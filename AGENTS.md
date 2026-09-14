# 码铃 MaLing — Agent 开发规则

> 本文件是 Agent 的工作约束。每次任务开始前必须阅读，违反红线的操作一律拒绝。

---

## 1. 架构分层（L0-L2）

| 层级 | 职责 | 代表文件 | 约束 |
|------|------|----------|------|
| **L0 核心** | API 通信、配置加载、安全策略、常量定义 | `core/__init__.py`, `api.py`, `security.py` | 禁止 import GUI 或 CLI 业务模块 |
| **L1 业务** | 会话管理、工具注册、Agent 引擎、命令系统 | `session.py`, `agent_engine.py`, `agent_tools.py`, `commands/` | 可 import L0，禁止 import `gui/` |
| **L2 界面** | PySide6 GUI、信号/槽、UI 渲染 | `gui/` | 可 import L0+L1，禁止反向依赖 |

**规则：import 方向只能从 L2 → L1 → L0，禁止反向或跨层循环依赖。**

---

## 2. 安全红线

### 2.1 授权函数默认必须拒绝（fail-safe）
- `authorize()` / `confirm_fn` 未配置时**一律拒绝**，绝不默认放行。
- 白名单目录内才放行写操作，无确认渠道时宁可拒绝。
- **历史教训**：初版 `authorize()` 默认放行，导致真实写入 `C:\Windows\system32` 测试文件。

### 2.2 命令安全判定
- 安全策略的单一权威来源是 `command_runner.py` 的 `ALLOWED_COMMANDS` + `FORBIDDEN_COMMANDS`。
- `core/__init__.py` 的 `SAFE_COMMAND_WHITELIST` 仅用于快速预检，不得与 `command_runner.py` 矛盾。
- 修改安全列表必须同步更新两处。

### 2.3 敏感信息
- API Key、密码、Token、私钥等不得硬编码、不得日志输出、不得写入会话历史。
- `config.yaml` 含个人密钥，已被 `.gitignore` 排除，禁止提交。

### 2.4 瞬时状态不可持久化
- UI 瞬时状态（窗口位置、侧栏展开/收起、临时选中项）**不得**写入配置文件或会话数据。
- 只有用户明确保存的数据才进入持久化通道。

---

## 3. 女仆语气规则

- 女仆语气**只作用于最终回答**（给用户的文本），工具执行过程文案走中性日志。
- `inject_maid_tone()` 不得在 Agent 工具执行循环中逐条注入，避免污染上下文。
- 全 UI 不展示心情/好感数值（关系只靠陪伴，无焦虑红线）。

---

## 4. 工具系统约定

### 4.1 工具分级
| 级别 | 说明 | 示例 | 授权要求 |
|------|------|------|----------|
| **L0 只读** | 不修改任何状态 | `read_file`, `git_status`, `git_log`, `web_search` | 无需授权 |
| **L1 修改** | 修改文件/执行命令 | `write_file`, `edit_file`, `run_python`, `git_commit` | 需会话级授权 |

### 4.2 工具执行约束
- `run_python` 走 AST 白名单沙箱（`CodeSandbox._check_ast_safe`），禁止 `os.system`/`subprocess`/`__import__` 等。
- `max_steps` 上限防止死循环，超限给兜底回答。
- 工具结果截断（`read_file` 3000 字符限制），防止上下文爆炸。

---

## 5. 构建与发布

- 构建命名规范：`dist_v{XYZ}f/`（XYZ 为版本号数字拼接，f = onedir 多文件模式）。
- 单文件模式：`dist_v{XYZ}of/`。
- 版本号三处同步：`version.json` 的 `version` 字段 + `downloads` URL + 构建目录名。
- 发布前清理旧产物，避免 8GB+ 堆积。

---

## 6. 禁止操作

- 禁止在代码中使用 `exec()` / `eval()` 执行不可信输入（沙箱例外：`CodeSandbox` 已做 AST 白名单过滤）。
- 禁止在非沙箱环境直接执行用户提交的代码。
- 禁止将 `pip`/`npm`/`docker` 等包管理命令列入安全白名单（需人工确认）。
- 禁止在非 Windows 平台使用 `msvcrt`，禁止在 Windows 平台使用 `fcntl`/`resource`（需平台检测）。
