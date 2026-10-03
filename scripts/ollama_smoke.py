"""Smoke test: run the pipeline against a real Ollama model on a few seed requirements.

Usage::

    python scripts/ollama_smoke.py [--reqs REQ-001,REQ-002,...] [--out outputs/ollama_smoke.json]

Forces ``LLM_MODE=ollama`` (real model, BM25 retrieval), prints a per-requirement
table and writes the full numbers to JSON. If Ollama is unreachable the factory
falls back to the mock; that fallback is recorded verbatim and flagged, never
hidden. No prompt tuning happens here: this only measures the current prompts.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from uds_assistant.agent import run_pipeline
from uds_assistant.config import Config
from uds_assistant.llm.factory import get_llm
from uds_assistant.rag.bm25 import Bm25Retriever
from uds_assistant.rag.ingest import build_corpus
from uds_assistant.spec.schema import load_spec

DEFAULT_REQS = ["REQ-001", "REQ-002", "REQ-003", "REQ-004", "REQ-005"]
NODES = ("parse", "retrieve", "plan", "instantiate", "validate", "explain")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reqs", default=",".join(DEFAULT_REQS))
    ap.add_argument("--out", default=str(ROOT / "outputs" / "ollama_smoke.json"))
    args = ap.parse_args(argv)
    req_ids = [r.strip() for r in args.reqs.split(",") if r.strip()]

    with (ROOT / "data" / "requirements_seed.csv").open(encoding="utf-8", newline="") as fh:
        rows = {r["id"]: r["text"] for r in csv.DictReader(fh) if r.get("id")}
    spec = load_spec(ROOT / "data" / "bcm_spec.yaml")
    retriever = Bm25Retriever(build_corpus(ROOT))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        llm = get_llm(Config(llm_mode="ollama", retriever="bm25"))
    for w in caught:
        print(f"WARNING: {w.message}")
    print(f"LLM backend: {llm.name} (model={getattr(llm, 'model', '-')}, "
          f"num_ctx={getattr(llm, 'num_ctx', '-')})")

    records: list[dict] = []
    for rid in req_ids:
        start = time.perf_counter()
        res = run_pipeline(rows[rid], rid, spec, llm, retriever, engine="plain")
        wall = (time.perf_counter() - start) * 1000
        rec = {
            "requirement_id": rid,
            "status": res.status,
            "llm": res.llm,
            "tests_kept": len(res.tests),
            "dropped": len(res.dropped),
            "rejected": len(res.rejected),
            "rejected_reasons": [f"{r.node}: {r.template_id}[{r.option_index}] {r.reason}"
                                 for r in res.rejected],
            "plan_attempts": res.plan_attempts,
            "plan_retries": max(0, res.plan_attempts - 1),
            "node_timings_ms": res.node_timings,
            "wall_ms": round(wall, 1),
            "llm_stats": res.llm_stats,
            "fallback_events": res.fallback_events,
            "parsed": res.parsed.model_dump() if res.parsed else None,
            "notes": res.notes,
            "test_ids": [t.id for t in res.tests],
        }
        records.append(rec)
        print(f"  {rid}: kept={rec['tests_kept']} wall={rec['wall_ms']:.0f} ms")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "llm_backend": llm.name,
        "model": getattr(llm, "model", None),
        "num_ctx": getattr(llm, "num_ctx", None),
        "client_fallback_events": list(getattr(llm, "fallback_events", [])),
        "requirements": records,
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print()
    head = (f"{'req':8} {'status':9} {'kept':>4} {'drop':>4} {'rej':>3} {'plans':>5} {'retry':>5} "
            f"{'calls':>5} {'jsonF':>5} {'llmRe':>5}  node latency ms "
            f"({'/'.join(n[:4] for n in NODES)})")
    print(head)
    for r in records:
        st = r["llm_stats"]
        lat = "/".join(f"{r['node_timings_ms'].get(n, 0):.0f}" for n in NODES)
        print(f"{r['requirement_id']:8} {r['status']:9} {r['tests_kept']:>4} {r['dropped']:>4} "
              f"{r['rejected']:>3} {r['plan_attempts']:>5} {r['plan_retries']:>5} "
              f"{int(st.get('calls', 0)):>5} {int(st.get('json_failures', 0)):>5} "
              f"{int(st.get('retries', 0)):>5}  {lat}")
    print("\nFallback events (verbatim):")
    any_event = False
    for r in records:
        for ev in r["fallback_events"]:
            any_event = True
            print(f"  [{r['requirement_id']}] {ev}")
    if not any_event:
        print("  (none)")
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
