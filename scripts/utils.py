#!/usr/bin/env python3
"""
公共工具模块：统一提供 inventory 解密加载、Ping 检测、备份文件查询、JSON 文件初始化等基础功能。
所有 scripts/ 和 web/ 下的模块应优先导入此模块，避免重复实现。
"""
import os
import glob
import json
import subprocess
import yaml

# ============================================================
# 路径常量定义
# 通过当前文件位置向上推导项目根目录，确保在任何工作目录下都能正确找到项目文件
# ============================================================

# 项目根目录：scripts/ 的上一级目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Ansible 设备清单文件（YAML 格式，经 Ansible Vault 加密存储）
INVENTORY_PATH = os.path.join(PROJECT_ROOT, "inventory.yml")

# Ansible Vault 密码文件（明文存储解密密码，供 ansible-vault 命令使用）
VAULT_PASS_FILE = os.path.join(PROJECT_ROOT, "vault_pass.txt")

# 设备配置备份存储目录（每个设备的备份文件以 设备别名_时间戳.cfg 命名）
BACKUP_DIR = os.path.join(PROJECT_ROOT, "backups")


def load_inventory(use_vault=True):
    """
    解密并加载 inventory.yml，返回解析后的 dict，失败返回 None。

    工作流程：
    1. 检查 inventory.yml 是否存在
    2. 如果 use_vault=True 且密码文件存在，调用 ansible-vault view 命令解密
    3. 否则直接读取明文 YAML 文件
    4. 使用 yaml.safe_load 解析 YAML 内容为 Python 字典

    参数:
        use_vault: 是否使用 Vault 解密，默认 True。设为 False 则直接读取明文文件

    返回:
        dict: 解析后的设备清单数据，典型结构为 {'all': {'hosts': {'设备别名': {...}}}}
        None: 文件不存在或解密/解析失败
    """
    if not os.path.exists(INVENTORY_PATH):
        return None
    if use_vault and os.path.exists(VAULT_PASS_FILE):
        # 调用 ansible-vault view 命令解密文件内容到 stdout
        cmd = ["ansible-vault", "view", INVENTORY_PATH, "--vault-password-file", VAULT_PASS_FILE]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"❌ Vault 解密失败: {res.stderr}")
            return None
        content = res.stdout
    else:
        with open(INVENTORY_PATH, 'r', encoding='utf-8') as f:
            content = f.read()
    try:
        return yaml.safe_load(content)
    except yaml.YAMLError as e:
        print(f"❌ YAML 解析失败: {e}")
        return None


def get_decrypted_devices():
    """
    解密 inventory 并返回简化的设备列表。

    从 inventory.yml 中提取所有设备的别名和 IP 地址，返回统一格式的列表。
    供前端 API（如设备状态检测、设备列表展示）调用。

    返回:
        list[dict]: 设备列表，每项包含 {'alias': '设备别名', 'ip': 'IP地址'}
        空列表: 解密失败或无设备
    """
    data = load_inventory()
    if not data:
        return []
    hosts = data.get('all', {}).get('hosts', {})
    return [{"alias": name, "ip": info.get('ansible_host')} for name, info in hosts.items()]


def ping_check(ip, count=1, timeout=1):
    """
    ICMP 连通性检测，用于判断设备是否在线。

    使用系统 ping 命令发送 ICMP 包，通过返回码判断目标是否可达。
    适用于 Linux 部署环境（Windows 的 ping 参数不同）。

    参数:
        ip: 目标设备 IP 地址
        count: 发送 ICMP 包的数量，默认 1
        timeout: 每次探测的超时时间（秒），默认 1

    返回:
        bool: True 表示设备在线（ping 通），False 表示设备离线
    """
    cmd = ["ping", "-c", str(count), "-W", str(timeout), ip]
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return res.returncode == 0


def list_backups_for_device(device_alias):
    """
    获取某台设备的所有备份文件列表，按修改时间倒序排列。

    备份文件命名规则：{设备别名}_{时间戳}.cfg
    例如：R1_20260507_153045.cfg

    参数:
        device_alias: 设备别名（如 'R1'）

    返回:
        list[str]: 备份文件的完整路径列表，最新的在前
    """
    pattern = os.path.join(BACKUP_DIR, f"{device_alias}_*.cfg")
    files = glob.glob(pattern)
    files.sort(key=os.path.getmtime, reverse=True)
    return files


def get_latest_backup(device_alias):
    """
    获取某台设备的最新备份文件路径。

    参数:
        device_alias: 设备别名（如 'R1'）

    返回:
        str: 最新备份文件的完整路径
        None: 该设备没有备份文件
    """
    files = list_backups_for_device(device_alias)
    return files[0] if files else None


def ensure_json_file(filepath):
    """
    确保 JSON 文件及其父目录存在，不存在则初始化为空列表 []。

    用于日志文件、操作记录等 JSON 存储场景，避免首次读取时文件不存在报错。
    会自动创建缺失的目录结构。

    参数:
        filepath: JSON 文件的完整路径
    """
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    if not os.path.exists(filepath):
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump([], f)
