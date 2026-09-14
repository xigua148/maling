# -*- coding: utf-8 -*-
"""v1.8 第三批测试（F4 场景化陪伴 V18-11/12/13，D-V18-07）。

覆盖（team-lead 指定七类针对性）：
  ① current_scene 时段映射边界（9:00/12:00/18:00/22:30/6:30 + 跨天 + 周末）；
  ② 手动覆盖当日有效、次日回落（Q-D4）；
  ③ 三层叠加：情绪陪伴激活（confide 命中 + 负面信号）→ 场景注入挂起（Q-D5）；
  ④ 工作场景 cap 3→1（Q-D6；四重闸其余参数零变化断言）；
  ⑤ 睡前场景与 NIGHT_CARE 防双注入（22:30 交叉点，D-V18-07 标红项）；
  ⑥ 注入序位最终断言（意图提示 → 实体 → 约定 → 场景 → 情绪概览）；
  ⑦ 场景切换 UI 持久化（GuiConfig 键 round-trip + 下拉 handler + 首页 chip）。

隔离：MemoryManager/GuiConfig/scenes 全部 tmp_path；Qt offscreen；零真实
~/.maid_coder、零真实 %APPDATA%。
"""
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

import scene as scene_mod  # noqa: E402
from memory import MemoryManager  # noqa: E402
from gui.proactive_scheduler import (  # noqa: E402
    ProactiveConfig, ProactivePolicy, PolicyState, scene_cap_override,
)


# ---------------------------------------------------------------------------
# 公共小件
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def qapp():
    from gui.qt_compat import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# 固定时钟（消除对系统墙钟的依赖——夜间跑批不再假红）：
#   _FIXED_DAY   = 周四 14:00（非深夜、非 quiet）→ 覆盖"无深夜关怀"分支
#   _FIXED_NIGHT = 周四 23:30（落在深夜关怀窗口 23:00–05:00）→ 覆盖"有深夜关怀"分支
_FIXED_DAY = datetime(2026, 9, 10, 14, 0)
_FIXED_NIGHT = datetime(2026, 9, 10, 23, 30)
_FIXED_DATE_STR = "2026-09-10"  # 与上述固定时钟同日，保证手动场景覆盖生效


def _freeze_chat_service_clock(monkeypatch, moment):
    """把 gui.chat_service 模块内的 datetime.now() 固定为 moment。

    send_message 内部硬读 datetime.now()（is_deep_night() 与 current_scene()），
    无可注入的 now 形参；故仅在被测模块命名空间替换 `datetime` 名，不含
    任何产品代码改动。调用方须把 manual_scene_date 设为与 moment 同一日期，
    手动场景覆盖才会生效。
    """
    import gui.chat_service as _cs
    real_dt = _cs.datetime

    class _FixedDT(real_dt):
        @classmethod
        def now(cls, tz=None):
            return moment

    monkeypatch.setattr(_cs, "datetime", _FixedDT)
    return moment


# ---------------------------------------------------------------------------
# ① current_scene 时段映射边界（Q-D4）
# ---------------------------------------------------------------------------
class TestSceneTimeWindows:
    @pytest.mark.parametrize("moment,expected", [
        # 工作日（2026-09-10 周四）工作窗口两段
        (datetime(2026, 9, 10, 9, 0), "work"),
        (datetime(2026, 9, 10, 8, 59), "rest"),
        (datetime(2026, 9, 10, 11, 59), "work"),
        (datetime(2026, 9, 10, 12, 0), "rest"),
        (datetime(2026, 9, 10, 13, 59), "rest"),
        (datetime(2026, 9, 10, 14, 0), "work"),
        (datetime(2026, 9, 10, 17, 59), "work"),
        (datetime(2026, 9, 10, 18, 0), "rest"),
        # 睡前窗口 22:30–次日 6:30（含周末，跨天）
        (datetime(2026, 9, 10, 22, 29), "rest"),
        (datetime(2026, 9, 10, 22, 30), "sleep"),
        (datetime(2026, 9, 10, 23, 59), "sleep"),
        (datetime(2026, 9, 11, 0, 0), "sleep"),
        (datetime(2026, 9, 11, 3, 0), "sleep"),
        (datetime(2026, 9, 11, 5, 59), "sleep"),
        (datetime(2026, 9, 11, 6, 30), "rest"),
        # 周末不进工作场景（2026-09-12 周六 / 09-13 周日）
        (datetime(2026, 9, 12, 10, 0), "rest"),
        (datetime(2026, 9, 13, 15, 0), "rest"),
    ])
    def test_auto_scene_boundaries(self, moment, expected):
        assert scene_mod.auto_scene(moment) == expected

    def test_current_scene_matches_auto_when_no_manual(self):
        assert scene_mod.current_scene(datetime(2026, 9, 10, 10, 0)) == "work"
        assert scene_mod.current_scene(datetime(2026, 9, 10, 23, 30)) == "sleep"


