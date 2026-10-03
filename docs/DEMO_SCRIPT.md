# Live demo script (about 8 minutes mock-only; about 10 minutes with the ollama segment)

Audience: Tata Technologies reviewers. Steps 1 to 7 run offline in a terminal with the mock LLM (a deterministic keyword stand-in for a language model): no internet, no GPU, no real LLM. Step 6b is an optional ~2 minute segment with the real local model (Ollama, Qwen2.5-3B); it needs a GPU and Ollama running, and has a pre-recorded fallback if either is unavailable.

Numbers: the figures quoted below are the real ones from `outputs\eval_report.md` (report version 3, generated 2026-10-03, template set v3) and `outputs\partC\before_after.md`. They are for orientation: during the session read them from the screen (the script's section [5] prints them from `outputs\eval_report.json`), and if the report has been regenerated since, the screen wins. The headline is the FRESH v2 numbers, whatever they are, including the unfavourable ones: held-out v2 detection is 2/15 for the generated suite in both modes. The test counts and bytes in the expected outputs below come from deterministic mock runs of the code and do not depend on the evaluation.

Setup before the session (do once, 2 minutes before):

```powershell
cd C:\Users\pasar\Desktop\tata_tech
python scripts/demo.py --offline > $null; echo "rc=$LASTEXITCODE"   # warm-up, should print rc=0
```

Terminal font large; two windows ready (one at the repo root, one with `outputs\eval_report.md` open in an editor; optionally a third with `outputs\partC\before_after.md`).

Timings below are measured on the build machine: the whole `python scripts/demo.py` takes about 2 seconds (2.3 s in the last run; `--offline` 1.5 s); `--full-eval` takes about 65 seconds (mock-only, now that it also runs the v2 sets and the determinism check).

| # | Step | Time |
|---|---|---|
| 1 | Frame the problem | 0:45 |
| 2 | Generate tests for one requirement | 1:30 |
| 3 | Read one test in bytes | 1:00 |
| 4 | Run on the clean simulator | 0:30 |
| 5 | Toggle a bug, watch a test catch it | 1:30 |
| 5b | A fresh held-out v2 bug | 1:00 |
| 6 | Show the honest eval numbers (v2 headline) | 1:30 |
| 6b | Optional: ollama mode, mock vs ollama | 2:00 |
| 7 | Close (and optional extras) | 0:30 |

Mock-only total: 8:15. With 6b: about 10:15.

---

## 1. Frame the problem (0:45)

**Say:** "Car ECUs speak UDS, a request/response protocol. Engineers write requirements like 'writing the brightness value needs extended session and security level 1', then hand-write tests. This assistant turns the requirement into cited, runnable tests. The rule: the language model only does language. Every byte comes from code, and a rules engine decides what the correct answer is. The ECU here is a synthetic, fictional Body Control Module that I wrote, not a real OEM spec."

No command. Optionally show `docs\ARCHITECTURE.md` diagram.

## 2. Generate tests for one requirement (1:30)

```powershell
python scripts/demo.py
```

The script prints five numbered sections. Pause on section [2].

**Expected output (real run):**

```
[2] Pick a requirement and generate tests (mock LLM)
REQ-005: Writing the interior lighting brightness DID (0x0100) shall require extended session and security level 0x01.
Engine=langgraph llm=mock plan attempts=1 dropped=0
Parsed: services=['0x27', '0x2E'] dids=['0x0100'] ...
18 tests kept. Categories: {'negative': 6, 'positive': 2, 'security': 5, 'session': 2, 'timing': 3}
  req_005__tpl_write_secured_0100                positive  write_did_secured_positive
  req_005__tpl_write_nosec_0100                  negative  write_did_without_security
  req_005__tpl_write_oor_0100                    negative  write_did_out_of_range
  ...
  req_005__tpl_seed_while_unlocked_01            security  seed_request_while_unlocked
```

**Say:** "The agent parsed the requirement, retrieved evidence from the spec, picked 18 test templates from a library of 27, built them, and re-checked every one against the oracle. 18 kept, 0 dropped, no retry needed. Some of those templates are new in the last round of work: for example one that writes a value and reads it back after an S3 timeout or an ECU reset."

**Fallback:** if the pipeline errors (for example a LangGraph import problem), run `python scripts/demo.py --offline`. It loads the pre-generated tests from `outputs\generated_tests.yaml` instead of running the pipeline, and everything after section [2] is identical. To force the plain engine: `$env:UDS_AGENT_ENGINE="plain"; python scripts/demo.py`.

Want another requirement or free text? `python scripts/demo.py --req REQ-010` or `python scripts/demo.py --text "The tester shall be able to read the VIN."`

## 3. Read one test in bytes (1:00)

Scroll to section [4] "One test, steps in hex".

```
Test req_005__tpl_write_oor_0100  [negative]  template=write_did_out_of_range
  step 0: send 1003         expect 5003003201F4   # Switch to session 0x3.
  step 1: send 2701         expect 6701950677E8   # Request seed for level 0x1.
  step 2: send 27029A068F73 expect 6702           # Send computed key for level 0x1.
  step 3: send 2E010065     expect 7F2E31         # Write out-of-range value 101 -> expect NRC 0x31.
  cite: data/bcm_spec.yaml :: did:interior_lighting_brightness_pct
```

**Say:** "Four steps: enter extended session, ask for a seed, send the key, then try to write 101 into a field that only allows 0 to 100. The expected answer is `7F 2E 31`: 7F means refusal, 2E is the write service, 31 means value out of range. The citation points at the exact spec entry."

**Fallback:** none needed (static print).

## 4. Run on the clean simulator (0:30)

Scroll to section [3] (it prints before the test detail).

```
Clean simulator: 18/18 tests pass
```

**Say:** "The tests run on a second, separately written ECU simulator. All 18 pass on the correct simulator. Passing here shows the oracle and simulator agree, which is necessary but not sufficient, so the next step matters."

## 5. Toggle a bug and watch a test catch it (1:30)

Section [4] header: `Inject bug 'write_ignores_value_range' and re-run`. The script now also prints which bug set the bug belongs to (`Bug set: in-sample (the templates were tuned on these)`).

```
Bug set: in-sample (the templates were tuned on these)
Bug: Write ignores value range
With bug: 17/18 pass; 1 FAIL
Failing tests: req_005__tpl_write_oor_0100

First failing step on the buggy simulator:
  req_005__tpl_write_oor_0100: FAIL at step 3
    request  : 2E010065
    expected : ['7F2E31']
    actual   : ['6E0100']
```

**Say:** "I switch on a seeded fault: the ECU forgets to check the value range. The same test now fails at step 3: expected a refusal `7F 2E 31`, but the buggy ECU said `6E 01 00`, which is 'write OK'. It wrote 101 into a 0 to 100 field. Only 1 of 18 tests notices this bug. A test catches a bug only if it sends the stimulus that exposes it. And note the label: this is an in-sample bug, one the templates were tuned on, so catching it proves little on its own."

Try a different bug live (each takes about 3 seconds):

```powershell
python scripts/demo.py --req REQ-010 --bug accepts_any_key
```

Expected: two failing tests (`req_010__tpl_security_lockout_01` and its reset variant); the failing step expects `7F2735` (invalid key) but the actual is `6702` (unlocked). Bug ids from all three sets are listed by `python scripts/demo.py --bug nonsense`.

**Fallback:** if a bug is not caught for the chosen requirement the script says so honestly ("NOT caught by the tests for this requirement"). Go back to the default bug.

## 5b. A fresh held-out v2 bug (1:00)

These bugs were written by a separate agent after the templates were frozen, and it could not see the templates, gold tests or evaluation code. That is the only kind of bug that tells you something about the test generator.

```powershell
python scripts/demo.py --req REQ-006 --bug write_range_upper_bound_exclusive
```

Look at section [4]:

```
Bug set: held-out v2 (FRESH: written blind after the Part C freeze)
Bug: Write value range treats the maximum as exclusive
With bug: 16/18 pass; 2 FAIL
Failing tests: req_006__tpl_write_retained_s3_0101, req_006__tpl_write_retained_reset_0101
  ...
  req_006__tpl_write_retained_s3_0101: FAIL at step 3
    request  : 2E01010F
    expected : ['6E0101']
    actual   : ['7F2E31']
```

**Say:** "This bug treats the top of the allowed range as out of range. It was written blind. Here two of the new write-and-read-back tests catch it, because they write a value at the top of the range. Honestly, that is partly luck of the stimulus, not a test aimed at this bug: no template mentions any bug. Now the opposite case." Then run a v2 bug that the suite for this requirement does not catch, for example the default requirement:

```powershell
python scripts/demo.py --bug s3_restart_skipped_on_negative_response
```

Expected: `This bug is NOT caught by the tests for this requirement`. **Say:** "Most fresh bugs are not caught by the tests for one requirement. How many are caught across all fifteen requirements is the headline in the report, next."

**Fallback:** none needed; if the exact lines differ the script prints the real result, so read what is on screen.

## 6. Show the honest eval numbers (1:30)

Section [5] prints the headline from `outputs\eval_report.json` (it does not re-run the evaluation). With the current version-3 report it prints the fresh v2 rows first, then the seen rows:

**Expected output (real run):**

```
Report version 3. Modes in this report: mock, ollama
Simulator <-> rules agreement : 5000/5000
Gold tests on clean simulator : 60/60
udsoncan virtual-CAN sequence : PASS
Part C freeze: all recorded hashes match and are clean = True

FRESH v2 headline (written blind after the freeze; nothing was tuned on it):
HELD-OUT v2 bug detection (15 bugs; generated suite is the headline):
  mock    generated 2/15 (13.3%), gold 5/15, union 5/15
  ollama  generated 2/15 (13.3%), gold 5/15, union 5/15
Natural v2 requirement understanding (test2, n=16):
  mock    parsed exact 0/16, P/R/F1 1.000/0.225/0.367
  ollama  parsed exact 4/16, P/R/F1 0.565/0.796/0.661
  noise check mock: deterministic, re-run identical = True
  noise check ollama: 3 runs, parsed F1 mean 0.661 (min-max 0.661 to 0.661)

SEEN / tuned-on rows (not independent evidence):
HELD-OUT v1 bug detection (12 bugs; SEEN: templates designed against these misses):
  mock    generated 10/12 (83.3%), gold 3/12, union 11/12
  ollama  generated 5/12 (41.7%), gold 3/12, union 6/12
Natural v1 test split (n=12; SEEN):
  mock    parsed exact 5/12, P/R/F1 0.933/0.560/0.700
  ollama  parsed exact 3/12, P/R/F1 0.500/0.840/0.627
Latency per requirement (mean / p95): mock 0.27 s / 0.46 s, ollama 21.4 s / 28.5 s
Before/after table: outputs\partC\before_after.md
Read the table above: the v2 rows are the independent evidence; see docs/RESULTS.md for the interpretation.
Honest note: in-sample and v1 held-out numbers are optimistic (seen); trust the fresh v2 rows.

Demo finished in 2.3 s.
```

If `outputs\eval_report.json` is an older (version 2) report the script prints `Fresh v2 headline: n/a - this report predates Part C` and the old held-out and test-split rows instead. If a mode was not run, its line says `not run: ...`. Nothing is hard-coded in the script, so what you read is what is in the file.

Then show the full report and, if it exists, the before/after table:

```powershell
Get-Content outputs\eval_report.md -TotalCount 60
Get-Content outputs\partC\before_after.md
```

**Say:** "Three independent-ish checks say the oracle and simulator are consistent: 5000 of 5000 random requests agree, all 60 hand-written tests pass, and a third-party client completes a real exchange. The numbers I want you to focus on are the fresh v2 rows: 15 bugs and 16 requirements written blind after I froze the templates and prompts. The generated tests catch 2 of the 15 fresh bugs, in both modes. The hand-written gold tests catch 5, and together they catch 5. That is low, and I am showing it rather than the 25 of 26 in-sample number. On requirement understanding the real model beats my keyword mock on fresh phrasing: parsed F1 0.661 against 0.367, and it covers 74% of the required test categories against 48%. But it invents targets: precision 0.565 with 30 false positives, mostly services, while the mock is at 1.000 precision and finds under a quarter of the targets (recall 0.225). My precision fix did not work, because the grounding check does not cover services. The v1 rows and the in-sample row are labelled seen or tuned on: they went up after the Part C work (the mock from 3 to 10 of 12 on v1), but I designed the new templates against the v1 misses, so that rise is expected and is not evidence. 11 of the 13 missed v2 bugs have no generated test that applies the stimulus, and 2 apply it but never check the response that exposes the bug; each has a stated reason in the report. The before/after table shows what changed from the pre-Part C report, with the comparability caveats under it. The freeze line says the frozen code and data were unchanged when these numbers were produced."

**Optional live re-run (about 65 s, only if the room has time):**

```powershell
python scripts/demo.py --full-eval
```

It is a mock-only run. It writes to a temp folder (does not change `outputs\`) and ends with a one-line summary beginning `mode=mock tests=206 HELD-OUT v2 (fresh) bug detection: generated 2/15, gold 5/15, union 5/15; natural v2 (fresh) understanding: parsed exact 0/16, ...`, plus the freeze line.

**Fallback:** the file `outputs\eval_report.md` is pre-generated; just open it. Never wait on `--full-eval` live unless there is slack.

## 6b. Optional: ollama mode, mock vs ollama (2:00)

Only do this if a GPU is free and you want to show the real model. The tests are still built from templates; the model only parses, plans and explains.

**Start Ollama (before the session, not live).** Ollama must already be installed with the model pulled (`ollama pull qwen2.5:3b-instruct-q4_K_M`, see `MODEL_SETUP.md`). The 4 GB GPU settings are Ollama *server* variables and only apply if set before the server starts:

```powershell
setx OLLAMA_FLASH_ATTENTION 1; setx OLLAMA_KV_CACHE_TYPE q8_0; setx OLLAMA_MAX_LOADED_MODELS 1
# restart the Ollama tray app / server from a fresh shell, then check:
curl.exe http://localhost:11434/api/tags
```

App-side environment variables (all optional; defaults shown):

```powershell
$env:OLLAMA_HOST = "http://localhost:11434"
$env:OLLAMA_MODEL = "qwen2.5:3b-instruct-q4_K_M"
$env:OLLAMA_NUM_CTX = "4096"        # the evaluated setting; do not raise on a 4 GB card
$env:OLLAMA_KEEP_ALIVE = "10m"      # keeps the model loaded between requirements
```

**Run.** Ollama needs tens of seconds per requirement, and the first call also loads the model, so warm it up once before the session:

```powershell
python scripts/demo.py --llm ollama --req REQ-010
```

`scripts/demo.py --llm ollama` uses the same `get_llm` factory as the app (the equivalent of `LLM_MODE=ollama`; the default stays mock). If Ollama is unreachable the script prints `WARNING: ... falling back to the deterministic mock LLM` and `continuing with the deterministic mock LLM, NOT ollama`, and the `Engine=... llm=mock` line shows what actually ran. Say so out loud if that happens. Section [5] already prints both modes' recorded numbers. (Note: the ollama suite is smaller and may not catch the default bug; the script says so honestly.)

**Say (while it runs):** "This is the real 3B model on a 4 GB laptop GPU. It reads the requirement, picks templates from a ranked shortlist, and writes the explanations in one batched call. Bytes still come only from templates, so even a 3B model cannot put a wrong byte in a test. In the recorded run it took 21.4 s per requirement on average (p95 28.5 s), against 0.27 s for the mock; one full run of all 83 pipeline runs, including the three noise runs, took about 31 minutes."

**Say (once it finishes; read the numbers from the report, not from memory):** "We ran both on the same requirements, and ollama three times on the fresh natural-v2 set so you can see the run-to-run spread. On the fresh set the model finds more of the right targets (recall 0.796 against 0.225, parsed F1 0.661 against 0.367) and its tests cover more categories (74.0% against 48.0%; mean over three runs 75.3%, range 74.0 to 76.0). The parsed numbers were identical in all three runs; the variation is in planning and explaining (precondition recall 77.8% to 85.2%). Part B showed this model finding more of the right identifiers but also inventing some. The Part C fixes target that: ids copied from prompt examples are removed, a grounding check drops DIDs, routines and DTCs the text does not support, and template ids are normalised. That did not fix precision: it is 0.565 with 30 false positives, 25 of them services, which the grounding check does not cover. The normalisation never fired, and rejected planner choices went from 10 to 15 on the old requirements and 12 on the new ones. What did work is the batched explain step: one model call per requirement instead of one per test, and mean latency from 30.8 s down to 21.4 s. The model path is safe either way: the validator rejects bad template choices and byte provenance holds for every generated test, 418 of 418 for ollama. Detection of the fresh bugs is 2 of 15 in both modes; the model does not change what the templates can do."

**MOCK FALLBACK (Ollama slow, down, or the GPU is busy).** Do not wait. Use the recorded results and say they are recorded:

1. Show the pre-recorded 5-requirement smoke run: `Get-Content outputs\ollama_smoke.json -TotalCount 60` (real model, num_ctx 4096). Be honest that this is the early smoke run from before the plan-context fix and the Part C changes; the final numbers are in the report.
2. Show the side-by-side table in the report: open `outputs\eval_report.md` at "Mock vs Ollama - side by side", or run `python scripts/demo.py --offline`, whose section [5] prints both modes.
3. Optionally open the Streamlit UI (`streamlit run uds_assistant/ui/streamlit_app.py`), section 4, which renders the v2 headline, the noise check, the before/after table and the comparison. The manual click-through is in `docs\UI_CHECKLIST.md`.

## 7. Close (0:30)

**Say:** "To summarize: language model for language, code for correctness; two implementations that cross-check; and honest numbers, meaning the fresh v2 rows, written blind after a frozen code state that the report verifies. Known limitations: synthetic spec, small test sets (15 bugs, 16 requirements), five documented disagreements with AUTOSAR's specification that I did not change (four others I fixed and re-verified), and CAPL exports that were never run in CANoe."

## Extras (only if asked)

- **API:** `python -m uds_assistant.api` then open <http://127.0.0.1:8000/docs> (endpoints: `/generate`, `/run`, `/eval`, `/export`, `/bugs`, `/runs`). Needs fastapi/uvicorn installed (they are in the project dependencies).
- **Streamlit UI:** `streamlit run uds_assistant/ui/streamlit_app.py` (needs `pip install -e ".[ui]"`). Section 4 shows the freeze status, the fresh v2 headline, the noise check, the before/after table and the mock vs ollama comparison, read from `outputs\eval_report.json` and `outputs\partC\before_after.md`. Headless AppTest runs exist; the human click-through is the checklist in `docs\UI_CHECKLIST.md`, so keep the UI as an extra, not the main demo, until the owner has done it.
- **Exported tests:** `outputs\exports\generated_tests_test.py` (pytest; the eval run reports how many passed) and `*.can` (CAPL, unverified).

## Likely curveballs (short answers)

- *Why mock as the default?* Reproducible, offline, much faster, and the LLM cannot affect bytes either way. On fresh requirement phrasing the real model has better recall but poor precision (0.565 against 1.000), so it is a trade-off, not a clear win.
- *Did you try a real model?* Yes: Qwen2.5-3B (Q4_K_M) via Ollama on an RTX 3050 4 GB; the recorded comparison is in `outputs\eval_report.md`.
- *Is the ollama gap just noise?* The noise-check block in the report lists the three ollama runs: parsed F1 was 0.661 in all three (range 0.661 to 0.661), exercised F1 0.583 to 0.611. The gap to the mock (0.661 against 0.367) is far outside that. Part B measured about +-0.05 on parsed F1 on the dev split; three runs is a small sample.
- *Why did the v1 numbers go up, and is that an improvement?* The Part C templates were designed against the v1 misses, so v1 is "seen". The improvement claim rests only on the fresh v2 rows.
- *Why fix four SWS disagreements and not nine?* Four were high confidence (an explicit normative requirement contradicts us); the rest are order-of-checks guesses, no observable effect, or a configuration choice. See `docs\SWS_DISAGREEMENTS.md`.
- *Is the spec real?* No, synthetic by design.
