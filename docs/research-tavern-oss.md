# 酒馆（Tavern）· 开源候选调研：能不能"上 GitHub 找别人开源的来改"（v1）

> **本文是只读调研报告**，不修改任何产品代码，不安装任何依赖（仅 WebSearch / WebFetch 查证）。作者：开源选型调研员（research-tavern-oss）。
> 前置文档：`docs/research-tavern-game.md`（v3 方案，§2 机制拆解 / §6 模块划分 / §7 分批任务）。
> **本文的唯一目标**：回答用户那句"实在不行就上 github 找别人开源的来改"——**这条路在码铃的约束下到底能不能走，能走多远**。

---

## 0. 一句话结论（先读这个）

> **SillyTavern 本体在码铃里**一个字都用不上**——它是 Node.js + 浏览器前端，且许可证是 **AGPL-3.0**（撞 R-H 许可白名单，是**否决性**约束，比"结构不匹配"更硬）。
> 系统性检索后，**在"能替换 `gui/tavern` 引擎内核（状态机 / 世界书 / 意图路由 / prompt 组装）"这个意义上，没有可直接改的开源**。
> 唯一同时满足**纯 Python + 零运行时依赖 + 许可证兼容（MIT）**的候选是 **`pytwee`**（Twee 3 格式解析器）——它能省掉"内容格式解析层"这一小块（约几百行），**但替不了任何一条核心机制**。
> **最终建议：走"自己按机制实现"，不引任何第三方代码。** 唯一例外是可选的 `pytwee` 源码移植（收益有限，不建议在 P0 引入）。
> 结论的最硬依据不是"找不到"，而是三条**否决性约束**叠加：**R-F 零运行时依赖** → 任何第三方引擎都必须"源码移植入库"而非依赖；**R-H 许可白名单** → GPL/AGPL/LGPL 系一律出局，而这是 LLM 角色扮演生态里最主流的许可证取向；**R-A 无焦虑红线** → 该生态里几乎所有"游戏化"引擎都内置数值/战斗/经济系统，与码铃正面冲突。

---

## 1. 结构可行性：SillyTavern 能不能"改了就用"

### 1.1 技术栈证据（**已核实**）

| 项 | 事实 | 来源 |
|---|---|---|
| 运行时 | **Node.js**（早期 18+，现版本 `package.json` 要求 **20+**）；`"type": "module"`（ESM） | DeepWiki《System Dependencies and Libraries》引 `package.json:100-102,112` |
| 服务端 | **Express** Web 服务（`express` / `body-parser` / `compression` / `cors` / `helmet` / `ws` WebSocket），入口 `server.js` | 同上，引 `package.json:35-95,140` |
| 前端 | **浏览器** HTML/CSS/JS + jQuery 环境（`.eslintrc.cjs` 对客户端文件用 browser/jQuery env）；社区博客亦述"前后端分离，浏览器访问 `localhost:8000`" | 同上 + gitcode 技术架构概览 |
| 运行形态 | 本地 HTTP 服务，默认端口 8000，用**浏览器**访问；也提供 Docker 镜像与 `--listen` 等 CLI 参数 | `sillytavern.wiki` 安装/Docker 页；`likethis85/SillyTavern` README 的 CLI 参数表 |
| 替代运行时 | 除 Node 外可用 **Deno** / **Bun** 跑同一个 `server.js`（`npm run` 脚本） | DeepWiki 引 `package.json:121-126` |
| **许可证** | **GNU Affero General Public License v3.0** | **已核实**：`https://raw.githubusercontent.com/SillyTavern/SillyTavern/release/LICENSE` 原文首行 = `GNU AFFERO GENERAL PUBLIC LICENSE / Version 3, 19 November 2007`；`sillytavern.wiki` 许可证段亦述 "根据 AGPL-3.0 许可证发布" |
| 活跃度 | 仍在活跃开发（本仓页面显示最近提交 2026-07-07） | github.com/SillyTavern/SillyTavern |

**结构结论（第一层）**：SillyTavern 是"**一个跑在本机 8000 端口的 Web 应用**"，不是"一个可被 import 的库"。它的 UI 是浏览器 DOM + CSS，**码铃是 PySide6 纯 Widgets、明确不做 WebView**（`research-tavern-game.md` §11.2 Non-goals 第 9 条）。两者之间**没有任何可嵌入的接缝**：既不能当组件塞进 QWidget 树，也不能把它当 Python 模块 import（它是 Node/JS）。

**结构结论（第二层，更致命）**：即便"跑一个 ST 服务、码铃用 `urllib` 去调它的 HTTP 接口"（纯标准库，理论上不违反 R-F 的字面），**AGPL-3.0 这一条就把它彻底否决了**：
- 码铃计划以 **MIT** 开源发布，而 `docs/THIRD_PARTY.md:4` 明确写死许可白名单"仅收 MIT / Apache-2.0 / BSD-3 / BSD-2 / 0BSD / CC0；**禁 GPL / AGPL / LGPL / SSPL**"（红线 **R-H**）；
- AGPL 是**强 copyleft**，第 13 条还专门覆盖"网络交互"场景；把它随包分发或作为服务端本体耦合，与"MIT 项目"直接冲突；
- **附带要求用户自行安装 Node.js + 跑 ST 服务**，也与"打包必须零第三方运行时依赖（R-F）"的产品承诺相悖。

### 1.2 "有没有 Python 版 / API-server 模式可用"（**已核实 + 一个重要的坑**）

**（a）Python 版：不存在。**
- 检索 `SillyTavern python port` 等关键词，**没有找到任何真实存在的、官方或社区维护的 SillyTavern 源码级 Python 移植**。
- ⚠️ **必须点名的检索陷阱**：搜索会稳定命中一批标题为《SillyTavern Python TavernAI Fork》的页面（`johal.in` 与 `www.johal.in` 的多个编号页）。这些页面属于 **AI 批量生成的内容农场**：正文自述所引仓库是 *"hypothetical Python fork at github.com/johal/sillytavern-python"*（**自承认是假设的**），并附带一整套无来源的"跑分表"（如 "Coherence 95.1%"、"45.2 t/s"）。**此类页面一律不可引用、不可作为选型依据**。凡看到"某项目有 Python 移植版且性能提升 40%"这类无仓库链接的说法，按内容农场处理。

