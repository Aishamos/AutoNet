#!/usr/bin/env python3
"""
企业级网络设备监控报告生成模块

功能概述：
- 通过 Netmiko SSH 登录每台设备，采集实时运行数据
- 收集 CPU 使用率、内存使用率、运行时间、系统版本、接口状态、路由条目数等
- 根据采集数据自动生成告警和巡检建议
- 使用 Jinja2 模板引擎渲染 HTML 格式的巡检报告
- 专为 eNSP 华为 AR 路由器适配

报告内容包括：
- 设备总览（在线/离线统计）
- 每台设备的详细运行指标
- 告警列表（CPU/内存过高、接口 DOWN、设备离线等）
- 巡检建议（基于数据分析的运维建议）
"""
import os
import re
import sys
from datetime import datetime
from utils import load_inventory, ping_check, list_backups_for_device, BACKUP_DIR

# Jinja2 模板引擎，用于渲染 HTML 报告
try:
    from jinja2 import Environment, FileSystemLoader
except ImportError:
    print("❌ 缺少 jinja2 模块，请执行: pip install jinja2")
    sys.exit(1)

# Netmiko 网络设备自动化库，用于 SSH 登录设备采集数据
try:
    from netmiko import ConnectHandler
except ImportError:
    print("❌ 缺少 netmiko 模块，请执行: pip install netmiko")
    sys.exit(1)

# ============================================================
# 路径配置
# ============================================================

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 巡检报告输出目录
REPORT_DIR = os.path.join(PROJECT_ROOT, "reports", "inspection_report")

# Jinja2 模板目录
TEMPLATE_DIR = os.path.join(PROJECT_ROOT, "templates")

os.makedirs(REPORT_DIR, exist_ok=True)

# ============================================================
# 华为 VRP 系统命令输出解析正则表达式
# 针对华为 AR 路由器的 display 命令输出格式进行匹配
# ============================================================

# CPU 使用率正则：匹配 "CPU Usage : 15%" 格式
RE_CPU = re.compile(r"CPU\s+Usage\s*:\s*(\d+%?)", re.IGNORECASE)

# 内存使用率正则：匹配 "Memory Using Percentage Is : 45%" 格式
RE_MEM = re.compile(r"Memory\s+Using\s+Percentage\s+Is\s*:\s*(\d+%?)", re.IGNORECASE)

# 设备运行时间正则：匹配 "Uptime is 1 week, 2 days" 格式
RE_UPTIME = re.compile(r"Uptime\s+is\s+(.*)", re.IGNORECASE)

# 系统版本正则：匹配 "VRP (R) software, Version 5.170" 格式
RE_VERSION = re.compile(r"VRP\s+\(R\)\s+software,\s+Version\s+([^\s]+)", re.IGNORECASE)

# 接口状态正则：匹配接口名 + 物理状态 + 协议状态
# 例如：GigabitEthernet0/0/1 up up
RE_INTERFACE_LINE = re.compile(r"^(\S+)\s+(up|down|admin\s*down)\s+(up|down)", re.IGNORECASE | re.MULTILINE)

# 路由条目正则：匹配 IP/掩码格式的路由条目
# 例如：192.168.1.0/24
RE_ROUTE_ENTRY = re.compile(r"^(\d+\.\d+\.\d+\.\d+/\d+)", re.MULTILINE)


def get_latest_backup_info(device_alias):
    """
    获取设备的最新备份状态信息。

    参数:
        device_alias: 设备别名

    返回:
        dict: {'status': '正常'/'未备份', 'time': '备份时间'/'-'}
    """
    files = list_backups_for_device(device_alias)
    if not files:
        return {"status": "未备份", "time": "-"}

    mtime = datetime.fromtimestamp(os.path.getmtime(files[0])).strftime('%Y-%m-%d %H:%M:%S')
    return {"status": "正常", "time": mtime}


