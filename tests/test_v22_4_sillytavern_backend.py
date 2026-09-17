"""内置 SillyTavern 子进程管理器（``tavern_backend.py``）的单元测试。

设计原则
--------
- **绝不真启动 ST**：会拖慢全量回归（冷启动 14~52s），且依赖 vendor 依赖树。
  全部用 monkeypatch 隔离，保证用例快速且与环境无关。
- 覆盖的都是**本轮实测得出的硬约束**，改坏即红：
  * 崩溃码 ``0xC0000409`` / ``0xC0000005`` 必须映射成可读提示（P2-1 同源）
  * 就绪探测**不走代理**，且 **5xx 不算就绪**（P2-2）
  * 启动命令行必须带 ``--require`` / ``--configPath`` / ``--browserLaunchEnabled``
  * ``stop()`` 幂等、``start()`` 幂等
  * 用户数据目录必须落在 ``%APPDATA%``，绝不能落在 ST 源码目录（方案 §4）
"""
from __future__ import annotations

import socket
import sys
import urllib.error
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import tavern_backend as tb  # noqa: E402  (需先补 sys.path)


# --------------------------------------------------------------------------
# 测试替身
# --------------------------------------------------------------------------
class _FakeResp:
    """模拟 ``urlopen`` 返回的响应对象（支持 ``with ... as resp``）。"""

    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


class _FakeOpener:
    """模拟 ``_no_proxy_opener()`` 的返回值，可指定状态码或抛出的异常。"""

    def __init__(self, status: int | None = None, exc: Exception | None = None) -> None:
        self._status = status
        self._exc = exc
        self.calls: list = []

    def open(self, url, timeout=None):
        self.calls.append((url, timeout))
        if self._exc is not None:
            raise self._exc
        return _FakeResp(self._status)


class _FakeProc:
    """模拟 subprocess.Popen：terminate 后 poll() 返回 0，避免触发 taskkill 兜底。"""

    def __init__(self) -> None:
        self.pid = 1234
        self.stdout = None
        self._rc: int | None = None

    def poll(self):
        return self._rc

    def terminate(self) -> None:
        self._rc = 0

    def kill(self) -> None:
        self._rc = 0

    def wait(self, timeout=None) -> int:
        return 0


def _backend_with_url() -> "tb.TavernBackend":
    b = tb.TavernBackend()
    b.port = 8754
    b.base_url = "http://127.0.0.1:8754/"
    return b


# --------------------------------------------------------------------------
# 常量与崩溃码映射
# --------------------------------------------------------------------------
def test_startup_timeout_and_port_pool_constants():
    # 90s 是实测结论：冷启动 31.2s / 49.7s，方案原值 30s 会误判失败
    assert tb.STARTUP_TIMEOUT_S == 90.0
    assert tb.PORT_POOL_START == 8754
    assert tb.PORT_POOL_END == 9000


def test_crash_codes_cover_both_known_ntstatus_codes():
    assert 3221226505 in tb._CRASH_CODES          # 0xC0000409
    assert 3221225477 in tb._CRASH_CODES          # 0xC0000005
    assert "0xC0000409" in tb._CRASH_CODES[3221226505]
    assert "0xC0000005" in tb._CRASH_CODES[3221225477]


def test_early_exit_maps_stack_buffer_overrun_to_readable_hint():
    msg = tb.TavernBackend()._format_early_exit(3221226505)
    assert "0xC0000409" in msg
    assert "--require" in msg            # 必须提示补丁
    assert "fs.cpSync" in msg or "nodejs/node#54476" in msg


def test_early_exit_maps_access_violation_to_readable_hint():
    msg = tb.TavernBackend()._format_early_exit(3221225477)
    assert "0xC0000005" in msg
    assert "ACCESS_VIOLATION" in msg


def test_early_exit_non_crash_code_is_still_readable():
    msg = tb.TavernBackend()._format_early_exit(1)
    assert "1" in msg
    assert "0xC0000409" not in msg       # 普通退出不该张冠李戴


