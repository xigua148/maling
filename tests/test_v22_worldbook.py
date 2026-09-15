"""tests/test_v22_worldbook.py —— V22-04 世界书 · 纯函数断言。

覆盖 design-v22 §5.4-14 / D-V22-09 与 §9.3-6 的可断言点（**确定性、纯函数、无墙钟、无 Qt**）：

    1. 四种 selective logic（``AND_ANY`` / ``NOT_ALL`` / ``NOT_ANY`` / ``AND_ALL``）各 1 例
       （**含必须不命中的负例**）；
    2. 预算四项各自生效：超 ``budget_chars`` / 超 ``max_entries`` / 超 ``CONSTANT_ENTRY_LIMIT`` /
       单条超 ``LORE_MAX_CONTENT_CHARS``；且**裁剪后总量不超预算**；
    3. 淘汰顺序 ``weight↓ → order↓ → uid↑``；
    4. 递归：达到 ``recursive_max_depth`` 即停，**收敛且有上界**；
    5. 脏数据：坏条目 / 未知字段 / 空关键词 / 重复 uid **各 1 例**，不崩且行为符合设计；
    6. ``LORE_POSITIONS`` 三种落点分类正确；
    7. 随包内容包（``content/lantern``）可读且结构合规；
    8. 源码零 Qt（AST 扫描 + 命名空间无 ``Q*`` 符号）。

所有用例只 import ``gui.tavern.*``（零 Qt 链）；不建 ``QApplication``，不受墙钟影响。
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from gui.tavern import worldbook as wb
from gui.tavern.errors import TavernContentError
from gui.tavern.model import (
    CONSTANT_ENTRY_LIMIT,
    DEFAULT_VAR_NAMES,
    LORE_MAX_CONTENT_CHARS,
    LORE_POSITIONS,
    SELECTIVE_LOGIC_MODES,
    default_worldbook_entry,
)


# ---------------------------------------------------------------------------
# 夹具小工具
# ---------------------------------------------------------------------------

def mk(**over) -> dict:
    """从类默认出发覆盖若干字段，得到一条 18 字段条目。"""
    entry = default_worldbook_entry()
    entry.update(over)
    return entry


def mk_body(uid: int, content: str, **over) -> dict:
    """构造一条「正文 + 字段覆盖」的条目（默认给一个可命中主键）。"""
    return mk(uid=uid, content=content, keys=["命"], **over)


# ===========================================================================
# 1. 四种 selective logic（含负例）
# ===========================================================================

def test_and_any_positive_and_negative():
    entry = mk(keys=["照片"], secondary_keys=["吧台"], selective_logic="AND_ANY")
    # 正例：主键 + 任一次键命中 → 激活
    assert wb.entry_activates(entry, ["我看看这张照片，就在吧台边上"]) is True
    # 负例：只有主键命中、无次键 → 不激活
    assert wb.entry_activates(entry, ["我看看这张照片"]) is False


def test_and_all_positive_and_negative():
    entry = mk(keys=["酒"], secondary_keys=["长夜", "一杯"], selective_logic="AND_ALL")
    # 正例：主键 + **全部**次键命中 → 激活
    assert wb.entry_activates(entry, ["给我来一杯长夜酒"]) is True
    # 负例：只命中一个次键 → 不激活
    assert wb.entry_activates(entry, ["给我来一杯酒吧"]) is False


def test_not_all_positive_and_negative():
    entry = mk(keys=["客人"], secondary_keys=["雨", "风"], selective_logic="NOT_ALL")
    # 正例：次键**非全部**命中（这里命中 1/2）→ 激活
    assert wb.entry_activates(entry, ["有个客人进来，外面在下雨"]) is True
    # 负例：次键**全部**命中 → 不激活
    assert wb.entry_activates(entry, ["客人和雨，还有风"]) is False


def test_not_any_positive_and_negative():
    entry = mk(keys=["名字"], secondary_keys=["已经", "早就"], selective_logic="NOT_ANY")
    # 正例：次键 0 命中 → 激活
    assert wb.entry_activates(entry, ["我想知道你的名字"]) is True
    # 负例：任一次键命中 → 不激活
    assert wb.entry_activates(entry, ["我早就知道你的名字"]) is False


def test_all_four_logic_modes_are_covered():
    # 每种档位都构造一组「真例 / 假例」，确保四态均有独立实现分支
    cases = {
        "AND_ANY": ("k s1", "k"),
        "AND_ALL": ("k s1 s2", "k s1"),
        "NOT_ALL": ("k s1", "k s1 s2"),
        "NOT_ANY": ("k", "k s1"),
    }
    assert set(cases) == set(SELECTIVE_LOGIC_MODES)
    for logic, (pos, neg) in cases.items():
        entry = mk(keys=["k"], secondary_keys=["s1", "s2"], selective_logic=logic)
        assert wb.entry_activates(entry, [pos]) is True, f"{logic} 真例应命中"
        assert wb.entry_activates(entry, [neg]) is False, f"{logic} 假例不应命中"


# ===========================================================================
# 2. 预算四项
# ===========================================================================

def test_budget_chars_trims_and_total_within_budget():
    book = wb.WorldBook([], budget_chars=25, scan_depth=4, max_entries=10, recursive_max_depth=2)
    entries = [mk_body(i, "a" * 10, weight=100, order=100) for i in (1, 2, 3)]
    selected = book.select_within_budget(entries)
    used = sum(len(e["content"]) for e in selected)
    assert used <= 25                      # 裁剪后总量不超预算
    assert len(selected) == 2              # 第 3 条加入会超预算 → 截断
    assert used == 20


def test_max_entries_per_turn_trims():
    book = wb.WorldBook([], budget_chars=10_000, scan_depth=4, max_entries=3, recursive_max_depth=2)
    entries = [mk_body(i, "a", weight=100, order=100) for i in range(1, 6)]
    selected = book.select_within_budget(entries)
    assert len(selected) == 3
    # constant 不占名额，但本次全为非 constant
    assert all(not e["constant"] for e in selected)


def test_constant_entry_limit_disables_overflow():
    raws = [mk(uid=i, content=f"世界规则 {i}", constant=True) for i in range(1, 8)]  # 7 条 constant
    result = wb.load_entries(raws)
    enabled_constants = [e for e in result.entries if e["constant"] and e["enabled"]]
    assert len(enabled_constants) == CONSTANT_ENTRY_LIMIT  # 恰好 5 条生效
    assert result.disabled >= 2                             # 其余被禁用
    assert any(i.level == wb.LEVEL_DISABLED and i.field == "constant" for i in result.issues)


def test_single_entry_over_limit_is_truncated():
    entry, issues = wb.normalize_entry(mk_body(9, "字" * (LORE_MAX_CONTENT_CHARS + 60)))
    assert entry is not None
    assert len(entry["content"]) == LORE_MAX_CONTENT_CHARS   # 截断到上限
    assert any(i.level == wb.LEVEL_TRUNCATED for i in issues)


def test_eviction_order_weight_order_uid():
    book = wb.WorldBook([], budget_chars=15, scan_depth=4, max_entries=10, recursive_max_depth=2)
    entries = [
        mk_body(1, "a" * 10, weight=10, order=100),
        mk_body(2, "a" * 10, weight=200, order=100),
        mk_body(3, "a" * 10, weight=50, order=100),
    ]
    selected = book.select_within_budget(entries)
    # 只够放 1 条 → 取 weight 最高者
    assert len(selected) == 1
    assert selected[0]["uid"] == 2

    # 同 weight 时看 order 降序
    same_w = [
        mk_body(1, "a" * 10, weight=100, order=10),
        mk_body(2, "a" * 10, weight=100, order=99),
    ]
    assert book.select_within_budget(same_w)[0]["uid"] == 2


def test_legitimate_zero_values_are_preserved():
    # 合法的 0 不应被「or 默认」吞掉（order=0 / weight=0 / depth=0 均为有效值）
    entry, _ = wb.normalize_entry(mk(uid=1, content="正文", keys=["k"], order=0, weight=0, depth=0))
    assert entry is not None
    assert entry["order"] == 0
    assert entry["weight"] == 0
    assert entry["depth"] == 0


# ===========================================================================
# 3. 递归：深度上界与收敛
# ===========================================================================

def test_recursive_stops_at_max_depth_and_converges():
    # A(recursive) 正文提到 B/C 的主键；B(recursive) 正文提到 A 的主键 → 会自激
    entries = [
        mk(uid=1, keys=["aa"], content="这里提到 bb 和 cc", recursive=True),
        mk(uid=2, keys=["bb"], content="这里提到 aa", recursive=True),
        mk(uid=3, keys=["cc"], content="只有 cc 的正文", recursive=False),
    ]
    book = wb.WorldBook(entries, budget_chars=10_000, scan_depth=4, max_entries=10, recursive_max_depth=2)
    selection = book.collect(["aa"])
    # 达到深度上限即停，且收敛（不会无限展开）
    assert selection.depth_reached <= 2
    assert selection.depth_reached == 2
    uids = {e["uid"] for e in selection.entries}
    assert {1, 2, 3} <= uids            # 递归确实把 B、C 拉进来了

    # 把上限抬高到 100：仍应收敛在同一深度（无新条目）
    book2 = wb.WorldBook(entries, budget_chars=10_000, scan_depth=4, max_entries=10, recursive_max_depth=100)
    sel2 = book2.collect(["aa"])
    assert sel2.depth_reached == 2
    assert sel2.depth_reached <= 100


def test_recursive_self_loop_terminates():
    entry = mk(uid=9, keys=["x"], content="x 会自己提到 x", recursive=True)
    book = wb.WorldBook([entry], budget_chars=10_000, scan_depth=4, max_entries=10, recursive_max_depth=2)
    selection = book.collect(["x"])
    # visited 集合命中自身 → 递归不再推进（1 层即收敛）
    assert selection.depth_reached == 1
    assert selection.depth_reached <= 2


def test_recursive_disabled_by_default_knob():
    entry = mk(uid=1, keys=["aa"], content="提到 bb", recursive=True)
    other = mk(uid=2, keys=["bb"], content="正文", recursive=False)
    book = wb.WorldBook([entry, other], budget_chars=10_000, scan_depth=4, max_entries=10, recursive_max_depth=0)
    selection = book.collect(["aa"])
    assert selection.depth_reached == 0
    assert {e["uid"] for e in selection.entries} == {1}  # 深度 0 → 不递归


# ===========================================================================
# 4. 脏数据（坏条目 / 未知字段 / 空关键词 / 重复 uid）
# ===========================================================================

def test_dirty_bad_entry_is_dropped_not_crash():
    result = wb.load_entries(["这是坏条目", 123, mk_body(2, "正常正文")])
    assert result.ok is True
    assert result.dropped >= 2
    assert len(result.entries) == 1
    assert result.entries[0]["uid"] == 2
    assert any(i.level == wb.LEVEL_DROPPED and i.field == "<entry>" for i in result.issues)


def test_dirty_unknown_field_preserved():
    entry, issues = wb.normalize_entry(mk_body(5, "正文", future_field=42))
    assert entry is not None
    assert entry["future_field"] == 42                       # 前向兼容：未知字段不销毁
    assert any(i.level == wb.LEVEL_UNKNOWN and i.field == "future_field" for i in issues)


def test_dirty_empty_keys_disables_non_constant():
    entry, issues = wb.normalize_entry(mk(uid=6, content="有正文但没有主键", keys=[], constant=False))
    assert entry is not None
    assert entry["enabled"] is False                          # 无主键 → 永久禁用
    assert any(i.level == wb.LEVEL_DISABLED and i.field == "keys" for i in issues)
    # 禁用后不会被触发
    assert wb.entry_activates(entry, ["任意文本"]) is False


def test_dirty_duplicate_uid_keeps_first():
    a = mk_body(7, "第一条")
    b = mk_body(7, "第二条")
    result = wb.load_entries([a, b])
    assert len(result.entries) == 1
    assert result.entries[0]["content"] == "第一条"           # 保留首个
    assert result.dropped >= 1
    assert any(i.level == wb.LEVEL_DROPPED and i.field == "uid" for i in result.issues)


def test_load_book_file_bad_json_controlled(tmp_path):
    path = tmp_path / "book.json"
    path.write_text("{ 这不是合法 JSON ", encoding="utf-8")
    # 非 strict：返回空结果 + 留痕，不抛
    result = wb.load_book_file(path)
    assert result.ok is False
    assert result.entries == []
    assert any(i.level == wb.LEVEL_ERROR for i in result.issues)
    # strict：受控抛 TavernContentError（携带 source）
    with pytest.raises(TavernContentError) as excinfo:
        wb.load_book_file(path, strict=True)
    assert excinfo.value.source.endswith("book.json")


def test_load_book_file_missing_not_crash(tmp_path):
    result = wb.load_book_file(tmp_path / "nope.json")
    assert result.ok is False and result.entries == []


def test_dirty_regex_key_compiles_or_is_dropped():
    # 合法正则键可命中；非法正则键被丢弃但不崩
    good = mk(uid=1, keys=["/长夜(酒)?/i"], content="正文")
    assert wb.entry_activates(good, ["长夜"]) is True
    bad = mk(uid=2, keys=["/[未闭合/"], content="正文")
    # 非法正则在编译期不会炸；该键被丢弃 → 无有效主键 → 不命中
    assert wb.entry_activates(bad, ["/[未闭合/"]) is False


# ===========================================================================
# 5. LORE_POSITIONS 三种落点分类
# ===========================================================================

def test_three_positions_classified_correctly():
    entries = [
        mk(uid=1, content="世界规则", constant=True, position="system_head"),
        mk(uid=2, content="本回合情境", keys=["触发"], position="system_tail"),
        mk(uid=3, content="历史内注入", keys=["深度"], position="history_depth", depth=3),
    ]
    book = wb.WorldBook(entries, budget_chars=10_000, scan_depth=4, max_entries=10, recursive_max_depth=2)
    selection = book.collect(["触发 深度"])
    assert set(selection.by_position) == set(LORE_POSITIONS)         # 三种键恒在
    assert [e["uid"] for e in selection.by_position["system_head"]] == [1]
    assert [e["uid"] for e in selection.by_position["system_tail"]] == [2]
    assert [e["uid"] for e in selection.by_position["history_depth"]] == [3]
    assert selection.used_chars == sum(len(e["content"]) for e in selection.entries)


def test_scan_depth_limits_window():
    entry = mk(uid=1, keys=["触发"], content="正文")
    book = wb.WorldBook([entry], budget_chars=10_000, scan_depth=1, max_entries=10, recursive_max_depth=0)
    # 命中词只出现在更早的拍（被 scan_depth=1 排除）→ 不触发
    assert book.match(["这里有触发", "最近这拍无关"]) == []
    # 命中词在最近一拍 → 触发
    assert [e["uid"] for e in book.match(["旧", "这里有触发"])] == [1]


# ===========================================================================
# 6. 随包内容包
# ===========================================================================

def test_builtin_content_pack_loads_and_is_valid():
    result = wb.load_builtin_book("lantern")
    assert result.ok is True
    assert result.entries, "内容包应至少含 1 本书的条目"
    # 字段齐全（恰好 18 字段 + 可能的未知保留字段）
    from gui.tavern.model import WORLDBOOK_ENTRY_FIELDS
    for entry in result.entries:
        assert set(WORLDBOOK_ENTRY_FIELDS) <= set(entry)
        assert len(entry["content"]) <= LORE_MAX_CONTENT_CHARS
    enabled_constants = [e for e in result.entries if e["constant"] and e["enabled"]]
    assert len(enabled_constants) <= CONSTANT_ENTRY_LIMIT
    # 四种 selective logic 均在包内出现
    logics = {e["selective_logic"] for e in result.entries}
    assert set(SELECTIVE_LOGIC_MODES) <= logics
    # 三种落点均在包内出现
    positions = {e["position"] for e in result.entries}
    assert set(LORE_POSITIONS) <= positions


def test_content_dir_resolves_under_gui():
    d = wb.content_dir()
    assert d.name == "content"
    assert d.parent.name == "tavern"
    assert (d / "lantern" / "book.json").exists()


# ===========================================================================
# 6b. 内容包 ↔ engine 读取键契约（design-v22 §4.2）
# ===========================================================================

_FROZEN_CONTENT_KEYS = (
    "node_ids",
    "scene_ids",
    "reachable",
    "known_topics",
    "menu",
    "open_conditions",
    "openable",
    "var_names",
)


def test_load_content_has_all_frozen_keys():
    content = wb.load_content("lantern")
    for key in _FROZEN_CONTENT_KEYS:
        assert key in content, f"缺冻结键 {key}"
    assert isinstance(content["node_ids"], list)
    assert isinstance(content["scene_ids"], list)
    assert isinstance(content["reachable"], dict)
    assert isinstance(content["known_topics"], dict)
    assert isinstance(content["menu"], dict)
    assert isinstance(content["open_conditions"], dict)
    assert isinstance(content["openable"], list)
    assert isinstance(content["var_names"], list)
    # 附加键（engine 不读，供 prompt/UI）
    assert isinstance(content["worldbook"], dict)
    assert isinstance(content["chapters"], list)
    assert isinstance(content["quick_actions"], list)
    # 别名键不得出现（避免与 check_i2 的 nodes/scenes 别名混淆）
    assert "nodes" not in content and "scenes" not in content


def test_load_content_derives_ids_and_scene_maps():
    """核心 id 推导的**增长容错契约守卫**（V22-10 内容扩充后语义收窄）。

    本用例原是「整份内容包的**完整快照**」（精确相等）。V22-10 把内容包从「最小可玩版」
    扩充为「≥3 章」后，新增 node / topic / openable **必然**令精确相等失效 —— 那是
    **假失败（内容基线快照 ≠ 契约回归）**，不是真回归。故语义收敛为：

        「这些**核心 id 必须存在**，且推导链（node_ids / scene_ids / 各 scene 动作面
         / 扁平 open_conditions）**仍然正确**」；

    新增内容**只要不破坏这些核心 id 的推导语义**即可自由增长（超集）。
    """
    content = wb.load_content("lantern")
    # node_ids 由 chapters[].nodes[].id 推导（核心 id 必须存在；允许内容增长 → 超集）
    assert {"opening", "counter_photo", "long_night"} <= set(content["node_ids"])
    # scene_ids 由 reachable/known_topics/menu 键推导，且**过滤空串**
    assert "counter" in content["scene_ids"] and "backdoor" in content["scene_ids"]
    assert "" not in content["scene_ids"]
    # 按 scene 分组的动作面：结构是 dict[scene] -> list
    assert content["reachable"][""] == ["counter"]   # 开局仍只通向吧台（V22-10 设计保持）
    assert "counter" in content["reachable"]["counter"]
    assert "long_night" in content["menu"][""]
    # 核心话题必须仍在（允许新增话题 → 超集）
    assert {"photo", "name"} <= set(content["known_topics"]["counter"])
    # 扁平 open_conditions（"<scene>:<key>" 与 "<key>" 混用）
    assert content["open_conditions"].get("backdoor") is True
    assert content["open_conditions"].get("counter:drawer") is True
    # 核心可开启物必须在（允许新增 → 子集判定）
    assert "drawer" in content["openable"]


def test_load_content_var_names_are_append_only():
    from gui.tavern.model import DEFAULT_VAR_NAMES, MAX_VARS

    content = wb.load_content("lantern")
    extra = set(content["var_names"])
    assert extra, "内容包应至少追加声明 1 个 var 名（示范 var_names 通道）"
    # 只追加：不得把基底 7 名写进 var_names（写了也不被反对，但契约是"只列新增"）
    assert not (extra & set(DEFAULT_VAR_NAMES))
    # 基底 7 名 ∪ 追加声明 ≤ MAX_VARS
    assert len(set(DEFAULT_VAR_NAMES) | extra) <= MAX_VARS


def test_content_declarations_satisfy_referenced_choices():
    """对齐守卫：内容包里每条 choice 引用的 target/topic/item/key 都必须**在 content 里被声明**。

    否则按 §4.2「缺省即安全」会被 engine 判 `precondition_failed:*`（fail-closed）。
    """
    content = wb.load_content("lantern")
    all_targets = {x for v in content["reachable"].values() for x in v}
    all_topics = {x for v in content["known_topics"].values() for x in v}
    all_items = {x for v in content["menu"].values() for x in v}
    known_locations = set(content["scene_ids"]) | {""}
    # ★ 合法写入面 = 三个推进字段（``CONTENT_EFFECT_FIELDS``）+ **基底 7 名 ∪ 内容包声明名**
    #   （口径 = ``engine.is_known_var``：基底 ``DEFAULT_VAR_NAMES`` 无需在 ``var_names`` 重复声明）。
    allowed_effect_fields = (
        set(wb.CONTENT_EFFECT_FIELDS) | set(DEFAULT_VAR_NAMES) | set(content["var_names"])
    )

    for chapter in content["chapters"]:
        for node in chapter.get("nodes", []):
            for choice in node.get("choices", []):
                transform = choice.get("transform")
                args = choice.get("args") or {}
                if transform == "move_to":
                    assert args["target"] in all_targets
                    assert args["target"] in known_locations
                elif transform == "ask_about":
                    assert args["topic"] in all_topics
                elif transform == "order":
                    assert args["item"] in all_items
                elif transform == "open":
                    key = args.get("key") or args.get("target")
                    assert key in content["open_conditions"] or key in content["openable"]
                # effects（若有）只能写「三个推进字段 ∪ 声明过的 var 名」
                for effect in args.get("effects") or []:
                    assert effect.get("field") in allowed_effect_fields


def test_load_content_missing_pack_controlled():
    content = wb.load_content("no_such_pack")
    # 非 strict：返回完整空壳（缺省即安全）
    assert content["node_ids"] == []
    assert content["reachable"] == {}
    assert set(_FROZEN_CONTENT_KEYS) <= set(content)
    # strict：受控抛 TavernContentError（携带 source）
    with pytest.raises(TavernContentError) as excinfo:
        wb.load_content("no_such_pack", strict=True)
    assert "no_such_pack" in excinfo.value.source


def test_load_content_bad_file_degrades_not_crash(tmp_path):
    pack = tmp_path / "broken"
    pack.mkdir()
    (pack / "book.json").write_text("{ 坏 JSON ", encoding="utf-8")
    (pack / "chapters.json").write_text("[]", encoding="utf-8")  # 非 dict → 视作空
    (pack / "transforms.json").write_text('{"var_names": ["v"]}', encoding="utf-8")
    content = wb.load_content("broken")
    # 注意：load_content 走 content_dir()，此处改用内部合并路径验证降级
    from gui.tavern import worldbook as _wb

    content = _wb._merge_content("broken", _wb._read_json(pack / "book.json"),
                                 _wb._read_json(pack / "chapters.json"),
                                 _wb._read_json(pack / "transforms.json"))
    assert content["node_ids"] == []          # chapters 非 dict → 空
    assert content["var_names"] == ["v"]      # transforms 正常
    assert content["worldbook"] == {}         # 坏 JSON → 空 dict，不崩


def test_load_content_labels_channel_is_additive():
    """可选附加键 ``labels``（机器名 → 中文名）经解析器透传；engine 不读、缺省为空 dict。"""
    content = wb._merge_content(
        "p", {},
        {"labels": {"counter": "吧台", "long_night": "长夜酒", "bad": 1, "": "空"}},
        {},
    )
    assert content["labels"] == {"counter": "吧台", "long_night": "长夜酒"}
    assert wb._merge_content("p", {}, {}, {})["labels"] == {}
    assert wb._empty_content("p")["labels"] == {}


# ===========================================================================
# 7. 零 Qt（源码 AST + 命名空间）
# ===========================================================================

def test_worldbook_source_has_no_qt_imports():
    src = pathlib.Path(wb.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("PySide6"), alias.name
                assert alias.name.split(".")[0] not in {"PyQt5", "PyQt6", "PySide2"}
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert not module.startswith("PySide6")
            assert module.split(".")[0] not in {"PyQt5", "PyQt6", "PySide2"}


def test_worldbook_namespace_has_no_qt_symbols():
    leaked = [n for n in dir(wb) if n.startswith("Q") and n[1:2].isupper()]
    assert leaked == [], f"worldbook 命名空间疑似泄漏 Qt 符号: {leaked}"


def test_public_api_all_names_exist():
    for name in wb.__all__:
        assert hasattr(wb, name), f"__all__ 声明的 {name} 不存在"


# ===========================================================================
# 8. probability / sticky / cooldown：**必须显式注入才生效**（否则与旧行为逐字节一致）
# ===========================================================================

class _FixedRng:
    """固定返回值的假随机源（实现 ``randint``，供 ``probability`` 判定）。"""

    def __init__(self, value: int) -> None:
        self.value = value

    def randint(self, a: int, b: int) -> int:
        return self.value


def _lore_book(entries: list, **over) -> "wb.WorldBook":
    """大预算 / 无递归的测试书（只关心触发判定，不关心裁剪）。"""
    knobs = dict(budget_chars=10_000, scan_depth=4, max_entries=10, recursive_max_depth=0)
    knobs.update(over)
    return wb.WorldBook(entries, **knobs)


def _uids(selection) -> list:
    return [e["uid"] for e in selection.entries]


def test_probability_inert_without_rng_and_consumed_with_it():
    """``probability`` 只在注入 ``rng`` 时参与判定（``rng=None`` → 恒真）。"""
    entry = mk(uid=11, content="吧台后的旧照片", keys=["照片"], probability=50)
    book = _lore_book([entry])

    # 不注入 rng → 概率不参与（确定性，与旧行为一致）
    assert _uids(book.collect(["我看看这张照片"])) == [11]
    # 注入 rng 后**真的**参与：抽到 1 ≤ 50 → 命中；抽到 100 > 50 → 不命中
    assert _uids(book.collect(["我看看这张照片"], rng=_FixedRng(1))) == [11]
    assert _uids(book.collect(["我看看这张照片"], rng=_FixedRng(100))) == []


def test_probability_zero_is_never_activated_even_with_rng():
    """``probability=0`` 是显式「永不触发」，不因 rng 缺失而被放行。"""
    entry = mk(uid=12, content="她不会提的事", keys=["提"], probability=0)
    book = _lore_book([entry])
    assert _uids(book.collect(["你提一句试试"])) == []
    assert _uids(book.collect(["你提一句试试"], rng=_FixedRng(1))) == []


def test_cooldown_suppresses_reactivation_for_n_turns():
    """``cooldown=2``：激活后再过两拍才允许重新激活（此前该字段从未被读取）。"""
    entry = mk(uid=13, content="长夜酒的滋味", keys=["长夜"], cooldown=2)
    book = _lore_book([entry])
    ledger: dict = {}
    texts = ["来一杯长夜酒"]

    assert _uids(book.collect(texts, turn=1, ledger=ledger)) == [13]   # 首次激活
    assert ledger == {13: 1}                                          # 记账（uid → 拍）
    assert _uids(book.collect(texts, turn=2, ledger=ledger)) == []    # 差 1 ≤ 2 → 抑制
    assert _uids(book.collect(texts, turn=3, ledger=ledger)) == []    # 差 2 ≤ 2 → 抑制
    assert _uids(book.collect(texts, turn=4, ledger=ledger)) == [13]  # 差 3 > 2 → 恢复
    assert ledger == {13: 4}                                          # 恢复后重新记账


def test_sticky_keeps_entry_active_without_keyword_and_does_not_self_renew():
    """``sticky=2``：激活后两拍内**不要求关键词命中**仍然在场；且不自我续期。"""
    entry = mk(uid=14, content="吧台后的旧照片", keys=["照片"], sticky=2)
    book = _lore_book([entry])
    ledger: dict = {}
    quiet = ["什么都没说，只是站着"]

    assert _uids(book.collect(["我看看这张照片"], turn=1, ledger=ledger)) == [14]
    assert ledger == {14: 1}
    # 关键词不再出现，但仍被粘滞保活（差 1 ≤ 2）
    assert _uids(book.collect(quiet, turn=2, ledger=ledger)) == [14]
    # 关键：保活**不算新激活** → 账本不刷新（否则条目会永续）
    assert ledger == {14: 1}
    assert _uids(book.collect(quiet, turn=3, ledger=ledger)) == [14]   # 差 2 ≤ 2
    assert _uids(book.collect(quiet, turn=4, ledger=ledger)) == []     # 差 3 > 2 → 脱落


def test_sticky_and_cooldown_inert_without_turn_or_ledger():
    """不传 ``turn`` / ``ledger``（旧调用形态）→ 两机制不参与，行为与改动前一致。"""
    entry = mk(uid=15, content="长夜酒的滋味", keys=["长夜"], sticky=2, cooldown=2)
    book = _lore_book([entry])
    texts = ["来一杯长夜酒"]

    for _ in range(3):                       # 旧形态：每拍都命中
        assert _uids(book.collect(texts)) == [15]
    assert _uids(book.collect(texts, turn=9)) == [15]   # 只给 turn、无账本 → 同样不参与


def test_cooldown_applies_on_recursive_path():
    """递归路径也必须吃 ``cooldown``（否则被冷却的条目会从递归绕回来）。"""
    root = mk(uid=20, content="灯笼的灯芯", keys=["灯笼"], recursive=True)
    child = mk(uid=21, content="灯芯的来历", keys=["灯芯"], cooldown=2)
    book = _lore_book([root, child], recursive_max_depth=2)
    ledger: dict = {}

    assert 21 in _uids(book.collect(["灯笼"], turn=1, ledger=ledger))     # 递归首次激活
    assert ledger.get(21) == 1
    assert 21 not in _uids(book.collect(["灯笼"], turn=2, ledger=ledger))  # 递归路径被冷却抑制


def test_constant_entries_are_never_cooldown_suppressed_or_recorded():
    """``constant`` 条目恒入：不受 cooldown 影响，也不写账本（它没有「激活」一说）。"""
    const = mk(uid=30, content="夜的规矩", constant=True, cooldown=3)
    book = _lore_book([const])
    ledger: dict = {}
    for turn in (1, 2, 3):
        assert _uids(book.collect([], turn=turn, ledger=ledger)) == [30]
    assert ledger == {}
