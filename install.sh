#!/usr/bin/env bash
# 码铃（MaLing）— 一键安装脚本（macOS / Linux）
# 版本号从 core/__init__.py 的 __version__ 提取（单一来源），禁止再硬编码。
# 用法: chmod +x install.sh && ./install.sh

set -euo pipefail

# ─── 颜色定义 ──────────────────────────────────────────────
BOLD='\033[1m'
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'   # No Color

# ─── 路径 ──────────────────────────────────────────────────
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_DIR}/venv"
REQUIREMENTS="${PROJECT_DIR}/requirements_gui.txt"
PYTHON_CMD=""

# 版本号：从 core/__init__.py 文本级提取，保持单一来源
APP_VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "${PROJECT_DIR}/core/__init__.py" | head -n 1)"
APP_VERSION="${APP_VERSION:-1.0.0}"

# ─── 辅助函数 ──────────────────────────────────────────────
print_header() {
    echo ""
    echo -e "${CYAN}============================================${NC}"
    echo -e "${CYAN}   码铃 v${APP_VERSION} - 一键安装向导${NC}"
    echo -e "${CYAN}============================================${NC}"
    echo ""
}

print_success() { echo -e "${GREEN}[✓]${NC} $1"; }
print_info()    { echo -e "${BLUE}[i]${NC} $1"; }
print_warn()    { echo -e "${YELLOW}[!]${NC} $1"; }
print_error()   { echo -e "${RED}[X]${NC} $1"; }

print_python_missing() {
    echo ""
    echo -e "${RED}${BOLD}[X] Python 3.10+ 未检测到！${NC}"
    echo ""
    echo "码铃 v${APP_VERSION} 需要 Python 3.10 或更高版本才能运行。"
    echo ""
    echo "┌─────────────────────────────────────────────────┐"
    echo "│  请按以下步骤安装 Python：                       │"
    echo "│                                                 │"
    case "$(uname -s)" in
        Darwin)
            echo "│  macOS 推荐方式：                                │"
            echo "│    1. 安装 Homebrew: https://brew.sh             │"
            echo "│    2. 运行: brew install python@3.12             │"
            echo "│    3. 重新打开终端并再次运行此脚本               │"
            echo "│                                                 │"
            echo "│  或访问: https://www.python.org/downloads/macos/ │"
            ;;
        Linux)
            echo "│  Linux 推荐方式：                                │"
            echo "│    Ubuntu/Debian:                                │"
            echo "│      sudo apt update && sudo apt install -y      │"
            echo "│        python3.12 python3.12-venv python3-pip    │"
            echo "│                                                 │"
            echo "│    CentOS/RHEL/Fedora:                           │"
            echo "│      sudo dnf install python3.12 python3-pip     │"
            echo "│                                                 │"
            echo "│    Arch:                                         │"
            echo "│      sudo pacman -S python python-pip            │"
            ;;
    esac
    echo "│                                                 │"
    echo "│  通用方案: https://www.python.org/downloads/    │"
    echo "└─────────────────────────────────────────────────┘"
    echo ""
    echo -e "${YELLOW}按回车键退出...${NC}"
    read -r
    exit 1
}

# ─── 步骤 1: 检测 Python 3.10+ ─────────────────────────────
detect_python() {
    echo -e "${BOLD}[1/4]${NC} 正在检测 Python 环境..."

    local candidates=("python3.12" "python3.11" "python3.10" "python3" "python")
    local py_ver=""

    for cmd in "${candidates[@]}"; do
        if command -v "$cmd" &>/dev/null; then
            py_ver=$($cmd --version 2>&1 || true)
            if echo "$py_ver" | grep -Eq 'Python 3\.(1[0-9]|[2-9][0-9])'; then
                PYTHON_CMD="$cmd"
                print_info "发现 Python: $py_ver"
                return 0
            fi
        fi
    done

    print_python_missing
}

