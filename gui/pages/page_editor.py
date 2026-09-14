"""文件编辑器页面 —— 多标签代码编辑、语法高亮、面包屑导航、状态栏。"""
from __future__ import annotations

import functools

import os
from pathlib import Path
from typing import Optional, Dict, Tuple

from gui.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QTabWidget, QShortcut, QKeySequence,
    QMessageBox, QFileDialog, Qt, QFont, QTextCharFormat,
    QColor, QApplication, QSyntaxHighlighter,
    QObject,
)

try:
    from pygments import lex
    from pygments.lexers import get_lexer_for_filename, TextLexer
    from pygments.token import Token
    from pygments.util import ClassNotFound
    PYGMENTS_AVAILABLE = True
except Exception:
    PYGMENTS_AVAILABLE = False
    lex = None  # type: ignore[assignment]
    get_lexer_for_filename = None  # type: ignore[assignment]
    TextLexer = None  # type: ignore[assignment,misc]
    Token = None  # type: ignore[assignment,misc]
    ClassNotFound = Exception  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 主题配色映射
# ---------------------------------------------------------------------------
_DARK_COLORS: Dict[str, str] = {
    "Comment": "#75715E",
    "Comment.Single": "#75715E",
    "Comment.Multiline": "#75715E",
    "Keyword": "#F92672",
    "Keyword.Constant": "#F92672",
    "Keyword.Declaration": "#66D9EF",
    "Keyword.Namespace": "#F92672",
    "Keyword.Reserved": "#F92672",
    "Keyword.Type": "#66D9EF",
    "Name": "#F8F8F2",
    "Name.Attribute": "#A6E22E",
    "Name.Builtin": "#F8F8F2",
    "Name.Builtin.Pseudo": "#66D9EF",
    "Name.Class": "#66D9EF",
    "Name.Constant": "#AE81FF",
    "Name.Decorator": "#A6E22E",
    "Name.Entity": "#F8F8F2",
    "Name.Exception": "#66D9EF",
    "Name.Function": "#A6E22E",
    "Name.Function.Magic": "#A6E22E",
    "Name.Label": "#F8F8F2",
    "Name.Namespace": "#F8F8F2",
    "Name.Other": "#F8F8F2",
    "Name.Tag": "#F92672",
    "Name.Variable": "#F8F8F2",
    "Name.Variable.Class": "#66D9EF",
    "Name.Variable.Global": "#F8F8F2",
    "Name.Variable.Instance": "#F8F8F2",
    "Name.Variable.Magic": "#F8F8F2",
    "Literal": "#AE81FF",
    "Literal.Date": "#E6DB74",
    "String": "#E6DB74",
    "String.Affix": "#E6DB74",
    "String.Backtick": "#E6DB74",
    "String.Char": "#E6DB74",
    "String.Delimiter": "#E6DB74",
    "String.Doc": "#75715E",
    "String.Double": "#E6DB74",
    "String.Escape": "#AE81FF",
    "String.Heredoc": "#E6DB74",
    "String.Interpol": "#E6DB74",
    "String.Other": "#E6DB74",
    "String.Regex": "#E6DB74",
    "String.Single": "#E6DB74",
    "String.Symbol": "#E6DB74",
    "Number": "#AE81FF",
    "Number.Bin": "#AE81FF",
    "Number.Float": "#AE81FF",
    "Number.Hex": "#AE81FF",
    "Number.Integer": "#AE81FF",
    "Number.Integer.Long": "#AE81FF",
    "Number.Oct": "#AE81FF",
    "Operator": "#F92672",
    "Operator.Word": "#F92672",
    "Punctuation": "#F8F8F2",
    "Punctuation.Marker": "#F8F8F2",
    "Generic": "#F8F8F2",
    "Generic.Deleted": "#F92672",
    "Generic.Emph": "#F8F8F2",
    "Generic.Error": "#F92672",
    "Generic.Heading": "#A6E22E",
    "Generic.Inserted": "#A6E22E",
    "Generic.Output": "#F8F8F2",
    "Generic.Prompt": "#F8F8F2",
    "Generic.Strong": "#F8F8F2",
    "Generic.Subheading": "#A6E22E",
    "Generic.Traceback": "#F92672",
    "Text": "#F8F8F2",
    "Whitespace": "#F8F8F2",
}

