"""gui/widgets/mini_games.py —— v1.3 P2-1 女仆小游戏（她当荷官）→ v1.4(A0) 游戏角容器

v1.3 设计（docs/design-v13.md D-V13-05 / PRD §3.2 P2-1）：
  - 四款游戏：抛硬币 / 抽签 / 猜拳 / 21 点（简化荷官规则），纯 random 确定性结果、零 LLM。
  - 她只做「台词 + 结果一句」；结果经 CompanionManager.react_to_game_result 产生
    （赢 -> happy / 输 -> 温柔安慰 / 平 -> 俏皮），30 分钟冷却口径只回普通台词。
  - 红线（R-A 最重灾区）：UI **绝无**分数/货币/筹码/输赢累计/胜率/连胜/等级/「今日首胜」；
    每局只是「此刻的一局小故事」，无任何养成数值、无后台加分。
  - 情绪表情：冷却外赢/平局时经 companion_bridge.note_activity 短暂展示 happy/surprised
    （约 1.8s 后回落），不持久化 mood。
  - 主题：取色一律 theme_color(app_ctx, key, fallback)，禁裸硬编码色。

v1.4(A0，D-V14-01) 容器化增量（docs/design-v14.md §2.1/§3.1）：
  - 右侧内容区改为 QStackedWidget：page0 = 荷官台（QTextEdit + 动作行，**荷官四款零改写**，
    R-D），pageN（>=1）= 注册表复杂游戏（gui/widgets/games.GAME_DEFS，kind="widget"）懒创建挂载页。
  - 左列按钮 = 荷官四款（顺序与旧版一致，在上）+ 「· 来找码铃玩点别的 ·」分组标题
    （theme_color）+ 注册表 widget 游戏按钮（在下）。
  - 底部无数值说明行改为中性文案（对容器全态通用）；窗口尺寸放大以容纳复杂交互游戏。
"""
from __future__ import annotations

import logging
import random
from typing import Dict, List, Optional

from gui.qt_compat import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget, QLabel, QPushButton,
    QTextEdit, QFrame, Qt, QScrollArea, QSizePolicy, QTimer,
    QStackedWidget,
)
from gui.utils import theme_color

logger = logging.getLogger("maid_coder.gui")

# 游戏 id
COIN = "coin"      # 抛硬币
LOT = "lot"        # 抽签
RPS = "rps"        # 猜拳
BJ = "bj"          # 21 点

# 荷官四款伪注册项（旧版固定清单首部，顺序与 v1.3 完全一致）
_DEALER_DEFS = [
    (COIN, "🪙 抛硬币", "猜硬币正反面"),
    (LOT, "🎋 抽签", "摇一支今日签"),
    (RPS, "✊ 猜拳", "石头剪刀布"),
    (BJ, "🂡 21 点", "和码铃比牌面，超过 21 爆牌"),
]

# v1.4(A2 裁定，D-V14-03 默认值)：widget 游戏 outcome -> react_to_game_result 口径
# 的映射（扫雷胜负有明确方向接 win/lose 情绪叙事；置空 dict 即关）。
# 若评审嫌「踩雷即安慰」过频，可改 True 仅接 win（design §8.8 一行开关）。
_REACT_WIDGET_ONLY_WIN = False
_WIDGET_REACT_MAP = {
    "game_minesweeper": {"win": "win", "lose": "lose"},
    # 2048 结束语义中性，不接情绪（D-V14-02）；"game_2048": {} 即不接
}

_RPS_CHOICES = {"✊": "石头", "✌️": "剪刀", "🖐": "布"}
_RPS_BEATS = {"石头": "剪刀", "剪刀": "布", "布": "石头"}

_LOT_RESULTS = [("大吉", "win"), ("中吉", "win"), ("小吉", "win"),
                ("吉", "win"), ("末吉", "win"), ("凶", "lose")]

_BJ_MAX = 21


