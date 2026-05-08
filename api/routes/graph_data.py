"""Knowledge graph read helpers."""

from __future__ import annotations

from typing import Any

from common.logger import get_logger
from knowledge_graph.neo4j_client import Neo4jClient

logger = get_logger(__name__)


async def neo4j_graph_chains() -> list[dict[str, Any]]:
    query = """
    MATCH (c:IndustryChain)
    WHERE (
      properties(c)['_source'] = 'chain_discovery'
      AND properties(c)['_discovery_source_mode'] = 'market_boards'
    )
    OR properties(c)['_source'] IN ['manual_verified', 'verified_import']
    OPTIONAL MATCH (s:Segment {chain_name: c.name})
    OPTIONAL MATCH (company:Company)-[:BELONGS_TO]->(s)
    WITH c, collect(DISTINCT s) AS segments, collect(DISTINCT company) AS companies
    RETURN
      c.name AS name,
      c.description AS description,
      coalesce(c.status, 'active') AS status,
      coalesce(properties(c)['_source'], 'neo4j') AS source,
      properties(c)['_discovery_source_mode'] AS discovery_source_mode,
      coalesce(properties(c)['_is_usable_for_discovery'], true) AS is_usable_for_discovery,
      size([item IN segments WHERE item IS NOT NULL]) AS segment_count,
      size([item IN companies WHERE item IS NOT NULL]) AS company_count
    ORDER BY name
    """
    try:
        rows = await (await Neo4jClient.get_instance()).run(query)
    except Exception as e:
        logger.warning(f"读取 Neo4j 产业链列表失败，使用 seed 兜底: {e}")
        return []

    return [
        {
            "chain_id": row.get("name"),
            "chain_name": row.get("name"),
            "name": row.get("name"),
            "description": row.get("description"),
            "status": row.get("status") or "active",
            "segment_count": row.get("segment_count") or 0,
            "company_count": row.get("company_count") or 0,
            "latest_score": None,
            "score": None,
            "score_date": None,
            "signal_count": 0,
            "data_source": row.get("source") or "neo4j",
            "discovery_source_mode": row.get("discovery_source_mode"),
            "is_usable_for_discovery": row.get("is_usable_for_discovery"),
        }
        for row in rows
        if row.get("name")
    ]


async def graph_chains_with_fallback() -> list[dict[str, Any]]:
    return await neo4j_graph_chains()


async def neo4j_chain_topology(chain_name: str) -> dict[str, Any] | None:
    query = """
    MATCH (c:IndustryChain {name: $chain_name})
    WHERE (
      properties(c)['_source'] = 'chain_discovery'
      AND properties(c)['_discovery_source_mode'] = 'market_boards'
    )
    OR properties(c)['_source'] IN ['manual_verified', 'verified_import']
    OPTIONAL MATCH (s:Segment {chain_name: c.name})
    OPTIONAL MATCH (company:Company)-[:BELONGS_TO]->(s)
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
    OPTIONAL MATCH (company2:Company)-[:BELONGS_TO]->(:Segment {chain_name: c.name})
    OPTIONAL MATCH (company2)-[:PRODUCES]->(p:Product)
    OPTIONAL MATCH (p)-[:USES]->(t:Technology)
    WITH
      c,
      raw_segments,
      collect(DISTINCT company2{.*}) AS raw_companies,
      collect(DISTINCT p{.*}) AS raw_products,
      collect(DISTINCT t{.*}) AS raw_technologies
    RETURN
      c{.*} AS chain,
      [item IN raw_segments WHERE item.uid IS NOT NULL] AS segments,
      [item IN raw_companies WHERE item.code IS NOT NULL] AS companies,
      [item IN raw_products WHERE item.name IS NOT NULL] AS products,
      [item IN raw_technologies WHERE item.name IS NOT NULL] AS technologies
    """
    try:
        rows = await (await Neo4jClient.get_instance()).run(query, chain_name=chain_name)
    except Exception as e:
        logger.warning(f"读取 Neo4j 产业链拓扑失败，使用 seed 兜底: chain={chain_name}, error={e}")
        return None
    if not rows:
        return None

    row = rows[0]
    chain = row.get("chain") or {}
    segments = row.get("segments") or []
    companies = row.get("companies") or []

    return {
        "chain": {"name": chain.get("name") or chain_name, **chain},
        "segments": segments,
        "companies": companies,
        "technologies": row.get("technologies") or [],
        "products": row.get("products") or [],
        "relationships": [],
        "data_source": chain.get("_source") or "neo4j",
    }


async def chain_topology_with_fallback(chain_name: str) -> dict[str, Any] | None:
    return await neo4j_chain_topology(chain_name)


async def neo4j_search_companies(keyword: str) -> list[dict[str, Any]]:
    query = """
    MATCH (company:Company)-[:BELONGS_TO]->(s:Segment)
    MATCH (c:IndustryChain {name: s.chain_name})
    WHERE (company.code CONTAINS $keyword OR company.name CONTAINS $keyword)
      AND (
        (
          properties(c)['_source'] = 'chain_discovery'
          AND properties(c)['_discovery_source_mode'] = 'market_boards'
        )
        OR properties(c)['_source'] IN ['manual_verified', 'verified_import']
      )
    WITH company, collect(DISTINCT s.chain_name) AS chain_names
    RETURN company{.*} AS company, chain_names
    ORDER BY company.code
    LIMIT 50
    """
    try:
        rows = await (await Neo4jClient.get_instance()).run(query, keyword=keyword)
    except Exception as e:
        logger.warning(f"读取 Neo4j 公司搜索失败，使用 seed 兜底: {e}")
        return []

    items: list[dict[str, Any]] = []
    for row in rows:
        company = row.get("company") or {}
        for chain_name in row.get("chain_names") or []:
            items.append({"chain_id": chain_name, **company})
    return items


async def search_companies_with_fallback(keyword: str) -> list[dict[str, Any]]:
    return await neo4j_search_companies(keyword)
