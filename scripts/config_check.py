#!/usr/bin/env python3
"""
配置校验与回滚模块 (API 适配版)

功能概述：
- 检测设备当前运行配置与最新备份是否一致（配置漂移检测）
- 对有漂移的设备生成 HTML 格式的差异报告
- 支持将设备配置回滚到指定的历史备份版本
- 支持 CLI 交互模式和 Web API 非交互模式

配置漂移（Drift）：指设备的当前运行配置与最后一次备份的配置不一致，
可能是人为手动修改、未记录的变更等原因导致，需要及时发现和处理。
"""
import subprocess
import os
import sys
import difflib
import argparse
import json
from datetime import datetime
from utils import load_inventory, list_backups_for_device, get_latest_backup, PROJECT_ROOT, INVENTORY_PATH, VAULT_PASS_FILE, BACKUP_DIR

# 解决 Linux 终端下 input() 无法使用退格键删除的问题
# readline 模块能让 input() 支持行编辑功能（退格、方向键等）
try:
    import readline
except ImportError:
    pass

# 差异报告输出目录
REPORT_DIR = os.path.join(PROJECT_ROOT, "reports", "diff_report")

# 获取设备当前配置的 Playbook
PLAYBOOK_GET_CURRENT = os.path.join(PROJECT_ROOT, "playbooks", "get_current_config.yml")

# 确保报告目录存在
os.makedirs(REPORT_DIR, exist_ok=True)


def get_device_current_config(device_alias):
    """
    通过 Ansible ad-hoc 命令获取设备的当前运行配置。

    使用 ansible.netcommon.cli_command 模块执行 'display current-configuration' 命令，
    从返回的 JSON 结果中提取 stdout 字段（即配置文本内容）。

    参数:
        device_alias: 设备别名（如 'R1'）

    返回:
        str: 设备当前运行配置的文本内容
        None: 获取失败（设备不可达或命令执行出错）
    """
    cmd = [
        "ansible", device_alias,                    # 目标设备
        "-i", INVENTORY_PATH,                        # 设备清单
        "-m", "ansible.netcommon.cli_command",       # 使用 cli_command 模块
        "-a", "command='display current-configuration'",  # 执行的命令
        "--vault-password-file", VAULT_PASS_FILE,    # Vault 密码
        "-o"                                         # 输出单行格式
    ]
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    # 解析 Ansible 输出，提取设备返回的配置内容
    for line in result.stdout.strip().split('\n'):
        if '| SUCCESS =>' in line:
            json_part = line.split('=>', 1)[1].strip()
            try:
                data = json.loads(json_part)
                return data.get('stdout', '')
            except json.JSONDecodeError:
                pass
    return result.stdout


def generate_diff_report(device_alias, backup_file, current_config):
    """
    生成 HTML 格式的配置差异报告。

    使用 Python 标准库 difflib.HtmlDiff 对比备份配置和当前配置，
    生成可视化的 HTML 差异页面，新增/删除/修改的行会高亮显示。

    参数:
        device_alias: 设备别名
        backup_file: 备份文件路径
        current_config: 当前运行配置文本

    返回:
        str: 生成的报告文件名（不含路径），供前端下载链接使用
    """
    # 读取备份文件内容
    with open(backup_file, 'r', encoding='utf-8') as f:
        backup_config = f.read()
    backup_lines = backup_config.splitlines()
    current_lines = current_config.splitlines()

    # 使用 difflib 生成 HTML 差异表格
    diff = difflib.HtmlDiff().make_file(
        backup_lines, current_lines,
        fromdesc=f"备份文件: {os.path.basename(backup_file)}",   # 左侧标题
        todesc=f"当前运行配置 ({device_alias})",                   # 右侧标题
        context=False, numlines=0   # 显示完整差异，不限制上下文行数
    )
    # 自定义样式：隐藏多余表格、统一差异行背景色
    custom_style = """
    <style>
        table.diff + table, table.diff ~ br, body > br, hr { display: none !important; }
        .diff_add, .diff_sub, .diff_chg { background-color: #ffcccc !important; }
        .diff_add span, .diff_sub span, .diff_chg span { background-color: #ffcccc !important; }
    </style>
    """
    diff = diff.replace('</head>', custom_style + '</head>') if '</head>' in diff else custom_style + diff
    # 生成带时间戳的报告文件名
    report_name = f"diff_{device_alias}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    report_path = os.path.join(REPORT_DIR, report_name)
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(diff)
    print(f"📊 完整差异报告已生成: {report_path}")
    return report_name


