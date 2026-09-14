# 码铃（MaLing）v2.0 增量 PRD ——「自动更新与分发：让已下载的人自动拿到新版本」

- 版本：v2.0（增量 PRD，承接 prd-v16 / prd-v17 / prd-v18 / prd-v19 的需求池格式与颗粒度）
- 文档状态：草案（**用户已拍板托管与分发形态：GitHub Releases 托管 + 用户小圈子渠道分发**；本文档不再抛回已定项，Q-U 系仅列实施口径待拍板）
- 维护人：许清楚（产品经理）
- 关联文档：`docs/prd-v19.md` + `docs/design-v19.md`（最近一期，格式基准）+ `docs/prd-v16.md` §红线（R-A / R-D / R-F 沿用源）+ `README.md` + `CHANGELOG.md`（基线 **v1.9.0**）+ 代码现状以源码为准（`gui/update_checker.py` / `gui/main.py` / `gui/utils.py` / `gui/config.py` / `version.json`）。工作副本仅限 `maling_agent_dev/` 与 `docs/`，**严禁触碰 `D:/【开发中版本】/maling_v1.0.0_src/`**。
- 修订记录：
  - **v2.0a（2026-09-10）**：立项草案。用户原话「我想做个正常软件，怎么把更新内容自动分发给已经下载过的用户呢」→ 拍板托管用 GitHub Releases、用户自己在微信群/朋友圈分发。v2.0 主攻「把 v1.0.0 就有的半手动更新（发现新版 → 复制链接 → 手动重新下载）升级为软件级的自动更新」：L1 检查 / L2 下载 / L3 自动替换重启 三层递进。红线沿用 R-A / R-D / R-F，新增 R-M / R-N / R-O（编号说明见 §8：R-L 已被 v1.9 字体授权占用，本期从 R-M 起）。

---

## 0. 一句话背景

码铃从 v1.0.0 起就有 `gui/update_checker.py`（230 行）——但它只做到「**提醒**」：启动后异步拉一次 `version.json`，发现新版就弹一个非阻断提示，用户点「复制下载链接」，然后**自己去浏览器粘贴、下载 248MB 的 zip、手动解压、手动替换**。这条链路对开发者是"半自动"，对用户是"全手动"，而 `VERSION_JSON_URL` 目前还是占位地址 `https://raw.githubusercontent.com/your-repo/maling/main/version.json`。

v2.0 一句话：**让"装过一次码铃的人"从此不用再手动下载整包——发现新版 → 后台下载 → 校验 → 退出时自动换包 → 重新拉起，用户只需要点一次"更新"。** 分发继续走 GitHub Releases（权威清单与产物），国内网络友好地配一条可配置的备用链，用户自己的微信群/朋友圈渠道也能当备用链来源。

---

## 1. 版本目标与范围

### 1.1 现状事实基线（已逐条核码，作为需求落点依据）

| # | 事实 | 源码/产物证据 | 对本期的影响 |
|---|---|---|---|
| F-1 | 现有更新能力 = **只检查、只提示、不下载、不安装** | `gui/update_checker.py` 全文；`gui/main.py:908-915` 接线；`gui/main.py:740-767` 提示弹窗（复制链接 / 忽略此版本） | 本期在其上做**增量扩展**，不推翻既有契约（R-D） |
| F-2 | 版本比较走 `core.parse_version`（数值元组）+ `is_newer_version`；纯函数 `evaluate_update / format_update_text / pick_download_link` 可测 | `update_checker.py:99 / :212 / :224` | 新增逻辑继续以**纯函数**为核心，便于 pytest 直接断言 |
| F-3 | `min_compatible` 低于本地 → 提示「建议重新下载安装」（`kind=reinstall`） | `update_checker.py:122-135` | 本期新增 `min_updatable`：低于它**禁止自动替换**、只能整包重装（见 L3） |
| F-4 | 用户数据目录与应用目录**分离** | `gui/utils.py:21-29`：`%APPDATA%/maid_coder`（Windows） | **换包不丢数据是可行的前提**；L3 全程把该目录列为禁区 |
| F-5 | 忽略态存独立文件（不进 config.yaml） | `update_checker.py:43-74`（`update_state.json`） | 本期在同一文件上**增量扩字段**，不新建第二份状态（Q-U3） |
| F-6 | 分发形态为**双产物**：onedir（`dist_v190f/maling/`：`maling.exe` + `_internal/`，含 `pi_runtime/` 13574 文件，整目录 **536MB / 13984 文件**，压缩 zip **248.1MB**）+ onefile（`MaLing_single.exe` **178MB**） | 打包产物核对 | 体积大 → **增量/delta 更新不现实**，按"整包替换"设计（§7 Non-goals） |
| F-7 | 含 Pi 编程引擎运行时（`_internal/pi_runtime/`）→ 单版本包即 248MB 级 | 同上 | 下载链路必须能**断点续传 + 校验**，否则弱网成功率低 |
| F-8 | Windows 现实：**运行中的 exe 及其所在目录内的文件无法被自身覆盖或删除**；但运行中的 exe **可被重命名** | 平台特性 | L3 必须靠**外部协助进程（sidecar updater）**在码铃退出后换包；onefile 另有"改名旧 exe"技巧可用 |
| F-9 | 目标用户在国内，GitHub raw / Releases 直连常慢或不可达 | 背景补充 | L1/L2 必须设计**主链（GitHub）+ 备用链（镜像 / 小圈子渠道）**降级，链路可配、可关 |
| F-10 | 打包红线 R-F：零第三方运行时依赖（`requests` 已是既有依赖） | prd-v16 §红线 / requirements | 更新功能**不得**引入新运行时第三方库；校验用标准库 `hashlib`，重启用 `subprocess` |

