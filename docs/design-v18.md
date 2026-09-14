# 码铃（MaLing）v1.8 增量架构设计 ——「认知深化：她真的认识我」

- 版本：v1.8（增量设计，格式对齐 design-v13 / design-v16 / design-v17）
- 文档状态：定稿（Q-D1~Q-D10 已由用户裁决，全按 PM 建议值，本文标「Q-Dx 裁决」）
- 维护人：高见远（架构）
- 关联文档：`docs/prd-v18.md`（需求源）+ `docs/design-v16.md`（记忆中心 / intent / request_injections 基建）+ `docs/design-v17.md`（群聊 / 提醒 / 角色卡 v1 先例）+ 源码为准
- **基线：v1.7.3**（Pi 引擎内置 / 群聊自由发言 / 记忆中心五分区 / 意图五态 / 反馈三键 / 每周回顾 / 贴身提醒全部在跑）
- 设计原则重申：本文所有落点均基于 v1.7.3 **重构后源码逐行核实**（不是旧版文件位置）；群聊调度与 Pi 引擎零触碰（R-J）。

---

## 1. 范围与现状校正（先读我）

### 1.1 本期范围

P0 三件套：F1 记忆图谱 / F2 情绪弧线 / F3 共同经历时间线。
P1 四项：F4 场景化陪伴 / F5 角色卡分享标准 / F6 自定义回应规则 / F7 多模态记忆。
Non-goals（PRD §1.3 全部承接）：语音闭环 / 桌宠深化 / AI 生图 / 回忆相册 / 知识图谱推理 / 云同步 / 群聊与 Pi 引擎零改动。

### 1.2 现状校正（⚠ 标红：PRD 表述与源码不符处，按本文执行）

| # | PRD 表述 | 源码事实（已核） | 本文裁决 |
|---|---|---|---|
| ⚠-1 | §5.1「情绪陪伴模式（v1.7 F6 安慰模式）均在跑」 | **该模式代码从未实现**——v1.7 设计 D-V17-09 已范围澄清：confide 态识别 + 当轮语气提示已覆盖，独立安慰模式被排除（grep 全树零命中） | F4 三层叠加中的「情绪陪伴模式激活」改锚定为：**当轮 intent=confide 命中 且 `_note_owner_emotion`（chat_service.py:1288，v1.2 A1 既有情绪采集）检出负面信号** → 该轮场景注入挂起（逐轮判定，无持久模式态）。D-V18-07 |
| ⚠-2 | §4.1「本轮命中实体 → build_memory_context 扩展注入」 | `build_memory_context`（memory.py:491）仅在 `_build_system_prompt` 会话级调用，**不是每轮**；request_injections（chat_service.py:1123）才是每轮请求级通道 | **双通道拆分**：pinned 实体走 `build_memory_context`（system 级常驻）；提及命中走 request_injections（每轮）。D-V18-02 |
| ⚠-3 | §4.2「intent 五态 emotion 命中」 | 五态实际命名：**confide / chat / analyze / advise / act**（gui/intent.py），无 emotion 态 | 情绪概览注入触发 = **confide 态命中 或 显式疑问句式**（"最近怎么样 / 最近状态 / 是不是很丧" 词表）。D-V18-04 |
| ⚠-4 | §4.1「实体段与偏好/话题共享 300 字符预算」 | 双通道拆分后（⚠-2），提及命中行已不在 build_memory_context 内 | 预算口径改：system 级 300 字符共享预算只管 pinned 段；request 级提及行独立限额（≤2 实体 × ≤120 字符）。D-V18-02 |
| ⚠-5 | §5.1「场景注入：会话级一次，非每轮」+「挂 request_injections」 | request_injections 为请求级副本、**不入 session.history**，下一轮即消失——"只注一次"靠它留不住 | 场景切换 = **双动作**：①切换当轮 request_injections 附完整场景语气指令（即时生效）②往 session 写一条幂等边界消息（复用 v1.5.1 `notify_role_switch`（session.py:206）边界模式，语气底色随历史留存）。D-V18-07 |

### 1.3 已核实的关键对接点（v1.7.3）

