"""Vision Analyzer — Gemini / Ollama llava для таблиц и графиков из PDF (паттерн 3dtoday)."""

from __future__ import annotations

import base64
import io
import logging
from pathlib import Path
from typing import Any

import httpx

from scinikel.config import settings

logger = logging.getLogger(__name__)

METALLURGY_ANALYSIS_PROMPT = """Проанализируй это изображение из научного/технического документа металлургии '{image_name}'.

1. Определи тип: таблица результатов | график | схема установки | микрофото | другое
2. Извлеки весь видимый текст (сохрани структуру)
3. Если это таблица — воспроизведи как markdown-таблицу с заголовками колонок
4. Для графиков: оси, единицы, ключевые точки и тренды
5. Укажи ID экспериментов (EXP-YYYY-NNN), материалы (Ni, Cu, сплав, концентрат), режимы (флотация, электролиз, T°C, pH), числовые результаты (% извлечения и т.д.)
6. Краткий вывод (1–2 предложения)

Ответ на русском, структурированно."""

METALLURGY_KEYWORDS = [
    "ni", "cu", "никел", "мед", "сплав", "концентрат", "флотац", "электролиз",
    "обжиг", "извлечен", "извлечение", "эксперимент", "металлург", "руд", "шлак",
    "xrd", "содержание", "ph", "температур",
]


GEMINI_VISION_FALLBACK_MODELS = (
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-3.1-flash-preview",
)


