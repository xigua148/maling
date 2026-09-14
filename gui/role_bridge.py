"""gui/role_bridge.py —— v1.4.2 角色切换广播桥。

角色面板「设为默认角色」生效 / 启动应用默认角色时广播 role_changed，
订阅方（左下角大形象 / 首页大形象 / 聊天气泡头像）按 role_id 换专属形象资产集，
按 avatar_path 换气泡自定义头像。信号广播失败不影响角色切换本身。
"""
from __future__ import annotations

from gui.qt_compat import QObject, Signal


class RoleBridge(QObject):
    """角色生效广播（类似 companion_bridge 的轻量信号桥，app_ctx 单例）。"""

    # (role_id, avatar_path)：avatar_path 为角色自定义头像绝对路径或 ""（未设置）
    role_changed = Signal(str, str, str)

    def notify_role_changed(self, role_id: str, avatar_path: str = "",
                            base_expression: str = "normal") -> None:
        """广播角色生效（防御式：任何异常不阻断切换）。

        base_expression：该角色的基线表情（用户在角色面板设定的当前表情），
        AI 标记表情结束后回落到这里。
        """
        try:
            self.role_changed.emit(
                str(role_id or ""), str(avatar_path or ""),
                str(base_expression or "normal"),
            )
        except Exception:
            pass