| 对接点 | 位置 | 用途 |
|---|---|---|
| `_DEFAULT_MEMORY` / `_merge_defaults` | memory.py:17 / :117 | F1/F6/F7 顶层新键读时迁移（D-V16-01 先例，meta.version 不升） |
| `get_emotions_history` / `_EMOTIONS_HISTORY_MAX=200` | memory.py:481 / :41 | F2 数据源（只读，零 schema 变更） |
| `build_memory_context(max_chars=300)` | memory.py:491 | F1 pinned 段扩展位 |
| `session.refresh_system_context` | session.py:197 | 删除即遗忘当轮生效（复用，零新增） |
| request_injections 组装 | chat_service.py:1123-1145 | F1 提及 / F2 概览 / F4 场景 / F6 规则 / F7 召回 共用注入位 |
| `NIGHT_CARE_INJECTION` | chat_service.py:69 / :1137 | F4 睡前场景合并判定对象 |
| 提醒拦截分支 / intent 路由 | chat_service.py:1103-1115 / :1122 | 注入序位锚点（新增注入全部插在 intent 提示之后） |
| `_note_owner_emotion` / `_route_intent` | chat_service.py:1288 / :1227 | F4 情绪挂起判定 / 五态（confide）判定 |
| `_launch_worker` / `_on_stream_finished` | chat_service.py:1841 / :2012 | F7 存档钩子（成功路径非 demo 分支） |
| `_image_attachments_to_data_uris` / `vision` 标记 | chat_service.py:1785 / :1927 | F7 判断就绪（图片当轮直传不落盘，F7 延续） |
| `ProactivePolicy` / `PolicyState.external_cooldown_until` | gui/proactive_scheduler.py（:150/:164 先例） | F4 `external_daily_cap_override` 同款落法 |
| page_memory_book 5 Tab | gui/pages/page_memory_book.py:211-239 | F1/F3/F6 新分区 + F2 弧线区块挂载点 |
| 角色卡 `SCHEMA_VERSION=1` / `EXPORT_FIELDS` 白名单 | gui/role_card.py | F5 升 v2 增量面（无 cover / 无预览，全新增） |
| GuiConfig 键模式 | gui/config.py:55 / :137 | `entity_auto_propose` / `scene_*` / `vision_memory_enhance` 照此注册 |
| `highlights.query_range` | highlights.py:160 | F3 三源之一 |

---

## 2. 架构决策（D-V18-01 ~ D-V18-10）

### D-V18-01 F1 实体存储：`user_memory.json` 顶层 `entities` 键（Q-D1 裁决：提议-确认默认关）

- `_DEFAULT_MEMORY` 增 `entities: []`，`_merge_defaults`（memory.py:117）读时迁移；meta.version **不升**；旧文件零破坏（D-V16-01 同款，R-D）。
- 结构见 §4.1。上限：实体 100 / 每实体事件 20，**超出写入被拒 + 友好提示，绝不自动淘汰**（人物记忆不悄悄消失）。
- MemoryManager 新 API：`add_entity / update_entity / delete_entity / add_entity_event / list_entities / find_entities_by_name(text)`（精确子串命中 name，供注入与提议链用）。所有写操作立即 `_save()`；删除后由 UI 链调 `session.refresh_system_context()`（session.py:197，既有）当轮生效。
- relation 开放枚举（同事/朋友/家人/恋人/同学/其他 + 自定义文本）；source ∈ manual / assistant_proposed。
- 提议-确认链（Q-D1：开关 `entity_auto_propose` **默认 False**，GuiConfig :55/:137 模式注册）：对话命中关系句式（"我同事/我朋友/我妈/我们领导…" + 人名）→ 回复尾部轻问 + [记下来][不用了] 两键（复用反馈三键组件样式，D-V16-05 先例）→ 确认才 `add_entity(source="assistant_proposed")`。**无确认路径绝不写入**（自动化断言）；纯手动录入为完整降级路径。

### D-V18-02 F1 实体注入：双通道拆分（⚠-2/⚠-4 机制校正）

| 通道 | 内容 | 时机 | 预算 |
|---|---|---|---|
| ① system 级（build_memory_context，memory.py:491 扩展） | **pinned 实体**始终注入（≤1 个，格式"【关于小李】同事；备注：…；最近：上周离职了（9-03）"） | 会话级（既有调用节奏不变） | 与偏好/话题**共享 300 字符**，超限按 pinned > 命中缓存 > 事件新近裁剪 |
| ② request 级（request_injections，chat_service.py:1123 后追加） | 本轮用户消息 `find_entities_by_name` **命中实体**（≤2 个 × ≤120 字符/实体行） | 每轮请求副本，不入历史 | 独立限额，与 ① 无关 |

- 未提及且无 pinned → 零实体注入（零 prompt 污染）。
- 注入序位（新增注入统一约定，全在 intent 提示之后）：**实体提及 → 回应约定(F6) → 情绪概览(F2) → 场景语气(F4)**；Agent / 任务 / demo 路径全部跳过（与 NIGHT_CARE :1134 边界一致）。
- `build_memory_context` 签名不变（D-V16-03 微调先例）。

### D-V18-03 F2 情绪弧线：8 周日格档位色带（Q-D3 裁决），R-A 本期主战场

