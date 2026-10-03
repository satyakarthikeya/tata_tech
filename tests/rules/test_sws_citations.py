"""Every AUTOSAR Dcm SWS requirement ID cited in the rules package must really exist.

The SWS PDF is not committed (AUTOSAR redistribution terms); tests that need it
skip with a clear reason when it is absent.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

import uds_assistant.rules as rules_pkg
from uds_assistant.rules.sws import SWS_PDF, find_requirement, load_sws_text

RULES_DIR = Path(rules_pkg.__file__).resolve().parent
CITATION_RE = re.compile(r"SWS_Dcm_\d+")

#: Number of distinct SWS IDs cited in rules/*.py when the citations were added.
MIN_CITATIONS = 38

#: Cited requirements whose text must name the NRC the check returns.
NRC_OF_CITATION: list[tuple[str, str]] = [
    ("SWS_Dcm_00197", "0x11"),
    ("SWS_Dcm_00211", "0x7F"),
    ("SWS_Dcm_00696", "0x13"),
    ("SWS_Dcm_00272", "0x13"),
    ("SWS_Dcm_00273", "0x12"),
    ("SWS_Dcm_00307", "0x12"),
    ("SWS_Dcm_00321", "0x12"),
    ("SWS_Dcm_00616", "0x7E"),
    ("SWS_Dcm_01265", "0x31"),
    ("SWS_Dcm_01060", "0x72"),
    ("SWS_Dcm_01059", "0x14"),
    ("SWS_Dcm_01350", "0x37"),
    ("SWS_Dcm_00660", "0x35"),
    ("SWS_Dcm_01349", "0x36"),
    ("SWS_Dcm_00467", "0x31"),
    ("SWS_Dcm_00468", "0x31"),
    ("SWS_Dcm_00469", "0x31"),
    ("SWS_Dcm_00470", "0x33"),
    ("SWS_Dcm_00815", "0x22"),
    ("SWS_Dcm_00568", "0x31"),
    ("SWS_Dcm_00570", "0x31"),
    ("SWS_Dcm_00571", "0x33"),
    ("SWS_Dcm_00869", "0x12"),
    ("SWS_Dcm_01140", "0x13"),
    ("SWS_Dcm_00024", "0x78"),
]


def _cited_ids() -> set[str]:
    ids: set[str] = set()
    for path in RULES_DIR.glob("*.py"):
        ids.update(CITATION_RE.findall(path.read_text(encoding="utf-8")))
    return ids


@pytest.fixture(scope="module")
def sws_text() -> str:
    text = load_sws_text()
    if text is None:
        pytest.skip(
            f"AUTOSAR Dcm SWS PDF not present at {SWS_PDF} (not committed for licensing "
            "reasons; download AUTOSAR_CP_SWS_DiagnosticCommunicationManager.pdf to run)"
        )
    return text


def test_every_cited_sws_id_is_defined_in_the_sws(sws_text: str) -> None:
    missing = sorted(i for i in _cited_ids() if find_requirement(i, sws_text) is None)
    assert missing == []


def test_minimum_number_of_citations(sws_text: str) -> None:
    assert len(_cited_ids()) >= MIN_CITATIONS


@pytest.mark.parametrize(("sws_id", "nrc"), NRC_OF_CITATION)
def test_cited_requirement_names_the_nrc(sws_text: str, sws_id: str, nrc: str) -> None:
    assert sws_id in _cited_ids()
    body = find_requirement(sws_id, sws_text)
    assert body is not None
    assert nrc.lower() in body.lower(), sws_id


def test_load_returns_none_without_pdf(tmp_path: Path) -> None:
    assert load_sws_text(tmp_path / "absent.pdf", tmp_path / "cache.txt") is None
    assert not (tmp_path / "cache.txt").exists()


def test_find_requirement_skips_cross_references() -> None:
    text = (
        "Trace table\n[SWS_Dcm_09999] [SWS_Dcm_00001]\n"
        "[SWS_Dcm_00002] see [SWS_Dcm_09999] and\n[SWS_Dcm_09999], done.\u230b\n"
        "[SWS_Dcm_09999] Title\n\u2308Body text.\u230b(SRS_Diag_00001)\nNext\n"
    )
    body = find_requirement("SWS_Dcm_09999", text)
    assert body == "[SWS_Dcm_09999] Title \u2308Body text.\u230b(SRS_Diag_00001)"
    assert find_requirement("SWS_Dcm_08888", text) is None


def test_cache_is_reused_when_newer(tmp_path: Path) -> None:
    pdf = tmp_path / "x.pdf"
    cache = tmp_path / "cache" / "x.txt"
    pdf.write_bytes(b"not a real pdf")
    cache.parent.mkdir()
    cache.write_text("cached text", encoding="utf-8")
    os.utime(pdf, (1_000_000, 1_000_000))  # PDF older than cache -> no re-extraction
    assert load_sws_text(pdf, cache) == "cached text"