**（b）API-server 模式：有，但它给不了我们想要的东西。**
- **ST 服务器插件（Server Plugins）**（**已核实**）：插件放在 `plugins/` 目录，需 `config.yaml` 里 `enableServerPlugins: true` 才加载；导出 `init(router)` 函数，用 **Express Router** 注册路由，挂在 `/api/plugins/{id}/{route}`。意味着**理论上**可以写一个插件给 ST 加自定义 HTTP 接口。但：① 语言仍是 **Node/JS**；② 官方文档明确警告"服务器插件**没有隔离**"，可访问整个文件系统、引入广泛安全漏洞；③ **受 AGPL-3.0 约束**（见 1.1）。
- **SillyTavern-extras**（**已核实存在**）：`SillyTavern/SillyTavern-extras` 是一个**真正的 Python 服务**，为 ST 提供 Extensions API（默认 `http://localhost:5100`），模块含 `summarize`（摘要）/ `classify`（情感分类）/ `caption` / `chromadb`（向量存储）等。这是"ST 生态里唯一的 Python 服务端"。
  - **但它不能用**：① 依赖是 torch / transformers / chromadb / coqui-tts / Selenium 级的**重依赖**，直接撞 R-F；② 官方定位是"给 ST 补能力"的伴生服务，不是可复用的叙事引擎；③ `Smart Context` 模块**已被标记 deprecated**；④ 其许可证**我未核实**（同属 SillyTavern org，**推测**与本体同为 AGPL-3.0，未经确认前按 AGPL 处理）。

### 1.3 所以：在 R-F 零依赖 + 无 WebView 前提下，SillyTavern 本体能"用到"的到底是什么？

**答案：只有三类东西，且都不是代码。**

| 能用的东西 | 形态 | 为什么不受 R-F 约束 | 在 v3 方案里的落点 |
|---|---|---|---|
| **① 机制（机制设计知识）** | 文档级描述：世界书的关键词触发 / 预算裁剪 / 三级排序淘汰、Prompt Manager 的"位置即权重"、Author's Note 的频率控制、swipe/regenerate 的"生成类型"思想 | 是**知识**，不是代码 | `research-tavern-game.md` §2 已经把 7 个机制逐条落成"抄什么 / 改成什么形态"——**这部分本报告确认：该文档做得对，且这就是 ST 唯一可用的部分** |
| **② 数据格式与公开规范** | 角色卡 CCv2 / CCv3 的字段结构；lorebook / `character_book` 的条目字段（`keys` / `secondary_keys` / `content` / `constant` / `insertion_order` / `priority` / `position` / `use_regex` / `selective` / `scan_depth` / `token_budget` / `recursive_scanning`） | **数据格式不受 R-F 约束**（格式不是"运行时依赖"）；照搬格式 = 零代码、零依赖 | `docs/character-card-spec.md` 的兼容性参照；酒馆世界书条目字段表（§2.2） |
| **③ 官方/社区文档里的阈值与规范** | ST 官方文档对"触发 / 预算 / 插入位置"的规范说明；chub.ai 的 lorebook 字段说明 | 同上（文档引用） | §2.2 的落点选择（`before_char` / `after_char` / depth / role）与 `scan_depth` 语义 |

**一句话**：ST 给码铃的是**一本"上下文工程设计手册" + 一套"可照搬的数据格式"**，**没有一行代码能用**。

---

## 2. 候选清单（按可复用粒度分三类，逐条给证据与裁决）

> **裁决口径**：`可直接采纳` / `可借鉴机制，不引代码` / `许可证不允许` / `依赖太重否决` / `维护已死`。
> **诚实标注**：凡我未实际打开页面确认的项，一律写"**未核实**"；凡仓库无 LICENSE 文件，一律写"**许可证查不到**"，**绝不以 README 徽章或第三方聚合站代替**。

### 2.1 类别一：纯 Python、零/极轻依赖的交互式小说 / 文字冒险 / 状态机引擎（第一优先）

| 候选 | 语言 | 许可证 | 依赖 | 维护状态 | 裁决 |
|---|---|---|---|---|---|
| **`pytwee`** `github.com/jixingcn/pytwee` | **纯 Python** | **MIT**（已核实：PyPI `license_expression="MIT"` + `license_files=["LICENSE"]`；README 徽章指向 `blob/main/LICENSE`） | **零**（已核实：PyPI `requires_dist = null`；piwheels 亦标 "Dependencies None"；wheel `py3-none-any`） | 0.3.3 / 2025-06-20 发布；Alpha（`Development Status :: 3 - Alpha`）；**star 数未核实** | **可直接采纳**（以源码移植入库形式），**但收益有限** —— 见 §3.3 |
| `COUR4G3/inkpy` `github.com/COUR4G3/inkpy` | 纯 Python | **⚠️ 自相矛盾**：`pyproject.toml` 写 `license = { text = "MIT" }`，但同一文件的 classifier 写 `License :: Other/Proprietary License`；**仓库根目录无 LICENSE 文件**（已核实文件树） | **零**（已核实 `dependencies = []`） | **停更**：最后提交 2024-02-14，共 35 commits，无 release | **维护已死**（且许可证不可靠 → 不可用） |
| `clembu/inkpy` `github.com/clembu/inkpy` | 纯 Python | MIT（仓页标 MIT license） | — | **已归档 + 作者自述废弃**：README 首行 "THIS PROJECT IS ABANDONNED"，正文 "It doesn't work, there's TypeErrors everywhere. It's okay, I don't care" | **维护已死** |
| `cproctor/inkpy` `github.com/cproctor/inkpy` | 纯 Python | **许可证查不到**（仓页文件树无 LICENSE） | — | 17 commits，README 全是 TODO，未实现 branch/call_stack/choice 等 | **许可证不允许**（无许可 = 保留全部权利，不可用） |
| `Bardic` `github.com/katelouie/bardic`（PyPI `bardic`） | Python | MIT（PyPI 元数据） | **核心依赖 2 个：`click>=8.0`、`graphviz`**（已核实 PyPI JSON `requires_dist`） | 活跃：0.10.2，2026；Alpha；25 stars（PyPI 页显示） | **依赖太重否决**（+2 运行时依赖，撞 R-F；且它是"编译器 + DSL"，引入即要改内容格式） |
| `P1wan/TexAdvent` | Python | MIT（README 述） | 有 `requirements.txt`（内容未核实） | 2025-05 起 10 commits，README 自述 features 是 "planned"，demo "only prints a placeholder" | **维护已死**（骨架阶段） |
| `Jgshep/Python-Text-Adventure-Engine` | Python | MIT（仓页标） | 无第三方（3 个文件） | 玩具级练习项目，含战斗/HP 数值 | **依赖/规模否决**（价值低于自己写）+ R-A 冲突 |
| `TheHackersWorkshop/forgotten_ship` | Python | MIT（仓页标） | 纯标准库 | 0 stars，18 commits，最近 2026-03 | **不值得引**（JSON 驱动终局型冒险，仅 1 人维护，机制价值低于 §6.1） |
| LevelKit-Text（`benjaminhyde.com.au/projects/levelkit-text`） | Python | 未核实（个人站项目页，无仓库链接） | **零第三方（仅标准库 + Tkinter）** | 未核实（个人项目页） | **R-A 冲突否决**（内置 XP 等级 / 回合制战斗 / 生命值 / 掉落，正面撞无焦虑红线） |
| `pyinklib`（PyPI） | Python | MIT | 1 个：`pyyoga>=0.1.0` | 2026 年新发布 | **误命中，与本议题无关**：它是 React 终端 UI 库 **Ink**（Vadim Demedes）的移植，**不是 inkle 的 ink 叙事语言**。**列出仅为防止后续被同名误导** |
| `videlais/extwee` | **JS / Node（npm）** | MIT（40 stars，最近 push 2026-01-21） | npm | 活跃 | **语言不符否决**（Node 库，不能进 Python 运行时；只能当**机制参照**） |

