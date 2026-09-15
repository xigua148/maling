"""tests/test_v22_router.py —— V22-03 三级意图路由 · 纯函数断言（确定性 / 无墙钟 / 无 Qt / 无网络）。

覆盖 design-v22 §4.2 / §4.3 / §5.4#13 / §9.3 / §10.1 的 router 验收要点：
    * ① **verbatim**：词表命中 → ``mode="verbatim"`` 且**状态确实被改**；选项点击同样 verbatim；
      命中但 ``pre`` 不满足 → 降级 narrate 且状态不变；
    * ② **propose**：未命中 + ``allow_propose=True`` + LLM 合法提议 → ``mode="propose"`` 且状态被改；
      越白名单 / ``pre`` 不满足的提议 → narrate、状态不变、``reason`` 可归因；
    * ③ **narrate**：LLM 返回 ``None`` / 畸形 JSON / 抛异常 / 超时 → **四者全部** narrate 且状态不变，
      且**断言走同一条代码路径**（``reason`` 共用 ``llm_`` 前缀 + 共享兜底函数 ``_narrate`` 调用计数）；
    * ``allow_propose=False`` → **永不进 propose**（LLM 桩**一次都不被调用**，调用计数断言）；
    * **每个结果**都过 ``RESOLUTION_REQUIRED_KEYS`` 键集断言；
    * **确定性**：同 ``seed`` + 同 ``turn`` + 同一 LLM 桩 ⇒ 两次结果一致；
    * **零 Qt**：屏蔽 PySide6 后 ``import gui.tavern.intent_router`` 仍成功（子进程实证）；
    * **无网络**：AST 扫描确认模块不 import 任何网络库。

全部用例只 import ``gui.tavern.*``（零 Qt 链），不建 ``QApplication``，不依赖墙钟 / 全局随机态。
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from gui.tavern import engine as e
from gui.tavern import intent_router as ir
from gui.tavern import model as m

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# 夹具（纯数据；content 键全部可缺省）
# ---------------------------------------------------------------------------

def _content() -> dict:
    """「灯笼酒馆」最小内容包（覆盖词表/别名/名词解析所需的全部查询面）。"""
    return {
        "node_ids": ["opening", "counter_photo"],
        "scene_ids": ["bar", "counter", "room"],
        "reachable": {"bar": ["counter"], "counter": ["bar", "room"], "room": ["bar"]},
        "known_topics": {"counter": ["photo", "music"]},
        "menu": {"counter": ["long_night", "moon"]},
        "open_conditions": {"counter:drawer": True},
        "items": ["old_photo", "key"],
        "aliases": {
            "旧照片": "old_photo", "照片": "old_photo",
            "钥匙": "key",
            "吧台": "counter", "里屋": "room", "酒柜": "bar",
            "抽屉": "drawer",
            "长夜": "long_night", "月光": "moon",
            "照片话题": "photo",
        },
    }


def _state(**over) -> dict:
    """基准局状态：站在吧台前，桌上有 old_photo，身上有 key。"""
    # 固定时间戳（now=…）：保证 _state() 完全确定性，不依赖墙钟
    s = m.new_play("lantern", "灯笼还亮着", 12345, now="2026-09-15T00:00:00")
    s["scene_id"] = "counter"
    s["node_id"] = "counter_photo"
    s["turn"] = 0
    v = dict(m.default_vars())
    v["scene_items"] = ["old_photo"]
    v["held_items"] = ["key"]
    s["vars"] = v
    s["pending"] = [
        {"choice_id": "c_take", "text": "拿起照片", "transform": "take", "args": {"item": "old_photo"}},
        {"choice_id": "c_wait", "text": "让一拍过去", "transform": "wait", "args": {}},
    ]
    s.update(over)
    return s


def _fingerprint(obj) -> str:
    """逐字节指纹（用于「降级 = 状态逐字节不变」断言）。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def _assert_resolution_keyset(res: dict) -> None:
    """每个 resolution 必须恰好含 RESOLUTION_REQUIRED_KEYS（契约锚点）。"""
    assert set(res) == set(m.RESOLUTION_REQUIRED_KEYS), res
    assert res["mode"] in m.ROUTE_MODES
    assert isinstance(res["ok"], bool)
    assert isinstance(res["llm_used"], bool)
    assert e.is_known_reason(res["reason"]) or res["reason"].startswith("llm_"), res["reason"]


# ===========================================================================
# ① verbatim：词表命中 / 选项点击 / 命中但 pre 不满足
# ===========================================================================

