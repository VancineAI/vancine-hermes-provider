"""plugin.yaml structure checks. No Hermes import."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from constants import PLUGIN_MANIFEST_NAME  # noqa: E402


def _parse_simple_yaml(text: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        data[key.strip()] = value.strip()
    return data


class PluginYamlTests(unittest.TestCase):
    def setUp(self):
        self.path = ROOT / "plugin.yaml"
        self.data = _parse_simple_yaml(self.path.read_text(encoding="utf-8"))

    def test_exists(self):
        self.assertTrue(self.path.is_file())

    def test_kind_is_model_provider(self):
        self.assertEqual(self.data.get("kind"), "model-provider")

    def test_manifest_name(self):
        self.assertEqual(self.data.get("name"), PLUGIN_MANIFEST_NAME)
        self.assertEqual(self.data.get("name"), "vancine-provider")

    def test_required_fields(self):
        for key in ("name", "kind", "version", "description", "author"):
            self.assertTrue(self.data.get(key), msg=f"missing {key}")

    def test_author_is_vancine(self):
        self.assertEqual(self.data.get("author"), "Vancine")


class SyntaxTests(unittest.TestCase):
    def test_python_sources_compile(self):
        import py_compile

        for name in ("__init__.py", "catalog.py", "constants.py"):
            py_compile.compile(str(ROOT / name), doraise=True)


if __name__ == "__main__":
    unittest.main()
