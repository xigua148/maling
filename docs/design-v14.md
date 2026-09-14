# 码铃（MaLing）v1.4 增量架构设计与任务分解——「开源玩具盒 × 看得见也能动手」

- 版本：v1.4（基于 v1.3.0 增量，承接 `docs/prd-v14.md` v1.4a 权威需求 + `docs/design-v13.md` v1.3 架构基线）
- 文档状态：架构初稿（供开发排期与实现消费；Q-A1 用户/团队已拍板、Q-A2..Q-B7 按 PRD 默认建议采纳 + 架构复核落法，见 §2）
- 维护人：高见远（架构）
- 输入：`docs/prd-v14.md`（权威需求，方向 A A0–A5 + 方向 B B0–B3 + 红线 R-G/R-H + 7 项待确认）+ `docs/design-v13.md`/`docs/prd-v13.md`（v1.3 基线，D-V13 系列决策、共享知识 11–17、R-A~F 全量沿用）+ 代码实测（`gui/widgets/mini_games.py` / `screen_capture.py` / `camera_capture.py` / `chat_panel.py` / `chat_service.py` / `agent_engine.py` / `agent_tools.py` / `proactive_scheduler.py` / `tray_manager.py` / `system_idle.py` / `gui/config.py` GuiConfig / `gui/main.py` / `gui/app_context.py` / `gui/qt_compat.py` / `gui/pages/page_about.py` / `gui/pages/page_home.py` / `maid_coder_gui.spec`）
- 关联文档：v1.2/v1.3 基线一律沿用不重写；只增量。工作目录仅限 `maling_agent_dev/` 与 `docs/`。
- 修订记录：
  - **v1.4a（2026-09-04）**：初稿。A/B 双线文件域硬分区（吸取 v1.3 P1 同文件双写教训）；Q-A1 局内即时分值豁免裁决落纸；Q-A2..Q-B7 逐条架构落法；R-G/R-H 落法 + A4 许可合规评审清单进任务；B 线与 agent_engine（C 线）关系裁决 = 首版独立非 Agent 工具；番茄钟到点提醒裁决 = 独立用户请求通道（不入 A9 proactive 闸门）。

> **总体红线复述（PRD §2，跨需求强制，实现逐条对照）**：
> R-A 全 UI 无数值/进度/倒计时/断签；**Q-A1 例外已拍板：开源"进程型"游戏局内即时分值允许**（不落盘、无排行/成就/连胜/连对/累计/历史最佳；扫描词扩：排行榜/最高分/连胜/连对）。
> R-B 不监督/不评判；看屏只分析"屏幕内容"、只在显式开启时采集；不做屏幕行为统计/使用报告/时间线（**R-B 同步增补禁屏幕行为统计**）。
> R-C 一切"码铃自发开口"受节流约束；看屏主动提示仅高价值事件、≤1 条/30min、可关、仅对话气泡；番茄到点提醒属用户主动启动的定时完成通知（非打扰推送，仅托盘静默气泡 + 可选 TTS，不做系统级弹窗）。
> R-D 只增量不重构：游戏容器在 `mini_games.py` 上增量扩展，荷官四款零改写；B 线新建模块，ChatService 只做两处**纯增量方法**（见 §3.2），不动用户发送链路骨架。
> R-E 数据纯本地：看屏帧仅内存当轮即弃、不落盘（用户主动"截一张"走既有临时 PNG 例外）；游戏无任何持久化（无排行/无成就/无存档高分局）；番茄钟无成绩持久化。
> R-F 打包友好：A 线纯 Qt 移植零新增依赖；B 线模拟走 ctypes SendInput 零依赖；帧压缩用 QImage/QPixmap 自带，不引 Pillow。
> **R-G（新增）computer-use 轻量版边界**：逐次授权（无会话级/任务级放行）；无自主周期采集/后台自动操作；帧仅内存无跨会话记忆；看屏仅前台开启时采集、关即停采弃帧；键鼠模拟仅当前交互桌面、不做无障碍/UIA/进程注入/远程桌面。
> **R-H（新增）开源许可合规**：只收 MIT/Apache-2.0/BSD-3/BSD-2/0BSD/CC0；禁 GPL/AGPL/LGPL/SSPL；PyQt 写的源码只看仓库自身许可（移植进 PySide6 合法）；每项目保留原版权头 + `docs/THIRD_PARTY.md` + About 页「开源组件」；实施前以仓库实际 LICENSE 文件复核（PRD 调研为初审）。

---

## 1. 增量范围（对照 PRD §1/§3/§4，简列）

| 线 | ID | 需求 | 一句话承接 | 架构归属 |
|---|---|---|---|---|
| A | A0 | P0 · 游戏角容器升级 | `mini_games.py` 增量容纳复杂交互 QWidget 游戏，荷官四款原样共存 | §2.1 D-V14-01 / §3.1 / §5 A0 |
| A | A1 | P0 · 内置 2048 | tangentecode/2048-pyqt6（MIT）→ PySide6 单文件 widget；局内分值豁免 | §2.1 D-V14-02 / §5 A1 |
| A | A2 | P0 · 内置扫雷 | dawsonbooth/pynsweeper（MIT）→ PySide6 widget；去 XP 皮/计时排行，留剩雷数/标旗 | §2.1 D-V14-03 / §5 A2 |
| A | A3 | P1 · 番茄钟「她陪你专注」 | 独立小组件；到点提醒 = 用户请求的定时通知（独立通道，不入 A9 闸） | §2.2 D-V14-04~06 / §5 A3 |
| A | A4 | P1 · 许可合规与第三方归属 | THIRD_PARTY.md + About 开源组件 + 原版权头保留 + 评审清单 | §6 共享知识 19 / §5 A4 |
| A | A5 | P2 · 扩充候选池 | 自制优先登记候选，非承诺；本版只留文档 + 可选自制贪吃蛇 | §5 A5 |
| B | B0 | P0 · 视觉模型前提与降级 | `vision_support.py` 启发式探测 + 开启引导，不静默失败 | §2.4 D-V14-08 / §5 B0 |
| B | B1 | P0 · 持续看屏 | ScreenWatchService 周期帧/显著变化触发/即时一帧 + chip + 成本护栏 + 高价值提示节流 | §2.4 D-V14-07/09/10 / §5 B1a/B1b |
| B | B2 | P1 · GUI 单步操作 | 独立 ComputerUseController；逐次授权增强弹窗；ctypes SendInput | §2.5 D-V14-11~13 / §5 B2 |
| B | B3 | P1 · 看屏统一底座 | `screen_grab.py` 抽取 + 帧 diff + 坐标/DPR 对齐 + 与 screen_capture 职责边界 | §2.3 D-V14-07 / §5 B3 |
| 收口 | — | DoD/红线扫描/打包 | A-14 式红线扫描（词表扩）+ py_compile + 打包零增量 + 升版 | §5 V-1.4-X |

> 优先级口径沿用：P0 = 本线必达 / P1 = 目标内应交付 / P2 = 排期靠后。v1.4 交付承诺 = A0/A1/A2/A4 + B0/B1 + 首版 B2（click+type 保底，见 D-V14-14）；A3 为 P1（与 B 线排期冲突可降 P2，需 PM 知情）；A5 为 P2 候选不承诺。

---

## 2. 关键架构决策

> 主理人/团队已拍板项（不再讨论，直接落纸）：Q-A1 允许局内分值（硬约束）；Q-A2..Q-B7 全按 PRD 默认建议采纳。架构在默认建议之上给出的**实现路径落法**标红说明，不静默推翻任何拍板结论。

