"""tests/test_v22_engine.py —— V22-02 酒馆引擎 · 纯函数断言（确定性 / 无墙钟 / 无 Qt）。

覆盖 design-v22 §4.2 / §4.3 / §5 / §9.3 / §10.1 的 engine 验收要点：
    * **7 变换各 2 例**（pre 满足 → 施加成功且 post 效果正确；不满足 → 拒绝且 reason 正确）；
    * **6 条硬禁区各 1 例**被正确拒绝（reason = ``forbidden:<id>``）；
    * **I1 / I2 / I3 各 1 例违反**被聚合校验抓到，且该次施加被**回滚**（状态逐字节不变）；
    * **确定性**：同 seed + 同 turn 跑两次结果完全一致；不同 turn 可不同；
    * ``UNKNOWN_VAR`` 与 ``MAX_VARS`` 上限生效；
    * 施加失败时 ``resolution`` 必填键齐全（``mode/transform/ok/reason/llm_used``）；
    * **零 Qt**：屏蔽 PySide6 后 ``import gui.tavern.engine`` 仍成功（子进程实证）。

全部用例只 import ``gui.tavern.*``（零 Qt 链），不建 ``QApplication``，不依赖墙钟 / 随机全局态。
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from gui.tavern import model as m
from gui.tavern import engine as e

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# 夹具（纯数据；content 键全部可缺省）
# ---------------------------------------------------------------------------

def _content() -> dict:
    """「灯笼酒馆」最小内容包（覆盖 7 变换所需的全部查询面）。"""
    return {
        "node_ids": ["opening", "counter_photo", "ghost_node"],
        "scene_ids": ["bar", "counter", "room", "roof"],
        "reachable": {"bar": ["counter", "room"], "counter": ["bar"], "room": ["bar"], "roof": []},
        "known_topics": {"counter": ["photo", "music"]},
        "menu": {"counter": ["long_night", "moon"]},
        "open_conditions": {"counter:drawer": True, "vault": False},
        "var_names": ["custom_note"],
    }


def _state(**over) -> dict:
    """基准局状态：站在吧台前，桌上有 old_photo，身上有 key。"""
    s = m.new_play("lantern", "灯笼还亮着", 12345)
    s["scene_id"] = "counter"
    s["node_id"] = "counter_photo"
    s["turn"] = 0
    v = dict(m.default_vars())
    v["scene_items"] = ["old_photo"]
    v["held_items"] = ["key"]
    s["vars"] = v
    s.update(over)
    return s


def _fingerprint(obj) -> str:
    """逐字节指纹（用于「回滚 = 状态逐字节相同」断言）。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


# ===========================================================================
# 7 变换 × (pre 满足 / 不满足)
# ===========================================================================

# —— move_to ——

def test_move_to_pre_ok_sets_scene():
    st = _state()
    r = e.apply_transform(st, "move_to", {"target": "bar"}, _content())
    assert r.ok is True
    assert r.reason == "ok"
    assert r.transform == "move_to"
    assert r.state["scene_id"] == "bar"


def test_move_to_pre_fail_target_not_reachable():
    st = _state()
    r = e.apply_transform(st, "move_to", {"target": "roof"}, _content())
    assert r.ok is False
    assert r.reason == "precondition_failed:target_not_reachable"
    assert r.state is st  # 回滚：原对象


# —— take ——

def test_take_pre_ok_moves_item_to_hand():
    st = _state()
    r = e.apply_transform(st, "take", {"item": "old_photo"}, _content())
    assert r.ok is True
    assert "old_photo" in r.state["vars"]["held_items"]
    assert "old_photo" not in r.state["vars"]["scene_items"]


def test_take_pre_fail_item_not_in_scene():
    st = _state()
    r = e.apply_transform(st, "take", {"item": "ghost"}, _content())
    assert r.ok is False
    assert r.reason == "precondition_failed:item_not_in_scene"


# —— give ——

def test_give_pre_ok_moves_item_to_given():
    st = _state()
    r = e.apply_transform(st, "give", {"item": "key"}, _content())
    assert r.ok is True
    assert "key" in r.state["vars"]["given"]
    assert "key" not in r.state["vars"]["held_items"]


def test_give_pre_fail_item_not_held():
    st = _state()
    r = e.apply_transform(st, "give", {"item": "none"}, _content())
    assert r.ok is False
    assert r.reason == "precondition_failed:item_not_held"


# —— open ——

def test_open_pre_ok_appends_opened():
    st = _state()
    r = e.apply_transform(st, "open", {"key": "drawer"}, _content())
    assert r.ok is True
    assert r.state["vars"]["opened"] == ["drawer"]


