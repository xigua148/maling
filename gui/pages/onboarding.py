"""首次启动引导 —— 依赖检查、功能轮播、AI 配置、主题预览。"""
from __future__ import annotations

import sys
import subprocess
from pathlib import Path
from typing import Optional, List

from gui.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QStackedWidget, QProgressBar,
    QCheckBox, QFrame, QGridLayout, Qt, QFont, Signal,
    QMessageBox, QClipboard,
)

# v10.8: API 厂商预设（deepseek / moonshot / qwen / zhipu / openai / openrouter / ollama / custom）
from core import API_PROVIDER_PRESETS, DEFAULT_API_PROVIDER, normalize_provider


class DependencyCheckWidget(QWidget):
    """依赖检查步骤。"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        title = QLabel("环境检查")
        title.setObjectName("onboardingSectionTitle")
        font = QFont()
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        desc = QLabel("码铃正在检查运行环境，请稍候...")
        desc.setObjectName("onboardingDesc")
        layout.addWidget(desc)
        layout.addSpacing(20)

        self.check_items: List[tuple] = []
        self._add_check_row("Python 版本", self._check_python())
        self._add_check_row("PySide6 依赖", self._check_pyside6())
        self._add_check_row("API 配置", self._check_api_config())

        layout.addStretch()

    def _add_check_row(self, name: str, ok: bool) -> None:
        row = QHBoxLayout()
        label = QLabel(name)
        row.addWidget(label)
        row.addStretch()
        status = QLabel("通过" if ok else "未通过")
        status.setObjectName("checkPass" if ok else "checkFail")
        row.addWidget(status)
        self.layout().insertLayout(self.layout().count() - 1, row)
        self.check_items.append((name, ok))

    def _check_python(self) -> bool:
        try:
            v = sys.version_info
            return v.major >= 3 and v.minor >= 10  # v10.15: 统一 3.10+ 要求
        except Exception:
            return False

    def _check_pyside6(self) -> bool:
        try:
            import PySide6
            return True
        except Exception:
            return False

    def _check_api_config(self) -> bool:
        """v10.15: 嵌套解析 config.yaml，识别 api.key 而非 flat 字段。

        v2.5(D-V25-08): 路径锚定应用根（原裸相对路径随工作目录漂移，
        会导致「明明配好了却提示未配置」）。
        """
        from core.path_guard import resolve_config_path
        cfg_path = resolve_config_path()
        if not cfg_path.exists():
            return False
        try:
            import yaml
            data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            api = data.get("api") if isinstance(data, dict) else None
            if not isinstance(api, dict):
                return False
            key = (api.get("key") or "").strip()
            provider = (api.get("provider") or "openai").strip().lower()
            if provider == "ollama":
                return True  # 本地无需 key
            return bool(key)
        except Exception:
            return False

    def all_passed(self) -> bool:
        # v10.15: Python / PySide6 任一失败即视为未通过（环境层硬阻塞）；
        # API 配置允许后续在引导页补填，不阻塞步骤流转
        for name, ok in self.check_items:
            if name in ("Python 版本", "PySide6 依赖") and not ok:
                return False
        return True


class FeatureCarouselWidget(QWidget):
    """功能轮播步骤。"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        title = QLabel("核心功能")
        title.setObjectName("onboardingSectionTitle")
        font = QFont()
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        desc = QLabel("码铃为您准备了以下核心能力，快来体验吧~")
        desc.setObjectName("onboardingDesc")
        layout.addWidget(desc)
        layout.addSpacing(16)

        features = [
            ("\U0001F9E0", "代码审查", "智能分析代码质量，发现潜在问题并提供修复建议"),
            ("\U0001F4BB", "智能重构", "一键优化代码结构，提升可读性与可维护性"),
            ("\U0001F527", "API 调试", "内置 API 客户端，支持流式与非流式调用测试"),
            ("\U0001F4CB", "项目管理", "会话管理、代码片段、待办事项一站式掌控"),
        ]

        grid = QGridLayout()
        grid.setSpacing(12)
        for i, (icon, feat_title, feat_desc) in enumerate(features):
            card = QFrame()
            card.setObjectName("featureCard")
            card.setFrameShape(QFrame.Shape.StyledPanel)
            c_layout = QVBoxLayout(card)
            c_layout.setContentsMargins(16, 16, 16, 16)
            c_layout.setSpacing(8)

            icon_label = QLabel(icon)
            icon_label.setObjectName("featureCardIcon")
            icon_font = QFont()
            icon_label.setFont(icon_font)
            c_layout.addWidget(icon_label)

            t = QLabel(feat_title)
            t_font = QFont()
            t_font.setBold(True)
            t.setFont(t_font)
            c_layout.addWidget(t)

            d = QLabel(feat_desc)
            d.setWordWrap(True)
            d.setObjectName("featureDesc")
            c_layout.addWidget(d)

            row, col = divmod(i, 2)
            grid.addWidget(card, row, col)

        layout.addLayout(grid)
        layout.addStretch()


