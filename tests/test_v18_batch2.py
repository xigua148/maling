# -*- coding: utf-8 -*-
"""v1.8 第二批测试（F6 回应约定 V18-07/08 + F5 角色卡 v2 V18-09/10）。

覆盖（team-lead 指定六类针对性）：
  ① response_rules CRUD + 20 上限拒写 + 读时迁移（旧文件无键自动补）；
  ② 触发词命中注入（命中/未命中/禁用规则/规则>偏好 与 mute 正交）；
  ③ 角色卡 v2 round-trip（导出→导入字段一致；v1 旧卡全兼容）；
  ④ cover_image 压缩（>512px 大图 → 压缩后 base64 ≤500KB + 尺寸 ≤512）；
  ⑤ 导入预览弹窗 offscreen 构造 + 冲突改名提示 + 异常红字；
  ⑥ 对齐链零破坏断言（notify_role_switch / sync_role_override_to_session
     接线语义不变 + 导入链 dedupe/parse 行为不变）。

隔离：MemoryManager filepath=tmp_path；Qt offscreen；零真实 ~/.maid_coder。
"""
import base64
import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

import gui.role_card as role_card  # noqa: E402
from memory import MemoryManager  # noqa: E402
from gui.chat_service import build_response_rule_injection  # noqa: E402


# ---------------------------------------------------------------------------
# ① response_rules CRUD + 上限 + 读时迁移
# ---------------------------------------------------------------------------
class TestResponseRules:
    def test_crud_and_persistence(self, tmp_path):
        fp = tmp_path / "memory.json"
        mm = MemoryManager(filepath=str(fp))
        rid = mm.add_rule("上线了", "回复辛苦了，别给建议")
        assert rid.startswith("rule_")
        mm.update_rule(rid, response="只说辛苦了")
        mm2 = MemoryManager(filepath=str(fp))
        rules = mm2.list_rules()
        assert len(rules) == 1
        assert rules[0]["trigger"] == "上线了"
        assert rules[0]["response"] == "只说辛苦了"
        assert rules[0]["enabled"] is True
        assert rules[0]["source"] == "manual"

    def test_old_file_migration(self, tmp_path):
        """旧 user_memory.json 无 response_rules 键 -> 读入自动补 []。"""
        fp = tmp_path / "old.json"
        old = {"preferences": {"nickname": "小远"},
               "topics": {"active": [], "archived": []},
               "meta": {"version": 1}}
        fp.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
        mm = MemoryManager(filepath=str(fp))
        assert mm._data.get("response_rules") == []
        assert mm.get_preference("nickname") == "小远"   # 旧数据零破坏
        assert mm._data["meta"]["version"] == 1          # meta.version 不升

    def test_rules_limit_reject_write(self, tmp_path):
        """20 条上限：超出写入被拒，绝不自动淘汰。"""
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        mm._data["response_rules"] = [
            {"id": f"rule_{i}", "trigger": f"词{i}", "response": "r",
             "enabled": True, "created_at": "", "last_hit_at": None,
             "source": "manual"}
            for i in range(20)]
        with pytest.raises(ValueError):
            mm.add_rule("新词", "新回应")
        assert len(mm._data["response_rules"]) == 20

    def test_duplicate_trigger_and_length_clamp(self, tmp_path):
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        mm.add_rule("上线了", "辛苦了")
        with pytest.raises(ValueError):
            mm.add_rule("上线了", "另一条")
        rid = mm.add_rule("词" * 50, "回" * 300)
        rule = mm.get_rule(rid)
        assert len(rule["trigger"]) == role_card_max_trigger()
        assert len(rule["response"]) <= 100


def role_card_max_trigger():
    from memory import _RULE_TRIGGER_MAX
    return _RULE_TRIGGER_MAX


