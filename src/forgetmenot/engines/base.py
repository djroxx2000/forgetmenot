from abc import ABC, abstractmethod

from sqlalchemy.orm import DeclarativeBase

from forgetmenot.models.artifact import MemoryArtifact


class ArchiveBase(DeclarativeBase):
    """Shared declarative base for all archive tables."""

    pass


class SourceEngine(ABC):
    """Base class for all source engines.

    Each engine knows how to ingest and normalize data from a specific source type
    (conversations, codebases, web pages) into MemoryArtifact objects.
    """

    engine_type: str

    @abstractmethod
    def normalize(self, raw_input: dict) -> list[MemoryArtifact]:
        """Transform raw input into normalized artifacts."""

    @abstractmethod
    def extract_for_mem0(self, artifacts: list[MemoryArtifact]) -> list[dict]:
        """Prepare artifacts for Mem0's extraction pipeline.

        Returns a list of dicts suitable for mem0's `add()` method, each with
        at minimum a "messages" key containing conversation-formatted data.
        """

    @abstractmethod
    def archive_schema(self) -> type[ArchiveBase]:
        """Return the SQLAlchemy model for raw archival of this source type."""
