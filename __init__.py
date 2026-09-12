"""Vancine model provider plugin for Hermes Agent.

Drop this directory under ``$HERMES_HOME/plugins/model-providers/vancine/``
or ``$HERMES_HOME/plugins/vancine-provider/`` (with ``kind: model-provider``).
Hermes discovers it through ``register_provider``; no Hermes core edits.
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

from providers import register_provider
from providers.base import ProviderProfile

try:
    from .catalog import redact_secret, resolve_model_ids
    from .constants import (
        API_KEY_ENV,
        BASE_URL,
        BASE_URL_ENV,
        CATALOG_TIMEOUT_S,
        DEFAULT_AUX_MODEL,
        DESCRIPTION,
        DISPLAY_NAME,
        ENV_VARS,
        PROVIDER_ALIASES,
        PROVIDER_ID,
        SIGNUP_URL,
    )
except ImportError:  # loaded as a loose module, not a package
    from pathlib import Path

    _plugin_dir = str(Path(__file__).resolve().parent)
    if _plugin_dir not in sys.path:
        sys.path.insert(0, _plugin_dir)
    from catalog import redact_secret, resolve_model_ids
    from constants import (
        API_KEY_ENV,
        BASE_URL,
        BASE_URL_ENV,
        CATALOG_TIMEOUT_S,
        DEFAULT_AUX_MODEL,
        DESCRIPTION,
        DISPLAY_NAME,
        ENV_VARS,
        PROVIDER_ALIASES,
        PROVIDER_ID,
        SIGNUP_URL,
    )

logger = logging.getLogger(__name__)


class VancineProviderProfile(ProviderProfile):
    """OpenAI-compatible Chat Completions provider backed by Vancine.

    ``fetch_models`` reads the public Pi catalog at vancine.com and never
    sends the API key there. ``fallback_models`` stays empty so Hermes does
    not merge a stale snapshot back into a successful live catalog.
    """

    def fetch_models(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = CATALOG_TIMEOUT_S,
    ) -> list[str] | None:
        # ``base_url`` is the inference endpoint. The Chat Completions catalog
        # is a separate public Vancine URL and is not ``{base_url}/models``,
        # which would mix image/video/audio models from the gateway.
        del base_url
        try:
            return resolve_model_ids(timeout=timeout, secret=api_key)
        except Exception as exc:
            logger.debug("fetch_models(%s): %s", self.name, redact_secret(str(exc), api_key))
            return None


vancine = VancineProviderProfile(
    name=PROVIDER_ID,
    aliases=PROVIDER_ALIASES,
    display_name=DISPLAY_NAME,
    description=DESCRIPTION,
    signup_url=SIGNUP_URL,
    env_vars=ENV_VARS,
    base_url=BASE_URL,
    auth_type="api_key",
    api_mode="chat_completions",
    default_aux_model=DEFAULT_AUX_MODEL,
    fallback_models=(),
)

register_provider(vancine)


def _ensure_optional_env_vars() -> None:
    """If Hermes already imported config before this user plugin loaded, the
    one-shot OPTIONAL_ENV_VARS injection missed us. Re-add our env vars.
    """
    module = sys.modules.get("hermes_cli.config")
    if module is None:
        return
    optional = getattr(module, "OPTIONAL_ENV_VARS", None)
    if not isinstance(optional, dict):
        return
    if API_KEY_ENV not in optional:
        optional[API_KEY_ENV] = {
            "description": f"{DISPLAY_NAME} API key",
            "prompt": f"{DISPLAY_NAME} API key",
            "url": SIGNUP_URL,
            "password": True,
            "category": "provider",
            "advanced": True,
        }
    if BASE_URL_ENV not in optional:
        optional[BASE_URL_ENV] = {
            "description": f"{DISPLAY_NAME} base URL override",
            "prompt": f"{DISPLAY_NAME} base URL (leave empty for default)",
            "url": SIGNUP_URL,
            "password": False,
            "category": "provider",
            "advanced": True,
        }


_ensure_optional_env_vars()
