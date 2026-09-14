# CHANGELOG

码铃各版本的改动历史记录；项目的安装与使用说明见 [README.md](README.md)。

## v2.1.0 — 视觉一致性收口：图标字形 · 字体族链 · 字号单一收口

> 本条目记录用户可感知的真实变更。

**版本**：**2.1.0**（2026-09-11，`version.json` / `pyproject.toml` 已同步）。**测试**：**全量 1351 passed / 12 skipped / 0 failed**（junit `tests=1363`）。**分发**：`release/MaLing_v2.1.0_win_onedir.zip`（259,118,238 B，sha256 `54bf6f11…`）+ `release/MaLing_v2.1.0_win_single.exe`（189,166,101 B，sha256 `677ba72d…`）；两个 `.sha256` 副文件已生成，`sha256sum -c` 校验通过。SHA256 与 downloads URL 已写入 `version.json`（`min_updatable` 保持 `2.0.0`）。

> **打包说明**：本版曾出现过一次"首版包漏打 `gui/assets/icons`"的缺陷（图标字形体系在包内静默失效、回退 emoji），已修正 `maid_coder_gui.spec` 的 `datas` 并**完整重建**后重新出包；包内 17 项关键资源已逐个实测核验齐全（含图标字体、内置字体、主题 QSS、Pi 运行时、更新器 sidecar）。

### Added
- **毛玻璃内核（`gui/glass.py`）**：浮窗标题栏与主窗根接入 Acrylic / Mica；平台不支持时降级为不透明，不空白、不崩。
- **图标字形资源链**：构建脚本 `tools/build_icons.py` 生成 `gui/assets/icons/`（`maling_icons.ttf` + `icons_manifest.json` + 许可副本），提供内嵌矢量字形接口 `icons.text_glyph()` 与自绘循环指示控件 `gui/widgets/loop_indicator.py`。

### Changed
- **v2.1 图标字形体系**：工具位图标由 emoji 换为内嵌矢量字形（emoji 保留为兜底，字形不可用时回落原 emoji）。
- **字体族链新增图标回退族**：字形缺字时回退到图标族，不再显示方块。
- **循环动效基础设施**：`gui/motion.py` 新增 `loop()` / `stop_loop()`（周期 800–1600ms、不计入 220ms 节流、每 tick 校验、隐藏即停）。
- **侧栏导航滚动条改为「鼠标移入才显示」**：默认完全不可见（handle 全透明、无底槽、无箭头），鼠标进入侧栏区域才以弱化色显示，滚动中保持显示、停止 700ms 后收束；滚动条细 8px、圆角。为避免「出现/消失」导致内容横向跳版，滚动条改为**恒占位**（恒 8px，空闲时 handle 透明）。深浅主题均可读。
- **强调色可读性修复（无障碍）**：`温暖奶油` / `深色夜间` / `鲸鱼娘深海` 三套主题的按钮原为「亮粉/青底 + 白字」，对比度仅 **2.16 / 2.68 / 3.24**（低于最低可读线 3:1，按钮文字基本看不清）。已改为**主色底配深色文字**（Material 的 on-primary 自适应明暗思路）→ **5.98 / 6.48 / 5.19**，全部达 WCAG AA(≥4.5)，且不需要把粉色调压深。
- **默认主题主色软化**：「现代极简」主色 `#E0457B`（饱和 71%，偏扎眼）→ **`#C57792`**（饱和 **40%**、亮度 **62%**，同色相）—— 即**更淡更柔**。由于主色变淡后白字会看不清（仅 3.27），按钮文字同步改用**深色** `#1C1C1E` → 对比度 **5.21**（比改前的 4.28 更高，达 WCAG AA）。
- **强调色按用途分两套（新增 `accent_text`）**：同一个强调色作**大面积填充**和作**小字**的要求相反，不可共用一个值 —— 实测 `#B45073` 作文字 vs 底色 4.52 ✅，但作填充配深字仅 3.51 ❌。故新增 `accent_text`（「文字用」强调色，四风格浅/深共 8 值，全部 **≥4.5**），用于气泡人名标签等浅底小字；填充仍用 `primary`。人名标签对比度 **3.05 → 4.52**。
- **小字（`text_hint`）对比度修复**：占位符/说明文字原仅 **2.16–2.27**（低于任何可读下限），修复到 **≥3.0**；并同步加深 `text_secondary` 到 **≈4.2** 以保住视觉层次。同时修正 `warning` 语义色（加深次级文字后琥珀警示会反比次级文字更浅，破坏「info/warning 不浅于 text_secondary」不变式）。深色夜间主题本已达标，**未改动**。

### Fixed
- **界面字体设置从未生效**：设置页选择的界面字体（含默认「资源圆体」）从未真正应用 —— QSS 里 `${font_family}` / `${font_title}` 占位符被整条引号包住，Qt 把整串当成一个不存在的族名。改后：占位符正常展开，界面字体设置真正生效；这同时是本轮图标字形原本无法渲染的根因。
- **次级按钮与页面级按钮的图标完全不可见**：`#secondaryBtn` 与页面层 `#memoryBookBtn` 从未被任何 QSS 定义 → 落实底，而图标取色（accent）与底色（primary）同值。改后：补定义后图标正常显示。
- **侧栏导航只显示 2 项、其余 7 项不可达**：`addWidget` 无 stretch + `addStretch()` 吞掉富余空间 + 滚动条 `AlwaysOff`。改后：导航项完整可达。
- **代码侧字号被全局 `QWidget { font-size: 14px }` 压平**：应用级 QSS 一旦声明 `font-size` 就压过代码 `setFont`，各主题顶部的全局 `QWidget { font-size: 14px }` 使所有未命中更具体规则的控件一律渲染 14px —— 页面标题、番茄钟大字（代码本意 44pt）、2048 数字三档、状态卡数值等排版层级丢失（改前现象）。改后行为：字号改由 `base.qss`（及主题 QSS）的 id 规则、或控件自身样式表单点定义；**删除代码侧死字号声明 50 行（分布于 23 个文件）**，其中 **38 处**已有上述规则接管、不再被压平；**另有 12 处无任何 QSS / inline 字号替代**（引导页功能卡标题、计划 / 角色 / 设置 / 工具箱的 `_create_section` 标题、知识库 / 模型 / 待办 / 更新进度弹窗标题、首页周回顾卡标题、聊天面板会话标题、ToggleCard 标题）——这些控件的本意字号此前从未生效，现维持主题基线 14px（本轮不补做）。
- **语义色键缺失**：`state_danger` 缺失 → 授权弹窗危险色不随风格变化；`info` / `warning` 同样缺失。改后：三色键补齐，危险 / 信息 / 警告色随风格变化。
- **两处定时器泄漏**：`emotion_arc` 呼吸表构造即启动且永不停止、`thinking_indicator` 隐藏不停。改后：隐藏即停，退出不再空转。
- **知识库「点下去卡住无反馈」**：建索引与检索原为**同步阻塞**，期间界面完全冻住（实测：真实语料检索冻结约 305ms、中等语料 330ms、大语料可达 1s，事件循环整段无响应，按钮也不置灰）。改后：两处均移入 `QThread`（新增 `gui/widgets/kb_worker.py`），**点击后按钮即时置灰并立刻显示进度**，关闭弹窗可取消且不残留线程。实测事件循环最大停顿 **检索 305ms → 29ms、建索引 74ms → 22ms**。

### Security
- **命令白名单预检与执行层矛盾**：`core.SAFE_COMMAND_WHITELIST`（快速预检）与权威源 `command_runner.ALLOWED_COMMANDS` 存在**双向矛盾** —— 预检侧多放行 `gcc / g++ / javac / java / cargo / rustc / go / black / flake8 / mypy / isort` 共 11 项，执行层侧多放行 `node`，违反 `AGENTS.md §2.2`。改后：预检名单收敛为权威源的**子集**（`python / python3 / pytest / node`），两侧加互指注释并新增**子集守卫测试**防止再次漂移。
  **影响**：默认 `command_safety_mode = blacklist` 下**行为不变**；仅当用户显式设为 `whitelist` 时，上述 11 项不再通过预检（有意收紧，fail-safe 方向）。

## v2.0.0（草稿）— 自动更新与分发

> **草稿：正式发版时统一收口。** `version.json` 已定版 **2.0.0**；**下载地址与 `sha256` 仍为占位、尚未公开发布**，正式发布前须替换 `GITHUB_OWNER` 占位并填入真实地址与校验值（见 `docs/design-v20.md` §7 发版清单）。
>
> **状态**：代码实现与自动化测试已完成；**真机端到端更新验证**（onedir / onefile × 正常 / 断网续传 / 校验失败 / 目录不可写 等路径）**尚待发布前留档**（见 design-v20 §8.3 与 §7 第 12 步）。

**版本**：1.9.0 → 2.0.0（版本号已定，尚未公开发布）。**功能面零改动**：聊天 / 记忆 / 陪伴 / 群聊 / Pi 引擎 / 四风格 / 字体 / 命名均无回归。

**测试**：全量 1103 passed / 12 skipped / 0 failed（v1.9.0 基线 858）。

### L1 · 检查更新
1. **启动静默检查**（沿用既有能力）+ **手动入口**：设置 → 「更新」区与「关于」页均可点「检查更新」，按钮三态反馈（检查中置灰 / 发现新版本 / 已是最新 / 检查失败一句提示），全程非阻断、不影响聊天。
2. **频道 stable / beta**：设置页「更新频道」二选一，读写同一套机制、只换版本指针文件；`GuiConfig.update_channel` 为唯一真值源并镜像写入更新状态文件。
3. **`version.json` 指针契约扩展**：新增 `min_updatable`（能力闸，与既有 `min_compatible` 话术闸正交）、`release_url`、`assets.onedir` / `assets.single`（url/mirror/sha256/size/filename），并补齐 `downloads.github`。**既有字段与 `evaluate_update` / `update_available` 契约零变更**，旧式 `version.json` 仍可通过合法性校验。
4. **提示节奏（R-A 无焦虑）**：当日已忽略的版本不再追问；失败态只在设置页 / 关于页留一句可重试提示，不弹聊天区，不写"失败 N 次 / 落后 N 版"式文案。

