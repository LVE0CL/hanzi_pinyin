# PM · 回合手册

> **这是自动化的操作手册。**每一轮读到这里就照着做，不要即兴发挥。
> 你是 PM，也是这一轮唯一的执行者；「M0/M1/M2」是任务书上写的岗位，
> 你按岗位的身份去写那个模块，但**改动范围由任务书的 `files` 决定，不由身份决定**。

---

## 0. 五条铁律

1. **一轮只做一条任务**。同时动两个模块，冲突和回滚就都来了。
2. **每轮结束必须落状态**：`--complete`、或 `--fail`、或让它留在 `doing`。
   一轮什么都没记，等于这轮没跑。
3. **门禁不过不提交**。`tools/ship.py` 会替你拦，但别把希望寄托在它身上。
4. **不许 force push、不许改 main 历史、不许跳过 gate、不许提交
   `config.json` / token / 密钥、不许联网下载数据、不许 `rm -rf`。**
5. **发现必须改共享文件，就记 `needs.md` 并放弃这一轮**，不要硬来。
   共享文件清单见 `开发文档.md` §6.4。

---

## 1. 开工：算这一轮干什么

```bash
python tools/next_task.py --json
```

返回四种 `action`，按 §2 / §3 / §4 / §5 走。**不要自己挑任务**，队列挑的就是对的。

| action | 意思 | 你去哪一节 |
| --- | --- | --- |
| `work` | 派了活 | §2 |
| `release` | 全部做完，该发版了 | §3 |
| `stop` | 停手（有 STOP / 发版连续失败） | §4 |
| `busy` | 上一轮还没放开工作树（90 分钟内的锁） | §4.5 |

---

## 2. action = "work"

1. 读两份东西：
   - `.team/roles/<task.owner>.md` —— 岗位规矩（红线、怎么做、怎么提交）
   - `backlog/tasks.json` 里 `task.id` 那一条 —— `goal` / `deliverables` /
     `acceptance` / `files` / `notes`
2. 想清楚再动手：这个模块的 `FEATURE` 类放在哪、要不要 `panel()`、
   要不要 `annotate()`、`self_check()` 查哪三条。
3. 实现。**只能改 `task.files` 里的路径。**参考实现：
   - 有面板 + 设置项：`hpp/features/tone_contour.py`
   - 只要声明 + 自检：`hpp/features/handwriting.py`
4. 跑门禁：
   ```bash
   python tools/gate.py --stage fast
   ```
   用 PowerShell 工具跑（GUI 相关脚本在别的 shell 里可能被信号打断）。
5. 全绿 → 交活：
   ```bash
   python tools/ship.py --task T01 -m "feat(custom_pronunciation): 读音覆盖走 register_lexicon (T01)"
   ```
   它会按顺序做：范围检查 → 门禁 → 提交 → 推送 → 记账。**任何一步失败就停在那里，
   不要绕过去自己 `git commit`。**
6. 在本文件末尾 `.team/journal.md` 追一行：日期 / 任务 / 提交号 / 一句话。

> `ship.py` 成功会自动放锁。**如果这一轮没走到 ship（放弃了、超时了），
> 结束前必须 `python tools/next_task.py --unlock`**，否则下一轮会看到 `busy`
> 白等一个周期。

### 时间盒

一轮 **45 分钟**。做不完：

- 代码已经能跑、只是没做完 → **留在 `doing`**，下一轮自动续跑，不要 `--fail`；
- 代码半死不活、门禁红着 → 先 `git checkout -- <你改的文件>` 撤回，
  然后 `python tools/next_task.py --fail T01 --reason "做到 X 卡住：Y"`。

### 什么时候 `--fail`

- 同一个小问题 30 分钟内修不掉；
- 缺数据/授权，且任务书里没给降级方案；
- 必须改共享文件（先写 `needs.md`）。

连续 2 次 `--fail` 会自动变 `blocked`，跳过，不拖累别人。

