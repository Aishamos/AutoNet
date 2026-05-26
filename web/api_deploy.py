#!/usr/bin/env python3
"""
配置下发模块 API 接口封装 (Blueprint)
"""
import os
import sys
import json
import re
import subprocess
from datetime import datetime
from flask import Blueprint, jsonify, request

API_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(API_DIR)
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, "templates")
LOGS_DIR = os.path.join(PROJECT_ROOT, "scripts", "logs", "deploy_logs")

def parse_ansible_recap(stdout):
    """解析 Ansible PLAY RECAP，返回逐设备状态 {host: True/False}"""
    results = {}
    lines = stdout.split('\n')
    in_recap = False
    for line in lines:
        if 'PLAY RECAP' in line:
            in_recap = True
            continue
        if in_recap:
            match = re.match(r'^(\S+)\s+:.*?failed=(\d+).*?unreachable=(\d+)', line)
            if match:
                host = match.group(1)
                failed = int(match.group(2)) > 0
                unreachable = int(match.group(3)) > 0
                results[host] = not failed and not unreachable
    return results

# 引入管理模块获取设备列表
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))
from manage_inventory import load_inventory

deploy_bp = Blueprint('deploy_api', __name__)

# 定义各模板所需的变量字段，供前端动态渲染表单
TEMPLATE_FIELDS = {
    "acl.j2": [
        {"name": "acl_number", "label": "ACL 编号 (如 3000)", "type": "text", "required": True},
        {"name": "rule_id", "label": "规则 ID (如 5)", "type": "text", "required": True},
        {"name": "source_ip", "label": "源 IP (如 192.168.1.0)", "type": "text", "required": True},
        {"name": "source_wildcard", "label": "通配符掩码 (如 0.0.0.255)", "type": "text", "required": True}
    ],
    "interface.j2": [
        {"name": "interface_name", "label": "接口名 (如 GigabitEthernet0/0/1)", "type": "text", "required": True},
        {"name": "ip_address", "label": "IP 地址 (如 10.1.1.1)", "type": "text", "required": True},
        {"name": "mask", "label": "子网掩码 (如 255.255.255.0)", "type": "text", "required": True}
    ],
    "vlan.j2": [
        {"name": "vlan_id", "label": "VLAN ID (如 10)", "type": "text", "required": False},
        {"name": "vlanif_ip", "label": "VLANIF IP 地址 (如 192.168.10.1)", "type": "text", "required": False},
        {"name": "vlanif_mask", "label": "VLANIF 子网掩码 (如 255.255.255.0)", "type": "text", "required": False},
        {"name": "port_name", "label": "接口名 (如 GigabitEthernet0/0/1)", "type": "text", "required": False},
        {"name": "port_link_type", "label": "接口类型", "type": "select", "options": ["access", "trunk"], "required": False},
        {"name": "port_default_vlan", "label": "Access 默认 VLAN", "type": "text", "required": False},
        {"name": "trunk_allowed_vlans", "label": "Trunk 允许 VLAN (如 10 20 30)", "type": "text", "required": False}
    ]
}

@deploy_bp.route('/api/deploy/meta', methods=['GET'])
def get_deploy_meta():
    """获取部署所需的元数据：模板列表及设备列表"""
    # 1. 获取模板列表
    templates = []
    if os.path.exists(TEMPLATES_DIR):
        for f in os.listdir(TEMPLATES_DIR):
            if f.endswith('.j2'):
                templates.append({
                    "filename": f,
                    "fields": TEMPLATE_FIELDS.get(f, [])
                })
    
    # 2. 获取设备列表
    devices = [{"alias": "all", "desc": "全网所有设备 (谨慎操作)"}]
    inventory = load_inventory()
    if inventory:
        hosts = inventory.get('all', {}).get('hosts', {})
        for alias, info in hosts.items():
            devices.append({"alias": alias, "desc": info.get('description', '暂无描述')})
            
    return jsonify({"status": "success", "templates": templates, "devices": devices})

@deploy_bp.route('/api/deploy/run', methods=['POST'])
def run_deploy():
    """触发下发任务"""
    req = request.json
    template = req.get('template')
    target = req.get('target', 'all')
    vars_dict = req.get('vars', {})

    if not template:
        return jsonify({"status": "error", "message": "未指定模板"}), 400

    script_path = os.path.join(PROJECT_ROOT, "scripts", "deploy_now.py")
    cmd = [
        sys.executable, script_path,
        "--api-mode",
        "--template", template,
        "--target", target,
        "--vars", json.dumps(vars_dict)
    ]
    
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
        full_log = res.stdout + ("\n" + res.stderr if res.stderr else "")

        # 保存详细日志到文件
        os.makedirs(LOGS_DIR, exist_ok=True)
        log_filename = f"deploy_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        log_path = os.path.join(LOGS_DIR, log_filename)
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write(f"模板: {template}\n目标: {target}\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 60 + "\n")
            f.write(full_log)

        # 解析逐设备结果
        device_results = parse_ansible_recap(full_log)

        if res.returncode == 0:
            return jsonify({"status": "success", "message": f"配置成功下发至 [{target}]", "results": device_results})
        else:
            # 前端只显示简单提示，详细日志在后端
            if device_results and any(device_results.values()):
                status = "partial"
                failed = [h for h, ok in device_results.items() if not ok]
                msg = f"部分设备下发失败: {', '.join(failed)}。详细日志: {log_path}"
            else:
                status = "error"
                msg = f"下发失败，请查看后端日志: {log_path}"
            print(f"❌ 下发失败，完整日志已保存至: {log_path}")
            print(full_log)
            return jsonify({"status": status, "message": msg, "results": device_results}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": f"执行异常: {str(e)}"}), 500
