# 码铃（MaLing）v1.9 增量架构设计 ——「视觉重塑：四风格 × 字体系统 × 人设命名」

- 版本：v1.9（增量设计，格式对齐 design-v16 / design-v17 / design-v18）
- 文档状态：定稿（Q-E1~Q-E7 已由用户裁决，全按 PM 建议值，本文标「Q-Ex 裁决」）
- 维护人：高见远（架构）
- 关联文档：`docs/prd-v19.md`（需求源）+ `docs/font-research-2026-09-10.md`（字体选型授权依据）+ 视觉稿 `D:/【试用测试】/ui_concept/码铃_UI四风格四字体.html`（设计基准，用户已首肯）+ `docs/design-v18.md`
- **基线：v1.8.1**（视觉稿 HTML 中 `--bg/--accent/--radius` 即四风格 `:root` 变量源）
- 设计纪律重申：**功能面零改动**（Non-goals）；群聊与 Pi 引擎零触碰；全部落点经 v1.8.1 源码逐行核实。

---

## 1. 范围与现状校正（先读我）

### 1.1 三块范围

| 块 | 内容 | 主要落点 |
|---|---|---|
| **C**（先行 1–1.5d） | 名字 / 自称 / 称呼规则分离 + 7 预设命名 + 鲸鱼娘设定补全 + "自称女仆"残留清理 | `persona.py` / `gui/pages/page_role.py`（Role + ROLE_PRESETS）/ `gui/role_card.py` / 8 处 UI 文案 |
| **B**（1.5–2.5d） | 内置 2 款 OFL 圆体（子集化）+ 4 系统字体 + fallback 链 + 切换器 + 构建脚本与许可 | 新 `gui/fonts.py` / `gui/theme_engine.load_theme` / 新 `tools/build_fonts.py` / `maid_coder_gui.spec` |
| **A**（4–6d，最大） | 四风格 QSS 全量 + 切换器 + 旧配置映射 + 即时生效 | `gui/theme_engine.py` / `gui/themes/*.qss` / `page_settings.py` / `chat_panel.py` / `main_window.py` |

Non-goals（PRD §1.4 全承接）：不改女仆形象资产 / 不做语音通话与桌宠与回忆相册 / 不动 Pi 与群聊 / 不新增功能面 / 不做动态主题与壁纸与 UI 缩放 / 不内置第三款字体与 B/C/D 级授权字体。

### 1.2 现状校正（⚠ 标红：PRD 表述与源码不符处，按本文执行）

| # | PRD 表述 | 源码事实（已核） | 本文裁决 |
|---|---|---|---|
| ⚠-1 | 「既有 `GuiConfig.theme`」 | 键名实为 **`theme_name`**（gui/config.py:22，默认 `"cute"`；save 落 :120）；启动读取在 main_window.py:58 | 映射逻辑挂在 `theme_name`（D-V19-10）；**不新增 `ui_style` 键**（避免双真值源），沿用 `theme_name` 承载四风格 id |
| ⚠-2 | 「spec datas 收集进 `_internal/fonts/`」 | `get_resource_path`（gui/utils.py:12）在 frozen 态以 `_MEIPASS` 为基准，源码态以 **`gui/`** 为基准 —— 目标目录必须与 `gui/` 下的相对路径一致（先例：`('gui/themes','themes')` 对应 `themes/xxx.qss`） | 字体放 `gui/assets/fonts/` + spec 目标 **`assets/fonts`**（不是 `fonts`），否则 frozen 态 `get_resource_path("assets/fonts/…")` 落空 → 静默回退（D-V19-06） |
| ⚠-3 | 「四风格不改既有契约」隐含"消费侧无需改" | `page_editor.py:205` 硬编码 **`self._is_dark = theme_name == "cute"`** —— 四风格下明暗判断完全失效（编辑器配色与主题错位） | 新增 `ThemeEngine.is_dark_effective()` 查询方法（**信号签名零变更**），page_editor 改接；其余 theme_changed 订户逐一核查（D-V19-13） |
| ⚠-4 | 「设置页「界面风格」下拉」 | 设置页现为"主题三选 + 快速切换按钮 ×3 + 外观模式"双维度（page_settings.py:103-151）；另 onboarding.py:350/501 也有主题选择与落盘 | 三处 UI 同步改造（设置页下拉 / 聊天顶栏入口 / onboarding 四风格），**共用同一 theme id 常量**（D-V19-13） |
| ⚠-5 | 字体"仅构建期依赖 fonttools" | requirements/spec 现状无 fonttools（已核） | 正确；但需**固化可复现**：源字体获取方式与字表生成脚本一并入库（D-V19-06） |

### 1.3 已核实的关键对接点（v1.8.1）

| 对接点 | 位置 | v1.9 用途 |
|---|---|---|
| `THEME_DEFINITIONS`（cute/minimal/maid） | theme_engine.py:49-181 | A 块增量四条目（键位完全对齐） |
| `load_theme`（`${...}` 替换 + `app.setFont`） | theme_engine.py:211 / :245-253 | B 块字体**单点接入**（`${font_family}` + `${font_title}`） |
| `_active_palette` / `derive_accent_palette` / `set_theme_mode` / `theme_changed(str)` | theme_engine.py:302 / :529 / :262 / :42 | **契约保留区**（签名与语义零变更） |
| `_augment_theme_palettes` / `_DARK_OVERRIDES` / `_SEMANTIC_*` | theme_engine.py:682 / :588 / :634-679 | 深色变体与语义键的现有装配机制（四风格沿用同一机制） |
| `GuiConfig.theme_name` / `theme_mode` / `custom_accent` / `font_size` | config.py:22 / :48 / :50 / :23 | 新增 `font_family`；其余只读 |
| `PersonaConfig.address_self` / `build_system_prompt` | persona.py:15 / :22-35 | C 块自称句生成改造点 |
| `Role` 数据模型 / `ROLE_PRESETS` / `PRESET_ROLE_IDS` | page_role.py:526 / :129 / :231 | `given_name` 字段增量 |
| `PRISTINE_ROLE_ID` / `PRISTINE_SYSTEM_PROMPT` | page_role.py:116-124 | 默认预设修正需同步（:135 属 ROLE_PRESETS["温柔女仆"]） |
| `role_card.py`：SCHEMA_VERSION=2 / `EXPORT_FIELDS` / `parse_card` / `card_summary_text` | role_card.py:27 / :36 / :179 / :268 | `given_name` 入白名单 + 预览呈现 |
| `main()` 启动链 | main.py:773（QApplication）→ :801（GuiConfig.load）→ :885（MainWindow） | 字体注册插入点：**:801 之后、:885 之前** |
| 聊天顶栏 `title_row` | widgets/chat_panel.py:229-339 | 风格快捷入口挂点 |
| About「内置开源组件」表 | pages/page_about.py:72-86 | R-L 字体条目登记位 |
| spec datas / hiddenimports | maid_coder_gui.spec:22-50 / :51+ | 字体与主题资源收集 |

---

## 2. 架构决策（D-V19-01 ~ D-V19-15）

### C 块

#### D-V19-01 名字与人设标签分离：`given_name` 字段 + 自称生成规则

