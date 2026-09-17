# -*- coding: utf-8 -*-
"""gui/pages/page_sillytavern.py —— 内置 SillyTavern 嵌入页（v2.2.3）。

设计依据：``SillyTavern内置施工方案.md``
    · §7  页面骨架（``TavernBackend.start()`` → ``QWebEngineView`` 加载 ``base_url``）；
    · §8  接入主窗口 + 退出钩子（终止 node 子进程，不留孤儿进程）；
    · §13 已知坑（冷启动 31.2s / 49.7s、中文路径、QtWebEngine 初始化顺序）。

与旧「酒馆」页（``gui/pages/page_tavern.py``）**完全独立**：两页各走各的数据与进程，
第一阶段不做任何数据互通（§14）；本文件不 import、不触碰旧酒馆任何模块。

---------------------------------- 三个实现选择（交付报告同步说明） ----------------------------------
1. **启动放后台线程**（:class:`_BootThread`，基类 ``gui.qt_exit_guard.ExitSafeQThread``）：
   ST 冷启动实测 31.2s / 49.7s（§13），同步调用会把 UI 线程钉死几十秒 —— 主窗变
   「未响应」、连「正在启动」提示都刷不出来。故 ``TavernBackend.start()`` 在子线程执行，
   成功/失败经信号回主线程；**``QWebEngineView`` 只在主线程创建**（Qt 硬约束）。
   退出安全复用既有 ``ExitSafeQThread``：应用退出时有界等待 + detach 兜底，不引入
   第二套停机机制。
2. **懒启动**：``__init__`` 只搭空壳 —— 不 import ``tavern_backend``、不 import
   ``PySide6.QtWebEngineWidgets``、不起任何进程。真正启动发生在首次 ``on_enter()``
   （``PageManager.navigate`` 进入本页时调用）。否则主窗构造（启动即建全部页面）
   就会拉起 ST 进程，每次开码铃白等 30~50 秒。
3. **QtWebEngine 初始化顺序**（§13）：``gui/main.py`` 在 ``QApplication`` **之前**
   import 一次 ``PySide6.QtWebEngineWidgets``；本页只在真正要上屏时惰性 import，
   并把它包成可替换的 :meth:`PageSillyTavern._create_view` 接缝（缺依赖 → 可读错误）。

-------------------------------------------- 纪律 --------------------------------------------
* 字号：本文件**零**字号赋值（``setPointSize`` / ``setPixelSize`` 一律不出现）；需要字号的
  控件先 ``setObjectName``，字号写在 ``gui/themes/base.qss``（本页 id：``sillyTavernStatus`` /
  ``sillyTavernRetryBtn``）。
* 颜色：本页只用主题语义色经 ``gui.utils.theme_color`` 现取，禁裸 ``#RRGGBB`` 上屏。
* 失败文案一律**可读**：原始退出码（如 ``3221226505`` = ``0xC0000409`` fail-fast）不直接
  丢给用户，转成「路径兼容问题，请反馈日志」（§13「中文路径」）。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from gui.qt_compat import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTimer,
    QVBoxLayout,
    QWidget,
    Qt,
    Signal,
)
from gui.qt_exit_guard import ExitSafeQThread
from gui.utils import theme_color

logger = logging.getLogger("maid_coder.gui.page_sillytavern")

__all__ = [
    "PageSillyTavern",
    "BOOT_TEXT",
    "BOOT_STAGE_TMPL",
    "PROGRESS_STAGES",
    "OPEN_BROWSER_TEXT",
    "COPY_DIAG_TEXT",
    "RETRY_TEXT_CLIP",
    "BOOT_RETRY_TEXT",
    "BOOT_FAILED_PREFIX",
    "PATH_COMPAT_TEXT",
    "STATE_IDLE",
    "STATE_STARTING",
    "STATE_READY",
    "STATE_FAILED",
    "STACK_TRACE_TEXT",
    "clip_status_text",
    "humanize_boot_error",
    "make_backend",
    "strip_machine_trace",
]

# ===========================================================================
# 文案与常量
# ===========================================================================

#: 页面标题（主窗注册时传入；侧栏入口文案见 ``gui/widgets/sidebar.py`` 的 NAV_ITEMS）。
PAGE_TITLE_DEFAULT: str = "Silly Tavern"

#: 启动中提示（§13 实测冷启动 31.2s / 49.7s → 给用户一个符合实际的预期区间）。
BOOT_TEXT: str = "正在启动酒馆（首次约 30-60 秒）…"

#: 三段式进度（v2.2.3）：冷启动的真实耗时大头是「内容播种」与「webpack 编译前端」，
#: 干等几十秒的体感很差。这里把子进程 stdout 的已知里程碑映射成三段可读文案，
#: 由 :meth:`_poll_progress` 轮询 ``TavernBackend.tail_output()`` 推进。
#: 关键词取自实测 stdout（见交付报告）：``Node version:`` → 运行时已起；
#: ``Content file`` / ``Compiling frontend`` / ``webpack`` → 播种与编译；
#: ``listening on`` / ``Go to: http`` → 服务已监听。匹配不到就保持上一阶段，不倒退。
BOOT_STAGE_TMPL: str = "正在启动酒馆 · {stage}（首次约 30-60 秒）…"
PROGRESS_STAGES: tuple = (
    ("准备运行时", re.compile(r"Node version:", re.IGNORECASE)),
    ("初始化内容与前端", re.compile(
        r"Content file|Compiling frontend|webpack|Collecting and creating stats",
        re.IGNORECASE)),
    ("启动服务", re.compile(r"listening on|Go to: http", re.IGNORECASE)),
)

#: 「在浏览器中打开」（大屏模式）：ST 本身就是本机回环上的一个网站，给用户一个
#: 脱离应用窗口的出口，顺带规避嵌入式 WebEngine 在无 GPU 机器上的不确定表现。
OPEN_BROWSER_TEXT: str = "在浏览器中打开"

#: 「复制诊断信息」：失败时把完整原文（含端口、退出码、子进程输出尾部）一键进剪贴板 ——
#: 界面上的文案是裁剪过的可读版，排障需要的是原文。
COPY_DIAG_TEXT: str = "复制诊断信息"
RETRY_TEXT_CLIP: str = "已复制"
BOOT_RETRY_TEXT: str = "重试启动"
BOOT_FAILED_PREFIX: str = "酒馆启动失败："

#: 启动态（``state()`` 只读暴露；供接线方与测试判断，不在文案里出现）。
STATE_IDLE: str = "idle"
STATE_STARTING: str = "starting"
STATE_READY: str = "ready"
STATE_FAILED: str = "failed"

#: Windows fail-fast / 访问违例退出码（十进制与十六进制两种写法都要覆盖，大小写变体
#: 由 :func:`humanize_boot_error` 的 ``lower()`` 统一处理）。ST 首次初始化在非 ASCII
#: 路径下的已知兼容问题（§13「中文路径」）；原始码对用户无意义，转可读文案。
#:
#: · ``3221226505`` / ``0xC0000409`` —— STACK_BUFFER_OVERRUN（``tavern_backend``
#:   的崩溃码表里明确登记，实测可达）；
#: · ``3221225477`` / ``0xC0000005`` —— ACCESS_VIOLATION。**该码的来源存疑**：
#:   后端工位称会随路径兼容问题出现，QA 在 6+ 种场景下只复现出 0xC0000409。
#:   无论可达性如何，「同族崩溃码漏映射」本身就是缺陷（会把裸码丢给用户），
#:   故在此**作防御性覆盖**（QA P2-1）。
_PATH_COMPAT_CODES = ("3221226505", "0xc0000409", "3221225477", "0xc0000005")
PATH_COMPAT_TEXT: str = "酒馆初始化失败（路径兼容问题，请反馈日志）"

#: 内置浏览器缺依赖时的可读文案（PySide6-WebEngine 未安装）。
WEBENGINE_MISSING_TMPL: str = "酒馆启动失败：缺少内置浏览器组件（{detail}）"

#: 状态区文案字符上限。后端的早退诊断会带上「子进程最后 N 行输出」（实测 60 行），
#: 直接塞进 QLabel 会把页面撑成一堵日志墙 —— 界面只留前段可读信息，
#: **完整原文仍由 ``_BootThread`` / :meth:`PageSillyTavern._show_failure` 写进日志**。
_MAX_STATUS_CHARS: int = 300
_CLIP_TAIL: str = "…（完整信息见日志）"

#: 子进程**机器痕迹**行的识别规则（QA P2-4）：native / JS 栈回溯头、纯地址行。
#: 命中即从该行起整段丢弃 —— 用户不该看到 ``----- Native stack trace -----`` 和
#: 一串 ``0x00007ff...`` 地址（``process.abort()`` 场景实测前 300 字符就是这些）。
#: **只影响界面呈现**：完整原文照旧进日志（``_show_failure`` 先 log 后 clip）。
_TRACE_HEADER_RE = re.compile(r"stack\s*trace", re.IGNORECASE)
#: 地址行：``0x00007ff6c1a2b3d4`` / `` 1: 0x00007ff6…`` / ``#1 0x…`` 三种常见形态。
_ADDRESS_LINE_RE = re.compile(r"^\s*(?:#?\s*\d*\s*:?\s*)?0x[0-9a-fA-F]{6,}\b")

#: 头部被整段判为机器痕迹（无可读信息）时的兜底文案。
STACK_TRACE_TEXT: str = "酒馆启动失败：子进程异常终止（完整信息见日志）"

#: 主题语义键的兜底色（仅 ``theme_engine`` 不可用时使用；正常路径一律经 theme_color）。
_FALLBACK_COLORS = {
    "text": "#4A4A4A",
    "text_hint": "#9A9A9A",
    "bg_card": "#FFFFFF",
    "divider": "#EFE0E2",
    "accent": "#FF6B9D",
    "text_on_accent": "#FFFFFF",
    "primary": "#FF6B9D",
}

#: 圆角 / 内距（不是色值，故不入上面的兜底色表）。
_RADIUS_SM: str = "6px"


# ===========================================================================
# 纯函数 / 工厂（可被测试替换）
# ===========================================================================

def humanize_boot_error(exc: BaseException) -> str:
    """把启动异常转成**用户可读**文案（退出码一律不外泄）。

    * 异常信息含 ``3221226505`` / ``0xC0000409`` → :data:`PATH_COMPAT_TEXT`；
    * 其余 → ``酒馆启动失败：<原始信息>``（原始信息本身是给人看的，保留以利排查）。
    """
    detail = str(exc).strip() or type(exc).__name__
    low = detail.lower()
    for code in _PATH_COMPAT_CODES:
        if code in low:
            return PATH_COMPAT_TEXT
    return f"{BOOT_FAILED_PREFIX}{detail}"


def strip_machine_trace(text: str) -> tuple:
    """切掉「机器痕迹」段，返回 ``(可读头部, 是否命中)``。

    机器痕迹 = 栈回溯头（含 ``stack trace``）或纯地址行（``0x00007ff…``）起、直到结尾的
    全部内容。只用于**界面呈现**：命中后界面只留头部可读信息 + 指向日志。
    """
    lines = str(text or "").splitlines()
    for index, line in enumerate(lines):
        if _TRACE_HEADER_RE.search(line) or _ADDRESS_LINE_RE.match(line):
            return "\n".join(lines[:index]).strip(), True
    return str(text or "").strip(), False


def clip_status_text(text: str) -> str:
    """把失败文案压成状态区可读的一版（去机器痕迹 + 超长截断；完整原文进日志）。

    * 命中栈回溯 / 地址行 → 只留头部；头部无可读信息时用 :data:`STACK_TRACE_TEXT`；
    * 其余超长 → 截到 :data:`_MAX_STATUS_CHARS` 并指向日志。
    """
    flat = str(text or "").strip()
    head, has_trace = strip_machine_trace(flat)
    if has_trace:
        if not head:
            return STACK_TRACE_TEXT
        return head[:_MAX_STATUS_CHARS].rstrip() + _CLIP_TAIL
    if len(flat) <= _MAX_STATUS_CHARS:
        return flat
    return flat[:_MAX_STATUS_CHARS].rstrip() + _CLIP_TAIL


def make_backend() -> Any:
    """创建 ST 子进程管理器（**惰性 import**；模块缺失 → 抛 ``ImportError``）。

    单点工厂：接线方 / 测试可替换本模块同名符号注入假后端，不必真起 node。
    接口由施工方案冻结：``start() -> (port, base_url)`` / ``stop()`` / ``is_running()``。
    """
    from tavern_backend import TavernBackend  # 惰性：模块缺失不应影响主窗构造

    return TavernBackend()


# ===========================================================================
# 后台启动线程
# ===========================================================================

class _BootThread(ExitSafeQThread):
    """在子线程里跑 ``backend.start()``（可能 30~60 秒），结果经信号回主线程。

    继承 ``ExitSafeQThread``（``gui/qt_exit_guard.py``）：应用退出时自动「有界等待 +
    detach 兜底」，不会出现「QThread 仍在跑时解释器退出」的 fail-fast（0xC0000409）。
    """

    #: (port, base_url)
    ok = Signal(int, str)
    #: 可读错误文案（已过 :func:`humanize_boot_error`）
    failed = Signal(str)

    def __init__(self, backend: Any, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._backend = backend

    def run(self) -> None:  # noqa: D102 - QThread 钩子
        try:
            port, url = self._backend.start()
        except Exception as exc:  # noqa: BLE001 - 任何启动失败都要转成页面可读态
            logger.warning("SillyTavern 启动失败: %s", exc, exc_info=True)
            self.failed.emit(humanize_boot_error(exc))
            return
        self.ok.emit(int(port), str(url))


# ===========================================================================
# 主类
# ===========================================================================

class PageSillyTavern(QWidget):
    """内置 SillyTavern 页：启动 node 后端 → 内嵌浏览器加载官方界面。

    公共 API（供接线方 / 测试）：
        * :meth:`on_enter` —— ``PageManager`` 生命周期钩子：**首次进入才启动**（懒启动）；
        * :meth:`retry` —— 「重试启动」按钮的落点（幂等，失败后可用）；
        * :meth:`shutdown` —— 停机（**幂等**）：停启动线程 + 终止 node 子进程；
        * :meth:`state` —— 只读启动态（``idle`` / ``starting`` / ``ready`` / ``failed``）。

    Attributes（装配结果）：
        ``status`` / ``retry_btn`` / ``view``（成功后才非 None）。
    """

    def __init__(
        self,
        app_context: Any = None,
        title: str = PAGE_TITLE_DEFAULT,
        parent: Optional[QWidget] = None,
    ) -> None:
        """构造页面（**只搭空壳**：不起进程、不 import 后端与 WebEngine）。

        Args:
            app_context: 应用上下文（本页当前只用 ``theme_engine`` 取语义色）。
            title: 页面标题（主窗注册用）。
            parent: Qt 父对象。
        """
        super().__init__(parent)
        self.app_ctx = app_context
        self.title = title
        self._backend: Any = None
        self._thread: Optional[_BootThread] = None
        self._view: Any = None
        self._state = STATE_IDLE
        self._quit_handled = False
        self._quit_app: Any = None
        # v2.2.3: 就绪后的基址（「在浏览器中打开」用）、失败原文（「复制诊断信息」用）、
        # 三段式进度的定时器与已到达阶段。
        self._base_url: str = ""
        self._last_error_text: str = ""
        self._progress_timer: Any = None
        self._last_stage: int = 0
        # v2.2.5 启动预热：本次启动是否由 warmup 发起；以及用户是否已在看这一页
        # （两者共同决定"后端就绪时要不要立刻建视图"，见 _on_boot_ok）。
        self._warmup_only: bool = False
        self._user_waiting: bool = False
        self._init_ui()
        self._apply_theme()
        self._connect_theme()
        self._arm_about_to_quit()

    # ==================================================================
    # 构建
    # ==================================================================
    def _init_ui(self) -> None:
        """空壳：状态提示 + 「重试启动」按钮 + 留给内嵌浏览器的位置。"""
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(12, 12, 12, 12)
        self._root.setSpacing(8)

        self.status = QLabel(BOOT_TEXT, self)
        self.status.setObjectName("sillyTavernStatus")
        self.status.setWordWrap(True)
        self._root.addWidget(self.status)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addStretch(1)
        # 三个动作按钮共用同一 objectName —— 字号由 base.qss 统一给，颜色由
        # _apply_theme() 按主题套（见该处说明），避免逐个维护样式。
        self.retry_btn = QPushButton(BOOT_RETRY_TEXT, self)
        self.retry_btn.setObjectName("sillyTavernRetryBtn")
        self.retry_btn.setCursor(Qt.PointingHandCursor)
        self.retry_btn.clicked.connect(self.retry)
        self.retry_btn.hide()
        row.addWidget(self.retry_btn)
        # 失败态追加：把**完整原文**（端口 / 退出码 / 子进程输出尾部）放进剪贴板。
        # 界面上那份是裁剪过的可读版，排障要的是原文。
        self.copy_btn = QPushButton(COPY_DIAG_TEXT, self)
        self.copy_btn.setObjectName("sillyTavernRetryBtn")
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.clicked.connect(self._copy_diagnostics)
        self.copy_btn.hide()
        row.addWidget(self.copy_btn)
        # 就绪态：大屏模式出口（ST 本身就是本机回环上的一个网站）。
        self.open_btn = QPushButton(OPEN_BROWSER_TEXT, self)
        self.open_btn.setObjectName("sillyTavernRetryBtn")
        self.open_btn.setCursor(Qt.PointingHandCursor)
        self.open_btn.clicked.connect(self._open_in_browser)
        self.open_btn.hide()
        row.addWidget(self.open_btn)
        row.addStretch(1)
        self._root.addLayout(row)

        # 末尾常驻 stretch：内嵌浏览器 insertWidget(count()-1, view) 插在它之前。
        self._root.addStretch(1)

    def _color(self, key: str) -> str:
        """现取主题语义色（读时取、绝不缓存）。"""
        return theme_color(self.app_ctx, key, _FALLBACK_COLORS.get(key, ""))

    def _action_buttons(self) -> tuple:
        """三个动作按钮（重试 / 复制诊断 / 浏览器打开）：共用 objectName 与样式。"""
        return (self.retry_btn, self.copy_btn, self.open_btn)

    def _apply_theme(self) -> None:
        """按活动色板重刷本页取色（字号一律留给 base.qss）。"""
        try:
            self.status.setStyleSheet(
                "QLabel#sillyTavernStatus { color: %s; background: transparent; }"
                % self._color("text_hint")
            )
            btn_qss = (
                "QPushButton#sillyTavernRetryBtn {"
                f" color: {self._color('text_on_accent')};"
                f" background: {self._color('primary')};"
                " border: none;"
                f" border-radius: {_RADIUS_SM};"
                " padding: 6px 18px;"
                "}"
            )
            for btn in self._action_buttons():
                btn.setStyleSheet(btn_qss)
        except Exception:
            logger.debug("SillyTavern 页换肤失败（忽略）", exc_info=True)

    def _on_theme_changed(self, _theme_name: str = "") -> None:
        """``theme_engine.theme_changed`` 槽：重刷本页取色。"""
        self._apply_theme()

    # ==================================================================
    # 生命周期
    # ==================================================================
    def on_enter(self) -> None:
        """``PageManager`` 生命周期钩子：首次进入本页时才真正启动（懒启动）。

        三种情形：
        * 已被 :meth:`warmup` 预热就绪 → 只补建视图（node 早就在跑了）；
        * 预热**正在进行** → 记下"用户已在看"，让就绪回调立刻建视图（否则用户会盯着空页）；
        * 其余（idle / failed）→ 照常 :meth:`boot`。
        """
        if self._state == STATE_READY and self._view is None:
            self._materialize_view(0, self._base_url)
            if self._view is not None:
                self.open_btn.show()
                logger.info("预热的后端已就绪，补建内嵌浏览器视图")
            return
        if self._state == STATE_STARTING:
            self._user_waiting = True
            return
        self.boot()

    def warmup(self) -> None:
        """启动预热（v2.2.5）：在用户点开本页**之前**，后台把 node 后端先拉起来。

        与 :meth:`boot` 共用同一条启动路径、同一套失败降级与退出清理，区别只在动机：
        boot 由 ``on_enter`` 触发（用户要看），warmup 由应用启动满 N 秒触发（预判）。

        **只启后端、不建视图** —— 提前创建 ``QWebEngineView`` 会白占一个渲染进程与内存，
        而用户可能压根不开这一页。视图留给真正进入时由 :meth:`_materialize_view` 补建。

        失败/不支持时静默（只记日志）：用户没在看，不该弹任何界面。
        """
        if self._state != STATE_IDLE or not self._warmup_enabled():
            return
        self._warmup_only = True
        logger.info("内置酒馆预热：后台预启 node 后端（用户点开时通常已就绪）")
        self.boot()

    def _warmup_enabled(self) -> bool:
        """预热开关（``GuiConfig.tavern_warmup``，取不到时按开启处理）。"""
        cfg = getattr(self.app_ctx, "config", None) if self.app_ctx is not None else None
        try:
            return bool(getattr(cfg, "tavern_warmup", True))
        except Exception:
            return True

    def state(self) -> str:
        """当前启动态（只读）：``idle`` / ``starting`` / ``ready`` / ``failed``。"""
        return self._state

    def boot(self) -> None:
        """启动 ST 后端（幂等；已启动 / 正在启动时直接返回）。

        失败路径一律落到「可读文案 + 重试按钮」，绝不抛给调用方（导航不该炸主窗）。
        """
        if self._state in (STATE_STARTING, STATE_READY):
            return
        self._state = STATE_STARTING
        self.status.setText(BOOT_TEXT)
        self.status.show()
        self.retry_btn.hide()

        if self._backend is None:
            try:
                self._backend = make_backend()
            except Exception as exc:  # noqa: BLE001 - 缺模块 / 缺依赖都要可读降级
                logger.warning("SillyTavern 后端不可用: %s", exc, exc_info=True)
                self._show_failure(humanize_boot_error(exc))
                return

        thread = _BootThread(self._backend, self)
        thread.ok.connect(self._on_boot_ok)
        thread.failed.connect(self._on_boot_failed)
        self._thread = thread
        self._start_progress_poll()   # 三段式进度：轮询子进程 stdout 里程碑
        thread.start()

    def retry(self) -> None:
        """「重试启动」：从失败态重来一次（启动中 / 已就绪时为无操作）。"""
        self.boot()

    # ==================================================================
    # 启动结果
    # ==================================================================
    def _on_boot_ok(self, port: int, url: str) -> None:  # noqa: ARG002 - port 仅留痕
        """后端就绪（主线程）：预热场景只记状态，正常场景创建内嵌浏览器并加载。"""
        self._thread = None
        self._stop_progress_poll()
        self._base_url = url          # 供「在浏览器中打开」使用
        # 预热且用户还没在看这一页 → 停在"后端已就绪"，视图留给 on_enter 补建
        # （提前建 QWebEngineView 会白占一个渲染进程，而用户可能压根不开这页）。
        if self._warmup_only and not self._user_waiting:
            self._warmup_only = False
            self._state = STATE_READY
            self.status.hide()
            self._register_diagnostics_provider()
            logger.info("内置酒馆预热就绪（node 已起，视图待进入时创建）port=%s", port)
            return
        self._warmup_only = False
        if not self._materialize_view(port, url):
            return
        self.open_btn.show()          # 就绪：给一个脱离应用窗口的出口（大屏模式）
        self._register_diagnostics_provider()   # 供「导出诊断包」收走 ST 的服务端输出
        logger.info("SillyTavern 已就绪（port=%s url=%s）", port, url)

    def _materialize_view(self, port: int, url: str) -> bool:
        """创建内嵌浏览器并加载 ``url``；成功返回 True（失败走可读降级并停后端）。

        独立成方法是为了让「预热就绪 → 用户进入时补建视图」复用同一条创建路径。
        """
        try:
            view = self._create_view()
        except Exception as exc:  # noqa: BLE001 - 缺 WebEngine 组件 → 可读降级
            logger.warning("内置浏览器创建失败: %s", exc, exc_info=True)
            self._show_failure(WEBENGINE_MISSING_TMPL.format(detail=exc))
            self._stop_backend()  # 浏览器起不来就别把 node 留在后台
            return False
        try:
            view.setUrl(self._make_url(url))
        except Exception as exc:  # noqa: BLE001 - 地址非法同样走可读降级
            logger.warning("加载酒馆地址失败: %s", exc, exc_info=True)
            self._show_failure(f"{BOOT_FAILED_PREFIX}{exc}")
            self._drop_view(view)
            self._stop_backend()
            return False

        # ⚠️ 必须先移掉空壳期的末尾 stretch，否则 QWebEngineView 会被压成 0 高。
        # QVBoxLayout 把全部剩余高度分给 stretch，而 QWebEngineView 的 sizeHint 很小；
        # 实测（1200x800 窗口）：
        #   insertWidget(count()-1, view)      → view 高度 0   ← 曾经的写法
        #   insertWidget(count()-1, view, 1)   → view 高度 360（与 stretch 平分，仍不满）
        #   移除末尾 stretch + addWidget(view, 1) → view 高度 720（占满剩余空间）✓
        # 症状是用户可见的：内嵌酒馆只显示顶部一条黑栏，主体空白（WebEngine 本身正常，
        # QtWebEngineProcess、DOM、HTTP 全部正常，纯粹是视口高度为 0）。
        last = self._root.count() - 1
        item = self._root.itemAt(last)
        if item is not None and item.spacerItem() is not None:
            self._root.takeAt(last)
            del item
        self._root.addWidget(view, 1)
        self._view = view
        self._state = STATE_READY
        self.status.hide()
        self.retry_btn.hide()
        self.copy_btn.hide()
        return True

    def _on_boot_failed(self, message: str) -> None:
        """后端启动失败（主线程）：显示可读错误 + 重试按钮。"""
        self._thread = None
        self._show_failure(message)

    def _show_failure(self, message: str) -> None:
        """统一失败呈现（可读文案 + 「重试启动」）。

        界面文案经 :func:`clip_status_text` 处理：**先切掉机器痕迹段**（栈回溯 / 地址行，
        见 :data:`_TRACE_HEADER_RE`），再截到 :data:`_MAX_STATUS_CHARS` 并指向日志。
        **完整原文进日志**（``maid_debug.log``）——用户看到的是人话，排障信息不丢。
        """
        full = str(message or "").strip() or BOOT_FAILED_PREFIX.rstrip("：")
        logger.warning("SillyTavern 失败呈现：%s", full)
        self._stop_progress_poll()
        self._state = STATE_FAILED
        self._last_error_text = full     # 界面那份是裁剪版；原文留给「复制诊断信息」
        self.status.setText(clip_status_text(full))
        self.status.show()
        self.retry_btn.show()
        self.copy_btn.show()
        self.open_btn.hide()

    # ==================================================================
    # 三段式进度（冷启动 30-60s 的等待体验）
    # ==================================================================
    def _start_progress_poll(self) -> None:
        """启动进度轮询（主线程 QTimer）：把子进程 stdout 的里程碑映射成阶段文案。

        为什么是轮询而不是让后端回调：``TavernBackend`` 的 stdout 消费线程已经在
        维护环形缓冲（``tail_output()``，线程安全），复用它比新增一条回调链更省事，
        也不改变后端的对外契约。
        """
        self._stop_progress_poll()
        self._last_stage = 0
        try:
            timer = QTimer(self)
            timer.setInterval(700)
            timer.timeout.connect(self._poll_progress)
            timer.start()
            self._progress_timer = timer
        except Exception:
            logger.debug("进度轮询启动失败（忽略，退回静态文案）", exc_info=True)

    def _poll_progress(self) -> None:
        """推进阶段文案；匹配不到里程碑就保持当前阶段（**不倒退**）。"""
        backend = self._backend
        if backend is None or self._state != STATE_STARTING:
            self._stop_progress_poll()
            return
        try:
            tail = backend.tail_output()
        except Exception:
            return
        reached = 0
        for idx, (_label, pat) in enumerate(PROGRESS_STAGES, start=1):
            if pat.search(tail):
                reached = idx
        if reached > self._last_stage:
            self._last_stage = reached
            self.status.setText(
                BOOT_STAGE_TMPL.format(stage=PROGRESS_STAGES[reached - 1][0]))

    def _stop_progress_poll(self) -> None:
        """停止进度轮询（幂等）。"""
        timer = self._progress_timer
        self._progress_timer = None
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                logger.debug("进度轮询停止失败（忽略）", exc_info=True)

    # ==================================================================
    # 动作：大屏模式 / 复制诊断信息
    # ==================================================================
    def _open_in_browser(self) -> None:
        """在系统浏览器打开 ST（大屏模式）。

        做成**可替换接缝**（惰性 import + 单点调用）：单元测试可替换本方法以免真的
        拉起系统浏览器。ST 本身就是本机回环上的一个网站，这条路径等价于"宽屏使用"。
        """
        url = self._base_url or ""
        if not url:
            return
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices

            QDesktopServices.openUrl(QUrl(url))
            logger.info("已在系统浏览器打开内置酒馆: %s", url)
        except Exception:
            logger.debug("打开系统浏览器失败（忽略）", exc_info=True)

    def _copy_diagnostics(self) -> None:
        """把失败**完整原文**放进剪贴板（界面那份是裁剪过的可读版）。"""
        text = self._last_error_text or self.status.text()
        try:
            clipboard = QApplication.clipboard()
            if clipboard is None:
                return
            clipboard.setText(text)
            self.copy_btn.setText(RETRY_TEXT_CLIP)
            # ⚠️ 必须把按钮作为 context 传进去，**不要**用裸 lambda：
            # 1.5 秒后按钮可能已随页面销毁（切页/关窗/测试里的 deleteLater），
            # 裸 lambda 会访问已释放的 C++ 对象，把
            # ``RuntimeError: Internal C++ object already deleted`` 抛进 Qt 事件循环。
            # 这个坑是被 pytest-qt 的 "Exceptions caught in Qt event loop" 抓到的 ——
            # 它不在本用例里报错，而是污染**后续**用例，症状极具迷惑性。
            QTimer.singleShot(1500, self.copy_btn,
                              lambda: self.copy_btn.setText(COPY_DIAG_TEXT))
            logger.info("诊断信息已复制到剪贴板（%d 字符）", len(text))
        except Exception:
            logger.debug("复制诊断信息失败（忽略）", exc_info=True)

    def _register_diagnostics_provider(self) -> None:
        """把本页持有的**内置酒馆服务端输出**注册给诊断包（段名 ``sillytavern_stdout``）。

        为什么必须由本页注册：node 的 stdout 由 ``TavernBackend`` 的消费线程收在环形缓冲里，
        只有持有 backend 的页面拿得到；日志侧因 handler 级别是 INFO 而落不了盘。
        注册的是**闭包**（读时现取），所以启动中/失败后导出都拿得到当时的输出。
        """
        ctx = self.app_ctx
        providers = getattr(ctx, "diagnostics_providers", None) if ctx is not None else None
        if providers is None:
            return

        def _dump() -> str:
            backend = self._backend
            if backend is None:
                return "(内置酒馆未启动)"
            header = (f"state={self._state}  port={getattr(backend, 'port', None) or '-'}  "
                      f"cwd=_internal/sillytavern\n{'-' * 60}\n")
            try:
                return header + (backend.tail_output() or "(无输出)")
            except Exception as exc:  # noqa: BLE001 - 诊断段不允许抛
                return header + f"(读取失败: {exc})"

        try:
            providers["sillytavern_stdout"] = _dump
        except Exception:
            logger.debug("注册诊断段失败（忽略）", exc_info=True)

    # ==================================================================
    # 可替换接缝（惰性 import 隔离；测试可替换以免真起 QtWebEngine）
    # ==================================================================
    def _create_view(self) -> Any:
        """创建 ``QWebEngineView``（**只在主线程调用**；缺依赖 → 抛异常由调用方转文案）。"""
        from PySide6.QtWebEngineWidgets import QWebEngineView

        return QWebEngineView(self)

    @staticmethod
    def _make_url(url: str) -> Any:
        """``str`` → ``QUrl``（惰性 import，与 WebEngine 同批依赖）。"""
        from PySide6.QtCore import QUrl

        return QUrl(url)

    def _drop_view(self, view: Any) -> None:
        """丢弃创建失败 / 加载失败的浏览器控件（幂等，异常静默）。"""
        try:
            self._root.removeWidget(view)
            view.setParent(None)
            view.deleteLater()
        except Exception:
            logger.debug("丢弃内置浏览器控件失败（忽略）", exc_info=True)

    # ==================================================================
    # 停机（退出清理；幂等）
    # ==================================================================
    def shutdown(self) -> None:
        """停机（**幂等**）：停后台启动线程 + 终止 node 子进程。

        退出链共四处调用（互为兜底，重复调用无副作用）：
          ① 本页自挂的 ``QApplication.aboutToQuit``（见 :meth:`_arm_about_to_quit`）；
          ② ``MainWindow.closeEvent``（无托盘 / ``close_quits=True`` 的直退路径）；
          ③ ``TrayManager._on_quit``（托盘「❌ 退出」= 唯一真退出入口）；
          ④ ``gui/main.py::_quit_stop_services`` 的总兜底步。
        这是「不留孤儿 node 进程」的保证（§8 / §12 验收 3）。
        """
        thread = self._thread
        self._thread = None
        if thread is not None:
            try:
                thread.stop()  # ExitSafeQThread 契约：有界等待，绝不无限阻塞
            except Exception:
                logger.debug("SillyTavern 启动线程停机失败（忽略）", exc_info=True)
        self._stop_backend()
        self._state = STATE_IDLE

    def _stop_backend(self) -> None:
        """终止 ST 子进程（幂等：后端引用置空后重复调用为无操作）。"""
        backend = self._backend
        self._backend = None
        if backend is None:
            return
        try:
            backend.stop()
        except Exception:
            logger.debug("SillyTavern 后端停机失败（忽略）", exc_info=True)

    # ==================================================================
    # 应用退出自我收口（与旧酒馆页同款：无 QApplication 时静默降级）
    # ==================================================================
    def _connect_theme(self) -> None:
        """订阅 ``theme_engine.theme_changed`` → 重刷本页取色（失败不影响启动）。"""
        try:
            engine = getattr(self.app_ctx, "theme_engine", None)
            if engine is not None and hasattr(engine, "theme_changed"):
                engine.theme_changed.connect(self._on_theme_changed)
        except Exception:
            logger.debug("换肤订阅失败（忽略）", exc_info=True)

    def _arm_about_to_quit(self) -> None:
        """挂 ``QApplication.aboutToQuit`` → 本页自我停机（幂等）。"""
        try:
            app = QApplication.instance()
        except Exception:  # pragma: no cover - 无 Qt 绑定边界
            logger.debug("取 QApplication 失败（降级为无应用级收口）", exc_info=True)
            return
        if app is None:
            return
        try:
            app.aboutToQuit.connect(self._on_app_about_to_quit)
            self._quit_app = app
        except Exception:
            logger.debug("aboutToQuit 挂接失败（忽略）", exc_info=True)

    def _on_app_about_to_quit(self) -> None:
        """应用即将退出：停线程 + 停 node 子进程（幂等）。"""
        if self._quit_handled:
            return
        self._quit_handled = True
        app = self._quit_app
        self._quit_app = None
        if app is not None:
            try:
                app.aboutToQuit.disconnect(self._on_app_about_to_quit)
            except Exception:
                logger.debug("aboutToQuit 断连失败（忽略）", exc_info=True)
        self.shutdown()
