# 第三方开源组件登记（THIRD_PARTY）

> 码铃（MaLing）v1.4 方向 A「开源玩具盒」第三方归属台账（docs/design-v14.md §2.6 / A4，R-H 红线）。
> **许可白名单（R-H）**：仅收 MIT / Apache-2.0 / BSD-3 / BSD-2 / 0BSD / CC0；禁 GPL / AGPL / LGPL / SSPL。
> 任何候选在代码合入前必须以仓库内**实际 LICENSE 文件**复核（本表为实施后复核记录）。
> PyQt 写的源码只看仓库自身许可（改写进 PySide6/LGPL 使用合法）。

## 一、已纳入组件

| 项目 | 仓库 | commit / 复核版本 | 许可（实际 LICENSE 文件核验） | 原版权行 | 入库文件 | 改动摘要 | 复核日期 | 复核人 |
|---|---|---|---|---|---|---|---|---|
| 2048（tangentecode/2048-pyqt6） | https://github.com/tangentecode/2048-pyqt6 | main @ 6c5e67c0642bd94e91c4595565bdfca1ecc98a76 | MIT | `Copyright (c) 2024 jøhann` | `gui/widgets/games/game_2048.py` + `docs/third_party_licenses/tangentecode_2048-pyqt6.txt` | PyQt6 → PySide6 单文件 QWidget；去 StartWindow 选单与 3x3/5x5/6x6；固定 4x4；WASD/方向键保留；经典瓦片配色保留；仅保留局内「当前得分」（Q-A1 豁免，不落盘）；壳面换 theme_color；合成 2048 一句庆祝 | 2026-09-04 | 工程师 A（寇豆码） |
| 扫雷（dawsonbooth/pynsweeper） | https://github.com/dawsonbooth/pynsweeper | master @ 618c22b32c1f2c146978893ef38639f68baf685a | MIT | `Copyright (c) 2020 Dawson Booth` | `gui/widgets/games/game_minesweeper.py` + `docs/third_party_licenses/dawsonbooth_pynsweeper.txt` | PyQt5 → PySide6 单文件 QWidget；去 Windows XP 复古皮图片资产（全部重绘，A4 评审项 ④）；去计时器/胜利记录/ScoreBoard；保留剩余雷数 + 右键标旗 + 零扩散翻开；默认 9x9/10 雷（首版无难度切换）；棋盘/数字中性色 + 壳面 theme_color | 2026-09-04 | 工程师 A（寇豆码） |

### 核验记录

- **2048**：仓库存在 `LICENSE` 文件，实际许可 = MIT。核验 URL：
  - 仓库页 https://github.com/tangentecode/2048-pyqt6 （LICENSE 条目，创建 commit `801b08ddc95b2af41afd597d22ea398ab3320271`）
  - LICENSE 原文 https://raw.githubusercontent.com/tangentecode/2048-pyqt6/main/LICENSE （2026-09-04 读取，MIT License / Copyright (c) 2024 jøhann）
  - 源码：`src/main.py`（单文件，无文件级版权头，版权行以 LICENSE 为准）
- **扫雷**：仓库存在 `LICENSE` 文件，实际许可 = MIT。核验 URL：
  - 仓库页 https://github.com/dawsonbooth/pynsweeper （README License 段指向 LICENSE）
  - LICENSE 原文 https://raw.githubusercontent.com/dawsonbooth/pynsweeper/master/LICENSE （2026-09-04 读取，MIT License / Copyright (c) 2020 Dawson Booth）
  - 源码：`src/constants.py` / `src/main.py` / `src/utils.py`（无文件级版权头，版权行以 LICENSE 为准）

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

## 二、内容素材特别条目（形象/美术，区别于代码组件）

> R-H 许可白名单针对**代码组件**。以下为**美术/形象内容素材**，依其自身内容许可单独登记；
> 分发码铃时须遵守对应条款（本项目当前为非商业分发，合规）。

| 素材 | 来源与作者 | 许可 | 使用范围与义务 | 入库位置 | 登记日期 |
|---|---|---|---|---|---|
| 鲸鱼娘表情差分图（37 张） | 社区二创角色：原型 OC「溟月」© 上善无形（2025-06 创作）；女仆装版 © ZipZipPipe（2026-04-25 GPT Image 2 二次设计）。背景见萌娘百科「DeepSeek娘」词条 | **CC BY-NC-SA 4.0**（署名-非商业性-相同方式共享，作者 2026-08-02 公开声明） | ①署名：本表及关于页已注明作者与来源；②**非商业**：码铃当前免费分发，若未来商业化须先移除本素材或获作者授权；③相同方式共享：衍生素材沿用同协议 | `gui/assets/roles/preset_whale/*.png`（37 张表情差分） | 2026-09-05 | 主理人 |

> **与 R-H 白名单的关系说明**：CC BY-NC-SA 不在代码白名单（MIT/Apache/BSD 系）内，因其为**内容素材**而非代码；
> 按 NC 条款随码铃非商业分发合法。若码铃未来以 MIT 整体开源，本素材须在仓库中**单独标注许可**（不得声明为 MIT），
> 且第三方下游若商用需自行向素材作者获取授权。

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

