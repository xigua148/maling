# 码铃（MaLing）v2.1 增量架构设计 ——「UI 体验进阶：QSS 打磨 × 克制动效 × 零依赖毛玻璃 × 矢量图标 × 暗色精修」

- 版本：v2.1（增量设计，格式对齐 design-v16 / v17 / v18 / v19 / v20）
- 文档状态：草案（Q-V1 / Q-V2 / Q-V3 / Q-V4 / Q-V8 已由用户/团队负责人拍板并锁死；其余 Q 按 PM 建议默认值收敛；本文标「Q-Vx 裁决」）
- 维护人：高见远（架构）
- 关联文档：`docs/prd-v21.md`（需求源，v2.1a / 2026-09-11，412 行 / 33 需求 / 12 Q）+ `docs/design-v19.md`（**直接基线**：视觉重塑，四风格 / 六字体 / 强调色派生）+ `docs/design-v20.md`（格式基准：自动更新链，**本轮零触碰**）+ `docs/prd-v16.md` §红线（R-A/R-D/R-F 源）+ `docs/font-research-2026-09-10.md`（字体授权先例）+ 视觉稿 `D:/【试用测试】/ui_concept/码铃_UI三方向对比稿.html`（动效曲线参考 `--t: .28s cubic-bezier(.4,0,.2,1)`）
- **基线：v2.0.0**（`version.json.version = 2.0.0`；双产物 onedir `maling/` + onefile `MaLing_single.exe`；自动更新链已上线）
- 设计纪律重申：**功能面零改动**（聊天 / 记忆 / 陪伴 / 群聊 / Pi 引擎零触碰）；**整个 ui-v21 实现不引入任何新的运行时第三方依赖**（守 R-F）；**v2.0 更新链全部文件与 `main.py` 更新编排段零变更**；不推翻 v1.9 四风格 / 六字体 / 强调色派生任何已定内容（R-D）；工作副本仅限 `maling_agent_dev/` 与 `docs/`，**严禁触碰 `D:/【开发中版本】/maling_v1.0.0_src/`**。

---

## 1. 范围与现状基线（先读我）

### 1.1 三块范围（承接 PRD §2 需求池，33 条）

| 块 | 内容 | 需求条数 | 主要落点 | 可复用 vs 需新增 |
|---|---|---|---|---|
| **S 样式打磨** | 四风格 QSS 二次精修 / 控件五态补齐 / 通用控件细节 / 浮层阴影分层 / 代码块与编辑器配色 / splash 色调协调 | 6（P0×3、P1×2、P2×1） | `gui/themes/base.qss` + 四风格 QSS + `page_editor.py` | **高复用**：v1.9 四风格 QSS 齐备（各 13–14KB）与 `${变量}` 机制完备，本轮仅"加规则、不动机制、不动色值" |
| **M 动效** | 动效基建 / 切页过渡 / 气泡入场 / 侧栏微交互 / 浮层出现消失 / 待机微动效 / 总开关+强度档 | 7（P0×4、P1×2、P2×1） | 新 `gui/motion.py` + `main_window.py` + `chat_panel.py` + `message_bubble.py` + `sidebar.py` + `config.py` + `page_settings.py` | **全新增**：全树零 `QPropertyAnimation`（已核 `grep -rn "QPropertyAnimation\|QEasingCurve" gui/` 零命中），无历史实现可复用 |
| **G 毛玻璃** | 能力探测 / 主窗 Mica / 浮层 Acrylic / 总开关+自动降级 / 四风格×浅深配色协调 | 5（P0×3、P1×2） | 新 `gui/glass.py` + `main_window.py` + 对话框类 + `config.py` + `page_settings.py` | **全新增**：全树零 `Mica/Acrylic/DWM` 调用（已核）；既有 `WA_TranslucentBackground`（`chat_window.py:61` / `message_bubble.py:101` / `maid_pet.py:642`）可作参考但非 Mica |
| **I 矢量图标** | 统一图标 API / 侧栏替换 / 顶栏按钮替换 / 状态栏与设置页替换 / 四态着色 / 授权登记 | 6（P0×3、P1×3） | 新 `gui/icons.py` + `sidebar.py:63-74` + `chat_panel.py` + `main_window.py` + `page_memory_book.py` + `docs/THIRD_PARTY.md` + `page_about.py` | **全新增**：现状为 emoji/unicode 文本字形；全站以 `QIcon` 加载资源的仅 4 处（`main.py:1497` / `tray_manager.py:45` / `page_role.py:1432` / `sidebar.py:352`）+ `sidebar.py:103` 的 `QIcon.fromTheme` |
| **D 暗色完善** | 对比度审计修正 / 深色细节精修 / 跟随系统实时性 / 深色×毛玻璃适配 / 深浅切换过渡 | 5（P0×2、P1×2、P2×1） | 四风格 `colors_dark`（`theme_engine.py:787-906` `_DARK_OVERRIDES`）+ 四风格 QSS + `theme_engine` 轮询器 + `glass.py` | **中复用**：v1.3 深色 + v1.9 四风格深色变体（**PM 已复核定稿**，`_DARK_OVERRIDES` 已含四风格）已在位；本轮做"达标审计 + 精修 + 实时性" |
| **C 设置与开关** | 「外观与效果」区 / 省电模式 / 持久化即时生效 / 分组整理 | 4（P0×2、P1×2） | `page_settings.py:105-201` + `config.py` | **中复用**：复用 `_create_section` + `cfg.save()` 既有机制；新键沿用 v2.0 的 `hasattr` 白名单范式 |

Non-goals（PRD §6 全承接）：**不换 Fluent 组件库重写界面** / **不改立绘与桌宠资产**（`gui/assets/maid`、`maid_pet`、`roles` 零改动）/ **不改业务逻辑与 Pi** / **不改 v2.0 自动更新链** / **不推翻 v1.9 四风格六字体命名** / **不做动态主题与壁纸与 UI 缩放** / **不做图标语义随风格切换** / **不做启动动画（Q-V10）** / **不引入 QSS 参考库为运行时依赖（Q-V12）** / **不改 `version.json` 与 `core.__version__`**。

### 1.2 已锁死的方向性决策（**不得再抛回**，本文照此执行）

| 项 | 裁决（团队负责人已锁） | 本文落点 |
|---|---|---|
| **Q-V1（R-F 冲突）** | **不放宽 R-F**，走**零依赖替代**：动效 = PySide6 内置 `QPropertyAnimation`/`QEasingCurve`；毛玻璃 = `ctypes` 直调 Windows DWM；图标 = 图标字体 TTF + `QFont`/`QPainter` 着色（复用 `fonts.py` 随包范式）；`qtawesome` **降级为构建期工具**（仅构建期导出图标字体/子集，不进 `requirements*.txt`、不进 exe） | D-V21-03 / D-V21-06 / D-V21-07；§8 R-F |
| **Q-V2（动效强度）** | **克制**：仅切页过渡、气泡入场、浮层出现/消失、侧栏微交互；**时长 ≤ 220ms**；缓动克制；默认档 `standard`，设置页可选 `off`/`soft`/`standard` | D-V21-01 / D-V21-02；§4.2 |
| **Q-V3（毛玻璃适用面）** | **主窗 Mica + 浮层 Acrylic**（不铺满所有面板）；**Win10 自动降级为纯色**；**默认开、不可用自动降级、可在设置关** | D-V21-03 / D-V21-04；§4.3 |
| **Q-V4（图标承载）** | **图标字体 TTF 为主**（复用 v1.9 字体随包范式）+ PySide6 自带 `QtSvg` 仅作多色补充；**零运行时依赖**；不采用 qtawesome 运行时集成 | D-V21-06 / D-V21-07；§4.4 |
| **Q-V8（毛玻璃 vs 透明度滑杆）** | **互斥/联动**：开毛玻璃则运行时锁定窗口透明度为 100% 并禁用滑杆 + 提示"毛玻璃与窗口透明度互斥"；关毛玻璃恢复滑杆原值 | D-V21-05；§4.3 |
| 其余 9 Q（V5/V6/V7/V9/V10/V11/V12 + 隐含项） | **按 PM §3 建议默认值收敛**（V5 = OFL/Apache-2.0 且允许随包商用的图标集；V6 = 启动 ≤ +5% / 内存 ≤ +20MB / 拖动无卡顿；V7 = 不自动探测硬件，手动省电模式 + 环境不支持自动降级；V9 = 事件监听优先、回落缩短轮询；V10 = 不加启动动画；V11 = 不换图标语义仅着色；V12 = QSS 库只参考不引入） | D-V21-06/09/10/11/13；§8 R-P |

> **本设计不升级任何 Q 项给用户裁决**：逐条核对代码现状后，9 个建议项均无阻塞性冲突（理由见 §9.4）。

### 1.3 已核实的关键对接点（v2.0.0 源码逐行核）

| 对接点 | 位置（已核） | v2.1 用途 |
|---|---|---|
| `ThemeEngine.theme_changed = Signal(str)` | `theme_engine.py:43` | **契约保留区**；毛玻璃随深浅重新应用、图标缓存随换肤清空的订阅源（签名零变更） |
| `ThemeEngine.load_theme`（`${...}` 替换 + `app.setStyleSheet` + `app.setFont`） | `theme_engine.py:349-406` | **契约保留区**；**毛玻璃开时根窗口透明**需要与它协同（见 D-V21-04 的 QSS 条件规则） |
| `_active_palette` / `derive_accent_palette` / `set_custom_accent` / `is_dark_effective` / `apply_night_lock` | `theme_engine.py:501 / :728 / :526 / :437 / :999` | **契约保留区**：动效/毛玻璃/图标**一律走活动色板取色**，不得绕过 |
| `_read_system_light_theme()`（`winreg` 封装范式） | `theme_engine.py:22-36` | 毛玻璃/系统减少动画/系统深浅监听**沿用同一"Windows 原生能力封装"范式** |
| `_start_system_poll` / `_poll_system_mode`（5min `QTimer`） | `theme_engine.py:541 / :561` | D-3 实时性改造点（事件监听优先，回落缩短轮询） |
| `_DARK_OVERRIDES`（含四风格深色变体，PM 已复核定稿） | `theme_engine.py:787-906` | D-1 对比度审计的**唯一色值真值源**（审计只读，不改值除非不达标） |
| `_SEMANTIC_LIGHT/DARK_DEFAULTS` | `theme_engine.py:909 / :924` | 新增语义键时须同步（若 S 组需新键） |
| `gui/fonts.py`：`FONT_DIR_REL` / `BUNDLED_FONTS` / `register_bundled_fonts` / `resolve_font_path`（`get_resource_path`） / `font_family_chain` | `fonts.py:27 / :57 / :119 / :99 / :179` | **图标字体随包的直接范式**（D-V21-07 同构复用）；字体系统本轮**零改动** |
| `main()` 启动链：`QApplication`(:1484) → `GuiConfig.load()`(:1512) → `register_bundled_fonts()`(:1516-1521) → `MainWindow(app_ctx)`(:1605) → `window.show()`(:1607) → `_mount_v13_services`(:1612) → `_mount_v14_services`(:1615) → **更新子系统**(:1617-1625) | `main.py:1479-1627` | **外观类插入点**：动效 configure、图标字体注册在 :1521 之后；毛玻璃 apply 在 :1607 之后。**更新编排段 :1617-1625 零变更** |
| `_quit_stop_services()`（v1.6.1 完整退出序列 + 末步 `_maybe_launch_updater`） | `main.py:641-713` | **不动**（R-D + v2.0 更新链）；动效不新增退出步（动画随窗口销毁自然收束，`stop_all` 仅在切档时调） |
| `MainWindow.__init__` 初始化序（ThemeEngine → set_theme_mode → set_custom_accent → load_theme → 窗口属性 → `setWindowOpacity`(:82) → 布局(:85) → 页面栈(:88) → 状态栏(:91) → 信号(:94)） | `main_window.py:36-97` | G-1 毛玻璃/透明度互斥的**主落点**；M-1 切页动效挂 `page_stack` |
| `central_splitter` + `sidebar.setFixedWidth(180)` + `page_stack(QStackedWidget)` | `main_window.py:107-121 / :115` | M-1 切页过渡落点（fade 新页，非滑动整页） |
| 状态栏三 `QLabel`（`status_theme`/`status_mode`/`status_api`） | `main_window.py:263 / :266 / :269` | I-3 图标化落点 |
| `SidebarWidget.NAV_ITEMS`（10 项，第三元为 emoji/unicode；`"project"` 项为 `None`） | `sidebar.py:63-74` | I-1 图标替换主战场（结构改造见 D-V21-06） |
| `sidebar._init_ui` 图标分支（`QIcon.fromTheme("folder")` → 退化 emoji；`isinstance(icon,str)` 分支） | `sidebar.py:102-115` | I-1 回退链改造点 |
| `ChatPanel.title_row`（`exportChatBtn`/`expandChatBtn`/`styleSwitchBtn` 等 + `status_label`） | `chat_panel.py:229-348` | I-2 顶栏按钮图标化落点 |
| `_cmd_popup`（`commandPopup`）/`_mention_popup`（`mentionPopup`） | `chat_panel.py:500-525` | M-4 浮层淡入淡出落点 |
| `_add_message_bubble(...)` 调用点（`_load_session_messages` 历史重载 :1055 vs 实时新增） | `chat_panel.py:1029-1058` | M-2 气泡入场"历史不重播"的判定点 |
| `page_memory_book.tabs`（8 Tab，`addTab` 于 :235/:239/:243/:247/:263/:279/:295/:316） | `page_memory_book.py:182-316` | I-3 Tab 图标统一落点 |
| `page_settings._init_ui` 「外观主题」区（四风格下拉 + 色块 + 外观模式 + 字体 + 强调色盘） | `page_settings.py:105-201` | C-1「外观与效果」区扩点 |
| `PageAbout._THIRD_PARTY_ITEMS`（静态表） | `page_about.py:15-25` | I-5 图标集授权登记位 |
| `GuiConfig` 新键落盘范式（`hasattr` 白名单 + `save()` 列举） | `config.py:113-214` | C-3 新键注册（旧存档零迁移） |
| `qt_compat.py`（集中导入，无动效/毛玻璃/图标相关符号） | `qt_compat.py:1-83` | **需追加**：`QPropertyAnimation`/`QEasingCurve`/`QParallelAnimationGroup`/`QGraphicsOpacityEffect`/`QAbstractNativeEventFilter`/`QPixmapCache` |
| `maid_coder_gui.spec`：`datas`（`gui/themes`→`themes`、`gui/assets/fonts`→`assets/fonts` 等）+ `hiddenimports` | `maid_coder_gui.spec:22-214` | I 组图标资源随包（新增 `('gui/assets/icons','assets/icons')` + `gui.icons`/`gui.motion`/`gui.glass` hiddenimports） |
| `maid_coder_gui_onefile.spec` | 同构 | **须同步**图标 datas + hiddenimports（防重演 v2.0 ⚠-10 onefile 字体缺口类事故） |
| `get_resource_path`（frozen 以 `_MEIPASS` 为基准；源码以 `gui/` 为基准） | `utils.py:12-18` | 图标资源相对路径必须与 `gui/` 下源码路径一致（`assets/icons/...`） |
| `theme_color(app_ctx, key, fallback)` | `utils.py:32-43` | 新控件取色唯一入口（图标着色亦走它） |

