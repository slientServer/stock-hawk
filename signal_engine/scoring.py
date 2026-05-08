"""Scoring engine for chain signals."""

from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal

from signal_engine.models import SIGNAL_WEIGHTS, ScoreDetail, ScoreLevel, ScoreResult, SignalResult, SignalType


class ScoringEngine:
    """Calculate a 0-100 score from real detected signals."""

    decay_lambda = 0.02

    def calculate_score(
        self,
        chain_id: str,
        signals: list[SignalResult],
        score_date: date | None = None,
        market_stage: str = "neutral",
        detector_errors: list[dict[str, str]] | None = None,
    ) -> ScoreResult:
        score_date = score_date or date.today()
        best_by_type: dict[SignalType, ScoreDetail] = {}

        for signal in signals:
            signal_type = signal.signal_type
            weight = SIGNAL_WEIGHTS.get(signal_type, 0)
            age = self._age_days(signal.trigger_date, score_date)
            decay = math.exp(-self.decay_lambda * age)
            contribution = Decimal(str(round(weight * float(signal.strength) * decay * 100, 4)))
            detail = ScoreDetail(
                signal_type=signal_type,
                weight=weight,
                strength=signal.strength,
                confidence=signal.confidence,
                time_decay=decay,
                contribution=contribution,
            )
            previous = best_by_type.get(signal_type)
            if previous is None or contribution > previous.contribution:
                best_by_type[signal_type] = detail

        total = sum((item.contribution for item in best_by_type.values()), Decimal("0"))
        total = max(Decimal("0"), min(Decimal("100"), total.quantize(Decimal("0.01"))))

        return ScoreResult(
            chain_id=chain_id,
            score=total,
            level=self._level(float(total)),
            signal_count=len(signals),
            score_date=score_date,
            details=list(best_by_type.values()),
            detector_errors=detector_errors or [],
        )

    @staticmethod
    def _age_days(trigger_date: datetime | None, score_date: date) -> int:
        if not trigger_date:
            return 0
        return max(0, (score_date - trigger_date.date()).days)

    @staticmethod
    def _level(score: float) -> ScoreLevel:
        if score >= 75:
            return ScoreLevel.STRONG_FOCUS
        if score >= 50:
            return ScoreLevel.FOCUS
        if score >= 30:
            return ScoreLevel.WATCH
        return ScoreLevel.IGNORE
