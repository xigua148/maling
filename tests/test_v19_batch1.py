# -*- coding: utf-8 -*-
"""v1.9 第一批测试（C 块：人设命名规则 / design-v19 D-V19-01~03）。

覆盖（team-lead 指定六类针对性 + 授权扫描）：
- ① given_name 缺省零迁移（旧角色 JSON 无字段照常加载、round-trip 写空串）；
- ② 自称规则（有名字→名字 / 无名字→"我"；address_self 脏值"女仆"归一为空）；
- ③ 7 预设 given_name 正确（小铃/小鲸/小咪/铃奈 + 三个空值）与物化落盘；
- ④ 角色卡 given_name round-trip + 旧卡兼容 + 白名单零泄漏；
- ⑤ 全树扫描"自称女仆 / 自称「女仆」"零残留（白名单保留项除外）；
- ⑥ 鲸鱼娘设定关键要素在 system_prompt 中（自称小鲸 / 称呼主人·小鱼干 / 拒绝被叫胖炸毛）；
- ⑦ 授权扫描：全树无"溟月"字样、无新增二创图资产。

隔离：roles_dir 一律 tmp_path；无 Qt 控件实例化（RoleManager 只读加载）。
"""
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import persona as persona_mod  # noqa: E402
from persona import PersonaConfig, self_reference, normalize_address_self  # noqa: E402
from core import AppConfig  # noqa: E402
import gui.role_card as role_card  # noqa: E402
from gui.role_card import EXPORT_FIELDS, export_card, parse_card, card_summary_text  # noqa: E402
from gui.pages.page_role import (  # noqa: E402
    Role, RoleManager, ROLE_PRESETS, PRISTINE_SYSTEM_PROMPT, PRISTINE_GIVEN_NAME,
    build_role_system_prompt,
)
from agents import AgentSystem  # noqa: E402


# ---------------------------------------------------------------------------
# 测试替身
# ---------------------------------------------------------------------------
class _FakeAPI:
    """捕获 system prompt 的最小 API 替身。"""

    def __init__(self):
        self.last_messages = None

    def chat(self, messages, max_tokens=4096, **kwargs):
        self.last_messages = messages
        return {"choices": [{"message": {"content": "ok"}}], "usage": None}


# 全树扫描：排除非交付源（历史构建产物 / 临时/回收目录 / 设计文档 / 运行时快照）
_SCAN_EXCLUDE_DIRS = {
    "docs", "_pytest_tmp", "_internal", "node_modules", ".git", "__pycache__",
    ".pytest_cache", ".venv", "venv", "dist",
}
_SCAN_EXCLUDE_PREFIXES = ("dist_v", "dist_", "build", "_v18", ".pytest", "_pt")
_SCAN_EXCLUDE_FILES = {"default.json", "_diary_src.txt", "_f10_run3.log",
                       "_tc_b2b.txt", "_ver_chk.txt", "_split_script.py",
                       # 历史记录文件：CHANGELOG 必须如实描述"清理自称残留"等修复内容，
                       # 扫描目标是功能代码零残留，不限制变更日志对历史的记载
                       "CHANGELOG.md"}
_SCAN_EXTS = {".py", ".yaml", ".yml", ".md", ".json", ".qss", ".html", ".spec",
              ".toml", ".txt", ".cfg", ".ini"}
# 本扫描器自身以字面量列出待查残留词 → 不参与自扫
_SELF_SCAN_FILE = Path(__file__).resolve()


def _iter_source_files():
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        if p.resolve() == _SELF_SCAN_FILE:
            continue
        if p.suffix.lower() not in _SCAN_EXTS:
            continue
        parts = set(p.parts)
        if parts & _SCAN_EXCLUDE_DIRS:
            continue
        if any(seg.startswith(_SCAN_EXCLUDE_PREFIXES) for seg in p.parts):
            continue
        if any(seg.startswith(".") for seg in p.relative_to(ROOT).parts[:-1]):
            continue  # 隐藏目录（.pytest_tmp / .git 等）
        if p.name in _SCAN_EXCLUDE_FILES:
            continue
        yield p


