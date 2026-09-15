# 酒馆内容包（worldbook.v1）撰写规范

> 本目录是「酒馆」随包发布的内容包。**是数据不是代码** —— 只放 JSON 与说明，
> 不含任何可执行脚本（design-v22 D-V22-15 / research §2.2）。
>
> 落点纪律（**改这里前必读**）：内容包随包依赖 `maid_coder_gui*.spec` 的 `datas`
> 目标路径 **必须等于「源码相对 `gui/` 的路径」**，即 `source_dir == gui/<target>`。
> 本目录对应的正确写法是 `('gui/tavern/content', 'tavern/content')`，
> 运行时用 `gui.utils.get_resource_path("tavern/content")` 解析（见
> `gui/tavern/worldbook.py::content_dir`）。**切勿写成 `tavern_content`** —— 源码态会静默读空。

## 目录结构

```
content/
├── README.md                 # 本文件（撰写规范 + 内容契约）
└── <book_id>/                # 一本书一个目录（首发：lantern）
    ├── book.json             # 世界书条目（供 WorldBook 消费）
    ├── chapters.json         # 章节 + storylet 节点 + **按 scene 分组的动作面**
    └── transforms.json       # `var_names`（var 名校验）+ 快捷动作（UI）
```

> **解析入口唯一**：`gui.tavern.worldbook.load_content(pack_id) -> dict`。
> 它把三个文件解析合并为一个冻结形状的 `content: dict`（engine / router / prompt **只消费这个 dict，不解析文件**）。
> 键与语义见下节「内容包 ↔ engine 读取键契约」。

## 内容包 ↔ engine 读取键契约（design-v22 §4.2，冻结）

`load_content(pack_id)` 产出的 `content` dict 键（**全部可缺省**；缺省 = fail-closed）：

| 键 | 结构 | 声明落点（本项目） | 缺省语义 |
|---|---|---|---|
| `node_ids` | `[str,…]` 全局 | 由 `chapters[].nodes[].id` 自动推导（可在 `chapters.json` 顶层显式 `node_ids` 覆盖） | I2 无法判定 → 放行 |
| `scene_ids` | `[str,…]` 全局 | 由 `reachable`/`known_topics`/`menu` 键 + `open_conditions` 的 `"<scene>:…"` 推导（可显式覆盖；**过滤空串**） | I2 放行 |
| `reachable` | `{scene:[scene,…]}` **按 scene 分组** | `chapters.json` 顶层 | 缺 → `move_to` 报 `no_reachable_target` |
| `known_topics` | `{scene:[topic,…]}` **按 scene 分组** | `chapters.json` 顶层 | 缺 → `ask_about` 报 `topic_not_known` |
| `menu` | `{scene:[item,…]}` **按 scene 分组** | `chapters.json` 顶层 | 缺 → `order` 报 `menu_empty` |
| `open_conditions` | **扁平** `{"<scene>:<key>": bool, "<key>": bool}` | `chapters.json` 顶层 | 缺 → `open` 报 `condition_not_met` |
| `openable` | `[key,…]` 全局（可选） | `chapters.json` 顶层 | 缺 → 仅看 `open_conditions` |
| `var_names` | `[str,…]` 全局 | `transforms.json` 顶层 | 缺 → 只认 `DEFAULT_VAR_NAMES`；写自定义 var → `forbidden:unknown_var` |

**硬性约束（否则 engine 判 `precondition_failed:*` / `forbidden:*`）**：

1. `reachable` / `known_topics` / `menu` 是**按 scene 分组**的 dict（key = `scene_id`），**不是全局列表**；`open_conditions` 是**扁平** dict（键用 `"<scene>:<key>"` 复合式，回退 `"<key>"`）。
2. `var_names` **只追加**：与基底 `DEFAULT_VAR_NAMES`（`poured/knows_name/held_items/scene_items/given/opened/known`）取**并集**；不得删/覆盖基底 7 名；`vars` 命名值总数 ≤ `MAX_VARS=8`。
3. 本期 engine **只校验 var 的「名」**，**不消费类型/值域** —— 不必（也不要据此设计）在 `transforms.json` 写 type/range。
4. **写自定义状态只能走 `effects`**（形如 `[{"field":…, "op":"append|set|remove|edit", "value":…}]`，`op` 缺省 = `set`）；`field` ∈ 三个推进字段（`scene_id`/`node_id`/`turn`）+ `transcript` + `var_names` 声明的 var。**`write_vars` 不是受支持入参**（会被 `bad_args:unexpected_args:write_vars` 拒绝）。
   - 本包示例：`opening` 节点的 **`look_around`** 选项、`counter_photo` 节点的
     **`look_closer`** 选项，用 `transform:"wait"` + **`choice.args.effects`** 写声明过的 var
     `photo_seen`（`{"field":"photo_seen","op":"set","value":true}`）。
   - ⚠️ **落点是 `choice.args.effects`，不是节点级 `node.effects`** —— 本包 18 个节点的 `node.effects` **全为空**，engine 也不读节点级 `effects`。写状态一律走「选项 `transform` + `args.effects`」这条受控通道。
