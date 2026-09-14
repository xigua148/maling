# 码铃（MaLing）v1.2 增量架构设计与任务分解

- 版本：v1.2（基于 v1.1.0 增量，承接 `prd-v12.md`）
- 文档状态：架构初稿（供开发排期与实现消费）；**v1.2c 复核修订已落库（2026-09-03）**
- 维护人：高见远（架构）
- 输入：`docs/prd-v12.md`（权威需求，当前 v1.2c）+ 代码库实测（`README.md` / `CHANGELOG.md` / `core/__init__.py` / `core/plan_engine.py` / `gui/main_window.py` / `gui/pages/*` / `gui/widgets/*` / `agent_engine.py` / `agent_tools.py` / `intimacy.py` / `memory.py` / `greeting.py` / `gui/theme_engine.py` 等）
- 关联文档：`docs/prd-v12.md`（Q1/Q3/Q4/Q6 裁决见本文件 D1/D3/D4/D2）
- v1.2c 修订记录（对应 PRD §7.3 复核点）：①D2 mood 由「中枢」修正为「后台氛围源」，暴露面收口——GUI 禁数值条（见 §3.9 红线）；②A5 进度条任务改「关系称谓文本」；③A9 有节制主动陪伴纳入 v1.2，新增调度/配置/通道设计（§3.10）与任务（A-12/A-13）；④Non-goal 合并去重（下述总体约束）；⑤A10 摄像头/麦克风仅观察，不进 requirements/spec/任务。

> **总体约束（PRD §8 Non-goals 复述 + v1.2c 合并去重，实现逐条对照）**：陪伴数据纯本地（`~/.maid_coder/`）；不做动画引擎/骨骼/Live2D（静态表情 + 轻量 QSS 动效）；不改三栏主窗骨架、不重构会话/消息模型；`run_command` 不是通用终端；C2 自愈有限轮次、可中止、写文件仍走授权；无监督循环禁止；**主动陪伴只做「有节制版 A9」、不做打扰式推送**（仅应用运行期/免打扰时段外/频控与单日上限内；不做系统级定时弹窗/闹钟、不做基于行为分析的推送）；**不做监督/评判式陪伴**（摄像头/麦克风不做学习监督/专注度评分/内容分析，v1.2 连「在场感知」都不做）；**不做数值养成焦虑**（UI 不展示心情值/心情条/经验条/分数/打卡倒计时；心情与好感永不 gate 功能、永不作负向反馈）；**不做 Flowise/Dify 式 node 工作流编辑器**（任务步骤可视化仅限 C3-2 只读进度视图）；**A10 摄像头/麦克风仅观察项，不进 v1.2 需求/依赖/spec/任务**。C1→C3→C2→C4 实现顺序与 PRD §4.3 一致（C4 最小版可与 C3 并行）。

---

## 1. D1–D8 决策表

| 编号 | 决策点 | 结论（一句话） | 主要影响文件 |
|---|---|---|---|
| D1 | 陪伴数据归属（PRD Q1） | **新建独立 `companion` 域**：`companion.py` manager + `~/.maid_coder/companion.json`，与 intimacy/memory 分离但单向读 intimacy；不并入两既有系统 | 新增 `companion.py`；`gui/main.py`（挂载）、`gui/main_window.py`（启动时序）；`intimacy.py` 仅加 1 计分键与 1 getter |
| D2 | 心情状态机 MoodState（A1，**v1.2c 口径：后台氛围源**） | 纯规则引擎（**零 LLM**，引擎/持久化/事件协议均不动）：输入 = detect_emotion(主人情绪)+好感度等级+时段+连续天数，输出心情态集合 {normal/happy/concerned/shy/tired}，由呈现层以「活动态临时覆盖」叠加 thinking/focus/surprised；Qt Signal 广播，GUI 单源 = `companion.mood` + `mood_changed` 信号，四处呈现同一路由。**暴露面收口**：mood/intimacy 一律不渲染数值/进度条，GUI 只消费心情态/表情/文案与关系称谓（红线见 §3.9） | 新增 `companion.py`（内含 MoodEngine）；新增 `gui/companion_bridge.py`；`greeting.py`、`gui/chat_service.py`、`gui/main_window.py` |
| D3 | run_command 安全边界（PRD Q3） | 命令/解释器+语法双白名单（**不进弹窗，拒绝即拒绝**），路径白名单命中 workspace 自动放行/越界走 L1 授权弹窗；argv 直传禁 shell；独立子进程 + 超时 kill + 截断 + 会话级互斥；诚实标注「进程级隔离，非沙箱」，与 CodeSandbox 并存不替代 | 新增 `command_runner.py`；`agent_tools.py`（注册 run_command）；`core/__init__.py`（agent 配置段扩展） |
| D4 | C3 任务步骤化（PRD Q4） | **不动既有 PlanStore/FileChange 语义**（/plan 命令与 session 依赖它），新扩 `core/plan_engine.py` 之**姊妹模块** `agent_task.py`：TaskStep/TaskRun + `~/.maid_coder/task_runs/` 持久化 + 断点恢复；与 PagePlan(Task/Plan) 无关，是另一套「运行时任务执行清单」；v1.2 人机接管 = 查看+停止+断点继续（跳过/改序 P2） | 新增 `agent_task.py`；`agent_engine.py`（新增 managed 入口）；`gui/widgets/tool_trace.py`（步骤视图） |
| D5 | AgentEngine 扩展点 | 三处全部走**新增事件类型 + 新增入口方法 + 每轮前任务上下文临时注入**，`run()` 旧路径零改动保零回归 | `agent_engine.py`、`agent_tools.py`、`agent_task.py`、`gui/chat_service.py` |
| D6 | B1 形象资产管线 | `gui/assets/maid/` + `manifest.json` + 加载器 + QPainter 占位脸回退 + `MaidAvatar.set_expression()` 统一 API（首页/宠物/气泡/侧栏托盘全部复用）；spec datas 加一条 | 新增 `gui/maid_assets.py`、`gui/widgets/maid_pet.py`；`maid_coder_gui.spec` |
| D7 | B8 设计语言落地 | **不加第 4 套主题**，走「新增 `themes/base.qss` 组件层 + 三套 QSS 收窄为肤感层」的合并式收敛（ThemeEngine 合并加载）；v1.2 只对新增/重构 UI 组件落 B8 token，全量 sweep 到 P2；主题引擎只加 layout 语义键与合并逻辑 | 新增 `themes/base.qss`；`gui/theme_engine.py`；`cute.qss/minimal.qss/maid.qss`（收敛裁剪） |
| D8 | B9 模型配置入口 | 抽独立 `ModelConfigPanel` 组件（状态头+厂商卡片点选+编辑区），设置页整区替换；首页快捷入口 + 侧栏状态按钮直达并滚动定位；脱敏由 `core.mask_api_key()` 统一提供 | 新增 `gui/widgets/model_config_panel.py`；`gui/pages/page_settings.py`、`gui/pages/page_home.py`、`gui/widgets/sidebar.py`、`gui/main_window.py`、`core/__init__.py` |

---

## 2. 新增 / 修改文件清单

### 2.1 新增文件