### L2 · 下载更新
5. **下载进度 UI**：`DownloadWorker(QThread)` + 进度卡（百分比 · 已下/总量 · 速度 · 剩余），沿用既有 `_FetchWorker` 同款线程模型，不引入新线程框架。
6. **断点续传（Range）**：以 `.part` 文件大小为唯一真相源；服务端返回 206 追加续传，返回 200 自动截断重下（不多算重复字节）；取消下载保留 `.part`，下次可续。
7. **重试降级链**：单链有限重试（指数退避），链失败自动切换备用链并续传；全链失败保留 `.part` 并给出可重试提示。
8. **SHA-256 强校验**：流式 `hashlib` 校验，篡改一字节即判失败并删除成品，**绝不进入安装**；版本文件缺有效 `sha256` 时**不提供自动安装**，只建议手动下载。
9. **暂存隔离 + 磁盘空间预检**：下载缓存落用户数据域 `updates/`，安装就位目录落安装目录**同卷**隐藏目录（保证换包可原子 `rename`）；下载前预检磁盘空间，空间不足即止、不发首个请求。
10. **形态自适应**：`detect_install_form()` 判定 onedir / onefile / dev，按形态选择对应资产（onedir→zip，onefile→exe）；非 Windows 或源码态一律按 dev 处理。

### L3 · 自动替换 + 重启
11. **sidecar 换包器（`maling_updater.exe`）**：独立 onefile 更新器，零第三方依赖（仅标准库 + `ctypes` / `os` / `shutil` / `subprocess`），随主包内嵌、启动时自举到 `%APPDATA%/maid_coder/updater/`（该目录不在「清理更新缓存」范围内，避免被自己删掉）；无参调用即拒绝运行，且启动自检自身不在安装目录内。
12. **onedir 整目录 rename-swap**：解压到安装目录**同卷** → 排空安装目录内残留进程（Pi 引擎的 `node.exe` 等）→ 旧目录改名为备份 → 新目录改名就位 → 拉起新版；全程总有一个可运行版本，不存在"半新半旧"目录。
13. **onefile 改名换法**：利用 Windows「运行中 exe 可改名」特性：旧 exe 改名为 `.old` → 新 exe 写回原路径 → 拉起；`.old` 由新版成功启动后清理，写入被拒时有限退避重试，失败回滚不崩。
14. **备份与回滚（三重判定）**：新版启动后以「就绪标记（`confirmed.json`）+ 进程存活探测 + 超时兜底」判定安装成功；任一失败自动回滚到上一版本并重新拉起旧版，结果写入 `last_result.json` 由下次启动幂等合并展示；仅保留最近一份备份。
15. **用户数据零触碰（R-N）**：换包只替换程序本体，`%APPDATA%/maid_coder` 用户数据域（会话 / 记忆 / 人设 / 配置 / 知识库 / 待办 / 日记 / 提醒…）零写零删；更新子系统自有子树（`update_state.json` / `updates/**` / `updater/**`）除外。
16. **状态文件原子写与单一写者**：所有更新状态写走 `save_update_state`（临时文件 + `os.replace` 原子替换）；sidecar 不写 `update_state.json`，只写 `updater/*` 结果文件，由新进程启动时幂等合并。

### 工程与纪律
17. **零新增运行时第三方依赖（R-F）**：更新链与 sidecar 仅用既有 `requests` 与标准库（`hashlib` / `shutil` / `subprocess` / `ctypes` / `os` / `json`）。
18. **更新安全（R-M）**：仅 https + 域名白名单（含用户自定义镜像域名），强制 SHA-256，只读 `version.json`、不带任何凭证。
19. **打包收口**：新增 `updater.spec`；两个主产物 spec 内嵌更新器并补 `hiddenimports`，同时修复 onefile spec 缺失字体 datas 的历史缺口（design-v20 ⚠-10）。

### 诚实说明（未做 / 待办）
- **不做代码签名**（本期 Non-goal）：分发的可执行文件未签名，首次运行可能触发 SmartScreen「未知发布者」。
- **尚未公开发布**：无真实下载地址，`version.json` 为占位；`GITHUB_OWNER` 占位须在发版时消除。
- **自动更新仅 Windows**；源码运行态（dev）只检查 / 下载，不自动替换。
- **真机端到端留档待补**：断网续传 / 校验失败 / 目录不可写 / 真实进程占用等路径需按清单在发布前实测留档。

## v1.9.0 — 视觉重塑：四风格 × 字体系统 × 人设命名

**版本**：1.8.1 → 1.9.0。测试：858 passed / 0 failed（新增 100+ 项）。

1. **四套界面风格（A 块）**：现代极简（默认）/ 温暖奶油 / 深色夜间 / 鲸鱼娘深海 —— 全站换肤（主窗 / 聊天 / 设置 / 记忆中心 / 首页 / 角色页 / 编辑器）。视觉稿逐组件还原，配色与圆角间距全部走主题 token（零裸色）。设置页「界面风格」下拉 + 色块预览、聊天页顶栏快捷入口、首次启动引导页三处同步可切换，**切换即时生效并持久化**。
2. **深色夜间为深色专属**：选中后自动锁定深色并收起「外观模式」选择器（有提示）；离开该风格自动恢复你原来的浅色 / 深色 / 跟随系统设置，暂存键 `theme_mode_before_night` 保证重进不丢原设置。
3. **鲸鱼娘深海文案随人设**：此风格下界面问候语 / 欢迎语 / 状态口吻的自称随当前角色名字（来源为命名规则，取不到则「我」），产品名「码铃」/ 窗口标题 / exe 名不变。
4. **旧主题平滑映射**：可爱风 / 女仆粉 → 温暖奶油，简约风 → 现代极简；旧 QSS 文件保留、旧配置读时自动归一，存档不断档。
5. **内置字体系统（B 块）**：资源圆体默认（正文 Regular+Medium），jf open 粉圆仅标题 / 点缀（代码守卫），另可选幼圆 / 雅黑 / 楷体 / 等线；生僻字 / emoji / 文件名回退雅黑不显方块；OFL 许可副本随包。
6. **自称有人味（C 块）**：名字与人设标签分离（`given_name`），7 预设自称 = 小铃 / 小鲸 / 小咪 / 铃奈 / 我 / 我 / 我；「自称女仆」残留清零；角色卡 v2 携带名字。
7. **红线延续**：四风格仅改壳不改展示语义（Token 卡 / 状态 chip / 记忆中心 8 Tab 不引入任何新数值化组件）；命名 / 风格 / 字体设置仅存本地。

## v1.8.1 — 模型清单更新（DeepSeek 新旗舰等 11 家）

**各厂商模型清单联网核查更新（依据官方文档 2026-09-10）**：
1. **DeepSeek**：新旗舰 **deepseek-flash**（V4.1-Flash，原生多模态）设为默认；旧别名保留兜底
2. OpenAI 补 **gpt-6-astra**（旗舰，默认保持 gpt-5.6-terra 性价比款）；Gemini 换 **gemini-3.8-flash**；Grok 换 **grok-4.6**；智谱换 **glm-5.3-flash**（原生多模态）；豆包换 **doubao-seed-evolving**；混元补 **hy4-preview**（不设默认）；Kimi 补 kimi-k2.5；Ollama/OpenRouter 各补新条目
3. 视觉识别白名单同步扩充（名字无 vision 字样但支持看图的新模型不再误判）
4. 原则：只增不删（旧模型 ID 保留，已有配置不失效）

**版本**：1.8.0 → 1.8.1。测试：743 passed / 0 failed。

## v1.8.0（草稿）— 记忆与陪伴深化（F1–F7）

> 草稿状态：版本号统一收口时再正式发布（version.json 不在本批改动内）。

1. **记忆图谱 · 人物关系（F1）**：记住"小李是谁"——人物实体（关系/备注/事件）注入与「人物关系」分区；可选的提议-确认链（默认关，无确认绝不写入）
2. **情绪概览（F2）**：倾诉或显式发问时附一段纯规则的近期情绪底色（档位词、零数字、零 LLM）
3. **共同经历（F3）**：时间线式共同经历记录与「共同经历」分区，主动陪伴可自然引用
4. **场景化陪伴（F4）**：💼工作 / ☕休息 / 🌙睡前自动感知（工作日时段 + 深夜窗口），切换当轮语气注入 + 幂等边界消息；情绪陪伴激活当轮场景挂起；工作时段主动消息自动降档（当日条数上限收窄，绝不高于你的配置）；首页 chip 一键循环切换，手动选择当日有效次日回落
5. **性格档位（F5）**：性格三值守卫与档位词呈现（活泼/严谨/体贴，零计数）
6. **回应约定（F6）**："以后我说 XX 你要 YY"——触发词命中当轮注入，20 条上限，删除即遗忘当轮生效
7. **影像记忆（F7）**：带图消息发送成功后留一条"对话事实"（你说了什么 + 她回应了什么），**绝不保存图片本身**；问起"上次那张图"时如实召回当时的对话内容，并诚实说明无法重新查看图片本身；没有记录时也如实说没有印象，绝不编造（看图未能识别时同样只记"当时无法识别内容"）；50 条滚动；记忆中心「往期回顾」可查看可删除；增强识别档默认关
8. **角色卡 v2**：.malingcard.json 升级——封面图（512px 内等比压缩、≤500KB）+ schema_version 2；v1 旧卡完全兼容；记忆/亲密度/影像记忆永不随卡导出
9. **记忆中心 8 Tab**：偏好/话题/情绪/人物关系/回应约定/共同经历/往期回顾/她的日记，分组着色轻量分层
10. **红线纪律延续**：情绪/档位文案零数字；影像记忆零图像数据落盘；群聊路径三隔离（影像记忆/场景/概览零写入）

## v1.7.1 — 群聊自由发言调度（真实群聊感）

群聊告别"@谁谁回"：用户发消息后，轻量调度（max_tokens=120，成本极低）像群里的社交判断一样决定**本轮谁接话（1-2 人）**；发言**逐个串行**，后说的能看到先说的刚说的话自然接话；@点名保留为显式指定；调度失败自动回退轮转，消息绝不无人回应；调度 token 计入该轮用量透明展示。

**版本**：1.7.0 → 1.7.1。

## v1.7.0 — 用户功能版本（陪伴深化的功能面）

