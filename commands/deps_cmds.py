"""依赖检查命令：/deps check|outdated|licenses — 检测依赖健康度。"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from commands.router import CommandRouter, CommandContext
from core import G, R, Y, C, GR


def register_deps_commands(router: CommandRouter) -> None:
    """注册依赖检查命令。"""

    @router.command(
        "deps",
        description="检查项目依赖（过时/漏洞/许可证）",
        usage="/deps check|outdated|licenses",
        category="开发者工具",
    )
    def cmd_deps(ctx: CommandContext) -> None:
        sub = ctx.args[0] if ctx.args else "check"

        if sub == "check":
            _cmd_deps_check(ctx)
        elif sub == "outdated":
            _cmd_deps_outdated(ctx)
        elif sub == "licenses":
            _cmd_deps_licenses(ctx)
        else:
            print("用法: /deps check | /deps outdated | /deps licenses")


def _cmd_deps_check(ctx: CommandContext) -> None:
    """检查依赖是否存在已知 CVE 漏洞和安装问题。"""
    deps = _detect_deps_files()
    if not deps:
        print(Y("⚠️ 未找到 requirements.txt 或 package.json"))
        return

    for dep_file, dep_type in deps:
        print(C(f"📦 检测到 {dep_file} ({dep_type})"))

        if dep_type == "python":
            _check_python_deps(dep_file)
        elif dep_type == "node":
            _check_node_deps(dep_file)


def _cmd_deps_outdated(ctx: CommandContext) -> None:
    """检查过时的依赖包。"""
    deps = _detect_deps_files()
    if not deps:
        print(Y("⚠️ 未找到依赖文件"))
        return

    for dep_file, dep_type in deps:
        print(C(f"📦 检查 {dep_file} 过时依赖..."))

        if dep_type == "python":
            pip_path = _find_tool("pip")
            if not pip_path:
                print(R("❌ 未找到 pip"))
                continue
            try:
                result = subprocess.run(
                    [pip_path, "list", "--outdated", "--format=json"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                )
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    if not data:
                        print(G("✅ 所有依赖均为最新版本"))
                    else:
                        print(Y(f"⚠️ 发现 {len(data)} 个过时依赖:"))
                        for item in data[:20]:
                            print(f"  {item['name']}: {item['version']} → {item['latest_version']}")
                        if len(data) > 20:
                            print(f"  ... 还有 {len(data) - 20} 个")
                else:
                    print(R(f"❌ pip 检查失败: {result.stderr}"))
            except Exception as e:
                print(R(f"❌ 检查失败: {e}"))

        elif dep_type == "node":
            npm_path = _find_tool("npm")
            if not npm_path:
                print(R("❌ 未找到 npm"))
                continue
            try:
                result = subprocess.run(
                    [npm_path, "outdated"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                    cwd=str(Path(dep_file).parent),
                )
                if result.stdout.strip():
                    print(Y(result.stdout))
                else:
                    print(G("✅ 所有依赖均为最新版本"))
            except Exception as e:
                print(R(f"❌ npm 检查失败: {e}"))


def _cmd_deps_licenses(ctx: CommandContext) -> None:
    """检查依赖许可证兼容性。"""
    deps = _detect_deps_files()
    if not deps:
        print(Y("⚠️ 未找到依赖文件"))
        return

    for dep_file, dep_type in deps:
        print(C(f"📦 分析 {dep_file} 许可证..."))

        if dep_type == "python":
            pip_path = _find_tool("pip")
            if not pip_path:
                print(R("❌ 未找到 pip"))
                continue
            try:
                # 获取已安装包的许可证信息
                result = subprocess.run(
                    [pip_path, "list", "--format=json"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                )
                if result.returncode == 0:
                    packages = json.loads(result.stdout)
                    _show_python_licenses(packages[:50])
                else:
                    print(R(f"❌ pip 查询失败: {result.stderr}"))
            except Exception as e:
                print(R(f"❌ 分析失败: {e}"))

        elif dep_type == "node":
            npm_path = _find_tool("npm")
            if not npm_path:
                print(R("❌ 未找到 npm"))
                continue
            try:
                result = subprocess.run(
                    [npm_path, "ls", "--depth=0", "--json"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                    cwd=str(Path(dep_file).parent),
                )
                if result.returncode in (0, 1):  # npm ls 可能返回 1 但有有效输出
                    data = json.loads(result.stdout)
                    deps_dict = data.get("dependencies", {})
                    _show_node_licenses(deps_dict, str(Path(dep_file).parent))
            except Exception as e:
                print(R(f"❌ npm 分析失败: {e}"))


def _detect_deps_files() -> List[Tuple[str, str]]:
    """检测项目中的依赖文件。返回 [(path, type)] 列表。"""
    found = []
    for root, _, files in os.walk("."):
        # 限制深度
        depth = root.count(os.sep)
        if depth > 2:
            continue
        for fname in files:
            if fname == "requirements.txt":
                found.append((os.path.join(root, fname), "python"))
            elif fname == "package.json":
                found.append((os.path.join(root, fname), "node"))
            elif fname == "pyproject.toml":
                found.append((os.path.join(root, fname), "python"))
    return found


def _find_tool(name: str) -> Optional[str]:
    """查找命令行工具路径。"""
    try:
        result = subprocess.run(
            ["which" if os.name != "nt" else "where", name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip().splitlines()[0]
    except Exception:
        pass
    return None


def _check_python_deps(req_file: str) -> None:
    """检查 Python 依赖安装状态。"""
    pip_path = _find_tool("pip")
    if not pip_path:
        print(R("  ❌ 未找到 pip"))
        return

    try:
        with open(req_file, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        reqs = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # 提取包名（忽略版本约束）
            match = re.match(r"^([a-zA-Z0-9_-]+)", line)
            if match:
                reqs.append(match.group(1))

        if not reqs:
            print(Y("  ⚠️ 未解析到依赖项"))
            return

        # 检查每个包是否已安装
        result = subprocess.run(
            [pip_path, "list", "--format=json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        installed = set()
        if result.returncode == 0:
            for pkg in json.loads(result.stdout):
                installed.add(pkg["name"].lower())

        missing = [r for r in reqs if r.lower() not in installed]
        if missing:
            print(R(f"  ❌ 未安装的依赖 ({len(missing)}): {', '.join(missing[:10])}"))
            if len(missing) > 10:
                print(R(f"     ... 还有 {len(missing) - 10} 个"))
        else:
            print(G(f"  ✅ 所有 {len(reqs)} 个依赖均已安装"))

        # 尝试用 safety 检查 CVE（如果已安装）
        safety_path = _find_tool("safety")
        if safety_path:
            print(C("  🔒 正在用 safety 检查 CVE..."))
            try:
                sresult = subprocess.run(
                    [safety_path, "check", "--file", req_file, "--json"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=60,
                )
                if sresult.stdout.strip():
                    try:
                        vulns = json.loads(sresult.stdout)
                        if vulns and vulns.get("vulnerabilities"):
                            print(R(f"  ⚠️ 发现 {len(vulns['vulnerabilities'])} 个 CVE 漏洞!"))
                            for v in vulns["vulnerabilities"][:5]:
                                pkg = v.get("package_name", "?")
                                cve = v.get("vulnerability_id", "?")
                                print(R(f"     - {pkg}: {cve}"))
                        else:
                            print(G("  ✅ 未发现已知 CVE 漏洞"))
                    except json.JSONDecodeError:
                        print(Y(f"  ⚠️ safety 输出解析失败"))
            except Exception as e:
                print(Y(f"  ⚠️ safety 检查失败: {e}"))
        else:
            print(GR("  ℹ️ 未安装 safety，跳过 CVE 检查（pip install safety）"))

    except Exception as e:
        print(R(f"  ❌ 检查失败: {e}"))


def _check_node_deps(pkg_file: str) -> None:
    """检查 Node.js 依赖安装状态。"""
    npm_path = _find_tool("npm")
    if not npm_path:
        print(R("  ❌ 未找到 npm"))
        return

    pkg_dir = str(Path(pkg_file).parent)
    node_modules = Path(pkg_dir) / "node_modules"
    if not node_modules.exists():
        print(Y(f"  ⚠️ node_modules 不存在，请先运行 npm install"))
        return

    try:
        result = subprocess.run(
            [npm_path, "audit", "--json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            cwd=pkg_dir,
        )
        if result.stdout.strip():
            try:
                data = json.loads(result.stdout)
                metadata = data.get("metadata", {})
                vulns = metadata.get("vulnerabilities", {})
                total = sum(vulns.values())
                if total > 0:
                    print(R(f"  ⚠️ npm audit 发现 {total} 个漏洞:"))
                    for level, count in vulns.items():
                        if count > 0:
                            print(R(f"     - {level}: {count}"))
                else:
                    print(G("  ✅ npm audit 未发现漏洞"))
            except json.JSONDecodeError:
                print(Y("  ⚠️ npm audit 输出解析失败"))
    except Exception as e:
        print(R(f"  ❌ npm audit 失败: {e}"))


def _show_python_licenses(packages: List[dict]) -> None:
    """显示 Python 包许可证信息（简化版）。"""
    # 常见许可证兼容性提示
    copyleft = {"GPL", "LGPL", "AGPL", "MPL", "EPL", "CC-BY-SA"}
    permissive = {"MIT", "Apache", "BSD", "ISC", "Python-2.0", "Unlicense", "CC0"}

    print(f"  {'包名':<25} {'版本':<15} {'许可证(推测)':<20}")
    print(f"  {'-'*60}")

    for pkg in packages[:30]:
        name = pkg.get("name", "?")
        version = pkg.get("version", "?")
        # 简化推测：基于常见包名映射
        lic = _guess_python_license(name)
        marker = ""
        if any(c in lic for c in copyleft):
            marker = Y(" [Copyleft]")
        elif any(p in lic for p in permissive):
            marker = G(" [Permissive]")
        print(f"  {name:<25} {version:<15} {lic:<20}{marker}")

    if len(packages) > 30:
        print(f"  ... 还有 {len(packages) - 30} 个包")
    print(GR("\n  ℹ️ 许可证信息为基于常见包的推测，准确信息请查阅各包官方文档。"))


def _show_node_licenses(deps: dict, pkg_dir: str) -> None:
    """显示 Node.js 包许可证信息。"""
    print(f"  {'包名':<30} {'版本':<15} {'许可证':<20}")
    print(f"  {'-'*65}")

    for name, info in list(deps.items())[:30]:
        version = info.get("version", "?") if isinstance(info, dict) else str(info)
        # 尝试读取 node_modules 中的 package.json
        lic = "Unknown"
        pkg_json = Path(pkg_dir) / "node_modules" / name / "package.json"
        if pkg_json.exists():
            try:
                with open(pkg_json, "r", encoding="utf-8", errors="replace") as f:
                    data = json.load(f)
                    lic_field = data.get("license") or data.get("licenses")
                    if isinstance(lic_field, str):
                        lic = lic_field
                    elif isinstance(lic_field, dict):
                        lic = lic_field.get("type", "Unknown")
                    elif isinstance(lic_field, list) and lic_field:
                        lic = lic_field[0].get("type", "Unknown") if isinstance(lic_field[0], dict) else str(lic_field[0])
            except Exception:
                pass
        print(f"  {name:<30} {version:<15} {lic:<20}")

    if len(deps) > 30:
        print(f"  ... 还有 {len(deps) - 30} 个包")


def _guess_python_license(pkg_name: str) -> str:
    """基于常见包名推测许可证（非常简化）。"""
    known = {
        "requests": "Apache-2.0", "urllib3": "MIT", "certifi": "MPL-2.0",
        "numpy": "BSD", "pandas": "BSD", "matplotlib": "PSF",
        "django": "BSD", "flask": "BSD", "fastapi": "MIT",
        "pytest": "MIT", "black": "MIT", "mypy": "MIT",
        "sqlalchemy": "MIT", "click": "BSD", "jinja2": "BSD",
        "pillow": "HPND", "tornado": "Apache-2.0", "twisted": "MIT",
        "scrapy": "BSD", "celery": "BSD", "redis": "MIT",
        "boto3": "Apache-2.0", "botocore": "Apache-2.0",
    }
    return known.get(pkg_name.lower(), "Unknown")
