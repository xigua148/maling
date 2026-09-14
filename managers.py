from __future__ import annotations

import importlib.util
import json
import os
import re
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from core import G, R, Y

# ---------------------------------------------------------------------------
def sanitize_session_name(name: str) -> str:
    """过滤会话名中的非法字符，避免 Windows/Unix 文件名问题。"""
    illegal = '<>:"/\\|?*'
    for ch in illegal:
        name = name.replace(ch, '_')
    name = name.strip('. ')
    if not name:
        name = "untitled"
    return name


class SessionManager:
    @staticmethod
    def list_sessions(pattern: str = "*.json") -> List[str]:
        excluded = {"snippets.json", "todos.json", "kb_index.json", "session_recovery.json", "maid_coder_cache.json", "audit.log"}
        return sorted([f for f in os.listdir(".") if f.endswith(".json") and f not in excluded])

    @staticmethod
    def delete_session(name: str, confirm: bool = True) -> str:
        safe_name = sanitize_session_name(name)
        filename = f"{safe_name}.json"
        if not os.path.exists(filename):
            return f"会话不存在: {filename}"
        if confirm:
            try:
                ans = input(Y(f"⚠️ 确定删除会话 {safe_name} 吗？此操作不可恢复 [Y/n]: "))
            except (EOFError, KeyboardInterrupt):
                ans = "n"
            if ans.strip().lower() not in ("y", "yes", ""):
                return "已取消删除。"
        os.remove(filename)
        return G(f"✅ 已删除会话: {filename}")


# ---------------------------------------------------------------------------
# 代码片段管理器
# ---------------------------------------------------------------------------
class SnippetManager:
    def __init__(self, filepath: str):
        self.filepath = filepath
        self._data: Dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.filepath):
            with open(self.filepath, "r", encoding="utf-8") as f:
                self._data = json.load(f)

    def _save(self) -> None:
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def save_snippet(self, name: str, content: str, language: str = "") -> str:
        self._data[name] = {
            "content": content,
            "language": language,
            "created_at": datetime.now().isoformat(),
        }
        self._save()
        return G(f"✅ 已保存片段: {name}")

    def list_snippets(self) -> str:
        if not self._data:
            return "暂无保存的代码片段。"
        lines = ["📚 代码片段列表:"]
        for name, info in self._data.items():
            lang = info.get("language", "?")
            created = info.get("created_at", "?")[:16]
            lines.append(f"  - {name} ({lang}) — {created}")
        return "\n".join(lines)

    def load_snippet(self, name: str) -> Optional[str]:
        return self._data.get(name, {}).get("content")

    def delete_snippet(self, name: str) -> str:
        if name in self._data:
            del self._data[name]
            self._save()
            return G(f"✅ 已删除片段: {name}")
        return f"片段不存在: {name}"

    def extract_from_text(self, text: str) -> Optional[Tuple[str, str]]:
        """从文本中提取第一个代码块。"""
        match = re.search(r"```(\w+)?\n(.*?)\n```", text, re.DOTALL)
        if match:
            lang = match.group(1) or "text"
            code = match.group(2)
            return lang, code
        return None


