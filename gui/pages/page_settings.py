"""设置页面 —— 主题切换、模型与接口（B9）、窗口设置。v10.15: 整个页面用 QScrollArea 包起来，避免模块被半遮挡。"""
from __future__ import annotations

from typing import Optional

from gui.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QSlider, QCheckBox, QLineEdit, QFrame,
    QScrollArea, QPoint, QToolButton, QColor,
    Qt, QFont, QMessageBox,
)

# v1.2(B9): 「模型与接口」专区由独立可复用组件 ModelConfigPanel 承载（原 API 配置分节替换）
from gui.widgets.model_config_panel import ModelConfigPanel
# v10.8: API 厂商预设
from core import __version__ as CORE_VERSION
# v1.4.3「主题强调色色盘」：取色对话框（PySide6 标准组件，无新依赖）
try:
    from PySide6.QtWidgets import QColorDialog as _QColorDialog
    _HAS_COLOR_DIALOG = True
except Exception:
    _QColorDialog = None
    _HAS_COLOR_DIALOG = False
# v1.4.3：复用主题引擎的 hex 校验（避免页面代码裸值 / 重复实现）
from gui.theme_engine import _is_valid_accent_hex  # noqa: F401
# v1.9 A(D-V19-11/D-V19-13)：四风格切换 + C 深色夜间进出收口
from gui.theme_engine import ThemeEngine, apply_night_lock
# v1.1(B3): 说明小字取主题次级文字色，避免硬编码
from gui.utils import theme_color

# v1.3(P1-3): 全局热键改键用 QKeySequenceEdit（按下捕获）；极旧 PySide6 缺失则降级只读
try:
    from PySide6.QtWidgets import QKeySequenceEdit as _QKeySequenceEdit
    _HAS_KEYSEQ_EDIT = True
except Exception:
    _QKeySequenceEdit = None
    _HAS_KEYSEQ_EDIT = False

# v1.3(P2-6): 纪念日录入用 QDateEdit（周年语义，仅存 MM-DD）；极端环境缺失则隐藏录入区
try:
    from PySide6.QtWidgets import QDateEdit as _QDateEdit
    from PySide6.QtCore import QDate as _QDate
    _HAS_QDATE = True
except Exception:
    _QDateEdit = None
    _QDate = None
    _HAS_QDATE = False

# v1.8(V18-13/D-V18-07): 工作场景主动降档上限用 QSpinBox；极端环境缺失则隐藏调整控件
try:
    from PySide6.QtWidgets import QSpinBox as _QSpinBox
    _HAS_SPINBOX = True
except Exception:
    _QSpinBox = None
    _HAS_SPINBOX = False


