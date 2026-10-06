"""Which AUTOSAR CP R24-11 Dcm SWS requirements back which rules-engine check.

The rules engine cites SWS ids in its ``Source:`` comments (``rules/nrc_order.py``,
``rules/engine.py``, ``rules/request.py``). This module is the same information as data, so it
can be shown next to a rules-engine decision (request check in the UI and API) and checked
against a local copy of the SWS PDF.

- :data:`SWS_REQUIREMENTS`: every cited id, with a one-line paraphrase in our own words (never
  SWS text), the keywords its SWS text must contain, and ``verified``.
- :data:`RULE_CITATIONS`: which trace step (``"Step 6c"`` etc.), for which services and NRC,
  each id backs.

``verified`` stays ``False`` until ``python -m uds_assistant.rules.verify_sws_map`` has been run
against the real PDF and found the id with all of its keywords;
``python -m uds_assistant.rules.verify_sws_map --mark-verified`` then flips exactly the ids
that passed. The keywords are a sanity check that the id points at the right requirement, not
a proof that the rule is right.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SWS_RELEASE = "R24-11"
"""The SWS release the ids below were taken from."""


@dataclass(frozen=True)
class SwsReq:
    """One cited SWS requirement."""

    sws_id: str
    summary: str
    """Own-words paraphrase (never SWS text)."""
    keywords: tuple[str, ...]
    """Strings the requirement's SWS text must contain (case, space and hyphen insensitive)."""
    verified: bool = False
    """True only after ``verify_sws_map`` found the id and every keyword in the local PDF."""


@dataclass(frozen=True)
class RuleCitation:
    """A rules-engine check (trace step, services, NRC) and the SWS ids that back it."""

    step: str
    """Trace label without ``Step``: ``"1"``, ``"6b'"``; ``"positive"``, ``"clock"``, ``"effect"``
    and ``"parse"`` for checks that are not numbered steps."""
    sws_ids: tuple[str, ...]
    sids: tuple[int, ...] = ()
    """Services this applies to; empty = any service."""
    nrc: int | None = None
    """NRC the check produces (``None`` for a positive outcome or a state effect)."""