_LIGHT_COLORS: Dict[str, str] = {
    "Comment": "#008000",
    "Comment.Single": "#008000",
    "Comment.Multiline": "#008000",
    "Keyword": "#0000FF",
    "Keyword.Constant": "#0000FF",
    "Keyword.Declaration": "#0000FF",
    "Keyword.Namespace": "#0000FF",
    "Keyword.Reserved": "#0000FF",
    "Keyword.Type": "#0000FF",
    "Name": "#333333",
    "Name.Attribute": "#795E26",
    "Name.Builtin": "#333333",
    "Name.Builtin.Pseudo": "#267F99",
    "Name.Class": "#267F99",
    "Name.Constant": "#098658",
    "Name.Decorator": "#795E26",
    "Name.Entity": "#333333",
    "Name.Exception": "#267F99",
    "Name.Function": "#795E26",
    "Name.Function.Magic": "#795E26",
    "Name.Label": "#333333",
    "Name.Namespace": "#333333",
    "Name.Other": "#333333",
    "Name.Tag": "#0000FF",
    "Name.Variable": "#333333",
    "Name.Variable.Class": "#267F99",
    "Name.Variable.Global": "#333333",
    "Name.Variable.Instance": "#333333",
    "Name.Variable.Magic": "#333333",
    "Literal": "#098658",
    "Literal.Date": "#A31515",
    "String": "#A31515",
    "String.Affix": "#A31515",
    "String.Backtick": "#A31515",
    "String.Char": "#A31515",
    "String.Delimiter": "#A31515",
    "String.Doc": "#008000",
    "String.Double": "#A31515",
    "String.Escape": "#098658",
    "String.Heredoc": "#A31515",
    "String.Interpol": "#A31515",
    "String.Other": "#A31515",
    "String.Regex": "#A31515",
    "String.Single": "#A31515",
    "String.Symbol": "#A31515",
    "Number": "#098658",
    "Number.Bin": "#098658",
    "Number.Float": "#098658",
    "Number.Hex": "#098658",
    "Number.Integer": "#098658",
    "Number.Integer.Long": "#098658",
    "Number.Oct": "#098658",
    "Operator": "#333333",
    "Operator.Word": "#0000FF",
    "Punctuation": "#333333",
    "Punctuation.Marker": "#333333",
    "Generic": "#333333",
    "Generic.Deleted": "#A31515",
    "Generic.Emph": "#333333",
    "Generic.Error": "#A31515",
    "Generic.Heading": "#795E26",
    "Generic.Inserted": "#795E26",
    "Generic.Output": "#333333",
    "Generic.Prompt": "#333333",
    "Generic.Strong": "#333333",
    "Generic.Subheading": "#795E26",
    "Generic.Traceback": "#A31515",
    "Text": "#333333",
    "Whitespace": "#333333",
}