### 1.4 v1.9 成果中**必须原样保留**的清单（R-D 硬口径）

| # | 保留项 | 证据 | 本轮态度 |
|---|---|---|---|
| 1 | 四风格 id 与 `THEME_DEFINITIONS` 条目结构 | `theme_engine.py:189-306` | **不动**（S 组只加 QSS 规则，不改 `colors`/`layout` 值） |
| 2 | 四风格核心色值（`--bg/--accent/--radius` 等） | 同上 | **不漂移**（S-1 验收③：与视觉稿一致；无新增裸色） |
| 3 | `LEGACY_THEME_MAP` / `THEME_IDS` / `DEFAULT_THEME_ID` / `normalize_theme_id` | `theme_engine.py:311-423` | **不动** |
| 4 | `dark_locked` / `brand_persona` 元字段与 `apply_night_lock` / `is_dark_effective` | `theme_engine.py:426 / :437 / :999` | **不动**（D-5 深浅过渡不得破坏 C 风格强制深色） |
| 5 | 六字体系统与粉圆 title-only 守卫 | `fonts.py:32-51 / :179-213` | **零改动**（图标字体是**并列新增**，不并入 `FONT_IDS`） |
| 6 | 强调色派生契约（`derive_accent_palette` 覆盖 8 键） | `theme_engine.py:728-773` | **不动**；毛玻璃/图标/动效取色一律走活动色板 |
| 7 | 旧三主题 QSS（cute/minimal/maid）文件 | `gui/themes/` | **保留**（不出现在任何 UI 入口） |
| 8 | `${变量}` 双层渲染机制（base 结构层 + 肤感层） | `theme_engine.py:376-378 / :383-384` | **不动**（S 组新增规则**只允许**引用 `${...}` token） |

---

## 2. 架构决策（D-V21-01 ~ D-V21-14）

> 每条格式：**决策 / 理由 / 被否决的替代方案**。D-V21-03/04（毛玻璃）与 D-V21-01/02（动效）为高危区，全文最细。

### D-V21-01 动效基建 `gui/motion.py`：单点收口 + 档位 + 尊重系统减少动画

**决策**

- **位置**：新模块 `gui/motion.py`（Qt 层模块，直接 `from gui.qt_compat import ...`，与 `fonts.py` 零顶层依赖范式**不需要保持一致**——`fonts.py` 也是 Qt 层模块）。
- **档位常量（唯一真值源）**：

| 常量 | 值 | 说明 |
|---|---|---|
| `LEVELS` | `("off", "soft", "standard")` | M-6 值域 |
| `DEFAULT_LEVEL` | `"standard"` | Q-V2 裁决默认档 |
| `_DURATION_MS` | `{"off": 0, "soft": 130, "standard": 200}` | 档位基准时长；**均 ≤ 220ms** |
| `MAX_DURATION_MS` | `220` | 硬上限（R-P④：动效总时长上限 ≤ 220ms） |

- **API（签名见 §4.2）**：
  - `configure(level) -> None`：启动期（`main.py`，`GuiConfig.load()` 之后）与设置页切换时调用；非法值回落 `DEFAULT_LEVEL`。
  - `level() -> str` / `enabled() -> bool`：`enabled() = level() != "off" and system_animations_enabled()`。
  - `system_animations_enabled() -> bool`：**"prefers-reduced-motion" 的 Windows 等价物**——`user32.SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION=0x1042, 0, byref(BOOL), 0)`（`ctypes`，零依赖）；读不到（非 Windows / 调用失败）→ **返回 `True`**（保守：不误关用户动效）。该函数**纯逻辑可 mock**（M-0 验收③要求"无 `QApplication` 时调用不崩"）。
  - `duration(base_ms: int = 0) -> int`：**单一收口**。`level=="off"` → `0`；否则 `min(base_ms or _DURATION_MS[level], MAX_DURATION_MS)`。**各动效落点禁止硬编码 `setDuration(<常量>)`**（M-0 验收②静态扫描断言）。
  - `easing() -> QEasingCurve`：默认 `OutCubic`（克制；对齐视觉稿 `cubic-bezier(.4,0,.2,1)` 的"快出缓停"家族）。
  - `animate(widget, prop, start, end, *, duration_ms=None, easing=None, on_finished=None) -> Optional[QPropertyAnimation]`：`enabled()==False` → **返回 `None` 且不实例化任何动画对象**（M-1 验收② / M-6 验收：`off` 时断言 `QPropertyAnimation` 未创建）。
  - `fade(widget, *, to=1.0, duration_ms=None, on_finished=None) -> Optional[QPropertyAnimation]`：内部 `QGraphicsOpacityEffect` 便捷封装（若 widget 已有 effect 则复用，不叠加）。
  - `stop_all(final: bool = True) -> None`：把 `_RUNNING` 中所有动画**立即跳到终态**并停止（M-6 验收②："切 `off` 后已在进行中的动画立即收束到终态，不残留半透明/错位"）。
  - `running_count() -> int`：测试用。
- **防 GC（关键）**：`animate()` 内部**双保险**——
  1. `anim = QPropertyAnimation(widget, prop, widget)`（`parent` 设为 widget，Qt 对象树持有）；
  2. 同时加入模块级 `_RUNNING: set`，`finished`/`destroyed` 信号里 `discard`。
  → 既不因 Python 侧无引用被回收，也不永久泄漏（动画结束后从集合移除、随 widget 销毁）。
- **切换档位即时生效**：设置页改档 → 写 `GuiConfig` + `save()` + `motion.configure(level)`；若新档为 `off` → `motion.stop_all(final=True)`（收束进行中动画）。
- **`duration()` 的耦合纪律**：落点调 `animate()` 时**只**传业务基准或留空，不传裸毫秒上限；`duration()` 内统一夹取。
- **循环动效（v2.x 增补 · V21-01 契约扩展）**：以上 API 只覆盖"入场/退场"**一次性过渡**；"进行中"**循环动效**另立类别，经 `loop()` 启动：

| 常量 | 值 | 说明 |
|---|---|---|
| `MIN_LOOP_PERIOD_MS` | `800` | 循环周期下限 |
| `MAX_LOOP_PERIOD_MS` | `1600` | 循环周期上限 |
| `_DEFAULT_LOOP_PERIOD_MS` | `1200` | 未指定周期时的默认值 |

  - **周期 ≠ 时长（关键裁决）**：`MAX_DURATION_MS=220`（R-P④）**仅**约束入场/退场过渡；**循环动效以"周期"计（夹取到 800–1600ms），不计入 220ms 上限**。
  - `loop_period_ms(base_ms=0) -> int`：循环周期**单一收口**；非法 / `≤0` → 默认 `1200`，夹取到 `[800, 1600]`（纯函数可断言）。
  - `loop(owner, on_tick, *, period_ms=None, on_disabled=None) -> Optional[_LoopHandle]`：`enabled()==False` → **不启动、不创建任何定时器、返回 `None`**（落点保持既有静态形态）；否则登记进**独立集合 `_LOOPS`** 并起用模块级驱动器，**每次 tick 回调 `on_tick(progress)`**（`progress ∈ [0,1)`）。
  - `stop_loop(handle) -> None`：停单个循环；**幂等**；从 `_LOOPS` 移除，集合空则停驱动器。
  - `running_loop_count() -> int`：测试用（与一次性动画的 `running_count()` **并列**，互不污染）。
  - **纪律（硬要求）**：① **每次 tick 校验 `enabled()`**，为 `False` → **全部循环立即自停**并回调各自 `on_disabled`（落点切静态形态）——即"**响应式立即停**"，**不新增信号**；② **隐藏即停**（落点 `hideEvent` 必须 `stop_loop`）；③ **`stop_all()` 必须一并停掉全部循环**（退出 / 换肤 / 切 `off` 的统一收口）；④ 循环与一次性动画**分开登记**（`_LOOPS` vs `_RUNNING`）——既有 `_RUNNING` 靠 `finished` 清理，而**循环永不 `finished`**，两条路径不得混用。
  - **顶层零 Qt 对象**：驱动器定时器**惰性创建**（首次 `loop()` 且 `enabled()` 为真时），保证无 `QApplication` 也能安全 `import`。

**理由**

1. **为什么单点收口**：M-0 验收②要求"各动效不得硬编码时长"，静态扫描要能断言无散落 `setDuration(<常量>)`。把档位判定、时长夹取、缓动、开关、系统减少动画、GC 全部塞进一个模块，落点只剩"调用 + 传 widget/prop/起止值"。
2. **为什么尊重系统减少动画**：Windows 有全局"在 Windows 中显示动画"开关（无障碍/性能诉求），与 Web 的 `prefers-reduced-motion` 同义。R-Q 要求"效果可关"，系统级开关是用户既有意图，必须尊重，否则等于绕过用户的关闭动作。
3. **为什么 `SPI_GETCLIENTAREAANIMATION` 而非 `winreg MinAnimate`**：前者是运行时权威值（受"辅助功能→视觉效果"实时影响），后者是注册表镜像（部分版本不一致）；且 `SystemParametersInfoW` 仍是纯 `ctypes`，零依赖。
4. **为什么 `animate()` 返回 `None`（而非返回一个时长为 0 的动画）**：`off` 时必须能断言"未创建动画对象"（M-1 验收②原文），返回 `None` 是最干净的信号；调用方 `if anim is None: 直接设终态` 即可，行为与"无动画"完全一致。

**被否决的替代方案**

- ❌ **每个落点各写 `QPropertyAnimation`**：时长/缓动/开关判定分散，无法单点收口，必然出现"某处动了某处没动"与硬编码时长。
- ❌ **用 QSS `transition` 做过渡**：**Qt Widgets 的 QSS 不支持 `transition`/`animation`**（与 Web 不同，PRD §2.2 技术前提）——此路不通，只能代码侧。
- ❌ **用 `QTimer` 手写插值**：重复造轮子，缓动曲线/生命周期管理全部自己写，且无法复用 Qt 的 `QEasingCurve` 40+ 曲线。
- ❌ **常驻 `QTimer` 轮询系统动画开关**：无必要（读一次 + 设置页切换时刷新即可），且违 R-P（常驻定时器空耗）。

---

### D-V21-02 动效落点与"不重复播放"：切页 / 气泡 / 浮层 / 侧栏（Q-V2 裁决）

**决策**

| 需求 | 落点 | 实现要点 | 关掉动效时（`off`） |
|---|---|---|---|
| **M-1 切页过渡** | `PageManager`/`MainWindow` 的页面切换路径（`page_stack` 换页处） | 切页后对新页 `QGraphicsOpacityEffect` 0→1 淡入（**不滑动整页**，避免 `QSplitter` 布局震荡）；动画结束后**移除 effect**（防长期重绘开销） | 直接 `setCurrentWidget`，不创建 effect/动画；行为同改动前 |
| **M-2 气泡入场** | `chat_panel._add_message_bubble(...)` | 新气泡淡入 + 上移归位（`pos` 或 `maximumHeight` 的短促过渡）；**禁止弹跳** | 直接 `addWidget`，无动画 |
| **M-3 侧栏微交互** | `sidebar.list_widget` 的 hover/选中 | hover/选中用 **QSS 静态态**表达（不叠加代码动画，避免双写冲突）；选中态高亮随四风格主色 | 无变化（QSS 本来就生效） |
| **M-4 浮层出现/消失** | `commandPopup`/`mentionPopup`（`:500/:516`）+ 非模态 `QDialog` | `showEvent` 淡入；`closeEvent` 淡出（延迟真正关闭到动画结束）。**模态 `exec()` 对话框只做淡入**（见下"为什么"） | 直显/直隐 |

- **"历史消息重载不重复播放入场"（M-2 验收②）**：`chat_panel` 增内部标志 `self._loading_history: bool`，在 `_load_session_messages`（`chat_panel.py:1029`）进入时置 `True`、`finally` 复位；`_add_message_bubble(..., animate=None)` 的默认值解析为 `animate if animate is not None else (not self._loading_history)`。→ 切会话/重载历史时**不**逐条播放（避免"滚动时满屏闪动"）。
- **浮层淡出的模态约束**：Qt 模态对话框用 `exec()` 阻塞事件循环，淡出需"动画结束再真关"；在其阻塞语义下延迟关闭会与返回值时序纠缠，且 `QMessageBox` 等多由框架内部 `exec()` 驱动，**不可控**。故口径：**只有非模态浮层（命令/提及弹窗、非模态对话框）做淡入+淡出；模态 `exec()` 对话框只做淡入**。M-4 验收"close() 有淡出"以非模态浮层为准（架构口径，实施期在 PRD 验收表标注适用范围）。

**理由**

1. **为什么切页用淡入而非滑动**：`page_stack` 在 `central_splitter` 内（`main_window.py:107-121`），滑动整页要动 splitter/布局，易在与侧栏固定宽、宠物 overlay（`track_widget=page_stack`）的联动上产生抖动；淡入是"改一个 opacity 属性"，与布局正交，风险最低。
2. **为什么侧栏只用 QSS 静态态**：hover 同时由 QSS 伪态与代码动画控制会产生"双真值源"，颜色会闪、且与四风格 QSS 精修相互覆盖；微交互的"过渡感"由 M-1/M-2 承担足够。**M-3 的"轻微缩放"若强行做会让固定宽侧栏的行高抖动**，故降级为 QSS hover/选中色过渡语义（静态）。
3. **为什么气泡入场要排除历史重载**：否则每次切会话 N 条历史同时入场，既违 R-P（批量动画掉帧），也违"克制"（满屏闪动）。用一个显式"正在重载"标志把"新消息"与"回放历史"分开，是最小改动且可断言。

**被否决的替代方案**

- ❌ **切页滑动整页**：`QSplitter` + 固定宽侧栏 + 宠物 overlay 组合下易抖，且 PRD 明示"非滑动整页，克制"。
- ❌ **气泡逐个 `QTimer` 排队入场**：弱机滚动时排队积压，违 R-P；且"历史不重播"已从根本上消除了批量入场。
- ❌ **模态对话框也做淡出**：`exec()` 阻塞语义下无法安全延迟关闭（见上）。
- ❌ **在 `paintEvent` 里手绘透明度**：侵入组件绘制、与既有 `QGraphicsDropShadowEffect`（`chat_window.py:106`）冲突。

---

### D-V21-03 毛玻璃零依赖实现：`ctypes` 直调 Windows DWM + 能力探测 + fail-safe

