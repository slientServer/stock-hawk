"""设置路由：系统配置管理。"""

import asyncio
import json
from typing import Any

import httpx
import requests
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from agents.tools.discovery_tools import DiscoveryTools
from api.deps import get_session_factory
from common.config import RUNTIME_SETTINGS_PATH, get_settings, load_runtime_settings

router = APIRouter(prefix="/settings", tags=["设置"])


class LLMTestRequest(BaseModel):
    custom_base_url: str | None = None


class MarketSourceTestRequest(BaseModel):
    eastmoney_cookie: str | None = None
    eastmoney_user_agent: str | None = None
    market_proxy_url: str | None = None
    market_request_timeout: int | None = None


def _configured(value: str | None) -> bool:
    return bool(value and value.strip())


def _preview(text: str, limit: int = 1200) -> str:
    return text[:limit] + ("..." if len(text) > limit else "")


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
        reasons.append(
            "认证或权限失败：如果该网关需要 Key，请在服务端运行配置中补齐 custom_api_key；也可能是模型权限未开通"
        )
    elif status_code == 404:
        reasons.append(
            "接口不存在：系统会请求 {Custom Base URL}/chat/completions，请确认 Base URL 不要填到具体接口之外"
        )
    elif status_code == 429:
        reasons.append("额度或频率限制：账号余额、并发或限流可能不足")
    elif status_code and status_code >= 500:
        reasons.append("模型服务端错误：网关或上游模型服务异常")

    if "model" in text and any(word in text for word in ["not found", "not exist", "invalid", "permission", "权限"]):
        reasons.append("模型名或模型权限异常：当前后台模型配置可能不可用")
    if "insufficient" in text or "quota" in text or "balance" in text or "余额" in text:
        reasons.append("账号额度异常：余额不足或配额不足")
    if not reasons:
        reasons.append("未能从错误中判断唯一原因，请查看 HTTP 状态码和响应正文")
    return reasons