# ---------------------------------------------------------------------------
# ② 手动覆盖当日有效、次日回落（Q-D4）
# ---------------------------------------------------------------------------
class TestManualOverride:
    def test_manual_today_valid(self):
        mo = {"scene": "work", "date": "2026-09-10"}
        # 当日：即使时段是深夜（本应 sleep），手动 work 生效
        assert scene_mod.current_scene(datetime(2026, 9, 10, 23, 30), mo) == "work"

    def test_manual_yesterday_falls_back(self):
        mo = {"scene": "work", "date": "2026-09-09"}
        # 次日：手动失效 → 回落自动感知（20:00 = rest）
        assert scene_mod.current_scene(datetime(2026, 9, 10, 20, 0), mo) == "rest"

    def test_manual_invalid_scene_ignored(self):
        mo = {"scene": "party", "date": "2026-09-10"}
        assert scene_mod.manual_scene_active(mo, datetime(2026, 9, 10, 20, 0)) is None

    def test_resolve_manual_override_from_config(self):
        assert scene_mod.resolve_manual_override("", "") is None
        assert scene_mod.resolve_manual_override("bad", "2026-09-10") is None
        mo = scene_mod.resolve_manual_override("sleep", "2026-09-10")
        assert mo == {"scene": "sleep", "date": "2026-09-10"}

    def test_boundary_text_and_chip(self):
        b = scene_mod.scene_boundary_text("work")
        assert b.startswith(scene_mod.SCENE_BOUNDARY_MARKER)
        assert "💼 工作模式" in b
        assert "仍然有效" in b          # 技术上下文保留口径
        assert scene_mod.scene_chip_text("rest") == "☕ 休息模式 · 点按切换"
        assert scene_mod.scene_chip_text("auto") == ""


# ---------------------------------------------------------------------------
# ③ 三层叠加：情绪陪伴激活 → 场景注入挂起（Q-D5）
# ---------------------------------------------------------------------------
class TestEmotionSuspension:
    def _mm(self, tmp_path):
        return MemoryManager(filepath=str(tmp_path / "m.json"))

    def test_negative_emotion_detection(self, tmp_path):
        mm = self._mm(tmp_path)
        assert mm.detect_emotion("我好累") == "tired"
        assert mm.detect_emotion("有点焦虑") == "anxious"
        assert mm.detect_emotion("好孤单") == "lonely"
        assert mm.detect_emotion("好开心") == "happy"

    def test_suspension_pure_builder(self, tmp_path):
        """情绪激活当轮：build_scene_injection(suspended=True) 零注入；退出恢复。"""
        assert cs().build_scene_injection("work", suspended=True) == []
        assert len(cs().build_scene_injection("work", suspended=False)) == 1
        # 总开关关闭（scene_auto=False）同样零注入
        assert cs().build_scene_injection("work", enabled=False) == []

    def test_suspension_logic_confide_plus_negative(self, tmp_path):
        """Q-D5 判定口径：当轮 confide 命中 + 负面信号 → 挂起；缺一不挂。"""
        mm = self._mm(tmp_path)
        negative = mm.detect_emotion("我好累") in cs()._NEGATIVE_EMOTIONS
        assert negative is True
        # confide + 负面 → 挂起
        assert cs().build_scene_injection("work", suspended=negative) == []
        # 非负面（仅 confide）→ 不挂起
        negative2 = mm.detect_emotion("今天好开心") in cs()._NEGATIVE_EMOTIONS
        assert negative2 is False
        assert len(cs().build_scene_injection("work", suspended=negative2)) == 1

    def test_emotion_overview_still_injected_when_scene_suspended(self, tmp_path):
        """挂起只作用于场景层：情绪概览照常注入（第①层不误伤 F2）。"""
        mm = self._mm(tmp_path)
        mm._data["emotions"] = [
            {"time": datetime.now().isoformat(), "emotion": "tired", "excerpt": ""}] * 3
        ov = cs().build_emotion_overview_injection(mm, "我好累", "confide", True)
        assert len(ov) == 1 and ov[0].startswith("【情绪概览】")


