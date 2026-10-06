# Demo script (6 to 7 minutes)

Before you start: Ollama running with `qwen2.5:3b-instruct-q4_K_M` (see [MODEL_SETUP.md](../MODEL_SETUP.md)),
`outputs/eval_report.json` present (run `python -m uds_assistant.eval.run_eval` once), and the UI open:

```bash
python -m uds_assistant.api        # web UI at http://localhost:8000
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
   **Generate tests** (about 25 s in the 2026-10-05 run: parse, retrieve, plan, instantiate, validate, explain).
2. Walk the table (id, category, confidence, review status). Select the security lockout test: show the decoded
   steps (`27 02 ... -> 7F 27 35 (invalidKey)`), the "written / inferred" target chips, the explanation and the citations.
3. Click **Approve** on one test and **Reject** on another; say both are stored in the audit database.

## 3. Run & Export (about 1.5 minutes)

1. Choose "no bug", **Run**: all tests pass on the clean simulator.
2. Choose bug `accepts_any_key`, keep "all tests", **Run**: green "Bug caught by N test(s)" (1 test in the 2026-10-05 run; the planner's choice varies); open the failing test and show the first
   failing step (expected `7F 27 35`, actual `67 02`).
3. Download the pytest file (and mention the CAPL template: **unverified**, never run in CANoe).

## 4. Import an existing suite and compare (about 1.5 minutes)

1. Open **Import & Compare**, click **Use the example suite** (`data/imports/legacy_bcm_regression.yaml`, 14 hand-written
   tests) and **Import and validate**. Show the table: 14 accepted, each "matches the rules engine"; the note says the tests
   are not AI-generated and are only *validated*. Optionally import `legacy_bcm_with_errors.yaml` (choose the file) to show
   2 accepted, 2 rules-engine mismatches (the step and both byte strings) and 4 invalid entries with reasons.
2. Click **Review the accepted tests**: each shows an "imported" badge and an Import provenance line (suite, file, id,
   SHA-256). Approve one. On **Run & Export**, run it (clean simulator passes); with nothing approved the run is refused.
3. Back on **Import & Compare**, pick the imported suite and a generated run (the REQ-005 run from step 2) or "All
   generated runs", click **Compare coverage**. Read the baseline row (for example 0/3 routines), the newly covered list,
   the items only the imported suite covers (the P2 response-time test) and what is still uncovered. Click **Download
   comparison report**.

## 5. Results (about 1 minute)

Open [RESULTS.md](RESULTS.md) (the same eight sections plus section 9, the imported-suite baseline): generation accuracy,
coverage, reuse rate, defect detection on the blind v3 bug set, requirement understanding, Q&A, tool time per
requirement, correctness checks. Point at the missed bugs and at "manual time: owner to fill". Close with the limitations: synthetic spec, one 3B model, small samples,
CAPL unverified, human review required before real-hardware use.

## Fallback if something fails

- Ollama red in the sidebar: start it and pull the model; the tabs say "Start Ollama and pull qwen2.5:3b-instruct-q4_K_M".
- Slow first request: the model and the BGE embeddings load once; repeat the click.
- No time for the UI: `python scripts/demo.py` runs the same story in the terminal (about 30 s in the 2026-10-05 run).