- **Role 增量**（page_role.py:526）：`__init__` 增 `given_name: str = ""`；`from_dict` 用 `data.get("given_name") or ""`（旧角色 JSON 缺字段零崩溃）；`to_dict` 落盘。**语义**：`name` 继续承担"人设标签 / 角色显示名"；`given_name` 为"她的名字"，空串 = 无名字。
- **自称生成（唯一规则源）**：`given_name` 非空 → 自称 = `given_name`；为空 → 自称 = `"我"`。**任何人设标签永不出现在自称位**。实现落两处：
  1. `persona.build_system_prompt`（persona.py:35）：自称句改为按上述规则生成（`PersonaConfig` 增 `given_name: str = ""`）。
  2. 角色卡链路：`Role.system_prompt` 由预设/用户编写，预设文本中的自称按规则写死（见 D-V19-02 表）；**导入卡不携带旧式"自称女仆"**。
- **PersonaConfig 默认值**：`address_self` 默认从 `"女仆"` 改为 `""`（空 = 走 given_name 规则），保持字段存在（向后兼容，旧配置读入非空值时……见清理决策：非空且为 `"女仆"` 视为脏值 → 归一为空）。**不改 core.AppConfig 字段名**（`persona_address_self` 保留，默认值改 `""`，core/__init__.py:762、:907 env 读取不变）。

#### D-V19-02 7 预设命名表 + 鲸鱼娘设定补全（含授权边界）

| 预设（ROLE_PRESETS key，不变） | `name`（不变） | 新增 `given_name` | 自称（system_prompt 内文案） | 称呼主人 | 原自称 → 新 |
|---|---|---|---|---|---|
| 温柔女仆 | 温柔女仆 | `小铃` | 小铃 | 主人 | 女仆 → 小铃 |
| 鲸鱼娘 | 鲸鱼娘 | `小鲸` | 小鲸 | 小鱼干 / 主人（语境切换） | 本鲸、人家 → 小鲸 |
| 猫娘 | 猫娘 | `小咪` | 小咪 | 主人 | 本喵 → 小咪 |
| 雌小鬼 | 雌小鬼 | `铃奈` | 铃奈 | 杂鱼♡ / 笨蛋主人（保留） | 本小姐 → 铃奈 |
| 温柔姐姐 | 温柔姐姐 | `""` | 我 | 小主人 / 乖（保留） | 姐姐 → 我 |
| 毒舌博士 | 毒舌博士 | `""` | 我 | 这位朋友 / 同学（保留） | 不变 |
| 编程老手 | 编程老手 | `""` | 我 | 你（保留） | 不变 |

- `PRESET_ROLE_IDS`（page_role.py:231）不变；预设物化（:850 起）自动带 `given_name`。
- **默认预设修正**：`ROLE_PRESETS["温柔女仆"]["system_prompt"]`（:133-140）与 `PRISTINE_SYSTEM_PROMPT`（:117-123）同步为"自称小铃"版本；`is_pristine_role`（:375）判定逻辑不变（比对常量即可，因常量同步更新）。
- **鲸鱼娘设定补全**（:206-225 重写 system_prompt）：傲娇 + 懒 + 聪明、服从主人、**被叫"胖"炸毛回怼**（人设剧本 3 用例进测试）、白米饭执念、摸鱼/找外包梗；自称统一"小鲸"；称呼"小鱼干/主人"语境切换。
- **授权硬约束（R-L 之外的合规条款，R-K 诚实）**：只用现有 `preset_whale` 资产 + 自创名"小鲸"；**不得出现"溟月"字样、不得搬运原作者二创图**（原作者 CC BY-NC-SA 4.0 非商用）；About/doc 注明"形象与设定灵感来自社区二创，本作使用自创命名"；扫描断言进验收。

#### D-V19-03 "自称女仆"残留清理：13 处清单（按新规则统一）

已核实清单（实施前逐个复核行号；含 8 处 UI 文案类）：

| # | 类别 | 落点（已核行号） | 修正 |
|---|---|---|---|
| 1 | 配置默认值 | persona.py:15 `address_self="女仆"` | 默认改 `""`（D-V19-01） |
| 2 | system prompt | persona.py:35 `自称：{address_self}` | 按 given_name 规则生成自称句 |
| 3 | 配置默认值 | core/__init__.py:762 `persona_address_self="女仆"` | 改 `""` |
| 4 | 融合 prompt | agents.py:53 `自称：女仆。` | 改 `自称：{given_name or "我"}`（取 cfg.persona_given_name，缺省"我"） |
| 5 | 默认预设 | page_role.py:135 `自称「女仆」` | 改「自称小铃」 |
| 6 | 配置模板 | gui/config.yaml:15 `address_self: 女仆` | 改 `address_self: ""`（+ 增 `given_name: ""`） |
| 7 | 注释/文档模板 | gui/main.py:132-136（persona 模板 docstring） | 同步 |
| 8 | UI 文案 | widgets/tool_trace.py:281「女仆这就来向主人汇报」 | 改为中性表述（"任务全部完成，来向主人汇报啦"） |
| 9 | UI 文案 | chat_input_logic.py:65「女仆正在思考…」 | 改"正在思考…"（或按当前角色 given_name 渲染） |
| 10 | UI 文案 | chat_input_logic.py:80「女仆提前收尾」 | 同上（中性） |
| 11 | UI 文案 | chat_exporter.py:12 `ROLE_LABELS = {..."assistant": "女仆酱"}` | 改"助手"或按角色名 |
| 12 | UI 文案 | page_about.py:56「女仆编程师 — 您的专属 AI 编程助手」 | 改「码铃 — 您的专属 AI 编程助手」 |
| 13 | 文档 | README.md:221 `persona_address_self: "女仆"` | 同步为新示例 |

- 排除项（**保留，不算残留**）：theme_engine.py:139 主题名「女仆粉」（A 块被映射下线，文件保留，R-D）、maid.qss 注释、config.py:32 宠物形态注释、main.py 日记模块注释（"女仆日记"是功能名，非自称）、assets/ICON_MANIFEST.md。
- 注意：**"女仆"作为角色类别词继续存在**（角色卡名"温柔女仆"不变）——名实分离，不是去女仆化（PRD §7 澄清）。
- 统一来源建议：新增 `persona.self_reference(given_name, fallback="我")` 纯函数，UI 文案类（#8~#12）若需动态化则调用它；静态处直接改中性词（零耦合）。

### B 块

#### D-V19-04 新 `gui/fonts.py` 模块契约

```
FONT_IDS / FONT_IDS_BODY 常量（六项）
  resource_rounded（默认，正文/UI）｜huninn（仅标题/点缀）｜youyuan｜yahei｜kaiti｜dengxian
BUNDLED_FONTS: {id: {"files": [...], "role": "body"|"title", "family_hint": ...}}    # 文件在 gui/assets/fonts/
resolve_font_path(rel) -> Path|None      # get_resource_path("assets/fonts/" + rel)（⚠-2 路径）
register_bundled_fonts() -> Dict[str, str]   # addApplicationFont -> applicationFontFamilies(fid)[0] 取真实 family
                                             #   记录到 _REGISTERED_FAMILIES（真实名，不凭文件名猜）；失败不抛
font_family_chain(choice: str, scope: str = "body") -> str
                                             # body: "<真实family>, Microsoft YaHei, sans-serif"
                                             #   choice=huninn（title-only）在 scope="body" 时回落 resource_rounded
                                             # title: 若 choice=huninn 用粉圆真实 family，否则同 body
is_title_only(choice) -> bool                # Q-E4 守卫查询
default_font_choice() -> str                 # "resource_rounded"
```
- 零 Qt 顶层依赖原则沿用 role_card 先例？**不需要**——fonts.py 本就是 Qt 层模块，直接 `from gui.qt_compat import QFontDatabase`。

