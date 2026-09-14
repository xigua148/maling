# 码铃 MaLing API 参考

> v1.4.8 — 核心模块接口文档

## 模块结构

```
maling_agent_dev/
├── api.py              # API 客户端（HTTP 请求、Key 轮换、流式响应）
├── agent_engine.py     # Agent 引擎（工具循环、流式推送、事件系统）
├── agent_tools.py      # 工具注册表（31 个工具、L0/L1 授权）
├── core/__init__.py    # 配置管理、安全常量、预设
├── version.py          # 版本号单源管理
├── memory.py           # 用户偏好记忆
├── utils.py            # 工具函数（格式化、原子写入、平台兼容）
├── command_runner.py   # 命令执行器（白名单、安全判定）
├── gui/
│   ├── chat_service.py # 聊天服务（消息收发、线程管理）
│   └── widgets/
│       ├── chat_panel.py  # 聊天面板（主容器）
│       └── tool_trace.py  # 工具轨迹面板
└── tests/              # 单元测试（90+ 项）
```

---

## api.py

### APIKeyRotator
多 Key 轮换管理器。

```python
from api import APIKeyRotator

rotator = APIKeyRotator(["sk-key1", "sk-key2"])
rotator.current_key       # "sk-key1"
rotator.rotate()          # 切到下一个
rotator.mark_failed(key)  # 标记失败，跳过
```

### APIClient
HTTP API 客户端。

```python
from api import APIClient

client = APIClient(cfg, logger)

# 非流式
response = client.chat(messages, tools=schemas)

# 流式（兼容旧接口）
content, tool_calls, usage = client.chat_stream(messages, tools=schemas)

# 流式 + 工具（v1.4.7+ 推荐）
gen = client.chat_stream_with_tools(messages, tools=schemas)
for delta in gen:
    print(delta, end="")  # content 逐块输出
# 生成结束后：
tool_calls = client._last_stream_tool_calls
usage = client._last_stream_usage
```

---

## agent_engine.py

### AgentEngine
Agent 工具循环引擎。

```python
from agent_engine import AgentEngine
from agent_tools import AgentTools
from api import APIClient

api = APIClient(cfg, logger)
tools = AgentTools(cfg, logger, confirm_fn=gui_confirm)

engine = AgentEngine(
    api, cfg, logger,
    tools=tools,
    max_steps=8,
    on_content_chunk=lambda chunk: print(chunk, end=""),  # 流式回调
    on_event=lambda event, data: handle(event, data),     # 事件回调
    cancel_check=lambda: user_cancelled,                   # 取消检查
)

result = engine.run(system_prompt, history, user_input)
```

**事件类型：**
- `tool_call` — 模型请求调用工具
- `tool_done` — 工具执行完成
- `final` — 最终回答
- `step` — 步骤计数

---

## agent_tools.py

### AgentTools
工具注册表。

```python
from agent_tools import AgentTools

tools = AgentTools(cfg, logger, confirm_fn=confirm_dialog)

# 获取 OpenAI tools 参数
schemas = tools.schemas()  # List[dict]

# 按名执行
result = tools.execute("read_file", {"path": "main.py"})
# → '{"status": "ok", "message": "..."}'

# 授权判断
tools.authorize("write_file", {"path": "/etc/passwd"}, "写入系统文件")
# → False（workspace 外，需用户确认）
```

**工具分级：**
- `L0`：只读，自动放行
- `L1`：修改，需授权（workspace 内自动放行，外走 confirm_fn）

---

## core/__init__.py

### AppConfig
运行时配置。

```python
from core import AppConfig

cfg = AppConfig.load(Path("config.yaml"))

# 配置校验（v1.4.8+）
warnings = cfg.validate()  # List[str]，空=通过

# 配置摘要
summary = cfg.get_summary()
# → {"provider": "deepseek", "model": "deepseek-v4-flash", ...}
```

### 安全常量
```python
from core import SAFE_COMMAND_WHITELIST, FORBIDDEN_COMMANDS

# SAFE_COMMAND_WHITELIST: 快速预检白名单（python/python3 等）
# FORBIDDEN_COMMANDS: command_runner 禁止列表
```

---

## version.py

版本号单源管理（从 version.json 读取）。

```python
from version import get_version, get_app_title, is_at_least

get_version()       # "1.4.8"
get_app_title()     # "码铃 MaLing v1.4.8"
is_at_least(1, 4)   # True
```

---

## 错误处理约定

所有工具返回 JSON 字符串，统一结构：

```json
// 成功
{"status": "ok", "message": "...", ...}

// 错误
{"status": "error", "message": "错误描述"}

// 拒绝（未授权）
{"status": "denied", "message": "用户未授权"}
```

Agent 引擎根据 `status` 字段判断是否继续循环。