# ---------------------------------------------------------------------------
# Todo 管理器
# ---------------------------------------------------------------------------
class TodoManager:
    def __init__(self, filepath: str):
        self.filepath = filepath
        self._items: List[dict] = []
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.filepath):
            with open(self.filepath, "r", encoding="utf-8") as f:
                self._items = json.load(f)

    def _save(self) -> None:
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self._items, f, ensure_ascii=False, indent=2)

    def extract_from_text(self, text: str) -> int:
        """从文本中提取待办事项。"""
        patterns = [
            r"(?:需要|应该|TODO|FIXME|待办|待完成|待处理|必须)[：:]\s*(.+?)(?:\n|$)",
            r"[-*]\s*(?:TODO|FIXME|需要|应该)\s*[：:]?\s*(.+?)(?:\n|$)",
        ]
        count = 0
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                item = match.group(1).strip()
                if item and len(item) > 10:
                    self._items.append({
                        "text": item,
                        "done": False,
                        "created_at": datetime.now().isoformat(),
                    })
                    count += 1
        if count:
            self._save()
        return count

    def list_items(self) -> str:
        if not self._items:
            return "📝 暂无待办事项。"
        lines = ["📝 待办事项:"]
        for i, item in enumerate(self._items, 1):
            status = G("[✓]") if item["done"] else Y("[ ]")
            lines.append(f"  {status} {i}. {item['text']}")
        return "\n".join(lines)

    def add_item(self, text: str) -> str:
        """v1.5.0: 新增一条待办（GUI 待办对话框用）。"""
        text = (text or "").strip()
        if not text:
            return "待办内容不能为空。"
        self._items.append({
            "text": text,
            "done": False,
            "created_at": datetime.now().isoformat(),
        })
        self._save()
        return G(f"✅ 已添加待办: {text}")

    def delete_item(self, index: int) -> str:
        """v1.5.0: 删除指定序号（1-based）的待办（GUI 待办对话框用）。"""
        if 1 <= index <= len(self._items):
            removed = self._items.pop(index - 1)
            self._save()
            return G(f"🗑 已删除: {removed['text']}")
        return "无效的序号。"

    def items(self) -> List[dict]:
        """v1.5.0: 只读访问待办列表（GUI 渲染用，返回浅拷贝防误改内部状态）。"""
        return [dict(item) for item in self._items]

    def mark_done(self, index: int) -> str:
        if 1 <= index <= len(self._items):
            self._items[index - 1]["done"] = True
            self._save()
            return G(f"✅ 已标记完成: {self._items[index - 1]['text']}")
        return "无效的序号。"

    def undo_done(self, index: int) -> str:
        """v1.5.0: 取消完成标记（GUI 待办对话框取消勾选时用）。"""
        if 1 <= index <= len(self._items):
            self._items[index - 1]["done"] = False
            self._save()
            return f"↩ 已取消完成: {self._items[index - 1]['text']}"
        return "无效的序号。"

    def clear(self) -> str:
        self._items = []
        self._save()
        return G("✅ 已清空所有待办事项。")

    # ------------------------------------------------------------------
    # v1.7(F4/D-V17-03/D-V17-10): 贴身提醒 —— 复用 todos.json 单源（条目可选
    # 字段 due_at/remind_text/notified/quiet_pending，旧条目无字段 = 普通待办
    # 零迁移）。index 一律 1-based（与 list_items/mark_done 对齐）。
    # ------------------------------------------------------------------
    def add_reminder(self, remind_text: str, due_at: str) -> int:
        """登记提醒（新增一条带 due_at 的待办），返回 1-based index。"""
        self._items.append({
            "text": str(remind_text or "").strip(),
            "done": False,
            "created_at": datetime.now().isoformat(),
            "due_at": str(due_at or ""),
            "remind_text": str(remind_text or "").strip(),
            "notified": False,
            "quiet_pending": False,
        })
        self._save()
        return len(self._items)

    def _has_due(self, item: dict) -> bool:
        due = str(item.get("due_at", "") or "")
        if not due:
            return False
        try:
            datetime.fromisoformat(due)
            return True
        except (TypeError, ValueError):
            return False

    def due_items(self, now: Optional[datetime] = None) -> List[Tuple[int, dict]]:
        """到期未提醒条目 [(1-based index, item)]：due_at<=now ∧ 未 notified ∧ 未 done。"""
        now = now or datetime.now()
        out: List[Tuple[int, dict]] = []
        for i, item in enumerate(self._items, start=1):
            if not self._has_due(item) or item.get("done") or item.get("notified"):
                continue
            try:
                if datetime.fromisoformat(str(item["due_at"])) <= now:
                    out.append((i, dict(item)))
            except (TypeError, ValueError):
                continue
        return out

    def mark_notified(self, index: int) -> bool:
        """触发后标记（恰一次防重）。"""
        if 1 <= index <= len(self._items):
            self._items[index - 1]["notified"] = True
            self._items[index - 1].pop("quiet_pending", None)
            self._save()
            return True
        return False

    def mark_quiet_pending(self, index: int) -> bool:
        """quiet 时段降级（Q-C4）：顺延补看，不弹通知。"""
        if 1 <= index <= len(self._items):
            self._items[index - 1]["quiet_pending"] = True
            self._save()
            return True
        return False

    def cancel_reminder(self, index: int) -> bool:
        """取消提醒（删除该条目，1-based）。"""
        if 1 <= index <= len(self._items):
            self._items.pop(index - 1)
            self._save()
            return True
        return False

    def today_items(self, now: Optional[datetime] = None) -> List[dict]:
        """今日有 due_at 的条目（不论是否已提醒；时间排序，列览用）。"""
        now = now or datetime.now()
        today = now.date()
        out: List[dict] = []
        for item in self._items:
            if not self._has_due(item):
                continue
            try:
                if datetime.fromisoformat(str(item["due_at"])).date() == today:
                    out.append(dict(item))
            except (TypeError, ValueError):
                continue
        out.sort(key=lambda d: str(d.get("due_at", "")))
        return out