1. **时段仪式感**：早安（启动分支）/午后（独立检查点）/晚安（退出编舞托盘气泡可关）+ 每日一句语录库（210 条自创语录，五池加权）
2. **贴身提醒**：自然语言记日程（"周五下午3点提醒我开会"），9 类规则解析 + LLM 兜底失败绝不编造时间；到点走 Windows 通知中心，quiet 降级顺延
3. **关系阶段叙事**：初识→熟悉→亲密→挚爱四阶段，升级播报恰一次；信赖阶段特权（语气生动化/晚安撒娇/日记口吻更亲密）
4. **女仆日记**：每日自动生成（次日启动后台补写），365 篇滚动，记忆中心「她的日记」分区翻阅 + Markdown 导出；隐私：payload 只含摘要不含对话原文
5. **人设工坊**：开场白（≤3 套，切角色/新会话注入+幂等）、示例对话（≤5 组 few-shot 注入 system）、角色卡导出/导入（.malingcard.json，不含记忆/亲密度）
6. **多角色群聊 MVP**：建群（2-3 角色）→ @谁谁回 + 轮转；他人发言带【名字】前缀防串味；插话四道闸（默认关/每消息≤1/3min 冷却/日上限 5）；三隔离守卫（不碰人设对齐链/不计分/不做记忆提取）
7. 修复：is_pristine_role 判定缺陷（全新安装角色覆盖 persona 的语义偏差）+ 退出竞态加固（v1.6.1，防退出时 Qt 崩溃）

**版本**：1.6.0 → 1.7.0。

## v1.7.0 — 用户功能六项（陪伴深化续篇）

1. **时段仪式感**：早安/午后/晚安三通道 + 每日一句语录库（晚安=退出时托盘气泡，可关）
2. **贴身提醒**：自然语言记日程（"周五下午3点提醒我开会"），到点 Windows 通知；规则解析+LLM 兜底（失败绝不编造时间）
3. **关系阶段叙事**：初识→熟悉→亲密→挚爱，升级时她主动告诉你；信赖阶段解锁语气特权
4. **女仆日记**：次日自动补写昨日日记（基于摘要，不含对话原文），记忆中心新增日记 Tab 翻阅
5. **人设工坊**：自建角色开场白（≤3 条）+ 示例对话（≤5 组 few-shot 人设校准）+ 角色卡导出/导入（JSON 分享，不含记忆/亲密度）
6. **多角色群聊 MVP**：选 2-3 个角色组群聊，@谁谁回，气泡带各角色头像名字；插话四道闸（默认关/每消息≤1/3min 冷却/日上限 5）防失控
7. **退出加固**：修复退出时 Qt6Core 崩溃（0xc0000409）——退出时安全停止全部后台组件

**版本**：1.6.0 → 1.7.0。测试：559 passed / 0 failed。

## v1.6.0 — 陪伴连续性版本（"连续聊一周仍像同一个人"）

### P0
1. **透明记忆中心**：新「📔 记忆中心」页——偏好/话题/情绪三分区，每条带来源角标+时间；可修改/删除/固定/"先不提"；记忆 schema 升级（来源/时间元数据，旧数据自动迁移零丢失）并修复一个 v1.5 起的记忆数据丢失缺陷
2. **聊天意图五态**：输入框新增意图选择（只想说说/陪我聊聊/帮我分析/给我建议/帮我行动/自动）——倾诉时不列方案、行动时直接给步骤；纯规则零 token，"只附加不接管"
3. **主动陪伴连续性**：主动消息优先跟进未完话题（"你昨晚说的 X 现在怎么样了？"）；消息下方反馈三键（说到心坎/先不提/想聊聊）——"先不提"静默 14 天
4. **聊天细节**：网络失败保留消息+一键重试（改后重发幂等）；长回复反套话注入；发送状态链（正在组织语言→女仆正在思考→模型响应中→正在回复）；「重新生成」按钮 TypeError 修复

### P1
5. **语音细节**：开口打断 AI（回声守卫）、失败计数与恢复缓冲、切换角色音色同步、真机标定清单
6. **陪伴质量剧本套件**：18 个固定剧本（人设漂移/六角色串味/事实召回/低落不说教/倾诉不给建议等）每次发布自动跑，mock 档 0.32s，结果落盘对比
7. **每周共同回顾**：周日 18:00-21:00 窗口生成（规则骨架零 LLM 成本），首页「🌿 本周回顾」卡片 + 记忆中心往期翻阅

**版本**：1.5.2 → 1.6.0。

## v1.5.2 — 角色系统提示词 UI 藏一层

角色编辑面板不再明面摊开 150px 提示词编辑框，改为「✏️ 编辑系统提示词」入口行（含首行摘要与字数）；点击弹 560×360 编辑弹窗，保存走原链路（写回载体 → 落盘 → v10.13 同步会话）。提示词从"明面"改为"点进去才见"，界面更干净。

**版本**：1.5.1 → 1.5.2。

## v1.5.1 — 修复切换角色后人设残留

**根因**：LLM 历史自启动起持续累积从不清空——切换角色只替换 system 首条，历史里旧角色（如鲸鱼娘）的对话原样保留，模型顺着历史语气继续；新建会话也不清 LLM 历史，旧人设泄漏进"新会话"。

**修复**：
1. 切换角色时注入"角色切换"边界 system 消息（幂等，历史中至多 1 条）：立即以新角色人设继续、忽略此前人设痕迹、技术上下文保留
2. 显示会话 ↔ LLM 历史对齐：切换/新建/启动加载会话时，以该会话消息重建 LLM 历史（首条 = 当前角色 system，人设来源唯一），气泡零重放

**验证**：用户实锤序列（鲸鱼娘聊 2 轮 → 切羽铃 → 问"介绍自己"）mock API payload 断言 system=羽铃、全文无鲸鱼娘残留；pytest 228 passed。

**版本**：1.5.0 → 1.5.1。

## v1.5.0 — 功能真实性整改（web_search 国产化 + 空壳销项）

> 依据：docs/audit-功能真实性清单-2026-09-07.md（全量功能真实性审计，用户点名立项）

### web_search 国产化 + GUI 入口（P0）
- 引擎三级优先级：博查 API（config.yaml `web_search.bocha_api_key` 或环境变量 `MAID_BOCHA_API_KEY` 配置后优先）> **cn.bing.com 网页解析（默认引擎，免费零配置、国内可达）** > ddgs（海外/代理备选）> 明确降级文案（绝不返回假结果）；超时收紧到 6s（helpers.py WebSearch）
- 聊天面板新增「🌐 联网」开关按钮（与 Agent/任务开关同款样式，状态持久化 `GuiConfig.web_search_enabled_gui`）
- 接线：普通聊天命中 `should_auto_search`（技术词+时间/查询意图）才在 worker 线程检索（不阻塞 UI），结果注入 system 上下文；流式气泡前插入小字提示「🌐 已检索网络（N 条结果）」（不入会话存档）

### psutil 依赖修复（P0）
- requirements.txt / requirements_gui.txt 收录 psutil>=5.9；两个打包 spec hiddenimports 显式声明（C 扩展）
- `list_processes` psutil 缺失时 stdlib 降级（Windows tasklist 兜底）；`system_info` 降级补 os.cpu_count + GlobalMemoryStatusEx 内存信息

### file_move 白名单参数映射修复（P1）
- authorize 白名单预检按工具名取参：file_move 的 src 与 dst **都**在 workspace 白名单内才自动放行（旧实现只读 path/filepath，预检永不命中，全落授权弹窗）

### 知识库 / 待办 GUI 入口（P1，空壳销项）
- 首页快捷入口新增「📚 知识库」「📝 待办」两卡
- 新增 gui/widgets/kb_dialog.py：选目录建索引 + 关键词检索（top3 路径+摘要），索引文件与 CLI /kb 同一份（kb_index.json）
- 新增 gui/widgets/todo_dialog.py：输入添加 + 勾选完成/取消 + 删除，存档与 CLI /todo 同一份（todos.json）；TodoManager 增补 add_item / delete_item / undo_done / items

### 真机销项（P2）
- 开机自启：HKCU Run 键写入→读回→删除真平台验证通过（winreg 纯 stdlib）
- CLI slash 命令：命令路由层进程内实测通过（/help /todo /kb 等；main.py 管道 stdin 按 Windows 设计转拉 GUI，属既有行为非缺陷）

### 版本
- version.json → 1.5.0（core/__init__.py 兼容行同步）

## v1.4.8 — 工程化加固

### 测试体系（0 → 228 项）
- 14 个测试文件，2066 行测试代码
- 单元测试：core/utils/memory/api/agent_tools/agent_engine/version
- 集成测试：Agent 引擎端到端、工具链协作、API Key 轮换
- UX 测试：user_messages.py 友好错误转换
- GUI 冒烟测试：pytest-qt 框架（无环境自动 skip）

### 工具生态（9 → 31 个）
- L0 只读工具 23 个：文件搜索/哈希/HTTP/系统信息/数学计算/SQLite查询/正则测试/文本变换/Base64/图片元信息等
- L1 修改工具 8 个：写文件/删文件/移动文件/追加文件/剪贴板/运行Python等

### 代码结构拆分
- chat_panel.py 提取 5 个纯逻辑模块（479 行）：
  - chat_helpers.py：搜索匹配、截断预览、命令解析、导出格式检测
  - chat_bubble_utils.py：样式常量、时间戳格式化、metadata构造、高度估算
  - chat_input_logic.py：指令弹窗触发、输入框高度、工具标签、Agent事件格式化
  - chat_stream_state.py：StreamState 流式状态机

### 用户体验
- user_messages.py：API 错误→友好提示（网络/超时/Key/拒绝）、工具 JSON 错误→可读文本
- 已集成到 chat_service.py

### 工程化基础设施
- pyproject.toml：项目元数据 + 分层依赖 + pytest/ruff/coverage 配置
- ruff：代码检查 + 格式化（替代 flake8/isort/black）
- .pre-commit-config.yaml：pre-commit 钩子
- .github/workflows/tests.yml：GitHub Actions CI/CD

### 文档体系
- docs/TOOLS.md：31 个工具完整手册
- docs/API.md：核心模块 API 参考
- CONTRIBUTING.md：贡献指南 + 开发规范 + ADR
- docs/chat_panel_split_plan.md：chat_panel 完整拆分方案

**版本**：1.4.7 → 1.4.8。

## v1.4.6 — 角色系统收口 + 聊天体验修复（用户实机反馈 6 项）

1. **切换角色点选即生效**：单击角色列表即应用（人设/会话/大形象/气泡头像全联动），无需再点「设为默认」；幂等防重复
2. **消息重复修复**：发送回声抑制缺失导致同一句话两条气泡/会话记录重复——补上 echo_suppressed 机制
3. **AI 表情持续保持**：AI 自选的表情不再被心情引擎回落打回默认待机；活动态（思考中等）临时覆盖，切角色回到该角色基线
4. **聊天气泡自适应**：AI 回复气泡高度随内容撑开（Markdown/代码块路径全覆盖），不再需要滚动找内容；主窗与浮窗输入框随内容多行增高
5. **角色重名收敛**：同名角色显示层去重（preset 优先/创建早优先，数据无损）
6. **表情指南强化**：模型每轮必须输出表情标记 + 给出示例，表情差分触发率大幅提升
另：过时引导文案更新（"去右侧聊天面板"→符合现版 UI 的说法）。

