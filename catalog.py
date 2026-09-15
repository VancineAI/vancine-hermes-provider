"""Public Vancine Pi catalog fetch, Chat Completions filter, and first-run fallback.

The catalog request is an unauthenticated GET to CATALOG_URL. The API key is
never attached to this request and is used only to redact accidental leaks
in error strings.
"""

from __future__ import annotations

import json
import logging
import socket
import urllib.error
import urllib.request
from typing import Any, Callable, Optional
from urllib.parse import urlparse

try:
    from .constants import (
        CATALOG_SCHEMA_VERSION,
        CATALOG_TIMEOUT_S,
        CATALOG_URL,
        CHAT_API,
        CHAT_ENDPOINTS,
        CHAT_KIND,
        EXCLUDED_ENDPOINTS,
        EXCLUDED_KINDS,
        FALLBACK_MODEL_IDS,
        PROVIDER_ID,
        RETIRED_MODEL_IDS,
        USER_AGENT,
        VANCINE_ORIGIN,
    )
except ImportError:
    from constants import (
        CATALOG_SCHEMA_VERSION,
        CATALOG_TIMEOUT_S,
        CATALOG_URL,
        CHAT_API,
        CHAT_ENDPOINTS,
        CHAT_KIND,
        EXCLUDED_ENDPOINTS,
        EXCLUDED_KINDS,
        FALLBACK_MODEL_IDS,
        PROVIDER_ID,
        RETIRED_MODEL_IDS,
        USER_AGENT,
        VANCINE_ORIGIN,
    )

logger = logging.getLogger(__name__)

Transport = Callable[[str, dict[str, str], float], tuple[int, bytes]]

# None = never fetched live; () = live empty success; non-empty = last live ids.
# One immutable tuple published by a single assignment so SWR readers never see
# a torn (succeeded, ids) pair.
_live_ids: Optional[tuple[str, ...]] = None
_transport: Optional[Transport] = None