# ---------------------------------------------------------------------------
# Git 集成
# 插件系统
# ---------------------------------------------------------------------------
class PluginManager:
    def __init__(self, plugins_dir: str):
        self.plugins_dir = plugins_dir
        self._handlers: Dict[str, Callable] = {}
        self._plugins: List[str] = []
        self._command_plugin: Dict[str, str] = {}  # command -> plugin_name

    def load_plugins(self) -> None:
        if not os.path.isdir(self.plugins_dir):
            return
        for fname in sorted(os.listdir(self.plugins_dir)):
            if not fname.endswith(".py") or fname.startswith("_"):
                continue
            path = os.path.join(self.plugins_dir, fname)
            try:
                spec = importlib.util.spec_from_file_location(fname[:-3], path)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    # v10.14 沙箱收敛：
                    # 移除 __import__/open/input/globals——这些是「开了等于没开」：
                    #   - __import__：能拉任何模块（os/subprocess/socket），再叠加
                    #     下文的 getattr 就能绕过一切；
                    #   - open：能读写任意文件；
                    #   - input：能阻塞/读取 stdin；
                    #   - globals：能拿到真实 globals 字典，配合 setattr 改写
                    #     自己的 __builtins__ 直接脱笼。
                    # 保留 getattr/setattr/delattr/vars/locals：单独使用无危险，
                    # 但仍然允许插件通过「拿到一个对象后访问其属性」的方式
                    # 间接调用危险 API。真正的硬隔离需要单独进程 + 沙箱语言
                    # 限制（rpyc-jail、firejail、seccomp 等），目前这里只做
                    # 内置名字黑名单的「best-effort」，文档诚实标注。
                    _RESTRICTED_BUILTINS = {
                        "abs": abs, "all": all, "any": any, "ascii": ascii,
                        "bin": bin, "bool": bool, "bytearray": bytearray,
                        "bytes": bytes, "callable": callable, "chr": chr,
                        "classmethod": classmethod,
                        "complex": complex, "dict": dict,
                        "dir": dir, "divmod": divmod, "enumerate": enumerate,
                        "filter": filter, "float": float, "format": format,
                        "frozenset": frozenset, "getattr": getattr,
                        "hasattr": hasattr, "hash": hash,
                        "help": help, "hex": hex, "id": id,
                        "int": int, "isinstance": isinstance, "issubclass": issubclass,
                        "iter": iter, "len": len, "list": list,
                        "map": map, "max": max, "memoryview": memoryview,
                        "min": min, "next": next, "object": object, "oct": oct,
                        "ord": ord, "pow": pow, "print": print,
                        "property": property, "range": range, "repr": repr,
                        "reversed": reversed, "round": round, "set": set,
                        "setattr": setattr, "slice": slice, "sorted": sorted,
                        "staticmethod": staticmethod, "str": str, "sum": sum,
                        "super": super, "tuple": tuple, "type": type, "vars": vars,
                        "zip": zip, "Exception": Exception, "BaseException": BaseException,
                        "ArithmeticError": ArithmeticError, "AssertionError": AssertionError,
                        "AttributeError": AttributeError, "BlockingIOError": BlockingIOError,
                        "BrokenPipeError": BrokenPipeError, "BufferError": BufferError,
                        "BytesWarning": BytesWarning, "ChildProcessError": ChildProcessError,
                        "ConnectionAbortedError": ConnectionAbortedError,
                        "ConnectionError": ConnectionError,
                        "ConnectionRefusedError": ConnectionRefusedError,
                        "ConnectionResetError": ConnectionResetError,
                        "DeprecationWarning": DeprecationWarning, "EOFError": EOFError,
                        "EnvironmentError": EnvironmentError, "FileExistsError": FileExistsError,
                        "FileNotFoundError": FileNotFoundError, "FloatingPointError": FloatingPointError,
                        "FutureWarning": FutureWarning, "GeneratorExit": GeneratorExit,
                        "IOError": IOError, "ImportError": ImportError,
                        "ImportWarning": ImportWarning, "IndentationError": IndentationError,
                        "IndexError": IndexError, "InterruptedError": InterruptedError,
                        "IsADirectoryError": IsADirectoryError, "KeyError": KeyError,
                        "KeyboardInterrupt": KeyboardInterrupt, "LookupError": LookupError,
                        "MemoryError": MemoryError, "ModuleNotFoundError": ModuleNotFoundError,
                        "NameError": NameError, "NotADirectoryError": NotADirectoryError,
                        "NotImplementedError": NotImplementedError, "OSError": OSError,
                        "OverflowError": OverflowError, "PendingDeprecationWarning": PendingDeprecationWarning,
                        "PermissionError": PermissionError, "ProcessLookupError": ProcessLookupError,
                        "RecursionError": RecursionError, "ReferenceError": ReferenceError,
                        "ResourceWarning": ResourceWarning, "RuntimeError": RuntimeError,
                        "RuntimeWarning": RuntimeWarning, "StopAsyncIteration": StopAsyncIteration,
                        "StopIteration": StopIteration, "SyntaxError": SyntaxError,
                        "SyntaxWarning": SyntaxWarning, "SystemError": SystemError,
                        "SystemExit": SystemExit, "TabError": TabError, "TimeoutError": TimeoutError,
                        "TypeError": TypeError, "UnboundLocalError": UnboundLocalError,
                        "UnicodeDecodeError": UnicodeDecodeError,
                        "UnicodeEncodeError": UnicodeEncodeError,
                        "UnicodeError": UnicodeError, "UnicodeTranslateError": UnicodeTranslateError,
                        "UnicodeWarning": UnicodeWarning, "UserWarning": UserWarning,
                        "ValueError": ValueError, "Warning": Warning,
                        "ZeroDivisionError": ZeroDivisionError,
                        "True": True, "False": False, "None": None,
                    }
                    mod.__builtins__ = _RESTRICTED_BUILTINS
                    spec.loader.exec_module(mod)
                    if hasattr(mod, "register"):
                        # 记录该插件注册前已有的命令，以便区分
                        before = set(self._handlers.keys())
                        mod.register(self)
                        after = set(self._handlers.keys())
                        for cmd in after - before:
                            self._command_plugin[cmd] = fname
                        self._plugins.append(fname)
            except Exception:
                pass

    def register(self, command: str, handler: Callable) -> None:
        self._handlers[command] = handler

    def handle(self, command: str, args: List[str], session: Any) -> Optional[str]:
        handler = self._handlers.get(command)
        if handler:
            try:
                return handler(args, session)
            except Exception as e:
                return f"插件执行失败: {e}"
        return None

    def register_with_router(self, router: Any) -> None:
        """将插件注册的所有命令桥接到 CommandRouter。"""
        for cmd_name, handler in self._handlers.items():
            router.register(
                cmd_name,
                lambda ctx, h=handler: self._wrap_plugin_handler(h, ctx),
                description=f"插件命令: {cmd_name}",
                usage=f"/{cmd_name}",
                category="扩展",
            )

    def _wrap_plugin_handler(self, handler: Callable, ctx: Any) -> None:
        """适配插件 handler 签名（旧: (args, session) → 新: ctx）."""
        result = handler(ctx.args, ctx.session)
        if result is not None:
            print(result)

    def list_plugins(self) -> str:
        if not self._plugins:
            return "🔌 未加载任何插件。"
        lines = ["🔌 已加载插件:"]
        for p in self._plugins:
            cmds = [k for k, v in self._command_plugin.items() if v == p]
            lines.append(f"  - {p} (命令: {', '.join(cmds) if cmds else '无'})")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 统计追踪
