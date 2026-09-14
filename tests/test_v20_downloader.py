"""tests/test_v20_downloader.py —— v2.0 下载层测试（V20-05 / V20-06 / V20-07）。

覆盖 docs/design-v20.md §8.1/§8.2 与 prd-v20.md L2-1~L2-7 验收：
- 纯函数核：build_url_chain / resume_offset / progress_text / verify_sha256 /
  disk_precheck / is_install_writable / asset_filename_for / sha256_file_line；
- DownloadWorker：Range 续传（断言 Range 头）/ 200 重下无重复字节 / 降级链 URL 序列 /
  全链失败保留 .part / 取消停止 / sha256 篡改失败 / 磁盘不足不发第一个 GET；
- 进度对话框：非模态 + 信号接线（R-A）。

**不依赖外网**：本地 `http.server` mock 服务端；无 pytest-qt 时自建 QApplication（offscreen）。
"""
from __future__ import annotations

import hashlib
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# GUI 无显示环境：必须在导入 gui.* 之前设置
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui import update_downloader as dl  # noqa: E402


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def qapp():
    """无 pytest-qt 时自建 QApplication（QThread 信号投递 / 控件实例化需要）。"""
    from gui.qt_compat import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fake_is_allowed_url(url: str, extra_hosts=None) -> bool:
    """模拟域1 `is_allowed_url` 的白名单语义（跨域集成断言用，不联网、不起真实 host）。"""
    from urllib.parse import urlsplit

    allowed = {
        "github.com",
        "objects.githubusercontent.com",
        "raw.githubusercontent.com",
        "codeload.github.com",
    }
    if extra_hosts:
        allowed |= {str(h).strip().lower() for h in extra_hosts if h}
    try:
        host = urlsplit(url).netloc.lower().split("@")[-1].split(":")[0]
    except Exception:
        return False
    return url.lower().startswith("https://") and host in allowed


# ---------------------------------------------------------------------------
# 本地 mock HTTP 服务端
# ---------------------------------------------------------------------------
class MockHttpServer:
    """极简可控 HTTP 服务端（range / 失败路径 / 慢速流）。

    - `support_range=True`：识别 `Range` 头 → 206 + Content-Range；否则 200 整包；
    - `fail_paths`：这些 path 一律 500；
    - `chunk`/`delay`：分包写出 + 每包延迟（供取消测试制造"慢速流"）；
    - `request_log`：`(path, headers_dict)` 列表，供断言请求 URL 序列 / Range 头。
    """

    def __init__(
        self,
        content: bytes,
        *,
        support_range: bool = True,
        fail_paths: set[str] | None = None,
        chunk: int = 64 * 1024,
        delay: float = 0.0,
    ):
        self.content = content
        self.support_range = support_range
        self.fail_paths = set(fail_paths or set())
        self.chunk = chunk
        self.delay = delay
        self.request_log: list[tuple[str, dict]] = []
        handler = self._make_handler()
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._httpd.mock = self  # type: ignore[attr-defined]
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def base(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def url(self, path: str) -> str:
        return self.base + path

    def close(self) -> None:
        try:
            self._httpd.shutdown()
        finally:
            self._httpd.server_close()

    def _make_handler(self):
        outer = self

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):  # noqa: A003 - 静默
                pass

            def do_GET(self):  # noqa: N802
                m = self.server.mock  # type: ignore[attr-defined]
                m.request_log.append((self.path, {k: v for k, v in self.headers.items()}))
                if self.path in m.fail_paths:
                    self.send_response(500)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                rng = self.headers.get("Range")
                start = 0
                if m.support_range and rng and rng.startswith("bytes="):
                    try:
                        start = int(rng[len("bytes="):].split("-")[0])
                    except Exception:
                        start = 0
                body = m.content[start:]
                try:
                    if start > 0 and m.support_range:
                        self.send_response(206)
                        self.send_header(
                            "Content-Range",
                            f"bytes {start}-{len(m.content) - 1}/{len(m.content)}",
                        )
                    else:
                        self.send_response(200)
                    self.send_header("Accept-Ranges", "bytes" if m.support_range else "none")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    for i in range(0, len(body), m.chunk):
                        self.wfile.write(body[i:i + m.chunk])
                        try:
                            self.wfile.flush()
                        except Exception:
                            return
                        if m.delay:
                            time.sleep(m.delay)
                except (BrokenPipeError, ConnectionResetError):
                    return

        return _Handler


