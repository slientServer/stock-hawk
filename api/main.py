import os
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agents.scheduler import AgentScheduler
from api.deps import get_session_factory
from api.routes import all_routers
from common.config import get_settings


def get_cors_origins() -> list[str]:
    origins = {
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3010",
        "http://127.0.0.1:3010",
    }
    web_port = os.environ.get("WEB_PORT")
    if web_port:
        origins.add(f"http://localhost:{web_port}")
        origins.add(f"http://127.0.0.1:{web_port}")

    for origin in os.environ.get("CORS_ORIGINS", "").split(","):
        origin = origin.strip()
        if origin:
            origins.add(origin)

    return sorted(origins)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    session_factory = get_session_factory()
    agent_scheduler = AgentScheduler(session_factory)
    app.state.agent_scheduler = agent_scheduler
    agent_scheduler.start()

    # 启动时异步预热 ETF 实时行情缓存，避免首次访问返回空数据
    async def _warmup_etf_spot():
        try:
            from api.routes.etf_analysis import _fetch_etf_spot_cached
            await _fetch_etf_spot_cached(wait_timeout=30.0, force_refresh=True)
        except Exception:
            pass

    asyncio.create_task(_warmup_etf_spot())

    try:
        yield
    finally:
        agent_scheduler.stop()


app = FastAPI(
    title="Stock Hawk API",
    description="智能量化分析系统",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    settings = get_settings()
    status = {"api": "ok", "postgres": "unknown", "redis": "unknown"}

    # Check PostgreSQL
    try:
        import asyncpg

        conn = await asyncpg.connect(
            host=settings.db.host,
            port=settings.db.port,
            user=settings.db.user,
            password=settings.db.password,
            database=settings.db.db,
        )
        await conn.execute("SELECT 1")
        await conn.close()
        status["postgres"] = "ok"
    except Exception as e:
        status["postgres"] = f"error: {str(e)}"

    # Check Redis
    try:
        r = aioredis.from_url(settings.redis.url)
        await r.ping()
        await r.aclose()
        status["redis"] = "ok"
    except Exception as e:
        status["redis"] = f"error: {str(e)}"

    all_ok = all(v == "ok" for v in status.values())
    return {"status": "healthy" if all_ok else "degraded", "services": status}


for router in all_routers:
    app.include_router(router, prefix="/api")
