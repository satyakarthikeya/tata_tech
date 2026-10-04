"""Blind Q&A evaluation: score ``/ask`` answers against ``data/qa_eval.csv``.

The CSV (and its conventions, ``data/qa_eval.md``) was written blind and is never edited;
its source-id conventions are **mapped onto our chunk ids here**:

- ``spec:did:0xNNNN`` / ``spec:routine:0xNNNN`` -> the ``ecu:`` chunk whose text starts with that DID / routine;
- ``spec:session`` and ``spec:timing`` -> every ``ecu:session:*`` chunk (timing lives in the session chunks);
- ``spec:security`` -> every ``ecu:security_level:*`` chunk;
- ``notes:<slug>`` -> the ``standard:`` chunk whose heading slugifies to ``<slug>`` (the chunk's first
  line is its heading). The file's preamble (suppress bit, negative-response format) is filed by the
  CSV under the nearest heading ``notes:nrc-evaluation-order``; the preamble chunk is therefore also accepted
  for that id.

How ``gold_facts`` atoms (``key=value``, ``;``-separated) are matched in the answer (whitespace collapsed,
case-insensitive):

- ``session=<name>``: the session name as a whole word;
- ``security_level=<n>``: ``level 0x0<n>`` / ``level <n>`` (an optional ``:`` or ``=`` after ``level`` is allowed) (``none``: "no security" / "none");
- ``length=<n>``: ``<n> byte(s)`` (or ``length <n>``);
- ``access=read``: "read-only"; ``write``: "writable"; ``read_write``: "readable and writable" or "read/write";
- ``nrc=0xNN``: the hex code as a whole token; ``nrc_name=<name>``: the name as a whole word;
- ``value=<number><unit>`` (e.g. ``5000ms``): the number followed by the unit, spaces optional;
  ``value=<n>attempts``: "<n> attempts" (or "attempts: <n>"); a bare number: the number as a whole token;
- ``term=<text>``: plain case-insensitive substring.

An answerable question is *accurate* when its status is ``answered`` and every atom is present.

Run through ``python -m uds_assistant.eval.run_eval`` (section 7 of the report).
"""

from __future__ import annotations

import csv
import re
import sys
import time
from pathlib import Path
from typing import Any

from uds_assistant.qa.answer import answer_question
from uds_assistant.qa.lookup import FactLookup
from uds_assistant.qa.models import AskResponse
from uds_assistant.qa.text import collapse, contains_token
from uds_assistant.rag.model import Chunk
from uds_assistant.spec.schema import EcuSpec

PREAMBLE_SLUG = "uds-reference-notes-own-words-summary"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# ---------------------------------------------------------------------------- fact matching


def fact_present(answer: str, atom: str) -> bool:
    """True if the gold atom ``key=value`` is present in ``answer`` (rules in the module docstring)."""
    key, _, value = atom.partition("=")
    key, value = key.strip().lower(), value.strip()
    a = collapse(answer).lower()
    v = value.lower()
    if key == "session":
        return contains_token(a, v)
    if key == "security_level":
        if v == "none":
            return bool(re.search(r"\bno security\b|\bnone\b", a))
        n = int(v, 0)
        return bool(re.search(rf"level\s*[:=]?\s*(?:0x0*{n:x}|{n})(?![0-9a-z])", a))
    if key == "length":
        n = int(v)
        return bool(re.search(rf"(?<![0-9a-z]){n}\s*bytes?(?![a-z])|length\s*{n}(?![0-9])", a))
    if key == "access":
        pats = {
            "read": r"read[- ]only",
            "write": r"writable|write[- ]only",
            "read_write": r"readable and writable|read/write|read and write|read-write",
        }
        return bool(re.search(pats.get(v, re.escape(v)), a))
    if key == "nrc":
        return contains_token(a, v)
    if key == "nrc_name":
        return contains_token(a, v)
    if key == "value":
        m = re.fullmatch(r"(\d+)\s*([a-z*]*)", v)
        if not m:
            return v in a
        num, unit = m.group(1), m.group(2)
        if unit in ("attempt", "attempts"):
            return bool(re.search(rf"(?<![0-9]){num}\s*attempts?|attempts?\s*(?:[:=]|of|is)?\s*{num}(?![0-9])", a))
        if unit:
            return bool(re.search(rf"(?<![0-9a-z.]){num}\s*{re.escape(unit)}(?![a-z])", a))
        return contains_token(a, num)
    if key == "term":
        return v in a
    raise ValueError(f"unknown gold fact key {key!r}")


def facts_present(answer: str, gold_facts: str) -> tuple[bool, list[str]]:
    """``(all present, missing atoms)`` for a ``;``-separated ``gold_facts`` string."""
    atoms = [x.strip() for x in gold_facts.split(";") if x.strip()]
    missing = [x for x in atoms if not fact_present(answer, x)]
    return not missing, missing


# ---------------------------------------------------------------------------- source mapping


