#!/usr/bin/env python3
"""
设备在线状态监控模块

功能：
- 解密设备清单，获取所有设备的别名和 IP 地址
- 对每台设备执行 ICMP Ping 探测，判断在线/离线状态
- 供 web/api_status.py 导入使用，也为 CLI 调试提供入口

监控原理：
通过向设备发送 ICMP Echo Request（Ping），根据返回码判断设备是否可达。
返回码 0 表示设备在线，非 0 表示设备离线或不可达。
"""
from utils import get_decrypted_devices, ping_check

if __name__ == "__main__":
    # CLI 调试入口：手动运行时逐台检测设备状态并打印结果
    print("正在测试解密与探测...")
    devices = get_decrypted_devices()
    for d in devices:
        status = "✅ 在线" if ping_check(d['ip']) else "❌ 离线"
        print(f"设备: {d['alias']} ({d['ip']}) -> {status}")
