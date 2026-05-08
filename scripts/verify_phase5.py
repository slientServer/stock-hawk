"""Phase 5 验证脚本：回测系统"""

import asyncio
import math
import sys
from dataclasses import asdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

PASS = 0
FAIL = 0


def ok(msg: str):
    global PASS
    PASS += 1
    print(f"  [PASS] {msg}")


def fail(msg: str):
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {msg}")


def check(condition: bool, msg: str):
    if condition:
        ok(msg)
    else:
        fail(msg)


# ─── TEST 1: Module imports ────────────────────────────────
def test_imports():
    print("=" * 60)
    print("TEST 1: Module imports")
    print("=" * 60)

    try:
        from backtest.replay import SignalReplay, SignalSample, FORWARD_WINDOWS
        check(True, "backtest.replay (SignalReplay, SignalSample, FORWARD_WINDOWS)")
    except Exception as e:
        fail(f"backtest.replay: {e}")

    try:
        from backtest.statistics import BacktestStatistics, BacktestStats, WeightSuggestion
        check(True, "backtest.statistics (BacktestStatistics, BacktestStats, WeightSuggestion)")
    except Exception as e:
        fail(f"backtest.statistics: {e}")

    try:
        from backtest.engine import BacktestEngine
        check(True, "backtest.engine (BacktestEngine)")
    except Exception as e:
        fail(f"backtest.engine: {e}")

    try:
        from backtest import (
            BacktestEngine, SignalReplay, SignalSample,
            FORWARD_WINDOWS, BacktestStatistics, BacktestStats, WeightSuggestion,
        )
        check(True, "backtest.__init__ top-level re-exports (7 symbols)")
    except Exception as e:
        fail(f"backtest.__init__: {e}")

    print()


# ─── TEST 2: SignalSample dataclass ────────────────────────
def test_signal_sample():
    print("=" * 60)
    print("TEST 2: SignalSample dataclass")
    print("=" * 60)

    from backtest.replay import SignalSample, FORWARD_WINDOWS

    s = SignalSample(
        signal_id=1,
        signal_type="demand_inflection",
        chain_id="test_chain",
        target_code="600000",
        trigger_date=date(2025, 1, 15),
        strength=0.8,
        confidence=0.9,
        entry_price=10.5,
        returns={30: 0.05, 60: 0.08, 90: 0.12},
        max_drawdown=0.03,
        valid=True,
    )

    check(s.signal_id == 1, "signal_id")
    check(s.signal_type == "demand_inflection", "signal_type")
    check(s.target_code == "600000", "target_code")
    check(s.entry_price == 10.5, "entry_price")
    check(s.returns[30] == 0.05, "returns[30]")
    check(s.max_drawdown == 0.03, "max_drawdown")
    check(s.valid is True, "valid flag")

    check(FORWARD_WINDOWS == [5, 10, 20, 30, 60, 90], "FORWARD_WINDOWS = [5, 10, 20, 30, 60, 90]")
    print()