**决策**

- **位置**：新模块 `gui/glass.py`（**纯标准库 + `ctypes`**，无第三方）。
- **DWM 常量与调用**（`ctypes.windll.dwmapi` / `ctypes.windll.user32`，全部 `try/except` 包裹）：

```python
# 能力判定（纯逻辑，可 mock sys.getwindowsversion().build / is_remote_session）
DWMWA_USE_IMMERSIVE_DARK_MODE = 20     # Win10 1903+ / Win11：深浅联动
DWMWA_SYSTEMBACKDROP_TYPE     = 38     # Win11 22H2+（build >= 22621）
DWMWA_MICA_EFFECT             = 1029   # Win11 21H2（build 22000..22620）私有 Mica 开关
DWMSBT_AUTO            = 0
DWMSBT_NONE            = 1
DWMSBT_MAINWINDOW      = 2   # Mica  —— 主窗
DWMSBT_TRANSIENTWINDOW = 3   # Acrylic —— 浮层/对话框
DWMSBT_TABBEDWINDOW    = 4   # Mica Alt（备用，本轮不用）
SM_REMOTESESSION       = 0x1000
```

- **能力探测** `detect_capability() -> GlassCapability`（`dataclass(frozen=True)`：`supported: bool` / `kind: "mica"|"acrylic"|"none"` / `build: int` / `reason: str`）：

```
if os.name != "nt":                                     → none  ("非 Windows")
if is_remote_session():                                 → none  ("远程桌面：DWM 材质不可靠，降级纯色")
build = sys.getwindowsversion().build
if build >= 22621:  → mica（可 Mica + Acrylic，attr=38）
elif build >= 22000:→ mica（仅 Mica，attr=1029；Acrylic 不可用）
else:               → none  （Win10 及更旧：按 Q-V3 裁决降级纯色）
```

- **API（签名见 §4.3）**：`is_supported() -> bool`（探测的布尔投影，纯逻辑可 mock）；`apply_main_window(hwnd, *, dark: bool) -> bool`；`apply_dialog(hwnd, *, dark: bool) -> bool`；`remove(hwnd) -> bool`；`is_remote_session() -> bool`；`safe_apply(hwnd, kind, *, dark) -> bool`。
- **fail-safe 铁律**：**任何一步失败（`winId()` 为 0 / `hwindll` 调用抛错 / 属性设不上）→ 返回 `False`，调用方保持纯色 `${bg}`**。`glass.py` 顶层不 `import` 任何可能抛错的平台模块（`ctypes.windll` 只在函数内访问，非 Windows 下 `os.name` 早退）。
- **深浅联动**：`dark=True` → 同时设 `DWMWA_USE_IMMERSIVE_DARK_MODE=1`（材质走深色调）；`dark=False` → 设 0。`theme_changed` 时重新 `safe_apply`（D-4：深色×毛玻璃适配）。
- **重新应用时机**：窗口 `showEvent` 后（HWND 才有效）、`theme_changed` 后、设置开关切换后、以及 `WindowStateChange`（最小化还原/重显）后（部分 Windows 版本重显会丢材质）。

**理由**

1. **为什么零依赖可用**：`dwmapi.DwmSetWindowAttribute` 与 `user32.SystemParametersInfoW` 都是系统 DLL 的稳定导出，`ctypes` 是标准库；项目已有 `winreg`（`theme_engine.py:30`）这一"Windows 原生能力封装"先例，范式同构、风险可控。
2. **为什么主窗用 `DWMSBT_MAINWINDOW`（Mica）而非旧 `DwmExtendFrameIntoClientArea`**：旧法是 Win10 时代的"边框延伸"技巧，需要 `WA_TranslucentBackground` + 负边距，与 Qt 控件背景易打架；Win11 的**系统背景材质**（`DWMWA_SYSTEMBACKDROP_TYPE`）是官方路径，DWM 自己处理壁纸采样与模糊，Qt 侧只需"根窗口背景透明"。
3. **为什么 Win10 降级纯色（Q-V3 裁决）**：Win10 无系统背景材质，只能走 `SetWindowCompositionAttribute` Acrylic 的"自绘模糊"路径——该路径在窗口拖动时是已知的卡顿源（违 R-P③），且需要强制 `WA_TranslucentBackground`（与既有透明窗口 `chat_window.py:61` 等叠加）。为保"不卡顿 + 不黑窗"，**Win10 一律纯色**，比"能糊但拖卡"更符合 R-P 与 R-R（诚实）。
4. **为什么必须 fail-safe**：PRD §7.2/§9.3 主张 2——毛玻璃在非 Win11/远程桌面出错若崩或黑窗，等于"软件坏了"；fail-safe + 自动降级是唯一可接受的失败模式。

**被否决的替代方案**

- ❌ **`QStyleHelper`（第三方）**：触碰 R-F（Q-V1 已否决）。
- ❌ **Win10 也上 Acrylic（`SetWindowCompositionAttribute`）**：拖动卡顿 + 强制半透明背景，与 R-P/既有透明窗口冲突；且 Q-V3 已裁"Win10 降级纯色"。
- ❌ **`QWGraphicsBlurEffect` 模拟毛玻璃**：只能模糊"自己画的内容"，无法透出桌面壁纸，视觉上不是真毛玻璃；且开销大。
- ❌ **自绘截图模糊（截桌面→高斯模糊→贴背景）**：开销极高、窗口移动即失效、违 R-P。

---

### D-V21-04 毛玻璃适用面与"根窗口透明"协同：主窗 Mica + 顶层对话框 Acrylic

**决策**

| 面 | 处理 | 说明 |
|---|---|---|
| **主窗（Mica）** | `MainWindow` 顶层应用 Mica；**根窗口与中心容器背景透明**，卡片/气泡保留各自 `${bg_card}` 等不透明白底 | 材质透出发生在"页面留白/间隙"处，卡片仍是实心 → 内容可读性不受材质影响 |
| **顶层对话框（Acrylic）** | 仅对**顶层 `QDialog` 子类**（如 `chat_window.py` 浮动聊天窗、各类 `*Dialog`）应用 `DWMSBT_TRANSIENTWINDOW` | 见下"为什么不用子控件" |
| **侧栏 / 卡片 / 子面板** | **不**直接套 DWM 材质；改用 **QSS 半透明叠在主窗 Mica 之上**（`rgba` 或透明背景） | 侧栏是 `central_splitter` 的子控件，非顶层窗口 |
| **Win10 / 远程桌面 / 探测失败** | 全部纯色 `${bg}` | 见 D-V21-03 |
| **协议（与 QSS 协同）** | 玻璃开时，给 `MainWindow` 设动态属性 `glass="on"` → `base.qss` 条件规则 `QMainWindow[glass="on"], QMainWindow[glass="on"] > QWidget { background: transparent; }`；改属性后**必须** `style().unpolish(this); style().polish(this)` 重刷 | 关玻璃时移除属性 → 恢复原背景，**行为与改动前一致**（R-Q③） |

- **"为什么不用子控件（侧栏）套 Acrylic"**：DWM 材质作用于**窗口句柄（HWND）**；要给子控件上材质须先 `WA_NativeWindow` 提升为原生窗口，这会造成：
  1. 侧栏与父窗口的原生子窗口裁剪/重绘撕裂；
  2. 与既有 `QSplitter` + 宠物 overlay 的命中测试冲突；
  3. 在不同 DPI/多显示器下句柄重建（`winId()` 变化）需反复重挂，极脆。
  → 因此**侧栏透明化叠加主窗 Mica** 达到"侧栏透出材质"的等效观感，且零原生窗口副作用。这是对 PRD G-2"侧栏 Acrylic"的**稳健化落地**（保留观感，去掉脆弱路径）。

**理由**：①主窗 Mica 是 Q-V3 点名必做；②浮层 Acrylic 限定顶层窗口，是 DWM 材质唯一稳定作用面；③侧栏/卡片走 QSS 透明 + 主窗材质，既满足"不铺满所有面板"的克制口径，又避免原生子窗口陷阱；④动态属性驱动 QSS 是"代码控制外观、QSS 只读属性"的干净边界（呼应 D-V21-08）。

**被否决的替代方案**

- ❌ **全窗口 `WA_TranslucentBackground` 通铺**：会让所有子控件透出、文字压壁纸不可读（违 G-4 对比度），且与既有透明窗口实现叠加发灰。
- ❌ **给侧栏/卡片 `WA_NativeWindow` 后逐个套 DWM**：见上四类风险，维护性极差。
- ❌ **为毛玻璃单独写一套 QSS**：会分叉四风格 token 体系（违 R-D）；用**属性条件规则**叠加在既有 QSS 之上，零分叉。

---

### D-V21-05 毛玻璃 × 窗口透明度滑杆互斥（Q-V8 裁决）

**决策**

- `GuiConfig.window_opacity`（`main_window.py:82 setWindowOpacity`）**保持不变**（不覆盖用户值）；新增运行时逻辑：
  - **玻璃开 + 支持** → `setWindowOpacity(1.0)` + 设置页透明度滑杆 `setEnabled(False)` + 提示"毛玻璃开启时窗口透明度固定 100%（两者互斥）"。
  - **玻璃关 / 不支持 / 降级** → 恢复 `setWindowOpacity(cfg.window_opacity)` + 滑杆 `setEnabled(True)`（行为与改动前**完全一致**）。
- 单一收口：`MainWindow._apply_glass_state()`（同时处理 DWM 应用、根属性、透明度互斥、状态栏/滑杆联动）；设置页只调它 + `save()`。
- 不改 `page_settings.py:1785/:1978` 既有滑杆链路，只在"外观与效果"区新增一个**提示 QLabel + 启用/禁用联动**。

**理由**：透明度（`setWindowOpacity`）作用于整个窗口表面，与 Mica/Acrylic 叠加会出现"半透明壁纸 + 半透明窗口"的双重透明 → 整窗发灰、文字发虚（PRD F-9 / Q-V8 的原始问题）。互斥是最简洁、可断言（滑杆 `isEnabled()==False`）的口径。

**被否决的替代方案**：❌"联动缩放"（透明度映射到材质不透明度）——材质不透明度不由我们控制，映射语义模糊；❌"允许叠加只给提示"——仍会出现发灰，用户会报"毛玻璃坏了"。

---

### D-V21-06 图标体系 `gui/icons.py`：图标字体 + 双用法统一 API + emoji 回退链

**决策**

- **位置**：新模块 `gui/icons.py`（Qt 层；复用 `fonts.py` 的"注册真实 family + 家族链 + 缺文件静默回退"范式）。
- **资源**：`gui/assets/icons/`（`maling_icons.ttf` 图标字体子集 + `icons_manifest.json` 名称→码位映射 + 该图标集的 `LICENSE`）。
- **单一收口 API**（§4.4）：

| 函数 | 语义 |
|---|---|
| `register_icon_font() -> Optional[str]` | `QFontDatabase.addApplicationFont`；用 `applicationFontFamilies` 取**真实 family**（不凭文件名猜，同 `fonts.py:152`）；失败返回 `None` 不抛 |
| `available() -> bool` | 字体已注册且 manifest 加载成功 |
| `has(name) -> bool` / `glyph(name) -> Optional[str]` | 名称→字形字符（`chr(codepoint)`）；未知名返回 `None` |
| **`icon(name, size=16, color=None) -> QIcon`** | **主 API**：`QPainter` 把字形画进 `QPixmap`（`setDevicePixelRatio` 适配高 DPI，M-P：矢量图标天然支持缩放）→ `QIcon`；`color=None` 时取活动色板 `text`（`theme_color`）；结果进 `QPixmapCache`（键 = `name|size|color|theme`）|
| `font(size=16) -> QFont` | **次 API**：需要"把图标当文本嵌入"时（`QLabel` 等）返回设好 family/pixelSize 的 `QFont`，颜色由控件的 QSS `color` 控制 |
| `text_glyph(name, fallback) -> str` | **文本流便捷入口**：`available()` 且 `has(name)` → `glyph(name)`（字形字符），否则原样返回 `fallback`（调用方约定传原 emoji，**不得删 emoji 字面量**）；颜色由控件 QSS 控（§4.4.1） |
| `configure(app_ctx) -> None` | 启动期注入 `app_ctx` 以便 `icon()` 取活动色板；订阅 `theme_changed` → 清缓存（换肤/深浅切换后图标重新按新色渲染） |
| `clear_cache() -> None` | 清 `QPixmapCache` 中图标键（测试/换肤用）|

- **两套用法统一**：落点只记 **图标名 + 尺寸**；需要 `QIcon` 的（`QListWidgetItem`/`QPushButton.setIcon`）走 `icons.icon(...)`；需要"文本流内嵌"的走 `icons.font(...)` + 字形文本。**禁止落点自己拼 `chr()` 或硬编码 family/颜色。**
- **旧 emoji 平滑替换与回退**：`SidebarWidget.NAV_ITEMS` 由 3 元组改 **4 元组** `(key, label, icon_name_or_None, fallback_text)`：

```python
NAV_ITEMS = [
    ("chat",        "聊天",     "chat",         "\U0001F4AC"),  # 💬
    ("home",        "首页",     "home",         "\u2302"),      # ⌂
    ("memories",    "回忆",     "auto_awesome", "\u2728"),      # ✨
    ("memory_book", "记忆中心", "menu_book",    "\U0001F4D4"),  # 📔
    ("project",     "项目",     None,           "\U0001F4C1"),  # 📁（沿用文件夹图标降级）
    ("file",        "文件",     "edit",         "\u270E"),      # ✎
    ("plan",        "计划",     "list",         "\u2630"),      # ☰
    ("agent",       "角色",     "person",       "\u263A"),      # ☺
    ("tools",       "工具",     "settings",     "\u2699"),      # ⚙
    ("settings",    "设置",     "tune",         "\u2691"),      # ⚑
]
```

  侧栏构建逻辑：`icons.available() and not icons.icon(name).isNull()` → `QListWidgetItem(icon, label)`；否则 → `QListWidgetItem(f"{fallback_text}  {label}")`（与现状行为一致，**不空白、不崩**）。`"project"` 项 `icon_name=None` 时回落到 `QIcon.fromTheme("folder")` → emoji（沿用现状降级链）。
- **状态/着色（I-4）**：正常态取 `text`；选中/hover 由 QSS `color` 与列表项伪态表达（图标为 `QIcon` 时需按态重渲染 → 提供 `icon(name, size, color)` 显式传色，落点在态切换时用 `theme_color` 取 `accent`/`focus_accent`）。禁用态用 `disabled_text`。
- **本设计不改 `fonts.py` 的字体集**：图标字体与界面字体是两套资源、两套常量，**并列存在**（图标码位**不并入** `FONT_IDS`，避免 UI 字体下拉被污染）。唯一例外：`font_family_chain` 在**通用族 `sans-serif` 之前**插入图标回退族（族名取 `gui.icons.FONT_FAMILY_NAME`，惰性 import）—— 使文案流里的 PUA 字形（`text_glyph` 产物）能随控件字体链渲染而不糊（§4.4.2）；该插入经既有「去重保序」逻辑约束，不重复、不排 generic 之后，其余降级路径行为不变。

