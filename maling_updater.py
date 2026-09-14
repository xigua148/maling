# -*- coding: utf-8 -*-
"""maling_updater.py —— 码铃（MaLing）v2.0 自动更新 sidecar（域3，最高危）。

职责（docs/design-v20.md §2 D-V20-01 ~ D-V20-04 / §4.4 / §4.5 / §5 批 C）：
    * 在主进程退出后，独立完成 onedir（整目录 rename-swap）/ onefile（运行中 exe
      改名换包）的替换、拉起新版、三重判定确认、失败回滚。
    * **纯标准库**（守 R-F）：argparse / ctypes / os / shutil / subprocess / json /
      hashlib / time / logging / pathlib / sys / tempfile。
    * **绝不触碰** `%APPDATA%/maid_coder` 用户数据域：只写 plan.confirm_dir 下的
      协议文件（pending_confirm / last_result）+ 安装卷 staging/backup + 日志。
    * sidecar **不写** update_state.json（那由主进程单一写者持有，D-V20-10）。

命令行契约（D-V20-01）：
    maling_updater.exe --pid <主进程pid> --plan <plan.json> --log <日志路径>
    maling_updater.exe --version        # 打印自身版本并退出 0

退出码表：
    0    成功（含回滚成功——软件仍可打开）
    1    换包执行失败（已尽力回滚 / 无需回滚，但本次未就位）
    2    参数非法：无参、缺少 --pid/--plan、不识别参数（绝不交互式运行）
    3    自我保护失败：sidecar 自身位于 install_dir 前缀内（生存铁律 D-V20-01）
    4    plan schema != 1（未知协议，不换包）
    5    plan 不合法：缺关键字段 / 字段类型错 / action 未知 / sha256 格式非法
    6    前置条件失败：跨卷 / 目标版本不高于当前 / 包 sha256 不符 / 解压产物不完整

自举与接线（供主进程调用的纯函数，D-V20-08 / V20-12）：
    ensure_self_installed(src_dir, dest_dir) -> Path
    consume_last_result(confirm_dir) -> dict | None
    write_confirmed(confirm_dir, version, pid) -> None
    purge_old_files(exe_path) -> bool
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

# ----------------------------------------------------------------------------
# 版本与常量
# ----------------------------------------------------------------------------
#: sidecar 自身版本（与携带它的客户端主版本强绑定，D-V20-08「版本一致性」）。
UPDATER_VERSION = "2.0.0"
__version__ = UPDATER_VERSION

#: plan 协议版本（D-V20-02 / §4.4）
PLAN_SCHEMA = 1

#: action 取值（§4.4）
ACTION_SWAP_ONEDIR = "swap_onedir"
ACTION_SWAP_ONEFILE = "swap_onefile"
_KNOWN_ACTIONS = (ACTION_SWAP_ONEDIR, ACTION_SWAP_ONEFILE)

#: 退出码
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_BAD_ARGS = 2
EXIT_SELF_INSIDE = 3
EXIT_BAD_SCHEMA = 4
EXIT_BAD_PLAN = 5
EXIT_PRECONDITION = 6

#: 回调文件名（§4.5）
PENDING_CONFIRM_NAME = "pending_confirm.json"
CONFIRMED_NAME = "confirmed.json"
LAST_RESULT_NAME = "last_result.json"

#: 包内默认可执行名（onedir 产物约定）
APP_EXE_NAME = "maling.exe"
INTERNAL_DIR_NAME = "_internal"

#: 默认超时（§4.4）
DEFAULT_CONFIRM_TIMEOUT_SEC = 45
DEFAULT_KILL_TIMEOUT_SEC = 20

#: 进程树判定最大上溯深度（缺陷 D-1：onefile bootloader → 应用本体仅 1 层，留足余量）
DEFAULT_TREE_MAX_DEPTH = 6
#: 回滚前终止整棵进程树后，等待句柄释放（进程退出）的默认上限（D-1b）
DEFAULT_TREE_KILL_WAIT_SEC = 5.0

#: 路径前缀分隔（staging 目录的兄弟命名，落在 install_parent 下 → 同卷）
STAGING_NAME_FMT = ".maling_new_{ver}"
BACKUP_NAME_FMT = ".maling_backup_{ver}"
FAILED_NAME_FMT = ".maling_new_failed_{ver}"

DEFAULT_SHA_CHUNK = 1024 * 1024
_COPY_RETRY_BACKOFF = (1.0, 3.0, 7.0)

_LOGGER_NAME = "maling_updater"

# ----------------------------------------------------------------------------
# Windows API 常量（ctypes；非 nt 平台全部降级为 no-op）
# ----------------------------------------------------------------------------
SYNCHRONIZE = 0x00100000
PROCESS_TERMINATE = 0x0001
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
ERROR_INVALID_PARAMETER = 87
ERROR_ACCESS_DENIED = 5
DETACHED_PROCESS = 0x00000008
CREATE_NO_WINDOW = 0x08000000

_kernel32_cache: Any = None


class UpdaterError(Exception):
    """带退出码的受控错误（main 捕获后写日志并以 code 退出）。"""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = int(code)


# ----------------------------------------------------------------------------
# 小工具
# ----------------------------------------------------------------------------
def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _win_long(path: Any) -> str:
    r"""Windows 长路径前缀（\\?\）—— 深目录（_internal/pi_runtime >260 字符）必需。

    design §6 共享知识 7：解压/读写深目录必须加前缀。非 Windows 原样返回。
    """
    s = os.fspath(path)
    if os.name != "nt":
        return s
    if s.startswith("\\\\?\\"):
        return s
    s = os.path.abspath(s)
    if s.startswith("\\\\"):
        return "\\\\?\\UNC\\" + s[2:]
    return "\\\\?\\" + s


def _norm(path: Any) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _norm_dir(path: Any) -> str:
    """规范化目录前缀：去掉尾部路径分隔（盘符根 "C:\\\\" → "C:"），避免拼出双分隔。"""
    n = _norm(path)
    stripped = n.rstrip("\\/")
    return stripped or n


def _is_under(path: Any, prefix: Any) -> bool:
    """path 是否落在 prefix 目录之下（含相等，Windows 大小写不敏感）。

    优先 abspath 前缀比较；不命中再以 realpath 兜底（junction / symlink 安装路径）。
    """
    p = _norm(path)
    base = _norm_dir(prefix)
    if p == base or p.startswith(base + os.sep):
        return True
    try:
        rp = os.path.normcase(os.path.realpath(os.fspath(path)))
        rb = _norm_dir(os.path.realpath(os.fspath(prefix)))
    except OSError:
        return False
    return rp == rb or rp.startswith(rb + os.sep)


def _try_remove(path: Any) -> bool:
    try:
        os.remove(_win_long(path))
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def _safe_rmtree(path: Any) -> bool:
    r"""删除目录树（长路径感知；分批逐项，规避沙箱批量删除拦截）。"""
    target = _win_long(path)
    if not os.path.exists(target):
        return True

    def _onerror(func, p, _exc):
        try:
            func(_win_long(p))
        except Exception:
            pass

    try:
        shutil.rmtree(target, onerror=_onerror)
        return not os.path.exists(target)
    except Exception:
        return False


def _rename(src: Any, dst: Any) -> None:
    """rename 单一收口（同卷原子操作，长路径感知）。

    独立成函数是为了让测试能注入"rename 被拒"（WinError 5/32）而不污染全局 os.rename。
    """
    os.rename(_win_long(src), _win_long(dst))


def parse_version(value: Any) -> Tuple[int, ...]:
    """数值元组版本解析（与 core.parse_version 语义一致）。

    ⚠ 这里刻意做一份本地实现：sidecar 是**独立 onefile**，按 V20-14 不收 core/gui，
    无法 import core；为守 R-F 与自包含，复制这份 10 行纯函数（非第二套语义）。
    """
    if isinstance(value, (tuple, list)):
        parts = list(value)
    else:
        parts = str(value or "").replace("-", ".").split(".")
    out: List[int] = []
    for p in parts:
        try:
            out.append(int(str(p).strip()))
        except (TypeError, ValueError):
            out.append(0)
    return tuple(out) if out else (0,)


def is_newer(candidate: Any, baseline: Any) -> bool:
    """candidate 是否严格高于 baseline（数值元组比较，禁字符串比较）。"""
    return parse_version(candidate) > parse_version(baseline)


def verify_sha256(path: Any, expected: str, chunk: int = DEFAULT_SHA_CHUNK) -> bool:
    """流式 sha256 比对（标准库 hashlib，守 R-F / R-M）。"""
    if not expected or not isinstance(expected, str):
        return False
    expected = expected.strip().lower()
    if len(expected) != 64:
        return False
    h = hashlib.sha256()
    try:
        with open(_win_long(path), "rb") as f:
            while True:
                block = f.read(chunk)
                if not block:
                    break
                h.update(block)
    except OSError:
        return False
    return h.hexdigest().lower() == expected


def is_valid_sha256(value: Any) -> bool:
    """64 位十六进制（R-M：sha256 缺失/非法 → 禁止自动替换）。"""
    if not isinstance(value, str):
        return False
    v = value.strip().lower()
    if len(v) != 64:
        return False
    return all(c in "0123456789abcdef" for c in v)


# ----------------------------------------------------------------------------
# 日志
# ----------------------------------------------------------------------------
def setup_logging(log_path: Any) -> logging.Logger:
    """初始化 sidecar 日志（带时间戳，落 plan.log_path 同目录）。

    任何落盘失败都退化为 stderr —— 绝不因日志问题崩溃，但也绝不静默吞异常。
    """
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            "%Y-%m-%d %H:%M:%S")
    try:
        parent = os.path.dirname(os.path.abspath(os.fspath(log_path)))
        if parent:
            os.makedirs(_win_long(parent), exist_ok=True)
        fh = logging.FileHandler(_win_long(log_path), encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        logger.addHandler(sh)
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    return logger


# ----------------------------------------------------------------------------
# plan 解析（§4.4，sidecar 唯一输入）
# ----------------------------------------------------------------------------
_REQUIRED_COMMON = (
    "action", "target_version", "from_version", "install_dir", "install_parent",
    "package_path", "package_sha256", "confirm_dir",
)
_REQUIRED_ONEDIR = ("staging_dir", "backup_dir")
_REQUIRED_ONEFILE = ("app_exe",)


class Plan:
    """plan.json 的强类型视图（字段语义见 design §4.4）。"""

    __slots__ = (
        "schema", "action", "target_version", "from_version", "app_pid", "app_exe",
        "install_dir", "install_parent", "package_path", "package_sha256",
        "staging_dir", "backup_dir", "confirm_dir", "confirm_timeout_sec",
        "kill_timeout_sec", "log_path", "raw",
    )

    def __init__(self, raw: Dict[str, Any]):
        self.raw = dict(raw)
        self.schema = raw.get("schema")
        self.action = str(raw.get("action") or "")
        self.target_version = str(raw.get("target_version") or "")
        self.from_version = str(raw.get("from_version") or "")
        self.app_pid = int(raw.get("app_pid") or 0)
        self.app_exe = str(raw.get("app_exe") or "")
        self.install_dir = str(raw.get("install_dir") or "")
        self.install_parent = str(raw.get("install_parent") or "")
        self.package_path = str(raw.get("package_path") or "")
        self.package_sha256 = str(raw.get("package_sha256") or "")
        staging = raw.get("staging_dir")
        backup = raw.get("backup_dir")
        self.staging_dir = str(staging) if staging else ""
        self.backup_dir = str(backup) if backup else ""
        self.confirm_dir = str(raw.get("confirm_dir") or "")
        self.confirm_timeout_sec = _as_float(
            raw.get("confirm_timeout_sec"), DEFAULT_CONFIRM_TIMEOUT_SEC)
        self.kill_timeout_sec = _as_float(
            raw.get("kill_timeout_sec"), DEFAULT_KILL_TIMEOUT_SEC)
        self.log_path = str(raw.get("log_path") or "")


def _as_float(value: Any, default: float) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def load_plan(path: Any) -> Plan:
    """解析并校验 plan.json；任何不合法 → UpdaterError(码 4/5)。"""
    try:
        with open(_win_long(path), "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        raise UpdaterError(EXIT_BAD_PLAN, f"plan 不存在: {path}")
    except ValueError as exc:
        raise UpdaterError(EXIT_BAD_PLAN, f"plan JSON 非法: {exc}")
    except OSError as exc:
        raise UpdaterError(EXIT_BAD_PLAN, f"plan 不可读: {exc}")
    if not isinstance(raw, dict):
        raise UpdaterError(EXIT_BAD_PLAN, "plan 顶层不是 JSON 对象")
    if raw.get("schema") != PLAN_SCHEMA:
        raise UpdaterError(EXIT_BAD_SCHEMA,
                           f"未知 schema: {raw.get('schema')!r}（要求 {PLAN_SCHEMA}）")

    action = raw.get("action")
    if action not in _KNOWN_ACTIONS:
        raise UpdaterError(EXIT_BAD_PLAN, f"未知 action: {action!r}")

    missing = [k for k in _REQUIRED_COMMON if not raw.get(k)]
    if action == ACTION_SWAP_ONEDIR:
        missing += [k for k in _REQUIRED_ONEDIR if not raw.get(k)]
    elif action == ACTION_SWAP_ONEFILE:
        missing += [k for k in _REQUIRED_ONEFILE if not raw.get(k)]
    if missing:
        raise UpdaterError(EXIT_BAD_PLAN, f"plan 缺关键字段: {sorted(set(missing))}")

    if not is_valid_sha256(raw.get("package_sha256")):
        raise UpdaterError(EXIT_BAD_PLAN,
                           "plan.package_sha256 非法（须 64 位十六进制，R-M 拒绝就位）")

    plan = Plan(raw)
    # install_dir 必须位于 install_parent 之下（允许相等：onefile 形态 exe 与父目录同层）
    if not _is_under(plan.install_dir, plan.install_parent):
        raise UpdaterError(
            EXIT_BAD_PLAN,
            f"install_dir({plan.install_dir}) 必须位于 install_parent({plan.install_parent}) 之下")
    return plan


# ----------------------------------------------------------------------------
# 自我保护（D-V20-01 生存铁律）
# ----------------------------------------------------------------------------
def self_check_ok(exe_path: Any, install_dir: Any) -> bool:
    """sidecar 自身 exe 是否**不在** install_dir 前缀下。

    返回 True = 安全（可以换包）；False = 自身住在被替换目录里（拒绝换包，退出 3）。
    """
    if not install_dir:
        return True
    return not _is_under(exe_path, install_dir)


# ----------------------------------------------------------------------------
# 进程：等待 / 探测 / 强杀 / 枚举 / 排空（D-V20-02 ③、D-V20-04 ②）
# ----------------------------------------------------------------------------
def _kernel32():
    global _kernel32_cache
    if os.name != "nt":
        return None
    if _kernel32_cache is None:
        try:
            from ctypes import wintypes  # noqa: F401  (确保 windll 可用)

            k = ctypes.WinDLL("kernel32", use_last_error=True)
            k.OpenProcess.restype = ctypes.c_void_p
            k.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
            k.CloseHandle.restype = ctypes.c_int
            k.CloseHandle.argtypes = [ctypes.c_void_p]
            k.WaitForSingleObject.restype = ctypes.c_uint32
            k.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            k.TerminateProcess.restype = ctypes.c_int
            k.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            k.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
            k.CreateToolhelp32Snapshot.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
            k.Process32FirstW.restype = ctypes.c_int
            k.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            k.Process32NextW.restype = ctypes.c_int
            k.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            k.QueryFullProcessImageNameW.restype = ctypes.c_int
            k.QueryFullProcessImageNameW.argtypes = [
                ctypes.c_void_p, ctypes.c_uint32, ctypes.c_wchar_p,
                ctypes.POINTER(ctypes.c_uint32)]
            _kernel32_cache = k
        except Exception:
            _kernel32_cache = None
    return _kernel32_cache


def wait_for_pid_exit(pid: int, timeout_sec: float) -> bool:
    """等待进程退出。返回 True = 已退出 / 不存在；False = 超时仍存活。

    机制：OpenProcess(SYNCHRONIZE) + WaitForSingleObject(handle, timeout)。
    """
    k = _kernel32()
    if k is None:
        return True
    try:
        handle = k.OpenProcess(SYNCHRONIZE, 0, int(pid))
    except Exception:
        return True
    if not handle:
        err = ctypes.get_last_error()
        # 进程不存在（无效参数）= 已退出；访问被拒 = 无法等待，按仍存活处理（交由排空强杀）
        return err != ERROR_ACCESS_DENIED
    try:
        rc = k.WaitForSingleObject(handle, int(max(0.0, float(timeout_sec)) * 1000))
        return rc == WAIT_OBJECT_0
    finally:
        try:
            k.CloseHandle(handle)
        except Exception:
            pass


def is_process_alive(pid: int) -> bool:
    """进程是否仍在运行（WaitForSingleObject(handle, 0)，D-V20-04 ② 存活探测）。"""
    k = _kernel32()
    if k is None:
        return False
    try:
        handle = k.OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, 0, int(pid))
    except Exception:
        return False
    if not handle:
        # 访问被拒 → 保守认为仍存活（避免误判失败而回滚）
        return ctypes.get_last_error() == ERROR_ACCESS_DENIED
    try:
        return k.WaitForSingleObject(handle, 0) != WAIT_OBJECT_0
    finally:
        try:
            k.CloseHandle(handle)
        except Exception:
            pass


def terminate_process(pid: int) -> bool:
    """强杀进程（TerminateProcess）。返回是否成功。"""
    k = _kernel32()
    if k is None:
        return False
    try:
        handle = k.OpenProcess(PROCESS_TERMINATE, 0, int(pid))
    except Exception:
        return False
    if not handle:
        return False
    try:
        return bool(k.TerminateProcess(handle, 1))
    except Exception:
        return False
    finally:
        try:
            k.CloseHandle(handle)
        except Exception:
            pass


class _PROCESSENTRY32W(ctypes.Structure):
    # th32DefaultHeapID 为 ULONG_PTR（64 位下 8 字节）→ 用 c_void_p，否则结构尺寸错、枚举失败
    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("cntUsage", ctypes.c_uint32),
        ("th32ProcessID", ctypes.c_uint32),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", ctypes.c_uint32),
        ("cntThreads", ctypes.c_uint32),
        ("th32ParentProcessID", ctypes.c_uint32),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_uint32),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


def _image_path(k, pid: int) -> str:
    handle = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, int(pid))
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = ctypes.c_uint32(len(buf))
        if k.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value or ""
        return ""
    except Exception:
        return ""
    finally:
        try:
            k.CloseHandle(handle)
        except Exception:
            pass


def enumerate_processes_under(prefix: Any) -> List[Tuple[int, str]]:
    """枚举 image path 落在 prefix 前缀下的进程（Toolhelp32，零第三方依赖）。

    返回 [(pid, image_path)]。典型目标：`_internal/pi_runtime/**/node.exe`（⚠-8）。
    """
    k = _kernel32()
    if k is None:
        return []
    result: List[Tuple[int, str]] = []
    snapshot = k.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == INVALID_HANDLE_VALUE:
        return result
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        ok = k.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            pid = int(entry.th32ProcessID)
            if pid:
                image = _image_path(k, pid)
                if image and _is_under(image, prefix):
                    result.append((pid, image))
            ok = k.Process32NextW(snapshot, ctypes.byref(entry))
    except Exception:
        pass
    finally:
        try:
            k.CloseHandle(snapshot)
        except Exception:
            pass
    return result


def _parent_of(pid: int) -> int:
    """返回 pid 的父进程 pid（Toolhelp32 快照）；pid 不在快照 / 无父 → 0。"""
    k = _kernel32()
    if k is None:
        return 0
    try:
        target = int(pid)
    except (TypeError, ValueError):
        return 0
    if target <= 0:
        return 0
    snapshot = k.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == INVALID_HANDLE_VALUE:
        return 0
    ppid = 0
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        ok = k.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if int(entry.th32ProcessID) == target:
                ppid = int(entry.th32ParentProcessID)
                break
            ok = k.Process32NextW(snapshot, ctypes.byref(entry))
    except Exception:  # noqa: BLE001 - 枚举失败按"查不到父进程"处理
        ppid = 0
    finally:
        try:
            k.CloseHandle(snapshot)
        except Exception:
            pass
    return ppid


def enumerate_process_children(parent_pid: int) -> List[int]:
    """枚举直接父进程为 parent_pid 的全部子进程 pid（Toolhelp32，零第三方依赖）。

    注：Windows 的 `th32ParentProcessID` 记录的是"创建者 pid"，创建者退出后该值
    不再变化（不做 reparent），因此 bootloader 退出后仍能查到它的应用本体子进程。
    """
    k = _kernel32()
    if k is None:
        return []
    try:
        target = int(parent_pid)
    except (TypeError, ValueError):
        return []
    if target <= 0:
        return []
    children: List[int] = []
    snapshot = k.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == INVALID_HANDLE_VALUE:
        return children
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        ok = k.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            cpid = int(entry.th32ProcessID)
            if cpid and int(entry.th32ParentProcessID) == target:
                children.append(cpid)
            ok = k.Process32NextW(snapshot, ctypes.byref(entry))
    except Exception:  # noqa: BLE001
        pass
    finally:
        try:
            k.CloseHandle(snapshot)
        except Exception:
            pass
    return children


def is_descendant(child_pid: Any, ancestor_pid: Any, *,
                  parent_of: Optional[Callable[[int], int]] = None,
                  max_depth: int = DEFAULT_TREE_MAX_DEPTH) -> bool:
    """child_pid 是否位于 ancestor_pid 的后代链上（父链上溯，最多 max_depth 层）。

    缺陷 D-1 的核心：PyInstaller **onefile** 的 `Popen.pid` 是 bootloader，
    应用本体是 bootloader 的子进程；`confirmed.json` 由应用本体写、带的是本体 pid，
    所以「自身 pid 相等」判定在 onefile 下永远为 False（每次更新都会误判超时→回滚）。
    本函数用于接受「后代 pid」。

    `parent_of` 可注入（单测不碰真实进程表）。任何查询异常 / 触顶未命中 → False
    （宁可不认账，也不误认账）。
    """
    fn = parent_of or _parent_of
    try:
        cur = int(child_pid)
        anc = int(ancestor_pid)
    except (TypeError, ValueError):
        return False
    if cur <= 0 or anc <= 0 or cur == anc:
        return False
    for _ in range(max(0, int(max_depth))):
        try:
            cur = int(fn(cur))
        except Exception:  # noqa: BLE001 - 查询失败 → 按非后代处理
            return False
        if cur <= 0:
            return False
        if cur == anc:
            return True
    return False


def _safe_alive(alive_fn: Callable[[int], bool], pid: int) -> bool:
    """alive_fn 查询失败 → 按"不存活"处理（等待循环另有超时兜底）。"""
    try:
        return bool(alive_fn(pid))
    except Exception:  # noqa: BLE001
        return False


def _pid_tree_alive(pid: int) -> bool:
    """pid 或其任一直接后代是否存活（onefile：bootloader 退出但应用本体仍在 → 不算失败）。"""
    if is_process_alive(pid):
        return True
    try:
        kids = enumerate_process_children(pid)
    except Exception:  # noqa: BLE001
        return False
    return any(is_process_alive(k) for k in kids)


def terminate_process_tree(
    root_pid: int,
    *,
    children_fn: Optional[Callable[[int], List[int]]] = None,
    kill_fn: Optional[Callable[[int], bool]] = None,
    alive_fn: Optional[Callable[[int], bool]] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    now_fn: Callable[[], float] = time.monotonic,
    wait_sec: float = DEFAULT_TREE_KILL_WAIT_SEC,
    poll_interval: float = 0.2,
    max_depth: int = DEFAULT_TREE_MAX_DEPTH,
    logger: Optional[logging.Logger] = None,
) -> bool:
    """递归终止 root_pid 及其全部后代，随后轮询等待进程退出（句柄释放）。

    缺陷 D-1 的配套修复（D-1b）：onefile 下 `launch_detached` 返回 bootloader pid，
    真正持有 `MaLing.exe` 文件句柄的是它的子进程（应用本体）。只杀 bootloader 会
    让子进程成为孤儿并继续锁死 exe → 回滚 `rename(.old → exe)` WinError 5/32。
    因此：**先收集整棵树 → 叶子优先全杀 → 轮询确认全部退出（默认 ≤5s）**。

    返回 True = root（及已收集到的后代）均已退出；False = 超时仍有存活。
    注入点（children_fn/kill_fn/alive_fn/sleep_fn/now_fn）供单测替换，不真杀进程。
    """
    children_fn = children_fn or enumerate_process_children
    kill_fn = kill_fn or terminate_process
    alive_fn = alive_fn or is_process_alive
    try:
        root = int(root_pid)
    except (TypeError, ValueError):
        return True
    if root <= 0:
        return True

    # ① 广度优先收集整棵树（深度受限，去重防环）
    ordered: List[int] = []
    seen = {root}
    frontier = [root]
    for _ in range(max(0, int(max_depth))):
        nxt: List[int] = []
        for p in frontier:
            try:
                kids = list(children_fn(p))
            except Exception:  # noqa: BLE001
                kids = []
            for kid in kids:
                try:
                    kpi = int(kid)
                except (TypeError, ValueError):
                    continue
                if kpi > 0 and kpi not in seen:
                    seen.add(kpi)
                    nxt.append(kpi)
                    ordered.append(kpi)
        if not nxt:
            break
        frontier = nxt

    # ② 叶子优先全杀（BFS 逆序 = 深→浅），最后杀 root
    for pid in list(reversed(ordered)) + [root]:
        try:
            kill_fn(pid)
        except Exception as exc:  # noqa: BLE001 - 单个失败不阻断其余
            if logger:
                logger.warning("终止进程树 pid=%s 失败: %s", pid, exc)

    # ③ 轮询等待句柄释放（进程退出即释放）
    all_pids = ordered + [root]
    deadline = now_fn() + max(0.0, float(wait_sec))
    while True:
        if not any(_safe_alive(alive_fn, p) for p in all_pids):
            return True
        if now_fn() >= deadline:
            if logger:
                logger.error("进程树终止后仍有存活: %s", all_pids)
            return False
        sleep_fn(min(max(0.05, poll_interval), max(0.05, deadline - now_fn())))


def drain_install_dir_processes(
    install_dir: Any,
    timeout_sec: float,
    logger: Optional[logging.Logger] = None,
    *,
    enumerate_fn: Optional[Callable[[str], List[Tuple[int, str]]]] = None,
    kill_fn: Optional[Callable[[int], bool]] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    now_fn: Callable[[], float] = time.monotonic,
    poll_interval: float = 0.3,
) -> bool:
    """排空 image path 在 install_dir 下的残留进程：等待 → 超时 TerminateProcess。

    这是换包成败的硬闸（⚠-8）：只要一个 `node.exe` 活着持有句柄，
    `os.rename(install_dir, backup_dir)` 就 WinError 5/32，换包全盘失败。
    注入点（enumerate_fn/kill_fn/sleep_fn/now_fn）供测试替换，不真杀进程。
    """
    enumerate_fn = enumerate_fn or enumerate_processes_under
    kill_fn = kill_fn or terminate_process
    timeout_sec = max(0.0, float(timeout_sec))
    deadline = now_fn() + timeout_sec
    leftovers: List[Tuple[int, str]] = []
    while True:
        leftovers = list(enumerate_fn(str(install_dir)))
        if not leftovers:
            return True
        if now_fn() >= deadline:
            break
        sleep_fn(min(max(0.05, poll_interval), max(0.05, deadline - now_fn())))
    for pid, image in leftovers:
        if logger:
            logger.warning("残留进程超时强杀: pid=%s image=%s", pid, image)
        try:
            kill_fn(pid)
        except Exception as exc:  # noqa: BLE001 - 强杀失败不阻断后续流程
            if logger:
                logger.warning("强杀 pid=%s 失败: %s", pid, exc)
    sleep_fn(0.4)
    remaining = list(enumerate_fn(str(install_dir)))
    if remaining and logger:
        logger.error("强杀后安装目录内仍有残留进程: %s", remaining)
    return not remaining


def launch_detached(exe_path: Any, cwd: Any = None) -> int:
    """DETACHED_PROCESS + CREATE_NO_WINDOW 拉起进程（主进程退出后 sidecar 存活）。

    **返回值语义（缺陷 D-1 关键）**：返回的是 `Popen.pid`，即**我们直接创建的那个进程**。
      * onedir：就是应用本体 pid，`confirmed.json` 会带同一个 pid → 自身相等即认账；
      * onefile：是 **bootloader** pid；应用本体是它的子进程，且 `confirmed.json` 由
        应用本体写、带的是**本体 pid**（≠ 返回值）。因此调用方**不能**只做 pid 相等判定，
        必须同时接受「后代 pid」（见 `is_confirmed` / `is_descendant`），
        回滚时也必须按**整棵进程树**终止（`terminate_process_tree`）。
    """
    flags = 0
    if os.name == "nt":
        flags = DETACHED_PROCESS | CREATE_NO_WINDOW
    proc = subprocess.Popen(
        [os.fspath(exe_path)],
        cwd=os.fspath(cwd) if cwd else None,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=flags,
    )
    return int(proc.pid)


# ----------------------------------------------------------------------------
# 同卷校验（D-V20-02 同卷铁律）
# ----------------------------------------------------------------------------
def check_same_volume(paths: Sequence[Any]) -> Tuple[bool, str]:
    """校验全部路径同卷（盘符 + 卷序列），禁止偷偷退化为跨卷复制。"""
    infos: List[Tuple[str, str, Any]] = []
    for p in paths:
        target = os.path.abspath(os.fspath(p))
        probe = target
        while not os.path.exists(_win_long(probe)) and \
                os.path.dirname(probe) != probe:
            probe = os.path.dirname(probe)
        dev = None
        try:
            dev = os.stat(_win_long(probe)).st_dev
        except OSError:
            dev = None
        drive = os.path.splitdrive(target)[0].lower()
        infos.append((target, drive, dev))
    drives = {i[1] for i in infos}
    if len(drives) > 1:
        return False, f"盘符不一致: {[(i[0], i[1]) for i in infos]}"
    devs = {i[2] for i in infos if i[2] is not None}
    if len(devs) > 1:
        return False, f"卷序列不一致: {[(i[0], i[2]) for i in infos]}"
    return True, "same-volume ok"


# ----------------------------------------------------------------------------
# 解压 / 校验（D-V20-02 ②）
# ----------------------------------------------------------------------------
def _detect_top_prefix(names: Sequence[str]) -> str:
    """探测 zip 顶层单一目录（命名规范 Q-U2：包内顶层为 `maling/`）。

    若全部条目共享唯一顶层目录（无顶层散文件）→ 返回 "maling/"，解压时下沉一层；
    否则返回 ""（保持原样）。这是「约定未定时的兼容探测」。
    """
    tops = set()
    has_root_file = False
    for raw in names:
        name = raw.replace("\\", "/")
        if not name or name.endswith("/"):
            # 目录条目（如 "maling/"）不计入顶层判定
            seg = name.rstrip("/").split("/", 1)
            if len(seg) == 1 and seg[0]:
                # 单独一个目录条目，视为潜在顶层，但不作为散文件
                tops.add(seg[0])
            continue
        seg = name.split("/", 1)
        if len(seg) == 1:
            has_root_file = True
        else:
            tops.add(seg[0])
    if not has_root_file and len(tops) == 1:
        return next(iter(tops)) + "/"
    return ""


def extract_zip_package(zip_path: Any, staging_dir: Any,
                        logger: Optional[logging.Logger] = None) -> str:
    """把 zip 解压到 staging_dir（同卷），自动下沉顶层单目录，长路径 + zip-slip 防护。"""
    dest = os.path.abspath(os.fspath(staging_dir))
    if os.path.exists(_win_long(dest)):
        raise UpdaterError(EXIT_PRECONDITION, f"staging 目录已存在，拒绝覆盖: {dest}")
    try:
        zf = zipfile.ZipFile(_win_long(zip_path))
    except (OSError, zipfile.BadZipFile) as exc:
        raise UpdaterError(EXIT_PRECONDITION, f"包不可读（非 zip？）: {exc}")
    with zf:
        names = zf.namelist()
        prefix = _detect_top_prefix(names)
        if logger:
            logger.info("解压包: 顶层前缀=%r，条目数=%d", prefix or "(无)", len(names))
        os.makedirs(_win_long(dest), exist_ok=True)
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if not name:
                continue
            if prefix:
                if name == prefix:
                    continue
                if not name.startswith(prefix):
                    continue
                rel = name[len(prefix):]
            else:
                rel = name
            rel = rel.lstrip("/")
            parts = [seg for seg in rel.split("/") if seg not in ("", ".")]
            if not parts:
                continue
            if any(seg == ".." for seg in parts):
                raise UpdaterError(EXIT_PRECONDITION, f"包内非法路径（zip-slip）: {info.filename}")
            out = os.path.join(dest, *parts)
            if info.is_dir():
                os.makedirs(_win_long(out), exist_ok=True)
                continue
            parent = os.path.dirname(out)
            if parent:
                os.makedirs(_win_long(parent), exist_ok=True)
            try:
                with zf.open(info) as src, open(_win_long(out), "wb") as dst:
                    shutil.copyfileobj(src, dst, DEFAULT_SHA_CHUNK)
            except OSError as exc:
                raise UpdaterError(EXIT_PRECONDITION, f"解压写入失败: {out}: {exc}")
    return dest


def validate_staged_install(staging_dir: Any, action: str) -> Tuple[bool, str]:
    """校验解压产物完整（D-V20-02 ①）。

    基础哨兵 = `maling.exe` 存在 + `_internal/` 目录存在（对齐 dist_v190f/maling/ 实际形态）；
    版本哨兵（`_internal/version.json` 与 target 一致）由 check_staged_version 另行把关。
    """
    root = os.path.abspath(os.fspath(staging_dir))
    exe = os.path.join(root, APP_EXE_NAME)
    if not os.path.isfile(_win_long(exe)):
        return False, f"解压产物缺少 {APP_EXE_NAME}"
    if action == ACTION_SWAP_ONEDIR:
        internal = os.path.join(root, INTERNAL_DIR_NAME)
        if not os.path.isdir(_win_long(internal)):
            return False, f"解压产物缺少 {INTERNAL_DIR_NAME}/ 目录"
    return True, "ok"


def read_packaged_version(version_json_path: Any) -> Optional[str]:
    """从 version.json 读 `version` 字段；缺失/损坏/无字段 → None（不抛异常）。"""
    try:
        with open(_win_long(version_json_path), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    version = data.get("version")
    if version in (None, ""):
        return None
    return str(version)


def check_staged_version(staging_dir: Any, target_version: str) -> Tuple[Optional[bool], str]:
    """就位阶段版本哨兵（V20-10 加固）：断言包内版本 == plan.target_version。

    sha256 只能证明"包没坏"，版本校验才能证明"包是对的那一版"（R-M 绝不装错包）。
    返回 (判定, 说明)：
      True  → 版本一致，通过；
      False → 存在但版本不符 → 调用方应退出 6 且不碰安装目录；
      None  → version.json 缺失/不可读 → **回退**到基础哨兵（不拒绝升级，向后兼容）。
    """
    vpath = os.path.join(os.path.abspath(os.fspath(staging_dir)),
                         INTERNAL_DIR_NAME, "version.json")
    if not os.path.isfile(_win_long(vpath)):
        return None, f"未随包分发 {INTERNAL_DIR_NAME}/version.json，回退基础哨兵"
    got = read_packaged_version(vpath)
    if not got:
        return None, f"{INTERNAL_DIR_NAME}/version.json 不可解析或无 version 字段，回退基础哨兵"
    if got != str(target_version):
        return False, f"包内版本({got}) != target_version({target_version})"
    return True, f"包内版本 == {target_version}"


def check_package_version_zip(zip_path: Any, target_version: str) -> Tuple[Optional[bool], str]:
    """从 zip 包（未解压）内查 `version.json` 做版本哨兵（onefile 走 zip 形态时用）。

    找不到条目 → None（回退）；找到但版本不符 → False。非 zip / 读取失败 → None。
    """
    try:
        if not zipfile.is_zipfile(_win_long(zip_path)):
            return None, "包非 zip，跳过版本哨兵"
        with zipfile.ZipFile(_win_long(zip_path)) as zf:
            names = [n.replace("\\", "/") for n in zf.namelist()]
            cand = next((n for n in names
                         if n.endswith(f"{INTERNAL_DIR_NAME}/version.json")), None)
            if cand is None:
                cand = next((n for n in names if n.endswith("version.json")), None)
            if cand is None:
                return None, "zip 内无 version.json，回退基础哨兵"
            raw = zf.read(cand).decode("utf-8", errors="replace")
            data = json.loads(raw)
            got = str(data.get("version")) if isinstance(data, dict) and data.get("version") else ""
            if not got:
                return None, "zip 内 version.json 无 version 字段，回退基础哨兵"
            if got != str(target_version):
                return False, f"包内版本({got}) != target_version({target_version})"
            return True, f"包内版本 == {target_version}"
    except Exception:  # noqa: BLE001 - 版本哨兵失败一律回退，不影响主流程
        return None, "zip 版本哨兵读取失败，回退基础哨兵"


# ----------------------------------------------------------------------------
# 回调文件（§4.5 / D-V20-04）
# ----------------------------------------------------------------------------
def _atomic_write_json(path: Any, payload: Dict[str, Any]) -> None:
    full = os.path.abspath(os.fspath(path))
    parent = os.path.dirname(full)
    if parent:
        os.makedirs(_win_long(parent), exist_ok=True)
    tmp = full + ".tmp"
    with open(_win_long(tmp), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(_win_long(tmp), _win_long(full))


def _pid_eq(a: Any, b: Any) -> bool:
    try:
        return int(a) == int(b)
    except (TypeError, ValueError):
        return False


def write_pending_confirm(confirm_dir: Any, version: str, pid: int,
                          from_version: str) -> Path:
    path = os.path.join(os.path.abspath(os.fspath(confirm_dir)), PENDING_CONFIRM_NAME)
    _atomic_write_json(path, {
        "version": str(version), "pid": int(pid),
        "from_version": str(from_version), "at": _now_iso(),
    })
    return Path(path)


def write_confirmed(confirm_dir: Any, version: str, pid: int) -> Path:
    """新版主进程 UI 就绪后调用（供域4接线；sidecar 只读它）。"""
    path = os.path.join(os.path.abspath(os.fspath(confirm_dir)), CONFIRMED_NAME)
    _atomic_write_json(path, {
        "version": str(version), "pid": int(pid), "at": _now_iso(),
    })
    return Path(path)


def clear_stale_confirm(confirm_dir: Any) -> None:
    """清掉上一轮残留的 confirmed.json（防误认账）。"""
    _try_remove(os.path.join(os.path.abspath(os.fspath(confirm_dir)), CONFIRMED_NAME))


def is_confirmed(confirm_dir: Any, version: str, pid: int, *,
                 is_desc_fn: Optional[Callable[[Any, Any], bool]] = None) -> bool:
    """confirmed.json 的 version 一致，且 pid 为「自身或后代」才认账（D-V20-04 / D-1）。

    * 版本必须严格一致（防误认旧版或错包）；
    * pid 判定放宽为 **自身相等 或 后代**：onefile 下 `launch_detached` 返回 bootloader
      pid，而 confirmed.json 带的是应用本体（bootloader 的子进程）pid，只有接受后代
      才不会把一次成功更新误判为超时并回滚（缺陷 D-1）。
    * `is_desc_fn` 可注入（单测不碰真实进程表）。
    """
    path = os.path.join(os.path.abspath(os.fspath(confirm_dir)), CONFIRMED_NAME)
    try:
        with open(_win_long(path), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    if str(data.get("version")) != str(version):
        return False
    confirmed_pid = data.get("pid")
    if _pid_eq(confirmed_pid, pid):
        return True
    desc_fn = is_desc_fn or is_descendant
    try:
        return bool(desc_fn(confirmed_pid, pid))
    except Exception:  # noqa: BLE001 - 后代查询失败 → 不认账（保守）
        return False


def poll_confirm(
    confirm_dir: Any,
    version: str,
    pid: int,
    timeout_sec: float,
    *,
    alive_fn: Optional[Callable[[int], bool]] = None,
    is_desc_fn: Optional[Callable[[Any, Any], bool]] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    now_fn: Callable[[], float] = time.monotonic,
    poll_interval: float = 0.5,
) -> str:
    """三重判定（D-V20-04）：确认优先 → 超时兜底 → 存活快速失败。

    返回 "success" / "failed"（新版在写 confirmed 前就退出）/ "timeout"。

    存活探测默认用 `_pid_tree_alive`（pid 或其后代任一存活），避免 onefile 下
    bootloader 已退出、应用本体仍在写确认时被误判为 "failed"（缺陷 D-1 加固）。
    """
    alive_fn = alive_fn or _pid_tree_alive
    timeout_sec = max(0.0, float(timeout_sec))
    deadline = now_fn() + timeout_sec
    while True:
        if is_confirmed(confirm_dir, version, pid, is_desc_fn=is_desc_fn):
            return "success"
        if now_fn() >= deadline:
            return "timeout"
        if not alive_fn(pid):
            return "failed"
        sleep_fn(min(max(0.05, poll_interval), max(0.05, deadline - now_fn())))


def write_last_result(confirm_dir: Any, payload: Dict[str, Any]) -> Path:
    path = os.path.join(os.path.abspath(os.fspath(confirm_dir)), LAST_RESULT_NAME)
    _atomic_write_json(path, payload)
    return Path(path)


def consume_last_result(confirm_dir: Any) -> Optional[Dict[str, Any]]:
    """读后删 last_result.json（供新/旧版主进程启动早期消费，D-V20-04/§4.5）。

    返回 dict；无文件/损坏 → None（损坏文件也会被删除，避免长期卡住）。
    """
    path = os.path.join(os.path.abspath(os.fspath(confirm_dir)), LAST_RESULT_NAME)
    if not os.path.exists(_win_long(path)):
        return None
    data: Optional[Dict[str, Any]] = None
    try:
        with open(_win_long(path), "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, ValueError):
        data = None
    _try_remove(path)
    return data


def purge_old_files(exe_path: Any) -> bool:
    """清理 onefile 换包遗留的 `<exe>.old`（供新版启动早期调用，D-V20-03 ③）。"""
    old = os.fspath(exe_path) + ".old"
    return _try_remove(old)


# ----------------------------------------------------------------------------
# 自举：把内嵌 sidecar 复制到 %APPDATA%/maid_coder/updater/（D-V20-08）
# ----------------------------------------------------------------------------
def _is_under_updates(path: Any) -> bool:
    parts = [p.lower() for p in os.path.normpath(os.path.abspath(os.fspath(path))).split(os.sep)]
    return "updates" in parts


def _sha256_file(path: Any) -> str:
    h = hashlib.sha256()
    with open(_win_long(path), "rb") as f:
        while True:
            block = f.read(DEFAULT_SHA_CHUNK)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def ensure_self_installed(src_dir: Any, dest_dir: Any) -> Path:
    """自举：把主包内嵌的 sidecar 复制到持久目录（幂等）。

    契约（供主进程启动早期接线调用）：
      * src_dir/maling_updater.exe  →  dest_dir/maling_updater.exe
      * 目标已存在且 **大小 + sha256 一致** → 跳过（不改 mtime，幂等）；
      * 内容不一致 → 原子覆盖（`os.replace`），实现"版本升级则覆盖"；
      * dest_dir 落在 `updates/` 下 → 拒绝复制（会被「清理更新缓存」删掉，D-V20-01）；
      * src 缺失 / 复制失败 → 记日志并返回目标路径（**不抛异常、不阻断启动**，R-N）。

    返回目标 exe 路径（`dest_dir/maling_updater.exe`）。调用方需自行判定 `exists()`。
    """
    logger = logging.getLogger(_LOGGER_NAME)
    src = os.path.join(os.path.abspath(os.fspath(src_dir)), "maling_updater.exe")
    dest_folder = os.path.abspath(os.fspath(dest_dir))
    dest = os.path.join(dest_folder, "maling_updater.exe")
    if _is_under_updates(dest_folder):
        logger.error("自举被拒：目标落在 updates/ 下（会被清理缓存删除）: %s", dest_folder)
        return Path(dest)
    if not os.path.isfile(_win_long(src)):
        logger.warning("自举跳过：内嵌 sidecar 不存在: %s", src)
        return Path(dest)
    try:
        if os.path.isfile(_win_long(dest)):
            try:
                if os.path.getsize(_win_long(src)) == os.path.getsize(_win_long(dest)) \
                        and _sha256_file(src) == _sha256_file(dest):
                    logger.info("自举：目标已是最新（大小+sha 一致），跳过")
                    return Path(dest)
            except OSError:
                pass
        os.makedirs(_win_long(dest_folder), exist_ok=True)
        tmp = dest + ".tmp"
        shutil.copyfile(_win_long(src), _win_long(tmp))
        os.replace(_win_long(tmp), _win_long(dest))
        logger.info("自举：已更新 sidecar → %s", dest)
        return Path(dest)
    except Exception as exc:  # noqa: BLE001 - 自举失败不阻断（R-N）
        logger.warning("自举复制失败（不阻断启动）: %s", exc)
        return Path(dest)


# ----------------------------------------------------------------------------
# 换包：onedir rename-swap（D-V20-02 7 步 + 回滚）
# ----------------------------------------------------------------------------
def _exe_for_install_dir(install_dir: Any, app_exe: str = "") -> str:
    name = os.path.basename(app_exe) if app_exe else APP_EXE_NAME
    if not name:
        name = APP_EXE_NAME
    candidate = os.path.join(os.path.abspath(os.fspath(install_dir)), name)
    if os.path.isfile(_win_long(candidate)):
        return candidate
    return os.path.join(os.path.abspath(os.fspath(install_dir)), APP_EXE_NAME)


def _unique_path(path: Any) -> str:
    base = os.path.abspath(os.fspath(path))
    if not os.path.exists(_win_long(base)):
        return base
    stamp = time.strftime("%Y%m%d%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"
    return f"{base}_stale_{stamp}"


def _pre_swap_wait_and_drain(plan: Plan, logger: logging.Logger,
                             drain_target: Optional[str] = None) -> None:
    """换包前置硬闸：等主进程退出 + 排空目标范围内残留进程（D-V20-02 ③）。

    drain_target：onedir 传 install_dir（整目录会被 rename，任何活着的子进程都锁目录）；
    onefile 只传目标 exe 路径（避免误杀同目录里的无关进程，守 R-N 不伤用户环境）。
    """
    timeout = plan.kill_timeout_sec
    if plan.app_pid:
        exited = wait_for_pid_exit(plan.app_pid, timeout)
        if not exited:
            logger.warning("主进程 pid=%s 在 %ss 内未退出，强制结束", plan.app_pid, timeout)
            terminate_process(plan.app_pid)
            time.sleep(0.5)
    target = drain_target or plan.install_dir
    ok = drain_install_dir_processes(target, timeout, logger)
    if not ok:
        raise UpdaterError(
            EXIT_PRECONDITION,
            f"目标范围内仍有残留进程无法排空（典型元凶 _internal/pi_runtime/node.exe）: "
            f"{target}")


def swap_onedir(plan: Plan, logger: logging.Logger) -> Dict[str, Any]:
    """onedir 整目录 rename-swap（§2 D-V20-02 7 步）。

    返回 last_result 载荷；不抛异常（除前置校验外）。任一步失败 → 回滚点见注释。
    """
    install_dir = os.path.abspath(plan.install_dir)
    install_parent = os.path.abspath(plan.install_parent)
    staging = os.path.abspath(plan.staging_dir)
    backup = os.path.abspath(plan.backup_dir)
    result: Dict[str, Any] = {
        "version": plan.target_version,
        "from_version": plan.from_version,
        "backup_path": backup,
        "at": _now_iso(),
        "detail": "",
    }

    # ① 前置校验：同卷（源/目标必须同卷，禁止退化为跨卷复制）
    same, why = check_same_volume([install_parent, install_dir, staging, backup])
    if not same:
        raise UpdaterError(EXIT_PRECONDITION, f"同卷校验失败，拒绝换包: {why}")

    # ①b 包 sha256 复核（R-M：不符绝不就位）
    if not verify_sha256(plan.package_path, plan.package_sha256):
        raise UpdaterError(EXIT_PRECONDITION,
                           f"包 sha256 不符（R-M 拒绝就位）: {plan.package_path}")

    # ② 就位准备：解压到 staging（同卷）
    if os.path.exists(_win_long(staging)):
        logger.warning("staging 已存在，先清理: %s", staging)
        if not _safe_rmtree(staging):
            raise UpdaterError(EXIT_PRECONDITION, f"无法清理旧 staging: {staging}")
    if os.path.exists(_win_long(backup)):
        # 备份目标已存在会让 ④ rename 失败；改名为 stale 保留（同卷 rename，原子）
        stale = _unique_path(backup)
        try:
            _rename(backup, stale)
            logger.warning("旧备份已改名保留: %s → %s", backup, stale)
        except OSError as exc:
            raise UpdaterError(EXIT_PRECONDITION, f"旧备份无法让位: {exc}")
    extract_zip_package(plan.package_path, staging, logger)
    ok, reason = validate_staged_install(staging, ACTION_SWAP_ONEDIR)
    if not ok:
        _safe_rmtree(staging)  # 清理解压残骸（install_dir 原样未动）
        raise UpdaterError(EXIT_PRECONDITION, f"解压产物不完整: {reason}")

    # ②b 版本哨兵（V20-10 加固 / R-M 绝不装错包）：仍在 staging 阶段 → 不动安装目录
    version_ok, version_reason = check_staged_version(staging, plan.target_version)
    if version_ok is False:
        _safe_rmtree(staging)
        raise UpdaterError(EXIT_PRECONDITION, f"包版本不符，拒绝就位: {version_reason}")
    if version_ok is None:
        logger.warning("版本哨兵回退（基础哨兵已通过）: %s", version_reason)
    else:
        logger.info("版本哨兵通过: %s", version_reason)

    # ③ 进程排空
    _pre_swap_wait_and_drain(plan, logger)

    # ④ 原子边界：旧目录瞬间让位（失败 → 无需回滚，install_dir 仍在原位）
    try:
        _rename(install_dir, backup)
        logger.info("④ rename 旧目录 → 备份: %s → %s", install_dir, backup)
    except OSError as exc:
        logger.error("④ rename 旧目录失败（旧版保持原位，无需回滚）: %s", exc)
        _safe_rmtree(staging)
        result["result"] = "failed"
        result["detail"] = f"step4_rename_install_failed: {exc}"
        return result

    # ⑤ 新目录就位（失败 → rename 旧目录回来）
    try:
        _rename(staging, install_dir)
        logger.info("⑤ rename 新目录就位: %s → %s", staging, install_dir)
    except OSError as exc:
        logger.error("⑤ rename 新目录失败，回滚 ④: %s", exc)
        _safe_rmtree(staging)
        try:
            _rename(backup, install_dir)
            logger.info("⑤ 回滚成功：旧目录已归位")
        except OSError as exc2:
            logger.critical("⑤ 回滚 rename 失败（需人工介入）: %s", exc2)
            result["detail"] = f"step5_rollback_failed: {exc2}"
        result["result"] = "failed"
        result["detail"] = result["detail"] or f"step5_rename_staging_failed: {exc}"
        return result

    # ⑥ 拉起新版 exe + 写 pending_confirm
    exe = _exe_for_install_dir(install_dir, plan.app_exe)
    try:
        clear_stale_confirm(plan.confirm_dir)
        new_pid = launch_detached(exe, install_dir)
        logger.info("⑥ 拉起新版: %s pid=%s", exe, new_pid)
    except Exception as exc:  # noqa: BLE001 - 拉起异常统一走回滚
        new_pid = 0
        logger.error("⑥ 拉起新版失败: %s", exc)
    if new_pid:
        try:
            write_pending_confirm(plan.confirm_dir, plan.target_version, new_pid,
                                  plan.from_version)
        except Exception as exc:  # noqa: BLE001
            logger.warning("写 pending_confirm 失败: %s", exc)
        verdict = poll_confirm(plan.confirm_dir, plan.target_version, new_pid,
                               plan.confirm_timeout_sec)
        logger.info("⑦ 三重判定结果: %s", verdict)
    else:
        verdict = "failed"

    # ⑦/⑧ 成功 → 保留备份（D-V20-13 保留 1 版）后返回
    if verdict == "success":
        result["result"] = "success"
        result["detail"] = "confirmed"
        return result

    # ⑧ 回滚：kill 新版 → 移开坏目录 → 备份归位 → 拉起旧版
    logger.warning("⑦ 判定失败(%s)，进入回滚 ⑧", verdict)
    if new_pid:
        # D-1b：按整棵进程树终止（onefile bootloader + 应用本体；onedir 本体 + node.exe），
        # 并等待句柄释放，否则接下来的 rename 归位会被残留进程锁死（WinError 5/32）。
        terminate_process_tree(new_pid, logger=logger)
    failed_dir = _unique_path(os.path.join(
        install_parent, FAILED_NAME_FMT.format(ver=plan.target_version)))
    try:
        _rename(install_dir, failed_dir)
        _rename(backup, install_dir)
        logger.info("⑧ 回滚完成：坏目录移开 %s，旧目录归位 %s", failed_dir, install_dir)
        try:
            old_exe = _exe_for_install_dir(install_dir, plan.app_exe)
            old_pid = launch_detached(old_exe, install_dir)
            logger.info("⑧ 已重新拉起旧版 pid=%s", old_pid)
        except Exception as exc:  # noqa: BLE001 - 拉起旧版失败不改写"已回滚"事实
            logger.error("⑧ 重新拉起旧版失败: %s", exc)
        result["result"] = "rolled_back"
        result["detail"] = f"verdict={verdict}"
    except OSError as exc:
        logger.critical("⑧ 回滚 rename 失败（旧版仍在备份目录，需人工介入）: %s", exc)
        result["result"] = "failed"
        result["detail"] = f"rollback_failed: {exc}"
    return result


# ----------------------------------------------------------------------------
# 换包：onefile 改名换 exe（D-V20-03）
# ----------------------------------------------------------------------------
def _copy_with_retry(src: Any, dst: Any, logger: logging.Logger,
                     backoff: Sequence[float] = _COPY_RETRY_BACKOFF,
                     sleep_fn: Callable[[float], None] = time.sleep) -> None:
    """复制并覆盖目标；被占用时按 1s/3s/7s 指数退避重试；仍失败抛 OSError。"""
    attempts = (0.0,) + tuple(backoff)
    last: Optional[Exception] = None
    for idx, delay in enumerate(attempts):
        if delay:
            logger.warning("写入被拒，%.0fs 后重试（第 %d 次）", delay, idx)
            sleep_fn(delay)
        try:
            tmp = os.fspath(dst) + ".tmp"
            shutil.copyfile(_win_long(src), _win_long(tmp))
            os.replace(_win_long(tmp), _win_long(dst))
            return
        except OSError as exc:
            last = exc
            _try_remove(os.fspath(dst) + ".tmp")
    raise last if last else OSError("copy failed")


def swap_onefile(plan: Plan, logger: logging.Logger) -> Dict[str, Any]:
    """onefile 换法：旧 exe→.old → 写新 exe → 拉起 → 三重判定 → 失败回滚。"""
    current_exe = os.path.abspath(plan.app_exe)
    package = os.path.abspath(plan.package_path)
    result: Dict[str, Any] = {
        "version": plan.target_version,
        "from_version": plan.from_version,
        "backup_path": current_exe + ".old",
        "at": _now_iso(),
        "detail": "",
    }
    if not os.path.isfile(_win_long(current_exe)):
        raise UpdaterError(EXIT_PRECONDITION, f"当前 exe 不存在: {current_exe}")
    # 包 sha256 复核（R-M）
    if not verify_sha256(package, plan.package_sha256):
        raise UpdaterError(EXIT_PRECONDITION,
                           f"包 sha256 不符（R-M 拒绝就位）: {package}")

    # 版本哨兵：onefile 包通常是 .exe（无法内查版本）→ 跳过；仅当包为 .zip 形态时按 zip 内查
    if package.lower().endswith(".zip"):
        v_ok, v_reason = check_package_version_zip(package, plan.target_version)
        if v_ok is False:
            raise UpdaterError(EXIT_PRECONDITION, f"包版本不符，拒绝就位: {v_reason}")
        if v_ok is None:
            logger.warning("版本哨兵回退: %s", v_reason)
        else:
            logger.info("版本哨兵通过: %s", v_reason)
    else:
        logger.info("版本哨兵跳过：onefile 包非 zip 形态（%s）", os.path.basename(package))

    # ③ 进程排空（onefile 无目录锁，只排空目标 exe 自身的残留实例，不误杀同目录无关进程）
    _pre_swap_wait_and_drain(plan, logger, drain_target=current_exe)

    old_path = current_exe + ".old"
    # ① 旧 exe 改名（Windows 运行中 exe 可改名）。旧 .old 存在则尝试清理。
    if os.path.exists(_win_long(old_path)) and not purge_old_files(current_exe):
        logger.warning("旧 .old 无法清理（仍被占用），尝试改名保留")
        try:
            _rename(old_path, _unique_path(old_path))
        except OSError as exc:
            logger.warning("旧 .old 改名失败（忽略）: %s", exc)
    try:
        _rename(current_exe, old_path)
        logger.info("① 旧 exe 改名: %s → %s", current_exe, old_path)
    except OSError as exc:
        result["result"] = "failed"
        result["detail"] = f"step1_rename_exe_failed: {exc}"
        logger.error("① 旧 exe 改名失败（旧版未动）: %s", exc)
        return result

    # ② 写入新 exe（占用 → 重试 → 仍失败 → 回滚）
    try:
        _copy_with_retry(package, current_exe, logger)
        logger.info("② 新 exe 已写入: %s", current_exe)
    except OSError as exc:
        logger.error("② 写入新 exe 失败，回滚: %s", exc)
        try:
            _rename(old_path, current_exe)
            logger.info("② 回滚成功：旧 exe 已归位")
        except OSError as exc2:
            logger.critical("② 回滚 rename 失败（需人工介入）: %s", exc2)
        result["result"] = "failed"
        result["detail"] = f"step2_write_exe_failed: {exc}"
        return result

    # ③ 拉起新版 + 写 pending_confirm
    try:
        clear_stale_confirm(plan.confirm_dir)
        new_pid = launch_detached(current_exe, os.path.dirname(current_exe))
        logger.info("③ 拉起新版: %s pid=%s", current_exe, new_pid)
    except Exception as exc:  # noqa: BLE001
        new_pid = 0
        logger.error("③ 拉起新版失败: %s", exc)
    if new_pid:
        try:
            write_pending_confirm(plan.confirm_dir, plan.target_version, new_pid,
                                  plan.from_version)
        except Exception as exc:  # noqa: BLE001
            logger.warning("写 pending_confirm 失败: %s", exc)
        verdict = poll_confirm(plan.confirm_dir, plan.target_version, new_pid,
                               plan.confirm_timeout_sec)
        logger.info("三重判定结果: %s", verdict)
    else:
        verdict = "failed"

    if verdict == "success":
        result["result"] = "success"
        result["detail"] = "confirmed（.old 留待下次启动清理）"
        return result

    # ④ 回滚：kill 新版 → .old 归位 → 拉起旧版
    logger.warning("判定失败(%s)，回滚 onefile", verdict)
    if new_pid:
        # D-1b：onefile 必须整树终止——只杀 bootloader 会留下仍在锁 exe 的应用本体，
        # 导致下面的 rename(.old → exe) 失败；终止后轮询等待句柄释放再归位。
        terminate_process_tree(new_pid, logger=logger)
    try:
        if os.path.exists(_win_long(old_path)):
            _try_remove(current_exe)
            _rename(old_path, current_exe)
            logger.info("④ 回滚完成：旧 exe 已归位")
            try:
                old_pid = launch_detached(current_exe, os.path.dirname(current_exe))
                logger.info("④ 已重新拉起旧版 pid=%s", old_pid)
            except Exception as exc:  # noqa: BLE001
                logger.error("④ 重新拉起旧版失败: %s", exc)
            result["result"] = "rolled_back"
            result["detail"] = f"verdict={verdict}"
        else:
            result["result"] = "failed"
            result["detail"] = f"rollback_no_backup: verdict={verdict}"
    except OSError as exc:
        logger.critical("④ 回滚失败（需人工介入）: %s", exc)
        result["result"] = "failed"
        result["detail"] = f"rollback_failed: {exc}"
    return result


# ----------------------------------------------------------------------------
# 编排入口
# ----------------------------------------------------------------------------
def _write_failure_result(plan: Optional[Plan], logger: logging.Logger,
                          detail: str) -> None:
    if plan is None:
        return
    try:
        write_last_result(plan.confirm_dir, {
            "version": plan.target_version,
            "from_version": plan.from_version,
            "result": "failed",
            "backup_path": plan.backup_dir,
            "at": _now_iso(),
            "detail": detail,
        })
    except Exception as exc:  # noqa: BLE001 - 结果文件写入失败不能掩盖主错误
        logger.error("写 last_result 失败: %s", exc)


def execute_plan(plan: Plan, logger: logging.Logger) -> int:
    """执行换包并写 last_result.json；返回退出码（成功 0 / 非成功 1）。"""
    try:
        if plan.action == ACTION_SWAP_ONEDIR:
            result = swap_onedir(plan, logger)
        else:
            result = swap_onefile(plan, logger)
    except UpdaterError as exc:
        logger.error("换包前置条件失败: %s", exc)
        _write_failure_result(plan, logger, f"precondition: {exc}")
        return exc.code
    except Exception as exc:  # noqa: BLE001 - 未捕获异常绝不静默吞掉
        logger.exception("换包未捕获异常")
        _write_failure_result(plan, logger, f"unexpected: {exc}")
        return EXIT_FAILED
    try:
        write_last_result(plan.confirm_dir, result)
    except Exception as exc:  # noqa: BLE001
        logger.error("写 last_result 失败: %s", exc)
    logger.info("换包结束: result=%s detail=%s",
                result.get("result"), result.get("detail"))
    return EXIT_OK if result.get("result") == "success" else EXIT_FAILED


# ----------------------------------------------------------------------------
# argv 契约与 main
# ----------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="maling_updater",
        description="码铃 v2.0 自动更新 sidecar（仅由主进程以 --pid/--plan/--log 拉起）",
    )
    parser.add_argument("--pid", type=int, default=0, help="待退出的主进程 PID")
    parser.add_argument("--plan", default="", help="plan.json 绝对路径（唯一输入）")
    parser.add_argument("--log", default="", help="日志文件路径")
    parser.add_argument("--version", action="store_true", help="打印 sidecar 版本后退出")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """sidecar 入口。返回退出码（见模块 docstring 的退出码表）。"""
    args_list = list(sys.argv[1:] if argv is None else argv)
    try:
        ns = _build_parser().parse_args(args_list)
    except SystemExit as exc:
        # argparse 对内建错误 exit(2)、-h exit(0)；统一转成返回值（不交互式运行）
        return int(exc.code) if isinstance(exc.code, int) else EXIT_BAD_ARGS

    if ns.version:
        print(UPDATER_VERSION)
        return EXIT_OK

    if not ns.pid or not ns.plan:
        # 无参 / 缺必填 → 拒绝运行（绝不交互式）
        return EXIT_BAD_ARGS

    log_path = ns.log or os.path.join(
        tempfile.gettempdir(), f"maling_updater_{os.getpid()}.log")
    logger = setup_logging(log_path)
    logger.info("sidecar 启动 version=%s argv_pid=%s plan=%s",
                UPDATER_VERSION, ns.pid, ns.plan)

    plan: Optional[Plan] = None
    try:
        plan = load_plan(ns.plan)
        plan.app_pid = int(ns.pid)

        # 自我保护（D-V20-01 生存铁律）：自身不得住在被替换目录内
        if not self_check_ok(sys.executable, plan.install_dir):
            logger.error("自我保护失败：sidecar(%s) 位于安装目录(%s)内，拒绝换包",
                         sys.executable, plan.install_dir)
            return EXIT_SELF_INSIDE

        # 前置：目标版本必须严格高于当前（D-V20-02 ①）
        if not is_newer(plan.target_version, plan.from_version):
            logger.error("前置校验失败：target(%s) 不高于 from(%s)",
                         plan.target_version, plan.from_version)
            _write_failure_result(plan, logger, "target_not_newer")
            return EXIT_PRECONDITION

        return execute_plan(plan, logger)
    except UpdaterError as exc:
        logger.error("plan/前置校验失败: %s", exc)
        _write_failure_result(plan, logger, f"updater_error: {exc}")
        return exc.code
    except Exception as exc:  # noqa: BLE001 - 未捕获异常必须写日志并不 0 退出
        logger.exception("sidecar 未捕获异常")
        _write_failure_result(plan, logger, f"unexpected: {exc}")
        return EXIT_FAILED
    finally:
        # 释放日志文件句柄（Windows 下不关闭会让日志文件/目录被占用）
        for handler in list(logger.handlers):
            try:
                handler.flush()
            except Exception:
                pass
            try:
                logger.removeHandler(handler)
                handler.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())