### 1.2 三层递进（v2.0 核心叙事）

| 层 | 一句话 | 用户获得 | 对应需求 |
|---|---|---|---|
| **L1 检查更新** | 知道有新版本，且不打扰 | 静默检查（沿用）+ 手动入口 + 频道选择 | L1-1 ~ L1-5 |
| **L2 下载更新** | 点一下就下，慢网也能下完 | 进度 / 续传 / 重试 / 校验 / 降级 / 可取消 | L2-1 ~ L2-7 |
| **L3 自动替换 + 重启** | 退出时自动换好，重开就是新版 | 备份 → 换包 → 拉起 / 失败回滚 / 数据零丢失 | L3-1 ~ L3-6 |

### 1.3 明确不进 v2.0（Non-goals，详见 §7）

增量/delta 补丁更新、静默强制更新（无确认自动替换）、macOS / Linux 自动更新、应用商店渠道（Microsoft Store / 应用宝等）、更新内容做灰度 A/B 分发、更新包内热补丁（只换单个 Python 文件）。

---

## 2. 需求池

> 优先级口径沿用：**P0 = 本期必达 / P1 = 目标内应交付 / P2 = 可裁**。工作量含自测。验收标准一律写成**可断言**形式（纯函数 / 状态文件 / 目录检查 / 可 mock 的下载器）。

### 2.1 L1 · 检查更新（5 条）

| ID | 优先级 | 需求 | 一句话说明 | 核心对接点 | 工作量 | 风险 |
|---|---|---|---|---|---|---|
| **L1-1** | P0 | 启动静默检查（沿用 + 频道化） | 主窗显示后异步拉当前频道 `version.json`；超时/失败静默；Prompt 非阻断 | `update_checker.UpdateChecker.start()` / `main.py:908-915` | 0.5d | 低 |
| **L1-2** | P0 | 手动「检查更新」入口 | 设置页（关于/更新区）提供按钮，点击后同步走同一检查链并有明确结果反馈 | `page_settings.py` + `page_about.py` + `UpdateChecker` | 0.5d | 低 |
| **L1-3** | P1 | 频道 channel（stable / beta） | 用户可选「稳定版 / 测试版」；两频道各自 `version.json` URL；切换后下次检查即生效 | `VERSION_JSON_URL` 常量 → 频道表 + `GuiConfig.update_channel` | 0.5d | 低 |
| **L1-4** | P0 | `version.json` 作轻量版本指针，权威清单与产物在 GitHub Releases | `version.json` 只放"指向信息"（版本号 / 要点 / 产物 URL / sha256 / 大小），不承载产物；Releases 是唯一权威来源 | `version.json`（字段契约见 §4.1） | 0.5d | 中 |
| **L1-5** | P0 | 提示节奏与红线（无焦虑） | 非模态、可忽略；同一版本忽略后**同日不重弹**、有新版本才恢复；绝不因更新问题弹模态卡死 | `save_ignored_version` + `update_state`（§4.3） | 0.5d | 低 |

**验收标准**

- L1-1：①启动路径下 `UpdateChecker` 检查发生时主窗已 `show()`（时序断言）；②网络失败 / 超时 / JSON 非法一律**不弹窗**、不抛异常、日志 ≤ info 级；③检查耗时不阻塞事件循环（主窗可交互）。
- L1-2：①手动入口点击后 ≤5s 内给出确定结果之一：`有新版本 vX.Y.Z` / `已是最新` / `检查失败，请稍后重试`（三态可断言）；②手动检查**不受**"忽略此版本"影响（用户主动查必出结果）；③按钮在检查中置灰并显示"检查中…"。
- L1-3：①`channel=stable` 与 `channel=beta` 命中的 URL 不同（常量表断言）；②非法频道值回落 `stable`；③`update_state.json` 记录当前频道，跨重启保持。
- L1-4：①`version.json` 中**不含**二进制/产物正文，单文件 < 8KB（断言）；②`evaluate_update` 对缺失 `assets` 的旧式 `version.json` 仍可按 L1 正常提示（向后兼容，不抛异常）。
- L1-5：①提示控件为非模态（`setModal(False)`）+ 可关闭；②同一 `ignored_version` 在 `last_prompt_date == today` 时 `should_prompt()==False`（纯函数断言）；③出现比被忽略版本更新的版本时恢复提示（复用 `evaluate_update` 语义，断言）。

### 2.2 L2 · 下载更新（7 条）