#### D-V19-05 字体接入：`theme_engine.load_theme` 单点 + fallback 链

- `load_theme` 内 `${font_family}` 的替换值改为 `fonts.font_family_chain(cfg.font_family, "body")`（读不到配置时用 `default_font_choice()`）；**新增 `${font_title}`** 替换为 `font_family_chain(choice, "title")`（Q-E4：粉圆只作用于标题位）。
- `app.setFont(QFont(chain.split(",")[0].strip(), 10))` 用链首（保持既有写法，只换取值来源）。
- `page_settings` 字体切换即时生效路径：写 `cfg.font_family` + `save()` → `theme_engine.load_theme(current_theme_name)`（复用既有重建链，零新机制）。
- **注册时机**：`main()` 中 `gui_config = GuiConfig.load()`（main.py:801）之后、`MainWindow(app_ctx)`（:885）之前调用 `fonts.register_bundled_fonts()`（try/except 不阻断；MainWindow.__init__ 内 load_theme 时 family 已就绪）。
- **优雅回退（R-K）**：字体文件缺失（打包疏漏）时 `register_bundled_fonts` 静默跳过 → family 链自动退到 `Microsoft YaHei` → 不崩、不方块；生僻字/emoji 由 Qt 字形回退到雅黑（R-L④）。

#### D-V19-06 子集化构建脚本 + 打包路径（Q-E5 裁决：GB2312 6763 + ASCII + 标点）

- 新 `tools/build_fonts.py`：
  - 字表 = GB2312 6763 全字 + ASCII(0x20-0x7E) + 中文标点（U+3000-303F、U+FF00-FFEF 常用项）；字表**生成**而非手抄（`--charset` 由脚本内置分类码表导出，保证可复现）。
  - `pyftsubset`：资源圆体 Regular + Medium（`requirement` 字表文件）；jf open 粉圆 子集（**标题常用字表**：界面标题字 + 常用成语 ≈ 800–1500 字，体积压到数百 KB）。
  - 产物 → `gui/assets/fonts/`（**⚠-2：spec 目标目录 `assets/fonts`，非 `_internal/fonts/`**）。
  - 依赖：`fonttools` + `brotli` **仅构建期**（不进 requirements 运行时、不进 exe）；脚本头部注释写明用法与源字体获取方式（官方仓库 clone 路径，不入库大文件）。
- **许可副本（R-L②）**：`gui/assets/fonts/OFL-Resource-Han-Rounded.txt`、`gui/assets/fonts/OFL-jf-open-huninn.txt`（随包，About 可读）+ 源树副本 `docs/third_party_licenses/`；`docs/THIRD_PARTY.md` 登记两条；`page_about.py` 开源组件表补两行（字体名 / 授权 OFL 1.1 / 来源仓库 / 用途）。
- **保留名称核对（R-L③，标"实施前必核"）**：构建前读官方 LICENSE 原文，确认是否有 Reserved Font Name；若声明保留名 → 子集产物 family 名按 OFL 要求处理（改名或以原名分发，二选一以原文为准），核对记录留档。
- 体积复核（验收项）：Regular+Medium ≈ 4–5MB + 粉圆 ≈ 0.3MB，实测值写入 CHANGELOG（R-K 不写未确认值）。

#### D-V19-07 粉圆守卫（Q-E4 裁决：显示但标注"仅标题/点缀" + 代码侧守卫）

- 设置页字体下拉：粉圆项文案 `jf open 粉圆（仅标题 / 点缀）`；选中时不改正文族，仅影响 `${font_title}` 位；`intent_notice`/提示条给"已作用于标题位；正文保持资源圆体"。
- 代码守卫：`fonts.font_family_chain("huninn", "body")` 强制返回资源圆体链（**单一收口点**，QSS 与 setFont 都走它 → 无法被误设为正文）。

#### D-V19-08 默认值与老用户切换策略（Q-E6 裁决：跟随默认升级）

- 新用户：`font_family` 默认 `"resource_rounded"`。
- 老用户（存档无 `font_family` 键）：`GuiConfig.load` 的 `hasattr` 循环天然跳过缺失键 → 取类默认 `"resource_rounded"` = **自动升级**；幼圆降为可选（下拉第 3 项）。
- 设置页给"切回幼圆"一键入口；**不做**版本号探测式迁移（零迁移成本）。

### A 块

#### D-V19-09 `THEME_DEFINITIONS` 增量四条目 + 键位对齐（R-D 合规论证）

- 新 id（共享知识常量，全项目唯一真值源）：`ui_minimal`（A 现代极简）/ `ui_cream`（B 温暖奶油）/ `ui_night`（C 深色夜间）/ `ui_whale`（D 鲸鱼娘深海）。
- 每条目结构**与现有一致**：`name / qss_file / colors / colors_dark / layout / font` + 两个新元字段：
  - `"dark_locked": True`（仅 ui_night → Q-E2 强制深色）
  - `"brand_persona": True`（仅 ui_whale → Q-E3 文案随人设）
- `colors` 键位**必须注册全部既有语义键**（`primary/primary_dark/secondary/accent/bg/bg_card/text/text_secondary/border/shadow/radius_*/text_on_accent/bg_light/disabled_*/surface_muted/text_hint/divider/focus_accent/pet_bubble_bg/state_ok/state_warn/spacing_*` + 语义键 `accent_light/bubble_user_bg/bubble_ai_bg/bubble_user_text/bubble_ai_text/chat_bg/chat_border`）——由既有 `_augment_theme_palettes()`（:682）自动补 `colors_dark` 与语义键（新条目**自动纳入**该装配链，零改动即生效）。
- **R-D 合规论证（"加皮肤不拆引擎"，PRD §7 澄清的落地口径）**：
  | 契约 | 状态 |
  |---|---|
  | `load_theme` 变量替换流程 / `${...}` 语法 | 保留（仅替换取值来源 + 增 `${font_title}` 一个键） |
  | `_active_palette` / `_custom_accent` 运行时 merge | 零改动 |
  | `set_theme_mode(light/dark/system)` 语义 | 零改动（C 风格强制深色由**调用侧**处理，见 D-V19-11） |
  | `theme_changed(str)` 信号签名 | 零改动 |
  | `get_color` / `get_layout_token` / `current_theme_name` | 零改动 |
  | 旧三主题（cute/minimal/maid）QSS 文件 | **保留**（读时映射，不删；R-D 明文） |
  | 旧配置值 | 读时映射（D-V19-10） |
  → 结论：四风格是 `THEME_DEFINITIONS` 的**增量条目 + 新增 QSS 文件**，非引擎重写。

#### D-V19-10 旧配置读时映射（Q-E1 裁决：不保留经典主题入口）

