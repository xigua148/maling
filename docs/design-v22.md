# 码铃（MaLing）v2.2 增量架构设计 ——「酒馆」独立功能域（中大型 · 高自由度 · 零新增第三方依赖）

- 版本：v2.2（增量设计，格式对齐 design-v16 / v17 / v18 / v19 / v20 / v21）
- 文档状态：**草案**；team lead 已按"最佳体验"口径锁定 Q1–Q4（见 §1.2），本文照此执行；其余开放项按 research 建议值收敛（§11 记录唯一一处"建议复议"）
- 维护人：高见远（架构）
- 关联文档（按权威度）：
  - **`docs/research-tavern-game.md`（v3，1133 行，权威需求来源）** —— §2 机制拆解 / §3 设计方法论 / §4 高自由度落地 / §5 现状盘点 / §6 中大型设计 / §7 分批 / §8 界面 / §9 融合点 / §11 风险与 Non-goals / 附录 B 诚实声明
  - **`docs/research-tavern-oss.md`（开源选型结论）** —— **不引任何第三方代码**；唯一可选采纳 = `kwaroran/character-card-spec-v3`（MIT）作为**规范引用**（只引字段模型 + 链接）
  - `docs/design-v21.md`（**格式基准**；§3.3 保护区清单 / §5 分批任务格式）+ `docs/prd-v21.md`
  - `AGENTS.md`（红线口径）、`README.md`、`docs/THIRD_PARTY.md`（许可白名单与适用范围）
- **基线：v2.1.x**（四风格 / 六字体 / 矢量图标 `gui/icons.py` / 动效 `gui/motion.py` / 毛玻璃 `gui/glass.py` 均已上线；自动更新链在 v2.0 已上线）
- 设计纪律重申：**功能面零改动**（聊天 / 记忆 / 陪伴 / 群聊 / Pi / 自动更新链零触碰）；**不新增任何运行时第三方依赖**（R-F：`requirements*.txt` diff 必须为空）；**不 vendor / 不移植任何第三方代码**（守 research-oss 结论）；工作副本仅限 `maling_agent_dev/` 与 `docs/`。

---

## 1. 范围与现状基线（先读我）

### 1.1 范围与 Non-goals

**做什么（本次范围）**：把「酒馆」做成**一整个独立功能域** —— 女仆当**老板娘兼说书人**，你既能**点选项**也能**自由打字**；真相（世界状态）存在**本地状态机**里、只由一组**受控变换**改写；LLM 负责**写作**与**提议变换**（提议必须过本地校验器才落地，不通过就降级为纯叙述并留痕）。

| 块 | 内容 | 落点 | 复用 vs 新增 |
|---|---|---|---|
| **D 数据层** | `tavern.json` schema v1 + 原子写 + 读时迁移 + 快照轮转 + 坏档恢复 | 新 `gui/tavern/model.py` / `store.py` | **全新增**（复用 root `utils._atomic_write_json` 与 `companion.py` 的 `_merge_defaults` 范式） |
| **E 引擎** | 7 条受控变换（pre/post）+ 3 条不变量 + 6 条硬禁区 + 显式 seed | 新 `gui/tavern/engine.py` | **全新增**（纯逻辑零 Qt） |
| **R 路由** | 三级意图路由（verbatim / propose / narrate）+ 全留痕 | 新 `gui/tavern/intent_router.py` | **全新增**；词表/正则写法照抄 `gui/intent.py` |
| **W 世界书** | 关键词触发 + selective logic + 字符预算裁剪 + 递归上限 + 脏数据容错 | 新 `gui/tavern/worldbook.py` + `content/**` | **全新增**（关键词触发与既有 `helpers.KnowledgeBase` 同源） |
| **P prompt/摘要** | 五段式 `build_story_prompt` + reroll 差异 + 摘要落盘校验 | 新 `gui/tavern/prompt.py` / `summarize.py` | **全新增**；复用 `api.py` 调用层与流式 worker 写法 |
| **U UI** | 侧栏新页 + 5 Tab（今夜/世界书/我的故事/人物/记录） | 新 `gui/pages/page_tavern.py` + `gui/widgets/tavern/**` | **全新增**；取色走 `theme_color`，图标走 `gui/icons.py`，动效走 `gui/motion.py` |
| **I 接线** | 侧栏纯增 1 项 + 快速开局浮窗 + AppContext 末位字段 + 页注册 | 改 `sidebar.py` / `extras.py` / `app_context.py` / `main_window.py` | **纯增**（既有 10 项导航 / 既有入口零回归） |
| **X 收口** | 双 spec 随包 + 授权登记 + 红线扫描 + 全量回归 + 真机留档 | 改两 `*.spec` / `THIRD_PARTY.md` / `README.md` / `CHANGELOG.md` | 串行收尾 |

**Non-goals（明确不做，逐条对齐 research §7.1 / §11.2 / research-oss §5）**：

1. **不引任何第三方代码 / 不 vendor**（research-oss §5.1：SillyTavern 是 Node + AGPL-3.0，**否决性**；纯 Python 零依赖候选只有 `pytwee`，净收益≈0）。**不新增任何运行时第三方依赖**（R-F）。
2. **不做 WebView / 不引游戏引擎**（码铃是 PySide6 纯 Widgets）。
3. **不做战斗 / 等级 / HP / 经济 / 行动点 / 体力 / 每日次数 / 排行榜 / 分享排行**（撞 R-A 无焦虑红线）。
4. **不做好感度 / 亲密度数值展示**（Q2：关系只读不写，见 D-V22-04）。
5. **不做脚本语言 / 插件执行面**（STscript 类一律不引；"按钮 → 受控变换 id 映射表"即够）。
6. **不做 prompt 拖拽编辑器**（对码铃用户是纯负担）。
7. **不做向量检索**（零依赖约束下不可能；关键词 + 摘要已能覆盖单机叙事）。
8. **不改 `ChatService` / `session` / `memory` / `companion` / `persona`**（酒馆自带数据层与 prompt 组装，与聊天域零耦合）。
9. **不改 `GuiConfig`**（settings 全部放 `tavern.json.settings`，从根上绕开 `save()` 逐键列举陷阱，D-V22-08）。
10. **不触碰保护区**（v2.0 更新链 / `main.py` 更新编排 24 函数 / 四风格色值 / `fonts.py` + 字体资产 / 美术资产 / 依赖清单 / `version.json`）。

### 1.2 team lead 已拍板的 4 个决定 → 机制映射（**不得推翻**）

| # | 决定 | 落为哪条机制 | 本文落点 |
|---|---|---|---|
| **Q1** | `propose` 档：**做，默认开启**，可在设置里关闭 | 三级路由的 `② propose` 档位 + `tavern.json.settings.allow_propose` 默认 `true`；关闭时退化为"完全确定模式"（仅 ①verbatim + ③narrate） | D-V22-02 / D-V22-03；§4.2 / §5.2 |
| **Q2** | **一期对"关系/好感度"只读不写** | 酒馆**读取**既有亲密/关系状态（`companion.relation_stage_name()` / `app_ctx.intimacy.level_name()`）来决定老板娘语气与称呼（产生"她认得你"的连续感），**绝不写入**任何好感/亲密数据 | D-V22-04；§5.6 |
| **Q3** | 入口 = **侧栏新增独立「酒馆」页**（中大型形态，不是浮窗小玩法） | `sidebar.NAV_ITEMS` **纯增 1 项** + `page_tavern.py` 页 + 5 Tab；**另保留一个"快速开局"浮窗入口**（低摩擦，两条并存不冲突） | D-V22-01；§6.1 / §8.3 |
| **Q4** | 界面**不出现「第 N 夜 / 第 N 幕」序号**，只显示**章标题** | UI 只渲染 `chapter.title`（如"灯笼还亮着"）；**任何序号标签一律不上屏**（项目既有 R-A 弧线零数字口径） | D-V22-05；§6.2 / §4.1 |

### 1.3 已核实的关键对接点（v2.1.x 源码逐行核，**禁止照抄旧记忆**）

| 对接点 | 位置（**本次已核**） | 酒馆怎么用 |
|---|---|---|
| **原子写工具** | **root `utils.py::_atomic_write_json(path, data)`**（`tmp = path + ".tmp"` → `json.dump(ensure_ascii=False)` → `os.replace`）—— ⚠️ **不在 `gui/utils.py`**（该文件**无**此函数）；`companion.py:309` 另有一份**同语义私有副本** | 酒馆 store **统一 `from utils import _atomic_write_json`**（D-V22-07）；**不要**沿 `session_manager.save_session()` 的非原子写（research §5.3 缺陷） |
| **业务数据目录** | `companion.py:300` = `os.path.expanduser("~/.maid_coder")`；**GUI 配置** `gui/utils.get_user_data_dir()` = `%APPDATA%\maid_coder`（存 `gui_config.json`） | 酒馆**只写 `~/.maid_coder/tavern/`**，**不碰 `%APPDATA%`**（research §5.3 双轨缺陷的规避） |
| **读时迁移范式** | `companion.py`：`_default_data()` → `_merge_defaults()`（`setdefault` + `isinstance` 类型守卫）→ `_save()` 单写点 → `_atomic_write_json` | 酒馆 `model.py` 照抄此范式（D-V22-07）；**未知字段不销毁** |
| **`GuiConfig.save()` 逐键列举陷阱** | `gui/config.py:153-235`：`save()` 把每个键**逐条显式列出**，漏改 `__init__` 或 `save()` 则**静默不持久化**（源码注释已自警："新增键必须同时改 __init__ 与本类 save()"） | 酒馆**不改 `GuiConfig`**（D-V22-08）——所有酒馆设置放 `tavern.json.settings`，从根上绕开 |
| **`AppContext`** | `gui/app_context.py`：`@dataclass`，末位 `current_role: str = "default"` | 末尾**纯增** 1 字段 `tavern: Any = None`（D-V22-14；纯增兼容既有构造） |
| **侧栏导航** | `gui/widgets/sidebar.py:109-120`：`NAV_ITEMS` = **4 元组 × 10 项** `(key, label, icon_name, fallback_text)`；`item_clicked = Signal(str)` 传出 `key` | **纯增 1 项** `("tavern", "酒馆", <已登记图标名或 None>, <emoji 回退>)`；既有 10 项 key/label/信号零变更（D-V22-01 / 见 §1.4 校正①） |
| **页面注册** | `gui/main_window.py:250-282`：`_setup_pages()` 内 `page_classes = [(key, cls, title), ...]`，页以 `cls(self.app_ctx, title)` 构造；`PageManager(page_stack, pages)` | 追加一项 `("tavern", PageTavern, "酒馆")` + 顶部 import（D-V22-14） |
| **页面路由** | `gui/page_manager.py`：`PageManager.navigate(key)` / `page_changed(str)` / `page.on_enter()` 生命周期钩子 | 酒馆页实现 `on_enter()`（刷新列表/关系语气），零改 PageManager |
| **浮窗入口范式** | `gui/widgets/chat_panel_parts/extras.py:477-487`：`_open_mini_games()` = 懒 import + `setAttribute(Qt.WA_DeleteOnClose)` | "快速开局"入口照此写法（D-V22-01；约 12 行） |
| **动效内核 API** | `gui/motion.py`：`configure/level/enabled/duration/animate/fade/stop_all/running_count` + 循环 `loop/stop_loop/loop_period_ms`；`MAX_DURATION_MS=220`、`MIN/MAX_LOOP_PERIOD_MS=800/1600` | 酒馆动效**只用既有能力**（D-V22-13；§7） |
| **图标内核 API** | `gui/icons.py`：`available/has/glyph/icon/font/text_glyph/configure/clear_cache`；`text_glyph(name, fallback)` 缺资源返回 fallback | 快捷动作/按钮图标**只走 `icons.icon()` 或 `icons.text_glyph()`**，禁裸 emoji 上屏、禁自拼 `chr()` |
| **取色唯一入口** | `gui/utils.theme_color(app_ctx, key, fallback)` | 酒馆所有代码侧取色一律走它；QSS 只引 token |
| **聊天注入门控** | `gui/chat_service.py:1247` `send_message(..., task_type="chat")`；`request_injections` 仅在 `task_type=="chat" and not self._agent_mode` 生效（`:1284/:1307/:1359`） | 酒馆**不挂进 ChatService**（避免污染会话/注入序位/计费口径）；酒馆自带 prompt 组装 |
| **LLM 调用层** | `api.py:42-91` `chat(...)`（非流式）/ `api.py:93-101` `chat_stream_chunks(...)`（流式）；`gui/chat_service.py:1017-1113` `ApiWorker._run_stream()` 流式 worker 范式；`:534` `_is_demo_mode()`；`:575` `inject_maid_tone()` | `propose` 走一次小 `chat()`（`max_tokens ≤ 80`、严格 JSON）；叙述走 `chat_stream_chunks`；"LLM 不可用"提示沿用 `_is_demo_mode` 的中性语义；说书人提示照 `inject_maid_tone` 写法 |
| **关系/亲密（只读）** | `companion.py:565` `relation_stage_name()`；`intimacy.py:241` `level_name()` / `:252 stage_privileges()` | Q2：**读**这两个（+ `utils.brand_persona_self` 的自称规则）拼"老板娘语气"；**绝不写** |
| **关于页第三方表** | `gui/pages/page_about.py:15` `_THIRD_PARTY_ITEMS`（含字体/图标条目） | 若采纳 CCv3，**只登记到 `THIRD_PARTY.md` 参考未采用表**，About 页**不加行**（非随包组件） |
| **打包 spec** | `maid_coder_gui.spec:22-59` datas（`gui/themes→themes`、`gui/assets/icons→assets/icons` 等）+ hiddenimports；`maid_coder_gui_onefile.spec` 同构；`get_resource_path()`（`gui/utils.py:12-18`）frozen 以 `_MEIPASS`、源码以 `gui/` 为基准 | 内容包 datas **目标目录必须等于源码相对路径**（见 §1.4 校正②）；**双 spec 同步** |
| **测试范式** | `tests/` 既有 `conftest.py`；GUI 测试须 `QT_QPA_PLATFORM=offscreen`；受管解释器 `.workbuddy/binaries/python/.../python` | 酒馆纯逻辑可 offscreen / 无显示单测（D-V22-06） |

### 1.4 ★ 对 research 文档的落点校正（**诚实指出，不照抄错误前提**）

核对现状代码后，发现 research 文档有 3 处落点需**更正/补全**（team lead 已要求直接指出）：