# ---------------------------------------------------------------------------
# ② 触发词命中注入（命中/未命中/禁用/正交）
# ---------------------------------------------------------------------------
class TestRuleInjection:
    def _mm(self, tmp_path):
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        mm.add_rule("上线了", "回复辛苦了，别给建议")
        return mm

    def test_hit_injection(self, tmp_path):
        mm = self._mm(tmp_path)
        lines = build_response_rule_injection(mm, "我上线了")
        assert len(lines) == 1
        assert "【回应约定】" in lines[0]
        assert "上线了" in lines[0] and "辛苦了" in lines[0]

    def test_miss_zero_injection(self, tmp_path):
        mm = self._mm(tmp_path)
        assert build_response_rule_injection(mm, "今天天气不错") == []

    def test_disabled_rule_not_hit(self, tmp_path):
        mm = self._mm(tmp_path)
        rid = mm.list_rules()[0]["id"]
        mm.update_rule(rid, enabled=False)
        assert build_response_rule_injection(mm, "我上线了") == []
        mm.update_rule(rid, enabled=True)
        assert build_response_rule_injection(mm, "我上线了")

    def test_last_hit_at_recorded_not_counted(self, tmp_path):
        """last_hit_at = 上次生效呈现原料；R-A 不计任何次数（单值覆盖，无计数器）。"""
        mm = self._mm(tmp_path)
        rid = mm.list_rules()[0]["id"]
        assert mm.get_rule(rid)["last_hit_at"] is None
        build_response_rule_injection(mm, "我上线了")
        first = mm.get_rule(rid)["last_hit_at"]
        assert first
        build_response_rule_injection(mm, "我又上线了")
        after = mm.get_rule(rid)["last_hit_at"]
        # 仍为单一 ISO 时间戳（覆盖更新，不是计数/列表/统计）
        assert isinstance(after, str) and "T" in after
        assert after >= first

    def test_rule_over_preference_and_orthogonal_to_mute(self, tmp_path):
        """规则 > 偏好（约定 > 画像）；规则与 mute 正交（三方并存）。"""
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        mm.add_rule("上线了", "只说辛苦了")
        mm.set_preference("回复风格", "详细解释", source="manual")
        mm.add_topic("Rust 入门", source="auto")
        # 偏好照常注入 build_memory_context（画像仍在）
        ctx = mm.build_memory_context()
        assert "回复风格" in ctx
        # 命中规则 → 注入约定行（约定 > 画像，由注入序位实体后约定先于概览保证）
        lines = build_response_rule_injection(mm, "我上线了")
        assert any("【回应约定】" in l for l in lines)
        # mute 话题不影响规则命中（正交）
        mm.record_followup_feedback("Rust 入门", "mute")
        assert build_response_rule_injection(mm, "我上线了")
        # 规则存在不影响 mute 写回
        t = mm.get_active_topics()[0]
        assert t.get("followup_muted_until")  # mute 正常落盘


