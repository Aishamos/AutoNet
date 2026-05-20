#!/bin/bash
# 此脚本只负责激活虚拟环境
VENV_PATH="/home/you/network/venv"

if [ -f "$VENV_PATH/bin/activate" ]; then
    source "$VENV_PATH/bin/activate"
    export PATH="$VENV_PATH/bin:$PATH"
    echo "虚拟环境已激活，当前 Python: $(which python)"
else
    echo "错误：未找到虚拟环境 $VENV_PATH"
    return 1
fi

cd "$(dirname "$0")" || exit 1
mkdir -p logs/cron_logs
python3 backup_now.py >> logs/cron_logs/backup_cron.log 2>&1
