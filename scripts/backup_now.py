#!/usr/bin/env python3
"""
配置自动备份模块 - 手动触发与 Git 提交
支持被 Web API 传参调用，也支持 CLI 独立运行。

工作流程：
1. 调用 Ansible Playbook 执行配置备份（从设备拉取 running-config 保存到 backups/ 目录）
2. 将备份文件自动提交到 Git 仓库，实现配置的版本管理
3. 支持 --target 参数定向备份指定设备，也支持 --commit-only 仅提交已有备份
"""
import subprocess
import os
import sys
import glob
import argparse
from datetime import datetime

# ============================================================
# 路径配置
# ============================================================

# 项目根目录（scripts/ 的上一级）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Ansible Playbook 文件路径，定义了备份任务的具体逻辑
PLAYBOOK_PATH = os.path.join(PROJECT_ROOT, "playbooks", "backup_config.yml")

# Ansible 设备清单（经 Vault 加密）
INVENTORY_PATH = os.path.join(PROJECT_ROOT, "inventory.yml")

# 备份文件存储目录
BACKUP_DIR = os.path.join(PROJECT_ROOT, "backups")

# Vault 密码文件
VAULT_PASS_FILE = os.path.join(PROJECT_ROOT, "vault_pass.txt")


def run_backup(target='all'):
    """
    执行 Ansible Playbook 备份设备配置。

    通过调用 ansible-playbook 命令运行 backup_config.yml，该 Playbook 会：
    1. 连接到目标设备（华为路由器）
    2. 执行 display current-configuration 获取当前运行配置
    3. 将配置保存到 backups/ 目录下，文件名格式：{设备别名}_{时间戳}.cfg

    参数:
        target: 目标设备，默认 'all'（全网设备）。可指定设备别名如 'R1'

    返回:
        bool: True 表示备份成功，False 表示备份失败
    """
    cmd = [
        "ansible-playbook",
        "-i", INVENTORY_PATH,           # 指定设备清单
        PLAYBOOK_PATH,                   # 指定 Playbook 文件
        "--extra-vars", f'{{"target_hosts": "{target}"}}',  # 传入目标设备变量
        "--vault-password-file", VAULT_PASS_FILE  # 指定 Vault 密码文件用于解密清单
    ]
    print(f"🚀 开始备份配置 [{target}]...")
    result = subprocess.run(cmd, capture_output=False, text=True)
    return result.returncode == 0


def git_commit_backup():
    """
    将备份文件提交到 Git 仓库，实现配置版本管理。

    工作流程：
    1. 检查 .git 目录是否存在，不存在则初始化仓库并创建 .gitignore
    2. 配置仓库级别的 Git 用户信息（防止 Web 调用时因缺少全局配置报错）
    3. 将 backups/ 目录下的所有 .cfg 文件加入暂存区
    4. 检查暂存区是否有变更，有则提交，无则跳过
    5. 提交信息格式：backup: YYYY-MM-DD HH:MM:SS
    """
    git_dir = os.path.join(PROJECT_ROOT, ".git")
    if not os.path.exists(git_dir):
        # 首次使用，初始化 Git 仓库
        print("🔧 初始化 Git 仓库...")
        subprocess.run(["git", "init"], cwd=PROJECT_ROOT, check=False)
        # 创建 .gitignore，排除敏感文件和临时文件
        gitignore_path = os.path.join(PROJECT_ROOT, ".gitignore")
        if not os.path.exists(gitignore_path):
            with open(gitignore_path, 'w') as f:
                f.write("vault_pass.txt\n__pycache__/\n*.pyc\ninventory_temp.yml\nlogs/\n")
        subprocess.run(["git", "add", ".gitignore"], cwd=PROJECT_ROOT)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=PROJECT_ROOT)

    # 强制配置仓库级别的用户名和邮箱，防止 Web 调用时因缺少全局 Git 配置而报错
    subprocess.run(["git", "config", "user.email", "netauto@system.local"], cwd=PROJECT_ROOT)
    subprocess.run(["git", "config", "user.name", "NetAutoBot"], cwd=PROJECT_ROOT)

    backup_path = os.path.join(PROJECT_ROOT, "backups")
    if not os.path.isdir(backup_path):
        print("ℹ️ 备份目录不存在，无需提交")
        return

    # 查找所有 .cfg 备份文件
    cfg_files = glob.glob(os.path.join(backup_path, "*.cfg"))
    if not cfg_files:
        print("ℹ️ 没有 .cfg 备份文件需要提交")
        return

    # 将所有备份文件加入 Git 暂存区
    for file in cfg_files:
        subprocess.run(["git", "add", file], cwd=PROJECT_ROOT, capture_output=True)

    print(f"✅ 已添加 {len(cfg_files)} 个备份文件到暂存区")

    # 检查暂存区是否有实际变更（避免空提交）
    status_result = subprocess.run(["git", "status", "--porcelain", "--", "backups/"], cwd=PROJECT_ROOT, capture_output=True, text=True)
    if not status_result.stdout.strip():
        print("ℹ️ 暂存区无变更，无需提交")
        return

    # 执行 Git 提交
    commit_msg = f"backup: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    commit_result = subprocess.run(["git", "commit", "-m", commit_msg], cwd=PROJECT_ROOT, capture_output=True, text=True)
    if commit_result.returncode == 0:
        print(f"📦 Git 提交成功: {commit_msg}")
    else:
        print(f"❌ Git 提交失败: {commit_result.stderr}")


def main():
    """
    主入口函数，支持命令行参数：
    --commit-only: 仅执行 Git 提交（不执行备份）
    --target: 指定备份目标设备（默认 all）
    """
    os.chdir(PROJECT_ROOT)

    # 命令行参数解析
    parser = argparse.ArgumentParser()
    parser.add_argument('--commit-only', action='store_true', help="仅执行Git提交")
    parser.add_argument('--target', default='all', help="目标设备 (all 或设备别名)")
    args = parser.parse_args()

    # 如果只提交，直接执行 Git 提交后退出
    if args.commit_only:
        git_commit_backup()
        sys.exit(0)

    # 正常流程：先备份，成功后再 Git 提交
    success = run_backup(target=args.target)
    if success:
        git_commit_backup()
        print("✅ 备份任务完成")
    else:
        print("❌ 备份执行失败，请检查 Ansible 输出")
        sys.exit(1)


if __name__ == "__main__":
    main()
