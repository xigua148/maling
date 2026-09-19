# 码铃（MaLing）v2.4 增量架构设计 ——「记忆捕获链路修复 × 续接排序升级 × 落盘安全网」（小型 · 零新增依赖 · 零 schema 变更）

- 版本：v2.4（承接 `docs/prd-v24.md`）
- 文档状态：**已实现并全量回归**（2397 passed / 1 failed 系既有环境问题，见 §4.3）
- 维护人：架构（高见远）
- 基线：`v2.3.1`（`version.json`）
- 关联：`docs/prd-v24.md`（需求池与红线）、`docs/design-v22.md`（被本轮解冻的冻结声明）
- **本文所有行号均以改动后的源码为准**；§1.3 的"改动前"行号另行标注

---

## 1. 范围与现状基线（先读我）

### 1.1 范围与 Non-goals

**范围**：`memory.py` + `gui/chat_service.py` 两个文件的**纯增量**改动，分三组：

| 组 | 内容 | 决策编号 |
|---|---|---|
| C | GUI 捕获链路接通（含话题提取质量门） | D-V24-01 / D-V24-02 |
| S | 续接排序多因子化 | D-V24-03 |
| P | 落盘安全网（快照 + 损坏隔离） | D-V24-05 |
| F | 既有缺陷顺带修复（影像记忆排序确定性） | D-V24-04 |

**Non-goals**：见 `prd-v24.md` §4（N1–N7）。其中最重要的是 **N1/N2：不并入任何第三方代码** —— 本轮**零新增依赖**，完全自研实现。

### 1.2 ★ 既有测试硬约束（**不得推翻**）

改造前逐条核过既有 2353 个用例，以下为**红线级约束**，任何实现方案不得违反：

| # | 约束 | 来源 | 本轮如何满足 |
|---|---|---|---|
| B1 | `followup_score` 精确值语义（heart 后 `== 1`） | `test_memory.py::TestV16FollowupFeedback::test_heart_chat_mute`（:297）、`test_archived_topic_feedback`（:314）、`test_v16_companion.py::test_chat_panel_callback_writes_memory_only` | **不改该字段语义**：评分只"读"它，不写 |
| B2 | 排序 tie-break 方向 = 列表原序（idx 小者优先） | `test_memory.py::test_score_weighting`（:280）**实际依赖此 tie-break**（该用例把两话题拨到同一时间戳，删掉评分也照样绿） | 排序键保留 `-idx`，方向不变 |
| B3 | 时间窗外不入选 | `test_out_of_window_ignored`（:285）、`test_dedupe_within_7_days`、`test_mute_expires_after_14_days` | **硬门全部保留**，仅换排序键 |
| B4 | 群聊记忆提取**零调用** | `test_v17_batch4_f10.py::TestTripleIsolation`（:321-342，R-J④⑤ / 共享知识 26） | 挂载点置于群聊分流 `return` **之后** |
| B5 | `build_memory_context` 输出 ≤300 字符 | `test_v18_batch1.py::test_channel1_pinned_in_build_memory_context`（:160） | **本轮不动该函数**（仅 `pick_topic_followup` 的注释里原有"同分加权"描述同步更新） |
| B6 | 六个剧本直接读写 `followup_score` / `followup_muted_until` / `last_mentioned` | `companion_scenarios/S07,S11,S12,S13,S15,S17` | **字段名冻结** |
| B7 | 无 schema 变更即无需迁移 | 共享知识 18（任何 schema 增量须经 `_merge_defaults` 读时迁移，不写升级脚本、不升 `meta.version`） | 本设计**不新增任何持久化字段**，故该条不触发 |
| B8 | 测试数据隔离 | 共享知识 23（memory 测试一律 `filepath=tmp_path`） | 三个新测试文件全部遵守 |

### 1.3 已核实的关键对接点（源码逐行核，**禁止照抄旧记忆**）

