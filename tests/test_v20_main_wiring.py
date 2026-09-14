"""tests/test_v20_main_wiring.py —— v2.0 域4（gui/main.py 编排接线）纯逻辑测试。

覆盖（design-v20 §5 批 C · V20-12/V20-13/V20-14）：
- `_compute_install_targets` / `_build_swap_plan`：plan.json 字段与**同卷落点**
  （staging/backup 必落 install_parent，不落 %APPDATA%）；
- plan.json 可被 sidecar `maling_updater.load_plan` 解析（schema/必填/同卷校验）；
- `_should_launch_updater` 守卫矩阵（dev 形态禁用替换 / pending / 校验 / 可写）；
- `_select_download_asset`（ok / no_remote / no_asset / no_sha256；dev→onedir 演练）；
- `_launch_updater_process` 的 creationflags 取值（**DETACHED_PROCESS | CREATE_NO_WINDOW**
  同存；且 stdin/stdout/stderr=DEVNULL、close_fds=True）；
- `_maybe_launch_updater` 编排：dev 跳过、守卫不过不启、happy-path 落 plan.json；
- `_resolve_remote` 只读域1 公开属性 `last_remote`（已摘除对私有 `_worker` 的兜底耦合）；
- `_release_page_url` / `_maybe_open_release_page`：Release 页入口闸（https 才出按钮）。

约束：**不真启 GUI、不真启进程、不联网**；临时目录文件数控制在 ~20 内。
"""
from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

import gui.main as m  # noqa: E402


# ---------------------------------------------------------------------------
# 版本 / 安装目标
# ---------------------------------------------------------------------------
def test_app_version_matches_version_json():
    from version import get_version
    assert m._app_version() == str(get_version())
    assert m._app_version()  # 非空


def test_compute_install_targets_onedir(tmp_path):
    exe = tmp_path / "apps" / "maling" / "maling.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("x", encoding="utf-8")
    t = m._compute_install_targets("onedir", exe_path=str(exe))
    assert t["install_dir"] == str((tmp_path / "apps" / "maling").resolve())
    assert t["install_parent"] == str((tmp_path / "apps").resolve())
    assert t["app_exe"] == str(exe.resolve())


def test_compute_install_targets_onefile(tmp_path):
    exe = tmp_path / "apps" / "MaLing_single.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("x", encoding="utf-8")
    t = m._compute_install_targets("onefile", exe_path=str(exe))
    assert t["install_dir"] == str((tmp_path / "apps").resolve())
    assert t["install_parent"] == str(tmp_path.resolve())


def test_compute_install_targets_dev(tmp_path):
    t = m._compute_install_targets("dev", project_dir=str(tmp_path))
    assert t["install_dir"] == str(tmp_path.resolve())
    assert t["app_exe"].endswith("run.py")


# ---------------------------------------------------------------------------
# plan.json 构造 + 同卷落点
# ---------------------------------------------------------------------------
_SHA = "a" * 64


def test_build_swap_plan_onedir_fields_and_same_volume(tmp_path):
    install_dir = tmp_path / "apps" / "maling"
    install_dir.mkdir(parents=True)
    plan = m._build_swap_plan(
        target_version="2.0.0", from_version="1.9.0", app_pid=1234,
        app_exe=str(install_dir / "maling.exe"), install_dir=str(install_dir),
        package_path=str(tmp_path / "pkg.zip"), package_sha256=_SHA,
        confirm_dir=str(tmp_path / "updater"), action="swap_onedir",
        log_path=str(tmp_path / "updater" / "logs" / "u.log"),
    )
    assert plan["schema"] == 1
    assert plan["action"] == "swap_onedir"
    assert plan["target_version"] == "2.0.0"
    assert plan["from_version"] == "1.9.0"
    assert plan["app_pid"] == 1234
    assert plan["install_parent"] == str(tmp_path / "apps")
    # 同卷铁律：staging/backup 落 install_parent，绝不落 %APPDATA%
    parent = str(tmp_path / "apps")
    assert plan["staging_dir"] == str((tmp_path / "apps" / ".maling_new_2.0.0"))
    assert plan["backup_dir"] == str((tmp_path / "apps" / ".maling_backup_1.9.0"))
    assert os.path.dirname(plan["staging_dir"]) == parent
    assert os.path.dirname(plan["backup_dir"]) == parent
    assert plan["confirm_timeout_sec"] == 45
    assert plan["kill_timeout_sec"] == 20