| 路径 | 一句话职责 | 是否进 v1.2 承诺 |
|---|---|---|
| `companion.py` | 陪伴域总管：MoodState 心情引擎（纯规则）+ streak 连续天数 + 每日动态缓存 + 成就判定 + 足迹/里程碑记录；读写 `~/.maid_coder/companion.json` | 是（A1/A2/A4/A5 底座，A7 数据已积累） |
| `command_runner.py` | C1 进程执行器：白名单/路径校验/argv 直连/超时 kill/输出截断/进程内互斥锁 | 是（C1-1/C1-2） |
| `agent_task.py` | C3/C4 任务执行域：TaskStep/TaskRun/TaskRunStore + TaskPlanner(LLM 出步骤) + C2 自愈子编排 + C4 任务上下文压缩器 | 是（C3/C2/C4） |
| `gui/maid_assets.py` | 形象资产加载器：manifest 校验 + 8 表情图加载 + QPainter 占位脸回退 + 圆裁/缩略缓存 + `MaidAvatar` 控件（统一 `set_expression()`） | 是（B1） |
| `gui/widgets/maid_pet.py` | A8 窗口角落微型常驻宠物 + A8-1 微型档渲染（5 态先行） | 是（A8/A8-1） |
| `gui/companion_bridge.py` | GUI 侧 MoodBridge：把 companion（纯 Python）变更翻译为 Qt `mood_changed` 信号；提供 `refresh_maid_expressions()` 统一刷新四处呈现 | 是（A1/B4/B5） |
| `gui/widgets/model_config_panel.py` | B9「模型与接口」可复用组件：状态头（脱敏/连接态）+ 厂商卡片点选 + Key/URL/模型编辑 + 保存 | 是（B9） |
| `gui/proactive_scheduler.py` | A9 主动陪伴调度器（QObject + 低频 QTimer，GUI 运行期唯一触发源）：空闲计时/免打扰窗/单日上限判定 + 触发上下文组装（companion 事件池选材）| 是（A9） |
| `themes/base.qss` | B8 公共组件样式层（引用 `${color}`/`${spacing_*}` 变量），三主题共享的布局/间距/圆角/密度 | 是（B8，随 ThemeEngine 合并加载） |

### 2.2 修改文件

| 路径 | 改动点 | 风险级 |
|---|---|---|
| `gui/main.py` | 初始化 `app_ctx.companion`（读 intimacy/session.memory_mgr/greeting）；构建 bridge；注入 Agent 任务完成事件点 | 低 |
| `gui/main_window.py` | 接线 mood 广播到四处呈现；挂载 MaidPetOverlay；`on_app_open` 每日打卡；B9 侧栏/首页直达；托盘心情文案扩展位；**挂 A9 ProactiveScheduler 并接 `interaction_occurred` 打点** | 中 |
| `gui/pages/page_home.py` | 首页改造为「房间式」：主形象 + 问候 + 每日动态卡 + 快捷入口重组（含模型设置）+ **关系称谓文本**（A5，无数值条，红线见 §3.9） | 中（不推翻卡片框架） |
| `gui/pages/page_settings.py` | 「API 配置」节替换为「模型与接口」专区（ModelConfigPanel），暴露 `scroll_to_model()` | 中 |
| `gui/widgets/sidebar.py` | 底部区：码铃头像(心情态) + 关系称谓文本入口 +「模型状态」直达按钮（含脱敏展示）；**不渲染好感分数/进度条** | 低 |
| `gui/widgets/chat_panel.py` / `gui/widgets/message_bubble.py` | AI 气泡旁 Q 版头像（B3）：thinking/focus/happy/shy 表情态；订阅 mood/活动态 | 中（纯增量） |
| `gui/widgets/tool_trace.py` | 新增事件行渲染：步骤开始/通过/失败/自愈第 n 次 + 步骤进度视图 + 「停止自愈」按钮信号 | 中（纯增量） |
| `agent_engine.py` | 新增 managed 任务入口（C3/C4 编排）+ 新事件常量 + 每轮任务上下文临时注入；`run()` 旧路径不改 | 高（加不改，回归风险可控） |
| `agent_tools.py` | 注册 `run_command`（L1）+ 挂 CommandRunner；工具描述诚实标注「进程级隔离非沙箱」 | 中 |
| `gui/chat_service.py` | 主人消息/回复完成 → companion 情绪与好感钩子（getattr 守卫、无 companion 则空转）；**新增 `proactive_ask()` 独立入口**（A9，kind="proactive"，见 §3.10） | 低~中 |
| `gui/widgets/chat_window.py` | A9 主动消息落点：浮窗接收/展示 proactive 气泡 + 托盘气泡点击「去看」激活浮窗；不建第二套聊天引擎 | 中（复用既有 R6 链路） |
| `intimacy.py` | `_SCORE_RULES` 增 `pet_click:1`；新增 `progress_to_next()`/`next_level()`/`level_bounds()` getter（不改计分规则）——**仅内部可用，不接 UI 进度条** | 低 |
| `greeting.py` | 导出 `current_period()` 公开帮助（供 mood/A2 取时段） | 低 |
| `core/__init__.py` | AppConfig 增 `agent_max_retries`/`agent_command_timeout`/`companion_llm_moments`/`proactive_*` 等字段 + yaml 段；`mask_api_key()`/`api_status_summary()`；API_PROVIDER_PRESETS 增 `desc`/`is_local` 展示元字段 | 低 |
| `gui/theme_engine.py` | 合并加载 base.qss + 主题 qss；补语义色键（三主题）+ layout token | 中 |
| `gui/themes/cute.qss`、`minimal.qss`、`maid.qss` | 收窄为「配色/肤感层」，删除与 base 重复的结构样式（diff-minimal 收敛） | 中 |
| `maid_coder_gui.spec` | datas 增 `('gui/assets/maid', 'assets/maid')`；hiddenimports 补 companion/command_runner/agent_task/gui.maid_assets/gui.widgets.maid_pet/gui.companion_bridge/gui.proactive_scheduler | 低 |
| `gui/config.py` | GuiConfig 增 `pet_enabled` 等展示偏好；**不存 proactive 运行状态**（A9 状态存 companion.json，见 §3.10） | 低 |
| `CHANGELOG.md` / `version.json` / `core/__init__.py.__version__` | v1.2.0 收口时升版与记录 | 低 |

### 2.3 P2 预留（不做代码，仅留口）

- A6 换装：资产命名约定 `{expression}_{theme}.png` + MaidAssets 已按主题查表；A8-ext 脱窗：MaidPetOverlay 结构可整窗提取为无边框 QWidget；A7 足迹页：companion.json 数据已覆盖日历/里程碑，页面 P2；C4-2 续接：TaskRun 存档天然可被「继续上次任务」读取。

---

## 3. 核心数据结构与接口签名

### 3.1 D1 · companion 域数据模型

文件：`~/.maid_coder/companion.json`（唯一 companion 持久化文件，`_atomic_write_json` 写）。