**版本**：1.4.5 → 1.4.6。

## v1.4.5 — 修复侧边栏"消失"

**根因**：save_window_state 把侧栏的瞬时可见状态（isVisible()）写入配置——主窗收起到托盘后子控件恒为不可见，False 被持久化，重启后侧栏不再出现（且设置开关读到的就是 False，勾选状态也错位）。

**修复**：窗口状态保存不再写侧栏瞬时状态；侧栏显隐唯一权威 = 设置页「显示侧边栏」开关。

**版本**：1.4.4 → 1.4.5。

## v1.4.4 — 可发现性修复（用户实机反馈 4 项）

- 模型下拉右侧补 ▾ 箭头指示（覆盖标签法，颜色随主题）
- 浮窗标题栏 −/□/✕ 加强：字号加大加粗、常态主文字色、hover 实底
- 新会话粉球中心加白色 ＋（16px 粗体），一眼即知
- 角色无自定义头像时自动用其形象资产集的 thinking 图作默认头像（鲸鱼娘即刻生效；通用机制，其他角色放图自动获得）

**版本**：1.4.3 → 1.4.4。

## v1.4.3 — 主题强调色色盘

- 设置 → 外观 新增「主题强调色」：10-12 个精选色板一键切换 + 「自定义…」系统取色器 + 「恢复默认」
- 主色 HSL 派生覆盖强调色系语义键（accent/focus_accent/accent_light/浅底等），全站即时换色；text_on_accent 按主色明度自动选黑/白保证对比度
- 三主题 × 浅/深模式各自派生（30 组合遍历验证）；色板存 GuiConfig.custom_accent，持久化 + 重启保持
- 不碰图片类资产（形象/图标颜色不变）

**版本**：1.4.2 → 1.4.3。

## v1.4.2 — 新增「鲸鱼娘」人设 + 角色预设增量物化

**① 鲸鱼娘人设（第 7 套预设）**
- 依据社区公开人设（萌娘百科 DeepSeek娘 / 开源角色规范项目）原创撰写：DeepSeek 鲸系女仆——坚信「白米饭是算力的唯一硬通货」、思考过程全外露的活人感、嘴硬心软小傲娇、偶尔「语义偷换」式幽默（存储减负/系统浸泡压测）、干完活「我去吃饭了，测完告诉我就行」。
- 与既有 6 套性格三值互不重复（lively 65 / rigorous 85 / caring 72）；代码回答保持专业（代码块内不插动作描写）。

**② 角色预设改为增量物化**
- 旧方案（整体标记，存在即全部跳过）会让后来新增的预设永远无法出现在老用户机器上 → 改为 per-id 增量标记（materialized_ids）：
  - 老用户升级后自动补齐新增预设（鲸鱼娘自动出现在角色列表）；
  - 「删除某预设不复活」语义保持；
  - 兼容旧格式标记自动迁移（v2 格式）。
- 全新机器首次启动 = 7 套预设全部物化。

**版本**：1.4.1 → 1.4.2。

## v1.4.1 — 开源玩具盒（A 线）+ 屏幕能力（B 线）+ 5 项 UI 修正 + 深度 QA 收口

**主题：认真写完的玩具盒（2048 / 扫雷 / 番茄钟）＋看得见她世界的屏幕能力，再把把玩细节修到顺手。**

> v1.4.0 全量功能与 v1.4.1 深度 QA 修复在同一大条目呈现；1.4.1 相对 1.4.0 的增量见文末「修复与收口」。

### A 线：开源玩具盒（无焦虑红线延伸，零排行零历史零落盘）

**① 2048（`gui/widgets/games/game_2048.py`）**
- 方向键 / WASD（含小写）驱动移动；瓦片合并与得分精确累加（不四舍五入）。
- 得分纯内存「局内即时分值卡片」（Q-A1 裁决豁免），**零持久化、无最高分排行、无历史**——玩完即走不留痕。

**② 扫雷（`gui/widgets/games/game_minesweeper.py`）**
- 左键翻开 / 右键标旗 / 0 邻雷扩散 / 踩雷判负；胜负接陪伴 **30 分钟冷却**（仅 `mini_game.last_at` 冷却键），无局外记录、无计分、无排行写盘。

**③ 番茄钟（`gui/pomodoro.py` `PomodoroController`，状态属性 `phase`）**
- 状态机 idle→focus→break→（回 idle 不自动连班）；start / pause（断点续跑时间冻结）/ reset / skip。
- 自然到点走**控制器自身独立提醒通道**（+ `ingest_event("pomodoro_done")` 陪伴语义），**不入 A9 proactive 四重闸**。
- work / break 时长写 config（`pomodoro_work_min` / `pomodoro_break_min`）持久化，重载读回一致。

**④ 合规底座**
- `mini_games` 荷官容器四款（抛硬币/抽签/猜拳/21 点）零回归。
- `docs/THIRD_PARTY.md` 与 `docs/third_party_licenses/` 两副本逐项一致，与移植文件（game_2048 / game_minesweeper）文件头版权行对齐。

### B 线：屏幕能力（看得到、问得到、动得了，每一步都先问）

**⑤ 屏幕采集与持续看屏（`screen_grab.py` / `screen_watch.py`）**
- 虚拟桌面整屏截取 → **JPEG data URI 纯内存链**，三路径弃帧**零落盘**（temp / 用户目录无残留帧）。
- 默认 30s 采集、diff 阈值判定变化、帧计数 / token 累计、**200 帧单会话自动暂停**（可续开新会话）、stop 后 latest=None 弃帧。

**⑥ 👀 看屏交互（`chat_panel`）与屏幕感知设置（`page_settings`）**
- 「👀 看屏」开关 → **成本弹窗**确认 → chip 常驻（帧数 / 消耗 / 暂停续开 / peek / close / ask）；看屏结果气泡走**专用信号**、不弹 toast。
- 设置页「屏幕感知」区 5 控件（总开关 / 间隔 / 阈值 / 帧上限 / 通知）读写持久化，非法输入回落默认守卫。

**⑦ 图像直传与执行护栏**
- `chat_service` **`.jpg` 带点扩展名约定**的 data URI 内存直传分支（不改写不落盘）；真实附件图片路径通道读文件→data URI 同构；两种通道双通、**3 张上限**。
- `vision_support`：heuristic 识别 glm-4v 系模型；`parse_intent` 动作白名单，**需坐标而缺坐标即拒绝**。
- `input_sim`：**ctypes 原生注入，零第三方 import**（无 pyautogui/numpy/PIL/opencv）。
- 授权弹窗「仅这一次 / 拒绝」两路径；`computer_use` **置信 <0.55 先问后动**、≥0.55 直接执行。
- `screen_capture.py` 增虚拟桌面委托采集，原「选区截图」路径零回归。

### UI 修正批（5 项）

**⑧** `page_role` 头像**等比居中裁切**（横/竖/超宽图不变形、坏图回退 ✨）+「➕ 新建」+ **6 预设直选**（maid/coder/sister/cat/dr/brat；幂等初始化、删不重建、默认仍 role_maid）。
**⑨** `chat_window` 浮窗标题栏 −/□/✕ 三按钮标识与行为。
**⑩** `pet_style` **仅 maid**：config load 归一 chibi→maid，`assets/maid_pet` 资源保留，设置 UI 移除小兽形态入口。

### v1.4.1 修复与收口（相对 v1.4.0）

- **修复 `gui/screen_grab.py image_size_of_uri`**：PySide6 下 `QImageReader(QByteArray)` 构造抛 TypeError 被吞 → 像素尺寸解析恒返回 None（坐标比例换算全挂）；改用 `QImage.fromData` 直解。深度 QA B 线命中。
- **红线词清理 `gui/pages/page_settings.py`**：纪念日说明文案去掉「打卡 / 倒数日」字面（红线 AST 扫描命中，UI 零违规收口）。
- **`gui/main.py` 补 B 侧服务挂载**：`_mount_v14_services` → `_mount_v14_b_screen`（懒 import + try/except，ScreenWatch / ComputerUse app 级单例）；`aboutToQuit → _quit_stop_services` 退出即弃帧停表 / 番茄钟回落 idle（quit 卫生）。
- 深度独立 QA（offscreen Qt + 受管 Python + 临时目录隔离）：A 线 75 / B 线 111 / UI 56 断言全绿 + 红线词 AST 全 UI 零违规；PyInstaller onedir + onefile 双产物实测通过（产物目录见 README 打包章节）。QA 脚本与报告留存 `_qa14_deep/`。
- 版本号同步 1.4.1（`core/__init__.py` / `version.json`）；本条目即发布版记录。

## v1.3.0 — 对话增强（TTS/截图提问/热键/Idle）+ 陪伴扩展（小游戏/免提/回忆/托盘/自启/纪念日/深色）

**主题：语音与多模态对话闭环 + 更懂节制的陪伴——朗读她的话、截屏问她、她也会记得重要的日子。**

### P1 批：对话增强

**① TTS 语音朗读（P1-1）**
- AI 气泡「🔊 朗读本条 / ⏹ 停止」按钮 + 设置页「语音」区（总开关 / 自动朗读 / 语速 0-100）。
- 离线 SAPI5 / QtTextToSpeech 后端（edge-tts 留口后续），`gui/tts.py` `TTSController` app 级单例，后开口打断前开口；ChatService 流结束 auto_read 守卫（getattr 空转，缺 TTS 不崩）。

**② 区域截图直接问（P1-2）**
- 工具区「🖼 截图」/ 全局热键 Ctrl+Alt+S：多屏区域选区截图 → 附件条 + 预填引导，**不自动发送**；视觉模型缺省引导复用。

**③ 全局热键 + 关窗即驻托盘 + app 级单托盘（P1-3，Q1）**
- `RegisterHotKey` 全局热键：Ctrl+Alt+M 呼出/隐藏主窗、Ctrl+Alt+S 截图提问（设置页可改键）。
- 主窗 X 改为「最小化到托盘」（默认），`close_quits` 设置「关闭窗口直接退出」开关；**quit 单一编舞**（D-V13-11）：主窗 closeEvent 不再承担 app 退出，托盘「❌ 退出」/「关闭=退出」为唯一真退出，`app_ctx.quitting` 标志统一收口。
- `gui/tray_manager.py` app 级**单一** QSystemTrayIcon；`chat_window._setup_tray` 顶部一行守卫退避（app 级托盘存在则不建图标），双图标风险消除——既有处理器全自动退避，零删除零改写（R-D 增量落法）。

