"""gui/tray_manager.py —— v1.3 P1-3 app 级单一系统托盘（共享知识 14：全 app 只允许一个图标）

设计（docs/design-v13.md D-V13-01 / D-V13-10 / D-V13-11，P1-3 最小形态）：
  - app 级唯一 QSystemTrayIcon，自 P1-3 起由 TrayManager 所有；
    chat_window 既有托盘经一行守卫退避（_setup_tray 顶部 return），零删除零改写。
  - P1-3 最小菜单：显示/隐藏主窗 + ❌ 退出（P2-4 再扩为完整动作集）。
  - tooltip = 心情语境一句 + 提示（无数值）；A9 静默气泡挂载点（proactive_message）。
  - quit 单一编舞（D-V13-11）：❌ 退出 → app_ctx.quitting=True → 保存几何 + chat
    shutdown + 隐藏图标 + QApplication.quit()；主窗 closeEvent 不再承担 app 退出。
"""
from __future__ import annotations

import logging
from typing import Optional

from gui.qt_compat import (
    QObject, QSystemTrayIcon, QMenu, QAction, QApplication, QIcon, QMessageBox,
)
from gui.utils import get_resource_path
from gui import icons

logger = logging.getLogger("maid_coder.gui")


def app_tray_exists(app_ctx) -> bool:
    """chat_window._setup_tray 守卫：app 级托盘已存在则不建第二个图标（D-V13-10）。"""
    return getattr(app_ctx, "tray_manager", None) is not None