```json
{
  "schema_version": 1,
  "meta": { "created_at": "ISO", "updated_at": "ISO" },
  "mood": {
    "current": "normal",
    "since": "ISO",
    "basis": { "owner_emotion": null, "intimacy_level": 0,
               "period": "evening", "consecutive_days": 1 },
    "history": [ { "mood": "happy", "at": "ISO", "reason": "gratitude|level_up|pet_click" } ]
  },
  "streak": {
    "first_seen_date": "YYYY-MM-DD",
    "last_seen_date": "YYYY-MM-DD",
    "consecutive_days": 1,
    "total_days": 1,
    "punch": [ { "date": "YYYY-MM-DD" } ]
  },
  "moments": [ { "date": "YYYY-MM-DD", "greeting": "...", "note": "...",
                 "mood": "normal", "task_done_today": 0 } ],
  "achievements": { "unlocked": [ { "id": "first_meeting", "at": "ISO" } ] },
  "milestones": [ { "type": "level_up|first_task|first_heal|theme_switch",
                    "at": "ISO", "detail": "..." } ],
  "event_log": [ { "type": "open|chat|level_up|agent_done|heal|pet_click|theme",
                   "at": "ISO", "data": {} } ],
  "proactive": {                    // v1.2c A9 运行状态（GUI 运行期维护）
    "last_date": "YYYY-MM-DD",      // 最近一次主动消息日期
    "count_today": 0,               // 今日累计（与 daily_cap 比较）
    "last_at": "ISO",               // 最近一次主动时刻（与 ≥60min 间隔比较）
    "next_idle_eligible_at": "ISO"  // 长时间未交互场景的下次可触发时刻
  }
}
```

> 字段命名说明（v1.2c）：schema 键名是**内部存储语义**，非 UI 文案语义——`streak.punch`/`consecutive_days` 仅作成就 `streak_3` 静默判定与足迹数据源，**不得以「打卡/断签/连续 N 天提醒」形式暴露给用户**（A2/A7 措辞红线）；UI 用语统一「相伴总天数 / 足迹」，不公开倒计时。

**数据边界与协同（D1 裁决细化）**

| 系统 | 归属主体 | 存什么 | 谁读谁 |
|---|---|---|---|
| `intimacy.json` / IntimacyTracker | 关系亲密度 | score/level/连续天数（计分引擎，已 CLI+GUI 共享） | **companion 只读** `intimacy.level/score` |
| `user_memory.json` / MemoryManager | 主人长期画像 | 偏好/话题/情绪记录（每会话注入） | mood 输入复用其 `detect_emotion()`（非写） |
| `companion.json` / CompanionManager | 码铃自身状态与关系成长线 | 心情/足迹/成就/每日动态 | 单向依赖前两者，GUI 读它呈现 |
| `sessions/*.json` | 会话 | 对话历史 | 不涉 |

关键裁决：
- **好感度升级 → 写 mood 事件**（是）：升级是陪伴中最重要的情绪源。实现不反向侵入 intimacy，由 GUI/CLI 调用方在拿到 level_up 消息后调 `companion.ingest_event("level_up")` → mood 变 happy（高等级变 shy）+ 成就 `intimacy_2`。
- **成就框架（A4）**：定义内置为 `companion.py` 常量 `ACHIEVEMENT_DEFS`（风格同 `_INTIMACY_LEVELS`），事件驱动：`event_log` 追加 → `_match_achievements()` 比对触发条件 → 解锁写 `achievements.unlocked` + 返回解锁清单。首批 6：first_meeting / first_task / first_heal / streak_3 / intimacy_2 / theme_switch。
- **与 PRD 差异声明**：PRD A4 写「徽章定义在 JSON 配置可扩展」，实现选择 Python 常量（与 intimacy/memory 内联风格一致、frozen 打包零负担、改动频率极低）；若 PM 坚持 JSON 化，抽到 `gui/assets/maid/` 同级数据文件并加 spec datas 即可，接口不受影响。**已同步 PM。**

### 3.2 D2 · MoodState 心情引擎（A1 · 后台氛围源，非养成数值）

```python
# companion.py 内
MOOD_IDS = ["normal", "happy", "concerned", "shy", "tired"]   # 心情态（持久化）
ACTIVITY_STATES = ["thinking", "focus", "surprised"]           # 活动态（呈现层临时覆盖，不持久化）

@dataclass
class MoodInput:
    owner_emotion: Optional[str]  # detect_emotion 输出: None/tired/happy/anxious/lonely
    intimacy_level: int           # 0..3
    hour: int                     # 0..23
    consecutive_days: int
    minutes_since_level_up: Optional[int]  # 升级后分钟数（用于短暂 boost）
    gratitude_recent: bool        # 刚检测到感谢/夸奖

class MoodEngine:
    def __init__(self, data: dict): ...
    def current(self) -> str
    def recompute(self, inp: MoodInput) -> tuple[str, str]   # (mood, reason)，变化才落盘+广播
    def note_activity(self, state: str | None) -> None       # 呈现层覆盖用，不发持久化
    def to_dict(self) -> dict
```

**规则映射表（优先级从高到低，命中即返回）**

| 优先级 | 条件 | 心情态 | 理由样例 |
|---|---|---|---|
| 1 | 升级后 10 分钟内且等级≥2 | happy / shy(≥3) | 升级庆祝 |
| 2 | owner_emotion ∈ {tired, anxious, lonely} | concerned | 主人低落/疲劳，码铃担忧 |
| 3 | hour ≥ 23 或 hour < 5（深夜） | tired | 深夜犯困（体现「她还在」） |
| 4 | owner_emotion == happy 且 gratitude_recent | shy（intimacy≥2）/ happy | 被夸奖害羞 |
| 5 | owner_emotion == happy | happy | 分享开心 |
| 6 | 其余 | normal | 默认微笑 |

- 主情绪持久化字段 key 用 1 位字符压缩（`"0"`=normal…）避免字段名与值歧义——**否**，用全名可读即可；JSON 才几十字节。
- **采集时机**：①主人情绪：GUI 统一在 `ChatService.send_message()`（主线程）经 `companion.note_owner_text(text)` → `memory_mgr.detect_emotion()`；②时段：`greeting.current_period()`；③连续天数：`companion.on_app_open()` 启动即算；④好感度/升级：`_bump_intimacy` 同点。全部 main-thread、事件驱动，**无心情采集定时器**（主动陪伴的调度定时器属 A9，见 §3.10，与心情采集解耦）。
- **持久化**：心情变化才写 `companion.json`（低频）；history 上限 50 条。
- **广播（B4/B5 单源同步）**：
  ```
  companion.MoodEngine.recompute() 变化
      └─> app_ctx.companion_bridge (QObject) .mood_changed.emit(mood, reason)
            ├─ 首页主形象   MaidPortrait.set_expression(mood)
            ├─ 角落宠物     MaidPet.set_expression(mood)          （活动态优先：thinking/focus）
            ├─ 聊天气泡头像 ChatBubbleAvatar.set_expression(...)   （活动态由 chat_service 事件覆盖）
            └─ 侧栏/托盘    sidebar 迷你头像 + tray tooltip 更新
  活动态（thinking/focus/surprised）由 chat_service/agent 事件发出，bridge.note_activity() 广播同一条信号，
  活动结束回落到心情态 —— 单源数据 + 单信号 + 四接收端。
  ```