class PageSettings(QWidget):
    """设置页面。"""

    def __init__(self, app_context, title: str = "设置", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app_ctx = app_context
        self.title = title
        self._init_ui()
        self._load_settings()
        # v1.3(P1-1): TTS 可用性探测完成 -> 刷新语音区降级提示（degraded 时显示说明）
        tts = getattr(app_context, "tts", None)
        if tts is not None and hasattr(tts, "availability_changed"):
            try:
                tts.availability_changed.connect(lambda _ok: self._refresh_tts_hint())
            except Exception:
                pass
        self._refresh_tts_hint()

    def _init_ui(self) -> None:
        # v10.15: 整个设置页用 QScrollArea 包起来，保证所有设置模块完整可见，
        # 解决「外观主题」与「个性」之间模块被半遮挡的体验问题
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setObjectName("settingsScroll")
        self._scroll = scroll  # v1.2(B9): 供 scroll_to_model() 直达滚动定位

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)
        scroll.setWidget(content)
        self._content = content

        # 页面标题
        title_label = QLabel("设置")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        # 主题设置
        theme_frame = self._create_section("外观主题")
        theme_layout = theme_frame.layout()

        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("界面风格:"))
        self.theme_combo = QComboBox()
        # v1.9 A(D-V19-13)：四风格（唯一真值源 ThemeEngine.THEME_IDS；旧值不暴露）
        for _tid in ThemeEngine.THEME_IDS:
            self.theme_combo.addItem(
                ThemeEngine.THEME_DEFINITIONS[_tid]["name"], _tid)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        theme_row.addWidget(self.theme_combo)
        theme_row.addStretch()
        theme_layout.addLayout(theme_row)

        # 快速切换：四风格色块预览（v1.9 A：替换旧「三按钮」）
        self._style_swatches: list = []  # [(QToolButton, theme_id, bg, accent)]
        quick_theme = QHBoxLayout()
        quick_theme.setSpacing(8)
        for _tid in ThemeEngine.THEME_IDS:
            _td = ThemeEngine.THEME_DEFINITIONS[_tid]
            _accent = _td.get("colors", {}).get("accent", "#888888")
            _bg = _td.get("colors", {}).get("bg", "#FFFFFF")
            btn = QToolButton()
            btn.setFixedSize(30, 30)
            btn.setToolTip(f"{_td['name']}（{_accent.upper()}）")
            btn.setProperty("style_id", _tid)
            btn.setStyleSheet(
                f"QToolButton {{ background: {_bg}; border: 2px solid {_accent};"
                f" border-radius: 9px; }}"
                f"QToolButton:hover {{ background: {_accent}; }}"
            )
            btn.clicked.connect(
                lambda _checked=False, t=_tid: self._switch_theme(t))
            self._style_swatches.append((btn, _tid, _bg, _accent))
            quick_theme.addWidget(btn)
        quick_theme.addStretch()
        theme_layout.addLayout(quick_theme)

        # v1.3(P2-7): 外观模式三选（浅色/深色/跟随系统），与原主题三选并存
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("外观模式:"))
        self.appearance_combo = QComboBox()
        self.appearance_combo.addItem("浅色", "light")
        self.appearance_combo.addItem("深色", "dark")
        self.appearance_combo.addItem("跟随系统", "system")
        self.appearance_combo.setToolTip(
            "深色会切换整套界面的明暗配色（当前主题保留）；「跟随系统」随 Windows 深浅色自动切换。"
        )
        self.appearance_combo.currentIndexChanged.connect(self._on_appearance_changed)
        mode_row.addWidget(self.appearance_combo)
        mode_row.addStretch()
        theme_layout.addLayout(mode_row)

        mode_hint = QLabel("「跟随系统」读取 Windows 深浅色设置并低频自动跟随；默认浅色，旧观感不变。")
        mode_hint.setWordWrap(True)
        mode_hint.setStyleSheet(
            f"QLabel {{ color: {self._hint_color()}; font-size: 11px; }}"
        )
        theme_layout.addWidget(mode_hint)

        # v1.9 A(D-V19-11/Q-E2)：C 深色夜间提示（进入时显示 + 外观模式收起）
        self._night_hint = QLabel("「深色夜间」为深色专属风格：进入时自动切深色并收起上方外观模式，离开后恢复原设置。")
        self._night_hint.setWordWrap(True)
        self._night_hint.setStyleSheet(
            f"QLabel {{ color: {self._hint_color()}; font-size: 11px; }}"
        )
        self._night_hint.setVisible(False)
        theme_layout.addWidget(self._night_hint)

        # v1.9 B/D-V19-08: 「界面字体」下拉（六字体：资源圆体默认 + 幼圆/雅黑/楷体/等线 + 粉圆仅标题）
        font_row = QHBoxLayout()
        font_row.addWidget(QLabel("界面字体:"))
        self.font_combo = QComboBox()
        try:
            from gui import fonts as _fonts
            for fid in _fonts.FONT_CHOICES:
                self.font_combo.addItem(_fonts.font_choice_label(fid), fid)
        except Exception:
            self.font_combo.addItem("资源圆体（默认）", "resource_rounded")
        self.font_combo.currentIndexChanged.connect(self._on_font_changed)
        font_row.addWidget(self.font_combo)
        font_row.addStretch()
        theme_layout.addLayout(font_row)

        self._font_hint = QLabel("选择「jf open 粉圆」仅作用于标题 / 点缀位，正文保持资源圆体。")
        self._font_hint.setWordWrap(True)
        self._font_hint.setStyleSheet(
            f"QLabel {{ color: {self._hint_color()}; font-size: 11px; }}"
        )
        theme_layout.addWidget(self._font_hint)

        # v1.4.3「主题强调色色盘」：一排精选色板 + 自定义 + 恢复默认（加在外观模式旁）
        accent_label = QLabel("主题强调色:")
        theme_layout.addWidget(accent_label)
        self._build_accent_palette(theme_layout)
        layout.addWidget(theme_frame)

        # v1.2(B9): 「模型与接口」专区 —— 替代原「API 配置」分节（设计 D8）：
        # 独立 ModelConfigPanel 承载 状态头(厂商/模型/Key末4位脱敏/连接态) + 厂商卡片点选
        # + Key/URL/模型编辑 + 保存；分区自身保留用于滚动定位与设置页层级。
        model_section = self._create_section("模型与接口")
        model_layout = model_section.layout()
        self.model_config_panel = ModelConfigPanel(self.app_ctx)
        # 面板保存成功/失败均会自刷新；这里再订阅 saved 以联动本页其它 UI（预留）
        model_layout.addWidget(self.model_config_panel)
        layout.addWidget(model_section)
        self.model_section = model_section

        # ============================================================
        # v1.4(B0/B1): 屏幕感知（持续看屏 + 视觉前提引导）
        # ============================================================
        screen_frame = self._create_section("屏幕感知")
        screen_layout = screen_frame.layout()

        sw_row = QHBoxLayout()
        self.sw_enabled_check = QCheckBox("持续看屏（总开关，默认关闭）")
        self.sw_enabled_check.setToolTip(
            "开启后码铃周期看一下你的屏幕，可回答「这个报错为什么」、按当前屏提问，"
            "并在检测到报错/异常时主动提醒。会消耗额外 token，可随时关闭；"
            "帧只在内存当轮即弃，不落盘、不做行为统计。"
        )
        self.sw_enabled_check.stateChanged.connect(self._on_sw_enabled_changed)
        sw_row.addWidget(self.sw_enabled_check)
        sw_row.addStretch()
        screen_layout.addLayout(sw_row)

        interval_row = QHBoxLayout()
        interval_row.addWidget(QLabel("采集间隔:"))
        self.sw_interval_combo = QComboBox()
        self.sw_interval_combo.addItem("15 秒（更跟手，token 消耗更高）", 15)
        self.sw_interval_combo.addItem("30 秒（推荐）", 30)
        self.sw_interval_combo.addItem("60 秒（更省）", 60)
        self.sw_interval_combo.currentIndexChanged.connect(self._on_sw_interval_changed)
        interval_row.addWidget(self.sw_interval_combo)
        interval_row.addStretch()
        screen_layout.addLayout(interval_row)

        thr_row = QHBoxLayout()
        thr_row.addWidget(QLabel("画面变化触发灵敏度:"))
        self.sw_threshold_combo = QComboBox()
        self.sw_threshold_combo.addItem("标准（变化明显才分析）", 0.04)
        self.sw_threshold_combo.addItem("灵敏（轻微变化也分析）", 0.02)
        self.sw_threshold_combo.addItem("宽松（大变化才分析）", 0.08)
        self.sw_threshold_combo.currentIndexChanged.connect(self._on_sw_threshold_changed)
        thr_row.addWidget(self.sw_threshold_combo)
        thr_row.addStretch()
        screen_layout.addLayout(thr_row)

        limit_row = QHBoxLayout()
        limit_row.addWidget(QLabel("单会话帧上限:"))
        self.sw_limit_combo = QComboBox()
        self.sw_limit_combo.addItem("100 帧", 100)
        self.sw_limit_combo.addItem("200 帧（默认）", 200)
        self.sw_limit_combo.addItem("400 帧", 400)
        self.sw_limit_combo.currentIndexChanged.connect(self._on_sw_limit_changed)
        limit_row.addWidget(self.sw_limit_combo)
        limit_row.addStretch()
        screen_layout.addLayout(limit_row)

        notice_row = QHBoxLayout()
        self.sw_notice_check = QCheckBox("高价值事件主动提醒（检测到报错/异常时气泡提示，默认开）")
        self.sw_notice_check.setToolTip(
            "开启后，看屏若检测到明显的报错/崩溃/异常弹窗，码铃会以对话气泡提醒一次"
            "（节流 ≤1 条/30 分钟，可随时关闭）。"
        )
        self.sw_notice_check.stateChanged.connect(self._on_sw_notice_changed)
        notice_row.addWidget(self.sw_notice_check)
        notice_row.addStretch()
        screen_layout.addLayout(notice_row)

        self.sw_hint_label = QLabel("")
        self.sw_hint_label.setWordWrap(True)
        self.sw_hint_label.setStyleSheet(
            f"QLabel {{ color: {self._hint_color()}; font-size: 11px; }}"
        )
        screen_layout.addWidget(self.sw_hint_label)
        self._refresh_sw_hint()
        layout.addWidget(screen_frame)
        self.screen_frame = screen_frame

        # 个性设置
        persona_frame = self._create_section("个性")
        persona_layout = persona_frame.layout()

        maid_row = QHBoxLayout()
        self.maid_check = QCheckBox("女仆模式")
        self.maid_check.setChecked(True)
        # v1.1(B3): 明确语气注入边界 —— 仅自然对话注入，代码/工具类回复保持干净
        self.maid_check.setToolTip(
            "开启后 AI 回复将带有女仆风格语气\n"
            "（仅对自然对话注入；代码与工具类回复保持干净）"
        )
        self.maid_check.stateChanged.connect(self._on_maid_mode_changed)
        maid_row.addWidget(self.maid_check)
        maid_row.addStretch()
        persona_layout.addLayout(maid_row)
        # v1.1(B3): 补充说明小字
        maid_hint = QLabel("开启后仅对自然对话注入语气，代码与工具类回复保持干净。")
        maid_hint.setWordWrap(True)
        maid_hint.setStyleSheet(
            f"QLabel {{ color: {self._hint_color()}; font-size: 11px; }}"
        )
        persona_layout.addWidget(maid_hint)

        # v1.4 宠物造型：形态已收敛为「女仆小人」一种（「女仆小兽」入口按用户
        # 要求移除，历史存档里的 chibi 由 maid_pet.resolve_pet_style 统一回落）。
        # 聊天气泡头像 + 窗口角落宠物两处共用；首页大形象 / 侧栏 / 托盘恒为本体。
        pet_row = QHBoxLayout()
        pet_row.addWidget(QLabel("宠物造型:"))
        self.pet_style_combo = QComboBox()
        self.pet_style_combo.addItem("女仆小人", "maid")
        self.pet_style_combo.setToolTip(
            "聊天气泡旁头像与窗口角落宠物的形态\n"
            "（maid = 女仆小人主形象，与首页大形象同源）"
        )
        pet_row.addWidget(self.pet_style_combo)
        pet_row.addStretch()
        persona_layout.addLayout(pet_row)
        pet_hint = QLabel(
            "影响聊天气泡头像与窗口角落宠物；首页大形象、侧栏与托盘始终是码铃小人本体。"
            "资产 PNG 放入 gui/assets/maid/ 即替换占位造型。"
        )
        pet_hint.setWordWrap(True)
        pet_hint.setStyleSheet(
            f"QLabel {{ color: {self._hint_color()}; font-size: 11px; }}"
        )
        persona_layout.addWidget(pet_hint)

        # v1.2.3: 角落宠物显隐开关（与宠物造型开关配套；默认关闭）
        pet_enabled_row = QHBoxLayout()
        self.pet_enabled_check = QCheckBox("角落宠物（聊天主屏右上角小立绘）")
        self.pet_enabled_check.setToolTip(
            "关闭后右上角不再显示窗口角落宠物；\n"
            "开启则挂载迷你 MaidPet，随心情换表情（无需重启码铃）。"
        )
        self.pet_enabled_check.stateChanged.connect(self._on_pet_enabled_changed)
        pet_enabled_row.addWidget(self.pet_enabled_check)
        pet_enabled_row.addStretch()
        persona_layout.addLayout(pet_enabled_row)
        pet_enabled_hint = QLabel(
            "默认关闭（避免聊天主屏视觉拥挤）。开启后会在聊天主屏右上角挂载一个小立绘，"
            "自动随心情换表情。"
        )
        pet_enabled_hint.setWordWrap(True)
        pet_enabled_hint.setStyleSheet(
            f"QLabel {{ color: {self._hint_color()}; font-size: 11px; }}"
        )
        persona_layout.addWidget(pet_enabled_hint)
        layout.addWidget(persona_frame)

        # v1.1(B3): Agent 设置 —— agent_enabled / agent_max_steps 属于 AppConfig(cfg)，
        # 保存时走 cfg.save()（与 API 配置区同款持久化）
        agent_frame = self._create_section("Agent 设置")
        agent_layout = agent_frame.layout()

        agent_enabled_row = QHBoxLayout()
        self.agent_enabled_check = QCheckBox("启用 Agent 模式（启动后 🤖 按钮默认开启）")
        self.agent_enabled_check.setToolTip(
            "仅影响启动时聊天面板「🤖 Agent」按钮的默认状态；\n"
            "运行中仍可随时在聊天面板手动开关（按钮显式操作优先）。"
        )
        agent_enabled_row.addWidget(self.agent_enabled_check)
        agent_enabled_row.addStretch()
        agent_layout.addLayout(agent_enabled_row)

        steps_row = QHBoxLayout()
        steps_row.addWidget(QLabel("单次任务步数上限:"))
        self.agent_steps_slider = QSlider(Qt.Horizontal)
        self.agent_steps_slider.setMinimum(3)
        self.agent_steps_slider.setMaximum(20)
        self.agent_steps_slider.setValue(8)
        self.agent_steps_slider.setToolTip("Agent 单次任务内允许的最大工具调用/思考轮数")
        self.agent_steps_slider.valueChanged.connect(self._on_agent_steps_changed)
        steps_row.addWidget(self.agent_steps_slider, 1)
        self.agent_steps_label = QLabel("8 步")
        self.agent_steps_label.setMinimumWidth(48)
        steps_row.addWidget(self.agent_steps_label)
        agent_layout.addLayout(steps_row)

        # v1.7.2(T3): 编程引擎选择（GuiConfig.coding_engine；默认内置 Agent）
        engine_row = QHBoxLayout()
        engine_row.addWidget(QLabel("编程引擎:"))
        self.coding_engine_combo = QComboBox()
        self.coding_engine_combo.addItem("内置 Agent（稳定）", "agent")
        self.coding_engine_combo.addItem("Pi 试点（RPC · 实验特性）", "pi")
        self.coding_engine_combo.setToolTip(
            "Agent 模式（🤖 开启后）执行编程任务的引擎：\n"
            "· 内置 Agent：现有 AgentEngine，行为不变；\n"
            "· Pi 试点：earendil-works/pi 0.85.1 子进程（RPC），流式与授权弹窗均已桥接。\n"
            "注意：①任务模式（managed 任务/自愈/断点）本期仍走内置引擎；\n"
            "      ②试点仅支持 DeepSeek 厂商；③需本机安装 Pi 0.85.1\n"
            "      （npm install -g --ignore-scripts @earendil-works/pi-coding-agent@0.85.1）。"
        )
        engine_row.addWidget(self.coding_engine_combo, 1)
        agent_layout.addLayout(engine_row)

        agent_hint = QLabel(
            "Agent 开启后，女仆可自主调用 8 种工具完成任务"
            "（读文件 / 列目录 / Git / 写文件 / 运行沙箱代码 / 联网搜索）；"
            "修改类操作会先征求你的授权。"
        )
        agent_hint.setWordWrap(True)
        agent_hint.setStyleSheet(
            f"QLabel {{ color: {self._hint_color()}; font-size: 11px; }}"
        )
        agent_layout.addWidget(agent_hint)
        layout.addWidget(agent_frame)

        # ============================================================
        # v1.3(P1-1): 语音 —— 朗读回复（TTS，QtTextToSpeech/SAPI 离线）
        # ============================================================
        tts_frame = self._create_section("语音")
        tts_layout = tts_frame.layout()

        # 可用性提示行：正常时一句隐私说明，degraded 时给可读降级提示
        self.tts_hint_label = QLabel("")
        self.tts_hint_label.setWordWrap(True)
        self.tts_hint_label.setStyleSheet(
            f"QLabel {{ color: {self._hint_color()}; font-size: 11px; }}"
        )
        tts_layout.addWidget(self.tts_hint_label)

        tts_enabled_row = QHBoxLayout()
        self.tts_enabled_check = QCheckBox("朗读回复（气泡「🔊 朗读本条」总开关）")
        self.tts_enabled_check.setToolTip(
            "关闭后女仆回复不再朗读；自动朗读也一并失效。\n"
            "朗读只读 AI 回复文本，绝不朗读你的原文（隐私）。"
        )
        self.tts_enabled_check.stateChanged.connect(self._on_tts_enabled_changed)
        tts_enabled_row.addWidget(self.tts_enabled_check)
        tts_enabled_row.addStretch()
        tts_layout.addLayout(tts_enabled_row)

        tts_auto_row = QHBoxLayout()
        self.tts_auto_read_check = QCheckBox("自动朗读 AI 回复（默认关）")
        self.tts_auto_read_check.setToolTip(
            "开启后每条 AI 回复完成会自动朗读出来（不打断正在进行的打字/流式）。"
        )
        self.tts_auto_read_check.stateChanged.connect(self._on_tts_auto_read_changed)
        tts_auto_row.addWidget(self.tts_auto_read_check)
        tts_auto_row.addStretch()
        tts_layout.addLayout(tts_auto_row)

        tts_speed_row = QHBoxLayout()
        tts_speed_row.addWidget(QLabel("语速:"))
        self.tts_speed_slider = QSlider(Qt.Horizontal)
        self.tts_speed_slider.setMinimum(0)
        self.tts_speed_slider.setMaximum(100)
        self.tts_speed_slider.setValue(50)
        self.tts_speed_slider.setToolTip("0 最慢 · 50 常速 · 100 最快")
        self.tts_speed_slider.valueChanged.connect(self._on_tts_speed_changed)
        tts_speed_row.addWidget(self.tts_speed_slider, 1)
        self.tts_speed_label = QLabel("50")
        self.tts_speed_label.setMinimumWidth(28)
        tts_speed_row.addWidget(self.tts_speed_label)
        tts_layout.addLayout(tts_speed_row)
        layout.addWidget(tts_frame)
        self.tts_frame = tts_frame

        # 窗口设置
        win_frame = self._create_section("窗口")
        win_layout = win_frame.layout()

        opacity_row = QHBoxLayout()
        opacity_row.addWidget(QLabel("窗口透明度:"))
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setMinimum(50)
        self.opacity_slider.setMaximum(100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        opacity_row.addWidget(self.opacity_slider)
        self.opacity_label = QLabel("100%")
        opacity_row.addWidget(self.opacity_label)
        win_layout.addLayout(opacity_row)

        sidebar_row = QHBoxLayout()
        self.sidebar_check = QCheckBox("显示侧边栏")
        self.sidebar_check.setChecked(True)
        sidebar_row.addWidget(self.sidebar_check)
        win_layout.addLayout(sidebar_row)

        chat_row = QHBoxLayout()
        self.chat_check = QCheckBox("显示聊天面板")
        self.chat_check.setChecked(True)
        chat_row.addWidget(self.chat_check)
        win_layout.addLayout(chat_row)
        layout.addWidget(win_frame)

        # ============================================================
        # v1.3(P2-6): 纪念日 —— 生日 / 首次相见日（周年语义，无倒计时无打卡）
        # ============================================================
        ann_frame = self._create_section("纪念日")
        ann_layout = ann_frame.layout()
        if _HAS_QDATE:
            self.anniversary_edits = {}
            for kind, label in (("birthday", "生日:"), ("first_meet", "首次相见日:")):
                row = QHBoxLayout()
                row.addWidget(QLabel(label))
                edit = _QDateEdit()
                edit.setCalendarPopup(True)
                edit.setDisplayFormat("MM-dd")
                sentinel = _QDate(1900, 1, 1)
                edit.setMinimumDate(sentinel)
                edit.setMaximumDate(_QDate(2099, 12, 31))
                edit.setSpecialValueText("未设置")
                edit.setDate(sentinel)  # 未设置态
                edit.setToolTip("只记住月日（周年）；当天码铃会送上一句祝福，可随时清除")
                edit.dateChanged.connect(
                    lambda _d, k=kind: self._on_anniversary_date_changed(k))
                row.addWidget(edit)
                clear_btn = QPushButton("清除")
                clear_btn.setCursor(Qt.PointingHandCursor)
                clear_btn.clicked.connect(lambda _c=False, k=kind: self._clear_anniversary(k))
                row.addWidget(clear_btn)
                row.addStretch()
                ann_layout.addLayout(row)
                self.anniversary_edits[kind] = edit
            ann_hint = QLabel(
                "只在当天送上一句祝福、不补发——记不记得都由主人说了算~"
                " 生日与首次相见日是同一天时会合并成一句祝福。"
            )
        else:
            ann_hint = QLabel("当前环境缺少日期控件，纪念日录入暂不可用（不影响其它设置）。")
        ann_hint.setWordWrap(True)
        ann_hint.setStyleSheet(
            f"QLabel {{ color: {self._hint_color()}; font-size: 11px; }}"
        )
        ann_layout.addWidget(ann_hint)
        layout.addWidget(ann_frame)
        self.ann_frame = ann_frame

        # ============================================================
        # v1.8(V18-13/D-V18-07): 场景 —— 自动感知开关 + 工作降档上限 + 映射说明
        # ============================================================
        scene_frame = self._create_section("场景")
        scene_layout = scene_frame.layout()
        scene_cfg = getattr(self.app_ctx, "config", None)
        self.scene_auto_check = QCheckBox("场景自动感知（按时段切换码铃的语气底色）")
        self.scene_auto_check.setChecked(
            bool(getattr(scene_cfg, "scene_auto", True)))
        self.scene_auto_check.stateChanged.connect(self._on_scene_auto_changed)
        self.scene_auto_check.setToolTip(
            "开启：工作日 9-12 / 14-18 点为工作模式，22:30-次日 6:30 为睡前模式，"
            "其余为休息模式；聊天面板与首页均可手动选定场景（当日有效，次日自动回落）。\n"
            "关闭：场景功能整体关闭（无语气切换、无工作降档）。"
        )
        scene_layout.addWidget(self.scene_auto_check)

        scene_cap_row = QHBoxLayout()
        scene_cap_row.addWidget(QLabel("工作模式主动消息上限:"))
        if _HAS_SPINBOX:
            self.scene_cap_spin = _QSpinBox()
            self.scene_cap_spin.setRange(0, 10)
            self.scene_cap_spin.setValue(
                max(0, int(getattr(scene_cfg, "scene_work_proactive_cap", 1))))
            self.scene_cap_spin.setToolTip(
                "工作模式下码铃每日主动消息的上限（默认 1，设 0 = 工作时段不打扰）；\n"
                "其余场景沿用「Agent 设置」里的每日上限。"
            )
            self.scene_cap_spin.valueChanged.connect(self._on_scene_cap_changed)
            scene_cap_row.addWidget(self.scene_cap_spin)
        else:
            self.scene_cap_spin = None
            scene_cap_row.addWidget(QLabel("（当前环境不支持调整）"))
        scene_cap_row.addStretch()
        scene_layout.addLayout(scene_cap_row)

        scene_hint = QLabel(
            "场景只影响码铃的语气底色（工作：简洁高效；休息：轻松随意；睡前：温柔安静），"
            "不改变消息的正常收发；工作模式还会把主动消息降到上面的上限。"
        )
        scene_hint.setWordWrap(True)
        scene_hint.setStyleSheet(
            f"QLabel {{ color: {self._hint_color()}; font-size: 11px; }}"
        )
        scene_layout.addWidget(scene_hint)
        layout.addWidget(scene_frame)
        self.scene_frame = scene_frame

        # ============================================================
        # v1.3(P1-3): 通用 —— 全局热键（按下捕获改键）+ 关闭窗口行为 + 开机自启
        # ============================================================
        common_frame = self._create_section("通用")
        common_layout = common_frame.layout()

        # 全局呼出/隐藏主窗热键
        hk_toggle_row = QHBoxLayout()
        hk_toggle_row.addWidget(QLabel("全局呼出/隐藏主窗:"))
        if _HAS_KEYSEQ_EDIT:
            self.hotkey_toggle_edit = _QKeySequenceEdit()
            self.hotkey_toggle_edit.setMaximumWidth(220)
            self.hotkey_toggle_edit.setToolTip(
                "点击后按下新组合键即可改键（任意界面生效）"
            )
            self.hotkey_toggle_edit.editingFinished.connect(self._on_hotkey_toggle_finished)
        else:
            self.hotkey_toggle_edit = QLineEdit()
            self.hotkey_toggle_edit.setReadOnly(True)
            self.hotkey_toggle_edit.setMaximumWidth(220)
        hk_toggle_row.addWidget(self.hotkey_toggle_edit)
        hk_toggle_row.addStretch()
        common_layout.addLayout(hk_toggle_row)

        # 截图提问热键
        hk_shot_row = QHBoxLayout()
        hk_shot_row.addWidget(QLabel("区域截图提问:"))
        if _HAS_KEYSEQ_EDIT:
            self.hotkey_screenshot_edit = _QKeySequenceEdit()
            self.hotkey_screenshot_edit.setMaximumWidth(220)
            self.hotkey_screenshot_edit.setToolTip(
                "点击后按下新组合键即可改键（截图选区问码铃）"
            )
            self.hotkey_screenshot_edit.editingFinished.connect(self._on_hotkey_screenshot_finished)
        else:
            self.hotkey_screenshot_edit = QLineEdit()
            self.hotkey_screenshot_edit.setReadOnly(True)
            self.hotkey_screenshot_edit.setMaximumWidth(220)
        hk_shot_row.addWidget(self.hotkey_screenshot_edit)
        hk_shot_row.addStretch()
        common_layout.addLayout(hk_shot_row)

        close_quit_row = QHBoxLayout()
        self.close_quits_check = QCheckBox("关闭窗口时直接退出")
        self.close_quits_check.setToolTip(
            "不勾选：点 X 最小化到系统托盘，应用继续驻留（默认，托盘「❌ 退出」真退出）。\n"
            "勾选：点 X 即退出（回到旧版行为）。"
        )
        self.close_quits_check.stateChanged.connect(self._on_close_quits_changed)
        close_quit_row.addWidget(self.close_quits_check)
        close_quit_row.addStretch()
        common_layout.addLayout(close_quit_row)

        close_quit_hint = QLabel(
            "默认不勾：关闭主窗 = 最小化到托盘，随时用 Ctrl+Alt+M 或托盘图标呼出；"
            "勾选后恢复「关窗即退」。"
        )
        close_quit_hint.setWordWrap(True)
        close_quit_hint.setStyleSheet(
            f"QLabel {{ color: {self._hint_color()}; font-size: 11px; }}"
        )
        common_layout.addWidget(close_quit_hint)

        # v1.3(P2-5): 开机自启 —— 默认关；首次开启确认；可随时在此关闭（干净移除）
        autostart_row = QHBoxLayout()
        self.autostart_check = QCheckBox("开机自启（默认关闭）")
        self.autostart_check.setToolTip(
            "开启后码铃随 Windows 启动；可随时回到这里关闭（干净移除启动项）。"
        )
        self.autostart_check.stateChanged.connect(self._on_autostart_toggled)
        autostart_row.addWidget(self.autostart_check)
        autostart_row.addStretch()
        common_layout.addLayout(autostart_row)

        autostart_hint = QLabel(
            "默认关闭、绝不偷偷开启。开启后写入当前用户的 Windows 启动项，"
            "取消勾选即干净移除，不会残留。"
        )
        autostart_hint.setWordWrap(True)
        autostart_hint.setStyleSheet(
            f"QLabel {{ color: {self._hint_color()}; font-size: 11px; }}"
        )
        common_layout.addWidget(autostart_hint)
        layout.addWidget(common_frame)
        self.common_frame = common_frame

        # v2.0(D-V20-03/§5.1): 更新区（检查三态 / 频道 / 开关 / 更新源 / 清理缓存）
        self._build_update_section(layout)

        # 关于
        about_frame = self._create_section("关于")
        about_layout = about_frame.layout()
        # v10.15: 关于页版本号硬编码改为读 core.__version__，v10.14 漏了 GUI 显示层
        about_layout.addWidget(QLabel(f"码铃 v{CORE_VERSION}"))
        about_layout.addWidget(QLabel("基于 PySide6 构建的 Windows 桌面应用"))
        about_layout.addWidget(QLabel("码铃 — 您的专属 AI 编程助手"))
        layout.addWidget(about_frame)

        layout.addStretch()

        # 底部保存按钮（保留在内容末尾，跟着滚动一起展示）
        save_all_btn = QPushButton("保存所有设置")
        save_all_btn.setObjectName("primaryBtn")
        save_all_btn.clicked.connect(self._on_save_all)
        layout.addWidget(save_all_btn)

        # v10.15: 把 scroll 放到 outer_layout 完成整页布局
        outer_layout.addWidget(scroll)

    def _create_section(self, title: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("settingsSection")
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        title_label = QLabel(title)
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)
        return frame

    # ==================================================================
    # v2.0(D-V20-03 / design-v20 §5.1): 「更新」区
    # ==================================================================
    def _build_update_section(self, layout) -> None:
        """构建「更新」区（当前版本 / 检查三态 / 频道 / 开关 / 更新源 / 清理缓存）。"""
        from gui.update_checker import detect_install_form

        frame = self._create_section("更新")
        box = frame.layout()

        self._update_checker = None           # 手动检查时持有，防 GC
        self._update_form = detect_install_form()

        # 当前版本（只读）+ 形态说明（dev 禁用自动替换，R-O 诚实）
        if self._update_form == "dev":
            form_hint = "开发模式（源码运行，不自动替换）"
        elif self._update_form == "onedir":
            form_hint = "目录版"
        else:
            form_hint = "单文件版"
        self.update_version_label = QLabel(f"当前版本 码铃 v{CORE_VERSION}（{form_hint}）")
        box.addWidget(self.update_version_label)

        # 检查更新按钮（三态反馈；检查中置灰显示"检查中…"）
        check_row = QHBoxLayout()
        self.update_check_btn = QPushButton("检查更新")
        self.update_check_btn.clicked.connect(self._on_check_update_clicked)
        check_row.addWidget(self.update_check_btn)
        self.update_status_label = QLabel("")
        self.update_status_label.setWordWrap(True)
        self.update_status_label.setStyleSheet(
            f"QLabel {{ color: {self._hint_color()}; font-size: 11px; }}"
        )
        check_row.addWidget(self.update_status_label)
        check_row.addStretch()
        box.addLayout(check_row)

        # v2.0(修正3 / R-A / L3-6): 上次换包未完成时的一句安静提示（只读、仅失败/回滚显示）
        from gui.update_checker import last_install_hint, load_update_state
        _last_hint = last_install_hint(load_update_state())
        self.update_last_install_label = QLabel(_last_hint)
        self.update_last_install_label.setWordWrap(True)
        self.update_last_install_label.setStyleSheet(
            f"QLabel {{ color: {theme_color(self.app_ctx, 'state_warn', '#E5A02E')}; "
            "font-size: 11px; }}"
        )
        self.update_last_install_label.setVisible(bool(_last_hint))
        box.addWidget(self.update_last_install_label)

        # 更新频道（稳定版 / 测试版）
        ch_row = QHBoxLayout()
        ch_row.addWidget(QLabel("更新频道"))
        self.update_channel_combo = QComboBox()
        self.update_channel_combo.addItem("稳定版", "stable")
        self.update_channel_combo.addItem("测试版（beta）", "beta")
        self.update_channel_combo.currentIndexChanged.connect(self._on_update_channel_changed)
        ch_row.addWidget(self.update_channel_combo)
        ch_row.addStretch()
        box.addLayout(ch_row)

        # 自动检查 / 自动下载
        self.auto_check_check = QCheckBox("自动检查更新（启动后静默检查，默认开）")
        box.addWidget(self.auto_check_check)
        self.auto_download_check = QCheckBox(
            "自动下载更新（后台下载，安装前仍需你确认，默认开）"
        )
        box.addWidget(self.auto_download_check)

        # 更新源（只读主链域名 + 备用链开关 + 自定义镜像）
        src_row = QHBoxLayout()
        src_row.addWidget(QLabel("更新源"))
        self.update_source_label = QLabel("")
        self.update_source_label.setStyleSheet(
            f"QLabel {{ color: {self._hint_color()}; font-size: 11px; }}"
        )
        src_row.addWidget(self.update_source_label)
        src_row.addStretch()
        box.addLayout(src_row)

        self.use_mirror_check = QCheckBox("使用备用链（镜像）")
        box.addWidget(self.use_mirror_check)

        mirror_row = QHBoxLayout()
        mirror_row.addWidget(QLabel("自定义镜像"))
        self.mirror_url_edit = QLineEdit()
        self.mirror_url_edit.setPlaceholderText("https://你的镜像域名/...（留空=不使用）")
        self.mirror_url_edit.setToolTip("只接受 https 直链；其域名会加入更新安全白名单")
        mirror_row.addWidget(self.mirror_url_edit)
        box.addLayout(mirror_row)

        # 清理更新缓存（保留 updater/ 与回滚备份）
        cache_row = QHBoxLayout()
        self.clear_cache_btn = QPushButton("清理更新缓存")
        self.clear_cache_btn.clicked.connect(self._on_clear_update_cache)
        cache_row.addWidget(self.clear_cache_btn)
        cache_hint = QLabel(
            "清空已下载的更新包缓存（保留最近一版回滚备份，不影响更新程序本身）"
        )
        cache_hint.setWordWrap(True)
        cache_hint.setStyleSheet(
            f"QLabel {{ color: {self._hint_color()}; font-size: 11px; }}"
        )
        cache_row.addWidget(cache_hint)
        cache_row.addStretch()
        box.addLayout(cache_row)

        self._refresh_update_source()
        layout.addWidget(frame)
        self.update_frame = frame

    def _refresh_update_source(self) -> None:
        """刷新「更新源」只读展示（当前频道主链域名）。"""
        if not hasattr(self, "update_source_label"):
            return
        from gui.update_checker import resolve_channel_url, extract_host
        config = getattr(self.app_ctx, "config", None)
        channel = getattr(config, "update_channel", "stable") if config else "stable"
        host = extract_host(resolve_channel_url(channel)) or "—"
        self.update_source_label.setText(f"主链：{host}")

    def _on_update_channel_changed(self, index: int) -> None:
        """频道切换即时落盘（下次检查生效）；刷新更新源展示。"""
        config = getattr(self.app_ctx, "config", None)
        if config is not None and hasattr(self, "update_channel_combo"):
            channel = self.update_channel_combo.currentData() or "stable"
            config.update_channel = channel
            try:
                config.save()
            except Exception:
                pass
        self._refresh_update_source()

    def _on_check_update_clicked(self) -> None:
        """手动检查更新：按钮置灰 + 显示"检查中…"，结果走三态回调。"""
        from gui.update_checker import UpdateChecker
        config = getattr(self.app_ctx, "config", None)
        channel = getattr(config, "update_channel", "stable") if config else "stable"
        self.update_check_btn.setEnabled(False)
        self.update_check_btn.setText("检查中…")
        self.update_status_label.setText("")
        try:
            checker = UpdateChecker(parent=self, channel=channel)
            checker.update_available.connect(self._on_update_available)
            checker.check_finished.connect(self._on_update_check_finished)
            self._update_checker = checker  # 持有引用防 GC
            checker.start(manual=True)
        except Exception:
            self._on_update_check_finished("failed")

    def _on_update_available(self, info: dict) -> None:
        """手动检查发现新版：展示要点（手动检查不受「忽略此版本」影响，L1-2②）。"""
        try:
            from gui.update_checker import format_update_text
            self.update_status_label.setText(format_update_text(info))
        except Exception:
            self.update_status_label.setText("发现新版本")

    def _on_update_check_finished(self, status: str) -> None:
        """手动检查三态收尾：有新版 / 已是最新 / 检查失败。"""
        from gui.update_checker import CHECK_UPDATE, CHECK_LATEST
        self.update_check_btn.setEnabled(True)
        self.update_check_btn.setText("检查更新")
        if status == CHECK_UPDATE:
            if not self.update_status_label.text():
                self.update_status_label.setText("发现新版本")
        elif status == CHECK_LATEST:
            self.update_status_label.setText("已是最新")
        else:
            self.update_status_label.setText("检查失败，请稍后重试")

    def _on_clear_update_cache(self) -> None:
        """清空 updates/ 下载缓存；保留 updater/（sidecar 运行时）与回滚备份。"""
        import shutil
        removed = False
        try:
            from gui.utils import get_user_data_dir
            updates_dir = get_user_data_dir() / "updates"
        except Exception:
            updates_dir = None
        if updates_dir is not None and updates_dir.exists():
            for child in updates_dir.iterdir():
                try:
                    if child.is_dir():
                        shutil.rmtree(child, ignore_errors=True)
                    else:
                        child.unlink()
                    removed = True
                except Exception:
                    pass
        QMessageBox.information(
            self, "清理更新缓存",
            "更新缓存已清理。" if removed else "没有需要清理的缓存。",
        )

    def _hint_color(self) -> str:
        """说明小字颜色：取主题次级文字色，主题缺失时用灰色兜底。"""
        try:
            return theme_color(self.app_ctx, "text_secondary", "#9E9E9E")
        except Exception:
            return "#9E9E9E"

    # ==================================================================
    # v1.3(P1-1): 语音区信号/降级提示
    # ==================================================================
    def _refresh_tts_hint(self) -> None:
        """语音区提示行：可用 = 隐私说明；degraded = 可读降级文案（不崩）。"""
        if not hasattr(self, "tts_hint_label"):
            return
        tts = getattr(self.app_ctx, "tts", None)
        if tts is None:
            text = "系统 TTS 组件不可用，朗读功能已停用（其它功能不受影响）。"
            color = theme_color(self.app_ctx, "state_warn", "#E5A02E")
        elif not getattr(tts, "available", False):
            reason = (getattr(tts, "availability_reason", "") or "").strip()
            text = reason or "语音朗读暂不可用，可检查系统语音设置。"
            color = theme_color(self.app_ctx, "state_warn", "#E5A02E")
        else:
            text = "朗读只读女仆的 AI 回复文本，绝不朗读你的原文（隐私保护）。"
            color = self._hint_color()
        self.tts_hint_label.setStyleSheet(f"QLabel {{ color: {color}; font-size: 11px; }}")
        self.tts_hint_label.setText(text)

    def _on_tts_enabled_changed(self, state: int) -> None:
        config = getattr(self.app_ctx, "config", None)
        if config is None:
            return
        config.tts_enabled = self.tts_enabled_check.isChecked()
        try:
            config.save()
        except Exception:
            pass
        self._refresh_tts_hint()
        # 关闭总开关时若有朗读进行，直接停（全局单例）
        if not config.tts_enabled:
            tts = getattr(self.app_ctx, "tts", None)
            if tts is not None and hasattr(tts, "stop"):
                try:
                    tts.stop()
                except Exception:
                    pass

    def _on_tts_auto_read_changed(self, state: int) -> None:
        config = getattr(self.app_ctx, "config", None)
        if config is None:
            return
        config.tts_auto_read = self.tts_auto_read_check.isChecked()
        try:
            config.save()
        except Exception:
            pass

    def _on_tts_speed_changed(self, value: int) -> None:
        self.tts_speed_label.setText(str(value))
        config = getattr(self.app_ctx, "config", None)
        if config is None:
            return
        config.tts_speed = value
        tts = getattr(self.app_ctx, "tts", None)
        if tts is not None and hasattr(tts, "set_speed"):
            try:
                tts.set_speed(value)
            except Exception:
                pass
        try:
            config.save()
        except Exception:
            pass

    # ==================================================================
    # v1.3(P1-3): 通用区 —— 全局热键改键 / 关闭窗口行为
    # ==================================================================
    def _current_hotkey(self, which: str) -> str:
        """从 QKeySequenceEdit/QLineEdit 取当前热键串（缺省回落默认）。"""
        default = "Ctrl+Alt+M" if which == "toggle" else "Ctrl+Alt+S"
        edit = getattr(self, f"hotkey_{which}_edit", None)
        if edit is None:
            return default
        try:
            if isinstance(edit, QLineEdit):
                val = edit.text().strip()
            elif hasattr(edit, "keySequence"):
                val = edit.keySequence().toString().strip()
            else:
                val = ""
        except Exception:
            val = ""
        return val or default

    def _apply_hotkey(self, which: str) -> None:
        """改键即时生效：config 落盘 + app_ctx.hotkeys 重注册（manager 缺省静默跳过）。"""
        config = getattr(self.app_ctx, "config", None)
        combo = self._current_hotkey(which)
        # 纯字母无修饰的热键会覆盖正常打字，拦下并提示（F 键等无修饰可接受）
        tokens = [t.strip() for t in combo.replace("+", " ").split() if t.strip()]
        if len(tokens) == 1 and tokens[0].isalpha():
            QMessageBox.warning(
                self, "热键提示",
                f"「{combo}」没有修饰键，会覆盖正常按键输入。\n"
                "请加上 Ctrl / Alt / Shift 等修饰键（例如 Ctrl+Alt+M）。",
            )
            if config is not None:
                _old = getattr(config, f"hotkey_{which}", "Ctrl+Alt+M" if which == "toggle" else "Ctrl+Alt+S")
            else:
                _old = "Ctrl+Alt+M" if which == "toggle" else "Ctrl+Alt+S"
            try:
                from gui.qt_compat import QKeySequence
                self.hotkey_toggle_edit.setKeySequence(QKeySequence(_old)) if which == "toggle" else \
                    self.hotkey_screenshot_edit.setKeySequence(QKeySequence(_old))
            except Exception:
                pass
            return
        if config is not None:
            setattr(config, f"hotkey_{which}", combo)
            try:
                config.save()
            except Exception:
                pass
        hk = getattr(self.app_ctx, "hotkeys", None)
        if hk is not None and hasattr(hk, "change_combo"):
            try:
                hk.change_combo(which, combo)
            except Exception:
                pass

    def _on_hotkey_toggle_finished(self) -> None:
        self._apply_hotkey("toggle")

    def _on_hotkey_screenshot_finished(self) -> None:
        self._apply_hotkey("screenshot")

    def _on_close_quits_changed(self, state: int) -> None:
        config = getattr(self.app_ctx, "config", None)
        if config is None:
            return
        config.close_quits = self.close_quits_check.isChecked()
        try:
            config.save()
        except Exception:
            pass

    # -- v1.8(V18-13/D-V18-07): 场景设置 --
    def _on_scene_auto_changed(self, state: int) -> None:
        """场景自动感知总开关（False = 场景功能整体关闭）。"""
        config = getattr(self.app_ctx, "config", None)
        if config is None:
            return
        try:
            config.scene_auto = self.scene_auto_check.isChecked()
            try:
                config.save()
            except Exception:
                pass
        except Exception:
            pass

    def _on_scene_cap_changed(self, value: int) -> None:
        """工作模式主动消息上限（Q-D6 降档值；0 = 工作时段不打扰）。"""
        config = getattr(self.app_ctx, "config", None)
        if config is None:
            return
        try:
            config.scene_work_proactive_cap = max(0, int(value))
            try:
                config.save()
            except Exception:
                pass
        except Exception:
            pass

        # D-V13-11：随 close_quits 联动 quitOnLastWindowClosed（关闭=退出时恢复 True）
        try:
            from gui.qt_compat import QApplication
            app = QApplication.instance()
            if app is not None:
                tray = getattr(self.app_ctx, "tray_manager", None)
                tray_ok = tray is not None and callable(getattr(tray, "is_available", None)) \
                    and bool(tray.is_available())
                app.setQuitOnLastWindowClosed(config.close_quits or not tray_ok)
        except Exception:
            pass

    # ==================================================================
    # v1.3(P2-7): 外观模式三选（浅色/深色/跟随系统）即时生效
    # ==================================================================
    def _on_appearance_changed(self, index: int) -> None:
        combo = getattr(self, "appearance_combo", None)
        if combo is None:
            return
        mode = combo.itemData(index) or "light"
        if mode not in ("light", "dark", "system"):
            mode = "light"
        config = getattr(self.app_ctx, "config", None)
        if config is not None:
            config.theme_mode = mode
            try:
                config.save()
            except Exception:
                pass
        engine = getattr(self.app_ctx, "theme_engine", None)
        if engine is not None and hasattr(engine, "set_theme_mode"):
            try:
                engine.set_theme_mode(mode)
            except Exception:
                pass

    # ==================================================================
    # v1.4.3「主题强调色色盘」：一排精选色板 + 自定义 + 恢复默认（即时生效）
    # ==================================================================
    # 预设色板（覆盖暖冷色相环；刻意避开三主题默认 accent 的「雷同感」）
    ACCENT_PRESETS = [
        ("珊瑚", "#FF7F50"), ("蜜橘", "#FFA726"), ("琥珀", "#FFB300"),
        ("抹茶", "#9CCC65"), ("薄荷", "#4DB6AC"), ("雾蓝", "#4FC3F7"),
        ("宝蓝", "#42A5F5"), ("靛蓝", "#5C6BC0"), ("紫罗兰", "#9B6BD6"),
        ("丁香", "#CE93D8"), ("蔷薇", "#EC6A9C"), ("月光银", "#B0BEC5"),
    ]

    def _build_accent_palette(self, parent_layout) -> None:
        """构建强调色色盘：一排色块 + 自定义 + 恢复默认。"""
        self._accent_buttons: list = []  # [(QToolButton, "#RRGGBB")]
        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setContentsMargins(0, 0, 0, 0)
        cols = 6
        for idx, (name, hexv) in enumerate(self.ACCENT_PRESETS):
            btn = QToolButton()
            btn.setToolTip(f"{name}（{hexv.upper()}）")
            btn.setFixedSize(28, 28)
            btn.setProperty("accent_hex", hexv.upper())
            btn.clicked.connect(
                lambda _checked=False, h=hexv: self._on_accent_swatch_clicked(h)
            )
            grid.addWidget(btn, idx // cols, idx % cols)
            self._accent_buttons.append((btn, hexv.upper()))
        parent_layout.addLayout(grid)

        # 操作行：自定义… / 恢复默认
        op_row = QHBoxLayout()
        op_row.setSpacing(8)
        self._accent_custom_btn = QPushButton("自定义…")
        self._accent_custom_btn.setFixedHeight(28)
        self._accent_custom_btn.clicked.connect(self._on_accent_custom)
        op_row.addWidget(self._accent_custom_btn)

        self._accent_reset_btn = QPushButton("恢复默认")
        self._accent_reset_btn.setFixedHeight(28)
        self._accent_reset_btn.setToolTip("清除自定义强调色，回退到当前主题的默认强调色")
        self._accent_reset_btn.clicked.connect(self._on_accent_reset)
        op_row.addWidget(self._accent_reset_btn)
        op_row.addStretch()
        parent_layout.addLayout(op_row)

        hint = QLabel("选定后全站界面即时换色；深色模式会自动派生对应变体。")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"QLabel {{ color: {self._hint_color()}; font-size: 11px; }}")
        parent_layout.addWidget(hint)

        # 初始高亮（加载配置后由 _load_settings 调用 _refresh_accent_selection）
        self._refresh_accent_selection()

    def _apply_custom_accent(self, hex_value: str) -> None:
        """写配置 + 引擎即时重建（复用 theme_changed 机制，全站换色）。"""
        config = getattr(self.app_ctx, "config", None)
        if config is not None:
            config.custom_accent = hex_value
            try:
                config.save()
            except Exception:
                pass
        engine = getattr(self.app_ctx, "theme_engine", None)
        if engine is not None and hasattr(engine, "set_custom_accent"):
            try:
                engine.set_custom_accent(hex_value)
                engine.load_theme(engine.current_theme_name())
            except Exception:
                pass

    def _on_accent_swatch_clicked(self, hex_value: str) -> None:
        self._apply_custom_accent(hex_value)
        self._refresh_accent_selection()

    def _on_accent_custom(self) -> None:
        if not _HAS_COLOR_DIALOG:
            return
        engine = getattr(self.app_ctx, "theme_engine", None)
        config = getattr(self.app_ctx, "config", None)
        start = QColor("#42A5F5")
        if config is not None and _is_valid_accent_hex(config.custom_accent):
            start = QColor(config.custom_accent)
        elif engine is not None and hasattr(engine, "get_color"):
            try:
                start = QColor(engine.get_color("accent", "#42A5F5"))
            except Exception:
                pass
        chosen = _QColorDialog.getColor(start, self, "选择主题强调色")
        # 取色取消或非法 -> 不改配置
        if not chosen.isValid():
            return
        hexv = chosen.name().upper()
        if not _is_valid_accent_hex(hexv):
            return
        self._apply_custom_accent(hexv)
        self._refresh_accent_selection()

    def _on_accent_reset(self) -> None:
        self._apply_custom_accent("")
        self._refresh_accent_selection()

    def _refresh_accent_selection(self) -> None:
        """高亮当前生效强调色对应的色块；自定义值高亮『自定义…』按钮。"""
        config = getattr(self.app_ctx, "config", None)
        current = (getattr(config, "custom_accent", "") or "").upper()
        matched_preset = current in {h for _, h in self._accent_buttons}
        for btn, hexv in self._accent_buttons:
            if hexv == current:
                btn.setStyleSheet(
                    "QToolButton { background-color: %s; border: 3px solid #555; "
                    "border-radius: 6px; }" % hexv
                )
            else:
                btn.setStyleSheet(
                    "QToolButton { background-color: %s; border: 2px solid rgba(0,0,0,0.12); "
                    "border-radius: 6px; }" % hexv
                )
        # 自定义按钮：若当前为自定义（非预设）值，显示该色；否则中性样式
        if hasattr(self, "_accent_custom_btn"):
            if current and not matched_preset:
                self._accent_custom_btn.setStyleSheet(
                    "QPushButton { background-color: %s; color: #FFFFFF; "
                    "border: 1px solid rgba(0,0,0,0.2); border-radius: 6px; }" % current
                )
            else:
                self._accent_custom_btn.setStyleSheet("")

    # ==================================================================
    # v1.3(P2-5): 开机自启（默认关；首次开启确认；可随时关闭干净移除）
    # ==================================================================
    def _on_autostart_toggled(self, state: int) -> None:
        config = getattr(self.app_ctx, "config", None)
        check = getattr(self, "autostart_check", None)
        if check is None:
            return
        want = check.isChecked()
        if not want:
            # 关闭：直接干净移除（失败静默，状态读取以注册表为准）
            try:
                import autostart as _auto_mod
                ok, msg = _auto_mod.disable()
            except Exception:
                ok, msg = False, "开机自启模块不可用"
            if config is not None:
                config.autostart_enabled = False
                try:
                    config.save()
                except Exception:
                    pass
            if not ok and config is not None and getattr(config, "close_quits", False):
                pass  # 静默：移除失败不打扰；系统设置里也可关
            return
        # 首次开启确认弹窗（说明行为 + 可随时关闭）
        box = QMessageBox(self)
        box.setWindowTitle("开启开机自启")
        box.setIcon(QMessageBox.Question)
        box.setText("开启后，码铃会在你登录 Windows 时自动启动。")
        box.setInformativeText(
            "你随时可以回到「设置 → 通用」关闭开机自启（干净移除启动项），不会残留。\n\n"
            "要现在开启吗？"
        )
        ok_btn = box.addButton("开启", QMessageBox.AcceptRole)
        box.addButton("暂不", QMessageBox.RejectRole)
        box.exec_()
        if box.clickedButton() is not ok_btn:
            check.blockSignals(True)
            try:
                check.setChecked(False)
            finally:
                check.blockSignals(False)
            return
        try:
            import autostart as _auto_mod
            ok, msg = _auto_mod.enable()
        except Exception as exc:
            ok, msg = False, f"开机自启模块不可用（{exc}）"
        if config is not None:
            config.autostart_enabled = ok
            try:
                config.save()
            except Exception:
                pass
        if not ok:
            QMessageBox.warning(self, "开机自启", f"{msg}\n\n可改用打包版 MaLing.exe 后重试。")
            check.blockSignals(True)
            try:
                check.setChecked(False)
            finally:
                check.blockSignals(False)

    # ==================================================================
    # v1.3(P2-6): 纪念日录入（生日/首次相见日 -> companion anniversaries，MM-DD）
    # ==================================================================
    def _anniversary_mmdd_from_edit(self, kind: str) -> Optional[str]:
        edit = (getattr(self, "anniversary_edits", None) or {}).get(kind)
        if edit is None:
            return None
        if edit.date() == edit.minimumDate():
            return None  # 未设置态
        d = edit.date()
        return f"{d.month():02d}-{d.day():02d}"

    def _on_anniversary_date_changed(self, kind: str) -> None:
        companion = getattr(self.app_ctx, "companion", None)
        if companion is None or not hasattr(companion, "set_anniversary"):
            return
        mmdd = self._anniversary_mmdd_from_edit(kind)
        try:
            companion.set_anniversary(kind, mmdd)
        except Exception:
            pass

    def _clear_anniversary(self, kind: str) -> None:
        edit = (getattr(self, "anniversary_edits", None) or {}).get(kind)
        if edit is None:
            return
        edit.blockSignals(True)
        try:
            edit.setDate(edit.minimumDate())  # 回到「未设置」态
        finally:
            edit.blockSignals(False)
        companion = getattr(self.app_ctx, "companion", None)
        if companion is not None and hasattr(companion, "set_anniversary"):
            try:
                companion.set_anniversary(kind, None)
            except Exception:
                pass

    def _on_agent_steps_changed(self, value: int) -> None:
        """步数滑条数值即时显示。"""
        self.agent_steps_label.setText(f"{value} 步")

    # ==================================================================
    # v1.4(B0/B1): 屏幕感知区信号（GuiConfig getattr/setattr 容错，不直接改 config.py）
    # ==================================================================
    def _sw_write(self, name: str, value) -> None:
        try:
            from gui.screen_watch import write_sw
            write_sw(getattr(self.app_ctx, "config", None), name, value)
        except Exception:
            pass

    def _sw_read(self, name: str, default):
        try:
            from gui.screen_watch import read_sw
            return read_sw(getattr(self.app_ctx, "config", None), name, default)
        except Exception:
            return default

    def _sw_service(self):
        try:
            from gui.screen_watch import get_screen_watch_service
            svc = get_screen_watch_service(self.app_ctx)
        except Exception:
            svc = None
        if svc is not None:
            try:
                svc.refresh_config()
            except Exception:
                pass
        return svc

    def _refresh_sw_hint(self) -> None:
        """屏幕感知区提示：隐私边界说明 + 视觉模型前提（非视觉红字引导，B0）。"""
        if not hasattr(self, "sw_hint_label"):
            return
        text = ("持续看屏只在你显式开启时采集，关即停采弃帧；帧只在内存当轮即弃，不落盘、不做行为统计。"
                "看屏与「操作」都需要支持视觉的多模态模型。")
        color = self._hint_color()
        try:
            from gui.vision_support import ensure_vision_model_hint
            hint = ensure_vision_model_hint(self.app_ctx)
        except Exception:
            hint = None
        if hint:
            text += "\n⚠️ " + hint
            color = theme_color(self.app_ctx, "state_warn", "#E5A02E")
        self.sw_hint_label.setStyleSheet(f"QLabel {{ color: {color}; font-size: 11px; }}")
        self.sw_hint_label.setText(text)

    def _confirm_screen_watch(self) -> bool:
        """设置页开启看屏的成本确认（与聊天面板开启确认同口径）。"""
        box = QMessageBox(self)
        box.setWindowTitle("开启持续看屏")
        box.setIcon(QMessageBox.Question)
        box.setText("开启后，码铃会周期性看一下你的屏幕以提供帮助。")
        lines = [
            "· 会消耗额外 token 与额度（看屏 chip 显示帧数与约消耗）",
            "· 单会话帧上限到达会自动暂停（可在此调上限 / 随时关闭）",
            "· 帧只在内存当轮即弃：不落盘、不进历史、不做行为统计",
        ]
        try:
            from gui.vision_support import ensure_vision_model_hint
            hint = ensure_vision_model_hint(self.app_ctx)
        except Exception:
            hint = None
        if hint:
            lines.append("\n⚠️ " + hint)
        box.setInformativeText("\n".join(lines))
        ok_btn = box.addButton("继续开启", QMessageBox.AcceptRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.exec_()
        return box.clickedButton() is ok_btn

    def _on_sw_enabled_changed(self, state: int) -> None:
        check = getattr(self, "sw_enabled_check", None)
        if check is None:
            return
        want = check.isChecked()
        svc = self._sw_service()
        already = svc is not None and svc.is_running()
        if want and not already:
            if not self._confirm_screen_watch():
                check.blockSignals(True)
                try:
                    check.setChecked(False)
                finally:
                    check.blockSignals(False)
                self._sw_write("enabled", False)
                return
        self._sw_write("enabled", want)
        if svc is not None:
            try:
                if want:
                    svc.start()
                else:
                    svc.stop()
            except Exception:
                pass

    def _on_sw_interval_changed(self, index: int) -> None:
        combo = getattr(self, "sw_interval_combo", None)
        if combo is None:
            return
        value = combo.itemData(index)
        if value:
            self._sw_write("interval", int(value))
            self._sw_service()

    def _on_sw_threshold_changed(self, index: int) -> None:
        combo = getattr(self, "sw_threshold_combo", None)
        if combo is None:
            return
        value = combo.itemData(index)
        if value:
            self._sw_write("threshold", float(value))
            self._sw_service()

    def _on_sw_limit_changed(self, index: int) -> None:
        combo = getattr(self, "sw_limit_combo", None)
        if combo is None:
            return
        value = combo.itemData(index)
        if value:
            self._sw_write("frame_limit", int(value))
            self._sw_service()

    def _on_sw_notice_changed(self, state: int) -> None:
        check = getattr(self, "sw_notice_check", None)
        if check is None:
            return
        self._sw_write("notice", check.isChecked())

    def _load_settings(self) -> None:
        config = getattr(self.app_ctx, "config", None)
        if config is None:
            return
        # 主题（v1.9 A：旧值归一 + 同步色块/夜间锁定 UI 状态）
        norm_theme = ThemeEngine.normalize_theme_id(getattr(config, "theme_name", ""))
        idx = self.theme_combo.findData(norm_theme)
        if idx >= 0:
            self.theme_combo.blockSignals(True)
            try:
                self.theme_combo.setCurrentIndex(idx)
            finally:
                self.theme_combo.blockSignals(False)
        if hasattr(self, "_sync_style_controls"):
            self._sync_style_controls(norm_theme)
        if hasattr(self, "_apply_night_lock_ui"):
            self._apply_night_lock_ui(ThemeEngine.is_dark_locked(norm_theme))
        # v1.9 B/D-V19-08: 界面字体回显（老配置无 font_family → 取默认资源圆体）
        if hasattr(self, "font_combo"):
            fidx = self.font_combo.findData(getattr(config, "font_family", "resource_rounded"))
            self.font_combo.blockSignals(True)   # 回显不触发保存/即时生效
            try:
                self.font_combo.setCurrentIndex(fidx if fidx >= 0 else 0)
            finally:
                self.font_combo.blockSignals(False)
        # 透明度
        val = int(config.window_opacity * 100)
        self.opacity_slider.setValue(val)
        self.opacity_label.setText(f"{val}%")
        # 侧边栏/聊天
        self.sidebar_check.setChecked(config.sidebar_visible)
        self.chat_check.setChecked(config.chat_panel_visible)
        # 女仆模式
        self.maid_check.setChecked(getattr(config, "maid_mode", True))
        # v1.4 宠物造型（仅 maid；历史 chibi 存档回落第一项）
        pet_idx = self.pet_style_combo.findData(getattr(config, "pet_style", "maid"))
        self.pet_style_combo.setCurrentIndex(pet_idx if pet_idx >= 0 else 0)
        # v1.2.3: 角落宠物开关初始化（默认关，避免拥挤）
        if hasattr(self, "pet_enabled_check"):
            self.pet_enabled_check.setChecked(getattr(config, "pet_enabled", False))
        # v1.2(B9): 模型/接口值由 ModelConfigPanel 自加载自刷新（不再在此读写旧字段）
        cfg = getattr(self.app_ctx, "cfg", None)
        if cfg:
            # v1.1(B3): Agent 设置（AppConfig 字段，默认关闭 / 8 步）
            self.agent_enabled_check.setChecked(bool(getattr(cfg, "agent_enabled", False)))
            steps = int(getattr(cfg, "agent_max_steps", 8) or 8)
            steps = max(3, min(20, steps))
            self.agent_steps_slider.setValue(steps)
            self.agent_steps_label.setText(f"{steps} 步")
        # v1.7.2(T3): 编程引擎选择回显（GuiConfig 字段，默认 agent）
        if hasattr(self, "coding_engine_combo"):
            idx = self.coding_engine_combo.findData(
                getattr(config, "coding_engine", "agent"))
            self.coding_engine_combo.setCurrentIndex(idx if idx >= 0 else 0)
        # ---- v1.3(P1-1): 语音区初始化 ----
        if hasattr(self, "tts_enabled_check"):
            self.tts_enabled_check.setChecked(bool(getattr(config, "tts_enabled", True)))
        if hasattr(self, "tts_auto_read_check"):
            self.tts_auto_read_check.setChecked(bool(getattr(config, "tts_auto_read", False)))
        if hasattr(self, "tts_speed_slider"):
            speed = int(getattr(config, "tts_speed", 50) or 50)
            speed = max(0, min(100, speed))
            self.tts_speed_slider.setValue(speed)
            self.tts_speed_label.setText(str(speed))
        # ---- v1.3(P1-3): 通用区热键 + 关闭行为初始化 ----
        from gui.qt_compat import QKeySequence
        hk_toggle = getattr(config, "hotkey_toggle", "Ctrl+Alt+M") or "Ctrl+Alt+M"
        hk_screenshot = getattr(config, "hotkey_screenshot", "Ctrl+Alt+S") or "Ctrl+Alt+S"
        if hasattr(self, "hotkey_toggle_edit"):
            try:
                if isinstance(self.hotkey_toggle_edit, QLineEdit):
                    self.hotkey_toggle_edit.setText(hk_toggle)
                elif hasattr(self.hotkey_toggle_edit, "setKeySequence"):
                    self.hotkey_toggle_edit.setKeySequence(QKeySequence(hk_toggle))
            except Exception:
                pass
        if hasattr(self, "hotkey_screenshot_edit"):
            try:
                if isinstance(self.hotkey_screenshot_edit, QLineEdit):
                    self.hotkey_screenshot_edit.setText(hk_screenshot)
                elif hasattr(self.hotkey_screenshot_edit, "setKeySequence"):
                    self.hotkey_screenshot_edit.setKeySequence(QKeySequence(hk_screenshot))
            except Exception:
                pass
        if hasattr(self, "close_quits_check"):
            self.close_quits_check.setChecked(bool(getattr(config, "close_quits", False)))
        # ---- v1.3(P2-7): 外观模式初始化 ----
        if hasattr(self, "appearance_combo"):
            mode = getattr(config, "theme_mode", "light") or "light"
            if mode not in ("light", "dark", "system"):
                mode = "light"
            idx = self.appearance_combo.findData(mode)
            if idx >= 0:
                self.appearance_combo.blockSignals(True)
                try:
                    self.appearance_combo.setCurrentIndex(idx)
                finally:
                    self.appearance_combo.blockSignals(False)
        # ---- v1.4.3「主题强调色色盘」：高亮当前生效色块 ----
        if hasattr(self, "_refresh_accent_selection"):
            self._refresh_accent_selection()
        # ---- v1.3(P2-5): 开机自启初始化（真值源在注册表；不可用环境禁勾）----
        if hasattr(self, "autostart_check"):
            try:
                import autostart as _autostart_mod
                auto_ok = bool(_autostart_mod.available()) if hasattr(_autostart_mod, "available") else False
                enabled = bool(_autostart_mod.is_enabled()) if auto_ok else False
            except Exception:
                auto_ok, enabled = False, bool(getattr(config, "autostart_enabled", False))
            self.autostart_check.blockSignals(True)
            try:
                self.autostart_check.setEnabled(auto_ok)
                self.autostart_check.setChecked(enabled)
            finally:
                self.autostart_check.blockSignals(False)
            if not auto_ok:
                self.autostart_check.setToolTip("仅 Windows 打包版（MaLing.exe）支持开机自启")
        # ---- v2.0(D-V20-03): 更新区回显（老存档缺键 → 默认值，零迁移）----
        if hasattr(self, "update_channel_combo"):
            ch = getattr(config, "update_channel", "stable") or "stable"
            if ch not in ("stable", "beta"):
                ch = "stable"
            idx = self.update_channel_combo.findData(ch)
            self.update_channel_combo.blockSignals(True)
            try:
                self.update_channel_combo.setCurrentIndex(idx if idx >= 0 else 0)
            finally:
                self.update_channel_combo.blockSignals(False)
        if hasattr(self, "auto_check_check"):
            self.auto_check_check.setChecked(bool(getattr(config, "auto_check", True)))
        if hasattr(self, "auto_download_check"):
            self.auto_download_check.setChecked(bool(getattr(config, "auto_download", True)))
        if hasattr(self, "use_mirror_check"):
            self.use_mirror_check.setChecked(bool(getattr(config, "use_mirror", True)))
        if hasattr(self, "mirror_url_edit"):
            self.mirror_url_edit.setText(str(getattr(config, "mirror_url", "") or ""))
        if hasattr(self, "_refresh_update_source"):
            self._refresh_update_source()
        # ---- v1.3(P2-6): 纪念日初始化（读 companion.anniversaries）----
        if _HAS_QDATE and hasattr(self, "anniversary_edits"):
            companion = getattr(self.app_ctx, "companion", None)
            saved = {}
            if companion is not None:
                try:
                    saved = companion.get_anniversaries() or {}
                except Exception:
                    saved = {}
            for kind, edit in self.anniversary_edits.items():
                mmdd = str(saved.get(kind) or "").strip()
                edit.blockSignals(True)
                try:
                    if mmdd:
                        d = _QDate(2000, int(mmdd[:2]), int(mmdd[3:5]))
                        if d.isValid():
                            edit.setDate(d)
                    else:
                        edit.setDate(edit.minimumDate())
                except (TypeError, ValueError):
                    edit.setDate(edit.minimumDate())
                finally:
                    edit.blockSignals(False)
        # ---- v1.4(B0/B1): 屏幕感知区初始化（读默认值；关闭信号防误触发确认）----
        if hasattr(self, "sw_enabled_check"):
            _enabled = bool(self._sw_read("enabled", False))
            self.sw_enabled_check.blockSignals(True)
            try:
                self.sw_enabled_check.setChecked(_enabled)
            finally:
                self.sw_enabled_check.blockSignals(False)
        if hasattr(self, "sw_interval_combo"):
            _iv = int(self._sw_read("interval", 30) or 30)
            _i = self.sw_interval_combo.findData(_iv)
            self.sw_interval_combo.blockSignals(True)
            try:
                self.sw_interval_combo.setCurrentIndex(_i if _i >= 0 else 1)
            finally:
                self.sw_interval_combo.blockSignals(False)
        if hasattr(self, "sw_threshold_combo"):
            _th = float(self._sw_read("threshold", 0.04) or 0.04)
            _i = self.sw_threshold_combo.findData(_th)
            self.sw_threshold_combo.blockSignals(True)
            try:
                self.sw_threshold_combo.setCurrentIndex(_i if _i >= 0 else 0)
            finally:
                self.sw_threshold_combo.blockSignals(False)
        if hasattr(self, "sw_limit_combo"):
            _fl = int(self._sw_read("frame_limit", 200) or 200)
            _i = self.sw_limit_combo.findData(_fl)
            self.sw_limit_combo.blockSignals(True)
            try:
                self.sw_limit_combo.setCurrentIndex(_i if _i >= 0 else 1)
            finally:
                self.sw_limit_combo.blockSignals(False)
        if hasattr(self, "sw_notice_check"):
            self.sw_notice_check.blockSignals(True)
            try:
                self.sw_notice_check.setChecked(bool(self._sw_read("notice", True)))
            finally:
                self.sw_notice_check.blockSignals(False)
        self._refresh_sw_hint()

    def _on_theme_changed(self, index: int) -> None:
        theme_name = self.theme_combo.itemData(index)
        if theme_name:
            self._switch_theme(theme_name)

    def _switch_theme(self, theme_name: str) -> None:
        """切换界面风格（v1.9 A/D-V19-13）。

        归一 id → C 深色夜间进出收口（apply_night_lock）→ load_theme 即时生效
        → 写 config.theme_name + save（补 ⚠-5：现状 :1405-1411 未 save 的既有缺口）。
        """
        theme_name = ThemeEngine.normalize_theme_id(theme_name)
        engine = getattr(self.app_ctx, "theme_engine", None)
        config = getattr(self.app_ctx, "config", None)
        locked = apply_night_lock(engine, config, theme_name)
        if engine is not None:
            try:
                engine.load_theme(theme_name)
            except Exception:
                pass
        if config is not None:
            config.theme_name = theme_name
            try:
                config.save()
            except Exception:
                pass
        self._apply_night_lock_ui(locked)
        self._sync_style_controls(theme_name)

    def _apply_night_lock_ui(self, locked: bool) -> None:
        """C 深色夜间：收起外观模式选择器 + 显示提示（Q-E2）。"""
        combo = getattr(self, "appearance_combo", None)
        if combo is not None:
            try:
                combo.setEnabled(not locked)
            except Exception:
                pass
        hint = getattr(self, "_night_hint", None)
        if hint is not None:
            try:
                hint.setVisible(bool(locked))
            except Exception:
                pass

    def _sync_style_controls(self, theme_name: str) -> None:
        """把下拉 / 色块高亮同步到当前风格（不触发切换）。"""
        combo = getattr(self, "theme_combo", None)
        if combo is not None:
            idx = combo.findData(theme_name)
            if idx >= 0 and combo.currentIndex() != idx:
                combo.blockSignals(True)
                try:
                    combo.setCurrentIndex(idx)
                finally:
                    combo.blockSignals(False)
        for btn, tid, bg, accent in getattr(self, "_style_swatches", []) or []:
            try:
                if tid == theme_name:
                    btn.setStyleSheet(
                        f"QToolButton {{ background: {accent}; border: 3px solid"
                        f" {accent}; border-radius: 9px; }}")
                else:
                    btn.setStyleSheet(
                        f"QToolButton {{ background: {bg}; border: 2px solid"
                        f" {accent}; border-radius: 9px; }}"
                        f"QToolButton:hover {{ background: {accent}; }}")
            except Exception:
                pass

    def _on_font_changed(self, index: int) -> None:
        """v1.9 B/D-V19-05：界面字体即时生效 —— 写 cfg + save → 复用既有
        load_theme 重建链（零新机制）。粉圆仅标题位的守卫在 fonts 层收口。"""
        choice = self.font_combo.itemData(index) if index >= 0 else None
        if not choice:
            return
        config = getattr(self.app_ctx, "config", None)
        if config is not None:
            config.font_family = choice
            try:
                config.save()
            except Exception:
                pass
        # 即时重载当前主题（重读 font_family → 重设 QSS + app.setFont）
        theme_engine = getattr(self.app_ctx, "theme_engine", None)
        if theme_engine is not None:
            try:
                theme_engine.load_theme(theme_engine.current_theme_name())
            except Exception:
                pass
        # 提示条：粉圆提示「已作用于标题位」
        if hasattr(self, "_font_hint"):
            try:
                from gui import fonts as _fonts
                if _fonts.is_title_only(choice):
                    self._font_hint.setText(
                        "已作用于标题位；正文保持资源圆体。粉圆简体覆盖有限，缺字自动回落雅黑（不会显示方块）。")
                else:
                    self._font_hint.setText("已作用于正文 / 界面；标题位同链。")
            except Exception:
                pass

    def _on_opacity_changed(self, value: int) -> None:
        self.opacity_label.setText(f"{value}%")
        opacity = value / 100.0
        main_window = self.window()
        if main_window is not None:
            main_window.setWindowOpacity(opacity)
        config = getattr(self.app_ctx, "config", None)
        if config is not None:
            config.window_opacity = opacity

    def _on_maid_mode_changed(self, state: int) -> None:
        config = getattr(self.app_ctx, "config", None)
        if config is not None:
            config.maid_mode = self.maid_check.isChecked()
            config.save()

    def _on_pet_enabled_changed(self, state: int) -> None:
        """v1.2.3: 角落宠物开关即时响应 —— 写配置 + 主窗挂载/隐藏 MaidPet。"""
        config = getattr(self.app_ctx, "config", None)
        if config is None:
            return
        config.pet_enabled = self.pet_enabled_check.isChecked()
        try:
            config.save()
        except Exception:
            pass
        main_window = self.window()
        if main_window is not None and hasattr(main_window, "set_pet_enabled"):
            try:
                main_window.set_pet_enabled(config.pet_enabled)
            except Exception:
                pass

    # ==================================================================
    # v1.2(B9): 「模型与接口」直达支持
    # ==================================================================
    def on_enter(self) -> None:
        """页面进入钩子（PageManager.navigate 调用）：刷新模型面板。

        若面板有未保存编辑则不覆盖用户输入，仅刷新状态头；
        否则从 cfg 重载（厂商卡片选中态/Key/URL/模型跟随外部变更）。
        """
        panel = getattr(self, "model_config_panel", None)
        if panel is not None:
            try:
                if panel.is_dirty():
                    panel.refresh_status()
                elif hasattr(panel, "reload_current"):
                    panel.reload_current()
            except Exception:
                pass
        self._refresh_sw_hint()  # v1.4(B0): 切到设置页时同步视觉模型前提提示

    def scroll_to_model(self) -> None:
        """把滚动区定位到「模型与接口」分区（B9 首页/侧栏直达的落点）。

        若页面首次展示、布局尚未激活（滚动条最大值仍为 0），延迟一帧重试，
        保证直达在 layout 完成后生效。
        """
        if getattr(self, "_scroll", None) is None or getattr(self, "_content", None) is None:
            return
        if getattr(self, "model_section", None) is None:
            return

        def _apply() -> None:
            try:
                sb = self._scroll.verticalScrollBar()
                if sb.maximum() <= 0:
                    return  # 布局仍未激活；不再追加重试（页面正常尺寸时极大值>0）
                # 分区顶相对内容区的 y 坐标（content 内含 24px 上边距）
                target = self.model_section.mapTo(self._content, QPoint(0, 0)).y()
                sb.setValue(max(0, min(target - 8, sb.maximum())))
            except Exception:
                pass

        sb = self._scroll.verticalScrollBar()
        if sb.maximum() > 0:
            _apply()
        else:
            # 一帧后布局完成再滚（Qt 布局激活发生在此前的事件循环）
            from gui.qt_compat import QTimer
            QTimer.singleShot(0, _apply)

    def _on_save_all(self) -> None:
        config = getattr(self.app_ctx, "config", None)
        cfg = getattr(self.app_ctx, "cfg", None)
        if config is not None:
            # 保存主题（v1.9 A：归一为四风格 id）
            config.theme_name = ThemeEngine.normalize_theme_id(
                self.theme_combo.currentData() or "")
            # v1.9 B/D-V19-08: 界面字体
            if hasattr(self, "font_combo"):
                _font_choice = self.font_combo.currentData()
                if _font_choice:
                    config.font_family = _font_choice
            # v1.3(P2-7): 外观模式
            if hasattr(self, "appearance_combo"):
                config.theme_mode = self.appearance_combo.currentData() or "light"
            # v1.3(P2-5): 开机自启镜像（真值源在注册表，此处仅回读镜像）
            if hasattr(self, "autostart_check"):
                config.autostart_enabled = self.autostart_check.isChecked()
            # v1.3(P2-6): 纪念日已即时落盘（无需再在此保存；防呆：若 companion 可用但
            # 录入未触发（如加载瞬间），此处补一次持久化）
            companion = getattr(self.app_ctx, "companion", None)
            if companion is not None and hasattr(companion, "set_anniversary") \
                    and hasattr(self, "anniversary_edits"):
                for kind in ("birthday", "first_meet"):
                    mmdd = self._anniversary_mmdd_from_edit(kind)
                    try:
                        if (companion.get_anniversaries() or {}).get(kind) != mmdd:
                            companion.set_anniversary(kind, mmdd)
                    except Exception:
                        pass
            # 保存透明度
            config.window_opacity = self.opacity_slider.value() / 100.0
            # 保存面板可见性
            config.sidebar_visible = self.sidebar_check.isChecked()
            config.chat_panel_visible = self.chat_check.isChecked()
            config.maid_mode = self.maid_check.isChecked()
            # v1.4 宠物造型（形态已收敛为 maid）
            config.pet_style = self.pet_style_combo.currentData() or "maid"
            # v1.2.3 角落宠物显隐
            config.pet_enabled = self.pet_enabled_check.isChecked()
            # ---- v1.3(P1-1): 语音区一并落盘 ----
            if hasattr(self, "tts_enabled_check"):
                config.tts_enabled = self.tts_enabled_check.isChecked()
            if hasattr(self, "tts_auto_read_check"):
                config.tts_auto_read = self.tts_auto_read_check.isChecked()
            if hasattr(self, "tts_speed_slider"):
                config.tts_speed = self.tts_speed_slider.value()
            # ---- v1.3(P1-3): 通用区（热键 + 关闭行为）一并落盘 ----
            if hasattr(self, "close_quits_check"):
                config.close_quits = self.close_quits_check.isChecked()
            if hasattr(self, "hotkey_toggle_edit") or hasattr(self, "hotkey_screenshot_edit"):
                config.hotkey_toggle = self._current_hotkey("toggle")
                config.hotkey_screenshot = self._current_hotkey("screenshot")
            # v1.7.2(T3): 编程引擎选择落盘（GuiConfig 字段）
            if hasattr(self, "coding_engine_combo"):
                data = self.coding_engine_combo.currentData()
                if data in ("agent", "pi"):
                    config.coding_engine = data
            # v2.0(D-V20-03): 更新区落盘（频道 / 自动检查 / 自动下载 / 更新源）
            if hasattr(self, "update_channel_combo"):
                data = self.update_channel_combo.currentData()
                if data in ("stable", "beta"):
                    config.update_channel = data
            if hasattr(self, "auto_check_check"):
                config.auto_check = self.auto_check_check.isChecked()
            if hasattr(self, "auto_download_check"):
                config.auto_download = self.auto_download_check.isChecked()
            if hasattr(self, "use_mirror_check"):
                config.use_mirror = self.use_mirror_check.isChecked()
            if hasattr(self, "mirror_url_edit"):
                config.mirror_url = self.mirror_url_edit.text().strip()
            config.save()
            # v1.3(P1-3): 保存后即时重注册热键 + 联动 quitOnLastWindowClosed
            hk = getattr(self.app_ctx, "hotkeys", None)
            if hk is not None and hasattr(hk, "change_combo"):
                try:
                    hk.change_combo("toggle", config.hotkey_toggle)
                except Exception:
                    pass
                try:
                    hk.change_combo("screenshot", config.hotkey_screenshot)
                except Exception:
                    pass
            try:
                from gui.qt_compat import QApplication
                _app = QApplication.instance()
                if _app is not None:
                    _tray = getattr(self.app_ctx, "tray_manager", None)
                    _tray_ok = _tray is not None and callable(getattr(_tray, "is_available", None)) \
                        and bool(_tray.is_available())
                    _app.setQuitOnLastWindowClosed(config.close_quits or not _tray_ok)
            except Exception:
                pass
        # v1.2(B9): Agent 设置由本页控件负责；模型/接口由 ModelConfigPanel 单独保存
        if cfg is not None:
            # v1.1(B3): Agent 设置（AppConfig 字段；agent_enabled 默认 False）
            cfg.agent_enabled = self.agent_enabled_check.isChecked()
            cfg.agent_max_steps = self.agent_steps_slider.value()
            cfg.save()
        # v1.2(B9): 若模型面板存在未保存编辑，随“保存所有设置”一并合并落盘
        # （不重复保存、不破坏 API Key 已保存流程；校验不过则静默跳过）
        model_panel = getattr(self, "model_config_panel", None)
        if model_panel is not None:
            try:
                if callable(getattr(model_panel, "is_dirty", None)) and model_panel.is_dirty():
                    model_panel.commit(interactive=False)
            except Exception:
                pass
        # 立即刷新 UI
        main_window = self.window()
        if main_window is not None:
            if hasattr(main_window, "sidebar"):
                main_window.sidebar.setVisible(self.sidebar_check.isChecked())
            if hasattr(main_window, "chat_panel"):
                main_window.chat_panel.setVisible(self.chat_check.isChecked())
            main_window.setWindowOpacity(self.opacity_slider.value() / 100.0)
            # 主题切换（v1.9 A：归一 id + C 深色夜间进出收口 + 即时生效）
            theme_engine = getattr(self.app_ctx, "theme_engine", None)
            saved_theme = ThemeEngine.normalize_theme_id(
                self.theme_combo.currentData() or "")
            if theme_engine is not None:
                apply_night_lock(theme_engine, config, saved_theme)
                try:
                    theme_engine.load_theme(saved_theme)
                except Exception:
                    pass
            # v1.3(P2-7): 保存后按外观模式即时生效（夜间锁定时不覆盖深色）
            if theme_engine is not None and hasattr(theme_engine, "set_theme_mode") \
                    and not ThemeEngine.is_dark_locked(saved_theme):
                try:
                    theme_engine.set_theme_mode(getattr(config, "theme_mode", "light"))
                except Exception:
                    pass
            if hasattr(self, "_apply_night_lock_ui"):
                self._apply_night_lock_ui(ThemeEngine.is_dark_locked(saved_theme))
            if hasattr(self, "_sync_style_controls"):
                self._sync_style_controls(saved_theme)
            # v1.2 宠物造型即时刷新：已存在的常驻角落宠物原位切换形象
            # （历史气泡不追溯刷新；新气泡构造时自然读取 config.pet_style）
            pet_style = self.pet_style_combo.currentData() or "maid"
            maid_pet = getattr(main_window, "maid_pet", None)
            if maid_pet is not None and callable(getattr(maid_pet, "set_pet_style", None)):
                try:
                    maid_pet.set_pet_style(pet_style)
                except Exception:
                    pass
        QMessageBox.information(self, "成功", "设置已保存")