def test_verbatim_take_by_builtin_wordlist_changes_state():
    st = _state()
    before = _fingerprint(st)
    res, new_state = ir.route("我拿起那张旧照片看看", st, _content(), allow_propose=False)

    _assert_resolution_keyset(res)
    assert res["mode"] == "verbatim"
    assert res["ok"] is True
    assert res["transform"] == "take"
    assert res["reason"] == "ok"
    assert res["llm_used"] is False
    # 状态确实被改：照片从桌上到了手里
    assert "old_photo" in new_state["vars"]["held_items"]
    assert "old_photo" not in new_state["vars"]["scene_items"]
    # 入参不被就地修改
    assert _fingerprint(st) == before


def test_verbatim_move_to_by_alias_changes_scene():
    st = _state()
    res, new_state = ir.route("我去里屋待一会儿", st, _content(), allow_propose=False)
    _assert_resolution_keyset(res)
    assert res["mode"] == "verbatim"
    assert res["transform"] == "move_to"
    assert new_state["scene_id"] == "room"


def test_verbatim_choice_click_is_verbatim_and_changes_state():
    st = _state()
    res, new_state = ir.route("c_take", st, _content(), input_kind="choice", allow_propose=False)
    _assert_resolution_keyset(res)
    assert res["mode"] == "verbatim"
    assert res["ok"] is True
    assert res["transform"] == "take"
    assert res["llm_used"] is False
    assert "old_photo" in new_state["vars"]["held_items"]


def test_verbatim_choice_wait_advances_turn():
    st = _state()
    res, new_state = ir.route("c_wait", st, _content(), input_kind="choice", allow_propose=False)
    assert res["mode"] == "verbatim"
    assert res["transform"] == "wait"
    assert new_state["turn"] == 1


def test_verbatim_unknown_choice_falls_to_narrate_state_unchanged():
    st = _state()
    before = _fingerprint(st)
    res, new_state = ir.route("c_nope", st, _content(), input_kind="choice", allow_propose=False)
    _assert_resolution_keyset(res)
    assert res["mode"] == "narrate"
    assert res["ok"] is False
    assert res["reason"] == ir.REASON_UNKNOWN_CHOICE
    assert new_state is st
    assert _fingerprint(st) == before


def test_verbatim_hit_but_pre_fails_degrades_to_narrate():
    # 词表命中 take，但桌上没有这个物品 → pre 不满足 → 降级 narrate
    st = _state()
    st["vars"] = dict(st["vars"])
    st["vars"]["scene_items"] = []  # 桌上空
    before = _fingerprint(st)
    res, new_state = ir.route("我拿起那张旧照片", st, _content(), allow_propose=False)
    _assert_resolution_keyset(res)
    assert res["mode"] == "narrate"
    assert res["ok"] is False
    assert res["transform"] == "take"  # 归因保留被尝试的变换
    assert res["reason"] == "precondition_failed:item_not_in_scene"
    assert new_state is st
    assert _fingerprint(st) == before


def test_resolve_verbatim_returns_none_for_gibberish():
    assert ir.resolve_verbatim("嗯…今天天气不错", _content()) is None
    assert ir.resolve_verbatim("", _content()) is None
    assert ir.resolve_verbatim(None, _content()) is None


# ===========================================================================
# ② propose：合法提议 / 越白名单 / pre 不满足
# ===========================================================================

def test_propose_valid_wait_is_applied():
    st = _state()
    before = _fingerprint(st)
    calls = {"n": 0}

    def stub(_prompt: str):
        calls["n"] += 1
        return {"transform": "wait", "args": {}}

    res, new_state = ir.route("随便发生点什么吧", st, _content(),
                              allow_propose=True, llm_propose=stub)
    _assert_resolution_keyset(res)
    assert calls["n"] == 1
    assert res["mode"] == "propose"
    assert res["ok"] is True
    assert res["transform"] == "wait"
    assert res["llm_used"] is True
    assert new_state["turn"] == 1
    assert _fingerprint(st) == before


def test_propose_json_string_is_accepted():
    st = _state()
    stub = lambda _p: '{"transform": "wait", "args": {}}'
    res, new_state = ir.route("随便发生点什么吧", st, _content(),
                              allow_propose=True, llm_propose=stub)
    assert res["mode"] == "propose"
    assert res["ok"] is True
    assert new_state["turn"] == 1


def test_propose_out_of_whitelist_transform_degrades_to_narrate():
    st = _state()
    before = _fingerprint(st)
    stub = lambda _p: {"transform": "fly_away", "args": {}}
    res, new_state = ir.route("随便发生点什么吧", st, _content(),
                              allow_propose=True, llm_propose=stub)
    _assert_resolution_keyset(res)
    assert res["mode"] == "narrate"
    assert res["ok"] is False
    assert res["transform"] == "fly_away"
    assert res["reason"] == "unknown_transform"  # 校验器裁决，可归因
    assert res["llm_used"] is True
    assert new_state is st
    assert _fingerprint(st) == before