class VisionAnalyzer:
    """Анализ изображений через Gemini Vision API или Ollama llava."""

    def __init__(self, *, prefer_ollama: bool = False) -> None:
        self.proxy_api_key = (
            settings.gemini_api_key or settings.openai_api_key
        )
        self.gemini_base_url = settings.gemini_base_url
        self.gemini_model = settings.gemini_model
        self.use_gemini = bool(self.proxy_api_key) and not prefer_ollama

        self.ollama_base_url = settings.ollama_base_url.rstrip("/")
        self.ollama_vision_model = settings.ollama_vision_model
        self.ollama_timeout = int(settings.ollama_vision_timeout)
        self.use_ollama = prefer_ollama or not self.use_gemini

    def check_availability(self) -> dict[str, Any]:
        if not settings.vision_enabled:
            return {
                "available": False,
                "message": "Vision отключён (VISION_ENABLED=false)",
                "provider": "disabled",
            }
        if self.use_ollama:
            return self._check_ollama()
        if not self.use_gemini:
            return {
                "available": False,
                "message": "Gemini Vision не настроен — нужен GEMINI_API_KEY или OPENAI_API_KEY",
                "provider": "gemini",
            }
        return {
            "available": True,
            "message": f"Gemini {self.gemini_model} через ProxyAPI",
            "provider": "gemini",
            "model": self.gemini_model,
        }

    def analyze_image(self, image_data: bytes, image_name: str = "image") -> dict[str, Any]:
        if not settings.vision_enabled:
            return {"success": False, "error": "Vision disabled", "provider": "disabled"}

        if self.use_ollama:
            return self._analyze_with_ollama(image_data, image_name)
        if not self.use_gemini:
            return self._analyze_with_ollama(image_data, image_name)

        try:
            optimized = self._optimize_image_bytes(image_data)
            image_b64 = base64.b64encode(optimized).decode()
            result = self._analyze_with_gemini(image_b64, image_name)
            if result.get("success"):
                return result
            logger.warning("Gemini vision failed: %s — fallback llava", result.get("error"))
            return self._analyze_with_ollama(image_data, image_name)
        except Exception as exc:
            logger.error("Vision analyze error: %s", exc)
            return self._analyze_with_ollama(image_data, image_name)

    def analyze_image_from_base64(self, image_base64: str, image_name: str = "image") -> dict[str, Any]:
        try:
            return self.analyze_image(base64.b64decode(image_base64), image_name)
        except Exception as exc:
            return {"success": False, "error": str(exc), "provider": "gemini"}

    def analyze_image_from_path(self, image_path: Path) -> dict[str, Any]:
        try:
            if image_path.stat().st_size > 20 * 1024 * 1024:
                return {"success": False, "error": "Image too large (>20MB)"}
            return self.analyze_image(image_path.read_bytes(), image_path.name)
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def check_relevance_to_metallurgy(self, analysis_text: str, image_name: str = "image") -> dict[str, Any]:
        text_lower = analysis_text.lower()
        hits = sum(1 for kw in METALLURGY_KEYWORDS if kw in text_lower)
        score = min(hits / 3.0, 1.0)
        is_relevant = score >= 0.34 or "таблиц" in text_lower or "exp-" in text_lower
        return {
            "success": True,
            "is_relevant": is_relevant,
            "relevance_score": score if is_relevant else 0.1,
            "reason": "keyword heuristic",
            "image_name": image_name,
        }

    def _check_ollama(self) -> dict[str, Any]:
        try:
            response = httpx.get(f"{self.ollama_base_url}/api/tags", timeout=5)
            if response.status_code != 200:
                return {"available": False, "message": f"Ollama HTTP {response.status_code}", "provider": "ollama"}
            models = response.json().get("models", [])
            prefix = self.ollama_vision_model.split(":")[0]
            if any(m.get("name", "").startswith(prefix) for m in models):
                return {
                    "available": True,
                    "message": f"Ollama {self.ollama_vision_model}",
                    "provider": "ollama",
                    "model": self.ollama_vision_model,
                }
            return {
                "available": False,
                "message": f"Модель {self.ollama_vision_model} не найдена в Ollama",
                "provider": "ollama",
            }
        except Exception as exc:
            return {"available": False, "message": str(exc), "provider": "ollama"}

    def _optimize_image_bytes(self, image_data: bytes) -> bytes:
        from PIL import Image

        image = Image.open(io.BytesIO(image_data))
        max_size = 2048 if len(image_data) > 5 * 1024 * 1024 else 1024
        image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        if image.mode != "RGB":
            image = image.convert("RGB")
        buf = io.BytesIO()
        quality = 90 if len(image_data) > 2 * 1024 * 1024 else 85
        image.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()

    def _gemini_models_to_try(self) -> list[str]:
        seen: set[str] = set()
        models: list[str] = []
        for name in (self.gemini_model, *GEMINI_VISION_FALLBACK_MODELS):
            if name and name not in seen:
                seen.add(name)
                models.append(name)
        return models

    def _analyze_with_gemini(self, image_b64: str, image_name: str) -> dict[str, Any]:
        prompt = METALLURGY_ANALYSIS_PROMPT.format(image_name=image_name)
        last_error = "unknown"
        for model in self._gemini_models_to_try():
            payload = {
                "contents": [
                    {
                        "parts": [
                            {"text": prompt},
                            {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}},
                        ]
                    }
                ],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2000},
            }
            try:
                response = httpx.post(
                    f"{self.gemini_base_url.rstrip('/')}/v1beta/models/{model}:generateContent",
                    headers={
                        "Authorization": f"Bearer {self.proxy_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=90,
                )
                if response.status_code == 200:
                    result = response.json()
                    candidates = result.get("candidates") or []
                    if not candidates:
                        last_error = f"{model}: empty response"
                        continue
                    analysis = candidates[0]["content"]["parts"][0]["text"]
                    if model != self.gemini_model:
                        logger.info("Vision: model %s used (fallback from %s)", model, self.gemini_model)
                    return {
                        "success": True,
                        "analysis": analysis,
                        "model": model,
                        "provider": "gemini",
                    }
                body = response.text[:300]
                last_error = f"{model}: HTTP {response.status_code} {body}"
                if response.status_code == 400 and "not supported" in body.lower():
                    logger.warning("Gemini vision model %s not supported, trying next", model)
                    continue
                if response.status_code in (404, 400, 403):
                    continue
                return {
                    "success": False,
                    "error": last_error,
                    "provider": "gemini",
                }
            except Exception as exc:
                last_error = f"{model}: {exc}"
                continue
        return {"success": False, "error": last_error, "provider": "gemini"}

    def _analyze_with_ollama(self, image_data: bytes, image_name: str) -> dict[str, Any]:
        try:
            from PIL import Image

            image = Image.open(io.BytesIO(image_data))
            max_size = 768 if len(image_data) > 2 * 1024 * 1024 else 512
            image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            if image.mode != "RGB":
                image = image.convert("RGB")
            buf = io.BytesIO()
            image.save(buf, format="JPEG", quality=85)
            optimized = buf.getvalue()
        except Exception:
            optimized = image_data

        image_b64 = base64.b64encode(optimized).decode()
        prompt = METALLURGY_ANALYSIS_PROMPT.format(image_name=image_name)
        payload = {
            "model": self.ollama_vision_model,
            "prompt": prompt,
            "images": [image_b64],
            "stream": False,
            "options": {"temperature": 0.1},
        }
        try:
            response = httpx.post(
                f"{self.ollama_base_url}/api/generate",
                json=payload,
                timeout=self.ollama_timeout + 60,
            )
            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Ollama HTTP {response.status_code}",
                    "provider": "ollama",
                }
            text = response.json().get("response", "")
            if not text.strip():
                return {"success": False, "error": "Empty Ollama response", "provider": "ollama"}
            return {
                "success": True,
                "analysis": text,
                "model": self.ollama_vision_model,
                "provider": "ollama",
            }
        except Exception as exc:
            return {"success": False, "error": str(exc), "provider": "ollama"}


_vision_analyzer: VisionAnalyzer | None = None


def get_vision_analyzer(*, prefer_ollama: bool = False) -> VisionAnalyzer:
    global _vision_analyzer
    if _vision_analyzer is None or prefer_ollama:
        return VisionAnalyzer(prefer_ollama=prefer_ollama)
    return _vision_analyzer


def vision_status() -> dict[str, Any]:
    analyzer = VisionAnalyzer()
    status = analyzer.check_availability()
    try:
        from scinikel.search.image_embeddings import clip_status

        status["clip"] = clip_status()
    except Exception as exc:
        status["clip"] = {"available": False, "message": str(exc)}
    return status
