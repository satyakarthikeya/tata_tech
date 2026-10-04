"""Breakdowns shared by the report and before/after: false positives / negatives by kind and
rejected planner choices by reason.

Pure functions over the per-requirement rows of a report, so the same code reads an old
(Part C) report and a new one and the numbers stay comparable.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any

KINDS = ("service", "did", "routine", "dtc")
"""Identifier kinds always listed (zero counts included); any other kind seen is added."""

REJECTION_REASONS = (
    "unknown_template_id",
    "option_index_out_of_range",
    "option_not_in_shortlist",
    "duplicate_or_other",
)
REJECTION_LABELS: dict[str, str] = {
    "unknown_template_id": "unknown template id",
    "option_index_out_of_range": "option index out of range",
    "option_not_in_shortlist": "option not in the offered shortlist",
    "duplicate_or_other": "duplicate / other (previously failed, instantiate or validate failure)",
}


def classify_rejection(reason: str) -> str:
    """Map a rejection reason text to one of :data:`REJECTION_REASONS`."""
    text = reason.lower()
    if "unknown template id" in text:
        return "unknown_template_id"
    if "out of range" in text:
        return "option_index_out_of_range"
    if "not in the offered shortlist" in text:
        return "option_not_in_shortlist"
    return "duplicate_or_other"


def rejected_by_reason(reasons: Iterable[str]) -> dict[str, int]:
    """Count rejection reason texts per class (every class present, zeros included)."""
    counts = Counter(classify_rejection(r) for r in reasons)
    return {k: counts.get(k, 0) for k in REJECTION_REASONS}


def kind_of(ident: str) -> str:
    """Kind of a typed identifier string such as ``"service:0x22"`` or ``"did:0xF190"``."""
    return ident.split(":", 1)[0]


def _empty(kinds: Iterable[str]) -> dict[str, dict[str, int]]:
    return {k: {"tp": 0, "fp": 0, "fn": 0} for k in kinds}


def by_kind(rows: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, int]]]:
    """TP / FP / FN per identifier kind for ``parsed`` and ``exercised`` targets.

    Reads each row's ``label_targets`` and ``<which>.missed`` / ``.extra`` lists (typed
    identifier strings); tp = label items of the kind minus the missed ones.
    """
    out: dict[str, dict[str, dict[str, int]]] = {}
    for which in ("parsed", "exercised"):
        table = _empty(KINDS)
        for row in rows:
            miss = [kind_of(i) for i in row[which]["missed"]]
            extra = [kind_of(i) for i in row[which]["extra"]]
            label = [kind_of(i) for i in row["label_targets"]]
            for kind in set(miss) | set(extra) | set(label):
                table.setdefault(kind, {"tp": 0, "fp": 0, "fn": 0})
            for kind in label:
                table[kind]["tp"] += 1
            for kind in miss:
                table[kind]["tp"] -= 1
                table[kind]["fn"] += 1
            for kind in extra:
                table[kind]["fp"] += 1
        out[which] = table
    return out


def fp_fn_text(table: dict[str, dict[str, int]], key: str) -> str:
    """``"service 3, did 1"`` for the non-zero counts of ``key`` (``"fp"`` or ``"fn"``)."""
    parts = [f"{k} {v[key]}" for k, v in table.items() if v[key]]
    return ", ".join(parts) or "none"


def reason_text(counts: dict[str, int]) -> str:
    """``"unknown template id 2, option not in the offered shortlist 1"`` or ``"none"``."""
    parts = [f"{REJECTION_LABELS[k].split(' (')[0]} {v}" for k, v in counts.items() if v]
    return ", ".join(parts) or "none"
