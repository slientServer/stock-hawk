#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/.."
PROJECT_ROOT=$(pwd)

echo "=== Stock Hawk 状态检查 ==="
echo ""

read_pid_setting() {
    local service="$1"
    local key="$2"
    local default_value="$3"
    local file=".pids/${service}.${key}"

    if [ -f "$file" ]; then
        cat "$file"
    else
        echo "$default_value"
    fi
}

service_running() {
    local pid="$1"
    kill -0 "$pid" 2>/dev/null || kill -0 -- "-$pid" 2>/dev/null
}

API_PORT=$(read_pid_setting "api" "port" "${API_PORT:-8010}")
WEB_PORT=$(read_pid_setting "web" "port" "${WEB_PORT:-3010}")

# 1. 检查 Docker 容器状态
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

echo "--- Docker 容器 ---"
$COMPOSE_CMD ps
echo ""

# 2. 检查 API 服务
echo "--- API 服务 ---"
API_PID_FILE=".pids/api.pid"
if [ -f "$API_PID_FILE" ]; then
    API_PID=$(cat "$API_PID_FILE")
    if service_running "$API_PID"; then
        echo "✅ API 服务运行中 (PID: $API_PID, Port: $API_PORT)"
    else
        echo "❌ API 服务未运行 (PID文件存在但进程已退出)"
    fi
else
    echo "❌ API 服务未启动"
fi
echo ""

# 3. 检查 Web 服务
echo "--- Web 服务 ---"
WEB_PID_FILE=".pids/web.pid"
if [ -f "$WEB_PID_FILE" ]; then
    WEB_PID=$(cat "$WEB_PID_FILE")
    if service_running "$WEB_PID"; then
        echo "✅ Web 服务运行中 (PID: $WEB_PID, Port: $WEB_PORT)"
    else
        echo "❌ Web 服务未运行 (PID文件存在但进程已退出)"
    fi
else
    echo "❌ Web 服务未启动"
fi
echo ""

# 4. 健康检查
echo "--- 健康检查 ---"
if command -v curl &> /dev/null; then
    HEALTH_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${API_PORT}/health" 2>/dev/null || true)
    HEALTH_RESPONSE=${HEALTH_RESPONSE:-000}
    if [ "$HEALTH_RESPONSE" = "200" ]; then
        echo "✅ API 健康检查通过"
        curl -s "http://127.0.0.1:${API_PORT}/health" | python3 -m json.tool 2>/dev/null || true
    else
        echo "❌ API 健康检查失败 (HTTP: $HEALTH_RESPONSE)"
    fi

    WEB_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${WEB_PORT}" 2>/dev/null || true)
    WEB_RESPONSE=${WEB_RESPONSE:-000}
    if [ "$WEB_RESPONSE" = "200" ]; then
        echo "✅ Web 首页可访问"
    else
        echo "❌ Web 首页访问失败 (HTTP: $WEB_RESPONSE)"
    fi
else
    echo "⚠️  curl 未安装，跳过健康检查"
fi
echo ""

# 5. 汇总
echo "--- 汇总 ---"
PG_OK="❌"
NEO4J_OK="❌"
REDIS_OK="❌"
API_OK="❌"
WEB_OK="❌"

docker exec stock_hawk_pg pg_isready -U stock_hawk &> /dev/null && PG_OK="✅"
docker exec stock_hawk_redis redis-cli ping &> /dev/null && REDIS_OK="✅"
docker exec stock_hawk_neo4j cypher-shell -u neo4j -p stock_hawk_dev "RETURN 1" &> /dev/null && NEO4J_OK="✅"

if [ -f "$API_PID_FILE" ] && service_running "$(cat "$API_PID_FILE")"; then
    API_OK="✅"
fi
if [ -f "$WEB_PID_FILE" ] && service_running "$(cat "$WEB_PID_FILE")"; then
    WEB_OK="✅"
fi

echo "  PostgreSQL: $PG_OK"
echo "  Neo4j:      $NEO4J_OK"
echo "  Redis:      $REDIS_OK"
echo "  API:        $API_OK"
echo "  Web:        $WEB_OK"
echo ""
