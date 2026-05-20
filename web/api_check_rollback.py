#!/usr/bin/env python3
"""
配置校验与回滚模块 API 接口封装 (Blueprint)
"""
import os
import sys
import subprocess
from flask import Blueprint, jsonify, request

API_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(API_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))
from utils import list_backups_for_device

check_bp = Blueprint('check_api', __name__)

@check_bp.route('/api/check/backups/<device_alias>', methods=['GET'])
def get_device_backups(device_alias):
    """获取某台设备的所有备份文件列表（用于前端下拉框选择）"""
    files = list_backups_for_device(device_alias)
    result = [{"filename": os.path.basename(f), "path": f} for f in files]
    return jsonify({"status": "success", "data": result})

@check_bp.route('/api/check/run', methods=['POST'])
def run_action():
    """触发漂移检测或配置回滚"""
    req = request.json
    action = req.get('action') # 'drift' 或 'rollback'
    target = req.get('target', 'all')
    backup_file = req.get('backup_file', '')

    script_path = os.path.join(PROJECT_ROOT, "scripts", "config_check.py")
    cmd = [
        sys.executable, script_path,
        "--api-mode",
        "--action", action,
        "--target", target
    ]
    if backup_file:
        cmd.extend(["--backup-file", backup_file])

    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            return jsonify({"status": "success", "message": f"操作 [{action}] 执行完毕", "log": res.stdout})
        else:
            return jsonify({"status": "error", "message": "执行失败", "log": res.stderr + "\n" + res.stdout}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@check_bp.route('/api/check/download/<filename>', methods=['GET'])
def download_report(filename):
    """下载差异报告文件"""
    report_path = os.path.join(PROJECT_ROOT, "reports", "diff_report", filename)
    if not os.path.exists(report_path):
        return jsonify({"status": "error", "message": "文件不存在"}), 404
    from flask import send_file
    return send_file(report_path, as_attachment=True, download_name=filename)