| # | research 原文 | 事实（本次核） | 本文采用 |
|---|---|---|---|
| **①** | §6.1 设想"`gui/tavern/__init__.py` 对外只暴露 `get_tavern(app_ctx)`"，并称"除 `__init__.py` 的 controller 例外，`gui/tavern` 不 import Qt" | 若把 Qt controller 放进 `__init__.py`，则 `import gui.tavern.model` 会先执行 `__init__.py` → **触发 Qt 导入**，与"纯逻辑零 Qt、可无显示环境单测"的**核心承诺自相矛盾** | **`gui/tavern/__init__.py` 保持零 Qt**（只导出常量与懒查函数）；**Qt controller 另立 `gui/tavern/service.py`**（D-V22-06） |
| **②** | §6.4 写 spec `datas +('gui/tavern/content','tavern_content')` | `get_resource_path(rel)` 在**源码态**解析为 `gui/<rel>`，在**frozen 态**解析为 `_MEIPASS/<rel>`。若 target=`tavern_content`，源码态查 `gui/tavern_content`（**实际不存在**，真路径是 `gui/tavern/content`）→ **源码态读不到内容包** | **target 必须 = 源码相对路径**：`datas +('gui/tavern/content','tavern/content')`，loader 用 `get_resource_path("tavern/content")`（D-V22-15）；**"两态都要能读到"的验证法见 §3.2 附注**（与既有 `('gui/assets/icons','assets/icons')` 同构：约定 `source_dir == gui/<target>`） |
| **③** | §5.4 / §8.4 只说 sidebar "纯增 1 项（4 元组结构不变）"，未提图标名依赖 | 侧栏第 3 元是**已登记的图标语义名**（`gui/assets/icons/icons_manifest.json`，**共 151 名**，顶层即 `{name: codepoint}`）。本次逐项核 `sidebar.NAV_ITEMS`（`sidebar.py:109-120`）实占登记名 = `chat` / `home` / `auto_awesome` / `menu_book` / `edit` / `list` / `person` / `settings` / `tune`（**9 名**）；**第 10 项 `("project","项目",None,"📁")` 第 3 元是 `None`**（走 `QIcon.fromTheme("folder")`）→ **不占登记名**，这正是"只数到 9 项"之因；**已定：复用登记名 `glass`（酒杯，codepoint 60376，`icons_manifest.json` 实存且未被任何导航项占用）** —— **零构建、不新建图标**；第 4 元 emoji 回退 = **`🍷`（U+1F377，与"酒杯"语义一致）**（D-V22-01 附注 / §3.2 / §6.1）。⚠️ **`menu_book` 已被「记忆中心」占用，切勿复用** |

> 其余 research 落点（`session._trim_history` / `auto_summary` 在 root `session.py`、`helpers.KnowledgeBase` 关键词+TF-IDF）**本次未复读**，按 research 记录**留待实现期复核**，不在本文断言。

---

## 2. 架构决策（D-V22-01 ~ D-V22-15）

> 每条格式：**决策 / 理由 / 被否决的替代方案**。D-V22-02/03/04（路由与只读关系）与 D-V22-05（零序号）为红线相关高危区，写最细。

### D-V22-01 入口形态：侧栏独立页 + 5 Tab + 保留快速开局浮窗（Q3）

**决策**

- **主入口**：`sidebar.NAV_ITEMS` **纯增 1 项**（4 元组结构不变）→ 独立页 `PageTavern`（页内 5 Tab）。
- **第二入口**：`chat_panel_parts/extras.py` 工具行加一个"快速开局"按钮（约 12 行），复用 `_open_mini_games()` 的**懒 import + `WA_DeleteOnClose`** 范式，直接开一局**不切页**。两条入口并存不冲突。
- **5 Tab**（P0 只做前 3 个）：`今夜`（叙述流 + 输入 + 快捷动作）／`世界书`（条目表 + 预算读数）／`我的故事`（存档列表 + 继续/回看）／`人物`（老板娘与客人卡，P1）／`记录`（`applied` 留痕 + 摘要，只读调试面，P1）。
- **导航图标名（已定，可固化）**：复用既有已登记名 **`glass`（酒杯）**（`icons_manifest.json` codepoint 60376，**未被任何导航项占用** → 零构建、不新建）；第 4 元 emoji 回退 = **`🍷`（U+1F377）**（不空白、不崩）。新增项 = `("tavern", "酒馆", "glass", "\U0001F377")`。⚠️ 禁复用 `menu_book`（已属「记忆中心」）。（见 §1.4 校正③ / §3.2 / §6.1）

**理由**：中大型功能需要自己的地盘与信息层级（research §5.4）；浮窗入口提供"低摩擦"并存价值；4 元组已是 v2.1 现状，纯增零回归。

**被否决的替代方案**：❌ 独立浮窗（v2 方案，承不住中大型：无导航、无多 Tab、无"我的故事"列表）；❌ 独立顶层窗口（与"主窗即工作台"信息架构冲突）；❌ 只做侧栏页不给浮动入口（丢掉"随手开一局"的低摩擦）。

### D-V22-02 三级意图路由：verbatim / propose / narrate（Q1）

**决策** —— 自由输入先经**本地意图解析（零 token 优先）**，分三档处理（精确定义见 §4.2）：

| 档 | 触发条件 | 谁有权改状态 | 失败行为 | 留痕 |
|---|---|---|---|---|
| **① verbatim** | 输入命中**受控意图词表**（主路径，零 token，复用 `gui/intent.py` 的"词表 + 句式正则 + 逐条 `try/compile`"写法） | 本地规则函数 | 前置不满足 → 降级到 ③ | 是（`mode:"verbatim"`） |
| **② propose** | 未命中词表，但自由输入"形状可识别" | **LLM 只提议**，**执行权在校验器** | 校验不过 / LLM 不可用 / 超时 → 降级到 ③ | 是（`mode:"propose"`, `ok`, `reason`, `llm_used`） |
| **③ narrate** | 完全无法识别，或 ①② 失败 | **无人** | —（终态） | 是（`mode:"narrate"`） |

- **不是"一刀切拒绝"**：绝大多数常见语义做成 `verbatim` 白名单，命中即改。
- **也不是"随便就改"**：`propose` 把**写权留在本地**（LLM 只能从**枚举清单**里选，且执行前必须过校验器）。与 arXiv:2605.24719 架构一致（LLM 预测变换 → 符号层执行 + 校验）。
- **降级不是静默吞掉**：任何一次"没能施加"都写进 `transcript[turn].applied`（含 `reason`），用户可在「记录」Tab 看到；**绝不因一次没识别就报错弹窗**。
- **超时与 LLM 关闭走同一条代码路径**（避免"只有网络慢时才炸"的偶发脏数据）。

**理由**：用户要"很高的自由度"（Q1），① 与 ② 共同构成自由度；而 `propose` 的可靠性**未被学术证明**（research §3.3 / 附录 B-6），故三级排序本身就是**对"未证明可靠性"的风险对冲**。

**被否决的替代方案**：❌ v2 的"自由输入一律不改状态"（那就不是高自由度）；❌ 让 LLM 直接写状态（把数据交给黑盒）；❌ 只做 ② + ③（丢掉零 token 主路径）。

### D-V22-03 `propose` 档默认开启、可在设置关闭（Q1）

**决策**

- `tavern.json.settings.allow_propose` **默认 `true`**（Q1 定稿）；`false` 时**退化为完全确定模式**（仅 ① + ③）——已命中的 `verbatim` 仍生效，仅**不发起** LLM 提议。
- 开关落在 `tavern.json.settings`（**不改 `GuiConfig`**，D-V22-08）；UI 入口在「今夜」Tab 或「世界书」Tab 的设置行，配一句中性说明（R-A：**禁**"性能/准确率/落后"等焦虑词）。
- 关闭时**不创建任何 LLM 提议请求**（可断言：`intent_router.route()` 在 `allow_propose=False` 时**不调用**注入的 LLM client）。

**理由**：Q1 定稿"默认开、可关"是把"自由 vs 可控"做成**用户可选的旋钮**，而非二选一（research §4.2-4）。

**被否决的替代方案**：❌ 默认关（多数用户不会发现它）；❌ 不给开关（数据洁癖用户无退路）。

### D-V22-04 关系/好感度：**只读不写**（Q2）

**决策**

- 酒馆在**构建拼 prompt 的当前回合**时，**读取**（只读，不修改）：
  - `app_ctx.companion.relation_stage_name()`（关系阶段名，自然语言，如"亲近"）；
  - `app_ctx.intimacy.level_name()`（阶段名，兜底）；
  - `gui/utils.brand_persona_self(app_ctx)`（界面自称规则，取 `persona.self_reference`）。
- 读到的结果拼成一段**只读的 `relation_ctx`**（如 `{"stage_name": "亲近", "self_ref": "我"}`），**作为参数传入** `build_story_prompt(...)`；用于老板娘的语气与**称呼**（产生"她认得你"的连续感）。
- **一期绝不写入任何好感度/亲密数据**：`gui/tavern/**` **不 import** `intimacy` / `companion` 的**写**接口；store **不落盘**任何关系数值；`relation_ctx` **不持久化**（每回合现读现用，或用即弃的显示缓存，**绝不回写**）。
- **UI 不展示任何关系数值**（R-A）：只可显示**自然语言称谓**（与 `page_home.py` / `sidebar.py` 既有口径一致）。

**理由**：兼顾"陪伴连续性"（最佳体验核心）与"数据不乱"（不污染陪伴数据）。读取是零风险高收益；写入留到后续版本单独评估（research §11.3 Q2）。

**被否决的替代方案**：❌ 写进 `intimacy`（产生"玩故事能刷关系"路径，撞 R-A 防"刷好感"精神）；❌ 只在「我的故事」留一句可读的话但写业务数据（仍要写业务数据）。

### D-V22-05 界面零序号：只显示章标题（Q4）

**决策**

- 「今夜」Tab 顶部与「我的故事」列表项**只渲染 `chapter.title`**（如"灯笼还亮着"），**绝不渲染**"第 N 夜 / 第 N 幕 / 第 N 章"这类序号。
- `chapter_id` / `node_id` / `turn` 等**仅存在于数据层**，**不上屏**（R-A 弧线零数字口径）。
- 代码级可断言：UI 文案扫描**零命中**序号正则（`第\s*\d+\s*(夜|幕|章|回|关)`）。

**理由**：项目既有 R-A 红线（弧线零数字、不给主人打分/计量），team lead 定为硬约束。

**被否决的替代方案**：❌ 显示"第 N 夜"（更"像游戏"但撞 R-A；用户未授权）。

### D-V22-06 纯逻辑内核零 Qt + 文件域切分

**决策**

- `gui/tavern/` 下 **`model / store / engine / intent_router / worldbook / prompt / summarize / errors`** 全部**零 Qt**（只依赖标准库 + `utils._atomic_write_json`）；**`__init__.py` 也零 Qt**（见 §1.4 校正①）。
- **Qt controller 另立 `gui/tavern/service.py`**：`TavernService`（持 store + 发 LLM 请求 + 向 UI 发信号）。它是**唯一** import Qt 的酒馆内核文件；缺失时 UI 静默降级。
- 分层方向：`gui/pages` / `gui/widgets` → `gui/tavern`（单向）。**`gui/tavern` 不 import 任何 Qt**（除 `service.py`），因此绝大部分逻辑**可在 offscreen / 无显示环境下测**。

**理由**：把"世界怎么改状态"与"界面怎么画"彻底解耦，纯逻辑可无 Qt 单测（research §6.1 的分层目标）；同时修正 research 的 controller 落点矛盾（§1.4 校正①）。

**被否决的替代方案**：❌ controller 放 `__init__.py`（破坏零 Qt 承诺）；❌ 把逻辑与 UI 混在 `gui/widgets/tavern/**`（无法纯函数单测）。

### D-V22-07 数据层：落 `~/.maid_coder/tavern/` + 原子写 + 读时迁移 + 快照轮转

**决策**

- **落盘位置**：`~/.maid_coder/tavern/tavern.json`（单文件，顶层 `schema_version`）；**跟随既有业务数据 `~/.maid_coder`**（`companion.py` / `memory.py` / `session_manager.py` 同源），**不碰 `%APPDATA%\maid_coder`**。
- **原子写**：`store.save()` → **`from utils import _atomic_write_json`**（root，`tmp + os.replace`）。**必须先 `Path.mkdir(parents=True, exist_ok=True)`**（该工具**不建父目录**），并**先 `json.dumps` 校验可序列化**再写。
- **单写点**：所有落盘只经 `TavernStore.save()`。
- **读时迁移**：`model.merge_defaults(data)` = 默认结构为底 → `setdefault` → `isinstance` 类型守卫；**未知字段不销毁**（前向兼容，对齐 `role_card.py` 铁则）。
- **写前快照轮转**：保留最近 N 份 `tavern.json.bak.N`（异常可回滚）。
- **显式 seed**：任何本地随机走 `random.Random(seed + turn)`，**不依赖全局 `random`**（既有 `game_2048.py` 用全局 `random` 不可复现，**不沿用**）。

**理由**：数据不乱的第一道防线；绕开 research §5.3 指出的两处既有缺陷（双目录、非原子写）。

**被否决的替代方案**：❌ 落 `%APPDATA%`（业务数据双轨加剧，用户困惑）；❌ 复用 `session_manager.save_session()`（非原子写）；❌ 多文件分片（单机单局规模无需）。

### D-V22-08 设置放 `tavern.json.settings`，**不改 `GuiConfig`**

**决策**

- 酒馆的**全部设置**（预算/扫描深度/递归上限/摘要间隔/`allow_propose`/`allow_free_input`/`llm_narration` 等）**放 `tavern.json.settings`**，与存档**同文件、原子写**。
- **不新增任何 `GuiConfig` 键**（`gui/config.py` 零改动）——从根上绕开"`save()` 逐键列举漏改即静默不持久化"的陷阱（research §5.3 缺陷 2）。
- 若未来**确需**在设置页暴露某键并进 `GuiConfig`，**必须同时改 `__init__` 与 `save()`**（把坑写进设计）。

**理由**：settings 与存档同源、随档迁移，语义更准；且规避 `GuiConfig` 的已知陷阱。

**被否决的替代方案**：❌ 放 `GuiConfig`（要同时改 `__init__` + `save()`，且酒馆设置与 GUI 全局设置语义不齐）。

### D-V22-09 世界书：关键词触发 + selective logic + **字符预算**（近似，如实标注）

**决策**

- 条目字段（照搬公开规范字段模型，**不摘录任何规范正文**）：`uid / title / keys[] / secondary_keys[] / selective_logic / content / position / depth / order / weight / constant / probability / sticky / cooldown / recursive / case_sensitive / enabled / budget_chars_est`。
- **触发**：`keys` 主键扫最近 `scan_depth` 拍；`secondary_keys` + `selective_logic`（`AND_ANY / NOT_ALL / NOT_ANY / AND_ALL`）做组合精化。
- **预算**：**字符预算（非 token）** —— 单条 `content ≤ 200 字`，总量 `worldbook_budget_chars`（默认 1600，建议区间 1200–2000）；超预算按 **`weight` 降序 → `order` 降序 → `uid` 升序** 截断。**UI 与文档只说"约 X 字"，不承诺 token 数**。
- **落点**只三种：`system_head`（世界规则）/ `system_tail`（本回合情境）/ `history_depth`（历史内指定深度）。**不做 role=assistant 注入**（会污染既有语义）。
- **正则 key** 允许，但**逐条 `try/compile`，编译失败静默丢弃**（照抄 `gui/intent.py` 的既有写法，避免"一条脏规则炸掉整本世界书"）。
- **递归默认关**，实现带**深度上限（默认 2）+ visited 集合**（防 snowball）。
- **来源两级**：`builtin`（随内容包发布）+ `play`（本局/本卡绑定）。**不做三层**。
- **`constant` 上限 5 条**；违规条目**加载时禁用并记日志，而不是崩**。
- **`ignore budget` 不实现**（会让安全阀失效）。