# ---------------------------------------------------------------------------
# ③ 角色卡 v2 round-trip + v1 兼容
# ---------------------------------------------------------------------------
class TestRoleCardV2:
    def _role(self, rm, name="圆环角色"):
        role = rm.create_role(name, "描述A")
        role.system_prompt = "系统提示词X"
        role.personality = {"lively": 77, "rigorous": 33, "caring": 88}
        role.opening_lines = ["开场白甲", "开场白乙"]
        role.example_dialogues = [
            {"user": "u1", "assistant": "a1", "enabled": True},
        ]
        role.current_expression = "happy"
        rm.save_role(role)
        return role

    def test_roundtrip_fields_match(self, tmp_path):
        from gui.pages.page_role import RoleManager
        rm = RoleManager(roles_dir=tmp_path)
        role = self._role(rm)
        card = role_card.export_card(role)
        assert card["schema_version"] == 2
        parsed = role_card.parse_card(json.loads(json.dumps(card)))
        for key in ("name", "description", "system_prompt", "personality",
                    "opening_lines", "example_dialogues", "current_expression",
                    "cover_image"):
            assert parsed[key] == card[key], key

    def test_v1_card_fully_compatible(self):
        """v1 旧卡导入零回归：缺 cover_image → 空串，其余逐项一致。"""
        v1 = {"card_type": "malingcard", "schema_version": 1,
              "name": "旧卡", "description": "d", "system_prompt": "s",
              "personality": {"lively": 80, "rigorous": 50, "caring": 20},
              "opening_lines": ["hi"],
              "example_dialogues": [{"user": "u", "assistant": "a"}],
              "current_expression": "normal"}
        parsed = role_card.parse_card(v1)
        assert parsed["cover_image"] == ""
        assert parsed["personality"] == {"lively": 80, "rigorous": 50, "caring": 20}

    def test_v2_forward_compat_unknown_fields_ignored(self):
        v2 = {"card_type": "malingcard", "schema_version": 2, "name": "未来卡",
              "unknown_field_v99": {"whatever": 1}}
        parsed = role_card.parse_card(v2)   # 不崩，未知字段忽略
        assert parsed["name"] == "未来卡"

    def test_cover_over_limit_downgraded(self):
        """卡内封面超 500KB → 降级空串（不拒整卡），预览弹窗红字路径。"""
        huge = "data:image/png;base64," + "A" * (500 * 1024)
        parsed = role_card.parse_card({"name": "大封面卡", "cover_image": huge})
        assert parsed["cover_image"] == ""
        ok = role_card.parse_card({
            "name": "小封面卡",
            "cover_image": "data:image/png;base64,"
                           + base64.b64encode(b"\x89PNG" * 8).decode()})
        assert ok["cover_image"].startswith("data:image/png;base64,")

    def test_summary_personality_tier_words_no_numbers(self):
        """R-A：预览摘要性格三值档位词呈现，不显数值。"""
        card = role_card.parse_card({
            "name": "档位卡",
            "personality": {"lively": 77, "rigorous": 50, "caring": 10}})
        text = role_card.card_summary_text(card)
        assert "偏上" in text and "适中" in text and "偏低" in text
        assert "77" not in text and "50" not in text and "10" not in text

    def test_spec_doc_matches_implementation(self):
        """R-K：规范文档与实现逐字段一致（字段清单核对）。"""
        doc = (ROOT / "docs" / "character-card-spec.md").read_text(
            encoding="utf-8")
        for field in role_card.EXPORT_FIELDS:
            assert f"`{field}`" in doc, f"规范文档缺字段 {field}"
        assert "1MB" in doc and "500KB" in doc and "512px" in doc
        assert "schema v2" in doc.lower()


# ---------------------------------------------------------------------------
# ④ cover_image 压缩链（offscreen Qt）
# ---------------------------------------------------------------------------
class TestCoverCompression:
    def _big_png(self, tmp_path):
        from PySide6.QtGui import QImage, QColor
        img = QImage(1600, 1200, QImage.Format.Format_RGB32)
        for y in range(0, 1200, 5):
            for x in range(0, 1600, 5):
                img.setPixelColor(x, y, QColor((x * 7) % 255, (y * 5) % 255, 128))
        path = tmp_path / "cover.png"
        img.save(str(path), "PNG")
        return path

    def test_compress_and_roundtrip(self, tmp_path):
        from PySide6.QtGui import QImage
        path = self._big_png(tmp_path)
        uri = role_card.prepare_cover_image(str(path))
        assert uri.startswith("data:image/")
        b64 = uri.split(",", 1)[1]
        assert len(b64) <= role_card.COVER_MAX_B64_BYTES  # ≤500KB
        raw = base64.b64decode(b64)
        out = QImage.fromData(raw)
        assert not out.isNull()
        assert max(out.width(), out.height()) <= role_card.COVER_MAX_PIXEL  # ≤512px

    def test_invalid_image_rejected(self, tmp_path):
        bad = tmp_path / "bad.png"
        bad.write_bytes(b"not an image")
        with pytest.raises(role_card.CardError):
            role_card.prepare_cover_image(str(bad))


