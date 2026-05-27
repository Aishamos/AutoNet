#!/usr/bin/env python3
"""
配置备份模块 API 接口封装 (Blueprint)
"""
import os
import sys
import subprocess
from datetime import datetime
from flask import Blueprint, jsonify, request, send_from_directory

API_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(API_DIR)
BACKUP_DIR = os.path.join(PROJECT_ROOT, "backups")
CRON_SCRIPT = os.path.join(PROJECT_ROOT, "scripts", "cron_backup.sh")

backup_bp = Blueprint('backup_api', __name__)

@backup_bp.route('/api/backup/files', methods=['GET'])
def list_backups():
    """1. 获取所有备份文件列表"""
    if not os.path.exists(BACKUP_DIR):
        return jsonify({"status": "success", "data": []})
    
    files_data = []
    for f in os.listdir(BACKUP_DIR):
        if f.endswith('.cfg'):
            f_path = os.path.join(BACKUP_DIR, f)
            size_kb = round(os.path.getsize(f_path) / 1024, 2)
            mtime = datetime.fromtimestamp(os.path.getmtime(f_path)).strftime('%Y-%m-%d %H:%M:%S')
            files_data.append({"name": f, "size": f"{size_kb} KB", "time": mtime, "timestamp": os.path.getmtime(f_path)})
    
    # 按时间倒序（最新的在前）
    files_data.sort(key=lambda x: x['timestamp'], reverse=True)
    return jsonify({"status": "success", "data": files_data})

@backup_bp.route('/api/backup/run', methods=['POST'])
def run_backup():
    """2. 立即备份所有设备 (附带自动提交)"""
    script_path = os.path.join(PROJECT_ROOT, "scripts", "backup_now.py")
    try:
        # 这里会有些耗时，前端需要等待转圈圈
        res = subprocess.run([sys.executable, script_path], capture_output=True, text=True)
        if res.returncode == 0:
            return jsonify({"status": "success", "message": "全网设备备份完成并已记录！", "log": res.stdout})
        return jsonify({"status": "error", "message": f"执行报错:\n{res.stderr}"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@backup_bp.route('/api/backup/commit', methods=['POST'])
def manual_commit():
    """3. 手动执行 Git 提交"""
    script_path = os.path.join(PROJECT_ROOT, "scripts", "backup_now.py")
    try:
        res = subprocess.run([sys.executable, script_path, "--commit-only"], capture_output=True, text=True)
        return jsonify({"status": "success", "message": "Git 提交操作执行完毕", "log": res.stdout})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@backup_bp.route('/api/backup/download/<filename>', methods=['GET'])
def download_backup(filename):
    """4. 下载指定备份文件"""
    if '/' in filename or '\\' in filename or not filename.endswith('.cfg'):
        return jsonify({"status": "error", "message": "非法的文件名"}), 400
    file_path = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(file_path):
        return jsonify({"status": "error", "message": "文件不存在"}), 404
    return send_from_directory(BACKUP_DIR, filename, as_attachment=True)

# ================= 定时任务 (Crontab) 管理 =================

def get_current_crontab():
    """读取当前用户的 crontab"""
    res = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    return res.stdout.splitlines() if res.returncode == 0 else []

@backup_bp.route('/api/backup/cron', methods=['GET'])
def get_cron():
    """获取当前备份定时任务状态"""
    lines = get_current_crontab()
    for line in lines:
        if CRON_SCRIPT in line and not line.strip().startswith('#'):
            parts = line.split()
            # 提取时间表达式的前 5 个字段
            cron_expr = " ".join(parts[:5])
            return jsonify({"status": "success", "active": True, "expression": cron_expr})
    return jsonify({"status": "success", "active": False, "expression": ""})

@backup_bp.route('/api/backup/cron', methods=['POST'])
def set_cron():
    """设置或更新定时任务"""
    expr = request.json.get('expression') # 比如 "0 2 * * *" (每天凌晨2点)
    if not expr:
        return jsonify({"status": "error", "message": "缺少 Cron 表达式"}), 400

    new_cron_line = f"{expr} /bin/bash {CRON_SCRIPT}"
    lines = get_current_crontab()
    
    # 清理旧的该任务
    filtered_lines = [l for l in lines if CRON_SCRIPT not in l]
    filtered_lines.append(new_cron_line)
    
    cron_content = "\n".join(filtered_lines) + "\n"
    subprocess.run(["crontab", "-"], input=cron_content, text=True)
    
    return jsonify({"status": "success", "message": f"定时任务已更新为: {expr}"})

@backup_bp.route('/api/backup/cron', methods=['DELETE'])
def delete_cron():
    """取消定时任务"""
    lines = get_current_crontab()
    filtered_lines = [l for l in lines if CRON_SCRIPT not in l]
    
    cron_content = "\n".join(filtered_lines) + "\n"
    subprocess.run(["crontab", "-"], input=cron_content, text=True)
    return jsonify({"status": "success", "message": "定时任务已取消"})
