"""北向个股检测：北向资金重点流入个股信号"""

import asyncio
from datetime import date, timedelta

import pandas as pd

from common.logger import get_logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signal_engine.base_detector import BaseDetector
from signal_engine.models import DetectionContext, SignalResult, SignalType

logger = get_logger(__name__)

NET_BUY_THRESHOLD = 5000  # 万元
TOP_N = 50


class NorthFlowStockDetector(BaseDetector):
    """北向个股检测器

    逻辑: 产业链内个股出现在北向资金净买入 Top50，或净买入 > 5000 万
    """

    signal_type = SignalType.NORTH_FLOW_STOCK

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], llm_client=None):
        super().__init__(session_factory, llm_client)

    async def _detect_impl(self, context: DetectionContext) -> list[SignalResult]:
        if not context.company_codes:
            return []

        north_data = await self._fetch_north_holdings(context.run_date)
        if north_data is None or north_data.empty:
            logger.info("north_flow_stock: 无法获取北向持仓数据")
            return []

        signals: list[SignalResult] = []

        for code in context.company_codes:
            stock_data = north_data[north_data["code"] == code]
            if stock_data.empty:
                continue

            row = stock_data.iloc[0]
            net_buy = float(row.get("net_buy", 0) or 0)
            rank = int(row.get("rank", 999) or 999)

            if net_buy <= 0:
                continue

            if net_buy >= NET_BUY_THRESHOLD or rank <= TOP_N:
                strength = self._clamp(net_buy / 20000, 0.3, 1.0)
                if rank <= 10:
                    strength = self._clamp(strength * 1.3, 0.3, 1.0)

                confidence = 0.7 if rank <= TOP_N else 0.5

                signals.append(
                    self._make_signal(
                        chain_id=context.chain_id,
                        source_entity=code,
                        target_codes=[code],
                        strength=strength,
                        confidence=confidence,
                        detail=(f"{code} 北向资金净买入{net_buy:.0f}万元" f"（排名第{rank}），资金面看好"),
                        raw_data_ref=f"north_flow:{code}:{context.run_date}",
                        expire_days=7,
                    )
                )

        return signals

    async def _fetch_north_holdings(self, as_of: date) -> pd.DataFrame | None:
        """获取北向资金个股持仓变动"""
        try:
            import akshare as ak

            df = await asyncio.to_thread(ak.stock_hsgt_hold_stock_em, market="北向", indicator="今日排行")
            if df is None or df.empty:
                return None

            date_col = next((c for c in df.columns if c == "日期" or "日期" in c), None)
            if date_col:
                data_dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
                if not data_dates.empty:
                    latest_data_date = data_dates.max().date()
                    if latest_data_date < as_of - timedelta(days=7):
                        logger.info(f"north_flow_stock: 北向排行数据过旧 latest={latest_data_date} as_of={as_of}")
                        return None

            result = pd.DataFrame()
            # 标准化列名
            code_col = next((c for c in df.columns if "代码" in c), None)
            net_col = next(
                (
                    c
                    for c in df.columns
                    if ("净买" in c or "净流入" in c or "增持" in c)
                    and ("市值" in c or "金额" in c)
                    and "占" not in c
                    and "增幅" not in c
                ),
                None,
            )

            if code_col is None:
                return None

            result["code"] = df[code_col].astype(str)
            if net_col:
                result["net_buy"] = pd.to_numeric(df[net_col], errors="coerce").fillna(0) / 10000  # 转万元
            else:
                result["net_buy"] = 0

            result = result.sort_values("net_buy", ascending=False).reset_index(drop=True)
            result["rank"] = result.index + 1

            return result
        except Exception as e:
            logger.warning(f"获取北向个股数据失败: {e}")
            return None
