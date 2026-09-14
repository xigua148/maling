"""性能基准命令：/benchmark run|compare|trend — 封装 timeit/pytest-benchmark。"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import timeit
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from commands.router import CommandRouter, CommandContext
from core import G, R, Y, C, GR
from utils import _validate_file_path


@dataclass
class BenchmarkResult:
    """单次基准测试结果。"""
    name: str
    mean_ms: float
    min_ms: float
    max_ms: float
    runs: int
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


# 内存中的基准历史（会话级别）
_benchmark_history: Dict[str, List[BenchmarkResult]] = {}


def register_benchmark_commands(router: CommandRouter) -> None:
    """注册性能基准测试命令。"""

    @router.command(
        "benchmark",
        description="性能基准测试（timeit/pytest-benchmark）",
        usage="/benchmark run <file_or_code> | /benchmark compare | /benchmark trend",
        category="开发者工具",
    )
    def cmd_benchmark(ctx: CommandContext) -> None:
        if not ctx.args:
            print("用法:")
            print("  /benchmark run <python_file_or_snippet> [--runs N]")
            print("  /benchmark compare")
            print("  /benchmark trend [name]")
            return

        sub = ctx.args[0]

        if sub == "run":
            _cmd_benchmark_run(ctx)
        elif sub == "compare":
            _cmd_benchmark_compare(ctx)
        elif sub == "trend":
            _cmd_benchmark_trend(ctx)
        else:
            print("用法: /benchmark run|compare|trend")


def _cmd_benchmark_run(ctx: CommandContext) -> None:
    """运行性能基准测试。"""
    if len(ctx.args) < 2:
        print("用法: /benchmark run <python_file_or_snippet> [--runs N]")
        print("说明: 运行 Python 代码并统计执行时间。")
        print("      如果是文件路径，运行文件中的代码；")
        print("      否则将参数作为 Python 代码片段执行。")
        return

    # 解析参数
    target = ctx.args[1]
    runs = 5
    i = 2
    while i < len(ctx.args):
        if ctx.args[i] == "--runs" and i + 1 < len(ctx.args):
            try:
                runs = int(ctx.args[i + 1])
                if runs < 1:
                    runs = 1
                if runs > 100:
                    runs = 100
            except ValueError:
                pass
            i += 2
        else:
            i += 1

    code = ""
    name = target

    # 判断是文件还是代码片段
    p = Path(target).expanduser()
    if p.exists() and p.suffix == ".py":
        ok, msg = _validate_file_path(target, ctx.cfg.workspace)
        if not ok:
            print(R(f"❌ {msg}"))
            return
        try:
            code = p.read_text(encoding="utf-8", errors="replace")
            name = str(p)
        except Exception as e:
            print(R(f"❌ 读取文件失败: {e}"))
            return
    else:
        # 作为代码片段处理
        code = target
        # 如果参数中包含空格被拆分了，合并回来
        if len(ctx.args) > 2 and not ctx.args[2].startswith("--"):
            code = " ".join(ctx.args[1:i if i > 2 else len(ctx.args)])
            # 重新检测 --runs 位置
            parts = ctx.args[1:]
            code_parts = []
            idx = 0
            while idx < len(parts):
                if parts[idx] == "--runs":
                    break
                code_parts.append(parts[idx])
                idx += 1
            code = " ".join(code_parts)

    if not code.strip():
        print(R("❌ 代码内容为空"))
        return

    print(C(f"⏱️  正在运行基准测试 ({runs} 轮)..."))
    print(GR(f"   目标: {name[:60]}{'...' if len(name) > 60 else ''}"))

    # 使用 timeit 统计
    try:
        # 将代码包装为可重复执行的语句
        # 尝试提取最后一个表达式或语句作为被测主体
        test_code = _prepare_benchmark_code(code)

        timer = timeit.Timer(stmt=test_code, setup="import sys; sys.path.insert(0, '.')", globals={})

        # 先运行一次确保无错误
        try:
            timer.timeit(number=1)
        except Exception as e:
            print(R(f"❌ 代码执行出错: {e}"))
            return

        # 正式测试
        times_sec = []
        for _ in range(runs):
            t = timer.timeit(number=1)
            times_sec.append(t)
            print(GR(f"   第 {_+1}/{runs} 轮: {t*1000:.3f} ms"))

        # 计算统计
        times_ms = [t * 1000 for t in times_sec]
        mean_ms = sum(times_ms) / len(times_ms)
        min_ms = min(times_ms)
        max_ms = max(times_ms)

        result = BenchmarkResult(
            name=name,
            mean_ms=mean_ms,
            min_ms=min_ms,
            max_ms=max_ms,
            runs=runs,
        )

        # 存入历史
        key = name
        if key not in _benchmark_history:
            _benchmark_history[key] = []
        _benchmark_history[key].append(result)

        # 输出结果
        print(C(f"\n📊 基准测试结果: {name}"))
        print(f"  平均耗时: {mean_ms:.3f} ms")
        print(f"  最小耗时: {min_ms:.3f} ms")
        print(f"  最大耗时: {max_ms:.3f} ms")
        print(f"  运行轮数: {runs}")

        # 与历史对比
        history = _benchmark_history[key]
        if len(history) > 1:
            prev = history[-2]
            delta = mean_ms - prev.mean_ms
            pct = (delta / prev.mean_ms * 100) if prev.mean_ms > 0 else 0
            if delta < 0:
                print(G(f"  对比上次: 快了 {abs(delta):.3f} ms ({abs(pct):.1f}% ↓)"))
            elif delta > 0:
                print(Y(f"  对比上次: 慢了 {delta:.3f} ms ({pct:.1f}% ↑)"))
            else:
                print(GR(f"  对比上次: 无变化"))

        # 保存到本地历史文件
        _persist_benchmark(result)

    except Exception as e:
        print(R(f"❌ 基准测试失败: {e}"))


def _cmd_benchmark_compare(ctx: CommandContext) -> None:
    """对比所有已记录的基准测试结果。"""
    if not _benchmark_history:
        print(Y("⚠️ 没有基准测试记录。先运行 /benchmark run <code>"))
        return

    print(C("📊 基准测试对比\n"))
    print(f"{'名称':<30} {'平均(ms)':<12} {'最小(ms)':<12} {'最大(ms)':<12} {'轮数':<8} {'时间':<20}")
    print("-" * 100)

    for name, results in _benchmark_history.items():
        latest = results[-1]
        print(
            f"{latest.name:<30} "
            f"{latest.mean_ms:<12.3f} "
            f"{latest.min_ms:<12.3f} "
            f"{latest.max_ms:<12.3f} "
            f"{latest.runs:<8} "
            f"{latest.timestamp[:19]:<20}"
        )
        # 如果有多个记录，显示趋势
        if len(results) > 1:
            first = results[0]
            last = results[-1]
            delta_pct = ((last.mean_ms - first.mean_ms) / first.mean_ms * 100) if first.mean_ms > 0 else 0
            trend = "→" if abs(delta_pct) < 5 else ("↑" if delta_pct > 0 else "↓")
            print(GR(f"  {'':29} 趋势: {trend} {delta_pct:+.1f}% (共 {len(results)} 次测试)"))


def _cmd_benchmark_trend(ctx: CommandContext) -> None:
    """显示指定基准测试的趋势图（文本版）。"""
    name = ctx.args[1] if len(ctx.args) > 1 else ""

    if not name:
        # 列出可用的测试名称
        if not _benchmark_history:
            print(Y("⚠️ 没有基准测试记录"))
            return
        print("可用基准测试:")
        for idx, key in enumerate(_benchmark_history.keys(), 1):
            print(f"  {idx}. {key} ({len(_benchmark_history[key])} 次)")
        print("\n用法: /benchmark trend <名称或编号>")
        return

    # 支持编号选择
    try:
        num = int(name)
        keys = list(_benchmark_history.keys())
        if 1 <= num <= len(keys):
            name = keys[num - 1]
    except ValueError:
        pass

    if name not in _benchmark_history:
        print(R(f"❌ 未找到基准测试记录: {name}"))
        return

    results = _benchmark_history[name]
    if len(results) < 2:
        print(Y(f"⚠️ {name} 只有 {len(results)} 次记录，不足以显示趋势"))
        return

    print(C(f"📈 {name} 性能趋势 ({len(results)} 次测试)\n"))

    # 文本趋势图
    values = [r.mean_ms for r in results]
    min_v, max_v = min(values), max(values)
    range_v = max_v - min_v if max_v > min_v else 1

    chart_width = 40
    for i, (r, v) in enumerate(zip(results, values)):
        bar_len = int(((v - min_v) / range_v) * chart_width) if range_v > 0 else chart_width // 2
        bar = "█" * bar_len
        prefix = f"{i+1:3d}. {v:8.3f}ms"
        print(f"{prefix} |{bar}")

    print(GR(f"\n最小: {min_v:.3f}ms | 最大: {max_v:.3f}ms | 范围: {range_v:.3f}ms"))


def _prepare_benchmark_code(code: str) -> str:
    """准备基准测试代码。"""
    code = code.strip()
    # 如果是文件内容，尝试提取主要逻辑
    # 简单策略：如果代码中有 if __name__ == "__main__" 块，尝试只提取上面的部分
    if "if __name__" in code:
        idx = code.find("if __name__")
        code = code[:idx].strip()

    # 如果代码以 def 开头，尝试自动调用最后一个函数
    lines = code.splitlines()
    func_names = []
    for line in lines:
        match = re.match(r"^def\s+(\w+)\s*\(", line.strip())
        if match:
            func_names.append(match.group(1))

    if func_names and not code.endswith("()"):
        # 自动添加函数调用
        last_func = func_names[-1]
        # 检查是否已经有调用
        has_call = False
        for line in reversed(lines):
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                if stripped == f"{last_func}()" or stripped.startswith(f"{last_func}("):
                    has_call = True
                break
        if not has_call:
            code += f"\n\n{last_func}()"

    return code


def _persist_benchmark(result: BenchmarkResult, history_file: str = ".benchmark_history.json") -> None:
    """将基准测试结果持久化到本地文件。"""
    try:
        data: Dict[str, List[dict]] = {}
        if os.path.exists(history_file):
            with open(history_file, "r", encoding="utf-8") as f:
                data = json.load(f)

        if result.name not in data:
            data[result.name] = []

        data[result.name].append({
            "name": result.name,
            "mean_ms": result.mean_ms,
            "min_ms": result.min_ms,
            "max_ms": result.max_ms,
            "runs": result.runs,
            "timestamp": result.timestamp,
        })

        # 限制每个测试保留最近 50 条
        data[result.name] = data[result.name][-50:]

        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# 启动时尝试加载历史记录
def _load_benchmark_history(history_file: str = ".benchmark_history.json") -> None:
    """从本地文件加载基准测试历史。"""
    global _benchmark_history
    if not os.path.exists(history_file):
        return
    try:
        with open(history_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        for name, entries in data.items():
            _benchmark_history[name] = []
            for e in entries:
                _benchmark_history[name].append(BenchmarkResult(
                    name=e["name"],
                    mean_ms=e["mean_ms"],
                    min_ms=e["min_ms"],
                    max_ms=e["max_ms"],
                    runs=e["runs"],
                    timestamp=e.get("timestamp", ""),
                ))
    except Exception:
        pass


# 模块加载时自动恢复历史
_load_benchmark_history()