- 数据：UI 侧直接聚合 `get_emotions_history()`（memory.py:481，只读零改动）；**memory 层仅新增 `emotion_overview(days) -> str`** 纯规则模板（近 7 天 / 近 30 天各一句档位描述，如"最近一周多数时候平稳，有两天显得疲惫"——零数字、零 LLM、≤80 字符）。
- 组件：新增 `gui/widgets/emotion_arc.py`（QFrame 网格，纯 Qt 零依赖）——最近 8 周 × 7 日格；当日多条取众数；**无记录 = 浅灰点不臆造**；hover 仅档位词（"那天有点累"）；今日格轻呼吸动画（v1.6 handsfree 先例）+ 点击跳该日条目列表。**全组件无 int→str 上屏路径**（验收断言）。
- 色值：平稳=主题淡色 / 元气=暖黄 / 有点累=淡橙 / 低落=淡蓝，走 theme_color 语义扩展，深浅色各配。
- 注入触发（⚠-3）：confide 态命中 **或** 显式疑问句式（"最近怎么样/状态怎么样/是不是很丧"词表，挂 intent 词表 JSON 同款合并加载）→ 该轮 request_injections 附 `emotion_overview(7)+emotion_overview(30)`；未问零注入。页面固定说明："这只是帮你看见自己，不是给你打分。"

### D-V18-04 F3 时间线：`timeline.py` 纯函数三源聚合（Q-D10 裁决：默认 6 个月）

- 新 `timeline.py`（根级纯 stdlib）：`build_timeline(memory_mgr, highlights_mgr, anniversary_src, weeks_mgr, months=6) -> List[MonthGroup]`——聚合 ①highlights（query_range 复用，highlights.py:160，引用原文 ≤500 字既有保证）②topics.archived（completed_at + subject）③anniversaries（周年语义月节点）④weekly 存在性（点击跳往期回顾 Tab）。纯函数可独立单测，跨年分组正确性单测覆盖。
- **只读视图，不提供编辑**：删高光/删话题 → 节点自然消失（单一真值源）。零 LLM 零成本。
- UI：page_memory_book 新 Tab「共同经历 🌟」，QScrollArea 竖排按月分组；默认 6 个月 + 底部「展开更早」按 6 个月分段追加（不做无限滚动）。空态："你们的故事刚开始写~"。

### D-V18-05 F6 回应规则：`response_rules` 顶层新键 + 命中当轮注入（Q-D9 裁决：20 条上限）

- `_DEFAULT_MEMORY` 增 `response_rules: []`（读时迁移同款）；规则结构见 §4.2；上限 20 条，超出写入被拒提示。
- MemoryManager 新 API：`add_rule / update_rule / delete_rule / match_rules(text)`——match 为**精确子串包含**（不做模糊语义，防误命中），返回 1–3 条 enabled 规则。
- 注入：命中 → request_injections 追加"【回应约定】主人说过：当他说「上线了」时，请回应…"；未命中零注入零成本。Agent 模式跳过。序位在实体提及之后（D-V18-02）。
- 与偏好/抑制表关系（PRD §5.3 口径落地）：**规则 > 偏好**（约定 > 画像）；规则与 mute **正交**（mute 不清规则、规则不受 mute 抑制）——三方并存断言进验收。
- 呈现：命中时 `intent_notice` 小字"📌 已按你的约定回应"；新 Tab「回应约定 📌」增删改查 + 启用开关 + 上次命中相对时间（**无命中计数**，R-A）。双入口：聊天中说"以后我说 XX 你要 YY"（句式命中 → 复述确认 + [记下约定][算了] 两键，与 F1 提议-确认同组件）或记忆中心手动管理。

### D-V18-06 F5 角色卡标准：schema v2 + 封面 base64 ≤500KB（Q-D7 裁决）+ 预览弹窗（收编 v1.7 Q-C10 遗留）

- `role_card.py`：`SCHEMA_VERSION` 1→2；`EXPORT_FIELDS` 白名单增 `cover_image`（其余字段不动）。v1 卡 → v2 导入器**全兼容**；v2 卡 → 未知字段忽略不崩（前向兼容铁则）。**记忆 / 亲密度 / 对话历史 / API 配置 / 实体 / 规则永不入卡**（白名单机制天然保证，R-I）。
- 封面：导入时选本地图（PNG/JPG/WebP）→ QImageReader/QImage 等比压至 512px 内 + 强制 ≤500KB → **base64 内嵌卡文件**（单文件自包含分享心智）；超限拒绝并提示；无封面 → 角色列表回退既有头像逻辑零残缺。
- 预览弹窗：新增 `gui/widgets/card_import_preview.py`——字段逐项呈现（名称 / 人设摘要前 80 字 / 开场白条数 / 示例对话条数 / 性格三值以"活泼偏上"档位词呈现**不显数值** R-A / 封面缩略）；异常与超限字段逐项红字 +「仍要导入」显式确认；重名冲突 →「覆盖导入（有确认框）/ 另存新角色」双路径（dedupe_import_name 既有逻辑衔接）。
- 规范文档：`docs/character-card-spec.md`（schema_version / 必填可选字段 / 兼容性声明 / 排除项）——R-K 新核对项：文档 ↔ 实现逐字段一致。

