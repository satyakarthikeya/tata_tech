"""Example requirements and questions offered in the UI."""

from __future__ import annotations

import csv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_IDS = ("REQ-001", "REQ-005", "REQ-010")
NATURAL_ID = "REQ-NL-DOOR"
NATURAL_TEXT = (
    "The door lock status must only be writable in extended session after security unlock."
)

ASK_EXAMPLES = (
    "What is the length of DID 0xF190?",
    "Can the VIN be written in any diagnostic session?",
    "In which session and at what security level can DID 0x0100 be written?",
    "What does NRC 0x33 mean?",
    "What does DID 0x0999 contain?",
)


def requirement_examples() -> dict[str, tuple[str, str]]:
    """``label -> (requirement id, text)``: three seed requirements and one natural-language one."""
    seeds: dict[str, str] = {}
    path = REPO_ROOT / "data" / "requirements_seed.csv"
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            seeds[row["id"]] = row["text"]
    out: dict[str, tuple[str, str]] = {}
    for rid in SEED_IDS:
        if rid in seeds:
            out[f"{rid} (seed): {seeds[rid][:70]}"] = (rid, seeds[rid])
    out[f"{NATURAL_ID} (natural language): {NATURAL_TEXT[:70]}"] = (NATURAL_ID, NATURAL_TEXT)
    return out