class AIConfigWidget(QWidget):
    """AI 配置步骤。"""

    config_ready = Signal(dict)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        title = QLabel("AI 配置")
        title.setObjectName("onboardingSectionTitle")
        font = QFont()
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        desc = QLabel("配置您的 AI 服务，码铃才能为您效力哦~")
        desc.setObjectName("onboardingDesc")
        layout.addWidget(desc)
        layout.addSpacing(16)

        # API 厂商预设（v10.8）：选定后自动带出 url 与默认模型
        provider_row = QHBoxLayout()
        provider_row.addWidget(QLabel("厂商:"))
        self.provider_combo = QComboBox()
        self._provider_keys = list(API_PROVIDER_PRESETS.keys())
        for pkey in self._provider_keys:
            self.provider_combo.addItem(API_PROVIDER_PRESETS[pkey]["label"], pkey)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        provider_row.addWidget(self.provider_combo)
        provider_row.addStretch()
        layout.addLayout(provider_row)

        # API Key
        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("API Key:"))
        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("输入所选厂商的 API Key（Ollama 本地可不填）...")
        self.key_edit.setEchoMode(QLineEdit.Password)
        key_row.addWidget(self.key_edit, 1)
        layout.addLayout(key_row)

        # 明文/密文切换
        self.show_key_check = QCheckBox("显示 API Key")
        self.show_key_check.stateChanged.connect(self._toggle_key_visibility)
        layout.addWidget(self.show_key_check)

        # Base URL
        url_row = QHBoxLayout()
        url_row.addWidget(QLabel("Base URL:"))
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("选择厂商后自动填充，也可手动修改")
        url_row.addWidget(self.url_edit, 1)
        layout.addLayout(url_row)

        # 模型选择（可编辑，选预设时自动带出默认模型，也可手动输入任意模型名）
        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("模型:"))
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        model_row.addWidget(self.model_combo, 1)
        model_row.addStretch()
        layout.addLayout(model_row)

        # 初始化为默认厂商（deepseek）的预设值
        self._on_provider_changed(self.provider_combo.currentIndex())

        # 提示
        tip = QLabel("提示: 您也可以稍后前往「设置」页面修改这些配置")
        tip.setObjectName("configTip")
        layout.addWidget(tip)
        layout.addStretch()

    def _on_provider_changed(self, index: int) -> None:
        """切换厂商预设：自动填充 url 与默认模型列表。"""
        if index < 0 or index >= len(self._provider_keys):
            return
        pkey = self._provider_keys[index]
        preset = API_PROVIDER_PRESETS.get(pkey, API_PROVIDER_PRESETS[DEFAULT_API_PROVIDER])
        self.url_edit.setText(preset["url"])
        self.model_combo.clear()
        if preset["models"]:
            self.model_combo.addItems(preset["models"])
            self.model_combo.setCurrentText(preset["default_model"])

    def _toggle_key_visibility(self, state: int) -> None:
        if state == Qt.Checked:
            self.key_edit.setEchoMode(QLineEdit.Normal)
        else:
            self.key_edit.setEchoMode(QLineEdit.Password)

    def get_config(self) -> dict:
        pkey = self.provider_combo.currentData() or DEFAULT_API_PROVIDER
        return {
            "api_provider": pkey,
            "api_key": self.key_edit.text().strip(),
            "api_url": self.url_edit.text().strip(),
            "api_model": self.model_combo.currentText().strip(),
        }


