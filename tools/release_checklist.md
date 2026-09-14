# 码铃（MaLing）v2.0 发版清单（Release Checklist）

> 固化自 `docs/prd-v20.md` §6（12 步）与 `docs/design-v20.md` §7。
> 使用方式：**从上到下逐项勾选**，任一门禁未过不得进入下一步。
> ⚠ 标注为**占位/未决项**，上线前必须显式消解。

---

## 上线前必须先裁决/替换的占位项（硬闸，未消解禁止上线）

- [ ] **`GITHUB_OWNER` 占位替换**：`gui/update_checker.py:53 GITHUB_OWNER = "your-github-name"` 与
      `version.json` 中的所有 `<owner>` / `your-repo` 必须替换为**真实公开仓库 owner**。
      验证：`grep -rn "your-github-name\|your-repo\|<GITHUB_OWNER>" gui/ version.json` **零命中**（R-O③ 硬闸）。
- [ ] **真实下载地址待建**：GitHub 公开仓库 `<owner>/maling` 与 Release 尚不存在 → 建库后第 9/10 步才可执行。
- [ ] **`downloads.github` 非空**（R-O / ⚠-5 硬闸）：空值 = 客户端永不提示新版。
- [ ] **未做代码签名（Q-U7）**：Release 说明必须**如实写明"未做代码签名，Windows 可能提示未知发布者"**（R-O④ 诚实）。

---

## 12 步发版流程

### 1. 定版号
- [ ] 确定 `X.Y.Z`（`v` 前缀小写，三段式）。
- [ ] 同步改 `core/__init__.py` 的 `__version__` 与仓库 `version.json` 的 `version`。
- [ ] `CHANGELOG.md` 写入该版本条目（如实描述，**不含自评分**，R-K）。
- [ ] **门禁**：`get_version()` 返回新值。

### 2. 全量测试
- [ ] `QT_QPA_PLATFORM=offscreen pytest`（受管 Python）。
- [ ] **门禁**：基线 v1.9.0 零回归 + v2.0 新增用例全绿。
- [ ] 记录测试数（passed / skipped / failed）。

### 3. 构建 sidecar（updater）— 必须在 onedir 之前
- [ ] `pyinstaller --noconfirm --clean --distpath dist_updater updater.spec`
      ⚠ **注意**：`updater.spec` 未设 `distpath`，**必须显式 `--distpath dist_updater`**，
      否则产物默认落到 `dist/maling_updater.exe`，后续两个主 spec 的 datas 路径会落空。
- [ ] **门禁**：`dist_updater/maling_updater.exe` 存在，体积 ≈7.24MB，**无 Qt / 无 requests**。

### 4. 构建 onedir
- [ ] `pyinstaller --noconfirm --clean maid_coder_gui.spec`（默认 → `dist/maling/`）。
- [ ] **门禁**：`dist/maling/_internal/updater/maling_updater.exe` 存在（内嵌 sidecar）。

### 4b. 复制 Pi 运行时到 onedir（⚠ **硬步骤，V20-17 新增，漏做=包少 61MB+**）
- [ ] `python copy_pi_runtime.py --dist dist/maling`
      ⚠ Pi 运行时是**「打包后复制」**机制：两个主 spec **都不含** `pi_runtime` datas，
      必须构建完 onedir 后再跑本步，才会把 `pi_runtime`（node.exe + Pi 依赖树）
      落进 `dist/maling/_internal/`。**历史上已因漏跑此步出过"zip 少 61MB"的事故**。
      （`--dist` 接的是 **app 目录 `dist/maling`**，不是 `dist` 根；脚本内部会顺带把
      `pi_gateway/maling_gate.js` 兜底复制进 `_internal/pi_gateway/`。）
- [ ] **门禁（压缩前必过）**：确认 `dist/maling/_internal/pi_runtime/` 存在且文件数为**万级**
      （实测源与 v1.9.0 分发目录均为 **13,567** 个文件；`find dist/maling/_internal/pi_runtime -type f | wc -l`）。
      **不达标不得进入第 6 步压缩**（`tools/build_release.py` 已内置同款 fail-fast 守卫，会直接拦下）。

### 5. 构建 onefile
- [ ] `pyinstaller --noconfirm --clean maid_coder_gui_onefile.spec` → `MaLing_single.exe`。
- [ ] **门禁**：内含内嵌 updater **且** 内含字体 datas（见第 4/5 步核验项，⚠-10 修复）。
- [ ] ⚠ **onefile 为便携模式，不内置 Pi 编程引擎**（Q-U10 裁决）——无需对 onefile 跑第 4b 步。

