# End-to-end check (branch `simple`)

Run on 2026-10-04 on a Windows laptop (RTX 3050 4 GB), Python 3.13.6, Ollama with `qwen2.5:3b-instruct-q4_K_M`,
code at commit `9e2df41` plus later edits to `Dockerfile` and docs only (the eval header says `+dirty` for that reason).
Nothing was tuned on evaluation data.

| Check | Result |
|---|---|
| `python -c "import uds_assistant"` | OK |
| `python scripts/demo.py` (REQ-005, bug `accepts_any_key`) | OK in 24 s: 4 tests generated, 4/4 pass on the clean simulator, with the bug 3/4 pass, "Bug caught by 1 test(s)" (`req_005__tpl_security_lockout_01`, first failing step: expected `7F 27 35`, actual `67 02`), pytest and CAPL files exported. The default bug `write_ignores_value_range` is *not* caught by REQ-005's tests; the demo says so and the default was changed to `accepts_any_key` for the demo story |
| `python -m uds_assistant.eval.run_eval` (full, with Ollama) | OK, 733 s, report in `outputs/eval_report.md` / `.json` (copy in `docs/RESULTS.md`): 15 seed requirements, 83 tests; 9/15 blind v3 bugs caught; Q&A 19/21. An earlier full run (git `377e7b5+dirty`, before a docstring-level cleanup) gave the same headline numbers: 81 tests, 9/15 bugs, Q&A 19/21 |
| API (`python -m uds_assistant.api`) | `/health` returned `ollama_reachable: true`; `/ask` ("length of DID 0xF190") answered with a citation; `/generate` returned run_id 1 with 8 tests; `/run` with `accepts_any_key` returned 7/8 passed; `/export` returned the pytest file (7962 chars) and the CAPL file (10901 chars). With `OLLAMA_HOST` pointing nowhere, `/ask` and `/generate` return HTTP 503 "Ollama is not reachable ... Start Ollama and pull qwen2.5:3b-instruct-q4_K_M" and `/health` reports the hint |
| Streamlit headless | `streamlit run` started and served (15 s) with no errors in the log. Because no browser connects in a headless boot, the script itself was also executed with Streamlit's `AppTest`: four tabs, green Ollama status, Ask ("What does NRC 0x33 mean?") answered, Generate (8 tests) and Run with a bug worked, the Results tab rendered 8 cards from the report, zero exceptions |
| Exported pytest file (`outputs/exports/generated_tests_test.py`) | **83 passed** in 1.1 s |
| `ruff check .` | All checks passed |
| Grep for `mock`, `bm25`, `LLM_MODE`, `RETRIEVER` | Nothing left in code. The only mentions are in `DECISIONS.md`, `MODEL_SETUP.md` and `PROJECT.md`, which say they were removed (the old one lived in `Dockerfile` and was fixed) |

## Bugs found and fixed while checking

- A stale local audit database broke runs after I renamed a column; the rename was reverted (the schema keeps `llm_mode`). If you ran the old version, an existing `outputs/ui_audit.sqlite` still works.
- The demo's first default bug was not caught by its requirement; changed (see above).
- The UI's run scope defaulted to "selected test", which hid the bug being caught; it now defaults to "all tests".

## Not done or not verified

- Docker was not built (no network assumption); `docker-compose.yml` is untested.
- The CAPL export was never compiled or run in CANoe.
- The Streamlit UI was not clicked through in a real browser (use `docs/UI_CHECKLIST.md`).
- The manual-time row of the test-design-time metric is "owner to fill".
- The pytest suite was removed from this branch on purpose (it is in tag `v1-full-archive`); verification here is this check plus `run_eval`.
- LLM output is not bit-deterministic, so a re-run can move scores by a few points (the two runs above agree on every headline number except test counts).

## Switching branches

```bash
git checkout simple            # this simplified release (Ollama + Chroma, one eval, four tabs)
git checkout master            # the full version on its original branch (this repository has no local branch named "main")
git checkout v1-full-archive   # the same full version, tagged, with the test suite and history
```
