# store 接口说明（M0 · T01）

`hpp/store.py` 是**用户数据**的落盘层，和 `config.json`（用户偏好）刻意分开：
配置坏了能恢复默认，数据坏了用户就白用了，所以写入走原子替换。

**M1 的 T05（生词本）/ T08 只读这份文档调接口，不要看实现猜。**
函数名一旦定下就别乱改；确需改签名，先改本文件再通知 PM。

---

## 1. 文件在哪

```
<config.json 所在目录>/store.json
```

`store_path()` 就是这么算的。**它跟着 `config_path()` 走**，因此：

- 正常运行时在 `%APPDATA%\汉字拼音浮窗\store.json`；
- `python hanzi_pinyin.py --config-dir .dev/M0`（或设 `HPP_CONFIG_DIR`）时，
  数据也一起挪进 `.dev/M0/`，不会碰用户真实数据——开发期隔离白拿。

损坏的旧文件会被改名成 `store.json.bad` 留证，然后按空库继续跑。

## 2. 文件长什么样

```json
{
  "schemaVersion": 1,
  "lexicon": { "银行": ["yín", "xíng"] },
  "words": {},
  "stats": {},
  "saved_at": "2026-10-31T08:31:00+00:00"
}
```

| 键 | 归属 | 说明 |
| --- | --- | --- |
| `schemaVersion` | store | 结构版本，当前 `1` |
| `lexicon` | T01 `custom_pronunciation` | `{词: [带调音节, ...]}`，音节数必须等于字数 |
| `words` | T04 `srs_review`（预留） | 生词本条目，M0 在 T04 里填 |
| `stats` | T10 / learning_stats（预留） | 统计计数 |
| `saved_at` | store | 最近一次写入的 **UTC** 时间戳，展示时再转本地时区 |

未列出的顶层键会被原样保留——想加新分区直接 `set_section()`，不用改 store。

## 3. 接口

全部接口都**不抛异常**，返回 `False` / 默认结构表示失败。
带 `path=` 的参数是给自检和测试用的，正常调用一律省略。

```python
from hpp import store

store.store_path() -> str
    # store.json 的绝对路径

store.default_data() -> dict
    # 空库结构（每次返回新 dict）

store.load(path=None) -> dict
    # 读库并规范化：缺键补默认、类型不对的丢、坏文件隔离后返回空库

store.save(data, path=None) -> bool
    # 原子写（.tmp → fsync → os.replace），自动刷新 saved_at

store.get_section(name, path=None, default=None)
store.set_section(name, value, path=None) -> bool
    # 任意顶层分区的读写；set_section 只动自己那一块，别的分区原样保留

store.get_lexicon(path=None) -> dict
    # 词库副本，随便改不影响磁盘

store.set_lexicon(entries, path=None, replace=False) -> dict
    # 写词条，默认合并；replace=True 表示「这份就是全部」。
    # 返回写完之后完整的词库（读到的是磁盘真值）

store.remove_lexicon(word, path=None) -> bool
    # 删一条，本来就没有 → False
```

## 4. 给 T05 生词本的用法

`words` 分区已经在结构里留好了，**不需要**改 `default_data()`：

```python
from hpp import store

words = store.get_section("words", default={})
words["银行"] = {"due": "2026-11-03T00:00:00+00:00", "ease": 2.5, "reps": 2}
store.set_section("words", words)
```

- 时间一律存 UTC ISO8601（带 `+00:00`），只在显示时转本地；
- 一次读写只碰一个分区，别 load 整个库、改、再 save 回去覆盖别人的分区。

## 5. 已知边界

- **不加锁跨进程**：单实例应用，同一时刻只有一个进程在写；进程内用 `RLock` 串行。
- **不做备份轮转**：只保留 `store.json.bad` 一份现场。
- **不压缩**：词条上千条也就几十 KB，不值得引入依赖。

## 6. 交接记录

- 2026-10-31 · T01 · `path / load / save / get_lexicon / set_lexicon / remove_lexicon`
  + 分区接口 `get_section / set_section` 落地，`store.json` 首次可用。
