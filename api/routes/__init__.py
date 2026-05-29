"""API 路由注册：仅保留当前产品功能。"""

from api.routes.etf_analysis import router as etf_analysis_router
from api.routes.news_center import router as news_center_router
from api.routes.portfolio import router as portfolio_router
from api.routes.pre_market import router as pre_market_router
from api.routes.settings import router as settings_router
from api.routes.stocks import router as stocks_router
from api.routes.ten_bagger import router as ten_bagger_router
from api.routes.watchlist import router as watchlist_router

all_routers = [
    etf_analysis_router,
    news_center_router,
    portfolio_router,
    pre_market_router,
    settings_router,
    stocks_router,
    ten_bagger_router,
    watchlist_router,
]
