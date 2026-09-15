# 酒馆（Tavern）· 联网调研与内置方案设计（v3 · 参照 SillyTavern · 中大型独立功能域）

> **本文是调研 + 方案设计稿**，不修改任何产品代码。作者：产品调研员（research-tavern）。
> v3 依据用户三次澄清重写：**①「酒馆」= SillyTavern（参照物，不是要复刻的游戏）②规模 = 中大型，不是小型玩法 ③高自由度是核心质量目标**。

---

## 0. 一句话结论

> **参照 SillyTavern，把「酒馆」做成一整个独立功能域：她（女仆）当老板娘兼 GM，你既能点选项、也能自由打字；
> 真相（世界状态）存在本地的状态机里、只由一组受控「变换」改写；LLM 负责写作与「提议变换」，**提议必须过本地校验器才落地，不通过就降级为纯叙述并留痕**。
> 世界书（关键词触发 + 预算裁剪）、角色卡、上下文摘要、重掷/编辑、快捷动作五件套按码铃的零依赖与四主题纪律重新落地。**

三句话讲清 v3 相对 v2 的变化：

1. **参照物换了**：v2 把 SillyTavern 当"已排除方向"；v3 把它当**唯一指定参照物**，逐机制写"抄什么、改成什么形态"（§2）。
2. **规模换了**：v2 是"独立浮窗 + 新增 3 文件"的小玩法；v3 是**独立功能域**——独立数据层 / 独立页与 Tab / 独立存档 / 独立测试，配 P0/P1/P2 清单与分批任务（§6、§7）。
3. **自由度换了**：v2 主张"自由输入一律不许改状态"；v3 推翻为**三级意图路由**——可直接施加的受控变换，命中即改；无法识别则降级纯叙述并留痕（§4）。

**查不到就写查不到**：本文所有方法、机制、来源均可回溯到附录 A；不确定处集中在附录 B。

---

## 1. 口径与参照物（先读我）

### 1.1 v3 的三处口径更正（覆盖 v2）

| # | v2 的写法 | v3 的写法（以此为准） |
|---|---|---|
| 1 | §8「已排除方向」里含 SillyTavern | **移除**。SillyTavern 升为 §1.2 / §2 的**主线参照物** |
| 2 | "最小可行 / 独立浮窗小玩法 / 新增 3 文件" | **推翻**。改为**中大型独立功能域**：独立数据层 + 独立 UI 页/Tab + 独立存档 + 独立测试 + P0/P1/P2 分批（§6、§7） |
| 3 | "自由输入一律不允许改状态" | **推翻**。改为**受控可扩展**：受控变换白名单 + 未识别降级为纯叙述并留痕（§4） |

### 1.2 参照物：SillyTavern 是什么（以及"参考实现"是什么意思）

SillyTavern 是一个**本地运行的 LLM 角色扮演前端**：它自己不含模型，负责的是**把"人设 / 世界 / 记忆 / 历史 / 指令"组装成一次请求**，并把回复渲染成可反复重掷与编辑的对话。它的价值不在"聊天界面"，而在**上下文工程**：

- 一个"角色卡" = 字段化的人设（他是谁、怎么行动、当下场景、开场白、语气样本）；
- 一个"世界书" = **关键词触发的动态词典**，只在相关时才把设定塞进 prompt；
- 一个"Prompt Manager" = 把上述所有片段**按位置与顺序**拼成最终请求，且"越靠后影响越大"；
- 一套"重掷 / 编辑 / 继续 / 滑动"= 对**同一拍**反复重写而不破坏上下文；
- 一套"快速回复 / STscript" = 把常用动作与变量操作做成按钮。

**这正是用户说"参考酒馆的实现"时指向的东西**：不是要复刻它的界面，而是要**借鉴它把"高自由度角色扮演"变为可控工程的这一整套方法**。

### 1.3 中文语境「酒馆」的三层含义（一句带过，证据见附录 A）

| 层 | 指什么 | 处理 |
|---|---|---|
| A | 炉石"酒馆战棋"（自走棋） | 排除（§10） |
| B | **SillyTavern 的中文简称**（AI 圈默认） | **本方案参照物** |
| C | 「酒馆」题材的桌游 / 经营模拟 | 排除（§10） |

---

## 2. ★ 参照物拆解：SillyTavern 的 7 个机制（抄什么 / 改成什么形态）

> 每小节格式：**机制原样 → 抄什么 → 改成什么形态（码铃约束下）**。
> 码铃的三条硬约束贯穿全章：**零新增运行时第三方依赖（R-F）／不引 WebView 与游戏引擎／必须与四套主题融合**。

### 2.1 角色卡（`chara_card_v2` 规范）

**机制原样。** ST 的角色卡是一个 JSON（`.png` 卡则把同一份 JSON 嵌在图片的 `chara` 文本块里），字段为：

```
spec="chara_card_v2" / spec_version="2.0" / data{
  name, description, personality, scenario, first_mes, mes_example,      # v1 六字段（必填）
  creator_notes, system_prompt, post_history_instructions,
  alternate_greetings[], character_book?, tags[], creator,
  character_version, extensions{}                                        # v2 新增
}
```

语义分层很讲究：`description` 是"他是谁（外观/背景/关系）"、`personality` 是"怎么行动"、`scenario` 是"当下场景"、`first_mes` 是开场白、`mes_example` 是**教模型说话语气的对话样本**。两条规范细节值得抄：`alternate_greetings` 必须是**可"滑动"切换**的数组；`creator_notes` / `tags` / `creator` **不得进入 prompt**（仅供人类与检索）。`character_book` 让角色自带一本世界书，**默认必须启用**，且**角色书优先于全局世界书**。

**抄什么。**
- 字段的**语义分层**（谁 / 怎么行动 / 当下 / 开场 / 语气）——这是把"人设"变成可工程化输入的关键。
- `mes_example` 的用法：**用样本教语气比用形容词描述语气有效**。
- `alternate_greetings` 的"开场白可滑动"——零成本提升重玩感。
- "非 prompt 字段永不入上下文"这条边界。

**改成什么形态。**
- **不引入 PNG 内嵌 JSON**。码铃已有自己的角色卡规范 `docs/character-card-spec.md`（`.malingcard.json`，schema v2，实现于 `gui/role_card.py`），导出走 `EXPORT_FIELDS` 白名单（`role_card.py:36-42`），**记忆 / 亲密度 / 对话历史 / entities / response_rules 永不入卡**（R-I 硬线）。酒馆**沿用这套卡，不另造格式**。
- 码铃卡现有字段 = `name / description / system_prompt / personality / opening_lines / example_dialogues / current_expression / cover_image / given_name`。与 ST 对照：`opening_lines[]`≈`alternate_greetings[]`（已经可滑动）、`example_dialogues`≈`mes_example`、`personality`≈`personality`、`description`≈`description`。**缺口只有三块**：`scenario`（当下场景）、`system_prompt` 的"卡级覆盖"语义、以及"卡自带世界书"。
- 建议（P1，且需拍板）：为酒馆卡**只增两个可选字段** —— `tavern_scenario`、`tavern_book_ref`（引用一本世界书 id，**不内嵌内容**，避免卡体积膨胀与"数据乱"）。二者必须同步进 `EXPORT_FIELDS` 白名单与 `parse_card` 校验，按既有前向兼容铁则"未知字段忽略不崩"处理旧卡。
- **复用而非重建**：`gui/role_card.py` 的 `CardError` / 体积上限 1MB / 重名去重 `dedupe_import_name` 全部照用。

### 2.2 世界书 / World Info（关键词触发 + 预算）

**机制原样。** 条目结构（`WIScanEntry`）：`uid / key[] / keysecondary[] / selectiveLogic / content / position / depth / weight / constant / enabled`。触发判定用 `key` 主键扫最近若干条消息，`keysecondary` + `selectiveLogic` 做组合精化：`AND_ANY(0) / NOT_ALL(1) / NOT_ANY(2) / AND_ALL(3)`；`key` 支持正则（JavaScript 风格，`/.../flags`），纯文本 key 用逗号分隔。**预算**：`world_info_budget`（占上下文百分比）+ `world_info_budget_cap`（绝对 token 上限）；超预算时按 **`weight` 降序 → `order` 降序 → `uid` 升序** 排序后截断。**插入位置**：`before_char` / `after_char` / 指定深度 / 指定 role（system/user/assistant）。**来源分层**：聊天级 → 人设级 → 角色级 / 全局级，合并策略 `sorted evenly`（默认）/ `character first` / `global first`。还有四个容易被忽略但极有用的旋钮：`probability`（触发后按百分比决定是否真插入）、`recursion`（条目内容可再触发其他条目）、`sticky / cooldown / delay`（触发后保持 N 条 / 冷却 N 条 / 延迟 N 条）、`ignore budget`（强制插入）。还有 `scan_depth`（扫最近几条）。

**抄什么。**
- **关键词触发代替"全程携带"**——这是世界书最核心的价值：把"设定"从常驻 prompt 变成按需检索。
- **预算 + 排序淘汰**（weight → order → uid）——保证"设定永远不会挤爆对话"。
- **`constant` 只留给 3–5 条基础世界规则**（社区共识，见 §3.2-6）。
- **`before_char` / `after_char` / depth / role 四种落点** + "**稳定事实放前，情境状态放后**"的经验法则。
- **递归激活**——条目之间可以互相引用，形成知识网。
- `sticky / cooldown / probability` 三个"节奏旋钮"。

**改成什么形态（这是本章最重要的一节）。**
- **码铃没有 embedding，这是决定性约束。** 全树检索确认：`gui/` 下**零** `embedding / 向量 / 余弦` 实现；既有本地 RAG 是 `helpers.KnowledgeBase`——注释写明"**简化版：关键词 + TF-IDF**"（`helpers.py:419-426`），索引落 `kb_index.json`，检索返回前 3 条（`gui/widgets/kb_dialog.py:1-9`）。
- **这反而是好消息**：SillyTavern 的世界书本就是**关键词触发**，与码铃既有能力**同源**。酒馆世界书直接走"关键词命中 + 排序 + 预算"，**不需要向量库、不违反 R-F**。
- **"token 预算"必须降级为"字符预算"，并且如实标注为近似。** 码铃没有 tokenizer（零第三方依赖），项目既有的上下文裁剪用的是**条数**而非 token（`GROUP_HISTORY_LIMIT = 60`，`chat_service.py:294`；`session._trim_history`，`session.py:232-239`）。因此：
  - 条目预算用 `budget_chars`（建议单条 ≤ 200 字），总量用 `worldbook_budget_chars`（建议 1200–2000 字）；
  - UI 与文档**只说"约 X 字"，不承诺 token 数**；若未来接入模型自带 usage，可另做校准（附录 B-3）。
- **落点只保留三种**：`system_head`（世界规则）/ `system_tail`（本回合情境）/ `history_depth`（对话历史内指定深度）。**不做 role=assistant 的注入**——码铃的注入基建是"追加 system"，伪造成 assistant 会污染既有语义（§5.1）。
- **正则 key 允许，但必须逐条 `try/compile` 并在编译失败时静默丢弃**——照抄码铃 `gui/intent.py:135-143` 的既有写法，避免"一条脏规则炸掉整本世界书"。
- **`recursive` 默认关闭**，且实现时必须带**深度上限（建议 2）与 visited 集合**——SillyTavern 官方文档提示递归会"链条滚雪球（snowball）"，chub.ai 文档也把 `recursive scanning` 定为需显式开启的选项；中文第三方文档（nativetavern"世界信息 / 知识库"）同样提示"递归扫描可能触发更多相关条目"。
- **来源分层简化为两级**：`builtin`（随内容包发布的基础世界书）+ `play`（本局/本卡绑定的书）。**不做三层**——三层在单人桌面场景收益低、调试成本高。
- **`ignore budget` 不抄**：它会让"预算"这个安全阀失效，与"数据不乱"的意图相反。

### 2.3 Prompt 组装顺序（Prompt Manager）

**机制原样。** 一个可拖拽的 prompt 列表，**越靠上越早发送、越靠下越晚发送（影响越大）**。**默认锁定项（pinned）依次是**：Main Prompt / World Info (before/after) / Persona Description / Character Description / Character Personality / Scenario / Enhance Definitions / Auxiliary Prompt / Chat Examples / Chat History / Post-History Instructions。每条可设 `Role`（system / AI assistant / user）、`Triggers`（**Normal / Continue / Impersonate / Swipe / Regenerate / Quiet** 六种生成类型）、`Position`（Relative 按列表顺序 / **In-Chat + Depth** 插入到历史里）、`Order`（同 role 同 depth 内排序；自上而下为 User → AI Assistant → System）。

