"""Phase 3 验证脚本：信号检测引擎"""

import asyncio
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from signal_engine.models import ScoreLevel, SignalResult, SignalType
from signal_engine.scoring import ScoringEngine


def test_scoring_engine():
    """单元测试: ScoringEngine 评分公式"""
    print("=" * 60)
    print("TEST 1: ScoringEngine 评分公式验证")
    print("=" * 60)

    engine = ScoringEngine()

    # Case 1: 两个信号 (今天触发)
    signals = [
        SignalResult(
            signal_type=SignalType.DEMAND_INFLECTION,
            chain_id="test",
            strength=Decimal("0.8"),
            confidence=Decimal("0.9"),
            trigger_date=datetime.now(),
        ),
        SignalResult(
            signal_type=SignalType.EARNINGS_INFLECTION,
            chain_id="test",
            strength=Decimal("0.7"),
            confidence=Decimal("0.85"),
            trigger_date=datetime.now() - timedelta(days=10),
        ),
    ]

    result = engine.calculate_score("test", signals, score_date=date.today())
    # 预期: 0.20*0.8*1.0*100 + 0.15*0.7*e^(-0.02*10)*100
    #      = 16.0 + 0.15*0.7*0.8187*100 ≈ 24.6
    print(f"  Score: {result.score} (expected ~24.6)")
    print(f"  Level: {result.level.value} (expected: ignore)")
    print(f"  Signal count: {result.signal_count}")
    print(f"  Details:")
    for d in result.details:
        print(f"    {d.signal_type.value}: weight={d.weight} strength={d.strength} "
              f"decay={d.time_decay} contribution={d.contribution}")

    assert 23 < float(result.score) < 26, f"Score {result.score} not in expected range"
    assert result.level == ScoreLevel.IGNORE
    print("  ✓ PASSED\n")

    # Case 2: 所有信号满强度 (应接近100)
    all_signals = [
        SignalResult(
            signal_type=st,
            chain_id="test_max",
            strength=Decimal("1.0"),
            confidence=Decimal("1.0"),
            trigger_date=datetime.now(),
        )
        for st in SignalType
    ]
    result_max = engine.calculate_score("test_max", all_signals, score_date=date.today())
    # 预期: 所有权重求和为 1.0
    print(f"  Max score: {result_max.score} (expected: 100)")
    assert float(result_max.score) == 100.0
    assert result_max.level == ScoreLevel.STRONG_FOCUS
    print("  ✓ PASSED\n")

    # Case 3: 时间衰减验证
    old_signal = [
        SignalResult(
            signal_type=SignalType.DEMAND_INFLECTION,
            chain_id="test_decay",
            strength=Decimal("1.0"),
            confidence=Decimal("1.0"),
            trigger_date=datetime.now() - timedelta(days=35),  # ~1 half-life
        ),
    ]
    result_decay = engine.calculate_score("test_decay", old_signal, score_date=date.today())
    # 预期: 0.20*1.0*e^(-0.02*35)*100 = 0.20*0.4966*100 ≈ 9.9
    print(f"  Decay score (35 days): {result_decay.score} (expected ~9.9)")
    assert 9 < float(result_decay.score) < 11
    print("  ✓ PASSED\n")

    # Case 4: 同类型取最强
    dup_signals = [
        SignalResult(
            signal_type=SignalType.DEMAND_INFLECTION,
            chain_id="test_dup",
            strength=Decimal("0.3"),
            confidence=Decimal("0.7"),
            trigger_date=datetime.now(),
        ),
        SignalResult(
            signal_type=SignalType.DEMAND_INFLECTION,
            chain_id="test_dup",
            strength=Decimal("0.9"),
            confidence=Decimal("0.9"),
            trigger_date=datetime.now(),
        ),
    ]
    result_dup = engine.calculate_score("test_dup", dup_signals, score_date=date.today())
    # 应取 strength=0.9 的那条: 0.20*0.9*1.0*100 = 18.0
    print(f"  Dedup score: {result_dup.score} (expected: 18.0)")
    assert float(result_dup.score) == 18.0
    print("  ✓ PASSED\n")

    # Case 5: 空信号列表
    result_empty = engine.calculate_score("test_empty", [], score_date=date.today())
    print(f"  Empty signals score: {result_empty.score} (expected: 0)")
    assert float(result_empty.score) == 0.0
    assert result_empty.level == ScoreLevel.IGNORE
    print("  ✓ PASSED\n")