| ID | 优先级 | 需求 | 一句话说明 | 核心对接点 | 工作量 | 风险 |
|---|---|---|---|---|---|---|
| **L2-1** | P0 | 下载进度 UI | 下载中显示百分比 / 已下-总大小 / 速度 / 剩余时间；可取消 | 新 `gui/update_downloader.py` + 进度组件 | 1d | 中 |
| **L2-2** | P0 | 断点续传（HTTP Range） | 中断后从已下字节继续；服务端不支持 Range 时回退整包重下 | 下载器（`requests` + `Range` 头） | 1d | **中高** |
| **L2-3** | P0 | 重试与降级链 | 单链失败自动重试 N 次 → 失败则切备用链（镜像 / 小圈子渠道）续传 | 下载器 URL 列表 + 循环 | 0.5d | 中 |
| **L2-4** | P0 | sha256 校验 | 下载完成对 `_internal` 之外的 zip/exe 算 sha256，与 `version.json.assets[*].sha256` 比对；不符即作废删除并重下 | `hashlib`（标准库，守 R-F） | 0.5d | 低 |
| **L2-5** | P0 | 暂存目录 | 下载到 `%APPDATA%/maid_coder/updates/<version>/`；与安装目录、用户数据隔离 | `get_user_data_dir()` | 0.5d | 低 |
| **L2-6** | P1 | 磁盘空间预检 | 下载前检查暂存盘可用空间 ≥ 包大小 × 1.3 + 解压峰值；不足则明确提示并**不启动下载** | `shutil.disk_usage`（标准库） | 0.5d | 低 |
| **L2-7** | P1 | 下载形态自适应 | 按当前安装形态（onedir / onefile）选择对应产物（zip / exe）；形态判定见 §4.4 | 运行时形态探测 | 0.5d | 中 |

**验收标准**

- L2-1：①进度回调**纯函数可测**（给定 `received/total` 输出 `percent/speed/eta` 文本）；②`percent` 随字节单调不减；③取消后 ≤1s 内停止写盘并**删除 `.part` 临时文件**（或保留供续传，口径见 Q-U4）。
- L2-2：①以 mock 服务端支持 `Accept-Ranges` 时，第二轮从 `received` 字节续传（断言请求头 `Range: bytes=<received>-`）；②服务端返回 200（不支持续传）时自动重下且不产生重复字节；③`.part` 文件大小 == `received`（可断言）。
- L2-3：①主链连续失败达阈值 → 切备用链（断言请求 URL 序列）；②任一链成功即产出完整文件；③全部链失败 → 状态置 `failed` 且**保留 `.part`**（下次可续）。
- L2-4：①`verify_sha256(path, expected)` 纯函数：正确返回 `True`、篡改 1 字节返回 `False`；②校验失败时自动删除已下文件并**不进入 L3**；③sha256 缺失（旧式 `version.json`）→ 降级为"仅大小比对 + 提示无法校验"，口径见 Q-U5。
- L2-5：①产物落 `%APPDATA%/maid_coder/updates/<version>/`（断言路径）；②**绝不**写入安装目录（换包前）；③暂存目录内文件在安装成功后被清理（保留最近 1 份）。
- L2-6：①可用空间不足时返回明确错误码且**不发第一个 GET**（断言）；②空间充足时正常下载。
- L2-7：①onedir 安装取 `assets.onedir.zip`，onefile 安装取 `assets.single.exe`（mock 断言）；②形态探测失败时默认按 onedir 处理并留日志。

### 2.3 L3 · 自动替换 + 重启（6 条）

| ID | 优先级 | 需求 | 一句话说明 | 核心对接点 | 工作量 | 风险 |
|---|---|---|---|---|---|---|
| **L3-1** | P0 | sidecar updater 换包 | 码铃退出后，由**安装目录之外**的协助进程完成换包并拉起新版 | 新 `tools/` 或打包进包的 updater 可执行体 + `subprocess` 拉起 | 2.5d | **高** |
| **L3-2** | P0 | onedir 换法：整目录 rename-swap | 旧目录整体改名 `.bak` → 新目录就位 → 新 exe 拉起；失败则 `rename` 回滚 | sidecar 文件操作 | （含 L3-1） | **高** |
| **L3-3** | P0 | onefile 换法：改名旧 exe → 写新 exe → 重启 | 利用"运行中 exe 可改名"特性；旧 exe 改名 `.old`，写入新 exe 后拉起 | sidecar | （含 L3-1） | 中高 |
| **L3-4** | P0 | 备份与回滚 | 保留上一版 `.bak`（含 exe / 整目录）；新版启动自检失败或拉起失败 → 回滚到上一版并留日志 | sidecar + 启动自检标记 | 1d | 高 |
| **L3-5** | P0 | 绝不触碰用户数据 | `%APPDATA%/maid_coder` 全程**只读引用、零写入、零迁移、零删除** | 代码守卫 + 验收扫描 | 0.5d | 中 |
| **L3-6** | P1 | 失败静默降级 | 任何换包失败都不得导致"打不开软件"：保留旧版可继续用，仅留日志 + 下次设置页可见一句提示 | 启动自检 + `update_state.last_install` | 0.5d | 中 |

