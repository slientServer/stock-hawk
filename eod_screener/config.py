"""尾盘选股策略配置 - 所有阈值均可调整"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class EODScreenerConfig:
    """杨永兴尾盘选股法参数配置"""

    # === 选股条件 ===
    min_change_pct: float = 2.0  # 最低涨幅%
    max_change_pct: float = 5.0  # 最高涨幅%

    volume_avg_days: int = 5  # 均量计算天数
    volume_ratio_min: float = 1.5  # 最低量比

    ma_short: int = 5  # 短期均线
    ma_long: int = 10  # 长期均线
    price_above_ma: bool = True  # 价格需在均线上方

    late_strength_min: float = 0.7  # 尾盘强度阈值 (close-low)/(high-low)

    min_turnover_rate: float = 3.0  # 最低换手率%
    max_turnover_rate: float = 15.0  # 最高换手率%

    # 基本过滤
    exclude_st: bool = True
    min_market_cap: float = 30.0  # 最低市值(亿元)
    min_listed_days: int = 60  # 最低上市天数

    # === 交易参数 ===
    take_profit_pct: float = 5.0  # 止盈%
    stop_loss_pct: float = 3.0  # 止损%
    max_hold_days: int = 3  # 最大持有交易日
    backtest_lookback_days: int = 30  # 选股排序默认回测窗口(自然日)

    # === 评分权重 ===
    weight_change_pct: float = 0.20
    weight_volume_ratio: float = 0.25
    weight_late_strength: float = 0.25
    weight_turnover: float = 0.15
    weight_main_flow: float = 0.15

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> EODScreenerConfig:
        valid = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in valid})

    def merge_update(self, updates: dict) -> EODScreenerConfig:
        """返回合并更新后的新配置"""
        current = self.to_dict()
        valid = {f.name for f in fields(self.__class__)}
        for k, v in updates.items():
            if k in valid and v is not None:
                current[k] = v
        return self.__class__.from_dict(current)

    def validate(self) -> None:
        """校验配置区间，避免保存会导致筛选失效的参数。"""
        if self.min_change_pct > self.max_change_pct:
            raise ValueError("最低涨幅不能高于最高涨幅")
        if self.volume_avg_days < 1:
            raise ValueError("均量天数必须大于等于1")
        if self.volume_ratio_min < 0:
            raise ValueError("最低量比不能为负数")
        if self.ma_short < 1 or self.ma_long < 1:
            raise ValueError("均线天数必须大于等于1")
        if not 0 <= self.late_strength_min <= 1:
            raise ValueError("尾盘强度阈值必须在0到1之间")
        if self.min_turnover_rate < 0 or self.min_turnover_rate > self.max_turnover_rate:
            raise ValueError("换手率区间不合法")
        if self.min_market_cap < 0 or self.min_listed_days < 0:
            raise ValueError("市值和上市天数过滤条件不能为负数")
        if self.take_profit_pct <= 0 or self.stop_loss_pct <= 0 or self.max_hold_days < 1:
            raise ValueError("交易参数必须为正数")
        if self.backtest_lookback_days < 5:
            raise ValueError("回测窗口至少需要5天")
        weights = [
            self.weight_change_pct,
            self.weight_volume_ratio,
            self.weight_late_strength,
            self.weight_turnover,
            self.weight_main_flow,
        ]
        if any(w < 0 for w in weights) or sum(weights) <= 0:
            raise ValueError("评分权重不能为负，且总和必须大于0")

    # --- 持久化 ---

    _SETTINGS_PATH = Path("data/runtime_settings.json")
    _KEY = "eod_screener_config"

    def save(self) -> None:
        self.validate()
        path = self._SETTINGS_PATH
        data: dict = {}
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        data[self._KEY] = self.to_dict()
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls) -> EODScreenerConfig:
        path = cls._SETTINGS_PATH
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if cls._KEY in data:
                return cls.from_dict(data[cls._KEY])
        return cls()
