from __future__ import annotations

import ast
import glob as glob_mod
import io
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING
from dataclasses import fields

if TYPE_CHECKING:  # 仅类型检查期解析（本模块启用 future annotations，运行期不求值）
    from session import ChatSession


def _atomic_write_json(path: str, data: dict) -> None:
    """原子写入 JSON（先写 .tmp 再重命名）。"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

from core import AppConfig, STYLES, _fmt, G, R, Y, C, B, GR, M, W, _HAS_YAML

# Help
# ---------------------------------------------------------------------------
def show_help(session: ChatSession) -> None:
    """直接逐行输出帮助文本，避免 .format() 解析大括号导致 KeyError。"""
    b = lambda t: _fmt(t, STYLES.BLUE)
    c = lambda t: _fmt(t, STYLES.CYAN)
    gr = lambda t: _fmt(t, STYLES.GRAY)
    r = lambda t: _fmt(t, STYLES.RED)
    g = lambda t: _fmt(t, STYLES.GREEN)
    y = lambda t: _fmt(t, STYLES.YELLOW)

    lines = [
        b("╔══════════════════════════════════════════════════════╗"),
        b("║         女仆编程师 v2.0 — 命令帮助                  ║"),
        b("╚══════════════════════════════════════════════════════╝"),
        "",
        c("【模式切换】"),
        "  /deep              切换深度思考模式",
        "  /code              切换编程模式",
        "  /multi             切换多模型协作模式",
        "  /stream on|off     切换真流式输出模式",
        "",
        c("【输出控制】"),
        "  /speed fast        直接整段输出",
        "  /speed normal      按片段输出（默认）",
        "  /speed slow        逐字输出",
        "  /tokens on|off     切换 Token 用量显示",
        "",
        c("【会话管理】"),
        "  /save [name]       保存会话",
        "  /load [name]       加载会话",
        "  /session list      列出所有会话",
        "  /session switch <n> 切换会话",
        "  /session new <n>   创建新会话",
        "  /session delete <n> 删除会话",
        "  /clear             清空对话历史",
        "",
        c("【文件编辑】"),
        "  /read <file>       读取文件内容",
        "  /edit <file> <desc> 让AI生成修改方案",
        "  /apply             确认应用修改",
        "  /undo [file]       撤销修改",
        "",
        c("【代码片段】"),
        "  /snippet save <n>  保存最近代码块",
        "  /snippet list      查看片段列表",
        "  /snippet load <n>  插入片段到输入",
        "  /snippet delete <n> 删除片段",
        "",
        c("【代码执行】"),
        "  /run               运行最近 Python 代码块",
        "  /test              为最近代码生成单元测试",
        "",
        c("【Git 集成】"),
        "  /git status        查看 git 状态",
        "  /git diff          查看变更",
        "  /git commit        AI生成提交信息并提交",
        "  /git log [n]       查看最近提交",
        "",
        c("【知识库】"),
        "  /kb index <dir>    索引目录文档",
        "  /kb search <query> 检索知识库",
        "  /kb status         查看索引状态",
        "",
        c("【Agent 系统】"),
        "  /agent <role>      切换角色 (product/arch/dev/review)",
        "  /agent auto        自动判断角色",
        "  /agent reset       切回默认女仆模式",
        "  /agents            查看可用角色",
        "  /workflow <task>   自动串联多Agent工作流",
        "",
        c("【搜索】"),
        "  /search <query>    手动触发联网搜索",
        "",
        c("【Todo】"),
        "  /todo list         查看待办",
        "  /todo done <n>     标记完成",
        "  /todo clear        清空待办",
        "",
        c("【开发者工具 · P1/P2】"),
        "  /diff <file>       显示文件与 .bak 备份差异",
        "  /score             对最近 AI 代码评分（复杂度/可读性）",
        "  /template <type>   生成项目骨架 (fastapi/flask/express/react)",
        "  /replaceall ...    批量替换文本（预览+确认）",
        "  /regex <p> <s>     正则测试工具",
        "  /format <data>     JSON/YAML/XML 格式化",
        "  /translate py2js   翻译最近代码块为其他语言",
        "  /gendoc <file>     从代码注释生成 API 文档",
        "  /ocr <image>       图片 OCR 识别代码",
        "  /sql <query>       自然语言生成/优化 SQL",
        "  /profile           分析最近 Python 代码性能",
        "  /share [name]      生成会话摘要分享",
        "  /docker            根据依赖自动生成 Dockerfile",
        "  /history           查看最近操作审计日志",
        "",
        c("【聊天增强 · Phase 1】"),
        "  /chat              切换闲聊模式（弱化编程，强化陪伴）",
        "  /chat off          退出闲聊模式",
        "  /greet             触发即时情境问候",
        "  /pref set <k> <v>  手动设置偏好",
        "  /pref get <k>      查看偏好",
        "  /pref list         列出所有偏好",
        "  /pref delete <k>   删除偏好",
        "  /remember <k> <v>  /pref set 别名",
        "  /memory            查看记忆摘要",
        "  /forget <topic>    手动遗忘话题",
        "  /mood              查看亲密度等级和情绪温度",
        "",
        c("【扩展】"),
        "  VS Code 插件开发中，敬请期待",
        "",
        c("【其他】"),
        "  /stats             会话统计",
        "  /plugins list      查看插件",
        "  /reload            热重载配置",
        "  /paste             读取剪贴板",
        "  /quiet             切换调试信息",
        "  /help              显示帮助",
        "  quit / exit        退出程序",
        "",
        gr("提示: 旧命令（deep/code/multi/clear/quit）仍兼容。"),
    ]
    print("\n".join(lines))


# ---------------------------------------------------------------------------
# 命令解析
# ---------------------------------------------------------------------------
def parse_command(raw: str) -> Tuple[str, List[str]]:
    parts = raw.split()
    if not parts:
        return "", []
    cmd = parts[0].lstrip("/").lower()
    args = parts[1:]
    return cmd, args


# ---------------------------------------------------------------------------
# 启动流程辅助函数
# ---------------------------------------------------------------------------

def _check_dependencies() -> None:
    """检测可选依赖，提示并可选自动安装。"""
    deps = {
        "colorama": ("colorama", "Windows 终端颜色支持"),
        "yaml": ("pyyaml", "YAML 配置文件支持"),
        "dotenv": ("python-dotenv", ".env 环境变量文件支持"),
        "pyperclip": ("pyperclip", "剪贴板集成"),
        "ddgs": ("ddgs", "联网搜索"),
    }

    core_missing = []
    optional_missing = []
    for mod, (pkg, desc) in deps.items():
        try:
            __import__(mod)
        except ImportError:
            if mod in ("yaml", "dotenv"):
                core_missing.append((pkg, desc))
            else:
                optional_missing.append((pkg, desc))

    if not core_missing and not optional_missing:
        return

    print(Y("\n📦 检测到以下依赖缺失:"))
    if core_missing:
        print(Y("  [核心推荐] " + ", ".join([f"{pkg}" for pkg, _ in core_missing])))
    if optional_missing:
        print(Y("  [功能增强] " + ", ".join([f"{pkg}" for pkg, _ in optional_missing])))

    all_missing = [pkg for pkg, _ in core_missing + optional_missing]
    try:
        resp = input(Y("\n是否自动安装缺失依赖？（Y/n）: ")).strip().lower()
    except (EOFError, KeyboardInterrupt):
        resp = "n"

    if resp in ("", "y", "yes"):
        print(C("⏳ 正在安装依赖，请稍候..."))
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install"] + all_missing,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                print(G("✅ 依赖安装完成，请重新启动程序。"))
            else:
                print(R(f"⚠️ 安装失败:\n{result.stderr}"))
                print(Y(f"   请手动执行: pip install {' '.join(all_missing)}"))
        except Exception as e:
            print(R(f"安装过程出错: {e}"))
            print(Y(f"   请手动执行: pip install {' '.join(all_missing)}"))
        sys.exit(0)
    else:
        print(GR("已跳过安装，部分功能可能不可用。"))


def _setup_api_key() -> str:
    """交互式配置 API Key。返回 key。"""
    print(Y("\n🔑 未检测到 DEEPSEEK_API_KEY。"))
    try:
        key = input(Y("请输入你的 DeepSeek API Key: ")).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)

    if not key:
        print(R("API Key 不能为空。"))
        sys.exit(1)

    # 验证 key 格式
    if not key.startswith("sk-"):
        print(Y("⚠️ 警告: Key 格式似乎不是标准的 sk- 开头，继续吗？（Y/n）"))
        try:
            confirm = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            sys.exit(0)
        if confirm not in ("", "y", "yes"):
            sys.exit(0)

    # 询问是否保存
    try:
        save = input(Y("是否保存到 .env 文件以便下次自动加载？（Y/n）: ")).strip().lower()
    except (EOFError, KeyboardInterrupt):
        save = "n"

    if save in ("", "y", "yes"):
        try:
            env_path = Path(".env")
            lines = []
            if env_path.exists():
                with open(env_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            replaced = False
            for i, line in enumerate(lines):
                if line.strip().startswith("DEEPSEEK_API_KEY="):
                    lines[i] = f"DEEPSEEK_API_KEY={key}\n"
                    replaced = True
                    break
            if not replaced:
                lines.append(f"DEEPSEEK_API_KEY={key}\n")
            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
            print(G("✅ 已保存到 .env 文件"))
        except Exception as e:
            print(R(f"保存失败: {e}"))

    return key


def _ensure_config() -> None:
    """如果 config.yaml 不存在，启动交互式配置向导。"""
    if os.path.exists("config.yaml"):
        return

    # 交互式向导
    wizard_cfg = _interactive_config_wizard()

    from core import API_PROVIDER_PRESETS
    provider = wizard_cfg.get("api_provider", "deepseek")
    preset = API_PROVIDER_PRESETS.get(provider, API_PROVIDER_PRESETS["deepseek"])
    preset_url = preset["url"] or "https://api.deepseek.com/chat/completions"
    preset_model = preset["default_model"] or "deepseek-flash"

    default_config = f'''# 女仆编程师 v2.0 配置文件
# 优先级: 环境变量 > 本文件 > 代码默认值
# 生成时间: {datetime.now().isoformat()}

api:
  # API 厂商预设（v10.8）: deepseek / moonshot / qwen / zhipu / openai / openrouter / ollama / custom
  provider: "{provider}"
  # DeepSeek API 配置
  key: ""                      # 优先从 DEEPSEEK_API_KEY 环境变量读取
  url: "{preset_url}"
  model: "{preset_model}"      # 模型名称
  max_tokens: 2000             # 单次最大生成 token
  temperature: 0.7             # 创造性 (0.0-2.0)
  retry_times: 3               # API 失败重试次数

session:
  max_history_rounds: 8        # 保留的历史轮数
  summary_interval: 5          # 自动摘要触发间隔（轮）
  auto_save: true              # 退出时自动保存（默认开启）
  workspace: "."

output:
  speed: "{wizard_cfg.get('output_speed', 'normal')}"       # fast / normal / slow
  colors: true
  debug: false
  show_token_usage: true
  stream_mode: {str(wizard_cfg.get('stream_mode', False)).lower()}

multi_model:
  enabled: {str(wizard_cfg.get('multi_enabled', False)).lower()}
  parallel_gen_review: true
  judge_threshold: 0.7

web_search:
  enabled: {str(wizard_cfg.get('web_search_enabled', True)).lower()}
  max_results: 5

code:
  exec_enabled: {str(wizard_cfg.get('code_exec_enabled', False)).lower()}
  exec_timeout: 5

safety:
  command_safety_mode: "blacklist"

agent:
  enabled: false
  max_steps: 8
'''
    with open("config.yaml", "w", encoding="utf-8") as f:
        f.write(default_config)


def _first_run_banner(is_first: bool, cfg: AppConfig) -> None:
    """打印启动引导信息。"""
    print(B("╔═══════════════════════════════════════╗"))
    print(B("║     欢迎回来，主人~ 女仆已就绪         ║"))
    print(B("╚═══════════════════════════════════════╝"))

    if is_first:
        print(C("\n[首次启动] 正在检查环境..."))
        print(G("✓ API Key 已配置"))
        print(G("✓ 依赖检查完成"))
        if os.path.exists("config.yaml"):
            print(G("✓ 配置文件已加载"))
        else:
            print(G("✓ 默认配置已生效"))

    # 配置状态面板
    print(C("\n[配置状态]"))
    on = G("开"); off = GR("关")
    print(f"  自动保存: {on if cfg.auto_save else off}  |  流式输出: {on if cfg.stream_mode else off}  |  多模型: {on if cfg.multi_enabled else off}")
    print(f"  代码执行: {on if cfg.code_exec_enabled else off}  |  剪贴板: {on if cfg.clipboard_check else off}  |  联网搜索: {on if cfg.web_search_enabled else off}")
    print(f"  敏感扫描: {on if cfg.sensitive_info_scan else off}  |  统计: {on if cfg.stats_enabled else off}  |  审计日志: {on}")
    print(f"  崩溃恢复: {on}  |  离线缓存: {on}  |  多 Key 轮换: {on if hasattr(cfg, 'api_keys') and cfg.api_keys else off}")

    print(f"\n{C('📖')} 输入 {Y('/help')} 查看完整命令手册")
    print(f"{C('🚪')} 输入 {Y('quit')} 退出程序")
    print()


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Readline 自动补全与历史
# ---------------------------------------------------------------------------
def _setup_readline(commands: Optional[List[str]] = None) -> bool:
    """配置 Tab 补全和命令历史。

    Args:
        commands: 可选的命令列表，用于 Tab 补全。为 None 时使用默认列表。

    Returns:
        是否成功启用 readline 补全。
    """
    try:
        import readline
    except ImportError:
        return False

    _CMD_LIST = commands or [
        "help", "quit", "exit", "clear", "deep", "code", "multi", "stream",
        "speed", "save", "load", "tokens", "session", "agent", "agents",
        "workflow", "search", "stats", "read", "edit", "apply", "undo",
        "snippet", "todo", "run", "test", "kb", "plugins",
        "diff", "score", "template", "replaceall", "regex", "format",
        "translate", "gendoc", "ocr", "sql", "profile", "share", "docker",
        "history",
        # Phase 1 MVP: 聊天增强命令
        "chat", "greet", "pref", "remember", "memory", "forget", "mood",
    ]

    def _completer(text: str, state: int):
        if text.startswith("/"):
            prefix = text[1:]
            matches = ["/" + c for c in _CMD_LIST if c.startswith(prefix)]
        else:
            matches = []
        if state < len(matches):
            return matches[state]
        return None

    readline.set_completer(_completer)
    readline.parse_and_bind("tab: complete")

    # 历史记录持久化（带文件锁，防止多实例覆盖）
    histfile = os.path.expanduser("~/.maid_coder_history")
    try:
        readline.read_history_file(histfile)
    except FileNotFoundError:
        pass
    import atexit

    def _write_history_locked(path: str) -> None:
        if sys.platform == "win32":
            # Windows: msvcrt 提供文件锁，降级为无锁写入也可接受
            try:
                import msvcrt
                with open(path, "a", encoding="utf-8") as f:
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    try:
                        readline.write_history_file(path)
                    finally:
                        try:
                            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                        except Exception:
                            pass
            except Exception:
                # msvcrt 不可用则降级为无锁写入
                readline.write_history_file(path)
        else:
            try:
                import fcntl
                with open(path, "a", encoding="utf-8") as f:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                    readline.write_history_file(path)
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except Exception:
                # 非 Unix 或 flock 不可用则降级为无锁写入
                readline.write_history_file(path)

    atexit.register(_write_history_locked, histfile)
    return True


# ---------------------------------------------------------------------------
# 配置向导
# ---------------------------------------------------------------------------
def _interactive_config_wizard() -> dict:
    """首次启动交互式配置向导。返回配置字典。"""
    print(B("\n╔═══════════════════════════════════════╗"))
    print(B("║      首次启动配置向导                  ║"))
    print(B("╚═══════════════════════════════════════╝"))

    cfg = {}

    # 输出速度
    print(C("\n1. 输出速度:"))
    print("   [1] fast   — 直接整段输出")
    print("   [2] normal — 按片段输出（推荐）")
    print("   [3] slow   — 逐字输出")
    try:
        choice = input("请选择 (1-3, 默认2): ").strip()
    except (EOFError, KeyboardInterrupt):
        choice = "2"
    speed_map = {"1": "fast", "2": "normal", "3": "slow"}
    cfg["output_speed"] = speed_map.get(choice, "normal")

    # 流式输出
    print(C("\n2. 是否开启真流式输出？"))
    print("   开启后 API 逐 chunk 返回，响应更快")
    try:
        ans = input("   开启流式输出？(Y/n, 默认n): ").strip()
    except (EOFError, KeyboardInterrupt):
        ans = "n"
    cfg["stream_mode"] = ans.lower() in ("y", "yes")

    # 多模型协作
    print(C("\n3. 是否开启多模型协作？"))
    print("   开启后每次请求会走 生成→评审→修正→裁判 流程")
    try:
        ans = input("   开启多模型协作？(Y/n, 默认n): ").strip()
    except (EOFError, KeyboardInterrupt):
        ans = "n"
    cfg["multi_enabled"] = ans.lower() in ("y", "yes")

    # 代码执行
    print(C("\n4. 是否开启代码执行沙箱？"))
    print("   允许 /run /test 命令执行 Python 代码（有 AST 安全检查）")
    try:
        ans = input("   开启代码执行？(Y/n, 默认n): ").strip()
    except (EOFError, KeyboardInterrupt):
        ans = "n"
    cfg["code_exec_enabled"] = ans.lower() in ("y", "yes")

    # 联网搜索（v10.8 起默认开启）
    print(C("\n5. 是否开启联网搜索？"))
    print("   独立 DuckDuckGo 搜索，不依赖具体 API 厂商；需要安装 duckduckgo-search")
    try:
        ans = input("   开启联网搜索？(Y/n, 默认y): ").strip()
    except (EOFError, KeyboardInterrupt):
        ans = "y"
    cfg["web_search_enabled"] = ans.lower() not in ("n", "no")

    # 剪贴板监控
    print(C("\n6. 是否开启剪贴板监控？"))
    print("   开启后检测到剪贴板有代码会自动提示粘贴")
    try:
        ans = input("   开启剪贴板监控？(Y/n, 默认n): ").strip()
    except (EOFError, KeyboardInterrupt):
        ans = "n"
    cfg["clipboard_check"] = ans.lower() in ("y", "yes")

    # 敏感信息扫描
    print(C("\n7. 是否开启敏感信息扫描？"))
    print("   检测到 API Key / 密码 / 私钥时会提示")
    try:
        ans = input("   开启敏感信息扫描？(Y/n, 默认y): ").strip()
    except (EOFError, KeyboardInterrupt):
        ans = "y"
    cfg["sensitive_info_scan"] = ans.lower() in ("y", "yes", "")

    # 统计功能
    print(C("\n8. 是否开启 Token 统计？"))
    try:
        ans = input("   开启统计？(Y/n, 默认y): ").strip()
    except (EOFError, KeyboardInterrupt):
        ans = "y"
    cfg["stats_enabled"] = ans.lower() in ("y", "yes", "")

    # 命令安全模式
    print(C("\n9. 命令安全模式:"))
    print("   [1] blacklist — 黑名单拦截危险命令（推荐）")
    print("   [2] whitelist — 白名单只允许安全命令")
    print("   [3] off       — 关闭安全检查")
    try:
        choice = input("   请选择 (1-3, 默认1): ").strip()
    except (EOFError, KeyboardInterrupt):
        choice = "1"
    safety_map = {"1": "blacklist", "2": "whitelist", "3": "off"}
    cfg["command_safety_mode"] = safety_map.get(choice, "blacklist")

    # API 厂商（v10.8）：选预设自动带出 url 与默认模型名，key 仍单独填
    from core import API_PROVIDER_PRESETS, DEFAULT_API_PROVIDER
    print(C("\n11. 选择 API 厂商（预设自动带出接口地址与默认模型名）:"))
    provider_keys = list(API_PROVIDER_PRESETS.keys())
    for i, pkey in enumerate(provider_keys, start=1):
        preset = API_PROVIDER_PRESETS[pkey]
        suffix = f" — {preset['url']}" if preset["url"] else " — 手动填写 url 与模型"
        print(f"   [{i}] {preset['label']}{suffix}")
    try:
        choice = input(f"   请选择 (1-{len(provider_keys)}, 默认1): ").strip()
    except (EOFError, KeyboardInterrupt):
        choice = "1"
    try:
        idx = int(choice) - 1
        cfg["api_provider"] = provider_keys[idx] if 0 <= idx < len(provider_keys) else DEFAULT_API_PROVIDER
    except ValueError:
        cfg["api_provider"] = DEFAULT_API_PROVIDER

    # Persona（可选快速设置）
    print(C("\n10. 角色设定（可选，直接回车使用默认女仆）:"))
    try:
        role = input("   角色名 (默认: 女仆): ").strip()
    except (EOFError, KeyboardInterrupt):
        role = ""
    if role:
        cfg["persona_role"] = role
    try:
        title = input("   职称 (默认: 资深全栈开发工程师): ").strip()
    except (EOFError, KeyboardInterrupt):
        title = ""
    if title:
        cfg["persona_title"] = title

    # 填充其余默认值，确保配置完整
    defaults = AppConfig()
    for field_name in [f.name for f in fields(AppConfig)]:
        if field_name not in cfg:
            cfg[field_name] = getattr(defaults, field_name)

    print(G("\n✅ 配置完成！已保存到 config.yaml"))
    print(GR("   随时可手动编辑 config.yaml 调整更多选项。\n"))
    return cfg


# ---------------------------------------------------------------------------
# 崩溃恢复
# ---------------------------------------------------------------------------
_RECOVERY_FILE = "session_recovery.json"

def _save_recovery(session: ChatSession) -> None:
    """保存会话恢复点。"""
    try:
        data = {
            "session_id": session.session_id,
            "timestamp": time.time(),
            "history": session.history[-20:] if len(session.history) > 20 else session.history,
            "turn_count": session.turn_count,
            "deep_mode": session.deep_mode,
            "coding_mode": session.coding_mode,
            "multi_mode": session.multi_mode,
            "stream_mode": session.stream_mode,
            "speed": session.speed,
            "current_role": session.agent_sys.current_role if hasattr(session, "agent_sys") else None,
            # Phase 1 MVP: 聊天增强状态
            "chat_mode": session.chat_mode.is_chat_mode if hasattr(session, "chat_mode") else False,
            "memory": session.memory_mgr.to_dict() if hasattr(session, "memory_mgr") else {},
            "intimacy": session.intimacy.to_dict() if hasattr(session, "intimacy") else {},
        }
        with open(_RECOVERY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _check_recovery(session: ChatSession) -> bool:
    """检测是否有崩溃恢复数据。返回是否已恢复。"""
    if not os.path.exists(_RECOVERY_FILE):
        return False
    try:
        with open(_RECOVERY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not data.get("history"):
            return False
        print(Y("\n⚠️ 检测到上次未正常退出。"))
        try:
            ans = input("是否恢复上次的对话？(Y/n/d 删除): ").strip()
        except (EOFError, KeyboardInterrupt):
            ans = "n"
        if ans.lower() in ("y", "yes", ""):
            session.session_id = data.get("session_id", "default")
            session.history = data.get("history", [])
            session.turn_count = data.get("turn_count", 0)
            session.deep_mode = data.get("deep_mode", False)
            session.coding_mode = data.get("coding_mode", False)
            session.multi_mode = data.get("multi_mode", False)
            session.stream_mode = data.get("stream_mode", False)
            session.speed = data.get("speed", "normal")
            if hasattr(session, "agent_sys"):
                session.agent_sys.current_role = data.get("current_role", None)
            # Phase 1 MVP: 恢复聊天增强状态
            if hasattr(session, "chat_mode") and "chat_mode" in data:
                session.chat_mode.toggle_chat(force=data["chat_mode"])
            if hasattr(session, "memory_mgr") and "memory" in data:
                session.memory_mgr.from_dict(data["memory"])
            if hasattr(session, "intimacy") and "intimacy" in data:
                session.intimacy.from_dict(data["intimacy"])
            print(G(f"✅ 已恢复会话 '{session.session_id}'（最近 {len(session.history)} 条消息）"))
            # 恢复成功后删除恢复文件
            try:
                os.remove(_RECOVERY_FILE)
            except Exception:
                pass
            return True
        elif ans.lower() == "d":
            try:
                os.remove(_RECOVERY_FILE)
            except Exception:
                pass
            print("已删除恢复文件。")
        else:
            print("已跳过恢复，恢复文件保留以便下次启动再次提示。")
    except Exception as e:
        print(GR(f"恢复失败: {e}"))
        # 读取失败时删除损坏的恢复文件
        try:
            os.remove(_RECOVERY_FILE)
        except Exception:
            pass
    return False


# ---------------------------------------------------------------------------
# 新功能辅助函数（P1/P2）
# ---------------------------------------------------------------------------

def _backup_path(filepath: str) -> str:
    """生成带时间戳的备份路径，避免覆盖历史备份。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{filepath}.bak.{ts}"