- **接口签名核心**：`CompanionManager.on_app_open() -> (mood, moment|None)`；`note_owner_text(text)`；`ingest_event(type, data)`；`react_to_pet_click() -> (text, expression)`（A3，30 分钟冷却内只回文案不加分）；`register_task_done()` / `register_heal()`；`summary_dict()`；**新增 `relation_stage_name() -> str`**（A5，只读委托 `intimacy.level_name()`：初识/熟悉/亲近/信赖；不新增字段、不存 companion.json）；`current_mood_context() -> str`（A9 选材用，见 §3.10）。
- **v1.2c 暴露面红线（D2 口径：后台氛围源）**：`summary_dict()` 保留（mood_label/intimacy_level/streak 供 CLI 文本态等 P2 消费）；**GUI 消费端只取心情态/表情/文案与关系称谓**，不得以数值/进度条形式展示 mood 或 intimacy（对应 PRD「不做数值养成焦虑」）；心情永不 gate 功能、永不作负向反馈。

### 3.3 D3 · run_command 安全边界（C1 定稿）

**判定表（决策即验收标准）**

| 类别 | 允许 | 拒绝（不进弹窗） | 条件放行（走授权） |
|---|---|---|---|
| 解释器/命令首 token | `python`/`python3`、`pytest`、`node` | `pip`、`pip install`、npm/npx、git、shell（`bash/sh/cmd/powershell`）、系统命令、`sudo`、全部 `core.DANGEROUS_COMMANDS` 命中项 | — |
| 语法形态 | 无 shell：argv 直传（`shlex.split`），禁 `;|&<>$()\` 反引号/换行/重定向/管道 | 含任一 shell 元字符 | — |
| python 参数 | `<ws 内脚本相对路径>`；`-B`/`-u`；`-m pytest <ws 内路径>` | `-c`、`-i`、`-m pip`、`--help` 之外的 `-m 任意模块` | — |
| pytest 参数 | `<ws 内测试路径>`、`-q`、`-x`、`--tb=short`、`-k <表达式>` | 目录外路径、`--pdb` 等交互 | — |
| node 参数 | `<ws 内 .js 路径>` | `-e` | — |
| 参数路径 | resolve 后在 workspace 内（含最近项目根判定，`cwd` 取 workspace 或含 `.git/pyproject.toml/package.json` 的最近祖先且仍在 ws 内） | 含 `..`/symlink 逃逸/不存在的外链 | **命令/语法全合法但路径越出 workspace** → 走既有 L1 授权弹窗（同 write_file），无渠道拒绝 |
| 授权级别 | — | — | L1（修改级）：命中白名单自动放行；越界授权；无渠道拒绝（沿用 v1.1 fail-safe） |
| 超时/截断 | 超时即 kill 进程，返回部分输出；stdout+stderr 各截断 8k（合计 16k） | — | — |
| 并发 | 每个 `AgentTools`/`CommandRunner` 实例一把 `threading.Lock`，同一进程同一会话同时只跑一个子进程（C1-2 P1）；跨进程互斥不做，文档标注 | — | — |

```python
# command_runner.py
ALLOWED_COMMANDS = {"python", "python3", "pytest", "node"}
FORBIDDEN = set(DANGEROUS_COMMANDS) | {...}
class CommandRunner:
    def __init__(self, cfg, logger): ...
    def run(self, command: str, cwd: str = "") -> dict:
        # 返回 {"status": "ok|error|denied", "exit_code", "stdout", "stderr", "timed_out"}
```
- 实现要点：`subprocess.run(argv, cwd=…, timeout=cfg.agent_command_timeout, capture_output, text, encoding="utf-8", errors="replace")`；Windows 加 `creationflags=subprocess.CREATE_NO_WINDOW`；不设 `shell=True`。
- **与 CodeSandbox 边界**：`run_python` = 纯计算 AST 沙箱（进程内禁文件/网络），`run_command` = **进程级真实执行（可读写文件/联网/长任务），白名单 + 授权但非沙箱**。工具描述与授权文案必须诚实（延续 `utils.py:1072` 与 README 既有口径），UI 在命令运行卡片上标注「独立进程运行 · 非沙箱 · 受白名单约束」。
- 注册进 `agent_tools.py`：`run_command`（L1），schema `{command: str, cwd?: str}`；授权复用 `authorize()` 判断 cwd/参数路径，无弹窗渠道时白名单内放行、越界拒绝。

### 3.4 D4 · C3 任务步骤化模型（与 plan_engine 的并存关系）

```
既有 core/plan_engine.py : FileChange / PlanStore(preview/apply/reject)  —— 文件变更方案语义，/plan 命令与 session.plan_store 在用 → 原样不动
PagePlan / PlanManager   : Plan/Milestone/Task —— 用户「手工计划编辑」，~/.maid_coder/plans/，GUI 参考载体 → 原样不动
新增 agent_task.py       : TaskStep / TaskRun / TaskRunStore —— 「Agent 任务运行时执行清单」v1.2 新语义 → 新模块
```

```python
# agent_task.py
@dataclass
class TaskStep:
    idx: int
    goal: str              # 本步要做什么
    acceptance: str        # 验收标准（用户声明或模型自拟）
    status: str            # pending|running|passed|failed|healing|aborted
    retries_used: int
    artifacts: list[str]   # 产出文件/验证命令输出摘要
    note: str = ""

@dataclass
class TaskRun:
    task_id: str           # task_{uuid8}
    goal: str
    steps: list[TaskStep]
    status: str            # planned|running|paused|done|failed|aborted
    created_at/updated_at: str
    summary: dict          # C4: {"goal", "done_steps", "current_blocker"} 每步后压缩更新
```
- `TaskRunStore`：目录 `~/.maid_coder/task_runs/<task_id>.json`，每步状态变更即落盘 → 异常退出从第一个非 `passed` 步骤续跑（断点恢复）。读取列表供「继续上次任务」（C4-2 P2）。
- **与 GUI 关系**：`tool_trace.py` 升级为「女仆工作进度」视图即 `TaskRun` 的只读投影（步骤清单+当前高亮+整体进度条+每步折叠）；PagePlan 不承载运行时步骤（语义不同，避免两套模型纠缠）。人机接管 v1.2 = **查看 + 停止 + 断点继续**：GUI 停止沿用 `stop_generation` 中断链，engine 捕获中断 → TaskRun.status=paused 落盘；「继续」从断点步重启。
- `TaskPlanner`：LLM 一次调用产出步骤 JSON（复用 `core/plan_engine.py:43` 的 PlanEngine.analyze 作为「文件影响发现」辅助？——不，analyze 是全量修改式、成本高，v1.2 直接让模型基于 read_file/list_dir 产出 2~8 步清单），每步含 goal+acceptance；模型同时可声明「一步可完成」→ 直接走单步执行（等价 v1.1）。

### 3.5 D5 · AgentEngine 扩展点

```python
# agent_engine.py 新增
EVT_TASK_PLAN   = "task_plan"     # {goal, steps: n}
EVT_STEP_START  = "step_start"    # {idx, total, goal}
EVT_STEP_PASS   = "step_pass"     # {idx, note}
EVT_STEP_FAIL   = "step_fail"     # {idx, error_summary}
EVT_HEAL_TRY    = "heal_try"      # {idx, attempt, max_retries, fail_summary}
EVT_STOP_HEAL   = "stop_heal"     # {idx, reason}（用户中止）
EVT_TASK_DONE   = "task_done"     # {ok, summary}

