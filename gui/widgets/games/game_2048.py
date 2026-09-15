"""gui/widgets/games/game_2048.py —— v1.4(A1) 2048 单文件 QWidget（PySide6 移植）

原项目（玩法/合并/配色参考，MIT，保留原版权行）：
    MIT License
    Copyright (c) 2024 jøhann
    Source: github.com/tangentecode/2048-pyqt6（src/main.py，commit 6c5e67c0642bd94e91c4595565bdfca1ecc98a76）
    核验：https://raw.githubusercontent.com/tangentecode/2048-pyqt6/main/LICENSE（2026-09-04）
    原 LICENSE 全文副本：docs/third_party_licenses/tangentecode_2048-pyqt6.txt
    登记：docs/THIRD_PARTY.md

码铃 v1.4(A1) 移植说明（docs/design-v14.md D-V14-02 / Q-A1 拍板）：
  - PyQt6 -> PySide6；StartWindow 选单/多尺寸（3x3~6x6）并入固定 4x4 单文件 widget；
    WASD/方向键移动合并，随机出块（90% 出 2 / 10% 出 4）。
  - 红线 R-A（Q-A1 豁免落点）：仅保留「当前得分」局内即时标签 —— 内存值、每局清零，
    绝不落盘、不设任何局外记录与统计（R-A/R-E）。
  - 合成到 2048 = 本局达成，展示一句庆祝台词（不中断、可继续合成更高块）。
  - 换肤：窗口壳/说明/按钮取 theme_color；数字瓦片用 2048 经典中性瓦片色
    （游戏内容色，design-v14 共享知识 24）。
  - 信号：score_changed(int) / outcome(str)（"reach_2048" | "stuck"）。
"""
from __future__ import annotations

import logging
import random
from typing import List, Optional

from gui.qt_compat import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QGridLayout, Qt, QFont, Signal,
)
from gui.utils import theme_color

logger = logging.getLogger("maid_coder.gui")

_GRID = 4  # 固定 4x4（首版不做难度切换，design §8.1）
_TARGET = 2048

# 经典 2048 瓦片中性色（游戏内容色，固定；壳面颜色走 theme_color）
_TILE_BG = {
    0: "#CDC1B4",
    2: "#EEE4DA", 4: "#EDE0C8", 8: "#F2B179", 16: "#F59563",
    32: "#F67C5F", 64: "#F65E3B", 128: "#EDCF72", 256: "#EDCC61",
    512: "#EDC850", 1024: "#EDC53F", 2048: "#EDC22E",
}
_FALLBACK_BG = "#3C3A32"          # 超过 2048 后的大块
_TILE_FONT = "#776E65"            # 瓦片数字深棕
_GRID_GAP = 10


