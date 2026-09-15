"""tests/test_v22_content_quality.py —— V22-10 内容包质量验收（可执行口径）。

把 design-v22 §3.2 + §7 的 **V22-10** 验收口径从「人眼检查」变成可执行断言：

    * 章节数 ≥ 3；每章 storylet 数 ∈ [4, 6]；storylet 总数 ≥ 12；
    * 存在 ≥ 2 个 ``choices == []`` 的**终局节点**（``ending_*``）——
      V22-10「2 结局」的**内容层**落地：当前 engine 无 ``status = "ended"`` 的写入通路，
      故结局以「终局节点」表达（见批 4 回传「设计-实现缺口」）；
    * ``constant`` 条目数 ≤ :data:`gui.tavern.model.CONSTANT_ENTRY_LIMIT`；
    * 每条世界书 ``content`` ≤ :data:`gui.tavern.model.LORE_MAX_CONTENT_CHARS`；
      ``enabled`` 的非 ``constant`` 条目 ``keys`` 非空；
    * 四种 ``selective_logic`` 各至少出现一次；
    * ``cast`` 恰好 3 条，``role`` 与 ``card_snapshot.name`` 均非空、``description`` ≤ 120 字；
    * **R-A 词表扫描**零命中（性能/准确率/落后/开销/进度/胜率/成功率/评分/排行/等级 + ``第\\d+``）；
    * ``quick_actions[].icon`` 全部已在 ``icons_manifest.json`` 登记；
    * 结构断言一律走**真实解析入口** :func:`gui.tavern.worldbook.load_content`。

批次 C 追加（§8–§11）：``choice_id`` 全局唯一（含与 quick_action id 不冲突）、
两个结局可达且由「读过信 / 没读信」互斥区分、``photo_seen`` / ``knows_name`` /
``scene_items→take→give`` 三条链各有消费者、``labels`` 覆盖全部被 prompt 使用的机器名、
``probability`` / ``cooldown`` 有非默认值、面向玩家的文案零阿拉伯数字、
每个非终局节点有 ``move_to`` 出口、选项级 ``prerequisites`` 真的存在、
回声节点 ≥2、存在「同结果不同语气」的角色扮演选项。

零 Qt（只 import ``gui.tavern.worldbook`` / ``gui.tavern.model``；不建 ``QApplication``）；
唯一例外是 :func:`test_choice_level_prerequisites_exist_and_use_approved_operators` 内**惰性**
import ``gui.tavern.service.PREREQ_OPERATORS``（算子名单的单一来源），模块级导入链保持零 Qt。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterator, List

from gui.tavern import worldbook as wb
from gui.tavern.model import (
    CONSTANT_ENTRY_LIMIT,
    DEFAULT_VAR_NAMES,
    LORE_MAX_CONTENT_CHARS,
    SELECTIVE_LOGIC_MODES,
)

#: 随包图标清单（判 ``quick_actions[].icon`` 是否登记）。
_ICONS_MANIFEST = (
    Path(__file__).resolve().parent.parent / "gui" / "assets" / "icons" / "icons_manifest.json"
)

#: 设计文档（C-0① 的文档漂移守卫用）。
_DESIGN_DOC = Path(__file__).resolve().parent.parent / "docs" / "design-v22.md"

#: 引入 ``prerequisites`` 算子时（批次 B）内容包的**历史规模**（节点数, 选项数）。
#: 该数由批次 B 实测得出（45），而设计文档当时写的是 **51** —— 本批把文档改对，
#: 并在此把「文档声称的历史规模」钉成可断言常量，防止再写错。
_OPERATOR_BATCH_PACK_SNAPSHOT = (16, 45)

#: 每章 storylet 数区间（V22-10）。
_MIN_STORYLETS_PER_CHAPTER = 4
_MAX_STORYLETS_PER_CHAPTER = 6

#: 全包 storylet 总数下限（V22-10）。
_MIN_TOTAL_STORYLETS = 12

#: 每个非终局 storylet 的选项数区间（V22-10「高影响选择」）。
_MIN_CHOICES = 3
_MAX_CHOICES = 5

#: cast 条数（老板娘 + 2 客人）。
_EXPECTED_CAST = 3

#: ``card_snapshot.description`` 上限（对齐 ``page_tavern._cast_member_view`` 的 120 字裁剪）。
_CAST_LINE_MAX = 120

#: R-A 词表（V22-10「全包零 R-A 词」）—— 任一命中即失败。
_RA_WORDS = ("性能", "准确率", "落后", "开销", "进度", "胜率", "成功率", "评分", "排行", "等级")

#: R-A 序号形态（第 N …）—— 章 / 节点标题一律不得带序号。
_RA_ORDINAL = re.compile(r"第\d+")

#: R-A 数字形态（阿拉伯数字）—— **面向玩家的文案**里一律不得出现。
_RA_DIGIT = re.compile(r"\d")

#: 隐含触碰 ``vars`` 的变换（其 ``post`` 写基底 var：poured/opened/known/held_items/given）。
_VAR_TOUCHING_TRANSFORMS = frozenset({"order", "open", "ask_about", "take", "give"})

#: 列表型基底 var（由 ``open`` / ``ask_about`` / ``take`` / ``give`` 的 ``post`` 自动 append）。
_LIST_VARS = ("opened", "known", "scene_items", "held_items", "given")


def _content() -> dict:
    """真实解析入口（**不另写解析器**）。"""
    return wb.load_content("lantern")


def _nodes(content: dict) -> List[dict]:
    """所有章节的所有节点（顺序 = 声明顺序）。"""
    out: List[dict] = []
    for chapter in content["chapters"]:
        out.extend(n for n in chapter.get("nodes", []) if isinstance(n, dict))
    return out


def _entries(content: dict) -> List[dict]:
    """``book.json`` 的原始条目列表（``content["worldbook"]["entries"]``）。"""
    worldbook = content.get("worldbook")
    entries = worldbook.get("entries") if isinstance(worldbook, dict) else None
    return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []


def _iter_strings(obj: Any) -> Iterator[str]:
    """递归产出对象内**全部字符串**（含 dict 键），供 R-A 扫描。"""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for key, value in obj.items():
            yield from _iter_strings(key)
            yield from _iter_strings(value)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _iter_strings(item)


def _touches_vars(choice: dict, var_set: set) -> bool:
    """一条 choice 是否「走 vars」（变换隐含写 var，或 ``effects`` 显式写 var）。"""
    if choice.get("transform") in _VAR_TOUCHING_TRANSFORMS:
        return True
    args = choice.get("args") or {}
    for effect in args.get("effects") or []:
        if isinstance(effect, dict) and effect.get("field") in var_set:
            return True
    return False


def _choices(content: dict) -> List[dict]:
    """全包所有选项（顺序 = 声明顺序）。"""
    out: List[dict] = []
    for node in _nodes(content):
        out.extend(c for c in (node.get("choices") or []) if isinstance(c, dict))
    return out


def _effect_writes(content: dict) -> List[dict]:
    """全包所有 ``choice.args.effects`` 条目（顺序 = 声明顺序）。"""
    out: List[dict] = []
    for choice in _choices(content):
        args = choice.get("args") or {}
        out.extend(e for e in (args.get("effects") or []) if isinstance(e, dict))
    return out


def _player_texts(content: dict) -> Iterator[str]:
    """**面向玩家**的全部文案（R-A 扫描面）。

    只取会上屏 / 会进提示词的字段：章标题、节点 ``title``/``text``/``llm_brief``、
    选项 ``label``、快捷动作 ``label``、世界书条目 ``title``/``content``、
    人物卡 ``role``/``name``/``description``、``labels`` 的中文名、书标题。
    **不**含机器名（``id`` / ``chapter_id`` 形如 ``ch1`` 自带数字，不在扫描面）。
    """
    for chapter in content.get("chapters") or []:
        if not isinstance(chapter, dict):
            continue
        yield from _strings_of(chapter.get("title"))
        for node in chapter.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            for key in ("title", "text", "llm_brief"):
                yield from _strings_of(node.get(key))
            for choice in node.get("choices") or []:
                if isinstance(choice, dict):
                    yield from _strings_of(choice.get("label"))
    for action in content.get("quick_actions") or []:
        if isinstance(action, dict):
            yield from _strings_of(action.get("label"))
    for label in (content.get("labels") or {}).values():
        yield from _strings_of(label)
    worldbook = content.get("worldbook")
    if isinstance(worldbook, dict):
        yield from _strings_of(worldbook.get("title"))
        for entry in worldbook.get("entries") or []:
            if isinstance(entry, dict):
                yield from _strings_of(entry.get("title"))
                yield from _strings_of(entry.get("content"))
        for member in worldbook.get("cast") or []:
            if not isinstance(member, dict):
                continue
            yield from _strings_of(member.get("role"))
            snapshot = member.get("card_snapshot")
            if isinstance(snapshot, dict):
                yield from _strings_of(snapshot.get("name"))
                yield from _strings_of(snapshot.get("description"))


def _strings_of(value: Any) -> Iterator[str]:
    """单个字段的字符串产出（非 str → 无）。"""
    if isinstance(value, str):
        yield value


def _machine_names_used_by_prompt(content: dict) -> set:
    """会被 :mod:`gui.tavern.prompt` 翻成中文的**全部机器名**。

    面 = 地点（``scene_ids``）+ 酒（``menu`` 值）+ 话题（``known_topics`` 值）+
    可开物（``openable`` + ``open_conditions`` 的复合键尾段）+ 内容包显式写进
    列表型 var 的值（``effects`` 的 ``value``）。
    """
    used: set = set(content.get("scene_ids") or [])
    for mapping_key in ("menu", "known_topics"):
        for values in (content.get(mapping_key) or {}).values():
            used |= {v for v in values if isinstance(v, str) and v}
    used |= {v for v in (content.get("openable") or []) if isinstance(v, str) and v}
    for compound in (content.get("open_conditions") or {}):
        if isinstance(compound, str) and compound:
            used.add(compound.split(":", 1)[-1])
    for effect in _effect_writes(content):
        if effect.get("field") in _LIST_VARS:
            value = effect.get("value")
            if isinstance(value, str) and value:
                used.add(value)
    return used


def _prereq_keys(prerequisites: Any) -> set:
    """``prerequisites`` 里出现的键名集合（非 dict → 空集）。"""
    if not isinstance(prerequisites, dict):
        return set()
    return {k for k in prerequisites if isinstance(k, str)}


# ===========================================================================
# 1. 解析入口与冻结键
# ===========================================================================

def test_pack_parses_through_real_entry_and_core_faces_nonempty():
    content = _content()
    assert content["book_id"] == "lantern"
    assert content["chapters"], "chapters 不得为空"
    assert content["menu"], "menu 不得为空"
    assert content["reachable"], "reachable 不得为空"
    assert content["quick_actions"], "quick_actions 不得为空"
    assert content["node_ids"], "node_ids 不得为空"


def test_var_names_frozen_to_photo_seen():
    # V22-10：var 名额已用满（基底 7 + 1），本批**不得**新增 var 名。
    assert _content()["var_names"] == ["photo_seen"]


# ===========================================================================
# 2. 章节 / storylet / 结局（V22-10 结构口径）
# ===========================================================================

def test_chapter_count_at_least_three():
    assert len(_content()["chapters"]) >= 3


def test_each_chapter_has_four_to_six_storylets():
    for chapter in _content()["chapters"]:
        count = len(chapter.get("nodes", []))
        assert _MIN_STORYLETS_PER_CHAPTER <= count <= _MAX_STORYLETS_PER_CHAPTER, (
            f"章 {chapter.get('chapter_id')!r} 有 {count} 个 storylet，越界"
        )


def test_total_storylet_count_at_least_twelve():
    assert len(_nodes(_content())) >= _MIN_TOTAL_STORYLETS


def test_two_or_more_terminal_ending_nodes():
    endings = [n for n in _nodes(_content()) if n.get("choices") == []]
    assert len(endings) >= 2, f"终局节点不足 2 个：{[n.get('id') for n in endings]}"
    for node in endings:
        assert str(node.get("id", "")).startswith("ending_"), (
            f"终局节点 id 应以 ending_ 开头（可辨识）：{node.get('id')!r}"
        )


def test_non_terminal_nodes_have_three_to_five_choices():
    for node in _nodes(_content()):
        choices = node.get("choices")
        assert isinstance(choices, list), f"节点 {node.get('id')!r} 缺 choices 列表"
        if not choices:                      # 终局节点
            continue
        assert _MIN_CHOICES <= len(choices) <= _MAX_CHOICES, (
            f"节点 {node.get('id')!r} 有 {len(choices)} 个选项，越界"
        )


# ===========================================================================
# 3. 高影响选择（V22-10「每章 3–5 个走 vars」）
# ===========================================================================

def test_each_chapter_has_at_least_three_var_touching_choices():
    content = _content()
    var_set = set(DEFAULT_VAR_NAMES) | set(content["var_names"])
    for chapter in content["chapters"]:
        hits = 0
        for node in chapter.get("nodes", []):
            for choice in node.get("choices", []):
                if _touches_vars(choice, var_set):
                    hits += 1
        assert hits >= 3, f"章 {chapter.get('chapter_id')!r} 只有 {hits} 个走 vars 的选择"


# ===========================================================================
# 4. 世界书（constant / 单条上限 / keys / 四种 selective logic）
# ===========================================================================

def test_constant_entries_within_limit():
    enabled_constants = [
        e for e in _entries(_content()) if e.get("constant") and e.get("enabled", True)
    ]
    assert len(enabled_constants) <= CONSTANT_ENTRY_LIMIT


def test_worldbook_entries_respect_content_and_keys_rules():
    entries = _entries(_content())
    assert entries, "世界书条目不得为空"
    for entry in entries:
        assert len(entry.get("content", "")) <= LORE_MAX_CONTENT_CHARS, (
            f"uid={entry.get('uid')} content 超 {LORE_MAX_CONTENT_CHARS} 字"
        )
        if entry.get("enabled", True) and not entry.get("constant"):
            assert entry.get("keys"), f"uid={entry.get('uid')} 非 constant 条目缺 keys"


def test_all_four_selective_logic_modes_present():
    logics = {e.get("selective_logic") for e in _entries(_content())}
    assert set(SELECTIVE_LOGIC_MODES) <= logics, f"缺档位：{set(SELECTIVE_LOGIC_MODES) - logics}"


# ===========================================================================
# 5. 人物卡（cast）—— 点亮「人物」Tab
# ===========================================================================

def test_cast_has_exactly_three_named_members():
    content = _content()
    worldbook = content.get("worldbook")
    cast = worldbook.get("cast") if isinstance(worldbook, dict) else None
    assert isinstance(cast, list), "book.json 顶层应含 cast 数组"
    assert len(cast) == _EXPECTED_CAST, f"cast 应为 {_EXPECTED_CAST} 条，实为 {len(cast)}"
    for member in cast:
        assert member.get("role"), f"cast 成员缺 role：{member!r}"
        snapshot = member.get("card_snapshot")
        assert isinstance(snapshot, dict), f"cast 成员缺 card_snapshot：{member!r}"
        assert snapshot.get("name"), f"cast 成员缺真名：{member!r}"
        assert len(snapshot.get("description", "")) <= _CAST_LINE_MAX, (
            f"cast {snapshot.get('name')!r} description 超 {_CAST_LINE_MAX} 字"
        )


# ===========================================================================
# 6. R-A 红线（零命中）
# ===========================================================================

def test_zero_ra_words_in_pack():
    hits: List[str] = []
    for text in _iter_strings(_content()):
        for word in _RA_WORDS:
            if word in text:
                hits.append(f"{word} → {text!r}")
        if _RA_ORDINAL.search(text):
            hits.append(f"第N序号 → {text!r}")
    assert hits == [], f"R-A 词表命中 {len(hits)} 处：{hits}"


def test_player_facing_text_has_no_arabic_digits():
    """★ 本批新增：**面向玩家的文案零数字**（R-A）。

    比 :func:`test_zero_ra_words_in_pack` 更严：那条只查 ``第\\d+`` 序号形态，
    这条把**阿拉伯数字本身**也一并禁掉 —— 酒馆的文案里不该出现任何计数 / 刻度 / 进度数字。
    扫描面**只含会上屏 / 会进提示词的字段**（见 :func:`_player_texts`），
    **不含** ``id`` / ``chapter_id``（``ch1`` 这类机器名自带数字，不是文案）。
    """
    hits = [t for t in _player_texts(_content()) if _RA_DIGIT.search(t)]
    assert hits == [], f"面向玩家的文案出现数字 {len(hits)} 处：{hits}"


# ===========================================================================
# 7. 快捷动作图标（必须已登记）
# ===========================================================================

def test_quick_action_icons_are_registered():
    manifest = json.loads(_ICONS_MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(manifest, dict) and manifest, "图标清单读取为空"
    for action in _content()["quick_actions"]:
        assert action.get("icon") in manifest, (
            f"快捷动作 {action.get('action_id')!r} 的 icon {action.get('icon')!r} 未登记"
        )


# ===========================================================================
# 8. 批次 C：choice_id 全局唯一（含与 quick_action id 不冲突）
# ===========================================================================

def test_choice_ids_are_globally_unique_and_do_not_collide_with_quick_actions():
    """★ 本批新增（缺陷 F）：45 选项只有 34 唯一 id（``ask_guest``×3 等）。

    为什么必须唯一：``service._content_choice_label`` 的**跨节点反查**按 ``choice_id``
    取第一条命中的中文 label —— 重名会让玩家看到**别的节点**的文案（自己没点过的那句）。
    另：``choices[].choice_id`` 与 ``quick_actions[].action_id`` 同属 router 的
    ``resolve_choice`` 查表键，**重名会让两处文案互相串**。
    """
    content = _content()
    choice_ids = [c.get("choice_id") for c in _choices(content)]
    assert choice_ids, "内容包没有任何选项"

    seen: dict = {}
    dups: List[str] = []
    for cid in choice_ids:
        assert isinstance(cid, str) and cid, f"选项缺 choice_id：{cid!r}"
        if cid in seen:
            dups.append(cid)
        seen[cid] = True
    assert dups == [], f"choice_id 重名 {len(dups)} 处：{sorted(set(dups))}"

    action_ids = [a.get("action_id") for a in content["quick_actions"]]
    collide = sorted(set(action_ids) & set(choice_ids))
    assert collide == [], f"choice_id 与 quick_action id 重名：{collide}"


# ===========================================================================
# 9. 批次 C：两个结局都可达（且由「读过信 / 没读信」区分）
# ===========================================================================

def test_both_endings_are_reachable_and_distinguished_by_letter_state():
    """★ 本批新增（缺陷 A）：``ending_guest_leaves`` 与 ``ending_dawn`` 原本**同前置**
    ``{"scene_id": "backdoor"}``，而 ``_advance_node`` 按**声明顺序**取第一个匹配 →
    先声明的那一个永远赢，另一个**不可达**。

    本用例在**内容层**锁死修复形态（真「两条路走通」的端到端断言见
    ``tests/test_v22_play_e2e.py::test_two_endings_reachable_through_letter_state``）：

    * 两个结局都必须以 ``backdoor`` 为地点前置；
    * 二者对 ``opened`` 的条件必须**互斥且穷尽** ——
      一个 ``{"has": "letter"}``、另一个 ``{"has_not": "letter"}``
      ⇒ 任何 ``opened`` 状态下**恰有一个**匹配 ⇒ 两个结局都能被走到。
    """
    content = _content()
    endings = [n for n in _nodes(content) if n.get("choices") == []]
    assert len(endings) >= 2, f"终局节点不足 2 个：{[n.get('id') for n in endings]}"

    gates: dict = {}
    for node in endings:
        prereq = node.get("prerequisites")
        assert isinstance(prereq, dict), f"结局 {node.get('id')!r} 缺 prerequisites"
        assert prereq.get("scene_id") == "backdoor", (
            f"结局 {node.get('id')!r} 的地点前置不是 backdoor：{prereq.get('scene_id')!r}"
        )
        opened = prereq.get("opened")
        assert isinstance(opened, dict), f"结局 {node.get('id')!r} 缺 opened 条件：{prereq!r}"
        gates[node["id"]] = opened

    assert any(g == {"has": "letter"} for g in gates.values()), (
        f"没有任何结局要求「读过信」：{gates}"
    )
    assert any(g == {"has_not": "letter"} for g in gates.values()), (
        f"没有任何结局要求「没读信」：{gates}"
    )
    # 互斥且穷尽：恰有一条 has / has_not 对同一目标
    has_targets = {g["has"] for g in gates.values() if set(g) == {"has"}}
    has_not_targets = {g["has_not"] for g in gates.values() if set(g) == {"has_not"}}
    assert has_targets == has_not_targets, (
        f"结局的 has / has_not 目标不一致（不互斥）：{has_targets} vs {has_not_targets}"
    )


# ===========================================================================
# 10. 批次 C：三个「死变量 / 死机制」各有消费者
# ===========================================================================

def test_photo_seen_is_consumed_not_dead():
    """★ 本批新增（缺陷 C）：``photo_seen`` 原本只被写、**0 个前置消费** → 死变量。"""
    content = _content()
    consumers: List[str] = []
    for node in _nodes(content):
        if "photo_seen" in _prereq_keys(node.get("prerequisites")):
            consumers.append(f"node:{node.get('id')}")
        for choice in node.get("choices") or []:
            if isinstance(choice, dict) and "photo_seen" in _prereq_keys(choice.get("prerequisites")):
                consumers.append(f"choice:{choice.get('choice_id')}")
    assert consumers, "photo_seen 没有任何消费方（仍是死变量）"
    # 并且它必须仍被写（否则消费方永不可满足）
    writers = [
        e for e in _effect_writes(content)
        if e.get("field") == "photo_seen" and e.get("value") is True
    ]
    assert writers, "photo_seen 没有任何写入点"


def test_knows_name_has_both_writer_and_consumer():
    """★ 本批新增（缺陷 E）：``knows_name`` 在白名单里、``prompt.py`` 会读，但**无人写**。"""
    content = _content()
    writers = [e for e in _effect_writes(content) if e.get("field") == "knows_name"]
    assert writers, "knows_name 没有写入点（prompt 里那句「你已经知道她的名字」永不可达）"
    assert any(e.get("value") is True for e in writers), "knows_name 的写入点没有真的置真"

    consumers: List[str] = []
    for node in _nodes(content):
        if "knows_name" in _prereq_keys(node.get("prerequisites")):
            consumers.append(f"node:{node.get('id')}")
        for choice in node.get("choices") or []:
            if isinstance(choice, dict) and "knows_name" in _prereq_keys(choice.get("prerequisites")):
                consumers.append(f"choice:{choice.get('choice_id')}")
    assert consumers, "knows_name 没有消费方（写了也没人看）"


def test_item_chain_scene_items_take_give_is_complete():
    """★ 本批新增（缺陷 D）：``take`` / ``give`` 从未被使用 → 物品系统整条死。

    完整链 = ① ``effects`` 写 ``scene_items``（否则 ``take`` 的前置 ``item_not_in_scene``
    恒不通过）→ ② ``take`` 把该 item 从 ``scene_items`` 挪进 ``held_items`` →
    ③ ``give`` 把该 item 从 ``held_items`` 挪进 ``given``。缺任何一环 = 半条死链。
    """
    content = _content()
    scene_writes = {
        e.get("value") for e in _effect_writes(content)
        if e.get("field") == "scene_items" and e.get("op") == "append"
        and isinstance(e.get("value"), str) and e.get("value")
    }
    assert scene_writes, "没有任何 effects 往 scene_items 里写东西 → take 永不可用"

    taken = set()
    for choice in _choices(content):
        if choice.get("transform") == "take":
            item = (choice.get("args") or {}).get("item")
            assert item in scene_writes, (
                f"take 选项 {choice.get('choice_id')!r} 拿的 {item!r} 从没被写进 scene_items"
            )
            taken.add(item)
    assert taken, "内容包没有任何 take 选项 → held_items 恒空"

    given = set()
    for choice in _choices(content):
        if choice.get("transform") == "give":
            item = (choice.get("args") or {}).get("item")
            assert item in taken, (
                f"give 选项 {choice.get('choice_id')!r} 交的 {item!r} 没有对应的 take 来源"
            )
            given.add(item)
    assert given, "内容包没有任何 give 选项 → given 恒空"


# ===========================================================================
# 11. 批次 C：labels 覆盖 / probability·cooldown 非默认 / 无死路 / 回声 / 角色扮演
# ===========================================================================

def test_labels_cover_every_machine_name_used_by_prompt():
    """★ 本批新增（缺陷 G）：内置包未声明 ``labels`` → 提示词里地点 / 酒 / 物品一律走
    中性兜底「这一处」，信息量比不修还低。

    本用例把「**会被 prompt 翻中文的机器名**」全部枚举出来，要求 ``labels`` 一个不漏。

    ★ 批次 D（E2）**订正理由表述**（原注释把因果说反了）：
        原注释称"漏一个就会在提示词里露出机器名"。**实测不是这样** ——
        :func:`gui.tavern.labels.labeled_values` 对查不到中文名的值**直接丢弃**，
        :func:`gui.tavern.labels.scene_label` 回落中性 :data:`UNKNOWN_SCENE`（「这一处」）。
        故漏 label 的**真实后果是「信息从提示词里消失」**（地点 / 酒 / 物品被并成
        「这一处」或干脆不出现），**不是**机器名泄漏（机器名泄漏由 ``labels.py``
        的"绝不回落机器名"纪律 + 机器名扫描用例单独守着）。
        所以补 label 仍然值得做 —— 但目的是**保住信息量**，不是"堵泄漏"。
    """
    content = _content()
    labels = content.get("labels")
    assert isinstance(labels, dict) and labels, "内容包没有声明 labels"
    used = _machine_names_used_by_prompt(content)
    missing = sorted(used - set(labels))
    assert missing == [], f"labels 漏了 {len(missing)} 个机器名：{missing}"
    for name in used:
        assert isinstance(labels[name], str) and labels[name].strip(), (
            f"labels[{name!r}] 不是非空中文名"
        )


def test_missing_label_drops_information_instead_of_leaking_machine_name():
    """★ 批次 D（E2）：把「漏 label 会**泄漏机器名**」这个**说反了**的理由钉成可执行断言。

    实测 :mod:`gui.tavern.labels` 的真实行为：

    * :func:`labeled_values` 只保留**能在 ``labels`` 表里查到中文名**的项，
      **查不到的直接丢弃**；一项都没命中 → 回落调用方给的中性 ``fallback``；
    * :func:`scene_label` 对「有 ``scene_id`` 但查不到中文名」回落中性
      :data:`UNKNOWN_SCENE`（「这一处」）—— **绝不回落机器名**。

    ⇒ 漏 label 的**真实后果是「信息从提示词里消失」**（那个地点 / 酒 / 物品不再被点名，
    或被并成「这一处」），**不是**机器名泄漏。故补 label 的价值在于**保住信息量**；
    「机器名不上屏 / 不进提示词」由 ``labels.py`` 的"绝不回落机器名"纪律单独保证。
    """
    from gui.tavern import labels as labels_mod

    content = {"labels": {"counter": "吧台"}}
    # ① 命中 → 中文名
    assert labels_mod.labeled_values(content, ["counter"], "这一处") == "吧台"
    # ② 部分命中 → 查不到的项被**丢弃**（信息消失），而不是留下机器名
    assert labels_mod.labeled_values(content, ["counter", "mystery_item"], "这一处") == "吧台"
    # ③ 一项都没命中 → 中性 fallback，且**不含**机器名
    only_unknown = labels_mod.labeled_values(content, ["mystery_item"], "这一处")
    assert only_unknown == "这一处"
    assert "mystery_item" not in only_unknown
    # ④ 有 scene_id 但无 label → 中性兜底，绝不回落机器名
    unknown_scene = labels_mod.scene_label(content, "mystery_scene")
    assert unknown_scene == labels_mod.UNKNOWN_SCENE
    assert "mystery_scene" not in unknown_scene


def test_probability_and_cooldown_have_non_default_values():
    """★ 本批新增（缺陷 B）：世界书 17 条全是 ``probability=100`` / ``cooldown=0`` →
    两个机制在真包上**永远等于默认值**，无法被观测（也就无法验证它们真的生效）。

    要求：至少 2 条 ``probability < 100``、至少 2 条 ``cooldown > 0``；
    且**不得**动 ``constant`` 条目（那是基础世界规则，不能变得不可靠）。
    """
    entries = _entries(_content())
    assert entries, "世界书条目不得为空"

    probabilistic = [e for e in entries if isinstance(e.get("probability"), int)
                     and not e.get("constant") and e["probability"] < 100]
    cooled = [e for e in entries if isinstance(e.get("cooldown"), int)
              and not e.get("constant") and e["cooldown"] > 0]
    assert len(probabilistic) >= 2, (
        f"probability < 100 的非 constant 条目不足 2 条：{[e.get('uid') for e in probabilistic]}"
    )
    assert len(cooled) >= 2, (
        f"cooldown > 0 的非 constant 条目不足 2 条：{[e.get('uid') for e in cooled]}"
    )
    for entry in entries:
        if entry.get("constant"):
            assert entry.get("probability", 100) == 100, (
                f"constant 条目 uid={entry.get('uid')} 的 probability 被调低了（基础规则不能不可靠）"
            )


def test_scene_graph_closes_on_backdoor_from_every_scene_including_start():
    """★ 批次 D（E1 校正）：**准确**口径 —— 从任一已声明地点（**含初始空场景 ``""``**）
    都能在有限步内走到 ``backdoor``；且每个非终局节点都至少有一条 ``move_to`` 出口。

    **旧口径错在哪**（本批订正）：旧用例把「``backdoor`` 从每个已声明地点可达」写成
    「**每个非终局节点**都有一条 ``move_to backdoor`` 出口」，且只遍历
    ``content["scene_ids"]`` —— 而 ``scene_ids`` **不含空串 ``""``**（§4.2 明确：
    空 ``scene_id`` 不参与 I2 校验，故不进 ``scene_ids``）⇒ **初始场景被悄悄豁免**。
    实测事实：``opening`` 节点**没有** ``move_to backdoor`` 直连出口（只有
    ``sit_down → counter``），``reachable[""]`` 也**不含** ``backdoor`` ——
    声明、实现、测试三者口径不一致（功能上两步必达，但声明**字面不成立**）。

    本用例改为按**场景图传递闭包**（BFS，不再只看一跳）判定，并把 ``""`` **显式纳入**：
    ``reachable`` 的**每一个**键（含 ``""``）都必须能在有限步内走到 ``backdoor``。
    端到端（真 service + 真内容包）的**完整状态可达性**证明见
    ``tests/test_v22_play_e2e.py::test_no_dead_end_from_any_reachable_state_including_empty_scene``。
    """
    content = _content()
    reachable = content["reachable"]
    assert isinstance(reachable, dict) and reachable, "reachable 不得为空"
    assert "" in reachable, (
        "初始 scene 为空串（``model.new_play``）—— ``reachable`` 必须显式声明它，不得豁免")
    assert "backdoor" in reachable, "内容包未声明 backdoor 地点"

    def _closure(start: str) -> set:
        """``start`` 在场景图上的可达闭包（含自身）。"""
        seen, queue = {start}, [start]
        while queue:
            scene = queue.pop()
            for nxt in reachable.get(scene) or []:
                if isinstance(nxt, str) and nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        return seen

    for scene in reachable:                 # ← 含 ""（旧口径的漏洞正在这里）
        assert "backdoor" in _closure(scene), (
            f"从地点 {scene!r} 出发走不到 backdoor（可达闭包={sorted(_closure(scene))}）")

    stuck: List[str] = []
    for node in _nodes(content):
        choices = node.get("choices")
        if not choices:                      # 终局节点本就该停
            continue
        moves = [c for c in choices if isinstance(c, dict) and c.get("transform") == "move_to"]
        if not moves:
            stuck.append(str(node.get("id")))
    assert stuck == [], f"这些节点没有任何「换个地方」的出口：{stuck}"


def test_choice_level_prerequisites_exist_and_use_approved_operators():
    """★ 本批新增（缺陷 B 后半）：选项级 ``prerequisites`` 原本 **0/45** →
    「选择有后果」在真包上不可见。

    （★ 批次 D（E3）订正：此处原写 **0/51** —— 那是设计文档早先写错的数字；
    批次 B 实测选项数为 **45**，见 :data:`_OPERATOR_BATCH_PACK_SNAPSHOT`。
    数字口径一律以实测快照为准。）

    要求：至少 3 条选项带前置；且用到的算子名 ∈ 已批准集合
    （单一来源 = ``gui.tavern.service.PREREQ_OPERATORS``）。
    """
    from gui.tavern.service import PREREQ_OPERATORS  # 惰性 import（本模块其余用例保持零 Qt）

    content = _content()
    gated: List[dict] = []
    for choice in _choices(content):
        prereq = choice.get("prerequisites")
        if not isinstance(prereq, dict) or not prereq:
            continue
        gated.append(choice)
        for key, want in prereq.items():
            assert isinstance(key, str) and key, f"选项 {choice.get('choice_id')!r} 前置键非法"
            if isinstance(want, dict):
                assert len(want) == 1, (
                    f"选项 {choice.get('choice_id')!r} 的前置 {key!r} 出现多个算子：{want!r}"
                )
                op = next(iter(want))
                assert op in PREREQ_OPERATORS, (
                    f"选项 {choice.get('choice_id')!r} 用了未批准算子 {op!r}"
                )
    assert len(gated) >= 3, f"带前置的选项只有 {len(gated)} 条，不足以让「选择有后果」可见"


def test_echo_nodes_echo_earlier_choices():
    """★ 本批新增：早期选择在后续文本被点名/改写（**后果回声**）。

    形态：至少 2 个回声节点，其前置引用**前文选项写下的状态**（而不是只按地点）。
    """
    content = _content()
    echoes = [n for n in _nodes(content) if str(n.get("id", "")).startswith("echo_")]
    assert len(echoes) >= 2, f"回声节点不足 2 个：{[n.get('id') for n in echoes]}"

    # 「前文写过的状态」= 变换 ``post`` 隐含维护的基底 var ∪ ``effects`` 显式写的 var
    written = set(_LIST_VARS) | {"poured"} | {
        e.get("field") for e in _effect_writes(content) if isinstance(e.get("field"), str)
    }
    for node in echoes:
        keys = _prereq_keys(node.get("prerequisites"))
        assert keys & written, (
            f"回声节点 {node.get('id')!r} 的前置没有引用任何「前文写过的状态」：{keys!r}"
        )


def test_roleplay_options_share_result_and_differ_only_in_tone():
    """★ 本批新增：治「点击翻页感」—— 同一结果、不同语气的选项（纯文案差异）。

    形态：同一节点内存在两条 **``transform`` + ``args`` + ``prerequisites`` 完全相同**、
    而 ``label`` **不同**的选项 —— 它们对世界的作用一模一样，差别只在客人怎么开口。

    ``prerequisites`` 必须一并相等：带不同前置的两条选项（如「问了才出现」的那条）
    是**状态门控**，不是语气变体，不能算数。
    """
    content = _content()
    hits: List[str] = []
    for node in _nodes(content):
        buckets: dict = {}
        for choice in node.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            key = (
                choice.get("transform"),
                json.dumps(choice.get("args") or {}, sort_keys=True),
                json.dumps(choice.get("prerequisites") or {}, sort_keys=True),
            )
            buckets.setdefault(key, []).append(choice)
        for group in buckets.values():
            if len(group) < 2:
                continue
            labels = {c.get("label") for c in group}
            if len(labels) >= 2:
                hits.append(f"{node.get('id')}: {sorted(labels)}")
    assert hits, "没有任何「同结果不同语气」的角色扮演式选项"



# ===========================================================================
# 12. C-0①：设计文档的「内容包规模」声称不得与实测漂移
# ===========================================================================

def test_design_doc_pack_size_claim_matches_measured_snapshot():
    """★ 批次 C（C-0①）：``docs/design-v22.md`` 曾把内容包写成「16 节点 + **51** 选项」，
    而批次 B 实测为 **45** —— 文档与实测不符（"写错一律不通过"的精神同样适用于文档）。

    本用例把文档里那句历史声称钉成可断言常量（:data:`_OPERATOR_BATCH_PACK_SNAPSHOT`），
    并顺带锁住**单调性**：历史规模必须 ≤ 现包规模（内容只增补，不缩水）。
    """
    text = _DESIGN_DOC.read_text(encoding="utf-8")
    match = re.search(r"内容包为\s*(\d+)\s*节点\s*\+\s*(\d+)\s*选项", text)
    assert match, "设计文档 §4.2 里「内容包为 N 节点 + M 选项」的表述被删/改写了"

    claimed = (int(match.group(1)), int(match.group(2)))
    assert claimed == _OPERATOR_BATCH_PACK_SNAPSHOT, (
        f"文档声称的历史规模 {claimed} 与实测快照 {_OPERATOR_BATCH_PACK_SNAPSHOT} 不符")

    content = _content()
    assert claimed[0] <= len(_nodes(content)), "文档声称的节点数超过现包节点数"
    assert claimed[1] <= len(_choices(content)), "文档声称的选项数超过现包选项数"