class AgentEngine:
    def run_managed_task(self, goal: str, planner_prompt: str = "",
                         task_ctx_fn: Optional[Callable[[TaskRun], str]] = None) -> TaskRun:
        """C3 步骤化执行。内部:
        1) 规划: 带 tools 调模型 -> 收 TaskRun(步骤清单) 落盘
        2) 逐 step:
           a) 每轮调 _chat 前注入 task_ctx_fn 压缩上下文（临时 user 项，请求完移除，不污染历史）——C4
           b) 本步内跑子循环（预算=agent_max_steps 步）
           c) 步骤完成判定: 模型显式声明完成 且 本步最近一次验证性 run_command exit_code==0
              → passed；否则进 C2 内层自愈
           d) C2: 失败输出回注模型 → write_file/run_command 修改重试，最多 agent_max_retries 轮
              (每次写文件仍走 AgentTools.authorize)；超限 → 步骤 failed + 上报卡点 + EVT_STOP_HEAL 等接管，不自动跳过
        3) 中断(用户停止) → TaskRun.status=paused 落盘 → 返回以便断点继续
        """
    # 原 run() 完全不变
```
- ① run_command 接入 = 只在 `agent_tools.py` 注册新工具，engine 的分发循环天然支持（无需引擎改动）。
- ② C2 自愈 = engine managed 模式内层 while `attempt <= max_retries`，与步骤循环形成「外层步骤 + 内层 retry」两层结构（见 §4 时序）。max_retries 配置 `agent.max_retries`（默认 3）。
- ③ C4 注入与 memory.py 作用域区分：**memory = 跨会话长期用户画像**（注入 persona/system）；**task_ctx = 当前任务会话内短程进度**（目标+已完成+卡点，存 TaskRun.summary）。两者独立存储、独立生命周期；task_ctx 注入点=每轮 `_chat` 前临时插入的 `{"role":"user","content":"[任务进度] …"}`，仅存在于当次请求窗口。

### 3.6 D6 · 形象资产约定（B1/A8-1）

```
gui/assets/maid/
  manifest.json            # {"version":1, "expressions":["normal","happy","thinking","focus",
                           #  "concerned","shy","tired","surprised"], "moods":[...], "themes":["default"]}
  normal.png happy.png thinking.png focus.png concerned.png shy.png tired.png surprised.png
  # 主形象 2x 出图 → 展示 260~340px 高；气泡/微型/托盘三档由运行时从主形象缩略/圆裁（不重复导图）
  # A8-1 微型档 v1.2 先行 5 态 normal/happy/thinking/focus/tired，缺失态自动回落 normal 或占位脸
```
- 加载器 `gui/maid_assets.py`：`MaidAssets.load(theme="default")` → 校验 manifest + `QImage` 非空 + 尺寸>0；任一缺失 → 该表情回退到 QPainter 占位「Q 版脸」（底色 + 铃铛 + 按表情画眉眼嘴）；**UI 永不因缺图空白/崩溃**（占位与真图同接口）。
- 统一 API：`MaidAvatar.set_expression(name, size_hint=None)`（内部按目标尺寸切 3 档缓存）；`MaidAvatar.round()` 圆形裁剪用于气泡。A8 宠物 = `MaidPet(MaidAvatar)` + 空闲 QTimer 呼吸/犯困微切换（不发持久化，本地活动态）+ hover tooltip（心情文案 + 「回首页」）+ 点击 → `clicked` 信号 → A3。
- 全部经 `gui.utils.get_resource_path("assets/maid/…")`；spec `datas` 增 `('gui/assets/maid','assets/maid')`。

### 3.7 D7 · B8 落地（token + base 合并 + 收敛清单）

- **不加第 4 套主题**；`minimal` 本就偏简洁，`cute/maid` 粉调保留。
- ThemeEngine 渲染链改为：
  ```
  qss = base.qss                     # 组件结构与布局（引用 ${color}/${layout}）
       + theme.qss(cute/minimal/maid) # 仅配色/氛围/局部覆盖（删除与 base 重复块）
  变量替换: colors + 新增 layout token（spacing_xs/sm/md/lg、radius、density）
  ```
- 新增公共语义色键（三主题同步注册，缺失回退）：`bg_light`、`surface_muted`、`text_hint`、`divider`、`focus_accent`、`pet_bubble_bg`；**新增色键必须进 `theme_color()`/取色器体系，禁止裸值**。
- v1.2 落 B8 的组件范围（其余 P2 sweep）：首页重组卡片、每日动态卡、ModelConfigPanel、气泡头像容器、MaidPet tooltip、tool_trace 步骤视图、设置分区。全部按 PRD §4.2 B8 对照表「跟随简洁 / 保留码铃」两列执行。
- 回归保护：base+主题合并后对三主题做 offscreen 截图 diff 冒烟（既有 `_v1014_regression` 同思路），切主题即时生效断言保留。

### 3.8 D8 · B9 实现路径

- `ModelConfigPanel(QWidget)`（新）：①状态头：`core.api_status_summary(cfg)` → 厂商名 / 模型 / `Key: sk-****1234` / 连接态色点，缺 Key 高亮引导；②厂商卡片区：读 `API_PROVIDER_PRESETS` + 新增 `desc/is_local` 元字段平铺点选卡（替代纯下拉）；③编辑区：Key（Password）/Base URL/模型 editable combo + 保存（沿用 `cfg.save()` + 重建 APIClient + `refresh_api_status()` 链路）。
- 设置页整节替换为「模型与接口」分区（objectName 区分 + 说明文字）；暴露 `PageSettings.scroll_to_model()`。
- 直达入口：首页「快捷入口」新增「模型设置」按钮（`page_manager.navigate("settings")` + 调 `scroll_to_model`）；侧栏底部新增「模型状态」小按钮（显示 provider 缩写 + 色点，tooltip 完整脱敏状态）→ 同一跳转。`MainWindow` 提供 `open_model_settings()` 桥。
- `mask_api_key()`：`sk-` + `****` + 末 4 位；空 key → 「未配置」。
- 涉及文件：见 §2（新增 model_config_panel.py + 改 page_settings/page_home/sidebar/main_window/core）。

### 3.9 v1.2c 暴露面红线（D2/A5 口径收口，跨 UI 强制）

PRD v1.2c「不做数值养成焦虑」的架构侧落库，**所有陪伴 UI 实现逐条对照**：

| 红线 | 禁止 | 允许的呈现 |
|---|---|---|
| 无心情数值 | 心情值/心情条/百分比/「心情 -2」式增减 | 表情、心情文案（如「码铃有点担心主人」）、tooltip 心情句 |
| 无好感数值 | 分数/经验条/「Lv.2」/升级 +xx 分 | 关系称谓文本（`relation_stage_name()`：初识/熟悉/亲近/信赖，可附一句暖描述）、升级时的 happy/shy 表情 + 一句庆祝 |
| 无打卡焦虑 | 「连续 N 天/断签提醒/打卡」作 UI 提醒 | 相伴**总天数**中性表达；连续天数仅静默驱动 `streak_3` |
| 无负向反馈 | 久未互动→难过/冷淡/怪罪/数值下降提示 | 心情永不 gate 功能；久未互动只可能触发 A9「安静陪着」式正向问候 |

实现约束：
- `summary_dict()`/`progress_to_next()`/`next_level()` 等带数字的 API **保留但不接任何 UI 进度条/数值位**（CLI 文本态 P2 可消费）；
- 侧栏/首页/宠物 tooltip 一律走 `relation_stage_name()` 与心情文案，代码审查与 C-10 收口同步检查「无进度条/分数控件残留」。
- D2 章节标题沿用「心情状态机（A1 中枢）」处补口径注：语义为**后台氛围源**（引擎/持久化不动，见 §3.2 已改）。

### 3.10 v1.2c A9 · 有节制主动陪伴（调度 + 配置 + 通道）

> 产品定位（PRD A9/US-6）：「她会先开口，但从不多嘴」。这是对 v1.1 期 Non-goal「不做主动打扰式陪伴」的**边界化重写**——A9 为 P0 级设计约束（见 §总体约束），非后补功能。

**原则**：仅 GUI 运行期触发；低频率；免打扰时段与单日上限硬约束；无系统级弹窗；文案模板优先（LLM 增强默认关）；应用退出即停。

**配置（`config.yaml` 新 `proactive:` 段，AppConfig 字段 + `_YAML_FIELD_MAP` + `save()`）**

```yaml
proactive:
  enabled: true          # 全局总开关
  quiet_start: "22:30"   # 免打扰开始（含）
  quiet_end: "08:00"     # 免打扰结束
  daily_cap: 3           # 单日主动消息上限
  idle_minutes: 90       # 长时间未交互触发阈值（默认 90）
  cooldown_minutes: 60   # 相邻两条主动消息最小间隔
  llm_enhance: false     # 文案 LLM 增强（默认关，模板优先）