def _find_latest_backup(filepath: str) -> Optional[str]:
    """查找文件最新的备份（支持旧 .bak 和新 .bak.时间戳）。"""
    import glob
    candidates = glob.glob(f"{filepath}.bak.*")
    if candidates:
        return max(candidates, key=os.path.getmtime)
    # 兼容旧版 .bak
    old_bak = filepath + ".bak"
    if os.path.exists(old_bak):
        return old_bak
    return None


def _show_diff(filepath: str) -> str:
    """P1-5: 显示文件与 .bak 备份的差异。"""
    bak_path = _find_latest_backup(filepath)
    if not os.path.exists(filepath):
        return f"文件不存在: {filepath}"
    if not bak_path or not os.path.exists(bak_path):
        return f"备份文件不存在: {filepath}.bak*"
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            current = f.readlines()
        with open(bak_path, "r", encoding="utf-8", errors="replace") as f:
            original = f.readlines()
        import difflib
        diff = list(difflib.unified_diff(original, current, fromfile=bak_path, tofile=filepath, lineterm=""))
        if not diff:
            return "ℹ️ 文件与备份一致，无差异。"
        lines = ["📋 差异对比 (+新增 / -删除):"]
        for line in diff[:200]:  # 限制输出量
            if line.startswith("+"):
                lines.append(G(line))
            elif line.startswith("-"):
                lines.append(R(line))
            else:
                lines.append(line)
        if len(diff) > 200:
            lines.append(f"... ({len(diff) - 200} 行省略)")
        return "\n".join(lines)
    except Exception as e:
        return f"生成 diff 失败: {e}"


