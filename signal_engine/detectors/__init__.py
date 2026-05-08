"""检测器注册表：统一管理所有信号检测器"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signal_engine.base_detector import BaseDetector
from signal_engine.detectors.catalyst import CatalystDetector
from signal_engine.detectors.chip_concentration import ChipConcentrationDetector
from signal_engine.detectors.demand_inflection import DemandInflectionDetector
from signal_engine.detectors.earnings_inflection import EarningsInflectionDetector
from signal_engine.detectors.north_flow_stock import NorthFlowStockDetector
from signal_engine.detectors.overseas_mapping import OverseasMappingDetector
from signal_engine.detectors.sector_linkage import SectorLinkageDetector
from signal_engine.detectors.supply_shortage import SupplyShortageDetector
from signal_engine.detectors.valuation_percentile import ValuationPercentileDetector
from signal_engine.models import SignalType

DETECTOR_REGISTRY: dict[SignalType, type[BaseDetector]] = {
    SignalType.DEMAND_INFLECTION: DemandInflectionDetector,
    SignalType.SUPPLY_SHORTAGE: SupplyShortageDetector,
    SignalType.EARNINGS_INFLECTION: EarningsInflectionDetector,
    SignalType.CHIP_CONCENTRATION: ChipConcentrationDetector,
    SignalType.OVERSEAS_MAPPING: OverseasMappingDetector,
    SignalType.CATALYST: CatalystDetector,
    SignalType.SECTOR_LINKAGE: SectorLinkageDetector,
    SignalType.NORTH_FLOW_STOCK: NorthFlowStockDetector,
    SignalType.VALUATION_PERCENTILE: ValuationPercentileDetector,
}


def create_all_detectors(
    session_factory: async_sessionmaker[AsyncSession],
    llm_client: Any = None,
) -> list[BaseDetector]:
    """创建所有检测器实例"""
    return [cls(session_factory, llm_client) for cls in DETECTOR_REGISTRY.values()]


def create_detector(
    signal_type: SignalType,
    session_factory: async_sessionmaker[AsyncSession],
    llm_client: Any = None,
) -> BaseDetector:
    """按类型创建单个检测器"""
    cls = DETECTOR_REGISTRY.get(signal_type)
    if cls is None:
        raise ValueError(f"Unknown signal type: {signal_type}")
    return cls(session_factory, llm_client)
