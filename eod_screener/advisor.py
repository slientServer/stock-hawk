"""操作建议生成"""

from __future__ import annotations

from eod_screener.config import EODScreenerConfig


class OperationAdvisor:
    """为每只选出的股票生成具体操作建议"""

    def __init__(self, config: EODScreenerConfig):
        self.config = config

    def generate(self, stock_item: dict) -> dict:
        close = float(stock_item.get("close_price", 0))
        if close <= 0:
            return {"target_price": 0, "stop_loss_price": 0, "suggestion": "数据异常，无法生成建议"}

        tp = round(close * (1 + self.config.take_profit_pct / 100), 2)
        sl = round(close * (1 - self.config.stop_loss_pct / 100), 2)

        score = stock_item.get("score", 0)
        strength = stock_item.get("signal_strength", "中")

        # 根据信号强度调整建议措辞
        if strength == "强":
            position_hint = "可适当加大仓位(不超过总仓位20%)"
        elif strength == "中":
            position_hint = "建议轻仓参与(不超过总仓位10%)"
        else:
            position_hint = "仅观察，谨慎参与"

        suggestion = (
            f"【{strength}信号 评分{score}】"
            f"建议尾盘以 {close:.2f} 元附近买入，"
            f"目标价 {tp:.2f}(+{self.config.take_profit_pct}%)，"
            f"止损价 {sl:.2f}(-{self.config.stop_loss_pct}%)，"
            f"最多持有{self.config.max_hold_days}个交易日。"
            f"{position_hint}。"
            f"次日若高开超过3%可考虑直接止盈。"
        )

        return {
            "target_price": tp,
            "stop_loss_price": sl,
            "suggestion": suggestion,
        }
