"""Part D1a: service evidence grounding, session / security-level rules, evidence quotes.

All sentences are made up here (none come from an evaluation set). Fake LLMs only.
"""

from __future__ import annotations

from typing import Any, TypeVar

import pytest
from pydantic import BaseModel

from uds_assistant.agent import nodes
from uds_assistant.agent.grounding import (
    apply_quote_check,
    ground_security_levels,
    ground_services,
    ground_sessions,
    parse_evidence_key,
    quote_in_text,
)
from uds_assistant.agent.options import spec_index
from uds_assistant.agent.service_lexicon import STRONG_RE, first_hit
from uds_assistant.agent.state import PipelineDeps, PipelineState
from uds_assistant.llm.base import ParsedRequirement
from uds_assistant.llm.mock import MockLLM
from uds_assistant.rag.bm25 import Bm25Retriever
from uds_assistant.rag.model import Chunk, Hit
from uds_assistant.spec.schema import EcuSpec

T = TypeVar("T", bound=BaseModel)


class FakeRetriever:
    """Returns fixed ``standard`` hits (refs) so rule (c) can be driven exactly."""

    def __init__(self, refs: list[str]) -> None:
        self.refs = refs
        self.calls = 0

    def search(self, query: str, k: int = 5, collections: list[str] | None = None) -> list[Hit]:
        self.calls += 1
        return [
            Hit(chunk=Chunk(id=f"standard:{r}", collection="standard", source_path="x", ref=r,
                            text="t"), score=1.0)
            for r in self.refs[:k]
        ]


NO_HITS = FakeRetriever([])


def sids(text: str, services: list[str], kept: dict[str, list[str]] | None = None,
         intents: list[str] | None = None, retriever: Any = NO_HITS) -> list[str]:
    out, _, _ = ground_services(services, text, kept or {}, intents or [], retriever)
    return out


# ------------------------------------------------------------------- (a) lexical evidence

@pytest.mark.parametrize(
    "text,sid",
    [
        ("The tester can read the ambient colour value.", "0x22"),
        ("The ECU shall report the speed to the tester.", "0x22"),
        ("Writing the wiper sensitivity is refused in the default session.", "0x2E"),
        ("The brightness can be changed or configured by the tester.", "0x2E"),
        ("The setting shall be stored after a power loss.", "0x2E"),
        ("The ECU shall enter the programming session.", "0x10"),
        ("Switch to extended mode before the request.", "0x10"),
        ("The ECU shall reboot after the request.", "0x11"),
        ("A power cycle returns all values to their defaults.", "0x11"),
        ("The tester clears the stored fault codes.", "0x14"),
        ("Erase the trouble codes from the fault memory.", "0x14"),
        ("The tester reads the active DTCs using a status mask.", "0x19"),
        ("Report the number of DTCs matching the mask.", "0x19"),
        ("The tester must unlock the ECU first.", "0x27"),
        ("A wrong key shall be rejected after the seed was sent.", "0x27"),
        ("Run the lighting self-test and fetch its result.", "0x31"),
        ("The calibration routine can be started and stopped.", "0x31"),
        ("A heartbeat keeps the session alive.", "0x3E"),
        ("Tester present messages restart the S3 timer.", "0x3E"),
    ],
)
def test_service_with_lexical_evidence_is_kept(text: str, sid: str) -> None:
    out, drops, reasons = ground_services([sid], text, {}, [], NO_HITS)
    assert out == [sid] and not drops
    assert reasons[sid].startswith("lexical evidence")


@pytest.mark.parametrize(
    "text,sid",
    [
        ("The door lock indicator shall be orange.", "0x27"),  # 'lock' alone is weak
        ("The tester clears the fault codes.", "0x19"),  # clearing is not reading
        ("Read the stored fault codes.", "0x22"),  # reading faults is 0x19, not 0x22
        ("Reading the VIN is allowed.", "0x2E"),
        ("The system shall respond quickly.", "0x31"),
        ("Return to the default session after one second.", "0x22"),
        ("The factory reset flag is a stored setting.", "0x11"),
    ],
)
def test_lexicon_does_not_over_match(text: str, sid: str) -> None:
    assert first_hit(STRONG_RE[sid], text) is None


