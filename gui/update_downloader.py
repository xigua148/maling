"""gui/update_downloader.py —— v2.0 下载层（L2）。

docs/design-v20.md D-V20-05：下载器进程模型 = `QThread` + **纯函数核**。
- 纯函数核（URL 链 / 续传偏移 / 进度文本 / sha256 / 磁盘预检 / 安装目录可写探测）
  不碰网络、不碰 Qt，可被 pytest 直接断言；
- `DownloadWorker(QThread)`（V20-06）沿用 `update_checker._FetchWorker` 同款进程模型，
  线程内**绝不直接触碰 Qt UI**（只 emit 信号），任何异常一律转 `failed(reason)` 不抛出（R-N）。

红线（design §9）：
- R-F 零新增第三方依赖：只用既有 `requests` + `hashlib`/`shutil`/`os`/`time`/`threading`；
- R-M 更新安全：**私有**防御性 scheme 检查 `_assert_safe_url`（仅 https、拒 UNC/相对/`..`）。
  域名白名单的**权威实现在** `gui.update_checker.is_allowed_url`（域1 独占），本模块**不重复实现**、
  不导出同名公开函数；`build_url_chain` **默认即启用域名白名单（fail-closed：默认只锁 GitHub 系）**，
  由 `make_allowed_check(extra_hosts)` 延迟 import 域1 权威实现；调用方也可用 `allowed_check=` 完全接管；
  **镜像 host 必须经 `extra_hosts` 注入**（`cfg.mirror_url` 的 host），否则自配镜像会被
  域1 白名单拒绝 → 备用链整体失效（Q-U3 镜像能力作废）；
- R-N 更新可失败不伤主程序：取消 / 断链 / 校验失败一律静默转失败态，保留 `.part` 供续传。

信号契约（V20-06，team-lead 定稿）：
    progress = Signal(int, int, float, str)   # received, total, speed(B/s), eta_text
    finished = Signal(str)                    # 成品绝对路径（已完成；不代表校验通过）
    failed   = Signal(str)                    # 错误码 / 原因文本
    verified = Signal(str)                    # 校验通过的成品绝对路径（R-M 强 sha256）
    cancelled = Signal()                      # 用户取消（.part 保留）
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Callable, Optional, Sequence
from urllib.parse import urlsplit

from gui.qt_compat import Signal
from gui.qt_exit_guard import ExitSafeQThread

logger = logging.getLogger("maid_coder.gui")

# ---------------------------------------------------------------------------
# 常量（集中收口，便于调参与测试注入）
# ---------------------------------------------------------------------------
DOWNLOAD_TIMEOUT_SECONDS = 30          # 每次 HTTP 请求超时（秒）
DEFAULT_CHUNK_SIZE = 256 * 1024        # 256KB 分块
DEFAULT_RETRY_PER_LINK = 3             # 单链重试次数（L2-3）
DEFAULT_RETRY_BACKOFF = (1.0, 3.0, 7.0)  # 退避（秒），不足时取末值
DISK_SPACE_FACTOR = 1.3                # 磁盘预检系数（L2-6：空间 < 包大小 × 1.3 即拒绝）
PROGRESS_MIN_INTERVAL = 0.1            # 进度信号最小发送间隔（秒），防刷屏

# 产物命名规范（Q-U2，v2.1 起直观名）：MaLing_v<X.Y.Z>_Desktop.zip / _Portable.exe
ASSET_FILENAME_RE = re.compile(r"^MaLing_v\d+\.\d+\.\d+_(Desktop\.zip|Portable\.exe)$")
_SHA256_HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")

# 错误码（failed 信号 payload；文案由 UI 层决定，R-A 不展示数值化催促语义）
ERR_DISK_SPACE_LOW = "disk_space_low"
ERR_ALL_LINKS_FAILED = "all_links_failed"
ERR_SHA256_MISMATCH = "sha256_mismatch"
ERR_NO_URLS = "no_urls"
ERR_CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# 一、纯函数核（可 pytest 直接断言）
# ---------------------------------------------------------------------------
def _assert_safe_url(url: object) -> bool:
    """**私有**防御性 URL scheme 检查（R-M 最小集，非域名白名单）。

    仅校验：①必须 `https://`；②拒绝 UNC（`\\\\` / `//` 开头）、相对路径；
    ③拒绝 path 含 `..` 段；④拒绝含反斜杠。
    域名白名单由 `gui.update_checker.is_allowed_url` 权威收口，本模块不重复实现。
    """
    if not isinstance(url, str):
        return False
    u = url.strip()
    if not u:
        return False
    if u.startswith("\\\\") or u.startswith("//"):
        return False  # UNC
    if "\\" in u:
        return False
    if not u.lower().startswith("https://"):
        return False  # 拒 http/file/相对路径
    parts = urlsplit(u)
    if not parts.netloc:
        return False
    if ".." in (parts.path or "").split("/"):
        return False
    return True


def make_allowed_check(
    extra_hosts: Optional[Sequence[str]] = None,
) -> Callable[[str], bool]:
    """构造 R-M 域名白名单校验器（延迟 import 域1 权威实现，避免加载顺序耦合）。

    返回的校验器调用 `gui.update_checker.is_allowed_url(url, extra_hosts=...)`。
    `extra_hosts` 用于放行**用户自配镜像**的 host（来自 `GuiConfig.mirror_url`）——
    不注入就会被域1 默认白名单（github.com / objects.githubusercontent.com /
    raw.githubusercontent.com / codeload.github.com）拒绝，备用链整体失效（Q-U3）。

    延迟 import 失败（域1 未落盘 / 未实现该函数）→ **保守回退**：只做私有
    `_assert_safe_url`（仅 https + 拒 UNC / 相对路径 / `..`）。这是 fail-safe：仍然拒绝
    `http`/UNC/`..` 注入，绝不是放宽安全约束，只是暂时失去"域名白名单"这一层。
    """
    hosts = list(extra_hosts) if extra_hosts else None

    def _check(url: str) -> bool:
        try:
            from gui.update_checker import is_allowed_url  # 延迟 import：避免顺序耦合
        except Exception as exc:
            logger.info("update_checker.is_allowed_url 不可用，回退私有 scheme 检查: %s", exc)
            return _assert_safe_url(url)
        try:
            return bool(is_allowed_url(url, extra_hosts=hosts))
        except TypeError:
            # 兼容旧签名（无 extra_hosts 关键字）——保守：先过私有检查再单参调用
            try:
                return bool(_assert_safe_url(url)) and bool(is_allowed_url(url))
            except Exception:
                return False
        except Exception as exc:  # 白名单异常按拒绝处理（安全优先）
            logger.info("域名白名单校验异常，按拒绝处理: %s", exc)
            return False

    return _check


def build_url_chain(
    asset: object,
    use_mirror: bool = True,
    allowed_check: Optional[Callable[[str], bool]] = None,
    extra_hosts: Optional[Sequence[str]] = None,
) -> list[str]:
    """构造降级链：主链在前、备用链（mirror）在后（L2-3）。

    - `asset` 形如 version.json 的 `assets.onedir` / `assets.single`：
      `{"url": ..., "mirror": ..., "sha256": ..., "size": ..., "filename": ...}`；
    - `use_mirror=False` → 只保留主链；
    - 每个候选先过私有 `_assert_safe_url`；域名白名单（R-M）按以下优先级：
      ① `allowed_check` 非空 → 直接用它（调用方完全接管，自行组合域1 实现）；
      ② 否则**一律** `make_allowed_check(extra_hosts)`（默认即启用白名单：`extra_hosts`
         为 None 时只允许 GitHub 系；延迟 import 域1 失败则保守回退 `_assert_safe_url`）；
      —— **fail-closed**：漏传参数只会更严（默认锁 GitHub 系），绝不会静默放开域名；
    - 去重、去空，保持顺序。
    """
    if not isinstance(asset, dict):
        return []
    candidates: list[str] = []
    primary = asset.get("url")
    mirror = asset.get("mirror")
    if isinstance(primary, str) and primary.strip():
        candidates.append(primary.strip())
    if use_mirror and isinstance(mirror, str) and mirror.strip():
        candidates.append(mirror.strip())

    # fail-closed：显式 allowed_check 优先；否则默认也吃域名白名单（不再 fail-open）
    check = allowed_check if allowed_check is not None else make_allowed_check(extra_hosts)

    out: list[str] = []
    for url in candidates:
        if not _assert_safe_url(url):
            logger.info("URL 被私有安全检查拒绝（不下载）: %r", url)
            continue
        try:
            if not check(url):
                logger.info("URL 未通过域名白名单（不下载）: %r", url)
                continue
        except Exception as exc:  # 白名单异常按拒绝处理（安全优先）
            logger.info("URL 白名单校验异常，按拒绝处理: %s", exc)
            continue
        if url not in out:
            out.append(url)
    return out


def resume_offset(part_path: object) -> int:
    """返回 `.part` 已下载字节数（L2-2）；不存在 / 非文件 / 读不到一律 0。"""
    try:
        p = Path(str(part_path))
        if p.is_file():
            size = p.stat().st_size
            return int(size) if size > 0 else 0
    except Exception:
        pass
    return 0


def progress_percent(received: int, total: int) -> int:
    """进度百分比（0–100，向下取整）。`total<=0`（未知长度）返回 0。"""
    try:
        r = max(int(received or 0), 0)
        t = int(total or 0)
    except (TypeError, ValueError):
        return 0
    if t <= 0:
        return 0
    if r >= t:
        return 100
    return int(r * 100 // t)


def _human_bytes(num: float, decimals: int = 0) -> str:
    """字节数人性化（B/KB/MB/GB/TB）。"""
    try:
        n = float(num or 0)
    except (TypeError, ValueError):
        n = 0.0
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            if unit == "B":
                return f"{int(n)}B"
            return f"{n:.{decimals}f}{unit}"
        n /= 1024
    return f"{n:.{decimals}f}TB"


def _human_duration(seconds: float) -> str:
    """秒数人性化：`1 分 12 秒` / `12 秒` / `1 小时 2 分`。"""
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        s = 0
    if s < 0:
        s = 0
    if s < 60:
        return f"{s} 秒"
    if s < 3600:
        m, sec = divmod(s, 60)
        return f"{m} 分 {sec} 秒"
    h, rem = divmod(s, 3600)
    m = rem // 60
    return f"{h} 小时 {m} 分"


def progress_text(received: int, total: int, speed: float = -1.0, eta: float = -1.0) -> str:
    """L2-1 进度文本骨架，纯函数可测。

    形如 `45% · 117MB/248MB · 2.3MB/s · 剩余 1 分 12 秒`；
    `total<=0`（未知长度）时退化为 `117MB · 2.3MB/s`；
    `speed<=0` / `eta<0` 的段落省略。percent 随 received 单调不减。
    """
    parts: list[str] = []
    t = int(total or 0)
    r = max(int(received or 0), 0)
    if t > 0:
        parts.append(f"{progress_percent(r, t)}%")
        parts.append(f"{_human_bytes(r)}/{_human_bytes(t)}")
    else:
        parts.append(_human_bytes(r))
    try:
        spd = float(speed)
    except (TypeError, ValueError):
        spd = -1.0
    if spd > 0:
        parts.append(f"{_human_bytes(spd, decimals=1)}/s")
    try:
        e = float(eta)
    except (TypeError, ValueError):
        e = -1.0
    if t > 0 and e >= 0:
        parts.append(f"剩余 {_human_duration(e)}")
    return " · ".join(parts)


def verify_sha256(path: object, expected: object, chunk_size: int = 1024 * 1024) -> bool:
    """流式 sha256 校验（L2-4 / Q-U5），标准库 `hashlib`，零依赖。

    `expected` 缺失 / 非 64 位 hex / 文件不可读 → 一律 False（安全优先）。
    """
    if not isinstance(expected, str) or not _SHA256_HEX_RE.match(expected.strip()):
        return False
    try:
        p = Path(str(path))
        if not p.is_file():
            return False
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for block in iter(lambda: f.read(chunk_size), b""):
                h.update(block)
        return h.hexdigest().lower() == expected.strip().lower()
    except Exception as exc:
        logger.info("sha256 校验失败（按未通过处理）: %s", exc)
        return False


def disk_precheck(
    target_dir: object,
    need_bytes: int,
    factor: float = DISK_SPACE_FACTOR,
) -> tuple[bool, str]:
    """磁盘空间预检（L2-6）。返回 `(ok, reason)`，ok=False 时 reason 为错误码。

    判定：`free >= need_bytes × factor`（默认 1.3）。空间不足 → `(False, "disk_space_low")`，
    调用方须**不发第一个 GET**（L2-6 验收①）。
    """
    try:
        need = int(need_bytes or 0)
    except (TypeError, ValueError):
        need = 0
    if need <= 0:
        return True, ""  # 尺寸未知（None）→ 不阻断（由服务端长度兜底）
    try:
        usage = shutil.disk_usage(str(target_dir))
        required = int(need * float(factor))
        if usage.free < required:
            logger.info(
                "磁盘空间不足：free=%s need=%s (factor=%s)", usage.free, required, factor
            )
            return False, ERR_DISK_SPACE_LOW
        return True, ""
    except Exception as exc:
        # 无法确定磁盘状态时不阻断（服务端 200 兜底；R-N 可失败不伤主程序）
        logger.info("磁盘预检异常（放行）: %s", exc)
        return True, ""


def is_install_writable(install_dir: object) -> bool:
    """安装目录可写探测（Q-U12 / D-V20-12）。

    `os.access(W_OK)` + **实际写探针**（临时文件创建后**立即删除**，不留垃圾）；
    不可写 / 不存在 / 探针失败 → False（→ 不自动替换，走"手动解压覆盖"兜底）。
    """
    try:
        d = Path(str(install_dir))
        if not d.is_dir():
            return False
        if not os.access(str(d), os.W_OK):
            return False
        probe = d / f".maling_write_probe_{os.getpid()}_{int(time.time() * 1000)}"
        try:
            with open(probe, "w", encoding="utf-8") as f:
                f.write("probe")
        finally:
            try:
                if probe.exists():
                    probe.unlink()
            except Exception:
                pass  # 清理失败不视为"可写"，但也不抛出（不留垃圾优先）
        return True
    except Exception as exc:
        logger.info("安装目录可写探测失败（按不可写处理）: %s", exc)
        return False


def asset_filename_for(version: str, form: str) -> str:
    """Q-U2 产物命名规范（v2.1 起改为**直观名**，用户一眼知道该下哪个）：
    ``MaLing_v<X.Y.Z>_Desktop.zip``（桌面版·解压即用）/
    ``MaLing_v<X.Y.Z>_Portable.exe``（单文件版·免解压）。

    背景：旧名 ``MaLing_v..._win_onedir.zip`` / ``..._win_single.exe`` 对普通用户不直观
    （用户反馈「不知道下哪个」）。
    ⚠️ **不能用中文文件名** —— GitHub Release 资产名会**直接删掉非 ASCII 字符**
    （实测 ``测试中文名_abc.txt`` → ``_abc.txt``）。故用 ASCII 直观词，
    中文说明放在 Release 的**资产显示名 label** 里（页面照常显示中文）。

    落盘名取自 ``version.json`` 的 ``filename`` 字段，本函数为回退推导；
    ``.sha256`` 文本内容里的文件名须与之一致（见 :func:`sha256_file_line`）。
    """
    ver = (version or "").strip().lstrip("vV")
    kind = "Portable.exe" if str(form).strip().lower() == "onefile" else "Desktop.zip"
    return f"MaLing_v{ver}_{kind}"


def sha256_file_line(digest: str, filename: str) -> str:
    """`.sha256` 文本内容格式（Q-U2）：`<hash>  <filename>`（两空格）。"""
    return f"{(digest or '').strip()}  {(filename or '').strip()}"


def parse_sha256_file(text: str) -> Optional[tuple[str, str]]:
    """解析 `.sha256` 文本，返回 `(hash, filename)`；非法返回 None。"""
    if not isinstance(text, str):
        return None
    line = text.strip().splitlines()[0] if text.strip() else ""
    m = re.match(r"^([0-9a-fA-F]{64})\s+(.+)$", line.strip())
    if not m:
        return None
    return m.group(1).lower(), m.group(2).strip()


# ---------------------------------------------------------------------------
# 二、DownloadWorker（V20-06）
# ---------------------------------------------------------------------------
class DownloadWorker(ExitSafeQThread):
    """后台下载线程（Range 续传 / 200 重下 / 降级链 / 取消保留 `.part` / sha256 校验）。

    用法（gui/main.py 接线建议）::

        # 镜像 host 必须经 extra_hosts 注入，否则自配镜像被域1 白名单拒绝 → 备用链失效
        extra_hosts = []
        try:
            from gui.update_checker import extract_host
            h = extract_host(cfg.mirror_url)      # 域1 权威取 host；拿不到就传 None
            extra_hosts = [h] if h else []
        except Exception:
            extra_hosts = []
        urls = build_url_chain(asset, use_mirror=cfg.use_mirror,
                               allowed_check=make_allowed_check(extra_hosts=extra_hosts))
        # 或直接：build_url_chain(asset, use_mirror=cfg.use_mirror, extra_hosts=extra_hosts)
        w = DownloadWorker(urls=urls, dest_path=dest_zip,
                           expected_sha256=asset.get("sha256", ""),
                           total_size=int(asset.get("size", 0) or 0))
        dlg = UpdateProgressDialog(app_ctx, parent=window)
        dlg.begin(w)          # 连接 progress/verified/failed/cancelled 并 show()
        w.start()

    线程内**绝不触碰 Qt UI**（只 emit 信号）；任何异常一律转 `failed(reason)`（R-N）。
    """

    progress = Signal(int, int, float, str)   # received, total, speed(B/s), eta_text
    finished = Signal(str)                    # 成品路径（已落盘；expected 为空时未经校验）
    failed = Signal(str)                      # 错误码 / 原因文本
    verified = Signal(str)                    # 校验通过的成品路径（R-M）
    cancelled = Signal()                      # 用户取消（.part 保留）

    def __init__(
        self,
        urls: list[str],
        dest_path: object,
        expected_sha256: str = "",
        total_size: int = 0,
        retry_per_link: int = DEFAULT_RETRY_PER_LINK,
        timeout: int = DOWNLOAD_TIMEOUT_SECONDS,
        backoff: tuple[float, ...] = DEFAULT_RETRY_BACKOFF,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        version: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._urls = [u for u in (urls or []) if isinstance(u, str) and u.strip()]
        self._dest = Path(str(dest_path))
        self._part = Path(str(dest_path) + ".part")
        self._expected = (expected_sha256 or "").strip()
        self._total_size = int(total_size or 0)
        self._retry = max(1, int(retry_per_link or 1))
        self._timeout = max(1, int(timeout or DOWNLOAD_TIMEOUT_SECONDS))
        self._backoff = tuple(backoff) if backoff else DEFAULT_RETRY_BACKOFF
        self._chunk = max(1024, int(chunk_size or DEFAULT_CHUNK_SIZE))
        self._version = version or ""
        self._cancel_evt = threading.Event()
        self._last_emit = 0.0

    # -- 对外控制 ----------------------------------------------------------
    def request_cancel(self) -> None:
        """请求取消（线程安全）；主循环每读一块检查 → ≤1s 内停止写盘，`.part` 保留。"""
        self._cancel_evt.set()

    # 别名（便于调用方语义化调用）
    cancel = request_cancel

    def stop(self, wait_ms=None) -> bool:
        """幂等停机（覆写基类）：先 ``request_cancel`` 协作取消，再**有界** ``wait``。

        退出收口（``aboutToQuit`` / 父控件 ``destroyed``）走此路径 → 先请求取消，
        主循环 ≤1s 内停写盘（``.part`` 保留），故有界等待通常远小于上界。
        """
        self.request_cancel()
        return super().stop(wait_ms)

    @property
    def part_path(self) -> Path:
        return self._part

    @property
    def dest_path(self) -> Path:
        return self._dest

    # -- 线程主体 ----------------------------------------------------------
    def run(self) -> None:  # noqa: D401 - QThread 入口
        try:
            self._run_inner()
        except Exception as exc:  # R-N：任何异常静默转失败态，绝不抛出
            logger.info("下载线程异常（转失败态）: %s", exc)
            self._safe_emit(self.failed, f"exception:{exc}")

    def _run_inner(self) -> None:
        try:
            self._dest.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            self._safe_emit(self.failed, f"staging_unwritable:{exc}")
            return
        if not self._urls:
            self._safe_emit(self.failed, ERR_NO_URLS)
            return

        # L2-6：磁盘空间预检 —— 不足则**不发第一个 GET**
        if self._total_size > 0:
            ok, reason = disk_precheck(str(self._dest.parent), self._total_size)
            if not ok:
                self._safe_emit(self.failed, reason or ERR_DISK_SPACE_LOW)
                return

        for url in self._urls:
            if self._cancel_evt.is_set():
                self._safe_emit(self.cancelled)
                return
            status = self._download_from(url)
            if status == "cancelled":
                self._safe_emit(self.cancelled)
                return
            if status == "done":
                self._finish()
                return
            # status == "error" → 换下一链（已在 _download_from 内做单链重试）

        # 全链失败：保留 `.part`（L2-3 验收③）
        self._safe_emit(self.failed, ERR_ALL_LINKS_FAILED)

    def _download_from(self, url: str) -> str:
        """从单条链下载；返回 `"done"` / `"cancelled"` / `"error"`。

        单链内有限重试（退避）；返回 error 时 `.part` 保留，供下一链续传。
        """
        offset = resume_offset(self._part)
        for attempt in range(self._retry):
            if self._cancel_evt.is_set():
                return "cancelled"
            try:
                import requests  # 延迟导入：下载失败不拖累启动

                headers = {}
                if offset > 0:
                    headers["Range"] = f"bytes={offset}-"
                resp = requests.get(
                    url, stream=True, timeout=self._timeout, headers=headers
                )
                try:
                    code = int(resp.status_code)
                    if code == 416:  # Range 不可满足（本地已完整）→ 视为完成
                        return "done"
                    if code not in (200, 206):
                        logger.info("下载链返回 %s（重试）: %s", code, url)
                        self._sleep_backoff(attempt)
                        continue

                    if code == 206 and offset > 0:
                        mode = "ab"
                        received = offset
                        total = self._parse_total(resp, offset, ranged=True)
                    else:
                        # 200：服务端不支持续传 → 截断重建，不产生重复字节（L2-2 验收③）
                        mode = "wb"
                        received = 0
                        total = self._parse_total(resp, 0, ranged=False)
                    if total <= 0:
                        total = self._total_size

                    base = received
                    start = time.monotonic()
                    with open(self._part, mode) as f:
                        for chunk in resp.iter_content(chunk_size=self._chunk):
                            if self._cancel_evt.is_set():
                                try:
                                    f.flush()
                                except Exception:
                                    pass
                                return "cancelled"
                            if not chunk:
                                continue
                            f.write(chunk)
                            received += len(chunk)
                            self._emit_progress(received, total, start, base)
                        try:
                            f.flush()
                        except Exception:
                            pass

                    if total > 0 and received < total:
                        logger.info("下载不完整（%s/%s），续传重试", received, total)
                        offset = received
                        self._sleep_backoff(attempt)
                        continue
                    # 保证最终进度到 100%
                    self._emit_progress(received, max(total, received), start, base, force=True)
                    return "done"
                finally:
                    try:
                        resp.close()
                    except Exception:
                        pass
            except Exception as exc:
                logger.info("下载链异常（重试）: %s", exc)
                offset = resume_offset(self._part)
                self._sleep_backoff(attempt)
                continue
        return "error"

    def _parse_total(self, resp, offset: int, ranged: bool) -> int:
        """从响应头解析总大小：206 读 Content-Range，200 读 Content-Length。"""
        try:
            if ranged:
                cr = resp.headers.get("Content-Range", "") or ""
                if "/" in cr:
                    try:
                        return int(cr.rsplit("/", 1)[1])
                    except Exception:
                        pass
                cl = resp.headers.get("Content-Length")
                if cl not in (None, ""):
                    return int(cl) + offset
            else:
                cl = resp.headers.get("Content-Length")
                if cl not in (None, ""):
                    return int(cl)
        except Exception:
            pass
        return 0

    def _emit_progress(
        self, received: int, total: int, start: float, base: int, force: bool = False
    ) -> None:
        now = time.monotonic()
        if not force and (now - self._last_emit) < PROGRESS_MIN_INTERVAL:
            return
        self._last_emit = now
        elapsed = max(now - start, 1e-6)
        speed = max(received - base, 0) / elapsed
        eta = -1.0
        if total > 0 and speed > 0:
            eta = max(total - received, 0) / speed
        text = progress_text(received, total, speed, eta)
        self._safe_emit(self.progress, received, total, float(speed), text)

    def _sleep_backoff(self, attempt: int) -> None:
        if self._retry <= 1:
            return  # 单次尝试不等待，退避只发生在"还有下一次"时
        if attempt >= self._retry - 1:
            idx = len(self._backoff) - 1
        else:
            idx = min(attempt, len(self._backoff) - 1)
        try:
            delay = float(self._backoff[idx]) if self._backoff else 0.0
        except (TypeError, ValueError, IndexError):
            delay = 0.0
        # 退避期间也响应取消（切片睡眠）
        deadline = time.monotonic() + max(delay, 0.0)
        while time.monotonic() < deadline:
            if self._cancel_evt.is_set():
                return
            time.sleep(min(0.05, max(deadline - time.monotonic(), 0.0)))

    def _finish(self) -> None:
        """关闭 `.part` → 落成品 → sha256 校验（不符删除、不进 L3）→ `.verified` → 信号。"""
        try:
            if self._dest.exists():
                self._dest.unlink()
        except Exception:
            pass
        try:
            os.replace(str(self._part), str(self._dest))
        except Exception as exc:
            self._safe_emit(self.failed, f"replace_failed:{exc}")
            return

        if self._expected:
            if not verify_sha256(str(self._dest), self._expected):
                try:
                    self._dest.unlink()
                except Exception:
                    pass
                logger.info("sha256 校验未通过，已删除成品（不进 L3）")
                self._safe_emit(self.failed, ERR_SHA256_MISMATCH)
                return
            self._write_verified_marker()
            self._safe_emit(self.verified, str(self._dest))
        else:
            # Q-U5：无 sha256 → 不进入自动替换，仅落盘（由调用方降级为手动）
            logger.info("assets.sha256 缺失，未校验（禁止自动替换）")

        self._safe_emit(self.finished, str(self._dest))

    def _write_verified_marker(self) -> None:
        marker = self._dest.parent / ".verified"
        payload = {
            "version": self._version,
            "filename": self._dest.name,
            "sha256": self._expected,
            "size": resume_offset(self._dest),
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        try:
            marker.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        except Exception as exc:  # 标记写失败不影响成品（幂等可重写）
            logger.info(".verified 标记写入失败（忽略）: %s", exc)

    @staticmethod
    def _safe_emit(signal, *args) -> None:
        """信号发射的安全包装：对象可能已销毁（退出竞态）→ 忽略，绝不抛出。"""
        try:
            signal.emit(*args)
        except Exception:
            pass


def staging_dir_for(version: str) -> Path:
    """暂存目录：`get_user_data_dir()/updates/<version>/`（L2-5，绝不写安装目录）。"""
    from gui.utils import get_user_data_dir

    d = get_user_data_dir() / "updates" / str(version or "").strip()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_filename(asset: dict, version: str) -> str:
    """从 asset 推导就位文件名（Q-U2）；非法（含路径分隔）则回退 url 末段。"""
    fn = asset.get("filename") if isinstance(asset, dict) else None
    if not isinstance(fn, str) or not fn.strip() or "/" in fn or "\\" in fn or ".." in fn:
        url = ""
        if isinstance(asset, dict) and isinstance(asset.get("url"), str):
            url = asset["url"]
        base = url.rstrip("/").rsplit("/", 1)[-1] or ""
        if base and "/" not in base and "\\" not in base:
            fn = base
        else:
            form = "onefile" if url.lower().endswith(".exe") else "onedir"
            fn = asset_filename_for(version, form)
    return fn.strip()


def make_download_worker(
    asset: dict,
    version: str,
    *,
    use_mirror: bool = True,
    allowed_check: Optional[Callable[[str], bool]] = None,
    extra_hosts: Optional[Sequence[str]] = None,
    parent=None,
) -> "DownloadWorker":
    """按 version.json 的 `assets.<kind>` 组装 `DownloadWorker`（L2-5/L2-7 落点收口）。

    - 降级链：`build_url_chain(asset, use_mirror, allowed_check, extra_hosts)`；
      **镜像 host 必须经 `extra_hosts` 注入**（否则自配镜像被域1 白名单拒绝 → 备用链失效）；
    - 落盘：`staging_dir_for(version) / <filename>`（**绝不写安装目录**）；
    - 校验：`asset.sha256`（缺失 → worker 不写 `.verified`，Q-U5 禁止自动替换）；
    - 大小：`asset.size`（供 L2-6 磁盘预检）。
    """
    a = asset if isinstance(asset, dict) else {}
    urls = build_url_chain(
        a, use_mirror=use_mirror, allowed_check=allowed_check, extra_hosts=extra_hosts
    )
    dest = staging_dir_for(version) / _safe_filename(a, version)
    sha = a.get("sha256") if isinstance(a.get("sha256"), str) else ""
    size = a.get("size") if isinstance(a.get("size"), int) else 0
    return DownloadWorker(
        urls=urls,
        dest_path=dest,
        expected_sha256=sha,
        total_size=int(size or 0),
        version=version,
        parent=parent,
    )
