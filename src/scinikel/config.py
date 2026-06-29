from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
SEED_DIR = DATA_DIR / "seed"
GRAPH_PATH = DATA_DIR / "graph.json"
CONFIG_ENV = ROOT / "config.env"
DOT_ENV = ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(CONFIG_ENV), str(DOT_ENV)),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "Научный клубок"
    debug: bool = True

    graph_backend: str = "networkx"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"

    llm_provider: str = Field(default="openai", validation_alias="LLM_PROVIDER")

    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_base_url: str | None = Field(default=None, validation_alias="OPENAI_BASE_URL")
    llm_model: str = Field(default="gpt-4o-mini", validation_alias="OPENAI_MODEL")
    openai_temperature: float = Field(default=0.2, validation_alias="OPENAI_TEMPERATURE")
    openai_timeout: float = Field(default=120.0, validation_alias="OPENAI_TIMEOUT")

    ollama_base_url: str = Field(default="http://localhost:11434", validation_alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="qwen2.5:7b", validation_alias="OLLAMA_MODEL")
    ollama_timeout: float = Field(default=120.0, validation_alias="OLLAMA_TIMEOUT")

    qdrant_host: str = Field(default="localhost", validation_alias="QDRANT_HOST")
    qdrant_port: int = Field(default=6333, validation_alias="QDRANT_PORT")
    qdrant_collection: str = Field(default="scinikel_docs", validation_alias="QDRANT_COLLECTION")
    hf_model_name: str = Field(default="intfloat/multilingual-e5-base", validation_alias="HF_MODEL_NAME")
    embedding_dimension: int = Field(default=768, validation_alias="EMBEDDING_DIMENSION")

    @property
    def llm_enabled(self) -> bool:
        if self.llm_provider.lower() == "ollama":
            return True
        return bool(self.openai_api_key)

    @property
    def active_llm_label(self) -> str:
        if self.llm_provider.lower() == "ollama":
            return f"ollama/{self.ollama_model}"
        return f"openai/{self.llm_model}"


settings = Settings()
