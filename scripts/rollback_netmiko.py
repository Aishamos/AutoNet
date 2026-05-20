#!/usr/bin/env python3
"""
Netmiko 配置回滚脚本

功能：
- 通过 Netmiko 库直接 SSH 连接到华为设备
- 将备份配置文件中的命令逐行推送到设备
- 推送完成后自动执行 save 保存配置

适用场景：
- 配置漂移检测发现不一致后，将设备恢复到备份版本
- 配置下发出错后的紧急回滚

使用方式：
    python rollback_netmiko.py <设备别名> <备份文件路径>
    例如：python rollback_netmiko.py R1 backups/R1_20260507_153045.cfg

注意事项：
- 专为华为 VRP 系统（AR 路由器）适配
- global_delay_factor 设置为 2.0 以适配 eNSP 模拟器的响应速度
- cmd_verify=False 关闭命令验证以提高 eNSP 环境下的稳定性
"""
import sys
import os

# 导入 Netmiko 相关模块
try:
    from netmiko import ConnectHandler
    from netmiko.exceptions import NetmikoTimeoutException, NetmikoAuthenticationException
except ImportError:
    print("❌ 缺少 netmiko 模块，请执行: pip install netmiko")
    sys.exit(1)

# 导入公共工具模块
from utils import load_inventory


def main():
    """
    主函数：执行配置回滚。

    流程：
    1. 解析命令行参数（设备别名、备份文件路径）
    2. 从 inventory.yml 中读取设备连接信息
    3. 通过 Netmiko SSH 连接到设备
    4. 进入系统视图（enable）
    5. 读取备份文件，过滤注释和空行
    6. 使用 send_config_set 批量下发配置命令
    7. 执行 save 命令保存配置
    """
    # 检查命令行参数
    if len(sys.argv) != 3:
        sys.exit(1)

    device_alias = sys.argv[1]    # 设备别名（如 R1）
    backup_file = sys.argv[2]     # 备份文件路径（如 backups/R1_20260507_153045.cfg）

    # 从 inventory.yml 加载设备信息
    inventory = load_inventory()
    device_info = inventory.get('all', {}).get('hosts', {}).get(device_alias) if inventory else None
    if not device_info:
        print(f"❌ 找不到设备: {device_alias}")
        sys.exit(1)

    # 构造 Netmiko 连接参数
    netmiko_device = {
        'device_type': 'huawei',           # 华为设备类型（VRP 系统）
        'host': device_info.get('ansible_host'),     # 设备 IP
        'username': device_info.get('ansible_user'), # SSH 用户名
        'password': device_info.get('ansible_password'), # SSH 密码
        'port': 22,                          # SSH 端口
        'global_delay_factor': 2.0,          # 延迟系数，设大一些以适配 eNSP 模拟器
        'timeout': 30,                       # SSH 连接超时时间（秒）
    }

    print(f"🔄 正在连接到 {device_alias} ({netmiko_device['host']}) ...")

    try:
        with ConnectHandler(**netmiko_device) as net_connect:
            # 进入系统视图（华为设备的 enable 命令）
            net_connect.enable()

            print("✅ 已进入系统视图，正在处理备份文件...")
            with open(backup_file, 'r', encoding='utf-8') as f:
                # 读取备份文件，过滤掉注释行（# 开头）和空行
                config_commands = [line.strip() for line in f.readlines() if line.strip() and not line.startswith('#')]

            print(f"🚀 开始下发配置 ({len(config_commands)} 行)...")

            # 使用 send_config_set 批量下发配置命令
            # cmd_verify=False: eNSP 环境下关闭命令验证，避免因响应延迟导致超时
            # read_timeout=120: 设置较长的读取超时，防止大批量配置下发时超时
            output = net_connect.send_config_set(
                config_commands=config_commands,
                cmd_verify=False,
                read_timeout=120
            )

            print("💾 配置下发成功，正在执行保存...")
            # 华为 VRP 的 save 命令需要交互式确认
            # expect_string 匹配 "[Yy]/[Nn]" 提示符
            save_output = net_connect.send_command(
                "save",
                expect_string=r"[Yy]/[Nn]",
                read_timeout=30
            )
            # 如果出现确认提示，自动输入 "y"
            if 'y/n' in save_output.lower():
                net_connect.send_command("y", expect_string=r"<.*>", read_timeout=30)

            print("✨ 备份配置已成功推送到设备")
            sys.exit(0)

    except Exception as e:
        print(f"❌ 回滚过程发生错误: {str(e)}")

    sys.exit(1)


if __name__ == "__main__":
    main()
