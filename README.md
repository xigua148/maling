# 码铃（MaLing）— 住在桌面里的 AI 女仆伙伴

码铃（MaLing）是一位"住在桌面里"的 AI 女仆伙伴：她**先陪你，再帮你干活**——每天打开有问候、有会随心情变化的形象与角落宠物、偶尔会主动关心你；需要时也能像资深工程师一样自主完成任务（读文件、跑测试、自己修 bug 修到通过）。

- 支持命令行（CLI）和图形界面（GUI）两种模式
- 陪伴优先：无心情/好感数值焦虑（全 UI 不展示分数/等级，关系只靠陪伴表达）
- 自主任务：C1–C4 全链（规划 → 执行 → 自测 → 自愈 → 交付）
- 桌面版：可打包为双击即用的 `MaLing.exe`（PyInstaller，见「.exe 打包整合说明」）
- 各版本改动历史见 [CHANGELOG.md](CHANGELOG.md)

---

## 亮点速览（v2.0.0）

| 能力 | 说明 |
|---|---|
| ⬆️ 自动更新（v2.0.0） | 启动静默检查 + 设置页手动入口；**自动下载 + 手动确认安装**（重启时换包，绝不无确认静默替换）；stable/beta 频道 + 备用镜像链；失败自动回滚，用户数据零影响。**尚未公开发布**，详见「自动更新与分发（v2.0）」 |
| 🎮 开源玩具盒 | 认真写的开源小玩具：2048 / 扫雷（陪玩有 30 分钟冷却、零排行零计分）+ 🍅 番茄钟（专注/休息循环、到点独立提醒你） |
| 👀 持续看屏 | 聊天里开「👀 看屏」：她会持续看着你的屏幕，有疑问随手问她（成本弹窗确认、帧数/消耗 chip、暂停续开、200 帧自动暂停） |
| 🖱 屏幕操作 | 看得见也动得了：每一步屏幕操作先弹「仅这一次 / 拒绝」，低置信先问再动（ctypes 原生注入，零第三方依赖） |
| 🎭 角色预设直选 | 头像等比居中裁切（坏图回退 ✨）+「➕ 新建」+ 6 预设一键直选（maid/coder/sister/cat/dr/brat，幂等不覆盖你的改动） |
| 🔊 TTS 语音朗读 | AI 气泡点「朗读本条」让她把回复念给你听（离线 SAPI5，可自动朗读、调语速） |
| 🖼 区域截图提问 | 划屏截个图直接问码铃（工具区「🖼 截图」/ 热键 Ctrl+Alt+S） |
| 🎙 免提语音对话 | 「🎙 免提」开关：对着麦克风连续说话即可发消息，她会把回答读出来（依赖麦克风 + Google STT 网络，见「语音输入」） |
| 🎲 女仆小游戏 | 抛硬币 / 抽签 / 猜拳 / 21 点——纯随机陪玩，零计分无数值，只添乐趣不加焦虑 |
| ✨ 高光回忆册 | AI 或你的消息右键「收藏为高光回忆」→「回忆」页随时翻看（本地保存） |
| 📅 纪念日祝福 | 设生日 / 首次相见日，当天她只送一句祝福（不倒数、不补发、不打卡） |
| ⌨️ 全局热键 | Ctrl+Alt+M 随时呼出/隐藏主窗；托盘常驻，点❌退出才真正关闭 |
| 🌙 深色模式跟随系统 | 设置「外观模式」浅色 / 深色 / 跟随系统，随 Windows 深浅自动切换 |
| ⏰ 等她回来 Idle 问候 | 离开一阵后回来，她先轻声打个招呼 |
| 🚀 开机自启开关 | 设置 → 通用一键开机启动（默认关） |
| 🏠 房间式首页 | 码铃形象常驻随心情换表情 + 时段问候 + 关系称谓 + 快捷入口 |
| 🎭 角色自定义 | 6 套差异化预设（温柔女仆/编程老手/温柔姐姐/猫娘/毒舌博士/雌小鬼）+ 头像自选 + 性格滑块真注入 + 羁绊自动联动 |
| 🎨 表情差分 | 内置 36+ 张表情（去白底 PNG），随心情/回复内容自动切换 |
| 🐰 宠物造型 | 聊天气泡头像在「女仆小人 / 女仆小兽」间切换（设置 → 个性 → 宠物造型，v1.4 起默认仅女仆小人形态）；窗口角落 MaidPet 默认关闭，可手动开启 |
| 💬 她会先开口 | 有节制的主动陪伴：长空闲/你低落/任务完成未回复 → 温柔问候（免打扰+频控） |
| 🧠 自主干活 | 丢给它任务：自己规划步骤、跑测试、看报错、改代码、再测，直到通过 |
| ⚡ Token 用量 | 会话累计只在首页 Token 卡呈现；聊天面板不显示逐条 token（无焦虑红线） |
| 🎨 无焦虑红线 | 心情/好感只作氛围背景，UI 永无数值条/分数/打卡，不制造养成焦虑 |
| ✨ 简洁 UI | 「简洁 × 女仆基调」设计语言 + 模型配置清晰入口（Key 脱敏 + 首启引导横幅） |

---

## 快速开始（一键安装，推荐）

### 前置要求

- **Python 3.10+**（Windows / macOS / Linux 均支持）
- 一个 DeepSeek API Key（或其他兼容 OpenAI 格式的 API Key，详见「多厂商配置指南」）

### 方式零：Windows 小白双击版（一键启动码铃.bat）

不想碰命令行？直接**双击仓库里的 `一键启动码铃.bat`**：自动检测 Python → 首次自动装依赖 → 打开窗口；之后再双击就是秒开。配套《1分钟启动指南_零基础版.md》三步完成（双击 → 填 Key → 开聊）。适合把整个文件夹拷给朋友。

### 方式一：跨平台 Python 脚本（推荐，最稳定）

适用于 **Windows / macOS / Linux** 所有平台，不受终端编码影响：

```bash
# 1. 克隆项目
git clone https://github.com/xigua148/maling.git
cd maling

# 2. 运行跨平台安装脚本
python install.py

# 3. 启动（GUI 模式默认）
python run.py

# 或启动 CLI 模式
python run.py --cli
```

> 如果终端不支持颜色，可加 `--no-color` 参数：`python install.py --no-color`

### 方式二：Windows 双击运行（备选）

```bash
# 1. 克隆项目
git clone https://github.com/xigua148/maling.git
cd maling

# 2. 双击 install.bat 安装，再双击 run.bat 启动
install.bat
run.bat
```

> 如遇乱码或报错，请改用方式一（`python install.py`），这是 Windows 命令行编码差异导致的，Python 脚本完全不受影响。

### 方式三：macOS / Linux Shell 脚本（备选）

```bash
# 1. 克隆项目
git clone https://github.com/xigua148/maling.git
cd maling

# 2. 运行安装脚本
chmod +x install.sh run.sh
./install.sh

# 3. 启动
./run.sh
```

> **首次运行**会提示你输入 API Key。你也可以提前在项目目录创建 `.env` 文件：
> ```
> DEEPSEEK_API_KEY=sk-your-key-here
> ```

### 安装脚本做了什么？

无论用哪种方式，安装脚本都会：

1. 自动检测 Python 3.10+ 是否已安装
2. 自动创建虚拟环境（`venv/`）
3. 自动安装所有依赖（`requirements_gui.txt`）
4. 给出清晰的启动指引