**抄什么。**
- **"位置即权重"**：同一条内容放在开头还是插到历史深处，效果完全不同——这是 prompt 工程里最实用的一条。
- **"稳定事实在前、情境状态在后"** 的排序法则。
- **`Triggers` 的思想**：同一次生成有不同"生成类型"（正常 / 继续 / 重掷 / 重新生成），不同类型的 prompt 可以不同。**这对"重掷"极其关键**（见 §2.6）。
- **可查看最终 prompt**（ST 提供 Prompt Itemization / Prompt Inspector）。**可观测性 = 可调试性**。

**改成什么形态。**
- 酒馆**不挂进 `ChatService`**（避免污染会话、注入序位与计费口径），而是自带一个**纯函数** `build_story_prompt(state, book, play) -> messages`。
- 内部分层固定为五段（**对齐 ST 的 pinned 语义，但只留五段**）：
  `[system] 说书人规则（长度/视角/禁项） → [system] 世界规则（constant 条目） → [system] 角色卡（她是谁/怎么行动/语气样本） → [system] 本回合情境（vars 摘要 + 命中条目 + 本回合发生了什么） → [history] 近 N 条叙述 + 【前情提要】`。
- `Triggers` 只落两种：`normal` 与 `reroll`。**`reroll` 时允许"本回合必不携带上一版文本"**——这是防止重掷总是生成同一句的关键。
- **可观测性必须做**：提供一个"看这一回合实际发了什么"的开发者入口（沿用 `tool_trace` 既有形态即可），否则线上出问题无法归因。
- **不引入"prompt 拖拽编辑器"**——那是 ST 面向高级用户的配置面，对码铃用户是纯负担。

### 2.4 作者注释（Author's Note）

**机制原样。** 一段可"**任意位置、任意频率**"插入的文本。位置二选一：`After Scenario`（角色定义的 scenario 之后、示例消息之前）或 `In-chat + Depth`（`depth 0` = 聊天历史最末尾；`depth 4` = 插在最近 3 条之前）。`Frequency`：`0` = 永不插入，`1` = 每次用户输入都插，`4` = 每 4 次用户输入插一次；**ST 明确提示：`frequency 0` 时指向 A/N 位置的条目会被忽略**。典型用途：约束输出格式（"你的下一条回复必须 300 token"）、强化指令（"记住开头给你的设定"）、兼作**临时世界信息**（"她此刻在图书馆"）。

**抄什么。**
- **"同一段内容可以用频率控制存在感"**——这是低成本调控节奏的手段。
- "**越靠底部影响越大**"的位置直觉。
- 用途清单里**"临时世界信息"**这一条：它等价于"只在需要时改变 prompt 的世界状态"。

**改成什么形态。**
- 酒馆里对应物叫 **「说书人提示」（narrator_note）**，但**形态收窄**：
  - 只有**两个位置**：`history_depth=1`（默认，插在最近一条之前）与 `system_tail`（情境段末尾）；
  - 频率**不做 0/N 随机**，改成**三种语义档**：`每回合` / `每章开头` / `本回合一次（一次性）`；
  - **不暴露给用户自由编辑**（P0），只由内容包与剧情节点声明，避免"用户写坏自己的 prompt"。
- 落点**必须复用码铃既有的语气注入范式** `inject_maid_tone`（`chat_service.py:575`）的写法，不自造拼接方式。
- **R-A 检查**：narrator_note 的文案不得出现数值性养成语义（见 §5.6）。

### 2.5 上下文截断 / 摘要 / 记忆

**机制原样。** 四种主流策略（Quickchat 的对照表）：`滑动窗口`（简单，但角色会忘）／`摘要`（保住长期脉络，但丢细节）／`RAG 检索`（召回最好，但增加延迟与复杂度）／`混合`（最强也最复杂）。ST 系的做法是"**关键词检索（世界书）+ 逐字保留最近若干条 + 生成的摘要**（`{summary}` 宏）"。**AI Dungeon** 的自救法是 `Auto-Summarization`（每 12 个动作摘要最早的 6 个）+ `Memory Bank`，免费档上下文约 4000 token，超出从最旧裁掉。更根本的一条来自实践总结：**"把上下文窗口当缓存，而不是硬盘。"** 以及 `Lost in the Middle`（Liu et al., 2023）的实证：长输入的中段会被稳定忽略，**"换个更大的窗口"不是解法**。工程侧给的缓解办法里有两条最实用：**结构化记忆（LLM 不自由写，用"专用抽取步骤 + 结构化 schema"落成确定性记忆）**、**对摘要/压缩保留"不可丢失字段"**（偏好、已确认事实、硬约束）。学术侧也在做（MOOM 论文：叙事摘要分支 + 人物构建分支 + 仿人类记忆的**竞争-抑制遗忘机制**）。

**抄什么。**
- **四策略对照表本身**（要什么、付什么代价），以及"**混合**"这个结论。
- **"把上下文当缓存"**——这句话直接决定了酒馆的记忆设计。
- **结构化记忆 + 专用抽取步骤**：**"LLM 不自由写记忆"** 这条与码铃的价值观完全一致。
- **摘要必须是"可见可编辑"的状态，而不是黑盒**（Chattica 的做法：summaries are visible and editable）。
- **`AI Dungeon` 的失败清单**（改名 / 场景跳变 / 循环重复 / 遗忘角色卡）应当**被当作必然，而不是意外**来设计防御。

**改成什么形态。**
- 码铃**已有**该范式：`session._trim_history()`（截断保最近，`session.py:232-239`）、`session.auto_summary()`（产出 `【前情提要】` 文本并作为一条 user 消息注入，`session.py:315-338`）、`context_trimmed` 标志（`session.py:95-98`）、`memory.py` 的 `_VISION_MEMORY_MAX = 50` 滚动淘汰。酒馆**照这套范式做，不另立规则**。
- 具体：
  - `transcript` 逐字保留**最近 N 拍**（建议 12–16 拍），更早的压缩进 `summary`；
  - `summary` 是**存档里的结构化字段**（`summary.text` + `summary.up_to_turn`），**不是 prompt 里的临时拼接**；一旦写入即数据，必须原子写 + 版本化；
  - **摘要由本地规则触发**（每 8 拍或进入新章）、**可选由 LLM 生成文本**，但**生成结果在落盘前必须过基本校验**（非空、长度上限、不含"玩家的选择是什么"这类越权臆断）——**这条是把"AI Dungeon 式遗忘"从制度上挡在门外**；
  - **世界书（§2.2）承担"长期事实召回"**，相当于码铃版的"Memory Bank"，且因为是关键词触发，**不存在向量库与额外延迟**。
- **不引入向量检索**：零依赖约束下不可能，且关键词检索 + 摘要已能覆盖单机叙事场景（附录 B-4 记为"未验证的规模上限"）。

### 2.6 分支与编辑重发（swipe / regenerate / edit / continue）

**机制原样。** ST 对 AI 的回复提供五类操作：`Swipe`（同一位置生成多个候选，横向切换）、`Regenerate`（丢弃重生成）、`Continue`（续写）、`Impersonate`（替用户扮演）、以及**直接编辑已生成的消息**。配套的还有 `/addswipe`、`/delswipe`、`/hide`、`/unhide`、`/sys`、`/comment` 等命令。关键设计点是：**这些操作被建模为不同的"生成类型"（`Triggers`），因此可以走不同的 prompt**（`Regenerate` 与 `Normal` 可以不是同一套指令）。

**抄什么。**
- **"同一拍可重掷"**：不满意就再摇一次，**不动上下文结构**。
- **"可编辑已生成文本"**：用户对"措辞"有最终解释权。
- **"重掷与正常生成走不同 prompt"** 这个思想。

**改成什么形态（这里有一个对码铃特别漂亮的性质）。**
- 在 v2/v3 的混合路线下，**"状态"与"文本"是分离的**：本回合的**变换已经施加完毕、状态已确定**，LLM 产出的**只是叙述文本**。因此"重掷"在码铃里是**天然安全的**：
  - `reroll` **只重跑 §4 的叙述生成步骤，绝不重跑变换执行**；
  - 重掷产生的候选**只写进 `transcript` 的该拍，不改 `vars` / `node_id` / `chapter_id`**；
  - 因此**不可能出现"重掷一次世界就变了一次"这种最危险的脏数据**。
- **编辑**同理：允许编辑**叙述文本**，**禁止编辑状态字段**（UI 上根本不呈现可编辑的状态）。
- **`Impersonate` 不抄**——它会替用户说话，与"陪伴"定位不符，也容易写出用户没说过的内容。
- **`/hide`、`/comment` 这类"改 prompt 可见性"的命令不抄**（它们需要暴露给用户，与"不暴露 prompt 编辑器"的决策一致）。
- **`Continue` 改形态**：不做"续写同一条"，而是**"再写一段"**——即新增一拍、状态不变（等价 `wait` 变换），语义更清晰且可留痕。

### 2.7 快速回复（Quick Replies + STscript）

**机制原样。** `Quick Replies` 是一个内置扩展：在输入栏上方放一排按钮（**最多 100 槽**），每个按钮绑定一段 `STscript`（斜杠命令批处理，用 `|` 串管道）。STscript 有**局部变量（存聊天元数据）与全局变量**，命令如 `/addvar` `/incvar` `/setvar` `/flushvar` `/if` `/echo` `/input` `/popup`；官方建议**按钮标签用 emoji 保持简洁**，并提示"开着 STscript 时要关掉输入自动注入，改用 `{{input}}` 宏取输入框内容"。预设可切换（`/qrset`）。官方明确其用途之一是"**创建小游戏或速通挑战**"。

**抄什么。**
- **"把常用动作变成一键"**——对酒馆就是"环顾四周 / 沉默 / 问下去 / 再来一杯"这类**零打字成本的推进动作**。
- **"动作是一等公民"**：STscript 里动作可以读写变量，这说明"按钮 = 一次受控状态变更"是成立的建模（正好对应本方案的"变换"）。
- **"按钮标签要简洁"**。

**改成什么形态。**
- **形态**：一排 QSS 按钮，**用既有图标集 `gui/icons.py`（Remix Icon）而非裸 emoji**——项目现行口径是 emoji 位一律矢量字形化（v2.1 已收口），**"官方建议用 emoji"这条不适用于码铃**。
- **数量**：**4–6 个固定槽**，不做 100 槽、不做用户自定义脚本。
- **绝不引入脚本语言**：`STscript` 本质是**可执行面**，引入它等于引入沙箱、权限与安全评审成本，且与 R-F/R-D 冲突。**"按钮 → 受控变换 id" 这个映射表就够用了**（这正是 §4.3 的白名单）。
- **可扩展点**：内容包可以为某个节点**额外声明 1–2 个情境动作**（例如"弹一首曲子"），仍然走同一张白名单校验。

### 2.8 汇总：7 机制 × 抄 / 改 / 裁

| # | ST 机制 | 抄 | 改成什么形态 | 明确不抄 |
|---|---|---|---|---|
| 1 | 角色卡 `chara_card_v2` | 字段语义分层；`mes_example` 教语气；`alternate_greetings` 可滑 | 沿用码铃 `.malingcard.json` schema v2；**只增可选 `tavern_scenario` / `tavern_book_ref`**，须同步白名单 | PNG 内嵌 JSON；卡内塞世界书正文 |
| 2 | 世界书 / World Info | 关键词触发；预算 + 三级排序淘汰；`constant` 限量；递归；四种落点；三个节奏旋钮 | **字符预算（近似，如实标注）**；落点收为三种；来源两级；正则逐条 try 编译；递归默认关 + 深度上限 | `ignore budget`；三层来源；向量检索（无能力） |
| 3 | Prompt 组装顺序 | "位置即权重"；稳定在前情境在后；`Triggers`；可查看最终 prompt | 五段固定分层；纯函数 `build_story_prompt`；`Triggers` 只留 `normal`/`reroll`；开发者可读 trace | 拖拽式 prompt 编辑器 |
| 4 | 作者注释 | "频率控制存在感"；"越靠底部影响越大"；兼作临时世界信息 | 收窄为「说书人提示」：两个位置 / 三种频率档 / **P0 不开放用户编辑** | 任意位置 × 任意频率的完全体 |
| 5 | 截断/摘要/记忆 | 四策略对照；"上下文是缓存"；结构化记忆 + 专用抽取；摘要可见可编辑 | 复用 `session._trim_history` / `auto_summary` / `【前情提要】` 范式；**摘要落盘为结构化字段并过校验**；世界书承担长期召回 | 向量 RAG；让 LLM 自由写记忆 |
| 6 | swipe/regenerate/edit/continue | 同一拍可重掷；可编辑文本；重掷走不同 prompt | **状态与文本分离 ⇒ 重掷只重写文字、绝不重跑变换**（本方案最大红利）；`continue` 改语义为"再写一段" | `Impersonate`；`/hide`、`/comment` |
| 7 | Quick Replies / STscript | 常用动作一键化；动作即受控状态变更；标签简洁 | 4–6 个固定 QSS 按钮 + 矢量图标；**按钮 → 受控变换 id 映射表** | 100 槽；任何形式的脚本语言 |

