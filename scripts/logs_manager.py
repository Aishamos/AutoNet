#!/usr/bin/env python3
"""
系统操作日志管理模块

功能：
- 记录系统中所有操作的日志（备份、下发、回滚、巡检等）
- 提供日志写入和读取接口，供 Web 前端展示操作历史
- 日志存储为 JSON 文件，最新记录置顶，最多保留 1000 条

日志格式：
{
    "time": "2026-05-07 15:30:45",     # 操作时间
    "action": "备份配置 R1",            # 操作描述
    "result": "成功"                    # 操作结果
}
"""
import os
import json
from datetime import datetime
from utils import ensure_json_file

# ============================================================
# 路径配置
# ============================================================

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 日志文件路径（JSON 格式）
LOG_FILE_PATH = os.path.join(PROJECT_ROOT, "logs", "sys_logs.json")


def write_log(action, result):
    """
    写入一条操作日志。

    日志以 JSON 数组形式存储，新记录插入到数组头部（最新在前），
    超过 1000 条时自动截断旧记录，防止文件无限增长。

    参数:
        action: 操作描述（如 "备份配置 R1"、"下发接口配置到 R2"）
        result: 操作结果（如 "成功"、"失败：设备不可达"）

    返回:
        bool: True 写入成功，False 写入失败
    """
    ensure_json_file(LOG_FILE_PATH)
    try:
        # 构造日志条目
        new_log = {
            "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "action": action or '未知操作',
            "result": result or '未知结果'
        }
        # 读取现有日志
        with open(LOG_FILE_PATH, 'r', encoding='utf-8') as f:
            logs = json.load(f)
        # 新记录插入到头部（最新在前）
        logs.insert(0, new_log)
        # 最多保留 1000 条记录
        logs = logs[:1000]
        # 写回文件
        with open(LOG_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(logs, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"❌ 日志写入失败: {e}")
        return False


def get_all_logs():
    """
    读取所有操作日志。

    返回日志列表（按时间倒序排列），供 Web 前端 API 调用。

    返回:
        list[dict]: 日志条目列表，每项包含 time、action、result 字段
        空列表: 读取失败或日志文件为空
    """
    ensure_json_file(LOG_FILE_PATH)
    try:
        with open(LOG_FILE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ 日志读取失败: {e}")
        return []
