"""开发者工具相关命令（P1/P2 功能）。"""

from __future__ import annotations

from commands.router import CommandRouter, CommandContext
from core import C, G, R, Y
from utils import (
    _validate_file_path, _show_diff, _code_score, _generate_template,
    _batch_replace_preview, _batch_replace_apply, _test_regex,
    _format_data, _ocr_image, _profile_code, _share_session,
    _generate_dockerfile, _audit_log, _read_audit_log,
    _TEMPLATES,
)
import re


def register_dev_commands(router: CommandRouter) -> None:
    """注册开发者工具命令。"""

    @router.command(
        "score",
        description="对最近 AI 代码评分（复杂度/可读性）",
        usage="/score",
        category="开发者工具",
    )
    def cmd_score(ctx: CommandContext) -> None:
        last_assistant = None
        for m in reversed(ctx.session.history):
            if m.get("role") == "assistant" and m.get("content"):
                last_assistant = m["content"]
                break
        if last_assistant:
            extracted = ctx.session.code_sandbox.extract_code(last_assistant)
            if extracted:
                _, code = extracted
                print(_code_score(code))
            else:
                print("最近回复中没有找到代码块。")
        else:
            print("没有可用的回复。")

    @router.command(
        "template",
        description="生成项目骨架 (fastapi/flask/express/react)",
        usage="/template <type> [target_dir]",
        category="开发者工具",
    )
    def cmd_template(ctx: CommandContext) -> None:
        ttype = ctx.args[0] if ctx.args else ""
        target = ctx.args[1] if len(ctx.args) > 1 else f"{ttype}-project"
        if ttype:
            ok, msg = _validate_file_path(target, ctx.cfg.workspace)
            if not ok:
                print(R(f"❌ {msg}"))
                return
            print(_generate_template(ttype, target))
        else:
            available = ", ".join(_TEMPLATES.keys())
            print(f"用法: /template <type> [target_dir]\n可用类型: {available}")

    @router.command(
        "replaceall",
        description="批量替换文本（预览+确认）",
        usage='/replaceall "旧文本" "新文本" *.py',
        category="开发者工具",
    )
    def cmd_replaceall(ctx: CommandContext) -> None:
        if len(ctx.args) >= 3:
            pattern, replacement, glob_expr = ctx.args[0], ctx.args[1], ctx.args[2]
            matches, total, originals = _batch_replace_preview(pattern, replacement, glob_expr, ctx.cfg.workspace)
            if not matches:
                print("未找到匹配文件。")
                return
            print(f"📋 预览: 将在 {len(matches)} 个文件中替换 {total} 处")
            for m in matches[:20]:
                print(m)
            if len(matches) > 20:
                print(f"... 还有 {len(matches)-20} 个文件")
            try:
                ans = input(Y("确认执行替换？(Y/n): ")).strip()
            except (EOFError, KeyboardInterrupt):
                ans = "n"
            if ans.lower() in ("y", "yes", ""):
                fc, tc = _batch_replace_apply(pattern, replacement, glob_expr, originals, ctx.cfg.workspace)
                print(G(f"✅ 已在 {fc} 个文件中替换 {tc} 处"))
                _audit_log("replaceall", f"pattern={pattern}, glob={glob_expr}, files={fc}, count={tc}")
            else:
                print("已取消。")
        else:
            print('用法: /replaceall "旧文本" "新文本" *.py')

    @router.command(
        "regex",
        description="正则测试工具",
        usage='/regex "pattern" "test string"',
        category="开发者工具",
    )
    def cmd_regex(ctx: CommandContext) -> None:
        if len(ctx.args) >= 2:
            print(_test_regex(ctx.args[0], ctx.args[1]))
        else:
            print('用法: /regex "pattern" "test string"')

    @router.command(
        "format",
        description="JSON/YAML/XML 格式化",
        usage='/format \'{"key": "value"}\'',
        category="开发者工具",
    )
    def cmd_format(ctx: CommandContext) -> None:
        text = " ".join(ctx.args)
        if text:
            print(_format_data(text))
        else:
            print('用法: /format \'{"key": "value"}\'')

    @router.command(
        "translate",
        description="翻译最近代码块为其他语言",
        usage="/translate py2js | /translate py2go | /translate js2py",
        category="开发者工具",
    )
    def cmd_translate(ctx: CommandContext) -> None:
        if ctx.args:
            direction = ctx.args[0]
            last_assistant = None
            for m in reversed(ctx.session.history):
                if m.get("role") == "assistant" and m.get("content"):
                    last_assistant = m["content"]
                    break
            if last_assistant:
                extracted = ctx.session.code_sandbox.extract_code(last_assistant)
                if extracted:
                    _, code = extracted
                    prompt = f"请将以下 {extracted[0]} 代码翻译为 {direction}，保持功能一致，输出完整代码块：\n\n```{extracted[0]}\n{code}\n```"
                    messages = [{"role": "system", "content": "你是一位精通多种编程语言的代码翻译专家。"}, {"role": "user", "content": prompt}]
                    try:
                        resp = ctx.api.chat(messages, max_tokens=ctx.cfg.api_max_tokens)
                        result = resp["choices"][0]["message"].get("content", "")
                        from core import print_typed
                        print_typed(result, ctx.session.speed, prefix=C("\n[翻译结果] "))
                        _audit_log("translate", f"direction={direction}")
                    except Exception as e:
                        print(f"翻译失败: {e}")
                else:
                    print("最近回复中没有找到代码块。")
            else:
                print("没有可用的回复。")
        else:
            print("用法: /translate py2js | /translate py2go | /translate js2py")

    @router.command(
        "gendoc",
        description="从代码注释生成 API 文档",
        usage="/gendoc <filepath>",
        category="开发者工具",
    )
    def cmd_gendoc(ctx: CommandContext) -> None:
        filepath = ctx.args[0] if ctx.args else None
        if filepath:
            ok, msg = _validate_file_path(filepath, ctx.cfg.workspace)
            if not ok:
                print(R(f"❌ {msg}"))
                return
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    code = f.read()
                prompt = f"从以下代码中提取所有函数/类的签名和 docstring，生成 Markdown 格式的 API 文档：\n\n```python\n{code[:8000]}\n```"
                messages = [{"role": "system", "content": "你是一位技术文档工程师。"}, {"role": "user", "content": prompt}]
                resp = ctx.api.chat(messages, max_tokens=ctx.cfg.api_max_tokens)
                result = resp["choices"][0]["message"].get("content", "")
                from core import print_typed
                print_typed(result, ctx.session.speed, prefix=C("\n[文档] "))
                _audit_log("gendoc", f"file={filepath}")
            except Exception as e:
                print(f"生成文档失败: {e}")
        else:
            print("用法: /gendoc <filepath>")

    @router.command(
        "ocr",
        description="图片 OCR 识别代码",
        usage="/ocr <image.png>",
        category="开发者工具",
    )
    def cmd_ocr(ctx: CommandContext) -> None:
        image_path = ctx.args[0] if ctx.args else None
        if image_path:
            ok, msg = _validate_file_path(image_path, ctx.cfg.workspace)
            if not ok:
                print(R(f"❌ {msg}"))
                return
            print(_ocr_image(image_path))
        else:
            print("用法: /ocr <image.png>")

    @router.command(
        "sql",
        description="自然语言生成/优化 SQL",
        usage="/sql 查询过去30天活跃用户数",
        category="开发者工具",
    )
    def cmd_sql(ctx: CommandContext) -> None:
        query = " ".join(ctx.args)
        if query:
            prompt = f"将以下自然语言需求转换为标准 SQL 查询，并给出简要说明：\n\n需求: {query}"
            messages = [{"role": "system", "content": "你是一位资深数据库工程师，精通 SQL 优化。"}, {"role": "user", "content": prompt}]
            try:
                resp = ctx.api.chat(messages, max_tokens=ctx.cfg.api_max_tokens)
                result = resp["choices"][0]["message"].get("content", "")
                from core import print_typed
                print_typed(result, ctx.session.speed, prefix=C("\n[SQL] "))
            except Exception as e:
                print(f"SQL 生成失败: {e}")
        else:
            print("用法: /sql 查询过去30天活跃用户数")

    @router.command(
        "profile",
        description="分析最近 Python 代码性能",
        usage="/profile",
        category="开发者工具",
    )
    def cmd_profile(ctx: CommandContext) -> None:
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
                print(_profile_code(code, ctx.cfg.code_exec_timeout))
            else:
                print("最近回复中没有找到 Python 代码块。")
        else:
            print("没有可用的代码。")

    @router.command(
        "share",
        description="生成会话摘要分享",
        usage="/share [name]",
        category="开发者工具",
    )
    def cmd_share(ctx: CommandContext) -> None:
        print(_share_session(ctx.session))

    @router.command(
        "docker",
        description="根据依赖自动生成 Dockerfile",
        usage="/docker",
        category="开发者工具",
    )
    def cmd_docker(ctx: CommandContext) -> None:
        print(_generate_dockerfile(ctx.cfg.workspace))
        _audit_log("docker", f"generated Dockerfile in {ctx.cfg.workspace}")

    @router.command(
        "history",
        description="查看最近操作审计日志",
        usage="/history",
        category="开发者工具",
    )
    def cmd_history(ctx: CommandContext) -> None:
        print(_read_audit_log(20))

    @router.command(
        "paste",
        description="读取剪贴板",
        usage="/paste",
        category="其他",
    )
    def cmd_paste(ctx: CommandContext) -> None:
        from core import _HAS_PYPERCLIP
        if _HAS_PYPERCLIP:
            try:
                import pyperclip
                clip = pyperclip.paste()
                if clip:
                    print(C(f"📋 剪贴板内容已读取 ({len(clip)} 字符)"))
                    # 将剪贴板内容作为新的用户输入处理
                    # 注意：这里不直接修改 ctx.raw_input，因为 dispatch 已完成
                    # 原始 main.py 中是修改 user_input 然后继续 fallthrough
                    # 在 Router 模式下，我们将剪贴板内容视为需要直通 AI 的输入
                    ctx.session.add_message("user", f"请分析以下代码:\n```\n{clip[:5000]}\n```")
                    print("剪贴板内容已加入对话。")
                else:
                    print("剪贴板为空。")
            except Exception as e:
                print(R(f"读取剪贴板失败: {e}"))
        else:
            print(Y("未安装 pyperclip，请执行: pip install pyperclip"))

    @router.command(
        "plugins",
        description="查看已加载插件",
        usage="/plugins list",
        category="扩展",
    )
    def cmd_plugins(ctx: CommandContext) -> None:
        sub = ctx.args[0] if ctx.args else ""
        if sub == "list":
            print(ctx.session.plugin_mgr.list_plugins())
        else:
            print("用法: /plugins list")
