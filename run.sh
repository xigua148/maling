#!/usr/bin/env bash
# 码铃（MaLing）— 启动脚本（macOS / Linux）
# 版本号从 core/__init__.py 的 __version__ 提取（单一来源），禁止再硬编码。
# 用法:
#   ./run.sh       启动 GUI 模式（默认）
#   ./run.sh gui   启动 GUI 模式
#   ./run.sh cli   启动 CLI 模式

set -euo pipefail

# ─── 颜色 ──────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ─── 路径 ──────────────────────────────────────────────────
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_DIR}/venv"
VENV_PYTHON="${VENV_DIR}/bin/python"

# 版本号：从 core/__init__.py 文本级提取，保持单一来源
APP_VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "${PROJECT_DIR}/core/__init__.py" | head -n 1)"
APP_VERSION="${APP_VERSION:-1.0.0}"

# ─── 检查虚拟环境 ──────────────────────────────────────────
if [[ ! -f "$VENV_PYTHON" ]]; then
    echo ""
    echo -e "${RED}[X] 虚拟环境未找到！${NC}"
    echo ""
    echo "请先运行安装脚本："
    echo "    ./install.sh"
    echo ""
    echo "或者手动安装依赖："
    echo "    python3 -m venv venv"
    echo "    venv/bin/pip install -r requirements_gui.txt"
    echo ""
    exit 1
fi

# ─── 解析模式参数 ──────────────────────────────────────────
MODE="gui"
case "${1:-gui}" in
    cli|--cli|-c)
        MODE="cli"
        ;;
    gui|--gui|-g|"")
        MODE="gui"
        ;;
esac

echo ""
echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}   码铃 v${APP_VERSION} 启动中...${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

cd "$PROJECT_DIR"

if [[ "$MODE" == "cli" ]]; then
    echo -e "${BLUE}[模式]${NC} CLI（命令行）"
    echo -e "${BLUE}[入口]${NC} main.py"
    echo ""
    "$VENV_PYTHON" main.py
else
    echo -e "${BLUE}[模式]${NC} GUI（图形界面）"
    echo -e "${BLUE}[入口]${NC} gui/main.py"
    echo ""
    "$VENV_PYTHON" gui/main.py
fi

exit_code=$?

# ─── 异常退出提示 ──────────────────────────────────────────
if [[ $exit_code -ne 0 ]]; then
    echo ""
    echo -e "${RED}[X] 程序异常退出（退出码 $exit_code）${NC}"
    echo ""
    echo "可能的原因："
    echo "  - 缺少 API Key（首次运行需配置）"
    echo "  - 依赖未正确安装"
    echo "  - 端口冲突或其他运行时错误"
    echo ""
    echo "建议操作："
    echo "  1. 检查 config.yaml 或 .env 中的 API Key 配置"
    echo "  2. 重新运行 ./install.sh 安装依赖"
    echo "  3. 查看上方错误信息排查问题"
    echo ""
fi

exit $exit_code
