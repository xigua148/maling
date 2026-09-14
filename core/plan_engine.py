from __future__ import annotations

import difflib
import glob as glob_mod
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from utils import _validate_file_path, _backup_path


# ---------------------------------------------------------------------------
# FileChange
# ---------------------------------------------------------------------------
@dataclass
class FileChange:
    """单个文件的变更方案。"""
    filepath: str
    original: str
    modified: str
    reason: str            # AI 说明为何修改此文件
    confidence: float      # 0~1，AI 对修改正确性的置信度


# ---------------------------------------------------------------------------
# PlanStore
# ---------------------------------------------------------------------------
class PlanStore:
    """持有跨文件修改的中间状态，支持 preview / apply / reject 完整生命周期。"""

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self._changes: List[FileChange] = []
        self._applied: List[str] = []   # 已应用的文件路径
        self._backup_map: Dict[str, str] = {}  # filepath -> .bak path

    # ── 生命周期 ──

    def load(self, changes: List[FileChange]) -> None:
        """加载 PlanEngine 生成的新方案，清空旧方案。"""
        self._changes = changes
        self._applied.clear()
        self.logger.info("PlanStore: 加载 %d 个文件变更", len(changes))

    def clear(self) -> None:
        """清空所有待修改（reject）。"""
        self._changes.clear()
        self._applied.clear()
        self.logger.info("PlanStore: 已清空")

    # ── Preview ──

    def preview(self) -> str:
        """生成所有待修改的 diff 预览文本。"""
        if not self._changes:
            return "当前没有待应用的修改方案。"
        lines = [f"📋 待修改文件: {len(self._changes)} 个", ""]
        for i, change in enumerate(self._changes, 1):
            diff = list(difflib.unified_diff(
                change.original.splitlines(keepends=True),
                change.modified.splitlines(keepends=True),
                fromfile=change.filepath,
                tofile=change.filepath + ".new",
            ))
            diff_str = "".join(diff)
            status = "✅ 已应用" if change.filepath in self._applied else "⏳ 待应用"
            lines.append(f"[{i}] {status} {change.filepath}")
            lines.append(f"    原因: {change.reason}")
            if diff_str:
                lines.append(f"```diff\n{diff_str[:800]}\n```")
            lines.append("")
        return "\n".join(lines)

    # ── Apply ──

    def apply_all(self, workspace: str) -> str:
        """全部应用，返回操作结果摘要。"""
        results = []
        for change in self._changes:
            if change.filepath in self._applied:
                continue
            ok, msg = self._apply_single(change, workspace)
            results.append(f"{'✅' if ok else '❌'} {change.filepath}: {msg}")
        return "\n".join(results)

    def apply_one(self, index: int, workspace: str) -> str:
        """按索引应用单个文件。"""
        if index < 0 or index >= len(self._changes):
            return "索引越界"
        change = self._changes[index]
        if change.filepath in self._applied:
            return "该文件已应用"
        ok, msg = self._apply_single(change, workspace)
        return f"{'✅' if ok else '❌'} {change.filepath}: {msg}"

    def _apply_single(self, change: FileChange, workspace: str) -> Tuple[bool, str]:
        """应用单个文件变更，创建备份。"""
        try:
            # 路径安全检查
            ok, msg = _validate_file_path(change.filepath, workspace)
            if not ok:
                return False, msg
            # 备份
            bak_path = _backup_path(change.filepath)
            with open(bak_path, "w", encoding="utf-8") as f:
                f.write(change.original)
            self._backup_map[change.filepath] = bak_path
            # 写入修改
            with open(change.filepath, "w", encoding="utf-8") as f:
                f.write(change.modified)
            self._applied.append(change.filepath)
            return True, f"已应用，备份: {bak_path}"
        except Exception as e:
            return False, str(e)

    # ── Reject ──

    def reject(self) -> str:
        """取消所有未应用的修改。"""
        pending = [c for c in self._changes if c.filepath not in self._applied]
        self._changes = [c for c in self._changes if c.filepath in self._applied]
        return f"已取消 {len(pending)} 个未应用的修改方案"

    # ── 辅助 ──

    def list_pending(self) -> List[FileChange]:
        return [c for c in self._changes if c.filepath not in self._applied]


