# DECISIONS.md

- Python 3.13.6 used instead of 3.11 (only interpreter available); code stays 3.11-compatible (no 3.12+ syntax).
- docs/, data/bcm_spec.yaml, data/requirements_seed.csv did not exist; synthetic BCM spec and requirements seed authored from scratch per PROJECT.md/SCOPE.md.
- Package root is `uds_assistant/` (implied by `python -m uds_assistant.eval.run_eval`); component dirs from PROJECT.md (protocol/, rules/, ...) live inside it.
- Owner asked for subagents ("sonnet 5.5"): no such model exists; Sonnet 5 used for routine phases, Opus for correctness-critical phases.
- Synthetic SecurityAccess algorithm: key = rotl8(seed_byte XOR (0xA5+level mod 256), 3) + level (mod 256), applied per byte; chosen to be simple, deterministic, and independently reproducible without copying any real algorithm.
- YAML spec authoring convention: `default_value` is a hex string (e.g. "F190" bytes as "f190"), converted to raw bytes by `_parse_spec_dict` before pydantic validation, since pydantic's `bytes` field otherwise treats a YAML string as UTF-8 text.
- `EcuSpec` cross-reference validation (sessions referenced by security levels/DIDs/routines, security levels referenced by DIDs/routines, SIDs referenced by sessions) is enforced in one `model_validator(mode="after")` so a malformed spec fails fast at `load_spec()` time rather than later in the rules engine.
- SecurityAccess seed/key subfunctions are constrained odd=seed / even=key via field validators, matching the udsoncan `Mode.RequestSeed`/`Mode.SendKey` convention used for cross-checking.
- `tester_present()` defaults `suppress_positive=True` since that is how it is used operationally (periodic keep-alive with no need for a response); callers that want a response pass `suppress_positive=False`.