def parse_interfaces(output):
    """
    解析 'display interface brief' 命令输出，提取接口状态信息。

    参数:
        output: display interface brief 命令的原始输出文本

    返回:
        dict: 接口状态汇总
            - list: 所有接口的详细信息列表
            - up: UP 状态的接口数量
            - down: DOWN 状态的接口数量
            - total: 接口总数
    """
    interfaces = []
    for match in RE_INTERFACE_LINE.finditer(output):
        name = match.group(1)          # 接口名（如 GigabitEthernet0/0/1）
        phy_status = match.group(2).strip()    # 物理层状态（up/down）
        proto_status = match.group(3).strip()  # 协议层状态（up/down）
        interfaces.append({
            "name": name,
            "phy": phy_status,
            "proto": proto_status
        })

    up_count = sum(1 for i in interfaces if i["phy"].lower() == "up")
    total = len(interfaces)
    return {
        "list": interfaces,
        "up": up_count,
        "down": total - up_count,
        "total": total
    }


def parse_routes(output):
    """
    解析 'display ip routing-table' 命令输出，统计路由条目数量。

    参数:
        output: display ip routing-table 命令的原始输出文本

    返回:
        int: 路由条目数量
    """
    entries = RE_ROUTE_ENTRY.findall(output)
    return len(entries)


def gather_device_metrics(ip, user, password):
    """
    通过 Netmiko SSH 登录设备，采集实时运行指标。

    依次执行以下华为 VRP 命令：
    - display cpu-usage: CPU 使用率
    - display memory: 内存使用率
    - display version: 系统版本和运行时间
    - display interface brief: 接口状态
    - display ip routing-table: 路由表
    - display logbuffer size 0: 系统日志

    参数:
        ip: 设备 IP 地址
        user: SSH 用户名
        password: SSH 密码

    返回:
        dict: 采集到的各项指标，采集失败时返回默认值 "-"
    """
    # 初始化默认值
    metrics = {
        "cpu": "-", "mem": "-", "uptime": "-", "version": "-",
        "interfaces": {"list": [], "up": 0, "down": 0, "total": 0},
        "route_count": 0,
        "log_count": 0
    }
    # Netmiko 连接参数
    device = {
        'device_type': 'huawei',    # 华为设备类型
        'host': ip,
        'username': user,
        'password': password,
        'port': 22,
        'global_delay_factor': 1.0, # 延迟系数（影响命令等待时间）
        'auth_timeout': 10,         # 认证超时
        'timeout': 10               # 连接超时
    }

    try:
        with ConnectHandler(**device) as net_connect:
            # 依次执行采集命令
            cpu_out = net_connect.send_command("display cpu-usage")
            mem_out = net_connect.send_command("display memory")
            ver_out = net_connect.send_command("display version")
            intf_out = net_connect.send_command("display interface brief")
            route_out = net_connect.send_command("display ip routing-table")
            log_out = net_connect.send_command("display logbuffer size 0")

            # 使用正则提取 CPU 使用率
            m_cpu = RE_CPU.search(cpu_out)
            if m_cpu:
                metrics["cpu"] = m_cpu.group(1) if "%" in m_cpu.group(1) else m_cpu.group(1) + "%"

            # 使用正则提取内存使用率
            m_mem = RE_MEM.search(mem_out)
            if m_mem:
                metrics["mem"] = m_mem.group(1) if "%" in m_mem.group(1) else m_mem.group(1) + "%"

            # 使用正则提取运行时间
            m_up = RE_UPTIME.search(ver_out)
            if m_up:
                metrics["uptime"] = m_up.group(1).strip()

            # 使用正则提取系统版本
            m_ver = RE_VERSION.search(ver_out)
            if m_ver:
                metrics["version"] = m_ver.group(1)

            # 解析接口状态
            metrics["interfaces"] = parse_interfaces(intf_out)

            # 解析路由条目数
            metrics["route_count"] = parse_routes(route_out)

            # 日志条目数（简单统计行数）
            metrics["log_count"] = len(log_out.strip().split('\n')) if log_out.strip() else 0

    except Exception:
        # 获取失败时保持默认值 "-"，不中断报告生成
        pass

    return metrics