---

## 3. ★ 设计方法（关键词 → 来源 → 在码铃里怎么用）

### 3.1 实际用过的关键词清单（原样列出，便于复核）

按用户要求逐条真搜，实际检索词如下（均为本次会话真实执行）：

| # | 关键词（原文） | 主要命中 |
|---|---|---|
| 1 | `storylet quality-based narrative design Fallen London StoryNexus` | IFWiki StoryNexus / videlais QBN / Troy Gilbert 的建模笔记 / Emily Short |
| 2 | `SillyTavern world info lorebook activation keys token budget prompt order` | `docs.sillytavern.app` World Info / DeepWiki `world-info.js` 源码级结构 |
| 3 | `emergent narrative vs branching narrative design interactive fiction` | 分支 vs 涌现的定义与"foldback / 汇流"结构 / consequence budget |
| 4 | `AI Dungeon criticism limitations AI hallucination memory problems` | `bex.co` 负面反馈综述 / arcanumrpgs 评测（含 Voyage 对照） |
| 5 | `lorebook authoring guide world info best practices token budget recursion` | kissable 世界书指南 / chub.ai Lorebooks / Chattica docs |
| 6 | `LLM long context roleplay memory summarization retrieval techniques` | Quickchat 四策略对照 / MOOM 论文 / `lost in the middle` 实践文 |
| 7 | `SillyTavern character card V2 spec description personality scenario first message example dialogue` | `character-card-spec-v2` 规范原文（GitHub）/ 建卡指南 |
| 8 | `interactive narrative world state modeling consistency variable tracking design` | "think in states not scenes" / 持久世界重建 / Sciencedirect 的世界状态谓词建模 |
| 9 | `"World-State Transformations" neuro-symbolic interactive storytelling paper arxiv` | **arXiv:2605.24719 原文** + Pith 同行评审意见 |
| 10 | `SillyTavern prompt template order author's note depth quick replies swipe regenerate` | Prompt Manager 文档 / Author's Note 中文文档 |
| 11 | `SillyTavern quick replies STscript slash commands guide` | STscript 语言参考（官方 + 中文） |
| 12 | `Emily Short storylets why you want them design principles` | Emily Short《Storylets: You Want Them》原文 + 中文译介 |

### 3.2 七条方法逐条落地

> 格式：**原则 → 来源 → 在码铃里怎么用**。

**① storylet（故事块）**
- **原则**：一段内容 = 「文本 + 前置条件 + 对世界状态的影响」三件套，**atomic、robust、可重组**；组织叙事时用"故事块空间里的游历"替代"分支树"。作者不能控制玩家路线，但可以给子空间赋予叙事含义。
- **来源**：Emily Short《Storylets: You Want Them》（`emshort.blog/2019/11/29/storylets-you-want-them/`）；张伯伦式定义亦可回溯到 Failbetter 2010 的博客。
- **在码铃里怎么用**：**酒馆的一夜 = 一组故事块，而不是一棵分支树**。酒馆的骨架节点就写成 storylet：`{id, title, text, llm_brief, prerequisites, effects, choices[]}`。这样"顺序"不再是硬编码，而是"哪一块的**前置条件**当前满足"。**收益**：想加内容只需加块，不必改动既有路径——这直接压低中大型规模的维护成本。

**② quality-based narrative（QBN）/ 资源叙事**
- **原则**：用**少量命名数值（qualities）**决定哪些故事块可选；分支可"锁定"甚至"隐藏"。作者的簿记成本是真实存在的（StoryNexus 要求手动设置"事件 A 可用 / A 已完成"这类属性）。
- **来源**：IFWiki `StoryNexus`；`videlais.github.io/simple-qbn/`（含 Kennedy 2017 建议改称 "resource narrative" 的说明）；Emily Short《Beyond Branching》。
- **在码铃里怎么用**：酒馆的 `vars` **就是一个受控 quality 集合**，但**严格限量**（建议 ≤ 8 个，且每个 var 必须在内容包里声明类型与值域）。**这同时是"数据不乱"和"分支不爆炸"的同一个解**：因为只有 8 个变量，状态空间天然有界。**明确不抄**其"行动点 / 刷新 / 付费解锁"（Nex）——那是运营经济，码铃的红线 R-A 明确禁止货币与筹码类数值。

**③ emergent vs branching（涌现 vs 分支）**
- **原则**：**分支 = 作者预先建好的路径**；**涌现 = 系统规则与玩家行为碰撞出的故事**。二者常被混为一谈，是项目翻车的常见起点。工程界给的收束手段是 `foldback`（分支汇流）、`hub and spoke`、共享结局；并给出"**每条叙事弧的高影响选择控制在 3–5 个**"这样的后果预算经验值。
- **来源**：Sunnyheadcase《What Do You Even Mean By Branching Narrative?》；Grokipedia 的 Interactive Storytelling Techniques 条目；game-store.cloud 的五种路线对照表（含 Hybrid 一栏）。
- **在码铃里怎么用**：**主线走作者化（storylet + 汇流），支线走涌现（自由输入 + 变换）**。具体：每章 3–5 个"高影响选择"（走 §2.2 的 `vars`），其余交给自由输入。**这就把"高自由度"落到可管理的量**：自由度体现在**每一步都能打字**，而**后果的重量集中在 3–5 个点**。

**④ world state modeling（世界状态建模）**
- **原则**：**"以状态思考，而不是以场景思考"**；世界状态 = 一组命名变量/谓词（角色、地点、物品、关系、进度）；**动作 = 前置条件 + 后置效果**；必须做"分支汇流、可复用叙事枢纽、共享结局"以防爆炸；**叙事 QA 与线性 QA 不同，要测的是不变量而不是穷举路径**。
- **来源**：Film Threat《Building Branching Interactive Cinema Without Breaking the Backend》；ScienceDirect《Managing the plot structure of character-based interactive narratives》（给出 `world state = 一组正文字面量` 与 `O=(act, PRE, POS)` 的算子定义）；themoonlight 对"持久世界重建"论文的评述。
- **在码铃里怎么用**：`TavernStore` 里的 `active_play.vars` 就是 world state；**每条变换写成一个 `(pre, post)` 对**；**测试策略改为"不变量断言"**（例如"任何时刻 `held_items` 与 `scene_items` 不相交"、"`node_id` 必存在于内容包"、"`seen_nodes ⊆ 内容包节点集`"）而不是穷举路径——这正是 §7 任务表里"纯逻辑可单测"的依据。

**⑤ LLM long-context roleplay memory（长上下文角色扮演记忆）**
- **原则**：滑动窗口 / 摘要 / RAG / 混合 四条路各有代价；**"把上下文窗口当缓存，不是硬盘"**；**`lost in the middle`** 说明"更大窗口不是解法"；**结构化记忆（LLM 不自由写 + 专用抽取步骤 + schema）** 是可靠的那条；摘要**应当可见可编辑**而不是黑盒。
- **来源**：Quickchat AI 的 AI Roleplay 指南（四策略表）；Fieldguidetoai 的 Context Management 指南；dev.to 的 `Lost in the Middle` 实践文；MOOM 论文（`lacuna.tiptreesystems.com`，含"竞争-抑制"遗忘机制）。
- **在码铃里怎么用**：`transcript`（近期逐字）+ `summary`（结构化、落盘、过校验）+ **世界书关键词召回**（= 无向量版的 RAG）。**关键判断：摘要一旦落盘就是数据**，必须原子写 + schema 版本 + 读时迁移——把"记忆"从易失的 prompt 提升为可迁移的存档（附录 B-5 记录了我对"摘要质量"的保留）。

**⑥ lorebook authoring（世界书撰写）**
- **原则**（社区共识，多条来源一致）：**一条目一主题**；**3–5 条要点**、条目要"独立成篇"；标题**带常见别名**；**always-active 只留 3–5 条基础世界规则**，否则预算被瓜分到"每条都触发不了"；**每轮预算有限，臃肿的一条会挤掉对话本身**；写完要**实跑 2–3 遍再迭代**（哪些常触发 / 从不触发 / 触发过频）。
- **来源**：kissable.app《AI Lorebook Guide》；docs.chub.ai《Lorebooks》（scan depth / token budget / recursive scanning / priority 的字段说明）；Chattica docs（"ten tight entries beat one essay"；"stable world facts early, situational state late"）。
- **在码铃里怎么用**：作为**内容包的编写规范**写进 `gui/tavern/content/README` 与校验器里 —— 条目正文 ≤ 200 字、`keys` ≥ 1 且含至少 1 个别名、`constant` 条目总数 ≤ 5。**校验器在加载时执行，违规条目禁用并打日志，而不是崩**（对齐 `_merge_defaults` 的"类型守卫"精神）。

**⑦ AI Dungeon criticism（纯 LLM 路线的失败档案）**
- **原则**：纯生成路线有**四类稳定失败**——重复/循环、幻觉与脱轨、**角色改名与设定漂移**、上下文遗忘导致的自相矛盾；并且这些**不是偶发 bug，而是机制必然**。其官方后继作品 `Voyage` 用"骰子 + 技能检定 + 生命值 + 永久死亡"换"**后果有真实重量**"，评测分数显著高于 AI Dungeon（同一站点评分 4.4 vs 2.6，2026-08-31 入榜）。
- **来源**：`bex.co` 负面反馈综述（含 Reddit 用户原话与"角色卡最终被忽略"）；`arcanumrpgs.com` AI Dungeon 评测（Voyage 对照）；`aitestguide.com` 2026 评测（"Memory is average… long sessions need reminders"）。
- **在码铃里怎么用**：**把失败清单当需求清单**——
  - 改名/漂移 → 角色卡与 `vars` 是**本地数据**，不参与生成，从根上不可能被改坏；
  - 循环/重复 → `reroll` 走不同 prompt（§2.3）+ 世界书提供新信息不同源；
  - 遗忘 → 摘要 + 世界书召回（§2.5）；
  - "后果没有重量" → **抄它的诊断，不抄它的药**：码铃**不引入 HP / 死亡 / 骰子数值**（撞 R-A），但采用**"后果留痕"**——你的每个动作都在 `transcript.applied` 里留下可查的一条。

### 3.3 一条被同行评审过的路线：world-state transformations（含反方意见）

这是本次调研中**与"自由输入何时能改状态"最直接相关**的学术工作，值得单列。

- **做法**：把玩家的整段自然语言输入交给 LLM，让 LLM **只预测"该施加哪些变换"**（从一张预定义变换清单里选），再由符号层**执行 + 一致性检查**，据此更新世界状态。作者把它定义为"经典 IF 动作的推广"——不再把某个具体输入绑定到某个具体结局，而是关注"**世界状态的一般性变更**"，从而让**更广的表达都能触发**。实验中实现了三个最小变换：`移动物品`、`打通地点`、`角色移动`。
- **来源**：Góngora, Chiruzzo, Méndez, Gervás《World-State Transformations for Neuro-symbolic Interactive Storytelling》，**arXiv:2605.24719**（2026-05-23，cs.CL / cs.AI）；代码 `github.com/sgongora27/transformations`。
- **结论与代价（作者自述 + 第三方评审）**：作者观察认为"变换**在保持世界状态一致性的同时**，仍能让玩家通过自由写作进行创造性表达"。但 **Pith 的评审明确指出软肋**：只有 **8 名参与者、2 个场景、纯定性观察**，**没有**一致性错误率、**没有**变换命中准确率、**没有**评分者间信度、**没有**与"纯 LLM 基线"的对照——因此"神经-符号交接的可靠性**尚未被证明**"。评审方给出的可能证伪条件是："更大规模的研究中，参与者报告大量不一致，或感到自己的创造性输入被变换规则挡住。"
- **在码铃里怎么用（含诚实的保留）**：
  - **直接采纳其架构**：LLM 只**提议**变换 → 符号层**执行 + 校验**。这正是 §4.2 的"`propose` 档"。
  - **必须注意它没证明的那一点**：变换命中率可能不高。所以码铃的设计**不能把"提议成功"当主路径**——`verbatim`（白名单直接命中）才是主路径，`propose` 是增强，`narrate`（纯叙述）是兜底。**三级路由的排序本身就是对"未证明可靠性"的风险对冲。**
  - 论文自身的两个已知失败类型也值得抄进日志设计：**共指消解失败**（"Hojita" = "Turtle"）与**隐含移动**（玩家说要拿东西但没说走过去）。→ 码铃的 `resolution` 记录里应保留"未识别原因"，便于日后调词表。