| 对接点 | 位置（改动后） | 说明 |
|---|---|---|
| 记忆单实例 | `session.py:80` `self.memory_mgr = MemoryManager()` | 全进程唯一生产实例；GUI 经 `gui/adapters/gui_chat_session.py:84-86` `__getattr__` 透传 |
| 取记忆管理器 | `gui/chat_service.py::_v18_memory_mgr`（读 `app_ctx.session.memory_mgr`） | 缺失返回 `None` → 全链静默降级 |
| 后置钩子聚集点 | `gui/chat_service.py::_on_stream_finished`（`self._current_user_text` 与 `_pending_vision` 均在此消费） | 既有钩子：亲密度 / 影像记忆 / agent 事件 / 自动朗读 |
| **群聊分流** | `_on_stream_finished` 顶部 `if self._group_active: ... return` | 注释原文已写明"三隔离（不写对齐历史 / 不计亲密度 / **不做记忆提取**）" |
| 暂存模式范本 | `_pending_vision`（声明 :1166 / 每轮清 :1283 / 置位 :1288-1292 / 消费 :2388-2389 / 取消清 :2490 / 失败清 :2513） | 新暂存槽完全镜像此模式 |
| CLI 既有调用 | `session.py:595`（`extract_from_dialogue`）、`session.py:600`（`archive_stale_topics`） | **保持原样不动**，GUI 侧为并列新增 |
| 落盘约定范本 | `gui/tavern/store.py:153-243`（L0–L6 阶梯 / `_rotate_backup` 复制式快照 / `_quarantine_corrupt` 改名保留） | `memory.py` 照此约定补齐 |

### 1.4 ★ 落点校正（**诚实指出，不照抄错误前提**）

1. **本轮最初的评估结论有两条不成立**，已在 `prd-v24.md` §1.4 详录：ALTM 的"防虚报机制"在码铃无落点；"RRF+PPR 检索层"是过度设计。
2. **"半衰期"曾在实现中被写成"时间常数"**：`recency = exp(-age/36)` 在 36h 处得 `0.368` 而非 `0.5`，与设计陈述（窗边缘 0.25、12h 处 0.79）不符。**该缺陷由新增测试 `test_half_life_value` 当场捕获**，已改为 `2 ** (-age/36)`。此事记录在此作为"测试先于实现写死语义"的有效性证据。
3. **`archive_stale_topics` 只搬运不删除**（`:548-549` 先 `archived.extend` 再替换 `active`，topic dict 原对象完整保留）—— 用户提出"尽量别做破坏性删除"约束时逐条审计确认，本轮**未新增任何删除路径**。既有删除点（`delete_preference` / `delete_topic_forever` / `delete_entity_event`）均为用户主动触发，未改。
4. **`test_score_weighting` 是弱测试**：它靠 tie-break 通过而非靠评分权重，因此**不能**当作评分公式的护栏（若把 tie-break 反转，删掉评分权重它反而仍绿）。已在新增测试里用更硬的用例补上。

---

## 2. 架构决策（D-V24-01 ~ D-V24-05）

### D-V24-01 捕获挂载：镜像 `_pending_vision` 的一次性暂存槽

**问题**：`_on_stream_finished(self, full_text, usage)` 的签名里**没有 user_text**，而捕获需要它。

**决策**：不新增服务层状态字段，而是镜像既有 `_pending_vision` 模式新增一个同构暂存槽 `_pending_memory_turn`，六个动作点位一一对应：

| 动作 | 位置 | 代码 |
|---|---|---|
| 声明 | `:1169` | `self._pending_memory_turn: Optional[dict] = None` |
| 每轮清 | `:1287` | `self._pending_memory_turn = None` |
| 置位 | `:1296-1299` | 条件 `task_type == "chat" and not self._agent_mode and not _is_demo_mode(...)` → `{"user_text": user_text}` |
| 一次性消费 | `:2394-2396` | `pending_memory = self._pending_memory_turn; self._pending_memory_turn = None` |
| 取消清 | `_on_cancelled` | `= None` |
| 失败清 | `_on_api_error` | `= None` |

