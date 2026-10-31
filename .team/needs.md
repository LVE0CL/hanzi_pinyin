# 待办交接（谁写谁改共享文件）

员工在干活时发现「必须动共享文件才能继续」，就往下记一条，然后放弃这一轮。
PM 在维护轮里处理，处理完把条目划掉并把提交号写在后面。

格式：

```
## needs#1 · 2026-10-31 · 提出人 M1 · 关联 T05
要什么：store 增一个只读 `review_streak()`
为什么：学习统计要算连续复习天数，现在只能自己遍历
影响：不改接口只能重复实现一遍过滤逻辑
处理：<PM 填：done in <sha> / 转成 Txx / 不做，理由>
```

## needs#1 · 2026-10-31 · 提出人 M0 · 关联 T01

要什么：`_accept.py` 必须能正常退出，且 stdout 钉成 UTF-8

为什么：开工前先跑基线门禁，`界面验收 _accept.py` 卡满 300s 超时。手工复现：
43/43 全过、结果打印完，进程却停在 `threading._shutdown()` 里等**非守护**的
pystray 托盘线程与 pynput 监听线程，永不返回。另有一次跑到一半崩在
`UnicodeEncodeError: 'gbk' codec can't encode character '\u2212'`——中文 Windows
下管道默认 GBK，脚本要打印 `−`/`📌` 就炸，而 `gate.py` 是按 UTF-8 解子进程输出的，
两边编码假设对不上。

影响：fast 门禁基线就是红的，12 个任务一个都交不了（`ship.py` 门禁不过拒收）；
即使侥幸过了，崩在中途退出码也是 1，看起来像"验收没过"，其实一项都没验完。

处理：本维护轮已修——`_accept.py` 结尾改 `os._exit(0/1)`（与 `_s2/_s3/_s4` 一致）、
开头 `sys.stdout.reconfigure(encoding="utf-8")`；连跑 3 次均 8.1s、exit=0。

## needs#2 · 2026-10-31 · 提出人 M0 · 关联 T01

要什么：`_s4_check.py` 不要锁死「已实现模块 2 个」

为什么：断言写的是 `sorted(all_feats) == ["handwriting", "tone_contour"]`。T01 起
每个任务都要新增一个 Feature 模块，注册表立刻变成 3 个，这条断言必红——等于谁先
交活谁就得回来改别人的验收脚本。

影响：不改的话 12 个任务会**全部**卡在同一条断言上，且员工无权改（脚本不在
`task.files` 白名单里），只能一轮轮 `--fail`。

处理：本维护轮已改成 `{"handwriting", "tone_contour"} <= set(all_feats)`——
只验两个参考实现还在，模块总数交给注册表与开关，契约交给后面的挂点检查。

## needs#3 · 2026-10-31 · 提出人 M0 · 关联 T01

要什么：`.gitignore` 的 `/_*.py` 要放过门禁依赖的五个脚本

为什么：`_accept.py` / `_bugfix_test.py` / `_s2_check.py` / `_s3_check.py` /
`_s4_check.py` 全被这条规则挡在版本库外（`git ls-files` 为空）。而 `tools/gate.py`
写死要跑它们，`gate_script()` 遇到文件不存在会 `return True, 0.0, "脚本不存在，跳过"`。

影响：新克隆的仓库根本带不上门禁——`gate.py` 五道验收全部"跳过"，门禁假绿，
`ship.py` 拿它当背书放行。这次修的 bug 也提交不上去。

处理：本维护轮已加 `!/_accept.py` 等五条例外（其余 `_xxx.py` 调试脚本仍忽略）。

## needs#4 · 2026-10-31 · 提出人 PM · 关联 发版 v1.3.0

要什么：`HanziPopup.quit()` 里 pystray / pynput 的线程要真的能停

为什么：needs#1 的根因在应用侧——`_tray.stop()` 与 `_mouse.stop()` 之后，托盘线程
仍停在 `_mainloop()`、pynput 线程仍停在 `win32.__iter__`，都是非守护线程。门禁脚本
已经用 `os._exit` 绕过去了，但**真实用户**点「退出」也会残留进程：残留进程占着
单实例端口，下次双击图标被判成"已有实例"，`sendall("show")` 后自己退出，表现为
"程序打不开"。

影响：这是用户可见缺陷，不是测试瑕疵；本次只做了兜底，没动库内部。

处理：本维护轮已在 `quit()` 末尾加 0.8s 硬退出兜底（配置此时已原子落盘，无数据风险）。
**根治留给发版轮**：把 `Icon.run_detached()` 换成自建 daemon 线程、pynput 监听器
`_thread.daemon = True`，然后去掉兜底。

