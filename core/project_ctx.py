from __future__ import annotations

import glob as glob_mod
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# networkx 优雅降级
try:
    import networkx as nx
    _HAS_NETWORKX = True
except ImportError:
    _HAS_NETWORKX = False


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------
@dataclass
class FileNode:
    """项目索引中的单文件元数据。"""
    path: str
    size: int
    language: str
    imports: List[str] = field(default_factory=list)
    imported_by: List[str] = field(default_factory=list)
    summary: str = ""


# ---------------------------------------------------------------------------
# ProjectDetector
# ---------------------------------------------------------------------------
class ProjectDetector:
    """通过标记文件自动检测项目类型与语言生态。"""

    MARKERS: Dict[str, List[str]] = {
        "python": ["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile"],
        "node":   ["package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"],
        "go":     ["go.mod", "go.sum"],
        "java":   ["pom.xml", "build.gradle", "build.gradle.kts"],
        "rust":   ["Cargo.toml", "Cargo.lock"],
    }

    def detect(self, root: str) -> Tuple[str, float]:
        """返回 (project_type, confidence)，confidence 为 0~1 的置信度。"""
        for ptype, markers in self.MARKERS.items():
            matched = sum(1 for m in markers if os.path.exists(os.path.join(root, m)))
            if matched:
                confidence = min(1.0, 0.5 + 0.25 * matched)
                return ptype, confidence
        return "unknown", 0.0

    def find_project_root(self, start_path: str = ".") -> Optional[str]:
        """向上遍历目录树，找到包含标记文件的最深目录。"""
        current = Path(start_path).resolve()
        best_root = None
        while current != current.parent:
            if any(
                (current / marker).exists()
                for markers in self.MARKERS.values()
                for marker in markers
            ):
                best_root = str(current)
            current = current.parent
        return best_root


