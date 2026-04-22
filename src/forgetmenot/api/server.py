import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from forgetmenot.api.routes import health, memories
from forgetmenot.config import Settings, get_settings
from forgetmenot.core.archive import ArchiveStore
from forgetmenot.core.dedup import DedupFilter
from forgetmenot.core.engine_registry import EngineRegistry
from forgetmenot.core.memory_engine import MemoryEngine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    app.state.settings = settings

    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    logger.info("Starting forgetmenot service...")

    registry = EngineRegistry()
    registry.discover()
    app.state.engine_registry = registry
    logger.info("Registered engines: %s", registry.list_engines())

    archive = ArchiveStore(settings)
    await archive.init_tables()
    app.state.archive = archive

    app.state.memory_engine = MemoryEngine(settings)
    app.state.dedup_filter = DedupFilter(settings)

    logger.info("Forgetmenot service ready on %s:%d", settings.api_host, settings.api_port)
    yield

    await archive.close()
    logger.info("Forgetmenot service shut down")


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings:
        get_settings.cache_clear()

    app = FastAPI(
        title="Forgetmenot",
        description="Persistent AI memory service with pluggable source engines",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(memories.router, prefix="/api/v1")

    return app


def main() -> None:
    import uvicorn

    settings = get_settings()
    app = create_app(settings)
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    main()
