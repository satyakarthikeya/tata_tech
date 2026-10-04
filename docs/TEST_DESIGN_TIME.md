# Test design time: manual vs generate + review

Status: pending owner measurement

Goal: compare the time to write UDS tests by hand with the time to generate them with the
tool and review them. The tool-side compute time is measured by a script; only the human
part needs a stopwatch.

## The five requirements (data/requirements_seed.csv)

| id | category | topic |
|---|---|---|
| REQ-001 | read_did | read the VIN in any session |
| REQ-005 | security | write DID 0x0100 needs extended session and security level 0x01 |
| REQ-009 | conditions | factory reset flag: programming session, level 0x03, vehicle stationary |
| REQ-011 | sequence | routine 0x0201: no stop/requestResults before start |
| REQ-015 | timing | TesterPresent accepted in every session (S3 timer) |

## Setup

1. Use the repo at a known commit (record `git rev-parse --short HEAD` with the results).
2. Have `data/bcm_spec.yaml` and the requirement text open. Do not look at `data/gold/` or
   `outputs/generated_tests.yaml` during the manual runs.
3. Do the manual and the tool session for the same requirement on different days, or in a
   shuffled order, so one does not prime the other. Use the mock LLM unless you are
   deliberately measuring ollama.
4. Close chat and email; one requirement per stopwatch run.

## What counts as "done"

- Manual: a set of tests for the requirement (the positive, negative and boundary cases you
  judge necessary), written in the project's test format and passing on the clean simulator.
- Tool: tests generated, then every one reviewed and marked accepted, corrected or
  rejected; the accepted set passes on the clean simulator.

## Stopwatch rules

- Start when you first read the requirement; stop when the set is done as defined above.
- Manual: includes looking things up in the spec and fixing failures on the simulator.
- Tool: includes the real generation wait, reading every test, and edits. Do not pause the
  watch for generation; the wait is part of the workflow.
- Pauses over 1 minute: stop the watch and note it. Record minutes to one decimal.
- Do not redo a requirement after seeing the other method's result.

## Review rules (tool side)

The reviewer must open and check every generated test (request bytes, expected response,
preconditions, citation) against the spec. Mark each test accepted, corrected or rejected,
and write each correction (what was wrong, what you changed) in the table. A test that was
not read does not count as accepted.

## Results (owner fills in)

Status: pending owner measurement

| requirement | manual minutes | tool generate+review minutes | tests written manually | tests accepted from tool | corrections |
|---|---|---|---|---|---|
| REQ-001 | | | | | |
| REQ-005 | | | | | |
| REQ-009 | | | | | |
| REQ-011 | | | | | |
| REQ-015 | | | | | |

## Tool-side timings (measured)

Run: `python scripts/time_generation.py --modes mock,ollama --repeats 3`, git `8357ec0`, 2026-10-04T11:51:04Z,
laptop GPU, Ollama `qwen2.5:3b-instruct-q4_K_M`, BM25 retriever. Raw data: `outputs/timing/tool_timing.json`.
Wall time per requirement for the whole pipeline (parse, retrieve, plan, instantiate, validate, explain).
Caveat: another agent was editing `uds_assistant/rag/` (E3.3) in the working tree during this run.

| requirement | mode | mean s | min s | max s | tests generated |
|---|---|---|---|---|---|
| REQ-001 | mock | 0.776 | 0.055 | 2.214 | 18 |
| REQ-005 | mock | 0.099 | 0.077 | 0.116 | 18 |
| REQ-009 | mock | 0.085 | 0.079 | 0.093 | 22 |
| REQ-011 | mock | 0.077 | 0.055 | 0.120 | 12 |
| REQ-015 | mock | 0.046 | 0.046 | 0.047 | 13 |
| REQ-001 | ollama | 17.505 | 17.439 | 17.570 | 5 |
| REQ-005 | ollama | 17.806 | 17.625 | 18.048 | 4 |
| REQ-009 | ollama | 28.754 | 28.616 | 29.003 | 8 |
| REQ-011 | ollama | 16.250 | 14.248 | 19.986 | 4 |
| REQ-015 | ollama | 16.486 | 16.297 | 16.760 | 4 |

REQ-001 mock max includes one-off warm-up (first call). These are tool-side times only; the
manual-vs-tool comparison above is **pending owner measurement**.