### 启动模式

| 命令 | 说明 |
|------|------|
| `python run.py` | 启动 GUI 模式（默认，全平台通用） |
| `python run.py --cli` | 启动 CLI 模式（全平台通用） |
| `./run.sh` / `./run.sh cli` | macOS / Linux shell 脚本 |
| `run.bat` / `run.bat cli` | Windows 批处理脚本（备选） |

### Windows 环境兼容性说明

由于 Windows 命令提示符（cmd.exe）的默认代码页在不同设备上可能不同（常见为 936-GBK 或 65001-UTF-8），`.bat` 批处理文件在某些设备上可能出现乱码或解析错误。

**解决方案优先级：**
1. **首选**：使用 `python install.py` / `python run.py` —— Python 脚本完全不受 cmd 编码影响，在所有 Windows 设备上表现一致
2. **备选**：双击 `install.bat` / `run.bat` —— 文件已精简为纯 ASCII，自动调用 Python 脚本，本身不含任何 Unicode 字符
3. **备用**：在 PowerShell 中直接运行 `python install.py`

> 如果双击 `.bat` 仍遇到问题，请直接打开 PowerShell 或 CMD，输入 `python install.py` 即可。

---

## 其他安装方式

### 手动 pip 安装

适合熟悉 Python 环境的开发者：

```bash
# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
# Windows:
venv\Scripts\activate
# macOS / Linux:
source venv/bin/activate

# 安装依赖
pip install -r requirements_gui.txt

# 启动 GUI
python gui/main.py

# 或启动 CLI
python main.py
```

### Docker（规划中，本版未提供）

> 容器化部署尚在规划，当前仓库不含 `Dockerfile`。请使用上方「手动 pip 安装」或「一键启动」方式运行。

---

## 首次配置指引

### 1. API Key 设置

首次启动 CLI 或 GUI 时，程序会检测 API Key 是否存在。如果没有配置：

- **CLI 模式**: 终端会提示输入 API Key，输入后自动保存到 `.env`
- **GUI 模式**: 界面会弹出设置窗口，填写后保存

### 2. 多厂商配置指南（更换 API 厂商）

码铃默认使用 DeepSeek，也支持更换为其他 OpenAI 兼容格式的 API 厂商（Kimi / 通义千问 / 智谱 / OpenAI / OpenRouter / 本地 Ollama 等）。所有配置集中在 `config.yaml` 的 `api` 段，也可以直接在 GUI 里完成。

**怎么选厂商：**

- **GUI 方式（推荐）**：引导页与设置页都有「厂商」下拉框，选定后网址与默认模型名自动带出，你只需要填自己的 API Key；模型框可手动输入任意模型名（不限于下拉预设）。
- **config.yaml 方式**：把 `api.provider` 改成下表中的值即可，选定后 `url` 与默认 `model` 自动带出，也可手动修改。

| provider | 端点 | 默认模型 |
|----------|------|----------|
| `deepseek`（默认） | `https://api.deepseek.com/chat/completions` | `deepseek-chat` |
| `moonshot` | `https://api.moonshot.cn/v1/chat/completions` | `kimi-k3` |
| `qwen` | `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions` | `qwen-plus` |
| `zhipu` | `https://open.bigmodel.cn/api/paas/v4/chat/completions` | `glm-4-flash` |
| `openai` | `https://api.openai.com/v1/chat/completions` | `gpt-4o-mini` |
| `openrouter` | `https://openrouter.ai/api/v1/chat/completions` | `openai/gpt-4o-mini` |
| `ollama`（本地） | `http://localhost:11434/v1/chat/completions` | `llama3.1:8b` |
| `custom` | 手动填写 | 手动填写 |

**怎么填 Key：**

API Key 在各厂商自己的后台申请（DeepSeek 的获取方式见 FAQ），填到 `config.yaml` 的 `api.key` 或 `.env` 文件中。本地 `ollama` 预设无需 Key，GUI 下允许留空。

**使用提示：**

- **旧配置兼容**：旧版 `config.yaml` 没有 `provider` 字段时自动按 `deepseek` 处理，不会报错；`provider` 值为空或未知时同样回退 `deepseek`。
- **深度思考模式**：深度思考模式（CLI 的 `/deep` 或 GUI「深度思考」开关）附带的 `reasoning_effort` 与 `extra_body.thinking` 参数为 **DeepSeek 专属**；使用其他厂商时这些参数**自动跳过、不会发送**，因此更换厂商后开启深度模式不会因不识别字段而报错。CLI 切换深度模式与 GUI 开启深度思考时均会给出对应提示。
- **联网搜索**：`web_search.enabled` 默认开启。联网搜索基于独立的 DuckDuckGo 搜索（HTTP 直连，与 API 厂商无关），对所有 provider 行为一致；未安装搜索依赖时会优雅降级提示，不影响其他功能。

### 3. 个性化配置

编辑 `config.yaml` 可调整以下设置：

```yaml
# 人设相关
persona_role: "女仆"                    # 角色类别
persona_title: "资深全栈开发工程师"      # 角色头衔
persona_personality: "娇羞、温顺、细腻，技术问题上专业且自信"
persona_address_user: "主人"           # 对你的称呼
persona_given_name: ""                 # 她的名字（留空则自称「我」；填「小铃」则以名字自称）
persona_address_self: ""               # 遗留字段：留空即走名字规则（不再用人设标签自称）

# API 相关
api:
  provider: deepseek        # API 厂商预设: deepseek / moonshot / qwen / zhipu / openai / openrouter / ollama / custom
  key: ""                   # 各厂商 API Key（优先从 DEEPSEEK_API_KEY 环境变量读取）
  url: "https://api.deepseek.com/chat/completions"   # 选定 provider 后自动带出，也可手动修改
  model: "deepseek-chat"    # 选定 provider 后自动带出默认模型，也可手动填写任意模型名
  max_tokens: 4096
  temperature: 0.7

# 功能开关
stream_mode: true          # 流式输出
multi_enabled: false       # 多模型协作
clipboard_check: true      # 剪贴板检测
auto_save: true            # 自动保存会话
web_search:
  enabled: true            # 联网搜索（默认开启；独立 DuckDuckGo 搜索，与 API 厂商无关）
  max_results: 5
```

### 4. 会话管理

- 使用 `/save <名称>` 保存当前会话
- 使用 `/load <名称>` 加载历史会话
- 使用 `/session` 列出所有会话
- 程序退出时会自动保存到 `default.json`

---

## 陪伴体验（v1.2.0 起 · 产品重心）

码铃首先是一位"住在桌面里的女仆伙伴"，陪伴功能刻意做得**温柔、不打扰、不制造焦虑**：

- **无数值焦虑红线**：全 UI 不展示心情值/好感分数/经验条/打卡天数——她和你多亲近，只通过表情、语气和"和主人的故事正在『亲近』篇章"这样的关系称谓来体现。数据在后台默默积累，从不逼你"养数值"。
- **房间式首页**：打开码铃就是"她的房间"——形象随心情换表情、按时段问候（早/午/晚/深夜）、一条今日随记。形象为原创女仆插画（去白底透明 PNG 接入；无真图时自动回退中性铃铛占位，绝不显示程序假脸）。
- **角落宠物**：聊天区角落常驻一只**女仆形象的小兽**（默认；可点击互动、随心情换表情）；窗口太窄时自动隐藏不挡操作。**小兽/小人双形态**可在「设置 → 个性 → 宠物造型」全局切换（聊天气泡头像一并跟随；首页大形象/侧栏恒为女仆本体）。
- **她会先开口（主动陪伴）**：只在三种"该关心你"的时刻轻声开口——你很久没理她、检测到你情绪低落、她刚帮你完成任务你却还没回复。有免打扰时段、单日上限、冷却，绝不会连环骚扰；她主动说的话不算交互，不会引发下一轮主动（防自续命）。
- **彩蛋互动**：点一下形象 → 一句台词 + 表情回应（30 分钟冷却内只回话不加分）。
- **心情与好感（可选了解）**：默认不打扰你；想了解关系阶段，首页会显示关系称谓。数据存本地 `~/.maid_coder/companion.json`。