**理由**：①图标字体单文件、体积小、可**按需着色**（`QPainter` 画笔色），与 v1.9 字体随包范式同构且已验证；②矢量渲染天然支持高 DPI（优于 emoji 文本在不同 DPI 下的字形差异）；③emoji 回退链保证"缺字体/未注册"时导航仍可用（R-K/R-Q 精神）。

**被否决的替代方案**

- ❌ **qtawesome 运行时集成**：触碰 R-F（Q-V1 已否决）。
- ❌ **纯 `QtSvg` 渲染随包 SVG**：可行但每个图标一个文件（10+ 个导航 + 顶栏/状态栏数十个），体积与查找成本高于单字体；且多色图标才是 `QtSvg` 的必要场景，本轮以单色为主 → **`QtSvg` 仅作多色补充**（Q-V4）。
- ❌ **构建期导出 PNG 随包**：高 DPI 下需多倍图、无法按需着色，体积膨胀。
- ❌ **保留 emoji 文本不换**：PRD I-1 明确要求替换；且 emoji 在四风格下颜色不可控（着色随"风格主色"无法实现）。

---

### D-V21-07 图标构建期链路：`tools/build_icons.py` + qtawesome 退守构建期 + 随包

**决策**

- **新 `tools/build_icons.py`（仅构建期，不入运行时、不进 exe）**，与 v1.9 `tools/build_fonts.py`（`fonttools` 构建期）同构：
  1. 取官方图标集 TTF（**OFL / Apache-2.0 且允许随包商用**，Q-V5 建议 Material Symbols 或 Remix Icon）；
  2. 用 `pyftsubset`（`fonttools`）**子集化**为 `maling_icons.ttf`（只留用到的字形，体积压到数十 KB）；
  3. 生成 `icons_manifest.json`（`{"<name>": <codepoint>, ...}`，名称用语义名如 `chat`/`settings`，**不直接暴露码位**）；
  4. 落 `gui/assets/icons/`（子集 TTF + manifest + 图标集 `LICENSE` 副本）；源树许可副本另落 `docs/third_party_licenses/`。
- **qtawesome 的角色（Q-V1 裁决）**：**仅构建期可选工具**——用于**校验**码位映射（对照 `qtawesome` 的 icon→codepoint 表）与辅助挑选图标名；**不写入 `requirements*.txt`、不进 exe**。构建脚本头部注释写明"`pip install qtawesome fonttools`（构建期临时安装）"。
- **随包（参照 v1.9 ⚠-2 路径纪律）**：spec `datas += ('gui/assets/icons', 'assets/icons')`；`hiddenimports += 'gui.icons'`；两个 spec 同步。`get_resource_path("assets/icons/...")` 在 frozen（`_MEIPASS`）与源码（`gui/`）两态路径一致。
- **缺资源优雅回退**：`register_icon_font()` 失败 → `available()==False` → 全部落点走 emoji 回退（= 现状），不崩、不空白。

**理由**：①子集化把"整套图标集（数百 KB~MB）"压到"实际用到的几十个字形（数十 KB）"，体积可控（R-P / 打包体积）；②qtawesome 只在构建机出现，运行时零依赖（R-F）；③许可副本随包 + 源树双份，满足 I-5 / R-R②。

**被否决的替代方案**：❌ 直接把整套图标字体随包（体积大、且码位映射需运行时解析）；❌ 运行时用 qtawesome 动态取图标（触碰 R-F）；❌ 自绘 SVG path（工作量与维护成本高，且着色/DPI 处理重复造轮子）。

---

### D-V21-08 QSS 与代码的职责边界（Qt QSS 无 transition）

**决策**——明确三档职责，落点不得越界：

| 效果类别 | 归属 | 具体 |
|---|---|---|
| **只能 QSS（静态）** | **QSS** | 颜色 / 圆角 / 描边 / 间距 / 阴影 token / `qlineargradient` 渐变 / **伪态**（`:hover`/`:pressed`/`:focus`/`:disabled`/`:checked`）/ 深浅两套配色 |
| **必须代码（动态）** | **代码侧** | **一切过渡/入场/微交互**（S 组无 transition，M 组全代码）；**毛玻璃**（DWM API）；**图标渲染**（`QIcon`/`QFont`） |
| **协同（两侧联动）** | QSS 读属性 / 代码写属性 | 毛玻璃开 → 代码设 `MainWindow[glass="on"]` 动态属性 → QSS 条件规则让根透明（D-V21-04）；**代码不直接 `setStyleSheet` 覆盖四风格**，只动"少量动态属性或既有 `theme_color` 取色" |

- **纪律**：S 组新增 QSS 规则**只允许**引用已注册的 `${...}` token（颜色 + layout），**禁止新增裸色 `#RRGGBB`**（S-1 验收③静态扫描断言）；M/G/I 组**不写 QSS 过渡声明**（Qt 不支持，写了无效且误导后来者 → 共享知识 §6 重申）。

**理由**：PRD §2.2 + §7.4 R4——"Qt QSS 无 transition"是本轮最大认知陷阱；把边界写成表格，避免实施者把动效写进 QSS 白费功夫，也避免把静态配色写进代码导致四风格分叉（违 R-D）。

**被否决的替代方案**：❌ 用 `QWidget.setStyleSheet` 在代码里拼动态样式做过渡——每帧重设样式表开销极大、且绕过四风格 token。

---

### D-V21-09 三维组合一致性策略（4 风格 × 浅/深 × 毛玻璃 → 正交化，避免爆炸）

**决策**——**把"动效开关""毛玻璃开关"降为正交开关，不参与配色设计**：

| 维度 | 是否影响配色 | 一致性策略 |
|---|---|---|
| 四风格（4） | **是** | v1.9 既有 4 套 `colors`（S 组只精修 QSS 规则，不动色值） |
| 浅/深（2） | **是** | v1.9 既有 `_DARK_OVERRIDES` 四风格深色变体（**PM 已复核定稿**）；D-1 只审计达标性 |
| **动效开关（off/soft/standard）** | **否** | 只影响"有没有动画"；**终态视觉完全一致** → 不进配色矩阵；只验"`off` 时无动画对象 + 终态与 standard 相同" |
| **毛玻璃开关（开/关）** | **否（正交）** | 毛玻璃只替换**最底层窗口背景源**（`${bg}` → DWM 材质），**不替换**卡片/气泡表面；文字/边框/强调色仍由活动色板决定 → 一致性 = "对比度不达标才算问题"（G-4/D-4 自动计算断言） |

- **因此配色组合只需覆盖 `4 风格 × 2 深浅 = 8` 个基色板**（v1.9 已存在），毛玻璃是"背景源切换"，不新增配色条目 —— 这是"避免 4×2×2 组合爆炸"的核心。
- **回归抽样矩阵（§7）**：8 基色板全测（每风格浅深各一页基准）；毛玻璃**只在 Win11 真机抽 2 风格**（`ui_minimal` 浅 + `ui_night` 深）验证材质与对比度；动效三档只验"提/降档后的终态一致 + `off` 无动画对象"。
- **深浅过渡动效（D-5）**：归 M 组同源开关；`ui_night`（`dark_locked`）强制深色行为**不变**（`apply_night_lock` 零改动）；关闭动效后"秒切不闪白"（靠"先改 QSS 再切 identity，不做 opacity 过渡"实现）。

**理由**：PRD R5 明确"4×2×效果 组合回归量大"；把效果开关与配色解耦，是用"正交化"把矩形面积降为两条线。也让"关掉效果后行为与改动前完全一致"（R-Q）成为**结构保证**而非事后验证。

**被否决的替代方案**：❌ 为"毛玻璃开/关"各出一套配色（16 套维护地狱，且违 R-D 不改色值）。

---

### D-V21-10 设置项落点与即时生效（C 组 + M-6 + G-3）

**决策**

- **新 `GuiConfig` 键（5 个，沿用 v2.0 `hasattr` 白名单范式，旧存档零迁移）**：

| 键 | 值域 | 默认 | 归属 |
|---|---|---|---|
| `animation_level` | `off` / `soft` / `standard` | `standard` | M-6（Q-V2） |
| `glass_enabled` | bool | `True` | G-3（Q-V3） |
| `glass_popups_enabled` | bool | `True` | G-2 浮层 Acrylic 可选开关 |
| `power_save_mode` | bool | `False` | C-2 省电模式（一键关动效+毛玻璃） |
| `animation_level_pre_power_save` / `glass_enabled_pre_power_save` | str / bool | `standard` / `True` | C-2 进入省电前的快照（退出省电可恢复） |

- **即时生效路径（无需重启，C-3 验收③）**：

```
设置页改动 → 写 GuiConfig 字段 → cfg.save() → 调即时生效回调：
  · 动效档变化  → motion.configure(level)（若 → off，额外 motion.stop_all(final=True)）
  · 毛玻璃开关  → window._apply_glass_state()（DWM apply/remove + 根属性 + 透明度互斥）
  · 省电模式    → 快照两键 → 置 animation_level="off" + glass_enabled=False → 两项即时生效 → save()
```

- **「外观与效果」区（C-1/C-4）**：`page_settings.py` 的「外观主题」区（`:105-201`）**扩展**为「外观与效果」，在既有四风格下拉/色块/外观模式/字体/强调色盘**之后追加**：动效强度下拉 + 毛玻璃开关 + 省电模式按钮，每项配一句自然语言说明（可发现性）；分区顺序维持"外观 → 效果 → 行为 → 数据"直觉。**R-A：新设置项文案禁"性能评分/落后/卡顿"等焦虑/评判语义。**
- **默认值回退**：非法 `animation_level` → `standard`；缺键 → 类默认（零迁移）。启动时 `main.py` 在 `GuiConfig.load()` 后 `motion.configure(cfg.animation_level)`。

**理由**：①复用既有 `_create_section` + `cfg.save()`（`page_settings.py:691 / :1730`），零新机制；②快照键让"省电模式"可逆（C-2 验收③"用户可随时关闭省电模式恢复"）；③即时生效走"写配置 + 调回调"，与 v1.9 字体切换（`cfg.save()` + `load_theme`）同构。

**被否决的替代方案**：❌ 不存快照、退出省电一律回 `standard`（会丢掉用户选的 `soft`）；❌ 新建设置存储（偏离 `gui_config.json` 单一配置域）；❌ 用全局模块常量硬编码默认档（无法持久化）。

---

### D-V21-11 暗色跟随系统实时性（D-3）：原生事件监听优先 + 回落缩短轮询

**决策**

- **首选：原生事件监听**。新增 `QAbstractNativeEventFilter` 子类（`theme_engine.py` 内私有实现，或紧邻的轻量模块），安装到 `QApplication`；拦截：

| 消息 | 值 | 含义 |
|---|---|---|
| `WM_SETTINGCHANGE` | `0x001A` | 系统设置变化（含主题/个性化） |
| `WM_THEMECHANGED` | `0x031A` | 主题切换 |
| `WM_DWMCOLORIZATIONCOLORCHANGED` | `0x0320` | DWM 颜色变化 |

  命中任一 → **去抖**（`QTimer.singleShot(300ms)`，避免一次改动触发多次）→ 调既有 `_poll_system_mode()`（`theme_engine.py:561`，**不动其实现**）。
- **回落：缩短轮询**。若原生过滤器安装失败 / 平台不支持 → `_start_system_poll` 的间隔从 **5min 缩短至 30s**（D-3 建议区间 30–60s 取 30s）。**`_system_poll` 的启停语义与 `set_theme_mode` 签名零变更**。
- **安装/卸载时机**：`set_theme_mode("system")` 时安装监听 + 启动轮询；切回 `light`/`dark` 时卸载监听 + 停轮询。**`set_theme_mode` 签名与语义零变更**（R-D）。
- **上限与不破坏**：`light`/`dark` 固定模式不受影响（不安装监听、不轮询）；`ui_night` 强制深色（`dark_locked`）不受影响（`apply_night_lock` 零改动）。

**理由**：PRD D-3 验收①要求"系统深浅变化后 ≤30s 内跟随"；事件监听做到**即时**（验收上限之外更优），零轮询开销（R-P②）；无法可靠监听时缩短轮询兜底。原生事件过滤器是 PySide6 标准能力（`QAbstractNativeEventFilter`），零依赖。

**被否决的替代方案**：❌ 只缩短轮询（即使 30s 仍有延迟与常驻开销）；❌ 常驻 1s 高频轮询（违 R-P）；❌ 依赖第三方库监听 Windows 消息（触碰 R-F）。

---

### D-V21-12 主题引擎与字体系统契约保留（R-D 论证表）

| 契约 | 状态 | 本轮说明 |
|---|---|---|
| `theme_changed(str)` 信号 | **零变更** | 毛玻璃重应用、图标缓存清空**作为新订户**，签名不动 |
| `load_theme` 变量替换流程 / `${...}` 语法 | **零变更** | 仅**新增 QSS 规则**（引用既有 token）；不新增替换键（`${font_title}` 已在 v1.9） |
| `_active_palette` / `_custom_accent` / `derive_accent_palette` | **零变更** | 动效/图标/毛玻璃取色一律走它 |
| `set_theme_mode(mode)` 语义 | **零变更** | D-3 事件监听在其内装卸，不改其对外语义 |
| `is_dark_effective` / `apply_night_lock` / `is_dark_locked` / `is_brand_persona` | **零变更** | D-5 深浅过渡不得破坏 |
| `get_color` / `get_layout_token` / `current_theme_name` | **零变更** | — |
| `THEME_DEFINITIONS` 四风格 `colors/layout` 值 | **零变更** | S 组只精修 QSS；D-1 只在"不达标"时最小修正（须留档） |
| `_DARK_OVERRIDES` / `_SEMANTIC_*` | **零变更**（除非 S 组确需新语义键，则**只增不改**并同步浅/深两套） | — |
| `gui/fonts.py` 全部 | **零变更** | 图标字体并列新增，不并入 `FONT_IDS` |
| 旧三主题 QSS（cute/minimal/maid） | **保留** | 不出现在 UI 入口 |

→ 结论：v2.1 是 `theme_engine` 的**增量订阅者 + 一个新增事件监听装卸**，是 `fonts.py` 的**零改动**，是 QSS 的**加规则**——**非重构**。

---

### D-V21-13 性能验收口径（R-P / Q-V6 可测量化）

**决策**——三条硬口径 + 测量方法（真机留档）：