def test_build_swap_plan_onefile_no_staging(tmp_path):
    install_dir = tmp_path / "apps"
    install_dir.mkdir(parents=True)
    plan = m._build_swap_plan(
        target_version="2.0.0", from_version="1.9.0", app_pid=1,
        app_exe=str(install_dir / "MaLing_single.exe"), install_dir=str(install_dir),
        package_path=str(tmp_path / "pkg.exe"), package_sha256=_SHA,
        confirm_dir=str(tmp_path / "updater"), action="swap_onefile",
    )
    assert plan["action"] == "swap_onefile"
    assert plan["staging_dir"] is None
    assert plan["backup_dir"] is None


def test_plan_parsable_by_sidecar_load_plan(tmp_path):
    """生成的 plan.json 必须被 sidecar 的 load_plan 接受（schema/必填/同卷）。"""
    from maling_updater import load_plan
    install_dir = tmp_path / "apps" / "maling"
    install_dir.mkdir(parents=True)
    plan = m._build_swap_plan(
        target_version="2.0.0", from_version="1.9.0", app_pid=9,
        app_exe=str(install_dir / "maling.exe"), install_dir=str(install_dir),
        package_path=str(tmp_path / "pkg.zip"), package_sha256=_SHA,
        confirm_dir=str(tmp_path / "updater"), action="swap_onedir",
        log_path=str(tmp_path / "updater" / "logs" / "u.log"),
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    parsed = load_plan(str(plan_path))
    assert parsed.schema == 1
    assert parsed.action == "swap_onedir"
    assert parsed.staging_dir == plan["staging_dir"]


# ---------------------------------------------------------------------------
# 守卫矩阵
# ---------------------------------------------------------------------------
def _pending_state(**over):
    st = {"pending_install": True, "pending_version": "2.0.0"}
    st.update(over)
    return st


def test_should_launch_dev_disabled():
    assert m._should_launch_updater(
        _pending_state(), "dev", package_verified=True, install_writable=True) is False


@pytest.mark.parametrize("form", ["onedir", "onefile"])
def test_should_launch_happy(form):
    assert m._should_launch_updater(
        _pending_state(), form, package_verified=True, install_writable=True) is True


def test_should_launch_requires_pending():
    st = {"pending_version": "2.0.0"}
    assert m._should_launch_updater(
        st, "onedir", package_verified=True, install_writable=True) is False


def test_should_launch_requires_version():
    st = {"pending_install": True, "pending_version": ""}
    assert m._should_launch_updater(
        st, "onedir", package_verified=True, install_writable=True) is False


def test_should_launch_requires_verified_and_writable():
    st = _pending_state()
    assert m._should_launch_updater(
        st, "onedir", package_verified=False, install_writable=True) is False
    assert m._should_launch_updater(
        st, "onedir", package_verified=True, install_writable=False) is False


def test_should_launch_bad_state():
    assert m._should_launch_updater(None, "onedir",
                                    package_verified=True, install_writable=True) is False


# ---------------------------------------------------------------------------
# 资产选择
# ---------------------------------------------------------------------------
_REMOTE = {
    "version": "2.0.0",
    "downloads": {"github": "https://github.com/o/m/releases/download/v2/a.zip", "mirror": ""},
    "assets": {
        "onedir": {"url": "https://github.com/o/m/releases/download/v2/a.zip",
                   "mirror": "", "sha256": _SHA, "size": 100, "filename": "a.zip"},
        "single": {"url": "https://github.com/o/m/releases/download/v2/a.exe",
                   "mirror": "", "sha256": _SHA, "size": 100, "filename": "a.exe"},
    },
}


def test_select_asset_ok_onedir():
    asset, reason = m._select_download_asset(_REMOTE, {}, "onedir")
    assert reason == "ok"
    assert asset is _REMOTE["assets"]["onedir"]


def test_select_asset_ok_onefile():
    asset, reason = m._select_download_asset(_REMOTE, {}, "onefile")
    assert reason == "ok"
    assert asset is _REMOTE["assets"]["single"]


def test_select_asset_dev_rehearses_onedir():
    asset, reason = m._select_download_asset(_REMOTE, {}, "dev")
    assert reason == "ok"
    assert asset is _REMOTE["assets"]["onedir"]


def test_select_asset_no_remote_but_primary_fallback_no_sha():
    info = {"primary": "https://github.com/o/m/releases/download/v2/a.zip", "mirror": ""}
    asset, reason = m._select_download_asset(None, info, "onedir")
    assert reason == "no_sha256"  # 兜底 asset 无 sha256 → 禁止自动替换（Q-U5）
    assert asset["url"] == info["primary"]


def test_select_asset_no_asset_no_primary():
    asset, reason = m._select_download_asset({"version": "2.0.0"}, {}, "onedir")
    assert asset is None
    assert reason == "no_asset"


def test_select_asset_missing_sha256():
    remote = {
        "assets": {"onedir": {"url": "https://github.com/o/m/a.zip", "mirror": ""}},
    }
    asset, reason = m._select_download_asset(remote, {}, "onedir")
    assert reason == "no_sha256"
    assert asset is not None


def test_select_asset_bad_sha256():
    remote = {"assets": {"onedir": {"url": "https://github.com/o/m/a.zip", "sha256": "xyz"}}}
    _, reason = m._select_download_asset(remote, {}, "onedir")
    assert reason == "no_sha256"


# ---------------------------------------------------------------------------
# 自动更新门闸
# ---------------------------------------------------------------------------
def test_can_auto_update_ok():
    assert m._can_auto_update({"kind": "update"}, "ok") is True


def test_can_auto_update_reinstall_blocked():
    assert m._can_auto_update({"kind": "reinstall"}, "ok") is False


def test_can_auto_update_no_sha_blocked():
    assert m._can_auto_update({"kind": "update"}, "no_sha256") is False
    assert m._can_auto_update({"kind": "update"}, "no_asset") is False


# ---------------------------------------------------------------------------
# min_updatable 能力闸（与 min_compatible 正交）
# ---------------------------------------------------------------------------
def test_below_min_updatable_true():
    assert m._below_min_updatable({"min_updatable": "2.0.0"}, "1.9.0") is True


def test_below_min_updatable_equal_or_newer_false():
    assert m._below_min_updatable({"min_updatable": "2.0.0"}, "2.0.0") is False
    assert m._below_min_updatable({"min_updatable": "1.5.0"}, "2.0.0") is False


def test_below_min_updatable_missing_no_limit():
    assert m._below_min_updatable({}, "1.0.0") is False
    assert m._below_min_updatable(None, "1.0.0") is False
    assert m._below_min_updatable({"min_updatable": ""}, "1.0.0") is False


def test_below_min_updatable_from_info_fallback():
    assert m._below_min_updatable(None, "1.0.0",
                                  info={"min_updatable": "2.0.0"}) is True


def test_can_auto_update_below_min_updatable_blocked(monkeypatch):
    monkeypatch.setattr(m, "_app_version", lambda: "1.9.0")
    assert m._can_auto_update({"kind": "update"}, "ok",
                              remote={"min_updatable": "2.0.0"}) is False


def test_can_auto_update_min_updatable_absent_allows(monkeypatch):
    monkeypatch.setattr(m, "_app_version", lambda: "1.9.0")
    assert m._can_auto_update({"kind": "update"}, "ok", remote={}) is True


def test_should_launch_min_updatable_block():
    assert m._should_launch_updater(
        _pending_state(), "onedir", package_verified=True,
        install_writable=True, min_updatable_block=True) is False


# ---------------------------------------------------------------------------
# 取原始 remote：只读域1 公开属性 last_remote（私有 _worker 兜底已摘除）
# ---------------------------------------------------------------------------
class _CheckerWithRemote:
    last_remote = {"version": "2.0.0", "assets": {}}


class _CheckerWithoutRemote:
    pass


def test_resolve_remote_reads_public_last_remote(monkeypatch):
    monkeypatch.setitem(m._update_ctx, "checker", _CheckerWithRemote())
    assert m._resolve_remote()["version"] == "2.0.0"


def test_resolve_remote_none_without_last_remote(monkeypatch):
    # 私有捕获已摘除：checker 无 last_remote 时即便 ctx 残留 remote 也一律返回 None
    monkeypatch.setitem(m._update_ctx, "checker", _CheckerWithoutRemote())
    monkeypatch.setitem(m._update_ctx, "remote", {"version": "1.0.0"})
    assert m._resolve_remote() is None


def test_resolve_remote_none(monkeypatch):
    monkeypatch.setitem(m._update_ctx, "checker", None)
    assert m._resolve_remote() is None


def test_select_asset_from_info_payload():
    # remote 缺失时回退用 info 载荷的 assets（域1 新载荷）
    asset, reason = m._select_download_asset(None, _REMOTE, "onedir")
    assert reason == "ok"
    assert asset is _REMOTE["assets"]["onedir"]


# ---------------------------------------------------------------------------
# Release 页入口（兑现 design-v20 §4.1：`release_url` = "查看完整更新内容"）
# ---------------------------------------------------------------------------
def test_release_page_url_accepts_https():
    url = "https://github.com/o/m/releases/tag/v2.0.0"
    assert m._release_page_url({"release_url": url}) == url


def test_release_page_url_gate_missing_or_non_https():
    # 缺失 / 空 / 非 https → ""（不出按钮）
    assert m._release_page_url({"release_url": None}) == ""
    assert m._release_page_url({}) == ""
    assert m._release_page_url(None) == ""
    assert m._release_page_url({"release_url": ""}) == ""
    assert m._release_page_url({"release_url": "http://github.com/o/m"}) == ""
    assert m._release_page_url({"release_url": "javascript:alert(1)"}) == ""


def test_release_click_opens_via_injected_opener():
    seen = []
    url = "https://github.com/o/m/releases/tag/v2.0.0"
    # 有 https release_url → 经注入 opener 打开一次并返回 True（不真开浏览器）
    assert m._maybe_open_release_page({"release_url": url}, opener=seen.append) is True
    assert seen == [url]
    # 缺失 / 非 https → 不调 opener、返回 False
    assert m._maybe_open_release_page({}, opener=seen.append) is False
    assert m._maybe_open_release_page({"release_url": "http://x"}, opener=seen.append) is False
    assert seen == [url]


# ---------------------------------------------------------------------------
# 与域1（update_checker）冻结接口的集成断言
# ---------------------------------------------------------------------------
def test_integration_evaluate_update_payload_has_new_keys():
    from gui.update_checker import evaluate_update
    remote = {
        "version": "2.0.0",
        "downloads": {"github": "https://github.com/o/m/releases/download/v2/a.zip"},
        "assets": {"onedir": {"url": "https://github.com/o/m/a.zip", "sha256": _SHA}},
        "min_updatable": "1.5.0",
        "release_url": "https://github.com/o/m/releases/tag/v2.0.0",
    }
    result = evaluate_update(remote, "1.0.0", None)
    assert result is not None
    for key in ("kind", "version", "notes", "primary", "mirror",
                "assets", "min_updatable", "release_url"):
        assert key in result  # 前五键零变更 + 后三键纯增量
    assert result["min_updatable"] == "1.5.0"
    # 载荷 → 入口闸闭环：release_url 经域1 载荷透到「查看完整更新内容」按钮
    assert m._release_page_url(result) == "https://github.com/o/m/releases/tag/v2.0.0"


def test_integration_update_checker_has_public_last_remote():
    from gui.update_checker import UpdateChecker
    assert hasattr(UpdateChecker, "last_remote")  # 公开只读属性（去私有耦合）
    import gui.main as _m  # noqa: F401 确认 main 与该接口可共存导入


def test_integration_resolve_remote_with_real_checker():
    """用真实 UpdateChecker 实例验证 _resolve_remote 走公开属性分支。"""
    from gui.update_checker import UpdateChecker
    checker = UpdateChecker(parent=None)
    assert checker.last_remote is None
    checker._last_remote = {"version": "2.0.0", "assets": {}}
    import gui.main as _m
    _m._update_ctx["checker"] = checker
    try:
        assert _m._resolve_remote() == {"version": "2.0.0", "assets": {}}
    finally:
        _m._update_ctx.pop("checker", None)


# ---------------------------------------------------------------------------
# 启动自举：消费 last_result → 清 pending（防自替换循环）
# ---------------------------------------------------------------------------
def test_bootstrap_clears_pending_after_last_result(monkeypatch, tmp_path):
    monkeypatch.setattr(m, "detect_install_form", lambda: "onedir")
    captured = {}

    def _fake_save(patch):
        captured.update(patch)

    monkeypatch.setattr(m, "save_update_state", _fake_save)
    monkeypatch.setattr(m, "load_update_state",
                        lambda: {"pending_install": True, "pending_version": "2.0.0"})
    import maling_updater as up
    monkeypatch.setattr(up, "ensure_self_installed", lambda *a, **k: None)
    monkeypatch.setattr(up, "consume_last_result",
                        lambda *a, **k: {"version": "2.0.0", "result": "success"})
    import gui.utils as gu
    monkeypatch.setattr(gu, "get_user_data_dir", lambda: tmp_path / "appdata")

    m._bootstrap_update_subsystem(_FakeCtx())

    assert captured.get("pending_install") is False
    assert captured.get("pending_version") == ""
    assert captured.get("last_install", {}).get("result") == "success"


def test_bootstrap_dev_skips_sidecar(monkeypatch, tmp_path):
    monkeypatch.setattr(m, "detect_install_form", lambda: "dev")
    called = []
    import maling_updater as up
    monkeypatch.setattr(up, "ensure_self_installed",
                        lambda *a, **k: called.append(a))
    monkeypatch.setattr(m, "save_update_state", lambda patch: called.append(patch))
    ctx = _FakeCtx()
    m._bootstrap_update_subsystem(ctx)
    assert ctx.update_install_form == "dev"
    assert called == []  # dev 形态不复制 sidecar、不写状态


# ---------------------------------------------------------------------------
# 拉起：creationflags 取值（不真启进程）
# ---------------------------------------------------------------------------
def test_launch_updater_process_flags(monkeypatch, tmp_path):
    captured = {}

    class _FakePopen:
        def __init__(self, args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

    import subprocess as _sp
    monkeypatch.setattr(_sp, "Popen", _FakePopen)
    updater = tmp_path / "updater" / "maling_updater.exe"
    updater.parent.mkdir(parents=True)

    m._launch_updater_process(updater, tmp_path / "plan.json", tmp_path / "u.log")

    assert captured["args"][0] == str(updater)
    assert "--pid" in captured["args"] and "--plan" in captured["args"] and "--log" in captured["args"]
    kwargs = captured["kwargs"]
    assert kwargs["close_fds"] is True
    assert kwargs["stdin"] == _sp.DEVNULL
    assert kwargs["stdout"] == _sp.DEVNULL
    assert kwargs["stderr"] == _sp.DEVNULL
    assert kwargs["cwd"] == str(updater.parent)
    # team-lead 更正：DETACHED_PROCESS | CREATE_NO_WINDOW 同时存在（保证子进程生命周期独立）
    expected = (_sp.DETACHED_PROCESS | _sp.CREATE_NO_WINDOW) if os.name == "nt" else 0
    assert kwargs["creationflags"] == expected
    if os.name == "nt":
        assert kwargs["creationflags"] & _sp.DETACHED_PROCESS
        assert kwargs["creationflags"] & _sp.CREATE_NO_WINDOW


# ---------------------------------------------------------------------------
# 编排：_maybe_launch_updater
# ---------------------------------------------------------------------------
def test_maybe_launch_dev_skips(monkeypatch):
    monkeypatch.setattr(m, "detect_install_form", lambda: "dev")
    called = []
    monkeypatch.setattr(m, "_launch_updater_process",
                        lambda *a, **k: called.append(a))
    m._maybe_launch_updater(_FakeCtx())
    assert called == []


def test_maybe_launch_guard_fails_no_verified(monkeypatch, tmp_path):
    monkeypatch.setattr(m, "detect_install_form", lambda: "onedir")
    monkeypatch.setattr(m, "load_update_state",
                        lambda: {"pending_install": True, "pending_version": "2.0.0",
                                 "download": {"path": str(tmp_path / "none.zip"),
                                              "sha256": _SHA}})
    monkeypatch.setattr(m, "_compute_install_targets", lambda *a, **k: {
        "app_exe": str(tmp_path / "maling.exe"),
        "install_dir": str(tmp_path), "install_parent": str(tmp_path.parent)})
    called = []
    monkeypatch.setattr(m, "_launch_updater_process",
                        lambda *a, **k: called.append(a))
    m._maybe_launch_updater(_FakeCtx())
    assert called == []  # 包不存在 → 校验不过 → 不拉起


def _patch_happy(monkeypatch, tmp_path):
    """装配 happy-path 的 monkeypatch，返回捕获列表。"""
    install_dir = tmp_path / "apps" / "maling"
    install_dir.mkdir(parents=True)
    pkg = tmp_path / "pkg.zip"
    pkg.write_bytes(b"pkg")
    updater_dir = tmp_path / "appdata" / "updater"
    updater_dir.mkdir(parents=True)
    (updater_dir / "maling_updater.exe").write_bytes(b"exe")

    monkeypatch.setattr(m, "detect_install_form", lambda: "onedir")
    monkeypatch.setattr(m, "load_update_state", lambda: {
        "pending_install": True, "pending_version": "2.0.0",
        "download": {"path": str(pkg), "sha256": _SHA},
    })
    monkeypatch.setattr(m, "_compute_install_targets", lambda *a, **k: {
        "app_exe": str(install_dir / "maling.exe"),
        "install_dir": str(install_dir),
        "install_parent": str(install_dir.parent),
    })
    import gui.update_downloader as dl
    monkeypatch.setattr(dl, "verify_sha256", lambda *a, **k: True)
    monkeypatch.setattr(dl, "is_install_writable", lambda *a, **k: True)
    import gui.utils as gu
    monkeypatch.setattr(gu, "get_user_data_dir", lambda: tmp_path / "appdata")

    captured = []
    monkeypatch.setattr(m, "_launch_updater_process",
                        lambda *a, **k: captured.append(a))
    return captured, install_dir


class _FakeCtx:
    update_install_form = None
    quitting = False


def test_maybe_launch_happy_writes_plan(monkeypatch, tmp_path):
    captured, install_dir = _patch_happy(monkeypatch, tmp_path)
    m._maybe_launch_updater(_FakeCtx())
    assert len(captured) == 1
    updater_exe, plan_path, log_path = captured[0]
    assert str(updater_exe).endswith("maling_updater.exe")
    plan = json.loads(open(str(plan_path), encoding="utf-8").read())
    assert plan["schema"] == 1
    assert plan["action"] == "swap_onedir"
    assert plan["target_version"] == "2.0.0"
    assert plan["install_parent"] == str(install_dir.parent)
    # 同卷：staging/backup 落 install_parent
    assert os.path.dirname(plan["staging_dir"]) == str(install_dir.parent)
    assert os.path.dirname(plan["backup_dir"]) == str(install_dir.parent)
    assert plan["package_sha256"] == _SHA
    assert plan["app_pid"] == os.getpid()
    # 供 sidecar load_plan 复核
    from maling_updater import load_plan
    assert load_plan(str(plan_path)).target_version == "2.0.0"


def test_maybe_launch_onefile_action(monkeypatch, tmp_path):
    install_dir = tmp_path / "apps"
    install_dir.mkdir(parents=True)
    pkg = tmp_path / "pkg.exe"
    pkg.write_bytes(b"pkg")
    updater_dir = tmp_path / "appdata" / "updater"
    updater_dir.mkdir(parents=True)
    (updater_dir / "maling_updater.exe").write_bytes(b"exe")
    monkeypatch.setattr(m, "detect_install_form", lambda: "onefile")
    monkeypatch.setattr(m, "load_update_state", lambda: {
        "pending_install": True, "pending_version": "2.0.0",
        "download": {"path": str(pkg), "sha256": _SHA},
    })
    monkeypatch.setattr(m, "_compute_install_targets", lambda *a, **k: {
        "app_exe": str(install_dir / "MaLing_single.exe"),
        "install_dir": str(install_dir),
        "install_parent": str(install_dir.parent),
    })
    import gui.update_downloader as dl
    monkeypatch.setattr(dl, "verify_sha256", lambda *a, **k: True)
    monkeypatch.setattr(dl, "is_install_writable", lambda *a, **k: True)
    import gui.utils as gu
    monkeypatch.setattr(gu, "get_user_data_dir", lambda: tmp_path / "appdata")
    captured = []
    monkeypatch.setattr(m, "_launch_updater_process",
                        lambda *a, **k: captured.append(a))
    m._maybe_launch_updater(_FakeCtx())
    assert len(captured) == 1
    plan = json.loads(open(str(captured[0][1]), encoding="utf-8").read())
    assert plan["action"] == "swap_onefile"
    assert plan["staging_dir"] is None
    assert plan["backup_dir"] is None
