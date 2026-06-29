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
    ollama_model: str = Field(default="qwen3.6:27b", validation_alias="OLLAMA_MODEL")
    ollama_timeout: float = Field(default=120.0, validation_alias="OLLAMA_TIMEOUT")

    qdrant_host: str = Field(default="localhost", validation_alias="QDRANT_HOST")
    qdrant_port: int = Field(default=6333, validation_alias="QDRANT_PORT")
    qdrant_collection: str = Field(default="scinikel_docs", validation_alias="QDRANT_COLLECTION")
    qdrant_image_collection: str = Field(default="scinikel_images", validation_alias="QDRANT_IMAGE_COLLECTION")
    hf_model_name: str = Field(default="intfloat/multilingual-e5-base", validation_alias="HF_MODEL_NAME")
    embedding_dimension: int = Field(default=768, validation_alias="EMBEDDING_DIMENSION")
    image_embedding_dimension: int = Field(default=512, validation_alias="IMAGE_EMBEDDING_DIMENSION")

    gemini_api_key: str | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    gemini_base_url: str = Field(
        default="https://api.proxyapi.ru/google",
        validation_alias="GEMINI_BASE_URL",
    )
    gemini_model: str = Field(default="gemini-3.5-flash", validation_alias="GEMINI_MODEL")
    ollama_vision_model: str = Field(default="llava", validation_alias="OLLAMA_VISION_MODEL")
    ollama_vision_timeout: float = Field(default=300.0, validation_alias="OLLAMA_VISION_TIMEOUT")
    vision_enabled: bool = Field(default=True, validation_alias="VISION_ENABLED")
    clip_enabled: bool = Field(default=True, validation_alias="CLIP_ENABLED")
    openclip_model: str = Field(default="ViT-B-16", validation_alias="OPENCLIP_MODEL")
    openclip_pretrained: str = Field(default="openai", validation_alias="OPENCLIP_PRETRAINED")

    @property
    def llm_enabled(self) -> bool:
        from scinikel.services.llm_runtime import get_effective_config, should_use_llm

        return should_use_llm() and get_effective_config().enabled

    @property
    def active_llm_label(self) -> str:
        from scinikel.services.llm_runtime import get_effective_config

        return get_effective_config().label


settings = Settings()