---

## 4. ★ 高自由度怎么落地（核心质量目标）

### 4.1 「自由度」的技术定义：四件套协同

用户要的"很高的自由度"，在工程上**不是**"随便写什么都能走"，而是**四件事同时成立**：

```
   ┌────────────────────────────────────────────────────────────┐
   │ ① 状态机  state machine                                     │
   │    世界是一组命名变量（vars）+ 当前位置（node_id）。           │
   │    ★ 唯一真相源：任何"世界真的变了"都必须落在这里。            │
   └───────────────┬────────────────────────────────────────────┘
                   │ 读（拼 prompt）/ 写（只由变换执行器写）
   ┌───────────────▼────────────────────────────────────────────┐
   │ ② 可自由输入的对话层  free-input layer                        │
   │    玩家除选项外可打任意文字。输入先经"意图路由"（§4.2），      │
   │    分成 直接施加 / 提议 / 纯叙述 三档。                        │
   └───────────────┬────────────────────────────────────────────┘
                   │ 需要"世界怎么变了"的素材
   ┌───────────────▼────────────────────────────────────────────┐
   │ ③ 记忆 / 世界书检索  memory & worldbook                       │
   │    关键词触发 + 预算裁剪（§2.2）：把"此刻相关的设定"喂进这一拍。│
   │    摘要承载长期脉络；transcript 承载近期逐字。                 │
   └───────────────┬────────────────────────────────────────────┘
                   │ 需要"不许违反什么"
   ┌───────────────▼────────────────────────────────────────────┐
   │ ④ 一致性约束  consistency constraints                        │
   │    变换白名单 + 前置条件 + 不变量校验 + 不可逆禁区 + 留痕。     │
   └────────────────────────────────────────────────────────────┘
```

**四者是乘法关系，缺一个自由度就塌**：

| 缺哪一件 | 会退化成什么 |
|---|---|
| 缺 ① 状态机 | 就是 AI Dungeon：世界状态在会遗忘的黑盒里，随时自相矛盾 |
| 缺 ② 自由输入 | 就是一个普通 AVG：只能点选项，**用户明确拒绝** |
| 缺 ③ 记忆/世界书 | 自由输入能改状态，但改完"没人记得"——下一拍就失忆 |
| 缺 ④ 一致性约束 | 自由度变成"世界可以被随手改坏"，**这恰恰是"数据乱"** |

**所以"高自由度"与"数据不乱"不是对立面，而是同一条链上的四个环节。**

### 4.2 自由输入何时允许改状态：三级意图路由

这是对 v2"一律不允许"的**正式推翻与替换**。

```
玩家自由输入（自然语言）
        │
        ▼
  ┌───────────────────────────────┐
  │ 本地意图解析（零 token 优先）    │  ← 词表 + 句式正则，复用 gui/intent.py 既有写法
  │ 命中受控意图 id？               │     （`intent.py:124-143`：逐条 try compile，脏数据静默）
  └──────┬───────────────┬────────┘
         │ 命中           │ 未命中
         ▼                ▼
  ┌────────────┐   ┌──────────────────────────────┐
  │ ① verbatim │   │ ② propose：请 LLM 提议一个候选  │
  │ 直接施加    │   │    变换（只能从白名单枚举里选）  │
  │            │   └──────┬───────────────────────┘
  └──────┬─────┘          │
         │                ▼
         │        ┌──────────────────────────────┐
         │        │ 本地校验器                     │
         │        │ pre 满足？不变量保持？不撞禁区？  │
         │        └──┬────────────────────┬──────┘
         │           │ 通过                │ 不通过 / LLM 不可用 / 超时
         │           ▼                     ▼
         │    ┌──────────────┐   ┌────────────────────────┐
         │    │ 施加变换       │   │ ③ narrate：纯叙述        │
         │    │ 记 applied[ok] │   │ 状态不变                 │
         │    └──────┬───────┘   │ 记 applied[skipped+reason]│
         │           │           └───────────┬────────────┘
         └───────────┴───────────────────────┘
                     │
                     ▼
        本回合"发生了什么"已确定（这是**数据**）
                     │
                     ▼
        LLM 只负责把"发生了什么"写成叙述（这是**文采**）
                     │
                     ▼
                  可 reroll（只重跑这一步，§2.6）
```

**三档的定义与边界：**

| 档 | 触发条件 | 谁有权改状态 | 失败时的行为 | 是否留痕 |
|---|---|---|---|---|
| **① verbatim** | 输入命中受控意图词表（主路径，零 token） | 本地规则函数 | 前置条件不满足 → 降级到 ③ | 是（`mode:"verbatim"`） |
| **② propose** | 未命中词表，但自由输入内容"形状可识别" | LLM 只**提议**，**执行权在校验器** | 校验不过 / LLM 不可用 / 超时 → 降级到 ③ | 是（`mode:"propose"`, `ok`, `reason`） |
| **③ narrate** | 完全无法识别，或 ①② 失败 | **无人** | —（本身就是终态） | 是（`mode:"narrate"`） |

**关键设计点（逐条回应 team-lead 的要求）：**

1. **不是"一刀切拒绝"。** v2 的做法是"自由输入永远不改世界"——**那就不是高自由度**。v3 把绝大多数**常见语义**做成 `verbatim` 白名单，**命中即改**。
2. **也不是"随便就改"。** `propose` 档**把写权留在本地**：LLM 只能从**枚举清单**里选，且**执行前必须过校验**。这与 arXiv:2605.24719 的架构一致（LLM 预测变换 → 符号层执行 + 校验）。
3. **降级不是静默吞掉。** 任何一次"没能施加"都**写进 `transcript[turn].applied`**，含 `reason`。用户不会被蒙在鼓里（可在"本夜记录"里看到），也不会因为一次没识别就报错弹窗。
4. **`propose` 档默认可以关**（P1 提供设置项）：关掉后只有 ① 与 ③——**这就退化成一个"高自由度但完全确定"的模式**，给"数据洁癖"用户一个选择。**这是把"自由 vs 可控"做成用户可选的旋钮，而不是二选一。**
5. **超时必须降级，不能卡住。** `propose` 走一次小请求（建议 `max_tokens ≤ 80`、严格 JSON），**超时阈值与失败路径必须与"LLM 关闭"完全同一条代码路径**——避免出现"只有网络慢时才炸"的偶发脏数据。

### 4.3 变换白名单（P0 最小集）与硬禁区

**P0 白名单（7 条，全部可离线执行、全部可单测）：**

| 变换 id | 语义 | 前置（pre） | 后置（post） | 触碰的状态 |
|---|---|---|---|---|
| `move_to` | 移动到当前可达地点 | `target ∈ reachable(scene)` | `scene_id = target` | `scene_id` |
| `take` | 拿走场景中的物品 | `item ∈ scene_items` | `held_items += item` | `held_items` / `scene_items` |
| `give` | 把持有的物品交给对方 | `item ∈ held_items` | `held_items -= item`、`given += item` | `held_items` / `given` |
| `open` | 打开/解锁（条件已具备） | `precondition(scene, key) 成立` | `opened += target` | `opened` |
| `ask_about` | 问某个已知话题 | `topic ∈ known_topics(scene)` | `known += topic` | `known` |
| `wait` | 让一拍过去（"再写一段"） | — | `turn += 1` | `turn` |
| `order` | 点一杯 / 要一样东西（酒馆特色） | `menu(scene) 非空` | `poured += item` | `poured` |

**硬禁区（任何档位都不得触碰，写进校验器为最高优先级）：**

1. **改写已发生的事实**（`transcript` 是 append-only，不可改历史）；
2. **跨越章节边界**（`chapter_id` 只能由章节结束条件推进，不能由输入决定）；
3. **杀死/复活关键角色、改变已确立的人物身份**；
4. **触碰 `meta` / `schema_version` / `settings`**（结构字段不参与玩法）；
5. **产出任何 R-A 禁项数值**（好感 / 心情 / 经验 / 货币 / 筹码 / 胜率 / 连胜 / 进度条 / 断签 / 倒计时）——**包括"隐藏不展示"也不做**，见 §5.6；
6. **写入未在白名单声明的 var 名**（防止 LLM 提议带来的"变量爆炸"）。

### 4.4 一致性约束：不变量 + 校验器 + 留痕

**三条不变量（每次施加变换前后各校验一次，违反即拒绝该变换并记 `reason`）：**

| 不变量 | 断言 | 防的是什么 |
|---|---|---|
| `I1 集合互斥` | `held_items ∩ scene_items = ∅` | "东西既在身上又在桌上"这类 AI Dungeon 经典矛盾 |
| `I2 引用有效` | `node_id ∈ 内容包节点集` 且 `scene_id ∈ 本书地点集` | 悬空引用导致的读档崩溃 |
| `I3 只增不改` | `transcript` 长度单调不减；`applied` 记录不可重写 | 历史被覆写（最不可逆的数据损坏） |

**留痕的数据形状**（`transcript` 每拍一条）：

```json
{
  "turn": 7,
  "role": "player",
  "input_kind": "free",
  "text": "我先把那张照片拿起来看看",
  "resolution": {
    "mode": "propose",
    "transform": "take",
    "ok": false,
    "reason": "item_not_in_scene",
    "llm_used": true
  },
  "narrated": true,
  "at": "2026-09-14T21:07:33+08:00"
}
```

**留痕的用处（三个具体收益）：**
1. **归因**：用户说"我说了要拿照片它没反应"时，能立刻看出是 `item_not_in_scene`（内容设计问题）还是 `mode:narrate`（词表覆盖不足）；
2. **调参**：统计 `mode` 分布 → 决定该往词表里加什么词（这是**可度量的迭代闭环**，正好补上 §3.3 那个"未被证明的可靠性"）；
3. **可测**：`resolution` 是纯数据，可以直接写 pytest 断言，**不需要真机、不需要联网**。

### 4.5 逐条回答 v2 的「一律不允许」

| v2 的主张 | v3 的裁决 | 理由 |
|---|---|---|
| 自由输入必须先经本地意图解析成受控意图，**不允许自然语言直接当成状态变更** | **保留**（这是 `verbatim` 档的全部内容，也是安全底线） | LLM 直接写状态 = 把数据交给黑盒（§3.2-⑦） |
| 自由输入**一律不允许改变状态** | **推翻** | 用户要的是高自由度；"永远改不了"等于拒绝了自由度本身 |
| 无法识别时"退化为普通回应" | **升级为 `propose` + `narrate` 两级**，并**全部留痕** | 不识别 ≠ 不能改；先让 LLM 提议、本地裁决，仍不行才纯叙述 |
| 未提"留痕" | **新增**：`applied` 逐拍记录 | 让"没改成功"可归因、可统计、可调优（§4.4） |

---

## 5. 现状盘点（决定方案能否落地）

### 5.1 LLM 链路（复用面）

| 落点 | 事实 | 酒馆怎么用 |
|---|---|---|
| `api.py:42-91` | `chat(messages, max_tokens, temperature, stream, tools, use_reasoning)` 非流式 | `propose` 档的小 JSON 请求用它（低 `max_tokens`） |
| `api.py:93-101` | `chat_stream_chunks(messages, ..., cancel_check, on_response)` 流式 | 叙述生成用它，**复用流式节奏做"文字节奏"动效** |
| `gui/chat_service.py:1017-1113` | `ApiWorker._run_stream()` 流式 worker 范式 | 酒馆的叙述 worker 照此写法（含末帧 usage 提取） |
| `gui/chat_service.py:1247-1371` | `ChatService.send_message()` + `request_injections`（`:1302-1351`） | **不挂进来**。理由：只在 `task_type=="chat"` 且非 Agent 模式生效；挂进来会污染会话、注入序位与计费口径 |
| `gui/chat_service.py:534-548` | `_is_demo_mode()` | 酒馆"LLM 不可用"的降级提示**沿用它既有的中性语义** |
| `gui/chat_service.py:575` | `inject_maid_tone()` 语气注入范式 | 「说书人提示」照此写法 |
| `session.py:232-239 / 315-338` | `_trim_history()` 截断 + `auto_summary()` 的 `【前情提要】` | 酒馆摘要沿此范式，但**落盘为结构化字段**（§2.5） |

