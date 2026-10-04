"""Deterministic fact lookup from the parsed ECU spec and the standard-layer NRC table.

``FactLookup(spec, chunks).lookup(question)`` detects DID / routine / NRC / service /
security-level / timing references and returns :class:`~uds_assistant.qa.models.Fact` objects
whose text is generated from the spec objects (never from a model), each tied to the ``ecu:``
(or ``standard:``) chunk it came from and an exact quote from that chunk. A reference to an
entity that does not exist is reported in ``unknown`` so the caller can refuse.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from uds_assistant.qa.models import Fact
from uds_assistant.qa.text import collapse, stem
from uds_assistant.rag.model import Chunk
from uds_assistant.spec.schema import DidDef, EcuSpec, RoutineDef

_HEX2 = re.compile(r"(?<![0-9A-Za-z])0x([0-9A-Fa-f]{2})(?![0-9A-Za-z])")
_HEX4 = re.compile(r"(?<![0-9A-Za-z])(?:0x)?([0-9A-Fa-f]{4})(?![0-9A-Za-z])")
_NRC_CTX = re.compile(r"\bnrc\s*[:#]?\s*0x([0-9A-Fa-f]{2})\b|\b0x([0-9A-Fa-f]{2})\s+nrc\b", re.IGNORECASE)
_LEVEL_CTX = re.compile(r"\b(?:security\s+)?level\s*(?:0x)?([0-9A-Fa-f]{1,2})\b", re.IGNORECASE)
_SESSION_CTX = re.compile(r"session\s*0x[0-9A-Fa-f]{1,2}", re.IGNORECASE)
_NRC_BULLET = re.compile(
    r"\*\*0x([0-9A-Fa-f]{2}) (\w+)\*\*\s*—\s*(.*?)(?=\n- \*\*|\n\n|\Z)", re.DOTALL
)
_SVC_HEADING = re.compile(r"^0x([0-9A-Fa-f]{2}) (\w+)")
_SECURITY_ATTR = re.compile(
    r"\b(attempts?|wrong keys?|invalid keys?|lock-?out|delay|seed length|seed|key sub-?function)\b",
    re.IGNORECASE,
)
_TIMING_VALUE = re.compile(r"\b(how long|timeout|time-?out|value|milli\w*|ms|how many)\b", re.IGNORECASE)
_IGNORED_NAME_TOKENS = frozenset({"id", "pct", "kph", "enable", "index"})
_SUBFUNC_NAMES = {0x01: "start", 0x02: "stop", 0x03: "requestResults"}


@dataclass
class LookupResult:
    """Facts found, entities named in the question that do not exist, and what was detected."""

    facts: list[Fact] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)


def _hx(value: int, width: int = 2) -> str:
    return "0x" + format(value, f"0{width}X")


def _join(items: list[str]) -> str:
    return ", ".join(items) if items else "none"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


class FactLookup:
    """Lookup tables built once from a spec and the corpus chunks."""

    def __init__(self, spec: EcuSpec, chunks: list[Chunk]):
        self.spec = spec
        self.by_id = {c.id: c for c in chunks}
        self.nrcs: dict[int, tuple[str, str, str, str]] = {}
        """code -> (name, description, quote, chunk_id) parsed from the standard layer."""
        self.services: dict[int, str] = {}
        """service id -> name, parsed from the standard layer's ``0xNN Name`` headings."""
        for c in chunks:
            if c.layer != "standard":
                continue
            for m in _NRC_BULLET.finditer(c.text):
                code = int(m.group(1), 16)
                self.nrcs.setdefault(code, (m.group(2), collapse(m.group(3)), m.group(0), c.id))
            h = _SVC_HEADING.match(c.text.split("\n", 1)[0])
            if h:
                self.services[int(h.group(1), 16)] = h.group(2)
        self.spec_services = {s for sess in spec.sessions for s in sess.allowed_services}

    # ------------------------------------------------------------------ helpers

    def _names(self, session_ids: list[int]) -> list[str]:
        out = []
        for sid in session_ids:
            s = self.spec.get_session(sid)
            out.append(s.name if s else _hx(sid))
        return out

    def _chunk(self, kind: str, name: str) -> Chunk | None:
        return self.by_id.get(f"ecu:{kind}:{name}")

    def _fact(self, key: str, text: str, must: list[str], chunk: Chunk | None) -> Fact | None:
        if chunk is None:
            return None
        return Fact(key=key, text=text, must_include=must, chunk_id=chunk.id, quote=chunk.text)

    # ------------------------------------------------------------------ DID / routine facts

    def did_facts(self, did: DidDef) -> list[Fact]:
        """Length, read access and write access of one DID, from its spec entry."""
        read = self._names(did.read_sessions)
        if did.write_sessions:
            write = self._names(did.write_sessions)
            sec = (
                f" with security level {_hx(did.write_security_level)} unlocked"
                if did.write_security_level is not None
                else " (no security level required)"
            )
            access = (
                f"readable and writable: it can be written only in the {_join(write)} "
                f"session{'s' if len(write) > 1 else ''}{sec}"
            )
            must = [
                *write,
                *([_hx(did.write_security_level)] if did.write_security_level is not None else []),
                "writable",
            ]
        else:
            access = "read-only: it cannot be written in any session"
            must = ["read-only"]
        text = (
            f"DID {_hx(did.id, 4)} ({did.name}) is {_plural(did.length, 'byte')} long and can be "
            f"read in the {_join(read)} session{'s' if len(read) > 1 else ''}; it is {access}."
        )
        f = self._fact(
            f"did:{_hx(did.id, 4)}", text, [str(did.length), *read, *must], self._chunk("did", did.name)
        )
        return [f] if f else []

    def routine_facts(self, r: RoutineDef) -> list[Fact]:
        """Sessions, security level and sub-functions of one routine."""
        sess = self._names(r.sessions)
        subs = [_SUBFUNC_NAMES.get(s, _hx(s)) for s in r.allowed_subfunctions]
        sec = _hx(r.security_level) if r.security_level is not None else None
        sec_txt = f"requires security level {sec}" if sec else "requires no security level"
        text = (
            f"Routine {_hx(r.id, 4)} ({r.name}) can run in the {_join(sess)} "
            f"session{'s' if len(sess) > 1 else ''} and {sec_txt}; sub-functions: {_join(subs)}; "
            f"option record {_plural(r.option_record_length, 'byte')}."
        )
        f = self._fact(
            f"routine:{_hx(r.id, 4)}", text, [*sess, *([sec] if sec else [])],
            self._chunk("routine", r.name),
        )
        return [f] if f else []

    # ------------------------------------------------------------------ detection

    @staticmethod
    def _match_names(question: str, items: list[tuple[str, object]]) -> list[object]:
        """Spec entries whose name words all (or, for long names, 75%) occur in the question."""
        qtok = {stem(w) for w in re.findall(r"[a-z0-9]+", question.lower())}
        scored: list[tuple[float, object]] = []
        for name, obj in items:
            key = [stem(t) for t in name.lower().split("_") if t not in _IGNORED_NAME_TOKENS]
            if not key:
                continue
            frac = sum(1 for t in key if t in qtok) / len(key)
            if (frac == 1.0) if len(key) <= 3 else (frac >= 0.75):
                scored.append((frac * 10 + len(key), obj))
        if not scored:
            return []
        best = max(s for s, _ in scored)
        return [o for s, o in scored if s == best]

    def lookup(self, question: str) -> LookupResult:
        """Detect entities in ``question`` and return the looked-up facts (see module docstring)."""
        sp = self.spec
        res = LookupResult()
        ql = question.lower()
        consumed: list[tuple[int, int]] = []

        def _taken(pos: int) -> bool:
            return any(a <= pos < b for a, b in consumed)

        # NRC references: "NRC 0x33", "0x33 NRC", and NRC names
        for m in _NRC_CTX.finditer(question):
            consumed.append(m.span())
            self._nrc(int(m.group(1) or m.group(2), 16), res)
        for code, (name, _d, _q, _c) in self.nrcs.items():
            if re.search(rf"\b{re.escape(name)}\b", question, re.IGNORECASE):
                self._nrc(code, res)

        # 4-hex tokens: DIDs / routines (unknown ones are refused)
        for m in _HEX4.finditer(question):
            tok = m.group(1)
            bare = not m.group(0).lower().startswith("0x")
            if bare and not (any(c.isdigit() for c in tok) and any(c.isalpha() for c in tok)):
                continue
            if _taken(m.start()):
                continue
            val = int(tok, 16)
            if (d := sp.get_did(val)) is not None:
                res.facts += self.did_facts(d)
                res.kinds.append("did")
            elif (r := sp.get_routine(val)) is not None:
                res.facts += self.routine_facts(r)
                res.kinds.append("routine")
            else:
                res.unknown.append(f"{_hx(val, 4)} is not a DID or routine defined in the ECU spec")
            consumed.append(m.span())

        # names of DIDs / routines (only when no id was given)
        if not res.facts and not res.unknown:
            dm = self._match_names(question, [(d.name, d) for d in sp.dids])
            rm = self._match_names(question, [(r.name, r) for r in sp.routines])
            if dm and (not rm or "routine" not in ql):
                for d in dm:
                    res.facts += self.did_facts(d)  # type: ignore[arg-type]
                res.kinds.append("did")
            elif rm:
                for r in rm:
                    res.facts += self.routine_facts(r)  # type: ignore[arg-type]
                res.kinds.append("routine")

        # 2-hex tokens: services (known / unknown) and bare NRC codes; "level 0x01" and
        # "session 0x03" are level / session references, not services
        for m in _LEVEL_CTX.finditer(question):
            consumed.append(m.span())
        for m in _SESSION_CTX.finditer(question):
            consumed.append(m.span())
        service_ids: list[int] = []
        for m in _HEX2.finditer(question):
            if _taken(m.start()):
                continue
            val = int(m.group(1), 16)
            if val in self.spec_services:
                service_ids.append(val)
            elif val in self.nrcs and not res.facts:
                self._nrc(val, res)
            else:
                res.unknown.append(f"service {_hx(val)} is not defined in the ECU spec")
        for sid, name in self.services.items():
            parts = re.findall(r"[A-Z][a-z]+|[A-Z]+(?![a-z])|[a-z]+", name)
            pat = r"\s*".join(parts)
            if sid in self.spec_services and sid not in service_ids and re.search(
                rf"\b{pat}\b", question, re.IGNORECASE
            ):
                service_ids.append(sid)
        if service_ids and "session" in ql and not res.facts:
            for sid in service_ids:
                self._service_sessions(sid, res)

        # timing values
        if not res.facts and _TIMING_VALUE.search(question):
            self._timing(question, res)

        # security levels
        if not res.facts and not res.unknown:
            lv = [int(m.group(1), 16) for m in _LEVEL_CTX.finditer(question)]
            if _SECURITY_ATTR.search(question) and ("security" in ql or lv):
                self._security(lv, res)
            elif lv and "security" in ql:
                for v in lv:
                    if sp.get_security_level(v) is None:
                        res.unknown.append(f"security level {_hx(v)} is not defined in the ECU spec")
        return res

    # ------------------------------------------------------------------ individual lookups

    def _nrc(self, code: int, res: LookupResult) -> None:
        if code not in self.nrcs:
            res.unknown.append(f"NRC {_hx(code)} is not in the NRC table of the approved sources")
            return
        name, desc, quote, cid = self.nrcs[code]
        text = f"NRC {_hx(code)} is {name}: {desc}"
        res.facts.append(
            Fact(key=f"nrc:{_hx(code)}", text=text, must_include=[_hx(code), name],
                 chunk_id=cid, quote=quote)
        )
        res.kinds.append("nrc")

    def nrc_fact(self, code: int) -> Fact | None:
        """The NRC-meaning fact for ``code`` (None if the table does not have it)."""
        tmp = LookupResult()
        self._nrc(code, tmp)
        return tmp.facts[0] if tmp.facts else None

    def _service_sessions(self, sid: int, res: LookupResult) -> None:
        sess = [s for s in self.spec.sessions if sid in s.allowed_services]
        name = self.services.get(sid)
        label = f"Service {_hx(sid)}" + (f" ({name})" if name else "")
        allowed = [s.name for s in sess]
        absent = [s.name for s in self.spec.sessions if sid not in s.allowed_services]
        text = f"{label} is allowed in the {_join(allowed)} session{'s' if len(allowed) != 1 else ''}"
        if absent:
            text += f" and not in the {_join(absent)} session{'s' if len(absent) != 1 else ''}."
        else:
            text += "."
        first = True
        for s in sess:
            ch = self._chunk("session", s.name)
            if ch:
                res.facts.append(
                    Fact(key=f"service:{_hx(sid)}:{s.name}", text=text if first else "",
                         must_include=allowed if first else [], chunk_id=ch.id, quote=ch.text)
                )
                first = False
        res.kinds.append("service")

    def _timing(self, question: str, res: LookupResult) -> None:
        ql = question.lower()
        params: list[str] = []
        if re.search(r"p2\s*\*|p2[\s-]*star", ql):
            params.append("p2_star_ms")
        elif re.search(r"\bp2\b", ql):
            params.append("p2_ms")
        if re.search(r"\bs3\b", ql):
            params.append("s3_ms")
        if not params:
            return
        label = {"p2_ms": "P2", "p2_star_ms": "P2*", "s3_ms": "S3"}
        named = [s for s in self.spec.sessions if re.search(rf"\b{s.name}\b", ql)]
        sessions = named or list(self.spec.sessions)
        same = all(len({getattr(s.timing, p) for s in sessions}) == 1 for p in params)
        if same:
            vals = [(p, getattr(sessions[0].timing, p)) for p in params]
            scope = (
                f"the {_join([s.name for s in sessions])} session{'s' if len(sessions) > 1 else ''}"
                if named
                else f"every session ({_join([s.name for s in sessions])})"
            )
            text = f"In {scope}: " + "; ".join(f"{label[p]} = {v} ms" for p, v in vals) + "."
            must = [f"{v} ms" for _p, v in vals] + [s.name for s in sessions]
        else:
            segs = [
                f"in the {s.name} session " + ", ".join(f"{label[p]} = {getattr(s.timing, p)} ms" for p in params)
                for s in sessions
            ]
            text = "; ".join(segs).capitalize() + "."
            must = [f"{getattr(s.timing, p)} ms" for s in sessions for p in params] + [
                s.name for s in sessions
            ]
        first = True
        for s in sessions:
            ch = self._chunk("session", s.name)
            if ch:
                res.facts.append(
                    Fact(key=f"timing:{s.name}", text=text if first else "",
                         must_include=must if first else [], chunk_id=ch.id, quote=ch.text)
                )
                first = False
        res.kinds.append("timing")

    def _security(self, levels: list[int], res: LookupResult) -> None:
        sp = self.spec
        targets = []
        for v in levels:
            lvl = sp.get_security_level(v)
            if lvl is None:
                res.unknown.append(f"security level {_hx(v)} is not defined in the ECU spec")
            else:
                targets.append(lvl)
        if res.unknown:
            return
        for lvl in targets or sp.security_levels:
            sess = self._names(lvl.allowed_sessions)
            text = (
                f"Security level {_hx(lvl.level)} ({lvl.name}) allows {lvl.max_attempts} attempts "
                f"before a lockout delay of {lvl.delay_ms} ms; the seed is {lvl.seed_length} bytes; "
                f"it can be requested only in the {_join(sess)} session{'s' if len(sess) > 1 else ''}."
            )
            ch = self._chunk("security_level", lvl.name)
            if ch:
                res.facts.append(
                    Fact(
                        key=f"security:{_hx(lvl.level)}", text=text,
                        must_include=[_hx(lvl.level), f"{lvl.max_attempts} attempts",
                                      f"{lvl.delay_ms} ms", str(lvl.seed_length), *sess],
                        chunk_id=ch.id, quote=ch.text,
                    )
                )
        res.kinds.append("security")
