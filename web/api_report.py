#!/usr/bin/env python3
"""
监控报告模块 API 接口封装 (Blueprint)
"""
import os
import sys
import subprocess
from datetime import datetime
from flask import Blueprint, jsonify, send_from_directory

API_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(API_DIR)
REPORT_DIR = os.path.join(PROJECT_ROOT, "reports", "inspection_report")

report_bp = Blueprint('report_api', __name__)

@report_bp.route('/api/reports', methods=['GET'])
def list_reports():
    """1. 获取历史报告列表"""
    if not os.path.exists(REPORT_DIR):
        return jsonify({"status": "success", "data": []})
    
    files_data = []
    for f in os.listdir(REPORT_DIR):
        if f.endswith('.html') or f.endswith('.htm'):
            f_path = os.path.join(REPORT_DIR, f)
            size_kb = round(os.path.getsize(f_path) / 1024, 2)
            mtime = os.path.getmtime(f_path)
            time_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
            files_data.append({"name": f, "size": f"{size_kb} KB", "time": time_str, "timestamp": mtime})
    
    # 按时间倒序（最新的在前）
    files_data.sort(key=lambda x: x['timestamp'], reverse=True)
    return jsonify({"status": "success", "data": files_data})


@report_bp.route('/api/reports/generate', methods=['POST'])
def generate_report():
    """2. 触发系统采集数据并生成报告"""
    script_path = os.path.join(PROJECT_ROOT, "scripts", "generate_report.py")
    try:
        # 这个过程会依次登录设备获取 CPU/Mem，耗时较长
        res = subprocess.run([sys.executable, script_path], capture_output=True, text=True)
        if res.returncode == 0:
            return jsonify({"status": "success", "message": "✅ 巡检报告生成完毕！", "log": res.stdout})
        else:
            return jsonify({"status": "error", "message": "报告生成失败", "log": res.stderr + "\n" + res.stdout}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@report_bp.route('/api/reports/view/<filename>', methods=['GET'])
def view_report(filename):
    """3. 在线预览 HTML 报告"""
    # 简单的安全校验，防止路径穿越
    if '/' in filename or '\\' in filename or not filename.endswith('.html'):
        return "非法的文件请求", 400
    return send_from_directory(REPORT_DIR, filename)
