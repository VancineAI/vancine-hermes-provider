"""Skip vs fail helpers for optional Hermes checkout tests.

Ordinary developer runs skip when the pinned Hermes tree is absent.
``VANCINE_REQUIRE_HERMES_COMPAT=1`` turns the same gaps into failures.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

EXPECTED_HERMES_SHA = "cbe9e5b2942f992d5f77e960cd36fd620a3cec0b"
DEFAULT_HERMES_SRC = "/tmp/hermes-agent-284d220"
REQUIRE_ENV = "VANCINE_REQUIRE_HERMES_COMPAT"


def require_hermes_compat() -> bool:
    return os.environ.get(REQUIRE_ENV, "").strip().lower() in {"1", "true", "yes"}


def hermes_src() -> Path:
    raw = os.environ.get("VANCINE_HERMES_SRC", DEFAULT_HERMES_SRC).strip()
    return Path(raw).expanduser()


def hermes_python() -> Path:
    """Interpreter used to import Hermes. Never a hardcoded personal path."""
    raw = os.environ.get("VANCINE_HERMES_PYTHON", "").strip()
    return Path(raw).expanduser() if raw else Path(sys.executable)


def skip_or_fail(message: str) -> None:
    if require_hermes_compat():
        raise AssertionError(message)
    raise unittest.SkipTest(message)
