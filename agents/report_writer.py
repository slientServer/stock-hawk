"""报告生成 Agent：自动生成研究报告。"""

from typing import Any

from agents.base import BaseAgent


class ReportWriterAgent(BaseAgent):
    agent_id = "report_writer"

    async def _run_impl(self, params: dict[str, Any]) -> dict[str, Any]:
        report_type = params.get("type") or params.get("workflow_type") or "summary"
        content = self._format_report(report_type, params)
        return {
            "status": "completed",
            "report_type": report_type,
            "report": content,
            "input": params,
            "confidence": "medium" if content else "low",
        }

    def _format_report(self, report_type: str, params: dict[str, Any]) -> str:
        scan = params.get("scan") or {}
        results = scan.get("results") or []
        if report_type == "alert":
            focus = [item for item in results if item.get("signal_count", 0) > 0 or item.get("score", 0) >= 30]
            lines = ["产业链评分预警", ""]
            if not focus:
                lines.append("本次扫描未发现达到预警阈值的产业链。")
            for item in focus[:5]:
                lines.append(
                    f"- {item.get('chain_id')}: 评分 {item.get('score')}，"
                    f"级别 {item.get('level')}，信号 {item.get('signal_count')} 个"
                )
            return "\n".join(lines)

        if report_type == "weekly":
            lines = ["# 产业链周度观察", "", "| 产业链 | 评分 | 级别 | 信号数 |", "|---|---:|---|---:|"]
            for item in sorted(results, key=lambda row: row.get("score", 0), reverse=True)[:10]:
                lines.append(
                    f"| {item.get('chain_id')} | {item.get('score')} | {item.get('level')} | {item.get('signal_count')} |"
                )
            picks = params.get("picks") or {}
            recs = picks.get("recommendations") or {}
            if any(recs.values()):
                lines.extend(["", "## 推荐关注标的"])
                for label, key in [("核心", "core"), ("卫星", "satellite"), ("观察", "watchlist")]:
                    names = [f"{item.get('name')}({item.get('code')})" for item in recs.get(key, [])[:5]]
                    if names:
                        lines.append(f"- {label}: " + "、".join(names))
            gaps = picks.get("data_gaps") or []
            if gaps:
                lines.extend(["", "## 数据缺口"])
                lines.extend(f"- {gap}" for gap in gaps)
            return "\n".join(lines)

        if report_type == "deep_research":
            chain_id = params.get("chain_id") or "未指定产业链"
            analysis = params.get("analysis") or {}
            picks = params.get("picks") or {}
            recs = picks.get("recommendations") or {}
            lines = [
                f"# {chain_id}深度研究",
                "",
                "## 结论",
                analysis.get("driving_factors") or "暂无足够真实数据形成驱动归因。",
                "",
                "## 阶段判断",
                f"- 趋势类型: {analysis.get('trend_type') or 'data_insufficient'}",
                f"- 当前阶段: {analysis.get('current_stage') or 'watching'}",
                f"- 依据: {analysis.get('stage_evidence') or '数据缺失'}",
                "",
                "## 传导路径",
            ]
            path = analysis.get("transmission_path") or []
            if path:
                for item in path:
                    lines.append(
                        f"- {item.get('position') or '-'} / {item.get('segment')}: "
                        f"{item.get('signal_count', 0)} 个信号，{item.get('status')}"
                    )
            else:
                lines.append("- 知识图谱传导路径缺失")
            lines.extend(
                [
                    "",
                    "## 弹性环节",
                    analysis.get("elasticity_reason") or "暂无足够信号定位弹性环节",
                    "",
                    "## 标的分层",
                ]
            )
            for label, key in [("核心", "core"), ("卫星", "satellite"), ("观察", "watchlist")]:
                items = recs.get(key, [])[:5]
                lines.append(f"### {label}")
                if not items:
                    lines.append("暂无满足真实数据条件的候选。")
                for item in items:
                    lines.append(f"- {item.get('name')}({item.get('code')}): 评分 {item.get('score')}；{item.get('logic')}")
            gaps = list(analysis.get("data_gaps") or []) + list(picks.get("data_gaps") or [])
            if gaps:
                lines.extend(["", "## 数据缺口"])
                lines.extend(f"- {gap}" for gap in gaps)
            lines.extend(["", "本报告仅使用已入库真实数据；缺失数据未做模拟填充。"])
            return "\n".join(lines)

        return str(params)