def generate_alerts(devices):
    """
    根据采集到的设备数据生成告警列表。

    告警规则：
    - 设备离线 → 严重
    - CPU >= 80% → 严重，>= 60% → 警告
    - 内存 >= 80% → 严重，>= 60% → 警告
    - 存在 DOWN 接口 → 警告
    - 未备份 → 警告

    参数:
        devices: 设备数据列表（含各项指标）

    返回:
        list[dict]: 告警列表，每项包含 level(严重/警告)、level_cls、device、ip、message
    """
    alerts = []

    for dev in devices:
        alias = dev["alias"]
        ip = dev["ip"]

        # 离线告警
        if dev["status_cls"] == "offline":
            alerts.append({
                "level": "严重",
                "level_cls": "critical",
                "device": alias,
                "ip": ip,
                "message": "设备不可达，无法建立连接"
            })
            continue

        # CPU 告警
        cpu_val = dev["cpu"].replace("%", "")
        if cpu_val.isdigit():
            cpu_num = int(cpu_val)
            if cpu_num >= 80:
                alerts.append({
                    "level": "严重",
                    "level_cls": "critical",
                    "device": alias,
                    "ip": ip,
                    "message": f"CPU 使用率过高: {dev['cpu']}"
                })
            elif cpu_num >= 60:
                alerts.append({
                    "level": "警告",
                    "level_cls": "warning",
                    "device": alias,
                    "ip": ip,
                    "message": f"CPU 使用率偏高: {dev['cpu']}"
                })

        # 内存告警
        mem_val = dev["mem"].replace("%", "")
        if mem_val.isdigit():
            mem_num = int(mem_val)
            if mem_num >= 80:
                alerts.append({
                    "level": "严重",
                    "level_cls": "critical",
                    "device": alias,
                    "ip": ip,
                    "message": f"内存使用率过高: {dev['mem']}"
                })
            elif mem_num >= 60:
                alerts.append({
                    "level": "警告",
                    "level_cls": "warning",
                    "device": alias,
                    "ip": ip,
                    "message": f"内存使用率偏高: {dev['mem']}"
                })

        # 接口 DOWN 告警
        if dev["interfaces"]["down"] > 0:
            alerts.append({
                "level": "警告",
                "level_cls": "warning",
                "device": alias,
                "ip": ip,
                "message": f"存在 {dev['interfaces']['down']} 个接口处于 DOWN 状态"
            })

        # 备份告警
        if dev["backup_status"] == "未备份":
            alerts.append({
                "level": "警告",
                "level_cls": "warning",
                "device": alias,
                "ip": ip,
                "message": "设备尚未进行配置备份"
            })

    return alerts


def generate_suggestions(devices, alerts):
    """
    根据采集数据和告警信息生成巡检建议。

    分析维度：
    - 网络整体健康率（在线设备占比）
    - 未备份设备数量
    - 严重/警告告警数量
    - 高 CPU 使用率设备

    参数:
        devices: 设备数据列表
        alerts: 告警列表

    返回:
        dict: 巡检汇总信息
            - health_rate: 网络健康率（百分比）
            - total/online/offline: 设备总数/在线数/离线数
            - no_backup: 未备份设备数
            - critical/warning: 严重/警告告警数
            - suggestions: 建议文本列表
    """
    suggestions = []

    # 统计各项指标
    total = len(devices)
    online = sum(1 for d in devices if d["status_cls"] == "online")
    offline = total - online
    no_backup = sum(1 for d in devices if d["backup_status"] == "未备份")
    critical_count = sum(1 for a in alerts if a["level"] == "严重")
    warning_count = sum(1 for a in alerts if a["level"] == "警告")

    # 计算健康率
    health_rate = round(online / total * 100, 1) if total > 0 else 0

    # 根据健康率生成建议
    if health_rate < 80:
        suggestions.append("网络整体健康率低于 80%，建议立即排查离线设备原因，检查物理链路和设备运行状态。")
    elif health_rate < 100:
        suggestions.append(f"当前有 {offline} 台设备离线，建议检查相关设备的电源、网线连接及管理接口配置。")
    else:
        suggestions.append("所有设备运行正常，网络连通性良好。")

    if no_backup > 0:
        suggestions.append(f"有 {no_backup} 台设备尚未进行配置备份，建议立即执行备份操作以防止配置丢失。")

    if critical_count > 0:
        suggestions.append(f"检测到 {critical_count} 条严重告警，建议优先处理。")

    if warning_count > 0:
        suggestions.append(f"检测到 {warning_count} 条警告信息，建议在下次维护窗口期间处理。")

    # 检查高 CPU 设备
    high_cpu_devices = [d["alias"] for d in devices if d["cpu"] != "-" and d["cpu"].replace("%", "").isdigit() and int(d["cpu"].replace("%", "")) >= 60]
    if high_cpu_devices:
        suggestions.append(f"设备 {', '.join(high_cpu_devices)} CPU 使用率偏高，建议检查是否存在异常进程或考虑升级硬件。")

    if not suggestions:
        suggestions.append("本次巡检未发现异常，系统运行状态良好。建议继续保持定期巡检。")

    return {
        "health_rate": health_rate,
        "total": total,
        "online": online,
        "offline": offline,
        "no_backup": no_backup,
        "critical": critical_count,
        "warning": warning_count,
        "suggestions": suggestions
    }