**为何不用 `_current_user_text`**：该字段是**共享 memo**，有 4 个不同写入点（`:642` agent 任务配置 / `:1288` 普通发送 / `:1508` 某编辑路径 / `:2024` 另一 agent 路径）。用它会让捕获挂到语义不确定的值上。专用暂存槽另有"一次性消费 + 群聊天然隔离"两个白拿的好处。

**新增方法** `_extract_memory_after_reply(pending, full_text, usage)`，守卫纪律逐条复刻 `_stash_vision_memory`：

```
not pending                          -> return
usage.get("cancelled")               -> return
_is_demo_mode(app_ctx)               -> return
mmgr 缺失 / 无 extract_from_dialogue  -> return
```

提取与归档**分两个 try** 隔离（提取失败不连坐归档失败）：

```python
try:
    mmgr.extract_from_dialogue(str(pending.get("user_text") or ""), full_text)
except Exception:
    logger.debug("记忆提取失败（静默，不阻塞消息链）", exc_info=True)
try:
    archive = getattr(mmgr, "archive_stale_topics", None)
    if callable(archive):
        archive()
except Exception:
    logger.debug("话题自动归档失败（静默，不阻塞消息链）", exc_info=True)
```

**权限边界**：挂载点位于 `_on_stream_finished` 群聊分流 `return` **之后**，故 `R-J④⑤`（群聊记忆提取零调用）**结构性成立**，不依赖运行时判断。

### D-V24-02 话题提取质量门

**问题**（实测）：`_TOPIC_PATTERNS[2]` 的分隔词 `(?:叫|是|关于)?` 可缺省，`[:：]?` 亦可缺省，于是 `(.+?)` 会捕获裸名词提及之后的整句剩余。

**决策**（两处，双保险）：

```python
# 改前
(r"(?:项目|任务|工作)\s*(?:叫|是|关于)?\s*[:：]?\s*(.+?)(?:[。！？\n]|$)", "ongoing")
# 改后
(r"(?:^|[。！？；;，,\s])(?:我的|这个|那个)?(?:项目|任务|工作)\s*(?:叫|是|关于|[:：])\s*[:：]?\s*(.+?)(?:[。！？\n]|$)", "ongoing")
```

- 前导锚点 `(?:^|[。！？；;，,\s])`：只在句首/标点/空白后起匹配，裸名词中缀（"这个**项目**做完了"里的"项目"前是"个"）不命中；
- 分隔符由可选改**必选**（`叫|是|关于|冒号` 四选一）；
- 新增 `_TOPIC_SUBJECT_MAX = 30`，把原来的硬编码上限 100 收到 30（长句必是误捕）。

**实测对照**（4 挡 / 6 留 / 1 长度门，全部符合预期）：

| 输入 | 改前 | 改后 |
|---|---|---|
| 这个项目做完了 | ❌ 捕获「做完了」 | ✅ 不提取 |
| 我的项目已经上线了 / 今天工作好累 / 我把任务交了 | ❌ 各捕一句垃圾 | ✅ 不提取 |
| 项目：做个网站 | ✅ | ✅「做个网站」 |
| 我的项目是做个网站 / 任务叫重构登录页 | ✅ | ✅ |
| 我在研究向量数据库 / 我最近在学 Rust | ✅ | ✅ |
| 项目是<39 字长句> | ❌ 捕获 39 字 | ✅ 长度门挡住 |

### D-V24-03 续接排序：多因子评分

**问题**（F7）：`key = (int(followup_score or 0), -idx)` 是**计数字典序**——被 heart 一次的话题在 72h 窗内**永远**压过其他所有话题，与时间无关；且 `followup_score` 无上限，会长期霸榜。

**决策**：新增纯函数 `_followup_priority(topic, now) -> float`，排序键改 `(priority, -idx)`。

```
priority = 0.40*useful + 0.40*recency + 0.20*evidence

useful   = min(followup_score * 0.20, 1.0)      「说到心坎」加权信号（clamp 防失控）
recency  = 2 ** (-age_hours / 36)               真半衰期（36h 处恰为 0.5）
evidence = manual 1.0 / legacy 0.7 / auto 0.6   来源可信度
```