5. **每个 scene 想用哪些动作，就必须把对应键写全**（缺省即该动作不可用，绝不误放行）。
6. 起始 scene 为**空串 `""`**（`model.new_play` 置 `scene_id=""`）：开局可用的 `move_to`/`order`/`ask_about` 必须把 `""` 作为 scene 键写进 `reachable`/`menu`/`known_topics`。
7. **「不卡死」不变量（批次 D 校正口径）**：内容包必须保证「**从任一可达状态出发，都能在有限步内抵达某个结局**」。落地成四条可核事实：① `""` 经开局节点的 `move_to` 一步进入已声明地点集；② `reachable` 的**每一个键（含 `""`）**都能（经传递闭包）走到 `backdoor`；③ 每个非终局节点至少有一条 `move_to` 出口；④ 终局节点前置由互斥且穷尽的条件区分（本包 = `scene_id == backdoor` + `opened` 的 `has / has_not letter`）。
   - ⚠️ **注意口径**：**不是**「每个非终局节点都有一条 `move_to backdoor` 直连出口」—— 本包的 `opening` 节点**没有** `move_to backdoor`（只有 `sit_down → counter`），`reachable[""]` 也**不含** `backdoor`。旧文档/旧用例曾这样写，且只遍历 `content["scene_ids"]`（**不含 `""`**）⇒ 把初始空场景**悄悄豁免**了，属"声明 ≠ 实现 ≠ 测试"。现以本条为准。
   - 可执行口径：`tests/test_v22_content_quality.py::test_scene_graph_closes_on_backdoor_from_every_scene_including_start`（场景图闭包，含 `""`）+ `tests/test_v22_play_e2e.py::test_no_dead_end_from_any_reachable_state_including_empty_scene`（真 service 完整状态空间可达性，含 `""`）。

> 自检：`tests/test_v22_worldbook.py::test_content_declarations_satisfy_referenced_choices` 逐条 choice 校验「引用的 target/topic/item/key 是否都已声明」，缺一即红。

### `prerequisites`（节点 / 选项准入条件）的算子写法

`chapters[].nodes[].prerequisites` 与 `choices[].prerequisites` 是 `{键: 期望值}` 映射，
**每个键都要满足**才放行；判定状态面 = `play.vars` ∪ `{"scene_id"}`。

值有 **5 种形态**（① 为原有严格等值；②–⑤ 为 **2026-09-15 经用户批准的契约扩展**，
单一来源 = `gui/tavern/service.py::PREREQ_OPERATORS`，设计见 `docs/design-v22.md` §4.2）：

```jsonc
{ "scene_id": "counter" }                          // ① 严格等值（原有；现有内容包全走这条）
{ "opened":   { "has": "drawer" } }                // ② 列表包含单项
{ "known":    { "has_all": ["photo", "name"] } }   // ③ 列表包含全部（取值必须是 list）
{ "opened":   { "has_not": "latch" } }             // ④ 列表不包含（做「你还没做过 X」）
{ "poured":   { "not": "long_night" } }            // ⑤ 标量不等于（列表请用 has_not）
```

- **为什么需要**：`opened` / `known` / `held_items` / `scene_items` / `given` 这 5 个基底变量
  **都是列表型**（由 `open` / `ask_about` / `take` / `give` 自动 append 维护）；没有算子时，
  列表永远不等于字符串 → 这 5 个变量**完全无法用于分支**。算子让它们第一次真正可用。
- **fail-closed（写错一律"不通过"，绝不崩）**：键不在状态里 → 不通过；一个 dict 里**出现 >1 个算子**
  或**未知算子名** → 不通过；`has` / `has_all` / `has_not` 用于**非列表** → 不通过；`not` 用于**列表**
  → 不通过；`has_all` 取值不是 list → 不通过；`has_all` 取值是**空 list** → 不通过
  （空表在集合语义下恒真 = vacuous truth，与"写错一律不通过"同口径）。
