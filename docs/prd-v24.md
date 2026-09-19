# 码铃（MaLing）v2.4 增量 PRD ——「记忆捕获链路修复 × 续接排序升级 × 落盘安全网」

- 版本：v2.4（增量 PRD，承接 prd-v16 / v17 / v18 / v19 / v20 / v21 的需求池格式与颗粒度）
- 文档状态：草案（§1.4 含**对既有建议的诚实更正**；Q-V24 系为待裁决项）
- 维护人：产品经理（许清楚）· 架构（高见远）
- 关联文档：
  - 格式基准：`docs/prd-v21.md` + `docs/design-v22.md`
  - **本轮直接基线**：`docs/design-v22.md`（v2.2 酒馆，其中把 `memory.py` 列为 Non-goal / 只读）
  - 红线源：`docs/prd-v21.md` §8（R-A / R-D / R-F / R-K / R-L / R-M / R-P / R-Q / R-R）、`docs/prd-v16.md` §2（R-I）
  - 项目速览：`README.md` + `CHANGELOG.md`（基线 **v2.3.1**）
  - 代码现状：**以源码为准**（`memory.py` / `gui/chat_service.py` / `session.py`），不采信任何二手描述
- 修订记录：
  - **v2.4a（2026-09-18）**：立项。起因是评估两个开源项目（LingChat / Autonomous-Long-Term-Memory-System）能否并入码铃；评估过程中实测发现**码铃记忆系统在 GUI 下从未写入过任何数据**，遂将本轮重心从"抄评分公式"改为"先修链路、再升级排序"。新增红线沿用 R-A / R-I / R-K，**不新增红线编号**。

---

## 0. 一句话背景

码铃的记忆系统在 GUI 链路上**从未被触发过**——`user_memory.json` 自 2026-08-29 首启生成默认骨架后三周零写入；本轮把它接通，并顺带把续接排序从"计数字典序"升级为多因子评分，同时补上项目已有的落盘安全约定。

---

## 1. 版本目标与背景

### 1.1 为什么现在做这个

用户要求评估两个开源项目能否并入码铃：

| 项目 | 语言/形态 | 许可 | 结论 |
|---|---|---|---|
| LingChat v0.5.0 | Tauri v2（Rust + Vue3） | **AGPL-3.0** | **不可并入**（见 §4 Non-goals） |
| Autonomous-Long-Term-Memory-System (ALTM) | Python 库 | Apache-2.0 | 可并入，但**建议只吸收设计** |

评估 ALTM 时，为判断"码铃现有记忆系统与它差多少"，对码铃记忆做了实测取证，结果发现的问题**比评分公式严重得多**（见 §1.3）。故本轮重新排序优先级：**链路 > 排序 > 花活**。

### 1.2 设计来源：从 ALTM 吸收什么

ALTM（`cuiyuestar/Autonomous-Long-Term-Memory-System`，Apache-2.0）的架构是 **L0–L4 分层 + 异步折叠流水线**。其中对本项目有借鉴价值的，按其重要性排序：

1. **capture 与 folding 分离**（最重要）：ALTM 的 L0 捕获层是**纯规则、无条件、必然写**；L1–L4 的 LLM 折叠才异步、可失败。**码铃把 capture 挂在了 CLI 这个非主链路上**——这才是真正的缺口。
2. **多因子加权 + 软时间衰减**：`governor.py` 的 `0.30*structural + 0.30*access + 0.25*recency + 0.15*evidence_quality`，其中 `access = access_count*0.05 + useful_access_count*0.20`——**「被引用」比「被召回」值钱 4 倍**。
3. **token 预算随压力自适应**：`dynamic_threshold = 0.70 + max(0, pressure-0.70)*0.35`（记忆库越满，晋升越难）。

### 1.3 现状事实基线（已逐条实测，作为需求落点依据）

