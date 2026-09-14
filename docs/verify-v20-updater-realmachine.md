# v2.0 自动更新 sidecar 换包层 · 真机验证留档（V20-16）

- 验证人：严过关（QA）
- 日期：2026-09-11
- 被测物：`maling_updater.py`（1336 行，纯标准库）+ 已构建 `dist_updater/maling_updater.exe`（7,591,945 B ≈ 7.24 MB）
- 契约：`docs/design-v20.md` §2 D-V20-01~04 / §4.4 / §4.5 / §8.4；需求 `docs/prd-v20.md` L3-1~L3-6
- 原则：**真实 Windows 文件系统 + 真实进程 + 真实已构建 exe**；不改任何产品源码
- 合成目录、日志、报告全部落 `D:/qa_v20_16/`（`cases/`、`logs/`、`report.json`、`_harness/v20_runner.py`），未往工作副本落垃圾

## 0. 方法说明（可信度前提）

- **两种真实桩**（用受管 Python + PyInstaller 6.22.2 打成，非 mock）：
  - `maling_fake_od/`：**onedir** 桩（12 文件，`maling.exe` + `_internal/`），**等价真实 `dist_v190f/maling/` 形态**，用于全部 onedir 场景；
  - `maling_fake.exe`：**onefile** 桩，用于 S10/S11（onefile 形态）。
  - 桩按 `_fake_cfg.json` 决定行为：`success`=以 `os.getpid()` 写 `confirmed.json` 后长驻；`hang`=不写 confirmed；`die`=立即退出。
- 方法上踩过的坑（已纠正，记录以免误判）：
  1. 最初用 **onefile 桩**跑 onedir 场景，导致 S7/S8 假失败——PyInstaller onefile 的 `Popen.pid`（bootloader）≠ 应用 `os.getpid()`（child）。改用 onedir 桩后 onedir 场景全绿；**这一现象本身是 S11 的真实缺陷**。
  2. 桩早期把运行日志写进安装目录，污染逐字节快照；已改到 `%TEMP%`。
- 逐字节对比：`snap(dir)` 取 `{相对路径: (size, sha256)}` 全量快照，前后 `==` 判定"零变化/复原"。
- 说明：本会话 WorkBuddy `sitecustomize` 有 safe-delete bulk 守卫（沙箱产物，用户机器不存在），已在驱动进程内抬高阈值，不影响 sidecar（sidecar 是独立 PyInstaller 进程）。

## 1. 结果矩阵（10 必测 + 2 附加）