| 旧 `theme_name` | 新 id | 理由 |
|---|---|---|
| `minimal` | `ui_minimal` | 同为冷调浅色极简 |
| `maid` | `ui_cream` | 同粉调暖色系 |
| `cute` | `ui_cream` | 同粉调（PRD §Q-E1 建议值） |

- 实现：`ThemeEngine.load_theme` 入口处 `LEGACY_THEME_MAP` 归一（`theme_name = LEGACY_THEME_MAP.get(theme_name, theme_name)`），并在加载后把归一值回写 `GuiConfig.theme_name`（下次 save 落新值）；旧 QSS 文件保留在 `gui/themes/` 但**不出现在任何 UI 入口**。
- `theme_engine.THEME_DEFINITIONS` 中旧三键**是否移除**：**保留**（R-D + 防止旧 QSS 引用/回归测试断裂）；但设置页/onboarding/chat_panel 三处 UI 只列四风格。
- 边界：若存档值为未知字符串 → 回落 `ui_minimal`（默认风格，见 D-V19-12）。

#### D-V19-11 C 深色夜间：强制深色 + 选择器收起 + 离开恢复（Q-E2 裁决）

- 触发点：`load_theme("ui_night")` 前/后判定 `theme_def.get("dark_locked")`。
- 行为（**在调用侧收口，不动 `set_theme_mode` 语义**）：设置页/切换器统一走新 helper：
  - 进入 ui_night：记住用户原 `theme_mode` → 存 `cfg.theme_mode_before_night`（新键，默认 `""`）→ `cfg.theme_mode = "dark"` → `set_theme_mode("dark")`；外观模式下拉 `setEnabled(False)` + 提示"夜间风格为深色专属"。
  - 离开 ui_night：若 `theme_mode_before_night` 非空 → 恢复该值并 `set_theme_mode(原值)`；清空暂存键。
  - 两状态分别持久化（`theme_name=ui_night` + `theme_mode_before_night=<用户原模式>`），重进 C 风格不丢原设置。
- 引擎侧零新增状态（暂存键在 GuiConfig）；`_dark` 仍由 `_resolve_dark_effective()` 计算。

#### D-V19-12 四风格 QSS 组织 + 视觉稿变量映射

- 文件：`gui/themes/base.qss`（**增量**：补四风格新组件的公共选择器与 `${font_title}` 用法）+ 四个新 QSS：`ui_minimal.qss / ui_cream.qss / ui_night.qss / ui_whale.qss`（肤感层，按视觉稿还原）。spec datas 已覆盖 `gui/themes` 目录 → **新 QSS 自动进包**（零 spec 改动）。
- **视觉稿 CSS var → QSS token 映射表**（实施逐项对照）：

| 视觉稿变量 | QSS token | A 极简 | B 奶油 | C 夜间 | D 深海 |
|---|---|---|---|---|---|
| `--bg` | `${bg}` | #F7F7F8 | #FFF8F3 | #131114 | #EEF6FA |
| `--surface` | `${bg_card}` | #FFFFFF | #FFFFFF | #1C1920 | #FFFFFF |
| `--surface2` | `${surface_muted}` | #FBFBFC | #FFFBF8 | #211D26 | #F4FAFC |
| `--border` | `${border}` | #EBEBEF | #F5E6DC | #2C2733 | #D5E8F0 |
| `--text` | `${text}` | #1C1C1E | #3D2E2A | #F2EFF5 | #12303F |
| `--sub` | `${text_secondary}` | #8E8E93 | #A68B7E | #918A9C | #6A8A9A |
| `--accent` | `${accent}` / `${focus_accent}` | #E0457B | #FF8FA3 | #FF6B9D | #2E9BB5 |
| `--accent-soft` | `${bg_light}` / `${pet_bubble_bg}` | #FCEEF4 | #FFEEF1 | #3A2430 | #E0F2F7 |
| `--user-bg` | `${bubble_user_bg}` | #F0F0F3 | #FFE8EF | #2B2130 | #DFF0F8 |
| `--ai-bg` | `${bubble_ai_bg}` | #FFFFFF | #FFFFFF | #1F1B24 | #FFFFFF |
| `--shadow` | `${shadow}` | 0 1px 3px rgba(0,0,0,.05) | 0 6px 20px rgba(255,143,163,.13) | 0 2px 12px rgba(0,0,0,.35) | 0 4px 16px rgba(46,155,181,.12) |
| `--radius` | `radius_md/radius_lg` | 14px | 20px | 14px | 18px |
| （无） | `${text_hint}` | #A9A9B0 | #C0A79B | #6E6878 | #8AA9B8 |
| （无） | `${divider}` | #F0F0F3 | #F1E2D8 | #262230 | #E3F0F5 |
| （无） | `${text_on_accent}` | 不写死（默认白字，运行时由明度机制自动选黑/白） | 同左 | 同左 | 同左 |
| （无） | `${state_ok}/${state_warn}` | 沿用既有语义色 | 同 | 同 | 同 |

- layout token（spacing_*）沿用既有值（A/C 用 minimal 密度档，B/D 用 maid 密度档）；`radius_pill` 随 `--radius`。
- **用户气泡结构纪律（深浅一致）**：`--user-bg` 在**浅色与深色下都是"柔和中性底 / 同族深色底"**，accent **只做强调不复用为用户气泡实底**（D-V19-15 ① 修正的根因）；`bubble_user_text` 随之取同族浅字，不走 `#FFFFFF` 硬编码。
- D 风格专属点缀（气泡鲸鱼 / 浅海渐变）走 QSS `qlineargradient` + 现有 assets（**不新增图片资产**，R-L/Non-goals）。

#### D-V19-13 切换器三处落点 + 即时生效 + 编辑器明暗修正（⚠-3）

- ① 设置页「外观主题」区改造为「界面风格」：下拉（四项 + 预览色块 QToolButton）+ 保留外观模式与强调色盘；旧"快速切换按钮 ×3"（page_settings.py:117-129）替换为四风格色块。
- ② 聊天页顶栏（chat_panel.py `title_row`，:229-339）加风格快捷入口（图标按钮 → 四项小菜单，选中即切）。
- ③ onboarding.py:350/501 主题选择同步四风格（`theme_selected` 信号不变，仅选项与 id 换）。
- 即时生效：统一走 `_switch_theme(theme_id)`（复用既有：`theme_engine.load_theme` + `cfg.theme_name = id` + `cfg.save()`；**补 save 调用**，现状 :1405-1411 未 save，属既有缺口）。
- **⚠-3 修正**：新增 `ThemeEngine.is_dark_effective() -> bool`（返回 `self._dark`）；`page_editor._on_theme_changed` 改 `self._is_dark = engine.is_dark_effective() if engine else (theme_name == "cute")`；初始化同样改（page_editor.py:194）。其余 `theme_changed` 订户（page_plan:736 / page_toolbox:539 / page_memory_book 等）核查是否只做"刷新取色"（若是则零改动）。
- 状态栏主题标签（main_window.py:424 `theme_labels` 三键）扩为四风格 + 映射后旧值同步显示。

#### D-V19-14 D 风格品牌文案范围（Q-E3 裁决）