> 陪伴数据纯本地，不上云、不做行为分析。摄像头/麦克风等感知功能 v1.2 不涉及（不做"监督/评判"式陪伴）。

---

## 角色与形象自定义（v1.2 起）

她不止"女仆"一种人格，形象也不止一张脸：

- **6 套差异化预设**（角色面板 →「套用预设…」）：温柔女仆（颜文字+动作）/ 编程老手（零废话直给）/ 温柔姐姐 / 猫娘（句句带喵）/ 毒舌博士（挑刺必有依据）/ 雌小鬼（嘴上嫌弃其实疼你）——气质、称谓、语癖完全错开，一键克隆为可编辑角色。女仆是默认，其余随时可建。
- **自定义任意角色**：新建角色 → 改系统提示词 + 拖三个性格滑块（活泼度/严谨度/贴心度）——**改滑块真的会注入回复风格**；角色可设默认/删除。
- **头像自定义**：点头像选本地图片（PNG/JPG/WebP），自动圆裁为该角色专属头像，重启保留。
- **羁绊**：角色卡底部的「羁绊」随真实关系自动联动（初识→熟悉→亲近→信赖），不是静态装饰。
- **表情差分**：形象资产目录 `gui/assets/maid/` 内置 36+ 张表情（文件名=表情 id，如 `happy.png`），随心情/活动态自动切换；把自己画的 PNG 按文件名放进去即自动生效（透明底最佳）。

---

## Agent 模式（v1.1.0 起）

码铃不止会聊天——**开启 Agent 模式后，它能自主调用工具替你完成任务**：读文件、查目录、看 Git 状态、写文件、跑沙箱代码、联网搜索，然后基于结果继续推理直到收尾。

### 怎么用（GUI）

1. 聊天输入区点 **「🤖 Agent」** 开关（亮起即开启）；
2. 直接说你要它做的事，例如：
   - "读一下 `src/main.py` 前 50 行，告诉我它在干嘛"
   - "看看当前目录结构，找有没有 TODO 文件"
   - "把项目里所有 `FIXME` 注释列出来"
3. 女仆会自主决定调用哪些工具，**消息区下方会出现执行过程卡片**（✅ 成功 / ❌ 失败 / ⛔ 被拒），完成后给出总结。

### 内置工具（9 个，分级授权）

| 级别 | 工具 | 说明 |
|---|---|---|
| L0 只读（自动放行） | `read_file` | 读文件（纯文本返回，自动截断） |
| L0 | `list_dir` | 列目录 |
| L0 | `git_status` / `git_diff` | 查看 Git 状态 / 未提交改动 |
| L0 | `web_search` | 联网搜索（需 ddgs 依赖） |
| L1 修改（需授权） | `write_file` | 写文件（自动 .bak 备份） |
| L1 | `git_commit` | Git 提交 |
| L1 | `run_python` | AST 沙箱执行 Python（禁文件/网络） |
| L1（v1.2） | `run_command` | 白名单内跑 python/pytest/node 并回读输出（进程级 · 非沙箱 · 受白名单约束） |

**授权规则（安全）**：只读工具直接执行；修改类工具若目标在**工作区目录内**自动放行，目录外弹窗问你是否允许——拒绝则不执行。无确认渠道时一律拒绝（fail-safe），绝不越权写文件。`run_command` 额外受命令/语法白名单约束（pip/任意 shell 一律拒绝，拒绝即拒绝不进弹窗）。

### 自主任务（v1.2 · C1–C4）

Agent 模式不止单轮干活——给码铃一个较大的任务（如"修这个失败的测试"），它能**自主拆解步骤、逐步执行、跑测试验证、失败自愈重试**，直到完成：

1. 开启 🤖 Agent 后直接下达任务即可；任务较复杂时码铃会先给出步骤计划；
2. 每步执行后自动验证（如 `run_command` 跑测试看 exit code）；
3. 失败时她把报错回注给自己 → 修改 → 再测，最多重试 N 轮（`agent.max_retries`，默认 3）——**口头说"完成了"但测试没过，不算完成**；
4. 轨迹卡片显示「女仆的工作进度」：步骤清单 + 当前步 + 自愈次数；随时可停止。

### 设置

「设置 → Agent 设置」可配置：启动时 🤖 是否默认开启、单次任务最大步数、自愈重试上限。也可直接编辑 `config.yaml` 的 `agent` 段：

```yaml
agent:
  enabled: false            # 启动后 🤖 按钮默认是否开启
  max_steps: 8              # 单次任务工具调用步数上限
  max_retries: 3            # 失败自愈最多重试轮数
  command_timeout: 30       # run_command 单条命令超时（秒）
  proactive:
    enabled: true           # 有节制主动陪伴总开关
    quiet_start: "22:30"    # 免打扰开始（不打扰主人休息）
    quiet_end: "08:00"      # 免打扰结束
    daily_cap: 3            # 单日最多主动开口次数
    idle_minutes: 90        # 长空闲多久后轻声问候
    cooldown_minutes: 60    # 两次主动的最小间隔
    llm_enhance: false      # 主动文案是否用 LLM 增强（默认纯模板）
```

> Agent 模式基于模型 function calling。模型或厂商不支持时会退化为普通聊天，不影响使用。

---

## AI 看图（多模态，v1.2.2 起）

**适用场景**：报错截图、界面/布局问题、图表、白板草稿、照片——"说不清、一看就懂"的问题。

**操作**：拖入或添加图片（≤8MB/张，最多 3 张）→ 发送 → 附一句话引导（如"看这张报错，为什么崩"）；或有摄像头的电脑点输入区 **📷 拍照** 直接拍一张发。

**前提：模型必须支持视觉。** 码铃按 OpenAI 兼容多模态格式发送图片；纯文本模型（DeepSeek 官方接口等）不支持，发送会报错并提示。要把看图用起来，把「设置 → 模型与接口」里的模型换成一个支持视觉的 OpenAI 兼容端点，例如：

| 服务 | API URL（OpenAI 兼容） | 模型示例 |
|---|---|---|
| 智谱 GLM（有免费额度，最易上手） | `https://open.bigmodel.cn/api/paas/v4/chat/completions` | `glm-4v-flash` / `glm-4v-plus` |
| 阿里通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions` | `qwen-vl-plus` / `qwen-vl-max` |
| OpenAI | `https://api.openai.com/v1/chat/completions` | `gpt-4o` / `gpt-4o-mini` |

> 换厂商只需在「模型与接口」选厂商卡片 → 填该服务的 API Key（URL/模型通常自动带出）→ 保存。换回 DeepSeek 即回到纯文本模式，看图按钮不影响。

---

## 功能使用说明（GUI）