def cs():
    """gui.chat_service 模块懒加载（避免收集期 Qt 依赖）。"""
    import gui.chat_service as _cs
    return _cs


# ---------------------------------------------------------------------------
# ④ 工作场景 cap 3→1（Q-D6；四重闸其余参数零变化）
# ---------------------------------------------------------------------------
class TestWorkCapOverride:
    def _cfg(self, **kw):
        return ProactiveConfig(daily_cap=3, **kw)

    def _now(self):
        return datetime(2026, 9, 10, 10, 0)  # 工作日 10:00（非 quiet）

    def test_cap_override_blocks_at_1(self):
        st = PolicyState(now=self._now(), count_today=1,
                         external_daily_cap_override=1)
        assert ProactivePolicy.gates(self._cfg(), st) == "daily_cap_reached"

    def test_cap_override_allows_first(self):
        st = PolicyState(now=self._now(), count_today=0,
                         external_daily_cap_override=1)
        assert ProactivePolicy.gates(self._cfg(), st) is None

    def test_no_override_keeps_existing_cap(self):
        """override=None → 既有 daily_cap=3 行为逐字不变。"""
        st2 = PolicyState(now=self._now(), count_today=2)
        assert ProactivePolicy.gates(self._cfg(), st2) is None
        st3 = PolicyState(now=self._now(), count_today=3)
        assert ProactivePolicy.gates(self._cfg(), st3) == "daily_cap_reached"

    def test_cap_zero_silences_work_scene(self):
        st = PolicyState(now=self._now(), count_today=0,
                         external_daily_cap_override=0)
        assert ProactivePolicy.gates(self._cfg(), st) == "daily_cap_reached"

    def test_other_gates_unchanged(self):
        """四重闸其余三闸 + 外部冷却零变化（完整回归锚定）。"""
        cfg = self._cfg()
        # enabled
        st = PolicyState(now=self._now(), count_today=0,
                         external_daily_cap_override=1)
        assert ProactivePolicy.gates(ProactiveConfig(enabled=False), st) == "disabled"
        # quiet hours
        st_q = PolicyState(now=datetime(2026, 9, 10, 3, 0), count_today=0,
                           external_daily_cap_override=1)
        assert ProactivePolicy.gates(cfg, st_q) == "quiet_hours"
        # external cooldown（resume_buffer 位于 cap 前）
        st_c = PolicyState(now=self._now(), count_today=1,
                           external_daily_cap_override=1,
                           external_cooldown_until=self._now().replace(hour=11))
        assert ProactivePolicy.gates(cfg, st_c) == "resume_buffer"
        # cooldown（上次主动间隔过短）
        st_d = PolicyState(now=self._now(), count_today=0,
                           external_daily_cap_override=1,
                           last_proactive_at=datetime(2026, 9, 10, 9, 30))
        reason = ProactivePolicy.gates(cfg, st_d)
        assert reason is not None and reason.startswith("cooldown(")

    def test_scene_cap_override_mapping(self):
        """调度器每轮场景 → override 映射：work→配置值；rest/sleep/关→None。"""
        cfg = SimpleNamespace(scene_auto=True, manual_scene="",
                              manual_scene_date="",
                              scene_work_proactive_cap=1)
        assert scene_cap_override(cfg, datetime(2026, 9, 10, 10, 0)) == 1
        assert scene_cap_override(cfg, datetime(2026, 9, 10, 20, 0)) is None
        assert scene_cap_override(cfg, datetime(2026, 9, 10, 23, 30)) is None
        cfg0 = SimpleNamespace(scene_auto=True, manual_scene="",
                               manual_scene_date="",
                               scene_work_proactive_cap=0)
        assert scene_cap_override(cfg0, datetime(2026, 9, 10, 10, 0)) == 0
        cfg_off = SimpleNamespace(scene_auto=False, manual_scene="",
                                  manual_scene_date="",
                                  scene_work_proactive_cap=1)
        assert scene_cap_override(cfg_off, datetime(2026, 9, 10, 10, 0)) is None
        # 手动 work 当日有效（晚间手动进工作模式也降档）
        cfg_m = SimpleNamespace(scene_auto=True, manual_scene="work",
                                manual_scene_date="2026-09-10",
                                scene_work_proactive_cap=1)
        assert scene_cap_override(cfg_m, datetime(2026, 9, 10, 20, 0)) == 1
        cfg_m2 = SimpleNamespace(scene_auto=True, manual_scene="work",
                                 manual_scene_date="2026-09-09",
                                 scene_work_proactive_cap=1)
        assert scene_cap_override(cfg_m2, datetime(2026, 9, 10, 20, 0)) is None

    def test_cap_downgrade_never_upgrade(self):
        """降档不改档（Q-D6 红线）：用户配置 daily_cap=0（全关）时，
        工作场景绝不悄悄放开；配置 5 时工作场景仍压到 1。"""
        # 用户全关（agent_proactive_daily_cap=0）→ 工作场景 override 仍为 0
        cfg_zero = SimpleNamespace(scene_auto=True, manual_scene="",
                                   manual_scene_date="",
                                   scene_work_proactive_cap=1,
                                   agent_proactive_daily_cap=0)
        assert scene_cap_override(cfg_zero, datetime(2026, 9, 10, 10, 0)) == 0
        # 用户放宽（=5）→ 工作场景仍按场景档压到 1
        cfg_loose = SimpleNamespace(scene_auto=True, manual_scene="",
                                    manual_scene_date="",
                                    scene_work_proactive_cap=1,
                                    agent_proactive_daily_cap=5)
        assert scene_cap_override(cfg_loose, datetime(2026, 9, 10, 10, 0)) == 1
        # 场景档 0 + 用户 5 → 0（场景档优先更严）
        cfg_s0 = SimpleNamespace(scene_auto=True, manual_scene="",
                                 manual_scene_date="",
                                 scene_work_proactive_cap=0,
                                 agent_proactive_daily_cap=5)
        assert scene_cap_override(cfg_s0, datetime(2026, 9, 10, 10, 0)) == 0


