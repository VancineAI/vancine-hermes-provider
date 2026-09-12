"""Isolated Hermes SHA compatibility tests.

Spawns a clean interpreter with HERMES_HOME under /tmp. Never reads or
writes the user's real ~/.hermes.

``subprocess.run`` here is the test harness only. It is not plugin runtime.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from hermes_gate import (  # noqa: E402
    EXPECTED_HERMES_SHA,
    hermes_python,
    hermes_src,
    skip_or_fail,
)

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_FILES = ("__init__.py", "catalog.py", "constants.py", "plugin.yaml")

FAKE_KEY = "test-key"

# Names a Hermes subprocess must never inherit. Values stay short so plugin_guard
# does not treat this file as credential_exposure.
SENTINEL_ENV_NAMES = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_PROFILE",
    "AWS_DEFAULT_PROFILE",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GITHUB_TOKEN",
    "AUTH_TOKEN",
    "COOKIE",
    "SESSION",
)

_ENV_ALLOWLIST = (
    "PATH",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LC_MESSAGES",
    "TMPDIR",
    "TEMP",
    "TMP",
    "TZ",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "TERM",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "SYSTEMDRIVE",
)

_ENV_DENY_SUBSTR = (
    "KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "CREDENTIAL",
    "AUTH",
    "COOKIE",
    "SESSION",
)

_ENV_DENY_EXACT = frozenset({
    "AWS_PROFILE",
    "AWS_DEFAULT_PROFILE",
    "GOOGLE_APPLICATION_CREDENTIALS",
})


def _is_isolated_tmp_home(home: Path) -> bool:
    resolved = str(home.resolve())
    return resolved.startswith("/tmp/") or resolved.startswith("/private/tmp/")


def _denied_env_name(name: str) -> bool:
    upper = name.upper()
    if upper in _ENV_DENY_EXACT:
        return True
    return any(part in upper for part in _ENV_DENY_SUBSTR)


def _isolated_env(
    home: Path,
    src: Path,
    source_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build a subprocess env from an allowlist. Never copy os.environ wholesale."""
    incoming = os.environ if source_env is None else source_env
    home_s = str(Path(home).resolve())
    env: dict[str, str] = {}
    for name in _ENV_ALLOWLIST:
        if _denied_env_name(name):
            continue
        value = incoming.get(name)
        if value:
            env[name] = value
    env["HOME"] = home_s
    env["HERMES_HOME"] = home_s
    env["XDG_CONFIG_HOME"] = str(Path(home_s) / ".config")
    env["XDG_CACHE_HOME"] = str(Path(home_s) / ".cache")
    env["XDG_DATA_HOME"] = str(Path(home_s) / ".local" / "share")
    env["USERPROFILE"] = home_s
    env["PYTHONPATH"] = str(src)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _child_env(
    home: Path,
    src: Path,
    source_env: dict[str, str] | None = None,
) -> dict[str, str]:
    env = _isolated_env(home, src, source_env=source_env)
    env["VANCINE_API_KEY"] = FAKE_KEY
    return env


def _install_plugin(home: Path, layout: str) -> Path:
    if layout == "user":
        dest = home / "plugins" / "model-providers" / "vancine"
    elif layout == "installed":
        dest = home / "plugins" / "vancine-provider"
    else:
        raise ValueError(layout)
    dest.mkdir(parents=True, exist_ok=True)
    for name in PLUGIN_FILES:
        shutil.copy2(ROOT / name, dest / name)
    return dest


_PROBE_SCRIPT = r"""
import json
import os
import sys
from pathlib import Path

expected = os.environ["HERMES_HOME"]
from hermes_constants import get_hermes_home
hermes_home = str(get_hermes_home())
path_home = str(Path.home())
if hermes_home != expected:
    sys.stderr.write(f"probe HERMES_HOME mismatch: {hermes_home!r} != {expected!r}\n")
    sys.exit(2)
if path_home != expected:
    sys.stderr.write(f"probe Path.home mismatch: {path_home!r} != {expected!r}\n")
    sys.exit(3)
sentinels = (
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_PROFILE", "AWS_DEFAULT_PROFILE",
    "GOOGLE_APPLICATION_CREDENTIALS", "GITHUB_TOKEN", "AUTH_TOKEN", "COOKIE", "SESSION",
)
leaked = [name for name in sentinels if name in os.environ]
if leaked:
    sys.stderr.write(f"probe inherited sentinel env: {leaked!r}\n")
    sys.exit(4)
import providers, hermes_cli.auth
print(json.dumps({"ok": True, "home": hermes_home, "path_home": path_home}))
"""


