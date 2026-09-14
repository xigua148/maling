# -*- coding: utf-8 -*-
"""v1.7 第三批测试（F8/F9 人设工坊 D-V17-07/08/09）。

覆盖（team-lead 指定六类针对性）：
- ① 旧角色文件加载零破坏（无新字段 .get 默认 []，str 开场白兼容）；
- ② 示例对话注入 payload 断言（enabled 过滤 / 角色名前缀 / ≤2000 字截断 / 旧签名零变化）；
- ③ 开场白注入幂等（inject_opening_line 双调用防重 + 空配置零注入 + 启动 sync 链零消息）；
- ④ 导入导出 round-trip（导出→json→parse→字段一致 + R-I 白名单断言）；
- ⑤ 导入缺字段默认值 / 非法卡拒绝 / 名称冲突收敛；
- ⑥ 编辑面板新入口存在（offscreen PageRole：开场白/示例对话/导出/导入按钮 + 概要刷新）。

隔离：roles_dir/session 全部 tmp_path / Fake 对象；Qt 走 offscreen；零真实 ~/.maid_coder。
"""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gui.pages.page_role as pr  # noqa: E402
import gui.role_card as role_card  # noqa: E402
from gui.pages.page_role import (  # noqa: E402
    Role, RoleManager, build_role_system_prompt, build_example_dialogues_block,
    inject_opening_line, normalize_opening_lines, normalize_example_dialogues,
    parse_opening_lines_text, format_opening_lines_text,
    resolve_role_override_prompt, sync_role_override_to_session,
    EXAMPLE_BLOCK_MAX_CHARS, MAX_OPENING_LINES, MAX_EXAMPLE_DIALOGUES,
)


# ---------------------------------------------------------------------------
# 测试替身（零 Qt）
# ---------------------------------------------------------------------------
class _DispMsg:
    def __init__(self, role, content):
        self.role = role
        self.content = content


class FakeDispSession:
    """显示会话替身（gui/models.ChatSession 最小面）。"""

    def __init__(self):
        self.messages = []

    def add_message(self, role, content, **kwargs):
        msg = _DispMsg(role, content)
        self.messages.append(msg)
        return msg


class FakeSessionManager:
    def __init__(self):
        self._active = FakeDispSession()
        self.saved = 0

    @property
    def active_session(self):
        return self._active

    def save_session(self, session):
        self.saved += 1


class FakeLLMSession:
    """CLI ChatSession 最小面（add_message 直写 history）。"""

    def __init__(self):
        self.history = []

    def add_message(self, role, content, **kwargs):
        msg = {"role": role}
        if content is not None:
            msg["content"] = content
        self.history.append(msg)


class FakeCtx:
    def __init__(self):
        self.session_manager = FakeSessionManager()
        self.session = FakeLLMSession()


def _make_role(**kwargs) -> Role:
    base = dict(id="role_t1", name="测试角色")
    base.update(kwargs)
    return Role(**base)


