"""交互式股票分析 Agent：基于真实入库数据进行多轮选股与个股分析。"""

from __future__ import annotations

import json
from typing import Any

from agents.base import BaseAgent
from agents.tools.stock_data_tools import StockDataTools, extract_stock_codes, normalize_stock_code


class StockAnalysisAgent(BaseAgent):
    """面向用户多轮问答的股票分析 Agent。"""

    agent_id = "stock_analysis"

    def __init__(self, session_factory, llm_client=None):
        super().__init__(session_factory, llm_client)
        self._stock_tools = StockDataTools(session_factory)

    async def _run_impl(self, params: dict[str, Any]) -> dict[str, Any]:
        context = await self._build_context(params)
        try:
            llm_result = await self._llm.chat_json(
                [
                    {"role": "system", "content": self._system_prompt()},
                    {"role": "user", "content": json.dumps(context, ensure_ascii=False, default=str)},
                ],
                temperature=0.2,
                max_tokens=2400,
            )
        except Exception as e:
            fallback = self._fallback_answer(context)
            fallback["llm_error"] = str(e)
            return fallback
        return self._normalize_llm_result(llm_result, context)

    async def _run_fallback(self, params: dict[str, Any]) -> dict[str, Any]:
        context = await self._build_context(params)
        return self._fallback_answer(context)

    async def build_stream_context(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self._build_context(params)

    def fallback_from_context(self, context: dict[str, Any]) -> dict[str, Any]:
        return self._fallback_answer(context)

    def normalize_stream_result(self, answer: str, context: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
        primary = context.get("primary_tool") or {}
        data = primary.get("data") if primary.get("success") else None
        normalized = dict(base)
        normalized.update(
            {
                "status": "completed",
                "mode": context.get("mode", "screen"),
                "answer": answer.strip() or base.get("answer") or self._compose_fallback_answer(context.get("mode"), data),
                "confidence": base.get("confidence") or self._resolve_confidence(context),
                "data_gaps": base.get("data_gaps") or self._collect_data_gaps(context),
                "picks": base.get("picks") or self._extract_picks(data),
                "snapshots": base.get("snapshots") or self._extract_snapshots(context.get("mode"), data),
                "follow_up_questions": base.get("follow_up_questions")
                or self._follow_up_questions(context.get("mode"), base.get("data_gaps") or []),
                "page_context": context.get("page_context", {}),
                "tool_results": context.get("tool_results", []),
                "source_policy": context.get("data_policy"),
            }
        )
        return normalized

    async def _build_context(self, params: dict[str, Any]) -> dict[str, Any]:
        message = str(params.get("message") or params.get("query") or "").strip()
        history = self._normalize_history(params.get("history") or [])
        filters = dict(params.get("filters") or {})
        page_context = params.get("page_context") if isinstance(params.get("page_context"), dict) else {}
        limit = max(1, min(int(params.get("limit") or filters.get("limit") or 10), 50))
        history_text = "\n".join(str(item.get("content") or "") for item in history[-8:])
        codes = self._collect_codes(params, f"{history_text}\n{message}")
        mode = self._detect_mode(message, codes)

        coverage = await self._call_tool("coverage", self._stock_tools.get_coverage)
        chains = await self._call_tool("list_chains", self._stock_tools.list_chains)
        chain_name = self._resolve_chain_name(message, filters, chains.get("data") if chains.get("success") else [])
        tool_results = [coverage, chains]

        if mode == "coverage":
            primary = coverage
        elif mode == "compare":
            primary = await self._call_tool("compare", self._stock_tools.compare_stocks, codes=codes[:6])
            tool_results.append(primary)
        elif mode == "analyze":
            primary = await self._call_tool("snapshot", self._stock_tools.get_stock_snapshot, code=codes[0])
            tool_results.append(primary)
        else:
            primary = await self._call_tool(
                "screen",
                self._stock_tools.screen_stocks,
                limit=limit,
                chain_name=chain_name,
                industry=filters.get("industry"),
                min_score=filters.get("min_score"),
                risk_tolerance=filters.get("risk_tolerance"),
            )
            tool_results.append(primary)

        return {
            "message": message,
            "history": history[-8:],
            "mode": mode,
            "codes": codes,
            "filters": {**filters, "chain_name": chain_name, "limit": limit},
            "page_context": page_context,
            "primary_tool": primary,
            "tool_results": tool_results,
            "data_policy": "仅使用系统已入库的股票、K线、财报、信号和知识图谱数据；缺失数据必须标注，不得补造。",
        }

    async def _call_tool(self, action: str, fn, **kwargs) -> dict[str, Any]:
        result = await fn(**kwargs)
        return {
            "tool": f"{self._stock_tools.tool_name}.{action}",
            "params": kwargs,
            "success": result.success,
            "data": result.data,
            "error": result.error,
        }

    @staticmethod
    def _normalize_history(history: list[dict[str, Any]]) -> list[dict[str, str]]:
        normalized = []
        for item in history:
            role = str(item.get("role") or "")
            content = str(item.get("content") or "").strip()
            if role in {"user", "assistant"} and content:
                normalized.append({"role": role, "content": content[:3000]})
        return normalized

    @staticmethod
    def _collect_codes(params: dict[str, Any], text: str) -> list[str]:
        codes = []
        for raw_code in params.get("codes") or []:
            code = normalize_stock_code(raw_code)
            if code and code not in codes:
                codes.append(code)
        for code in extract_stock_codes(text):
            if code not in codes:
                codes.append(code)
        return codes

    @staticmethod
    def _detect_mode(message: str, codes: list[str]) -> str:
        if any(word in message for word in ["覆盖", "数据够", "数据缺", "数据质量", "有哪些数据"]):
            return "coverage"
        if len(codes) >= 2 or any(word in message for word in ["对比", "比较", "哪个更", "谁更"]):
            return "compare" if codes else "screen"
        if codes:
            return "analyze"
        return "screen"

    @staticmethod
    def _resolve_chain_name(message: str, filters: dict[str, Any], chains: list[dict[str, Any]]) -> str | None:
        explicit = filters.get("chain_name") or filters.get("chain_id")
        if explicit:
            return str(explicit)
        for chain in chains:
            name = str(chain.get("name") or "")
            if name and name in message:
                return name
        return None

    @staticmethod
    def _system_prompt() -> str:
        return (
            "你是股票分析 Agent。你只能基于 user JSON 中的工具结果回答，禁止补造缺失数据，"
            "禁止把推测写成事实。user JSON 中的 page_context 是用户当前投研页面可见数据，"
            "回答当前页面、当前产业链或当前候选股时必须优先使用它。输出严格 JSON，字段包括 "
            "answer, confidence, data_gaps, picks, snapshots, follow_up_questions。answer 用中文，先给结论，再给数据依据和风险。"
        )

    @staticmethod
    def stream_system_prompt() -> str:
        return (
            "你是股票分析 Agent。你只能基于 user JSON 中的工具结果和 page_context 回答，禁止补造缺失数据，"
            "禁止把推测写成事实。请直接输出中文正文，不要输出 JSON、Markdown 代码块或额外字段。"
            "回答要结论先行，然后给数据依据、风险和数据缺口；如果数据不足，明确说明置信度低。"
        )

    @staticmethod
    def _fallback_answer(context: dict[str, Any]) -> dict[str, Any]:
        mode = context.get("mode", "screen")
        primary = context.get("primary_tool") or {}
        data = primary.get("data") if primary.get("success") else None
        answer = StockAnalysisAgent._compose_fallback_answer(mode, data, primary.get("error"))
        data_gaps = StockAnalysisAgent._collect_data_gaps(context)
        return {
            "status": "completed",
            "mode": mode,
            "answer": answer,
            "confidence": StockAnalysisAgent._resolve_confidence(context),
            "data_gaps": data_gaps,
            "picks": StockAnalysisAgent._extract_picks(data),
            "snapshots": StockAnalysisAgent._extract_snapshots(mode, data),
            "follow_up_questions": StockAnalysisAgent._follow_up_questions(mode, data_gaps),
            "page_context": context.get("page_context", {}),
            "tool_results": context.get("tool_results", []),
            "source_policy": context.get("data_policy"),
        }

    @staticmethod
    def _normalize_llm_result(result: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        primary = context.get("primary_tool") or {}
        data = primary.get("data") if primary.get("success") else None
        return {
            "status": "completed",
            "mode": context.get("mode", "screen"),
            "answer": str(result.get("answer") or StockAnalysisAgent._compose_fallback_answer(context.get("mode"), data)),
            "confidence": result.get("confidence") or StockAnalysisAgent._resolve_confidence(context),
            "data_gaps": result.get("data_gaps") or StockAnalysisAgent._collect_data_gaps(context),
            "picks": result.get("picks") or StockAnalysisAgent._extract_picks(data),
            "snapshots": result.get("snapshots") or StockAnalysisAgent._extract_snapshots(context.get("mode"), data),
            "follow_up_questions": result.get("follow_up_questions")
            or StockAnalysisAgent._follow_up_questions(context.get("mode"), result.get("data_gaps") or []),
            "page_context": context.get("page_context", {}),
            "tool_results": context.get("tool_results", []),
            "source_policy": context.get("data_policy"),
        }

    @staticmethod
    def _compose_fallback_answer(mode: str | None, data: Any, error: str | None = None) -> str:
        if error:
            return f"数据工具调用失败：{error}"
        if mode == "coverage" and isinstance(data, dict):
            return (
                f"当前股票基础数据 {data.get('stock_count', 0)} 只，候选池 {data.get('candidate_count', 0)} 只；"
                f"候选池K线覆盖 {data.get('candidate_kline_coverage', 0)}/{data.get('candidate_count', 0)}，"
                f"财报覆盖 {data.get('candidate_financial_coverage', 0)}/{data.get('candidate_count', 0)}。"
            )
        if mode == "analyze" and isinstance(data, dict):
            stock = data.get("stock") or {}
            metrics = data.get("metrics") or {}
            financial = data.get("latest_financial") or {}
            return (
                f"{stock.get('name') or data.get('code')}({data.get('code')})："
                f"近5日涨跌幅 {metrics.get('return_5d')}%，近20日 {metrics.get('return_20d')}%；"
                f"最新净利同比 {financial.get('net_profit_yoy')}%，"
                f"近期信号 {len(data.get('recent_signals') or [])} 个。"
            )
        if mode == "compare" and isinstance(data, dict):
            parts = []
            for item in data.get("items") or []:
                stock = item.get("stock") or {}
                metrics = item.get("metrics") or {}
                parts.append(
                    f"{stock.get('name') or item.get('code')}({item.get('code')}) "
                    f"近20日{metrics.get('return_20d')}%，信号{len(item.get('recent_signals') or [])}个"
                )
            return "；".join(parts) or "没有可对比的有效标的。"
        if isinstance(data, dict):
            items = data.get("items") or []
            if not items:
                return "没有筛出符合条件的候选股，需要补充图谱、信号、K线或财报数据后再筛选。"
            parts = [f"{item.get('name')}({item.get('code')}) {item.get('score')}分" for item in items[:5]]
            return "按当前真实入库数据筛选，靠前候选为：" + "；".join(parts)
        return "当前没有可用工具结果。"

    @staticmethod
    def _collect_data_gaps(context: dict[str, Any]) -> list[str]:
        gaps = []
        for tool in context.get("tool_results") or []:
            if not tool.get("success"):
                gaps.append(f"{tool.get('tool')} 调用失败: {tool.get('error')}")
                continue
            data = tool.get("data")
            if isinstance(data, dict):
                for gap in data.get("data_gaps") or []:
                    if gap not in gaps:
                        gaps.append(gap)
        return gaps

    @staticmethod
    def _resolve_confidence(context: dict[str, Any]) -> str:
        primary = context.get("primary_tool") or {}
        data = primary.get("data") if primary.get("success") else None
        if isinstance(data, dict) and data.get("confidence"):
            return str(data["confidence"])
        if not primary.get("success"):
            return "low"
        return "medium"

    @staticmethod
    def _extract_picks(data: Any) -> list[dict[str, Any]]:
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return data["items"][:10]
        return []

    @staticmethod
    def _extract_snapshots(mode: str | None, data: Any) -> list[dict[str, Any]]:
        if mode == "analyze" and isinstance(data, dict):
            return [data]
        if mode == "compare" and isinstance(data, dict):
            return list(data.get("items") or [])
        return []

    @staticmethod
    def _follow_up_questions(mode: str | None, data_gaps: list[str]) -> list[str]:
        if data_gaps:
            return ["是否先补齐 K线/财报/信号数据后再筛一遍？"]
        if mode == "screen":
            return ["要不要按某条产业链、低风险或最低评分继续收窄？"]
        if mode == "compare":
            return ["要不要把对比结果转成观察清单？"]
        return ["要不要继续看估值、财务趋势或近期信号明细？"]