class CatalogError(Exception):
    """Catalog fetch or parse failure."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise CatalogError("redirect", "Catalog request refused to follow a redirect")


def reset_catalog_state() -> None:
    """Test helper: clear live-success memory and any injected transport."""
    global _live_ids, _transport
    _live_ids = None
    _transport = None


def set_transport(transport: Optional[Transport]) -> None:
    """Test helper: inject a (url, headers, timeout) -> (status, body) transport."""
    global _transport
    _transport = transport


def redact_secret(text: str, secret: Optional[str]) -> str:
    """Replace an exact secret with asterisks. Never returns the original secret."""
    if not text:
        return text
    redacted = text
    if secret:
        redacted = redacted.replace(secret, "***")
        stripped = secret.strip()
        if stripped and stripped != secret:
            redacted = redacted.replace(stripped, "***")
    for needle in ("Authorization", "authorization", "Bearer ", "bearer "):
        if needle in redacted and secret:
            redacted = redacted.replace(secret, "***")
    return redacted


def _assert_catalog_url(url: str) -> None:
    try:
        parsed = urlparse(url)
    except Exception as exc:  # pragma: no cover — urlparse is permissive
        raise CatalogError("invalid_catalog", "Catalog URL is invalid") from exc
    if parsed.scheme != "https":
        raise CatalogError("redirect", "Catalog URL must use HTTPS")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if origin != VANCINE_ORIGIN:
        raise CatalogError("redirect", f"Catalog URL origin must be {VANCINE_ORIGIN}")
    if url != CATALOG_URL:
        raise CatalogError("invalid_catalog", "Catalog URL must be the Vancine Pi catalog")


def default_transport(url: str, headers: dict[str, str], timeout: float) -> tuple[int, bytes]:
    """Bounded unauthenticated GET. No Authorization header is added here."""
    _assert_catalog_url(url)
    req = urllib.request.Request(url, method="GET")
    for key, value in headers.items():
        if key.lower() == "authorization":
            raise CatalogError("invalid_catalog", "Refusing to send Authorization to the catalog")
        req.add_header(key, value)
    opener = urllib.request.build_opener(_RejectRedirects)
    try:
        with opener.open(req, timeout=timeout) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            body = resp.read()
            return int(status), body
    except CatalogError:
        raise
    except socket.timeout as exc:
        raise CatalogError("timeout", f"Catalog request timed out after {timeout}s") from exc
    except TimeoutError as exc:
        raise CatalogError("timeout", f"Catalog request timed out after {timeout}s") from exc
    except urllib.error.HTTPError as exc:
        # HTTPError is also a file-like response. Do not follow it as success.
        status = int(getattr(exc, "code", 0) or 0)
        if status:
            raise CatalogError("http", f"Catalog request failed with HTTP {status}") from exc
        raise CatalogError("network", "Catalog request failed") from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            raise CatalogError("timeout", f"Catalog request timed out after {timeout}s") from exc
        raise CatalogError("network", "Catalog request failed") from exc


def _catalog_headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }


def _is_record(value: Any) -> bool:
    return isinstance(value, dict)


def parse_chat_model_ids(payload: Any) -> list[str]:
    """Return Chat Completions model ids from a Vancine Pi catalog payload.

    Raises CatalogError on an invalid envelope. Individual unsound,
    non-chat, or retired entries are skipped. A valid envelope with zero
    compatible models is a successful empty list, not a fallback trigger.
    """
    if not _is_record(payload):
        raise CatalogError("invalid_catalog", "Catalog payload must be a JSON object")
    if isinstance(payload.get("data"), list) and not isinstance(payload.get("models"), list):
        raise CatalogError(
            "invalid_catalog",
            "Catalog is not a Vancine Pi catalog (OpenAI /v1/models shape is not used)",
        )
    provider = payload.get("provider")
    if not isinstance(provider, str) or provider.strip() != PROVIDER_ID:
        raise CatalogError("invalid_catalog", f'Catalog provider must be "{PROVIDER_ID}"')
    if payload.get("schemaVersion") != CATALOG_SCHEMA_VERSION:
        raise CatalogError(
            "invalid_catalog",
            f"Catalog schemaVersion must be {CATALOG_SCHEMA_VERSION}",
        )
    models = payload.get("models")
    if not isinstance(models, list):
        raise CatalogError("invalid_catalog", "Catalog models must be an array")

    ids: list[str] = []
    seen: set[str] = set()
    for index, entry in enumerate(models):
        model_id = _compatible_chat_id(entry, index)
        if model_id is None or model_id in seen:
            continue
        seen.add(model_id)
        ids.append(model_id)
    return ids


def _compatible_chat_id(entry: Any, index: int) -> Optional[str]:
    if not _is_record(entry):
        logger.debug("catalog models[%s] skipped: not an object", index)
        return None
    model_id = entry.get("id")
    if not isinstance(model_id, str) or not model_id.strip():
        logger.debug("catalog models[%s] skipped: missing id", index)
        return None
    model_id = model_id.strip()
    if model_id in RETIRED_MODEL_IDS:
        logger.debug("catalog %s skipped: retired model id", model_id)
        return None
    kind = entry.get("kind")
    api = entry.get("api")
    endpoint = entry.get("endpoint")
    kind_l = kind.strip().lower() if isinstance(kind, str) else ""
    if kind_l != CHAT_KIND:
        logger.debug("catalog %s skipped: kind %r is not chat", model_id, kind)
        return None
    if api != CHAT_API:
        logger.debug("catalog %s skipped: api %r is not %s", model_id, api, CHAT_API)
        return None
    if isinstance(endpoint, str) and endpoint and endpoint not in CHAT_ENDPOINTS:
        logger.debug("catalog %s skipped: endpoint %r is not chat completions", model_id, endpoint)
        return None
    if entry.get("enabled") is False:
        logger.debug("catalog %s skipped: disabled", model_id)
        return None
    if entry.get("available") is False:
        logger.debug("catalog %s skipped: unavailable", model_id)
        return None
    inputs = entry.get("input")
    if not isinstance(inputs, list) or "text" not in inputs:
        logger.debug("catalog %s skipped: does not support text input", model_id)
        return None
    if kind_l in EXCLUDED_KINDS:
        return None
    if isinstance(endpoint, str) and endpoint in EXCLUDED_ENDPOINTS:
        return None
    return model_id


def fetch_live_model_ids(
    *,
    timeout: float = CATALOG_TIMEOUT_S,
    transport: Optional[Transport] = None,
    secret: Optional[str] = None,
) -> list[str]:
    """GET the Pi catalog and return compatible Chat Completions ids.

    Never sends ``secret`` (the API key) on the wire. Raises CatalogError
    on timeout, non-2xx, redirect, network, or malformed payloads.
    """
    headers = _catalog_headers()
    if any(k.lower() == "authorization" for k in headers):
        raise CatalogError("invalid_catalog", "Refusing to send Authorization to the catalog")
    runner = transport or _transport or default_transport
    try:
        status, body = runner(CATALOG_URL, headers, timeout)
    except CatalogError as exc:
        raise CatalogError(exc.code, redact_secret(str(exc), secret)) from exc
    except (socket.timeout, TimeoutError) as exc:
        raise CatalogError("timeout", f"Catalog request timed out after {timeout}s") from exc
    except Exception as exc:
        raise CatalogError("network", redact_secret("Catalog request failed", secret)) from exc

    if status == 304:
        raise CatalogError("http", "Catalog request returned HTTP 304 without a cached body")
    if not (200 <= int(status) < 300):
        raise CatalogError("http", f"Catalog request failed with HTTP {int(status)}")

    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception as exc:
        raise CatalogError("invalid_catalog", "Catalog response is not valid JSON") from exc
    return parse_chat_model_ids(payload)


def resolve_model_ids(
    *,
    timeout: float = CATALOG_TIMEOUT_S,
    transport: Optional[Transport] = None,
    secret: Optional[str] = None,
) -> list[str]:
    """Live catalog, else last successful live list, else first-run snapshot.

    A successful live fetch — including a legitimate empty compatible list —
    records that success. Later failures must not revive FALLBACK_MODEL_IDS.
    Network I/O runs without holding plugin state; the live snapshot is then
    published as one immutable tuple assignment.
    """
    global _live_ids
    try:
        ids = fetch_live_model_ids(timeout=timeout, transport=transport, secret=secret)
    except CatalogError as exc:
        logger.debug("vancine catalog fetch failed (%s): %s", exc.code, redact_secret(str(exc), secret))
        snapshot = _live_ids
        if snapshot is None:
            return list(FALLBACK_MODEL_IDS)
        return list(snapshot)

    published = tuple(ids)
    _live_ids = published
    return list(published)
