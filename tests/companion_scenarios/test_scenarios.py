# -*- coding: utf-8 -*-
"""陪伴质量剧本套件 —— mock runner（v1.6 P1-2 / D-V16-09）。

- 剧本：tests/companion_scenarios/scenarios/*.json（18 个，覆盖 8 大类 +
  设计 §2.9 增补：意图五态/误判落默认、反馈三键三路径、7 天去重/14 天静默、
  免打扰静默、记忆删除即遗忘、反套话诚实）；
- 跑的是完整链：session + memory + 意图路由 + 主动策略（mock API，断言
  system 注入与行为约束），零网络零 Qt 交互（Qt 仅 offscreen 冒烟）；
- 每个剧本结束后做 R-A 红线词扫描（全局词表 + 剧本自定义词）；
- 隔离：MemoryManager / ChatSession 全部落 tmp_path，绝不读写真实 ~/.maid_coder。

用法：
    pytest tests/companion_scenarios/test_scenarios.py -v
真实档手工脚本见同目录 run_real_check.py。
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from memory import MemoryManager  # noqa: E402

SCEN_DIR = Path(__file__).resolve().parent / "scenarios"
SCENARIO_PATHS = sorted(SCEN_DIR.glob("*.json"))

# R-A 全局红线词（「无焦虑」：不出现筹码/胜率/倒数/断签/打卡/进度/第N次类表述）
GLOBAL_REDLINE_WORDS = ["筹码", "胜率", "倒数", "断签", "打卡", "进度"]
GLOBAL_REDLINE_RES = [re.compile(r"第\d+次"), re.compile(r"连续第\d+")]


# ---------------------------------------------------------------------------
# 剧本环境
# ---------------------------------------------------------------------------
class ScenarioEnv:
    """一个剧本一份环境：memory / session / 输出暂存。"""

    _MISSING = object()

    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.memory = MemoryManager(filepath=str(tmp_path / "memory.json"))
        self.session = None
        self.last_output = ScenarioEnv._MISSING
        self.outputs = []  # 进入模型可见语境的文本（红线扫描对象）

    def _set_out(self, value):
        self.last_output = value
        return value

    def _require_session(self):
        assert self.session is not None, "本步前必须先 session_init"
        return self.session

    def _find_topic(self, subject):
        for t in self.memory._data["topics"]["active"]:
            if t.get("subject") == subject:
                return t
        for t in self.memory._data["topics"]["archived"]:
            if t.get("subject") == subject:
                return t
        raise AssertionError(f"话题不存在: {subject}")

    # -- 动作实现 -----------------------------------------------------------
    def act_session_init(self, args):
        from session import ChatSession
        cfg = MagicMock()
        cfg.max_history_rounds = int(args.get("rounds", 3))
        cfg.summary_interval = 5
        cfg.workspace = str(self.tmp)
        cfg.snippets_file = str(self.tmp / "s.json")
        cfg.todos_file = str(self.tmp / "t.json")
        cfg.code_exec_timeout = 5
        cfg.web_search_max_results = 3
        cfg.kb_index_file = str(self.tmp / "kb.json")
        cfg.plugins_dir = str(self.tmp / "plugins")
        cfg.persona_role = "maid"
        cfg.persona_title = "码铃"
        cfg.persona_personality = "温柔"
        cfg.persona_address_user = "主人"
        cfg.persona_address_self = "我"
        cfg.multi_enabled = False
        cfg.output_speed = "fast"
        cfg.stream_mode = False
        cfg.output_show_token_usage = False
        cfg.output_debug = False
        cfg.web_search_enabled = False
        cfg.sensitive_info_scan = False
        cfg.code_exec_enabled = False
        self.session = ChatSession(cfg, MagicMock(), MagicMock())
        return self._set_out(None)

    def act_rounds(self, args):
        s = self._require_session()
        n = int(args.get("n", 1))
        for i in range(n):
            s.add_message("user", f"u{i}")
            s.add_message("assistant", f"a{i}")
        return self._set_out(f"{n} rounds")

    def act_history_first_role(self, args):
        return self._set_out(self._require_session().history[0]["role"])

    def act_history_last_role(self, args):
        return self._set_out(self._require_session().history[-1]["role"])

    def act_role_switch(self, args):
        s = self._require_session()
        s.notify_role_switch(args["role_name"])
        boundary = [m for m in s.history
                    if m.get("role") == "system"
                    and str(m.get("content", "")).startswith("【角色切换】")]
        assert boundary, "角色切换后必须存在边界消息"
        text = boundary[-1]["content"]
        self.outputs.append(text)
        return self._set_out(text)

    def act_set_preference(self, args):
        self.memory.set_preference(args["key"], args["value"],
                                   args.get("source", "manual"))
        return self._set_out(None)

    def act_delete_preference(self, args):
        return self._set_out(self.memory.delete_preference(args["key"]))

    def act_get_preference(self, args):
        return self._set_out(self.memory.get_preference(args["key"]))

    def act_add_topic(self, args):
        self.memory.add_topic(args["subject"], args.get("status", "ongoing"),
                              args.get("source", "manual"))
        return self._set_out(None)

    def act_backdate_topic(self, args):
        t = self._find_topic(args["subject"])
        t["last_mentioned"] = (datetime.now() -
                               timedelta(hours=float(args["hours"]))).isoformat()
        self.memory._save()
        return self._set_out(None)

    def act_mute_topic(self, args):
        t = self._find_topic(args["subject"])
        t["followup_muted_until"] = (datetime.now() +
                                     timedelta(days=float(args["days"]))).isoformat()
        self.memory._save()
        return self._set_out(None)

    def act_complete_topic(self, args):
        return self._set_out(self.memory.complete_topic(args["subject"]))

    def act_forget_topic(self, args):
        return self._set_out(self.memory.forget_topic(args["subject"]))

    def act_delete_topic_forever(self, args):
        return self._set_out(self.memory.delete_topic_forever(args["subject"]))

    def act_pick_followup(self, args):
        hit = self.memory.pick_topic_followup(args.get("min_hours", 1),
                                              args.get("max_hours", 72))
        if hit:
            self.outputs.append(hit.get("text", ""))
        return self._set_out(hit)

    def act_build_followup(self, args):
        text = self.memory.build_topic_followup(args.get("min_hours", 1),
                                                args.get("max_hours", 72))
        if text:
            self.outputs.append(text)
        return self._set_out(text)

    def act_feedback(self, args):
        return self._set_out(self.memory.record_followup_feedback(
            args["subject"], args["feedback"]))

    def act_score_min(self, args):
        t = self._find_topic(args["subject"])
        return self._set_out(int(t.get("followup_score") or 0) >= int(args["n"]))

    def act_memory_context(self, args):
        text = self.memory.build_memory_context(max_chars=int(args.get("max_chars", 300)))
        self.outputs.append(text or "")
        return self._set_out(text)

    def act_extract_dialogue(self, args):
        extracted = self.memory.extract_from_dialogue(args.get("user", ""),
                                                      args.get("assistant", ""))
        return self._set_out("；".join(extracted))

    def act_detect_emotion(self, args):
        return self._set_out(self.memory.detect_emotion(args["text"]))

    def act_intent(self, args):
        from gui.intent import classify_intent
        return self._set_out(classify_intent(args["text"]))

    def act_intent_hint(self, args):
        from gui.intent import INTENT_HINTS
        text = INTENT_HINTS.get(args["state"], "")
        self.outputs.append(text)
        return self._set_out(text)

    def act_policy(self, args):
        from gui.proactive_scheduler import PolicyState, ProactiveConfig, ProactivePolicy
        cfg = ProactiveConfig(**{k: v for k, v in (args.get("cfg") or {}).items()})
        st_kwargs = {}
        for k, v in (args.get("st") or {}).items():
            if k in ("now", "last_user_activity_at", "last_proactive_at",
                     "last_chat_event_at", "last_agent_done_at",
                     "external_cooldown_until"):
                st_kwargs[k] = datetime.fromisoformat(v) if v else None
            else:
                st_kwargs[k] = v
        st = PolicyState(**st_kwargs)
        allow, scene, reason = ProactivePolicy.decision(cfg, st)
        return self._set_out({"allow": allow, "scene": scene, "reason": reason})

    def act_contentful_line(self, args):
        from greeting import build_contentful_line
        hit = build_contentful_line(self.memory, None)
        if hit:
            self.outputs.append(str(hit.get("text", "")))
        return self._set_out(hit)

    def act_is_source_muted(self, args):
        return self._set_out(self.memory.is_source_muted(args["key"]))

    def act_active_topics_not_contains(self, args):
        subs = {t.get("subject") for t in self.memory.get_active_topics()}
        return self._set_out(args["subject"] not in subs)

    def act_archived_topics_contains(self, args):
        subs = {t.get("subject") for t in self.memory.get_archived_topics()}
        return self._set_out(args["subject"] in subs)

    def act_anti_fluff(self, args):
        """真链冒烟：ChatService（FakeCtx）发送 → 捕获请求副本 → 断言注入。"""
        from gui.qt_compat import QApplication
        _ = QApplication.instance() or QApplication([])
        import gui.chat_service as cs_mod
        from gui.chat_service import ChatService, ANTI_FLUFF_INJECTION

        class _Inner:
            def __init__(self):
                self.history = [{"role": "system", "content": "SYS"}]
                self.current_system = "SYS"
                self.context_trimmed = False

            def add_message(self, role, content=None, **kw):
                msg = {"role": role, "content": content}
                msg.update(kw)
                self.history.append(msg)

            @property
            def inner(self):
                return self

        class _Cfg:
            api_provider = "deepseek"
            api_key = "sk-test"  # 非 demo
            chat_intent_mode = "auto"
            web_search_enabled_gui = False
            stream_mode = True
            temperature = 0.7
            agent_anti_hallucination_inject = bool(args.get("switch", True))

        class _Ctx:
            def __init__(self):
                self.config = _Cfg()
                self.session = _Inner()
                self.api = MagicMock()

        class _AnyCall:
            def __getattr__(self, name):
                return self

            def __call__(self, *a, **k):
                return None

        class _Worker:
            captured = {}

            def __init__(self, api, messages, task_config, app_ctx,
                         on_session_used=None, expr_filter=False):
                type(self).captured = {"messages": messages}

            def __getattr__(self, name):
                # 信号替身：ChatService 会 connect 一串 worker 信号（offscreen 无所谓）
                return _AnyCall()

        orig = cs_mod.ApiWorker
        cs_mod.ApiWorker = _Worker
        try:
            svc = ChatService(_Ctx())
            sess = svc._app_ctx.session
            sess.context_trimmed = bool(args.get("trim"))
            svc.send_message("继续说说刚才那个话题", suppress_echo=True)
        finally:
            cs_mod.ApiWorker = orig
        msgs = _Worker.captured.get("messages") or []
        hit = any(ANTI_FLUFF_INJECTION[:10] in str(m.get("content", ""))
                  for m in msgs if m.get("role") == "system")
        return self._set_out({"injection": hit})


ACTIONS = {name[4:]: getattr(ScenarioEnv, name)
           for name in dir(ScenarioEnv) if name.startswith("act_")}


# ---------------------------------------------------------------------------
# 断言求值
# ---------------------------------------------------------------------------
def _as_list(v):
    return v if isinstance(v, list) else [v]


def _out_str(env):
    out = env.last_output
    if isinstance(out, str):
        return out
    return json.dumps(out, ensure_ascii=False, default=str)


def check_expect(env, expect, where):
    if not expect:
        return
    out = env.last_output

    if "out_equals" in expect:
        assert out == expect["out_equals"], f"{where}: 期望 {expect['out_equals']!r}，实得 {out!r}"
    if expect.get("out_is_null"):
        assert out is None, f"{where}: 期望为空，实得 {out!r}"
    if expect.get("out_not_null"):
        assert out is not None, f"{where}: 期望非空，实得 None"
    if "out_contains" in expect:
        s = _out_str(env)
        for sub in _as_list(expect["out_contains"]):
            assert sub in s, f"{where}: 输出应包含 {sub!r}，实际 {s!r}"
    if "out_not_contains" in expect:
        s = _out_str(env)
        for sub in _as_list(expect["out_not_contains"]):
            assert sub not in s, f"{where}: 输出不应包含 {sub!r}，实际 {s!r}"
    if "pref" in expect:
        key = expect["pref"]["key"]
        val = expect["pref"].get("value")
        got = env.memory.get_preference(key)
        if val is None:
            assert got is None, f"{where}: 偏好 {key} 应已删除，实得 {got!r}"
        else:
            assert got == val, f"{where}: 偏好 {key} 期望 {val!r}，实得 {got!r}"
    if "history_max_len" in expect:
        n = len(env.session.history)
        assert n <= expect["history_max_len"], \
            f"{where}: history 长度 {n} 应 ≤ {expect['history_max_len']}"
    if "history_min_len" in expect:
        n = len(env.session.history)
        assert n >= expect["history_min_len"], \
            f"{where}: history 长度 {n} 应 ≥ {expect['history_min_len']}"
    if "trimmed" in expect:
        got = env.session.context_trimmed
        assert got is expect["trimmed"], f"{where}: context_trimmed 应为 {expect['trimmed']}"
    if "history_contains" in expect:
        blob = "".join(str(m.get("content", "")) for m in env.session.history)
        for sub in _as_list(expect["history_contains"]):
            assert sub in blob, f"{where}: history 应包含 {sub!r}"
    if "history_not_contains" in expect:
        blob = "".join(str(m.get("content", "")) for m in env.session.history)
        for sub in _as_list(expect["history_not_contains"]):
            assert sub not in blob, f"{where}: history 不应包含 {sub!r}"
    if "history_last_prefix" in expect:
        last = str(env.session.history[-1].get("content", ""))
        assert last.startswith(expect["history_last_prefix"]), \
            f"{where}: 末条应以 {expect['history_last_prefix']!r} 开头，实际 {last[:30]!r}"
    if "boundary_count" in expect:
        n = sum(1 for m in env.session.history
                if m.get("role") == "system"
                and str(m.get("content", "")).startswith("【角色切换】"))
        assert n == expect["boundary_count"], \
            f"{where}: 边界消息应恰 {expect['boundary_count']} 条，实得 {n}"
    if "injection" in expect:
        assert isinstance(out, dict) and "injection" in out, \
            f"{where}: 上一步应产出 injection 结果，实得 {out!r}"
        assert out["injection"] is expect["injection"], \
            f"{where}: 注入断言期望 {expect['injection']}，实得 {out['injection']}"
    if "decision" in expect:
        assert isinstance(out, dict) and "allow" in out, \
            f"{where}: 上一步应产出 policy decision，实得 {out!r}"
        d = expect["decision"]
        if "allow" in d:
            assert out["allow"] is d["allow"], f"{where}: allow 期望 {d['allow']}，实得 {out['allow']}"
        if "scene" in d:
            assert out["scene"] == d["scene"], f"{where}: scene 期望 {d['scene']!r}，实得 {out['scene']!r}"
        if "reason" in d:
            assert out["reason"] == d["reason"], f"{where}: reason 期望 {d['reason']!r}，实得 {out['reason']!r}"
        if "reason_contains" in d:
            assert str(out["reason"] or "").startswith(d["reason_contains"]) or \
                d["reason_contains"] in str(out["reason"]), \
                f"{where}: reason 应含 {d['reason_contains']!r}，实得 {out['reason']!r}"
        if "reason_not" in d:
            assert out["reason"] != d["reason_not"], \
                f"{where}: reason 不应为 {d['reason_not']!r}，实得 {out['reason']!r}"
    if "active_topics_not_contains" in expect or "archived_topics_contains" in expect:
        pass  # 由动作返回 bool，走 out_equals 断言
    if "emotion" in expect:
        assert out == expect["emotion"], f"{where}: emotion 期望 {expect['emotion']!r}，实得 {out!r}"


def check_redlines(env, scen):
    words = list(GLOBAL_REDLINE_WORDS) + list(scen.get("redline_words") or [])
    for out in env.outputs:
        for w in words:
            assert w not in out, f"[{scen['id']}] 红线词 {w!r} 出现在输出: {out[:60]!r}"
        for pat in GLOBAL_REDLINE_RES:
            m = pat.search(out)
            assert m is None, f"[{scen['id']}] 红线表述 {m.group(0)!r} 出现在输出: {out[:60]!r}"


# ---------------------------------------------------------------------------
# pytest 入口
# ---------------------------------------------------------------------------
@pytest.fixture
def env(tmp_path):
    return ScenarioEnv(tmp_path)


@pytest.mark.parametrize("scen_path", SCENARIO_PATHS, ids=[p.stem for p in SCENARIO_PATHS])
def test_scenario(scen_path, env):
    scen = json.loads(scen_path.read_text(encoding="utf-8"))
    assert scen.get("mode") == "mock", "mock 套件只跑 mode=mock 剧本"
    assert scen.get("id") and scen.get("title"), "剧本缺 id/title"
    steps = scen.get("steps") or []
    assert steps, f"[{scen['id']}] 剧本无步骤"
    for i, step in enumerate(steps):
        action = step.get("action")
        assert action in ACTIONS, f"[{scen['id']}#{i}] 未知动作 {action!r}"
        where = f"{scen['id']}#{i}({action})"
        getattr(env, f"act_{action}")(step.get("args") or {})
        try:
            check_expect(env, step.get("expect") or {}, where)
        except AssertionError as e:
            pytest.fail(str(e), pytrace=False)
    check_redlines(env, scen)


def test_scenario_count_at_least_15():
    assert len(SCENARIO_PATHS) >= 15, f"剧本数应 ≥15，实得 {len(SCENARIO_PATHS)}"


def test_scenario_files_valid_schema():
    for p in SCENARIO_PATHS:
        scen = json.loads(p.read_text(encoding="utf-8"))
        for k in ("id", "title", "targets", "mode", "steps", "redline_words"):
            assert k in scen, f"{p.name} 缺字段 {k}"
        for i, step in enumerate(scen["steps"]):
            assert "action" in step, f"{p.name}#{i} 缺 action"
            assert step["action"] in ACTIONS, f"{p.name}#{i} 未知动作 {step['action']}"
