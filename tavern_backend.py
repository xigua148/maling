"""tavern_backend.py —— 内置 SillyTavern 子进程管理（v1.0）

复用项目已捆绑的 node.exe（``_internal/pi_runtime/node.exe``，v22.22.2），
启动 ``vendor/sillytavern/server.js``，监听本机 ``127.0.0.1:<port>``，
供 ``gui/pages/page_sillytavern.py`` 的 QWebEngineView 加载。

生命周期：``start() -> stop()``。崩溃不自动重启（ST 是 UI 服务，重启无意义，
让用户手动重开）。

相对施工方案 §6 骨架的实测修正（每条都是本机实测结论，不是推测）：

1. **node 定位候选顺序**：方案写的 ``dist/maling/_internal/pi_runtime/node.exe``
   在当前仓库并不存在，实际位置是仓库根的 ``_internal/pi_runtime/node.exe``。
2. **必须注入 ``--require maling_node_compat.cjs``**：Node v22.22.2 的
   ``fs.cpSync`` 在非 ASCII 路径下递归复制目录会静默硬崩溃（退出码
   3221226505 / 3221225477）。ST 源码里有 12 处 ``fs.cpSync``，Python 侧绕不开，
   只能从 fs 层打补丁。详见 ``maling_node_compat.cjs`` 头部注释。
3. **必须带 ``--configPath``**：否则 ST 把 ``config.yaml`` 写到服务目录
   （打包后是 ``_internal/sillytavern/``，属程序文件区），违反方案 §4
   "用户数据一律落在 ``%APPDATA%\\maling\\sillytavern\\data``"。
4. **必须带 ``--browserLaunchEnabled false``**：否则每次启动都会弹出系统浏览器。
5. **``STARTUP_TIMEOUT_S = 90``**：本机实测冷启动 31.2s / 49.7s，方案原值 30 秒
   必然误判失败（还会把已经起了一半的进程杀掉）。
6. **stdout 必须由独立线程持续消费**：ST 启动期日志量很大，管道写满会把子进程
   卡死。只在等待循环里读是不够的。
7. **无孤儿进程**：``terminate() -> wait(5) -> kill()``，Windows 下再加
   ``taskkill /F /T /PID`` 兜底确保整棵进程树退出。
"""
from __future__ import annotations

import collections
import ctypes
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger("maid_coder.tavern_backend")

# 冷启动实测 31.2s / 49.7s（首次含数据目录 migration）。方案原值 30s 会误判失败。
STARTUP_TIMEOUT_S = 90.0
PORT_POOL_START = 8754
PORT_POOL_END = 9000

# 就绪探测：先探 TCP，再探 HTTP
_READY_POLL_S = 0.3
_TCP_TIMEOUT_S = 0.5
_HTTP_TIMEOUT_S = 2.0

# 子进程输出的环形缓冲上限。
# 60 行只够"启动失败时给一段可读诊断"；但 ST 首启的 stdout 有 ~195 行（内容播种占大头），
# 60 行会把早期里程碑（``Node version:`` / 首个 ``Content file``）直接挤掉 ——
# 界面上的三段式进度（page_sillytavern.PROGRESS_STAGES）就再也匹配不到前两段。
_TAIL_LINES = 400

# 诊断文案里**展示**的行数（缓冲可以大，但塞给用户看的仍要克制）。
_DIAG_TAIL_LINES = 60

NODE_EXE_NAME = "node.exe"
NODE_COMPAT_NAME = "maling_node_compat.cjs"

# Windows NTSTATUS 崩溃码（有符号 Popen.returncode 需先 & 0xFFFFFFFF）
_CRASH_CODES = {
    3221226505: "0xC0000409 STACK_BUFFER_OVERRUN",
    3221225477: "0xC0000005 ACCESS_VIOLATION",
}

_CREATE_NO_WINDOW = 0x08000000


