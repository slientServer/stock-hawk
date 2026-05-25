# Stock Hawk

智能量化分析系统，当前保留 ETF 分析、持续上涨筛选、资讯中心和配置中心。

资讯中心会按小时拉取财经源，使用已配置的大模型对真实入库资讯做去重汇总，生成今日财经小结并保留历史。未配置 LLM 时会降级为规则化小结，并明确标注数据缺口。

## 本地启动

```bash
bash scripts/start.sh
```

启动脚本会拉起 PostgreSQL、Neo4j、Redis、FastAPI 和 Next.js Web 服务。访问地址：

- Web: http://localhost:3010
- API: http://localhost:8010
- API Docs: http://localhost:8010/docs

可通过环境变量覆盖端口：

```bash
WEB_PORT=3000 API_PORT=8000 bash scripts/start.sh
```

查看状态：

```bash
bash scripts/status.sh
```

停止服务：

```bash
bash scripts/stop.sh
```

## 环境要求

- Docker / Docker Compose
- Python 3.11+
- Node.js 20.17+ 或 22.x

首次部署可先运行：

```bash
bash scripts/setup.sh
```

## 数据真实性

系统禁止用模拟数据冒充真实分析输入。缺少 Tushare、LLM 或市场数据源配置时，页面和任务输出应明确标注阻断原因或低置信度。

## 验证

```bash
cd web
npm run build
npm run lint
npm run test:e2e
```
