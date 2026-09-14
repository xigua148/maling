# 码铃（MaLing）v2.0 增量架构设计 ——「自动更新与分发：把半手动升级为软件级自动更新」

- 版本：v2.0（增量设计，格式对齐 design-v16 / v17 / v18 / v19）
- 文档状态：定稿（Q-U1/U2/U3/U4/U5/U6/U7/U8/U9/U10/U11/U12/U13 全部由用户拍板 + PM 建议收口，本文标「Q-Ux 裁决」）
- 维护人：高见远（架构）
- 关联文档：`docs/prd-v20.md`（需求源，v2.0a / 2026-09-10）+ `docs/design-v19.md`（格式基准）+ `docs/design-v18.md`（分层与共享知识基线）+ `AGENTS.md`（L0–L2 分层纪律）+ `README.md`（打包章节）+ `CHANGELOG.md`
- **基线：v1.9.0**（`version.json.version = 1.9.0`；双产物 onedir `dist_v190f/maling/` + onefile `MaLing_single.exe`）
- 设计纪律重申：**功能面零改动**（聊天 / 记忆 / 陪伴 / 群聊 / Pi 引擎零触碰）；`gui/update_checker.py` 既有契约（`evaluate_update` / `format_update_text` / `pick_download_link` / `update_available` 信号名与语义、旧字段语义）**零变更**；更新链**零新增运行时第三方依赖**（守 R-F）；不重做 v1.9 四风格 / 字体 / 命名任何已定内容；工作副本仅限 `maling_agent_dev/`，**严禁触碰 `D:/【开发中版本】/maling_v1.0.0_src/`**。

---

## 1. 范围与现状基线（先读我）

### 1.1 三块范围

| 块 | 内容 | 主要落点 | 是否可复用现状 |
|---|---|---|---|
| **L1 检查更新** | 静默检查（沿用）+ 手动入口三态 + 频道 stable/beta + `version.json` 指针契约 + 提示节奏（忽略同日不重弹） | `gui/update_checker.py`（增量）+ `gui/config.py` + `gui/pages/page_settings.py` + `page_about.py` + `gui/main.py` | **高复用**：`_FetchWorker` / `evaluate_update` / `format_update_text` / `pick_download_link` / `load_update_state` / `save_ignored_version` 全部保留 |
| **L2 下载更新** | 进度 UI + 断点续传（Range）+ 重试降级链 + sha256 校验 + 暂存隔离 + 空间预检 + 形态自适应 | 新 `gui/update_downloader.py` + 进度组件 + 暂存目录 | **中复用**：`QThread` 进程模型与 `_FetchWorker` 同款；`requests` 既有依赖；校验/空间/落盘全标准库 |
| **L3 自动替换 + 重启** | sidecar 换包（onedir 整目录 rename-swap / onefile 改名换 exe）+ 备份回滚 + 用户数据零触碰 + 失败静默降级 | 新 `maling_updater.py`（sidecar 主体）+ `updater.spec` + `gui/main.py` 退出编排 + 启动自检 | **全新增**（现状零基础，最大风险区） |

Non-goals（PRD §7 全承接）：增量/delta 补丁、无确认静默替换、macOS/Linux 自动更新、应用商店渠道、灰度 A/B、热补丁、网盘链接自动下载、代码签名（Q-U7 = 本期不做）。

### 1.2 现状校正（⚠ 标红：PRD 表述与源码不符处，**按本文执行**）

| # | PRD 表述 | 源码事实（已逐行核） | 本文裁决 |
|---|---|---|---|
| ⚠-1 | §4.3 示例：`backup_path = %APPDATA%/maid_coder/updates/backup/maling_1.9.0` | Windows `rename()` 是**同卷**元数据操作，跨卷会退化为复制+删除（无原子性，且 536MB 慢）。备份必须是"旧安装目录的改名结果"，**只能落在安装目录同卷** | 备份落点改为 **安装目录父目录**（`<install_parent>/.maling_backup_<ver>/`）；`backup_path` 记录真实值（可在 C:\ 或 D:\），**不再假设在 `%APPDATA%` 下**。D-V20-02 / §4.2 |
| ⚠-2 | §4.4 图示：新包解压/暂存均在 `%APPDATA%/maid_coder/updates/<ver>/` | 同上，**解压产物必须与安装目录同卷**才能 rename 就位；`%APPDATA%`（通常 C:）与安装目录（用户可能放 D:）不一定同卷 | 下载 zip 存 `%APPDATA%/.../updates/<ver>/`（缓存域）；**解压/就位目录落 `<install_parent>/.maling_new_<ver>/`**（安装卷），由 sidecar 执行。D-V20-02 |
| ⚠-3 | §4.3「L3-5：换包前后 `%APPDATA%/maid_coder` 文件清单零变化（除 `update_state.json` 本身）」 | `updates/` 下载缓存、`updater/` sidecar 运行时**都在 `%APPDATA%/maid_coder` 下**，下载/换包必然改变这些文件 —— 字面口径自相矛盾 | **R-N 禁区精确定义**：禁区 = **用户数据域**（会话 / 记忆 / persona / `gui_config.json` / 知识库 / 待办 / 日记 / 提醒 …），**排除更新子系统自有子树** `update_state.json` + `updates/**` + `updater/**`。验收扫描按白名单三键放行。§9 R-N |
| ⚠-4 | §4.4 假设 sidecar 可落 `updates/` 下 | Q-U6 设置页「清理更新缓存」= 清空 `updates/`。sidecar 若在其中，**会被自己的清理按钮删掉** | sidecar 落 **`%APPDATA%/maid_coder/updater/`**（`updates/` 的**兄弟目录**，不在清理范围）。D-V20-01 / D-V20-08 |
| ⚠-5 | §4.1 示例 `downloads.github` 为必填且 `_valid_remote` 依赖它 | 现存 `version.json` 的 `downloads` 为 **空对象 `{}`**（未发布占位）→ 现网一旦托管此文件，`_valid_remote` 恒返回 `None`，客户端**永不提示** | 发布前**必须**填 `downloads.github`（≥1 个真实 URL），否则 L1 全链失效。这是发版第 9 步的硬闸（§7）。属"填值"非"改语义"，不违 R-D |
| ⚠-6 | §1.1 F-1「`gui/main.py:908-915` 接线」 | 实为 **:908-915** 检查接线（对）+ **:740-767** 提示弹窗（对）+ **:725 `aboutToQuit` → `_quit_stop_services`（:631）** 退出编排（PRD 未列） | 拉 sidecar 的唯一插入点 = `_quit_stop_services` **末步之后**、`aboutToQuit` 回调内；顺序契约不动。D-V20-09 |
| ⚠-7 | PRD 通篇假设「运行中的 exe 可改名」成立 | macOS 无此特性、Linux 无此约束；本期仅 Windows（Non-goal 3 已限定），但**代码必须形态/平台守卫**，非 Windows 一律 `dev` 模式禁用替换 | `detect_install_form()` 先判 `os.name == "nt"`，否则返回 `"dev"`。D-V20-06 |
| ⚠-8 | §9.2「sidecar 由主进程退出后执行」 | Pi 引擎在 `_internal/pi_runtime/` 下会 spawn `node.exe` 子进程；`chat_service.shutdown()`（:2112）**只停 ApiWorker，不停 Pi RPC 子进程**（`PiRpcSession.stop()` 仅在任务 finally 内自调） | **换包前置硬闸**：sidecar 就位前必须**排空安装目录内的残留进程**（枚举 image path 在 `install_dir` 下的进程 → 等待 → 超时强杀）。这是最容易翻车的一处。D-V20-02 / 风险 §8.4 |
| ⚠-9 | §1.1 F-3「`min_compatible` → `kind=reinstall`」语义 | 确认：`evaluate_update`（:122-135）本地 < `min_compatible` → `kind="reinstall"` | 新增 `min_updatable` 与之**正交**：`min_compatible` 管"提示话术"，`min_updatable` 管"是否允许自动替换"。二者独立判定，互不覆盖。D-V20-02 / §4.1 |
| ⚠-10 | 隐含「两个 spec 等价，改一个即可」 | `maid_coder_gui_onefile.spec`（改于 16:47）**缺** v1.9 的 `('gui/assets/fonts','assets/fonts')` datas 与 `'gui.fonts'` hiddenimport（onedir spec 改于 19:15 已含）→ onefile 目前**打进去也没有字体**，会静默回退雅黑 | onefile spec **必须补**字体 datas + hiddenimports（v1.9 遗留缺口，本期随 V20-14 spec 收口一并修，属修 bug 非新功能）；§3.2 明确列出 |

### 1.3 已核实的关键对接点（v1.9.0）

