"""Deterministic, rule-based stand-in for an LLM (``LLM_MODE=mock``).

:class:`MockLLM` implements the same :class:`~uds_assistant.llm.base.LLMClient`
interface as the Ollama client but answers with keyword/regex rules over the
JSON context block that every agent prompt carries (see
:func:`~uds_assistant.llm.base.build_prompt`). Same input -> same output, no
randomness, no model, no network.

Like a real LLM it never sees or produces bytes: parsing returns identifier
references and intents, planning returns ``(template_id, option_index)``
choices from the options the agent enumerated, and explanations are prose.
"""

from __future__ import annotations

import re
from typing import Any, TypeVar

from pydantic import BaseModel

from uds_assistant.llm.base import (
    LLMError,
    ParsedRequirement,
    PlannedTest,
    TestPlan,
    extract_context,
)

T = TypeVar("T", bound=BaseModel)

_HEX_TOKEN_RE = re.compile(r"\b0x[0-9a-fA-F]+\b")
_DTC_TOKEN_RE = re.compile(r"\b[PCBU][0-9A-F]{5}\b")
_WORD_RE = re.compile(r"[a-z][a-z0-9\-]+")

# Keyword that most recently precedes a hex token decides what kind of
# identifier it is ("DID (0x0100)", "security level 0x01", ...). Kinds mapped
# to None mean "this hex is a sub-function value, not a spec identifier".
_KIND_KEYWORDS: tuple[tuple[str, str | None], ...] = (
    ("did", "dids"),
    ("data identifier", "dids"),
    ("routine", "routines"),
    ("session", "sessions"),
    ("level", "security_levels"),
    ("service", "services"),
    ("sid", "services"),
    ("subfunction", None),
    ("sub-function", None),
    ("reset", None),
)
_KIND_WINDOW = 40
_WORD_START = r"(?<![a-z0-9])"

_SERVICE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("diagnosticsessioncontrol", "0x10"),
    ("session control", "0x10"),
    ("switch", "0x10"),
    ("enter", "0x10"),
    ("ecureset", "0x11"),
    ("ecu reset", "0x11"),
    ("hard reset", "0x11"),
    ("soft reset", "0x11"),
    ("cleardiagnosticinformation", "0x14"),
    ("clear dtc", "0x14"),
    ("readdtcinformation", "0x19"),
    ("dtc", "0x19"),
    ("readdatabyidentifier", "0x22"),
    ("read(?!dtc)", "0x22"),
    ("securityaccess", "0x27"),
    ("security", "0x27"),
    ("writedatabyidentifier", "0x2E"),
    ("writ", "0x2E"),
    ("accept values", "0x2E"),
    ("routinecontrol", "0x31"),
    ("routine", "0x31"),
    ("testerpresent", "0x3E"),
    ("tester present", "0x3E"),
)

_INTENT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("negative", ("shall not", "only", "invalid", "reject", "require", "not accept", "lock",
                  "before")),
    ("session", ("session",)),
    ("security", ("security", "seed", "key", "unlock", "lock out")),
    ("timing", ("timeout", "timer", "s3", "expir", "seconds", "p2")),
    ("range", ("between", "range", "inclusive", "accept values")),
    ("length", ("length",)),
    ("sequence", ("before", "sequence", "order")),
    ("conditions", ("stationary", "condition", "moving", "speed")),
    ("subfunction", ("subfunction", "sub-function")),
    ("lockout", ("lock out", "lockout", "attempts", "invalid key")),
    ("suppress", ("suppress", "testerpresent", "tester present")),
    ("dtc", ("dtc", "trouble code")),
    ("read", ("read(?!dtc)",)),
    ("write", ("writ", "accept values")),
    ("routine", ("routine",)),
)

_STOPWORDS = frozenset(
    {
        "the", "and", "shall", "be", "able", "to", "in", "any", "of", "a", "an", "or", "with",
        "only", "when", "while", "for", "after", "before", "this", "that", "from", "into",
        "back", "its", "it", "is", "are", "not", "all", "every", "than",
    }
)

# Templates that are per-session variants of the same check: when the
# requirement names sessions, prefer the options in those sessions.
_PER_SESSION_TEMPLATES = frozenset(
    {
        "read_did_positive",
        "read_did_wrong_session_or_unknown",
        "unsupported_subfunction",
        "suppress_positive_response",
    }
)
_MAX_OPTIONS_PER_TEMPLATE = 6


class MockLLM:
    """Deterministic keyword/regex "LLM" used in mock mode and in tests."""

    name = "mock"

    def complete_json(self, system: str, prompt: str, schema: type[T]) -> T:
        """Answer a structured request; dispatches on ``schema``."""
        ctx = extract_context(prompt)
        if issubclass(schema, ParsedRequirement):
            return schema.model_validate(_parse(ctx).model_dump())
        if issubclass(schema, TestPlan):
            return schema.model_validate(_plan(ctx).model_dump())
        raise LLMError(f"MockLLM has no rule for schema {schema.__name__}")

    def complete_text(self, system: str, prompt: str) -> str:
        """Write a templated prose explanation from the prompt's context."""
        return _explain(extract_context(prompt))