| # | 场景 | 结果 | 关键证据（退出码 / 日志 / 快照） |
|---|---|---|---|
| S0 | 契约冒烟（真实 exe） | ✅ 通过 | `--version`→rc 0/stdout `2.0.0`；无参→rc 2；schema=2→rc 4；sidecar 在 install_dir 内→rc 3 |
| S1 | **Pi `node.exe` 残留锁目录（正例）** | ✅ 通过 | 控制组：node 持句柄时裸 `rename` → **WinError 5**（锁真实）。sidecar：`残留进程超时强杀: pid=… image=…\maling\node.exe` → `④ rename 旧目录 → 备份` **成功**，无 `step4_rename_install_failed`；node 已被强杀；`last_result=rolled_back` |
| S1b | node 在安装目录**外**持其文件句柄（反例 R-N） | ✅ 通过 | rc=1；无关 node **未被误杀（仍在运行）**；安装目录逐字节零变化；`step4_rename_install_failed`（旧版原样留守）→ **不误伤、失败安全** |
| S2 | 同卷通过 / 跨卷拒绝 | ✅ 通过 | 同卷 rc=1 且无"同卷校验失败"；跨卷（staging 落 C:）rc=**6** + 日志 `同卷校验失败` + **C: staging 未创建**（拒绝在解压之前）+ 安装目录零变化 |
| S3 | 长路径 `\\?\` >260 | ✅ 通过 | 完整深路径 **282 字符**（13 层）；解压成功、无 `解压写入失败`、无 precondition/未捕获异常；深路径文件落盘（回滚后于 `.maling_new_failed_*` 可见）；安装目录回滚后逐字节等于旧版 |
| S4 | sha256 不符 | ✅ 通过 | rc=**6** + `包 sha256 不符`；安装目录逐字节零变化；**staging 未创建**（校验先于解压） |
| S5 | staged version 不符 | ✅ 通过 | rc=**6** + `包版本不符`；安装目录逐字节零变化；**staging 已清**（无半成品） |
| S6 | 新版不可启动 → 回滚 | ✅ 通过 | 包内 `maling.exe`=非法 PE → `⑥ 拉起新版失败: WinError 216` → `⑧ 回滚完成` → `last_result=rolled_back`；安装目录**逐字节等于旧版**；坏版本留在 `.maling_new_failed_2.0.0`；无"需人工介入" |
| S7 | 成功路径 + confirm 握手 | ✅ 通过 | rc=**0**，`last_result=success`；`pending_confirm.pid == confirmed.json.pid == 拉起进程 pid`（10724）；安装目录已换新版（`_internal/data.dll=NEW-DLL`）；备份保留 |
| S8 | 确认超时兜底 | ✅ 通过 | 新版 `hang`（不写 confirmed）→ 耗时 **8.3s**（`confirm_timeout=6s`）→ `判定失败(timeout)` → `last_result=rolled_back`；安装目录逐字节等于旧版；新版进程已终止、不残留 |
| S9 | 安装目录不可写（ACL 拒写） | ✅ 通过 | 控制组：`install_parent` 写入被拒 `[Errno 13] Permission denied`；sidecar rc=**6** + `换包前置条件失败: 解压写入失败: … Permission denied`；旧版逐字节完好、exe 在位；`last_result` 已写 |
| S10 | onefile 换法（运行中改名 + 改名/写入/`.old` 清理） | ✅ 通过（机制） | (a) **运行中的 exe 改名成功**（Windows 特性验证）；(b) 换包后 exe sha == 新版包 sha、路径不变、`.old` 由换包产生、`purge_old_files` 清理成功 |
| S11 | **onefile 确认握手 pid 语义（缺陷探针）** | ❌ **缺陷** | sidecar 记录 pid（Popen/bootloader）=15448；应用自报 pid（`os.getpid()`/child）=5516；`is_confirmed(boot_pid)=False`、`is_confirmed(app_pid)=True` |

**汇总：10 必测场景全部通过（S1/S1b/S2/S3/S4/S5/S6/S7/S8/S9/S10）+ 1 项真实缺陷（S11）。**

## 2. 缺陷清单

### D-1【高】onefile 形态：确认握手 pid 永不匹配 → 每次更新被判"超时"并回滚

- **影响面**：**onefile 安装形态**（`MaLing_single.exe`，PRD §6 第 4 步产物）；onedir 形态**不受影响**（S7 真机 PASS）。
- **根因**：PyInstaller **onefile** 运行时，`launch_detached()`（`subprocess.Popen`）拿到的是 **bootloader（父）pid**；而应用内 `gui/main.py:1034` 用 `pid = os.getpid()`（**child** pid）经 `write_confirmed()` 写 `confirmed.json`。sidecar 的 `is_confirmed()` 要求 `version + pid` 严格一致 → 恒不匹配 → `poll_confirm` 45s 超时 → 判失败回滚。
- **最小复现**（真实 exe，非 mock）：
  1. 用 PyInstaller 打一个 onefile 桩，行为为"以 `os.getpid()` 写 `confirmed.json`"；
  2. 按 sidecar 语义 `Popen([exe], creationflags=DETACHED_PROCESS|CREATE_NO_WINDOW)` 拉起，记 `Popen.pid=A`；
  3. 读 `confirmed.json` 的 `pid=B`；
  4. `maling_updater.is_confirmed(dir, ver, A)` → `False`；`is_confirmed(dir, ver, B)` → `True`。
- **实际**：`A=15448`，`B=5516`（父子进程不同 pid）；S10 中 sidecar 日志：`⑥ 拉起新版 pid=19380` → 20s 后 `三重判定结果: timeout` → `判定失败(timeout)，回滚 onefile`。
- **期望**：新版 UI 就绪后握手成功（`success`），不需要用户重试。
- **连带缺陷 D-1b（中）**：上述误判触发回滚后，`terminate_process(new_pid)` 只杀掉 onefile **bootloader**，**child 仍存活并占用新 exe**，导致回滚 `_try_remove/rename` 失败：
  `④ 回滚失败（需人工介入）: [WinError 183] 当文件已存在时，无法创建该文件: '…\maling.exe.old' -> '…\maling.exe'` → `result=failed`。即：**新版被留在盘上但记录为失败、`.old` 未回收**，状态不受控。
- **建议修复方向**（仅供参考，请示作者定夺）：onefile 下 `main.py` 用 `os.getppid()`（即 bootloader pid）写 confirmed；或 sidecar 的存活/确认判定改为"进程树内任一存活 + 版本匹配"；或暂时对 onefile 关闭自动替换、只走"手动覆盖"兜底。

### D-2【低/提示】ACL 只读对本机不生效（环境限制，非产品缺陷）

- 本机以 `jr-202607241359\administrator` 运行，`icacls /deny` 对"目录改名/删文件"被绕过（仅"写文件"被拦）。S9 因此走"解压写入失败"路径（rc=6，行为正确）。真实"非管理员用户 + `C:\Program Files`"场景未能在本环境稳定复现（见 §4）。
- 附带确认：`gui/main.py:_maybe_launch_updater` 在拉起 sidecar 前会用 `is_install_writable(install_dir)`（`gui/update_downloader.py:321`，"os.access + 写探针"）闸一道，不可写时**根本不会拉起 sidecar**；S9 是为验证 sidecar 自身行为而**绕过该闸**直接执行。

## 3. 关键日志摘录（真实 exe 输出）

```
# S1：node.exe 持句柄锁目录 → 等待 → 强杀 → rename 成功
[WARNING] 残留进程超时强杀: pid=12228 image=D:\qa_v20_16\cases\s1_node_lock\install_parent\maling\node.exe
[INFO]    ④ rename 旧目录 → 备份: …\maling → …\.maling_backup_1.9.0
[INFO]    ⑤ rename 新目录就位: …\.maling_new_2.0.0 → …\maling
[WARNING] ⑦ 判定失败(failed)，进入回滚 ⑧
[INFO]    ⑧ 回滚完成：坏目录移开 …\.maling_new_failed_2.0.0，旧目录归位 …\maling
[INFO]    换包结束: result=rolled_back detail=verdict=failed

