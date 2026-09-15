"""kb_dialog.py —— 知识库最小可用对话框（v1.5.0）

审计结论（docs/audit-功能真实性清单-2026-09-07.md #C1）：KnowledgeBase 能力本体
（index_directory / search / status）实测可用，但 GUI 全树零引用 —— 空壳。
本对话框补上 GUI 入口：选目录建索引 + 关键词检索（top3：路径 + 摘要）。

后端：helpers.KnowledgeBase（helpers.py:363 search），索引文件沿用
AppConfig.kb_index_file（默认 cwd/kb_index.json，与 CLI /kb 同一份）。
"""

from __future__ import annotations

import logging
from pathlib import Path

from gui.qt_compat import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QPlainTextEdit, QFileDialog, Qt,
)
from gui import icons
from gui import motion
from gui.widgets.kb_worker import KbIndexWorker, KbSearchWorker

try:
    from gui.utils import theme_color
except Exception:  # 主题工具缺失时对话框仍可用（内置兜底色）
    theme_color = None

logger = logging.getLogger("maid_coder.gui")

#: 状态文案的**文字节奏**（省略号循环）；融入度合规形态（非几何母题），
#: 见 `_spec_loading_motion.md §10` / `MEMORY.md §七`。
_BUSY_DOTS = ("", ".", "..", "...")
#: 循环周期（ms）；`motion.loop()` 会夹取到 [800, 1600] → 4 拍 ≈ 400ms/拍。
_BUSY_PERIOD_MS = 1600

#: 已脱离对话框、仍在后台收尾的 worker 强引用（防"销毁运行中线程"崩溃 / 防 GC）。
_DETACHED_WORKERS: "set" = set()


def _reap_worker(worker) -> None:
    """worker 自然结束：解除强引用（`finished → deleteLater` 已在创建时接好）。"""
    _DETACHED_WORKERS.discard(worker)


def _detach_worker(worker) -> None:
    """对话框销毁前 worker 仍在跑：**脱离父子关系**并持强引用，待其自然结束自回收。

    避免"销毁运行中的 QThread"这一 Qt 未定义行为（不用 `terminate()`）；
    信号已在 `_shutdown_worker` 中先行断连 → 不会再回写已销毁控件。
    """
    try:
        worker.setParent(None)
    except Exception:
        pass
    _DETACHED_WORKERS.add(worker)
    worker.finished.connect(lambda w=worker: _reap_worker(w))


