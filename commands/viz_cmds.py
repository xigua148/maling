"""代码可视化命令：/viz calls|deps|class — 生成调用图/依赖图/类图（文本/ASCII）。"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from commands.router import CommandRouter, CommandContext
from core import G, R, Y, C, GR


def register_viz_commands(router: CommandRouter) -> None:
    """注册代码可视化命令。"""

    @router.command(
        "viz",
        description="代码可视化（调用图 / 依赖图 / 类图）",
        usage="/viz calls <file> | /viz deps [file] | /viz class <file>",
        category="开发者工具",
    )
    def cmd_viz(ctx: CommandContext) -> None:
        sub = ctx.args[0] if ctx.args else ""

        if sub == "calls":
            _cmd_viz_calls(ctx)
        elif sub == "deps":
            _cmd_viz_deps(ctx)
        elif sub == "class":
            _cmd_viz_class(ctx)
        else:
            print("用法: /viz calls <file>    — 函数调用关系图")
            print("       /viz deps [file]      — 模块依赖图")
            print("       /viz class <file>     — 类继承与成员图")


def _parse_python_file(filepath: str) -> Optional[ast.Module]:
    """解析 Python 文件为 AST。"""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
        return ast.parse(source)
    except Exception:
        return None


def _extract_functions(tree: ast.Module) -> Dict[str, List[str]]:
    """提取模块中的函数定义及其调用关系。"""
    functions: Dict[str, List[str]] = {}

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_name = node.name
            calls = []
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    call_name = _get_call_name(child)
                    if call_name:
                        calls.append(call_name)
            functions[func_name] = calls

    return functions


def _extract_classes(tree: ast.Module) -> Dict[str, Dict[str, any]]:
    """提取类定义及其信息。"""
    classes: Dict[str, Dict[str, any]] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            cls_info = {
                "bases": [_get_name(base) for base in node.bases],
                "methods": [],
                "attributes": set(),
                "line": node.lineno,
            }
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    cls_info["methods"].append(item.name)
                elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    cls_info["attributes"].add(item.target.id)
                elif isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            cls_info["attributes"].add(target.id)
            classes[node.name] = cls_info

    return classes


def _get_call_name(node: ast.Call) -> Optional[str]:
    """从 Call 节点获取被调用函数的名称。"""
    if isinstance(node.func, ast.Name):
        return node.func.id
    elif isinstance(node.func, ast.Attribute):
        parts = []
        n = node.func
        while isinstance(n, ast.Attribute):
            parts.append(n.attr)
            n = n.value
        if isinstance(n, ast.Name):
            parts.append(n.id)
        return ".".join(reversed(parts))
    return None


def _get_name(node: ast.AST) -> str:
    """从 AST 节点获取名称。"""
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        return f"{_get_name(node.value)}.{node.attr}"
    return str(type(node).__name__)


def _build_ascii_graph(edges: List[Tuple[str, str]], nodes: Optional[Set[str]] = None,
                        title: str = "", max_nodes: int = 30) -> str:
    """用 networkx + 文本渲染生成 ASCII 图。"""
    try:
        import networkx as nx
    except ImportError:
        return "❌ 未安装 networkx，请执行: pip install networkx"

    G = nx.DiGraph()
    all_nodes = nodes or set()
    for src, dst in edges:
        all_nodes.add(src)
        all_nodes.add(dst)

    if len(all_nodes) > max_nodes:
        # 只保留边数最多的节点
        node_edges = {}
        for src, dst in edges:
            node_edges[src] = node_edges.get(src, 0) + 1
            node_edges[dst] = node_edges.get(dst, 0) + 1
        top_nodes = set(sorted(node_edges.keys(), key=lambda n: node_edges[n], reverse=True)[:max_nodes])
        edges = [(s, d) for s, d in edges if s in top_nodes and d in top_nodes]
        all_nodes = top_nodes

    G.add_nodes_from(all_nodes)
    G.add_edges_from(edges)

    lines = [f"📊 {title}"] if title else []
    lines.append(f"节点: {G.number_of_nodes()}  边: {G.number_of_edges()}")
    lines.append("")

    # 统计信息
    if G.number_of_nodes() > 0:
        try:
            in_degrees = dict(G.in_degree())
            out_degrees = dict(G.out_degree())
            # 找出中心节点（出度最高）
            top_callers = sorted(out_degrees.items(), key=lambda x: x[1], reverse=True)[:5]
            lines.append("🔝 最活跃调用者:")
            for node, deg in top_callers:
                if deg > 0:
                    lines.append(f"   {node} → {deg} 次调用")
            lines.append("")

            # 孤立节点
            isolated = [n for n in all_nodes if in_degrees.get(n, 0) == 0 and out_degrees.get(n, 0) == 0]
            if isolated:
                lines.append(f"⚠️ 孤立节点 ({len(isolated)}): {', '.join(isolated[:10])}")
                lines.append("")
        except Exception:
            pass

    # 简单的层级文本表示
    # 使用拓扑排序或简单的 BFS 分层
    roots = [n for n in G.nodes() if G.in_degree(n) == 0]
    if not roots:
        roots = list(G.nodes())[:5]

    visited: Set[str] = set()
    lines.append("📈 调用链路:")

    def _show_tree(node: str, depth: int = 0, prefix: str = "", visited_path: Optional[Set[str]] = None):
        if visited_path is None:
            visited_path = set()
        if depth > 4 or node in visited_path:
            lines.append(f"{prefix}  {'  ' * depth}└─ ... (循环引用或深度超限)")
            return
        visited.add(node)
        successors = list(G.successors(node))
        for i, succ in enumerate(successors[:6]):
            is_last = (i == len(successors[:6]) - 1)
            connector = "└─" if is_last else "├─"
            lines.append(f"{prefix}  {'  ' * depth}{connector} {succ}")
            if len(successors) > 6 and i == 5:
                lines.append(f"{prefix}  {'  ' * depth}└─ ... ({len(successors)-6} 更多)")
                break
            _show_tree(succ, depth + 1, prefix, visited_path | {node})

    for root in roots[:5]:
        lines.append(f"  ▶ {root}")
        _show_tree(root, 0, "")

    if len(roots) > 5:
        lines.append(f"  ... 还有 {len(roots)-5} 个根节点")

    return "\n".join(lines)


def _cmd_viz_calls(ctx: CommandContext) -> None:
    """生成函数调用关系图。"""
    filepath = ctx.args[1] if len(ctx.args) > 1 else None
    if not filepath:
        print("用法: /viz calls <file>")
        return

    if not os.path.exists(filepath):
        print(R(f"❌ 文件不存在: {filepath}"))
        return

    tree = _parse_python_file(filepath)
    if not tree:
        print(R(f"❌ 无法解析文件: {filepath}"))
        return

    functions = _extract_functions(tree)
    if not functions:
        print(Y("⚠️ 未找到函数定义"))
        return

    # 构建边列表
    edges = []
    for func_name, calls in functions.items():
        for call in calls:
            # 只保留同一文件内的调用（简化）
            if call in functions:
                edges.append((func_name, call))

    print(_build_ascii_graph(edges, set(functions.keys()),
                              title=f"调用图: {filepath}", max_nodes=25))

    # 额外统计
    print(f"\n📊 统计: {len(functions)} 个函数, {len(edges)} 条内部调用边")


def _cmd_viz_deps(ctx: CommandContext) -> None:
    """生成模块依赖图。"""
    target = ctx.args[1] if len(ctx.args) > 1 else None

    # 收集所有 Python 文件
    py_files = []
    if target and os.path.isfile(target):
        py_files = [target]
    else:
        root = target if target and os.path.isdir(target) else "."
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in {
                "node_modules", "venv", ".venv", "__pycache__", ".git",
                "dist", "build"
            }]
            for fname in filenames:
                if fname.endswith(".py"):
                    py_files.append(os.path.join(dirpath, fname))

    if not py_files:
        print(Y("⚠️ 未找到 Python 文件"))
        return

    print(C(f"🔍 分析 {len(py_files)} 个文件...\n"))

    # 模块名映射
    module_names: Dict[str, str] = {}
    for fpath in py_files:
        rel = os.path.relpath(fpath)
        mod = rel.replace(os.sep, ".").replace(".py", "")
        module_names[fpath] = mod

    # 提取导入关系
    edges = []
    all_modules = set(module_names.values())
    external_imports: Dict[str, int] = {}

    for fpath in py_files:
        tree = _parse_python_file(fpath)
        if not tree:
            continue
        src_mod = module_names[fpath]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in all_modules:
                        edges.append((src_mod, top))
                    else:
                        external_imports[top] = external_imports.get(top, 0) + 1
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top = node.module.split(".")[0]
                    if top in all_modules:
                        edges.append((src_mod, top))
                    else:
                        external_imports[top] = external_imports.get(top, 0) + 1

    # 构建图
    nodes = set()
    for s, d in edges:
        nodes.add(s)
        nodes.add(d)

    print(_build_ascii_graph(edges, nodes, title="模块依赖图", max_nodes=30))

    # 外部依赖摘要
    if external_imports:
        print(f"\n📦 外部依赖 Top 10:")
        for mod, count in sorted(external_imports.items(), key=lambda x: x[1], reverse=True)[:10]:
            print(f"   {mod}: {count} 次导入")


def _cmd_viz_class(ctx: CommandContext) -> None:
    """生成类继承与成员图。"""
    filepath = ctx.args[1] if len(ctx.args) > 1 else None
    if not filepath:
        print("用法: /viz class <file>")
        return

    if not os.path.exists(filepath):
        print(R(f"❌ 文件不存在: {filepath}"))
        return

    tree = _parse_python_file(filepath)
    if not tree:
        print(R(f"❌ 无法解析文件: {filepath}"))
        return

    classes = _extract_classes(tree)
    if not classes:
        print(Y("⚠️ 未找到类定义"))
        return

    # 继承关系边
    edges = []
    for cls_name, info in classes.items():
        for base in info["bases"]:
            if base != "object" and base in classes:
                edges.append((base, cls_name))

    lines = [f"📊 类图: {filepath}", f"类数: {len(classes)}", ""]

    # 输出每个类的详情
    for cls_name, info in classes.items():
        base_str = f"({', '.join(info['bases'])})" if info["bases"] else ""
        lines.append(f"class {cls_name}{base_str}:")
        if info["attributes"]:
            for attr in sorted(info["attributes"])[:8]:
                lines.append(f"    {attr}")
            if len(info["attributes"]) > 8:
                lines.append(f"    ... ({len(info['attributes'])-8} 更多属性)")
        for method in info["methods"][:10]:
            marker = "📍 " if method in ("__init__", "__call__") else "    "
            lines.append(f"{marker}{method}()")
        if len(info["methods"]) > 10:
            lines.append(f"    ... ({len(info['methods'])-10} 更多方法)")
        lines.append("")

    # 继承链
    if edges:
        lines.append("📈 继承关系:")
        for base, child in edges:
            lines.append(f"    {base} → {child}")

    # 检测菱形继承
    try:
        import networkx as nx
        G = nx.DiGraph()
        G.add_edges_from(edges)
        for cls in classes:
            ancestors = list(nx.ancestors(G, cls))
            seen = set()
            dup = []
            for a in ancestors:
                paths = list(nx.all_simple_paths(G, a, cls))
                if len(paths) > 1:
                    dup.append((a, len(paths)))
            if dup:
                lines.append(f"\n⚠️ {cls} 存在多重继承路径:")
                for a, count in dup:
                    lines.append(f"    来自 {a}: {count} 条路径")
    except ImportError:
        pass

    print("\n".join(lines))