# ----------------------------------------------------------------------
# Windows Job Object：让 node 随本进程**任何形式**的死亡一起被系统回收
# ----------------------------------------------------------------------
# 页面自挂 / closeEvent / 托盘退出 / main.py 收口这四道清理都要求应用**走到**清理代码。
# 以下情形走不到，node 会变成孤儿进程并长期占着端口：
#   · 应用被强杀（任务管理器结束进程）或崩溃；
#   · **系统关机/注销时窗口处于最小化或已收进托盘**——实测：最小化状态下向主窗口发
#     WM_QUERYENDSESSION / WM_ENDSESSION 不会触发 Qt 的退出链（还原窗口后再发则 1 秒内
#     完整退出、零孤儿）。
# Job Object 的 KILL_ON_JOB_CLOSE 由**内核**保证：句柄关闭（含本进程崩溃/被杀）即终止
# Job 内所有进程。启用失败时静默降级，退回原有四道清理，不影响任何功能。
_JOB_HANDLE: Optional[int] = None
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", ctypes.c_ulong),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_ulong),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_ulong),
        ("SchedulingClass", ctypes.c_ulong),
    ]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def ensure_kill_on_close_job() -> Optional[int]:
    """创建 KILL_ON_JOB_CLOSE 的 Job 并把**当前进程**纳入，返回句柄（失败返回 None）。

    幂等：成功后缓存句柄并**一直持有**——句柄一旦关闭，Job 内所有进程立即被终止，
    这正是我们要的语义（本进程死亡 → node 一起被内核回收）。

    纳入当前进程（而非只纳入子进程）是关键：之后 ``subprocess.Popen`` 创建的子进程
    会自动继承 Job 成员身份，无需在每个创建点重复处理。
    """
    global _JOB_HANDLE
    if _JOB_HANDLE is not None or sys.platform != "win32":
        return _JOB_HANDLE
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = ctypes.c_void_p
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        # ⚠️ 以下签名**必须显式声明**（实测踩过）：不设 restype 时 ctypes 默认按 c_int
        # 返回，`GetCurrentProcess()` 的 64 位伪句柄 -1（0xFFFF…FF）会被截成 0xFFFFFFFF，
        # 于是 AssignProcessToJobObject 失败 → 整个增强被静默降级，Job 形同虚设。
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.GetCurrentProcess.argtypes = []
        k32.SetInformationJobObject.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint]
        k32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        job = k32.CreateJobObjectW(None, None)
        if not job:
            logger.debug("CreateJobObject 失败（降级）：%s", ctypes.get_last_error())
            return None
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(
                ctypes.c_void_p(job), _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(info), ctypes.sizeof(info)):
            logger.debug("SetInformationJobObject 失败（降级）：%s", ctypes.get_last_error())
            k32.CloseHandle(ctypes.c_void_p(job))
            return None
        if not k32.AssignProcessToJobObject(ctypes.c_void_p(job), k32.GetCurrentProcess()):
            # 已在不允许嵌套的 Job 中（受限环境/极旧系统）→ 静默降级
            logger.debug("AssignProcessToJobObject 失败（降级）：%s", ctypes.get_last_error())
            k32.CloseHandle(ctypes.c_void_p(job))
            return None
        _JOB_HANDLE = job            # 故意不释放：持有到本进程结束
        logger.info("已启用 Job Object：node 子进程将随本进程退出（含崩溃/强杀）被系统回收")
        return job
    except Exception:  # noqa: BLE001 - 纯增强项，任何异常都只降级
        logger.debug("Job Object 启用失败（降级为常规清理）", exc_info=True)
        return None


# ----------------------------------------------------------------------
# 路径定位
# ----------------------------------------------------------------------
def _here() -> Path:
    """本模块所在目录。

    开发态 = 仓库根；PyInstaller onedir 态 = ``<app>/_internal``
    （模块在 PYZ 里，``__file__`` 以 ``sys._MEIPASS`` 为基准）。
    """
    return Path(__file__).resolve().parent


def node_exe_candidates() -> List[Path]:
    """捆绑 node.exe 的候选位置（按优先序）。

    ①②③ 对应两种布局：
    - 开发态 ``here`` = 仓库根 → 命中 ① ``<repo>/_internal/pi_runtime/node.exe``
      （当前仓库的实际位置）；
    - 打包态 ``here`` = ``<app>/_internal`` → 命中 ② ``<app>/_internal/pi_runtime/node.exe``，
      ③ 是同一路径的防御性别名（``here.parent`` = ``<app>``）。
    """
    here = _here()
    return [
        here / "_internal" / "pi_runtime" / NODE_EXE_NAME,          # ① 开发态（当前实际位置）
        here / "pi_runtime" / NODE_EXE_NAME,                        # ② 打包态 / 开发态备用
        here.parent / "_internal" / "pi_runtime" / NODE_EXE_NAME,   # ③ 打包态兜底
    ]