class Game2048(QWidget):
    """2048 单局小游戏（纯 Qt、零第三方依赖、零持久化）。"""

    score_changed = Signal(int)
    outcome = Signal(str)

    def __init__(self, app_ctx, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app_ctx = app_ctx
        self._board: List[List[int]] = [[0] * _GRID for _ in range(_GRID)]
        self._labels: List[List[QLabel]] = []
        self._score: int = 0
        self._celebrated: bool = False
        self._over: bool = False
        self._build_ui()
        self.new_game()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 8)
        outer.setSpacing(8)

        # 顶栏：标题说明 + 当前得分 + 重新开局
        top = QHBoxLayout()
        top.setSpacing(10)
        hint = QLabel("方向键 / WASD 移动，合成到 2048 就算成功~")
        hint.setObjectName("g2048Hint")
        hint.setWordWrap(True)
        top.addWidget(hint, 1)
        self.score_label = QLabel("当前得分 0")
        self.score_label.setObjectName("g2048Score")
        top.addWidget(self.score_label)
        restart = QPushButton("重新开局")
        restart.setObjectName("g2048Restart")
        restart.setCursor(Qt.PointingHandCursor)
        restart.clicked.connect(self.new_game)
        top.addWidget(restart)
        outer.addLayout(top)

        # 棋盘：QLabel 瓦片 4x4（纯 Qt 绘制）
        board_host = QWidget()
        board_host.setObjectName("g2048Board")
        grid = QGridLayout(board_host)
        grid.setSpacing(_GRID_GAP)
        grid.setContentsMargins(_GRID_GAP, _GRID_GAP, _GRID_GAP, _GRID_GAP)
        self._labels = []
        for r in range(_GRID):
            row: List[QLabel] = []
            for c in range(_GRID):
                tile = QLabel("")
                tile.setAlignment(Qt.AlignCenter)
                tile.setFixedSize(84, 84)
                tile.setObjectName("g2048Tile")
                grid.addWidget(tile, r, c)
                row.append(tile)
            self._labels.append(row)
        outer.addWidget(board_host, 1)

        # 女仆一句话位（容器/A1 内写入）
        self.maid_line = QLabel("")
        self.maid_line.setObjectName("g2048MaidLine")
        self.maid_line.setWordWrap(True)
        self.maid_line.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.maid_line)

        self._apply_theme()

    def _apply_theme(self) -> None:
        bg_card = theme_color(self.app_ctx, "bg_card", "#FFFFFF")
        bg_light = theme_color(self.app_ctx, "bg_light", "#FFF0F3")
        text = theme_color(self.app_ctx, "text", "#5D4037")
        text_secondary = theme_color(self.app_ctx, "text_secondary", "#8A8A8A")
        accent = theme_color(self.app_ctx, "accent", "#FF6B9D")
        divider = theme_color(self.app_ctx, "divider", "#EFE0E2")
        self.setStyleSheet(
            f"QWidget#g2048Board {{ background: {bg_card}; border: 1px solid {divider};"
            f" border-radius: 14px; }}"
            f"QLabel#g2048Hint {{ color: {text_secondary}; font-size: 12px; background: transparent; }}"
            # 对比度修复：得分/hover 字落在 bg_light 实底上 —— accent 为「填充用」强调色，
            # 四风格实测仅 2.783/1.931/5.317/2.814（三套浅色 <4.5），改用文字色 text
            # （14.492/11.556/12.503/11.980，四套全达标）。
            f"QLabel#g2048Score {{ color: {text}; font-size: 14px; font-weight: bold;"
            f" background: {bg_light}; border-radius: 8px; padding: 6px 10px; }}"
            f"QPushButton#g2048Restart {{ background: {accent}; color: #FFFFFF; border: none;"
            f" border-radius: 8px; padding: 6px 12px; font-size: 12px; }}"
            f"QPushButton#g2048Restart:hover {{ background: {bg_light}; color: {text};"
            f" border: 1px solid {accent}; }}"
            f"QLabel#g2048MaidLine {{ color: {text_secondary}; font-size: 12px; background: transparent; }}"
        )

    # ------------------------------------------------------------------
    # 逻辑
    # ------------------------------------------------------------------
    def new_game(self) -> None:
        """重新开局：清空棋盘、得分清零（绝不读档/不落盘）。"""
        self._board = [[0] * _GRID for _ in range(_GRID)]
        self._score = 0
        self._celebrated = False
        self._over = False
        self._spawn_tile()
        self._spawn_tile()
        self._render()
        self.score_label.setText("当前得分 0")
        self.score_changed.emit(0)
        self.maid_line.setText("码铃把棋盘擦得亮亮的，开始吧~")

    def _empty_cells(self) -> list:
        return [(r, c) for r in range(_GRID) for c in range(_GRID)
                if self._board[r][c] == 0]

    def _spawn_tile(self) -> bool:
        empty = self._empty_cells()
        if not empty:
            return False
        r, c = random.choice(empty)
        self._board[r][c] = 2 if random.random() < 0.9 else 4
        return True

    @staticmethod
    def _line_move(line: List[int]):
        """单行压缩 + 合并（经典 2048 规则）：返回 (新行, 本行得分, 是否移动)。"""
        nums = [v for v in line if v]
        out: List[int] = []
        gained = 0
        i = 0
        while i < len(nums):
            if i + 1 < len(nums) and nums[i] == nums[i + 1]:
                out.append(nums[i] * 2)
                gained += nums[i] * 2
                i += 2
            else:
                out.append(nums[i])
                i += 1
        out += [0] * (_GRID - len(out))
        return out, gained, out != line

    def _slide_rows(self, reverse: bool) -> bool:
        """把四行各自按方向滑动；返回是否发生移动。"""
        moved = False
        gained = 0
        for r in range(_GRID):
            line = self._board[r]
            if reverse:
                line = list(reversed(line))
            new_line, g, m = self._line_move(line)
            if reverse:
                new_line = list(reversed(new_line))
            if m:
                moved = True
            gained += g
            self._board[r] = new_line
        if gained:
            self._score += gained
            self.score_label.setText(f"当前得分 {self._score}")
            self.score_changed.emit(self._score)
        return moved

    def _slide_columns(self, reverse: bool) -> bool:
        """把四列按方向滑动（上/下）。"""
        moved = False
        gained = 0
        for c in range(_GRID):
            col = [self._board[r][c] for r in range(_GRID)]
            if reverse:
                col = list(reversed(col))
            new_col, g, m = self._line_move(col)
            if reverse:
                new_col = list(reversed(new_col))
            if m:
                moved = True
            gained += g
            for r in range(_GRID):
                self._board[r][c] = new_col[r]
        if gained:
            self._score += gained
            self.score_label.setText(f"当前得分 {self._score}")
            self.score_changed.emit(self._score)
        return moved

    def _move(self, direction: str) -> None:
        if self._over:
            return
        if direction == "left":
            moved = self._slide_rows(False)
        elif direction == "right":
            moved = self._slide_rows(True)
        elif direction == "up":
            moved = self._slide_columns(False)
        elif direction == "down":
            moved = self._slide_columns(True)
        else:
            return
        if moved:
            self._spawn_tile()
            self._render()
            self._check_state()
        elif self._no_moves_left():
            self._finish_stuck()

    def _check_state(self) -> None:
        if not self._celebrated and any(
            v >= _TARGET for row in self._board for v in row
        ):
            self._celebrated = True
            self.maid_line.setText("🎉 合成到 2048 啦，主人好厉害！还能继续往上叠哦~")
            self.outcome.emit("reach_2048")
        elif self._no_moves_left():
            self._finish_stuck()

    def _no_moves_left(self) -> bool:
        if self._empty_cells():
            return False
        for r in range(_GRID):
            for c in range(_GRID):
                v = self._board[r][c]
                if c + 1 < _GRID and self._board[r][c + 1] == v:
                    return False
                if r + 1 < _GRID and self._board[r + 1][c] == v:
                    return False
        return True

    def _finish_stuck(self) -> None:
        if self._over:
            return
        self._over = True
        self.maid_line.setText("棋盘满啦，这局到这儿~ 想再来一把就点『重新开局』")
        self.outcome.emit("stuck")

    def _render(self) -> None:
        for r in range(_GRID):
            for c in range(_GRID):
                v = self._board[r][c]
                tile = self._labels[r][c]
                bg = _TILE_BG.get(v, _FALLBACK_BG) if v else _TILE_BG[0]
                fg = "#F9F6F2" if v >= 128 else _TILE_FONT
                if v == 0:
                    tile.setText("")
                else:
                    tile.setText(str(v))
                font = tile.font()
                if v < 128:
                    _fs_px = 35      # 原 26pt
                elif v < 1024:
                    _fs_px = 29      # 原 22pt
                else:
                    _fs_px = 24      # 原 18pt
                font.setBold(True)
                tile.setFont(font)
                # v2.1 后续：应用级 QSS 的 `QWidget { font-size: 14px }` 会压过 setFont，
                # 故值相关字号只写进瓦片自身样式表（控件级优先级最高），三档差异由此保留；
                # 代码侧不再 setPointSize（会被样式表压掉，徒留死行）。
                tile.setStyleSheet(
                    f"QLabel {{ background: {bg}; color: {fg}; border-radius: 10px;"
                    f" font-size: {_fs_px}px; }}"
                )

    # ------------------------------------------------------------------
    # 键盘
    # ------------------------------------------------------------------
    def keyPressEvent(self, event) -> None:
        key = event.key()
        mapping = {
            Qt.Key_Left: "left", Qt.Key_Right: "right",
            Qt.Key_Up: "up", Qt.Key_Down: "down",
            Qt.Key_A: "left", Qt.Key_D: "right",
            Qt.Key_W: "up", Qt.Key_S: "down",
        }
        direction = mapping.get(key)
        if direction:
            self._move(direction)
            return
        super().keyPressEvent(event)
