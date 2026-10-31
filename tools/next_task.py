#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务队列状态机：决定「这一轮该谁干什么」。

设计目标是**无人值守可续跑**：每一轮自动化读一次状态、派一个任务；做完标记
done，做不动标记 attempts，两次做不动就 blocked 跳过。所有状态都在
`.team/progress.json` 里，进程挂了、机器重启都不会丢进度。

用法：
    python tools/next_task.py --json       # 给自动化读的机器可读输出
    python tools/next_task.py --status     # 给人看的进度表
    python tools/next_task.py --complete T01
    python tools/next_task.py --fail T01 --reason "缺少数据源"
    python tools/next_task.py --release-done --tag v1.3.0
    python tools/next_task.py --fail-release --reason "打包失败"
    python tools/next_task.py --reset T01   # 人工干预：退回 pending

退出码：0 正常；2 参数/状态文件问题。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASKS_FILE = os.path.join(ROOT, "backlog", "tasks.json")
STATE_FILE = os.path.join(ROOT, ".team", "progress.json")
STOP_FILE = os.path.join(ROOT, ".team", "STOP")

MAX_ATTEMPTS = 2          # 同一个任务连续失败这么多次就 blocked
MAX_RELEASE_ATTEMPTS = 3  # 发版失败这么多次就停下等人


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_json(path: str) -> dict:
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def load_tasks() -> list:
    tasks = load_json(TASKS_FILE)["tasks"]
    return sorted(tasks, key=lambda t: (t.get("order", 999), t["id"]))


def load_state(tasks: list, path: str) -> dict:
    if os.path.exists(path):
        try:
            state = load_json(path)
        except Exception:
            state = {}
    else:
        state = {}
    state.setdefault("version", 1)
    state.setdefault("release", {"done": False, "attempts": 0, "tag": None, "reason": ""})
    entries = state.setdefault("tasks", {})
    for task in tasks:
        entries.setdefault(task["id"], {
            "status": "pending", "attempts": 0, "commit": None,
            "note": "", "updated": None,
        })
    state["updated"] = now()
    return state


def mark(state: dict, task_id: str, **fields) -> None:
    entry = state["tasks"].setdefault(task_id, {})
    entry.update(fields)
    entry["updated"] = now()


def eligible(task: dict, state: dict) -> bool:
    for dep in task.get("depends_on") or []:
        if state["tasks"].get(dep, {}).get("status") != "done":
            return False
    return True


def pick(tasks: list, state: dict):
    """返回 (task, resumed)。优先续跑做了一半的，再按 order 取第一个可做的。"""
    for task in tasks:
        entry = state["tasks"][task["id"]]
        if entry["status"] == "doing" and entry["attempts"] < MAX_ATTEMPTS:
            if eligible(task, state):
                return task, True
            # 依赖没好的 doing 是异常状态，退回 pending 重排
            mark(state, task["id"], status="pending")
    for task in tasks:
        entry = state["tasks"][task["id"]]
        if entry["status"] != "pending":
            continue
        if not eligible(task, state):
            continue
        return task, False
    return None, False


def summary(tasks: list, state: dict) -> dict:
    counts = {"done": 0, "doing": 0, "pending": 0, "blocked": 0}
    for task in tasks:
        status = state["tasks"][task["id"]]["status"]
        counts[status] = counts.get(status, 0) + 1
    blocked = [t["id"] for t in tasks if state["tasks"][t["id"]]["status"] == "blocked"]
    return {
        "total": len(tasks),
        "done": counts["done"],
        "doing": counts["doing"],
        "pending": counts["pending"],
        "blocked": counts["blocked"],
        "blocked_ids": blocked,
    }


def decide(tasks: list, state: dict) -> dict:
    """核心：算出这一轮该做什么。"""
    info = summary(tasks, state)

    if os.path.exists(STOP_FILE):
        return {"action": "stop", "reason": "存在 .team/STOP（发版完成或人工叫停）",
                "progress": info}

    if not state["release"]["done"]:
        left = info["pending"] + info["doing"]
        if left == 0:
            attempts = state["release"].get("attempts", 0)
            if attempts >= MAX_RELEASE_ATTEMPTS:
                return {"action": "stop", "progress": info,
                        "reason": f"发版连续失败 {attempts} 次，停下等人处理："
                                  f"{state['release'].get('reason', '')}"}
            return {"action": "release", "progress": info,
                    "blocked": info["blocked_ids"],
                    "attempts": attempts}

    task, resumed = pick(tasks, state)
    if task is None:
        return {"action": "stop", "progress": info, "reason": "没有可执行的任务"}

    # 注意：decide() 只算，不改状态。真正落地在 main() 里做，
    # 否则 --status 这种看一眼的操作也会把任务标成 doing。
    return {
        "action": "work",
        "progress": info,
        "resumed": resumed,
        "attempts": state["tasks"][task["id"]]["attempts"],
        "role_file": os.path.join(".team", "roles", f"{task['owner']}.md"),
        "task": task,
    }


