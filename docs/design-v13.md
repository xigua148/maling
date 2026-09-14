# 码铃（MaLing）v1.3 增量架构设计与任务分解

- 版本：v1.3（基于 v1.2.2/v1.2.3 增量，承接 `docs/prd-v13.md` v1.3a）
- 文档状态：架构初稿（供开发排期与实现消费；Q1–Q9 已按 PRD §7 默认建议收敛，见 §2）
- 维护人：高见远（架构）
- 输入：`docs/prd-v13.md`（权威需求，v1.3a，11 项需求 + 9 项待确认默认建议）+ `docs/design-v12.md`（v1.2 架构基线，D1–D8/R1–R14/§3 设计章节）+ 代码实测（`gui/main.py` / `gui/main_window.py` / `gui/widgets/chat_window.py` / `gui/proactive_scheduler.py` / `companion.py` / `gui/theme_engine.py` / `gui/widgets/voice_input.py` / `gui/widgets/camera_capture.py` / `gui/chat_service.py` / `gui/config.py` / `core/__init__.py` / `maid_coder_gui.spec` / `version.json` 等）
- 关联文档：`docs/prd-v12.md` / `docs/design-v12.md`（v1.2 基线，一律沿用不重写）
- 修订记录：
  - **v1.3a（2026-09-04）**：初稿。11 项需求全量收录；Q1–Q9 默认建议逐条架构评估；两处架构层面微调标红（D-V13-02 TTS 后端实现路径、D-V13-09 深色最小目标面）；托盘统一评估为"增量级"给出不触碰已交付托盘代码的落法（D-V13-01）。

> **总体红线复述（PRD §2，跨需求强制，实现逐条对照）**：R-A 全 UI 无数值/筹码/胜率/倒数/断签/进度；R-B Idle 只取 `GetLastInputInfo` 毫秒数、免提仅在显式开启时采集且只用于转文字；R-C 一切主动开口（A9 三类 + idle_return + anniversary）走 A9 调度 gates 口径（enabled / quiet / 共享冷却 / cap），不做系统级弹窗/闹钟，热键/截图/呼出属用户主动动作；R-D 只增量不重构（见 D-V13-10 托盘统一与 D-V13-11 quit 语义边界）；R-E 数据纯本地 `~/.maid_coder/` + `config.yaml`/`gui_config.json`；R-F 零新增第三方依赖（ctypes/winreg/Qt 自带），打包体积 0 增量。

---

## 1. 增量范围（对照 PRD §1，简列）

| PRD ID | 需求 | 一句话承接 | 架构归属（§2/§3/§5） |
|---|---|---|---|
| P1-1 | TTS 语音输出 | SAPI5 离线默认 + 可插拔后端；气泡「🔊 朗读本条」+ 设置语音区 + 自动朗读默认关 | D-V13-02 / §3 / §5 P1-1 |
| P1-2 | 区域截图直接问 | 全屏选区拖框 → 临时 PNG → 附件条 + 预填引导，**不自动发送** | D-V13-04 / §3 / §5 P1-2 |
| P1-3 | 全局唤起热键 | `RegisterHotKey` + QAbstractNativeEventFilter；默认 `Ctrl+Alt+M`；前置 = 主窗 X 关闭改隐藏（Q1） | D-V13-01/D-V13-11 / §3 / §5 P1-3 |
| P1-4 | Idle 问候 | `GetLastInputInfo` 空闲 crossing → 并入 A9 gates（共享 cooldown/cap） | D-V13-03 / §3 / §5 P1-4 |
| P2-1 | 女仆小游戏 | 四游戏纯确定性随机；无计分/无后台加分；情绪反馈沿用 30min 冷却口径 | D-V13-05 / §3 / §5 P2-1 |
| P2-2 | 免提语音对话 | 状态机闭环；三通道退出；免提期间暂停 A9 | D-V13-07 / §3 / §5 P2-2 |
| P2-3 | 高光回忆册 | 独立 `highlights.json` + `回忆` 页；AI/用户气泡均可收藏 | D-V13-06 / §3 / §5 P2-3 |
| P2-4 | 托盘完整菜单 | 单一托盘（P1-3 起 app 级拥有）扩全动作集；chat_window 托盘增量退避 | D-V13-01/D-V13-10 / §3 / §5 P2-4 |
| P2-5 | 开机自启 | winreg HKCU Run，默认关、可干净移除 | §3 / §5 P2-5 |
| P2-6 | 纪念日 | `companion.json.anniversaries` + 独立 1 次/日祝福、受 quiet 约束、错过不补发 | D-V13-08 / §3 / §5 P2-6 |
| P2-7 | 深色模式 | `colors_dark` 色板级，跟随系统热切换 | D-V13-09 / §3 / §5 P2-7 |

> 注：ID 前缀 P1./P2. 为开发批次；与 PRD 优先级列 P0/P1/P2 是两套维度，沿用 PRD §3 口径。v1.3 交付承诺 = 全部 11 项。

---

## 2. 关键架构决策（Q1–Q9 逐条 + 2 项架构自决，标红 = 需 PM/团队复核的微调）

> 每条给出「主理人默认建议 / 实施要点 / 风险点 / 降级方案」。默认建议一律采纳，**架构仅在两处做实现路径级微调并显式标红**（D-V13-02、D-V13-09），不静默推翻。

### 决策表总览

| 编号 | 对应 | 结论（一句话） | 风险级 |
|---|---|---|---|
| D-V13-01 | Q1（+ P2-4） | 主窗 X = 隐藏到托盘；托盘自 P1-3 起由 app 级 `gui/tray_manager.py` 单一拥有；chat_window 既有托盘经一行守卫退避不删 | 高（app 生命周期语义变更） |
| D-V13-02 | Q2 | TTS 后端 = SAPI5 离线；**实现路径建议 QtTextToSpeech（SAPI 引擎）而非手写 ctypes COM**（标红微调） | 中 |
| D-V13-03 | Q3 | Idle 问候独立阈值 30min、**并入 A9 gates 共享 cooldown/daily_cap**；crossing 触发、静默让路 | 低~中 |
| D-V13-04 | Q4 | 选区完成 → 进附件条 + 预填「帮我看看这张截图…」，不自动发送 | 低 |
| D-V13-05 | Q5 | 小游戏零计分键、后台零加分；情绪化反馈单条 30min 冷却（独立计时键，口径同 pet_click） | 低 |
| D-V13-06 | Q6 | AI/用户气泡均可收藏；快照含会话引用；文本 ≤500 字截断 | 低 |
| D-V13-07 | Q7 | 免提三通道退出；免提期 set_busy 暂停 A9；识别失败/静默超时回空闲 | 中~高 |
| D-V13-08 | Q8 | 纪念日祝福独立 1 次/日（不占 A9 cap）；companion.json 新增 `anniversaries` 块 + `blessed` 天标 | 中 |
| D-V13-09 | Q9 | 深色 = 色板级 `colors_dark`；跟随系统走 winreg 轮询热切换 | 中 |
| D-V13-10 | 架构自决 | 托盘统一 ≠ 重构级：chat_window 托盘增量退避 + app 级单一托盘，先决条件是 P1-3 已建 app 级托盘 | 中 |
| D-V13-11 | 架构自决 | quit 单一编舞：`app_ctx.quitting` 标志 + `setQuitOnLastWindowClosed(False)`（随 close_quits 开关联动） | 中（与 D-V13-01 同源） |

