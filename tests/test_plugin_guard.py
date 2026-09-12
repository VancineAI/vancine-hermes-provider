"""Regression: official plugin_guard must not mark this plugin dangerous.

Uses the pinned Hermes checkout only to import ``tools.plugin_guard``.
Missing checkout skips unless ``VANCINE_REQUIRE_HERMES_COMPAT=1``.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from hermes_gate import hermes_src, skip_or_fail  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class PluginGuardTests(unittest.TestCase):
    def test_scan_plugin_is_not_dangerous(self):
        src = hermes_src()
        if not src.is_dir():
            skip_or_fail(f"Hermes source not found at {src}")
        guard = src / "tools" / "plugin_guard.py"
        if not guard.is_file():
            skip_or_fail(f"tools.plugin_guard missing at {src}")

        src_s = str(src.resolve())
        if src_s not in sys.path:
            sys.path.insert(0, src_s)
        from tools.plugin_guard import scan_plugin

        result = scan_plugin(ROOT, source="local-review")
        critical = [f for f in result.findings if str(f.severity).lower() == "critical"]
        self.assertNotEqual(
            str(result.verdict).lower(),
            "dangerous",
            msg=f"plugin_guard verdict is dangerous: {result.summary}",
        )
        self.assertEqual(
            critical,
            [],
            msg="plugin_guard reported critical findings: "
            + ", ".join(f"{f.file}:{f.pattern_id}" for f in critical),
        )


if __name__ == "__main__":
    unittest.main()