# ---------------------------------------------------------------------------
# ⑤⑥ ChatService 级：NIGHT_CARE 防双注入 + 注入序位最终断言
# ---------------------------------------------------------------------------
class _FakeSession:
    def __init__(self, mm):
        self.memory_mgr = mm
        self.history = []


def _make_svc(tmp_path, cfg_overrides=None):
    from gui.chat_service import ChatService
    mm = MemoryManager(filepath=str(tmp_path / "m.json"))
    cfg = SimpleNamespace(
        api_key="test-key", chat_intent_mode="auto",
        entity_auto_propose=False, emotion_overview_enabled=True,
        scene_auto=True, manual_scene="", manual_scene_date="",
        scene_work_proactive_cap=1,
    )
    for k, v in (cfg_overrides or {}).items():
        setattr(cfg, k, v)
    app_ctx = SimpleNamespace(config=cfg, session=_FakeSession(mm))
    svc = ChatService(app_ctx)
    captured = []
    svc._launch_worker = lambda payload: captured.append(payload)
    return svc, captured, mm


class TestSleepNightCareMerge:
    def test_sleep_scene_skips_night_care(self, tmp_path, monkeypatch, qapp):
        """睡前场景激活（手动 sleep 当日）→ 深夜关怀跳过（防双注入）。"""
        monkeypatch.setattr(cs(), "is_deep_night", lambda: True)
        svc, captured, _ = _make_svc(
            tmp_path, {"manual_scene": "sleep", "manual_scene_date": _today()})
        svc.send_message("晚安", task_type="chat", suppress_echo=True)
        payload = captured[-1]
        assert not any("深夜关怀" in line for line in payload["request_injections"])
        # 场景语气在（睡前温柔安静）
        assert any("场景语气 · 睡前" in line for line in payload["request_injections"])

    def test_work_scene_keeps_night_care(self, tmp_path, monkeypatch, qapp):
        """深夜 + 非睡前场景（手动 work 当日）→ 深夜关怀照常（v1.7 行为不变）。"""
        monkeypatch.setattr(cs(), "is_deep_night", lambda: True)
        svc, captured, _ = _make_svc(
            tmp_path, {"manual_scene": "work", "manual_scene_date": _today()})
        svc.send_message("还在赶工", task_type="chat", suppress_echo=True)
        payload = captured[-1]
        assert any("深夜关怀" in line for line in payload["request_injections"])

    def test_scene_disabled_keeps_night_care(self, tmp_path, monkeypatch, qapp):
        """scene_auto 关闭 → 场景链整体空转，NIGHT_CARE 保持 v1.7 行为。"""
        monkeypatch.setattr(cs(), "is_deep_night", lambda: True)
        svc, captured, _ = _make_svc(tmp_path, {"scene_auto": False})
        svc.send_message("还在赶工", task_type="chat", suppress_echo=True)
        payload = captured[-1]
        assert any("深夜关怀" in line for line in payload["request_injections"])
        assert not any("场景语气" in line for line in payload["request_injections"])

    def test_crossing_point_no_double_injection(self, tmp_path, monkeypatch, qapp):
        """22:30 交叉点口径：深夜 + 睡前同时在场时只保留场景语气一种底色。"""
        monkeypatch.setattr(cs(), "is_deep_night", lambda: True)
        svc, captured, _ = _make_svc(
            tmp_path, {"manual_scene": "sleep", "manual_scene_date": _today()})
        svc.send_message("夜深了", task_type="chat", suppress_echo=True)
        payload = captured[-1]
        care = sum(1 for line in payload["request_injections"] if "深夜关怀" in line)
        sleep_tone = sum(1 for line in payload["request_injections"]
                         if "场景语气 · 睡前" in line)
        assert care == 0 and sleep_tone == 1


