# 贡献指南

> 码铃 MaLing 项目开发规范

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt -r requirements_gui.txt

# 2. 运行测试
python -m pytest tests/ -v

# 3. 启动应用
python run.py
```

## 项目结构

```
maling_agent_dev/
├── core/               # 配置、安全、预设
├── gui/                # PySide6 GUI
│   └── widgets/        # 可复用组件
├── commands/           # 斜杠命令
├── tests/              # 单元测试
├── docs/               # 文档
├── agent_tools.py      # Agent 工具注册表
├── agent_engine.py     # Agent 引擎
├── api.py              # API 客户端
└── version.py          # 版本号单源
```

## 开发规范

### 代码风格
- 使用 UTF-8 编码
- 4 空格缩进
- 函数/方法不超过 50 行
- 单文件不超过 500 行（chat_panel.py 例外，待拆分）

### 提交规范
```
feat: 新功能
fix: 修复 bug
test: 添加测试
docs: 文档更新
refactor: 重构（不改变功能）
chore: 构建/工具变更
```

### 测试要求
- 新功能必须附带单元测试
- 修改现有功能需确保原有测试通过
- 工具新增需在 `tests/test_agent_tools.py` 添加测试

### 工具开发
新增 Agent 工具需遵循：

1. 在 `agent_tools.py` 的 `_register_builtin_tools()` 注册
2. 实现 handler（返回 JSON 字符串）
3. 确定安全级别（L0 只读 / L1 修改）
4. 在 `tests/test_agent_tools.py` 添加测试
5. 在 `docs/TOOLS.md` 更新文档

### 安全规则
- **fail-safe**：不确定时拒绝
- L0 工具不弹授权框
- L1 工具在 workspace 外必须走 `confirm_fn`
- 命令执行仅白名单解释器（python/python3/pytest/node）
- 不在顶层 import 可选依赖（Windows 兼容）

### 版本号管理
版本号唯一来源：`version.json`。
- 修改版本号只改 `version.json`
- 代码中通过 `from version import get_version` 获取
- 构建脚本从 `version.json` 读取

## 测试

```bash
# 运行全部测试
python -m pytest tests/ -v

# 运行特定模块测试
python -m pytest tests/test_agent_tools.py -v

# 运行并显示覆盖率
python -m pytest tests/ --cov=. --cov-report=term-missing
```

## 打包

```bash
# 使用 PyInstaller 打包
pyinstaller maid_coder_gui.spec

# 输出在 dist/ 目录
```

## 架构决策记录

| 日期 | 决策 | 原因 |
|------|------|------|
| v1.4.8 | 版本号从 version.json 单源读取 | 避免多处不同步 |
| v1.4.8 | 工具返回 JSON 字符串 | 便于模型理解和引擎处理 |
| v1.4.7 | 流式工具循环 | 提升用户体验，content 实时显示 |
| v1.4.7 | 安全白名单统一到 core | 避免 security.py 和 command_runner.py 矛盾 |
| v1.0 | fail-safe 默认拒绝 | 宁可拒绝不可误放 |