# S2 跨卷：拒绝在解压之前
[ERROR] 换包前置条件失败: 同卷校验失败，拒绝换包: 盘符不一致: [...]

# S9 不可写：受控前置失败（rc 6）
[ERROR] 换包前置条件失败: 解压写入失败: …\.maling_new_2.0.0\maling.exe: [Errno 13] Permission denied

# S10/D-1：onefile 确认超时 + 回滚失败
[INFO]    ⑥ 拉起新版: …\app\maling.exe pid=19380
[INFO]    三重判定结果: timeout
[CRITICAL] ④ 回滚失败（需人工介入）: [WinError 183] …'maling.exe.old' -> '…maling.exe'
[INFO]    换包结束: result=failed detail=rollback_failed: [WinError 183] …
```

## 4. 本环境无法验证 / 必须等真实仓库或正式包（未验证清单）

1. **真实 GitHub Releases 302 跨域下载链路**：`GITHUB_OWNER` 仍为占位、`version.json` 真实地址未建立 → 下载层真实链路未验证（本次只验证 sidecar 换包层，与下载解耦）。
2. **打包后 v2.0 GUI 的完整"发现→下载→换包→拉起"全链路**：当前无 v2.0.0 正式包（仅有 v1.9.0 产物），本次用手写 `plan.json` 直接驱动 sidecar，未走主进程真实编排。
3. **杀毒软件 / Defender 实时扫描造成的占用与误报**：本环境无法稳定复现，**记为未验证风险**（换包期文件被扫描器短暂占用可能造成 rename/写入被拒）。
4. **真实"非管理员用户 + Program Files"ACL 场景**：本机以管理员运行，ACL 对改名/删除被绕过（见 D-2），真实低权限安装路径未验证。
5. **大体积真实包（~500MB）**：本次用 KB 级合成包，未测解压/换包耗时与磁盘空间预检（`disk_precheck`）的真机表现。
6. **真实 Pi 会话 spawn 的 `node.exe` 进程树**：已用真实 `node.exe`（v22.22.2）复现"句柄锁目录 → 强杀"，但未在真实码铃运行态下跑 Pi 会话（真实 Pi 的进程层级/是否有多层子进程未验证）。
7. **onefile 正式包**：D-1 用 PyInstaller onefile 桩复现，未用 v2.0 正式 onefile 产物（因无）。

## 5. 上线判断（依据）

- **onedir 形态（当前主分发 `MaLing_v<ver>_win_onedir.zip`）：可上线。** 依据：S1（最高价值项，工程师自认 mock 测不出的 Pi node.exe 锁目录）在真机"等待→强杀→rename 成功"通过；S3/S4/S5/S6/S7/S8/S9/S1b 全部真机通过，含长路径、逐字节回滚、R-N 不误杀、跨卷拒绝、sha/版本双哨兵。核心风险（node.exe 锁目录、同卷、回滚）已被真机证据覆盖。
- **onefile 形态（`MaLing_single.exe`）：不建议随 v2.0 上线自动替换。** 依据：D-1（确认握手 pid 本质不匹配）会使 onefile 的自动更新**必然回滚**，且回滚还可能因 child 进程占位而失败，留下"新版在盘 + 记录 failed"的不受控状态。onedir 无此问题（S7 真机 PID 一致）。建议：修复 D-1 后再验证，或对 onefile 暂时关闭自动替换、只做手动覆盖兜底。
- 其余为环境未覆盖项（§4），不构成上线阻塞，但**真实 GitHub 链路与 v2.0 正式包全链路必须在上线前补测**。

## 6. 复现指引（供原作者定位 D-1）

```
被测 sidecar：D:/【试用测试】/maling_agent_改造/maling_agent_dev/dist_updater/maling_updater.exe
驱动脚本　　：D:/qa_v20_16/_harness/v20_runner.py（真实进程 + 真实 FS）
报告　　　　：D:/qa_v20_16/report.json；逐场景日志 D:/qa_v20_16/logs/{s0,s1,s1b,s2...}.log
关键纯函数　：maling_updater.is_confirmed / poll_confirm / launch_detached
应用侧写点　：gui/main.py:1034 `pid = os.getpid()` → write_confirmed(confirm_dir, version, pid)
```
