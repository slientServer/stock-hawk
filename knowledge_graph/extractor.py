"""知识图谱实体抽取：从文本中提取实体和关系。"""

from agents.llm_client import LLMClient


def is_llm_available() -> bool:
    return LLMClient().is_available()


class KnowledgeExtractor:
    def __init__(self, llm_client: LLMClient | None = None):
        self.llm = llm_client or LLMClient()

    async def extract(self, text: str) -> dict:
        if not self.llm.is_available():
            return {
                "status": "blocked",
                "entities": [],
                "relationships": [],
                "blocking_issues": ["LLM is not configured; extraction cannot run without source-backed parsing."],
                "confidence": "low",
            }
        return await self.llm.chat_json(
            [
                {
                    "role": "system",
                    "content": "Extract industry-chain entities and relationships from the user text.",
                },
                {"role": "user", "content": text},
            ]
        )
