"""Catalog parse, filter, fallback, and fetch-failure tests. No Hermes import."""

from __future__ import annotations

import json
import socket
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from catalog import (  # noqa: E402
    CatalogError,
    fetch_live_model_ids,
    parse_chat_model_ids,
    redact_secret,
    reset_catalog_state,
    resolve_model_ids,
)
from constants import (  # noqa: E402
    CATALOG_URL,
    FALLBACK_MODEL_IDS,
    RETIRED_MODEL_IDS,
    VANCINE_ORIGIN,
)


def chat_model(model_id: str, **overrides):
    model = {
        "id": model_id,
        "name": model_id,
        "enabled": True,
        "available": True,
        "kind": "chat",
        "api": "openai-completions",
        "endpoint": "chat.completions",
        "input": ["text"],
        "reasoning": True,
        "contextWindow": 128000,
        "maxTokens": 8192,
        "cost": {"input": 0.1, "output": 0.2, "cacheRead": 0.0, "cacheWrite": 0.0},
    }
    model.update(overrides)
    return model


def envelope(models):
    return {
        "provider": "vancine",
        "schemaVersion": 1,
        "generatedAt": "2026-09-11T17:26:07Z",
        "models": models,
    }


class ParseTests(unittest.TestCase):
    def test_keeps_chat_completions_ids_in_order(self):
        payload = envelope(
            [
                chat_model("glm-5.3-flash", input=["text", "image"]),
                chat_model("hy4-preview"),
            ]
        )
        self.assertEqual(parse_chat_model_ids(payload), ["glm-5.3-flash", "hy4-preview"])

    def test_empty_models_is_success(self):
        self.assertEqual(parse_chat_model_ids(envelope([])), [])

    def test_filters_image_video_audio_and_other_non_chat(self):
        payload = envelope(
            [
                chat_model("keep-chat"),
                chat_model("seedream", kind="image"),
                chat_model("seedance", kind="video"),
                chat_model("tts-1", kind="audio"),
                chat_model("embed-1", kind="embedding"),
                chat_model("rerank-1", kind="rerank"),
                chat_model("mesh-1", kind="3d"),
                chat_model("wrong-api", api="images"),
                chat_model("wrong-ep", endpoint="images.generations"),
                chat_model("no-text", input=["image"]),
                chat_model("disabled", enabled=False),
                chat_model("down", available=False),
            ]
        )
        self.assertEqual(parse_chat_model_ids(payload), ["keep-chat"])

    def test_skips_duplicate_ids(self):
        payload = envelope([chat_model("same"), chat_model("same"), chat_model("other")])
        self.assertEqual(parse_chat_model_ids(payload), ["same", "other"])

    def test_parse_filters_retired_ids_and_keeps_the_replacement(self):
        payload = envelope(
            [chat_model("deepseek-flash"), chat_model("deepseek-v4.1-flash")]
        )
        self.assertEqual(parse_chat_model_ids(payload), ["deepseek-v4.1-flash"])

    def test_parse_retired_only_is_a_successful_empty_catalog(self):
        self.assertEqual(parse_chat_model_ids(envelope([chat_model("deepseek-flash")])), [])

    def test_retired_filter_is_exact_not_prefix_or_regex(self):
        payload = envelope(
            [
                chat_model("deepseek-flash-preview"),
                chat_model("deepseek-flash-v2"),
                chat_model("my-deepseek-flash"),
                chat_model("deepseek-flashx"),
                chat_model("deepseek-v4.1-flash"),
            ]
        )
        self.assertEqual(
            parse_chat_model_ids(payload),
            [
                "deepseek-flash-preview",
                "deepseek-flash-v2",
                "my-deepseek-flash",
                "deepseek-flashx",
                "deepseek-v4.1-flash",
            ],
        )

    def test_rejects_openai_models_shape(self):
        with self.assertRaises(CatalogError) as ctx:
            parse_chat_model_ids({"object": "list", "data": [{"id": "glm-5.3-flash"}]})
        self.assertEqual(ctx.exception.code, "invalid_catalog")

    def test_rejects_wrong_provider_and_schema(self):
        with self.assertRaises(CatalogError):
            parse_chat_model_ids({**envelope([]), "provider": "other"})
        with self.assertRaises(CatalogError):
            parse_chat_model_ids({**envelope([]), "schemaVersion": 2})
        with self.assertRaises(CatalogError):
            parse_chat_model_ids(["not", "an", "object"])


class FallbackMigrationTests(unittest.TestCase):
    """The retired deepseek-flash migration invariants."""

    def test_first_run_fallback_contains_the_current_replacement(self):
        self.assertIn("deepseek-v4.1-flash", FALLBACK_MODEL_IDS)

    def test_first_run_fallback_contains_no_retired_id(self):
        for retired_id in RETIRED_MODEL_IDS:
            self.assertNotIn(retired_id, FALLBACK_MODEL_IDS)

    def test_retired_set_contains_the_exact_delisted_id(self):
        self.assertIn("deepseek-flash", RETIRED_MODEL_IDS)


