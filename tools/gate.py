#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""质量门禁：一次跑完全部验收，任何一道不过就返回非 0。

自动化每一轮都要过这道门才允许提交——人是可以商量的，门禁不商量。

两个档位：
    --stage fast   开发期每一轮用。自检 + 四套验收 + 导入体检，约 40 秒。
    --stage full   波次末与发版用。在 fast 之上再打 onedir / onefile 两个包，
                   并对 exe 跑 --selftest，约 6~12 分钟。

用法：
    python tools/gate.py --stage fast
    python tools/gate.py --stage full --tag v1.3.0

退出码：0 全过；1 有门禁没过；2 环境问题（找不到带 tkinter 的解释器）。
结果同时写到 .team/gate.log，最后一轮结论在 .team/gate.json。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEAM = os.path.join(ROOT, ".team")
LOG = os.path.join(TEAM, "gate.log")
RESULT = os.path.join(TEAM, "gate.json")

# 打包必须放在短 ASCII 路径下：中文长路径拷 VCRUNTIME140.dll 会 PermissionError
BUILD_DIR = r"C:\hppbuild"
SIZE_LIMIT_MB = 35.0

_log_lines: list = []


def _decode(raw: bytes) -> str:
    """解子进程输出：先 UTF-8，解不开再 GBK。

    中文 Windows 的管道默认 GBK，而验收脚本有的已强制 UTF-8、有的一直是 GBK，
    上下文两种字节混着来。只用 UTF-8 硬解会得到一串 U+FFFD，再 print 到 GBK
    控制台就是 UnicodeEncodeError——门禁自己被自己搞崩（ship.py 里踩过一次）。
    """
    for encoding in ("utf-8", "gbk"):
        try:
            return raw.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace").strip()