def commit_decision(state: dict, verdict: dict) -> None:
    """把 decide() 的结论落到状态里（只有 work 会改状态）。"""
    if verdict.get("action") == "work":
        task_id = verdict["task"]["id"]
        if state["tasks"][task_id]["status"] != "doing":
            mark(state, task_id, status="doing")


def print_status(tasks: list, state: dict) -> None:
    info = summary(tasks, state)
    print("=" * 68)
    print(f"进度 {info['done']}/{info['total']}  "
          f"待做 {info['pending']}  在做 {info['doing']}  卡住 {info['blocked']}")
    if info["blocked_ids"]:
        print("卡住：", ", ".join(info["blocked_ids"]))
    print("=" * 68)
    icons = {"done": "✔", "doing": "▶", "pending": "·", "blocked": "✖"}
    for task in tasks:
        entry = state["tasks"][task["id"]]
        print(f" {icons.get(entry['status'], '?')} {task['id']}  "
              f"{task['owner']}  波次{task['wave']}  {task['key']:<22} "
              f"{entry['status']:<8} 试{entry['attempts']}")
        if entry.get("note"):
            print(f"        └ {entry['note']}")
    rel = state["release"]
    print("-" * 68)
    print(f"发版：{'已完成 ' + str(rel.get('tag')) if rel['done'] else '未开始'}"
          f"（尝试 {rel.get('attempts', 0)} 次）")
    verdict = decide(tasks, state)
    print(f"下一轮：{verdict['action']}"
          + (f"  {verdict['task']['id']} {verdict['task']['key']}" if verdict.get("task") else "")
          + (f"  ({verdict['reason']})" if verdict.get("reason") else ""))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="自动开发任务队列")
    parser.add_argument("--state", default=STATE_FILE, help="状态文件路径（测试用）")
    parser.add_argument("--json", action="store_true", help="输出机器可读结果")
    parser.add_argument("--status", action="store_true", help="打印进度表")
    parser.add_argument("--complete", metavar="ID", help="标记任务完成")
    parser.add_argument("--fail", metavar="ID", help="标记任务失败一次")
    parser.add_argument("--reason", default="", help="失败原因")
    parser.add_argument("--commit", default=None, help="对应提交号（可选）")
    parser.add_argument("--reset", metavar="ID", help="把任务退回 pending")
    parser.add_argument("--release-done", action="store_true", help="标记发版完成")
    parser.add_argument("--tag", default=None, help="发版 tag")
    parser.add_argument("--fail-release", action="store_true", help="记一次发版失败")
    args = parser.parse_args(argv)

    tasks = load_tasks()
    state = load_state(tasks, args.state)
    ids = {t["id"]: t for t in tasks}

    if args.complete:
        if args.complete not in ids:
            print(f"没有这个任务：{args.complete}", file=sys.stderr)
            return 2
        mark(state, args.complete, status="done", note=args.reason or "",
             **({"commit": args.commit} if args.commit else {}))
        save_json(args.state, state)
        print(f"{args.complete} 标记完成")
        return 0

    if args.fail:
        if args.fail not in ids:
            print(f"没有这个任务：{args.fail}", file=sys.stderr)
            return 2
        entry = state["tasks"][args.fail]
        attempts = int(entry.get("attempts", 0)) + 1
        status = "blocked" if attempts >= MAX_ATTEMPTS else "pending"
        mark(state, args.fail, status=status, attempts=attempts, note=args.reason)
        save_json(args.state, state)
        print(f"{args.fail} 失败第 {attempts} 次 -> {status}")
        return 0

    if args.reset:
        mark(state, args.reset, status="pending", attempts=0, note="")
        save_json(args.state, state)
        print(f"{args.reset} 已退回 pending")
        return 0

    if args.release_done:
        state["release"].update({"done": True, "tag": args.tag, "reason": ""})
        mark_all = {"updated": now()}
        state.update(mark_all)
        save_json(args.state, state)
        with io.open(STOP_FILE, "w", encoding="utf-8", newline="\n") as f:
            f.write(f"发版完成：{args.tag}\n{now()}\n")
        print(f"发版完成 {args.tag}，已写 .team/STOP")
        return 0

    if args.fail_release:
        rel = state["release"]
        rel["attempts"] = int(rel.get("attempts", 0)) + 1
        rel["reason"] = args.reason
        save_json(args.state, state)
        print(f"发版失败第 {rel['attempts']} 次：{args.reason}")
        return 0

    if args.status:
        print_status(tasks, state)
        return 0

    verdict = decide(tasks, state)
    commit_decision(state, verdict)
    save_json(args.state, state)
    if args.json:
        print(json.dumps(verdict, ensure_ascii=False, indent=2))
    else:
        print_status(tasks, state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