| 对接点 | 位置 | v2.0 用途 |
|---|---|---|
| `VERSION_JSON_URL` 占位常量 / `CHECK_TIMEOUT_SECONDS=5` | `update_checker.py:37 / :40` | L1-3 升级为**频道表**（保留常量名做 stable 别名，R-D） |
| `load_update_state()` / `save_ignored_version()` / `_update_state_path()` | `update_checker.py:49 / :62 / :43` | 增量扩字段；新增通用 `save_update_state(dict)`（读-改-写单一入口） |
| `_valid_remote()`（强依赖 `version` + `downloads.github`） | `update_checker.py:77-96` | 保留；新字段（`assets`/`min_updatable`）**不参与**合法性判定 → 旧式 `version.json` 零破坏（L1-4 验收） |
| `evaluate_update()` 返回 `{kind,version,notes,primary,mirror}` | `update_checker.py:99-145` | **签名与返回键零变更**；`primary` 继续取 `downloads.github`（旧语义），新链资产走 `assets`（新函数读取） |
| `_FetchWorker(QThread)`（fetched/failed 信号） | `update_checker.py:148-173` | L2 下载器**同款进程模型**（QThread + 信号），不引入新线程框架 |
| `UpdateChecker.update_available = Signal(dict)` | `update_checker.py:186` | **信号名与 payload 契约零变更** |
| `format_update_text()` / `pick_download_link()` | `update_checker.py:212 / :224` | 保留；新增下载/安装态文案走**新纯函数**，不复用改签名 |
| `_show_update_prompt()` 非阻断弹窗（copy/ignore 两键） | `main.py:740-767` | 扩为四态提示卡（发现/下载中/待安装/失败），壳沿用 `QMessageBox.show()` + `setModal(False)` |
| 检查接线（`main()` 末段 `checker.start()`） | `main.py:908-915` | 追加：频道读取、24h 节奏闸、自动下载触发 |
| `_quit_stop_services()`（v1.6.1 完整退出序列） | `main.py:631-696` | **末步之后**追加"启动 sidecar"（唯一插入点）；其内部顺序零变更 |
| `aboutToQuit` 连接 | `main.py:725` | sidecar 在 aboutToQuit 内拉起（此时服务已停、UI 已拆，主进程即将退出） |
| `get_user_data_dir()` = `%APPDATA%/maid_coder` | `gui/utils.py:21-29` | 暂存/状态/sidecar 运行时根；**不改函数**（R-D） |
| `get_resource_path()`（frozen 以 `_MEIPASS` 为基准） | `gui/utils.py:12-18` | 主包内嵌 updater exe 的取径方式（`assets/updater/maling_updater.exe`） |
| `GuiConfig.load/save` 的 `hasattr` 白名单落盘 | `gui/config.py:107-203` | 四个新键（`update_channel` 等）照此注册；老存档缺键自动取默认（零迁移） |
| 设置页 `_create_section` + 保存链 `cfg.save()` | `page_settings.py:691 / :1730` | 新增「更新」区；复用既有 section/save 机制 |
| `PageAbout` 版本卡 + 开源组件表 | `page_about.py:50-93` | 手动「检查更新」入口 + 当前版本 + 更新源展示位 |
| onedir spec：datas/hiddenimports/EXE/COLLECT | `maid_coder_gui.spec` | 追加内嵌 updater datas + `gui.update_downloader` hiddenimport |
| onefile spec：单 EXE（含 binaries/datas） | `maid_coder_gui_onefile.spec` | 追加内嵌 updater datas + 字体缺口修复（⚠-10） |
| `version.py.get_version()` → `core.__version__` | `version.py:35` / `core/__init__.py:126-130` | 本地版本单一来源，禁止硬编码版本字符串 |
| `pack_release_v190.py`（zip + `\\?\` 长路径） | `tools/pack_release_v190.py` | 发版脚本升级版 `build_release.py` 的前身（本期允许文档固化，脚本可选） |
| `parse_version` / `is_newer_version`（数值元组） | `core/__init__.py:92 / :104` | 全部版本比较唯一入口，**禁止字符串比较** |

---

## 2. 架构决策（D-V20-01 ~ D-V20-15）

> 每条格式：**决策** / **理由** / **被否决的替代方案**。D-V20-01~04 为高危区，全文最细。

### D-V20-01 sidecar 生存性：updater 必须"生于安装目录之外"且"活过清理按钮"

**决策**

| 项 | 定案 |
|---|---|
| 落点 | `%APPDATA%/maid_coder/updater/`（`updates/` 的**兄弟目录**） |
| 兜底落点 | `%TEMP%/maling_updater_<pid>/`（仅当 `updater/` 不可写且 `%TEMP%` 与安装目录**同卷**可用；否则放弃自动替换） |
| 文件名 | `maling_updater.exe`（onefile，PyInstaller `console=False`，零第三方依赖） |
| 运行时 cwd | `%APPDATA%/maid_coder/updater/`（**不是**安装目录） |
| 拉起方式 | `subprocess.Popen([updater_exe, "--pid", str(os.getpid()), "--plan", plan_path, "--log", log_path], cwd=updater_dir, close_fds=True, stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL, creationflags=DETACHED_PROCESS \| CREATE_NO_WINDOW)` |
| 命令行契约 | `--pid <主进程 PID>`（必填）/ `--plan <plan.json 绝对路径>`（必填）/ `--log <日志路径>`（必填）/ `--version`（打印自身版本后退出）。**无参数或不识别参数 → 退出码 2，绝不交互式运行** |
| 自我保护 | 启动时自检 `sys.executable` 不在任何 `install_dir` 前缀下；若在 → 只记日志并退出 3（不换包） |

**理由**

1. **为什么不在安装目录内**：onedir 换包要 `rename(install_dir)` 整目录，若 updater 在目录内，它会**成为被 rename / 删除的对象**，自己把自己锁死；且主进程运行时其 exe 的句柄被占用，目录 rename 直接 `WinError 32`。这是 PRD §9.2 主张 1 的代码级落定。
2. **为什么不用 `updates/` 目录**：Q-U6 的「清理更新缓存」清空 `updates/`（保留 `backup/`），sidecar 放里面会被用户一键清理掉，下一次更新就找不到执行体。故放 `updater/` 兄弟目录，且清理按钮**不触碰** `updater/`（§5.1 设置页口径）。
3. **为什么 `DETACHED_PROCESS`**：主进程退出后 sidecar 必须继续存活，不能随父进程控制台/作业对象收尾。`CREATE_NO_WINDOW` 对 `console=False` 的 GUI exe 无实际作用，作为防御性冗余；两标志可并用。`close_fds=True` 防句柄继承导致旧进程退出时**间接占用安装目录文件**（关键：否则 sidecar 继承的句柄会让 rename 失败）。
4. **"如何知道自己被调用"**：唯一定义为 argv 契约，无参数即拒绝运行；sidecar 不读 GUI 配置、不依赖 cwd 猜测，plan.json 是**唯一输入源**（可复现、可人工重放排障）。
5. **自检断言（L3-1 验收）**：`os.path.commonpath([sys.executable, install_dir]) != install_dir`。

**被否决的替代方案**

- ❌ **主进程内 `os.execv` 自我重启**：无法在自身运行时覆盖自身目录，原理上不可行（F-8）。
- ❌ **批处理 + PowerShell 脚本（Q-U11 备选）**：零依赖但无法跨 onedir/onefile 统一、无结构化日志、无法做 sha 复核与回滚判定，且杀软对 `.bat` 改名 exe 行为敏感。
- ❌ **落 `updates/`**：被「清理更新缓存」删除（见上，⚠-4）。
- ❌ **落安装目录同卷的隐藏目录**：换包后新版本不会重新播种旧路径，且污染用户可见目录；`%APPDATA%` 更干净。

---

### D-V20-02 onedir rename-swap：原子边界 + 同卷 + 残留进程排空

**决策**（sidecar 内固定 7 步，任一步失败 → 回滚路径）

```
① 前置校验：plan 合法 / target_version > from_version / 解压产物完整（含 version.json + maling.exe）
② 就位准备：zip 解压到 <install_parent>/.maling_new_<ver>/（同卷！）
③ 进程排空：枚举 image path 在 install_dir 下的进程 → 等待至多 kill_timeout → 超时 TerminateProcess
④ rename(install_dir, <install_parent>/.maling_backup_<from_ver>/)      # 原子边界，旧目录"瞬间"让位
⑤ rename(<install_parent>/.maling_new_<ver>/, install_dir)              # 新目录就位
⑥ 拉起 install_dir/maling.exe（新进程），进入 D-V20-04 待确认判定
⑦ 判定成功 → 写 last_result.json；判定失败 → 回滚（⑧）
⑧ 回滚：kill 新版进程 → rename(install_dir, <install_parent>/.maling_new_failed_<ver>/) → rename(.maling_backup_<from_ver>/ , install_dir) → 重新拉起旧版
```

**为什么"先 rename 再 move"而不是"直接覆盖"**

| 维度 | 先 rename 再 move（采纳） | 直接覆盖（否决） |
|---|---|---|
| 原子性 | rename 是**同卷元数据操作**，安装目录要么是"全旧"要么是"全新"，不存在中间态 | 逐文件复制/删除会长时间处于"半新半旧"目录，**无法判定版本**，也无法回滚 |
| 可回滚 | 旧目录被完整改名保留 = 天然备份，回滚=再一次 rename | 需预先整目录复制备份（536MB 双写，慢且可能中途失败） |
| 运行保证 | 换包前旧 exe 已退出（③），新目录就位后拉起，全程"总有一个可运行的目录" | 覆盖过程中旧 exe 已不可运行、新版未就位 → **可能打不开软件**（违 R-N②） |
| 验收断言 | "不允许出现两个半成品目录"= 同时存在的目录集合只允许 `{install_dir, 一个 .bak}` | 无法给出该断言 |

**为什么必须同卷**：`os.rename` 跨卷会抛 `OSError(EXDEV)`；即使 Python `shutil.move` 兜底为复制+删除，也失去原子性与速度。故 ② 的解压目标**必须是 `install_dir.parent` 下的隐藏目录**，不能是 `%APPDATA%`（⚠-2）。

**为什么必须排空残留进程（③，⚠-8）**：`_internal/pi_runtime/node.exe` 若仍存活，会持有 `node.exe`/`.dll` 句柄，④ 的目录 rename 直接 `WinError 5/32`。`chat_service.shutdown()` 只停 ApiWorker，Pi 子进程需在退出编排显式 stop（D-V20-09 时序）**且** sidecar 三重保险：等待 → 再等待 → `TerminateProcess`。进程枚举用标准库：`ctypes` + `CreateToolhelp32Snapshot` / `Process32*` + `QueryFullProcessImageNameW`（零第三方依赖，守 R-F）。

**失败必回滚的场景**：④ 失败（目录被占用/权限）→ 无需回滚（旧目录仍在原位）；
⑤ 失败（极罕见）→ rename 旧目录回来；⑥ 新版拉不起 → 走 ⑧。

**被否决的替代方案**

- ❌ **就地覆盖 + 文件级 diff（增量）**：PRD Non-goal 1 已排除（248MB 整包，二进制差分收益低）。
- ❌ **先复制旧目录做备份再覆盖**：双写 536MB，弱机耗时且中途失败更危险。
- ❌ **用 junction / symlink 指向版本目录**：Windows 用户无 symlink 权限，且杀软/备份软件对 junction 敏感，2026 用户环境不普适。

---

### D-V20-03 onefile 换法：利用"运行中 exe 可改名"

**决策**

```
① rename(<current_exe>, <current_exe>.old)        # 运行中 exe 可改名（Windows 特性，F-8）
② copy(<staging>/MaLing_v<ver>_win_single.exe, <current_exe>)   # 写回原路径（路径不变）
③ 拉起 <current_exe>（同一路径，内容已换）→ 进入 D-V20-04 判定
④ 判定成功 → 下一次启动时删除 <current_exe>.old；判定失败 → kill 新版 → rename(.old 回原路径) → 拉起旧版
```

**要点**

1. **主进程必须先退出**：`current_exe` 只有当主进程**完全退出**（句柄释放）后才可写入；sidecar 用 D-V20-01 的 pid 等待（`OpenProcess(SYNCHRONIZE)` + `WaitForSingleObject`）确保。改名 ① 虽可在运行中做，但**整体时序仍以主进程退出为起点**，避免"写入新 exe 时旧进程仍在读 `_MEIPASS` 解压残留"。
2. **`sys.executable` 在 onefile 下指向真实 exe 路径**（不是 `_MEIxxxxx` 临时目录），故 `current_exe = sys.executable` 可直接作为换包目标；sidecar 由主进程在 plan 中显式传入该绝对路径（不靠 sidecar 自己推断）。
3. **`.old` 清理时机**：新版**成功启动并写 confirmed** 后，由新版主进程在启动早期（UI 就绪前）尝试删除同目录 `.old`；失败（仍被占用/杀软扫描）忽略，留待下次。
4. **占用兜底**：若 ② 写入被拒绝（杀软实时扫描 / 索引服务短暂占用），sidecar 做**有限次指数退避重试**（如 3 次：1s/3s/7s），仍失败 → 进入回滚路径（保持旧 `.old` 改名回位），**不崩溃、不丢文件**。

**被否决的替代方案**

- ❌ **onefile 走 onedir 的整目录 swap**：onefile 没有独立目录，`sys._MEIPASS` 是临时解压目录，不起作用。
- ❌ **改名后再让用户手动重启**：违反"退出时换好、重开即新版"的 v2.0 主张（Q-U9 仍是自动安装，只是确认点在前）。

---

### D-V20-04 回滚优先：三重判定（就绪标记 + 存活探测 + 超时兜底）

**决策**——sidecar 拉起新版后，用**三信号联合**判定"安装成功"，任一失败即回滚：

| 信号 | 机制 | 判定 |
|---|---|---|
| **① 就绪标记（主判据）** | 新版主进程在 `window.show()` 之后、事件循环正常运行（一次 `QTimer.singleShot(0, …)` 回调触发）时，写 `%APPDATA%/maid_coder/updater/confirmed.json` = `{"version": "<new>", "pid": <new_pid>, "at": "..."}` | 在 `confirm_timeout_sec`（默认 **45s**）内出现 → 成功 |
| **② 存活探测** | sidecar 用 `OpenProcess(SYNCHRONIZE)` + `WaitForSingleObject(handle, 0)` 轮询新版 pid | 新版进程**在 confirmed 出现前就退出** → 立即判定失败（快速失败，不等满 45s） |
| **③ 超时兜底** | 超过 `confirm_timeout_sec` 仍无 confirmed | 失败（**fail-safe 默认回滚**，宁旧勿坏） |

**判定成功后**：sidecar 写 `updater/last_result.json = {"version","result":"success","at","from_version","backup_path"}`；按 D-V20-13 决定是否清理更早备份。
**判定失败后**：kill 新版进程 → 回滚（D-V20-02 ⑧ / D-V20-03 ④）→ 拉起旧版 → 写 `last_result.json = {"result":"rolled_back", ...}`。
**下次启动消费**：新版（或回滚后的旧版）主进程启动早期读 `last_result.json`，把它合并进 `update_state.json.last_install` 并**删除** result 文件（幂等）。主进程**从不直接写 swap 结果**，避免与 sidecar 争写。

**为什么选"就绪标记"为主判据（而非只看 exit code）**

| 方案 | 问题 | 结论 |
|---|---|---|
| 仅看子进程 exit code | GUI 应用"启动成功"与"进程存活"不等价：窗口没起来也可能不退出（消息泵空转）；反之正常退出也可能是用户立刻关窗 | 不足 |
| 仅看进程存活 N 秒 | "活着但白屏/报错弹窗"会被误判成功，回滚失效 | 不足 |
| **就绪标记（新版主动举手）+ 存活探测（快速失败）+ 超时（兜底）** | 新版在最接近"用户真的能用"的时点（窗口已显示、事件循环已跑）主动确认；任何崩溃都能被存活探测秒级捕获；最坏情况超时兜底为回滚 | **采纳** |

**防误判要点**：`confirmed.json` 必须带 `version` 与 `pid`，sidecar 校验二者与本次 plan 一致才认账（防上一轮残留/伪造）；只有**换包后新版**才会在 plan 指定的一次性路径写它（路径含 `from_version`+时间戳）。

**被否决的替代方案**

- ❌ **无标记、只靠"下次启动读版本号"**：无法区分"新版装好但用户没重启"与"新版起不来"，回滚无处触发。
- ❌ **注册表/计划任务做健康探针**：引入系统级副作用，违反"更新链零副作用、删得干净"的定位与 R-N。

---

### D-V20-05 下载器进程模型：QThread + 纯函数核

**决策**

- 进程/线程模型：**沿用 `QThread`**（与 `_FetchWorker` 同构），不引入独立进程、不引入线程池。
  - `DownloadWorker(QThread)`（新，`gui/update_downloader.py`）信号契约：
    - `progress = Signal(int, int)`（received, total；total≤0 表示未知长度，UI 显示已下字节）
    - `finished = Signal(str)`（校验通过的成品绝对路径）
    - `failed = Signal(str)`（错误码/原因文本，供日志与提示卡）
    - `cancelled = Signal()`
  - 取消：`request_cancel()` 置 `threading.Event`，worker 主循环每读一块检查；取消后**保留 `.part`**（Q-U4 裁决）并 emit `cancelled`。
- 纯函数核（可 pytest 直接断言，不碰网络）：
  - `build_url_list(assets: dict, asset_kind: str, use_mirror: bool, extra_hosts) -> list[str]`（主链 + 备用链，过滤 R-M 非法 URL）
  - `disk_precheck(staging_dir, install_parent, size) -> (bool, str)`（见 D-V20-12）
  - `resume_offset(part_path) -> int`（`.part` 当前字节数）
  - `should_restart_when_200(part_exists) -> bool`
  - `progress_text(received, total, elapsed_sec) -> str`（`percent · 已下/总量 · 速度 · 剩余`，R-A 禁用"失败 N 次"类语义）
  - `verify_sha256(path, expected, chunk=1MB) -> bool`（流式，标准库 `hashlib`）
  - `is_allowed_url(url, extra_hosts) -> bool`（R-M 白名单，单一收口）
- **Range 与 `.part` 的关系**（唯一真相源 = `.part` 文件大小）：
  1. 开始下载：`offset = resume_offset(part_path)`；
  2. `offset > 0` 且服务端支持续传 → 请求头 `Range: bytes=<offset>-`；
  3. 返回 **206** → 以 `ab` 模式追加，`received` 从 `offset` 继续累计；
  4. 返回 **200**（服务端不支持）→ **截断重建 `.part`**（`wb`），`received` 归 0，避免重复字节（L2-2 验收③：`.part` 大小 == received）；
  5. 完成 → 关闭 `.part` → `os.replace(part, final)` → `verify_sha256(final, expected)`；
  6. 校验失败 → 删除 `final`（**绝不进入 L3**），emit `failed("sha256_mismatch")`；
  7. 校验通过 → 写 `.verified` 标记 + 更新 `update_state.json.download`（received=total, verified=true）。
- 降级链：单链内**有限重试**（默认 3 次，退避 1s/3s/7s），链失败 → 换下一链并**续传**（`url_index` 递增落 `update_state.json`）；全链失败 → `failed("all_links_failed")` 且**保留 `.part`**。

**被否决的替代方案**

- ❌ **独立下载进程**：无必要（不涉及跨进程文件锁），且引入 IPC 复杂度；`_FetchWorker` 先例已证明 QThread 足够。
- ❌ **`urllib` 替代 `requests`**：`requests` 已是既有依赖（R-F 允许复用），重写无收益且易漏超时/重定向处理。
- ❌ **内存缓冲整包（248MB）**：吃内存且中断即全丢，违背续传目标。

---

### D-V20-06 形态探测：`sys.frozen` + `_internal` + `_MEIPASS` 三判据

**决策**——纯函数 `detect_install_form() -> "onedir" | "onefile" | "dev"`：

```
if os.name != "nt":                                   → "dev"（⚠-7）
if not getattr(sys, "frozen", False):                 → "dev"（源码态）
exe_dir = Path(sys.executable).resolve().parent
if (exe_dir / "_internal").is_dir():                  → "onedir"
elif getattr(sys, "_MEIPASS", None) and Path(sys._MEIPASS) != exe_dir:  → "onefile"
else:                                                 → "onefile"（保守：frozen 且非 onedir 即按 onefile）
```

- 同时返回 `install_dir`（onedir = `exe_dir`；onefile = `exe_dir`；dev = 项目根，仅用于展示）。
- **dev 模式行为**：允许 L1 检查 + L2 下载（演练/自测），**禁用 L3 自动替换**（设置页与提示卡文案明确"开发模式，不自动替换"）。
- 探测失败/异常 → 默认按 `onedir` 处理并留 info 日志（L2-7 验收②）。

**被否决的替代方案**

- ❌ **只判 `sys._MEIPASS` 是否存在**：onefile 下 `_MEIPASS` 也存在（临时目录），会误判为 onedir。
- ❌ **读 exe 大小/文件数猜形态**：脆弱且与打包配置耦合。

---

### D-V20-07 频道与 URL 表：owner 单一常量 + stable/beta 双指针

**决策**

```python
# gui/update_checker.py（保留区，R-D：常量名不变，取值来源升级）
GITHUB_OWNER = "<owner>"          # TODO(上线前必填): 用户 GitHub 用户名（Q-U1 待用户提供）
GITHUB_REPO = "maling"
CHANNEL_STABLE, CHANNEL_BETA = "stable", "beta"