---

### 2.1 D-V13-01 · 主窗 X = 最小化到托盘（Q1 默认采纳）+ 托盘单一拥有（P2-4 前置）

**实施要点（代码现状核实行 431–446 `main_window.py closeEvent`：现为保存几何 + `chat_service.shutdown()` + accept；当前 app 内无启动即存在的托盘——托盘只随 `ChatWindow` 惰性创建（chat_panel.py:1032），QSystemTrayIcon 是其子对象）**：

1. `gui/main.py`：MainWindow 创建后置 `app_ctx.main_window = window`；新增 `app_ctx.quitting = False`；按 `gui_config.close_quits` 决定 `app.setQuitOnLastWindowClosed(...)`（默认 False）。
2. `gui/main_window.py closeEvent` 改为：若 `close_quits=False` 且系统托盘可用 → `event.ignore()` + `self.hide()`（保存几何照旧）；若 `quitting=True` 或托盘不可用 → 原逻辑（保存 + shutdown）+ accept。
3. quit 单一编舞（D-V13-11）：托盘「❌ 退出」→ `app_ctx.quitting=True` → 保存 + `chat_service.shutdown()` + 隐藏托盘 + `QApplication.quit()`；ChatService.shutdown 由托盘 quit 调用，主窗 closeEvent 在 quitting 路径不再重复 shutdown（幂等亦可，二者取其一）。
4. app 级托盘（`gui/tray_manager.py`）P1-3 即建最小菜单（显示/隐藏主窗、退出、心情 tooltip、A9 静默气泡），保证「未开过浮窗也能驻留 + 能退出」。

**风险点**：
- app 生命周期语义变更（close→hide）是行为级变更，易出现「关了但退不掉 / 任务栏常驻」困惑；托盘不可用平台/被系统禁用时 X 仍应真退出（守卫已含）。
- 双 quit 路径（closeEvent 旧逻辑 vs 托盘 quit）若没收敛到单一编舞，会重复 shutdown 或漏存几何。
- 静默气泡从 ChatWindow 迁到 TrayManager 时，若 ChatWindow 仍连接 `proactive_message`，会出现双气泡（见 P2-4 退避法）。

**降级方案**：若 closeEvent 改造回归面超预期 → 保持 X=退出不变，P1-3 热键只做「呼出/聚焦」（最小语义），Q1 整体降级到 P2 批随托盘统一再做（需 PM 知情）；托盘不可用环境自动回落现行为。

---

### 2.2 D-V13-02 · TTS 后端：SAPI5 离线默认（Q2 采纳）；**实现路径微调标红**

**主理人默认建议**：SAPI5 离线默认（R-E 最稳、零体积），edge-tts 留 P2 可插拔口（默认关 + 隐私明示）。

**架构微调（标红，需 PM/团队知悉，不改结论只改实现路径）**：PRD §6 表写「ctypes 调 `SpVoice` COM」。经代码现状核实，手写 ctypes 调 COM 接口（ISpeechVoice/IDispatch Invoke）约 150–250 行脆弱绑定，维护与异常成本高、误用易崩。**建议 SAPI 后端走 PySide6 自带 `QtTextToSpeech`（Windows 底层即 SAPI5）**：
- PySide6 已在本应用随包（`camera_capture.py` 已用 QtMultimedia，属 PySide6_Addons 同一安装体系），**零新增第三方依赖、零网络、纯本地**，R-E/R-F 不变，体积增量 ≈ QtTextToSpeech DLL（MB 级以下）。
- 仍满足「可插拔接口」：`gui/tts.py` 内 `TTSBackend` 抽象，`SapiBackend(QTextToSpeech)` 默认实现；edge-tts 后端口预留（P2，本版不打包、不默认开）。
- 若运行环境 QtTextToSpeech import 失败 → 语音区显示「系统 TTS 组件不可用」降级提示，其余功能不受影响（同 camera/voice 三态探测风格）。

**实施要点**：
- `gui/tts.py`：`TTSController(QObject)`（app_ctx 单例）+ `speak(text)`/`stop()`/`is_speaking`；`SapiBackend` 内部 QTextToSpeech，语速经 0..100 UI 值映射引擎 rate。
- 只有 AI 回复可朗读；`message_stream_finished` 钩子：`auto_read` 开且非 demo 时朗读回复文本（**不中断流式**——回复已完成才触发，天然满足）；无 key 演示模式无回复 → 不朗读。
- 气泡「🔊 朗读本条 / ⏹ 停止」：`message_bubble.py` AI 气泡 action 行（与「🔄 重新生成」同排）新增；点停止只停当前条。
- `GuiConfig` 增 `tts_enabled`（朗读按钮总开关，默认 True）/`tts_auto_read`（默认 False）/`tts_speed`（默认 50）；设置页新增「语音」区。
- **红线**：只朗读 AI 文本，不朗读用户原文（隐私）；多气泡并发朗读 → 全局单例，后开口打断前开口。

**风险点**：系统缺中文语音包 → SAPI speak 失败；QTextToSpeech 在不同系统版本行为差异（rate 语义）。**降级**：错误回调接住，气泡与设置页给一句「未检测到系统语音，请到 Windows 语音设置添加中文语音包」；edge-tts 后端口保持打开但 v1.3 不交付入口。

---

### 2.3 D-V13-03 · Idle 问候并入 A9 gates、共享冷却（Q3 采纳）

