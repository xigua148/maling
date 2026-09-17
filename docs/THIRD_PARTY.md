# 第三方开源组件登记（THIRD_PARTY）

> 码铃（MaLing）v1.4 方向 A「开源玩具盒」第三方归属台账（docs/design-v14.md §2.6 / A4，R-H 红线）。
> **许可白名单（R-H）**：仅收 MIT / Apache-2.0 / BSD-3 / BSD-2 / 0BSD / CC0；禁 GPL / AGPL / LGPL / SSPL。
> ⚠️ **适用范围**：白名单针对的是**「移植 / 改写他人源码进本项目」**。
> **纯外部运行时依赖**（如 PySide6 = LGPL-3.0）与**构建期工具**（如 PyInstaller = GPL-2.0 + bootloader 例外）按下方 §三/§四 的**独立口径**评估——前者以**动态链接 + 用户可自行替换库文件**满足 LGPL，后者**不随发行包分发**。二者不因本条而排除。
> 任何候选在代码合入前必须以仓库内**实际 LICENSE 文件**复核（本表为实施后复核记录）。
> PyQt 写的源码只看仓库自身许可（改写进 PySide6/LGPL 使用合法）。

## 一、已纳入组件

| 项目 | 仓库 | commit / 复核版本 | 许可（实际 LICENSE 文件核验） | 原版权行 | 入库文件 | 改动摘要 | 复核日期 | 复核人 |
|---|---|---|---|---|---|---|---|---|
| 2048（tangentecode/2048-pyqt6） | https://github.com/tangentecode/2048-pyqt6 | main @ 6c5e67c0642bd94e91c4595565bdfca1ecc98a76 | MIT | `Copyright (c) 2024 jøhann` | `gui/widgets/games/game_2048.py` + `docs/third_party_licenses/tangentecode_2048-pyqt6.txt` | PyQt6 → PySide6 单文件 QWidget；去 StartWindow 选单与 3x3/5x5/6x6；固定 4x4；WASD/方向键保留；经典瓦片配色保留；仅保留局内「当前得分」（Q-A1 豁免，不落盘）；壳面换 theme_color；合成 2048 一句庆祝 | 2026-09-04 | 工程师 A（寇豆码） |
| 扫雷（dawsonbooth/pynsweeper） | https://github.com/dawsonbooth/pynsweeper | master @ 618c22b32c1f2c146978893ef38639f68baf685a | MIT | `Copyright (c) 2020 Dawson Booth` | `gui/widgets/games/game_minesweeper.py` + `docs/third_party_licenses/dawsonbooth_pynsweeper.txt` | PyQt5 → PySide6 单文件 QWidget；去 Windows XP 复古皮图片资产（全部重绘，A4 评审项 ④）；去计时器/胜利记录/ScoreBoard；保留剩余雷数 + 右键标旗 + 零扩散翻开；默认 9x9/10 雷（首版无难度切换）；棋盘/数字中性色 + 壳面 theme_color | 2026-09-04 | 工程师 A（寇豆码） |
| Pi Coding Agent Runtime（@earendil-works/pi-coding-agent） | https://github.com/earendil-works/pi | npm 0.85.1（随桌面包分发） | MIT | `Copyright (c) 2025 Mario Zechner` | `dist/maling/_internal/pi_runtime/node_modules/@earendil-works/pi-coding-agent/` + `docs/third_party_licenses/earendil-works_pi-coding-agent.txt` | 作为独立 Node.js Agent Runtime 随发行包分发；本项目未修改其源码 | 2026-09-14 | 主理人 |
| SillyTavern（内置酒馆） | https://github.com/SillyTavern/SillyTavern | `release` 分支 @ `06bde939fb1e9c4c8d8641d810f0a916b5bce127`（tag `1.19.0` = `7e8663cd9c184a550b37238218bdd32c6efc68e9`） | **AGPL-3.0**（⚠️ 非白名单许可，经「纯外部运行时依赖」口径 R-H 豁免后纳入，见下） | 见 `vendor/sillytavern/LICENSE`（AGPL-3.0 标准版权行） | `vendor/sillytavern/`（源码树；`node_modules/` 为构建输入、由 .gitignore 排除）+ `docs/third_party_licenses/sillytavern_AGPL-3.0.txt` | **零改动**：与上游发布包逐字节一致。作为独立 Node.js 进程仅在本机回环（127.0.0.1）提供服务，由应用内嵌浏览器经本机 HTTP 访问；本项目未修改、未链接、未派生其代码 | 2026-09-17 | 主理人（R-H 豁免） |

