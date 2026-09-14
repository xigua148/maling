# 角色专属形象资产（表情差分）

每个角色可拥有一套独立的表情差分图集，切换角色时左下角大形象/首页大形象/气泡头像随之切换。

## 目录约定
- 目录名 = 角色 id（如 `preset_whale`、`preset_cat`、你自建角色的 id）
- 文件名 = 表情 id + `.png`（如 `normal.png`、`happy.png`、`thinking.png`）
- 完整表情 id 清单见 `assets/maid/manifest.json`；也支持自定义扩展名（会被自动发现）
- 规格：方形透明背景 PNG（建议 ≥512×512，与 assets/maid/ 同规格）

## 回落规则
目录中缺失的表情，自动使用码铃本体（assets/maid/）同表情图顶替——
所以你不必一次画满 38 张，放一张 normal.png 就能让角色形象生效。

## 查找优先级
1. `~/.maid_coder/role_assets/<角色id>/`（用户本地覆盖，升级不丢）
2. 本目录（随包内置，开源用户体验完整）
