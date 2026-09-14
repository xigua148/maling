"""Git 集成相关命令。"""

from __future__ import annotations

from commands.router import CommandRouter, CommandContext
from core import G, R
from helpers import GitHelper


def register_git_commands(router: CommandRouter) -> None:
    """注册 Git 集成命令。"""

    @router.command(
        "git",
        description="Git 操作（status/diff/commit/log）",
        usage="/git status|diff|commit|log [n]",
        category="Git 集成",
    )
    def cmd_git(ctx: CommandContext) -> None:
        sub = ctx.args[0] if ctx.args else ""
        if sub == "status":
            print(GitHelper.status())
        elif sub == "diff":
            print(GitHelper.diff())
        elif sub == "log":
            n = int(ctx.args[1]) if len(ctx.args) >= 2 else 5
            print(GitHelper.log(n))
        elif sub == "commit":
            _, diff_out, _ = GitHelper._run_git(["diff", "--cached"])
            if not diff_out:
                _, diff_out, _ = GitHelper._run_git(["diff"])
            if not diff_out:
                print("没有待提交的变更。")
                return
            commit_prompt = f"根据以下 git diff 生成简洁的提交信息（一行，中文）：\n```diff\n{diff_out[:3000]}\n```"
            try:
                resp = ctx.api.chat([{"role": "user", "content": commit_prompt}], max_tokens=100)
                msg = resp["choices"][0]["message"].get("content", "更新").strip().strip('"').strip("'")
                print(f"📝 生成的提交信息: {msg}")
                confirm = input("确认提交？(Y/n): ").strip().lower()
                if confirm in ("", "y", "yes"):
                    print(GitHelper.commit(msg))
                else:
                    print("已取消。")
            except Exception as e:
                print(R(f"生成提交信息失败: {e}"))
        else:
            print("用法: /git status|diff|commit|log [n]")
