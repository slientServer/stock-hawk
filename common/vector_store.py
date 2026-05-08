import chromadb
from chromadb.config import Settings as ChromaSettings


class VectorStore:
    def __init__(self, persist_dir: str = "./data/chroma"):
        self.client = chromadb.PersistentClient(
            path=persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )

    def get_or_create_collection(self, name: str):
        return self.client.get_or_create_collection(name=name)

    async def add_documents(
        self,
        collection_name: str,
        documents: list[str],
        metadatas: list[dict],
        ids: list[str],
    ):
        collection = self.get_or_create_collection(collection_name)
        collection.add(documents=documents, metadatas=metadatas, ids=ids)

    async def search(
        self,
        collection_name: str,
        query: str,
        n_results: int = 10,
    ) -> dict:
        collection = self.get_or_create_collection(collection_name)
        return collection.query(query_texts=[query], n_results=n_results)

    async def delete(self, collection_name: str, ids: list[str]):
        collection = self.get_or_create_collection(collection_name)
        collection.delete(ids=ids)


# 预定义的collection名称
COLLECTION_NEWS = "news"
COLLECTION_RESEARCH_REPORTS = "research_reports"
COLLECTION_ANNOUNCEMENTS = "announcements"
