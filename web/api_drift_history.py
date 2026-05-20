#!/usr/bin/env python3
"""
漂移检测历史记录 API
"""
import os
import sys
import json
from flask import Blueprint, request, jsonify
from datetime import datetime

drift_bp = Blueprint('drift_api', __name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))
from utils import ensure_json_file

HISTORY_FILE = os.path.join(PROJECT_ROOT, "logs", "drift_history.json")

@drift_bp.route('/api/drift/history', methods=['GET'])
def get_drift_history():
    """获取漂移检测历史记录"""
    ensure_json_file(HISTORY_FILE)
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify({"status": "success", "data": data})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@drift_bp.route('/api/drift/history', methods=['POST'])
def add_drift_history():
    """新增漂移检测记录"""
    ensure_json_file(HISTORY_FILE)
    try:
        records = request.json.get('records', [])
        if not records:
            return jsonify({"status": "error", "message": "无记录数据"}), 400

        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            history = json.load(f)

        history = records + history
        history = history[:500]

        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

        return jsonify({"status": "success", "message": "记录保存成功"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
