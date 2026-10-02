"""Enumerated choices the agent offers the LLM: spec index and template options.

The LLM never invents parameters. Instead, for every registered template the
agent enumerates ``applicable_params(spec, template_id)`` and describes each
entry with a human-readable summary plus the spec identifiers it touches
(``refs``). The LLM answers with ``(template_id, option_index)`` only.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from uds_assistant.protocol.constants import ServiceId
from uds_assistant.spec.schema import EcuSpec
from uds_assistant.testgen.templates import TEMPLATES, applicable_params


def hex2(value: int) -> str:
    """Format a one-byte identifier like ``0x2E``."""
    return f"0x{value:02X}"


def hex4(value: int) -> str:
    """Format a two-byte identifier like ``0xF190``."""
    return f"0x{value:04X}"


def service_name(sid: int) -> str:
    """Readable service name, e.g. ``ReadDataByIdentifier``."""
    try:
        return "".join(w.capitalize() for w in ServiceId(sid).name.split("_"))
    except ValueError:
        return f"Service{sid:02X}"


def spec_index(spec: EcuSpec) -> dict[str, dict[str, str]]:
    """Map every spec identifier (as a hex string / DTC code) to its name."""
    sids = sorted({s for sess in spec.sessions for s in sess.allowed_services})
    return {
        "services": {hex2(s): service_name(s) for s in sids},
        "dids": {hex4(d.id): d.name for d in spec.dids},
        "routines": {hex4(r.id): r.name for r in spec.routines},
        "sessions": {hex2(s.id): s.name for s in spec.sessions},
        "security_levels": {hex2(lvl.level): lvl.name for lvl in spec.security_levels},
        "dtcs": {d.code: d.name for d in spec.dtcs},
    }


class OptionRefs(BaseModel):
    """Spec identifiers touched by one template option."""

    services: list[str] = Field(default_factory=list)
    dids: list[str] = Field(default_factory=list)
    routines: list[str] = Field(default_factory=list)
    sessions: list[str] = Field(default_factory=list)
    security_levels: list[str] = Field(default_factory=list)
    dtcs: list[str] = Field(default_factory=list)

    def all_ids(self) -> list[str]:
        """Every identifier, entity ids (DID/routine/DTC/level) first."""
        out: list[str] = []
        for group in (self.dids, self.routines, self.dtcs, self.security_levels, self.sessions,
                      self.services):
            for ident in group:
                if ident not in out:
                    out.append(ident)
        return out


class TemplateOption(BaseModel):
    """One enumerated parameter combination of a template."""

    index: int
    summary: str
    refs: OptionRefs
    flags: list[str] = Field(default_factory=list)


class TemplateOptions(BaseModel):
    """A template and all of its options for the loaded spec."""

    template_id: str
    description: str
    category: str
    services: list[str]
    options: list[TemplateOption]


def _add(lst: list[str], value: str) -> None:
    if value not in lst:
        lst.append(value)


def describe_option(spec: EcuSpec, template_id: str, index: int, params: BaseModel) -> TemplateOption:
    """Summarize one option and list the spec identifiers it touches."""
    tpl = TEMPLATES[template_id]
    p: dict[str, Any] = params.model_dump()
    refs = OptionRefs(services=[hex2(s) for s in tpl.applicable_services])
    flags: list[str] = []
    bits: list[str] = []
    writes = template_id.startswith("write_") or template_id == "condition_not_met"

    did_id = p.get("did")
    if p.get("kind") == "did":
        did_id = p.get("target")
    if isinstance(did_id, int):
        _add(refs.dids, hex4(did_id))
        did = spec.get_did(did_id)
        if did is None:
            flags.append("unknown_identifier")
            bits.append(f"DID {hex4(did_id)} (not in spec)")
        else:
            bits.append(f"DID {hex4(did_id)} {did.name}")
            if writes:
                for s in did.write_sessions[:1]:
                    _add(refs.sessions, hex2(s))
                if did.write_security_level is not None:
                    _add(refs.security_levels, hex2(did.write_security_level))
    routine_id = p.get("routine")
    if p.get("kind") == "routine":
        routine_id = p.get("target")
    if isinstance(routine_id, int):
        _add(refs.routines, hex4(routine_id))
        routine = spec.get_routine(routine_id)
        if routine is not None:
            bits.append(f"routine {hex4(routine_id)} {routine.name}")
            for s in routine.sessions[:1]:
                _add(refs.sessions, hex2(s))
            if routine.security_level is not None:
                _add(refs.security_levels, hex2(routine.security_level))
    if isinstance(p.get("sid"), int):
        sid = int(p["sid"])
        refs.services = [hex2(sid)]
        bits.append(f"service {hex2(sid)} {service_name(sid)}")
    if isinstance(p.get("level"), int):
        level = int(p["level"])
        _add(refs.security_levels, hex2(level))
        level_def = spec.get_security_level(level)
        bits.append(f"security level {hex2(level)}")
        if level_def is not None:
            for s in level_def.allowed_sessions[:1]:
                _add(refs.sessions, hex2(s))
    if isinstance(p.get("session"), int):
        session = int(p["session"])
        _add(refs.sessions, hex2(session))
        sess = spec.get_session(session)
        bits.append(f"in session {hex2(session)}" + (f" {sess.name}" if sess else ""))
    if isinstance(p.get("code"), str):
        _add(refs.dtcs, str(p["code"]))
        bits.append(f"DTC {p['code']}")

    summary = f"{tpl.description} " + ", ".join(bits) if bits else tpl.description
    return TemplateOption(index=index, summary=summary.strip(), refs=refs, flags=flags)


def build_catalog(spec: EcuSpec) -> list[TemplateOptions]:
    """Enumerate every registered template with its described options."""
    catalog: list[TemplateOptions] = []
    for tid, tpl in TEMPLATES.items():
        options = [
            describe_option(spec, tid, i, params)
            for i, params in enumerate(applicable_params(spec, tid))
        ]
        catalog.append(
            TemplateOptions(
                template_id=tid,
                description=tpl.description,
                category=tpl.category,
                services=[hex2(s) for s in tpl.applicable_services],
                options=options,
            )
        )
    return catalog


def option_refs(spec: EcuSpec, template_id: str, index: int) -> OptionRefs:
    """Spec identifiers touched by one option (used to pick relevant citations)."""
    params = applicable_params(spec, template_id)[index]
    return describe_option(spec, template_id, index, params).refs


# The service a template is "about" (its other services are set-up steps).
_PRIMARY_SERVICE: dict[str, int] = {
    "read_did_positive": 0x22,
    "read_did_wrong_session_or_unknown": 0x22,
    "write_did_secured_positive": 0x2E,
    "write_did_without_security": 0x2E,
    "write_did_out_of_range": 0x2E,
    "write_did_invalid_length": 0x2E,
    "security_invalid_key_lockout": 0x27,
    "s3_timeout_reverts_session": 0x10,
    "routine_sequence": 0x31,
    "dtc_read_clear": 0x19,
}


def primary_service(template_id: str, params: BaseModel) -> str:
    """The service id (``0x2E`` style) a template option mainly exercises."""
    p = params.model_dump()
    if isinstance(p.get("sid"), int):
        return hex2(int(p["sid"]))
    if template_id == "condition_not_met":
        return "0x31" if p.get("kind") == "routine" else "0x2E"
    if template_id in _PRIMARY_SERVICE:
        return hex2(_PRIMARY_SERVICE[template_id])
    return hex2(TEMPLATES[template_id].applicable_services[0])