**验收标准**

- L3-1：①sidecar 运行时**不位于**被替换目录内（断言其 `sys.executable`/路径不在安装目录之下）；②主进程退出前**不删除**任何在用的包文件；③sidecar 以 detached 方式拉起，主进程退出流程（v1.6.1 `_quit_stop_services`）零回归。
- L3-2：①换包成功后安装目录为**新版内容**（校验新版 `version` 文件/标记）；②换包失败（模拟移动被拒）→ 旧目录完整回滚（逐文件比对或目录存在性断言）；③全程不产生"两个半成品目录"（原子性：先 rename 再 move）。
- L3-3：①onefile 换包后 `sys.executable` 路径不变、文件内容为新版（大小/sha256 断言）；②旧 `.old` 文件在下次启动时清理；③若目标 exe 被占用无法写入 → 进入重试/回滚路径而非崩溃。
- L3-4：①存在 `backup_path` 且新版拉起失败 → 自动回滚后旧版可正常启动（断言）；②回滚结果写 `update_state.last_install = {version, result:"rolled_back", at}`；③`.bak` 默认保留**1 个版本**，安装成功且新版稳定启动后按 Q-U6 口径清理。
- L3-5：①换包前后 `%APPDATA%/maid_coder` 下**文件清单与 mtime 零变化**（除 `update_state.json` 本身，断言）；②代码扫描：换包路径内无对该目录的 `unlink/rmtree/rename/write`（静态检查 + 单测）。
- L3-6：①模拟 sidecar 缺失 → 主程序仍能正常启动并进入设置页提示"更新未完成，可重试"；②任何更新异常不影响聊天 / 启动 / 记忆（回归断言）；③异常全程仅日志 + 一句非阻断提示，无模态报错。

### 2.4 需求计数

- L1：5 条（P0×4、P1×1）
- L2：7 条（P0×5、P1×2）
- L3：6 条（P0×5、P1×1）
- **合计 18 条**（P0×14、P1×4；总量约 11–13 人日，L3 为最大风险批）

---

## 3. 待确认问题 Q 列表（Q-U 系——需用户拍板项已加粗标注）

| # | 问题 | 默认建议 | 是否需用户拍板 |
|---|---|---|---|
| **Q-U1** | **GitHub 仓库名与归属**：`version.json` 与 Releases 托管在哪个仓库？公开还是私有？ | 公开仓库 `<owner>/maling`（公开才能让 `raw.githubusercontent.com` 无需 token 读取 `version.json`；私有仓库需带 token，违背"零凭证更新"）。**默认占位 `your-repo/maling`，上线前必须替换。** | ✅ **必须拍板** |
| **Q-U2** | **产物命名规范**：Release asset 怎么命名？ | `MaLing_v<X.Y.Z>_win_onedir.zip` 与 `MaLing_v<X.Y.Z>_win_single.exe`，并各自附 `.sha256` 文本文件（内容 `<hash>  <filename>`）。版本号三段的 `v` 前缀统一小写。 | ✅ **必须拍板** |
| **Q-U3** | **备用链（镜像）形式**：用户小圈子里怎么放备用链？ | 三选一（可都支持）：①国内对象存储/静态站直链（如自有域名 / 腾讯云 COS）；②网盘分享链接（**不可用于自动下载**，手动兜底）；③GitHub 代理镜像。**默认：`downloads.mirror` 支持任意 https 直链；网盘链接只出现在"复制链接"兜底与 release notes 里，不进自动下载链。** | ✅ **需要拍板** |
| **Q-U4** | **取消下载后 `.part` 去留** | 保留 `.part`（支持下次续传），仅当用户显式"删除已下载"时清理。 | 建议即可 |
| **Q-U5** | **sha256 缺失时的降级策略** | 旧式 `version.json`（无 `assets.sha256`）→ **不允许自动替换**，仅提示"发现新版（无法校验，建议手动下载）"。安全优先于便利。 | 建议即可 |
| **Q-U6** | **`.bak` 备份保留策略** | 保留最近 **1 个**版本；新版成功启动并经一次"稳定启动标记"后清理更早的备份。磁盘占用 onedir 约 536MB，需在设置页给出"清理更新缓存"按钮。 | 建议即可 |
| **Q-U7** | **是否加代码签名（code signing）** | 本**不强制**（证书有成本、且当前分发是"用户自己解压运行"的非商店形态）。列为 Q 而非 Non-goal：若未来做企业分发/上商店再补。**默认不签名，但 release notes 需如实说明。** | ✅ **需要拍板** |
| **Q-U8** | **稳定/测试频道是否本期做** | 本期做 **stable 必达 + beta 可选**（beta 复用同一套机制、只换 URL）；若资源紧张，beta 可降为 v2.0.x 补。 | 建议即可 |
| **Q-U9** | **更新触发方式默认值** | 默认 **"自动检查 + 自动下载 + 手动确认安装"**（下载在后台静默完成，安装前弹一句"已下载好 vX.Y.Z，是否现在重启安装？"），**不做无确认静默替换**。理由见 §9 主张。 | ✅ **需要拍板** |
| **Q-U10** | **安装形态默认主推** | onedir（`maling/` 整目录 zip）为**官方主推**（可整目录 swap、更稳）；onefile 保留但标注"便携模式，更新后重启自动换"。 | ✅ **需要拍板** |
| **Q-U11** | **sidecar updater 的实现载体** | 用**同一套 Python 打包出一个最小 updater 可执行体**（随包分发，`_internal` 外另存），不引入新第三方库（守 R-F）；备选：Windows 批处理 + PowerShell（零依赖但不跨形态）。 | ✅ **需要拍板**（影响技术方案） |
| **Q-U12** | **安装目录不可写的兜底** | 检测到安装目录不可写（如放在 `Program Files`）→ 不尝试自动替换，改为"下载完成，请手动解压替换"并打开目标文件夹。 | 建议即可 |
| **Q-U13** | **检查频率** | 启动时检查 + 每 24h 至多一次（以 `last_checked` 为准）；手动检查不限次数。 | 建议即可 |

