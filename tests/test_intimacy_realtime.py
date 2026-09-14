from __future__ import annotations

from types import SimpleNamespace

from intimacy import IntimacyTracker
from persona import PersonaConfig, PromptManager
from session import ChatSession
from gui.chat_service import ChatService
from gui.main_window import MainWindow


class _PromptSession:
    def __init__(self, intimacy):
        self.intimacy = intimacy
        self.history = [{"role": "system", "content": "旧上下文"}]
        self.current_system = "旧上下文"

    def refresh_system_context(self):
        self.current_system = self.intimacy.build_intimacy_prompt()
        self.history[0]["content"] = self.current_system

    def add_message(self, role, content=None, **kwargs):
        self.history.append({"role": role, "content": content, **kwargs})


class _Companion:
    def __init__(self):
        self.calls = []

    def ingest_event(self, event_type, **kwargs):
        self.calls.append((event_type, kwargs))


class _Config:
    api_key = "sk-test"
    api_provider = "deepseek"


def _tracker(tmp_path, score):
    tracker = IntimacyTracker(filepath=str(tmp_path / "intimacy.json"))
    tracker._data["score"] = score
    tracker._data["level"] = tracker._get_level_info(score)["level"]
    return tracker


def test_upgrade_syncs_shared_tracker_refreshes_system_and_ingests_once(tmp_path):
    tracker = _tracker(tmp_path, score=149)
    stale_tracker = _tracker(tmp_path, score=0)
    session = _PromptSession(stale_tracker)
    companion = _Companion()
    ctx = SimpleNamespace(
        intimacy=tracker,
        session=session,
        companion=companion,
        collaborator=None,
        config=_Config(),
    )
    service = ChatService(ctx)
    service._current_user_text = "继续聊聊"

    service._bump_intimacy_after_reply()

    assert session.intimacy is tracker
    assert "【关系阶段】信赖" in session.current_system
    assert companion.calls == [("level_up", {"level": 3})]

    service._bump_intimacy_after_reply()
    assert companion.calls == [("level_up", {"level": 3})]


def test_custom_role_prompt_keeps_persona_and_relationship_context(tmp_path):
    tracker = _tracker(tmp_path, score=50)
    session = ChatSession.__new__(ChatSession)
    session.gui_role_prompt = "你是定制角色小铃，回答时保持这一角色。"
    session.memory_mgr = SimpleNamespace(build_memory_context=lambda: "【记忆】主人喜欢测试")
    session.intimacy = tracker
    session.pm = PromptManager(PersonaConfig(role="女仆", title="工程师"))
    session.deep_mode = False
    session.coding_mode = False
    session.chat_mode = SimpleNamespace(is_chat_mode=False)
    session.expr_guide_enabled = False

    prompt = session._build_system_prompt()

    assert "你是主人的专属贴身女仆" in prompt
    assert "【关系阶段】亲近" in prompt
    assert "【互动规则】" in prompt
    assert "【当前角色设定】\n你是定制角色小铃" in prompt


def test_intimacy_signal_refreshes_existing_home_page():
    class _StatusBar:
        def __init__(self):
            self.messages = []

        def showMessage(self, text, timeout):
            self.messages.append((text, timeout))

    class _Home:
        def __init__(self):
            self.refreshes = 0

        def _refresh_companion_panel(self):
            self.refreshes += 1

    home = _Home()
    window = SimpleNamespace(status_bar=_StatusBar(), pages={"home": home})

    MainWindow._on_intimacy_changed(window, "关系更亲近了")

    assert home.refreshes == 1
    assert window.status_bar.messages == [("💕 关系更亲近了", 5000)]


def test_intimacy_signal_refreshes_sidebar_chip():
    class _StatusBar:
        def showMessage(self, text, timeout):
            pass

    class _Sidebar:
        def __init__(self):
            self.refreshes = 0

        def update_maid_chip(self):
            self.refreshes += 1

    sidebar = _Sidebar()
    window = SimpleNamespace(status_bar=_StatusBar(), pages={}, sidebar=sidebar)

    MainWindow._on_intimacy_changed(window, "关系更亲近了")

    assert sidebar.refreshes == 1


def test_sidebar_chip_uses_current_role_assets_and_intimacy_stage(monkeypatch, tmp_path):
    from gui.qt_compat import QApplication
    QApplication.instance() or QApplication([])
    import gui.maid_avatar as maid_avatar
    import gui.pages.page_role as page_role
    import gui.widgets.sidebar as sidebar_mod
    from gui.qt_compat import QPixmap, Qt

    class _Asset:
        def __init__(self, marker):
            self.marker = marker
            self.calls = []

        def rounded(self, expression, size):
            self.calls.append((expression, size))
            pix = QPixmap(size, size)
            pix.fill(Qt.white)
            return pix

    default_assets = _Asset("default")
    whale_assets = _Asset("whale")
    roles = {
        "maid": SimpleNamespace(id="maid", name="码铃"),
        "whale": SimpleNamespace(id="whale", name="鲸鱼娘"),
    }
    manager = SimpleNamespace(default_role=roles["maid"], get_role=roles.get)
    tracker = _tracker(tmp_path, score=50)
    ctx = SimpleNamespace(
        cfg=None, config=None, theme_engine=None,
        companion=SimpleNamespace(mood="normal", relation_stage_name=lambda: "信赖"),
        companion_bridge=None, role_bridge=None, page_manager=None,
        intimacy=tracker,
    )

    monkeypatch.setattr(page_role, "RoleManager", lambda: manager)
    monkeypatch.setattr(maid_avatar, "role_assets", lambda role_id: {
        "maid": None, "whale": whale_assets,
    }.get(role_id))
    monkeypatch.setattr(sidebar_mod, "_SIDEBAR_MAID_OK", True)
    monkeypatch.setattr(sidebar_mod, "_sidebar_assets", lambda: default_assets)
    monkeypatch.setattr(sidebar_mod, "_MAID_BIG_OK", False)
    monkeypatch.setattr(sidebar_mod, "_side_mood_to_expr", lambda state: "happy")

    sidebar = sidebar_mod.SidebarWidget(ctx)
    default_assets.calls.clear()
    sidebar._on_role_changed("whale", "", "normal")

    assert sidebar.maid_chip.text().strip() == "鲸鱼娘 · 亲近"
    assert whale_assets.calls == [("happy", 28)]
    assert default_assets.calls == []