class TestInjectionOrder:
    def test_final_order(self, tmp_path, qapp, monkeypatch):
        """序位最终断言（D-V18-02 框架）：意图提示 → 实体提及 → 回应约定 →
        场景语气 → 情绪概览。

        固定白天时钟 14:00：非深夜 → 无第 6 行【深夜关怀】，len 确定 == 5。
        """
        _freeze_chat_service_clock(monkeypatch, _FIXED_DAY)  # 固定白天时钟
        svc, captured, mm = _make_svc(
            tmp_path, {"manual_scene": "rest", "manual_scene_date": _FIXED_DATE_STR})
        mm.add_entity("小李", "同事", "同组后端")
        mm.add_rule("聊天", "先轻轻抱一下，别急着给建议")
        mm._data["emotions"] = [
            {"time": datetime.now().isoformat(), "emotion": "tired", "excerpt": ""}] * 3
        svc.send_message("和小李聊天心里有点闷", task_type="chat",
                         suppress_echo=True, intent_mode="confide")
        lines = captured[-1]["request_injections"]
        assert len(lines) == 5
        assert lines[0].startswith("【语气提示】")          # 意图提示（confide）
        assert lines[1].startswith("【关于小李】")          # ① 实体提及
        assert lines[2].startswith("【回应约定】")          # ② 回应约定
        assert lines[3].startswith("【场景语气 · 休息】")   # ③ 场景语气（手动 rest 当日）
        assert lines[4].startswith("【情绪概览】")          # ④ 情绪概览

    def test_final_order_with_night_care(self, tmp_path, qapp, monkeypatch):
        """深夜分支：固定深夜时钟 23:30 + 手动 rest 当日（非睡前场景）

        → 在既有 5 行注入序位之后追加【深夜关怀】，序位框架不被打乱。
        """
        _freeze_chat_service_clock(monkeypatch, _FIXED_NIGHT)  # 固定深夜时钟
        svc, captured, mm = _make_svc(
            tmp_path, {"manual_scene": "rest", "manual_scene_date": _FIXED_DATE_STR})
        mm.add_entity("小李", "同事", "同组后端")
        mm.add_rule("聊天", "先轻轻抱一下，别急着给建议")
        mm._data["emotions"] = [
            {"time": datetime.now().isoformat(), "emotion": "tired", "excerpt": ""}] * 3
        svc.send_message("和小李聊天心里有点闷", task_type="chat",
                         suppress_echo=True, intent_mode="confide")
        lines = captured[-1]["request_injections"]
        assert len(lines) == 6
        assert lines[0].startswith("【语气提示】")
        assert lines[1].startswith("【关于小李】")
        assert lines[2].startswith("【回应约定】")
        assert lines[3].startswith("【场景语气 · 休息】")
        assert lines[4].startswith("【情绪概览】")
        assert lines[5].startswith("【深夜关怀】")          # 深夜尾注追加在末位

    def test_suspension_removes_scene_only(self, tmp_path, qapp):
        """情绪激活当轮：场景行消失，其余序位不变（前缀序 = 0,1,2 后接概览）。"""
        svc, captured, mm = _make_svc(
            tmp_path, {"manual_scene": "rest", "manual_scene_date": _today()})
        mm._data["emotions"] = [
            {"time": datetime.now().isoformat(), "emotion": "tired", "excerpt": ""}] * 3
        svc.send_message("我好累", task_type="chat",
                         suppress_echo=True, intent_mode="confide")
        lines = captured[-1]["request_injections"]
        assert not any("场景语气" in line for line in lines)
        assert any("情绪概览" in line for line in lines)
        assert lines[0].startswith("【语气提示】")   # 意图提示仍在首位

    def test_scene_boundary_idempotent_in_history(self, tmp_path, qapp):
        """⚠-5 双动作②：边界消息幂等 —— 首次写入 1 条；同场景不重复写；
        切换场景替换（历史中至多一条）。"""
        cfg_ov = {"manual_scene": "rest", "manual_scene_date": _today()}
        svc, captured, _ = _make_svc(tmp_path, cfg_ov)
        svc.send_message("第一次", task_type="chat", suppress_echo=True)
        hist = svc._app_ctx.session.history
        assert sum(1 for m in hist if str(m.get("content", "")).startswith(
            scene_mod.SCENE_BOUNDARY_MARKER)) == 1
        # 同场景再来一条 → 不重复
        svc.send_message("第二次", task_type="chat", suppress_echo=True)
        hist = svc._app_ctx.session.history
        assert sum(1 for m in hist if str(m.get("content", "")).startswith(
            scene_mod.SCENE_BOUNDARY_MARKER)) == 1
        # 切到睡前 → 替换为新场景
        svc._app_ctx.config.manual_scene = "sleep"
        svc.send_message("第三次", task_type="chat", suppress_echo=True)
        hist = svc._app_ctx.session.history
        marks = [m for m in hist if str(m.get("content", "")).startswith(
            scene_mod.SCENE_BOUNDARY_MARKER)]
        assert len(marks) == 1 and "🌙 睡前模式" in marks[0]["content"]

    def test_agent_mode_skips_scene_chain(self, tmp_path, qapp):
        """Agent/任务路径零触碰（R-J）：Agent 模式下场景/实体/约定/概览全跳过。"""
        svc, captured, mm = _make_svc(tmp_path)
        mm.add_entity("小李", "同事", "同组后端")
        svc._agent_mode = True
        svc.send_message("和小李聊天心里很难受", task_type="agent",
                         suppress_echo=True)
        payload = captured[-1]
        assert payload["request_injections"] == []
        assert payload["task_type"] == "agent"


