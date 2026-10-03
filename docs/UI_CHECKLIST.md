# UI manual click-through checklist

For the owner. About 15 minutes. The Streamlit page has headless tests (`tests/ui`), but nobody has clicked through it in a browser yet; this checklist is that check. Every label below is the real label in `uds_assistant/ui/streamlit_app.py`, confirmed by running the page under Streamlit's `AppTest`. Test ids start with `req_ui_001__` because the default Requirement id is `REQ-UI-001`; if you change that field, the prefix changes.

Nothing here needs a GPU or Ollama, except step 10 (optional).

Tick each step when the screen matches. If it does not, follow the "If not" line, write down what you saw, and carry on.

---

## 1. Start the page

**Do.** In PowerShell, from the repo root:

```powershell
cd C:\Users\pasar\Desktop\tata_tech
streamlit run uds_assistant/ui/streamlit_app.py
```

Your browser opens `http://localhost:8501`. Leave `LLM_MODE` unset (mock LLM, the default).

**Should see.**
- Title "UDS Diagnostics & Automated Test Generation Assistant" and a grey line starting "Local, offline-capable. ECU spec is SYNTHETIC."
- Five headings: "1. Generate tests from a requirement", "2. Review generated tests", "3. Run on the ECU simulator", "4. Evaluation report (mock vs ollama)", "5. Export".
- In section 2 a yellow banner: "Generated tests require human review before execution on real hardware. The ECU spec is synthetic. Audit trail: outputs/ui_audit.sqlite."
- Before any generation: "No tests generated yet.", "Generate tests first." (sections 3 and 5).

**If not.**
- `streamlit` is not recognised or the page says `No module named streamlit`: `python -m pip install -e ".[ui]"`.
- A red error `ModuleNotFoundError: No module named 'uds_assistant'`: run `$env:PYTHONPATH = "."` in the same PowerShell window, then start again (or `python -m streamlit run uds_assistant/ui/streamlit_app.py`).
- Port busy: add `--server.port 8502`.

## 2. Enter a requirement and generate

**Do.** In the text box "Diagnostic requirement (plain English)" replace the text with:

`Writing the interior lighting brightness DID (0x0100) shall require extended session and security level 0x01.`

Leave "Requirement id" as `REQ-UI-001`. Click the blue "Generate tests" button.

**Should see.** A spinner ("Running parse -> retrieve -> plan ..."), then a green box "Generated 18 test(s), dropped 0. run_id=<number>", and under it a grey line "LLM backend used: mock; engine: langgraph." (or "engine: plain" if LangGraph is unavailable). No yellow "Fallback:" warning (that only appears with `LLM_MODE=ollama` and no server). The mock is deterministic, so you should get 18 tests every time with this text.

**If not.**
- Red "Requirement text must not be empty.": the box is empty.
- A different test count: note it; the page is still fine if the number stays the same on a second click. A count that changes between clicks is a bug.
- A Python traceback in red: copy it and stop; that is a real failure.

## 3. Review the tests

**Do.** Look at the table in section 2, then open the dropdown "Inspect test" and pick `req_ui_001__tpl_write_oor_0100`.

**Should see.**
- Table columns: `id`, `category`, `template_id`, `review_status`, `steps`, `citations`. Categories present: negative, positive, security, session, timing. Every `review_status` is `validated`. Every row has at least one citation.
- Below the dropdown: the test title, then a short explanation sentence, then "Steps (hex)" with one block per step in lower-case hex, for this test:
  - `[0] -> 1003` / `[0] <- 5003003201f4`
  - `[1] -> 2701` / `[1] <- 6701950677e8`
  - `[2] -> 27029a068f73` / `[2] <- 6702`
  - `[3] -> 2e010065` / `[3] <- 7f2e31` (write 101 into a 0 to 100 field: refused with NRC 0x31)
