# -*- coding: utf-8 -*-
"""kb_worker.py —— 知识库建索引 / 检索的 QThread 工作线程（v2.x / 批 1）。

背景（``_eval_loading_async.md`` §1）：``kb_dialog`` 的建索引与检索原先在 GUI 线程
**同步**执行，实测冻结事件循环 57.7ms（建索引）/ 313.8ms（检索，1000 文件达 1049ms），
表现为"点下去卡住无反馈"。本模块把这两段移到 ``QThread`` 子类，对齐仓库既有惯用法
``gui/widgets/voice_input.py:68 _RecognitionWorker``。

契约（设计文档 §2.3 / §2.4）：
  · 只传不可变/可拷贝数据（``str`` / ``int`` / ``list[tuple]``）；**绝不**跨线程传控件或
    ``KnowledgeBase`` 实例；
  · ``KnowledgeBase`` 实例由 worker 在 ``run()`` 内**新建并独占**，UI 线程在任务期不并发访问；
  · ``run()`` 整体 ``try/except``，异常经 ``failed`` 回传，**绝不**跨线程抛出；
  · **协作式取消**：``cancel()`` / ``stop()`` 置 ``threading.Event``，``run()`` 在可检查点
    退出并发 ``cancelled``；**不使用** ``QThread.terminate()``；
  · 零新增运行时第三方依赖（仅 PySide6 内置 + 标准库 ``threading``）。

应用退出自我收口（v2.1 修复 #281）：
  worker 在构造时挂 ``QApplication.aboutToQuit`` → 应用退出时 ``stop()``（幂等取消 + 有界
  ``wait()``）+ 必要时 ``setParent(None)`` detach。**自包含**：不依赖任何外部停机链路，
  故无需改动 ``gui/main.py`` 停机编排等保护文件。修复的是评测指出的真实缺陷——若应用在
  建索引/检索运行中退出（不经过对话框 ``closeEvent``），父窗被销毁时会连带销毁仍在运行的
  子 ``QThread``，触发 ``QThread: Destroyed while thread is still running`` 并进而
  **Windows fail-fast 0xC0000409 崩溃**（实测复现，见 ``_probe_kb_exit.py``）。

取消粒度说明（**已知取舍**）：``helpers.KnowledgeBase.index_directory/search`` 为单次
阻塞调用，不暴露取消钩子（给其加 ``should_cancel`` 属设计文档「批 2」，本阶段未批准）→
取消只能落在"调用前 / 调用后"两个检查点。若取消发生在调用进行中，worker 仍会跑完该次
调用，但**丢弃结果**（发 ``cancelled`` 而非 ``ok``）并随即 ``finished → deleteLater``
自回收（**不泄漏线程**，对齐 ``voice_input._shutdown_worker`` 的既有取舍）。
"""
from __future__ import annotations

import logging
import threading

from gui.qt_compat import QThread, Signal

logger = logging.getLogger("maid_coder.gui")

#: ``index_directory`` 返回消息里携带的 ANSI 色码（GUI 显示前粗略去除）
_ANSI_CODES = ("\033[92m", "\033[93m", "\033[0m")

#: 退出超时仍未结束、已被 detach（脱离父子关系）的 worker 强引用集合。
#: 持强引用防 GC，令其能自然结束并自回收（对齐 ``kb_dialog._DETACHED_WORKERS``）。
_ORPHANED: "set" = set()


def _strip_ansi(msg: str) -> str:
    out = str(msg)
    for code in _ANSI_CODES:
        out = out.replace(code, "")
    return out


