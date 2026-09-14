# maid/ 形象资产目录（占位说明）

> 本目录当前仅含 `manifest.json` 与本文档。**PNG 表情资产尚未到位**
> （由美术 / AI 出图后导入）。缺图策略（v1.2x 用户拍板）：程序绘制的占位脸默认
> **不显示**（`gui/maid_avatar.py` 的 `PLACEHOLDER_ENABLED=False`），形象位显示
> 中性铃铛/花瓣兜底；PNG 到位即自动启用真形象，无需改代码。

## 资产清单（8 表情，文件名 = 表情 id）

| 表情 id      | 类别     | 说明                     |
|--------------|----------|--------------------------|
| `normal.png`    | 心情态 | 默认微笑                 |
| `happy.png`     | 心情态 | 开心                     |
| `concerned.png` | 心情态 | 担忧（主人低落/疲劳）    |
| `shy.png`       | 心情态 | 害羞（被夸奖/高等级）    |
| `tired.png`     | 心情态 | 犯困（深夜）             |
| `thinking.png`  | 活动态 | 思考/流式回复中          |
| `focus.png`     | 活动态 | Agent 专注干活           |
| `surprised.png` | 活动态 | 惊喜/彩蛋（短暂，回落）  |

## PNG 出图规格（供美术 / AI 导入参考）

- 命名：`{expression_id}.png`，小写，与 `manifest.json["expressions"]` 完全一致。
- 建议主形象按 **2x 出图**（展示约 260~340px 高）：即高度约 520~680px、
  正方形或接近方形、主体居中，预留裁剪安全边距。
- 透明背景 PNG 优先（气泡/圆形裁剪/角落宠物需叠加不同背景）。
- 风格一致：同一形象同一画师批次，线稿/上色/头身比保持统一。
- 主题变体（A6 换装预留，P2）：命名 `{expression}_{theme}.png`（如 `normal_maid.png`），
  加载器已按 `MaidAssets.load(theme=...)` 预留查表结构。

## 加载与回退约定（B1）

- 加载：`gui/maid_avatar.py` 经 `gui.utils.get_resource_path("assets/maid/…")` 定位，
  校验 manifest + 图像非空 + 尺寸 > 0；任一缺失/损坏 → 该表情回退 QPainter 占位脸
  （底色块 + 铃铛符号 + 按表情画眉眼/嘴型）。
- 打包：`maid_coder_gui.spec` datas 已含 `('gui/assets/maid', 'assets/maid')`，
  **目录只含 manifest 也必须保留**（防打包漏资源）。