**主理人默认建议**：系统 Idle 阈值独立默认 30min，并入 proactive gates 且共享 cooldown/cap。

**实施要点（现状核实：`proactive_scheduler.py` 已有四重闸 `enabled→quiet→cap→cooldown`，场景 ③ idle_hello 是「连续空闲≥idle_minutes 才问候一次」，无 crossing 语义；companion.proactive.last_at 是全局主动时间戳，天然共享）**：
- 新增 `gui/system_idle.py`：`SystemIdleMonitor(QObject)`，QTimer 秒级轮询 `GetLastInputInfo`；状态机 `away→present` 上升沿才 emit `returned()`；`last_input_age_ms()` 工具函数（供免提 P2-2 复用）。
- 新增独立场景 `idle_return`：`ProactiveScheduler` 增 `on_system_idle_return()` 入口——**不新起定时器**，由 SystemIdleMonitor 上升沿回调；内部复用现有四重闸判定（enabled/quiet/cap/cooldown 全查，demo/忙挡在外），放行则 `_deliver(idle_return 文案, scene)` + `commit_proactive`。与 A9 三种场景共享 `last_at/count_today` → 同一冷却窗内 app 内问候与 Idle 问候**天然互斥不双发**。
- 文案池：`SCENE_TEXTS` 增 `idle_return` 条目（接 A9 文案池 + `current_mood_context()` 心情/称谓）；防刷：离开 <30min 不触发（阈值判定在 monitor）；同日多次短暂离开由共享 cap 收敛。
- 配置：`core/__init__.py` AppConfig + `_YAML_FIELD_MAP` + env 增 `agent_proactive_idle_return_enabled`(True)/`agent_proactive_system_idle_minutes`(30)，写 `agent.proactive.{idle_return_enabled,system_idle_minutes}`；`ProactiveConfig.from_cfg` 接读。
- Idle 问候由 SystemIdleMonitor 只在 GUI 运行期存在 → app 未运行不触发（R-C 满足）。

**风险点**：GetLastInputInfo 只返回"距上次输入毫秒"，跨 DPI/锁屏场景行为需真机验证；与 A9 idle_hello 双判定并存，若共享冷却把 idle_return 卡到几乎不发声，PM 预期落差（Q3 已默认共享，属预期，若想高频须走 Q3 备选独立 cap=2，需显式决策）。

**降级方案**：monitor 判定失败/API 不可用 → 模块内降级禁用并记日志，不影响主流程（A9 既有 idle_hello 仍在）。

---

### 2.4 D-V13-04 · 截图提问不自动发送（Q4 采纳）

**实施要点**：`gui/widgets/screen_capture.py`（仿 `camera_capture.py` 防御式临时文件思路）：无边框半透明全屏遮罩 QDialog + 多屏遍历 `QScreen.grabWindow(0)` + `devicePixelRatio` 校正 → 选区拖框 → 存 `tempfile/maid_coder_shot/shot_*.png` → 成功返回路径。触发后：`attachment_bar.add_file_path(png)` + 输入框**预填**「帮我看看这张截图…」，**不自动发送**；用户确认/改字后走既有 `send_message` 附件通道。无视觉模型 → 沿用既有可读报错引导（v1.2.2 已有）。

**风险点**：多屏/高分屏 DPI 坐标换算偏差（选区与截取错位）。**降级**：先用主屏单屏最小可用，多屏 P2 内修；隐私由"显式触发 + 不自动发送"双保险。

---

### 2.5 D-V13-05 · 小游戏零计分、情绪反馈 30min 冷却（Q5 采纳）

**实施要点（现状核实：`companion.py` `react_to_pet_click()` 已有 30min 冷却模板；`EVENT_TYPES` 白名单校验 ingest_event）**：
- `gui/widgets/mini_games.py`：四游戏（抛硬币/抽签/猜拳/21 点），纯 `random` 确定性结果，零 LLM；她当荷官只做"台词 + 结果一句"，**UI 绝无分数/货币/筹码/胜率/连胜/等级/今日首胜**。
- companion 新增 `react_to_game_result(outcome) -> {text, expression, cooling}`：按 pet_click 同款 30min 冷却口径，独立计时键 `companion.json["mini_game"]["last_at"]`（**非 intimacy 计分键**，冷却内只回普通台词）；冷却外回一句情绪反馈文案 + 短暂 surprised/happy 表情（经 bridge.note_activity，不持久化 mood），**不调 intimacy.add_interaction、后台零加分**。
- `EVENT_TYPES` 增 `"game"`；仅冷却外 `ingest_event("game")` 记账（足迹语料，非计分）。台词带 `relation_stage_name()` 称谓。
- 入口：聊天面板工具区「🎲 小游戏」按钮 + 首页快捷入口（二选一亦可，默认两处，UI 侧裁决）。

**风险点**：21 点规则歧义、庄家行为属纯规则需写死（产品无需再裁决，取最简单荷官规则并文案自洽）；R-A 扫描需把游戏 UI 纳入（筹码/胜率/连胜词零残留）。**降级**：把结果从"你赢/你输"改写为陪伴式叙事时如被 UI 成本卡住，先只交付抛硬币+猜拳两个最简游戏，抽签/21 点 P2 内补。

---

### 2.6 D-V13-06 · 回忆收藏 AI 与用户双收（Q6 采纳）

**实施要点**：气泡右键菜单增「✨ 收藏为高光回忆」，`MessageBubble` 发 `favorite_requested(role, text, meta)`；chat_panel/chat_window 监听到调 `HighlightsManager.add(...)`。快照 = {date, role, text(≤500 截断), session 引用, 当时心情(companion.mood)}。数据存**独立文件** `~/.maid_coder/highlights.json`（理由：总量无上界、逐条独立生命周期，避免撑大 companion.json 的整档原子写；架构裁决，PRD 已授权）。回忆页 `gui/pages/page_memories.py`：时间倒序卡片 + 取消收藏/清空 + 底部一行中性相伴信息（相伴总天数/首次相见日，读 companion.streak/anniversaries，无数值墙）。页注册走 sidebar `NAV_ITEMS` + main_window `page_classes` 同现有模式。

**风险点**：无界增长 → 上限 500 条滚动淘汰（写进 manager，UI 不显示计数）；会话被删后 session 引用失效 → 只回溯定位不强链。**降级**：清空/取消收藏可整档重写，无事务诉求。

---

