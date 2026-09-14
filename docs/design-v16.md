# 码铃（MaLing）v1.6 增量架构设计与任务分解

- 版本：v1.6（基于 v1.5.2 重构后源码树增量，承接 `docs/prd-v16.md` v1.6a，Q-B1~B8 已按 PM 建议 + 用户裁决收敛：**B8 情绪历史上限 200 条**，其余 B1–B7 采纳默认建议）
- 文档状态：架构定稿（供开发排期与实现消费）
- 维护人：高见远（架构）
- 输入：`docs/prd-v16.md`（权威需求）+ `docs/design-v13.md`（格式与红线参照）+ `docs/audit-功能真实性清单-2026-09-07.md`（真实性基线）+ **重构后源码通读**（`memory.py` / `session.py` / `managers.py` / `gui/chat_service.py` / `gui/widgets/chat_panel.py` / `gui/adapters/gui_chat_session.py` / `gui/proactive_scheduler.py` / `greeting.py` / `highlights.py` / `gui/pages/page_memories.py` / `gui/voice_conversation.py` / `gui/widgets/handsfree_bar.py` / `gui/expr_markup.py` / `gui/main.py` / `maid_coder_gui.spec` / `tests/conftest.py`）
- 修订记录：
  - **v1.6（2026-09-08）**：初稿。7 项需求全量收录；两处**对 PRD 现状判断的架构校正**（D-V16-08 摘要链路、D-V16-07 失败保留现状）；一处兼容性微调标红（D-V16-03 记忆上下文排序）。

> **红线复述（PRD §2，实现逐条对照）**：R-A 无焦虑（记忆中心无计数/容量语义、三键不进 intimacy、周回顾无打卡）；R-D 只增量不重构（page_memories 不动、四重闸结构不动、UI 直插唯一渲染入口不动）；R-I 记忆隐私（全本地 `~/.maid_coder/`、删除立即落盘当轮生效、周回顾请求不含对话原文）；R-G/R-H 无涉重申；**R-K 发布诚实**（"已实现待验证"必须真机销项、文档↔dist 逐项核对）。

---

## 1. 增量范围（对照 PRD §1，简列）

| PRD ID | 需求 | 一句话承接 | 架构归属 |
|---|---|---|---|
| P0-1 | 透明记忆中心 | 偏好/话题/情绪三分区透出 + 来源时间元数据 + 增删改（**情绪上限 200**） | D-V16-01/02/03 / §3 / §5 |
| P0-2 | 聊天意图五态 | 纯规则五态路由（闲聊默认/技术/任务/待办/情绪），只附加不接管 | D-V16-04 / §3 / §5 |
| P0-3 | 主动陪伴连续性 | build_topic_followup 接线 + 内容拼装 + 反馈三键写回 | D-V16-05/06 / §3 / §5 |
| P0-4 | 聊天细节打磨 | 验证三项（停止/边界/编辑链）+ 新做四项（失败重试/改后重发/反套话/状态链） | D-V16-07/08/12 / §3 / §5 |
| P1-1 | 语音细节 | 失败反馈/退出恢复 10min 缓冲/打断反馈/录音微提示 + 标定留档 | D-V16-11 / §3 / §5 |
| P1-2 | 陪伴质量测试套件 | ≥15 剧本，mock 进 CI <60s + 真实档手动脚本，结果 JSON 对比 | D-V16-09 / §3 / §5 |
| P1-3 | 每周共同回顾 | 周日 18:00–21:00 窗口首次打开呈现、规则骨架零 LLM 默认、错过不补 | D-V16-10 / §3 / §5 |

**Non-goals（沿用 PRD §1.3）**：多角色群聊 / 人设工坊 / 女仆日记 / 时段仪式 / 贴身提醒 / 关系阶段叙事 / 完整安慰模式（= v1.7 F3–F9）；语音通话闭环 / 桌宠深化 / AI 形象；记忆云端同步（R-I）。**补充架构边界**：P0-2 五态不做 LLM 分类器；P0-3 不改 intimacy 计分链；P1-3 LLM 润色只留接口默认关。

---

## 2. 关键架构决策

### 决策表总览

| 编号 | 对应 | 结论（一句话） | 风险级 |
|---|---|---|---|
| D-V16-01 | P0-1 | memory.py schema 增量：偏好对象化（source/created_at/updated_at，读时迁移 legacy）、话题增 source+followup 三字段、emotions 历史上限 **200**、delete_topic_forever 物理删除 | 中（schema 兼容） |
| D-V16-02 | P0-1 | 新建 `gui/pages/page_memory_book.py` 三分区页（page_memories 高光册零改动）；"删除即遗忘"经 `session.refresh_system_context()` 当轮生效 | 低 |
| D-V16-03 | P0-1 | build_memory_context 兼容性**微调（标红）**：活跃话题按 last_mentioned 降序取 3、仅 ongoing；偏好全量——接口签名不变 | 低 |
| D-V16-04 | P0-2 | 新建根级 `intent.py`（纯 stdlib）：内置词表 + 可选 `intent_words.json` 热加载；ChatService.send_message 前置路由；Agent 显式开关绝对优先；只附加不接管 | 中 |
| D-V16-05 | P0-3 | 反馈三键 = 订阅 `proactive_message` 的**独立动作行 widget**（不触碰气泡内部、不入会话存档）；写 `memory.record_followup_feedback`；不 mark_user_activity（防自续命）、不进 intimacy（R-A） | 中 |
| D-V16-06 | P0-3 | 内容拼装在调度侧：`greeting.build_contentful_line(memory_mgr, todo_mgr)` 纯函数 + scheduler 接线（idle_hello / 新 startup_greet 一次性场景）；无命中逐字回退现有模板 | 中 |
| D-V16-07 | P0-4 | 失败保留+重试：现状**session 已保留 user 消息**（_launch_worker 先写后调 API，失败不回滚）——缺的只是 UI 入口；新增 `ChatService.retry_last_failure()`（skip_history_write 防重复入库）+ 错误动作行（🔄/✏️）+ 连续 3 次引导 | 中 |
| D-V16-08 | P0-4 | **PRD 现状校正（标红）**：`auto_summary` 仅 CLI single_turn 调用，GUI 链路从不触发——GUI 的"上下文精简"= `_trim_history` 截断。反套话条件改用新暴露的 `session.context_trimmed` 标志（截断或摘要发生过即置位），注入为**请求级 system 消息**（不入会话历史） | 中 |
| D-V16-09 | P1-2 | 剧本 = JSON 数据文件 + 双档 runner（mock 档 pytest 断言拼装/闸门/去重；真实档手动脚本）；结果落盘 `docs/_qa_v16/companion_*.json` 版本对比 | 低 |
| D-V16-10 | P1-3 | 新建根级 `weekly.py`（纯 stdlib）：周日 18:00–21:00 窗口启动判定、52 周滚动淘汰、规则骨架零 LLM；highlights 增 `query_range`；page_home 卡片 + page_memory_book 往期 Tab | 低 |
| D-V16-11 | P1-1 | 免提退出 10min 缓冲计入闸：ProactivePolicy 增 `external_cooldown_until`（PolicyState 字段），非独立闸；失败计数 ≥3 状态条提示 | 低 |
| D-V16-12 | P0-4 | 验证三项（停止/边界/编辑链）= **验证任务非开发任务**：给出可执行验证步骤与留档文档，R-K 销项 | 低 |

---

### 2.1 D-V16-01 · memory.py schema 增量与向后兼容（P0-1 核心）

**现状核实**（memory.py）：`preferences: {k: v:str}` 纯键值（无元数据，:115-130）；话题条目 `{subject, last_mentioned, status}`（无 source）；情绪只有 `habits.last_emotion/last_emotion_time` 单条（:265-266）；`forget_topic` 软删除进 archived（:173-184）；`build_topic_followup` 已实现无调用方（:307-322）。

**增量字段**（`_DEFAULT_MEMORY` 合并式扩展，`meta.version` 保持 1，不引入 schema_version 升级流程）：

