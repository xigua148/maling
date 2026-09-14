"""gui/widgets/games/game_minesweeper.py —— v1.4(A2) 扫雷单文件 QWidget（PySide6 移植）

原项目（棋盘/布雷/翻开扩散算法参考，MIT，保留原版权行）：
    MIT License
    Copyright (c) 2020 Dawson Booth
    Source: github.com/dawsonbooth/pynsweeper（src/utils.py + src/constants.py，
            master commit 618c22b32c1f2c146978893ef38639f68baf685a）
    核验：https://raw.githubusercontent.com/dawsonbooth/pynsweeper/master/LICENSE（2026-09-04）
    原 LICENSE 全文副本：docs/third_party_licenses/dawsonbooth_pynsweeper.txt
    登记：docs/THIRD_PARTY.md

码铃 v1.4(A2) 移植说明（docs/design-v14.md D-V14-03）：
  - PyQt5 -> PySide6；src/utils.py 多类并入单文件 QWidget；UI 剥去 Windows XP 复古
    皮（不使用其图片资产，全部重绘，A4 评审项 ④ 通过）、去掉计时器与胜利面板。
  - 保留操作必需信息：剩余雷数 + 右键标旗；无任何分值/用时/局外记录（天然无养成）。
  - 默认难度 9x9 / 10 雷，首版不做难度切换。
  - 换肤：壳面/数字走 theme_color + 内容中性色（design-v14 共享知识 24）。
  - 信号：flags_changed(int)（剩余雷数）/ outcome(str)（"win" | "lose"）。
"""
from __future__ import annotations

import logging
import random
from typing import List, Optional

from gui.qt_compat import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QGridLayout, Qt, Signal,
)
from gui.utils import theme_color

logger = logging.getLogger("maid_coder.gui")

_W = 9            # 宽（列数）
_H = 9            # 高（行数）
_MINES = 10       # 默认雷数

_MINE = "💣"
_FLAG = "🚩"
_EXPLODE = "💥"

# 数字 1..8 的经典内容中性色（游戏内容色；壳面走 theme_color）
_NUM_COLORS = {
    1: "#1976D2", 2: "#388E3C", 3: "#D32F2F", 4: "#7B1FA2",
    5: "#E65100", 6: "#00838F", 7: "#212121", 8: "#616161",
}


class _Cell(QPushButton):
    """扫雷格子：左键翻开 / 右键标旗（事件转发给 GameMinesweeper）。"""

    clicked_at = Signal(int, int, object)   # (row, col, Qt.MouseButton)

    def __init__(self, row: int, col: int, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._row = row
        self._col = col
        self.setFixedSize(36, 36)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)

    def mousePressEvent(self, event) -> None:
        self.clicked_at.emit(self._row, self._col, event.button())
        event.accept()


