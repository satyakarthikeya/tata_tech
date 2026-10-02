# DECISIONS.md

- Python 3.13.6 used instead of 3.11 (only interpreter available); code stays 3.11-compatible (no 3.12+ syntax).
- docs/, data/bcm_spec.yaml, data/requirements_seed.csv did not exist; synthetic BCM spec and requirements seed authored from scratch per PROJECT.md/SCOPE.md.
- Package root is `uds_assistant/` (implied by `python -m uds_assistant.eval.run_eval`); component dirs from PROJECT.md (protocol/, rules/, ...) live inside it.
- Owner asked for subagents ("sonnet 5.5"): no such model exists; Sonnet 5 used for routine phases, Opus for correctness-critical phases.
