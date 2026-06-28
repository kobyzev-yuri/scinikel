from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
SEED_DIR = DATA_DIR / "seed"
GRAPH_PATH = DATA_DIR / "graph.json"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Научный клубок"
    debug: bool = True

    # Graph backend: "networkx" (default) | "neo4j"
    graph_backend: str = "networkx"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"

    # LLM: openai | ollama
    llm_provider: str = "openai"
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    llm_model: str = "gpt-4o-mini"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"

    # Vector search (Qdrant + e5 — как в 3dtoday)
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "scinikel_docs"
    hf_model_name: str = "intfloat/multilingual-e5-base"
    embedding_dimension: int = 768


settings = Settings()