# One entry per line (``--mark-verified`` edits the ``verified=`` flag in place).
_REQS: tuple[SwsReq, ...] = (
    SwsReq("SWS_Dcm_00001", "Some NRCs are suppressed only for functionally addressed requests.", ("functional",), verified=False),
    SwsReq("SWS_Dcm_00024", "Send 0x78 (response pending) when processing takes longer than P2.", ("0x78",), verified=False),
    SwsReq("SWS_Dcm_00085", "The Dcm itself answers reads of the active-session DID 0xF186.", ("0xF186",), verified=False),
    SwsReq("SWS_Dcm_00139", "Leaving a non-default session (also via S3 timeout) re-locks security.", ("security",), verified=False),
    SwsReq("SWS_Dcm_00197", "A request with an unknown service id is answered with NRC 0x11.", ("0x11",), verified=False),
    SwsReq("SWS_Dcm_00200", "A set suppress bit means no positive response is sent.", ("suppress",), verified=False),
    SwsReq("SWS_Dcm_00201", "The suppress bit is masked out of the sub-function before processing.", ("suppress",), verified=False),
    SwsReq("SWS_Dcm_00203", "After a response-pending NRC the final response is never suppressed.", ("0x78",), verified=False),
    SwsReq("SWS_Dcm_00204", "Suppress-bit handling applies only to services with sub-functions.", ("subfunction",), verified=False),
    SwsReq("SWS_Dcm_00211", "A service not enabled for the active session is answered with NRC 0x7F.", ("0x7F",), verified=False),
    SwsReq("SWS_Dcm_00251", "TesterPresent supports only the zero sub-function.", ("0x3E",), verified=False),
    SwsReq("SWS_Dcm_00272", "A length or format error found while parsing gives NRC 0x13.", ("0x13",), verified=False),
    SwsReq("SWS_Dcm_00273", "A sub-function without a configured sub-service gives NRC 0x12.", ("0x12",), verified=False),
    SwsReq("SWS_Dcm_00307", "DiagnosticSessionControl with an unconfigured session type gives NRC 0x12.", ("0x12",), verified=False),
    SwsReq("SWS_Dcm_00321", "SecurityAccess with an unconfigured access type gives NRC 0x12.", ("0x12",), verified=False),
    SwsReq("SWS_Dcm_00323", "A seed request for the already active level returns an all-zero seed.", ("seed",), verified=False),
    SwsReq("SWS_Dcm_00433", "ReadDataByIdentifier gives 0x31 only if no requested DID has read access.", ("0x31",), verified=False),
    SwsReq("SWS_Dcm_00434", "ReadDataByIdentifier gives 0x31 only if no DID is readable in the active session.", ("0x31",), verified=False),
    SwsReq("SWS_Dcm_00438", "ReadDataByIdentifier gives 0x31 only if none of the requested DIDs is supported.", ("0x31",), verified=False),
    SwsReq("SWS_Dcm_00467", "WriteDataByIdentifier on an unsupported DID gives NRC 0x31.", ("0x31",), verified=False),
    SwsReq("SWS_Dcm_00468", "WriteDataByIdentifier on a DID without write access gives NRC 0x31.", ("0x31",), verified=False),
    SwsReq("SWS_Dcm_00469", "WriteDataByIdentifier on a DID not writable in the active session gives NRC 0x31.", ("0x31",), verified=False),
    SwsReq("SWS_Dcm_00470", "WriteDataByIdentifier at the wrong security level gives NRC 0x33.", ("0x33",), verified=False),
    SwsReq("SWS_Dcm_00473", "For a fixed-length DID the written data length must match the DID size.", ("length",), verified=False),
    SwsReq("SWS_Dcm_00568", "RoutineControl with an unsupported routine identifier gives NRC 0x31.", ("0x31",), verified=False),
    SwsReq("SWS_Dcm_00570", "RoutineControl for a routine not allowed in the active session gives NRC 0x31.", ("0x31",), verified=False),
    SwsReq("SWS_Dcm_00571", "RoutineControl at the wrong security level gives NRC 0x33.", ("0x33",), verified=False),
    SwsReq("SWS_Dcm_00616", "A sub-service not enabled for the active session gives NRC 0x7E.", ("0x7E",), verified=False),
    SwsReq("SWS_Dcm_00660", "A wrong key below the attempt limit gives NRC 0x35.", ("0x35",), verified=False),
    SwsReq("SWS_Dcm_00696", "A request shorter than the service minimum gives NRC 0x13.", ("0x13",), verified=False),
    SwsReq("SWS_Dcm_00815", "A failed mode rule without its own NRC gives NRC 0x22.", ("0x22",), verified=False),
    SwsReq("SWS_Dcm_00822", "A DID write can be gated by a mode rule.", ("mode",), verified=False),
    SwsReq("SWS_Dcm_00863", "A key is compared only after a successful seed request for that level.", ("seed",), verified=False),
    SwsReq("SWS_Dcm_00869", "A routine control type that is not configured gives NRC 0x12.", ("0x12",), verified=False),
    SwsReq("SWS_Dcm_01059", "A response longer than the response buffer gives NRC 0x14.", ("0x14",), verified=False),
    SwsReq("SWS_Dcm_01060", "A memory error while clearing DTCs gives NRC 0x72.", ("0x72",), verified=False),
    SwsReq("SWS_Dcm_01140", "RoutineControl with a wrong overall request length gives NRC 0x13.", ("0x13",), verified=False),
    SwsReq("SWS_Dcm_01169", "startRoutine can be gated by a mode rule.", ("mode",), verified=False),
    SwsReq("SWS_Dcm_01265", "A groupOfDTC the DTC memory cannot select gives NRC 0x31.", ("0x31",), verified=False),
    SwsReq("SWS_Dcm_01349", "A wrong key at the attempt limit starts the delay timer and gives NRC 0x36.", ("0x36",), verified=False),
    SwsReq("SWS_Dcm_01350", "A seed request while the level's delay timer runs gives NRC 0x37.", ("0x37",), verified=False),
    SwsReq("SWS_Dcm_01397", "A failed key increments the level's attempt counter.", ("attempt",), verified=False),
    SwsReq("SWS_Dcm_01411", "Each configured sub-service is accepted with the suppress bit clear or set.", ("suppress",), verified=False),
    SwsReq("SWS_Dcm_01670", "S3 server timeout returns the ECU to the default session.", ("S3",), verified=False),
)