**理由**：关键词触发与既有 `helpers.KnowledgeBase`（关键词 + TF-IDF）同源；码铃**无 tokenizer 且零依赖**，故 token 预算必须降级为字符预算并**如实标注为近似**（research §2.2 / 附录 B-3）。

**被否决的替代方案**：❌ 向量检索（零依赖下不可能）；❌ 三层来源（单人桌面场景收益低、调试成本高）；❌ 自称"token 预算"（不诚实）。

### D-V22-10 prompt 组装：五段式纯函数 + reroll 差异

**决策**

- 酒馆**不挂进 `ChatService`**；自带纯函数 `build_story_prompt(state, book, play, *, relation_ctx, mode="normal"|"reroll") -> list[dict]`。
- 内部分层**固定五段**：`[system] 说书人规则（长度/视角/禁项） → [system] 世界规则（constant 条目） → [system] 角色卡（她是谁/怎么行动/语气样本） → [system] 本回合情境（vars 摘要 + 命中条目 + 本回合发生了什么） → [history] 近 N 条叙述 + 【前情提要】`。
- `Triggers` 只落两种：`normal` 与 `reroll`；**`reroll` 时"本回合必不携带上一版文本"**（防重掷总生成同一句）。
- **可观测性**：提供"看这一回合实际发了什么"的开发者入口（「记录」Tab，沿用 `tool_trace` 既有形态）——线上出问题可归因。
- **不引入 prompt 拖拽编辑器**。

**理由**："位置即权重"是 prompt 工程最实用的一条（research §2.3）；纯函数可单测。

**被否决的替代方案**：❌ 接入 `ChatService`（污染会话、注入序位与计费口径）；❌ 拖拽式 prompt 编辑器（对码铃用户是纯负担）。

### D-V22-11 摘要：落盘为结构化字段 + 落盘前校验

**决策**

- `transcript` 逐字保留**最近 N 拍**（默认 14，`settings.transcript_keep_turns`）；更早的压缩进 `summary`。
- `summary` 是**存档里的结构化字段**（`summary.text` + `summary.up_to_turn` + `generated_by` + `verified`），**不是 prompt 里的临时拼接**；一旦写入即数据，**原子写 + 版本化**。
- **触发**：本地规则（每 `auto_summary_every=8` 拍或进入新章）。**可选由 LLM 生成文本**，但**生成结果在落盘前必须过基本校验**：非空、长度上限、不含"玩家的选择是什么/他想要…"这类**越权臆断**；不通过 → 拒绝入库（保留旧摘要）。
- 世界书（D-V22-09）承担**长期事实召回**（≈ 无向量版的 RAG）。

**理由**：把"记忆"从易失 prompt 提升为可迁移存档；对"AI Dungeon 式遗忘"从制度上设防（research §2.5）。

**被否决的替代方案**：❌ 让 LLM 自由写记忆（与码铃"结构化记忆、LLM 不自由写"价值观冲突）；❌ 摘要只放 prompt 不落盘（无法归因/迁移）。

### D-V22-12 降级铁律：LLM 不可用/超时/垃圾 一律不留坑

**决策（硬要求）**

- **`propose` 与叙述生成**的全部失败路径（LLM 关闭 / 超时 / 返回畸形 JSON / 抛异常）**与"LLM 关闭"走完全同一条代码路径** → 降级为 ③ `narrate`（纯叙述），**留痕 `reason`**。
- **离线可玩、进度不丢、不弹错误框**：任何 LLM 失败**不得**阻断本回合（状态已由本地确定）；提示走 `_is_demo_mode` 的中性语义（"这次她没听懂"类，**不弹窗、不报错**）。
- **`propose` 请求**：`max_tokens ≤ 80`、严格 JSON、**有超时阈值**；解析失败/越权/未知变换 → 视为失败 → 降级。
- **叙述流**失败 → 显示占位叙述（本地模板）+ 可重掷，**不阻塞** `transcript` 写入。

**理由**：research §4.2-5 明确"必须走同一条降级路径，避免只有网络慢时才炸"。

**被否决的替代方案**：❌ 失败弹错误框（破坏"陪伴"体验）；❌ 失败即丢回合（进度丢失）。

### D-V22-13 动效铁律：只用 `gui/motion.py` 既有能力 + 只说书人两类原生母题

**决策**

- **只用** `motion.animate()/fade()/loop()/stop_loop()`；**禁止**散落 `QPropertyAnimation(...).start()` 与硬编码时长。
- **只允许项目原生两类母题**：① **文字节奏**（省略号循环 / 逐字流式；先例 `gui/widgets/kb_dialog.py`）；② **既有元素的呼吸/淡入**（`motion.fade()`，≤220ms）。
- **明确不做第三类"几何母题运动"**：跳动三点、电平柱条、同心涟漪、旋转环、骨架屏微光、打字机光标、翻页、烛光、粒子、错峰入场、进度条 —— **一律判"不做"**。**宁可不做，也不要有外来感。**
- `off` 档：**不创建任何动画对象**（`motion.enabled()==False` → 落点走静态形态）。

**理由**：项目审美纪律（用户最高优先）；research §5.5 与 v2.1 动效内核纪律。

**被否决的替代方案**：❌ 引入第三方动画库（R-F）；❌ 跳动三点/柱条/涟漪（外来感）。

### D-V22-14 接线：纯增 1 项导航 + AppContext 末位字段 + 页注册（单写者）

**决策**

- `sidebar.NAV_ITEMS` **纯增 1 项**（4 元组，既有 10 项 key/label/信号零变更）。
- `gui/app_context.py` `@dataclass` **末尾纯增** `tavern: Any = None`。
- `gui/main_window.py` `page_classes` **追加 1 项** `("tavern", PageTavern, "酒馆")` + 顶部 import。
- `gui/widgets/chat_panel_parts/extras.py` 工具行 **+1 入口**（约 12 行）。
- **单写者**：`sidebar.py` 与 `extras.py` 各只 1 人编辑；`main_window.py` 单写者。

**理由**：全部为"纯增"，`item_clicked(str)` 信号语义不变，`AppContext` 既有构造兼容。

**被否决的替代方案**：❌ 改导航结构为 5 元组（无必要，回归风险）；❌ 改 `PageManager` 语义（零必要）。

### D-V22-15 内容包随包 + 双 spec 同步（含路径校正）

**决策**

- 内容包 = **数据（JSON），不是代码**：`gui/tavern/content/lantern/{book.json, chapters.json, transforms.json}` + `content/README.md`（世界书撰写规范）。
- **打包**（双 spec 同步）：
  - `datas + ('gui/tavern/content', 'tavern/content')`（**target = 源码相对路径**，见 §1.4 校正②）；
  - `hiddenimports + 'gui.tavern'`（惰性 import 的子模块）。
- **loader**：`content_dir() = get_resource_path("tavern/content")`（源码态 → `gui/tavern/content`；frozen 态 → `_MEIPASS/tavern/content`）。
- **不新增任何第三方依赖**；`requirements*.txt` diff 必须为空。

**理由**：路径纪律（design-v21 ⚠-2 类事故的预防）；双 spec 同步（防 onefile 资源缺口，v2.0 ⚠-10 教训）。

**被否决的替代方案**：❌ target=`tavern_content`（源码态读不到，见校正②）；❌ 只改 onedir spec（onefile 缺口）。

---

## 3. 文件清单

### 3.1 新增

| 文件 | 职责 | 依赖 | 红线 |
|---|---|---|---|
| `gui/tavern/__init__.py` | 包入口：常量（`SCHEMA_VERSION` / 白名单 / 段名）+ 懒查函数；**零 Qt** | 标准库 | R-F；D-V22-06 |
| `gui/tavern/model.py` | 数据结构 + schema_version + 默认结构 + 读时迁移（`merge_defaults`） | 标准库 | 数据不乱 |
| `gui/tavern/store.py` | 存档 IO：单写点 `save()` / `load()` / 原子写 / 快照轮转 / 坏档恢复 | root `utils._atomic_write_json` | 原子写（D-V22-07） |
| `gui/tavern/engine.py` | 状态机：`apply_transform()` + 三条不变量 + 硬禁区 + 显式 seed | 标准库 | 数据不乱 |
| `gui/tavern/intent_router.py` | 三级路由：`route()`（词表 + 规则 + 可选 LLM 提议 + 降级 + 留痕） | 标准库（LLM 以**注入 client** 解耦） | Q1；降级铁律 |
| `gui/tavern/worldbook.py` | 关键词触发 + selective logic + 字符预算裁剪 + 递归上限 + 脏数据容错；**内容包唯一解析入口 `content_dir()` / `load_content()`**（§4.2） | 标准库 | R-F（无向量） |
| `gui/tavern/prompt.py` | 五段式 `build_story_prompt()` + reroll 差异 | 标准库 | — |
| `gui/tavern/summarize.py` | 摘要触发 + 落盘前校验 | 标准库 | — |
| `gui/tavern/service.py` | **Qt controller**（`TavernService`）：持 store + 发 LLM 请求（`api.chat` / `chat_stream_chunks`）+ 向 UI 发信号 | `gui.qt_compat` + `api` | **唯一** Qt 文件（D-V22-06） |
| `gui/tavern/errors.py` | `TavernError`（中文消息，直接可呈现，对齐 `CardError`） | 标准库 | — |
| `gui/tavern/content/lantern/book.json` | 「灯笼酒馆」基础世界书（`constant ≤ 5`） | — | R-A（零禁项词） |
| `gui/tavern/content/lantern/chapters.json` | 章节 + storylet 节点（`{id,title,text,llm_brief,prerequisites,effects,choices[]}`） | — | 章标题无序号 |
| `gui/tavern/content/lantern/transforms.json` | 该包额外声明的受控动作（仍过白名单校验） | — | — |
| `gui/tavern/content/README.md` | 世界书撰写规范（一条目一主题 / 3–5 要点 / `constant ≤5` 等） | — | — |
| `gui/pages/page_tavern.py` | 独立页：5 Tab 容器 + `on_enter()` 刷新 | `gui.qt_compat` | Q3 |
| `gui/widgets/tavern/tavern_narrative.py` | 叙述流（流式渲染 + 重掷/编辑文本） | motion / icons | D-V22-13 |
| `gui/widgets/tavern/tavern_input.py` | 输入行 + 快捷动作按钮排（4–6 槽） | icons | 无裸 emoji |
| `gui/widgets/tavern/tavern_hud.py` | 顶部状态条（**章标题，无数值**） | — | Q4 / R-A |
| `gui/widgets/tavern/tavern_worldbook.py` | 世界书编辑器（条目表 + 预算读数） | — | — |
| `gui/widgets/tavern/tavern_plays.py` | 我的故事（列表 + 继续/回看） | — | 列表项无序号 |
| `gui/widgets/tavern/tavern_trace.py` | 记录（`applied` 留痕 + 摘要，只读） | — | **不呈现成功率/进度** |
| `tests/test_v22_model.py` | schema / 迁移 / 类型守卫 / 坏档恢复 | — | 纯函数 |
| `tests/test_v22_store.py` | 原子写 / 崩溃不损坏 / 快照轮转 | — | 纯函数 |
| `tests/test_v22_engine.py` | 7 变换 pre/post + 三不变量 + 硬禁区 | — | 纯函数 |
| `tests/test_v22_router.py` | 三级路由 + 降级 + 留痕字段（LLM 用 mock） | — | 纯函数 |
| `tests/test_v22_worldbook.py` | 触发 / selective logic / 预算淘汰 / 递归上限 / 脏正则 | — | 纯函数 |
| `tests/test_v22_prompt.py` | 五段顺序 / reroll 不含上版文本 | — | 纯函数 |
| `tests/test_v22_no_ra.py` | R-A 扫描（数值/序号禁项词表） | — | R-A |

### 3.2 修改（**纯增**）

| 文件 | 改动 | 红线注意 |
|---|---|---|
| `gui/widgets/sidebar.py` | `NAV_ITEMS` **纯增 1 项** = `("tavern", "酒馆", "glass", "\U0001F377")`（复用已登记图标名 `glass`，第 4 元 emoji 回退 `🍷`） | 既有 10 项 key/label/信号零变更（R-D） |
| `gui/widgets/chat_panel_parts/extras.py` | 工具行 **+1** "快速开局"入口（约 12 行，复用 `_open_mini_games()` 范式） | 不动既有条目 |
| `gui/app_context.py` | `@dataclass` **末尾纯增** `tavern: Any = None` | 既有字段零改动 |
| `gui/main_window.py` | 顶部 import `PageTavern` + `_setup_pages()` 的 `page_classes` **追加 1 项** | `_setup_*` 序不变；更新链零触碰 |
| `maid_coder_gui.spec` | datas `+('gui/tavern/content','tavern/content')`；hiddenimports `+'gui.tavern'` | 既有 datas 不动 |
| `maid_coder_gui_onefile.spec` | **同步**同上 | 双 spec 一致 |
| `gui/assets/icons/icons_manifest.json` / `tools/build_icons.py` | **不触发** —— 图标名已定为既有登记名 `glass`（存在且未被占用），**本期零构建、不补名、不重建 ttf** | 构建期；无运行时依赖（原条件分支作废） |
| `docs/THIRD_PARTY.md` | "二、参考未采用"表登记 CCv3 + ST 文档（仅借鉴格式/规范，未复制代码） | R-H；**无 LICENSE 副本入库**（只引字段） |
| `README.md` / `CHANGELOG.md` | 酒馆用法/能力如实说明；版本条目 | R-R 诚实，无自评分 |

#### §3.2 附注 · `datas` 目标路径"两态都要能读到"的验证法（**批 5 必做，别踩第二次**）

**约定（唯一规则）**：`spec` 里内容包的 **target 必须等于"源码相对 `gui/` 的路径"**，即 `source_dir == gui/<target>`。既有 `('gui/assets/icons','assets/icons')` 即此规则的正例（`source = gui/assets/icons`，`target = assets/icons`）。酒馆据此取 `('gui/tavern/content','tavern/content')`，与 `content_dir() = get_resource_path("tavern/content")` 严格对齐。

**为什么两态会分叉**（`gui/utils.py:12-18` `get_resource_path`）：

| 运行态 | 基准（`base_path`） | `get_resource_path("tavern/content")` 解析为 | 内容包须落在 |
|---|---|---|---|
| **源码态** | `Path(gui/utils.py).parent` = `<repo>/gui` | `<repo>/gui/tavern/content` | 真实目录 `gui/tavern/content/**`（开发即在此） |
| **frozen 态**（onedir/onefile） | `sys._MEIPASS` = `<dist>/maling/_internal` | `<dist>/maling/_internal/tavern/content` | spec `datas` 把 `gui/tavern/content` 拷到 `_internal/tavern/content` |

**验证法（一条断言覆盖两态，批 5 编码进 `tests/` + 打包冒烟）**：

