from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional, Tuple

from core import G, R, Y, C, _HAS_DDGS, DDGS

# ---------------------------------------------------------------------------
class GitHelper:
    @staticmethod
    def is_git_repo(path: str = ".") -> bool:
        return os.path.isdir(os.path.join(path, ".git"))

    @staticmethod
    def _run_git(args: List[str], cwd: str = ".") -> Tuple[int, str, str]:
        try:
            result = subprocess.run(
                ["git"] + args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=cwd,
                timeout=10,
            )
            return result.returncode, result.stdout, result.stderr
        except Exception as e:
            return -1, "", str(e)

    @classmethod
    def status(cls, cwd: str = ".") -> str:
        code, out, err = cls._run_git(["status", "-sb"], cwd)
        if code != 0:
            return f"Git status 失败: {err}"
        return f"📊 Git Status:\n```\n{out or '(无变更)'}\n```"

    @classmethod
    def diff(cls, cwd: str = ".") -> str:
        code, out, err = cls._run_git(["diff"], cwd)
        if code != 0:
            return f"Git diff 失败: {err}"
        display = out[:3000] if out else "(无变更)"
        if len(out) > 3000:
            display += "\n... (已截断)"
        return f"📋 Git Diff:\n```diff\n{display}\n```"

    @classmethod
    def log(cls, n: int = 5, cwd: str = ".") -> str:
        code, out, err = cls._run_git(["log", "--oneline", f"-n{n}"], cwd)
        if code != 0:
            return f"Git log 失败: {err}"
        return f"📜 Git Log (最近{n}条):\n```\n{out}\n```"

    @classmethod
    def commit(cls, message: str, cwd: str = ".") -> str:
        code, _, err = cls._run_git(["add", "-A"], cwd)
        if code != 0:
            return f"Git add 失败: {err}"
        code, out, err = cls._run_git(["commit", "-m", message], cwd)
        if code != 0:
            return f"Git commit 失败: {err}"
        return G(f"✅ Git commit 成功: {message}")