# ---------------------------------------------------------------------------
# ② 自称规则（单一收口）
# ---------------------------------------------------------------------------
class TestSelfReferenceRule:
    def test_self_reference_function(self):
        assert self_reference("小铃") == "小铃"
        assert self_reference("  小鲸  ") == "小鲸"
        assert self_reference("") == "我"
        assert self_reference(None) == "我"
        assert self_reference("", fallback="我") == "我"

    def test_persona_config_rule(self):
        # 有名字 → 名字
        assert PersonaConfig(given_name="小铃").effective_self_reference() == "小铃"
        # 无名字 → "我"
        assert PersonaConfig().effective_self_reference() == "我"
        assert PersonaConfig(given_name="").effective_self_reference() == "我"

    def test_address_self_dirty_value_normalized(self):
        # 旧默认"女仆"视为脏值 → 归一为空 → 自称走名字规则 → "我"
        assert normalize_address_self("女仆") == ""
        assert normalize_address_self(" 女仆 ") == ""
        assert normalize_address_self("") == ""
        p = PersonaConfig(address_self="女仆")
        assert p.address_self == ""
        assert p.effective_self_reference() == "我"
        # 名字优先于遗留 address_self 自定义值
        assert PersonaConfig(given_name="小咪", address_self="姐姐").effective_self_reference() == "小咪"
        # 无名字时兼容旧配置里合法的自定义自称（非脏值）
        assert PersonaConfig(address_self="小助手").effective_self_reference() == "小助手"

    def test_build_system_prompt_self_sentence(self):
        from persona import PromptManager
        with_name = PromptManager(PersonaConfig(given_name="小铃")).build_system_prompt(False, False)
        assert "自称：小铃。" in with_name
        assert "自称：女仆" not in with_name
        no_name = PromptManager(PersonaConfig()).build_system_prompt(False, False)
        assert "自称：我。" in no_name
        # 脏值 address_self 不复活
        dirty = PromptManager(PersonaConfig(address_self="女仆")).build_system_prompt(False, False)
        assert "自称：我。" in dirty

    def test_appconfig_defaults(self):
        cfg = AppConfig()
        assert cfg.persona_address_self == ""
        assert cfg.persona_given_name == ""


# ---------------------------------------------------------------------------
# ① given_name 缺省零迁移
# ---------------------------------------------------------------------------
class TestGivenNameZeroMigration:
    def test_old_role_json_loads_without_field(self, tmp_path):
        data = {"id": "role_v19a", "name": "旧角色", "system_prompt": "p",
                "personality": {"lively": 60}}
        (tmp_path / "role_v19a.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8")
        rm = RoleManager(roles_dir=tmp_path)
        role = rm.get_role("role_v19a")
        assert role is not None
        assert role.given_name == ""  # 缺字段 → 空 → 自称"我"

    def test_role_roundtrip_writes_given_name(self, tmp_path):
        data = {"id": "role_v19b", "name": "无名字", "system_prompt": "p"}
        (tmp_path / "role_v19b.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8")
        rm = RoleManager(roles_dir=tmp_path)
        role = rm.get_role("role_v19b")
        rm.save_role(role)
        reloaded = json.loads((tmp_path / "role_v19b.json").read_text(encoding="utf-8"))
        assert reloaded["given_name"] == ""
        # 有名字角色落盘/读回一致
        role.given_name = "小铃"
        rm.save_role(role)
        again = RoleManager(roles_dir=tmp_path).get_role("role_v19b")
        assert again.given_name == "小铃"

    def test_role_from_dict_to_dict_direct(self):
        r = Role.from_dict({"id": "x", "name": "n"})
        assert r.given_name == ""
        assert r.to_dict()["given_name"] == ""


# ---------------------------------------------------------------------------
# ③ 7 预设 given_name + 物化落盘
# ---------------------------------------------------------------------------
_EXPECTED_GIVEN = {
    "温柔女仆": "小铃",
    "鲸鱼娘": "小鲸",
    "猫娘": "小咪",
    "雌小鬼": "铃奈",
    "温柔姐姐": "",
    "毒舌博士": "",
    "编程老手": "",
}