**结论**：酒馆**复用 `api.py` 的调用层**、**复用流式 worker 与注入的写法**，但**自建 prompt 组装与数据层**，与聊天域**零耦合**。

### 5.2 既有可复用能力（决定了"中大型"的成本）

| 能力 | 现状 | 酒馆怎么复用 |
|---|---|---|
| **角色卡** | `gui/role_card.py` 导出白名单（`:36-42`）、`CardError`、1MB 上限、`dedupe_import_name`；规范 `docs/character-card-spec.md`（schema v2） | 酒馆的"老板娘/客人"直接是角色卡；**不另造格式** |
| **本地知识库 RAG** | `helpers.KnowledgeBase`：**关键词 + TF-IDF**（`helpers.py:419-426`），索引 `kb_index.json`，检索 top3（`kb_dialog.py:1-9`），异步 worker（`kb_worker.py`） | **世界书的检索骨架直接沿用这套范式**（关键词触发，无向量） |
| **意图分类** | `gui/intent.py` 五态纯规则分类：词表 + 句式正则、逐条 try compile、JSON 可热加载（`:117-188`） | **意图路由的写法照抄**；酒馆另立自己的词表（不改动聊天域的 `intent.py` 语义） |
| **记忆与实体** | `memory.py`：`entities` / `vision_memories`（`_VISION_MEMORY_MAX = 50` 滚动淘汰）/ 读时迁移 | 酒馆**不改 `memory.py`**；自己的 `journal` 独立存档 |
| **群聊 @ 与多人** | V17 F10 群聊（@点名、1-2 人串行接话、调度 ≤120 tokens） | 中大型阶段的"**客人也能说话**"可借鉴其串行接话的调度思想（P2） |
| **浮窗范式** | `gui/widgets/pomodoro_dialog.py`（独立浮窗 + controller 持状态 + 关闭即隐藏） | **仅在"快速开局"入口复用**；主入口改为独立页（§5.4） |

### 5.3 数据落盘范式与两处既有缺陷

**范式（必须照抄）**：`companion.py` 的 `_default_data()`（默认结构为底）→ `_merge_defaults()`（`setdefault` + `isinstance` 类型守卫的读时迁移）→ `_save()` **单写点** → `utils._atomic_write_json()`（tmp + `os.replace` 原子写）。

**必须继承的两处既有缺陷**：

| # | 缺陷 | 事实 | 酒馆的规避 |
|---|---|---|---|
| 1 | **数据目录双轨** | `gui/utils.get_user_data_dir()` = `%APPDATA%\maid_coder`（GUI 配置）；`memory.py` / `companion.py` / `session_manager.py:14` = `~/.maid_coder`（业务数据） | 酒馆存档**明确跟随业务数据走 `~/.maid_coder`**（新建 `~/.maid_coder/tavern/`），**不碰 `%APPDATA%`** |
| 2 | **`GuiConfig.save()` 逐键显式列举** | `gui/config.py:149-229`；漏改 `__init__` 或 `save()` 则**静默不持久化** | 酒馆**不改 `GuiConfig`**：所有设置放 `tavern.json.settings`，从根上绕开这个坑 |

**新发现的既有缺陷（本方案不沿用）**：`gui/session_manager.py:149-156` 的 `save_session()` 是**非原子写**（直接 `open(...).write`）。**酒馆的数据层一律走 `utils._atomic_write_json`**，不复制这个缺陷。（另一处同类：`helpers.KnowledgeBase._save()`，`helpers.py:433-435`，同样非原子。）

### 5.4 入口与容器（中大型形态的落点）

**v2 的"独立浮窗"被推翻**，改为：**新增一个独立页 + 页内多 Tab**。

| 形态 | 改动面 | 裁决 |
|---|---|---|
| 独立浮窗（v2 选择） | 最小 | ❌ 承不住中大型：无导航、无多 Tab、无"我的故事"列表 |
| **独立页 + 页内 Tab**（v3 选择） | 需改 `sidebar.NAV_ITEMS` | ✅ **主入口**。`sidebar.py:109-119` 现为 4 元组 × 10 项；**纯增 1 项**，结构与信号不变 |
| 独立顶层窗口 | 大 | ❌ 与"主窗即工作台"的信息架构冲突 |

**页内 Tab 规划（5 个，P0 只做前 3 个）**：
`今夜`（叙述流 + 输入 + 快捷动作）／`世界书`（条目增删改 + 预算读数）／`我的故事`（历史存档列表 + 继续/回看/导出）／`人物`（老板娘与客人的卡）／`记录`（`applied` 留痕与摘要，**开发者与好奇者的调试面**）。

**入口的两种可达性**：① 侧栏新页；② **保留一个"快速开局"浮窗入口**（复用 `pomodoro_dialog` 范式，从工具行直接开一局，不切页）。②的价值是"低摩擦"，**两条并存不冲突**。

### 5.5 样式 / 动效 / 图标纪律

- **四主题融合**：色一律走语义键与 `theme_color(app_ctx, key, fallback)`；**QSS 只引用 token，无裸色**。四风格 id：`ui_minimal` / `ui_cream` / `ui_night` / `ui_whale`。
- **动效只用 `gui/motion.py`**：一次性 `animate()/fade()`（≤ `MAX_DURATION_MS = 220`）+ 循环 `loop()`（周期夹取 800–1600ms）；`off` 档不创建 Qt 对象；**禁止散落 `QPropertyAnimation(...).start()`**。
- **只允许本项目原生两类母题**：① **文字节奏**（省略号循环 / 流式渲染节奏，`kb_dialog.py:33` 已有先例）；② **既有元素的呼吸**。**不做**跳动圆点、柱条、涟漪、旋转环、翻页、烛光、粒子、错峰入场等第三类几何母题。
- **图标只用 `gui/icons.py`**（Remix Icon 2.5.0，Apache-2.0），**禁自拼 `chr()`、禁裸 emoji 上屏**。
- **字号只能写 QSS**（`setPointSize` 在项目里已有"永久守卫测试"记录，别踩）。

### 5.6 红线（对本方案影响最大的一条）

**R-A 无焦虑红线**：全 UI 不得出现心情 / 好感 / 经验 / token / 货币 / 筹码 / 胜率 / 连胜 / 进度条 / 断签 / 倒计时等养成数值。`AGENTS.md:45` 明确"全 UI 不展示心情 / 好感数值"；`AGENTS.md:36-37` 明确"UI 瞬时状态不可持久化"。

**对酒馆的具体约束**：
- `transcript.applied` 是**调试数据**，出现在「记录」Tab 时**不得呈现为"胜率/成功率/进度"**，只能是可读的事件流水；
- **不做好感度/亲密度展示**（§11 Q2 待拍板）；
- **不做体力/行动点/每日次数**（**这正是 QBN/StoryNexus 里我明确不抄的部分**）；
- 「第 N 幕 / 第 N 夜」这类**序号标签**是否允许上屏，**需用户拍板**（§11 Q4）。

---

## 6. 中大型功能域设计

### 6.1 模块划分（一图）

```
gui/tavern/                          ← 独立功能域（纯逻辑零 Qt 的部分占多数，可无显示环境测试）
  ├─ __init__.py                    # 对外只暴露 get_tavern(app_ctx) 与常量
  ├─ model.py            ★ 无 Qt     # 数据结构 + schema_version + 默认结构 + 读时迁移
  ├─ store.py            ★ 无 Qt     # 存档 IO（原子写 / 单写点 / 备份轮转）
  ├─ engine.py           ★ 无 Qt     # 状态机：apply(transform) + 三条不变量 + 硬禁区
  ├─ intent_router.py    ★ 无 Qt     # 三级路由：verbatim / propose / narrate（词表 + 规则）
  ├─ worldbook.py        ★ 无 Qt     # 关键词触发 + selective logic + 预算裁剪 + 递归上限
  ├─ prompt.py           ★ 无 Qt     # 五段式 build_story_prompt(state, book, play)
  ├─ summarize.py        ★ 无 Qt     # 摘要触发 + 校验（落盘前）
  ├─ content/                        # 内容包（数据，不是代码）
  │    ├─ lantern/                   # 「灯笼酒馆」基础包
  │    │    ├─ book.json            # 世界书条目（含 constant ≤5）
  │    │    ├─ chapters.json        # 章节 + storylet 节点
  │    │    └─ transforms.json      # 该包额外声明的受控动作（仍过白名单校验）
  │    └─ README.md                 # 世界书撰写规范（§3.2-⑥）
  └─ errors.py           ★ 无 Qt     # TavernError（中文消息，直接可呈现，对齐 CardError）

gui/pages/page_tavern.py             # 独立页：5 Tab 容器
gui/widgets/tavern/
  ├─ tavern_narrative.py             # 叙述流（流式渲染 + 重掷/编辑）
  ├─ tavern_input.py                 # 输入行 + 快捷动作按钮排（4–6 槽）
  ├─ tavern_hud.py                   # 顶部状态条（章标题，**不含数值**）
  ├─ tavern_worldbook.py             # 世界书编辑器（条目表 + 预算读数条）
  ├─ tavern_plays.py                 # 我的故事（列表 + 继续/回看/导出）
  └─ tavern_trace.py                 # 记录（applied 留痕 + 摘要，只读）

tests/test_tavern_model.py           # schema / 迁移 / 类型守卫
tests/test_tavern_engine.py          # 变换 pre/post / 三条不变量 / 硬禁区
tests/test_tavern_router.py          # 三级路由 + 降级 + 留痕字段
tests/test_tavern_worldbook.py       # 触发 / selective logic / 预算淘汰 / 递归上限 / 脏正则
tests/test_tavern_prompt.py          # 五段顺序 / reroll 不携带上版文本
tests/test_tavern_store.py           # 原子写 / 崩溃不损坏 / 迁移
tests/test_tavern_no_ra.py           # R-A 扫描（数值禁项词表）
```

**分层方向**：`gui/pages` / `gui/widgets` → `gui/tavern`（单向）。**`gui/tavern` 不 import 任何 Qt**（除 `__init__.py` 的 controller 例外），因此**绝大部分逻辑可在 offscreen / 无显示环境下测**。

### 6.2 数据模型（完整 JSON）

`~/.maid_coder/tavern/tavern.json`（单文件，`schema_version` 顶层，原子写）：

```json
{
  "schema_version": 1,
  "meta": { "created_at": "2026-09-14T20:00:00+08:00", "updated_at": "2026-09-14T21:07:33+08:00" },

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
      "play_id": "p_20260914_a1b2",
      "book_id": "lantern",
      "title": "灯笼还亮着",
      "status": "active",
      "created_at": "2026-09-14T20:00:00+08:00",
      "updated_at": "2026-09-14T21:07:33+08:00",

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
          "at": "2026-09-14T21:07:33+08:00"
        }
      ],

      "summary": { "up_to_turn": 6, "text": "【前情提要】你推门进来时，她正在擦一只杯子……", "generated_by": "llm", "verified": true },

      "llm": { "last_model": "", "last_error": "", "degraded": false, "last_propose_at": "" }
    }
  ],

  "active_play_id": "p_20260914_a1b2",

  "journal": {
    "seen_endings": [],
    "unlocked_entries": [12],
    "first_seen": { "lantern": "2026-09-14T20:00:00+08:00" }
  }
}
```

**结构要点（逐条对上"数据不乱"）**：
- **`vars` 是唯一可写状态**，且**键名受内容包约束**（`transforms.json` 声明的集合之外，一律拒绝写入）；
- **`pending` 是"当前可选项的快照"**——它是**数据**，不是每次现算。这样即使内容包更新，老存档的选项也不会"凭空变形"；
- **`transcript` append-only**，每条自带 `resolution`（留痕）；
- **`summary` 是结构化字段**（`up_to_turn` 决定"摘要覆盖到哪里"），**不是 prompt 里的临时拼接**；
- **`journal` 是跨局累积**（看过的结局、解锁的条目），**与单局的 `plays[]` 物理分离**——这正是"不互相污染"的落点；
- **`seed` 显式保存**：任何本地随机（如选项权重）都走 `random.Random(seed + turn)`，**不依赖全局 `random`**（既有游戏 `game_2048.py` 用全局 `random` 导致不可复现，**不沿用**）。

### 6.3 「数据不乱」的 14 条机制