- 仅替换**界面自称 / 状态提示 / 欢迎语**口吻文案，来源 = C 块命名规则的运行时值（当前角色 `given_name`，取不到则"我"）；**窗口标题（"码铃"）/ 关于页产品名 / exe 名（maling）/ package 名 / NOTICE 类文案一律不变**。
- 实现：新增 `gui/brand_text.py`？→ 否（避免过度设计）。改为在既有文案点按"是否 D 风格"分支：`theme_engine.current_theme_name() == "ui_whale"` 时文案模板切换（欢迎语/状态 chip 等 3–5 处），模板内自称位取 `persona.self_reference(given_name)`。清单实施期核定并留档（与 D-V19-03 的 UI 文案点重合，可一次改到位）。

#### D-V19-15 深色变体对照表（Q-E7 裁决：架构/设计推导，**PM 已复核定稿**）

A/B/D 三风格按视觉稿色系推导（保持气质：极简冷灰深 / 奶油暖棕深 / 深海深蓝）：

> **PM 复核记录（v1.9 定稿）**：方向通过；1 项阻塞（深色下用户气泡对比度不达标）已修 + 2 项建议已采纳，详见下表与表后修正说明。**修完即可实施，无需再审。**

| token | A 极简·深 | B 奶油·深 | D 深海·深 |
|---|---|---|---|
| bg | #17171A | #201A17 | #0E1A21 |
| bg_card | #1F1F23 | #2A2320 | #14232C |
| surface_muted | #242429 | #312925 | #182A34 |
| border | #303036 | #453A33 | #24404E |
| text | #EDEDF0 | #F3E9E3 | #E2F1F7 |
| text_secondary | #9A9AA2 | #B9A79C | #8FAEBE |
| text_hint | #7E7E88 | #9A8072 | #6B8C9D |
| divider | #2A2A30 | #3B322C | #1D3641 |
| accent | #FF5E93 | #FF9FB2 | #4FC0DA |
| accent_light | #4A2434 | #4A2F34 | #16404D |
| bg_light | #2E2129 | #38292B | #12333E |
| focus_accent | #FF7AA6 | #FFB3C2 | #6AD2E8 |
| bubble_user_bg | #3A2430 | #4A2F34 | #12333E |
| bubble_ai_bg | #1C1C21 | #2A2320 | #13242D |
| bubble_user_text | #F2DCE6 | #F7E4E8 | #E2F1F7 |
| bubble_ai_text | #E8E8EC | #EFE3DC | #DCEDF5 |
| text_on_accent | **不写死** → 由 `derive_accent_palette` 按主色明度自动选黑/白 | 同左 | 同左 |
| chat_bg | #17171A（可选微调 #1A1A1E，见注③） | #241D1A | #0F1D25 |
| chat_border | #34343B | #4E4038 | #2A4A59 |
| pet_bubble_bg | #242429 | #312925 | #182A34 |
| shadow | rgba(0,0,0,.40) | rgba(0,0,0,.42) | rgba(0,0,0,.38) |
| state_ok / state_warn | #4FD18F / #E8B04C | 同左 | 同左 |

**PM 复核修正说明（本次改动）**

① **阻塞项已修 —— 深色用户气泡配色**：原设计 `bubble_user_bg = accent`（亮 accent 实底）+ 白字，对比度不达标（A ≈2.8:1 / B ≈1.9:1 几乎不可读 / D ≈2.1:1），且结构上偏离视觉稿浅色基准（浅色下用户气泡是柔和中性/浅色底 `${--user-bg}`，accent 只做强调不复用为气泡实底）。
改为**同族深色底 + 同族浅字**（PM 推荐方案①，结构一致）：
- A：`#FF5E93 → #3A2430` + 字色 `#F2DCE6`（≈10.8:1）
- B：`#FF9FB2 → #4A2F34` + 字色 `#F7E4E8`（≈9:1）
- D：`#4FC0DA → #12333E`（accent_light 同族）+ 字色 `#E2F1F7`（≈13:1）

② **`text_on_accent` 不写死 `#FFFFFF`**：交给 v1.4.3 既有"按主色相对亮度自动选黑/白"机制（`derive_accent_palette`，theme_engine.py:564）——深色下高亮 accent 自动取深字；写死白字会绕过该保护，叠加自定义强调色盘（用户选浅黄/浅青等高明度色）时复现不可读组合。

③ **`text_hint` 提亮一档**（placeholder 等小字稳过 4.5:1）：A `#71717A→#7E7E88`、B `#8C7264→#9A8072`、D `#5F7F8F→#6B8C9D`。

④ **实施提示（无需改值）**：深色下 `${shadow}` 视觉弱化属正常——层级主要由 `${border}` 表达，实施期不要误判为"阴影丢失"而回补强阴影。

⑤ **可选微调（非阻塞）**：A `chat_bg` 与 `bg` 同值（`#17171A`），可选调为 `#1A1A1E` 增强聊天区分区感；实施期视观感定，默认保持同值。

- C 深色夜间 `colors_dark == colors`（自身即深色；`dark_locked`）。
- 落法：写入四处 `_DARK_OVERRIDES`（theme_engine.py:588 字典增四个 key）或直接写进各条目 `colors_dark` —— **统一走 `_DARK_OVERRIDES` 增量**（与既有三主题同机制，`_augment_theme_palettes` 自动装配）。
- **本表经 PM 复核定稿**（阻塞项已修 + 建议项已采纳，见上方修正说明），**可直接实施，无需再审**；对照表入本文档留档。

---

## 3. 文件清单

### 新增

| 文件 | 内容 | 说明 |
|---|---|---|
| `gui/fonts.py` | 字体注册 / 真实 family / 家族链 / 粉圆守卫 | B 块核心 |
| `gui/themes/ui_minimal.qss` | A 现代极简肤感层 | 视觉稿还原 |
| `gui/themes/ui_cream.qss` | B 温暖奶油 | 同上 |
| `gui/themes/ui_night.qss` | C 深色夜间 | 同上 |
| `gui/themes/ui_whale.qss` | D 鲸鱼娘深海 | 同上 |
| `tools/build_fonts.py` | pyftsubset 子集化构建脚本（构建期） | 不入运行时 |
| `gui/assets/fonts/`（目录） | 子集字体产物 + OFL 许可副本 | spec datas 收集 |
| `docs/third_party_licenses/OFL-*.txt` | 许可全文副本（源树） | R-L② |
| `tests/test_v19_c.py` / `test_v19_b.py` / `test_v19_a.py` | 三批测试 | — |

### 修改