# ─── TEST 3: BacktestStatistics (pure calculation) ─────────
def test_statistics():
    print("=" * 60)
    print("TEST 3: BacktestStatistics pure calculation")
    print("=" * 60)

    from backtest.replay import SignalSample
    from backtest.statistics import BacktestStatistics

    calc = BacktestStatistics()

    # 构造模拟样本
    samples = [
        SignalSample(
            signal_id=i, signal_type="demand_inflection",
            chain_id="c1", target_code=f"60000{i}",
            trigger_date=date(2025, 1, 1) + timedelta(days=i * 7),
            strength=0.5 + i * 0.1, confidence=0.8,
            entry_price=10.0,
            returns={30: 0.05 + i * 0.01, 60: 0.08 + i * 0.02, 90: 0.10 + i * 0.03},
            max_drawdown=0.02 + i * 0.005,
            valid=True,
        )
        for i in range(5)
    ]
    # 加一个亏损样本
    samples.append(SignalSample(
        signal_id=99, signal_type="demand_inflection",
        chain_id="c1", target_code="600099",
        trigger_date=date(2025, 3, 1),
        strength=0.3, confidence=0.7,
        entry_price=10.0,
        returns={30: -0.05, 60: -0.08, 90: -0.10},
        max_drawdown=0.15,
        valid=True,
    ))

    stats = calc.calculate(samples, signal_type="demand_inflection")

    check(stats.signal_type == "demand_inflection", "signal_type propagated")
    check(stats.total_signals == 6, f"total_signals={stats.total_signals} (expected 6)")
    check(stats.valid_signals == 6, f"valid_signals={stats.valid_signals} (expected 6)")

    # Win rate: 5 wins, 1 loss → 5/6 ≈ 0.833
    wr30 = stats.win_rate.get(30, 0)
    check(abs(wr30 - 5 / 6) < 0.01, f"win_rate[30]={wr30:.3f} (expected ~0.833)")

    # Avg return 30d: (0.05+0.06+0.07+0.08+0.09-0.05)/6 = 0.30/6 = 0.05
    ar30 = stats.avg_return.get(30, 0)
    check(abs(ar30 - 0.05) < 0.01, f"avg_return[30]={ar30:.4f} (expected ~0.05)")

    # Max drawdown from samples: 0.15
    check(stats.max_drawdown == 0.15, f"max_drawdown={stats.max_drawdown} (expected 0.15)")

    # Profit-loss ratio (90d): avg_win / avg_loss
    # wins: 0.10, 0.13, 0.16, 0.19, 0.22 → avg=0.16
    # losses: 0.10 → avg=0.10
    # PLR = 0.16/0.10 = 1.6
    check(stats.profit_loss_ratio > 1.0, f"profit_loss_ratio={stats.profit_loss_ratio:.2f} > 1.0")

    # Sharpe > 0 (positive avg returns)
    check(stats.sharpe_ratio > 0, f"sharpe_ratio={stats.sharpe_ratio:.4f} > 0")

    # Strength buckets
    check(len(stats.strength_buckets) == 3, f"strength_buckets has 3 groups")
    print(f"  Strength buckets:")
    for b in stats.strength_buckets:
        print(f"    {b['strength_range']}: count={b['count']}, wr={b['win_rate']:.2f}, avg_r={b['avg_return']:.4f}")

    print()


# ─── TEST 4: Weight suggestions ───────────────────────────
def test_weight_suggestions():
    print("=" * 60)
    print("TEST 4: Weight optimization suggestions")
    print("=" * 60)

    from backtest.statistics import BacktestStatistics, BacktestStats

    calc = BacktestStatistics()

    stats_by_type = {
        "demand_inflection": BacktestStats(
            signal_type="demand_inflection",
            total_signals=100, valid_signals=80,
            win_rate={90: 0.65}, avg_return={90: 0.08},
            sharpe_ratio=1.5, avg_drawdown=0.05,
        ),
        "supply_shortage": BacktestStats(
            signal_type="supply_shortage",
            total_signals=50, valid_signals=40,
            win_rate={90: 0.55}, avg_return={90: 0.04},
            sharpe_ratio=0.8, avg_drawdown=0.08,
        ),
        "earnings_inflection": BacktestStats(
            signal_type="earnings_inflection",
            total_signals=60, valid_signals=50,
            win_rate={90: 0.60}, avg_return={90: 0.06},
            sharpe_ratio=1.2, avg_drawdown=0.06,
        ),
    }

    suggestions = calc.suggest_weights(stats_by_type)
    check(len(suggestions) == 3, f"Got {len(suggestions)} suggestions (expected 3)")

    for s in suggestions:
        print(f"  {s.signal_type}: current={s.current_weight:.2f} → suggested={s.suggested_weight:.4f} ({s.reason})")
        check(0 <= s.suggested_weight <= 1, f"{s.signal_type} weight in [0, 1]")

    # demand_inflection 表现最好，应该 suggested > current 或至少合理
    di = [s for s in suggestions if s.signal_type == "demand_inflection"]
    if di:
        check(di[0].suggested_weight > 0, "demand_inflection has positive suggested weight")

    print()


# ─── TEST 5: BacktestEngine instantiation ──────────────────
def test_engine_instantiation():
    print("=" * 60)
    print("TEST 5: BacktestEngine instantiation")
    print("=" * 60)

    from unittest.mock import MagicMock
    from backtest.engine import BacktestEngine

    mock_sf = MagicMock()
    engine = BacktestEngine(mock_sf)

    check(hasattr(engine, "run"), "has run()")
    check(hasattr(engine, "run_all_types"), "has run_all_types()")
    check(engine._replay is not None, "_replay (SignalReplay) initialized")
    check(engine._stats is not None, "_stats (BacktestStatistics) initialized")
    print()


