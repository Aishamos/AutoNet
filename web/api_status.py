import os
import sys
from flask import Blueprint, jsonify
from apscheduler.schedulers.background import BackgroundScheduler

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts'))
from utils import get_decrypted_devices, ping_check

status_bp = Blueprint('status', __name__)

# 内存缓存，存储最新的统计结果
current_stats = {"online_count": 0, "total_count": 0, "devices": {}}

def init_status_monitor(socketio):
    """启动 20s 一次的后台巡检任务"""
    scheduler = BackgroundScheduler()

    def check_job():
        global current_stats
        devices = get_decrypted_devices()
        online = 0
        device_status = {}

        for dev in devices:
            is_online = dev['ip'] and ping_check(dev['ip'])
            if is_online:
                online += 1
            device_status[dev['alias']] = is_online

        current_stats = {
            "online_count": online,
            "total_count": len(devices),
            "devices": device_status
        }

        # 通过 WebSocket 管道主动推给前端
        socketio.emit('status_update', current_stats)
        print(f" 定时巡检同步: {online}/{len(devices)} 在线")

    # 设定 20 秒间隔
    scheduler.add_job(func=check_job, trigger="interval", seconds=20)
    scheduler.start()

@status_bp.route('/api/status/summary', methods=['GET'])
def get_stats():
    """初次打开页面时拉取最新数据的接口"""
    return jsonify({"status": "success", "data": current_stats})

@status_bp.route('/api/status/devices', methods=['GET'])
def get_device_status():
    """逐设备在线状态接口"""
    return jsonify({"status": "success", "data": current_stats.get("devices", {})})