class KnowledgeBaseDialog(QDialog):
    """知识库：选目录 → 建立索引 → 检索（最小可用，不做大页面）。"""

    def __init__(self, app_ctx, parent=None):
        super().__init__(parent or None)
        self.app_ctx = app_ctx
        self.setWindowTitle("码铃 · 知识库")
        self.resize(560, 420)
        self._kb = None

        self._accent = self._tc("accent", "#FF6B9D")
        self._bg = self._tc("bg_card", "#FFFFFF")
        self._border = self._tc("border", "#FFE4E1")
        self._text = self._tc("text", "#5D4037")
        self._text2 = self._tc("text_secondary", "#888888")

        self.setStyleSheet(
            f"QDialog {{ background: {self._tc('bg', '#FFF5F5')}; }}"
            f"QLabel {{ color: {self._text}; }}"
            f"QLineEdit, QPlainTextEdit {{"
            f"  background: {self._bg}; color: {self._text};"
            f"  border: 1px solid {self._border}; border-radius: 8px; padding: 6px;"
            f"}}"
            f"QPushButton {{"
            f"  background: {self._bg}; color: {self._accent};"
            f"  border: 1px solid {self._accent}; border-radius: 8px; padding: 6px 14px;"
            f"}}"
            # hover 换 bg_light（随主题翻转的软填充）→ 显式补配对文字色 text；
            # 原依赖基规则 color（本处是 accent 填充色当字色），在浅色档
            # bg_light 上只有 1.931/2.783/2.814。
            f"QPushButton:hover {{ background: {self._tc('bg_light', '#FFF0F3')};"
            f" color: {self._text}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title = QLabel(f"{icons.text_glyph('menu_book', '📚')} 本地知识库")
        f = title.font()
        f.setBold(True)
        title.setFont(f)
        layout.addWidget(title)

        # -- 第一行：目录选择 + 建立索引 --
        dir_row = QHBoxLayout()
        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText("选择要索引的文件夹（.md/.txt/.py 等）")
        dir_row.addWidget(self.dir_edit, 1)
        pick_btn = QPushButton(f"{icons.text_glyph('folder', '📁')} 选目录")
        pick_btn.clicked.connect(self._on_pick_dir)
        dir_row.addWidget(pick_btn)
        self.index_btn = QPushButton(f"{icons.text_glyph('search', '🔍')} 建立索引")
        self.index_btn.clicked.connect(self._on_index)
        dir_row.addWidget(self.index_btn)
        layout.addLayout(dir_row)

        # -- 第二行：搜索框 --
        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("输入关键词检索知识库…")
        self.search_edit.returnPressed.connect(self._on_search)
        search_row.addWidget(self.search_edit, 1)
        self.search_btn = QPushButton("搜索")
        self.search_btn.clicked.connect(self._on_search)
        search_row.addWidget(self.search_btn)
        layout.addLayout(search_row)

        # -- 结果区 --
        self.result_view = QPlainTextEdit()
        self.result_view.setReadOnly(True)
        self.result_view.setMinimumHeight(180)
        layout.addWidget(self.result_view, 1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {self._text2}; font-size: 12px;")
        layout.addWidget(self.status_label)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

        # 初始化后端（失败不崩，状态栏提示）
        self._init_kb()
        self._refresh_status()

        # -- 异步任务状态（批 1：建索引 / 检索移入 QThread）--
        self._worker = None          # 当前在跑的 worker（同一时刻至多一个）
        self._busy = False           # 是否有任务进行中（按钮置灰 + 防重入）
        self._busy_handle = None     # motion.loop() 句柄（文字节奏）
        self._busy_text = ""         # 进行中文案主体（省略号循环拼接）
        self._pending_query = ""     # 检索发起时的查询词（回填"未找到"文案用）

    # ------------------------------------------------------------------
    def _tc(self, key: str, fallback: str) -> str:
        if theme_color is None:
            return fallback
        try:
            return str(theme_color(self.app_ctx, key, fallback))
        except Exception:
            return fallback

    def _index_file(self) -> str:
        """索引文件路径（与 CLI /kb 同一份）：AppConfig.kb_index_file，缺省 cwd/kb_index.json。"""
        cfg = getattr(self.app_ctx, "cfg", None)
        return str(getattr(cfg, "kb_index_file", "") or "kb_index.json")

    def _init_kb(self) -> None:
        """按 AppConfig.kb_index_file（缺省 cwd/kb_index.json）实例化 KnowledgeBase。"""
        try:
            from helpers import KnowledgeBase
            self._kb = KnowledgeBase(self._index_file())
        except Exception as exc:
            self._kb = None
            logger.warning("KnowledgeBase 初始化失败: %s", exc)
            self.status_label.setText(f"知识库初始化失败：{exc}")

    def _refresh_status(self) -> None:
        if self._kb is not None:
            try:
                self.status_label.setText(self._kb.status())
            except Exception:
                pass

    # ------------------------------------------------------------------
    def _on_pick_dir(self) -> None:
        start = self.dir_edit.text().strip() or str(Path.cwd())
        chosen = QFileDialog.getExistingDirectory(self, "选择要索引的目录", start)
        if chosen:
            self.dir_edit.setText(chosen)

    # ------------------------------------------------------------------
    # 进行中反馈（文字节奏，融入度合规；off 档回落静态文案）
    # ------------------------------------------------------------------
    def _start_busy(self, text: str) -> None:
        """点击后**立即**：按钮置灰 + 出现进度提示（文案，不空白）。"""
        self._busy = True
        self._busy_text = text
        self.index_btn.setEnabled(False)
        self.search_btn.setEnabled(False)
        # 先落静态文案，保证"立即出现提示"（即使随后被 tick 覆盖）
        self.status_label.setText(f"{text}…")
        handle = motion.loop(
            self, self._on_busy_tick,
            period_ms=_BUSY_PERIOD_MS, on_disabled=self._on_busy_disabled,
        )
        if handle is None:
            return                       # off 档 / 系统关动画 → 保留静态文案
        self._busy_handle = handle

    def _stop_busy(self) -> None:
        """任务终态：停循环 + 恢复按钮（失败后仍可重试）。"""
        handle = self._busy_handle
        self._busy_handle = None
        if handle is not None:
            motion.stop_loop(handle)     # 显式停止：不触发 on_disabled
        self._busy = False
        self._busy_text = ""
        self.index_btn.setEnabled(True)
        self.search_btn.setEnabled(True)

    def _on_busy_tick(self, progress: float) -> None:
        idx = int(progress * len(_BUSY_DOTS))
        if idx >= len(_BUSY_DOTS):
            idx = len(_BUSY_DOTS) - 1
        self.status_label.setText(self._busy_text + _BUSY_DOTS[idx])

    def _on_busy_disabled(self) -> None:
        """因禁用而停（档位切 off / 系统关动画 / stop_all）→ 切静态文案，不得空白。"""
        self._busy_handle = None
        if self._busy:
            self.status_label.setText(f"{self._busy_text}…")

    # ------------------------------------------------------------------
    # 建索引 / 检索（批 1：移入 QThread，GUI 不再冻结）
    # ------------------------------------------------------------------
    def _on_index(self) -> None:
        directory = self.dir_edit.text().strip()
        if not directory:
            self.status_label.setText("请先选择要索引的目录。")
            return
        if self._busy:
            return
        if self._kb is None:
            self._init_kb()
            if self._kb is None:
                return
        worker = KbIndexWorker(self._index_file(), directory, self)
        self._launch_worker(worker, "正在建立索引")

    def _on_search(self) -> None:
        query = self.search_edit.text().strip()
        if not query:
            self.status_label.setText("请输入检索关键词。")
            return
        if self._busy:
            return
        if self._kb is None:
            self._init_kb()
            if self._kb is None:
                return
        self._pending_query = query
        worker = KbSearchWorker(self._index_file(), query, 3, self)
        self._launch_worker(worker, "检索中")

    def _launch_worker(self, worker, busy_text: str) -> None:
        worker.ok.connect(self._on_worker_ok)
        worker.failed.connect(self._on_worker_failed)
        worker.cancelled.connect(self._on_worker_cancelled)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        self._start_busy(busy_text)
        worker.start()

    # ----- 信号回填（均经 sender 身份校验，丢弃陈旧信号）-----
    def _on_worker_ok(self, payload) -> None:
        worker = self.sender()
        if worker is not self._worker:
            return
        self._worker = None
        self._stop_busy()
        if isinstance(worker, KbIndexWorker):
            self._init_kb()              # worker 独占写盘后，UI 侧重载以取新状态
            self.result_view.setPlainText(str(payload))
        else:
            results = payload or []
            if not results:
                self.result_view.setPlainText(
                    f"未找到与「{self._pending_query}」相关的内容。\n（可先对文档目录「建立索引」）"
                )
            else:
                lines = [f"{icons.text_glyph('menu_book', '📚')} 检索结果（Top {len(results)}）："]
                for path, chunk, score in results:
                    lines.append("")
                    lines.append(f"[{path}]（相关度 {score:.3f}）")
                    lines.append(f"  {chunk[:300]}")
                self.result_view.setPlainText("\n".join(lines))
        self._refresh_status()

    def _on_worker_failed(self, msg: str) -> None:
        worker = self.sender()
        if worker is not self._worker:
            return
        self._worker = None
        self._stop_busy()
        kind = "建立索引失败" if isinstance(worker, KbIndexWorker) else "检索失败"
        self.result_view.setPlainText(f"{kind}：{msg}")
        self._refresh_status()

    def _on_worker_cancelled(self) -> None:
        worker = self.sender()
        if worker is not self._worker:
            return
        self._worker = None
        self._stop_busy()
        self._refresh_status()

    # ------------------------------------------------------------------
    # 关闭：**先断连再取消**（不 terminate），不向已销毁控件发信号
    # ------------------------------------------------------------------
    def _shutdown_worker(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            for sig, slot in (
                (worker.ok, self._on_worker_ok),
                (worker.failed, self._on_worker_failed),
                (worker.cancelled, self._on_worker_cancelled),
            ):
                try:
                    sig.disconnect(slot)
                except (TypeError, RuntimeError):
                    pass
            try:
                worker.cancel()
            except Exception:
                pass
            if worker.isRunning():
                _detach_worker(worker)   # 脱离父子关系 + 强引用，待其自然结束自回收
        self._stop_busy()

    def done(self, result: int) -> None:  # noqa: N802
        # accept()/reject()/closeEvent 的唯一收口点
        self._shutdown_worker()
        super().done(result)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._shutdown_worker()
        super().closeEvent(event)
