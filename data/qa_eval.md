# qa_eval.csv - blind QA evaluation set

Written blind: the author read only `data/bcm_spec.yaml` and `data/sources/uds_reference_notes.md` (no code, tests, docs or outputs).
25 questions: 21 answerable (DID/RID facts, NRC meanings, session/timing/security, 3 conceptual) and 4 unanswerable (QA-006, QA-012, QA-018, QA-024).

## Columns
- `id`: QA-001..QA-025.
- `question`: natural-language question (mix of hex ids and names).
- `answerable`: true/false.
- `gold_answer`: short answer; empty if unanswerable.
- `gold_facts`: semicolon-separated `key=value` atoms a correct answer must contain. Keys: `session` (default|extended|programming), `security_level` (integer or none), `length` (bytes), `access` (read|write|read_write), `nrc` (0xNN), `nrc_name`, `value` (number+unit, e.g. 5000ms; attempt counts as `3attempts`), `term` (conceptual keyword).
- `gold_source_ids`: where the answer lives.
- `notes`: remarks; for unanswerable rows, why the answer is absent.

## Source-id convention
bcm_spec.yaml has top-level keys `sessions`, `security_levels`, `dids`, `routines`, `dtcs`, `ecu_reset`, ... and has **no NRC section**. Therefore:
- `spec:did:0xNNNN`, `spec:routine:0xNNNN` - entries of `dids` / `routines`.
- `spec:session` - `sessions` (incl. allowed_services); `spec:timing` - per-session `timing`; `spec:security` - `security_levels`.
- `spec:service:0xNN` is unused (services are only lists inside `sessions`; use `spec:session`).
- NRC meanings come only from the notes, so they cite `notes:nrcs-in-scope` (not `spec:nrc:*`).
- `notes:<slug>` - heading lowercased, spaces to hyphens, punctuation removed (e.g. `notes:timing-p2-p2-s3`, `notes:0x22-readdatabyidentifier`). Text in the notes preamble (suppress bit, negative-response format) is cited with the nearest heading `notes:nrc-evaluation-order`.
