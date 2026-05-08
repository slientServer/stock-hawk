"""图谱路由：知识图谱可视化、查询。"""

from fastapi import APIRouter, HTTPException, Query

from api.routes.graph_data import (
    chain_topology_with_fallback,
    graph_chains_with_fallback,
    search_companies_with_fallback,
)

router = APIRouter(prefix="/graph", tags=["知识图谱"])


@router.get("/chains")
async def graph_chains():
    return {"chains": await graph_chains_with_fallback()}


@router.get("/chains/{chain_name}/topology")
async def chain_topology(chain_name: str):
    topology = await chain_topology_with_fallback(chain_name)
    if not topology:
        raise HTTPException(status_code=404, detail="Chain not found")
    return topology


@router.get("/search")
async def search_company(keyword: str = Query(..., min_length=1)):
    matches = await search_companies_with_fallback(keyword)
    return {"items": matches, "total": len(matches)}
