"""消息气泡控件 —— 支持头像、昵称、时间戳、Markdown 渲染、代码块复制、语法高亮、附件展示、消息编辑/重新生成。"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import List, Optional

from gui.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, Qt, QSizePolicy, QFont, QTextBrowser, QFrame,
    QMenu, Signal, QPainter, QColor, QPixmap, QPainterPath,
)
from gui.syntax_highlighter import SimpleSyntaxHighlighter
from gui.utils import theme_color
from gui.widgets.attachment_bar import attachment_icon, human_size

# v1.2 A-10 (B3): AI 气泡旁 Q 版头像 —— 复用 MaidAssets 主形象（圆形裁剪）。
# 防御式接入：companion/资产缺失时 _BUBBLE_MAID_OK=False，_MaidAvatarView 不实例化，
# 回退原「🌸」emoji 头像；头像作为气泡内可选元素，纯增量、零回归。
try:
    from gui.maid_avatar import MaidAssets, mood_to_expression
    _BUBBLE_MAID_OK = MaidAssets is not None
except Exception:
    _BUBBLE_MAID_OK = False

# v1.2 宠物造型全局开关：气泡头像可选「女仆小兽（chibi，assets/maid_pet/）/
# 女仆小人（maid，assets/maid/）」。惰性 import gui.widgets.maid_pet 的 PetAssets
# 与纯决策函数；异常/资产缺失降级 _BUBBLE_PET_OK=False，chibi 自动回退 maid/emoji。
try:
    from gui.widgets.maid_pet import (
        PET_STYLE_CHIBI,
        PET_STYLE_MAID,
        PetAssets as _PetAssetsCls,
        pet_expression_for as _pet_expression_for,
        resolve_pet_style as _resolve_pet_style,
    )
    _BUBBLE_PET_OK = _PetAssetsCls is not None
except Exception:
    PET_STYLE_CHIBI = "chibi"
    PET_STYLE_MAID = "maid"
    _PetAssetsCls = None
    _pet_expression_for = None
    _resolve_pet_style = None
    _BUBBLE_PET_OK = False

_bubble_assets_cache = None
_bubble_pet_assets_cache = None


def _bubble_maid_assets():
    """模块级共享 MaidAssets（避免每个气泡各自解码主形象资产）。"""
    global _bubble_assets_cache
    if _bubble_assets_cache is None and _BUBBLE_MAID_OK:
        try:
            _bubble_assets_cache = MaidAssets()
        except Exception:
            _bubble_assets_cache = None
    return _bubble_assets_cache


def _bubble_pet_assets():
    """模块级共享 PetAssets（assets/maid_pet/ 小兽），供 chibi 造型气泡头像复用。"""
    global _bubble_pet_assets_cache
    if _bubble_pet_assets_cache is None and _BUBBLE_PET_OK:
        try:
            _bubble_pet_assets_cache = _PetAssetsCls()
        except Exception:
            _bubble_pet_assets_cache = None
    return _bubble_pet_assets_cache


class _MaidAvatarView(QWidget):
    """AI 气泡 Q 版头像（32~44px，圆裁）：随 GuiConfig.pet_style 双造型。

      - maid（默认）= 复用 MaidAssets.rounded() 圆形裁剪主形象（assets/maid/）；
      - chibi = 改用 PetAssets（assets/maid_pet/ 小兽）圆裁渲染小兽头像，
        表情经 pet_expression_for 收敛到小兽 5 态；
      - 造型在构造时固化读一次（历史气泡不追溯刷新，新气泡自然取最新）。

    表情联动（B3）：
      - 默认 normal；构造时取 bridge.current_display()（活动态 thinking/focus 优先）；
      - 订阅 companion_bridge.mood_changed —— thinking（思考中）/ focus（Agent 干活）
        由聊天面板经 bridge.note_activity 广播；被夸奖时 companion 心情变 shy/happy，
        下一条回复气泡随 mood_changed 同步切换；
      - companion/资产缺失：本类不被实例化（_BUBBLE_MAID_OK 守卫），气泡纯文本零回归。
    """

    def __init__(self, app_context, expression: str = "normal", size: int = 36,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app_ctx = app_context
        self._size = size
        # v1.2 造型开关：构造时固化读一次（历史气泡不追溯，新气泡自然取最新）
        self._style = (_resolve_pet_style(getattr(app_context, "config", None))
                       if _resolve_pet_style is not None else PET_STYLE_CHIBI)
        self._expr = self._normalize(expression) if _BUBBLE_MAID_OK else "normal"
        self._connected = False
        self._pix_cache: Optional[tuple] = None  # (expr, size) -> QPixmap
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._init_from_current_display()
        self._connect_mood_bridge()

    # -- 当前展示态（bridge 活动态优先；无则 companion.mood / normal）--
    def _current_display_state(self) -> str:
        bridge = getattr(self.app_ctx, "companion_bridge", None)
        try:
            if bridge is not None and hasattr(bridge, "current_display"):
                return bridge.current_display() or "normal"
        except Exception:
            pass
        companion = getattr(self.app_ctx, "companion", None)
        if companion is not None:
            try:
                return companion.mood or "normal"
            except Exception:
                pass
        return "normal"

    def _normalize(self, state: Optional[str]) -> str:
        """把心情/活动态映射为当前造型域的表情 id。

        maid：走 mood_to_expression（8 态主形象）；chibi：收敛到小兽 5 态
        （pet_expression_for，与 assets/maid_pet 微型档口径一致）。chibi 映射源
        不可用时回落 8 态映射（渲染侧会相应回退 maid 资产，不崩）。
        """
        if self._style == PET_STYLE_CHIBI and _pet_expression_for is not None:
            return _pet_expression_for(state)
        return mood_to_expression(state)

    def _init_from_current_display(self) -> None:
        if _BUBBLE_MAID_OK:
            self._expr = self._normalize(self._current_display_state())

    def _connect_mood_bridge(self) -> None:
        if self._connected or not _BUBBLE_MAID_OK:
            return
        bridge = getattr(self.app_ctx, "companion_bridge", None)
        if bridge is None:
            return
        try:
            if hasattr(bridge, "mood_changed") and hasattr(bridge.mood_changed, "connect"):
                bridge.mood_changed.connect(self._on_mood_changed)
                self._connected = True
        except Exception:
            pass

    def _on_mood_changed(self, state: str, reason: str) -> None:
        new = self._normalize(state)
        if new != self._expr:
            self._expr = new
            self._pix_cache = None
            self.update()

    def set_avatar_expression(self, state: str) -> None:
        """外部直设头像表情（保留接口，供后续显式联动调用）。"""
        new = self._normalize(state)
        if new != self._expr:
            self._expr = new
            self._pix_cache = None
            self.update()

    def avatar_expression(self) -> str:
        return self._expr

    def _pick_assets(self):
        """按造型选资产源：chibi -> PetAssets（小兽）；maid -> MaidAssets（小人）。

        源不可用（初始化失败/资产缺失）自动回退另一源，仍无则 paintEvent 走 emoji 兜底。
        """
        if self._style == PET_STYLE_CHIBI:
            pet = _bubble_pet_assets()
            if pet is not None:
                return pet
        return _bubble_maid_assets()

    def paintEvent(self, event) -> None:  # noqa: N802
        assets = self._pick_assets()
        pix = None
        if assets is not None:
            try:
                if self._pix_cache is not None and self._pix_cache[0] == self._expr:
                    pix = self._pix_cache[1]
                else:
                    pix = assets.rounded(self._expr, self._size)
                    self._pix_cache = (self._expr, pix)
            except Exception:
                pix = None
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            if pix is not None:
                painter.drawPixmap(self.rect(), pix)
            else:
                # 极端兜底：资产不可用时画圆形底板 + 铃铛字符（UI 永不空白）
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#FFE4EC"))
                painter.drawEllipse(self.rect())
                painter.setPen(QColor("#E8A9BC"))
                font = painter.font()
                font.setPixelSize(max(12, self._size // 2))
                painter.setFont(font)
                painter.drawText(self.rect(), Qt.AlignCenter, "🌸")
        finally:
            painter.end()


def _role_avatar_pixmap(path: str, size: int):
    """Bug4: 把角色自定义头像文件渲染为圆形 QPixmap（等比缩放 + 居中裁切 + 圆裁）。

    与 page_role.rounded_avatar_pixmap 同口径但自包含（避免 message_bubble ←
    page_role 反向重依赖）。坏图/解码失败返回 None，由调用方回落表情头像。
    """
    if not path:
        return None
    try:
        from gui.qt_compat import QImageReader
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        img = reader.read()
        if img is None or img.isNull() or size <= 0:
            return None
        # 居中取方（唯一丢像素步骤），再等比缩放到目标尺寸
        w, h = img.width(), img.height()
        side = min(w, h)
        if side <= 0:
            return None
        if w != h:
            img = img.copy((w - side) // 2, (h - side) // 2, side, side)
        result = img.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
        if result.isNull():
            return None
        # 圆形裁剪：透明底 + 反走样椭圆蒙版
        out = QPixmap(size, size)
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            clip = QPainterPath()
            clip.addEllipse(0, 0, size, size)
            p.setClipPath(clip)
            # reader.read() 返回 QImage，须先转 QPixmap 再绘制（drawPixmap 无 QImage 重载）
            p.drawPixmap(0, 0, QPixmap.fromImage(result))
        finally:
            p.end()
        return out
    except Exception:
        return None


class MessageBubble(QWidget):
    """单条消息气泡，支持连续消息折叠、Markdown 渲染、动态主题、右键菜单、附件展示、编辑/重新生成。"""

    delete_requested = Signal()
    edit_requested = Signal()
    regenerate_requested = Signal()
    # v1.3(P1-1): AI 气泡「🔊 朗读本条 / ⏹ 停止」点击上报（由 chat_panel/chat_window
    # 接续调 TTSController；只朗读 AI 文本，用户原文不朗读——按钮仅 AI 气泡渲染）
    read_aloud_requested = Signal()
    # v1.3(P2-3): 右键「✨ 收藏为高光回忆」上报 (role, text, meta)；AI 与用户气泡均可收藏
    favorite_requested = Signal(str, str, object)

    def __init__(
        self,
        role: str,
        content: str,
        timestamp: Optional[datetime] = None,
        is_consecutive: bool = False,
        max_bubble_width: int = 320,
        app_context=None,
        parent: Optional[QWidget] = None,
        attachments: Optional[List[dict]] = None,
        error_style: bool = False,  # v10.15: 错误气泡红框
        avatar_path: Optional[str] = None,  # Bug4: 角色自定义头像文件路径（仅 AI 气泡消费）
    ):
        super().__init__(parent)
        self.role = role
        self.raw_content = content
        self.timestamp = timestamp or datetime.now()
        self.is_consecutive = is_consecutive
        self.max_bubble_width = max_bubble_width
        self.app_ctx = app_context
        self.error_style = error_style  # v10.15
        # Bug4: 角色头像路径缓存（空串 = 无自定义头像 → 回落女仆表情头像）
        self.avatar_path = str(avatar_path or "")
        # 兼容 attachment dict（name/path/size/ext）
        self.attachments: List[dict] = []
        for a in attachments or []:
            if isinstance(a, dict):
                # 仅保留已知字段，过滤掉脏数据
                self.attachments.append({
                    "name": str(a.get("name", "")),
                    "path": str(a.get("path", "")),
                    "size": int(a.get("size", 0) or 0),
                    "ext": str(a.get("ext", "")),
                })
        self._theme_colors = self._get_theme_colors()
        self._tts_reading = False  # v1.3(P1-1): 本气泡是否正在被朗读（决定按钮文案）
        self._init_ui()
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def _get_theme_colors(self) -> dict:
        """从主题引擎获取当前颜色，若不可用则返回默认值。"""
        theme_engine = getattr(self.app_ctx, "theme_engine", None) if self.app_ctx else None
        if theme_engine is None:
            return {
                "user_bubble": "#FF9EB5",
                "ai_bubble": "#FFFFFF",
                "user_text": "#FFFFFF",
                "ai_text": "#4A4A4A",
                "accent": "#FF6B9D",
                "accent_light": "#FFB6C1",
                "bg_light": "#FFF0F3",
            }
        return {
            "user_bubble": theme_engine.get_color("bubble_user_bg", "#FF9EB5"),
            "ai_bubble": theme_engine.get_color("bubble_ai_bg", "#FFFFFF"),
            "user_text": theme_engine.get_color("bubble_user_text", "#FFFFFF"),
            "ai_text": theme_engine.get_color("bubble_ai_text", "#4A4A4A"),
            "accent": theme_engine.get_color("accent", "#FF6B9D"),
            "accent_light": theme_engine.get_color("accent_light", "#FFB6C1"),
            "bg_light": theme_engine.get_color("bg_light", "#FFF0F3"),
        }

    def _apply_theme(self) -> None:
        """应用当前主题颜色到气泡样式。"""
        is_user = self.role == "user"
        c = self._theme_colors
        bubble = self.findChild(QWidget, "bubbleFrame")
        if bubble is None:
            return
        if is_user:
            bubble.setStyleSheet(
                f"QWidget#bubbleFrame {{"
                f"  background-color: {c['user_bubble']};"
                f"  color: {c['user_text']};"
                f"  border-top-left-radius: 16px;"
                f"  border-top-right-radius: 4px;"
                f"  border-bottom-left-radius: 16px;"
                f"  border-bottom-right-radius: 16px;"
                f"  padding: 12px 16px;"
                f"}}"
            )
        else:
            # v10.15: 错误气泡在主题刷新时也保持红框
            if self.error_style:
                bubble.setStyleSheet(
                    f"QWidget#bubbleFrame {{"
                    f"  background-color: #FFF0F0;"
                    f"  color: #B71C1C;"
                    f"  border: 2px solid #E53935;"
                    f"  border-top-left-radius: 4px;"
                    f"  border-top-right-radius: 16px;"
                    f"  border-bottom-left-radius: 16px;"
                    f"  border-bottom-right-radius: 16px;"
                    f"  padding: 12px 16px;"
                    f"}}"
                )
                return
            bubble.setStyleSheet(
                f"QWidget#bubbleFrame {{"
                f"  background-color: {c['ai_bubble']};"
                f"  color: {c['ai_text']};"
                f"  border: 1px solid {c['accent_light']};"
                f"  border-top-left-radius: 4px;"
                f"  border-top-right-radius: 16px;"
                f"  border-bottom-left-radius: 16px;"
                f"  border-bottom-right-radius: 16px;"
                f"  padding: 12px 16px;"
                f"}}"
            )
        # 刷新内容
        self.update_text(self.raw_content)
        # 刷新附件 widget 颜色（仅 AI 角色使用了主题色；user 角色文字色为白，硬编码即可）
        # R12: 清理死代码（空循环体）并改用 != 写法
        if self.role != "user":
            att_widget = self.findChild(QWidget, "bubbleAttachments")
            if att_widget is not None:
                bg_overlay = theme_color(self.app_ctx, "bg_light", "#FFF0F3")
                att_widget.setStyleSheet(
                    f"QWidget#bubbleAttachments {{"
                    f"  background: {bg_overlay};"
                    f"  border-radius: 8px; padding: 2px;"
                    f"}}"
                )
                text_color = theme_color(self.app_ctx, "text", "#4A4A4A")
                # 找到容器内 QLabel 一并刷新（图标标签保留默认 font-size 即可）
                for lab in att_widget.findChildren(QLabel):
                    current = lab.styleSheet() or ""
                    if "font-size: 12px;" in current:
                        lab.setStyleSheet(
                            f"QLabel {{ color: {text_color}; font-size: 12px; }}"
                        )
                    elif "font-size: 10px;" in current:
                        lab.setStyleSheet(
                            f"QLabel {{ color: {text_color}; font-size: 10px; opacity: 0.8; }}"
                        )
        # 重新生成按钮（仅 AI 消息）
        regen_btn = self.findChild(QPushButton, "regenBtn")
        if regen_btn is not None:
            regen_btn.setStyleSheet(self._regen_btn_style())
        # v1.3(P1-1): 朗读按钮随主题刷新（保留当前 朗读中/待朗读 视觉态）
        read_btn = self.findChild(QPushButton, "readAloudBtn")
        if read_btn is not None:
            read_btn.setStyleSheet(self._read_btn_style(active=self._tts_reading))

    def update_theme(self) -> None:
        """外部调用：主题变更时刷新颜色。"""
        self._theme_colors = self._get_theme_colors()
        self._apply_theme()

    def _show_context_menu(self, pos) -> None:
        """右键菜单：收藏高光 / 复制文本 / 删除消息 / 编辑或重新生成。"""
        menu = QMenu(self)
        favorite_action = menu.addAction("✨ 收藏为高光回忆")
        menu.addSeparator()
        copy_action = menu.addAction("复制文本")
        copy_md_action = menu.addAction("复制 Markdown")
        # 角色相关操作
        edit_action = None
        regen_action = None
        if self.role == "user":
            edit_action = menu.addAction("编辑消息")
        else:
            regen_action = menu.addAction("重新生成")
        menu.addSeparator()
        delete_action = menu.addAction("删除消息")
        action = menu.exec_(self.mapToGlobal(pos))
        if action == favorite_action:
            self.favorite_requested.emit(self.role, self.raw_content, {})
        elif action == copy_action:
            self._copy_content()
        elif action == copy_md_action:
            self._copy_to_clipboard(self.raw_content)
        elif edit_action is not None and action == edit_action:
            self.edit_requested.emit()
        elif regen_action is not None and action == regen_action:
            self.regenerate_requested.emit()
        elif action == delete_action:
            self.delete_requested.emit()

    def _init_ui(self) -> None:
        is_user = self.role == "user"
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(12, 4 if self.is_consecutive else 8, 12, 4)
        main_layout.setSpacing(8)

        # --- 头像区域（仅非连续消息显示）---
        if not self.is_consecutive:
            avatar = None
            # Bug4: 角色自定义头像优先 —— 有路径且文件有效时用它（圆形裁剪）。
            # 文件缺失/坏图回落 _MaidAvatarView 表情头像；历史气泡不追溯。
            if not is_user and self.avatar_path and os.path.isfile(self.avatar_path):
                pix = _role_avatar_pixmap(self.avatar_path, 36)
                if pix is not None and not pix.isNull():
                    role_avatar = QLabel()
                    role_avatar.setFixedSize(36, 36)
                    role_avatar.setPixmap(pix)
                    role_avatar.setObjectName("avatarLabel")
                    avatar = role_avatar
            # v1.2 A-10 (B3): AI 气泡换 Q 版女仆头像（圆裁主形象 + mood 联动）。
            # 防御式：资产/companion 缺失或实例化失败 -> 回落原 emoji（零回归）。
            if avatar is None and not is_user and _BUBBLE_MAID_OK:
                try:
                    avatar = _MaidAvatarView(
                        self.app_ctx, expression="normal", size=36, parent=self
                    )
                except Exception:
                    avatar = None
            if avatar is None:
                avatar = QLabel("🧑" if is_user else "🌸")
                avatar.setFixedSize(36, 36)
                avatar.setAlignment(Qt.AlignCenter)
                avatar.setObjectName("avatarLabel")
                avatar.setStyleSheet(
                    "QLabel { background-color: #FFF0F3; border-radius: 18px;"
                    " border: 2px solid #FFB6C1; font-size: 16px; }"
                )
        else:
            avatar = None

        # --- 内容区域 ---
        content_area = QWidget()
        content_layout = QVBoxLayout(content_area)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(2)

        # 元信息行（昵称 + 时间戳）
        if not self.is_consecutive:
            meta_layout = QHBoxLayout()
            meta_layout.setContentsMargins(0, 0, 0, 0)
            meta_layout.setSpacing(8)

            name_label = QLabel("主人" if is_user else "女仆")
            name_label.setObjectName("nameLabel")
            name_color = "#FF9EB5" if is_user else "#FF6B9D"
            name_label.setStyleSheet(
                f"QLabel {{ font-size: 12px; font-weight: 500; color: {name_color}; padding: 0 4px; }}"
            )
            meta_layout.addWidget(name_label)

            time_str = self.timestamp.strftime("%H:%M")
            time_label = QLabel(time_str)
            time_label.setObjectName("timeLabel")
            time_label.setStyleSheet(
                "QLabel { font-size: 10px; color: #BBBBBB; padding-left: 8px; }"
            )
            meta_layout.addWidget(time_label)
            meta_layout.addStretch()
            content_layout.addLayout(meta_layout)

        # 气泡主体
        bubble = QWidget()
        bubble.setObjectName("bubbleFrame")
        bubble.setMaximumWidth(self.max_bubble_width)

        # 气泡样式（使用主题颜色）
        c = self._theme_colors
        if is_user:
            bubble.setStyleSheet(
                f"QWidget#bubbleFrame {{"
                f"  background-color: {c['user_bubble']};"
                f"  color: {c['user_text']};"
                f"  border-top-left-radius: 16px;"
                f"  border-top-right-radius: 4px;"
                f"  border-bottom-left-radius: 16px;"
                f"  border-bottom-right-radius: 16px;"
                f"  padding: 12px 16px;"
                f"}}"
            )
        else:
            # v10.15: 错误气泡走红框 + 浅红底，明确告诉用户这是失败而非助手回复
            if self.error_style:
                bubble.setStyleSheet(
                    f"QWidget#bubbleFrame {{"
                    f"  background-color: #FFF0F0;"
                    f"  color: #B71C1C;"
                    f"  border: 2px solid #E53935;"
                    f"  border-top-left-radius: 4px;"
                    f"  border-top-right-radius: 16px;"
                    f"  border-bottom-left-radius: 16px;"
                    f"  border-bottom-right-radius: 16px;"
                    f"  padding: 12px 16px;"
                    f"}}"
                )
            else:
                bubble.setStyleSheet(
                    f"QWidget#bubbleFrame {{"
                    f"  background-color: {c['ai_bubble']};"
                    f"  color: {c['ai_text']};"
                    f"  border: 1px solid {c['accent_light']};"
                    f"  border-top-left-radius: 4px;"
                    f"  border-top-right-radius: 16px;"
                    f"  border-bottom-left-radius: 16px;"
                    f"  border-bottom-right-radius: 16px;"
                    f"  padding: 12px 16px;"
                    f"}}"
                )

        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(12, 10, 12, 10)
        bubble_layout.setSpacing(6)

        # 内容区域
        content_widget = self._build_content_widget(self.raw_content, is_user)
        bubble_layout.addWidget(content_widget)

        # 附件展示（文件名 + 类型图标 + 大小）
        if self.attachments:
            attachments_widget = self._build_attachments_widget()
            bubble_layout.addWidget(attachments_widget)

        # 操作按钮栏（仅 AI 消息）
        if not is_user:
            action_row = QHBoxLayout()
            action_row.setContentsMargins(0, 4, 0, 0)
            action_row.setSpacing(8)

            copy_btn = QPushButton("复制")
            copy_btn.setObjectName("actionBtn")
            copy_btn.setFixedSize(48, 24)
            copy_btn.setCursor(Qt.PointingHandCursor)
            copy_btn.setStyleSheet(
                "QPushButton { background: transparent; border: 1px solid #FFE4EC;"
                " border-radius: 6px; color: #BBBBBB; font-size: 11px; padding: 2px 8px; }"
                "QPushButton:hover { background: #FFF0F3; border-color: #FFB6C1; color: #FF6B9D; }"
            )
            copy_btn.clicked.connect(self._copy_content)
            action_row.addWidget(copy_btn)

            # v1.3(P1-1): 朗读本条 —— AI 气泡同排按钮（朗读中切「⏹ 停止」，
            # 按钮态由 chat_panel/chat_window 经 TTSController.state_changed 驱动）
            read_btn = QPushButton("🔊 朗读本条")
            read_btn.setObjectName("readAloudBtn")
            read_btn.setFixedHeight(24)
            read_btn.setCursor(Qt.PointingHandCursor)
            read_btn.setToolTip("朗读本条 AI 回复（只朗读 AI 文本，不朗读你的原文）")
            read_btn.setStyleSheet(self._read_btn_style(active=False))
            read_btn.clicked.connect(self._on_read_aloud_clicked)
            action_row.addWidget(read_btn)

            # 重新生成（新增）
            regen_btn = QPushButton("重新生成")
            regen_btn.setObjectName("regenBtn")
            regen_btn.setFixedSize(64, 24)
            regen_btn.setCursor(Qt.PointingHandCursor)
            regen_btn.setToolTip("清空该条回复并重新请求流式输出")
            regen_btn.setStyleSheet(self._regen_btn_style())
            regen_btn.clicked.connect(self.regenerate_requested.emit)
            action_row.addWidget(regen_btn)

            action_row.addStretch()
            bubble_layout.addLayout(action_row)

        content_layout.addWidget(bubble)

        # --- 整体对齐 ---
        if is_user:
            if avatar:
                main_layout.addStretch()
                main_layout.addWidget(content_area)
                main_layout.addWidget(avatar)
            else:
                main_layout.addStretch()
                main_layout.addWidget(content_area)
        else:
            if avatar:
                main_layout.addWidget(avatar)
                main_layout.addWidget(content_area)
                main_layout.addStretch()
            else:
                main_layout.addWidget(content_area)
                main_layout.addStretch()

    @staticmethod
    def _make_adaptive_browser(html: str) -> "QTextBrowser":
        """v1.4.6: 高度自适应文档内容的只读浏览器。

        QTextBrowser 默认在布局中高度不随内容撑开（内容长时被裁剪，且内滚动
        已关闭 -> 用户"看不全"）。这里按文档实际尺寸动态 setFixedHeight，
        宽度变化（窗口拉伸/换行重排）时通过 resizeEvent 重算。
        Bug6: 取消 6000px 高度上限 —— 长回复完整撑开气泡，超出部分由外层
        聊天滚动区承接（气泡内滚动保持关闭，阅读体验一致）。
        """
        browser = QTextBrowser()
        browser.setReadOnly(True)
        browser.setFrameShape(QFrame.Shape.NoFrame)
        browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        browser.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        browser.setStyleSheet("QTextBrowser { background: transparent; border: none; }")
        browser.setHtml(html)
        browser.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        def _adjust():
            try:
                doc_h = int(browser.document().size().height()
                            + 2 * browser.document().documentMargin() + 4)
                browser.setFixedHeight(max(24, doc_h))
            except Exception:
                pass

        _orig_resize = browser.resizeEvent

        def _resize_event(ev):
            _orig_resize(ev)
            _adjust()

        browser.resizeEvent = _resize_event  # type: ignore[assignment]
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, _adjust)  # 布局完成后再算一次（宽度就位）
        return browser

    def _build_content_widget(self, content: str, is_user: bool) -> QWidget:
        """根据内容构建展示控件（支持 Markdown 渲染 + 代码块 + 语法高亮）。"""
        code_blocks = list(re.finditer(r"```(\w*)\n(.*?)```", content, re.DOTALL))

        if not code_blocks:
            # 纯文本 —— Markdown 转 HTML
            return self._make_adaptive_browser(self._markdown_to_html(content, is_user))

        # 混合内容：文本 + 代码块
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        last_end = 0
        for match in code_blocks:
            start, end = match.span()
            lang = match.group(1) or "text"
            code = match.group(2)

            if start > last_end:
                text_part = content[last_end:start].strip()
                if text_part:
                    layout.addWidget(self._make_adaptive_browser(
                        self._markdown_to_html(text_part, is_user)))

            code_widget = self._build_code_block(code, lang)
            layout.addWidget(code_widget)
            last_end = end

        if last_end < len(content):
            tail = content[last_end:].strip()
            if tail:
                browser = self._make_adaptive_browser(
                    self._markdown_to_html(tail, is_user))
                browser.setHtml(self._markdown_to_html(tail, is_user))
                layout.addWidget(browser)

        return container

    def _markdown_to_html(self, text: str, is_user: bool) -> str:
        """将 Markdown 文本转为 HTML，使用当前主题颜色。"""
        c = self._theme_colors
        html = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        # 水平分隔线 --- / *** / ___
        html = re.sub(
            r"^([\-*_])\s*\1\s*\1\s*$",
            '<hr style="border:none;border-top:1px solid ' + c["accent_light"] + ';margin:12px 0;">',
            html,
            flags=re.MULTILINE,
        )

        # 行内代码 `code`
        code_bg = "rgba(255,255,255,0.15)" if is_user else self._hex_to_rgba(c["accent"], 0.12)
        code_color = c["user_text"] if is_user else c["accent"]
        html = re.sub(
            r"`([^`]+?)`",
            rf'<span style="background:{code_bg};color:{code_color};'
            rf'padding:2px 5px;border-radius:3px;font-family:Consolas,monospace;font-size:13px;">\1</span>',
            html,
        )

        # 粗体 **text**
        bold_color = c["user_text"] if is_user else c["accent"]
        html = re.sub(
            r"\*\*([^*]+?)\*\*",
            rf'<b style="color:{bold_color};font-weight:600;">\1</b>',
            html,
        )

        # 斜体 *text*（不与粗体重叠）
        html = re.sub(
            r"(?<!\*)\*([^*\s][^*]*?)\*(?!\*)",
            rf'<i style="color:{bold_color};opacity:0.9;">\1</i>',
            html,
        )

        # 有序列表 1. / 2. 等
        ol_pattern = re.compile(r"^(\d+)\.\s+(.*)$", re.MULTILINE)
        ol_items = []
        ol_match = False
        lines = html.split("\n")
        result_lines = []
        for line in lines:
            m = ol_pattern.match(line)
            if m:
                if not ol_match:
                    ol_match = True
                    ol_items = []
                ol_items.append(m.group(2))
            else:
                if ol_match:
                    lis = "".join(
                        f'<li style="margin:3px 0;padding-left:4px;">{item}</li>' for item in ol_items
                    )
                    result_lines.append(
                        f'<ol style="margin:6px 0;padding-left:20px;color:{c["user_text"] if is_user else c["ai_text"]};">'
                        f'{lis}</ol>'
                    )
                    ol_match = False
                result_lines.append(line)
        if ol_match:
            lis = "".join(
                f'<li style="margin:3px 0;padding-left:4px;">{item}</li>' for item in ol_items
            )
            result_lines.append(
                f'<ol style="margin:6px 0;padding-left:20px;color:{c["user_text"] if is_user else c["ai_text"]};">'
                f'{lis}</ol>'
            )
        html = "\n".join(result_lines)

        # 无序列表 - / * / +
        ul_pattern = re.compile(r"^([\-*+])\s+(.*)$", re.MULTILINE)
        ul_items = []
        ul_match = False
        lines = html.split("\n")
        result_lines = []
        for line in lines:
            m = ul_pattern.match(line)
            if m:
                if not ul_match:
                    ul_match = True
                    ul_items = []
                ul_items.append(m.group(2))
            else:
                if ul_match:
                    lis = "".join(
                        f'<li style="margin:3px 0;padding-left:4px;">{item}</li>' for item in ul_items
                    )
                    result_lines.append(
                        f'<ul style="margin:6px 0;padding-left:20px;list-style-type:disc;color:{c["user_text"] if is_user else c["ai_text"]};">'
                        f'{lis}</ul>'
                    )
                    ul_match = False
                result_lines.append(line)
        if ul_match:
            lis = "".join(
                f'<li style="margin:3px 0;padding-left:4px;">{item}</li>' for item in ul_items
            )
            result_lines.append(
                f'<ul style="margin:6px 0;padding-left:20px;list-style-type:disc;color:{c["user_text"] if is_user else c["ai_text"]};">'
                f'{lis}</ul>'
            )
        html = "\n".join(result_lines)

        # 引用块 > text
        lines = html.split("\n")
        result = []
        in_quote = False
        quote_lines = []

        q_bg_user = "rgba(255,255,255,0.1)"
        q_bg_ai = self._hex_to_rgba(c["accent_light"], 0.08)
        q_border_user = c["user_text"]
        q_border_ai = c["accent_light"]

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("&gt;"):
                in_quote = True
                quote_lines.append(stripped[4:].strip())
            else:
                if in_quote:
                    q_bg = q_bg_user if is_user else q_bg_ai
                    q_border = q_border_user if is_user else q_border_ai
                    q_text = "<br>".join(quote_lines)
                    result.append(
                        f'<div style="border-left:3px solid {q_border};background:{q_bg};'
                        f'padding:6px 12px;margin:8px 0;border-radius:0 4px 4px 0;">{q_text}</div>'
                    )
                    in_quote = False
                    quote_lines = []
                result.append(line)

        if in_quote:
            q_bg = q_bg_user if is_user else q_bg_ai
            q_border = q_border_user if is_user else q_border_ai
            q_text = "<br>".join(quote_lines)
            result.append(
                f'<div style="border-left:3px solid {q_border};background:{q_bg};'
                f'padding:6px 12px;margin:8px 0;border-radius:0 4px 4px 0;">{q_text}</div>'
            )

        html = "\n".join(result)

        # 分段
        paragraphs = html.split("\n\n")
        formatted = []
        for p in paragraphs:
            p = p.strip()
            if not p:
                continue
            # 跳过已包装的列表/引用块/hr
            if p.startswith(("<ol", "<ul", "<div", "<hr")):
                formatted.append(p)
            else:
                p = p.replace("\n", "<br>")
                formatted.append(f'<p style="margin:0 0 8px 0;line-height:1.6;">{p}</p>')

        text_color = c["user_text"] if is_user else c["ai_text"]
        return (
            f'<div style="color:{text_color};font-family:Microsoft YaHei,Segoe UI,sans-serif;'
            f'font-size:14px;line-height:1.6;">{"".join(formatted)}</div>'
        )

    @staticmethod
    def _hex_to_rgba(hex_color: str, alpha: float) -> str:
        """将 #RRGGBB 转为 rgba(R,G,B,A)。"""
        hex_color = hex_color.lstrip("#")
        if len(hex_color) == 3:
            hex_color = "".join(c * 2 for c in hex_color)
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        return f"rgba({r},{g},{b},{alpha})"

    def _build_code_block(self, code: str, lang: str) -> QWidget:
        """构建代码块展示控件（含语法高亮）。"""
        container = QWidget()
        container.setObjectName("codeBlock")
        container.setStyleSheet(
            "QWidget#codeBlock { background-color: #2D2D2D; border-radius: 8px; }"
        )
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        header = QHBoxLayout()
        lang_label = QLabel(lang.upper() if lang else "CODE")
        lang_label.setObjectName("codeLangLabel")
        lang_label.setStyleSheet(
            "QLabel { color: #AAAAAA; font-size: 10px; font-weight: bold; }"
        )
        header.addWidget(lang_label)
        header.addStretch()
        copy_btn = QPushButton("复制代码")
        copy_btn.setObjectName("copyCodeBtn")
        copy_btn.setFixedSize(64, 22)
        copy_btn.setCursor(Qt.PointingHandCursor)
        copy_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #888888;"
            " border: 1px solid #555555; border-radius: 4px; font-size: 11px; padding: 2px 6px; }"
            "QPushButton:hover { background: #444444; color: #FFFFFF; }"
        )
        copy_btn.clicked.connect(lambda: self._copy_to_clipboard(code))
        header.addWidget(copy_btn)
        layout.addLayout(header)

        editor = QTextEdit()
        editor.setPlainText(code)
        editor.setReadOnly(True)
        editor.setLineWrapMode(QTextEdit.NoWrap)
        editor.setMaximumHeight(300)
        editor.setObjectName("codeEditor")
        editor.setStyleSheet(
            "QTextEdit#codeEditor { background-color: #2D2D2D; color: #F8F8F2;"
            " border: none; border-radius: 4px; font-family: Consolas, JetBrains Mono, monospace; font-size: 12px; }"
        )
        font = QFont("Consolas, JetBrains Mono, monospace")
        font.setPointSize(10)
        editor.setFont(font)

        # 应用语法高亮
        if lang:
            SimpleSyntaxHighlighter(editor.document(), lang)

        layout.addWidget(editor)
        return container

    def update_text(self, new_content: str) -> None:
        """更新消息内容，用于流式输出时原地刷新。"""
        self.raw_content = new_content
        # 找到 bubbleFrame 并替换内容 widget
        bubble = self.findChild(QWidget, "bubbleFrame")
        if bubble is None:
            return
        bubble_layout = bubble.layout()
        # 第一个 widget 是内容区域
        if bubble_layout.count() > 0:
            old_widget = bubble_layout.itemAt(0).widget()
            if old_widget is not None:
                bubble_layout.removeWidget(old_widget)
                old_widget.deleteLater()
        is_user = self.role == "user"
        new_widget = self._build_content_widget(new_content, is_user)
        bubble_layout.insertWidget(0, new_widget)

    def get_text(self) -> str:
        """获取消息原始文本内容。"""
        return self.raw_content

    def get_attachments(self) -> List[dict]:
        """获取附件元信息列表（用于持久化）。"""
        return list(self.attachments)

    def _copy_content(self) -> None:
        """复制整条消息内容。"""
        self._copy_to_clipboard(self.raw_content)

    # ------------------------------------------------------------------
    # 附件展示（新增）
    # ------------------------------------------------------------------
    def _regen_btn_style(self) -> str:
        border = theme_color(self.app_ctx, "border", "#FFE4EC")
        text = theme_color(self.app_ctx, "text_secondary", "#8A8A8A")
        bg_light = theme_color(self.app_ctx, "bg_light", "#FFF0F3")
        accent_light = theme_color(self.app_ctx, "accent_light", "#FFB6C1")
        accent = theme_color(self.app_ctx, "accent", "#FF6B9D")
        return (
            f"QPushButton#regenBtn {{"
            f"  background: transparent; border: 1px solid {border};"
            f"  border-radius: 6px; color: {text}; font-size: 11px; padding: 2px 8px;"
            f"}}"
            f"QPushButton#regenBtn:hover {{"
            f"  background: {bg_light}; border-color: {accent_light}; color: {accent};"
            f"}}"
        )

    # ---- v1.3(P1-1): 朗读按钮样式与状态 ----
    def _read_btn_style(self, active: bool = False) -> str:
        """朗读按钮：待朗读 = 描边灰字（同复制键）；朗读中 = 主题色实底白字。"""
        border = theme_color(self.app_ctx, "border", "#FFE4EC")
        text = theme_color(self.app_ctx, "text_secondary", "#8A8A8A")
        bg_light = theme_color(self.app_ctx, "bg_light", "#FFF0F3")
        accent_light = theme_color(self.app_ctx, "accent_light", "#FFB6C1")
        accent = theme_color(self.app_ctx, "accent", "#FF6B9D")
        if active:
            return (
                f"QPushButton#readAloudBtn {{"
                f"  background: {accent}; border: 1px solid {accent};"
                f"  border-radius: 6px; color: #FFFFFF; font-size: 11px; padding: 2px 8px;"
                f"}}"
                f"QPushButton#readAloudBtn:hover {{ background: {accent_light}; border-color: {accent_light}; }}"
            )
        return (
            f"QPushButton#readAloudBtn {{"
            f"  background: transparent; border: 1px solid {border};"
            f"  border-radius: 6px; color: {text}; font-size: 11px; padding: 2px 8px;"
            f"}}"
            f"QPushButton#readAloudBtn:hover {{"
            f"  background: {bg_light}; border-color: {accent_light}; color: {accent};"
            f"}}"
        )

    def _on_read_aloud_clicked(self) -> None:
        """点击朗读/停止：AI 气泡才可朗读；经信号上报由面板/浮窗接续调 TTS。"""
        if self.role != "assistant":
            return
        self.read_aloud_requested.emit()

    def set_read_aloud(self, active: bool) -> None:
        """朗读归属变化时由容器调用：active=True = 本气泡正在朗读（切「⏹ 停止」）。"""
        self._tts_reading = bool(active)
        btn = self.findChild(QPushButton, "readAloudBtn")
        if btn is None:
            return
        btn.setText("⏹ 停止" if active else "🔊 朗读本条")
        btn.setToolTip("停止朗读" if active else "朗读本条 AI 回复（只朗读 AI 文本）")
        btn.setStyleSheet(self._read_btn_style(active=active))

    def is_reading(self) -> bool:
        return self._tts_reading

    def _build_attachments_widget(self) -> QWidget:
        """构建附件列表展示控件。"""
        container = QWidget()
        container.setObjectName("bubbleAttachments")
        # 半透明 overlay 风格
        if self.role == "user":
            bg_overlay = "rgba(255,255,255,0.18)"
            text_color = "#FFFFFF"
        else:
            bg_overlay = theme_color(self.app_ctx, "bg_light", "#FFF0F3")
            text_color = theme_color(self.app_ctx, "text", "#4A4A4A")

        container.setStyleSheet(
            f"QWidget#bubbleAttachments {{"
            f"  background: {bg_overlay};"
            f"  border-radius: 8px;"
            f"  padding: 2px;"
            f"}}"
        )
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)

        for att in self.attachments:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            icon = QLabel(attachment_icon(att.get("name", ""), att.get("ext", "")))
            icon.setStyleSheet("font-size: 13px;")
            row.addWidget(icon)
            name = QLabel(att.get("name", ""))
            name.setStyleSheet(
                f"QLabel {{ color: {text_color}; font-size: 12px; }}"
            )
            name.setToolTip(att.get("path", ""))
            row.addWidget(name, 1)
            size = QLabel(human_size(int(att.get("size", 0) or 0)))
            size.setStyleSheet(
                f"QLabel {{ color: {text_color}; font-size: 10px; opacity: 0.8; }}"
            )
            row.addWidget(size)
            layout.addLayout(row)
        return container

    @staticmethod
    def _copy_to_clipboard(text: str) -> None:
        from gui.qt_compat import QApplication
        app = QApplication.instance()
        if app is not None:
            clipboard = app.clipboard()
            if clipboard is not None:
                clipboard.setText(text)