def test_open_pre_fail_condition_not_met():
    st = _state()
    r = e.apply_transform(st, "open", {"key": "vault"}, _content())
    assert r.ok is False
    assert r.reason == "precondition_failed:condition_not_met"


# —— ask_about ——

def test_ask_about_pre_ok_appends_known():
    st = _state()
    r = e.apply_transform(st, "ask_about", {"topic": "photo"}, _content())
    assert r.ok is True
    assert r.state["vars"]["known"] == ["photo"]


def test_ask_about_pre_fail_topic_not_known():
    st = _state()
    r = e.apply_transform(st, "ask_about", {"topic": "weather"}, _content())
    assert r.ok is False
    assert r.reason == "precondition_failed:topic_not_known"


# —— wait ——

def test_wait_ok_advances_turn():
    st = _state()
    r = e.apply_transform(st, "wait", {}, _content())
    assert r.ok is True
    assert r.state["turn"] == 1


def test_wait_rejects_unexpected_args():
    # wait 无 pre（§4.2），故「拒绝」路径用 args 结构非法落点断言
    st = _state()
    r = e.apply_transform(st, "wait", {"target": "x"}, _content())
    assert r.ok is False
    assert r.reason == "bad_args:unexpected_args:target"


# —— order ——

def test_order_pre_ok_sets_poured():
    st = _state()
    r = e.apply_transform(st, "order", {"item": "long_night"}, _content())
    assert r.ok is True
    assert r.state["vars"]["poured"] == "long_night"


def test_order_pre_fail_item_not_on_menu():
    st = _state()
    r = e.apply_transform(st, "order", {"item": "water"}, _content())
    assert r.ok is False
    assert r.reason == "precondition_failed:item_not_on_menu"


def test_order_pre_fail_menu_empty():
    st = _state(scene_id="roof")
    r = e.apply_transform(st, "order", {}, _content())
    assert r.ok is False
    assert r.reason == "precondition_failed:menu_empty"


# ===========================================================================
# 6 条硬禁区（各 1 例）
# ===========================================================================

def test_forbidden_rewrite_history():
    st = _state()
    args = {"effects": [{"field": "transcript", "op": "edit", "value": {"turn": 0}}]}
    assert e.is_forbidden(st, "wait", args, _content()) == "rewrite_history"
    r = e.apply_transform(st, "wait", args, _content())
    assert r.ok is False
    assert r.reason == "forbidden:rewrite_history"


def test_forbidden_cross_chapter():
    st = _state()
    args = {"effects": [{"field": "chapter_id", "op": "set", "value": "ch2"}]}
    assert e.is_forbidden(st, "wait", args, _content()) == "cross_chapter"
    r = e.apply_transform(st, "wait", args, _content())
    assert r.ok is False
    assert r.reason == "forbidden:cross_chapter"


def test_forbidden_kill_revive_character():
    st = _state()
    args = {"effects": [{"field": "alive", "op": "set", "value": False}]}
    assert e.is_forbidden(st, "wait", args, _content()) == "kill_revive_character"
    r = e.apply_transform(st, "wait", args, _content())
    assert r.ok is False
    assert r.reason == "forbidden:kill_revive_character"


def test_forbidden_touch_structure():
    st = _state()
    args = {"settings": {}}
    assert e.is_forbidden(st, "wait", args, _content()) == "touch_structure"
    r = e.apply_transform(st, "wait", args, _content())
    assert r.ok is False
    assert r.reason == "forbidden:touch_structure"


def test_forbidden_emit_ra_number():
    st = _state()
    args = {"affection": 5}
    assert e.is_forbidden(st, "wait", args, _content()) == "emit_ra_number"
    r = e.apply_transform(st, "wait", args, _content())
    assert r.ok is False
    assert r.reason == "forbidden:emit_ra_number"


def test_forbidden_unknown_var():
    st = _state()
    args = {"effects": [{"field": "gold", "op": "set", "value": 1}]}
    assert e.is_forbidden(st, "wait", args, _content()) == "unknown_var"
    r = e.apply_transform(st, "wait", args, _content())
    assert r.ok is False
    assert r.reason == "forbidden:unknown_var"


