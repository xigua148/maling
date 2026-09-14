"""gui/widgets/games —— v1.4(A0) 复杂交互游戏注册表（docs/design-v14.md §2.1/§3.1）

mini_games 容器消费本注册表生成「游戏区」入口与挂载页；荷官四款（抛硬币/抽签/
猜拳/21 点）保留在 mini_games.py 内部清单（kind="dealer" 伪注册项），**不入本表**。

widget 游戏契约（容器按下列约定驱动，本版最小集合）：
  - 定义元组：(gid, label, tip, kind, factory)
      kind == "widget"
      factory: Callable[[AppContext, Optional[QWidget]], QWidget] —— 首次选中时懒建
  - 游戏 QWidget 可选提供：
      * Qt 信号 outcome(str)   —— 一局结束（"reach_2048"/"stuck"/"win"/"lose"…）
      * Qt 信号 score_changed(int) / flags_changed(int)（局内即时值，仅供当局 UI，
        绝不落盘/无排行，R-A/R-E）
      * 方法 new_game()        —— 重新开局
      * QLabel 属性 maid_line  —— 女仆一句话展示位（容器把情绪反馈写到这里，可无）

红线（R-A/R-D/R-F/R-H）：
  - 游戏实现文件保留原项目 MIT 版权头；改动经 docs/THIRD_PARTY.md 登记（A4）。
  - 纯 Qt 实现，零新增第三方依赖；分数仅局内即时值，无任何持久化。
"""
from __future__ import annotations

from typing import Any, Callable, Optional

# 工厂均懒 import 各自游戏模块：避免注册表导入即拉起全部游戏、也允许模块
# 尚未创建时容器照常列出荷官四款（A0 早于 A1/A2 交付的兼容性）。
# 参数签名统一 (app_ctx, parent) -> QWidget。


def _factory_2048(app_ctx: Any, parent: Optional[Any] = None):
    """2048 单文件 widget（A1：MIT tangentecode/2048-pyqt6 移植，局内即时值豁免）。"""
    from gui.widgets.games.game_2048 import Game2048
    return Game2048(app_ctx, parent)


def _factory_minesweeper(app_ctx: Any, parent: Optional[Any] = None):
    """扫雷单文件 widget（A2：MIT dawsonbooth/pynsweeper 移植，去皮/去计时排行）。"""
    from gui.widgets.games.game_minesweeper import GameMinesweeper
    return GameMinesweeper(app_ctx, parent)


# (gid, label, tip, kind, factory)
GAME_DEFS: list = [
    ("game_2048", "🎮 2048", "方向键 / WASD 移动瓦片，合成到 2048", "widget", _factory_2048),
    ("game_minesweeper", "💣 扫雷", "左键翻开格子，右键标旗，排完所有雷即胜", "widget", _factory_minesweeper),
]

__all__ = ["GAME_DEFS"]