**类别一小结**：**没有**任何"纯 Python + 零依赖 + 许可证可核实 + 维护活着 + 能提供状态机/叙事引擎"的候选。
- `ink` 谱系（inkle 的 ink 叙事语言）的 4 个 Python 移植**全部不可用**：1 个作者自述废弃、1 个停更且许可证自相矛盾、1 个无许可证、1 个是未完成骨架。**且即便它们可用**，ink 运行时消费的是**编译后的 `.ink.json`**，而编译 `.ink → .ink.json` 的正统工具是 **C#（ink 官方）/ JS（inkjs）**——**Python 侧没有可用的编译器**，端到端仍然跑不通。
- `Bardic` 是这一格里**最现代、最活跃**的候选，但两个核心依赖直接否决。

### 2.2 类别二：LLM 角色扮演 / 文字 RPG 框架，或"机制实现"（第二优先）

| 候选 | 语言 | 许可证 | 关键依赖 | 维护 | 裁决 |
|---|---|---|---|---|---|
| **`SillyTavern/SillyTavern-extras`** | Python | **未核实**（同 org，**推测** AGPL-3.0，未证实前按 AGPL 处理） | torch / transformers / chromadb / coqui-tts / Selenium 级 | 存在；`Smart Context` 已 deprecated | **依赖太重否决**（+ AGPL 风险） |
| `DesvoSoft/DungeonCore` `github.com/DesvoSoft/DungeonCore` | Python + **Plotly Dash** | **未核实**（仓页文件树无 LICENSE） | Plotly Dash；需 LM Studio 本地服务 | WIP / MVP，Phase 1 才在做存读档 | **可借鉴机制，不引代码** —— 它**强制 LLM 返回结构化 JSON**（`Narrative` + `State Deltas` + `Choices`），由 Python 侧做状态数学更新。**这正是 §4.2 `propose` 档的同一思想**，是本轮检索里**机制上最贴近**的一个 |
| `Heretyc/RAID` `github.com/Heretyc/RAID` | Python 3.13+ | **Apache-2.0**（README 明确 + LICENSE） | `sqlite-vec` + `FTS5` 向量/关键词混合检索、RRF 融合 | "active early development" | **依赖否决**（向量库 + 明确不用重框架/云服务，但自身依赖已超 R-F） |
| `Sinjan-Debnath/MemoryForge` | Python（Notebook） | MIT（仓页标 + LICENSE） | ChromaDB / Pinecone / all-MiniLM-L6-v2 / Groq API | 2025-10 初始提交，Notebook 形态 | **依赖否决**（向量 RAG；且 Notebook 不可产品化） |
| `Raven95676/astrbot_plugin_lorebook_lite`（GitHub / Gitee 双源） | Python | **未核实**（文件树有 LICENSE，类型未确认） | **`python-dateutil` + `kwmatcher`**（2 个） | 39 commits，最近改动 2025-05（元数据 2026-03） | **依赖否决（代码）／机制高度可借鉴** —— 它有 `world_state` / `user_state`、**变量值占位符解析**、**作用域继承**、按会话/人格**隔离** lorebook、触发计数与重置。**这几条与 §6.2 的 `vars`、§6.3 的"不互相污染"是同一批问题**，值得作为设计参照 |
| `Krishnaag23/narrative-core` | Python | 未核实 | OpenAI / HF Transformers / spaCy / **ChromaDB** / NetworkX / Langchain | — | **依赖否决** |
| `ATAIN000/story` | Python + uvicorn 后端 | 未核实 | 315 题材 × 20 层世界观，依赖未核实 | — | **依赖否决**（且体量与形态远超需求） |
| `albinks/narrative` | Python 3.12+ | MIT（README 述） | Poetry 管理（依赖未核实） | — | **未核实，暂不采纳**（"符号规划 + LLM"，思路可看，但成本远高于自写） |
| `zukijourney/openshapes`（lorebook 子系统） | Python（Discord bot） | 未核实 | 整套 bot 框架 | — | **仅机制参照**：其 lorebook 是"JSON 数组 + case-insensitive 子串匹配"，**极简**，可作为"世界书最小形态"的下限参照 |
| `luokeychen/comfyui_LLM_party` 的 `tools/lorebook.py` | Python | 未核实 | ComfyUI | — | **仅机制参照**：**约 60 行**，"冒号分行的 KV + 子串命中即拼接"——证明**世界书的触发层本身极简**，不需要引任何库 |

**类别二小结**：这一格里**几乎所有候选都依赖向量库 / torch / transformers**（RAG 派），**全部撞 R-F**；而**不依赖向量**的那几个（DungeonCore、lorebook_lite、comfyui 的 lorebook.py）**恰好都只是"机制"级别的启发**，且其实现短到"自己写更划算"。
- **关键洞察**：这类项目里真正有价值的**不是代码，而是"结构化输出 + 本地校验"这一条架构选择**——它**已经被 `research-tavern-game.md` §4.2 独立推导出来了**（且 §3.3 用 arXiv:2605.24719 做了学术佐证）。**不需要引任何开源代码来获得这条结论。**

### 2.3 类别三：SillyTavern 的周边资产（格式与规范，**不受 R-F 约束**，第三优先）

