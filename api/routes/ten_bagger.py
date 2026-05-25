"""持续上涨股票筛选 API 路由

筛选标准：
  - 最近 6 个月内，月月收涨（环比上月收盘价，至少 4/5 个月为正，可自动降级）
  - 6 个月整体收益为正（最新收盘 > 6M 起点收盘）
  - 非 ST / 退市 / 北交所
  - 市值 ≥ 10 亿
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from agents.llm_client import LLMClient
from api.deps import get_db
from common.logger import get_logger
from common.models import DailyKline, EtfDailyKline

logger = get_logger(__name__)

router = APIRouter(prefix="/ten-bagger", tags=["持续上涨选股"])

# ---------------------------------------------------------------------------
# 主 SQL：计算月环比收益、日涨天数统计
# ---------------------------------------------------------------------------
_SCREENER_SQL = text("""
    WITH klines_6m AS (
        SELECT code, trade_date, CAST(close AS FLOAT) AS close
        FROM daily_klines
        WHERE trade_date >= CURRENT_DATE - INTERVAL '220 days'
          AND close IS NOT NULL
          AND CAST(close AS FLOAT) > 0
    ),
    latest_close AS (
        SELECT DISTINCT ON (code)
            code, close AS latest_close, trade_date AS latest_date
        FROM klines_6m
        ORDER BY code, trade_date DESC
    ),
    start_6m_close AS (
        SELECT DISTINCT ON (code)
            code, close AS start_close, trade_date AS start_date
        FROM klines_6m
        ORDER BY code, trade_date ASC
    ),
    start_3m_close AS (
        SELECT DISTINCT ON (code)
            code, close AS start_3m_close
        FROM klines_6m
        WHERE trade_date >= CURRENT_DATE - INTERVAL '95 days'
        ORDER BY code, trade_date ASC
    ),
    start_1m_close AS (
        SELECT DISTINCT ON (code)
            code, close AS start_1m_close
        FROM klines_6m
        WHERE trade_date >= CURRENT_DATE - INTERVAL '35 days'
        ORDER BY code, trade_date ASC
    ),
    monthly_last AS (
        SELECT DISTINCT ON (code, DATE_TRUNC('month', trade_date))
            code,
            DATE_TRUNC('month', trade_date)::date AS month,
            close AS last_close
        FROM klines_6m
        ORDER BY code, DATE_TRUNC('month', trade_date), trade_date DESC
    ),
    monthly_changes AS (
        SELECT
            code, month, last_close,
            LAG(last_close) OVER (PARTITION BY code ORDER BY month) AS prev_close
        FROM monthly_last
    ),
    monthly_returns AS (
        SELECT
            code, month,
            (last_close - prev_close) / NULLIF(prev_close, 0) * 100 AS return_pct
        FROM monthly_changes
        WHERE prev_close IS NOT NULL
          AND prev_close > 0
          AND month < DATE_TRUNC('month', CURRENT_DATE)::date
    ),
    monthly_stats AS (
        SELECT
            code,
            COUNT(*)                                                          AS total_months,
            SUM(CASE WHEN return_pct > 0 THEN 1 ELSE 0 END)                  AS up_months,
            MIN(return_pct)                                                   AS worst_month_pct,
            MAX(return_pct)                                                   AS best_month_pct,
            -- 各时间窗口内的上涨月数（用于前端"最近N个月"筛选）
            SUM(CASE WHEN return_pct > 0
                      AND month >= (DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '6 months')::date
                 THEN 1 ELSE 0 END)  AS up_w6m,
            SUM(CASE WHEN return_pct > 0
                      AND month >= (DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '5 months')::date
                 THEN 1 ELSE 0 END)  AS up_w5m,
            SUM(CASE WHEN return_pct > 0
                      AND month >= (DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '4 months')::date
                 THEN 1 ELSE 0 END)  AS up_w4m,
            SUM(CASE WHEN return_pct > 0
                      AND month >= (DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '3 months')::date
                 THEN 1 ELSE 0 END)  AS up_w3m,
            SUM(CASE WHEN return_pct > 0
                      AND month >= (DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '2 months')::date
                 THEN 1 ELSE 0 END)  AS up_w2m
        FROM monthly_returns
        GROUP BY code
        HAVING COUNT(*) >= 1
    ),
    daily_changes_1m AS (
        SELECT
            code, trade_date, close,
            LAG(close) OVER (PARTITION BY code ORDER BY trade_date) AS prev_close
        FROM klines_6m
        WHERE trade_date >= CURRENT_DATE - INTERVAL '35 days'
    ),
    daily_stats_1m AS (
        SELECT
            code,
            COUNT(*) FILTER (WHERE prev_close IS NOT NULL)                        AS total_days_1m,
            COUNT(*) FILTER (WHERE prev_close IS NOT NULL AND close > prev_close) AS up_days_1m
        FROM daily_changes_1m
        GROUP BY code
    )
    SELECT
        s.code, s.name, s.industry, s.market,
        CAST(s.market_cap AS FLOAT)   AS market_cap,
        s.listed_date,
        lc.latest_close,
        lc.latest_date,
        sc.start_close,
        sc.start_date,
        CASE WHEN s3.start_3m_close IS NOT NULL AND s3.start_3m_close > 0
             THEN (lc.latest_close - s3.start_3m_close) / s3.start_3m_close * 100
             ELSE NULL END            AS return_3m_pct,
        CASE WHEN s1.start_1m_close IS NOT NULL AND s1.start_1m_close > 0
             THEN (lc.latest_close - s1.start_1m_close) / s1.start_1m_close * 100
             ELSE NULL END            AS return_1m_pct,
        ms.total_months,
        ms.up_months,
        ms.worst_month_pct,
        ms.best_month_pct,
        ms.up_w6m,
        ms.up_w5m,
        ms.up_w4m,
        ms.up_w3m,
        ms.up_w2m,
        COALESCE(d.up_days_1m, 0)    AS up_days_1m,
        COALESCE(d.total_days_1m, 0) AS total_days_1m
    FROM stocks s
    JOIN  latest_close   lc  ON lc.code  = s.code
    JOIN  start_6m_close sc  ON sc.code  = s.code
    LEFT JOIN start_3m_close s3  ON s3.code  = s.code
    LEFT JOIN start_1m_close s1  ON s1.code  = s.code
    JOIN  monthly_stats  ms  ON ms.code  = s.code
    LEFT JOIN daily_stats_1m d   ON d.code   = s.code
    WHERE (s.is_st IS NULL OR s.is_st = FALSE)
      AND (s.market IS NULL OR s.market != 'BJ')
      AND s.market_cap IS NOT NULL
      AND s.market_cap >= :min_market_cap
      AND ms.up_months  >= 1
      AND lc.latest_close > sc.start_close
    ORDER BY ms.up_months DESC,
             (lc.latest_close - sc.start_close) / NULLIF(sc.start_close, 0) DESC
    LIMIT 2000