| 项 | 阈值 | 测量方法 |
|---|---|---|
| 冷启动耗时 | 增幅 **≤ 5%** | `time.perf_counter()` 从进程启动到 `window.show()` 返回；**改动前 v2.0 基线 vs 改动后 v2.1 各 5 次取中位数**；因 Q-V10（无启动动画）+ 毛玻璃在 `show()` 后应用，预期增量接近 0 |
| 常驻内存 | 增幅 **≤ 20MB** | 启动后静置 60s 读 `psutil.Process().memory_info().rss`，5 次中位数对比；图标 `QPixmapCache` 设上限，避免无界增长 |
| 窗口拖动 | **无肉眼可感卡顿** | Win11 真机录屏拖动 5s + 任务管理器抽样 CPU；平均 CPU **≤ 基线 +10%**；顺带验 Win10/远程桌面降级态拖动无异常 |
| 动效时长 | **单次 ≤ 220ms** | `motion.duration()` 纯函数断言（默认档 200 / soft 130 / off 0；任意入参夹取 ≤220） |
| 切页响应 | 切页调用返回 **< 16ms** | 动画异步执行，`setCurrentWidget` 立即返回；断言不阻塞主线程 |
| 效果未生效不卡启动 | — | `glass`/`icons` 全部失败路径返回 `False`/`None`，不重试、不阻塞 |

**理由**：PRD §7.1 与 Q-V6 要求"不明显增加"须量化；上述是可复现、可留档的测法（对比法消除机器差异）。

**被否决的替代方案**：❌ 只用"目测不卡"（不可回归）；❌ 绝对耗时阈值（不同机器差异大）。

---

### D-V21-14 图标授权合规（I-5 / R-R②，扩 R-K/R-L 精神）

**决策**

- 图标集**只选** OFL / Apache-2.0 / MIT / CC0 且**允许随包商用**者（Q-V5：Material Symbols 或 Remix Icon，均为 Apache-2.0）；**GPL 系一律排除**。
- **四处登记**：①`docs/THIRD_PARTY.md` 新增图标集条目（项目/仓库/commit/许可/版权行/入库文件/改动摘要/复核日期/复核人）；②`docs/third_party_licenses/` 放许可全文副本；③`gui/assets/icons/LICENSE` 随包；④`page_about.py` `_THIRD_PARTY_ITEMS` 追加一行（图标集名 / 许可 / 来源 / 用途）。
- **子集属"修改"**：沿用原许可、保留版权声明；若图标集有保留名/署名要求，按原文处理并留档（同 v1.9 字体 R-L③）。
- **诚实口径（R-R③）**：README/CHANGELOG **不自评分、不夸大**；毛玻璃"仅 Win11 支持、Win10 及远程桌面降级纯色"须**如实标注**；不能把"源码态可运行"写成"dist 产物已验证"（须 dist 逐项核对）。

**被否决的替代方案**：❌ 使用许可不明/NC 图标集；❌ 不登记（违 R-R）。

---

## 3. 文件清单

### 3.1 新增

| 文件 | 职责 | 依赖 | 红线 |
|---|---|---|---|
| `gui/motion.py` | 动效助手：档位/时长/缓动/开关/系统减少动画/动画生命周期（GC 保护）/`stop_all` | 仅 `gui.qt_compat` + `ctypes` + 标准库 | R-F；R-P（≤220ms）；R-Q（可关） |
| `gui/glass.py` | 毛玻璃：能力探测 / `ctypes` DWM Mica+Acrylic / 远程桌面判定 / fail-safe | 仅 `ctypes` + `os/sys` 标准库 | R-F；R-P（拖动）；R-Q（可关+自动降级） |
| `gui/icons.py` | 图标：注册 / manifest / `icon()` / `font()` / 缓存 / 活动色板着色 | `gui.qt_compat` + `gui.utils.theme_color` | R-F；I-5 授权 |
| `gui/assets/icons/maling_icons.ttf` | 图标字体子集（构建期生成） | — | I-5 |
| `gui/assets/icons/icons_manifest.json` | 名称→码位映射 | — | — |
| `gui/assets/icons/LICENSE` | 图标集许可副本（随包） | — | R-R② |
| `tools/build_icons.py` | 构建期图标字体子集化 + manifest 生成 + 许可落盘 | `fonttools`/`brotli`（构建期）；`qtawesome`（构建期可选校验） | R-F（仅构建期） |
| `docs/third_party_licenses/<iconset>.txt` | 图标集许可全文（源树） | — | R-R② |
| `tests/test_v21_motion.py` | 动效纯函数/档位/系统动画读取/无 Qt 不崩 | — | — |
| `tests/test_v21_glass.py` | 能力探测（mock build/远程桌面）/ fail-safe / 常量 | — | — |
| `tests/test_v21_icons.py` | 图标名映射/回退链/缓存/无字体不崩 | — | — |
| `tests/test_v21_settings.py` | 新键默认/回退/零迁移/省电快照 | — | — |

### 3.2 修改

| 文件 | 改动 | 红线注意 |
|---|---|---|
| `gui/qt_compat.py` | **追加**（纯增，零删改）：`QPropertyAnimation`/`QEasingCurve`/`QParallelAnimationGroup`/`QGraphicsOpacityEffect`/`QAbstractNativeEventFilter`/`QPixmapCache` 导入 + `__all__` | R-D：既有导出零改动 |
| `gui/config.py` | +5 新键（`animation_level`/`glass_enabled`/`glass_popups_enabled`/`power_save_mode`/两 `_pre_power_save` 快照键）；`__init__` + `save()` 列举同步 | 既有键零改动 |
| `gui/theme_engine.py` | **仅**新增：原生事件监听安装/卸载（`set_theme_mode` 内装卸）+ 去抖转调既有 `_poll_system_mode` + 轮询间隔 5min→30s 回落 | **契约零变更**（D-V21-12 表）；`_DARK_OVERRIDES` 除非 D-1 不达标否则不改 |
| `gui/main.py` | **仅外观段**：`GuiConfig.load()` 后 `motion.configure(...)`；字体注册处并列 `icons.register_icon_font()`；`window.show()` 后 `window._apply_glass_state()` | **更新编排段（:1617-1625）零变更**；`_quit_stop_services` 零变更 |
| `gui/main_window.py` | `_apply_glass_state()`（DWM + 根属性 + 透明度互斥）；窗口 `showEvent`/`changeEvent` 重应用；状态栏三 `QLabel` 图标化（I-3）；切页过渡挂点（M-1） | `theme_changed` 订户追加，签名不变；`_setup_*` 序不改 |
| `gui/widgets/sidebar.py` | `NAV_ITEMS` 改 4 元组；图标构建 + emoji 回退链；`theme_changed` 清图标缓存 | 导航 key/label 与信号零变更 |
| `gui/widgets/chat_panel.py` | 顶栏按钮图标化（I-2）；`_add_message_bubble` 增 `animate` 参数 + `_loading_history` 标志（M-2）；命令/提及弹窗淡入淡出（M-4） | 发送/流式/会话逻辑零改动 |
| `gui/widgets/message_bubble.py` | 气泡入场配合（若在气泡内部实现淡入/位移动画） | 既有 `QGraphicsDropShadowEffect` 不冲突 |
| `gui/widgets/chat_window.py` | 浮动窗 Acrylic（顶层 QDialog，M-4/G-2） | 既有 `WA_TranslucentBackground` 需与 Acrylic 协调（见 §9 风险） |
| `gui/pages/page_settings.py` | 「外观主题」扩为「外观与效果」：动效强度 + 毛玻璃开关 + 省电模式 + 说明文案；透明度滑杆互斥联动 | 四风格/外观模式/强调色链路不动 |
| `gui/pages/page_about.py` | `_THIRD_PARTY_ITEMS` +1 图标集条目 | 版本卡/更新入口不动 |
| `gui/pages/page_memory_book.py` | 8 Tab 图标统一（I-3） | 8 Tab 数据/逻辑零改动 |
| `gui/pages/page_editor.py` | 配色随四风格×浅深（S-5）；`is_dark_effective` 链路已就位不改 | 语法高亮/编辑逻辑零改动 |
| `gui/themes/base.qss` | 追加：毛玻璃根透明条件规则 `[glass="on"]` + S 组公共控件规则 + 浮层阴影分层 | **只引用 token，无裸色**；不改既有规则语义 |
| `gui/themes/ui_minimal.qss` / `ui_cream.qss` / `ui_night.qss` / `ui_whale.qss` | 四风格二次精修（S-1/S-2/S-3/S-4/S-5 + D-2） | **色值不漂移**（与视觉稿一致）；无新增裸色 |
| `maid_coder_gui.spec` | datas +`('gui/assets/icons','assets/icons')`；hiddenimports +`gui.icons`/`gui.motion`/`gui.glass` | 既有 datas 不动 |
| `maid_coder_gui_onefile.spec` | **同步**图标 datas + 三 hiddenimports | 防 onefile 资源缺口（同 v2.0 ⚠-10 教训） |
| `docs/THIRD_PARTY.md` / `README.md` / `CHANGELOG.md` | 图标集登记 + 用法/能力如实说明（毛玻璃仅 Win11）+ 版本条目 | R-R 诚实，无自评分 |

### 3.3 不动（**保护区**，逐个点名）

| 分类 | 文件 | 理由 |
|---|---|---|
| **v2.0 更新链（硬保护）** | `maling_updater.py` / `updater.spec` / `version.json` / `gui/update_checker.py` / `gui/update_downloader.py` / `gui/widgets/update_progress.py` / `tools/build_release.py` / `tools/release_checklist.md` | PRD §6 Non-goal 4；R-D |
| **`main.py` 更新编排段（段级保护）** | `_compute_install_targets` / `_build_swap_plan` / `_should_launch_updater` / `_select_download_asset` / `_below_min_updatable` / `_can_auto_update` / `_resolve_remote` / `_release_page_url` / `_open_external_url` / `_maybe_open_release_page` / `_bootstrap_update_subsystem` / `_arm_confirm_handshake` / `_start_update_check` / `_show_update_prompt` / `_start_update_download` / `_on_update_verified` / `_on_update_download_failed` / `_show_install_ready_prompt` / `_trigger_restart_install` / `_show_disk_space_hint` / `_open_folder` / `_launch_updater_process` / `_maybe_launch_updater` / `_quit_stop_services`（含末步）+ `main()` 内 :1617-1625 调用 | 本轮**只允许**动外观相关段（:1512-1521 附近、:1605-1615 附近） |
| **v1.9 成果** | `gui/fonts.py` / `gui/assets/fonts/**` / `THEME_DEFINITIONS` 四风格色值 / `LEGACY_THEME_MAP` / `apply_night_lock` / `is_dark_effective` | R-D / D-B |
| **业务与陪伴** | `gui/chat_service.py`（逻辑）/ `session.py` / `memory.py` / `companion.py` / `persona.py` / `pi_backend.py` / `agents.py` / `agent_engine.py` | Non-goal 3 |
| **美术资产（零改动）** | `gui/assets/maid/**` / `gui/assets/maid_pet/**` / `gui/assets/roles/**` / `maling.ico` / `app_icon_*.png`（S-6 仅 splash 色调协调，不改图形） | PRD §6 Non-goal 2 |
| **依赖清单（硬保护）** | `requirements.txt` / `requirements_gui.txt` / `pyproject.toml` dependencies | R-F：**diff 必须为空** |
| **版本源** | `version.json` / `core/__init__.py`（`__version__`） | PRD §6 Non-goal 10 |
| **旧主题 QSS** | `gui/themes/cute.qss` / `minimal.qss` / `maid.qss` | R-D：保留，不出现在 UI 入口 |

### 3.4 文件域切分（供多工程师并行）

| 域 | 独占文件 | 可并行 | 说明 |
|---|---|---|---|
| **域0 契约/兼容层** | `gui/qt_compat.py`、`docs/design-v21.md` §4 | **先行串行** | 三内核 API 签名 + 新配置键 + 常量先冻结 |
| **域1 动效内核** | `gui/motion.py`、`tests/test_v21_motion.py` | 与域2/3/4 并行 | 纯逻辑 + Qt 生命周期，可 offscreen 测 |
| **域2 毛玻璃内核** | `gui/glass.py`、`tests/test_v21_glass.py` | 与域1/3/4 并行 | 探测纯逻辑可 mock；真机留档另算 |
| **域3 图标内核+构建** | `gui/icons.py`、`tools/build_icons.py`、`gui/assets/icons/**`、`tests/test_v21_icons.py`、`docs/THIRD_PARTY.md`、`docs/third_party_licenses/**`、`page_about.py` | 与域1/2/4 并行 | 构建期脚本可独立跑 |
| **域4 配置/主题引擎/设置UI** | `gui/config.py`、`gui/theme_engine.py`、`gui/pages/page_settings.py`、`tests/test_v21_settings.py` | **内部串行**（config→settings）；与域1/2/3 可并行 | **单写者**（settings 页最挤） |
| **域5 主窗/启动/侧栏** | `gui/main_window.py`、`gui/main.py`（仅外观段）、`gui/widgets/sidebar.py` | 依赖域0/1/2/3；与域6/7/8 并行 | `main.py` 单写者（**不得碰更新编排段**） |
| **域6 聊天/浮层** | `gui/widgets/chat_panel.py`、`message_bubble.py`、`chat_window.py` | 同上 | M-2/M-4/I-2 落点 |
| **域7 QSS 打磨/暗色** | `gui/themes/base.qss`、四风格 QSS、`gui/pages/page_editor.py` | 依赖域0；与域5/6/8 并行 | 只改 QSS/配色，不碰 .py 逻辑（editor 仅配色） |
| **域8 记忆中心/其他页图标** | `gui/pages/page_memory_book.py`、其他页（`page_home`/`page_role`/`page_toolbox`/`page_plan`/`page_memories`/`page_help`） | 同上 | I-3 与 S/D 复核 |
| **域9 打包/收口** | 两个 `*.spec`、`README.md`、`CHANGELOG.md`、真机留档 | **串行收尾** | 依赖全部产物名与资源路径定案 |

**必须串行的链**：`V21-01 契约冻结（域0）` → 域1/2/3/4 并行 → 域5/6/7/8 并行 → 域9 收口。**域4（config+page_settings+theme_engine）与域5（main.py）各自单写者**，禁止并发编辑。

---

## 4. 数据结构 / 接口

### 4.1 `GuiConfig` 新增键

| 键 | 类型 | 值域 | 默认 | 归属 | 读时行为 |
|---|---|---|---|---|---|
| `animation_level` | str | `off`/`soft`/`standard` | `"standard"` | M-6 | 非法 → `standard`；缺键 → 类默认（零迁移） |
| `glass_enabled` | bool | — | `True` | G-3 | 缺键 → `True` |
| `glass_popups_enabled` | bool | — | `True` | G-2 | 缺键 → `True` |
| `power_save_mode` | bool | — | `False` | C-2 | 缺键 → `False` |
| `animation_level_pre_power_save` | str | 同 `animation_level` | `"standard"` | C-2 快照 | 缺键 → `standard` |
| `glass_enabled_pre_power_save` | bool | — | `True` | C-2 快照 | 缺键 → `True` |