def test_propose_pre_unsatisfied_degrades_to_narrate():
    st = _state()
    before = _fingerprint(st)
    # 提议 move_to 到不可达地点 → pre 不满足
    stub = lambda _p: {"transform": "move_to", "args": {"target": "roof"}}
    res, new_state = ir.route("随便发生点什么吧", st, _content(),
                              allow_propose=True, llm_propose=stub)
    _assert_resolution_keyset(res)
    assert res["mode"] == "narrate"
    assert res["ok"] is False
    assert res["reason"] == "precondition_failed:target_not_reachable"
    assert new_state is st
    assert _fingerprint(st) == before


def test_propose_forbidden_ra_number_degrades_to_narrate():
    st = _state()
    before = _fingerprint(st)
    stub = lambda _p: {"transform": "wait", "args": {"affection": 1}}
    res, new_state = ir.route("随便发生点什么吧", st, _content(),
                              allow_propose=True, llm_propose=stub)
    assert res["mode"] == "narrate"
    assert res["reason"] == "forbidden:emit_ra_number"
    assert new_state is st
    assert _fingerprint(st) == before


def test_propose_write_vars_is_rejected_fail_closed():
    """锁断言（架构师口径）：``write_vars`` **不是契约**，携带必被 `bad_args:unexpected_args:write_vars` 拒绝。

    写 var 的唯一通道是 ``effects``（``{field:<var名>,op,value}``）；本用例防止后人误以为
    ``write_vars`` 受支持而在 router/内容包里启用它。
    """
    st = _state()
    before = _fingerprint(st)
    # 内层用**已知 var 名**（poured ∈ DEFAULT_VAR_NAMES）：避免 is_forbidden 因"未知 var"抢先拒绝，
    # 从而精确锁住设计口径「write_vars 键本身结构外 → bad_args:unexpected_args:write_vars」。
    stub = lambda _p: {"transform": "wait", "args": {"write_vars": {"poured": "x"}}}
    res, new_state = ir.route("随便发生点什么吧", st, _content(),
                              allow_propose=True, llm_propose=stub)
    _assert_resolution_keyset(res)
    assert res["mode"] == "narrate"
    assert res["reason"] == "bad_args:unexpected_args:write_vars"
    assert new_state is st
    assert _fingerprint(st) == before


def test_propose_forbidden_checked_before_bad_args():
    """锁断言（§4.2 冻结校验序）：白名单 → **硬禁区** → args → pre。

    同一提议里既有硬禁区字段（``affection``）又有结构外键，**硬禁区优先命中**
    （``forbidden:emit_ra_number`` 先于 ``bad_args:unexpected_args``）。
    """
    st = _state()
    stub = lambda _p: {"transform": "wait", "args": {"affection": 1, "bogus_key": 1}}
    res, _new_state = ir.route("随便发生点什么吧", st, _content(),
                               allow_propose=True, llm_propose=stub)
    assert res["mode"] == "narrate"
    assert res["reason"] == "forbidden:emit_ra_number"


# ===========================================================================
# ③ narrate：四类 LLM 失败 → 全部 narrate、状态不变、**同一条代码路径**
# ===========================================================================

def _raise(exc: BaseException):
    def _fn(_p):
        raise exc
    return _fn


def test_llm_returning_none_degrades_to_narrate():
    st = _state()
    before = _fingerprint(st)
    res, new_state = ir.route("随便发生点什么吧", st, _content(),
                              allow_propose=True, llm_propose=lambda _p: None)
    _assert_resolution_keyset(res)
    assert res["mode"] == "narrate"
    assert res["ok"] is False
    assert res["reason"] == ir.REASON_LLM_DISABLED
    assert res["reason"].startswith("llm_")
    assert res["llm_used"] is True
    assert new_state is st
    assert _fingerprint(st) == before


def test_llm_malformed_json_degrades_to_narrate():
    st = _state()
    before = _fingerprint(st)
    res, new_state = ir.route("随便发生点什么吧", st, _content(),
                              allow_propose=True, llm_propose=lambda _p: "{oops not json")
    _assert_resolution_keyset(res)
    assert res["mode"] == "narrate"
    assert res["reason"] == ir.REASON_LLM_BAD_JSON
    assert res["reason"].startswith("llm_")
    assert new_state is st
    assert _fingerprint(st) == before