SWS_REQUIREMENTS: dict[str, SwsReq] = {r.sws_id: r for r in _REQS}

_RC, _ECU_RESET, _CLEAR, _RDTC, _RDBI, _SA, _WDBI, _RC31, _TP = (
    0x10, 0x11, 0x14, 0x19, 0x22, 0x27, 0x2E, 0x31, 0x3E)

RULE_CITATIONS: tuple[RuleCitation, ...] = (
    RuleCitation("1", ("SWS_Dcm_00197",), nrc=0x11),
    RuleCitation("2", ("SWS_Dcm_00211",), nrc=0x7F),
    RuleCitation("3", ("SWS_Dcm_00696", "SWS_Dcm_00272"), nrc=0x13),
    RuleCitation("4", ("SWS_Dcm_00273", "SWS_Dcm_00201", "SWS_Dcm_01411"), nrc=0x12),
    RuleCitation("4", ("SWS_Dcm_00307",), sids=(_RC,), nrc=0x12),
    RuleCitation("4", ("SWS_Dcm_00321",), sids=(_SA,), nrc=0x12),
    RuleCitation("4", ("SWS_Dcm_00251",), sids=(_TP,), nrc=0x12),
    RuleCitation("5", ("SWS_Dcm_00616",), nrc=0x7E),
    RuleCitation("5b", ("SWS_Dcm_00272",), nrc=0x13),
    RuleCitation("6a", ("SWS_Dcm_01265",), sids=(_CLEAR,), nrc=0x31),
    RuleCitation("6f", ("SWS_Dcm_01060",), sids=(_CLEAR,), nrc=0x72),
    RuleCitation("7", ("SWS_Dcm_01059",), sids=(_RDTC, _RDBI), nrc=0x14),
    RuleCitation("6a", ("SWS_Dcm_00438",), sids=(_RDBI,), nrc=0x31),
    RuleCitation("6b", ("SWS_Dcm_00433", "SWS_Dcm_00434"), sids=(_RDBI,), nrc=0x31),
    RuleCitation("6d", ("SWS_Dcm_01350",), sids=(_SA,), nrc=0x37),
    RuleCitation("6e", ("SWS_Dcm_00863",), sids=(_SA,), nrc=0x24),
    RuleCitation("6g", ("SWS_Dcm_01397", "SWS_Dcm_00660"), sids=(_SA,), nrc=0x35),
    RuleCitation("6g", ("SWS_Dcm_01397", "SWS_Dcm_01349"), sids=(_SA,), nrc=0x36),
    RuleCitation("6a", ("SWS_Dcm_00467",), sids=(_WDBI,), nrc=0x31),
    RuleCitation("6a'", ("SWS_Dcm_00468",), sids=(_WDBI,), nrc=0x31),
    RuleCitation("6b", ("SWS_Dcm_00469",), sids=(_WDBI,), nrc=0x31),
    RuleCitation("6b'", ("SWS_Dcm_00473", "SWS_Dcm_00272"), sids=(_WDBI,), nrc=0x13),
    RuleCitation("6c", ("SWS_Dcm_00470",), sids=(_WDBI,), nrc=0x33),
    RuleCitation("6d", ("SWS_Dcm_00822", "SWS_Dcm_00815"), sids=(_WDBI,), nrc=0x22),
    RuleCitation("6a", ("SWS_Dcm_00568",), sids=(_RC31,), nrc=0x31),
    RuleCitation("6b", ("SWS_Dcm_00570",), sids=(_RC31,), nrc=0x31),
    RuleCitation("6b'", ("SWS_Dcm_00869", "SWS_Dcm_00273"), sids=(_RC31,), nrc=0x12),
    RuleCitation("6b''", ("SWS_Dcm_01140",), sids=(_RC31,), nrc=0x13),
    RuleCitation("6c", ("SWS_Dcm_00571",), sids=(_RC31,), nrc=0x33),
    RuleCitation("6d", ("SWS_Dcm_01169", "SWS_Dcm_00815"), sids=(_RC31,), nrc=0x22),
    RuleCitation("8", ("SWS_Dcm_00024", "SWS_Dcm_00203"), sids=(_RC31,), nrc=0x78),
    RuleCitation("positive", ("SWS_Dcm_00200",)),
    RuleCitation("clock", ("SWS_Dcm_01670", "SWS_Dcm_00139")),
    RuleCitation("effect", ("SWS_Dcm_00085",), sids=(_RDBI,)),
    RuleCitation("effect", ("SWS_Dcm_00323",), sids=(_SA,)),
    RuleCitation("parse", ("SWS_Dcm_00201", "SWS_Dcm_00204", "SWS_Dcm_01411")),
)

