"""gui/pages/page_memory_book.py —— v1.6 P0-1 透明记忆中心页（D-V16-02）。

三分区（Tab）：主人偏好 / 活跃话题 / 情绪记录。
- 数据源唯一 = app_ctx.session.memory_mgr（GuiChatSession __getattr__ 透传）；
  页面只调 MemoryManager 既有/新增方法，**禁止直改 _data**（共享知识 19）。
- 每次增删改后：manager 自身已 _save() 落盘（原子写）+ 调
  app_ctx.session.refresh_system_context()（删除即遗忘当轮生效，R-I）。
- 双角标（Q-B1）：来源（自动记下 / 你告诉我的 / 早期记忆）+ 最近提及/更新
  相对时间（"3 天前提到"式）。
- 红线内建（R-A）：无条目计数徽章、无容量条、无进度、无打卡语义；
  底部固定隐私脚注（R-I）。page_memories.py（高光回忆册）零改动、零引用。
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from gui import icons
from gui.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, Qt, QMessageBox, QInputDialog, QTabWidget, QSize,
)
from gui.utils import theme_color
from gui.widgets.emotion_arc import EmotionArcWidget  # v1.8(F2/D-V18-03)

logger = logging.getLogger("maid_coder.gui")

# --- v2.1(V21-12/D-V21-06): 矢量图标统一 -------------------------------------
# 图标位只记「图标名 + 尺寸 + 取色（走 theme_color）」；字体不可用时回落原 emoji，
# 绝不空白（D-V21-06 回退链）。取色一律 theme_color（共享知识 §6 第 4 条）。
_TAB_ICON_SIZE = 16
_BTN_ICON_SIZE = 14
_TITLE_ICON_SIZE = 14

# 8 Tab 图标名（顺序 = addTab 顺序；group 用于分组着色，D-V18-09 零改动）
# (clean_text, fallback_text, icon_name, group)
_TAB_DEFS = (
    ("主人偏好", "主人偏好", "pref", "memory"),
    ("活跃话题", "活跃话题", "topic", "memory"),
    ("情绪记录", "情绪记录", "emotion", "memory"),
    ("人物关系", "人物关系", "people", "memory"),
    ("回应约定", "回应约定 📌", "response", "memory"),
    ("共同经历", "共同经历 🌟", "auto_awesome", "story"),
    ("往期回顾", "往期回顾", "history", "story"),
    ("她的日记", "她的日记", "diary", "diary"),
)

# 动作按钮 emoji 前缀 → 矢量图标名（图标可用时剥掉前缀 emoji）
_ACTION_ICONS = (
    ("✏️", "edit"),
    ("📌", "bookmark"),
    ("🗑", "delete"),
    ("➕", "add"),
    ("▶️", "check"),
    ("⏸", "stop"),
    ("🙈", "eye_off"),
    ("🖼", "image"),
)


def _vector_icon(app_ctx, name: str, size: int, color: Optional[str]):
    """取矢量 ``QIcon``；字体/名字不可用或渲染失败 → ``None``（调用方回落 emoji）。"""
    try:
        if not name or not icons.available() or not icons.has(name):
            return None
        ic = icons.icon(name, size, color)
        if ic is None or ic.isNull():
            return None
        return ic
    except Exception:
        return None


def _decorate_button(btn: QPushButton, app_ctx, name: str, clean_text: str,
                     fallback_text: str, size: int = _BTN_ICON_SIZE) -> None:
    """给按钮挂矢量图标（取色 ``accent``）并去掉文案 emoji；不可用回落 ``fallback_text``。"""
    ic = _vector_icon(app_ctx, name, size, theme_color(app_ctx, "accent", "#FF6B9D"))
    if ic is not None:
        btn.setIcon(ic)
        btn.setText(clean_text)
    else:
        btn.setText(fallback_text)


def _decorate_action_label(label: str):
    """按 emoji 前缀解析动作按钮文案 → ``(icon_name_or_None, clean_text)``。"""
    for emoji, name in _ACTION_ICONS:
        if label.startswith(emoji):
            rest = label[len(emoji):].lstrip()
            return name, rest
    return None, label

# 来源角标（Q-B1）：legacy 显示「早期记忆」——绝不把机器提取误标为「你告诉我的」
_SOURCE_LABELS = {
    "auto": "自动记下",
    "manual": "你告诉我的",
    "legacy": "早期记忆",
}

# v1.8(D-V18-01): 实体来源角标（assistant_proposed = 提议-确认链确认后才写入）
_ENTITY_SOURCE_LABELS = {
    "manual": "你告诉我的",
    "assistant_proposed": "码铃问过你之后记下的",
}

# v1.8(D-V18-01): 关系类型预设（开放枚举：预设 + 自定义文本）
_ENTITY_RELATION_PRESETS = ("同事", "朋友", "家人", "恋人", "同学", "其他")

# v1.8(F3/D-V18-04): 时间线节点类型 -> 矢量图标名 + 回落 emoji + 说明
# v2.1(V21-12): 图标名统一走 icons.icon（字体不可用时回落 emoji）
_TIMELINE_KIND_META = {
    "highlight": ("star", "✨", "收藏的高光"),
    "topic": ("check", "✅", "一起完成的事"),
    "anniversary": ("cake", "🎂", "值得记着的日子"),
    "weekly": ("bookmark", "📒", "那一周的小结"),
}

_EMOTION_LABELS = {
    "tired": "疲惫", "happy": "开心", "anxious": "焦虑",
    "lonely": "孤单", "normal": "平静",
}


def _memory_mgr_of(app_ctx):
    """取 MemoryManager（session 可能缺失/为 GuiChatSession，透传即可）。"""
    session = getattr(app_ctx, "session", None)
    return getattr(session, "memory_mgr", None) if session is not None else None


def _refresh_system_context(app_ctx) -> None:
    """增删改后的当轮刷新（删除即遗忘，R-I）；session 缺失时静默。"""
    session = getattr(app_ctx, "session", None)
    if session is not None and callable(getattr(session, "refresh_system_context", None)):
        try:
            session.refresh_system_context()
        except Exception as exc:
            logger.debug("refresh_system_context 失败（可忽略）: %s", exc)


def _relative_time(iso: str) -> str:
    """ISO → 「3 天前提到」式相对时间；空/非法返回空串。"""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(str(iso))
    except (TypeError, ValueError):
        return ""
    delta = datetime.now() - dt
    seconds = delta.total_seconds()
    if seconds < 0:
        return "刚刚"
    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return f"{int(seconds // 60)} 分钟前"
    if seconds < 86400:
        return f"{int(seconds // 3600)} 小时前"
    days = int(seconds // 86400)
    if days < 30:
        return f"{days} 天前"
    return dt.strftime("%Y-%m-%d")


class _EntryCard(QFrame):
    """记忆中心单条目卡：标题 + 角标行 + 动作按钮区。"""

    def __init__(self, app_ctx, title: str, badge: str,
                 actions: List[tuple], icon_name: str = "", prefix: str = "",
                 parent: Optional[QWidget] = None):
        """actions: [(label, tooltip, callback)]。

        v2.1(V21-12): ``icon_name`` 为标题矢量图标名（取色 accent）；字体不可用时
        回落 ``prefix`` emoji 前缀（``title`` 保持纯文案，由本卡决定是否加前缀）。
        """
        super().__init__(parent)
        self.app_ctx = app_ctx
        self.setObjectName("memoryBookCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(6)
        ic = (_vector_icon(app_ctx, icon_name, _TITLE_ICON_SIZE,
                           theme_color(app_ctx, "accent", "#FF6B9D"))
              if icon_name else None)
        if ic is not None:
            icon_lab = QLabel()
            icon_lab.setObjectName("memoryBookTitleIcon")
            icon_lab.setFixedSize(_TITLE_ICON_SIZE, _TITLE_ICON_SIZE)
            icon_lab.setPixmap(ic.pixmap(_TITLE_ICON_SIZE, _TITLE_ICON_SIZE))
            head.addWidget(icon_lab)
            title_text = title
        else:
            title_text = f"{prefix}{title}" if prefix else title
        title_lab = QLabel(title_text)
        title_lab.setObjectName("memoryBookTitle")
        title_lab.setWordWrap(True)
        title_lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        head.addWidget(title_lab, 1)
        for label, tooltip, cb in actions:
            btn = QPushButton(label)
            btn.setObjectName("memoryBookBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(tooltip)
            ic_name, clean = _decorate_action_label(label)
            if ic_name:
                _decorate_button(btn, app_ctx, ic_name, clean, label)
            btn.clicked.connect(lambda checked=False, f=cb: f())
            head.addWidget(btn)
        lay.addLayout(head)

        badge_lab = QLabel(badge)
        badge_lab.setObjectName("memoryBookBadge")
        lay.addWidget(badge_lab)
        self._apply_style()

    def _apply_style(self) -> None:
        bg = theme_color(self.app_ctx, "bg_card", "#FFFFFF")
        border = theme_color(self.app_ctx, "divider", "#EFE0E2")
        text = theme_color(self.app_ctx, "text", "#5D4037")
        secondary = theme_color(self.app_ctx, "text_secondary", "#8A8A8A")
        accent = theme_color(self.app_ctx, "accent", "#FF6B9D")
        self.setStyleSheet(
            f"QFrame#memoryBookCard {{ background: {bg}; border: 1px solid {border};"
            f" border-radius: 10px; }}"
            f"QLabel#memoryBookTitle {{ color: {text}; font-size: 13px;"
            f" background: transparent; }}"
            f"QLabel#memoryBookBadge {{ color: {secondary}; font-size: 11px;"
            f" background: transparent; }}"
            f"QPushButton#memoryBookBtn {{ background: transparent; color: {accent};"
            f" border: 1px solid {border}; border-radius: 6px; font-size: 11px;"
            f" padding: 3px 10px; }}"
            f"QPushButton#memoryBookBtn:hover {{ background: {border}; }}"
        )


class PageMemoryBook(QWidget):
    """记忆中心页：偏好 / 话题 / 情绪 三分区 + 隐私脚注。"""

    def __init__(self, app_context, title: str = "记忆中心", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app_ctx = app_context
        self._list_widgets: List[QWidget] = []
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 16)
        outer.setSpacing(10)

        head_row = QHBoxLayout()
        title = QLabel("记忆中心")
        title.setObjectName("pageTitle")
        f = title.font()
        f.setBold(True)
        title.setFont(f)
        head_row.addWidget(title)
        head_row.addStretch()
        outer.addLayout(head_row)

        sub = QLabel("码铃记下的关于主人的小事，都摊开在这里——随时看、随时改、随时忘。")
        sub.setObjectName("memoryBookSub")
        sub.setWordWrap(True)
        outer.addWidget(sub)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("memoryBookTabs")
        outer.addWidget(self.tabs, 1)

        # v1.8(D-V18-09/Q-D2): 8 Tab 平铺 + 分组着色（本批补齐「回应约定」满 8）。
        # 既有五 Tab 数据链零改动（R-D）。
        self._timeline_months = 6   # F3 时间线回看窗口（「展开更早」+6 递增）
        self._build_pref_tab()
        self._build_topic_tab()
        self._build_emotion_tab()
        self._build_entity_tab()    # v1.8(F1/D-V18-01) 人物关系
        self._build_rules_tab()     # v1.8(F6/D-V18-05) 回应约定
        self._build_timeline_tab()  # v1.8(F3/D-V18-04) 共同经历
        self._build_weekly_tab()
        self._build_diary_tab()

        # 底部固定隐私脚注（R-I）
        self.privacy_label = QLabel(
            f"{icons.text_glyph('menu_book', '📔')} 这里的一切只存于你的电脑，删除立即生效。")
        self.privacy_label.setObjectName("memoryBookPrivacy")
        outer.addWidget(self.privacy_label)

        self.refresh()
        self._apply_style()

    # -- Tab 骨架 --
    def _make_scroll_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(2, 8, 2, 8)
        lay.setSpacing(8)
        lay.addStretch()
        scroll.setWidget(host)
        scroll._host = host          # type: ignore[attr-defined]
        scroll._lay = lay            # type: ignore[attr-defined]
        return scroll

    def _build_pref_tab(self) -> None:
        tab = self._make_scroll_tab()
        add_row = QHBoxLayout()
        add_btn = QPushButton("➕ 添加偏好")
        add_btn.setObjectName("memoryBookBtn")
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.setToolTip("告诉码铃一件关于你的事（例如：叫我小远）")
        add_btn.clicked.connect(self._on_add_preference)
        _decorate_button(add_btn, self.app_ctx, "add", "添加偏好", "➕ 添加偏好")
        add_row.addWidget(add_btn)
        add_row.addStretch()
        idx = max(0, tab._lay.count() - 1)  # type: ignore[attr-defined]
        tab._lay.insertLayout(idx, add_row)  # type: ignore[attr-defined]
        self.pref_tab = tab
        self.tabs.addTab(tab, "主人偏好")

    def _build_topic_tab(self) -> None:
        self.topic_tab = self._make_scroll_tab()
        self.tabs.addTab(self.topic_tab, "活跃话题")

    def _build_emotion_tab(self) -> None:
        self.emotion_tab = self._make_scroll_tab()
        self.tabs.addTab(self.emotion_tab, "情绪记录")

    def _build_weekly_tab(self) -> None:
        self.weekly_tab = self._make_scroll_tab()
        self.tabs.addTab(self.weekly_tab, "往期回顾")

    # -- v1.8(F1/D-V18-01): 人物关系（记忆图谱）分区 --
    def _build_entity_tab(self) -> None:
        tab = self._make_scroll_tab()
        add_row = QHBoxLayout()
        add_btn = QPushButton("➕ 记下一位重要的人")
        add_btn.setObjectName("memoryBookBtn")
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.setToolTip("告诉码铃一位你身边重要的人（同事/朋友/家人……）")
        add_btn.clicked.connect(self._on_add_entity)
        _decorate_button(add_btn, self.app_ctx, "user_add", "记下一位重要的人",
                         "➕ 记下一位重要的人")
        add_row.addWidget(add_btn)
        add_row.addStretch()
        idx = max(0, tab._lay.count() - 1)  # type: ignore[attr-defined]
        tab._lay.insertLayout(idx, add_row)  # type: ignore[attr-defined]
        self.entity_tab = tab
        self.tabs.addTab(tab, "人物关系")

    # -- v1.8(F6/D-V18-05/Q-D9): 回应约定分区（第 8 分区，双入口之记忆中心侧）--
    def _build_rules_tab(self) -> None:
        tab = self._make_scroll_tab()
        add_row = QHBoxLayout()
        add_btn = QPushButton("➕ 添加约定")
        add_btn.setObjectName("memoryBookBtn")
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.setToolTip("告诉码铃一条小约定（例如：以后我说「上线了」你要说「辛苦了」）")
        add_btn.clicked.connect(self._on_add_rule)
        _decorate_button(add_btn, self.app_ctx, "add", "添加约定", "➕ 添加约定")
        add_row.addWidget(add_btn)
        add_row.addStretch()
        idx = max(0, tab._lay.count() - 1)  # type: ignore[attr-defined]
        tab._lay.insertLayout(idx, add_row)  # type: ignore[attr-defined]
        self.rules_tab = tab
        self.tabs.addTab(tab, "回应约定 📌")

    # -- v1.8(F3/D-V18-04): 共同经历时间线分区（只读视图，无编辑）--
    def _build_timeline_tab(self) -> None:
        tab = self._make_scroll_tab()
        op_row = QHBoxLayout()
        expand_btn = QPushButton("⏪ 展开更早")
        expand_btn.setObjectName("memoryBookBtn")
        expand_btn.setCursor(Qt.PointingHandCursor)
        expand_btn.setToolTip("再多看半年的共同经历")
        expand_btn.clicked.connect(self._on_expand_timeline)
        _decorate_button(expand_btn, self.app_ctx, "history", "展开更早", "⏪ 展开更早")
        op_row.addWidget(expand_btn)
        op_row.addStretch()
        idx = max(0, tab._lay.count() - 1)  # type: ignore[attr-defined]
        tab._lay.insertLayout(idx, op_row)  # type: ignore[attr-defined]
        self.timeline_tab = tab
        self.tabs.addTab(tab, "共同经历 🌟")

    def _on_expand_timeline(self) -> None:
        """「展开更早」按 6 个月分段追加（Q-D10：不做无限滚动）。"""
        self._timeline_months += 6
        self.refresh()

    # -- v1.7(F7/D-V17-05): 她的日记（第 5 分区，按月分组倒序翻阅 + 导出）--
    def _build_diary_tab(self) -> None:
        tab = self._make_scroll_tab()
        op_row = QHBoxLayout()
        export_btn = QPushButton("📄 导出 Markdown")
        export_btn.setObjectName("memoryBookBtn")
        export_btn.setCursor(Qt.PointingHandCursor)
        export_btn.setToolTip("把日记导出为 Markdown 文件（自选目录）")
        export_btn.clicked.connect(self._on_export_diary)
        _decorate_button(export_btn, self.app_ctx, "export", "导出 Markdown", "📄 导出 Markdown")
        op_row.addWidget(export_btn)
        op_row.addStretch()
        idx = max(0, tab._lay.count() - 1)  # type: ignore[attr-defined]
        tab._lay.insertLayout(idx, op_row)  # type: ignore[attr-defined]
        self.diary_tab = tab
        self.tabs.addTab(tab, "她的日记")

    def _diary_mgr(self):
        """app 级 DiaryManager 单例（main 装配时挂 app_ctx.diary）。"""
        mgr = getattr(self.app_ctx, "diary", None)
        if mgr is not None:
            return mgr
        try:
            from diary import DiaryManager
            mgr = DiaryManager()
            self.app_ctx.diary = mgr
        except Exception as exc:
            logger.debug("DiaryManager 懒装配失败（Tab 空态）: %s", exc)
            mgr = None
        return mgr

    def _diary_month_label(self, date: str) -> str:
        """date（YYYY-MM-DD）→「M月」。"""
        try:
            d = datetime.strptime(str(date), "%Y-%m-%d")
            return f"{d.month} 月"
        except (TypeError, ValueError):
            return "那些日子"

    def _refresh_diary(self) -> None:
        """她的日记（按月分组、时间倒序翻阅；无 R-A 计数语义）。"""
        note = QLabel(
            "码铃会在第二天安静地写下昨天的小日子。\n"
            "写不成的日子就先空着，之后有机会再补上。")
        note.setObjectName("memoryBookBadge")
        note.setWordWrap(True)
        self._insert_card(self.diary_tab, note)
        mgr = self._diary_mgr()
        entries: List[dict] = []
        if mgr is not None:
            try:
                entries = mgr.list_entries() or []
            except Exception as exc:
                logger.warning("读取日记失败: %s", exc)
        if not entries:
            self._insert_card(self.diary_tab, self._empty_label(
                "还没有日记，明天开始她会记下你们的故事。"))
            return
        current_month: str = ""
        for e in entries:
            month = self._diary_month_label(str(e.get("date", "")))
            if month != current_month:
                current_month = month
                badge = QLabel(month)
                badge.setObjectName("memoryBookBadge")
                self._insert_card(self.diary_tab, badge)
            mood = str(e.get("mood", "")).strip()
            body = str(e.get("content", "")).strip()
            badge = (f"心情：{mood}\n{body}" if mood else body)
            self._insert_card(self.diary_tab, _EntryCard(
                self.app_ctx, str(e.get("date", "")),
                badge or "（这一篇没写完。）", []))

    def _on_export_diary(self) -> None:
        """导出 Markdown（单篇/全部 → 全部；QFileDialog 自选目录，纯 stdlib）。"""
        mgr = self._diary_mgr()
        if mgr is None:
            return
        try:
            from gui.qt_compat import QFileDialog, QMessageBox
            directory = QFileDialog.getExistingDirectory(
                self, "选择导出目录", str(Path.home()))
            if not directory:
                return
            out = mgr.export_markdown(str(Path(directory) / "她的日记.md"))
            QMessageBox.information(self, "导出完成", f"已导出到：\n{out}")
        except Exception as exc:
            logger.warning("日记导出失败: %s", exc)

    def _weekly_mgr(self):
        """app 级 WeeklyReviewManager 单例（main 装配时挂 app_ctx.weekly）。"""
        mgr = getattr(self.app_ctx, "weekly", None)
        if mgr is not None:
            return mgr
        try:
            from weekly import WeeklyReviewManager
            mgr = WeeklyReviewManager()
            self.app_ctx.weekly = mgr
        except Exception as exc:
            logger.debug("WeeklyReviewManager 懒装配失败（Tab 空态）: %s", exc)
            mgr = None
        return mgr

    def _week_label(self, week_start: str) -> str:
        """周一键 → 「本周」/「M月D日 那一周」（R-A：绝不出现「第 N 周」）。"""
        try:
            d = datetime.strptime(str(week_start), "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return "那段时间"
        today = datetime.now().date()
        monday = today.toordinal() - today.weekday()
        if d.toordinal() == monday:
            return "本周"
        return f"{d.month} 月 {d.day} 日那一周"

    def _refresh_weekly(self) -> None:
        """往期回顾（时间倒序翻阅；无任何记录给软空态）。"""
        note = QLabel(
            "每个周日傍晚，码铃会悄悄把这周的小事整理好。\n"
            "没有提醒、没有任务，什么时候想翻就翻一翻。")
        note.setObjectName("memoryBookBadge")
        note.setWordWrap(True)
        self._insert_card(self.weekly_tab, note)
        mgr = self._weekly_mgr()
        reviews: List[dict] = []
        if mgr is not None:
            try:
                reviews = mgr.list_reviews() or []
            except Exception as exc:
                logger.warning("读取往期回顾失败: %s", exc)
        if not reviews:
            self._insert_card(self.weekly_tab, self._empty_label(
                "还没有回顾。\n等第一个周日过后，这里就会有第一份小小的周记~"))
            self._refresh_vision_entries()
            return
        for r in reviews:
            sk = r.get("skeleton") or {}
            body = r.get("polished") or ""
            if not str(body).strip():
                lines = []
                pace = str(sk.get("pace", "")).strip()
                if pace:
                    lines.append(f"这是{pace}。")
                stage = str(sk.get("relation_stage", "")).strip()
                if stage:
                    lines.append(f"我们正处在「{stage}」的时光里。")
                done = [str(s) for s in (sk.get("done_topics") or []) if str(s).strip()]
                new = [str(s) for s in (sk.get("new_topics") or []) if str(s).strip()]
                if done:
                    lines.append("完成的事：" + "、".join(done) + "，干得漂亮~")
                if new:
                    lines.append("最近聊起：" + "、".join(new))
                mood_note = str(sk.get("mood_note", "")).strip()
                if mood_note:
                    lines.append(mood_note)
                for h in (sk.get("highlights") or []):
                    text = str(h.get("text", "")).strip()
                    if text:
                        lines.append(f"{icons.text_glyph('auto_awesome', '✨')} 「{text}」")
                body = "\n".join(lines)
            self._insert_card(self.weekly_tab, _EntryCard(
                self.app_ctx, self._week_label(r.get("week_start", "")),
                str(body or "这一周安安静静地过去了。"), []))
        self._refresh_vision_entries()

    # -- ⑦ v1.8(V18-16/D-V18-08): F7 影像记忆条目（「往期回顾」Tab 内文字卡）--
    # 最小方案（Q-D8）：文字卡、无缩略图、无专属图片化 UI（v1.8 Non-goals 明确
    # 不做图片墙类功能）；
    # 只呈现"对话事实"（配文 + 当时回应 + 中性描述），绝不出现图像数据（R-I）；
    # 删除走删除即遗忘链（物理移除 + 当轮 refresh_system_context）。
    def _refresh_vision_entries(self) -> None:
        """影像记忆条目渲染（无任何影像记忆时零噪音，不打扰既有周记流）。"""
        mgr = _memory_mgr_of(self.app_ctx)
        if mgr is None or not hasattr(mgr, "list_vision_memories"):
            return
        try:
            visions = mgr.list_vision_memories() or []
        except Exception as exc:
            logger.warning("读取影像记忆失败: %s", exc)
            return
        if not visions:
            return
        badge = QLabel(
            f"{icons.text_glyph('image', '🖼')} 那些发过的图（码铃只记得当时的对话，图片本身没有留下）")
        badge.setObjectName("memoryBookBadge")
        badge.setWordWrap(True)
        self._insert_card(self.weekly_tab, badge)
        for v in visions:
            if not isinstance(v, dict) or not v.get("id"):
                continue
            vid = str(v.get("id"))
            try:
                d = datetime.fromisoformat(str(v.get("time", "")))
                head = f"{d.month}-{d.day:02d} 的分享"
            except (TypeError, ValueError):
                head = "一次分享"
            bits: List[str] = []
            utext = str(v.get("user_text", "")).strip()
            if utext:
                bits.append(f"配文：{utext}")
            digest = str(v.get("assistant_digest", "")).strip()
            if digest:
                bits.append(f"当时码铃回应：{digest}")
            note = str(v.get("image_note", "")).strip()
            if note:
                bits.append(note)
            rel = _relative_time(v.get("time", ""))
            if rel:
                bits.append(f"{rel}分享")
            actions = [("🗑 删除", "码铃会立刻忘掉这次分享（立即生效）",
                        lambda i=vid: self._on_delete_vision(i))]
            self._insert_card(self.weekly_tab, _EntryCard(
                self.app_ctx, head, "\n".join(bits) or "一次小小的分享。", actions,
                icon_name="image", prefix="🖼 "))

    def _on_delete_vision(self, vision_id: str) -> None:
        """删除影像记忆（删除即遗忘：物理移除 + 当轮 refresh_system_context，R-I）。"""
        mgr = _memory_mgr_of(self.app_ctx)
        if mgr is None or not hasattr(mgr, "delete_vision_memory"):
            return
        box = QMessageBox(self)
        box.setWindowTitle("删除分享记忆")
        box.setIcon(QMessageBox.Question)
        box.setText("忘掉这次分享？\n码铃会立刻忘记当时的对话内容（不可恢复）。")
        yes = box.addButton("忘掉", QMessageBox.DestructiveRole)
        box.addButton("再想想", QMessageBox.RejectRole)
        box.exec_()
        if box.clickedButton() is not yes:
            return
        try:
            mgr.delete_vision_memory(vision_id)
        except Exception as exc:
            logger.warning("删除影像记忆失败: %s", exc)
            return
        _refresh_system_context(self.app_ctx)
        self.refresh()

    def _on_arc_day_clicked(self, date_iso: str) -> None:
        """点击弧线日格 -> 展示那一天的条目（档位词 + 原文摘录，零计数）。"""
        label = getattr(self, "_arc_day_label", None)
        arc = getattr(self, "_arc_widget", None)
        if label is None or arc is None:
            return
        mgr = _memory_mgr_of(self.app_ctx)
        history: List[dict] = []
        if mgr is not None and hasattr(mgr, "get_emotions_history"):
            try:
                history = mgr.get_emotions_history() or []
            except Exception:
                history = []
        lines = []
        for e in history:
            if not str(e.get("time", "")).startswith(str(date_iso)):
                continue
            label_word = _EMOTION_LABELS.get(str(e.get("emotion", "")), "有些心事")
            excerpt = str(e.get("excerpt", "") or "").strip()
            lines.append(f"· {label_word}" + (f" ——「{excerpt}」" if excerpt else ""))
        try:
            d = datetime.fromisoformat(str(date_iso)).date()
            head = f"{d.month} 月 {d.day} 日那天"
        except (TypeError, ValueError):
            head = "那天"
        if lines:
            label.setText(f"{head}：" + "\n".join(lines))
        else:
            label.setText(f"{head}的心情，已经先一步被主人删掉啦。")
        label.setVisible(True)

    # -- ④ v1.8(F1/D-V18-01) 人物关系 --
    def _refresh_entities(self) -> None:
        note = QLabel(
            "这些是主人身边重要的人。码铃只在聊到他们时才想起，"
            "平时不会主动提起；删掉就会立刻忘掉。")
        note.setObjectName("memoryBookBadge")
        note.setWordWrap(True)
        self._insert_card(self.entity_tab, note)
        mgr = _memory_mgr_of(self.app_ctx)
        entities: List[dict] = []
        if mgr is not None and hasattr(mgr, "list_entities"):
            try:
                entities = mgr.list_entities() or []
            except Exception as exc:
                logger.warning("读取人物关系失败: %s", exc)
        if not entities:
            self._insert_card(self.entity_tab, self._empty_label(
                f"还没有记下谁。\n点上面的「{icons.text_glyph('add', '➕')} 记下一位重要的人」，"
                "或聊天时自然地提起他们~"))
            return
        for ent in entities:
            eid = str(ent.get("id", ""))
            name = str(ent.get("name", ""))
            relation = str(ent.get("relation", "其他"))
            source = str(ent.get("source", "manual"))
            badge_bits = [relation, _ENTITY_SOURCE_LABELS.get(source, "你告诉我的")]
            rel = _relative_time(ent.get("updated_at", ""))
            if rel:
                badge_bits.append(f"{rel}更新")
            badge_text = "（" + " · ".join(badge_bits) + "）"
            notes = str(ent.get("notes", "") or "").strip()
            if notes:
                badge_text += f"\n{notes}"
            for ev in (ent.get("events") or []):
                ev_text = str(ev.get("text", "")).strip()
                ev_date = str(ev.get("date", ""))
                date_label = ""
                try:
                    d = datetime.strptime(ev_date, "%Y-%m-%d").date()
                    date_label = f"（{d.month} 月 {d.day} 日）"
                except (TypeError, ValueError):
                    date_label = ""
                if ev_text:
                    badge_text += f"\n· {ev_text}{date_label}"
            pinned = bool(ent.get("pinned"))
            title = name
            prefix = "📌 " if pinned else "🙋 "
            icon_name = "bookmark" if pinned else "person"
            actions = [
                ("✏️ 修改", "修改名字 / 关系 / 备注", lambda i=eid: self._on_edit_entity(i)),
                ("➕ 记一件事", "记一件你们之间的事",
                 lambda i=eid: self._on_add_entity_event(i)),
                ("🗑 删除", "码铃会立刻忘掉这位（立即生效）",
                 lambda i=eid: self._on_delete_entity(i)),
            ]
            if ent.get("pinned"):
                actions.insert(1, ("📌 取消常驻", "不再在每次对话常驻提起这位",
                                   lambda i=eid: self._on_pin_entity(i, False)))
            else:
                actions.insert(1, ("📌 常驻", "码铃每次对话都会记得这位在场",
                                   lambda i=eid: self._on_pin_entity(i, True)))
            self._insert_card(self.entity_tab, _EntryCard(
                self.app_ctx, title, badge_text, actions,
                icon_name=icon_name, prefix=prefix))

    def _ask_entity_fields(self, name: str = "", relation: str = "其他",
                           notes: str = "") -> Optional[tuple]:
        """实体字段录入对话框（名字 / 关系预设+自定义 / 备注）。取消返回 None。"""
        name, ok = QInputDialog.getText(self, "这位的名字", "怎么称呼这位:",
                                        text=name)
        if not ok or not name.strip():
            return None
        items = list(_ENTITY_RELATION_PRESETS) + ["自定义…"]
        rel, ok = QInputDialog.getItem(self, "关系", "这位是主人的:",
                                       items, max(0, items.index(relation) if relation in items else 0),
                                       False)
        if not ok or not str(rel).strip():
            return None
        if rel == "自定义…":
            rel, ok = QInputDialog.getText(self, "自定义关系", "关系是（例如：室友）:")
            if not ok or not str(rel).strip():
                return None
        notes, ok = QInputDialog.getMultiLineText(
            self, "备注（可留空）", "想补充的小备注（例如：同组后端）:", text=notes)
        if not ok:
            return None
        return name.strip(), str(rel).strip(), notes

    def _on_add_entity(self) -> None:
        mgr = _memory_mgr_of(self.app_ctx)
        if mgr is None or not hasattr(mgr, "add_entity"):
            return
        fields = self._ask_entity_fields()
        if fields is None:
            return
        name, relation, notes = fields
        try:
            mgr.add_entity(name, relation=relation, notes=notes, source="manual")
        except ValueError as exc:
            QMessageBox.information(self, "先等等", str(exc))
            return
        except Exception as exc:
            logger.warning("添加实体失败: %s", exc)
            return
        _refresh_system_context(self.app_ctx)
        self.refresh()

    def _on_edit_entity(self, entity_id: str) -> None:
        mgr = _memory_mgr_of(self.app_ctx)
        if mgr is None or not hasattr(mgr, "update_entity"):
            return
        ent = mgr.get_entity(entity_id)
        if ent is None:
            return
        fields = self._ask_entity_fields(
            name=str(ent.get("name", "")),
            relation=str(ent.get("relation", "其他")),
            notes=str(ent.get("notes", "")))
        if fields is None:
            return
        name, relation, notes = fields
        try:
            mgr.update_entity(entity_id, name=name, relation=relation, notes=notes)
        except ValueError as exc:
            QMessageBox.information(self, "先等等", str(exc))
            return
        except Exception as exc:
            logger.warning("修改实体失败: %s", exc)
            return
        _refresh_system_context(self.app_ctx)
        self.refresh()

    def _on_pin_entity(self, entity_id: str, pinned: bool) -> None:
        mgr = _memory_mgr_of(self.app_ctx)
        if mgr is None or not hasattr(mgr, "pin_entity"):
            return
        try:
            mgr.pin_entity(entity_id, pinned)
        except Exception as exc:
            logger.warning("固定实体失败: %s", exc)
            return
        _refresh_system_context(self.app_ctx)
        self.refresh()

    def _on_add_entity_event(self, entity_id: str) -> None:
        mgr = _memory_mgr_of(self.app_ctx)
        if mgr is None or not hasattr(mgr, "add_entity_event"):
            return
        text, ok = QInputDialog.getMultiLineText(
            self, "记一件事", "记一件你们之间的事（例如：上周一起吃了火锅）:")
        if not ok or not text.strip():
            return
        try:
            mgr.add_entity_event(entity_id, text.strip())
        except ValueError as exc:
            QMessageBox.information(self, "先等等", str(exc))
            return
        except Exception as exc:
            logger.warning("记录事件失败: %s", exc)
            return
        self.refresh()

    def _on_delete_entity(self, entity_id: str) -> None:
        """删除人物（删除即遗忘：物理移除 + 当轮 refresh_system_context，R-I）。"""
        mgr = _memory_mgr_of(self.app_ctx)
        if mgr is None or not hasattr(mgr, "delete_entity"):
            return
        ent = mgr.get_entity(entity_id)
        name = str(ent.get("name", "")) if ent else "这位"
        box = QMessageBox(self)
        box.setWindowTitle("删除人物")
        box.setIcon(QMessageBox.Question)
        box.setText(f"忘掉「{name}」？\n连同记下的事一起删掉，码铃会立刻忘记（不可恢复）。")
        yes = box.addButton("忘掉", QMessageBox.DestructiveRole)
        box.addButton("再想想", QMessageBox.RejectRole)
        box.exec_()
        if box.clickedButton() is not yes:
            return
        try:
            mgr.delete_entity(entity_id)
        except Exception as exc:
            logger.warning("删除实体失败: %s", exc)
            return
        _refresh_system_context(self.app_ctx)
        self.refresh()

    # -- ④b v1.8(F6/D-V18-05) 回应约定 --
    def _refresh_rules(self) -> None:
        note = QLabel(
            "「以后我说 XX 你要 YY」这样的小约定记在这里。\n"
            "聊天时说到约定的话，码铃会按约定回应；删掉就立刻忘掉。")
        note.setObjectName("memoryBookBadge")
        note.setWordWrap(True)
        self._insert_card(self.rules_tab, note)
        mgr = _memory_mgr_of(self.app_ctx)
        rules: List[dict] = []
        if mgr is not None and hasattr(mgr, "list_rules"):
            try:
                rules = mgr.list_rules() or []
            except Exception as exc:
                logger.warning("读取回应约定失败: %s", exc)
        if not rules:
            self._insert_card(self.rules_tab, self._empty_label(
                f"还没有约定。\n点上面的「{icons.text_glyph('add', '➕')} 添加约定」，或聊天时说"
                "「以后我说 XX 你要 YY」~"))
            return
        for rule in rules:
            rid = str(rule.get("id", ""))
            trigger = str(rule.get("trigger", ""))
            response = str(rule.get("response", ""))
            enabled = bool(rule.get("enabled", True))
            source = str(rule.get("source", "manual"))
            bits = [f"当他说「{trigger}」时", _SOURCE_LABELS.get(source, "你告诉我的")]
            last_hit = rule.get("last_hit_at")
            if last_hit:
                rel = _relative_time(str(last_hit))
                if rel:
                    bits.append(f"上次生效：{rel}")   # 相对时间呈现原料，R-A 不计次数
            badge_text = "（" + " · ".join(bits) + "）"
            if response:
                badge_text += f"\n{response}"
            if not enabled:
                badge_text += "\n（已停用，暂时不生效）"
            actions = [
                ("▶️ 启用" if not enabled else "⏸ 停用",
                 "重新生效" if not enabled else "暂停生效（内容保留）",
                 lambda i=rid, e=enabled: self._on_toggle_rule(i, not e)),
                ("✏️ 修改", "修改约定内容", lambda i=rid: self._on_edit_rule(i)),
                ("🗑 删除", "码铃会立刻忘掉这条约定（立即生效）",
                 lambda i=rid: self._on_delete_rule(i)),
            ]
            title = trigger
            prefix = "📌 " if enabled else "⏸ "
            icon_name = "bookmark" if enabled else "stop"
            self._insert_card(self.rules_tab, _EntryCard(
                self.app_ctx, title, badge_text, actions,
                icon_name=icon_name, prefix=prefix))

    def _ask_rule_fields(self, trigger: str = "", response: str = "") -> Optional[tuple]:
        """规则字段录入对话框（触发词 / 回应风格）。取消返回 None。"""
        trigger, ok = QInputDialog.getText(
            self, "约定的话", "当他说（触发词，例如：上线了）:", text=trigger)
        if not ok or not trigger.strip():
            return None
        response, ok = QInputDialog.getMultiLineText(
            self, "要怎么回应", "码铃应该（例如：回复'辛苦了'，别给建议）:",
            text=response)
        if not ok:
            return None
        return trigger.strip(), response.strip()

    def _on_add_rule(self) -> None:
        mgr = _memory_mgr_of(self.app_ctx)
        if mgr is None or not hasattr(mgr, "add_rule"):
            return
        fields = self._ask_rule_fields()
        if fields is None:
            return
        try:
            mgr.add_rule(*fields, source="manual")
        except ValueError as exc:
            QMessageBox.information(self, "先等等", str(exc))
            return
        except Exception as exc:
            logger.warning("添加约定失败: %s", exc)
            return
        _refresh_system_context(self.app_ctx)
        self.refresh()

    def _on_edit_rule(self, rule_id: str) -> None:
        mgr = _memory_mgr_of(self.app_ctx)
        if mgr is None or not hasattr(mgr, "update_rule"):
            return
        rule = mgr.get_rule(rule_id)
        if rule is None:
            return
        fields = self._ask_rule_fields(
            trigger=str(rule.get("trigger", "")),
            response=str(rule.get("response", "")))
        if fields is None:
            return
        try:
            mgr.update_rule(rule_id, trigger=fields[0], response=fields[1])
        except ValueError as exc:
            QMessageBox.information(self, "先等等", str(exc))
            return
        except Exception as exc:
            logger.warning("修改约定失败: %s", exc)
            return
        _refresh_system_context(self.app_ctx)
        self.refresh()

    def _on_toggle_rule(self, rule_id: str, enabled: bool) -> None:
        mgr = _memory_mgr_of(self.app_ctx)
        if mgr is None or not hasattr(mgr, "update_rule"):
            return
        try:
            mgr.update_rule(rule_id, enabled=enabled)
        except Exception as exc:
            logger.warning("启停约定失败: %s", exc)
            return
        _refresh_system_context(self.app_ctx)
        self.refresh()

    def _on_delete_rule(self, rule_id: str) -> None:
        """删除约定（删除即遗忘：物理移除 + 当轮 refresh_system_context，R-I）。"""
        mgr = _memory_mgr_of(self.app_ctx)
        if mgr is None or not hasattr(mgr, "delete_rule"):
            return
        rule = mgr.get_rule(rule_id)
        trigger = str(rule.get("trigger", "")) if rule else "这条约定"
        box = QMessageBox(self)
        box.setWindowTitle("删除约定")
        box.setIcon(QMessageBox.Question)
        box.setText(f"忘掉「{trigger}」这条约定？\n码铃会立刻忘记（不可恢复）。")
        yes = box.addButton("忘掉", QMessageBox.DestructiveRole)
        box.addButton("再想想", QMessageBox.RejectRole)
        box.exec_()
        if box.clickedButton() is not yes:
            return
        try:
            mgr.delete_rule(rule_id)
        except Exception as exc:
            logger.warning("删除约定失败: %s", exc)
            return
        _refresh_system_context(self.app_ctx)
        self.refresh()

    # -- ⑤ v1.8(F3/D-V18-04) 共同经历时间线 --
    def _timeline_srcs(self) -> tuple:
        """时间线三源 + 周记（任何单源缺失静默，build_timeline 内部再兜底）。"""
        from gui.pages.page_memories import get_highlights_manager
        memory_mgr = _memory_mgr_of(self.app_ctx)
        highlights_mgr = get_highlights_manager(self.app_ctx)
        anniversary_src = getattr(self.app_ctx, "companion", None)
        weeks_mgr = self._weekly_mgr()
        return memory_mgr, highlights_mgr, anniversary_src, weeks_mgr

    def _refresh_timeline(self) -> None:
        note = QLabel(
            "一起走过的事，按月轻轻排开。\n"
            "删掉源头（收藏的高光 / 话题），这里也会跟着一起忘掉。")
        note.setObjectName("memoryBookBadge")
        note.setWordWrap(True)
        self._insert_card(self.timeline_tab, note)
        try:
            import timeline as timeline_mod
            groups = timeline_mod.build_timeline(
                *self._timeline_srcs(), months=self._timeline_months)
        except Exception as exc:
            logger.warning("时间线聚合失败: %s", exc)
            groups = []
        if not groups:
            self._insert_card(self.timeline_tab, self._empty_label(
                "你们的故事刚开始写~\n收藏一条高光、聊完一件事，这里就会慢慢热闹起来。"))
            return
        for g in groups:
            month_badge = QLabel(str(g.get("label", "")))
            month_badge.setObjectName("memoryBookBadge")
            self._insert_card(self.timeline_tab, month_badge)
            for item in (g.get("items") or []):
                icon_name, emoji, _kind_label = _TIMELINE_KIND_META.get(
                    str(item.get("kind")), ("star", "🌟", ""))
                try:
                    d = item.get("date")
                    day_label = f"{d.month} 月 {d.day} 日"
                except Exception:
                    day_label = ""
                actions = []
                if str(item.get("kind")) == "weekly":
                    actions.append(("翻开那一周", "跳到往期回顾",
                                    lambda: self._goto_weekly_tab()))
                self._insert_card(self.timeline_tab, _EntryCard(
                    self.app_ctx, str(item.get("text", "")),
                    day_label, actions, icon_name=icon_name, prefix=f"{emoji} "))

    def _goto_weekly_tab(self) -> None:
        """周记节点点击 -> 跳往期回顾 Tab（D-V18-04 ④）。"""
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == "往期回顾":
                self.tabs.setCurrentIndex(i)
                return

    # ------------------------------------------------------------------
    def on_enter(self) -> None:
        """每次进入页面重读（数据可能被对话实时更新）。"""
        self.refresh()

    def refresh(self) -> None:
        """重建三分区列表（清掉上次插入的卡片/空态，重读数据）。"""
        for w in self._list_widgets:
            try:
                w.parentWidget().layout().removeWidget(w)
            except Exception:
                pass
            w.deleteLater()
        self._list_widgets = []
        self._refresh_prefs()
        self._refresh_topics()
        self._refresh_emotions()
        self._refresh_entities()
        self._refresh_rules()
        self._refresh_timeline()
        self._refresh_weekly()
        self._refresh_diary()
        self._apply_style()

    def _insert_card(self, tab, widget: QWidget) -> None:
        lay = tab._lay  # type: ignore[attr-defined]
        idx = max(0, lay.count() - 1)
        lay.insertWidget(idx, widget)
        self._list_widgets.append(widget)

    def _empty_label(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("memoryBookEmpty")
        lab.setAlignment(Qt.AlignCenter)
        lab.setWordWrap(True)
        return lab

    # -- ① 主人偏好 --
    def _refresh_prefs(self) -> None:
        mgr = _memory_mgr_of(self.app_ctx)
        prefs: dict = {}
        if mgr is not None:
            try:
                prefs = mgr.list_preferences() or {}
            except Exception as exc:
                logger.warning("读取偏好失败: %s", exc)
        if not prefs:
            self._insert_card(self.pref_tab, self._empty_label(
                f"还没有记下的偏好。\n点上面的「{icons.text_glyph('add', '➕')} 添加偏好」，或在聊天里自然地告诉码铃~"))
            return
        for key, item in prefs.items():
            value = item.get("value", "") if isinstance(item, dict) else str(item)
            source = item.get("source", "legacy") if isinstance(item, dict) else "legacy"
            updated = item.get("updated_at", "") if isinstance(item, dict) else ""
            badge = _SOURCE_LABELS.get(source, "早期记忆")
            rel = _relative_time(updated)
            badge_text = f"（{badge}）" + (f" · {rel} 更新" if rel else "")
            actions = [
                ("✏️ 修改", "修改这条偏好", lambda k=key: self._on_edit_preference(k)),
                ("🗑 删除", "删除这条偏好（立即生效）", lambda k=key: self._on_delete_preference(k)),
            ]
            self._insert_card(self.pref_tab, _EntryCard(
                self.app_ctx, f"{key}：{value}", badge_text, actions))

    def _on_add_preference(self) -> None:
        key, ok = QInputDialog.getText(self, "添加偏好", "偏好名称（例如：叫我）:")
        if not ok or not key.strip():
            return
        value, ok = QInputDialog.getText(self, "添加偏好", f"{key.strip()} 的内容:")
        if not ok or not value.strip():
            return
        mgr = _memory_mgr_of(self.app_ctx)
        if mgr is None:
            return
        try:
            mgr.set_preference(key.strip(), value.strip(), source="manual")
        except Exception as exc:
            logger.warning("添加偏好失败: %s", exc)
            return
        _refresh_system_context(self.app_ctx)
        self.refresh()

    def _on_edit_preference(self, key: str) -> None:
        mgr = _memory_mgr_of(self.app_ctx)
        if mgr is None:
            return
        current = mgr.get_preference(key) or ""
        value, ok = QInputDialog.getText(self, "修改偏好", f"{key} 改为:", text=current)
        if not ok or not value.strip():
            return
        try:
            mgr.set_preference(key, value.strip(), source="manual")
        except Exception as exc:
            logger.warning("修改偏好失败: %s", exc)
            return
        _refresh_system_context(self.app_ctx)
        self.refresh()

    def _on_delete_preference(self, key: str) -> None:
        mgr = _memory_mgr_of(self.app_ctx)
        if mgr is None:
            return
        box = QMessageBox(self)
        box.setWindowTitle("删除偏好")
        box.setIcon(QMessageBox.Question)
        box.setText(f"删除偏好「{key}」？\n码铃会立刻忘掉它（不可恢复）。")
        yes = box.addButton("删除", QMessageBox.DestructiveRole)
        box.addButton("再想想", QMessageBox.RejectRole)
        box.exec_()
        if box.clickedButton() is not yes:
            return
        try:
            mgr.delete_preference(key)
        except Exception as exc:
            logger.warning("删除偏好失败: %s", exc)
            return
        _refresh_system_context(self.app_ctx)
        self.refresh()

    # -- ② 活跃话题 --
    def _refresh_topics(self) -> None:
        mgr = _memory_mgr_of(self.app_ctx)
        active: List[dict] = []
        archived: List[dict] = []
        if mgr is not None:
            try:
                active = mgr.get_active_topics() or []
                archived = mgr.get_archived_topics() or []
            except Exception as exc:
                logger.warning("读取话题失败: %s", exc)
        if not active:
            self._insert_card(self.topic_tab, self._empty_label(
                "暂时没有活跃的话题。\n在聊天里说说最近在忙什么，码铃会记在心上~"))
        for t in active:
            subject = str(t.get("subject", ""))
            source = t.get("source", "legacy")
            badge = _SOURCE_LABELS.get(source, "早期记忆")
            rel = _relative_time(t.get("last_mentioned", ""))
            badge_text = f"（{badge}）" + (f" · {rel}提到" if rel else "")
            pinned = bool(t.get("pinned"))
            actions = [
                ("📌 固定" if not pinned else "📌 已固定",
                 "固定后不会被自动归档" if not pinned else "取消固定",
                 lambda s=subject, p=pinned: self._on_pin_topic(s, not p)),
                ("🙈 不要再提", "码铃 14 天内不再主动提起（内容仍在记忆中心）",
                 lambda s=subject: self._on_mute_topic(s)),
                ("🗑 删除", "移入已归档（不再出现在活跃区）",
                 lambda s=subject: self._on_forget_topic(s)),
            ]
            self._insert_card(self.topic_tab, _EntryCard(
                self.app_ctx, subject, badge_text, actions))
        # 已归档折叠只读区（QLabel 不折叠展开，直接一节卡片尾随）
        if archived:
            note = QLabel("—— 已归档 ——")
            note.setObjectName("memoryBookBadge")
            self._insert_card(self.topic_tab, note)
            for t in archived:
                subject = str(t.get("subject", ""))
                rel = _relative_time(t.get("last_mentioned", ""))
                badge_text = "（已归档）" + (f" · {rel}提到" if rel else "")
                self._insert_card(self.topic_tab, _EntryCard(
                    self.app_ctx, subject, badge_text,
                    [("🗑 彻底删除", "物理删除、码铃永远忘记（不可恢复）",
                      lambda s=subject: self._on_delete_topic_forever(s))]))

    def _on_pin_topic(self, subject: str, pinned: bool) -> None:
        mgr = _memory_mgr_of(self.app_ctx)
        if mgr is None or not hasattr(mgr, "pin_topic"):
            return
        try:
            mgr.pin_topic(subject, pinned)
        except Exception as exc:
            logger.warning("固定话题失败: %s", exc)
            return
        self.refresh()

    def _on_mute_topic(self, subject: str) -> None:
        """「不要再提」= 反馈 mute 键写回（14 天静默，不删数据）。"""
        mgr = _memory_mgr_of(self.app_ctx)
        if mgr is None or not hasattr(mgr, "record_followup_feedback"):
            return
        try:
            mgr.record_followup_feedback(subject, "mute")
        except Exception as exc:
            logger.warning("静默话题失败: %s", exc)
            return
        self.refresh()

    def _on_forget_topic(self, subject: str) -> None:
        mgr = _memory_mgr_of(self.app_ctx)
        if mgr is None:
            return
        try:
            mgr.forget_topic(subject)
        except Exception as exc:
            logger.warning("删除话题失败: %s", exc)
            return
        _refresh_system_context(self.app_ctx)
        self.refresh()

    def _on_delete_topic_forever(self, subject: str) -> None:
        """彻底删除（物理双删，不可恢复）—— 必弹确认框。"""
        mgr = _memory_mgr_of(self.app_ctx)
        if mgr is None or not hasattr(mgr, "delete_topic_forever"):
            return
        box = QMessageBox(self)
        box.setWindowTitle("彻底删除")
        box.setIcon(QMessageBox.Warning)
        box.setText(f"彻底删除「{subject}」？\n这是物理删除，码铃将永远忘记，不可恢复。")
        yes = box.addButton("彻底删除", QMessageBox.DestructiveRole)
        box.addButton("再想想", QMessageBox.RejectRole)
        box.exec_()
        if box.clickedButton() is not yes:
            return
        try:
            mgr.delete_topic_forever(subject)
        except Exception as exc:
            logger.warning("彻底删除话题失败: %s", exc)
            return
        _refresh_system_context(self.app_ctx)
        self.refresh()

    # -- ③ 情绪记录 --
    def _refresh_emotions(self) -> None:
        # v1.8(F2/D-V18-03): 情绪弧线区块（8 周日格色带；挂情绪记录 Tab 顶部，
        # R-A 零数字主战场——组件内建断言见 tests/test_v18_batch1.py）
        try:
            arc = EmotionArcWidget(self.app_ctx)
            self._insert_card(self.emotion_tab, arc)
            self._arc_widget = arc
        except Exception as exc:
            logger.debug("情绪弧线组件装配失败（Tab 其余内容照常）: %s", exc)
            self._arc_widget = None
        note = QLabel(
            "情绪只作为陪伴的参考，码铃不会给它们打分。\n"
            "需要的时候随时删掉任何一条，或者干脆全部忘掉。")
        note.setObjectName("memoryBookBadge")
        note.setWordWrap(True)
        self._insert_card(self.emotion_tab, note)
        mgr = _memory_mgr_of(self.app_ctx)
        history: List[dict] = []
        if mgr is not None and hasattr(mgr, "get_emotions_history"):
            try:
                history = mgr.get_emotions_history() or []
            except Exception as exc:
                logger.warning("读取情绪历史失败: %s", exc)
        # 弧线喂data + 点日格看那天的心情（R-A：展示恒为档位词 + 原文摘录）
        if self._arc_widget is not None:
            try:
                self._arc_widget.refresh_arc(history)
                self._arc_widget.dayClicked.connect(self._on_arc_day_clicked)
            except Exception as exc:
                logger.debug("情绪弧线渲染失败（可忽略）: %s", exc)
            self._arc_day_label = QLabel("")
            self._arc_day_label.setObjectName("memoryBookBadge")
            self._arc_day_label.setWordWrap(True)
            self._arc_day_label.setVisible(False)
            self._insert_card(self.emotion_tab, self._arc_day_label)
        if not history:
            self._insert_card(self.emotion_tab, self._empty_label(
                "还没有情绪记录。\n聊天时提到的心情会悄悄记在这里，只给码铃自己看~"))
            return
        # 时间倒序展示（最近心情在最上面）
        for e in reversed(history):
            emotion = str(e.get("emotion", ""))
            label = _EMOTION_LABELS.get(emotion, emotion)
            rel = _relative_time(e.get("time", ""))
            excerpt = str(e.get("excerpt", "") or "")
            badge_text = (f" · {rel}" if rel else "")
            emoji = "😊" if emotion == "happy" else "😌"
            title = label
            if excerpt:
                title = f"{title} ——「{excerpt}」"
            self._insert_card(self.emotion_tab, _EntryCard(
                self.app_ctx, title, badge_text.strip(" ·"), [],
                icon_name="emotion", prefix=f"{emoji} "))

    # ------------------------------------------------------------------
    def _apply_style(self) -> None:
        text = theme_color(self.app_ctx, "text", "#5D4037")
        secondary = theme_color(self.app_ctx, "text_secondary", "#8A8A8A")
        divider = theme_color(self.app_ctx, "divider", "#EFE0E2")
        self.privacy_label.setStyleSheet(
            f"QLabel#memoryBookPrivacy {{ color: {secondary}; font-size: 12px;"
            f" border-top: 1px solid {divider}; padding-top: 10px; }}"
        )
        for name in ("memoryBookSub", "memoryBookEmpty"):
            lab = self.findChild(QLabel, name)
            if lab is not None:
                lab.setStyleSheet(f"QLabel#{name} {{ color: {secondary}; font-size: 12px; }}")
        add_btn = self.pref_tab.findChild(QPushButton, "memoryBookBtn")
        if add_btn is not None:
            accent = theme_color(self.app_ctx, "accent", "#FF6B9D")
            add_btn.setStyleSheet(
                f"QPushButton#memoryBookBtn {{ background: transparent; color: {accent};"
                f" border: 1px solid {divider}; border-radius: 8px; font-size: 12px;"
                f" padding: 6px 14px; }}"
                f"QPushButton#memoryBookBtn:hover {{ border-color: {accent}; }}"
            )
        self.tabs.setStyleSheet(
            f"QTabWidget#memoryBookTabs::pane {{ border: 1px solid {divider};"
            f" border-radius: 8px; top: -1px; }}"
            # 未选中 Tab 颜色走 setTabTextColor 分组着色（D-V18-09），此处不设通用色
            f"QTabBar::tab {{ padding: 6px 18px; }}"
            f"QTabBar::tab:selected {{ color: {text}; font-weight: bold; }}"
        )
        self._color_tabs()

    def _color_tabs(self) -> None:
        """v1.8(D-V18-09/Q-D2): Tab 分组着色 —— 记忆组（暖粉）/ 经历组（暖蓝）/
        日记组（暖橙）。平铺不重构，只动本页样式，数据链零改动（R-D）。

        v2.1(V21-12/D-V21-06): 同时统一 8 Tab 矢量图标（尺寸/取色一致）；图标字体
        不可用 → 回落原 emoji 文案（不空白、不崩）。分组仍按序位（文本随图标可用性
        变，文本匹配会失效，故改序位判定，行为等价）。
        """
        colors = {
            "memory": theme_color(self.app_ctx, "accent", "#FF6B9D"),
            "story": theme_color(self.app_ctx, "info", "#5B9BD5"),
            "diary": theme_color(self.app_ctx, "warning", "#E6A23C"),
        }
        self.tabs.setIconSize(QSize(_TAB_ICON_SIZE, _TAB_ICON_SIZE))
        for i in range(self.tabs.count()):
            if i >= len(_TAB_DEFS):
                continue
            clean, fallback, icon_name, group = _TAB_DEFS[i]
            color = colors.get(group, colors["memory"])
            ic = _vector_icon(self.app_ctx, icon_name, _TAB_ICON_SIZE, color)
            if ic is not None:
                self.tabs.setTabIcon(i, ic)
                if self.tabs.tabText(i) != clean:
                    self.tabs.setTabText(i, clean)
            elif self.tabs.tabText(i) != fallback:
                self.tabs.setTabText(i, fallback)
            self.tabs.tabBar().setTabTextColor(i, color)
