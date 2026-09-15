"""tests/test_v22_model.py —— V22-00 酒馆契约冻结 · 纯函数断言。

覆盖 design-v22 §4 的「形状」冻结（**确定性、不依赖墙钟、不依赖 Qt**）：
    * ``SCHEMA_VERSION`` 与 ``default_tavern()`` 顶层键集合（与 §4.1 逐键对齐）；
    * 7 变换白名单**恰好 7 条**且名字与设计一致（含 ``pre``/``post`` 声明存在）；
    * 三级路由枚举成员与 ``resolution`` 必填字段集合；
    * ``PROMPT_SEGMENTS`` 的**顺序**与段名；
    * 6 条硬禁区常量存在且语义不重复；
    * ``merge_defaults({})`` 不抛（读时迁移「零迁移」前提）+ 类型守卫 + 未知字段保留。

所有用例只 import ``gui.tavern.*``（零 Qt 链）；不建 ``QApplication``，不受墙钟影响。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import gui.tavern as tavern_pkg
from gui.tavern import model as m

ROOT = Path(__file__).resolve().parent.parent

_FIXED_TS = "2026-09-15T20:00:00+08:00"


# ---------------------------------------------------------------------------
# §4.1 顶层结构
# ---------------------------------------------------------------------------

def test_schema_version_is_one():
    assert m.SCHEMA_VERSION == 1
    assert tavern_pkg.SCHEMA_VERSION == 1


def test_default_tavern_top_level_key_set_exact():
    d = m.default_tavern(now=_FIXED_TS)
    # 顶层键集合与 §4.1 逐键对齐：多一个少一个都失败
    assert set(d) == set(m.TOP_LEVEL_KEYS)
    assert len(d) == len(m.TOP_LEVEL_KEYS)
    assert m.TOP_LEVEL_KEYS == (
        "schema_version",
        "meta",
        "settings",
        "library",
        "plays",
        "active_play_id",
        "journal",
    )


def test_default_tavern_values_match_design():
    d = m.default_tavern(now=_FIXED_TS)
    assert d["schema_version"] == 1
    assert d["meta"] == {"created_at": _FIXED_TS, "updated_at": _FIXED_TS}
    assert d["settings"] == m.SETTING_DEFAULTS
    assert set(d["settings"]) == set(m.SETTING_KEYS)
    assert d["library"] == {"books": [], "bound_book_ids": [], "cast": []}
    assert d["plays"] == []
    assert d["active_play_id"] == ""
    assert d["journal"] == {"seen_endings": [], "unlocked_entries": [], "first_seen": {}}


def test_settings_defaults_exact():
    assert m.SETTING_DEFAULTS == {
        "worldbook_budget_chars": 1600,
        "worldbook_scan_depth": 4,
        "max_lore_entries_per_turn": 3,
        "recursive_max_depth": 2,
        "transcript_keep_turns": 14,
        "auto_summary_every": 8,
        "allow_free_input": True,
        "allow_propose": True,
        "llm_narration": True,
        "narrator_length": "short",
    }
    # 默认开启 propose（Q1 / D-V22-03）
    assert m.SETTING_DEFAULTS["allow_propose"] is True


# ---------------------------------------------------------------------------
# §4.2 变换白名单（恰好 7 条）
# ---------------------------------------------------------------------------

def test_transform_whitelist_exactly_seven_named():
    assert len(m.TRANSFORM_WHITELIST) == 7
    assert m.TRANSFORM_WHITELIST == (
        "move_to",
        "take",
        "give",
        "open",
        "ask_about",
        "wait",
        "order",
    )
    assert len(set(m.TRANSFORM_WHITELIST)) == 7  # 无重复
    assert tavern_pkg.TRANSFORM_WHITELIST == m.TRANSFORM_WHITELIST


def test_transform_specs_keyset_matches_whitelist():
    assert set(m.TRANSFORM_SPECS) == set(m.TRANSFORM_WHITELIST)
    for tid, spec in m.TRANSFORM_SPECS.items():
        assert spec.transform_id == tid
        # pre/post **签名声明**存在（本批只声明，不实现）
        assert isinstance(spec.pre, str) and spec.pre
        assert isinstance(spec.post, str) and spec.post
        assert isinstance(spec.touches, tuple)


# ---------------------------------------------------------------------------
# §4.2/§4.3 三级路由枚举与 resolution 字段形状
# ---------------------------------------------------------------------------

def test_route_modes_members():
    assert m.ROUTE_MODES == ("verbatim", "propose", "narrate")
    assert {mode.value for mode in m.RouteMode} == {"verbatim", "propose", "narrate"}
    assert len(m.ROUTE_MODES) == 3
    assert tavern_pkg.ROUTE_MODES == m.ROUTE_MODES


def test_resolution_required_keys_exact():
    assert m.RESOLUTION_REQUIRED_KEYS == ("mode", "transform", "ok", "reason", "llm_used")
    assert set(m.Resolution.__annotations__) == set(m.RESOLUTION_REQUIRED_KEYS)
    assert set(tavern_pkg.RESOLUTION_REQUIRED_KEYS) == {"mode", "transform", "ok", "reason", "llm_used"}


def test_transcript_entry_keys_exact():
    assert tuple(m.TRANSCRIPT_ENTRY_KEYS) == (
        "turn",
        "role",
        "input_kind",
        "text",
        "resolution",
        "narrated",
        "at",
    )
    assert set(m.TranscriptEntry.__annotations__) == set(m.TRANSCRIPT_ENTRY_KEYS)
    # 两条「直接施加」入口同为 verbatim 语义（§4.2）
    assert m.INPUT_KINDS == ("free", "choice")


# ---------------------------------------------------------------------------
# §4.3 五段式 prompt 段名（有序）
# ---------------------------------------------------------------------------

def test_prompt_segments_order_and_names():
    assert m.PROMPT_SEGMENTS == (
        "narrator_rules",
        "world_rules",
        "character_card",
        "turn_context",
        "history",
    )
    assert len(m.PROMPT_SEGMENTS) == 5
    assert len(set(m.PROMPT_SEGMENTS)) == 5
    assert set(m.PROMPT_SEGMENT_ROLES) == set(m.PROMPT_SEGMENTS)
    # 前 4 段 system，末段 history（§4.3 / D-V22-10）
    assert all(m.PROMPT_SEGMENT_ROLES[s] == "system" for s in m.PROMPT_SEGMENTS[:4])
    assert m.PROMPT_SEGMENT_ROLES["history"] == "history"
    assert tavern_pkg.PROMPT_SEGMENTS == m.PROMPT_SEGMENTS


# ---------------------------------------------------------------------------
# §4.2 6 条硬禁区（存在且语义不重复）
# ---------------------------------------------------------------------------

def test_forbidden_rules_six_unique_semantics():
    assert len(m.FORBIDDEN_RULES) == 6
    assert len(set(m.FORBIDDEN_RULES)) == 6  # id 无重复
    assert set(m.FORBIDDEN_RULES) == {rule.value for rule in m.ForbiddenRule}
    assert len({rule.value for rule in m.ForbiddenRule}) == 6
    # 语义不重复：6 条中文描述互不相同且非空
    assert set(m.FORBIDDEN_RULE_DESC) == set(m.FORBIDDEN_RULES)
    assert len(set(m.FORBIDDEN_RULE_DESC.values())) == 6
    assert all(m.FORBIDDEN_RULE_DESC[r].strip() for r in m.FORBIDDEN_RULES)
    # 第 4 条针对的结构字段（结构字段不参与玩法）
    assert set(m.FORBIDDEN_STRUCTURE_FIELDS) == {"meta", "schema_version", "settings"}


# ---------------------------------------------------------------------------
# §4.2 三条不变量 I1/I2/I3
# ---------------------------------------------------------------------------

def test_invariants_ids_and_rules():
    assert m.INVARIANTS == ("I1", "I2", "I3")
    assert set(m.INVARIANT_RULES) == set(m.INVARIANTS)
    assert len(set(m.INVARIANT_RULES.values())) == 3  # 语义不重复
    assert all(m.INVARIANT_RULES[i].strip() for i in m.INVARIANTS)


# ---------------------------------------------------------------------------
# §4.1 世界书条目结构
# ---------------------------------------------------------------------------

def test_worldbook_entry_fields_and_default():
    assert len(m.WORLDBOOK_ENTRY_FIELDS) == 18
    assert set(m.WorldbookEntry.__annotations__) == set(m.WORLDBOOK_ENTRY_FIELDS)
    entry = m.default_worldbook_entry()
    assert tuple(entry) == m.WORLDBOOK_ENTRY_FIELDS  # 字段齐全且顺序一致
    assert m.SELECTIVE_LOGIC_MODES == ("AND_ANY", "NOT_ALL", "NOT_ANY", "AND_ALL")
    assert m.LORE_POSITIONS == ("system_head", "system_tail", "history_depth")
    assert m.CONSTANT_ENTRY_LIMIT == 5
    assert m.LORE_MAX_CONTENT_CHARS == 200


# ---------------------------------------------------------------------------
# §4.1/§4.3 局结构
# ---------------------------------------------------------------------------

def test_new_play_key_set_exact():
    p = m.new_play("lantern", "灯笼还亮着", 1731845, now=_FIXED_TS)
    assert tuple(p) == m.PLAY_KEYS
    assert set(p) == set(m.PLAY_KEYS)
    assert p["status"] == "active"
    assert p["seed"] == 1731845
    assert p["vars"] == m.default_vars()
    assert p["summary"] == {"up_to_turn": 0, "text": "", "generated_by": "", "verified": False}
    # 默认 seed 可传 0
    assert m.default_play()["turn"] == 0


# ---------------------------------------------------------------------------
# §4.3/§5.4-4 读时迁移（零迁移前提）
# ---------------------------------------------------------------------------

def test_merge_defaults_empty_does_not_throw():
    d = m.merge_defaults({})
    assert set(d) == set(m.TOP_LEVEL_KEYS)
    assert d["schema_version"] == m.SCHEMA_VERSION
    assert d["settings"] == m.SETTING_DEFAULTS
    assert d["plays"] == []
    assert d["library"] == {"books": [], "bound_book_ids": [], "cast": []}
    # 非 dict 入参亦不抛
    assert set(m.merge_defaults(None)) == set(m.TOP_LEVEL_KEYS)
    assert set(m.merge_defaults([1, 2, 3])) == set(m.TOP_LEVEL_KEYS)
    assert set(m.merge_defaults("oops")) == set(m.TOP_LEVEL_KEYS)


def test_merge_defaults_type_guard_and_unknown_preserved():
    raw = {
        "schema_version": "2",
        "plays": "not-a-list",          # 类型错 → 回落默认
        "library": [],                  # 类型错 → 回落默认
        "settings": {
            "worldbook_budget_chars": "x",  # 类型错 → 回落 1600
            "allow_propose": False,         # 合法覆盖
            "future_key": 1,                # 未知设置项保留
        },
        "custom_top": {"a": 1},         # 未知顶层字段保留
    }
    d = m.merge_defaults(raw)
    assert d["schema_version"] == 2
    assert d["plays"] == []
    assert d["library"] == {"books": [], "bound_book_ids": [], "cast": []}
    assert d["settings"]["worldbook_budget_chars"] == 1600
    assert d["settings"]["allow_propose"] is False
    assert d["settings"]["future_key"] == 1
    assert d["custom_top"] == {"a": 1}
    # 入参不被就地修改
    assert raw["plays"] == "not-a-list"


def test_merge_play_type_guard_and_unknown_preserved():
    p = m.merge_play({
        "turn": 7,
        "vars": {"poured": "long_night"},
        "transcript": "oops",   # 类型错 → 回落 []
        "unknown": 5,           # 未知字段保留
    })
    assert p["turn"] == 7
    assert p["vars"]["poured"] == "long_night"
    assert p["vars"]["held_items"] == []   # 默认键补齐
    assert p["transcript"] == []
    assert p["unknown"] == 5
    assert p["status"] == "active"


def test_migrate_current_version_is_noop_and_no_downgrade():
    d = m.migrate({"schema_version": 1, "plays": [{"turn": 3}]})
    assert d["schema_version"] == m.SCHEMA_VERSION
    assert d["plays"][0]["turn"] == 3
    # L4：高于当前的版本不降级（只读加载语义）
    assert m.migrate({"schema_version": 99})["schema_version"] == 99


# ---------------------------------------------------------------------------
# 零 Qt：包入口不引入任何 UI 模块
# ---------------------------------------------------------------------------

def test_package_has_no_qt_symbols():
    # gui.tavern 的公开出口不含 Qt 符号；命名空间里不应出现 PySide6 相关名字
    leaked = [n for n in dir(tavern_pkg) if n.startswith("Q") and n[1:2].isupper()]
    assert leaked == [], f"gui.tavern 命名空间疑似泄漏 Qt 符号: {leaked}"


def test_package_entry_does_not_import_service_or_qt():
    """**干净进程**里 ``import gui.tavern`` 不得带出 ``service`` 子模块，也不得引入 PySide6。

    原先这里写的是本进程内断言 ``"service" not in dir(tavern_pkg)`` —— 该断言**随
    「本次跑了哪些测试文件」而变**，属假失败：pytest 在 **collection 阶段**就 import 了
    全部测试模块，``tests/test_v22_service.py:33`` 的
    ``from gui.tavern import service as svc_mod`` 会把 ``service`` 绑成父包属性
    （Python 语义：import 子模块即给父包设置同名属性）。于是单跑本文件通过、
    全量跑失败 —— 与产品代码无关。

    真正要守的口径是「**包入口自身**不 import ``service`` / 不引入 Qt」，故改为在全新
    解释器里验证：既免疫导入顺序，又能顺带抓住**传递性** Qt 泄漏（本进程内做不到）。
    """
    code = (
        "import sys\n"
        "import gui.tavern as pkg\n"
        "assert 'service' not in dir(pkg), 'service 子模块被 gui.tavern 入口带出: %r' % (sorted(dir(pkg)),)\n"
        "assert 'PySide6' not in sys.modules, 'PySide6 泄漏进 sys.modules'\n"
        "print('ENTRY_CLEAN_OK', len(pkg.__all__))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"干净进程导入 gui.tavern 失败：{proc.stderr}"
    assert "ENTRY_CLEAN_OK" in proc.stdout, proc.stdout