### 2.7 D-V13-07 · 免提三通道退出（Q7 采纳）

**实施要点**：`gui/voice_conversation.py`：`VoiceConversationController(QObject)` 状态机 `idle→listening→recognizing→sending→speaking→listening`。识别循环复用 `voice_input.py` 既有 STT 链路（SpeechRecognition + pyaudio + recognize_google zh-CN，依赖已进包）；speaking 环节依赖 P1-1 TTS。发送落地**不直连 ChatService**：controller emit `speech_ready(text)`，由 chat_panel/chat_window 各自复用本面板 `_on_send` 路径（保住"UI 直插气泡唯一渲染入口"约定，防双气泡）。
- 三通道退出：① 状态条「⏹ 停止」按钮；② 识别文本命中固定关键词（暂停/结束对话）→ 回 idle；③ 任意系统输入打断——listening 期复用 `gui/system_idle.last_input_age()`，连续检测到新输入 → 视为用户想打字，自动停听并提示（灵敏度真机标定，见 §8）。
- 免提期间 `scheduler.set_busy("handsfree", True)` 暂停 A9（防她在你说话时插嘴）；识别失败/静默超时不打断循环、自动回空闲。
- UI：聊天面板顶部免提状态条（常驻醒目）+ 快速入口「🎙 免提」开关（可与既有「🎤 语音」并存；不替换它）。chat_window 浮窗提供入口作为 P2-2 可选增强（同一 controller，避免第二套识别链）。

**风险点**：连续录音/识别生命周期与 QThread 管理复杂（现有 VoiceInputDialog 是单次模态，需新的可循环 worker）；Google STT 网络依赖既有声明（非本版新增）；关键词误命中打断正常对话。**降级**：先交付「按钮启停 + 界面停止」两通道，关键词与任意输入打断留真机标定后补（P2 内），不影响主闭环跑通。

---

### 2.8 D-V13-08 · 纪念日独立 1 次/日配额（Q8 采纳）

**实施要点**：`companion.json` 新增 `anniversaries` 块（见 §4.1）。`CompanionManager` 增 getter/setter + `anniversary_due_today()` + `mark_anniversary_blessed()`。`ProactiveScheduler` 增**独立祝福通道** `maybe_anniversary_blessing()`（在既有 tick 内顺带判定，不新起定时器）：判定 = enabled ∧ 非 quiet ∧ 今日命中 anniversary ∧ `blessed != today`；命中 → `_deliver(anniversary 文案, scene="anniversary")` + 标记 blessed=today。**独立配额语义**：不走 daily_cap/cooldown 两道闸（温暖仪式不被日常问候挤掉），仍受 enabled/quiet/demo/忙 约束；**绝无补发**（当天 app 没运行/无 key → 错过即错过，blessed 不补记，次日自然再判）。
- 生日与首次相见日同天撞车 → 合并为一条祝福（防双气泡）。
- 设置页「纪念日」区：QDateEdit × 2（生日/首次相见日），存 MM-DD（周年语义），无倒数文案。
- 红线：无倒计时、无断签、无打卡义务感（R-A）。

**风险点**：日期解析与跨天边界（23:59 判定 vs 08:00 后触发）；与 idle_return 双场景同日叠发 → idle_return 走共享 cap/冷却、anniversary 走独立通道，同日两场景可能都出声（间隔数小时内）。**降级**：若 PM 判定"同日两条主动太吵"，给 anniversary 也挂 cooldown（只与 idle_return 竞争时不冲突即可），架构预留一行开关。

---

### 2.9 D-V13-09 · 深色模式 = 色板级跟随系统（Q9 采纳）

**实施要点（现状核实：`theme_engine.py` `THEME_DEFINITIONS` 每主题 colors + layout + font，`load_theme` 一次性做 `${var}` 替换并 emit `theme_changed(str)`；`theme_color()`/`get_color()` 读当前主题 colors）**：
- 每主题增 `colors_dark`（与 colors 同键深色变体，**不得缺键**）；`ThemeEngine` 增活动色板解析：`_resolve_palette(theme, mode)` = mode=="dark" 时 `{**colors, **colors_dark}`（colors_dark 缺失键回落 colors，兼容渐进）；QSS 替换用解析后色板；`get_color/get_layout_token` 改读活动色板。
- 新增 `theme_mode`（light/dark/system，存 GuiConfig，默认 light）；"system" 时 winreg 读 `HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize\AppsUseLightTheme`（0=深），QTimer 低频轮询（5min）感知变化 → 热切换（内部再走 `load_theme(current_theme)` 全量重建，复用既有 `theme_changed(str)` 单参信号，**不改信号签名**——既有订阅方靠它刷新取色，零回归）。
- 深色可读性最小目标面（**微调说明**）：chat_window/输入框/气泡等**既有硬编码浅色**（如 `#FFF8FA/#FFE4EC`）必须替换为 `theme_color()` 语义键才能保证深色可用——这超出"纯 QSS 变量"但仍在**色板级**（不画插画/图标重绘）；主形象透明 PNG 用柔化圆形容器垫底防穿帮；占位脸/宠物 QPainter 配色给深色变体。新增色键必须三主题 × 深浅两套注册（B8 约束）。
- 设置页「外观主题」区改三选（浅色/深色/跟随系统）+ 保留原主题三选。

**风险点**：既有大量内联 `setStyleSheet` 硬编码（chat_window/message_bubble/sidebar 等）是深色最大障碍——全量 sweep 触碰已交付代码面大（R-D 邻近），故收窄到"深色下主要表面 + 文本可读"清单，其余 P2+ 续 sweep。**降级**：深色模式若回归风险不可控 → 先只做「三选一切换时 QSS 生效」，内联硬编码点做黑名单清单化替换（不改结构只改取值），offscreen 三主题×两模式截图 diff 把关。

---

### 2.10 D-V13-10 · 架构自决：托盘统一 = 增量级，非重构级（P2-4 前置澄清）

**评估**：chat_window 托盘（`_setup_tray` + `_tray_icon` 约 6 处引用 + mood/proactive 两处广播）**如整体迁出属重构级**（会重写已交付链路内部引用）。但代码现状核实发现关键事实：所有 chat_window 托盘处理器（`_refresh_tray_mood`/`_on_proactive_ready`/`_on_tray_quit`）入口均有 `self._tray_icon is None → return` 守卫。因此**只需让 ChatWindow 不再创建图标**（`_setup_tray` 顶部一行 `if app 级托盘存在: return`），其既有处理器全部自动退避为空操作，零删除零改写 → 判为**增量级**。