VERSION_JSON_URLS = {
    "stable": f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/main/version.json",
    "beta":   f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/main/beta/version.json",
}
VERSION_JSON_URL = VERSION_JSON_URLS["stable"]   # 向后兼容别名（旧签名默认值仍可用）

def resolve_channel_url(channel: str) -> str:     # 非法值 → "stable"（L1-3 验收②）
    return VERSION_JSON_URLS.get((channel or "").strip().lower(), VERSION_JSON_URLS["stable"])
```

- **owner 单一常量**：`GITHUB_OWNER` 一处可改；`GITHUB_REPO` 默认 `maling`。上线前 `your-repo` 占位**必须消除**（R-O③，发版硬闸 §7 第 9 步）。
- **频道归属**：`GuiConfig.update_channel` 是**唯一用户真值源**（设置页读写），默认 `"stable"`；每次检查时把生效频道**镜像**写入 `update_state.json.channel`（满足 L1-3 验收③"跨重启保持" + PRD §4.3 要求落状态文件）。读取优先级：`GuiConfig.update_channel` > `update_state.channel` > `"stable"`。
- beta 复用同一套机制，**只换 URL**（Q-U8）；beta 的 `version.json` 放在仓库 `main/beta/version.json`（同仓库不同路径，不新建仓库）。
- `UpdateChecker.__init__(url=...)` 默认参数改为 `url: str = ""`（空=按频道解析），**保留可显式传 URL 的旧用法**（测试/回归兼容）。

**被否决的替代方案**

- ❌ **两个仓库/两个常量分散写死**：违背"一处可改"，易漏改。
- ❌ **频道只存 `update_state.json` 不存 GuiConfig**：用户可见设置项应在配置域（`gui_config.json`），状态文件是行为审计，二者职责不同（⚠-3 精神）。

---

### D-V20-08 updater 打包与自举：内嵌主包 → 启动复制到 `%APPDATA%/updater/`

**决策**

| 项 | 定案 |
|---|---|
| spec | 新增 `updater.spec`（onefile，`console=False`，`name='maling_updater'`，`icon='gui/assets/maling.ico'`，`upx=False`） |
| 入口 | `maling_updater.py`（项目根，纯标准库 + 仅 `ctypes`/`os`/`shutil`/`subprocess`/`json`/`hashlib`/`time`/`logging`） |
| 产物 | `dist_updater/maling_updater.exe`（目标 ≈10–15MB，无 Qt/无 requests） |
| 分发方式 | **内嵌进主包**：onedir 放到 `_internal/updater/maling_updater.exe`（spec datas 目标 `updater`）；onefile 作为 data 打进 exe（运行时经 `_MEIPASS/updater/…` 取） |
| 自举 | 主进程启动早期（`GuiConfig.load()` 之后、`MainWindow` 之前）检查 `%APPDATA%/maid_coder/updater/maling_updater.exe` 是否与内嵌副本**大小+sha 一致**，不一致则复制覆盖（幂等；失败仅记日志不阻断） |
| 与换包的关系 | onedir 换包 replace 的是**安装目录**，`%APPDATA%/updater/` 不在其中 → **sidecar 天然不受影响**；新版启动后重新自举（可能更新 sidecar 自身） |
| 版本一致性 | sidecar `--version` 打印自身版本；主进程 bootstrapping 时若发现 `%APPDATA%` 副本版本低于内嵌副本则覆盖（升级路径） |

**理由**：① 随包分发、离线可用、无额外下载；② 与将要使用它的版本强绑定，避免 sidecar 与客户端协议漂移；③ 落在用户数据域，绕开"运行中目录不可覆盖"与"清理缓存"两坑，与 D-V20-01 呼应；④ 守 R-F（sidecar 不 import requests/PySide6）。

**被否决的替代方案**

- ❌ **sidecar 作为独立 Release asset 更新时下载**：多一次网络依赖，弱网下"包下好了但换包器下不来"更糟。
- ❌ **sidecar 直接随包放安装目录并在原地运行**：违反 D-V20-01（自我锁死）。
- ❌ **用主 exe 加 `--update` 子命令复用同一可执行体**：主 exe 250MB+，启动慢，且主 exe 自身就是被替换对象，仍无法在运行时覆盖自己。

---

### D-V20-09 安装编排时序：自动检查 + 自动下载 + **手动确认安装** + 退出时换包（Q-U9 裁决）

**决策**——主进程内的完整时序（全部 try/except 包裹，任一步失败即静默降级）：

```
启动 → (auto_check 开) 24h 节奏闸过 → UpdateChecker.start() 异步检查
   ├─ 有新版本
   │    ├─ 提示卡「立即下载 / 稍后 / 忽略此版本」
   │    ├─ 用户点立即下载 或 (auto_download 开) 自动开始 → DownloadWorker（后台，进度卡）
   │    ├─ 下载+校验通过 → 写 update_state.pending_version + download.verified=true
   │    └─ 提示卡「vX.Y.Z 已下载并校验通过，重启后启用：立即重启安装 / 稍后（下次退出时安装）」
   └─ 用户点「立即重启安装」→ 置 pending_install=True → 触发退出流程