> **R-H 豁免说明（SillyTavern）**：第 4 行白名单针对的是「**移植 / 改写他人源码进本项目**」。
> SillyTavern 属于第 6 行已预留的「**纯外部运行时依赖**」形态（与 PySide6/LGPL 同口径）：
> 独立进程 + 本机 HTTP + 未修改源码，**不构成衍生作品**，故不落入白名单的排除范围。
> 本项经主理人于 2026-09-17 援引该既有口径签发豁免，并配套完成：AGPL 全文随包
> （`_internal/sillytavern/LICENSE`）+ 源树副本（`docs/third_party_licenses/sillytavern_AGPL-3.0.txt`）
> + 仓库根 `NOTICE` 第五节登记 + `package-lock.json` 哈希固定的可复现配方。
> **边界**：一旦形态改变（同进程加载、链接其代码、或修改其源码），豁免立即失效，须转 §7 流程重评。

### 核验记录

- **2048**：仓库存在 `LICENSE` 文件，实际许可 = MIT。核验 URL：
  - 仓库页 https://github.com/tangentecode/2048-pyqt6 （LICENSE 条目，创建 commit `801b08ddc95b2af41afd597d22ea398ab3320271`）
  - LICENSE 原文 https://raw.githubusercontent.com/tangentecode/2048-pyqt6/main/LICENSE （2026-09-04 读取，MIT License / Copyright (c) 2024 jøhann）
  - 源码：`src/main.py`（单文件，无文件级版权头，版权行以 LICENSE 为准）
- **扫雷**：仓库存在 `LICENSE` 文件，实际许可 = MIT。核验 URL：
  - 仓库页 https://github.com/dawsonbooth/pynsweeper （README License 段指向 LICENSE）
  - LICENSE 原文 https://raw.githubusercontent.com/dawsonbooth/pynsweeper/master/LICENSE （2026-09-04 读取，MIT License / Copyright (c) 2020 Dawson Booth）
  - 源码：`src/constants.py` / `src/main.py` / `src/utils.py`（无文件级版权头，版权行以 LICENSE 为准）
- **SillyTavern**：本地树声明 `"license": "AGPL-3.0"`（`vendor/sillytavern/package.json`），
  随树的 `LICENSE` 首行为 `GNU AFFERO GENERAL PUBLIC LICENSE / Version 3, 19 November 2007`。核验：
  - **版本锚点（可验证，非仅引用）**：本地 `package-lock.json` 的 sha256 =
    `5ee4095a82d2b326e30290480b33529553cba60d2f418bc086ed3c08d874d888`，与上游
    `release` 分支 HEAD（`06bde939…`）及 tag `1.19.0`（`7e8663cd…`）取回的同一文件
    **逐字节一致**（2026-09-17 经 GitHub API 取回比对）→ 坐实本地树对应上述 commit。
  - **零改动**：与上游发布包逐字节比对，1010 个源码文件 0 内容差异 / 0 缺失 / 0 多余
    （独立复核，不采信 mtime 论证）。
  - **依赖树**：`node_modules` 667 个非 dev 包与 `package-lock.json` 闭包对账 **0 缺失**；
    许可审计覆盖 730 个真实包，728 个为宽松许可。
  - **源码获取**：分发包内已随附完整源码（含 `node_modules`），上游对应版本见上表 commit / tag。

