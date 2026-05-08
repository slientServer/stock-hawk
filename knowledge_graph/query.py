"""知识图谱查询：Cypher 查询封装、产业链追溯。"""

from knowledge_graph.neo4j_client import Neo4jClient


class KnowledgeGraphQuery:
    def __init__(self, client: Neo4jClient | None = None):
        self.client = client or Neo4jClient()

    async def chains(self):
        return await self.client.run("MATCH (c:IndustryChain) RETURN c")

    async def list_chains(self):
        try:
            rows = await self.client.run(
                """
                MATCH (c:IndustryChain)
                WHERE (
                  properties(c)['_source'] = 'chain_discovery'
                  AND properties(c)['_discovery_source_mode'] = 'market_boards'
                )
                OR properties(c)['_source'] IN ['manual_verified', 'verified_import']
                RETURN c.name AS name
                ORDER BY name
                """
            )
        except Exception:
            rows = []
        if rows:
            return [{"name": row["name"]} for row in rows if row.get("name")]
        return []

    async def query_chain_topology(self, chain_name: str):
        query = """
        MATCH (c:IndustryChain {name: $chain_name})
        OPTIONAL MATCH (s:Segment {chain_name: c.name})
        OPTIONAL MATCH (company:Company)-[r:BELONGS_TO]->(s)
            WHERE r._active IS NULL OR r._active = true
        WITH c, s, [item IN collect(DISTINCT company{.*}) WHERE item.code IS NOT NULL] AS segment_companies
        ORDER BY
          CASE s.position
            WHEN '上游' THEN 0
            WHEN '中游' THEN 1
            WHEN '下游' THEN 2
            ELSE 3
          END,
          s.name
        WITH
          c,
          collect(
            CASE
              WHEN s IS NULL THEN NULL
              ELSE s{.*, segment_id: s.uid, segment_name: s.name, companies: segment_companies}
            END
          ) AS raw_segments
        OPTIONAL MATCH (company2:Company)-[r2:BELONGS_TO]->(:Segment {chain_name: c.name})
            WHERE r2._active IS NULL OR r2._active = true
        RETURN
          c{.*} AS chain,
          [item IN raw_segments WHERE item.uid IS NOT NULL] AS segments,
          collect(DISTINCT company2{.*}) AS companies
        """
        try:
            rows = await self.client.run(query, chain_name=chain_name)
        except Exception:
            rows = []
        if rows:
            row = rows[0]
            return {
                "chain": row.get("chain") or {"name": chain_name},
                "segments": row.get("segments") or [],
                "companies": [item for item in (row.get("companies") or []) if item.get("code")],
            }
        return {"chain": {"name": chain_name}, "segments": [], "companies": []}

    @staticmethod
    def _seed_topology(chain_name: str):
        return {"chain": {"name": chain_name}, "segments": [], "companies": []}

    async def get_chain_companies(self, chain_name: str) -> list[dict[str, str]]:
        """获取某产业链中所有活跃公司及其所属 Segment"""
        query = """
        MATCH (c:Company)-[r:BELONGS_TO]->(s:Segment {chain_name: $chain_name})
        WHERE r._active IS NULL OR r._active = true
        RETURN c.code AS code, c.name AS name, s.uid AS segment_uid, s.name AS segment_name
        """
        try:
            rows = await self.client.run(query, chain_name=chain_name)
        except Exception:
            rows = []
        return rows if rows else []

    async def upstream(self, node_id: str):
        return await self.client.run(
            "MATCH (n {uid: $node_id})<-[:TRANSMITS_TO|SUPPLIES_TO*1..3]-(m) RETURN m",
            node_id=node_id,
        )

    async def downstream(self, node_id: str):
        return await self.client.run(
            "MATCH (n {uid: $node_id})-[:TRANSMITS_TO|SUPPLIES_TO*1..3]->(m) RETURN m",
            node_id=node_id,
        )