# --------------------------------------------------------------------------
# 端口
# --------------------------------------------------------------------------
def test_find_free_port_returns_bindable_port_in_range():
    port = tb._find_free_port(tb.PORT_POOL_START, tb.PORT_POOL_END)
    assert tb.PORT_POOL_START <= port <= tb.PORT_POOL_END
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", port))


# --------------------------------------------------------------------------
# HTTP 就绪探测（P2-2）
# --------------------------------------------------------------------------
def test_http_ready_true_on_2xx(monkeypatch):
    b = _backend_with_url()
    monkeypatch.setattr(tb, "_no_proxy_opener", lambda: _FakeOpener(status=200))
    assert b._http_ready() is True


def test_http_ready_true_on_4xx(monkeypatch):
    """4xx 算就绪：服务器已在应答、路由已挂上。"""
    b = _backend_with_url()
    exc = urllib.error.HTTPError("u", 404, "Not Found", {}, None)
    monkeypatch.setattr(tb, "_no_proxy_opener", lambda: _FakeOpener(exc=exc))
    assert b._http_ready() is True


def test_http_ready_false_on_5xx(monkeypatch):
    """5xx 不算就绪 —— 这正是 P2-2 修复的 bug（代理 502 曾被误判为就绪）。"""
    b = _backend_with_url()
    exc = urllib.error.HTTPError("u", 502, "Bad Gateway", {}, None)
    monkeypatch.setattr(tb, "_no_proxy_opener", lambda: _FakeOpener(exc=exc))
    assert b._http_ready() is False


def test_no_proxy_opener_ignores_env_proxy(monkeypatch):
    """回归守卫（P2-2）：即便环境里设了 HTTP_PROXY，回环探测也不得走代理。

    原理：``build_opener(ProxyHandler({}))`` 会让 build_opener **跳过默认的
    ProxyHandler**（那个才会去读环境变量）。

    ⚠ 注意：``ProxyHandler({})`` 因 proxies 为空而不具备 ``<type>_open`` 方法，
    **不会**出现在 ``opener.handlers`` 里。所以这里断言的目标不是"存在一个空的
    ProxyHandler"，而是"不存在任何带非空 proxies 的 ProxyHandler"。
    """
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:64558")
    monkeypatch.setattr(tb, "_NO_PROXY_OPENER", None)      # 清缓存，强制重建
    opener = tb._no_proxy_opener()

    from urllib.request import ProxyHandler

    bad = [h for h in opener.handlers
           if isinstance(h, ProxyHandler) and getattr(h, "proxies", None)]
    assert bad == [], "opener 不得带来自环境变量的代理"


def test_no_proxy_opener_is_memoized():
    """惰性创建并复用，不要每次探测都新建 opener。"""
    assert tb._no_proxy_opener() is tb._no_proxy_opener()


def test_http_ready_does_not_fall_back_to_bare_urlopen():
    """回归守卫：不得退回裸 urlopen（会走 HTTP_PROXY，把 502 误判成就绪）。"""
    src = Path(tb.__file__).read_text(encoding="utf-8")
    assert "_no_proxy_opener()" in src
    assert "urllib.request.urlopen" not in src


# --------------------------------------------------------------------------
# 生命周期
# --------------------------------------------------------------------------
def test_stop_is_idempotent():
    b = tb.TavernBackend()
    b.stop()                      # proc 为 None
    b.stop()
    assert not b.is_running()
    assert b.port is None and b.base_url is None


def test_start_is_idempotent_when_already_running():
    b = tb.TavernBackend()
    b.proc = _FakeProc()
    b.port = 8754
    b.base_url = "http://127.0.0.1:8754/"
    assert b.start() == (8754, "http://127.0.0.1:8754/")


