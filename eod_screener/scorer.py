"""评分与排序逻辑"""

from __future__ import annotations

from eod_screener.config import EODScreenerConfig


class EODScorer:
    """对通过筛选的股票进行加权评分(0-100)并排序"""

    def __init__(self, config: EODScreenerConfig):
        self.config = config

    def score_and_rank(self, candidates: list[dict]) -> list[dict]:
        for item in candidates:
            item["score"] = round(self._calculate_score(item), 2)
            item["signal_strength"] = self._strength_label(item["score"])

        candidates.sort(key=lambda x: x["score"], reverse=True)
        for i, item in enumerate(candidates, 1):
            item["rank"] = i
        return candidates

    def _calculate_score(self, item: dict) -> float:
        c = self.config
        score = 0.0
        weight_sum = (
            c.weight_change_pct
            + c.weight_volume_ratio
            + c.weight_late_strength
            + c.weight_turnover
            + c.weight_main_flow
        )
        if weight_sum <= 0:
            return 0.0

        # 涨幅适中度: 3~4%最优(满分), 偏离线性递减
        change = item.get("change_pct", 0.0)
        optimal_change = (c.min_change_pct + c.max_change_pct) / 2
        change_range = (c.max_change_pct - c.min_change_pct) / 2
        if change_range > 0:
            deviation = abs(change - optimal_change) / change_range
            change_score = max(0, 100 * (1 - deviation))
        else:
            change_score = 100.0
        score += change_score * c.weight_change_pct / weight_sum

        # 量比: 2~4倍最优, <1.5或>6减分
        vr = item.get("volume_ratio", 1.0)
        if vr <= 1.5:
            vr_score = 30.0
        elif vr <= 2.0:
            vr_score = 60.0 + (vr - 1.5) / 0.5 * 40
        elif vr <= 4.0:
            vr_score = 100.0
        elif vr <= 6.0:
            vr_score = 100.0 - (vr - 4.0) / 2.0 * 40
        else:
            vr_score = 40.0
        score += vr_score * c.weight_volume_ratio / weight_sum

        # 尾盘强度: 越高越好, 0.7为及格线
        ls = item.get("late_strength", 0.5)
        if ls >= 0.95:
            ls_score = 100.0
        elif ls >= 0.7:
            ls_score = 60.0 + (ls - 0.7) / 0.25 * 40
        else:
            ls_score = max(0, ls / 0.7 * 60)
        score += ls_score * c.weight_late_strength / weight_sum

        # 换手率: 5~10%最优
        tr = item.get("turnover_rate", 5.0)
        if 5.0 <= tr <= 10.0:
            tr_score = 100.0
        elif 3.0 <= tr < 5.0:
            tr_score = 60.0 + (tr - 3.0) / 2.0 * 40
        elif 10.0 < tr <= 15.0:
            tr_score = 100.0 - (tr - 10.0) / 5.0 * 40
        else:
            tr_score = 40.0
        score += tr_score * c.weight_turnover / weight_sum

        # 主力资金净流入占比: 正值加分
        main_pct = item.get("main_net_pct", 0.0)
        if main_pct >= 5.0:
            mf_score = 100.0
        elif main_pct >= 0:
            mf_score = 50.0 + main_pct / 5.0 * 50
        elif main_pct >= -5.0:
            mf_score = 50.0 + main_pct / 5.0 * 30
        else:
            mf_score = 20.0
        score += mf_score * c.weight_main_flow / weight_sum

        return score

    @staticmethod
    def _strength_label(score: float) -> str:
        if score >= 75:
            return "强"
        elif score >= 50:
            return "中"
        return "弱"
