"""tests/test_v22_service.py —— V22-06 酒馆服务层 · 断言（offscreen / 确定性 / LLM 用桩）。

覆盖 ``docs/design-v22.md`` 与本任务书对 ``gui/tavern/service.py``（**本域唯一 Qt 控制器**）的验收要点：

    * **生命周期**：新开一局 → 一拍 → 落盘 → 重新载入，状态与 ``transcript`` 一致；
    * **单写点**：持久化只经 ``store.save``（被写入路径集合 == ``["tavern.json"]``）；
    * **L4 只读态**：载入高版本档 → 不崩、可玩、**写入路径集合为空**、``save`` 被拒时优雅降级；
    * **★ ``"history"`` 段映射**：最终消息序列里**没有非法 role**（末段 history → user）；
    * **LLM 桩失败**（``None`` / 畸形 / 抛异常 / 超时）→ 一拍仍能完成、**世界状态不变**、
      ``resolution`` 键集齐全、**UI 无异常抛**；
    * **Q2 只读审计**：跑完整流程后，断言**未调用任何好感度 / 亲密写入 API**；
    * **不缓存全局派生值**：改 ``motion`` 档位 / 主题后，下一次取用反映新值；
    * **姓名规则**：``given_name`` 为空 → 显示「码铃」；非空 → 显示名字（**不得用** ``role.name``）。

全部用例：``QT_QPA_PLATFORM=offscreen``；LLM 一律用桩；不依赖墙钟；不写真实 ``~/.maid_coder``。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.qt_compat import QApplication  # noqa: E402

import gui.tavern.store as store_mod  # noqa: E402
from gui.tavern import model as m  # noqa: E402
from gui.tavern import service as svc_mod  # noqa: E402
from gui.tavern.service import (  # noqa: E402
    PRODUCT_NAME,
    SEGMENT_MESSAGE_ROLES,
    VALID_CHAT_ROLES,
    TavernService,
    local_narration,
    read_persona,
    render_chat_messages,
)

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Qt / 夹具
# ---------------------------------------------------------------------------

def _qapp() -> "QApplication":
    return QApplication.instance() or QApplication([])


def _content() -> dict:
    """最小内容包（覆盖 verbatim 解析所需的全部查询面；``scene_id=""`` 也已声明）。"""
    return {
        "book_id": "lantern",
        "node_ids": ["opening", "counter_photo"],
        "scene_ids": ["bar", "counter"],
        "reachable": {"": ["bar"], "bar": ["counter"], "counter": ["bar"]},
        "known_topics": {"": ["photo"], "counter": ["photo"]},
        "menu": {"": ["long_night"], "counter": ["long_night"]},
        "open_conditions": {"counter:drawer": True},
        "items": ["old_photo", "key"],
        "var_names": [],
        "aliases": {"长夜": "long_night", "旧照片": "old_photo"},
        "worldbook": {"title": "灯笼酒馆"},
        "chapters": [{"id": "ch1", "title": "灯笼还亮着"}],
        "quick_actions": [],
    }


@pytest.fixture
def patch_content(monkeypatch):
    """内容包解析（唯一入口）返回确定性 dict；随包世界书为空。"""
    monkeypatch.setattr(
        svc_mod.tavern_worldbook, "load_content",
        lambda pack_id="lantern", **kw: _content(),
    )
    monkeypatch.setattr(
        svc_mod.tavern_worldbook, "load_builtin_book",
        lambda book_id="lantern", **kw: svc_mod.tavern_worldbook.LoadResult(entries=[]),
    )


def _cfg(api_key: str = "sk-test") -> SimpleNamespace:
    return SimpleNamespace(api_provider="deepseek", api_key=api_key)


def _app_ctx(api=None, cfg=None, companion=None, intimacy=None, theme_engine=None) -> SimpleNamespace:
    return SimpleNamespace(
        api=api, cfg=cfg, companion=companion, intimacy=intimacy,
        theme_engine=theme_engine, config=None,
        logger=None,
    )


def _service(app_ctx, base_dir, *, synchronous=True) -> TavernService:
    _qapp()
    return TavernService(app_ctx, base_dir=base_dir, synchronous=synchronous)


# ===========================================================================
# 生命周期：新开一局 → 一拍 → 落盘 → 重新载入一致
# ===========================================================================

def test_start_play_turn_save_reload_roundtrip(tmp_path, patch_content):
    base = tmp_path / "tavern"
    svc = _service(_app_ctx(), base)

    pid = svc.start_play("lantern", title="灯笼还亮着", play_id="p1", seed=12345, now="2026-09-15T20:00:00")
    assert pid == "p1"
    assert svc.current_play_id() == "p1"

    # verbatim：order（"来一杯长夜" → order long_night）→ 状态确实被改
    assert svc.submit("来一杯长夜", input_kind="free") is True
    play = svc.current_play()
    assert play["vars"]["poured"] == "long_night"

    transcript = play["transcript"]
    roles = [e["role"] for e in transcript]
    assert roles == ["player", "narrator"]
    for entry in transcript:
        assert set(entry) == set(m.TRANSCRIPT_ENTRY_KEYS)
        assert set(entry["resolution"]) == set(m.RESOLUTION_REQUIRED_KEYS)
        assert entry["resolution"]["mode"] == "verbatim"
    # 落盘
    assert (base / "tavern.json").exists()

    # 重新载入（新服务实例，读同一 base_dir）
    svc2 = _service(_app_ctx(), base)
    assert svc2.current_play_id() == "p1"
    play2 = svc2.current_play()
    assert play2["vars"]["poured"] == "long_night"
    assert [e["role"] for e in play2["transcript"]] == ["player", "narrator"]
    assert play2["transcript"][0]["text"] == "来一杯长夜"
    assert play2["turn"] == play["turn"]


def test_no_active_play_submit_degrades(tmp_path, patch_content):
    _qapp()
    hints: list = []
    svc = _service(_app_ctx(), tmp_path / "tavern")
    svc.degraded.connect(hints.append)
    assert svc.submit("随便走走") is False
    assert hints and "还没有开局" in hints[0]


# ===========================================================================
# 单写点：写入路径集合 == ["tavern.json"]
# ===========================================================================

def test_only_writes_tavern_json(tmp_path, patch_content, monkeypatch):
    base = tmp_path / "tavern"
    written: list = []
    save_calls: list = []
    real_write = store_mod._atomic_write_json

    def _spy_write(path, data):
        written.append(os.path.basename(str(path)))
        return real_write(path, data)

    real_save = store_mod.TavernStore.save

    def _spy_save(self, data):
        save_calls.append(1)
        return real_save(self, data)

    monkeypatch.setattr(store_mod, "_atomic_write_json", _spy_write)
    monkeypatch.setattr(store_mod.TavernStore, "save", _spy_save)

    svc = _service(_app_ctx(), base)
    svc.start_play("lantern", play_id="p1", seed=1, now="2026-09-15T20:00:00")
    svc.submit("来一杯长夜")

    # 唯一被写入的文件恒为 tavern.json（单写点；子模块零写盘）
    assert written, "应当至少写盘一次"
    assert set(written) == {"tavern.json"}
    # 每一次落盘都恰经一次 _atomic_write_json（不存在旁路写点）
    assert len(save_calls) == len(written)


# ===========================================================================
# L4 只读态：高版本档 → 不崩 / 可玩 / 写入路径集合为空 / 优雅降级
# ===========================================================================

def test_l4_read_only_playable_no_write(tmp_path, patch_content, monkeypatch):
    base = tmp_path / "tavern"
    base.mkdir(parents=True, exist_ok=True)
    future = m.SCHEMA_VERSION + 5
    (base / "tavern.json").write_text(json.dumps({
        "schema_version": future,
        "plays": [m.new_play("lantern", "灯笼还亮着", 7, play_id="p1", now="2026-09-15T20:00:00")],
        "active_play_id": "p1",
    }, ensure_ascii=False), encoding="utf-8")

    written: list = []
    monkeypatch.setattr(store_mod, "_atomic_write_json",
                        lambda path, data: written.append(str(path)))

    hints: list = []
    ro: list = []
    svc = _service(_app_ctx(), base)
    svc.degraded.connect(hints.append)
    svc.read_only_changed.connect(ro.append)

    assert svc.is_read_only() is True
    # 可列出 / 可玩
    assert [p["play_id"] for p in svc.list_plays()] == ["p1"]
    assert svc.submit("来一杯长夜") is True

    play = svc.current_play()
    assert play["vars"]["poured"] == "long_night"            # 内存态可玩
    assert len(play["transcript"]) == 2
    # 不崩溃、写入路径集合为空、save 被拒但优雅降级
    assert written == []
    assert svc.save() is False
    assert hints and any("更高的版本" in h for h in hints)


def test_read_only_degrade_is_idempotent(tmp_path, patch_content):
    base = tmp_path / "tavern"
    base.mkdir(parents=True, exist_ok=True)
    (base / "tavern.json").write_text(
        json.dumps({"schema_version": m.SCHEMA_VERSION + 1, "plays": [], "active_play_id": ""}),
        encoding="utf-8",
    )
    svc = _service(_app_ctx(), base)
    assert svc.is_read_only() is True
    assert svc.save() is False
    assert svc.save() is False          # 幂等；不抛、不崩


# ===========================================================================
# ★ "history" 段 → 真实消息映射
# ===========================================================================

def test_render_chat_messages_maps_history_to_user():
    segments = [
        {"segment": "narrator_rules", "role": "system", "content": "规则"},
        {"segment": "world_rules", "role": "system", "content": ""},        # 空 system 被跳过
        {"segment": "character_card", "role": "system", "content": "人设"},
        {"segment": "turn_context", "role": "system", "content": "此刻"},
        {"segment": "history", "role": "history", "content": "【最近的经过】\n你：……"},
    ]
    messages = render_chat_messages(segments)
    assert [msg["role"] for msg in messages] == ["system", "system", "system", "user"]
    assert all(msg["role"] in VALID_CHAT_ROLES for msg in messages)
    assert "history" not in [msg["role"] for msg in messages]
    assert messages[-1]["role"] == "user"
    assert "最近的经过" in messages[-1]["content"]
    assert SEGMENT_MESSAGE_ROLES["history"] == "user"


def test_end_to_end_messages_have_no_illegal_role(tmp_path, patch_content):
    captured: list = []

    class _Api:
        def chat(self, *a, **k):
            return {"choices": [{"message": {"content": "{}"}}]}

        def chat_stream_chunks(self, messages, **kw):
            captured.append(messages)
            yield "夜色"

    app = _app_ctx(api=_Api(), cfg=_cfg())
    svc = _service(app, tmp_path / "tavern")
    svc.start_play("lantern", play_id="p1", seed=1, now="2026-09-15T20:00:00")
    # 自由输入走 propose（未命中词表）→ 叙述生成会用到 messages
    svc.submit("嗯，随便说点什么吧")

    assert captured, "应当有叙述请求"
    messages = captured[0]
    assert messages, "消息序列非空"
    assert all(msg["role"] in VALID_CHAT_ROLES for msg in messages)
    # 末段 history 已映射为 user
    assert messages[-1]["role"] == "user"


# ===========================================================================
# LLM 桩失败：一拍仍能完成 / 世界状态不变 / resolution 齐全 / 无异常抛
# ===========================================================================

def _llm_fail_api(mode: str):
    """构造四类失败 LLM 桩（propose 与叙述都失败）。"""
    class _Api:
        def chat(self, *a, **k):
            if mode == "none":
                return None
            if mode == "bad_json":
                return {"choices": [{"message": {"content": "{not json"}}]}
            if mode == "raise":
                raise RuntimeError("boom")
            if mode == "timeout":
                raise TimeoutError()
            return None

        def chat_stream_chunks(self, messages, **kw):
            def _gen():
                if mode == "raise":
                    raise RuntimeError("stream boom")
                return
                yield  # pragma: no cover
            return _gen()

    return _Api()


@pytest.mark.parametrize("mode", ["none", "bad_json", "raise", "timeout"])
def test_llm_failures_still_complete_turn(tmp_path, patch_content, mode):
    class _Cfg:
        api_provider = "deepseek"
        api_key = "sk-x"

    app = _app_ctx(api=_llm_fail_api(mode), cfg=_Cfg())
    svc = _service(app, tmp_path / "tavern")
    svc.start_play("lantern", play_id="p1", seed=1, now="2026-09-15T20:00:00")

    before = svc.current_play()
    before_vars = json.dumps(before["vars"], ensure_ascii=False, sort_keys=True)
    before_scene = before["scene_id"]
    before_node = before["node_id"]

    # 未命中词表的自由输入 → 走 propose；LLM 失败 → 降级 narrate（世界状态不变）
    assert svc.submit("嗯…今天天气不错") is True

    play = svc.current_play()
    # 世界状态不变（vars / scene / node）；turn 为拍计数由服务推进
    assert json.dumps(play["vars"], ensure_ascii=False, sort_keys=True) == before_vars
    assert play["scene_id"] == before_scene
    assert play["node_id"] == before_node

    entries = play["transcript"]
    assert [e["role"] for e in entries] == ["player", "narrator"]
    res = entries[0]["resolution"]
    assert set(res) == set(m.RESOLUTION_REQUIRED_KEYS)
    assert res["mode"] == "narrate"
    assert res["ok"] is False
    # 叙述降级为占位（非空）且 narrated 留痕完整
    assert entries[1]["text"].strip() != ""


def test_llm_malformed_propose_reason_is_bad_json(tmp_path, patch_content):
    class _Cfg:
        api_provider = "deepseek"
        api_key = "sk-x"
    app = _app_ctx(api=_llm_fail_api("bad_json"), cfg=_Cfg())
    svc = _service(app, tmp_path / "tavern")
    svc.start_play("lantern", play_id="p1", seed=1, now="2026-09-15T20:00:00")
    svc.submit("嗯…今天天气不错")
    res = svc.current_play()["transcript"][0]["resolution"]
    assert res["reason"] == "llm_bad_json"      # 畸形 JSON 可归因
    assert res["llm_used"] is True


def test_llm_timeout_propose_reason_is_timeout(tmp_path, patch_content):
    class _Cfg:
        api_provider = "deepseek"
        api_key = "sk-x"
    app = _app_ctx(api=_llm_fail_api("timeout"), cfg=_Cfg())
    svc = _service(app, tmp_path / "tavern")
    svc.start_play("lantern", play_id="p1", seed=1, now="2026-09-15T20:00:00")
    svc.submit("嗯…今天天气不错")
    res = svc.current_play()["transcript"][0]["resolution"]
    assert res["reason"] == "llm_timeout"


# ===========================================================================
# Q2 只读审计：跑完整流程后，未调用任何好感度 / 亲密写入 API
# ===========================================================================

class _SpyCompanion:
    """记录被调用的方法名；写入类方法若被调用即失败。"""

    WRITE_METHODS = ("add_intimacy", "bump", "record_event", "set_level", "set_stage", "increase")

    def __init__(self):
        self.calls: list = []

    def relation_stage_name(self):
        self.calls.append("relation_stage_name")
        return "亲近"

    def __getattr__(self, name):
        # 任何未知/写方法被访问 → 记录，便于断言"零写入"
        def _recorder(*a, **k):
            self.calls.append(name)
            return None
        return _recorder


class _SpyIntimacy:
    WRITE_METHODS = ("add_score", "set_score", "bump", "record", "increase")

    def __init__(self):
        self.calls: list = []

    def level_name(self):
        self.calls.append("level_name")
        return "熟悉"

    def __getattr__(self, name):
        def _recorder(*a, **k):
            self.calls.append(name)
            return None
        return _recorder


def test_q2_relation_read_only_no_writes(tmp_path, patch_content):
    companion = _SpyCompanion()
    intimacy = _SpyIntimacy()
    app = _app_ctx(companion=companion, intimacy=intimacy)
    svc = _service(app, tmp_path / "tavern")
    svc.start_play("lantern", play_id="p1", seed=1, now="2026-09-15T20:00:00")
    svc.submit("来一杯长夜")
    svc.submit("嗯…随便说点什么吧")

    # 只读：仅允许读方法被调用
    assert set(companion.calls) <= {"relation_stage_name"}, companion.calls
    assert set(intimacy.calls) <= {"level_name"}, intimacy.calls
    # 无任何写入命中
    assert not (set(companion.calls) & set(_SpyCompanion.WRITE_METHODS))
    assert not (set(intimacy.calls) & set(_SpyIntimacy.WRITE_METHODS))
    # 落盘里不出现亲密 / 好感数据
    raw = (tmp_path / "tavern" / "tavern.json").read_text(encoding="utf-8")
    for token in ("intimacy", "affection", "favor", "好感", "亲密"):
        assert token not in raw


# ===========================================================================
# 不缓存全局派生值：改 motion 档位 / 主题后下一次取用反映新值
# ===========================================================================

def test_motion_values_read_at_call_time(tmp_path, patch_content, monkeypatch):
    from gui import motion
    monkeypatch.setattr(motion, "system_animations_enabled", lambda: True)

    svc = _service(_app_ctx(), tmp_path / "tavern")

    motion.configure("off")
    assert svc.motion_level() == "off"
    assert svc.motion_enabled() is False
    assert svc.motion_duration(200) == 0

    motion.configure("standard")
    assert svc.motion_level() == "standard"
    assert svc.motion_enabled() is True
    assert svc.motion_duration(200) == 200      # 现取，非构造期缓存

    motion.configure("off")                       # 收尾还原


def test_theme_color_read_at_call_time(tmp_path, patch_content):
    class _Theme:
        def __init__(self):
            self.value = "#000001"

        def get_color(self, key, fallback):
            return self.value

    theme = _Theme()
    svc = _service(_app_ctx(theme_engine=theme), tmp_path / "tavern")
    assert svc.theme_color("bg", "#ffffff") == "#000001"
    theme.value = "#000002"
    # 未缓存：下一次调用反映新值
    assert svc.theme_color("bg", "#ffffff") == "#000002"


# ===========================================================================
# 姓名规则：given_name 空 → 码铃；非空 → 名字；绝不用 role.name
# ===========================================================================

class _Role:
    def __init__(self, given, name, desc="", sysp=""):
        self.given_name = given
        self.name = name
        self.description = desc
        self.system_prompt = sysp


def test_read_persona_empty_given_name_uses_product_name(monkeypatch):
    monkeypatch.setattr(svc_mod, "_default_role",
                        lambda: _Role("", "温柔女仆", desc="她系着围裙。"))
    persona = read_persona(_app_ctx())
    assert persona["display_name"] == PRODUCT_NAME
    assert persona["given_name"] == ""
    assert "温柔女仆" not in persona["display_name"]      # 严禁用人设标签当姓名


def test_read_persona_non_empty_given_name(monkeypatch):
    monkeypatch.setattr(svc_mod, "_default_role",
                        lambda: _Role("小铃", "温柔女仆", desc="她系着围裙。", sysp="说话慢。"))
    persona = read_persona(_app_ctx())
    assert persona["display_name"] == "小铃"
    assert "她系着围裙。" in persona["persona"]
    assert "说话慢。" in persona["persona"]
    assert "温柔女仆" not in persona["display_name"]


def test_persona_injected_into_prompt_system_message(tmp_path, patch_content, monkeypatch):
    captured: list = []

    class _Api:
        def chat(self, *a, **k):
            return None

        def chat_stream_chunks(self, messages, **kw):
            captured.append(messages)
            yield "夜色"

    monkeypatch.setattr(svc_mod, "_default_role",
                        lambda: _Role("小铃", "温柔女仆", desc="她系着围裙站在吧台后。"))
    app = _app_ctx(api=_Api(), cfg=_cfg())
    svc = _service(app, tmp_path / "tavern")
    svc.start_play("lantern", play_id="p1", seed=1, now="2026-09-15T20:00:00")
    svc.submit("来一杯长夜")

    assert captured
    joined = "\n".join(msg["content"] for msg in captured[0] if msg["role"] == "system")
    assert "她系着围裙站在吧台后。" in joined      # 应用侧 persona 注入成功
    assert "小铃" in joined                          # 名字进入 prompt
    assert "温柔女仆" not in joined                  # 人设标签未混入姓名位


# ===========================================================================
# reroll：只改 transcript 该拍，vars / node_id 不变；edit 只改 text
# ===========================================================================

def test_reroll_changes_only_narration_text(tmp_path, patch_content):
    class _Api:
        def chat(self, *a, **k):
            return None

        def chat_stream_chunks(self, messages, **kw):
            yield "重掷后的夜色"

    app = _app_ctx(api=_Api(), cfg=_cfg())
    svc = _service(app, tmp_path / "tavern")
    svc.start_play("lantern", play_id="p1", seed=1, now="2026-09-15T20:00:00")
    svc.submit("来一杯长夜")

    play = svc.current_play()
    turn = play["turn"]
    before_vars = json.dumps(play["vars"], ensure_ascii=False, sort_keys=True)
    before_node = play["node_id"]
    before_len = len(play["transcript"])

    assert svc.reroll(turn) is True
    after = svc.current_play()
    assert after["vars"] == play["vars"]
    assert json.dumps(after["vars"], ensure_ascii=False, sort_keys=True) == before_vars
    assert after["node_id"] == before_node
    assert len(after["transcript"]) == before_len
    assert after["transcript"][-1]["role"] == "narrator"
    assert after["transcript"][-1]["text"] == "重掷后的夜色"


def test_edit_narration_only_changes_text(tmp_path, patch_content):
    svc = _service(_app_ctx(), tmp_path / "tavern")
    svc.start_play("lantern", play_id="p1", seed=1, now="2026-09-15T20:00:00")
    svc.submit("来一杯长夜")
    play = svc.current_play()
    turn = play["turn"]

    assert svc.edit_narration(turn, "我把它改了个写法。") is True
    after = svc.current_play()
    assert after["transcript"][-1]["text"] == "我把它改了个写法。"
    assert after["vars"] == play["vars"]


# ===========================================================================
# 查询面：HUD / choices / trace / settings（界面零序号、零数值）
# ===========================================================================

def test_hud_and_trace_shapes(tmp_path, patch_content):
    svc = _service(_app_ctx(), tmp_path / "tavern")
    svc.start_play("lantern", play_id="p1", seed=1, now="2026-09-15T20:00:00")
    svc.submit("来一杯长夜")

    hud = svc.current_hud()
    assert set(hud) == {"chapter_title", "scene_id", "held_items", "read_only", "degraded"}
    assert hud["chapter_title"] == "灯笼还亮着"      # 章标题（无序号）
    assert hud["read_only"] is False

    trace = svc.trace()
    assert trace
    for row in trace:
        assert set(row) == {"turn", "role", "mode", "transform", "ok", "reason", "llm_used"}
        # 「记录」Tab 不呈现成功率 / 进度 / 胜率
        assert "win_rate" not in row and "progress" not in row and "score" not in row


def test_settings_get_set(tmp_path, patch_content):
    svc = _service(_app_ctx(), tmp_path / "tavern")
    assert svc.get_settings()["allow_propose"] is True
    assert svc.set_settings(allow_propose=False) is True
    assert svc.get_settings()["allow_propose"] is False
    assert svc.set_settings(unknown_key=1) is False          # 未知键不落
    # 类型不符 → 不落
    assert svc.set_settings(allow_propose="yes") is False


def test_free_input_disabled_gates_submit(tmp_path, patch_content):
    hints: list = []
    svc = _service(_app_ctx(), tmp_path / "tavern")
    svc.degraded.connect(hints.append)
    svc.start_play("lantern", play_id="p1", seed=1, now="2026-09-15T20:00:00")
    svc.set_settings(allow_free_input=False)
    assert svc.submit("来一杯长夜", input_kind="free") is False
    assert hints and "自由输入" in hints[-1]


# ===========================================================================
# 本地占位叙述：确定性 / 无网络 / 无 R-A 词
# ===========================================================================

def test_local_narration_deterministic_and_no_ra():
    play = m.new_play("lantern", "t", 1, now="2026-09-15T20:00:00")
    a = local_narration(play, {"mode": "verbatim", "ok": True, "transform": "order"})
    b = local_narration(play, {"mode": "verbatim", "ok": True, "transform": "order"})
    assert a == b and a.strip()
    assert local_narration(play, {"mode": "narrate", "ok": False, "transform": ""}).strip()
    ra_tokens = ("好感", "心情", "经验", "货币", "胜率", "连胜", "进度条", "倒计时", "好感度")
    for res in ({"mode": "verbatim", "ok": True, "transform": "wait"},
                {"mode": "narrate", "ok": False, "transform": ""}):
        text = local_narration(play, res)
        assert not any(tok in text for tok in ra_tokens)


# ===========================================================================
# 工作线程路径（生产默认）：submit → wait_for_idle
# ===========================================================================

def test_threaded_submit_completes(tmp_path, patch_content):
    _qapp()
    svc = _service(_app_ctx(), tmp_path / "tavern", synchronous=False)
    svc.start_play("lantern", play_id="p1", seed=1, now="2026-09-15T20:00:00")
    assert svc.submit("来一杯长夜") is True
    assert svc.wait_for_idle(10.0) is True
    play = svc.current_play()
    assert play["vars"]["poured"] == "long_night"
    assert len(play["transcript"]) == 2
    assert svc.is_busy() is False


# ===========================================================================
# 零 Qt 边界回归：除 service.py 外，其余 9 个模块仍可屏蔽 PySide6 后 import
# ===========================================================================

@pytest.mark.parametrize("module", [
    "gui.tavern",
    "gui.tavern.model",
    "gui.tavern.errors",
    "gui.tavern.store",
    "gui.tavern.engine",
    "gui.tavern.worldbook",
    "gui.tavern.intent_router",
    "gui.tavern.prompt",
    "gui.tavern.summarize",
])
def test_core_modules_import_without_pyside6(module):
    code = (
        "import sys\n"
        "class _Block:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name == 'PySide6' or name.startswith('PySide6.'):\n"
        "            raise ImportError('blocked: ' + name)\n"
        "        return None\n"
        "sys.meta_path.insert(0, _Block())\n"
        f"import {module}\n"
        "assert 'PySide6' not in sys.modules, 'PySide6 leaked: ' + repr(sorted(m for m in sys.modules if 'PySide6' in m))\n"
        "print('ZERO_QT_OK')\n"
    )
    import subprocess
    proc = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT),
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "ZERO_QT_OK" in proc.stdout
