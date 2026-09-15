# -*- coding: utf-8 -*-
"""V22-09 酒馆域「接线」端到端可达性单测（design-v22 §6.1 / 酒馆域批 3）。

本文件论证的是「酒馆**真的可达**」，而不是「源码里出现了 ``tavern`` 字符串」：

  1. 侧栏 ``NAV_ITEMS`` 恰含 ``("tavern", "酒馆", "glass", "\\U0001F377")``，且
     ``icon_name == "glass"`` 是**已登记**图标名（以 ``icons_manifest.json`` 为权威）；
  2. **端到端可达性**：offscreen 构造 ``MainWindow`` → ``page_manager.navigate("tavern")``
     后，当前页 key == ``"tavern"``、当前页**是** :class:`PageTavern` 实例、
     ``tabs.count() == 5`` 且 5 个 ``tabText(i)`` 顺序 == 今夜 / 世界书 / 我的故事 / 人物 / 记录；
  3. 两个打包 spec（onedir / onefile）的 ``datas`` 均把酒馆内容包打到 frozen 态口径
     ``tavern/content``（与 ``worldbook.content_dir()`` 严格对齐，写歪即静默空包）；
  4. **零污染**（自证）：本测试隔离酒馆存档目录，**绝不**创建 / 改写真实
     ``~/.maid_coder/tavern``；并在模块用例前后各取一次真实目录快照、断言逐字节不变。

GUI 用例统一 ``QT_QPA_PLATFORM=offscreen``。
"""
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

import gui.motion as motion
import gui.pages.page_tavern as page_tavern_mod
import gui.widgets.sidebar as sidebar_mod
from gui.qt_compat import QApplication, QWidget

ROOT = Path(__file__).resolve().parents[1]

#: 期望的侧栏酒馆导航项（4 元组：key / label / icon_name / emoji 回退）。
_TAVERN_NAV_ITEM = ("tavern", "酒馆", "glass", "\U0001F377")

#: 5 Tab 标题（**顺序冻结**，design-v22 §6.1）。
_TAB_TITLES = ["今夜", "世界书", "我的故事", "人物", "记录"]

#: 两个打包 spec（onedir + onefile）。
_SPEC_FILES = ("maid_coder_gui.spec", "maid_coder_gui_onefile.spec")

#: spec ``datas`` 里必须出现的酒馆内容包条目（text 断言；目标目录恰为 tavern/content）。
_TAVERN_DATAS_ENTRY = "('gui/tavern/content', 'tavern/content')"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _reset_motion():
    """每个用例前后把动效档复位；接线用例不关心过渡动画，直接终态。"""
    motion.stop_all(final=True)
    motion.configure("off")
    yield
    motion.stop_all(final=True)
    motion.configure("standard")


def _real_tavern_snapshot():
    """真实用户酒馆存档目录的只读快照：``(状态, 路径, 文件树指纹)``。

    ``default_base_dir()`` == ``~/.maid_coder/tavern``（``gui/tavern/store.py``，D-V22-07）。
    本函数**只 stat / 只遍历**，绝不创建、绝不写入。
    """
    from gui.tavern.store import default_base_dir

    base = default_base_dir()
    if not base.exists():
        return ("absent", str(base), ())
    entries = []
    for path in sorted(base.rglob("*")):
        try:
            info = path.stat()
            entries.append(
                (str(path.relative_to(base)), info.st_size, int(info.st_mtime))
            )
        except OSError:  # pragma: no cover - 并发删除等边界
            entries.append((str(path.relative_to(base)), -1, -1))
    return ("present", str(base), tuple(entries))


@pytest.fixture(scope="module")
def _real_store_guard():
    """模块级零污染守卫：整轮用例前后快照真实存档目录，断言逐字节不变。

    这是第 4 项的**自证**手段——若任何用例误用真实目录（创建 / 改写），
    模块收尾时本守卫会以断言失败把污染暴露出来，而不是静默放过。
    """
    before = _real_tavern_snapshot()
    yield before
    after = _real_tavern_snapshot()
    assert before == after, (
        f"测试污染了真实用户酒馆存档目录（D-V22-07）！before={before!r} after={after!r}"
    )


@pytest.fixture(scope="module")
def tavern_sandbox(tmp_path_factory, _real_store_guard):
    """模块级存档隔离：把 ``PageTavern`` 内的 ``TavernService`` 换成为 ``base_dir`` 强制
    注入临时目录的工厂。

    只要 ``MainWindow`` 构造 ``PageTavern``（→ ``TavernService`` → ``TavernStore``），
    存档就只会落在 pytest 临时目录，**绝不**触碰 ``~/.maid_coder/tavern``。
    """
    sandbox = tmp_path_factory.mktemp("tavern_sandbox")
    real_service = page_tavern_mod.TavernService
    mp = pytest.MonkeyPatch()

    def _factory(app_ctx, *args, **kwargs):
        kwargs["base_dir"] = sandbox
        return real_service(app_ctx, *args, **kwargs)

    mp.setattr(page_tavern_mod, "TavernService", _factory)
    yield sandbox
    mp.undo()