def test_llm_raising_exception_degrades_to_narrate():
    st = _state()
    before = _fingerprint(st)
    res, new_state = ir.route("随便发生点什么吧", st, _content(),
                              allow_propose=True, llm_propose=_raise(RuntimeError("boom")))
    _assert_resolution_keyset(res)
    assert res["mode"] == "narrate"
    assert res["reason"].startswith("llm_")
    assert res["llm_used"] is True
    assert new_state is st
    assert _fingerprint(st) == before


def test_llm_timeout_degrades_to_narrate():
    st = _state()
    before = _fingerprint(st)
    res, new_state = ir.route("随便发生点什么吧", st, _content(),
                              allow_propose=True, llm_propose=_raise(TimeoutError()))
    _assert_resolution_keyset(res)
    assert res["mode"] == "narrate"
    assert res["reason"] == ir.REASON_LLM_TIMEOUT
    assert res["reason"].startswith("llm_")
    assert res["llm_used"] is True
    assert new_state is st
    assert _fingerprint(st) == before


def test_four_llm_failures_share_one_code_path(monkeypatch):
    """★ 降级铁律（D-V22-12）：None / 畸形 / 抛异常 / 超时 **共用唯一兜底出口**。

    证据：① 四者 ``reason`` 同以 ``llm_`` 起头；② 四者都**恰好一次**经过共享兜底函数
    :func:`intent_router._narrate`（调用计数）；③ 四者 ``mode`` 同为 ``narrate``、状态不变。
    """
    st = _state()
    before = _fingerprint(st)

    seen = {"n": 0}
    real_narrate = ir._narrate

    def spy_narrate(state, *, reason, transform="", llm_used=False):
        seen["n"] += 1
        return real_narrate(state, reason=reason, transform=transform, llm_used=llm_used)

    monkeypatch.setattr(ir, "_narrate", spy_narrate)

    stubs = [
        lambda _p: None,                      # LLM 关闭 / 不可用
        lambda _p: "{not valid json",         # 畸形 JSON
        _raise(ValueError("net down")),       # 抛异常
        _raise(TimeoutError()),               # 超时
    ]

    reasons = []
    for stub in stubs:
        res, new_state = ir.route("随便发生点什么吧", st, _content(),
                                  allow_propose=True, llm_propose=stub)
        _assert_resolution_keyset(res)
        assert res["mode"] == "narrate"
        assert res["ok"] is False
        assert new_state is st
        assert _fingerprint(st) == before
        reasons.append(res["reason"])

    # ② 四者都恰好经过同一兜底函数一次
    assert seen["n"] == len(stubs)
    # ① 四者 reason 共用 llm_ 前缀
    assert all(r.startswith("llm_") for r in reasons), reasons
    # 四类各自的短码（None/异常 → disabled；畸形 → bad_json；超时 → timeout）
    assert reasons == [
        ir.REASON_LLM_DISABLED,
        ir.REASON_LLM_BAD_JSON,
        ir.REASON_LLM_DISABLED,
        ir.REASON_LLM_TIMEOUT,
    ], reasons


# ===========================================================================
# allow_propose=False：永不进 propose（LLM 桩零调用）
# ===========================================================================

def test_allow_propose_false_never_calls_llm():
    st = _state()
    before = _fingerprint(st)
    calls = {"n": 0}

    def stub(_prompt: str):
        calls["n"] += 1
        return {"transform": "wait", "args": {}}

    res, new_state = ir.route("随便发生点什么吧", st, _content(),
                              allow_propose=False, llm_propose=stub)
    _assert_resolution_keyset(res)
    assert calls["n"] == 0                    # LLM 桩一次都没被调用
    assert res["mode"] == "narrate"
    assert res["ok"] is False
    assert res["llm_used"] is False
    assert res["reason"] == ir.REASON_LLM_DISABLED
    assert new_state is st
    assert _fingerprint(st) == before


def test_allow_propose_false_still_applies_verbatim():
    # 关闭 propose 只挡 LLM 提议，已命中的 verbatim 仍生效
    st = _state()
    calls = {"n": 0}
    res, new_state = ir.route("我拿起那张旧照片", st, _content(),
                              allow_propose=False,
                              llm_propose=lambda _p: calls.__setitem__("n", calls["n"] + 1))
    assert res["mode"] == "verbatim"
    assert res["ok"] is True
    assert calls["n"] == 0
    assert "old_photo" in new_state["vars"]["held_items"]


def test_llm_not_injected_and_allow_propose_true_degrades_to_narrate():
    # LLM 不可用（未注入 callable）→ 与「LLM 关闭」同路径
    st = _state()
    res, new_state = ir.route("随便发生点什么吧", st, _content(),
                              allow_propose=True, llm_propose=None)
    assert res["mode"] == "narrate"
    assert res["reason"] == ir.REASON_LLM_DISABLED
    assert new_state is st


