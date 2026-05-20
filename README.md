# NetAuto - 网络设备自动化运维平台

基于 Python + Ansible 的网络设备自动化运维工具，提供 Web 图形化界面，支持设备管理、配置备份、批量下发、配置校验与回滚、全网监控报告等功能。

## 功能特性

| 模块 | 功能 |
|------|------|
| 设备信息管理 | 设备增删改查、连通性验证、多条件筛选、清单导入导出 |
| 配置自动备份 | 手动备份、Cron 定时备份、备份文件下载 |
| 批量配置下发 | Jinja2 模板化下发（ACL/VLAN/接口）、逐设备状态反馈 |
| 配置校验与回滚 | 漂移检测、差异报告、一键回滚、操作历史记录 |
| 全网监控报告 | 设备状态采集、告警汇总、巡检建议、报告生成下载 |
| 实时监控 | WebSocket 实时推送设备在线状态 |

## 技术栈

- **后端**: Python 3.11 + Flask 3.x + Flask-SocketIO
- **前端**: Bootstrap 5 + JavaScript
- **自动化**: Ansible 2.16+ + Jinja2
- **设备交互**: Netmiko + Ansible CLI
- **实验环境**: 华为 eNSP 模拟器（AR 系列路由器）

## 环境要求

- Ubuntu 24.04
- Python 3.11+
- Ansible 2.16+
- Flask 3.x
- SSH 连接到网络设备

## 快速部署

```bash
# 1. 克隆项目
git clone <项目地址>
cd Autonet

# 2. 执行部署脚本
chmod +x deploy.sh
./deploy.sh

# 3. 启动服务
source venv/bin/activate
python web/app.py
```

访问 `http://localhost:5000` 进入系统。

## 手动部署

```bash
# 1. 安装系统依赖
sudo apt update
sudo apt install -y python3 python3-pip python3-venv sshpass

# 2. 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 3. 安装 Python 依赖
pip install flask>=3.0 flask-socketio eventlet apscheduler ansible>=2.16 jinja2 pyyaml netmiko

# 4. 安装 Ansible 集合
ansible-galaxy collection install community.network
ansible-galaxy collection install ansible.netcommon

# 5. 初始化目录
mkdir -p backups logs reports/inspection_report reports/diff_report

# 6. 配置设备清单
# 编辑 inventory.yml，添加设备信息
# 确保 vault_pass.txt 存在

# 7. 启动服务
python web/app.py
```

## 项目结构

```
Autonet/
├── ansible.cfg                # Ansible 配置
├── inventory.yml              # 设备清单（Vault 加密）
├── vault_pass.txt             # Vault 解密密码
├── deploy.sh                  # 部署脚本
├── README.md                  # 项目说明
│
├── web/                       # Web 应用
│   ├── __init__.py            # 包初始化
│   ├── app.py                 # Flask 主入口
│   ├── api_inventory.py       # 设备管理 API
│   ├── api_backup.py          # 备份 API
│   ├── api_deploy.py          # 下发 API
│   ├── api_check_rollback.py  # 校验回滚 API
│   ├── api_report.py          # 报告 API
│   ├── api_logs.py            # 日志 API
│   ├── api_status.py          # 状态 API
│   ├── api_drift_history.py   # 漂移历史 API
│   └── templates/             # HTML 页面
│       ├── base.html          # 基础模板（侧边栏/导航/公共样式）
│       ├── login.html
│       ├── dashboard.html
│       ├── inventory.html
│       ├── backup.html
│       ├── deploy.html
│       ├── rollback.html
│       └── report.html
│
├── playbooks/                 # Ansible Playbook
│   ├── backup_config.yml      # 备份 Playbook
│   ├── deploy_config.yml      # 下发 Playbook
│   └── get_current_config.yml # 获取当前配置
│
├── scripts/                   # Python 脚本
│   ├── __init__.py            # 包初始化
│   ├── utils.py               # 公共工具模块（inventory 加密加载/Ping/备份查询等）
│   ├── generate_report.py     # 报告生成
│   ├── config_check.py        # 配置校验
│   ├── backup_now.py          # 备份脚本
│   ├── deploy_now.py          # 下发脚本
│   ├── manage_inventory.py    # 清单管理
│   ├── rollback_netmiko.py    # 回滚脚本
│   ├── logs_manager.py        # 日志管理
│   └── monitor.py             # 监控脚本
│
├── templates/                 # Jinja2 配置模板
│   ├── acl.j2                 # ACL 配置模板
│   ├── vlan.j2                # VLAN 配置模板
│   ├── interface.j2           # 接口配置模板
│   └── report_template.html   # 报告 HTML 模板
│
├── backups/                   # 配置备份文件
├── logs/                      # 日志文件
├── reports/                   # 报告文件
│   ├── inspection_report/     # 巡检报告
│   └── diff_report/           # 差异报告
└── exports/                   # 清单导出文件
```

## 使用说明

### 1. 添加设备

进入"设备信息管理"页面，输入设备别名、IP、用户名、密码，点击"添加"。系统会自动验证设备连通性。

### 2. 配置备份

进入"配置自动备份"页面：
- 点击"立即备份"手动触发备份
- 设置 Cron 表达式配置定时备份（如 `0 2 * * *` 每天凌晨2点）

### 3. 配置下发

进入"批量配置下发"页面：
- 选择目标设备
- 选择配置模板（ACL/VLAN/接口）
- 填写模板变量
- 点击"执行下发"

### 4. 配置校验

进入"配置校验与回滚"页面：
- 选择设备，点击"开始检测"
- 查看差异报告
- 如需回滚，点击"一键回滚"

### 5. 监控报告

进入"全网监控报告"页面：
- 点击"生成报告"
- 按日期筛选历史报告
- 下载 HTML 格式报告

## 后台运行

```bash
# 使用 nohup 后台运行
nohup python web/app.py > /dev/null 2>&1 &

# 查看进程
ps aux | grep "python web/app.py"

# 停止服务
pkill -f "python web/app.py"
```

## 常见问题

**Q: 设备添加失败，提示连通性验证失败？**
A: 检查设备 IP 是否可达，SSH 服务是否开启，用户名密码是否正确。

**Q: 备份文件为空？**
A: 检查设备是否在线，vault_pass.txt 是否正确。

**Q: 配置下发失败？**
A: 检查模板变量是否填写完整，设备是否在线。

## 许可证

本项目仅供学习和毕业设计使用。