```

**运行时状态存 `companion.json.proactive`**（见 §3.1 schema，非 GuiConfig——GuiConfig 的 `save()` 是全量覆盖式，不适合存计数器）。

**调度器（`gui/proactive_scheduler.py`，新）**
```
ProactiveScheduler(QObject)  —— 主线程、QTimer tick=30s（低频）
  信号: proactive_requested = Signal(str)   # 组装好的 prompt/topic 上下文
  输入打点: interaction_occurred()           # ChatService.send_message/用户气泡完成 处调用
  判定(每次 tick):
    1) cfg.proactive.enabled 且 当前不在免打扰窗内(22:30–08:00)
    2) 距上一条主动 ≥ cooldown_minutes；今日 count_today < daily_cap
    3) 场景白名单命中其一（v1.2 触发仅限以下三类，全部非主动定时打扰）：
       a) idle ≥ idle_minutes（自 interaction_occurred 起）—— 轻声问候
       b) companion 事件池近 5 分钟内出现 owner_low（低情绪，→ concerned 关心）
       c) 近 5 分钟有 agent_done 且用户未回复 —— 任务回访
    通过 → count_today+1 持久化 → proactive_requested.emit(上下文)
```
- 免打扰判定内聚在 scheduler，产物不落多余定时器；tick 不产生 UI。
- 场景素材：`companion.current_mood_context()` 返回短文本（心情/关系称谓/最近事件一句），scheduler 拼成模板句。

**ChatService 主动入口（区别于用户 send_message 的独立路径，关键防冲突点）**
```
ChatService.proactive_ask(context_text: str):
  # 1. 不走 send_message（那里会 echo 用户气泡 + bump_intimacy + 打点 interaction）
  # 2. 入队 kind="proactive"，ApiWorker 以"仅 assistant 开场"模式：
  #    messages = session 历史(去尾部) + system(主动开场说明,禁止假装主人先说话) + [user 占位"<proactive>"]
  #    流式结果照常 message_stream_finished 渲染为 assistant 气泡；写入 session 时带 meta.proactive=True
  # 3. 副作用守卫：不 bump_intimacy；不重置 interaction 计时（防止自我续命循环：主动消息不当作"用户交互"）
```
- **渲染/落点**：主聊天面板照常出现一条 AI 气泡（与会话历史连贯、可 regenerate）；`chat_window.py` 独立浮窗（复用既有 R6 单数据源链路，**不建第二套聊天引擎**）作为用户回看的「浮窗」入口；托盘侧只做**静默气泡**（`QSystemTrayIcon.showMessage` 无声音/无系统弹窗），点气泡「去看」→ 打开/激活 chat_window 浮窗。
- 防自续命：主动消息不算交互打点；用户任一真实交互后重置 idle 计时并可再次 arm。
- 演示模式（无 key）下主动消息不触发（沿用 `_is_demo_mode` 守卫），避免无 API 假开口。
- 新增 GUI 运行期装配：MainWindow 建 scheduler，连接 `proactive_requested → ChatService.proactive_ask`；`chat_service.send_message` 与气泡送达处补 `interaction_occurred` 打点（getattr 守卫）。

**文件面**：新增 `gui/proactive_scheduler.py`；改 `gui/main_window.py`、`gui/chat_service.py`、`gui/widgets/chat_window.py`（浮窗接收/激活）、`gui/tray`（静默气泡，若托盘为独立模块按其入口接）、`core/__init__.py`（proactive 段）、`companion.py`（proactive 状态子块 + `current_mood_context()`，engineer-a1 已实现的 companion 基础上**增量加**，不推翻既有 API）。

---

## 4. 关键流程时序

### 4.1 任务闭环（US-3/US-4：规划→运行→验证→修正→汇报）

```
用户:「跑 tests/test_utils.py，挂了帮我修」(GUI Agent 模式, task_type=agent)
 ChatPanel → ChatService.send_message(agent)
  └─ ApiWorker._run_agent()
       └─ agent_engine.run_managed_task(goal)              [C3]
           ├─ 规划: LLM(带 tools) → TaskRun{步骤:[跑测试/读失败/修复/复跑/汇报]} 落盘
           ├─ for step in steps:
           │    ├─ task_ctx_fn() → 临时注入 [任务进度] 目标+已完成+卡点 [C4]
           │    ├─ 子循环(budget=agent_max_steps): LLM⇄工具(read_file/write_file/run_command…)
           │    │     run_command(pytest tests/test_utils.py) → exit_code!=0 + stderr 失败输出
           │    └─ 判定 fail → C2 自愈内层:
           │          for attempt in 1..agent_max_retries(默认3):
           │            失败摘要回注 → write_file(仍走授权) → run_command 复跑
           │            EVT_HEAL_TRY → tool_trace 显示「第 n 次自愈」
           │          ├─ exit_code==0 → step passed (EVT_STEP_PASS) → 下一 step
           │          └─ 超限 → step failed → EVT_STOP_HEAL → 上报卡点, 等用户接管
           ├─ 用户「停止自愈」= chat_service.stop_generation → cancel_check=True
           │     → TaskRun.status=paused 落盘 (断点)
           └─ 全部 passed → EVT_TASK_DONE → 汇报总结(骄傲脸 happy) + companion.register_task_done()
 主线程: agent_tool_event → tool_trace 步骤进度视图逐条点亮
 授权: run_command/write_file 命中 workspace 自动放行; 越界走 agent_authorization_requested 弹窗
```

### 4.2 心情广播（B4/B5 单源同步，A1）

```
启动/打开: MainWindow 显示前 → companion.on_app_open()
  ├─ 打卡 streak（连/断天判定）; first_seen_date 兜底首日
  ├─ 生成今日 A2 每日动态卡(问候词+相伴天数+按心情模板句; LLM 增强默认关)
  └─ MoodEngine.recompute(时段/连续天数) → 深夜= tired, 否则 normal