def node_compat_candidates() -> List[Path]:
    """Node 兼容补丁的候选位置（按优先序）。"""
    here = _here()
    return [
        here / "_internal" / NODE_COMPAT_NAME,          # ① 打包态（datas 目标目录 '.'）
        here / NODE_COMPAT_NAME,                        # ② 开发态（仓库根）
        here.parent / "_internal" / NODE_COMPAT_NAME,   # ③ 打包态兜底
    ]


def st_dir_candidates() -> List[Path]:
    """内置 SillyTavern 源码目录的候选位置（按优先序）。"""
    here = _here()
    return [
        here / "_internal" / "sillytavern",         # ① 打包态（datas 目标目录 'sillytavern'）
        here / "sillytavern",                       # ② 打包态兜底
        here / "vendor" / "sillytavern",            # ③ 开发态
        here.parent / "_internal" / "sillytavern",  # ④ 打包态兜底
    ]


def find_bundled_node_exe() -> Optional[Path]:
    for p in node_exe_candidates():
        if p.is_file():
            return p
    return None


def find_node_compat() -> Optional[Path]:
    for p in node_compat_candidates():
        if p.is_file():
            return p
    return None


def find_bundled_st_dir() -> Optional[Path]:
    for p in st_dir_candidates():
        if (p / "server.js").is_file():
            return p
    return None


def _user_data_root() -> Path:
    """用户数据目录：``%APPDATA%\\maling\\sillytavern\\data``（方案 §4）。

    绝不写进 ``_internal/sillytavern/``（程序文件区，升级会被覆盖）。
    """
    base = os.environ.get("APPDATA") or str(Path.home())
    p = Path(base) / "maling" / "sillytavern" / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _find_free_port(start: int, end: int) -> int:
    """在 [start, end] 里找一个空闲端口（方案 §5）。"""
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"没有空闲端口（{start}-{end}）")


_NO_PROXY_OPENER: Optional[urllib.request.OpenerDirector] = None


def _no_proxy_opener() -> urllib.request.OpenerDirector:
    """返回一个**完全不走代理**的 opener（惰性创建并复用）。

    本机回环探测绝不能经过 ``HTTP_PROXY``。实测本机设了
    ``HTTP_PROXY=http://127.0.0.1:64558``，走代理会把"探测 127.0.0.1:8754"
    变成"让代理去连 127.0.0.1:8754"：代理不可用时会返回 502，于是把**未就绪
    误判成就绪**（`urlopen` 抛 `HTTPError` 502 → 旧代码直接 return True）。

    ``ProxyHandler({})`` 显式声明"无代理"，其优先级高于环境变量
    （`build_opener` 只在调用方未提供任何 ProxyHandler 子类时才注入默认的那个）。
    """
    global _NO_PROXY_OPENER
    if _NO_PROXY_OPENER is None:
        _NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return _NO_PROXY_OPENER


