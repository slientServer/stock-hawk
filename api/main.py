from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from neo4j import AsyncGraphDatabase

from agents.automation import AutomationRunner
from agents.scheduler import AgentScheduler
from api.deps import get_session_factory
from api.routes import all_routers
from common.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    session_factory = get_session_factory()
    automation_runner = AutomationRunner(session_factory)
    agent_scheduler = AgentScheduler(session_factory, automation_runner)
    app.state.automation_runner = automation_runner
    app.state.agent_scheduler = agent_scheduler
    agent_scheduler.start()
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
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3010",
        "http://127.0.0.1:3010",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    settings = get_settings()
    status = {"api": "ok", "postgres": "unknown", "neo4j": "unknown", "redis": "unknown"}

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

    # Check Neo4j
    try:
        driver = AsyncGraphDatabase.driver(
            settings.neo4j.uri,
            auth=(settings.neo4j.user, settings.neo4j.password),
        )
        async with driver.session() as session:
            await session.run("RETURN 1")
        await driver.close()
        status["neo4j"] = "ok"
    except Exception as e:
        status["neo4j"] = f"error: {str(e)}"

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
