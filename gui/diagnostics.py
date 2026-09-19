# -*- coding: utf-8 -*-
"""gui/diagnostics.py —— 诊断包一键导出（v2.2.5，尽量纯逻辑）。

============================ 为什么需要它 ============================

排障时最缺的从来不是"日志文件在哪"，而是**把散落各处的证据凑成一份能直接发出去的包**：
应用日志、内置酒馆的服务端输出、环境与路径、进程树、脱敏后的配置。

v2.2.3 内置酒馆验收就为此绕了几个弯：ST 的 stdout 由 ``tavern_backend`` 以
``logger.debug`` 记录，而文件 handler 是 INFO 级 —— 打包态**根本拿不到它的服务端输出**，
最后只能自己写脚本、用同版本 PySide6 复现前端行为才定位到问题。这份包就是为了让下次
不用再绕：**凡是排障要用到的东西，一次收齐**。

============================ 安全 ============================

* **脱敏**：配置文件里键名含 ``key`` / ``token`` / ``secret`` / ``password`` / ``credential``
  / ``auth`` 的项，其值一律替换为 ``<redacted>``；**保留键名与缩进**——既能定位问题，
  又不泄露凭据。API Key、Cookie secret 这类绝不出包。
* **只读**：不修改任何被收集的文件、不碰被测目录。
* **不外发**：只往本地写 zip，全程零网络动作（导入时也不联网）。
* **有界**：日志与子进程输出都只取**尾部若干行**，避免几十 MB 的日志把包撑爆。
"""
from __future__ import annotations

import io
import json
import logging
import os
import platform
import re
import sys
import time
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("maid_coder.diagnostics")

__all__ = [
    "SENSITIVE_KEY_RE",
    "redact_config",
    "redact_text",
    "collect_environment",
    "collect_process_tree",
    "tail_text_file",
    "build_bundle",
    "default_bundle_dir",
]

#: 日志尾部默认取多少行（够定位，又不至于把包撑大）。
DEFAULT_LOG_TAIL_LINES = 3000

#: 敏感键识别：键名**按词**命中即把值替换掉（键名保留，便于定位是哪个配置项）。
#: 用「前后必须是非字母数字」的边界写法，既能认出 ``key`` / ``bocha_api_key``，
#: 又不会误伤 ``keyword`` / ``provider`` / ``keymap``。
#: ⚠️ 最初的版本只列了 ``api_key`` / ``apikey``，**漏了最常见的裸 ``key``**
#: ——单元测试当场抓到（配置里的 ``api.key`` 会原样带进诊断包）。凭据类判断宁可宽一点。
SENSITIVE_KEY_RE = re.compile(
    r"(?:^|[^a-z0-9])(?:key|keys|secret|secrets|token|tokens|password|passwd|"
    r"credential|credentials|auth|authorization|apikey|accesskey|privatekey)"
    r"(?:$|[^a-z0-9])",
    re.IGNORECASE,
)

#: ``key: value`` / ``key = value`` 两种写法都覆盖；引号可选。
_KV_RE = re.compile(
    r"^(?P<indent>\s*)(?P<key>[A-Za-z_][\w\-.]*)(?P<sep>\s*[:=]\s*)"
    r"(?P<quote>['\"]?)(?P<value>.*?)(?P=quote)\s*$")

_REDACTED = "<redacted>"


def redact_text(text: str, extra_keys: Optional[List[str]] = None) -> str:
    """把 ``key: value`` 形式的敏感值替换为 ``<redacted>``（**只影响值，不动键名与缩进**）。

    Args:
        text: 原始文本（配置文件、环境 dump 等）。
        extra_keys: 额外视为敏感的键名（精确匹配，大小写不敏感）。

    Returns:
        脱敏后的文本；``text`` 非字符串时原样返回。
    """
    if not isinstance(text, str):
        return text
    extra = {k.lower() for k in (extra_keys or [])}
    out_lines: List[str] = []
    for line in text.splitlines():
        m = _KV_RE.match(line)
        if m is None:
            out_lines.append(line)
            continue
        key = m.group("key")
        if not SENSITIVE_KEY_RE.search(key) and key.lower() not in extra:
            out_lines.append(line)
            continue
        quote = m.group("quote") or ""
        out_lines.append(
            f"{m.group('indent')}{key}{m.group('sep')}{quote}{_REDACTED}{quote}")
    return "\n".join(out_lines)