| # | 事实 | 取证方式 |
|---|---|---|
| F1 | `~/.maid_coder/user_memory.json` 为 **2026-08-29 首启生成的默认骨架**，`created_at == updated_at`，偏好/话题全空，无 v1.6/v1.8 应补的 `emotions`/`entities`/`vision_memories` 键 | 实读文件 |
| F2 | 同目录 `companion.json`（9-17 22:07）、`sessions/`（9-17）均活跃 → 用户正常使用码铃 | `ls -lat` |
| F3 | `extract_from_dialogue` **只有 CLI 调用**（`session.py:595`） | `grep -rn` 全仓 |
| F4 | `archive_stale_topics` **只有 CLI 调用**（`session.py:600`） | 同上 |
| F5 | 后果链：无话题 → `pick_topic_followup()` 恒 `None`（主动续接从不触发）；无偏好 → `build_memory_context()` 恒返空串 | 代码推演 + F1 实证 |
| F6 | 记忆中心「自动提取」角标（`page_memory_book.py` `_SOURCE_LABELS["auto"]`）在 GUI 下**永不可能出现**——GUI 无任何代码能产出 `source="auto"` | `grep` 溯源 |
| F7 | `pick_topic_followup` 排序键为 `(int(followup_score or 0), -idx)`——**计数字典序**：被 heart 过的话题在 72h 窗内永远压过其他所有话题、与时间无关；`followup_score` 无上限 | 实读 `memory.py:1152` |
| F8 | `_TOPIC_PATTERNS[2]` 的 `(?:叫|是|关于)?` **可缺省**，裸名词提及会捕获整句剩余——「这个项目做完了」→ 话题「做完了」 | 实测复现 |
| F9 | `_load()` 遇 `JSONDecodeError` **直接 pass 并用默认结构覆盖写盘**，无备份、无日志——本模块唯一会静默销毁用户记忆的路径 | 实读 `memory.py:167-181` |
| F10 | 项目**已有**更好的约定：`gui/tavern/store.py` 实现 L0–L6 加载阶梯（L5 快照恢复 / L6 损坏档改名 `.corrupt` 保留，**绝不静默删除**），但 `memory.py` 未采用 | 实读 `store.py:153-243` |
| F11 | `list_vision_memories` 用 `sort(reverse=True)` 排时间倒序；Python 稳定排序对**相等元素保持插入序**，而 `datetime.now()` 在 Windows 计时器分辨率下会撞时间戳（实测 55 条仅 34 个不同值）→ 「最新一条在前」失效 | 实测复现 + 批量跑红 |
| F12 | `update_topic_status` 是全仓**死代码**（只定义，零调用） | `grep -rn` |

### 1.4 ⚠ 对既有建议的诚实更正（**不照抄错误前提**）

本轮的输入来自一次口头评估，其中**两条建议经实测后被推翻**，记录在此以免后续误用：

1. **「防虚报机制」在码铃无处可施** —— ALTM 的 Hermes 插件用正则扫 `memory://<id>` 并校验 id 是否在当轮下发列表内，是因为它**让 LLM 自己申报引用了哪条记忆**。码铃不使用 LLM 抽取、不收集 LLM 的引用声明（抽取是纯正则），故该机制**没有落点**。原建议将其列为"最值钱的三件事之一"是**不准确的**。
2. **「RRF 融合 + 2 跳 PPR 涌现」属于过度设计** —— 码铃当前**没有检索层**，且注入预算是 300 字符硬顶（约 2–3 条话题）。在候选池只有个位数量级、注入位只有 3 个的前提下，四路召回融合与图随机游走**无可分配收益**；且引入向量召回需额外 embedding API（DeepSeek 官方无 embeddings 接口），成本与失败面都上升。
3. **排序公式里「半衰期」曾被误用为「时间常数」** —— 原稿写 `recency = exp(-age_hours / 36)` 并称其为半衰期，但 `exp(-36/36) = 0.368 ≠ 0.5`。方案陈述的「窗口边缘权重 0.25、12h 处 0.79」**只有真半衰期语义才成立**。已改为 `recency = 2 ** (-age_hours / 36)`，实测 `recency(36)=0.500`、`recency(72)=0.250`。

---

## 2. 需求池

### 2.1 C 组 —— 捕获链路（3 条，本轮 P0）

| ID | 需求 | 落点 |
|---|---|---|
| C1 | GUI 单聊普通轮回复完成后，从本轮对话捕获偏好 / 话题 / 情绪 | `gui/chat_service.py::_extract_memory_after_reply` |
| C2 | GUI 同处顺带执行过期话题自动归档（原本只有 CLI 跑） | 同上，链调 `archive_stale_topics()` |
| C3 | 话题提取质量门：挡住裸名词误捕（F8） | `memory.py::_TOPIC_PATTERNS[2]` + `_TOPIC_SUBJECT_MAX` |

### 2.2 S 组 —— 续接排序（1 条，本轮 P0）