---

## 4. 数据结构

### 4.1 `version.json` 字段契约（版本指针，放 GitHub 仓库 `main/version.json`）

> 定位：**只做"指针"**，不含产物；权威清单与产物在 GitHub Releases。字段**向后兼容**——现有 `_valid_remote` 只强依赖 `version` + `downloads.github`，新增字段缺失时旧客户端仍可按 L1 提示。

```json
{
  "version": "2.0.0",
  "channel": "stable",
  "released_at": "2026-09-20",
  "min_compatible": "1.0.0",
  "min_updatable": "1.7.0",
  "notes": ["要点1（≤5 条，每条一句话）", "要点2"],
  "release_url": "https://github.com/<owner>/maling/releases/tag/v2.0.0",
  "downloads": {
    "github": "https://github.com/<owner>/maling/releases/download/v2.0.0/MaLing_v2.0.0_win_onedir.zip",
    "mirror": ""
  },
  "assets": {
    "onedir": {
      "url": "https://github.com/<owner>/maling/releases/download/v2.0.0/MaLing_v2.0.0_win_onedir.zip",
      "mirror": "",
      "sha256": "<64 位十六进制>",
      "size": 260200000
    },
    "single": {
      "url": "https://github.com/<owner>/maling/releases/download/v2.0.0/MaLing_v2.0.0_win_single.exe",
      "mirror": "",
      "sha256": "<64 位十六进制>",
      "size": 186600000
    }
  }
}
```

| 字段 | 必填 | 类型 | 语义 / 约束 |
|---|---|---|---|
| `version` | ✅ | str | `X.Y.Z`，可被 `core.parse_version` 解析 |
| `channel` | ✅ | str | `stable` / `beta`；与 `VERSION_JSON_URL` 频道一致 |
| `released_at` | ✅ | str | `YYYY-MM-DD` |
| `min_compatible` | ⬜ | str | 低于它 → `kind=reinstall`（沿用现有语义） |
| `min_updatable` | ⬜ | str | **新增**：低于它 → **禁止自动替换**，只能整包重装（衔接 L3） |
| `notes` | ⬜ | list[str] | ≤5 条，提示卡展示前 3 条（沿用 `format_update_text`） |
| `release_url` | ⬜ | str | Release 页面（"查看完整更新内容"用） |
| `downloads.github` | ✅ | str | **向后兼容保留**（onedir 主链），现有 `evaluate_update` 依赖它 |
| `downloads.mirror` | ⬜ | str | 备用链（onedir） |
| `assets.onedir` / `assets.single` | ⬜ | dict | `url` / `mirror` / `sha256` / `size`；缺失 → 按 Q-U5 降级 |

**URL 安全约束（R-M）**：所有 URL 必须 `https://`；拒绝 `file://`、`\\\\` UNC、相对路径、含 `..` 的路径注入；域名默认允许 `github.com` / `objects.githubusercontent.com` / `raw.githubusercontent.com` + 用户自配镜像白名单。

### 4.2 GitHub Release 侧契约

| 项 | 规范 |
|---|---|
| tag | `vX.Y.Z`（例 `v2.0.0`） |
| Release 标题 | `码铃 vX.Y.Z — <本期主题>` |
| Release 正文 | 取自 `CHANGELOG.md` 该版本条目，如实描述（R-K 精神）；附"安装 / 更新说明"与 sha256 校验值 |
| Assets | ①`MaLing_vX.Y.Z_win_onedir.zip`；②`MaLing_vX.Y.Z_win_single.exe`；③对应 `.sha256` 文本（可选但推荐） |

### 4.3 本地 `update_state.json` 扩展（`%APPDATA%/maid_coder/update_state.json`）

> 在现有文件上**增量扩字段**（F-5），旧字段语义不变；读时缺字段按默认值处理，**零迁移**。