class ThemePreviewWidget(QWidget):
    """主题预览步骤。"""

    theme_selected = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(14)

        title = QLabel("主题预览")
        title.setObjectName("onboardingSectionTitle")
        font = QFont()
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        desc = QLabel("选择您喜欢的界面风格~")
        desc.setObjectName("onboardingDesc")
        layout.addWidget(desc)
        layout.addSpacing(6)

        # v1.9 A(D-V19-13③)：onboarding 四风格（与设置页 / 顶栏共用 theme id 常量）
        try:
            from gui.theme_engine import ThemeEngine
            themes = [(tid, ThemeEngine.THEME_DEFINITIONS[tid]["name"])
                      for tid in ThemeEngine.THEME_IDS]
        except Exception:
            themes = [("ui_minimal", "现代极简")]
        _descs = {
            "ui_minimal": "冷调极简，克制描边，专注高效",
            "ui_cream": "暖色奶油，柔和圆角，温馨亲切",
            "ui_night": "深色夜间，深色专属，护眼沉浸",
            "ui_whale": "深海清爽，浅海渐变，鲸鱼娘专属",
        }
        for tid, name in themes:
            card = QFrame()
            card.setObjectName("themePreviewCard")
            card.setFrameShape(QFrame.Shape.StyledPanel)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(20, 14, 20, 14)
            t = QLabel(name)
            t.setObjectName("themePreviewName")
            tf = QFont()
            tf.setBold(True)
            t.setFont(tf)
            cl.addWidget(t)
            d = QLabel(_descs.get(tid, name))
            d.setWordWrap(True)
            cl.addWidget(d)
            b = QPushButton("选择此风格")
            b.clicked.connect(lambda _checked=False, x=tid: self._select_theme(x))
            cl.addWidget(b)
            layout.addWidget(card)

        layout.addStretch()

    def _select_theme(self, theme_name: str) -> None:
        self.theme_selected.emit(theme_name)
        try:
            from gui.theme_engine import ThemeEngine
            label = ThemeEngine.THEME_DEFINITIONS.get(theme_name, {}).get("name", theme_name)
        except Exception:
            label = theme_name
        QMessageBox.information(self, "风格已选择", f"已选择「{label}」，点击「完成」即可应用~")


