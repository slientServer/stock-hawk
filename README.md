# Stock Hawk - 智能量化分析系统

## 系统架构

| 组件 | 技术栈 | 默认端口 | 部署方式 |
|------|--------|----------|---------|
| PostgreSQL | 15 | 5432 | Docker |
| Neo4j | 5 Community | 7474 / 7687 | Docker |
| Redis | 7 Alpine | 6379 | Docker |
| API 后端 | FastAPI + Uvicorn | 8010 | 后台进程 |
| Web 前端 | Next.js 16 + React 19 | 3010 | 后台进程 |

## 环境要求

- **Docker** + Docker Compose（v2+）
- **Python 3.11+**（推荐使用 Poetry 管理依赖）
- **Node.js 20+**（推荐通过 nvm 安装）

## 快速部署

### 1. 克隆仓库

```bash
git clone git@github-slientserver:slientServer/stock-hawk.git
cd stock-hawk
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，必须配置项：

| 变量 | 说明 | 必要性 |
|------|------|--------|
| `PG_PASSWORD` | PostgreSQL 密码 | 必填（有默认值） |
| `NEO4J_PASSWORD` | Neo4j 密码 | 必填（有默认值） |
| `CUSTOM_BASE_URL` | LLM API 地址（OpenAI 兼容端点） | 必填 |
| `CUSTOM_API_KEY` | LLM API Key | 必填 |
| `CUSTOM_MODEL` | 模型名称（如 gpt-4o-mini） | 必填 |
| `TUSHARE_TOKEN` | Tushare 数据源 Token | 推荐（财报/K线增强数据） |
| `FEISHU_WEBHOOK_URL` | 飞书 Webhook 通知地址 | 可选 |

完整环境变量参考 `.env.example`。

### 3. 安装依赖

**后端（Python）：**

```bash
# 方式一：Poetry（推荐）
pip install poetry
poetry install

# 方式二：pip
pip install -e .
```

**前端（Node.js）：**

```bash
cd web
npm install
cd ..
```

### 4. 一键启动

```bash
bash scripts/start.sh
```

脚本会自动完成：
1. 启动 Docker 容器（PostgreSQL、Neo4j、Redis）
2. 等待容器健康检查通过
3. 执行数据库迁移（Alembic）
4. 启动 API 后端服务
5. 构建并启动 Web 前端

启动完成后：
- **Web 界面**: http://localhost:3010
- **API 文档**: http://localhost:8010/docs
- **健康检查**: http://localhost:8010/health

可通过环境变量覆盖端口：

```bash
WEB_PORT=3000 API_PORT=8000 bash scripts/start.sh
```

### 5. 停止服务

```bash
bash scripts/stop.sh
```

## 常用运维命令

### 仅重启后端（改动 Python 代码后）

```bash
bash scripts/start.sh --api-only
```

### 仅重建前端（改动前端代码后）

```bash
cd web && npm run build && cd .. && bash scripts/start.sh --api-only
```

### 查看日志

```bash
# API 日志
tail -f logs/api.log

# Web 日志
tail -f logs/web.log
```

### 手动执行数据库迁移

```bash
# Poetry 环境
poetry run alembic upgrade head

# 直接 Python
python -m alembic upgrade head
```

### 查看服务状态

```bash
# 查看进程 PID
cat .pids/api.pid .pids/web.pid

# 查看容器状态
docker compose ps
```

## 目录结构

```
stock-hawk/
├── agents/             # AI Agent 调度器
├── api/                # FastAPI 后端
│   ├── main.py         # 应用入口
│   ├── routes/         # API 路由
│   └── deps.py         # 依赖注入
├── common/             # 共享模块（配置、模型、日志）
├── data_collector/     # 数据采集器
│   ├── sources/        # 各数据源采集实现
│   ├── cache/          # Redis 缓存
│   └── storage.py      # 数据存储层
├── alembic/            # 数据库迁移
├── web/                # Next.js 前端
├── scripts/            # 运维脚本
│   ├── start.sh        # 启动
│   └── stop.sh         # 停止
├── data/               # 持久化数据（Docker 卷、运行时配置）
├── logs/               # 运行日志
├── .pids/              # 进程 PID 文件
├── docker-compose.yml  # 基础设施编排
├── pyproject.toml      # Python 依赖
└── .env.example        # 环境变量模板
```

## 定时任务

系统内置以下定时任务（APScheduler）：

| 任务 | 触发时间 | 说明 |
|------|----------|------|
| 财经资讯拉取 | 每小时 | 抓取财经新闻并生成每日摘要 |
| ETF 轮动分析 | 周一~五 18:30 | 大模型驱动的 ETF 配置建议 |
| 盘前短线选股 | 周一~五 07:00 | AI 盘前候选股筛选 |
| 盘后绩效回填 | 周一~五 16:30 | 回测盘前选股结果 |
| 全市场日K线 | 周一~五 17:00 | 更新当日收盘行情 |
| 主力资金流 | 周一~五 19:00 | 更新当日主力资金数据 |
| 盯盘推送 | 盘中每5分钟 | 持仓+关注列表实时监控 |

所有定时任务均支持在 Web 设置页面手动一键触发。

## 数据初始化

首次部署后，访问 Web 设置页面完成以下步骤：

1. **配置 LLM**：设置页面填写 Custom Base URL / Token / Model，测试连通性
2. **全量初始化**（推荐，一次性采集所有数据）：

```bash
curl -X POST http://localhost:8010/api/stocks/collect \
  -H "Content-Type: application/json" \
  -d '{"task": "collect_all", "days": 365}'
```

或分步执行：

```bash
# 初始化股票池
curl -X POST http://localhost:8010/api/stocks/collect \
  -H "Content-Type: application/json" \
  -d '{"task": "seed_all"}'

# 采集K线历史（365天）
curl -X POST http://localhost:8010/api/stocks/collect \
  -H "Content-Type: application/json" \
  -d '{"task": "seed_klines", "days": 365}'

# 采集股东数据
curl -X POST http://localhost:8010/api/stocks/collect \
  -H "Content-Type: application/json" \
  -d '{"task": "seed_shareholders"}'

# 采集财报数据
curl -X POST http://localhost:8010/api/stocks/collect \
  -H "Content-Type: application/json" \
  -d '{"task": "seed_financials"}'
```

## 数据真实性

系统禁止用模拟数据冒充真实分析输入。缺少 Tushare、LLM 或市场数据源配置时，页面和任务输出会明确标注阻断原因或低置信度。

## 生产环境建议

- 将 `.env` 中的默认密码替换为强密码
- 前端建议通过 Nginx 反向代理，添加 HTTPS
- 定期备份 `data/postgres` 目录
- 设置飞书 Webhook 接收异常通知
- 日志文件建议配置 logrotate 防止磁盘占满

## 验证

```bash
cd web
npm run build
npm run lint
npm run test:e2e
```
