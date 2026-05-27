#!/usr/bin/env python3
"""
网络自动化运维平台 - Web 入口
"""
import os
import hashlib
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_socketio import SocketIO

# 密码哈希（SHA256），明文 admin123 对应的哈希值
ADMIN_PASSWORD_HASH = "240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9"

# 导入所有拆分好的 API 蓝图 (Blueprint)
from api_inventory import inventory_bp
from api_backup import backup_bp
from api_deploy import deploy_bp
from api_check_rollback import check_bp
from api_report import report_bp
from api_logs import logs_bp
from api_status import status_bp, init_status_monitor
from api_drift_history import drift_bp

app = Flask(__name__)
app.secret_key = 'super_secret_key_for_network_tool'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# ========== 核心路径配置 ==========
WEB_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(WEB_DIR)

# 强制切换工作目录到项目根目录
# 确保底层 Ansible 脚本能正确找到 inventory.yml 和 vault_pass.txt
os.chdir(PROJECT_ROOT) 

# ========== 注册 API 蓝图 ==========
# 将后端的模块 API 全部挂载到主程序上
app.register_blueprint(inventory_bp)
app.register_blueprint(backup_bp)
app.register_blueprint(deploy_bp)
app.register_blueprint(check_bp)
app.register_blueprint(report_bp)
app.register_blueprint(logs_bp)
app.register_blueprint(status_bp)
app.register_blueprint(drift_bp)

# 将 socketio 实例传入，这样后台脚本发现状态变化时可以直接 emit 推送
# 只在子进程中启动定时任务，避免 reloader 导致重复执行
if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
    init_status_monitor(socketio)

# ========== 页面路由 (负责调度前端 HTML) ==========

@app.route('/')
def index():
    # 默认访问根目录时，重定向到登录页
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    # 处理登录请求
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        if username == 'admin' and password_hash == ADMIN_PASSWORD_HASH:
            return redirect(url_for('dashboard'))
        flash('❌ 用户名或密码错误', 'danger')
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

@app.route('/inventory')
def inventory():
    return render_template('inventory.html')

@app.route('/backup')
def backup():
    return render_template('backup.html')

@app.route('/deploy')
def deploy():
    return render_template('deploy.html')

@app.route('/rollback')
def rollback():
    return render_template('rollback.html')

@app.route('/report')
def report():
    return render_template('report.html')

if __name__ == '__main__':
    print(" NetAuto 实时运维服务正在启动...")
    print("巡检频率: 每 20 秒一次")

    # 必须使用 socketio.run 
    # 这样才能启动支持长连接的服务器，否则实时推送功能会失效
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, use_reloader=True)