- "Citations": grey lines like `data/bcm_spec.yaml / did:interior_lighting_brightness_pct -- "..."`.
- Tests with a clock step (for example `..._s3_timeout_03`) show a block like `[5] advance_time: {...}` instead of a request.

**If not.** Missing citations, an empty explanation ("(no explanation)"), or hex that differs from the above: note the test id. The yellow human-review banner must stay visible in section 2.

## 4. Mark one test human_reviewed

The UI supports this (it is a real button; review status is also stored in `outputs/ui_audit.sqlite`).

**Do.** With `req_ui_001__tpl_write_oor_0100` still selected, click the button "Mark req_ui_001__tpl_write_oor_0100 as human_reviewed". (The button always names the test currently selected in "Inspect test".)

**Should see.** The page reloads. In the table the `review_status` of that test now reads `human_reviewed`; the other 17 still read `validated`. The row order in the table may change and the "Inspect test" dropdown goes back to the first test; that is expected (the table is re-read from the audit store).

**If not.** If the button is missing, generation did not finish (no run_id): redo step 2. If the status does not change, note it; the audit store write failed.

## 5. Run on the clean simulator

**Do.** In section 3, leave "Inject bug(s) (optional)" empty and click "Run suite on simulator".

**Should see.** A big "Passed" number `18/18` and a table with columns `test_id`, `passed`, `functional_passed`, `timing_passed`, `failure`, `duration_ms`: every `passed` is true and every `failure` is empty.

**If not.** A false row on the clean simulator is a real defect (the clean simulator must pass every generated test). Copy the `failure` text and stop.

## 6. Toggle a bug and re-run (three bug sets)

The dropdown "Inject bug(s) (optional)" lists three kinds of bug. The label says which, and it matters for how much a catch proves:

- `[in-sample] <id> (<title>)`: 26 bugs the templates were tuned on. A catch proves little.
- `[held-out v1, seen] <id> (<title>)`: 12 bugs the Part C templates were designed against. Also not independent.
- `[held-out v2, fresh] <id> (<title>)`: 15 bugs written blind after the freeze. The only independent ones.

**Do (a).** Pick `[in-sample] write_ignores_value_range (Write ignores value range)` and click "Run suite on simulator".

**Should see (a).** "Passed" `17/18`; one table row with `passed` false: `req_ui_001__tpl_write_oor_0100`, `failure` = `step 3: expected ['7f2e31'], got ['6e0100']`.

**Do (b).** Click the small x on that bug to remove it, pick `[held-out v1, seen] seed_returned_while_unlocked (...)`, run again. Expect `req_ui_001__tpl_seed_while_unlocked_01` to fail: `step 3: expected ['670100000000'], got ['670132a31485']`.

**Do (c).** Remove it, pick `[held-out v2, fresh] session_reentry_keeps_unlock (...)`, run again. Expect `req_ui_001__tpl_session_relock_01` to fail: `step 4: expected ['7f2e33'], got ['6e0100']`.

**If not.** A bug that is not caught is not a UI error: the table just shows 18/18. Only a missing set of options is a UI problem (you should see all three prefixes). Several bugs can be selected at once; failures then mix.

## 7. See which test failed and why

**Do.** Re-run (a) from step 6. Then in section 2 pick the failing test in "Inspect test" and compare its step 3 with the `failure` text.

**Should see.** The `failure` column gives "step N: expected [...], got [...]": the step number, the bytes the test expected (from the rules engine) and the bytes the buggy simulator returned. In the "Steps (hex)" block, step 3 shows the request `2e010065` and the expected reply `7f2e31`, so you can read the bug as: expected refusal, got `6e0100` (write accepted).

**If not.** If `failure` is empty for a failed row, or the step index does not match the block, note it.

## 8. Export pytest and CAPL

**Do.** Scroll to section 5 "Export". Click "Download pytest file", then "Download CAPL template (unverified)". Optionally run the pytest file from the repo root:

```powershell
$env:UDS_REPO_ROOT = "C:\Users\pasar\Desktop\tata_tech"
python -m pytest generated_tests_test.py -q
```

**Should see.** Two files in your downloads folder: `generated_tests_test.py` and `generated_tests.can`. The pytest file runs on the in-process simulator (18 passed for the 18 generated tests; verified for this requirement). The CAPL file starts with a comment "UNVERIFIED TEMPLATE - not compiled or run in CANoe". That label is honest: the CAPL has never been compiled or run in CANoe. Do not describe it as working CAPL.

**If not.** If the pytest file cannot import `uds_assistant`, set `UDS_REPO_ROOT` as above. A failing exported test is a real defect: note which.

## 9. Open the evaluation section (v2 headline, before/after, noise check)

**Do.** Scroll to "4. Evaluation report (mock vs ollama)". It reads `outputs/eval_report.json`.

**Should see, with a version-3 report** (after the real evaluation has been run):
- A line "Report version 3".
- "Freeze status (...)": a green box "Freeze status: all recorded hashes MATCH and the worktree is clean." and a path table. A red "MISMATCH" box means a frozen path changed; write down which row.
- "Fresh v2 headline (written blind after the Part C freeze)": a table with a mock and an ollama column: held-out v2 bug detection (generated / gold / union), natural v2 requirement understanding, and two supplementary rows. A mode that was not run says "not run yet".
- "Headline metrics": the 7-row table; the v1 rows say SEEN.
- "Noise check (natural v2, repeated runs)": for ollama, one table row per run (run 1 is the one used for the tables) and a line "Mean and min-max range over all runs: ..."; for mock, "Second run identical: True".
- "Before / after Part C": the before/after table (from `outputs/partC/before_after.md`), with its comparability note.
- "Mock vs Ollama: side by side" (with v2 rows first) and "Retrieval comparison: BM25 vs Chroma ...".
- Further down: the per-bug and per-requirement tables for v2, then v1 under "seen (templates designed against these misses)".

**Should see, with the current version-2 report** (before the real evaluation is run): "Report version 2 (n/a — report predates Part C: v2 rows are n/a, v1 sections are shown as measured)", the fresh v2 table filled with "n/a — report predates Part C", "Noise check: n/a — report predates Part C", "Before/after table not generated yet (...)", and the v1 sections as they were measured. That is correct behaviour, not a bug.

**If not.** "No report yet at ..." means `outputs/eval_report.json` is missing. A Python traceback in this section is a real bug: note the report version and copy the error. To preview another report file: `$env:UDS_EVAL_REPORT = "<path>"` (and `$env:UDS_BEFORE_AFTER = "<path>"`) before starting the page.

## 10. Mock versus ollama (optional)

Ollama is only used if you ask for it and the server is running; otherwise the page falls back to the mock.

**Do (only if Ollama is running and the GPU is free).** Stop the page (Ctrl+C), then:

```powershell
$env:LLM_MODE = "ollama"
streamlit run uds_assistant/ui/streamlit_app.py
```

Generate tests as in step 2 (about 30 seconds or more per requirement; the first call also loads the model).

**Should see.** The grey line reads "LLM backend used: ollama; engine: ...". Expect a different test count than the mock's 18; the tests may differ, but the bytes always come from templates. If Ollama is not running instead: a yellow "Fallback: LLM_MODE=ollama requested but Ollama is not reachable at ...; falling back to the deterministic mock LLM." and "LLM backend used: mock". The page does not crash.

Section 4 compares the two modes from the report in either case; it never runs the model itself.

**If not.** If you set `LLM_MODE=ollama` without a server and see no yellow "Fallback:" warning, or the grey line says ollama when it is not running, note it. Unset the variable afterwards: `Remove-Item Env:LLM_MODE`.

---

## What to report back

For each step: pass, or what you saw. Especially note anything labelled differently from this checklist, any traceback, and any step where the screen needed more than one click to match.