class CodeHighlighter(QSyntaxHighlighter):
    """基于 pygments 的语法高亮器，支持主题切换。"""

    def __init__(
        self,
        document,
        theme_engine=None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(document)
        self._lexer: Optional[object] = None
        self._theme_engine = theme_engine
        self._formats: Dict[str, QTextCharFormat] = {}
        # v1.9 A(D-V19-13/⚠-3)：明暗判断改走引擎 is_dark_effective()；
        # 引擎缺失时保守回落深色（浅色色板会由首次 theme_changed 校正）。
        self._is_dark = self._resolve_is_dark("")
        self._rebuild_formats()

        # 监听主题变更
        if self._theme_engine is not None:
            self._theme_engine.theme_changed.connect(self._on_theme_changed)

        # token → format 键的 LRU 缓存（P1-4 优化）
        self._token_resolver = functools.lru_cache(maxsize=256)(self._resolve_token)

    def _resolve_is_dark(self, theme_name: str = "") -> bool:
        """v1.9 A(D-V19-13/⚠-3)：解析当前是否深色。

        首选引擎 is_dark_effective()（含深色模式 / system / C 风格强制深色）；
        引擎不可用时，按旧值兜底：cute 曾为深色高亮预设，四风格时代统一回落 True。
        """
        engine = self._theme_engine
        if engine is not None and hasattr(engine, "is_dark_effective"):
            try:
                return bool(engine.is_dark_effective())
            except Exception:
                pass
        return True

    def _on_theme_changed(self, theme_name: str) -> None:
        self._is_dark = self._resolve_is_dark(theme_name)
        self._rebuild_formats()
        self.rehighlight()

    def _rebuild_formats(self) -> None:
        """根据当前主题重建格式映射。"""
        self._formats.clear()
        palette = _DARK_COLORS if self._is_dark else _LIGHT_COLORS
        for token_name, color_hex in palette.items():
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color_hex))
            # 粗体关键字
            if token_name.startswith("Keyword") or token_name in ("Name.Class", "Name.Function"):
                fmt.setFontWeight(QFont.Bold)
            self._formats[token_name] = fmt
        # 主题变更后清空 token 缓存
        if hasattr(self, '_token_resolver'):
            self._token_resolver.cache_clear()

    def _resolve_token(self, token_name: str) -> Optional[str]:
        """将 token 解析为格式映射中的键；未命中时回退父级 token。"""
        if token_name in self._formats:
            return token_name
        parts = token_name.split(".")
        for i in range(len(parts) - 1, 0, -1):
            parent_name = ".".join(parts[:i])
            if parent_name in self._formats:
                return parent_name
        return None

    def set_lexer_by_filename(self, filename: str) -> None:
        """根据文件名推断语言并设置词法分析器。"""
        if not PYGMENTS_AVAILABLE or get_lexer_for_filename is None:
            self._lexer = None
            return
        try:
            self._lexer = get_lexer_for_filename(filename)
        except (ClassNotFound, Exception):
            self._lexer = None

    def highlightBlock(self, text: str) -> None:
        """逐行高亮。"""
        if not PYGMENTS_AVAILABLE or self._lexer is None or lex is None:
            return
        try:
            pos = 0
            for token, value in lex(text, self._lexer):
                token_name = str(token)
                resolved_key = self._token_resolver(token_name)
                if resolved_key is not None:
                    fmt = self._formats[resolved_key]
                    length = len(value)
                    self.setFormat(pos, length, fmt)
                pos += len(value)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 单个编辑器标签页
