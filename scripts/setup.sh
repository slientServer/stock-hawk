#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/.."
PROJECT_ROOT=$(pwd)

echo "=== Stock Hawk 一键部署 ==="
echo "项目目录: $PROJECT_ROOT"
echo ""

# 1. 检查 Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker 未安装，请先安装 Docker"
    exit 1
fi
echo "✅ Docker 已安装: $(docker --version)"

# 2. 检查 docker compose
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
else
    echo "❌ docker compose 未安装"
    exit 1
fi
echo "✅ Docker Compose 可用"

# 3. 检查 Python 3.11+
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 未安装"
    exit 1
fi
PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]); then
    echo "❌ Python 版本需要 3.11+，当前: $PYTHON_VERSION"
    exit 1
fi
echo "✅ Python $PYTHON_VERSION"

# 4. 检查 Poetry
if ! command -v poetry &> /dev/null; then
    echo "❌ Poetry 未安装，请执行: curl -sSL https://install.python-poetry.org | python3 -"
    exit 1
fi
echo "✅ Poetry 已安装: $(poetry --version)"

# 5. 复制 .env
if [ ! -f .env ]; then
    cp .env.example .env
    echo "✅ 已创建 .env 文件（从 .env.example 复制）"
else
    echo "ℹ️  .env 文件已存在，跳过"
fi

# 6. 安装 Python 依赖
echo ""
echo ">>> 安装 Python 依赖..."
poetry install
echo "✅ Python 依赖安装完成"

# 7. 启动 Docker 容器
echo ""
echo ">>> 启动 Docker 容器..."
$COMPOSE_CMD up -d
echo "✅ Docker 容器已启动"

# 8. 等待容器健康
echo ""
echo ">>> 等待容器健康..."
TIMEOUT=60
ELAPSED=0
while [ $ELAPSED -lt $TIMEOUT ]; do
    PG_HEALTHY=$($COMPOSE_CMD ps --format json 2>/dev/null | grep -c '"healthy"' || echo "0")
    ALL_RUNNING=$($COMPOSE_CMD ps --status running -q 2>/dev/null | wc -l | tr -d ' ')
    if [ "$ALL_RUNNING" -ge 3 ]; then
        # 简单检查 pg 是否就绪
        if docker exec stock_hawk_pg pg_isready -U stock_hawk &> /dev/null && \
           docker exec stock_hawk_redis redis-cli ping &> /dev/null; then
            echo "✅ 所有容器已就绪"
            break
        fi
    fi
    sleep 2
    ELAPSED=$((ELAPSED + 2))
    echo "  等待中... (${ELAPSED}s/${TIMEOUT}s)"
done

if [ $ELAPSED -ge $TIMEOUT ]; then
    echo "⚠️  容器启动超时，请检查: $COMPOSE_CMD ps"
fi

# 9. 创建 logs 目录
mkdir -p logs
echo "✅ logs 目录已创建"

# 10. 运行 Alembic 迁移（如果已配置）
if [ -f alembic.ini ] && grep -q "sqlalchemy.url" alembic.ini 2>/dev/null; then
    echo ""
    echo ">>> 运行数据库迁移..."
    poetry run alembic upgrade head
    echo "✅ 数据库迁移完成"
else
    echo "ℹ️  Alembic 尚未配置，跳过迁移"
fi

# 11. 打印状态
echo ""
echo "=============================="
echo "  Stock Hawk 部署完成！"
echo "=============================="
echo ""
echo "  PostgreSQL: localhost:5432"
echo "  Neo4j:      localhost:7687 (Web: http://localhost:7474)"
echo "  Redis:      localhost:6379"
echo ""
echo "  启动 API 服务: bash scripts/start.sh"
echo "  查看状态:      bash scripts/status.sh"
echo ""