### 决策总览

| 编号 | 对应 | 结论（一句话） | 风险级 |
|---|---|---|---|
| D-V14-01 | Q-A2 / A0 | `mini_games.py` 容器化 = 右侧区改 QStackedWidget 双页（荷官日志页原样 + widget 游戏页注册挂载），左列按钮组从游戏注册表生成；荷官四款零改写 | 中 |
| D-V14-02 | Q-A1 / A1 | 2048 局内分值允许显示（「当前得分」标签）；不落盘/无最佳/无排行/无连胜；每局清零 | 低 |
| D-V14-03 | A2 | 扫雷保留剩雷数 + 右键标旗，去计时与胜利记录；无任何分/时间表 | 低 |
| D-V14-04 | Q-A3 / A3 | 番茄钟入 v1.4（P1）；控制器 app 级单例 + 无状态浮窗视图；**不做**成绩/统计/连续天数 | 低~中 |
| D-V14-05 | Q-A3 / A3 | 番茄到点提醒 = **独立用户请求通道**，不入 A9 proactive 四重闸（免打扰/每日上限/冷却均不适用）；仅托盘静默气泡 + 可选 TTS | 中（语义澄清） |
| D-V14-06 | A3 | 专注开始/结束接 companion 轻量事件仅经 `companion_bridge.note_activity`（focus 短暂活动态），不写 event_log/不碰 intimacy/不落盘 | 低 |
| D-V14-07 | Q-B1/Q-B3/B3 | 新 `gui/screen_grab.py` 纯函数屏抓共享底座（从 screen_capture 抽取，非新建第二套）；ScreenWatchService 消费；screen_capture.py 保留对话框职责并委托抽取函数 | 中（P1-2 已有代码小改） |
| D-V14-08 | Q-B0/B0 | 视觉前提 = 模型名启发式探测（best-effort）+ 开启引导 + 沿用 API 失败的可读报错兜底；不静默失败 | 低 |
| D-V14-09 | Q-B1 | 采集策略 = 30s 间隔 + 显著变化（帧差比阈值）立即触发 + 「现在看一下」即时单帧；帧仅内存 data URI，不落盘 | 中 |
| D-V14-10 | Q-B2/Q-B3 | 高价值事件主动提示 = 显著变化帧做低成本"是否有报错/异常弹窗"分类（≤1 次/90s 且仅显著变化帧）+ 命中后节流 ≤1 条/30min + 可关；成本可见 = 开启确认 + chip「已分析 N 帧 · ≈xk」+ 单会话帧上限自动暂停 | 中~高 |
| D-V14-11 | Q-B4/B2 | B2 独立 ComputerUseController，**不做 Agent 工具、不进 AgentEngine**（理由见 §2.5） | 高（边界裁决） |
| D-V14-12 | Q-B4/B2 | 授权 = 新专用信号/对话框（区域缩略截图 + 动作 + 坐标 + type 明文预览 + 敏感语义红字），仅「允许这一次 / 拒绝」，无会话级放行；独立于 Agent `agent_authorization_requested` | 高 |
| D-V14-13 | Q-B5/Q-B6 | 模拟 = ctypes SendInput/mouse_event/SetCursorPos（零依赖）；type 用 SendInput KEYEVENTF_UNICODE；敏感词红字提示、不做内容黑名单、不记录任何键鼠输入 | 中~高 |
| D-V14-14 | Q-B7/B2 | B 线两段式：B1 先行、B2 紧随；B2 首版动作 = click + double + right + type + hotkey，scroll/拖拽 P2；若资源紧可只留 click+type | 高 |

---

### 2.1 方向 A · 游戏角容器化 + 2048/扫雷内置（A0/A1/A2）

**现状核实（mini_games.py 386 行）**：`MiniGamesDialog(QDialog, modal=False)` 左右布局——左列 150px 固定 4 枚荷官选择钮（`miniGamePickBtn` checkable），右侧 = `QTextEdit` 台面日志 + 底部可重建动作行（`_build_actions` 清空重放）；四游戏纯 random、零 LLM、`_react()` 走 `companion.react_to_game_result`（30min 冷却）；对话框 620×480。入口在 `chat_panel._open_mini_games`（工具行「🎲 小游戏」）。

**D-V14-01 · A0 容器化落法（增量，不推翻荷官四款）**：

1. `_build_ui` 右侧内容区改为一个 `QStackedWidget`：
   - **page 0 = 荷官台**：现有 `QTextEdit` + 动作行原样搬入（视觉/逻辑零改动）；
   - **page N（≥1） = 复杂游戏挂载页**：每个注册的 widget 游戏一个独立页面，游戏 QWidget 直接 add 到其页面布局；**懒创建**（首次选中该游戏才实例化，避免启动成本与后台空转）。
2. 左列按钮改为从注册表生成：`gui/widgets/games/__init__.py` 提供 `GAME_DEFS`（`(gid, label, tip, kind, factory)`，kind ∈ `dealer`/`widget`）；荷官四款作为 `kind="dealer"` 的伪注册项保留在 `mini_games.py` 内部清单首部（按钮顺序与旧版一致 = 荷官四款在上、复杂游戏分组在下，分组用一行只读小标题「· 来找码铃玩点别的 ·」，取 `theme_color`）。
3. `_pick_game(gid)`：`dealer` → 切 page0 + 走**既有**分支逻辑（`_build_actions` 等一行不改）；`widget` → 切对应页 + `factory` 懒建 + `setFocusPolicy(StrongFocus)` + `setFocus()`（键盘可达，见下）。
4. 主题：对话框壳/左列/分组标题一律 `theme_color()`；游戏自身版面见 D-V14-02/03。
5. 关闭语义不变：Esc/外部 close 正常关闭对话框（非 modal，随主窗生命周期）。
6. 底部无数值说明行改为中性文案「游戏结果只留在这张小桌上，不记分账、不排行，随时可玩~」（荷官行保留；widget 页底由游戏自身放等价说明）。

**A 线窗口尺寸**：`setMinimumSize` 提至约 660×520、默认 resize 720×560（复杂游戏需要更大网格面），荷官页在更宽面上自适应（QTextEdit Expanding，零回归风险）。

**2048（A1，D-V14-02）**：来源 tangentecode/2048-pyqt6（MIT，PyQt6，src 单层）。移植为 `gui/widgets/games/game_2048.py`：
- **玩法核心完整保留**：4×4 网格、WASD/方向键移动合并、随机出块、合成到 2048 = 本局达成（展示一句庆祝台词）。
- **局内即时分值豁免（Q-A1 硬约束落点）**：界面只保留「当前得分」单值标签（随当场合成即时累加）；**无**最高分/历史/排行榜/连胜/连对/「再来一局超越上次」类文案；每次开局清零；**绝不落盘、绝不持久化**（无 best.json、无 companion 键）。计数数值仅存在于该 QWidget 实例内存。
- **输入**：`keyPressEvent` 处理方向键 + WASD；对话框不消费方向键（QDialog 无默认方向键处理，Esc 默认 reject 保留）。无触屏滑动手势（首版仅键盘，触屏 P2，见 §8）。
- 换肤：窗口/底板/文字取 `theme_color`；数字瓦片使用 2048 经典中性瓦片色（**游戏内容色，独立于主题色板**，见共享知识 23 的裁定说明）。
- 状态信号：`score_changed(int)` / `outcome(str)`（`"reach_2048"` | `"stuck"`）。**本版不接 A9 情绪**（D-V14 裁定：2048 结束语义中性，`react_to_game_result` 是输/赢情绪叙事，硬接会在每次"僵局结束"误触发情绪反馈，语义噪音 > 陪伴价值）；仅选中游戏时给一句荷官开场白（对话框侧 `_say` 或游戏内 dealer 行可选）。留 `dealer_line(str)` 扩展位。

