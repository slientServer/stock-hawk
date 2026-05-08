import numpy as np
import pandas as pd
from ta.trend import MACD
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands

from common.logger import get_logger

logger = get_logger(__name__)


class TechnicalCalculator:
    """技术指标本地计算器"""

    @staticmethod
    def calculate_macd(close_series: pd.Series) -> dict:
        """计算MACD (12,26,9)"""
        macd = MACD(close_series, window_slow=26, window_fast=12, window_sign=9)
        return {
            "macd": macd.macd().iloc[-1],
            "macd_signal": macd.macd_signal().iloc[-1],
            "macd_hist": macd.macd_diff().iloc[-1],
        }

    @staticmethod
    def calculate_kdj(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 9) -> dict:
        """计算KDJ指标

        参考中国股市标准KDJ算法:
        RSV = (C-L9)/(H9-L9)*100
        K = 2/3*昨日K + 1/3*RSV
        D = 2/3*昨日D + 1/3*K
        J = 3*K - 2*D
        """
        low_min = low.rolling(window=window).min()
        high_max = high.rolling(window=window).max()
        rsv = (close - low_min) / (high_max - low_min) * 100
        rsv = rsv.fillna(50)

        k = pd.Series(index=close.index, dtype=float)
        d = pd.Series(index=close.index, dtype=float)
        k.iloc[0] = 50.0
        d.iloc[0] = 50.0

        for i in range(1, len(close)):
            k.iloc[i] = 2.0 / 3.0 * k.iloc[i - 1] + 1.0 / 3.0 * rsv.iloc[i]
            d.iloc[i] = 2.0 / 3.0 * d.iloc[i - 1] + 1.0 / 3.0 * k.iloc[i]

        j = 3 * k - 2 * d
        return {"kdj_k": k.iloc[-1], "kdj_d": d.iloc[-1], "kdj_j": j.iloc[-1]}

    @staticmethod
    def calculate_rsi(close: pd.Series) -> dict:
        """计算RSI(6,12,24)"""
        rsi6 = RSIIndicator(close, window=6).rsi().iloc[-1]
        rsi12 = RSIIndicator(close, window=12).rsi().iloc[-1]
        rsi24 = RSIIndicator(close, window=24).rsi().iloc[-1]
        return {"rsi_6": rsi6, "rsi_12": rsi12, "rsi_24": rsi24}

    @staticmethod
    def calculate_boll(close: pd.Series, window: int = 20) -> dict:
        """计算布林带"""
        bb = BollingerBands(close, window=window)
        return {
            "boll_upper": bb.bollinger_hband().iloc[-1],
            "boll_mid": bb.bollinger_mavg().iloc[-1],
            "boll_lower": bb.bollinger_lband().iloc[-1],
        }

    def calculate_all(self, df: pd.DataFrame) -> list[dict]:
        """基于K线DataFrame计算所有技术指标

        df必须包含列: trade_date, code, open, close, high, low, volume
        返回每日一条指标记录（需要至少26条数据才能计算MACD）
        """
        if df is None or len(df) < 26:
            logger.warning(f"数据不足26条，无法计算完整技术指标, rows={len(df) if df is not None else 0}")
            return []

        df = df.sort_values("trade_date").reset_index(drop=True)
        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)

        # 计算全序列MACD
        macd_indicator = MACD(close, window_slow=26, window_fast=12, window_sign=9)
        macd_line = macd_indicator.macd()
        macd_signal = macd_indicator.macd_signal()
        macd_hist = macd_indicator.macd_diff()

        # 计算全序列KDJ
        window_kdj = 9
        low_min = low.rolling(window=window_kdj).min()
        high_max = high.rolling(window=window_kdj).max()
        rsv = (close - low_min) / (high_max - low_min) * 100
        rsv = rsv.fillna(50)

        k_series = pd.Series(index=close.index, dtype=float)
        d_series = pd.Series(index=close.index, dtype=float)
        k_series.iloc[0] = 50.0
        d_series.iloc[0] = 50.0
        for i in range(1, len(close)):
            k_series.iloc[i] = 2.0 / 3.0 * k_series.iloc[i - 1] + 1.0 / 3.0 * rsv.iloc[i]
            d_series.iloc[i] = 2.0 / 3.0 * d_series.iloc[i - 1] + 1.0 / 3.0 * k_series.iloc[i]
        j_series = 3 * k_series - 2 * d_series

        # 计算全序列RSI
        rsi6 = RSIIndicator(close, window=6).rsi()
        rsi12 = RSIIndicator(close, window=12).rsi()
        rsi24 = RSIIndicator(close, window=24).rsi()

        # 计算全序列布林带
        bb = BollingerBands(close, window=20)
        boll_upper = bb.bollinger_hband()
        boll_mid = bb.bollinger_mavg()
        boll_lower = bb.bollinger_lband()

        # 从第26行开始输出（确保MACD有效）
        results = []
        start_idx = 25  # 0-indexed, 第26条数据
        code = df["code"].iloc[0] if "code" in df.columns else ""

        for i in range(start_idx, len(df)):
            record = {
                "code": code,
                "trade_date": df["trade_date"].iloc[i],
                "macd": None if pd.isna(macd_line.iloc[i]) else float(macd_line.iloc[i]),
                "macd_signal": None if pd.isna(macd_signal.iloc[i]) else float(macd_signal.iloc[i]),
                "macd_hist": None if pd.isna(macd_hist.iloc[i]) else float(macd_hist.iloc[i]),
                "kdj_k": None if pd.isna(k_series.iloc[i]) else float(k_series.iloc[i]),
                "kdj_d": None if pd.isna(d_series.iloc[i]) else float(d_series.iloc[i]),
                "kdj_j": None if pd.isna(j_series.iloc[i]) else float(j_series.iloc[i]),
                "rsi_6": None if pd.isna(rsi6.iloc[i]) else float(rsi6.iloc[i]),
                "rsi_12": None if pd.isna(rsi12.iloc[i]) else float(rsi12.iloc[i]),
                "rsi_24": None if pd.isna(rsi24.iloc[i]) else float(rsi24.iloc[i]),
                "boll_upper": None if pd.isna(boll_upper.iloc[i]) else float(boll_upper.iloc[i]),
                "boll_mid": None if pd.isna(boll_mid.iloc[i]) else float(boll_mid.iloc[i]),
                "boll_lower": None if pd.isna(boll_lower.iloc[i]) else float(boll_lower.iloc[i]),
            }
            results.append(record)

        return results
