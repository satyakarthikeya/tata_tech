"""Human-readable decoding of UDS request/response hex for the UI and exports.

Uses only :mod:`uds_assistant.protocol.constants` (service names, NRC names, the positive-response
offset). It deliberately does not import the rules engine: a decoded line says what the bytes
*are*, never what they *should* be.
"""

from __future__ import annotations

from dataclasses import dataclass

from uds_assistant.protocol.constants import (
    NEGATIVE_RESPONSE_SID,
    POSITIVE_RESPONSE_OFFSET,
    SERVICES_WITH_SUBFUNCTION,
    Nrc,
    ServiceId,
)

ARROW = "→"
DID_SERVICES = frozenset({ServiceId.READ_DATA_BY_IDENTIFIER, ServiceId.WRITE_DATA_BY_IDENTIFIER})


def camel(name: str) -> str:
    """``SECURITY_ACCESS_DENIED`` -> ``securityAccessDenied``."""
    head, *rest = name.lower().split("_")
    return head + "".join(p.capitalize() for p in rest)


def service_name(sid: int) -> str:
    """``WriteDataByIdentifier`` for 0x2E, ``service 0xNN`` for an unknown SID."""
    try:
        return "".join(p.capitalize() for p in ServiceId(sid).name.lower().split("_"))
    except ValueError:
        return f"service 0x{sid:02X}"


def nrc_name(code: int) -> str:
    """``securityAccessDenied`` for 0x33, ``unknownNrc`` style fallback for the rest."""
    try:
        return camel(Nrc(code).name)
    except ValueError:
        return f"unknown NRC 0x{code:02X}"


def spaced_hex(raw: bytes | str) -> str:
    """``2e200101`` -> ``2E 20 01 01``."""
    data = bytes.fromhex(raw) if isinstance(raw, str) else raw
    return " ".join(f"{b:02X}" for b in data)


def _safe_bytes(hex_str: str) -> bytes | None:
    try:
        return bytes.fromhex(hex_str.replace(" ", ""))
    except ValueError:
        return None


def describe_request(
    request_hex: str, did_names: dict[int, str] | None = None
) -> str:
    """One phrase for a request, e.g. ``WriteDataByIdentifier DID 0x2001 (name)``."""
    raw = _safe_bytes(request_hex)
    if not raw:
        return "empty or malformed request"
    name = service_name(raw[0])
    try:
        sid = ServiceId(raw[0])
    except ValueError:
        return name
    if sid in DID_SERVICES and len(raw) >= 3:
        did = (raw[1] << 8) | raw[2]
        label = (did_names or {}).get(did)
        return f"{name} DID 0x{did:04X}" + (f" ({label})" if label else "")
    if sid in SERVICES_WITH_SUBFUNCTION and len(raw) >= 2:
        sub = raw[1] & 0x7F
        suppress = " (suppress positive response)" if raw[1] & 0x80 else ""
        return f"{name} subfunction 0x{sub:02X}{suppress}"
    return name


def describe_response(response_hex: str) -> str:
    """``(securityAccessDenied)``-style tag for a negative response, ``positive`` text otherwise."""
    raw = _safe_bytes(response_hex)
    if not raw:
        return "no response"
    if raw[0] == NEGATIVE_RESPONSE_SID:
        if len(raw) < 3:
            return "malformed negative response"
        return f"negative response to {service_name(raw[1])}: {nrc_name(raw[2])}"
    request_sid = raw[0] - POSITIVE_RESPONSE_OFFSET
    if request_sid in {int(s) for s in ServiceId}:
        return f"positive response to {service_name(request_sid)}"
    return f"unrecognised response SID 0x{raw[0]:02X}"


def response_tag(response_hex: str) -> str:
    """Short tag in the step line: the NRC name, or ``positive``."""
    raw = _safe_bytes(response_hex)
    if not raw:
        return "no response"
    if raw[0] == NEGATIVE_RESPONSE_SID and len(raw) >= 3:
        return nrc_name(raw[2])
    if raw[0] == NEGATIVE_RESPONSE_SID:
        return "malformed negative response"
    return "positive"


@dataclass(frozen=True)
class DecodedStep:
    """A send step in three forms: the arrow line, the request text and the response text."""

    line: str
    request_text: str
    response_texts: list[str]


def decode_responses(responses_hex: list[str]) -> str:
    """``7F 2E 33 (securityAccessDenied)``; several frames joined by `` | ``."""
    if not responses_hex:
        return "(no response)"
    parts = []
    for r in responses_hex:
        raw = _safe_bytes(r)
        shown = spaced_hex(raw) if raw is not None else r
        parts.append(f"{shown} ({response_tag(r)})" if raw else "(no response)")
    return " | ".join(parts)


def decode_step(
    request_hex: str, expected_hex: list[str], did_names: dict[int, str] | None = None
) -> DecodedStep:
    """Decode a send step: ``2E 20 01 01 → 7F 2E 33 (securityAccessDenied)``."""
    raw = _safe_bytes(request_hex)
    req = spaced_hex(raw) if raw is not None else request_hex
    return DecodedStep(
        line=f"{req} {ARROW} {decode_responses(expected_hex)}",
        request_text=describe_request(request_hex, did_names),
        response_texts=[describe_response(r) for r in expected_hex],
    )
