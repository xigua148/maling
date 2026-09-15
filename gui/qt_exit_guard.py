# -*- coding: utf-8 -*-
"""qt_exit_guard.py —— 持线程类的「应用退出自我收口」公共基类（v2.2 横扫批）。

背景（机制与 ``gui/widgets/kb_worker.py`` 的 v2.1 #281 修法完全相同）：
若应用在 ``QThread`` 仍在运行时退出，且该线程被**父控件析构连坐**或**最后一个
Python 引用被丢弃**，Qt 会在析构「仍在运行的 QThread」时触发
``QThread: Destroyed while thread is still running`` 并进而
**Windows fail-fast ``0xC0000409``**（既存缺陷，实测复现见 ``_fix_exitcrash/``）。

自包含停机契约（**两条**挂载点，均不依赖 ``gui/main.py`` 停机编排）：
  ① ``QApplication.aboutToQuit``（真实应用经 ``main.py`` 的 ``app.exec()`` 退出时触发）
     → ``stop()``（**幂等** + **有界** ``wait``）→ 超时仍未结束则 ``setParent(None)``
     detach + 强引用防 GC（**不** ``terminate()``）；
  ② 父控件 ``destroyed`` 信号（Qt 语义：父对象析构时**先 emit destroyed，再删子对象**）
     → ``stop()``。②覆盖不经 ``aboutToQuit`` 的拆除路径（父控件被直接销毁 / 宿主未跑
     ``app.exec()``）。无父控件（``parent=None`` 的纯逻辑 worker）时②自动跳过。

为何抽成基类：本仓库既有 ``kb_worker`` / ``page_tavern`` 为**逐类 inline 副本**（机制
一致）；本批新增 5 个持线程类，若继续逐类复制将产出约 250 行同构样板，故统一收口于此。
既有两处 inline 实现保持不变（已各自验证，改动零收益、纯风险）。
"""
from __future__ import annotations

import logging

from gui.qt_compat import QApplication, QObject, QThread

logger = logging.getLogger("maid_coder.gui")

#: 退出超时仍未结束、已被 detach（脱离父子关系）的线程强引用集合。
#: 持强引用防 GC，令其能自然结束并自回收（对齐 ``kb_worker._ORPHANED``）。
_ORPHANED: "set" = set()


class ExitSafeQThread(QThread):
    """带「应用退出自我收口」的 ``QThread`` 基类。

    子类 ``__init__`` 只需 ``super().__init__(parent)``；收口自动就绪。
    仍可覆写 ``stop()`` 以叠加协作取消（例如置 ``threading.Event``），但**必须**
    保持幂等与有界（调用 ``super().stop(...)`` 复用有界 ``wait``）。
    """

    #: 退出时对线程的**有界**等待上界（ms）。硬上界保证退出**绝不无限阻塞**。
    _QUIT_WAIT_MS = 2000

    def __init__(self, parent: "QObject | None" = None):
        super().__init__(parent)
        self._quit_handled = False     # aboutToQuit 自我收口幂等闸
        self._quit_app = None          # 已挂接的 QApplication（结束时断连，防悬挂连接）
        # 自然结束 → 解除退出挂接（防连接堆积 + 引用泄漏）
        self.finished.connect(self._on_finished)
        self._arm_about_to_quit()
        self._arm_parent_destroyed(parent)

    # ------------------------------------------------------------------
    # 挂载
    # ------------------------------------------------------------------
    def _arm_about_to_quit(self) -> None:
        """挂 ``QApplication.aboutToQuit``；无 QApplication 实例（无 GUI 测试）时静默降级。"""
        try:
            app = QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(self._on_app_about_to_quit)
                self._quit_app = app
        except Exception:
            logger.debug("%s aboutToQuit 挂接失败（降级为无应用级收口）",
                         type(self).__name__, exc_info=True)

    def _arm_parent_destroyed(self, parent: "QObject | None") -> None:
        """挂父控件 ``destroyed``；``parent`` 非 QObject 时跳过。"""
        if not isinstance(parent, QObject):
            return
        try:
            parent.destroyed.connect(self._on_parent_destroyed)
        except (TypeError, RuntimeError):
            logger.debug("%s 父控件 destroyed 挂接失败", type(self).__name__, exc_info=True)

    def _disconnect_app_quit(self) -> None:
        """解除 ``aboutToQuit`` 挂接（幂等；对象已销毁时忽略）。"""
        app = self._quit_app
        self._quit_app = None
        if app is None:
            return
        try:
            app.aboutToQuit.disconnect(self._on_app_about_to_quit)
        except (TypeError, RuntimeError):
            logger.debug("%s aboutToQuit 断连失败（忽略）", type(self).__name__, exc_info=True)

    # ------------------------------------------------------------------
    # 停机
    # ------------------------------------------------------------------
    def stop(self, wait_ms: "int | None" = None) -> bool:
        """幂等停机：**有界**等待线程结束。

        - ``wait_ms=None`` → 用 ``_QUIT_WAIT_MS``；``<=0`` → 不等待，直接返回。
        - 返回 ``True``=线程已结束；``False``=超时仍在运行（调用方应 detach 兜底）。
        - 可重复调用；**从不**无限阻塞。
        """
        if not self.isRunning():
            return True
        budget = self._QUIT_WAIT_MS if wait_ms is None else int(wait_ms)
        if budget <= 0:
            return False
        try:
            return bool(self.wait(budget))
        except (RuntimeError, TypeError):
            logger.debug("%s wait 失败（对象可能已销毁）", type(self).__name__, exc_info=True)
            return False

    def _detach(self) -> None:
        """脱离父子关系 + 强引用防 GC（交进程退出时自然收尾；**不** terminate）。"""
        try:
            self.setParent(None)
            _ORPHANED.add(self)
            self.finished.connect(lambda w=self: _ORPHANED.discard(w))
        except (RuntimeError, TypeError):
            logger.debug("%s 退出 detach 失败（对象可能已销毁）",
                         type(self).__name__, exc_info=True)

    # ------------------------------------------------------------------
    # 槽
    # ------------------------------------------------------------------
    def _on_finished(self) -> None:
        """线程自然结束：解除退出挂接（幂等）。"""
        self._disconnect_app_quit()

    def _on_app_about_to_quit(self) -> None:
        """应用即将退出：自我收口（幂等）。超时则 detach 兜底。"""
        if self._quit_handled:
            return
        self._quit_handled = True
        self._disconnect_app_quit()
        if not self.stop():
            self._detach()

    def _on_parent_destroyed(self, *_args) -> None:
        """父控件析构中：抢在「连坐删除子线程」之前**有界**停机（幂等）。"""
        self.stop()