### 4.2 `gui/motion.py` 接口

```python
LEVELS = ("off", "soft", "standard")
DEFAULT_LEVEL = "standard"
MAX_DURATION_MS = 220
_DURATION_MS = {"off": 0, "soft": 130, "standard": 200}

def configure(level: str) -> None: ...                     # 启动 + 设置页；非法回落 DEFAULT_LEVEL
def level() -> str: ...
def enabled() -> bool: ...                                 # level != "off" and system_animations_enabled()
def system_animations_enabled() -> bool: ...               # SPI_GETCLIENTAREAANIMATION；读不到→True
def duration(base_ms: int = 0) -> int: ...                 # 单一收口；off→0；夹取 ≤ MAX_DURATION_MS
def easing() -> "QEasingCurve": ...                        # OutCubic
def animate(widget, prop: bytes, start, end, *, duration_ms: int | None = None,
            easing=None, on_finished=None) -> "QPropertyAnimation | None": ...
            # enabled()==False → 不实例化，返回 None
            # 否则 QPropertyAnimation(widget, prop, widget) + 注册进模块级 _RUNNING（防 GC）
def fade(widget, *, to: float = 1.0, duration_ms: int | None = None,
         on_finished=None) -> "QPropertyAnimation | None": ...
def stop_all(final: bool = True) -> None: ...              # 收束进行中动画到终态（切 off 时）；并一并停全部循环
def running_count() -> int: ...                            # 测试用（一次性动画）
```

**循环动效（v2.x 增补 · 契约扩展）**

```python
MIN_LOOP_PERIOD_MS = 800                    # 周期下限
MAX_LOOP_PERIOD_MS = 1600                   # 周期上限
_DEFAULT_LOOP_PERIOD_MS = 1200              # 缺省周期

def loop_period_ms(base_ms: int = 0) -> int: ...   # 单一收口；非法/≤0→1200；夹取 [800,1600]
def loop(owner, on_tick, *, period_ms: int | None = None,
         on_disabled=None) -> "_LoopHandle | None": ...
         # enabled()==False → 不启动 / 不建定时器 / 返回 None（落点保持静态形态）
         # 否则登记 _LOOPS（独立于 _RUNNING）；每 tick 回调 on_tick(progress)（progress∈[0,1)）
         # 每 tick 校验 enabled()，False → 全部循环自停 + 回调各自 on_disabled()
def stop_loop(handle) -> None: ...                 # 幂等；_LOOPS 移除；集合空则停驱动器
def running_loop_count() -> int: ...               # 测试用（循环）
```

> **周期不计入 `MAX_DURATION_MS`**（后者仅约束入场/退场过渡）；循环必须受 `enabled()` 门控、**隐藏即停**、可被 `stop_all()` 一并停；`off` 档下不得启动，落点须已有静态形态。
> 驱动器为**模块级惰性创建**的单一 `QTimer`（多循环共享，最省），顶层不创建任何 Qt 对象。

### 4.3 `gui/glass.py` 接口

```python
@dataclass(frozen=True)
class GlassCapability:
    supported: bool
    kind: str          # "mica" | "acrylic" | "none"
    build: int
    reason: str

def detect_capability() -> GlassCapability: ...            # 纯逻辑可 mock（build / is_remote_session）
def is_supported() -> bool: ...
def is_remote_session() -> bool: ...                       # GetSystemMetrics(SM_REMOTESESSION=0x1000)
def apply_main_window(hwnd: int, *, dark: bool) -> bool: ...   # DWMSBT_MAINWINDOW(2) / 21H2 走 1029
def apply_dialog(hwnd: int, *, dark: bool) -> bool: ...        # DWMSBT_TRANSIENTWINDOW(3)
def remove(hwnd: int) -> bool: ...                             # DWMSBT_NONE(1) / 关 1029 / 关 immersive dark
def safe_apply(hwnd: int, kind: str, *, dark: bool) -> bool: ...  # 全 try/except，失败 False，绝不抛
```

### 4.4 `gui/icons.py` 接口

```python
ICON_DIR_REL = "assets/icons"
ICONSET = "<material_symbols | remix_icon>"      # 构建期确定，随包登记
FONT_FAMILY_NAME = "remixicon"                   # 图标字体真实 family 名（唯一真值源）

def register_icon_font() -> Optional[str]: ...   # 返回真实 family（applicationFontFamilies）
def available() -> bool: ...
def has(name: str) -> bool: ...
def glyph(name: str) -> Optional[str]: ...       # chr(codepoint)
def icon(name: str, size: int = 16, color: Optional[str] = None) -> "QIcon": ...
        # color=None → theme_color(app_ctx, "text", fallback)
        # QPainter 绘制字形到 QPixmap（setDevicePixelRatio 适配高 DPI）→ QIcon
        # QPixmapCache 键 = f"{name}|{size}|{color}|{theme_name}"
def font(size: int = 16) -> "QFont": ...         # 文本内嵌用法（颜色由控件 QSS 控制）
def text_glyph(name: str, fallback: str) -> str: ...  # 文本流内嵌便捷入口（见下）
def configure(app_ctx) -> None: ...              # 注入 app_ctx + 订阅 theme_changed 清缓存
def clear_cache() -> None: ...
```

#### 4.4.1 `text_glyph(name, fallback)` 契约

- **签名冻结**：`def text_glyph(name: str, fallback: str) -> str`（`font()` 的姊妹 API，同属「渲染」小节）。
- **语义**：`available() and has(name)` 为真 → 返回 `glyph(name)`（PUA 字形字符，可直接拼接进文案流，如按钮标签 `f"{icons.text_glyph('file', '📄')} 导出 Markdown"`）；否则**原样返回 `fallback`**。
- **fallback 约定（强制）**：调用方把**原 emoji 字面量**作为 `fallback` 传入；**禁止删除 emoji 字面量** —— 它是图标字体缺资源 / 未注册（`available()==False`）时唯一的兜底文案来源，保证文案不空白、不崩（R-K/R-Q 精神）。
- **颜色**：由承载控件的 QSS `color` 控制（与 `font()` 同源）；字形随主题色统一、矢量缩放不糊。
- **无 `QApplication` 安全**：该函数不创建 Qt 对象、不注册字体、不读配置，纯查表返回，可在任何导入阶段调用。

#### 4.4.2 家族链中的图标回退族（`gui/fonts.py::font_family_chain`）

- `font_family_chain(choice, scope)` 在**通用回退族 `sans-serif` 之前**插入图标字体族，族名取 `gui.icons.FONT_FAMILY_NAME`（在函数体内惰性 import，避免模块级循环依赖）。
- 生成形如：`<真实 family>, Microsoft YaHei, remixicon, sans-serif`；`scope="body"` 与 `scope="title"` 两条路径**均生效**。
- 既有「去重保序」逻辑继续生效：图标族**不重复**，且**不得排在 generic 之后**。
- Remix Icon 2.5.0 子集**不含 ASCII / 数字 / 中文**（已真机实测）→ 作为文字链回退族**不会劫持正常字符**，仅在文案流出现 PUA 码位（图标字形）时被选中渲染。
- 图标模块不可用 / 常量缺失时链路该层为 `None`，家族链退化回引入图标族之前的形态（缺资源优雅降级）；函数签名、逗号连接返回格式、`primary_family()` 的 `split(",")[0]` 首值语义**零变更**。

#### 4.4.3 QSS 出口形态（`qss_font_family`）与模板写法纪律

- **第二个出口**：`gui/fonts.py::qss_font_family(choice, scope) -> str` 把裸链渲染成 **QSS 可解析的 family 列表**：每个族名各自加双引号，**通用族（`sans-serif` 等）裸写不加引号**，产出形如 `"Resource Han Rounded CN", "Microsoft YaHei", "remixicon", sans-serif`。`font_family_chain()` 的返回格式**保持不变**（`tests/test_v19_b.py` 的 `split(",")` / `startswith` / `primary_family().split(",")[0]` 均依赖旧格式）。
- **模板纪律（强制）**：QSS 模板里占位符**外不得再加引号** —— 必须写 `font-family: ${font_family};` / `font-family: ${font_title};`，**禁止** `font-family: "${font_family}";`。
- **既有缺陷根因**（v2.1 修复）：模板原先把占位符整条包在一对引号里，替换后 Qt 把整串当成**一个不存在的族名** → 整条链不解析 → 用户所选界面字体与图标字形均不生效（详见 CHANGELOG）。`theme_engine.load_theme` 因此改用 `qss_font_family(...)` 作为 `${font_family}` / `${font_title}` 的替换值。
- **等宽字体声明同理**：`font-family: "Consolas, JetBrains Mono, monospace";` 是**死声明**（整串被当单个族名），须写 `font-family: "Consolas", "JetBrains Mono", monospace;`（逐族引号 + 通用族裸写）；本次一并对 7 套主题 QSS 的 21 处等宽声明修正，代码块自此真正使用等宽字体（**行为变化，需可独立回退时以此条为界**）。

### 4.5 `NAV_ITEMS` 结构（sidebar 从 3 元组 → 4 元组）

| 位置 | 含义 | 备注 |
|---|---|---|
| `[0]` key | 页面 key（`_on_row_changed` 经 `Qt.UserRole` 传出的值） | **不变**（信号语义零变更） |
| `[1]` label | 展示文案 | **不变** |
| `[2]` icon_name | `icons.icon()` 的名称；`None` = 无矢量图标（用 `QIcon.fromTheme`） | **新增语义** |
| `[3]` fallback_text | 图标字体不可用时的 emoji/unicode 回退文本 | **新增**（= 现状第三元的值） |

### 4.6 毛玻璃动态属性（代码 ↔ QSS 契约）

| 属性 | 值 | 由谁设置 | QSS 用途 |
|---|---|---|---|
| `MainWindow.glass` | `"on"` / 无（移除） | 代码（`_apply_glass_state`） | `QMainWindow[glass="on"], QMainWindow[glass="on"] > QWidget { background: transparent; }` |

> 改属性后必须 `style().unpolish(this); style().polish(this)`；关玻璃时**移除属性**，恢复原背景（R-Q③：行为与改动前一致）。

---

## 5. 任务分解（18 项，六批）

> 工作量对齐 PRD 合计 13–18 人日。批间可并行关系见 §3.4；**批 0 必须先行**。

### 批 0 · 契约冻结（域0，先行串行）

| ID | 任务 | 涉及文件 | 依赖 | 验收 | 独占 |
|---|---|---|---|---|---|
| **V21-01** | **契约冻结**：`qt_compat` 追加 6 个符号；`motion`/`glass`/`icons` 三 API 签名冻结；`GuiConfig` 5 新键与默认值；`NAV_ITEMS` 4 元组结构；`glass` 动态属性名；动效时长常量 | `gui/qt_compat.py`、`docs/design-v21.md` §4 | — | 三内核模块可 import（空实现）；`qt_compat` 新符号可导入；配置键默认值断言通过 | 域0 单人 |

### 批 1 · 三内核并行（域1/2/3）

| ID | 任务 | 涉及文件 | 依赖 | 验收 | 独占 |
|---|---|---|---|---|---|
| **V21-02** | `gui/motion.py` 全实现 + 单测 | `gui/motion.py`、`tests/test_v21_motion.py` | V21-01 | `duration()` 档位/夹取纯函数断言；`off` 不创建动画对象；无 `QApplication` 调用不崩；`stop_all` 收束终态；`animate` 返回对象非 None 且 `running_count` 归零 | 域1 |
| **V21-03** | `gui/glass.py` 全实现 + 单测 | `gui/glass.py`、`tests/test_v21_glass.py` | V21-01 | `detect_capability` mock build（22621/22000/19045）与远程桌面返回正确 `kind`；非 Windows → none；`safe_apply` 非法 hwnd → False 且不抛；常量值断言 | 域2 |
| **V21-04** | `gui/icons.py` + `tools/build_icons.py` + 资源 + 授权登记 + 单测 | `gui/icons.py`、`tools/build_icons.py`、`gui/assets/icons/**`、`tests/test_v21_icons.py`、`docs/THIRD_PARTY.md`、`docs/third_party_licenses/**`、`page_about.py` | V21-01 | 子集 TTF 生成 + manifest 覆盖全部用到的名字；缺资源 → `available()==False` 且 `icon()` 返回空 `QIcon` 不崩；缓存键含 color/theme；授权四处登记齐 | 域3 |

### 批 2 · 配置 / 主题引擎 / 设置 UI（域4，内部串行）

| ID | 任务 | 涉及文件 | 依赖 | 验收 | 独占 |
|---|---|---|---|---|---|
| **V21-05** | `GuiConfig` 5 新键 + load/save | `gui/config.py` | V21-01 | 旧存档缺键 → 类默认（零迁移）；非法 `animation_level` → `standard`；save 后重载保持 | 域4 |
| **V21-06** | 「外观与效果」区 + 即时生效 + 省电模式 + 透明度互斥联动 | `gui/pages/page_settings.py` | V21-05 | 三项可见可操作 + 说明文案；改档即时生效无需重启；省电模式一键两项置关 + 快照 + 可恢复；R-A 文案扫描无焦虑词；无控件半遮挡 | 域4 |
| **V21-07** | 系统深浅实时性（D-3）：原生事件监听 + 回落 30s 轮询 | `gui/theme_engine.py` | V21-01 | mock 消息 → 去抖后调 `_poll_system_mode`；`set_theme_mode` 签名/语义回归；`light`/`dark` 固定模式不受影响；`ui_night` 锁定不变 | 域4 |

### 批 3 · 落点并行（域5/6/8，依赖批 1）

| ID | 任务 | 涉及文件 | 依赖 | 验收 | 独占 |
|---|---|---|---|---|---|
| **V21-08** | 主窗毛玻璃 + 透明度互斥 + 切页过渡 + 状态栏图标（G-1/G-3/M-1/I-3） | `gui/main_window.py` | V21-02/03/04/05 | 支持环境窗口材质生效；不支持 → 纯色不黑窗；开玻璃锁透明度 100% + 禁滑杆；关玻璃恢复；切页淡入且 `off` 无动画；状态栏三标签图标化 | 域5 |
| **V21-09** | 侧栏图标替换 + 回退链（I-1） | `gui/widgets/sidebar.py` | V21-04 | `NAV_ITEMS` 10 项全用矢量图标（字体可用时）；不可用时 emoji 回退不空白；导航信号/高亮零回归；四风格下图标取色正确 | 域5 |
| **V21-10** | 聊天顶栏图标 + 命令/提及弹窗淡入淡出（I-2/M-4） | `gui/widgets/chat_panel.py` | V21-02/04 | 顶栏按钮图标替换且功能不变、尺寸对齐；非模态浮层 show 淡入 / close 淡出；`off` 时直显直隐 | 域6 |
| **V21-11** | 气泡入场 + 历史不重播（M-2） | `gui/widgets/chat_panel.py`、`gui/widgets/message_bubble.py` | V21-02 | 新气泡入场；切会话/重载历史不播放；`off` 时立即显示；不阻塞发送链路 | 域6 |
| **V21-12** | 记忆中心 8 Tab 图标统一 + 其他页图标/深色复核（I-3/D-2/S-1） | `gui/pages/page_memory_book.py`、各页 | V21-04 | 8 Tab 图标统一可辨且深色下清晰；其余页卡片/图标统一；数据逻辑零回归 | 域8 |
| **V21-13** | `main.py` 启动接线（外观段） | `gui/main.py` | V21-02/03/04 | `motion.configure` 在 `GuiConfig.load` 后；`icons.register_icon_font` 并列字体注册；`show()` 后 `_apply_glass_state`；**更新编排段 :1617-1625 零变更（diff 核对）** | 域5（main.py 单写者） |

