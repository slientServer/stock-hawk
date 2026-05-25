"""盘前选股策略配置"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class PreMarketConfig:
    """盘前选股参数配置"""

    # === 激进标（个股）筛选条件 ===
    agg_5d_min: float = 10.0       # 近5日最低涨幅%
    agg_5d_max: float = 40.0       # 近5日最高涨幅%
    agg_1d_min: float = 0.0        # 前一日最低涨幅%
    agg_1d_max: float = 7.0        # 前一日最高涨幅%（排除涨停）
    agg_turnover_min: float = 5.0  # 最低换手率%
    agg_turnover_max: float = 15.0 # 最高换手率%
    agg_volume_ratio_min: float = 1.5  # 最低量比
    agg_market_cap_min: float = 50.0   # 最低流通市值(亿元)
    agg_market_cap_max: float = 500.0  # 最高流通市值(亿元)
    agg_main_net_1d_min: float = 5000.0  # 前1日主力净流入(万元)
    agg_catalyst_strength_min: int = 3   # 最低催化强度（筛选催化板块时）
    agg_max_candidates: int = 100        # 最多送入LLM匹配的候选股数量

    # === 稳健标（ETF）筛选条件 ===
    etf_ma5_deviation_max: float = 3.0   # MA5偏离度上限%（未超买）
    etf_amount_ratio_min: float = 1.2    # 成交额/20日均值最低倍数
    etf_avg_amplitude_min: float = 1.5   # 近20日日均振幅最低%
    etf_avg_amplitude_max: float = 2.5   # 近20日日均振幅上限%（止损-1.5%需低波动）
    etf_top_n: int = 3                   # 最多选出稳健标数量

    # === 交易参数 ===
    agg_take_profit_pct: float = 5.0   # 激进标止盈%
    agg_stop_loss_pct: float = 3.0     # 激进标止损%
    etf_take_profit_pct: float = 2.0   # 稳健标止盈%
    etf_stop_loss_pct: float = 1.5     # 稳健标止损%
    max_hold_days: int = 3             # 最大持有交易日

    # === 评分权重（激进标）===
    agg_weight_catalyst: float = 0.30  # 催化强度
    agg_weight_technical: float = 0.30 # 技术形态
    agg_weight_fund: float = 0.40      # 资金强度

    # === 评分权重（稳健标）===
    etf_weight_momentum: float = 0.35  # 方向动量
    etf_weight_fund: float = 0.35      # 资金流入
    etf_weight_safety: float = 0.30    # 技术安全

    # === 稳健标（个股）筛选条件 ===
    stable_stock_market_cap_min: float = 30.0    # 最低流通市值(亿元)
    stable_stock_market_cap_max: float = 300.0   # 最高流通市值(亿元)
    stable_stock_turnover_min: float = 2.0       # 最低换手率%
    stable_stock_turnover_max: float = 10.0      # 最高换手率%
    stable_stock_5d_min: float = 3.0             # 近5日最低涨幅%
    stable_stock_5d_max: float = 20.0            # 近5日最高涨幅%
    stable_stock_1d_min: float = -2.0            # 前1日最低涨幅%（允许略微回调）
    stable_stock_1d_max: float = 5.0             # 前1日最高涨幅%
    stable_stock_volume_ratio_min: float = 0.8   # 最低量比（稳定即可）
    stable_stock_volume_ratio_max: float = 2.5   # 最高量比（排除炒作）
    stable_stock_amplitude_max: float = 3.0      # 近20日日均振幅上限%（个股稳健，止损-1.5%需控制）
    stable_stock_main_net_3d_min: float = 0.0    # 近3日主力净流入下限（元，持续非负）
    stable_stock_top_n: int = 3                  # 最多输出稳健个股数量

    # === 评分权重（稳健个股）===
    stable_stock_weight_momentum: float = 0.30   # 稳健动量
    stable_stock_weight_safety: float = 0.40     # 低波动安全
    stable_stock_weight_fund: float = 0.30       # 资金持续性

    # === 过热过滤阈值 ===
    agg_5d_hot_exclude: float = 15.0        # 近5日涨幅 > 此值直接排除（赔率差）
    agg_5d_hot_need_catalyst: float = 10.0  # 近5日涨幅 > 此值，需催化强度达标才可入池
    agg_hot_catalyst_min: int = 4           # 过热保护触发时的最低催化强度要求

    # === 双止损（激进标）===
    agg_stop_loss_hard_pct: float = 5.0     # 硬止损%（无条件触发，不可商量）
    # agg_stop_loss_pct 保留为软止损观察价（-3% + 分时均线判断）

    # === 双止损（稳健标）===
    etf_stop_loss_hard_pct: float = 3.0     # 硬止损%（无条件触发）
    # etf_stop_loss_pct 保留为软止损观察价（-1.5% + 买入后15分钟判断）

    # === 行业集中度约束 ===
    agg_max_per_sector: int = 1             # 同一催化板块最多选入激进标数量

    # === 最低入选分阈值 ===
    agg_score_min: float = 65.0             # 激进标最低入选分，低于此值不推荐（信号太弱）
    stable_score_min: float = 70.0          # 稳健标最低入选分

    # === 新闻催化分析 ===
    news_lookback_hours: int = 13      # 回溯新闻小时数（昨日18:00~今日07:00）
    news_max_articles: int = 50        # 最多输入LLM的资讯条数

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> PreMarketConfig:
        valid = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in valid})

    def merge_update(self, updates: dict) -> PreMarketConfig:
        current = self.to_dict()
        valid = {f.name for f in fields(self.__class__)}
        for k, v in updates.items():
            if k in valid and v is not None:
                current[k] = v
        return self.__class__.from_dict(current)

    # --- 持久化 ---

    _SETTINGS_PATH = Path("data/runtime_settings.json")
    _KEY = "pre_market_config"

    def save(self) -> None:
        path = self._SETTINGS_PATH
        data: dict = {}
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        data[self._KEY] = self.to_dict()
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls) -> PreMarketConfig:
        path = cls._SETTINGS_PATH
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if cls._KEY in data:
                return cls.from_dict(data[cls._KEY])
        return cls()
