"""FP / FN by kind, rejection classification and the natural-v3 loader / split handling."""

from __future__ import annotations

from pathlib import Path

from uds_assistant.eval import breakdown as bd
from uds_assistant.eval import understanding as u

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_classify_rejection_reasons() -> None:
    assert bd.classify_rejection("unknown template id 'foo'") == "unknown_template_id"
    assert bd.classify_rejection(
        "option_index 28 out of range for write_did_out_of_range (6 options)"
    ) == "option_index_out_of_range"
    assert bd.classify_rejection("option was not in the offered shortlist"
                                 ) == "option_not_in_shortlist"
    assert bd.classify_rejection("choice previously failed validation") == "duplicate_or_other"
    assert bd.classify_rejection("instantiation failed: boom") == "duplicate_or_other"


def test_rejected_by_reason_counts_and_zero_fills() -> None:
    got = bd.rejected_by_reason([
        "plan: a[1]: option was not in the offered shortlist",
        "plan: b[0]: unknown template id 'b'",
        "plan: a[2]: option was not in the offered shortlist",
    ])
    assert got == {"unknown_template_id": 1, "option_index_out_of_range": 0,
                   "option_not_in_shortlist": 2, "duplicate_or_other": 0}
    assert list(bd.rejected_by_reason([])) == list(bd.REJECTION_REASONS)
    assert bd.reason_text(got) == "unknown template id 1, option not in the offered shortlist 2"
    assert bd.reason_text(bd.rejected_by_reason([])) == "none"


def _row(label: list[str], missed: list[str], extra: list[str]) -> dict[str, object]:
    block = {"missed": missed, "extra": extra}
    return {"label_targets": label, "parsed": block, "exercised": block}


def test_by_kind_counts_tp_fp_fn() -> None:
    rows = [
        _row(["service:0x22", "did:0xF190"], ["did:0xF190"], ["service:0x10", "did:0x0150"]),
        _row(["routine:0x0201"], [], ["service:0x10"]),
    ]
    got = bd.by_kind(rows)["parsed"]  # type: ignore[arg-type]
    assert got["service"] == {"tp": 1, "fp": 2, "fn": 0}
    assert got["did"] == {"tp": 0, "fp": 1, "fn": 1}
    assert got["routine"] == {"tp": 1, "fp": 0, "fn": 0}
    assert got["dtc"] == {"tp": 0, "fp": 0, "fn": 0}
    assert bd.fp_fn_text(got, "fp") == "service 2, did 1"
    assert bd.fp_fn_text(got, "fn") == "did 1"


def test_natural_v3_loads_with_the_same_schema_and_aggregates_by_test3() -> None:
    reqs = u.load_natural_requirements(REPO_ROOT / "data" / "requirements_natural_v3.csv")
    assert len(reqs) == 16 and {r.split for r in reqs} == {"test3"}
    assert "test3" in u.SPLITS
    rows = [{
        "id": r.id, "split": r.split, "ambiguous": r.ambiguous, "status": "completed",
        "tests": 1, "label_targets": sorted(
            [f"service:0x{s:02X}" for s in r.target_services]
            + [f"did:0x{d:04X}" for d in r.target_dids]
            + [f"routine:0x{x:04X}" for x in r.target_routines]),
        "parsed": {"exact": False, "tp": 0, "fp": 0, "fn": 0, "missed": [], "extra": []},
        "exercised": {"exact": False, "tp": 0, "fp": 0, "fn": 0, "missed": [], "extra": []},
        "categories": {"required": 0, "hit": 0, "recall": None, "missed": []},
        "preconditions": {"required": 0, "hit": 0, "recall": None, "missed": []},
        "fallback": False, "fallback_reasons": [],
    } for r in reqs]
    agg = u.aggregate_by_split(rows)
    assert set(agg) == {"test3", "all"} and agg["test3"]["requirements"] == 16
    assert set(agg["test3"]["by_kind"]) == {"parsed", "exercised"}
    # the v1 layout is unchanged
    v1 = u.aggregate_by_split([{**rows[0], "split": "test"}])
    assert set(v1) == {"test", "dev", "all"}
    v2 = u.aggregate_by_split([{**rows[0], "split": "test2"}])
    assert set(v2) == {"test2", "all"}