def _harden_console() -> None:
    """控制台编码兜底：遇到 GBK 编不出来的字符就替换，别让打印把进程带走。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass


def log(msg: str = "") -> None:
    print(msg, flush=True)
    _log_lines.append(msg)


def _run(cmd, cwd=None, timeout=180):
    """跑一条命令，返回 (ok, 耗时秒, 输出尾部)。"""
    start = time.time()
    try:
        proc = subprocess.run(
            cmd, cwd=cwd or ROOT, timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
    except subprocess.TimeoutExpired:
        return False, time.time() - start, f"超时（>{timeout}s）"
    except FileNotFoundError as exc:
        return False, time.time() - start, f"命令不存在：{exc}"
    out = _decode(proc.stdout or b"")
    tail = "\n".join(out.splitlines()[-12:])
    return proc.returncode == 0, time.time() - start, tail


def resolve_python() -> str:
    """找一个能 import tkinter + PIL 的解释器。

    PATH 上的 python 可能是 WorkBuddy 自带的精简版，没有 tkinter，
    拿它跑 --selftest 会直接 sys.exit。所以这里必须实测，不能信 sys.executable。
    """
    def usable(exe: str) -> bool:
        try:
            proc = subprocess.run(
                [exe, "-c", "import tkinter, PIL; print('ok')"],
                timeout=60, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
        except Exception:
            return False
        return proc.returncode == 0

    candidates = []
    if os.environ.get("HPP_PY"):
        candidates.append(os.environ["HPP_PY"])
    candidates.append(sys.executable)
    local = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Python", "bin", "python.exe")
    candidates.append(local)
    candidates.extend(["python", "python3", "py"])

    tried = []
    for exe in candidates:
        if not exe or exe in tried:
            continue
        tried.append(exe)
        if usable(exe):
            return exe
    log("找不到带 tkinter + Pillow 的 Python 解释器。已尝试：" + ", ".join(tried))
    log("用 HPP_PY=<解释器绝对路径> 指定一个再来。")
    sys.exit(2)


def gate_selftest(py: str) -> tuple:
    ok, cost, tail = _run([py, "hanzi_pinyin.py", "--selftest"], timeout=180)
    return ok, cost, tail


def gate_script(py: str, script: str) -> tuple:
    path = os.path.join(ROOT, script)
    if not os.path.exists(path):
        return True, 0.0, "脚本不存在，跳过"
    ok, cost, tail = _run([py, script], timeout=300)
    return ok, cost, tail


def gate_imports(py: str) -> tuple:
    """逐个 import 包内模块，抓「搬完文件忘了改 import」这类伤。"""
    code = (
        "import importlib, os, sys, traceback\n"
        "bad = []\n"
        "for base, dirs, files in os.walk('hpp'):\n"
        "    dirs[:] = [d for d in dirs if d != '__pycache__']\n"
        "    for f in files:\n"
        "        if not f.endswith('.py'):\n"
        "            continue\n"
        "        rel = os.path.join(base, f)[:-3].replace(os.sep, '.')\n"
        "        if rel.endswith('.__init__'):\n"
        "            rel = rel[:-9]\n"
        "        try:\n"
        "            importlib.import_module(rel)\n"
        "        except Exception:\n"
        "            bad.append(rel + ' -> ' + traceback.format_exc().strip().splitlines()[-1])\n"
        "print('\\n'.join(bad) if bad else 'all modules import ok')\n"
        "sys.exit(1 if bad else 0)\n"
    )
    ok, cost, tail = _run([py, "-c", code], timeout=180)
    return ok, cost, tail


def gate_features(py: str) -> tuple:
    """每个已实现的模块都必须能被注册表找到并实例化。"""
    code = (
        "import sys\n"
        "from hpp.config import load_config\n"
        "from hpp.features.registry import load_features, collect_self_checks\n"
        "feats = load_features(load_config(), include_disabled=True)\n"
        "ids = sorted(feats)\n"
        "print('loaded:', ', '.join(ids))\n"
        "bad = [(n, d) for n, ok, d in collect_self_checks(feats) if not ok]\n"
        "for n, d in bad:\n"
        "    print('FAIL', n, d)\n"
        "sys.exit(1 if bad else 0)\n"
    )
    ok, cost, tail = _run([py, "-c", code], timeout=180)
    return ok, cost, tail


def dir_size_mb(path: str) -> float:
    total = 0
    for base, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                pass
    return total / (1024 * 1024)


def gate_build(py: str) -> tuple:
    """PyInstaller onedir + onefile，并对两个 exe 跑自检。"""
    out = []
    ok_all = True
    cost_all = 0.0
    if os.path.isdir(BUILD_DIR):
        shutil.rmtree(BUILD_DIR, ignore_errors=True)
    os.makedirs(BUILD_DIR, exist_ok=True)

    targets = [
        ("onedir", ["--windowed"], "HanziPinyinPopup"),
        ("onefile", ["--windowed", "--onefile"], "HanziPinyinPopup-portable"),
    ]
    for kind, extra, name in targets:
        cmd = [py, "-m", "PyInstaller", "--noconfirm", "--noupx",
               "--collect-submodules", "hpp.features",
               "--distpath", os.path.join(BUILD_DIR, "dist"),
               "--workpath", os.path.join(BUILD_DIR, "work"),
               "--specpath", BUILD_DIR,
               "--name", name] + extra + ["hanzi_pinyin.py"]
        ok, cost, tail = _run(cmd, cwd=ROOT, timeout=900)
        cost_all += cost
        out.append(f"[{kind}] build {'ok' if ok else 'FAIL'} {cost:.0f}s")
        if not ok:
            ok_all = False
            out.append(tail)
            continue

        if kind == "onedir":
            exe = os.path.join(BUILD_DIR, "dist", name, name + ".exe")
            size = dir_size_mb(os.path.join(BUILD_DIR, "dist", name))
        else:
            exe = os.path.join(BUILD_DIR, "dist", name + ".exe")
            size = os.path.getsize(exe) / (1024 * 1024) if os.path.exists(exe) else 0.0
        out.append(f"[{kind}] 体积 {size:.1f} MB")

        if not os.path.exists(exe):
            ok_all = False
            out.append(f"[{kind}] 产物不存在：{exe}")
            continue
        sok, scost, stail = _run([exe, "--selftest"], cwd=os.path.dirname(exe), timeout=180)
        cost_all += scost
        out.append(f"[{kind}] exe --selftest {'ok' if sok else 'FAIL'}")
        if not sok:
            ok_all = False
            out.append(stail)
        if kind == "onefile" and size > SIZE_LIMIT_MB:
            out.append(f"[警告] 单文件 {size:.1f} MB 超过约定上限 {SIZE_LIMIT_MB} MB")
    return ok_all, cost_all, "\n".join(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="质量门禁")
    parser.add_argument("--stage", choices=["fast", "full"], default="fast")
    parser.add_argument("--tag", default="", help="本次门禁对应的版本，仅记录用")
    parser.add_argument("--json", action="store_true", help="只输出 JSON 结论")
    args = parser.parse_args(argv)

    os.makedirs(TEAM, exist_ok=True)
    _harden_console()
    started = datetime.now().astimezone().isoformat(timespec="seconds")
    py = resolve_python()
    if not args.json:
        log(f"门禁开始 {started}  档位 {args.stage}")
        log(f"解释器 {py}")
        log("-" * 68)

    checks = [
        ("启动自检 --selftest", gate_selftest),
        ("界面验收 _accept.py", lambda p: gate_script(p, "_accept.py")),
        ("缺陷回归 _bugfix_test.py", lambda p: gate_script(p, "_bugfix_test.py")),
        ("S2 分层检查", lambda p: gate_script(p, "_s2_check.py")),
        ("S3 界面零件检查", lambda p: gate_script(p, "_s3_check.py")),
        ("S4 模块契约检查", lambda p: gate_script(p, "_s4_check.py")),
        ("包内模块导入体检", gate_imports),
        ("功能模块加载与自检", gate_features),
    ]
    if args.stage == "full":
        checks.append(("PyInstaller 打包 + exe 自检", gate_build))

    failed = []
    records = []
    total = 0.0
    for name, fn in checks:
        ok, cost, tail = fn(py)
        total += cost
        records.append({"name": name, "ok": ok, "seconds": round(cost, 1)})
        if not args.json:
            log(f"{'PASS' if ok else 'FAIL'}  {name:<26} {cost:5.1f}s")
            if not ok:
                for line in (tail or "").splitlines():
                    log("      | " + line)
        if not ok:
            failed.append(name)

    verdict = {
        "stage": args.stage,
        "tag": args.tag,
        "started": started,
        "finished": datetime.now().astimezone().isoformat(timespec="seconds"),
        "seconds": round(total, 1),
        "interpreter": py,
        "ok": not failed,
        "failed": failed,
        "checks": records,
    }
    with io.open(RESULT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(verdict, f, ensure_ascii=False, indent=2)
        f.write("\n")
    with io.open(LOG, "a", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(_log_lines) + "\n")
        f.write(f"结论：{'全绿' if not failed else '未通过 ' + ', '.join(failed)}"
                f"  用时 {total:.1f}s\n")

    if args.json:
        print(json.dumps(verdict, ensure_ascii=False, indent=2))
    else:
        log("-" * 68)
        if failed:
            log(f"未通过：{', '.join(failed)}（共 {total:.1f}s）")
        else:
            log(f"全绿（共 {total:.1f}s）——可以提交")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