**扫雷（A2，D-V14-03）**：来源 dawsonbooth/pynsweeper（MIT，PyQt5，`src/` 多文件）。移植为 `gui/widgets/games/game_minesweeper.py`：
- 经典规则保留：网格点开/右键标旗/胜利判定；**保留操作必需信息 = 剩余雷数 + 右键标旗**。
- **裁剪**：去掉 XP 复古皮/计时器/胜利记录/排行榜；无任何分值与时间呈现（天然零养成）。
- 默认难度初局 9×9/10 雷；首版不做难度切换（P2）。右键标旗在 QWidget 单元上经 mousePressEvent RightButton 处理。
- 换肤：棋盘底/单元格边框/数字用 theme 键 + 内容中性色（同 2048 裁定）。
- 状态信号：`flags_changed(int)` / `outcome(str)`（`"win"` | `"lose"`）。**A9 情绪联动默认接 `lose`/`win` → 对话框 `_react("win"/"lose")`（走 30min 冷却，无计分）**——扫雷胜负有明确方向，情绪叙事不违和；若评审嫌"踩雷即安慰"过频，可仅接 win（一行开关，见 §8）。play 本身不受冷却限制。

**Q-A1 红线扫描落地（重要）**：R-A 扫描词表扩 `排行榜/最高分/连胜/连对/纪录/成就/历史最佳`；"得分/剩余雷数"等**局内必需词**只允许出现在 `gui/widgets/games/` 域（扫描白名单路径），其余 UI 仍禁「分数/得分/计时」等养成词（QA 扫描任务落实，见 §6 共享知识 23）。

**键盘与对话框冲突规避**：游戏 widget `setFocusPolicy(Qt.StrongFocus)`；切换游戏时 `_pick_game` 后 `setFocus()`；荷官页有 QTextEdit 时点回左列按钮天然转移焦点，无冲突；游戏运行中不弹任何第二 modal。

---

### 2.2 方向 A · 番茄钟「她陪你专注」（A3）

**范围收窄（严格 v1.2 A10 口径）**：只做"专注计时骨架"——阶段（专注/休息）、时长可调（默认 25/5）、开始/暂停/重置、当前番茄剩余倒计时显示、到点提醒。**不做**成绩/统计图/专注评分/连续天数/完成 N 轮成就/任何历史累计。参考 Wenlin-AI/Pomodoro-timer（MIT）仅借鉴计时交互形态；**实现为码铃自制轻量组件，不整库移植**（去 pygame/去 Obsidian/去 session 历史文件），故许可面最小（A4 是否登记该参考源见 §2.6）。

**D-V14-04 · 模块结构（app 级单例 + 无状态视图）**：
- `gui/pomodoro.py`：`PomodoroController(QObject)` app 级单例（QTimer 1s tick；状态 `idle→focus→break→idle`，断点暂停）。专注结束 → 自动进入休息并提醒；休息结束 → 回 idle **不自动连班**（"想继续随时再按"文案，避免自律/打卡感，R-A）。随 app 退出即停（无后台持久计时）。
- `gui/widgets/pomodoro_dialog.py`：`PomodoroDialog(QDialog, modal=False)` 视图——大字剩余时间 + 阶段名 + 开始/暂停/重置 + 简短中性说明「到点只轻轻提醒，不记成绩」。关闭 = 隐藏，计时继续（controller 持有状态）；再开恢复显示。
- 入口（默认）：首页 `page_home.QUICK_ACTIONS` 增 `("pomodoro","专注","🍅","25 分钟番茄钟，她陪你专注","pomodoro")` + handler；托盘 `tray_manager` 菜单增「🍅 专注」动作。**聊天工具行不加入口**（把 `chat_panel.py` 完全让给 B 线，避免 A/B 双写，见 §3.3）。

**D-V14-05 · 到点提醒通道裁决（独立通道，不入 proactive 闸门）**：番茄到点是**用户主动启动**的定时器完成通知，语义上等于闹钟/计时器，不是"码铃自发开口"，与 A9 scheduler 的 `enabled/quiet/daily_cap/cooldown` 四重闸**不兼容**——若并入 A9，用户在免打扰窗（22:30–08:00）内专注学习会因 quiet 收不到自己的到点提醒，产品语义荒谬。裁决：
- 提醒走 **PomodoroController 自己的投递**：优先 `TrayManager.notify_maid(title, text)`（新加方法，A4 域）；托盘不可用 → 主窗可见则状态栏一行；两者皆无则不打扰。**无系统级弹窗**（R-C）。
- 可选语音：`app_ctx.tts.speak` 一句（守卫 `tts_enabled`/可用；默认开，GuiConfig `pomodoro_tts`）。demo 模式（无 key）时 TTS 无回复文本可读但本提示可读，允许（系统本地 SAPI 不依赖 key）。
- **不写 proactive 计数器、不占 A9 配额、不受 quiet 约束**——与纪念日"独立配额通道"同源但更彻底：连 scheduler 都不经过（不新起 scheduler 场景，避免四重闸语义污染）。

**D-V14-06 · companion 轻量事件**：专注开始 → `companion_bridge.note_activity("focus")`；到点/结束 → `note_activity(None)`（活动态回落）。只走既有 activity 广播（首页/宠物/气泡表情联动），**不 ingest_event、不加 companion.json 键、不碰 intimacy**（无任何成绩痕迹）。

配置键：`pomodoro_work_min`(25)/`pomodoro_break_min`(5)/`pomodoro_tts`(True) 入 GuiConfig（§4），时长在对话框内可调并存盘。

---

### 2.3 方向 B · 看屏统一底座（B3）

**现状核实**：`screen_capture.py` 里 `ScreenCaptureDialog._capture_desktop`（合成多屏 grabWindow + 主屏 DPR 基准 + 虚拟桌面并集）是现成可复用屏抓逻辑，但**私有在对话框内**；P1-2 已知边界：混合 DPR（各屏缩放不同）下选区边缘可能偏差 ≤ 一屏 DPR 差。摄像头/托盘等临时文件先例 = `camera_capture.py`。

**D-V14-07 · `gui/screen_grab.py`（纯函数共享底座，非第二套截屏）**：
- `CaptureResult` dataclass：`{pixmap: QPixmap, virtual_rect: QRect, dpr: float}`（沿用 screen_capture 的"主屏 DPR 基准合成"，混合 DPR 已知边界一并继承并在此强化记录）。
- `grab_virtual_desktop() -> Optional[CaptureResult]`：从 `ScreenCaptureDialog._capture_desktop` **抽取**（方法体搬移 + 少量命名调整），对话框改为委托调用（失败仍走原 try 守卫）。**行为等价，offscreen/真机回归各一次**。
- 帧处理工具（纯函数，内存链）：
  - `pixmap_to_jpeg_bytes(pm, max_width=1568, quality=82) -> Optional[bytes]`（QImage 等比缩放 → QBuffer 存 JPG；JPEG 失败回落 PNG），再 `base64 → data URI`（复用 chat_service 既有多模态 content 格式）；
  - `frame_changed_ratio(a: QImage, b: QImage, thumb=96) -> float`：缩略灰度逐字节差比 0..1（`memoryview`/`bytes` 比较，不引 numpy/Pillow）；
  - `crop_region(pm, center_logical_xy, w=280, h=180) -> QPixmap`（B2 授权缩略图用，坐标 DPR 换算见共享知识 22）。
