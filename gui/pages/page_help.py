"""帮助页面 —— 使用指南与快捷命令参考。"""
from __future__ import annotations

from typing import Optional

from gui import icons
from gui.qt_compat import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QTextBrowser,
    QHBoxLayout, Qt, QFont,
)
from gui.utils import theme_color


def _vector_icon(app_ctx, name: str, size: int, color):
    """取矢量 ``QIcon``；字体/名字不可用或渲染失败 → ``None``（调用方回落纯文字）。"""
    try:
        if not name or not icons.available() or not icons.has(name):
            return None
        ic = icons.icon(name, size, color)
        if ic is None or ic.isNull():
            return None
        return ic
    except Exception:
        return None


class PageHelp(QWidget):
    """帮助页面。"""

    def __init__(self, app_context, title: str = "帮助", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app_ctx = app_context
        self.title = title
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        # 页面标题（v2.1/V21-12：统一矢量图标；字体不可用时纯文字）
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_label = QLabel("帮助中心")
        title_label.setObjectName("pageTitle")
        title_font = QFont()
        title_font.setBold(True)
        title_label.setFont(title_font)
        tic = _vector_icon(self.app_ctx, "help", 20,
                           theme_color(self.app_ctx, "text", "#5D4037"))
        if tic is not None:
            icon_lab = QLabel()
            icon_lab.setPixmap(tic.pixmap(20, 20))
            icon_lab.setFixedSize(20, 20)
            title_row.addWidget(icon_lab)
        title_row.addWidget(title_label)
        title_row.addStretch()
        layout.addLayout(title_row)

        # 简介
        intro = QLabel("欢迎使用码铃！以下是常用功能和快捷操作指南。")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addSpacing(12)

        # 快捷命令
        cmds_title = QLabel("快捷命令")
        cmds_title.setObjectName("helpSectionTitle")
        cmds_font = QFont()
        cmds_font.setBold(True)
        cmds_title.setFont(cmds_font)
        layout.addWidget(cmds_title)

        cmds_browser = QTextBrowser()
        cmds_browser.setObjectName("helpBrowser")
        cmds_html = """
<p><b>/deep</b> — 切换深度思考模式</p>
<p><b>/code</b> — 切换编程模式</p>
<p><b>/chat</b> — 切换闲聊模式</p>
<p><b>/multi</b> — 切换多模型协作模式</p>
<p><b>/stream</b> — 切换流式输出模式</p>
<p><b>/save</b> — 保存当前会话</p>
<p><b>/load</b> — 加载历史会话</p>
<p><b>/help</b> — 显示帮助信息</p>
"""
        cmds_browser.setHtml(cmds_html)
        layout.addWidget(cmds_browser)

        # 快捷键
        keys_title = QLabel("快捷键")
        keys_title.setObjectName("helpSectionTitle")
        keys_title.setFont(cmds_font)
        layout.addWidget(keys_title)

        keys_browser = QTextBrowser()
        keys_browser.setObjectName("helpBrowser")
        keys_html = """
<p><b>Ctrl + Enter</b> — 发送消息</p>
<p><b>Ctrl + N</b> — 新建对话</p>
<p><b>Ctrl + S</b> — 保存会话</p>
<p><b>Ctrl + O</b> — 加载会话</p>
<p><b>Ctrl + ,</b> — 打开设置</p>
"""
        keys_browser.setHtml(keys_html)
        layout.addWidget(keys_browser)

        # 提示
        tip = QLabel("更多功能请在侧边栏各页面中探索~")
        tip.setObjectName("helpTip")
        layout.addWidget(tip)
        layout.addStretch()

        # 返回按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        back_btn = QPushButton("返回首页")
        back_btn.clicked.connect(self._on_back)
        btn_row.addWidget(back_btn)
        layout.addLayout(btn_row)

    def _on_back(self) -> None:
        pm = getattr(self.app_ctx, "page_manager", None)
        if pm is not None:
            pm.navigate("home")
