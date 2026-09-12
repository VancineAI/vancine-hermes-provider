"""API key must not leave the Vancine inference/catalog boundary in this plugin."""

from __future__ import annotations

import io
import json
import logging
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from catalog import (  # noqa: E402
    default_transport,
    fetch_live_model_ids,
    redact_secret,
    reset_catalog_state,
    resolve_model_ids,
)
from constants import CATALOG_URL, FALLBACK_MODEL_IDS  # noqa: E402

SECRET = "test-key"


class SecurityTests(unittest.TestCase):
    def setUp(self):
        reset_catalog_state()
        self.calls = []

    def tearDown(self):
        reset_catalog_state()

    def _ok_transport(self, payload):
        def runner(url, headers, timeout):
            self.calls.append({"url": url, "headers": dict(headers), "timeout": timeout})
            return 200, json.dumps(payload).encode()

        return runner

    def test_fetch_does_not_send_authorization_or_secret(self):
        payload = {
            "provider": "vancine",
            "schemaVersion": 1,
            "models": [
                {
                    "id": "glm-5.3-flash",
                    "name": "GLM-5.3-Flash",
                    "enabled": True,
                    "available": True,
                    "kind": "chat",
                    "api": "openai-completions",
                    "endpoint": "chat.completions",
                    "input": ["text", "image"],
                }
            ],
        }
        ids = fetch_live_model_ids(transport=self._ok_transport(payload), secret=SECRET)
        self.assertEqual(ids, ["glm-5.3-flash"])
        headers = {k.lower(): v for k, v in self.calls[0]["headers"].items()}
        self.assertNotIn("authorization", headers)
        blob = json.dumps(self.calls)
        self.assertNotIn(SECRET, blob)
        self.assertEqual(self.calls[0]["url"], CATALOG_URL)
        self.assertNotIn("models.dev", self.calls[0]["url"])

    def test_does_not_call_third_party_hosts(self):
        payload = {"provider": "vancine", "schemaVersion": 1, "models": []}
        resolve_model_ids(transport=self._ok_transport(payload), secret=SECRET)
        url = self.calls[0]["url"]
        for banned in (
            "models.dev",
            "github.com",
            "pypi.org",
            "pypi.python.org",
            "nousresearch.com",
            "openai.com",
        ):
            self.assertNotIn(banned, url)

    def test_error_and_log_output_do_not_contain_secret(self):
        def runner(url, headers, timeout):
            raise RuntimeError(f"upstream said Bearer {SECRET} was bad")

        log_stream = io.StringIO()
        handler = logging.StreamHandler(log_stream)
        logger = logging.getLogger("catalog")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        try:
            ids = resolve_model_ids(transport=runner, secret=SECRET)
        finally:
            logger.removeHandler(handler)

        self.assertEqual(ids, list(FALLBACK_MODEL_IDS))
        logged = log_stream.getvalue()
        self.assertNotIn(SECRET, logged)
        self.assertNotIn(SECRET, redact_secret(f"Bearer {SECRET}", SECRET))

    def test_default_transport_rejects_authorization_header(self):
        with self.assertRaises(Exception):
            default_transport(
                CATALOG_URL,
                {"Accept": "application/json", "Authorization": f"Bearer {SECRET}"},
                1.0,
            )


if __name__ == "__main__":
    unittest.main()