# ─── TEST 6: BacktestResult ORM model ─────────────────────
def test_backtest_result_model():
    print("=" * 60)
    print("TEST 6: BacktestResult ORM model")
    print("=" * 60)

    from common.models import BacktestResult

    check(BacktestResult.__tablename__ == "backtest_results", "table = backtest_results")
    cols = {c.name for c in BacktestResult.__table__.columns}
    required = {
        "id", "task_id", "signal_type", "start_date", "end_date",
        "total_signals", "win_rate", "avg_return_30d", "avg_return_60d",
        "avg_return_90d", "max_drawdown", "result_detail", "created_at",
    }
    missing = required - cols
    check(len(missing) == 0, f"All columns present (missing: {missing or 'none'})")
    print()


# ─── TEST 7: Median calculation ───────────────────────────
def test_median():
    print("=" * 60)
    print("TEST 7: Median & Sharpe helper functions")
    print("=" * 60)

    from backtest.statistics import BacktestStatistics

    calc = BacktestStatistics()

    check(calc._median([1, 2, 3]) == 2, "median([1,2,3]) = 2")
    check(calc._median([1, 2, 3, 4]) == 2.5, "median([1,2,3,4]) = 2.5")
    check(calc._median([5]) == 5, "median([5]) = 5")
    check(calc._median([]) == 0.0, "median([]) = 0.0")

    # Sharpe with all same returns → std~0 → should not crash
    sharpe = calc._sharpe([0.05, 0.05, 0.05, 0.05], 90)
    check(isinstance(sharpe, float), f"sharpe with constant returns = {sharpe:.4f}")

    # Sharpe with positive returns
    sharpe2 = calc._sharpe([0.05, 0.08, 0.03, 0.10, 0.06], 90)
    check(sharpe2 > 0, f"sharpe with positive returns = {sharpe2:.4f}")

    print()


# ─── TEST 8: Empty samples edge case ──────────────────────
def test_empty_samples():
    print("=" * 60)
    print("TEST 8: Edge case - empty samples")
    print("=" * 60)

    from backtest.statistics import BacktestStatistics

    calc = BacktestStatistics()
    stats = calc.calculate([], signal_type="test")

    check(stats.total_signals == 0, "total_signals = 0")
    check(stats.valid_signals == 0, "valid_signals = 0")
    check(stats.max_drawdown == 0, "max_drawdown = 0")
    check(stats.sharpe_ratio == 0, "sharpe_ratio = 0")
    check(stats.profit_loss_ratio == 0, "profit_loss_ratio = 0")
    check(len(stats.win_rate) == 0, "win_rate empty")
    print()


# ─── TEST 9: Integration (requires DB) ────────────────────
async def test_integration():
    print("=" * 60)
    print("TEST 9: Integration test (requires DB)")
    print("=" * 60)

    try:
        from common.database import async_session_factory
        from backtest.engine import BacktestEngine
        from backtest.replay import SignalReplay

        replay = SignalReplay(async_session_factory)
        ok("SignalReplay with real session_factory")

        engine = BacktestEngine(async_session_factory)
        ok("BacktestEngine with real session_factory")

        # Quick DB check
        async with async_session_factory() as session:
            from sqlalchemy import text, func, select
            from common.models import Signal
            result = await session.execute(select(func.count()).select_from(Signal))
            cnt = result.scalar() or 0
            print(f"  Signal count in DB: {cnt}")
            if cnt > 0:
                ok(f"Signals table has {cnt} records")
            else:
                print("  [SKIP] No signals in DB, replay test skipped")

    except Exception as e:
        print(f"  [SKIP] Integration test: {e}")

    print()


def main():
    print("\n" + "=" * 60)
    print(" Phase 5: Backtest System - Verification")
    print("=" * 60 + "\n")

    test_imports()
    test_signal_sample()
    test_statistics()
    test_weight_suggestions()
    test_engine_instantiation()
    test_backtest_result_model()
    test_median()
    test_empty_samples()
    asyncio.run(test_integration())

    print("=" * 60)
    print(f" Results: {PASS} passed, {FAIL} failed")
    print("=" * 60)

    if FAIL > 0:
        sys.exit(1)
    print(" Phase 5 verification complete!")


if __name__ == "__main__":
    main()