# ---------------------------------------------------------------------------
# 代码执行沙箱
# ---------------------------------------------------------------------------
class CodeSandbox:
    # 允许导入的安全模块白名单
    SAFE_MODULES = {
        "math", "random", "datetime", "re", "json", "string",
        "itertools", "functools", "statistics", "decimal", "fractions",
        "hashlib", "uuid", "time", "collections", "typing", "enum",
        "numbers", "textwrap", "dataclasses",
        "heapq", "csv", "html",
    }
    # 禁止调用的危险内置函数
    DANGEROUS_BUILTINS = {"eval", "exec", "open", "__import__", "compile", "input", "getattr", "getattribute"}
    # 禁止调用的文件系统方法（通过属性链访问）
    DANGEROUS_METHODS = {
        "read_text", "write_text", "read_bytes", "write_bytes",
        "open", "unlink", "rename", "chmod",
        "mkdir", "rmdir", "touch", "symlink_to", "link_to",
        "deepcopy",
    }

    def __init__(self, timeout: int = 5):
        self.timeout = timeout

    def extract_code(self, text: str) -> Optional[Tuple[str, str]]:
        """提取第一个 Python 代码块。"""
        for match in re.finditer(r"```(?:python|py)\n(.*?)\n```", text, re.DOTALL):
            return "python", match.group(1)
        return None

    def _check_ast_safe(self, code: str) -> Tuple[bool, str]:
        """用 AST 检查代码安全性。返回 (是否安全, 原因)。"""
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, f"语法错误: {e}"

        for node in ast.walk(tree):
            # 检查导入语句
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name.split(".")[0]
                    if mod not in self.SAFE_MODULES:
                        return False, f"禁止导入模块: {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                mod = node.module.split(".")[0] if node.module else ""
                if mod not in self.SAFE_MODULES:
                    return False, f"禁止导入模块: {node.module}"
            # 检查危险内置函数调用
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in self.DANGEROUS_BUILTINS:
                    return False, f"禁止调用危险函数: {func.id}"
            # 检查属性访问（允许常用魔术方法，禁止危险内省属性）
            elif isinstance(node, ast.Attribute):
                ALLOWED_DUNDERS = {
                    "__name__", "__doc__", "__len__", "__str__", "__repr__",
                    "__eq__", "__hash__", "__iter__", "__next__", "__enter__",
                    "__exit__", "__getitem__", "__setitem__", "__contains__",
                    "__add__", "__sub__", "__mul__", "__call__", "__bool__",
                    "__int__", "__float__", "__index__", "__format__",
                }
                if node.attr.startswith("__") and node.attr not in ALLOWED_DUNDERS:
                    return False, f"禁止访问危险属性: {node.attr}"
                if node.attr in self.DANGEROUS_METHODS:
                    return False, f"禁止调用危险方法: {node.attr}"
        return True, ""

    def run_python(self, code: str) -> dict:
        """安全运行 Python 代码，返回 stdout/stderr/exit_code。"""
        result = {"stdout": "", "stderr": "", "exit_code": -1}

        # AST 安全检查
        safe, reason = self._check_ast_safe(code)
        if not safe:
            result["stderr"] = f"安全拦截: {reason}"
            return result

        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
                f.write(code)
                tmp_path = f.name

            try:
                proc = subprocess.run(
                    [sys.executable, tmp_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.timeout,
                )
                result["stdout"] = proc.stdout
                result["stderr"] = proc.stderr
                result["exit_code"] = proc.returncode
            except subprocess.TimeoutExpired:
                result["stderr"] = f"执行超时（>{self.timeout}秒）"
            except Exception as e:
                result["stderr"] = str(e)
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
        except Exception as e:
            result["stderr"] = str(e)
        return result

    def format_with_black(self, code: str) -> Tuple[bool, str]:
        """尝试用 black 格式化代码。"""
        black_path = shutil.which("black")
        if not black_path:
            return False, "未找到 black"
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
                f.write(code)
                tmp_path = f.name

            try:
                result = subprocess.run(
                    [black_path, "--quiet", tmp_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    with open(tmp_path, "r", encoding="utf-8") as f:
                        formatted = f.read()
                    return True, formatted
                return False, result.stderr
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
        except Exception as e:
            return False, str(e)


# ---------------------------------------------------------------------------
# 联网搜索（v1.5.0 国产化改造）
#
# 引擎优先级（2026-09-07 审计定案）：ddgs 全引擎（yahoo/bing/duckduckgo/google）
# 在国内网络全部超时（实测 20.2s 失败，对照 baidu 200 OK），故默认改为：
#   1. 博查 API（bochaai.com）—— 配置了 web_search.bocha_api_key（或环境变量
#      MAID_BOCHA_API_KEY）时优先使用，质量最好；
#   2. cn.bing.com 网页解析 —— 免费零配置、国内可达（默认引擎）；
#   3. ddgs —— 保留为海外/代理网络备选；
#   4. 全部失败 → 明确的「搜索暂不可用」降级文案（绝不返回假结果）。
# 返回结构不变：List[dict]，每项 {title, href, body}。
# ---------------------------------------------------------------------------
class WebSearch:
    _UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
    _TIMEOUT = 6  # 审计定案：超时收紧到 6s，快速失败 + 明确反馈

    def __init__(self, max_results: int = 5):
        self.max_results = max(1, int(max_results or 5))

    # -- 引擎 1：博查 API（有 key 才用） ----------------------------------
    @staticmethod
    def _get_bocha_key() -> str:
        """博查 API Key 获取顺序：环境变量 MAID_BOCHA_API_KEY > config.yaml web_search.bocha_api_key。
        读取失败一律返回空串（静默降级到下一引擎，不抛异常）。"""
        key = (os.environ.get("MAID_BOCHA_API_KEY") or "").strip()
        if key:
            return key
        try:
            import yaml as _yaml
            for cand in ("config.yaml",):
                if os.path.exists(cand):
                    with open(cand, "r", encoding="utf-8") as f:
                        data = _yaml.safe_load(f) or {}
                    key = str((((data or {}).get("web_search") or {}).get("bocha_api_key")) or "").strip()
                    if key:
                        return key
        except Exception:
            pass
        return ""

    def _search_bocha(self, query: str, api_key: str) -> List[dict]:
        """博查 Web Search API（OpenAI 风格 REST）。失败返回 []（交由下一引擎）。"""
        try:
            import requests as _requests
            resp = _requests.post(
                "https://api.bochaai.com/v1/web-search",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": self._UA,
                },
                json={"query": query, "count": self.max_results, "summary": True},
                timeout=self._TIMEOUT,
            )
            if resp.status_code != 200:
                return []
            pages = (((resp.json() or {}).get("data") or {}).get("webPages") or {}).get("value") or []
            results = []
            for item in pages[:self.max_results]:
                title = str(item.get("name") or "").strip()
                href = str(item.get("url") or "").strip()
                body = str(item.get("summary") or item.get("snippet") or "").strip()
                if title and href:
                    results.append({"title": title, "href": href, "body": body[:300]})
            return results
        except Exception:
            return []

    # -- 引擎 2：cn.bing.com 结果页解析（默认引擎，免费零配置） ------------
    @staticmethod
    def _strip_tags(html: str) -> str:
        """极简去标签 + 实体还原（不引第三方解析器）。"""
        text = re.sub(r"<[^>]+>", "", html or "")
        for ent, ch in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                        ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " ")):
            text = text.replace(ent, ch)
        return re.sub(r"\s+", " ", text).strip()

    def _search_bing_cn(self, query: str) -> List[dict]:
        """抓取 cn.bing.com/search?q=... 结果页并解析 b_algo 条目。失败返回 []。"""
        try:
            import requests as _requests
            resp = _requests.get(
                "https://cn.bing.com/search",
                params={"q": query, "count": str(self.max_results), "setlang": "zh-hans"},
                headers={
                    "User-Agent": self._UA,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                },
                timeout=self._TIMEOUT,
            )
            if resp.status_code != 200 or not resp.text:
                return []
            html = resp.text
            results: List[dict] = []
            # 每个 organic 结果为一个 <li class="b_algo">…</li> 块
            for block in re.findall(r'<li class="b_algo"[^>]*>(.*?)</li>', html, re.DOTALL)[:self.max_results]:
                m = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL)
                if not m:
                    continue
                href = self._strip_tags(m.group(1))
                title = self._strip_tags(m.group(2))
                # 摘要取 <p> 或 .b_caption 内文本
                pm = re.search(r"<p[^>]*>(.*?)</p>", block, re.DOTALL) or \
                     re.search(r'class="b_caption[^"]*"[^>]*>(.*?)</div>', block, re.DOTALL)
                body = self._strip_tags(pm.group(1)) if pm else ""
                if title and href:
                    results.append({"title": title, "href": href, "body": body[:300]})
            return results
        except Exception:
            return []

    # -- 引擎 3：ddgs（海外/代理网络备选） --------------------------------
    def _search_ddgs(self, query: str) -> List[dict]:
        if not _HAS_DDGS:
            return []
        try:
            with DDGS() as ddgs:
                raw_results = ddgs.text(query, max_results=self.max_results)
                if raw_results is None:
                    return []
                results = []
                for r in raw_results:
                    # 兼容 namedtuple / dataclass / dict 等多种返回格式
                    if hasattr(r, "_asdict"):
                        item = r._asdict()
                    elif isinstance(r, dict):
                        item = r
                    else:
                        item = dict(r)
                    title = item.get("title", "") or ""
                    href = item.get("href", "") or item.get("url", "") or ""
                    body = (item.get("body", "") or item.get("snippet", "") or "")
                    if title and href:
                        results.append({"title": title, "href": href, "body": body[:300]})
                return results
        except Exception:
            return []

    # -- 统一入口：按优先级串行尝试 ----------------------------------------
    def search(self, query: str) -> List[dict]:
        query = (query or "").strip()
        if not query:
            return [{"title": "搜索不可用", "href": "", "body": "搜索关键词为空。"}]
        # 1) 博查（有 key）
        bocha_key = self._get_bocha_key()
        if bocha_key:
            results = self._search_bocha(query, bocha_key)
            if results:
                return results
        # 2) cn.bing.com 解析（默认）
        results = self._search_bing_cn(query)
        if results:
            return results
        # 3) ddgs（海外网络可用）
        results = self._search_ddgs(query)
        if results:
            return results
        # 4) 明确降级文案（不返回假结果）
        if bocha_key:
            hint = "搜索暂不可用：博查与 Bing 均未返回结果，请检查网络后重试。"
        else:
            hint = ("搜索暂不可用：cn.bing.com 未返回结果（请检查网络）。\n"
                    "可选增强：① 在 config.yaml web_search.bocha_api_key 填入博查 API Key；"
                    "② 有代理的网络环境下可安装 ddgs 作为备用引擎（pip install ddgs）。")
        return [{"title": "搜索暂不可用", "href": "", "body": hint}]

    def should_auto_search(self, query: str) -> bool:
        """判断用户输入是否应该自动触发搜索。
        需要同时命中技术词 + 时间/查询词，避免日常闲聊误触发。
        """
        tech_words = [
            r"python", r"javascript", r"typescript", r"java", r"go", r"rust", r"cpp", r"c\+\+",
            r"api", r"sdk", r"framework", r"library", r"package", r"module",
            r"docker", r"kubernetes", r"k8s", r"aws", r"azure", r"gcp",
            r"react", r"vue", r"angular", r"django", r"flask", r"fastapi",
            r"git", r"github", r"ci/cd", r"pipeline", r"devops",
            r"database", r"sql", r"nosql", r"redis", r"mongodb",
            r"linux", r"ubuntu", r"centos", r"macos", r"windows",
            r"tensorflow", r"pytorch", r"ml", r"ai", r"llm",
        ]
        intent_words = [
            r"最新版本", r"最新 release", r"changelog", r"更新日志",
            r"怎么解决", r"报错", r"error", r"bug", r"issue",
            r"API 文档", r"官方文档", r"documentation", r"docs",
            r"202[5-9]", r"今天", r"最近", r"news", r"latest",
        ]
        has_tech = any(re.search(t, query, re.IGNORECASE) for t in tech_words)
        has_intent = any(re.search(t, query, re.IGNORECASE) for t in intent_words)
        return has_tech and has_intent

    def format_results(self, results: List[dict]) -> str:
        if not results:
            return "(无搜索结果)"
        lines = ["🔍 搜索结果:"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['title']}")
            lines.append(f"   {r['href']}")
            lines.append(f"   {r['body'][:200]}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 本地知识库 RAG（简化版：关键词 + TF-IDF）
# ---------------------------------------------------------------------------
class KnowledgeBase:
    def __init__(self, index_file: str):
        self.index_file = index_file
        self._index: Dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.index_file):
            with open(self.index_file, "r", encoding="utf-8") as f:
                self._index = json.load(f)

    def _save(self) -> None:
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump(self._index, f, ensure_ascii=False, indent=2)

    def _extract_keywords(self, text: str) -> List[str]:
        """简单关键词提取：中文按字，英文按词。"""
        # 英文单词
        words = re.findall(r"[a-zA-Z_]{2,}", text.lower())
        # 中文字符（去掉常见虚词）
        stopwords = set("的 了 和 是 就 都 而 及 与 或 在 有 被 将 把 为 之 其 这 那 我 你 他 她 它 们 个 一 不 也 很 会 能 要 去 到 做 来 上 下 中 大 小 多 少 可以 可能 但是 然后 因为 所以 如果 但是 而 且".split())
        chinese = [c for c in text if "\u4e00" <= c <= "\u9fff" and c not in stopwords]
        return words + chinese

    def _tfidf_score(self, query_words: List[str], doc_text: str) -> float:
        """简单 TF 评分。"""
        doc_words = self._extract_keywords(doc_text)
        if not doc_words:
            return 0.0
        score = 0.0
        for qw in query_words:
            tf = doc_words.count(qw) / len(doc_words)
            score += tf
        return score

    def index_directory(self, directory: str) -> str:
        """索引目录下的文档。"""
        exts = {".md", ".txt", ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".rs", ".go", ".java", ".c", ".cpp", ".h"}
        indexed = 0
        skipped = 0
        max_size = 10 * 1024 * 1024  # 10MB
        for root, _, files in os.walk(directory):
            for fname in files:
                if any(fname.endswith(e) for e in exts):
                    path = os.path.join(root, fname)
                    try:
                        size = os.path.getsize(path)
                        if size > max_size:
                            skipped += 1
                            continue
                        with open(path, "r", encoding="utf-8", errors="replace") as f:
                            content = f.read()
                        # 切分为约 500 字片段
                        chunks = []
                        chunk_size = 500
                        for i in range(0, len(content), chunk_size):
                            chunks.append(content[i:i + chunk_size])
                        self._index[path] = {
                            "chunks": chunks,
                            "mtime": os.path.getmtime(path),
                            "size": len(content),
                        }
                        indexed += 1
                    except Exception:
                        pass
        self._save()
        msg = G(f"✅ 已索引 {indexed} 个文件")
        if skipped:
            msg += Y(f"（跳过 {skipped} 个超大文件 >10MB）")
        return msg

    def search(self, query: str, top_k: int = 5) -> List[Tuple[str, str, float]]:
        """搜索知识库，返回 (filepath, chunk, score) 列表。"""
        query_words = self._extract_keywords(query)
        results = []
        for path, info in self._index.items():
            for chunk in info.get("chunks", []):
                score = self._tfidf_score(query_words, chunk)
                if score > 0:
                    results.append((path, chunk, score))
        results.sort(key=lambda x: x[2], reverse=True)
        return results[:top_k]

    def status(self) -> str:
        total_files = len(self._index)
        total_chunks = sum(len(v.get("chunks", [])) for v in self._index.values())
        return f"📚 知识库状态: {total_files} 个文件, {total_chunks} 个片段"


# ---------------------------------------------------------------------------
# 多 Agent 系统