- **与 screen_capture.py 职责边界（R-D 关键）**：screen_capture = 用户手动选区对话框（产物 = 临时 PNG 进附件条，属 R-E "用户主动截一张"例外）；screen_grab + ScreenWatchService = 用户显式开启的持续模式内存帧服务（产物 = 内存 data URI，不落盘）。两者经 `screen_grab` 共享底层屏抓函数，**不重造**。

**ScreenWatchService（B1a 核心，见 §5）职责**：app 级单例 QObject；持 QTimer（间隔=GuiConfig `screen_watch_interval_s`，默认 30s）；tick → grab → 与上次帧 diff → `changed_ratio > screen_watch_change_threshold(默认 0.04)` 才触发分析链；分析帧数计数 + token 累计（从视觉调用 usage 回读）；单会话帧上限（默认 200）达限 → 自动暂停 + 一次气泡说明；关闭即弃内存帧。坐标：逻辑虚拟桌面坐标 + 命中屏幕 DPR → 物理像素（click 命中准确性关键，见共享知识 22）。

---

### 2.4 方向 B · 持续看屏 B1 + 视觉前提 B0

**D-V14-08 · B0 视觉前提（不静默失败）**：现状 `gui` 无任何模型视觉能力前置探测（看图失败走 API 报错 → 可读引导，chat_service.py:280-287 已存在）。B 线新增 `gui/vision_support.py`：
- `heuristic_supports_vision(model_name) -> Optional[bool]`：模型名含 `4v/vl/vision/gpt-4o` 等视觉标记 → True；含 `deepseek`（官方纯文本）等已知纯文本 → False；其余 → None（不确定）。**best-effort，非权威**；权威仍以 API 实际回包为准（既有可读报错兜底保留，不静默）。
- `vision_guidance_text() -> str`：复用 README 既有多厂商视觉端点口径（智谱 GLM-4V / 通义 qwen-vl / OpenAI GPT-4o / 若 deepseek-v4-flash-vision-exp 可用则补厂商预设说明）。
- 开启看屏确认弹窗 = 成本说明 + 若启发式命中纯文本则红字引导"当前模型不支持看图，建议先切换视觉模型"（**仍允许开启**，防启发式误杀自定义视觉模型）；模型配置面板厂商预设说明同步（README 表 + `model_config_panel` 备注，B0 域）。

**B1 交互闭环（D-V14-09/10）**：
- 快捷开关：聊天工具行「👀 看屏」checkable（默认关）；设置页新增「视觉·看屏」区（同一 GuiConfig 真值）。
- 开启：**确认弹窗一次**（说明：周期查看屏幕提供帮助、消耗额外 token、可随时关闭、不落盘、不做行为统计）；通过后聊天面板消息区上方出现**常驻 chip「👀 码铃在看」**（`gui/widgets/screen_watch_bar.py`，仿 handsfree_bar 状态条先例）：`👀 码铃在看 · 本会话已分析 N 帧 · ≈xk tokens`（可折叠细账）+ 「📷 看一帧」即时采集按钮 + 「🔍 按当前屏提问」+ 「✕ 关闭」（关即停采弃帧）。
- 被动解释：看屏期间用户正常提问，**启发式命中**（文本含 屏幕/这/那个/报错/弹窗/界面/怎么点 等指向当前屏的意图词）且无本图附件 → 面板在发送前把最近帧作为**内存 data URI 合成附件**附上（ChatService 附件链加 `uri` 通道，见 §3.2）。**非命中不附帧**（防每轮烧 token）。「🔍 按当前屏提问」按钮 = 命中标记，最可靠。
- 主动提示（高价值事件，R-C）：每显著变化帧（且距上次分类 ≥90s）做一次低成本"是否有报错/崩溃/异常弹窗"分类（视觉小调用，system 固定只让回 yes/no + 一句摘要）；命中 → 生成一句提示气泡；**节流 ≤1 条/30min**（内存时间戳，随 app 生命周期）+ 设置 `screen_watch_notice_enabled` 可关 + **仅对话气泡**（专用信号，托盘不 toast，见 §3.2）。
- 「看一帧」即时分析 → 结果以**对话气泡**呈现（scene=`screen_peek`）。
- 成本护栏：开启确认 + chip 帧/token 累计 + `screen_watch_frame_limit` 达限自动暂停（气泡提示续开）。token 口径：帧数 = 已送视觉调用的帧数；token = 累计 usage.total_tokens（复用 API `_last_stream_usage` 口径，只在本会话 chip 累计展示，不逐条、不落盘）。

**帧内存链**：grab → 内存 QPixmap → data URI（≤8MB/视觉格式）→ 送既有 content 数组；每次仅保留最近一帧 + 其缩略图（授权预览复用）；关闭/暂停/单例销毁 → 置 None（R-E/R-G 可自动化断言无缓存文件）。

---

### 2.5 方向 B · GUI 单步操作 B2（computer-use 轻量版）

**D-V14-11 · 与 agent_engine（C 线）关系裁决 = 首版独立，不做 Agent 工具**，理由：
1. R-G 粒度是**逐次授权、无会话级放行**；而 C 线 `agent_tools.authorize()` 对通过 confirm 的工具做**会话级缓存放行**（agent_tools.py:47-84 `_session_allowed` 语义），语义直接冲突；
2. Agent 工具循环 = "自主连续执行到任务完成"（max_steps 循环），与 v1.4 Non-goal「不做任务级自由操作」在诱导模型连续调用上边界模糊，逐动作打断需在循环内插桩，改造量大且风险高；
3. B2 是一次用户请求 → 一次意图产出 → 一次授权 → 一次执行，不需要 planner/历史/重试；独立 controller 更简单、可离线单测（无 LLM 时拒绝执行）。
**扩展口**：若未来要把"看屏理解"作为只读 Agent 工具（如 `look_at`），留 `ScreenWatchService.latest_frame_data_uri()` 公共取帧口（v1.4 不接）。

