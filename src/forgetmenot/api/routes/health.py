import asyncio
import logging

import httpx
from fastapi import APIRouter, Request

from forgetmenot.api.schemas import HealthResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request) -> HealthResponse:
    services: dict[str, str] = {}
    settings = request.app.state.settings

    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"http://{settings.qdrant_host}:{settings.qdrant_port}/healthz")
            services["qdrant"] = "healthy" if resp.status_code == 200 else "unhealthy"
    except Exception as e:
        logger.warning("Qdrant health check failed: %s", e)
        services["qdrant"] = "unreachable"

    try:
        def _check_neo4j():
            from neo4j import GraphDatabase
            driver = GraphDatabase.driver(settings.neo4j_url, auth=(settings.neo4j_user, settings.neo4j_password))
            driver.verify_connectivity()
            driver.close()

        await asyncio.to_thread(_check_neo4j)
        services["neo4j"] = "healthy"
    except Exception as e:
        logger.warning("Neo4j health check failed: %s", e)
        services["neo4j"] = "unreachable"

    try:
        archive = request.app.state.archive
        async with archive.session() as sess:
            from sqlalchemy import text
            await sess.execute(text("SELECT 1"))
        services["postgres"] = "healthy"
    except Exception as e:
        logger.warning("Postgres health check failed: %s", e)
        services["postgres"] = "unreachable"

    all_healthy = all(v == "healthy" for v in services.values())
    return HealthResponse(status="ok" if all_healthy else "degraded", services=services)
