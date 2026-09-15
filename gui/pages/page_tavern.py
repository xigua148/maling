# -*- coding: utf-8 -*-
"""gui/pages/page_tavern.py —— 酒馆页：5 Tab 容器（V22-06 / V22-11 装配点）。

设计依据：``docs/design-v22.md``
    · §4.6  页面冻结签名 ``PageTavern(app_ctx, title="酒馆")`` + ``on_enter()`` 生命周期钩子；
    · §6.1  5 Tab：``今夜`` / ``世界书`` / ``我的故事`` / ``人物`` / ``记录``（顺序固定）；
    · §6.2  「今夜」信息层级：章标题条 → 叙述流（贴底跟随）→ 快捷动作排 → 自由输入行；
    · §6.3  颜色只走 ``gui.utils.theme_color`` 语义键（**读时现取，绝不缓存**）；
    · §6.4  **字号只写在 ``gui/themes/base.qss``**（本文件零字号赋值）；
    · §6.5  全局派生值（主题色 / 动效档）**读时取、不缓存**——故本页订阅 ``theme_changed``，
            槽内对各控件调 ``apply_theme()`` 重刷；
    · §7    **不做任何第三类几何母题动效**（本页不创建动画对象）；
    · Q4 / R-A 界面零序号、零计量数值（章标题条 / 故事列表 / 记录面均由控件侧守卫）。

=================================  接线契约（与控件拥有者约定）  =================================
1. **控件自订阅数据信号**：``narration_chunk`` / ``narration_done`` / ``hud_changed`` /
   ``choices_changed`` / ``busy_changed`` / ``read_only_changed`` / ``degraded`` /
   ``worldbook_changed`` / ``turn_ready`` 一律由 ``gui/widgets/tavern/**`` **自行订阅**
   （见 ``gui/widgets/tavern/__init__.py:20-24``）。**本页绝不重复连接这些信号**
   （否则同一次事件会被渲染两遍）。
2. **控件自己动手**：``TavernInput`` 点击/回车时自行 ``service.submit(...)``；
   ``TavernNarrative.reroll / edit_text`` 自行 ``service.reroll / edit_narration``。
   本页的槽**绝不**再调这三个方法（会双发）。控件另发的 ``submitted`` /
   ``reroll_requested`` / ``edit_requested`` 仅供本页做**观察性**动作（如玩家回显）。
3. **``theme_changed`` 由本页独占订阅**：槽内对 6 个控件 + 本页自带小面板调 ``apply_theme()``。
4. **玩家那一行的回显是本页的活**：``TavernNarrative.add_player(text)`` 的 docstring 写明
   "页面在 submit 成功后调用"，故 ``TavernInput.submitted`` → ``narrative.add_player``。
5. **退出安全**：``TavernService`` 持 ``_TurnWorker(QThread)``，其 ``stop()`` **未**自动挂
   ``aboutToQuit``（QThread 仍在跑时解释器退出会崩 ``0xC0000409``）。本页照
   ``gui/widgets/kb_worker.py`` 既有做法自挂 ``QApplication.aboutToQuit`` →
   有界 ``service.stop(2000)`` + ``service.save()``，槽幂等、无 QApplication 时静默降级。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from gui.qt_compat import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    Qt,
)
from gui.tavern.service import FALLBACK_BOOK_ID, TavernService
from gui.utils import theme_color
from gui.widgets.tavern.tavern_hud import TavernHud
from gui.widgets.tavern.tavern_input import TavernInput
from gui.widgets.tavern.tavern_narrative import TavernNarrative
from gui.widgets.tavern.tavern_plays import PlaysPanel
from gui.widgets.tavern.tavern_trace import TracePanel
from gui.widgets.tavern.tavern_worldbook import WorldbookPanel

logger = logging.getLogger("maling.tavern.page")

__all__ = ["PageTavern", "TAB_TITLES"]

# ===========================================================================
# 常量
# ===========================================================================

#: 5 Tab 标题（**顺序冻结**，见 §6.1；标题本身是无序号的中文短名）。
TAB_TITLES = ("今夜", "世界书", "我的故事", "人物", "记录")

TAB_TONIGHT, TAB_WORLDBOOK, TAB_PLAYS, TAB_CAST, TAB_TRACE = range(5)

#: 退出时对酒馆工作线程的**有界**等待上界（ms）。一拍含一次 LLM 往返，
#: 2.0s 为既有取值（``TavernService.stop`` 默认同值）；硬上界保证退出绝不无限阻塞。
QUIT_STOP_WAIT_MS: int = 2000

#: 「今夜」文本级操作按钮（重写 / 改字，§6.2）——**只重跑叙述，不动状态**。
REROLL_BTN_TEXT: str = "重写这一拍"
EDIT_BTN_TEXT: str = "改这一拍的字"
EDIT_DIALOG_TITLE: str = "改这一拍的字"
EDIT_DIALOG_LABEL: str = "把这一拍改成："

#: 「今夜」开局 / 终局出口（P0：无入口则首次进入永远开不了局）。
#: 文案一律**自然语言**（贴合产品调性），**不用**「开始游戏」这类工具腔，**零序号 / 零数值**。
START_BTN_TEXT: str = "今晚留下来"
START_HINT_TEXT: str = "灯笼还亮着，还没人推门进来。就从这里开始这一夜吧。"
RESTART_BTN_TEXT: str = "再来一夜"
ENDED_HINT_TEXT: str = "这一夜走到了尽头，余韵还留着。要不要再点一盏灯，重新坐一会儿？"

#: 叙述流空态引导（**无活动局**时；指向开局入口，让玩家知道该点哪里开始）。
NARRATIVE_EMPTY_HINT: str = "这一夜还没开始。点上面的入口，故事就从这里铺开。"
#: 叙述流空态（**已有活动局**但尚未落第一拍）——中性，不误导玩家去找入口。
NARRATIVE_IDLE_HINT: str = "故事还没开始。"

#: 「人物」Tab 文案（**零序号、零计量**；缺 cast → 中性空态，绝不空白、绝不崩）。
CAST_PANEL_TITLE: str = "人物"
CAST_HINT_TEXT: str = "这里放着这一夜会遇到的人；只是看一看，改不了他们。"
CAST_EMPTY_TEXT: str = "人物卡还没有准备好，等故事铺开再来看。"
CAST_UNNAMED: str = "（还没有名字）"
CAST_LINE_MAX_CHARS: int = 120

#: 「世界书」Tab 设置行文案 —— R-A 口径：**中性**，不含「性能 / 准确率 / 落后 / 开销」
#: 这类焦虑词（对齐 D-V22-03）。
SETTINGS_PROPOSE_LABEL: str = "让她自己想个主意，再按本地的规矩落实"
SETTINGS_PROPOSE_HINT: str = "关掉之后，这一夜就只按你写下的原话来走。"
SETTINGS_BUDGET_LABEL: str = "世界书每拍大约带上"
SETTINGS_BUDGET_HINT: str = "这是一段大约的字数，不必一次定准。"
BUDGET_MIN: int = 1200
BUDGET_MAX: int = 2000
BUDGET_STEP: int = 100
BUDGET_DEFAULT: int = 1600

#: 圆角 / 内距（**不是色值**，故不入下面的兜底色表；同样读时使用）。
_RADIUS_MD: str = "10px"
_RADIUS_SM: str = "6px"

#: 主题语义键的**兜底值**（仅 ``theme_engine`` 不可用时使用）。
#: 纪律：本文件**只允许**在这一张表里出现 ``#RRGGBB`` 字面量；任何上屏颜色都必须
#: 经 :meth:`PageTavern._color` → ``gui.utils.theme_color`` **读时现取**（§6.3 / §6.5），
#: 保证换肤即时生效、且不存在"绕过主题的裸色"。
_FALLBACK_COLORS: Dict[str, str] = {
    "text": "#4A4A4A",
    "text_secondary": "#8A8A8A",
    "text_hint": "#9A9A9A",
    "bg_card": "#FFFFFF",
    "divider": "#EFE0E2",
    "border": "#EFE0E2",
    "accent": "#FF6B9D",
    "accent_text": "#B45073",
    "primary": "#FF6B9D",
    "primary_dark": "#E8558A",
    "focus_accent": "#FF6B9D",
    "surface_muted": "#EFEFEF",
    "state_warn": "#A96A12",
    "text_on_accent": "#FFFFFF",
}


# ===========================================================================
# 纯函数小工具（本地副本，避免跨文件耦合）
# ===========================================================================

def _first_str(*values: Any) -> str:
    """取首个非空字符串（去首尾空白）；都不合格式 → 空串。"""
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _clip(text: str, limit: int = CAST_LINE_MAX_CHARS) -> str:
    """压成单行短摘要（保留可读性，**不改动原文语义**）。"""
    flat = " ".join(str(text).split())
    if len(flat) > limit:
        return flat[:limit] + "…"
    return flat


def _decorate(name: str, label: str) -> str:
    """图标字形 + 文案；图标不可用 → **只留文案**（不回落 emoji，§6.1「禁裸 emoji 上屏」）。"""
    try:
        from gui import icons

        glyph = icons.text_glyph(name, "")
    except Exception:  # pragma: no cover - 图标内核不可用边界
        logger.debug("酒馆页面取图标字形失败（只显示文案）", exc_info=True)
        glyph = ""
    return f"{glyph} {label}" if glyph else label


def _default_book_id() -> str:
    """内容包里的**缺省书 id**（开局入口的集中取值点）。

    纪律：开局入口**不得硬编码** ``"lantern"``；书 id 一律经本函数从内容包目录现取
    （枚举 ``content_dir()`` 下带 ``book.json`` 的包，取排序首个），以后新增内容包
    无需改 UI 代码。读不到（目录缺失 / 解析异常）→ 回落 :data:`FALLBACK_BOOK_ID`。
    """
    try:
        from gui.tavern.worldbook import content_dir

        packs = sorted(
            path.name for path in content_dir().iterdir()
            if path.is_dir() and (path / "book.json").is_file()
        )
    except Exception:
        logger.debug("枚举酒馆内容包失败（回落缺省书 id）", exc_info=True)
        packs = []
    return packs[0] if packs else FALLBACK_BOOK_ID


def _content_cast(book_id: str) -> List[dict]:
    """读取**内容包**里声明的人物卡（只读；缺包 / 无 ``cast`` → 空表，**绝不抛**）。

    内容包解析走**唯一入口** :func:`gui.tavern.worldbook.load_content`（§4.2「单一 source」），
    本函数**不另写解析器**：``cast`` 既可来自解析器的顶层同名键（未来扩展），
    也可来自 ``book.json`` 整份保留的 ``worldbook`` 段（现状下内容包作者唯一的落点）。

    ⚠️ 「灯笼酒馆」内容包现阶段**没有** ``cast`` → 调用方渲染中性空态（不空白、不崩）。
    V22-11 的人物卡导入 / 导出（``role_card.py``）**不在本页范围**。
    """
    bid = _first_str(book_id) or FALLBACK_BOOK_ID
    try:
        from gui.tavern.worldbook import load_content

        content = load_content(bid)
    except Exception:
        logger.debug("酒馆内容包读取失败（人物卡按空处理）: %s", bid, exc_info=True)
        return []
    if not isinstance(content, dict):
        return []
    raw = content.get("cast")
    if not isinstance(raw, list):
        worldbook = content.get("worldbook")
        raw = worldbook.get("cast") if isinstance(worldbook, dict) else None
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _cast_member_view(member: dict) -> Dict[str, str]:
    """把一条 ``cast[]`` 记录渲染成 ``{"name", "role", "line"}``（**如实读取，不编造**）。

    兼容 ``{cast_id, role, card_id, card_snapshot}``（§4.1）与更扁平的写法；取不到的名字
    回落角色名，再回落中性占位（而不是编一个名字出来）。
    """
    snapshot = member.get("card_snapshot")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    name = _first_str(
        member.get("name"),
        snapshot.get("given_name"),
        snapshot.get("name"),
        snapshot.get("title"),
    )
    role = _first_str(member.get("role"), snapshot.get("role"))
    line = _clip(_first_str(
        snapshot.get("description"),
        snapshot.get("persona"),
        snapshot.get("system_prompt"),
        member.get("line"),
    ))
    if not name:
        name = role or CAST_UNNAMED
    return {"name": name, "role": role, "line": line}


# ===========================================================================
# 主类：PageTavern
# ===========================================================================

class PageTavern(QWidget):
    """酒馆页：5 Tab 容器（装配 ``TavernService`` 与 6 个酒馆控件）。

    公共 API（供接线方 / 测试）：
        * :meth:`on_enter` —— PageManager 生命周期钩子：整体刷新；
        * :meth:`refresh_cast` —— 重绘「人物」Tab（只读卡片）；
        * :meth:`sync_settings_row` —— 从 ``service.get_settings()`` 回读设置行；
        * :meth:`tab_titles` —— 当前 5 个 Tab 标题（运行期实测值）。

    Attributes（装配结果，供接线方 / 测试直接取用）：
        ``service`` / ``tabs`` / ``hud`` / ``narrative`` / ``tavern_input`` /
        ``worldbook`` / ``plays`` / ``trace`` / ``allow_propose_check`` / ``budget_spin`` /
        ``_start_panel`` / ``_start_hint`` / ``_start_btn``（开局 / 终局出口）。
    """

    def __init__(
        self,
        app_context: Any,
        title: str = "酒馆",
        parent: Optional[QWidget] = None,
    ) -> None:
        """构造酒馆页。

        Args:
            app_context: 应用上下文（``theme_engine`` 用于换肤订阅）。
            title: 页面标题（页面注册用；Tab 标题见 :data:`TAB_TITLES`）。
            parent: Qt 父对象。
        """
        super().__init__(parent)
        self.app_ctx = app_context
        self.title = title
        # 服务：本页是一等依赖持有者（单测用 tmp 目录的 service 替换本模块同名符号）
        self.service = TavernService(app_context, parent=self)
        self._quit_handled = False
        self._quit_app: Any = None
        self._settings_sync = False
        self._cast_cards: List[QFrame] = []
        self._init_ui()
        self._apply_theme()
        self._connect_signals()

    # ==================================================================
    # 构建
    # ==================================================================
    def _init_ui(self) -> None:
        """搭 5 Tab（顺序冻结）+ 各 Tab 内容。"""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("tavernTabs")
        self.tabs.addTab(self._build_tonight_tab(), TAB_TITLES[TAB_TONIGHT])
        self.tabs.addTab(self._build_worldbook_tab(), TAB_TITLES[TAB_WORLDBOOK])
        self.tabs.addTab(self._build_plays_tab(), TAB_TITLES[TAB_PLAYS])
        self.tabs.addTab(self._build_cast_tab(), TAB_TITLES[TAB_CAST])
        self.tabs.addTab(self._build_trace_tab(), TAB_TITLES[TAB_TRACE])
        root.addWidget(self.tabs)

    # ---------------------------------------------------------------- 今夜
    def _build_tonight_tab(self) -> QWidget:
        """「今夜」：章标题条 → 开局/终局入口 → 叙述流 → 文本级操作行 → 快捷动作 + 自由输入。"""
        page = QWidget(self.tabs)
        page.setObjectName("tavernTonightTab")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.hud = TavernHud(self.service, self.app_ctx, page)
        layout.addWidget(self.hud)

        # 开局 / 终局出口（P0）：无活动局时显示开局入口，终局时显示「再来一夜」；
        # 有活动局时整块隐藏（避免重复开局）。状态由 _sync_start_entry 现读现切。
        self._start_panel = self._build_start_entry(page)
        layout.addWidget(self._start_panel)

        self.narrative = TavernNarrative(self.service, self.app_ctx, page)
        layout.addWidget(self.narrative, 1)

        layout.addLayout(self._build_text_actions(page))

        self.tavern_input = TavernInput(self.service, self.app_ctx, page)
        layout.addWidget(self.tavern_input)
        return page

    def _build_start_entry(self, parent: QWidget) -> QFrame:
        """开局 / 终局入口块（引导文案 + 一个自然语言动作按钮）。

        * **无活动局** → 引导文案 + 「今晚留下来」（点击 → ``service.start_play(book_id)``）；
        * **终局**（``status == "ended"``）→ 余韵引导 + 「再来一夜」（开新的一局）；
        * **有活动局** → 整块隐藏（由 :meth:`_sync_start_entry` 现读现切）。
        """
        frame = QFrame(parent)
        frame.setObjectName("tavernStartPanel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        self._start_hint = QLabel(START_HINT_TEXT, frame)
        self._start_hint.setObjectName("tavernStartHint")
        self._start_hint.setWordWrap(True)
        layout.addWidget(self._start_hint)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addStretch(1)
        self._start_btn = QPushButton(_decorate("glass", START_BTN_TEXT), frame)
        self._start_btn.setObjectName("tavernStartBtn")
        self._start_btn.setCursor(Qt.PointingHandCursor)
        self._start_btn.clicked.connect(self._on_start_clicked)
        row.addWidget(self._start_btn)
        layout.addLayout(row)
        return frame

    def _build_text_actions(self, parent: QWidget) -> QHBoxLayout:
        """「重写 / 改字」行（§6.2）：**文本级**操作，不触碰任何状态字段（§5.2）。

        按钮归页面装配（``TavernNarrative`` 只暴露方法 + 信号，不内建按钮）。
        点击经控件自身的 ``reroll`` / ``edit_text`` 走一次服务调用 —— 本页**不**直连
        ``service.reroll`` / ``service.edit_narration``（避免双发）。
        """
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addStretch(1)

        self.reroll_btn = QPushButton(_decorate("refresh", REROLL_BTN_TEXT), parent)
        self.reroll_btn.setObjectName("tavernRerollBtn")
        self.reroll_btn.setCursor(Qt.PointingHandCursor)
        self.reroll_btn.clicked.connect(self._on_reroll_clicked)
        row.addWidget(self.reroll_btn)

        self.edit_btn = QPushButton(_decorate("edit", EDIT_BTN_TEXT), parent)
        self.edit_btn.setObjectName("tavernEditBtn")
        self.edit_btn.setCursor(Qt.PointingHandCursor)
        self.edit_btn.clicked.connect(self._on_edit_clicked)
        row.addWidget(self.edit_btn)
        return row

    # -------------------------------------------------------------- 世界书
    def _build_worldbook_tab(self) -> QWidget:
        """「世界书」：条目一览（只读展示）+ 一行设置（``allow_propose`` / 字符预算）。"""
        page = QWidget(self.tabs)
        page.setObjectName("tavernWorldbookTab")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.worldbook = WorldbookPanel(self.service, self.app_ctx, page)
        layout.addWidget(self.worldbook, 1)
        layout.addWidget(self._build_settings_row(page))
        return page

    def _build_settings_row(self, parent: QWidget) -> QFrame:
        """设置行：``allow_propose`` 勾选 + 世界书字符预算（读写 :meth:`TavernService.set_settings`）。"""
        frame = QFrame(parent)
        frame.setObjectName("tavernSettingsRow")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        self.allow_propose_check = QCheckBox(SETTINGS_PROPOSE_LABEL, frame)
        self.allow_propose_check.setObjectName("tavernAllowPropose")
        self.allow_propose_check.toggled.connect(self._on_allow_propose_toggled)
        layout.addWidget(self.allow_propose_check)

        propose_hint = QLabel(SETTINGS_PROPOSE_HINT, frame)
        propose_hint.setObjectName("tavernSettingsHint")
        propose_hint.setWordWrap(True)
        layout.addWidget(propose_hint)

        budget_row = QHBoxLayout()
        budget_row.setContentsMargins(0, 0, 0, 0)
        budget_row.setSpacing(8)
        budget_label = QLabel(SETTINGS_BUDGET_LABEL, frame)
        budget_label.setObjectName("tavernSettingsLabel")
        budget_row.addWidget(budget_label)

        self.budget_spin = QSpinBox(frame)
        self.budget_spin.setObjectName("tavernBudgetSpin")
        self.budget_spin.setRange(BUDGET_MIN, BUDGET_MAX)
        self.budget_spin.setSingleStep(BUDGET_STEP)
        self.budget_spin.setValue(BUDGET_DEFAULT)
        self.budget_spin.setSuffix(" 字")
        self.budget_spin.valueChanged.connect(self._on_budget_changed)
        budget_row.addWidget(self.budget_spin)
        budget_row.addStretch(1)
        layout.addLayout(budget_row)

        budget_hint = QLabel(SETTINGS_BUDGET_HINT, frame)
        budget_hint.setObjectName("tavernSettingsHint")
        budget_hint.setWordWrap(True)
        layout.addWidget(budget_hint)

        # 首帧回读存档里的当前设置（只读；不回写）
        self.sync_settings_row()
        return frame

    # ------------------------------------------------------------ 我的故事
    def _build_plays_tab(self) -> QWidget:
        """「我的故事」：多局存档列表（列表项只显示章标题 + 相对时间，**无序号**）。"""
        page = QWidget(self.tabs)
        page.setObjectName("tavernPlaysTab")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.plays = PlaysPanel(self.service, self.app_ctx, page)
        layout.addWidget(self.plays, 1)
        return page

    # ---------------------------------------------------------------- 人物
    def _build_cast_tab(self) -> QWidget:
        """「人物」：只读人物卡（来源 = 内容包声明的 ``cast``；无则中性空态）。"""
        page = QWidget(self.tabs)
        page.setObjectName("tavernCastTab")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        self._cast_title = QLabel(CAST_PANEL_TITLE, page)
        self._cast_title.setObjectName("tavernPanelTitle")
        layout.addWidget(self._cast_title)

        self._cast_hint = QLabel(CAST_HINT_TEXT, page)
        self._cast_hint.setObjectName("tavernPanelHint")
        self._cast_hint.setWordWrap(True)
        layout.addWidget(self._cast_hint)

        self._cast_scroll = QScrollArea(page)
        self._cast_scroll.setWidgetResizable(True)
        self._cast_scroll.setFrameShape(QFrame.NoFrame)
        self._cast_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._cast_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._cast_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._cast_host = QWidget()
        self._cast_layout = QVBoxLayout(self._cast_host)
        self._cast_layout.setContentsMargins(0, 0, 0, 0)
        self._cast_layout.setSpacing(6)
        self._cast_layout.addStretch(1)

        self._cast_empty = QLabel(CAST_EMPTY_TEXT, self._cast_host)
        self._cast_empty.setObjectName("tavernEmptyHint")
        self._cast_empty.setWordWrap(True)
        self._cast_layout.insertWidget(0, self._cast_empty)

        self._cast_scroll.setWidget(self._cast_host)
        layout.addWidget(self._cast_scroll, 1)

        self.refresh_cast()
        return page

    def refresh_cast(self) -> None:
        """重绘「人物」Tab（幂等；只读卡片 + 空态；**绝不空白、绝不崩**）。

        卡片的颜色在**每次渲染时**现取（§6.5），故换肤后重绘即跟随。
        """
        for card in self._cast_cards:
            try:
                self._cast_layout.removeWidget(card)
                card.setParent(None)
                card.deleteLater()
            except Exception:  # pragma: no cover - 对象生命周期边界
                logger.debug("移除酒馆人物卡失败（忽略）", exc_info=True)
        self._cast_cards = []

        book_id = self._current_book_id()
        members = _content_cast(book_id)
        for member in members:
            card = self._build_cast_card(_cast_member_view(member))
            self._cast_cards.append(card)
            self._cast_layout.insertWidget(self._cast_layout.count() - 1, card)

        self._cast_empty.setVisible(not self._cast_cards)
        self._cast_empty.setStyleSheet(
            "QLabel#tavernEmptyHint { color: %s; background: transparent; }"
            % self._color("text_hint")
        )

    def _current_book_id(self) -> str:
        """当前局的 ``book_id``（无局 / 异常 → 内容包缺省 id，集中经 :func:`_default_book_id`）。"""
        try:
            play = self.service.current_play()
        except Exception:
            logger.debug("读取酒馆当前局失败（人物卡按缺省内容包）", exc_info=True)
            return _default_book_id()
        if isinstance(play, dict):
            return _first_str(play.get("book_id")) or _default_book_id()
        return _default_book_id()

    def _build_cast_card(self, view: Dict[str, str]) -> QFrame:
        """单张只读人物卡（姓名 + 角色 + 一句话；颜色现取）。"""
        card = QFrame(self._cast_host)
        card.setObjectName("tavernCastCard")

        bg_card = self._color("bg_card")
        border = self._color("border")
        card.setStyleSheet(
            "QFrame#tavernCastCard {"
            f" background: {bg_card}; border: 1px solid {border};"
            f" border-radius: {_RADIUS_MD};"
            "}"
        )

        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        name = QLabel(view["name"], card)
        name.setObjectName("tavernCastName")
        name.setWordWrap(True)
        name.setStyleSheet(
            "QLabel#tavernCastName { color: %s; background: transparent; }" % self._color("text")
        )
        head.addWidget(name, 1)

        if view["role"]:
            role = QLabel(view["role"], card)
            role.setObjectName("tavernCastRole")
            accent = self._color("accent")
            # v2.1(UI-P1)：chip 文字用 accent_text；描边仍用 accent（非文字图形）。
            accent_text = self._color("accent_text")
            role.setStyleSheet(
                "QLabel#tavernCastRole {"
                f" color: {accent_text}; border: 1px solid {accent};"
                f" border-radius: {_RADIUS_SM}; padding: 1px 8px; background: transparent;"
                "}"
            )
            head.addWidget(role, 0, Qt.AlignTop)
        layout.addLayout(head)

        if view["line"]:
            line = QLabel(view["line"], card)
            line.setObjectName("tavernCastLine")
            line.setWordWrap(True)
            line.setStyleSheet(
                "QLabel#tavernCastLine { color: %s; background: transparent; }"
                % self._color("text_secondary")
            )
            layout.addWidget(line)
        return card

    # ---------------------------------------------------------------- 记录
    def _build_trace_tab(self) -> QWidget:
        """「记录」：只读留痕（**不呈现成功率 / 进度 / 胜率**，控件侧守卫）。"""
        page = QWidget(self.tabs)
        page.setObjectName("tavernTraceTab")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.trace = TracePanel(self.service, self.app_ctx, page)
        layout.addWidget(self.trace, 1)
        return page

    # ==================================================================
    # 主题（本页独占订阅 theme_changed）
    # ==================================================================
    def _color(self, key: str) -> str:
        """现取主题语义色（**读时取、绝不缓存**；§6.3 / §6.5）。"""
        return theme_color(self.app_ctx, key, _FALLBACK_COLORS.get(key, ""))

    def _apply_theme(self) -> None:
        """换肤刷新：6 个控件各自 ``apply_theme()`` + 本页自带面板重绘取色。"""
        for widget in (
            self.hud, self.narrative, self.tavern_input,
            self.worldbook, self.plays, self.trace,
        ):
            fn = getattr(widget, "apply_theme", None)
            if not callable(fn):
                continue
            try:
                fn()
            except Exception:
                logger.debug("酒馆控件换肤失败（忽略）", exc_info=True)

        self._apply_page_style()
        self._sync_start_entry()
        self.refresh_cast()

    def _apply_page_style(self) -> None:
        """本页自带小部件的取色（读时现取；字号一律留给 ``base.qss`` 的 11c 段）。"""
        self._cast_title.setStyleSheet(
            "QLabel#tavernPanelTitle { color: %s; background: transparent; }" % self._color("text")
        )
        self._cast_hint.setStyleSheet(
            "QLabel#tavernPanelHint { color: %s; background: transparent; }"
            % self._color("text_hint")
        )
        hint_color = self._color("text_hint")
        for label in self.findChildren(QLabel, "tavernSettingsHint"):
            label.setStyleSheet(
                "QLabel#tavernSettingsHint { color: %s; background: transparent; }" % hint_color
            )
        for label in self.findChildren(QLabel, "tavernSettingsLabel"):
            label.setStyleSheet(
                "QLabel#tavernSettingsLabel { color: %s; background: transparent; }"
                % self._color("text_secondary")
            )
        self.allow_propose_check.setStyleSheet(
            "QCheckBox#tavernAllowPropose { color: %s; background: transparent; }"
            % self._color("text")
        )
        self.budget_spin.setStyleSheet(
            "QSpinBox#tavernBudgetSpin { color: %s; background: transparent; }"
            % self._color("text")
        )
        action_qss = (
            "color: %s; border: 1px solid %s; border-radius: %s; padding: 2px 10px;"
            " background: transparent;"
        )
        self.reroll_btn.setStyleSheet(
            f"QPushButton#tavernRerollBtn {{ {action_qss % (self._color('primary_dark'), self._color('divider'), _RADIUS_SM)} }}"
        )
        self.edit_btn.setStyleSheet(
            f"QPushButton#tavernEditBtn {{ {action_qss % (self._color('text_secondary'), self._color('divider'), _RADIUS_SM)} }}"
        )
        # 开局 / 终局入口块（颜色读时现取；字号留给 base.qss §11c）
        self._start_panel.setStyleSheet(
            "QFrame#tavernStartPanel {"
            f" background: {self._color('bg_card')};"
            f" border: 1px solid {self._color('divider')};"
            f" border-radius: {_RADIUS_MD};"
            "}"
        )
        self._start_hint.setStyleSheet(
            "QLabel#tavernStartHint { color: %s; background: transparent; }"
            % self._color("text_secondary")
        )
        self._start_btn.setStyleSheet(
            "QPushButton#tavernStartBtn {"
            f" color: {self._color('text_on_accent')};"
            f" background: {self._color('primary')};"
            " border: none;"
            f" border-radius: {_RADIUS_SM};"
            " padding: 6px 18px;"
            "}"
        )

    def _on_theme_changed(self, theme_name: str) -> None:  # noqa: ARG002 - 只关心"变了"
        """``theme_engine.theme_changed`` 槽：整页换肤（控件不自行订阅本信号）。"""
        self._apply_theme()

    # ==================================================================
    # 接线
    # ==================================================================
    def _connect_signals(self) -> None:
        """订阅**本页自己的**信号：换肤 + 玩家回显 + 故事列表刷新 + 退出收口。

        **不**订阅任何数据信号（叙述 / 状态条 / 选项 / 忙态 / 降级 / 世界书 / 留痕）——
        那些由各控件自行订阅（见模块 docstring 契约 1）。
        """
        theme_engine = getattr(self.app_ctx, "theme_engine", None)
        if theme_engine is not None and hasattr(theme_engine, "theme_changed"):
            try:
                theme_engine.theme_changed.connect(self._on_theme_changed)
            except Exception:
                logger.debug("酒馆页换肤订阅失败（忽略）", exc_info=True)

        # 玩家那一行的回显（观察性动作；**不**在此重发 submit）
        try:
            self.tavern_input.submitted.connect(self._on_input_submitted)
        except Exception:
            logger.debug("酒馆页输入回显接线失败（忽略）", exc_info=True)

        # 列表增删改 → 刷新「我的故事」（面板亦自订阅，刷新幂等）
        try:
            self.service.plays_changed.connect(self._on_plays_changed)
        except Exception:
            logger.debug("酒馆页故事列表接线失败（忽略）", exc_info=True)

        # 当前局变化（开局 / 载入 / 终局落定）→ 重切开局 / 终局入口（本页自己的 UI 状态）
        try:
            self.service.play_changed.connect(self._on_play_changed)
        except Exception:
            logger.debug("酒馆页开局入口接线失败（忽略）", exc_info=True)

        self._connect_app_quit()

    def _connect_app_quit(self) -> None:
        """挂 ``QApplication.aboutToQuit`` → 本页自我收口（无 QApplication 时静默降级）。"""
        try:
            app = QApplication.instance()
        except Exception:  # pragma: no cover - 无 Qt 绑定边界
            logger.debug("酒馆页取 QApplication 失败（降级为无应用级收口）", exc_info=True)
            return
        if app is None:
            return
        try:
            app.aboutToQuit.connect(self._on_app_about_to_quit)
            self._quit_app = app
        except Exception:
            logger.debug("酒馆页 aboutToQuit 挂接失败（忽略）", exc_info=True)

    def _on_app_about_to_quit(self) -> None:
        """应用即将退出：**有界**停掉酒馆工作线程 + 落盘（**幂等**，重复调用不抛）。

        为什么必做：``TavernService`` 持 ``_TurnWorker(QThread)``，其 ``stop()`` 未自动挂
        ``aboutToQuit``；线程仍在跑时解释器退出 → ``QThread: Destroyed while thread is
        still running`` → Windows fail-fast ``0xC0000409``（本项目已修过同类缺陷，
        见 ``gui/widgets/kb_worker.py``）。顺序 = ``stop(wait)`` → ``save()``。
        """
        if self._quit_handled:
            return
        self._quit_handled = True

        app = self._quit_app
        self._quit_app = None
        if app is not None:
            try:
                app.aboutToQuit.disconnect(self._on_app_about_to_quit)
            except Exception:
                logger.debug("酒馆页 aboutToQuit 断连失败（忽略）", exc_info=True)

        service = getattr(self, "service", None)
        stop = getattr(service, "stop", None)
        if callable(stop):
            try:
                stop(QUIT_STOP_WAIT_MS)
            except Exception:
                logger.debug("酒馆工作线程停机失败（忽略）", exc_info=True)
        save = getattr(service, "save", None)
        if callable(save):
            try:
                save()
            except Exception:
                logger.debug("酒馆页退出落盘失败（忽略）", exc_info=True)

    def _on_input_submitted(self, text: str, input_kind: str = "free") -> None:
        """玩家输入已提交（``TavernInput.submitted``）→ 叙述流补一行回显。

        ``service.submit`` 已由 ``TavernInput`` 自己调用，此处**只做观察性回显**；
        ``turn`` 用控件默认值（``-1``），随后的 ``play_changed`` 重建会以存档为准对齐。
        """
        _ = input_kind
        try:
            self.narrative.add_player(text)
        except Exception:
            logger.debug("酒馆页玩家回显失败（忽略）", exc_info=True)

    def _on_plays_changed(self) -> None:
        """``plays_changed`` → 刷新「我的故事」列表（刷新幂等）。"""
        refresh = getattr(self.plays, "refresh", None)
        if callable(refresh):
            try:
                refresh()
            except Exception:
                logger.debug("酒馆页刷新故事列表失败（忽略）", exc_info=True)

    # ==================================================================
    # 开局 / 终局出口（P0：首次进入必须能开局；终局后必须有出口）
    # ==================================================================
    def _play_status(self) -> str:
        """当前局状态（**只读**）：无局 → 空串；有局 → ``status``（缺省 ``"active"``）。"""
        try:
            play = self.service.current_play()
        except Exception:
            logger.debug("读取酒馆当前局状态失败（按无局处理）", exc_info=True)
            return ""
        if not isinstance(play, dict):
            return ""
        status = play.get("status")
        return status if isinstance(status, str) and status else "active"

    def _sync_start_entry(self) -> None:
        """按当前局状态切换「开局 / 终局」入口（幂等；**有活动局 → 隐藏**）。

        * 无局 → 引导 + 「今晚留下来」；
        * 终局（``status == "ended"``）→ 余韵引导 + 「再来一夜」；
        * 有活动局 → 整块隐藏（避免重复开局）。

        同时把叙述流空态文案切成与状态相符的一版（无局才指向开局入口，避免误导）。
        """
        status = self._play_status()
        if status == "ended":
            hint, button = ENDED_HINT_TEXT, RESTART_BTN_TEXT
            visible = True
        elif status:
            hint, button, visible = "", "", False
        else:
            hint, button, visible = START_HINT_TEXT, START_BTN_TEXT, True

        self._start_hint.setText(hint)
        self._start_btn.setText(_decorate("glass", button))
        self._start_panel.setVisible(visible)

        set_hint = getattr(self.narrative, "set_empty_text", None)
        if callable(set_hint):
            try:
                set_hint(NARRATIVE_EMPTY_HINT if not status else NARRATIVE_IDLE_HINT)
            except Exception:
                logger.debug("酒馆页设置叙述流空态文案失败（忽略）", exc_info=True)

    def _on_start_clicked(self) -> None:
        """开局 / 再来一夜：调 ``service.start_play(book_id)``（``book_id`` 从内容包集中取）。"""
        status = self._play_status()
        if status and status != "ended":
            return  # 已有活动局：入口本应隐藏，防御性拒绝重复开局
        fn = getattr(self.service, "start_play", None)
        if not callable(fn):
            return
        try:
            fn(self._current_book_id())
        except Exception:
            logger.debug("酒馆开局失败（忽略）", exc_info=True)
        self._sync_start_entry()

    def _on_play_changed(self, *_args: Any) -> None:
        """``play_changed`` → 重切开局 / 终局入口（开局、载入、终局落定都走这里）。"""
        self._sync_start_entry()

    # ==================================================================
    # 文本级操作（重写 / 改字；状态一动不动，§5.2）
    # ==================================================================
    def _narrator_entry(self) -> Dict[str, Any]:
        """最近一拍的说书人条目（读 :meth:`TavernService.current_narrative`；无 → 空 dict）。"""
        try:
            entries = self.service.current_narrative()
        except Exception:
            logger.debug("读取酒馆叙述面失败（忽略）", exc_info=True)
            return {}
        if not isinstance(entries, (list, tuple)):
            return {}
        for entry in reversed(entries):
            if isinstance(entry, dict) and entry.get("role") == "narrator":
                return entry
        return {}

    @staticmethod
    def _entry_turn(entry: Dict[str, Any]) -> int:
        """条目里的 ``turn``（非 ``int`` / ``bool`` → ``-1``）。"""
        turn = entry.get("turn")
        if isinstance(turn, int) and not isinstance(turn, bool):
            return turn
        return -1

    def _on_reroll_clicked(self) -> None:
        """「重写这一拍」：请求重跑最近一拍的**叙述**（经控件转发，绝不在此直连服务）。"""
        entry = self._narrator_entry()
        turn = self._entry_turn(entry)
        if turn < 0:
            return
        try:
            self.narrative.reroll(turn)
        except Exception:
            logger.debug("酒馆重写请求失败（忽略）", exc_info=True)

    def _on_edit_clicked(self) -> None:
        """「改这一拍的字」：就地改最近一拍的**叙述文本**（只允许改文本）。"""
        entry = self._narrator_entry()
        turn = self._entry_turn(entry)
        if turn < 0:
            return
        current = entry.get("text")
        current = current if isinstance(current, str) else ""
        text, ok = QInputDialog.getMultiLineText(
            self, EDIT_DIALOG_TITLE, EDIT_DIALOG_LABEL, current
        )
        if not ok:
            return
        new_text = (text or "").strip()
        if not new_text or new_text == current:
            return
        try:
            self.narrative.edit_text(turn, new_text)
        except Exception:
            logger.debug("酒馆改字请求失败（忽略）", exc_info=True)

    # ==================================================================
    # 设置行（私有设置落 tavern.json.settings；不改 GuiConfig）
    # ==================================================================
    def sync_settings_row(self) -> None:
        """从 ``service.get_settings()`` 回读设置行（幂等；不回写）。"""
        try:
            settings = self.service.get_settings()
        except Exception:
            logger.debug("读取酒馆设置失败（忽略）", exc_info=True)
            settings = {}
        if not isinstance(settings, dict):
            settings = {}

        allow = settings.get("allow_propose", True)
        budget = settings.get("worldbook_budget_chars", BUDGET_DEFAULT)
        if not isinstance(budget, int) or isinstance(budget, bool):
            budget = BUDGET_DEFAULT

        self._settings_sync = True
        try:
            self.allow_propose_check.setChecked(bool(allow))
            self.budget_spin.setValue(min(max(budget, BUDGET_MIN), BUDGET_MAX))
        finally:
            self._settings_sync = False

    def _on_allow_propose_toggled(self, checked: bool) -> None:
        """勾选变化 → 写 ``tavern.json.settings.allow_propose``。"""
        if self._settings_sync:
            return
        self._set_setting(allow_propose=bool(checked))

    def _on_budget_changed(self, value: int) -> None:
        """预算变化 → 写 ``tavern.json.settings.worldbook_budget_chars``。"""
        if self._settings_sync:
            return
        self._set_setting(worldbook_budget_chars=int(value))

    def _set_setting(self, **kwargs: Any) -> None:
        """经 ``service.set_settings`` 落盘（只接受已知键 + 类型相符者；异常不崩）。"""
        fn = getattr(self.service, "set_settings", None)
        if not callable(fn):
            return
        try:
            fn(**kwargs)
        except Exception:
            logger.debug("写入酒馆设置失败（忽略）", exc_info=True)

    # ==================================================================
    # 生命周期 / 只读查询
    # ==================================================================
    def on_enter(self) -> None:
        """PageManager 生命周期钩子：整体刷新（服务广播 → 各控件自建，§4.6）。"""
        try:
            self.service.refresh()
        except Exception:
            logger.debug("酒馆服务整体刷新失败（忽略）", exc_info=True)
        self.sync_settings_row()
        self._sync_start_entry()
        self.refresh_cast()

    def tab_titles(self) -> List[str]:
        """当前 5 个 Tab 的标题（运行期实测值，供接线方 / 测试核对顺序）。"""
        return [self.tabs.tabText(i) for i in range(self.tabs.count())]