class FetchAndFallbackTests(unittest.TestCase):
    def setUp(self):
        reset_catalog_state()
        self.calls = []

    def tearDown(self):
        reset_catalog_state()

    def _transport(self, status, payload, error=None):
        def runner(url, headers, timeout):
            self.calls.append({"url": url, "headers": dict(headers), "timeout": timeout})
            if error is not None:
                raise error
            body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            return status, body

        return runner

    def test_live_success_returns_filtered_ids(self):
        payload = envelope([chat_model("glm-5.3-flash"), chat_model("pic", kind="image")])
        ids = resolve_model_ids(transport=self._transport(200, payload))
        self.assertEqual(ids, ["glm-5.3-flash"])
        self.assertEqual(self.calls[0]["url"], CATALOG_URL)
        self.assertTrue(self.calls[0]["url"].startswith(VANCINE_ORIGIN))

    def test_empty_live_catalog_is_not_fallback(self):
        ids = resolve_model_ids(transport=self._transport(200, envelope([])))
        self.assertEqual(ids, [])
        self.assertNotEqual(ids, list(FALLBACK_MODEL_IDS))

    def test_timeout_uses_first_run_fallback(self):
        ids = resolve_model_ids(
            transport=self._transport(0, b"", error=socket.timeout("timed out"))
        )
        self.assertEqual(ids, list(FALLBACK_MODEL_IDS))

    def test_timeout_error_uses_first_run_fallback(self):
        ids = resolve_model_ids(
            transport=self._transport(0, b"", error=TimeoutError("timed out"))
        )
        self.assertEqual(ids, list(FALLBACK_MODEL_IDS))

    def test_http_500_uses_first_run_fallback(self):
        ids = resolve_model_ids(transport=self._transport(500, b"oops"))
        self.assertEqual(ids, list(FALLBACK_MODEL_IDS))

    def test_http_401_uses_first_run_fallback(self):
        ids = resolve_model_ids(transport=self._transport(401, b'{"error":"no"}'))
        self.assertEqual(ids, list(FALLBACK_MODEL_IDS))

    def test_malformed_json_uses_first_run_fallback(self):
        ids = resolve_model_ids(transport=self._transport(200, b"{not-json"))
        self.assertEqual(ids, list(FALLBACK_MODEL_IDS))

    def test_malformed_envelope_uses_first_run_fallback(self):
        ids = resolve_model_ids(transport=self._transport(200, {"data": [{"id": "x"}]}))
        self.assertEqual(ids, list(FALLBACK_MODEL_IDS))

    def test_success_then_failure_does_not_resurrect_fallback(self):
        live = envelope([chat_model("only-live-model")])
        self.assertEqual(resolve_model_ids(transport=self._transport(200, live)), ["only-live-model"])
        later = resolve_model_ids(transport=self._transport(503, b"down"))
        self.assertEqual(later, ["only-live-model"])
        self.assertNotIn("hy4-preview", later)
        for snapshot_id in FALLBACK_MODEL_IDS:
            if snapshot_id != "only-live-model":
                self.assertNotIn(snapshot_id, later)

    def test_empty_success_then_failure_does_not_resurrect_fallback(self):
        self.assertEqual(resolve_model_ids(transport=self._transport(200, envelope([]))), [])
        later = resolve_model_ids(transport=self._transport(500, b"down"))
        self.assertEqual(later, [])
        self.assertNotEqual(later, list(FALLBACK_MODEL_IDS))

    def test_retired_only_success_then_failure_keeps_empty_list(self):
        """A live catalog that only still publishes a retired id is a
        successful empty catalog; a later failure must not revive fallback."""
        self.assertEqual(
            resolve_model_ids(
                transport=self._transport(200, envelope([chat_model("deepseek-flash")]))
            ),
            [],
        )
        later = resolve_model_ids(transport=self._transport(503, b"down"))
        self.assertEqual(later, [])
        self.assertNotEqual(later, list(FALLBACK_MODEL_IDS))
        self.assertNotIn("deepseek-flash", later)

    def test_first_failure_fallback_has_current_ids_only(self):
        ids = resolve_model_ids(transport=self._transport(0, b"", error=socket.timeout("x")))
        self.assertIn("deepseek-v4.1-flash", ids)
        self.assertNotIn("deepseek-flash", ids)
        self.assertEqual(ids, list(FALLBACK_MODEL_IDS))

    def test_fetch_live_raises_on_non_2xx(self):
        with self.assertRaises(CatalogError) as ctx:
            fetch_live_model_ids(transport=self._transport(404, b"missing"))
        self.assertEqual(ctx.exception.code, "http")

    def test_catalog_url_is_vancine_pi_catalog_not_models_dev(self):
        resolve_model_ids(transport=self._transport(200, envelope([chat_model("x")])))
        url = self.calls[0]["url"]
        self.assertEqual(url, "https://vancine.com/api/pi/catalog")
        self.assertNotIn("models.dev", url)
        self.assertNotIn("github.com", url)
        self.assertNotIn("pypi.org", url)


class RedactTests(unittest.TestCase):
    def test_redacts_exact_secret(self):
        secret = "test-key"
        text = f"failed Authorization: Bearer {secret} extra"
        out = redact_secret(text, secret)
        self.assertNotIn(secret, out)
        self.assertIn("***", out)


if __name__ == "__main__":
    unittest.main()