""")


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------
class RunScreenerRequest(BaseModel):
    filter_mode: str = "4m"  # 6m | 5m | 4m | 3m | 2m | 1m_day


def _qualifies(row: Any, mode: str) -> bool:
    """判断某行数据是否满足指定筛选周期的条件。"""
    if mode == "6m":
        return int(row.up_w6m or 0) >= 5
    if mode == "5m":
        return int(row.up_w5m or 0) >= 4
    if mode == "4m":
        return int(row.up_w4m or 0) >= 3
    if mode == "3m":
        return int(row.up_w3m or 0) >= 2
    if mode == "2m":
        return int(row.up_w2m or 0) >= 1
    if mode == "1m_day":
        total = int(row.total_days_1m or 0)
        up = int(row.up_days_1m or 0)
        return total > 0 and up / total >= 0.8
    return True


def _normalize_code(code: Any) -> str | None:
    text = str(code or "").strip().upper()
    if "." in text:
        text = text.split(".", 1)[0]
    if text.startswith(("SH", "SZ", "BJ")):
        text = text[2:]
    if not text.isdigit():
        return None
    return text.zfill(6)


@router.post("/run")
async def run_rising_screener(
    req: RunScreenerRequest, db: AsyncSession = Depends(get_db)
) -> dict:
    """按指定周期从全市场独立筛选持续上涨的 A 股。"""
    today = date.today()
    min_market_cap = 1_000_000_000  # 10 亿

    result = await db.execute(
        _SCREENER_SQL,
        {"min_market_cap": min_market_cap},
    )
    rows = result.fetchall()

    # 按 filter_mode 独立筛选
    filtered_rows = [row for row in rows if _qualifies(row, req.filter_mode)]

    results = []
    for row in filtered_rows:
        market_cap_val = row.market_cap
        market_cap_yi = round(market_cap_val / 1e8, 2) if market_cap_val else None
        return_6m = (
            round((row.latest_close - row.start_close) / row.start_close * 100, 2)
            if row.start_close and row.start_close > 0
            else None
        )
        results.append(
            {
                "code": row.code,
                "name": row.name,
                "industry": row.industry,
                "market": row.market,
                "market_cap": market_cap_val,
                "market_cap_yi": market_cap_yi,
                "listed_date": row.listed_date.isoformat() if row.listed_date else None,
                "latest_close": round(row.latest_close, 2) if row.latest_close else None,
                "latest_date": row.latest_date.isoformat() if row.latest_date else None,
                "start_close": round(row.start_close, 2) if row.start_close else None,
                "start_date": row.start_date.isoformat() if row.start_date else None,
                "return_6m_pct": return_6m,
                "return_3m_pct": round(row.return_3m_pct, 2) if row.return_3m_pct is not None else None,
                "return_1m_pct": round(row.return_1m_pct, 2) if row.return_1m_pct is not None else None,
                "total_months": int(row.total_months),
                "up_months": int(row.up_months),
                "worst_month_pct": round(row.worst_month_pct, 2) if row.worst_month_pct is not None else None,
                "best_month_pct": round(row.best_month_pct, 2) if row.best_month_pct is not None else None,
                "up_days_1m": int(row.up_days_1m),
                "total_days_1m": int(row.total_days_1m),
                "up_w6m": int(row.up_w6m) if row.up_w6m is not None else 0,
                "up_w5m": int(row.up_w5m) if row.up_w5m is not None else 0,
                "up_w4m": int(row.up_w4m) if row.up_w4m is not None else 0,
                "up_w3m": int(row.up_w3m) if row.up_w3m is not None else 0,
                "up_w2m": int(row.up_w2m) if row.up_w2m is not None else 0,
            }
        )

    # 汇总统计
    returns_valid = [r["return_6m_pct"] for r in results if r["return_6m_pct"] is not None]
    avg_return_6m = round(sum(returns_valid) / len(returns_valid), 2) if returns_valid else None
    up4_count = sum(1 for r in results if r["up_months"] >= 4)
    up5_count = sum(1 for r in results if r["up_months"] >= 5)

    return {
        "run_date": today.isoformat(),
        "filter_mode": req.filter_mode,
        "total_count": len(results),
        "avg_return_6m_pct": avg_return_6m,
        "up4_count": up4_count,
        "up5_count": up5_count,
        "filters": {
            "min_market_cap_yi": int(min_market_cap / 1e8),
            "lookback_days": 220,
            "exclude": ["ST", "退市", "北交所"],
        },
        "results": results,
    }


@router.get("/{code}/kline")
async def get_rising_kline(
    code: str,
    days: int = Query(default=180, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    normalized = _normalize_code(code)
    if not normalized:
        raise HTTPException(status_code=400, detail="股票代码格式不正确")
    rows = (
        await db.execute(
            select(DailyKline)
            .where(DailyKline.code == normalized)
            .order_by(desc(DailyKline.trade_date))
            .limit(days)
        )
    ).scalars().all()

    # 若 daily_klines 无数据，尝试 etf_daily_klines（ETF 数据存在不同表）
    if not rows:
        rows = (
            await db.execute(
                select(EtfDailyKline)
                .where(EtfDailyKline.code == normalized)
                .order_by(desc(EtfDailyKline.trade_date))
                .limit(days)
            )
        ).scalars().all()

    return [
        {
            "trade_date": row.trade_date.isoformat() if row.trade_date else None,
            "open": float(row.open) if row.open is not None else None,
            "close": float(row.close) if row.close is not None else None,
            "high": float(row.high) if row.high is not None else None,
            "low": float(row.low) if row.low is not None else None,
            "volume": row.volume,
            "amount": float(row.amount) if row.amount is not None else None,
        }
        for row in reversed(rows)
    ]


# ---------------------------------------------------------------------------
# AI 分析端点
# ---------------------------------------------------------------------------
class StockAnalyzeRequest(BaseModel):
    code: str
    name: str
    industry: str | None = None
    market_cap_yi: float | None = None
    return_6m_pct: float | None = None
    return_3m_pct: float | None = None
    return_1m_pct: float | None = None
    up_months: int | None = None
    total_months: int | None = None
    latest_close: float | None = None
    start_close: float | None = None
    worst_month_pct: float | None = None
    best_month_pct: float | None = None


@router.post("/analyze")
async def analyze_stock(req: StockAnalyzeRequest) -> dict:
    """使用 AI 分析单只持续上涨股票的优劣势、风险、买入建议。"""
    llm = LLMClient()
    if not llm.is_available():
        return {"error": "LLM 不可用，请先在【设置】中配置 LLM 接入"}

    def _fmt_pct(v: float | None) -> str:
        if v is None:
            return "未知"
        return f"{v:+.1f}%"

    def _fmt_price(v: float | None) -> str:
        if v is None:
            return "未知"
        return f"¥{v:.2f}"

    user_prompt = f"""请基于以下持续上涨 A 股的量化数据，给出简洁的投资分析：