### D-V18-07 F4 场景化陪伴：scene.py + 三层叠加 + cap 降档（Q-D4/Q-D5/Q-D6 裁决）

- 新 `scene.py`（根级纯 stdlib）：场景枚举（💼工作 / ☕休息 / 🌙睡前 / ✨自定义 ≤3）、时段判定 `current_scene(now, manual_override, cfg)`（工作日 09:00–12:00 / 14:00–18:00 → 工作；22:30–次日 6:30 → 睡前；其余 → 休息；周末不进工作）、语气指令文案表、`~/.maid_coder/scenes.json` 自定义存取。GuiConfig 增 `scene_auto: True` / `manual_scene_date: str`（手动选择当日有效，次日回落自动感知）。
- **三层叠加（Q-D5）**：① 情绪激活（⚠-1 校正锚定：当轮 confide 命中 且 `_note_owner_emotion` 负面信号）> ② 场景 > ③ 意图五态。情绪激活当轮 → 场景注入挂起（逐轮判定，无持久模式）；场景只改基调不改路由（工作场景下"提醒我"照样走提醒分支 chat_service.py:1103）。
- **注入实现（⚠-5 校正：双动作）**：切换当轮 request_injections 附完整场景语气指令（即时生效）+ 往 session 写幂等边界消息（复用 v1.5.1 `notify_role_switch` 边界模式，语气底色随历史留存；服务层记 `last_applied_scene` 防重复写）。**睡前场景与 NIGHT_CARE 合并判定防双注入**：当前场景=睡前 → 跳过 NIGHT_CARE append（:1134-1137 处增量判定，22:30 交叉点断言）。Agent / demo 路径跳过场景注入（与 NIGHT_CARE 同边界）。
- **主动降档（Q-D6：cap 3→1）**：ProactivePolicy 增输入 `external_daily_cap_override: Optional[int]`（PolicyState 增量字段，`external_cooldown_until` :150/:164 **同款落法**，四重闸结构零改动）；调度器每轮按 `current_scene()` 计算——工作场景 → 1，其余 → None（走既有 cap）。可配置键支持调 0。
- 呈现：首页问候区旁场景 chip（"💼 工作模式 · 点按切换"）+ 设置页「场景」区（自动感知开关 / 映射说明 / 自定义管理）；工作模式主动降档在 Agent 设置区文案同步。

### D-V18-08 F7 多模态记忆：`vision_memories` 顶层新键 + 默认零成本档（Q-D8 裁决：增强档默认关）

- `_DEFAULT_MEMORY` 增 `vision_memories: []`，**上限 50 条滚动淘汰**；API：`add_vision_memory / query_vision_memories(keyword) / delete_vision_memory`。
- **默认档（零 LLM 零图像）**：带图消息发送成功后自动存 `{time, user_text(≤50字), assistant_digest(回应首段摘要 ≤50字截断), image_note("用户分享了一张图片"中性描述)}`——**绝不落盘原图 / data URI / 缩略图**（R-I 硬线，文件内容断言验收）。存的是"对话事实"不是"识别结果"。
- 存档钩子：`_on_stream_finished`（chat_service.py:2012）成功路径非 demo 分支增量。**实现注意**：`_on_stream_finished` 无 payload 入参 → `send_message`（:1085）时把 attachments 暂存到服务层（`_current_user_text` :1117 同款模式），流结束时读用；`vision` 标记（:1927）判断就绪。
- 增强档（开关 `vision_memory_enhance` **默认 False**）：视觉模型可用时对图片追加一次轻量识别（max_tokens=120 一句话描述）→ 结果替代 image_note；**失败静默回落默认档，绝不编造**。成本 ≈ 每图 1k token 内。
- 召回：用户消息命中"上次/之前 + 图/截图/照片"句式（规则）→ 检索（关键词重叠 + 时间倒序 top2）→ request_injections 注入"【之前的分享】9-03 主人发过一张图（配文：xxx），当时码铃回应：…" + `intent_notice` 小字。
- **诚实边界（R-K 核心验收）**：①发送当时不支持视觉 → 不存影像记忆，日后问起诚实回应"那次发送时码铃没能看到图"；②增强档失败保留中性描述不编造；③记忆中心可查看可删除（删除即遗忘链复用）。
- UI：**最小方案**——影像记忆为「往期回顾」Tab 内的条目类型（文字卡，无缩略图，无专属图片化 UI——Non-goals 排除相册）。带图成功发送 → `intent_notice`"🖼 这次的分享码铃记在心里了"（一次性轻提示，可关）。

### D-V18-09 记忆中心 Tab 归属（Q-D2 裁决：平铺 + 分组着色，不重构）