```json
{
  "ignored_version": "1.9.0",
  "last_checked": "2026-09-10",
  "last_prompt_date": "2026-09-10",
  "channel": "stable",
  "pending_version": "2.0.0",
  "download": {
    "version": "2.0.0",
    "asset": "onedir",
    "path": "%APPDATA%/maid_coder/updates/2.0.0/MaLing_v2.0.0_win_onedir.zip",
    "received": 12345678,
    "total": 260200000,
    "url_index": 0,
    "updated_at": "2026-09-10T21:03:00"
  },
  "backup_path": "%APPDATA%/maid_coder/updates/backup/maling_1.9.0",
  "last_install": {"version": "1.9.0", "result": "success", "at": "2026-09-10T21:05:00"}
}
```

| 字段 | 语义 |
|---|---|
| `ignored_version` / `last_checked` | 沿用现有 |
| `last_prompt_date` | **新增**：同日去重用（L1-5） |
| `channel` | **新增**：当前检查频道（L1-3） |
| `pending_version` | **新增**：已下载待安装版本 |
| `download` | **新增**：续传所需的已下字节 / 总大小 / 当前链序号 |
| `backup_path` | **新增**：上一版备份位置（L3-4 回滚源） |
| `last_install` | **新增**：上次安装结果（`success` / `failed` / `rolled_back` + 时间） |

### 4.4 暂存目录结构与安装形态探测

```
%APPDATA%/maid_coder/updates/
├── 2.0.0/
│   ├── MaLing_v2.0.0_win_onedir.zip        # 完整包（校验通过）
│   ├── MaLing_v2.0.0_win_onedir.zip.part   # 未完成（续传用，Q-U4）
│   └── .verified                           # 校验通过标记（防止半包进 L3）
├── 2.0.1/ …
└── backup/
    └── maling_1.9.0/                       # 上一版备份（Q-U6）
```

**安装形态探测（L2-7）**：`sys.frozen` 为真且 `Path(sys.executable).parent / "_internal"` 存在 → **onedir**；`sys.frozen` 为真且 `sys._MEIPASS` 位于临时目录、exe 为单文件 → **onefile**；源码态（`sys.frozen` 为假）→ 走"开发模式"，**禁用自动替换**、只做检查与下载演练。

---

## 5. 界面与交互

### 5.1 入口与设置项（`page_settings.py` 关于/更新区 + `page_about.py`）

| 控件 | 行为 | 默认 |
|---|---|---|
| 当前版本 | 只读文本 `码铃 v2.0.0` | — |
| **检查更新**按钮 | 点击走 L1 链；三态反馈（有新版 / 已最新 / 失败） | 可用 |
| 更新频道 | 下拉「稳定版 / 测试版(beta)」 | 稳定版 |
| 自动检查更新 | 开关（关 = 启动不检查，手动入口仍在） | 开 |
| 自动下载更新 | 开关（开 = 后台静默下载，装前问一句；Q-U9） | 开 |
| 更新源 | 只读展示主链域名 + "使用备用链"开关 + 自定义镜像输入框 | 主链 GitHub，备用链开 |
| 清理更新缓存 | 按钮：清空 `updates/`（保留 `backup/`） | — |

### 5.2 提示卡（非阻断，沿用并扩展现有弹窗壳）

| 状态 | 文案骨架 | 按钮 |
|---|---|---|
| 发现新版（未下载） | `发现新版本 vX.Y.Z：{前 3 条要点}` | `立即下载` / `稍后` / `忽略此版本` |
| 下载中 | 进度条 + `45% · 117MB/248MB · 2.3MB/s · 剩余 1 分 12 秒` | `后台继续` / `取消` |
| 下载完成待安装 | `vX.Y.Z 已下载并校验通过，重启后启用` | `立即重启安装` / `稍后（下次退出时安装）` |
| 校验失败 | `下载文件校验未通过，已作废，将重试` | `重试` / `关闭` |
| 全部链失败 | `更新下载失败（网络原因），可稍后在设置页重试` | `重试` / `关闭` |
| 无法自动替换（Q-U12） | `已下载完成，但当前目录无法自动替换，请手动解压覆盖` | `打开文件夹` / `关闭` |

### 5.3 红线约束（UI）

- 所有更新相关提示 **非模态、可关闭、可忽略**（R-A 无焦虑延续：不反复骚扰、不阻塞聊天）。
- **不展示**"更新失败 N 次""落后 N 个版本"等数值化 / 催促语义。
- 失败态只在设置页留一句可重试提示，**绝不**在聊天区 / 首页弹错误。

---

## 6. 打包与发布流程（发版时人工步骤，越具体越好）

> 建议把下列步骤固化成 `tools/release_checklist.md`（或脚本 `tools/build_release.py`），本期只要求文档固化，不强制自动化。