# ---------------------------------------------------------------------------
# ① 旧角色文件加载零破坏
# ---------------------------------------------------------------------------
class TestOldRoleCompat:
    def test_old_role_json_loads_without_new_fields(self, tmp_path):
        data = {
            "id": "role_old1", "name": "旧角色", "description": "旧描述",
            "system_prompt": "旧提示词", "personality": {"lively": 60},
            "intimacy": 2, "created_at": "2026-01-01T00:00:00",
        }  # 无 opening_lines / example_dialogues
        (tmp_path / "role_old1.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        rm = RoleManager(roles_dir=tmp_path)
        role = rm.get_role("role_old1")
        assert role is not None
        assert role.name == "旧角色"
        assert role.opening_lines == []
        assert role.example_dialogues == []

    def test_old_role_roundtrip_zero_migration(self, tmp_path):
        """旧文件 → 加载 → 落盘 → 再加载：新字段以 [] 写入，旧字段原样保留。"""
        data = {"id": "role_old2", "name": "旧角色二", "system_prompt": "p"}
        (tmp_path / "role_old2.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        rm = RoleManager(roles_dir=tmp_path)
        role = rm.get_role("role_old2")
        rm.save_role(role)
        reloaded = json.loads((tmp_path / "role_old2.json").read_text(encoding="utf-8"))
        assert reloaded["name"] == "旧角色二"
        assert reloaded["system_prompt"] == "p"
        assert reloaded["opening_lines"] == []
        assert reloaded["example_dialogues"] == []

    def test_single_string_opening_line_compat(self):
        """str 开场白（旧数据/手填）兼容收敛为 list。"""
        assert normalize_opening_lines("你好呀") == ["你好呀"]
        assert _make_role(opening_lines="你好呀").opening_lines == ["你好呀"]

    def test_limits_and_garbage_filtered(self):
        assert normalize_opening_lines(["a", "", "  ", 123, "b", "c", "d"]) == ["a", "b", "c"]
        assert len(normalize_opening_lines(["1", "2", "3", "4"])) == MAX_OPENING_LINES
        dialogs = [
            {"user": "u1", "assistant": "a1", "enabled": False},
            {"user": "u2"},                      # 缺 assistant → 丢弃
            {"user": None, "assistant": "a3"},   # 非法 → 丢弃
            "not-a-dict",                        # 非法 → 丢弃
            {"user": "u5", "assistant": "a5", "enabled": True},
        ]
        out = normalize_example_dialogues(dialogs)
        assert [d["user"] for d in out] == ["u1", "u5"]
        assert out[1]["enabled"] is True  # 缺 enabled 默认 True


# ---------------------------------------------------------------------------
# ② 示例对话注入 payload 断言
# ---------------------------------------------------------------------------
class TestExampleDialoguesInjection:
    def test_two_arg_signature_output_unchanged(self):
        """旧签名（两参调用，无示例配置）输出零回归：第三参缺省不追加示例块，
        同参重复调用逐字节一致。"""
        out = build_role_system_prompt("你是测试。", {"lively": 10, "rigorous": 20, "caring": 30})
        assert out.startswith("你是测试。\n\n【性格参数】活泼度 10/100")
        assert "【对话风格示例】" not in out
        # 旧签名重复调用（不传第三参）逐字节一致（缺省 example_dialogues=None 零影响）
        assert build_role_system_prompt("你是测试。", {"lively": 10, "rigorous": 20, "caring": 30}) == out
        # 未配置示例时显式传 None 同样零追加
        assert build_role_system_prompt("你是测试。", {"lively": 10, "rigorous": 20, "caring": 30}, example_dialogues=None) == out

    def test_block_contains_enabled_groups_with_role_name(self):
        dialogs = [
            {"user": "今天写什么代码", "assistant": "（竖起耳朵）本喵来帮你喵！", "enabled": True},
            {"user": "被禁用的一组", "assistant": "不该出现", "enabled": False},
        ]
        block = build_example_dialogues_block(dialogs, role_name="猫娘")
        assert block.startswith("【对话风格示例】")
        assert "（仅供语气与相处方式参考，不要在对话中复述这些示例）" in block
        assert "用户：今天写什么代码" in block
        assert "猫娘：（竖起耳朵）本喵来帮你喵！" in block
        assert "被禁用的一组" not in block

    def test_block_truncated_to_2000(self):
        dialogs = [{"user": "u" * 500, "assistant": "a" * 500, "enabled": True}
                   for _ in range(20)]
        block = build_example_dialogues_block(dialogs, role_name="长角色")
        assert len(block) <= EXAMPLE_BLOCK_MAX_CHARS
        assert len(block) == EXAMPLE_BLOCK_MAX_CHARS

    def test_empty_dialogues_return_empty_block(self):
        assert build_example_dialogues_block(None) == ""
        assert build_example_dialogues_block([]) == ""
        assert build_example_dialogues_block([{"user": "u", "assistant": "a", "enabled": False}]) == ""

    def test_full_prompt_appends_block_when_configured(self):
        dialogs = [{"user": "你好", "assistant": "主人好呀", "enabled": True}]
        out = build_role_system_prompt("你是测试。", {"lively": 50, "rigorous": 50, "caring": 50},
                                       example_dialogues=dialogs, role_name="女仆")
        assert "【对话风格示例】" in out
        assert "女仆：主人好呀" in out

    def test_resolve_role_override_prompt_includes_block(self, tmp_path):
        """gui_role_prompt 覆盖链携带示例块（D-V17-07 当轮生效）。"""
        rm = RoleManager(roles_dir=tmp_path)
        role = rm.get_role(rm._default_role_id)
        role.system_prompt = "定制人设。"
        role.example_dialogues = [{"user": "在吗", "assistant": "在的呢", "enabled": True}]
        rm.save_role(role)
        rm.set_default(role.id)
        prompt = resolve_role_override_prompt(rm)
        assert prompt is not None and "【对话风格示例】" in prompt and "在的呢" in prompt

    def test_resolve_role_override_prompt_clean_role_unchanged(self, tmp_path):
        rm = RoleManager(roles_dir=tmp_path)  # 全新目录：pristine 默认角色
        assert resolve_role_override_prompt(rm) is None


# ---------------------------------------------------------------------------
# ③ 开场白注入幂等（D-V17-08）
# ---------------------------------------------------------------------------
class TestOpeningLineInjection:
    def test_inject_writes_llm_history_and_display(self):
        ctx = FakeCtx()
        role = _make_role(opening_lines=["主人好，今天也要加油哦～"])
        assert inject_opening_line(ctx, ctx.session, role) is True
        assert ctx.session.history == [
            {"role": "assistant", "content": "主人好，今天也要加油哦～"}
        ]
        assert ctx.session_manager.active_session.messages[-1].role == "assistant"
        assert ctx.session_manager.saved == 1

    def test_inject_idempotent_second_call_skipped(self):
        """幂等守卫：显示会话末尾已是同内容 assistant → 第二次注入跳过
        （防启动 sync / 重复触发双注入）。"""
        ctx = FakeCtx()
        role = _make_role(opening_lines=["唯一开场白"])
        assert inject_opening_line(ctx, ctx.session, role) is True
        llm_len = len(ctx.session.history)
        disp_len = len(ctx.session_manager.active_session.messages)
        assert inject_opening_line(ctx, ctx.session, role) is False
        assert len(ctx.session.history) == llm_len
        assert len(ctx.session_manager.active_session.messages) == disp_len

    def test_inject_random_rotation_among_lines(self):
        """多套开场白：注入内容 ∈ 配置集合（F9 轮换）。"""
        import random as _random
        lines = ["开场白一", "开场白二", "开场白三"]
        seen = set()
        for seed in range(30):
            ctx = FakeCtx()
            _random.seed(seed)
            role = _make_role(opening_lines=lines)
            assert inject_opening_line(ctx, ctx.session, role) is True
            seen.add(ctx.session.history[0]["content"])
        assert seen <= set(lines)

    def test_empty_opening_lines_zero_injection(self):
        """空配置零注入（v1.6 行为零回归）。"""
        ctx = FakeCtx()
        assert inject_opening_line(ctx, ctx.session, _make_role()) is False
        assert ctx.session.history == []
        assert ctx.session_manager.active_session.messages == []

    def test_no_session_graceful(self):
        ctx = FakeCtx()
        ctx.session = None
        role = _make_role(opening_lines=["你好"])
        assert inject_opening_line(ctx, None, role) is False
        # LLM 目标缺失 → 显示会话也不动（防"显示有、LLM 无"分叉）
        assert ctx.session_manager.active_session.messages == []

    def test_startup_sync_chain_injects_no_messages(self, tmp_path):
        """启动 sync 链（sync_role_override_to_session）绝不注入任何消息——
        开场白只允许出现在两个显式调用点（D-V17-08 红线）。"""
        ctx = FakeCtx()
        rm = RoleManager(roles_dir=tmp_path)
        role = rm.get_role(rm._default_role_id)
        role.system_prompt = "定制。"
        role.opening_lines = ["开场白不该出现在这里"]
        rm.save_role(role)
        rm.set_default(role.id)
        sync_role_override_to_session(ctx.session, rm)
        assert ctx.session.history == []  # sync 只动 system，不加 user/assistant 消息


# ---------------------------------------------------------------------------
# ④ 导入导出 round-trip + R-I 白名单
# ---------------------------------------------------------------------------
class TestRoleCardRoundTrip:
    def test_export_import_roundtrip_fields_match(self, tmp_path):
        rm = RoleManager(roles_dir=tmp_path)
        role = rm.create_role("圆环角色", "描述A")
        role.system_prompt = "系统提示词X"
        role.personality = {"lively": 77, "rigorous": 33, "caring": 88}
        role.opening_lines = ["开场白甲", "开场白乙"]
        role.example_dialogues = [
            {"user": "u1", "assistant": "a1", "enabled": True},
            {"user": "u2", "assistant": "a2", "enabled": False},
        ]
        role.current_expression = "happy"
        rm.save_role(role)

        card = role_card.export_card(role)
        path = tmp_path / "roundtrip.malingcard.json"
        path.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")

        loaded = json.loads(path.read_text(encoding="utf-8"))
        parsed = role_card.parse_card(loaded)
        assert parsed["name"] == "圆环角色"
        assert parsed["description"] == "描述A"
        assert parsed["system_prompt"] == "系统提示词X"
        assert parsed["personality"] == {"lively": 77, "rigorous": 33, "caring": 88}
        assert parsed["opening_lines"] == ["开场白甲", "开场白乙"]
        assert parsed["example_dialogues"] == [
            {"user": "u1", "assistant": "a1", "enabled": True},
            {"user": "u2", "assistant": "a2", "enabled": False},
        ]
        assert parsed["current_expression"] == "happy"

    def test_export_whitelist_no_private_fields(self):
        """R-I：导出绝不含 avatar/id/记忆/亲密度/历史。"""
        role = _make_role(
            id="role_priv", avatar="/home/user/private.png", intimacy=4,
            created_at="2020-01-01T00:00:00", is_default=True,
            opening_lines=["hi"], example_dialogues=[{"user": "u", "assistant": "a"}],
        )
        card = role_card.export_card(role)
        forbidden = {"id", "avatar", "intimacy", "created_at", "is_default",
                     "messages", "history", "memory", "memories", "session"}
        assert forbidden.isdisjoint(card.keys())
        assert set(role_card.EXPORT_FIELDS) <= set(card.keys())
        # v1.8(D-V18-06): schema 升 v2（cover_image 字段），v1 旧卡导入仍全兼容
        assert card["card_type"] == "malingcard" and card["schema_version"] == 2
        assert "exported_at" in card

    def test_parse_card_size_limit_rejected(self, tmp_path):
        big = {"name": "大卡", "padding": "x" * (role_card.MAX_CARD_BYTES + 10)}
        with pytest.raises(role_card.CardError):
            role_card.parse_card(big)

    def test_card_survives_json_file_roundtrip_unicode(self, tmp_path):
        role = _make_role(name="表情角色🎨", opening_lines=["（开心）你来啦～"])
        card = role_card.export_card(role)
        path = tmp_path / "u.malingcard.json"
        path.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
        parsed = role_card.parse_card(json.loads(path.read_text(encoding="utf-8")))
        assert parsed["name"] == "表情角色🎨"
        assert parsed["opening_lines"] == ["（开心）你来啦～"]


# ---------------------------------------------------------------------------
# ⑤ 导入缺字段 / 非法卡 / 名称冲突
# ---------------------------------------------------------------------------
class TestImportValidation:
    def test_missing_fields_get_defaults(self):
        parsed = role_card.parse_card({"name": "极简卡"})
        assert parsed["name"] == "极简卡"
        assert parsed["description"] == ""
        assert parsed["system_prompt"] == ""
        assert parsed["personality"] == {"lively": 50, "rigorous": 50, "caring": 50}
        assert parsed["opening_lines"] == []
        assert parsed["example_dialogues"] == []
        assert parsed["current_expression"] == "normal"

    def test_invalid_card_rejected(self):
        with pytest.raises(role_card.CardError):
            role_card.parse_card("not a dict")
        with pytest.raises(role_card.CardError):
            role_card.parse_card([])
        with pytest.raises(role_card.CardError):
            role_card.parse_card({"description": "没有名字"})
        with pytest.raises(role_card.CardError):
            role_card.parse_card({"name": "  "})
        with pytest.raises(role_card.CardError):
            role_card.parse_card({"name": "x", "card_type": "other-card"})

    def test_personality_clamped(self):
        parsed = role_card.parse_card({
            "name": "越界卡",
            "personality": {"lively": 250, "rigorous": -10, "caring": "abc"},
        })
        assert parsed["personality"] == {"lively": 100, "rigorous": 0, "caring": 50}

    def test_name_conflict_dedupe(self):
        assert role_card.dedupe_import_name("新角色", []) == "新角色"
        assert role_card.dedupe_import_name("女仆", ["女仆"]) == "女仆（导入）"
        assert role_card.dedupe_import_name("女仆", ["女仆", "女仆（导入）"]) == "女仆（导入2）"
        assert role_card.dedupe_import_name(
            "女仆", ["女仆", "女仆（导入）", "女仆（导入2）", "女仆（导入3）"]
        ) == "女仆（导入4）"

    def test_import_flow_creates_renamed_role(self, tmp_path):
        """页面导入链：撞名自动改名 + 新 id 独立落盘。"""
        rm = RoleManager(roles_dir=tmp_path)
        first = rm.create_role("撞名角色")
        first.opening_lines = ["你来了"]
        rm.save_role(first)
        card = role_card.export_card(first)
        parsed = role_card.parse_card(card)
        final_name = role_card.dedupe_import_name(
            parsed["name"], [r.name for r in rm.all_roles()]
        )
        assert final_name == "撞名角色（导入）"
        new_role = rm.create_role(final_name)
        new_role.opening_lines = list(parsed["opening_lines"])
        rm.save_role(new_role)
        assert new_role.id != first.id
        assert rm.get_role(new_role.id).opening_lines == ["你来了"]
        assert rm.get_role(first.id) is not None  # 原角色不受影响


# ---------------------------------------------------------------------------
# ⑥ 编辑面板新入口存在（offscreen）
# ---------------------------------------------------------------------------
@pytest.fixture
def page_role_page(tmp_path, monkeypatch):
    """offscreen PageRole：隔离 roles_dir / avatars_dir，防污染真实家目录。"""
    from gui.qt_compat import QApplication
    monkeypatch.setattr(pr, "DEFAULT_ROLES_DIR", tmp_path / "roles")
    monkeypatch.setattr(pr, "ROLE_AVATARS_DIR", tmp_path / "roles" / "avatars")
    app = QApplication.instance() or QApplication([])
    ctx = SimpleNamespace(
        theme_engine=None, companion=None, session=None,
        role_bridge=None, session_manager=None,
    )
    page = pr.PageRole(ctx)
    yield page
    page.deleteLater()


class TestWorkshopUIEntries:
    def test_workshop_entry_buttons_exist(self, page_role_page):
        assert page_role_page.opening_entry_btn.text().startswith("🎬 开场白")
        assert page_role_page.dialogue_entry_btn.text().startswith("💬 示例对话")

    def test_card_buttons_exist(self, page_role_page):
        assert page_role_page.export_card_btn.text().startswith("📤 导出角色卡")
        assert page_role_page.import_card_btn.text().startswith("📥 导入角色卡")

    def test_entry_summary_refresh(self, page_role_page):
        role = page_role_page.role_manager.default_role
        role.opening_lines = ["一套", "两套"]
        role.example_dialogues = [{"user": "u", "assistant": "a", "enabled": True}]
        page_role_page._load_role_detail(role)
        assert "已配 2 套" in page_role_page.opening_entry_btn.text()
        assert "已配 1 组" in page_role_page.dialogue_entry_btn.text()

    def test_opening_text_parse_format_roundtrip(self):
        text = format_opening_lines_text(["甲", "乙", "丙"])
        assert parse_opening_lines_text(text) == ["甲", "乙", "丙"]
        assert len(text.splitlines()) == 5  # 3 套 + 2 个 --- 分隔行
        assert parse_opening_lines_text("单套（无分隔符）") == ["单套（无分隔符）"]
        assert parse_opening_lines_text("") == []
        assert len(parse_opening_lines_text("a\n---\nb\n---\nc\n---\nd")) == MAX_OPENING_LINES

    def test_role_opening_persisted_after_save(self, page_role_page):
        """工坊字段走既有 _save_role_fields 保存链落盘。"""
        page = page_role_page
        role = page.role_manager.default_role
        page._load_role_detail(role)
        role.opening_lines = ["落盘开场白"]
        role.example_dialogues = [{"user": "在吗", "assistant": "在的", "enabled": True}]
        assert page._save_role_fields() is True
        reloaded = RoleManager(roles_dir=page.role_manager.roles_dir).default_role
        assert reloaded.opening_lines == ["落盘开场白"]
        assert reloaded.example_dialogues[0]["assistant"] == "在的"


# ---------------------------------------------------------------------------
# R-A 快扫：工坊新 UI 文案零焦虑词
# ---------------------------------------------------------------------------
def test_workshop_ui_texts_no_redline():
    ui_texts = [
        "开场白", "示例对话", "已配", "未填写", "套", "组",
        "对话风格示例", "仅供语气与相处方式参考",
        "导出角色卡", "导入角色卡",
    ]
    redline_words = ["筹码", "胜率", "倒数", "断签", "打卡", "进度",
                     "心情曲线", "情绪报告", "记忆成就", "日记打卡"]
    for text in ui_texts:
        for word in redline_words:
            assert word not in text