常量集中在 `memory.py` 常量区（标注"可调"，符合本项目既有惯例）：

```python
_FOLLOWUP_HALF_LIFE_HOURS = 36.0   # 72h 时间窗 = 两个半衰期，窗边缘权重 0.25
_FOLLOWUP_W_USEFUL = 0.40
_FOLLOWUP_W_RECENCY = 0.40
_FOLLOWUP_W_EVIDENCE = 0.20
_FOLLOWUP_USE_PER_HEART = 0.20
_FOLLOWUP_EVIDENCE = {"manual": 1.0, "auto": 0.6, "legacy": 0.7}
```

**硬门全部保留**（与评分正交——硬门决定"能不能提"，评分只决定"先提哪个"）：`followup_muted_until` 静默、`followup_asked_at` 7 天去重、`[min_hours, max_hours]` 时间窗。

**为何不新增字段**：`mention_count` 一类"被提及次数"字段**在 GUI 下永远不会增长** —— 增长点只能挂在 `extract_from_dialogue` 里，而该函数在 GUI 侧正是本轮才接通的，且 `_TOPIC_PATTERNS` 只有 3 条正则、覆盖面有限。引入一个在主要使用场景下恒为初值的字段只会增加复杂度。故只用 `recency` 承担"被提及"的角色，`useful`（heart）独立高权重，保住了 ALTM"被引用比被召回值钱"的洞见而不引入惰性字段。

**实测排序语义**（4 场景全符合直觉）：

| A | B | 结果 |
|---|---|---|
| 60h 前 heart×1(manual) = 0.406 | 3h 前无 heart(auto) = 0.498 | **B 胜** |
| 12h 前 heart×2(manual) = 0.677 | 2h 前无 heart(manual) = 0.585 | **A 胜** |
| manual = 0.539 | auto = 0.459（同时刻同分） | manual 优先 |
| 脏 score / 非法时间戳 / 非法 source / 空 dict | — | 降级不抛错，缺时间戳时 recency=0（沉底） |

### D-V24-04 影像记忆排序确定性（顺带修复既有缺陷）

**问题**（F11，实测）：`list_vision_memories` 用 `items.sort(key=..., reverse=True)`。Python 的 `sort(reverse=True)` 对**相等元素保持插入序**，而 `datetime.now()` 在 Windows 计时器分辨率下会撞时间戳（实测 55 条仅 34 个不同值，`消息53`/`消息54` 同戳），于是"最新一条在前"失效、首条错位。

**外部症状**：`test_v18_batch4.py::test_rolling_eviction_keeps_newest_50` **单跑必过、批跑必挂**（批跑时机器更慢，撞车概率上升）。

**决策**（一行语义修正）：

```python
# 改前：相等时间戳保持插入序 -> 首条可能是次新
items.sort(key=lambda v: str(v.get("time") or ""), reverse=True)
# 改后：升序稳定排序 + 整体 reverse -> 相等时间戳下后插入者在前
items.sort(key=lambda v: str(v.get("time") or ""))
items.reverse()
```

**实测**：改前 `items[0] == "消息53"`；改后 `items[0] == "消息54"`、`items[-1] == "消息5"`，该测试批跑转绿（200 passed/1 failed → 201 passed）。

### D-V24-05 落盘安全网（对齐项目既有约定，非新发明）

**问题**（F9）：`_load()` 遇 `JSONDecodeError` 直接 `pass`，随后用默认结构**覆盖写盘** —— 本模块唯一会静默销毁用户记忆的路径。GUI 接通捕获后写入频率由"几乎不写"变为"每轮都写"，该风险被放大。

**决策**：把 `gui/tavern/store.py` **已经实现并测试过**的 L5/L6 约定推广到 `memory.py`（单槽即可，不做历史回溯）：