1. **定版号**：确定 `X.Y.Z`；同步改 `core/__init__.py` 的 `__version__` 与 `version.json` 的 `version`。
2. **全量测试**：跑 `pytest`（基线 v1.9.0 = 858 passed / 12 skipped / 0 failed），新增更新相关用例后要求全绿。
3. **构建 onedir**：`pyinstaller maid_coder_gui.spec`（onedir 模式）→ 产物 `dist/maling/`。
4. **构建 onefile**：onefile spec → 产物 `MaLing_single.exe`。
5. **压缩 onedir**：把 `dist/maling/` 整目录压成 `MaLing_vX.Y.Z_win_onedir.zip`（注意：压缩包内需保留顶层 `maling/` 或明确解压约定，口径随命名规范 Q-U2 定）。
6. **算 sha256**：对 zip 与 exe 各算一次（Windows：`certutil -hashfile <file> SHA256`；Git 环境：`sha256sum <file>`），记下 64 位值。
7. **写 Release 说明**：从 `CHANGELOG.md` 抽该版本条目，附安装 / 更新说明与 sha256 值（不含自评分，R-K）。
8. **建 GitHub Release**：打 tag `vX.Y.Z` → New release → 粘贴说明 → 上传 zip、exe（及 `.sha256` 文本）。
9. **release 可下载性验证**：用浏览器无痕 + 国内网络各试一次下载，确认 302 到 `objects.githubusercontent.com` 可通；若不通，配置备用链并在下一步填入。
10. **更新 `version.json`**：写入新 `version` / `released_at` / `notes` / `downloads.github`（+ `mirror`）/ `assets.onedir|single` 的 `url` / `sha256` / `size`；必要时更新 `min_compatible` / `min_updatable`。commit + push 到 `main`（**这一步才让客户端"看到"新版**）。
11. **分发到小圈子**：微信群 / 朋友圈发 Release 页面链接（新用户整包下载）。
12. **端到端自测**：用上一版（如 v1.9.0）真实安装包启动 → 收到提示 → 下载 → 校验 → 安装 → 拉起 → **确认 `%APPDATA%/maid_coder` 用户数据仍在**（聊天记录 / 记忆 / 配置）→ 全流程留档。

---

## 7. Non-goals（明确不做）

1. **增量 / delta 补丁更新**：包内含 Pi 运行时，整包 248MB，二进制差分收益低、维护成本高（F-6/F-7）→ 本期只做整包替换。
2. **静默强制更新**：不做"无用户确认自动替换"。替换前必须有用户确认（Q-U9 默认）。
3. **macOS / Linux 自动更新**：本期只做 Windows（onedir + onefile）；跨平台更新列为后续候选。
4. **应用商店渠道**：不做 Microsoft Store / 应用宝 / 360 等商店上架与商店内更新。
5. **灰度 / A-B 分发**：不做按用户分桶推送不同版本。
6. **热补丁**：不做"只替换单个 Python 文件"的运行时热更新（会破坏打包一致性）。
7. **网盘链接自动下载**：网盘分享链接只作"手动兜底 + 复制链接"，不进自动下载链（Q-U3）。
8. **代码签名**：本期默认不做，但列为 **Q-U7 待拍板**而非永久 Non-goal（若拍板要做，则纳入 L3 前置校验）。

---

## 8. 铁律红线区（v2.0 = 沿用 R-A / R-D / R-F + 新增 R-M / R-N / R-O）

> 编号说明：v1.6 用 R-K、v1.9 用 R-L（字体授权），本期从 **R-M** 起，避免与既有编号冲突。

| # | 红线 | v2.0 强制口径 |
|---|---|---|
| R-A | **无焦虑红线（延续）** | 更新提示**非阻断、可忽略、可关闭**；忽略后同日不重弹、有新版本才恢复；**不展示**"更新失败 N 次""落后 N 个版本""还剩几天"等催促 / 数值化语义；任何更新状态不得在聊天区 / 首页制造打扰。更新失败只留日志 + 设置页一句可重试提示。 |
| R-D | **只增量不重构（延续）** | 在 `update_checker.py` / `update_state.json` / `main.py` 接线 / 设置页入口上**增量扩展**；**保留** `evaluate_update` / `format_update_text` / `pick_download_link` / `UpdateChecker.update_available` 信号名与语义；`version.json` 只**加字段不改旧字段**；不改 v1.9 四风格 / 字体 / 命名任何既有行为。 |
| R-F | **打包零第三方依赖（延续）** | 更新功能**不得引入新的运行时第三方库**：`requests` 为既有依赖可复用；sha256 用标准库 `hashlib`；磁盘空间用 `shutil.disk_usage`；进程拉起用 `subprocess`；断点续传用 `requests` 的 `Range` 头。sidecar updater 同样零新增依赖。 |
| **R-M** | **更新安全（新增）** | ①**只允许 `https://`**——拒绝 `http://` / `file://` / `\\\\` UNC / 相对路径 / 含 `..` 的注入；②**强制 sha256 校验**，不符即作废重下，**绝不安装未通过校验的包**；③下载域名默认锁定 GitHub 系（`github.com` / `objects.githubusercontent.com` / `raw.githubusercontent.com`）+ 用户显式自配镜像白名单；④不得为更新读取 / 写入任何用户凭证，不得回传设备信息（更新请求只读 `version.json`）。 |
| **R-N** | **更新可失败，但绝不伤主程序（新增）** | ①更新链任何环节失败**都不得影响启动 / 聊天 / 记忆 / 陪伴**——失败即静默降级 + 留日志；②换包失败必须**回滚**到上一版，保证软件始终可打开；③**绝不触碰** `%APPDATA%/maid_coder` 用户数据（换包路径对该目录零写零删）；④主进程运行期间不删除 / 覆盖任何在用文件（换包只能由退出后的 sidecar 执行）。 |
| **R-O** | **分发诚实与合规（新增）** | ①Release notes / CHANGELOG **不自评分、不夸大**（延续 R-K 精神），"已自动更新"能力必须在 dist 产物上逐项核对（sidecar 落包、sha256 可校验、回滚可用）；②分发遵守 GitHub Releases 服务条款，镜像不得声称官方；③`version.json` 与 Release 的**真实地址**必须替换占位（`your-repo` 上线前必须消除）；④代码签名若未做，文档如实说明。 |