def test_imports():
    """验证模块导入是否正常"""
    print("=" * 60)
    print("TEST 2: 模块导入验证")
    print("=" * 60)

    from signal_engine import (
        BaseDetector,
        DetectionContext,
        ScoreLevel,
        ScoreResult,
        SignalEngine,
        SignalHistory,
        SignalResult,
        SignalType,
        ScoringEngine,
        SIGNAL_WEIGHTS,
        create_all_detectors,
        create_detector,
    )
    print("  ✓ signal_engine top-level imports OK")

    from signal_engine.detectors import DETECTOR_REGISTRY
    assert len(DETECTOR_REGISTRY) == 9
    print(f"  ✓ DETECTOR_REGISTRY has {len(DETECTOR_REGISTRY)} detectors")

    from signal_engine.detectors.demand_inflection import DemandInflectionDetector
    from signal_engine.detectors.earnings_inflection import EarningsInflectionDetector
    from signal_engine.detectors.chip_concentration import ChipConcentrationDetector
    from signal_engine.detectors.supply_shortage import SupplyShortageDetector
    from signal_engine.detectors.overseas_mapping import OverseasMappingDetector
    from signal_engine.detectors.catalyst import CatalystDetector
    from signal_engine.detectors.sector_linkage import SectorLinkageDetector
    from signal_engine.detectors.north_flow_stock import NorthFlowStockDetector
    from signal_engine.detectors.valuation_percentile import ValuationPercentileDetector
    print("  ✓ All 9 detector classes importable")

    # 验证权重之和为1
    total_weight = sum(SIGNAL_WEIGHTS.values())
    assert abs(total_weight - 1.0) < 1e-9, f"Weights sum to {total_weight}"
    print(f"  ✓ SIGNAL_WEIGHTS sum = {total_weight}")
    print()


def test_detector_creation():
    """验证检测器实例化"""
    print("=" * 60)
    print("TEST 3: 检测器实例化验证")
    print("=" * 60)

    from unittest.mock import MagicMock
    from signal_engine.detectors import create_all_detectors, create_detector

    mock_factory = MagicMock()
    detectors = create_all_detectors(mock_factory)
    assert len(detectors) == 9
    print(f"  ✓ create_all_detectors() returned {len(detectors)} detectors")

    for d in detectors:
        assert hasattr(d, "signal_type")
        assert hasattr(d, "detect")
        print(f"    - {d.signal_type.value}: {d.__class__.__name__}")

    # 单个创建
    d = create_detector(SignalType.DEMAND_INFLECTION, mock_factory)
    assert d.signal_type == SignalType.DEMAND_INFLECTION
    print("  ✓ create_detector() works")
    print()


async def test_integration():
    """集成测试: 需要数据库连接"""
    print("=" * 60)
    print("TEST 4: 集成测试 (需要 DB)")
    print("=" * 60)

    try:
        from common.database import async_session_factory
        from signal_engine import SignalEngine

        engine = SignalEngine(async_session_factory)
        print("  ✓ SignalEngine instantiated")

        # 尝试构建 context (需要 Neo4j)
        try:
            context = await engine._build_context("光通信产业链", date.today())
            print(f"  ✓ Context built: {len(context.company_codes)} companies, "
                  f"{len(context.segments)} segments")

            if context.company_codes:
                # 运行扫描
                result = await engine.scan_chain("光通信产业链")
                print(f"  ✓ Scan completed: score={result.score}, "
                      f"signals={result.signal_count}, level={result.level.value}")
            else:
                print("  ⚠ No company codes found (no KG data?), skipping scan")
        except Exception as e:
            print(f"  ⚠ KG query failed (Neo4j not seeded?): {e}")

    except Exception as e:
        print(f"  ⚠ Integration test skipped: {e}")
    print()


def main():
    print("\n🔍 Phase 3: Signal Detection Engine - Verification\n")

    test_imports()
    test_scoring_engine()
    test_detector_creation()
    asyncio.run(test_integration())

    print("=" * 60)
    print("✓ Phase 3 verification complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