@pytest.fixture
def server():
    servers: list[MockHttpServer] = []

    def _make(content: bytes, **kw) -> MockHttpServer:
        s = MockHttpServer(content, **kw)
        servers.append(s)
        return s

    yield _make
    for s in servers:
        s.close()


# ---------------------------------------------------------------------------
# 信号收集 + 等待工具
# ---------------------------------------------------------------------------
class Recorder:
    def __init__(self, worker):
        self.progress: list[tuple] = []
        self.finished: list[str] = []
        self.failed: list[str] = []
        self.verified: list[str] = []
        self.cancelled: int = 0
        worker.progress.connect(lambda *a: self.progress.append(a))
        worker.finished.connect(lambda p: self.finished.append(p))
        worker.failed.connect(lambda r: self.failed.append(r))
        worker.verified.connect(lambda p: self.verified.append(p))
        worker.cancelled.connect(lambda: setattr(self, "cancelled", self.cancelled + 1))


def _wait_until(app, cond, timeout: float = 20.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    app.processEvents()
    return cond()


def _run_worker(app, worker: "dl.DownloadWorker", rec: Recorder, timeout: float = 20.0) -> None:
    worker.start()
    _wait_until(
        app,
        lambda: not worker.isRunning() and (rec.finished or rec.failed or rec.cancelled),
        timeout=timeout,
    )
    app.processEvents()


# ===========================================================================
# 一、纯函数核
# ===========================================================================
class TestPureFunctions:
    def test_build_url_chain_primary_then_mirror(self):
        # 默认 fail-closed：主链/备用链都用 GitHub 系 host，才都能过默认白名单
        asset = {
            "url": "https://github.com/o/r/releases/download/v2/MaLing_v2.0.0_Desktop.zip",
            "mirror": "https://objects.githubusercontent.com/MaLing_v2.0.0_Desktop.zip",
        }
        chain = dl.build_url_chain(asset, use_mirror=True)
        assert chain == [asset["url"], asset["mirror"]]
        assert dl.build_url_chain(asset, use_mirror=False) == [asset["url"]]

    def test_build_url_chain_rejects_unsafe(self):
        asset = {
            "url": "http://evil.example.com/x.zip",     # 非 https
            "mirror": "\\\\srv\\share\\x.zip",           # UNC
        }
        assert dl.build_url_chain(asset) == []
        assert dl.build_url_chain({"url": "https://h.com/a/../b.zip"}) == []
        assert dl.build_url_chain({"url": "https://github.com/ok.zip"}) == [
            "https://github.com/ok.zip"
        ]

    def test_build_url_chain_allowed_check_injection(self):
        """域名白名单权威在域1；本模块通过 allowed_check 注入，不重复实现。"""
        asset = {
            "url": "https://github.com/o/r/x.zip",
            "mirror": "https://mirror.example.com/x.zip",
        }
        allow = lambda u: "github.com" in u  # noqa: E731
        assert dl.build_url_chain(asset, allowed_check=allow) == [asset["url"]]

    # -- 镜像 host 白名单缺口（工程师 A 报的跨域集成缺口）-----------------
    def test_mirror_host_rejected_when_extra_hosts_empty(self, monkeypatch):
        """① extra_hosts 为空 → 非 github 镜像被白名单拒绝，不含在链中。"""
        import gui.update_checker as uc

        monkeypatch.setattr(uc, "is_allowed_url", _fake_is_allowed_url, raising=False)
        asset = {
            "url": "https://github.com/o/r/releases/download/v2/x.zip",
            "mirror": "https://mirror.example.com/x.zip",
        }
        chain = dl.build_url_chain(asset, extra_hosts=[])
        assert chain == [asset["url"]]
        assert asset["mirror"] not in chain

    def test_mirror_host_allowed_when_injected_via_extra_hosts(self, monkeypatch):
        """② 传入 extra_hosts=[镜像 host] → 结果含镜像，且顺序在主链之后（Q-U3）。"""
        import gui.update_checker as uc

        monkeypatch.setattr(uc, "is_allowed_url", _fake_is_allowed_url, raising=False)
        asset = {
            "url": "https://github.com/o/r/releases/download/v2/x.zip",
            "mirror": "https://mirror.example.com/x.zip",
        }
        chain = dl.build_url_chain(asset, extra_hosts=["mirror.example.com"])
        assert chain == [asset["url"], asset["mirror"]]

    def test_default_is_fail_closed_rejects_non_github_mirror(self, monkeypatch):
        """⑤ 默认（都不传 allowed_check / extra_hosts）→ 非 github 镜像被**拒绝**（fail-closed）。"""
        import gui.update_checker as uc

        monkeypatch.setattr(uc, "is_allowed_url", _fake_is_allowed_url, raising=False)
        asset = {
            "url": "https://github.com/o/r/releases/download/v2/x.zip",
            "mirror": "https://mirror.example.com/x.zip",
        }
        chain = dl.build_url_chain(asset)          # 不传 extra_hosts：默认吃白名单
        assert chain == [asset["url"]]
        assert asset["mirror"] not in chain

    def test_explicit_allowed_check_takes_precedence(self, monkeypatch):
        """① 显式 allowed_check 完全接管（优先于默认白名单），即使 extra_hosts 为空。"""
        import gui.update_checker as uc

        monkeypatch.setattr(uc, "is_allowed_url", _fake_is_allowed_url, raising=False)
        asset = {
            "url": "https://github.com/o/r/x.zip",
            "mirror": "https://mirror.example.com/x.zip",
        }
        # allowed_check 放行一切 → 即使 extra_hosts=[] 也保留非 github 镜像（证明 ①>②）
        assert dl.build_url_chain(
            asset, allowed_check=lambda _u: True, extra_hosts=[]
        ) == [asset["url"], asset["mirror"]]
        # allowed_check 拒绝一切 → 即使 extra_hosts 给了镜像也拒绝（证明 ① 优先）
        assert dl.build_url_chain(
            asset, allowed_check=lambda _u: False, extra_hosts=["mirror.example.com"]
        ) == []

    def test_make_download_worker_forwards_extra_hosts(self, monkeypatch, tmp_path):
        """★ make_download_worker 把 extra_hosts 透传到 build_url_chain（核对）。"""
        import gui.update_checker as uc
        import gui.utils as utils

        monkeypatch.setattr(uc, "is_allowed_url", _fake_is_allowed_url, raising=False)
        monkeypatch.setattr(utils, "get_user_data_dir", lambda: tmp_path)
        asset = {
            "url": "https://github.com/o/r/releases/download/v2/MaLing_v2.0.0_Desktop.zip",
            "mirror": "https://mirror.example.com/MaLing_v2.0.0_Desktop.zip",
            "sha256": "a" * 64,
            "size": 1,
        }
        w_blocked = dl.make_download_worker(asset, "2.0.0")            # 默认 fail-closed
        assert list(w_blocked._urls) == [asset["url"]]                 # noqa: SLF001
        w_ok = dl.make_download_worker(
            asset, "2.0.0", extra_hosts=["mirror.example.com"]
        )
        assert list(w_ok._urls) == [asset["url"], asset["mirror"]]     # noqa: SLF001

    def test_make_allowed_check_forwards_extra_hosts(self, monkeypatch):
        """make_allowed_check 以 extra_hosts 关键字委托域1 权威实现。"""
        import gui.update_checker as uc

        captured: dict = {}

        def _spy(url, extra_hosts=None):
            captured["url"] = url
            captured["extra"] = extra_hosts
            return True

        monkeypatch.setattr(uc, "is_allowed_url", _spy, raising=False)
        check = dl.make_allowed_check(["mirror.example.com"])
        assert check("https://mirror.example.com/x.zip") is True
        assert captured["extra"] == ["mirror.example.com"]

    def test_make_allowed_check_import_failure_still_fails_safe(self, monkeypatch):
        """③ import 失败路径：保守回退仍拒 http:// 与 `..` 注入（fail-safe 非放宽）。"""
        monkeypatch.setitem(sys.modules, "gui.update_checker", None)  # 触发 ImportError
        check = dl.make_allowed_check()
        assert check("http://evil.example.com/x.zip") is False      # 非 https
        assert check("https://evil.example.com/a/../b.zip") is False  # .. 注入
        assert check("\\\\srv\\share\\x.zip") is False               # UNC
        assert check("https://github.com/ok.zip") is True          # 合法 https 仍放行

    def test_resume_offset(self, tmp_path):
        assert dl.resume_offset(tmp_path / "none.part") == 0
        p = tmp_path / "a.part"
        p.write_bytes(b"x" * 1234)
        assert dl.resume_offset(p) == 1234
        d = tmp_path / "adir"
        d.mkdir()
        assert dl.resume_offset(d) == 0

    def test_progress_percent_monotonic(self):
        vals = [dl.progress_percent(r, 1000) for r in range(0, 1100, 37)]
        assert vals == sorted(vals)          # 单调不减
        assert dl.progress_percent(0, 1000) == 0
        assert dl.progress_percent(1000, 1000) == 100
        assert dl.progress_percent(5000, 1000) == 100
        assert dl.progress_percent(10, 0) == 0

    def test_progress_text_skeleton_and_no_anxiety(self):
        text = dl.progress_text(117 * 1024 * 1024, 248 * 1024 * 1024, 2.3 * 1024 * 1024, 72)
        assert "%" in text and "MB" in text and "/s" in text and "剩余" in text
        for banned in ("失败", "落后", "还剩", "第"):
            assert banned not in text
        # 未知长度：退化但不崩
        assert "MB" in dl.progress_text(5 * 1024 * 1024, 0)

    def test_verify_sha256_correct_and_tampered(self, tmp_path):
        data = bytes(range(256)) * 40
        p = tmp_path / "pkg.bin"
        p.write_bytes(data)
        good = _sha256(data)
        assert dl.verify_sha256(p, good) is True
        # 篡改 1 字节
        tampered = bytearray(data)
        tampered[100] ^= 0xFF
        p.write_bytes(bytes(tampered))
        assert dl.verify_sha256(p, good) is False
        # 缺失 / 非法 expected → False（Q-U5）
        assert dl.verify_sha256(p, "") is False
        assert dl.verify_sha256(p, None) is False
        assert dl.verify_sha256(p, "zzz") is False
        assert dl.verify_sha256(tmp_path / "nope.bin", good) is False

    def test_disk_precheck(self, tmp_path):
        huge = 10 ** 15
        ok, reason = dl.disk_precheck(tmp_path, huge)
        assert ok is False and reason == dl.ERR_DISK_SPACE_LOW
        ok2, reason2 = dl.disk_precheck(tmp_path, 1024)
        assert ok2 is True and reason2 == ""
        assert dl.disk_precheck(tmp_path, 0) == (True, "")

    def test_is_install_writable(self, tmp_path):
        assert dl.is_install_writable(tmp_path) is True
        # 探针必须清理干净，不留垃圾
        assert [p.name for p in tmp_path.iterdir()] == []
        assert dl.is_install_writable(tmp_path / "missing") is False
        f = tmp_path / "afile"
        f.write_text("x", encoding="utf-8")
        assert dl.is_install_writable(f) is False

    def test_is_install_writable_probe_error(self, tmp_path, monkeypatch):
        def _boom(*a, **kw):
            raise OSError("denied")

        monkeypatch.setattr("builtins.open", _boom)
        assert dl.is_install_writable(tmp_path) is False

    def test_asset_filename_and_sha256_line(self):
        assert dl.asset_filename_for("2.0.0", "onedir") == "MaLing_v2.0.0_Desktop.zip"
        assert dl.asset_filename_for("v2.0.0", "onefile") == "MaLing_v2.0.0_Portable.exe"
        assert dl.ASSET_FILENAME_RE.match("MaLing_v2.0.0_Desktop.zip")
        assert dl.ASSET_FILENAME_RE.match("MaLing_v2.0.0_Portable.exe")
        assert not dl.ASSET_FILENAME_RE.match("maling_2.0.0.zip")
        # .sha256 内容格式 `<hash>  <filename>`（两空格，Q-U2）
        digest = "a" * 64
        line = dl.sha256_file_line(digest, "MaLing_v2.0.0_Desktop.zip")
        assert line == f"{digest}  MaLing_v2.0.0_Desktop.zip"
        assert dl.parse_sha256_file(line) == (digest, "MaLing_v2.0.0_Desktop.zip")
        assert dl.parse_sha256_file("garbage") is None

    def test_make_download_worker_staging_path_l2_5(self, monkeypatch, tmp_path):
        """L2-5：产物落 %APPDATA%/.../updates/<version>/，绝不写安装目录。"""
        import gui.utils as utils

        monkeypatch.setattr(utils, "get_user_data_dir", lambda: tmp_path)
        asset = {
            "url": "https://github.com/o/r/releases/download/v2/MaLing_v2.0.0_Desktop.zip",
            "mirror": "https://mirror.example.com/MaLing_v2.0.0_Desktop.zip",
            "sha256": "a" * 64,
            "size": 123,
        }
        w = dl.make_download_worker(asset, "2.0.0")
        assert w.dest_path.parent == tmp_path / "updates" / "2.0.0"
        assert w.dest_path.name == "MaLing_v2.0.0_Desktop.zip"
        assert "updates" in w.dest_path.parts
        assert w.isRunning() is False

    def test_make_download_worker_filename_traversal_falls_back(self, monkeypatch, tmp_path):
        """L2-7 + R-M：非法 filename（含 .. 或路径分隔）回退 url 末段推导。"""
        import gui.utils as utils

        monkeypatch.setattr(utils, "get_user_data_dir", lambda: tmp_path)
        asset = {
            "url": "https://github.com/o/r/releases/download/v2/MaLing_v2.0.0_Portable.exe",
            "filename": "../evil.exe",
            "sha256": "",
            "size": 0,
        }
        w = dl.make_download_worker(asset, "2.0.0")
        assert w.dest_path.name == "MaLing_v2.0.0_Portable.exe"
        assert ".." not in w.dest_path.parts


# ===========================================================================
# 二、DownloadWorker
# ===========================================================================
CONTENT = bytes(range(256)) * 4096  # 1MB 确定性内容


class TestDownloadWorker:
    def _worker(self, tmp_path, urls, content=CONTENT, **kw):
        dest = tmp_path / "pkg.zip"
        params = dict(
            urls=urls,
            dest_path=dest,
            expected_sha256=kw.pop("expected_sha256", _sha256(content)),
            total_size=kw.pop("total_size", len(content)),
            retry_per_link=kw.pop("retry_per_link", 1),
            backoff=(0.01, 0.02, 0.03),
            chunk_size=kw.pop("chunk_size", 64 * 1024),
        )
        params.update(kw)
        return dl.DownloadWorker(**params), dest

    def test_fresh_download_verified(self, qapp, server, tmp_path):
        s = server(CONTENT)
        w, dest = self._worker(tmp_path, [s.url("/pkg.zip")])
        rec = Recorder(w)
        _run_worker(qapp, w, rec)
        assert rec.failed == []
        assert rec.verified == [str(dest)]
        assert rec.finished == [str(dest)]
        assert dest.read_bytes() == CONTENT
        assert not Path(str(dest) + ".part").exists()
        assert (tmp_path / ".verified").is_file()

    def test_range_resume_206_asserts_range_header(self, qapp, server, tmp_path):
        s = server(CONTENT)
        dest = tmp_path / "pkg.zip"
        part = Path(str(dest) + ".part")
        offset = 300 * 1024
        part.write_bytes(CONTENT[:offset])  # 模拟断点

        w = dl.DownloadWorker(
            urls=[s.url("/pkg.zip")],
            dest_path=dest,
            expected_sha256=_sha256(CONTENT),
            total_size=len(CONTENT),
            retry_per_link=1,
            chunk_size=64 * 1024,
        )
        rec = Recorder(w)
        _run_worker(qapp, w, rec)

        assert rec.verified == [str(dest)]
        assert dest.read_bytes() == CONTENT
        headers = s.request_log[0][1]
        assert headers.get("Range") == f"bytes={offset}-"      # L2-2 验收①
        assert dl.resume_offset(part) == 0                     # 已落成品
        assert not part.exists()

    def test_range_unsupported_200_restarts_no_duplicate(self, qapp, server, tmp_path):
        s = server(CONTENT, support_range=False)  # 永远 200
        dest = tmp_path / "pkg.zip"
        part = Path(str(dest) + ".part")
        part.write_bytes(b"GARBAGE" * 500)  # 脏半包

        w = dl.DownloadWorker(
            urls=[s.url("/pkg.zip")],
            dest_path=dest,
            expected_sha256=_sha256(CONTENT),
            total_size=len(CONTENT),
            retry_per_link=1,
            chunk_size=64 * 1024,
        )
        rec = Recorder(w)
        _run_worker(qapp, w, rec)

        assert rec.verified == [str(dest)]
        assert dest.read_bytes() == CONTENT                    # 无重复字节
        assert dest.stat().st_size == len(CONTENT)             # L2-2 验收②③

    def test_fallback_chain_url_sequence(self, qapp, server, tmp_path):
        s = server(CONTENT, fail_paths={"/bad.zip"})
        w, dest = self._worker(
            tmp_path, [s.url("/bad.zip"), s.url("/good.zip")], retry_per_link=1
        )
        rec = Recorder(w)
        _run_worker(qapp, w, rec)

        assert rec.verified == [str(dest)]
        assert [p for p, _ in s.request_log] == ["/bad.zip", "/good.zip"]  # L2-3 验收①
        assert dest.read_bytes() == CONTENT

    def test_all_links_failed_keeps_part(self, qapp, server, tmp_path):
        s = server(CONTENT, fail_paths={"/a.zip", "/b.zip"})
        dest = tmp_path / "pkg.zip"
        part = Path(str(dest) + ".part")
        prior = b"x" * 4096
        part.write_bytes(prior)

        w = dl.DownloadWorker(
            urls=[s.url("/a.zip"), s.url("/b.zip")],
            dest_path=dest,
            expected_sha256=_sha256(CONTENT),
            total_size=len(CONTENT),
            retry_per_link=1,
        )
        rec = Recorder(w)
        _run_worker(qapp, w, rec)

        assert rec.failed == [dl.ERR_ALL_LINKS_FAILED]     # L2-3 验收③
        assert part.exists() and part.read_bytes() == prior
        assert not dest.exists()

    def test_cancel_stops_within_1s_and_keeps_part(self, qapp, server, tmp_path):
        s = server(CONTENT, chunk=32 * 1024, delay=0.02)  # 慢速流
        dest = tmp_path / "pkg.zip"
        part = Path(str(dest) + ".part")
        w = dl.DownloadWorker(
            urls=[s.url("/pkg.zip")],
            dest_path=dest,
            expected_sha256=_sha256(CONTENT),
            total_size=len(CONTENT),
            retry_per_link=1,
            chunk_size=16 * 1024,
        )
        rec = Recorder(w)
        w.start()
        assert _wait_until(qapp, lambda: bool(rec.progress), timeout=10)  # 已有写入
        t0 = time.monotonic()
        w.request_cancel()
        assert _wait_until(
            qapp, lambda: rec.cancelled == 1 and not w.isRunning(), timeout=3
        )
        assert time.monotonic() - t0 <= 1.0                  # ≤1s 停止（L2-1 验收③）
        assert part.exists() and part.stat().st_size > 0     # Q-U4 保留 .part
        assert not dest.exists()

    def test_sha256_mismatch_deletes_and_not_enters_l3(self, qapp, server, tmp_path):
        s = server(CONTENT)
        dest = tmp_path / "pkg.zip"
        w = dl.DownloadWorker(
            urls=[s.url("/pkg.zip")],
            dest_path=dest,
            expected_sha256=_sha256(b"different"),
            total_size=len(CONTENT),
            retry_per_link=1,
        )
        rec = Recorder(w)
        _run_worker(qapp, w, rec)

        assert rec.failed == [dl.ERR_SHA256_MISMATCH]        # L2-4 验收②
        assert not dest.exists()                             # 成品已删除
        assert not (tmp_path / ".verified").exists()
        assert rec.verified == []

    def test_disk_low_sends_no_first_get(self, qapp, server, tmp_path):
        s = server(CONTENT)
        dest = tmp_path / "pkg.zip"
        w = dl.DownloadWorker(
            urls=[s.url("/pkg.zip")],
            dest_path=dest,
            expected_sha256=_sha256(CONTENT),
            total_size=10 ** 15,                             # 空间必然不足
            retry_per_link=1,
        )
        rec = Recorder(w)
        _run_worker(qapp, w, rec)

        assert rec.failed == [dl.ERR_DISK_SPACE_LOW]         # L2-6 验收①
        assert s.request_log == []                           # 不发第一个 GET
        assert not dest.exists()

    def test_no_urls_fails_cleanly(self, qapp, tmp_path):
        w = dl.DownloadWorker(urls=[], dest_path=tmp_path / "x.zip")
        rec = Recorder(w)
        _run_worker(qapp, w, rec)
        assert rec.failed == [dl.ERR_NO_URLS]


# ===========================================================================
# 三、进度对话框（R-A 非阻断 + 信号接线）
# ===========================================================================
class TestUpdateProgressDialog:
    def test_nomodal_and_buttons(self, qapp):
        from gui.widgets.update_progress import UpdateProgressDialog

        dlg = UpdateProgressDialog()
        assert dlg.isModal() is False                        # R-A 非阻断
        assert dlg.background_btn.text() == "后台继续"
        assert dlg.cancel_btn.text() == "取消"
        dlg.close()

    def test_begin_wires_worker_signals(self, qapp, server, tmp_path):
        from gui.widgets.update_progress import UpdateProgressDialog

        s = server(CONTENT)
        dest = tmp_path / "pkg.zip"
        w = dl.DownloadWorker(
            urls=[s.url("/pkg.zip")],
            dest_path=dest,
            expected_sha256=_sha256(CONTENT),
            total_size=len(CONTENT),
            retry_per_link=1,
            chunk_size=64 * 1024,
        )
        dlg = UpdateProgressDialog()
        seen = {"verified": [], "failed": []}
        dlg.download_verified.connect(lambda p: seen["verified"].append(p))
        dlg.download_failed.connect(lambda r: seen["failed"].append(r))
        dlg.begin(w)                                          # 只连线 + show，不启动
        assert w.isRunning() is False
        w.start()
        assert _wait_until(qapp, lambda: bool(seen["verified"]), timeout=20)
        assert seen["verified"] == [str(dest)]
        assert dlg.bar.value() == 100
        dlg.close()

    def test_failure_text_has_no_anxiety_terms(self, qapp):
        from gui.widgets.update_progress import UpdateProgressDialog, _friendly_failure

        for reason in (dl.ERR_ALL_LINKS_FAILED, dl.ERR_DISK_SPACE_LOW, dl.ERR_SHA256_MISMATCH):
            text = _friendly_failure(reason)
            for banned in ("失败 N", "落后", "还剩", "第", "次数"):
                assert banned not in text
        dlg = UpdateProgressDialog()
        dlg._on_failed(dl.ERR_ALL_LINKS_FAILED)               # noqa: SLF001
        assert "重试" in dlg.title_label.text()
        dlg.close()

    def test_cancel_button_calls_request_cancel(self, qapp):
        from gui.widgets.update_progress import UpdateProgressDialog

        calls = {"n": 0}

        class _FakeWorker:
            progress = finished = verified = failed = cancelled = None

            def request_cancel(self):
                calls["n"] += 1

        fake = _FakeWorker()
        # 直接注入，绕过信号连接（_FakeWorker 无真信号）
        dlg = UpdateProgressDialog()
        dlg._worker = fake                                    # noqa: SLF001
        dlg._on_cancel()                                      # noqa: SLF001
        assert calls["n"] == 1
        dlg.close()