def check_drift(device_alias=None):
    """
    检测设备配置漂移。

    逐台设备获取当前运行配置，与最新备份文件进行文本对比。
    如果内容不一致则标记为"漂移"，并生成差异报告。

    参数:
        device_alias: 设备别名，支持以下格式：
            - None 或 'all': 检测所有设备
            - 单个设备名: 'R1'
            - 逗号分隔多台: 'R1,R2,R3'

    返回:
        list[dict]: 检测结果列表，每项包含：
            - device: 设备别名
            - status: 'ok'(一致) / 'drift'(漂移) / 'error'(获取失败) / 'no_backup'(无备份)
            - report: 差异报告文件名（仅 status='drift' 时有值）
    """
    inventory = load_inventory()
    if not inventory: return []
    devices = list(inventory.get('all', {}).get('hosts', {}).keys())

    # 解析目标设备列表
    if not device_alias or device_alias == 'all':
        target_devices = devices
    elif ',' in device_alias:
        target_devices = [d.strip() for d in device_alias.split(',')]
    else:
        target_devices = [device_alias]
    drift_found = False
    results = []

    # 逐台检测
    for dev in target_devices:
        print(f"\n🔍 检查设备 {dev} ...")
        # 获取设备当前配置
        current = get_device_current_config(dev)
        if current is None:
            print(f"❌ 无法获取设备 {dev} 的当前配置")
            results.append({"device": dev, "status": "error", "report": None})
            continue
        # 获取最新备份
        latest_backup = get_latest_backup(dev)
        if not latest_backup:
            print(f"⚠️ 设备 {dev} 没有备份文件，无法对比")
            results.append({"device": dev, "status": "no_backup", "report": None})
            continue

        # 读取备份内容进行对比
        with open(latest_backup, 'r', encoding='utf-8') as f:
            backup_content = f.read()

        if current.strip() != backup_content.strip():
            # 配置不一致，存在漂移
            print(f"⚠️ 警告：设备 {dev} 存在配置漂移！")
            drift_found = True
            report_name = generate_diff_report(dev, latest_backup, current)
            results.append({"device": dev, "status": "drift", "report": report_name})
        else:
            # 配置一致
            print(f"✅ 设备 {dev} 配置与最新备份一致")
            results.append({"device": dev, "status": "ok", "report": None})

    if not drift_found and len(target_devices) > 0:
        print("\n✅ 所有设备配置均与最新备份一致")

    return results


def do_rollback(device_alias, backup_file):
    """
    底层回滚调用：通过 rollback_netmiko.py 脚本执行单台设备的配置回滚。

    使用 Netmiko 库直接 SSH 连接设备，将备份配置推送到设备上。

    参数:
        device_alias: 设备别名
        backup_file: 要回滚到的备份文件路径

    返回:
        bool: True 回滚成功，False 回滚失败
    """
    print(f"\n⚠️ 即将把设备 {device_alias} 回滚到: {os.path.basename(backup_file)}")
    cmd = [sys.executable, os.path.join(PROJECT_ROOT, "scripts", "rollback_netmiko.py"), device_alias, backup_file]
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    if result.returncode == 0:
        print(f"✅ 设备 {device_alias} 回滚成功！")
        return True
    else:
        print(f"❌ 设备 {device_alias} 回滚失败！")
        return False