| 环节 | 实现 | 关键点 |
|---|---|---|
| 写前快照 | `_rotate_backup()`：`shutil.copy2(filepath, filepath + ".bak.1")` | **复制而非移动**（移动会让"写失败"时原档消失）；失败 best-effort 不阻断写入 |
| L5 快照恢复 | `_load_latest_backup()`：主档不可解析时取 `.bak.1`，并做读时迁移 | 恢复后仍走 `_merge_defaults`，老备份也能被升级 |
| L6 损坏隔离 | `_quarantine_corrupt()`：`os.replace(filepath, filepath + ".corrupt[.n]")` | **改名保留，绝不静默删除**；不加时间戳（保确定性单测）；同名追加序号 |

**快照语义（重要）**：快照是**写前**拍摄的，故**永远落后主档一次保存**。这是有意的取舍——代价是最多丢最后一次改动，收益是任何时刻都有一份可回滚的上次完好状态。与 tavern store §4.4 口径一致。

**实测四条**：① 首写不产生快照（无档可快照）；② 主档坏 → 从快照恢复，数据不丢（只丢最后一次保存）；③ 主档+快照都坏 → 隔离为 `.corrupt` 且**内容可读**，回落默认；④ 二次损坏追加 `.corrupt.1`，不覆盖第一份。

---

## 3. 文件清单

### 3.1 新增

| 文件 | 内容 |
|---|---|
| `docs/prd-v24.md` | 需求池 C/S/P/F 组、Q-V24 待裁决、Non-goals N1–N7、红线对照 |
| `docs/design-v24.md` | 本文 |
| `tests/test_v24_followup_priority.py` | 评分公式 + 硬门保留 + tie-break 方向 + 提取质量门（**26 例**） |
| `tests/test_v24_memory_capture.py` | 捕获守卫矩阵 + 群聊隔离 + 暂存置位 + **端到端全链路**（**21 例**） |
| `tests/test_v24_memory_persistence.py` | 快照轮转 + L5/L6 恢复阶梯 + 隔离不删除（**11 例**） |

### 3.2 修改（**纯增为主**）

| 文件 | 改动 |
|---|---|
| `memory.py` | + 安全网常量 `_MEMORY_BACKUPS` / `_BACKUP_SUFFIX` / `_CORRUPT_SUFFIX`；+ 评分常量 6 个；+ `_TOPIC_SUBJECT_MAX`；`_TOPIC_PATTERNS[2]` 正则收紧；`_load` 改为 L5/L6 阶梯；`_save` 加写前快照；+ 4 个私有方法（`_backup_path` / `_load_latest_backup` / `_quarantine_corrupt` / `_rotate_backup`）；+ 静态方法 `_followup_priority`；`pick_topic_followup` 排序键 1 行；`extract_from_dialogue` 长度门 1 行；`list_vision_memories` 排序 2 行；`import shutil` |
| `gui/chat_service.py` | + 暂存槽声明 1 处 + 清零/置位/消费共 5 处；+ `_extract_memory_after_reply` 方法；调用点 1 处（`_stash_vision_memory` 旁） |
| `CHANGELOG.md` | 顶部新增 v2.4.0 条目 |

### 3.3 明确不动

| 对象 | 理由 |
|---|---|
| `version.json` | `assets.*.sha256/size` 是 `tools/build_release.py` 发布时回填的产物，手工改会破坏更新器 |
| `build_memory_context` | B5（`len(ctx) <= 300` 被测试钉死） |
| `followup_score` / `followup_muted_until` / `followup_asked_at` / `last_mentioned` | B1/B6（字段名与语义冻结） |
| `_DEFAULT_MEMORY` | B7（本轮无 schema 变更，因此**不经** `_merge_defaults`、不涉及 `meta.version`） |
| `session.py` | CLI 既有调用点保持原样；GUI 侧为并列新增而非迁移 |
| `gui/tavern/**` | 本轮是"从它借约定"，不回改它 |

---

## 4. 测试与验收

### 4.1 新增测试（58 例）

