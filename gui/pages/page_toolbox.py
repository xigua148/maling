"""工具箱 —— 集成开发辅助工具：代码美化、正则测试、编码转换、文本处理。"""
from __future__ import annotations

import base64
import binascii
import json
import re
import time
import urllib.parse
from typing import Optional

from gui.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QPlainTextEdit, QListWidget, QFrame, Qt, QFont,
    QLineEdit, QComboBox, QMessageBox, QApplication, QListWidgetItem,
)


class PageToolbox(QWidget):
    """工具箱页面。"""

    TOOLS = [
        ("代码美化", [
            ("python", "Python", "粘贴 Python 代码..."),
            ("json", "JSON", "粘贴 JSON..."),
            ("html", "HTML", "粘贴 HTML..."),
            ("css", "CSS", "粘贴 CSS..."),
            ("sql", "SQL", "粘贴 SQL..."),
        ]),
        ("正则测试", [
            ("regex", "正则测试", "输入待测试的文本..."),
        ]),
        ("编码转换", [
            ("base64", "Base64", "输入文本..."),
            ("url", "URL", "输入 URL..."),
            ("hex", "Hex", "输入文本..."),
            ("unicode", "Unicode", "输入字符..."),
        ]),
        ("文本处理", [
            ("dedup", "去重", "每行一条数据..."),
            ("sort", "排序", "每行一条数据..."),
            ("stats", "统计", "输入文本..."),
            ("case", "大小写转换", "输入文本..."),
        ]),
    ]

    def __init__(self, app_context, title: str = "工具箱", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app_ctx = app_context
        self.title = title
        self._current_tool: Optional[str] = None
        self._init_ui()
        self._apply_theme()
        self._connect_signals()
        # 默认选中第一个工具
        self._on_tool_selected(self.tool_list.item(0))

    def _init_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- 左侧工具分类 ---
        self.left_sidebar = QWidget()
        self.left_sidebar.setObjectName("toolboxSidebar")
        self.left_sidebar.setFixedWidth(200)
        left_layout = QVBoxLayout(self.left_sidebar)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(8)

        title = QLabel("工具箱")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        left_layout.addWidget(title)

        self.tool_list = QListWidget()
        self.tool_list.setObjectName("toolList")
        for category, tools in self.TOOLS:
            cat_item = QListWidgetItem(f"📁 {category}")
            cat_item.setFlags(Qt.ItemIsEnabled)
            cat_item.setData(Qt.UserRole, "category")
            self.tool_list.addItem(cat_item)
            for key, name, placeholder in tools:
                item = QListWidgetItem(f"   {name}")
                item.setData(Qt.UserRole, key)
                item.setData(Qt.UserRole + 1, placeholder)
                self.tool_list.addItem(item)

        self.tool_list.itemClicked.connect(self._on_tool_selected)
        left_layout.addWidget(self.tool_list, 1)
        main_layout.addWidget(self.left_sidebar)

        # --- 右侧工作区 ---
        self.work_area = QWidget()
        self.work_area.setObjectName("toolboxPage")
        work_layout = QVBoxLayout(self.work_area)
        work_layout.setContentsMargins(24, 24, 24, 24)
        work_layout.setSpacing(16)

        # 工具标题
        self.tool_title = QLabel("Python 美化")
        tool_title_font = QFont()
        tool_title_font.setPointSize(14)
        tool_title_font.setBold(True)
        self.tool_title.setFont(tool_title_font)
        work_layout.addWidget(self.tool_title)

        # 输入区
        input_card = self._create_section("输入")
        input_layout = input_card.layout()
        self.input_edit = QTextEdit()
        self.input_edit.setPlaceholderText("粘贴代码...")
        input_layout.addWidget(self.input_edit)
        work_layout.addWidget(input_card)

        # 正则专用：表达式输入
        self.regex_widget = QWidget()
        self.regex_row = QHBoxLayout(self.regex_widget)
        self.regex_row.setContentsMargins(0, 0, 0, 0)
        self.regex_row.addWidget(QLabel("正则表达式:"))
        self.regex_edit = QLineEdit()
        self.regex_edit.setPlaceholderText("输入正则，如: \\d+")
        self.regex_row.addWidget(self.regex_edit, 1)
        self.flags_combo = QComboBox()
        self.flags_combo.addItems(["无标志", "忽略大小写 (i)", "多行 (m)", "单行 (s)"])
        self.regex_row.addWidget(self.flags_combo)
        self.regex_widget.setVisible(False)
        work_layout.addWidget(self.regex_widget)

        # 操作按钮区
        btn_layout = QHBoxLayout()
        self.action_btn1 = QPushButton("格式化")
        self.action_btn1.setObjectName("primaryBtn")
        self.action_btn1.clicked.connect(self._on_action1)
        btn_layout.addWidget(self.action_btn1)

        self.action_btn2 = QPushButton("压缩")
        self.action_btn2.setObjectName("secondaryBtn")
        self.action_btn2.clicked.connect(self._on_action2)
        btn_layout.addWidget(self.action_btn2)

        self.copy_btn = QPushButton("复制结果")
        self.copy_btn.setObjectName("secondaryBtn")
        self.copy_btn.clicked.connect(self._on_copy_result)
        btn_layout.addWidget(self.copy_btn)

        btn_layout.addStretch()
        work_layout.addLayout(btn_layout)

        # 输出区
        output_card = self._create_section("输出")
        output_layout = output_card.layout()
        self.output_edit = QPlainTextEdit()
        self.output_edit.setReadOnly(True)
        self.output_edit.setPlaceholderText("处理结果将显示在这里...")
        output_layout.addWidget(self.output_edit)
        work_layout.addWidget(output_card)

        # 状态栏
        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("toolboxStatus")
        work_layout.addWidget(self.status_label)

        work_layout.addStretch()
        main_layout.addWidget(self.work_area, 1)

    def _create_section(self, title: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("toolboxSection")
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        title_label = QLabel(title)
        title_font = QFont()
        title_font.setPointSize(11)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)
        return frame

    def _connect_signals(self) -> None:
        theme_engine = getattr(self.app_ctx, "theme_engine", None)
        if theme_engine is not None:
            theme_engine.theme_changed.connect(self._on_theme_changed)

    def _on_tool_selected(self, item: QListWidgetItem) -> None:
        if not item:
            return
        tool_key = item.data(Qt.UserRole)
        if tool_key == "category":
            return

        self._current_tool = tool_key
        placeholder = item.data(Qt.UserRole + 1) or ""
        self.input_edit.setPlaceholderText(placeholder)
        self.input_edit.clear()
        self.output_edit.clear()
        self.status_label.setText("就绪")

        # 更新标题
        tool_names = {
            "python": "Python 美化", "json": "JSON 美化",
            "html": "HTML 美化", "css": "CSS 美化", "sql": "SQL 美化",
            "regex": "正则测试", "base64": "Base64 编解码",
            "url": "URL 编解码", "hex": "Hex 编解码",
            "unicode": "Unicode 转换", "dedup": "去重",
            "sort": "排序", "stats": "文本统计",
            "case": "大小写转换",
        }
        self.tool_title.setText(tool_names.get(tool_key, tool_key))

        # 更新按钮和界面
        is_code = tool_key in ("python", "json", "html", "css", "sql")
        is_regex = tool_key == "regex"
        is_encode = tool_key in ("base64", "url", "hex", "unicode")
        is_text = tool_key in ("dedup", "sort", "stats", "case")

        self.regex_widget.setVisible(is_regex)

        if is_code:
            self.action_btn1.setText("格式化")
            self.action_btn1.setVisible(True)
            self.action_btn2.setText("压缩")
            self.action_btn2.setVisible(True)
        elif is_regex:
            self.action_btn1.setText("测试匹配")
            self.action_btn1.setVisible(True)
            self.action_btn2.setText("替换")
            self.action_btn2.setVisible(False)
        elif is_encode:
            self.action_btn1.setText("编码")
            self.action_btn1.setVisible(True)
            self.action_btn2.setText("解码")
            self.action_btn2.setVisible(True)
        elif is_text:
            self.action_btn1.setText("处理")
            self.action_btn1.setVisible(True)
            self.action_btn2.setVisible(False)

    def _on_action1(self) -> None:
        if not self._current_tool:
            return
        text = self.input_edit.toPlainText()
        start = time.time()

        try:
            if self._current_tool == "python":
                result = self._beautify_python(text)
            elif self._current_tool == "json":
                result = self._beautify_json(text)
            elif self._current_tool == "html":
                result = self._beautify_html(text)
            elif self._current_tool == "css":
                result = self._beautify_css(text)
            elif self._current_tool == "sql":
                result = self._beautify_sql(text)
            elif self._current_tool == "regex":
                result = self._test_regex(text)
            elif self._current_tool == "base64":
                result = base64.b64encode(text.encode("utf-8")).decode("utf-8")
            elif self._current_tool == "url":
                result = urllib.parse.quote(text, safe="")
            elif self._current_tool == "hex":
                result = binascii.hexlify(text.encode("utf-8")).decode("utf-8")
            elif self._current_tool == "unicode":
                result = " ".join(f"U+{ord(c):04X}" for c in text)
            elif self._current_tool == "dedup":
                result = self._dedup_lines(text)
            elif self._current_tool == "sort":
                result = self._sort_lines(text)
            elif self._current_tool == "stats":
                result = self._text_stats(text)
            elif self._current_tool == "case":
                result = text.upper()
            else:
                result = "未知工具"
        except Exception as exc:
            result = f"错误: {exc}"

        elapsed = (time.time() - start) * 1000
        self.output_edit.setPlainText(result)
        in_len = len(text)
        out_len = len(result)
        self.status_label.setText(
            f"处理完成 | 输入 {in_len} 字符 → 输出 {out_len} 字符 | 耗时 {elapsed:.0f}ms"
        )

    def _on_action2(self) -> None:
        if not self._current_tool:
            return
        text = self.input_edit.toPlainText()
        start = time.time()

        try:
            if self._current_tool == "python":
                result = self._minify_python(text)
            elif self._current_tool == "json":
                result = json.dumps(json.loads(text), separators=(",", ":"))
            elif self._current_tool == "html":
                result = self._minify_html(text)
            elif self._current_tool == "css":
                result = self._minify_css(text)
            elif self._current_tool == "sql":
                result = re.sub(r"\s+", " ", text).strip()
            elif self._current_tool == "base64":
                result = base64.b64decode(text.encode("utf-8")).decode("utf-8")
            elif self._current_tool == "url":
                result = urllib.parse.unquote(text)
            elif self._current_tool == "hex":
                result = binascii.unhexlify(text.strip().replace(" ", "")).decode("utf-8")
            elif self._current_tool == "unicode":
                result = self._unicode_decode(text)
            else:
                result = "不支持此操作"
        except Exception as exc:
            result = f"错误: {exc}"

        elapsed = (time.time() - start) * 1000
        self.output_edit.setPlainText(result)
        self.status_label.setText(f"处理完成 | 耗时 {elapsed:.0f}ms")

    def _on_copy_result(self) -> None:
        text = self.output_edit.toPlainText()
        if not text:
            return
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(text)
            self.status_label.setText("已复制到剪贴板")

    def _beautify_python(self, text: str) -> str:
        try:
            import ast
            ast.parse(text)
        except SyntaxError as exc:
            return f"语法错误: {exc}"

        # 简单的格式化：保持原有结构，统一缩进
        lines = text.split("\n")
        result_lines = []
        indent_level = 0
        for line in lines:
            stripped = line.strip()
            if stripped.endswith(":") and not stripped.startswith("#"):
                result_lines.append("    " * indent_level + stripped)
                indent_level += 1
            elif stripped in ("return", "pass", "break", "continue", "raise"):
                result_lines.append("    " * indent_level + stripped)
            elif stripped == "":
                result_lines.append("")
            else:
                result_lines.append("    " * indent_level + stripped)
                if stripped.startswith(("return", "raise", "pass", "break", "continue")):
                    indent_level = max(0, indent_level - 1)
        return "\n".join(result_lines)

    def _minify_python(self, text: str) -> str:
        lines = text.split("\n")
        result = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                result.append(stripped)
        return " ".join(result)

    def _beautify_json(self, text: str) -> str:
        data = json.loads(text)
        return json.dumps(data, ensure_ascii=False, indent=2)

    def _beautify_html(self, text: str) -> str:
        # 简单的标签缩进
        indent = 0
        result = []
        import re
        tokens = re.split(r"(<[^>]+>)", text)
        for token in tokens:
            if not token.strip():
                continue
            if token.startswith("</"):
                indent = max(0, indent - 1)
                result.append("  " * indent + token)
            elif token.startswith("<") and not token.endswith("/>") and not token.startswith("<!--"):
                result.append("  " * indent + token)
                if not any(token.startswith(f"<{t}") for t in ("br", "hr", "img", "input", "meta", "link")):
                    indent += 1
            else:
                if token.strip():
                    result.append("  " * indent + token.strip())
        return "\n".join(result)

    def _minify_html(self, text: str) -> str:
        return re.sub(r">\s+<", "><", text.strip())

    def _beautify_css(self, text: str) -> str:
        # 简单格式化：每个规则一行，属性缩进
        text = re.sub(r"\s+", " ", text.strip())
        text = text.replace("{", " {\n  ")
        text = text.replace(";", ";\n  ")
        text = text.replace("}", "\n}\n")
        return text.strip()

    def _minify_css(self, text: str) -> str:
        return re.sub(r"\s+", " ", text.strip())

    def _beautify_sql(self, text: str) -> str:
        keywords = [
            "SELECT", "FROM", "WHERE", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER",
            "ON", "GROUP", "BY", "ORDER", "HAVING", "LIMIT", "OFFSET",
            "INSERT", "INTO", "VALUES", "UPDATE", "SET", "DELETE",
            "CREATE", "TABLE", "ALTER", "DROP", "INDEX", "AND", "OR", "NOT",
        ]
        result = text
        for kw in keywords:
            result = re.sub(rf"\b{kw}\b", kw, result, flags=re.IGNORECASE)
        # 在关键字前换行
        for kw in keywords[1:]:
            result = re.sub(rf"\s+{kw}\b", f"\n{kw}", result, flags=re.IGNORECASE)
        return result.strip()

    def _test_regex(self, text: str) -> str:
        pattern = self.regex_edit.text()
        if not pattern:
            return "请输入正则表达式"
        flags = 0
        flag_text = self.flags_combo.currentText()
        if "i" in flag_text:
            flags |= re.IGNORECASE
        if "m" in flag_text:
            flags |= re.MULTILINE
        if "s" in flag_text:
            flags |= re.DOTALL

        try:
            compiled = re.compile(pattern, flags)
        except re.error as exc:
            return f"正则语法错误: {exc}"

        matches = list(compiled.finditer(text))
        if not matches:
            return "无匹配"

        results = [f"共找到 {len(matches)} 处匹配:"]
        for i, match in enumerate(matches, 1):
            start, end = match.span()
            groups = match.groups()
            group_str = f" | 分组: {groups}" if groups else ""
            results.append(f"  {i}. 位置 {start}-{end}: '{match.group()}'{group_str}")
        return "\n".join(results)

    def _unicode_decode(self, text: str) -> str:
        parts = text.split()
        result = []
        for part in parts:
            part = part.strip().upper().replace("U+", "")
            try:
                result.append(chr(int(part, 16)))
            except ValueError:
                result.append(part)
        return "".join(result)

    def _dedup_lines(self, text: str) -> str:
        lines = text.split("\n")
        seen = set()
        result = []
        for line in lines:
            if line not in seen:
                seen.add(line)
                result.append(line)
        return "\n".join(result)

    def _sort_lines(self, text: str) -> str:
        lines = text.split("\n")
        return "\n".join(sorted(lines))

    def _text_stats(self, text: str) -> str:
        chars = len(text)
        lines = text.count("\n") + 1 if text else 0
        words = len(text.split())
        bytes_len = len(text.encode("utf-8"))
        return (
            f"字符数: {chars}\n"
            f"词数: {words}\n"
            f"行数: {lines}\n"
            f"字节数: {bytes_len}"
        )

    def _apply_theme(self) -> None:
        theme_engine = getattr(self.app_ctx, "theme_engine", None)
        if theme_engine is None:
            return

        bg = theme_engine.get_color("bg", "#FFF5F5")
        text = theme_engine.get_color("text", "#5D4037")
        primary = theme_engine.get_color("primary", "#FF6B9D")
        secondary = theme_engine.get_color("text_secondary", "#888888")
        border = theme_engine.get_color("border", "#FFE4EC")
        card_bg = theme_engine.get_color("bg_card", "#FFFFFF")

        self.setStyleSheet(f"""
            QWidget#toolboxPage {{
                background: {bg};
            }}
            QWidget#toolboxSidebar {{
                background: {card_bg};
                border-right: 1px solid {border};
            }}
            QListWidget#toolList {{
                background: transparent;
                border: none;
                outline: none;
                color: {text};
            }}
            QListWidget#toolList::item {{
                padding: 6px 10px;
                border-radius: 6px;
            }}
            QListWidget#toolList::item:selected {{
                background: {primary}22;
                color: {primary};
                font-weight: 500;
            }}
            QListWidget#toolList::item:hover {{
                background: {primary}11;
            }}
            QFrame#toolboxSection {{
                background: {card_bg};
                border: 1px solid {border};
                border-radius: 12px;
            }}
            QLabel#toolboxStatus {{
                color: {secondary};
                font-size: 11px;
            }}
        """)

    def _on_theme_changed(self, theme_name: str) -> None:
        self._apply_theme()
