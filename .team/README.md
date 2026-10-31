# .team —— 无人值守开发的现场

这个目录是「老板只按一次开始，剩下全自动」的那套东西的**现场记录**。
人看进度只需要一个命令：

```bash
python tools/next_task.py --status
```

## 目录里都是什么

| 路径 | 谁写 | 干什么用的 |
| --- | --- | --- |
| `progress.json` | `tools/next_task.py` | 唯一权威进度：每个任务的状态、失败次数、对应提交号 |
| `gate.log` / `gate.json` | `tools/gate.py` | 门禁流水与最近一次结论 |
| `roles/PM.md` | 人（PM） | **每一轮照着做的操作手册**，自动化读的就是它 |
| `roles/M0.md` `M1.md` `M2.md` | 人（PM） | 三个岗位的任务书：能改什么、红线、交付标准 |
| `needs.md` | 执行轮 | 干活时发现「必须改共享文件」就往这里记一条，不许自己动手 |
| `STOP` | `next_task.py` | 有这个文件，所有轮次立即停手（发版完成会自动写） |
| `store-api.md` | M0（T01） | 本地存储接口说明，M1 的 T05/T08 要读 |

## 一条指令跑完全程

```
python tools/next_task.py            # 算出这轮干什么（work T01 / release / stop）
   ↓ work
读 .team/roles/<owner>.md + 任务书 → 写代码 → python tools/gate.py --stage fast
   ↓ 全绿
python tools/ship.py --task T01 -m "feat(...): ..."     # 查范围 + 门禁 + 提交 + 推送 + 记账
   ↓
python tools/next_task.py            # 下一轮
```

`ship.py` 会拒绝两类提交：**改到别人文件**、**门禁不过**。所以「员工偷懒」这件事
在机制上被堵住了，不靠自觉。

## 停手与接管

| 想干什么 | 怎么做 |
| --- | --- |
| 立刻停 | 建一个空文件 `.team/STOP`（或 `echo stop > .team/STOP`） |
| 恢复继续 | 删掉 `.team/STOP` |
| 让某个任务重做 | `python tools/next_task.py --reset T05` |
| 跳过卡住的任务 | 它会自动 `blocked`（连续失败 2 次），不影响别人继续 |
| 只想知道进度 | `python tools/next_task.py --status`（只读，不改状态） |
| 发版 | 全部任务 done 后队列自动要求 release，走 `tools/ship.py --release v1.3.0` |

## 卡住是怎么回事

`blocked` 不是失败，是「这个人卡住了，先跳过」。两种来路：

1. 同一任务连续 2 轮没过门禁；
2. 执行轮发现要改共享文件（登记到 `needs.md` 后主动放弃）。

处理办法是先看 `needs.md` 和 `gate.log` 的最后一次 FAIL，改完 `--reset` 即可。
卡住的条目不影响其他任务推进——这是刻意设计的，一台机器卡不死整条线。

## 一个前提

并行开发靠 `--config-dir` 与端口隔离，三个岗位各自一套，互不踩：

| 岗位 | 配置目录 | 端口 |
| --- | --- | --- |
| M0 | `.dev/M0` | 47661 |
| M1 | `.dev/M1` | 47662 |
| M2 | `.dev/M2` | 47663 |

```bash
python hanzi_pinyin.py --config-dir .dev/M0
```
