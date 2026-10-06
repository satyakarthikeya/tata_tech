# Import format (existing UDS tests)

Import format version 1: a small YAML file describing tests you already have. Import is
deterministic and uses no model: nothing in the file is rewritten or generated, and every expected
byte you wrote is checked against the rules engine for `data/bcm_spec.yaml` (a synthetic ECU spec).

Example files: [`data/imports/legacy_bcm_regression.yaml`](../data/imports/legacy_bcm_regression.yaml)
(14 accepted tests) and [`data/imports/legacy_bcm_with_errors.yaml`](../data/imports/legacy_bcm_with_errors.yaml)
(every rejection kind).

## File

```yaml
format_version: 1            # required, must be 1
suite: legacy_bcm_regression # optional name (default: the file name)
description: free text       # optional
tests:                       # required, 1..500 tests, file at most 512 KB
  - id: LEG-001              # required, unique in the file: letters, digits, _ . : -
    title: Read VIN          # required
    category: positive       # optional: positive | negative | session | security | timing
    requirement_ids: [REQ-001]   # optional
    template: TPL_READ_DID   # optional, name of YOUR automation template (kept as provenance, not interpreted)
    preconditions: [ ... ]   # optional free text; if empty the tool derives it from the steps
    pass_criteria: "..."     # optional free text; if empty the tool derives it from the steps
    steps:                   # required, 1..100 steps, at least one `send`
      - send: "22 F1 90"             # request bytes, hex (spaces / 0x allowed)
        expect: ["62 F1 90 ..."]     # REQUIRED: expected response frames, in order; [] = no response
        max_response_time_ms: 50     # optional P2-style limit for this step
        note: free text              # optional
      - wait_ms: 6000                # advance the injected clock
      - environment: {vehicle_speed_kph: 0, nvm_write_fault: false}   # either key or both
      - dtc: {code: "B10101", status: 8}                              # inject a DTC status byte
```

Rules:

- Each step has exactly one of `send`, `wait_ms`, `environment`, `dtc`. Unknown keys are errors
  (a misspelt `expected:` is rejected, not ignored).
- `expect` may be one string or a list. A response-pending sequence is two frames: `["7F 31 78", "71 01 02 01 00"]`.
- When `category` is missing it is inferred: any wait or `max_response_time_ms` -> `timing`;
  a `0x27` request -> `security`; a `0x10` / `0x11` request -> `session`; a last response starting
  `7F` -> `negative`; otherwise `positive`.
- Files are read with `yaml.safe_load`; nothing in them is executed.

## What import does with each test

| Outcome | Meaning | Stored? | Counted in coverage / run? |
|---|---|---|---|
| `accepted` | Fits the format and the `TestCase` schema, and every expected response equals the rules engine's prediction | Yes, as `origin: imported`, `review_status: validated` | Yes, after approval for run / export; coverage counts it as soon as it is accepted |
| `oracle_mismatch` | Fits the schema, but your expected bytes differ from the rules engine (the step and both values are shown) | Only in the import result and the audit trail | No |
| `invalid` | Does not fit the format / schema (bad hex, unknown key, no `send`, duplicate id, ...) | Only in the import result and the audit trail | No |

One bad test never blocks the others. A file-level problem (not YAML, wrong `format_version`,
no `tests`, too large) rejects the whole file (HTTP 422).

## Provenance, review and audit

- Imported tests carry `origin: "imported"` and a `provenance` record: suite, file name, SHA-256 of
  the uploaded bytes, the id as written in the file and your `template` name. AI-generated tests keep
  `origin: "generated"`. The UI shows the origin on every test.
- Imported tests are **never auto-approved**. They enter as `validated`; a human approves them in
  Generate & Review (the import run opens there). Run and export use approved tests only,
  exactly as for generated tests. Exported pytest / CAPL carry the simulator-only banner.
- Citations: each imported test cites the import file (`import:<file>`, test id) and the spec
  items it touches (`bcm_spec.yaml`, e.g. `dids.VIN`, `sessions.extended`), derived from its steps.
- Audit trail (SQLite): one run per import (`llm_mode = import`, requirement `import:<suite>`, the
  file's SHA-256), one `import` decision per test (outcome and reasons), one `import_result`
  decision with the full outcome list, and the usual `review` decisions when a person approves
  or rejects.

## Coverage comparison

`POST /import/{run_id}/compare` (and the Import & Compare tab) computes static coverage of the
accepted imported tests against the spec and compares it with generated tests and with the union.
It reports, per kind (services, DIDs, routines, NRCs, sessions, security levels, timing cases), items
touched / items in the spec for the baseline, the generated suite and the combined suite, plus:

- **Newly covered**: zero imported tests, at least one generated test;
- **Covered only by imported tests**;
- **Still uncovered** by the combined suite.

Timing cases are a fixed list: P2 response-time limit (a send step with `max_response_time_ms`),
response pending (`7F xx 78` then the final response), S3 timeout (a wait longer than S3 in a
non-default session), S3 keep-alive (a wait shorter than S3 in a non-default session) and security
delay (wait, then `0x27`, after a `0x36` / `0x37` NRC). Coverage is a static walk of the tests'
steps; nothing is executed and it says nothing about whether a test would catch a bug.

## API

| Endpoint | Purpose |
|---|---|
| `GET /import/format` | this document and the example file |
| `POST /import` `{filename, content}` | parse, validate, store; returns the outcome list |
| `GET /imports`, `GET /import/{run_id}` | list import runs / one import result |
| `POST /import/{run_id}/compare` `{generated_run_id?}` | comparison JSON + Markdown; omit the id to use every generated run in the audit trail |
| `GET /import/{run_id}/compare.md?generated_run_id=` | the Markdown report as a download |
| `GET /runs/{run_id}/tests`, `POST /runs/{run_id}/tests/{test_id}/review`, `POST /run`, `POST /export` | review, run and export, unchanged (same review gate) |

## Limits

The fixtures are synthetic and written for this project; no real customer suite was imported.
The format covers single-ECU, single-tester UDS request/response tests. It does not read CAPL,
vTESTstudio, Excel or other tool formats, and `template` names are recorded but not interpreted.