| # | 机制 | 落点 |
|---|---|---|
| 1 | 顶层 `schema_version` + `meta{created_at, updated_at}` | `model.py` |
| 2 | **原子写**（tmp + `os.replace`） | `store.py` → `utils._atomic_write_json` |
| 3 | **单写点**：所有落盘只经一个 `save()` | `store.py` |
| 4 | **读时迁移**：默认结构为底 → `setdefault` → `isinstance` 类型守卫 | `model.py::_merge_defaults` |
| 5 | **未知字段不销毁**（前向兼容） | `model.py`（对齐 `role_card.py` 铁则） |
| 6 | **写前快照轮转**（保留最近 N 份，异常可回滚） | `store.py` |
| 7 | 单局状态与跨局累积**物理分离**（`plays[]` vs `journal`） | `model.py` |
| 8 | `vars` 键名**受内容包白名单约束** | `engine.py` + `content/*/transforms.json` |
| 9 | **三条不变量**校验（I1/I2/I3） | `engine.py` |
| 10 | **硬禁区**在最高优先级拦截（含 R-A 数值） | `engine.py` |
| 11 | `transcript` **append-only**，`applied` 不可重写 | `engine.py` |
| 12 | **显式 seed**，本地随机可复现（不依赖全局 `random`） | `engine.py` |
| 13 | **降级不抛错**：LLM 不可用 / 提议失败 → 纯叙述 + 留痕 | `intent_router.py` |
| 14 | **内容包加载校验**：脏正则 `try/compile` 丢弃、违规条目禁用并记日志、`constant` 超额裁剪 | `worldbook.py` |

### 6.4 文件清单：新增 / 修改 / 保护区

**新增**：见 §6.1 全量（`gui/tavern/**` + `gui/pages/page_tavern.py` + `gui/widgets/tavern/**` + 7 个测试 + 内容包）。

**修改（尽量少，且全部为"纯增"）**：

| 文件 | 改动 | 红线注意 |
|---|---|---|
| `gui/widgets/sidebar.py` | `NAV_ITEMS` **纯增 1 项**（4 元组结构不变） | 既有 key/label/信号零变更 |
| `gui/widgets/chat_panel_parts/extras.py` | 工具行加一个"快速开局"入口（约 12 行，复用 `_open_mini_games()` 的懒 import + `WA_DeleteOnClose` 范式，`:477-487`） | 不动既有条目 |
| `gui/app_context.py` | 末尾**纯增** 1 个字段（`tavern` 哨兵/None） | `@dataclass` 末尾追加，兼容既有构造 |
| `gui/pages/__init__.py` / `page_manager.py` | 仅**注册**新页 | 不改页面枚举语义 |
| `maid_coder_gui.spec` / `maid_coder_gui_onefile.spec` | datas +`('gui/tavern/content','tavern_content')`；hiddenimports +`gui.tavern` | 既有 datas 不动；**双 spec 同步** |

**保护区（不动）**：`gui/chat_service.py`（逻辑）/ `session.py` / `memory.py` / `companion.py` / `persona.py` / `gui/role_card.py`（逻辑，仅在被要求时按 §2.1 增字段）/ `gui/config.py` / `gui/themes/**` / `gui/motion.py`（只用不改）/ `gui/icons.py`（只用不改）/ 全部美术资产 / `requirements*.txt`（**diff 必须为空**）/ v2.0 更新链与 `main.py` 更新编排段。

### 6.5 文件域切分（供多工程师并行）

| 域 | 独占文件 | 依赖 | 说明 |
|---|---|---|---|
| **域0 契约冻结** | `gui/tavern/model.py`、`docs/` 本文件 §6.2 | — | **先行串行**：JSON schema、变换白名单、三级路由枚举、五段 prompt 结构先冻结 |
| **域1 数据层** | `store.py`、`errors.py`、`tests/test_tavern_store.py`、`test_tavern_model.py` | 域0 | 原子写 / 迁移 / 崩溃不损坏 |
| **域2 引擎** | `engine.py`、`tests/test_tavern_engine.py` | 域0 | 变换 pre/post + 三不变量 + 硬禁区，**纯逻辑可单测** |
| **域3 路由** | `intent_router.py`、`tests/test_tavern_router.py` | 域0/2 | 三级 + 降级 + 留痕字段 |
| **域4 世界书** | `worldbook.py`、`content/**`、`tests/test_tavern_worldbook.py` | 域0 | 触发 / 预算 / 递归上限 / 脏数据 |
| **域5 prompt 与摘要** | `prompt.py`、`summarize.py`、`tests/test_tavern_prompt.py` | 域0/4 | 五段式 + reroll 差异 |
| **域6 UI 页与控件** | `page_tavern.py`、`gui/widgets/tavern/**` | 域1–5 | 5 Tab；**QSS 只引 token** |
| **域7 接线** | `sidebar.py`、`extras.py`、`app_context.py`、`page_manager` 注册 | 域6 | 单写者：`sidebar.py` 与 `extras.py` 各只 1 人 |
| **域8 收口** | 两个 `*.spec`、`README` / `CHANGELOG`、真机留档 | 全部 | 串行收尾 |

**必须串行**：域0 → {域1,2,3,4,5} 并行 → 域6 → 域7 → 域8。

---

## 7. P0/P1/P2 功能清单 + 分批任务拆分

### 7.1 功能清单

**P0（"是一个完整的中大型功能域"的最小成立集）**

| id | 功能 | 说明 |
|---|---|---|
| T-01 | 独立页 + 3 Tab（今夜 / 世界书 / 我的故事） | 中大型的入口形态（§5.4） |
| T-02 | 状态机 + 7 条受控变换 + 3 条不变量 | §4.3 / §4.4 |
| T-03 | 三级意图路由（verbatim / propose / narrate）+ 全留痕 | §4.2 |
| T-04 | 世界书：关键词触发 + selective logic + 字符预算裁剪 + 递归上限 | §2.2 |
| T-05 | 五段式 prompt 组装 + reroll 差异 | §2.3 / §2.6 |
| T-06 | 叙述流式渲染（可 reroll / 可编辑文本） | §2.6 |
| T-07 | 快捷动作 4–6 槽（矢量图标，无脚本语言） | §2.7 |
| T-08 | 存档：原子写 / 迁移 / 快照轮转 / 我的故事列表 | §6.2 / §6.3 |
| T-09 | 摘要（每 8 拍或进章触发，落盘为结构化字段 + 校验） | §2.5 |
| T-10 | LLM 不可用完整降级（玩法完整、不报错弹窗） | §5.1 `_is_demo_mode` 语义 |

**P1（让它"好玩且可长期"）**

| id | 功能 | 说明 |
|---|---|---|
| T-11 | 章节与 storylet 内容包（≥3 章 × 4–6 节点 + 2 结局） | §3.2-① |
| T-12 | 人物 Tab（老板娘 + 2 位客人，均为角色卡） | §2.1 |
| T-13 | 记录 Tab（applied 留痕 + 摘要，只读） | §4.4 |
| T-14 | 世界书编辑器（条目表 + 预算读数条） | 让用户能自己加设定 |
| T-15 | 3–5 个"高影响选择"（后果预算，走 `vars`） | §3.2-③ |
| T-16 | 导出（单局导出为 Markdown / 复用 `chat_exporter` 思路） | 情感留存的出口 |
| T-17 | `propose` 档开关（关掉 → 退化为完全确定的模式） | §4.2-4 |

**P2（锦上添花 / 需另立小轮）**

| id | 功能 | 说明 |
|---|---|---|
| T-18 | 客人也能说话（借鉴 V17 F10 串行接话调度） | 复杂度显著上升 |
| T-19 | 世界书递归激活（默认关，开启时才用） | §2.2 |
| T-20 | 记忆钩子：把故事里的物件写进她日后的闲聊 | **触碰业务数据，需单独评审** |

**明确不做**：任何形式的脚本语言 / prompt 拖拽编辑器 / 好感度数值 / 行动点 / 体力 / 每日次数 / 排行榜 / 分享排行。

### 7.2 任务分解（批 0–5，对齐 `design-v21.md` 分域做法）

> 格式对齐 `docs/design-v21.md` §5：`ID / 任务 / 涉及文件 / 依赖 / 验收 / 独占`。

#### 批 0 · 契约冻结（域0，先行串行）

| ID | 任务 | 涉及文件 | 依赖 | 验收 | 独占 |
|---|---|---|---|---|---|
| **T-00** | **契约冻结**：`tavern.json` schema v1（§6.2 全字段）；7 条变换白名单与 pre/post；三条不变量；三级路由枚举与 `resolution` 字段形状；五段式 prompt 段名；世界书条目字段表；`NAV_ITEMS` 新增 key | 本文件 §4.3/§4.4/§5.4/§6.2 + `gui/tavern/model.py`（空实现可 import） | — | 常量可 import；schema 默认结构与 §6.2 一致；`_merge_defaults` 对空 dict 不抛 | 域0 单人 |

#### 批 1 · 纯逻辑内核并行（域1–5，全部无 Qt，可 offscreen 测）

| ID | 任务 | 涉及文件 | 依赖 | 验收 | 独占 |
|---|---|---|---|---|---|
| **T-01** | 数据层：默认结构 / 读时迁移 / 原子写 / 快照轮转 | `store.py`、`errors.py`、`tests/test_tavern_store.py`、`test_tavern_model.py` | T-00 | 旧档缺键 → 类默认（零迁移）；写入中断 → 旧档完好（模拟 tmp 残留）；未知字段不销毁；`os.replace` 被调用 | 域1 |
| **T-02** | 引擎：7 变换 pre/post + I1/I2/I3 + 硬禁区 | `engine.py`、`tests/test_tavern_engine.py` | T-00 | 每条变换的 pre 不满足 → 拒绝且 `reason` 正确；六条硬禁区各有用例；`vars` 白名单外键名被拒；同 seed 同输入 → 同结果 | 域2 |
| **T-03** | 路由：三级 + 降级 + 留痕 | `intent_router.py`、`tests/test_tavern_router.py` | T-00/T-02 | 命中词表 → `verbatim`；未命中且 LLM 可用 → `propose`；LLM 关闭/超时 → `narrate`；**三档都不抛异常**；`resolution` 字段齐全 | 域3 |
| **T-04** | 世界书：触发 / selective logic / 预算 / 递归 / 脏数据 | `worldbook.py`、`content/**`、`tests/test_tavern_worldbook.py` | T-00 | 四种 selective logic 各有用例；超预算按 weight→order→uid 淘汰；`recursive_max_depth` 生效且不死循环；**脏正则被丢弃且不崩**；`constant` >5 被裁剪并记日志 | 域4 |
| **T-05** | prompt 与摘要：五段式 + reroll 差异 + 摘要校验 | `prompt.py`、`summarize.py`、`tests/test_tavern_prompt.py` | T-00/T-04 | 五段顺序与 role 固定；`reroll` 版**不含**上一版叙述文本；摘要超长/空/含越权内容 → 拒绝入库 | 域5 |

#### 批 2 · UI（域6，依赖批 1）

| ID | 任务 | 涉及文件 | 依赖 | 验收 | 独占 |
|---|---|---|---|---|---|
| **T-06** | 页与 3 Tab 骨架 + 叙述流（流式 + reroll + 编辑文本） | `page_tavern.py`、`tavern_narrative.py` | T-01…T-05 | 流式渲染复用既有节奏；reroll **不改变** `transcript` 之外的任何字段（断言）；编辑只允许改 `text`；`off` 档无几何母题动画 | 域6 |
| **T-07** | 输入行 + 快捷动作排 + 顶部状态条 | `tavern_input.py`、`tavern_hud.py` | T-06 | 4–6 槽按钮全用 `icons.py` 矢量图标（**无裸 emoji**）；状态条**不含任何数值**；快捷键不与既有热键冲突 | 域6 |
| **T-08** | 世界书编辑器 + 我的故事列表 | `tavern_worldbook.py`、`tavern_plays.py` | T-06 | 增删改落盘原子写；预算读数条随条目变化；列表可继续/回看；**坏档 → 提示而非崩** | 域6 |

#### 批 3 · 接线（域7，依赖批 2）

| ID | 任务 | 涉及文件 | 依赖 | 验收 | 独占 |
|---|---|---|---|---|---|
| **T-09** | 侧栏新页 + 快速开局浮窗入口 + AppContext 字段 + 页注册 | `sidebar.py`、`extras.py`、`app_context.py`、`page_manager` | T-06/T-07/T-08 | `NAV_ITEMS` **纯增 1 项**，既有 10 项 key/label/信号零回归；浮窗复用 pomodoro 范式且关闭即隐藏；`AppContext` 既有字段零改动 | 域7（**sidebar.py 与 extras.py 各 1 人**） |

#### 批 4 · 内容与打磨（域4/6，可与批 2/3 部分并行）