def map_source_id(gold_id: str, chunks: list[Chunk]) -> set[str]:
    """Our chunk ids that a gold source id (CSV convention) refers to."""
    gid = gold_id.strip()
    if gid.startswith("spec:did:"):
        hx = "0x" + gid.split("0x", 1)[1].upper()
        return {c.id for c in chunks if c.layer == "ecu" and c.text.startswith(f"DID {hx} ")}
    if gid.startswith("spec:routine:"):
        hx = "0x" + gid.split("0x", 1)[1].upper()
        return {c.id for c in chunks if c.layer == "ecu" and c.text.startswith(f"Routine {hx} ")}
    if gid in ("spec:session", "spec:timing"):
        return {c.id for c in chunks if c.id.startswith("ecu:session:")}
    if gid == "spec:security":
        return {c.id for c in chunks if c.id.startswith("ecu:security_level:")}
    if gid.startswith("notes:"):
        slug = gid[len("notes:"):]
        out = {c.id for c in chunks if c.layer == "standard" and _slug(c.text.split("\n", 1)[0]) == slug}
        if slug == "nrc-evaluation-order":
            out |= {c.id for c in chunks if c.layer == "standard" and _slug(c.text.split("\n", 1)[0]) == PREAMBLE_SLUG}
        return out
    return set()


# ---------------------------------------------------------------------------- scoring


def score_rows(rows: list[dict[str, Any]], chunks: list[Chunk]) -> dict[str, Any]:
    """Aggregate metrics from per-question rows (each has the CSV fields plus ``response``)."""
    ans = [r for r in rows if r["answerable"]]
    unans = [r for r in rows if not r["answerable"]]
    n_ans = len(ans) or 1
    accurate = cite_ok = 0
    cited_total = cited_good = 0
    for r in ans:
        resp: AskResponse = r["response"]
        gold_ids: set[str] = set()
        for g in r["gold_source_ids"]:
            gold_ids |= map_source_id(g, chunks)
        r["gold_chunk_ids"] = sorted(gold_ids)
        ok, missing = facts_present(resp.answer, r["gold_facts"]) if resp.status == "answered" else (False, ["<not_found>"])
        r["accurate"], r["missing_facts"] = ok, missing
        cited = sorted({c.chunk_id for c in resp.citations})
        good = [c for c in cited if c in gold_ids]
        r["citation_ok"] = bool(good)
        r["cited_chunks"], r["cited_good"] = cited, good
        accurate += ok
        cite_ok += bool(good)
        cited_total += len(cited)
        cited_good += len(good)
    for r in unans:
        r["correct_not_found"] = r["response"].status == "not_found"
    return {
        "n_questions": len(rows),
        "n_answerable": len(ans),
        "n_unanswerable": len(unans),
        "answer_accuracy": accurate / n_ans,
        "answer_accuracy_n": accurate,
        "citation_correctness": cite_ok / n_ans,
        "citation_correctness_n": cite_ok,
        "citation_precision": (cited_good / cited_total) if cited_total else 0.0,
        "citation_precision_counts": [cited_good, cited_total],
        "correct_not_found_rate": (sum(r["correct_not_found"] for r in unans) / len(unans)) if unans else 0.0,
        "correct_not_found_n": sum(r["correct_not_found"] for r in unans),
        "false_not_found": sum(r["response"].status == "not_found" for r in ans),
        "fallback_events": sum(len(r["response"].fallback_events) for r in rows),
    }


def load_questions(path: Path) -> list[dict[str, Any]]:
    """Read ``qa_eval.csv`` into dicts (``answerable`` bool, ``gold_source_ids`` list)."""
    out = []
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            row["answerable"] = row["answerable"].strip().lower() == "true"
            row["gold_source_ids"] = [x.strip() for x in row["gold_source_ids"].split(";") if x.strip()]
            out.append(row)
    return out


def run_qa(
    questions: list[dict[str, Any]], *, spec: EcuSpec, chunks: list[Chunk], retriever: Any, llm: Any
) -> dict[str, Any]:
    """Answer every question with ``llm`` and score it; ``rows`` keeps the per-question detail."""
    lookup = FactLookup(spec, chunks)
    rows: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    for q in questions:
        t = time.perf_counter()
        resp = answer_question(q["question"], spec=spec, chunks=chunks, retriever=retriever,
                               llm=llm, lookup=lookup)
        rows.append({**q, "response": resp, "seconds": round(time.perf_counter() - t, 2)})
        print(f"[qa] {q['id']}: {resp.status} ({rows[-1]['seconds']} s)", file=sys.stderr, flush=True)
    metrics = score_rows(rows, chunks)
    metrics.update(llm=llm.name, total_seconds=round(time.perf_counter() - t0, 1))
    metrics["rows"] = [
        {k: (v.model_dump() if isinstance(v, AskResponse) else v) for k, v in r.items()}
        for r in rows
    ]
    return metrics