- 最终 **8 Tab**：主人偏好 / 活跃话题 / 情绪记录 / **人物关系（F1）** / **回应约定（F6）** / **共同经历（F3）** / 往期回顾（含 F7 影像记忆条目）/ 她的日记。
- 轻量视觉分层：顶部 Tab **分组着色**（记忆组：偏好/话题/情绪/人物/回应；经历组：共同经历/往期回顾；日记组：她的日记）——只动 page_memory_book 内部样式，数据层与既有五 Tab 数据链零改动（R-D）。结构重构列 v1.9 不做。

### D-V18-10 配置键与数据迁移总表

| 键/数据 | 位置 | 默认 | 模式 |
|---|---|---|---|
| `entities` | user_memory.json 顶层 | [] | `_merge_defaults` 读时迁移 |
| `response_rules` | user_memory.json 顶层 | [] | 同上 |
| `vision_memories` | user_memory.json 顶层 | [] | 同上 + 50 条滚动淘汰 |
| `scenes` | ~/.maid_coder/scenes.json | 内置四场景 | 独立文件（用户数据，非记忆） |
| `entity_auto_propose` | GuiConfig | False | :55/:137 注册模式 |
| `scene_auto` / `manual_scene_date` | GuiConfig | True / "" | 同上 |
| `vision_memory_enhance` | GuiConfig | False | 同上 |
| `emotion_overview_enabled` | GuiConfig | True | F2 概览注入总开关 |

meta.version 全部不升；旧版文件加载零破坏（单测：无新键旧文件 → 加载后行为与 v1.7.3 一致）。

---

## 3. 文件清单

### 新增

| 文件 | 内容 | 模块归属 |
|---|---|---|
| `timeline.py` | F3 三源聚合纯函数 | 根级（stdlib only） |
| `scene.py` | F4 场景枚举 / 时段判定 / 语气文案表 / scenes.json 存取 | 根级（stdlib only） |
| `gui/widgets/emotion_arc.py` | F2 日格色带组件（纯 Qt） | gui.widgets |
| `gui/widgets/card_import_preview.py` | F5 导入预览弹窗 | gui.widgets |
| `tests/test_v18_p0.py` / `tests/test_v18_p1.py` | 分批测试 | tests |
| `docs/character-card-spec.md` | F5 格式规范 | docs |

### 修改

| 文件 | 改动 | 红线注意 |
|---|---|---|
| `memory.py` | `_DEFAULT_MEMORY` 三新键 + `_merge_defaults` + 实体/规则/影像 API + `emotion_overview` + `build_memory_context` pinned 段 | 只增量；既有函数签名除 build_memory_context 内部实现外零变更 |
| `gui/chat_service.py` | 注入序位框架（实体/约定/概览/场景四个 append 块，插在 :1131 之后、NIGHT_CARE 判定合并改造）+ F7 存档钩子（:2012）+ attachments 暂存 + F1/F6 提议-确认两键挂接 | `_launch_worker` 组装顺序不动（R-D）；群聊路径零触碰 |
| `gui/pages/page_memory_book.py` | 3 新 Tab + 弧线区块 + Tab 分组着色 + 影像记忆条目 | 既有五 Tab 数据链零改动 |
| `gui/proactive_scheduler.py` | PolicyState 增 `external_daily_cap_override` + 调度器按场景计算 | 四重闸结构不动 |
| `gui/role_card.py` | SCHEMA_VERSION 2 + cover_image + 压缩 | EXPORT_FIELDS 白名单机制不动 |
| `gui/pages/page_role.py` | 导入按钮 → 预览弹窗接线 | **v1.5.1 对齐链（sync_role_override_to_session :296 / notify_role_switch 接线 :1038）零语义变更** |
| `gui/pages/page_home.py` | 场景 chip | — |
| `gui/pages/page_settings.py` | 场景区 + 开关键 | — |
| `gui/config.py` | 4 新配置键 | :55/:137 模式 |
| `gui/session_manager.py` | 无（边界消息走 session 既有 add 通道） | 零改动确认项 |
| `CHANGELOG.md` / `README.md` | v1.8 条目 + 边界说明 | R-K |

---

## 4. 数据结构

### 4.1 `entities`（user_memory.json 顶层，≤100 条）

```json
{
  "id": "ent_9f3a",
  "name": "小李",
  "relation": "同事",
  "notes": "同组后端，Rust 同好",
  "events": [ {"date": "2026-09-03", "text": "上周离职了，主人心情受影响"} ],
  "pinned": false,
  "created_at": "2026-09-10T21:00:00",
  "updated_at": "2026-09-10T21:00:00",
  "source": "manual"
}
```

约束：events 按时间倒序 ≤20；relation 开放枚举；source ∈ manual / assistant_proposed；id 生成用 `uuid4().hex[:8]`（项目既有风格）。

