# Live demo script (about 7 minutes mock-only; about 9 minutes with the ollama segment)

Audience: Tata Technologies reviewers. Steps 1 to 7 run offline in a terminal with the mock LLM (a deterministic keyword stand-in for a language model): no internet, no GPU, no real LLM. Step 6b is an optional ~2 minute segment with the real local model (Ollama, Qwen2.5-3B); it needs a GPU and Ollama running, and has a pre-recorded fallback if either is unavailable.

Setup before the session (do once, 2 minutes before):

```powershell
cd C:\Users\pasar\Desktop\tata_tech
python scripts/demo.py --offline > $null; echo "rc=$LASTEXITCODE"   # warm-up, should print rc=0
```

Terminal font large; two windows ready (one at the repo root, one with `outputs\eval_report.md` open in an editor).

Timings below are measured on the build machine: the whole `python scripts/demo.py` takes about 2 to 4 seconds; `--full-eval` takes about 38 seconds.

| # | Step | Time |
|---|---|---|
| 1 | Frame the problem | 0:45 |
| 2 | Generate tests for one requirement | 1:30 |
| 3 | Read one test in bytes | 1:00 |
| 4 | Run on the clean simulator | 0:30 |
| 5 | Toggle a bug, watch a test catch it | 1:30 |
| 6 | Show the honest eval numbers | 1:30 |
| 6b | Optional: ollama mode, mock vs ollama | 2:00 |
| 7 | Close (and optional extras) | 0:30 |

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
14 tests kept. Categories: {'negative': 6, 'positive': 1, 'security': 3, 'session': 2, 'timing': 2}
  req_005__tpl_write_secured_0100     positive  write_did_secured_positive
  req_005__tpl_write_oor_0100         negative  write_did_out_of_range
  ...
```

**Say:** "The agent parsed the requirement, retrieved evidence from the spec, picked 14 test templates, built them, and re-checked every one against the oracle. 14 kept, 0 dropped, no retry needed."

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
Clean simulator: 14/14 tests pass
```

**Say:** "The tests run on a second, separately written ECU simulator. All 14 pass on the correct simulator. Passing here shows the oracle and simulator agree, which is necessary but not sufficient, so the next step matters."

## 5. Toggle a bug and watch a test catch it (1:30)

Section [4] header: `Inject bug 'write_ignores_value_range' and re-run`.

```
Bug: Write ignores value range
With bug: 13/14 pass; 1 FAIL
Failing tests: req_005__tpl_write_oor_0100

First failing step on the buggy simulator:
  req_005__tpl_write_oor_0100: FAIL at step 3
    request  : 2E010065
    expected : ['7F2E31']
    actual   : ['6E0100']
```

**Say:** "I switch on a seeded fault: the ECU forgets to check the value range. The same test now fails at step 3: expected a refusal `7F 2E 31`, but the buggy ECU said `6E 01 00`, which is 'write OK'. It wrote 101 into a 0 to 100 field. Only 1 of 14 tests notices this bug. A test catches a bug only if it sends the stimulus that exposes it."

Try a different bug live (each takes about 3 seconds):

```powershell
python scripts/demo.py --req REQ-010 --bug accepts_any_key
```

Expected: `With bug: 5/6 pass; 1 FAIL`, failing step expects `7F2735` (invalid key) but actual is `6702` (unlocked).
Bug ids are listed by `python scripts/demo.py --bug nonsense`.

**Fallback:** if a bug is not caught for the chosen requirement the script says so honestly ("NOT caught by the tests for this requirement"). Go back to the default bug.

## 6. Show the honest eval numbers (1:30)

Section [5] prints the headline for both modes from `outputs\eval_report.json` (it does not re-run the evaluation):

```
Simulator <-> rules agreement : 5000/5000
Gold tests on clean simulator : 60/60
udsoncan virtual-CAN sequence : PASS
HELD-OUT bug detection (12 bugs):
  mock    generated 3/12 (25.0%), gold 3/12, union 5/12
  ollama  generated 3/12 (25.0%), gold 3/12, union 5/12
Requirement understanding (test split n=12):
  mock    parsed exact 5/12, P/R/F1 0.933/0.560/0.700
  ollama  parsed exact 4/12, P/R/F1 0.512/0.880/0.647
```

Then show the full report:

```powershell
Get-Content outputs\eval_report.md -TotalCount 40
```

**Say:** "Three independent-ish checks say the oracle and simulator are consistent. The number I want you to focus on is the held-out one: 12 bugs written by a separate agent that never saw my templates. The generated tests catch 3 of 12. On my own 26 bugs we got 25 of 26, but I tuned the templates after seeing those, so that number is optimistic. Each miss has a stated reason in the report, for example no test writes a 16-bit value and reads it back. The mock LLM is also weak at understanding free-form requirements: 5 of 12 on the test split. We also ran the real local model; that is the next segment."

