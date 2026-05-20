#!/usr/bin/env python3
"""
设备信息管理模块 API 接口封装 (Blueprint)
"""
import os
import sys
import yaml
from datetime import datetime
from flask import Blueprint, request, jsonify, send_file

# ========== 核心路径配置 ==========
API_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(API_DIR)

# 将 scripts 目录加入环境变量，导入底层逻辑函数
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))
from manage_inventory import load_inventory, save_inventory, verify_device_connection

# 初始化蓝图
inventory_bp = Blueprint('inventory_api', __name__)

# ========== RESTful API 接口 ==========

@inventory_bp.route('/api/devices', methods=['GET'])
def get_devices():
    """1. 查看所有设备"""
    data = load_inventory(use_vault=True)
    if not data:
        return jsonify({"status": "error", "message": "无法加载设备清单"}), 500
    
    hosts = data.get('all', {}).get('hosts', {})
    device_list = [
        {
            "alias": alias,
            "ip": info.get('ansible_host', ''),
            "user": info.get('ansible_user', ''),
            "description": info.get('description', '')
        }
        for alias, info in hosts.items()
    ]
    return jsonify({"status": "success", "data": device_list})

@inventory_bp.route('/api/devices', methods=['POST'])
def add_device():
    """2. 添加设备（可选连通性验证）"""
    req = request.json
    alias, ip, user, pwd, desc = req.get('alias'), req.get('ip'), req.get('user', 'admin'), req.get('password', ''), req.get('description', '')
    verify = req.get('verify', True)  # 默认开启验证

    if not alias or not ip:
        return jsonify({"status": "error", "message": "别名和IP为必填项"}), 400

    # 根据 verify 参数决定是否验证连通性
    if verify:
        is_ok, msg = verify_device_connection(ip, user, pwd)
        if not is_ok:
            return jsonify({"status": "error", "message": f"设备连通性验证失败：{msg}"}), 400

    inventory = load_inventory() or {'all': {'hosts': {}}}
    if 'all' not in inventory: inventory['all'] = {'hosts': {}}
    if 'hosts' not in inventory['all']: inventory['all']['hosts'] = {}

    inventory['all']['hosts'][alias] = {
        'ansible_host': ip,
        'ansible_user': user,
        'ansible_password': pwd,
        'ansible_connection': 'ansible.netcommon.network_cli',
        'ansible_network_os': 'community.network.ce',
        'description': desc
    }
    save_inventory(inventory)
    msg = "连通性测试通过，设备已加密保存！" if verify else "设备已加密保存（跳过连通性验证）"
    return jsonify({"status": "success", "message": msg})

@inventory_bp.route('/api/devices', methods=['DELETE'])
def delete_device():
    """3. 删除设备"""
    alias = request.json.get('alias')
    inventory = load_inventory()
    if alias in inventory.get('all', {}).get('hosts', {}):
        del inventory['all']['hosts'][alias]
        save_inventory(inventory)
        return jsonify({"status": "success", "message": f"设备 {alias} 已移除"})
    return jsonify({"status": "error", "message": "设备不存在"}), 404

@inventory_bp.route('/api/check_connectivity', methods=['POST'])
def check_connectivity():
    """4. 独立连通性验证（已有设备）"""
    alias = request.json.get('alias')
    inventory = load_inventory()
    host_info = inventory.get('all', {}).get('hosts', {}).get(alias)
    
    if not host_info:
        return jsonify({"status": "error", "message": "设备配置不存在"}), 404
        
    ip = host_info.get('ansible_host')
    user = host_info.get('ansible_user')
    pwd = host_info.get('ansible_password')
    
    is_ok, msg = verify_device_connection(ip, user, pwd)
    if is_ok:
        return jsonify({"status": "success", "message": "✅ 测试通过：" + msg})
    else:
        return jsonify({"status": "error", "message": "❌ 测试失败：" + msg})

@inventory_bp.route('/api/export_inventory', methods=['POST'])
def export_inventory():
    """5. 导出设备清单（服务器保存 + 浏览器下载），密码字段脱敏"""
    data = load_inventory()
    if not data:
        return jsonify({"status": "error", "message": "无法加载设备清单"}), 500

    # 导出前将密码字段替换为 ***，防止明文密码泄露
    for alias, info in data.get('all', {}).get('hosts', {}).items():
        if 'ansible_password' in info:
            print(f"[DEBUG] 脱敏设备 {alias} 的密码")
            info['ansible_password'] = '***'

    filename = f"inventory_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.yml"
    export_dir = os.path.join(PROJECT_ROOT, "exports")
    os.makedirs(export_dir, exist_ok=True)
    filepath = os.path.join(export_dir, filename)

    with open(filepath, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    return send_file(filepath, as_attachment=True, download_name=filename, mimetype='text/yaml')