以下功能走主题色与无侵入式接入，关闭后回退到原有行为。

### 1. 文件拖拽上传

**怎么用：** 在聊天输入框上方或整个消息区**直接拖入文件**（支持多选）。

- 拖入后会在输入框上方出现**芯片条**（chip），显示：类型图标 + 文件名 + 大小。
- 每个芯片右侧的 **×** 可单独移除。
- 发送时，AI **实际收到的内容按文件类型如实区分**（并非 "AI 已看到整个文件"）：
  - **文本 / 代码类**（`.txt` `.md` `.markdown` `.json` `.py` `.js` `.ts` `.tsx` `.jsx` `.html` `.htm` `.css` `.xml` `.yaml` `.yml` `.toml` `.ini` `.sql` `.csv` `.tsv` `.sh` `.bat` `.cmd` `.go` `.rs` `.java` `.c` `.cpp` `.h` 等代码 / 标记 / 配置 / 表格 / 脚本类后缀）：AI **会读到文件正文**——≤ 50KB 全量读入；超过 50KB 则截断读入，并附截断提示与原文件大小。
  - **Office 文本文档**（`.docx` Word、`.xlsx` Excel）：AI **会读到抽取出的正文**——Word 按段落取文本、Excel 按单元格取文本（共享字符串 / 内联字符串 / 数值），同样 ≤ 50KB 全量、更大截断并标注；若文件损坏或非标准格式，则**降级为仅附文件名与大小**，并明确说明解析失败。
  - **图片**（`.png` `.jpg` `.jpeg` `.webp` `.bmp`，单张 ≤8MB、每轮 ≤3 张）：若当前模型**支持视觉**（OpenAI 兼容多模态端点，如智谱 GLM-4V / 通义 qwen-vl / OpenAI GPT-4o 等），图片会**以原图直传**——AI 真正"看到"图（截图报错、界面问题、手绘示意都适用）；纯文本模型（如 DeepSeek 官方接口）不支持看图，会提示更换视觉模型。图片仅随**当前轮**发送，历史记录不回放图片。拖图时建议附一句话引导（如"看这张报错截图"）。也可点输入区 **「📷 拍照」** 直接拍一张（需本机摄像头，拍完加入附件随消息发送）。
  - **其它二进制 / 暂不支持解析的类型**（`.pdf`、旧版 Office 的 `.doc` / `.ppt`、压缩包、exe 等）：**不支持解析内容**，AI **只看到文件名、类型与大小** 这一行附件信息，不会假装读到文件内容——**请把关键内容直接粘贴进消息正文**。
- 发送后，自己与对方的气泡里展示的**芯片仅作展示**（文件名 + 大小），不代表 AI 已读取其中内容。
- **单文件上限 10MB**；超限会弹窗提示「已添加 N 个附件 / 超 10MB 的文件 N 个被拒绝」。
- 重复文件（同一绝对路径）会被去重；不存在的文件会被跳过。

**入口位置：** 主聊天面板 + 独立聊天浮窗（`chat_window.py`）均支持。

### 2. 消息编辑 / 重新生成

**编辑用户消息：**
- 在自己发出的**用户气泡**上**右键 → 「编辑」**，原内容会回填到输入框（同时把这条消息的附件一并回填到芯片条，可继续添加或修改）。
- 改完按发送：从该条**之后的所有气泡**会被截断（包含本条在内），新的 AI 回复会重新流式输出。
- 取舍：采用「就地截断+重发」而非「分支」——实现简单、行为可预期；旧会话历史里被截断的消息**不删除磁盘**（仅 UI 隐藏），刷新页面后会从 `metadata` 字段恢复。

**重新生成 AI 消息：**
- 在 AI 气泡**右键 → 「重新生成」**，或在 AI 气泡底部按钮行点 **「🔄 重新生成」**。
- 当前 AI 气泡**之后**的所有消息会被截断，AI 重新生成。

**持久化兼容：** `ChatMessage.metadata` 字段在旧会话文件里默认为 `{}`，新格式会话文件带 `metadata.attachments`；加载旧文件不会崩溃，保存新文件不会丢字段。

### 3. 多会话标签页（Tab 模式）

**开启方式：** 主聊天面板顶部、刷新按钮旁有一个 **「📑 标签」** 切换按钮。开启后：
- 顶部多出一行 **类似浏览器的 tab**：每个 tab 显示会话标题（未命名显示「**新会话**」），右侧 **×** 关闭。
- 行尾的 **「+」** 新建标签。
- 切换 tab 即切换当前会话；消息历史与左侧会话列表共享同一数据源。

**关闭 vs 删除：**
- **关闭 tab** = 结束当前 tab，但**会话本身仍保留**（在左侧列表里仍然在，关闭的 tab 只是不再显示）。
- **删除会话** 仍走左侧列表的**右键 → 删除**。

**主题切换：** tab 的颜色全部从 `theme_engine.get_color()` 取色，切换主题后调用 `apply_theme()` 即同步，无需重启。

### 4. 语音输入（可选依赖）

输入区右下角有 **「🎤 语音」** 按钮：

- **依赖缺失时**：弹出明确说明对话框，告知「未检测到语音识别后端 / 无可用麦克风设备」，并给出**两条可执行路径**：
  1. `pip install SpeechRecognition pyaudio`（需真实麦克风 + 可访问 Google 语音 API 的网络）；
  2. 接入公司/自建的 ASR 模型 API（修改 `gui/widgets/voice_input.py` 中 `recognize_*` 调用）。
- **依赖就绪时**：弹出录音对话框，按「开始录音」→ 8 秒内识别 → 文字回填到输入框。

语音输入是**可选依赖**：装不上不影响聊天等其他任何功能，程序会明确提示而不是崩溃。

### 5. 免提语音对话（v1.3，可选依赖）

聊天面板顶部常驻免提状态条 + 工具区 **「🎙 免提」** 开关（与「🎤 语音」并存）：

- 开启后**连续对话**：你直接说话 → 识别 → 自动发消息 → 她把回答念给你听 → 继续听下一句（循环）。
- **三种方式停止**：点状态条「⏹ 停止」/ 说「暂停 / 结束对话 / 不说了」/ 开始敲键盘或动鼠标即自动暂停。
- 识别失败或安静不打断循环；免提期间她会暂停主动问候（不抢麦）。
- 依赖与既有「语音输入」一致：**需系统麦克风 + 可访问 Google 语音 API 的网络**；真机音频链路（音量/噪音/打断灵敏度）建议按实际环境标定后再日常使用。

### 6. 区域截图直接问（v1.3）

- 工具区 **「🖼 截图」** 或全局热键 **Ctrl+Alt+S**：进入划屏选区 → 松开即截取该区域 → 图片进附件条并预填一句引导，**不会自动发送**，可补充文字后发送。
- 需当前模型支持视觉（与「📷 拍照」/拖图直传同链路），纯文本模型会提示更换视觉模型。

### 7. 女仆小游戏（v1.3）

- 工具区 **「🎲 小游戏」** 打开对话框，可选**抛硬币 / 抽签 / 猜拳 / 21 点**，她当荷官给台词与表情。
- 纯随机陪玩：**无分数/筹码/胜率/等级**，不落聊天记录、不进好感计分；每局间隔 30 分钟冷却（只限情绪反馈，不计数）。

### 8. 高光回忆册（v1.3）