### 6. 压缩 onedir + 算 sha256 + 生成片段（一条命令）
- [ ] `python tools/build_release.py --version X.Y.Z --dist-dir dist --out release`
      （onedir 源 `dist/maling/`、onefile 源 `dist/MaLing_single.exe`；可用 `--onedir-src/--single-src` 覆盖）
- [ ] 该脚本**内置 fail-fast 守卫**（默认拦截，防静默产残缺包）：
  - [ ] `pi_runtime` 存在且文件数 ≥ 10000（等价第 4b 步门禁）→ 否则非 0 退出「疑似漏跑 copy_pi_runtime.py」
  - [ ] onedir 内嵌 `_internal/updater/maling_updater.exe` 存在且体积 ≈7.2MB → 否则非 0 退出（把 sidecar distpath 错误暴露在发版脚本层）
  - [ ] 逃生开关 `--skip-pi-check`（默认**关闭**，仅限有意出精简包时显式开启）
- [ ] 产出：
  - [ ] `release/MaLing_vX.Y.Z_win_onedir.zip`（顶层 `maling/`）
  - [ ] `release/MaLing_vX.Y.Z_win_single.exe`
  - [ ] `release/MaLing_vX.Y.Z_win_onedir.zip.sha256`（内容 `<64hex>  <文件名>`，**两个空格**）
  - [ ] `release/MaLing_vX.Y.Z_win_single.exe.sha256`
  - [ ] `release/version_fragment.json`（人工粘贴用，**脚本不改 version.json**）
- [ ] **门禁**：命名符合 Q-U2；`.sha256` 内容格式合规、可校验（`certutil -hashfile <f> SHA256` 复核一致）。

### 7. 写 Release 说明
- [ ] 从 `CHANGELOG.md` 抽该版本条目 + 安装/更新说明 + **两个 sha256 值**。
- [ ] 如实说明**未做代码签名**（R-O④）；不写自评分（R-K）。

### 8. 建 GitHub Release
- [ ] 打 tag `vX.Y.Z` → New release → 标题 `码铃 vX.Y.Z — <本期主题>`。
- [ ] 上传 ①zip ②exe ③两个 `.sha256` 文本。
- [ ] **门禁（硬）**：上传前 `grep` 确认 `GITHUB_OWNER` 已替换（见顶部占位项）。

### 9. Release 可下载性验证
- [ ] 浏览器无痕 + 国内网络各试一次，确认 302 到 `objects.githubusercontent.com` 可通。
- [ ] 若不通 → 配置备用链（`downloads.mirror` / `assets.*.mirror`）并填入下一步。

### 10. 更新 `version.json`（**这一步才让客户端"看到"新版**）
- [ ] 把 `release/version_fragment.json` 合并进仓库 `version.json`：
      `version` / `released_at` / `notes` / `release_url` / `downloads.github`(+`mirror`) /
      `assets.onedir` / `assets.single` /（必要时 `min_compatible` / `min_updatable`）。
- [ ] `downloads.github` **非空**（硬闸 ⚠-5）。
- [ ] commit + push 到 `main`。
- [ ] ⚠ **顺序铁律**：必须第 8/9 步产物**已可下载**后再 push，否则"客户端看到新版但包 404"。

### 11. 分发到小圈子
- [ ] 微信群 / 朋友圈发 **Release 页面链接**（新用户整包下载）。

### 12. 端到端自测（真机留档，对应 V20-16）
- [ ] 用上一版（如 v1.9.0）**真实安装包**启动 → 收到提示 → 下载 → 校验 → 安装 → 拉起新版。
- [ ] **核对 `%APPDATA%/maid_coder` 用户数据仍在**（聊天记录 / 记忆 / 配置 / persona）。
- [ ] onedir / onefile × {正常 / 断网续传 / 校验失败 / 目录不可写} 八路径留档。
- [ ] 记录：更新前后用户数据域文件清单 + mtime 零变化（白名单三键除外）。

---

## 本次收口（V20-17）打包核验证据位（供发版时填空）

| # | 核验项 | 期望 | 实测 |
|---|---|---|---|
| ① | `_internal/updater/maling_updater.exe` | 存在，≈7.24MB | ______ |
| ② | `_internal/assets/fonts/` | 3 ttf + 2 OFL | ______ |
| ③ | onefile 内嵌字体（`pyi-archive_viewer` / `.toc` grep `assets/fonts`） | 命中 | ______ |
| ④ | onedir `maling.exe` offscreen 冒烟 | 启动不崩 | ______ |

---

## 回滚 / 兜底提示

- 更新失败 → 设置页一句"可重试"提示（R-A 无焦虑，不弹聊天区/首页）。
- 备份保留最近 **1 个**版本（Q-U6）；新版稳定启动后清理更早备份。
- 目录不可写（如 `Program Files`）→ 不自动替换，改为"下载完成，请手动解压替换"（Q-U12）。