# ---------------------------------------------------------------------------
class StatsTracker:
    def __init__(self):
        self.start_time = time.time()
        self.total_messages = 0
        self.total_tokens = 0
        self.token_usage: Dict[str, int] = {
            "normal": 0, "agent": 0, "workflow": 0, "multi": 0,
            "search": 0, "tool": 0,
        }
        self.mode_usage: Dict[str, int] = {
            "deep": 0, "coding": 0, "multi": 0, "stream": 0,
            "agent": 0, "search": 0, "tool": 0,
        }

    def add_message(self) -> None:
        self.total_messages += 1

    def add_tokens(self, tokens: int, mode: str = "normal") -> None:
        self.total_tokens += tokens
        self.token_usage[mode] = self.token_usage.get(mode, 0) + tokens

    def bump_mode(self, mode: str) -> None:
        self.mode_usage[mode] = self.mode_usage.get(mode, 0) + 1

    def report(self) -> str:
        elapsed = time.time() - self.start_time
        hours = int(elapsed // 3600)
        mins = int((elapsed % 3600) // 60)
        secs = int(elapsed % 60)

        # 估算费用 (DeepSeek 参考价: 输入 1元/百万tokens, 输出 2元/百万tokens)
        cost = self.total_tokens * 1.5 / 1_000_000

        lines = [
            "📊 会话统计",
            f"  会话时长: {hours}h {mins}m {secs}s",
            f"  总消息数: {self.total_messages}",
            f"  总Token:  {self.total_tokens:,}",
            f"  预估费用: ¥{cost:.4f}",
            "",
            "  Token 消耗（按模式）:",
        ]
        for mode, tokens in sorted(self.token_usage.items()):
            if tokens > 0:
                pct = tokens / self.total_tokens * 100 if self.total_tokens > 0 else 0
                lines.append(f"    {mode}: {tokens:,} ({pct:.1f}%)")
        lines.append("")
        lines.append("  模式触发次数:")
        for mode, count in sorted(self.mode_usage.items()):
            if count > 0:
                lines.append(f"    {mode}: {count}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 输出打印
