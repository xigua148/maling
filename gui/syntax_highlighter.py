"""简单语法高亮器 —— 为代码块提供基础着色。"""
from __future__ import annotations

import re
from typing import Dict, List, Pattern

from gui.qt_compat import QSyntaxHighlighter, QTextCharFormat, QColor, QFont


# 通用 token 配色（暗色背景）
TOKEN_COLORS = {
    "keyword": "#FF79C6",      # 关键字
    "string": "#F1FA8C",       # 字符串
    "comment": "#6272A4",      # 注释
    "number": "#BD93F9",       # 数字
    "function": "#50FA7B",     # 函数名
    "class_name": "#8BE9FD",   # 类名
    "operator": "#FF79C6",     # 运算符
    "builtin": "#8BE9FD",      # 内置函数/类型
}

# 各语言关键字
LANGUAGE_KEYWORDS: Dict[str, List[str]] = {
    "python": [
        "and", "as", "assert", "async", "await", "break", "class", "continue",
        "def", "del", "elif", "else", "except", "False", "finally", "for",
        "from", "global", "if", "import", "in", "is", "lambda", "None",
        "nonlocal", "not", "or", "pass", "raise", "return", "True", "try",
        "while", "with", "yield",
    ],
    "javascript": [
        "break", "case", "catch", "class", "const", "continue", "debugger",
        "default", "delete", "do", "else", "export", "extends", "false",
        "finally", "for", "function", "if", "import", "in", "instanceof",
        "new", "null", "return", "super", "switch", "this", "throw", "true",
        "try", "typeof", "var", "void", "while", "with", "yield", "let",
        "static", "await",
    ],
    "typescript": [
        "break", "case", "catch", "class", "const", "continue", "debugger",
        "default", "delete", "do", "else", "export", "extends", "false",
        "finally", "for", "function", "if", "import", "in", "instanceof",
        "new", "null", "return", "super", "switch", "this", "throw", "true",
        "try", "typeof", "var", "void", "while", "with", "yield", "let",
        "static", "await", "interface", "type", "enum", "namespace", "abstract",
        "readonly", "implements", "declare",
    ],
    "java": [
        "abstract", "assert", "boolean", "break", "byte", "case", "catch",
        "char", "class", "const", "continue", "default", "do", "double",
        "else", "enum", "extends", "final", "finally", "float", "for",
        "goto", "if", "implements", "import", "instanceof", "int",
        "interface", "long", "native", "new", "package", "private",
        "protected", "public", "return", "short", "static", "strictfp",
        "super", "switch", "synchronized", "this", "throw", "throws",
        "transient", "try", "void", "volatile", "while", "true", "false", "null",
    ],
    "cpp": [
        "alignas", "alignof", "and", "and_eq", "asm", "auto", "bitand",
        "bitor", "bool", "break", "case", "catch", "char", "char8_t",
        "char16_t", "char32_t", "class", "compl", "concept", "const",
        "consteval", "constexpr", "constinit", "const_cast", "continue",
        "co_await", "co_return", "co_yield", "decltype", "default", "delete",
        "do", "double", "dynamic_cast", "else", "enum", "explicit", "export",
        "extern", "false", "float", "for", "friend", "goto", "if", "inline",
        "int", "long", "mutable", "namespace", "new", "noexcept", "not",
        "not_eq", "nullptr", "operator", "or", "or_eq", "private",
        "protected", "public", "register", "reinterpret_cast", "requires",
        "return", "short", "signed", "sizeof", "static", "static_assert",
        "static_cast", "struct", "switch", "template", "this", "thread_local",
        "throw", "true", "try", "typedef", "typeid", "typename", "union",
        "unsigned", "using", "virtual", "void", "volatile", "wchar_t",
        "while", "xor", "xor_eq",
    ],
    "go": [
        "break", "case", "chan", "const", "continue", "default", "defer",
        "else", "fallthrough", "for", "func", "go", "goto", "if", "import",
        "interface", "map", "package", "range", "return", "select", "struct",
        "switch", "type", "var",
    ],
    "rust": [
        "as", "async", "await", "break", "const", "continue", "crate", "dyn",
        "else", "enum", "extern", "false", "fn", "for", "if", "impl", "in",
        "let", "loop", "match", "mod", "move", "mut", "pub", "ref", "return",
        "self", "Self", "static", "struct", "super", "trait", "true", "type",
        "unsafe", "use", "where", "while",
    ],
    "bash": [
        "if", "then", "else", "elif", "fi", "case", "esac", "for", "select",
        "while", "until", "do", "done", "in", "function", "time", "{", "}",
        "!", "[[", "]]",
    ],
    "sql": [
        "SELECT", "FROM", "WHERE", "INSERT", "UPDATE", "DELETE", "CREATE",
        "DROP", "ALTER", "TABLE", "INDEX", "VIEW", "JOIN", "INNER", "LEFT",
        "RIGHT", "OUTER", "ON", "GROUP", "BY", "ORDER", "HAVING", "LIMIT",
        "OFFSET", "UNION", "ALL", "DISTINCT", "AS", "AND", "OR", "NOT",
        "NULL", "IS", "IN", "BETWEEN", "LIKE", "EXISTS", "CASE", "WHEN",
        "THEN", "ELSE", "END", "IF", "ASC", "DESC", "VALUES", "INTO",
        "SET", "PRIMARY", "KEY", "FOREIGN", "REFERENCES", "DEFAULT",
        "AUTO_INCREMENT", "UNIQUE", "CHECK", "CONSTRAINT",
    ],
}

