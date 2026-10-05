# UI checklist (manual click-through)

Run `streamlit run uds_assistant/ui/streamlit_app.py` with Ollama running, then tick each line.

## Sidebar and page

- [ ] Title "UDS Diagnostics & Automated Test Generation Assistant"; four tabs: Ask, Generate & Review, Run & Export, Results.
- [ ] With `OLLAMA_HOST` set to a non-local host the sidebar shows a red warning that data would leave this machine.
- [ ] Sidebar: green "Ollama reachable at http://localhost:11434"; the banner "Synthetic ECU spec — human review required before real-hardware use." appears once.
- [ ] Stop Ollama and reload: the sidebar line turns red ("Ollama not reachable ... Start Ollama and pull qwen2.5:3b-instruct-q4_K_M."), and Ask and Generate & Review show the same red message instead of their buttons. The page does not crash.

## Ask

- [ ] Pick an example question and click **Ask**: answer, confidence badge with a reason, expandable citations (layer, source, quote).
- [ ] "What does DID 0x0999 contain?" gives a warning "Not found in the approved sources." and low confidence.
- [ ] **Check a raw request** (expander): `2E 01 00 11` in extended session with nothing unlocked shows structurally valid, expected `7F 2E 33 (securityAccessDenied)`, the reason (step 6c), citations; with level 0x01 unlocked it shows `6E 01 00`; `99 99` shows structurally invalid; `zz` shows a hex error.

## Generate & Review

- [ ] "Load example" fills the text and id; **Generate tests** shows a green "Generated N test(s), dropped M. run_id=..." and a table (id, category, confidence, review status).
- [ ] Selecting a test shows its preconditions and pass criteria, then decoded steps (hex request and the readable line), target chips (written / inferred), the explanation and citations.
- [ ] **Bulk approve all validated tests** approves every validated test only when clicked and writes one log line per test.
- [ ] Approve, Reject and Add comment each show a message; the review status column and the log lines under the buttons update.

## Run & Export

- [ ] With no tests generated, the tab says to generate tests first.
- [ ] The scope radio defaults to "Approved tests only" and "Include unreviewed tests (demo only)" is unchecked. With nothing approved, run and export show the "No approved tests" message. Approve a test (or bulk approve), then a "no bug" run: "All tests pass on the clean simulator."; with `accepts_any_key` after REQ-005: "Bug caught by N test(s)." and an expandable failing step (request, expected, actual).
- [ ] Ticking the demo override shows an orange warning and runs/exports all tests.
- [ ] Both downloads work (pytest file, CAPL template with the "unverified" label); the export follows the same approved-only scope.
- [ ] A coverage table (items with zero tests highlighted red) and a **Download coverage report (Markdown)** button appear under the export.

## Results

- [ ] Eight cards from `outputs/eval_report.json`: generation accuracy, coverage, reuse rate, defect detection, requirement understanding, Q&A accuracy, tool time per requirement, correctness checks; run date, git hash and model on top; missed blind-set bugs listed.
- [ ] Without `outputs/eval_report.json` the tab shows an info message with the command to create it.