# ===========================================================================
# 确定性：同 seed + 同 turn + 同 LLM 桩 ⇒ 两次结果一致
# ===========================================================================

def test_determinism_same_seed_turn_same_result():
    stub = lambda _p: {"transform": "wait", "args": {}}
    results = []
    for _ in range(2):
        st = _state()
        res, new_state = ir.route("随便发生点什么吧", st, _content(),
                                  allow_propose=True, llm_propose=stub, seed=777)
        results.append((json.dumps(res, ensure_ascii=False, sort_keys=True),
                        _fingerprint(new_state)))
    assert results[0] == results[1]


def test_determinism_verbatim_random_move_is_seed_reproducible():
    # move_to 缺 target → engine 按 seed+turn 确定性选；同 seed 两次应一致
    results = []
    for _ in range(2):
        st = _state()
        res, new_state = ir.route("我四处走走", st, _content(), allow_propose=False, seed=2024)
        assert res["mode"] == "verbatim"
        assert res["transform"] == "move_to"
        results.append(new_state["scene_id"])
    assert results[0] == results[1]
    assert results[0] in ("bar", "room")


# ===========================================================================
# 入参不可用 → TavernRouteError（调用方编程错误，非 LLM 失败降级）
# ===========================================================================

def test_route_rejects_non_dict_state():
    from gui.tavern.errors import TavernRouteError
    with pytest.raises(TavernRouteError):
        ir.route("你好", ["not", "a", "dict"], _content())


def test_route_rejects_bad_input_kind():
    from gui.tavern.errors import TavernRouteError
    with pytest.raises(TavernRouteError):
        ir.route("你好", _state(), _content(), input_kind="sms")


# ===========================================================================
# 留痕字段：所有路径键集一致
# ===========================================================================

def test_all_paths_share_required_keyset():
    st = _state()
    cases = [
        ir.route("我拿起那张旧照片", st, _content(), allow_propose=False),            # verbatim ok
        ir.route("嗯…今天天气不错", st, _content(), allow_propose=False),              # narrate（未命中）
        ir.route("随便发生点什么吧", st, _content(), allow_propose=True,
                 llm_propose=lambda _p: {"transform": "wait", "args": {}}),            # propose ok
        ir.route("随便发生点什么吧", st, _content(), allow_propose=True,
                 llm_propose=lambda _p: None),                                        # narrate（LLM 关闭）
        ir.route("c_take", st, _content(), input_kind="choice", allow_propose=False),  # choice verbatim
    ]
    for res, _new_state in cases:
        _assert_resolution_keyset(res)


# ===========================================================================
# 严格 JSON 提示词（确定性 + 含白名单枚举）
# ===========================================================================

def test_strict_json_prompt_is_deterministic_and_lists_whitelist():
    st = _state()
    p1 = ir.build_strict_json_prompt(st, _content())
    p2 = ir.build_strict_json_prompt(st, _content())
    assert p1 == p2
    for transform in m.TRANSFORM_WHITELIST:
        assert transform in p1
    assert '"transform"' in p1


# ===========================================================================
# 零 Qt：屏蔽 PySide6 后 import 仍成功（子进程实证）
# ===========================================================================

def test_router_import_is_zero_qt():
    code = (
        "import builtins, sys\n"
        "real = builtins.__import__\n"
        "def guard(name, *a, **k):\n"
        "    if name == 'PySide6' or name.startswith('PySide6.'):\n"
        "        raise AssertionError('router imported PySide6: ' + name)\n"
        "    return real(name, *a, **k)\n"
        "builtins.__import__ = guard\n"
        "import gui.tavern.intent_router as r\n"
        "assert 'PySide6' not in sys.modules, 'PySide6 leaked into sys.modules'\n"
        "print('ZERO_QT_OK', len(r.VERB_WORDS), len(r.TRANSFORM_WHITELIST))\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT),
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "ZERO_QT_OK 7 7" in proc.stdout


# ===========================================================================
# 无网络：AST 扫描确认模块不 import 任何网络库
# ===========================================================================

_NETWORK_MODULES = (
    "socket", "ssl", "urllib", "http", "requests", "httpx", "aiohttp",
    "ftplib", "telnetlib", "smtplib", "asyncio",
)


def test_router_imports_no_network_library():
    src = (ROOT / "gui" / "tavern" / "intent_router.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                imported.add(node.module.split(".")[0])
    offenders = imported & set(_NETWORK_MODULES)
    assert not offenders, f"router 不应 import 网络库：{offenders}"