def test_write_vars_is_not_a_channel_rejected_by_args():
    """``write_vars`` **不是**受支持的 args 键（单一写入通道 = ``effects``）。

    design-v22 §653/§1180 已定性：``ARG_KEYS`` 不收 ``write_vars``，故任何携带它的入参
    必被 ``bad_args:unexpected_args:write_vars`` 拒绝（fail-closed）。``is_forbidden`` 里
    原先那份对 ``write_vars`` 的扫描**永远走不到**（args 校验在后面才跑不到它），只留下
    "看起来支持 write_vars" 的误导 —— 已按 §1180 清理，本用例锁住清理后的单一口径。

    注：本用例此前断言的是 ``forbidden:unknown_var``，那是**死扫描**的产物，不是契约。
    """
    st = _state()
    args = {"write_vars": {"gold": 1}}
    # 硬禁区**不再**为 write_vars 背锅（它只看 effects / 顶层键名）
    assert e.is_forbidden(st, "wait", args, _content()) is None
    r = e.apply_transform(st, "wait", args, _content())
    assert r.ok is False
    assert r.reason == "bad_args:unexpected_args:write_vars"


# ===========================================================================
# 三条不变量：违反 → 聚合抓到 + 施加被回滚（逐字节不变）
# ===========================================================================

def test_invariant_i1_overlap_rolls_back():
    # state 里同一物品在桌上出现两次：take 一次后仍在桌上，且被拿进手里 → held ∩ scene ≠ ∅
    v = dict(m.default_vars())
    v["scene_items"] = ["key", "key"]
    v["held_items"] = []
    st = _state(vars=v)
    before = _fingerprint(st)
    assert e.check_invariants(st, _content(), prev_state=st) == []  # 施加前干净

    r = e.apply_transform(st, "take", {"item": "key"}, _content())
    assert r.ok is False
    assert r.reason.startswith("invariant_violated:I1")
    assert _fingerprint(r.state) == before  # 回滚：状态与施加前逐字节相同


def test_invariant_i2_dangling_scene_rolls_back():
    content = _content()
    # 故意把 reachable 指向一个不在 scene_ids 里的地点（悬空引用）
    content["reachable"] = {"counter": ["ghost_scene"]}
    st = _state()
    before = _fingerprint(st)

    r = e.apply_transform(st, "move_to", {}, content)  # 无 target → 确定性取 reachable 里的 ghost_scene
    assert r.ok is False
    assert r.reason.startswith("invariant_violated:I2")
    assert "ghost_scene" in r.reason
    assert _fingerprint(r.state) == before


def test_invariant_i3_transcript_shrunk_rolls_back():
    st = _state(transcript=[{"turn": 0, "role": "player", "input_kind": "free", "text": "……",
                             "resolution": {"mode": "narrate", "transform": "", "ok": False,
                                            "reason": "ok", "llm_used": False},
                             "narrated": False, "at": "2026-09-15T20:00:00+08:00"}])
    before = _fingerprint(st)
    args = {"effects": [{"field": "transcript", "op": "set", "value": []}]}

    r = e.apply_transform(st, "wait", args, _content())
    assert r.ok is False
    assert r.reason.startswith("invariant_violated:I3")
    assert _fingerprint(r.state) == before


def test_check_invariants_clean_state_empty():
    assert e.check_invariants(_state(), _content()) == []


# ===========================================================================
# 确定性（显式 seed）
# ===========================================================================

def test_derive_rng_is_reproducible():
    assert isinstance(e.derive_rng(7, 3), type(e.derive_rng(7, 3)))
    a = [e.derive_rng(7, 3).randrange(1000) for _ in range(3)]
    b = [e.derive_rng(7, 3).randrange(1000) for _ in range(3)]
    assert a == b  # 同 seed + 同 turn ⇒ 同序列


def test_deterministic_choice_same_inputs_same_result():
    menu = ["a", "b", "c", "d"]
    assert e.deterministic_choice(menu, 42, 5) == e.deterministic_choice(menu, 42, 5)
    assert e.deterministic_choice([], 42, 5) is None


def test_deterministic_choice_varies_across_turns():
    menu = ["a", "b", "c", "d"]
    picks = {e.deterministic_choice(menu, 42, t) for t in range(20)}
    assert len(picks) >= 2  # 不同 turn ⇒ 可不同（未被固定死）


def test_order_without_item_is_deterministic():
    st1 = _state()
    st2 = _state()
    r1 = e.apply_transform(st1, "order", {}, _content())
    r2 = e.apply_transform(st2, "order", {}, _content())
    assert r1.ok and r2.ok
    assert r1.state["vars"]["poured"] == r2.state["vars"]["poured"]
    assert r1.state["vars"]["poured"] in ["long_night", "moon"]


# ===========================================================================
# vars 白名单 / MAX_VARS
# ===========================================================================

def test_write_vars_known_name_allowed():
    st = _state()
    args = {"effects": [{"field": "custom_note", "op": "set", "value": "灯还亮着"}]}
    r = e.apply_transform(st, "wait", args, _content())
    assert r.ok is True
    assert r.state["vars"]["custom_note"] == "灯还亮着"