| 资产 | 链接 | 许可证 | 状态 | 裁决 |
|---|---|---|---|---|
| **Character Card V3 规范（CCv3）** | `github.com/kwaroran/character-card-spec-v3`（`SPEC_V3.md` / `concepts.md`） | **MIT**（**已核实**：文件树有 `LICENSE`，提交记录 `Add MIT license` @ 2024-05-28） | 最后提交 2024-07-20；当前状态自列为"提案 / 待批准" | **可直接采纳（作为规范引用）**。V3 相对 V2 的增量：**原生 lorebook 结构**（不再是把 lorebook 塞成字符串）、多语言资产、更丰富的 creator 元数据；PNG 内嵌用 `ccv3` tEXt chunk（base64 UTF-8 JSON）；新增 `.charx`（zip）容器格式 |
| **Character Card V2 规范（CCv2）** | `github.com/malfoyslastname/character-card-spec-v2`（`spec_v1.md` / `spec_v2.md` / `keyword_definitions.md`） | **⚠️ 许可证查不到**（**已核实**：文件树仅 README + 3 个 md，**无 LICENSE 文件**，README 未提许可） | 最后提交 2023-06-22 | **可引用格式，不可复制正文**。V2 定了 `spec="chara_card_v2"`、六字段必填 + v2 新增字段、`character_book`、`alternate_greetings` 等；**字段结构是可照搬的事实，但规范文本著作权无明确许可 → 只引用字段名与语义，不整段抄正文** |
| **lorebook / `character_book` 字段结构** | CCv2 规范的 `character_book` 段；chub.ai 文档《Lorebooks》；DeepWiki 的 ST `world-info.js` 源码级结构 | 同 CCv2（无许可）/ 文档页（引用） | — | **可直接照搬字段模型**。已核实的字段名：`keys[]` / `secondary_keys[]` / `content` / `constant` / `insertion_order` / `priority` / `case_sensitive` / `use_regex` / `enabled` / `selective` / `comment` / `position`（`before_char` / `after_char`） / `scan_depth` / `token_budget` / `recursive_scanning` / `extensions{}` |
| **ST 官方文档（World Info / Prompt Manager / Author's Note / STscript）** | `docs.sillytavern.app/...`（另有中文 `sillytavern.wiki`、`sillytavern.wiki` 镜像） | 文档站，引用性质 | 活跃 | **可直接引用**（**注意**：文档随 AGPL 项目发布，**引用与被引用的说明性使用**不等于复制代码；**不得抄录其文档正文段落进本项目文档**，只做"结论 + 链接"） |
| **Twine / Twee 3 规范** | `github.com/iftechfoundation/twine-specs` | **未核实** | 活跃 | 若采纳 `pytwee`，需要它；**本次未核实其许可证，若要在文档中引用需另做核实** |
| `@character-foundry/schemas` | `github.com/character-foundry/character-foundry`（`docs/schemas.md`） | **未核实** | — | **仅参照**：TS/Zod 写的 CCv2/CCv3/Voxta/Risu 类型定义。**是**一份很好的"字段全集"清单（含 CCv2/CCv3 完整字段），但它是 **Node/TS**，不可用代码 |

**类别三小结（这格是唯一"划算"的一格）**：
- **CCv3 规范 = MIT，可安全引用/采纳为格式参照**；**CCv2 规范 = 无许可证，只能引用字段事实，不能抄正文**。**这是本次调研里唯一一条"明确许可证状态 + 明确可用"的资产结论。**
- 但要注意：**酒馆并不需要新造角色卡格式**——`research-tavern-game.md` §2.1 已经拍板"沿用码铃 `.malingcard.json`（schema v2），不另造格式"。所以 CCv3 的真正用途是**给未来"卡互操作/导入预览"提供一份规范依据**，而不是 P0 需求。

---

## 3. 裁决汇总表 + 三个关键问答

### 3.1 裁决汇总（一行一候选）

