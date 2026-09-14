"""国际化辅助命令：/i18n extract|check — 扫描硬编码字符串，生成 POT，检查缺失翻译。"""

from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from commands.router import CommandRouter, CommandContext
from core import G, R, Y, C, GR


def register_i18n_commands(router: CommandRouter) -> None:
    """注册国际化辅助命令。"""

    @router.command(
        "i18n",
        description="国际化辅助（提取字符串 / 检查缺失翻译）",
        usage="/i18n extract [lang] | /i18n check",
        category="开发者工具",
    )
    def cmd_i18n(ctx: CommandContext) -> None:
        sub = ctx.args[0] if ctx.args else ""

        if sub == "extract":
            _cmd_i18n_extract(ctx)
        elif sub == "check":
            _cmd_i18n_check(ctx)
        else:
            print("用法: /i18n extract [lang]  — 扫描代码提取硬编码字符串")
            print("       /i18n check            — 检查翻译文件完整性")


def _find_source_files(root: str = ".", langs: Optional[List[str]] = None) -> List[Tuple[str, str]]:
    """查找项目中的源代码文件。"""
    if langs is None:
        langs = [".py", ".js", ".ts", ".jsx", ".tsx", ".vue", ".html"]

    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        # 跳过常见非源码目录
        dirnames[:] = [d for d in dirnames if d not in {
            "node_modules", "venv", ".venv", "__pycache__", ".git",
            "dist", "build", ".pytest_cache", ".mypy_cache", "site-packages"
        }]
        for fname in filenames:
            if any(fname.endswith(ext) for ext in langs):
                fpath = os.path.join(dirpath, fname)
                # 确定语言类型
                if fname.endswith(".py"):
                    lang = "python"
                elif fname.endswith((".js", ".jsx")):
                    lang = "javascript"
                elif fname.endswith((".ts", ".tsx")):
                    lang = "typescript"
                elif fname.endswith(".vue"):
                    lang = "vue"
                elif fname.endswith(".html"):
                    lang = "html"
                else:
                    lang = "unknown"
                files.append((fpath, lang))
    return files


def _extract_python_strings(filepath: str) -> List[Dict[str, any]]:
    """从 Python 文件提取可能需翻译的字符串。"""
    results = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
    except Exception:
        return results

    try:
        tree = ast.parse(source)
    except SyntaxError:
        # 语法错误时退回到正则
        return _extract_python_strings_regex(source, filepath)

    for node in ast.walk(tree):
        # 提取 print() 和 logging 中的字符串
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in ("print",):
                for arg in node.args:
                    s = _ast_str_value(arg)
                    if s and _is_translatable(s):
                        results.append({
                            "file": filepath,
                            "line": getattr(node, "lineno", 0),
                            "text": s,
                            "context": "print statement",
                        })
            # 检查 f-string 中的字面量
        # 提取直接的字符串常量（排除 docstring）
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            s = node.value
            if _is_translatable(s) and not _is_docstring(node, tree):
                # 检查是否在函数调用中作为参数
                parent = _find_parent(tree, node)
                context = "literal"
                if parent and isinstance(parent, ast.Call):
                    context = "function argument"
                results.append({
                    "file": filepath,
                    "line": getattr(node, "lineno", 0),
                    "text": s,
                    "context": context,
                })

    return results


def _extract_python_strings_regex(source: str, filepath: str) -> List[Dict[str, any]]:
    """用正则提取 Python 字符串（AST 失败时的 fallback）。"""
    results = []
    # 匹配中文字符串
    pattern = re.compile(r'[rufb]*"([^"]*[\u4e00-\u9fff][^"]*)"|[rufb]*\'([^\']*[\u4e00-\u9fff][^\']*)\'')
    for i, line in enumerate(source.splitlines(), 1):
        for m in pattern.finditer(line):
            text = m.group(1) or m.group(2)
            if text and _is_translatable(text):
                results.append({
                    "file": filepath,
                    "line": i,
                    "text": text,
                    "context": "literal (regex fallback)",
                })
    return results


