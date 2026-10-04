"""Retrieval comparison: BM25 vs Chroma on the natural-language requirements.

Every row of ``data/requirements_natural.csv`` is a query (its ``text``).
Relevant chunks are derived from the row's own labels, not from either backend:

* row has target DIDs/routines: the ``ecu`` chunks whose ``identifiers``
  contain any of them;
* otherwise, if it has target services: the ``standard`` chunks whose ref is
  ``svc-<sid>`` for those services;
* no targets at all (e.g. NAT-020): excluded and counted.

A query hits@k if any relevant chunk is in the top ``k`` of a search across all
collections. MRR uses the rank of the first relevant chunk in the top 10 (0 if
none). Citation validity is the share of top-k hits whose
``Hit.to_citation()`` passes :func:`citation_is_valid`.

Run standalone: ``python -m uds_assistant.eval.retrieval_compare``.
"""

from __future__ import annotations

import csv
import sys
import warnings
from pathlib import Path
from typing import Any

from uds_assistant.config import get_config
from uds_assistant.rag.citations import citation_is_valid
from uds_assistant.rag.ingest import build_corpus, normalize_identifier
from uds_assistant.rag.model import CORE_LAYERS, Chunk, Retriever

REPO_ROOT = Path(__file__).resolve().parents[2]
TOP_N = 10
CITATION_K = 3
SPLITS = ("dev", "test", "all")


# --- pure scoring (no models) -------------------------------------------------------------


def first_relevant_rank(ranked_ids: list[str], relevant: set[str], limit: int = TOP_N) -> int:
    """1-based rank of the first relevant id within the top ``limit``; 0 if none."""
    for i, cid in enumerate(ranked_ids[:limit], start=1):
        if cid in relevant:
            return i
    return 0


def score_ranks(ranks: list[int]) -> dict[str, Any]:
    """Aggregate first-relevant ranks (0 = miss) into hit@1, hit@3 and MRR."""
    n = len(ranks)
    if n == 0:
        return {"queries": 0, "hit_at_1": None, "hit_at_3": None, "mrr": None}
    return {
        "queries": n,
        "hit_at_1": round(sum(1 for r in ranks if r == 1) / n, 4),
        "hit_at_3": round(sum(1 for r in ranks if 1 <= r <= 3) / n, 4),
        "mrr": round(sum(1 / r for r in ranks if r > 0) / n, 4),
    }


def _split_list(value: str) -> list[str]:
    return [v.strip() for v in value.split(";") if v.strip()]


def relevant_chunk_ids(row: dict[str, str], corpus: list[Chunk]) -> set[str]:
    """Ground-truth relevant chunk ids for one natural-requirement row (may be empty)."""
    targets = {
        normalize_identifier(t)
        for t in _split_list(row.get("target_dids", "")) + _split_list(row.get("target_routines", ""))
    }
    if targets:
        return {
            c.id for c in corpus
            if c.collection == "ecu" and targets & set(c.identifiers)
        }
    services = {normalize_identifier(s) for s in _split_list(row.get("target_services", ""))}
    refs = {f"svc-{s.lower()}" for s in services}
    return {c.id for c in corpus if c.collection == "standard" and c.ref.lower() in refs}


# --- evaluation ---------------------------------------------------------------------------


def evaluate_backend(
    retriever: Retriever,
    rows: list[dict[str, str]],
    relevance: dict[str, set[str]],
    corpus: list[Chunk],
) -> dict[str, Any]:
    """Run every non-excluded row through ``retriever`` and score it per split."""
    per_query: dict[str, dict[str, Any]] = {}
    for row in rows:
        rel = relevance[row["id"]]
        if not rel:
            continue
        hits = retriever.search(row["text"], k=TOP_N)
        ranks = first_relevant_rank([h.chunk.id for h in hits], rel)
        top = hits[:CITATION_K]
        valid = sum(1 for h in top if citation_is_valid(h.to_citation(), corpus))
        per_query[row["id"]] = {
            "split": row["split"], "rank": ranks, "citations_valid": valid,
            "citations_total": len(top),
        }
    splits: dict[str, Any] = {}
    for name in SPLITS:
        sel = [q for q in per_query.values() if name == "all" or q["split"] == name]
        agg = score_ranks([q["rank"] for q in sel])
        total = sum(q["citations_total"] for q in sel)
        agg["citation_validity"] = (
            round(sum(q["citations_valid"] for q in sel) / total, 4) if total else None
        )
        splits[name] = agg
    return {"splits": splits, "per_query": per_query}