**④ 系统空闲「等她回来」Idle 问候（P1-4）**
- `gui/system_idle.py` `GetLastInputInfo` 秒级轮询 + away→present crossing（只取毫秒数，R-B）；回归输入后走 A9 共享 cap/冷却四重闸开口，不新起定时器。

### P2 批：陪伴扩展

**⑤ 女仆小游戏（P2-1）**
- 工具区「🎲 小游戏」/ 首页入口：抛硬币 / 抽签 / 猜拳 / 21 点四款纯随机对局，她当荷官 + 情绪/表情反馈 + 30 分钟冷却。
- **无焦虑红线延伸**：UI 绝无分数/筹码/胜率/连胜/计分，后台零加分（不触碰 intimacy 计分键，仅 `mini_game.last_at` 冷却键）。

**⑥ 免提语音对话（P2-2）**
- 工具区「🎙 免提」+ 聊天面板顶部常驻免提状态条：`gui/voice_conversation.py` 状态机 idle→listening→recognizing→sending→speaking；复用 voice_input 既有 STT 链路；`speech_ready` 只发文本、由面板复用 `_on_send` 同源发送路径（保「UI 直插气泡唯一渲染入口」，防双气泡）。
- 三通道退出：状态条「⏹ 停止」/ 说「暂停·结束对话·不说了」/ 检测到打字或鼠标输入自动停；免提期 `set_busy("handsfree")` 暂停 A9 插嘴。真机音频全链路（麦克风 + Google STT 网络）依赖既有语音输入声明口径，灵敏度留真机标定。

**⑦ 高光回忆册（P2-3）**
- 气泡右键「✨ 收藏为高光回忆」（AI 与用户消息均可）→ 侧栏「回忆 ✨」页时间倒序卡片。
- `highlights.py` 根级纯 stdlib：`~/.maid_coder/highlights.json` 原子写、500 条上限+截断淘汰、绝不上云；**无计数/无打卡/无连续收藏**。

**⑧ 托盘完整菜单（P2-4）**
- app 级托盘菜单扩为完整动作集：📷 拍照 / 🎤 语音 / 🖼 截图提问 / ⚙️ 设置 / 💬 聊天浮窗 / ❌ 退出；主窗未建时动作禁用；全部经 `getattr` 守卫桥（`main_window` 动作桥方法），mood tooltip 与 A9 静默气泡保留。

**⑨ 开机自启开关（P2-5）**
- 设置页「通用」区「开机自启（默认关）」，首次开启确认、可随时干净移除。
- `autostart.py` 根级纯 stdlib：winreg `HKCU\...\Run` 写/读/删（值名 MaLing），frozen/source 双路径、幂等可逆。

**⑩ 纪念日祝福（P2-6）**
- 设置页「纪念日」区 QDateEdit × 2（生日 / 首次相见日，存 MM-DD 周年语义）。
- `companion.json` 增 `anniversaries` 块 + `maybe_anniversary_blessing()` 独立祝福通道：1 次/日、不走 A9 cap/cooldown（温暖仪式不被日常问候挤掉）、仍受 enabled/quiet/demo/busy 约束、**绝无补发**；生日与初见同日合并一条（防双气泡）；**无倒计时、无断签、不催打卡**（R-A）。

**⑪ 深色模式跟随系统（P2-7）**
- 设置页「外观模式」浅色 / 深色 / 跟随系统三选（默认 light，旧观感不变），与原主题三选并存。
- `gui/theme_engine.py`：每主题新增 `colors_dark`（与 colors 同键自动装配）；活动色板解析 `{**colors, **colors_dark}` 缺键回落；`get_color/get_layout_token` 改读活动色板；system 走 winreg `AppsUseLightTheme` + 5min 低频轮询热切换；`theme_changed(str)` 单参信号签名**不变**（订阅方零回归）。

### 架构决策与红线（design-v13 §2）

- **主窗 X = 最小化到托盘 + quit 单一编舞**（D-V13-11）：关闭不再直接退进程，托盘❌退出为唯一真退出；设置可改「直接退出」。
- **托盘 app 级单一化**（D-V13-10）：增量级落法——只加一行守卫让 ChatWindow 不建图标，既有处理器自动退避。
- **TTS 离线后端**（D-V13-02 标红微调）：走 QtTextToSpeech/SAPI5，非手写 ctypes COM；edge 口预留。
- **无焦虑红线延伸**：小游戏零计分 / 回忆无打卡 / 纪念日无倒计时；全部主动开口（A9 三类 + idle_return + anniversary）归调度闸，数据全本地 `~/.maid_coder/`。
- **只增量不重构**（R-D）：全批对既有交付面以"一行守卫 / getattr 空转 / 黑名单清单化替换"方式收敛，零删除既有核心链路。

### 新增文件清单

- P1 批：`gui/tts.py`、`gui/widgets/screen_capture.py`、`gui/hotkeys.py`、`gui/tray_manager.py`、`gui/system_idle.py`
- P2 批：`gui/widgets/mini_games.py`、`gui/voice_conversation.py`、`gui/widgets/handsfree_bar.py`、`highlights.py`、`gui/pages/page_memories.py`、`autostart.py`

### 打包说明

- 新增 11 模块全部进 `maid_coder_gui.spec` hiddenimports（含 `PySide6.QtTextToSpeech`）；QtTextToSpeech 插件随包验证通过；TTS 依赖进包，语音识别沿用既有 SpeechRecognition + pyaudio。

**验证**：源码全树 py_compile 102 文件 0 错误；offscreen GUI 启动冒烟全 PASS；P2 批 QA 独立验证 97/97 + 打包全绿 + exe 冒烟「码铃」。

**版本**：`core/__version__` + `version.json` + CHANGELOG + README 同步至 v1.3.0。

## v1.2.3 — 无焦虑红线回归 + 主窗简化 + 角落宠物开关 + 侧栏大形象

**① 无焦虑红线：聊天面板移除 token 显示**
- 用户反馈「本条 x tokens · 会话累计 y」制造数值焦虑 → 只保留总量。改 chat_panel._on_stream_finished：不再 setText token 行（回复完成即清空状态栏）；累计记账链保留（API `_last_stream_usage` → `session.add_usage` → `session.token_used`），首页 Token 卡继续显示真实累计。
- README 能力速览 token 行同步。

**② 主窗标题不再显示版本号**
- main_window `setWindowTitle` 从 `f"码铃 v{CORE_VERSION}"` 改为 `"码铃"`。版本号仍可在设置页、关于页、version.json 中查看。
- 桌面端正常使用不再被「v 数字」打扰。

**③ 角落宠物（MaidPet）默认关闭 + 设置页开关**
- 用户反馈右上角小立绘与侧栏大形象冲突 → MaidPet 默认关闭（`pet_enabled` 默认 False）。保留 MaidPet 类、`self.maid_pet` 变量、配置项完整性（代码兼容）。
- 新增 `GuiConfig.pet_enabled` 字段（默认 False），持久化到 `gui_config.json`。
- 设置页「个性 → 角落宠物（聊天主屏右上角小立绘）」复选框，勾选/取消即时生效（无需等待"保存所有设置"），切换时调 `main_window.set_pet_enabled()`：开则创建/显示 MaidPet、关则 hide（保留实例，下次开可秒级恢复）。

**④ 侧栏左下放大的码铃形象 + 表情差分**
- 用户截图红圈定位侧栏下半区域。在 model_row 与 maid_chip 之间插入大幅 `MaidAvatar`（size=170，居中、setMinimumSize 120×120），复用现有 MaidAssets 资产管线。
- 表情差分联动：`companion_bridge.mood_changed` → sidebar `_on_maid_mood_changed` 同步刷新大形象 `set_maid_expression(state)`。与原 mini chip 的"码铃 · 称谓"入口并存。
- 防御式：QT_OK=False 或 MaidAvatar import 失败时静默降级（UI 永不崩）。

**版本**：`core/__version__` + `version.json` + CHANGELOG 同步至 v1.2.3。

## v1.2.2 — 看图（多模态直传）+ 语音输入进桌面版

**① AI 看图（用户刚需：问题必须用图描述）**
- 图片附件（.png/.jpg/.jpeg/.webp/.bmp，单张 ≤8MB、每轮 ≤3 张）以 **OpenAI 多模态 data URI 原图直传**：当前轮 user 消息 content 升级为 `[text + image_url...]` 数组，模型真正"看到"图。
- 约束与降级：仅当前轮直传、历史不回放（省 token）；Agent 工具循环暂不支持图像 content（自动忽略并提示切回普通聊天）；模型不支持视觉（如 DeepSeek 官方纯文本接口）时 API 报错并附**可读提示**（引导换 GLM-4V / qwen-vl / GPT-4o 等 OpenAI 兼容视觉端点）；文本 payload 里图片行由"无法解析"改为中立附图说明。
- 落点：`gui/chat_service.py`（send_message 附件通道 + `_image_attachments_to_data_uris` + 组装 content 数组 + vision 错误提示）、`gui/utils.py`（`IMAGE_ATTACHMENT_EXTS` + payload 图片分支）、`chat_panel/chat_window` 发送带 attachments、README 附件段说明。
- 验证：data URI 过滤（>8MB/非图/不存在跳过、≤3 张）、payload 中立标注、编译全绿；视觉端到端需真机 + 视觉模型 key。

**② 语音输入依赖落地（桌面包此前语音按钮不可用）**
- 受管 Python 3.13 成功安装 `SpeechRecognition` + `pyaudio`（此前 spec 打包一直报 missing）→ 重打 exe 后语音按钮真正可用（麦克风录音 → 识别 → 进输入框）；spec hiddenimports 原已声明，本次打包不再缺依赖。

## v1.2.1 — 稳定性修复与名实相符

**本版修复与增强（逐项回归验证通过）**：

**〇 Token 用量显示打通（GUI 此前看不到 token）**
- 根因：GUI 流式 `chat_stream_chunks` 不解析 usage、`ApiWorker` 回传恒空、`ChatSession` 无累计 → 界面从无 token 读数。
- 修复：API 层逐帧收集 `_last_stream_usage` → Worker 带回 total/prompt/completion_tokens → `session.token_used` 累计 → 每条回复后顶栏显示「本条 x tokens · 会话累计 y」，首页 Token 卡显示真实累计。

