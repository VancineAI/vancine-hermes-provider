# vancine-hermes-provider

Community Hermes **model provider plugin** that adds [Vancine](https://vancine.com) as an OpenAI-compatible Chat Completions backend for:

- Hermes CLI
- Hermes Gateway
- Hermes Desktop (same Hermes Agent backend; there is no separate Desktop plugin or `plugin.js`)

This plugin is authored and maintained by Vancine. It is **not** a Hermes built-in provider. It does **not** constitute an official partnership, certification, recommendation, or endorsement by Nous Research, Hermes Agent, or their maintainers.

## What it does

After install, Hermes can resolve `--provider vancine` / `vancine:<model>` using:

| | |
| --- | --- |
| Provider ID | `vancine` |
| Display name | Vancine |
| Plugin manifest name | `vancine-provider` |
| API mode | `chat_completions` |
| Auth | API key (`VANCINE_API_KEY`) |
| Default base URL | `https://vancine.com/v1` |
| Optional base URL override | `VANCINE_BASE_URL` |
| Register | https://vancine.com |
| API keys | https://vancine.com/console |
| Docs | https://vancine.com/docs |
| Models and pricing | https://vancine.com/docs/models |

The plugin does not ship a hardcoded full model list. Hermes loads Chat Completions models from Vancine's public Pi catalog.

## Isolated development test

This example uses a throwaway directory. It does **not** default to `~/.hermes` and must not be pointed at your real Hermes home unless you intend that.

```bash
HERMES_HOME="$(mktemp -d /tmp/vancine-hermes-XXXX)"
export HERMES_HOME
mkdir -p "$HERMES_HOME/plugins/model-providers"
ln -sfn /absolute/path/to/vancine-hermes-provider "$HERMES_HOME/plugins/model-providers/vancine"
HERMES_HOME="$HERMES_HOME" hermes doctor
```

Hermes discovers the drop-in from `$HERMES_HOME/plugins/model-providers/<name>/`. You can also copy the plugin files into `$HERMES_HOME/plugins/vancine-provider/` (the `hermes plugins install` layout). That directory must contain `plugin.yaml` with `kind: model-provider` and `__init__.py`.

Set `VANCINE_API_KEY` in that isolated environment before sending chat requests.

## Install into your real Hermes home

These commands modify the Hermes home you actually use. Do not run them from an automated test. Isolation examples above stay under `/tmp`.

```bash
# This modifies your real Hermes plugin directory.
HERMES_USER_HOME="${HERMES_HOME:-$HOME/.hermes}"
mkdir -p "$HERMES_USER_HOME/plugins/model-providers"
ln -sfn /absolute/path/to/vancine-hermes-provider \
  "$HERMES_USER_HOME/plugins/model-providers/vancine"
```

Restart the Hermes CLI / Gateway / Desktop backend after linking. `vancine` should appear as an API-key provider.

## GitHub install

Public source: https://github.com/VancineAI/vancine-hermes-provider

```bash
hermes plugins install VancineAI/vancine-hermes-provider
```

Hermes treats this as a **custom (unreviewed) source**, not an official catalog entry. After clone it asks `Enable 'vancine-provider' now? [y/N]`. Answer `y` to activate.

This plugin is **not** in the official Hermes plugin catalog. Being listed there is a separate discovery path and has not been requested.

`hermes plugins validate` currently exits 1 with `capability probe: no register()`. That gate looks for a generic PluginManager `register(ctx)` entry. Runtime discovery for `kind: model-provider` uses import-time `register_provider` instead, and PluginManager skips this kind so it does not double-instantiate. Hermes's own bundled model providers fail the same check. This plugin does not add a no-op `register()` to paper over that admission-gate mismatch.

A pip extra / PyPI package is not provided in this tree.

## Credentials

Set the key in the same environment Hermes reads (process env or the Hermes `.env` for that `HERMES_HOME`):

```bash
export VANCINE_API_KEY="your-vancine-key"
# optional; default is https://vancine.com/v1
export VANCINE_BASE_URL="https://vancine.com/v1"
```

Get a key at https://vancine.com/console.

`VANCINE_BASE_URL` only overrides the **inference** endpoint. The model catalog always comes from `https://vancine.com/api/pi/catalog` and does not use the API key.

## CLI, Desktop local, and Desktop remote Gateway

| Surface | Where the plugin must be installed | Notes |
| --- | --- | --- |
| Hermes CLI | The `HERMES_HOME` used by that CLI process | `hermes chat --provider vancine -m glm-5.3-flash` |
| Hermes Gateway | The Gateway host's `HERMES_HOME` | Gateway and CLI share the Agent backend. |
| Hermes Desktop, local backend | The same `HERMES_HOME` as the local Hermes runtime Desktop launched | Desktop does not load a second catalog. It uses `/api/model/options` on the Agent backend. |
| Hermes Desktop, remote Gateway | **The remote Gateway host**, not only the machine showing the Desktop UI | Desktop talks to the remote Agent. A plugin that exists only on the laptop will not appear. |

Desktop local mode: start Desktop with the same `HERMES_HOME` you installed into (for a sandbox, `HERMES_HOME=/tmp/throwaway`).

**Isolated Desktop status (not `~/.hermes`, not a general production rollout):**

- Page display: in an isolated production Electron build (`file://` renderer, no `npm run dev`), a human check confirmed the model settings page is not a skeleton, the Provider dropdown lists Vancine, and the Model dropdown lists 17 chat models.
- One live chat: the same isolated Desktop sent a single prompt `Reply with OK.` with main model `vancine` / `glm-5.3-flash`. The thread showed assistant text `OK` (Hermes UI: 已思考 OK). The isolated backend issued `POST https://vancine.com/v1/chat/completions` (Authorization present; catalog was not used for this call). Session `tool_call_count` was 0. Hermes recorded `input_tokens=13302`, `output_tokens=28`, `reasoning_tokens=24`; `actual_cost_usd` was unset (`cost_status=unknown`).
- This is **not** an end-to-end certification of every Desktop path, remote Gateway, or a real user home. Dev-mode (`npm run dev`) skeleton flashing remains consistent with React StrictMode effect replay and is not proven as the sole cause.

Backend contracts (`list_providers`, `get_provider_profile`, `PROVIDER_REGISTRY`, `provider_catalog`, `build_model_options_payload` / `/api/model/options`) are covered by automated tests.

## Choosing a Vancine model

```bash
hermes model
# or
hermes chat --provider vancine -m glm-5.3-flash
```

Use `vancine:<model-id>` anywhere Hermes accepts `provider:model`. Model ids are Vancine Chat Completions ids from the live catalog (for example `glm-5.3-flash`, `qwen3.8-flash`, `deepseek-v4.1-flash`). Image, video, audio, embedding, and other non-chat models are not listed. Retired ids such as `deepseek-flash` are filtered out of every live list even if the server still publishes them.

The cheap auxiliary default is `glm-5.3-flash` (summaries, compression). You can still pick any catalog model as the main chat model.

## Dynamic catalog, cache, and fallback

Live source: **unauthenticated** `GET https://vancine.com/api/pi/catalog`.

That endpoint is a Vancine Pi catalog (`provider=vancine`, `schemaVersion=1`) of Chat Completions models. It is used instead of `https://vancine.com/v1/models` because the OpenAI-style models list requires an API key and can include image/video/audio models Hermes cannot call as chat.

Two layers, which must not be conflated:

**This plugin (process memory)**

1. A successful live fetch — including a legitimate empty compatible list — is recorded as success and replaces the previous live list in this process.
2. A later fetch failure returns that last live list. It does **not** re-inject the first-run snapshot.
3. First-run failure only (never a successful live fetch) returns this **snapshot**, which is not a live catalog:
   - `hy4-preview`
   - `deepseek-v4.1-flash`
   - `glm-5.3-flash`
   - `qwen3.8-flash`
4. After a live fetch succeeds, a snapshot id that Vancine no longer publishes is **not** revived by this plugin's fallback.
5. Delisted ids are filtered from live payloads by exact match (`deepseek-flash`). `deepseek-v4.1-flash` is a different catalog entry that replaced it, not a rename of the same id, so the two are distinct catalog entries. The raw server payload may still return both ids during the migration; because the plugin filters the retired id exactly, the list this plugin hands to Hermes never exposes both at once. A live catalog that still returns only the retired id resolves to a successful empty list.

**Hermes core disk cache** (`provider_models_cache.json` under `HERMES_HOME`)

Hermes itself caches provider model ids (about 1 hour TTL, stale-while-revalidate up to 7 days). That cache is Hermes core behaviour, not a second catalog in this plugin. A later empty live result does **not** guarantee that every Hermes UI immediately shows an empty Vancine list: the core may keep serving a previous non-empty list for the same credentials until that cache entry expires. This plugin does not delete or rewrite that cache.

`https://vancine.com/v1/models` is not used as the picker source. `https://models.dev/providers/vancine/` is not queried by this plugin.

The catalog is not guaranteed realtime and can fail.

## Security

- The API key is only for Vancine inference at the configured base URL (`https://vancine.com/v1` or `VANCINE_BASE_URL`). This plugin does not send the key to the Pi catalog, Models.dev, GitHub, PyPI, Hermes, or Nous Research.
- The key is not written into the catalog cache. Errors and logs redact it when it is passed into `fetch_models`.
- No telemetry, analytics, background beacons, install scripts, or custom Desktop UI.
- Do not paste production keys into issues, test output, or chat logs.

## Uninstall / stop loading

Hermes model-provider discovery imports every `$HERMES_HOME/plugins/model-providers/<name>/` directory and every `$HERMES_HOME/plugins/<name>/` directory whose `plugin.yaml` declares `kind: model-provider`. That filesystem scan does **not** honour `hermes plugins disable`. Disable is not a reliable way to stop this provider from loading.

The reliable stop is to remove or unlink the plugin directory, then restart Hermes CLI / Gateway / Desktop. The commands below use the same real user home as the install section and **will modify that directory**. Do not run them against an isolated `/tmp` test home unless that is what you intend.

```bash
HERMES_USER_HOME="${HERMES_HOME:-$HOME/.hermes}"
```

**Local drop-in**

```bash
rm "$HERMES_USER_HOME/plugins/model-providers/vancine"    # symlink
# or
rm -rf "$HERMES_USER_HOME/plugins/model-providers/vancine"
```

**Installed clone** (`hermes plugins install`, after a public GitHub repo exists)

```bash
HERMES_HOME="$HERMES_USER_HOME" hermes plugins remove vancine-provider
```

`remove` deletes the clone under `$HERMES_USER_HOME/plugins/`. After removal, restart the backend.

Unset `VANCINE_API_KEY` and `VANCINE_BASE_URL` from that Hermes `.env` if you added them.

Removing the plugin does not delete Vancine account data. Rotate the key in https://vancine.com/console if it may have leaked.

## Tests

Offline unit tests (catalog, manifest, security) need no Hermes checkout:

```bash
python3 -m unittest tests.test_catalog tests.test_plugin_yaml tests.test_security -v
```

`python3 -m unittest discover -s tests -v` also collects the Hermes compatibility and plugin_guard tests. Those **skip** when any of the following is missing or mismatched, unless the gate env is set:

- `VANCINE_HERMES_SRC` (default `/tmp/hermes-agent-284d220`) is not a Hermes Agent source tree
- `VANCINE_HERMES_PYTHON` (or `sys.executable` when unset) does not exist or cannot `import providers` from that tree
- `git -C "$VANCINE_HERMES_SRC" rev-parse HEAD` is not `cbe9e5b2942f992d5f77e960cd36fd620a3cec0b` (compatibility tests only)

Skipped tests are not compatibility evidence.

Fixed-SHA compatibility gate — missing tree, interpreter, or SHA **fails** instead of skip:

```bash
VANCINE_REQUIRE_HERMES_COMPAT=1 \
VANCINE_HERMES_SRC=/tmp/hermes-agent-284d220 \
VANCINE_HERMES_PYTHON=/path/to/python-that-can-import-hermes-deps \
python3 -m unittest tests.test_hermes_compat tests.test_plugin_guard -v
```

Those tests set `HERMES_HOME` under `/tmp` and never touch `~/.hermes`.

## License

MIT. See [LICENSE](LICENSE).
