"""Stable Vancine identifiers, URLs, and the first-run catalog snapshot."""

from __future__ import annotations

PROVIDER_ID = "vancine"
PROVIDER_ALIASES = ("vancine-api",)
DISPLAY_NAME = "Vancine"
PLUGIN_MANIFEST_NAME = "vancine-provider"
DESCRIPTION = "Vancine — OpenAI-compatible Chat Completions API"

BASE_URL = "https://vancine.com/v1"
VANCINE_ORIGIN = "https://vancine.com"
CATALOG_URL = "https://vancine.com/api/pi/catalog"

API_KEY_ENV = "VANCINE_API_KEY"
BASE_URL_ENV = "VANCINE_BASE_URL"
ENV_VARS = (API_KEY_ENV, BASE_URL_ENV)

REGISTER_URL = "https://vancine.com"
SIGNUP_URL = "https://vancine.com/console"
DOCS_URL = "https://vancine.com/docs"
MODELS_DOCS_URL = "https://vancine.com/docs/models"

CATALOG_SCHEMA_VERSION = 1
CATALOG_TIMEOUT_S = 8.0
USER_AGENT = "vancine-hermes-provider/0.1.0"

# Low-cost Chat Completions aux model from the live Pi catalog
# GET https://vancine.com/api/pi/catalog at 2026-09-12T04:26:14Z
# (generatedAt 2026-09-11T17:26:07Z): kind=chat, api=openai-completions,
# endpoint=chat.completions, enabled, available, input includes text,
# cost.input=0.12, cost.output≈0.40. Also present in FALLBACK_MODEL_IDS so
# first-run offline aux routing still names a real snapshot model.
DEFAULT_AUX_MODEL = "glm-5.3-flash"

# First-run offline snapshot only. Same live GET as DEFAULT_AUX_MODEL.
# All four were Chat Completions models suitable for agent tool use.
# This is not a live catalog. A successful live fetch replaces it entirely
# and must not resurrect a snapshot id the server no longer publishes.
FALLBACK_MODEL_IDS = (
    "hy4-preview",
    "deepseek-flash",
    "glm-5.3-flash",
    "qwen3.8-flash",
)

CHAT_KIND = "chat"
CHAT_API = "openai-completions"
CHAT_ENDPOINTS = frozenset({"chat.completions", "openai-completions"})
EXCLUDED_KINDS = frozenset(
    {
        "image",
        "image-generation",
        "video",
        "audio",
        "tts",
        "3d",
        "embedding",
        "embeddings",
        "rerank",
        "task",
        "async",
    }
)
EXCLUDED_ENDPOINTS = frozenset(
    {
        "image-generation",
        "images.generations",
        "audio.speech",
        "audio.transcriptions",
        "embeddings",
        "rerank",
        "video.generations",
        "videos.generations",
    }
)