**触发链路（用户触发单步）**：`gui/widgets/chat_panel.py` 工具行「🖱 操作」checkable（B 线独占文件内新增，紧邻 Agent 开关先例）。开启后用户**下一条消息**被路由到 ComputerUseController（用户气泡照常由 UI 直插渲染，处理状态走一条细状态行）；流程：
1. 取帧：看屏开启 → 复用最近帧；未开 → **一次性显式抓帧**（用户触发，内存即弃，R-E 例外，不等同开启看屏）；
2. 意图产出：后台 worker（QThread，复用 `app_ctx.api` 非流式）发一条多模态（系统提示 + 帧 + 用户原话），**要求模型只输出严格 JSON 动作意图**（schema 见下），不使用 function calling（避免依赖厂商工具调用支持）；
3. 解析校验：`{type, description, x?, y?, text?, keys?, confidence}`；type ∈ `click/double_click/right_click/type/hotkey`（白名单，其余拒绝）；置信 <0.55 或字段非法/缺坐标 → **先问不乱点**（气泡「码铃不太确定要点的位置…请说得再具体些」并结束，不发授权、不执行）；
4. **逐次授权增强弹窗**（D-V14-12）：`gui/widgets/authorize_action_dialog.py` `AuthorizeActionDialog(QDialog, modal=True)`——动作类型中文 + 目标逻辑坐标 `(x,y)` + 该点周边 280×180 区域缩略截图（来自当前帧 crop）+ type 动作**明文预览将输入文本** + 敏感语义命中（password/key/secret/密码/密钥/卡号等）额外**红字警告条**（诚实提示，**不做内容黑名单**，Q-B6）；按钮仅「允许这一次 / 拒绝」；**不提供**「本次会话都允许」（与 Agent 授权弹窗样式同源但语义更强，文案明示"仅这一次"）；拒绝 → 尊重结果、不重试、不强推（气泡一句「好的，码铃不动啦」）。
5. 执行：ctypes SendInput（D-V14-13，`gui/input_sim.py`）：click/double/right = `SetCursorPos(物理像素)` + `mouse_event(DOWN/UP)`；type = 逐字符 `SendInput KEYEVENTF_UNICODE`（支持 CJK）；hotkey = 修饰键 + VK（最小映射表：字母/数字/F1-F12/Ctrl/Alt/Shift/Win + 常用组合，白名单内）。坐标换算：模型返回的 (x,y) 是**图像像素坐标**（图像 = 完整虚拟桌面逻辑图缩放而来），→ 反缩放为逻辑虚拟桌面坐标 → 命中屏幕的 DPR → 物理像素（共享知识 22 公式；混合 DPR 为已知边界，真机标定）。
6. 反馈：执行成功 → `ChatService.screen_bubble` 一条「已帮你点了 (x,y) 的『确定』」/「已输入」等（scene=`computer_action`）；拒绝/失败同理一条。**不做任何键鼠记录/输入日志**。

**授权弹窗独立性**：新起专用信号链（见 §3.2 ChatService 信号），**不动** `agent_authorization_requested` 既有 QMessageBox 样式与语义（R-D）。

**降级/守卫**：无视觉模型/API 失败 → 可读气泡，不执行；ctypes 调用异常 → 气泡提示不执行；`hotkey/type` 白名单外 → 拒绝；对话框超时未响应（如 120s）→ 按拒绝（fail-safe，同 C 线授权桥口径）。

---

### 2.6 许可合规（A4）落法

- 已拍板：R-H 白名单 = MIT/Apache-2.0/BSD-3/BSD-2/0BSD/CC0；禁 GPL/AGPL/LGPL/SSPL；PyQt 源看仓库自身许可。
- 实施流程：**任何候选 clone 前架构复核仓库实际 LICENSE 文件**（PRD §6 为初审，不以此放行）→ 过评审清单（共享知识 19）→ 通过才允许 A1/A2 工程落地。
- 2048 / 扫雷移植文件头保留原 MIT 版权行（照抄仓库原文 year+author），下方加码铃移植说明块；参考源（如番茄钟仅借鉴形态不搬码）按需登记为"参考未采用"行。
- `docs/THIRD_PARTY.md` 新增登记结构（每项目行：名称/仓库/commit 或版本/许可/原版权行/改动摘要/复核日期/复核人）；`docs/third_party_licenses/<proj>.txt` 存放第三方 LICENSE 全文副本（MIT 合规需在分发副本中包含声明）。
- About 页（`gui/pages/page_about.py`，A 线独占）「开源组件」卡片：列出 2048/扫雷（+ 若借鉴番茄钟形态则说明）名称、仓库链接、许可简称；现有"第三方依赖 PySide6(LGPL)…"行保留在其上。

---

## 3. 模块 / 文件清单（A 线与 B 线文件域硬分区）

> **防双写铁律（吸取 v1.3 P1 同文件双写教训）**：A 线工程师只写"§3.1 A 域"文件；B 线只写"§3.1 B 域"文件；**汇交点（§3.2 共享文件）全部预留在 V-1.4-0 一次性编好（配置键/主窗挂载钩子/spec hiddenimports/qt_compat 补类）**，此后两线不得再改，杜绝并行期同文件互踩。唯一例外 = `chat_panel.py`（B 线独占）与 `page_settings.py`（B 线独占），A3 不新增聊天工具行/设置项（见 D-V14-04），故 A 线完全不需要碰这两个文件。

### 3.1 新增 / 修改文件（按域）

**A 线独占文件（软件工程师 A）**：

| 路径 | 一句话职责 | 对应需求 | 类型 |
|---|---|---|---|
| `gui/widgets/games/__init__.py` | 游戏注册表 `GAME_DEFS` + widget 契约（`dealer_line/score_changed/outcome` 约定） | A0 | 新增 |
| `gui/widgets/games/game_2048.py` | 2048 单文件 widget（PySide6 移植，MIT 头保留，局内得分豁免） | A1 | 新增 |
| `gui/widgets/games/game_minesweeper.py` | 扫雷单文件 widget（去皮/去计时排行，留剩雷数与标旗） | A2 | 新增 |
| `gui/widgets/mini_games.py` | 容器化：QStackedWidget 双页 + 注册表驱动左列 + 荷官四款零改写 | A0 | 修改 |
| `gui/pomodoro.py` | PomodoroController app 级单例（状态机 + 到点提醒独立投递 + companion 轻事件） | A3 | 新增 |
| `gui/widgets/pomodoro_dialog.py` | 番茄钟视图（大字倒计时 + 开始/暂停/重置 + 中性说明） | A3 | 新增 |
| `gui/pages/page_home.py` | `QUICK_ACTIONS` 增「🍅 专注」+ handler（打开/聚焦 PomodoroDialog） | A3 | 修改 |
| `gui/tray_manager.py` | 增「🍅 专注」菜单动作 + `notify_maid(title,text)` 通用静默气泡方法（A9/A3 提醒复用，不接 proactive_message 语义） | A3/A4 | 修改 |
| `docs/THIRD_PARTY.md` | 第三方归属登记 + 原版权行与改动摘要 + 复核状态 | A4 | 新增 |
| `docs/third_party_licenses/` | 第三方 LICENSE 全文副本（2048/扫雷；番茄钟按需） | A4 | 新增 |
| `gui/pages/page_about.py` | 「开源组件」卡片（第三方内置列表 + 仓库链接 + 许可） | A4 | 修改 |

**B 线独占文件（软件工程师 B）**：

| 路径 | 一句话职责 | 对应需求 | 类型 |
|---|---|---|---|
| `gui/screen_grab.py` | 屏抓共享底座：`grab_virtual_desktop` + JPG/data URI + 帧差比 + 区域 crop | B3 | 新增 |
| `gui/screen_watch.py` | ScreenWatchService：周期帧/diff/计数/token/帧上限自停/高价值分类节流/帧内存链/取帧口 | B1/B3 | 新增 |
| `gui/vision_support.py` | 视觉模型启发式探测 + 引导文案 + 分类/意图 worker（QThread 视觉小调用） | B0/B1/B2 | 新增 |
| `gui/widgets/screen_watch_bar.py` | 常驻 chip「👀 码铃在看」（N 帧 · ≈xk + 看一帧 + 按屏提问 + ✕） | B1 | 新增 |
| `gui/input_sim.py` | ctypes SendInput/mouse_event 执行器（click/double/right/type/hotkey，坐标换算） | B2 | 新增 |
| `gui/computer_use.py` | ComputerUseController：意图解析/校验/授权编排/执行/反馈闭环 | B2 | 新增 |
| `gui/widgets/authorize_action_dialog.py` | 逐次授权增强弹窗（区域缩略 + 动作/坐标 + type 明文 + 敏感红字；仅这一次/拒绝） | B2 | 新增 |
| `gui/widgets/chat_panel.py` | 「👀 看屏」「🖱 操作」快捷钮 + chip 注入 + 操作路由 + 按屏提问标记（**B 线独占**） | B1/B2 | 修改 |
| `gui/pages/page_settings.py` | 新「视觉·看屏」区（开关/频率/帧上限/提示开关/视觉模型引导） | B0/B1 | 修改 |
| `gui/widgets/screen_capture.py` | `_capture_desktop` 委托 `screen_grab.grab_virtual_desktop`（行为等价回归） | B3 | 修改 |

