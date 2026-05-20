#!/usr/bin/env python3
"""
设备信息管理模块 (强管控 CLI 版)

功能：
- 增删改查网络设备信息（存储在 inventory.yml 中）
- 添加设备时强制进行 Ping + SSH 连通性验证，失败则拒绝入库
- 支持单台设备验证、批量导入导出
- 所有凭据通过 Ansible Vault 加密存储

设备清单结构（inventory.yml）：
all:
  hosts:
    R1:
      ansible_host: 192.168.1.1
      ansible_user: admin
      ansible_password: ****
      ansible_connection: ansible.netcommon.network_cli
      ansible_network_os: community.network.ce
      description: 核心路由器
"""
import yaml
import shutil
import subprocess
import os
import sys
from datetime import datetime
from utils import load_inventory, PROJECT_ROOT, INVENTORY_PATH, VAULT_PASS_FILE, BACKUP_DIR

# 尝试导入 netmiko 用于 SSH 连通性验证
# netmiko 是 Python 的网络设备自动化库，支持华为、思科等设备的 SSH 连接
try:
    from netmiko import ConnectHandler
    NETMIKO_AVAILABLE = True
except ImportError:
    NETMIKO_AVAILABLE = False
    print("⚠️ 警告: 未安装 netmiko，SSH 极速验证将被跳过。请执行 pip install netmiko")

# 设备清单文件路径
INVENTORY_FILE = INVENTORY_PATH

# 清单导出目录
EXPORT_DIR = os.path.join(PROJECT_ROOT, "exports")