### 批 4 · QSS 打磨 + 暗色（域7，依赖批 0，可与批 1/2/3 并行）

| ID | 任务 | 涉及文件 | 依赖 | 验收 | 独占 |
|---|---|---|---|---|---|
| **V21-14** | 四风格 QSS 二次精修 + 控件五态 + 通用控件 + 浮层阴影分层 + 毛玻璃根透明规则（S-1/2/3/4 + D-V21-04） | `gui/themes/base.qss` + 四风格 QSS | V21-01 | 四风格 × 全站页面逐页截图对照无漏改；六类控件五态有显式规则；滚动条/下拉/复选/滑块齐；三档阴影可辨且深色靠描边；**QSS 无新增裸色**（扫描 `#RRGGBB` 仅在 token 定义处）；`[glass="on"]` 规则生效 | 域7 |
| **V21-15** | 代码块/编辑器配色随风格 + 深色对比度审计修正（S-5/D-1/D-2） | 四风格 QSS、`gui/pages/page_editor.py`、`theme_engine.py`（仅在需修色值时） | V21-01 | 四风格×浅深 8 组合 `code_text`/`code_bg` 对比度 ≥ 4.5:1；`text`/`text_secondary`/`text_hint` 达标（自动计算脚本输出逐项报告）；不达标项最小修正并留档；**四风格既有色值不漂移**（除不达标项） | 域7 |

### 批 5 · 收口（域9，依赖全部）

| ID | 任务 | 涉及文件 | 依赖 | 验收 | 独占 |
|---|---|---|---|---|---|
| **V21-16** | 打包 spec 收口（图标 datas + 三 hiddenimports，双 spec 同步）+ 图标字体随包 + 冒烟 | `maid_coder_gui.spec`、`maid_coder_gui_onefile.spec` | V21-04/13 | 双 spec 一致；onedir/onefile 包内 `_internal/assets/icons/` 有 TTF+manifest+LICENSE；图标与动效在包内取证（dist 真机） | 域9 |
| **V21-17** | 真机留档（毛玻璃/动效/性能）+ 红线扫描 + 全量回归 | 留档文档 | V21-08/10/11/13/14/15/16 | Win11 真机 Mica + 浮层 Acrylic 取证；Win10/远程桌面 → 纯色不黑窗；重开/换肤/拖动材质不丢不卡；启动 ≤+5% / 内存 ≤+20MB 留档；`requirements*.txt` diff 为空；R-A 扫描零命中；v2.0 全量零回归；py_compile + pytest 双绿 | 域9 |
| **V21-18** | 文档收口：THIRD_PARTY / README（毛玻璃仅 Win11 如实说明）/ CHANGELOG（不自评分） | `docs/THIRD_PARTY.md`、`README.md`、`CHANGELOG.md` | V21-16/17 | 图标集登记齐；能力边界如实；无自评分；dist 核对点留档 | 域9 |

**裁剪顺序（资源紧张时）**：`M-5 待机微动效`（P2，默认不做）→ `M-3 侧栏微交互`（降为 QSS 静态态）→ `S-6 splash 色调`（P2）→ `M-4 浮层淡出`（保留淡入）→ `G-2 浮层 Acrylic`（保留主窗 Mica）。**M-0/M-6/G-0/G-1/G-3/I-0/I-1/C-1/C-3 与 R-F/R-P/R-Q 相关项不裁。**

> **M-5（待机微动效）本轮默认不做**：它是 P2/可裁项，且"周期呼吸"与 Q-V2 锁定的四项克制动效不同源，且持续动画有 R-P 隐患（常驻 CPU）；若用户强需求，另立小轮，用低频 opacity 脉冲 + 独立开关实现。

---

## 6. 共享知识（团队必读）

1. **Qt Widgets 的 QSS 不支持 `transition` / `animation`**（与 Web 不同）——**一切过渡/入场/微交互必须走代码侧**（`gui/motion.py`）。在 QSS 里写 `transition:` 无效且会误导后来者。这是本轮最大认知陷阱（PRD §2.2 / §7.4 R4）。
2. **QSS 里的 `${...}` 不是 CSS 变量**：它是 `theme_engine.load_theme` 的**字符串替换占位符**（`theme_engine.py:383-384`），只在 `load_theme` 时按活动色板替换一次；**新增 QSS 只允许引用已注册 token**，且**禁止新增裸色 `#RRGGBB`**（除 token 定义处）。
3. **R-D 契约保留区**：`theme_changed(str)` / `load_theme` / `_active_palette` / `_custom_accent` / `derive_accent_palette` / `set_theme_mode` / `is_dark_effective` / `apply_night_lock` / `get_color` / `get_layout_token` —— **签名与语义零变更**；新需求一律"加皮肤/加订阅者/加键"，不改机制。
4. **取色唯一入口**：新控件（不依赖 QSS 的代码侧取色）一律 `theme_color(app_ctx, key, fallback)`（`utils.py:32`）；图标/动效/毛玻璃**不得硬编码颜色**。
5. **动效唯一收口 `motion`**：落点调 `motion.animate()/fade()`，**禁止散落 `QPropertyAnimation(...).start()` 与硬编码 `setDuration(<常量>)`**（M-0 验收②静态扫描）。
6. **毛玻璃 fail-safe 铁律**：`glass` 任何失败路径返回 `False`，**绝不抛异常**；不可用环境必须**纯色降级**，不得黑窗/全透明/文字不可读（G-1 验收②）。
7. **毛玻璃与透明度互斥（Q-V8）**：玻璃开 → `setWindowOpacity(1.0)` + 禁滑杆；玻璃关 → 恢复 `cfg.window_opacity`。**不得出现两个半透明叠加**。
8. **Mica 需要根窗口透明**：材质只在"没有不透明白底覆盖"处可见 → 玻璃开时给 `MainWindow` 设 `glass="on"` 动态属性并 `unpolish/polish`；**卡片/气泡保留各自不透明底**，材质只在留白/间隙透出。**不要**给主窗设 `WA_TranslucentBackground`（会破坏系统背景材质路径）。
9. **图标字体 ≠ 界面字体**：图标字体走 `gui/icons.py` + `gui/assets/icons/`，**不并入 `gui/fonts.py` 的 `FONT_IDS`**（避免 UI 字体下拉被污染）；缺字体 → emoji 回退（`NAV_ITEMS` 第四元）。
10. **`qtawesome` 只准出现在构建期脚本**（`tools/build_icons.py` 注释内），**不得出现在任何 `gui/` 源码或 `requirements*.txt`**（R-F）。
11. **v2.0 更新链保护（段级）**：`maling_updater.py` / `version.json` / `update_checker.py` / `update_downloader.py` / 两 spec 的更新契约 / `main.py` 更新编排段（`_quit_stop_services` 及其后所有更新相关函数 + `main()` 内 :1617-1625 调用）**零变更**；本轮只允许动 `main.py` 的**窗口创建与外观相关段**。
12. **资源路径纪律（沿用 v1.9 ⚠-2）**：资源相对路径必须与 `gui/` 下源码路径一致（`assets/icons/...`），spec `datas` 目标目录 = 该相对路径；`get_resource_path` 在 frozen 以 `_MEIPASS`、源码以 `gui/` 为基准。
13. **沙箱批量删除限制**：批量删除 >50 个文件会被沙箱 safe-delete 拦截（v1.9/v2.0 先例）；清理构建产物/临时图标子集产物时**分批删除**或走 `shutil.rmtree(onerror=...)` 逐项重试，避免一次性 `unlink` 列表触发拦截。
14. **测试必须 `QT_QPA_PLATFORM=offscreen`**：GUI 冒烟/信号/控件测试在无显示环境（CI/沙箱）必须 `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")`（先例：`tests/test_v161_quit.py:20` 等），否则 `QApplication` 初始化失败。
15. **受管 Python 路径**：本机受管解释器固定为 `/c/Users/Administrator/.workbuddy/binaries/python/versions/3.13.12/python`（`.workbuddy/binaries`）；构建/测试/子集化命令一律用受管解释器，**不依赖 PATH 里的 `python`**。
16. **worker/信号投递延迟**：`QThread`/`QTimer` 信号投递到 GUI 线程有事件循环延迟；**测试断言"收到信号/动画已跑"必须 `QCoreApplication.processEvents()` 或等待事件循环**，不能"启动后立刻断言"（v16/v17/v20 先例）。
17. **编号续写**：红线编号本期从 **R-P 起**（R-A/R-D/R-F 沿用；v1.6 用 R-K、v1.9 用 R-L、v2.0 用 R-M/N/O）；架构决策编号续 **D-V21-xx**；任务编号 **V21-xx**。**禁止复用**既有编号。
18. **深色层级不靠阴影**：深色下 `${shadow}` 视觉弱化属正常，层级由 `${border}` 表达（design-v19 §D-V19-15④）；实施期不要误判"阴影丢失"而回补强阴影。

---

## 7. 测试与验证策略

### 7.1 可自动化（pytest 直接断言，无需真机/显示）

| 模块 | 断言点 |
|---|---|
| `motion` | `duration()` 三档取值 + 夹取 ≤220 + 非法档回落；`enabled()` 随档与 `system_animations_enabled()` 变化；`animate()` 在 `off` 时返回 `None` 且 `running_count()==0`；`QEasingCurve` 类型；无 `QApplication` 调用不崩；`stop_all(final=True)` 后动画值到终态 |
| `glass` | `detect_capability()` mock `sys.getwindowsversion().build`（22621/22000/19045/非 NT）+ mock `is_remote_session()` → `kind`/`supported`/`reason` 正确；`safe_apply(0, ...)` → `False` 不抛；常量值断言（38/1029/2/3/1/0x1000） |
| `icons` | 名→码位映射；未知名字 `has()`/`glyph()` 返回 Falsy；`available()==False` 时 `icon()` 返回空 `QIcon` 不崩；缓存键含 color/theme（换肤后重渲染）；无 `QApplication` 不崩 |
| `config` | 5 新键默认值；旧存档（无键 JSON）加载 → 类默认（零迁移）；非法 `animation_level` → `standard`；save→load 往返一致 |
| 设置页 | offscreen 构造 `PageSettings`；省电模式 → 两键同时置关 + 快照写入；退出省电 → 恢复快照；透明度滑杆 `isEnabled()` 随玻璃联动 |
| 侧栏 | offscreen 构造 `SidebarWidget`；字体不可用 → 文本回退含 emoji；`item_clicked` 信号仍按 key 发出（零回归） |
| QSS 扫描 | `grep` 四风格 QSS 与 base 的 `#RRGGBB` **只出现在 token 定义处**（S-1 验收③）；新增规则引用的 `${...}` 键均在 `THEME_DEFINITIONS` 注册 |
| 对比度审计 | 纯脚本读四风格 `colors/colors_dark`，计算 `text`/`text_secondary`/`text_hint`/`code_text` 对背景的 WCAG 对比度，输出逐项报告（D-1/S-5 验收①②） |

### 7.2 必须 mock（不可真机/不可联网）

| 项 | 做法 |
|---|---|
| **DWM 调用** | `glass` 把 `hwnd` 与 `windll` 访问抽象为可注入点（测试传 `hwnd=0` 或 monkeypatch 函数）；断言"不支持时不执行 DWM 调用"（G-0 验收②：不调用 `DwmSetWindowAttribute`） |
| **系统动画开关 / 系统深浅** | monkeypatch `system_animations_enabled()` / `_read_system_light_theme()` 返回值，验证 `enabled()`/`_poll_system_mode` 分支 |
| **原生事件监听** | 直接调 `nativeEventFilter` 桩（构造伪 `MSG`）断言去抖后触发 `_poll_system_mode`（不依赖真实 `WM_SETTINGCHANGE`） |
| **构建期图标子集** | 若无法联网取图标源，`build_icons.py --source-dir` 指向本地 TTF（同 `build_fonts.py` 先例）；单测只验 manifest 契约，不验真实字体文件 |

### 7.3 **mock 测不出 → 必须真机留档**（V21-17 核心）

| 项 | 为什么 mock 测不出 |
|---|---|
| **Mica/Acrylic 真实观感** | DWM 材质由系统合成，offscreen/无显示环境**完全不触发**；必须 Win11 真机取证（G-1 验收①"读取 DWM 属性 / 目视取证"） |
| **Win10 / 远程桌面降级** | 需真实 OS 版本 + 真实 RDP 会话验证"纯色不黑窗"（G-1 验收②） |
| **多显示器 / 高 DPI 下的材质边界** | 需真实多屏与缩放环境（PRD §7.2） |
| **窗口拖动帧率** | 需真实合成器 + 录屏 + CPU 抽样（R-P③） |
| **图标字体在真实 DPI 下的清晰度** | offscreen 无真实 DPI 缩放（I-1 验收③） |
| **启动耗时 / 内存对比** | 需真实进程冷启动与静置测量（R-P①②） |
| **重显/最小化还原后材质是否保留** | 需真实窗口状态迁移 |

### 7.4 "关掉动效/毛玻璃后行为与改动前完全一致"如何验证

| 效果 | 验证方式 |
|---|---|
| **动效 off** | ①断言 `motion.animate()/fade()` 返回 `None` 且未实例化 `QPropertyAnimation`（`running_count()==0`）；②切页/气泡/浮层路径走"直接设终态"分支；③offscreen 对比 `off` 与 `standard` 的**终态 widget 属性快照**（opacity/geometry/effect 均一致）；④真机录屏对照（无动画） |
| **毛玻璃关** | ①断言 `glass.remove(hwnd)` 被调 + `MainWindow[glass="on"]` 属性被移除 + `style()` 已 `unpolish/polish`；②`setWindowOpacity(cfg.window_opacity)` 恢复 + 滑杆 `isEnabled()==True`；③offscreen 对比关玻璃前后主窗背景色 = `${bg}` 纯色（QSS 计算值）；④真机截图对照"关玻璃 = 改动前观感" |
| **降级态（不支持）** | 断言 `is_supported()==False` → `safe_apply` 未被调用 → 主窗背景 = `${bg}`；真机在 Win10/远程桌面取证不黑窗 |

