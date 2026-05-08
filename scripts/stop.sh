#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/.."
PROJECT_ROOT=$(pwd)

echo "=== Stock Hawk 停止 ==="

# 1. 停止 API 进程
if [ -d .pids ]; then
    for pid_file in .pids/*.pid; do
        if [ -f "$pid_file" ]; then
            PID=$(cat "$pid_file")
            SERVICE=$(basename "$pid_file" .pid)
            if kill -0 "$PID" 2>/dev/null; then
                kill "$PID"
                echo "✅ 已停止 $SERVICE (PID: $PID)"
            else
                echo "ℹ️  $SERVICE (PID: $PID) 已经停止"
            fi
            rm -f "$pid_file"
        fi
    done
else
    echo "ℹ️  没有发现运行中的服务 PID"
fi

# 2. 停止 Docker 容器
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

echo ">>> 停止 Docker 容器..."
$COMPOSE_CMD down
echo "✅ Docker 容器已停止"

echo ""
echo "Stock Hawk 已完全停止"
