#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
女仆编程师 v2.0 — 完全重构版
一款带多模型协作、工具调用、会话持久化、多Agent系统、联网搜索的 AI 聊天机器人。

快速开始：
    export DEEPSEEK_API_KEY="sk-xxx"
    python maid_coder_v2.py
"""

from __future__ import annotations

import ast
import difflib
import hashlib
import importlib.util
import io
import json
import logging
import math
import os
import re
import shlex
import subprocess
import sys
import tempfile
import textwrap
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Callable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------------------------------------------------------------------------
# 可选依赖：优雅降级
# ---------------------------------------------------------------------------
try:
    import colorama
    colorama.init()
    _HAS_COLORAMA = True
except ImportError:
    _HAS_COLORAMA = False

try:
    from dotenv import load_dotenv
    load_dotenv()
    _HAS_DOTENV = True
except ImportError:
    _HAS_DOTENV = False

try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

try:
    import pyperclip
    _HAS_PYPERCLIP = True
except ImportError:
    _HAS_PYPERCLIP = False

try:
    from ddgs import DDGS
    _HAS_DDGS = True
except ImportError:
    try:
        from duckduckgo_search import DDGS
        _HAS_DDGS = True
    except ImportError:
        DDGS = None  # type: ignore
        _HAS_DDGS = False

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False


# ---------------------------------------------------------------------------
# 版本常量（v10.14 引入，run.py / run.bat / run.sh / install.* 共用此单一来源）
# ---------------------------------------------------------------------------
def parse_version(v: str) -> tuple:
    """'1.10.0' -> (1, 10, 0)；剥离预发布/构建后缀。

    v1.0.0 起为版本比较的唯一实现（执行文档 2.3）：
    一切版本比较（更新检查、min_compatible 判断）必须按数值元组，
    禁止字符串比较——字符串序中 "1.10.0" < "1.9.0"（逐字符比较
    '1'=='1'、'.'=='.'、'1'<'9'），会把新版误判为旧版。
    """
    core = str(v).split("-")[0].split("+")[0]
    return tuple(int(x) for x in core.split("."))


def is_newer_version(remote: str, local: str) -> bool:
    """remote 是否比 local 新（更新检查用）。

    预发布版本（-rc 后缀）视为低于同号正式版：1.1.0-rc.1 < 1.1.0，
    仅防内测误判；正式渠道不分发 rc 版。
    """
    r_core, l_core = parse_version(remote), parse_version(local)
    if r_core != l_core:
        return r_core > l_core
    # 核心号相同：仅当 remote 为正式版且 local 为预发布版时才算更新
    return _is_release(remote) and not _is_release(local)


def _is_release(v: str) -> bool:
    """无 -rc 等预发布后缀视为正式版。"""
    return "-" not in str(v)


__version__ = "1.5.0"  # v1.4.8: 改为从 version.py 读取，此处保留兼容旧代码
APP_NAME = "maid_coder"

# v1.4.8: 版本号单源——从 version.json 读取
try:
    from version import get_version as _get_version
    __version__ = _get_version()
except ImportError:
    pass  # 使用上面硬编码的默认值


# ---------------------------------------------------------------------------
# 颜色 / 样式
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _Styles:
    RESET: str = "\033[0m"
    BOLD: str = "\033[1m"
    DIM: str = "\033[2m"
    RED: str = "\033[91m"
    GREEN: str = "\033[92m"
    YELLOW: str = "\033[93m"
    BLUE: str = "\033[94m"
    MAGENTA: str = "\033[95m"
    CYAN: str = "\033[96m"
    WHITE: str = "\033[97m"
    GRAY: str = "\033[90m"

STYLES = _Styles()

def _fmt(text: str, *codes: str) -> str:
    if not _HAS_COLORAMA:
        return text
    return "".join(codes) + text + STYLES.RESET

R = lambda t: _fmt(t, STYLES.RED)
G = lambda t: _fmt(t, STYLES.GREEN)
Y = lambda t: _fmt(t, STYLES.YELLOW)
B = lambda t: _fmt(t, STYLES.BLUE)
C = lambda t: _fmt(t, STYLES.CYAN)
M = lambda t: _fmt(t, STYLES.MAGENTA)
W = lambda t: _fmt(t, STYLES.WHITE)
GR = lambda t: _fmt(t, STYLES.GRAY)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
DANGEROUS_COMMANDS = [
    "rm -rf", "mkfs", "dd if=", "format", "del /f /s /q",
    "> /dev/sd", "mkfs.ext", "mkfs.ntfs", "mkfs.fat",
    "shutdown", "reboot", "poweroff", "init 0",
    "chmod -R 777 /", "chmod -R 000 /",
    r"wget.*\|.*sh", r"curl.*\|.*sh",
    ":(){ :|:& };:", "> /etc/passwd", "> /etc/shadow",
]

SAFE_COMMAND_WHITELIST = [
    "python", "python3", "pytest",
    "gcc", "g++", "javac", "java",
    "cargo", "rustc", "go",
    "black", "flake8", "mypy", "isort",
]

SENSITIVE_PATTERNS = [
    (r"(?i)(api[_-]?key\s*[:=]\s*[\"']?)(sk-[a-zA-Z0-9]{20,})", "API Key"),
    (r"(?i)(password\s*[:=]\s*[\"']?)([^\"'\s]{8,})", "密码"),
    (r"(?i)(token\s*[:=]\s*[\"']?)([a-zA-Z0-9_-]{20,})", "Token"),
    (r"(-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----)", "私钥"),
    (r"(?i)(secret\s*[:=]\s*[\"']?)([^\"'\s]{8,})", "Secret"),
    (r"(AK[A-Z0-9]{18,})", "AWS Access Key"),
]

AGENT_ROLES = {
    "product": {
        "name": "产品经理",
        "desc": "需求分析、功能规划、用户故事撰写",
        "prompt": (
            "你是一位资深产品经理，擅长需求分析、功能规划和用户故事撰写。\n"
            "你的职责：\n"
            "- 深入理解用户需求，提炼核心功能点\n"
            "- 撰写清晰的用户故事和验收标准\n"
            "- 评估功能优先级和可行性\n"
            "- 输出结构化的 PRD（产品需求文档）\n"
            "回复时保持专业、简洁，使用 Markdown 格式。"
        ),
    },
    "arch": {
        "name": "架构师",
        "desc": "系统设计、技术选型、接口设计、性能评估",
        "prompt": (
            "你是一位资深系统架构师，擅长技术选型、系统设计和性能评估。\n"
            "你的职责：\n"
            "- 设计清晰、可扩展的系统架构\n"
            "- 评估技术方案的优劣和适用场景\n"
            "- 设计 RESTful / GraphQL / gRPC 接口\n"
            "- 给出性能优化建议和容量规划\n"
            "回复时使用技术图表、伪代码和结构化描述。"
        ),
    },
    "dev": {
        "name": "研发工程师",
        "desc": "写代码、Debug、工具调用",
        "prompt": (
            "你是一位资深全栈研发工程师，擅长编写高质量代码和调试。\n"
            "你的职责：\n"
            "- 编写完整、可运行、带注释的代码\n"
            "- 分析报错日志并给出修复方案\n"
            "- 进行代码重构和优化\n"
            "- 输出单元测试和集成测试\n"
            "代码块使用 ``` 包裹，语言标识明确。"
        ),
    },
    "review": {
        "name": "代码质检官",
        "desc": "代码审查、安全扫描、测试建议",
        "prompt": (
            "你是一位严格的代码审查专家，专注于代码质量和安全。\n"
            "你的职责：\n"
            "- 审查代码中的潜在 Bug 和逻辑漏洞\n"
            "- 扫描安全隐患（SQL注入、XSS、越权等）\n"
            "- 评估代码可读性和可维护性\n"
            "- 给出测试覆盖建议\n"
            "发现严重问题时必须明确指出，不回避。"
        ),
    },
}


# ---------------------------------------------------------------------------
# API 厂商预设（v10.8）
# 所有预设均为 OpenAI 兼容的 chat/completions 端点；选定预设后 url 与默认模型自动带出，
# API Key 仍需单独填写。custom 为完全手动模式。
# v1.2(B9/D8)：每条预设增 desc（一句话说明）/ is_local（本地运行无需 Key）展示元字段，
# 供 ModelConfigPanel 厂商卡片平铺点选（B9④）；既有消费方只读 label/url/models/default_model，
# 新字段必须用 .get() 兜底访问，保持向后兼容。
# ---------------------------------------------------------------------------
API_PROVIDER_PRESETS: Dict[str, Dict[str, Any]] = {
    # 模型清单依据各厂商官方文档核对（2026-09-10）。规则：
    #   models         = 该厂商当前可用的模型 ID（下拉候选）
    #   vision_models  = 其中支持图片理解（视觉/多模态）的模型，供「AI 看图/拍照/截图提问」使用
    #   default_model  = 当前推荐的主力型号，必须是 models 中的一项
    # 更新原则（v1.7.3 起）：只增不删（用户配置里可能存着旧 model id，删除会破坏可用性）、
    #   最新在前、default 换该厂当前主推款。厂商会下线旧模型（例：DeepSeek 的
    #   deepseek-chat/deepseek-reasoner 已于 2026-07-24 退役，Moonshot 的 kimi-k2 系列与
    #   kimi-latest 已下线），清单只保留当前可用项（含官方明确保留的过渡别名）。
    "deepseek": {
        "label": "DeepSeek（默认）",
        "url": "https://api.deepseek.com/chat/completions",
        "default_model": "deepseek-flash",
        "models": [
            # 2026-09-10 官方文档：deepseek-flash = DeepSeek-V4.1-Flash（官方推荐名，原生多模态视觉）
            "deepseek-flash",
            "deepseek-v4-pro",
            # 官方保留的过渡别名（v4-flash / vision-exp 对应模型已退役，请求改由 V4.1-Flash 承接）
            "deepseek-v4-flash",
            "deepseek-v4-flash-vision-exp",
        ],
        "vision_models": ["deepseek-flash", "deepseek-v4-flash-vision-exp"],
        "desc": "DeepSeek 官方 · deepseek-flash = V4.1-Flash 主力（原生视觉，1M 上下文）；v4-pro 自 2026-09-14 起并入 V4.1",
        "is_local": False,
    },
    "zhipu": {
        "label": "智谱 GLM",
        "url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "default_model": "glm-5.3-flash",
        "models": [
            # 2026-09 官方 Model Code；glm-5.3-flash 原生多模态（图/视频/文件），1M 上下文
            "glm-5.3-flash",
            "glm-5.3",
            "glm-5.2",
            "glm-5.1",
            "glm-5",
            "glm-5-turbo",
            "glm-4.7-flash",
            "glm-4.6",
            "glm-4.5-flash",
            "glm-4-flash-250414",
            "glm-4.6v",
            "glm-4.6v-flash",
            "glm-4.1v-thinking-flash",
            "glm-4v-flash",
            "glm-5v-turbo",
        ],
        "vision_models": [
            "glm-5.3-flash",
            "glm-4.6v",
            "glm-4.6v-flash",
            "glm-4.1v-thinking-flash",
            "glm-4v-flash",
            "glm-5v-turbo",
        ],
        "desc": "智谱 GLM · 国产直连；glm-5.3-flash 原生多模态（看图/看屏首选），另有免费视觉型号",
        "is_local": False,
    },
    "qwen": {
        "label": "通义千问（阿里云百炼）",
        "url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "default_model": "qwen3.8-flash",
        "models": [
            # 2026-09 百炼在售：qwen3.8 档为最新（max 旗舰 / flash 轻量）
            "qwen3.8-flash",
            "qwen3.8-max",
            "qwen-plus",
            "qwen-flash",
            "qwen-long",
            "qwen3.7-plus",
            "qwen3.7-flash",
            "qwen3.6-plus",
            "qwen3.6-flash",
            "qwen3.5-plus",
            "qwen3.5-flash",
            "qwen3-vl-plus",
            "qwen3-vl-flash",
            "qwen-vl-max",
            "qwen-vl-plus",
            "qwen-vl-ocr",
            "qwen3.5-omni-plus",
        ],
        "vision_models": [
            "qwen3.8-max",
            "qwen3.7-plus",
            "qwen3-vl-plus",
            "qwen3-vl-flash",
            "qwen-vl-max",
            "qwen-vl-plus",
            "qwen-vl-ocr",
            "qwen3.5-omni-plus",
        ],
        "desc": "阿里云百炼 · 千问文本 + VL 视觉系列（qwen3.8-flash 为最新轻量档）",
        "is_local": False,
    },
    "moonshot": {
        "label": "Moonshot / Kimi",
        "url": "https://api.moonshot.cn/v1/chat/completions",
        "default_model": "kimi-k3",
        "models": [
            "kimi-k3",
            "kimi-k2.7-code",
            "kimi-k2.7-code-highspeed",
            "kimi-k2.6",
            "kimi-k2.5",
        ],
        "vision_models": [
            "kimi-k3",
            "kimi-k2.6",
            "kimi-k2.5",
        ],
        "desc": "月之暗面 Kimi · kimi-k3 原生视觉、1M 上下文；moonshot-v1 系列已于 2026-08-31 下线",
        "is_local": False,
    },
    "openai": {
        "label": "OpenAI",
        "url": "https://api.openai.com/v1/chat/completions",
        "default_model": "gpt-5.6-terra",
        "models": [
            # 2026-09-03 发布 GPT-6 Astra（旗舰，价格较高）；5.6 三档为 Sol/Terra/Luna
            "gpt-6-astra",
            "gpt-5.6-sol",
            "gpt-5.6-terra",
            "gpt-5.6-luna",
            "gpt-5.5",
            "gpt-5.4",
            "gpt-5.4-mini",
            "gpt-5.4-nano",
        ],
        "vision_models": [
            "gpt-6-astra",
            "gpt-5.6-sol",
            "gpt-5.6-terra",
            "gpt-5.6-luna",
            "gpt-5.5",
            "gpt-5.4",
        ],
        "desc": "OpenAI 官方 · 5.6 起均支持视觉与 computer use；GPT-6 Astra 为最新旗舰（分批开放）",
        "is_local": False,
    },
    "grok": {
        "label": "Grok（xAI）",
        "url": "https://api.x.ai/v1/chat/completions",
        "default_model": "grok-4.6",
        "models": [
            "grok-4.6",
            "grok-4.5",
            "grok-4.3",
            "grok-4-fast",
            "grok-4-fast-reasoning",
            "grok-3",
            "grok-3-mini",
        ],
        "vision_models": ["grok-4.6", "grok-4.5"],
        "desc": "xAI Grok · grok-4.6 为当前旗舰（500K 上下文），支持图像输入",
        "is_local": False,
    },
    "gemini": {
        "label": "Gemini（Google）",
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "default_model": "gemini-3.8-flash",
        "models": [
            # 2026-09-02 发布 3.8 Flash（最新稳定档）
            "gemini-3.8-flash",
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-3-flash-preview",
            "gemini-2.5-pro",
            "gemini-2.5-flash",
        ],
        "vision_models": [
            "gemini-3.8-flash",
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-3-flash-preview",
            "gemini-2.5-pro",
            "gemini-2.5-flash",
        ],
        "desc": "Google Gemini · 官方 OpenAI 兼容层，主力型号均支持多模态（gemini-3-pro-preview 已于 2026-03-09 关停）",
        "is_local": False,
    },
    "openrouter": {
        "label": "OpenRouter",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "default_model": "deepseek/deepseek-v4-flash",
        "models": [
            # 2026-09 新上架（OpenRouter 榜单可查）
            "openai/gpt-6-astra",
            "google/gemini-3.8-flash",
            "z-ai/glm-5.3-flash",
            "z-ai/glm-5.3",
            "anthropic/claude-fable-5.1",
            "tencent/hy4-preview",
            "deepseek/deepseek-v4-flash",
            "deepseek/deepseek-v4-pro",
            "deepseek/deepseek-v4-flash-vision-exp",
            "openai/gpt-5.6-sol",
            "openai/gpt-5.4",
            "openai/gpt-5.4-mini",
            "anthropic/claude-opus-5",
            "anthropic/claude-fable-5",
            "google/gemini-3.7-flash",
            "google/gemini-3.5-flash",
            "moonshotai/kimi-k3",
            "x-ai/grok-4.6",
            "x-ai/grok-4.5",
        ],
        "vision_models": [
            "openai/gpt-6-astra",
            "google/gemini-3.8-flash",
            "z-ai/glm-5.3-flash",
            "deepseek/deepseek-v4-flash-vision-exp",
            "openai/gpt-5.6-sol",
            "openai/gpt-5.4",
            "anthropic/claude-opus-5",
            "anthropic/claude-fable-5",
            "anthropic/claude-fable-5.1",
            "google/gemini-3.7-flash",
            "google/gemini-3.5-flash",
            "x-ai/grok-4.6",
            "x-ai/grok-4.5",
        ],
        "desc": "聚合多厂商 · 一个 Key 多模型（前缀写法，如 openai/xxx、anthropic/xxx）",
        "is_local": False,
    },
    "ollama": {
        "label": "本地 Ollama",
        "url": "http://localhost:11434/v1/chat/completions",
        "default_model": "qwen3:8b",
        "models": [
            # 官方库 2026-09 热门/最新（体积小可跑优先在前）
            "qwen3.8:27b",
            "gpt-oss:20b",
            "glm-5.3",
            "deepseek-v4-pro",
            "gemma4:31b",
            "qwen3:8b",
            "qwen3.6:27b",
            "qwen3.5",
            "llama4:scout",
            "llama3.1:8b",
            "deepseek-r1:8b",
            "gemma4:12b",
            "mistral-small3.2",
            "phi4:14b",
            "llama3.2-vision:11b",
            "qwen3-vl",
            "llava:7b",
            "gemma3:12b",
        ],
        "vision_models": [
            "qwen3.8:27b",
            "gemma4:31b",
            "llama3.2-vision:11b",
            "qwen3-vl",
            "llava:7b",
            "gemma3:12b",
        ],
        "desc": "本机部署开源模型 · 无需 API Key（需先 ollama pull；qwen3.8 / gpt-oss / gemma4 等为最新档）",
        "is_local": True,
    },
    "doubao": {
        "label": "豆包（火山方舟）",
        "url": "https://ark.cn-volces.com/api/v3/chat/completions",
        "default_model": "doubao-seed-evolving",
        "models": [
            # 2026-09 官方文档：doubao-seed-evolving 为统一最新版 ID；2.1 系列用官方发布公告的带版本号 ID
            "doubao-seed-evolving",
            "doubao-seed-2-1-pro-260628",
            "doubao-seed-2-1-turbo-260628",
            "doubao-seed-2.0-pro",
            "doubao-seed-2.0-mini",
            "doubao-seed-2.0-lite",
            "doubao-seed-1.6",
            "doubao-seed-1.6-thinking",
            "doubao-1.5-pro-256k",
            "doubao-1.5-vision-pro",
            "doubao-1.5-thinking-vision-pro",
        ],
        "vision_models": [
            "doubao-seed-evolving",
            "doubao-seed-2-1-pro-260628",
            "doubao-seed-2.0-pro",
            "doubao-1.5-vision-pro",
            "doubao-1.5-thinking-vision-pro",
        ],
        "desc": "火山方舟 · 字节豆包；doubao-seed-evolving 为官方统一最新版 ID（model 也可填方舟接入点资源名）",
        "is_local": False,
    },
    "hunyuan": {
        "label": "腾讯混元",
        "url": "https://api.hunyuan.cloud.tencent.com/v1/chat/completions",
        "default_model": "hy3",
        "models": [
            # 2026-09-08 官方调用指南：hy4-preview 新一代预览（1024K），hy3 为稳定主力
            "hy4-preview",
            "hy3",
            "hunyuan-turbo-s",
            "hunyuan-lite",
            "hunyuan-t1",
            "hunyuan-vision",
        ],
        "vision_models": ["hunyuan-vision"],
        "desc": "腾讯混元 · OpenAI 兼容；hy3 为稳定主力，hy4-preview 为新一代预览（1024K 上下文）",
        "is_local": False,
    },
    "custom": {
        "label": "自定义（手动填写）",
        "url": "",
        "default_model": "",
        "models": [],
        "vision_models": [],
        "desc": "任意 OpenAI 兼容端点手动配置",
        "is_local": False,
    },
}

DEFAULT_API_PROVIDER = "deepseek"


def normalize_provider(name: Any) -> str:
    """归一化厂商名：空值或未知厂商一律回退 deepseek（旧配置向后兼容，不报错）。"""
    text = str(name or "").strip().lower()
    if text in API_PROVIDER_PRESETS:
        return text
    return DEFAULT_API_PROVIDER


def provider_label_short(provider_key: Any) -> str:
    """返回厂商展示短名（去掉「（默认）」/括号注释），供侧栏/按钮等紧凑位使用。"""
    key = normalize_provider(provider_key)
    label = API_PROVIDER_PRESETS.get(key, {}).get("label", "") or key
    for ch in ("（", "(", " /", "·"):
        label = label.split(ch)[0].strip()
    return label.strip() or key


def mask_api_key(key: Any) -> str:
    """脱敏 API Key：`sk-****` + 末 4 位；空 Key → 「未配置」。

    规则（design D8）：保留 `sk-` 前缀以提示厂商前缀，中段全部打码，只露末 4 位。
    非 `sk-` 前缀的 Key（如 OpenAI 兼容）同样只露末 4 位；密钥体 ≤4 位时不外露真尾。
    纯函数，GUI/CLI 共用。
    """
    text = str(key or "").strip()
    if not text:
        return "未配置"
    prefix = ""
    rest = text
    if text.lower().startswith("sk-"):
        prefix = "sk-"
        rest = text[len("sk-"):]
    if not rest:
        return "****"
    if len(rest) <= 4:
        return prefix + "****" if prefix else "****"
    return f"{prefix}****{rest[-4:]}"


def api_status_summary(cfg: Any, last_error: Any = None) -> Dict[str, Any]:
    """汇总当前模型接口状态（B9/D8 状态头 / 侧栏状态按钮共用）。

    参数 cfg 为 AppConfig（或任何带 api_provider/api_key/api_model 属性的对象），
    last_error 为可选的最近一次调用错误（None 表示未知/未测）。
    返回：
      provider_key / provider_label / provider_short  厂商标识与展示名
      is_local            本地运行（无需 Key，如 ollama）
      model               当前生效模型
      url                 当前 Base URL
      has_key / masked_key Key 是否存在及其脱敏展示
      configured          「可用的配置已就绪」= 有 Key 或本地
      ok                  绿色态 = configured 且无 last_error
      state_text          一句话状态（已配置 / 未配置 Key / 本地运行 / 连接异常）
      hint                缺 Key 时的高亮引导文案（其余为空）
    """
    provider = normalize_provider(getattr(cfg, "api_provider", DEFAULT_API_PROVIDER)
                                  if cfg is not None else DEFAULT_API_PROVIDER)
    preset = API_PROVIDER_PRESETS.get(provider, API_PROVIDER_PRESETS[DEFAULT_API_PROVIDER])
    api_key = str(getattr(cfg, "api_key", "") or "").strip() if cfg is not None else ""
    is_local = bool(preset.get("is_local", False))
    has_key = bool(api_key)
    model = str(getattr(cfg, "api_model", "") or "").strip() if cfg is not None else ""
    url = str(getattr(cfg, "api_url", "") or "").strip() if cfg is not None else ""
    configured = bool(has_key or is_local)
    has_error = bool(last_error)

    if is_local:
        state_text = "本地运行"
        hint = ""
    elif has_error:
        state_text = "连接异常"
        hint = ""
    elif has_key:
        state_text = "已配置"
        hint = ""
    else:
        state_text = "未配置 Key"
        hint = "请选择下方厂商并填写 API Key（本地 Ollama 可留空）"

    return {
        "provider_key": provider,
        "provider_label": str(preset.get("label", provider)),
        "provider_short": provider_label_short(provider),
        "is_local": is_local,
        "model": model,
        "url": url,
        "has_key": has_key,
        "masked_key": mask_api_key(api_key),
        "configured": configured,
        "ok": bool(configured and not has_error),
        "state_text": state_text,
        "hint": hint,
        "error": str(last_error) if has_error else "",
    }


# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------
def _load_yaml(path: Path) -> dict:
    if _HAS_YAML:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


# v10.15: 字段 → (yaml 段落, 子键) 映射，与 AppConfig.save() 写出的结构一一对应，
# 是 load() 读取 config.yaml 的唯一依据（旧的环境变量名拆段推导已废弃）。
_YAML_FIELD_MAP: Dict[str, Tuple[str, str]] = {
    "api_provider": ("api", "provider"),
    "api_key": ("api", "key"),
    "api_url": ("api", "url"),
    "api_model": ("api", "model"),
    "api_max_tokens": ("api", "max_tokens"),
    "api_temperature": ("api", "temperature"),
    "api_retry_times": ("api", "retry_times"),
    "max_history_rounds": ("session", "max_history_rounds"),
    "summary_interval": ("session", "summary_interval"),
    "auto_save": ("session", "auto_save"),
    "workspace": ("session", "workspace"),
    # v1.9(C/D-V19-01): persona 段落 yaml —— 自称/名字规则读时生效
    "persona_address_self": ("persona", "address_self"),
    "persona_given_name": ("persona", "given_name"),
    "output_speed": ("output", "speed"),
    "output_colors": ("output", "colors"),
    "output_debug": ("output", "debug"),
    "output_show_token_usage": ("output", "show_token_usage"),
    "stream_mode": ("output", "stream_mode"),
    "multi_enabled": ("multi_model", "enabled"),
    "multi_parallel_gen_review": ("multi_model", "parallel_gen_review"),
    "multi_judge_threshold": ("multi_model", "judge_threshold"),
    "web_search_enabled": ("web_search", "enabled"),
    "web_search_max_results": ("web_search", "max_results"),
    "code_exec_enabled": ("code", "exec_enabled"),
    "code_exec_timeout": ("code", "exec_timeout"),
    "command_safety_mode": ("safety", "command_safety_mode"),
    # v1.1(agent): Agent 模式配置段
    "agent_enabled": ("agent", "enabled"),
    "agent_max_steps": ("agent", "max_steps"),
    # v1.2(C1): run_command 单条命令超时（秒）；命令白名单为 D3 定稿常量集，不开放配置
    "agent_command_timeout": ("agent", "command_timeout"),
    # v1.2(C2): 步骤失败后 C2 内层自愈最大重试轮数
    "agent_max_retries": ("agent", "max_retries"),
    # v1.6(P0-4/D-V16-08): 反套话注入总开关（降级阀；config.yaml agent 段，不进 UI）
    "agent_anti_hallucination_inject": ("agent", "anti_hallucination_inject"),
    # v1.2(A9): 主动陪伴配置段（yaml 三级子路径，sub 用 "." 分隔逐层查找）
    "agent_proactive_enabled": ("agent", "proactive.enabled"),
    "agent_proactive_quiet_start": ("agent", "proactive.quiet.start"),
    "agent_proactive_quiet_end": ("agent", "proactive.quiet.end"),
    "agent_proactive_daily_cap": ("agent", "proactive.daily_cap"),
    "agent_proactive_idle_minutes": ("agent", "proactive.idle_minutes"),
    "agent_proactive_cooldown_minutes": ("agent", "proactive.cooldown_minutes"),
    "agent_proactive_llm_enhance": ("agent", "proactive.llm_enhance"),
    # v1.3(P1-4): Idle 问候 —— 系统全局空闲 crossing 问候（并入 proactive gates）
    "agent_proactive_idle_return_enabled": ("agent", "proactive.idle_return_enabled"),
    "agent_proactive_system_idle_minutes": ("agent", "proactive.system_idle_minutes"),
}


@dataclass
class AppConfig:
    """运行时配置，优先顺序：环境变量 > config.yaml > 代码默认值。"""

    # API
    api_provider: str = "deepseek"  # deepseek / moonshot / qwen / zhipu / openai / openrouter / ollama / custom
    api_key: str = ""
    api_keys: List[str] = field(default_factory=list)
    api_url: str = "https://api.deepseek.com/chat/completions"
    api_model: str = "deepseek-flash"  # 与 API_PROVIDER_PRESETS["deepseek"]["default_model"] 同步（V4.1-Flash）
    api_max_tokens: int = 4096
    api_temperature: float = 0.7
    api_retry_times: int = 3

    # Session
    max_history_rounds: int = 8
    summary_interval: int = 5
    auto_save: bool = True
    workspace: str = "."

    # Persona
    persona_role: str = "女仆"
    persona_title: str = "资深全栈开发工程师"
    persona_personality: str = "娇羞、温顺、细腻，技术问题上专业且自信"
    persona_address_user: str = "主人"
    # v1.9(C/D-V19-01): address_self 降级为遗留兼容字段（默认空 = 走 given_name 规则）；
    # 新增独立「名字」字段：空 = 无名字 → 自称"我"。
    persona_address_self: str = ""
    persona_given_name: str = ""

    # Output
    output_speed: str = "normal"
    output_colors: bool = True
    output_debug: bool = False
    output_show_token_usage: bool = True
    stream_mode: bool = False

    # Multi-model
    multi_enabled: bool = False
    multi_parallel_gen_review: bool = True
    multi_judge_threshold: float = 0.7

    # Tools
    tools_harness_path: str = "dsh.cmd"
    tools_harness_timeout: int = 120

    # Safety
    command_safety_mode: str = "blacklist"  # blacklist / whitelist / off

    # Agent (v1.1: Agent 模式开关与步数上限；GUI 设置页读写并持久化)
    agent_enabled: bool = False
    agent_max_steps: int = 8
    # v1.6(P0-4/D-V16-08): 反套话注入总开关（默认 True 一键关）
    agent_anti_hallucination_inject: bool = True

    # Agent 主动陪伴（v1.2 A9：有节制主动陪伴；PRD §4.1 A9 / design §3.10）
    # 配置落 yaml `agent.proactive` 子段；运行态计数存 companion.json.proactive（GUI config 不存）
    agent_proactive_enabled: bool = True          # 总开关
    agent_proactive_quiet_start: str = "22:30"    # 免打扰开始 HH:MM（跨天）
    agent_proactive_quiet_end: str = "08:00"      # 免打扰结束 HH:MM
    agent_proactive_daily_cap: int = 3            # 单日主动条数上限
    agent_proactive_idle_minutes: int = 90        # 长空闲阈值（分钟）
    agent_proactive_cooldown_minutes: int = 60    # 相邻两次主动最小间隔（分钟）
    agent_proactive_llm_enhance: bool = False     # LLM 增强文案（默认关，模板先行）
    # v1.3(P1-4): Idle 问候（系统全局空闲恢复时一句迎接；与 A9 共享 cooldown/cap）
    agent_proactive_idle_return_enabled: bool = True   # Idle 问候总开关（默认 true）
    agent_proactive_system_idle_minutes: int = 30     # 系统全局空闲阈值（分钟，默认 30）
    # v1.2(C1): run_command 单条命令超时（秒，默认 30s），超时即 kill 进程树
    agent_command_timeout: int = 30
    # v1.2(C2): 步骤失败后 C2 内层自愈（heal）最大轮数（默认 3），超限即 failed+上报卡点
    agent_max_retries: int = 3

    # Web search
    web_search_enabled: bool = True
    web_search_max_results: int = 5

    # Files
    snippets_file: str = "snippets.json"
    todos_file: str = "todos.json"
    kb_index_file: str = "kb_index.json"
    plugins_dir: str = "plugins"

    # Code execution
    code_exec_timeout: int = 5
    code_exec_enabled: bool = False

    # Clipboard
    clipboard_check: bool = False

    # Sensitive info
    sensitive_info_scan: bool = True

    # Stats
    stats_enabled: bool = True

    @classmethod
    def load(cls, yaml_path: Optional[Path] = None) -> "AppConfig":
        defaults = cls()
        cfg: dict = {}
        if yaml_path and yaml_path.exists():
            cfg = _load_yaml(yaml_path)

        env = {k: v for k, v in os.environ.items() if k.startswith(("MAID_", "DEEPSEEK_"))}

        def _env(key: str, default: Any, field: Optional[str] = None) -> Any:
            # 优先级 1：显式环境变量（MAID_* / DEEPSEEK_*）
            if key in env:
                v = env[key]
                if isinstance(default, bool):
                    return v.lower() in ("1", "true", "yes", "on")
                if isinstance(default, int):
                    return int(v)
                if isinstance(default, float):
                    return float(v)
                return v
            # 优先级 2（v10.15 修复）：按 save() 实际写出的 yaml 段落结构直读。
            # 旧实现按「环境变量名拆段」推导 yaml 位置，与 save() 写出的
            # multi_model / web_search / safety / session 段落全部对不上，
            # 导致这些字段保存后永远读不回（round-trip 失效）。
            f = field or key
            entry = _YAML_FIELD_MAP.get(f)
            if entry is not None:
                section, path = entry
                sec = cfg.get(section) if isinstance(cfg, dict) else None
                # v1.2(A9): 支持 "proactive.quiet.start" 三级子路径逐层查找
                v = None
                for part in path.split("."):
                    if isinstance(sec, dict) and part in sec:
                        sec = sec[part]
                        v = sec
                    else:
                        v = None
                        break
                if v is not None:
                    if isinstance(default, bool) and isinstance(v, str):
                        return v.lower() in ("1", "true", "yes", "on")
                    if isinstance(default, int) and isinstance(v, str):
                        try:
                            return int(v)
                        except ValueError:
                            return default
                    if isinstance(default, float) and isinstance(v, str):
                        try:
                            return float(v)
                        except ValueError:
                            return default
                    return v
            return default

        # 读取多 key 配置
        _api_keys = defaults.api_keys
        if "api" in cfg and "keys" in cfg["api"]:
            _api_keys = cfg["api"]["keys"]
        if not _api_keys and defaults.api_key:
            _api_keys = [defaults.api_key]

        return cls(
            api_provider=normalize_provider(_env("MAID_API_PROVIDER", defaults.api_provider, "api_provider")),
            api_key=_env("DEEPSEEK_API_KEY", defaults.api_key, "api_key"),
            api_keys=_api_keys,
            api_url=_env("MAID_API_URL", defaults.api_url, "api_url"),
            api_model=_env("MAID_API_MODEL", defaults.api_model, "api_model"),
            api_max_tokens=_env("MAID_API_MAX_TOKENS", defaults.api_max_tokens, "api_max_tokens"),
            api_temperature=_env("MAID_API_TEMPERATURE", defaults.api_temperature, "api_temperature"),
            api_retry_times=_env("MAID_API_RETRY_TIMES", defaults.api_retry_times, "api_retry_times"),
            max_history_rounds=_env("MAID_MAX_HISTORY_ROUNDS", defaults.max_history_rounds, "max_history_rounds"),
            summary_interval=_env("MAID_SUMMARY_INTERVAL", defaults.summary_interval, "summary_interval"),
            auto_save=_env("MAID_AUTO_SAVE", defaults.auto_save, "auto_save"),
            workspace=_env("MAID_WORKSPACE", defaults.workspace, "workspace"),
            persona_role=_env("MAID_PERSONA_ROLE", defaults.persona_role, "persona_role"),
            persona_title=_env("MAID_PERSONA_TITLE", defaults.persona_title, "persona_title"),
            persona_personality=_env("MAID_PERSONA_PERSONALITY", defaults.persona_personality, "persona_personality"),
            persona_address_user=_env("MAID_PERSONA_ADDRESS_USER", defaults.persona_address_user, "persona_address_user"),
            persona_address_self=_env("MAID_PERSONA_ADDRESS_SELF", defaults.persona_address_self, "persona_address_self"),
            persona_given_name=_env("MAID_PERSONA_GIVEN_NAME", defaults.persona_given_name, "persona_given_name"),
            output_speed=_env("MAID_OUTPUT_SPEED", defaults.output_speed, "output_speed"),
            output_colors=_env("MAID_OUTPUT_COLORS", defaults.output_colors, "output_colors"),
            output_debug=_env("MAID_OUTPUT_DEBUG", defaults.output_debug, "output_debug"),
            output_show_token_usage=_env("MAID_OUTPUT_SHOW_TOKEN_USAGE", defaults.output_show_token_usage, "output_show_token_usage"),
            stream_mode=_env("MAID_STREAM_MODE", defaults.stream_mode, "stream_mode"),
            multi_enabled=_env("MAID_MULTI_ENABLED", defaults.multi_enabled, "multi_enabled"),
            multi_parallel_gen_review=_env("MAID_MULTI_PARALLEL_GEN_REVIEW", defaults.multi_parallel_gen_review, "multi_parallel_gen_review"),
            multi_judge_threshold=_env("MAID_MULTI_JUDGE_THRESHOLD", defaults.multi_judge_threshold, "multi_judge_threshold"),
            tools_harness_path=_env("MAID_TOOLS_HARNESS_PATH", defaults.tools_harness_path, "tools_harness_path"),
            tools_harness_timeout=_env("MAID_TOOLS_HARNESS_TIMEOUT", defaults.tools_harness_timeout, "tools_harness_timeout"),
            command_safety_mode=_env("MAID_COMMAND_SAFETY_MODE", defaults.command_safety_mode, "command_safety_mode"),
            agent_enabled=_env("MAID_AGENT_ENABLED", defaults.agent_enabled, "agent_enabled"),
            agent_max_steps=_env("MAID_AGENT_MAX_STEPS", defaults.agent_max_steps, "agent_max_steps"),
            agent_command_timeout=_env("MAID_AGENT_COMMAND_TIMEOUT", defaults.agent_command_timeout, "agent_command_timeout"),
            agent_max_retries=_env("MAID_AGENT_MAX_RETRIES", defaults.agent_max_retries, "agent_max_retries"),
            agent_anti_hallucination_inject=_env("MAID_AGENT_ANTI_HALLUCINATION_INJECT", defaults.agent_anti_hallucination_inject, "agent_anti_hallucination_inject"),
            agent_proactive_enabled=_env("MAID_AGENT_PROACTIVE_ENABLED", defaults.agent_proactive_enabled, "agent_proactive_enabled"),
            agent_proactive_quiet_start=_env("MAID_AGENT_PROACTIVE_QUIET_START", defaults.agent_proactive_quiet_start, "agent_proactive_quiet_start"),
            agent_proactive_quiet_end=_env("MAID_AGENT_PROACTIVE_QUIET_END", defaults.agent_proactive_quiet_end, "agent_proactive_quiet_end"),
            agent_proactive_daily_cap=_env("MAID_AGENT_PROACTIVE_DAILY_CAP", defaults.agent_proactive_daily_cap, "agent_proactive_daily_cap"),
            agent_proactive_idle_minutes=_env("MAID_AGENT_PROACTIVE_IDLE_MINUTES", defaults.agent_proactive_idle_minutes, "agent_proactive_idle_minutes"),
            agent_proactive_cooldown_minutes=_env("MAID_AGENT_PROACTIVE_COOLDOWN_MINUTES", defaults.agent_proactive_cooldown_minutes, "agent_proactive_cooldown_minutes"),
            agent_proactive_llm_enhance=_env("MAID_AGENT_PROACTIVE_LLM_ENHANCE", defaults.agent_proactive_llm_enhance, "agent_proactive_llm_enhance"),
            agent_proactive_idle_return_enabled=_env("MAID_AGENT_PROACTIVE_IDLE_RETURN_ENABLED", defaults.agent_proactive_idle_return_enabled, "agent_proactive_idle_return_enabled"),
            agent_proactive_system_idle_minutes=_env("MAID_AGENT_PROACTIVE_SYSTEM_IDLE_MINUTES", defaults.agent_proactive_system_idle_minutes, "agent_proactive_system_idle_minutes"),
            web_search_enabled=_env("MAID_WEB_SEARCH_ENABLED", defaults.web_search_enabled, "web_search_enabled"),
            web_search_max_results=_env("MAID_WEB_SEARCH_MAX_RESULTS", defaults.web_search_max_results, "web_search_max_results"),
            snippets_file=_env("MAID_SNIPPETS_FILE", defaults.snippets_file, "snippets_file"),
            todos_file=_env("MAID_TODOS_FILE", defaults.todos_file, "todos_file"),
            kb_index_file=_env("MAID_KB_INDEX_FILE", defaults.kb_index_file, "kb_index_file"),
            plugins_dir=_env("MAID_PLUGINS_DIR", defaults.plugins_dir, "plugins_dir"),
            code_exec_timeout=_env("MAID_CODE_EXEC_TIMEOUT", defaults.code_exec_timeout, "code_exec_timeout"),
            code_exec_enabled=_env("MAID_CODE_EXEC_ENABLED", defaults.code_exec_enabled, "code_exec_enabled"),
            clipboard_check=_env("MAID_CLIPBOARD_CHECK", defaults.clipboard_check, "clipboard_check"),
            sensitive_info_scan=_env("MAID_SENSITIVE_INFO_SCAN", defaults.sensitive_info_scan, "sensitive_info_scan"),
            stats_enabled=_env("MAID_STATS_ENABLED", defaults.stats_enabled, "stats_enabled"),
        )._loaded_from(yaml_path)

    def _loaded_from(self, yaml_path: Optional[Path]) -> "AppConfig":
        """记录加载来源，供 save() 默认回写同一路径（v10.8）。"""
        self._yaml_path = Path(yaml_path) if yaml_path else None
        return self

    def validate(self) -> List[str]:
        """v1.4.8: 配置校验，返回警告列表（空列表=全部通过）。

        只检查关键配置项的合理性，不抛异常。
        """
        warnings = []
        # API Key 检查
        if not self.api_key and not self.api_keys:
            warnings.append("API Key 未设置，Agent 功能将无法使用")
        # API URL 检查
        if not self.api_url:
            warnings.append("API URL 未设置")
        elif not self.api_url.startswith(("http://", "https://")):
            warnings.append(f"API URL 格式可能不正确: {self.api_url}")
        # 数值范围检查
        if self.api_max_tokens < 1:
            warnings.append(f"api_max_tokens 应 > 0，当前: {self.api_max_tokens}")
        if not (0 <= self.api_temperature <= 2):
            warnings.append(f"api_temperature 应在 0-2 之间，当前: {self.api_temperature}")
        if self.api_retry_times < 0:
            warnings.append(f"api_retry_times 应 >= 0，当前: {self.api_retry_times}")
        # Agent 配置检查
        if self.agent_max_steps < 1:
            warnings.append(f"agent_max_steps 应 >= 1，当前: {self.agent_max_steps}")
        # workspace 检查
        ws = Path(self.workspace)
        if not ws.exists():
            warnings.append(f"workspace 目录不存在: {self.workspace}")
        return warnings

    def get_summary(self) -> Dict[str, Any]:
        """v1.4.8: 返回配置摘要（用于日志/调试）。"""
        return {
            "provider": self.api_provider,
            "model": self.api_model,
            "workspace": self.workspace,
            "agent_enabled": self.agent_enabled,
            "stream_mode": self.stream_mode,
            "max_steps": self.agent_max_steps,
        }

    def save(self, yaml_path: Optional[Path] = None) -> bool:
        """把当前配置写回 config.yaml（v10.8 新增，GUI 设置页持久化用）。

        只更新已知字段的值，保留文件中已有的其他段落与注释之外的键。
        写入失败（如未安装 PyYAML）返回 False，不抛异常。
        """
        if not _HAS_YAML:
            return False
        # v10.8: 未显式指定路径时，默认回写加载时的 config.yaml，
        # 避免从其他工作目录启动时写错位置
        default_path = getattr(self, "_yaml_path", None) or Path("config.yaml")
        path = Path(yaml_path) if yaml_path else default_path
        try:
            data: dict = {}
            if path.exists():
                data = _load_yaml(path)
            if not isinstance(data, dict):
                data = {}

            def _sec(name: str) -> dict:
                section = data.get(name)
                if not isinstance(section, dict):
                    section = {}
                    data[name] = section
                return section

            _sec("api").update({
                "provider": self.api_provider,
                "key": self.api_key,
                "url": self.api_url,
                "model": self.api_model,
                "max_tokens": self.api_max_tokens,
                "temperature": self.api_temperature,
                "retry_times": self.api_retry_times,
            })
            _sec("session").update({
                "max_history_rounds": self.max_history_rounds,
                "summary_interval": self.summary_interval,
                "auto_save": self.auto_save,
                "workspace": self.workspace,
            })
            _sec("output").update({
                "speed": self.output_speed,
                "colors": self.output_colors,
                "debug": self.output_debug,
                "show_token_usage": self.output_show_token_usage,
                "stream_mode": self.stream_mode,
            })
            _sec("multi_model").update({
                "enabled": self.multi_enabled,
                "parallel_gen_review": self.multi_parallel_gen_review,
                "judge_threshold": self.multi_judge_threshold,
            })
            _sec("web_search").update({
                "enabled": self.web_search_enabled,
                "max_results": self.web_search_max_results,
            })
            _sec("code").update({
                "exec_enabled": self.code_exec_enabled,
                "exec_timeout": self.code_exec_timeout,
            })
            _sec("safety").update({
                "command_safety_mode": self.command_safety_mode,
            })
            _sec("agent").update({
                "enabled": self.agent_enabled,
                "max_steps": self.agent_max_steps,
                "command_timeout": self.agent_command_timeout,
                "max_retries": self.agent_max_retries,
            })
            # v1.2(A9): 主动陪伴三段（agent.proactive.{enabled,quiet,daily_cap,...}）
            _ap = _sec("agent").get("proactive")
            if not isinstance(_ap, dict):
                _ap = {}
                _sec("agent")["proactive"] = _ap
            _ap.update({
                "enabled": self.agent_proactive_enabled,
                "daily_cap": self.agent_proactive_daily_cap,
                "idle_minutes": self.agent_proactive_idle_minutes,
                "cooldown_minutes": self.agent_proactive_cooldown_minutes,
                "llm_enhance": self.agent_proactive_llm_enhance,
                # v1.3(P1-4): Idle 问候新键
                "idle_return_enabled": self.agent_proactive_idle_return_enabled,
                "system_idle_minutes": self.agent_proactive_system_idle_minutes,
            })
            _aq = _ap.get("quiet")
            if not isinstance(_aq, dict):
                _aq = {}
                _ap["quiet"] = _aq
            _aq.update({
                "start": self.agent_proactive_quiet_start,
                "end": self.agent_proactive_quiet_end,
            })
            with open(path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            return True
        except Exception:
            return False


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
def _setup_logging(debug: bool) -> logging.Logger:
    logger = logging.getLogger("maid_coder")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    if not logger.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setLevel(logging.DEBUG if debug else logging.INFO)
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
        h.setFormatter(fmt)
        logger.addHandler(h)
    return logger


# ---------------------------------------------------------------------------
# 带重试的 API 客户端
# ---------------------------------------------------------------------------
def print_typed(text: str, speed: str, prefix: str = "") -> None:
    if prefix:
        print(prefix, end="", flush=True)
    if speed == "fast":
        print(text)
        return
    if speed == "slow":
        for ch in text:
            print(ch, end="", flush=True)
            time.sleep(0.015)
        print()
        return
    chunk_size = 30
    for i in range(0, len(text), chunk_size):
        chunk = text[i : i + chunk_size]
        print(chunk, end="", flush=True)
        time.sleep(0.03)
    print()


# ---------------------------------------------------------------------------