_STEP_RE = re.compile(r"^Step ([0-9]+[a-z]?'*)[:\s]")
_SWS_IN_CODE_RE = re.compile(r"SWS_Dcm_\d{5}")


def deciding_step(trace: list[str]) -> str | None:
    """Label of the last numbered trace step (``"6c"``, ``"6b''"``), or ``None``."""
    for line in reversed(trace):
        m = _STEP_RE.match(line)
        if m:
            return m.group(1)
    return None


def refs_for_decision(
    sid: int | None, nrc: int | None, trace: list[str], *, suppressed: bool = False
) -> list[SwsReq]:
    """The SWS requirements behind one rules-engine decision, most specific first.

    Negative outcome: the citations of the deciding step for this service and NRC. Positive
    outcome: the suppress-bit requirement when the response was suppressed. An S3 timeout in the
    trace adds the S3 requirements. Empty when the decision rests on a design decision only.
    """
    ids: list[str] = []
    if any(line.startswith("Clock: S3 expired") for line in trace):
        ids += _ids_for("clock", sid, None)
    if nrc is not None:
        step = deciding_step(trace)
        if step is not None:
            ids += _ids_for(step, sid, nrc)
    elif suppressed:
        ids += _ids_for("positive", sid, None)
    return [SWS_REQUIREMENTS[i] for i in dict.fromkeys(ids)]


def _ids_for(step: str, sid: int | None, nrc: int | None) -> list[str]:
    specific = [c for c in RULE_CITATIONS if c.step == step and c.nrc == nrc and sid in c.sids]
    generic = [c for c in RULE_CITATIONS if c.step == step and c.nrc == nrc and not c.sids]
    return [i for c in specific + generic for i in c.sws_ids]


def ids_cited_in_code(paths: list[str] | None = None) -> set[str]:
    """Every ``SWS_Dcm_NNNNN`` mentioned in the rules package source (default: all its files)."""
    from pathlib import Path

    here = Path(__file__).resolve().parent
    files = [Path(p) for p in paths] if paths else sorted(
        p for p in here.glob("*.py") if p.name not in {"sws_map.py", "verify_sws_map.py"})
    found: set[str] = set()
    for f in files:
        found.update(_SWS_IN_CODE_RE.findall(f.read_text(encoding="utf-8")))
    return found