- **不支持**：值域为 `dict` 的 var **无法用等值分支** —— 值形态 `dict` 已被算子形态占用
  （`{"var": {"some_key": v}}` 会被当作算子判定，未知算子名一律不通过）。这类 var 只能走算子形态。
- **示例**（"读过信"才给的下一个节点）：

```jsonc
// chapters[].nodes[]
{ "id": "letter_seen",   "prerequisites": { "opened": { "has": "letter" } } }
{ "id": "letter_unseen", "prerequisites": { "opened": { "has_not": "letter" } } }
```

### `load_content()` 返回形状（**形状示意**；真实全量见 `content/lantern/*.json`）

> 首发包 `lantern` 现为 **3 章 / 18 个节点 / 5 个 scene**（`""` + `counter` / `backdoor` / `window` / `table`），
> 选项 **76** 条（`choice_id` 全局唯一，且与 `quick_actions[].action_id` 不冲突）。
> `node_ids` 较长（18 项），故此处**只示意形状与量级**，一切以真实解析为准。

```json
{
  "book_id": "lantern",
  "node_ids": ["opening", "counter_photo", "long_night", "…"],   // 由 chapters[].nodes[].id 推导（现有 18 项）
  "scene_ids": ["counter", "backdoor", "window", "table"],       // 过滤空串后
  "reachable": {
    "":        ["counter"],
    "counter": ["counter", "backdoor", "window", "table"]
  },
  "known_topics": {
    "":        ["photo"],
    "counter": ["photo", "name", "lantern", "guest", "door"]
  },
  "menu": {
    "":        ["long_night"],
    "counter": ["long_night"]
  },
  "open_conditions": { "backdoor": true, "counter:drawer": true, "oil": true, "latch": true, "letter": true },
  "openable": ["drawer", "oil", "latch", "letter"],
  "var_names": ["photo_seen"],

  "worldbook": { "book_id": "lantern", "entries": [ /* … */ ], "cast": [ /* 人物卡，见 §book.json */ ] },
  "chapters": [ /* chapters.json 的 chapters[] 原样 */ ],
  "quick_actions": [ /* transforms.json 的 quick_actions[] 原样 */ ]
}
```

- 前 9 个键是 **§4.2 冻结键**（engine/router/prompt 消费）；后 3 个（`worldbook` / `chapters` / `quick_actions`）是**附加键**，engine **不读**，仅供 prompt / UI 复用（`content["worldbook"]` 即 `book.json` 原样，可直接喂 `WorldBook.from_result(load_book(content["worldbook"]))`）。
- **不**输出 `nodes` / `scenes` 别名（避免与 `check_i2` 的别名读取撞名）。
- 三个附加键之外，**缺省键一律按上表 fail-closed**；`node_ids`/`scene_ids` 缺省时由**解析器**自动推导（规则见上表「声明落点」列）。

### 文件里怎么写（`chapters.json` / `transforms.json` 顶层模板）

```jsonc
// chapters.json —— 动作面写在本文件顶层；chapters[] 只描述节点线
{
  "book_id": "lantern",
  "reachable":    { "": ["counter"], "counter": ["counter", "backdoor"] },
  "known_topics": { "": ["photo"],   "counter": ["photo", "name"] },
  "menu":         { "": ["long_night"], "counter": ["long_night"] },
  "open_conditions": { "backdoor": true, "counter:drawer": true },
  "openable": ["drawer"],
  "chapters": [ { "chapter_id": "ch1", "title": "…", "nodes": [ /* id/title/text/llm_brief/prerequisites/effects/choices[] */ ] } ]
}

// transforms.json —— var 名声明 + UI 快捷动作
{
  "book_id": "lantern",
  "var_names": ["photo_seen"],                 // 只列「基底 7 名之外」的新名；基底 7 名无需在此重复
  "quick_actions": [ { "action_id": "order_drink", "label": "来一杯", "icon": "glass",
                       "transform": "order", "args": { "item": "long_night" } } ]
}
```

> `icon` 只能用 `gui/assets/icons/icons_manifest.json` 里**已登记**的名字（如 `glass` / `menu_book` / `search` / `moon`），否则 UI 取不到字形。

## book.json

```json
{
  "book_id": "lantern",
  "title": "灯笼酒馆",
  "builtin": true,
  "entries": [ { /* 18 字段条目 */ } ]
}
```