class GameMinesweeper(QWidget):
    """经典扫雷 9x9/10 雷（纯 Qt、零第三方依赖、无任何持久化）。"""

    flags_changed = Signal(int)      # 剩余雷数（总雷 - 已标旗）
    outcome = Signal(str)            # "win" | "lose"

    def __init__(self, app_ctx, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app_ctx = app_ctx
        self._mines: List[List[bool]] = [[False] * _W for _ in range(_H)]
        self._revealed: List[List[bool]] = [[False] * _W for _ in range(_H)]
        self._flagged: List[List[bool]] = [[False] * _W for _ in range(_H)]
        self._counts: List[List[int]] = [[0] * _W for _ in range(_H)]
        self._cells: List[List[_Cell]] = []
        self._flags: int = 0
        self._safe_left: int = _W * _H - _MINES
        self._over: bool = False
        self._exploded: Optional[tuple] = None
        self._build_ui()
        self.new_game()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 8)
        outer.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(10)
        self.left_label = QLabel("剩余雷数 10")
        self.left_label.setObjectName("msLeft")
        top.addWidget(self.left_label)
        top.addStretch()
        hint = QLabel("左键翻开 · 右键标旗，排完所有雷即胜")
        hint.setObjectName("msHint")
        top.addWidget(hint, 1)
        restart = QPushButton("重新开局")
        restart.setObjectName("msRestart")
        restart.setCursor(Qt.PointingHandCursor)
        restart.clicked.connect(self.new_game)
        top.addWidget(restart)
        outer.addLayout(top)

        host = QWidget()
        host.setObjectName("msBoard")
        grid = QGridLayout(host)
        grid.setSpacing(2)
        grid.setContentsMargins(10, 10, 10, 10)
        self._cells = []
        for r in range(_H):
            row: List[_Cell] = []
            for c in range(_W):
                cell = _Cell(r, c)
                cell.clicked_at.connect(self._on_cell_pressed)
                grid.addWidget(cell, r, c)
                row.append(cell)
            self._cells.append(row)
        outer.addWidget(host, 1, Qt.AlignHCenter)

        # 女仆一句话位（容器/A2 内写入）
        self.maid_line = QLabel("")
        self.maid_line.setObjectName("msMaidLine")
        self.maid_line.setWordWrap(True)
        self.maid_line.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.maid_line)

        self._apply_theme()

    def _apply_theme(self) -> None:
        bg_card = theme_color(self.app_ctx, "bg_card", "#FFFFFF")
        bg_light = theme_color(self.app_ctx, "bg_light", "#FFF0F3")
        accent = theme_color(self.app_ctx, "accent", "#FF6B9D")
        text_secondary = theme_color(self.app_ctx, "text_secondary", "#8A8A8A")
        divider = theme_color(self.app_ctx, "divider", "#EFE0E2")
        self.setStyleSheet(
            f"QWidget#msBoard {{ background: {bg_card}; border: 1px solid {divider};"
            f" border-radius: 12px; }}"
            f"QLabel#msLeft {{ color: {accent}; font-size: 14px; font-weight: bold;"
            f" background: {bg_light}; border-radius: 8px; padding: 6px 10px; }}"
            f"QLabel#msHint {{ color: {text_secondary}; font-size: 12px; background: transparent; }}"
            f"QPushButton#msRestart {{ background: {accent}; color: #FFFFFF; border: none;"
            f" border-radius: 8px; padding: 6px 12px; font-size: 12px; }}"
            f"QPushButton#msRestart:hover {{ background: {bg_light}; color: {accent};"
            f" border: 1px solid {accent}; }}"
            f"QLabel#msMaidLine {{ color: {text_secondary}; font-size: 12px; background: transparent; }}"
        )

    # ------------------------------------------------------------------
    # 游戏逻辑
    # ------------------------------------------------------------------
    def new_game(self) -> None:
        """重新开局：重布雷、清标记（只在本局内存，绝不落盘）。"""
        self._mines = [[False] * _W for _ in range(_H)]
        self._revealed = [[False] * _W for _ in range(_H)]
        self._flagged = [[False] * _W for _ in range(_H)]
        self._counts = [[0] * _W for _ in range(_H)]
        self._flags = 0
        self._safe_left = _W * _H - _MINES
        self._over = False
        self._exploded = None

        positions = [(r, c) for r in range(_H) for c in range(_W)]
        for r, c in random.sample(positions, _MINES):
            self._mines[r][c] = True
        for r in range(_H):
            for c in range(_W):
                self._counts[r][c] = sum(
                    1 for nr, nc in self._neighbors(r, c) if self._mines[nr][nc]
                )
        self.left_label.setText(f"剩余雷数 {_MINES}")
        self.flags_changed.emit(_MINES)
        self.maid_line.setText("码铃悄悄埋好了 10 颗雷，小心翻开哦~")
        self._refresh_all()

    def _neighbors(self, r: int, c: int) -> list:
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                nr, nc = r + dr, c + dc
                if 0 <= nr < _H and 0 <= nc < _W:
                    yield (nr, nc)

    def _on_cell_pressed(self, r: int, c: int, button) -> None:
        if self._over:
            return
        if button == Qt.RightButton:
            self._toggle_flag(r, c)
        elif button == Qt.LeftButton:
            if not self._flagged[r][c]:
                self._sweep(r, c)

    def _toggle_flag(self, r: int, c: int) -> None:
        if self._revealed[r][c]:
            return
        self._flagged[r][c] = not self._flagged[r][c]
        self._flags += 1 if self._flagged[r][c] else -1
        left = max(0, _MINES - self._flags)
        self.left_label.setText(f"剩余雷数 {left}")
        self.flags_changed.emit(left)
        self._refresh_cell(r, c)

    def _sweep(self, r: int, c: int) -> None:
        if self._revealed[r][c]:
            return
        if self._mines[r][c]:
            # 踩雷：本局结束（不落盘、无反馈分）
            self._revealed[r][c] = True
            self._exploded = (r, c)
            self._end_game("lose")
            self._refresh_all()
            return
        # 零扩散翻开
        stack = [(r, c)]
        while stack:
            cr, cc = stack.pop()
            if self._revealed[cr][cc] or self._mines[cr][cc]:
                continue
            self._revealed[cr][cc] = True
            self._safe_left -= 1
            if self._counts[cr][cc] == 0:
                for nr, nc in self._neighbors(cr, cc):
                    if not self._revealed[nr][nc] and not self._mines[nr][nc]:
                        stack.append((nr, nc))
        self._refresh_all()
        if self._safe_left == 0:
            self._end_game("win")

    def _end_game(self, result: str) -> None:
        if self._over:
            return
        self._over = True
        if result == "lose":
            self.maid_line.setText("轰——踩到雷啦！不过只是一小局，点『重新开局』再来~")
        else:
            self.maid_line.setText("全部安全区都翻开啦，主人好细心！")
        self.outcome.emit(result)

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------
    def _cell_text_style(self, r: int, c: int):
        if self._over and self._mines[r][c]:
            # 局终展示雷：踩中的那格显示爆炸，其余显示雷
            if self._exploded == (r, c):
                return _EXPLODE, "#FFFFFF", "#D32F2F"
            if not self._flagged[r][c]:
                return _MINE, "#FFFFFF", "#757575"
        if self._flagged[r][c]:
            return _FLAG, "#FFFFFF", "#FF6B9D"
        if self._revealed[r][c]:
            if self._mines[r][c]:
                return _EXPLODE, "#FFFFFF", "#D32F2F"
            n = self._counts[r][c]
            if n == 0:
                return "", "#000000", "#E8E2D8"
            return str(n), _NUM_COLORS.get(n, "#616161"), "#E8E2D8"
        return "", "#5D4037", "#C9C2B8"

    def _refresh_cell(self, r: int, c: int) -> None:
        cell = self._cells[r][c]
        text, color, bg = self._cell_text_style(r, c)
        cell.setText(text)
        cell.setStyleSheet(
            f"QPushButton {{ background: {bg}; color: {color}; font-size: 15px;"
            f" font-weight: bold; border-radius: 4px; border: 1px solid #B0A89B; }}"
        )

    def _refresh_all(self) -> None:
        for r in range(_H):
            for c in range(_W):
                self._refresh_cell(r, c)