**落法**：P1-3 已由 TrayManager 建 app 级单托盘（含显示/隐藏/退出/A9 静默气泡/mood tooltip）；P2-4 扩其菜单为完整动作集（📷/🎤/🖼 截图/⚙️ 设置/💬 浮窗/❌ 退出）。若评审仍判双图标风险 → **退回 PRD 最小形态**：TrayManager 保留（Q1 必需，见 D-V13-01），完整动作项逐条 `getattr` 守卫、主窗未就绪时禁用。

---

### 2.11 D-V13-11 · 架构自决：quit 单一编舞（与 D-V13-01 配套）

见 2.1 实施要点 3。要点：主窗 closeEvent 不再承担"真退出"，统一由 `app_ctx.quitting` 标志 + 托盘 quit 或 close_quits=True 时的关闭事件承载；`setQuitOnLastWindowClosed` 随 `close_quits` 开关联动（关闭=退出时恢复 True，防旧用户习惯失效后"退不掉"）。

---

## 3. 模块 / 文件清单

### 3.1 新增文件

| 路径 | 一句话职责 | 对应需求 | 是否进 v1.3 承诺 |
|---|---|---|---|
| `gui/tts.py` | TTS 控制器 + 后端接口（默认 QtTextToSpeech/SAPI，edge 口预留）；朗读/停止/语速；AI 文本朗读守卫 | P1-1 | 是 |
| `gui/widgets/screen_capture.py` | 区域截图遮罩 QDialog：多屏 grabWindow + DPI 校正 + 临时 PNG + 不自动发送契约 | P1-2 | 是 |
| `gui/hotkeys.py` | RegisterHotKey + QAbstractNativeEventFilter 全局热键管理；失败静默降级提示 | P1-3 | 是 |
| `gui/tray_manager.py` | app 级单一 QSystemTrayIcon：完整菜单 + 信号桥（主窗/浮窗/拍照/语音/截图/设置/退出）+ mood tooltip + A9 静默气泡 | P1-3 最小/P2-4 完整 | 是 |
| `gui/system_idle.py` | GetLastInputInfo 轮询 + away/present crossing 状态机 + `last_input_age_ms()` 工具 | P1-4（P2-2 复用） | 是 |
| `gui/widgets/mini_games.py` | 四款小游戏对话框（纯确定性随机、零 LLM、无数值 UI） | P2-1 | 是 |
| `gui/voice_conversation.py` | 免提对话控制器（状态机 + 识别循环 + 三通道退出 + speech_ready 信号） | P2-2 | 是 |
| `gui/widgets/handsfree_bar.py` | 免提状态条组件（常驻醒目 + ⏹ 停止） | P2-2 | 是 |
| `highlights.py`（根级，纯 stdlib） | HighlightsManager：highlights.json 原子写、快照截断 500、上限淘汰 | P2-3 | 是 |
| `gui/pages/page_memories.py` | 回忆页：时间倒序卡片 + 取消/清空 + 中性相伴信息行 | P2-3 | 是 |
| `autostart.py`（根级，纯 stdlib） | winreg HKCU Run 写/读/删（MaLing 值），frozen/source 双路径，幂等可逆 | P2-5 | 是 |

### 3.2 修改文件

| 路径 | 改动点 | 风险级 |
|---|---|---|
| `gui/main.py` | 装配：app_ctx.main_window/`quitting`；quit 编舞；TrayManager/Hotkeys/SystemIdle/TTS/Highlights 单例挂载（各 try/except 不阻断）；`setQuitOnLastWindowClosed`；启动即写默认 config.yaml（proactive 新键） | 中（生命周期） |
| `gui/main_window.py` | closeEvent 改隐藏逻辑（D-V13-01/11）；托盘动作桥方法（toggle/navigate_settings/open_float/camera/voice/screenshot）；page_classes 增 `("memories", PageMemories)` | 中（高影响点但改动局部） |
| `gui/widgets/chat_window.py` | `_setup_tray` 顶部一行退避守卫（app 级托盘存在则不建图标）；其余托盘处理器零改动自动退避；免提入口可选 | 低~中 |
| `gui/widgets/message_bubble.py` | AI 气泡 action 行增「🔊 朗读」；右键菜单增「✨ 收藏为高光」；新信号 favorite_requested | 中（交付控件但纯增量） |
| `gui/widgets/chat_panel.py` | 工具区增「🖼 截图」「🎲 小游戏」「🎙 免提」；截图落附件+预填；favorite_requested→Highlights；hands-free 状态条；`speech_ready`→复用 _on_send | 中 |
| `gui/widgets/sidebar.py` | NAV_ITEMS 增 `("memories","回忆",✨)` | 低 |
| `gui/pages/page_settings.py` | 新增「语音」区（TTS 开关/自动朗读/语速）；「通用」区补全局热键改键 + 「关闭窗口直接退出」；「外观主题」区改三选 mode；新增「纪念日」区；**开机自启**开关（含首次确认） | 中 |
| `gui/theme_engine.py` | 每主题增 `colors_dark`；活动色板解析；`theme_mode` 应用与 system 轮询热切换；get_color 读活动色板 | 中 |
| `gui/chat_service.py` | `message_stream_finished` 补 TTS auto_read 守卫钩子（getattr，缺 tts 空转）；供 P2-2 busy 语义的既有 is_busy 复用 | 低 |
| `companion.py` | `EVENT_TYPES` 增 game/anniversary；`react_to_game_result()`；`anniversaries` 块 + getter/setter/due/blessed；`mini_game.last_at` 冷却；_EVENT_PHRASES 补 game/anniversary 文案；_merge_defaults 兜底新块 | 低（纯增量） |
| `gui/proactive_scheduler.py` | 场景 `idle_return` + `on_system_idle_return()` 入口（复用四重闸）；独立通道 `maybe_anniversary_blessing()`；SCENE_TEXTS 补 idle_return/anniversary；ProactiveConfig 接读新配置键 | 中（加方法不改判定核心） |
| `core/__init__.py` | AppConfig 增 `agent_proactive_idle_return_enabled/system_idle_minutes`（字段 + _YAML_FIELD_MAP + env + save） | 低 |
| `gui/config.py` | GuiConfig 增 theme_mode/tts_enabled/tts_auto_read/tts_speed/hotkey_toggle/hotkey_screenshot/close_quits/autostart_enabled + save() 收录 | 低 |
| `maid_coder_gui.spec` | hiddenimports 补全部新模块 + `PySide6.QtTextToSpeech`（若用 QtTTS）；datas 无新增 | 低 |
| `CHANGELOG.md`/`version.json`/`core/__init__.py` | v1.3.0 收口同步 | 低 |
| `README.md` | 能力速览补：TTS/截图提问/全局热键/Idle/小游戏/免提/回忆册/纪念日/深色/托盘/自启；打包章节同步（§7） | 低 |