### 条目 18 字段（顺序即 `gui.tavern.model.WORLDBOOK_ENTRY_FIELDS`）

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `uid` | int | 0 | 条目 id（书内唯一；重复的正数 uid 会被丢弃并留痕） |
| `title` | str | `""` | 条目标题（编辑器显示） |
| `keys` | list[str] | `[]` | **主键**：命中任一即通过第一道闸 |
| `secondary_keys` | list[str] | `[]` | **次键**：与 `selective_logic` 组合精化 |
| `selective_logic` | str | `AND_ANY` | ∈ `AND_ANY` / `NOT_ALL` / `NOT_ANY` / `AND_ALL` |
| `content` | str | `""` | 条目正文，**≤ 200 字**（超长会被截断并留痕） |
| `position` | str | `system_tail` | 落点 ∈ `system_head` / `system_tail` / `history_depth` |
| `depth` | int | 0 | 仅 `history_depth` 有意义（插到历史第几层） |
| `order` | int | 100 | 同权重内排序（越大越靠前） |
| `weight` | int | 100 | 预算淘汰优先级（越大越先保留） |
| `constant` | bool | false | 常驻条目（无视关键词），**全书 ≤ 5 条** |
| `probability` | int | 100 | 命中后按百分比决定是否插入（0–100） |
| `sticky` | int | 0 | 命中后保持 N 拍（保留位） |
| `cooldown` | int | 0 | 命中后冷却 N 拍（保留位） |
| `recursive` | bool | false | 其正文可再触发其他条目（受全局深度上限约束） |
| `case_sensitive` | bool | false | 是否区分大小写 |
| `enabled` | bool | true | 是否启用 |
| `budget_chars_est` | int | 0 | 正文字数估计（缺失/非法时由正文长度推算） |

### 触发与 selective logic 口径

索引窗口 = 最近 `settings.worldbook_scan_depth` 拍文本。

- `primary_hit` = 任一 `keys` 命中（`keys` 为空且非 `constant` → 永不触发）；
- 无 `secondary_keys` → `selective_logic` 不参与，命中主键即激活；
- `AND_ANY` = 主键命中 **且** ≥1 个次键命中；
- `AND_ALL` = 主键命中 **且** 全部次键命中；
- `NOT_ALL` = 主键命中 **且** 非全部次键命中（含 0 个）；
- `NOT_ANY` = 主键命中 **且** 0 个次键命中。

正则键：写成 `/pattern/flags`（如 `/长夜(酒)?/i`）。**编译失败逐条丢弃**，
不会「一条脏规则炸掉整本世界书」（对齐 `gui/intent.py` 的既有写法）。

### 预算与淘汰（字符预算，**近似非 token**）

- 单条正文 ≤ **200 字**（`LORE_MAX_CONTENT_CHARS`）；
- 单回合注入总量 ≤ `settings.worldbook_budget_chars`（默认 **1600** 字）；
- 单回合关键词命中条目数 ≤ `settings.max_lore_entries_per_turn`（默认 **3**）；
- 超预算时按 **`weight` 降序 → `order` 降序 → `uid` 升序** 保留靠前者、截断其余；
- `constant` 条目优先保留且不占「每回合条数」名额。
- **UI 与文档只说「约 X 字」，绝不承诺 token 数**（码铃无 tokenizer）。

### 递归

`recursive: true` 的条目，其正文会再次进入索引窗口去触发**其他**条目；
递归深度上限 `settings.recursive_max_depth`（默认 **2**），并带 visited 集合
防 snowball。**默认关闭**。

## 撰写方法（社区共识，逐条落地）

1. **一条目一主题**，独立成篇；
2. **3–5 条要点**，别把一段设定写成论文；
3. 标题与 `keys` **带上常见别名**（玩家怎么写，就怎么命中）；
4. `constant` **只留给 3–5 条基础世界规则**，否则预算被瓜分到「每条都触发不了」；
5. **稳定事实放前（`system_head`）、情境状态放后（`system_tail`）**；
6. 写完实跑几遍，按「常触发 / 从不触发 / 触发过频」迭代。

## 红线（写作时自查）

- **零 R-A 禁项**：不出现好感/心情/经验/货币/筹码/胜率/连胜/进度条/断签/倒计时；
- **零序号**：章节与节点标题**不写**「第 N 夜 / 第 N 幕 / 第 N 章」，只写标题；
- 正文只用文本，**不写颜色 / 字号 / 任何样式**（那是主题层的事）。