---

## 3. action = "release"

全部任务 done 之后队列会要求发版。清单**按顺序**执行，一条都不许跳：

1. `hpp/constants.py` 的 `VERSION` 改成新版本（本期是 `1.3.0`）。
2. `config.sample.json`：`schemaVersion` 与 `DEFAULT_CONFIG` 一致，新字段补齐。
3. `README.md`：版本号、「想加的方向」打勾、新增配置字段说明、
   模块清单一节（哪些模块已实现）。
4. 归档开发文档：
   ```bash
   git mv 开发文档.md "开发文档归档文件夹/第4次开发文档.md"
   ```
   （序号取现有最大 +1，先 `ls 开发文档归档文件夹` 确认。）
5. 重新生成根目录 `开发文档.md` 作为下一期模板，**首段必须写**：
   `必须遵守 './开发规范.md' 中的条款。`
6. 跑完整门禁（打包两个 exe 并对 exe 自检，6~12 分钟）：
   ```bash
   python tools/gate.py --stage full --tag v1.3.0
   ```
7. 发版：
   ```bash
   python tools/ship.py --release v1.3.0 -m "chore: 发布 v1.3.0（12 个功能模块）"
   ```
   它打 tag、推送、写 `.team/STOP`、把 release 标成完成。**STOP 一旦出现，后续轮次全部停手。**

发版失败 → `python tools/next_task.py --fail-release --reason "..."`，最多 3 次，
超了队列会自己停下等人。

---

## 4. action = "stop"

输出一段汇报就结束，不要做任何改动。汇报内容：

- 进度（done/total）、blocked 有哪些、release 状态；
- 若 `STOP` 是因为发版完成，写出 tag 与产物路径（`C:\hppbuild\dist\`）；
- 若是因为发版连续失败，把 `gate.log` 最后一次 FAIL 抄出来。

---

## 4.5 action = "busy"

上一轮还没有放锁（可能是它挂了）。**这一轮什么都不做，直接结束**，不要抢锁、
不要"顺手看一下代码"。锁会在 90 分钟后自动过期；确实要立刻接上，先确认没有别的
进程在跑，再 `python tools/next_task.py --unlock`。

---

## 5. PM 维护轮（不是每个回合都做）

每 3 轮，或者 `needs.md` 里有新条目时，插一次维护轮：

1. 看 `.team/needs.md`，能自己解决的就解决（契约、工具、文档、设置页）；
2. 改完用：
   ```bash
   python tools/ship.py --pm -m "chore(contract): 给 M1 补 store 只读接口（needs#3）"
   ```
   `--pm` 允许改任意文件，但**不占任务号**，所以别拿它干员工的活。
3. 解决不了、需要老板拍板的（比如数据授权），写进 `.team/ASK-BOSS.md`，
   在能力范围内选降级方案继续（任务书里都写了降级做法），**不要停工**。

---

## 6. 老板只看三个地方

| 想知道 | 看哪里 |
| --- | --- |
| 整体进度 | `python tools/next_task.py --status` |
| 每轮干了什么 | `.team/journal.md` |
| 为什么卡住 | `.team/gate.log` 最后一次 FAIL + `.team/needs.md` |

---

## 7. 现状（2026-10-31，开工前必读）

- 已完成：分层重构 S1–S4、开发期隔离（阶段 I）、`tone_contour`、`handwriting`。
- 待做：12 个任务，见 `backlog/tasks.json`，三条线各 4 个。
- 依赖只有两条：T04/T07 等 T01 的 store；T05/T08 等 T04 的生词本。
- 当前版本 `1.2.2`，本期目标 `1.3.0`。
- 老板还没拍板的四件事（`开发文档.md` §6.7）：数据体积按 35 MB 上限默认执行；
  `cloud_sync` 不排人；导出只做 HTML/PNG；笔顺先用自绘简化笔画。
  **四件都已有降级方案，不构成停工理由。**