- AI 或你的消息气泡上**右键 → 「✨ 收藏为高光回忆」**，即存入本地回忆册。
- 左侧导航「**回忆 ✨**」页按时间倒序展示卡片（角色标签 + 心情 + 日期），可取消收藏或清空。
- 本地保存于用户数据目录（`highlights.json`，上限 500 条自动淘汰），**绝不上云**；不设打卡/连续收藏等激励。

### 9. 纪念日祝福（v1.3）

- 设置 → **「纪念日」**：用日历控件录入**生日 / 首次相见日**（只记月日，周年语义）。
- 当天她**只主动送上一次祝福**（生日与初见同日会合并成一句）；**不做倒数、不补发、不催打卡**——错过即错过，记不记得由你决定。

### 10. 主题与深色模式说明

新引入的所有 UI（附件芯片、tab 标签、语音对话框）**全部**通过 `gui.utils.theme_color(app_ctx, key, fallback)` 取色，**禁止硬编码颜色**。主题切换时调 `refresh_theme()` / `apply_theme()` 即生效。新增的色键：

- `text_on_accent`：强调背景上的文字色（默认 `#FFFFFF`）
- `bg_light`：次级背景（默认 `#FFF0F3`）
- `disabled_bg` / `disabled_text`：禁用态（默认 `#E0E0E0` / `#9E9E9E`）

**外观模式（v1.3）**：设置 → 外观主题 → **「外观模式」浅色 / 深色 / 跟随系统**（默认浅色）。「跟随系统」读取 Windows 深浅色设置并低频自动跟随；每套主题都配了 `colors_dark` 深色色板（气泡/输入区/主要表面随深色切换，个别历史控件仍为浅色高亮属后续持续收窄范围）。

**界面字体（v1.9）**：设置 → 外观主题 → **「界面字体」**下拉，可选六款：

- **资源圆体**（默认，内置 OFL 1.1）：正文 / 界面，Regular + Medium 两字重。
- **幼圆 / 雅黑 / 楷体 / 等线**：Windows 系统字体（可选回退，雅黑同时作为生僻字兜底）。
- **jf open 粉圆**（内置 OFL 1.1）：**仅作用于标题 / 点缀位**，选中后正文自动保持资源圆体（代码守卫，不会误设为正文）。粉圆简体覆盖有限，缺字自动回落雅黑（不会显示方块）。

切换即时生效并持久化（写入 `gui_config.json` 的 `font_family`）；老用户配置无该键时自动升级为资源圆体。内置字体产物与 OFL 许可副本见 `gui/assets/fonts/`，许可全文见 `docs/third_party_licenses/`，构建脚本 `tools/build_fonts.py`（仅构建期依赖 fonttools / brotli / py7zr，**不进运行时**）。

**界面风格（v1.9）**：设置 → 外观主题 → **「界面风格」**（下拉 + 色块预览），四款：

- **现代极简**（默认）：冷灰浅色，扁平克制。
- **温暖奶油**：暖棕浅色，圆角更柔。
- **深色夜间**：深色专属 —— 选中后自动锁定深色（「外观模式」下拉收起并提示；离开该风格会恢复你原来的浅色 / 深色 / 跟随系统设置，且原设置不会丢失）。
- **鲸鱼娘深海**：清爽深海蓝（主按钮与背景走浅海渐变）；此风格下界面问候语/欢迎语/状态口吻的自称随当前角色名字（取不到则「我」），产品名「码铃」不变。

切换即时生效并持久化（写入 `gui_config.json` 的 `theme_name`）；旧主题配置自动映射：可爱风 / 女仆粉 → 温暖奶油，简约风 → 现代极简（旧 QSS 文件保留但不再作为可见选项）。聊天页顶栏与首次启动引导页同样可选四风格。

### 11. 设置项速览（GUI，v1.3 起）

- **外观主题**：四套界面风格（现代极简 / 温暖奶油 / 深色夜间 / 鲸鱼娘深海）+ **外观模式**三选（浅色 / 深色 / 跟随系统）+ **界面字体**（v1.9：资源圆体默认 / 幼圆 / 雅黑 / 楷体 / 等线 / 粉圆仅标题）。
- **语音区**：TTS 朗读总开关 / AI 回复自动朗读 / 语速滑条（0–100）。
- **纪念日区**：日历控件录入生日、首次相见日（见上文「纪念日祝福」）。
- **通用区**：全局热键改键（呼出主窗 / 区域截图提问）、**关闭窗口行为**（勾选「关闭窗口直接退出」= 点 X 真正退出；默认不勾 = X 隐藏到托盘）、**开机自启**开关（首次开启会确认，可随时干净移除）。
- **更新区（v2.0）**：检查更新（三态按钮）/ 更新频道（稳定版 / beta）/ 自动检查更新 / 自动下载更新 / 更新源（只读域名）+ 使用备用链 / 自定义镜像 / 清理更新缓存；另有上次更新结果只读提示行（仅失败 / 回滚时出现）。
- 个性 / 模型与接口 / Agent 等既有分区保持不变。

---

## 常见问题 FAQ

### Q: 提示 "Python 3.10+ 未检测到"