| ID | 需求 | 落点 |
|---|---|---|
| S1 | `pick_topic_followup` 排序由计数字典序改为多因子评分（有用信号 + 软时间衰减 + 来源可信度） | `memory.py::_followup_priority` |

**验收语义**（实测）：3h 前刚提到（0.498）应胜过 60h 前 heart 过一次（0.406）；12h 前 heart 过两次（0.677）应胜过 2h 前无 heart（0.585）。

### 2.3 P 组 —— 落盘安全（2 条，本轮 P0）

| ID | 需求 | 落点 |
|---|---|---|
| P1 | 写前快照轮转（复制而非移动，写失败原档不被破坏） | `memory.py::_save` + `_rotate_backup` |
| P2 | 主档不可解析 → 试快照 → 隔离坏档 `.corrupt[.n]` → 才回落默认（**绝不静默删除**） | `memory.py::_load` + `_load_latest_backup` + `_quarantine_corrupt` |

### 2.4 F 组 —— 既有缺陷顺带修复（1 条）

| ID | 需求 | 落点 |
|---|---|---|
| F1 | `list_vision_memories` 时间倒序在时间戳撞车时首条错位（F11） | `memory.py::list_vision_memories` |

### 2.5 需求计数

**7 条**（C3 + S1 + P2 + F1）。

---

## 3. 待确认问题 Q 列表（Q-V24 系）

| ID | 问题 | 建议 | 状态 |
|---|---|---|---|
| **Q-V24-1** | 评分权重与半衰期取值为**初次拍定**（0.40/0.40/0.20，半衰期 36h），缺乏真实数据校准。是否需要等积累出真实话题分布后再回归调参？ | 建议先上线，v2.5 用真实数据复核。常量已集中且注明「可调」 | 待裁决 |
| **Q-V24-2** | `_FOLLOWUP_EVIDENCE` 给 `legacy`（迁移来的老话题）0.7、`auto` 0.6——老数据是否应比自动提取更可信？ | 建议维持（迁移数据多为当年手建） | 待裁决 |
| **Q-V24-3** | ARCHIVE 在 GUI 每轮跑一次，是否过频？ | 建议维持：纯内存遍历 + 仅在真有归档时落盘 | 待裁决 |
| **Q-V24-4** | 情绪历史 200 上限（`_EMOTIONS_HISTORY_MAX`）在 GUI 接通后会**更频繁触发裁剪**（每次超限删最旧）。是否可接受？ | 建议维持：这是 v1.6(Q-B8) 既有裁决，非本轮引入 | 待裁决 |

---

## 4. Non-goals（明确不做）

| # | 不做的事 | 理由 |
|---|---|---|
| N1 | **不并入 LingChat 任何代码** | AGPL-3.0 违反 R-H 白名单（`docs/THIRD_PARTY.md`：仅收 MIT/Apache-2.0/BSD/CC0，**禁 GPL/AGPL**）。且其"纯外部运行时依赖"豁免（同 SillyTavern）**不适用**：v0.5.0 主动移除了对外通信层（无 CLI / 无 WS / 无 HTTP 控制面），要驱动它必须改其 Rust 源码 → 触发 `docs/THIRD_PARTY.md` 已写明的豁免失效边界。另：技术栈（Rust+Vue）与码铃（Python+PySide6）零重叠 |
| N2 | **不 vendor ALTM 本体** | PyPI 无发布（404）需 vendor 源码并要求自维护单人作者的未广泛分发库（供应链风险）；需额外 embedding key（DeepSeek 无 embeddings 接口）；`embeddings.py:240` 有 Windows-only `os.fchmod` 缺陷；其 L2 原子事实与本项目 preferences/topics 高度同构，会产生双真相源冲突 |
| N3 | 不做 RRF 融合 / 图 PPR 涌现（见 §1.4-2） | 无检索层，候选池与注入位都不足以分摊复杂度 |
| N4 | 不做防虚报引用校验（见 §1.4-1） | 码铃无 LLM 引用申报环节，无落点 |
| N5 | 不做晋升/降级滞后防抖（ALTM 的 `promotion_min_cycles=3`） | 该机制为**大记忆库**抑制排序抖动；码铃候选池为个位数量级，抖动无实际影响，引入状态不划算 |
| N6 | 不给 `followup_score` 加上限或衰减 | 既有 `tests/test_memory.py` 精确断言 `== 1`、六个 `companion_scenarios` 剧本直接读写该字段；本轮**只读不改**其语义（见 design §1.2） |
| N7 | 不新开 UI 数值展示（评分 / 优先级 / 次数） | **R-A 无焦虑红线**：全 UI 不得展示任何数值化心情/好感/等级/进度 |

