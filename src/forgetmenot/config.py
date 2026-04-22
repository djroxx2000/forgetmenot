from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FORGETMENOT_", env_file=".env", env_file_encoding="utf-8")

    # PostgreSQL
    postgres_dsn: str = "postgresql+asyncpg://memzero:memzero_dev@localhost:5432/memzero"
    postgres_pool_size: int = 5

    # Qdrant
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333

    # Neo4j
    neo4j_url: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "memzero_dev"

    # Ollama embeddings
    ollama_base_url: str = "http://localhost:11434"
    embedding_model: str = "embeddinggemma"
    embedding_dims: int = 768

    # Mem0 LLM (for fact extraction)
    mem0_llm_provider: str = "ollama"
    mem0_llm_model: str = "qwen3:8b"

    # Graph store -- disabled by default (saves ~25s on add, ~5.5s on search)
    graph_store_enabled: bool = True

    # Dedup / echo filter
    dedup_similarity_threshold: float = 0.95

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8230

    # Debug
    debug: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