1. **源码态断言**：`assert get_resource_path("tavern/content/lantern/book.json").exists()`（源码环境直接跑）。
2. **frozen 态断言**：monkeypatch `sys.frozen=True` + `sys._MEIPASS=<dist>/maling/_internal`（或真机 exe 内跑），同一断言必须为真；同时对 `chapters.json` / `transforms.json` 各断一次。
3. **反向守卫**：断言 `not get_resource_path("tavern_content").exists()`——防止有人退回 `target=tavern_content` 的错误写法（该写法源码态会静默读空）。
4. **打包冒烟**：onedir **与** onefile 两包内 `.../tavern/content/lantern/book.json` 均存在，且 exe 内**真开一局**取证（对应 R5）。

> 结论口径：**审 spec 时只问一句——`datas` 的 target 是否等于源码相对 `gui/` 的路径？** 是则两态自动成立；否（如 `tavern_content`）则源码态必空。此条同样适用于任何**后续新增的内容包目录**。

### 3.3 不动（**保护区**，逐个点名；对齐 design-v21 §3.3 + team lead 口径）

| 分类 | 文件 | 理由 |
|---|---|---|
| **v2.0 更新链（硬保护）** | `maling_updater.py` / `updater.spec` / `version.json` / `gui/update_checker.py` / `gui/update_downloader.py` / `gui/widgets/update_progress.py` / `tools/build_release.py` | R-D |
| **`main.py` 更新编排段（段级保护）** | `_compute_install_targets` … `_maybe_launch_updater` / `_quit_stop_services`（含末步）+ `main()` 内更新编排调用 | 本轮**不碰 `main.py`**（酒馆无需启动期接线） |
| **v1.9/v2.1 成果** | `gui/fonts.py` + `gui/assets/fonts/**` / `THEME_DEFINITIONS` 四风格色值 / `LEGACY_THEME_MAP` / `apply_night_lock` / `is_dark_effective` | R-D |
| **业务与陪伴** | `gui/chat_service.py` / `session.py` / `memory.py` / `companion.py` / `persona.py` / `gui/role_card.py`（逻辑）/ `pi_backend.py` | Non-goal；Q2 只读 |
| **配置** | `gui/config.py`（**零改动**，D-V22-08） | 绕开 `save()` 陷阱 |
| **动效/图标内核** | `gui/motion.py` / `gui/icons.py`（**只用不改**） | D-V22-13 |
| **美术资产** | `gui/assets/maid/**` / `maid_pet/**` / `roles/**` / `maling.ico` | Non-goal |
| **依赖清单（硬保护）** | `requirements.txt` / `requirements_gui.txt` / `pyproject.toml` dependencies | R-F：**diff 必须为空** |
| **版本源** | `version.json` / `core/__init__.py`（`__version__`） | — |

### 3.4 文件域切分（供多工程师并行）

| 域 | 独占文件 | 依赖 | 可并行 |
|---|---|---|---|
| **域0 契约冻结** | `gui/tavern/model.py`、`errors.py`、`__init__.py`、本文 §4 | — | **先行串行** |
| **域1 数据层** | `store.py`、`tests/test_v22_model.py`、`test_v22_store.py` | 域0 | 与域2/3/4 并行 |
| **域2 引擎** | `engine.py`、`tests/test_v22_engine.py` | 域0 | 与域1/3/4 并行 |
| **域3 路由** | `intent_router.py`、`tests/test_v22_router.py` | 域0/2 | 与域1/4/5 并行 |
| **域4 世界书** | `worldbook.py`、`content/**`、`tests/test_v22_worldbook.py` | 域0 | 与域1/2/3/5 并行 |
| **域5 prompt/摘要** | `prompt.py`、`summarize.py`、`tests/test_v22_prompt.py` | 域0/4 | 与域1/2/3 并行 |
| **域6 UI** | `page_tavern.py`、`gui/widgets/tavern/**`、`service.py` | 域1–5 | 依赖批1 完成后 |
| **域7 接线** | `sidebar.py`、`extras.py`、`app_context.py`、`main_window.py` | 域6 | **`sidebar.py` 与 `extras.py` 各 1 人** |
| **域8 收口** | 两 `*.spec`、`docs/THIRD_PARTY.md`、`README.md`、`CHANGELOG.md`、真机留档 | 全部 | **串行收尾** |

**必须串行**：域0 → {域1,2,3,4,5 并行} → 域6 → 域7 → 域8。

---

## 4. 数据结构 / 接口（全文最重要之一）

### 4.1 `tavern.json` schema v1（完整 JSON）

落盘：**`~/.maid_coder/tavern/tavern.json`**（单文件，顶层 `schema_version`，原子写）。

```json
{
  "schema_version": 1,
  "meta": { "created_at": "2026-09-15T20:00:00+08:00", "updated_at": "2026-09-15T21:07:33+08:00" },

  "settings": {
    "worldbook_budget_chars": 1600,
    "worldbook_scan_depth": 4,
    "max_lore_entries_per_turn": 3,
    "recursive_max_depth": 2,
    "transcript_keep_turns": 14,
    "auto_summary_every": 8,
    "allow_free_input": true,
    "allow_propose": true,
    "llm_narration": true,
    "narrator_length": "short"
  },

  "library": {
    "books": [
      {
        "book_id": "lantern",
        "title": "灯笼酒馆",
        "builtin": true,
        "entries": [
          {
            "uid": 1,
            "title": "酒馆的位置（基础规则）",
            "keys": ["酒馆", "这里"],
            "secondary_keys": [],
            "selective_logic": "AND_ANY",
            "content": "灯笼酒馆只有一扇门，开在巷子尽头。屋里只有吧台、四张桌子和一盏总也不灭的灯笼。",
            "position": "system_head",
            "depth": 0,
            "order": 10,
            "weight": 100,
            "constant": true,
            "probability": 100,
            "sticky": 0,
            "cooldown": 0,
            "recursive": false,
            "case_sensitive": false,
            "enabled": true,
            "budget_chars_est": 58
          },
          {
            "uid": 12,
            "title": "吧台后的旧照片",
            "keys": ["照片", "旧照片"],
            "secondary_keys": ["吧台"],
            "selective_logic": "AND_ANY",
            "content": "吧台后面的墙上钉着一张褪了色的照片，边角卷起。照片里有两个人的影子和半截灯笼。",
            "position": "system_tail",
            "depth": 0,
            "order": 100,
            "weight": 100,
            "constant": false,
            "probability": 100,
            "sticky": 2,
            "cooldown": 0,
            "recursive": false,
            "case_sensitive": false,
            "enabled": true,
            "budget_chars_est": 52
          }
        ]
      }
    ],
    "bound_book_ids": ["lantern"],
    "cast": [
      { "cast_id": "host", "role": "老板娘", "card_id": "<role_card_id>", "card_snapshot": {} }
    ]
  },

  "plays": [
    {
      "play_id": "p_20260915_a1b2",
      "book_id": "lantern",
      "title": "灯笼还亮着",
      "status": "active",
      "created_at": "2026-09-15T20:00:00+08:00",
      "updated_at": "2026-09-15T21:07:33+08:00",

      "chapter_id": "ch1",
      "node_id": "counter_photo",
      "scene_id": "counter",
      "turn": 7,
      "seed": 1731845,

      "vars": { "poured": "long_night", "knows_name": false, "held_items": [], "scene_items": ["old_photo"], "given": [], "opened": [], "known": [] },

      "seen_nodes": ["opening", "she_begins", "counter_photo"],
      "pending": [
        { "choice_id": "ask_photo", "label": "问她照片里的人是谁", "transform": "ask_about", "args": { "topic": "photo" } },
        { "choice_id": "drink_first", "label": "先喝一口，听她讲", "transform": "order", "args": { "item": "long_night" } },
        { "choice_id": "stay_silent", "label": "什么都不问，静静等她开口", "transform": "wait", "args": {} }
      ],

      "transcript": [
        {
          "turn": 7,
          "role": "player",
          "input_kind": "free",
          "text": "我先把那张照片拿起来看看",
          "resolution": { "mode": "propose", "transform": "take", "ok": false, "reason": "item_not_in_scene", "llm_used": true },
          "narrated": true,
          "at": "2026-09-15T21:07:33+08:00"
        }
      ],

      "summary": { "up_to_turn": 6, "text": "【前情提要】你推门进来时，她正在擦一只杯子……", "generated_by": "llm", "verified": true },

      "llm": { "last_model": "", "last_error": "", "degraded": false, "last_propose_at": "" }
    }
  ],

  "active_play_id": "p_20260915_a1b2",

  "journal": {
    "seen_endings": [],
    "unlocked_entries": [12],
    "first_seen": { "lantern": "2026-09-15T20:00:00+08:00" }
  }
}
```

**字段表（顶层）**

| 键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `schema_version` | int | `1` | 顶层版本字段（迁移依据） |
| `meta` | object | `{created_at, updated_at}` | 时间戳（ISO 8601 本地时区） |
| `settings` | object | 见 §4.1 | 酒馆设置（**不改 `GuiConfig`**） |
| `library` | object | `{books:[], bound_book_ids:[], cast:[]}` | 世界书 / 绑定书 / 人物 |
| `plays` | array | `[]` | **单局**存档（可多局） |
| `active_play_id` | str | `""` | 当前局 |
| `journal` | object | `{seen_endings:[], unlocked_entries:[], first_seen:{}}` | **跨局累积**（与 `plays[]` **物理分离**） |

**字段表（`plays[i]` 关键项）**

| 键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `chapter_id` / `node_id` / `scene_id` | str | `"ch1"/"opening"/""` | **仅数据层**，不上屏（Q4） |
| `turn` | int | `0` | 拍数（仅内部） |
| `seed` | int | 随机 | **显式 seed**（`random.Random(seed+turn)`） |
| `vars` | object | 见上 | **唯一可写状态**；键名受内容包白名单约束 |
| `seen_nodes` | array[str] | `[]` | 不变量 I2 用 |
| `pending` | array[object] | `[]` | **当前可选项快照**（是数据，不是现算） |
| `transcript` | array[object] | `[]` | **append-only**；每条自带 `resolution` |
| `summary` | object | `{up_to_turn:0, text:"", generated_by:"", verified:false}` | **结构化字段**，非临时拼接 |
| `llm` | object | 见上 | 降级状态（`degraded`/`last_error`） |

**结构要点（逐条对上"数据不乱"）**：① `vars` 是唯一可写状态、键名受白名单约束；② `pending` 是"选项快照"（内容包更新，老存档选项不"凭空变形"）；③ `transcript` append-only（每条自带 `resolution`）；④ `summary` 是结构化字段；⑤ `journal` 跨局累积**与单局物理分离**；⑥ `seed` 显式保存。

### 4.2 ★ 三级路由的精确定义 + 白名单枚举 + 本地校验器 + 不变量

**路由精确定义（自由输入路径）**：

```
自由输入 text
   │
   ▼
resolve_verbatim(text, content) → 命中受控意图 id？   ← 纯本地：词表 + 句式正则（逐条 try/compile）
   │ 命中                                  │ 未命中
   ▼                                       ▼
① verbatim                             allow_propose 且 LLM 可用？
   校验 pre 满足？                          │ 是                 │ 否 / 超时 / 关闭
   │ 是      │ 否                           ▼                    ▼
   ▼         └──────────────┐       ② propose：LLM 从【白名单枚举】里
apply → ok                   │         提议一个 {transform, args}
                             │              │
                             │              ▼
                             │       validate(state, transform, args) → 本地校验器
                             │         不撞硬禁区？→ args 合法？→ pre 满足？→（施加后）不变量保持？
                             │              │ 通过          │ 不通过
                             │              ▼               ▼
                             │       apply → ok        ③ narrate（状态不变，记 reason）
                             ▼              │               │
                    ┌────────────────────────┴───────────────┘
                    ▼
        本回合"发生了什么"已确定（= 数据）
                    ▼
        LLM 只负责把"发生了什么"写成叙述（= 文采）
                    ▼
                可 reroll（只重跑这一步，绝不重跑变换）
```

**两条"直接施加"入口（同为 verbatim 语义，都零 token）**：
- `input_kind="free"` → `resolve_verbatim()` 词表命中；
- `input_kind="choice"` → 命中 `pending[].choice_id` 的**选项快照**（直接取该 `transform` + `args`）。

**白名单枚举（P0 = 7 条，全部可离线执行、可单测）**

| 变换 id | 语义 | 前置 `pre` | 后置 `post` | 触碰状态 |
|---|---|---|---|---|
| `move_to` | 移动到当前可达地点 | `target ∈ reachable(scene)` | `scene_id = target` | `scene_id` |
| `take` | 拿走场景中的物品 | `item ∈ scene_items` | `held_items += item` | `held_items`/`scene_items` |
| `give` | 把持有物品交给对方 | `item ∈ held_items` | `held_items -= item`；`given += item` | `held_items`/`given` |
| `open` | 打开/解锁（条件已具备） | `precondition(scene, key)` 成立 | `opened += target` | `opened` |
| `ask_about` | 问某个已知话题 | `topic ∈ known_topics(scene)` | `known += topic` | `known` |
| `wait` | 让一拍过去（"再写一段"） | — | `turn += 1` | `turn` |
| `order` | 点一杯 / 要一样东西（酒馆特色） | `menu(scene)` 非空 | `poured += item` | `poured` |

**`vars` 白名单**：内容包 `transforms.json` 以 `var_names` **声明合法 var 名**（engine 实测**只校验「名」，本期不消费类型/值域声明** —— 类型/值域列为**后续可选增强，本期不做**，避免两套形状）；`vars` 键名在此集合之外，**一律拒绝写入**（防 LLM 提议带来的"变量爆炸"）。建议 `vars` **≤ 8 个命名值**（对齐 QBN"少量命名数值"）。

**★ 受控变换 `args` 形状（**V22-02 冻结**，单一来源 = `engine.ARG_KEYS`）**

| 变换 | 必填 | 可选 | 前置/校验（`_validate_args` / `_check_pre` 实测） |
|---|---|---|---|
| `move_to` | — | `target`(str) | 缺 `target` → 在 `reachable(scene)` 内**确定性随机**选（`seed+turn`）；`target ∉ reachable` → `target_not_reachable`；无可达 → `no_reachable_target`；`target` 非 str → `arg_type_invalid:target` |
| `take` | `item`(str) | — | `item ∉ scene_items` → `item_not_in_scene`；缺 → `missing_item` |
| `give` | `item`(str) | — | `item ∉ held_items` → `item_not_held`；缺 → `missing_item` |
| `open` | `key` **或** `target`(str，二者其一) | 同左 | 缺两者 → `missing_key`；`precondition(scene,key)` 不成立 → `condition_not_met` |
| `ask_about` | `topic`(str) | — | `topic ∉ known_topics(scene)` → `topic_not_known`；缺 → `missing_topic` |
| `wait` | — | — | 无前置；`turn += 1` |
| `order` | — | `item`(str) | `menu(scene)` 空 → `menu_empty`；`item ∉ menu` → `item_not_on_menu`；缺 `item` → 确定性随机点一杯 |
| **全部** | — | **`effects`**(list) | 受控额外写入通道（见下） |

- **结构键之外的任何键一律 `bad_args:unexpected_args:<key>`**（fail-closed）；缺失必填 → `bad_args:missing_*`。内容包作者 / LLM 提议**只允许**用上表列出的键。