@pytest.fixture(scope="module")
def main_window(qapp, tavern_sandbox):
    """构造一次主窗（含页面栈 / 侧栏 / 酒馆页）。

    ``ChatPanelWidget``（域 6 独占）以轻量桩替换——本文件只验证酒馆接线，
    不耦合聊天面板内部实现（沿用 ``tests/test_v21_wiring.py`` 的同款手法）。
    """
    import gui.main_window as mw_mod
    from gui.app_context import AppContext
    from gui.config import GuiConfig

    class _StubChatPanel(QWidget):
        def __init__(self, app_ctx, parent=None):
            super().__init__(parent)
            self.app_ctx = app_ctx

    mp = pytest.MonkeyPatch()
    mp.setattr(mw_mod, "ChatPanelWidget", _StubChatPanel)
    try:
        ctx = AppContext()
        ctx.config = GuiConfig()
        ctx.config.first_run = False  # 跳过首次引导弹层
        win = mw_mod.MainWindow(ctx)
    finally:
        mp.undo()
    yield win
    try:
        win.close()
        win.deleteLater()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 1 · 侧栏导航项（含已登记图标名）
# ---------------------------------------------------------------------------
def test_nav_items_contains_tavern_with_registered_icon():
    """侧栏恰含酒馆项，且图标名 ``glass`` 是 manifest 中的已登记语义名。"""
    from gui import icons

    items = sidebar_mod.SidebarWidget.NAV_ITEMS
    assert _TAVERN_NAV_ITEM in items, f"NAV_ITEMS 缺少酒馆项：{_TAVERN_NAV_ITEM!r}"

    idx = items.index(_TAVERN_NAV_ITEM)
    assert items[idx][2] == "glass"
    assert items[idx][3] == "\U0001F377", "emoji 回退须为 🍷（图标字体不可用时不空白）"
    assert icons.has("glass"), "glass 必须是已登记图标名（icons_manifest.json 权威）"


def test_nav_items_tavern_is_pure_insertion_between_plan_and_agent():
    """纯插入（R-D 增量）：tavern 紧邻在 plan 之后、agent 之前，既有相对顺序不变。"""
    keys = [item[0] for item in sidebar_mod.SidebarWidget.NAV_ITEMS]
    assert "tavern" in keys
    pos = keys.index("tavern")
    assert keys[pos - 1] == "plan", "tavern 之前应仍是 plan（不得重排既有项）"
    assert keys[pos + 1] == "agent", "tavern 之后应仍是 agent（不得重排既有项）"
    # plan → agent 的原始相邻关系被 tavern 插入后，两者仍在彼此附近且顺序未反转
    assert keys.index("plan") < keys.index("tavern") < keys.index("agent")


# ---------------------------------------------------------------------------
# 2 · 端到端可达性：MainWindow → navigate("tavern") → PageTavern + 5 Tab
# ---------------------------------------------------------------------------
def test_navigate_tavern_reaches_page_tavern_with_five_tabs(main_window):
    """``page_manager.navigate("tavern")`` 真的把酒馆页推到前台，且 5 Tab 顺序正确。"""
    win = main_window
    pm = win.page_manager

    pm.navigate("tavern")

    assert pm.current_page_key() == "tavern"
    page = win.pages["tavern"]
    assert isinstance(page, page_tavern_mod.PageTavern), (
        f"tavern 页类型应为 PageTavern，实际 {type(page).__name__}"
    )
    # 当前栈顶 **就是** 酒馆页（而非仅页面字典里有）
    assert pm._stack.currentWidget() is page

    # Tab 数量 + 顺序（真读 tabText，而非只信常量）
    assert page.tabs.count() == 5
    titles = [page.tabs.tabText(i) for i in range(page.tabs.count())]
    assert titles == _TAB_TITLES
    # 页面自带查询接口与实测一致
    assert page.tab_titles() == _TAB_TITLES


def test_navigate_tavern_invokes_on_enter_lifecycle(main_window):
    """可达性的副作用正确：``navigate`` 触发了 ``PageTavern.on_enter``（整体刷新）。"""
    win = main_window
    page = win.pages["tavern"]
    calls = []
    original = page.on_enter

    def _spy():
        calls.append(True)
        original()

    page.on_enter = _spy  # type: ignore[assignment]
    try:
        win.page_manager.navigate("tavern")
    finally:
        pass
    assert calls == [True]


# ---------------------------------------------------------------------------
# 3 · 打包 spec 带内容包（目标目录恰为 tavern/content）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("spec_name", _SPEC_FILES)
def test_spec_datas_packages_tavern_content_at_expected_target(spec_name):
    """两个 spec 的 datas 都把 ``gui/tavern/content`` 打到 ``tavern/content``（frozen 口径）。"""
    text = (ROOT / spec_name).read_text(encoding="utf-8")
    assert _TAVERN_DATAS_ENTRY in text, (
        f"{spec_name} 缺少酒馆内容包 datas 条目：{_TAVERN_DATAS_ENTRY}"
    )


def test_tavern_content_source_dir_exists_at_content_dir():
    """源码态内容包目录存在，且恰是 ``worldbook.content_dir()`` 指向处。"""
    from gui.tavern.worldbook import content_dir

    resolved = content_dir()
    assert resolved.is_dir(), f"内容包目录不存在：{resolved}"
    # 内容包内含随包书（lantern）
    assert (resolved / "lantern").is_dir()


# ---------------------------------------------------------------------------
# 4 · 零污染自证：真实 ~/.maid_coder/tavern 前后不变
# ---------------------------------------------------------------------------
def test_real_user_tavern_store_untouched(main_window):
    """在同一用例内前后各取一次真实存档目录快照，断言 navigate 也不触碰它。"""
    before = _real_tavern_snapshot()
    main_window.page_manager.navigate("tavern")  # 触发 PageTavern.on_enter（读盘 + 刷新）
    after = _real_tavern_snapshot()
    assert before == after, (
        f"navigate('tavern') 改动了真实存档目录！before={before!r} after={after!r}"
    )
    assert before[0] in ("absent", "present")