def generate_html_report():
    """
    主函数：生成完整的 HTML 巡检报告。

    完整流程：
    1. 加载设备清单
    2. 逐台设备 Ping 检测在线状态
    3. 在线设备通过 Netmiko 采集运行指标
    4. 生成告警和巡检建议
    5. 使用 Jinja2 模板渲染 HTML 报告
    6. 保存报告到 reports/inspection_report/ 目录
    """
    print("🔍 正在采集设备实时运行数据（此过程需要登录设备，请稍候）...")
    inventory = load_inventory()
    if not inventory:
        print("❌ 无法读取设备清单，报告生成中止。")
        return

    hosts = inventory.get('all', {}).get('hosts', {})
    report_data = []
    online_count, offline_count = 0, 0

    # 逐台设备采集数据
    for alias, info in hosts.items():
        ip = info.get('ansible_host', 'Unknown')
        user = info.get('ansible_user', 'admin')
        password = info.get('ansible_password', '')

        sys.stdout.write(f"  -> 采集 {alias} ({ip}) 信息... ")
        sys.stdout.flush()

        # 检测设备是否在线
        is_online = ping_check(ip, count=2)
        # 获取备份状态
        backup_info = get_latest_backup_info(alias)

        if is_online:
            online_count += 1
            status_cls = "online"
            status_txt = "正常在线"
            # 在线设备：采集实时运行数据
            metrics = gather_device_metrics(ip, user, password)
            print("完成")
        else:
            offline_count += 1
            status_cls = "offline"
            status_txt = "设备离线"
            # 离线设备：使用默认空值
            metrics = {
                "cpu": "-", "mem": "-", "uptime": "-", "version": "-",
                "interfaces": {"list": [], "up": 0, "down": 0, "total": 0},
                "route_count": 0,
                "log_count": 0
            }
            print("离线")

        # 汇总该设备的所有数据
        report_data.append({
            "alias": alias,
            "ip": ip,
            "status_cls": status_cls,
            "status_txt": status_txt,
            "cpu": metrics["cpu"],
            "mem": metrics["mem"],
            "version": metrics["version"],
            "uptime": metrics["uptime"],
            "interfaces": metrics["interfaces"],
            "route_count": metrics["route_count"],
            "log_count": metrics["log_count"],
            "backup_status": backup_info["status"],
            "backup_time": backup_info["time"]
        })

    # 生成告警列表
    alerts = generate_alerts(report_data)

    # 生成巡检建议
    summary = generate_suggestions(report_data, alerts)

    # 使用 Jinja2 模板渲染 HTML 报告
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    try:
        template = env.get_template('report_template.html')
    except Exception as e:
        print(f"❌ 找不到模板文件 {TEMPLATE_DIR}/report_template.html")
        return

    report_content = template.render(
        report_id=f"NR-{datetime.now().strftime('%Y%m%d%H%M%S')}",  # 报告编号
        gen_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),       # 生成时间
        total=len(hosts),          # 设备总数
        online=online_count,       # 在线设备数
        offline=offline_count,     # 离线设备数
        devices=report_data,       # 设备详细数据
        alerts=alerts,             # 告警列表
        summary=summary            # 巡检建议汇总
    )

    # 保存报告文件
    report_filename = f"Inspection_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    report_path = os.path.join(REPORT_DIR, report_filename)

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_content)

    print(f"\n📊 标准巡检报告已生成: {report_path}")


if __name__ == "__main__":
    generate_html_report()
