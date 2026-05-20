#!/usr/bin/env python3
"""
配置下发模块（支持批量/单台、支持 CLI 和 Web API 传参）

功能概述：
- 将 Jinja2 模板渲染后的配置命令批量下发到网络设备
- 下发前自动备份当前配置（防止误操作无法回滚）
- 下发后自动备份新配置并保存到 Git
- 支持 CLI 交互模式和 Web API 非交互模式

工作流程：
1. 选择配置模板（acl.j2 / interface.j2 / vlan.j2）
2. 指定目标设备（单台 / 多台 / 全网）
3. 输入模板所需的变量值
4. 下发前备份当前配置 → 执行 Ansible Playbook 下发 → 下发后备份新配置
"""
import subprocess
import os
import sys
import json
import argparse
from datetime import datetime

# ============================================================
# 路径配置
# ============================================================

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 配置下发 Playbook 文件
PLAYBOOK_PATH = os.path.join(PROJECT_ROOT, "playbooks", "deploy_config.yml")

# Ansible 设备清单
INVENTORY_PATH = os.path.join(PROJECT_ROOT, "inventory.yml")

# Vault 密码文件
VAULT_PASS_FILE = os.path.join(PROJECT_ROOT, "vault_pass.txt")

# Jinja2 模板目录（存放 acl.j2、interface.j2、vlan.j2 等配置模板）
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, "templates")

# 备份脚本路径（下发前后调用备份功能）
BACKUP_SCRIPT = os.path.join(PROJECT_ROOT, "scripts", "backup_now.py")


def list_templates():
    """
    扫描模板目录，返回所有可用的 Jinja2 模板文件列表。

    返回:
        list[str]: 模板文件名列表（如 ['acl.j2', 'interface.j2', 'vlan.j2']）
        空列表: 模板目录不存在
    """
    if not os.path.exists(TEMPLATES_DIR):
        return []
    return [f for f in os.listdir(TEMPLATES_DIR) if f.endswith('.j2')]


def get_template_vars_interactive(template_name):
    """
    CLI 交互模式下，根据模板类型提示用户输入所需的变量值。

    不同模板需要不同的变量：
    - acl.j2: ACL 编号、规则 ID、源 IP、通配符掩码
    - interface.j2: 接口名、IP 地址、子网掩码
    - vlan.j2: VLAN ID、VLAN 描述

    参数:
        template_name: 模板文件名（如 'acl.j2'）

    返回:
        dict: 变量名到用户输入值的映射
    """
    vars_dict = {}
    print(f"\n📝 为模板 '{template_name}' 输入变量值：")
    if template_name == "acl.j2":
        vars_dict['acl_number'] = input("  ACL 编号 (如 3000): ").strip()
        vars_dict['rule_id'] = input("  规则 ID (如 5): ").strip()
        vars_dict['source_ip'] = input("  源 IP (如 192.168.1.0): ").strip()
        vars_dict['source_wildcard'] = input("  通配符掩码 (如 0.0.0.255): ").strip()
    elif template_name == "interface.j2":
        vars_dict['interface_name'] = input("  接口名 (如 GigabitEthernet0/0/1): ").strip()
        vars_dict['ip_address'] = input("  IP 地址 (如 10.1.1.1): ").strip()
        vars_dict['mask'] = input("  子网掩码 (如 255.255.255.0): ").strip()
    elif template_name == "vlan.j2":
        vars_dict['vlan_id'] = input("  VLAN ID (如 10): ").strip()
        vars_dict['vlan_description'] = input("  VLAN 描述 (可选): ").strip()
    return vars_dict


def run_pre_deploy_backup(target='all', api_mode=False):
    """
    下发前备份目标设备的当前运行配置。

    这是一个安全措施：在修改设备配置前先备份，万一出错可以回滚。
    调用 backup_now.py 脚本的 --target 参数，只备份即将被修改的设备。

    参数:
        target: 目标设备，默认 'all'
        api_mode: 是否为 API 模式。API 模式下失败不会弹出确认提示
    """
    print(f"\n📦 下发前备份 [{target}] 的当前运行配置...")
    result = subprocess.run([sys.executable, BACKUP_SCRIPT, '--target', target], cwd=PROJECT_ROOT, capture_output=api_mode)
    if result.returncode != 0:
        print("⚠️ 下发前备份失败！")
        if not api_mode:
            # CLI 模式下询问用户是否继续
            if input("是否继续下发？(y/N): ").strip().lower() != 'y':
                sys.exit(1)
    else:
        print("✅ 下发前备份完成")