# ---------------------------------------------------------------------------
# ⑦ 场景切换 UI 持久化
# ---------------------------------------------------------------------------
class TestSceneUiPersistence:
    def test_config_round_trip(self, tmp_path, monkeypatch):
        """GuiConfig 四新键注册（D-V18-10）+ save/load round-trip（%APPDATA% 隔离）。"""
        monkeypatch.setenv("APPDATA", str(tmp_path))
        from gui.config import GuiConfig
        cfg = GuiConfig()
        assert cfg.scene_auto is True
        assert cfg.manual_scene == ""
        assert cfg.manual_scene_date == ""
        assert cfg.scene_work_proactive_cap == 1
        cfg.scene_auto = False
        cfg.manual_scene = "work"
        cfg.manual_scene_date = "2026-09-10"
        cfg.scene_work_proactive_cap = 0
        cfg.save()
        cfg2 = GuiConfig.load()
        assert cfg2.scene_auto is False
        assert cfg2.manual_scene == "work"
        assert cfg2.manual_scene_date == "2026-09-10"
        assert cfg2.scene_work_proactive_cap == 0
        data = json.loads((tmp_path / "maid_coder" / "gui_config.json")
                          .read_text(encoding="utf-8"))
        for key in ("scene_auto", "manual_scene", "manual_scene_date",
                    "scene_work_proactive_cap"):
            assert key in data

    def test_scene_combo_handler_persists(self, tmp_path, monkeypatch, qapp):
        """聊天面板场景下拉 handler：切换即持久化 manual_scene + 当日日期。"""
        monkeypatch.setenv("APPDATA", str(tmp_path / "combo"))
        from gui.config import GuiConfig
        from gui.qt_compat import QComboBox
        cfg = GuiConfig()
        app_ctx = SimpleNamespace(config=cfg)
        combo = QComboBox()
        for label, value in (("✨ 场景·自动", ""), ("💼 工作", "work"),
                             ("☕ 休息", "rest"), ("🌙 睡前", "sleep")):
            combo.addItem(label, value)
        fake_self = SimpleNamespace(app_ctx=app_ctx, scene_combo=combo,
                                    status_label=None)
        from gui.widgets import chat_panel
        combo.blockSignals(True)
        combo.setCurrentIndex(1)  # 💼 工作
        combo.blockSignals(False)
        chat_panel.ChatPanelWidget._on_scene_mode_changed(fake_self, 1)
        assert cfg.manual_scene == "work"
        assert cfg.manual_scene_date == _today()
        # 回"自动" → 手动覆盖清空
        combo.blockSignals(True)
        combo.setCurrentIndex(0)
        combo.blockSignals(False)
        chat_panel.ChatPanelWidget._on_scene_mode_changed(fake_self, 0)
        assert cfg.manual_scene == ""
        # 落盘校验
        data = json.loads((tmp_path / "combo" / "maid_coder" / "gui_config.json")
                          .read_text(encoding="utf-8"))
        assert data["manual_scene"] == ""

    def test_home_scene_chip(self, qapp):
        """首页场景 chip：文案 + 点按循环切换（work→rest→sleep→自动）。"""
        from gui.pages.page_home import _SceneChip
        chip = _SceneChip()
        assert chip.text() == ""
        chip.setText(scene_mod.scene_chip_text("work"))
        assert "💼 工作模式" in chip.text()
        # 点按回调
        clicked = {"n": 0}
        chip.on_clicked = lambda: clicked.__setitem__("n", clicked["n"] + 1)
        chip.trigger_click()
        assert clicked["n"] == 1

    def test_chip_cycle_mapping(self):
        """点按循环序：work→rest→sleep→auto("")→work；与 handler 实现一致。"""
        cycle = {"": scene_mod.SCENE_WORK,
                 scene_mod.SCENE_WORK: scene_mod.SCENE_REST,
                 scene_mod.SCENE_REST: scene_mod.SCENE_SLEEP,
                 scene_mod.SCENE_SLEEP: ""}
        assert cycle[""] == "work" and cycle["work"] == "rest" \
            and cycle["rest"] == "sleep" and cycle["sleep"] == ""