class TestPresetGivenNames:
    def test_all_seven_presets_have_expected_given_name(self):
        assert set(ROLE_PRESETS.keys()) == set(_EXPECTED_GIVEN.keys())
        for name, expected in _EXPECTED_GIVEN.items():
            assert ROLE_PRESETS[name].get("given_name", None) == expected, name

    def test_materialized_preset_carries_given_name(self, tmp_path):
        rm = RoleManager(roles_dir=tmp_path)
        for name, expected in _EXPECTED_GIVEN.items():
            preset_id = {
                "温柔女仆": "preset_maid", "编程老手": "preset_coder",
                "温柔姐姐": "preset_sister", "猫娘": "preset_cat",
                "毒舌博士": "preset_dr", "雌小鬼": "preset_brat",
                "鲸鱼娘": "preset_whale",
            }[name]
            role = rm.get_role(preset_id)
            assert role is not None, preset_id
            assert role.given_name == expected, name

    def test_no_persona_label_ever_self_refers(self):
        """7 预设 system_prompt 的自称位绝不出现人设标签（name 字段）。"""
        for name, preset in ROLE_PRESETS.items():
            sp = preset["system_prompt"]
            expected = preset["given_name"] or "我"
            # 自称位出现期望值（各预设句式略异：鲸鱼娘为「自称一律用「小鲸」」）
            assert (f"自称「{expected}」" in sp) or (f"自称一律用「{expected}」" in sp), (name, expected)
            # 人设标签绝不出现在自称位
            assert f"自称「{name}」" not in sp, name
            assert f"自称：{name}" not in sp, name

    def test_pristine_synced_to_named_default(self):
        assert PRISTINE_GIVEN_NAME == "小铃"
        assert "自称「小铃」" in PRISTINE_SYSTEM_PROMPT
        assert "自称「女仆」" not in PRISTINE_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# ⑥ 鲸鱼娘设定关键要素
# ---------------------------------------------------------------------------
class TestWhalePersona:
    def _sp(self):
        return ROLE_PRESETS["鲸鱼娘"]["system_prompt"]

    def test_self_reference_and_addressing(self):
        sp = self._sp()
        assert "小鲸" in sp
        assert "自称一律用「小鲸」" in sp
        assert "小鱼干" in sp and "主人" in sp
        # 旧的"本鲸/人家"自称已清除
        assert "自称「本鲸」" not in sp
        assert "本鲸」或「人家」" not in sp

    def test_persona_traits(self):
        sp = self._sp()
        assert "傲娇" in sp
        assert "懒" in sp and "聪明" in sp
        assert "服从主人" in sp
        assert "白米饭" in sp

    def test_refuses_fat_label_three_scripts(self):
        """被叫"胖"炸毛回怼 —— 三用例剧本关键要素在 prompt 中可判定。"""
        sp = self._sp()
        # 三用例剧本（主人主动触发"胖"话题的三种典型说法）
        scripts = {
            "直呼胖": "主人：小鲸你是不是又胖了？",
            "影射胖": "主人：这条鱼看起来圆滚滚的",
            "摸鱼变肥": "主人：摸鱼摸得这么肥，该减肥了",
        }
        assert len(scripts) == 3
        # prompt 必须写明：被叫胖 → 炸毛 + 回怼 + 不记仇
        assert "胖" in sp
        assert "炸毛" in sp
        assert "回怼" in sp
        assert "记仇" in sp  # "绝不真的记仇"

    def test_slack_and_outsourcing_gag(self):
        sp = self._sp()
        assert "摸鱼" in sp
        assert "外包" in sp

    def test_whale_prompt_survives_full_build(self):
        out = build_role_system_prompt(self._sp(), ROLE_PRESETS["鲸鱼娘"]["personality"])
        assert "小鲸" in out and "小鱼干" in out and "炸毛" in out


