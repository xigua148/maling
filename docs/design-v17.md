# 码铃（MaLing）v1.7 增量架构设计与任务分解

- 版本：v1.7（基于 v1.6.0 已发布源码树增量，承接 `docs/prd-v17.md` v1.7a；Q-C1~C11 已在本文 D-V17 裁决定案，不再抛回用户）
- 文档状态：架构定稿（供开发排期与实现消费）
- 维护人：高见远（架构）
- 输入：`docs/prd-v17.md`（权威需求）+ `docs/design-v16.md`（v1.6 基建与格式参照）+ **v1.6.0 现状通读核实**（`gui/intent.py`（五态 confide/chat/analyze/advise/act + request_injections 机制）/ `memory.py`（pick_topic_followup / record_followup_feedback / delete_topic_forever / emotions / pin_topic）/ `gui/chat_service.py`（retry_last_failure / skip_history_write / 反套话注入 / proactive_ask(text,scene,subject)）/ `gui/proactive_scheduler.py`（内容句接线 + maybe_startup_greet + external_cooldown_until）/ `greeting.py`（build_contentful_line → {"text","subject"}）/ `weekly.py` / `gui/pages/page_memory_book.py`（3 Tab）/ `gui/models.py`（ChatMessage.metadata）+ `gui/session_manager.py`（sessions/*.json + metadata）/ `gui/pages/page_role.py`（Role schema / RoleManager / sync_role_override_to_session / notify_role_switch 链）/ `intimacy.py`（4 级 _INTIMACY_LEVELS + _check_level_up）/ `gui/tray_manager.py`（notify_maid）/ `managers.py`（TodoManager 无时间字段）/ `version.json`（1.6.0））
- 修订记录：
  - **v1.7（2026-09-08）**：初稿。六项范围（F3/F4/F5/F7/F8/F10）；Q-C1~C11 逐项 D-V17 裁决；F10 群聊给出「显示会话层承载 + 历史角色改写」最小化方案与两步切片；一处范围澄清（F6 安慰模式不进本期）。

> **红线复述（PRD §2，实现逐条对照）**：R-A 无焦虑（阶段播报无数值/日记无打卡/语录无签到）；R-D 只增量（角色 schema 向后兼容、TodoManager 旧条目零迁移、A9/对齐链不动）；R-G/R-H 无涉重申（语录库全部自创）；R-I 记忆日记隐私（日记 payload 只含摘要要点、角色卡导出不含记忆/亲密度/历史）；**R-J 群聊防失控**（@触发、插话四道闸、≤3 成员、各角色各自 system、群聊零计分）。

---

## 1. 增量范围（对照 PRD §1，v1.6 交付后修正）

| PRD ID | 需求 | 一句话承接 | v1.6 后现状 | 架构归属 |
|---|---|---|---|---|
| F3 | 时段仪式感 + 每日一句 | 早安/午后/晚安按日限次 + 语录库（**天气本期不做**） | greeting 6 时段已有；startup_greet 通道已备 | D-V17-02 / §3 / §5 |
| F4 | 贴身提醒 | NL 记日程 → 到点通知；规则优先 + LLM 兜底零编造 | TodoManager 无时间字段；intent 五态无 remind 态 | D-V17-03 / §3 / §5 |
| F5 | 关系阶段叙事 | 4 级阶段 + 特权表 + 升级播报恰一次 | intimacy 4 级 + _check_level_up 已有 | D-V17-04 / §3 / §5 |
| F7 | 女仆日记 | 次日补写昨日 + 角色口吻 + 翻阅导出 | 无日记基建；highlights.query_range / memory / page_memory_book 原料齐备 | D-V17-05 / §3 / §5 |
| F8/F9 | 人设工坊 | 开场白 + 示例对话 few-shot + 角色卡导入导出 | Role schema 无新字段；v1.5.1 对齐链为敏感区 | D-V17-07/08 / §3 / §5 |
| F10 | 多角色群聊 MVP | 2–3 角色 @指定 + 插话四道闸 | 无群聊会话模型；ChatMessage.metadata 可承载 speaker | D-V17-06 / §3 / §5 |

**范围澄清（PM 知情）**：
- **F1/F2 已随 v1.6.0 交付**（page_memory_book 记忆中心 / build_contentful_line 内容拼装），Q-C7/Q-C8 随之 closed——本期零重复工作。
- **F6 完整安慰模式不进本期设计范围**：v1.6 confide 态已交付"识别 + 当轮语气放缓注入"（INTENT_HINTS["confide"] + request_injections）；PRD F6 的增量面（连续 N 轮模式状态机 + 徽标 + 自动退出）顺延 v1.7.x/v1.8，若 PM 要求本期补齐，按 D-V16 请求级注入机制增一个模式状态机即可（预估 +1d，不阻塞主线）。
- **F3 天气接入本期不做**（PRD 裁剪顺序第一位；`weather.py` 不建、config 键不落，语录/仪式离线自洽）。

**Non-goals（沿用 PRD §1.4）**：语音通话闭环 / 桌宠深化 / AI 形象 / 云同步 / 情绪报表 / 群聊自由互辩与多轮接力 / 提醒跨设备。

---

## 2. 关键架构决策

### 决策表总览

| 编号 | 对应 | 结论（一句话） | 风险级 |
|---|---|---|---|
| D-V17-01 | Q-C 全系 | 11 项 Q-C 裁决定案（见 2.1 裁决表），不再抛回用户 | — |
| D-V17-02 | F3 | 仪式三通道沿用纪念日先例：启动早安（ritual.json 按日限次）/ scheduler tick 午后检查点（受 quiet、不走 cap）/ 关 app 托盘晚安（可关）；语录库 `quotations.py` + assets JSON datas | 低 |
| D-V17-03 | F4 | `reminders.py`：规则解析器（正则族，默认无时刻=09:00）+ ReminderScheduler（60s QTimer）；**确认句本地模板直出（零 LLM 零幻觉）**；LLM 兜底 = ApiWorker 新分支 `remind_parse`（单次 JSON 解析，失败诚实回退绝不编造）；到点通知复用 `tray_manager.notify_maid`（Windows 通知中心呈现），quiet 降级顺延 | 中 |
| D-V17-04 | F5 | intimacy 增阶段特权表 + notified_stage 持久化 + 升级播报走 proactive_ask（恰一次）；**Q-C9 裁决 = 砍掉"主动聊闲天话术变体"特权**（idle_hello 文案池零改动，A9 零回归面），信赖阶段特权 = system 语气生动化 + 晚安撒娇变体 + 日记口吻更亲密 | 低 |
| D-V17-05 | F7 | 新建根级 `diary.py`（纯 stdlib 存储 + 摘要组装）：次日启动后台补写昨日（Q-C6）、payload 只含摘要要点（R-I）、失败静默次日重试绝不占位造假；默认开（Q-C2）、设置页可关；翻阅 = page_memory_book 第 4 个 Tab「她的日记」+ Markdown 导出 | 中 |
| D-V17-06 | F10 | 群聊 = **显示会话层功能，不触碰 session.history 单角色对齐链**（v1.5.1 零回归的关键）；会话 metadata 存 type/members/turn_order；发言 = 请求时按"历史角色改写"组装（他人 assistant 消息改写为 user 前缀「【名字】：」），串行单 ApiWorker；插话四道闸默认关；两步切片交付 | **高** |
| D-V17-07 | F8 | Role schema 增 `opening_lines`(list≤3)/`example_dialogues`(list≤5 组，每组含 enabled)——from_dict .get 默认零迁移；示例对话块拼进 `build_role_system_prompt`（page_role 内聚，随 gui_role_prompt 当轮生效，不进历史） | 中 |
| D-V17-08 | F8 | 开场白注入收敛单点 helper `inject_opening_line`（切角色后 & 新建会话后两调用点，均在 v1.5.1 对齐链**之后**执行）；入 LLM 历史 + 显示会话同步存（防重启分叉） | 中 |
| D-V17-09 | F8/F9 | 新建 `gui/role_card.py`（纯逻辑导出/导入/校验）；导出只含人设字段（R-I）；导入重名默认"另存新角色（导入）"，F9 提供覆盖导入选择 | 低 |
| D-V17-10 | F4/F3 存储 | 提醒复用 todos.json（条目可选字段向后兼容）；仪式/语录状态 ritual.json 独立文件——**不新增 reminders.json**（避免待办与提醒双源分裂） | 低 |

### 2.1 Q-C1~C11 裁决表（D-V17 裁决，PRD §11 全项闭环）

| # | 裁决 | 落点 |
|---|---|---|
| Q-C1 | **采纳 MVP 口径**：@指定回复 + 无@默认轮转第一位（GuiConfig `group_no_at_policy` 可切"全沉默"）+ 插话默认关四道闸 | D-V17-06 |
| Q-C2 | **日记默认开启**，设置页「陪伴」区开关可一键关；无 key/demo 自动停用并留一次性说明 | D-V17-05 |
| Q-C3 | **默认时刻 09:00**（"提醒我续费"类无明确时间句）；常量 `_DEFAULT_REMIND_TIME = "09:00"` 可调不入 UI | D-V17-03 |
| Q-C4 | **到点 = 系统通知**：复用 `tray_manager.notify_maid("码铃提醒", text)`（Windows 11 通知中心原生呈现，零新增依赖）；quiet 时段降级为不弹通知、气泡顺延补看 | D-V17-03 |
| Q-C5 | **保留关 app 深夜托盘晚安气泡**（GuiConfig `ritual_goodnight` 默认开，可关）；挂 quit 编舞处，深夜时段（23:00–5:00）且当日未发过才发 | D-V17-02 |
| Q-C6 | **次日启动补写昨日日记**（后台线程不阻塞启动）；当日退出生成不做 | D-V17-05 |
| Q-C7 | **已在 v1.6 落地关闭**（build_contentful_line ①话题②情绪③待办优先级 + is_source_muted 可单独静默待办维度） | v1.6 交付 |
| Q-C8 | **已在 v1.6 落地关闭**（emotions 上限 200，用户裁决版本） | v1.6 交付 |
| Q-C9 | **砍掉"主动聊闲天话术变体"**：信赖阶段特权 = system 语气生动化（build_stage_system_prompt）+ 晚安撒娇式变体 + 日记口吻更亲密；idle_hello 文案池零改动（R-D：不为特权碰 A9 回归面） | D-V17-04 |
| Q-C10 | **首版轻量校验**：体积 ≤1MB + 字段白名单 + 类型守卫；导入成功后编辑面板可查看全部内容；预览确认页列 v1.7.x | D-V17-09 |
| Q-C11 | **预授权 F10 延后**：切片（F10a）2 人日技术验证不通过即整项顺延 v1.7.x，不影响 v1.7 发布完整性 | D-V17-06 |

---

### 2.2 D-V17-02 · 时段仪式感与每日一句（F3）

**落法**：

1. **新建根级 `quotations.py`（纯 stdlib）**：语录库 `gui/assets/quotations.json`（自创 ≥200 条，主题 `morning/afternoon/night/all` 四池，R-H 全自创零引用）+ `pick_quote(date_str, stage, slot) -> str`——当日确定（以 date+slot 做稳定哈希选择，24h 不重复）、按阶段加权（信赖/亲近 → 亲昵子池优先）。加载守卫同 intent_words.json 模式（内置小池兜底 + get_resource_path 打包态兜底）。
2. **`~/.maid_coder/ritual.json`**：`{"date": "YYYY-MM-DD", "given": ["morning","afternoon","goodnight"], "quote_morning": "...", "quote_afternoon": "..."}`——按日重置（date != today 即重置），原子写。
3. **greeting.py 增纯函数**：`build_morning_ritual(quote, nickname, stage) -> str` / `build_afternoon_line(quote)` / `build_goodnight_line(stage)`——既有 `_TIME_PERIODS` 零改动；晚安按阶段取撒娇/关切变体（F5 联动）。
4. **三通道接线**：
   - **早安**：`maybe_startup_greet`（v1.6 已有）内部增量——时段 ∈ 清晨/上午 且 ritual 当日未给 morning → 问候升级为"早安编排（时段问候 + 动作 + 每日一句）"并记 ritual.json；其余时段走 v1.6 内容拼装逻辑不变。受既有四重闸约束（startup_greet 本就占 cap/cooldown）。
   - **午后**：scheduler `_on_tick` 增一个每日一次检查点 `maybe_afternoon_ritual()`（仿 anniversary 模式：14:00–17:00 ∧ 当日未给 ∧ 非 quiet ∧ 非忙）→ 一句轻量午后小句走 proactive_ask（scene="afternoon_ritual"，subject=""，**不走 cap/cooldown**——纪念日先例，但受 quiet/demo/忙约束）。一日两条仪式句上限由 ritual.json 天然保证。
   - **晚安**：gui/main.py quit 编舞处（保存退出前）——深夜时段 ∧ ritual 未给 goodnight ∧ `ritual_goodnight` 开 → `tray_manager.notify_maid` 一句晚安（一次性，无气泡入会话——退出时序不适合写会话）。深夜对话尾部轻附晚安关切：ChatService 请求级注入（深夜时段自动加一句提示"夜深了，回复可轻附休息关切"，复用 request_injections，零新机制）。
5. **红线**：语录/仪式无"第 N 天"、无签到、无连续语义（R-A）；无天气残缺态（本期整段不做）。

**风险点**：maybe_startup_greet 已有内容拼装逻辑，早安仪式叠加需保持"内容句优先于仪式句"或二者合一——**裁决：早安仪式与内容句合并为一条编排（问候 + 仪式句/内容句二选一，仪式句优先级低于话题续接）**，防问候过长。**降级**：午后检查点若与 A9 拥挤，降级为"仅首页可见不给气泡"。

---

### 2.3 D-V17-03 · 贴身提醒（F4）

**现状核实**：TodoManager 条目 `{text, done, created_at}` 无时间字段；`tray_manager.notify_maid(title, text)`（:150）现成；ChatService 无 remind 相关分支；`gui/intent.py` 五态无提醒态。

**落法**：

1. **`reminders.py`（根级，解析器纯 stdlib + 调度器薄 Qt）**：
   - `parse_when(text) -> Optional[dict]`（`{"due_at": ISO, "remind_text": str, "confidence": "high|low"}`）：正则族覆盖——相对（"N分钟后/N小时后"）、今日/明日/后天 + 时段（上午/下午/晚上 N点[半/N分]）、"周X[下午] N点"、'N月N日 N点'、裸"N点"；下午/晚上 12h→24h 换算；**无任何时间线索时返回 due_at=今日 09:00（Q-C3）+ confidence=low**；跨周"周X"取未来最近一个。
   - `parse_when` 全部命中即返回（规则层离线可用）；文本主体剥离"提醒我/叫我/别让我忘"等前缀得到 remind_text。
2. **TodoManager 增量（managers.py，R-D 向后兼容）**：条目可选字段 `due_at`(ISO)/`remind_text`/`notified`(bool)；旧条目无字段 = 普通待办零迁移。新方法：`add_reminder(remind_text, due_at) -> int`（返回 index）/ `due_items(now) -> List[(index, dict)]`（due_at≤now ∧ 未 notified ∧ 未 done）/ `mark_notified(index)` / `cancel_reminder(index)`（删除条目）。
3. **对话录入挂接（ChatService.send_message 入口、intent 路由之前）**：
   - 提醒意图词命中（"提醒我/叫我/别让我忘/记得提醒"独立词表，reminders.py 内置 + 可 JSON 扩展）且 `task_type=="chat"` 且非 Agent/demo → 进提醒分支：
     - 规则解析 confidence=high → **确认句本地模板直出**："好的，{周X HH:MM} 我会提醒你「{text}」📝"（确定性回复，经 screen_bubble 式独立通道落 assistant 气泡，**不调 LLM、不入用户发送队列**——零成本零幻觉）+ 气泡下挂确认卡小组件（时间 + 内容 + 「取消」按钮，5 分钟内可见，超时自动隐藏；取消 = `cancel_reminder`）。
     - 规则解析失败/仅 low（复杂从句）→ **LLM 兜底**：入队 `task_type="remind_parse"` 专用分支——ApiWorker 单次 `api.chat`（temperature=0, max_tokens=100，提示词要求输出 `{"datetime": "YYYY-MM-DD HH:MM", "text": "..."}` JSON）→ 解析成功登记 + 确认句；解析失败/JSON 不合法 → 确定性诚实回复："码铃没听懂时间呢，主人可以直接说'明天9点提醒我xxx'~"（**绝不编造时间**——自动化断言：失败路径零 due_at 写入）。用户消息本身仍照常入会话（上下文完整）。
   - 对话中列览："今天有什么安排/提醒" 词命中 → 本地模板列出今日有 due_at 条目（时间排序，零 LLM）。
4. **触发调度**：`ReminderScheduler(QObject)` 挂 gui/main.py 装配（60s QTimer）→ `due_items(now)` 扫描 → 每条：非 quiet → `notify_maid("码铃提醒", remind_text)`（Windows 通知中心）+ ChatService 确定性气泡（"主人，到点的提醒来啦：{text}"，scene="reminder"）；quiet 时段 → 只标记 `notified=False, quiet_pending=True`，quiet 结束后首个 tick 补气泡**不弹通知**（Q-C4 降级口径）；触发后 `mark_notified`。**独立通道不占 A9 cap**（番茄钟先例，不走 proactive 四重闸）。
5. **补送**：启动时扫描 `due_at < now ∧ not notified` → 补送一次，文案加"（你不在时到点的）"，仅一次（notified 标记即防重）。
6. **todo_dialog.py 增强**：有 due_at 条目显示"⏰ HH:MM"角标；右键改期（QDateTimeEdit）/取消提醒。

**风险点**：时间解析长尾（"大后天""下周一"）——v1.7 规则层覆盖 PRD 列出的六类 + 兜底诚实话术，长尾靠 LLM 分支；**通知权限**：QSystemTrayIcon.showMessage 在 Win10/11 即通知中心通知（无需新依赖）；focus assist 静音属系统层，文档如实标注。**降级**：remind_parse 分支若排期紧 → 首版只上规则层 + 失败诚实话术（PRD 验收 2 的"复杂句成功解析"降级为"如实说没听懂"，PM 知情）。

---

### 2.4 D-V17-04 · 关系阶段叙事（F5）

**现状核实**：intimacy.py `_INTIMACY_LEVELS` 4 级（初识 0–9 / 熟悉 10–49 / 亲近 50–149 / 信赖 150+，含 action_limit）+ `_check_level_up` 文案（:95，无数值 R-A 判例）+ `build_intimacy_prompt`（:225）；GUI 计分链 = ChatService._on_stream_finished → collab.bump_intimacy。

**落法**：

1. **intimacy.py 增量**：
   - `_STAGE_PRIVILEGES`（按 level 键）：`address_style`（初识"您"/其余"你"——build_intimacy_prompt 既有语气段落扩展引用）、`goodnight_variant`（亲近+ 撒娇式晚安，F3 消费）、`diary_tone`（信赖 日记口吻更亲密，F7 消费）、`quote_pool_weight`（熟悉+ 亲昵语录池加权，F3 消费）。**无"闲聊话术变体"键**（Q-C9 裁决）。
   - `build_intimacy_prompt` 内部扩展为阶段化注入（称呼 + 语气 + 特权说明），**签名不变**——session._build_system_prompt 零改动，切角色/升级后当轮生效（走既有 _update_system）。
   - 持久化 `notified_stage`（intimacy.json 增字段，_merge_defaults 兜底默认 -1）。
2. **升级播报恰一次**：`add_interaction` 返回 level_msg 既有通道保留（GUI 有无处呈现均可）；**新增权威播报点**——ChatService._on_stream_finished 的 bump_intimacy 后：比较 `tracker.level > tracker.notified_stage` → 组播报句（"主人，码铃感觉我们更亲近了——现在是「{阶段名}」的关系啦 💕"）→ `proactive_ask(text, scene="stage_up", subject="")`（无 echo、不计分、不触发自续命，A9 机制零回归——播报是用户交互的即时反馈，不走四重闸）→ 成功投递后 `tracker.notified_stage = level` 落盘（重启/重开不重播，断言）。
3. **page_home 关系称谓**：既有关系文案读 `relation_stage_name()` 改阶段化措辞（"和主人的故事正在『熟悉』篇章"）——只换词不换机制。
4. **红线**：全 UI 无分数/Lv/进度/差 N 分（R-A 硬线，播报句模板内无任何数值位）。

**风险点**：bump_intimacy 在群聊路径不调用（D-V17-06 隔离）→ 群聊零计分自动满足 R-J⑤。**降级**：notified_stage 写盘失败 → 播报退化为内存标记（进程内恰一次），下次重启可能重播一次（诚实降级，日志记录）。

---

### 2.5 D-V17-05 · 女仆日记（F7）

**落法**：

1. **新建根级 `diary.py`（纯 stdlib 存储 + 摘要组装；LLM 调用由 GUI 层执行——保持根级零网络依赖可单测）**：
   - `DiaryManager(filepath)`：`~/.maid_coder/diaries.json`，`{"schema_version":1, "entries":[{"date","role_name","mood","content","generated_at"}]}`，**上限 365 篇滚动淘汰**（design-v13 highlights 范式）。
   - `build_diary_payload(memory_mgr, highlights_mgr, companion, role_name, date) -> dict`：摘要要点 = 当日新增高光条目（`highlights.query_range(date, date)` v1.6 已有）+ 话题变化（active 新增/完成）+ 情绪记录（emotions 当日）+ 消息量档位词 + 偏好变化——**只含要点不含对话原文**（R-I 硬线，payload 结构化字段进断言）。
   - `should_write(date) -> bool`（昨日有内容且未写过）。
2. **生成链（gui/main.py 启动检查点）**：装配完成后（weekly 同款挂载模式）→ 后台 QThread：`should_write` ∧ `diary_enabled` ∧ 非 demo → api.chat 单次调用（提示词："以 {角色名} 第一人称写 100–200 字日记" + payload JSON）→ 成功 `add_entry`；失败静默（次日 should_write 仍 True 自然重试），**绝不落占位假日记**。当前角色名取 app_ctx 默认角色（RoleManager.default_role）。
3. **翻阅与导出**：page_memory_book 增第 4 个 Tab「她的日记」——按月分组时间倒序 + 单篇卡（日期 + mood 小表情 + 正文）+ 「导出 Markdown」（单篇/全部，QFileDialog 自选目录，纯 stdlib 拼接 utf-8）。
4. **开关**：GuiConfig `diary_enabled`（默认 True，Q-C2）+ 设置页「陪伴」区；无 key → 启动检查点静默跳过 + 首次给一次性说明气泡。
5. **红线**：无"连续写日记 N 天"（R-A）；token 消耗经既有首页 Token 卡自然累计（add_usage 既有链，api.chat 返回 usage 手动累加）。

**风险点**：生成质量依赖模型（弱模型日记流水账）——验收为抽样人工评审，不阻塞交付；生成线程与主窗退出竞争 → 守护线程 daemon + 退出不等待（丢了次日重试即可，无一致性问题）。**降级**：Tab 排期紧 → 先只落 diary.json + 导出脚本，翻阅页 v1.7.x 补（PM 知情）。

---

### 2.6 D-V17-06 · 多角色群聊 MVP（F10，全池最重）

**核心裁决：群聊 = 显示会话层功能，完全绕开 session（CLI ChatSession）与 v1.5.1 对齐链。**

**现状核实**：显示会话 `ChatSession(gui/models)` 已有 `metadata: dict` 自由字段 + `ChatMessage.metadata`（:21）可承载 speaker；SessionManager 会话文件 `~/.maid_coder/sessions/{id}.json` + metadata 落盘齐备；ChatService 单角色对齐链（notify_role_switch/replace_history）是 v1.5.1 敏感区——**群聊不写 session.history、不触发对齐链、不写亲密度**。

**数据结构**：

- 群聊会话：`display_session.metadata = {"type": "group", "members": [role_id ×2–3], "turn_order": [role_id…], "no_at_policy": "rotate"|"silent", "chatter": {"enabled": false, "last_at": 0, "date": "", "count_today": 0}}`（旧会话无 type = "single" 零影响）。
- 群聊消息：`ChatMessage.metadata["speaker_id"] = role_id`（assistant 发言归属）；user 消息不变。

**发言循环（串行，单 ApiWorker 复用）**：

1. **@解析**：用户消息以 `@` 开头或含 `@名字`（正则 `@([\u4e00-\u9fa5A-Za-z0-9_·]+)`，对 members 角色名**精确**匹配，防"@一下"误命中）；输入框 QCompleter @ 补全（成员名前缀触发）。命中 → 目标角色；未命中 → `no_at_policy`：rotate（默认，Q-C1）= turn_order 轮转第一位（发言后移到队尾）；silent = 全员沉默等待 @（消息照常入会话，零回复——诚实呈现"等你点名"）。
2. **请求组装（历史角色改写，关键设计）**：发言 = 一次独立 LLM 调用，messages 即时从显示会话组装、用后即弃：
   - system = 发言角色 `build_role_system_prompt` + 群聊语境段（"你正在与主人及 {其他成员名列表} 的群聊中；【名字】：前缀的消息是其他成员的发言，主人是没有前缀的消息；只以你自己的人设发言，不代替他人"）。
   - 历史改写：遍历显示会话消息——发言角色**自己的**历史 assistant 消息保持 `assistant` role；**其他成员**的 assistant 消息改写为 `user` role 且内容前缀 `【{名字}】：`；user 消息原样 `user`。→ 保留对话结构、无角色错位（标准 multi-party 建模），system 永远唯一（R-J④）。
   - 上下文控制：群聊历史超 60 条时截断保留最近（复用条数常量，群聊会话不做 auto_summary——MVP 边界）。
3. **执行**：组装后交既有 ApiWorker 普通流式分支（task_type="chat"，messages 为定制副本——`_launch_worker` 增可选 `custom_messages` 覆盖 session.history 组装路径，**默认 None 零回归**）；流式完成 → 写显示会话（speaker_id）+ 气泡渲染（speaker 头像 + 名字标签，复用 Bug4 角色头像缓存机制）；**不写 session.history、不 bump_intimacy、不 trigger intimacy_changed**。
4. **主动插话四道闸（R-J②，全过才插话）**：①开关 `chatter.enabled`（默认关，群聊会话设置或全局 GuiConfig）；②每条用户消息后最多 1 个未指定角色插话；③全局冷却 ≥3min（`chatter.last_at` epoch，持久在 session.metadata）；④每日上限 5（`chatter.date/count_today` 按日重置）。插话目标 = turn_order 中未发言的下一成员；插话内容触发 = 无 LLM 判定（MVP：用户消息后固定概率/直接按闸放行下一位）——**裁决：插话 = 轮转下一位基于用户消息的短回应，无兴趣判定（成本与失控双收窄）**。四道闸全部自动化断言（P1-2 式单测）。
5. **UI**：session_tabs 群会话"👥"角标；message_bubble 群聊 assistant 气泡显示 `【{角色名}】` 名字标签 + 角色头像（avatar 路径从 RoleManager 读）；新建群聊入口 = session_tabs 右键/新会话菜单"新建群聊" → 成员选择对话框（角色多选 ≤3）。
6. **亲密度隔离（R-J⑤）**：群聊发言链路零计分——`custom_messages` 路径跳过 bump_intimacy/intimacy_changed/memory extract（群聊对话不进记忆提取，防多角色污染偏好）——单一布尔守卫实现。

**风险点**：token 成本 ×N（每次发言独立调用）——首页 Token 卡如实累计（验收 5）；插话体验生硬（无兴趣判定）——MVP 接受，v1.7.x 演进为 LLM 兴趣判定；**长历史多角色改写的 token 膨胀**——60 条截断 + 名字前缀开销可控。

**切片建议（两步走，Q-C11 预授权）**：
- **F10a 切片（≈2 人日）= 会话模型 + @指定发言 + 历史改写 + speaker 渲染**：技术验证核心（改写正确性/串味/v1.5.1 零回归）——切片验收不过 → 整项顺延 v1.7.x，已产出的会话模型代码保留不发布。
- **F10b 完整（≈1.5–3 人日）= 插话四道闸 + @补全 + 群标签/设置 + 不计分断言 + 群聊历史截断**。

---

### 2.7 D-V17-07/08 · 人设工坊（F8/F9）

**现状核实**：`Role`（page_role.py:336-390）字段 id/name/description/system_prompt/is_default/personality{3 滑块}/intimacy/created_at/avatar/current_expression，from_dict `.get` 默认（向后兼容范式现成）；角色 system 注入链 = `build_role_system_prompt(system_prompt, personality)` → `set_gui_role_prompt`（:296-315，覆盖式、当轮生效）；切角色边界 = `notify_role_switch`（page_role.py:1038）；会话↔LLM 历史对齐 = `replace_history`（v1.5.1）。

**落法**：

1. **Role schema 增量（D-V17-07）**：
   - `opening_lines: List[str]`（≤3 套，F9 轮换随机取一；单字符串旧数据/手填兼容——setter 收敛为 list）；
   - `example_dialogues: List[dict]`（每组 `{"user": str, "assistant": str, "enabled": bool}`，≤5 组，enabled 为 F9 组开关，默认 True）。
   - `from_dict`/`to_dict` 增 `.get` 默认（空 list）——旧角色 JSON 零迁移加载。
2. **示例对话注入 = system 尾部追加块**（PRD 口径，不进 messages 历史）：拼进 `build_role_system_prompt`（page_role 模块函数）——"【对话风格示例】（仅供语气与相处方式参考，不要在对话中复述这些示例）：\n用户：…\n{角色名}：…（×N，仅 enabled 组）"。随 gui_role_prompt 覆盖链当轮生效，与表情指南单点注入同模式（session._build_system_prompt 末尾已有先例），**零触碰对齐链**。token 控制：示例总长 ≤2000 字硬截断。
3. **开场白注入（D-V17-08，敏感区）**：
   - 新 helper `inject_opening_line(app_ctx, session, role)`（page_role.py 或 gui/opening.py）：`opening = random.choice([l for l in role.opening_lines if l.strip()] or [])`；空 → 既有默认欢迎语零回归；非空 → `session.add_message("assistant", opening)`（经 gui_session.message_added 单入口渲染气泡，expr_markup 表情标记照常解析）+ **显示会话同步 append**（同 content 同序——防重启后显示/LLM 两套历史分叉，v1.5.1 对齐语义保持）。
   - **调用点仅两处、且都在对齐动作之后**：①`_apply_role` 切角色成功后（notify_role_switch 之后追加）；②新建会话（replace_history 重建之后）。**严禁**在 sync_role_override_to_session 内注入（该函数启动时也跑，会重复开场白）。
   - 重启恢复：显示会话 JSON 已含开场白 assistant 消息 → 会话切换 replace_history 重建时自然带回 LLM 历史（无需再注入——**注入点带幂等守卫**：显示会话末尾已是同内容 assistant 则跳过）。
4. **编辑面板**：page_role 编辑区增「开场白」多行输入（3 套 Tab 或单框多段——**裁决：单框存储、`---` 分行解析为多套**，UI 最简）+「示例对话」双列编辑（QPlainTextEdit × 2 × 5 组 + 勾选启用）+ 保存走既有 `_save_role_fields`。
5. **导入导出（D-V17-09）**：新建 `gui/role_card.py`（纯逻辑）：`export_card(role) -> dict`（只含 name/description/system_prompt/personality/opening_lines/example_dialogues/current_expression + schema_version + 导出时间——**不含 avatar 路径/记忆/亲密度/对话历史/角色 id**，R-I）；`parse_card(data, size_limit=1MB) -> Role`（字段白名单 + 类型守卫 + 超限拒绝）。page_role 角色右键菜单/编辑面板增「📤 导出角色卡」「📥 导入角色卡」（QFileDialog `.malingcard.json`）；预设角色导出前弹"这是预设角色的副本"提示；导入重名默认另存"（导入）"后缀，F9 提供覆盖导入选择（QMessageBox 三态）。
6. **F9 增强随 F8 同批**：开场白轮换（choice 已含）/示例组 enabled 开关/覆盖导入路径。

**风险点**：开场白在切角色时与 notify_role_switch 边界消息的顺序——开场白 assistant 消息在边界 system 之后追加，语义正确（边界消息管人设延续、开场白是角色开口）；**幂等守卫必须先行**（防启动 sync + 手动切换双注入）。**降级**：示例对话若与某些角色卡 system 冲突 → 单角色级"启用示例对话"总开关（默认开）。

---

### 2.8 D-V17-10 · 存储面汇总裁决

- 提醒 → **todos.json 扩展**（不建 reminders.json，待办/提醒单源，todo_dialog 一处呈现）；ritual/quote 状态 → ritual.json；日记 → diaries.json；群聊 → sessions/*.json metadata 扩展；阶段 → intimacy.json 扩展；角色 → roles/*.json 扩展。**零新 JSON 除 diaries/ritual 外**，schema 全部向后兼容。

---

## 3. 模块 / 文件清单

### 3.1 新增文件

| 路径 | 一句话职责 | 对应需求 | 进 v1.7 承诺 |
|---|---|---|---|
| `quotations.py`（根级，纯 stdlib） | 语录库加载/按日去重抽取/阶段加权 | F3 | 是 |
| `gui/assets/quotations.json` | 自创语录库 ≥200 条（4 池，datas 进包） | F3 | 是 |
| `reminders.py`（根级；解析纯 stdlib + Scheduler 薄 Qt） | parse_when 规则解析 + ReminderScheduler 60s 扫描/quiet 顺延/补送 + 提醒意图词表 | F4 | 是 |
| `diary.py`（根级，纯 stdlib） | DiaryManager（365 篇滚动）+ build_diary_payload 摘要组装 + should_write | F7 | 是 |
| `gui/role_card.py`（纯逻辑） | 角色卡导出/导入/校验（白名单 + 1MB 上限） | F8/F9 | 是 |
| `gui/widgets/reminder_confirm_card.py` | 确认卡小组件（时间+内容+5min 可撤销） | F4 | 是 |
| `gui/widgets/group_member_dialog.py` | 新建群聊成员选择对话框（≤3） | F10 | 是（随 F10a） |
| `tests/test_v17_*.py` 系列 | 各模块单测 + F10 四道闸断言 + 日记 R-I payload 断言 | 全部 | 是 |

### 3.2 修改文件

| 路径 | 改动点 | 风险级 |
|---|---|---|
| `greeting.py` | build_morning_ritual / build_afternoon_line / build_goodnight_line 纯函数（_TIME_PERIODS 不动） | 低 |
| `gui/proactive_scheduler.py` | `_on_tick` 增 maybe_afternoon_ritual 检查点 + maybe_startup_greet 内早安编排分支 | 中（加方法不动闸） |
| `gui/chat_service.py` | 提醒意图拦截分支（确认句直出/remind_parse 入队/列览）+ ApiWorker 增 remind_parse 分支 + `_launch_worker` 增 `custom_messages` 可选参 + stage_up 播报接线（bump 后比较 notified_stage） + 深夜 request_injection | 中（发送链汇交点） |
| `managers.py` | TodoManager 增量（due_at/remind_text/notified + add_reminder/due_items/mark_notified/cancel_reminder） | 低 |
| `intimacy.py` | _STAGE_PRIVILEGES + build_intimacy_prompt 阶段化扩展（签名不变）+ notified_stage 持久化 | 低 |
| `gui/tray_manager.py` | 零改动（notify_maid 复用）；gui/main.py quit 编舞处挂晚安检查 | 低 |
| `diary 生成线程挂载 → gui/main.py` | 启动检查点（QThread daemon）+ ReminderScheduler 装配 + ritual.json 读写助手 | 中（装配汇交点） |
| `gui/pages/page_home.py` | 启动早安编排消费 + 关系称谓阶段化文案 | 低 |
| `gui/pages/page_memory_book.py` | 第 4 Tab「她的日记」（列表 + 详情 + 导出） | 中 |
| `gui/pages/page_role.py` | Role schema 增量 + build_role_system_prompt 示例块 + 开场白/示例编辑区 + 导入导出按钮 + inject_opening_line helper + _apply_role/新会话两调用点 | **中高（敏感区）** |
| `gui/widgets/chat_panel.py` | 确认卡挂载 + 群聊气泡 speaker 渲染分支 + @补全（QCompleter）+ 新建群聊入口 | 中（汇交点） |
| `gui/widgets/session_tabs.py` | 群会话"👥"角标 + 新建群聊菜单项 | 低 |
| `gui/widgets/message_bubble.py` | metadata.speaker_id → 名字标签 + 角色头像 | 低~中 |
| `gui/models.py` | 零改动（metadata 自由字段已够）；如需 speaker 便捷属性加只读 property | 低 |
| `gui/config.py` | GuiConfig 增 `diary_enabled`(True)/`ritual_goodnight`(True)/`group_no_at_policy`("rotate")/`group_chatter_enabled`(False) | 低 |
| `gui/pages/page_settings.py` | 「陪伴」区（日记开关/晚安开关）+「群聊」区（插话开关/无@策略） | 低 |
| `maid_coder_gui.spec` | hiddenimports 补 `quotations`/`reminders`/`diary`/`gui.role_card`/`gui.widgets.reminder_confirm_card`/`gui.widgets.group_member_dialog`；datas 补 `gui/assets/quotations.json`（intent_words.json 同目录模式） | 低 |
| `CHANGELOG.md`/`version.json`/`README.md` | v1.7.0 收口（R-K：如实标注验证态，F10 若切片通过才写"已支持"） | 低 |

---

## 4. 数据结构

### 4.1 todos.json（扩展，向后兼容）

```jsonc
[
  {"text": "…", "done": false, "created_at": "ISO",              // 旧条目零迁移
   "due_at": "2026-09-12T15:00", "remind_text": "开会",           // 新增可选：有 due_at = 提醒
   "notified": false, "quiet_pending": false}                     // 新增可选：触发记账
]
```

### 4.2 ritual.json（新文件，按日重置）

```jsonc
{"date": "2026-09-09", "given": ["morning"],
 "quote_morning": "…", "quote_afternoon": null}
```

### 4.3 diaries.json（新文件，365 篇滚动）

```jsonc
{"schema_version": 1,
 "entries": [{"date": "2026-09-08", "role_name": "温柔女仆", "mood": "happy",
              "content": "100–200 字日记正文…", "generated_at": "ISO"}]}
```

### 4.4 intimacy.json（扩展）

```jsonc
{"score": 62, "…既有键不动…", "notified_stage": 2}   // 已播报到的阶段（-1 = 从未播报）
```

### 4.5 角色 JSON（roles/*.json，扩展）与角色卡（.malingcard.json）

```jsonc
// roles/*.json 增量字段（缺省 []）
{"…既有字段…",
 "opening_lines": ["开场白第一套", "第二套", "第三套"],
 "example_dialogues": [{"user": "…", "assistant": "…", "enabled": true}]}
// .malingcard.json = 上述人设字段子集 + {"card_type":"malingcard","schema_version":1,"exported_at":"ISO"}
// 绝不含：avatar 路径 / 角色id / 记忆 / 亲密度 / 对话历史（R-I）
```

### 4.6 群聊会话（sessions/*.json metadata 扩展）

```jsonc
// ChatSession.metadata（旧会话无 type = single）
{"type": "group",
 "members": ["role_a1b2", "role_c3d4", "role_e5f6"],       // ≤3（R-J③）
 "turn_order": ["role_a1b2", "role_c3d4"],                  // 轮转序，发言后移队尾
 "no_at_policy": "rotate",                                  // rotate | silent（Q-C1）
 "chatter": {"enabled": false, "last_at": 0, "date": "2026-09-09", "count_today": 0}}
// 群聊 assistant 消息：ChatMessage.metadata {"speaker_id": "role_a1b2"}
```

### 4.7 GuiConfig（gui_config.json 增量）

| 键 | 默认 | 语义 |
|---|---|---|
| `diary_enabled` | true | 女仆日记开关（Q-C2） |
| `ritual_goodnight` | true | 深夜关 app 晚安托盘气泡（Q-C5） |
| `group_no_at_policy` | "rotate" | 群聊无@策略（rotate/silent，Q-C1；会话级可覆盖） |
| `group_chatter_enabled` | false | 群聊插话全局默认（R-J② 默认关） |

---

## 5. 任务分解列表（分四批；特性任务 ≈ 11–16.5 人日 + 公共项 1.5 人日）

### 5.1 依赖与批次总览

- **第一批（轻，先行）= F3 + F5**：F5 极轻且 F3 消费其阶段表（语录加权/晚安变体）——F5a 先合、F3 后合。
- **第二批 = F4 + F7（可并行）**：F4 独立性最强；F7 依赖 page_memory_book（v1.6 已在）。
- **第三批 = F8/F9（敏感区，专人串行）**：page_role 单人负责，避开其他批次的 chat_panel 时段。
- **第四批 = F10**：切片 F10a 技术验证 → 通过才 F10b；不通过按 Q-C11 顺延。
- 汇交点：`gui/chat_service.py`（F4 拦截 + F5 播报 + F10 custom_messages 三方触碰——按任务顺序串行合入）；`chat_panel.py`（F4 确认卡 + F10 渲染）。

### 5.2 任务表

| 任务 ID | 任务 | 依赖 | 产出文件 | 估算 |
|---|---|---|---|---|
| V17-0 | 基线接线：spec hiddenimports/datas 一次收录 + GuiConfig 四新键 + 设置页区骨架 + quotations.json 语录库编写（自创 200 条） | — | spec、config.py、page_settings.py、quotations.json | 0.5d |
| F5 | 阶段叙事：_STAGE_PRIVILEGES + build_intimacy_prompt 阶段化 + notified_stage 持久化 + stage_up 播报接线 + page_home 阶段化称谓 + 恰一次断言 | V17-0 | intimacy.py、chat_service.py、page_home.py、tests | 1–1.5d |
| F3 | 时段仪式：quotations.py + ritual.json + greeting 三纯函数 + 早安编排（startup_greet 分支）+ 午后检查点 + 晚安托盘 + 深夜注入 + 按日限次断言 | F5（阶段表） | quotations.py、greeting.py、proactive_scheduler.py、gui/main.py、page_home.py、tests | 1–1.5d |
| F4a | 提醒解析与存储：parse_when 规则族 + TodoManager 增量 + 提醒意图词表 + 规则层单测（PRD 验收 1 用例全绿） | V17-0 | reminders.py、managers.py、tests | 1d |
| F4b | 触发链：ReminderScheduler + notify_maid 通知 + reminder scene 气泡 + quiet 顺延 + 启动补送 + 确认卡组件与挂载 + todo_dialog 角标/改期/取消 | F4a | reminders.py、gui/main.py、chat_service.py、reminder_confirm_card.py、todo_dialog.py、tests | 1–1.5d |
| F4c | LLM 兜底：ApiWorker remind_parse 分支 + JSON 解析守卫 + 失败诚实话术（零编造断言） | F4a | chat_service.py、tests | 0.5d |
| F7a | 日记生成：diary.py（DiaryManager/payload/should_write）+ 启动后台检查点 + 开关 + R-I payload 断言 + 失败不造假断言 | V17-0 | diary.py、gui/main.py、config.py、tests | 1d |
| F7b | 翻阅导出：page_memory_book 第 4 Tab + 月分组/详情卡 + Markdown 导出 | F7a | page_memory_book.py、tests | 0.5–1d |
| F8a | 角色工坊数据与注入：Role schema 增量 + build_role_system_prompt 示例块（≤2000 字截断）+ 编辑面板开场白/示例区 | V17-0 | page_role.py、tests | 1d |
| F8b | 开场白注入链（敏感区）：inject_opening_line + 两调用点 + 幂等守卫 + 显示会话同步 + v1.5.1 对齐链全量回归（切角色×新会话×重启矩阵） | F8a | page_role.py、chat_panel.py、tests | 0.5–1d |
| F8c | 角色卡：gui/role_card.py 导出/导入/校验 + page_role 按钮 + 重名策略 + 预设副本提示 + 字段逐项断言 | F8a | gui/role_card.py、page_role.py、tests | 0.5d |
| F9 | 工坊增强随 F8：开场白多套轮换 / 示例组 enabled 开关 / 覆盖导入三态 | F8c | page_role.py、gui/role_card.py | 0.5d |
| F10a | **群聊切片**：会话 metadata 模型 + @解析 + 历史角色改写组装 + custom_messages 路径 + speaker 气泡渲染 + 串味/v1.5.1 零回归验证（**过闸决策点**） | V17-0 | models 无改、chat_service.py、chat_panel.py、message_bubble.py、session_tabs.py、group_member_dialog.py、tests | 2d |
| F10b | 群聊完整：轮转/沉默策略 + 插话四道闸（断言）+ @补全 + 群标签 + 零计分/零记忆提取守卫 + 历史 60 条截断 | F10a 通过 | chat_service.py、chat_panel.py、session_tabs.py、page_settings.py、tests | 1.5–3d |
| V17-X | 收口：py_compile + 全量 pytest 回归（v1.6 套件 + 新增）+ R-A 扫描（词表扩：心情曲线/情绪报告/记忆成就/日记打卡）+ 打包核对（R-K：文档↔dist、F10 如实标注）+ 升版 1.7.0 | 全部 | version.json、CHANGELOG.md、README.md | 1d |

**特性合计 ≈ 12–16.5 人日；与 PRD 全量 14.5–21.5 的差值 = F1/F2（v1.6 已交付 2.5–3.5）+ F6（范围澄清，不进本期）**——口径自洽。

---

## 6. 依赖 / 共享知识（design-v16 §6 沿用 1–25 + v1.7 增补）

design-v16 共享知识 1–25 全部沿用（读时迁移幂等 / request_injections 不入历史 / 主动反馈护栏 / 测试数据隔离 / 沙箱批量删除约束等），v1.7 增补：

26. **群聊三隔离**：群聊会话**不写** session.history、**不调** bump_intimacy/intimacy_changed、**不做** memory extract——`custom_messages` 路径单一布尔守卫收口（R-J④⑤ + v1.5.1 零回归的结构性保证）。
27. **历史角色改写规范**：他人 assistant 消息 → user + `【名字】：` 前缀；自己历史保 assistant role；system 永远唯一且含群聊语境段；请求副本用后即弃。
28. **提醒确定性回复**：提醒确认/列览/失败话术一律本地模板直出（screen_bubble 式独立通道），零 LLM；LLM 只出现在 remind_parse 兜底分支且输出必须过 JSON 守卫——失败即诚实话术，零编造。
29. **敏感区改动纪律（page_role）**：F8 全部改动收敛在 schema 字段追加 + build_role_system_prompt 尾部追加 + 独立 helper；**严禁**修改 sync_role_override_to_session / notify_role_switch / replace_history 的既有语义；每任务合入跑"切角色×新会话×重启"三矩阵回归。
30. **通知面统一**：一切系统级通知只走 `tray_manager.notify_maid`（提醒/晚安/既有番茄钟）；新代码禁止自建 QSystemTrayIcon（单一托盘红线延续）。
31. **语录与文案自创**：quotations.json 逐条自创（R-H），入库时不含他人署名语录；语气词库扩查走 P1-2 式剧本断言（本期沿用 v1.6 companion_scenarios 框架增补 F3/F4/F5 剧本）。

---

## 7. 打包评估（对照 PRD §8 逐项核实）

| 需求 | 依赖 | 体积影响 | 离线性 | spec 动作 |
|---|---|---|---|---|
| F3 仪式 | 无新增（语录库 JSON） | 0（<50KB） | 离线（天气本期不做） | hiddenimports 补 `quotations`；datas 补 `gui/assets/quotations.json` |
| F4 提醒 | 无新增（正则 + QTimer + notify_maid 既有）；LLM 兜底走既有 API | 0 | 规则解析/触发离线；兜底需联网 | hiddenimports 补 `reminders`、`gui.widgets.reminder_confirm_card` |
| F5 阶段 | 无新增 | 0 | 离线 | 无 |
| F7 日记 | 无新增（生成走既有 API；导出 stdlib） | 0 | 生成需联网 | hiddenimports 补 `diary` |
| F8/F9 工坊 | 无新增 | 0 | 离线 | hiddenimports 补 `gui.role_card` |
| F10 群聊 | 无新增（复用 API 客户端） | 0 | 联网 | hiddenimports 补 `gui.widgets.group_member_dialog`（切片通过后） |

**打包总评**：**全池零新增第三方依赖**、exe 体积 0 增量延续（R-F）；hiddenimports 净增 ≤6 项 + datas 1 项。**R-K 新增核对点**：① quotations.json 落包且缺文件时内置小池兜底；② diary/quotations 在无网络环境降级路径行为与文档一致；③ F10 发布话术与切片实际状态一致（未过闸则 CHANGELOG 写"实验性/未含"）；④ reminders 规则层离线可用在包内实测。

---

## 8. 待明确事项（架构层面次要开放项，不阻塞开工）

1. **F6 完整安慰模式归属**：本稿按 PM 六项范围未含 F6（v1.6 confide 态已覆盖识别+当轮语气）；若要求本期补"模式状态机+徽标+自动退出"，按 request_injections 增量 +1d，插队批次二——请 PM 排期时定夺。
2. **群聊插话的兴趣判定**：MVP 裁决为"轮转下一位短回应"（无 LLM 判定）——若试用反馈生硬，v1.7.x 演进为轻量 LLM 判定（一次廉价分类调用，受四道闸约束）。
3. **开场白编辑 UI 形态**：单框 `---` 分行解析多套（本稿裁决，最简）；若 PM 要"3 套独立 Tab"需 +0.5d UI 工作量。
4. **日记角色归属**：多角色下日记以"当前默认角色"口吻生成（本稿裁决）；群聊成员各自的日记 = v1.7.x 演进空间。
5. **提醒 quiet 顺延补看的呈现位置**：气泡补在 quiet 结束后首个提醒扫描 tick（本稿裁决），不聚合多条为一条摘要（保持简单）。

---

## 9. 红线复核（v1.7 全项对照）

| 红线 | v1.7 落实 |
|---|---|
| **R-A 无焦虑** | 阶段播报句无数值位（模板定稿审查）；首页称谓只换词；语录/仪式/日记无"第 N 天/连续/打卡"字段与文案（扫描词表扩 4 词进 V17-X + P1-2 剧本）；群聊无任何计分/排行语义。 |
| **R-D 只增量** | 角色/Todo/intimacy/session 全部 `.get` 默认式向后兼容；A9 四重闸结构与 idle_hello 文案池零改动（Q-C9 砍特权）；v1.5.1 对齐链三函数零语义变更（共享知识 29 纪律 + 三矩阵回归）；TodoManager 旧条目零迁移。 |
| **R-G/R-H** | 不触碰屏幕链路；语录库 200+ 条全自创、无第三方源码/语录引用。 |
| **R-I 隐私** | 日记 payload 结构化摘要要点（话题名/情绪标签/高光条目/档位词），自动化断言 payload 不含消息原文（F7a 专项）；角色卡导出字段白名单（无 avatar/记忆/亲密度/历史）；diaries/ritual/todos 全本地 `~/.maid_coder/` 原子写。 |
| **R-J 群聊防失控** | ①@指定唯一触发（无@走轮转/沉默策略，插话另受闸）；②插话默认关 + 每消息 ≤1 + 3min 冷却 + 日上限 5（四道闸全自动化断言）；③成员 ≤3（对话框硬限）；④各角色各自 system + 历史角色改写（他人发言永远带名字前缀的 user 消息，system 唯一）；⑤群聊路径 bump_intimacy 结构性禁用（共享知识 26）。 |
| **R-K 发布诚实** | CHANGELOG 无自评分；F10 交付状态如实标注（切片未过闸即写"未含/实验性"）；文档↔dist 四核对点（§7）；提醒"真机通知权限"差异如实留档。 |

---

## 10. DoD（v1.7 完成标准，承接 PRD §10）

1. **仪式感立住**：早安/午后/晚安按日限次（ritual.json 断言）、错过不补、语录离线 24h 去重、阶段加权生效；晚安气泡可关。（F3）
2. **提醒闭环**：PRD 验收 1 规则用例全绿；LLM 兜底成功登记/失败零编造（断言）；到点通知+气泡、quiet 顺延、重启补送恰一次、确认卡 5min 可撤销；不占 A9 cap；旧 todos.json 零回归。（F4）
3. **关系往前走**：阶段特权生效（晚安变体/语录加权/日记口吻）、升级播报恰一次（notified_stage 断言）、全 UI 无数值；"闲聊话术变体"特权确认不存在。（F5）
4. **她的日记**：次日补写昨日、payload 无原文（R-I 断言）、失败静默不造假、365 篇淘汰、翻阅+导出可用、开关关 = 零 token。（F7）
5. **人设属于你**：开场白（含表情标记/多套轮换）新会话首条正确且幂等；示例对话注入不进历史；角色卡导出→删→导入逐字段还原、异常文件被拒；v1.5.1 对齐链三矩阵回归全绿；旧角色 JSON 零迁移。（F8/F9）
6. **（若切片通过）群聊 MVP**：@谁谁回（人设/头像正确）、无@策略生效、四道插话闸断言全过、人设零串、零计分、历史持久化/恢复、token 如实累计。（F10）
7. **零回归 + 打包**：v1.6.0 全量能力无回归；py_compile 全绿；pytest（v1.6 套件 228+ + v1.6 新增 + v1.7 新增）全绿；R-A 词表全 UI 零命中；零新增第三方依赖；hiddenimports/datas 增量随包验证。（V17-X）

---

## 11. IS_PASS 自审

| 检查项 | 结论 |
|---|---|
| 与 PRD 一致性 | 通过：六项范围全收录；Q-C1~C11 逐项 D-V17 裁决定案（2 项随 v1.6 closed）；F1/F2/F6 归属澄清显式声明，无静默缩水 |
| 与 v1.6.0 现状一致性 | 通过：全部落点基于通读核实（intent.py 五态与 request_injections、memory.pick_topic_followup、notify_maid:150、Role schema:336-390、_INTIMACY_LEVELS:17-25、ChatMessage.metadata:21、SessionManager metadata 落盘）——按重构后真实路径设计，无旧文件位置 |
| 群聊风险控制 | 通过：显示会话层承载绕开对齐链 + 历史角色改写消角色错位 + 四道闸可断言 + 两步切片 + Q-C11 预授权延后——最坏情况 F10 整体顺延且不影响发布完整性 |
| R-D 防回归 | 通过：全部 schema `.get` 默认兼容；A9/对齐链/单托盘零语义变更；敏感区单任务专人 + 纪律条款 |
| 任务粒度 | 15 任务四批；依赖清晰；F10a 设过闸决策点；估算与 PRD 口径对齐（差值已解释：F1/F2 已交付 + F6 范围澄清） |

**IS_PASS: YES**（第一批 V17-0 + F5 可立即开工；F10a 切片过闸后 F10b 才排期）。