股票信息：
- 代码：{req.code}
- 名称：{req.name}
- 行业：{req.industry or '未知'}
- 市值：{f'{req.market_cap_yi:.1f} 亿' if req.market_cap_yi else '未知'}
- 最新收盘价：{_fmt_price(req.latest_close)}
- 6 个月前起点价：{_fmt_price(req.start_close)}
- 6 月涨幅：{_fmt_pct(req.return_6m_pct)}
- 3 月涨幅：{_fmt_pct(req.return_3m_pct)}
- 1 月涨幅：{_fmt_pct(req.return_1m_pct)}
- 上涨月数：{req.up_months}/{req.total_months} 个月持续上涨
- 最差月涨幅：{_fmt_pct(req.worst_month_pct)}
- 最强月涨幅：{_fmt_pct(req.best_month_pct)}

请严格按如下 JSON 格式输出（每项 2-3 条，简洁有力）：
{{
  "pros": ["优势1", "优势2"],
  "cons": ["劣势1", "劣势2"],
  "risks": ["风险1", "风险2"],
  "buy_recommendation": "建议买入" 或 "谨慎买入" 或 "暂不建议买入",
  "buy_price": "建议买入价格或区间，如 ¥25.00-27.00 或 回调至 ¥xx 附近",
  "summary": "一句话核心结论"
}}

注意：
1. 仅基于量化趋势数据分析，不要捏造未提供的公司基本面信息
2. 若 6 月涨幅超过 50% 需在风险中提示追高风险
3. 买入价应结合最新价和近期趋势给出合理建议（如回调目标位或当前价附近支撑位）
"""

    try:
        result = await llm.chat_json(
            [
                {"role": "system", "content": "你是严谨的 A 股量化投资分析师，只输出 JSON，不附加任何解释文字。"},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=1024,
        )
        return result
    except Exception as e:
        logger.error("AI analysis failed for %s: %s", req.code, e)
        return {"error": str(e)}
