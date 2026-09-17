# -*- coding: utf-8 -*-
r"""v2.2.2 浮窗接线守卫 —— 两条不变量，专治「没有守卫的修复会漂回去」。

背景（用户不可观测，但会静默劣化）：
  `ChatWindow._connect_signals` 改前首行是 `if self.chat_service is None: return`。
  真实路径上 `chat_service` 恒有值（`gui/main.py` 注入），所以**症状不可观测** ——
  但该早退会把 5 条**与 `chat_service` 无关**的通道一并跳过：
      theme_engine.theme_changed / gui_session.message_added /
      role_bridge.role_changed / tts.state_changed / companion_bridge.mood_changed
  反事实实测（改前）：`chat_service=None` 时这 5 条**各 0 次**触发，且
  `main_container` 的 QSS **冻结**在旧主题；改后各 1 次、QSS 跟随新主题。

本文件守两条不变量：
  A. **judged 独立性**：`chat_service` 缺失时，上述 5 条通道仍各连接 1 次，
     且换肤信号能真的把窗口容器 QSS 刷成新主题 —— 用**两把尺子**
     （新主题 chat_bg/border 出现 + 旧主题 chat_bg/border 消失），不只数槽。
  B. **幂等**：`_connect_signals` 再被调用 2 次后，单次 emit 只触发 **1 次**。
     改前实测是 **3 次**（重复 connect 会让同一个槽被调多次）—— 这条用例
     在改前是**红的**，正是它要守的东西。

另附：
  · 非空转守卫（`test_slot_counter_is_not_vacuous`）：人为重复连接一次，计数器
    必须报 2 —— 否则不变量 B 的 `== 1` 是假绿。
  · 源码级不变量（AST）：5 条与 service 无关的 `connect()` **不得**嵌在任何
    「测试表达式提到 chat_service」的 `if` 里。这样即使将来有人换个写法重新
    把通道塞回判空块，也会在这里炸，而不是等到用户在某条降级路径上发现换肤失效。

对抗性自检（本轮已实跑，输出见回传 / `_release_work/_evidence_b/`）：
  ① 把不变量 B 的一次性标记摘掉（`if not self._theme_connected:` → `if True:`）
     ⇒ `test_connect_signals_is_idempotent` 必红；
  ② 把 `theme_changed` 那条连接塞回 `if self.chat_service is not None:` 块内
     ⇒ `test_chat_service_missing_does_not_kill_other_channels` 与
        `test_service_independent_connections_not_gated_by_chat_service` 双红。
  每次还原后按字节回读校验（sha256 与改前一致）。

全 offscreen、零网络、不改任何产品文件。
"""
from __future__ import annotations

import ast
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CODEBUDDY_SAFE_DELETE_ENABLED", "0")

import pytest  # noqa: E402
from PySide6.QtCore import QObject, Signal  # noqa: E402

from gui.qt_compat import QApplication  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CHAT_WINDOW_PY = ROOT / "gui" / "widgets" / "chat_window.py"
_ISO = Path(tempfile.mkdtemp(prefix="maling_test_wiring_"))

T_OLD, T_NEW = "ui_minimal", "ui_night"

#: 与 `chat_service` **无关**的 5 条通道（槽名）—— 改前的早退把它们全跳过
INDEPENDENT_SLOTS = (
    "_on_theme_changed",        # theme_engine.theme_changed
    "_on_message_added",        # gui_session.message_added
    "_on_role_changed",         # role_bridge.role_changed
    "_on_tts_state_changed",    # tts.state_changed
    "_on_tray_mood_changed",    # companion_bridge.mood_changed
)


def _pump(n: int = 6) -> None:
    for _ in range(n):
        QApplication.processEvents()


# ---------------------------------------------------------------------------
# 假订阅源：只提供被订阅的那一个信号，签名照抄产品（gui/chat_service.py 等）
# ---------------------------------------------------------------------------
class _FakeGuiSession(QObject):
    message_added = Signal(str, str)


class _FakeRoleBridge(QObject):
    role_changed = Signal(str, str, str)


class _FakeTts(QObject):
    state_changed = Signal(object)


class _FakeCompanionBridge(QObject):
    mood_changed = Signal(str, str)


class _FakeChatService(QObject):
    message_stream_started = Signal()
    message_chunk_received = Signal(str)
    message_stream_finished = Signal(str, dict)
    message_cancelled = Signal()
    thinking_indicator = Signal(bool)
    message_failed = Signal(str)
    agent_tool_event = Signal(str, str)
    agent_authorization_requested = Signal(str, str)
    proactive_message = Signal(str, str)
    proactive_feedback_ready = Signal(str, str)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(scope="module")
