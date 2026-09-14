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
  · **协作式取消**：``cancel()`` 置 ``threading.Event``，``run()`` 在可检查点退出并发
    ``cancelled``；**不使用** ``QThread.terminate()``；
  · 零新增运行时第三方依赖（仅 PySide6 内置 + 标准库 ``threading``）。

取消粒度说明（**已知取舍**）：``helpers.KnowledgeBase.index_directory/search`` 为单次
阻塞调用，不暴露取消钩子（给其加 ``should_cancel`` 属设计文档「批 2」，本阶段未批准）→
取消只能落在"调用前 / 调用后"两个检查点。若取消发生在调用进行中，worker 仍会跑完该次
调用，但**丢弃结果**（发 ``cancelled`` 而非 ``ok``）并随即 ``finished → deleteLater``
自回收（**不泄漏线程**，对齐 ``voice_input._shutdown_worker`` 的既有取舍）。
"""
from __future__ import annotations

import threading

from gui.qt_compat import QThread, Signal

#: ``index_directory`` 返回消息里携带的 ANSI 色码（GUI 显示前粗略去除）
_ANSI_CODES = ("\033[92m", "\033[93m", "\033[0m")


def _strip_ansi(msg: str) -> str:
    out = str(msg)
    for code in _ANSI_CODES:
        out = out.replace(code, "")
    return out


class _KbWorkerBase(QThread):
    """公共基类：取消标志 + 统一信号集合。"""

    #: (已处理, 总数)；helpers 不暴露粒度进度（批 2 前置）→ 仅在启动时发一次占位。
    #: R-A：**不上屏数字**，仅供内部/测试判断"任务已启动"。
    progress = Signal(int, int)
    #: 成功：``str``（建索引消息，已去 ANSI）或 ``list[tuple]``（检索结果，纯数据）
    ok = Signal(object)
    #: 失败：错误描述（绝不跨线程抛异常）
    failed = Signal(str)
    #: 用户取消（正常终态，非错误）
    cancelled = Signal()

    def __init__(self, index_file: str, parent=None):
        super().__init__(parent)
        self._index_file = index_file
        self._cancel = threading.Event()

    def cancel(self) -> None:
        """请求取消（协作式）；幂等，可从 UI 线程调用。"""
        self._cancel.set()

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
