# Stock Hawk Web

Next.js + Ant Design 前端，默认连接 `http://127.0.0.1:8000/api`。

## 开发

```bash
npm install
npm run dev
```

访问 http://localhost:3000。

## 生产构建

```bash
npm run build
npm run start -- --hostname 127.0.0.1 --port 3000
```

项目需要 Node.js 20.17+。如果本机有多个 Node 版本，先执行 `nvm use 22`。

## 端到端验证

先确保后端 API 已启动并健康：

```bash
curl http://127.0.0.1:8000/health
npm run test:e2e
```