**★ 受控写入通道 `effects`（冻结）—— 6 硬禁区 / 3 不变量的唯一可测触发路径**

```
effects := [ { "field": str, "op": "append"|"set"|"remove"|"edit"(缺省="set"), "value": any }, ... ]
```

- **`field` 白名单** = `ALLOWED_EFFECT_FIELDS`（`("scene_id","node_id","turn","transcript")`）**∪ 白名单 var 名**（`DEFAULT_VAR_NAMES` ∪ 内容包 `var_names`）。三者之外 → `forbidden:unknown_var`。**这是"内容包作者可写、但必须过校验"的受控面** —— 内容包确实能驱动自定义状态，但**只能写**：三个推进字段（`scene_id`/`node_id`/`turn`）+ `transcript`（只增不改）+ 它自己声明的 var。**没有 effects 通道，硬禁区/不变量就没有可测触发路径** → 故冻结为**唯一写入通道**。
- **`op` 语义与边界**（`_apply_effect` 实测）：

| field | `append` | `set` | `remove` | `edit` |
|---|---|---|---|---|
| `transcript` | 追加一条 | `value` 为 list → **整体替换**（缩短 → I3 拦截回滚；延长 ≈ append）；标量 → append | 删**首个**匹配 | **禁止** → `forbidden:rewrite_history` |
| `scene_id` / `node_id` | — | 赋值（引用无效 → I2 拦截回滚） | — | — |
| `turn` | `turn += value` | `turn = value` | — | — |
| 其他（= var 名） | 追加到列表（非列表则先包成 `[cur]`） | 赋值 | 删首个匹配 | — |

- **触发面（可测性保证）**：`field:"meta"` → `touch_structure`；`field` ∈ `RA_NUMBER_FIELDS`（如 `"affection"`）→ `emit_ra_number`；`field` ∈ `KILL_REVIVE_FIELDS`（如 `"alive"`）→ `kill_revive_character`；`field:"chapter_id"` → `cross_chapter`；`field:"transcript",op:"edit"` → `rewrite_history`；`field` 越权 → `unknown_var`。不变量：写 `scene_items` 造 `held ∩ scene ≠ ∅` → I1；写悬空 `node_id`/`scene_id` → I2；缩短 `transcript` → I3。
- **`write_vars`（裁决：不采纳 → 不是 args 形状的一部分）**：engine 实测 `is_forbidden` 会扫描 `args["write_vars"]`，**但 `ARG_KEYS` 未列该键、`_apply_post` 也不施加它** → 任何 `write_vars` 入参都会被 `bad_args:unexpected_args:write_vars` **拒绝（fail-closed，安全）**；其功能被 `effects` **完全覆盖**（写 var 即 `{field:<var名>, op:..., value:...}`）。**故 args 形状中不存在 `write_vars`**（单一写入通道 = `effects`，杜绝两套形状）。**engine 无需为此调整**（当前拒绝行为即正确）；engine 若愿清理 `is_forbidden` 里对该键的死扫描，属可选卫生项，不阻断。**内容包 / router / 本文档一律不得使用 `write_vars`。**

**★ 内容包（`content`）↔ engine 读取键契约（**V22-02 冻结**，单一来源）**

内容包落点 `gui/tavern/content/<pack>/`（`book.json` 世界书 / `chapters.json` 节点线与选项 / `transforms.json` var 声明与自定义动作）；**解析后合并为一个 `content: dict`** 供 engine/router 读取（engine **不解析文件**，只消费 dict）。下表键**全部可缺省**：

| 键 | 结构 | 读它的地方 | 缺省语义（"安全"具体指） |
|---|---|---|---|
| `node_ids` | `[str,…]`（**全局**） | `model.check_i2` | 缺 → I2 **无法判定 → 放行** |
| `scene_ids` | `[str,…]`（**全局**） | `model.check_i2` | 缺 → I2 放行 |
| `nodes` / `scenes` | 同 node_ids/scene_ids（**别名**） | `check_i2`（`node_ids or nodes`） | 同左 |
| `reachable` | `{scene_id: [scene_id,…]}`（**按 scene 分组**） | `engine._check_pre`(move_to) | 缺 → `no_reachable_target`（**拒绝**） |
| `known_topics` | `{scene_id: [topic,…]}`（**按 scene 分组**） | `_check_pre`(ask_about) | 缺 → `topic_not_known`（拒绝） |
| `menu` | `{scene_id: [item,…]}`（**按 scene 分组**） | `_check_pre`(order) | 缺 → `menu_empty`（拒绝） |
| `open_conditions` | **扁平 dict**：`{"<scene>:<key>": bool}` 优先、回退 `{"<key>": bool}` | `_check_pre`(open) | 缺 → `condition_not_met`（拒绝） |
| `openable` | `[key,…]`（全局，可选） | `open_condition_met` | 缺 → 仅看 `open_conditions` |
| `var_names` | `[str,…]`（**全局**） | `engine.is_known_var` / `declared_var_names` | 缺 → 只认 `DEFAULT_VAR_NAMES`；写自定义 var → `forbidden:unknown_var` |

- **`var_names` 与 `DEFAULT_VAR_NAMES` 的关系 = 并集（内容包只能"追加声明"）**：`is_known_var(name) = name ∈ DEFAULT_VAR_NAMES` **或** `name ∈ declared(content["var_names"])`。内容包**不能删除/覆盖**基底 7 名（`poured`/`knows_name`/`held_items`/`scene_items`/`given`/`opened`/`known`），只能**在其上追加**；`vars` 命名值总数仍受 `MAX_VARS(=8)` 约束（超限 → `bad_args:max_vars_exceeded`）。
- **"缺省即安全"的两条精确含义**：① **pre 面 fail-closed** —— 缺 `reachable`/`known_topics`/`menu`/`open_conditions` → 对应动作**直接不可用**（`precondition_failed:*`），**绝不误放行**；② **I2 面 fail-open** —— 缺 `node_ids`/`scene_ids`（及别名）→ I2 **无法判定即放行**（`check_i2` 返回 `None`），**避免把合法状态误判为悬空**（这是唯一一处"缺省=放行"，其余皆为"缺省=拒绝"）。

**★ 内容包解析入口（单一 source，V22-04 补齐）**：`gui/tavern/worldbook.py::load_content(pack_id: str) -> dict`（域4，零 Qt，仅标准库）是**唯一**的「三文件 → `content` dict」入口（`content_dir()` 同处）。**`engine` / `intent_router` / `prompt` 一律接收解析好的 `content: dict`，各自禁止再写解析器**（杜绝两套形状 —— 正是本节要杜绝的）。

- **保留附加键（engine 不读，供 prompt / UI）**：`worldbook` / `chapters` / `quick_actions` 等以**独立顶层键**命名空间挂在 content 里；engine 只读上表冻结键、忽略其余。**解析器不得 emit `nodes` / `scenes` 别名**（避免与 `check_i2` 的 `node_ids or nodes` 语义撞车）—— `node_ids` / `scene_ids` 由解析器从 `chapters[].nodes[].id` 与（`reachable` / `known_topics` / `menu` 键 ∪ `open_conditions` 的 `<scene>:` 段）**推导**。
- **初始 scene = `""`（易踩）**：`model.new_play()` 置 `scene_id=""`，故内容包**必须声明 `reachable[""]` / `known_topics[""]` / `menu[""]`**（否则开局第一个动作即 fail-closed）。注：`check_i2` 对空 `scene_id` **不校验**（`and scene_id` 守卫），故 `""` **无需**进 `scene_ids`。
- **节点级元数据**（如 `prerequisites`）属 `chapters[].nodes[]` 的**节点字段**，**非** content 顶层键、engine 不读；若 router / UI 需消费，**必须另约定键名**，不得占用上表冻结键。消费方 = **服务层** `gui/tavern/service.py::_prerequisites_met`（`_advance_node` 节点准入 + `_sync_pending` 选项准入**共用同一把尺子**），语义见下。

**★ `prerequisites` 条件算子语义（契约扩展 · 2026-09-15 · 经用户批准）**

> **本批是经用户明确批准的、对 `prerequisites` 语义的契约扩展**（唯一一次授权）。原因：`opened` / `known` / `held_items` / `scene_items` / `given` 这 5 个基底变量**全是列表型**（由 `open` / `ask_about` / `take` / `give` 的 `post` 自动 append 维护），而原判定是**严格等值** —— 列表永不等于字符串，这 5 个变量**完全无法用于分支**。本扩展**只让"已被维护、但查询不到"的 5 个列表变量变得可查询**（可用分支键 3 → 8），**不新增 `MAX_VARS`、不改任何冻结常量、不动 engine**。

`prerequisites` 是一个 `{键: 期望值}` 映射；**每个键**都要满足，全部满足才放行。值有 **5 种形态**（单一来源 = `service.PREREQ_OPERATORS`）：

| # | 形态 | 语义 | 例 |
|---|---|---|---|
| ① | `{key: <标量>}`（**原样，向后兼容**） | 与 `state[key]` **严格等值**（`==`） | `{"scene_id": "counter"}` |
| ② | `{key: {"has": v}}` | `state[key]` 是 **list** 且含 `v` | `{"opened": {"has": "drawer"}}` |
| ③ | `{key: {"has_all": [v…]}}` | `state[key]` 是 list 且含 `[v…]` 的**全部**（取值必须是 list） | `{"known": {"has_all": ["photo", "name"]}}` |
| ④ | `{key: {"has_not": v}}` | `state[key]` 是 list 且**不含** `v`（做「你还没做过 X」） | `{"opened": {"has_not": "latch"}}` |
| ⑤ | `{key: {"not": v}}` | `state[key]` **不是 list** 且 `!= v`（标量不等于；列表请用 `has_not`） | `{"poured": {"not": "long_night"}}` |

- **判定状态面** = `play.vars` ∪ `{"scene_id"}`（`service._storylet_state`；**节点准入与选项准入共用**）。
- **fail-closed 规则**（全部"不通过"，**绝不抛异常** —— 本函数被 `_advance_node` / `_sync_pending` 调用，抛异常会炸整拍）：
  - 空 / 非 dict 的 `prerequisites` → **无条件通过**（作者没写条件即通用块）；
  - 键不在 `state` → **不通过**（保持现状）；键非 `str` → 不通过；
  - 值**不是** dict → 严格等值（保持现状）；
  - 值是 dict：**一个 dict 只认一个算子**（>1 个 → 不通过）；**未知算子名** → 不通过；空算子 dict → 不通过；
  - `has` / `has_all` / `has_not` 用于**非列表** `state[key]` → 不通过；`has_all` 取值**不是 list** → 不通过；`has_all` 取值是**空 list** → 不通过（空表恒真 = vacuous truth，与「写错一律不通过」同口径）；
  - `not` 用于**列表** `state[key]` → 不通过（列表请用 `has_not`）。
- **向后兼容**：引入算子时内容包为 16 节点 + 45 选项，全部走 ① 形态，语义**逐字节不变**（`test_v22_play_e2e.py` 全绿）。
- **不支持**：值域为 `dict` 的 var **无法用等值分支** —— 值形态 `dict` 已被算子形态占用（写 `{"var": {"some_key": v}}` 会被当作算子判定，未知算子名一律不通过）。这类 var 只能走算子形态或不用。
- **空表 fail-closed**：`{"key": {"has_all": []}}` **判不通过** —— 空表在集合语义下恒真（vacuous truth），与「写错一律不通过」同口径，故显式拒绝。

**★ 内容包的「不卡死」不变量（批次 D 校正口径，声明 = 实现 = 测试）**

> **本批订正一处"声明 ≠ 实现 ≠ 测试"的口径漂移。** 旧声明写成「**每个非终局节点都有一条 `move_to backdoor` 出口**」，但它**字面不成立**：`opening` 节点**没有** `move_to backdoor` 直连出口（只有 `sit_down → counter`），`reachable[""]` 也**不含** `backdoor`。旧测试还只遍历 `content["scene_ids"]` —— 而 `""` **不在 `scene_ids` 里**（§4.2：空 `scene_id` 不参与 I2 校验），于是**初始场景被悄悄豁免**。功能上无碍（两步必达），但三者口径不一致。**旧声明作废，以本节为准。**

- **准确声明**：**从任一可达状态出发，都能在有限步内抵达某个结局**（不是"每个节点都有一条 backdoor 出口"）。
- **实现口径（逐步可核）**：① 初始 `scene_id == ""`（`model.new_play`）；② `""` 经 `opening` 的 `sit_down`（`move_to → counter`）一步进入已声明地点集；③ 每个已声明地点在 `reachable` 上都（经传递闭包）可达 `backdoor`；④ 每个非终局节点至少有一条 `move_to` 出口（内容耗尽时 `_advance_node` 保持当前节点，出口即兜底）；⑤ 两个终局节点前置同为 `scene_id == backdoor`，由 `opened` 的 `{"has":"letter"}` / `{"has_not":"letter"}` **互斥且穷尽** ⇒ 任何 `opened` 状态下**恰有一个**匹配。
- **测试口径（两条，缺一不可）**：
  - `tests/test_v22_content_quality.py::test_scene_graph_closes_on_backdoor_from_every_scene_including_start` —— **场景图传递闭包**检查，遍历 `reachable` 的**每一个键（含 `""`）**，`""` 不再被豁免；
  - `tests/test_v22_play_e2e.py::test_no_dead_end_from_any_reachable_state_including_empty_scene` —— 真 service + 真内容包驱动的**完整状态空间 BFS** + **反向可达**，断言「不能抵达任何结局的可达状态数 == 0」，且显式断言初始空场景状态在枚举内、并明确其能抵达结局。
- **为什么不做「给 `opening` 补一条 `move_to backdoor`、并把 `backdoor` 加进 `reachable[""]`」**：两个终局的前置只有 `scene_id == backdoor` + `opened` 条件；初始 `opened == []` ⇒ `ending_dawn`（`has_not letter`）**第一拍即匹配**，玩家开局一步就能收束整局故事 —— 体验上不可接受（短路整个故事）。故本批选择「把声明改准确 + 把测试加强到能真正证明不变量」，**不动内容包**。

**硬禁区（任何档位都不得触碰，校验器最高优先级）**

1. 改写已发生的事实（`transcript` append-only，不可改历史）；
2. 跨越章节边界（`chapter_id` 只能由章节结束条件推进，不能由输入决定）；
3. 杀死/复活关键角色、改变已确立的人物身份；
4. 触碰 `meta` / `schema_version` / `settings`（结构字段不参与玩法）；
5. 产出任何 R-A 禁项数值（好感/心情/经验/货币/筹码/胜率/连胜/进度条/断签/倒计时）——**包括"隐藏不展示"也不做**；
6. 写入未在白名单声明的 `var` 名。

**本地校验器（`engine.validate(state, transform, args, content=None) -> ApplyResult`）** —— 依次检查（**V22-02 冻结序：硬禁区提到最前，仅次于白名单**）：

