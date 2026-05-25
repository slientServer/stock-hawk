"""评分逻辑：激进标（个股）+ 稳健标（ETF）"""

from __future__ import annotations

from pre_market.config import PreMarketConfig


class PreMarketScorer:
    """对候选标的进行加权评分(0-100)"""

    def __init__(self, config: PreMarketConfig):
        self.config = config

    # ─────────────────────── 激进标 ───────────────────────

    def score_aggressive(self, candidates: list[dict]) -> list[dict]:
        for item in candidates:
            item["score"] = round(self._score_agg(item), 2)
        candidates.sort(key=lambda x: x["score"], reverse=True)
        for i, item in enumerate(candidates, 1):
            item["rank"] = i
        return candidates

    def _score_agg(self, item: dict) -> float:
        c = self.config
        w_cat = c.agg_weight_catalyst
        w_tec = c.agg_weight_technical
        w_fund = c.agg_weight_fund
        total_w = w_cat + w_tec + w_fund
        if total_w <= 0:
            return 0.0

        # 催化强度分（1-5 → 0-100）
        strength = item.get("catalyst_strength", 3)
        cat_score = max(0.0, min(100.0, (strength - 1) / 4 * 100))

        # 技术形态分
        tec_score = self._technical_score(item)

        # 资金强度分
        fund_score = self._fund_score_agg(item)

        return (cat_score * w_cat + tec_score * w_tec + fund_score * w_fund) / total_w

    def _technical_score(self, item: dict) -> float:
        """近5日涨幅适中 + 前1日涨幅温和 + 量比充分 + 换手率适中"""
        score = 0.0
        weight_sum = 0.0

        # 近5日涨幅：15-25%最优
        change_5d = float(item.get("change_pct_5d", 0))
        if 15 <= change_5d <= 25:
            s = 100.0
        elif 10 <= change_5d < 15:
            s = 60.0 + (change_5d - 10) / 5 * 40
        elif 25 < change_5d <= 40:
            s = 100.0 - (change_5d - 25) / 15 * 60
        else:
            s = 20.0
        score += s * 0.30
        weight_sum += 0.30

        # 前1日涨幅：2-5%最优
        change_1d = float(item.get("change_pct_1d", 0))
        if 2 <= change_1d <= 5:
            s = 100.0
        elif 0 <= change_1d < 2:
            s = 50.0 + change_1d / 2 * 50
        elif 5 < change_1d <= 7:
            s = 100.0 - (change_1d - 5) / 2 * 40
        else:
            s = 20.0
        score += s * 0.25
        weight_sum += 0.25

        # 量比：2-4倍最优
        vr = float(item.get("volume_ratio", 1.0))
        if 2.0 <= vr <= 4.0:
            s = 100.0
        elif 1.5 <= vr < 2.0:
            s = 60.0 + (vr - 1.5) / 0.5 * 40
        elif 4.0 < vr <= 6.0:
            s = 100.0 - (vr - 4.0) / 2.0 * 40
        else:
            s = 30.0
        score += s * 0.25
        weight_sum += 0.25

        # 换手率：7-12%最优
        tr = float(item.get("turnover_rate", 5.0))
        if 7.0 <= tr <= 12.0:
            s = 100.0
        elif 5.0 <= tr < 7.0:
            s = 70.0 + (tr - 5.0) / 2.0 * 30
        elif 12.0 < tr <= 15.0:
            s = 100.0 - (tr - 12.0) / 3.0 * 30
        else:
            s = 40.0
        score += s * 0.20
        weight_sum += 0.20

        return score / weight_sum if weight_sum > 0 else 0.0

    def _fund_score_agg(self, item: dict) -> float:
        """主力净流入强度：以3日趋势为主（70%），1日作修正（30%）
        
        设计逻辑：
        - 3日持续流入 + 1日仍流入 → 主力持续入场，满分区间
        - 3日持续流入 + 1日回调   → 短期洗盘/回抽，保留大部分分数，不重扣
        - 3日开始流出             → 整体撤退信号，重扣
        """
        main_1d = float(item.get("main_net_1d", 0)) / 10000  # 万元
        main_3d = float(item.get("main_net_3d", 0)) / 10000

        # 3日基础分（主指标，权重70%）
        if main_3d >= 50000:
            s3 = 100.0
        elif main_3d >= 10000:
            s3 = 60.0 + (main_3d - 10000) / 40000 * 40
        elif main_3d >= 0:
            s3 = main_3d / 10000 * 60
        else:
            # 3日净流出：重扣，趋势已反转
            s3 = max(0.0, 20.0 + main_3d / 10000 * 20)

        # 1日修正系数（权重30%，体现近期变化方向）
        if main_1d >= 10000:
            # 昨日大幅流入：趋势加速，给满分
            s1 = 100.0
        elif main_1d >= 0:
            # 昨日小幅流入或持平：中性，不加不减
            s1 = 50.0 + main_1d / 10000 * 50
        elif main_3d > 0 and main_1d >= -5000:
            # 昨日小幅流出但3日仍正：正常回抽/洗盘，轻微扣分
            s1 = 40.0 + main_1d / 5000 * 20  # 最低20分
        else:
            # 昨日大幅流出：撤退信号，重扣
            s1 = max(0.0, 20.0 + main_1d / 10000 * 20)

        return s3 * 0.70 + s1 * 0.30

    # ─────────────────────── 稳健标 ───────────────────────

    def score_stable(self, candidates: list[dict]) -> list[dict]:
        for item in candidates:
            item["score"] = round(self._score_etf(item), 2)
        candidates.sort(key=lambda x: x["score"], reverse=True)
        for i, item in enumerate(candidates, 1):
            item["rank"] = i
        return candidates

    def _score_etf(self, item: dict) -> float:
        c = self.config
        w_mom = c.etf_weight_momentum
        w_fund = c.etf_weight_fund
        w_safe = c.etf_weight_safety
        total_w = w_mom + w_fund + w_safe
        if total_w <= 0:
            return 0.0

        mom_score = self._momentum_score(item)
        fund_score = self._fund_score_etf(item)
        safe_score = self._safety_score(item)

        return (mom_score * w_mom + fund_score * w_fund + safe_score * w_safe) / total_w

    def _momentum_score(self, item: dict) -> float:
        """近3日涨幅 + MA5向上"""
        change_3d = float(item.get("change_pct_3d", 0))
        if change_3d >= 3.0:
            s = 100.0
        elif change_3d >= 1.0:
            s = 50.0 + (change_3d - 1.0) / 2.0 * 50
        elif change_3d >= 0:
            s = change_3d / 1.0 * 50
        else:
            s = max(0.0, 30.0 + change_3d * 10)

        direction = item.get("ma5_direction", "flat")
        if direction == "up":
            s = min(100.0, s * 1.1)
        elif direction == "down":
            s *= 0.7
        return s

    def _fund_score_etf(self, item: dict) -> float:
        """成交额比：越高越活跃"""
        amt_ratio = float(item.get("amount_ratio", 1.0))
        if amt_ratio >= 2.5:
            return 100.0
        elif amt_ratio >= 1.5:
            return 60.0 + (amt_ratio - 1.5) / 1.0 * 40
        elif amt_ratio >= 1.2:
            return 40.0 + (amt_ratio - 1.2) / 0.3 * 20
        else:
            return max(0.0, amt_ratio / 1.2 * 40)

    def _safety_score(self, item: dict) -> float:
        """MA5偏离度不超买 + 振幅适中"""
        deviation = float(item.get("ma5_deviation", 0))
        if deviation <= 0:
            s = 20.0  # 低于MA5扣分
        elif deviation <= 1.5:
            s = 100.0
        elif deviation <= 3.0:
            s = 100.0 - (deviation - 1.5) / 1.5 * 40
        else:
            s = 40.0

        amplitude = float(item.get("avg_amplitude", 0))
        if amplitude >= 2.0:
            amp_score = 100.0
        elif amplitude >= 1.5:
            amp_score = 60.0 + (amplitude - 1.5) / 0.5 * 40
        else:
            amp_score = amplitude / 1.5 * 60

        return s * 0.6 + amp_score * 0.4

    # ─────────────────────── 稳健个股 ───────────────────────

    def score_stable_stock(self, candidates: list[dict]) -> list[dict]:
        for item in candidates:
            item["score"] = round(self._score_stable_stock(item), 2)
        candidates.sort(key=lambda x: x["score"], reverse=True)
        for i, item in enumerate(candidates, 1):
            item["rank"] = i
        return candidates

    def _score_stable_stock(self, item: dict) -> float:
        c = self.config
        w_mom = c.stable_stock_weight_momentum
        w_safe = c.stable_stock_weight_safety
        w_fund = c.stable_stock_weight_fund
        total_w = w_mom + w_safe + w_fund
        if total_w <= 0:
            return 0.0

        mom_score = self._stable_stock_momentum_score(item)
        safe_score = self._stable_stock_safety_score(item)
        fund_score = self._stable_stock_fund_score(item)

        return (mom_score * w_mom + safe_score * w_safe + fund_score * w_fund) / total_w

    def _stable_stock_momentum_score(self, item: dict) -> float:
        """稳健动量：5日涨幅 3-15% 最优，MA5向上加成"""
        change_5d = float(item.get("change_pct_5d", 0))
        if 5.0 <= change_5d <= 12.0:
            s = 100.0
        elif 3.0 <= change_5d < 5.0:
            s = 60.0 + (change_5d - 3.0) / 2.0 * 40
        elif 12.0 < change_5d <= 20.0:
            s = 100.0 - (change_5d - 12.0) / 8.0 * 40
        elif 0 < change_5d < 3.0:
            s = 30.0 + change_5d / 3.0 * 30
        else:
            s = 20.0

        # MA5偏离度方向：偏离度小且正向加成
        deviation = float(item.get("ma5_deviation", 0))
        if 0 < deviation <= 2.0:
            s = min(100.0, s * 1.1)
        elif deviation > 4.0:
            s *= 0.8
        return s

    def _stable_stock_safety_score(self, item: dict) -> float:
        """低波动安全分：振幅越小越好 + MA5偏离度适中"""
        # 振幅：越小越安全（主要指标）
        amplitude = float(item.get("avg_amplitude", 99.0))
        if amplitude <= 1.5:
            amp_score = 100.0
        elif amplitude <= 2.5:
            amp_score = 100.0 - (amplitude - 1.5) / 1.0 * 30
        elif amplitude <= 3.5:
            amp_score = 70.0 - (amplitude - 2.5) / 1.0 * 40
        else:
            amp_score = 20.0

        # MA5偏离度：0-2% 最安全
        deviation = float(item.get("ma5_deviation", 0))
        if 0 < deviation <= 2.0:
            dev_score = 100.0
        elif deviation <= 3.5:
            dev_score = 100.0 - (deviation - 2.0) / 1.5 * 40
        elif deviation <= 0:
            dev_score = 20.0
        else:
            dev_score = 40.0

        return amp_score * 0.65 + dev_score * 0.35

    def _stable_stock_fund_score(self, item: dict) -> float:
        """资金持续性：3日主力持续净流入"""
        main_3d = float(item.get("main_net_3d", 0)) / 10000  # 万元
        main_1d = float(item.get("main_net_1d", 0)) / 10000  # 万元

        # 3日净流入（主指标）
        if main_3d >= 10000:
            s3 = 100.0
        elif main_3d >= 3000:
            s3 = 60.0 + (main_3d - 3000) / 7000 * 40
        elif main_3d >= 0:
            s3 = main_3d / 3000 * 60
        else:
            s3 = max(0.0, 20.0 + main_3d / 3000 * 20)

        # 1日净流入加成
        if main_1d >= 1000:
            s1_bonus = 10.0
        elif main_1d > 0:
            s1_bonus = 5.0
        else:
            s1_bonus = 0.0

        return min(100.0, s3 + s1_bonus)
