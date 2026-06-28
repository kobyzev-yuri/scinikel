from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
SEED_DIR = DATA_DIR / "seed"
GRAPH_PATH = DATA_DIR / "graph.json"
CHROMA_PATH = DATA_DIR / "vectors"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Научный клубок"
    debug: bool = True

    # Graph backend: "networkx" (default) | "neo4j"
    graph_backend: str = "networkx"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"

    # LLM (optional — без ключа работает rule-based fallback)
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    llm_model: str = "gpt-4o-mini"

    chroma_collection: str = "scinikel_docs"
    embedding_model: str = "default"


settings = Settings()
