#!/bin/bash
# ============================================
# NetAuto 网络自动化运维平台 - 部署脚本
# 适用环境：Ubuntu 24.04
# ============================================

set -e

echo "=========================================="
echo "  NetAuto 自动化运维平台 部署脚本"
echo "=========================================="

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 项目路径
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/venv"

# 检查是否为 root 用户
check_root() {
    if [ "$EUID" -eq 0 ]; then
        echo -e "${YELLOW}警告：建议使用普通用户运行此脚本，而非 root${NC}"
    fi
}

# 1. 安装系统依赖
install_system_deps() {
    echo ""
    echo ">>> [1/6] 安装系统依赖..."
    sudo apt update -qq
    sudo apt install -y -qq python3 python3-pip python3-venv sshpass git

    if command -v python3 &>/dev/null; then
        echo -e "${GREEN}✓ Python3 已安装: $(python3 --version)${NC}"
    else
        echo -e "${RED}✗ Python3 安装失败${NC}"
        exit 1
    fi
}

# 2. 创建虚拟环境
create_venv() {
    echo ""
    echo ">>> [2/6] 创建 Python 虚拟环境..."
    if [ -d "$VENV_DIR" ]; then
        echo -e "${YELLOW}虚拟环境已存在，跳过创建${NC}"
    else
        python3 -m venv "$VENV_DIR"
        echo -e "${GREEN}✓ 虚拟环境创建成功${NC}"
    fi
    source "$VENV_DIR/bin/activate"
}

# 3. 安装 Python 依赖
install_python_deps() {
    echo ""
    echo ">>> [3/6] 安装 Python 依赖..."
    pip install --upgrade pip -q
    pip install -q \
        flask \
        flask-socketio \
        eventlet \
        apscheduler \
        ansible \
        jinja2 \
        pyyaml \
        netmiko
    echo -e "${GREEN}✓ Python 依赖安装完成${NC}"
}

# 4. 初始化目录
init_dirs() {
    echo ""
    echo ">>> [4/6] 初始化项目目录..."
    mkdir -p "$PROJECT_DIR/backups"
    mkdir -p "$PROJECT_DIR/logs"
    mkdir -p "$PROJECT_DIR/exports"
    mkdir -p "$PROJECT_DIR/reports/inspection_report"
    mkdir -p "$PROJECT_DIR/reports/diff_report"
    mkdir -p "$PROJECT_DIR/scripts/logs/deploy_logs"
    mkdir -p "$PROJECT_DIR/scripts/logs/cron_logs"
    echo -e "${GREEN}✓ 目录结构初始化完成${NC}"
}

# 5. 配置 Ansible
config_ansible() {
    echo ""
    echo ">>> [5/6] 配置 Ansible..."
    # 安装华为设备集合
    ansible-galaxy collection install community.network -q 2>/dev/null || true
    ansible-galaxy collection install ansible.netcommon -q 2>/dev/null || true
    echo -e "${GREEN}✓ Ansible 配置完成${NC}"
}

# 6. 验证部署
verify_deploy() {
    echo ""
    echo ">>> [6/6] 验证部署..."
    cd "$PROJECT_DIR"

    # 检查关键文件
    local files=(
        "web/app.py"
        "inventory.yml"
        "ansible.cfg"
        "vault_pass.txt"
        "templates/acl.j2"
        "templates/vlan.j2"
        "templates/interface.j2"
    )

    local all_ok=true
    for f in "${files[@]}"; do
        if [ -f "$f" ]; then
            echo -e "  ${GREEN}✓${NC} $f"
        else
            echo -e "  ${RED}✗${NC} $f (缺失)"
            all_ok=false
        fi
    done

    if $all_ok; then
        echo -e "${GREEN}✓ 部署验证通过${NC}"
    else
        echo -e "${YELLOW}⚠ 部分文件缺失，请检查${NC}"
    fi
}

# 启动服务
start_service() {
    echo ""
    echo "=========================================="
    echo "  部署完成！"
    echo "=========================================="
    echo ""
    echo "启动命令："
    echo "  cd $PROJECT_DIR"
    echo "  source venv/bin/activate"
    echo "  python web/app.py"
    echo ""
    echo "访问地址：http://localhost:5000"
    echo ""
    echo "后台运行："
    echo "  nohup python web/app.py > /dev/null 2>&1 &"
    echo ""
    echo "停止服务："
    echo "  pkill -f 'python web/app.py'"
    echo ""
}

# 主流程
main() {
    check_root
    install_system_deps
    create_venv
    install_python_deps
    init_dirs
    config_ansible
    verify_deploy
    start_service
}

main "$@"