_CHILD_SCRIPT = r"""
import json
import os
import sys
import traceback

FAKE_KEY = os.environ["VANCINE_API_KEY"]
expected_home = os.environ["HERMES_HOME"]
out = {"ok": False}

def fail(msg, **extra):
    extra["error"] = msg
    extra["ok"] = False
    print(json.dumps(extra))
    sys.exit(0)

try:
    from pathlib import Path
    from hermes_constants import get_hermes_home
    home = str(get_hermes_home())
    path_home = str(Path.home())
    if home != expected_home:
        fail("hermes home is not the isolated directory", home=home, expected=expected_home)
    if path_home != expected_home:
        fail("Path.home is not the isolated directory", path_home=path_home, expected=expected_home)
    sentinels = (
        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_PROFILE", "AWS_DEFAULT_PROFILE",
        "GOOGLE_APPLICATION_CREDENTIALS", "GITHUB_TOKEN", "AUTH_TOKEN", "COOKIE", "SESSION",
    )
    leaked = [name for name in sentinels if name in os.environ]
    if leaked:
        fail("child inherited sentinel env", leaked=leaked)

    from providers import list_providers, get_provider_profile, register_provider
    from providers.base import ProviderProfile

    names = sorted({p.name for p in list_providers()})
    if "vancine" not in names:
        fail("vancine not in list_providers()", names=names[:50], n=len(names))

    profile = get_provider_profile("vancine")
    if profile is None:
        fail("get_provider_profile('vancine') returned None")
    alias = get_provider_profile("vancine-api")
    if alias is None or alias is not profile:
        fail("alias vancine-api did not resolve to the same profile")

    fields = {
        "name": profile.name,
        "aliases": list(profile.aliases),
        "display_name": profile.display_name,
        "base_url": profile.base_url,
        "auth_type": profile.auth_type,
        "api_mode": profile.api_mode,
        "env_vars": list(profile.env_vars),
        "default_aux_model": profile.default_aux_model,
        "fallback_models": list(profile.fallback_models),
        "signup_url": profile.signup_url,
        "models_url": profile.models_url,
    }
    expected = {
        "name": "vancine",
        "aliases": ["vancine-api"],
        "display_name": "Vancine",
        "base_url": "https://vancine.com/v1",
        "auth_type": "api_key",
        "api_mode": "chat_completions",
        "env_vars": ["VANCINE_API_KEY", "VANCINE_BASE_URL"],
        "default_aux_model": "glm-5.3-flash",
        "fallback_models": [],
        "signup_url": "https://vancine.com/console",
    }
    for key, value in expected.items():
        if fields.get(key) != value:
            fail("profile field mismatch", key=key, actual=fields.get(key), expected=value, fields=fields)

    register_provider(ProviderProfile(
        name="vancine",
        aliases=("vancine-api",),
        display_name="Vancine Duplicate",
        env_vars=("VANCINE_API_KEY", "VANCINE_BASE_URL"),
        base_url="https://vancine.com/v1",
        auth_type="api_key",
        api_mode="chat_completions",
    ))
    dup = get_provider_profile("vancine")
    if dup is None or dup.display_name != "Vancine Duplicate":
        fail("duplicate register_provider did not last-writer-win", display_name=getattr(dup, "display_name", None))
    register_provider(profile)

    from hermes_cli.auth import PROVIDER_REGISTRY
    cfg = PROVIDER_REGISTRY.get("vancine")
    if cfg is None:
        fail("vancine missing from PROVIDER_REGISTRY")
    if tuple(cfg.api_key_env_vars) != ("VANCINE_API_KEY",):
        fail("api_key_env_vars mismatch", actual=list(cfg.api_key_env_vars))
    if cfg.base_url_env_var != "VANCINE_BASE_URL":
        fail("base_url_env_var mismatch", actual=cfg.base_url_env_var)
    if cfg.inference_base_url.rstrip("/") != "https://vancine.com/v1":
        fail("inference_base_url mismatch", actual=cfg.inference_base_url)
    if PROVIDER_REGISTRY.get("vancine-api") is None:
        fail("alias vancine-api missing from PROVIDER_REGISTRY")

    from hermes_cli.config import OPTIONAL_ENV_VARS
    if "VANCINE_API_KEY" not in OPTIONAL_ENV_VARS:
        fail("VANCINE_API_KEY not injected into OPTIONAL_ENV_VARS")
    if "VANCINE_BASE_URL" not in OPTIONAL_ENV_VARS:
        fail("VANCINE_BASE_URL not injected into OPTIONAL_ENV_VARS")

    from hermes_cli.provider_catalog import provider_catalog
    catalog = {d.slug: d for d in provider_catalog()}
    if "vancine" not in catalog:
        fail("vancine missing from provider_catalog()", slugs=sorted(catalog)[:40])
    desc = catalog["vancine"]
    if desc.tab != "keys":
        fail("desktop tab mismatch", tab=desc.tab)
    if tuple(desc.api_key_env_vars) != ("VANCINE_API_KEY",):
        fail("catalog api_key_env_vars mismatch", actual=list(desc.api_key_env_vars))
    if desc.base_url_env_var != "VANCINE_BASE_URL":
        fail("catalog base_url_env_var mismatch", actual=desc.base_url_env_var)
    if desc.auth_type != "api_key":
        fail("catalog auth_type mismatch", actual=desc.auth_type)

    from hermes_cli.models import CANONICAL_PROVIDERS, list_available_providers, provider_model_ids
    if "vancine" not in {p.slug for p in CANONICAL_PROVIDERS}:
        fail("vancine missing from CANONICAL_PROVIDERS")
    available = {row["id"] for row in list_available_providers()}
    if "vancine" not in available:
        fail("vancine missing from list_available_providers()")

    model_ids = profile.fetch_models(api_key=FAKE_KEY, timeout=8.0)
    if not model_ids:
        fail("fetch_models returned empty/None", model_ids=model_ids)
    dumped = json.dumps(model_ids)
    if FAKE_KEY in dumped:
        fail("fetch_models leaked API key into model ids")

    live_or_cached = provider_model_ids("vancine")
    if not live_or_cached:
        fail("provider_model_ids('vancine') empty")
    if FAKE_KEY in json.dumps(live_or_cached):
        fail("provider_model_ids leaked API key")

    from hermes_cli.inventory import build_model_options_payload, load_picker_context
    payload = build_model_options_payload(
        load_picker_context(), include_unconfigured=True, refresh=False
    )
    providers = payload.get("providers") or []
    vancine_rows = [r for r in providers if str(r.get("slug") or "").lower() == "vancine"]
    if not vancine_rows:
        vancine_rows = [r for r in providers if str(r.get("id") or "").lower() == "vancine"]
    if not vancine_rows:
        fail(
            "vancine missing from build_model_options_payload (Desktop /api/model/options)",
            provider_slugs=[str(r.get("slug") or r.get("id") or r.get("name") or "") for r in providers][:40],
        )
    row = vancine_rows[0]
    options_models = row.get("models")
    if not isinstance(options_models, list) or not options_models:
        fail(
            "Desktop vancine row has no selectable models",
            row_keys=sorted(row.keys()),
            models=options_models,
        )
    option_ids = []
    for item in options_models:
        if isinstance(item, str) and item.strip():
            option_ids.append(item.strip())
        elif isinstance(item, dict):
            ident = item.get("id") or item.get("name")
            if isinstance(ident, str) and ident.strip():
                option_ids.append(ident.strip())
    if not option_ids:
        fail("Desktop vancine models is a non-empty list but has no model ids", models=options_models[:20])
    if FAKE_KEY in json.dumps(option_ids):
        fail("desktop models leaked API key")
    live_set = {str(m) for m in live_or_cached}
    option_set = set(option_ids)
    if not (option_set & live_set):
        fail(
            "Desktop /api/model/options models do not intersect provider_model_ids('vancine')",
            options=option_ids[:20],
            live=list(live_or_cached)[:20],
        )
    extra = sorted(option_set - live_set)
    if extra:
        fail(
            "Desktop options models are not a subset of provider_model_ids('vancine')",
            extra=extra[:20],
        )

    options_blob = json.dumps(payload)
    if FAKE_KEY in options_blob:
        fail("model options payload leaked API key")

    out = {
        "ok": True,
        "home": home,
        "path_home": path_home,
        "profile": fields,
        "n_list_providers": len(names),
        "n_model_ids": len(model_ids),
        "provider_model_ids": list(live_or_cached),
        "n_provider_model_ids": len(live_or_cached),
        "n_options_providers": len(providers),
        "options_vancine_models": option_ids,
        "n_options_vancine_models": len(option_ids),
        "providers_file": getattr(__import__("providers"), "__file__", ""),
    }
    print(json.dumps(out))
except Exception as exc:
    fail(f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
"""


class HermesCompatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        src = hermes_src()
        py = hermes_python()
        if not src.is_dir():
            skip_or_fail(f"Hermes source not found at {src}")
        if not (src / "providers" / "base.py").is_file():
            skip_or_fail(f"Hermes providers.base missing at {src}")
        if not py.is_file():
            skip_or_fail(f"Hermes Python not found at {py}")
        git = subprocess.run(
            ["git", "-C", str(src), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        sha = (git.stdout or "").strip()
        if git.returncode != 0 or not sha:
            skip_or_fail(
                f"git rev-parse HEAD failed in {src}: {(git.stderr or git.stdout or '').strip()}"
            )
        if sha != EXPECTED_HERMES_SHA:
            skip_or_fail(
                f"Hermes HEAD {sha} != expected {EXPECTED_HERMES_SHA} (src={src})"
            )
        with tempfile.TemporaryDirectory(prefix="vancine-hermes-probe-", dir="/tmp") as probe_home:
            probe_path = Path(probe_home).resolve()
            if not _is_isolated_tmp_home(probe_path):
                skip_or_fail(f"probe HERMES_HOME is not under /tmp: {probe_path}")
            probe = subprocess.run(
                [str(py), "-c", _PROBE_SCRIPT],
                cwd=str(src),
                env=_isolated_env(probe_path, src),
                capture_output=True,
                text=True,
                check=False,
            )
            probe_stdout = (probe.stdout or "").strip()
            probe_home_used = str(probe_path)
        if probe.returncode != 0:
            skip_or_fail(
                f"interpreter {py} cannot import Hermes from {src} "
                f"under isolated HERMES_HOME: "
                f"{(probe.stderr or probe.stdout or '')[-500:]}"
            )
        try:
            probe_payload = json.loads(probe_stdout.splitlines()[-1] if probe_stdout else "")
        except json.JSONDecodeError:
            skip_or_fail(
                f"probe stdout was not JSON: {probe_stdout[-500:]!r} "
                f"stderr={(probe.stderr or '')[-300:]!r}"
            )
        if not probe_payload.get("ok"):
            skip_or_fail(f"probe failed: {probe_payload}")
        if probe_payload.get("home") != probe_home_used:
            skip_or_fail(
                f"probe get_hermes_home {probe_payload.get('home')!r} != {probe_home_used!r}"
            )
        if probe_payload.get("path_home") != probe_home_used:
            skip_or_fail(
                f"probe Path.home {probe_payload.get('path_home')!r} != {probe_home_used!r}"
            )
        cls.hermes_src = src
        cls.hermes_python = py
        cls.hermes_sha = sha
        cls.probe_home = probe_home_used

    def _run_layout(self, layout: str) -> dict:
        home = Path(tempfile.mkdtemp(prefix=f"vancine-hermes-{layout}-", dir="/tmp")).resolve()
        if not _is_isolated_tmp_home(home):
            self.fail(f"layout HERMES_HOME is not under /tmp: {home}")
        try:
            _install_plugin(home, layout)
            # Test harness only: isolate HOME/HERMES_HOME. Not plugin runtime.
            proc = subprocess.run(
                [str(self.hermes_python), "-c", _CHILD_SCRIPT],
                cwd=str(self.hermes_src),
                env=_child_env(home, self.hermes_src),
                capture_output=True,
                text=True,
                timeout=180,
            )
            stdout = proc.stdout.strip()
            if FAKE_KEY in stdout or FAKE_KEY in proc.stderr:
                self.fail("child process leaked the fake API key")
            if not stdout:
                self.fail(
                    f"compat child produced no stdout (exit {proc.returncode}): {proc.stderr[-4000:]}"
                )
            try:
                payload = json.loads(stdout.splitlines()[-1])
            except json.JSONDecodeError:
                self.fail(
                    f"compat child stdout was not JSON: {stdout[-2000:]}\nstderr={proc.stderr[-2000:]}"
                )
            if not payload.get("ok"):
                self.fail(
                    f"compat layout={layout} failed: {payload.get('error')}\n"
                    f"{payload.get('traceback', '')[-3000:]}"
                )
            self.assertEqual(payload["home"], str(home))
            self.assertEqual(payload["path_home"], str(home))
            self.assertTrue(_is_isolated_tmp_home(Path(payload["home"])))
            self.assertTrue(_is_isolated_tmp_home(Path(payload["path_home"])))
            return payload
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def _assert_desktop_models(self, payload: dict) -> None:
        models = payload.get("options_vancine_models")
        live = payload.get("provider_model_ids") or []
        self.assertIsInstance(models, list)
        self.assertGreater(len(models), 0, "Desktop /api/model/options vancine row has no models")
        self.assertNotIn(FAKE_KEY, json.dumps(models))
        self.assertTrue(
            set(models) & set(live),
            f"no intersection between options={models[:12]!r} and provider_model_ids={list(live)[:12]!r}",
        )

    def test_user_plugin_layout_model_providers_vancine(self):
        payload = self._run_layout("user")
        self.assertGreater(payload["n_model_ids"], 0)
        self.assertIn("providers", payload["providers_file"])
        self._assert_desktop_models(payload)

    def test_installed_plugin_layout_plugins_vancine_provider(self):
        payload = self._run_layout("installed")
        self.assertGreater(payload["n_provider_model_ids"], 0)
        self.assertGreaterEqual(payload["n_options_providers"], 1)
        self._assert_desktop_models(payload)


class IsolatedEnvTests(unittest.TestCase):
    def test_allowlist_drops_credential_sentinels(self):
        home = Path("/tmp/vancine-hermes-env-test").resolve()
        src = Path("/tmp/hermes-agent-284d220")
        source = {
            "PATH": "/usr/bin",
            "LANG": "C",
            "AWS_ACCESS_KEY_ID": "sen-aws-id",
            "AWS_SECRET_ACCESS_KEY": "sen-aws-sec",
            "AWS_PROFILE": "sen-profile",
            "AWS_DEFAULT_PROFILE": "sen-def",
            "GOOGLE_APPLICATION_CREDENTIALS": "sen-gac",
            "GITHUB_TOKEN": "sen-gh",
            "AUTH_TOKEN": "sen-auth",
            "COOKIE": "sen-ck",
            "SESSION": "sen-sess",
            "HOME": "/Users/someone",
            "HERMES_HOME": "/Users/someone/.hermes",
        }
        env = _isolated_env(home, src, source_env=source)
        for name in SENTINEL_ENV_NAMES:
            self.assertNotIn(name, env)
        blob = json.dumps(env)
        for value in (
            "sen-aws-id", "sen-aws-sec", "sen-profile", "sen-def",
            "sen-gac", "sen-gh", "sen-auth", "sen-ck", "sen-sess",
            "/Users/someone",
        ):
            self.assertNotIn(value, blob)
        self.assertEqual(env["HOME"], str(home))
        self.assertEqual(env["HERMES_HOME"], str(home))
        self.assertEqual(env["USERPROFILE"], str(home))
        self.assertEqual(env["XDG_CONFIG_HOME"], str(home / ".config"))
        self.assertEqual(env["XDG_CACHE_HOME"], str(home / ".cache"))
        self.assertEqual(env["XDG_DATA_HOME"], str(home / ".local" / "share"))
        self.assertEqual(env["PATH"], "/usr/bin")
        self.assertEqual(env["PYTHONPATH"], str(src))
        self.assertEqual(env["PYTHONNOUSERSITE"], "1")
        self.assertEqual(env["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertTrue(_is_isolated_tmp_home(Path(env["HOME"])))
        self.assertNotIn("VANCINE_API_KEY", env)


if __name__ == "__main__":
    unittest.main()
