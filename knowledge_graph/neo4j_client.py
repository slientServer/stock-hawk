"""Neo4j 客户端：连接管理、事务操作。"""

from typing import Any

from neo4j import AsyncGraphDatabase

from common.config import get_settings


class Neo4jClient:
    _instance: "Neo4jClient | None" = None

    def __init__(self, uri: str | None = None, user: str | None = None, password: str | None = None):
        settings = get_settings().neo4j
        self._uri = uri or settings.uri
        self._user = user or settings.user
        self._password = password or settings.password
        self._driver = None

    @classmethod
    async def get_instance(cls) -> "Neo4jClient":
        if cls._instance is None:
            cls._instance = cls()
            await cls._instance.connect()
        return cls._instance

    async def connect(self):
        if self._driver is None:
            self._driver = AsyncGraphDatabase.driver(self._uri, auth=(self._user, self._password))
        return self

    async def close(self):
        if self._driver is not None:
            await self._driver.close()
            self._driver = None

    async def run(self, query: str, **params):
        await self.connect()
        async with self._driver.session() as session:
            result = await session.run(query, params)
            return [record.data() async for record in result]

    async def ensure_schema(self) -> None:
        """创建图谱唯一约束；幂等。"""
        constraints = [
            "CREATE CONSTRAINT industry_chain_name IF NOT EXISTS FOR (n:IndustryChain) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT segment_uid IF NOT EXISTS FOR (n:Segment) REQUIRE n.uid IS UNIQUE",
            "CREATE CONSTRAINT company_code IF NOT EXISTS FOR (n:Company) REQUIRE n.code IS UNIQUE",
            "CREATE CONSTRAINT technology_name IF NOT EXISTS FOR (n:Technology) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT product_name IF NOT EXISTS FOR (n:Product) REQUIRE n.name IS UNIQUE",
        ]
        for query in constraints:
            await self.run(query)

    async def merge_nodes_batch(self, label: str, nodes: list[dict[str, Any]], key_fields: list[str]) -> int:
        """按 key_fields MERGE 节点，并用完整属性更新。"""
        if not nodes:
            return 0
        self._validate_identifier(label)
        for field_name in key_fields:
            self._validate_identifier(field_name)

        merge_props = ", ".join(f"{field}: ${field}" for field in key_fields)
        query = f"MERGE (n:{label} {{{merge_props}}}) SET n += $props RETURN count(n) AS count"
        count = 0
        for node in nodes:
            if any(node.get(field) is None for field in key_fields):
                continue
            params = {field: node[field] for field in key_fields}
            params["props"] = {key: value for key, value in node.items() if value is not None}
            rows = await self.run(query, **params)
            count += int(rows[0]["count"]) if rows else 0
        return count

    async def merge_relationships_batch(self, relationships: list[dict[str, Any]]) -> int:
        """按关系定义 MERGE 关系。"""
        count = 0
        for rel in relationships:
            from_label = rel["from_label"]
            from_field = rel["from_key_field"]
            to_label = rel["to_label"]
            to_field = rel["to_key_field"]
            rel_type = rel["rel_type"]
            for identifier in (from_label, from_field, to_label, to_field, rel_type):
                self._validate_identifier(identifier)

            query = (
                f"MATCH (a:{from_label} {{{from_field}: $from_value}}) "
                f"MATCH (b:{to_label} {{{to_field}: $to_value}}) "
                f"MERGE (a)-[r:{rel_type}]->(b) "
                "SET r += $props "
                "RETURN count(r) AS count"
            )
            rows = await self.run(
                query,
                from_value=rel["from_key_value"],
                to_value=rel["to_key_value"],
                props=rel.get("properties") or {},
            )
            count += int(rows[0]["count"]) if rows else 0
        return count

    async def set_relationship_properties(
        self,
        from_label: str,
        from_field: str,
        from_value: str,
        to_label: str,
        to_field: str,
        to_value: str,
        rel_type: str,
        properties: dict[str, Any],
    ) -> int:
        """更新指定关系的属性（如标记 _active=false）。"""
        for identifier in (from_label, from_field, to_label, to_field, rel_type):
            self._validate_identifier(identifier)

        query = (
            f"MATCH (a:{from_label} {{{from_field}: $from_value}})"
            f"-[r:{rel_type}]->"
            f"(b:{to_label} {{{to_field}: $to_value}}) "
            "SET r += $props "
            "RETURN count(r) AS count"
        )
        rows = await self.run(query, from_value=from_value, to_value=to_value, props=properties)
        return int(rows[0]["count"]) if rows else 0

    def _validate_identifier(self, value: str) -> None:
        if not value.replace("_", "").isalnum():
            raise ValueError(f"Invalid Neo4j identifier: {value}")