1. **偏好对象化**：`preferences[key] = {value, source, created_at, updated_at}`；`source ∈ {"auto","manual","legacy"}`。
   - **读时迁移**（`_merge_defaults` 内）：遇旧格式 `str` 值 → 包装为 `{value: 原值, source: "legacy", created_at: meta.updated_at 或 meta.created_at}`。**不用 "manual"**（避免把机器提取误标为"你告诉我的"），UI 显示"（早期记忆）"。
   - **向后兼容守卫**：`get_preference()` 迁移后仍返回 `str`（value 字段）——既有调用方（page_home.py:544 nickname、session._build_system_prompt、greeting）**零改动**；`list_preferences()` 新增返回结构化副本 `{key: {value, source, created_at}}`，仅记忆中心页消费。
   - `extract_from_dialogue` 写入时 source="auto"；记忆中心页手动添加/编辑 source="manual"。
2. **话题增补**：条目加 `source`（"auto"/"manual"，同上迁移默认 "legacy"）；`add_topic`/`extract_from_dialogue` 增可选 source 参数。
3. **followup 三字段**（P0-3 依赖，随本项一次落盘避免二次迁移）：`followup_asked_at`（最近一次续接提问时间，7 天去重）、`followup_muted_until`（"先不提"静默截止 ISO）、`followup_score`（int，"说到心坎" +1）。
4. **emotions 历史**：顶层新键 `"emotions": [{time, emotion, excerpt(≤30 字)}]`，**上限 200 条**（Q-B8 用户裁决，append 淘汰最旧）；`extract_from_dialogue` 命中情绪时 append（同时保留 habits.last_emotion 单条兼容 main.py:288 既有读取）。空态/说明文案（R-A/R-I 合规）由页面层承担，memory 层只存数据。
5. **物理删除**：`delete_topic_forever(subject) -> bool`——active 与 archived 两列表同删（精确 subject 匹配，不用 `in` 模糊匹配防误删），物理移除并落盘。
6. **followup 感知增强**：`build_topic_followup(min_hours, max_hours)` 增量逻辑——① 跳过 `followup_muted_until > now` 的话题；② 跳过 `followup_asked_at` 距今 <7 天的话题；③ 同分加权排序：优先 `followup_score` 高者，命中后写 `followup_asked_at` 并 `_save()`。**接口签名不变**（旧调用语义纯增量收紧）。
7. **反馈写回**：`record_followup_feedback(subject, feedback)`——feedback ∈ {"heart","mute","chat"}；heart：`followup_score += 1`（后续续接间隔经加权自然缩短至 48h 语义，见 D-V16-06）；mute：`followup_muted_until = now + 14 天`（Q-B7，常量 `_FOLLOWUP_MUTE_DAYS = 14` 可调）；chat：仅记 `followup_asked_at`（策略不变）。另支持特殊键 `__emotion__` / `__todo__`（对情绪延续/待办轻提两内容源 mute 3 天，常量 `_SOURCE_MUTE_DAYS = 3`），由 scheduler 侧组装 feedback 时选择键。
8. **build_memory_context**：见 D-V16-03。

**风险点**：旧 user_memory.json 迁移一次性、幂等（读时包装、下次 _save 自然固化新结构）；session.save/load 的 `memory.to_dict()/from_dict()` 全量快照往返兼容（from_dict 走 _merge_defaults 自动迁移）。**降级**：若迁移在极端脏数据上抛错，`_load` 已有 try/except 重建默认结构兜底（现状保留），迁移逻辑包 try 逐条守卫。

---

### 2.2 D-V16-02 · 记忆中心新页 page_memory_book（P0-1 UI）

**现状核实**：`page_memories.py` = 高光回忆册（HighlightsManager 专用，:24-59 + 时间倒序卡片），**与 MemoryManager 无任何引用**（全 gui/ 树 grep 证实：memory_mgr 仅 main.py/page_home.py 读取）——审计清单 C3 行"GUI 记忆页存在"对 v1.5.2 已失真，PRD 缺口四判断正确。

**落法**：

1. 新建 `gui/pages/page_memory_book.py`：三分区 Tab 或分节（**主人偏好 / 活跃话题 / 情绪记录**）+ 底部固定一行「📔 这里的一切只存于你的电脑，删除立即生效。」。取色一律 `theme_color(app_ctx, key, fallback)`；注册走 sidebar `NAV_ITEMS` + main_window `page_classes` 同既有模式（置于「回忆 ✨」之下）。
2. **数据源**：`app_ctx.session.memory_mgr`（GuiChatSession `__getattr__` 透传，:84-86）；页面增删改只调 MemoryManager 既有/新增方法，**页面不直接改 `_data`**。
3. **删除即遗忘接线**（R-I 硬要求"当轮生效"）：MemoryManager 删除即 `_save()`（内存与文件同步），但 system prompt 里的记忆段落只在 `_update_system()` 时重建——新增 `ChatSession.refresh_system_context()`（**一行薄包装 = `_update_system()`**，session.py 公开方法，CLI/GUI 共用）；记忆中心页每次增删改后调用 `app_ctx.session.refresh_system_context()`。测试断言：删除偏好 → refresh → `history[0]["content"]` 不再含该条。
4. **角标呈现**（Q-B1 双角标）：来源（自动记下 / 你告诉我的 / 早期记忆）+ 最近提及时间（话题用 last_mentioned、偏好用 updated_at，"3 天前提到"式相对时间）。
5. **红线自检内建**：无条目计数徽章、无容量条、无进度；情绪分区顶部中性说明照 PRD §4.1 文案。
6. "已归档"折叠只读区 + 「🗑 彻底删除」入口（调 `delete_topic_forever`，弹确认框——物理删除不可逆）。

**风险点**：main_window page_classes / sidebar NAV_ITEMS 为多人汇交点（v1.4 屡次触碰），本项只加一行注册。**降级**：情绪分区若一期内做不完，先交付偏好+话题两分区 + 情绪分区占位中性文案（诚实标注"整理中"），不阻断主链。

---

### 2.3 D-V16-03 · build_memory_context 兼容性微调（标红）

PRD §4.1 说"注入逻辑不变"；用户裁决口径（架构接收的任务面）为"按相关度+类型过滤"。两相调和后的**最小微调**（接口签名 `build_memory_context(max_chars=300)` 不变）：

- 活跃话题：由现状"取列表**末尾** 3 个（append 顺序）"改为"按 `last_mentioned` **降序**取 3 个、仅 `status=="ongoing"`"——老用户数据上行为差异极小（近期提及的通常就是最新 append 的），但语义更正确（归档再活跃的话题不再占注入位）。
- 偏好：全量注入不变。
- **不注入** muted_until/score 等策略字段（它们只服务主动续接，与 system 注入无关——防止 prompt 污染）。

若 PM 复核坚持零变化，回退=删除排序两行，其余不受影响。

---

### 2.4 D-V16-04 · 意图五态路由（P0-2）

**落法**：

1. **新建根级 `intent.py`（纯 stdlib，零 Qt 零 core 依赖，可独立单测）**：
   - `classify_intent(text: str) -> str`，返回 `"chat" | "tech" | "task" | "todo" | "emotion"`；内部 = 词表匹配（优先）+ 句式正则（"提醒我/叫我/别让我忘"→todo；"帮我改/跑一下/看看这个报错/读一下/写一个"→task；"什么是/为什么/怎么做 + 技术词"→tech；强情绪词命中复用 memory._EMOTION_KEYWORDS 同源词表**副本**（intent.py 不 import memory，保持零依赖，词表数据重复一份并由测试断言两边一致）→emotion；其余→chat）。
   - **词表数据文件**：内置默认词表常量兜底；模块加载时尝试读同目录 `intent_words.json`（`{state: [words]}`，<20KB），成功则合并覆盖、失败静默用内置——社区可增补、离线可用。热加载 = 提供 `reload_words()` 供设置页后续使用（本期不接 UI）。
   - 判定纯函数、零 token、零网络；**未识别/低置信一律落 "chat"**（Q-B2）。