**B 线专属 ChatService 纯增量（§2.5/B1 渲染与帧注入依赖）**：
- 附件链 `_image_attachments_to_data_uris` 支持 `uri` 键（内存 data URI 直传，跳过文件读；保留 path 旧通道兼容）——用户按屏提问发帧用；
- 新方法 `screen_bubble(text, scene)`：写一条 assistant 会话气泡（meta.screen=True）+ 发**新信号 `screen_bubble_ready(str,str)`**（托盘/chat_window 不订阅，故不 toast）；渲染仍走 `gui_session.message_added` 单入口，**无双气泡风险**；
- `proactive_ask` 与用户发送链路**均不改语义**（R-D）。

### 3.2 汇交点文件（V-1.4-0 预编，两线随后只读）

| 文件 | 预编内容 | 风险级 |
|---|---|---|
| `gui/config.py`（GuiConfig） | 一次性补 §4 全部新键（A 线 pomodoro_* + B 线 screen_watch_*）+ `save()` 收录；两线代码只 `getattr`/属性读，不再编辑 | 低 |
| `gui/main.py` | 预置 `_mount_v14_services(app, app_ctx)`（主窗显示后调用）：内部两条守卫式 helper `_mount_v14_b_screen`（懒 import screen_watch 等，B 模块未创建则 try 记日志不阻断）与 `_mount_v14_a_services`（懒挂 pomodoro 单例）+ `quit` 生命周期卫生列表补 `screen_watch.stop`；main() 在 `_mount_v13_services` 后调用。**此后 A/B 均不再改 main.py** | 中 |
| `maid_coder_gui.spec` | hiddenimports 一次性补 A 域：`gui.pomodoro`/`gui.widgets.pomodoro_dialog`/`gui.widgets.games`/`gui.widgets.games.game_2048`/`gui.widgets.games.game_minesweeper`；B 域：`gui.screen_grab`/`gui.screen_watch`/`gui.vision_support`/`gui.computer_use`/`gui.input_sim`/`gui.widgets.screen_watch_bar`/`gui.widgets.authorize_action_dialog` | 低 |
| `gui/qt_compat.py` | 一次性补 `QImage/QBuffer/QByteArray/QImageWriter`（screen_grab 帧压缩与 games 绘板需要），此后两线不再编辑（新代码只允许用 qt_compat 已导出名或模块内 from PySide6 直引必需类） | 低 |
| `config.yaml` 模板（gui/main.py 默认配置字串） | **无新增键**（screen_watch/pomodoro 全是 GuiConfig 域，不进 AppConfig/config.yaml；`core/__init__.py` AppConfig 本版零改动） | 低 |

> A/B 双线从 V-1.4-0 后即**文件域不相交**，可全程并行；`chat_panel.py`/`page_settings.py` 虽被多人读取参考，但写方仅 B 线一人，天然无双写。游戏信号接 A9 情绪若后续要接线，也只落在 A 域 mini_games.py/games，不触 B 文件。

---

## 4. 数据结构

> 本版 **AppConfig / config.yaml 零新增**（screen_watch 与 pomodoro 均为 GUI 偏好，归 GuiConfig）；**companion.json 零新增键**；新增无任何持久化状态文件（帧不落盘、游戏无存档、番茄钟无成绩）。

### 4.1 GuiConfig 新增（`gui/config.py`，V-1.4-0 预编）

| 字段 | 类型/默认 | 语义 | 域 |
|---|---|---|---|
| `screen_watch_enabled` | bool False | 持续看屏总开关（设置区与快捷钮同一真值；开启经确认弹窗） | B |
| `screen_watch_interval_s` | int 30 | 周期采集间隔秒（30/15 可配，见 Q-B1 备选） | B |
| `screen_watch_frame_limit` | int 200 | 单会话已分析帧上限，达限自动暂停并提示续开 | B |
| `screen_watch_notice_enabled` | bool True | 高价值事件主动提示总开关（R-C 可关） | B |
| `pomodoro_work_min` | int 25 | 专注时长（对话框可调） | A |
| `pomodoro_break_min` | int 5 | 休息时长 | A |
| `pomodoro_tts` | bool True | 到点可选语音（受 `tts_enabled` 与可用性双守卫） | A |

> 运行态非持久项（内存）：screen_watch 当前帧 data URI / 本会话帧计数 / token 累计 / 高价值提示上次时间戳 / 帧上限已达标记；pomodoro 当前阶段与剩余秒 —— 均随 app 生命周期，不落盘。

---

## 5. 任务分解列表

> 批内标注可并行项；文件域规则见 §3。**并发模型**：V-1.4-0 单人串行 → 之后 A 线（工程师 A：A0→A1/A2→A3→A4 收口）与 B 线（工程师 B：B3/B0→B1a→B1b→B2）**两路全程并行**；能力富余可让工程师 B 在 B1a 后分流 B0/B2 细任务串行推进。每个任务完成后 `py_compile` 绿。

### 5.1 V-1.4-0 · 基线接线（串行，架构/主程）

| 任务 | 依赖 | 产出文件 | 范围 | 风险 |
|---|---|---|---|---|
| V-1.4-0 | — | gui/config.py（§4.1 全键 + save）、gui/main.py（`_mount_v14_services` + 两条守卫 helper + quit 卫生补 screen_watch.stop）、maid_coder_gui.spec（§3.2 hiddenimports 全量）、gui/qt_compat.py（QImage/QBuffer/QByteArray/QImageWriter） | 4 个汇交点文件一次性编好；默认 config.yaml 字串零改动 | L（串行一次完成） |

### 5.2 A 线（工程师 A，P0/P1）

| 任务 ID | 任务 | 依赖 | 产出文件 | 风险 | 备注 |
|---|---|---|---|---|---|
| A0 | 游戏角容器：QStackedWidget 双页 + 注册表驱动左列 + 荷官四款零改写 + 尺寸适配 | V-1.4-0 | gui/widgets/mini_games.py、gui/widgets/games/__init__.py（仅注册表骨架） | M | 交付后荷官四款 offscreen 回归断言（旧四钮行为等价） |
| A1 | 2048 内置（PySide6 单文件 widget；MIT 头保留；当前得分豁免；无排行/无存档） | A0 | gui/widgets/games/game_2048.py + games/__init__.py 注册行 | M | 移植前先过 A4 许可复核门（见 A4） |
| A2 | 扫雷内置（去皮/去计时排行；剩雷数与标旗；MIT 头保留；win/lose 可选接 `_react`） | A0 | gui/widgets/games/game_minesweeper.py + games/__init__.py 注册行 | M | 右键标旗真机验证；A1/A2 建议同人串行（games/__init__.py 同文件） |
| A3 | 番茄钟：PomodoroController + 视图 + 首页入口 + 托盘动作/notify_maid + companion 轻事件 | V-1.4-0 | gui/pomodoro.py、gui/widgets/pomodoro_dialog.py、page_home.py、tray_manager.py | M | 独立通道（D-V14-05）；与 A0 并行互不影响 |
| A4 | 许可合规：复核 2048/扫雷 仓库 LICENSE（clone 前门禁）→ THIRD_PARTY.md + third_party_licenses 全文 → About 开源组件卡片；移植文件头合规抽查 | A1/A2 clone 节点起、A1/A2 完成前必须核完 | docs/THIRD_PARTY.md、docs/third_party_licenses/、page_about.py | L（门禁型，卡 A1/A2 代码合入） | 见共享知识 19 评审清单 |
| A5 | P2 扩充池：候选登记（贪吃蛇自制 <300 行、数独待复核、井字棋/五子棋/翻牌自制优先）写 THIRD_PARTY 预留节 + design 附录；**可选**自制贪吃蛇（不进 v1.4 承诺） | 全部 A | docs（候选表） | L | 非承诺；排期松才做代码 |