| 文件 | 改动 | 红线注意 |
|---|---|---|
| `gui/theme_engine.py` | +4 条目、`LEGACY_THEME_MAP`、`is_dark_effective()`、`${font_family}` 取值改造 + `${font_title}`、`_DARK_OVERRIDES` +4 | **契约零变更**（见 D-V19-09 表）；`_active_palette` 等不动 |
| `gui/config.py` | +`font_family`（默认 resource_rounded）、+`theme_mode_before_night`、load/save 同步 | 既有键不动 |
| `gui/main.py` | `register_bundled_fonts()`（:801 后） | 启动链顺序不动 |
| `gui/pages/page_settings.py` | 「界面风格」下拉+色块、字体下拉、占位/收起逻辑、`_switch_theme` 补 save | 外观模式/强调色盘链路不动 |
| `gui/widgets/chat_panel.py` | 顶栏风格快捷入口 | 顶栏其余按钮不动 |
| `gui/pages/onboarding.py` | 主题选项换四风格 id | 信号不变 |
| `gui/main_window.py` | `theme_labels` 扩四（+旧值兜底） | — |
| `gui/pages/page_editor.py` | `_is_dark` 改 `is_dark_effective()` | 只改判断来源 |
| `gui/pages/page_about.py` | 开源组件表 +2 字体条目；产品名文案（#12，D-V19-03） | — |
| `persona.py` | `PersonaConfig.given_name`、自称句生成、`self_reference()` | 字段增量 |
| `core/__init__.py` | `persona_address_self` 默认 `""`；+`persona_given_name`（env 读取） | 字段名不变 |
| `agents.py` | 融合 prompt 自称按规则（:53） | — |
| `gui/pages/page_role.py` | `Role.given_name`（模型/from_dict/to_dict）、`ROLE_PRESETS` +given_name 与自称文案、鲸鱼娘重写、`PRISTINE_*` 同步 | **v1.5.1 对齐链（:296/:1038）零语义变更** |
| `gui/role_card.py` | `EXPORT_FIELDS` +`given_name`、`parse_card` 读取、`card_summary_text` 呈现 | 白名单机制不动 |
| `gui/widgets/tool_trace.py` / `chat_input_logic.py` / `chat_exporter.py` | 文案清理（#8~#11） | 纯文案 |
| `gui/config.yaml` | persona 模板段 | — |
| `maid_coder_gui.spec` | datas +1（`('gui/assets/fonts','assets/fonts')`）、hiddenimports +`gui.fonts` | 目标目录按 ⚠-2 |
| `docs/THIRD_PARTY.md` / `README.md` / `CHANGELOG.md` | 字体登记 + 用法 + 版本条目 | R-K 如实 |

---

## 4. 数据结构

### 4.1 四风格 theme 条目（示例：ui_minimal）

```python
"ui_minimal": {
    "name": "现代极简",
    "qss_file": "themes/ui_minimal.qss",
    "colors": { "bg": "#F7F7F8", "bg_card": "#FFFFFF", "surface_muted": "#FBFBFC",
                "border": "#EBEBEF", "text": "#1C1C1E", "text_secondary": "#8E8E93",
                "text_hint": "#A9A9B0", "divider": "#F0F0F3",
                "accent": "#E0457B", "bg_light": "#FCEEF4", "focus_accent": "#E0457B",
                # text_on_accent 为注册默认值；设自定义强调色时由 derive_accent_palette
                # 按主色明度自动覆盖（不写死为最终值，见 D-V19-15 ②）
                "text_on_accent": "#FFFFFF", "bubble_user_bg": "#F0F0F3",
                "bubble_ai_bg": "#FFFFFF", "pet_bubble_bg": "#FCEEF4",
                "state_ok": "#3F9E6E", "state_warn": "#E0A02E",
                "radius_sm": "8px", "radius_md": "14px", "radius_lg": "20px", "radius_pill": "24px",
                "spacing_xs": "4px", "spacing_sm": "6px", "spacing_md": "10px", "spacing_lg": "16px" },
    "layout": { "radius_sm": 8, "radius_md": 14, "radius_lg": 20, "radius_pill": 24,
                "spacing_xs": 4, "spacing_sm": 6, "spacing_md": 10, "spacing_lg": 16 },
    "font": { "family": "Microsoft YaHei, Segoe UI", "code": "JetBrains Mono" },  # 实际由 fonts.py 覆盖
    # v1.9 新元字段
    # "dark_locked": True     仅 ui_night
    # "brand_persona": True   仅 ui_whale
}
```
（缺省元字段 = 不存在键，`theme_def.get("dark_locked")` 判空即 False，零破坏。）

### 4.2 字体配置项

| 键 | 值域 | 默认 |
|---|---|---|
| `GuiConfig.font_family` | `resource_rounded` / `huninn` / `youyuan` / `yahei` / `kaiti` / `dengxian` | `resource_rounded` |

`FONT_IDS` 常量表（`gui/fonts.py`）：
```python
{"resource_rounded": {"label": "资源圆体（默认）",    "scope": "body",  "bundled": True},
 "huninn":           {"label": "jf open 粉圆（仅标题 / 点缀）", "scope": "title", "bundled": True},
 "youyuan":          {"label": "幼圆",   "scope": "body", "bundled": False, "qt_family": "YouYuan"},
 "yahei":            {"label": "雅黑",   "scope": "body", "bundled": False, "qt_family": "Microsoft YaHei"},
 "kaiti":            {"label": "楷体",   "scope": "body", "bundled": False, "qt_family": "KaiTi"},
 "dengxian":         {"label": "等线",   "scope": "body", "bundled": False, "qt_family": "DengXian"}}
```

### 4.3 `given_name` 字段

| 位置 | 类型/默认 | 说明 |
|---|---|---|
| `Role.given_name` | str / `""` | 空 = 无名字 → 自称"我" |
| 角色卡 JSON | `"given_name": "小铃"` | v2 白名单新增；旧卡缺字段 → `""` |
| `PersonaConfig.given_name` / `AppConfig.persona_given_name` | str / `""` | env `MAID_PERSONA_GIVEN_NAME` |

### 4.4 旧配置映射表

| 键 | 旧值 | 新值 | 时机 |
|---|---|---|---|
| `theme_name` | cute / minimal / maid | ui_cream / ui_minimal / ui_cream | `load_theme` 读时归一 + 回写 |
| `font_family` | （不存在） | resource_rounded | `GuiConfig.load` 类默认（Q-E6） |
| `theme_mode` | light / dark / system | 不变 | C 风格进出时暂存/恢复（`theme_mode_before_night`） |

### 4.5 E7 深色变体对照表

见 **D-V19-15**（PM 已复核定稿：深色用户气泡对比度阻塞项已修 + `text_on_accent` 交自动明度选字 + `text_hint` 提亮）。

---

## 5. 任务分解（17 项，分批 C → B → A；A 分两小轮）

> 工作量对齐 PRD 合计 6.5–10 人日。

### 第一批 · C 块（1–1.5d，零依赖先行）

| ID | 任务 | 落点 | 交付 / 验证要点 | 人日 |
|---|---|---|---|---|
| V19-01 | `given_name` 字段 + 自称生成规则 | persona.py / core/__init__.py(:762,:907) / page_role.py Role(:526-595) | 7 预设 mock payload 自称 = 小铃/小鲸/小咪/铃奈/我/我/我；自建角色空名→"我"、有名→该名；人设标签零出现在自称位 | 0.4 |
| V19-02 | 7 预设命名落地 + 鲸鱼娘设定补全 | page_role.py ROLE_PRESETS(:129-226) / PRISTINE(:116-124) | 预设物化后 given_name 落盘；鲸鱼娘"被叫胖炸毛"剧本 3 用例、"小鱼干/主人"语境切换抽样评审 | 0.3 |
| V19-03 | 角色卡携带 `given_name` | role_card.py(:36,:179,:268) | 导出自称字段在卡内；旧卡缺字段→"我"零崩溃；预览摘要含名字；白名单外零泄漏断言 | 0.2 |
| V19-04 | 13 处残留清理（含 8 UI 文案） | 见 D-V19-03 清单 | 全树扫描"自称女仆 / 自称「女仆」"零命中；`address_self` 默认非"女仆"；产品名"码铃"不变 | 0.4 |
| V19-05 | C 批自测 | tests/test_v19_c.py | 上述断言 + 鲸鱼娘授权扫描（无"溟月"、无新二创图） | 0.2 |