# ------------------------------------------------------------------------------------ parse


def _classify_hex(text_lower: str, start: int) -> str | None | bool:
    """Return the identifier kind for a hex token at ``start``.

    ``False`` means no keyword was found nearby (caller decides by spec lookup).
    """
    window = text_lower[max(0, start - _KIND_WINDOW) : start]
    best_pos = -1
    best_kind: str | None | bool = False
    for keyword, kind in _KIND_KEYWORDS:
        pos = window.rfind(keyword)
        if pos > best_pos:
            best_pos, best_kind = pos, kind
    return best_kind


def _has(text_lower: str, keyword: str) -> bool:
    """True if regex fragment ``keyword`` matches ``text_lower`` at a word start."""
    return re.search(_WORD_START + keyword, text_lower) is not None


def _name_phrases(name: str) -> list[str]:
    """Phrases that refer to a spec entry by name, e.g. ``wiper sensitivity level``."""
    words = name.lower().split("_")
    phrases = [" ".join(words)]
    if len(words) > 2:
        phrases.append(" ".join(words[:-1]))
    return phrases


def _parse(ctx: dict[str, Any]) -> ParsedRequirement:
    text = str(ctx.get("requirement_text", ""))
    lower = text.lower()
    flat = lower.replace("-", " ")
    index: dict[str, dict[str, str]] = ctx.get("spec_index", {}) or {}
    found: dict[str, list[str]] = {
        "services": [], "dids": [], "routines": [], "sessions": [], "security_levels": [],
    }

    def add(kind: str, ident: str) -> None:
        if ident not in found[kind]:
            found[kind].append(ident)

    for match in _HEX_TOKEN_RE.finditer(text):
        ident = "0x" + match.group(0)[2:].upper()
        kind = _classify_hex(lower, match.start())
        if kind is None:
            continue
        if kind is False:
            for k in ("dids", "routines"):
                if ident in index.get(k, {}):
                    add(k, ident)
            continue
        add(str(kind), ident)

    for kind in ("dids", "routines"):
        for ident, name in index.get(kind, {}).items():
            for phrase in _name_phrases(name):
                if re.search(rf"\b{re.escape(phrase)}\b", flat):
                    add(kind, ident)
                    break

    for keyword, sid in _SERVICE_KEYWORDS:
        if _has(lower, keyword):
            add("services", sid)

    dtcs = [m.group(0) for m in _DTC_TOKEN_RE.finditer(text)]
    intents = ["positive"] + [
        intent for intent, kws in _INTENT_KEYWORDS if any(_has(lower, kw) for kw in kws)
    ]

    keywords: list[str] = []
    for word in _WORD_RE.findall(lower):
        if len(word) > 3 and word not in _STOPWORDS and word not in keywords:
            keywords.append(word)

    return ParsedRequirement(
        services=sorted(found["services"]),
        dids=found["dids"],
        routines=found["routines"],
        sessions=found["sessions"],
        security_levels=found["security_levels"],
        dtcs=dtcs,
        intents=intents,  # type: ignore[arg-type]
        keywords=keywords[:12],
    )


# ------------------------------------------------------------------------------------- plan


def _refs(option: dict[str, Any], key: str) -> set[str]:
    return set((option.get("refs") or {}).get(key, []))


def _hits(option: dict[str, Any], key: str, wanted: set[str]) -> bool:
    return bool(_refs(option, key) & wanted)