# ---------------------------------------------------------------------------
class EditorTab(QWidget):
    """单个编辑器标签页：编辑器 + 高亮 + 文件路径 + 修改状态。"""

    def __init__(
        self,
        file_path: Optional[str],
        app_context,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.file_path = file_path
        self.app_ctx = app_context
        self._modified = False
        self._encoding = "UTF-8"
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.editor = QPlainTextEdit()
        self.editor.setObjectName("codeEditorArea")
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.editor.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.editor, 1)

        # 字体完全交给 QSS 控制

        # 语法高亮
        theme_engine = getattr(self.app_ctx, "theme_engine", None)
        self.highlighter = CodeHighlighter(self.editor.document(), theme_engine)

        if self.file_path:
            self._setup_lexer()

    def _setup_lexer(self) -> None:
        if self.file_path:
            self.highlighter.set_lexer_by_filename(self.file_path)

    def _on_text_changed(self) -> None:
        if not self._modified:
            self._modified = True
            self._update_tab_title()

    def _update_tab_title(self) -> None:
        """通知父级更新标签标题。"""
        parent = self.parent()
        if isinstance(parent, QTabWidget):
            idx = parent.indexOf(self)
            if idx >= 0:
                parent.setTabText(idx, self.tab_title())

    def tab_title(self) -> str:
        """生成标签页标题（文件名 + 修改标记）。"""
        name = self.display_name()
        if self._modified:
            return f"{name} <b>*</b>"
        return name

    def display_name(self) -> str:
        """显示文件名。"""
        if self.file_path:
            return os.path.basename(self.file_path)
        return "未命名"

    def tooltip(self) -> str:
        """标签页悬浮提示。"""
        if self.file_path:
            return self.file_path
        return "未命名文件"

    def load_file(self, path: str) -> bool:
        """加载文件内容到编辑器（仅 UTF-8）。"""
        try:
            file_size = os.path.getsize(path)
            if file_size > 500 * 1024:  # >500KB 警告
                reply = QMessageBox.warning(
                    self,
                    "文件较大",
                    f'"{os.path.basename(path)}" 大小为 {file_size / 1024:.0f} KB，打开可能卡顿，是否继续？',
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if reply == QMessageBox.No:
                    return False
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            self.editor.setPlainText(content)
            self.file_path = path
            self._modified = False
            self._encoding = "UTF-8"
            self._setup_lexer()
            self._update_tab_title()
            return True
        except UnicodeDecodeError:
            QMessageBox.warning(
                self, "编码错误",
                f'无法以 UTF-8 编码读取文件 "{os.path.basename(path)}"，请转换编码后重试。'
            )
            return False
        except Exception:
            return False

    def save_file(self) -> bool:
        """保存编辑器内容到文件。"""
        if not self.file_path:
            return False
        try:
            content = self.editor.toPlainText()
            with open(self.file_path, "w", encoding="utf-8") as f:
                f.write(content)
            self._modified = False
            self._encoding = "UTF-8"
            self._update_tab_title()
            return True
        except Exception:
            return False

    def is_modified(self) -> bool:
        return self._modified

    def encoding(self) -> str:
        return self._encoding

    def file_type(self) -> str:
        """返回文件类型描述。"""
        if not self.file_path:
            return "-"
        ext = os.path.splitext(self.file_path)[1].lower()
        mapping = {
            ".py": "Python",
            ".js": "JavaScript",
            ".ts": "TypeScript",
            ".jsx": "React JSX",
            ".tsx": "React TSX",
            ".html": "HTML",
            ".htm": "HTML",
            ".css": "CSS",
            ".scss": "SCSS",
            ".sass": "Sass",
            ".json": "JSON",
            ".xml": "XML",
            ".yaml": "YAML",
            ".yml": "YAML",
            ".toml": "TOML",
            ".md": "Markdown",
            ".rst": "reStructuredText",
            ".c": "C",
            ".cpp": "C++",
            ".cc": "C++",
            ".h": "C Header",
            ".hpp": "C++ Header",
            ".java": "Java",
            ".kt": "Kotlin",
            ".go": "Go",
            ".rs": "Rust",
            ".rb": "Ruby",
            ".php": "PHP",
            ".swift": "Swift",
            ".sh": "Shell",
            ".bash": "Bash",
            ".zsh": "Zsh",
            ".ps1": "PowerShell",
            ".sql": "SQL",
            ".dart": "Dart",
            ".lua": "Lua",
            ".r": "R",
            ".pl": "Perl",
            ".scala": "Scala",
            ".groovy": "Groovy",
            ".dockerfile": "Dockerfile",
            ".makefile": "Makefile",
            ".cmake": "CMake",
            ".vue": "Vue",
            ".svelte": "Svelte",
        }
        return mapping.get(ext, ext[1:].upper() + " 文件" if ext else "文本")

    def cursor_position(self) -> Tuple[int, int]:
        """返回当前光标 (行, 列)，1-based。"""
        cursor = self.editor.textCursor()
        return cursor.blockNumber() + 1, cursor.columnNumber() + 1


# ---------------------------------------------------------------------------
# 文件编辑器主页面
# ---------------------------------------------------------------------------
class PageEditor(QWidget):
    """文件编辑器主页面：多标签 + 面包屑 + 状态栏 + 空状态。"""

    MAX_TABS = 8

    def __init__(
        self,
        app_context,
        title: str = "编辑",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.app_ctx = app_context
        self.title = title
        self._init_ui()
        self._setup_shortcuts()

    # ------------------------------------------------------------------
    # UI 初始化
    # ------------------------------------------------------------------
    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ---------- 面包屑导航 ----------
        breadcrumb_container = QWidget()
        breadcrumb_container.setObjectName("editorBreadcrumbContainer")
        breadcrumb_layout = QHBoxLayout(breadcrumb_container)
        breadcrumb_layout.setContentsMargins(12, 6, 12, 6)
        breadcrumb_layout.setSpacing(4)

        self.breadcrumb_label = QLabel("未打开文件")
        self.breadcrumb_label.setObjectName("editorBreadcrumb")
        breadcrumb_layout.addWidget(self.breadcrumb_label)
        breadcrumb_layout.addStretch()
        main_layout.addWidget(breadcrumb_container)

        # ---------- 标签页区域 ----------
        self.tab_widget = QTabWidget()
        self.tab_widget.setObjectName("editorTabWidget")
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.setMovable(True)
        self.tab_widget.tabCloseRequested.connect(self._on_tab_close)
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        main_layout.addWidget(self.tab_widget, 1)

        # ---------- 编辑器状态栏 ----------
        self.editor_status = QWidget()
        self.editor_status.setObjectName("editorStatusBar")
        status_layout = QHBoxLayout(self.editor_status)
        status_layout.setContentsMargins(12, 4, 12, 4)
        status_layout.setSpacing(16)

        self.pos_label = QLabel("Ln 1, Col 1")
        self.pos_label.setObjectName("editorStatusLabel")
        status_layout.addWidget(self.pos_label)
        status_layout.addStretch()

        self.encoding_label = QLabel("UTF-8")
        self.encoding_label.setObjectName("editorStatusLabel")
        status_layout.addWidget(self.encoding_label)

        self.file_type_label = QLabel("-")
        self.file_type_label.setObjectName("editorStatusLabel")
        status_layout.addWidget(self.file_type_label)

        main_layout.addWidget(self.editor_status)

        # ---------- 空状态覆盖层 ----------
        self.empty_state = QWidget(self)
        self.empty_state.setObjectName("editorEmptyState")
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setAlignment(Qt.AlignCenter)

        empty_icon = QLabel("\u270E")
        empty_icon_font = QFont()
        empty_icon_font.setPointSize(48)
        empty_icon.setFont(empty_icon_font)
        empty_icon.setObjectName("editorEmptyIcon")
        empty_icon.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(empty_icon)

        empty_title = QLabel("未打开任何文件")
        empty_title_font = QFont()
        empty_title_font.setPointSize(16)
        empty_title_font.setBold(True)
        empty_title.setFont(empty_title_font)
        empty_title.setObjectName("editorEmptyTitle")
        empty_title.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(empty_title)

        empty_desc = QLabel(
            "在项目视图中双击文件即可打开编辑\n"
            "支持多标签页同时编辑，最多同时打开 8 个文件"
        )
        empty_desc.setObjectName("editorEmptyDesc")
        empty_desc.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(empty_desc)

        empty_layout.addStretch()

        self._update_empty_state()

    def resizeEvent(self, event) -> None:
        """确保空状态覆盖层随窗口大小变化。"""
        super().resizeEvent(event)
        if self.empty_state.isVisible():
            self._position_empty_state()

    def _position_empty_state(self) -> None:
        """将空状态覆盖层定位到编辑器区域上方。"""
        # 空状态只覆盖 tab_widget 区域
        geo = self.tab_widget.geometry()
        self.empty_state.setGeometry(geo)

    def _update_empty_state(self) -> None:
        """根据标签页数量显示/隐藏空状态。"""
        has_tabs = self.tab_widget.count() > 0
        self.empty_state.setVisible(not has_tabs)
        if not has_tabs:
            self._position_empty_state()

    # ------------------------------------------------------------------
    # 快捷键
    # ------------------------------------------------------------------
    def _setup_shortcuts(self) -> None:
        QShortcut(
            QKeySequence("Ctrl+S"), self, activated=self._on_save
        )

    # ------------------------------------------------------------------
    # 标签页管理
    # ------------------------------------------------------------------
    def _on_tab_close(self, index: int) -> None:
        """关闭标签页，未保存时提示。"""
        tab = self._tab_at(index)
        if tab is None:
            self.tab_widget.removeTab(index)
            self._update_empty_state()
            return

        if tab.is_modified():
            reply = QMessageBox.question(
                self,
                "未保存的更改",
                f'"{tab.display_name()}" 有未保存的更改，请选择操作：',
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply == QMessageBox.Save:
                if not tab.save_file():
                    QMessageBox.warning(
                        self, "保存失败", f"无法保存 {tab.display_name()}"
                    )
                    return
            elif reply == QMessageBox.Cancel:
                return

        # 断开光标位置信号，防止已关闭标签页触发回调
        try:
            tab.editor.cursorPositionChanged.disconnect()
        except Exception:
            pass
        tab.deleteLater()
        self.tab_widget.removeTab(index)
        self._update_empty_state()
        self._update_status_for_current_tab()

    def _on_tab_changed(self, index: int) -> None:
        """切换标签页时更新面包屑和状态栏。"""
        self._update_status_for_current_tab()

    def _tab_at(self, index: int) -> Optional[EditorTab]:
        """获取指定索引的标签页 widget。"""
        if index < 0 or index >= self.tab_widget.count():
            return None
        widget = self.tab_widget.widget(index)
        return widget if isinstance(widget, EditorTab) else None

    def _current_tab(self) -> Optional[EditorTab]:
        """获取当前活动标签页。"""
        return self._tab_at(self.tab_widget.currentIndex())

    def _find_tab_by_path(self, path: str) -> Optional[int]:
        """查找已打开某路径的标签页索引。"""
        abs_path = os.path.abspath(path)
        for i in range(self.tab_widget.count()):
            tab = self._tab_at(i)
            if tab and tab.file_path and os.path.abspath(tab.file_path) == abs_path:
                return i
        return None

    # ------------------------------------------------------------------
    # 文件操作
    # ------------------------------------------------------------------
    def open_file(self, path: str) -> bool:
        """打开文件到编辑器（如已打开则切换到对应标签）。"""
        if not os.path.isfile(path):
            return False

        # 路径穿越校验：文件必须在项目目录内
        project_root = None
        for attr in ("project_dir", "current_project_root"):
            val = getattr(self.app_ctx, attr, None)
            if val:
                project_root = val
                break
        if not project_root:
            config = getattr(self.app_ctx, "config", None)
            if config:
                project_root = getattr(config, "last_project_root", None)
        if project_root:
            try:
                resolved_path = Path(path).resolve()
                resolved_root = Path(project_root).resolve()
                resolved_path.relative_to(resolved_root)
            except ValueError:
                QMessageBox.warning(
                    self, "路径错误",
                    f"文件不在项目目录内，无法打开：\n{path}"
                )
                return False
            except Exception:
                pass

        # 检查是否已在某个标签页中打开
        existing = self._find_tab_by_path(path)
        if existing is not None:
            self.tab_widget.setCurrentIndex(existing)
            return True

        # 检查标签页上限
        if self.tab_widget.count() >= self.MAX_TABS:
            QMessageBox.information(
                self,
                "标签页已满",
                f"最多同时打开 {self.MAX_TABS} 个文件，请先关闭部分标签页。",
            )
            return False

        tab = EditorTab(path, self.app_ctx)
        if not tab.load_file(path):
            QMessageBox.warning(
                self, "打开失败", f"无法读取文件:\n{path}"
            )
            return False

        idx = self.tab_widget.addTab(tab, tab.tab_title())
        self.tab_widget.setTabToolTip(idx, tab.tooltip())
        self.tab_widget.setCurrentIndex(idx)

        # 连接光标位置变化到状态栏
        tab.editor.cursorPositionChanged.connect(
            lambda: self._on_cursor_changed(tab)
        )

        self._update_empty_state()
        self._update_status_for_current_tab()
        return True

    def _on_save(self) -> None:
        """Ctrl+S 保存当前标签页。"""
        tab = self._current_tab()
        if tab is None:
            return
        if tab.file_path is None:
            # 未命名文件 → 另存为
            path, _ = QFileDialog.getSaveFileName(self, "保存文件")
            if path:
                tab.file_path = path
                if tab.save_file():
                    self.tab_widget.setTabText(
                        self.tab_widget.currentIndex(), tab.tab_title()
                    )
                    self.tab_widget.setTabToolTip(
                        self.tab_widget.currentIndex(), tab.tooltip()
                    )
                    self._update_status_for_current_tab()
            return

        if tab.save_file():
            self.tab_widget.setTabText(
                self.tab_widget.currentIndex(), tab.tab_title()
            )
            self._update_status_for_current_tab()

    # ------------------------------------------------------------------
    # 状态栏 / 面包屑
    # ------------------------------------------------------------------
    def _update_status_for_current_tab(self) -> None:
        """根据当前标签页更新状态栏和面包屑。"""
        tab = self._current_tab()
        if tab is None:
            self.breadcrumb_label.setText("未打开文件")
            self.pos_label.setText("Ln 1, Col 1")
            self.encoding_label.setText("UTF-8")
            self.file_type_label.setText("-")
            return

        # 面包屑
        self._update_breadcrumb(tab)

        # 状态栏
        self._update_status_bar(tab)

    def _update_breadcrumb(self, tab: EditorTab) -> None:
        """更新面包屑导航。"""
        if not tab.file_path:
            self.breadcrumb_label.setText("未命名")
            return

        # 尝试从项目根目录计算相对路径
        project_root = None
        for attr in ("project_dir", "current_project_root"):
            val = getattr(self.app_ctx, attr, None)
            if val:
                project_root = val
                break
        if not project_root:
            config = getattr(self.app_ctx, "config", None)
            if config:
                project_root = getattr(config, "last_project_root", None)

        if project_root:
            try:
                rel = os.path.relpath(tab.file_path, project_root)
                parts = rel.split(os.sep)
                root_name = os.path.basename(project_root) or project_root
                parts.insert(0, root_name)
                self.breadcrumb_label.setText(" > ".join(parts))
                return
            except Exception:
                pass

        self.breadcrumb_label.setText(tab.file_path)

    def _update_status_bar(self, tab: EditorTab) -> None:
        """更新编辑器状态栏。"""
        line, col = tab.cursor_position()
        self.pos_label.setText(f"Ln {line}, Col {col}")
        self.encoding_label.setText(tab.encoding())
        self.file_type_label.setText(tab.file_type())

    def _on_cursor_changed(self, tab: EditorTab) -> None:
        """光标位置变化时更新状态栏（仅当该标签页是当前活动页）。"""
        current = self._current_tab()
        if current is tab:
            self._update_status_bar(tab)

    # ------------------------------------------------------------------
    # 页面生命周期
    # ------------------------------------------------------------------
    def on_enter(self) -> None:
        """页面进入时：检查 app_context 是否有待打开的文件。"""
        path = getattr(self.app_ctx, "current_file_path", None)
        if path and os.path.isfile(path):
            self.open_file(path)
            # 消费掉，避免重复打开
            self.app_ctx.current_file_path = None