| 文件 | 覆盖要点 |
|---|---|
| `test_v24_followup_priority.py`（26） | 评分 clamp / evidence 序 / 衰减单调性 / **半衰期精确值** / 脏数据降级 / 纯函数无副作用；排序 4 场景；三条硬门 + 命中副作用；提取质量门（4 挡 6 留 + 长度门） |
| `test_v24_memory_capture.py`（21） | 正向落盘（含"重开 MemoryManager 重读文件"断言）；零写入矩阵（None/空/取消/demo/无 mgr）；异常不外抛（提取异常、归档异常、脏 user_text）；群聊三隔离；暂存置位与清零；**端到端 4 例**（`send_message` → `_on_stream_finished` → 重读磁盘） |
| `test_v24_memory_persistence.py`（11） | 首写无快照 / 二次写有快照 / **快照落后一次保存**（语义钉死）/ 快照不替换主档 / 主档坏从快照恢复 / 双坏隔离回落 / **隔离内容可读** / 二次损坏追加序号 / 截断恢复 / 正常路径零干扰 |

### 4.2 验收判据

**程序化**（已达成）：端到端测试 `test_full_cycle_writes_topic_to_disk` —— 走完 `send_message` → `_on_stream_finished` 后，**新开 `MemoryManager` 重读文件**能取到 `source=="auto"` 的话题。这直接对应修复前的症状（该链路终点为空）。

**人工**（待用户执行）：启动 GUI 发一句「我最近在学 Rust」→ 检查 `~/.maid_coder/user_memory.json` 首次被写入 → 记忆中心「活跃话题」出现该条且带「自动提取」角标。

### 4.3 全量回归结果

```
1 failed, 2397 passed, 9 skipped in 254.73s
```

唯一失败 `test_v20_updater.py::test_enumerate_finds_own_process` **系既有环境问题**，证据三条：① 与本轮改动文件（`memory.py` / `gui/chat_service.py`）无任何依赖关系，它测的是 `maling_updater.py::enumerate_processes_under`（本轮零改动）；② **单独跑即失败**（0.18s），故与测试顺序/本轮改动无关；③ 该测试自身 docstring 已写明"venv 的 `sys.executable` 与真实 image path 不同（`Scripts/python.exe` 是重定向器）"，属 Windows venv 环境特性。

`py_compile` 双绿（共享知识 25）。

---

## 5. 实施顺序（实际执行）

1. `memory.py` 常量与安全网 → 跑记忆测试确认零回归（同时暴露 D-V24-04 的 flaky 并修复）
2. `memory.py` 正则质量门 → 实测 4 挡 6 留
3. `memory.py` 评分函数 + 排序键 → **新测试当场捕获半衰期语义错误**，修正后 26 例绿
4. `gui/chat_service.py` 暂存槽 + 钩子 → 201 例回归绿
5. 三个测试文件 → 58 例绿
6. 全量回归 → 2397 passed
7. 文档

---

## 6. 红线对照

| 红线 | 实现对照 | 验证 |
|---|---|---|
| **R-A** 无焦虑（全 UI 无数值化） | 新评分为纯计算量：不进 `build_memory_context`、不进 `request_injections`、不落任何字段、无日志文案；`followup_*` 四字段本就零 UI 呈现 | 未新增任何 UI 触点 |
| **R-I** 本地与遗忘 | 全本地 `~/.maid_coder/`；坏档**隔离保留**（`.corrupt`）而非删除；快照提供回滚 | `test_quarantine_preserves_content` |
| **R-K** 诚实边界 | `prd-v24.md` §1.4 主动更正两条不成立的原建议与一处实现错误；§4.3 如实记录既有失败测试不掩盖 | 本文 §1.4 |
| **R-J④⑤** 群聊三隔离 | 挂载点结构性地在群聊分流 `return` 之后 | `test_group_path_never_reaches_capture_hook` + 既有 `TestTripleIsolation` 未改 |
| **共享知识 18** 读时迁移 | 本轮**无 schema 变更**，不触发 | — |
| **共享知识 19** 页面只调方法 | 未改任何页面 | — |
| **共享知识 23** 测试隔离 | 三个新文件全部 `filepath=tmp_path` | 无 `~/.maid_coder/` 读写 |
| **共享知识 25** 双绿 | `py_compile` + pytest | §4.3 |

---

*文档版本：v2.4a（2026-09-18）*