### 评审清单（design-v14 共享知识 19 逐条）

- ① LICENSE 白名单：2048 = MIT ✅ / 扫雷 = MIT ✅（以仓库实际文件为准，非 README 徽章）
- ② 原版权行：两项目源码均无文件头版权行 → 以仓库 LICENSE 版权行为准，移植文件头照抄（year+author）✅
- ③ 第三方 Python 依赖许可：2048 仅 PyQt6（仓库自身 MIT，改写进 PySide6 合法）；扫雷仅 PyQt5（同）✅；码铃侧零新增第三方依赖（R-F）
- ④ 资产版权：**未引入任何原项目图片/图标/音效**（扫雷 XP 皮肤资产弃用并重绘）✅
- ⑤ 移植文件头：保留原 MIT 版权行照抄 + 码铃移植说明块 ✅；LICENSE 全文副本已入库 ✅；About「开源组件」见下 ✅
- ⑥ 复核人/日期/commit 在案：见上表 ✅

## 二、参考未采用（仅借鉴形态，未复制代码）

| 参考 | 仓库 | 说明 |
|---|---|---|
| Pomodoro-timer | https://github.com/Wenlin-AI/Pomodoro-timer | 仅借鉴「专注/休息计时交互形态」（prd-v14 §6.2 调研）；码铃 A3 番茄钟为自制轻量组件（去 pygame/去 Obsidian/去 session 历史文件），**未复制其任何代码/资产**，许可面最小，无需 LICENSE 副本入库。 |

## 三、P2 扩展候选池（A5，登记不承诺）

> 口径：**自制优先**（无许可负担、与荷官文案/表情系统天然整合）；MIT/白名单现成实现干净才移植；GPL 系一律排除（R-H）。

| 候选 | 来源策略 | 许可状态 | 备注 |
|---|---|---|---|
| 贪吃蛇 | 自制优先（<300 行） | 自制零负担 | 散见仓库多无 LICENSE；mlisbit/pyqt_snake、songquanpeng/snake-game 等未标注许可，不可用 |
| 井字棋 / 五子棋 | 自制优先（<200 行） | 自制零负担 | 双人对弈可接「她陪你下」（规则级 AI，不引 LLM） |
| 记忆翻牌 | 自制优先 | 自制零负担 | 轻松短局 |
| 俄罗斯方块 | Pytris（AoifeHughes）MIT（初审） | 待复核实际 LICENSE | 局内计分为玩法核心，若纳入按 Q-A1 豁免口径处理 |
| 数独 | SajjadSaljoughi/Sudoku（待复核）+ `sudoku` 库（待复核） | ⚠️ 依赖库许可未核 | 数独天然无数值焦虑；计时/提示次数等引入需裁剪；复核通过才排期 |
| 2048 触屏手势 | — | — | 现有 game_2048 仅键盘；QGestureEvent 适配为 P2 |
| 剪贴板历史 | CopyQ = GPL ❌ | 排除 | 隐私边界 + 许可双重否决，另立专项再议 |

> 红线提醒：候选只要来源仓库无明确白名单 LICENSE（或为 GPL 系）即**拒绝**，不自作主张绕行。

## 二、角色美术素材（项目自有）

> 主理人 2026-09-14 确认：**全部角色表情差分图、女仆主形象与宠物造型均为 AI 生成的项目自有素材**。
> 不含第三方代码或资产，不产生第三方署名、许可或来源登记义务；随本项目 MIT 许可一并分发。

| 素材 | 来源 | 许可 | 入库位置 | 登记日期 |
|---|---|---|---|---|
| 全部角色表情差分 / 女仆主形象 / 宠物造型 | 项目自有 AI 生成素材 | 项目 MIT | `gui/assets/maid/`、`gui/assets/maid_pet/`、`gui/assets/roles/` | 2026-09-14 |

## 四、内置字体（v1.9 第二批 B / 红线 R-L）

