# Demo script (5 minutes)

Before you start: Ollama running with `qwen2.5:3b-instruct-q4_K_M` (see [MODEL_SETUP.md](../MODEL_SETUP.md)),
`outputs/eval_report.json` present (run `python -m uds_assistant.eval.run_eval` once), and the UI open:

```bash
streamlit run uds_assistant/ui/streamlit_app.py
```

Say up front: **the ECU spec is synthetic, and the LLM never writes a byte; the rules engine does.** The sidebar shows
the same banner and a green Ollama status.

## 1. Ask (about 1 minute)

1. Pick "What is the length of DID 0xF190?" from the examples and click **Ask**. Show the answer, the confidence badge
   (high: the fact was looked up in the parsed spec) and the expanded citation (layer, source, exact quote).
2. Ask "What does DID 0x0999 contain?" Show **"Not found in the approved sources."** with low confidence: the
   assistant refuses instead of guessing.

## 2. Generate & Review (about 1.5 minutes)

1. Load the REQ-005 example ("writing DID 0x0100 shall require extended session and security level 0x01") and click
   **Generate tests** (about 25 s: parse, retrieve, plan, instantiate, validate, explain).
2. Walk the table (id, category, confidence, review status). Select the security lockout test: show the decoded
   steps (`27 02 ... -> 7F 27 35 (invalidKey)`), the "written / inferred" target chips, the explanation and the citations.
3. Click **Approve** on one test and **Reject** on another; say both are stored in the audit database.

## 3. Run & Export (about 1.5 minutes)

1. Choose "no bug", **Run**: all tests pass on the clean simulator.
2. Choose bug `accepts_any_key`, keep "all tests", **Run**: green "Bug caught by 1 test"; open the failing test and show the first
   failing step (expected `7F 27 35`, actual `67 02`).
3. Download the pytest file (and mention the CAPL template: **unverified**, never run in CANoe).

## 4. Results (about 1 minute)

Open the **Results** tab: the eight sections as cards (generation accuracy, coverage, reuse rate, defect detection on
the blind v3 bug set, requirement understanding, Q&A, tool time per requirement, correctness checks). Point at the missed
bugs and at "manual time: owner to fill". Close with the limitations: synthetic spec, one 3B model, small samples,
CAPL unverified, human review required before real-hardware use.

## Fallback if something fails

- Ollama red in the sidebar: start it and pull the model; the tabs say "Start Ollama and pull qwen2.5:3b-instruct-q4_K_M".
- Slow first request: the model and the BGE embeddings load once; repeat the click.
- No time for the UI: `python scripts/demo.py` runs the same story in the terminal in about 30 s.