### 第二批 · B 块（1.5–2.5d，四风格共同底座）

| ID | 任务 | 落点 | 交付 / 验证要点 | 人日 |
|---|---|---|---|---|
| V19-06 | `gui/fonts.py` | 新文件 | 六项常量；真实 family 取法（applicationFontFamilies）；家族链；粉圆 scope 守卫；缺文件不崩 | 0.5 |
| V19-07 | theme_engine 接入 + 启动注册 + 切换器 | theme_engine.py(:245-253) / main.py(:801 后) / page_settings.py | `${font_family}` 与 `${font_title}` 生效；`app.setFont` 用链首；六项切换即时生效 + 重启保持 | 0.5 |
| V19-08 | 构建脚本 + 子集产物 + 许可副本 | tools/build_fonts.py / gui/assets/fonts/ / docs/third_party_licenses/ / docs/THIRD_PARTY.md | 字表 GB2312 6763+ASCII+标点可复现生成；Regular+Medium ≈4–5MB + 粉圆 ≈0.3MB 实测留档；OFL 副本 2 份；保留名核对记录 | 0.5–1 |
| V19-09 | spec + About 字体条目 | maid_coder_gui.spec / page_about.py | datas `('gui/assets/fonts','assets/fonts')`；hiddenimports `gui.fonts`；About 可见两行 | 0.2 |
| V19-10 | B 批自测 + 打包核对 | tests/test_v19_b.py + onedir 冒烟 | 生僻字"龘"/emoji/文件名三类文本源无方块；缺字体优雅回退；粉圆守卫断言；包内取证真实 family | 0.3–0.5 |

### 第三批 · A 块（4–6d，**建议分两小轮**）

**小轮 1 · A/B/D 浅色三风格 + 引擎增量 + 切换器**

| ID | 任务 | 落点 | 交付 / 验证要点 | 人日 |
|---|---|---|---|---|
| V19-11 | 四条目增量 + 深色变体 + 旧值映射 | theme_engine.py(:49,:588,:682) | 四 id 加载成功；语义键齐备（`_augment_theme_palettes` 自动装配）；旧值归一 + 回写；`dark_locked/brand_persona` 元字段 | 0.5 |
| V19-12 | base.qss 增量 + ui_minimal/ui_cream/ui_whale 三 QSS | gui/themes/ | 视觉稿组件形态逐项对照（卡片/气泡/按钮/输入区/侧栏/会话项/chip）；无裸色（全走 token） | 2–2.5 |
| V19-13 | 切换器三处 + 即时生效 + 编辑器明暗修正 | page_settings.py(:103-151,:1400-1412) / chat_panel.py(:229-339) / onboarding.py(:350,:501) / main_window.py(:424) / page_editor.py(:194,:204) | 切换 <200ms 无闪烁无残留；重启保持；`_switch_theme` 补 save；`is_dark_effective()` 接入 | 0.5–0.7 |
| V19-14 | 小轮 1 全站截图回归 | 主窗/浮窗/设置/记忆中心 8 Tab/首页/角色页/对话框 | A/B/D×页面清单无漏改；强调色盘 × 浅深组合回归（v1.4.3 遍历先例）；红线扫描零命中 | 1–1.5 |

**小轮 2 · C 深色 + 收尾**

| ID | 任务 | 落点 | 交付 / 验证要点 | 人日 |
|---|---|---|---|---|
| V19-15 | ui_night.qss + 强制深色机制 | gui/themes/ui_night.qss / page_settings.py / config.py | 进入即深色 + 外观模式下拉收起 + 提示；离开恢复原模式；两状态分别持久化；重进不丢原设置 | 0.7–1 |
| V19-16 | D 风格文案随人设 + 全站组件复查 | 欢迎语/状态 chip 等 3–5 处 + page_memory_book 等订户 | D 风格下自称取 given_name；窗口标题/产品名/exe 名不变（断言）；其余 theme_changed 订户零回归 | 0.3–0.5 |
| V19-17 | 收尾：四风格红线扫描 + R-L 核对 + 文档 + 全量回归 + 打包 | 全局 | 四风格 × 全页面 R-A 扫描零命中；R-L 白名单/许可副本/保留名/fallback 四项留档；R-K 五核对点；v1.8.1 全量零回归；py_compile + pytest 双绿；CHANGELOG（体积如实）；dist 取证 | 0.5–1 |

**合计 6.5–10 人日**。裁剪顺序（PRD §9 承接）：A 的 D 风格 → B 的粉圆 → A 降为两风格；**C 块与 B 资源圆体不裁**。

---

## 6. 共享知识（团队必读）

1. **theme id 常量（唯一真值源）**：`ui_minimal / ui_cream / ui_night / ui_whale`；旧值仅存在于 `LEGACY_THEME_MAP`（读时映射）。UI 文案与代码**不得再出现 cute/minimal/maid 作为用户可见选项**。
2. **字体 id 常量**：`resource_rounded / huninn / youyuan / yahei / kaiti / dengxian`；正文家族一律经 `fonts.font_family_chain(choice, "body")`（**唯一收口**，禁止硬编码 family 字符串）。
3. **QSS 变量命名纪律**：新 QSS **只允许**引用 `${...}` token（颜色 + layout），token 键必须已在四条目 `colors/layout` 注册；新增语义键须同时进 `_SEMANTIC_LIGHT_DEFAULTS`/`_SEMANTIC_DARK_DEFAULTS`（或条目内显式给深浅两值）。
4. **theme_engine 契约保留区**：`load_theme` 变量替换 / `_active_palette` / `_custom_accent` / `derive_accent_palette` / `set_theme_mode` / `theme_changed(str)` / `get_color` / `get_layout_token`——签名与语义**零变更**；新需求一律"加皮肤/加键"，不改机制。
5. **`given_name` 语义**：名字 ≠ 人设标签；自称位只接受 `given_name` 或"我"；UI 文案动态化统一走 `persona.self_reference(given_name)`。
6. **字体注册时机**：QApplication → GuiConfig.load → `register_bundled_fonts()` → MainWindow（load_theme 前必须已注册，否则 family 取不到）。
7. **路径纪律（⚠-2）**：资源相对路径必须与 `gui/` 下源码路径一致（`assets/fonts/...`），spec datas 目标目录 = 该相对路径。
8. **D 风格文案边界**：只改口吻文案；产品标识（码铃 / exe / package / 窗口标题）永不变。

---

## 7. 打包评估