**A:** 请访问 [python.org/downloads](https://www.python.org/downloads/) 下载并安装 Python 3.10 或更高版本。
- **Windows**: 安装时务必勾选 **"Add Python to PATH"**
- **macOS**: 推荐通过 Homebrew 安装 `brew install python@3.12`
- **Linux**: 使用包管理器安装，如 `sudo apt install python3.12 python3.12-venv`

### Q: 安装依赖时卡住或超时

**A:** 这是 PySide6 体积较大导致的正常现象（约 150MB+）。建议：
1. 使用国内镜像加速：
   ```bash
   pip install -r requirements_gui.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
   ```
2. 单独先装 PySide6，再装其他依赖：
   ```bash
   pip install PySide6>=6.5
   pip install -r requirements_gui.txt
   ```

### Q: 权限不足（Permission denied）

**A:**
- **Windows**: 右键点击脚本，选择"以管理员身份运行"
- **macOS / Linux**: 先赋予执行权限：
   ```bash
   chmod +x install.sh run.sh
   ```

### Q: 启动时提示 "缺少 API Key"

**A:** 运行时会交互式提示输入 API Key。你也可以手动创建配置文件：

**方法 1 —— .env 文件（推荐，不入 git）：**
```bash
echo "DEEPSEEK_API_KEY=sk-your-key" > .env
```

**方法 2 —— config.yaml：**
编辑项目目录下的 `config.yaml`，找到 `api_key:` 填入你的 Key。

### Q: 如何获取 DeepSeek API Key？

**A:**
1. 访问 [DeepSeek 开放平台](https://platform.deepseek.com/)
2. 注册并登录账号
3. 进入 "API Keys" 页面创建新 Key
4. 复制 Key 到 `.env` 文件或运行时的提示中

### Q: GUI 模式下窗口显示异常

**A:**
- 确保显示器缩放设置为 100% 或 125%（PySide6 高 DPI 适配已知问题）
- 尝试在启动前设置环境变量：`export QT_AUTO_SCREEN_SCALE_FACTOR=0`

---

## .exe 打包整合说明

> 本章节写给需要在 **Windows 本机** 把码铃打包成 `.exe` 的使用者。开发环境为 Linux 沙箱，无法产出真实 `.exe`，因此本文所有「打包/运行」步骤均标注 **[需用户本机执行]**；已验证 / 未验证边界见本节末尾。项目内已同步提供修订后的 `maid_coder_gui.spec`（产物名 `maling`、图标 `gui/assets/maling.ico`）与补齐的 `requirements_gui.txt`。
>
> ✅ **2026-09-03 已在 Windows 实测打包成功**：`python -m PyInstaller maid_coder_gui.spec --noconfirm` 约 1 分钟产出 `dist/maling/maling.exe`（onedir ≈218MB），offscreen 启动冒烟通过。**务必保留 spec 中 `('gui/assets/maling.ico', 'assets')` 这行**——图标不进包会导致任务栏/托盘退回默认图标（曾踩过）。语音依赖（speech_recognition/pyaudio）为可选，未装仅语音按钮降级提示、不影响其它功能。详细可复现步骤见《码铃_v1.2.0_本机打包发版指引.md》与配套分发 zip。

> ✅ 当前版本 **v2.0.0**：主产物打包流程与 v1.4.1 相同（`python -m PyInstaller maid_coder_gui.spec --noconfirm` ＋ onefile spec）。
> ⚠️ **待发布**：`version.json` 已定版 **2.0.0**，`GITHUB_OWNER` 已注入真实账号 **`xigua148`**（仓库 `github.com/xigua148/maling`），双产物已按此重打并算好真实 sha256；尚待把产物上传 GitHub Release（tag `v2.0.0`）并 push `version.json` 后客户端才能看到新版。发版时另需构建更新器 sidecar（`updater.spec`）并按 `docs/design-v20.md` §7 的 12 步走完清单。见「自动更新与分发（v2.0）」。
> 各版本改动见 [CHANGELOG.md](CHANGELOG.md)；功能真实性审计见 [docs/audit-功能真实性清单-2026-09-07.md](docs/audit-功能真实性清单-2026-09-07.md)。

### 一、环境准备与依赖清单 [需用户本机执行]

| 依赖 | 用途（包内 import 依据） | 必需性 |
|------|--------------------------|--------|
| Python 3.11 / 3.12 | 全部代码；`install.bat` 要求 ≥3.10，PySide6≥6.5 与 PyInstaller 6.x 对 3.11/3.12 支持最成熟 | 必需 |
| PySide6 ≥ 6.5 | `gui/qt_compat.py` 顶层导入，全部界面 | 必需 |
| requests ≥ 2.31 | `core/__init__.py:43` 顶层导入，API 调用 | 必需 |
| PyYAML ≥ 6.0 | `core/__init__.py:59` try-import；`config.yaml` 读写 | 必需 |
| colorama ≥ 0.4 | `core/__init__.py:47` try-import，终端着色 | 建议 |
| python-dotenv ≥ 1.0 | `core/__init__.py:53` try-import，`.env` 支持 | 建议 |
| pyperclip ≥ 1.8 | `core/__init__.py:65` try-import，剪贴板 | 建议 |
| pygments ≥ 2.16 | `gui/pages/page_editor.py:19` try-import，编辑器高亮 | 建议 |
| ddgs ≥ 9.0 | `core/__init__.py:69` try-import（回退 `duckduckgo_search`），联网搜索 | 可选 |
| SpeechRecognition ≥ 3.10 | `gui/widgets/voice_input.py:29` importlib 动态探测，语音输入 | 可选 |
| pyaudio ≥ 0.2.13 | `speech_recognition.Microphone` 的录音后端 | 可选（语音） |
| pyinstaller ≥ 6.0 | 打包工具本身 | 打包机必需 |

一键安装（在项目根目录）：

```bat
pip install -r requirements_gui.txt
```

说明：原 `requirements_gui.txt` 中的 `markdown` 已移除——全包代码无 `import markdown`（聊天导出的 Markdown 是 `gui/chat_exporter.py` 手写字符串拼接），装了也无害但属冗余。

### 二、打包方案 [需用户本机执行]

推荐用随包分发的 spec 文件（onedir 模式，修订点见 spec 头部注释）：

```bat
cd maling                    :: 项目根目录（README.md 所在层）
pip install -r requirements_gui.txt
pyinstaller maid_coder_gui.spec --noconfirm --clean
```

产物：`dist\maling\MaLing.exe`（同目录含 Qt 运行库与主题 QSS）。**分发时整个 `dist\maling` 文件夹一起拷贝，不要只拷 exe**。

对外分发时，把整个 `dist\maling` 文件夹压成 zip，按 **`maling_v{版本}_{平台}.zip`** 命名（如 `maling_v1.0.0_win64.zip`），随 GitHub Release 发布并附 md5 校验值。

spec 关键配置及其依据：

- **入口**：`gui/main.py`（`gui/main.py:10-15` 已做 `sys.frozen` / `sys._MEIPASS` 兼容，PyInstaller 感知）
- **窗口模式**：`console=False`，无控制台黑窗
- **资源文件**：`('gui/themes', 'themes')`——把三套 QSS（`cute.qss` / `minimal.qss` / `maid.qss`）放到 `_MEIPASS/themes/`，与 `gui/utils.py get_resource_path()` + `theme_engine.py:108` 的 frozen 解析路径对齐。**注意：旧版 spec 写的是 `('gui/themes', 'gui/themes')`，打包后代码会找不到 QSS，三主题将全部降级为内置默认样式**，本版已修正
- **hiddenimports**：`speech_recognition` + `pyaudio`（`voice_input.py:29` 是 `importlib.import_module("speech_recognition")` 动态导入，PyInstaller 静态分析看不到，不声明则打包后语音永远提示「未安装」）；另显式列出第四阶段控件与全部 `commands/*_cmds`（静态可见，属保险项）
- **v1.3 新增模块 hiddenimports**（11 个，见 spec 头部注释）：`gui.tts` / `gui.hotkeys` / `gui.tray_manager` / `gui.system_idle` / `gui.widgets.screen_capture` / `gui.voice_conversation` / `gui.widgets.handsfree_bar` / `gui.widgets.mini_games` / `gui.pages.page_memories` / `highlights` / `autostart` + **`PySide6.QtTextToSpeech`**（TTS 后端）。QtTextToSpeech 的 SAPI 插件由 PySide6 官方 hook 自动收集，随包验证通过；若朗读按钮不可用，先确认 Windows「语音设置」里有可用语音包
- **Qt 平台插件**：PyInstaller 6.x 自带 PySide6 hook，自动收集 `platforms/qwindows.dll` 等插件，无需手写
- **图标**：`icon='gui/assets/maling.ico'`
- **UPX 关闭**：`upx=False`，降低杀软误报率

**onefile 单文件变体**（如坚持要单个 exe 文件）：把 spec 中 `EXE(...)` 的 `exclude_binaries=True` 删掉、改为在 `EXE(...)` 里传 `a.binaries, a.zipfiles, a.datas`，并删除整个 `COLLECT(...)` 段；产物为 `dist\MaLing.exe`。代价：启动变慢（每次解压到临时目录）、杀软误报率升高，不推荐。

### 三、运行路径行为（重要）

- **config.yaml**：`gui/main.py:97` 以相对路径 `Path("config.yaml")` 读写——首次运行在 **exe 所在目录** 自动生成默认配置，之后直接编辑该文件填 `api_key` 即可。因此请**通过双击 exe 启动**（CWD=exe 所在目录）；从其他目录用绝对路径启动会导致配置文件散落在当时目录。
- **会话/用户数据**：聊天会话存 `~/.maid_coder/sessions/`（`gui/session_manager.py:14`），GUI 配置存系统用户数据目录（`gui/utils.py get_user_data_dir()`，Windows 为 `%APPDATA%\maid_coder`），均不依赖 exe 所在位置，可放心分发。
- **关闭窗口行为（v1.3 起）**：默认点主窗 **X 是「最小化到系统托盘」而非退出**——从托盘点 **❌ 退出** 才真正关闭进程（退出前会保存窗口几何与会话）；若想恢复「点 X 直接退出」，在设置 → 通用勾选「**关闭窗口直接退出**」。app 级单托盘由 `gui/tray_manager.py` 创建（含 📷 拍照 / 🎤 语音 / 🖼 截图 / ⚙️ 设置 / 💬 浮窗 / ❌ 退出 完整菜单），聊天浮窗不再自建第二托盘图标。
- **主题 QSS**：只读资源，从 `_MEIPASS/themes/` 加载（onedir 模式下在 exe 同目录的 `_internal/themes/`）。

### 四、打包后验收清单 [需用户本机执行]

逐条勾选（每条对应一项关键功能）：

1. **启动**：双击 `MaLing.exe`，主窗口正常出现、无控制台黑窗、图标正确；首次运行 exe 目录生成 `config.yaml`
2. **发消息**：`config.yaml` 填入 API key 后重启，发送一条消息——用户气泡**只出现一个**，AI 流式回复正常渲染（Markdown + 代码高亮）
3. **附件拖拽**：把一个小于 10MB 的文件拖进聊天区→出现附件芯片→发送后气泡内展示文件名/图标/大小；再拖一个 >10MB 文件→被拒绝并提示
4. **语音输入**：装了 SpeechRecognition+pyaudio 的机器，点「🎤 语音」弹出录音对话框、能识别回填；未装的机器点按钮→弹窗明确说明缺什么（不应崩溃）
5. **导出**：右键/菜单导出聊天记录为 Markdown / TXT / JSON，三种格式内容完整（中文无乱码）
6. **三主题切换**：cute / minimal / maid 三套主题逐一切换，界面即时换肤且**QSS 真实生效**（若切完样式粗糙单一，说明 QSS 没打进包，回查第二节 datas 配置）
7. **多会话标签页**：新建/切换/关闭标签，关闭后切到相邻标签；重启后会话历史恢复
8. **编辑/重新生成**：右键编辑用户消息→确认框→重发；AI 气泡「重新生成」从中段正确重答
9. **托盘/独立窗口**：聊天窗口可分离、置顶，系统托盘图标可显示/恢复

### 五、常见坑

- **杀软误报**：PyInstaller 打的未签名 exe 是误报重灾区。已做：UPX 关闭、onedir 模式。仍被报毒时：加入 Defender 白名单 / 上传样本申诉；正式开源分发建议做代码签名（Authenticode 证书）
- **体积优化**：PyInstaller 只收 import 链上的模块，`_split_script.py`、`install.py`、`install.bat`、`run.py`、`run.bat` 等源码运行辅助脚本**不会**进 exe（不在 `gui/main.py` 依赖链上），无需处理。可选的惰性依赖（`PIL`/`pytesseract` OCR、`networkx` 可视化、`numpy`、`httpx`）若打包机未安装则自动不收录，exe 更小——代价是对应 CLI 命令不可用，GUI 主功能不受影响。spec 的 `excludes` 已排除 `tkinter`
- **路径/编码**：所有读写均显式 `encoding="utf-8"`（QSS、会话 JSON、导出文件），中文无乱码风险；唯一路径坑是 `config.yaml` 的 CWD 相对性（见第三节）
- **Windows SmartScreen**：首次运行可能弹「未知发布者」，点「仍要运行」；开源后随版本热度和签名可缓解
- **PyAudio 安装失败**：Python 3.11/3.12 下 `pip install pyaudio` 有预编译 wheel，一般可直接装；若失败先升级 pip，或从 Gohlke 仓库装对应版本 wheel。装不上就放弃语音功能，其余不受影响（语音入口三态探测会给出明确指引）

### 六、已验证 / 未验证边界（如实声明）

- **已在 Linux 沙箱验证**：依赖清单与每个 import 的对应关系（AST 全量扫描 118 个包内文件）；入口脚本与 frozen 兼容代码（`gui/main.py:10-15`、`gui/utils.py:10-13`）存在且正确；`get_resource_path` 与旧 spec datas 目标的路径错位（用路径解析推演复现）；spec / requirements 修订后全量 `py_compile` 与包完整性
- **未验证（沙箱无 Windows，需用户本机执行）**：`pyinstaller` 实际打包产物、exe 启动与第四节全部验收项、杀软/SmartScreen 实际行为。本文相应步骤均已标注

---

## 自动更新与分发（v2.0）

> 本节描述 v2.0.0 新增的自动更新能力。**当前状态：功能已实现并通过自测，双产物已构建**——`version.json` 已定版 **2.0.0**；`GITHUB_OWNER` 已注入真实账号 **`xigua148`**（仓库 `github.com/xigua148/maling`），下载地址与 `sha256` 已填真实值，**尚待上传 GitHub Release 并 push `version.json`**（见 `docs/design-v20.md` §7 发版清单）。版本与改动见 [CHANGELOG.md](CHANGELOG.md)。

### 怎么检查更新

- **自动检查**：启动码铃时后台静默检查一次（可在 设置 → **更新** 关闭「自动检查更新」）。
- **手动检查**：设置 → **更新** → 「检查更新」按钮；**「关于」页**同样有「检查更新」入口，并显示当前版本与更新源。
- 检查结果三态：**发现新版本** / **已是最新** / **检查失败**（只给一句提示，可稍后重试）。检查全程不影响你正常聊天。

### 更新流程：自动检查 + 自动下载 + **手动确认安装**

码铃**不会**在你不知情、未点头的情况下静默替换程序。完整流程是：

1. 启动后按节奏自动检查（默认约每 24 小时一次，避免频繁打扰；可在设置中关闭）；
2. 发现新版本 → 弹出**非阻断**提示：`立即下载 / 稍后 / 忽略此版本`（忽略后同一版本当天不再追问）；
3. 下载并校验完成后提示「**vX.Y.Z 已下载并校验通过，重启后启用**」——此时才问是否安装；
4. 你点「**立即重启安装**」，或直接退出码铃，程序在退出后由独立的更新器（sidecar）完成换包，**下次打开即新版**。

> 一句话概括：**下载可以自动，安装必须你确认**（或在退出时按你的确认执行）。没有"你不知情就被换掉"的路径。

### 频道：稳定版 / beta

设置 → 更新 → **「更新频道」** 可选 **稳定版（stable）** 或 **beta**。两者使用同一套更新机制，只是读取不同的版本指针文件；普通使用者保持默认「稳定版」即可。

### 备用链与自定义镜像

- 更新默认走 GitHub Release，同时预留**备用下载链**；「**使用备用链（镜像）**」开关默认开启，主链失败时自动降级重试。
- 若你有自己的镜像地址（国内加速等），可在设置 → 更新 → **「自定义镜像」** 填入；该地址的域名会并入下载白名单。
- 下载支持**断点续传**：中途断网后重试会从已下载的部分继续；取消下载也会保留已下载的分片（`.part`），下次可续。

### 安全校验

- 下载只允许 **https** 且限**白名单域名**（含你配置的镜像域名），拒绝非安全协议与未知来源；
- 下载完成后强制校验 **SHA-256**：版本文件未提供有效 `sha256` 时**不提供自动安装**（只建议手动下载）；校验不通过的文件会被删除，**绝不进入安装流程**。

### 备份与回滚

- 安装（换包）采用**「先改名、再就位」**的原子方式：旧版本目录被完整改名保留为备份，新版本目录就位后拉起；**全程总有一个可运行的版本**，不会出现"半新半旧"打不开的情况。
- 新版本启动后若在限定时间内未正常就绪（窗口未起来 / 进程提前退出），更新器会**自动回滚**到上一版本并重新拉起旧版；回滚结果会在设置页「更新」区以一行只读提示如实告知（如"上次更新未完成，已回滚到旧版本"）。
- 更早的历史备份会按策略清理，只保留最近一份，避免长期占用磁盘。

### 你的数据不受影响

更新只替换**程序本体**；聊天会话、记忆、角色人设、配置、知识库、待办、日记、提醒等**用户数据**（Windows 下位于 `%APPDATA%\maid_coder`）在更新前后**保持不变**，不会被读取、覆盖或删除（更新子系统自身的状态文件与其下载缓存 `update_state.json` / `updates/` / `updater/` 除外）。

### 清理更新缓存

设置 → 更新 → **「清理更新缓存」** 可清空已下载的更新包缓存（`updates/`），**保留回滚备份与更新器本体**，不会影响已安装版本与你自己的数据。

### 诚实声明（未做 / 待验证的部分）

- **未做代码签名**：本版分发的可执行文件**没有进行 Authenticode 代码签名**，首次运行可能触发 Windows SmartScreen「未知发布者」提示（点"仍要运行"即可）。正式对外分发前建议补上代码签名。
- **尚未上传 GitHub Release**：`version.json` 已填入正式地址（`github.com/xigua148/maling`），但产物尚未上传到 Release 页；请以正式发布页为准。
- **自动更新目前仅支持 Windows**（onedir 与 onefile 两种打包形态）；源码运行态（dev 模式）保留检查与下载，但**不会自动替换**（便于开发调试）。
- **真机端到端验证待补**：断网续传 / 校验失败 / 安装目录不可写 / 真实进程占用等极端路径，需在发布前按清单在真机上实测留档（见 `docs/design-v20.md` §8.3 与 §7 第 12 步）。

---

## 开发者指南

### 模块拆分说明

项目最初为单文件脚本（4139 行），现已按模块边界拆分为多个 Python 文件，功能完全等价。

#### 文件清单

| 文件 | 行数 | 职责 |
|------|------|------|
| `core.py` | ~400 | 基础层：导入、可选依赖检测、样式/颜色、常量、AppConfig、日志、print_typed |
| `api.py` | ~232 | API 层：APIClient（带重试）、APIKeyRotator（多 Key 轮换） |
| `persona.py` | ~74 | 人设层：PersonaConfig、PromptManager（系统提示词组装） |
| `security.py` | ~71 | 安全层：is_command_safe、build_tools_definition、scan_sensitive_info |
| `harness.py` | ~111 | 工具层：call_harness（外部命令执行封装） |
| `editors.py` | ~134 | 编辑层：FileEditor（/read /edit /apply /undo） |
| `managers.py` | ~278 | 管理层：SessionManager、SnippetManager、TodoManager、PluginManager、StatsTracker |
| `helpers.py` | ~356 | 辅助层：GitHelper、CodeSandbox、WebSearch、KnowledgeBase |
| `agents.py` | ~220 | Agent 层：AgentSystem（角色切换）、MultiModelCollaborator（生成-评审-修正-裁判） |
| `agent_tools.py` | 新增 v1.1 | Agent 工具注册表：8 个工具（L0 只读 / L1 修改分级授权），v1.2 加 run_command（9 个） |
| `agent_engine.py` | 新增 v1.1 | AgentEngine 统一调度器：LLM 推理 ↔ 工具执行循环，CLI/GUI 共用 |
| `command_runner.py` | 新增 v1.2 | C1 run_command 进程执行器：命令/语法/路径三重白名单 + 超时 + 截断 + 互斥 |
| `agent_task.py` | 新增 v1.2 | C3/C4 任务域：TaskStep/TaskRun/TaskRunStore/Planner + 自愈 + 任务级记忆 |
| `companion.py` | 新增 v1.2 | 陪伴域：MoodState 心情引擎（纯规则）+ 成就 + 彩蛋 + 主动陪伴记账 |
| `session.py` | ~426 | 会话层：ChatSession（状态封装、单轮对话、历史管理、自动摘要） |
| `utils.py` | ~1221 | 工具函数层：show_help、parse_command、启动辅助、崩溃恢复、P1/P2 新功能、离线缓存、审计日志 |
| `main.py` | ~783 | 入口层：main() 函数、启动流程、主循环、命令分发 |

#### GUI 模块

| 文件 | 职责 |
|------|------|
| `gui/main.py` | GUI 入口，初始化 QApplication 和主窗口 |
| `gui/main_window.py` | 主窗口框架 |
| `gui/chat_service.py` | 聊天服务层（v1.1 起含 Agent 模式分支与授权桥） |
| `gui/theme_engine.py` | 主题引擎 |
| `gui/config.py` | GUI 配置管理 |
| `gui/pages/` | 各页面组件（设置页含「Agent 设置」区块） |
| `gui/widgets/` | 可复用 UI 组件（含 v1.1 `tool_trace.py` Agent 轨迹卡片） |

#### 依赖关系

```
main.py
  ├── core.py          (基础常量、配置、日志)
  ├── api.py           (API 客户端)
  ├── persona.py       (人设提示词)
  ├── session.py       (聊天会话)
  ├── agents.py        (Agent 系统)
  ├── agent_tools.py   (Agent 工具注册表，v1.1)
  ├── agent_engine.py  (AgentEngine 调度器，v1.1)
  ├── utils.py         (工具函数)
  ├── helpers.py       (Git/沙箱/搜索/知识库)
  ├── editors.py       (文件编辑)
  ├── managers.py      (会话/片段/Todo/插件/统计)
  └── security.py      (安全检查)
```

### 运行方式（开发者）

```bash
cd maling
export DEEPSEEK_API_KEY="sk-xxx"
python main.py           # CLI 模式
python gui/main.py       # GUI 模式
```

### 注意事项

1. **循环依赖避免**：`print_typed` 从 `utils.py` 移入 `core.py`，避免 `session.py` ↔ `utils.py` 循环导入。
2. **类型注解安全**：所有文件顶部保留 `from __future__ import annotations`，跨模块类型引用使用字符串延迟求值。
3. **可选依赖降级**：`core.py` 统一检测可选依赖（colorama、pyyaml、python-dotenv、pyperclip、duckduckgo-search），其他模块通过 `core.py` 引用检测结果。

---

## 开源协议

MIT License — 欢迎 Fork、PR 和 Issue！

- 包内 `LICENSE` 为 MIT 许可证全文；版权行当前为占位写法 `Copyright (c) 2026 MaLing project contributors`，上传 GitHub / 对外分发前请把这一行改成你自己的署名，许可证正文不用动。
- 包内 `.gitignore` 已把 `config.yaml`（你的 API Key 所在）、`.env`、`dist/`、`build/`、`__pycache__/`、`*.pyc`、`*.spec.bak` 挡在版本库外，防止密钥随仓库泄露；请勿在开源仓库中存放任何真实密钥。
