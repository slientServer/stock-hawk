"""止盈止损建议生成"""

from __future__ import annotations

from pre_market.config import PreMarketConfig


class PreMarketAdvisor:
    """为每只选出标的生成操作建议"""

    def __init__(self, config: PreMarketConfig):
        self.config = config

    def generate_aggressive(self, item: dict) -> dict:
        close = float(item.get("close_price", 0))
        if close <= 0:
            return {"target_price": 0, "stop_loss_price": 0, "suggestion": "数据异常"}
        c = self.config
        tp = round(close * (1 + c.agg_take_profit_pct / 100), 2)
        sl = round(close * (1 - c.agg_stop_loss_pct / 100), 2)
        score = item.get("score", 0)
        sector = item.get("catalyst_sector", "")
        strength = item.get("catalyst_strength", 0)
        suggestion = (
            f"【激进标 评分{score}】"
            f"催化板块：{sector}（强度{strength}）。"
            f"建议次日开盘以 {close:.2f} 附近买入，"
            f"目标价 {tp:.2f}(+{c.agg_take_profit_pct}%)，"
            f"止损价 {sl:.2f}(-{c.agg_stop_loss_pct}%)，"
            f"持有不超过{c.max_hold_days}个交易日。"
            f"若次日高开超过3%可考虑直接止盈。"
        )
        return {"target_price": tp, "stop_loss_price": sl, "suggestion": suggestion}

    def generate_stable(self, item: dict) -> dict:
        close = float(item.get("close_price", 0))
        if close <= 0:
            return {"target_price": 0, "stop_loss_price": 0, "suggestion": "数据异常"}
        c = self.config
        tp = round(close * (1 + c.etf_take_profit_pct / 100), 4)
        sl = round(close * (1 - c.etf_stop_loss_pct / 100), 4)
        score = item.get("score", 0)
        direction = item.get("ma5_direction", "flat")
        change_3d = item.get("change_pct_3d", 0)
        suggestion = (
            f"【稳健标 评分{score}】"
            f"MA5方向：{direction}，近3日涨幅{change_3d:.2f}%。"
            f"建议次日开盘以 {close:.4f} 附近买入，"
            f"目标价 {tp:.4f}(+{c.etf_take_profit_pct}%)，"
            f"止损价 {sl:.4f}(-{c.etf_stop_loss_pct}%)，"
            f"持有不超过{c.max_hold_days}个交易日。"
        )
        return {"target_price": tp, "stop_loss_price": sl, "suggestion": suggestion}

    def generate_stable_stock(self, item: dict) -> dict:
        close = float(item.get("close_price", 0))
        if close <= 0:
            return {"target_price": 0, "stop_loss_price": 0, "suggestion": "数据异常"}
        c = self.config
        tp = round(close * (1 + c.etf_take_profit_pct / 100), 2)
        sl = round(close * (1 - c.etf_stop_loss_pct / 100), 2)
        score = item.get("score", 0)
        change_5d = item.get("change_pct_5d", 0)
        amplitude = item.get("avg_amplitude", 0)
        suggestion = (
            f"【稳健个股 评分{score:.1f}】"
            f"近5日涨幅{change_5d:.1f}%，日均振幅{amplitude:.1f}%（低波动）。"
            f"建议次日开盘以 {close:.2f} 附近买入，"
            f"目标价 {tp:.2f}(+{c.etf_take_profit_pct}%)，"
            f"止损价 {sl:.2f}(-{c.etf_stop_loss_pct}%)，"
            f"持有不超过{c.max_hold_days}个交易日。"
        )
        return {"target_price": tp, "stop_loss_price": sl, "suggestion": suggestion}