def test_service_without_any_evidence_is_dropped_with_reason() -> None:
    text = "The module shall behave sensibly under all conditions."
    out, drops, _ = ground_services(["0x2E", "0x31"], text, {}, [], NO_HITS)
    assert out == []
    assert {d.identifier for d in drops} == {"0x2E", "0x31"}
    assert all(d.field == "services" and d.reason.startswith("no evidence") for d in drops)


def test_only_unsupported_services_are_dropped() -> None:
    assert sids("Read the ambient value; nothing else.", ["0x22", "0x2E", "0x3E"]) == ["0x22"]


# ------------------------------------------------------------ (b) implied by kept identifier

def test_kept_did_with_read_intent_implies_0x22() -> None:
    text = "Ensure the VIN is exactly seventeen characters long."
    assert sids(text, ["0x22"], {"dids": ["0xF190"]}) == ["0x22"]
    assert sids(text, ["0x22"], {}) == []  # no kept DID: nothing implied


def test_kept_did_with_write_intent_implies_0x2E_via_intent_field() -> None:
    text = "The brightness only accepts values up to one hundred."
    assert sids(text, ["0x2E"], {"dids": ["0x0100"]}, intents=["range"]) == ["0x2E"]
    assert sids(text, ["0x2E"], {"dids": ["0x0100"]}, intents=["positive"]) == []


def test_kept_routine_implies_0x31() -> None:
    assert sids("The actuator test needs the door closed.", ["0x31"],
                {"routines": ["0x0201"]}) == ["0x31"]
    assert sids("The actuator test needs the door closed.", ["0x31"], {}) == []


def test_kept_dtc_implies_clear_or_read() -> None:
    kept = {"dtcs": ["B10101"]}
    assert sids("Make sure B10101 is gone afterwards.", ["0x14"], kept) == []  # no clear word
    assert sids("Afterwards, verify that B10101 is listed.", ["0x19"], kept) == ["0x19"]
    assert sids("B10101 shall be gone, flushed by the tester.", ["0x19"], kept,
                intents=["dtc"]) == ["0x19"]


def test_state_services_need_the_text_not_the_session_or_level_alone() -> None:
    """0x10 / 0x27 are never implied just because a session / level was parsed."""
    text = "The ambient colour is set to a new value."
    kept = {"dids": ["0x0101"], "sessions": ["0x03"], "security_levels": ["0x01"]}
    assert sids(text, ["0x10", "0x27", "0x2E"], kept) == ["0x2E"]


# ------------------------------------------------------------------- (c) retrieval support

def test_retrieval_alone_is_never_evidence() -> None:
    text = "The module shall behave sensibly under all conditions."
    retr = FakeRetriever(["svc-0x2e", "svc-0x22"])
    assert sids(text, ["0x2E", "0x22"], retriever=retr) == []


def test_retrieval_plus_weak_word_is_evidence() -> None:
    text = "The module shall accept a new value."  # 'value' weak for 0x2E and 0x22
    retr = FakeRetriever(["svc-0x2e"])
    out, _, reasons = ground_services(["0x2E"], text, {}, [], retr)
    assert out == ["0x2E"] and reasons["0x2E"].startswith("retrieval support")


def test_weak_word_without_retrieval_is_dropped() -> None:
    text = "The module shall accept a new value."
    assert sids(text, ["0x2E"], retriever=FakeRetriever(["svc-0x11"])) == []
    assert sids(text, ["0x2E"], retriever=NO_HITS) == []


def test_retrieval_only_runs_when_a_service_lacks_lexical_evidence() -> None:
    retr = FakeRetriever(["svc-0x22"])
    sids("Read the VIN.", ["0x22"], retriever=retr)
    assert retr.calls == 0
    sids("Nothing special here.", ["0x22"], retriever=retr)
    assert retr.calls == 1


