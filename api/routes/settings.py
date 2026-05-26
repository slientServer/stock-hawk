"""设置路由：当前功能的运行配置。"""

from __future__ import annotations

import json
from typing import Any

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel

from common.config import RUNTIME_SETTINGS_PATH, get_settings, load_runtime_settings

router = APIRouter(prefix="/settings", tags=["设置"])


class LLMTestRequest(BaseModel):
    custom_base_url: str | None = None


def _configured(value: str | None) -> bool:
    return bool(value and value.strip())


def _preview(text: str, limit: int = 1200) -> str:
    return text[:limit] + ("..." if len(text) > limit else "")


@router.get("")
async def read_settings() -> dict[str, Any]:
    settings = get_settings()
    return {
        "database": {
            "host": settings.db.host,
            "port": settings.db.port,
            "db": settings.db.db,
            "user": settings.db.user,
        },
        "redis": {"url": settings.redis.url},
        "llm": {
            "custom_configured": _configured(settings.llm.custom_base_url),
            "custom_base_url": settings.llm.custom_base_url,
            "custom_model": settings.llm.custom_model,
        },
        "data_source": {
            "tushare_configured": _configured(settings.data_source.tushare_token),
            "eastmoney_cookie_configured": _configured(settings.data_source.eastmoney_cookie),
            "eastmoney_user_agent_configured": _configured(settings.data_source.eastmoney_user_agent),
            "eastmoney_user_agent": settings.data_source.eastmoney_user_agent,
            "market_proxy_configured": _configured(settings.data_source.market_proxy_url),
            "market_proxy_url": settings.data_source.market_proxy_url,
            "market_request_timeout": settings.data_source.market_request_timeout,
        },
        "feishu": {"webhook_configured": _configured(settings.feishu.webhook_url)},
        "log_level": settings.log_level,
    }


@router.put("")
async def update_settings(data: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "custom_api_key",
        "custom_base_url",
        "custom_model",
        "tushare_token",
        "eastmoney_cookie",
        "eastmoney_user_agent",
        "market_proxy_url",
        "market_request_timeout",
        "feishu_webhook_url",
        "log_level",
    }
    current = load_runtime_settings()
    for key, value in data.items():
        if key in allowed and value not in (None, ""):
            current[key] = value
    RUNTIME_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_SETTINGS_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    get_settings.cache_clear()
    return {"status": "ok", "updated_keys": sorted(key for key in data if key in allowed)}


def _diagnose_llm_failure(
    *,
    error_type: str | None = None,
    status_code: int | None = None,
    response_text: str = "",
) -> list[str]:
    text = response_text.lower()
    reasons: list[str] = []
    if error_type == "timeout":
        reasons.append("请求超时：Base URL 网络不可达、网关无响应，或模型响应超过 20 秒")
    elif error_type == "connect":
        reasons.append("连接失败：Base URL 域名、端口、代理或本机网络可能不可达")
    elif error_type == "invalid_url":
        reasons.append("URL 无效：Custom Base URL 需要是 http(s) 地址")
    if status_code in {401, 403}:
        reasons.append("认证或权限失败：如网关需要 Key，请补齐 Custom Token")
    elif status_code == 404:
        reasons.append("接口不存在：系统会请求 {Custom Base URL}/chat/completions")
    elif status_code == 429:
        reasons.append("额度或频率限制：账号余额、并发或限流可能不足")
    elif status_code and status_code >= 500:
        reasons.append("模型服务端错误：网关或上游模型服务异常")
    if "model" in text and any(word in text for word in ["not found", "invalid", "permission", "权限"]):
        reasons.append("模型名或模型权限异常")
    if not reasons:
        reasons.append("未能从错误中判断唯一原因，请查看 HTTP 状态码和响应正文")
    return reasons


