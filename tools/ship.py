#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交活：把「改完了」变成「提交好了、推送了、进度记上了」。

为什么要多这一层：自动化跑起来之后，没人盯着 `git add .`。
这个脚本干三件人工容易偷懒的事——

1. **卡范围**：拿 `git status` 的改动去比对任务书里的 `files`，
   改到别人的文件直接拒收（这是 M0/M1/M2 并行不打架的根本保障）；
2. **过门禁**：跑 `tools/gate.py`，不过就不许提交；
3. **记账**：提交、推送、`next_task --complete`，一步都不许跳。

用法：
    python tools/ship.py --task T01 -m "feat(custom_pronunciation): 自定义读音词库 (T01)"
    python tools/ship.py --task T01 -m "..." --dry-run      # 只看范围和门禁，不提交
    python tools/ship.py --task T01 -m "..." --skip-gate    # 仅限救援（会记警告）
    python tools/ship.py --release v1.3.0 -m "chore: 发布 v1.3.0"

退出码：0 成功；1 范围越界/门禁不过/提交失败；2 参数问题。
"""
from __future__ import annotations

import argparse
import fnmatch
import io
import json
import os
import subprocess
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASKS_FILE = os.path.join(ROOT, "backlog", "tasks.json")
PY = sys.executable

# 状态与日志不算「代码改动」，谁都可以写
ALWAYS_OK = (".team/",)


def run(cmd, timeout=900, check=False):
    proc = subprocess.run(cmd, cwd=ROOT, timeout=timeout,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = (proc.stdout or b"").decode("utf-8", "replace")
    if check and proc.returncode != 0:
        raise SystemExit(f"命令失败：{' '.join(cmd)}\n{out}")
    return proc.returncode, out


def git(*args, **kw):
    return run(["git"] + list(args), **kw)


def unlock() -> None:
    """交活成功即视为这一轮结束，放掉工作树锁（PM 忘了也会被这里补上）。"""
    run([PY, os.path.join("tools", "next_task.py"), "--unlock"], timeout=60)


def load_task(task_id: str) -> dict:
    with io.open(TASKS_FILE, encoding="utf-8") as f:
        tasks = json.load(f)["tasks"]
    for task in tasks:
        if task["id"] == task_id:
            return task
    raise SystemExit(f"没有这个任务：{task_id}")


def changed_paths() -> list:
    # core.quotepath=false：不然中文文件名会被转义成 \345\274\200 这种八进制，
    # git add 时就找不到文件（本项目根目录就有中文名的开发文档）。
    _, out = git("-c", "core.quotepath=false", "status", "--porcelain")
    paths = []
    for line in out.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip()
        if " -> " in path:          # 重命名
            path = path.split(" -> ", 1)[1]
        paths.append(path.strip('"'))
    return paths


def allowed(path: str, patterns) -> bool:
    if any(path.startswith(prefix) for prefix in ALWAYS_OK):
        return True
    for pattern in patterns:
        if pattern.endswith("/**"):
            head = pattern[:-3]
            if path == head or path.startswith(head + "/"):
                return True
        elif fnmatch.fnmatchcase(path, pattern):
            return True
    return False


def gate(stage: str, tag: str = "") -> bool:
    cmd = [PY, os.path.join("tools", "gate.py"), "--stage", stage]
    if tag:
        cmd += ["--tag", tag]
    code, out = run(cmd, timeout=1500)
    print(out.strip()[-4000:])
    return code == 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="交活流水线")
    parser.add_argument("--task", help="任务号，例如 T01")
    parser.add_argument("--release", help="发版号，例如 v1.3.0（与 --task 二选一）")
    parser.add_argument("--pm", action="store_true",
                        help="PM 维护轮：允许改任意文件（改契约、修工具、补文档）")
    parser.add_argument("-m", "--message", required=True, help="提交信息")
    parser.add_argument("--dry-run", action="store_true", help="只检查不提交")
    parser.add_argument("--skip-gate", action="store_true", help="跳过门禁（救援用）")
    parser.add_argument("--no-push", action="store_true", help="只提交不推送（不推荐）")
    args = parser.parse_args(argv)

    if bool(args.task) == bool(args.release) and not (args.pm and not args.task and not args.release):
        parser.error("--task / --release / --pm 必须且只能给一个")

    paths = changed_paths()
    if not paths:
        print("工作区没有改动，没什么可交的。")
        return 1

    if args.pm:
        print("PM 维护轮：允许改动全部文件。")
        for path in paths:
            print("  " + path)
        stage, tag = "fast", ""
    elif args.task:
        task = load_task(args.task)
        patterns = task.get("files") or []
        bad = [p for p in paths if not allowed(p, patterns)]
        print(f"任务 {args.task} {task['key']}（{task['owner']}）")
        print("允许改：" + ", ".join(patterns))
        for path in paths:
            print(("  ok   " if allowed(path, patterns) else "  越界 ") + path)
        if bad:
            print("\n拒收：下面这些文件不在本任务的范围里。")
            for path in bad:
                print("  · " + path)
            print("要动它们，先找 PM 改任务书的 files 字段，或者撤回这些改动"
                  "（git checkout -- <path>）。")
            return 1
        stage = "fast"
        tag = ""
    else:
        stage = "full"
        tag = args.release
        print(f"发版 {args.release}：允许改动全部文件，门禁走 full 档。")

    if args.skip_gate:
        print("[警告] 跳过了门禁，这次提交没有验收背书。")
    elif not gate(stage, tag):
        print("\n门禁未通过，不予提交。")
        return 1

    if args.dry_run:
        print("\n--dry-run：范围与门禁都过了，但不提交。")
        return 0

    code, _ = git("add", "--", *paths)
    if code != 0:
        print("git add 失败")
        return 1
    code, out = git("-c", "i18n.commitEncoding=utf-8", "commit", "-m", args.message)
    print(out.strip())
    if code != 0:
        print("提交失败")
        return 1

    _, sha = git("rev-parse", "--short", "HEAD")
    sha = sha.strip()
    print(f"提交 {sha}")

    if not args.no_push:
        code, out = git("push", "origin", "HEAD", timeout=300)
        print(out.strip()[-2000:])
        if code != 0:
            print("推送失败——本地提交还在，网络恢复后 `git push` 即可。")
            return 1

    if args.task:
        code, out = run([PY, os.path.join("tools", "next_task.py"),
                         "--complete", args.task, "--commit", sha], timeout=120)
        print(out.strip())
        unlock()
        return 0

    if args.pm:
        print(f"PM 维护提交 {sha} 完成（不占任务号）。")
        unlock()
        return 0

    code, out = git("tag", "-a", args.release, "-m", f"release {args.release}")
    print(out.strip() or f"已打 tag {args.release}")
    if not args.no_push:
        git("push", "origin", args.release, timeout=300)
    code, out = run([PY, os.path.join("tools", "next_task.py"),
                     "--release-done", "--tag", args.release], timeout=120)
    print(out.strip())
    unlock()
    print(f"\n发版收尾完成：{args.release}  {datetime.now().isoformat(timespec='seconds')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