### 5.3 B 线（工程师 B，P0/P1）

| 任务 ID | 任务 | 依赖 | 产出文件 | 风险 | 备注 |
|---|---|---|---|---|---|
| B3 | 屏抓共享底座：抽取 `grab_virtual_desktop` + JPG/data URI + 帧差比 + crop；screen_capture 委托回归 | V-1.4-0 | gui/screen_grab.py、gui/widgets/screen_capture.py | M | offscreen 截图回归一次 |
| B0 | 视觉前提：vision_support 启发式 + 引导文案 + 模型配置/README 备注；分类/意图 worker | V-1.4-0 | gui/vision_support.py | L | 与 B3 并行 |
| B1a | ScreenWatchService 核心：周期/diff/计数/token 累计/帧上限自停/高价值分类节流/帧内存链/取帧口/启停弃帧 | B3, B0 | gui/screen_watch.py | M~H | 纯服务，无 UI，可 py_compile + 逻辑断言自测 |
| B1b | 看屏 UI 与渲染：screen_watch_bar chip + chat_panel「👀 看屏」钮/「🔍 按屏提问」/启发式附帧路由 + page_settings「视觉」区 + ChatService `uri` 附件通道与 `screen_bubble`/`screen_bubble_ready` | B1a, B0 | gui/widgets/screen_watch_bar.py、chat_panel.py、page_settings.py、chat_service.py | H | chip 与 handsfree_bar 并存布局验证；无双气泡断言 |
| B2 | GUI 单步操作：input_sim + authorize_action_dialog + computer_use 意图/授权/执行/反馈闭环 + chat_panel「🖱 操作」钮路由 | B1b（可先于 B1b 的 UI 部）、B0 | gui/input_sim.py、gui/widgets/authorize_action_dialog.py、gui/computer_use.py、chat_panel.py | **H** | 三大风险：授权粒度、坐标准确度、真机 DPI；首版保 click+type，其余动作健在则给 |

### 5.4 收口（串行，QA/主程）

| 任务 ID | 任务 | 依赖 | 风险 |
|---|---|---|---|
| V-1.4-X | 全量收口：py_compile 全绿；A-14 式红线扫描（词表扩：排行榜/最高分/连胜/连对/纪录/成就/历史最佳；`gui/widgets/games/` 局内词白名单化）；帧不落盘断言（启停后无缓存文件）；回归冒烟（荷官四款/看图/截图/免提/TTS/托盘/深色零回归）；打包 onedir 验证体积零增量（ctypes 路径）；A4 复核表签字；升版（version.json/`__version__`/CHANGELOG/README） | 全部 A + B | L |

---

## 6. 依赖 / 共享知识（design-v13 1–17 全沿用 + v1.4 增补）

design-v12 知识 1–10、design-v13 知识 11–17 全部沿用。v1.4 增补：

18. **文件域硬分区**（本版最高优先级）：A/B 双线文件域如 §3.1 表互不相交；共享文件（config/main/spec/qt_compat）V-1.4-0 一次性编好后只读；`chat_panel.py`/`page_settings.py` 单写者（B 线）。任何跨域需求先找架构，禁止顺手改对方文件。
19. **A4 许可合规评审清单**（每候选 clone 前逐条过，任一不满足即停用并记日志）：
    ① 仓库内实际存在 LICENSE 文件，其许可 ∈ {MIT, Apache-2.0, BSD-3-Clause, BSD-2-Clause, 0BSD, CC0}（以文件为准，不信 README 徽章）；存在即判 GPL/AGPL/LGPL/SSPL 或缺失/自定义 → 拒绝。
    ② 源码文件带原版权头（year+author）——无版权头的 MIT 文件无法合规保留声明，需溯源到仓库 LICENSE 版权行。
    ③ 项目 import 的第三方 Python 依赖许可干净（如数独候选的 `sudoku` 库待核）；PyQt 源仅核仓库自身许可（改写进 PySide6 合法）。
    ④ 资产版权：原项目图标/音效若引入需许可允许；CC 音效类（如 CherryTomato）一律不引入；码铃默认重绘/不搬资产。
    ⑤ 移植文件保留原版权行（照抄）+ 码铃移植说明块；`THIRD_PARTY.md` 行 + `docs/third_party_licenses/<proj>.txt` 全文 + About「开源组件」。
    ⑥ 复核人/日期/commit 记录在案（供审计）。
20. **帧不落盘约定（R-E/R-G）**：ScreenWatch 系任何帧/缩略图只存内存（data URI / QPixmap 变量），**严禁写入磁盘**；唯一落盘例外 = 用户手动截图（`screen_capture.capture_region` 临时 PNG）。关停/达限/退出三路径必须置空内存帧；收口断言可扫 temp 目录无新缓存。chip 展示的帧/token 计数只是本会话运行时读数，不做文件。
21. **authorization 复用约定**：B2 授权 = 新专用信号/对话框 + **逐次授权语义**，绝不复用 Agent `agent_authorization_requested`/`agent_tools.authorize()` 的会话级缓存；两者视觉同源（QMessageBox 家族/同主题取色）但按钮语义不同，UI 明示"仅这一次"。拒绝即终局，不重试、不强推（沿用 agent 授权文案口径）。
22. **坐标换算约定**（B2 点击准确性核心）：模型返回 (x,y) 以送视觉的**图像像素**为基准 → 按"图像宽/高 vs 逻辑虚拟桌面宽/高"等比反算到**逻辑虚拟桌面坐标** → 用 `screen_grab` 记录的屏几何命中包含该点的屏幕 → 该屏 DPR → **物理像素**（虚拟桌面负坐标 + 每屏 dpr 独立换算，公式在 `input_sim.py` 单点实现供 QA 断言）。混合 DPR 屏下换算为已知近似边界（继承 P1-2），需真机标定。
23. **局内词白名单扫描约定（Q-A1 落地）**：红线扫描把 `gui/widgets/games/` 作为白名单路径——`得分/剩余雷数/重新开局` 等局内必需词只允许出现在该路径；其外全 UI 仍禁 `分数/得分/计时/排行` 类养成词；扩扫词（排行榜/最高分/连胜/连对/纪录/成就/历史最佳）**全路径零命中**（含 games）。
24. **游戏内容色与主题色边界（B8 延伸裁定）**：games 的棋盘/瓦片为"游戏内容中性色"，允许自带固定小色板（否则 2048 瓦片语义色没法进主题三套×深浅两套）；但 games 的窗口壳、侧栏、按钮、说明文字一律 `theme_color()`，深色下保证壳面可读、游戏内容不刺眼白块。
25. **视觉模型前提约定（B0）**：所有视觉能力（看图/看屏/操作）统一 `vision_support.heuristic_supports_vision` 做 best-effort 前置提示；权威失败（API 报错）走既有可读引导链；**任何路径都不得静默失败**。视觉小调用（B1 分类 / B2 意图）一律 worker 线程 + 超时 + 可取消。
26. **气泡渲染单入口延伸**：B1 提示/B2 反馈/peek 结果 = `ChatService.screen_bubble`（写 session → `gui_session.message_added` 单入口渲染 + 专用信号 `screen_bubble_ready`）；托盘只订阅 `proactive_message`，天然不 toast 屏幕类气泡（R-C 仅对话气泡满足）。

