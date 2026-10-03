"""B3/D1b prompt-tuning harness: run the agent with the real Ollama model on the DEV split only.

Usage::

    python scripts/tune_dev.py --rev N [--note "what changed"] [--num-ctx 32768]

Held-out integrity: the natural requirements are read only through
:func:`uds_assistant.eval.understanding.load_natural_requirements`, filtered to
``split == "dev"`` immediately, and an assertion guarantees no other split ever
reaches the pipeline, the scorer, the output file or stdout.

Scoring is exactly the eval's: :func:`score_requirement` per row and the eval's
aggregate for the dev split. To save time the explain node's LLM call is stubbed
*in this harness only* (a wrapper LLM whose ``complete_text`` returns ``""``, so
each test keeps its template explanation); explain does not affect any score.
Agent code is not modified. Writes ``outputs/prompt_tuning/rev_<N>.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import warnings
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from uds_assistant.agent import run_pipeline
from uds_assistant.config import Config
from uds_assistant.eval import understanding as u
from uds_assistant.llm import prompts
from uds_assistant.llm.client import OllamaClient
from uds_assistant.llm.factory import get_llm
from uds_assistant.rag.bm25 import Bm25Retriever
from uds_assistant.rag.ingest import build_corpus
from uds_assistant.spec.schema import load_spec

T = TypeVar("T", bound=BaseModel)
SPLIT = "dev"
OUT_DIR = ROOT / "outputs" / "promptD"
SNAPSHOT_FILES = (
    "uds_assistant/llm/prompts.py",
    "uds_assistant/agent/service_lexicon.py",
    "uds_assistant/agent/grounding.py",
)
SERVER_LOG = Path(os.environ.get("LOCALAPPDATA", "")) / "Ollama" / "server.log"


class NoExplainLLM:
    """Delegates structured calls to the real client; free-text (explain) is stubbed.

    D1b: every structured call is also timed (``calls`` holds ``(kind, seconds)``; kind is
    ``plan-enum`` when a per-call schema was passed, else ``json``)."""

    def __init__(self, inner: Any, stub_explain: bool = True) -> None:
        self.calls: list[tuple[str, float]] = []
        self.stub_explain = stub_explain
        self.supports_json_schema = getattr(inner, "supports_json_schema", False)
        self.applies_grounding = getattr(inner, "applies_grounding", True)
        self.inner = inner
        self.name = inner.name
        self.stats = inner.stats
        self.fallback_events = inner.fallback_events
        self.truncation_events = inner.truncation_events
        self.context_tokens = inner.context_tokens

    def complete_json(self, system: str, prompt: str, schema: type[T], **kw: Any) -> T:
        t0 = time.perf_counter()
        try:
            return self.inner.complete_json(system, prompt, schema, **kw)
        finally:
            kind = "plan-enum" if kw.get("json_schema") else "json"
            self.calls.append((kind, round(time.perf_counter() - t0, 2)))

    def complete_text(self, system: str, prompt: str) -> str:
        return "" if self.stub_explain else self.inner.complete_text(system, prompt)


_BREAKDOWN_KEYS = ("fp_by_kind", "fn_by_kind", "rejected_total", "rejected_by_reason",
                   "dropped_notes", "plan_call_s_mean", "plan_call_s_max", "plan_calls")


def _kind_counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        for ident in r["parsed"][key]:
            kind = ident.split(":")[0]
            out[kind] = out.get(kind, 0) + 1
    return out


def _reason_kind(rej: str) -> str:
    if "unknown template id" in rej:
        return "unknown template id"
    if "out of range" in rej:
        return "index out of range"
    if "not in the offered shortlist" in rej:
        return "not in shortlist"
    if "previously failed" in rej:
        return "previously failed validation"
    return "other (validation: " + rej.split(" ", 1)[-1][:60] + ")"


def _error_breakdown(per_req: list[dict[str, Any]]) -> dict[str, Any]:
    """FP/FN by identifier kind, planner rejections by reason, evidence-rule drop notes."""
    reasons: dict[str, int] = {}
    total = 0
    for r in per_req:
        for rej in r["rejected"]:
            if rej.startswith("plan:"):
                reasons[_reason_kind(rej)] = reasons.get(_reason_kind(rej), 0) + 1
            total += 1
    plan_t = [t for r in per_req for t in r["plan_call_s"]]
    return {
        "fp_by_kind": _kind_counts(per_req, "extra"),
        "fn_by_kind": _kind_counts(per_req, "missed"),
        "rejected_total": total,
        "rejected_by_reason": reasons,
        "dropped_notes": {r["id"]: [n for n in r["notes"] if "Dropped" in n or "No parsed" in n]
                          for r in per_req},
        "plan_call_s_mean": round(sum(plan_t) / len(plan_t), 2) if plan_t else None,
        "plan_call_s_max": max(plan_t) if plan_t else None,
        "plan_calls": len(plan_t),
    }


def _snapshot_files(dest: Path) -> None:
    """Copy the tunable source files next to the revision record (for exact restoration)."""
    dest.mkdir(parents=True, exist_ok=True)
    for rel in SNAPSHOT_FILES:
        (dest / Path(rel).name).write_bytes((ROOT / rel).read_bytes())


def seed_smoke(args: argparse.Namespace) -> int:
    """15 seed requirements through the full pipeline (real explain); no scoring, no labels."""
    import csv

    spec = load_spec(ROOT / "data" / "bcm_spec.yaml")
    retriever = Bm25Retriever(build_corpus(ROOT))
    inner = get_llm(Config(llm_mode="ollama", retriever="bm25"))
    if not isinstance(inner, OllamaClient):
        print("ERROR: Ollama not reachable")
        return 2
    llm = NoExplainLLM(inner, stub_explain=False)
    with (ROOT / "data" / "requirements_seed.csv").open(encoding="utf-8", newline="") as fh:
        seeds = list(csv.DictReader(fh))
    assert len(seeds) == 15
    log_start = _log_lines()
    out_rows: list[dict[str, Any]] = []
    for row in seeds:
        start = time.perf_counter()
        call_mark = len(llm.calls)
        res = run_pipeline(row["text"], row["id"], spec, llm, retriever, engine="plain")
        rec = {
            "id": row["id"],
            "status": res.status,
            "tests": len(res.tests),
            "parsed": res.parsed.model_dump() if res.parsed else None,
            "notes": res.notes,
            "plan_attempts": res.plan_attempts,
            "rejected": [f"{r.node}: {r.template_id}[{r.option_index}] {r.reason}"
                         for r in res.rejected],
            "llm_stats": res.llm_stats,
            "fallback_events": res.fallback_events,
            "call_s": llm.calls[call_mark:],
            "wall_s": round(time.perf_counter() - start, 1),
        }
        out_rows.append(rec)
        print(f"  {row['id']}: status={res.status} tests={len(res.tests)} "
              f"rej={len(res.rejected)} fb={len(res.fallback_events)} wall={rec['wall_s']}s")
    truncs = _truncation_warnings(log_start)
    summary = {
        "n": len(out_rows),
        "rejected_total": sum(len(r["rejected"]) for r in out_rows),
        "rejected_plan_total": sum(1 for r in out_rows for x in r["rejected"] if x.startswith("plan:")),
        "fallback_events": sum(len(r["fallback_events"]) for r in out_rows),
        "json_failures": sum(int(r["llm_stats"].get("json_failures", 0)) for r in out_rows),
        "llm_errors": sum(int(r["llm_stats"].get("errors", 0)) for r in out_rows),
        "server_log_truncations": len(truncs),
        "mean_tests": round(sum(r["tests"] for r in out_rows) / len(out_rows), 2),
        "wall_s_total": round(sum(r["wall_s"] for r in out_rows), 1),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"seed_smoke_{args.rev}.json"
    out.write_text(json.dumps({"revision": args.rev, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                               "summary": summary, "requirements": out_rows}, indent=2),
                   encoding="utf-8")
    print("seed smoke:", summary, "->", out.relative_to(ROOT))
    return 0


def dev_rows() -> list[u.NaturalRequirement]:
    """The dev split, and nothing else."""
    rows = [
        r for r in u.load_natural_requirements(ROOT / "data" / "requirements_natural.csv")
        if r.split == SPLIT
    ]
    assert rows and all(r.split == SPLIT for r in rows), "non-dev row leaked"
    return rows


def _log_lines() -> int:
    try:
        with SERVER_LOG.open(encoding="utf-8", errors="replace") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return -1


def _truncation_warnings(since_line: int) -> list[str]:
    if since_line < 0:
        return []
    with SERVER_LOG.open(encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()[since_line:]
    return [ln.strip() for ln in lines if "truncating input prompt" in ln]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rev", required=True)
    ap.add_argument("--note", default="")
    ap.add_argument("--seed", action="store_true",
                    help="smoke-test mode: run the 15 seed requirements (data/requirements_seed.csv) "
                    "through the full pipeline with the REAL explain call; no scoring")
    ap.add_argument("--num-ctx", type=int, default=None,
                    help="diagnostic only: override OLLAMA_NUM_CTX for this run")
    args = ap.parse_args(argv)
    if args.num_ctx:
        os.environ["OLLAMA_NUM_CTX"] = str(args.num_ctx)

    if args.seed:
        return seed_smoke(args)
    rows = dev_rows()
    spec = load_spec(ROOT / "data" / "bcm_spec.yaml")
    retriever = Bm25Retriever(build_corpus(ROOT))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        inner = get_llm(Config(llm_mode="ollama", retriever="bm25"))
    if not isinstance(inner, OllamaClient):
        print("ERROR: Ollama not reachable; refusing to score the mock.", *caught, sep="\n")
        return 2
    llm = NoExplainLLM(inner)

    log_start = _log_lines()
    t0 = time.perf_counter()
    scored: list[dict[str, Any]] = []
    per_req: list[dict[str, Any]] = []
    for req in rows:
        assert req.split == SPLIT
        start = time.perf_counter()
        call_mark = len(llm.calls)
        res = run_pipeline(req.text, req.id, spec, llm, retriever, engine="plain")
        row = u.score_requirement(spec, req, res.parsed, res.tests, res.status)
        scored.append(row)
        per_req.append({
            **row,
            "parsed_raw": res.parsed.model_dump() if res.parsed else None,
            "notes": res.notes,
            "plan_attempts": res.plan_attempts,
            "rejected": [f"{r.node}: {r.template_id}[{r.option_index}] {r.reason}"
                         for r in res.rejected],
            "test_templates": [t.template_id for t in res.tests],
            "llm_stats": res.llm_stats,
            "fallback_events": res.fallback_events,
            "plan_call_s": [t for k, t in llm.calls[call_mark:] if k == "plan-enum"],
            "parse_call_s": [t for k, t in llm.calls[call_mark:] if k == "json"],
            "shortlist_sizes": [int(d.message.split()[2]) for d in res.decisions
                                if d.node == "plan" and d.message.startswith("compact prompt")],
            "wall_s": round(time.perf_counter() - start, 1),
        })
        print(f"  {req.id}: tests={row['tests']} parsed_exact={row['parsed']['exact']} "
              f"extra={row['parsed']['extra']} missed={row['parsed']['missed']}")
    assert all(r["split"] == SPLIT for r in scored)
    agg = u.aggregate_by_split(scored)
    assert agg["test"]["requirements"] == 0
    dev = agg["dev"]
    truncs = _truncation_warnings(log_start)
    json_failures = sum(int(r["llm_stats"].get("json_failures", 0)) for r in per_req)
    retries = sum(int(r["llm_stats"].get("retries", 0)) for r in per_req)
    errors = sum(int(r["llm_stats"].get("errors", 0)) for r in per_req)
    mean_tests = round(sum(r["tests"] for r in scored) / len(scored), 2)
    summary = {
        "targets_parsed_exact": dev["targets_parsed"]["exact"],
        "targets_exercised_exact": dev["targets_exercised"]["exact"],
        "parsed_precision": dev["targets_parsed"]["precision"],
        "parsed_recall": dev["targets_parsed"]["recall"],
        "parsed_f1": dev["targets_parsed"]["f1"],
        "exercised_f1": dev["targets_exercised"]["f1"],
        "category_recall_micro": dev["categories"]["micro_recall"],
        "precondition_recall_micro": dev["preconditions"]["micro_recall"],
        "fallback_count": dev["fallback"]["count"],
        "mean_tests_per_req": mean_tests,
        "json_failures": json_failures,
        "llm_retries": retries,
        "llm_errors": errors,
        "prompt_truncations": len(truncs),
        "client_truncation_events": sum(
            1 for r in per_req for e in r["fallback_events"] if "prompt likely truncated" in e),
        "mean_shortlist": round(sum(r["shortlist_sizes"][0] if r["shortlist_sizes"] else 0
                                    for r in per_req) / len(per_req), 1),
    }
    summary.update(_error_breakdown(per_req))
    summary["selection_score"] = round(
        (summary["parsed_f1"] or 0) + (summary["category_recall_micro"] or 0)
        + (summary["precondition_recall_micro"] or 0), 4)
    prompt_texts = {n: getattr(prompts, n) for n in prompts.__all__}
    payload = {
        "revision": args.rev,
        "note": args.note,
        "split": SPLIT,
        "n_requirements": len(rows),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "model": inner.model,
        "num_ctx": inner.num_ctx,
        "retriever": "bm25",
        "explain": "stubbed in harness (template explanation kept); does not affect scores",
        "wall_s": round(time.perf_counter() - t0, 1),
        "summary": summary,
        "aggregate_dev": dev,
        "truncation_warnings": truncs,
        "prompts_sha256": hashlib.sha256(
            json.dumps(prompt_texts, sort_keys=True).encode()).hexdigest()[:16],
        "prompts": prompt_texts,
        "requirements": per_req,
    }
    payload["error_breakdown"] = {k: summary[k] for k in _BREAKDOWN_KEYS}
    out_dir = OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    _snapshot_files(out_dir / f"rev_{args.rev}_files")
    suffix = f"_ctx{args.num_ctx}" if args.num_ctx else ""
    out = out_dir / f"rev_{args.rev}{suffix}.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    s = summary
    print(f"rev {args.rev}{suffix}: parsed_exact={s['targets_parsed_exact']}/{len(rows)} "
          f"exercised_exact={s['targets_exercised_exact']}/{len(rows)} "
          f"P/R/F1={s['parsed_precision']}/{s['parsed_recall']}/{s['parsed_f1']} "
          f"cat={s['category_recall_micro']} pre={s['precondition_recall_micro']} "
          f"fallback={s['fallback_count']} tests/req={s['mean_tests_per_req']} "
          f"jsonF={s['json_failures']} retries={s['llm_retries']} "
          f"trunc(server_log)={s['prompt_truncations']} "
          f"trunc(client)={s['client_truncation_events']} score={s['selection_score']} "
          f"wall={payload['wall_s']}s -> {out.relative_to(ROOT)}")
    print("  FP by kind:", s["fp_by_kind"], "FN by kind:", s["fn_by_kind"],
          "rejected:", s["rejected_total"], s["rejected_by_reason"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