### 4.2 `response_rules`（≤20 条）

```json
{
  "id": "rule_1c2d",
  "trigger": "上线了",
  "response": "回复'辛苦了'，别给建议",
  "enabled": true,
  "created_at": "2026-09-10T21:00:00",
  "last_hit_at": "2026-09-10T21:30:00",
  "source": "manual"
}
```

约束：trigger ≤20 字、response ≤100 字；last_hit_at 为相对时间呈现原料（**不计次数**，R-A）。

### 4.3 `vision_memories`（≤50 条滚动淘汰）

```json
{
  "id": "vis_7e21",
  "time": "2026-09-03T15:20:00",
  "user_text": "这个报错怎么搞",
  "assistant_digest": "先看栈顶那行，像是依赖版本冲突…",
  "image_note": "用户分享了一张图片",
  "source_mode": "default"
}
```

**硬约束：任何字段不得含图像二进制 / data URI / base64（R-I，文件内容断言）**；source_mode ∈ default / enhanced。

### 4.4 角色卡 v2（.malingcard.json）

v1 全字段 + `cover_image`（base64 ≤500KB，512px 内等比压缩）+ `"schema_version": 2`。排除项（白名单外永不入卡）：记忆 / 亲密度 / 对话历史 / API 配置 / entities / response_rules。

### 4.5 scenes.json

```json
{ "custom": [ {"id": "sc_01", "name": "自习", "tone": "安静一点，少用表情"} ] }
```

≤3 个自定义；内置四场景不入文件（代码常量）。

---

## 5. 任务分解（17 项，四批 + 收尾）

> 工作量含自测；对齐 PRD 合计 10.5–15.5 人日。共享汇交点：第一批三件套同批对齐 commit 顺序（page_memory_book 为汇交面）。

### 第一批 · P0 三件套（F1 → F3 → F2，共享记忆中心汇交点）

| ID | 任务 | 落点 | 交付 / 断言要点 | 人日 |
|---|---|---|---|---|
| V18-01 | entities schema + MemoryManager API + pinned 注入段 | memory.py | 增删改查落盘；旧文件零破坏；上限 100/20 拒写不淘汰；`build_memory_context` pinned 段共享 300 预算 | 0.5–1 |
| V18-02 | 提及命中 request 注入通道 + 注入序位框架 | gui/chat_service.py | 提"小李"该轮 system 含实体行；未提及零注入；Agent/demo 跳过；序位框架（实体→约定→概览→场景）一次立好 | 0.5 |
| V18-03 | 「人物关系」Tab + 卡片/详情/护栏 + 删除即遗忘 | page_memory_book.py + session 链 | 删除当轮 refresh 断言；深色模式 + theme_color；无社交评分 | 1–1.5 |
| V18-04 | F1 提议-确认链（默认关） | chat_service + GuiConfig | `entity_auto_propose=False`；无确认不写入断言；两键复用反馈组件样式。**可后置 v1.8.x（PRD §8）** | 0.5–1 |
| V18-05 | timeline.py + 「共同经历」Tab | timeline.py + page_memory_book.py | 三源节点一一对应（删源节点消失）；跨年分组单测；默认 6 月展开更早；R-A 零计数 | 1–1.5 |
| V18-06 | emotion_arc 组件 + 弧线区块 + emotion_overview 注入 | gui/widgets/emotion_arc.py + memory.py + chat_service | 弧线与 get_emotions_history 一致；空日浅灰点；hover 档位词；全组件无数字断言；confide/句式触发注入、未问零注入 | 1.5–2 |

### 第二批 · P1 快赢（F6 + F5，均为基建复用）

| ID | 任务 | 落点 | 交付 / 断言要点 | 人日 |
|---|---|---|---|---|
| V18-07 | response_rules + match_rules + 「回应约定」Tab + 命中注入 | memory.py + chat_service + page_memory_book | 20 条上限拒写；未命中零注入 payload 断言；删规则当轮生效；规则/偏好/mute 三方并存断言 | 1–1.5 |
| V18-08 | 角色卡 schema v2 + cover_image 压缩链 | gui/role_card.py | v1 旧卡导入零回归；base64 ≤500KB 强压；白名单外零泄漏（导出文件内容断言） | 0.5–1 |
| V18-09 | card_import_preview 预览弹窗 + 冲突双路径 | gui/widgets + page_role.py | 字段逐项可见；异常红字 + 仍要导入确认；覆盖/另存双分支落盘正确；**对齐链零触碰** | 0.5–1 |
| V18-10 | character-card-spec.md 规范文档 | docs | 与实现逐字段一致（R-K 核对项） | 0.5 |

### 第三批 · F4 场景化（触碰调度闸，单独批次 + 完整回归）

