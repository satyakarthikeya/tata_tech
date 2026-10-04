# UI checklist (manual click-through)

Run `streamlit run uds_assistant/ui/streamlit_app.py` with Ollama running, then tick each line.

## Sidebar and page

- [ ] Title "UDS Diagnostics & Automated Test Generation Assistant"; four tabs: Ask, Generate & Review, Run & Export, Results.
- [ ] Sidebar: green "Ollama reachable at http://localhost:11434"; the banner "Synthetic ECU spec — human review required before real-hardware use." appears once.
- [ ] Stop Ollama and reload: the sidebar line turns red ("Ollama not reachable ... Start Ollama and pull qwen2.5:3b-instruct-q4_K_M."), and Ask and Generate & Review show the same red message instead of their buttons. The page does not crash.

## Ask

- [ ] Pick an example question and click **Ask**: answer, confidence badge with a reason, expandable citations (layer, source, quote).
- [ ] "What does DID 0x0999 contain?" gives a warning "Not found in the approved sources." and low confidence.

## Generate & Review

- [ ] "Load example" fills the text and id; **Generate tests** shows a green "Generated N test(s), dropped M. run_id=..." and a table (id, category, confidence, review status).
- [ ] Selecting a test shows decoded steps (hex request and the readable line), target chips (written / inferred), the explanation and citations.
- [ ] Approve, Reject and Add comment each show a message; the review status column and the log lines under the buttons update.

## Run & Export

- [ ] With no tests generated, the tab says to generate tests first.
- [ ] The scope radio defaults to "all tests". "no bug" run: "All tests pass on the clean simulator."; with `accepts_any_key` after REQ-005: "Bug caught by N test(s)." and an expandable failing step (request, expected, actual).
- [ ] "approved tests" scope with nothing approved warns instead of running.
- [ ] Both downloads work (pytest file, CAPL template with the "unverified" label); "Approved tests only" filters the export.

## Results

- [ ] Eight cards from `outputs/eval_report.json`: generation accuracy, coverage, reuse rate, defect detection, requirement understanding, Q&A accuracy, tool time per requirement, correctness checks; run date, git hash and model on top; missed blind-set bugs listed.
- [ ] Without `outputs/eval_report.json` the tab shows an info message with the command to create it.
