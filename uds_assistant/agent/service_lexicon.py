"""Vocabulary used to decide whether a parsed service / session / security level has evidence.

Everything here is written from three sources only: the service names in
``protocol/constants.py``, the entity names in ``data/bcm_spec.yaml`` and general UDS /
automotive-diagnostics vocabulary. It is NOT derived from any requirement set's phrasing.
To extend it, add a regex alternative to the right entry; nothing else needs to change.
All patterns are matched case-insensitively against the requirement text.

Two tiers per service:

* ``SERVICE_STRONG``: a hit is *lexical evidence* by itself (rule (a) of
  :mod:`uds_assistant.agent.grounding`).
* ``SERVICE_WEAK``: a single word that is too ambiguous to count alone ("value", "mode",
  "test"). It only counts together with retrieval support (rule (c)); retrieval alone
  never counts.
"""

from __future__ import annotations

import re

_I = re.IGNORECASE
_SEP = r"[\s_-]*"  # separator inside compound words: "self-test", "self test", "selftest"
_GAP = r"[^.;:!?]{0,40}?"  # a few words between a verb and its object, inside one clause

# Objects that mean "the fault memory" (spec DTC names: short circuit / stuck / overcurrent).
_FAULT_OBJECT = (
    r"(?:dtcs?|faults?|trouble\s+codes?|diagnostic\s+trouble|fault\s+(?:codes?|memory)|"
    r"error\s+codes?|diagnostic\s+(?:information|trouble)|short\s+circuit|overcurrent|stuck)"
)
_CLEAR_VERB = r"(?:clear(?:s|ed|ing)?|eras(?:e|es|ed|ing)|wip(?:e|es|ed|ing)|delet(?:e|es|ed|ing)|purg(?:e|es|ed|ing))"
_READ_VERB = (
    r"(?:read(?:s|ing)?|report(?:s|ed|ing)?|list(?:s|ed|ing)?|retriev(?:e|es|ed|ing)|"
    r"query|queries|fetch(?:es|ed|ing)?|get|gets|check(?:s|ed|ing)?|show(?:s|ed|ing)?|"
    r"count(?:s|ed|ing)?|inspect(?:s|ed|ing)?)"
)