**Optional live re-run (38 s, only if the room has time):**

```powershell
python scripts/demo.py --full-eval
```

It is a mock-only run. It writes to a temp folder (does not change `outputs\`) and ends with `HELD-OUT bug detection: generated 3/12, gold 3/12, union 5/12`.

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

**Run.** Ollama needs about 30 s per requirement, and the first call also loads the model, so warm it up once before the session:

```powershell
python scripts/demo.py --llm ollama --req REQ-010
```

`scripts/demo.py --llm ollama` uses the same `get_llm` factory as the app (the equivalent of `LLM_MODE=ollama`; the default stays mock). If Ollama is unreachable the script prints `WARNING: ... falling back to the deterministic mock LLM` and `continuing with the deterministic mock LLM, NOT ollama`, and the `Engine=... llm=mock` line shows what actually ran. Say so out loud if that happens. Section [5] already prints both modes' recorded numbers. (Note: the ollama suite is smaller and may not catch the default bug; the script says so honestly.)

**Say (while it runs, about 30 s):** "This is the real 3B model on a 4 GB laptop GPU. It reads the requirement, picks templates from a shortlist, and writes the explanations. Bytes still come only from templates, so even a 3B model cannot put a wrong byte in a test. It takes about 30 seconds per requirement, against a quarter of a second for the mock."

**Say (once it finishes, about 60 s; use the recorded numbers):** "We ran both on the same 35 requirements. On the held-out test split the 3B model did not beat the mock on any headline metric. It finds more of the right identifiers (recall 0.880 against 0.560) but it also invents identifiers, so precision drops from 0.933 to 0.512. Held-out bug detection is 3 of 12 for both, the same three bugs, because both use the same templates. It is about 120 times slower. So the mock stays the default. The model path is safe, because the validator rejected all 10 bad template choices and byte provenance held for all 158 tests, but it is not yet better. The two fixes I would try first are stripping the category suffix the model copies into template ids, and suppressing the example identifier it copies."

**MOCK FALLBACK (Ollama slow, down, or the GPU is busy).** Do not wait. Use the recorded results and say they are recorded:

1. Show the pre-recorded 5-requirement smoke run: `Get-Content outputs\ollama_smoke.json -TotalCount 60` (real model, num_ctx 4096, 0 JSON failures, 0 fallbacks). Be honest that this is the early smoke run from before the plan-context fix: it kept 18 to 19 tests per requirement and took 103 to 126 s per requirement. The final numbers are in the report.
2. Show the side-by-side table in the report: open `outputs\eval_report.md` at "Mock vs Ollama - side by side", or run `python scripts/demo.py --offline`, whose section [5] prints both modes.
3. Optionally open the Streamlit UI (`streamlit run uds_assistant/ui/streamlit_app.py`), section 4, which renders the same two-column headline table and the comparison.

## 7. Close (0:30)

**Say:** "To summarize: language model for language, code for correctness; two implementations that cross-check; and honest numbers: 3 of 12 held out for both the mock and the real 3B model, where the model did not beat the mock on any headline metric, with known limitations: synthetic spec, a small test set (12), nine documented disagreements with AUTOSAR's specification that I did not change, and CAPL exports that were never run in CANoe."

## Extras (only if asked)

- **API:** `python -m uds_assistant.api` then open <http://127.0.0.1:8000/docs> (endpoints: `/generate`, `/run`, `/eval`, `/export`, `/bugs`, `/runs`). Needs fastapi/uvicorn installed (they are in the project dependencies).
- **Streamlit UI:** `streamlit run uds_assistant/ui/streamlit_app.py` (needs `pip install -e ".[ui]"`). Section 4 shows the mock vs ollama comparison, read from `outputs\eval_report.json`. Note: only headless AppTest runs exist, not a human click-through, so keep it as an extra, not the main demo.
- **Exported tests:** `outputs\exports\generated_tests_test.py` (pytest; the eval run reported `171 passed`) and `*.can` (CAPL, unverified).

## Likely curveballs (short answers)

- *Why mock as the default?* Reproducible, offline, about 120x faster, and on the held-out test split the 3B model did not beat it on any headline metric. The LLM cannot affect bytes either way.
- *Did you try a real model?* Yes: Qwen2.5-3B (Q4_K_M) via Ollama on an RTX 3050 4 GB; the recorded comparison is in `outputs\eval_report.md`. A larger model and a new held-out requirement set are the next experiments.
- *Is the ollama gap just noise?* The parsed F1 gap (0.647 vs 0.700) is at the edge of GPU run-to-run noise (about +-0.05), but the precision gap (0.512 vs 0.933) is not.
- *Is 3/12 bad?* It is what it is: it shows the generic templates leave gaps, and the report names each gap. It is more honest than 25/26.
- *Is the spec real?* No, synthetic by design.