2. **ChatService.send_message 前置路由**（chat_service.py:591 入口、入队前）：
   - **显式开关绝对优先**：`self._agent_mode == True` 或 `task_type != "chat"`（🖱 操作单步路由等）→ **完全跳过路由**（Q-B2，与 v1.5.2 行为逐字一致）。
   - 演示模式（`_is_demo_mode`）→ 跳过路由（demo 无附加行为意义）。
   - 路由命中后**只做附加、必走普通聊天链**（防消息黑洞的底设计）：
     - `tech`：`web_search_enabled_gui` 开 → task_config 直接置 `web_search_query`（**跳过 `should_auto_search` 二次判定**——tech 态本身即技术判定，收敛语义；联网提示小字沿用既有 `web_search_notice` 链）。
     - `task`：Agent 开关关 → 发 `intent_notice("🔧 检测到技术任务，可在首页点亮 Agent 模式让我动手")`；开 → 不会到这（上面已跳过）。
     - `todo`：`session.todo_mgr.add_item(text)`（TodoManager.add_item 既有，managers.py:153）+ `intent_notice("📭 已记入待办，可在待办清单查看")`。
     - `emotion`：本轮请求注入语气放缓提示（见 D-V16-08 的请求级注入机制）+ **不**做任何其它动作（完整安慰模式 = v1.7 F6，Q-B6）。
     - `chat`：零附加。
   - 新信号 `intent_notice = Signal(str)`；主窗/浮窗面板渲染复用联网提示的小字插入样式（不入会话存档）。
3. **幂等**：路由只作用于用户发送路径；proactive_ask / screen_bubble / retry 重发（skip_history_write 路径）均**不再过路由**（retry 保持原 task_type 原样重发）。

**风险点**：规则分类长尾误判——上限=多一行小字提示，可接受；词表 JSON 脏数据 → 合并前做 `isinstance(list)` 逐项守卫。**降级**：intent.py 加载失败 → classify_intent 恒返 "chat"，全链退化为 v1.5.2 行为。

---

### 2.5 D-V16-05 · 反馈三键数据流（P0-3 反馈闭环）

**现状核实**：主动消息渲染双链已存在——正文经 `session.add_message("assistant", ..., proactive=True)` → `gui_session.message_added` 单入口落主窗/浮窗气泡（无双气泡）；`ChatService.proactive_message(text, scene)` 信号另有 chat_window:408（托盘静默气泡）订阅。**主面板气泡渲染时拿不到 meta**（message_added 只传 role/content）。

**落法**（不触碰 MessageBubble 内部、不改 message_added 签名——R-D）：

1. **新建 `gui/widgets/proactive_feedback.py`**：`ProactiveFeedbackBar(QWidget)`——一行三个轻量小按钮「💗 说到心坎」「🙈 先不提这个」「💬 想聊聊」，**hover 展开式**（Q-B3：默认收起为一个小 ✨ 图标，hover 浮现三键；若后续反馈隐蔽可切常驻，构造参数可配）。发出 `feedback_picked(str)`（"heart"/"mute"/"chat"）+ 点击后按钮态收敛（置禁用 + 打勾文案，防重复提交）。
2. **挂载**：chat_panel 与 chat_window 各自订阅 `proactive_message(text, scene)`，在该次主动气泡渲染完成后，于消息流末尾插入一个 FeedbackBar（与 `_on_web_search_notice` 的 QLabel 插入同款"末尾 stretch 之前"位，**不入会话存档**）；下一条用户消息发出时自动移除未点击的 FeedbackBar（防堆积）。
3. **数据流**：FeedbackBar 点击 → 面板回调 →
   - `scene` 与内容源解析：scheduler 投递时把**内容源键**随 scene 一并带出——方案：`proactive_message` 信号**不改签名**，scheduler 把 subject 编进投递文本约定分隔行（`【关于：{subject}】` 首行，UI 剥离展示）？——**否决**（污染正文）。**采纳**：ChatService 增新信号 `proactive_feedback_ready = Signal(str, str)`（subject, scene）由 scheduler 经 chat_service 新方法 `proactive_ask(text, scene, subject="")` 透传（proactive_ask 加第三可选参，既有调用不破）；FeedbackBar 挂载时同时收到 text/scene/subject 三元组。情绪延续源 subject="__emotion__"、待办轻提 subject="__todo__"、模板问候 subject=""（无内容源 → **不渲染三键**，纯模板无需反馈）。
   - 点击 → `memory_mgr.record_followup_feedback(subject, feedback)`（D-V16-01 第 7 条）。
4. **护栏断言**（验收 3）：三键点击路径**绝不调用** `mark_user_activity` / `scheduler.mark_user_activity` / `intimacy.add_interaction` / `collab.bump_intimacy`——纯 memory 策略写入（R-A + 防自续命零回归）。"想聊聊"只发 `intent_notice("那我们接着聊~ 主人直接说就好")` 引导 + 记 asked_at，不改策略。
5. **加权语义**：「说到心坎」→ score+1；build_topic_followup 按 score 降序优先 + 命中后 asked_at 去重 7 天 → 实际效果 = 该话题更被优先续接（≈48h 级间隔，与 1–72h 窗口天然衔接，无需新增独立间隔字段）。

**风险点**：浮窗/主窗双实例都挂 FeedbackBar → 同一主动消息两侧各一行，属预期（两窗独立消息流）；subject 为空串时三键不渲染（防无意义反馈）。**降级**：hover 展开实现成本超预期 → 先常驻三小键（Q-B3 备选形态），交互打磨后置。

---

### 2.6 D-V16-06 · 主动内容拼装与 startup_greet（P0-3 内容侧）

**现状核实**：`build_topic_followup` 全树无调用方；`run_check` 文案 = `build_text(scene, companion)` 纯模板池；`_last_user_activity_at` 启动时为 None → 既有 idle_hello 启动后不会命中（场景判定要求 last_user_activity 非空，proactive_scheduler.py:184）——**启动问候渠道今天不存在**。

**落法**：

1. **greeting.py 新增纯函数** `build_contentful_line(memory_mgr, todo_mgr) -> Optional[str]`（无 Qt 无 random 依赖注入由调用方做）——按优先级拼装、**同次最多 1 条，宁缺毋滥**：
   - ① 话题续接：`memory_mgr.build_topic_followup(1, 72)` 命中 → 直接采用（内部已含 muted/去重/加权，D-V16-01 第 6 条）；
   - ② 情绪延续：`memory_mgr.get_last_emotion() ∈ ("tired","anxious","lonely")` 且 `habits.last_emotion_time` 在 24h 内 → 模板句（"昨天感觉你有点累，今天好些了吗"池）；
   - ③ 待办轻提：`todo_mgr.items()` 存在 `done==False` 且 `created_at` ≥24h → 不点名内容模板（"便签上还留着一件没做完的事…"池）；
   - 无命中 → 返回 None。
2. **scheduler 接线**（proactive_scheduler.py 增量，四重闸结构不动）：`run_check` 与新 startup 场景在 `_deliver` 前：`line = build_contentful_line(...)`；命中 → 投递 `f"{模板开头}{line}"`（模板做轻开头衔接，如场景句 + 换行 + 内容句），`scene` 不变（idle_hello）、`subject` 随内容源传出（D-V16-05）；未命中 → `build_text(scene, companion)` **逐字回退**（验收 4：与 v1.5.2 逐字一致）。memory_mgr/todo_mgr 来源 = `app_ctx.session.memory_mgr / .todo_mgr`（getattr 防御，缺失→None→回退模板）。`llm_enhance` 开关沿用既有配置（默认 False，零 token）。
3. **startup_greet 一次性场景**：scheduler 新增 `maybe_startup_greet() -> Optional[str]`（仿 `maybe_anniversary_blessing` 独立通道模式，但**走完整四重闸并占 cap/cooldown**——与随后的 idle_hello 天然互斥不双发）：gui/main.py 装配完成后调用一次（try/except 不阻断启动）；内部 = gates 检查 → 内容拼装/模板 → `_deliver` → `commit_proactive(count_delta=1)`。触发窗口：启动后首个 tick（复用 `_on_tick` 附带判定，用一次性内存标记防重复）。
4. **记账**：内容命中话题续接时 `build_topic_followup` 内已写 asked_at；`followup_asked_at` 7 天去重 + 同话题不重复（验收 1）由此保证。
5. **防自续命零回归**：内容拼装与三键路径均不触碰 `mark_user_activity`（run_check 既有结构保持）。

**风险点**：startup_greet 与用户开机即打字竞争 → gates 含 cooldown、用户已交互（last_user_activity 非空且 < idle 阈值）时 startup_greet 让路（判 `st.last_user_activity_at is None or 空闲达标` 才开口）。**降级**：startup_greet 若回归面超预期 → 仅接线 idle_hello 内容拼装（启动问候 v1.7 F2 再补），PRD 主验收（验收 1/2）不受影响。

---

### 2.7 D-V16-07 · 失败保留 + 一键重试 + 改后重发（P0-4 ④⑤）