def _ast_str_value(node: ast.AST) -> Optional[str]:
    """从 AST 节点提取字符串值。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
            else:
                parts.append("{}")
        return "".join(parts) if parts else None
    return None


def _is_docstring(node: ast.Constant, tree: ast.AST) -> bool:
    """判断一个字符串常量是否是 docstring。"""
    # 简单判断：模块/类/函数体的第一个语句
    if isinstance(tree, ast.Module) and tree.body:
        if tree.body[0] is node or (isinstance(tree.body[0], ast.Expr) and tree.body[0].value is node):
            return True
    return False


def _find_parent(tree: ast.AST, target: ast.AST) -> Optional[ast.AST]:
    """在 AST 中查找节点的父节点。"""
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            if child is target:
                return node
    return None


def _extract_js_ts_strings(filepath: str) -> List[Dict[str, any]]:
    """从 JS/TS/Vue/HTML 文件提取可能需翻译的字符串。"""
    results = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
    except Exception:
        return results

    # 提取模板字符串和引号字符串中的中文
    # 匹配 `...中文...`, "...中文...", '...中文...'
    patterns = [
        (r'`([^`]*[\u4e00-\u9fff][^`]*)`', "template literal"),
        (r'"([^"]*[\u4e00-\u9fff][^"]*)"', "double quote"),
        (r"'([^']*[\u4e00-\u9fff][^']*)'", "single quote"),
    ]

    for i, line in enumerate(source.splitlines(), 1):
        for pattern, context in patterns:
            for m in re.finditer(pattern, line):
                text = m.group(1)
                if text and _is_translatable(text):
                    results.append({
                        "file": filepath,
                        "line": i,
                        "text": text,
                        "context": context,
                    })

    # Vue 模板中的文本节点
    if filepath.endswith(".vue") or filepath.endswith(".html"):
        # 提取标签之间的文本
        text_pattern = re.compile(r'>([^<]*[\u4e00-\u9fff][^<]*)<')
        for i, line in enumerate(source.splitlines(), 1):
            for m in text_pattern.finditer(line):
                text = m.group(1).strip()
                if text and _is_translatable(text):
                    results.append({
                        "file": filepath,
                        "line": i,
                        "text": text,
                        "context": "template text",
                    })

    return results


def _is_translatable(text: str) -> bool:
    """判断字符串是否需要翻译。"""
    if not text or len(text) < 2:
        return False
    # 排除纯数字、URL、文件路径、代码标识符
    if text.isdigit():
        return False
    if text.startswith(("http://", "https://", "/", "./", "../", "#")):
        return False
    # 排除全是大写（可能是常量）
    if text.isupper() and len(text) > 3:
        return False
    # 包含中文或常见需翻译标记
    has_chinese = bool(re.search(r'[\u4e00-\u9fff]', text))
    # 英文句子（长度>10且包含空格，可能是用户可见文本）
    is_sentence = len(text) > 10 and " " in text and text[0].isalpha()
    return has_chinese or is_sentence


def _generate_pot(strings: List[Dict[str, any]], output_path: Path) -> None:
    """生成 POT 模板文件。"""
    lines = [
        '# Translations template for PROJECT.',
        '# Copyright (C) YEAR ORGANIZATION',
        '# This file is distributed under the same license as the PROJECT project.',
        '# FIRST AUTHOR <EMAIL@ADDRESS>, YEAR.',
        '#',
        '#, fuzzy',
        'msgid ""',
        'msgstr ""',
        '"Project-Id-Version: PROJECT VERSION\\n"',
        '"Report-Msgid-Bugs-To: EMAIL@ADDRESS\\n"',
        '"POT-Creation-Date: ' + __import__('datetime').datetime.now().isoformat() + '\\n"',
        '"PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE\\n"',
        '"Last-Translator: FULL NAME <EMAIL@ADDRESS>\\n"',
        '"Language: \\n"',
        '"MIME-Version: 1.0\\n"',
        '"Content-Type: text/plain; charset=utf-8\\n"',
        '"Content-Transfer-Encoding: 8bit\\n"',
        '"Generated-By: MaLing\\n"',
        '',
    ]

    seen: Set[str] = set()
    for item in strings:
        text = item["text"]
        if text in seen:
            continue
        seen.add(text)
        # 对文本中的特殊字符进行转义
        escaped = text.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
        lines.append(f"#: {item['file']}:{item['line']}")
        lines.append(f'msgid "{escaped}"')
        lines.append('msgstr ""')
        lines.append('')

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _cmd_i18n_extract(ctx: CommandContext) -> None:
    """扫描代码提取硬编码字符串。"""
    lang = ctx.args[1] if len(ctx.args) > 1 else None

    print(C("🔍 扫描项目中的硬编码字符串...\n"))
    files = _find_source_files()
    if not files:
        print(Y("⚠️ 未找到源代码文件"))
        return

    all_strings: List[Dict[str, any]] = []
    for filepath, ftype in files:
        if ftype == "python":
            strings = _extract_python_strings(filepath)
        else:
            strings = _extract_js_ts_strings(filepath)
        all_strings.extend(strings)

    if not all_strings:
        print(G("✅ 未发现明显的硬编码可翻译字符串"))
        return

    # 去重统计
    unique_texts: Set[str] = set(s["text"] for s in all_strings)
    print(f"发现 {len(all_strings)} 处字符串引用，涉及 {len(unique_texts)} 个唯一文本\n")

    # 按文件分组展示
    by_file: Dict[str, List[Dict]] = {}
    for s in all_strings:
        by_file.setdefault(s["file"], []).append(s)

    for fpath, items in sorted(by_file.items())[:10]:
        print(C(f"📄 {fpath} ({len(items)} 处)"))
        for item in items[:5]:
            text_preview = item["text"][:60]
            if len(item["text"]) > 60:
                text_preview += "..."
            print(f"   行{item['line']:>4}: {GR(text_preview)}")
        if len(items) > 5:
            print(f"   ... 还有 {len(items)-5} 处")
        print()

    if len(by_file) > 10:
        print(GR(f"... 还有 {len(by_file)-10} 个文件"))

    # 生成 POT 文件
    pot_path = Path("locale") / "messages.pot"
    _generate_pot(all_strings, pot_path)
    print(G(f"✅ POT 模板已生成: {pot_path}"))
    print(GR(f"   唯一文本: {len(unique_texts)} 条"))

    # 如果指定了语言，生成对应的 PO 文件
    if lang:
        po_dir = Path("locale") / lang / "LC_MESSAGES"
        po_dir.mkdir(parents=True, exist_ok=True)
        po_path = po_dir / "messages.po"

        # 从现有 PO 文件读取已有翻译
        existing: Dict[str, str] = {}
        if po_path.exists():
            existing = _parse_po_file(po_path)

        po_lines = [
            f'\nmsgid ""',
            'msgstr ""',
            '"Language: ' + lang + '\\n"',
            '"MIME-Version: 1.0\\n"',
            '"Content-Type: text/plain; charset=utf-8\\n"',
            '"Content-Transfer-Encoding: 8bit\\n"',
            '',
        ]
        for text in sorted(unique_texts):
            escaped = text.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
            po_lines.append(f'msgid "{escaped}"')
            trans = existing.get(text, "")
            trans_escaped = trans.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
            po_lines.append(f'msgstr "{trans_escaped}"')
            po_lines.append('')

        with open(po_path, "w", encoding="utf-8") as f:
            f.write("\n".join(po_lines))
        print(G(f"✅ PO 文件已生成: {po_path}"))
        if existing:
            print(GR(f"   已保留 {len(existing)} 条现有翻译"))


def _parse_po_file(path: Path) -> Dict[str, str]:
    """简单解析 PO 文件，返回 msgid -> msgstr 映射。"""
    result: Dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception:
        return result

    # 简化解析
    pattern = re.compile(r'msgid "(.*?)"\s*\nmsgstr "(.*?)"', re.DOTALL)
    for m in pattern.finditer(content):
        msgid = m.group(1).replace('\\"', '"').replace('\\n', '\n').replace('\\\\', '\\')
        msgstr = m.group(2).replace('\\"', '"').replace('\\n', '\n').replace('\\\\', '\\')
        if msgid:
            result[msgid] = msgstr
    return result


def _cmd_i18n_check(ctx: CommandContext) -> None:
    """检查翻译文件完整性。"""
    locale_dir = Path("locale")
    if not locale_dir.exists():
        print(Y("⚠️ 未找到 locale 目录，先执行 /i18n extract <lang>"))
        return

    pot_path = locale_dir / "messages.pot"
    if not pot_path.exists():
        print(Y("⚠️ 未找到 messages.pot，先执行 /i18n extract"))
        return

    # 读取 POT 中的 msgid
    pot_ids = set(_parse_po_file(pot_path).keys())
    if not pot_ids:
        print(Y("⚠️ POT 文件为空"))
        return

    print(C(f"📋 基准文本: {len(pot_ids)} 条\n"))

    # 检查每个语言的 PO 文件
    issues_found = False
    for lang_dir in sorted(locale_dir.iterdir()):
        if not lang_dir.is_dir() or lang_dir.name == "__pycache__":
            continue
        po_path = lang_dir / "LC_MESSAGES" / "messages.po"
        if not po_path.exists():
            print(Y(f"⚠️ {lang_dir.name}: 缺少 messages.po"))
            issues_found = True
            continue

        translations = _parse_po_file(po_path)
        missing = []
        empty = []
        for msgid in pot_ids:
            if msgid not in translations:
                missing.append(msgid)
            elif not translations[msgid].strip():
                empty.append(msgid)

        if missing or empty:
            issues_found = True
            print(R(f"❌ {lang_dir.name}: 缺失 {len(missing)} 条，未翻译 {len(empty)} 条"))
            if missing:
                for m in missing[:3]:
                    preview = m[:50] + "..." if len(m) > 50 else m
                    print(f"   缺失: {GR(preview)}")
                if len(missing) > 3:
                    print(f"   ... 还有 {len(missing)-3} 条缺失")
        else:
            print(G(f"✅ {lang_dir.name}: 完整 ({len(translations)} 条翻译)"))

    if not issues_found:
        print(G("\n✅ 所有语言翻译完整"))
    else:
        print(f"\n{Y('提示')}: 执行 /i18n extract <lang> 更新翻译文件")
