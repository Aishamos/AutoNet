#!/usr/bin/env python3
"""
系统操作日志管理模块 API 接口封装 (Blueprint)
"""
from flask import Blueprint, request, jsonify
from logs_manager import write_log, get_all_logs

# 创建日志蓝图 
logs_bp = Blueprint('logs', __name__)

@logs_bp.route('/api/logs', methods=['POST'])
def add_log_api():
    """接口：新增一条日志"""
    data = request.json
    action = data.get('action')
    result = data.get('result')
    
    success = write_log(action, result) # 调用核心功能
    
    if success:
        return jsonify({"status": "success", "message": "日志记录成功"})
    else:
        return jsonify({"status": "error", "message": "后端写入失败"}), 500

@logs_bp.route('/api/logs', methods=['GET'])
def get_logs_api():
    """接口：获取所有日志"""
    logs = get_all_logs() # 调用核心功能
    return jsonify({"status": "success", "data": logs})