def redact_config(path: "str | Path") -> str:
    """读取并脱敏一个配置文件；读不到时返回可读说明（**不抛**）。"""
    try:
        p = Path(path)
        if not p.is_file():
            return f"(配置文件不存在: {p})"
        return redact_text(p.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001 - 诊断项，绝不能因它中断整包
        return f"(读取配置失败: {exc})"


def tail_text_file(path: "str | Path", max_lines: int = DEFAULT_LOG_TAIL_LINES) -> str:
    """读取文本文件的**尾部若干行**（读不到时返回可读说明，**不抛**）。"""
    try:
        p = Path(path)
        if not p.is_file():
            return f"(文件不存在: {p})"
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        if len(lines) > max_lines:
            head = f"... (已截断，仅保留最后 {max_lines} 行 / 共 {len(lines)} 行) ...\n"
            return head + "".join(lines[-max_lines:])
        return "".join(lines)
    except Exception as exc:  # noqa: BLE001
        return f"(读取失败: {exc})"


def collect_environment(app_ctx: object = None) -> str:
    """收集环境与路径信息（版本 / 解释器 / Qt / frozen 状态 / 关键目录）。"""
    rows: List[Tuple[str, str]] = []

    def add(k: str, v: object) -> None:
        rows.append((k, str(v)))

    try:
        import version as _v  # 仓库根的 version.py（打包态亦可见）

        add("码铃版本", _v.get_version())
    except Exception:
        add("码铃版本", "(取不到)")
    try:
        from PySide6 import __version__ as _pyside

        add("PySide6", _pyside)
        try:
            from PySide6.QtCore import qVersion

            add("Qt runtime", qVersion())
        except Exception:
            pass
    except Exception:
        add("PySide6", "(未安装)")
    add("Python", sys.version.replace("\n", " "))
    add("平台", f"{platform.platform()} / {platform.machine()}")
    add("frozen（打包态）", bool(getattr(sys, "frozen", False)))
    add("可执行文件", sys.executable)
    add("_MEIPASS", getattr(sys, "_MEIPASS", "(无)"))
    add("工作目录", os.getcwd())
    try:
        from gui.utils import get_user_data_dir

        add("用户数据目录", get_user_data_dir())
    except Exception:
        pass
    try:
        from gui.utils import get_resource_path

        add("资源基准目录", get_resource_path("."))
    except Exception:
        pass
    add("进程 id", os.getpid())
    add("采集时间", time.strftime("%Y-%m-%d %H:%M:%S"))

    width = max(len(k) for k, _ in rows) if rows else 0
    return "\n".join(f"{k.ljust(width)} : {v}" for k, v in rows) + "\n"


# ----------------------------------------------------------------------
# 进程树（纯 ctypes，零第三方依赖）
# ----------------------------------------------------------------------
def _iter_processes() -> List[Tuple[int, int, str, str]]:
    """列出 ``(pid, ppid, name, path)``；失败时返回空列表（诊断项不该因它报错）。"""
    try:
        import ctypes
        import ctypes.wintypes as w

        k32 = ctypes.windll.kernel32
        TH32CS_SNAPPROCESS = 0x00000002
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

        class PE(ctypes.Structure):
            _fields_ = [
                ("dwSize", w.DWORD), ("cntUsage", w.DWORD),
                ("th32ProcessID", w.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", w.DWORD), ("cntThreads", w.DWORD),
                ("th32ParentProcessID", w.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", w.DWORD),
                ("szExeFile", ctypes.c_char * 260)]

        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        pe = PE()
        pe.dwSize = ctypes.sizeof(PE)
        out: List[Tuple[int, int, str, str]] = []
        if k32.Process32First(snap, ctypes.byref(pe)):
            while True:
                name = pe.szExeFile.decode("mbcs", "replace")
                path = ""
                h = k32.OpenProcess(
                    PROCESS_QUERY_LIMITED_INFORMATION, False, pe.th32ProcessID)
                if h:
                    buf = ctypes.create_unicode_buffer(1024)
                    size = w.DWORD(1024)
                    if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                        path = buf.value
                    k32.CloseHandle(h)
                out.append((pe.th32ProcessID, pe.th32ParentProcessID, name, path))
                if not k32.Process32Next(snap, ctypes.byref(pe)):
                    break
        k32.CloseHandle(snap)
        return out
    except Exception:
        logger.debug("枚举进程失败（诊断项降级）", exc_info=True)
        return []


def collect_process_tree(root_pid: Optional[int] = None) -> str:
    """输出以 ``root_pid``（默认本进程）为根的**进程树**。

    内置酒馆的 node 子进程、QtWebEngine 的渲染进程都会出现在这里 —— 排"孤儿进程"
    或"没起来"这类问题时，这一节往往一眼看出结论。
    """
    root = root_pid if root_pid is not None else os.getpid()
    procs = _iter_processes()
    if not procs:
        return "(进程枚举不可用)\n"

    by_parent: Dict[int, List[Tuple[int, int, str, str]]] = {}
    for pid, ppid, name, path in procs:
        by_parent.setdefault(ppid, []).append((pid, ppid, name, path))

    lines: List[str] = [f"根进程 pid={root}", ""]
    seen = set()

    def walk(pid: int, depth: int) -> None:
        if pid in seen:
            return
        seen.add(pid)
        for child_pid, _ppid, name, path in by_parent.get(pid, []):
            lines.append(f"{'  ' * depth}- {name} (pid={child_pid})")
            if path:
                lines.append(f"{'  ' * depth}    {path}")
            walk(child_pid, depth + 1)

    walk(root, 0)
    if len(lines) <= 2:
        lines.append("(无子进程)")
    lines.append("")
    lines.append(f"当前 node.exe 进程数 = "
                 f"{sum(1 for _p, _q, n, _r in procs if n.lower() == 'node.exe')}")
    return "\n".join(lines) + "\n"


def default_bundle_dir() -> Path:
    """诊断包的默认输出目录（用户数据目录下的 ``diagnostics/``）。"""
    try:
        from gui.utils import get_user_data_dir

        base = Path(get_user_data_dir()) / "diagnostics"
    except Exception:
        base = Path.home() / ".maid_coder" / "diagnostics"
    base.mkdir(parents=True, exist_ok=True)
    return base


def build_bundle(
    dest_dir: "Optional[str | Path]" = None,
    providers: Optional[Dict[str, Callable[[], str]]] = None,
    log_path: "Optional[str | Path]" = None,
    config_path: "Optional[str | Path]" = None,
    app_ctx: object = None,
    max_log_lines: int = DEFAULT_LOG_TAIL_LINES,
) -> Path:
    """收集所有诊断项并打成一个 zip，返回 zip 路径（**不抛**：单项失败只降级）。

    Args:
        dest_dir: 输出目录（默认 :func:`default_bundle_dir`）。
        providers: 额外文本段 ``{段名: 取文本的可调用}`` —— 调用方用它注入自己持有的
            运行时信息（内置酒馆的服务端输出就走这里，见 ``page_sillytavern``）。
            每个 provider 单独 try，失败只写一行说明。
        log_path: 应用日志路径（默认用户数据目录下的 ``maid_debug.log``）。
        config_path: 配置路径（默认仓库/exe 同目录的 ``config.yaml``）。
        app_ctx: 预留（当前未用）。
        max_log_lines: 日志与各段文本的尾部行数上限。

    Returns:
        zip 文件路径。
    """
    out_dir = Path(dest_dir) if dest_dir is not None else default_bundle_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    bundle = out_dir / f"maling_diagnostics_{stamp}.zip"

    if log_path is None:
        try:
            from gui.utils import get_user_data_dir

            log_path = Path(get_user_data_dir()) / "maid_debug.log"
        except Exception:
            log_path = Path("maid_debug.log")
    if config_path is None:
        # v2.5(D-V25-08): 锚定应用根（诊断包要能定位真实配置，不随工作目录漂移）
        from core.path_guard import resolve_config_path
        config_path = resolve_config_path()

    members: Dict[str, str] = {
        "environment.txt": collect_environment(app_ctx),
        "processes.txt": collect_process_tree(),
        "logs/app_log_tail.txt": tail_text_file(log_path, max_log_lines),
        "config.redacted.yaml": redact_config(config_path),
    }

    # 调用方注入的额外段（内置酒馆 stdout 等）；逐个 try，坏了不拖垮整包。
    for name, fn in (providers or {}).items():
        # 只留字母/数字/下划线/连字符：既挡掉路径分隔符，也顺带断掉 ".." 这类穿越写法。
        safe = re.sub(r"[^A-Za-z0-9_\-]", "_", str(name)) or "section"
        try:
            text = fn() if callable(fn) else str(fn)
            members[f"runtime/{safe}.txt"] = (
                text if isinstance(text, str) else str(text))
        except Exception as exc:  # noqa: BLE001
            members[f"runtime/{safe}.txt"] = f"(采集失败: {exc})"

    manifest = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "members": sorted(members),
        "note": "凭据类配置值已脱敏为 <redacted>；本包仅存本地，未做任何网络动作。",
    }

    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in members.items():
            zf.writestr(name, text)
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    logger.info("诊断包已生成: %s（%d 项）", bundle, len(members))
    return bundle