### 3.3 P2+ 预留（不做代码，仅留口）

- edge-tts 高质量女声后端（tts.py 后端口）；A8-ext 不受影响；节日皮肤不进（PRD §1.4）；回忆页日历/时间线可视化 P2+；托盘 ico 深浅双态 P2+（Q9 不承诺）。

---

## 4. 数据结构

### 4.1 companion.json（增量块，`_merge_defaults` 兜底，schema_version 保持 1）

```json
{
  // …既有键全部不动（mood/streak/moments/achievements/milestones/event_log/proactive/pet_click）
  "anniversaries": {
    "birthday": "MM-DD",          // 可空；周年语义，QDateEdit 录入后归一化存 MM-DD
    "first_meet": "MM-DD",        // 可空
    "blessed": "YYYY-MM-DD"       // 最近一次已祝福的日期标记（防跨天重发，绝无补发）
  },
  "mini_game": {
    "last_at": null               // 最近一次冷却外情绪反馈时间（30min 冷却口径，非计分键）
  }
}
```

> - 祝福配额独立于 `proactive.count_today`（D-V13-08）：纪念日不写 proactive 计数器。
> - `event_log` 事件类型白名单增 `game` / `anniversary`（companion.py EVENT_TYPES）。
> - 明确 **不新增任何 intimacy 计分键**（Q5）；`pet_click` 块保持原义不动。

### 4.2 highlights.json（新文件，`~/.maid_coder/`，原子写）

```json
{
  "schema_version": 1,
  "meta": { "created_at": "ISO", "updated_at": "ISO" },
  "items": [
    {
      "id": "hl_xxxxxxxx",
      "role": "user|assistant",        // Q6：AI/用户双收
      "text": "…（≤500 字截断）",
      "session_id": "…",               // 会话引用（定位用，不强链）
      "mood": "normal",                // 收藏当时 companion.mood 快照
      "at": "ISO"
    }
  ]
}
```

### 4.3 GuiConfig（gui_config.json，`gui/config.py` 扩展；`theme_name/pet_enabled/pet_style` 等既有字段不重定义）

| 字段 | 类型/默认 | 语义 |
|---|---|---|
| `theme_mode` | str `"light"` | light/dark/system（P2-7） |
| `tts_enabled` | bool True | 朗读按钮总开关（P1-1） |
| `tts_auto_read` | bool False | 自动朗读回复（默认关） |
| `tts_speed` | int 50 | 语速 0..100 → SAPI rate 映射 |
| `hotkey_toggle` | str `"Ctrl+Alt+M"` | 全局呼出/隐藏主窗（P1-3） |
| `hotkey_screenshot` | str `"Ctrl+Alt+S"` | 截图提问热键（P1-2/P1-3 触发） |
| `close_quits` | bool False | 「关闭窗口直接退出」开关（默认不勾 = X 隐藏到托盘） |
| `autostart_enabled` | bool False | 自启开关 UI 镜像（真值源在注册表） |

### 4.4 AppConfig / config.yaml（`agent.proactive` 段扩展，`core/__init__.py`）

```yaml
agent:
  proactive:
    idle_return_enabled: true      # Idle 问候总开关（默认 true）
    system_idle_minutes: 30        # 系统全局空闲阈值（默认 30；与 agent 内 idle_minutes:90 并存）
```

> 运行时频控计数仍存 `companion.json.proactive`（不新增独立计数器）；`idle_return` 与 A9 三类共享该计数器与冷却（Q3）。

### 4.5 ProactiveConfig（`gui/proactive_scheduler.py`）

`from_cfg` 追加：`idle_return_enabled`（默认 True）、`system_idle_minutes`（默认 30）；其余四重闸配置沿用。

---

## 5. 任务分解列表（ID 沿用 PRD；有序按批；P1 批先 4 项 / P2 批后 7 项 + 2 项整合）

> 批内标注可并行项。同文件并发注意：`page_settings`/`chat_panel`/`companion.py`/`proactive_scheduler.py` 为多人汇交点，建议按"分区/方法级"commit、避免同文件同函数互踩；每个任务完成后 `py_compile` 绿。

### 5.1 依赖总览

- **P1 批 4 项互不阻塞、可 4 路并行**（P1-1 设置页语音区 / P1-2 快捷区按钮 / P1-3 设置页通用区 / P1-4 配置段——page_settings 与 chat_panel 是主汇交点，见上建议）。
- **P1-3 是 P2-4 的前置**（app 级托盘先建、quit 编舞先落地）；P1-2 截图是 P2-4 托盘动作的来源之一。
- **P2-2 依赖 P1-1**（speaking 环节）；P2-6 祝福通道与 P1-4 复用同一 scheduler 扩展点（scheduler 文件串行修改）。
- **P2-7 无功能依赖**，但色板改动会触碰 chat_window/message_bubble 取色 → 建议排在 P2 批中段，与 P2-3/P2-4 错开同文件时段。

### 5.2 P1 批（S 级，可并行开工）

