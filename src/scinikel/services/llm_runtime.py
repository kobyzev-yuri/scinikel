"""Runtime-переключение LLM (ProxyAPI / Ollama) без правки config.env."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from scinikel.config import CONFIG_ENV, DATA_DIR, settings

logger = logging.getLogger(__name__)

RUNTIME_PATH = DATA_DIR / "llm_runtime.json"

PROVIDER_PROXYAPI = "proxyapi"
PROVIDER_OLLAMA = "ollama"

ANSWER_MODE_LLM = "llm"
ANSWER_MODE_RULE = "rule"

SEARCH_MODE_KEYWORD = "keyword"
SEARCH_MODE_VECTOR = "vector"
SEARCH_MODE_HYBRID = "hybrid"

WORK_MODE_LITE = "lite"
WORK_MODE_LOCAL = "local"
WORK_MODE_FULL = "full"
WORK_MODE_CUSTOM = "custom"

WORK_MODE_PRESETS: dict[str, dict[str, Any]] = {
    WORK_MODE_LITE: {
        "name": "Экономный",
        "hint": "Минимум ресурсов: ответы из графа, без LLM, эмбеддингов и Qdrant",
        "answer_mode": ANSWER_MODE_RULE,
        "search_mode": SEARCH_MODE_KEYWORD,
        "provider": None,
        "resources": {
            "ram": "низкое (~200 MB)",
            "network": False,
            "docker": False,
            "llm": False,
            "vector": False,
        },
    },
    WORK_MODE_LOCAL: {
        "name": "Локальный AI",
        "hint": "Ollama qwen2.5:7b без облака; поиск по ключевым словам",
        "answer_mode": ANSWER_MODE_LLM,
        "search_mode": SEARCH_MODE_KEYWORD,
        "provider": PROVIDER_OLLAMA,
        "default_ollama_model": "qwen2.5:7b",
        "resources": {
            "ram": "среднее (зависит от модели Ollama)",
            "network": False,
            "docker": False,
            "llm": True,
            "vector": False,
        },
    },
    WORK_MODE_FULL: {
        "name": "Полный",
        "hint": "GPT + гибрид BM25+e5 (RRF) + Gemini Vision + CLIP — рекомендуется",
        "answer_mode": ANSWER_MODE_LLM,
        "search_mode": SEARCH_MODE_HYBRID,
        "provider": PROVIDER_PROXYAPI,
        "resources": {
            "ram": "высокое (~1+ GB)",
            "network": True,
            "docker": True,
            "llm": True,
            "vector": True,
        },
    },
}


@dataclass
class EffectiveLLMConfig:
    provider: str
    openai_api_key: str | None
    openai_base_url: str | None
    openai_model: str
    ollama_base_url: str
    ollama_model: str
    openai_temperature: float
    openai_timeout: float
    ollama_timeout: float

    @property
    def enabled(self) -> bool:
        if self.provider == PROVIDER_OLLAMA:
            return True
        return bool(self.openai_api_key)

    @property
    def label(self) -> str:
        if get_answer_mode() == ANSWER_MODE_RULE:
            return "rule-based (граф)"
        if self.provider == PROVIDER_OLLAMA:
            return f"ollama/{self.ollama_model}"
        return f"proxyapi/{self.openai_model}"


def _load_runtime_raw() -> dict[str, Any]:
    if not RUNTIME_PATH.exists():
        return {}
    try:
        return json.loads(RUNTIME_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("llm_runtime.json unreadable: %s", exc)
        return {}


def _save_runtime_raw(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _env_provider() -> str:
    raw = settings.llm_provider.lower()
    if raw == "ollama":
        return PROVIDER_OLLAMA
    return PROVIDER_PROXYAPI


def get_effective_config() -> EffectiveLLMConfig:
    runtime = _load_runtime_raw()
    provider = runtime.get("provider") or _env_provider()
    if provider not in (PROVIDER_PROXYAPI, PROVIDER_OLLAMA):
        provider = _env_provider()

    openai_model = runtime.get("openai_model") or settings.llm_model
    ollama_model = runtime.get("ollama_model") or settings.ollama_model

    return EffectiveLLMConfig(
        provider=provider,
        openai_api_key=settings.openai_api_key,
        openai_base_url=settings.openai_base_url,
        openai_model=openai_model,
        ollama_base_url=settings.ollama_base_url,
        ollama_model=ollama_model,
        openai_temperature=settings.openai_temperature,
        openai_timeout=settings.openai_timeout,
        ollama_timeout=settings.ollama_timeout,
    )


def get_answer_mode() -> str:
    mode = _load_runtime_raw().get("answer_mode", ANSWER_MODE_LLM)
    return mode if mode in (ANSWER_MODE_LLM, ANSWER_MODE_RULE) else ANSWER_MODE_LLM


def get_search_mode() -> str:
    mode = _load_runtime_raw().get("search_mode", SEARCH_MODE_KEYWORD)
    valid = (SEARCH_MODE_KEYWORD, SEARCH_MODE_VECTOR, SEARCH_MODE_HYBRID)
    return mode if mode in valid else SEARCH_MODE_KEYWORD


def vector_search_enabled() -> bool:
    """Qdrant+e5 активен (vector или hybrid)."""
    return get_search_mode() in (SEARCH_MODE_VECTOR, SEARCH_MODE_HYBRID)


def hybrid_search_enabled() -> bool:
    return get_search_mode() == SEARCH_MODE_HYBRID


def should_use_llm() -> bool:
    return get_answer_mode() != ANSWER_MODE_RULE


def detect_work_mode() -> str:
    return detect_work_mode_from_data(_load_runtime_raw())


def _work_mode_payload() -> list[dict[str, Any]]:
    rows = []
    for mode_id, preset in WORK_MODE_PRESETS.items():
        rows.append(
            {
                "id": mode_id,
                "name": preset["name"],
                "hint": preset["hint"],
                "resources": preset["resources"],
            }
        )
    rows.append(
        {
            "id": WORK_MODE_CUSTOM,
            "name": "Своя настройка",
            "hint": "Комбинация параметров вручную",
            "resources": {},
        }
    )
    return rows


def runtime_payload() -> dict[str, Any]:
    cfg = get_effective_config()
    runtime = _load_runtime_raw()
    mode = get_answer_mode()
    search = get_search_mode()
    work_mode = detect_work_mode()
    llm_on = should_use_llm() and cfg.enabled
    preset = WORK_MODE_PRESETS.get(work_mode, {})
    resources = preset.get("resources", {})
    return {
        "provider": cfg.provider,
        "answer_mode": mode,
        "search_mode": search,
        "work_mode": work_mode,
        "vector_search_enabled": vector_search_enabled(),
        "hybrid_search_enabled": hybrid_search_enabled(),
        "openai_model": cfg.openai_model,
        "ollama_model": cfg.ollama_model,
        "openai_base_url": cfg.openai_base_url or "https://api.proxyapi.ru/openai/v1",
        "ollama_base_url": cfg.ollama_base_url,
        "llm_enabled": llm_on,
        "active_label": cfg.label,
        "has_api_key": bool(cfg.openai_api_key),
        "config_env_path": str(CONFIG_ENV),
        "runtime_override": bool(
            runtime.get("provider")
            or runtime.get("answer_mode")
            or runtime.get("search_mode")
            or runtime.get("work_mode")
        ),
        "work_modes": _work_mode_payload(),
        "search_modes": [
            {
                "id": SEARCH_MODE_KEYWORD,
                "name": "Ключевые слова",
                "hint": "Без эмбеддингов и Qdrant — минимум RAM",
            },
            {
                "id": SEARCH_MODE_VECTOR,
                "name": "Семантический (Qdrant + e5)",
                "hint": "Только dense; перефразы без точных терминов",
            },
            {
                "id": SEARCH_MODE_HYBRID,
                "name": "Гибрид (BM25 + e5, RRF)",
                "hint": "Рекомендуется: термины + семантика",
            },
        ],
        "resources": resources,
        "answer_modes": [
            {
                "id": ANSWER_MODE_LLM,
                "name": "LLM формулирует ответ",
                "hint": "ProxyAPI или Ollama переформулируют данные графа",
            },
            {
                "id": ANSWER_MODE_RULE,
                "name": "Только граф (без сети)",
                "hint": "Rule-based: ответ и таблицы из графа, без LLM",
            },
        ],
        "providers": [
            {
                "id": PROVIDER_PROXYAPI,
                "name": "ProxyAPI (облако)",
                "hint": "OpenAI-совместимый API через proxyapi.ru",
            },
            {
                "id": PROVIDER_OLLAMA,
                "name": "Ollama (локально)",
                "hint": "Модели на этой машине, без отправки данных в облако",
            },
        ],
    }


def apply_work_mode(work_mode: str) -> dict[str, Any]:
    if work_mode not in WORK_MODE_PRESETS:
        raise ValueError(f"Unknown work_mode: {work_mode}")
    preset = WORK_MODE_PRESETS[work_mode]
    return set_runtime_config(
        provider=preset["provider"],
        answer_mode=preset["answer_mode"],
        search_mode=preset["search_mode"],
        work_mode=work_mode,
    )


def set_runtime_config(
    *,
    provider: str | None = None,
    openai_model: str | None = None,
    ollama_model: str | None = None,
    answer_mode: str | None = None,
    search_mode: str | None = None,
    work_mode: str | None = None,
) -> dict[str, Any]:
    data = _load_runtime_raw()
    applied_preset = False

    if work_mode and work_mode in WORK_MODE_PRESETS:
        preset = WORK_MODE_PRESETS[work_mode]
        data["work_mode"] = work_mode
        data["answer_mode"] = preset["answer_mode"]
        data["search_mode"] = preset["search_mode"]
        if preset.get("provider"):
            data["provider"] = preset["provider"]
        default_ollama = preset.get("default_ollama_model")
        if default_ollama and work_mode == WORK_MODE_LOCAL:
            data.setdefault("ollama_model", default_ollama)
        applied_preset = True
    elif work_mode == WORK_MODE_CUSTOM:
        data["work_mode"] = WORK_MODE_CUSTOM

    if provider:
        provider = provider.lower().strip()
        if provider not in (PROVIDER_PROXYAPI, PROVIDER_OLLAMA):
            raise ValueError(f"Unknown provider: {provider}")
        data["provider"] = provider

    if openai_model:
        data["openai_model"] = openai_model.strip()
    if ollama_model:
        data["ollama_model"] = ollama_model.strip()

    if answer_mode:
        if answer_mode not in (ANSWER_MODE_LLM, ANSWER_MODE_RULE):
            raise ValueError(f"Unknown answer_mode: {answer_mode}")
        data["answer_mode"] = answer_mode

    if search_mode:
        if search_mode not in (SEARCH_MODE_KEYWORD, SEARCH_MODE_VECTOR, SEARCH_MODE_HYBRID):
            raise ValueError(f"Unknown search_mode: {search_mode}")
        data["search_mode"] = search_mode

    if not applied_preset:
        data["work_mode"] = detect_work_mode_from_data(data)

    _save_runtime_raw(data)

    from scinikel.services.llm import reset_llm_client

    reset_llm_client()
    return runtime_payload()


def detect_work_mode_from_data(data: dict[str, Any]) -> str:
    answer = data.get("answer_mode", ANSWER_MODE_LLM)
    search = data.get("search_mode", SEARCH_MODE_KEYWORD)
    provider = data.get("provider") or _env_provider()
    for mode_id, preset in WORK_MODE_PRESETS.items():
        if answer != preset["answer_mode"]:
            continue
        if search != preset["search_mode"]:
            continue
        if preset["provider"] and provider != preset["provider"]:
            continue
        return mode_id
    return WORK_MODE_CUSTOM


def set_runtime_provider(
    provider: str,
    *,
    openai_model: str | None = None,
    ollama_model: str | None = None,
    answer_mode: str | None = None,
    search_mode: str | None = None,
    work_mode: str | None = None,
) -> dict[str, Any]:
    return set_runtime_config(
        provider=provider,
        openai_model=openai_model,
        ollama_model=ollama_model,
        answer_mode=answer_mode,
        search_mode=search_mode,
        work_mode=work_mode,
    )


def set_answer_mode(answer_mode: str) -> dict[str, Any]:
    if answer_mode not in (ANSWER_MODE_LLM, ANSWER_MODE_RULE):
        raise ValueError(f"Unknown answer_mode: {answer_mode}")
    return set_runtime_config(answer_mode=answer_mode)


def list_ollama_models() -> list[dict[str, str]]:
    cfg = get_effective_config()
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{cfg.ollama_base_url.rstrip('/')}/api/tags")
            resp.raise_for_status()
            models = resp.json().get("models", [])
    except Exception as exc:
        logger.info("Ollama tags failed: %s", exc)
        return []

    rows: list[dict[str, str]] = []
    for item in models:
        name = item.get("name") or item.get("model")
        if not name:
            continue
        size = item.get("size")
        rows.append(
            {
                "name": name,
                "size": _human_size(size) if size else "",
                "modified": item.get("modified_at", "")[:10],
            }
        )
    return rows


def probe_ollama() -> dict[str, Any]:
    cfg = get_effective_config()
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{cfg.ollama_base_url.rstrip('/')}/api/tags")
            resp.raise_for_status()
            models = [m.get("name") for m in resp.json().get("models", []) if m.get("name")]
        return {"ok": True, "models": models}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def probe_proxyapi() -> dict[str, Any]:
    cfg = get_effective_config()
    if not cfg.openai_api_key:
        return {"ok": False, "error": "OPENAI_API_KEY не задан в config.env"}
    base = (cfg.openai_base_url or "https://api.proxyapi.ru/openai/v1").rstrip("/")
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(
                f"{base}/models",
                headers={"Authorization": f"Bearer {cfg.openai_api_key}"},
            )
            if resp.status_code == 404:
                return {"ok": True, "note": "Ключ принят (models endpoint недоступен)"}
            resp.raise_for_status()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _human_size(num: int | float) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num)
    for unit in units:
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"