# 语言别名映射
LANG_ALIASES = {
    "py": "python", "js": "javascript", "ts": "typescript",
    "sh": "bash", "shell": "bash", "zsh": "bash",
    "c++": "cpp", "cxx": "cpp", "hpp": "cpp",
    "rs": "rust", "rb": "ruby", "md": "markdown",
}


def normalize_lang(lang: str) -> str:
    """统一语言标识符。"""
    lang = lang.lower().strip()
    return LANG_ALIASES.get(lang, lang)


def _build_keyword_pattern(keywords: List[str]) -> Pattern:
    """构建关键字正则。"""
    escaped = [re.escape(kw) for kw in sorted(keywords, key=len, reverse=True)]
    return re.compile(r"\b(" + "|".join(escaped) + r")\b")


def _build_rules(lang: str) -> List[tuple]:
    """为指定语言构建高亮规则列表 [(pattern, format_name), ...]。"""
    lang = normalize_lang(lang)
    keywords = LANGUAGE_KEYWORDS.get(lang, [])
    rules: List[tuple] = []

    # 注释
    if lang in ("python", "bash", "shell", "yaml", "ruby", "perl"):
        rules.append((re.compile(r"#.*$", re.MULTILINE), "comment"))
    elif lang in ("javascript", "typescript", "java", "cpp", "c", "go", "rust"):
        rules.append((re.compile(r"//.*$", re.MULTILINE), "comment"))
        rules.append((re.compile(r"/\*.*?\*/", re.DOTALL), "comment"))

    # 字符串
    rules.append((re.compile(r"\"(\\.|[^\"\\])*\""), "string"))
    rules.append((re.compile(r"'(\\.|[^'\\])*'"), "string"))
    if lang == "python":
        triple_dq = '"""'
        triple_sq = "'''"
        rules.append((re.compile(triple_dq + ".*?" + triple_dq + "|" + triple_sq + ".*?" + triple_sq, re.DOTALL), "string"))
    # 数字
    rules.append((re.compile(r"\b\d+(\.\d+)?([eE][+-]?\d+)?\b"), "number"))

    # 关键字
    if keywords:
        rules.append((_build_keyword_pattern(keywords), "keyword"))

    # 函数调用（简单模式：标识符后跟括号）
    rules.append((re.compile(r"\b([A-Za-z_]\w*)\s*(?=\()"), "function"))

    # 类名（Python/Java/C++ 的大写开头）
    if lang in ("python", "java", "cpp", "typescript", "javascript"):
        rules.append((re.compile(r"\b[A-Z][a-zA-Z0-9_]*\b"), "class_name"))

    return rules


class SimpleSyntaxHighlighter(QSyntaxHighlighter):
    """基于正则的简单语法高亮器。"""

    def __init__(self, document, lang: str = "text"):
        super().__init__(document)
        self._lang = normalize_lang(lang)
        self._rules = _build_rules(self._lang)
        self._formats = self._create_formats()

    def _create_formats(self) -> Dict[str, QTextCharFormat]:
        """创建各 token 的 QTextCharFormat。"""
        fmts: Dict[str, QTextCharFormat] = {}
        for token, color in TOKEN_COLORS.items():
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if token in ("keyword", "builtin"):
                fmt.setFontWeight(QFont.Weight.Bold)
            fmts[token] = fmt
        return fmts

    def highlightBlock(self, text: str) -> None:
        """高亮单行文本。"""
        if self._lang == "text" or not self._rules:
            return
        for pattern, token in self._rules:
            fmt = self._formats.get(token)
            if fmt is None:
                continue
            for match in pattern.finditer(text):
                start, end = match.span()
                self.setFormat(start, end - start, fmt)