class OnboardingDialog(QWidget):
    """首次启动引导对话框（以 QWidget 形式嵌入页面栈）。"""

    finished = Signal()

    STEP_TITLES = ["环境检查", "功能介绍", "AI 配置", "主题选择"]

    def __init__(self, app_context, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app_ctx = app_context
        self._current_step = 0
        # v1.9 A(D-V19-12)：默认风格 = 现代极简（ui_minimal）
        self._selected_theme = "ui_minimal"
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶部进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(len(self.STEP_TITLES))
        self.progress_bar.setValue(1)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v / %m  %p%")
        layout.addWidget(self.progress_bar)

        # 步骤标题
        self.step_title = QLabel(self.STEP_TITLES[0])
        self.step_title.setObjectName("onboardingStepTitle")
        step_font = QFont()
        step_font.setBold(True)
        self.step_title.setFont(step_font)
        self.step_title.setContentsMargins(20, 12, 20, 0)
        layout.addWidget(self.step_title)

        # 步骤内容栈
        self.stack = QStackedWidget()
        self.dep_check = DependencyCheckWidget()
        self.feature_carousel = FeatureCarouselWidget()
        self.ai_config = AIConfigWidget()
        self.theme_preview = ThemePreviewWidget()

        self.stack.addWidget(self.dep_check)
        self.stack.addWidget(self.feature_carousel)
        self.stack.addWidget(self.ai_config)
        self.stack.addWidget(self.theme_preview)
        # v2.1(UI bugfix): theme_preview.theme_selected 必须接住 —— 此前全文件无任何
        #   connect()，用户点「选择此风格」后信号发出去没人收，「完成」时应用的仍是
        #   _selected_theme 的默认值 ui_minimal。这是「选了不生效」bug 的根因。
        self.theme_preview.theme_selected.connect(self._on_theme_selected)

        layout.addWidget(self.stack, 1)

        # 底部导航按钮
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(20, 12, 20, 20)
        btn_layout.setSpacing(12)

        self.prev_btn = QPushButton("上一步")
        self.prev_btn.clicked.connect(self._on_prev)
        self.prev_btn.setEnabled(False)
        btn_layout.addWidget(self.prev_btn)
        btn_layout.addStretch()

        self.next_btn = QPushButton("下一步")
        self.next_btn.setObjectName("primaryBtn")
        self.next_btn.clicked.connect(self._on_next)
        btn_layout.addWidget(self.next_btn)

        layout.addLayout(btn_layout)

    def _on_next(self) -> None:
        # v10.15: Python / PySide6 任一未通过时硬阻塞第 0 步，
        # 提示用户必须先解决环境再继续
        if self._current_step == 0 and not self.dep_check.all_passed():
            failed = [n for n, ok in self.dep_check.check_items if not ok and n in ("Python 版本", "PySide6 依赖")]
            if failed:
                QMessageBox.warning(
                    self,
                    "环境检查未通过",
                    f"以下项目未通过，必须解决后才能继续：\n\n• " + "\n• ".join(failed) +
                    "\n\n请安装 Python 3.10+ 与 PySide6 后重启应用。",
                )
                return

        if self._current_step < len(self.STEP_TITLES) - 1:
            self._current_step += 1
            self._update_step()
        else:
            self._finish()

    def _on_prev(self) -> None:
        if self._current_step > 0:
            self._current_step -= 1
            self._update_step()

    def _on_theme_selected(self, theme_name: str) -> None:
        # v2.1(UI bugfix): 收 theme_preview.theme_selected，记录到 _selected_theme，
        #   完成时（onboarding.py:490-507）会据此调用 theme_engine.load_theme 并写 config。
        self._selected_theme = theme_name

    def _update_step(self) -> None:
        self.stack.setCurrentIndex(self._current_step)
        self.step_title.setText(self.STEP_TITLES[self._current_step])
        self.progress_bar.setValue(self._current_step + 1)
        self.prev_btn.setEnabled(self._current_step > 0)

        if self._current_step == len(self.STEP_TITLES) - 1:
            self.next_btn.setText("完成")
        else:
            self.next_btn.setText("下一步")

    def _finish(self) -> None:
        # 保存 AI 配置
        ai_cfg = self.ai_config.get_config()
        cfg = getattr(self.app_ctx, "cfg", None)
        # v10.8: 有 key 或选了厂商（如本地 Ollama 无 key）都持久化；
        # 统一走 AppConfig.save()，默认回写加载时的 config.yaml 路径
        if cfg is not None and (ai_cfg.get("api_key") or ai_cfg.get("api_provider")):
            cfg.api_provider = normalize_provider(
                ai_cfg.get("api_provider", getattr(cfg, "api_provider", DEFAULT_API_PROVIDER)))
            if ai_cfg.get("api_key"):
                cfg.api_key = ai_cfg["api_key"]
            cfg.api_url = ai_cfg.get("api_url", cfg.api_url)
            cfg.api_model = ai_cfg.get("api_model", cfg.api_model)
            try:
                cfg.save()
            except Exception:
                pass

            # v10.15: 保存 key 后重建 API 客户端，否则旧的 (无 key) 实例仍会被复用
            try:
                from api import APIClient
                self.app_ctx.api = APIClient(cfg, getattr(self.app_ctx, "logger", None))
                session = getattr(self.app_ctx, "session", None)
                if session is not None and hasattr(session, "api"):
                    try:
                        session.api = self.app_ctx.api
                    except Exception:
                        pass
                collab = getattr(self.app_ctx, "collaborator", None)
                if collab is not None and hasattr(collab, "api"):
                    try:
                        collab.api = self.app_ctx.api
                    except Exception:
                        pass
            except Exception as exc:
                logger = getattr(self.app_ctx, "logger", None)
                if logger is not None:
                    logger.warning("引导完成后重建 API 客户端失败: %s", exc)

        # 应用风格（v1.9 A：归一四风格 id + C 深色夜间进出收口）
        try:
            from gui.theme_engine import ThemeEngine, apply_night_lock
            _theme_id = ThemeEngine.normalize_theme_id(self._selected_theme)
        except Exception:
            ThemeEngine = None
            apply_night_lock = None
            _theme_id = self._selected_theme
        theme_engine = getattr(self.app_ctx, "theme_engine", None)
        config = getattr(self.app_ctx, "config", None)
        if apply_night_lock is not None:
            apply_night_lock(theme_engine, config, _theme_id)
        if theme_engine is not None:
            theme_engine.load_theme(_theme_id)
        if config is not None:
            config.theme_name = _theme_id
            config.first_run = False
            config.save()

        self.finished.emit()