> R-L 口径：**仅内置 OFL 1.1 字体**；B/C/D 级授权（MiSans / HarmonyOS Sans / OPPO Sans / 阿里系 / 乐米系 /
> 阿里健康体 / 站酷非开源版）一律不内置。子集化属 OFL "修改"，须沿用 OFL、保留版权声明、附许可副本。

| 字体 | 仓库 | 许可（实际 LICENSE 文件核验） | 用途 / 入库文件 | OFL 副本（随包 + 源树） | 登记日期 |
|---|---|---|---|---|---|
| 资源圆体 Resource Han Rounded | https://github.com/CyanoHao/Resource-Han-Rounded（release v0.990，RHR-CN） | **SIL Open Font License 1.1** | 正文 / 界面默认字体；`gui/assets/fonts/ResourceHanRoundedCN-Regular.ttf` + `ResourceHanRoundedCN-Medium.ttf`（GB2312 子集） | `gui/assets/fonts/OFL-Resource-Han-Rounded.txt` + `docs/third_party_licenses/OFL-Resource-Han-Rounded.txt` | 2026-09-10 |
| jf open 粉圆 Open Huninn | https://github.com/justfont/open-huninn-font（v2.0，`font/jf-openhuninn-2.0.ttf`） | **SIL Open Font License 1.1** | 标题 / 点缀（仅标题位，代码守卫）；`gui/assets/fonts/jf-openhuninn-subset.ttf`（标题子集） | `gui/assets/fonts/OFL-jf-open-huninn.txt` + `docs/third_party_licenses/OFL-jf-open-huninn.txt` | 2026-09-10 |

### 核验与合规记录（R-L）

- **① OFL 白名单**：两款均为 OFL 1.1（以官方仓库 `OFL-License.txt` / `license.txt` 原文为准），允许嵌入软件并随包再分发；唯一红线「禁止单独售卖字体文件」未触碰。✅
- **② 许可副本 + 版权声明随包**：OFL 全文副本随包（`gui/assets/fonts/`）+ 源树（`docs/third_party_licenses/`）；About 页「内置开源组件」列出字体名 / 授权 / 仓库 / 用途。✅
- **③ 保留名（Reserved Font Name）核对**：资源圆体 OFL 原文未声明附加 Reserved Font Name 条款；jf open 粉圆 license 同为标准 OFL 1.1。子集产物沿用原名分发（未改 family），合乎 OFL 要求；核对记录留档于此。✅
- **④ 生僻字 fallback**：子集仅含 GB2312 + ASCII + 标点，超集字符（生僻字 / emoji / 文件名）由 Qt 字形回退到系统「Microsoft YaHei」，绝不方块。✅
- **构建可复现**：`tools/build_fonts.py`（字表生成 + pyftsubset 子集 + 许可副本落盘）；fonttools / brotli / py7zr **仅构建期**，不进运行时、不进 exe。✅
- **未内置确认**：B/C/D 级可爱圆体（MiSans / HarmonyOS Sans / OPPO Sans 4.0 / 阿里妈妈方圆体 / 乐米系列 / 阿里健康体 2.0 / 站酷非开源版）**均未纳入**。✅

## 五、图标字体（v2.1 域3 / 红线 R-R②，扩 R-K/R-L 精神）

> R-R② 口径：第三方图标集须**四处登记**（本表 + 源树许可全文 + 随包许可副本 + About 页），
> 且许可须为 OFL / Apache-2.0 / MIT / CC0 且允许随包商用；GPL 系一律排除（D-V21-14）。