# ----- strong lexicon: a hit is evidence on its own ------------------------------------
SERVICE_STRONG: dict[str, tuple[str, ...]] = {
    # 0x22 ReadDataByIdentifier: read / report a value. "read" followed by a fault-memory
    # object is the 0x19 idiom and is excluded here.
    "0x22": (
        rf"\bread(?:s|ing|able|out)?\b(?!\s+(?:the\s+)?(?:stored\s+|active\s+|confirmed\s+|pending\s+)?{_FAULT_OBJECT})",
        r"\breadable\b",
        r"\bretriev(?:e|es|ed|al|ing)\b(?!\s+(?:the\s+)?" + _FAULT_OBJECT + ")",
        r"\breport(?:s|ed|ing)?\b(?!\s+(?:the\s+)?(?:stored\s+|active\s+)?" + _FAULT_OBJECT + ")",
        r"\b(?:fetch|query|look\s*up)\b(?!\s+(?:the\s+)?" + _FAULT_OBJECT + ")",
        r"\b(?:ReadDataByIdentifier|read\s+data\s+by\s+identifier)\b",
        r"\bdata\s+identifiers?\b",
    ),
    # 0x2E WriteDataByIdentifier: write / set / change / configure / store a value.
    "0x2E": (
        r"\b(?:write|writes|writing|written|writable|overwrit\w*|rewrit\w*)\b",
        r"\b(?:set|sets|setting)\b(?!\s+of\b)",
        r"\b(?:chang(?:e|es|ed|ing|eable)|modif(?:y|ies|ied|ying)|updat(?:e|es|ed|ing)|adjust(?:s|ed|ing)?)\b",
        r"\b(?:configur(?:e|es|ed|ing|able|ation)|stor(?:e|es|ing)|persist(?:s|ed|ing)?|assign(?:s|ed|ing)?|cod(?:e|ing))\b",
        r"\b(?:program(?:s|med)?\s+(?:the\s+)?(?:value|variant|setting))\b",
        r"\b(?:WriteDataByIdentifier)\b",
    ),
    # 0x10 DiagnosticSessionControl: session / mode names.
    "0x10": (
        r"\bsessions?\b",
        r"\b(?:extended|programming|default|diagnostic|flash|boot|engineering)\s+(?:session|mode)s?\b",
        r"\b(?:extended|programming)\b",
        r"\b(?:flash(?:ing)?|reflash\w*|reprogram\w*)\b",
        r"\b(?:DiagnosticSessionControl|session\s+control)\b",
    ),
    # 0x11 ECUReset: reset / restart / reboot / power-cycle ("factory reset" is a routine /
    # DID name in the spec, not an ECU reset).
    "0x11": (
        r"(?<!factory\s)\breset(?:s|ting)?\b(?!\s+(?:flag|counter|reason))",
        r"\b(?:re-?start(?:s|ed|ing)?|re-?boot(?:s|ed|ing)?|reinitiali[sz]\w*)\b",
        rf"\bpower{_SEP}(?:cycl\w*|down|up|off|on)\b",
        r"\b(?:hard|soft|key[\s-]?off[\s-]?on)\s+reset\b",
        r"\b(?:ECUReset|ecu\s+reset)\b",
    ),
    # 0x14 ClearDiagnosticInformation: a clearing verb close to a fault-memory object.
    "0x14": (
        rf"\b{_CLEAR_VERB}\b{_GAP}\b{_FAULT_OBJECT}\b",
        rf"\b{_FAULT_OBJECT}\b{_GAP}\b(?:cleared|erased|wiped|deleted)\b",
        r"\b(?:ClearDiagnosticInformation|clear\s+diagnostic\s+information)\b",
    ),
    # 0x19 ReadDTCInformation: a read verb near a fault-memory object, or status-mask talk.
    "0x19": (
        rf"\b{_READ_VERB}\b{_GAP}\b{_FAULT_OBJECT}\b",
        r"\bstatus\s+mask\b",
        r"\b(?:number|count)\s+of\s+(?:dtcs?|faults?)\b",
        r"\b(?:ReadDTCInformation|read\s+dtc\s+information)\b",
    ),
    # 0x27 SecurityAccess: unlock / seed / key / authenticate.
    "0x27": (
        r"\bunlock(?:s|ed|ing)?\b",
        r"\bsecurity\b",
        r"\bseeds?\b",
        r"\bkeys?\b(?!\s*[-\s]?(?:off|on)\b)",
        r"\bauthenticat\w*\b",
        r"\b(?:challenge|response\s+key|access\s+level|secure\s+access|SecurityAccess)\b",
        r"\blockout\b",
    ),
    # 0x31 RoutineControl: routine / self-test / calibration / start-stop-results / run
    # (spec routine names: lighting_self_test, door_actuator_calibration, nvm_factory_restore).
    "0x31": (
        r"\broutines?\b",
        rf"\bself{_SEP}tests?\b",
        r"\bcalibrat\w*\b",
        r"\b(?:factory\s+restore|nvm\s+restore|restore\s+(?:the\s+)?factory)\b",
        (
            r"\b(?:start(?:s|ed|ing)?|stop(?:s|ped|ping)?|launch\w*|trigger\w*|"
            r"initiat(?:e|es|ed|ing)|execut(?:e|es|ed|ing|ion)|run|runs|running|"
            r"perform(?:s|ed|ing)?)\b"
            r"(?=[^.;]{0,40}\b(?:routine|test|calibration|check|procedure|restore|cycle)\b)"
        ),
        r"\b(?:routine\s+)?results?\b(?=[^.;]{0,40}\b(?:routine|test|calibration|procedure)\b)",
        r"\b(?:RoutineControl|routine\s+control)\b",
        r"\b(?:start|stop|result)Routine\b",
    ),
    # 0x3E TesterPresent: keep-alive.
    "0x3E": (
        r"\btester[\s_-]*present\b",
        r"\bkeep[\s_-]*alive\b",
        r"\bkeep(?:s|ing)?\s+(?:the\s+)?(?:session|ecu|link|connection)\s+(?:alive|active|open)\b",
        r"\bheart[\s-]?beat\b",
        r"\bs3\b",
        r"\b(?:session|S3)\s+(?:timeout|timer|expir\w*)\b",
        r"\bidle\s+timeout\b",
    ),
}

