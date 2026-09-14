"""关于页面 —— 版本号、开源协议、致谢。"""
from __future__ import annotations

from typing import Optional

from gui.qt_compat import (
    QWidget, QVBoxLayout, QLabel, QPushButton,
    QHBoxLayout, QFrame, Qt, QFont,
)

# v10.15: 关于页版本号硬编码改为读 core.__version__
from core import __version__ as CORE_VERSION

# v1.4(A4): 内置第三方开源组件静态表（内容与 docs/THIRD_PARTY.md「已纳入组件」一致）
_THIRD_PARTY_ITEMS = [
    "2048 —— tangentecode/2048-pyqt6（MIT，Copyright (c) 2024 jøhann）",
    "　　仓库：https://github.com/tangentecode/2048-pyqt6",
    "扫雷 —— dawsonbooth/pynsweeper（MIT，Copyright (c) 2020 Dawson Booth）",
    "　　仓库：https://github.com/dawsonbooth/pynsweeper",
    # v1.9 B/R-L②: 内置字体（OFL 1.1，许可副本随包 docs/third_party_licenses/）
    "资源圆体 Resource Han Rounded —— CyanoHao/Resource-Han-Rounded（OFL 1.1）",
    "　　仓库：https://github.com/CyanoHao/Resource-Han-Rounded　用途：正文 / 界面默认字体",
    "jf open 粉圆 Open Huninn —— justfont/open-huninn-font（OFL 1.1）",
    "　　仓库：https://github.com/justfont/open-huninn-font　用途：标题 / 点缀（子集）",
]


class PageAbout(QWidget):
    """关于页面。"""

    def __init__(self, app_context, title: str = "关于", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app_ctx = app_context
        self.title = title
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        # 页面标题
        title_label = QLabel("关于码铃")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        # 版本信息卡片
        version_card = QFrame()
        version_card.setObjectName("aboutCard")
        version_card.setFrameShape(QFrame.Shape.StyledPanel)
        v_layout = QVBoxLayout(version_card)
        v_layout.setContentsMargins(20, 20, 20, 20)
        v_layout.setSpacing(12)

        v_layout.addWidget(QLabel("<b>码铃 MaLing</b>"))
        v_layout.addWidget(QLabel(f"版本: v{CORE_VERSION}"))  # v10.15
        v_layout.addWidget(QLabel("基于 PySide6 构建的桌面应用"))
        v_layout.addWidget(QLabel("码铃 — 您的专属 AI 编程助手"))

        # v2.0(D-V20-03/§5.1): 更新源展示 + 手动「检查更新」入口（开源组件表不动）
        v_layout.addWidget(QLabel(f"更新源: {self._update_source_host()}"))
        upd_row = QHBoxLayout()
        self.check_update_btn = QPushButton("检查更新")
        self.check_update_btn.clicked.connect(self._on_check_update)
        upd_row.addWidget(self.check_update_btn)
        self.update_state_label = QLabel("")
        self.update_state_label.setWordWrap(True)
        upd_row.addWidget(self.update_state_label)
        upd_row.addStretch()
        v_layout.addLayout(upd_row)

        layout.addWidget(version_card)

        # 开源协议
        license_card = QFrame()
        license_card.setObjectName("aboutCard")
        license_card.setFrameShape(QFrame.Shape.StyledPanel)
        l_layout = QVBoxLayout(license_card)
        l_layout.setContentsMargins(20, 20, 20, 20)
        l_layout.setSpacing(12)

        l_layout.addWidget(QLabel("<b>开源协议</b>"))
        l_layout.addWidget(QLabel("本项目基于 MIT 协议开源"))
        l_layout.addWidget(QLabel("第三方依赖: PySide6 (LGPL), PyYAML (MIT), requests (Apache-2.0)"))
        layout.addWidget(license_card)

        # v1.4(A4): 内置第三方开源组件（R-H 归属：docs/THIRD_PARTY.md）
        # 静态表展示（随包只读，避免运行时读文档路径；内容与 THIRD_PARTY.md 保持一致）
        open_card = QFrame()
        open_card.setObjectName("aboutCard")
        open_card.setFrameShape(QFrame.Shape.StyledPanel)
        o_layout = QVBoxLayout(open_card)
        o_layout.setContentsMargins(20, 20, 20, 20)
        o_layout.setSpacing(8)

        o_layout.addWidget(QLabel("<b>内置开源组件</b>"))
        o_layout.addWidget(QLabel("以下开源项目经许可合规（R-H）纳入码铃，版权归原作者所有："))
        for row in _THIRD_PARTY_ITEMS:
            o_layout.addWidget(QLabel(row))
        o_layout.addWidget(QLabel(
            "完整登记与许可全文：docs/THIRD_PARTY.md / docs/third_party_licenses/"
        ))
        layout.addWidget(open_card)

        # 致谢
        thanks_card = QFrame()
        thanks_card.setObjectName("aboutCard")
        thanks_card.setFrameShape(QFrame.Shape.StyledPanel)
        t_layout = QVBoxLayout(thanks_card)
        t_layout.setContentsMargins(20, 20, 20, 20)
        t_layout.setSpacing(12)

        t_layout.addWidget(QLabel("<b>致谢</b>"))
        t_layout.addWidget(QLabel("感谢 DeepSeek 提供的强大 AI 能力"))
        t_layout.addWidget(QLabel("感谢 Qt / PySide6 团队提供的优秀 GUI 框架"))
        layout.addWidget(thanks_card)

        layout.addStretch()

        # 返回按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        back_btn = QPushButton("返回首页")
        back_btn.clicked.connect(self._on_back)
        btn_row.addWidget(back_btn)
        layout.addLayout(btn_row)

    def _update_source_host(self) -> str:
        """当前频道主链域名（只读展示，R-O 诚实）。"""
        try:
            from gui.update_checker import resolve_channel_url, extract_host
            channel = getattr(getattr(self.app_ctx, "config", None),
                              "update_channel", "stable") or "stable"
            return extract_host(resolve_channel_url(channel)) or "—"
        except Exception:
            return "—"

    def _on_check_update(self) -> None:
        """手动检查更新入口：按钮置灰 + 三态结果（非阻断提示）。"""
        from gui.update_checker import (
            UpdateChecker, format_update_text, CHECK_UPDATE, CHECK_LATEST,
        )
        if not hasattr(self, "check_update_btn"):
            return
        self.check_update_btn.setEnabled(False)
        self.check_update_btn.setText("检查中…")
        self.update_state_label.setText("")
        channel = getattr(getattr(self.app_ctx, "config", None),
                          "update_channel", "stable") or "stable"

        def _finish(status: str) -> None:
            self.check_update_btn.setEnabled(True)
            self.check_update_btn.setText("检查更新")
            if status == CHECK_UPDATE:
                if not self.update_state_label.text():
                    self.update_state_label.setText("发现新版本")
            elif status == CHECK_LATEST:
                self.update_state_label.setText("已是最新")
            else:
                self.update_state_label.setText("检查失败，请稍后重试")

        try:
            checker = UpdateChecker(parent=self, channel=channel)
            checker.update_available.connect(
                lambda info: self.update_state_label.setText(format_update_text(info)))
            checker.check_finished.connect(_finish)
            self._about_update_checker = checker  # 持有引用防 GC
            checker.start(manual=True)
        except Exception:
            _finish("failed")

    def _on_back(self) -> None:
        pm = getattr(self.app_ctx, "page_manager", None)
        if pm is not None:
            pm.navigate("home")