# --------------------------------------------------------------------------
# 缺件时的可读错误
# --------------------------------------------------------------------------
def test_start_raises_readable_error_when_node_missing(monkeypatch):
    monkeypatch.setattr(tb, "find_bundled_node_exe", lambda: None)
    with pytest.raises(RuntimeError) as ei:
        tb.TavernBackend().start()
    assert "node.exe" in str(ei.value)


def test_start_raises_readable_error_when_compat_patch_missing(monkeypatch):
    monkeypatch.setattr(tb, "find_bundled_node_exe", lambda: Path("x"))
    monkeypatch.setattr(tb, "find_node_compat", lambda: None)
    with pytest.raises(RuntimeError) as ei:
        tb.TavernBackend().start()
    assert "maling_node_compat.cjs" in str(ei.value)


def test_start_raises_readable_error_when_st_dir_missing(monkeypatch):
    monkeypatch.setattr(tb, "find_bundled_node_exe", lambda: Path("x"))
    monkeypatch.setattr(tb, "find_node_compat", lambda: Path("y"))
    monkeypatch.setattr(tb, "find_bundled_st_dir", lambda: None)
    with pytest.raises(RuntimeError) as ei:
        tb.TavernBackend().start()
    assert "sillytavern" in str(ei.value)


# --------------------------------------------------------------------------
# 启动命令行（每条都是实测得出的必需项）
# --------------------------------------------------------------------------
def test_start_builds_cmdline_with_all_required_flags(monkeypatch, tmp_path):
    captured: dict = {}

    def fake_popen(cmd, **kw):
        captured["cmd"] = list(cmd)
        captured["cwd"] = kw.get("cwd")
        return _FakeProc()

    monkeypatch.setattr(tb.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(tb, "find_bundled_node_exe", lambda: Path("N") / "node.exe")
    monkeypatch.setattr(tb, "find_node_compat", lambda: Path("C") / "maling_node_compat.cjs")
    monkeypatch.setattr(tb, "find_bundled_st_dir", lambda: Path("S") / "sillytavern")
    monkeypatch.setattr(tb.TavernBackend, "_wait_ready", lambda self: None)
    monkeypatch.setenv("APPDATA", str(tmp_path))

    b = tb.TavernBackend()
    port, url = b.start()
    cmd = captured["cmd"]

    assert "--require" in cmd
    assert any("maling_node_compat.cjs" in a for a in cmd)   # 非 ASCII 路径崩溃补丁
    assert "server.js" in cmd
    assert cmd[cmd.index("--listen") + 1] == "false"         # 只绑 127.0.0.1
    assert "--dataRoot" in cmd
    assert "--configPath" in cmd                             # 不把 config.yaml 写进 _internal/
    assert cmd[cmd.index("--browserLaunchEnabled") + 1] == "false"
    assert captured["cwd"].endswith("sillytavern")
    assert url == f"http://127.0.0.1:{port}/"

    b.stop()


# --------------------------------------------------------------------------
# 用户数据目录（方案 §4）
# --------------------------------------------------------------------------
def test_user_data_root_lives_under_appdata(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    root = tb._user_data_root()
    assert root == tmp_path / "maling" / "sillytavern" / "data"
    assert root.is_dir()


def test_user_data_root_is_never_inside_st_dir(monkeypatch, tmp_path):
    """ST 写入绝不能落进程序文件区（升级会被覆盖）。"""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    root = tb._user_data_root()
    st_dir = tb.find_bundled_st_dir()
    if st_dir is not None:
        assert str(st_dir) not in str(root)


# --------------------------------------------------------------------------
# 候选路径
# --------------------------------------------------------------------------
def test_candidate_lists_contain_expected_filenames():
    assert any(p.name == "node.exe" for p in tb.node_exe_candidates())
    assert any(p.name == tb.NODE_COMPAT_NAME for p in tb.node_compat_candidates())
    assert all(isinstance(p, Path) for p in tb.st_dir_candidates())