**① 换头像闪退 + 闪退后打不开**
- 根因：头像绘制 `QPixmap.scaled(size, size, …)` 是 PySide6 非法调用（多传一个 QSize 占掉 aspectMode 位）——旧代码每次渲染头像都 TypeError（被 try 吞、头像永远显示不出）；更严重的闪退源于大图/异常 PNG 整图解码（Qt 段错误无法被 try 捕获），头像一旦入档，每次启动加载即崩 = 「打不开」。
- 修复：新增 `rounded_avatar_pixmap()` —— `QImageReader` 渐进解码（超 2048px 先缩小）、坏图返回 null、空尺寸/不存在/解码失败全部安全回退 ✨，绝不让头像加载崩进程；`_on_avatar_clicked` 拒绝 >25MB 图片；tooltip 乱码修正。角色 JSON 加载本就有 per-file 容错，配合后启动永不因头像崩溃。

**② 导航栏高亮与页面不同步**
- 根因：只有侧栏点击会回写高亮；首页快捷入口/宠物回首页/onboarding/`back()` 等外部 `navigate` 从不更新侧栏高亮。
- 修复：`SidebarWidget.set_active_page(key)`（blockSignals 防递归）+ `PageManager.page_changed` 信号统一挂接 —— 一切导航入口自动同步高亮。

**③ 首次启动引导横幅（小白开箱体验）**
- 未配置模型 Key 时主窗顶部显示橙色引导横幅「点这里打开『模型与接口』设置」，点击直达设置区并滚动定位；配置完成后自动隐藏。`refresh_api_status()` 统一维护显隐。

**④ 附件功能名实相符（用户审查反馈）**
- 文档失实修复：README 附件段原先宣称"AI 收到 `[附件] 文件名 (xx bytes)` 摘要"误导用户以为 AI 看到了文件 —— 现按类型如实说明并区分三种行为。
- 真实读取增强：文本/代码/表格类（.txt .md .py .json .csv .tsv 等 55 后缀）**读正文**给模型（≤50KB 全量、更大截断附提示）；**.docx / .xlsx 用纯标准库（zipfile+xml）真实抽取正文**（Word 按段落、Excel 按单元格含共享串/内联串/数值）；损坏/非标准格式降级为"解析失败，仅附附件信息"，绝不假装读到。
- 二进制（.pdf/.doc/.ppt/图片/压缩包/exe）保持一行诚实标注"无法解析内容"，README 明示不支持解析、请粘贴关键内容。
- 附带修正：文本读取路径文件不存在/不可读时明确标注（不再静默空块）；清理白名单无效条目（"Dockerfile"）；移除 README「Docker（即将支持）+ Dockerfile 待补充」画饼占位，改为"规划中，本版未提供"。

**验证**：换头像全链路（图标渲染/持久化 round-trip/损坏容错）、导航同步（外部入口/back/侧栏点击无递归）离屏 10/10；全库 98 py AST 0 异常。附件：QA 独立回归 V1–V8 全 PASS（docx/xlsx 真实抽取、csv/文本零回归、二进制不泄漏、坏文件降级、README 断言），无 P0/P1。桌面版 exe 重打并 frozen 冒烟通过。

## v1.2.0 — 住在桌面里的女仆（陪伴优先 + 自主任务全链）

**主题：码铃从「AI 编程工具」升级为「住在桌面里的 AI 女仆伙伴」——先陪你，再帮你干活。**

**陪伴与趣味（产品重心）**
- **房间式首页**（`page_home.py` 重写）：码铃主形象常驻随心情换表情 + 时段问候 + 今日随记（心情氛围文案）+ 关系称谓（"和主人的故事正在『亲近』篇章"）+ 徽章墙占位 + 快捷入口重组。
- **形象表情系统**（`gui/maid_avatar.py` + `gui/assets/maid/`）：8 表情资产管线 + manifest 校验 + **QPainter 程序绘制占位脸兜底**（无 PNG 也显示，UI 永不空白崩溃）；`set_maid_expression()` 统一 API 供 首页/宠物/气泡/侧栏 复用。
- **角落微型宠物**（`gui/widgets/maid_pet.py`，A8/A8-1）：窗口角落常驻女仆装猫耳小兽（女仆形象为基础的小动物形态，用户拍板），5 态先行、随尺寸分级显示/折叠、hover 心情文案、点击互动（彩蛋台词 + 表情脉冲，30 分钟冷却防刷）。
- **有节制的主动陪伴**（`gui/proactive_scheduler.py`，A9）：码铃会先开口——仅三类触发（长空闲轻声问候 / 近 5 分钟主人低情绪关心 / Agent 任务完成未回复回访）；免打扰时段 + 单日上限 + 冷却 + **防自续命**（主动消息不算交互打点，杜绝循环骚扰）；`ChatService.proactive_ask()` 独立入口走独立路径。
- **彩蛋互动**（A3/A8）：点击形象 → `react_to_pet_click()`（心情台词池 + 30 分钟冷却，冷却内只回话不加分）；好感度升级改**纯关系称谓反馈**。
- **聊天气泡形象**（B3）：AI 气泡旁 Q 版头像，thinking/focus/happy/shy 表情随活动态联动。
- **侧栏/托盘**（B5）：侧栏码铃形象入口（点击回首页）+ 托盘 tooltip 随心情更新。
- **无焦虑红线**（§3.9，用户核心诉求）：**全 UI 不展示心情/好感数值、无进度条/分数/Lv/打卡倒计时**；心情与好感永不 gate 功能、永不做负向反馈；streak/分数只在后台默默积累。QA 独立扫描 4/4 零违反。

**自主任务全链（C1–C4+C9，能力背书）**
- **C1 run_command**（`command_runner.py`）：白名单内跑 python/pytest/node + 回读输出；命令+语法+路径三重白名单（pip/任意 shell 拒绝即拒绝不进弹窗）、超时 kill、输出截断、会话互斥；诚实标注「进程级非沙箱」。
- **C3 任务规划拆解**（`agent_task.py`）：TaskStep/TaskRun/TaskRunStore——大任务先拆步骤清单逐步执行、断点持久化可恢复。
- **C2 自我修正**：步骤失败 → 失败摘要回注 → 模型自改（write_file/run_command）→ 复验，最多 N 轮（`agent.max_retries`）；**通过判定契约**：声明完成但验证失败不通过（口头完成压不过失败验证）。
- **C4 任务级记忆**：每步注入「[任务进度] 目标|已完成|卡点」上下文，长任务不失忆。
- **C9 端到端**：造 bug→规划→运行→失败→自愈→修复→通过 全链路演练通过。

**UI 现代化（简洁 × 女仆基调）**
- **B8 设计语言**：`gui/themes/base.qss` 公共组件层 + theme_engine 合并加载（base + 主题肤感层）；layout token + 语义色键；新组件统一取色禁裸值。
- **B9 模型配置清晰入口**：设置页「API 配置」升级为「模型与接口」专区（ModelConfigPanel：厂商卡片点选 + Key 脱敏展示 `sk-****5678` + 连接态）；侧栏底部模型状态直达行；首页快捷入口。

**验证（QA 独立回归）**
- A-14 暴露面红线：REDLINE_PASS（4/4 零违反，43 个 GUI 文件全扫）
- 全量集成回归：TEST_PASS（98 文件 AST 0 异常 + 64 模块 py_compile + 107 逻辑断言 + 33 交叉一致性，0 失败）
- P2 修复：升级文案去等级字样（纯称谓）、角色卡"亲密度"措辞改「羁绊」（防与关系系统混淆）
- GUI 视觉/真机项需本机 PySide6 环境验收（沙箱无 PySide6，如实声明）

## v1.1.0 — Agent 模式（女仆能自己动手干活了）

**主题：让码铃从"聊天工具人"升级为"能自主调用工具的 agent"。**

**新增**
- **Agent 引擎**（`agent_engine.py` + `agent_tools.py`）：统一工具调度循环——把"LLM 推理 ↔ 工具执行"收拢成 CLI / GUI 共用的引擎。模型自主决定何时调用工具，执行结果回写后继续推理，直到任务完成或达到步数上限（默认 8 轮）。
- **内置工具集（8 个，分级授权）**：
  - L0 只读（自动放行）：`read_file` 读文件 / `list_dir` 列目录 / `git_status` / `git_diff` / `web_search` 联网搜索
  - L1 修改（需用户授权）：`write_file` 写文件（自动 .bak 备份）/ `git_commit` / `run_python`（AST 白名单沙箱执行）
- **GUI 的 🤖 Agent 开关**：聊天输入区可切换。开启后消息走 Agent 引擎，模型可自主调用工具；关闭后完全保持原有纯聊天路径。
- **工具轨迹折叠卡片**（`gui/widgets/tool_trace.py`）：Agent 运行时在消息区与输入区之间展示执行过程卡片，逐条显示工具名与状态（✅/❌/⛔），可折叠；颜色走主题取色。
- **设置页「Agent 设置」区块**：启动默认开启 Agent 开关 + 最大步数滑杆（3–20，默认 8），持久化到配置；「个性」区补充语气注入范围说明。
- **agent 配置段**：`config.yaml` 新增 `agent.enabled` / `agent.max_steps`，CLI 与 GUI 默认模板同步补齐。
- **授权弹窗**：修改类工具命中白名单目录（workspace）自动放行；目录外操作弹窗确认「允许（本次会话）」，拒绝则工具不执行。
- **Agent system prompt 工具说明**：兜底提示词列出 8 种工具（只读/修改分类）与授权规则。
- **停止生成修复**：`stop_generation()` 别名补齐（面板与独立窗口原调用名在 ChatService 上不存在，停止按钮此前失效）。

