# Stock Hawk - Claude 工作规范

## 部署规则

**每次完成代码改动后，必须自动执行以下命令重新构建并重启服务：**

```bash
bash scripts/start.sh
```

该脚本会自动完成：Docker 容器检查 → 数据库迁移 → 重启后端 API → 重建前端 → 重启 Web 服务。

### 仅改动前端代码时（更快）

```bash
cd /Users/bytedance/workspace/stock-hawk/web && npm run build && cd .. && bash scripts/start.sh --api-only
```

### 仅改动后端代码时

```bash
bash scripts/start.sh --api-only
```

## 项目结构

- `api/` - FastAPI 后端
- `web/` - Next.js 前端（生产环境，需要构建）
- `scripts/start.sh` - 启动脚本（生产环境）
- `scripts/stop.sh` - 停止脚本