# ─── 步骤 2: 创建虚拟环境 ──────────────────────────────────
create_venv() {
    echo ""
    echo -e "${BOLD}[2/4]${NC} 正在创建虚拟环境..."

    if [[ -d "$VENV_DIR" ]]; then
        print_warn "检测到已有虚拟环境，跳过创建..."
    else
        "$PYTHON_CMD" -m venv "$VENV_DIR"
        if [[ $? -ne 0 ]]; then
            echo ""
            print_error "虚拟环境创建失败！"
            echo ""
            echo "可能的原因："
            echo "  - Python 的 venv 模块未安装"
            echo "  - 当前目录没有写入权限"
            echo "  - 磁盘空间不足"
            echo ""
            echo "请尝试以下解决方案："
            echo "  1. 运行: $PYTHON_CMD -m ensurepip --upgrade"
            echo "  2. 使用 sudo 或检查目录权限"
            echo "  3. 检查磁盘空间"
            echo ""
            echo -e "${YELLOW}按回车键退出...${NC}"
            read -r
            exit 1
        fi
        print_success "虚拟环境已创建: venv/"
    fi
}

# ─── 步骤 3: 安装依赖 ──────────────────────────────────────
install_deps() {
    echo ""
    echo -e "${BOLD}[3/4]${NC} 正在安装依赖（可能需要几分钟）..."
    print_info "依赖来源: requirements_gui.txt"
    echo ""

    local pip_cmd="${VENV_DIR}/bin/pip"

    # 先升级 pip
    "$pip_cmd" install --upgrade pip -q 2>/dev/null || print_warn "pip 升级失败，继续尝试安装..."

    # 安装依赖
    if ! "$pip_cmd" install -r "$REQUIREMENTS"; then
        echo ""
        print_error "依赖安装失败！"
        echo ""
        echo "可能的原因："
        echo "  - 网络连接问题（需访问 PyPI）"
        echo "  - requirements_gui.txt 文件缺失或损坏"
        echo "  - 某些依赖需要系统级编译工具"
        echo ""
        echo "请尝试以下解决方案："
        echo "  1. 检查网络连接，或更换 PyPI 镜像源："
        echo "     $pip_cmd install -r requirements_gui.txt -i https://pypi.tuna.tsinghua.edu.cn/simple"
        echo "  2. 单独安装 PySide6（体积最大，容易失败）："
        echo "     $pip_cmd install 'PySide6>=6.5'"
        echo "  3. 安装系统编译工具："
        case "$(uname -s)" in
            Darwin)
                echo "     xcode-select --install"
                ;;
            Linux)
                echo "     Ubuntu/Debian: sudo apt install build-essential"
                echo "     CentOS/RHEL:    sudo dnf groupinstall 'Development Tools'"
                ;;
        esac
        echo ""
        echo -e "${YELLOW}按回车键退出...${NC}"
        read -r
        exit 1
    fi

    print_success "依赖安装完成！"
}

# ─── 步骤 4: 完成提示 ──────────────────────────────────────
print_done() {
    echo ""
    echo -e "${BOLD}[4/4]${NC} 安装完成！"
    echo ""
    echo -e "${GREEN}============================================${NC}"
    echo -e "${GREEN}   安装成功！码铃 v${APP_VERSION} 已就绪${NC}"
    echo -e "${GREEN}============================================${NC}"
    echo ""
    echo "启动方式："
    echo ""
    echo "  方式 A —— 双击运行（推荐）："
    echo "    ./run.sh"
    echo ""
    echo "  方式 B —— 命令行启动 GUI："
    echo "    ./run.sh gui"
    echo ""
    echo "  方式 C —— 命令行启动 CLI："
    echo "    ./run.sh cli"
    echo ""
    echo "首次使用？"
    echo "  运行后会提示你设置 API Key（DeepSeek 等）。"
    echo "  也可以在项目目录下创建 .env 文件："
    echo "    DEEPSEEK_API_KEY=sk-your-key-here"
    echo ""
    echo "常用命令："
    echo "  /help    显示所有命令"
    echo "  /deep    切换深度思考模式"
    echo "  /code    进入编程模式"
    echo "  /save    保存当前会话"
    echo ""
    echo -e "${CYAN}============================================${NC}"
    echo ""
}

# ════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════
print_header
detect_python
create_venv
install_deps
print_done

exit 0