### 7.5 回归矩阵（抽样，避免组合爆炸）

| 维度 | 抽样 |
|---|---|
| 四风格 × 浅深（8 基色板） | **全测**（每风格浅深各一页基准 + 关键页） |
| 毛玻璃 | Win11 真机抽 `ui_minimal` 浅 + `ui_night` 深（材质 + 对比度）；Win10/远程桌面各 1 次降级 |
| 动效档 | `off`（无动画 + 终态一致）/ `standard`（有动画）；`soft` 抽 1 次 |
| 图标 | 矢量可用 + 字体缺失 emoji 回退 两态 |
| 红线 | R-A 全页面扫描（四风格 × 浅深）+ R-F diff + R-D 契约回归 |

---

## 8. 红线落法（PRD §8 逐条 → 代码级落点 + 可断言检查）

| 红线 | 落点 | 可断言检查 |
|---|---|---|
| **R-A 无焦虑** | 新设置项文案（动效强度/毛玻璃/省电）用中性描述；动效/毛玻璃/图标**不引入任何数值化组件**（无"性能评分/落后/剩余/次数"） | ①全 UI 文案扫描词表（心情/好感/等级/token/进度/断签/倒数/评分/落后/卡顿）零命中；②新设置项逐一人工复核语义；③四风格 × 浅深 × 效果开关全组合逐页扫描 |
| **R-D 只增量** | D-V21-12 契约表；`theme_engine` 只加"事件监听装卸 + 轮询间隔"；`config` 只加键；QSS 只加规则不改色值；`fonts.py` 零改动；旧三 QSS 保留 | ①`theme_changed`/`load_theme`/`_active_palette`/`derive_accent_palette`/`set_theme_mode`/`is_dark_effective`/`apply_night_lock` 签名与语义回归测试；②四风格 `colors` 色值 diff（除 D-1 不达标修正项，须留档）；③v2.0 全量零回归 |
| **R-F 零新依赖（保持不放宽）** | `motion`（PySide6 内置 + ctypes）、`glass`（ctypes 标准库）、`icons`（PySide6 + 构建期 fonttools/qtawesome）；`qtawesome`/`fonttools` 均**仅构建期** | ①**`git diff --exit-code -- requirements.txt requirements_gui.txt` 为空**（可执行断言）；②`pyproject.toml` `dependencies` 未新增；③AST 扫描 `gui/motion.py`/`glass.py`/`icons.py` 的 import 白名单（仅 PySide6/stdlib/`gui.*`），`qtawesome` 零命中；④dist 产物无 `qtawesome` 包 |
| **R-P 性能（新增）** | `motion.duration()` 夹取 ≤220；无启动动画（Q-V10）；动画对象用完即弃；`QGraphicsOpacityEffect` 动画结束移除；`icons` 走 `QPixmapCache` 且有界；`glass` fail-safe 不阻塞；**循环动效另立类别**（周期 800–1600ms，**不计入** 220ms 上限），每 tick 校验 `enabled()`、隐藏即停、`stop_all` 一并停、无泄漏 | ①冷启动 ≤+5%（对比法 5 次中位数，留档）；②内存 ≤+20MB（留档）；③拖动无卡顿 + CPU ≤基线+10%（留档）；④`duration()` 纯函数断言 ≤220；⑤切页调用返回 <16ms；⑥不可用环境不重试不卡启动；⑦循环：`loop_period_ms()` 纯函数夹取 800–1600、`off` 不启动、`enabled()==False` 自停、`stop_all` 停全部、`_LOOPS` 不泄漏、`stop_loop` 幂等 |
| **R-Q 可关闭与可退路（新增）** | 动效三档（`motion`）；毛玻璃开关（`_apply_glass_state`）；不支持自动降级；省电模式（C-2）；四风格 QSS 文件独立可回滚；新模块可剥离（`glass`/`icons`/`motion` 失败均静默回退） | ①`off` → 无动画对象；②玻璃关 → 恢复纯色 + 滑杆恢复；③设置改动即时生效无需重启；④四风格 QSS 单独回滚不影响其余；⑤新模块缺失（模拟 import 失败）→ 主程序仍启动、回退到改动前行为；⑥省电模式一键两项置关且可恢复 |
| **R-R 视觉与授权诚实（新增，扩 R-K/R-L）** | 图标集授权四处登记；README/CHANGELOG 如实（毛玻璃仅 Win11 / Win10 降级纯色）；dist 逐项核对 | ①`docs/THIRD_PARTY.md` + `docs/third_party_licenses/` + 包内 `gui/assets/icons/LICENSE` + About 条目齐；②README/CHANGELOG 含"Mica 仅 Win11、Win10 及远程桌面降级纯色"如实说明；③无自评分；④dist 核对点：图标字体落包 / manifest 落包 / 动效在包内生效 / 毛玻璃在包内 Win11 生效 / 降级路径可用——逐项留档 |

---

## 9. 风险与回退

### 9.1 风险清单

| # | 风险 | 定级 | 说明与缓解 |
|---|---|---|---|
| R1 | **毛玻璃真机兼容**（build/远程桌面/多显示器/高DPI/杀软） | **中高** | Mica/Acrylic 系统合成行为因环境而异，mock 完全测不出 → **能力探测 + fail-safe + 自动降级 + 可关**四件套 + §7.3 真机留档；远程桌面直接降级纯色 |
| R2 | **Mica 需要根窗口透明，与四风格 QSS 冲突** | **中高** | 主窗默认有不透明底 → Mica 不显或与卡片叠加异常；缓解：动态属性 `[glass="on"]` 条件规则 + `unpolish/polish`，**卡片保留不透明底**只让留白透出；关闭即移除属性恢复原样。**这是最容易翻车的一处**（见 §9.3） |
| R3 | **图标字体真实 family 名不定 / 缺字** | 中 | 同 v1.9 字体范式：**构建期用 `applicationFontFamilies` 实测**真实 family 写入（代码不猜名）；缺资源 → emoji 回退（`NAV_ITEMS` 第四元）不崩 |
| R4 | **动效与交互手感** | 中 | 过强显廉价、过弱无感知 → 时长 ≤220 + 克制缓动 + 真机调参 + 用户主观确认（§7.3） |
| R5 | **`QGraphicsOpacityEffect` 在复杂页上的重绘开销** | 中 | 动画结束**立即移除 effect**（不留常驻 effect）；`off` 时不创建 effect；切页仅淡入新页 |
| R6 | **浮层淡出与模态 `exec()` 时序冲突** | 中 | 口径：模态对话框**只做淡入**；非模态浮层才做淡入+淡出（D-V21-02） |
| R7 | **Qt QSS 无 transition 的认知陷阱** | 中 | 共享知识 §6.1 + D-V21-08 职责表明确；代码评审检查 QSS 中无 `transition` |
| R8 | **切档/关效果时残留半透明/错位** | 中 | `motion.stop_all(final=True)` 收束到终态；玻璃关时移除属性 + 恢复透明度 + `polish` |
| R9 | **原生事件监听平台差异/收不到消息** | 中 | 回落 30s 轮询（D-V21-11）；轮询器启停语义不变；`light`/`dark` 不受影响 |
| R10 | **组合回归量大** | 中 | 正交化（D-V21-09）+ §7.5 抽样矩阵 |

### 9.2 逐项回退方案

| 效果/改动 | 回退动作 |
|---|---|
| 动效 | 设置页切 `off`（运行时零动画，行为同改动前）；或回退 `motion.py` + 各落点调用（新模块可整体剥离，落点均有 `if anim is None` 兜底） |
| 毛玻璃 | 设置页关开关（即时恢复纯色）；或回退 `glass.py` + `_apply_glass_state`（fail-safe 设计使缺失即纯色） |
| 图标 | 回退 `icons.py` 注册（`available()==False` → 全站 emoji 回退，即现状）；或回退 `NAV_ITEMS` 到 3 元组 |
| 四风格 QSS 精修 | 四文件**独立**，单风格回滚不影响其余三风格与 v1.9 既有色值 |
| 深色对比度修正 | 只改 `_DARK_OVERRIDES` 不达标项（留档），可逐项回滚 |
| 系统深浅实时性 | 移除事件监听 → 回落 30s 轮询 → 再回落 5min（三层退化，均不崩） |
| 整个 ui-v21 | 新模块（`motion`/`glass`/`icons`）+ 新键 + QSS 规则全可剥离；剥离后仅剩"外观段调用"需一并回退（`main.py` 外观段与新键分离、可单独回退） |

### 9.3 你认为最容易翻车的一处（**明确标出**）

**＝ Mica 落地的"根窗口透明 ↔ 四风格 QSS ↔ 深浅切换 ↔ 透明度互斥"四者协同链（R2）。**

理由与具体翻车点：
1. **Mica 不会自动透出**——Qt 主窗与中心容器默认有不透明背景，`DwmSetWindowAttribute` 设了材质但被自绘背景盖住 → "开了没效果"。必须让根/中心透明，但**不能全局透明**（否则卡片气泡都透、文字压壁纸不可读，违 G-4）。
2. **透明化与四风格 QSS 的双真值源**——若在代码里 `setStyleSheet` 加透明，会覆盖四风格 QSS；正确解法是**动态属性 + QSS 条件规则**（D-V21-04），但属性变更后**必须 `unpolish/polish`**，漏了就不刷新（"改了属性没反应"）。
3. **深浅切换要重设**——Mica 深浅由 `DWMWA_USE_IMMERSIVE_DARK_MODE` 决定，`theme_changed` 后必须重新 `safe_apply`，否则切深色后材质仍是浅色调（突兀）。
4. **透明度滑杆互斥**——若遗漏，用户开玻璃再拉滑杆 → 双半透明叠加发灰（PRD F-9 原始问题原样复现）。
5. **窗口重显**——最小化还原/多显示器切换后部分 Windows 版本会丢材质，需在 `showEvent`/`changeEvent` 重应用。

→ 该链**任一环漏掉都会以"毛玻璃坏了"的形式暴露**，且 mock 测不出（§7.3）。因此 D-V21-04/D-V21-05 全文最细，V21-08 验收逐条对齐，V21-17 真机留档必须覆盖"开/关/切深浅/切风格/重显/拖动/降级"七态。

### 9.4 是否有 Q 项需上升给用户裁决

**结论：无需上升。** 逐条核对代码现状后：

| Q | 是否阻塞 | 依据 |
|---|---|---|
| Q-V1/Q-V2/Q-V3/Q-V4/Q-V8 | 已锁死 | 本文直接执行 |
| Q-V5（图标集） | 否 | 现行候选（Material Symbols / Remix Icon，均 Apache-2.0）与 `docs/THIRD_PARTY.md` 白名单（MIT/Apache-2.0/BSD/CC0）一致；构建期定稿即可，无冲突 |
| Q-V6（性能基线） | 否 | 与 R-P 一致，可测量化已落 D-V21-13 |
| Q-V7（低配降级） | 否 | 现状无硬件探测代码，PM 建议"不自动探测"与既有行为一致 |
| Q-V9（系统深浅实时性） | 否 | 原生事件过滤器为 PySide6 标准能力 + 既有 `winreg` 轮询可回落，零冲突 |
| Q-V10（首屏动效） | 否 | 不新增启动动画，与既有启动链零冲突 |
| Q-V11（图标换语义） | 否 | 仅着色，不换语义集，零冲突 |
| Q-V12（QSS 参考库） | 否 | 不引入，与 R-D/R-F 一致 |

→ 12 个 Q 全部收敛，**无阻塞性冲突需升级**。

---

## 10. DoD（对照 PRD §10 逐条）

1. **S 样式打磨立住**：四风格 QSS 二次精修完成、逐页截图对照无漏改；六类控件五态齐备；滚动条/下拉/复选/滑块/提示圆角描边统一；三档阴影可辨（深色靠描边）；代码块与编辑器四风格×浅深配色达标（≥4.5:1）；**无新增裸色**、四风格核心色值不漂移。
2. **M 动效立住**：`gui/motion.py` 单点收口；切页/气泡/浮层/侧栏四项克制动效落地（≤220ms）；`off`/`soft`/`standard` 三档可选且持久化；`off` 时**不创建动画对象**、进行中动画收束到终态；历史消息重载不重播；系统减少动画被尊重。
3. **G 毛玻璃立住**：能力探测（Win11 22H2+ Mica / 22H2 前 Mica / Win10 及远程桌面 none）+ 主窗 Mica + 顶层对话框 Acrylic + 侧栏透明叠加；**fail-safe、不可用自动降级纯色、不黑窗**；开关默认开、可关、即时生效；与透明度滑杆互斥；深浅联动重应用。
4. **I 图标立住**：`gui/icons.py` 单一收口、零新增运行时依赖；侧栏 10 项 + 顶栏 + 状态栏 + 设置分区 + 记忆中心 8 Tab 全部替换；四态着色随四风格与深浅；高 DPI 不失真；缺字体 emoji 回退不空白；图标集授权四处登记。
5. **D 暗色立住**：四风格深色正文 ≥4.5:1、次级大字 ≥3:1（逐项报告）；深色细节（滚动条/描边/分隔线/代码块/气泡/浮层）精修；跟随系统 ≤30s 内跟随（事件监听即时）；深色×毛玻璃对比达标；深浅过渡可关且不闪白、不破坏 `dark_locked`。
6. **C 设置与开关立住**：「外观与效果」区信息架构清晰、每项含说明文案、无控件遮挡；省电模式一键关动效+毛玻璃且可恢复；新键持久化、旧存档零迁移、切换即时生效无需重启；R-A 文案无焦虑语义。
7. **红线归零**：R-A / R-D / R-F / R-P / R-Q / R-R 全条对照；**`requirements*.txt` diff 为空**；`qtawesome` 零命中运行时；四风格 × 浅深 × 效果开关全组合逐页 R-A 扫描零命中；R-D 契约回归全绿。
8. **零回归 + 打包**：v2.0.0 全量功能（四风格 / 字体 / 命名 / 记忆 / 群聊 / Pi / **自动更新链**）零回归；py_compile + pytest 双绿；两 spec 同步图标 datas + hiddenimports；icons/motion/glass 在包内取证；**真机留档**（毛玻璃七态 + 动效 + 性能对比）；README/CHANGELOG 诚实标注毛玻璃适用面、无自评分。

---

> 文档结束 · 高见远 · 2026-09-11 · 基线 v2.0.0 · 功能面零改动 · v2.0 更新链零触碰 · R-F 保持不放宽（零依赖替代） · 最大风险 = 毛玻璃真机兼容与"根窗口透明↔QSS↔深浅↔透明度互斥"协同链