| ID | 任务 | 涉及文件 | 依赖 | 验收 | 独占 |
|---|---|---|---|---|---|
| **T-10** | 内容包：3 章 × 4–6 storylet + 2 结局 + 世界书（`constant` ≤5） | `gui/tavern/content/lantern/**` | T-04 | 每章 3–5 个高影响选择；每条世界书符合 §3.2-⑥ 规范；**全包零 R-A 词** | 域4 |
| **T-11** | 人物卡（老板娘 + 2 客人）+ 记录 Tab | `content/**`、`tavern_trace.py` | T-10/T-08 | 卡可直接导入导出（复用 `role_card.py`）；记录 Tab 只读且**不呈现成功率/进度** | 域6 |
| **T-12** | 四主题视觉核对（浅/深 × 4 风格，逐页截图对照） | `gui/widgets/tavern/**`（仅样式） | T-06/T-07/T-08 | 四风格无"外来感"；**QSS 无新增裸色**；对比度 ≥4.5:1；`ui_night` 下不刺眼 | 域6 |

#### 批 5 · 收口（域8，依赖全部）

| ID | 任务 | 涉及文件 | 依赖 | 验收 | 独占 |
|---|---|---|---|---|---|
| **T-13** | 双 spec 同步（内容包 datas + `gui.tavern` hiddenimports）+ 打包冒烟 | `maid_coder_gui.spec`、`maid_coder_gui_onefile.spec` | T-09/T-10 | 双 spec 一致；onedir/onefile 包内 `_internal/tavern_content/` 有内容包；exe 内可开一局 | 域8 |
| **T-14** | **红线扫描 + 全量回归 + 真机留档** | 留档文档 | T-11/T-12/T-13 | `requirements*.txt` **diff 为空**；R-A 词表扫描零命中；`test_tavern_no_ra.py` 绿；全量 pytest 零回归；py_compile 绿；四主题真机截图留档 | 域8 |
| **T-15** | 文档收口（README 用法 / CHANGELOG 条目 / 世界书撰写规范） | `README.md`、`CHANGELOG.md`、`content/README.md` | T-14 | 如实描述"字符预算为近似"；无自评分 | 域8 |

**裁剪顺序（资源紧张时）**：`T-19/T-18`（P2）→ `T-14 世界书编辑器`（降为内置只读）→ `T-16 导出` → `T-11 记录 Tab`。**不裁**：T-01…T-10（P0 全量）与 T-14 红线/回归。

---

## 8. 界面与融入（中大型形态）

### 8.1 页面布局稿（`今夜` Tab）

```
┌──────────────────────────────────────────────────────────────────┐
│  灯笼还亮着                                    ← 章标题，无数值     │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│   她把杯子推过来，杯壁上还凝着水汽。                              │
│                                                                  │
│   柜台上那盏灯笼的火苗抖了一下 ——                                 │
│                                                                  │
│   ▍（流式渲染中，文字节奏：省略号循环 / 逐字出现）                  │
│                                                                  │
│                                        ┌────────┐ ┌────────┐     │
│                                        │ ⟳ 重写 │ │ ✎ 改字 │     │
│                                        └────────┘ └────────┘     │
├──────────────────────────────────────────────────────────────────┤
│  ⟳ 问她照片里的人   ⊙ 先喝一口   ⏳ 静等她开口                    │
│  ──────────────── 快捷动作 4–6 槽，矢量图标，无 emoji ──────────  │
├──────────────────────────────────────────────────────────────────┤
│  ┌────────────────────────────────────────────────────┐ ┌──────┐ │
│  │ 也可以直接写下你想做的事…                            │ │ 送出 │ │
│  └────────────────────────────────────────────────────┘ └──────┘ │
└──────────────────────────────────────────────────────────────────┘
```

**`我的故事` Tab**

```
┌──────────────────────────────────────────────────────────────────┐
│  灯笼还亮着            第 ? 夜 · 上次 21:07            ›           │
│  ▸ 无风的雨夜          已完结                        看结局 ›      │
│  ▸ 一杯没喝完的酒      已搁置                        继续 ›        │
└──────────────────────────────────────────────────────────────────┘
```

**要点**：① 章标题**不带"第 N 幕"**（R-A 待拍板，见 §11 Q4）；② 重写/改字是**文本级**操作，与状态无关（§2.6）；③ 快捷动作槽位**只引图标名**，不写 emoji 字面量。

### 8.2 语义键表（只用既有键，不新增色值）

| 用途 | 语义键 |
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

**取色入口**：`theme_color(app_ctx, key, fallback)`；**QSS 只引 token**。

### 8.3 动效（严格受限）

| 场合 | 做法 | 依据 |
|---|---|---|
| 叙述流式渲染 | **文字节奏**（逐字/逐段出现），复用 `chat_stream_chunks` 的节奏；生成中指示复用既有文本省略号循环 | 本项目原生第①类母题（`kb_dialog.py:33-35` 已有先例） |
| 重掷切换 | 叙述块**淡入**（`motion.fade()`，≤220ms） | 既有元素呼吸 |
| 卡片/页切换 | 沿用 `motion` 既有过渡 | 同上 |
| `off` 档 | **不创建任何动画对象** | `motion.py` 纪律 |

**明确不做**（第三类几何母题）：跳动的三个点、柱条、涟漪、旋转环、打字机光标、翻页、烛光、粒子、错峰入场、进度条。

### 8.4 集成点

| 集成点 | 改动 | 说明 |
|---|---|---|
| `sidebar.NAV_ITEMS` | +1 项（4 元组） | 结构与信号不变 |
| `extras.py` 工具行 | +1 入口（约 12 行） | 复用 `_open_mini_games()` 范式（`:477-487`） |
| `AppContext` | +1 字段（末尾） | 纯增 |
| `page_manager` | 注册新页 | 不改枚举语义 |
| 两个 spec | datas + hiddenimports | 双 spec 同步 |

**不集成**：`ChatService` / `session` / `memory` / `companion` / `GuiConfig` / QSS 文件 / `motion.py` / `icons.py` —— **全部零改动**。

### 8.5 测试要点

**可自动化（无需真机、无需联网）**：
1. schema 迁移：空档 / 缺键 / 键类型错 / 未来高版本 → 均不抛，回落到默认；
2. 原子写：模拟中途失败 → 旧档完好；
3. 引擎：7 变换 × (pre 满足 / 不满足) 共 14 例 + 6 条硬禁区 + `vars` 白名单外键名 → `reason` 逐一断言；
4. 不变量 I1/I2/I3 的**违反用例**各有断言（不变量测试最关键的是"能抓到违反"）；
5. 路由三档 + LLM 关闭 + 超时 + 脏返回，**均不抛且留痕字段齐全**；
6. 世界书：四种 selective logic、预算淘汰顺序、递归深度上限与死循环、脏正则；
7. prompt：五段顺序、`reroll` 不含上版文本；
8. R-A 扫描：`tavern.json` + 内容包 + UI 文案 **零禁项词**；
9. `vars` 键名越权、`node_id` 悬空、transcript 长度回退 → 全部被拒。

**需 mock**：LLM 调用（`api.chat` / `chat_stream_chunks`）→ 成功 / JSON 畸形 / 超时 / 抛异常 四种。

**必须真机留档**：四主题 × 浅深 的 8 组合逐页截图；流式渲染的实际观感；reroll/编辑的用户操作路径；打包态开一局。

**回归矩阵**：`sidebar` 既有 10 项导航 + 游戏角既有入口 + 聊天发送链路 + 记忆中心，抽样回归（不做全组合）。

---

## 9. 与「酒馆」题材的融合点（女仆当老板娘，是否自然）

**自然，而且是本方案最强的情感落点。**

| 角色 | 设定 | 为什么成立 |
|---|---|---|
| 女仆（码铃） | **老板娘 / 说书人** | 她本就"陪你说话"。在酒馆里，她**有一个地方**、**有一盏灯**、**为你留着位子**——这是把"陪伴"具象化 |
| 你 | 推门进来的客人 | 用户的一切输入都被世界承接，"你来了"这件事本身就有意义 |
| 客人（P1） | 2 位常客 | 让世界"不只围绕你转"，反而更真实 |

**三个具体的"只有码铃能做"的点**：
1. **她的语气样本就在角色卡里**（`example_dialogues`）——无需重新写对白风格，**她的声音是同一个**；
2. **她的记忆能成为剧情素材**（T-20，需单独评审）：她讲的"今天有个客人……"可以引用你们真实聊过的事 —— 这是 §3.2-① 的 storylet 与既有 `memory` 的结合点；
3. **四套主题即四种酒馆**：`ui_cream` 是暖灯的木质小馆，`ui_night` 是打烊后的深夜，`ui_whale` 是深海里的玻璃屋子。**零额外美术成本**。

---

## 10. 已排除的方向（v1/v2 调研压缩保留）

### 10.1 A 层：炉石"酒馆战棋"（自走棋）—— 排除
形态是**对战自走棋**，与"陪伴 + 叙事"无关；且必然引入战力/血量/胜负数值（撞 R-A）。

### 10.2 Tavern Keeper（酒馆经营模拟）—— 排除
以**经营循环**（进货、定价、翻台、装修）为主，与 LLM 能力无关；经营数值同样撞 R-A。

### 10.3 「文字冒险」作为**独立形态**—— 降级为"参照之一"，不再作为主线
v2 曾把「文字冒险」作为主线。v3 更正：用户要的是**参照 SillyTavern 的实现**。文字冒险谱系（parser 系 / AVG / 现代 IF 引擎）仍然**有价值的部分**被保留为设计方法来源（§3.2），但**不再作为形态主张**。

### 10.4 行业旁证（支持"陪伴 + 轻量叙事"路线）
`AI Dungeon` 的用户规模证明了"自由输入 + 生成叙述"的需求真实存在；其官方后继 `Voyage` 用"**后果有重量**"换来显著更高的评价，反向印证了**"必须让选择有代价"**这条设计原则（§3.2-⑦）。

---

## 11. 风险与 Non-goals

### 11.1 风险

| # | 风险 | 影响 | 对策 | 回退 |
|---|---|---|---|---|
| 1 | **`propose` 档命中率不可知**（§3.3 的论文未量化证明） | 用户觉得"我说了它没反应" | 三级路由以 `verbatim` 为主路径；`mode` 分布可统计（§4.4） | 关掉 `propose`（T-17），退化为完全确定模式 |
| 2 | **字符预算 ≠ token 预算** | 长条目可能超出模型真实上下文 | 预算取保守值；单条 ≤200 字；文档如实标注"近似" | 下调 `worldbook_budget_chars` |
| 3 | **中大型规模带来维护成本** | 内容包/引擎/UI 三线并行 | 域切分（§6.5）+ 纯逻辑无 Qt 可测（§6.1） | 按 §7.2 裁剪顺序缩减 P1/P2 |
| 4 | **摘要质量不稳** | 长期剧情脉络走样 | 摘要落盘 + 过校验；世界书承担事实召回（双保险） | 停用 LLM 摘要，只用规则摘要 |
| 5 | **内容写作量** | 3 章 × 4–6 节点是真实工作量 | 用 storylet 结构降低增量成本（§3.2-①）；先 1 章打通全链路 | 首发 1 章 |
| 6 | **切换主题后"外来感"** | 用户对"外来感"极度敏感 | QSS 只引 token；四主题 × 浅深 逐页截图核对（T-12） | 回退到既有卡片形态 |
| 7 | **`~/.maid_coder` 双目录既有缺陷** | 数据分散，用户困惑 | 酒馆**只写 `~/.maid_coder/tavern/`**，不碰 `%APPDATA%` | — |

### 11.2 Non-goals（明确不做）

1. 不做脚本语言 / 插件执行面；
2. 不做 prompt 拖拽编辑器；
3. 不做任何 R-A 禁项数值（含隐藏不展示）；
4. 不做好感度 / 亲密度 / 行动点 / 体力 / 每日次数；
5. 不做向量检索（零依赖约束下不可能）；
6. 不做多人联机 / 分享排行；
7. **不改 `GuiConfig`**（设置全部放 `tavern.json.settings`）；
8. **不改 `ChatService` / `session` / `memory` / `companion`**；
9. 不引 WebView / 游戏引擎；
10. 不新增运行时第三方依赖（`requirements*.txt` diff 必须为空）。

### 11.3 需要用户拍板的问题

**Q1 · `propose` 档（LLM 提议变换）要不要做？**
- **① 做（本报告建议）**：自由度更高，但引入了"未证明可靠性"的环节（§3.3），需接受偶尔"它没听懂"。
- ② 不做，只保留 `verbatim + narrate`：**行为完全确定、100% 可测**，但自由度明显低一档。
- ③ 做但**默认关**、由用户在设置里打开：稳妥，代价是多数用户不会发现它。