# ---------------------------------------------------------------------------
# PlanEngine
# ---------------------------------------------------------------------------
class PlanEngine:
    """分析用户需求，确定影响范围，生成跨文件修改方案。"""

    def __init__(self, api, cfg, project_ctx=None):
        self.api = api
        self.cfg = cfg
        self.project_ctx = project_ctx

    def analyze(self, requirement: str, session_history: List[dict]) -> List[FileChange]:
        """主入口：接收自然语言需求，返回跨文件变更列表。"""
        # Step 1: 确定影响范围
        affected_files = self._discover_affected_files(requirement)
        if not affected_files:
            return []

        # Step 2: 逐个生成修改
        changes: List[FileChange] = []
        for filepath in affected_files[:10]:  # 上限保护
            original = self._safe_read(filepath)
            if original is None:
                continue
            modified = self._generate_modification(filepath, original, requirement, session_history)
            if modified and modified != original:
                changes.append(FileChange(
                    filepath=filepath,
                    original=original,
                    modified=modified,
                    reason=self._explain_change(filepath, original, modified, requirement),
                    confidence=0.8,
                ))
        return changes

    def _discover_affected_files(self, requirement: str) -> List[str]:
        """发现可能受影响的文件列表。"""
        candidates = []
        # 策略 A：若 project_ctx 已初始化，用索引缩小范围
        if self.project_ctx and self.project_ctx.index:
            candidates = list(self.project_ctx.index.files.keys())
            # 将相对路径转为绝对路径（基于项目根目录）
            root = self.project_ctx.index.root
            candidates = [os.path.join(root, c) for c in candidates]
        else:
            # 策略 B：回退到当前工作目录的源码文件扫描
            candidates = self._fallback_discover()

        # 去重并限制数量
        candidates = list(dict.fromkeys(candidates))
        if len(candidates) > 20:
            candidates = candidates[:20]
        return candidates

    def _fallback_discover(self) -> List[str]:
        """回退策略：扫描工作目录下的常见源码文件。"""
        workspace = getattr(self.cfg, "workspace", ".")
        candidates = []
        extensions = {".py", ".js", ".ts", ".go", ".java", ".rs", ".c", ".cpp", ".h", ".hpp", ".rb", ".php"}
        for dirpath, dirnames, filenames in os.walk(workspace):
            # 跳过常见忽略目录
            dirnames[:] = [d for d in dirnames if d not in {
                ".git", "node_modules", "__pycache__", ".venv", "venv",
                "dist", "build", ".idea", ".vscode"
            }]
            for fname in filenames:
                if os.path.splitext(fname)[1].lower() in extensions:
                    candidates.append(os.path.join(dirpath, fname))
            if len(candidates) >= 50:
                break
        return candidates

    def _safe_read(self, filepath: str) -> Optional[str]:
        """安全读取文件内容。"""
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            return None

    def _generate_modification(self, filepath: str, original: str,
                               requirement: str, history: List[dict]) -> Optional[str]:
        """对单个文件调用 AI 生成修改后的完整内容。"""
        messages = [
            {"role": "system", "content": "你是一位资深工程师，根据用户需求修改代码文件。输出完整的修改后文件内容，用 ``` 包裹。"},
            {"role": "user", "content": (
                f"需求: {requirement}\n"
                f"文件: {filepath}\n\n"
                f"原始内容:\n```\n{original[:8000]}\n```\n\n"
                f"请输出修改后的完整文件内容。"
            )},
        ]
        try:
            resp = self.api.chat(messages, max_tokens=self.cfg.api_max_tokens)
            content = resp["choices"][0]["message"].get("content", "")
            # 提取代码块
            match = re.search(r"```(?:\w+)?\n(.*?)\n```", content, re.DOTALL)
            return match.group(1) if match else content
        except Exception:
            return None

    def _explain_change(self, filepath: str, original: str, modified: str, requirement: str) -> str:
        """生成变更说明（一句话）。"""
        diff = list(difflib.unified_diff(original.splitlines(), modified.splitlines(), lineterm=""))
        added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
        removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
        return f"增 {added} 行 / 删 {removed} 行 — 适配需求: {requirement[:50]}..."