---

## 5. 约束与风险

### 5.1 兼容性（最高优先级约束）

既有 **2353 个测试用例零修改且必须全绿**。经逐条排查，以下测试对本次改造构成硬约束：

| 测试 | 约束 | 应对 |
|---|---|---|
| `test_memory.py::TestV16FollowupFeedback::test_heart_chat_mute` | 精确断言 `followup_score == 1` | 不动该字段语义 |
| `test_memory.py::TestV16TopicFollowup::test_score_weighting` | 靠 **tie-break**（idx 小者优先）通过，非靠评分 | 排序键保留 `-idx` 且方向不变 |
| `test_memory.py::TestV16TopicFollowup::test_out_of_window_ignored` | 窗外不入选 | 保留硬时间窗 |
| `test_v18_batch1.py::test_channel1_pinned_in_build_memory_context` | `len(ctx) <= 300` | 本轮**不动** `build_memory_context` |
| `test_v17_batch4_f10.py::TestTripleIsolation` | 群聊**记忆提取零调用**（R-J④⑤） | 挂载点置于群聊分流 `return` 之后 |
| `companion_scenarios` S07/S11/S12/S13/S15/S17 | 直接读写 `followup_score`/`followup_muted_until`/`last_mentioned` | 字段名冻结 |

### 5.2 写入频率

GUI 接通捕获后，记忆文件由"几乎不写"变为"**每轮对话写一次**"（`extract_from_dialogue` 仅在 `modified` 时落盘）。JSON 体量小（KB 级）+ 原子写，成本可忽略；但**损坏风险随之放大** —— 这正是 P 组（§2.3）必须同批交付的原因。

### 5.3 最大风险

**正则收紧（C3）可能降低 CLI 侧召回**。取"精度优先于召回"：两条主模式（`我在学X` / `最近在X`）不改，仅第三条加前导锚点与必选分隔符。已实测 4 个垃圾场景全挡住、6 个正常场景全保留。

### 5.4 可回退性

`memory.py` / `gui/chat_service.py` 均为纯增量改动，无 schema 变更（**新评分不落任何字段**），回退只需还原这两个文件；记忆数据文件无迁移、无版本号变动。

---

## 6. 红线（v2.4 = 沿用 R-A / R-I / R-K，不新增编号）

| 红线 | 口径 | 本轮落点 |
|---|---|---|
| **R-A** 无焦虑 | 全 UI 不得展示任何数值化心情/好感/等级/token/进度 | 新评分为**纯内部计算量**：不落字段、不入 UI、不入注入串、不进日志文案 |
| **R-I** 本地与遗忘 | 记忆全本地 `~/.maid_coder/`；删除立即落盘；下一轮注入前重读 | P 组强化：坏档隔离保留而非删除；快照保证可回滚 |
| **R-K** 诚实边界 | 不编造、不夸大 | §1.4 主动更正原建议中的两处不准确表述；§7 记录实测发现的既有失败测试 |
| **R-J④⑤**（沿用） | 群聊三隔离：不写对齐历史 / 不计亲密度 / **不做记忆提取** | 挂载点位于 `_on_stream_finished` 群聊分流 `return` 之后；新增端到端测试钉住 |

---

## 7. 裁决记录

| 项 | 结论 | 依据 |
|---|---|---|
| 是评估的两个开源项目"能不能加入" | LingChat **不能**（许可+架构双重否决）；ALTM **能但只吸收设计** | §4 N1/N2 |
| 本轮范围 | 经用户拍板：**捕获链路与评分公式两个都做** | 用户于规划阶段选定 |
| 是否新立设计文档解冻 `ChatService` | 是。`docs/design-v22.md:42` 明文「不改 `ChatService`/`session`/`memory`/`companion`/`persona`」，本轮以本文 + `design-v24.md` 正式解冻并记录理由 | 项目文档纪律 |
| 落盘安全网是否属于本轮 | 是。它是 C 组的前置条件（写入频率放大损坏风险），且**只是把项目已有约定从 `store.py` 推广到 `memory.py`**，非新发明 | F10 |

---

*文档版本：v2.4a（2026-09-18）*