def test_retrieval_with_the_real_bm25_standard_collection(retriever: Bm25Retriever) -> None:
    out, drops, _ = ground_services(["0x3E", "0x2E"], "Nothing in this sentence.", {}, [],
                                    retriever)
    assert out == [] and len(drops) == 2


# ---------------------------------------------------------------- sessions / security levels

def test_sessions_must_be_named_or_implied(spec: EcuSpec) -> None:
    index = spec_index(spec)
    got, drops = ground_sessions(["0x01", "0x02", "0x03"], "Only valid in the extended session.", index)
    assert got == ["0x03"] and {d.identifier for d in drops} == {"0x01", "0x02"}
    got, _ = ground_sessions(["0x01", "0x02", "0x03"], "It works in any session.", index)
    assert got == ["0x01", "0x02", "0x03"]
    got, _ = ground_sessions(["0x02"], "Allowed while flashing the ECU.", index)
    assert got == ["0x02"]
    got, _ = ground_sessions(["0x03"], "Allowed only in session 0x03.", index)
    assert got == ["0x03"]
    got, drops = ground_sessions(["0x03"], "The wrong session is refused.", index)
    assert got == [] and drops[0].field == "sessions"


def test_security_levels_need_an_unlock_word() -> None:
    got, drops = ground_security_levels(["0x01"], "Level one applies to this write.")
    assert got == [] and drops[0].field == "security_levels"
    got, drops = ground_security_levels(["0x01"], "After unlocking at level one it works.")
    assert got == ["0x01"] and not drops
    got, _ = ground_security_levels(["0x03"], "The seed is requested for the flash level.")
    assert got == ["0x03"]
    assert ground_security_levels([], "anything") == ([], [])


# ---------------------------------------------------------------------------- quotes

def test_quote_check_is_case_and_whitespace_insensitive() -> None:
    assert quote_in_text("READ  the\nvin", "The tester shall read the VIN today.")
    assert not quote_in_text("write the vin", "The tester shall read the VIN today.")
    assert not quote_in_text("   ", "anything")


def test_parse_evidence_key() -> None:
    assert parse_evidence_key("service:0x2e") == ("services", "0x2E")
    assert parse_evidence_key("did:f190") == ("dids", "0xF190")
    assert parse_evidence_key("dtc:b10101") == ("dtcs", "B10101")
    assert parse_evidence_key("level:1") == ("security_levels", "0x1")
    assert parse_evidence_key("nonsense:1") is None
    assert parse_evidence_key("service:") is None


def test_apply_quote_check_drops_only_items_with_a_bad_quote() -> None:
    text = "The tester shall read the VIN."
    kept = {"services": ["0x22", "0x2E"], "dids": ["0xF190"]}
    out, drops, valid = apply_quote_check(
        kept, {"service:0x22": "shall read", "service:0x2E": "overwrite it", "did:0xF190": ""}, text
    )
    assert out["services"] == ["0x22"] and out["dids"] == ["0xF190"]
    assert [(d.field, d.identifier) for d in drops] == [("services", "0x2E")]
    assert valid == {"service:0x22": "shall read"}


# ------------------------------------------------------------------------ parse node

class ParseOnly:
    """Fake non-mock backend returning a fixed parse (grounding applies: no opt-out flag)."""

    name = "fake"

    def __init__(self, parsed: ParsedRequirement) -> None:
        self.parsed = parsed

    def complete_json(self, system: str, prompt: str, schema: type[T]) -> T:
        return self.parsed  # type: ignore[return-value]

    def complete_text(self, system: str, prompt: str) -> str:
        return ""


