"""Backtest statistics and weight suggestions."""

import math
from dataclasses import dataclass, field

from backtest.replay import FORWARD_WINDOWS
from signal_engine.models import SIGNAL_WEIGHTS


@dataclass(slots=True)
class BacktestStats:
    signal_type: str
    total_signals: int = 0
    valid_signals: int = 0
    win_rate: dict[int, float] = field(default_factory=dict)
    avg_return: dict[int, float] = field(default_factory=dict)
    median_return: dict[int, float] = field(default_factory=dict)
    max_drawdown: float = 0.0
    avg_drawdown: float = 0.0
    profit_loss_ratio: float = 0.0
    sharpe_ratio: float = 0.0
    strength_buckets: list[dict] = field(default_factory=list)


@dataclass(slots=True)
class WeightSuggestion:
    signal_type: str
    current_weight: float
    suggested_weight: float
    reason: str


class BacktestStatistics:
    def calculate(self, samples, signal_type: str) -> BacktestStats:
        valid = [sample for sample in samples if sample.valid]
        stats = BacktestStats(signal_type=signal_type, total_signals=len(samples), valid_signals=len(valid))
        if not valid:
            return stats

        for window in FORWARD_WINDOWS:
            returns = [sample.returns[window] for sample in valid if window in sample.returns]
            if returns:
                stats.win_rate[window] = sum(1 for value in returns if value > 0) / len(returns)
                stats.avg_return[window] = sum(returns) / len(returns)
                stats.median_return[window] = self._median(returns)

        drawdowns = [sample.max_drawdown for sample in valid]
        stats.max_drawdown = max(drawdowns) if drawdowns else 0.0
        stats.avg_drawdown = sum(drawdowns) / len(drawdowns) if drawdowns else 0.0

        primary_returns = self._primary_returns(valid)
        wins = [value for value in primary_returns if value > 0]
        losses = [-value for value in primary_returns if value < 0]
        if wins and losses:
            stats.profit_loss_ratio = (sum(wins) / len(wins)) / (sum(losses) / len(losses))
        stats.sharpe_ratio = self._sharpe(primary_returns, max(FORWARD_WINDOWS))
        stats.strength_buckets = self._strength_buckets(valid)
        return stats

    def suggest_weights(self, stats_by_type: dict[str, BacktestStats]) -> list[WeightSuggestion]:
        raw_scores = {}
        for signal_type, stats in stats_by_type.items():
            win_rate = stats.win_rate.get(90) or stats.win_rate.get(60) or stats.win_rate.get(30) or 0
            avg_return = stats.avg_return.get(90) or stats.avg_return.get(60) or stats.avg_return.get(30) or 0
            sample_factor = min(1.0, stats.valid_signals / 30) if stats.valid_signals else 0
            risk_penalty = max(0.2, 1 - stats.max_drawdown)
            raw_scores[signal_type] = max(0.0, win_rate * max(avg_return, 0) * sample_factor * risk_penalty)

        total = sum(raw_scores.values())
        suggestions = []
        for signal_type, stats in stats_by_type.items():
            current = self._current_weight(signal_type)
            suggested = raw_scores[signal_type] / total if total > 0 else current
            reason = f"90日胜率 {stats.win_rate.get(90, 0):.1%}，90日均收益 {stats.avg_return.get(90, 0):.1%}"
            suggestions.append(WeightSuggestion(signal_type, current, suggested, reason))
        return suggestions

    def _median(self, values: list[float]) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        mid = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[mid]
        return (ordered[mid - 1] + ordered[mid]) / 2

    def _sharpe(self, returns: list[float], window: int) -> float:
        if not returns:
            return 0.0
        mean = sum(returns) / len(returns)
        if len(returns) < 2:
            return mean
        variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
        std = math.sqrt(variance)
        if std == 0:
            return 0.0
        return mean / std * math.sqrt(365 / max(window, 1))

    @staticmethod
    def _primary_returns(samples) -> list[float]:
        returns = []
        for sample in samples:
            for window in reversed(FORWARD_WINDOWS):
                if window in sample.returns:
                    returns.append(sample.returns[window])
                    break
        return returns

    def _strength_buckets(self, samples) -> list[dict]:
        bucket_defs = [
            ("弱信号", lambda value: value < 0.4),
            ("中等信号", lambda value: 0.4 <= value < 0.7),
            ("强信号", lambda value: value >= 0.7),
        ]
        rows = []
        for name, predicate in bucket_defs:
            group = [sample for sample in samples if predicate(sample.strength)]
            group_returns = self._primary_returns(group)
            rows.append(
                {
                    "strength_range": name,
                    "count": len(group),
                    "win_rate": (sum(1 for value in group_returns if value > 0) / len(group_returns))
                    if group_returns
                    else 0.0,
                    "avg_return": (sum(group_returns) / len(group_returns)) if group_returns else 0.0,
                }
            )
        return rows

    @staticmethod
    def _current_weight(signal_type: str) -> float:
        for key, value in SIGNAL_WEIGHTS.items():
            if key.value == signal_type or str(key) == signal_type:
                return float(value)
        return 0.0