def _code_score(code: str) -> str:
    """P1-6: 基于启发式规则的代码质量评分。"""
    lines = code.splitlines()
    total_lines = len(lines)
    non_empty = [l for l in lines if l.strip()]

    # 用 AST 过滤注释和字符串，获取纯代码行
    code_lines = []
    try:
        tree = ast.parse(code)
        # 收集所有字符串节点的行号
        string_lines = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if hasattr(node, "lineno"):
                    for ln in range(getattr(node, "lineno", 1), getattr(node, "end_lineno", node.lineno) + 1):
                        string_lines.add(ln)
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                if hasattr(node, "lineno"):
                    string_lines.add(node.lineno)
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("\"\"") or stripped.startswith("'''"):
                continue
            if i in string_lines and (stripped.startswith('"') or stripped.startswith("'") or stripped.startswith('f"') or stripped.startswith("f'")):
                continue
            code_lines.append(line)
    except SyntaxError:
        code_lines = non_empty

    # 复杂度：嵌套深度
    max_indent = 0
    for line in code_lines:
        indent = len(line) - len(line.lstrip())
        max_indent = max(max_indent, indent)
    depth = max_indent // 4
    complexity = min(10, max(1, depth + len([l for l in code_lines if any(k in l for k in ("if ", "for ", "while ", "def ", "class "))]) // 3))

    # 可读性：目标行长度放宽到 100
    avg_len = sum(len(l) for l in non_empty) / max(1, len(non_empty))
    readability = max(1, min(10, 10 - abs(avg_len - 100) // 20))

    # 潜在问题（基于 AST 过滤后的代码行）
    issues = []
    if any("TODO" in l or "FIXME" in l for l in code_lines):
        issues.append("包含 TODO/FIXME 未解决项")
    if any("print(" in l for l in code_lines):
        issues.append("包含调试 print 语句")
    if any("except:" in l for l in code_lines):
        issues.append("存在裸 except: 可能吞掉异常")
    if depth > 4:
        issues.append(f"嵌套深度达 {depth} 层，建议拆分")

    score_text = f"""📊 代码质量评分
  总行数: {total_lines} | 非空行: {len(non_empty)}
  复杂度: {complexity}/10 {'🔴' if complexity > 7 else '🟡' if complexity > 4 else '🟢'}
  可读性: {readability}/10 {'🔴' if readability < 4 else '🟡' if readability < 7 else '🟢'}
  潜在问题 ({len(issues)} 条):
"""
    if issues:
        for issue in issues:
            score_text += f"    - {issue}\n"
    else:
        score_text += "    (无)\n"
    return score_text


# 项目模板定义
_TEMPLATES: Dict[str, Dict[str, str]] = {
    "fastapi": {
        "main.py": '''from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def read_root():
    return {"Hello": "World"}
''',
        "requirements.txt": "fastapi\nuvicorn[standard]\n",
        "README.md": "# FastAPI Project\n\nRun: `uvicorn main:app --reload`\n",
    },
    "flask": {
        "app.py": '''from flask import Flask

app = Flask(__name__)

@app.route("/")
def hello():
    return "Hello, World!"
''',
        "requirements.txt": "flask\n",
        "README.md": "# Flask Project\n\nRun: `flask --app app run`\n",
    },
    "express": {
        "app.js": '''const express = require('express');
const app = express();
const port = 3000;

app.get('/', (req, res) => {
  res.send('Hello World!');
});

app.listen(port, () => {
  console.log(`Example app listening on port ${port}`);
});
''',
        "package.json": '{"name": "express-app", "version": "1.0.0", "dependencies": {"express": "^4.18.0"}}\n',
        "README.md": "# Express Project\n\nRun: `node app.js`\n",
    },
    "react": {
        "src/App.jsx": '''function App() {
  return (
    <div className="App">
      <h1>Hello React</h1>
    </div>
  );
}

export default App;
''',
        "package.json": '{"name": "react-app", "version": "1.0.0", "dependencies": {"react": "^18.0.0", "react-dom": "^18.0.0"}}\n',
        "README.md": "# React Project\n\nRun: `npm start`\n",
    },
}


def _generate_template(template_type: str, target_dir: str) -> str:
    """P1-7: 生成项目模板骨架。"""
    template_type = template_type.lower()
    if template_type not in _TEMPLATES:
        available = ", ".join(_TEMPLATES.keys())
        return f"未知模板类型。可用: {available}"

    import pathlib
    base = pathlib.Path(target_dir)
    base.mkdir(parents=True, exist_ok=True)

    files = _TEMPLATES[template_type]
    overwritten = []
    for rel_path, content in files.items():
        p = base / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists():
            overwritten.append(str(p))
            # 自动重命名已存在文件为 .bak
            bak = p.with_suffix(p.suffix + ".bak")
            try:
                import shutil
                shutil.copy2(p, bak)
            except Exception:
                pass
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)

    msg = G(f"✅ 已生成 {template_type} 项目骨架到 {target_dir}（{len(files)} 个文件）")
    if overwritten:
        msg += f"\n{Y('⚠️ 以下文件已存在，原文件已备份为 .bak:')}\n  " + "\n  ".join(overwritten)
    return msg


_SKIP_DIRS = {".git", ".github", ".svn", "node_modules", "venv", "__pycache__", "dist", "build", ".pytest_cache", ".mypy_cache", ".tox"}


def _validate_file_path(filepath: str, workspace: str = ".") -> Tuple[bool, str]:
    """验证文件路径是否在工作空间内，防止路径遍历。"""
    try:
        target = (Path(workspace) / filepath).resolve()
        base = Path(workspace).resolve()
        # 检查路径是否以 base 开头
        try:
            target.relative_to(base)
        except ValueError:
            return False, f"路径越界: {filepath} 不在工作目录 {workspace} 内"
        # 拒绝包含 .. 的原始路径
        if ".." in filepath.replace("\\", "/"):
            return False, "路径包含非法的父目录引用 .."
        return True, str(target)
    except Exception as e:
        return False, f"路径验证失败: {e}"


def _batch_replace_preview(pattern: str, replacement: str, glob_expr: str, workspace: str = ".") -> Tuple[List[str], int, Dict[str, str]]:
    """P1-8: 批量替换预览。返回 (文件列表, 总替换数, 原始内容字典)。"""
    import fnmatch
    matches = []
    total = 0
    originals: Dict[str, str] = {}
    workspace_path = Path(workspace).resolve()
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fname in files:
            if fnmatch.fnmatch(fname, glob_expr):
                path = os.path.join(root, fname)
                # 路径遍历校验
                try:
                    resolved = Path(path).resolve()
                    resolved.relative_to(workspace_path)
                except ValueError:
                    continue
                try:
                    size = os.path.getsize(path)
                    if size > 1_048_576:
                        continue
                    with open(path, "rb") as f:
                        raw = f.read()
                    if b"\x00" in raw:
                        continue
                    content = raw.decode("utf-8", errors="replace")
                    count = content.count(pattern)
                    if count > 0:
                        matches.append(f"  {path}: {count} 处")
                        total += count
                        originals[path] = content  # 保存原始内容供备份用
                except Exception:
                    pass
    return matches, total, originals


def _batch_replace_apply(pattern: str, replacement: str, glob_expr: str, originals: Dict[str, str], workspace: str = ".") -> Tuple[int, int]:
    """P1-8: 执行批量替换。返回 (文件数, 总替换数)。"""
    import fnmatch
    import shutil
    file_count = 0
    total = 0
    workspace_path = Path(workspace).resolve()
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fname in files:
            if fnmatch.fnmatch(fname, glob_expr):
                path = os.path.join(root, fname)
                # 路径遍历校验
                try:
                    resolved = Path(path).resolve()
                    resolved.relative_to(workspace_path)
                except ValueError:
                    continue
                try:
                    size = os.path.getsize(path)
                    if size > 1_048_576:
                        continue
                    with open(path, "rb") as f:
                        raw = f.read()
                    if b"\x00" in raw:
                        continue
                    content = raw.decode("utf-8", errors="replace")
                    new_content = content.replace(pattern, replacement)
                    if new_content != content:
                        # 使用预览时保存的原始内容创建备份（避免预览后文件被修改）
                        original_content = originals.get(path, content)
                        bak_path = _backup_path(path)
                        with open(bak_path, "w", encoding="utf-8") as f:
                            f.write(original_content)
                        with open(path, "w", encoding="utf-8") as f:
                            f.write(new_content)
                        file_count += 1
                        total += content.count(pattern)
                except Exception:
                    pass
    return file_count, total


def _test_regex(pattern: str, text: str) -> str:
    """P1-9: 正则测试工具。"""
    try:
        import re
        compiled = re.compile(pattern)
        matches = list(compiled.finditer(text))
        if not matches:
            return "ℹ️ 无匹配结果。"
        lines = [f"🔍 正则: /{pattern}/", f"📄 测试文本: {text[:200]}", f"✅ 匹配数: {len(matches)}", ""]
        for i, m in enumerate(matches, 1):
            lines.append(f"  匹配 {i}: '{m.group()}' @ 位置 {m.start()}-{m.end()}")
            if m.groups():
                for j, g in enumerate(m.groups(), 1):
                    lines.append(f"    分组 {j}: '{g}'")
        return "\n".join(lines)
    except Exception as e:
        return f"正则错误: {e}"


def _format_data(text: str) -> str:
    """P1-10: JSON/YAML/XML 格式化。"""
    text = text.strip()
    if text.startswith("<") and ">" in text:
        # XML
        try:
            import xml.dom.minidom
            import xml.sax
            import xml.sax.handler
            # 拒绝内部实体膨胀攻击（Billion Laughs）
            if "<!ENTITY" in text.upper():
                return "XML 格式化失败: 输入包含 <!ENTITY。为防御 Billion Laughs 攻击，含实体声明的 XML 被禁止。如需处理此类 XML，请手动去除实体声明后重试。"
            # 禁用 DTD 和外部实体，防止 XXE
            parser = xml.sax.make_parser()
            parser.setFeature(xml.sax.handler.feature_external_ges, False)
            parser.setFeature(xml.sax.handler.feature_external_pes, False)
            dom = xml.dom.minidom.parseString(text, parser)
            return dom.toprettyxml(indent="  ")
        except Exception as e:
            return f"XML 格式化失败: {e}"
    elif text.startswith("{") or text.startswith("["):
        # JSON
        try:
            data = json.loads(text)
            return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
        except Exception as e:
            return f"JSON 格式化失败: {e}"
    elif ":" in text.splitlines()[0] if text else False:
        # YAML (简单检测)
        try:
            if _HAS_YAML:
                import yaml
                data = yaml.safe_load(text)
                return yaml.dump(data, allow_unicode=True, sort_keys=True, default_flow_style=False)
            else:
                return "YAML 格式化需要安装 PyYAML: pip install pyyaml"
        except Exception as e:
            return f"YAML 格式化失败: {e}"
    return "无法识别格式。支持 JSON / YAML / XML。"


def _ocr_image(image_path: str) -> str:
    """P1-13: 图片 OCR 识别。"""
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(image_path)
        text = pytesseract.image_to_string(img, lang="chi_sim+eng")
        return f"🖼️ OCR 结果:\n{text[:2000]}"
    except ImportError:
        return "⚠️ OCR 需要安装依赖: pip install pytesseract pillow\n   并安装 Tesseract-OCR 引擎。"
    except Exception as e:
        return f"OCR 失败: {e}"


def _profile_code(code: str, timeout: int = 5) -> str:
    """P1-15: 性能分析。将用户代码写入独立文件，避免 f-string 拼接导致的注入风险。"""
    import time
    import tempfile

    result = {"stdout": "", "stderr": "", "elapsed": 0, "peak_mem": 0}
    user_tmp_path = None
    wrapper_tmp_path = None

    try:
        # 将用户代码写入独立临时文件，避免字符串拼接注入
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(code)
            user_tmp_path = f.name

        # v10.15: 进程级隔离（非沙箱：仍是独立 Python 进程，仍可读取文件/访问网络，
        # 仅阻止主进程被用户代码异常拖崩；不能当作安全沙箱使用）。
        if sys.platform == "win32":
            # Windows 无 resource 模块，使用 psutil 或仅测时间
            wrapper_code = """import sys, time
_USER_CODE_PATH = sys.argv[1]
_start = time.perf_counter()
try:
    exec(open(_USER_CODE_PATH, "r", encoding="utf-8").read())
finally:
    _elapsed = time.perf_counter() - _start
    print("\\n___PROFILE_TIME___" + str(_elapsed), file=sys.stderr)
    # Windows: 尝试用 psutil 获取峰值内存
    try:
        import psutil
        proc = psutil.Process()
        peak_kb = proc.memory_info().rss / 1024
        print("\\n___PROFILE_MEM___" + str(peak_kb), file=sys.stderr)
    except Exception:
        pass
"""
        else:
            wrapper_code = """import resource, sys
_USER_CODE_PATH = sys.argv[1]
try:
    exec(open(_USER_CODE_PATH, "r", encoding="utf-8").read())
finally:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    peak_kb = usage.ru_maxrss
    if sys.platform == "darwin":
        peak_kb = peak_kb / 1024
    print("\\n___PROFILE_MEM___" + str(peak_kb), file=sys.stderr)
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(wrapper_code)
            wrapper_tmp_path = f.name

        start = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, wrapper_tmp_path, user_tmp_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
        )
        elapsed = time.perf_counter() - start

        # 从 stderr 解析内存测量值
        peak_kb = 0
        for line in proc.stderr.splitlines():
            if line.strip().startswith("___PROFILE_MEM___"):
                try:
                    peak_kb = float(line.strip().split("___PROFILE_MEM___")[1])
                except (IndexError, ValueError):
                    pass
                break
        peak_mb = peak_kb / 1024

        # 清理临时文件
        try:
            if user_tmp_path and os.path.exists(user_tmp_path):
                os.unlink(user_tmp_path)
        except Exception:
            pass
        try:
            if wrapper_tmp_path and os.path.exists(wrapper_tmp_path):
                os.unlink(wrapper_tmp_path)
        except Exception:
            pass

        result["stdout"] = proc.stdout
        result["stderr"] = proc.stderr
        result["elapsed"] = elapsed
        result["peak_mem"] = peak_mb

        lines = [
            "📊 性能分析结果",
            f"  执行时间: {elapsed:.3f}s",
            f"  峰值内存: {result['peak_mem']:.2f} MB",
            f"  退出码: {proc.returncode}",
        ]
        if result["stdout"]:
            lines.append(f"  stdout:\n{result['stdout'][:500]}")
        # stderr 中过滤掉我们的测量标记
        filtered_stderr = "\n".join(
            line for line in proc.stderr.splitlines()
            if not line.strip().startswith("___PROFILE_MEM___")
        )
        if filtered_stderr:
            lines.append(f"  stderr:\n{filtered_stderr[:500]}")
        return "\n".join(lines)
    except subprocess.TimeoutExpired:
        # 超时后也要清理临时文件
        try:
            if user_tmp_path and os.path.exists(user_tmp_path):
                os.unlink(user_tmp_path)
        except Exception:
            pass
        try:
            if wrapper_tmp_path and os.path.exists(wrapper_tmp_path):
                os.unlink(wrapper_tmp_path)
        except Exception:
            pass
        return f"⏱️ 执行超时（>{timeout}s）"
    except Exception as e:
        # 异常后也要清理临时文件
        try:
            if user_tmp_path and os.path.exists(user_tmp_path):
                os.unlink(user_tmp_path)
        except Exception:
            pass
        try:
            if wrapper_tmp_path and os.path.exists(wrapper_tmp_path):
                os.unlink(wrapper_tmp_path)
        except Exception:
            pass
        return f"性能分析失败: {e}"


def _share_session(session: ChatSession) -> str:
    """P2-17: 生成会话摘要。"""
    recent = session.history[-10:] if len(session.history) > 10 else session.history
    lines = ["📋 会话摘要", f"会话ID: {session.session_id}", f"总轮数: {session.turn_count}", ""]
    for msg in recent:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        preview = content[:80].replace("\n", " ")
        if len(content) > 80:
            preview += "..."
        lines.append(f"[{role}] {preview}")
    return "\n".join(lines)


def _generate_dockerfile(workspace: str = ".") -> str:
    """P2-18: 根据依赖自动生成 Dockerfile。"""
    # 检测项目类型（基于 workspace 目录）
    ws = Path(workspace).resolve()
    req_txt = ws / "requirements.txt"
    setup_py = ws / "setup.py"
    pyproject = ws / "pyproject.toml"
    pkg_json = ws / "package.json"
    cargo = ws / "Cargo.toml"
    go_mod = ws / "go.mod"

    if req_txt.exists() or setup_py.exists() or pyproject.exists():
        base = "python:3.11-slim"
        dep_cmds = [
            "COPY requirements.txt ." if req_txt.exists() else "COPY pyproject.toml .",
            "RUN pip install --no-cache-dir -r requirements.txt" if req_txt.exists() else "RUN pip install --no-cache-dir .",
        ]
        cmd = '["python", "main.py"]'
    elif pkg_json.exists():
        base = "node:18-alpine"
        dep_cmds = [
            "COPY package.json package-lock.json* ./",
            "RUN npm ci",
        ]
        cmd = '["npm", "start"]'
    elif cargo.exists():
        base = "rust:1.75-slim"
        dep_cmds = [
            "COPY Cargo.toml .",
            "RUN cargo build --release",
        ]
        cmd = '["./target/release/app"]'
    elif go_mod.exists():
        base = "golang:1.21-alpine"
        dep_cmds = [
            "COPY go.mod go.sum ./",
            "RUN go mod download",
            "RUN go build -o app",
        ]
        cmd = '["./app"]'
    else:
        base = "python:3.11-slim"
        dep_cmds = ["# 未检测到常见依赖文件，请手动添加 COPY 和 RUN 指令"]
        cmd = '["python", "main.py"]  # 请根据实际入口修改'

    dockerfile = [f"FROM {base}", "WORKDIR /app", ""]
    dockerfile.extend(dep_cmds)
    dockerfile.append("")
    dockerfile.append("COPY . .")
    dockerfile.append(f'CMD {cmd}')

    out_path = ws / "Dockerfile"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(dockerfile))
    return G(f"✅ 已生成 Dockerfile 到 {out_path}（基础镜像: {base}）")


# 离线缓存
_OFFLINE_CACHE: Dict[str, str] = {}
_OFFLINE_CACHE_FILE = "maid_coder_cache.json"

def _load_offline_cache() -> None:
    global _OFFLINE_CACHE
    if os.path.exists(_OFFLINE_CACHE_FILE):
        try:
            with open(_OFFLINE_CACHE_FILE, "r", encoding="utf-8") as f:
                _OFFLINE_CACHE = json.load(f)
        except Exception:
            _OFFLINE_CACHE = {}


def _save_offline_cache() -> None:
    try:
        with open(_OFFLINE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_OFFLINE_CACHE, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _offline_cache_get(query: str) -> Optional[str]:
    """P2-19: 从本地缓存读取最近成功的相似回答。"""
    if not _OFFLINE_CACHE:
        return None
    # 简单模糊匹配：找包含 query 关键词的缓存项
    q_words = set(query.lower().split())
    best_key, best_score = None, 0
    for key in _OFFLINE_CACHE:
        k_words = set(key.lower().split())
        score = len(q_words & k_words)
        if score > best_score:
            best_score = score
            best_key = key
    if best_score >= max(1, int(len(q_words) * 0.7)):
        return _OFFLINE_CACHE[best_key]
    return None


def _offline_cache_save(query: str, answer: str) -> None:
    """保存回答到离线缓存。"""
    _OFFLINE_CACHE[query] = answer
    if len(_OFFLINE_CACHE) > 100:
        # 简单 LRU：只保留最新的 50 条
        keys = list(_OFFLINE_CACHE.keys())
        for k in keys[:-50]:
            del _OFFLINE_CACHE[k]
    _save_offline_cache()


# 审计日志
_AUDIT_LOG_FILE = "audit.log"

def _audit_log(action: str, detail: str) -> None:
    """P2-21: 记录操作日志。"""
    try:
        # 敏感信息掩码
        import re as _re
        detail = _re.sub(r"(sk-[a-zA-Z0-9]{4})[a-zA-Z0-9]*([a-zA-Z0-9]{4})", r"\1...\2", detail)
        # 换行符转义
        detail = detail.replace("\n", "\\n").replace("\r", "\\r")
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(_AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {action}: {detail}\n")
        # 确保日志文件权限为 0o600（Unix  only）
        import platform
        if platform.system() != "Windows":
            os.chmod(_AUDIT_LOG_FILE, 0o600)
    except Exception:
        pass


def _read_audit_log(limit: int = 20) -> str:
    """读取最近审计日志。"""
    if not os.path.exists(_AUDIT_LOG_FILE):
        return "暂无审计记录。"
    try:
        with open(_AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if not lines:
            return "暂无审计记录。"
        recent = lines[-limit:]
        return "📋 最近操作记录:\n" + "".join(recent)
    except Exception as e:
        return f"读取审计日志失败: {e}"


# 多 API Key 轮换