| 任务 ID | 任务 | 依赖 | 负责人建议 | 产出文件 | 改动范围 | 风险 |
|---|---|---|---|---|---|---|
| V-0 | 基线接线：新模块骨架 + app_ctx 挂载点 + spec hiddenimports 一次性收录 + 默认 config.yaml proactive 新键 | — | 架构/主程 | spec、main.py、core/__init__.py | 全仓轻量 | L |
| P1-1 | TTS：`gui/tts.py` + GuiConfig 语音字段 + 设置「语音」区 + 气泡朗读按钮 + chat_service auto_read 钩子 + 演示模式守卫 | V-0 | UI/逻辑工程师 | gui/tts.py、message_bubble.py、chat_panel.py、page_settings.py、config.py、chat_service.py | 纯新增 + 3 个汇交点文件 | M |
| P1-2 | 截图提问：screen_capture.py + 工具区按钮 + 附件条/预填 + 不自动发送 + 视觉模型缺省引导复用 | V-0 | UI 工程师 | gui/widgets/screen_capture.py、chat_panel.py | 纯新增 + chat_panel 一处 | L |
| P1-3 | 全局热键 + Q1（X→托盘 + quit 编舞 + app 级最小托盘）：hotkeys.py、tray_manager.py(最小)、closeEvent/生命周期、GuiConfig 热键与 close_quits、设置「通用」区 | V-0 | 主程/架构（生命周期敏感） | gui/hotkeys.py、gui/tray_manager.py、main.py、main_window.py、config.py、page_settings.py | 生命周期行为变更 + 2 新模块 | **H** |
| P1-4 | Idle 问候：system_idle.py + scheduler `idle_return` 场景 + AppConfig/ProactiveConfig 新键 + crossing 触发 | V-0 | 逻辑工程师 | gui/system_idle.py、proactive_scheduler.py、core/__init__.py、main.py | 纯新增 + scheduler/config 扩展 | L~M |
| P1-X | P1 批集成冒烟：四场景 hand-on + 红线快扫（无数值词残留，scan 词扩：筹码/胜率/倒数/断签） | P1-1..4 | QA/验收 | — | 全仓 | — |

### 5.3 P2 批（A+B 级，P1 批后；并行建议见下）

| 任务 ID | 任务 | 依赖 | 负责人建议 | 产出文件 | 改动范围 | 风险 |
|---|---|---|---|---|---|---|
| P2-1 | 小游戏：mini_games.py 四游戏 + companion `react_to_game_result` + EVENT_TYPES 增 game + 入口按钮（聊工具区+首页） | V-0 | UI 工程师 | gui/widgets/mini_games.py、companion.py、chat_panel.py、page_home.py(可选) | 纯新增 + companion 增量 | L |
| P2-2 | 免提语音：voice_conversation.py 状态机 + handsfree_bar + chat_panel 接线(speech_ready→_on_send) + 免提期 set_busy + 三通道退出 | P1-1 | 逻辑/UI 联合 | gui/voice_conversation.py、gui/widgets/handsfree_bar.py、chat_panel.py、chat_window.py(可选) | 纯新增 + 汇交点 | M~**H** |
| P2-3 | 回忆册：highlights.py + page_memories.py + sidebar/main_window 注册 + 气泡收藏菜单与接线 | V-0 | 逻辑/UI 工程师 | highlights.py、gui/pages/page_memories.py、message_bubble.py、chat_panel.py、sidebar.py、main_window.py | 纯新增 + 3 汇交点 | L |
| P2-4 | 托盘完整菜单：tray_manager.py 扩全动作集（📷/🎤/🖼/⚙️/💬/❌）+ chat_window `_setup_tray` 一行退避守卫 + 主窗动作桥方法 | P1-3, P1-2 | UI/主程 | gui/tray_manager.py、chat_window.py、main_window.py、chat_panel.py(供方法) | 托盘扩展 + 1 行守卫 | M |
| P2-5 | 开机自启：autostart.py（winreg 幂等写删）+ 设置「通用」开关 + 首次确认 | V-0 | 逻辑工程师 | autostart.py、page_settings.py、config.py | 纯新增 + 设置区 | L |
| P2-6 | 纪念日：companion `anniversaries` 块 + scheduler `maybe_anniversary_blessing()` 独立通道 + 设置「纪念日」区(QDateEdit) | V-0（scheduler 扩展建议等 P1-4 合入后串行） | 逻辑/UI | companion.py、proactive_scheduler.py、page_settings.py | companion/scheduler 增量 | M |
| P2-7 | 深色模式：theme_engine colors_dark + 活动色板 + theme_mode 三选 + system 轮询热切换 + 深色可读性最小目标面（chat_window/气泡/输入框取色替换）+ 设置外观区改选 | V-0 | UI 工程师 | gui/theme_engine.py、page_settings.py、chat_window.py、message_bubble.py、chat_panel.py、attachment_bar.py | 引擎扩展 + 若干取色点替换 | M |
| V-X | 全量收口：py_compile + A-14 式红线扫描（含小游戏/回忆/纪念日 UI，词表扩：筹码/胜率/连胜/倒数/断签/打卡/进度）+ 三主题×深浅 offscreen 截图 diff + 回归冒烟（房间/宠物/A9/看图/语音输入/托盘/独立窗）+ 打包 onedir 验证体积零增量 + 升版（version.json/`__version__`/CHANGELOG/README） | 全部 | QA/主程 | version.json、CHANGELOG.md、README.md、core/__init__.py | 全仓 | L |

**P2 批并行建议**：P2-1 / P2-3 / P2-5 三路并行（低汇点）；P2-4 紧随 P1-3；P2-6 在 P1-4 的 scheduler 扩展合入后启动（同文件串行）；P2-2 依赖 P1-1 落地；P2-7 建议与 P2-2/P2-3 错开 chat_panel/message_bubble 时段。

---

## 6. 依赖 / 共享知识（design-v12 §6 沿用 + v1.3 新增）

design-v12 共享知识 1–10 全部沿用，v1.3 增补：

11. **编码与原子写**：一切 JSON/QSS 读写显式 `encoding="utf-8"`；用户数据一律走 `~/.maid_coder/` 原子写（companion 的 `_atomic_write_json` 先写 `.tmp` 再 `os.replace`；新 highlights.py 同法，不复用 utils 以免拉入 core 依赖链）。
12. **frozen hiddenimports 必加**：新增模块（`gui.tts`/`gui.hotkeys`/`gui.tray_manager`/`gui.system_idle`/`gui.voice_conversation`/`gui.widgets.screen_capture`/`gui.widgets.mini_games`/`gui.widgets.handsfree_bar`/`gui.pages.page_memories`/`highlights`/`autostart` + `PySide6.QtTextToSpeech`）一律进 `maid_coder_gui.spec` hiddenimports；凡 main 内延迟 import 的根级模块（highlights/autostart 同 companion 先例）保险列出。
13. **防刷口径统一沿用 pet_click 30min 冷却**：小游戏情绪化反馈单条冷却 30min、独立计时键、无计分、后台零加分；Idle 问候与 A9 共享 proactive cooldown/cap，互斥不双发。
14. **单一托盘 / 单一 quit**：全 app 只允许一个 QSystemTrayIcon（TrayManager 所有）；真退出唯一入口 = quitting 标志路径，closeEvent 不再直接承担 app 退出。
15. **theme_changed 信号签名不变**（单参 str）：深色热切换通过重入 `load_theme(current_theme)` 复用既有信号，避免所有订阅方改造；新取色一律 `theme_color(app_ctx, key, fallback)`/`get_color()`（活动色板），禁止裸值。
16. **气泡渲染单入口**：用户气泡仍由 UI 直插 + `suppress_echo=True`（免提语音 `speech_ready` 只发信号、由面板复用 _on_send，ChatService 不回 echo），防双气泡。
17. **主动陪伴三通道护栏**：所有"码铃主动开口"（A9 三类 + idle_return + anniversary）只走 `ChatService.proactive_ask` 交付；免提期间 `set_busy("handsfree")` 暂停开口。