def run_retrieval_comparison(
    repo_root: str | Path | None = None, *, persist_dir: str | Path = "outputs/chroma"
) -> dict[str, Any]:
    """Compare BM25 and Chroma; Chroma is recorded as "not run" (with reason) if unavailable."""
    from uds_assistant.rag.bm25 import Bm25Retriever

    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    corpus = build_corpus(root, layers=CORE_LAYERS)  # OEM layer excluded: keeps Part B numbers comparable
    with (root / "data" / "requirements_natural.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    relevance = {r["id"]: relevant_chunk_ids(r, corpus) for r in rows}
    excluded = [r["id"] for r in rows if not relevance[r["id"]]]
    result: dict[str, Any] = {
        "queries_total": len(rows),
        "queries_scored": len(rows) - len(excluded),
        "excluded": excluded,
        "relevance_sizes": {rid: len(v) for rid, v in relevance.items()},
        "top_n": TOP_N,
        "citation_k": CITATION_K,
        "backends": {"bm25": {"status": "completed",
                              **evaluate_backend(Bm25Retriever(corpus), rows, relevance, corpus)}},
    }
    embedder = get_config().embedder
    from uds_assistant.rag.chroma import ChromaRetriever, chroma_available

    if not chroma_available(embedder):
        result["backends"]["chroma"] = {
            "status": "not run",
            "reason": f"chromadb or the {embedder} embedder is not installed",
        }
        return result
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            chroma = ChromaRetriever(corpus, persist_dir=root / persist_dir, embedder=embedder)
        result["backends"]["chroma"] = {
            "status": "completed", "embedder": embedder,
            **evaluate_backend(chroma, rows, relevance, corpus),
        }
    except Exception as exc:  # noqa: BLE001 - model unavailable offline, corrupt store, ...
        result["backends"]["chroma"] = {
            "status": "not run", "reason": f"{type(exc).__name__}: {exc}",
        }
    return result


# --- rendering ----------------------------------------------------------------------------


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"


def render_section(cmp: dict[str, Any]) -> list[str]:
    """Markdown lines for the "Retrieval comparison (BM25 vs Chroma)" section."""
    lines = ["## Retrieval comparison (BM25 vs Chroma)", ""]
    if cmp.get("status") == "not run":
        return lines + [f"Not run: {cmp.get('reason', 'unknown reason')}.", ""]
    lines += [
        (f"Queries are the `text` of each row of `data/requirements_natural.csv`; "
         f"{cmp['queries_scored']} of {cmp['queries_total']} scored "
         f"({', '.join(cmp['excluded']) or 'none'} excluded: no target service/DID/routine). "
         "Relevant chunks: ecu chunks carrying a target DID/routine identifier; for rows "
         "with no DID/routine, the standard-collection `svc-<sid>` chunk of each target service. "
         f"Search spans all collections; MRR uses the first relevant rank in the top "
         f"{cmp['top_n']} (0 if none); citation validity is over the top "
         f"{cmp['citation_k']} hits."),
        "",
    ]
    backends = cmp["backends"]
    chroma = backends["chroma"]
    if chroma["status"] != "completed":
        lines += [f"Chroma: **not run** ({chroma.get('reason')}).", ""]
    names = [n for n in ("bm25", "chroma") if backends[n]["status"] == "completed"]
    rows = []
    for split in SPLITS:
        for n in names:
            s = backends[n]["splits"][split]
            label = f"**{split}**" if split == "test" else split
            nm = f"**{n}**" if split == "test" else n
            rows.append([label, nm, s["queries"], _pct(s["hit_at_1"]), _pct(s["hit_at_3"]),
                         "n/a" if s["mrr"] is None else f"{s['mrr']:.3f}",
                         _pct(s["citation_validity"])])
    lines += _md_table(["split", "backend", "queries", "hit@1", "hit@3", "MRR",
                        f"citation validity (top {cmp['citation_k']})"], rows)
    lines += ["", f"Rank of the first relevant chunk per query (0 = not in top {cmp['top_n']}):", ""]
    ids = list(backends["bm25"]["per_query"])
    qrows = []
    for qid in ids:
        b = backends["bm25"]["per_query"][qid]
        row = [qid, b["split"], cmp["relevance_sizes"][qid], b["rank"]]
        if "chroma" in names:
            row.append(backends["chroma"]["per_query"][qid]["rank"])
        qrows.append(row)
    head = ["query", "split", "relevant chunks", "BM25 rank"] + (["Chroma rank"] if "chroma" in names else [])
    lines += _md_table(head, qrows) + [""]
    return lines


def _md_table(header: list[str], rows: list[list[Any]]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: print the comparison as Markdown."""
    del argv
    cmp = run_retrieval_comparison()
    sys.stdout.write("\n".join(render_section(cmp)) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