def test_max_vars_limit_enforced():
    content = _content()
    content["var_names"] = ["a1", "a2"]  # 基底 7 + 2 = 9 > MAX_VARS(8)
    args = {"effects": [{"field": "a1", "op": "set", "value": 1},
                        {"field": "a2", "op": "set", "value": 2}]}
    r = e.apply_transform(_state(), "wait", args, content)
    assert r.ok is False
    assert r.reason == "bad_args:max_vars_exceeded"


def test_max_vars_constant_matches_design():
    assert m.MAX_VARS == 8  # §4.2「建议 vars ≤ 8 个命名值」


# ===========================================================================
# 其他校验路径 / 留痕 / 契约
# ===========================================================================

def test_unknown_transform_rejected():
    r = e.apply_transform(_state(), "fly_away", {}, _content())
    assert r.ok is False
    assert r.reason == "unknown_transform"


def test_non_dict_state_rejected():
    r = e.apply_transform("not-a-dict", "wait", {}, _content())
    assert r.ok is False
    assert r.reason == "bad_args:state_not_dict"


def test_validate_does_not_mutate_state():
    st = _state()
    before = _fingerprint(st)
    vr = e.validate(st, "take", {"item": "old_photo"}, _content())
    assert vr.ok is True
    assert vr.state is st
    assert _fingerprint(st) == before


def test_apply_success_does_not_mutate_input():
    st = _state()
    before = _fingerprint(st)
    r = e.apply_transform(st, "take", {"item": "old_photo"}, _content())
    assert r.ok is True
    assert r.state is not st           # 新对象
    assert _fingerprint(st) == before  # 入参逐字节不变


def test_build_resolution_required_keys_on_failure():
    st = _state()
    r = e.apply_transform(st, "take", {"item": "ghost"}, _content())
    assert r.ok is False
    res = e.build_resolution(r, mode="propose", llm_used=True)
    assert set(res) == set(m.RESOLUTION_REQUIRED_KEYS)
    assert res["mode"] == "propose"
    assert res["transform"] == "take"
    assert res["ok"] is False
    assert res["reason"] == "precondition_failed:item_not_in_scene"
    assert res["llm_used"] is True


def test_reasons_are_known_codes():
    st = _state()
    results = [
        e.apply_transform(st, "wait", {}, _content()),                       # ok
        e.apply_transform(st, "fly_away", {}, _content()),                   # unknown_transform
        e.apply_transform(st, "take", {"item": "ghost"}, _content()),        # precondition_failed:*
        e.apply_transform(st, "wait", {"affection": 1}, _content()),         # forbidden:*
        e.apply_transform(st, "wait", {"target": "x"}, _content()),          # bad_args:*
    ]
    for r in results:
        assert e.is_known_reason(r.reason), r.reason
    assert e.is_known_reason("ok")
    assert not e.is_known_reason("nonsense_code")


def test_strict_mode_raises_frozen_exceptions():
    from gui.tavern.errors import TavernForbiddenError, TavernValidationError
    with pytest.raises(TavernForbiddenError):
        e.apply_transform(_state(), "wait", {"affection": 1}, _content(), strict=True)
    with pytest.raises(TavernValidationError):
        e.apply_transform(_state(), "fly_away", {}, _content(), strict=True)


def test_apply_result_is_frozen():
    r = e.ApplyResult(True, {}, "ok", "wait")
    with pytest.raises(Exception):
        r.ok = False  # frozen dataclass


def test_engine_reuses_frozen_single_invariant_checks():
    # §4.3 归属：单条判定在 model，engine 只做聚合 —— 二者同源、结果一致
    v = dict(m.default_vars())
    v["held_items"] = ["x"]
    v["scene_items"] = ["x"]
    bad = _state(vars=v)
    assert m.check_i1(bad) is not None
    assert any(code.startswith("I1") for code in e.check_invariants(bad, _content()))


# ===========================================================================
# 零 Qt：屏蔽 PySide6 后 import 仍成功（子进程实证）
# ===========================================================================

def test_engine_import_is_zero_qt():
    code = (
        "import builtins, sys\n"
        "real = builtins.__import__\n"
        "def guard(name, *a, **k):\n"
        "    if name == 'PySide6' or name.startswith('PySide6.'):\n"
        "        raise AssertionError('engine imported PySide6: ' + name)\n"
        "    return real(name, *a, **k)\n"
        "builtins.__import__ = guard\n"
        "import gui.tavern.engine as eng\n"
        "assert 'PySide6' not in sys.modules, 'PySide6 leaked into sys.modules'\n"
        "print('ZERO_QT_OK', len(eng.TRANSFORM_WHITELIST))\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT),
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "ZERO_QT_OK 7" in proc.stdout
