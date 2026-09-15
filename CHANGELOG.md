# Changelog

All notable changes to the Vancine Hermes provider plugin are documented in this
file. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-09-16

### Changed

- Replaced the retired first-run fallback model id `deepseek-flash` with the
  current catalog entry `deepseek-v4.1-flash`. The migration is a catalog-item
  swap, not a rename: the two ids are distinct catalog entries, and a raw server
  payload may carry both during the migration. Because the plugin filters the
  retired id exactly, its output keeps only the current id.

### Fixed

- Filtered the retired model id `deepseek-flash` out of live catalog responses.
  `parse_chat_model_ids` now drops delisted ids by exact string match, so a
  server payload that still publishes a retired id cannot resurface it in a live
  or cached model list. A live catalog that returns only the retired id resolves
  to a successful empty list, not a fallback trigger.

### Documentation

- Clarified the four distinct catalog roles and their refresh behavior: the
  Vancine public live catalog; the last successful live list the plugin keeps in
  process memory; the offline snapshot used only when the first request fails;
  and the Hermes core disk cache (`provider_models_cache.json` under
  `HERMES_HOME`). The plugin's in-process state, the offline snapshot, and the
  Hermes core disk cache are three different things, not one shared cache.

### Tests

- Added regression coverage for the catalog migration and fallback invariants
  (fallback carries the current replacement and no retired id; retired-only live
  responses stay empty across later failures; the retired filter is exact and
  not a prefix or regex) and for host compatibility.