# -*- coding: utf-8 -*-
"""gui/tavern/stat_block.py 单测（v2.2.5）。

覆盖：固定位置映射、万能键（赋值/增减）、背包分组、全角标点、保留键拒绝、
未知行原样保留、畸形输入不抛、渲染回放。
"""
from __future__ import annotations

import pytest

from gui.tavern.stat_block import (
    FIXED_FIELDS,
    RESERVED_KEYS,
    StatDelta,
    parse_stat_block,
    render_stat_block,
)

#: 取自"结构化自然语言"的原始示例（含全角括号与竖线）。
SAMPLE = """苏小染把酒杯推过来，指尖在杯沿停了一下。

【状态】苏小染|女|显|平静|好感度 1000/1000
【变化】
类型: 背包物品
长夜酒 +1
旧照片 -1
类型: 属性
photo_seen = true
"""


class TestFixedFields:
    def test_positions_map_to_semantics(self):
        d = parse_stat_block(SAMPLE)
        assert d.saw_state is True
        assert d.fixed["name"] == "苏小染"
        assert d.fixed["gender"] == "女"
        assert d.fixed["visibility"] == "显"
        assert d.fixed["mood"] == "平静"

    def test_affinity_splits_value_and_max(self):
        d = parse_stat_block(SAMPLE)
        assert d.fixed["affinity"] == {"value": 1000, "max": 1000}

    def test_affinity_without_max_is_tolerated(self):
        d = parse_stat_block("【状态】A|女|显|平静|好感度 42")
        assert d.fixed["affinity"] == {"value": 42, "max": None}

    def test_short_line_keeps_prefix_only(self):
        d = parse_stat_block("【状态】只|有|三个")
        assert d.fixed["name"] == "只"
        assert d.fixed["gender"] == "有"
        assert d.fixed["visibility"] == "三个"
        assert "mood" not in d.fixed

    def test_labelled_mood_is_stripped(self):
        d = parse_stat_block("【状态】A|女|显|心情: 雀跃|好感度 5/10")
        assert d.fixed["mood"] == "雀跃"

    def test_extra_columns_go_to_unknown(self):
        d = parse_stat_block("【状态】A|女|显|平静|好感度 1/2|额外字段")
        assert d.unknown == ["[state-extra] 额外字段"]


class TestUniversalKeys:
    def test_item_deltas_are_grouped(self):
        d = parse_stat_block(SAMPLE)
        assert d.items == {"长夜酒": 1.0, "旧照片": -1.0}
        assert d.deltas == {}

    def test_attr_set_coerces_bool(self):
        d = parse_stat_block(SAMPLE)
        assert d.sets == {"photo_seen": True}

    def test_numeric_set_coerces_int(self):
        d = parse_stat_block("【变化】\n金币: 120\n")
        assert d.sets == {"金币": 120}

    def test_non_item_delta_goes_to_deltas(self):
        d = parse_stat_block("【变化】\n信任 +5\n怀疑 -2\n")
        assert d.deltas == {"信任": 5.0, "怀疑": -2.0}

    def test_unknown_keys_need_no_schema(self):
        """万能键的核心：代码不认识的键也能收下（新增属性无需改代码）。"""
        d = parse_stat_block("【变化】\n某种从没见过的自定义值 +3\n")
        assert d.deltas == {"某种从没见过的自定义值": 3.0}

    def test_repeat_keys_accumulate(self):
        d = parse_stat_block("【变化】\n信任 +5\n信任 +2\n")
        assert d.deltas == {"信任": 7.0}


class TestTolerance:
    def test_fullwidth_punctuation(self):
        d = parse_stat_block("【状态】苏小染｜女｜显｜平静｜好感度 1000/1000\n【变化】\nphoto_seen＝true\n")
        assert d.fixed["name"] == "苏小染"
        assert d.sets["photo_seen"] is True

    def test_fullwidth_sign_and_colon(self):
        d = parse_stat_block("【变化】\n金币：100\n长夜酒＋2\n")
        assert d.sets["金币"] == 100
        # 没有「类型: 背包物品」分组 → 按普通数值处理（归不归背包由模型的显式分组决定，
        # 解析器不替它猜 —— 这正是"万能键"该有的克制）
        assert d.deltas == {"长夜酒": 2.0}

    def test_marker_variants(self):
        for marker in ("【状态】", "[状态]", "【当前状态】"):
            assert parse_stat_block(f"{marker}A|女|显|平静|1/2").saw_state is True
        for marker in ("【变化】", "[变化]", "【数值变化】", "【变更】"):
            assert parse_stat_block(f"{marker}\n金币 +1").saw_change is True

    def test_change_content_on_marker_line(self):
        d = parse_stat_block("【变化】金币 +3")
        assert d.deltas == {"金币": 3.0}

    def test_reserved_keys_are_refused(self):
        d = parse_stat_block("【变化】\nturn = 9\nscene_id: x\n")
        assert d.sets == {} and d.deltas == {}
        assert len(d.warnings) == 2
        assert all("保留键" in w for w in d.warnings)
        assert all(k in RESERVED_KEYS for k in ("turn", "scene_id"))

    def test_unrecognized_lines_are_kept_not_dropped(self):
        d = parse_stat_block("【变化】\n这是一句模型自由发挥的话\n金币 +1\n")
        assert d.unknown == ["这是一句模型自由发挥的话"]
        assert d.deltas == {"金币": 1.0}

    @pytest.mark.parametrize("bad", [None, "", "   ", 123, [], {"a": 1}])
    def test_never_raises_on_bad_input(self, bad):
        d = parse_stat_block(bad)
        assert isinstance(d, StatDelta)
        assert d.is_empty
        assert d.saw_state is False and d.saw_change is False

    def test_narrative_outside_block_is_ignored(self):
        d = parse_stat_block("她笑了一下。\n又补了一句：金币很多。\n")
        assert d.is_empty and d.unknown == [] and d.warnings == []

    def test_missing_state_section_still_parses_change(self):
        d = parse_stat_block("【变化】\n金币 +1")
        assert d.saw_state is False and d.saw_change is True
        assert d.deltas == {"金币": 1.0}

    def test_repeated_state_lines_last_wins(self):
        """``【状态】`` 可多次出现，**以最后一次为准**。

        模型常用「变化前 / 变化后」两段式输出，末段才是终态；若取第一段，玩家会看到
        一个永远停在回合初的状态栏。
        """
        d = parse_stat_block("【状态】A|女|显|平静|1/2\n【状态】B|男|隐|怒|3/4\n")
        assert d.fixed["name"] == "B"
        assert d.fixed["mood"] == "怒"
        assert d.fixed["affinity"] == {"value": 3, "max": 4}


class TestRender:
    def test_roundtrip_renders_and_reparses(self):
        text = render_stat_block(
            fixed={"name": "苏小染", "gender": "女", "visibility": "显", "mood": "平静",
                   "affinity": {"value": 1000, "max": 1000}},
            deltas={"信任": 5},
            items={"长夜酒": 1},
        )
        assert "【状态】苏小染|女|显|平静|1000/1000" in text
        d = parse_stat_block(text)
        assert d.fixed["name"] == "苏小染"
        assert d.fixed["affinity"] == {"value": 1000, "max": 1000}
        assert d.deltas == {"信任": 5.0}
        assert d.items == {"长夜酒": 1.0}

    def test_empty_render_is_empty_string(self):
        assert render_stat_block() == ""

    def test_fixed_fields_count_is_stable(self):
        """固定位置字段是本模块与 prompt 侧的契约，变动需同步两侧。"""
        assert FIXED_FIELDS == ("name", "gender", "visibility", "mood", "affinity")