**Q2 · 故事里的选择要不要影响"关系"？**
- **① 一期完全不写（本报告建议）**：零数值污染，故事只是故事。
- ② 写进既有 `intimacy`（内部，**不展示**）：延续项目既有做法，但新增"玩故事能刷关系"的路径 —— 需评估是否违背 R-A 防"刷好感"的精神。
- ③ 只在「我的故事」里留一句可读的话：仍无数值，但要写业务数据。

**Q3 · 形态与首发范围**
- (a) 入口形态：**① 独立页 + 页内 Tab（建议）** / ② 独立页 + 保留快速开局浮窗 / ③ 两者都要。
- (b) 首发做多深：**① P0 全量（T-01…T-10，建议）** / ② P0 + 1 章内容（更快见效） / ③ P0 + P1 内容包（体量最完整）。

**Q4 · R-A 口径**：「第 N 幕 / 第 N 夜」这类**序号标签**能否上屏？本报告默认**不用序号、只显示章标题**（如"灯笼还亮着"）。若允许序号，UI 上会更"像游戏"，但需要用户确认不违反 R-A。

---

## 附录 A：证据链接汇总

**SillyTavern 机制**
1. World Info（官方）：https://docs.sillytavern.app/usage/core-concepts/worldinfo/
2. World Info（中文）：https://sillytavern.wiki/usage/core-concepts/worldinfo/
3. World Info 源码级结构（DeepWiki，含 `WIScanEntry` / 四种 selective logic / 预算与排序）：https://deepwiki.com/SillyTavern/SillyTavern/6.1-slash-commands
4. Prompt Manager（顺序 / Triggers / Position / Depth / Order）：http://docs.sillytavern.app/usage/prompts/prompt-manager/
5. Prompts 总览（含 pinned 默认项与主提示词建议）：https://docs.sillytavern.app/usage/prompts/
6. Author's Note（官方）：https://docs.sillytavern.app/usage/core-concepts/authors-note/ ；中文：https://sillytavern.wiki/usage/core-concepts/authors-note/
7. STscript 语言参考（官方）：https://docs.sillytavern.app/usage/st-script/ ；中文：https://sillytavern.wiki/usage/st-script/
8. Quick Replies（中文译介，含 100 槽与 `/addvar` 示例）：https://ima.qq.com/wiki/ （酒馆SillyTavern 助手）
9. 角色卡 V2 规范原文（GitHub）：https://github.com/malfoyslastname/character-card-spec-v2/blob/main/spec_v2.md
10. V2/V3 格式说明（DeepWiki）：https://deepwiki.com/aleph23/easytavern/4.2.1-character-card-formats
11. 建卡指南（字段语义）：https://tavernsprite.com/blog/sillytavern-character-card-creation-guide/
12. Lorebook 使用（scan depth / token budget / priority / recursive）：https://docs.chub.ai/docs/venus-documentation/lorebooks

**世界书撰写方法**
13. kissable《AI Lorebook Guide》（always-active 3–5 条、3–5 要点、标题带别名、实跑迭代）：https://kissable.app/blog/ai-lorebook-guide
14. Chattica docs（"ten tight entries beat one essay"；"stable world facts early, situational state late"；摘要可见可编辑）：https://www.chattica.ai/docs.html
15. pixelchat Lorebook（约 20% 上下文上限——**注意：这是该产品的数值，非 SillyTavern**）：http://docs.pixelchat.ai/product-guides/lorebook

**storylet / QBN**
16. Emily Short《Storylets: You Want Them》：https://emshort.blog/category/if-languages/
17. Emily Short《Pacing Storylet Structures》：https://emshort.blog/category/craft/
18. StoryNexus（IFWiki）：http://www.ifwiki.org/StoryNexus
19. Quality-Based Narrative 术语与史料（含 2010 原始定义、2017 改称 resource narrative）：https://videlais.github.io/simple-qbn/qbn.html
20. StoryNexus 建模笔记（"本质上是一个大状态机"，storylets = 状态、qualities = 变量）：https://troygilbert.com/modeling-games/thoughts-on-storynexus
21. 中文译介（落日间：storylet 架构与《80 天》）：见 Emily Short 三篇译文合辑

**分支 / 涌现 / 世界状态建模**
22. Sunnyheadcase《What Do You Even Mean By Branching Narrative?》（branch and bottleneck / hub and spoke / gauntlet）：https://www.sunnyheadcase.com/?p=2658
23. Interactive Storytelling Techniques（agency 两分、foldback、consequence budget 3–5）：https://grokipedia.opelly.me/articles/interactive-storytelling-techniques
24. Film Threat：分支叙事的系统性逻辑与 QA（"think in states rather than scenes"、branch convergence、不变量测试）：https://filmthreat.com/features/building-branching-interactive-cinema-without-breaking-the-backend-systems-asset-flowcharts-and-qa-workflows-for-narrative-heavy-projects
25. ScienceDirect：角色驱动互动叙事的情节结构管理（世界状态 = 一组谓词；动作 = `(act, PRE, POS)`）：https://www.sciencedirect.com/science/article/pii/S1875952123000459

**LLM 记忆与上下文**
26. Quickchat AI：AI Roleplay 指南（四策略对照表：滑动窗口 / 摘要 / RAG / 混合）：https://quickchat.ai/post/ai-roleplay-telegram
27. Field Guide to AI：Context Management（滚动窗口 + 摘要、结构化记忆、"不要过度压缩"）：https://fieldguidetoai.com/guides/context-management
28. `Lost in the Middle` 的工程实践总结（"把上下文窗口当缓存，不是硬盘"）：https://dev.to/aioperator2026/why-ai-roleplay-characters-forget-who-they-are-after-30-turns-the-context-window-problem-3i7d
29. 生产实践四种策略（结构化记忆由专用抽取步骤写入，LLM 不自由写）：https://dev.to/adamo_software/how-we-handle-llm-context-window-limits-without-losing-conversation-quality-1eh5
30. MOOM 论文（叙事摘要分支 + 人物构建分支 + 竞争-抑制遗忘）：https://lacuna.tiptreesystems.com/paper/moom-maintenance-organization-and-optimization-of-memory-in-ultra-long-role-playing-dialogues

**世界状态变换（核心方法）**
31. **Góngora et al.《World-State Transformations for Neuro-symbolic Interactive Storytelling》，arXiv:2605.24719**：https://arxiv.org/html/2605.24719v1 （PDF：https://arxiv.org/pdf/2605.24719 ；代码：https://github.com/sgongora27/transformations）
32. **Pith 同行评审**（明确指出 8 人 / 2 场景 / 纯定性、无指标、无纯 LLM 基线）：https://pith.science/paper/2UZB52DD （另一入口：https://pith.science/paper/2605.24719 ）

**AI Dungeon 失败档案**
33. `bex.co` 负面反馈综述（重复循环 / 幻觉 / 改名 / "角色卡最终被忽略"）：https://bex.co/blog/2025/04/17/negative-feedback-on-llm-powered-storytelling-and-roleplay-apps
34. `arcanumrpgs` AI Dungeon 评测（含官方后继 **Voyage** 用骰子/技能检定/HP/永久死亡换"后果有重量"，4.4 vs 2.6）：https://arcanumrpgs.com/blog/ai-dungeon-review
35. `aitestguide` 2026 评测（"Memory is average… long sessions need reminders"）：https://aitestguide.com/?p=1943/

**码铃仓内依据（只读引用）**
36. `AGENTS.md:36-37`（UI 瞬时状态不可持久化）、`AGENTS.md:45`（全 UI 不展示心情/好感数值）
37. `gui/role_card.py:36-42`（导出白名单 R-I）、`docs/character-card-spec.md`（.malingcard.json schema v2）
38. `helpers.py:419-426`（`KnowledgeBase` = 关键词 + TF-IDF）、`gui/widgets/kb_dialog.py:1-9`、`gui/widgets/kb_worker.py:1-23`
39. `gui/intent.py:117-188`（词表加载 / 逐条 try compile / 合并覆盖）
40. `session.py:232-239 / 315-338`（`_trim_history` / `auto_summary` 与 `【前情提要】`）
41. `gui/chat_service.py:294`（`GROUP_HISTORY_LIMIT = 60`，截断用条数）
42. `gui/chat_service.py:1017-1113 / 1247-1371 / 1302-1351 / 534-548 / 575`（流式 worker / 注入序位 / demo 语义 / 语气注入）
43. `api.py:42-91 / 93-101`（`chat` / `chat_stream_chunks`）
44. `gui/session_manager.py:14 / 149-156`（`~/.maid_coder` 业务数据 + **非原子写缺陷**）
45. `gui/config.py:149-229`（`GuiConfig.save()` 逐键列举陷阱）
46. `gui/widgets/sidebar.py:109-119`（`NAV_ITEMS` 4 元组 × 10 项）
47. `gui/widgets/chat_panel_parts/extras.py:477-487`（工具行入口范式）
48. `gui/widgets/pomodoro_dialog.py:34-37 / 224-226`（浮窗 + controller + 关闭即隐藏）
49. `gui/motion.py`（`MAX_DURATION_MS = 220`、`loop()` 周期夹取）、`gui/icons.py`（Remix Icon 2.5.0）、`gui/widgets/kb_dialog.py:33-35`（文字节奏既有先例）
50. `docs/design-v21.md` §3.1–§3.4、§5、§7（文件清单 / 文件域切分 / 分批任务 / 测试策略的格式来源）

---

## 附录 B：诚实声明（查不到 / 不确定）

1. **我未运行任何代码、未做任何冒烟验证。** §6.4 的集成点是"设计意图与既有代码的接口对齐"；§6.5/§7.2 的验收是**设计要求**，不是已通过的验证结果。
2. **我未修改任何产品文件**，仅在 `docs/` 下产出本报告（只读调研）。
3. **"token 预算"我无法精确实现**：码铃没有 tokenizer（零依赖约束），且项目既有裁剪用的是**条数**（`GROUP_HISTORY_LIMIT = 60`）。本方案统一改用**字符数**并标注为**近似**，**不承诺**与实际 token 数的对应关系。SillyTavern 文档中的 `world_info_budget / budget_cap` 是**百分比与绝对 token 上限**，我**没有查到**其默认具体数值，因此**未引用任何默认值**。
4. **世界书的"召回质量"未经我验证**：关键词触发在"用户换一种说法"时会漏（这正是 §3.3 论文里记录的"共指消解失败"）。**没有向量检索**是明确的架构限制，其用户体验代价我**没有数据**。
5. **摘要质量我没有任何量化证据**：本项目 `auto_summary()` 的实际效果我未测；本方案"摘要落盘 + 过校验"只能防"坏数据入库"，**不能保证摘要内容本身准确**。
6. **`propose` 档的可靠性有明确的反方证据**：arXiv:2605.24719 只有 **8 名参与者 / 2 个场景 / 纯定性**，Pith 评审指出**无一致性错误率、无变换命中准确率、无评分者间信度、无纯 LLM 基线**。**请不要把"LLM 预测变换"当成已被验证的可靠机制**——本方案用三级路由与降级留痕来对冲这一点，但它**仍然是本设计里最不确定的一环**。
7. **"酒馆"作为中文固定词组仍无权威定义。** 本版按用户澄清的"参考 SillyTavern 的实现"执行；若用户实际想要的是别的（例如"酒馆场景的自由对话扮演"而**不要结构化玩法**），则 §4 的状态机与变换层要大幅削减。**这一条仍列在 Q1/Q3 里。**
8. **我查不到"码铃目标用户"对 SillyTavern / 互动叙事偏好的任何直接证据。** 已确认项目历史任务与 `docs/` 中**没有**"酒馆 / SillyTavern / 文字冒险 / 互动小说"的直接需求痕迹（本次是首次引入）。
9. **"文字冒险 / 互动叙事的留存率"我没有可靠数据**，只有间接旁证（AI Dungeon 的用户规模、`Voyage` 的评分跃升）。**不要把这个形态的留存想当然。**
10. **内容写作量我无法精确估计。** §7.1 T-11 的"3 章 × 4–6 节点"是**建议体量**，不是测算结果。
11. **`~/.maid_coder` 与 `%APPDATA%\maid_coder` 双轨的成因我仍未查清**，只做事实陈述与规避建议（§5.3）。
12. **四个"快速回复按钮"的最终文案与图标名我未定稿**，需在 T-07 中与视觉口径一起定。