def run_deploy(template_file, target_hosts, extra_vars_dict):
    """
    执行 Ansible Playbook 配置下发。

    通过 ansible-playbook 命令运行 deploy_config.yml，该 Playbook 会：
    1. 读取指定的 Jinja2 模板
    2. 使用传入的变量渲染模板，生成设备配置命令
    3. 通过 huawei.ce_config 模块将配置推送到目标设备
    4. 执行 save 命令保存配置

    参数:
        template_file: Jinja2 模板文件名（如 'interface.j2'）
        target_hosts: 目标设备（'all' 或设备别名，多台用逗号分隔）
        extra_vars_dict: 模板变量字典（如 {'interface_name': 'GE0/0/1', 'ip_address': '10.1.1.1'}）

    返回:
        bool: True 表示下发成功，False 表示下发失败
    """
    # 合并基础变量和用户自定义变量
    extra_vars = {
        "template_file": template_file,    # 模板文件名
        "target_hosts": target_hosts        # 目标设备
    }
    extra_vars.update(extra_vars_dict)     # 加入模板所需的具体变量

    cmd = [
        "ansible-playbook",
        "-i", INVENTORY_PATH,              # 设备清单
        PLAYBOOK_PATH,                      # Playbook 文件
        "--extra-vars", json.dumps(extra_vars),  # 以 JSON 格式传入所有变量
        "--vault-password-file", VAULT_PASS_FILE  # Vault 密码
    ]
    print(f"\n🚀 开始下发配置到 [{target_hosts}]...")
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    return result.returncode == 0


def main():
    """
    主入口函数，支持两种运行模式：

    1. API 模式（--api-mode）：由 Web 后端调用，所有参数通过命令行传入，无交互
    2. CLI 模式：交互式菜单，用户手动选择模板、输入变量、确认执行
    """
    os.chdir(PROJECT_ROOT)

    # 命令行参数解析
    parser = argparse.ArgumentParser()
    parser.add_argument('--template', help="模板文件名 (如 interface.j2)")
    parser.add_argument('--target', default='all', help="目标设备 (all 或 设备别名)")
    parser.add_argument('--vars', help="JSON 格式的模板变量")
    parser.add_argument('--api-mode', action='store_true', help="以 API 模式运行 (不出现 input 卡顿)")
    args = parser.parse_args()

    # ==================== API 模式 ====================
    # 由 Web 后端（api_deploy.py）调用，跳过所有交互式输入
    if args.api_mode:
        if not args.template:
            print("❌ API 模式下必须提供 --template 参数")
            sys.exit(1)
        # 解析 JSON 格式的模板变量
        vars_dict = json.loads(args.vars) if args.vars else {}
        # 下发前备份
        run_pre_deploy_backup(target=args.target, api_mode=True)
        # 执行下发
        success = run_deploy(args.template, args.target, vars_dict)
        if success:
            print("\n✅ 配置下发完成")
            # 下发成功后自动备份新配置
            print("📦 下发后备份新配置...")
            subprocess.run([sys.executable, BACKUP_SCRIPT, '--target', args.target], capture_output=True)
            sys.exit(0)
        else:
            print("\n❌ 配置下发失败")
            sys.exit(1)

    # ==================== CLI 交互模式 ====================
    # 显示模板列表供用户选择
    templates = list_templates()
    if not templates:
        print("❌ 没有可用的模板文件")
        return

    print("\n📂 可用配置模板：")
    for idx, tpl in enumerate(templates, 1):
        print(f"  {idx}. {tpl}")
    choice = input("请选择模板编号: ").strip()
    try:
        template_file = templates[int(choice) - 1]
    except (ValueError, IndexError):
        print("❌ 无效的选择")
        return

    # 输入目标设备
    target = input("\n🎯 请输入目标设备别名 (直接回车表示下发给 all 全网设备): ").strip()
    target_hosts = target if target else 'all'

    # 根据模板类型收集变量
    vars_dict = get_template_vars_interactive(template_file)

    # 确认执行
    print(f"\n📋 即将把模板 [{template_file}] 下发至 [{target_hosts}]")
    confirm = input("确认执行？(y/N): ").strip().lower()
    if confirm != 'y': return

    # 执行下发流程：备份 → 下发 → 备份
    run_pre_deploy_backup(target=target_hosts)
    if run_deploy(template_file, target_hosts, vars_dict):
        print("\n✅ 配置下发完成")
        print("📦 下发后备份新配置...")
        subprocess.run([sys.executable, BACKUP_SCRIPT, '--target', target_hosts])
    else:
        print("\n❌ 配置下发失败")


if __name__ == "__main__":
    main()