def rollback_device(device_alias, backup_file=None, api_mode=False):
    """
    回滚单台设备的配置。

    如果未指定备份文件：
    - API 模式下自动选择最新备份
    - CLI 模式下显示备份列表让用户选择

    参数:
        device_alias: 设备别名
        backup_file: 指定的备份文件路径，None 则让用户选择
        api_mode: 是否为 API 模式
    """
    if not backup_file:
        backups = list_backups_for_device(device_alias)
        if not backups:
            print(f"❌ 设备 {device_alias} 没有可用备份")
            return

        if api_mode:
            # API 模式下默认回滚到最新版本
            backup_file = backups[0]
        else:
            # CLI 模式下显示备份列表供用户选择
            print(f"\n📋 可用备份文件 (最新在前):")
            for idx, bf in enumerate(backups, 1):
                mtime = datetime.fromtimestamp(os.path.getmtime(bf)).strftime('%Y-%m-%d %H:%M:%S')
                print(f"  {idx}. {os.path.basename(bf)}  ({mtime})")
            choice = input("请输入要恢复的备份编号 (或 0 取消): ").strip()
            if choice == '0': return
            try:
                backup_file = backups[int(choice) - 1]
            except (ValueError, IndexError):
                print("❌ 无效选择")
                return

    # CLI 模式下需要用户二次确认
    if not api_mode:
        if input("此操作将覆盖当前运行配置，是否继续？(yes/N): ").strip().lower() != 'yes':
            print("❌ 已取消")
            return

    do_rollback(device_alias, backup_file)


def rollback_all_devices(api_mode=False):
    """
    回滚全网所有设备到各自的最新备份。

    这是一个高危操作，会遍历 inventory 中的所有设备，
    逐台调用 do_rollback 将配置恢复到最新备份版本。

    参数:
        api_mode: 是否为 API 模式（API 模式跳过确认提示）
    """
    if not api_mode:
        confirm = input("⚠️ 危险操作！确定要将【全网所有设备】回滚到最新备份吗？(yes/N): ").strip()
        if confirm.lower() != 'yes': return

    inventory = load_inventory()
    if not inventory: return
    devices = list(inventory.get('all', {}).get('hosts', {}).keys())

    for dev in devices:
        latest = get_latest_backup(dev)
        if latest:
            do_rollback(dev, latest)
        else:
            print(f"⚠️ 设备 {dev} 没有可用备份，已跳过")


def main():
    """
    主入口函数，支持两种运行模式：

    API 模式参数：
    --api-mode: 启用 API 模式
    --action: drift(漂移检测) / rollback(回滚)
    --target: 目标设备（all 或设备别名）
    --backup-file: 指定回滚的备份文件（可选）

    CLI 模式：交互式菜单
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--api-mode', action='store_true')
    parser.add_argument('--action', choices=['drift', 'rollback'])
    parser.add_argument('--target', default='all')
    parser.add_argument('--backup-file', default='')
    args = parser.parse_args()

    os.chdir(PROJECT_ROOT)

    # ==================== API 模式 ====================
    if args.api_mode:
        if args.action == 'drift':
            # 漂移检测：返回 JSON 格式结果
            results = check_drift(args.target)
            print(json.dumps(results))
        elif args.action == 'rollback':
            # 回滚操作
            if args.target == 'all':
                rollback_all_devices(api_mode=True)
            else:
                rollback_device(args.target, args.backup_file if args.backup_file else None, api_mode=True)
            # 回滚后统一触发一次新备份，记录回滚后的设备状态
            subprocess.run([sys.executable, os.path.join(PROJECT_ROOT, "scripts", "backup_now.py")], capture_output=True)
        sys.exit(0)

    # ==================== CLI 交互菜单 ====================
    while True:
        print("\n" + "=" * 40 + "\n     配置校验与回滚模块\n" + "=" * 40)
        print("1. 检测所有设备配置漂移\n2. 检测指定设备配置漂移\n3. 回滚指定设备\n4. 🚨 回滚全部设备到最新备份\n0. 返回主菜单")
        choice = input("请选择: ").strip()
        if choice == '1': check_drift('all')
        elif choice == '2': check_drift(input("请输入设备别名: ").strip())
        elif choice == '3': rollback_device(input("请输入设备别名: ").strip())
        elif choice == '4': rollback_all_devices()
        elif choice == '0': break
        else: print("❌ 无效选项")


if __name__ == "__main__":
    main()
