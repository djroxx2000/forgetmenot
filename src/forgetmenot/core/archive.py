import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from forgetmenot.config import Settings, get_settings
from forgetmenot.engines.base import ArchiveBase

logger = logging.getLogger(__name__)


class ArchiveStore:
    """Async PostgreSQL writer for raw archive data.

    Accepts any SQLAlchemy model that inherits from ArchiveBase --
    each engine defines its own archive schema, and this store
    writes them polymorphically.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._engine = create_async_engine(
            self._settings.postgres_dsn,
            pool_size=self._settings.postgres_pool_size,
            echo=self._settings.debug,
        )
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    async def init_tables(self) -> None:
        """Create all archive tables (idempotent)."""
        async with self._engine.begin() as conn:
            await conn.run_sync(ArchiveBase.metadata.create_all)
        logger.info("Archive tables initialized")

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        async with self._session_factory() as sess:
            try:
                yield sess
                await sess.commit()
            except Exception:
                await sess.rollback()
                raise

    async def save(self, record: ArchiveBase) -> None:
        """Persist a single archive record."""
        async with self.session() as sess:
            sess.add(record)
        logger.debug("Saved archive record: %s", type(record).__name__)

    async def save_many(self, records: list[ArchiveBase]) -> None:
        """Persist multiple archive records in a single transaction."""
        async with self.session() as sess:
            sess.add_all(records)
        logger.debug("Saved %d archive records", len(records))

    async def query_by_session(self, model: type[ArchiveBase], session_id: str) -> list:
        """Retrieve all archive records for a given session."""
        async with self._session_factory() as sess:
            from sqlalchemy import select
            stmt = select(model).where(model.session_id == session_id)  # type: ignore[attr-defined]
            result = await sess.execute(stmt)
            return list(result.scalars().all())

    async def close(self) -> None:
        await self._engine.dispose()