# ----- weak words: only count with retrieval support (rule (c)) ------------------------
SERVICE_WEAK: dict[str, tuple[str, ...]] = {
    "0x22": (r"\bvalues?\b", r"\bdata\b", r"\bidentifiers?\b", r"\bshow\w*\b", r"\bdisplay\w*\b",
             r"\bavailable\b", r"\baccessible\b", r"\brespon\w+\b", r"\breturn\w*\b", r"\bexpos\w+\b"),
    "0x2E": (r"\bvalues?\b", r"\bnew\b", r"\bdata\b", r"\bprogram\w*\b", r"\bsave\w*\b",
             r"\baccept\w*\b", r"\breject\w*\b"),
    "0x10": (r"\bmodes?\b", r"\benter\w*\b", r"\bswitch\w*\b", r"\btransition\w*\b",
             r"\bdiagnostic\b", r"\bdefault\b"),
    "0x11": (r"\bpower\b", r"\bcycle\w*\b", r"\bstartup\b", r"\bboot\w*\b", r"\binitiali[sz]\w*\b"),
    "0x14": (r"\bclear\w*\b", r"\bera\w+\b", r"\bdelete\w*\b", r"\bmemory\b", r"\bstored\b"),
    "0x19": (r"\bdtcs?\b", r"\bfaults?\b", r"\btrouble\b", r"\bcodes?\b", r"\bstatus\b",
             r"\bsnapshot\b", r"\bmask\b"),
    "0x27": (r"\block\w*\b", r"\baccess\b", r"\bsecure\b", r"\bprotect\w*\b", r"\blevel\b",
             r"\battempts?\b", r"\bdelay\b"),
    "0x31": (r"\btests?\b", r"\bactuator\b", r"\bexecut\w*\b", r"\bstart\w*\b", r"\bstop\w*\b",
             r"\bperform\w*\b", r"\bcheck\w*\b", r"\bprocedure\b", r"\bresults?\b"),
    "0x3E": (r"\balive\b", r"\btimeout\b", r"\btimer\b", r"\bperiodic\w*\b", r"\bidle\b",
             r"\bexpir\w*\b", r"\bpresent\b"),
}

# ----- intent words used by rule (b): kept identifier + intent implies a service --------
READ_INTENT_WORDS = (
    r"\b(?:read\w*|report\w*|verif(?:y|ies|ied|ying)|check\w*|ensur\w*|confirm\w*|show\w*|"
    r"display\w*|expos\w*|return\w*|respond\w*|retriev\w*|available|accessible|query|fetch)\b"
)
WRITE_INTENT_WORDS = SERVICE_STRONG["0x2E"]  # the same write vocabulary
CLEAR_INTENT_WORDS = (rf"\b{_CLEAR_VERB}\b",)
READ_INTENTS = frozenset({"read"})
"""``ParsedRequirement.intents`` values that mean "read/report"."""
WRITE_INTENTS = frozenset({"write", "range", "length"})
"""Intents that only make sense for a write."""
CLEAR_INTENTS = frozenset({"dtc"})
"""``dtc`` is a DTC-handling intent (read or clear; the text words decide)."""

# ----- sessions: words that name each session id ---------------------------------------
SESSION_WORDS: dict[str, tuple[str, ...]] = {
    "0x01": (r"\bdefault\b", r"\bnormal\s+(?:session|mode|operation)\b", r"\bpower[\s-]?on\s+session\b"),
    "0x02": (r"\bprogramming\b", r"\bflash\w*\b", r"\breprogram\w*\b", r"\bboot\w*\b", r"\bdownload\b"),
    "0x03": (r"\bextended\b", r"\bdiagnostic\s+(?:session|mode)\b", r"\bengineering\b", r"\bdiag\b"),
}
ALL_SESSIONS_WORDS = (
    r"\b(?:any|every|all|each|whatever)\s+(?:diagnostic\s+)?sessions?\b",
    r"\bregardless\s+of\s+(?:the\s+)?(?:active\s+)?session\b",
)
"""Phrases that name every session without naming one."""


def compile_all(patterns: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    """Compile a tuple of regex sources (case-insensitive)."""
    return tuple(re.compile(p, _I) for p in patterns)


STRONG_RE = {sid: compile_all(p) for sid, p in SERVICE_STRONG.items()}
WEAK_RE = {sid: compile_all(p) for sid, p in SERVICE_WEAK.items()}
READ_INTENT_RE = re.compile(READ_INTENT_WORDS, _I)
WRITE_INTENT_RE = compile_all(WRITE_INTENT_WORDS)
CLEAR_INTENT_RE = compile_all(CLEAR_INTENT_WORDS)
SESSION_RE = {sid: compile_all(p) for sid, p in SESSION_WORDS.items()}
ALL_SESSIONS_RE = compile_all(ALL_SESSIONS_WORDS)


def first_hit(patterns: tuple[re.Pattern[str], ...], text: str) -> str | None:
    """The matched text of the first pattern that hits ``text`` (None if no pattern does)."""
    for pat in patterns:
        m = pat.search(text)
        if m:
            return m.group(0)
    return None
