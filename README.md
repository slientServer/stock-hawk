# Stock Hawk

智能量化分析系统，提供产业链总览、投研工作台、信号中心、数据管理、研报、回测、知识图谱、审计和系统设置页面。

## 本地启动

```bash
bash scripts/start.sh
```

启动脚本会拉起 PostgreSQL、Neo4j、Redis、FastAPI 和 Next.js Web 服务。访问地址：

- Web: http://localhost:3000
- API: http://localhost:8000
- API Docs: http://localhost:8000/docs

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

系统禁止用模拟数据冒充真实分析输入。缺少 Tushare、LLM 或市场数据源配置时，页面和 Agent 输出应明确标注阻断原因或低置信度。

## 验证

```bash
cd web
npm run build
npm run lint
npm run test:e2e
```