@router.get("")
async def read_settings():
    settings = get_settings()
    return {
        "database": {
            "host": settings.db.host,
            "port": settings.db.port,
            "db": settings.db.db,
            "user": settings.db.user,
        },
        "neo4j": {"uri": settings.neo4j.uri, "user": settings.neo4j.user},
        "redis": {"url": settings.redis.url},
        "llm": {
            "custom_configured": _configured(settings.llm.custom_base_url),
            "custom_base_url": settings.llm.custom_base_url,
            "custom_model": settings.llm.custom_model,
            "deepseek_configured": _configured(settings.llm.deepseek_api_key),
            "openai_configured": _configured(settings.llm.openai_api_key),
            "openai_base_url": settings.llm.openai_base_url,
            "claude_configured": _configured(settings.llm.claude_api_key),
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
        "feishu": {
            "webhook_configured": _configured(settings.feishu.webhook_url),
        },
        "log_level": settings.log_level,
    }


@router.put("")
async def update_settings(data: dict[str, Any]):
    allowed = {
        "custom_api_key",
        "custom_base_url",
        "custom_model",
        "deepseek_api_key",
        "tushare_token",
        "eastmoney_cookie",
        "eastmoney_user_agent",
        "market_proxy_url",
        "market_request_timeout",
        "openai_api_key",
        "openai_base_url",
        "claude_api_key",
        "feishu_webhook_url",
        "log_level",
    }
    current = load_runtime_settings()
    for key, value in data.items():
        if key in allowed and value not in (None, ""):
            current[key] = value
    RUNTIME_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_SETTINGS_PATH.write_text(
        json.dumps(current, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    get_settings.cache_clear()
    return {"status": "ok", "updated_keys": sorted(key for key in data if key in allowed)}


@router.post("/llm/test")
async def test_llm_settings(req: LLMTestRequest):
    """测试 Custom Base URL，并返回可读诊断信息。"""
    settings = get_settings().llm
    base_url = (req.custom_base_url or settings.custom_base_url or "").strip().rstrip("/")
    if not base_url:
        return {
            "status": "missing",
            "ok": False,
            "message": "Custom Base URL 未配置",
            "diagnosis": ["请先填写 Custom Base URL"],
        }
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
            "diagnosis": _diagnose_llm_failure(
                status_code=response.status_code,
                response_text=response_text,
            ),
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
            "diagnosis": ["接口可访问，但协议不兼容；系统要求 /chat/completions 响应包含 choices[0].message.content"],
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


def _market_request_value(req: MarketSourceTestRequest, field_name: str) -> Any:
    request_value = getattr(req, field_name)
    if request_value not in (None, ""):
        return request_value
    return getattr(get_settings().data_source, field_name)


def _market_test_headers(req: MarketSourceTestRequest) -> dict[str, str]:
    user_agent = _market_request_value(req, "eastmoney_user_agent")
    cookie = _market_request_value(req, "eastmoney_cookie")
    headers = {
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "close",
        "Referer": "https://quote.eastmoney.com/center/boardlist.html",
        "User-Agent": user_agent
        or (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        ),
    }
    if cookie:
        headers["Cookie"] = cookie
    return headers


def _market_test_proxies(req: MarketSourceTestRequest) -> dict[str, str] | None:
    proxy_url = str(_market_request_value(req, "market_proxy_url") or "").strip()
    if not proxy_url:
        return None
    return {"http": proxy_url, "https": proxy_url}


def _market_test_timeout(req: MarketSourceTestRequest) -> int:
    timeout = _market_request_value(req, "market_request_timeout")
    try:
        return max(3, min(int(timeout), 60))
    except (TypeError, ValueError):
        return 15


def _push2_test_urls(preferred_hosts: list[str]) -> list[str]:
    default_hosts = ["17", "79", "69", "70", "80", "82", "29", "1", "64"]
    hosts: list[str] = []
    for host in [*preferred_hosts, *default_hosts]:
        host_text = str(host).strip()
        if host_text and host_text not in hosts:
            hosts.append(host_text)
    return [f"https://{host}.push2.eastmoney.com/api/qt/clist/get" for host in hosts]


def _test_eastmoney_endpoint(req: MarketSourceTestRequest, source_type: str) -> dict[str, Any]:
    if source_type == "concept":
        urls = _push2_test_urls(["17", "70", "80", "82", "79"])
        params = {
            "pn": "1",
            "pz": "5",
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f12",
            "fs": "m:90 t:3 f:!50",
            "fields": "f3,f12,f14",
        }
        label = "东方财富概念板块"
    else:
        urls = _push2_test_urls(["79", "17", "70", "80", "82"])
        params = {
            "pn": "1",
            "pz": "5",
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": "m:90 t:2 f:!50",
            "fields": "f3,f12,f14",
        }
        label = "东方财富行业板块"

    errors: list[str] = []
    for url in urls:
        try:
            response = requests.get(
                url,
                params=params,
                headers=_market_test_headers(req),
                proxies=_market_test_proxies(req),
                timeout=_market_test_timeout(req),
            )
            response.raise_for_status()
            payload = response.json()
            diff = (payload.get("data") or {}).get("diff") or []
            samples = [
                {"board_code": item.get("f12"), "board_name": item.get("f14"), "change_pct": item.get("f3")}
                for item in diff[:5]
            ]
            if samples:
                return {
                    "source_type": source_type,
                    "label": label,
                    "ok": True,
                    "request_url": url,
                    "http_status": response.status_code,
                    "records": len(diff),
                    "samples": samples,
                    "message": "接口返回有效板块数据",
                }
            errors.append(f"{url}: empty diff")
        except Exception as e:
            errors.append(f"{url}: {e.__class__.__name__}: {e}")
    return {
        "source_type": source_type,
        "label": label,
        "ok": False,
        "message": "所有 push2 分片域名均不可用",
        "error_type": "AllPush2HostsFailed",
        "errors": errors[:8],
    }


@router.post("/market-source/test")
async def test_market_source_settings(req: MarketSourceTestRequest, session_factory=Depends(get_session_factory)):
    """按产业链发现的真实取数路径测试外部板块源。"""
    tools = DiscoveryTools(session_factory)
    concept, industry = await asyncio.gather(
        tools.fetch_hot_concept_boards(top_n=5, min_change_pct=0),
        tools.fetch_hot_industry_boards(top_n=5, min_change_pct=0),
    )
    results = [_market_tool_result("concept", "概念板块", concept), _market_tool_result("industry", "行业板块", industry)]
    ok = any(item.get("ok") for item in results)
    return {
        "status": "ok" if ok else "failed",
        "ok": ok,
        "message": "产业链发现外部板块源可用" if ok else "产业链发现外部板块源不可用，请查看失败原因",
        "requires_token": False,
        "requires_cookie": False,
        "configured": {
            "eastmoney_cookie": bool(_market_request_value(req, "eastmoney_cookie")),
            "eastmoney_user_agent": bool(_market_request_value(req, "eastmoney_user_agent")),
            "market_proxy_url": bool(_market_request_value(req, "market_proxy_url")),
            "market_request_timeout": _market_test_timeout(req),
        },
        "sources": results,
        "diagnosis": [
            "AKShare 是 Python 包，不需要 Token；当前产业链发现用的是 AKShare/东方财富公开行情接口。",
            "东方财富公开板块接口通常不需要 Cookie；如果公司网络、代理或反爬导致断连，可填写 Cookie、User-Agent 或代理后重试。",
            "该测试复用产业链发现的真实取数路径：东方财富直连、AKShare 东方财富、AKShare 新浪与短期缓存。",
            "至少一个概念/行业源可用时，自动发现可继续运行；两个都失败时系统不会使用本地行业分组当作热门板块。",
        ],
    }


def _market_tool_result(source_type: str, label: str, result) -> dict[str, Any]:
    if not result.success:
        return {"source_type": source_type, "label": label, "ok": False, "message": result.error}
    data = result.data or {}
    return {
        "source_type": source_type,
        "label": label,
        "ok": True,
        "source_name": data.get("source_name"),
        "records": len(data.get("boards") or []),
        "total_count": data.get("total_count"),
        "max_change_pct": data.get("max_change_pct"),
        "cache_info": data.get("cache_info"),
        "samples": [
            {
                "board_code": item.get("板块代码") or item.get("board_code"),
                "board_name": item.get("板块名称") or item.get("board_name"),
                "change_pct": item.get("涨跌幅") or item.get("change_pct"),
            }
            for item in (data.get("top_boards") or [])[:5]
        ],
    }


@router.get("/scheduler")
async def scheduler_info(request: Request):
    scheduler = getattr(request.app.state, "agent_scheduler", None)
    runner = getattr(request.app.state, "automation_runner", None)
    if scheduler:
        return {
            "jobs": scheduler.get_jobs(),
            "status": "started",
            "running": runner.running_workflows() if runner else [],
            "running_details": runner.running_details() if runner else [],
        }
    return {
        "jobs": [
            {"id": "daily_scan", "name": "每日信号扫描", "next_run": None},
            {"id": "weekly_report", "name": "周度产业链报告", "next_run": None},
            {"id": "risk_monitor", "name": "风险监控", "next_run": None},
        ],
        "status": "not_started",
    }