用户退出（X/托盘退出/立即重启安装）→ aboutToQuit → _quit_stop_services(...)  [顺序零变更]
   → 末步之后：maybe_launch_updater(app_ctx)
        ├─ 守卫：pending_install 且 verified 且 形态∈{onedir,onefile} 且 安装目录可写 且 sha 有值
        ├─ 写 plan.json（§4.4）
        ├─ Popen(detached) 拉起 sidecar
        └─ 记 QUIT-launch-updater 日志
sidecar 等待主 pid 退出 → 排空残留进程 → 换包 → 拉起新版 → 等 confirmed → 成功/回滚
新版启动 → 读 last_result.json 合并进 update_state.last_install → 清理 .part/旧 backup（按 D-V20-13）→ 清 confirmed
```

- **不做无确认静默替换**（Q-U9）：安装动作**必须**由用户在提示卡点一次（"立即重启安装"或"稍后=退出时安装"）。`auto_download` 只影响下载，不影响安装确认。
- **"立即重启安装"实现**：调用与托盘退出同一条退出编舞（置 `app_ctx.quitting=True` → `window.close()` / `app.quit()`），**不新增第二条退出路径**（防 v1.6.1 退出竞态回归）。
- **Pi 子进程显式停机（⚠-8）**：在 `_quit_stop_services` 内**补一步**（在现有第 2 步 chat_service 之后、新增 `QUIT-stop-pi`）：若存在 Pi RPC 会话则 `stop()`。此步为**新增独立步**，不影响既有 5 步顺序契约（R-D）。§3.2 列出。
- **手动"下次退出时安装"**：`pending_install` 标记落 `update_state.json`；下次退出时若仍 `verified` 且版本未变 → 自动拉起 sidecar（不再问）。

**被否决的替代方案**

- ❌ **静默替换**：Q-U9 明确否决（回滚漏洞=软件打不开级事故）。
- ❌ **在 `aboutToQuit` 之前（如 closeEvent）就拉 sidecar**：此时 UI 与服务未拆，安装目录仍被占用，换包必败；必须在服务停止后。

---

### D-V20-10 状态文件并发与单一写者

**决策**

- `update_state.json` 写入统一走新函数 `save_update_state(patch: dict)`（读-合并-写，原子：写临时文件 + `os.replace`），**禁止散落直接 `write_text`**（`save_ignored_version` 内部改调它，签名与语义不变 → R-D）。
- **写者划分（避免并发）**：
  | 进程 | 可写范围 | 时机 |
  |---|---|---|
  | 主进程 | `update_state.json`（检查/下载/pending_install/last_install 合并） | 运行期 |
  | sidecar | **只写** `updater/*`（plan 消费、`last_result.json`）；**不写** `update_state.json` | 主进程退出后 |
  | 新版主进程 | 启动早期消费 `last_result.json` → 合并进 `update_state.json` 并删除 result 文件 | 启动期 |
- 同一时刻只有一个主进程（沿用现有单实例行为）；sidecar 启动后**先等主 pid 退出**再动安装目录与 result，故不存在主/辅同写 `update_state.json`。

**被否决的替代方案**

- ❌ **sidecar 直接改 `update_state.json`**：会在主进程刚退出、文件缓冲未刷的窗口期争写；拆成"sidecar 写 result → 新进程合并"更稳。
- ❌ **引入文件锁（`msvcrt.locking`）**：过度设计；单写者时序已足够，且 `msvcrt` 禁用风险（AGENTS.md §6 平台检测要求）。

---

### D-V20-11 R-M 校验收口：URL 白名单 + 强制 sha256 单一函数

**决策**

- **URL 校验单一函数** `is_allowed_url(url, extra_hosts) -> bool`：
  1. scheme 必须 `https`（拒 `http`/`file`/空）；
  2. 拒 UNC（以 `\\` 开头）、拒相对路径、拒 path 含 `..` 段；
  3. `netloc` 必须命中白名单：`github.com` / `objects.githubusercontent.com` / `raw.githubusercontent.com` / `codeload.github.com` + `extra_hosts`（用户自配镜像，来自 `GuiConfig.mirror_url` 的 host）；
  4. 白名单外 → 拒绝，记 info 日志，不下载。
- **sha256 强制**：`assets.<kind>.sha256` 缺失或非法（非 64 hex）→ **禁止自动替换**（Q-U5），降级为"发现新版（无法校验，建议手动下载）"，只给"复制链接"。
- 校验失败 → 删除成品文件 + 不进入 L3 + emit `failed`（L2-4 验收②）。
- **不做凭证/隐私**：更新请求只 GET `version.json` 与产物，不携带 API Key / 设备指纹（R-M④）。

**被否决的替代方案**

- ❌ **只做前缀 `https://` 校验**：无法拦 `https://evil.com/x.zip` 投毒（version.json 被篡改时）；域名白名单是必要防线。
- ❌ **sha256 缺失时按大小比对就放行**：Q-U5 明确否决（安全优先）。

---

### D-V20-12 安装目录 / 磁盘可写预检（Q-U12 + L2-6）

**决策**

- **磁盘空间预检** `disk_precheck(staging_dir, install_parent, size) -> (ok, reason)`：
  - 缓存卷：`shutil.disk_usage(staging_dir).free >= size * 1.2`（下载 `.part` 峰值）；
  - 安装卷：`shutil.disk_usage(install_parent).free >= size * 2.5`（解压峰值，onedir ≈ 压缩比 ~2.2）;
  - 不足 → 明确错误码 + 提示，**不发第一个 GET**（L2-6 验收①）。
- **安装目录可写预检** `is_install_writable(install_dir) -> bool`：`os.access(install_dir.parent, os.W_OK)` + **实际写探针**（临时文件创建/删除），二者皆通过才算可写。
- 不可写（如 `Program Files`）→ Q-U12：**不尝试自动替换**，提示卡「已下载完成，但当前目录无法自动替换，请手动解压覆盖」+「打开文件夹」按钮（打开 `%APPDATA%/.../updates/<ver>/`）。
- 校验时机：**下载完成、进 L3 之前**；不可写则 `pending_install` 不置位。

**被否决的替代方案**

- ❌ **只信 `os.access`**：Windows 上 `W_OK` 对只读 ACL/虚拟化目录常误报可用，必须写探针。
- ❌ **下载前就检查安装目录可写**：用户可能稍后移动目录；且首检失败会过早放弃下载（下载本身有价值——可手动替换）。

---

### D-V20-13 备份保留与清理（Q-U6）

**决策**

- 备份 = `<install_parent>/.maling_backup_<from_ver>/`（onedir）/ `<exe>.old`（onefile），**保留最近 1 版**。
- 清理时机：新版启动**成功写 confirmed** 且 `last_result.result=="success"` 后，新版主进程扫描 `install_parent` 下所有 `.maling_backup_*`，**只保留 `from_version` 对应的那一个**（其余删除；删除失败忽略留待下次）。
- 设置页「清理更新缓存」：清空 `%APPDATA%/maid_coder/updates/**`（含 `.part`/`.verified`/成品 zip），**保留** `updater/**`（sidecar 自身与日志）；**不动**任何 `.maling_backup_*`（那在安装卷，且是回滚保险）——按钮文案如实说明"保留最近一版回滚备份"。
- `last_install` 记录 `{version, result: success|failed|rolled_back, at}`，供设置页一句可重试提示（R-A：不展示次数/落后版本数）。

**被否决的替代方案**

- ❌ **保留多版备份**：onedir 536MB/版，磁盘压力大（PRD Q-U6 定为 1 版）。
- ❌ **启动即删所有 backup**：若新版"能启动但功能坏"未触发回滚机制，会失去手动回滚源；故只在**确认成功**后清理。

---

### D-V20-14 检查节奏（Q-U13）与提示节奏（L1-5 / R-A）

**决策**

- `should_check_now(state, cfg, now) -> bool`（纯函数）：
  - `cfg.auto_check is False` → 启动不自动查；
  - 手动检查**不受限**（`force=True` 绕过）；
  - 自动：`last_checked` 为空 → 查；否则 `now - last_checked >= 24h` → 查，否则跳过。
- `should_prompt(version, state, today) -> bool`（纯函数，L1-5 验收②）：
  - `ignored_version` 为空 → True；
  - `is_newer_version(version, ignored_version)` → True（出现更新的版本恢复提示）；
  - 否则若 `last_prompt_date == today` → False（同日不重弹）。
- 提示一律 `setModal(False)` + 可关；失败态只在设置页留一句可重试提示（R-A 硬口径）。

**被否决的替代方案**

- ❌ **每次启动都提示**：骚扰用户，违 R-A。
- ❌ **用 `QTimer` 常驻轮询**：无必要（一天一次，启动检查足够）。

---

### D-V20-15 `update_checker.py` 增量契约保留（R-D 论证表）

| 契约 | 状态 | 说明 |
|---|---|---|
| `evaluate_update(remote, local_version, ignored_version)` 签名与返回键 | **零变更** | 新增字段不进返回值；`primary` 仍取 `downloads.github` |
| `format_update_text(info)` / `pick_download_link(info)` | **零变更** | 新态文案走新纯函数 |
| `UpdateChecker.update_available = Signal(dict)` | **零变更** | payload 结构不变 |
| `_FetchWorker`（fetched/failed） | **零变更** | 下载器新类并列，不改它 |
| `load_update_state()` / `save_ignored_version()` | 签名零变更 | 内部实现改调 `save_update_state`（原子写），行为等价 |
| `_valid_remote` 强依赖 `version`+`downloads.github` | **保留** | 新字段可选；旧式 `version.json` 仍可 L1 提示（L1-4 验收①） |
| `VERSION_JSON_URL` / `CHECK_TIMEOUT_SECONDS` | **常量名保留** | 取值来源升级为频道表；`VERSION_JSON_URL` 作 stable 别名 |
| `version.json` 旧字段 | **不改语义** | 只加 `min_updatable`/`release_url`/`assets`；`downloads.github` 由空补值 |
| v1.9 四风格 / 字体 / 命名 | **零触碰** | 本期不涉及 |

→ 结论：v2.0 是 `update_checker.py` 的**频道化 + 字段扩展 + 新模块并列**，非重写。

---

## 3. 文件清单

### 3.1 新增

| 文件 | 职责 | 依赖 | 红线 |
|---|---|---|---|
| `gui/update_downloader.py` | 下载器：`DownloadWorker(QThread)` + 纯函数核（URL 链 / 续传 / 进度文本 / sha256 / 空间预检 / URL 白名单） | `requests`(既有)、`hashlib`、`shutil`、`os`、`threading` | R-F 零新依赖；R-M URL/校验收口 |
| `maling_updater.py` | sidecar 主体：argv 契约 / pid 等待 / 进程排空 / onedir swap / onefile swap / 回滚 / result 写盘 / 日志 | 仅标准库（`ctypes`/`os`/`shutil`/`subprocess`/`json`/`hashlib`/`time`/`logging`/`argparse`） | R-F；R-N（不碰用户数据域） |
| `updater.spec` | sidecar 打包（onefile，`maling_updater`） | — | 体积最小化 |
| `tests/test_v20_check.py` | 检查层纯函数测试（频道表/节奏闸/提示节奏/合法性） | — | — |
| `tests/test_v20_downloader.py` | 下载器测试（mock 服务端 Range/200/降级/sha/空间） | — | — |
| `tests/test_v20_updater.py` | sidecar 测试（临时目录树模拟 swap/回滚/plan 解析/进程排空桩） | — | — |
| `tests/test_v20_assets.py` | 资产/URL 契约 + version.json 契约测试 | — | R-M |
| `tools/build_release.py`（可选） | 发版脚本：zip + sha256 + 命名规范 + `version.json` 片段生成 | — | R-O |
| `tools/release_checklist.md` | 发版 12 步人工清单（PRD §6 固化） | — | R-O |

### 3.2 修改

| 文件 | 改动 | 红线注意 |
|---|---|---|
| `gui/update_checker.py` | 频道表 + `GITHUB_OWNER` + `resolve_channel_url` + `should_check_now`/`should_prompt` + `save_update_state`（原子写）+ `asset_for_form`/`has_valid_sha256` 纯函数；**保留**全部既有契约（D-V20-15 表） | R-D 契约保留区 |
| `gui/config.py` | +`update_channel`(="stable")、`auto_check`(=True)、`auto_download`(=True)、`use_mirror`(=True)、`mirror_url`(="")；load/save 同步 | 既有键不动 |
| `gui/main.py` | ①检查接线追加节奏闸/频道；②提示卡扩展四态；③`_quit_stop_services` 补 Pi 停机步 + 末步 `maybe_launch_updater`；④启动早期 updater 自举 + 消费 `last_result.json`；⑤新版启动写 `confirmed.json`（UI 就绪后） | **严格串行单写者**；退出序列既有 5 步顺序零变更 |
| `gui/pages/page_settings.py` | 「更新」区：当前版本 / 检查更新按钮（三态+检查中置灰）/ 频道下拉 / 自动检查 / 自动下载 / 更新源（主链域名+备用链开关+自定义镜像）/ 清理更新缓存 | 复用 `_create_section` + `cfg.save()` |
| `gui/pages/page_about.py` | 版本卡加手动「检查更新」入口 + 更新源展示 | 开源组件表不动 |
| `version.json` | +`min_updatable` / `release_url` / `assets.onedir` / `assets.single`；`downloads.github` 补真实 URL；`channel` 保留 | **只加字段**；R-O③ 消占位 |
| `maid_coder_gui.spec` | datas +`('updater_dist','updater')`（内嵌 sidecar）；hiddenimports +`gui.update_downloader` | 路径按 `get_resource_path` 基准 |
| `maid_coder_gui_onefile.spec` | 同上 + **补 v1.9 遗留**：`('gui/assets/fonts','assets/fonts')` + `'gui.fonts'`（⚠-10） | 修 bug 非新功能 |
| `README.md` / `CHANGELOG.md` | 更新章节（安装/更新说明、sha 校验、未签名如实说明 R-O④）+ 版本条目 | R-K/R-O 诚实 |

### 3.3 不动（保护区）

`gui/utils.py`（`get_user_data_dir`/`get_resource_path` 签名零改）、`core/__init__.py`（`parse_version`/`is_newer_version` 零改）、`gui/fonts.py`、`gui/themes/**`、`persona.py`、`session.py`、`memory.py`、`companion.py`、`pi_backend.py`（仅 quit 编排处调用其 `stop()`，**不改其实现**）、`gui/chat_service.py`（不改 shutdown；Pi 停机在 `main.py` 编排层做）、v1.9 全部资产与文案。

### 3.4 文件域切分（供多工程师并行）

| 域 | 独占文件 | 可并行 | 说明 |
|---|---|---|---|
| **域1 检查/配置/UI设置** | `gui/update_checker.py`、`gui/config.py`、`version.json`、`page_settings.py`、`page_about.py` | 与域2、域3 并行 | 契约须先冻结（V20-01） |
| **域2 下载器** | `gui/update_downloader.py`、`tests/test_v20_downloader.py`、`tests/test_v20_check.py`、`tests/test_v20_assets.py` | 与域1、域3 并行 | 纯函数 + mock 服务端 |
| **域3 换包/sidecar** | `maling_updater.py`、`updater.spec`、`tests/test_v20_updater.py`、主包内嵌 `updater/` 目录 | 与域1、域2 并行（仅依赖契约） | **高危，单人独占** |
| **域4 `gui/main.py` 接线** | `gui/main.py` | **串行** | 域1（检查接线）与域3（退出编排）**都要改 main.py** → 必须单写者顺序交棒，禁止并发编辑 |
| **域5 打包/发版/文档** | 两个 `*.spec`、`tools/**`、`README.md`、`CHANGELOG.md` | 收尾阶段 | 依赖域1/2/3 产物名与 datas 定案 |

**必须串行的链**：`V20-01 契约冻结` → 域1/域2/域3 并行 → `main.py 交棒（域1 完成检查接线后，域4 再加退出编排）` → 域5 收口。**L3 换包（域3 + 域4 的退出编排）建议同一人完成**，因为换包正确性依赖退出时序的精确配合。

---

## 4. 数据结构

### 4.1 `version.json` 契约（权威指针，放仓库 `main/version.json`；beta 放 `main/beta/version.json`）

```json
{
  "version": "2.0.0",
  "channel": "stable",
  "released_at": "2026-09-20",
  "min_compatible": "1.0.0",
  "min_updatable": "2.0.0",
  "notes": ["要点1（≤5 条）", "要点2"],
  "release_url": "https://github.com/<owner>/maling/releases/tag/v2.0.0",
  "downloads": {
    "github": "https://github.com/<owner>/maling/releases/download/v2.0.0/MaLing_v2.0.0_win_onedir.zip",
    "mirror": ""
  },
  "assets": {
    "onedir": {"url": "https://github.com/<owner>/maling/releases/download/v2.0.0/MaLing_v2.0.0_win_onedir.zip",
               "mirror": "", "sha256": "<64hex>", "size": 260200000,
               "filename": "MaLing_v2.0.0_win_onedir.zip"},
    "single": {"url": "https://github.com/<owner>/maling/releases/download/v2.0.0/MaLing_v2.0.0_win_single.exe",
               "mirror": "", "sha256": "<64hex>", "size": 186600000,
               "filename": "MaLing_v2.0.0_win_single.exe"}
  }
}
```

| 字段 | 必填 | 语义 / 约束 | 变更 |
|---|---|---|---|
| `version` / `channel` / `released_at` / `notes` | ✅/✅/✅/⬜ | 沿用 | 保留 |
| `min_compatible` | ⬜ | 本地 < 它 → `kind=reinstall`（**话术**） | 保留 |
| `min_updatable` | ⬜ | 本地 < 它 → **禁止自动替换**，只提示整包重装（**能力闸**） | **新增** |
| `release_url` | ⬜ | Release 页（"查看完整更新内容"） | **新增** |
| `downloads.github` | ✅ | `_valid_remote` 依赖；onedir 主链 | **由空补值（⚠-5）** |
| `downloads.mirror` | ⬜ | onedir 备用链 | 保留 |
| `assets.{onedir,single}` | ⬜ | 缺 → 按 Q-U5 禁止自动替换（仅提示手动） | **新增** |
| `assets.*.filename` | ⬜ | 就位文件名（命名规范 Q-U2），缺 → 从 `url` 末段推导 | **新增** |

- **合法性判定不变**：`_valid_remote` 仅看 `version` + `downloads.github`，新字段全可选 → 旧式 `version.json` 零破坏（L1-4 验收①）。
- **`min_compatible` 与 `min_updatable` 正交**：前者决定"提示怎么说"，后者决定"能不能自动换"。二者可同时命中（此时只提示、不自动换）。

### 4.2 `update_state.json` 扩展（`%APPDATA%/maid_coder/update_state.json`）

```json
{
  "ignored_version": "1.9.0",
  "last_checked": "2026-09-10T21:00:00",
  "last_prompt_date": "2026-09-10",
  "channel": "stable",
  "pending_version": "2.0.0",
  "pending_install": true,
  "download": {
    "version": "2.0.0",
    "asset": "onedir",
    "filename": "MaLing_v2.0.0_win_onedir.zip",
    "path": "C:/Users/x/AppData/Roaming/maid_coder/updates/2.0.0/MaLing_v2.0.0_win_onedir.zip",
    "part_path": ".../MaLing_v2.0.0_win_onedir.zip.part",
    "received": 260200000,
    "total": 260200000,
    "sha256": "<64hex>",
    "url_index": 0,
    "verified": true,
    "updated_at": "2026-09-10T21:03:00"
  },
  "backup_path": "D:/apps/.maling_backup_1.9.0",
  "last_install": {"version": "2.0.0", "result": "success", "at": "2026-09-10T21:06:30"}
}
```

| 字段 | 语义 | 变更 | 备注 |
|---|---|---|---|
| `ignored_version` / `last_checked` | 沿用 | 保留 | |
| `last_prompt_date` | 同日去重（L1-5） | **新增** | `YYYY-MM-DD` |
| `channel` | 生效频道镜像（GuiConfig 为真值源） | **新增** | D-V20-07 |
| `pending_version` | 已下载待安装版本 | **新增** | |
| `pending_install` | "下次退出时安装"标记 | **新增** | 与 pending_version 联合判定 |
| `download` | 续传/校验所需全量信息 | **新增** | `verified=true` 是进 L3 的必要条件 |
| `backup_path` | 上一版备份位置（**可在安装卷**） | **新增** | ⚠-1 修正 |
| `last_install` | `success` / `failed` / `rolled_back` + 时间 | **新增** | 供设置页一句提示 |

- 读时缺字段按默认处理，**零迁移**（沿用 F-5）；写入走 `save_update_state`（原子，D-V20-10）。

### 4.3 目录树（用户数据域 + 安装卷 staging）

```
%APPDATA%/maid_coder/                     ← 用户数据域（R-N：用户数据零触碰）
├── gui_config.json                       ← 保护区（含 update_* 新键）
├── user_memory.json / *.json / sessions… ← 保护区（禁止换包触碰）
├── update_state.json                     ← 更新子系统状态（唯一例外，允许写）
├── updater/                              ← sidecar 运行时（「清理更新缓存」不删！）
│   ├── maling_updater.exe
│   ├── plans/plan_2.0.0_<ts>.json
│   ├── logs/updater_2.0.0_<ts>.log
│   ├── pending_confirm.json              ← 待确认（sidecar 写）
│   └── last_result.json                  ← 换包结果（sidecar 写，新进程消费后删）
└── updates/                              ← 下载缓存（「清理更新缓存」清空此处）
    ├── 2.0.0/
    │   ├── MaLing_v2.0.0_win_onedir.zip
    │   ├── MaLing_v2.0.0_win_onedir.zip.part
    │   └── .verified
    └── <旧版本>/…

<install_parent>/                          ← 安装卷（可能非 C:）
├── maling/                                ← 当前安装目录（onedir）
├── .maling_backup_1.9.0/                  ← 备份（rename 源/回滚源）
└── .maling_new_2.0.0/                     ← 新解压目录（rename 目标；成功后消失）
```

- **同卷硬约束**：`.maling_*` 必须在 `install_parent` 下（D-V20-02）；`updates/` 只要在任意可写卷即可（缓存）。
- onefile 形态下安装卷目标为 `<exe>` 与 `<exe>.old`，无目录级 staging。

### 4.4 sidecar plan.json（主进程写、sidecar 读，唯一输入）

```json
{
  "schema": 1,
  "action": "swap_onedir",
  "target_version": "2.0.0",
  "from_version": "1.9.0",
  "app_pid": 12345,
  "app_exe": "D:/apps/maling/maling.exe",
  "install_dir": "D:/apps/maling",
  "install_parent": "D:/apps",
  "package_path": "C:/Users/x/AppData/Roaming/maid_coder/updates/2.0.0/MaLing_v2.0.0_win_onedir.zip",
  "package_sha256": "<64hex>",
  "staging_dir": "D:/apps/.maling_new_2.0.0",
  "backup_dir": "D:/apps/.maling_backup_1.9.0",
  "confirm_dir": "C:/Users/x/AppData/Roaming/maid_coder/updater",
  "confirm_timeout_sec": 45,
  "kill_timeout_sec": 20,
  "log_path": "C:/Users/x/AppData/Roaming/maid_coder/updater/logs/updater_2.0.0_<ts>.log"
}
```

`action ∈ {"swap_onedir","swap_onefile"}`（onefile 下 `staging_dir` 为 null、`package_path` 指向 `.exe`）。sidecar 启动即校验 `schema==1`，未知 schema → 退出 4（不换包）。

### 4.5 sidecar 回调文件

| 文件 | 写者 | 内容 | 消费者 |
|---|---|---|---|
| `updater/pending_confirm.json` | sidecar | `{"version","pid","from_version","at"}` | sidecar 自身轮询 |
| `updater/last_result.json` | sidecar | `{"version","result":"success"\|"failed"\|"rolled_back","from_version","backup_path","at","detail"}` | 主进程启动早期（合并进 `last_install` 后删除） |
| `updater/confirmed.json` | **新版主进程**（UI 就绪后） | `{"version","pid","at"}` | sidecar（判定成功） |

### 4.6 `GuiConfig` 新增键

| 键 | 值域 | 默认 | 归属 |
|---|---|---|---|
| `update_channel` | `stable` / `beta` | `stable` | 用户设置（真值源） |
| `auto_check` | bool | `True` | 启动自动检查 |
| `auto_download` | bool | `True` | 后台自动下载（安装仍需确认） |
| `use_mirror` | bool | `True` | 启用备用链 |
| `mirror_url` | str | `""` | 自定义镜像（其 host 进 R-M 白名单） |

---

## 5. 任务分解（18 项，四批；L3 高危区单批串行）

> 工作量对齐 PRD 合计 11–13 人日。**批间可并行**：批 A / 批 B / 批 C 在契约冻结（V20-01）后并行；批 D 依赖前三批。

### 批 A · 契约冻结与检查层（域1，先行串行）

| ID | 任务 | 涉及文件 | 依赖 | 验收 | 独占 |
|---|---|---|---|---|---|
| V20-01 | **契约冻结**：`version.json` 字段 + `update_state.json` 扩展 + 频道表/`GITHUB_OWNER` + `save_update_state` 原子写 + plan schema + 目录树 | `update_checker.py`、`config.py`、`version.json`、`docs/design-v20.md` §4 | — | 契约纯函数可 import；`version.json` 含 `assets`/`min_updatable` 样例；旧式 `version.json` 仍 `_valid_remote` 通过 | 域1 单人 |
| V20-02 | 检查层增量：频道解析 / `should_check_now` / `should_prompt` / `asset_for_form` / `has_valid_sha256` / `is_allowed_url` | `update_checker.py` | V20-01 | 纯函数断言（L1-3/L1-5/L2-7/L2-4 部分） | 域1 |
| V20-03 | 检查层接线 + 设置/关于页 UI（三态按钮 + 频道/开关/更新源/清理缓存） | `main.py`(检查段)、`page_settings.py`、`page_about.py` | V20-02 | 手动检查 ≤5s 三态；按钮检查中置灰；忽略同日不重弹 | 域1（**main.py 检查段先占，随后交棒域4**） |
| V20-04 | 检查层测试 | `tests/test_v20_check.py`、`test_v20_assets.py` | V20-02 | 频道表/节奏/提示/合法性/URL 白名单全绿 | 域2 |

### 批 B · 下载层（域2，与批 A 并行）

| ID | 任务 | 涉及文件 | 依赖 | 验收 | 独占 |
|---|---|---|---|---|---|
| V20-05 | 下载器纯函数核（URL 链 / 续传 / `progress_text` / `verify_sha256` / `disk_precheck` / `is_install_writable`） | `update_downloader.py` | V20-01 | 纯函数单测；sha 篡改 1 字节 → False | 域2 |
| V20-06 | `DownloadWorker(QThread)`：Range 续传 / 200 重下 / 降级链 / 取消保留 `.part` / 进度信号 | `update_downloader.py` | V20-05 | mock 服务端断言请求头 `Range`、`.part`==received、全链失败保留 `.part` | 域2 |
| V20-07 | 下载器测试 + 下载态提示卡（进度 UI） | `tests/test_v20_downloader.py`、提示卡组件 | V20-06 | L2-1~L2-7 验收逐条 | 域2 |

### 批 C · 换包层（域3+域4，**高危，单人严格串行**）

| ID | 任务 | 涉及文件 | 依赖 | 验收 | 独占 |
|---|---|---|---|---|---|
| V20-08 | sidecar 骨架：argv 契约 / plan 解析 / `--version` / 自我保护自检 / 日志 | `maling_updater.py` | V20-01 | 无参退出 2；install_dir 内运行退出 3；未知 schema 退出 4 | **单人** |
| V20-09 | pid 等待（`ctypes` `OpenProcess`+`WaitForSingleObject`）+ **残留进程排空**（Toolhelp32 枚举 image path） | `maling_updater.py` | V20-08 | 模拟残留进程 → 等待/超时强杀；无残留直接过 | 单人 |
| V20-10 | onedir rename-swap（7 步）+ 失败回滚 + 同卷校验 | `maling_updater.py` | V20-09 | 目录树模拟：成功=全新；失败=逐文件回到旧；无"两个半成品目录" | 单人 |
| V20-11 | onefile 换法（改名→写入→拉起→`.old` 清理）+ 写入重试 | `maling_updater.py` | V20-09 | 路径不变、内容为新；`.old` 下次启动清理；写入被拒 → 回滚不崩 | 单人 |
| V20-12 | 回滚/确认协议：`pending_confirm` / `confirmed` / `last_result` + 新版启动自检钩子 + 旧/新版启动消费结果 | `maling_updater.py`、`main.py`(启动段) | V20-10、V20-11 | 拉起失败自动回滚且旧版可启动；`last_install=rolled_back` 落盘 | 单人 |
| V20-13 | 退出编排：`_quit_stop_services` 补 Pi 停机步 + 末步 `maybe_launch_updater`（守卫+Spawn detached）+「立即重启安装」走既有退出链 | `main.py` | V20-03（检查段交棒后）、V20-12 | detached 拉起成功；主进程退出后 sidecar 存活；v1.6.1 退出序列零回归 | 域4 单人 |
| V20-14 | `updater.spec` + 主包内嵌 sidecar + 启动自举复制到 `%APPDATA%/updater/` | `updater.spec`、两个 `*.spec`、`main.py`(自举段) | V20-10 | 产物 `maling_updater.exe` 体积合规；自举幂等；版本升级覆盖 | 单人 |
| V20-15 | sidecar 测试（临时目录树模拟全路径 + 回滚矩阵） | `tests/test_v20_updater.py` | V20-12 | 成功/失败/回滚/onefile/onedir 矩阵全绿 | 域3 |

### 批 D · 收尾（域5，依赖 A/B/C）

| ID | 任务 | 涉及文件 | 依赖 | 验收 | 独占 |
|---|---|---|---|---|---|
| V20-16 | 端到端真机留档：onedir / onefile × {正常 / 断网续传 / 校验失败 / 目录不可写} 八路径 | 留档文档 | V20-13、V20-14 | PRD §6 第 12 步 + §9.2 主张 5；用户数据零变化取证 | 单人 |
| V20-17 | 打包 spec 收口（onedir + onefile：内嵌 updater datas + hiddenimport + 修复 ⚠-10 字体缺口）+ 发版脚本/清单 | 两个 `*.spec`、`tools/build_release.py`、`tools/release_checklist.md` | V20-14 | `version.json` 片段生成 + zip/exe 命名与 `.sha256` 合规 | 域5 |
| V20-18 | 收尾：红线扫描（R-A/R-D/R-F/R-M/R-N/R-O）+ 全量回归 + README/CHANGELOG + dist 核对 | 文档 + 全局 | 全部 | py_compile + pytest 双绿；v1.9.0 零回归；dist 逐项核对 | 域5 |

**裁剪顺序（资源紧张时）**：`beta 频道`（Q-U8 可降 v2.0.x）→ `L2-6 空间预检` → `下载进度 UI 精细度`。**L3 与 R-M 强校验不裁**。

---

## 6. 共享知识（团队必读）

1. **sidecar 生存铁律**：updater 的 `sys.executable` **必须不在任何 `install_dir` 前缀下**，且**不在 `updates/` 下**（会被"清理更新缓存"删除）。落 `%APPDATA%/maid_coder/updater/`（D-V20-01/08）。
2. **同卷铁律**：一切 `os.rename` 就位/回滚操作，源与目标必须**同一卷**；解压/备份目录因此落 `install_parent` 下，绝不落 `%APPDATA%`（D-V20-02，PRD ⚠-2 修正）。
3. **残留进程排空**：Pi 引擎 spawn 的 `node.exe`（`_internal/pi_runtime/`）会锁死目录 rename。换包前必须排空安装目录内进程（D-V20-02）；`chat_service.shutdown()` 不停 Pi，需在 `main.py` 退出编排补一步 + sidecar 侧双重保险。
4. **版本比较唯一入口**：一律 `core.parse_version` / `is_newer_version`（数值元组），**禁止字符串比较**（`"1.10.0" < "1.9.0"` 陷阱）。
5. **R-N 禁区白名单**：换包路径对该目录**零写零删** = 用户数据域（`gui_config.json`/会话/记忆/persona/知识库/待办/日记/提醒…）；**排除**更新子系统自有子树 `update_state.json` + `updates/**` + `updater/**`（D-V20-01/§9 R-N）。
6. **`save_update_state` 单一写入口**：所有状态写走它（原子 `os.replace`）；sidecar **不写** `update_state.json`，只写 `updater/*` 结果文件，由新进程合并（D-V20-10）。
7. **Windows 长路径 `\\?\`**：打包/解压/读写深目录（`_internal/pi_runtime` 树 >260 字符）必须用 `\\?\` 前缀（先例 `tools/pack_release_v190.py:long_path`）。sidecar 解压 zip 同样要处理长路径。
8. **沙箱 safe-delete 限制**：批量删除 >50 个文件会被沙箱拦截（先例：v1.9 清理时的观察）。sidecar/测试清理临时目录树时**分批删除**或走 `shutil.rmtree` 的 onerror 逐项重试，避免一次性 `unlink` 列表触发拦截。
9. **worker 报告延迟**：QThread worker 的信号投递到 GUI 线程有事件循环延迟；**测试断言"收到信号"必须 `QCoreApplication.processEvents()` 或等待事件循环**，不能用"启动后立刻断言"（先例：v16/v17 测试踩坑）。
10. **测试必须 `QT_QPA_PLATFORM=offscreen`**：GUI 冒烟/信号测试在无显示环境（CI/沙箱）必须设 `QT_QPA_PLATFORM=offscreen`，否则 `QApplication` 初始化失败。
11. **受管 Python 路径**：本机受管 Python 解释器路径固定（见 `.workbuddy` 环境）；构建/测试命令一律用受管解释器，不依赖 PATH 里的 `python`；sidecar spec 构建亦然。
12. **命名规范（Q-U2）**：`MaLing_v<X.Y.Z>_win_onedir.zip` / `MaLing_v<X.Y.Z>_win_single.exe` + `.sha256`（内容 `<hash>  <filename>`，两空格）；版本号 `v` 前缀小写。
13. **`version.json` 是唯一让客户端"看到"新版的开关**：产物先上 Release，`version.json` 后 push（§7 第 10 步）；`downloads.github` 空值 = 客户端永不提示（⚠-5）。

---

## 7. 打包与发版（PRD §6 的 12 步 → 可执行）

| # | 步骤 | 可执行动作 / 脚本 | 门禁 |
|---|---|---|---|
| 1 | 定版号 | 改 `core/__init__.py`/`version.json` 的 `version`；`CHANGELOG.md` 写条目 | `get_version()` 返回新值 |
| 2 | 全量测试 | `QT_QPA_PLATFORM=offscreen pytest` | 基线 v1.9.0 + v2.0 新增用例全绿 |
| 3 | 构建 onedir | `pyinstaller maid_coder_gui.spec --noconfirm --clean` → `dist_v2.0.0f/maling/` | 含 `_internal/updater/maling_updater.exe` |
| 4 | 构建 onefile | `pyinstaller maid_coder_gui_onefile.spec --noconfirm --clean` → `MaLing_single.exe` | 含内嵌 updater + 字体 datas（⚠-10） |
| 5 | 构建 sidecar | `pyinstaller updater.spec --noconfirm --clean` → `dist_updater/maling_updater.exe` | 体积达标、无 Qt/requests |
| 6 | 压缩 onedir | `tools/build_release.py zip`（zipfile + `\\?\`，顶层 `maling/`） | `MaLing_v2.0.0_win_onedir.zip` |
| 7 | 算 sha256 | `certutil -hashfile <f> SHA256` / `sha256sum` | 记 64hex，与 `version.json.assets` 一致 |
| 8 | 写 Release 说明 | 抽 `CHANGELOG` 条目 + 安装/更新说明 + sha 值（**不签名的如实说明 R-O④**） | 无自评分（R-K） |
| 9 | 建 GitHub Release | tag `v2.0.0`；上传 zip/exe + `.sha256` | **上线前确认 `GITHUB_OWNER` 已替换 `your-repo`（R-O③ 硬闸）** |
| 10 | 更新 `version.json` | 填 `version`/`assets`/`downloads.github`/`min_updatable`；commit + push `main` | **`downloads.github` 非空（⚠-5 硬闸）**；此步才让客户端看到新版 |
| 11 | 小圈子分发 | 微信群/朋友圈发 Release 链接 | 新用户整包下载 |
| 12 | 端到端自测 | v1.9.0 真实包 → 提示 → 下载 → 校验 → 安装 → 拉起 → **核对 `%APPDATA%/maid_coder` 用户数据仍在** | 留档（V20-16） |

- `tools/build_release.py`（可选实现）职责：zip 打包（含 `\\?\`）、sha256 计算、`.sha256` 文本生成、`version.json` 片段草稿打印。**不强制自动化**（PRD §6 允许文档固化）。
- **`version.json` 何时 push**：第 10 步（产物全部可下载并验证后）。顺序错误会导致"客户端看到新版但包 404"。

---

## 8. 测试策略

### 8.1 纯函数（pytest 直接断言，无需真机/网络）

| 模块 | 断言点 |
|---|---|
| 检查层 | `resolve_channel_url`（stable/beta/非法回落）；`should_check_now`（24h 闸/关开关/force）；`should_prompt`（忽略同日/新版本恢复）；`_valid_remote`（旧式 `version.json` 零破坏） |
| 资产/URL | `is_allowed_url`（http/file/UNC/`..`/非白名单 host 全拒）；`asset_for_form`（onedir→zip、onefile→exe）；`has_valid_sha256`（缺失/非 64hex → False） |
| 下载器 | `resume_offset`；`progress_text`（单调不减）；`verify_sha256`（正确 True / 篡改 1 字节 False）；`disk_precheck`（不足返回 False 且**不发第一个 GET**）；`is_install_writable`（写探针） |
| 形态探测 | `detect_install_form`（dev/onedir/onefile 三态，monkeypatch `sys.frozen`/`_MEIPASS`） |
| sidecar | plan 解析（schema 校验/未知退出码）；目录树模拟的 swap 成功/失败/回滚；`last_result.json` 内容 |

### 8.2 必须 mock（不可真机联网）

- **下载器**：`requests` 打桩或本地 `http.server` mock —— 覆盖 ①支持 Range 返回 206（断言请求头 `Range: bytes=<received>-`）②返回 200（自动截断重下、无重复字节）③中途断链（`.part` 保留、下次续传）④全链失败（保留 `.part`）。
- **进程排空**：把"枚举安装目录内进程"抽象为可注入函数，测试注入假进程列表，验证等待/超时强杀逻辑。
- **sidecar 换包**：在 `tmp_path` 构造 `install_parent/maling/` 假目录树 + 假 zip，直接调用 swap 函数（不经 subprocess），断言目录结构。

### 8.3 mock 测不出 → **必须真机留档**（V20-16）

| 项 | 为什么 mock 测不出 |
|---|---|
| 文件锁 / 杀软占用 | mock 无真实句柄；只有真机才能验证 `rename` 在杀软实时扫描下的表现 |
| **Pi 残留进程锁目录** | 需真实 spawn `node.exe` 并验证 sidecar 排空（最高价值） |
| Windows 长路径 `\\?\` | 需真实文件系统深度 >260 |
| onefile "运行中 exe 可改名" | 平台特有行为，须真机 |
| 安装目录不可写（`Program Files`） | 需真实 ACL 环境 |
| 目录跨卷（`%APPDATA%` 在 C:、安装目录在 D:） | 需真实双卷 |

### 8.4 高危区专项矩阵（L3）

| 维度 | 用例 |
|---|---|
| 形态 × 结果 | onedir/onefile × {换包成功 / 拉不起回滚 / 目录被占用回滚} |
| 异常路径（PRD §9.2 主张 5） | 断网续传 / 校验失败 / 目录不可写 / sidecar 缺失 |
| 数据安全（R-N/L3-5） | 换包前后 `%APPDATA%/maid_coder` **用户数据域**文件清单 + mtime 零变化（白名单三键除外） |

---

## 9. 红线落法（PRD §8 逐条 → 代码级落点 + 可断言检查）

| 红线 | 落点 | 可断言检查 |
|---|---|---|
| **R-A 无焦虑** | 提示卡全 `setModal(False)`；`should_prompt` 同日去重；失败态只在设置页一句；文案禁"更新失败 N 次/落后 N 版" | ①`box.setModal(False)` 断言；②`should_prompt` 纯函数断言；③全链文案扫描词表（"失败"/"落后"/"还剩"）零命中；④失败不弹聊天区/首页（扫描） |
| **R-D 只增量** | `update_checker.py` 契约保留（D-V20-15 表）；`version.json` 只加字段；`update_state.json` 读时缺字段默认；不动 v1.9 四风格/字体/命名 | ①`evaluate_update`/`format_update_text`/`pick_download_link`/`update_available` 签名与语义回归测试；②旧式 `version.json` `_valid_remote` 通过；③v1.9 全量零回归 |
| **R-F 零新依赖** | 更新链 + sidecar 只用 `requests`(既有)/`hashlib`/`shutil`/`subprocess`/`ctypes`/`os`/`json` | ①`requirements*.txt` 无新增（diff 为空）；②sidecar 模块 AST 扫描：import 白名单外零命中 |
| **R-M 更新安全** | `is_allowed_url` 单一收口；`has_valid_sha256` 缺失即禁自动替换；sha 不符删包不进 L3；只读 `version.json` 无凭证 | ①URL 校验纯函数矩阵（http/file/UNC/../非白名单全拒）；②sha 缺失 → 提示卡为"无法校验，建议手动下载"（不出现"立即安装"）；③篡改包 → False + 删文件；④网络请求头无 Authorization（扫描） |
| **R-N 绝不伤主程序** | sidecar 只写 `updater/*` + 安装卷；主进程运行期不删/覆盖在用文件（换包仅退出后）；失败静默降级 + 回滚 | ①换包前后用户数据域文件清单/mtime 零变化（白名单三键）；②sidecar 代码扫描：用户数据域无 `unlink/rmtree/rename/write`；③模拟 sidecar 缺失 → 主程序正常启动 + 设置页一句可重试；④回滚后旧版可启动 |
| **R-O 分发诚实** | Release notes/CHANGELOG 不自评分；`GITHUB_OWNER` 消占位；未签名如实说明；dist 逐项核对 | ①发版清单第 9 步硬闸（`your-repo` grep 零命中）；②README/Release 含"未做代码签名"如实说明；③dist 核对：sidecar 落包 / sha 可校验 / 回滚可用三项留档 |

---

## 10. DoD（对照 PRD §10 逐条）

1. **L1 立住**：启动静默检查（沿用）+ 手动入口三态 + 频道切换 + `version.json` 指针契约（旧式兼容）+ 提示节奏（忽略同日不重弹）——全部纯函数可断言。
2. **L2 立住**：进度 UI + 断点续传（Range/200 回退）+ 重试降级 + sha256 校验 + 暂存隔离 + 空间预检 + 形态自适应；弱网可续、错包作废、取消保留 `.part`。
3. **L3 立住**：sidecar 换包（onedir 整目录 rename-swap / onefile 改名换 exe）+ 备份回滚（就绪标记+存活探测+超时三重判定）+ 用户数据零触碰 + 失败静默降级；**真机端到端更新留档**（八路径）。
4. **红线归零**：R-A / R-D / R-F / R-M / R-N / R-O 六条逐项对照；更新链零新第三方依赖；`%APPDATA%/maid_coder` 用户数据域换包前后零变化（白名单三键除外）。
5. **零回归 + 打包**：v1.9.0 全量功能（四风格 / 字体 / 命名 / 记忆 / 群聊 / Pi）零回归；py_compile + pytest 双绿；sidecar 落包、sha256 可校验、回滚可用在 dist 上逐项核对留档；onefile 字体缺口（⚠-10）修复。

---

> 文档结束 · 高见远 · 2026-09-10 · 基线 v1.9.0 · 功能面零改动 · `update_checker` 契约保留 · L3 换包为最大风险区（单批串行）
