# -*- coding: utf-8 -*-
"""tests/test_v20_updater.py —— sidecar 换包层测试（design-v20 §5 V20-15 / §8.3）。

覆盖：argv 退出码 / plan 解析 / 自我保护 / onedir rename-swap（成功·失败·回滚·
无半成品目录）/ 同卷拒绝 / onefile 换法 + 写入重试 + .old 清理 / 三重判定回滚矩阵 /
pending_confirm·confirmed·last_result 协议 / consume_last_result 读后删 /
ensure_self_installed 幂等 / purge_old_files / 缺陷 D-1·D-1b（onefile 握手 pid 按
「自身或后代」判定 + 回滚前整树终止）。

D-10 说明（规模边界）：本文件所有用例使用**缩减目录树**（每例 <50 文件）以适配沙箱
与快速回归；**真实万级文件树**的整树 rename-swap 已由 QA 真机验证（V20-16 harness，
D:/qa_v20_16/，13/13 场景 PASS），两者互补：本文件保证逻辑分支与退出码，真机保证规模与
文件系统语义（长路径、句柄锁、ACL）。

约束（共享知识 8）：不真跑 exe、不联网、临时目录树模拟全路径；
每批删除 <50 文件（本文件的测试树都很小）；进程枚举/拉起/判定全部注入替换。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import maling_updater as mu  # noqa: E402


# ---------------------------------------------------------------------------
# 测试脚手架
# ---------------------------------------------------------------------------
def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(root: Path) -> dict:
    """目录快照（相对路径 → 内容），用于逐文件比对回滚。"""
    out = {}
    if not root.exists():
        return out
    for p in root.rglob("*"):
        if p.is_file():
            out[p.relative_to(root).as_posix()] = p.read_bytes()
    return out


def make_zip(zip_path: Path, *, top: str = "maling/", exe: bytes = b"NEW-EXE",
             internal: bool = True, version: str = None) -> Path:
    """构造一个小 zip；默认顶层为 `maling/`（Q-U2 命名规范）。

    version 非 None 时写入 `maling/_internal/version.json`（V20-10 版本哨兵测试用）。
    """
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(f"{top}{mu.APP_EXE_NAME}", exe)
        if internal:
            zf.writestr(f"{top}{mu.INTERNAL_DIR_NAME}/data.txt", b"new-internal")
        if version is not None:
            zf.writestr(f"{top}{mu.INTERNAL_DIR_NAME}/version.json",
                        json.dumps({"version": version}))
    return zip_path


def build_onedir(tmp_path: Path, *, bad_sha: bool = False, exe_name: str = None,
                 staged_version: str = None):
    """构造 onedir 环境：install_parent/maling/（旧）+ 新包 zip + plan.json。

    返回 (plan_dict, plan_path, paths dict)。
    """
    parent = tmp_path / "apps"
    install = parent / "maling"
    (install / "_internal").mkdir(parents=True)
    (install / mu.APP_EXE_NAME).write_bytes(b"OLD-EXE")
    (install / "_internal" / "old.txt").write_bytes(b"old-internal")
    (install / "extra.bin").write_bytes(b"old-extra")

    zip_path = tmp_path / "MaLing_v2.0.0_win_onedir.zip"
    make_zip(zip_path, version=staged_version)
    sha = "0" * 64 if bad_sha else _sha(zip_path)

    confirm = tmp_path / "updater"
    confirm.mkdir()
    plan = {
        "schema": 1,
        "action": mu.ACTION_SWAP_ONEDIR,
        "target_version": "2.0.0",
        "from_version": "1.9.0",
        "app_pid": 999999,
        "app_exe": str(install / mu.APP_EXE_NAME),
        "install_dir": str(install),
        "install_parent": str(parent),
        "package_path": str(zip_path),
        "package_sha256": sha,
        "staging_dir": str(parent / ".maling_new_2.0.0"),
        "backup_dir": str(parent / ".maling_backup_1.9.0"),
        "confirm_dir": str(confirm),
        "confirm_timeout_sec": 2,
        "kill_timeout_sec": 1,
        "log_path": str(confirm / "updater.log"),
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    return plan, plan_path, {
        "parent": parent, "install": install, "zip": zip_path,
        "confirm": confirm, "staging": parent / ".maling_new_2.0.0",
        "backup": parent / ".maling_backup_1.9.0",
    }


def build_onefile(tmp_path: Path):
    """构造 onefile 环境：当前 exe + 新 exe 包 + plan.json。"""
    exe = tmp_path / "MaLing_single.exe"
    exe.write_bytes(b"OLD-SINGLE")
    pkg = tmp_path / "MaLing_v2.0.0_win_single.exe"
    pkg.write_bytes(b"NEW-SINGLE-CONTENT")
    confirm = tmp_path / "updater"
    confirm.mkdir()
    plan = {
        "schema": 1,
        "action": mu.ACTION_SWAP_ONEFILE,
        "target_version": "2.0.0",
        "from_version": "1.9.0",
        "app_pid": 999999,
        "app_exe": str(exe),
        "install_dir": str(tmp_path),
        "install_parent": str(tmp_path),
        "package_path": str(pkg),
        "package_sha256": _sha(pkg),
        "confirm_dir": str(confirm),
        "confirm_timeout_sec": 2,
        "kill_timeout_sec": 1,
        "log_path": str(confirm / "updater.log"),
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    return plan, plan_path, {"exe": exe, "pkg": pkg, "confirm": confirm,
                             "old": tmp_path / (exe.name + ".old")}


@pytest.fixture
def no_blockers(monkeypatch):
    """注入无残留进程 + 主进程已退出 + 拉起返回假 pid。"""
    monkeypatch.setattr(mu, "wait_for_pid_exit", lambda pid, t: True)
    monkeypatch.setattr(mu, "enumerate_processes_under", lambda prefix: [])
    monkeypatch.setattr(mu, "launch_detached", lambda exe, cwd=None: 4242)


def run_main(plan_path: Path, confirm: Path, pid: int = 999999) -> int:
    return mu.main(["--pid", str(pid), "--plan", str(plan_path),
                    "--log", str(confirm / "updater.log")])


# ===========================================================================
# argv 契约（退出码 2）
# ===========================================================================
def test_no_args_exit_2():
    assert mu.main([]) == mu.EXIT_BAD_ARGS


def test_unknown_arg_exit_2():
    assert mu.main(["--bogus-flag"]) == mu.EXIT_BAD_ARGS


def test_missing_pid_or_plan_exit_2(tmp_path):
    assert mu.main(["--plan", "x.json"]) == mu.EXIT_BAD_ARGS
    assert mu.main(["--pid", "1"]) == mu.EXIT_BAD_ARGS


def test_version_flag_exit_0(capsys):
    assert mu.main(["--version"]) == mu.EXIT_OK
    out = capsys.readouterr().out.strip()
    assert out == mu.UPDATER_VERSION


# ===========================================================================
# plan 解析（退出码 4 / 5）
# ===========================================================================
def test_unknown_schema_exit_4(tmp_path):
    plan, plan_path, paths = build_onedir(tmp_path)
    plan["schema"] = 99
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    assert run_main(plan_path, paths["confirm"]) == mu.EXIT_BAD_SCHEMA
    # 未换包：旧 exe 原样
    assert (paths["install"] / mu.APP_EXE_NAME).read_bytes() == b"OLD-EXE"


def test_missing_field_exit_5_and_log_written(tmp_path):
    plan, plan_path, paths = build_onedir(tmp_path)
    plan.pop("staging_dir")
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    rc = run_main(plan_path, paths["confirm"])
    assert rc == mu.EXIT_BAD_PLAN
    log = (paths["confirm"] / "updater.log").read_text(encoding="utf-8")
    assert "缺关键字段" in log


def test_unknown_action_exit_5(tmp_path):
    plan, plan_path, paths = build_onedir(tmp_path)
    plan["action"] = "swap_whatever"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    assert run_main(plan_path, paths["confirm"]) == mu.EXIT_BAD_PLAN


def test_bad_sha_format_exit_5(tmp_path):
    plan, plan_path, paths = build_onedir(tmp_path)
    plan["package_sha256"] = "not-a-sha"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    assert run_main(plan_path, paths["confirm"]) == mu.EXIT_BAD_PLAN


def test_target_not_newer_exit_6(tmp_path):
    plan, plan_path, paths = build_onedir(tmp_path)
    plan["target_version"] = "1.9.0"  # 不高于 from
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    assert run_main(plan_path, paths["confirm"]) == mu.EXIT_PRECONDITION


# ===========================================================================
# 自我保护（退出码 3）
# ===========================================================================
def test_self_check_ok_pure(tmp_path):
    assert mu.self_check_ok(tmp_path / "updater" / "maling_updater.exe",
                            tmp_path / "apps" / "maling") is True
    assert mu.self_check_ok(tmp_path / "apps" / "maling" / "maling_updater.exe",
                            tmp_path / "apps" / "maling") is False


def test_self_inside_install_exit_3(tmp_path):
    # install_dir = 解释器所在目录 → sidecar 自身落在其中 → 拒绝换包
    target = Path(sys.executable).parent
    confirm = tmp_path / "updater"
    confirm.mkdir()
    plan = {
        "schema": 1, "action": mu.ACTION_SWAP_ONEDIR,
        "target_version": "2.0.0", "from_version": "1.9.0", "app_pid": 1,
        "app_exe": str(target / mu.APP_EXE_NAME), "install_dir": str(target),
        "install_parent": str(target.parent), "package_path": str(tmp_path / "p.zip"),
        "package_sha256": "a" * 64,
        "staging_dir": str(target.parent / ".maling_new_2.0.0"),
        "backup_dir": str(target.parent / ".maling_backup_1.9.0"),
        "confirm_dir": str(confirm), "confirm_timeout_sec": 1, "kill_timeout_sec": 1,
        "log_path": str(confirm / "u.log"),
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    assert run_main(plan_path, confirm, pid=1) == mu.EXIT_SELF_INSIDE


# ===========================================================================
# 工具纯函数
# ===========================================================================
@pytest.mark.parametrize("candidate,base,expected", [
    ("1.10.0", "1.9.0", True),
    ("1.9.0", "1.9.0", False),
    ("2.0.0", "1.9.9", True),
])
def test_is_newer_numeric(candidate, base, expected):
    assert mu.is_newer(candidate, base) is expected
    assert mu.parse_version("1.10.0") == (1, 10, 0)


@pytest.mark.parametrize("value,ok", [
    ("a" * 64, True),
    ("A" * 64, True),
    ("a" * 63, False),
    ("z" * 64, False),
    ("", False),
    (None, False),
])
def test_is_valid_sha256(value, ok):
    assert mu.is_valid_sha256(value) is ok


def test_verify_sha256_detects_tamper(tmp_path):
    f = tmp_path / "f.bin"
    f.write_bytes(b"hello")
    good = hashlib.sha256(b"hello").hexdigest()
    assert mu.verify_sha256(f, good) is True
    f.write_bytes(b"hellp")  # 篡改 1 字节
    assert mu.verify_sha256(f, good) is False


def test_check_same_volume_same_and_cross(tmp_path):
    ok, _ = mu.check_same_volume([tmp_path, tmp_path / "a", tmp_path / "b"])
    assert ok is True
    if os.name == "nt":
        ok2, why = mu.check_same_volume([tmp_path, "Z:/nonexistent-maling-xyz"])
        assert ok2 is False
        assert "盘符" in why


# ===========================================================================
# 残留进程排空
# ===========================================================================
def test_drain_no_leftover():
    assert mu.drain_install_dir_processes("X:/x", 1, enumerate_fn=lambda p: []) is True


def test_drain_waits_then_clears():
    state = {"n": 0}

    def enum(prefix):
        state["n"] += 1
        return [(1, "X:/x/node.exe")] if state["n"] < 3 else []

    killed = []
    ok = mu.drain_install_dir_processes(
        "X:/x", 10, enumerate_fn=enum, kill_fn=killed.append,
        sleep_fn=lambda d: None, now_fn=lambda: 0.0)
    assert ok is True
    assert killed == []  # 等待期间自行退出，无需强杀


def test_drain_timeout_kills():
    clock = [0.0]

    def now():
        return clock[0]

    def sleep(d):
        clock[0] += d

    killed = []
    ok = mu.drain_install_dir_processes(
        "X:/x", 1, enumerate_fn=lambda p: [(7, "X:/x/node.exe")],
        kill_fn=killed.append, sleep_fn=sleep, now_fn=now)
    # 强杀后仍在（stub 永远返回残留）→ 返回 False，但确实调用了强杀
    assert killed == [7]
    assert ok is False


# ===========================================================================
# 解压 / 顶层目录兼容探测
# ===========================================================================
def test_extract_descends_single_top_dir(tmp_path):
    zp = make_zip(tmp_path / "p.zip", top="maling/")
    dest = tmp_path / "stage"
    mu.extract_zip_package(zp, dest)
    assert (dest / mu.APP_EXE_NAME).is_file()
    assert (dest / mu.INTERNAL_DIR_NAME / "data.txt").is_file()
    assert not (dest / "maling").exists()


def test_extract_root_files_without_top_dir(tmp_path):
    zp = make_zip(tmp_path / "p.zip", top="")
    dest = tmp_path / "stage"
    mu.extract_zip_package(zp, dest)
    assert (dest / mu.APP_EXE_NAME).is_file()
    assert (dest / mu.INTERNAL_DIR_NAME / "data.txt").is_file()


def test_validate_staged_install(tmp_path):
    ok_root = tmp_path / "ok"
    (ok_root / mu.INTERNAL_DIR_NAME).mkdir(parents=True)
    (ok_root / mu.APP_EXE_NAME).write_bytes(b"x")
    ok, _ = mu.validate_staged_install(ok_root, mu.ACTION_SWAP_ONEDIR)
    assert ok is True
    bad = tmp_path / "bad"
    bad.mkdir()
    ok2, reason = mu.validate_staged_install(bad, mu.ACTION_SWAP_ONEDIR)
    assert ok2 is False and "maling.exe" in reason


# ===========================================================================
# onedir rename-swap
# ===========================================================================
def test_swap_onedir_success(tmp_path, monkeypatch, no_blockers):
    plan, plan_path, paths = build_onedir(tmp_path)
    monkeypatch.setattr(mu, "poll_confirm", lambda *a, **k: "success")

    rc = run_main(plan_path, paths["confirm"])
    assert rc == mu.EXIT_OK
    # 安装目录 = 全新内容
    assert (paths["install"] / mu.APP_EXE_NAME).read_bytes() == b"NEW-EXE"
    assert (paths["install"] / mu.INTERNAL_DIR_NAME / "data.txt").read_bytes() == b"new-internal"
    assert not (paths["install"] / "extra.bin").exists()
    # 备份保留（回滚源）+ staging 已消失（无半成品）
    assert (paths["backup"] / mu.APP_EXE_NAME).read_bytes() == b"OLD-EXE"
    assert not paths["staging"].exists()
    # last_result = success
    res = json.loads((paths["confirm"] / "last_result.json").read_text(encoding="utf-8"))
    assert res["result"] == "success"
    assert res["version"] == "2.0.0" and res["from_version"] == "1.9.0"
    # pending_confirm 写成（新版 pid）
    pending = json.loads((paths["confirm"] / mu.PENDING_CONFIRM_NAME).read_text(encoding="utf-8"))
    assert pending["pid"] == 4242 and pending["version"] == "2.0.0"


def test_swap_onedir_step4_rename_rejected_keeps_old(tmp_path, monkeypatch, no_blockers):
    """④ rename 被拒（目录被占用）→ 旧目录原位不动、无需回滚、无半成品。"""
    plan, plan_path, paths = build_onedir(tmp_path)
    before = snapshot(paths["install"])
    real_rename = mu._rename

    def fake_rename(src, dst):
        if Path(str(src)) == paths["install"]:
            raise OSError(32, "in use")
        return real_rename(src, dst)

    monkeypatch.setattr(mu, "_rename", fake_rename)
    monkeypatch.setattr(mu, "poll_confirm", lambda *a, **k: "success")

    rc = run_main(plan_path, paths["confirm"])
    assert rc == mu.EXIT_FAILED
    assert snapshot(paths["install"]) == before          # 逐文件回到旧态
    assert not paths["backup"].exists()
    assert not paths["staging"].exists()                 # 无半成品
    res = json.loads((paths["confirm"] / "last_result.json").read_text(encoding="utf-8"))
    assert res["result"] == "failed"


def test_swap_onedir_step5_rename_rejected_rolls_back(tmp_path, monkeypatch, no_blockers):
    """⑤ 就位失败 → rename 旧目录回来；无两个半成品目录。"""
    plan, plan_path, paths = build_onedir(tmp_path)
    before = snapshot(paths["install"])
    real_rename = mu._rename
    calls = []

    def fake_rename(src, dst):
        calls.append((Path(str(src)), Path(str(dst))))
        if len(calls) == 2:  # ⑤ staging → install
            raise OSError(5, "access denied")
        return real_rename(src, dst)

    monkeypatch.setattr(mu, "_rename", fake_rename)
    monkeypatch.setattr(mu, "poll_confirm", lambda *a, **k: "success")

    rc = run_main(plan_path, paths["confirm"])
    assert rc == mu.EXIT_FAILED
    assert snapshot(paths["install"]) == before
    assert not paths["backup"].exists()      # 已 rename 回位
    assert not paths["staging"].exists()
    res = json.loads((paths["confirm"] / "last_result.json").read_text(encoding="utf-8"))
    assert res["result"] == "failed"


def test_swap_onedir_poll_failed_rolls_back(tmp_path, monkeypatch, no_blockers):
    """拉起新版后三重判定失败 → 回滚旧版可启动 + last_result=rolled_back。"""
    plan, plan_path, paths = build_onedir(tmp_path)
    before = snapshot(paths["install"])
    launches = []
    monkeypatch.setattr(mu, "launch_detached",
                        lambda exe, cwd=None: launches.append(exe) or 4242)
    monkeypatch.setattr(mu, "poll_confirm", lambda *a, **k: "failed")
    monkeypatch.setattr(mu, "terminate_process_tree", lambda pid, **k: True)

    rc = run_main(plan_path, paths["confirm"])
    assert rc == mu.EXIT_FAILED
    assert (paths["install"] / mu.APP_EXE_NAME).read_bytes() == b"OLD-EXE"
    assert snapshot(paths["install"]) == before
    assert not paths["backup"].exists()                       # 备份已归位
    assert not paths["staging"].exists()                      # 无 staging 半成品
    assert len(launches) == 2                                 # 新版 + 回滚后旧版
    res = json.loads((paths["confirm"] / "last_result.json").read_text(encoding="utf-8"))
    assert res["result"] == "rolled_back"


def test_swap_onedir_sha_mismatch_exit_6_no_touch(tmp_path, monkeypatch, no_blockers):
    plan, plan_path, paths = build_onedir(tmp_path, bad_sha=True)
    before = snapshot(paths["install"])
    rc = run_main(plan_path, paths["confirm"])
    assert rc == mu.EXIT_PRECONDITION
    assert snapshot(paths["install"]) == before
    assert not paths["staging"].exists()


def test_swap_onedir_cross_volume_rejected(tmp_path, monkeypatch, no_blockers):
    plan, plan_path, paths = build_onedir(tmp_path)
    before = snapshot(paths["install"])
    monkeypatch.setattr(mu, "check_same_volume", lambda ps: (False, "跨卷"))
    rc = run_main(plan_path, paths["confirm"])
    assert rc == mu.EXIT_PRECONDITION
    assert snapshot(paths["install"]) == before


# ---- V20-10 加固：就位阶段版本哨兵（R-M 绝不装错包）----
def test_check_staged_version_pure(tmp_path):
    """纯函数：缺失→回退(None)、一致→True、不符→False。"""
    root = tmp_path / "stage"
    (root / mu.INTERNAL_DIR_NAME).mkdir(parents=True)
    (root / mu.APP_EXE_NAME).write_bytes(b"x")
    assert mu.check_staged_version(root, "2.0.0")[0] is None     # 版本文件缺失 → 回退
    vjson = root / mu.INTERNAL_DIR_NAME / "version.json"
    vjson.write_text(json.dumps({"version": "2.0.0"}), encoding="utf-8")
    assert mu.check_staged_version(root, "2.0.0")[0] is True
    assert mu.check_staged_version(root, "3.0.0")[0] is False    # 存在但不符


def test_staged_version_matches_target_passes(tmp_path, monkeypatch, no_blockers):
    """staging 的 version.json == target → 通过并完成换包。"""
    plan, plan_path, paths = build_onedir(tmp_path, staged_version="2.0.0")
    monkeypatch.setattr(mu, "poll_confirm", lambda *a, **k: "success")
    assert run_main(plan_path, paths["confirm"]) == mu.EXIT_OK
    assert (paths["install"] / mu.APP_EXE_NAME).read_bytes() == b"NEW-EXE"
    assert (paths["install"] / mu.INTERNAL_DIR_NAME / "version.json").is_file()


def test_staged_version_mismatch_exit_6_no_touch(tmp_path, monkeypatch, no_blockers):
    """staging 版本不符（1.8.0 != 2.0.0）→ 退出 6 且安装目录零变化、无半成品。"""
    plan, plan_path, paths = build_onedir(tmp_path, staged_version="1.8.0")
    before = snapshot(paths["install"])
    monkeypatch.setattr(mu, "poll_confirm", lambda *a, **k: "success")
    rc = run_main(plan_path, paths["confirm"])
    assert rc == mu.EXIT_PRECONDITION
    assert snapshot(paths["install"]) == before           # 安装目录零变化
    assert not paths["staging"].exists()                  # staging 已清，无半成品
    res = json.loads((paths["confirm"] / mu.LAST_RESULT_NAME).read_text(encoding="utf-8"))
    assert res["result"] == "failed"


# ===========================================================================
# onefile 换法
# ===========================================================================
def test_swap_onefile_success_and_purge(tmp_path, monkeypatch, no_blockers):
    plan, plan_path, paths = build_onefile(tmp_path)
    monkeypatch.setattr(mu, "poll_confirm", lambda *a, **k: "success")

    rc = run_main(plan_path, paths["confirm"])
    assert rc == mu.EXIT_OK
    assert paths["exe"].exists()
    assert paths["exe"].read_bytes() == b"NEW-SINGLE-CONTENT"   # 路径不变、内容为新
    assert paths["old"].read_bytes() == b"OLD-SINGLE"           # 旧 exe 改名保留
    assert mu.purge_old_files(paths["exe"]) is True             # 下次启动清理
    assert not paths["old"].exists()
    res = json.loads((paths["confirm"] / "last_result.json").read_text(encoding="utf-8"))
    assert res["result"] == "success"


def test_swap_onefile_write_rejected_rolls_back(tmp_path, monkeypatch, no_blockers):
    plan, plan_path, paths = build_onefile(tmp_path)

    def boom(src, dst, logger, **k):
        raise OSError(32, "file in use")

    monkeypatch.setattr(mu, "_copy_with_retry", boom)
    rc = run_main(plan_path, paths["confirm"])
    assert rc == mu.EXIT_FAILED
    assert paths["exe"].read_bytes() == b"OLD-SINGLE"           # 旧 exe 已归位
    assert not paths["old"].exists()
    res = json.loads((paths["confirm"] / "last_result.json").read_text(encoding="utf-8"))
    assert res["result"] in ("failed", "rolled_back")


def test_swap_onefile_poll_failed_rolls_back(tmp_path, monkeypatch, no_blockers):
    plan, plan_path, paths = build_onefile(tmp_path)
    monkeypatch.setattr(mu, "poll_confirm", lambda *a, **k: "failed")
    monkeypatch.setattr(mu, "terminate_process_tree", lambda pid, **k: True)

    rc = run_main(plan_path, paths["confirm"])
    assert rc == mu.EXIT_FAILED
    assert paths["exe"].read_bytes() == b"OLD-SINGLE"
    assert not paths["old"].exists()
    res = json.loads((paths["confirm"] / "last_result.json").read_text(encoding="utf-8"))
    assert res["result"] == "rolled_back"


def test_swap_onefile_rollback_uses_tree_termination(tmp_path, monkeypatch, no_blockers):
    """D-1b：onefile 回滚必须整树终止（bootloader + 应用本体），否则 exe 句柄不释放。"""
    plan, plan_path, paths = build_onefile(tmp_path)
    monkeypatch.setattr(mu, "poll_confirm", lambda *a, **k: "failed")
    calls = []
    monkeypatch.setattr(mu, "terminate_process_tree",
                        lambda pid, **k: calls.append(pid) or True)

    rc = run_main(plan_path, paths["confirm"])
    assert rc == mu.EXIT_FAILED
    assert calls == [4242]                       # 传的是 launch_detached 返回的 bootloader pid
    assert paths["exe"].read_bytes() == b"OLD-SINGLE"
    assert not paths["old"].exists()
    res = json.loads((paths["confirm"] / "last_result.json").read_text(encoding="utf-8"))
    assert res["result"] == "rolled_back"


def test_swap_onedir_rollback_uses_tree_termination(tmp_path, monkeypatch, no_blockers):
    """D-1b：onedir 回滚同样整树终止（应用本体 + _internal 下的 node.exe 等）。"""
    plan, plan_path, paths = build_onedir(tmp_path)
    monkeypatch.setattr(mu, "poll_confirm", lambda *a, **k: "failed")
    calls = []
    monkeypatch.setattr(mu, "terminate_process_tree",
                        lambda pid, **k: calls.append(pid) or True)

    rc = run_main(plan_path, paths["confirm"])
    assert rc == mu.EXIT_FAILED
    assert calls == [4242]
    assert snapshot(paths["install"])["maling.exe"] == b"OLD-EXE"   # 旧目录已归位
    res = json.loads((paths["confirm"] / "last_result.json").read_text(encoding="utf-8"))
    assert res["result"] == "rolled_back"


# ===========================================================================
# 三重判定回滚矩阵（poll_confirm）
# ===========================================================================
def test_poll_confirm_success(tmp_path):
    confirm = tmp_path / "c"
    confirm.mkdir()
    mu.write_confirmed(confirm, "2.0.0", 4242)
    assert mu.poll_confirm(confirm, "2.0.0", 4242, 5,
                           alive_fn=lambda p: False) == "success"


def test_poll_confirm_fast_fail_when_new_process_exits(tmp_path):
    confirm = tmp_path / "c"
    confirm.mkdir()
    clock = [0.0]
    verdict = mu.poll_confirm(
        confirm, "2.0.0", 4242, 45,
        alive_fn=lambda p: False,
        now_fn=lambda: clock[0], sleep_fn=lambda d: clock.__setitem__(0, clock[0] + d))
    assert verdict == "failed"


def test_poll_confirm_timeout(tmp_path):
    confirm = tmp_path / "c"
    confirm.mkdir()
    clock = [0.0]

    def sleep(d):
        clock[0] += d

    verdict = mu.poll_confirm(
        confirm, "2.0.0", 4242, 1,
        alive_fn=lambda p: True, now_fn=lambda: clock[0], sleep_fn=sleep)
    assert verdict == "timeout"


def test_is_confirmed_requires_version_and_pid(tmp_path):
    confirm = tmp_path / "c"
    confirm.mkdir()
    mu.write_confirmed(confirm, "2.0.0", 4242)
    assert mu.is_confirmed(confirm, "2.0.0", 4242) is True
    assert mu.is_confirmed(confirm, "2.0.0", 1) is False        # pid 不符
    assert mu.is_confirmed(confirm, "2.0.1", 4242) is False     # 版本不符
    assert mu.is_confirmed(tmp_path / "empty", "2.0.0", 4242) is False


# ===========================================================================
# 缺陷 D-1：onefile 握手 pid（bootloader ≠ 应用本体）——后代判定 + 整树终止
# ===========================================================================
def test_is_descendant_pure_chain():
    """父链上溯：5003 → 5002 → 5001 → 4242(bootloader) → 100。"""
    chain = {5003: 5002, 5002: 5001, 5001: 4242, 4242: 100, 100: 0}

    def pf(p):
        return chain.get(int(p), 0)

    assert mu.is_descendant(5003, 4242, parent_of=pf) is True    # 两代之后仍是后代
    assert mu.is_descendant(5001, 4242, parent_of=pf) is True    # 直接子进程
    assert mu.is_descendant(4242, 4242, parent_of=pf) is False   # 自身不算后代
    assert mu.is_descendant(100, 4242, parent_of=pf) is False    # 祖先不是后代
    assert mu.is_descendant(9999, 4242, parent_of=pf) is False   # 不在链上


def test_is_descendant_depth_limit():
    pf = lambda p: p - 1 if p > 1 else 0                          # 1..20 单链
    assert mu.is_descendant(20, 15, parent_of=pf) is True        # 5 层内命中
    assert mu.is_descendant(20, 13, parent_of=pf, max_depth=8) is True
    assert mu.is_descendant(20, 5, parent_of=pf) is False        # 超出 max_depth=6


def test_is_descendant_cycle_guard_and_bad_input():
    pf = lambda p: {7: 8, 8: 7}.get(int(p), 0)                   # 环
    assert mu.is_descendant(7, 99, parent_of=pf) is False        # 不死循环
    assert mu.is_descendant("x", 1) is False                     # 非法输入
    assert mu.is_descendant(5, 0) is False
    assert mu.is_descendant(5, 3, parent_of=lambda p: 0) is False
    assert mu.is_descendant(5, 1, parent_of=lambda p: 1 / 0) is False   # 查询异常 → False


def test_is_confirmed_accepts_descendant_pid(tmp_path):
    """onefile：confirmed.json 带应用本体 pid，拉起返回的是 bootloader pid。"""
    confirm = tmp_path / "c"
    confirm.mkdir()
    mu.write_confirmed(confirm, "2.0.0", 5003)                  # 本体的 pid
    launch_pid = 4242                                          # bootloader 的 pid
    assert mu.is_confirmed(confirm, "2.0.0", launch_pid) is False   # 默认真机查不到 → 不认账
    assert mu.is_confirmed(
        confirm, "2.0.0", launch_pid,
        is_desc_fn=lambda c, a: int(c) == 5003 and int(a) == launch_pid) is True
    assert mu.is_confirmed(confirm, "2.0.1", launch_pid,
                           is_desc_fn=lambda c, a: True) is False   # 版本不符 → 仍拒
    assert mu.is_confirmed(confirm, "2.0.0", launch_pid,
                           is_desc_fn=lambda c, a: False) is False  # 非后代 → 拒


def test_is_confirmed_descendant_query_error_is_false(tmp_path):
    confirm = tmp_path / "c"
    confirm.mkdir()
    mu.write_confirmed(confirm, "2.0.0", 5003)

    def boom(_c, _a):
        raise RuntimeError("toolhelp fail")

    assert mu.is_confirmed(confirm, "2.0.0", 4242, is_desc_fn=boom) is False


def test_poll_confirm_success_via_descendant_pid(tmp_path):
    """D-1 端到端（纯逻辑）：bootloader pid ≠ confirmed pid，但是后代 → success。"""
    confirm = tmp_path / "c"
    confirm.mkdir()
    mu.write_confirmed(confirm, "2.0.0", 5003)
    verdict = mu.poll_confirm(
        confirm, "2.0.0", 4242, 5,
        alive_fn=lambda p: True,
        is_desc_fn=lambda c, a: int(c) == 5003 and int(a) == 4242,
        now_fn=lambda: 0.0, sleep_fn=lambda d: None)
    assert verdict == "success"


def test_terminate_process_tree_kills_leaves_first():
    tree = {100: [200, 300], 200: [400], 300: [], 400: []}
    order = []
    dead = set()

    def kill(p):
        order.append(p)
        dead.add(p)
        return True

    ok = mu.terminate_process_tree(
        100, children_fn=lambda p: tree.get(p, []), kill_fn=kill,
        alive_fn=lambda p: p not in dead, wait_sec=1)
    assert ok is True
    assert set(order) == {100, 200, 300, 400}                   # 整树都杀了
    assert order[-1] == 100                                     # root 最后
    assert order.index(400) < order.index(200)                  # 孙子先于其父


def test_terminate_process_tree_cycle_guard():
    killed = []
    ok = mu.terminate_process_tree(
        1, children_fn=lambda p: {1: [2], 2: [1]}.get(p, []),
        kill_fn=lambda p: killed.append(p) or True,
        alive_fn=lambda p: False, wait_sec=1)
    assert ok is True
    assert sorted(killed) == [1, 2]                             # 不去重就死循环


def test_terminate_process_tree_polls_until_handle_released():
    """进程退出（句柄释放）是异步的 → 必须轮询等待，而不是杀完就 rename。"""
    dead = set()
    clock = [0.0]

    def kill(p):
        dead.add(p)
        return True

    # 第 2 次轮询才真正退出 → 应该等待并返回 True
    polls = [0]

    def alive(p):
        polls[0] += 1
        return polls[0] < 2

    ok = mu.terminate_process_tree(
        7, children_fn=lambda p: [], kill_fn=kill, alive_fn=alive,
        now_fn=lambda: clock[0], sleep_fn=lambda d: clock.__setitem__(0, clock[0] + d),
        wait_sec=5, poll_interval=0.1)
    assert ok is True
    assert dead == {7}
    assert 0 < clock[0] < 5                                     # 轮询过、未耗尽超时


def test_terminate_process_tree_timeout_reports_false():
    clock = [0.0]
    ok = mu.terminate_process_tree(
        7, children_fn=lambda p: [], kill_fn=lambda p: True,
        alive_fn=lambda p: True,                                # 杀不掉
        now_fn=lambda: clock[0], sleep_fn=lambda d: clock.__setitem__(0, clock[0] + d),
        wait_sec=1, poll_interval=0.25)
    assert ok is False
    assert clock[0] >= 1                                        # 等满超时才放弃


def test_terminate_process_tree_bad_pid_is_noop():
    calls = []
    assert mu.terminate_process_tree(0, kill_fn=lambda p: calls.append(p)) is True
    assert mu.terminate_process_tree("x", kill_fn=lambda p: calls.append(p)) is True
    assert calls == []


def test_clear_stale_confirm(tmp_path):
    confirm = tmp_path / "c"
    confirm.mkdir()
    mu.write_confirmed(confirm, "2.0.0", 1)
    mu.clear_stale_confirm(confirm)
    assert not (confirm / mu.CONFIRMED_NAME).exists()


# ===========================================================================
# last_result 消费
# ===========================================================================
def test_consume_last_result_read_then_delete(tmp_path):
    confirm = tmp_path / "c"
    confirm.mkdir()
    payload = {"version": "2.0.0", "result": "success", "at": "x"}
    mu.write_last_result(confirm, payload)
    assert mu.consume_last_result(confirm) == payload
    assert not (confirm / mu.LAST_RESULT_NAME).exists()   # 读后删
    assert mu.consume_last_result(confirm) is None        # 二次调用 → None


def test_consume_last_result_missing_is_none(tmp_path):
    assert mu.consume_last_result(tmp_path / "none") is None


# ===========================================================================
# 自举 ensure_self_installed
# ===========================================================================
def test_ensure_self_installed_idempotent(tmp_path):
    src = tmp_path / "embedded" / "updater"
    src.mkdir(parents=True)
    (src / "maling_updater.exe").write_bytes(b"UPDATER-BIN")
    dest_dir = tmp_path / "appdata" / "updater"

    first = mu.ensure_self_installed(src, dest_dir)
    assert first.exists() and first.read_bytes() == b"UPDATER-BIN"
    mtime1 = first.stat().st_mtime_ns
    second = mu.ensure_self_installed(src, dest_dir)
    assert second == first
    assert second.stat().st_mtime_ns == mtime1      # 幂等：大小+sha 一致 → 不改 mtime


def test_ensure_self_installed_overwrites_on_change(tmp_path):
    src = tmp_path / "embedded" / "updater"
    src.mkdir(parents=True)
    exe = src / "maling_updater.exe"
    exe.write_bytes(b"OLD-BIN")
    dest_dir = tmp_path / "appdata" / "updater"
    mu.ensure_self_installed(src, dest_dir)

    exe.write_bytes(b"NEW-BIN-LONGER")               # 升级路径
    dest = mu.ensure_self_installed(src, dest_dir)
    assert dest.read_bytes() == b"NEW-BIN-LONGER"


def test_ensure_self_installed_refuses_updates_dir(tmp_path):
    src = tmp_path / "embedded" / "updater"
    src.mkdir(parents=True)
    (src / "maling_updater.exe").write_bytes(b"BIN")
    dest_dir = tmp_path / "maid_coder" / "updates" / "updater"
    dest = mu.ensure_self_installed(src, dest_dir)
    assert not dest.exists()                          # 拒绝落 updates/（会被清理缓存删掉）


def test_ensure_self_installed_missing_src_is_noop(tmp_path):
    dest = mu.ensure_self_installed(tmp_path / "nope", tmp_path / "appdata" / "updater")
    assert not dest.exists()


# ===========================================================================
# purge_old_files
# ===========================================================================
def test_purge_old_files(tmp_path):
    exe = tmp_path / "MaLing_single.exe"
    exe.write_bytes(b"x")
    assert mu.purge_old_files(exe) is True            # 不存在 → True
    old = tmp_path / "MaLing_single.exe.old"
    old.write_bytes(b"old")
    assert mu.purge_old_files(exe) is True
    assert not old.exists()


# ===========================================================================
# R-N 守卫：sidecar 不写 update_state.json、不碰用户数据
# ===========================================================================
def test_sidecar_never_writes_update_state(tmp_path, monkeypatch, no_blockers):
    plan, plan_path, paths = build_onedir(tmp_path)
    monkeypatch.setattr(mu, "poll_confirm", lambda *a, **k: "success")
    fake_user = tmp_path / "maid_coder"
    fake_user.mkdir()
    marker = fake_user / "update_state.json"
    marker.write_text('{"ignored_version": null}', encoding="utf-8")
    before = marker.read_bytes()

    run_main(plan_path, paths["confirm"])
    assert marker.read_bytes() == before               # sidecar 从不写 update_state.json
    assert snapshot(fake_user) == {"update_state.json": before}


# ===========================================================================
# 真机 ctypes 层（Toolhelp32 / WaitForSingleObject）——mock 覆盖不到的部分
# 只操作本进程自己 spawn 的子进程，不触碰任何真实安装目录。
# ===========================================================================
import subprocess as _sp  # noqa: E402
import time as _time  # noqa: E402

_nt_only = pytest.mark.skipif(os.name != "nt", reason="Windows 专有 API")


@_nt_only
def test_enumerate_finds_own_process():
    """Toolhelp32 结构尺寸正确 → 能枚举出本进程（证明 64 位 ULONG_PTR 对齐正确）。

    注：venv 的 sys.executable 与真实 image path 不同（Scripts/python.exe 是重定向器），
    故按盘符根枚举（只读，不杀任何进程）。
    """
    root = os.path.splitdrive(os.path.abspath(sys.executable))[0] + os.sep
    procs = mu.enumerate_processes_under(root)
    assert any(pid == os.getpid() for pid, _image in procs)


@_nt_only
def test_is_process_alive_self():
    assert mu.is_process_alive(os.getpid()) is True
    assert mu.is_process_alive(0xFFFFFFF0) is False   # 不存在的 pid


@_nt_only
def test_wait_for_pid_exit_real_child():
    child = _sp.Popen([sys.executable, "-c", "import time; time.sleep(0.2)"])
    try:
        assert mu.wait_for_pid_exit(child.pid, 10) is True
    finally:
        child.wait(timeout=10)
    assert mu.is_process_alive(child.pid) is False


@_nt_only
def test_wait_for_pid_exit_timeout_on_live_child():
    child = _sp.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert mu.is_process_alive(child.pid) is True
        assert mu.wait_for_pid_exit(child.pid, 0) is False   # 超时 → 仍存活
        assert mu.terminate_process(child.pid) is True
        assert mu.wait_for_pid_exit(child.pid, 10) is True
    finally:
        try:
            child.kill()
        except Exception:
            pass
        child.wait(timeout=10)


@_nt_only
def test_drain_kills_real_child(tmp_path):
    """排空逻辑用真实 terminate_process 杀掉真实子进程（证明强杀路径真的生效）。"""
    child = _sp.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        def enum(_prefix):
            return [(child.pid, str(tmp_path / "node.exe"))]

        clock = [0.0]
        mu.drain_install_dir_processes(
            tmp_path, 0.2, enumerate_fn=enum,
            sleep_fn=lambda d: clock.__setitem__(0, clock[0] + d),
            now_fn=lambda: clock[0])
        assert mu.wait_for_pid_exit(child.pid, 10) is True   # 已被强杀
    finally:
        try:
            child.kill()
        except Exception:
            pass
        child.wait(timeout=10)


@_nt_only
def test_terminate_process_tree_real_parent_and_grandchild():
    """真机：父进程再 spawn 一个孙子 → 整树终止必须把两代都杀掉（D-1b 取证）。

    模拟 onefile 形态：我们只持有"父"pid（对应 bootloader），应用本体是其子进程。
    """
    code = (
        "import subprocess, sys, time;"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']);"
        "time.sleep(30)"
    )
    parent = _sp.Popen([sys.executable, "-c", code])
    try:
        deadline = _time.time() + 20
        kids = []
        while _time.time() < deadline:
            kids = mu.enumerate_process_children(parent.pid)
            if kids:
                break
            _time.sleep(0.2)
        assert kids, "未探测到孙子进程（Toolhelp32 父子关系）"
        grandchild = int(kids[0])
        assert mu.is_process_alive(parent.pid) is True
        assert mu.is_process_alive(grandchild) is True

        assert mu.terminate_process_tree(parent.pid, wait_sec=10) is True
        assert mu.is_process_alive(parent.pid) is False
        assert mu.is_process_alive(grandchild) is False       # 孙子也被收掉
    finally:
        for p in (locals().get("grandchild"), parent.pid):
            try:
                mu.terminate_process(int(p))
            except Exception:
                pass
        try:
            parent.kill()
        except Exception:
            pass
        parent.wait(timeout=10)