# ----------------------------------------------------------------------
# 后端
# ----------------------------------------------------------------------
class TavernBackend:
    """一个 SillyTavern node 子进程的完整生命周期管理。"""

    def __init__(self) -> None:
        self.proc: Optional[subprocess.Popen] = None
        self.port: Optional[int] = None
        self.base_url: Optional[str] = None
        self._tail: "collections.deque[str]" = collections.deque(maxlen=_TAIL_LINES)
        self._tail_lock = threading.Lock()
        self._reader: Optional[threading.Thread] = None

    # ---- 启动 ----
    def start(self) -> Tuple[int, str]:
        """启动 ST 并阻塞到 HTTP 就绪，返回 ``(port, base_url)``。

        失败时保证不留孤儿进程（内部先 stop() 再抛）。
        """
        if self.is_running():
            # 幂等：UI 上"重试启动"连点两次不应起两个 node
            assert self.port is not None and self.base_url is not None
            return self.port, self.base_url

        node_exe = find_bundled_node_exe()
        if node_exe is None:
            raise RuntimeError(
                "找不到捆绑的 node.exe。候选路径：\n  "
                + "\n  ".join(str(p) for p in node_exe_candidates())
                + "\n分发包应自带 _internal/pi_runtime/node.exe。")

        compat = find_node_compat()
        if compat is None:
            raise RuntimeError(
                f"找不到 Node 兼容补丁 {NODE_COMPAT_NAME}。候选路径：\n  "
                + "\n  ".join(str(p) for p in node_compat_candidates())
                + "\n该补丁用于绕开 Node 在非 ASCII 路径下 fs.cpSync 崩溃（nodejs/node#54476），"
                  "缺失会导致 SillyTavern 静默崩溃，必须随包分发。")

        st_dir = find_bundled_st_dir()
        if st_dir is None:
            raise RuntimeError(
                "找不到内置的 sillytavern 目录。候选路径：\n  "
                + "\n  ".join(str(p) for p in st_dir_candidates())
                + "\n应为 vendor/sillytavern（开发态）或 _internal/sillytavern（打包态）。")

        self.port = _find_free_port(PORT_POOL_START, PORT_POOL_END)
        data_root = _user_data_root()
        self.base_url = f"http://127.0.0.1:{self.port}/"

        cmd = [
            str(node_exe),
            "--require", str(compat),          # 必须：非 ASCII 路径下的 fs.cpSync 崩溃补丁
            "server.js",
            "--port", str(self.port),
            "--listen", "false",               # 只绑 127.0.0.1
            "--dataRoot", str(data_root),      # 用户数据落在 %APPDATA%
            "--configPath", str(data_root / "config.yaml"),  # 别把 config.yaml 写进 _internal/
            "--whitelist", "false",            # 只本机回环，不需要白名单
            "--browserLaunchEnabled", "false",  # 不弹系统浏览器
        ]
        logger.info("启动 SillyTavern: %s (cwd=%s)", cmd, st_dir)

        creationflags = _CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            with self._tail_lock:
                self._tail.clear()
            # 必须在 Popen **之前**：先保证本进程已纳入 KILL_ON_JOB_CLOSE 的 Job，
            # 之后创建的 node 才会随本进程任何形式的死亡被内核一并回收。
            ensure_kill_on_close_job()
            self.proc = subprocess.Popen(
                cmd,
                cwd=str(st_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
                # 不传 shell=True
            )
            # stdout 必须被持续消费，否则 ST 日志写满管道会卡死子进程（方案 §13）
            self._reader = threading.Thread(
                target=self._pump_stdout, name="sillytavern-stdout", daemon=True)
            self._reader.start()
            self._wait_ready()
        except BaseException:
            self.stop()          # 不留孤儿进程
            raise

        return self.port, self.base_url

    def _pump_stdout(self) -> None:
        """daemon 线程：持续消费子进程 stdout，避免管道写满；保留尾部供诊断。"""
        proc = self.proc
        if proc is None or proc.stdout is None:
            return
        stream = proc.stdout
        try:
            for raw in iter(stream.readline, b""):
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                with self._tail_lock:
                    self._tail.append(line)
                logger.debug("[sillytavern] %s", line)
        except Exception:
            logger.debug("SillyTavern stdout 读取线程异常结束", exc_info=True)
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _tail_text(self, lines: Optional[int] = None) -> str:
        """环形缓冲的文本快照；``lines`` 非空时只取最后若干行。"""
        with self._tail_lock:
            items = list(self._tail)
        if lines is not None:
            items = items[-int(lines):]
        return "\n".join(items)

    def _wait_ready(self) -> None:
        """等 ST 就绪：轮询进程存活 → TCP 端口 → HTTP 应答。"""
        proc = self.proc
        assert proc is not None and self.port is not None
        deadline = time.monotonic() + STARTUP_TIMEOUT_S
        tcp_ok = False

        while time.monotonic() < deadline:
            rc = proc.poll()
            if rc is not None:
                raise RuntimeError(self._format_early_exit(rc))

            if not tcp_ok:
                if self._port_open():
                    tcp_ok = True
                    logger.debug("SillyTavern TCP %s 已监听，等待 HTTP 就绪", self.port)
            elif self._http_ready():
                logger.info("SillyTavern 就绪: %s", self.base_url)
                return

            time.sleep(_READY_POLL_S)

        raise TimeoutError(
            f"SillyTavern {STARTUP_TIMEOUT_S:.0f}s 内未就绪"
            f"（tcp_listening={tcp_ok}）。"
            f"\n--- 子进程最后 {_DIAG_TAIL_LINES} 行输出 ---\n{self._tail_text(_DIAG_TAIL_LINES) or '(无输出)'}"
            f"\n--- 输出结束 ---")

    def _port_open(self) -> bool:
        assert self.port is not None
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=_TCP_TIMEOUT_S):
                return True
        except OSError:
            return False

    def _http_ready(self) -> bool:
        """ST 能应答 HTTP 且**不是服务端错误**即视为就绪。

        - 2xx / 3xx：正常就绪；
        - **4xx 也算就绪** —— 服务器已在应答、路由已挂上，只是该路径需要登录等；
        - **5xx 不算就绪**（服务端自身还没准备好，或代理返回 502），继续轮询直到超时。

        探测**不走代理**，见 `_no_proxy_opener()`。
        """
        assert self.base_url is not None
        try:
            with _no_proxy_opener().open(self.base_url, timeout=_HTTP_TIMEOUT_S) as resp:
                return 200 <= int(resp.status) < 500
        except urllib.error.HTTPError as e:
            # urlopen 对 4xx/5xx 抛 HTTPError：只有 4xx 才算"服务器已就绪"
            return 400 <= int(e.code) < 500
        except Exception:
            return False

    def _format_early_exit(self, rc: int) -> str:
        unsigned = rc & 0xFFFFFFFF
        hint = ""
        if unsigned in _CRASH_CODES:
            hint = (
                f"\n检测到 Node 进程被 NTSTATUS 异常终止"
                f"（退出码 {rc} / {unsigned} / {_CRASH_CODES[unsigned]}），且无任何错误输出。"
                "\n这正是 Node 在非 ASCII 路径下 fs.cpSync 递归复制目录时的已知崩溃"
                "（nodejs/node#54476）。"
                f"\n请确认启动命令里带上了 `--require <{NODE_COMPAT_NAME} 绝对路径>`，"
                "且该文件存在、可读 —— 即兼容补丁未生效。"
            )
        elif unsigned >= 0xC0000000:
            hint = (f"\n检测到 Node 进程异常终止"
                    f"（NTSTATUS 退出码 {unsigned} / 0x{unsigned:08X}）。")
        return (
            f"SillyTavern 启动失败，子进程提前退出（退出码 {rc}）。{hint}"
            f"\n--- 子进程最后 {_DIAG_TAIL_LINES} 行输出 ---\n{self._tail_text(_DIAG_TAIL_LINES) or '(无输出)'}"
            f"\n--- 输出结束 ---"
        )

    # ---- 停止 ----
    def stop(self) -> None:
        """停机：terminate → wait(5) → kill →（Windows）taskkill /F /T 兜底。幂等。"""
        proc = self.proc
        self.proc = None
        self.port = None
        self.base_url = None

        if proc is None or proc.poll() is not None:
            return

        logger.info("停止 SillyTavern (pid=%s)", proc.pid)
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.debug("SillyTavern 未在 5s 内响应 terminate，改用 kill")
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                logger.debug("SillyTavern kill 后仍未退出", exc_info=True)
        except Exception:
            logger.debug("SillyTavern terminate 异常", exc_info=True)

        if proc.poll() is None:
            self._taskkill_tree(proc.pid)

    @staticmethod
    def _taskkill_tree(pid: int) -> None:
        """Windows 兜底：强杀整棵进程树，确保不留孤儿。"""
        if sys.platform != "win32":
            return
        logger.warning("taskkill /F /T 兜底终止 SillyTavern 进程树 (pid=%s)", pid)
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, timeout=15,
                creationflags=_CREATE_NO_WINDOW,
            )
        except Exception:
            logger.debug("taskkill 兜底失败 (pid=%s)", pid, exc_info=True)

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    # ---- 诊断 ----
    def tail_output(self) -> str:
        """最近 ``_TAIL_LINES`` 行子进程输出（UI 上排障用）。"""
        return self._tail_text()
