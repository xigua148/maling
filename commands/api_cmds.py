"""API 调试命令：/api get|save|run|collection — HTTP 请求调试与集合管理。"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from commands.router import CommandRouter, CommandContext
from core import G, R, Y, C, GR


# 持久化存储路径
_API_COLLECTION_DIR = Path.home() / ".maid_coder" / "api_collections"
_API_COLLECTION_DIR.mkdir(parents=True, exist_ok=True)


def register_api_commands(router: CommandRouter) -> None:
    """注册 API 调试命令。"""

    @router.command(
        "api",
        description="API 调试（HTTP 请求 / 保存 / 重放 / 集合管理）",
        usage="/api get <url> [headers] | /api save <name> | /api run <name> | /api collection",
        category="开发者工具",
    )
    def cmd_api(ctx: CommandContext) -> None:
        sub = ctx.args[0] if ctx.args else ""

        if sub == "get":
            _cmd_api_get(ctx)
        elif sub == "save":
            _cmd_api_save(ctx)
        elif sub == "run":
            _cmd_api_run(ctx)
        elif sub == "collection":
            _cmd_api_collection(ctx)
        else:
            print("用法: /api get <url> [--method POST] [--data '{...}'] [--header 'k:v']")
            print("       /api save <name>          保存最近请求到集合")
            print("       /api run <name>           重放集合中的请求")
            print("       /api collection           查看所有保存的请求")

    @router.command(
        "curl",
        description="执行类 curl HTTP 请求",
        usage='/curl <url> [--method POST] [--data \'{"k":"v"}\']',
        category="开发者工具",
    )
    def cmd_curl(ctx: CommandContext) -> None:
        """快捷命令 /curl 等价于 /api get。"""
        _cmd_api_get(ctx, sub_cmd="curl")


def _parse_api_args(args: List[str]) -> Dict[str, Any]:
    """解析 API 命令参数。"""
    result: Dict[str, Any] = {
        "url": "",
        "method": "GET",
        "headers": {},
        "data": None,
        "timeout": 30,
    }
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--method", "-X") and i + 1 < len(args):
            result["method"] = args[i + 1].upper()
            i += 2
        elif arg in ("--data", "-d") and i + 1 < len(args):
            data_str = args[i + 1]
            try:
                result["data"] = json.loads(data_str)
            except json.JSONDecodeError:
                result["data"] = data_str
            i += 2
        elif arg in ("--header", "-H") and i + 1 < len(args):
            header = args[i + 1]
            if ":" in header:
                k, v = header.split(":", 1)
                result["headers"][k.strip()] = v.strip()
            i += 2
        elif arg in ("--timeout", "-t") and i + 1 < len(args):
            result["timeout"] = int(args[i + 1])
            i += 2
        elif not result["url"] and not arg.startswith("-"):
            result["url"] = arg
            i += 1
        else:
            i += 1
    return result


def _cmd_api_get(ctx: CommandContext, sub_cmd: str = "api") -> None:
    """执行 HTTP 请求。"""
    args = ctx.args[1:] if ctx.args[0] in ("get", "curl") else ctx.args
    if not args:
        print(f"用法: /{sub_cmd} <url> [--method GET] [--data '{{...}}'] [--header 'k:v']")
        return

    parsed = _parse_api_args(args)
    url = parsed["url"]
    if not url:
        print("❌ 缺少 URL")
        return

    # 自动补全协议头
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
        parsed["url"] = url

    method = parsed["method"]
    headers = parsed["headers"]
    data = parsed["data"]
    timeout = parsed["timeout"]

    print(C(f"🌐 {method} {url}"))
    if headers:
        for k, v in headers.items():
            print(GR(f"   {k}: {v}"))

    try:
        import httpx
        start = time.time()

        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            if method == "GET":
                resp = client.get(url, headers=headers)
            elif method == "POST":
                if isinstance(data, dict):
                    if "Content-Type" not in headers:
                        headers["Content-Type"] = "application/json"
                    resp = client.post(url, json=data, headers=headers)
                else:
                    resp = client.post(url, data=data, headers=headers)
            elif method == "PUT":
                if isinstance(data, dict):
                    resp = client.put(url, json=data, headers=headers)
                else:
                    resp = client.put(url, data=data, headers=headers)
            elif method == "DELETE":
                resp = client.delete(url, headers=headers)
            elif method == "PATCH":
                if isinstance(data, dict):
                    resp = client.patch(url, json=data, headers=headers)
                else:
                    resp = client.patch(url, data=data, headers=headers)
            elif method == "HEAD":
                resp = client.head(url, headers=headers)
            else:
                resp = client.request(method, url, headers=headers, data=data)

        elapsed = time.time() - start

        # 保存到 session 上下文供 /api save 使用
        ctx.session._last_api_request = {
            "url": url,
            "method": method,
            "headers": headers,
            "data": data,
            "timestamp": time.time(),
        }

        # 输出响应摘要
        status_color = G if resp.status_code < 300 else (Y if resp.status_code < 400 else R)
        print(f"\n{status_color(f'← HTTP {resp.status_code}')}  ({elapsed*1000:.1f}ms)  {len(resp.content)} bytes")

        # 输出响应头
        print(GR("\n响应头:"))
        for k, v in list(resp.headers.items())[:15]:
            print(GR(f"  {k}: {v}"))
        if len(resp.headers) > 15:
            print(GR(f"  ... 还有 {len(resp.headers)-15} 个头"))

        # 输出响应体（智能截断 + 格式化）
        content_type = resp.headers.get("content-type", "")
        body = resp.text
        print(f"\n响应体:")
        if "application/json" in content_type:
            try:
                json_data = resp.json()
                formatted = json.dumps(json_data, ensure_ascii=False, indent=2)
                if len(formatted) > 3000:
                    print(formatted[:3000])
                    print(GR(f"\n... (截断，共 {len(formatted)} 字符)"))
                else:
                    print(formatted)
            except Exception:
                print(body[:3000])
        else:
            if len(body) > 3000:
                print(body[:3000])
                print(GR(f"\n... (截断，共 {len(body)} 字符)"))
            else:
                print(body)

    except httpx.TimeoutException:
        print(R(f"❌ 请求超时 ({timeout}s)"))
    except httpx.ConnectError as e:
        print(R(f"❌ 连接失败: {e}"))
    except Exception as e:
        print(R(f"❌ 请求失败: {e}"))


def _cmd_api_save(ctx: CommandContext) -> None:
    """保存最近请求到集合。"""
    name = ctx.args[1] if len(ctx.args) > 1 else None
    if not name:
        print("用法: /api save <name>")
        return

    last_req = getattr(ctx.session, "_last_api_request", None)
    if not last_req:
        print(Y("⚠️ 没有可保存的最近请求，先执行 /api get"))
        return

    collection_file = _API_COLLECTION_DIR / "default.json"
    collection = {}
    if collection_file.exists():
        try:
            with open(collection_file, "r", encoding="utf-8") as f:
                collection = json.load(f)
        except Exception:
            pass

    collection[name] = last_req

    try:
        with open(collection_file, "w", encoding="utf-8") as f:
            json.dump(collection, f, ensure_ascii=False, indent=2)
        print(G(f"✅ 请求已保存为 '{name}'"))
    except Exception as e:
        print(R(f"❌ 保存失败: {e}"))


def _cmd_api_run(ctx: CommandContext) -> None:
    """重放集合中的请求。"""
    name = ctx.args[1] if len(ctx.args) > 1 else None
    if not name:
        print("用法: /api run <name>")
        return

    collection_file = _API_COLLECTION_DIR / "default.json"
    if not collection_file.exists():
        print(Y("⚠️ 集合为空，先执行 /api save <name>"))
        return

    try:
        with open(collection_file, "r", encoding="utf-8") as f:
            collection = json.load(f)
    except Exception as e:
        print(R(f"❌ 读取集合失败: {e}"))
        return

    saved = collection.get(name)
    if not saved:
        available = ", ".join(collection.keys())
        print(R(f"❌ 未找到请求 '{name}'"))
        print(f"可用请求: {available}")
        return

    # 构造模拟参数并复用 get 逻辑
    ctx.session._last_api_request = saved
    mock_args = [saved["url"], "--method", saved.get("method", "GET")]
    for k, v in saved.get("headers", {}).items():
        mock_args.extend(["--header", f"{k}:{v}"])
    if saved.get("data"):
        mock_args.extend(["--data", json.dumps(saved["data"])])

    # 临时替换 args 调用 get
    original_args = ctx.args
    ctx.args = ["get"] + mock_args
    _cmd_api_get(ctx)
    ctx.args = original_args


def _cmd_api_collection(ctx: CommandContext) -> None:
    """查看所有保存的请求。"""
    collection_file = _API_COLLECTION_DIR / "default.json"
    if not collection_file.exists():
        print("集合为空。")
        return

    try:
        with open(collection_file, "r", encoding="utf-8") as f:
            collection = json.load(f)
    except Exception as e:
        print(R(f"❌ 读取集合失败: {e}"))
        return

    if not collection:
        print("集合为空。")
        return

    print(C(f"📁 API 集合 ({len(collection)} 个请求):\n"))
    print(f"{'名称':<20} {'方法':<8} {'URL':<45}")
    print("-" * 75)
    for name, req in collection.items():
        method = req.get("method", "GET")
        url = req.get("url", "")[:45]
        print(f"{name:<20} {method:<8} {url}")