```
1) transform ∈ TRANSFORM_WHITELIST                                   （否则 reject "unknown_transform"）
2) 硬禁区判定（6 条 is_forbidden）★最高优先级                          （命中 → reject "forbidden:<id>"）
3) args 结构合法（键名 ∈ ARG_KEYS[transform]，全部可带 effects）        （否则 reject "bad_args:<detail>"）
4) pre 满足                                                          （否则 reject "precondition_failed:<detail>"）
→ 通过：ApplyResult(ok=True, state=入参原样回传, reason="ok")
── 以下在 apply_transform 内、对候选态施加之后执行 ──
5) 施加后 I1/I2/I3 均保持（check_invariants；违反 → 回滚 "invariant_violated:<In>"）
→ 全通过：返回新 state（不可变式，绝不改入参）
```

> ⚠️ **与初稿编号的差异（本文冻结 engine 实测序）**：初稿把「硬禁区」写在第 4 位（args / pre 之后）。engine 实测为 **白名单 → 硬禁区 → args → pre**，理由是「硬禁区最高优先级」（§5.4#10）：**即便 args 结构畸形，只要意图命中硬禁区也先按 `forbidden:<id>` 拒绝**。**以此冻结序为准，初稿编号作废。** 施加后的 I1/I2/I3 仍在 `apply_transform` 内做（需先施加到候选态）。

**三条不变量（每次施加变换前后各校验一次，违反即拒绝该变换并记 `reason`）**

| 不变量 | 断言 | 防的是什么 |
|---|---|---|
| `I1 集合互斥` | `held_items ∩ scene_items = ∅` | "东西既在身上又在桌上"这类经典矛盾 |
| `I2 引用有效` | `node_id ∈ 内容包节点集` 且 `scene_id ∈ 本书地点集` | 悬空引用导致的读档崩溃 |
| `I3 只增不改` | `transcript` 长度单调不减；`applied` 记录不可重写 | 历史被覆写（最不可逆的数据损坏） |

**留痕的数据形状（`transcript` 每拍一条）**

```json
{
  "turn": 7,
  "role": "player",
  "input_kind": "free",
  "text": "我先把那张照片拿起来看看",
  "resolution": { "mode": "propose", "transform": "take", "ok": false, "reason": "item_not_in_scene", "llm_used": true },
  "narrated": true,
  "at": "2026-09-15T21:07:33+08:00"
}
```

> `resolution.mode ∈ {"verbatim","propose","narrate"}`；`reason` 是**可读的自然语言短码**（`item_not_in_scene` / `precondition_failed:*` / `forbidden:*` / `invariant_violated:*` / `llm_timeout` / `llm_bad_json`），**供「记录」Tab 归因与日后调词表**。

### 4.3 模块接口签名（冻结）

```python
# gui/tavern/__init__.py  —— 零 Qt
SCHEMA_VERSION = 1
TRANSFORM_WHITELIST = ("move_to","take","give","open","ask_about","wait","order")
ROUTE_MODES = ("verbatim","propose","narrate")
PROMPT_SEGMENTS = ("narrator_rules","world_rules","character_card","turn_context","history")
SETTING_DEFAULTS = { ... }   # 4.1 settings 默认值

# gui/tavern/model.py  —— 零 Qt
def default_tavern() -> dict: ...
def merge_defaults(data: dict) -> dict: ...          # setdefault + isinstance 类型守卫；未知字段保留
def migrate(data: dict) -> dict: ...                 # 旧版本 → 当前 schema
def new_play(book_id: str, title: str, seed: int) -> dict: ...

# gui/tavern/store.py  —— 零 Qt
class TavernStore:
    def __init__(self, base_dir: Path | None = None): ...   # 默认 ~/.maid_coder/tavern
    @property
    def path(self) -> Path: ...
    def load(self) -> dict: ...       # 坏档 → 逐级恢复矩阵（§4.4），绝不抛
    def save(self, data: dict) -> None: ...   # mkdir → _atomic_write_json → 快照轮转
    def _rotate_backup(self) -> None: ...

# gui/tavern/engine.py  —— 零 Qt（V22-02 冻结：与 engine.py 实测签名逐字对齐）
@dataclass(frozen=True)
class ApplyResult: ok: bool; state: dict; reason: str; transform: str
ARG_KEYS: dict[str, tuple[str, ...]]                # 各变换 args 键白名单（每条均含 "effects"）
ALLOWED_EFFECT_FIELDS = ("scene_id", "node_id", "turn", "transcript")   # effects.field 白名单（∪ 白名单 var）
def validate(state, transform, args, content=None) -> ApplyResult: ...            # 校验序见 §4.2（硬禁区第 2）
def apply_transform(state, transform, args, content=None, *, seed=None, strict=False) -> ApplyResult: ...
def check_invariants(state, content=None, *, prev_state=None) -> list[str]: ...   # prev_state：I3 需施加前长度
def is_forbidden(state, transform, args, content=None) -> str | None: ...         # content：识别内容包声明的 var 名
# 只读辅助（供 router / UI 复用，同一契约）：
#   derive_rng / deterministic_choice / reachable_scenes / known_topics / menu_items /
#   open_condition_met / declared_var_names / is_known_var / build_resolution / is_known_reason

# gui/tavern/intent_router.py  —— 零 Qt（LLM 以注入 client 解耦）
# Resolution 的规范形状 = model.Resolution（TypedDict，键 = RESOLUTION_REQUIRED_KEYS，见 §4.2）；
#   router 返回该 dict，不再自定义 dataclass；engine.build_resolution() 产出同形（键集断言）。
def resolve_verbatim(text, content) -> tuple[str, dict] | None: ...
def route(text, state, content, *, allow_propose: bool, llm_propose=None,
          timeout_s: float = 6.0) -> tuple[dict, dict]: ...   # (resolution_dict, new_state)
# llm_propose(strict_json_prompt) -> dict|None 由 service 注入；None/超时/畸形 → narrate

# gui/tavern/worldbook.py  —— 零 Qt
# 内容包**唯一解析入口**（V22-04 补齐；见 §4.2「单一 source = load_content」）
def content_dir() -> Path: ...                              # get_resource_path("tavern/content")
def load_content(pack_id: str) -> dict: ...                 # 三文件→合并为 engine 契约 dict（§4.2），绝不抛
class WorldBook:
    def __init__(self, entries: list, *, budget_chars: int, scan_depth: int,
                 max_entries: int, recursive_max_depth: int): ...
    def match(self, recent_texts: list[str]) -> list[dict]: ...
    def select_within_budget(self, matched: list[dict]) -> list[dict]: ...  # weight→order→uid

# gui/tavern/prompt.py  —— 零 Qt
def build_story_prompt(state: dict, book: WorldBook, play: dict, content: dict,
                       *, relation_ctx: dict, mode: str = "normal") -> list[dict]: ...

# gui/tavern/summarize.py  —— 零 Qt
def should_summarize(play: dict, content: dict) -> bool: ...
def validate_summary(text: str) -> tuple[bool, str]: ...
def make_summary(play: dict, *, llm_summarize=None) -> dict: ...   # 校验不过→保留旧摘要

# gui/tavern/errors.py  —— 零 Qt
class TavernError(Exception): ...

# gui/tavern/service.py  —— Qt（唯一）
class TavernService(QObject):
    narration_chunk = Signal(str)   # 流式
    narration_done = Signal(str)
    play_changed = Signal(str)
    degraded = Signal(str)          # 中性提示，不弹窗
    def __init__(self, app_ctx): ...
    def start_play(self, book_id: str) -> None: ...
    def submit(self, text: str, input_kind: str = "free") -> None: ...
    def reroll(self, turn: int) -> None: ...
    def edit_narration(self, turn: int, text: str) -> None: ...
```

### 4.4 原子写 / 坏档恢复矩阵

**原子写（`TavernStore.save`）**：
```
1) d = Path(...)/"tavern"; d.mkdir(parents=True, exist_ok=True)     # 工具不建父目录
2) data["meta"]["updated_at"] = iso_now()
3) json.dumps(data, ensure_ascii=False)  # 预校验可序列化（失败则抛，不写坏）
4) if path.exists(): _rotate_backup()    # 保留最近 N 份 .bak.N
5) from utils import _atomic_write_json; _atomic_write_json(str(path), data)   # tmp + os.replace
```

**坏档恢复矩阵（`TavernStore.load`，逐级，**绝不抛**）**

| 级别 | 症状 | 恢复动作 | 结果 |
|---|---|---|---|
| L0 | 文件不存在 | `default_tavern()` | 新档（首次运行） |
| L1 | 字段缺失 | `merge_defaults()` 补默认 | 可用（字段级） |
| L2 | 字段类型错（如 `plays` 非 list） | 该字段回落默认（`isinstance` 守卫） | 可用（字段级） |
| L3 | `schema_version` 旧 | `migrate()` 升级 | 可用（升级后） |
| L4 | `schema_version` 高于当前 | 只读加载（**不写回**）+ 中性提示 | 可用（只读） |
| L5 | JSON 截断/解析失败 | 尝试 `tavern.json.bak.1`（最新快照） | 可用（回滚） |
| L6 | 截断 + 备份也坏 | 空档 + **中性提示**（不弹错误框），损坏文件改名保留 | 可用（空档） |

> 与既有业务数据的隔离：酒馆使用**独立子目录/独立文件**，`load()` 只读 `~/.maid_coder/tavern/**`，**绝不**触碰 `memory.json` / `companion.json` / `intimacy.json` / `sessions/**`。

### 4.5 与既有业务数据的隔离机制（逐条）

| # | 隔离手段 | 落点 |
|---|---|---|
| 1 | **独立文件/目录**：`~/.maid_coder/tavern/tavern.json` | `store.py` |
| 2 | **零写依赖**：`gui/tavern/**` **不 import** `intimacy`/`companion`/`memory`/`session` 的**写**接口 | 静态扫描可断言 |
| 3 | **关系只读**：`relation_ctx` 由 UI 层读取后**作为参数传入**，纯逻辑层不 import 业务模块（D-V22-04） | `service.py` 读，`prompt.py` 收 |
| 4 | **跨局/单局物理分离**：`journal`（跨局累积）vs `plays[]`（单局） | `model.py` |
| 5 | **不污染聊天**：不挂 `ChatService`；不写 `session.history` | D-V22-10 |
| 6 | **测试隔离**：单测用 `tmp_path` 作 `base_dir`，绝不写真实 `~/.maid_coder` | `tests/` |

### 4.6 页面/控件接口

```python
class PageTavern(QWidget):
    def __init__(self, app_ctx, title: str = "酒馆"): ...
    def on_enter(self) -> None: ...      # PageManager 生命周期钩子：刷新「我的故事」/关系语气
```
Tab 容器：`QTabWidget`（5 Tab）；每 Tab 一个 `gui/widgets/tavern/*` 控件；控件**只经 `TavernService` 的信号**更新，**不直接读写 store**。

---

## 5. 高自由度机制设计（核心质量目标）

### 5.1 「自由度」的技术定义：四件套协同（乘法关系）

| 环节 | 落点 |
|---|---|
| ① **状态机**（唯一真相源） | `engine.py`：`vars` + `node_id`；任何"世界真的变了"都必须落这里 |
| ② **可自由输入的对话层** | `intent_router.py`：输入 → 三级路由 |
| ③ **记忆/世界书检索** | `worldbook.py` + `summary`（关键词触发，无向量） |
| ④ **一致性约束** | 白名单 + 前置条件 + 不变量 + 硬禁区 + 留痕 |

缺 ① = 变成"会遗忘的黑盒"；缺 ② = 普通 AVG（用户明确拒绝）；缺 ③ = 改完就失忆；缺 ④ = 世界可被随手改坏。**四者是乘法关系，缺一自由度就塌**（research §4.1）。

### 5.2 状态与文本分离 → reroll 天然安全（本方案最大红利）

- 本回合**变换已施加、状态已确定**，LLM 只产出**叙述文本**；
- `reroll` **只重跑叙述生成，绝不重跑变换执行**；候选**只写 `transcript` 该拍**，**不改 `vars`/`node_id`/`chapter_id`**；
- 编辑同理：**只允许编辑叙述文本，禁止编辑状态字段**（UI 根本不呈现可编辑状态）；
- **因此不可能出现"重掷一次世界就变一次"这种最危险的脏数据**（research §2.6）。

### 5.3 忠实沿用 research 已定的四条铁则

1. **本地状态机是唯一真相源**（LLM 不写状态）；
2. **LLM 只产结构化输出**（`propose` = 一个变换候选；叙述 = 文本）；
3. **`transcript` append-only 可归因**（每条自带 `resolution`）；
4. **`journal` 与 `plays[]` 物理分离** + **显式 seed**。

### 5.4 「数据不乱」的 14 条机制（落点表）

| # | 机制 | 落点 |
|---|---|---|
| 1 | 顶层 `schema_version` + `meta` | `model.py` |
| 2 | 原子写（tmp + `os.replace`） | `store.py` → root `utils._atomic_write_json` |
| 3 | 单写点 | `store.save()` |
| 4 | 读时迁移（默认为底 + `setdefault` + `isinstance`） | `model.merge_defaults` |
| 5 | 未知字段不销毁 | `model.py` |
| 6 | 写前快照轮转 | `store._rotate_backup` |
| 7 | 单局 vs 跨局物理分离 | `model.py`（`plays[]` vs `journal`） |
| 8 | `vars` 键名受内容包白名单约束 | `engine.py` + `content/*/transforms.json` |
| 9 | 三条不变量 I1/I2/I3 | `engine.py` |
| 10 | 硬禁区最高优先级拦截（含 R-A） | `engine.py` |
| 11 | `transcript` append-only，`applied` 不可重写 | `engine.py` |
| 12 | 显式 seed（不依赖全局 `random`） | `engine.py` |
| 13 | 降级不抛错（LLM 失败 → 纯叙述 + 留痕） | `intent_router.py` |
| 14 | 内容包加载校验（脏正则丢弃 / 违规条目禁用 / `constant` 超额裁剪） | `worldbook.py` |

### 5.5 关系只读的落地（Q2）

- **读**：`service.py` 在每回合渲染前调用 `companion.relation_stage_name()` / `app_ctx.intimacy.level_name()` / `brand_persona_self()`；拼 `relation_ctx`。
- **用**：`prompt.py` 的第五段"角色卡/语气"中，把 `relation_ctx` 作为**称呼与语气提示**（如"她认得你，称呼你作主人"）；**不产出任何数值**。
- **不写**：`gui/tavern/**` 无 `intimacy`/`companion` 写调用；`tavern.json` 不存关系数值。
- **可断言**：AST 扫描 `gui/tavern/**` 除 `service.py` 外**零 `import intimacy/companion`**；`service.py` 只调用 `relation_stage_name` / `level_name` 等**只读**方法。

### 5.6 LLM 不可用/返回垃圾/超时 → 完整降级（不变量）

| 场景 | 行为 |
|---|---|
| LLM 关闭（`_is_demo_mode` 或未配 Key） | `propose` 与叙述**都跳过**；本地模板叙述；`degraded=True`；**中性提示**（沿用 `_is_demo_mode` 语义） |
| `propose` 超时 | 走与"关闭"相同代码路径 → ③ narrate |
| `propose` 返回畸形 JSON / 越权变换 / 未知 var | 校验器 reject → ③ narrate（记 `reason`） |
| 叙述流中断 | 占位叙述 + 可 reroll；`transcript` 照常写入（**进度不丢**） |
| **共同约束** | **离线可玩、进度不丢、不弹错误框** |