**现状核实（含一处 PRD 判断的落地校正）**：`_launch_worker` 在 worker 启动**前**已 `session.add_message("user", ...)`（chat_service.py:878），失败路径（`_on_api_error`）不回滚 → **"失败保留"在数据层已成立**（user 消息在 session 与 UI 气泡都在）；真正缺口 = ①错误气泡无「重试/改后重发」入口 ②重试若走 `send_message` 会**重复入库 user 消息** ③连续失败无引导。CLI 侧 `single_turn` 失败才回滚 pop（session.py:609-611），与 GUI 无关。

**落法**：

1. **ChatService 增量**：
   - 失败时记 `self._last_failure = {"text": user_text, "task_type": task_type, "ts": time.time()}`（在 `_on_api_error` 与 `run()` 异常路径统一记录——统一收口：ChatService._on_api_error 已经是所有 message_failed 的汇聚点，在这里记录即可）；
   - 新增 `retry_last_failure()`：取 `_last_failure` → `_enqueue_request({"kind": "send", "text": ..., "task_type": ..., "suppress_echo": True, "skip_history_write": True})`；`_launch_worker` 尊重 `skip_history_write`（跳过 :868-882 的 session.add_message 段，其余不变）→ **幂等不重复入库**；清空 `_last_failure`、失败计数复位逻辑见下。
   - 连续失败计数 `self._fail_streak`：`_on_api_error` +1、`_on_stream_finished` 归零；≥3 → 错误文案追加引导（"连续几次都没连上，建议检查网络或 API Key——设置里可以测一下连接"），文案走 `user_messages` 既有友好错误体系（format_api_error 之后拼接）。
2. **chat_panel 增量**：
   - `_on_message_failed` 时保留失败现场的引用对 `(user_bubble, error_row)`——错误气泡照旧渲染（error_style），其下挂**错误动作行**（新小组件或复用 FeedbackBar 布局风格）：「🔄 重试」「✏️ 改后重发」；点击"重试"→ 先移除错误动作行 + 状态 chip 转"重试中…" → `chat_service.retry_last_failure()`；
   - 「改后重发」→ 对**失败前的 user 气泡**执行既有 `_on_edit_requested` 截断链（R9 确认框 + 截断该条及之后 + 回填输入框，chat_panel 既有实现零改动复用）——用户改完自行发送；旧错误动作行随截断一并 deleteLater；
   - 重试成功（`_on_stream_finished`）→ 移除残留错误行、`_last_failure=None`。
3. **边界**：demo 模式不产生 message_failed（演示链不失败）→ 无入口冲突；Agent/任务模式失败同样可重试（task_type 原样保留）；重试期间再次失败 → 计数累计、入口仍可用。

**风险点**：retry 与用户此时手动输入竞争 → 队列 `queue.Queue` 串行既有机制保证顺序；`skip_history_write` 必须同时跳过 echo（suppress_echo=True 强制）防双气泡。**降级**：若"改后重发"复用编辑链出现截断语义边界问题 → 一期先只交付「🔄 重试」（PRD ⑤ 标注为收敛项，可后置），④ 主验收（消息不丢、可重试）不受影响。

---

### 2.8 D-V16-08 · 反套话注入 + 发送状态显示链（P0-4 ⑥⑦）