| ID | 任务 | 落点 | 交付 / 断言要点 | 人日 |
|---|---|---|---|---|
| V18-11 | scene.py + scenes.json + GuiConfig 键 | scene.py + config.py | 时段映射表判定单测（含跨天/周末）；手动当日有效次日回落 | 0.5 |
| V18-12 | 场景注入双动作 + 睡前/NIGHT_CARE 合并 + 情绪挂起 | chat_service.py | 切换轮注入 + 幂等边界消息；22:30 交叉点无双注入断言；情绪激活当轮挂起、退出恢复（⚠-1 锚定断言）；Agent/demo 跳过 | 0.5–1 |
| V18-13 | external_daily_cap_override + 场景 chip + 设置区 | proactive_scheduler.py + page_home + page_settings | 工作场景当日 cap=1 断言；**四重闸其余零回归**（完整回归：startup_greet/免打扰/冷却/番茄钟/纪念日通道）；场景零行为统计 | 0.5–1 |

### 第四批 · F7 多模态记忆收尾（需真实看图环境联调）

| ID | 任务 | 落点 | 交付 / 断言要点 | 人日 |
|---|---|---|---|---|
| V18-14 | vision_memories + 默认档存档钩子 | memory.py + chat_service.py:2012 | 带图成功才存、纯文本零写入；文件零二进制断言（R-I 硬线）；50 条滚动淘汰 | 0.5–1 |
| V18-15 | 召回句式 + 注入 + 诚实边界 + 增强档开关 | chat_service + GuiConfig | "上次那张截图"召回引用真实内容 ≥3 用例；无匹配不编造；无视觉模型不存 + 诚实话术断言；增强档默认关零调用、失败回落 | 0.5–1 |
| V18-16 | 往期回顾 Tab 影像记忆条目 + 删除链 | page_memory_book.py | 文字卡无缩略图；删除当轮生效 | 0.5 |

### 收尾

| ID | 任务 | 落点 | 交付 / 断言要点 | 人日 |
|---|---|---|---|---|
| V18-17 | 红线扫描扩充 + 全量回归 + 打包核对 + CHANGELOG | 全局 | 扫描词表增 `情绪分数/弧线统计/社交图谱评分/相册` 全 UI 零命中；v1.7.3 全量能力回归（群聊/Pi/五分区/五态/三键/提醒）；py_compile + pytest 双绿；R-K 三核对点（新分区 QSS 深色渲染 / 角色卡 v2 dist 可用 / 影像记忆落位 ~/.maid_coder/） | 0.5–1 |

**合计：10.5–15.5 人日**（V18-04 可后置则 10–14.5）。分批闸门：第一批全绿 → 第二批 → 第三批（含调度闸完整回归）→ 第四批 → 收尾。

---

## 6. 共享知识（团队必读）

1. **注入序位框架**（V18-02 建立，全期共用）：request_injections 统一在 intent 提示（chat_service.py:1129）之后追加，顺序 = 实体提及 → 回应约定 → 情绪概览 → 场景语气；Agent / 任务 / demo 三类路径全部跳过（与 NIGHT_CARE :1134 边界逐字一致）。
2. **顶层新键三连**：entities / response_rules / vision_memories 全走 `_merge_defaults`（memory.py:117）读时迁移——不建独立文件、不升 meta.version、不写迁移脚本。
3. **删除即遗忘链**：实体 / 规则 / 影像记忆删除 → 立即 `_save()` + `session.refresh_system_context()`（session.py:197）当轮生效——三处共用同一断言模板。
4. **提议-确认组件**：F1（记人物）与 F6（记约定）共用两键确认组件与 `intent_notice` 小字样式（复用 v1.6 反馈三键先例）；无确认绝不写入。
5. **request_injections 不入历史**：一切"持续性"语义（场景底色）不能靠它承载——必须配合 session 边界消息（D-V18-07 双动作），新同学易踩。
6. **R-A 档位化纪律**：F2 弧线 / F5 性格三值 / F6 命中呈现三处均"档位词、零数字"；日格 hover / 时间线 / 规则列表一律相对时间与档位词，禁计数禁统计。
7. **对齐链敏感区**：page_role.py 的 sync_role_override_to_session / notify_role_switch 接线（:296/:1038）本期**零语义变更**；F5 只动导入入口与 role_card schema。

---

## 7. 打包评估

- **零新增第三方依赖**，exe 体积 0 增量（F2 纯 Qt、F5 QImage 既有、其余纯 stdlib）。
- hiddenimports / datas 净增核对：`timeline`、`scene`、`gui.widgets.emotion_arc`、`gui.widgets.card_import_preview`（根级新模块是 PyInstaller 隐式收集漏网高发区，**必核**）。
- R-K 发版核对点（PRD §7 三条照录）：①记忆中心 8 Tab 在包内 QSS / 深色模式渲染正常；②角色卡 v2 导入在 dist 产物可用（v1 旧卡回归）；③影像记忆 / scenes.json 在包环境落位 `~/.maid_coder/` 正常。

