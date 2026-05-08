"""产业链自动发现 Agent：从热门概念板块中发现新产业链"""

import json
from datetime import date, datetime
from typing import Any

from agents.base import BaseAgent
from agents.tools.discovery_tools import DiscoveryTools
from common.logger import get_logger

logger = get_logger(__name__)

# 多维候选评分权重
CANDIDATE_SCORE_WEIGHTS = {
    "change_pct": 0.30,       # 当日涨跌幅
    "advance_ratio": 0.25,    # 上涨家数占比
    "turnover_rank": 0.25,    # 成交额/总市值排名
    "weekly_momentum": 0.20,  # 5日累计动量
}


class ChainDiscoveryAgent(BaseAgent):
    """数据驱动 + LLM 分析，自动发现并构建新产业链"""

    agent_id = "chain_discovery"

    def __init__(self, session_factory, llm_client=None):
        super().__init__(session_factory, llm_client)
        self._discovery = DiscoveryTools(session_factory)
        self._last_llm_error = ""

    async def _run_impl(self, params: dict[str, Any]) -> dict[str, Any]:
        """主逻辑: 数据获取 → LLM 构建链 → 验证 → 写入 Neo4j"""
        top_n = params.get("top_n", 20)
        min_change_pct = params.get("min_change_pct", 0.0)
        dry_run = params.get("dry_run", False)
        allow_local_fallback = bool(params.get("allow_local_fallback", False))

        # Step 1: 获取候选板块。默认只接受真实市场板块源；本地行业分组必须显式开启。
        board_payload = await self._fetch_candidate_boards(
            top_n=top_n,
            min_change_pct=min_change_pct,
            allow_local_fallback=allow_local_fallback,
        )
        hot_boards = board_payload.get("boards", [])
        if not hot_boards:
            if board_payload.get("all_market_sources_failed"):
                return {
                    "status": "market_source_unavailable",
                    "message": "外部概念/行业板块数据源不可用，已暂停产业链自动发现；未使用本地低置信度数据生成新图谱。",
                    "source_mode": board_payload.get("source_mode"),
                    "source_summary": board_payload.get("source_summary", {}),
                    "source_assessment": board_payload.get("source_assessment", {}),
                    "diagnostics": board_payload.get("diagnostics", {}),
                }
            return {
                "status": "no_hot_boards",
                "message": f"未发现涨幅 >= {min_change_pct}% 的热门板块",
                "source_mode": board_payload.get("source_mode"),
                "source_summary": board_payload.get("source_summary", {}),
                "source_assessment": board_payload.get("source_assessment", {}),
                "diagnostics": board_payload.get("diagnostics", {}),
            }
        logger.info(
            "发现 %s 个候选板块，source_mode=%s",
            len(hot_boards),
            board_payload.get("source_mode"),
        )

        # Step 2: 获取各板块成分股。外部源限制请求数；本地源可多给行业但少给样本股。
        boards_with_stocks = []
        constituent_errors = []
        is_local_fallback = board_payload.get("source_mode") == "local_fallback"
        board_limit = min(len(hot_boards), 20 if is_local_fallback else 10)
        stock_limit = 6 if is_local_fallback else 30
        for board in hot_boards[:board_limit]:
            board_name = board.get("板块名称", "") or board.get("board_name", "")
            if not board_name:
                continue
            board_symbol = board.get("板块代码") or board.get("board_code") or board_name
            source_type = board.get("source_type", "concept")
            cons_result = await self._discovery.fetch_board_constituents(board_symbol, board_type=source_type)
            if cons_result.success and cons_result.data:
                stocks = self._normalize_stock_refs(cons_result.data[:stock_limit])
                if not stocks:
                    continue
                boards_with_stocks.append(
                    {
                        "board_name": board_name,
                        "change_pct": board.get("涨跌幅", 0),
                        "turnover": board.get("成交额", 0),
                        "source_type": source_type,
                        "source_name": board.get("source_name", ""),
                        "stocks": stocks,
                    }
                )
            else:
                constituent_errors.append(
                    {
                        "board_name": board_name,
                        "source_type": source_type,
                        "error": cons_result.error if not cons_result.success else "empty constituents",
                    }
                )

        if not boards_with_stocks:
            return {
                "status": "no_constituents",
                "message": "候选板块存在，但获取板块成分股失败",
                "diagnostics": {
                    **board_payload.get("diagnostics", {}),
                    "constituent_errors": constituent_errors,
                },
            }

        # Step 3: 获取已有链名（去重用）
        existing_result = await self._discovery.get_existing_chain_names()
        existing_chains = existing_result.data if existing_result.success else []

        # Step 3.5: 增量更新已有链
        incremental_results = []
        if existing_chains and not dry_run:
            incremental_results = await self._incremental_update_existing_chains(
                existing_chains, boards_with_stocks
            )

        # Step 4: LLM 分析板块关系，构建产业链
        chain_proposals = await self._llm_construct_chains(boards_with_stocks, existing_chains)

        if not chain_proposals:
            if self._last_llm_error:
                return {
                    "status": "llm_unavailable",
                    "hot_boards": [b["board_name"] for b in boards_with_stocks],
                    "message": "LLM 调用失败，未能完成产业链结构化",
                    "error": self._last_llm_error,
                    "source_mode": board_payload.get("source_mode"),
                    "source_summary": board_payload.get("source_summary", {}),
                    "source_assessment": board_payload.get("source_assessment", {}),
                    "diagnostics": board_payload.get("diagnostics", {}),
                }
            return {
                "status": "no_new_chains",
                "hot_boards": [b["board_name"] for b in boards_with_stocks],
                "message": "LLM 未识别出新的产业链",
                "source_mode": board_payload.get("source_mode"),
                "source_summary": board_payload.get("source_summary", {}),
                "source_assessment": board_payload.get("source_assessment", {}),
                "diagnostics": board_payload.get("diagnostics", {}),
            }

        # Step 5: 验证 + 写入
        results = []
        for proposal in chain_proposals:
            validated = await self._validate_and_build(
                proposal,
                source_mode=board_payload.get("source_mode") or "",
                source_assessment=board_payload.get("source_assessment") or {},
            )
            if not validated:
                continue

            if dry_run:
                results.append(
                    {
                        "chain_name": validated["chain"]["name"],
                        "segments": len(validated["segments"]),
                        "companies": len(validated["companies"]),
                        "relationships": len(validated["relationships"]),
                        "dry_run": True,
                    }
                )
            else:
                write_result = await self._discovery.write_chain_to_neo4j(validated)
                if write_result.success:
                    # P3: 信号验证
                    verification = await self._verify_new_chain(validated["chain"]["name"])
                    results.append({**write_result.data, "dry_run": False, "verification": verification})
                else:
                    logger.error(f"写入失败: {validated['chain']['name']}: {write_result.error}")

        return {
            "status": "completed",
            "hot_boards_scanned": len(boards_with_stocks),
            "existing_chains": existing_chains,
            "incremental_updates": incremental_results,
            "new_chains": results,
            "source_mode": board_payload.get("source_mode"),
            "source_summary": board_payload.get("source_summary", {}),
            "source_assessment": board_payload.get("source_assessment", {}),
            "diagnostics": board_payload.get("diagnostics", {}),
        }

    async def _run_fallback(self, params: dict[str, Any]) -> dict[str, Any]:
        """降级: 仅返回热门板块信息，不做 LLM 链构建"""
        top_n = params.get("top_n", 20)
        min_change_pct = params.get("min_change_pct", 0.0)
        allow_local_fallback = bool(params.get("allow_local_fallback", False))

        board_payload = await self._fetch_candidate_boards(
            top_n=top_n,
            min_change_pct=min_change_pct,
            allow_local_fallback=allow_local_fallback,
        )
        hot_boards = board_payload.get("boards", [])
        if not hot_boards and board_payload.get("all_market_sources_failed"):
            return {
                "status": "market_source_unavailable",
                "message": "外部概念/行业板块数据源不可用，已暂停产业链自动发现；未使用本地低置信度数据生成新图谱。",
                "diagnostics": board_payload.get("diagnostics", {}),
                "hot_boards": [],
                "source_mode": board_payload.get("source_mode"),
                "source_summary": board_payload.get("source_summary", {}),
                "source_assessment": board_payload.get("source_assessment", {}),
            }
        if not hot_boards:
            return {
                "status": "no_hot_boards",
                "message": f"未发现涨幅 >= {min_change_pct}% 的热门板块",
                "diagnostics": board_payload.get("diagnostics", {}),
                "hot_boards": [],
                "source_mode": board_payload.get("source_mode"),
                "source_summary": board_payload.get("source_summary", {}),
                "source_assessment": board_payload.get("source_assessment", {}),
            }

        boards = [
            {
                "board_name": b.get("板块名称", ""),
                "change_pct": b.get("涨跌幅", 0),
                "turnover": b.get("成交额", 0),
                "source_type": b.get("source_type", ""),
                "source_name": b.get("source_name", ""),
            }
            for b in hot_boards
        ]

        return {
            "status": "degraded",
            "message": "LLM 不可用，仅返回热门板块，无法自动构建产业链",
            "hot_boards": boards,
            "source_mode": board_payload.get("source_mode"),
            "source_summary": board_payload.get("source_summary", {}),
            "source_assessment": board_payload.get("source_assessment", {}),
            "diagnostics": board_payload.get("diagnostics", {}),
        }

    async def _fetch_candidate_boards(
        self,
        top_n: int,
        min_change_pct: float,
        allow_local_fallback: bool = False,
    ) -> dict[str, Any]:
        """拉取概念板块和行业板块；本地行业分组仅在显式允许时参与发现。"""
        diagnostics: dict[str, Any] = {"sources": {}}
        boards: list[dict[str, Any]] = []
        market_success_count = 0
        cached_market_source_count = 0
        cache_ages: list[int] = []

        source_calls = [
            ("concept", self._discovery.fetch_hot_concept_boards),
            ("industry", self._discovery.fetch_hot_industry_boards),
        ]
        for source_type, fetcher in source_calls:
            result = await fetcher(top_n=top_n, min_change_pct=min_change_pct)
            if not result.success:
                diagnostics["sources"][source_type] = {
                    "success": False,
                    "error": result.error,
                }
                continue

            market_success_count += 1
            payload = result.data or {}
            source_boards = payload.get("boards", []) if isinstance(payload, dict) else []
            cache_info = payload.get("cache_info") if isinstance(payload, dict) else None
            if cache_info and cache_info.get("used"):
                cached_market_source_count += 1
                if isinstance(cache_info.get("age_seconds"), int):
                    cache_ages.append(cache_info["age_seconds"])
            diagnostics["sources"][source_type] = {
                "success": True,
                "source_name": payload.get("source_name") if isinstance(payload, dict) else source_type,
                "total_count": payload.get("total_count") if isinstance(payload, dict) else None,
                "qualified_count": payload.get("qualified_count") if isinstance(payload, dict) else len(source_boards),
                "min_change_pct": payload.get("min_change_pct") if isinstance(payload, dict) else min_change_pct,
                "max_change_pct": payload.get("max_change_pct") if isinstance(payload, dict) else None,
                "top_boards": payload.get("top_boards", [])[:5] if isinstance(payload, dict) else [],
                "cache_info": cache_info,
            }
            boards.extend(source_boards)

        local_available = False
        if not boards and market_success_count == 0:
            local_result = await self._discovery.fetch_local_industry_groups(top_n=top_n, min_stock_count=3)
            if local_result.success and local_result.data:
                local_payload = local_result.data
                local_boards = local_payload.get("boards", [])
                local_available = bool(local_boards)
                diagnostics["sources"]["local_industry"] = {
                    "success": True,
                    "source_name": local_payload.get("source_name"),
                    "total_count": local_payload.get("total_count"),
                    "qualified_count": local_payload.get("qualified_count"),
                    "note": "仅基于本地 Stock.industry，不代表实时热门程度；默认不参与自动发现",
                }
                if allow_local_fallback:
                    boards.extend(local_boards)
            else:
                diagnostics["sources"]["local_industry"] = {
                    "success": False,
                    "error": local_result.error,
                }

        boards = await self._dedupe_and_score_boards(boards, top_n)
        if market_success_count > 0:
            source_mode = "market_boards"
        elif boards and allow_local_fallback:
            source_mode = "local_fallback"
        else:
            source_mode = "market_unavailable"
        return {
            "boards": boards,
            "source_mode": source_mode,
            "source_summary": {
                "market_sources_succeeded": market_success_count,
                "cached_market_sources": cached_market_source_count,
                "max_cache_age_seconds": max(cache_ages) if cache_ages else None,
                "candidate_boards": len(boards),
                "min_change_pct": min_change_pct,
                "local_fallback_available": local_available,
                "local_fallback_enabled": allow_local_fallback,
            },
            "source_assessment": self._source_assessment(
                source_mode,
                market_success_count,
                cached_market_source_count,
            ),
            "diagnostics": diagnostics,
            "all_market_sources_failed": market_success_count == 0,
        }

    @staticmethod
    def _source_assessment(
        source_mode: str,
        market_success_count: int = 0,
        cached_market_source_count: int = 0,
    ) -> dict[str, Any]:
        if source_mode == "market_boards":
            all_cached = market_success_count > 0 and cached_market_source_count == market_success_count
            partly_cached = cached_market_source_count > 0 and not all_cached
            return {
                "confidence": "medium" if not all_cached else "low",
                "is_realtime_market": not all_cached,
                "is_market_hot": True,
                "is_simulated": False,
                "is_usable_for_discovery": True,
                "action_required": False,
                "data_source": "eastmoney_or_sina_market_boards",
                "label": "短期缓存市场板块" if all_cached else "实时市场板块",
                "explanation": (
                    f"实时接口当前不可用，使用 {market_success_count} 个 4 小时内成功采集的外部板块缓存。"
                    if all_cached
                    else f"至少 {market_success_count} 个外部概念/行业板块源可用"
                    + (f"，其中 {cached_market_source_count} 个来自短期缓存" if partly_cached else "")
                    + "，可用于热门板块发现。"
                ),
                "recommended_usage": "可作为产业链自动发现候选，但仍需结合信号、财报和人工复核。",
            }
        if source_mode == "local_fallback":
            return {
                "confidence": "low",
                "is_realtime_market": False,
                "is_market_hot": False,
                "is_simulated": False,
                "is_usable_for_discovery": False,
                "action_required": True,
                "data_source": "local_stock_industry_grouping",
                "label": "本地行业降级",
                "explanation": "外部概念/行业板块源失败后，系统使用本地 stocks.industry 分组生成候选；这不是模拟数据，但不包含实时涨幅、成交额或市场热度。",
                "recommended_usage": "默认不应作为自动发现输入；仅在人工明确允许时用于扩展图谱候选。",
                "resolution_steps": ChainDiscoveryAgent._market_source_resolution_steps(),
            }
        if source_mode == "market_unavailable":
            return {
                "confidence": "none",
                "is_realtime_market": False,
                "is_market_hot": False,
                "is_simulated": False,
                "is_usable_for_discovery": False,
                "action_required": True,
                "data_source": "market_board_sources_failed",
                "label": "市场源异常",
                "explanation": "外部概念/行业板块数据源不可用，系统已暂停自动发现，未使用本地低置信度数据生成新图谱。",
                "recommended_usage": "先修复市场数据源，再重新运行自动发现。",
                "resolution_steps": ChainDiscoveryAgent._market_source_resolution_steps(),
            }
        return {
            "confidence": "none",
            "is_realtime_market": False,
            "is_market_hot": False,
            "is_simulated": False,
            "is_usable_for_discovery": False,
            "action_required": True,
            "data_source": "none",
            "label": "无可用数据",
            "explanation": "没有可用于产业链发现的市场源或本地降级源。",
            "recommended_usage": "不可用于发现任务。",
            "resolution_steps": ChainDiscoveryAgent._market_source_resolution_steps(),
        }

    @staticmethod
    def _market_source_resolution_steps() -> list[str]:
        return [
            "检查运行机器是否能访问东方财富/AKShare 相关接口；当前常见错误是 RemoteDisconnected，通常是网络、代理、反爬或出口限制导致。",
            "如果在公司网络内运行，配置可用代理或放通东方财富行情域名后重试。",
            "升级 AKShare 到当前版本后重试概念板块和行业板块接口。",
            "系统已内置新浪板块备用源；若仍失败，优先检查运行机器到外部财经站点的网络出口或代理配置。",
            "只有需要扩展图谱候选且接受低置信度时，才显式开启 allow_local_fallback=true；该模式不能用于热门板块或交易信号。",
        ]

    async def _verify_new_chain(self, chain_name: str) -> dict[str, Any]:
        """对新写入的链执行信号验证，更新状态元数据"""
        try:
            from signal_engine import SignalEngine
            from knowledge_graph.neo4j_client import Neo4jClient

            engine = SignalEngine(self._session_factory, self._llm)
            score_result = await engine.scan_chain(chain_name)

            score_value = float(score_result.score)
            signal_count = score_result.signal_count
            new_status = "active" if score_value > 0 else "pending_verification"

            # 更新 Neo4j 元数据
            client = await Neo4jClient.get_instance()
            now_iso = datetime.now().isoformat()
            await client.merge_nodes_batch("IndustryChain", [{
                "name": chain_name,
                "status": new_status,
                "_verified_at": now_iso,
                "_initial_score": score_value,
                "_initial_signal_count": signal_count,
            }], ["name"])

            return {
                "chain_name": chain_name,
                "verification_status": new_status,
                "initial_score": score_value,
                "signal_count": signal_count,
                "verified_at": now_iso,
            }
        except Exception as e:
            logger.warning(f"信号验证失败 chain={chain_name}: {e}")
            return {
                "chain_name": chain_name,
                "verification_status": "verification_failed",
                "error": str(e),
            }

    async def _incremental_update_existing_chains(
        self,
        existing_chains: list[str],
        boards_with_stocks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """检查已有链的成分股变化，执行增量更新"""
        results = []

        # 构建 board_name -> codes 映射
        board_stocks_map: dict[str, set[str]] = {}
        for board in boards_with_stocks:
            board_name = board.get("board_name", "")
            codes = {s["code"] for s in board.get("stocks", []) if s.get("code")}
            if codes:
                board_stocks_map[board_name] = codes

        if not board_stocks_map:
            return results

        all_fresh_codes_by_board = list(board_stocks_map.values())

        for chain_name in existing_chains:
            try:
                update = await self._try_update_single_chain(
                    chain_name, board_stocks_map, all_fresh_codes_by_board
                )
                if update:
                    results.append(update)
            except Exception as e:
                logger.warning(f"增量更新链 {chain_name} 异常: {e}")

        if results:
            logger.info(f"增量更新完成: {len(results)} 条链有变更")
        return results

    async def _try_update_single_chain(
        self,
        chain_name: str,
        board_stocks_map: dict[str, set[str]],
        all_fresh_codes_by_board: list[set[str]],
    ) -> dict[str, Any] | None:
        """尝试增量更新单条产业链"""
        # 1. 查询链当前活跃公司
        current_result = await self._discovery.get_chain_current_companies(chain_name)
        if not current_result.success or not current_result.data:
            return None

        current_companies = current_result.data
        current_codes = {c["code"] for c in current_companies}
        if not current_codes:
            return None

        segment_uid_map = {c["code"]: c["segment_uid"] for c in current_companies}

        # 2. 从热门板块中找与本链相关的板块（重叠≥30%）
        related_fresh_codes: set[str] = set()
        for board_codes in all_fresh_codes_by_board:
            overlap = board_codes & current_codes
            threshold = max(2, int(len(current_codes) * 0.3))
            if len(overlap) >= threshold:
                related_fresh_codes |= board_codes

        if not related_fresh_codes:
            return None

        # 3. 计算 diff
        new_codes = related_fresh_codes - current_codes
        # 只标记那些在关联板块中完全消失的公司
        removed_codes = current_codes - related_fresh_codes

        # 变化不足阈值则跳过
        if len(new_codes) + len(removed_codes) < 2:
            return None

        # 4. 验证新股票代码有效性
        valid_new: set[str] = set()
        if new_codes:
            validation = await self._discovery.validate_stock_codes(list(new_codes))
            if validation.success and validation.data:
                valid_new = set(validation.data.get("valid", []))

        if not valid_new and not removed_codes:
            return None

        # 5. 为新公司分配 segment（加入公司数最多的 segment）
        segment_counts: dict[str, int] = {}
        for c in current_companies:
            seg_uid = c["segment_uid"]
            segment_counts[seg_uid] = segment_counts.get(seg_uid, 0) + 1
        default_segment = max(segment_counts, key=segment_counts.get) if segment_counts else None

        if not default_segment and valid_new:
            return None

        added_companies = [
            {"code": code, "name": "", "segment_uid": default_segment}
            for code in valid_new
        ] if default_segment else []

        # 6. 执行增量更新
        update_result = await self._discovery.update_chain_incrementally(
            chain_name=chain_name,
            added_companies=added_companies,
            removed_codes=list(removed_codes),
            segment_uid_map=segment_uid_map,
        )
        if update_result.success:
            return update_result.data
        return None

    async def _dedupe_and_score_boards(self, boards: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
        """去重 + 多维度复合评分排序"""
        seen: set[tuple[str, str]] = set()
        unique = []
        for board in boards:
            name = str(board.get("板块名称") or board.get("board_name") or "").strip()
            source_type = str(board.get("source_type") or "")
            if not name:
                continue
            key = (source_type, name)
            if key in seen:
                continue
            seen.add(key)
            unique.append(board)

        if not unique:
            return []

        # 计算成交额/总市值百分位
        turnover_percentiles = self._compute_turnover_percentiles(unique)

        # 获取 Redis 中缓存的近5日板块涨幅
        weekly_momentum_map = await self._get_weekly_momentum_from_cache(unique)

        # 缓存当日板块涨幅供后续使用
        await self._save_board_change_to_cache(unique)

        # 为每个 board 计算 composite score
        for board in unique:
            board["_candidate_score"] = self._compute_candidate_score(
                board, weekly_momentum_map, turnover_percentiles
            )

        return sorted(unique, key=lambda b: b.get("_candidate_score", 0), reverse=True)[:top_n]

    @staticmethod
    def _compute_candidate_score(
        board: dict[str, Any],
        weekly_momentum_map: dict[str, float],
        turnover_percentiles: dict[str, float],
    ) -> float:
        """计算板块的复合候选评分 (0~100)"""
        board_name = str(board.get("板块名称") or board.get("board_name") or "")

        # 维度1: 当日涨幅归一化 [-5%, +10%] → [0, 100]
        try:
            change_pct = float(board.get("涨跌幅") or 0)
        except (TypeError, ValueError):
            change_pct = 0.0
        change_score = max(0.0, min(100.0, (change_pct + 5) / 15 * 100))

        # 维度2: 上涨比例
        try:
            advancing = int(board.get("上涨家数") or 0)
            declining = int(board.get("下跌家数") or 0)
        except (TypeError, ValueError):
            advancing, declining = 0, 0
        total = advancing + declining
        advance_score = (advancing / total * 100) if total > 0 else 50.0

        # 维度3: 成交额/总市值百分位排名
        turnover_score = turnover_percentiles.get(board_name, 0.5) * 100

        # 维度4: 5日累计动量归一化 [-10%, +30%] → [0, 100]
        weekly = weekly_momentum_map.get(board_name, 0.0)
        weekly_score = max(0.0, min(100.0, (weekly + 10) / 30 * 100))

        # 加权合成
        composite = (
            CANDIDATE_SCORE_WEIGHTS["change_pct"] * change_score
            + CANDIDATE_SCORE_WEIGHTS["advance_ratio"] * advance_score
            + CANDIDATE_SCORE_WEIGHTS["turnover_rank"] * turnover_score
            + CANDIDATE_SCORE_WEIGHTS["weekly_momentum"] * weekly_score
        )
        return round(composite, 2)

    @staticmethod
    def _compute_turnover_percentiles(boards: list[dict[str, Any]]) -> dict[str, float]:
        """将成交额/总市值转为百分位排名 (0~1)"""
        named_values = []
        for b in boards:
            name = str(b.get("板块名称") or b.get("board_name") or "")
            try:
                value = float(b.get("成交额") or b.get("总市值") or 0)
            except (TypeError, ValueError):
                value = 0.0
            named_values.append((name, value))

        named_values.sort(key=lambda x: x[1])
        n = len(named_values)
        if n <= 1:
            return {name: 0.5 for name, _ in named_values}
        return {name: i / (n - 1) for i, (name, _) in enumerate(named_values)}

    async def _save_board_change_to_cache(self, boards: list[dict[str, Any]]) -> None:
        """保存当日板块涨幅到 Redis，供后续计算5日动量"""
        from data_collector.cache.redis_cache import RedisCache

        today = date.today().isoformat()
        data = {}
        for b in boards:
            name = str(b.get("板块名称") or b.get("board_name") or "")
            if not name:
                continue
            try:
                change = float(b.get("涨跌幅") or 0)
            except (TypeError, ValueError):
                continue
            data[name] = change

        if not data:
            return

        cache = RedisCache()
        try:
            await cache.connect()
            await cache.redis.set(
                f"discovery:board_daily_change:{today}",
                json.dumps(data, ensure_ascii=False),
                ex=86400 * 7,  # 保留7天
            )
        except Exception:
            pass
        finally:
            try:
                await cache.close()
            except Exception:
                pass

    async def _get_weekly_momentum_from_cache(self, boards: list[dict[str, Any]]) -> dict[str, float]:
        """从 Redis 获取近5天缓存的板块涨幅，计算累计动量"""
        from data_collector.cache.redis_cache import RedisCache

        board_names = {
            str(b.get("板块名称") or b.get("board_name") or "")
            for b in boards if b.get("板块名称") or b.get("board_name")
        }

        momentum_map: dict[str, float] = {}
        cache = RedisCache()
        try:
            await cache.connect()
            today = date.today()
            daily_data: list[dict[str, float]] = []
            for offset in range(1, 6):  # 过去5天
                day = today.toordinal() - offset
                day_str = date.fromordinal(day).isoformat()
                raw = await cache.redis.get(f"discovery:board_daily_change:{day_str}")
                if raw:
                    try:
                        daily_data.append(json.loads(raw))
                    except (json.JSONDecodeError, TypeError):
                        pass

            # 累加每天的涨幅作为动量
            for name in board_names:
                total = sum(d.get(name, 0.0) for d in daily_data)
                if total != 0.0:
                    momentum_map[name] = total
        except Exception:
            pass
        finally:
            try:
                await cache.close()
            except Exception:
                pass

        return momentum_map

    @staticmethod
    def _normalize_stock_refs(raw_stocks: list[dict[str, Any]]) -> list[dict[str, str]]:
        stocks = []
        seen: set[str] = set()
        for raw in raw_stocks:
            raw_code = raw.get("代码") or raw.get("code") or raw.get("股票代码") or ""
            code = str(raw_code).strip().split(".")[0]
            if code.isdigit() and len(code) < 6:
                code = code.zfill(6)
            name = str(raw.get("名称") or raw.get("name") or raw.get("股票简称") or "").strip()
            if len(code) != 6 or not code.isdigit() or code in seen:
                continue
            seen.add(code)
            stocks.append({"code": code, "name": name})
        return stocks

    async def _llm_construct_chains(
        self,
        boards_with_stocks: list[dict],
        existing_chains: list[str],
    ) -> list[dict]:
        """调用 LLM 分析热门板块间的上下游关系，输出产业链定义"""
        prompt = self._build_prompt(boards_with_stocks, existing_chains)
        self._last_llm_error = ""
        try:
            result = await self._llm.chat_json(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是资深A股产业链投资分析师，擅长识别板块间的上下游供应链关系。"
                            "请严格按用户要求的 JSON 格式输出，不要添加任何额外解释。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=2048,
            )
            chains = result.get("chains", [])
            return chains if isinstance(chains, list) else []
        except Exception as e:
            self._last_llm_error = str(e) or e.__class__.__name__
            logger.warning(f"LLM chain construction failed: {e}")
            return []

    def _build_prompt(
        self,
        boards_with_stocks: list[dict],
        existing_chains: list[str],
    ) -> str:
        """构建 LLM prompt"""
        boards_text = json.dumps(boards_with_stocks, ensure_ascii=False, indent=2)
        if len(boards_text) > 8000:
            boards_text = boards_text[:8000] + "\n... (已截断)"

        existing_text = "、".join(existing_chains) if existing_chains else "无"

        return f"""分析以下热门概念板块及其成分股，识别出可以构成完整产业链（有上下游供应关系）的板块组合。

## 已有产业链（请勿重复创建）
{existing_text}

## 当前热门概念板块及成分股
{boards_text}

## 数据来源说明
- source_type=concept/industry 表示来自东方财富实时板块数据。
- source_type=local_industry 表示外部板块源不可用时的本地行业分组，只能作为低置信度候选。

## 任务要求
1. 从上述板块中找出存在上下游供应链关系的板块组合（2-5个板块组成一条链）
2. 每条链需要有明确的 上游→中游→下游 结构
3. 每个环节选取 3-8 家代表性上市公司
4. 不要创建与已有产业链重复或高度重叠的链
5. 只使用上面数据中出现的股票代码，不要编造
6. 不确定上下游关系时不要创建产业链，返回空 chains 数组
7. 如果没有发现合适的产业链，返回空 chains 数组
8. 最多输出 3 条产业链

## 输出格式（严格 JSON）
{{
  "chains": [
    {{
      "chain_name": "XX产业链",
      "description": "一句话描述这条产业链",
      "segments": [
        {{
          "name": "环节名称",
          "position": "上游|中游|下游",
          "companies": [
            {{"code": "600xxx", "name": "公司名", "industry": "所属细分", "role": ""}}
          ]
        }}
      ],
      "supply_relations": [
        {{"from_code": "600xxx", "to_code": "300xxx", "product": "供应的产品/服务"}}
      ]
    }}
  ]
}}

注意:
- chain_name 格式: "XX产业链"（以"产业链"结尾）
- position 只能是: "上游"、"中游"、"下游"
- code 必须是6位A股代码
- role 填 "龙头" 或留空
- supply_relations 描述公司间的直接供应关系（可选，有则填）"""

    async def _validate_and_build(
        self,
        proposal: dict,
        source_mode: str = "",
        source_assessment: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """验证 LLM 输出的链结构，构建 Neo4j 写入格式"""
        chain_name = proposal.get("chain_name", "")
        if not chain_name:
            return None

        description = proposal.get("description", "")
        segments_raw = proposal.get("segments", [])
        if not segments_raw:
            return None

        # 收集所有股票代码
        all_codes = []
        for seg in segments_raw:
            for comp in seg.get("companies", []):
                code = comp.get("code", "")
                if code:
                    all_codes.append(code)

        if not all_codes:
            return None

        # 验证股票代码
        validation = await self._discovery.validate_stock_codes(all_codes)
        if not validation.success:
            return None
        valid_codes = set(validation.data["valid"])
        valid_details = validation.data["valid_details"]  # code -> name

        if len(valid_codes) < 3:
            logger.info(f"链 {chain_name} 有效股票不足3只({len(valid_codes)})，跳过")
            return None

        # 构建节点
        chain_node = {
            "name": chain_name,
            "description": description,
            "status": "active",
            "_source": "chain_discovery",
            "_discovery_source_mode": source_mode,
            "_discovery_confidence": (source_assessment or {}).get("confidence"),
            "_is_usable_for_discovery": bool((source_assessment or {}).get("is_usable_for_discovery")),
        }

        segments = []
        companies = []
        relationships: list[dict[str, Any]] = []

        for seg in segments_raw:
            seg_name = seg.get("name", "")
            if not seg_name:
                continue
            position = seg.get("position", "中游")
            uid = f"{chain_name}::{seg_name}"

            segments.append(
                {
                    "uid": uid,
                    "name": seg_name,
                    "position": position,
                    "chain_name": chain_name,
                }
            )

            for comp in seg.get("companies", []):
                code = comp.get("code", "")
                if code not in valid_codes:
                    continue
                name = valid_details.get(code, comp.get("name", ""))
                industry = comp.get("industry", "")

                companies.append(
                    {
                        "code": code,
                        "name": name,
                        "industry": industry,
                    }
                )

                # Company -BELONGS_TO-> Segment
                role = comp.get("role", "")
                rel_props = {"role": role} if role else {}
                relationships.append(
                    {
                        "from_label": "Company",
                        "from_key_field": "code",
                        "from_key_value": code,
                        "to_label": "Segment",
                        "to_key_field": "uid",
                        "to_key_value": uid,
                        "rel_type": "BELONGS_TO",
                        "properties": rel_props,
                    }
                )

        if not segments or not companies:
            return None

        # 构建 TRANSMITS_TO 关系（下游 → 中游 → 上游）
        position_order = {"下游": 0, "中游": 1, "上游": 2}
        sorted_segments = sorted(segments, key=lambda s: position_order.get(s["position"], 1))
        for i in range(len(sorted_segments) - 1):
            relationships.append(
                {
                    "from_label": "Segment",
                    "from_key_field": "uid",
                    "from_key_value": sorted_segments[i]["uid"],
                    "to_label": "Segment",
                    "to_key_field": "uid",
                    "to_key_value": sorted_segments[i + 1]["uid"],
                    "rel_type": "TRANSMITS_TO",
                    "properties": {},
                }
            )

        # 构建 SUPPLIES_TO 关系（如果 LLM 提供了）
        for supply in proposal.get("supply_relations", []):
            from_code = supply.get("from_code", "")
            to_code = supply.get("to_code", "")
            if from_code in valid_codes and to_code in valid_codes:
                relationships.append(
                    {
                        "from_label": "Company",
                        "from_key_field": "code",
                        "from_key_value": from_code,
                        "to_label": "Company",
                        "to_key_field": "code",
                        "to_key_value": to_code,
                        "rel_type": "SUPPLIES_TO",
                        "properties": {"product": supply.get("product", "")},
                    }
                )

        return {
            "chain": chain_node,
            "segments": segments,
            "companies": companies,
            "relationships": relationships,
        }