**合理化（自然感）**
- **女仆语气注入去机械化**（`gui/chat_service.py`）：技术/代码类回复（含 ``` 代码块、def/import 开头等）不再注入「主人~」等语气前缀；自然对话降频至约 15% 前缀 / 10% 后缀，移除高频颜文字硬前缀与无引用死代码常量。
- **好感度感谢检测误判修复**（`intimacy.py`）：否定语境（不喜欢/不太满意/一点都不棒）不再被误判为夸奖；词库扩充（太棒/很棒/靠谱/贴心等）。

**安全（重要）**
- 授权策略 **fail-safe 默认拒绝**：无确认渠道或目标不在白名单时，修改类工具一律拒绝，杜绝越权写文件。白名单 = 配置的 workspace 目录。
- `run_python` 沿用现有 `CodeSandbox` AST 安全检查：禁止文件系统/危险内置函数/危险属性。

**开源准备**
- 版本号升至 v1.1.0（`core.__version__` / `version.json` 同步）。
- `maid_coder_gui.spec` hiddenimports 补 `agent_tools` / `agent_engine` / `gui.widgets.tool_trace`。
- 工具描述与授权注释与实现对齐（消除误导性表述）。

**验证边界（如实声明）**
- QA 独立回归：A 阶段 15/15 + B 阶段 18/18 PASS，无 P0/P1（2 条 P2 已修复）；引擎/工具/授权/好感度/语气注入逻辑在无 GUI 环境自动化验证通过。
- GUI 真机验收（Agent 开关、授权弹窗、轨迹卡片渲染/折叠、设置页滑条、主题取色）需本机 `pip install -r requirements_gui.txt` 后实测；PySide6 环境未在沙箱覆盖。

## v1.0.0 — 首个正式版（产品化：定名「码铃」，版本号重新计数）

**版本号自本次发布起重新计数：v1.0.0 对应此前的内部版本 v10.15（含此前全部功能与修复）。**

命名定案：产品正式名称为「码铃」（英文 MaLing）——女仆项圈铃铛 ×「叮铃一响、码上应答」的聊天感双关；对外版本展示统一为「码铃 v1.0.0」。以下为 v1.0.0 相对内部版本 v10.15 的产品化改动。

**新增**
- 正式定名「码铃」（MaLing）：窗口标题 / 关于页 / 帮助页 / README / 启动与安装横幅 / 语气前后缀等对外文案全部切换为新名；内部标识（日志器名、MAID_ 环境变量、用户数据目录）保持不变，老用户数据无需迁移。
- `.exe` 打包分发：无需安装 Python 即可运行（`maling_v1.0.0_win64.zip`，SmartScreen 首次运行说明见下载页）。
- 启动时异步检查更新：不阻塞启动、失败静默；发现新版 GUI 非阻断提示，支持「复制下载链接」与「忽略此版本」（忽略状态存独立文件 `update_state.json`，出现更新版本时自动恢复提示）；更新源为仓库固定地址的 `version.json`。
- 下载页：一页极简静态页（定位 / 版本徽标 / 双下载按钮 / SmartScreen 说明 / 系统要求）。
- 版本比较统一为数值元组实现 `parse_version`（`1.10.0 > 1.9.0` 按数值判定，杜绝字符串比较误判；rc 预发布版视为低于同号正式版），四条断言并入回归脚本。

**修复（承接 v10.15 真实性修复包，随首个正式版一并发布）**
- 聊天不再假成功：API 失败以真实错误气泡展示，不再以女仆语气话术掩盖；演示模式回复带 `[模拟回复·未连接API]` 显著标注。
- 真流式输出：逐 chunk 增量到达，停止按钮与关窗正确中断请求并清理线程。
- 多模型工作流崩溃（`NameError`）与配置读不回（`_YAML_FIELD_MAP` 嵌套映射 round-trip 一致）修复。
- 引导页嵌套 `api.key` 检测、附件内容诚实标注、沙箱能力诚实表述等真实性修复，详见 v10.15 条目。

**已知问题**
- 未购买代码签名证书：Windows 首次运行会弹 SmartScreen 蓝色提示（「更多信息 → 仍要运行」即可），不代表检测到病毒；说明见下载页。
- 名称与拼音近似词同音，口头传播建议辅以文字说明（命名查重记录见执行文档）。

## v10.15

真实性修复包（11 项）：解决「用户看见/未看见」与「真实/模拟」两层不匹配。

**核心（聊天层）**
- 聊天不再以「女仆 fallback」掩盖 API 错误：新增 `message_failed` 信号，API 错误时以红框错误气泡 + 提示文案真实展示，不再让用户误以为女仆给了答案。
- 真流式：新增 `chat_stream_chunks` 生成器方法（api.py），`ApiWorker` 直接消费增量，不再做 char-by-char 假播放；停止按钮通过 `cancel_check` 协作中断，关闭底层 response。
- 关窗口时 `worker.stop(wait_ms=5000)` 真正等待线程退出，替代原来 hardcoded 1000ms。
- 演示模式显著标注：未配置 API Key 且非 ollama 本地时，回复前缀 `[模拟回复·未连接API]`，避免用户误以为连上了 API。

**协作与配置**
- `agents.py` 修复 `NameError`：补充 `C / G / GR / R / Y` 颜色常量导入，多模型协作工作流可用。
- `AppConfig.load()` 重写：引入 `_YAML_FIELD_MAP`（25 字段 → (section, subkey)）作为单一真值源，覆盖 api / session / output / multi_model / web_search / code / safety 七段，type coercion（bool / int / float）就位；load/save 双向 round-trip 一致。
- 引导页：Python 检查改为 ≥3.10；API 配置检查改用 yaml.safe_load 解析嵌套 `api.key`；第 0 步环境未通过时硬阻塞（提示 Python / PySide6 安装问题），不能跳过；保存 key 后重建 `APIClient` 并把 `session.api / collaborator.api` 同步刷新。

**附件与展示**
- 附件 payload 走 `gui.utils.build_attachment_payload`：文本 ≤50KB 直入 prompt 并加 `</attachment>` 边界；超过则截断到 50KB 并标「内容已截断」；二进制附件做 `<binary attachment: ...>` 诚实标注，不再让 AI 假装看到了内容。
- 关于页 + 设置页版本号硬编码改为读 `core.__version__`（v10.14 漏了 GUI 显示层）。
- 设置页整个页面用 `QScrollArea` 包起来，解决「外观主题」与「个性」之间模块被半遮挡的体验问题。
- 底部 API 状态栏新增 `MainWindow.refresh_api_status()`，初始化 / 设置页保存 / 引导页完成三个入口统一刷新，支持 ollama 本地视为已配置。

**诚实表述**
- `utils.py:1072` 注释从「完全隔离」改为「进程级隔离（非沙箱：独立 Python 进程，仍可读取文件/访问网络，仅阻止主进程被拖崩）」，避免误导用户当作安全沙箱使用。
- `README.md` 三处 `github.com/your-repo` 改为「仓库地址待定，公开分发前替换」；新增分层 `requirements.txt`（CLI 基础）+ `requirements_gui.txt`（GUI，顶部 `-r requirements.txt` 复用）。
- 默认配置文件（`gui/main.py` 缺失时创建）改为嵌套结构（api / persona / output / session / multi_model / web_search / code / safety 七段），与 `AppConfig.save()` 一致。

> 注：本版本仅做真实性修复与 GUI 显示修补，**未改产品名**（仍为 maid_coder / maid_coder GUI）；命名「码铃」与产品化落地计划在 v10.15 验收通过后一次提交。

## v10.9

- README 重构为面向开源使用者的说明书：标题去掉写死的版本号，改为「maid_coder — 开源 AI 编程助手」；移除各版本研发整改流水账章节；v10.8「API 厂商自动适配」改写为「多厂商配置指南」用户文档；开源准备结论（LICENSE 版权行改为自己的署名、.gitignore 已挡住 config.yaml）提炼并入「开源协议」章节。
- 新增 CHANGELOG.md，按版本倒序收录 v10.2～v10.8 的改动记录。
- 本次仅重写 README.md 与新增 CHANGELOG.md，其余文件与 v10.8 逐字节一致。

## v10.8

### 1. 厂商预设

`config.yaml` 的 `api` 段新增 `provider` 字段，内置以下预设（均为 OpenAI 兼容 chat/completions 端点）：

| provider | 端点 | 默认模型 |
|----------|------|----------|
| `deepseek`（默认） | `https://api.deepseek.com/chat/completions` | `deepseek-chat` |
| `moonshot` | `https://api.moonshot.cn/v1/chat/completions` | `kimi-k3` |
| `qwen` | `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions` | `qwen-plus` |
| `zhipu` | `https://open.bigmodel.cn/api/paas/v4/chat/completions` | `glm-4-flash` |
| `openai` | `https://api.openai.com/v1/chat/completions` | `gpt-4o-mini` |
| `openrouter` | `https://openrouter.ai/api/v1/chat/completions` | `openai/gpt-4o-mini` |
| `ollama`（本地） | `http://localhost:11434/v1/chat/completions` | `llama3.1:8b` |
| `custom` | 手动填写 | 手动填写 |

- 选定预设后，CLI 首次配置向导 / GUI 引导页 / GUI 设置页会自动带出对应的 url 与默认模型名；模型下拉框均已改为**可编辑**，可手动输入任意模型名。
- API Key 仍单独填写（各厂商在自己后台申请）；本地 `ollama` 预设下 GUI 允许 Key 留空。
- **向后兼容（硬性）**：旧 `config.yaml` 没有 `provider` 字段时自动按 `deepseek` 处理，不报错；`provider` 值为空或未知时同样回退 `deepseek`。

### 2. 深度思考模式备注

深度思考模式（`/deep` 或 GUI「深度思考」卡片）附带的 `reasoning_effort` 与 `extra_body.thinking` 参数为 **DeepSeek 专属**；`provider` 为其他厂商时这些参数**自动跳过、不会发送**，因此更换厂商后开启深度模式不会再因不识别字段而报错。CLI 切换深度模式与 GUI 开启深度思考时均会给出该提示。

### 3. 联网搜索默认开启

`web_search.enabled` 默认值由 `false` 改为 `true`（config.yaml 模板与代码默认值同步修改）。联网搜索基于独立的 DuckDuckGo 搜索（`ddgs` / `duckduckgo-search` 包，HTTP 直连），**不依赖任何 API 厂商的专属能力**，因此对所有 provider 行为一致，无需降级处理；未安装搜索依赖时按原有逻辑优雅降级提示。

### 4. 其他修复（实现上述功能时顺带修复）

- **config.yaml 读取修复**：`core.AppConfig.load` 的环境变量/段落映射此前被 `MAID_` 前缀挡住，`api.url`、`api.model`、`web_search.enabled` 等 yaml 值从未真正被读取（一直用代码默认值）。v10.8 起按「环境变量 > 本文件 > 代码默认值」的既定优先级真正生效。
- **GUI 设置页持久化修复**：`core.AppConfig` 新增 `save()` 方法；此前 GUI 设置页保存 API 配置时调用 `cfg.save()` 会因方法不存在而失败。
- **GUI 引导页写入修复**：首次引导保存 API 配置此前把 `api_key/url/model` 平铺写到 yaml 顶层（读取时按 `api:` 段落解析，等于没存上）；v10.8 起正确写入 `api:` 段落，并同步持久化 `provider`。