class TrayManager(QObject):
    """系统托盘唯一管理者：图标 + 最小菜单 + mood tooltip + A9 静默气泡。"""

    def __init__(self, app_ctx, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.app_ctx = app_ctx
        self._icon: Optional[QSystemTrayIcon] = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._build_icon()
        else:
            logger.info("系统托盘不可用，托盘驻留/退出入口降级（主窗 X 将保持直退）")
        self._connect_broadcasts()

    # ------------------------------------------------------------------
    def _build_icon(self) -> None:
        try:
            icon = QIcon(str(get_resource_path("assets/maling.ico")))
            if icon.isNull():
                icon = QIcon()
        except Exception:
            icon = QIcon()
        tray = QSystemTrayIcon(icon, self)
        tray.setToolTip("码铃")
        # QMenu 的 parent 必须是 QWidget——TrayManager 是 QObject 不能作 parent，
        # 用无 parent 菜单 + self._menu 强引用防 GC（PySide 陷阱：菜单 Python 引用
        # 丢失会在弹出瞬间异常退出）
        menu = QMenu()
        self._menu = menu
        show_action = QAction("显示 / 隐藏主窗", menu)
        show_action.triggered.connect(self.toggle_main_window)
        menu.addAction(show_action)
        menu.addSeparator()

        # ---- v1.3(P2-4): 完整动作集（经 main_window 动作桥，getattr 守卫；主窗未建时禁用）----
        mw_ok = getattr(self.app_ctx, "main_window", None) is not None

        def _bridge(method_name: str):
            """构造一个动作回调：主窗/方法缺失时静默跳过（getattr 守卫）。"""
            def _run() -> None:
                mw = getattr(self.app_ctx, "main_window", None)
                if mw is not None and hasattr(mw, method_name):
                    try:
                        getattr(mw, method_name)()
                    except Exception as exc:
                        logger.warning("托盘动作 %s 执行失败: %s", method_name, exc)
            return _run

        camera_action = QAction(f"{icons.text_glyph('camera', '📷')} 拍照", menu)
        camera_action.triggered.connect(_bridge("trigger_camera"))
        camera_action.setEnabled(mw_ok)
        camera_action.setToolTip("调起摄像头拍一张发给码铃")
        menu.addAction(camera_action)

        voice_action = QAction(f"{icons.text_glyph('voice', '🎤')} 语音输入", menu)
        voice_action.triggered.connect(_bridge("trigger_voice"))
        voice_action.setEnabled(mw_ok)
        voice_action.setToolTip("打开一次语音输入（识别结果填入输入框）")
        menu.addAction(voice_action)

        shot_action = QAction(f"{icons.text_glyph('screenshot', '🖼')} 截图提问", menu)
        shot_action.triggered.connect(_bridge("trigger_screenshot"))
        shot_action.setEnabled(mw_ok)
        shot_action.setToolTip("划屏选区截图，作为图片问码铃")
        menu.addAction(shot_action)

        # v1.4(A3): 番茄钟「她陪你专注」（独立小组件入口，controller 单例懒建；无需主窗）
        pomodoro_action = QAction("🍅 专注", menu)
        pomodoro_action.triggered.connect(self._open_pomodoro)
        pomodoro_action.setToolTip("番茄钟：25 分钟专注，她陪你")
        menu.addAction(pomodoro_action)

        menu.addSeparator()

        settings_action = QAction(f"{icons.text_glyph('settings', '⚙️')} 设置", menu)
        settings_action.triggered.connect(_bridge("navigate_settings"))
        settings_action.setEnabled(mw_ok)
        menu.addAction(settings_action)

        float_action = QAction(f"{icons.text_glyph('chat', '💬')} 聊天浮窗", menu)
        float_action.triggered.connect(_bridge("open_float_chat"))
        float_action.setEnabled(mw_ok)
        float_action.setToolTip("呼出/聚焦独立聊天浮窗")
        menu.addAction(float_action)

        menu.addSeparator()
        quit_action = QAction(f"{icons.text_glyph('close', '❌')} 退出", menu)
        quit_action.triggered.connect(self._confirm_quit)
        menu.addAction(quit_action)
        menu.addSeparator()
        # v1.4.0-勘: 菜单底部垫「禁用占位项」——Windows 托盘菜单自图标向上弹出，
        # 底部正对鼠标、右键松开会被系统当作选中该项；垫一个禁用项后，右键松开
        # 落在这里=零反应零弹窗，用户可自由浏览菜单，只有主动点击才触发动作。
        try:
            from core import __version__ as _ver
        except Exception:
            _ver = ""
        placeholder_action = QAction(f"码铃 v{_ver}", menu)
        placeholder_action.setEnabled(False)  # 禁用：不可点击、触发零反应
        menu.addAction(placeholder_action)
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_activated)
        # A9 静默气泡点击 -> 呼出主窗看完整会话
        tray.messageClicked.connect(self.show_main_window)
        self._icon = tray
        tray.show()
        self._refresh_mood_tooltip()

    def is_available(self) -> bool:
        return self._icon is not None and self._icon.isVisible()

    # ------------------------------------------------------------------
    # v1.4(A3): 番茄钟入口 + 通用静默气泡（A3/A9 复用，非 proactive 语义）
    # ------------------------------------------------------------------
    def _open_pomodoro(self) -> None:
        """打开/聚焦番茄钟浮窗（app 级单例 controller，懒建；失败不阻断）。"""
        try:
            from gui.pomodoro import open_pomodoro
            open_pomodoro(self.app_ctx)
        except Exception as exc:
            logger.warning("番茄钟打开失败: %s", exc)

    def notify_maid(self, title: str, text: str) -> None:
        """通用静默托盘气泡（到点/轻提醒用）：托盘不可用则静默跳过（不抢焦点）。"""
        if self._icon is None or not self._icon.isVisible():
            return
        head = (text or "").strip().split("\n")[0][:80]
        if not head:
            return
        try:
            self._icon.showMessage(
                (title or "码铃")[:60] or "码铃", head,
                QSystemTrayIcon.Information, 6000,
            )
        except Exception as exc:
            logger.warning("托盘静默气泡失败: %s", exc)

    def _maybe_goodnight_ritual(self) -> None:
        """v1.7(F3/D-V17-02/Q-C5): 退出编舞晚安气泡。

        - 深夜时段（23:00–5:00）∧ 当日未发过 goodnight ∧ GuiConfig
          `ritual_goodnight` 开（默认开，可关）→ notify_maid 一句晚安；
        - 一次性记账（ritual.json），错过不补，无补发队列；退出时序不适合
          写会话 → 不入会话存档（R-C：系统通知只走 notify_maid）；
        - 晚安变体按 F5 阶段取词（亲近/信赖 → 撒娇式）；
        - 任一环节失败静默，绝不阻断退出。
        """
        try:
            from datetime import datetime
            from quotations import RitualStore, goodnight_due
            from greeting import build_goodnight_line
            enabled = True
            config = getattr(self.app_ctx, "config", None)
            if config is not None:
                enabled = bool(getattr(config, "ritual_goodnight", True))
            store = getattr(self.app_ctx, "ritual_store", None)
            if store is None:
                store = RitualStore()
                try:
                    self.app_ctx.ritual_store = store
                except Exception:
                    logger.debug("静默降级：_maybe_goodnight_ritual 中忽略异常", exc_info=True)
            now = datetime.now()
            if not goodnight_due(now, store, enabled):
                return
            stage = ""
            companion = getattr(self.app_ctx, "companion", None)
            if companion is not None:
                try:
                    stage = str(companion.relation_stage_name() or "")
                except Exception:
                    stage = ""
            text = build_goodnight_line(stage)
            self.notify_maid("码铃晚安", text)
            store.mark_given("goodnight", None, now)
        except Exception as exc:
            logger.debug("晚安仪式失败（不阻断退出）: %s", exc)

    # ------------------------------------------------------------------
    # 广播接线：mood tooltip + A9 静默气泡
    # ------------------------------------------------------------------
    def _connect_broadcasts(self) -> None:
        try:
            bridge = getattr(self.app_ctx, "companion_bridge", None)
            if bridge is not None and hasattr(bridge, "mood_changed"):
                bridge.mood_changed.connect(self._on_mood_changed)
        except Exception:
            logger.debug("静默降级：_connect_broadcasts 中忽略异常", exc_info=True)
        chat_service = getattr(self.app_ctx, "chat_service", None)
        if chat_service is not None:
            try:
                chat_service.proactive_message.connect(self._on_proactive_ready)
            except Exception:
                logger.debug("静默降级：_connect_broadcasts 中忽略异常", exc_info=True)

    def _on_mood_changed(self, mood: str, reason: str) -> None:
        self._refresh_mood_tooltip()

    def _refresh_mood_tooltip(self) -> None:
        if self._icon is None:
            return
        try:
            from gui.widgets.maid_pet import mood_tooltip_text
            companion = getattr(self.app_ctx, "companion", None)
            state = None
            bridge = getattr(self.app_ctx, "companion_bridge", None)
            if bridge is not None and hasattr(bridge, "current_display"):
                try:
                    state = bridge.current_display() or None
                except Exception:
                    state = None
            text = mood_tooltip_text(companion, state)
            self._icon.setToolTip(f"{text}\n点托盘呼出码铃")
        except Exception:
            logger.debug("静默降级：_refresh_mood_tooltip 中忽略异常", exc_info=True)

    def _on_proactive_ready(self, text: str, scene: str) -> None:
        """A9 / Idle 主动消息 -> 托盘静默气泡（不抢焦点；点开呼出主窗）。"""
        if self._icon is None or not self._icon.isVisible():
            return
        head = (text or "").strip().split("\n")[0][:60]
        if not head:
            return
        try:
            self._icon.showMessage(
                "码铃 · 悄悄话", head,
                QSystemTrayIcon.Information, 6000,
            )
        except Exception:
            logger.debug("静默降级：_on_proactive_ready 中忽略异常", exc_info=True)

    # ------------------------------------------------------------------
    # 主窗显示/隐藏 + 托盘交互
    # ------------------------------------------------------------------
    def show_main_window(self) -> None:
        mw = getattr(self.app_ctx, "main_window", None)
        if mw is None:
            return
        try:
            mw.showNormal()
            mw.raise_()
            mw.activateWindow()
        except Exception:
            logger.debug("静默降级：show_main_window 中忽略异常", exc_info=True)

    def hide_main_window(self) -> None:
        mw = getattr(self.app_ctx, "main_window", None)
        if mw is None:
            return
        try:
            mw.hide()
        except Exception:
            logger.debug("静默降级：hide_main_window 中忽略异常", exc_info=True)

    def toggle_main_window(self) -> None:
        """显示/隐藏主窗（托盘菜单 + 双击 + P1-3 全局热键共用逻辑）。"""
        mw = getattr(self.app_ctx, "main_window", None)
        if mw is None:
            return
        try:
            if mw.isVisible() and not mw.isMinimized():
                mw.hide()
            else:
                mw.showNormal()
                mw.raise_()
                mw.activateWindow()
        except Exception:
            logger.debug("静默降级：toggle_main_window 中忽略异常", exc_info=True)

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_main_window()

    # ------------------------------------------------------------------
    # quit 单一编舞（D-V13-11）
    # ------------------------------------------------------------------
    def _confirm_quit(self) -> None:
        """❌ 退出二次确认：托盘菜单底部项贴近鼠标，右键松开易误触发——
        先弹确认，避免「没想退却被退出」。用户点「退出」才走真退出编舞。"""
        logger.info("QUIT-ask: 托盘退出被触发，弹确认框")
        try:
            box = QMessageBox()
            box.setWindowTitle("退出码铃？")
            box.setText("确定要退出码铃吗？\n\n退出后她就不会再主动问候你啦。")
            box.setIcon(QMessageBox.Question)
            yes_btn = box.addButton("退出", QMessageBox.AcceptRole)
            no_btn = box.addButton("再陪我一会", QMessageBox.RejectRole)
            box.setDefaultButton(no_btn)
            box.exec()
            if box.clickedButton() is not yes_btn:
                logger.info("QUIT-no: 用户选择「再陪我一会」，不退出")
                return
        except Exception as exc:
            # 确认框不可用时保守不退出（防误触目的优先；用户仍可用设置/任务管理器退出）
            logger.warning("退出确认框异常，取消退出: %s", exc)
            return
        self._on_quit()

    def _on_quit(self) -> None:
        """❌ 退出：唯一真退出入口。"""
        logger.info("QUIT-tray: 托盘「❌ 退出」确认通过，执行退出")
        try:
            self.app_ctx.quitting = True
        except Exception:
            logger.debug("静默降级：_on_quit 中忽略异常", exc_info=True)
        mw = getattr(self.app_ctx, "main_window", None)
        if mw is not None and hasattr(mw, "save_window_state"):
            try:
                mw.save_window_state()
            except Exception:
                logger.debug("静默降级：_on_quit 中忽略异常", exc_info=True)
        chat_service = getattr(self.app_ctx, "chat_service", None)
        if chat_service is not None:
            try:
                chat_service.shutdown()
            except Exception:
                logger.debug("静默降级：_on_quit 中忽略异常", exc_info=True)
        # v2.2.3(内置 SillyTavern): 停掉内置页持有的 node 子进程 —— 托盘是「唯一真退出
        # 入口」，此处漏掉就会留下孤儿 node.exe（方案 §12 验收 3）。页面侧 shutdown()
        # 幂等；主窗 closeEvent 与 QApplication.aboutToQuit 另有两道兜底。
        if mw is not None:
            _st_shutdown = getattr(mw, "shutdown_sillytavern", None)
            if callable(_st_shutdown):
                try:
                    _st_shutdown()
                except Exception:
                    logger.debug("静默降级：_on_quit 中忽略异常", exc_info=True)
        # v1.7(F3/D-V17-02/Q-C5): 深夜晚安托盘气泡（保存退出前、图标仍在时发；
        # 一次性、可关、错过不补、无气泡入会话）
        self._maybe_goodnight_ritual()
        if self._icon is not None:
            try:
                self._icon.hide()
            except Exception:
                logger.debug("静默降级：_on_quit 中忽略异常", exc_info=True)
        # 生命周期卫生：停低频定时器/监视器/热键（失败绝不阻断退出）
        for _attr, _meth in (("proactive_scheduler", "stop"),
                             ("reminder_scheduler", "stop"),
                             ("idle_monitor", "stop"),
                             ("hotkeys", "shutdown"), ("tts", "shutdown")):
            _obj = getattr(self.app_ctx, _attr, None)
            if _obj is not None and hasattr(_obj, _meth):
                try:
                    getattr(_obj, _meth)()
                except Exception:
                    logger.debug("静默降级：_on_quit 中忽略异常", exc_info=True)
        try:
            QApplication.quit()
        except Exception:
            logger.debug("静默降级：_on_quit 中忽略异常", exc_info=True)