- **运行时零新增第三方依赖**（fonttools 仅构建期；字体是数据文件不是 Python 依赖）。
- 体积：**+4.5–5.5MB**（资源圆体 Regular+Medium 子集 4–5MB + 粉圆子集 ≈0.3MB），相对整包可忽略（调研报告 §4.2）。
- spec 动作：
  - `datas` += `('gui/assets/fonts', 'assets/fonts')`（**目标 `assets/fonts`**，⚠-2）；四新 QSS 由既有 `('gui/themes','themes')` 自动覆盖 → **零新增**；
  - `hiddenimports` += `'gui.fonts'`（新增模块，防静态分析漏收）；
  - 许可副本随包（放 `gui/assets/fonts/` 内即可被上面 datas 收集）。
- **R-K 五项核对点（PRD §8 照录 + 落地）**：①四风格 QSS 全部落包且缺文件时降级不崩（`_build_default_qss` 兜底既有）；②字体子集落 `_internal/assets/fonts/` 且注册成功（包内取证真实 family）；③粉圆"仅标题"守卫在包内生效；④OFL 许可副本 + 版权声明 + About 字体条目可见；⑤缺字体时雅黑回退不崩。
- **R-L 四项核对**：仅内置 OFL 字体（资源圆体 / jf open 粉圆）/ 许可副本与声明随包 / 子集保留名核对记录留档 / 生僻字 fallback 无方块。

---

## 8. 待明确（不阻塞立项）

| # | 问题 | 建议 |
|---|---|---|
| E-1 | ~~E7 深色变体对照表（D-V19-15）~~ | **已关闭**——PM 复核定稿（阻塞项已修 + 2 建议已采纳），可直接实施 |
| E-2 | 资源圆体 / 粉圆的**真实 family name** | 构建期用 `applicationFontFamilies` 实测后填入 `BUNDLED_FONTS` 的 `family_hint`（代码不猜名） |
| E-3 | 粉圆标题子集字表范围 | 首版"界面标题常用字 + 常用成语"≈800–1500 字，脚本内以字表文件固化 |
| E-4 | jf open 粉圆精确字库体积 | 调研报告标注"未取得"（§8.1）——READEME/CHANGELOG **不得写确定值**（R-K） |
| E-5 | 源字体获取方式（不入库大文件） | spec 头部注明官方仓库 clone 路径 + 手工放置约定；构建脚本校验存在性 |
| E-6 | D 风格文案清单最终条数（3–5 处） | 与 D-V19-03 的 UI 文案点合并实施，清单留档 |

---

## 9. 红线对照（本期强制口径）

| 红线 | 落点 |
|---|---|
| **R-A 无焦虑** | 四风格仅改壳不改展示语义——首页 Token 卡 / 状态 chip / 记忆中心 8 Tab 在四风格逐一切换验证；风格切换不得引入任何新数值化组件；扫描词表（心情/好感/token/进度/断签/倒数）四风格 × 全页面零命中 |
| **R-D 只增量** | 见 D-V19-09 契约表：引擎机制零改、旧三 QSS 保留、旧配置读时映射、`theme_changed` 签名不变；B 块单点接入；C 块字段增量（旧数据零迁移） |
| **R-I 隐私** | 字体/风格/命名设置仅存本地（GuiConfig）；内置字体不含任何用户数据；鲸鱼娘二创授权边界（D-V19-02）作为合规条款一并执行 |
| **R-K 发布诚实** | 文档 ↔ dist 逐项核对（四风格 QSS / 字体子集 / 粉圆守卫 / 许可副本 / 缺字体回退五核对点）；调研"未确认项"（粉圆体积）不得写成确定值；CHANGELOG 无自评分 |
| **R-L 字体授权合规（新增）** | ①仅 OFL 1.1（资源圆体 / jf open 粉圆），B/C/D 级（MiSans / HarmonyOS Sans / OPPO Sans / 阿里系 / 乐米系 / 阿里健康体 / 站酷非开源版）**一律不内置**；②许可副本 + 版权声明随包（`gui/assets/fonts/` + `docs/third_party_licenses/` + `docs/THIRD_PARTY.md` + About 条目）；③子集属"修改"——沿用 OFL、保留版权声明、**保留名核对留档**；④生僻字 fallback 雅黑，绝不方块 |

---

## 10. DoD（对照 PRD §10 逐条）

1. **四风格立住（A）**：A/B/C/D 全站覆盖、逐页截图核对表留档、无漏改页；视觉稿组件形态一致；切换即时生效（<200ms）+ 持久化；浅深与强调色盘两维组合零回归；旧配置读时映射不断档。
2. **字体精致且安全（B）**：资源圆体默认（Regular 正文 / Medium 强调层次可辨）、粉圆仅标题（代码守卫）、4 系统字体可选、生僻字/emoji/文件名三类文本源回退无方块；切换即时 + 持久化；OFL 副本与声明在包内；构建脚本可复现。
3. **自称有人味（C）**：7 预设自称 = 小铃/小鲸/小咪/铃奈/我/我/我；人设标签永不进自称位；"自称女仆"零残留；自建角色与角色卡 v2 兼容；鲸鱼娘炸毛梗与授权边界合规（无"溟月"、无新二创图）。
4. **红线归零**：R-A/R-D/R-I/R-K/R-L 全条对照；四风格 × 全页面红线扫描零命中；字体授权白名单无越界。
5. **零回归 + 打包**：v1.8.1 全量功能（记忆图谱/情绪/场景/回应约定/影像记忆/群聊/Pi）零回归；py_compile + pytest 双绿；运行时零新增第三方依赖、体积增量仅字体 ≈5MB 且文档如实标注；R-K 五核对点留档。

---

## 11. IS_PASS 自评

| 维度 | 结论 |
|---|---|
| PRD 全覆盖 | PASS——A/B/C 三块全项有任务；Q-E1~Q-E7 全部落为裁决口径（E1 映射表 / E2 强制深色+收起+恢复 / E3 文案范围 / E4 粉圆守卫 / E5 GB2312 6763 / E6 自动切圆体 / E7 深色对照表 **PM 已复核定稿**）；Non-goals 全承接 |
| 源码核实 | PASS——全部对接点行号经 v1.8.1 源码逐行核实；**5 处 PRD↔源码偏差（⚠-1~⚠-5）已标红并给出裁决**（theme_name 键名 / spec 目标目录 / page_editor 硬编码明暗 / 三处切换器 / fonttools 固化） |
| 红线兼容 | PASS——R-D 契约保留表逐项列明（"加皮肤不拆引擎"有论证）；R-A 四风格逐页扫描为验收硬项；R-L 四项核对（白名单/副本/保留名/fallback）落地 |
| 零重构 | PASS——theme_engine 仅"增条目 + 增方法 + 增一个替换键"；旧三 QSS 与旧配置值保留；C 块为字段增量 |
| 工作量 | PASS——17 任务合计 6.5–10 人日与 PRD 对齐；A 块拆两小轮（A/B/D 浅色 → C 深色 + 收尾）；裁剪顺序承接 PRD §9 |
| 打包 | PASS——运行时零新依赖；datas +1、hiddenimports +1；体积 +4.5–5.5MB 已复核；R-K/R-L 核对点留档 |

**IS_PASS = YES**，可移交排期（E-7 深色对照表已 PM 复核定稿，无待办阻塞）。

> 文档结束 · 高见远 · 2026-09-10 · 基线 v1.8.1 · 功能面零改动 · 群聊与 Pi 引擎零触碰