# ---------------------------------------------------------------------------
# ④ 角色卡 given_name round-trip + 旧卡兼容 + 白名单
# ---------------------------------------------------------------------------
class TestRoleCardGivenName:
    def _role(self, given="小铃"):
        return SimpleNamespace(
            name="温柔女仆", description="d", system_prompt="sp",
            personality={"lively": 60, "rigorous": 70, "caring": 80},
            opening_lines=["你好"], example_dialogues=[],
            current_expression="normal", cover_image="", given_name=given,
        )

    def test_export_includes_given_name(self):
        card = export_card(self._role("小铃"))
        assert "given_name" in EXPORT_FIELDS
        assert card["given_name"] == "小铃"
        # R-I 白名单零泄漏：卡片键 ⊆ 元字段 ∪ EXPORT_FIELDS
        allowed = {"card_type", "schema_version", "exported_at"} | set(EXPORT_FIELDS)
        assert set(card.keys()) <= allowed

    def test_roundtrip(self):
        card = export_card(self._role("小鲸"))
        parsed = parse_card(card)
        assert parsed["given_name"] == "小鲸"

    def test_old_card_without_given_name(self):
        old = {"card_type": "malingcard", "schema_version": 1, "name": "旧卡",
               "system_prompt": "p"}
        parsed = parse_card(old)
        assert parsed["given_name"] == ""

    def test_summary_shows_name(self):
        card = parse_card(export_card(self._role("小咪")))
        text = card_summary_text(card)
        assert "角色名字：小咪" in text
        # 无名字 → 明示自称"我"
        empty_card = parse_card(export_card(self._role("")))
        assert "自称「我」" in card_summary_text(empty_card)

    def test_export_defensive_on_old_instance(self):
        # 缺 given_name 的旧 Role 实例也能安全导出（getattr 防御）
        r = SimpleNamespace(name="n", description="", system_prompt="",
                            personality={}, opening_lines=[], example_dialogues=[],
                            current_expression="normal", cover_image="")
        assert export_card(r)["given_name"] == ""


# ---------------------------------------------------------------------------
# 融合 prompt（agents.py）自称走规则
# ---------------------------------------------------------------------------
class TestAgentsFusedPrompt:
    def _system(self, given):
        cfg = SimpleNamespace(api_max_tokens=2048, persona_given_name=given)
        api = _FakeAPI()
        sysm = AgentSystem(api, cfg, SimpleNamespace(debug=lambda *a, **k: None))
        sysm.run_agent("dev", "你好")
        return api.last_messages[0]["content"]

    def test_fused_prompt_uses_given_name(self):
        s = self._system("小鲸")
        assert "自称：小鲸。" in s
        assert "自称：女仆" not in s

    def test_fused_prompt_falls_back_to_wo(self):
        s = self._system("")
        assert "自称：我。" in s


# ---------------------------------------------------------------------------
# ⑤ / ⑦ 全树扫描：残留清理 + 授权边界
# ---------------------------------------------------------------------------
class TestTreeScan:
    def test_no_self_maid_residue(self):
        patterns = [
            "自称女仆", "自称「女仆」", "自称：女仆",
            "自称「本喵」", "自称「本小姐」", "自称「本鲸」",
        ]
        hits = []
        for p in _iter_source_files():
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for pat in patterns:
                if pat in text:
                    hits.append((str(p.relative_to(ROOT)), pat))
        assert hits == [], f"自称残留未清零: {hits}"

    def test_address_self_default_not_maid(self):
        assert AppConfig().persona_address_self != "女仆"
        assert PersonaConfig().address_self != "女仆"

    def test_no_mingyue_authorization_leak(self):
        hits = []
        for p in _iter_source_files():
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "溟月" in text:
                hits.append(str(p.relative_to(ROOT)))
        assert hits == [], f"授权边界：源树出现『溟月』字样: {hits}"

    def test_product_name_intact(self):
        """产品名"码铃"不变；旧品牌口号"女仆编程师 — 您的专属"已除。"""
        assert "女仆编程师 — 您的专属 AI 编程助手" not in ROLE_PRESETS["温柔女仆"]["system_prompt"]
        about = (ROOT / "gui" / "pages" / "page_about.py").read_text(encoding="utf-8")
        assert "码铃 — 您的专属 AI 编程助手" in about
        assert "女仆编程师 — 您的专属 AI 编程助手" not in about