# ---------------------------------------------------------------------------
# ProjectIndex
# ---------------------------------------------------------------------------
class ProjectIndex:
    """维护项目的文件索引、模块依赖图和语言分类。"""

    SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
                 "dist", "build", ".idea", ".vscode", ".github", ".svn",
                 ".pytest_cache", ".mypy_cache", ".tox"}
    SKIP_PATTERNS = [r"\.pyc$", r"\.class$", r"\.o$", r"\.exe$", r"\.dll$", r"\.so$"]

    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self.files: Dict[str, FileNode] = {}      # rel_path -> FileNode
        self.modules: Dict[str, str] = {}         # module_name -> rel_path
        self.project_type, self.confidence = ProjectDetector().detect(root)
        self._last_indexed: Optional[float] = None

        # 依赖图：networkx 优雅降级
        if _HAS_NETWORKX:
            self.dependency_graph: Any = nx.DiGraph()
        else:
            self.dependency_graph: Any = _SimpleGraph()

    def build(self, max_files: int = 1000) -> dict:
        """全量扫描项目目录，构建索引和依赖图。

        返回统计信息：{"files": N, "modules": N, "dependencies": N}
        """
        self.files.clear()
        self.modules.clear()
        if _HAS_NETWORKX:
            self.dependency_graph.clear()
        else:
            self.dependency_graph = _SimpleGraph()

        count = 0
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in self.SKIP_DIRS]
            for fname in filenames:
                if any(re.search(p, fname) for p in self.SKIP_PATTERNS):
                    continue
                if count >= max_files:
                    break
                full = os.path.join(dirpath, fname)
                rel = os.path.relpath(full, self.root)
                node = self._analyze_file(full, rel)
                self.files[rel] = node
                self.dependency_graph.add_node(rel, **{
                    "path": node.path,
                    "size": node.size,
                    "language": node.language,
                })
                count += 1
            if count >= max_files:
                break

        # 第二遍：解析跨文件依赖
        self._resolve_dependencies()
        self._last_indexed = time.time()
        return {
            "files": len(self.files),
            "modules": len(self.modules),
            "dependencies": self.dependency_graph.number_of_edges(),
        }

    def _analyze_file(self, full_path: str, rel_path: str) -> FileNode:
        """分析单个文件：语言检测、导入语句提取。"""
        ext = os.path.splitext(rel_path)[1]
        language = self._ext_to_language(ext)
        imports: List[str] = []
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            imports = self._extract_imports(content, language)
        except Exception:
            pass
        return FileNode(
            path=rel_path,
            size=os.path.getsize(full_path),
            language=language,
            imports=imports,
            imported_by=[],
        )

    def _ext_to_language(self, ext: str) -> str:
        """扩展名到语言映射。"""
        mapping = {
            ".py": "python", ".pyi": "python",
            ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
            ".ts": "typescript", ".tsx": "typescript",
            ".go": "go",
            ".java": "java",
            ".rs": "rust",
            ".c": "c", ".h": "c",
            ".cpp": "cpp", ".hpp": "cpp", ".cc": "cpp",
            ".rb": "ruby",
            ".php": "php",
            ".swift": "swift",
            ".kt": "kotlin",
            ".scala": "scala",
            ".sh": "shell", ".bash": "shell",
            ".html": "html", ".htm": "html",
            ".css": "css", ".scss": "css", ".sass": "css", ".less": "css",
            ".json": "json", ".yaml": "yaml", ".yml": "yaml",
            ".toml": "toml", ".xml": "xml", ".md": "markdown",
        }
        return mapping.get(ext.lower(), "unknown")

    def _extract_imports(self, content: str, language: str) -> List[str]:
        """按语言提取导入语句中的模块名。"""
        if language == "python":
            return re.findall(r"^(?:from|import)\s+([a-zA-Z_][a-zA-Z0-9_.]*)", content, re.M)
        elif language in ("javascript", "typescript"):
            return re.findall(r"import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]", content)
        elif language == "go":
            return re.findall(r'import\s+[^\n]*["\']([^"\']+)["\']', content)
        elif language == "java":
            return re.findall(r"^import\s+([a-zA-Z_][a-zA-Z0-9_.]*);", content, re.M)
        elif language == "rust":
            return re.findall(r"^use\s+([a-zA-Z_][a-zA-Z0-9_:]*)", content, re.M)
        return []

    def _resolve_dependencies(self) -> None:
        """解析跨文件依赖，建立 import -> file 的反向索引。"""
        # 构建模块名到文件路径的映射（简化：文件名 = 模块名）
        for rel, node in self.files.items():
            basename = os.path.splitext(os.path.basename(rel))[0]
            if basename and basename not in ("__init__", "index", "mod"):
                self.modules[basename] = rel

        # 建立依赖边
        for rel, node in self.files.items():
            for imp in node.imports:
                # 尝试匹配本地模块
                parts = imp.replace("/", ".").split(".")
                for part in parts:
                    if part in self.modules and self.modules[part] != rel:
                        target = self.modules[part]
                        self.dependency_graph.add_edge(rel, target)
                        if target in self.files:
                            if rel not in self.files[target].imported_by:
                                self.files[target].imported_by.append(rel)

    def get_context_snapshot(self, max_tokens: int = 4000) -> str:
        """生成供 AI 使用的项目上下文摘要，控制 token 预算。"""
        lines = [
            f"项目类型: {self.project_type} (置信度: {self.confidence:.0%})",
            f"文件总数: {len(self.files)}",
            f"索引时间: {datetime.fromtimestamp(self._last_indexed).isoformat() if self._last_indexed else 'N/A'}",
            "",
            "=== 项目结构 ===",
        ]
        # 输出前 30 个文件的简要信息
        for i, (rel, node) in enumerate(self.files.items()):
            if i >= 30:
                lines.append(f"... 还有 {len(self.files) - 30} 个文件")
                break
            lines.append(f"- {rel} ({node.language}, {node.size}B)")
        lines.append("")
        lines.append("=== 关键依赖 ===")
        # 输出入度最高的 10 个文件（被引用最多）
        top_deps = sorted(
            self.files.values(),
            key=lambda n: len(n.imported_by),
            reverse=True,
        )[:10]
        for node in top_deps:
            lines.append(f"- {node.path} (被 {len(node.imported_by)} 个文件引用)")
        snapshot = "\n".join(lines)
        # 若超出预算，截断并提示
        if len(snapshot) > max_tokens * 4:  # 粗略 1 token ≈ 4 字符
            snapshot = snapshot[:max_tokens * 4] + "\n...[上下文已截断]"
        return snapshot


