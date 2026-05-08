"""Signal engine data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any


class SignalType(str, Enum):
    DEMAND_INFLECTION = "demand_inflection"
    SUPPLY_SHORTAGE = "supply_shortage"
    EARNINGS_INFLECTION = "earnings_inflection"
    CHIP_CONCENTRATION = "chip_concentration"
    OVERSEAS_MAPPING = "overseas_mapping"
    CATALYST = "catalyst"
    NORTH_FLOW_STOCK = "north_flow_stock"
    SECTOR_LINKAGE = "sector_linkage"
    VALUATION_PERCENTILE = "valuation_percentile"


class ScoreLevel(str, Enum):
    IGNORE = "ignore"
    WATCH = "watch"
    FOCUS = "focus"
    STRONG_FOCUS = "strong_focus"


SIGNAL_WEIGHTS: dict[SignalType, float] = {
    SignalType.DEMAND_INFLECTION: 0.20,
    SignalType.SUPPLY_SHORTAGE: 0.15,
    SignalType.EARNINGS_INFLECTION: 0.15,
    SignalType.CHIP_CONCENTRATION: 0.10,
    SignalType.OVERSEAS_MAPPING: 0.10,
    SignalType.CATALYST: 0.10,
    SignalType.SECTOR_LINKAGE: 0.10,
    SignalType.NORTH_FLOW_STOCK: 0.05,
    SignalType.VALUATION_PERCENTILE: 0.05,
}


def as_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


@dataclass(slots=True)
class DetectionContext:
    chain_id: str
    chain_name: str
    company_codes: list[str] = field(default_factory=list)
    segments: list[dict[str, Any]] = field(default_factory=list)
    run_date: date = field(default_factory=date.today)


@dataclass(slots=True)
class SignalResult:
    signal_type: SignalType
    chain_id: str
    strength: Decimal
    confidence: Decimal = Decimal("0.6")
    source_entity: str | None = None
    target_codes: list[str] = field(default_factory=list)
    detail: str = ""
    raw_data_ref: str | None = None
    trigger_date: datetime = field(default_factory=datetime.now)
    expire_date: datetime | None = None
    source: str = "signal_engine"

    def __post_init__(self) -> None:
        if not isinstance(self.signal_type, SignalType):
            self.signal_type = SignalType(str(self.signal_type))
        self.strength = as_decimal(self.strength)
        self.confidence = as_decimal(self.confidence, default="0.6")
        if self.expire_date is None:
            self.expire_date = self.trigger_date + timedelta(days=30)

    def to_record(self) -> dict[str, Any]:
        return {
            "signal_type": self.signal_type.value,
            "chain_id": self.chain_id,
            "source_entity": self.source_entity,
            "target_codes": list(self.target_codes or []),
            "strength": self.strength,
            "confidence": self.confidence,
            "detail": self.detail,
            "raw_data_ref": self.raw_data_ref,
            "trigger_date": self.trigger_date,
            "expire_date": self.expire_date,
            "source": self.source,
        }


@dataclass(slots=True)
class ScoreDetail:
    signal_type: SignalType
    weight: float
    strength: Decimal
    confidence: Decimal
    time_decay: float
    contribution: Decimal

    def to_json(self) -> dict[str, Any]:
        return {
            "signal_type": self.signal_type.value,
            "weight": self.weight,
            "strength": float(self.strength),
            "confidence": float(self.confidence),
            "time_decay": round(self.time_decay, 4),
            "contribution": float(self.contribution),
        }


@dataclass(slots=True)
class ScoreResult:
    chain_id: str
    score: Decimal
    level: ScoreLevel
    signal_count: int
    score_date: date
    details: list[ScoreDetail] = field(default_factory=list)
    detector_errors: list[dict[str, str]] = field(default_factory=list)

    def to_record(self) -> dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "score": self.score,
            "score_detail": {
                "level": self.level.value,
                "details": [item.to_json() for item in self.details],
                "detector_errors": self.detector_errors,
            },
            "signal_count": self.signal_count,
            "score_date": self.score_date,
        }