def run_parse(spec: EcuSpec, retriever: Any, parsed: ParsedRequirement, text: str,
              llm: Any = None) -> PipelineState:
    state = PipelineState(requirement_id="REQ-T", requirement_text=text)
    deps = PipelineDeps(spec=spec, llm=llm or ParseOnly(parsed), retriever=retriever)
    return nodes.parse(state, deps)


def test_parse_node_drops_unsupported_services_and_records_every_drop(
    spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    parsed = ParsedRequirement(
        services=["0x22", "0x2E", "0x27", "0x10"], dids=["0xF190"], sessions=["0x03"],
        security_levels=["0x01"], intents=["read"],
    )
    s = run_parse(spec, retriever, parsed, "The tester shall read the VIN (DID 0xF190).")
    assert s.parsed is not None
    assert s.parsed.services == ["0x22"]
    assert s.parsed.dids == ["0xF190"]
    assert s.parsed.sessions == [] and s.parsed.security_levels == []
    dropped = {n.split(" identifier ")[1].split(":")[0] for n in s.notes
               if n.startswith("Dropped ungrounded")}
    assert {"0x2E", "0x27", "0x10", "0x03", "0x01"} <= dropped
    decisions = [d.message for d in s.decisions if d.node == "parse"]
    assert all(any(f"identifier {i}:" in m for m in decisions) for i in dropped)
    assert any("service 0x22 kept: lexical evidence" in m for m in decisions)


def test_parse_node_notes_when_no_service_survives(
    spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    parsed = ParsedRequirement(services=["0x2E"], intents=["positive"])
    s = run_parse(spec, retriever, parsed, "The module shall behave sensibly.")
    assert s.parsed is not None and s.parsed.services == []
    assert any("No parsed service had evidence" in n for n in s.notes)


def test_parse_node_bad_quote_drops_the_item_and_good_quote_is_kept(
    spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    text = "The tester shall read the VIN (DID 0xF190) and write the colour index."
    parsed = ParsedRequirement(
        services=["0x22", "0x2E"], dids=["0xF190"],
        evidence={"service:0x22": "shall READ the VIN", "service:0x2E": "overwrite everything",
                  "did:0xF190": "DID 0xF190"},
    )
    s = run_parse(spec, retriever, parsed, text)
    assert s.parsed is not None
    assert s.parsed.services == ["0x22"]  # 0x2E had lexical evidence but its quote is not in the text
    assert any("0x2E" in n and "evidence quote" in n for n in s.notes)
    assert s.parsed.evidence == {"service:0x22": "shall READ the VIN", "did:0xF190": "DID 0xF190"}


def test_parse_node_item_without_quote_falls_back_to_the_rules(
    spec: EcuSpec, retriever: Bm25Retriever
) -> None:
    text = "The tester shall write the colour index."
    parsed = ParsedRequirement(services=["0x2E", "0x22"], evidence={"service:0x22": "read it"})
    s = run_parse(spec, retriever, parsed, text)
    assert s.parsed is not None and s.parsed.services == ["0x2E"]


def test_evidence_field_is_optional_and_tolerates_garbage() -> None:
    assert ParsedRequirement().evidence == {}
    assert ParsedRequirement.model_validate({"evidence": "oops"}).evidence == {}
    p = ParsedRequirement.model_validate({"evidence": {"a": "b", "c": 3}})
    assert p.evidence == {"a": "b"}


def test_evidence_schema_has_no_byte_fields() -> None:
    props = ParsedRequirement.model_json_schema()["properties"]["evidence"]
    assert props["type"] == "object" and props["additionalProperties"] == {"type": "string"}


def test_mock_backend_skips_all_new_grounding(spec: EcuSpec, retriever: Bm25Retriever) -> None:
    llm = MockLLM()
    assert llm.applies_grounding is False
    text = "The tester shall read the VIN (DID 0xF190) in any session."
    s = run_parse(spec, retriever, ParsedRequirement(), text, llm=llm)
    assert not any(n.startswith("Dropped ungrounded") for n in s.notes)
    assert s.parsed is not None and s.parsed.evidence == {}