def _plan(ctx: dict[str, Any]) -> TestPlan:
    req = ctx.get("requirement", {}) or {}
    intents = set(req.get("intents", []))
    r_services = set(req.get("services", []))
    r_dids = set(req.get("dids", []))
    r_routines = set(req.get("routines", []))
    r_sessions = set(req.get("sessions", []))
    r_levels = set(req.get("security_levels", []))
    r_dtcs = set(req.get("dtcs", []))
    rejected = {
        (str(r.get("template_id")), int(r.get("option_index", -1)))
        for r in ctx.get("rejected", []) or []
    }
    templates: list[dict[str, Any]] = ctx.get("templates", []) or []

    def first_pass(tid: str, opt: dict[str, Any]) -> str | None:
        """Identifier-driven choices; return a rationale or None."""
        if tid == "read_did_positive":
            if _hits(opt, "dids", r_dids) and ("read" in intents or "0x22" in r_services):
                return "Requirement references this DID for reading."
        elif tid == "read_did_wrong_session_or_unknown":
            if "0x22" in r_services and (
                _hits(opt, "dids", r_dids) or "unknown_identifier" in opt.get("flags", [])
            ):
                return "Negative read: DID unknown or not readable in this session."
        elif tid in (
            "write_did_secured_positive",
            "write_did_without_security",
            "write_did_out_of_range",
            "write_did_invalid_length",
        ):
            if _hits(opt, "dids", r_dids) and intents & {"write", "range", "security", "length"}:
                return "Requirement constrains writing this DID."
        elif tid == "condition_not_met":
            if _hits(opt, "dids", r_dids) or _hits(opt, "routines", r_routines):
                return "Referenced identifier is gated by an environmental condition."
        elif tid == "routine_sequence":
            if _hits(opt, "routines", r_routines):
                return "Requirement references this routine; check its start/stop sequencing."
        elif tid == "dtc_read_clear" and (
            r_services & {"0x19", "0x14"} or "dtc" in intents or _hits(opt, "dtcs", r_dtcs)
        ):
            return "Requirement concerns DTC reading/clearing."
        return None

    chosen: list[PlannedTest] = []
    taken: set[tuple[str, int]] = set()

    def take(tid: str, opts: list[tuple[dict[str, Any], str]]) -> None:
        if tid in _PER_SESSION_TEMPLATES and r_sessions:
            narrowed = [(o, r) for o, r in opts if _hits(o, "sessions", r_sessions)]
            opts = narrowed or opts
        for opt, rationale in opts[:_MAX_OPTIONS_PER_TEMPLATE]:
            key = (tid, int(opt["index"]))
            if key in rejected or key in taken:
                continue
            taken.add(key)
            chosen.append(PlannedTest(template_id=tid, option_index=key[1], rationale=rationale))

    for tpl in templates:
        tid = str(tpl.get("template_id"))
        picks = []
        for opt in tpl.get("options", []):
            why = first_pass(tid, opt)
            if why:
                picks.append((opt, why))
        if tid == "read_did_wrong_session_or_unknown":
            # Keep at most one unknown-DID probe plus the referenced-DID ones.
            unknown = [p for p in picks if "unknown_identifier" in p[0].get("flags", [])]
            known = [p for p in picks if p not in unknown]
            if r_sessions:
                unknown = [p for p in unknown if _hits(p[0], "sessions", r_sessions)] or unknown
            picks = known + unknown[:1]
        take(tid, picks)

    # Second pass: derived checks use identifiers implied by the first pass
    # (e.g. a secured DID implies its security level and write session).
    implied: dict[str, set[str]] = {
        "services": set(r_services), "sessions": set(r_sessions), "security_levels": set(r_levels),
    }
    by_id = {str(t.get("template_id")): t for t in templates}
    for pt in chosen:
        opt = by_id[pt.template_id]["options"][pt.option_index]
        for key in implied:
            implied[key] |= _refs(opt, key)

    for tpl in templates:
        tid = str(tpl.get("template_id"))
        picks = []
        for opt in tpl.get("options", []):
            why: str | None = None
            if tid == "security_invalid_key_lockout":
                if _hits(opt, "security_levels", implied["security_levels"]) and (
                    intents & {"security", "lockout", "write"}
                ):
                    why = "Security level involved; verify invalid-key lockout and delay."
            elif tid == "s3_timeout_reverts_session":
                if _hits(opt, "sessions", implied["sessions"]) and (
                    intents & {"session", "timing", "security", "write"}
                ):
                    why = "Non-default session involved; verify S3 timeout reverts it."
                elif not implied["sessions"] and {"session", "timing"} <= intents:
                    why = "Requirement concerns the session timer; verify S3 timeout."
            elif tid == "service_not_in_session":
                if _hits(opt, "services", implied["services"]):
                    why = "Service involved; verify it is rejected where the session forbids it."
            elif tid == "unsupported_subfunction":
                if _hits(opt, "services", r_services) and (
                    intents & {"subfunction", "negative", "session", "security"}
                ):
                    why = "Service named by the requirement; probe an unsupported sub-function."
            elif tid == "suppress_positive_response" and _hits(opt, "services", r_services):
                why = "Service supports suppressPosRspMsgIndicationBit; check it."
            if why:
                picks.append((opt, why))
        take(tid, picks)

    return TestPlan(tests=chosen)


# ------------------------------------------------------------------------------------ explain


def _explain(ctx: dict[str, Any]) -> str:
    test = ctx.get("test", {}) or {}
    title = test.get("title", "this test")
    category = test.get("category", "")
    req_id = test.get("requirement_id", "")
    description = str(test.get("template_description", "")).rstrip(".")
    rationale = str(test.get("rationale", "")).strip()
    steps = test.get("step_descriptions", []) or []
    refs = test.get("citation_refs", []) or []
    parts = [
        f"{title}. This {category} test supports requirement {req_id}.",
        f"Template intent: {description}." if description else "",
        f"Why it was chosen: {rationale}" if rationale else "",
        f"It performs {len(steps)} step(s); expected responses come from the rules engine.",
        f"Evidence: {', '.join(refs)}." if refs else "",
    ]
    return " ".join(p for p in parts if p)