---

## 8. 待明确（实现期，不阻塞立项）

| # | 问题 | 建议 |
|---|---|---|
| E-1 | F1 提议链关系句式词表首版覆盖度（"我同事/我朋友/我妈/我们领导/我表…"） | 首版 8–10 条高频句式，词表外挂 JSON 可热补 |
| E-2 | F7 召回句式长尾（"那张图"无"上次"前缀） | 首版只做 PRD 句式，长尾进 v1.8.x 打磨 |
| E-3 | 情绪挂起判定的"负面信号"阈值 | 直接复用 detect_emotion 既有分类结果（tired/anxious/lonely），不新增阈值体系 |
| E-4 | 场景切换边界消息的措辞模板 | 实现 V18-12 时给 2–3 版文案，抽样评审定稿 |

---

## 9. 红线对照（本期强制口径）

| 红线 | 落点 |
|---|---|
| R-A 无焦虑 | F2 弧线零数字主战场（无分数/百分比/计数/坐标轴）；F3 无"第 N 条记忆"；F1 无社交评分；F4 无专注度/时长统计（感知时钟不感知行为）；F5 性格档位词；F6 无默契计数。扫描词表扩充进 V18-17 |
| R-D 只增量 | 顶层新键读时迁移 / page_memory_book 增量分区既有数据链零改动 / ProactivePolicy 四重闸只加输入 / `_launch_worker` 组装顺序不动 / 对齐链零语义变更 |
| R-I 隐私 | 三新键全本地；删除即遗忘当轮生效；**影像记忆绝不落盘原图/data URI**；**实体/规则/影像永不随角色卡导出**（白名单保证 + 导出内容断言）；payload 最小化（未命中零注入） |
| R-J 群聊 | 本期零触碰（群聊路径在 `_on_stream_finished` :2017 优先分流，F7 钩子在分流之后，天然隔离——验收补一条群聊带图零写入断言） |
| R-K 诚实 | F7 诚实边界三条款进验收；规范文档↔实现逐字段一致；CHANGELOG 如实；三核对点进发版流程 |

---

## 10. DoD（对照 PRD §9 逐条）

1. F1：实体 CRUD + 双通道注入（pinned 常驻 / 提及即注入 / 未提及零污染）+ 提议-确认无静默写入 + 上限护栏 + 删除当轮生效。
2. F2：8 周日格与 emotions 数据一致、hover 档位词、零数字断言；概览注入触发正确、未问零注入。
3. F3：三源聚合按月分组、删源节点消失、零计数零统计、默认 6 月展开更早。
4. F4：映射表切换、手动当日有效、cap 3→1 且四重闸零回归、三层叠加优先级断言（情绪>场景>五态，含 ⚠-1 校正锚定）、睡前无双注入。
5. F5：schema v2 文档一致（R-K）、预览逐字段 + 冲突双路径、v1 旧卡零回归、卡内永无记忆/亲密度/实体/规则。
6. F6：命中注入、未命中零成本、20 条上限、提议-确认、与偏好/mute 三方互不干扰。
7. F7：只存文字事实（零二进制断言）、召回真实、诚实边界、增强档默认关失败回落、群聊路径零写入。
8. 全局：R-A/R-D/R-I/R-K 全条对照（R-J 确认无涉）、扫描词表零命中、v1.7.3 全量零回归、py_compile + pytest 双绿、零新依赖 exe 0 增量。

---

## 11. IS_PASS 自评

| 维度 | 结论 |
|---|---|
| PRD 全覆盖 | PASS——F1~F7 全项有任务；Q-D1~D10 全部落为裁决口径；Non-goals 全部承接 |
| 源码核实 | PASS——全部对接点行号经 v1.7.3 源码逐行核实；5 处 PRD↔源码偏差（⚠-1~⚠-5）已标红并给出裁决 |
| 红线兼容 | PASS——R-A/R-D/R-I/R-J/R-K 逐条落点；新增面（弧线/时间线/实体/影像）为红线重点关照区 |
| 零重构 | PASS——既有函数签名除 build_memory_context 内部扩展外零变更；page_memory_book / ProactivePolicy / 对齐链均为增量 |
| 工作量 | PASS——17 任务合计 10.5–15.5 人日与 PRD 对齐；分批闸门与裁剪顺序承接 PRD §8（V18-04 可后置） |
| 打包 | PASS——零新依赖；hiddenimports 净增 4 项已列核对 |

**IS_PASS = YES**，可移交任务分解与排期。

> 文档结束 · 高见远 · 2026-09-10 · 基线 v1.7.3 · 群聊与 Pi 引擎零触碰
