"""API 路由注册"""

from api.routes.audit import router as audit_router
from api.routes.advisor import router as advisor_router
from api.routes.automation import router as automation_router
from api.routes.backtest import router as backtest_router
from api.routes.chains import router as chains_router
from api.routes.discovery import router as discovery_router
from api.routes.eod_screener import router as eod_screener_router
from api.routes.graph import router as graph_router
from api.routes.reports import router as reports_router
from api.routes.settings import router as settings_router
from api.routes.signals import router as signals_router
from api.routes.stocks import router as stocks_router

all_routers = [
    advisor_router,
    automation_router,
    chains_router,
    signals_router,
    stocks_router,
    backtest_router,
    reports_router,
    graph_router,
    audit_router,
    settings_router,
    discovery_router,
    eod_screener_router,
]
