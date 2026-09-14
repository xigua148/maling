# assets/maid_pet —— 角落微型宠物（A8/A8-1）资产目录

本目录服务 **A-9 窗口角落微型常驻宠物（MaidPet）**，与主形象资产
`gui/assets/maid/` 相互独立。

> v1.2「宠物造型」全局开关：聊天气泡头像与窗口角落宠物可在
> **女仆小兽（chibi，本目录）** 与 **女仆小人（maid，`gui/assets/maid/`）**
> 两形态间切换。选「女仆小人」时，角落宠物与气泡头像改用主形象资产目录；
> 本目录的资产约定仍适用于小兽形态。首页大形象 / 侧栏 / 托盘恒为小人本体。

## 当前状态（v1.2）

**无宠物 PNG 资产。** 只提交 `manifest.json` 与本说明占位。

运行时表现：`gui/widgets/maid_pet.py` 的 `PetAssets`（继承
`MaidAssets` 加载器）发现目录内无 PNG / PNG 缺失损坏时，**默认不渲染
程序绘制的占位小兽**（`PLACEHOLDER_ENABLED=False`，用户拍板「先去掉小兽小人，
画好真图再启用」），控件显示中性 🔔 兜底；`PLACEHOLDER_ENABLED=True`
可临时预览 `PetChibiPainter` 占位小兽（调试用）。UI 永不空白 / 崩溃。

## 资产约定（PNG 到位即替换，接口不变）

- `manifest.json`：声明 5 态表达式
  `normal / happy / thinking / focus / tired`（A8-1 微型档先行 5 态）；
- PNG 文件名 = 表情 id，如 `normal.png`、`happy.png`；
- 建议按 2x 出图（微型档展示 24~64px，运行时由加载器缩略）；
- 其余 8 态输入（concerned/shy/surprised）由
  `pet_expression_for()` 收敛到 5 态内，无需单独导图；
- 打包：`maid_coder_gui.spec` 已加 datas 目标 `assets/maid_pet`；
  加载路径与 `gui/utils.get_resource_path("assets/maid_pet/…")` 对齐。

## 出图参考（可选项）

- 猫耳方向（猫娘化小兽），主体占画布约 60%；
- 铃铛：头顶发饰小金铃；领结：胸前蝴蝶结（女仆装）；
- 表情：开心 = 弯月眼 + 张嘴笑 + 腮红；思考 = 视线飘斜上；专注 = 正视 + 平眉；
  困倦 = 半闭眼；默认 = 圆点眼 + 微笑。
