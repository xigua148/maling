"""代码执行相关命令。"""

from __future__ import annotations

from commands.router import CommandRouter, CommandContext
from core import C, G, R
from utils import _audit_log
import re


def register_run_commands(router: CommandRouter) -> None:
    """注册代码执行命令。"""

    @router.command(
        "run",
        description="运行最近 Python 代码块",
        usage="/run",
        category="代码执行",
    )
    def cmd_run(ctx: CommandContext) -> None:
        if not ctx.cfg.code_exec_enabled:
            print(R("⚠️ 代码执行已禁用，请在 config.yaml 中设置 code.exec_enabled: true"))
            return
        last_assistant = None
        for m in reversed(ctx.session.history):
            if m.get("role") == "assistant" and m.get("content"):
                last_assistant = m["content"]
                break
        if last_assistant:
            extracted = ctx.session.code_sandbox.extract_code(last_assistant)
            if extracted:
                _, code = extracted
                print(C("💻 正在运行代码..."))
                result = ctx.session.code_sandbox.run_python(code)
                output = result["stdout"] or "(无输出)"
                err = result["stderr"] or ""
                exit_code = result["exit_code"]
                print(f"📤 stdout:\n{output}")
                if err:
                    print(f"📤 stderr:\n{R(err)}")
                print(f"Exit code: {exit_code}")
                run_result = f"[代码执行结果]\nstdout: {output}\nstderr: {err}\nexit_code: {exit_code}"
                ctx.session.add_message("system", run_result)
                _audit_log("run", f"exit_code={exit_code}")
            else:
                print("最近回复中没有找到 Python 代码块。")
        else:
            print("没有可用的代码。")

    @router.command(
        "test",
        description="为最近代码生成单元测试",
        usage="/test",
        category="代码执行",
    )
    def cmd_test(ctx: CommandContext) -> None:
        if not ctx.cfg.code_exec_enabled:
            print(R("⚠️ 代码执行已禁用，请在 config.yaml 中设置 code.exec_enabled: true"))
            return
        last_assistant = None
        for m in reversed(ctx.session.history):
            if m.get("role") == "assistant" and m.get("content"):
                last_assistant = m["content"]
                break
        if last_assistant:
            extracted = ctx.session.code_sandbox.extract_code(last_assistant)
            if extracted:
                _, code = extracted
                test_prompt = (
                    f"请为以下代码生成 pytest 单元测试，覆盖主要功能和边界条件。\n"
                    f"代码:\n```python\n{code}\n```\n"
                    f"请输出完整的测试文件内容（用 ```python 包裹）："
                )
                print(C("🧪 正在生成单元测试..."))
                try:
                    resp = ctx.api.chat(
                        [{"role": "user", "content": test_prompt}],
                        max_tokens=ctx.cfg.api_max_tokens,
                    )
                    test_code_raw = resp["choices"][0]["message"].get("content", "")
                    match = re.search(r"```python\n(.*?)\n```", test_code_raw, re.DOTALL)
                    test_code = match.group(1) if match else test_code_raw
                    print(G("✅ 测试代码已生成"))
                    print(f"```python\n{test_code[:2000]}\n```")
                    print(C("🧪 正在运行测试..."))
                    result = ctx.session.code_sandbox.run_python(test_code)
                    if result["exit_code"] == 0:
                        print(G("✅ 测试通过"))
                    else:
                        print(R(f"❌ 测试失败:\n{result['stderr']}"))
                    ctx.session.add_message("system", f"[单元测试结果] exit_code={result['exit_code']}\n{result['stderr']}")
                    _audit_log("test", f"exit_code={result['exit_code']}")
                except Exception as e:
                    print(R(f"生成测试失败: {e}"))
                    _audit_log("test", f"failed={str(e)[:100]}")
            else:
                print("最近回复中没有找到代码块。")
        else:
            print("没有可用的代码。")