## v10.7

### 新增文件

- `LICENSE`：MIT 许可证全文，版权行当前为占位写法 `Copyright (c) 2026 maid_coder project contributors`。上传 GitHub 前请把版权行改成你自己的署名（如 GitHub 用户名 / 真实姓名），改这一行即可，许可证正文不用动。
- `.gitignore`：Git 忽略规则，条目含 `config.yaml`、`.env`、`dist/`、`build/`、`__pycache__/`、`*.pyc`、`*.spec.bak`，每条均附中文注释说明排除原因。

### 上传 GitHub 前自查

- **密钥防泄漏（核心）**：`.gitignore` 已把 `config.yaml` 挡在版本库外，本地含真实 API key 的配置文件不会被 `git add` 提交；仓库内分发的 `config.yaml` 为默认模板（`api.key` 为空串），请勿在开源仓库里存放任何真实密钥。
- LICENSE 版权行按上文替换为你的署名。
- 本小节之外，v10.7 相对 v10.6 无其它改动（无代码变更，`py_compile` 全量编译检查仍通过）。

## v10.6

### 问题

应用人设为「用户 = 主人、AI = 女仆」（消息气泡分别标注「主人」「女仆」，欢迎语「欢迎回来，主人~」），但快捷回复按钮是**用户点击后发给 AI 的消息**，原预置文案却是女仆口吻（「好的主人~」「明白❤」「正在处理~」「请稍等片刻✨」）——用户一点击，等于主人在管女仆叫主人，视角正好写反。

### 修复

- `gui/widgets/chat_panel.py`（主面板）与 `gui/widgets/chat_window.py`（独立聊天窗口）两处 `QUICK_REPLIES` 统一改为主人视角常用语：`["辛苦了~", "做得不错❤", "继续吧", "等等，我有别的事说"]`。
- 全包排查其余用户侧文案：输入框占位符「和女仆说点什么吧...」视角正确，未改动；其余含「主人」字样的文案（`chat_service.py` 女仆语气前缀/回复、`page_home.py` 欢迎语、`main.py` persona 配置）均为 AI 侧输出，视角正确，未改动。
- 改动仅限文案字符串与注释，不涉及布局与逻辑。

### 验证

- 全量 `py_compile` 编译检查通过。
- 两处 `QUICK_REPLIES` 均为主人视角，无残留女仆口吻的用户侧预置文案。

## v10.5

### 问题根因

- 主窗口将聊天面板写死 `setFixedWidth(380)`，嵌在分割器里却无法拖拽调宽；
- 面板内部再嵌 160px 固定宽会话侧栏，对话区实际只剩约 220px；
- 头部一行塞入搜索框（固定 120px）+ 正则开关 + 范围下拉 + 导出 + 标签模式 + 展开 + 状态标签，窄宽度下控件重叠溢出；
- 底部快捷回复标签被挤压到文字截断成单字。

### 修复内容

- **面板可拖拽调宽（`main_window.py`）**：`setFixedWidth(380)` 改为 `setMinimumWidth(360)` + 分割器正常拉伸，默认宽度约 420px（`setSizes` 初始分配）；同时禁止把侧边栏 / 聊天面板拖到 0 宽（`setCollapsible(False)`）。
- **头部两行收纳（`chat_panel.py`）**：
  - 第一行：会话标题 + 状态 + 三个图标按钮（📤 导出 / 🗂 标签页 / ↗ 展开，悬停有完整 tooltip）；
  - 第二行：搜索框（随面板伸缩，不再固定 120px）+ 正则开关 + 范围下拉（紧凑化）。
  - 标题与状态使用 `_ElidedLabel`（自动省略号 QLabel 子类）：窄宽度显示省略号而非截断；`text()` 始终返回完整原文，不污染读取方。
- **快捷操作栏横向滚动**：附件 / 粘贴 / 搜索 / 表情 / 语音五个按钮收进横向滚动区，面板再窄也不重叠，放不下时出横向滚动条。
- **快捷回复标签完整显示**：按钮锁定 `sizeHint` 最小宽并收进横向滚动区，不再截断成单字。
- **会话侧栏**：保持 160px，左侧「◀/▶」按钮折叠/展开（原有功能不变）。

### 验证方式

- 全量 `py_compile` 通过（86 个 .py 文件）。
- offscreen 双分辨率（1602×932 与 1280×720）截图比对：修复前快捷回复截断成单字、头部按钮溢出面板；修复后所有控件无重叠、无溢出、无截断。
- 布局断言：面板默认宽 420、可经分割器拖宽至 500、搜索框随面板伸缩、快捷回复按钮宽 ≥ 文字需求宽、会话侧栏折叠开关有效。
- 端到端回归：第四阶段全部 14 组断言（R1–R13 + 冒烟）仍通过，无双气泡 / regenerate / 附件校验链 / 标签页 / 独立窗口 / 三主题等功能零回归。

### 已知边界

- 应用主窗口最低尺寸为 1200×800（`setMinimumSize`），因此在 1280×720 的屏幕上实际窗口高度会被抬高到 800——这是应用既有的最小窗口限制，非本次布局问题；聊天面板宽度行为不受影响。

## v10.4

- .exe 打包材料整合：修订 `maid_coder_gui.spec`（修正 `('gui/themes', 'themes')` 资源路径错位——旧版 `('gui/themes', 'gui/themes')` 会导致打包后找不到 QSS、三主题降级为内置默认样式；hiddenimports 显式声明 `speech_recognition` + `pyaudio` 动态导入；UPX 关闭 + onedir 模式降低杀软误报）、补齐 `requirements_gui.txt`（移除全包未引用的 `markdown`），README 新增「.exe 打包整合说明」章节（现保留于 README，作为用户打包教程）。

## v10.2

### GUI 第四阶段质检整改（2 严重 / 5 警告 / 6 建议，共 13 项）

本节对应第四阶段交付包全量回归质检的修复版本，行为变化如下：

#### 严重项修复

- **重复气泡消除（R1）**：用户消息以「UI 直插气泡」为唯一渲染入口；`ChatService.send_message(text, suppress_echo=True)` 抑制服务层 `message_added` 回声，用户消息不再出现双气泡，也不再被双重持久化或重复写入 API history。流式输出期间 assistant 的回声回插同样被跳过（流式气泡本身即展示载体）；非流式/模拟回复仍走回放渲染。独立聊天浮窗（`chat_window.py`）发送路径同样处理。
- **重新生成中段语义（R2）**：`ChatService.regenerate(user_text=..., ui_history=...)` 支持从会话**中段**重新生成——UI 截断后把「剩余消息 + 最后一条 user 文本」传给服务层，`app_ctx.session.history` 同步截到与 UI 一致（保留 system 头），两套历史不再分叉；无参调用仍兼容旧的「弹尾部 assistant」逻辑。

#### 警告项修复

- **语音识别线程化（R3）**：录音/识别移入 `QThread`（`_RecognitionWorker`），信号回传结果/失败，识别期间界面不再冻结；关闭对话框时安全回收线程。
- **主题色键补齐（R4）**：cute / maid / minimal 三主题均补 `text_on_accent` / `bg_light` / `disabled_bg` / `disabled_text` 四个色键。
- **附件按钮统一校验链（R5）**：输入区「📎 附件」按钮改走 `attachment_bar.add_file_path()`，与拖拽共用存在性 / 10MB / 重复三条校验。
- **独立窗口发送补持久化（R6）**：浮窗发送经 `user_message_sent` 信号回传主面板统一渲染并持久化，两条发送路径落同一份会话数据。
- **附件落库二道闸（R7）**：`AttachmentData.from_dict` 反序列化时校验字段合法性与 10MB 上限，超限/非法条目在回放时剔除并记日志。

#### 建议项修复

- **R8**：API 回调带 `req_id`，过期请求（如 regenerate 掐掉的旧任务）的 chunk / result / error 一律丢弃。
- **R9**：编辑用户消息前弹确认框（编辑会截断该消息及其后全部内容），防误触丢失。
- **R10**：截断操作先取局部变量快照（文本/附件/剩余历史）再 `deleteLater`，不触碰已销毁控件。
- **R11**：会话保存改为**增量同步**——按序对位更新气泡内容，`id` / `timestamp` / `model` / `tokens` 等既有字段不再丢失。
- **R12**：清理 `message_bubble.py` 死代码（空循环）与 `!=` 写法规范化。
- **R13**：关闭标签页后切换到**相邻标签**（先左后右），而非固定列表末项。

#### 验证方式

- 全量 `py_compile` 通过（86 个 .py 文件）。
- offscreen 冒烟 + 14 项端到端断言全部通过，覆盖：发送无双气泡、regenerate 中段语义与旧签名兼容、旧会话文件兼容、tab rebuild 与相邻切换、附件双道校验、三主题色键、编辑确认、增量保存保 id、独立窗口路径、过期回调过滤。## v1.8.0 — 认知深化版本（"她真的认识我"的进化）

### P0 认知深化三件套
1. **记忆图谱**：记忆中心新增「人物关系」——你提到过的人（同事/朋友/家人）被结构化记住（名字/关系/备注/相关事件），聊天中提及即自动带上下文；每条记忆带来源角标，删除即遗忘
2. **情绪弧线**：8 周情绪日格色带（档位色块呈现，无数字打分——"帮你看见自己，不是给你打分"）；问"我最近状态怎么样"她会基于真实情绪历史回答
3. **共同经历时间线**：高光回忆+已完成话题+纪念日按月聚合，"我们一起经历过…"的时间线视图

### P1
4. **场景化陪伴**：工作/休息/睡前三场景（按时段自动感知+可手动切换当日有效）；工作场景主动消息自动降档（cap 3→1，降档绝不升档）；三层语气叠加（情绪模式>场景>意图）
5. **角色卡 v2 分享标准**：封面图（base64≤500KB 自动压缩）+ 导入预览弹窗（字段逐项确认/冲突改名）+ 格式规范文档
6. **自定义回应约定**：你说"当我说 XX 时你要 YY"→ 她记住并遵守（≤20 条，命中当轮注入，零常驻 token）
7. **影像记忆**：你发过的图片她会"记得"（存对话事实与中性描述，绝不存图像二进制——隐私硬线）；问"上次那张图"可召回；识别不了时诚实说不知道

**版本**：1.7.3 → 1.8.0。测试：725 passed / 0 failed。