---

## 6. UI 设计

### 6.1 页面结构（Tab / 分区）

`PageTavern` = `QTabWidget`（5 Tab）：

| Tab | P0/P1 | 内容 |
|---|---|---|
| **今夜** | P0 | 顶「章标题」条（`tavern_hud`）+ 叙述流（`tavern_narrative`）+ 快捷动作排（`tavern_input`）+ 自由输入行 |
| **世界书** | P0 | 条目表（增删改）+ 预算读数条（`tavern_worldbook`）+ `allow_propose`/预算设置行 |
| **我的故事** | P0 | 存档列表（继续/回看）`tavern_plays`（**列表项只显示章标题 + 相对时间，无序号**） |
| **人物** | P1 | 老板娘 + 2 客人卡（复用 `role_card.py`） |
| **记录** | P1 | `applied` 留痕 + 摘要（只读；**不呈现成功率/进度/胜率**） |

- **侧栏入口**：新增导航项 `("tavern", "酒馆", "glass", "\U0001F377")` —— 图标**复用已登记语义名 `glass`（酒杯）**，第 4 元 emoji 回退 `🍷`（不空白、不崩）。取图标只走 `icons.icon("glass")`（`icons.py` 已订阅 `theme_changed` 自动换肤）；**禁裸 emoji 上屏**。（D-V22-01 / §3.2 / §1.4 校正③）

### 6.2 信息层级（`今夜` Tab）

```
┌──────────────────────────────────────────────────┐
│  灯笼还亮着                        ← 章标题（无序号，Q4）│
├──────────────────────────────────────────────────┤
│  （叙述流：逐段/逐字出现，文字节奏）                    │
│                        ┌──────┐ ┌──────┐           │
│                        │重写  │ │改字  │  ← 文本级   │
│                        └──────┘ └──────┘           │
├──────────────────────────────────────────────────┤
│  问她照片里的人  先喝一口  静静等她开口  ← 快捷动作 4–6 │
├──────────────────────────────────────────────────┤
│  [ 也可以直接写下你想做的事…              ] [ 送出 ]  │
└──────────────────────────────────────────────────┘
```

- **重写/改字是文本级操作**，与状态无关（§5.2）。
- 快捷动作**只引图标名 + 文案**，**无裸 emoji**。
- **无任何数值**（无进度条、无好感、无计数）。

### 6.3 四主题 × 浅深：**只列语义键，不硬编码颜色**

| 用途 | 语义键（走 `theme_color(app_ctx, key, fallback)`；QSS 只引 token） |
|---|---|
| 页面底 | `bg` |
| 叙述卡片 / 列表项 | `bg_card` |
| 次级容器 / 输入框底 | `bg_light` / `surface_muted` |
| 正文 / 次要 / 提示 | `text` / `text_secondary` / `text_hint` |
| 分隔线 | `divider` |
| 焦点 | `focus_accent` |
| 主按钮 | `primary` / `primary_dark` |
| 强调（章标题装饰） | `accent` |
| 边框 | `border` |
| 降级提示（"这次她没听懂"） | `state_warn` |
| 错误（坏档） | `state_danger` |
| 已施加（记录 Tab） | `state_ok` |

- **四风格 id**：`ui_minimal` / `ui_cream` / `ui_night` / `ui_whale`；**浅/深两态**由 `theme_engine` 活动色板自动给出，酒馆**不感知具体色值**。
- **对比度**：正文对底 **≥ 4.5:1**，次级大字 ≥ 3:1（实施期用脚本审计，见 §10）。
- **不新增任何色值/token**；若确需新语义键，**只增不改**并同步 `_SEMANTIC_LIGHT/DARK_DEFAULTS`（`theme_engine`）——**本设计预期无需新增**。

### 6.4 字号 / QSS 纪律

- **字号只能写在 QSS**（`setPointSize` 在项目有"永久守卫测试"记录，**不要踩**）。
- **`font-family` 逐族加引号**（通用族裸写）：`font-family: "Resource Han Rounded CN", "Microsoft YaHei", "remixicon", sans-serif;`；**禁**整串包一对引号（v2.1 已修复的"死声明"缺陷）。
- QSS **只引 `${...}` token**，**禁新增裸色 `#RRGGBB`**。
- 酒馆的 QSS 增量**只加规则**（新 `objectName` 作用域），不改既有规则语义；`gui/themes/*.qss` 的改动**尽量小**（优先用控件级 `setStyleSheet` + `objectName`，减少对四风格文件的侵入）。

### 6.5 设置归属：`tavern.json` 私有 vs 全局运行时（**读时取，不缓存**）

**核心结论**：「酒馆」**不写 `GuiConfig`（D-V22-08），也不会因此"换主题/换动效档位后失联"** —— 只要守住下面两条铁律。

**两条铁律**：

1. **只把"酒馆私有选择"落 `tavern.json.settings`**；凡是**派生自全局**的（颜色 / 动效档 / 字号 / 字体），**一律不落盘**。
2. **派生自全局的值，在每个渲染 / 触发时机用运行时 API 现取现用**（**不在 `__init__` 缓存、不存成字段**）。

| 设置项 | 归属 | 取用方式（源码依据） | 换主题/换档位后是否即时生效 |
|---|---|---|---|
| `allow_propose` / `allow_free_input` / `llm_narration` | **`tavern.json.settings`**（私有；默认值在 `model.py` 常量） | `service` 读 `store` | 与主题/动效无关，不受影响 |
| 世界书启停 / 字符预算 / 扫描深度 / 递归上限 / 摘要间隔 | **`tavern.json.settings`**（私有） | 同上 | 无关 |
| 上次打开的 Tab / 最近一局 `play_id` | **`tavern.json`**（私有 UI 记忆） | `service` 读 `store` | 无关 |
| **动效档位（跟随全局）** | **不落盘** | **每次触发现取 `motion.enabled()` / `motion.level()`**（`gui/motion.py:114/109`） | ✅ 即时（下次触发即为新档；`off` 时 `enabled()` 为假 → 不播放） |
| **动效时长 / 缓动** | **不落盘** | `motion.duration(base_ms)` / `motion.easing()`（单一收口，**禁硬编码 ms**） | ✅ 即时 |
| **主题色**（底/卡/文字/强调/警示…） | **不落盘、不缓存 `QColor`** | **绘制/刷新时** `theme_color(app_ctx, key, fallback)`（§6.3） | ✅ 即时（优先 QSS token，QSS 由 `theme_engine` 重灌） |
| **字号** | **不落盘** | **只写在 QSS**（`setPointSize` 有永久守卫测试，见 §6.4） | ✅ 即时 |
| **字体族** | **不落盘** | QSS `font-family`（逐族引号；族由 `gui/fonts.py` 注入） | ✅ 即时 |

**"失联"的唯一真实来源 = 在构造期缓存了全局派生值**（与"写不写 `GuiConfig`"无关）：若某控件在 `__init__` 里把 `theme_color(...)` 的结果 `QColor` 存成字段、或把 `motion.enabled()` 存成布尔，用户之后换主题/换档位时该控件**不会自动更新**。**对策（批 2 工程师照做）**：

- **颜色**：在 `paintEvent` / `refresh()` 里**现取**；**禁止**在 `__init__` 缓存色值。
- **换肤兜底**：`PageTavern` 在 `__init__` 里**订阅 `app_ctx.theme_engine.theme_changed`**（既有信号，`main_window.py:474`、`sidebar.py`、`icons.py`、`elevation.py` 均如此），槽内 `update()` 重绘。`icons.py` **已自行订阅**（图标随之换肤，酒馆无需处理）。
- **动效**：**无需订阅** —— 触发时现取 `motion.enabled()`，天然跟随全局；若「记录」等只读面要显示"动效已关"提示，在 `on_enter()` 里现取刷新即可。

**可选集成点（记于批 3，非必须）**：若日后要把 `allow_propose` 开关也放进全局「设置」页 —— **仍不碰 `gui/config.py`**，由设置页调用 `TavernService.get_settings()/set_settings()` 读写 `tavern.json`（跨域调用合法，D-V22-08 不变）。默认 UI 入口仍建议留在酒馆页内（§8 批 2/3）。

---

## 7. 动效清单（只能用 `gui/motion.py` 既有能力）

| 场合 | 做法 | 依据 |
|---|---|---|
| 叙述流式渲染 | **文字节奏**（逐字/逐段出现，复用 `chat_stream_chunks` 节奏） | 原生母题① |
| 生成中指示 | **文字省略号节奏**（`……` 循环，复用 `kb_dialog.py` 既有先例） | 原生母题①；**不得**用跳动三点/柱条/涟漪 |
| 重掷/重写切换 | 叙述块 **`motion.fade()` 淡入**（≤220ms） | 原生母题②（既有元素呼吸/淡入） |
| Tab / 卡片切换 | 沿用 `motion` 既有过渡（可选），不新增母题 | 既有 |
| `off` 档 | **不创建任何动画对象**（`motion.enabled()==False` → 静态形态） | `motion.py` 纪律 |

**明确不做（第三类几何母题，一律判"不做"）**：跳动三点、电平柱条、同心涟漪、旋转环、骨架屏微光、打字机光标、翻页、烛光、粒子、错峰入场、进度条。**宁可不做，也不要有外来感。**

**可断言**：AST/`grep` 扫描 `gui/widgets/tavern/**` 与 `gui/pages/page_tavern.py` **零** `QPropertyAnimation(` 直接实例化、**零** `setDuration(<常量>)`。

---

## 8. 分批任务表（V22-00 + 批1–批5）

> 格式对齐 design-v21 §5：`ID / 任务 / 涉及文件 / 依赖 / 验收 / 独占`。**批间可并行关系**见 §3.4。

### 批 0 · 契约冻结（域0，先行串行）

| ID | 任务 | 涉及文件 | 依赖 | 验收 | 独占 |
|---|---|---|---|---|---|
| **V22-00** | **契约冻结**：`tavern.json` schema v1（§4.1 全字段）；7 变换白名单与 pre/post（§4.2）；三条不变量 I1/I2/I3；三级路由枚举与 `resolution` 字段形状；五段式段名 `PROMPT_SEGMENTS`；世界书条目字段表；`NAV_ITEMS` 新增项形状；设置默认值 `SETTING_DEFAULTS` | 本文 §4 + `gui/tavern/__init__.py`（常量）+ `model.py`（默认结构骨架）+ `errors.py` | — | 常量可 import；`default_tavern()` 结构与 §4.1 一致；`merge_defaults({})` 不抛；`__init__.py` **零 Qt**（无 `QApplication` 可 import） | 域0 单人 |

### 批 1 · 纯逻辑内核并行（域1–5，全部零 Qt，可 offscreen / 无显示测）

| ID | 任务 | 涉及文件 | 依赖 | 验收 | 独占 |
|---|---|---|---|---|---|
| **V22-01** | 数据层：默认结构 / 读时迁移 / 原子写 / 快照轮转 / 坏档恢复矩阵 | `store.py`、`tests/test_v22_model.py`、`test_v22_store.py` | V22-00 | 旧档缺键 → 类默认（零迁移）；**坏档矩阵 L0–L6 逐级不抛**；写入中断（模拟 `.tmp` 残留）→ 旧档完好；`os.replace` 被调用；未知字段不销毁 | 域1 |
| **V22-02** | 引擎：7 变换 pre/post + I1/I2/I3 + 6 硬禁区 + 显式 seed | `engine.py`、`tests/test_v22_engine.py` | V22-00 | 每条变换 pre 不满足 → 拒绝且 `reason` 正确（14 例）；6 硬禁区各有用例；`vars` 白名单外键名被拒；同 seed 同输入 → 同结果 | 域2 |
| **V22-03** | 路由：三级 + 降级 + 留痕 | `intent_router.py`、`tests/test_v22_router.py` | V22-00/02 | 命中词表 → `verbatim`；未命中且 `allow_propose=True` 且 LLM 可用 → `propose`；**`allow_propose=False` → 不调用 LLM**；LLM 关闭/超时/畸形 → `narrate`；**三档都不抛**；`resolution` 字段齐全 | 域3 |
| **V22-04** | 世界书：触发 / selective logic / 预算 / 递归 / 脏数据 | `worldbook.py`、`content/**`、`tests/test_v22_worldbook.py` | V22-00 | 四种 selective logic 各有用例；超预算按 `weight→order→uid` 淘汰；`recursive_max_depth` 生效且不死循环；**脏正则被丢弃且不崩**；`constant > 5` 被裁剪并记日志 | 域4 |
| **V22-05** | prompt 与摘要：五段式 + reroll 差异 + 摘要落盘校验 | `prompt.py`、`summarize.py`、`tests/test_v22_prompt.py` | V22-00/04 | 五段顺序与 role 固定；`reroll` 版**不含**上一版叙述文本；摘要超长/空/含越权内容 → **拒绝入库（保留旧摘要）** | 域5 |

### 批 2 · UI（域6，依赖批 1）

| ID | 任务 | 涉及文件 | 依赖 | 验收 | 独占 |
|---|---|---|---|---|---|
| **V22-06** | 页与 Tab 骨架 + 叙述流（流式 + 重掷 + 编辑文本）+ `TavernService` | `page_tavern.py`、`tavern_narrative.py`、`service.py` | V22-01…05 | 流式渲染复用既有节奏；**reroll 只改 `transcript` 该拍、`vars`/`node_id` 断言不变**；编辑只允许改 `text`；`off` 档无几何母题动画；**`page_tavern` 之外内核零 Qt** | 域6 |
| **V22-07** | 输入行 + 快捷动作排 + 顶部状态条 | `tavern_input.py`、`tavern_hud.py` | V22-06 | 4–6 槽按钮全用 `icons` 矢量/字形（**无裸 emoji**）；**状态条只显示章标题、零数值、零序号**（Q4）；快捷键不与既有热键冲突 | 域6 |
| **V22-08** | 世界书编辑器 + 我的故事列表 | `tavern_worldbook.py`、`tavern_plays.py` | V22-06 | 增删改落盘原子写；预算读数条随条目变化；列表可继续/回看且**列表项无序号**；**坏档 → 中性提示而非崩** | 域6 |

### 批 3 · 接线（域7，依赖批 2）

| ID | 任务 | 涉及文件 | 依赖 | 验收 | 独占 |
|---|---|---|---|---|---|
| **V22-09** | 侧栏新页 + 快速开局浮窗入口 + AppContext 字段 + 页注册 | `sidebar.py`、`extras.py`、`app_context.py`、`main_window.py` | V22-06/07/08 | `NAV_ITEMS` **纯增 1 项**，既有 10 项 key/label/信号零回归；浮窗复用 `_open_mini_games()` 范式且关闭即隐藏；`AppContext` 既有字段零改动 | 域7（**`sidebar.py` 与 `extras.py` 各 1 人**） |

### 批 4 · 内容与四主题打磨（域4/6，可与批 2/3 部分并行）

