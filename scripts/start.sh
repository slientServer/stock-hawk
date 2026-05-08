#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/.."
PROJECT_ROOT=$(pwd)

echo "=== Stock Hawk 启动 ==="
echo "项目目录: $PROJECT_ROOT"

mkdir -p .pids logs

stop_service() {
    local service="$1"
    local pid_file=".pids/${service}.pid"

    if [ ! -f "$pid_file" ]; then
        return
    fi

    local pid
    pid=$(cat "$pid_file")
    if kill -0 "$pid" 2>/dev/null; then
        echo ">>> 停止已有 ${service} 服务 (PID: $pid)..."
        kill "$pid"
        for _ in $(seq 1 20); do
            if ! kill -0 "$pid" 2>/dev/null; then
                break
            fi
            sleep 0.2
        done
        if kill -0 "$pid" 2>/dev/null; then
            echo "❌ ${service} 服务未能正常停止，请手动检查 PID: $pid"
            exit 1
        fi
    fi
    rm -f "$pid_file"
}

find_node_path() {
    if command -v node >/dev/null 2>&1 && node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 20 ? 0 : 1)' >/dev/null 2>&1; then
        dirname "$(command -v node)"
        return 0
    fi

    if [ -n "${NVM_DIR:-}" ] && [ -s "$NVM_DIR/nvm.sh" ]; then
        . "$NVM_DIR/nvm.sh"
        if nvm use 22 >/dev/null 2>&1 || nvm use 20 >/dev/null 2>&1; then
            if node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 20 ? 0 : 1)' >/dev/null 2>&1; then
                dirname "$(command -v node)"
                return 0
            fi
        fi
    fi

    local nvm_latest
    nvm_latest=$(find "$HOME/.nvm/versions/node" -maxdepth 1 -type d -name 'v2[0-9]*' 2>/dev/null | sort | tail -n 1 || true)
    if [ -n "$nvm_latest" ] && [ -x "$nvm_latest/bin/node" ]; then
        echo "$nvm_latest/bin"
        return 0
    fi

    return 1
}

# 1. 启动 Docker 容器
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

echo ">>> 启动 Docker 容器..."
$COMPOSE_CMD up -d

# 2. 等待容器健康
echo ">>> 等待容器就绪..."
TIMEOUT=30
ELAPSED=0
while [ $ELAPSED -lt $TIMEOUT ]; do
    if docker exec stock_hawk_pg pg_isready -U stock_hawk &> /dev/null && \
       docker exec stock_hawk_redis redis-cli ping &> /dev/null; then
        echo "✅ 容器已就绪"
        break
    fi
    sleep 2
    ELAPSED=$((ELAPSED + 2))
done

if [ $ELAPSED -ge $TIMEOUT ]; then
    echo "⚠️  容器启动超时，继续尝试启动服务..."
fi

# 3. 启动 FastAPI
stop_service "api"
echo ">>> 启动 API 服务..."
API_PID=$(python -c '
import pathlib
import shutil
import subprocess
import sys

pathlib.Path(".pids").mkdir(exist_ok=True)
pathlib.Path("logs").mkdir(exist_ok=True)

if shutil.which("poetry"):
    cmd = ["poetry", "run", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
else:
    cmd = [sys.executable, "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

log = open("logs/api.log", "ab", buffering=0)
proc = subprocess.Popen(
    cmd,
    stdin=subprocess.DEVNULL,
    stdout=log,
    stderr=subprocess.STDOUT,
    start_new_session=True,
)
pathlib.Path(".pids/api.pid").write_text(str(proc.pid))
print(proc.pid)
')
echo "✅ API 服务已启动 (PID: $API_PID)"

# 4. 构建并启动 Web
echo ">>> 准备 Web 前端..."
NODE_PATH_DIR=$(find_node_path) || {
    echo "❌ Web 前端需要 Node.js 20+。请安装 Node 20/22，或通过 nvm use 22 后重试。"
    exit 1
}
export PATH="$NODE_PATH_DIR:$PATH"
echo "✅ Node: $(node --version)"

if [ ! -d web/node_modules ]; then
    echo ">>> 安装 Web 依赖..."
    (cd web && npm install)
fi

stop_service "web"
echo ">>> 构建 Web 前端..."
(cd web && npm run build)

echo ">>> 启动 Web 服务..."
WEB_PID=$(python -c '
import os
import pathlib
import subprocess

root = pathlib.Path.cwd()
pathlib.Path(".pids").mkdir(exist_ok=True)
pathlib.Path("logs").mkdir(exist_ok=True)

env = os.environ.copy()
env["NEXT_PUBLIC_API_URL"] = env.get("NEXT_PUBLIC_API_URL", "http://127.0.0.1:8000/api")

log = open("logs/web.log", "ab", buffering=0)
proc = subprocess.Popen(
    ["npm", "run", "start", "--", "--hostname", "127.0.0.1", "--port", "3000"],
    cwd=root / "web",
    stdin=subprocess.DEVNULL,
    stdout=log,
    stderr=subprocess.STDOUT,
    start_new_session=True,
    env=env,
)
pathlib.Path(".pids/web.pid").write_text(str(proc.pid))
print(proc.pid)
')
echo "✅ Web 服务已启动 (PID: $WEB_PID)"

# 5. 打印访问地址
echo ""
echo "=============================="
echo "  Stock Hawk 已启动"
echo "=============================="
echo ""
echo "  Web:    http://localhost:3000"
echo "  API:    http://localhost:8000"
echo "  Health: http://localhost:8000/health"
echo "  Docs:   http://localhost:8000/docs"
echo ""
echo "  停止服务: bash scripts/stop.sh"
echo ""