@router.post("/llm/test")
async def test_llm_settings(req: LLMTestRequest) -> dict[str, Any]:
    settings = get_settings().llm
    base_url = (req.custom_base_url or settings.custom_base_url or "").strip().rstrip("/")
    if not base_url:
        return {"status": "missing", "ok": False, "message": "Custom Base URL 未配置", "diagnosis": ["请先填写 Custom Base URL"]}
    if not base_url.startswith(("http://", "https://")):
        return {
            "status": "failed",
            "ok": False,
            "error_type": "invalid_url",
            "request_url": f"{base_url}/chat/completions",
            "message": "Custom Base URL 不是有效的 http(s) 地址",
            "diagnosis": _diagnose_llm_failure(error_type="invalid_url"),
        }

    request_url = f"{base_url}/chat/completions"
    model = settings.custom_model or "gpt-4o-mini"
    headers = {"Content-Type": "application/json"}
    if settings.custom_api_key:
        headers["Authorization"] = f"Bearer {settings.custom_api_key}"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a health check endpoint. Return JSON only."},
            {"role": "user", "content": '{"ping":"ok"}'},
        ],
        "temperature": 0,
        "max_tokens": 32,
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(request_url, headers=headers, json=body)
    except httpx.TimeoutException as e:
        return {
            "status": "failed",
            "ok": False,
            "error_type": "timeout",
            "request_url": request_url,
            "model": model,
            "message": str(e) or "请求超时",
            "diagnosis": _diagnose_llm_failure(error_type="timeout"),
        }
    except httpx.ConnectError as e:
        return {
            "status": "failed",
            "ok": False,
            "error_type": "connect",
            "request_url": request_url,
            "model": model,
            "message": str(e) or "连接失败",
            "diagnosis": _diagnose_llm_failure(error_type="connect"),
        }
    except httpx.HTTPError as e:
        return {
            "status": "failed",
            "ok": False,
            "error_type": e.__class__.__name__,
            "request_url": request_url,
            "model": model,
            "message": str(e),
            "diagnosis": _diagnose_llm_failure(error_type="http"),
        }

    response_text = response.text
    if response.status_code >= 400:
        return {
            "status": "failed",
            "ok": False,
            "request_url": request_url,
            "model": model,
            "http_status": response.status_code,
            "response_preview": _preview(response_text),
            "message": f"HTTP {response.status_code}",
            "diagnosis": _diagnose_llm_failure(status_code=response.status_code, response_text=response_text),
        }
    try:
        payload = response.json()
        content = payload.get("choices", [{}])[0].get("message", {}).get("content")
    except Exception:
        return {
            "status": "failed",
            "ok": False,
            "request_url": request_url,
            "model": model,
            "http_status": response.status_code,
            "response_preview": _preview(response_text),
            "message": "HTTP 成功，但响应不是 Chat Completions JSON",
            "diagnosis": ["接口可访问，但协议不兼容；系统要求响应包含 choices[0].message.content"],
        }
    if not content:
        return {
            "status": "failed",
            "ok": False,
            "request_url": request_url,
            "model": model,
            "http_status": response.status_code,
            "response_preview": _preview(response_text),
            "message": "响应缺少 choices[0].message.content",
            "diagnosis": ["接口可访问，但响应结构不符合 Chat Completions 协议"],
        }
    return {
        "status": "ok",
        "ok": True,
        "request_url": request_url,
        "model": model,
        "http_status": response.status_code,
        "message": "Custom Base URL 调用成功",
        "response_preview": _preview(str(content), 400),
        "diagnosis": ["LLM 端点可用"],
    }


@router.get("/scheduler")
async def scheduler_info(request: Request) -> dict[str, Any]:
    scheduler = getattr(request.app.state, "agent_scheduler", None)
    if scheduler:
        return {"jobs": scheduler.get_jobs(), "status": "started", "running": []}
    return {
        "jobs": [
            {"id": "finance_news_hourly", "name": "财经资讯每小时拉取与今日小结", "next_run": None},
            {"id": "etf_analysis", "name": "每日盘后 ETF 大模型轮动分析", "next_run": None},
        ],
        "status": "not_started",
        "running": [],
    }


@router.post("/workflows/trigger")
async def trigger_workflow(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """手动触发指定工作流。
    workflow_type 可选值: daily_kline / main_flow / etf_analysis / pre_market / pre_market_perf / finance_news
    """
    workflow_type = body.get("workflow_type", "")
    if not workflow_type:
        return {"error": "workflow_type 不能为空"}
    scheduler = getattr(request.app.state, "agent_scheduler", None)
    if not scheduler:
        return {"error": "调度器未启动"}
    kwargs = {k: v for k, v in body.items() if k != "workflow_type"}
    try:
        result = await scheduler.trigger_manual(workflow_type, **kwargs)
        return {"workflow_type": workflow_type, "result": result}
    except Exception as e:
        return {"error": str(e), "workflow_type": workflow_type}