| ID | 任务 | 涉及文件 | 依赖 | 验收 | 独占 |
|---|---|---|---|---|---|
| **V22-10** | 内容包：≥3 章 × 4–6 storylet + 2 结局 + 世界书（`constant ≤5`） | `gui/tavern/content/lantern/**` | V22-04 | 每章 3–5 个高影响选择（走 `vars`）；每条世界书符合撰写规范；**全包零 R-A 词、零序号** | 域4 |
| **V22-11** | 人物 Tab（老板娘 + 2 客人）+ 记录 Tab（只读） | `content/**`、`tavern_trace.py`、`tavern_plays.py` | V22-10/08 | 卡可导入导出（复用 `role_card.py`）；记录 Tab 只读且**不呈现成功率/进度/胜率**；关系只读（Q2） | 域6 |
| **V22-12** | 四主题视觉核对（浅/深 × 4 风格，逐页截图对照） | `gui/widgets/tavern/**`（仅样式） | V22-06/07/08 | 四风格无"外来感"；**QSS 无新增裸色**；正文对比度 ≥4.5:1；`ui_night` 下不刺眼；**字族逐族加引号** | 域6 |

### 批 5 · 收口（域8，依赖全部）

| ID | 任务 | 涉及文件 | 依赖 | 验收 | 独占 |
|---|---|---|---|---|---|
| **V22-13** | 双 spec 同步（内容包 datas + `gui.tavern` hiddenimports）+ 打包冒烟 | `maid_coder_gui.spec`、`maid_coder_gui_onefile.spec` | V22-09/10 | 双 spec 一致；onedir/onefile 包内 `.../tavern/content/` 有内容包；exe 内可开一局 | 域8 |
| **V22-14** | **红线扫描 + 全量回归 + 真机留档** | 留档文档 | V22-11/12/13 | `requirements*.txt` **diff 为空**；R-A 词表 + 序号正则扫描零命中；`test_v22_no_ra.py` 绿；全量 pytest 零回归；py_compile 绿；四主题真机截图留档 | 域8 |
| **V22-15** | 文档收口（README 用法 / CHANGELOG / 世界书撰写规范 / `THIRD_PARTY.md` 参考未采用登记） | `README.md`、`CHANGELOG.md`、`content/README.md`、`docs/THIRD_PARTY.md` | V22-14 | 如实描述"字符预算为近似"；CCv3 登记在"参考未采用"表（无 LICENSE 副本入库）；无自评分 | 域8 |

**裁剪顺序（资源紧张时）**：`V22-11 记录 Tab`（降为只读摘要）→ `V22-11 人物 Tab` → `V22-10` 首发减为 1 章 → 快速开局浮窗（保留侧栏页）。**不裁**：V22-00…V22-09（P0 全量）与 V22-14 红线/回归。

**必须串行**：V22-00 → 批1 并行 → 批2 → 批3 → 批4（可与批2/3 部分并行）→ 批5。

---

## 9. 风险与验收

### 9.1 高风险点（定级 + 缓解）

| # | 风险 | 定级 | 缓解 | 回退 |
|---|---|---|---|---|
| **R1** | **`propose` 档命中率不可知**（research §3.3 论文未量化证明，附录 B-6） | **高** | 三级路由以 `verbatim` 为主路径；`mode` 分布可统计（「记录」Tab）；**默认开但可关**（D-V22-03） | 关掉 `propose`，退化为完全确定模式 |
| **R2** | **字符预算 ≠ token 预算** | 中 | 保守取值；单条 ≤200 字；文档**如实标注"近似"** | 下调 `worldbook_budget_chars` |
| **R3** | **reroll 误改状态**（最危险的脏数据） | 中 | 状态/文本分离（§5.2）；**单测断言 reroll 只改 `transcript`** | 禁用 reroll 按钮 |
| **R4** | **坏档导致读档崩溃** | 中 | 坏档恢复矩阵 L0–L6（§4.4）；`load()` 绝不抛 | 空档兜底 |
| **R5** | **内容包路径随包后读不到**（校正② 类事故） | 中 | datas target = 源码相对路径（`source_dir == gui/<target>`）；**两态验证法（源码态 + frozen 态 + 反向守卫 + 双包冒烟）见 §3.2 附注**；**打包态真机开一局取证** | 内容包内嵌为 Python 常量（最后手段） |
| **R6** | **主题切换后"外来感"** | 中 | 只引语义键；四主题 × 浅深逐页截图（V22-12） | 回退到既有卡片形态 |
| **R7** | **中大型规模维护成本** | 中 | 文件域切分（§3.4）+ 纯逻辑零 Qt 可测（D-V22-06） | 按 §8 裁剪顺序缩减 P1/P2 |
| **R8** | **随手加 `GuiConfig` 键踩 `save()` 陷阱** | 低 | D-V22-08：**不改 `GuiConfig`** | — |
| **R9** | **导航图标名不存在**（校正③） | **已消除**（降为无风险） | **已定复用登记名 `glass`（`icons_manifest.json` 实存 151 名中之一，且未被任何导航项占用）零构建**；新增项 = `("tavern","酒馆","glass","\U0001F377")`，第 4 元 emoji 回退 `🍷` | emoji 回退即可用 |
| **R10** | **换主题/换动效档位后页面"失联"**（缓存在构造期的全局派生值不刷新） | 低 | §6.5 两条铁律：全局派生值**读时取、不缓存**；`PageTavern` 订阅 `theme_changed` 重绘；动效现取 `motion.enabled()` | QSS 由 `theme_engine` 重灌；图标由 `icons.py` 自订阅换肤 |

### 9.2 必须**真机视觉验证**的点（本机 offscreen 画不出中文，文字/字形判断必须真实平台）

| 项 | 为什么 mock 测不出 |
|---|---|
| **中文文字渲染 / 换行 / 字重** | offscreen 环境无法真实栅格化中文，字形/换行/断句判断必须真机 |
| **叙述流式观感（文字节奏）** | 逐字/逐段的实际节奏与阅读舒适度需真机目视 |
| **四主题 × 浅深 × 酒馆页逐页对照** | 颜色/对比度/"外来感"需真实屏幕 |
| **图标字形在真实 DPI 下的清晰度** | offscreen 无真实 DPI 缩放 |
| **重掷/编辑的用户操作路径** | 交互手感需真机 |
| **打包态开一局（onedir + onefile）** | 内容包随包路径与 frozen 解析需真实 exe |

### 9.3 可**纯函数单测**（无需真机 / 无需联网）

1. schema 迁移：空档 / 缺键 / 键类型错 / 未来高版本 → 均不抛，回落默认；
2. 原子写：模拟中途失败 → 旧档完好；
3. 引擎：7 变换 ×（pre 满足/不满足）= 14 例 + 6 硬禁区 + `vars` 白名单外键名 → `reason` 逐一断言；
4. 不变量 I1/I2/I3 的**违反用例**各有断言（最关键的是"能抓到违反"）；
5. 路由三档 + LLM 关闭 + 超时 + 脏返回，**均不抛且留痕字段齐全**；
6. 世界书：四种 selective logic、预算淘汰顺序、递归深度上限与死循环、脏正则；
7. prompt：五段顺序、`reroll` 不含上版文本；
8. R-A 扫描：`tavern.json` + 内容包 + UI 文案 + **序号正则** 零命中；
9. `vars` 键名越权、`node_id` 悬空、`transcript` 长度回退 → 全部被拒；
10. AST 扫描：`gui/tavern/**`（除 `service.py`）零 Qt 依赖；`gui/widgets/tavern/**` 零直接 `QPropertyAnimation(`。
11. **内容包两态可读**（§3.2 附注）：源码态 `get_resource_path("tavern/content/lantern/book.json").exists()` 为真；mock `sys.frozen=True` + `sys._MEIPASS=<tmp>` 后同一断言为真（三种子文件各断一次）；**反向守卫** `not get_resource_path("tavern_content").exists()`。
12. **导航项与图标名**：`NAV_ITEMS` 长度 == 11，且新增项形如 `("tavern","酒馆","glass","\U0001F377")`；断言 `icons.has("glass")` 为真，且第 3 元（图标名）∉ 既有 9 个实占名。

**需 mock**：LLM 调用（`api.chat` / `chat_stream_chunks`）→ 成功 / JSON 畸形 / 超时 / 抛异常 四种。

---

## 10. 测试要点 + DoD

### 10.1 测试要点

| 层 | 断言点 |
|---|---|
| `model` | `default_tavern()` 结构；`merge_defaults` 缺键补默认、类型守卫、未知字段保留；`migrate` 旧版本 |
| `store` | 原子写（`os.replace` 被调）；`.tmp` 残留不损坏旧档；快照轮转保留 N 份；坏档矩阵 L0–L6 不抛 |
| `engine` | 7 变换 pre/post；I1/I2/I3 违反用例；6 硬禁区；seed 可复现 |
| `intent_router` | 三档 + `allow_propose=False` 不调 LLM + 降级 + 留痕字段 |
| `worldbook` | 四 selective logic；预算淘汰顺序；递归上限；脏正则丢弃；`constant` 超 5 裁剪 |
| `prompt` | 五段顺序与 role；`reroll` 不含上版文本 |
| `summarize` | 触发条件；越权/超长拒绝入库 |
| UI（offscreen） | 构造 `PageTavern`；表格/列表项**无序号**；状态条**无数值**；快捷动作按钮无裸 emoji；坏档提示不崩 |
| 隔离 | AST：内核零 Qt（除 service）；内核不 import 业务写接口；单测用 `tmp_path` |
| 红线 | R-A 词表 + 序号正则扫描；`requirements*.txt` diff 空 |

### 10.2 DoD（对照 research §7 与 team lead 要求逐条）

1. **中大型形态立住**：侧栏独立页 + 5 Tab；「我的故事」可多局继续/回看；坏档不崩。
2. **状态机立住**：7 变换 + 3 不变量 + 6 硬禁区 + 显式 seed，全部可单测。
3. **三级路由立住**：`verbatim` 主路径零 token；`propose` 默认开可关；`narrate` 兜底；**全留痕**。
4. **高自由度成立**：自由输入可改状态（①/②），未识别不报错（③）；**降级完整、离线可玩、进度不丢、不弹错误框**。
5. **关系只读（Q2）**：读关系做语气/称呼，**零写入**；UI 零关系数值。
6. **零序号（Q4）**：UI 只显示章标题；序号正则零命中。
7. **零新增第三方依赖（R-F）**：`requirements*.txt` diff 为空；不 vendor 任何第三方代码。
8. **数据不乱**：原子写 + 单写点 + 读时迁移 + 快照轮转 + 坏档恢复 + 与业务数据隔离，全部可断言。
9. **四主题融合**：只引语义键、无新增裸色、字族逐族引号、正文对比度 ≥4.5:1、四主题 × 浅深逐页真机对照无"外来感"。
10. **动效克制**：只用 `motion` 既有能力 + 只说书人两类原生母题；`off` 档不创建动画对象；零第三类几何母题。
11. **红线归零**：R-A / R-D / R-F / R-H 全条对照；保护区零触碰；R-D 契约（既有 10 项导航/既有入口/更新链）零回归。
12. **打包 + 回归**：双 spec 同步；onedir/onefile 包内内容包齐、exe 内可开一局；py_compile + pytest 全绿；真机留档；README/CHANGELOG 诚实标注"字符预算为近似"，无自评分。
13. **三处契约细节已固化（本设计补）**：① 侧栏新项 = `("tavern","酒馆","glass","\U0001F377")`（复用已登记名 `glass`，**零构建、不补图标**）；② 内容包路径 `source_dir == gui/<target>`（`('gui/tavern/content','tavern/content')`）且**两态可读**（§3.2 附注四条验证）；③ 设置归属：**私有落 `tavern.json`、全局派生值读时取不缓存**（§6.5，换主题/换档位即时生效，零 `GuiConfig` 改动）。

---

## 11. 建议复议 / 保留意见（**单独列出，不默默改**）

> 对 team lead 的 4 个决定，**本文全部执行、无反对**。以下仅为**保留意见与风险提示**，供 team lead 知悉，**不影响执行**：

1. **Q1（`propose` 默认开）—— 保留意见一（低强度）**：research 附录 B-6 明确"`propose` 可靠性**未被证明**（8 人/2 场景/纯定性）"。本文据此把 `verbatim` 定为主路径、`narrate` 定为兜底，**并在「记录」Tab 暴露 `mode` 分布**。若首发后实测 `propose` 失败率偏高，建议**不改默认值**（用户已选"自由"），而**优先补词表**（把高频失败语义迁到 `verbatim`）——这条已写进 `reason` 留痕设计（§4.2），无需额外机制。**不请求复议，仅备案。**

2. **一处**对 research 的**技术性更正**（非决定层，已落 §1.4 校正①②③）：controller 落点、内容包打包路径、导航图标名依赖 —— research 文档在这三处的落点与现状代码/资源不符，本文按真实代码修正（**校正③ 现已定死：复用登记名 `glass`，零构建、不补图标**；**校正② 附 §3.2 两态验证法**）。**请 team lead 知悉**，若 research 作者后续更新文档，以本文 §1.4 为准。

3. **一处需后续单独立项的开放项**（本期不做，记录备查）：**T-20「记忆钩子」**——把故事里的物件写进她日后的闲聊，**触碰业务数据（`memory`/`companion`），与 Q2 的"只读"口径相冲**。本文**不做**，留待后续版本单独评审（research §7.1 P2）。

4. **批 5 清理项（engine 口径对齐，非阻断，已定性）**：`engine.is_forbidden` 目前仍扫描 `args["write_vars"]`，但 `ARG_KEYS` 未收、`_apply_post` 不施加该键 → 任何 `write_vars` 实际必被 `bad_args:unexpected_args:write_vars` 拒绝（**fail-closed，行为安全**）。**功能无风险、engine 无需改**，但该"死扫描"会留下"看起来支持 `write_vars`"的误导。**建议批 5 由 eng 侧清理**：删除 `is_forbidden` 中对 `write_vars` 的扫描分支（或就地加注释标"仅防御、非契约"），使 `ARG_KEYS` / `is_forbidden` / 文档**单一口径**。**本轮不改**（不触碰已交付的批 1 `engine.py`）。

---

## 附录 · 引用（仅引用结论 + 链接，不摘录正文）

- 机制来源：SillyTavern 官方文档（World Info / Prompt Manager / Author's Note / STscript）、`character-card-spec-v2`（无许可，只引字段名）、`chub.ai` Lorebooks 字段说明 —— 详见 `docs/research-tavern-game.md` 附录 A（均为**结论引用**，**未复制代码/正文**）。
- 学术方法：Góngora et al.《World-State Transformations for Neuro-symbolic Interactive Storytelling》arXiv:2605.24719 与 Pith 评审（明确其可靠性未证明）。
- **规范引用（可选，P1）**：`kwaroran/character-card-spec-v3`（**MIT**）—— **只引字段模型 + 链接**，登记到 `docs/THIRD_PARTY.md` 的"二、参考未采用"表；**不复制规范正文、不加 LICENSE 副本、不加 About 条目**（见 §3.2）。
- 仓内只读依据：逐条见 §1.3（本次已核）与 §1.4（校正）。

> 文档结束 · 高见远 · 2026-09-15 · 基线 v2.1.x · 零新增第三方依赖 · 不 vendor · 保护区零触碰 · 最大风险 = `propose` 可靠性（以三级路由 + 降级留痕对冲）