---

## 7. 打包影响（对照 PRD §8 表逐项核实）

| 需求 | 依赖 | exe 体积影响 | 离线性 | spec 动作 |
|---|---|---|---|---|
| A0/A1/A2 游戏容器与 2048/扫雷 | **无新增**（纯 Qt 移植进代码库） | 0 | 离线 | hiddenimports 补 `gui.widgets.games`(+2 子模块)（V-1.4-0 已编） |
| A3 番茄钟 | 无新增（去 pygame；提醒 = 托盘气泡 + 既有 TTS） | 0 | 离线 | hiddenimports 补 `gui.pomodoro`/`gui.widgets.pomodoro_dialog` |
| A4 第三方声明 | 无新增依赖 | 0 | 离线 | datas 收录 `docs/third_party_licenses`（随仓库分发即可；如需进包再列 datas 一行，V-1.4-X 确认） |
| B0 视觉链 | 既有（多模态 OpenAI 兼容端点） | 0 | 联网（模型 API，既有声明） | hiddenimports 补 `gui.vision_support` |
| B1 看屏帧采集/压缩 | **无新增**（Qt QScreen/QImage/QBuffer，不引 Pillow/numpy） | 0 | 联网（视觉模型） | hiddenimports 补 `gui.screen_grab`/`gui.screen_watch`/`gui.widgets.screen_watch_bar` |
| B2 操作模拟 | **默认零新增**（ctypes `SendInput`/`mouse_event`/`SetCursorPos`） | 0 | 离线执行 | ctypes 无需 spec 额外项；pyautogui 备选不打包（PRD §8 备注保留） |
| 通用 | JPEG 编码走 Qt imageformats 插件（随包既有，camera_capture 已用 JPG 先例）；新增全部模块 V-1.4-0 已进 hiddenimports | 0 | — | 本版无新增静态资产（A4 声明文件走仓库/About 呈现） |

> 默认产物体积 0 增量承诺延续；`py_compile` 全绿 + 打包 onedir 验证在 V-1.4-X。

---

## 8. 待明确事项（收敛 + 默认建议，均不阻塞 A0/B3 开工）

1. **2048 触屏滑动手势**：首版仅键盘（方向键 + WASD）；触屏手势 P2（需 QGestureEvent 适配，成本中）。默认 = 键盘先行。
2. **B2 坐标换算精度边界**：混合 DPR（多屏不同缩放）点击命中为近似（同 P1-2 已知边界），首版承诺"主屏/同 DPR 多屏精确"，混合 DPR 真机标定；默认接受此边界并写入 README 已知问题。
3. **B2 未开启看屏时的取帧策略**：默认 = 「🖱 操作」开启后一次性显式抓帧（内存即弃，R-E 例外），不进持续采集；若 PM 觉得应强制先开看屏（更严边界）可加一行开关，默认开放但提示。
4. **意图产出格式**：默认 JSON 文本输出 + 严格 schema 校验（不依赖厂商 function calling），比 function calling 兼容面大；B2 若希望结构化更稳可后续换 tools，架构留口。
5. **高价值分类频率**：显著变化帧才分类 + ≥90s 最小间隔（默认）；真机跑一周后按 token/命中率调（架构口径：宁可少提示不可漏报错，漏报由「按屏提问/看一帧」人工兜底）。
6. **番茄钟 TTS 默认**：默认开（`pomodoro_tts=True`），仅一句、受 tts_enabled/可用性守卫；无语音包设备自动静默（TTS degraded 已在 v1.3 处理）。
7. **托盘加「🍅 专注」后菜单项数**：现 6 项 → 7 项，可接受；不改图标不重构。
8. **A1/A2 情绪联动默认值**：2048 = 不接（结束语义中性，防误情绪）；扫雷 = 接 win/lose（方向明确）。若评审要求 2048 也接，仅接 `reach_2048` 当 win，一行开关见 A2 任务备注。
9. **游戏角标题文案**：保留 v1.3「码铃荷官台」作为荷官页小标题 + 对话框标题改为「🎲 游戏角 · 码铃陪你」（老入口不变）；由 UI 裁最终措辞，产品无硬性要求。
10. **A3 若与 B2 排期冲突**：A3 可降 P2（PRD 裁剪顺序已列），需 PM 知情；默认仍 P1 并行推进。

---

## 9. IS_PASS 自审

| 检查项 | 结论 |
|---|---|
| 与 prd-v14（A0–A5/B0–B3/R-G/R-H/Q-A1..Q-B7）一致性 | 通过：Q-A1 拍板（局内即时分值豁免 + 不落盘/无排行硬约束 + 扫描词扩）已写 §2.1 与共享知识 23；Q-A2..Q-B7 默认建议逐条落架构（§2.1–§2.5 + D-V14-01..14），无静默推翻；R-G/R-H 全文转述为强制口径并在 §3/§5/§6 落文件与任务级验收 |
| 与 design-v13 不冲突 | 通过：R-A~F 与 v1.3 全部语义沿用；mini_games 走"加注册表 + 双页容器"不改荷官四款；托盘仅加动作与 notify 方法（不改既有 quit 编舞/proactive 订阅）；ChatService 只加两个纯增量方法与新信号；proactive scheduler/companion/theme_engine/core 本版**零改动**；v1.3 汇交点教训通过 §3 硬分区规避 |
| 红线归零路径 | R-A：games 局内词白名单 + 全路径扩扫词零命中 + 游戏零持久化；R-B：看屏只显式开启/只答当下帧/无行为统计（新增词"使用报告/时间线/屏幕行为统计"入扫描）；R-C：屏幕提示专用信号不 toast + 节流可关，番茄走独立通道明确非打扰；R-D：文件域与只增量方法面清单化；R-E：帧内存约定 + 三路径弃帧断言；R-F：§7 零新增依赖表；R-G：逐次授权独立对话框/无会话放行/无周期采集/仅交互桌面；R-H：评审清单门禁进 A4 |
| 任务粒度 | A/B 双线共 11 个任务 + V-1.4-0/V-1.4-X 整合项；每任务含依赖/产出文件/风险/负责人建议；A 线（A0→A1/A2→A3→A4）与 B 线（B3/B0→B1a→B1b→B2）两路全程并行、文件域零交集；高影响点 B1b/B2 标 H 并给降级（B2 可裁到 click+type） |
| 双写防护 | §3.1 域表 + §3.2 汇交点 V-1.4-0 一次性预编 + §6 共享知识 18 = 明确机制，非口头约定 |

**IS_PASS: YES**（V-1.4-0 可先行；A/B 两路可并行开工；2 处架构级语义裁决——番茄钟独立通道 D-V14-05、B2 独立于 Agent 的 D-V14-11——建议 PM 知情后无异议即按本稿执行）。
