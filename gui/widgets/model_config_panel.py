"""ModelConfigPanel —— B9「模型与接口」可复用配置面板（v1.2 / design D8）。

结构：
  ① 状态头卡（#modelStatusCard）：当前生效 厂商 / 模型 / Key 末 4 位（脱敏）+ 连接态色点；
     缺 Key 时高亮引导（#modelMissingKeyHint）。
  ② 厂商卡片点选区：读 core.API_PROVIDER_PRESETS（含 desc/is_local 展示元字段）平铺点选，
     替代纯下拉（B9④）；点选即自动带出 url 与推荐模型列表。
  ③ 编辑区（#modelEditArea）：API Key(Password) / Base URL / 模型(editable combo) + 保存。

保存链路与 page_settings 协调（design D8 / 团队约束）：
  - 面板内「保存模型配置」= 唯一权威保存动作：写 cfg → cfg.save() → 重建 APIClient
    → MainWindow.refresh_api_status()（与旧 _on_save_api 同一链路，逻辑抽到本组件）；
  - PageSettings._on_save_all 若面板有未保存编辑（is_dirty()）会调 commit() 合并保存，
    不重复保存、不破坏 API Key 已保存流程。

取色：一律 theme_color()；禁止裸色值。
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

from gui.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QFrame, Qt, QFont, Signal, QEvent,
)
from gui.utils import theme_color
from core import (
    API_PROVIDER_PRESETS, DEFAULT_API_PROVIDER, normalize_provider,
    api_status_summary,
)


def save_api_config(app_ctx, provider: str, key: str, url: str, model: str) -> bool:
    """权威保存链路（从旧 page_settings._on_save_api 抽出，逻辑等价）。

    返回是否保存成功；失败原因由调用方弹窗提示。
    """
    cfg = getattr(app_ctx, "cfg", None)
    if cfg is None:
        return False
    provider = normalize_provider(provider)
    cfg.api_provider = provider
    cfg.api_key = (key or "").strip()
    cfg.api_url = (url or "").strip()
    cfg.api_model = (model or "").strip()
    try:
        cfg.save()
    except Exception:
        return False
    # 尝试同步到环境变量（旧链路行为保留）
    if cfg.api_key:
        try:
            os.environ["DEEPSEEK_API_KEY"] = cfg.api_key
        except Exception:
            pass
    # 重新初始化 APIClient
    try:
        from api import APIClient
        app_ctx.api = APIClient(cfg, getattr(app_ctx, "logger", None))
    except Exception:
        # Key 已保存；重建失败留给调用方决定是否提示（不回滚用户数据）
        pass
    return True


class ModelConfigPanel(QWidget):
    """「模型与接口」可复用配置组件。"""

    saved = Signal()          # 保存成功（供设置页联动刷新/提示）
    provider_changed = Signal(str)  # 厂商卡片点选（参数：provider key）

    def __init__(self, app_context, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app_ctx = app_context
        self._provider_keys: List[str] = list(API_PROVIDER_PRESETS.keys())
        self._provider_cards: Dict[str, QPushButton] = {}
        self._selected_provider: str = normalize_provider(
            getattr(getattr(self.app_ctx, "cfg", None), "api_provider", DEFAULT_API_PROVIDER)
        )
        self._dirty = False
        self.setObjectName("modelConfigPanel")
        self._init_ui()
        self._load_current()

    # ==================================================================
    # 取色 / 状态辅助
    # ==================================================================
    def _tc(self, key: str, fallback: str) -> str:
        return theme_color(self.app_ctx, key, fallback)

    def _cfg(self):
        return getattr(self.app_ctx, "cfg", None)

    def _preset_of(self, pkey: str) -> dict:
        pkey = normalize_provider(pkey)
        return API_PROVIDER_PRESETS.get(pkey, API_PROVIDER_PRESETS[DEFAULT_API_PROVIDER])

    # ==================================================================
    # 布局构建
    # ==================================================================
    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # ---- 分区说明 ----
        desc = QLabel(
            "此处为码铃连接的「大脑」：先选厂商，再填 Key 与模型。"
            "本地 Ollama 无需 API Key。保存后即时生效。"
        )
        desc.setObjectName("modelSectionDesc")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # ---- ① 状态头卡 ----
        layout.addWidget(self._build_status_card())

        # ---- ② 厂商卡片 ----
        picker_title = QLabel("选择厂商（点选卡片）")
        pf = QFont()
        pf.setPointSize(12)
        pf.setBold(True)
        picker_title.setFont(pf)
        layout.addWidget(picker_title)
        grid = QGridLayout()
        grid.setSpacing(8)
        for idx, pkey in enumerate(self._provider_keys):
            card = self._build_provider_card(pkey)
            self._provider_cards[pkey] = card
            card.clicked.connect(lambda _=False, k=pkey: self._on_provider_card(k))
            grid.addWidget(card, idx // 4, idx % 4)
        for col in range(4):
            grid.setColumnStretch(col, 1)
        layout.addLayout(grid)

        # ---- ③ 编辑区 ----
        edit_area = QWidget()
        edit_area.setObjectName("modelEditArea")
        edit_layout = QVBoxLayout(edit_area)
        edit_layout.setContentsMargins(0, 4, 0, 0)
        edit_layout.setSpacing(8)

        key_row = QHBoxLayout()
        key_label = QLabel("API Key")
        key_label.setObjectName("modelFieldLabel")
        key_label.setMinimumWidth(72)
        key_row.addWidget(key_label)
        self.key_edit = QLineEdit()
        self.key_edit.setObjectName("modelKeyEdit")
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("输入所选厂商的 API Key（Ollama 本地可不填）")
        self.key_edit.textChanged.connect(self._mark_dirty)
        key_row.addWidget(self.key_edit, 1)
        self.show_key_btn = QPushButton("显示")
        self.show_key_btn.setObjectName("modelShowKeyBtn")
        self.show_key_btn.setCursor(Qt.PointingHandCursor)
        self.show_key_btn.clicked.connect(self._on_toggle_key_visibility)
        key_row.addWidget(self.show_key_btn)
        edit_layout.addLayout(key_row)

        url_row = QHBoxLayout()
        url_label = QLabel("Base URL")
        url_label.setObjectName("modelFieldLabel")
        url_label.setMinimumWidth(72)
        url_row.addWidget(url_label)
        self.url_edit = QLineEdit()
        self.url_edit.setObjectName("modelUrlEdit")
        self.url_edit.setPlaceholderText("选择厂商后自动填充，也可手动修改")
        self.url_edit.textChanged.connect(self._mark_dirty)
        url_row.addWidget(self.url_edit, 1)
        edit_layout.addLayout(url_row)

        model_row = QHBoxLayout()
        model_label = QLabel("模型")
        model_label.setObjectName("modelFieldLabel")
        model_label.setMinimumWidth(72)
        model_row.addWidget(model_label)
        self.model_combo = QComboBox()
        self.model_combo.setObjectName("modelModelCombo")
        self.model_combo.setEditable(True)
        self.model_combo.currentTextChanged.connect(self._mark_dirty)
        model_row.addWidget(self.model_combo, 1)
        edit_layout.addLayout(model_row)

        # ① 模型下拉右側「下三角」指示：自定义 QSS 把 ::drop-down 子控件覆盖后
        #   ::down-arrow 无 image 定义 → 箭头消失。这里在 combo 右侧叠加一个透明
        #   穿透的「▾」标签（颜色随主题，见 base.qss 的 QLabel#modelComboArrow），
        #   鼠标点击透传给 combo 自身以展开下拉，不破坏既有交互与其余 QSS。
        self.model_arrow = QLabel("▾", self.model_combo)
        self.model_arrow.setObjectName("modelComboArrow")
        self.model_arrow.setCursor(Qt.PointingHandCursor)
        self.model_arrow.setAlignment(Qt.AlignCenter)
        # 透明穿透：落在 drop-down 区域的点击交还给 combo（展开下拉），标签只作指示。
        self.model_arrow.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.model_combo.installEventFilter(self)
        self._position_model_arrow()

        # 本地厂商说明（ollama 等）
        self.local_hint = QLabel("")
        self.local_hint.setObjectName("modelLocalHint")
        self.local_hint.setWordWrap(True)
        edit_layout.addWidget(self.local_hint)

        # 视觉模型提示（下拉里带 👁 tooltip 的模型支持看图）
        self.vision_hint = QLabel("👁 下拉中带「支持看图」提示的模型支持图片理解（视觉/多模态），可用于 AI 看图 / 拍照 / 截图提问。")
        self.vision_hint.setObjectName("modelVisionHint")
        self.vision_hint.setWordWrap(True)
        edit_layout.addWidget(self.vision_hint)

        # 保存行
        save_row = QHBoxLayout()
        self.save_btn = QPushButton("保存模型配置")
        self.save_btn.setObjectName("modelSaveBtn")
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.clicked.connect(self._on_save_clicked)
        save_row.addWidget(self.save_btn)
        save_row.addStretch()
        self.feedback_label = QLabel("")
        self.feedback_label.setObjectName("modelSectionDesc")
        save_row.addWidget(self.feedback_label)
        edit_layout.addLayout(save_row)

        layout.addWidget(edit_area)
        layout.addStretch()

    # ==================================================================
    # ① 下拉框右侧下三角指示（叠加标签定位）
    # ==================================================================
    def _position_model_arrow(self) -> None:
        """把下三角标签贴到 combo 右侧的 drop-down 区域（约 22px 宽），不挡编辑区。"""
        if not hasattr(self, "model_arrow") or self.model_arrow is None:
            return
        aw = 22
        self.model_arrow.setGeometry(
            self.model_combo.width() - aw - 2, 0, aw, self.model_combo.height()
        )

    def eventFilter(self, obj, event) -> bool:
        # combo 尺寸变化时同步移动下三角，避免错位。
        if obj is self.model_combo and event.type() == QEvent.Type.Resize:
            self._position_model_arrow()
        return super().eventFilter(obj, event)

    def _build_status_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("modelStatusCard")
        card.setFrameShape(QFrame.Shape.StyledPanel)
        v = QVBoxLayout(card)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(6)

        # 顶行：状态点 + 厂商 + 连接态文字
        top = QHBoxLayout()
        top.setSpacing(8)
        self.status_dot = QLabel("")
        self.status_dot.setObjectName("modelStatusDot")
        self.status_dot.setFixedSize(10, 10)
        top.addWidget(self.status_dot)
        self.status_provider = QLabel("")
        self.status_provider.setObjectName("modelStatusProvider")
        top.addWidget(self.status_provider)
        top.addStretch()
        self.status_state = QLabel("")
        self.status_state.setObjectName("modelStatusStateText")
        top.addWidget(self.status_state)
        v.addLayout(top)

        # 底行：模型 + Key 末四位 chip
        meta = QHBoxLayout()
        meta.setSpacing(10)
        self.status_meta = QLabel("")
        self.status_meta.setObjectName("modelStatusMeta")
        meta.addWidget(self.status_meta)
        self.status_key_chip = QLabel("")
        self.status_key_chip.setObjectName("modelStatusKeyChip")
        meta.addWidget(self.status_key_chip)
        meta.addStretch()
        v.addLayout(meta)

        # 缺 Key 引导（默认隐藏）
        self.missing_key_hint = QLabel("")
        self.missing_key_hint.setObjectName("modelMissingKeyHint")
        self.missing_key_hint.setWordWrap(True)
        self.missing_key_hint.hide()
        v.addWidget(self.missing_key_hint)
        return card

    def _build_provider_card(self, pkey: str) -> QPushButton:
        preset = self._preset_of(pkey)
        btn = QPushButton()
        btn.setObjectName("providerCard")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setMinimumHeight(88)
        # 卡片内容：标题(+本地标签) / 说明 / 推荐模型
        inner = QVBoxLayout(btn)
        inner.setContentsMargins(10, 8, 10, 8)
        inner.setSpacing(3)

        head = QHBoxLayout()
        head.setSpacing(6)
        title = QLabel(str(preset.get("label", pkey)))
        title.setObjectName("providerCardTitle")
        title.setWordWrap(True)
        head.addWidget(title, 1)
        if preset.get("is_local"):
            tag = QLabel("本地")
            tag.setObjectName("providerCardTagLocal")
            head.addWidget(tag, 0, Qt.AlignTop)
        inner.addLayout(head)

        d = QLabel(str(preset.get("desc", "")))
        d.setObjectName("providerCardDesc")
        d.setWordWrap(True)
        inner.addWidget(d)

        rec_model = (preset.get("models") or [preset.get("default_model", "")] or [""])[0]
        m = QLabel(f"推荐 · {rec_model}" if rec_model else "手动填写模型")
        m.setObjectName("providerCardModel")
        m.setWordWrap(True)
        inner.addWidget(m)
        return btn

    # ==================================================================
    # 状态刷新 / 数据加载
    # ==================================================================
    def _load_current(self) -> None:
        """按 cfg 当前值初始化：选中厂商卡片并带出 url/模型/Key。

        程序化回填期间 blockSignals，结束后清 dirty，避免“打开即脏”。
        """
        cfg = self._cfg()
        provider = normalize_provider(getattr(cfg, "api_provider", DEFAULT_API_PROVIDER))
        self._selected_provider = provider
        self._apply_provider_preset(provider, load_saved=True)
        self._refresh_card_states()
        self._dirty = False
        self.refresh_status()

    def reload_current(self) -> bool:
        """从 cfg 重载编辑区与选中态（无未保存编辑时执行，避免覆盖用户输入）。

        供 PageSettings.on_enter（页面进入钩子）调用；返回是否真正重载。
        """
        if self._dirty:
            self.refresh_status()
            return False
        self._load_current()
        return True

    def _apply_provider_preset(self, pkey: str, *, load_saved: bool) -> None:
        """点选/加载厂商：带出 url 与模型列表（load_saved=True 时以 cfg 已存值为准）。

        程序化回填 blockSignals，不触发 dirty；交互点选产生的 dirty 由调用方设置。
        """
        preset = self._preset_of(pkey)
        cfg = self._cfg()

        url_edit, key_edit = self.url_edit, self.key_edit
        url_edit.blockSignals(True)
        key_edit.blockSignals(True)
        try:
            if load_saved and cfg is not None and normalize_provider(
                    getattr(cfg, "api_provider", DEFAULT_API_PROVIDER)) == pkey:
                # 当前生效即该厂商：直接读已保存值（不覆盖 Key）
                url = str(getattr(cfg, "api_url", "") or preset.get("url", "") or "")
                saved_model = str(getattr(cfg, "api_model", "") or "").strip()
                url_edit.setText(url)
                self._fill_model_combo(preset, saved_model or preset.get("default_model", ""))
                key_edit.setText(str(getattr(cfg, "api_key", "") or "").strip())
            else:
                url_edit.setText(str(preset.get("url", "") or ""))
                self._fill_model_combo(preset, str(preset.get("default_model", "") or ""))
                # 切换厂商不清空已输入的 Key，避免误删（单 Key 字段语义沿用）
        finally:
            url_edit.blockSignals(False)
            key_edit.blockSignals(False)

        # 本地厂商提示
        if preset.get("is_local"):
            self.local_hint.setText("本地模型无需 API Key，保存后将直连本机服务。")
            self.local_hint.show()
        else:
            self.local_hint.setText("")
            self.local_hint.hide()

    def _fill_model_combo(self, preset: dict, current: str) -> None:
        """填充模型下拉：显示纯模型 ID；视觉模型额外挂 tooltip 提示支持看图。

        v1.4.1: 仅用 setItemData 挂 ToolTipRole 提示，不改动显示文本——保存值
        必须是厂商原始模型 ID，不能被前缀/后缀污染。
        """
        self.model_combo.blockSignals(True)
        try:
            self.model_combo.clear()
            models = [str(x) for x in (preset.get("models") or []) if str(x).strip()]
            vision = {str(x) for x in (preset.get("vision_models") or [])}
            if models:
                self.model_combo.addItems(models)
                for idx, mid in enumerate(models):
                    if mid in vision:
                        self.model_combo.setItemData(
                            idx, "👁 支持看图（视觉/多模态）", Qt.ToolTipRole
                        )
            self.model_combo.setCurrentText(str(current or ""))
        finally:
            self.model_combo.blockSignals(False)

    def _refresh_card_states(self) -> None:
        for pkey, card in self._provider_cards.items():
            selected = pkey == self._selected_provider
            card.setObjectName("providerCardSelected" if selected else "providerCard")
            card.style().unpolish(card)
            card.style().polish(card)
            card.update()

    def refresh_status(self) -> None:
        """刷新状态头：厂商/模型/Key 脱敏 + 连接态 + 缺 Key 引导。"""
        cfg = self._cfg()
        summary = api_status_summary(cfg)
        self.status_provider.setText(summary["provider_label"])
        if summary["model"]:
            self.status_meta.setText(
                f"模型：{summary['model']}    {summary['url'] or ''}"
            )
        else:
            self.status_meta.setText(summary["url"] or "尚未选择模型")
        self.status_key_chip.setText(f"Key · {summary['masked_key']}")
        self.status_state.setText(summary["state_text"])

        # 状态点颜色（theme_color 取色，禁裸值）
        color_key = "state_ok" if summary["ok"] else "state_warn"
        dot_color = self._tc(color_key, "#E0A02E" if not summary["ok"] else "#3FBF7F")
        self.status_dot.setStyleSheet(
            f"QLabel#modelStatusDot {{ background-color: {dot_color}; border-radius: 5px; }}"
        )
        # 缺 Key → 高亮引导
        if not summary["configured"] and not summary["is_local"]:
            self.missing_key_hint.setText(summary["hint"] or "请先配置 API Key")
            self.missing_key_hint.show()
        else:
            self.missing_key_hint.setText("")
            self.missing_key_hint.hide()
        if self.feedback_label is not None:
            self.feedback_label.setText("")

    # ==================================================================
    # 交互
    # ==================================================================
    def _on_provider_card(self, pkey: str) -> None:
        self._selected_provider = normalize_provider(pkey)
        self._apply_provider_preset(pkey, load_saved=False)
        self._refresh_card_states()
        self.provider_changed.emit(self._selected_provider)
        self._mark_dirty(True)

    def _on_toggle_key_visibility(self) -> None:
        show = self.key_edit.echoMode() == QLineEdit.Password
        self.key_edit.setEchoMode(QLineEdit.Normal if show else QLineEdit.Password)
        self.show_key_btn.setText("隐藏" if show else "显示")

    def _mark_dirty(self, *_args) -> None:
        self._dirty = True

    # ==================================================================
    # 保存
    # ==================================================================
    def is_dirty(self) -> bool:
        return self._dirty

    def _collect_values(self) -> Dict[str, str]:
        provider = self._selected_provider or normalize_provider(
            getattr(self._cfg(), "api_provider", DEFAULT_API_PROVIDER))
        return {
            "provider": provider,
            "key": self.key_edit.text().strip(),
            "url": self.url_edit.text().strip(),
            "model": self.model_combo.currentText().strip(),
        }

    def validate(self) -> Optional[str]:
        """校验失败返回错误文案；成功返回 None。"""
        v = self._collect_values()
        preset = self._preset_of(v["provider"])
        if not preset.get("is_local") and not v["key"]:
            return "请输入 API Key（本地 Ollama 可留空）"
        if not v["url"]:
            return "请填写 Base URL（可先选择厂商预设自动带出）"
        if not v["model"]:
            return "请填写模型名称（可手动输入任意模型名）"
        return None

    def _on_save_clicked(self) -> None:
        err = self.validate()
        if err:
            from gui.qt_compat import QMessageBox
            QMessageBox.warning(self, "提示", err)
            return
        v = self._collect_values()
        ok = save_api_config(self.app_ctx, v["provider"], v["key"], v["url"], v["model"])
        if not ok:
            from gui.qt_compat import QMessageBox
            QMessageBox.warning(self, "保存失败", "配置写入失败，请检查 config.yaml 是否可写")
            return
        # 重建 APIClient 的异常已在 save_api_config 内吞掉；此处提示成功
        self._dirty = False
        self.refresh_status()
        main_window = self.window()
        if main_window is not None and hasattr(main_window, "refresh_api_status"):
            try:
                main_window.refresh_api_status()
            except Exception:
                pass
        self.saved.emit()
        from gui.qt_compat import QMessageBox
        QMessageBox.information(self, "成功", "模型配置已保存")

    def commit(self, *, interactive: bool = True) -> bool:
        """供 PageSettings._on_save_all 合并保存：有未保存编辑时落盘。

        interactive=False 时校验不过则静默跳过（避免阻断“保存所有设置”）。
        """
        if not self.is_dirty():
            return True
        err = self.validate()
        if err:
            if interactive:
                from gui.qt_compat import QMessageBox
                QMessageBox.warning(self, "提示", err)
            return False
        v = self._collect_values()
        ok = save_api_config(self.app_ctx, v["provider"], v["key"], v["url"], v["model"])
        if ok:
            self._dirty = False
            self.refresh_status()
            self.saved.emit()
        return ok

    def clear_dirty(self) -> None:
        """强制清除未保存标记（外部已另行持久化时用）。"""
        self._dirty = False