| # | 仓库 | 语言 | 许可证 | 裁决 | 一句话理由 |
|---|---|---|---|---|---|
| 1 | **SillyTavern/SillyTavern** | Node/JS + 浏览器 | **AGPL-3.0**（已核实） | **许可证不允许**（叠加"结构不可嵌入"） | Web 应用而非库；AGPL 撞 R-H 白名单，比语言不匹配更硬 |
| 2 | **jixingcn/pytwee** | **纯 Python** | **MIT**（已核实） | **可直接采纳（源码移植）；但收益有限** | 唯一同时满足零依赖 + 纯 Python + MIT 的候选；但只是 Twee 解析器 |
| 3 | COUR4G3/inkpy | Python | 自相矛盾（pyproject=MIT / classifier=Proprietary / **无 LICENSE 文件**） | **维护已死 + 许可证不可靠** | 2024-02 停更，35 commits，无 release |
| 4 | clembu/inkpy | Python | MIT | **维护已死** | 作者自述废弃："It doesn't work, there's TypeErrors everywhere" |
| 5 | cproctor/inkpy | Python | **查不到（无 LICENSE）** | **许可证不允许** | 无许可 = 保留所有权利；且是未完成骨架 |
| 6 | katelouie/bardic | Python | MIT | **依赖太重否决** | 核心依赖 `click` + `graphviz`（+2 运行时依赖 → 撞 R-F） |
| 7 | videlais/extwee | **JS/Node** | MIT | **语言不符否决**（可当机制参照） | 40 stars 活跃，但 npm 包不能进 Python 运行时 |
| 8 | SillyTavern/SillyTavern-extras | Python | 未核实（推测 AGPL） | **依赖太重否决** | torch/transformers/chromadb 级重依赖 |
| 9 | DesvoSoft/DungeonCore | Python + Dash | 未核实 | **可借鉴机制，不引代码** | "LLM 出结构化 JSON + 本地执行状态"= §4.2 `propose` 档同源思想；Dash 依赖否决 |
| 10 | Heretyc/RAID | Python 3.13+ | **Apache-2.0**（已核实 README） | **依赖否决** | sqlite-vec 向量 + RRF 混合检索 |
| 11 | Sinjan-Debnath/MemoryForge | Python Notebook | MIT | **依赖否决** | ChromaDB / Pinecone / MiniLM |
| 12 | Raven95676/astrbot_plugin_lorebook_lite | Python | 未核实 | **依赖否决（代码）／机制高度可借鉴** | `python-dateutil` + `kwmatcher`；但 world_state/user_state/作用域继承/占位符值得看 |
| 13 | comfyui_LLM_party `tools/lorebook.py` | Python | 未核实 | **仅机制参照** | ~60 行证明"世界书触发层极简，不必引库" |
| 14 | zukijourney/openshapes 的 lorebook 子系统 | Python | 未核实 | **仅机制参照** | 世界书最小形态 = JSON 数组 + 子串匹配 |
| 15 | P1wan/TexAdvent | Python | MIT | **维护已死** | README 自述功能均为 "planned" |
| 16 | LevelKit-Text | Python + Tkinter | 未核实 | **R-A 冲突否决** | 内置 XP/战斗/HP 数值，正面撞无焦虑红线 |
| 17 | kwaroran/character-card-spec-v3 | 规范文档 | **MIT**（已核实） | **可直接采纳（规范引用）** | 含原生 lorebook 结构；`.`charx` 容器 |
| 18 | malfoyslastname/character-card-spec-v2 | 规范文档 | **查不到（无 LICENSE）** | **可引用字段，不可抄正文** | 字段结构是事实；规范文本著作权无许可 |
| 19 | pyinklib（PyPI） | Python | MIT | **无关（误命中）** | 是 React 终端 UI 库 Ink 的移植，与叙事语言 ink 无关 |

### 3.2 问题一：有没有**任何一个**候选能满足"纯 Python + 零运行时依赖 + 许可证兼容"？

**有，且只有一个：`jixingcn/pytwee`（MIT + 零依赖 + 纯 Python）。**

但它**能替我们省掉的部分，比预期小得多**：

| 它**能**省的 | 对应 v3 的哪一块 |
|---|---|
| Twee 3 语法解析（`.twee` / `.tw` 文件的 `:: Passage` 头、`StoryTitle` / `StoryData`、`script` / `stylesheet` 特殊 tag） | `research-tavern-game.md` §7.2 **域4**（内容包加载）里"把人类可读的作者格式读进来"这一层前置 |
| Story → Twine 2 JSON 的序列化 | 仅当我们要做"导出为 Twine 可读"时的出口 |

| 它**完全替不了**的 | 对应 v3 的哪一块 |
|---|---|
| 状态机（`apply(transform)` + 三条不变量 + 硬禁区） | §6.1 `engine.py`（**域2**） |
| 世界书（关键词触发 / selective logic / 预算裁剪 / 递归上限 / 脏正则） | §6.1 `worldbook.py`（**域4**） |
| 三级意图路由（verbatim / propose / narrate + 留痕） | §6.1 `intent_router.py`（**域3**） |
| 五段式 prompt 组装 + reroll 差异 | §6.1 `prompt.py` / `summarize.py`（**域5**） |
| 存档（schema 版本 / 原子写 / 读时迁移 / 快照轮转） | §6.1 `store.py` / `model.py`（**域1**） |
| 5 Tab UI 与四主题融合 | §6.1 `page_tavern.py` / `widgets/tavern/**`（**域6**） |

**实话**：pytwee 省下的是 §7.2 里**一个子步骤的一部分**（内容格式前端解析），而它引入的成本是——**引入一门新的作者格式（Twee 3）+ 一次源码移植 + 一层 Twine JSON ↔ storylet JSON 的双向映射**。**净收益为负或接近零。**
**结论：pytwee 技术上"可采纳"，工程上"不建议采纳"（至少 P0 不要）。**

### 3.3 问题二：如果没有可直接改的开源 → 最接近的是什么、差在哪？

**"没有可直接改的开源"这个结论在"能替换 `gui/tavern` 引擎内核"的意义上成立。** 最接近的三个，分别差在三个不同的维度：

| 最接近的 | 差在哪（**这是关键**） |
|---|---|
| **`pytwee`（最接近"合规"）** | **差在功能层级**：它是"内容格式解析器"，**不是引擎**。它没有状态、没有变换、没有不变量、没有预算、没有路由。它解决的是"作者怎么写字"，而 v3 需要的是"世界怎么改状态"。**它的输出（Twine 2 JSON 的 passages + links）与我们的 storylet（`{id, title, text, llm_brief, prerequisites, effects, choices[]}`）不同构**，中间层要自己写 |
| **`Bardic`（最接近"现代 + 活跃"）** | **差在两个运行时依赖**（`click` + `graphviz`）→ 撞 R-F；**且差在形态**：它是"DSL + 编译器"，引入即要改内容格式与构建链（要加一步 `bardic compile`），而码铃的内容是**随包分发的 JSON 数据**（`gui/tavern/content/**`），不需要编译期。另外它的 stdlib 里有 `economy`（钱包/商店）与 `relationship`（好感阈值）—— **这两个直接撞 R-A 无焦虑红线** |
| **`DesvoSoft/DungeonCore`（最接近"机制"）** | **差在依赖与成熟度**（Plotly Dash + LM Studio；许可证未核实；MVP 阶段）。但它的**架构判断与 §4.2 完全同源**：让 LLM 只输出结构化 JSON（叙述 + 状态增量 + 选项），由 Python 侧做状态更新。**它证明了这条路是"别人也这么做"的，而不是码铃的孤例** —— 这本身就是有价值的旁证（与 §3.3 的 arXiv:2605.24719 一起，构成三方独立佐证） |

---

## 4. 许可证与登记（若存在可采纳候选）

### 4.1 可采纳候选的许可证事实

| 候选 | 许可证 | 与 MIT 的兼容性 | 需要保留什么 |
|---|---|---|---|
| **`jixingcn/pytwee`** | **MIT**（已核实：PyPI `license_expression="MIT"`、`license_files=["LICENSE"]`；GitHub 仓 `LICENSE` 存在） | **完全兼容**（MIT → MIT 是最宽松方向） | ① **原版权行照抄**（year + author；作者名从 LICENSE 原文取，**本次未逐字读取 LICENSE 原文，实施前必须打开 `blob/main/LICENSE` 取准确版权行**）；② **LICENSE 全文副本入库**（`docs/third_party_licenses/`）；③ 移植文件头加"码铃移植说明块"；④ `docs/THIRD_PARTY.md` 表一条目；⑤ About 页「内置开源组件」列一行 |
| **`kwaroran/character-card-spec-v3`** | **MIT**（已核实） | **完全兼容** | 同上；但**若只引用字段模型、不复制规范正文，则不需要 LICENSE 副本**——**建议只引用** |
| **`malfoyslastname/character-card-spec-v2`** | **查不到**（无 LICENSE 文件） | **不可复制正文**（无许可 = 保留所有权利） | **只允许引用"字段名 + 语义"这类事实**；**不得整段摘录规范文本进本项目仓库** |
| **SillyTavern / ST 文档 / ST-extras** | **AGPL-3.0**（本体已核实）/ 未核实 | **不兼容**（R-H 明令禁止） | **任何形式都不可引入**（含随包分发、含作为服务端耦合、含整段抄录文档正文） |

### 4.2 本项目**实际**的登记位置（**已核实**，非推测）

> 项目已有一套成熟的第三方登记机制（v1.4 方向 A 建立、v1.9 / v2.1 扩展）。**任何新引入的第三方代码必须同时落这 4 处**（`docs/THIRD_PARTY.md` 里"R-R② 四处登记"的既有口径）：

| # | 登记位置 | 实际路径 | 说明 |
|---|---|---|---|
| ① | **主登记台账** | **`docs/THIRD_PARTY.md`** | "一、已纳入组件"表：项目 / 仓库 / **commit 或复核版本** / 许可（实际 LICENSE 文件核验） / 原版权行 / 入库文件 / 改动摘要 / 复核日期 / 复核人。另设"二、参考未采用（仅借鉴形态，未复制代码）"表 —— **纯机制借鉴应登记在此表** |
| ② | **许可全文副本（源树）** | **`docs/third_party_licenses/<owner>_<repo>.txt`** | 现有命名实例：`tangentecode_2048-pyqt6.txt`、`dawsonbooth_pynsweeper.txt`、`remix_icon.txt`、`earendil-works_pi-coding-agent.txt`、`OFL-Resource-Han-Rounded.txt`、`OFL-jf-open-huninn.txt` |
| ③ | **运行时依赖台账** | **`NOTICE`**（仓库根） | `docs/THIRD_PARTY.md` 第五节明确："依赖以 `requirements.txt` / `requirements_gui.txt` 锁定的运行为准……完整列表与说明见仓库根 **`NOTICE`** 文件"。**R-F 要求 `requirements*.txt` diff 为空 → 源码移植入库的东西不进这里** |
| ④ | **应用内可见** | **About 页「内置开源组件」** | `docs/THIRD_PARTY.md` 多处提到（字体条目 ②、图标条目 ③）；对应文件 **`gui/pages/page_about.py`（已核实存在）** —— 条目内容本次未打开核对 |

**若未来移植 pytwee，需新增**：
- `docs/third_party_licenses/jixingcn_pytwee.txt`（LICENSE 全文）
- `docs/THIRD_PARTY.md` 表一条目：仓库 URL + **锁定 commit/tag（建议 `0.3.3` 对应 commit）** + `MIT` + 原版权行 + 入库文件路径 + 改动摘要（"Py3 纯 Python 单包移植；去 CLI 入口；只用 `twee3.Parser`"）
- About 页加一行
- **`requirements*.txt` diff 必须仍为空**（R-F）

---

## 5. 最终建议

### 5.1 建议：**走"自己按机制实现"，不引第三方代码**

**三条理由（按硬度排序）：**

1. **R-F 已经替我们把"引库"这条路封死了。**
   "零新增运行时第三方依赖"意味着**任何**第三方候选都不能以 `import` 形式存在，只能**源码移植入库**。而移植一个**引擎**（不是像 2048/扫雷那样的独立小控件）意味着：把它整套数据模型、错误语义、生命周期一起搬进来，再和码铃的"单写点 / 原子写 / 读时迁移 / 主题 token / 动效纪律"逐条对齐——**这比按 §6.1 自己写一遍更贵，且引入了不可控的外部设计债务**。

2. **R-H 把整个 LLM 角色扮演生态的主要供给排除了。**
   这个生态里最成熟、最活跃的实现（**SillyTavern 本体 AGPL-3.0**、其周边、以及大量 GPL 系的 IF 引擎）**按白名单一律出局**。剩下的 BSD/MIT 侧，要么是停更/废弃的 `inkpy` 系列（4 个全部不可用），要么是重依赖的 RAG 框架（全部撞 R-F），要么是玩具级骨架。

3. **R-A + "数据不乱"把"能用"进一步收窄到"几乎没有"。**
   可用的 Python 游戏/叙事引擎普遍内置**经验值、等级、战斗、生命值、掉落、经济**（LevelKit-Text、Bardic 的 `economy`/`relationship`、DungeonCore 的 HP/Gold），**与 R-A 无焦虑红线正面冲突**；而 §6.2 那套"`vars` 键名受内容包白名单约束 / `transcript` append-only / `journal` 与 `plays` 物理隔离 / 三条不变量 / 显式 seed" 是**码铃特有的数据纪律**，**没有哪个外部引擎会替我们满足**。

### 5.2 但不要浪费这次调研：**三样东西应当吸收进 v3 方案**

| 吸收什么 | 来源（本次核实） | 落点 |
|---|---|---|
| **"LLM 只输出结构化 JSON（叙述 + 状态增量 + 选项），状态由本地代码更新"** 这条架构判断，**有三方独立佐证** | ① `DesvoSoft/DungeonCore`（同上，README 明述"ensures the game state is tracked mathematically by Python, preventing the AI from hallucinating the player's health or inventory"）② `research-tavern-game.md` §3.3 的 arXiv:2605.24719 ③ 本报告 §2.2 的 `MemoryForge`/`narrative-core` 亦在做"生成与校验分离" | **强化 §4.2 的信心**：`propose` 档不是码铃独创，`verbatim → propose → narrate` 的三级降级是对"未证明可靠性"的额外对冲（比 DungeonCore 更保守、更稳） |
| **lorebook 的触发层极简**（≈60 行：KV 存储 + 子串命中 + 拼接） | `comfyui_LLM_party/tools/lorebook.py`；`zukijourney/openshapes` 的 `LorebookManager` | **给 §2.2 / 域4 定体量预期**：触发层不该被做重；世界的复杂度应当压在**条目撰写规范**（§3.2-⑥）与**预算裁剪**上，而不是检索算法上 |
| **`world_state` / `user_state` 分离 + 作用域继承 + 按会话/人格隔离** | `Raven95676/astrbot_plugin_lorebook_lite` | **给 §6.2 / §6.3 做交叉验证**：它的"按会话隔离 + 全局状态 vs 用户状态分离"与码铃的"`journal`（跨局累积）vs `plays[]`（单局）物理分离"是**同一问题的两种解**，说明 §6.2 的切分方向是对的 |

### 5.3 具体行动建议

| 优先级 | 建议 |
|---|---|
| **P0** | **不引入任何第三方代码。** 按 `research-tavern-game.md` §7.2 批 0–5 执行。 |
| **P1（可选，且需单独评估）** | 把 **CCv3 规范（MIT）** 作为**规范引用**补进 `docs/character-card-spec.md` 的"外部参照"一节 —— **只引字段模型 + 链接，不抄正文**。**注意 CCv2 无许可证，只引字段名** |
| **不建议** | 移植 `pytwee`（净收益≈0）、移植 `Bardic`（+2 依赖）、任何形式的 ST 代码/服务耦合（AGPL） |
| **登记动作** | 若采纳 P1：在 `docs/THIRD_PARTY.md` **"二、参考未采用"** 表登记 CCv2/CCv3 与 ST 文档为"仅借鉴格式/规范，未复制代码"；若最终移植了任何 MIT 代码，才走 §4.2 的四处登记 |

---

## 附录 A：证据链接汇总（**均为本次实际访问**）

**SillyTavern 技术栈与许可**

1. SillyTavern 仓库（活跃度：最近提交 2026-07-07）：https://github.com/SillyTavern/SillyTavern
2. **ST 许可证原文（AGPL-3.0 已核实）**：https://raw.githubusercontent.com/SillyTavern/SillyTavern/release/LICENSE
3. ST 依赖与运行时（Node 20+ / ESM / Express / 客户端库清单，引 `package.json`）：https://deepwiki.com/SillyTavern/SillyTavern/1.2-system-dependencies-and-libraries
4. ST 中文文档·许可证段（"根据 AGPL-3.0 许可证发布"）：https://sillytavern.wiki/
5. ST 中文文档·安装要求（NodeJS 18+）：https://sillytavern.wiki/#%E5%88%86%E6%94%AF/
6. ST Docker 安装（HTTP 服务 + 端口映射 + 卷映射）：https://sillytavern.wiki/installation/docker/
7. ST 服务器插件机制（Express Router / `/api/plugins/{id}/{route}` / "插件未隔离"警告）：https://sillytavern.wiki/for-contributors/server-plugins/
8. ST 命令行参数表（`--port` / `--listen` / `--dataRoot` 等）：https://github.com/likethis85/SillyTavern
9. **SillyTavern-extras（ST 生态里的 Python 服务，默认 5100）**：https://github.com/chrisbennight/sillytavern-extras 与 https://github.com/SillyTavern/SillyTavern-extras（后者经前者的 README 引用确认存在）
10. ⚠️ **内容农场反例（不可引用）**：https://johal.in/sillytavern-python-tavernai-fork-silly-roleplay-features-7 （正文自述 "hypothetical Python fork at github.com/johal/sillytavern-python"）

**类别一：纯 Python 叙事引擎**

11. **pytwee（MIT / 零依赖 / 纯 Python）**：https://github.com/jixingcn/pytwee
12. pytwee PyPI 元数据（`license_expression=MIT`、`requires_dist=null`、0.3.3 @ 2025-06-20）：https://pypi.org/pypi/pytwee/json
13. pytwee 依赖确认为 None：https://www.piwheels.org/project/pytwee/
14. pytwee 使用文档：https://pytwee.readthedocs.io/en/latest/usage.html
15. COUR4G3/inkpy（pyproject=MIT / classifier=Other-Proprietary / 无 LICENSE 文件 / `dependencies=[]` / 最后提交 2024-02-14）：https://github.com/COUR4G3/inkpy 与 https://raw.githubusercontent.com/COUR4G3/inkpy/master/pyproject.toml
16. clembu/inkpy（作者自述废弃）：https://github.com/clembu/inkpy
17. cproctor/inkpy（无 LICENSE / 未完成骨架）：https://github.com/cproctor/inkpy
18. Bardic（MIT / 核心依赖 click + graphviz）：https://pypi.org/project/bardic/ 与 https://pypi.org/pypi/bardic/json
19. Bardic 0.7.0 页（25 stars / Alpha）：https://pypi.org/project/bardic/0.7.0
20. P1wan/TexAdvent（MIT / 功能均为 planned）：https://github.com/P1wan/TexAdvent
21. Jgshep/Python-Text-Adventure-Engine（MIT / 玩具）：https://github.com/Jgshep/Python-Text-Adventure-Engine
22. TheHackersWorkshop/forgotten_ship（MIT / 0 stars）：https://github.es/TheHackersWorkshop/forgotten_ship
23. LevelKit-Text（零依赖仅标准库 + Tkinter，但含 XP/战斗/HP）：https://benjaminhyde.com.au/projects/levelkit-text
24. pyinklib（**误命中**：React 终端 UI 库 Ink 的移植）：https://pypi.org/project/pyinklib/1.1.9
25. videlais/extwee（MIT / JS-Node / 40 stars / 2026-01 push）：https://awesome.ecosyste.ms/projects/github.com%2Fvidelais%2Fextwee

**类别二：LLM 角色扮演 / 文字 RPG 框架**

26. DesvoSoft/DungeonCore（Python + Dash / 结构化 JSON 输出 / 许可证未核实）：https://github.com/DesvoSoft/DungeonCore
27. Heretyc/RAID（Apache-2.0 / sqlite-vec + FTS5 + RRF）：https://github.com/Heretyc/RAID
28. Sinjan-Debnath/MemoryForge（MIT / ChromaDB + Pinecone）：https://github.org/Sinjan-Debnath/MemoryForge
29. Raven95676/astrbot_plugin_lorebook_lite（world_state/user_state / 作用域继承 / 依赖 python-dateutil + kwmatcher）：https://gitee.com/Raven95676/astrbot_plugin_lorebook_lite
30. comfyui_LLM_party `tools/lorebook.py`（~60 行极简世界书）：https://github.com/luokeychen/comfyui_LLM_party/blob/main/tools/lorebook.py
31. zukijourney/openshapes 的 lorebook 子系统（JSON 数组 + 子串匹配 / `LorebookManager`）：https://deepwiki.com/zukijourney/openshapes/6.2-lorebook-system
32. Krishnaag23/narrative-core（ChromaDB / NetworkX / spaCy，依赖否决）：http://ghub.com/Krishnaag23/narrative-core
33. ATAIN000/story（重体量，依赖否决）：https://github.com/ATAIN000/story
34. albinks/narrative（MIT 述 / "符号规划 + LLM"）：https://github.com/albinks/narrative

**类别三：SillyTavern 周边资产（格式与规范）**

35. **Character Card V3 规范（MIT，已核实 LICENSE + "Add MIT license" 提交）**：https://github.com/kwaroran/character-card-spec-v3 与 https://github.com/kwaroran/character-card-spec-v3/blob/main/SPEC_V3.md
36. **Character Card V2 规范（无 LICENSE 文件，许可证查不到）**：https://github.com/malfoyslastname/character-card-spec-v2
37. V2/V3 字段差异与 2026 现状（第三方整理，**辅助理解，非权威**）：https://honeychat.bot/en/blog/ai-character-cards-guide-v2-v3-2026/
38. lorebook 字段结构（CCv2 `character_book` 段，Go 实现侧的类型定义，字段名可交叉核对）：https://pkg.go.dev/cnb.cool/limxsaikou/characard
39. CCv2/CCv3 类型定义全集（TS/Zod，**仅参照，不可用代码**）：https://github.com/character-foundry/character-foundry/blob/master/docs/schemas.md
40. chub.ai《Lorebooks》（scan depth / token budget / priority / recursive scanning）：https://docs.chub.ai/docs/venus-documentation/lorebooks
41. Twine/Twee 3 规范（**许可证未核实**）：https://github.com/iftechfoundation/twine-specs/blob/master/twee-3-specification.md

**仓内依据（只读引用）**

42. `docs/THIRD_PARTY.md:4`（R-H 许可白名单：MIT/Apache-2.0/BSD-3/BSD-2/0BSD/CC0；禁 GPL/AGPL/LGPL/SSPL）
43. `docs/THIRD_PARTY.md:8-14`（"一、已纳入组件"表格式，含"实际 LICENSE 文件核验"与"原版权行"两列）
44. `docs/THIRD_PARTY.md:36-40`（"二、参考未采用（仅借鉴形态，未复制代码）"表 —— 纯机制借鉴的登记位）
45. `docs/THIRD_PARTY.md:86-102`（R-R② "四处登记"口径：本表 + 源树许可全文 + 随包许可副本 + About 页）
46. `docs/THIRD_PARTY.md:106-126`（"五、运行时依赖"表 + 指向仓库根 `NOTICE`；PySide6 = LGPL-3.0 动态链接）
47. `docs/third_party_licenses/` 实际文件命名实例：`tangentecode_2048-pyqt6.txt`、`dawsonbooth_pynsweeper.txt`、`remix_icon.txt`、`earendil-works_pi-coding-agent.txt`、`OFL-Resource-Han-Rounded.txt`、`OFL-jf-open-huninn.txt`
48. `AGENTS.md:45`（全 UI 不展示心情/好感数值）、`AGENTS.md:35-37`（瞬时状态不可持久化）
49. `docs/research-tavern-game.md` §2（7 机制拆解）/ §6.1（模块划分）/ §7.2（批 0–5 任务）/ §11.2（Non-goals 第 10 条：不新增运行时第三方依赖）

---

## 附录 B：诚实声明（未能核实 / 不确定）

1. **我没有运行任何候选的代码，没有克隆任何仓库，没有安装任何依赖。** 所有"依赖清单"与"许可证"结论均来自我对**仓库页面 / 原始文件 / PyPI 元数据**的实际读取，不是实测。
2. **以下许可证我**未能核实**，报告中一律标注为"查不到/未核实"，请勿当作结论使用**：
   - `malfoyslastname/character-card-spec-v2`：**无 LICENSE 文件**（已核实文件树），README 亦未提许可 → **按"保留所有权利"处理**；
   - `cproctor/inkpy`：无 LICENSE 文件；
   - `SillyTavern/SillyTavern-extras`：**我未打开其 LICENSE**。因同属 SillyTavern org，我**推测**为 AGPL-3.0，但**这是推测**；
   - `DesvoSoft/DungeonCore` / `Raven95676/astrbot_plugin_lorebook_lite` / `ATAIN000/story` / `Krishnaag23/narrative-core` / `albinks/narrative` / `P1wan/TexAdvent 的 requirements.txt` / `LevelKit-Text`：许可证或依赖**未核实**；
   - `iftechfoundation/twine-specs`：许可证**未核实**。
3. **以下数据点我未能核实**：多数仓库的 **star 数**（GitHub 页面抓取常不返回星标数）。例外：`extwee` 40 stars、`Bardic` 25 stars（来自第三方聚合页/PyPI 页，**非 GitHub 原生**）、`TheHackersWorkshop/forgotten_ship` 0 stars、`clembu/inkpy` 0 stars、`cproctor/inkpy` 0 stars。**其余候选的 star 数我写不出，也不编造。**
4. **我没有逐字读取 `pytwee` 的 LICENSE 原文**，只确认了 `license_expression="MIT"` 与 `license_files=["LICENSE"]` 以及 GitHub 仓存在 `LICENSE` 文件。**实施前必须打开 `https://github.com/jixingcn/pytwee/blob/main/LICENSE` 取准确版权行（year + author）**，这是 `docs/THIRD_PARTY.md` 表一的必填列。
5. **`docs/THIRD_PARTY.md` 自身存在一处口径不一致**（如实指出，不回避）：第 4 行写"许可白名单……**禁 GPL / AGPL / LGPL / SSPL**"，但第 113 行把 **PySide6（LGPL-3.0）** 列入"运行时依赖"表。可解释为"LGPL 通过**动态链接**使用属合规"，但**文档没有写明这一豁免条件**。**这不影响本报告的结论**（AGPL 无论怎么链接都不可用；且 ST 是 AGPL 而非 LGPL），但**建议后续修文档口径**。
6. **我用 WebSearch 检索过但"什么都没找到"的方向**（如实列出，避免读者以为我没找）：搜索"是否存在纯 Python 的独立 lorebook / world info 实现库"——**没有找到任何以库形式发布、且零依赖的 Python lorebook 实现**。找到的都是：① 某 bot / 某 ComfyUI 节点里的 60 行内联实现；② 依赖向量库的 RAG 项目；③ 生成 lorebook **文件**的工具（如 `grahamwaters/lorebook_generator_for_novelai`，它生成 NovelAI 的 `.lorebook` 数据文件，**不含检索运行时**）。**故判断：世界书这一块没有可引的 Python 库，自己写是最优解。**
7. **本次检索的置信度分层**（供 team-lead 判断）：
   - **高置信（我读了原始文件/权威页）**：SillyTavern = Node + AGPL-3.0；pytwee = MIT + 零依赖；CCv3 = MIT；CCv2 = 无 LICENSE；inkpy 四兄弟的四种死法；Bardic 的 2 个核心依赖。
   - **中置信（我读了仓页/README，但未读 LICENSE 原文）**：各"仅机制参照"项目的架构描述。
   - **低置信（第三方聚合页 / 商业博客 / 二手整理）**：star 数、"2026 生态现状"类叙述、字段差异对比表。**低置信项未用于任何结论。**
8. **我没有评估"用户是否真的需要酒馆"这个产品问题。** 本报告只回答技术选型。§7.1 的 Q1/Q3（`propose` 档做不做、首发范围）**仍然悬而未决**，与本报告的结论独立。
9. **"AGPL-3.0 是否真的 100% 不可用"这个法律判断，我是按项目自己的 R-H 口径执行的**，不是我的法律意见。若主理人愿意为 ST 单开一个"AGPL 例外"（例如"不作为产品的一部分、仅作为用户自装的外部服务"），**结论会变**——但那样 R-F 与"零门槛打包分发"的承诺也会变。**这是一个需要主理人拍板的产品决策，不是技术决策。**