| 图标集 | 仓库 | 复核版本 | 许可（实际 LICENSE 文件核验） | 原版权行 | 入库文件 | 改动摘要 | 复核日期 | 复核人 |
|---|---|---|---|---|---|---|---|---|
| Remix Icon（`remix_icon`） | https://github.com/Remix-Design/RemixIcon | remixicon-2.5.0（经 qtawesome 1.4.2 前缀 `ri` 内置字体取出） | **Apache License 2.0** | `Copyright (c) 2018-2021 Remix Design` | `gui/assets/icons/maling_icons.ttf`（子集）、`gui/assets/icons/icons_manifest.json`、`gui/assets/icons/LICENSE`、`docs/third_party_licenses/remix_icon.txt` | 以 `pyftsubset` 按 manifest 登记的语义名做**字形子集化**（Apache-2.0 允许的修改/派生）；未改任何字形轮廓；产物沿用原 family name（Apache-2.0 无 Reserved Font Name 条款）；运行时零新增第三方依赖（R-F） | 2026-09-11 | 工程师（寇豆码，域3 V21-04） |

### 核验与合规记录（R-R②）

- **① 许可白名单**：remixicon `2.5.0` 发布时仓库 `License` 文件为 **Apache License 2.0**（原文核验：`https://raw.githubusercontent.com/Remix-Design/RemixIcon/v2.5.0/License`，2026-09-11 读取），允许商用、修改、随更大作品再分发，仅需保留版权/许可声明并标注修改 → 白名单通过。✅
- **② 上游改版口径（诚实标注）**：上游仓库自 **2026-01** 起把 `License` 文件改为自定义「Remix Icon License v1.0」（仍允许商用/修改/随包分发；禁止单独售卖图标集、用作 logo/商标、制成竞品图标库）。按新许可 §11「可选择接收时所依据的许可版本」，本子集按接收版本 `2.5.0` 沿 **Apache-2.0**；两种口径下码铃将图标作为桌面应用 UI 元件随包分发均属许可范围。本项不回避、如实登记。✅
- **③ 四处登记齐**：本表条目（此处）+ 源树许可全文 `docs/third_party_licenses/remix_icon.txt` + 随包副本 `gui/assets/icons/LICENSE` + About 页「内置开源组件」条目。✅
- **④ 使用范围声明**：图标仅作码铃界面的功能性 UI 元件（单色、按活动色板着色），**不作为码铃 logo / 商标 / 品牌标识**，不单独售卖、不构成竞品图标库。✅
- **⑤ 构建可复现**：`tools/build_icons.py`（本地 wheel 取字体 → `pyftsubset` 子集 → manifest → 许可副本；qtawesome / fonttools **仅构建期**，不进运行时、不进 exe、不写入 `requirements*.txt`）。新增图标名只需在脚本 `ICON_MAP` 补一行后重跑。✅
- **⑥ 覆盖范围**：子集含 **151 个语义名 / 145 个唯一字形**（含侧栏 10 项、顶栏与输入区工具、状态栏 3 项、设置分区、记忆中心 8 Tab 及通用控件），TTF 体积 25,232 字节（约 24.6 KB）。✅



## 五、运行时依赖（随发行包分发的第三方库）

> 登记日期：2026-09-14。依赖以 `requirements.txt` / `requirements_gui.txt` 锁定的运行为准，
> 均经 pip 从上游发布渠道获取、**未修改其源码**；完整列表与说明见仓库根 **`NOTICE`** 文件。

| 依赖 | 许可 | 备注 |
|---|---|---|
| **PySide6** | **LGPL-3.0** | Qt 官方 Python 绑定；以动态链接（.pyd/.dll）方式随包分发，用户可自行替换该库文件。LGPL 许可文本：https://www.gnu.org/licenses/lgpl-3.0.html |
| requests | Apache-2.0 | |
| PyYAML | MIT | |
| pygments | BSD-2-Clause | |
| psutil | BSD-3-Clause | |
| colorama | BSD-3-Clause | |
| python-dotenv | BSD-3-Clause | |
| pyperclip | BSD-3-Clause | |
| ddgs（可选） | MIT | 未安装时联网搜索自动降级 |
| SpeechRecognition（可选） | BSD-3-Clause | |
| pyaudio（可选） | MIT | |

构建期工具（**不随发行包分发**）：PyInstaller —— GPL-2.0 + bootloader 例外条款
（允许打包产物按任意许可分发，本项目产物仍为 MIT）。