class _KbWorkerBase(QThread):
    """公共基类：取消标志 + 退出自我收口 + 统一信号集合。"""

    #: (已处理, 总数)；helpers 不暴露粒度进度（批 2 前置）→ 仅在启动时发一次占位。
    #: R-A：**不上屏数字**，仅供内部/测试判断"任务已启动"。
    progress = Signal(int, int)
    #: 成功：``str``（建索引消息，已去 ANSI）或 ``list[tuple]``（检索结果，纯数据）
    ok = Signal(object)
    #: 失败：错误描述（绝不跨线程抛异常）
    failed = Signal(str)
    #: 用户取消（正常终态，非错误）
    cancelled = Signal()

    #: 应用退出时对 worker 的**有界**等待上界（ms）。建索引/检索最坏实测 ~1.05s
    #: （1000 文件），2.0s 留约 2× 余量；硬上界保证退出**绝不无限阻塞**。
    _QUIT_WAIT_MS = 2000

    def __init__(self, index_file: str, parent=None):
        super().__init__(parent)
        self._index_file = index_file
        self._cancel = threading.Event()
        self._quit_handled = False     # aboutToQuit 自我收口幂等闸
        self._quit_app = None          # 已挂接的 QApplication（结束时断连，防悬挂连接）
        # 自然结束 → 解除退出挂接（防连接堆积 + 引用泄漏）；须先于 dialog 的 deleteLater
        self.finished.connect(self._on_finished)
        self._connect_app_quit()

    # ------------------------------------------------------------------
    # 应用级退出自我收口（自包含，不触碰保护文件）
    # ------------------------------------------------------------------
    def _connect_app_quit(self) -> None:
        """挂 ``QApplication.aboutToQuit``：应用退出时自我收口。

        无 QApplication 实例（如无 GUI 的单元测试）时静默降级为"无应用级收口"。
        """
        try:
            from gui.qt_compat import QApplication
            app = QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(self._on_app_about_to_quit)
                self._quit_app = app
        except Exception:
            logger.debug("KB worker aboutToQuit 挂接失败（降级为无应用级收口）", exc_info=True)

    def _disconnect_app_quit(self) -> None:
        """解除 ``aboutToQuit`` 挂接（幂等；对象已销毁时忽略）。"""
        app = self._quit_app
        self._quit_app = None
        if app is None:
            return
        try:
            app.aboutToQuit.disconnect(self._on_app_about_to_quit)
        except (TypeError, RuntimeError):
            logger.debug("KB worker aboutToQuit 断连失败（忽略）", exc_info=True)

    def _on_finished(self) -> None:
        """线程自然结束：解除退出挂接（幂等）。"""
        self._disconnect_app_quit()

    def _on_app_about_to_quit(self) -> None:
        """应用即将退出：自我收口（幂等）。

        顺序：请求取消 → **有界** ``wait`` → 超时仍未结束则 ``setParent(None)`` detach
        （脱离父子关系 + 强引用），避免父窗（对话框）被销毁时连带销毁运行中的
        ``QThread``（崩溃根因）。重复 emit ``aboutToQuit`` 无害。
        """
        if self._quit_handled:
            return
        self._quit_handled = True
        self._disconnect_app_quit()
        if not self.stop():
            # 超时：脱离父子关系，交进程退出时自然收尾（**不** terminate）
            try:
                self.setParent(None)
                _ORPHANED.add(self)
                self.finished.connect(lambda w=self: _ORPHANED.discard(w))
            except (RuntimeError, TypeError):
                logger.debug("KB worker 退出 detach 失败（对象可能已销毁）", exc_info=True)

    # ------------------------------------------------------------------
    # 取消 / 停机（均幂等，可从 UI 线程调用）
    # ------------------------------------------------------------------
    def cancel(self) -> None:
        """请求取消（协作式）；幂等，可从 UI 线程调用。"""
        self._cancel.set()

    def stop(self, wait_ms: int | None = None) -> bool:
        """幂等停机：请求取消 + **有界**等待线程结束。

        - ``wait_ms=None`` → 用 ``_QUIT_WAIT_MS``；``<=0`` → 不等待，直接返回。
        - 返回 ``True``=线程已结束；``False``=超时仍在运行（调用方应 detach 兜底）。
        - 可重复调用；**从不**无限阻塞。
        """
        self._cancel.set()
        if not self.isRunning():
            return True
        budget = self._QUIT_WAIT_MS if wait_ms is None else int(wait_ms)
        if budget <= 0:
            return False
        try:
            return bool(self.wait(budget))
        except (RuntimeError, TypeError):
            logger.debug("KB worker wait 失败（对象可能已销毁）", exc_info=True)
            return False

    def is_cancelled(self) -> bool:
        """是否已请求取消（测试用）。"""
        return self._cancel.is_set()


class KbIndexWorker(_KbWorkerBase):
    """建索引 worker：独占一个 ``KnowledgeBase``，调用 ``index_directory``。"""

    def __init__(self, index_file: str, directory: str, parent=None):
        super().__init__(index_file, parent)
        self._directory = directory

    def run(self) -> None:
        try:
            if self._cancel.is_set():
                self.cancelled.emit()
                return
            from helpers import KnowledgeBase

            kb = KnowledgeBase(self._index_file)   # 独占，任务期 UI 不触碰
            self.progress.emit(0, 0)               # 占位：无粒度进度（见模块 docstring）
            msg = kb.index_directory(self._directory)
            if self._cancel.is_set():
                self.cancelled.emit()
                return
            self.ok.emit(_strip_ansi(msg))
        except Exception as exc:
            if self._cancel.is_set():
                self.cancelled.emit()
                return
            self.failed.emit(f"{type(exc).__name__}：{exc}")


class KbSearchWorker(_KbWorkerBase):
    """检索 worker：独占一个 ``KnowledgeBase``，调用 ``search``。"""

    def __init__(self, index_file: str, query: str, top_k: int = 3, parent=None):
        super().__init__(index_file, parent)
        self._query = query
        self._top_k = top_k

    def run(self) -> None:
        try:
            if self._cancel.is_set():
                self.cancelled.emit()
                return
            from helpers import KnowledgeBase

            kb = KnowledgeBase(self._index_file)   # 独占，任务期 UI 不触碰
            self.progress.emit(0, 0)
            results = kb.search(self._query, top_k=self._top_k)
            if self._cancel.is_set():
                self.cancelled.emit()
                return
            self.ok.emit(list(results))
        except Exception as exc:
            if self._cancel.is_set():
                self.cancelled.emit()
                return
            self.failed.emit(f"{type(exc).__name__}：{exc}")