---

## 7. 打包影响（对照 PRD §6 表逐项核实）

| 需求 | 依赖 | 体积影响 | 离线性 | spec 动作 |
|---|---|---|---|---|
| P1-1 TTS | **无新增第三方**（QtTextToSpeech 属 PySide6_Addons，随包体系） | 0~MB 级（QtTTS DLL） | 离线（SAPI5；无中文语音包给降级提示） | hiddenimports 补 `gui.tts` + `PySide6.QtTextToSpeech` |
| P1-1（edge-tts 可选口） | 不打包、不开默认入口；后端口预留 | 0（不进默认产物） | 联网需明示 | requirements 可选行 + hiddenimports `edge_tts`（P2+） |
| P1-2 截图 | 无新增（Qt QScreen） | 0 | 离线 | hiddenimports 补 `gui.widgets.screen_capture` |
| P1-3 热键 | 无新增（ctypes RegisterHotKey） | 0 | 离线 | hiddenimports 补 `gui.hotkeys` |
| P1-4 Idle | 无新增（ctypes GetLastInputInfo） | 0 | 离线 | hiddenimports 补 `gui.system_idle` |
| P2-1 小游戏 | 无新增 | 0 | 离线 | hiddenimports 补 `gui.widgets.mini_games` |
| P2-2 免提 | **既有** SpeechRecognition+pyaudio（已进包） | 0 | STT 需 Google 网络（既有声明）；TTS 侧离线 | hiddenimports 补 `gui.voice_conversation`/`gui.widgets.handsfree_bar`；沿用 voice_input 三态降级风格 |
| P2-3 回忆册 | 无新增 | 0 | 离线 | hiddenimports 补 `highlights`/`gui.pages.page_memories` |
| P2-4 托盘 | 无新增 | 0 | 离线 | hiddenimports 补 `gui.tray_manager` |
| P2-5 自启 | 无新增（winreg 标准库） | 0 | 离线 | hiddenimports 补 `autostart`（根级延迟 import，保险列出） |
| P2-6 纪念日 | 无新增 | 0 | 离线 | 无 |
| P2-7 深色 | 无新增（winreg 标准库） | 0 | 离线 | 无 |

通用：全部新增模块进 spec `hiddenimports`；本版无新增静态资产（datas 无需增）；README「打包」章节需同步 TTS/免提/托盘统一说明；默认产物体积保持 ≈218MB 量级零增量承诺。

---

## 8. 待明确事项（架构层面次要开放项，不阻塞 P1 批开工）

1. **免提关键词清单与「任意输入打断」灵敏度**（Q7 通道 ②③）：识别关键词集合（建议最小集：「暂停」「结束对话」「不说了」）与打断判定阈值需真机标定，先交付界面通道，其余 P2 内补——PM 知情即可。
2. **Idle 问候文案情绪分级**：`idle_return` 文案是否区分"离开时长/时段"（清晨回 vs 深夜回）属产品文案选择，建议先统一模板池，细分配置后续。
3. **小游戏首页入口 vs 仅聊工具区**：默认两处都做，若首页拥挤由 UI 裁一处（产品无硬性要求）。
4. **回忆页相伴信息行口径**：展示「相伴 N 天 · 初见于 M/D」中性行是否连"初见日"一起展示（用户可能对首次相见日敏感），建议默认显示、提供不显示位。
5. **托盘「🎤 语音」语义**：调用主窗聊天面板的单次语音输入框（默认），还是唤起免提（需 P2-2 就绪），建议 v1.3 先用单次输入，免提入口只放面板内。
6. **深色模式首启默认**：theme_mode 默认 light（跟随 PRD），不改旧用户观感；跟随系统仅作为新可选项。

---

## 9. IS_PASS 自审

| 检查项 | 结论 |
|---|---|
| 与 PRD §7（Q1–Q9）一致性 | 通过：9 项默认建议全部采纳并落架构；2 处显式标红微调（D-V13-02 TTS 实现路径走 QtTextToSpeech 而非手写 ctypes COM；D-V13-09 深色最小目标面含少量既有硬编码取色替换）——**不改默认建议结论，只改实现路径/范围，均已写明理由与降级** |
| 与 design-v12 不冲突 | 通过：沿用 D1–D8 架构与 §3.9/§3.10 口径；companion/proactive/theme/托盘均按"既有 API 加方法、白名单加事件、_merge_defaults 加兜底"增量扩展，不推翻 v1.2 任何已交付语义 |
| R-A/R-B/R-C/R-D/R-E/R-F 归零 | R-A：小游戏零计分/后台零加分/回忆与纪念日无计数与倒计时，UI 词表扩扫；R-B：GetLastInputInfo 仅毫秒数、免提仅显式开启且只转文字；R-C：全部主动开口归 A9 调度 + 独立祝福通道受 quiet 约束；R-D：托盘统一判增量级并给一行守卫退避法、closeEvent 改动收窄到生命周期守卫，超纲退最小形态；R-E：数据全本地、TTS 离线；R-F：§7 表逐项 0 新增第三方依赖 |
| 红线区防回归 | closeEvent/quit 编舞是本版**唯一高影响行为变更**，已单独列 P1-3（H 风险）并配降级（回归即退回 X=退出 + 热键呼出聚焦） |
| 任务粒度 | 11 项需求拆为 11 个任务（含 V-0/V-X 整合项），每任务含依赖/产出/风险/负责人建议；P1 批 4 项可并行、P2 批给出串并行次序与汇交点规避——工程师可批量吃下 |

**IS_PASS: YES**（P1 批可开工；2 处标红微调建议 PM 复核后无异议即按本稿执行）。