# ---------------------------------------------------------------------------
# _SimpleGraph — networkx 降级实现
# ---------------------------------------------------------------------------
class _SimpleGraph:
    """networkx.DiGraph 的轻量级降级实现。"""

    def __init__(self):
        self._nodes: Dict[str, dict] = {}
        self._edges: set = set()
        self._adj: Dict[str, set] = {}
        self._pred: Dict[str, set] = {}

    def clear(self) -> None:
        self._nodes.clear()
        self._edges.clear()
        self._adj.clear()
        self._pred.clear()

    def add_node(self, node: str, **attr) -> None:
        self._nodes[node] = attr
        self._adj.setdefault(node, set())
        self._pred.setdefault(node, set())

    def add_edge(self, u: str, v: str) -> None:
        self._adj.setdefault(u, set()).add(v)
        self._pred.setdefault(v, set()).add(u)
        self._edges.add((u, v))
        # 确保节点存在
        if u not in self._nodes:
            self._nodes[u] = {}
        if v not in self._nodes:
            self._nodes[v] = {}

    def number_of_edges(self) -> int:
        return len(self._edges)

    def number_of_nodes(self) -> int:
        return len(self._nodes)

    def has_node(self, node: str) -> bool:
        return node in self._nodes

    def successors(self, node: str):
        return iter(self._adj.get(node, set()))

    def predecessors(self, node: str):
        return iter(self._pred.get(node, set()))

    def in_degree(self, node: str) -> int:
        return len(self._pred.get(node, set()))

    def out_degree(self, node: str) -> int:
        return len(self._adj.get(node, set()))


# ---------------------------------------------------------------------------
# ProjectContext
# ---------------------------------------------------------------------------
class ProjectContext:
    """管理项目级上下文的生命周期：检测 → 索引 → 注入 → 淘汰。"""

    def __init__(self, session):
        self.session = session
        self.index: Optional[ProjectIndex] = None
        self._injected_system_msg: Optional[dict] = None
        self._context_token_budget = 4000  # 可配置

    def initialize(self, path: str = ".") -> str:
        """初始化项目上下文。返回状态摘要。"""
        detector = ProjectDetector()
        root = detector.find_project_root(path)
        if not root:
            return "未检测到项目根目录（未找到 pyproject.toml/package.json/go.mod/pom.xml 等标记文件）"
        self.index = ProjectIndex(root)
        stats = self.index.build()
        self._inject_to_session()
        return (
            f"项目上下文已初始化\n"
            f"根目录: {root}\n"
            f"类型: {self.index.project_type}\n"
            f"文件: {stats['files']} | 模块: {stats['modules']} | 依赖: {stats['dependencies']}"
        )

    def _inject_to_session(self) -> None:
        """将项目上下文以 system message 形式注入对话历史。"""
        if not self.index:
            return
        snapshot = self.index.get_context_snapshot(self._context_token_budget)
        msg = {
            "role": "system",
            "content": (
                f"[项目上下文]\n{snapshot}\n\n"
                f"你在回答与代码相关的问题时，应参考上述项目结构和依赖关系。"
            )
        }
        self._injected_system_msg = msg
        self.session.history.append(msg)

    def refresh(self) -> str:
        """重建索引并刷新注入的上下文。"""
        if not self.index:
            return "项目上下文尚未初始化，请先执行 /project index"
        # 移除旧的注入消息
        if self._injected_system_msg in self.session.history:
            self.session.history.remove(self._injected_system_msg)
        stats = self.index.build()
        self._inject_to_session()
        return f"索引已重建 | 文件: {stats['files']} | 依赖: {stats['dependencies']}"

    def add_file(self, rel_path: str) -> str:
        """手动将文件纳入上下文（支持 glob）。"""
        if not self.index:
            return "项目上下文尚未初始化"
        # 解析 glob 并添加到索引
        added = 0
        import glob as glob_mod
        for match in glob_mod.glob(os.path.join(self.index.root, rel_path), recursive=True):
            if os.path.isfile(match):
                rel = os.path.relpath(match, self.index.root)
                if rel not in self.index.files:
                    node = self.index._analyze_file(match, rel)
                    self.index.files[rel] = node
                    added += 1
        if added:
            self.index._resolve_dependencies()
            self.refresh()
        return f"已添加 {added} 个文件到项目上下文"

    def get_status(self) -> str:
        """返回项目状态的可读文本。"""
        if not self.index:
            return "项目上下文尚未初始化"
        lines = [
            f"项目根目录: {self.index.root}",
            f"检测类型: {self.index.project_type} (置信度 {self.index.confidence:.0%})",
            f"索引文件数: {len(self.index.files)}",
            f"模块依赖边: {self.index.dependency_graph.number_of_edges()}",
            f"最后索引: {datetime.fromtimestamp(self.index._last_indexed).isoformat() if self.index._last_indexed else 'N/A'}",
            "",
            "语言分布:",
        ]
        lang_counts: Dict[str, int] = {}
        for node in self.index.files.values():
            lang_counts[node.language] = lang_counts.get(node.language, 0) + 1
        for lang, cnt in sorted(lang_counts.items(), key=lambda x: -x[1]):
            lines.append(f"  {lang}: {cnt}")
        return "\n".join(lines)
