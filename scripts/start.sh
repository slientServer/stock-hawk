#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/.."
PROJECT_ROOT=$(pwd)

# 解析参数：--api-only 只重启后端，跳过 Docker/迁移/前端
API_ONLY=false
for arg in "$@"; do
  case "$arg" in
    --api-only|-a) API_ONLY=true ;;
  esac
done

if $API_ONLY; then
  echo "=== Stock Hawk 快速重启后端 ==="
else
  echo "=== Stock Hawk 启动 ==="
fi
echo "项目目录: $PROJECT_ROOT"

mkdir -p .pids logs

API_HOST="${API_HOST:-0.0.0.0}"
API_PORT="${API_PORT:-8010}"
WEB_HOST="${WEB_HOST:-127.0.0.1}"
WEB_PORT="${WEB_PORT:-3010}"
NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-http://127.0.0.1:${API_PORT}/api}"
export API_HOST API_PORT WEB_HOST WEB_PORT NEXT_PUBLIC_API_URL

stop_service() {
    local service="$1"
    local pid_file=".pids/${service}.pid"

    if [ ! -f "$pid_file" ]; then
        return
    fi

    local pid
    pid=$(cat "$pid_file")
    if kill -0 "$pid" 2>/dev/null || kill -0 -- "-$pid" 2>/dev/null; then
        echo ">>> 停止已有 ${service} 服务 (PID: $pid)..."
        kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
        for _ in $(seq 1 20); do
            if ! kill -0 "$pid" 2>/dev/null && ! kill -0 -- "-$pid" 2>/dev/null; then
                break
            fi
            sleep 0.2
        done
        if kill -0 "$pid" 2>/dev/null || kill -0 -- "-$pid" 2>/dev/null; then
            echo "❌ ${service} 服务未能正常停止，请手动检查 PID: $pid"
            exit 1
        fi
    fi
    rm -f "$pid_file" ".pids/${service}.port" ".pids/${service}.host"
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
if ! $API_ONLY; then
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

# 3. 执行数据库迁移
echo ">>> 执行数据库迁移..."
if command -v poetry >/dev/null 2>&1; then
    poetry run alembic upgrade head
else
    python -m alembic upgrade head
fi
echo "✅ 数据库迁移完成"
fi # end !API_ONLY

# 4. 启动 FastAPI
stop_service "api"
echo ">>> 启动 API 服务..."
API_PID=$(python -c '
import os
import pathlib
import shutil
import subprocess
import sys

pathlib.Path(".pids").mkdir(exist_ok=True)
pathlib.Path("logs").mkdir(exist_ok=True)

api_host = os.environ.get("API_HOST", "0.0.0.0")
api_port = os.environ.get("API_PORT", "8010")

if shutil.which("poetry"):
    cmd = ["poetry", "run", "uvicorn", "api.main:app", "--host", api_host, "--port", api_port]
else:
    cmd = [sys.executable, "-m", "uvicorn", "api.main:app", "--host", api_host, "--port", api_port]

log = open("logs/api.log", "ab", buffering=0)
proc = subprocess.Popen(
    cmd,
    stdin=subprocess.DEVNULL,
    stdout=log,
    stderr=subprocess.STDOUT,
    start_new_session=True,
)
pathlib.Path(".pids/api.pid").write_text(str(proc.pid))
pathlib.Path(".pids/api.port").write_text(api_port)
pathlib.Path(".pids/api.host").write_text(api_host)
print(proc.pid)
')
echo "✅ API 服务已启动 (PID: $API_PID)"

# 等待 API 就绪
echo ">>> 等待 API 就绪..."
for i in $(seq 1 15); do
    if curl -s "http://127.0.0.1:${API_PORT}/health" > /dev/null 2>&1; then
        echo "✅ API 健康检查通过"
        break
    fi
    sleep 1
done

if $API_ONLY; then
    echo ""
    echo "=============================="
    echo "  后端已重启"
    echo "=============================="
    echo "  API:    http://localhost:${API_PORT}"
    echo "  日志:   tail -f ${PROJECT_ROOT}/logs/api.log"
    echo ""
    exit 0
fi

# 5. 构建并启动 Web
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
web_host = env.get("WEB_HOST", "127.0.0.1")
web_port = env.get("WEB_PORT", "3010")
env["NEXT_PUBLIC_API_URL"] = env.get("NEXT_PUBLIC_API_URL", "http://127.0.0.1:8010/api")

log = open("logs/web.log", "ab", buffering=0)
proc = subprocess.Popen(
    ["npm", "run", "start", "--", "--hostname", web_host, "--port", web_port],
    cwd=root / "web",
    stdin=subprocess.DEVNULL,
    stdout=log,
    stderr=subprocess.STDOUT,
    start_new_session=True,
    env=env,
)
pathlib.Path(".pids/web.pid").write_text(str(proc.pid))
pathlib.Path(".pids/web.port").write_text(web_port)
pathlib.Path(".pids/web.host").write_text(web_host)
print(proc.pid)
')
echo "✅ Web 服务已启动 (PID: $WEB_PID)"

# 6. 打印访问地址
echo ""
echo "=============================="
echo "  Stock Hawk 已启动"
echo "=============================="
echo ""
echo "  Web:    http://localhost:${WEB_PORT}"
echo "  API:    http://localhost:${API_PORT}"
echo "  Health: http://localhost:${API_PORT}/health"
echo "  Docs:   http://localhost:${API_PORT}/docs"
echo ""
echo "  停止服务: bash scripts/stop.sh"
echo ""