def isolated_env(_cwd_repo):
    keys = ("USERPROFILE", "HOME", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP")
    saved = {k: os.environ.get(k) for k in keys}
    for k in keys:
        os.environ[k] = str(_ISO)
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture(scope="module", autouse=True)
def _restore_default_theme(qapp):
    yield
    try:
        from gui.theme_engine import ThemeEngine
        ThemeEngine().load_theme(ThemeEngine.DEFAULT_THEME_ID)
        _pump(4)
    except Exception:  # noqa: BLE001 —— 收尾清理失败不该污染用例结论
        pass


@pytest.fixture(scope="module", autouse=True)
def _cwd_repo():
    """先 `os.chdir(仓库根)`，收尾还原（不在 import 期改动全局 cwd）。"""
    saved = os.getcwd()
    os.chdir(ROOT)
    yield ROOT
    os.chdir(saved)


@pytest.fixture
def no_glass(monkeypatch):
    """毛玻璃开关关掉后仍显式打桩，避免平台差异把用例结论搅浑。"""
    import gui.glass as glass
    monkeypatch.setattr(glass, "is_supported", lambda: False, raising=True)
    monkeypatch.setattr(glass, "safe_apply", lambda h, k, *, dark: True, raising=True)
    monkeypatch.setattr(glass, "remove", lambda h: True, raising=True)
    yield


@pytest.fixture
def calls(monkeypatch):
    """槽调用计数器：在类上打桩，**连的仍是 `self._on_xxx` 绑定方法**。

    之所以不数「`connect()` 被调用了几次」，是因为那样只能证明接线代码跑过，
    证明不了信号真的能到达槽。计数器由 `monkeypatch` 保证按原值还原。
    """
    from gui.widgets.chat_window import ChatWindow

    counter: dict = {}
    for name in INDEPENDENT_SLOTS + ("_on_stream_started",):
        orig = getattr(ChatWindow, name)

        def make(n, o):
            def wrapper(self, *a, **k):
                counter[n] = counter.get(n, 0) + 1
                return o(self, *a, **k)
            return wrapper

        monkeypatch.setattr(ChatWindow, name, make(name, orig), raising=True)
    yield counter


def _build(with_service: bool):
    """真 `ChatWindow`（不 show：本文件判的是接线与 QSS 串，不判几何）。"""
    from gui.app_context import AppContext
    from gui.config import GuiConfig
    from gui.theme_engine import ThemeEngine
    from gui.widgets.chat_window import ChatWindow

    cfg = GuiConfig()
    cfg.first_run = False
    cfg.auto_check = False
    cfg.tts_enabled = False
    cfg.pet_enabled = False
    cfg.glass_popups_enabled = False
    eng = ThemeEngine()
    eng.load_theme(T_OLD)
    _pump(4)
    bg_old = eng.get_color("chat_bg", "#000000").upper()
    bd_old = eng.get_color("chat_border", "#000000").upper()
    ctx = AppContext(config=cfg)
    ctx.theme_engine = eng
    ctx.gui_session = _FakeGuiSession()
    ctx.role_bridge = _FakeRoleBridge()
    ctx.tts = _FakeTts()
    ctx.companion_bridge = _FakeCompanionBridge()
    ctx.chat_service = _FakeChatService() if with_service else None
    cw = ChatWindow(ctx)
    cw.resize(520, 720)
    _pump(6)
    return cw, ctx, eng, bg_old, bd_old


def _teardown(cw) -> None:
    try:
        cw.close()
        cw.deleteLater()
        _pump(4)
    except Exception:  # noqa: BLE001
        pass


# ===========================================================================
# 不变量 A —— chat_service 缺失时，与它无关的通道一条都不能断
# ===========================================================================
def test_chat_service_missing_does_not_kill_other_channels(
        qapp, isolated_env, no_glass, calls):
    """`chat_service=None` 时 5 条通道各触发 1 次，且换肤真的落到容器 QSS。

    改前这里会红：5 条各 **0** 次（首行 `if self.chat_service is None: return` 早退）。
    """
    cw, ctx, eng, bg_old, bd_old = _build(with_service=False)
    try:
        # 构造期基线：容器 QSS 必须先落在**旧**主题上，否则下面的换肤判据无意义
        assert bg_old in cw.main_container.styleSheet().upper(), (
            "构造期基线不成立：容器 QSS 里没有旧主题 chat_bg —— 换肤判据无从谈起")
        assert bg_old in cw.messages_container.styleSheet().upper()

        # --- 通道①：换肤（真信号、真槽、真副作用；两把尺子）---
        calls.clear()
        eng.load_theme(T_NEW)          # load_theme 内部就会 emit（theme_engine.py:512）
        _pump(6)
        assert calls.get("_on_theme_changed") == 1, (
            "`chat_service=None` 时 theme_changed 没有到达 `_on_theme_changed` —— "
            "通道被 `if self.chat_service is None: return` 之类的前置判空挡住了")
        bg_new = eng.get_color("chat_bg", "#000000").upper()
        bd_new = eng.get_color("chat_border", "#000000").upper()
        assert bg_new != bg_old and bd_new != bd_old, (
            "两套主题的 chat_bg / chat_border 相同 —— 本用例的『新色出现 / 旧色消失』"
            "两把尺子失效，请换一对主题")
        for w, label in ((cw.main_container, "main_container"),
                         (cw.messages_container, "messages_container")):
            ss = w.styleSheet().upper()
            assert bg_new in ss, f"{label} 的 QSS 没有刷成新主题 chat_bg={bg_new}"
            assert bg_old not in ss, f"{label} 的 QSS 残留旧主题 chat_bg={bg_old}"
        assert bd_old not in cw.main_container.styleSheet().upper(), (
            "main_container 的 QSS 残留旧主题 chat_border —— 只有部分属性被重刷")
        assert bd_new in cw.main_container.styleSheet().upper()

        # --- 通道②：会话消息广播 ---
        # role 取 "system"：槽照常被调用，但不建气泡（保持用例聚焦在「接线」上）
        calls.clear()
        ctx.gui_session.message_added.emit("system", "探针")
        _pump(4)
        assert calls.get("_on_message_added") == 1, (
            "`chat_service=None` 时 gui_session.message_added 没有到达 `_on_message_added`")

        # --- 通道③：角色生效 ---
        calls.clear()
        ctx.role_bridge.role_changed.emit("preset_maid", "", "normal")
        _pump(4)
        assert calls.get("_on_role_changed") == 1, (
            "`chat_service=None` 时 role_bridge.role_changed 没有到达 `_on_role_changed`")

        # --- 通道④：TTS 朗读归属 ---
        calls.clear()
        ctx.tts.state_changed.emit(None)
        _pump(4)
        assert calls.get("_on_tts_state_changed") == 1, (
            "`chat_service=None` 时 tts.state_changed 没有到达 `_on_tts_state_changed`")

        # --- 通道⑤：托盘心情 ---
        calls.clear()
        ctx.companion_bridge.mood_changed.emit("happy", "manual")
        _pump(4)
        assert calls.get("_on_tray_mood_changed") == 1, (
            "`chat_service=None` 时 companion_bridge.mood_changed 没有到达 "
            "`_on_tray_mood_changed`")

        # --- 反例守卫：依赖 chat_service 的通道在本场景**按设计不接** ---
        assert calls.get("_on_stream_started", 0) == 0, (
            "没有 chat_service 却接上了流式通道 —— 判空保护被改坏了（会 NPE）")
    finally:
        _teardown(cw)


def test_feedback_bars_initialised_without_chat_service(
        qapp, isolated_env, no_glass, calls):
    """`_feedback_bars` 与 `chat_service` 无关，必须无条件建立。

    改前它只在「连 proactive_feedback_ready」的 try 块里初始化 ⇒ `chat_service`
    缺失时该属性**从未建立**，而产品代码里存在直接
    `self._feedback_bars.append(...)` 的路径（AttributeError）。
    """
    cw, _ctx, _eng, _bg, _bd = _build(with_service=False)
    try:
        assert hasattr(cw, "_feedback_bars"), (
            "`chat_service=None` 时 `_feedback_bars` 没有建立 —— "
            "它被错误地留在依赖 chat_service 的分支里")
        assert isinstance(cw._feedback_bars, list) and cw._feedback_bars == []
    finally:
        _teardown(cw)


# ===========================================================================
# 不变量 B —— `_connect_signals` 必须幂等
# ===========================================================================
def test_connect_signals_is_idempotent(qapp, isolated_env, no_glass, calls):
    """再调 2 次 `_connect_signals` 后，单次 emit 只能触发 **1** 次。

    改前这里会红：`_on_theme_changed` 实测触发 **3** 次（1 次原始 + 2 次重复连接），
    `_on_message_added` 同样 3 次 —— 重复 connect 会让同一个槽被调多次。
    """
    cw, ctx, eng, _bg, _bd = _build(with_service=True)
    try:
        cw._connect_signals()
        cw._connect_signals()

        calls.clear()
        eng.theme_changed.emit(T_NEW)
        ctx.gui_session.message_added.emit("system", "重复探针")
        ctx.chat_service.message_stream_started.emit()
        _pump(6)

        assert calls.get("_on_theme_changed") == 1, (
            f"`_connect_signals` 不幂等：单次 theme_changed 触发了 "
            f"{calls.get('_on_theme_changed')} 次（应为 1）—— 每条通道需要自己的"
            f"「一次性连接」标记，否则换肤回调会被重复执行 N 次")
        assert calls.get("_on_message_added") == 1, (
            f"`_connect_signals` 不幂等：单次 message_added 触发了 "
            f"{calls.get('_on_message_added')} 次（应为 1）—— 重复连接会让气泡渲染两次")
        assert calls.get("_on_stream_started") == 1, (
            f"`_connect_signals` 不幂等：单次 message_stream_started 触发了 "
            f"{calls.get('_on_stream_started')} 次（应为 1）")
    finally:
        _teardown(cw)


def test_slot_counter_is_not_vacuous(qapp, isolated_env, no_glass, calls):
    """**非空转守卫**：人为重复连接一次，计数器必须报 **2**。

    否则上面那条 `== 1` 可能是「计数器根本不会变大」造成的假绿。
    """
    cw, ctx, _eng, _bg, _bd = _build(with_service=True)
    try:
        ctx.gui_session.message_added.connect(cw._on_message_added)  # 人为重复连接
        calls.clear()
        ctx.gui_session.message_added.emit("system", "非空转")
        _pump(4)
        assert calls.get("_on_message_added") == 2, (
            "计数器无法报出重复连接（实测 "
            f"{calls.get('_on_message_added')} 次）—— 幂等用例里的 `== 1` 是假绿，"
            "请先修好计数口径")
    finally:
        _teardown(cw)


# ===========================================================================
# 源码级不变量 —— 5 条通道的 connect 不得嵌在任何「提到 chat_service」的 if 里
# ===========================================================================
def test_service_independent_connections_not_gated_by_chat_service():
    """AST 判据：与 `chat_service` 无关的 `connect()` 不许被前置判空圈住。

    行为用例已经能抓到「早退」这一种退化写法；本判据多守一层 —— 拦住
    「不用早退、改成把某几条通道挪进 `if self.chat_service is not None:` 块内」
    这种同样会断通道、但只在降级路径上才暴露的写法。
    """
    src = CHAT_WINDOW_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "_connect_signals"), None)
    assert fn is not None, "chat_window.py 找不到 `_connect_signals`（判据失效）"

    parents: dict = {}
    for p in ast.walk(tree):
        for c in ast.iter_child_nodes(p):
            parents[c] = p

    def _gated(node) -> str:
        """沿祖先链找「测试表达式提到 chat_service」的 if，返回其源码片段。"""
        cur = parents.get(node)
        while cur is not None and cur is not fn:
            if isinstance(cur, ast.If):
                seg = ast.get_source_segment(src, cur.test) or ""
                if "chat_service" in seg:
                    return seg.strip()
            cur = parents.get(cur)
        return ""

    offenders, seen = [], set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if not (isinstance(target, ast.Attribute) and target.attr == "connect"
                and node.args):
            continue
        callee = node.args[0]
        if not (isinstance(callee, ast.Attribute)
                and isinstance(callee.value, ast.Name)
                and callee.value.id == "self"):
            continue
        if callee.attr not in INDEPENDENT_SLOTS:
            continue
        seen.add(callee.attr)
        guard = _gated(node)
        if guard:
            offenders.append(
                f"{callee.attr} 的连接被 `if {guard}:` 圈住（chat_window.py:{node.lineno}）")

    assert not offenders, (
        "与 `chat_service` 无关的通道被前置判空圈住了 —— 该对象缺失时这些通道会"
        "整段断掉（换肤 / 消息广播 / 角色切换 / TTS / 托盘心情）：\n  "
        + "\n  ".join(offenders))
    assert seen == set(INDEPENDENT_SLOTS), (
        f"这 5 条通道的 connect 没有全部被本判据覆盖（只找到 {sorted(seen)}）—— "
        f"说明 `_connect_signals` 的写法变了，判据需要同步更新，"
        f"但现在它是**失效**状态")