# ---------------------------------------------------------------------------
# ⑤ 导入预览弹窗（offscreen）
# ---------------------------------------------------------------------------
class TestImportPreviewDialog:
    def _card(self, cover=""):
        return {"name": "女仆", "description": "温柔的编程伙伴" * 20,
                "system_prompt": "你是码铃…",
                "personality": {"lively": 77, "rigorous": 50, "caring": 10},
                "opening_lines": ["a", "b"],
                "example_dialogues": [{"user": "u", "assistant": "a"}],
                "current_expression": "normal", "cover_image": cover}

    def test_construct_and_conflict_rename_hint(self):
        from PySide6.QtWidgets import QApplication, QLabel
        QApplication.instance() or QApplication([])
        from gui.widgets.card_import_preview import CardImportPreviewDialog
        dlg = CardImportPreviewDialog(self._card(), ["女仆"])
        assert dlg.final_name == "女仆（导入）"   # 冲突自动改名
        blob = " ".join(l.text() for l in dlg.findChildren(QLabel))
        assert "女仆（导入）" in blob              # 冲突提示可见
        assert "偏上" in blob and "偏低" in blob   # 性格档位词
        assert "77" not in blob and "10" not in blob  # R-A 零数值
        assert "2 套" in blob and "1 组" in blob
        dlg2 = CardImportPreviewDialog(self._card(), [])
        assert dlg2.final_name == "女仆"           # 无冲突不改名

    def test_broken_cover_red_text(self):
        from PySide6.QtWidgets import QApplication, QLabel
        QApplication.instance() or QApplication([])
        from gui.widgets.card_import_preview import CardImportPreviewDialog
        dlg = CardImportPreviewDialog(
            self._card(cover="data:image/png;base64,!!!!bad!!!!"))
        errs = [l for l in dlg.findChildren(QLabel)
                if l.objectName() == "cardPreviewError"]
        assert errs and "异常" in errs[0].text()    # 异常红字 + 仍可确认导入


# ---------------------------------------------------------------------------
# ⑥ 对齐链零破坏断言
# ---------------------------------------------------------------------------
class TestAlignmentChainIntact:
    def test_notify_role_switch_semantics_unchanged(self):
        """v1.5.1 边界注入：消息构造与 _trim_history 保留行为零变更。"""
        from session import ChatSession
        import inspect
        src = inspect.getsource(ChatSession.notify_role_switch)
        assert "角色已切换为" in src
        assert "一律忽略" in src

    def test_sync_role_override_to_session_still_wired(self):
        """page_role._sync_role_override → sync_role_override_to_session 接线在位。"""
        from gui.pages import page_role
        import inspect
        assert hasattr(page_role, "sync_role_override_to_session")
        src = inspect.getsource(page_role.PageRole._sync_role_override)
        assert "sync_role_override_to_session" in src

    def test_import_flow_uses_parse_and_dedupe(self, tmp_path):
        """导入链行为不变：parse_card 清洗 + dedupe_import_name 改名 + 新 id 落盘。"""
        from gui.pages.page_role import RoleManager
        rm = RoleManager(roles_dir=tmp_path)
        first = rm.create_role("撞名角色")
        rm.save_role(first)
        card = role_card.export_card(first)
        parsed = role_card.parse_card(card)
        final_name = role_card.dedupe_import_name(
            parsed["name"], [r.name for r in rm.all_roles()])
        assert final_name == "撞名角色（导入）"
        new_role = rm.create_role(final_name)
        assert new_role.id != first.id

    def test_preview_dialog_wired_into_import(self):
        """page_role 导入入口已接预览弹窗（v1.7 Q-C10 收编落地）。"""
        import inspect
        from gui.pages import page_role
        src = inspect.getsource(page_role.PageRole._on_import_role_card)
        assert "CardImportPreviewDialog" in src
        assert "preview.final_name" in src   # 与预览提示一致的改名落盘