class MiniGamesDialog(QDialog):
    """小游戏对话框：左侧游戏选择，右侧荷官台面日志 + 动作按钮。"""

    def __init__(self, app_ctx, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app_ctx = app_ctx
        # v1.4(A0): 「🎲 游戏角 · 码铃陪你」（design §8.9 裁定老入口不变、对话框更名）
        self.setWindowTitle("🎲 游戏角 · 码铃陪你")
        self.setModal(False)
        # v1.4(A0): 窗口放大以容纳复杂交互游戏（design §2.1：min 660x520 / 默认 720x560）
        self.resize(720, 560)
        self.setMinimumSize(660, 520)

        self._game: str = COIN
        self._action_row_layout: Optional[QHBoxLayout] = None
        self._bj: dict = {}
        # v1.4(A0): 容器内部件引用
        self._stack: Optional[QStackedWidget] = None
        self._dealer_page: Optional[QWidget] = None
        self._game_pages: Dict[str, int] = {}      # widget gid -> stack index
        self._game_instances: Dict[str, QWidget] = {}  # widget gid -> 懒建实例

        self._build_ui()
        self._pick_game(COIN)
        self._apply_theme()

    # ------------------------------------------------------------------
    # v1.4(A0): 注册表读取 / 游戏类型
    # ------------------------------------------------------------------
    def _widget_game_defs(self) -> list:
        """从 gui.widgets.games 注册表取 kind=="widget" 的新游戏定义。"""
        try:
            from gui.widgets.games import GAME_DEFS
            return [d for d in list(GAME_DEFS or []) if d and len(d) >= 5 and d[3] == "widget"]
        except Exception as exc:
            logger.warning("游戏注册表读取失败（仅荷官四款可用）: %s", exc)
            return []

    def _is_dealer(self, gid: str) -> bool:
        return gid in {d[0] for d in _DEALER_DEFS}

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(10)

        # v1.4(A0): 顶部标题（荷官页/游戏页各自措辞，_set_header 切换）
        self.title_label = QLabel("码铃荷官台 · 和小女仆玩一小局吧")
        self.title_label.setObjectName("miniGamesTitle")
        f = self.title_label.font()
        f.setBold(True)
        self.title_label.setFont(f)
        outer.addWidget(self.title_label)

        body = QHBoxLayout()
        body.setSpacing(12)

        # 左侧：荷官四款（上）+ v1.4 注册表复杂游戏（下，分组标题分隔）
        side = QWidget()
        side.setObjectName("miniGamesSide")
        side.setFixedWidth(150)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(8, 8, 8, 8)
        side_layout.setSpacing(8)
        side_layout.setAlignment(Qt.AlignTop)

        self.game_btns: dict = {}
        # 荷官四款：按钮创建与 v1.3 完全一致（顺序 = COIN/LOT/RPS/BJ）
        for gid, text, tip in _DEALER_DEFS:
            btn = QPushButton(text)
            btn.setObjectName("miniGamePickBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(tip)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _c=False, g=gid: self._pick_game(g))
            side_layout.addWidget(btn)
            self.game_btns[gid] = btn

        # v1.4(A0): 复杂游戏分组标题（只读小标题，取 theme_color）
        self.game_group_label = QLabel("· 来找码铃玩点别的 ·")
        self.game_group_label.setObjectName("miniGameGroupLabel")
        self.game_group_label.setAlignment(Qt.AlignCenter)
        side_layout.addWidget(self.game_group_label)

        widget_defs = self._widget_game_defs()
        for gid, text, tip, _kind, _factory in widget_defs:
            btn = QPushButton(text)
            btn.setObjectName("miniGamePickBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(tip)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _c=False, g=gid: self._pick_game(g))
            side_layout.addWidget(btn)
            self.game_btns[gid] = btn
        if not widget_defs:
            # 注册表为空（极早期/缺模块）：分组标题置灰不引导
            self.game_group_label.hide()
        side_layout.addStretch()
        body.addWidget(side)

        # v1.4(A0): 右侧内容区 -> QStackedWidget
        #   page0 = 荷官台（QTextEdit + 动作行原样，荷官四款零改写）
        #   pageN = 每个注册表 widget 游戏一个挂载页（懒创建）
        self._stack = QStackedWidget()
        self._stack.setObjectName("miniGamesStack")

        dealer = QWidget()
        dealer.setObjectName("miniGamesTable")
        dealer_layout = QVBoxLayout(dealer)
        dealer_layout.setContentsMargins(10, 10, 10, 10)
        dealer_layout.setSpacing(8)

        self.log_edit = QTextEdit()
        self.log_edit.setObjectName("miniGamesLog")
        self.log_edit.setReadOnly(True)
        self.log_edit.setPlaceholderText("选左侧一款游戏开始~ 码铃洗牌中…")
        self.log_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        dealer_layout.addWidget(self.log_edit, 1)

        # 动作按钮行（随当前游戏/回合重建）
        action_wrap = QWidget()
        self._action_row_layout = QHBoxLayout(action_wrap)
        self._action_row_layout.setContentsMargins(0, 0, 0, 0)
        self._action_row_layout.setSpacing(8)
        dealer_layout.addWidget(action_wrap)

        self._stack.addWidget(dealer)          # index 0 = 荷官台
        self._dealer_page = dealer

        # widget 游戏挂载页（首次选中才实例化游戏，避免启动成本与后台空转）
        for gid, text, _tip, _kind, _factory in widget_defs:
            page = QWidget()
            page.setObjectName("miniGamesWidgetPage")
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(4, 4, 4, 4)
            page_layout.setSpacing(4)
            self._stack.addWidget(page)        # index >= 1
            self._game_pages[gid] = self._stack.count() - 1

        body.addWidget(self._stack, 1)
        outer.addLayout(body, 1)

        # 底部一行隐私/无数值说明（自然语言，无计数；v1.4(A0) 中性化以覆盖容器全态）
        note = QLabel("游戏结果只留在这张小桌上，不记分账、不排行，随时可玩~")
        note.setObjectName("miniGamesNote")
        note.setWordWrap(True)
        outer.addWidget(note)

    def _apply_theme(self) -> None:
        bg = theme_color(self.app_ctx, "bg_card", "#FFFFFF")
        border = theme_color(self.app_ctx, "border", "#FFE4E1")
        text = theme_color(self.app_ctx, "text", "#5D4037")
        secondary = theme_color(self.app_ctx, "text_secondary", "#8A8A8A")
        # 对比度修复（标题）：accent 是「填充用」强调色，作字色落在 bg_card 上仅
        # 3.267/2.163/6.485/3.245；标题 19px bold 属 WCAG 大字（阈值 3.0，ui_cream
        # 2.163 不过）→ 改用「文字用」accent_text（4.844/4.924/6.507/4.935）。
        accent_text = theme_color(self.app_ctx, "accent_text", "#B45073")
        # 对比度修复（miniGamePickBtn 选中/hover 实底）：实底为 primary/accent 时，
        # 原硬编码 #FFFFFF 只有 3.267/2.163/2.678/3.245（四套全 <4.5，ui_night 2.678
        # 连 3.0 都不过）→ 改用仓库 P4 约定键 text_on_accent（5.208/5.984/6.485/5.192）。
        text_on_accent = theme_color(self.app_ctx, "text_on_accent", "#FFFFFF")
        bg_light = theme_color(self.app_ctx, "bg_light", "#FFF0F3")
        primary = theme_color(self.app_ctx, "primary", "#FFB6C1")
        primary_dark = theme_color(self.app_ctx, "primary_dark", "#FF69B4")
        divider = theme_color(self.app_ctx, "divider", "#EFE0E2")

        self.setStyleSheet(f"QDialog {{ background: {bg}; color: {text}; }}")
        self.title_label.setStyleSheet(
            f"QLabel#miniGamesTitle {{ color: {accent_text}; background: transparent; }}"
        )
        self.game_group_label.setStyleSheet(
            f"QLabel#miniGameGroupLabel {{ color: {secondary}; background: transparent;"
            f" font-size: 11px; padding: 2px 0; }}"
        )
        self.log_edit.setStyleSheet(
            f"QTextEdit#miniGamesLog {{"
            f"  background: {bg_light}; color: {text}; border: 1px solid {divider};"
            f"  border-radius: 10px; padding: 8px; font-size: 13px;"
            f"}}"
        )
        for gid, btn in self.game_btns.items():
            checked = (gid == self._game)
            # 对比度修复（未选中）：实测底色是 bg（不是 bg_card，两处独立取样互证），
            # 原字色 accent 落上去只有 3.051/2.057/7.014/2.966（三套浅色 <4.5）
            # → 改用「文字用」accent_text（4.524/4.684/7.039/4.511）。
            # ⚠ 描边仍为 primary（未选中态与字色原为同色，现描边保持不动）。
            fill = primary if checked else "transparent"
            fg = text_on_accent if checked else accent_text
            btn.setStyleSheet(
                f"QPushButton#miniGamePickBtn {{"
                f"  background: {fill}; color: {fg};"
                f"  border: 1px solid {primary}; border-radius: 8px;"
                f"  padding: 8px 6px; font-size: 13px;"
                f"}}"
                f"QPushButton#miniGamePickBtn:hover {{"
                f" background: {primary}; color: {text_on_accent}; }}"
            )
        note = self.findChild(QLabel, "miniGamesNote")
        if note is not None:
            note.setStyleSheet(f"QLabel#miniGamesNote {{ color: {secondary}; font-size: 11px; }}")

    def _say(self, text: str) -> None:
        """女仆荷官台词。"""
        name = self._dealer_name()
        self.log_edit.append(f"码铃 · {name}：{text}")

    def _note(self, text: str) -> None:
        """叙述/玩家行动行。"""
        self.log_edit.append(text)

    def _dealer_name(self) -> str:
        companion = getattr(self.app_ctx, "companion", None)
        if companion is not None:
            try:
                stage = companion.relation_stage_name()
                if stage:
                    return f"{stage}的码铃"
            except Exception:
                pass
        return "码铃"

    # ------------------------------------------------------------------
    # 游戏切换 / 动作按钮重建
    # ------------------------------------------------------------------
    def _pick_game(self, gid: str) -> None:
        self._game = gid
        for k, btn in self.game_btns.items():
            btn.setChecked(k == gid)
        self._apply_theme()
        # v1.4(A0): 注册表复杂游戏走独立挂载页（荷官四款逻辑零改写）
        if not self._is_dealer(gid):
            self._activate_widget_game(gid)
            return
        # ---- 荷官四款：以下分支与 v1.3 逐行等价（R-D） ----
        self._stack.setCurrentWidget(self._dealer_page)
        self._set_header("dealer")
        self.log_edit.clear()
        self._bj = {"player": 0, "dealer": 0, "round": 0}
        if gid == COIN:
            self._note("新的一局：猜硬币正反面~")
            self._say("主人想猜哪一面？码铃来抛~")
            self._build_actions([("🪙 正面", lambda: self._play_coin("正面")),
                                 ("🪙 反面", lambda: self._play_coin("反面"))])
        elif gid == LOT:
            self._say("码铃把签筒轻轻摇了摇…主人要抽一支吗？")
            self._build_actions([("🎋 抽一支签", self._play_lot)])
        elif gid == RPS:
            self._note("新的一局：石头剪刀布~")
            self._say("主人出什么？码铃可要认真出拳啦~")
            self._build_actions([("✊ 石头", lambda: self._play_rps("石头")),
                                 ("✌️ 剪刀", lambda: self._play_rps("剪刀")),
                                 ("🖐 布", lambda: self._play_rps("布"))])
        elif gid == BJ:
            self._note("简化 21 点：每张牌 1~10，谁更接近 21 谁赢，超过 21 就爆牌。")
            self._say("主人先要一张牌吧？")
            self._build_actions([("🃏 要牌", self._bj_hit),
                                 ("✋ 停牌", self._bj_stand)])

    # ------------------------------------------------------------------
    # v1.4(A0): 复杂游戏挂载页（懒创建 + 信号接线）
    # ------------------------------------------------------------------
    def _set_header(self, mode: str) -> None:
        """顶部标题随荷官页/游戏页切换（design §8.9：荷官台保留为荷官页小标题）。"""
        if mode == "widget":
            self.title_label.setText("游戏角 · 来找码铃玩点别的")
        else:
            self.title_label.setText("码铃荷官台 · 和小女仆玩一小局吧")

    def _widget_factory(self, gid: str):
        try:
            from gui.widgets.games import GAME_DEFS
        except Exception:
            return None
        for d in list(GAME_DEFS or []):
            if d and len(d) >= 5 and d[0] == gid and d[3] == "widget":
                return d[4]
        return None

    def _activate_widget_game(self, gid: str) -> None:
        page = self._stack.widget(self._game_pages.get(gid, 1))
        game = self._ensure_widget_game(gid)
        self._stack.setCurrentWidget(page if page is not None else self._dealer_page)
        self._set_header("widget")
        if game is not None:
            game.setFocusPolicy(Qt.StrongFocus)
            game.setFocus()

    def _ensure_widget_game(self, gid: str):
        """懒创建：首次选中该游戏才实例化并挂到其页面（此后常驻，切走不销毁）。"""
        if gid in self._game_instances:
            return self._game_instances[gid]
        page = self._stack.widget(self._game_pages.get(gid, 1))
        if page is None:
            return None
        factory = self._widget_factory(gid)
        if factory is None:
            self._page_fallback_text(page, "这款小游戏暂时没摆上桌，主人下次再来看看~")
            return None
        try:
            game = factory(self.app_ctx, page)
        except Exception as exc:
            logger.warning("游戏 %s 实例化失败: %s", gid, exc)
            self._page_fallback_text(page, "这款小游戏暂时没摆上桌，主人下次再来看看~")
            return None
        if game is None:
            return None
        layout = page.layout()
        if layout is not None and layout.count() == 0:
            layout.addWidget(game, 1)
        self._game_instances[gid] = game
        self._wire_widget_signals(gid, game)
        return game

    @staticmethod
    def _page_fallback_text(page: QWidget, text: str) -> None:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color: #9E9E9E; font-size: 12px; background: transparent;")
        layout = page.layout()
        if layout is not None and layout.count() == 0:
            layout.addWidget(label, 1)

    def _wire_widget_signals(self, gid: str, game: QWidget) -> None:
        """连接 widget 结局信号 -> 情绪反馈（v1.4(A2) 扫雷 win/lose；2048 不接）。"""
        mapping = _WIDGET_REACT_MAP.get(gid)
        if not mapping:
            return
        if not (hasattr(game, "outcome") and hasattr(game.outcome, "connect")):
            return
        try:
            game.outcome.connect(
                lambda outcome, _g=gid, _m=mapping: self._on_widget_outcome(_g, outcome, _m)
            )
        except Exception as exc:
            logger.warning("widget 游戏 %s 信号接线失败: %s", gid, exc)

    def _on_widget_outcome(self, gid: str, outcome: str, mapping: dict) -> None:
        """widget 游戏一局结束 -> 经 react_to_game_result 一句情绪反馈（30min 冷却，无计分）。"""
        if _REACT_WIDGET_ONLY_WIN and outcome != "win":
            react_outcome = None
        else:
            react_outcome = mapping.get(outcome) if outcome else None
        if react_outcome is None:
            return
        companion = getattr(self.app_ctx, "companion", None)
        reaction = None
        if companion is not None and hasattr(companion, "react_to_game_result"):
            try:
                reaction = companion.react_to_game_result(react_outcome) or {}
            except Exception as exc:
                logger.warning("react_to_game_result 异常: %s", exc)
        text = (reaction or {}).get("text") if reaction else None
        if text:
            self._show_widget_maid_line(gid, text)
        self._flash_expression((reaction or {}).get("expression") if reaction else None)

    def _show_widget_maid_line(self, gid: str, text: str) -> None:
        """把女仆一句话写到游戏页自己的 maid_line 标签（游戏未提供则忽略）。"""
        game = self._game_instances.get(gid)
        target = getattr(game, "maid_line", None)
        if isinstance(target, QLabel):
            try:
                target.setText(text)
            except Exception:
                pass

    def _build_actions(self, actions: List) -> None:
        """清空动作行并重建一组按钮。"""
        if self._action_row_layout is None:
            return
        while self._action_row_layout.count():
            item = self._action_row_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        bg_light = theme_color(self.app_ctx, "bg_light", "#FFF0F3")
        accent = theme_color(self.app_ctx, "accent", "#FF6B9D")
        text = theme_color(self.app_ctx, "text", "#5D4037")
        text_on = "#FFFFFF"
        for label, cb in actions:
            btn = QPushButton(label)
            btn.setObjectName("miniActionBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, fn=cb: self._safe(fn))
            btn.setStyleSheet(
                f"QPushButton#miniActionBtn {{"
                f"  background: {accent}; color: {text_on}; border: none;"
                f"  border-radius: 8px; padding: 6px 14px; font-size: 13px;"
                f"}}"
                # hover 字落在 bg_light 实底上：accent 仅 2.783/1.931/5.317/2.814，
                # 改用文字色 text（14.492/11.556/12.503/11.980）。
                f"QPushButton#miniActionBtn:hover {{ background: {bg_light}; color: {text};"
                f" border: 1px solid {accent}; }}"
            )
            self._action_row_layout.addWidget(btn)
        self._action_row_layout.addStretch()

    def _safe(self, fn) -> None:
        """动作回调防御：任何异常不回崩对话框。"""
        try:
            fn()
        except Exception as exc:
            logger.warning("小游戏动作异常: %s", exc)
            self._say("哎呀，码铃手滑了一下…主人再点一次试试？")

    # ------------------------------------------------------------------
    # 回合结束 -> 情绪反馈（经 companion.react_to_game_result）
    # ------------------------------------------------------------------
    def _react(self, outcome: str) -> None:
        """结局叙事 + 情绪反馈（30min 冷却只回普通台词，无数值/无加分）。"""
        companion = getattr(self.app_ctx, "companion", None)
        reaction = None
        if companion is not None and hasattr(companion, "react_to_game_result"):
            try:
                reaction = companion.react_to_game_result(outcome) or {}
            except Exception as exc:
                logger.warning("react_to_game_result 异常: %s", exc)
                reaction = None
        if reaction and reaction.get("text"):
            self._say(reaction["text"])
        else:
            self._say(random.choice(
                ["这一小局就到这儿啦，主人要再来一局的话随时点左边~",
                 "玩得开心就好~ 码铃把桌子收拾好啦。"]) if outcome != "win"
                else "主人手气真不错，码铃陪得也开心~")
        self._flash_expression(reaction.get("expression") if reaction else None)
        self._build_actions([("🔁 再来一局", lambda: self._pick_game(self._game))])

    def _flash_expression(self, expression: Optional[str]) -> None:
        """短暂展示 happy/surprised（冷却内 expression=normal 时不闪）。"""
        bridge = getattr(self.app_ctx, "companion_bridge", None)
        if bridge is None or not hasattr(bridge, "note_activity"):
            return
        if expression not in ("happy", "surprised"):
            return
        try:
            bridge.note_activity(expression)
            QTimer.singleShot(1800, lambda: self._safe(lambda: bridge.note_activity(None)))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 抛硬币
    # ------------------------------------------------------------------
    def _play_coin(self, guess: str) -> None:
        face = random.choice(["正面", "反面"])
        self._note(f"主人猜了「{guess}」…")
        self._say(f"叮——硬币在空中转了几圈，落下来是「{face}」！")
        if guess == face:
            self._note("猜中啦！")
            self._react("win")
        else:
            self._note("没猜中~ 本就是五五开的小游戏。")
            self._react("lose")

    # ------------------------------------------------------------------
    # 抽签
    # ------------------------------------------------------------------
    def _play_lot(self) -> None:
        name, outcome = random.choice(_LOT_RESULTS)
        self._say(f"签筒轻轻一晃…「{name}」！")
        if outcome == "win":
            self._note("抽到一支好签，今天的心情也跟着亮了起来。")
            self._react("win")
        else:
            self._note("嗯…抽到什么都是签筒的小玩笑啦。")
            self._react("lose")

    # ------------------------------------------------------------------
    # 猜拳
    # ------------------------------------------------------------------
    def _play_rps(self, user: str) -> None:
        comp = random.choice(list(_RPS_BEATS.keys()))
        self._note(f"主人出「{user}」，码铃出「{comp}」…")
        if user == comp:
            self._note("平局~")
            self._react("draw")
        elif _RPS_BEATS[user] == comp:
            self._note("这局主人赢啦！")
            self._react("win")
        else:
            self._note("这局码铃险胜…主人可别灰心。")
            self._react("lose")

    # ------------------------------------------------------------------
    # 简化 21 点
    # ------------------------------------------------------------------
    def _bj_draw(self) -> int:
        return random.randint(1, 10)

    def _bj_bust(self, total: int) -> bool:
        return total > _BJ_MAX

    def _bj_hit(self) -> None:
        if self._bj.get("round", 0) == 0:
            # 开局：双方各先抽一张（庄家牌先藏一张，不显示）
            self._bj["player"] = self._bj_draw()
            self._bj["dealer"] = self._bj_draw()
            self._bj["round"] = 1
            self._note(f"主人先抽到 {self._bj['player']} 点。")
            return
        self._bj["player"] += self._bj_draw()
        total = self._bj["player"]
        self._note(f"又抽了一张，主人牌面合计 {total} 点。")
        if self._bj_bust(total):
            self._say("爆牌啦——超过 21 点，这一局…")
            self._react("lose")
            return
        if total == _BJ_MAX:
            self._note("刚好 21 点！停牌比下去吧。")
            self._bj_stand()

    def _bj_stand(self) -> None:
        dealer = self._bj.get("dealer", 0)
        if self._bj.get("round", 0) == 0:
            self._note("先要一张牌再决定要不要停牌吧~")
            return
        player = self._bj["player"]
        # 庄家补牌：不足 17 一直要
        while dealer < 17:
            dealer += self._bj_draw()
        self._bj["dealer"] = dealer
        self._note(f"码铃翻开自己的牌面合计 {dealer} 点（主人 {player} 点）。")
        if self._bj_bust(dealer):
            self._note("码铃爆牌啦——")
            self._react("win")
        elif self._bj_bust(player):
            self._react("lose")
        elif player > dealer:
            self._note("主人牌面更接近 21，赢啦！")
            self._react("win")
        elif player < dealer:
            self._note("码铃牌面略胜一筹…")
            self._react("lose")
        else:
            self._note("牌面一样，平局~")
            self._react("draw")