---

## 9. 裁决记录与 PM 主张

### 9.1 本期待用户裁决项（对应 §3 加粗项）

| # | 待裁决 | PM 建议 |
|---|---|---|
| Q-U1 | GitHub 仓库名 / 公开性 | 公开仓库 `<owner>/maling`；上线前必须替换 `your-repo` 占位 |
| Q-U2 | 产物命名规范 | `MaLing_vX.Y.Z_win_onedir.zip` / `MaLing_vX.Y.Z_win_single.exe` + `.sha256` |
| Q-U3 | 备用链形式 | https 直链（对象存储 / 自有域）+ 网盘链接仅手动兜底 |
| Q-U7 | 是否代码签名 | 本期不做，如实说明；留待后续 |
| Q-U9 | 更新触发方式 | 自动检查 + 自动下载 + **手动确认安装**（不做无确认静默替换） |
| Q-U10 | 主推安装形态 | onedir 为官方主推；onefile 保留为便携模式 |
| Q-U11 | sidecar 实现载体 | 用同一套 Python 打包的最小 updater 可执行体（守 R-F） |

### 9.2 PM 对最大技术风险（Windows 换包）的主张

**风险定级：高。** Windows 下"运行中的 exe 及其所在目录无法自我覆盖 / 删除"是硬约束（F-8），因此**"码铃自己替换自己"在原理上不可能**，必须引入**安装目录之外的 sidecar updater**。我的主张（供架构细化）：

1. **sidecar 必须"生于安装目录之外"**：updater 可执行体应落 `%APPDATA%/maid_coder/updates/`（或 `%TEMP%`）并在那里运行，否则它自己也会被换包操作锁住 / 删掉。这是整个方案成立的前提，架构必须先钉死这一点。
2. **换包策略分形态**：onedir 用"**整目录 rename-swap**"——`maling/` → `maling.bak/`（rename 是元数据操作，快且可回滚）→ 新目录就位 → 拉起新 exe；失败则 `rename` 回来。onefile 用"**运行中 exe 可改名**"特性——旧 exe → `.old`，写入新 exe，拉起。两种策略都要保证"要么全新、要么全旧"，**不允许出现半成品目录**。
3. **可回滚优先于可更新**：先保住"永远能打开软件"，再谈"更新成功"。`backup_path` + `last_install` 全落 `update_state.json`，新版拉起失败即回滚（L3-4 / L3-6）。
4. **默认不做无确认静默替换**（Q-U9）：全自动换包一旦回滚逻辑有漏洞就是"软件打不开"级事故；"下载自动、安装确认、退出时换"是最稳的折中。
5. **必须真机端到端验证**：mock 测不出文件锁与杀软占用。建议架构/QA 用**真实 v1.9.0 安装包 → 真机更新 → 重启**的流程留档（§6 第 12 步），并额外覆盖两种形态、断网续传、校验失败、目录不可写四种异常路径。

---

## 10. DoD 摘要（v2.0 完成标准）

1. **L1 立住**：启动静默检查（沿用）+ 手动入口三态 + 频道切换 + `version.json` 指针契约 + 提示节奏（忽略同日不重弹）全部可断言。
2. **L2 立住**：进度 UI + 断点续传（Range）+ 重试降级 + sha256 校验 + 暂存隔离 + 空间预检 + 形态自适应，弱网可续、错包作废。
3. **L3 立住**：sidecar 换包（onedir 整目录 swap / onefile 改名换 exe）+ 备份回滚 + 用户数据零触碰 + 失败静默降级；真机端到端更新留档。
4. **红线归零**：R-A / R-D / R-F / R-M / R-N / R-O 全条对照；更新链零新第三方依赖；`%APPDATA%/maid_coder` 换包前后零变化。
5. **零回归 + 打包**：v1.9.0 全量功能（四风格 / 字体 / 命名 / 记忆 / 群聊 / Pi）无回归；py_compile + pytest 双绿；sidecar 落包、sha256 可校验、回滚可用在 dist 上逐项核对留档。

---

> 文档结束。许清楚 · 2026-09-10 · v2.0a 草案——用户已拍板「GitHub Releases 托管 + 小圈子分发」不再抛回；Q-U1/Q-U2/Q-U3/Q-U7/Q-U9/Q-U10/Q-U11 为待拍板项，收敛后移交架构评估。最大技术风险 = Windows 换包（sidecar updater），主张见 §9.2。