**⚠️ PRD 现状校正（标红）**：PRD §4.4 表称"② 上下文边界 = max_history_rounds 截断（session.py:226）+ auto_summary 每 N 轮摘要（session.py:301-319）"。**通读证实：`auto_summary` 仅在 CLI `single_turn` 内调用（session.py:560-563），GUI 全树（gui/**）零调用**——GUI 的上下文精简**只有 `_trim_history` 截断**（add_message 内每次触发）。因此：⑥ 的注入条件不能写"auto_summary 触发后"；② 的 GUI 验证步骤按"截断生效"设计，"摘要自然衔接"项仅 CLI 链验证。

**落法**：

1. **`session.py` 增量**：`self.context_trimmed: bool = False`（`__init__`）；`_trim_history` 内 `len(others) > max_msgs` 实际裁剪发生时置 True；`auto_summary` 成功时置 True；`clear()` 复位 False；只增不清（会话级标志，不做撤销）。新增 `refresh_system_context()`（D-V16-02 共用）。
2. **请求级注入机制**（ChatService._launch_worker，一次改造服务 ⑤⑥ 两态）：组装 history 后、worker 启动前，按需在**消息副本**末尾 user 之前插入 system 注入条目（`history + [injection] + [user]` 顺序，**不写入 session.history**——当轮生效、不入存档，与 P0-2 ⑤情绪提示同一机制）：
   - `getattr(session, "context_trimmed", False)` → 追加反套话指令（文案定稿）："【诚实边界】较早期的对话已被精简为摘要。若主人问到已精简的内容，请如实说明'那段我们聊天的细节我记不全了，只记得大概'，并主动提议补充要点；**绝不编造当时的具体原话**。"
   - P0-2 emotion 态 → 追加语气放缓提示（一句，不做人设覆盖）。
   - 未触发条件 → 零注入（验收：未摘要场景不注入，零打扰）。
3. **发送状态显示链（⑦）**：chat_panel 既有 `status_label`（现仅"思考中..."）升级为状态 chip 链，由 ChatService 既有信号驱动，**零新信号**：`send_message` 调用后 →「发送中…」；`message_stream_started` →「模型响应中…」；首个 `message_chunk_received` →「接收中…」（与 thinking 表情联动并存，chip 与表情互不覆盖——chip 在状态行、表情在气泡区）；`retry_last_failure` →「重试中…」；失败 →「发送失败」+ 动作行承接；完成/取消 → 清空（现状行为）。**无百分比、无进度条、无耗时数字**（R-A）；Agent 模式下工具执行阶段 chip 显示「正在动手处理…」（agent_tool_event 首事件触发）。
4. **验证步骤（②上下文边界，R-K 销项）**：见 §5 P0-4a 任务；payload 长度断言以 `session.history` 条数与请求 messages 条数差值核对。

**风险点**：注入条目被 `_trim_history` 的 recent_injections 保留逻辑影响？——不会：注入只存在于请求副本，session.history 从未包含它。**降级**：反套话指令若与某角色 system 冲突（极少数第三方角色卡），提供 cfg 开关 `anti_hallucination_inject`(默认 True) 一键关（config.yaml agent 段，不进 UI）。

---

### 2.9 D-V16-09 · 陪伴质量测试套件（P1-2）

**落法**：

1. **剧本数据**：`tests/companion_scenarios/scenarios/*.json`（每剧本一文件）——`{id, title, targets:["P0-1"...], steps:[{action, expect}], redline_words:[...]}`；≥15 条覆盖：时段问候（早/午/深夜）、话题续接命中/7 天去重/14 天静默、情绪延续、待办轻提、反馈三键三路径、升级播报恰一次、免打扰静默、意图五态路由（每态 ≥1 + 误判落默认）、反套话诚实、记忆删除即遗忘、30–50 轮人设漂移（mock 固定回复序列下断言 history 截断与 system 稳定）、六角色切换串味（notify_role_switch 边界消息断言）、20 事实召回 + 修改事实（偏好写改删链）。
2. **mock 档 runner**（pytest，进 CI）：`tests/companion_scenarios/test_scenarios.py` 通用驱动——LLM 调用点（api.chat/chat_stream_chunks）统一 monkeypatch 固定响应；断言拼装逻辑/四重闸/去重/字数/红线词表（R-A 扫描词固化为断言：筹码/胜率/倒数/断签/打卡/进度/第 N 次等）。目标全绿 <60s。
3. **真实档 runner**（手动）：`tests/companion_scenarios/run_real_check.py`——同一剧本库、真实 LLM（读 config.yaml），输出逐剧本结果（关键词断言为辅 + 人工评审位）；成本护栏：脚本内置剧本总数与预算上限提示（Q-B5：单次全剧本 ≤¥1），**不进 CI、不进 exe**。
4. **结果落盘**：两个 runner 均写 `docs/_qa_v16/companion_<yyyymmdd_hhmm>_<mock|real>.json`（版本号 + 逐剧本 pass/fail），与上一份对比输出增量摘要（供 R-K 发布核对引用）。
5. mock 档所需注入点均为既有纯逻辑层（ProactivePolicy/MemoryManager/greeting/intent 无 Qt 可直测；proactive_scheduler QT_OK=False 降级路径既有——conftest 无需新 fixture，补一个 `mock_app_ctx` 即可）。

**风险点**：剧本对实现细节耦合过深导致脆弱 → expect 用行为断言（"muted_until 距今 ≥13 天"）而非实现断言（"字段==具体 ISO"）。**降级**：人设漂移长剧本若 CI 超时，拆为 `@pytest.mark.slow` 仍进 CI 但允许 120s（与 <60s 主套件分离计数）。

---

### 2.10 D-V16-10 · 每周共同回顾（P1-3）

**落法**：

1. **新建根级 `weekly.py`（纯 stdlib，HighlightsManager 同款风格）**：`WeeklyReviewManager(filepath)`——存 `~/.maid_coder/weekly.json`：`{"schema_version":1, "reviews":[{"week_start":"YYYY-MM-DD"(周一), "generated_at":ISO, "skeleton":{...}, "polished":null}]}`，**52 周滚动淘汰**（写入时裁剪）。
2. **生成判定** `maybe_generate(now, highlights, memory_mgr, companion) -> Optional[dict]`：`now` 为周日且 18:00–21:00（Q-B4）∧ 本周（week_start 键）无已生成记录 → 生成；**错过窗口不补**（week 键无记录即跳过，无补发队列）。生成内容（规则骨架，零 LLM）：
   - 消息量档位词：本周消息数映射"清闲的一周/张弛有度的一周/忙碌的一周"三档（**不报具体数字**，R-A；数据源 `session.token_used` 不可用（是 token），改用 StatsTracker?——GUI 侧无持久消息计数 → **用 highligt/话题/情绪活动度综合判档**（有任一记录=有来有往，全空=安静的一周），诚实且零新增统计面）；
   - 新增话题与完成话题（memory topics 按 completed_at/last_mentioned 周区间过滤）；
   - 高光精选 ≤3 条（`highlights.query_range(week_start, week_end, limit=3)`，直接引用用户收藏原文——R-I 安全：用户自己收藏的）；
   - 情绪概览档位描述（emotions 历史周区间，"大部分时间都很有干劲"式）；
   - 相伴天数（`companion.streak_info()` 既有，读 only）。
3. **highlights.py 增量**：`query_range(start_date, end_date, limit=3) -> List[dict]`（按 `date` 字段区间倒序）——纯读方法，零风险。
4. **触发与呈现**：gui/main.py 启动装配完成后调 `maybe_generate`（try/except）；page_home 增「本周回顾」卡片（有本周记录才渲染，无则不出现——无空卡打扰）；**无系统通知无推送**（R-C 精神）；page_memory_book 增「往期回顾」Tab（时间倒序翻阅）。
5. **LLM 润色口**（预留，默认关）：`skeleton` 存档后，若 GuiConfig `weekly_llm_polish=True` → 把**骨架要点**（不含任何对话原文，R-I）交 `api.chat` 生成 80–150 字"她口吻"周记存 `polished` 字段；失败静默回落骨架。本期不接设置页 UI（留 v1.7 与日记共用预算口径时再开入口），配置键先落。
6. **红线**：无"第 N 周"、无连续回顾、无周对比图表（R-A）；无系统通知（R-C）。

**风险点**：周日判定跨时区/系统时钟回拨 → 判定用本地时间 + week_start 键幂等，重开 app 不会重复生成。**降级**：page_home 卡片若汇交冲突 → 先只在 page_memory_book 呈现（验收"卡片+翻阅"折半兑现需 PM 知情）。

---

### 2.11 D-V16-11 · 语音四项打磨（P1-1）

**现状核实**：voice_conversation.py 已有 `_hard_failures ≥3` 自动暂停（硬错误）；软失败（听不懂/静默）**静默重听**（:50-52 `_SILENT_SOFT_MARKERS`，无计数无提示）；stop() 释放 busy 无缓冲；TTS 打断已有通道（tts.state_changed 钩子）；handsfree_bar 纯状态文案无动画。

**落法**：

1. **失败反馈**：软失败连续计数 `_soft_failures`（识别成功/正常发送时归零）≥3 → `notice.emit("没听清，建议换个安静环境，或改用打字和我聊~")` + 状态条展示；**不打断退出通道**（⏹/关键词/键鼠打断三通道照旧），计数达 6 自动暂停（防无限空转，上限为新增常量）。
2. **退出恢复缓冲**：`stop()` 时置 `self._resume_buffer_until = now + 10min`；scheduler 侧读 `getattr(controller, "resume_cooldown_until")` → 注入 `PolicyState.external_cooldown_until`（`ProactivePolicy.gates` 在 quiet 检查后、cap 前插入判定：`external_cooldown_until > now → return "resume_buffer"`）。**计入闸而非独立闸**（PRD 口径）：共享既有四重闸结构，只多一个输入。/controller 常量 `_RESUME_BUFFER_MIN = 10`。
3. **打断反馈**：TTS 朗读中被识别打断（既有后开口打断链）→ 补两件事：打断瞬间 `notice.emit("我在听~")`；被打断的回复**话头截断处理**——面板侧已有流式停止逻辑（_on_stream_cancelled），免提打断复用 `stop_generation` 路径，无需新增截断实现（验证项写入手册）。
4. **录音微提示**：handsfree_bar listening 态加音量呼吸动画（QTimer 驱动 ● 圆点透明度/尺寸正弦波动，纯 UI；**无波形分析、无音频落盘**，R-B）；recognizing 态显示"识别中"文案既有。
5. **真机标定清单**：新建 `docs/voice-真机标定清单-2026-09.md`——灵敏度（_INTERRUPT_AGE_MS 450）/打断阈值/失败计数阈值/麦克风增益/噪音场景，逐项留"默认值 + 真机建议值 + 验证人"空表（R-K：此前 CHANGELOG 一直声明"真机标定"未落文档，本期销项）。

**风险点**：呼吸动画 QTimer 常驻耗电 → 仅 listening 态启停；缓冲期用户主动说话 → 正常聊天链不受影响（只挡主动开口）。**降级**：external_cooldown_until 若改 gates 签名引发回归 → 改在 scheduler._build_state 内把 `last_proactive_at` 取 max(last_at, buffer_until)（零签名变更的等价实现）。

---

### 2.12 D-V16-12 · P0-4 验证三项口径（验证非开发）

①停止 / ②边界 / ③编辑重发基础链均为已上线机制，本期**验证 + 留档**（R-K）：

- **①停止生效**：真机步骤——长回复流式中点「⏹」→ 断言 3s 内 send_btn 恢复、可再次发送、无残留 worker 线程（`chat_service.is_busy()==False`）、UI 出现"生成已停止~"气泡；重复 3 次含 Agent 流式中断。留档 `docs/verify-v16-chat-details.md`。
- **②上下文边界**：自动化——mock_cfg 下 30 轮对话（> max_history_rounds）→ 断言请求 messages 长度受控（`len(session.history) <= 1 + 4 + max_history_rounds*2`）+ `context_trimmed==True` + 反套话注入出现在请求副本；"摘要自然衔接"项仅 CLI 链跑（GUI 无 auto_summary，D-V16-08 校正）。
- **③编辑重发基础链**：真机——右键编辑 user 消息 → 确认框 → 截断 + 回填 + 改后重发 → 断言后续气泡消失、会话存档同步截断、LLM 收到的是改后文本；零回归对照 v1.5.2 行为。

---

## 3. 模块 / 文件清单

### 3.1 新增文件

| 路径 | 一句话职责 | 对应需求 | 进 v1.6 承诺 |
|---|---|---|---|
| `intent.py`（根级，纯 stdlib） | classify_intent 五态纯规则分类 + 内置词表 + intent_words.json 可选热加载 | P0-2 | 是 |
| `intent_words.json`（根级） | 意图词表数据文件（<20KB，社区可增补；进 spec datas） | P0-2 | 是 |
| `gui/pages/page_memory_book.py` | 记忆中心三分区页（偏好/话题/情绪 + 来源时间角标 + 增删改 + 隐私脚注） | P0-1 | 是 |
| `gui/widgets/proactive_feedback.py` | 反馈三键动作行（hover 展开 + 收敛防重复 + feedback_picked 信号） | P0-3 | 是 |
| `weekly.py`（根级，纯 stdlib） | WeeklyReviewManager：weekly.json 52 周滚动 + 周日窗口判定 + 规则骨架生成 | P1-3 | 是 |
| `tests/companion_scenarios/scenarios/*.json` | ≥15 剧本数据文件 | P1-2 | 是 |
| `tests/companion_scenarios/test_scenarios.py` | mock 档 pytest 通用驱动（<60s） | P1-2 | 是 |
| `tests/companion_scenarios/run_real_check.py` | 真实档手动脚本（¥1 预算护栏 + 结果 JSON） | P1-2 | 是 |
| `docs/voice-真机标定清单-2026-09.md` | 语音真机标定留档（R-K 销项） | P1-1 | 是 |
| `docs/verify-v16-chat-details.md` | P0-4 验证三项销项记录（R-K） | P0-4 | 是 |

### 3.2 修改文件

| 路径 | 改动点 | 风险级 |
|---|---|---|
| `memory.py` | D-V16-01 全部：偏好对象化+读时迁移、话题 source、followup 三字段、emotions(200)、delete_topic_forever、record_followup_feedback、build_topic_followup 增强、build_memory_context 微调（D-V16-03） | 中（schema 兼容） |
| `session.py` | `context_trimmed` 标志 + `refresh_system_context()` 薄包装 + auto_summary 置位 | 低 |
| `gui/chat_service.py` | send_message 前置意图路由 + intent_notice/proactive_feedback_ready 信号 + proactive_ask 加 subject 参 + retry_last_failure/skip_history_write/_fail_streak + 请求级注入机制（emotion/反套话） | 中（发送链核心） |
| `gui/widgets/chat_panel.py` | intent_notice 小字渲染（与联网提示合并为共用插入助手）+ 错误动作行 + 重试/改后重发接线 + 状态 chip 链 + FeedbackBar 挂载 | 中（汇交点） |
| `gui/widgets/chat_window.py` | FeedbackBar 挂载（浮窗）+ intent_notice 小字（与主窗同款） | 低~中 |
| `gui/proactive_scheduler.py` | build_contentful_line 接线（run_check + maybe_startup_greet）+ PolicyState.external_cooldown_until + subject 透传 | 中（加方法不改四重闸核心） |
| `greeting.py` | 新增 `build_contentful_line(memory_mgr, todo_mgr)` 纯函数 + 三类内容模板池 | 低 |
| `gui/widgets/handsfree_bar.py` | 软失败提示态 + listening 呼吸动画 + "我在听"闪显 | 低 |
| `gui/voice_conversation.py` | `_soft_failures` 计数 + 10min resume 缓冲 + 打断 notice | 低~中 |
| `highlights.py` | `query_range(start, end, limit)` 只读方法 | 低 |
| `gui/main.py` | weekly 触发挂载 + maybe_startup_greet 调用 + FeedbackBar/新页装配守卫 | 中（装配汇交点） |
| `gui/pages/page_home.py` | 「本周回顾」卡片（有本周记录才渲染） | 低 |
| `gui/widgets/sidebar.py` | NAV_ITEMS 增 `("memory_book", "记忆中心", 📔)`（置于"回忆"之下） | 低 |
| `gui/main_window.py` | page_classes 增 `("memory_book", PageMemoryBook)` | 低 |
| `gui/config.py` | GuiConfig 增 `weekly_llm_polish`(False)（润色预留）；AppConfig 侧 `agent_anti_hallucination_inject`(True)（core/__init__.py 同步字段+env） | 低 |
| `maid_coder_gui.spec` | hiddenimports 补 `intent`/`weekly`/`gui.pages.page_memory_book`/`gui.widgets.proactive_feedback`；datas 补 `intent_words.json` | 低 |
| `CHANGELOG.md`/`version.json`/`core/__init__.py`/`README.md` | v1.6 收口同步（R-K：CHANGELOG 无自评分、"已实现待验证"如实标注） | 低 |

### 3.3 P2+ 预留（不做代码，仅留口）

- 记忆条目"原文出处"展开（Q-B1 可选增强）；意图词表设置页编辑器（reload_words 已留）；免提入口进托盘菜单；周回顾 LLM 润色设置页开关（配置键已落）；情绪分区占位补全（若一期裁剪）。

---

## 4. 数据结构

### 4.1 user_memory.json（增量，`_merge_defaults` 读时迁移，meta.version 保持 1）

```jsonc
{
  "preferences": {
    "nickname": {                       // 旧格式 "小远" 读时自动包装（source="legacy"）
      "value": "小远",
      "source": "auto",                 // auto | manual | legacy（显示：自动记下/你告诉我的/早期记忆）
      "created_at": "ISO",
      "updated_at": "ISO"
    }
  },
  "topics": {
    "active": [{
      "subject": "…", "status": "ongoing", "last_mentioned": "ISO",
      "source": "auto",                 // 新增：auto | manual | legacy
      "followup_asked_at": null,        // 新增：最近一次续接提问 ISO（7 天去重）
      "followup_muted_until": null,     // 新增：先不提 → now+14d（Q-B7 常量可调）
      "followup_score": 0               // 新增：说到心坎 +1（续接优先加权，非亲密度）
    }],
    "archived": [ "…同上结构…" ]
  },
  "habits": { "…既有键不动（含 last_emotion/last_emotion_time 单条兼容）…" },
  "emotions": [                          // 新增顶层键；上限 200（Q-B8 裁决），append 淘汰最旧
    { "time": "ISO", "emotion": "tired", "excerpt": "≤30 字触发消息摘要" }
  ],
  "meta": { "created_at": "ISO", "updated_at": "ISO", "version": 1 }
}
```

> 兼容守卫：`get_preference()` 恒返回 str；`to_dict()/from_dict()` 快照往返经 `_merge_defaults` 幂等迁移；emotions/followup 字段缺省即默认值，旧文件零破坏。

### 4.2 intent 枚举与词表（intent.py / intent_words.json）

```jsonc
// classify_intent 返回值（str 字面量，非 Enum——保持零依赖可序列化）
"chat" | "tech" | "task" | "todo" | "emotion"
// intent_words.json（可选，缺省用内置；合并加载，逐项 isinstance(list) 守卫）
{
  "todo":   ["提醒我", "叫我", "别让我忘", "帮我记着", "记一下"],
  "task":   ["帮我改", "跑一下", "看看这个报错", "读一下", "写一个", "修复", "重构"],
  "tech":   ["什么是", "为什么", "怎么做", "报错", "编译", "部署", "算法"],
  "emotion":[]   // emotion 态由情绪关键词表（与 memory._EMOTION_KEYWORDS 同源副本）判定，词表文件可扩展
}
```

### 4.3 weekly.json（新文件，`~/.maid_coder/`，原子写）

```jsonc
{
  "schema_version": 1,
  "reviews": [{
    "week_start": "2026-08-31",          // 周一（幂等键：同周仅一条）
    "generated_at": "ISO",
    "skeleton": {
      "activity_tone": "张弛有度的一周",   // 档位词，无具体数字（R-A）
      "new_topics": ["…"], "done_topics": ["…"],
      "highlights": [{"text": "…", "date": "YYYY-MM-DD"}],   // ≤3 条，用户收藏原文
      "emotion_tone": "大部分时间都很有干劲",
      "days_together": 128
    },
    "polished": null                     // LLM 润色结果（默认 null，键预留）
  }]
}
```

### 4.4 剧本 JSON（tests/companion_scenarios/scenarios/）

```jsonc
{
  "id": "followup_mute_14d",
  "title": "先不提 → 话题 14 天静默",
  "targets": ["P0-3", "P1-2"],
  "mode": "mock",                        // mock（CI） | real（手动档）
  "steps": [
    {"action": "add_topic", "args": {"subject": "Rust 入门", "hours_ago": 5}},
    {"action": "run_check", "expect": {"scene": "idle_hello", "contains": "Rust 入门"}},
    {"action": "feedback", "args": {"subject": "Rust 入门", "kind": "mute"}},
    {"action": "run_check", "expect": {"contains_not": "Rust 入门"}},
    {"action": "assert_field", "args": {"path": "topics.active[0].followup_muted_until", "days_ahead_min": 13}}
  ],
  "redline_words": ["筹码", "胜率", "倒数", "断签", "打卡", "进度", "第N次"]
}
```

### 4.5 配置增量（均带默认值，零配置可跑）

| 位置 | 键 | 默认 | 语义 |
|---|---|---|---|
| GuiConfig（gui_config.json） | `weekly_llm_polish` | false | 周回顾 LLM 润色口（本期无 UI 入口） |
| AppConfig（config.yaml agent 段） | `agent_anti_hallucination_inject` | true | 反套话注入总开关（D-V16-08 降级阀） |

---

## 5. 任务分解列表（有序按批；估算对齐 PRD 10.5–15.5 人日 + 公共项约 1.5 人日）

> 批内并行建议见 5.1；同文件汇交点：chat_service.py / chat_panel.py / proactive_scheduler.py（P0-2 与 P0-4 都触碰发送链——建议同批同人对齐 commit 顺序）；每任务完成 `py_compile` 绿 + 对应 pytest 子集绿。

### 5.1 依赖总览

- **第一批（P0-1 + P0-3，共享 memory.py 扩展）**：V16-0 → P0-1a →（P0-1b ∥ P0-3a）→ P0-3b。
- **第二批（P0-2 + P0-4，共享发送链）**：P0-4a 验证三项**最先跑**（R-K 兑现成本最低，且不依赖任何新代码）；P0-2a → P0-2b ∥ P0-4b → P0-4c。
- **第三批（P1）**：P1-2 先行（可提前与第二批并行——mock 档只依赖 P0-1a/P0-3a 逻辑）；P1-1、P1-3 独立（P1-3 依赖 P0-1b 的 page_memory_book 挂 Tab）。
- V16-X 收口最后。

### 5.2 任务表

| 任务 ID | 任务 | 依赖 | 产出文件 | 改动范围 | 估算 |
|---|---|---|---|---|---|
| V16-0 | 基线接线：spec hiddenimports/datas 一次收录 + GuiConfig/AppConfig 新配置键 + 默认词表 intent_words.json 骨架 | — | spec、gui/config.py、core/__init__.py、intent_words.json | 全仓轻量 | 0.5d |
| P0-1a | memory.py schema 增量（D-V16-01 全部）+ 读时迁移单测 + get_preference 兼容断言 + build_topic_followup 增强单测 | V16-0 | memory.py、tests/test_memory.py 增量 | 单文件 | 0.5–1d |
| P0-1b | page_memory_book 三分区页 + sidebar/main_window 注册 + refresh_system_context 接线 + 删除即遗忘自动化断言 + 旧数据迁移手工核对 | P0-1a | gui/pages/page_memory_book.py、session.py、sidebar.py、main_window.py、tests | 新页 + 3 汇交点一行 | 1–1.5d |
| P0-2a | intent.py classify_intent + 词表加载/热加载 + ≥40 用例判定单测（准确率 ≥85% 断言） | V16-0 | intent.py、tests/test_intent.py | 新文件 | 0.5d |
| P0-2b | ChatService 前置路由 + intent_notice + tech 搜索收敛 + todo 写入 + emotion 请求级注入 + 面板小字 + Agent 显式跳过回归断言 | P0-2a | gui/chat_service.py、chat_panel.py、chat_window.py、tests | 发送链 | 1–1.5d |
| P0-3a | greeting.build_contentful_line + scheduler 内容拼装接线 + maybe_startup_greet + followup_asked_at 记账 + 零内容逐字回退断言 | P0-1a | greeting.py、gui/proactive_scheduler.py、gui/main.py、tests | scheduler 增量 | 0.5–1d |
| P0-3b | proactive_feedback.py 三键组件 + 主窗/浮窗挂载 + record_followup_feedback 接线 + subject 透传（proactive_ask 扩参）+ 不进 intimacy/防自续命断言 | P0-3a（P0-1b 联动展示） | gui/widgets/proactive_feedback.py、chat_panel.py、chat_window.py、chat_service.py、tests | 新组件 + 3 汇交点 | 1d |
| P0-4a | **验证三项**（停止/边界/编辑链，D-V16-12 步骤执行）+ 留档 verify-v16-chat-details.md | —（仅真机/自动化环境） | docs/verify-v16-chat-details.md、tests 边界断言 | 验证为主 | 0.5d |
| P0-4b | 失败保留+一键重试+改后重发（D-V16-07）+ 连续失败引导 + 幂等不重复入库断言 | P0-4a（确认现状基线） | gui/chat_service.py、chat_panel.py、tests | 发送链 | 1d |
| P0-4c | 反套话注入（context_trimmed + 请求级注入）+ 发送状态 chip 链 + 注入开关 | P0-4b | session.py、chat_service.py、chat_panel.py、tests | 两文件 | 0.5–1d |
| P1-1 | 语音四项（软失败提示/10min 缓冲入闸/打断反馈/呼吸动画）+ 标定清单文档 | V16-0 | voice_conversation.py、handsfree_bar.py、proactive_scheduler.py（缓冲入闸）、docs | 语音链 | 1–1.5d |
| P1-2 | 陪伴质量套件：≥15 剧本 JSON + mock runner（<60s）+ 真实档脚本 + 结果 JSON 对比 | P0-1a、P0-3a（P0-2a 可选覆盖路由剧本） | tests/companion_scenarios/**、docs/_qa_v16/ | tests 目录 | 1.5–2d |
| P1-3 | weekly.py + highlights.query_range + page_home 卡片 + page_memory_book 往期 Tab + 周日窗口/幂等/淘汰断言 | P0-1b | weekly.py、highlights.py、gui/main.py、page_home.py、page_memory_book.py、tests | 新模块 + 3 汇交点 | 1.5–2d |
| V16-X | 收口：py_compile 全绿 + 228 项回归 + R-A 词表全 UI 扫描 + 打包 onedir 核对（R-K 文档↔dist 逐项）+ 升版 1.6.0（version.json/CHANGELOG/README，CHANGELOG 无自评分） | 全部 | version.json、CHANGELOG.md、README.md、core/__init__.py | 全仓 | 1d |

**特性任务合计 ≈ 10.5–14.5 人日，含 V16-0/V16-X 公共项 ≈ 12–16 人日**——与 PRD 10.5–15.5 口径对齐（PRD 未计公共项）。

---

## 6. 依赖 / 共享知识（design-v13 §6 沿用 1–17 + v1.6 增补）

design-v13 共享知识 1–17 全部沿用（原子写 utf-8 / hiddenimports 必加 / theme_color 禁裸值 / theme_changed 单参信号 / 气泡渲染单入口 / 主动开口三通道护栏等），v1.6 增补：

18. **user_memory.json 读时迁移幂等**：任何 schema 增量一律经 `_merge_defaults` 读时包装，不写升级脚本、不升 meta.version；`get_preference()` 对外恒 str——新字段只经新方法（`list_preferences()` 结构化）暴露。
19. **记忆中心数据流单向**：页面只调 MemoryManager 方法 → 改后必调 `session.refresh_system_context()`；页面禁止直改 `_data`、禁止自行落盘。
20. **意图路由三不**：不产生数值（R-A）、不入会话存档（提示与小字同款）、不改变消息必达（任何误判回退 chat 态普通链）。
21. **请求级注入不入历史**：emotion 语气提示 / 反套话指令 / 联网上下文（既有）都在请求副本层组装，session.history 只存真实 user/assistant——注入条件的查询靠 `context_trimmed` 标志而非扫描历史。
22. **主动反馈护栏**：三键与内容拼装路径**禁止**调用 `mark_user_activity` / `bump_intimacy` / `add_interaction`（验收 3 专项断言，P1-2 剧本固化）。
23. **测试数据隔离**：memory/weekly/highlights 测试一律 `filepath=tmp_path` 显式注入（MemoryManager/HighlightsManager 构造器已支持），**禁止**读写真实 `~/.maid_coder/`。
24. **沙箱环境批量操作约束**：本开发环境安全层对"单次删除 >50 文件"类批量操作会拦截——测试/构建清理避免一次性大批量删除（分批或保留），构建脚本不依赖 rm -rf 语义。
25. **py_compile + pytest 双绿**：每任务完成跑 `python -m py_compile <改动文件>` + `pytest tests/ -x -q`（228 项基线 + 新增），红线词扫描沿用 QA 清单（新增词：本期无新增养成语义词，沿用 13 的扩展表）。

---

## 7. 打包评估（对照 PRD §7 逐项核实）

| 需求 | 依赖 | 体积影响 | 离线性 | spec 动作 |
|---|---|---|---|---|
| P0-1 记忆中心 | 无新增第三方 | 0 | 离线 | hiddenimports 补 `gui.pages.page_memory_book`、`gui.widgets.proactive_feedback` |
| P0-2 意图五态 | 无新增（intent.py 纯 stdlib） | 0（intent_words.json <20KB） | 离线 | hiddenimports 补 `intent`；datas 补 `intent_words.json` |
| P0-3 主动连续性 | 无新增 | 0 | 离线（llm_enhance 默认关） | 无新模块（组件归 gui.widgets） |
| P0-4 细节打磨 | 无新增 | 0 | 离线（注入为本地拼装） | 无新模块 |
| P1-1 语音细节 | 无新增 | 0 | 离线（STT 网络为既有声明） | 无新模块 |
| P1-2 测试套件 | pytest 既有（不进 exe） | 0 | — | 不入包（tests 不进 spec） |
| P1-3 每周回顾 | 无新增（weekly.py 纯 stdlib） | 0 | 离线（默认规则档） | hiddenimports 补 `weekly` |

**打包总评**：全池**零新增第三方依赖**、默认 exe 体积 0 增量（R-F 沿用）；hiddenimports 净增 4 项（`intent` / `weekly` / `gui.pages.page_memory_book` / `gui.widgets.proactive_feedback`）+ datas 1 项（`intent_words.json`）。**R-K 新增核对点**（发版前 dist 逐项核对记录进 verify 文档）：① intent_words.json 落包且缺文件时内置词表兜底可跑；② 记忆中心页在包内 QSS/深色模式下渲染正常；③ `gui.widgets.proactive_feedback` 进 PYZ；④ CHANGELOG 中"已实现待验证"条目与 verify 文档一一对应。

---

## 8. 待明确事项（架构层面次要开放项，不阻塞开工）

1. **D-V16-03 注入排序微调**：活跃话题按 last_mentioned 降序（替代 append 序取末 3）——已按任务面"相关度+类型过滤"口径实施，若 PM 复核要求与 PRD"注入逻辑不变"严格一致，回退为两行改动（其余不受影响）。
2. **startup_greet 与既有 idle_hello 的首日体验**：新装机（无话题/情绪/待办）首次启动 → startup_greet 走纯模板 + 占 cap/cooldown；若用户反馈"开机就问候太吵"，常量改 `maybe_startup_greet` 默认关（配置化一行）。
3. **反馈三键 hover vs 常驻**：按 Q-B3 先 hover 展开；若实现打磨期成本超预期，回退常驻三小键（Q-B3 备选已预留构造参数）。
4. **情绪分区一期裁剪预案**：若 P0-1b 排期吃紧，情绪分区可后置为占位（诚实文案），偏好+话题分区先行——需 PM 知情，不默裁。
5. **真实档抽检频率**：Q-B5 建议"每里程碑一次"——具体挂哪个里程碑（P0 批完成 / v1.6 全量完成）由 PM 定，脚本已就绪随时可跑。

---

## 9. 红线复核（v1.6 全项对照）

| 红线 | v1.6 落实 |
|---|---|
| **R-A 无焦虑** | 记忆中心无条目计数/容量/进度（页面红线内建）；反馈三键不进 intimacy 计分链（D-V16-05 断言 + 剧本固化）；周回顾无"第 N 周"/连续/对比图表（skeleton 无计数字段）；意图路由零数值产出；状态 chip 无百分比无耗时数字。R-A 扫描词表进 P1-2 剧本固化。 |
| **R-D 只增量** | page_memories.py 零改动（新页独立）；四重闸结构不动（只增 PolicyState 输入与两个入口方法）；ChatService 发送链改动全部为前置路由/请求副本注入/失败入口增量，`_launch_worker` 既有组装顺序不动；气泡渲染单入口不动（三键/提示为独立插入 widget）。 |
| **R-I 记忆隐私** | 数据全本地 `~/.maid_coder/`；删除即 `_save()` + `refresh_system_context()` 当轮生效（自动化断言）；记忆中心显著隐私脚注；周回顾 payload 只含骨架要点 + 用户自己收藏的高光原文，不含对话原文；旧数据迁移不伪造来源（legacy≠auto）。 |
| **R-G/R-H** | v1.6 不触碰屏幕采集/操作链路；无新增第三方依赖、无外部文案引用——无涉重申。 |
| **R-J** | 不涉（本期无相关面）。 |
| **R-K 发布诚实** | ①②③"已实现待验证"三项 = P0-4a 专门验证任务 + verify 文档销项；CHANGELOG 无自评分数、如实描述边界；发版前文档↔dist 逐项核对（§7 四个新增核对点）；P1-1 真机标定清单落档销掉历史欠账。 |

---

## 10. DoD（v1.6 完成标准，承接 PRD §9）

1. 记忆中心三分区与 `user_memory.json` 实时一致；来源/时间角标全量；增删改即时原子落盘；删除当轮生效（自动化断言）；旧数据迁移不崩且来源诚实。（P0-1）
2. 五态规则路由 ≥40 用例 ≥85%；Agent 显式开关完全跳过路由（零回归）；未识别落 chat 不丢消息（"无消息黑洞"断言）；零 token。（P0-2）
3. 存在 1–72h 话题时首次主动问候必含续接句；7 天去重、14 天静默、心坎加权各有断言；四重闸与防自续命零回归；无内容源时输出与 v1.5.2 逐字一致。（P0-3）
4. 停止/边界/编辑链验证销项留档；断网消息不丢、重试幂等不重复入库、改后重发截断干净、反套话诚实（≥5 用例抽样）、状态链与真实阶段一致且无数值。（P0-4）
5. 语音软失败提示、10min 恢复缓冲（断言）、打断"我在听"反馈、录音呼吸动画四项落地；标定清单留档；无音频落盘。（P1-1）
6. ≥15 剧本 mock 档进 CI 全绿 <60s；R-A 词表断言固化；真实档脚本一键可跑、结果 JSON 版本对比。（P1-2）
7. 周日窗口一次生成、错过不补、同周幂等、52 周淘汰；默认档零 LLM；卡片+翻阅落地；无打卡语义。（P1-3）
8. R-K 全条：CHANGELOG 无自评分、"已实现待验证"如实标注、文档↔dist 核对记录在案（含 intent_words.json 落包核对）。（R-K）
9. py_compile 全绿；228 项 pytest 基线 + 新增全绿；R-A/R-D/R-I/R-K 归零（R-G/R-H/R-J 无涉确认）；零新增第三方依赖、exe 体积 0 增量。

---

## 11. IS_PASS 自审

| 检查项 | 结论 |
|---|---|
| 与 PRD（Q-B1~B8）一致性 | 通过：B1 双角标 / B2 默认 chat + Agent 显式跳过 / B3 hover 三键 / B4 周日 18:00–21:00 错过不补 / B5 CI 仅 mock + 真实档 ¥1 上限 / B6 情绪态仅当轮注入 / B7 静默 14 天 / **B8 情绪历史上限 200（用户裁决，覆盖 PRD 正文 50）**——全部落进对应决策与数据结构，无再抛回 |
| 与重构后现状一致性 | 通过：全部落点基于通读核实（memory.py:115-130/173-184/307-322、chat_service.py:591/720/878、chat_panel._on_message_failed/_on_web_search_notice、proactive_scheduler.py:184/486、page_memories=高光册实证、GuiChatSession 透传 :84-86）；两处 PRD 现状判断校正显式标红（D-V16-07 失败保留数据层已成立、D-V16-08 GUI 无 auto_summary） |
| R-D 防回归 | 通过：四重闸/气泡单入口/page_memories/_launch_worker 顺序均不动；2 处标红微调（D-V16-03 注入排序、D-V16-08 注入条件改 context_trimmed）均为行为兼容级且配回退 |
| 任务粒度 | 14 任务（含 V16-0/V16-X），依赖图清晰、三批可滚动交付；估算与 PRD 口径对齐并显式列公共项 |
| 打包与红线 | 零新增依赖确认；hiddenimports/datas 增量明确；R-A/R-D/R-I/R-K 逐条落措施 + R-J 无涉声明 |

**IS_PASS: YES**（第一批 V16-0 + P0-1a 可立即开工；2 处标红微调请 PM 复核知悉）。