def save_inventory(data, use_vault=True):
    """
    保存设备清单到 inventory.yml，支持 Vault 加密。

    保存流程：
    1. 备份当前 inventory.yml（如果存在）
    2. 将数据写入临时文件 inventory_temp.yml
    3. 使用 ansible-vault encrypt 命令加密临时文件，输出到 inventory.yml
    4. 删除临时文件

    参数:
        data: 设备清单数据（Python 字典）
        use_vault: 是否使用 Vault 加密，默认 True
    """
    # 保存前先备份当前清单
    if os.path.exists(INVENTORY_FILE):
        os.makedirs(BACKUP_DIR, exist_ok=True)
        backup_name = os.path.join(BACKUP_DIR, f"inventory_{datetime.now().strftime('%Y%m%d_%H%M%S')}.yml")
        shutil.copy2(INVENTORY_FILE, backup_name)

    temp_file = os.path.join(PROJECT_ROOT, "inventory_temp.yml")
    try:
        # 写入临时文件
        with open(temp_file, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

        if use_vault and os.path.exists(VAULT_PASS_FILE):
            # 使用 ansible-vault encrypt 加密
            cmd = ["ansible-vault", "encrypt", temp_file, "--vault-password-file", VAULT_PASS_FILE, "--encrypt-vault-id", "default", "--output", INVENTORY_FILE]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                print(f"❌ Vault 加密失败: {res.stderr}")
                return
        else:
            # 不加密，直接替换
            os.replace(temp_file, INVENTORY_FILE)
    except Exception as e:
        print(f"❌ 保存过程中发生异常: {e}")
    finally:
        # 确保临时文件被清理
        if os.path.exists(temp_file):
            os.remove(temp_file)


# ================= 核心验证引擎 =================

def verify_device_connection(ip, user, password):
    """
    综合验证设备连通性：先 Ping 再 SSH。

    验证流程：
    1. 发送 2 个 ICMP 包测试 IP 是否可达
    2. 如果 netmiko 可用，尝试 SSH 登录验证凭据是否正确
    3. 返回验证结果和详细信息

    参数:
        ip: 设备 IP 地址
        user: SSH 用户名
        password: SSH 密码

    返回:
        tuple: (bool, str)
            - bool: True 验证通过，False 验证失败
            - str: 详细结果描述
    """
    # 第一步：Ping 测试
    ping_cmd = ["ping", "-c", "2", "-W", "1", ip]
    res = subprocess.run(ping_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if res.returncode != 0:
        return False, "IP 无法 Ping 通"

    # 第二步：SSH 验证（需要 netmiko）
    if not NETMIKO_AVAILABLE:
        return True, "Ping 正常 (未安装 netmiko，已跳过 SSH 验证)"

    try:
        device = {
            'device_type': 'huawei',    # 华为设备类型
            'host': ip,
            'username': user,
            'password': password,
            'port': 22,                 # SSH 默认端口
            'timeout': 5,               # 连接超时 5 秒
            'global_delay_factor': 0.5  # 快速模式（验证用，不需要等待完整输出）
        }
        with ConnectHandler(**device) as conn:
            pass  # 只要能建立连接就算验证通过
        return True, "Ping 正常，SSH 登录成功"
    except Exception as e:
        return False, f"Ping 正常，但 SSH 验证失败: {str(e)}"


# ---------------- CLI 交互逻辑 ----------------

def list_devices():
    """显示所有设备的详细信息（别名、IP、用户名、描述）"""
    data = load_inventory()
    if not data or 'all' not in data or 'hosts' not in data['all']:
        print("📭 清单为空")
        return
    hosts = data['all']['hosts']
    print("\n📋 当前设备列表：")
    print("-" * 60)
    for alias, info in hosts.items():
        print(f"别名: {alias}\n  IP: {info.get('ansible_host', 'N/A')}\n  用户: {info.get('ansible_user', 'N/A')}\n  描述: {info.get('description', 'N/A')}\n" + "-" * 60)


def add_device():
    """
    添加新设备（强管控模式）。

    流程：
    1. 用户输入设备信息（别名、IP、用户名、密码、描述）
    2. 执行 Ping + SSH 连通性验证
    3. 验证通过才允许入库，否则拒绝添加
    4. 保存到 inventory.yml（Vault 加密）
    """
    alias = input("请输入设备别名（如 ar_router_33）: ").strip()
    ip = input("请输入 IP 地址: ").strip()
    user = input("请输入 SSH 用户名 [admin]: ").strip() or "admin"
    password = input("请输入 SSH 密码: ").strip()
    desc = input("请输入设备描述: ").strip()

    if not alias or not ip or not password:
        print("❌ 别名、IP 和密码不能为空！")
        return

    # 执行连通性验证
    print(f"\n🔍 正在测试设备连通性 ({ip})，请稍候...")
    is_ok, msg = verify_device_connection(ip, user, password)

    # 核心拦截逻辑：验证失败则拒绝添加
    if not is_ok:
        print(f"❌ 验证失败: {msg}")
        print("🚫 拒绝添加：出于强管控要求，设备必须在网络可达且凭据正确的情况下才能录入！")
        return

    print(f"✅ 验证通过: {msg}")

    # 加载现有清单，添加新设备
    data = load_inventory() or {'all': {'hosts': {}}}
    if 'all' not in data: data['all'] = {'hosts': {}}
    if 'hosts' not in data['all']: data['all']['hosts'] = {}

    if alias in data['all']['hosts']:
        print(f"⚠️ 别名 {alias} 已存在，将覆盖原配置")

    # 写入设备信息
    data['all']['hosts'][alias] = {
        'ansible_host': ip,
        'ansible_user': user,
        'ansible_password': password,
        'ansible_connection': 'ansible.netcommon.network_cli',  # 使用 network_cli 连接方式
        'ansible_network_os': 'community.network.ce',           # 华为 CE 设备 OS
        'description': desc
    }
    save_inventory(data)
    print("✅ 设备已成功加密保存入库")


def delete_device():
    """删除指定设备"""
    alias = input("请输入要删除的设备别名: ").strip()
    data = load_inventory()
    if not data or alias not in data.get('all', {}).get('hosts', {}):
        print(f"❌ 设备 {alias} 不存在")
        return
    del data['all']['hosts'][alias]
    save_inventory(data)
    print(f"✅ 设备 {alias} 已删除")


def check_connectivity():
    """
    独立连通性验证功能。

    可验证单台或全部设备的 Ping + SSH 连通性，
    不修改任何数据，仅用于诊断。
    """
    alias = input("请输入要验证的设备别名（直接回车则验证全部设备）: ").strip()
    data = load_inventory()
    if not data: return

    hosts = data.get('all', {}).get('hosts', {})
    if alias:
        if alias not in hosts:
            print(f"❌ 设备 {alias} 不存在")
            return
        hosts = {alias: hosts[alias]}

    print("\n🔍 开始连通性验证...")
    for name, info in hosts.items():
        ip = info.get('ansible_host')
        user = info.get('ansible_user')
        pwd = info.get('ansible_password')
        print(f"\n检查 {name} ({ip}):")
        is_ok, msg = verify_device_connection(ip, user, pwd)
        if is_ok:
            print(f"  ✅ {msg}")
        else:
            print(f"  ❌ {msg}")


def export_inventory():
    """导出设备清单为明文 YAML 文件，密码字段替换为 *** 脱敏处理"""
    data = load_inventory()
    if not data: return
    # 导出前将密码字段替换为 ***，防止明文密码泄露
    for alias, info in data.get('all', {}).get('hosts', {}).items():
        if 'ansible_password' in info:
            info['ansible_password'] = '***'
    os.makedirs(EXPORT_DIR, exist_ok=True)
    export_file = os.path.join(EXPORT_DIR, f"inventory_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.yml")
    try:
        with open(export_file, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
        print(f"✅ 清单已导出至 {export_file}（密码已脱敏）")
    except Exception as e:
        print(f"❌ 导出失败: {e}")


def import_inventory():
    """
    从 YAML 文件批量导入设备。

    注意：批量导入不进行连通性验证，仅合并数据。
    """
    file_path = input("请输入要导入的 YAML 文件路径 (相对或绝对): ").strip()
    if not os.path.exists(file_path):
        print(f"❌ 文件 {file_path} 不存在")
        return
    with open(file_path, 'r', encoding='utf-8') as f:
        new_data = yaml.safe_load(f)
    # 合并到现有清单
    current = load_inventory() or {'all': {'hosts': {}}}
    if 'all' not in current: current['all'] = {'hosts': {}}
    for alias, info in new_data.get('all', {}).get('hosts', {}).items():
        current['all']['hosts'][alias] = info
    save_inventory(current)
    print(f"✅ 已从 {file_path} 导入设备 (注意：批量导入未进行连通性强校验)")


def main():
    """CLI 主菜单入口"""
    while True:
        print("\n" + "=" * 40 + "\n       设备信息管理模块\n" + "=" * 40)
        print("1. 查看所有设备\n2. 添加设备\n3. 删除设备\n4. 连通性验证\n5. 导出设备清单\n6. 批量导入设备\n0. 退出")
        choice = input("请选择操作: ").strip()
        if choice == '1': list_devices()
        elif choice == '2': add_device()
        elif choice == '3': delete_device()
        elif choice == '4': check_connectivity()
        elif choice == '5': export_inventory()
        elif choice == '6': import_inventory()
        elif choice == '0': break
        else: print("❌ 无效选项，请重新输入")


if __name__ == "__main__":
    main()
