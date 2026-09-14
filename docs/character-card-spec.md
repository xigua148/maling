# 码铃角色卡格式规范（.malingcard.json）— schema v2

- 版本：v2（v1.8.0 起生效；design-v18.md D-V18-06 / Q-D7）
- 维护人：高见远（架构）· 实现对照：`gui/role_card.py`
- R-K 核对承诺：本文档与实现**逐字段一致**，发版前按本表核对。

---

## 1. 文件格式

单文件 JSON（UTF-8，无 BOM），文件名建议 `<角色名>.malingcard.json`。
**单文件自包含**：封面以 base64 内嵌，分享只需传一个文件（Q-D7 裁决）。
整卡体积上限 **1MB**（`MAX_CARD_BYTES`，超限拒绝导入）。

## 2. 字段表（v2）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `card_type` | str | 否 | 恒为 `"malingcard"`；存在但非此值 → 拒绝导入；缺失容忍（手写 JSON 可导入） |
| `schema_version` | int | 否 | v2 卡为 `2`；缺失/为 1 按 v1 兼容处理 |
| `exported_at` | str | 否 | ISO 时间戳，仅信息展示 |
| `name` | str | **是** | 角色名，非空，≤50 字（超长截断） |
| `given_name` | str | 否 | **v1.9 新增**。她的名字（自称用），≤30 字；空串/缺失 = 无名字 → 自称「我」。**人设标签（`name`）永不用作自称**（design-v19 D-V19-01） |
| `description` | str | 否 | 角色描述 |
| `system_prompt` | str | 否 | 人设提示词 |
| `personality` | object | 否 | `{lively, rigorous, caring}` 三值 int（0–100，越界夹取）；缺省 50 |
| `opening_lines` | str[] | 否 | 开场白，≤3 套（`MAX_OPENING_LINES`），空项剔除 |
| `example_dialogues` | object[] | 否 | `{user, assistant, enabled}`，≤5 组（`MAX_EXAMPLE_DIALOGUES`），user/assistant 必须均为字符串 |
| `current_expression` | str | 否 | 默认表情 key，缺省 `"normal"` |
| `cover_image` | str | 否 | **v2 新增**。封面 data URI（`data:image/png;base64,…` 或 jpeg），base64 部分连同前缀 ≤500KB（`COVER_MAX_B64_BYTES`）；源图导入时等比压至 512px 内（`COVER_MAX_PIXEL`）。空串/缺失 = 无封面（角色列表回退既有头像逻辑） |

## 3. 兼容性声明

- **v1 → v2 导入**：全兼容。v1 卡缺 `cover_image` → 导入为无封面；其余字段逐项一致（回归用例：tests/test_v17_batch3_f8.py round-trip + tests/test_v18_batch2.py v1 兼容组）。
- **v2 → 未来版本（前向兼容铁则）**：导入方只读白名单字段，**未知字段忽略不崩**。
- **v1 旧卡（schema_version 1 或缺失）零回归**：解析行为与 v1.7.3 一致。

## 4. 排除项（白名单外永不入卡，R-I 硬线）

以下内容**绝不**出现在角色卡的任何字段中（导出白名单机制天然保证 + 测试断言）：

- 用户记忆（preferences / topics / entities / response_rules / vision_memories）
- 亲密度与关系数据
- 对话历史
- API 配置与密钥
- 角色内部 id / avatar 文件路径 / created_at / is_default

## 5. 导入校验规则（实现：`parse_card`）

按序执行，命中即抛 `CardError`（含中文原因）：

1. 根节点必须是 JSON 对象；
2. 序列化体积 ≤1MB；
3. `card_type` 存在时必须为 `"malingcard"`；
4. `name` 必须为非空字符串。

其余字段全部类型守卫 + 默认值，**绝不抛错**（缺字段 = 默认值；脏字段清洗）。特殊规则：

- `cover_image` 非 data URI 的裸 base64 自动补 `data:image/png;base64,` 前缀；**超限/非法封面降级为空串**（不拒整卡），导入预览弹窗红字提示 +「仍要导入」确认（Q-D7）。
- 导入重名：`dedupe_import_name` 收敛为「XX（导入）」，仍冲突追加序号。

## 6. 导入预览（实现：`gui/widgets/card_import_preview.py`，v1.7 Q-C10 收编）

导入确认前逐项展示：名称 / 名字（未设置则提示「自称我」）/ 描述 / 系统提示词摘要 / 性格三值（**档位词「偏上·适中·偏低」呈现，不显数值**，R-A）/ 开场白套数 / 示例对话组数 / 封面缩略图；封面异常或超限逐项红字 + 显式确认；名称冲突时提示将自动改名的最终名。

## 7. 版本历史

- v1（v1.7）：name/description/system_prompt/personality/opening_lines/example_dialogues/current_expression。
- v2（v1.8）：新增 `cover_image`（内嵌封面 ≤500KB，512px 内等比压缩）；性格预览改档位词呈现（数值仍存卡内供编辑器使用）。
- v2.1（v1.9）：新增 `given_name`（她的名字，空 = 自称「我」；旧卡缺字段零迁移）；导入预览增名字行。
