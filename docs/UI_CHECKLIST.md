# UI manual click-through checklist (tabbed UI)

For the owner. About 15 minutes. The page has headless tests (`tests/ui`, `streamlit.testing` AppTest), but a browser click-through is still the final check. Labels below are the real labels in `uds_assistant/ui/streamlit_app.py`.

Nothing needs a GPU or Ollama except the items marked (Ollama). Tick each item when the screen matches; if it does not, write down what you saw and carry on.

## 0. Start the page

```powershell
cd C:\Users\pasar\Desktop\tata_tech
streamlit run uds_assistant/ui/streamlit_app.py
```

Browser opens `http://localhost:8501`. Leave `LLM_MODE` / `RETRIEVER` unset.

- [ ] Title "UDS Diagnostics & Automated Test Generation Assistant" and five tabs: Ask, Generate & Review, Run on Simulator, Export, Results.
- [ ] Sidebar (Settings): "LLM mode" radio, "Retriever" radio, and ONE yellow banner: "Synthetic ECU spec. Human review required before any real-hardware execution." That text appears nowhere else on the page.
- [ ] Ollama running: radio offers `mock` and `ollama`, green line "Ollama reachable at http://localhost:11434". Ollama not running: radio shows only `mock`, is greyed out, yellow line "Ollama option disabled: Ollama not reachable at ...". (A radio cannot grey out a single option, so the unavailable option is removed and the widget disabled.)
- [ ] Chroma installed: retriever radio offers `bm25` and `chroma`. Chroma missing: only `bm25`, greyed, yellow "Chroma option disabled: ...".
- [ ] If `streamlit` is not recognised: `python -m pip install -e ".[ui]"`. If `No module named 'uds_assistant'`: `$env:PYTHONPATH = "."`.

## 1. Tab "Ask"

- [ ] Pick the example "What is the length of DID 0xF190?" in "Example questions" (it fills the question box), click "Ask". Expect: "DID 0xF190 (VIN) is 17 bytes long ... read-only", a green badge "confidence: high" with its reason, and an expander "Citations (n)" with layer (`ecu`), source (`data/bcm_spec.yaml`) and a quoted line.
- [ ] Ask "What does DID 0x0999 contain?". Expect a yellow callout "Not found in the approved sources." and a red badge "confidence: low". No citations.
- [ ] (Ollama) Switch LLM mode to ollama and ask again: the line "Answer phrased by: ollama" appears; the facts stay the same (the model only rephrases, and a rephrasing that changes a value is discarded and noted).

## 2. Tab "Generate & Review"

- [ ] The requirement box is EMPTY and shows a placeholder. Click "Generate tests" with it empty: red "Requirement text must not be empty."
- [ ] "Load example" has 4 entries: REQ-001, REQ-005, REQ-010 (seed requirements) and REQ-NL-DOOR ("The door lock status must only be writable in extended session after security unlock."). Loading one fills the box and the Requirement id.
- [ ] Load the REQ-005 example, click "Generate tests" (mock). Expect green "Generated 18 test(s), dropped 0. run_id=<n>", caption "LLM backend used: mock; engine: langgraph." (or plain), no "Fallback:" warning.
- [ ] Table with columns id, category, confidence, review status. Every status is `validated`.
- [ ] "Select a test to inspect": pick `req_005__tpl_write_oor_0100`. Expect steps like `[3] 2E 01 00 65 → 7F 2E 31 (requestOutOfRange)` with a grey line under each: "WriteDataByIdentifier DID 0x0100 (interior_lighting_brightness_pct); expects: negative response to WriteDataByIdentifier: requestOutOfRange".
- [ ] Targets: green chips "written" for targets named in the requirement, orange chips "inferred" for the rest.
- [ ] Explanation, Citations (source, ref, quote), confidence badge with reason.
- [ ] Type a comment, click "Approve": green "Approved <id>. Stored in the audit DB.", the table status becomes `human_reviewed`. "Reject" returns the test to draft and the table says `rejected`. "Add comment" only logs the comment. The log lines show under the buttons. All three are in `outputs/ui_audit.sqlite` (table `decisions`, node `review`).
- [ ] (Ollama) With ollama selected and the server stopped mid-session: a yellow "Fallback: LLM_MODE=ollama requested but Ollama is not reachable ... falling back to the deterministic mock LLM." and "LLM backend used: mock". The page does not crash.

## 3. Tab "Run on Simulator"

- [ ] Before generating: blue "Generate tests first (Generate & Review tab)."
- [ ] "Inject a bug" has "no bug (clean simulator)" first, then groups `[in-sample]`, `[held-out v1]`, `[held-out v2]`, `[held-out v3, fresh]`; choosing a bug shows its description. Only v3 is fresh; the others were seen when the templates were written.
- [ ] Radio "Run": selected test / approved tests / all tests. "approved tests" with none approved: yellow "No approved tests yet ...".
- [ ] "all tests", no bug, "Run on simulator": green "All tests pass on the clean simulator.", "Passed 18/18", all rows PASS.
- [ ] Pick `[in-sample] write_ignores_value_range`, run: green "Bug caught by 1 test.", "Passed 17/18", row `req_005__tpl_write_oor_0100` FAIL, failure `step 3: expected ['7f2e31'], got ['6e0100']`. The expander "FAIL req_005__tpl_write_oor_0100" shows the first failing step: request `2E 01 00 65`, expected `7F 2E 31 (requestOutOfRange)`, actual `6E 01 00 (positive)`.
- [ ] A bug none of the tests catch shows yellow "Bug not caught." (that is a result, not an error).
- [ ] Credit is given only to tests that also pass on the clean simulator (the page runs both); tests failing on the clean simulator are mentioned and not counted.

## 4. Tab "Export"

- [ ] Before generating: "Generate tests first". After: checkbox "Approved tests only", "Download pytest file" and "Download CAPL template (unverified — never run in CANoe)". The caption quotes the CAPL banner. The pytest file runs with `$env:UDS_REPO_ROOT = "C:\Users\pasar\Desktop\tata_tech"; python -m pytest generated_tests_test.py -q` (18 passed for REQ-005). The CAPL file has never been compiled or run in CANoe: do not call it working CAPL.

## 5. Tab "Results"

- [ ] Six cards, each with a "run <date> · git <hash>" line: 1 Correctness (simulator vs rules 5000/5000, gold 60/60), 2 Bug detection on the fresh v3 set (mock 10/15, ollama 9/15; requirement-driven only 4/15 and 2/15), 3 Understanding mock vs Ollama (natural v3 parsed F1 0.407 / 0.609), 4 Q&A accuracy (90.5% both), 5 Coverage, 6 Latency (mock 0.22 s, ollama 19.36 s per requirement).
- [ ] Below: collapsed expanders (Run provenance, Headline tables, Noise checks and freeze hashes, Mock vs Ollama side by side, Per-bug tables, Per-requirement tables, Before / after Part C, History (historical), Full report JSON). History is labelled historical. (Streamlit runs expander bodies on every rerun; the report file is read once and cached by modification time.)
- [ ] Missing report (`$env:UDS_EVAL_REPORT = "C:\nope.json"` before starting): blue "No evaluation report at ...", no traceback. A report without some keys: cards say "Not in this report." and the page still renders.

## What to report back

For each item: pass, or what you saw. Note any traceback, any label that differs from this list, and anything that needed more than one click.
