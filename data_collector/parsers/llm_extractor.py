from common.config import get_settings
from common.logger import get_logger

logger = get_logger(__name__)


class LLMExtractor:
    """LLM结构化信息提取器

    ⚠️ 需要用户配置LLM API Key后方可使用
    """

    def __init__(self):
        settings = get_settings()
        self._api_key = settings.llm.openai_api_key or settings.llm.deepseek_api_key
        self._base_url = settings.llm.openai_base_url
        self._enabled = bool(self._api_key)
        if not self._enabled:
            logger.warning("LLM提取器未启用: 需要配置LLM API Key")

    async def extract_financial_metrics(self, text: str) -> dict | None:
        """从财报文本中提取关键财务指标"""
        if not self._enabled:
            logger.warning("LLM API Key未配置，无法提取财务指标")
            return None

        prompt = """从以下财报文本中提取关键财务指标，以JSON格式输出:
        {
            "revenue": 营收(万元),
            "revenue_yoy": 营收同比增长率(%),
            "net_profit": 净利润(万元),
            "net_profit_yoy": 净利润同比(%),
            "gross_margin": 毛利率(%),
            "roe": 净资产收益率(%)
        }
        如果某个指标无法从文本中提取，对应值设为null。

        财报文本:
        """
        import httpx
        import json

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [
                            {"role": "system", "content": "你是一个财务数据提取专家，只输出JSON格式数据，不要任何解释。"},
                            {"role": "user", "content": prompt + text[:4000]},
                        ],
                        "temperature": 0,
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                # 解析JSON
                content = content.strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[1].rsplit("```", 1)[0]
                return json.loads(content)
        except Exception as e:
            logger.error(f"LLM提取失败: {e}")
            return None

    async def extract_signals_from_news(self, news_text: str) -> list[dict]:
        """从新闻文本中提取投资信号"""
        if not self._enabled:
            return []
        # TODO: 实现具体提取逻辑
        return []