主人发消息: ChatService.send_message(text) → companion.note_owner_text(text)
  └─ detect_emotion → 若 mood 应变更 → recompute() 返回(mood,reason) → 差异时写库
AI 回复完成: _on_stream_finished → 若 detect_gratitude → companion.ingest_event(gratitude)
升级: intimacy level_up 消息 → companion.ingest_event("level_up") → mood boost + 成就 + 庆祝文案
变更→ 广播: companion_bridge.mood_changed.emit(mood, reason)
   └─ 首页主形象 / 角落宠物 / 气泡头像 / 侧栏+托盘  同步 set_expression(mood)
活动态覆盖: streaming=thinking, agent 干活=focus, 彩蛋点击=surprised(→回落)
   chat_service.thinking_indicator / agent 事件 / pet click → companion_bridge.note_activity()
```

### 4.3 A3 彩蛋互动

```
点角落宠物/首页形象 → MaidPet.clicked
  → companion.react_to_pet_click():
      冷却 30min 内 → 仅回台词不加分; 冷却外 → 台词(按 mood+intimacy 选) + intimacy.add_interaction("pet_click")
  → 短暂 surprised → 回落 mood; 台词气泡短显示
```

### 4.4 A9 主动陪伴（有节制，v1.2c）

```
GUI 运行期：ProactiveScheduler(QTimer 30s tick)   ← 唯一触发源
  打点: 用户真实交互（ChatService.send_message / 气泡送达）→ interaction_occurred() 重置 idle
  tick 判定: enabled ∧ 非免打扰窗(22:30–08:00) ∧ 距上一条≥cooldown ∧ 今日<daily_cap
             ∧ 场景白名单: idle≥90min | 近5min owner_low | 近5min agent_done 未回复
  命中 → companion.json.proactive.count_today+1 落盘 → 组装模板句(context)
       → proactive_requested.emit(文本)
  MainWindow → ChatService.proactive_ask(文本)      ← 独立入口，非 send_message
       → ApiWorker kind="proactive"：session 历史 + 主动开场 system
         （明文禁止"假装主人先说话"；demo 模式不触发）
       → 流式 → assistant 气泡入会话(meta.proactive=True) → 主聊天面板 + chat_window 浮窗可见
       → 托盘静默气泡(无声音/无系统弹窗)；点击"去看"→激活浮窗
  防自续命: 主动消息不 bump_intimacy、不重置 interaction_occurred（真实用户交互才重置）
