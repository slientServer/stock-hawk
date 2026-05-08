"""Phase 6 验证脚本：API 层"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

PASS = 0
FAIL = 0


def ok(msg: str):
    global PASS
    PASS += 1
    print(f"  [PASS] {msg}")


def fail(msg: str):
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {msg}")


def check(condition: bool, msg: str):
    if condition:
        ok(msg)
    else:
        fail(msg)


# ─── TEST 1: Module imports ────────────────────────────────
def test_imports():
    print("=" * 60)
    print("TEST 1: Module imports")
    print("=" * 60)

    try:
        from api.deps import get_db, get_session_factory
        check(True, "api.deps (get_db, get_session_factory)")
    except Exception as e:
        fail(f"api.deps: {e}")

    route_modules = [
        ("api.routes.advisor", "advisor"),
        ("api.routes.chains", "chains"),
        ("api.routes.signals", "signals"),
        ("api.routes.stocks", "stocks"),
        ("api.routes.backtest", "backtest"),
        ("api.routes.reports", "reports"),
        ("api.routes.graph", "graph"),
        ("api.routes.audit", "audit"),
        ("api.routes.settings", "settings"),
    ]
    for mod, name in route_modules:
        try:
            m = __import__(mod, fromlist=["router"])
            check(hasattr(m, "router"), f"{name} router importable")
        except Exception as e:
            fail(f"{name}: {e}")

    try:
        from api.routes import all_routers
        check(len(all_routers) == 10, f"all_routers has {len(all_routers)} routers (expected 10)")
    except Exception as e:
        fail(f"api.routes.__init__: {e}")

    print()


# ─── TEST 2: FastAPI app creation ──────────────────────────
def test_app():
    print("=" * 60)
    print("TEST 2: FastAPI app creation")
    print("=" * 60)

    from api.main import app

    check(app.title == "Stock Hawk API", "app.title = 'Stock Hawk API'")
    check(app.version == "0.1.0", "app.version = '0.1.0'")

    # 检查路由注册
    routes = [r.path for r in app.routes]
    check("/health" in routes, "/health endpoint registered")
    check(any("/api/chains" in r for r in routes), "/api/chains registered")
    check(any("/api/advisor" in r for r in routes), "/api/advisor registered")
    check(any("/api/signals" in r for r in routes), "/api/signals registered")
    check(any("/api/stocks" in r for r in routes), "/api/stocks registered")
    check(any("/api/backtest" in r for r in routes), "/api/backtest registered")
    check(any("/api/reports" in r for r in routes), "/api/reports registered")
    check(any("/api/graph" in r for r in routes), "/api/graph registered")
    check(any("/api/audit" in r for r in routes), "/api/audit registered")
    check(any("/api/settings" in r for r in routes), "/api/settings registered")

    print()


# ─── TEST 3: Route endpoint counts ────────────────────────
def test_route_counts():
    print("=" * 60)
    print("TEST 3: Route endpoint details")
    print("=" * 60)

    from api.routes.chains import router as chains_r
    from api.routes.advisor import router as advisor_r
    from api.routes.signals import router as signals_r
    from api.routes.stocks import router as stocks_r
    from api.routes.backtest import router as backtest_r
    from api.routes.reports import router as reports_r
    from api.routes.graph import router as graph_r
    from api.routes.audit import router as audit_r
    from api.routes.settings import router as settings_r

    routers = {
        "advisor": advisor_r,
        "chains": chains_r,
        "signals": signals_r,
        "stocks": stocks_r,
        "backtest": backtest_r,
        "reports": reports_r,
        "graph": graph_r,
        "audit": audit_r,
        "settings": settings_r,
    }

    total_endpoints = 0
    for name, r in routers.items():
        count = len(r.routes)
        total_endpoints += count
        check(count >= 2, f"{name}: {count} endpoints")
        for route in r.routes:
            methods = ",".join(route.methods) if hasattr(route, "methods") else "?"
            print(f"    {methods} {route.path}")

    check(total_endpoints >= 20, f"Total: {total_endpoints} endpoints (expected >= 20)")
    print()


# ─── TEST 4: TestClient smoke test ────────────────────────
def test_client():
    print("=" * 60)
    print("TEST 4: TestClient smoke test")
    print("=" * 60)

    try:
        from httpx import ASGITransport, AsyncClient
        from api.main import app
        import asyncio

        async def _test():
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                # Settings (no DB needed)
                resp = await client.get("/api/settings")
                check(resp.status_code == 200, f"GET /api/settings → {resp.status_code}")
                data = resp.json()
                check("database" in data, "settings response has database key")
                check("llm" in data, "settings response has llm key")

                # Chains (may be empty but shouldn't error)
                resp = await client.get("/api/advisor/overview")
                check(resp.status_code == 200, f"GET /api/advisor/overview → {resp.status_code}")

                resp = await client.post(
                    "/api/advisor/stock-analysis/chat",
                    json={"message": "筛选候选股", "use_llm": False},
                )
                check(resp.status_code == 200, f"POST /api/advisor/stock-analysis/chat → {resp.status_code}")

                # Chains (may be empty but shouldn't error)
                resp = await client.get("/api/chains")
                check(resp.status_code == 200, f"GET /api/chains → {resp.status_code}")

                # Signals
                resp = await client.get("/api/signals")
                check(resp.status_code == 200, f"GET /api/signals → {resp.status_code}")
                data = resp.json()
                check("total" in data and "items" in data, "signals has total+items")

                # Stocks
                resp = await client.get("/api/stocks")
                check(resp.status_code == 200, f"GET /api/stocks → {resp.status_code}")

                # Backtest results
                resp = await client.get("/api/backtest/results")
                check(resp.status_code == 200, f"GET /api/backtest/results → {resp.status_code}")

                # Audit stats
                resp = await client.get("/api/audit/stats")
                check(resp.status_code == 200, f"GET /api/audit/stats → {resp.status_code}")
                data = resp.json()
                check("agent_executions" in data, "audit stats has agent_executions")

                # Signal types
                resp = await client.get("/api/signals/types")
                check(resp.status_code == 200, f"GET /api/signals/types → {resp.status_code}")

                # Reports
                resp = await client.get("/api/reports")
                check(resp.status_code == 200, f"GET /api/reports → {resp.status_code}")

        asyncio.run(_test())

    except Exception as e:
        fail(f"TestClient: {e}")
        import traceback
        traceback.print_exc()

    print()


# ─── TEST 5: OpenAPI schema ───────────────────────────────
def test_openapi():
    print("=" * 60)
    print("TEST 5: OpenAPI schema")
    print("=" * 60)

    from api.main import app

    schema = app.openapi()
    check("paths" in schema, "OpenAPI has paths")
    paths = schema["paths"]
    check(len(paths) >= 20, f"OpenAPI has {len(paths)} paths (expected >= 20)")

    # 检查关键路径
    key_paths = [
        "/api/chains",
        "/api/advisor/overview",
        "/api/advisor/stock-analysis/chat",
        "/api/signals",
        "/api/stocks",
        "/api/backtest/run",
        "/api/backtest/results",
        "/api/reports",
        "/api/audit/stats",
        "/api/settings",
    ]
    for p in key_paths:
        check(p in paths, f"OpenAPI has {p}")

    print()


def main():
    print("\n" + "=" * 60)
    print(" Phase 6: Web API - Verification")
    print("=" * 60 + "\n")

    test_imports()
    test_app()
    test_route_counts()
    test_client()
    test_openapi()

    print("=" * 60)
    print(f" Results: {PASS} passed, {FAIL} failed")
    print("=" * 60)

    if FAIL > 0:
        sys.exit(1)
    print(" Phase 6 verification complete!")


if __name__ == "__main__":
    main()
