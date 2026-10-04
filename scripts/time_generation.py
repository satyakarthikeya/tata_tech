"""Measure tool-side wall time per requirement (generate + validate + explain).

Run from the repo root::

    python scripts/time_generation.py --modes mock,ollama --repeats 3
    python scripts/time_generation.py --modes mock --repeats 1 --reqs REQ-001

Uses the real pipeline (``uds_assistant.agent.run_pipeline``). Stage times come from
``PipelineResult.node_timings``: *generate* = parse + retrieve + plan + instantiate,
*validate* and *explain* are the pipeline nodes of the same name; *total* is the
wall-clock time around the whole ``run_pipeline`` call. The ollama mode is skipped
(with a logged message) when ``GET /api/tags`` is not answered within a short timeout.
Writes JSON (default ``outputs/timing/tool_timing.json``) and prints a markdown table.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import statistics
import subprocess
import sys
import time
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from uds_assistant.agent import run_pipeline
from uds_assistant.config import Config
from uds_assistant.llm.client import ollama_base_url
from uds_assistant.llm.factory import get_llm
from uds_assistant.rag.factory import get_retriever
from uds_assistant.rag.ingest import build_corpus
from uds_assistant.spec.schema import load_spec

log = logging.getLogger("time_generation")

DEFAULT_REQS = ("REQ-001", "REQ-005", "REQ-009", "REQ-011", "REQ-015")
GENERATE_NODES = ("parse", "retrieve", "plan", "instantiate")
DEFAULT_OUT = ROOT / "outputs" / "timing" / "tool_timing.json"
PROBE_TIMEOUT_S = 2.0


def git_hash() -> str:
    """Short git hash of HEAD, or ``unknown``."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def load_requirements(ids: list[str]) -> dict[str, str]:
    """Return ``{id: text}`` for the given seed requirement ids."""
    with (ROOT / "data" / "requirements_seed.csv").open(encoding="utf-8", newline="") as fh:
        rows = {r["id"]: r["text"] for r in csv.DictReader(fh) if r.get("id")}
    missing = [i for i in ids if i not in rows]
    if missing:
        raise SystemExit(f"Unknown requirement id(s): {', '.join(missing)}")
    return {i: rows[i] for i in ids}


def ollama_up() -> bool:
    """True if Ollama answers ``GET /api/tags`` within a short timeout."""
    import httpx

    url = ollama_base_url() + "/api/tags"
    try:
        return httpx.get(url, timeout=PROBE_TIMEOUT_S).status_code == 200
    except httpx.HTTPError:
        return False


def summarise(values: list[float]) -> dict[str, float]:
    """Mean / min / max of a list of seconds (rounded to ms)."""
    return {
        "mean": round(statistics.fmean(values), 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
    }


def time_one(
    req_id: str, text: str, mode: str, spec: Any, retriever: Any, repeats: int
) -> dict[str, Any]:
    """Time ``repeats`` pipeline runs of one requirement in one LLM mode."""
    cfg = Config(llm_mode=mode, retriever="bm25")  # type: ignore[arg-type]
    totals: list[float] = []
    stages: dict[str, list[float]] = {"generate": [], "validate": [], "explain": []}
    n_tests = 0
    llm_used = mode
    for _ in range(repeats):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            llm = get_llm(cfg)
        llm_used = llm.name
        t0 = time.perf_counter()
        result = run_pipeline(text, req_id, spec, llm, retriever)
        totals.append(time.perf_counter() - t0)
        nt = result.node_timings
        stages["generate"].append(sum(nt.get(n, 0.0) for n in GENERATE_NODES) / 1000)
        stages["validate"].append(nt.get("validate", 0.0) / 1000)
        stages["explain"].append(nt.get("explain", 0.0) / 1000)
        n_tests = len(result.tests)
    return {
        "requirement": req_id,
        "mode": mode,
        "llm_used": llm_used,
        "repeats": repeats,
        "tests_generated": n_tests,
        "total_s": summarise(totals),
        "stages_s": {k: summarise(v) for k, v in stages.items()},
        "runs_total_s": [round(t, 3) for t in totals],
    }


def markdown_table(rows: list[dict[str, Any]]) -> str:
    """Render the result rows as a markdown table."""
    lines = [
        "| requirement | mode | mean s | min s | max s | tests generated |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        t = r["total_s"]
        lines.append(
            f"| {r['requirement']} | {r['mode']} | {t['mean']:.3f} | {t['min']:.3f} "
            f"| {t['max']:.3f} | {r['tests_generated']} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Run the timing; write JSON and print a markdown table. Return the exit code."""
    p = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    p.add_argument("--modes", default="mock,ollama", help="comma list of mock,ollama")
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--reqs", default=",".join(DEFAULT_REQS), help="comma list of seed ids")
    p.add_argument("--out", default=str(DEFAULT_OUT))
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    if any(m not in ("mock", "ollama") for m in modes) or args.repeats < 1:
        p.error("modes must be mock/ollama and repeats >= 1")
    reqs = load_requirements([r.strip() for r in args.reqs.split(",") if r.strip()])

    spec = load_spec(ROOT / "data" / "bcm_spec.yaml")
    retriever = get_retriever(Config(llm_mode="mock", retriever="bm25"), chunks=build_corpus(ROOT))

    rows: list[dict[str, Any]] = []
    skipped: dict[str, str] = {}
    for mode in modes:
        if mode == "ollama" and not ollama_up():
            msg = f"Ollama not reachable at {ollama_base_url()}; skipping ollama mode"
            log.warning(msg)
            skipped[mode] = msg
            continue
        for req_id, text in reqs.items():
            log.info("timing %s in %s mode (%d repeats)", req_id, mode, args.repeats)
            rows.append(time_one(req_id, text, mode, spec, retriever, args.repeats))

    payload = {
        "git_hash": git_hash(),
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "repeats": args.repeats,
        "requirements": list(reqs),
        "skipped_modes": skipped,
        "results": rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(markdown_table(rows))
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