```

---

## 5. 任务列表（有序、含依赖，工程师按此消费）

### 5.1 依赖总览

- **两大可并行主干**：Track A（companion/心情/形象/UI，纯新增域 + GUI 呈现）与 Track C（C1–C4，agent/引擎/工具），二者仅在事件点（任务完成→成就/心情）交汇，用 `companion.ingest_event` 接口弱耦合 → 可并行开工。
- **Track C 内部严格串行**：C1(run_command) → C3(任务步骤化) → C2(步骤内自愈) → C4(任务上下文；最小版可与 C3 并行)。
- **Track A 内部**：A1/MoodEngine(纯逻辑) 与 B1/资产管线(纯资源) 可并行 → 之后再接线 B4/B5 广播 → 各呈现点。

### 5.2 Track C（推荐首先开工 C-1，因阻塞 PRD Q3 且独立无依赖）

| # | 任务 | 需求 | 依赖 | 备注 |
|---|---|---|---|---|
| C-1 | command_runner.py + 白名单判定表 + 授权接线 + run_command 注册 | C1-1 | — | **首先开工**；含超时/截断/锁；UI 诚实文案 |
| C-2 | agent 配置段扩展：`agent_max_retries/agent_command_timeout` + yaml 映射 + 设置页 Agent 区补充 | C1-1/C1-2 | C-1 | |
| C-3 | run_command 工具轨迹呈现 + 「非沙箱」标注 | C1-2 | C-1 | tool_trace 微调 |
| C-4 | C1–C4 集成演练场景（先修一个带失败单测的小函数链路，CI 断言） | C9 | C-1 | 可先行骨架 |
| C-5 | agent_task.py：TaskRun/TaskStep/TaskRunStore/断点恢复 | C3-1 | C-1 | C4 最小版可同人并行 |
| C-6 | agent_engine.run_managed_task：规划→逐步执行→事件 | C3-1 | C-5 | |
| C-7 | C2 内层自愈循环 + EVT_HEAL_TRY + 停止自愈 | C2-1/C2-2 | C-6 | |
| C-8 | tool_trace 步骤进度视图（步骤清单/高亮/进度条/折叠） | C3-2 | C-6/C-7 | |
| C-9 | C4 任务上下文压缩注入 + TaskRun.summary 维护 | C4-1 | C-6 | 与 C-7 可并行 |
| C-10 | C9 安全边界复核 + 授权回归 + 超时/中断/并发边界测试收口 | C9 | C-1..C-9 | C 主干质量闸门 |

### 5.3 Track A（companion + 形象 UI）

| # | 任务 | 需求 | 依赖 | 备注 |
|---|---|---|---|---|
| A-1 | companion.py：schema + CompanionManager + streak + on_app_open + 事件池 | A1/A2/A4 底座 | — | **可并行开工** |
| A-2 | MoodEngine 纯规则 + 输入采集钩子（ChatService/greeting/升级） | A1 | A-1 | |
| A-3 | 形象资产管线：MaidAssets + manifest + QPainter 占位回退 + spec datas | B1 | — | 与 A-1 并行 |
| A-4 | MaidAvatar 控件 + set_expression 统一 API + 缩略/圆裁缓存 | B1 | A-3 | |
| A-5 | companion_bridge（MoodBridge + 广播路由） | B4/B5 | A-1..A-4 | |
| A-6 | A2 每日动态卡 + 问候接入首页（模板先行） | A2 | A-2 | |
| A-7 | 首页改造为房间式（主形象常驻 + 快捷入口重组 + **关系称谓文本**，无进度条/分数） | B2/A5 | A-4/A-5/A-6 | A5 按 §3.9 红线收口 |
| A-8 | A3 彩蛋互动（点击→台词+表情+低频加分） | A3 | A-5 | |
| A-9 | A8/A8-1 角落微型宠物（MaidPet + 5 态 + tooltip + 窄窗折叠） | A8/A8-1 | A-5 | |
| A-10 | 气泡旁 Q 版头像 + thinking/focus/shy 联动 | B3 | A-4/A-5 | |
| A-11 | 侧栏形象入口 + 托盘心情扩展（tooltip 文案） | B5 | A-5 | |
| A-12 | A4 首批徽章触发点接线 + 首页徽章墙 | A4 | A-1 + C 主干事件点 | 依赖 C 事件：first_task/first_heal |
| A-13 | A9 主动陪伴：`proactive` 配置段 + `gui/proactive_scheduler.py` + `ChatService.proactive_ask()` 独立入口 + 浮窗/托盘静默气泡落点 + companion proactive 状态与 `current_mood_context()` | A9 | A-1/A-5；C-? 不强依赖 | 防冲突要点见 §3.10；单独产品决策可裁剪 |
| A-14 | 暴露面红线验收：全 UI 无心情/好感数值条（进度条/分数/Lv/打卡倒计时扫描） + C2/C9 收口项 | A1/A2/A5 红线 | A-7/A-11/A-13 | 配合 §3.9 表逐条核对，归零才放行 |

### 5.4 Track B8/B9（依赖 A-7 首页形态，与 Track C 无关可早做）

| # | 任务 | 需求 | 依赖 |
|---|---|---|---|
| U-1 | theme_engine 合并加载 base.qss + layout token + 语义色键注册（三主题） | B8 | — |
| U-2 | themes/base.qss 组件层初稿（新 UI 组件用；既有 QSS 收敛裁剪） | B8 | U-1 |
| U-3 | ModelConfigPanel + 设置页「模型与接口」专区替换 + 脱敏/连接态 | B9 | — |
| U-4 | 首页/侧栏模型直达入口 + scroll_to_model | B9 | U-3, A-7 或独立完成 |
| U-5 | 三主题 offscreen 截图回归（base 合并后不回归） | B8/零回归 | U-2 |
| U-6 | 全量 py_compile + v1.1 回归冒烟 + 收口验收（US1–US6 + C9 + A-14 红线归零） | DoD | 全部 |

---

## 6. 依赖 / 共享知识（跨文件约定）

1. **取色规范**：新 UI 一律 `theme_color(app_ctx, key, fallback)` 或对象 QSS 走主题变量；新增色键必须三主题 + `_base` token 同步注册，禁止裸色值。
2. **资源路径**：凡打包资源（形象、manifest）一律 `gui.utils.get_resource_path()`，spec datas 目标目录与其保持一致（`assets/maid`）。
3. **编码**：全部 JSON/QSS 读写显式 `encoding="utf-8"`；`_atomic_write_json`（`utils.py`）统一写 `~/.maid_coder/` 下文件，禁止裸 `open(...,"w")` 覆盖用户数据。
4. **模块风格**：`from __future__ import annotations`；dataclass 定义数据；manager 构造收敛在 `gui/main.py` 挂 `app_ctx.*`；页面/widget 一律从 `app_ctx` 取对象（`getattr` 守卫，缺省降级不崩）。
5. **中英命名**：表情/心情 ID 用英文短 id（`normal/happy/…`）；事件类型全小写下划线（与 agent_engine 事件命名一致）；中文注释；日志器 `logging.getLogger("maid_coder.gui")`。
6. **广播约定**：GUI 跨组件用 Qt Signal（`companion_bridge.mood_changed(str,str)`）；纯逻辑层只暴露回调/轮询，不 import Qt（保 CLI 可复用——Q5 CLI 文本化形态 P2 天然可接）。
7. **授权语**：run_command 文案口径统一「独立进程运行 · 受白名单约束 · 非沙箱」，与 README/utils.py 既有表述一致。
8. **事件 feed**：陪伴/成就统一经 `companion.ingest_event(type, data)` 进入；调用方只投递，不解耦判定——避免各 UI 各自写成就逻辑。
9. **PyInstaller**：新增模块全部进 spec hiddenimports（`companion/command_runner/agent_task/gui.maid_assets/gui.widgets.maid_pet/gui.companion_bridge`），形象目录进 datas；打包路径与 `get_resource_path` 对齐（防 v1.0 themes 坑重演）。
10. **低侵入总线**：`chat_service` 层只加 `companion.…` 的 `getattr(app_ctx,'companion',None)` 守卫调用，禁止 companion 反向依赖 GUI。

---

## 7. 风险与待明确

| # | 风险 / 待明确 | 影响 | 缓解 / 责任方 |
|---|---|---|---|
| R1 | QSS base 合并重构触碰三套既有样式，存在零回归压力 | B8 落地范围 | 分两段：v1.2 只改 base 覆盖的新组件，全量 sweep 到 P2；U-5 offscreen 截图回归 + 主题切换即时生效断言；责任人 UI |
| R2 | GUI 当前发送路径未接 memory 提取/detect_emotion（原在 CLI session 内），mood 输入需补钩子 | A1 | ChatService.send_message/_on_stream_finished 加两处守卫调用；注意不与 intimacy 重复加分、无回路 |
| R3 | `run_command` 跨平台差异：Windows 控制台弹窗/`python` vs `python3`/venv 解释器选择；路径参数识别启发式误判 | C1 | `CREATE_NO_WINDOW`；解释器走 `sys.executable` 兼容；路径校验 resolve 制；判定表作为验收标准过安全审计（C-10） |
| R4 | 模型可能绕 run_command 白名单（如把命令写进参数、用超长路径/`-k` 注入） | C1 安全 | argv 直传无 shell + 语法白名单 + 输出/超时兜底；C9 做绕过测试用例；无授权渠道一律拒 |
| R5 | C2 步骤通过判定依赖 LLM 声明 + 最近一次 run_command exit_code，模型可能误报完成/假失败 | C2/C3 | 判定契约写入 planner prompt；`agent_max_retries` 上限兜底；GUI 停止自愈兜底；记录为已知边界 |
| R6 | 跨进程并发（CLI+GUI 同时跑 run_command 于同 workspace）未做互斥 | C1-2 | v1.2 进程内互斥（会话级），文档标注；跨进程锁 P2 |
| R7 | 心情状态在长会话/长时间挂机时可能「过期」（如深夜切清晨仍是 tired） | A1 | mood 每次事件/打开重算；MainWindow 低频 QTimer（≥1h）仅时段驱动 refresh；与 A9 调度定时器各自独立，互不混用 |
| R8 | 成就「JSON 配置」与实现选「Python 常量」的偏差 | A4 | 已同步 PM；若要求 JSON 化，抽数据文件 + spec datas 即可 |
| R9 | A8 宠物位置与窄窗折叠的具体呈现细节尚未最终裁决（Q2 已放权 UI） | A8 | 建议：主窗级右上角独立 overlay widget（resizeEvent 定位、宽<阈值隐藏、可配置关闭），最终 UI 定 |
| R10 | 托盘图标 v1.2 形态（Q5 残留） | B5 | 建议最小实现：托盘 tooltip 随 mood 更新 + 3 态小图标（normal/thinking/tired）复用缩略管线；图标替换若成本高仅做 tooltip |
| R11 | 主形象 AI 出图风格一致性 / 何时到位 | B1 | 资产管线+占位脸先行验收不依赖美术（PRD §6.4 口径），出图仅影响观感 |
| R12 | `run_managed_task` 对 agent_engine 的改动属「高」风险区 | C3 | 严格只加不改：run() 原样、新事件只增、注入用临时 user 项即用即删；C-10 回归把关 |
| R13 | A9 主动消息触及聊天历史/渲染/持久化主链路，若误走用户路径会造成气泡回显污染 | A9 | `proactive_ask()` 独立入口 + kind="proactive" 路由 + meta.proactive 标记 + 无 echo/不 bump_intimacy/不算交互打点；免打扰窗与 daily_cap 硬约束；C-10/U-6 验收含「免打扰时段零触发」断言 |
| R14 | `summary_dict()`/intimacy getter 带数值，若 GUI 误接会违反「无数值焦虑」红线 | A1/A5 | A-14 扫描验收（进度条/分数/Lv/倒计时零残留）+ 代码 review 把关；CLI 文本态 P2 才允许消费数值 |
