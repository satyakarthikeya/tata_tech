# Architecture

## Pipeline and components

```mermaid
flowchart TD
    REQ["Plain-English requirement"] --> PARSE

    subgraph AGENT["agent/ pipeline (LangGraph or plain loop)"]
        PARSE["1 parse<br/>LLM names services, DIDs, routines"] --> RETRIEVE
        RETRIEVE["2 retrieve<br/>evidence from the core layers<br/>(standard, ecu, project)"] --> PLAN
        PLAN["3 plan<br/>LLM picks template ids + option indices"] --> INST
        INST["4 instantiate<br/>templates build the bytes"] --> VAL
        VAL{"5 validate<br/>schema, byte provenance,<br/>oracle agreement, citations"}
        VAL -- "all valid" --> EXPL["6 explain<br/>prose rationale per test"]
        EXPL --> ANN["7 annotate<br/>confidence + reason,<br/>written vs inferred targets"]
        VAL -- "failures and retries left (max 2)" --> PLAN
    end

    LLM[["llm/ mock or Ollama<br/>language only, never bytes"]] -.-> PARSE
    LLM -.-> PLAN
    LLM -.-> EXPL
    RAG[("rag/ core layers<br/>standard, ecu, project")] -.-> RETRIEVE
    SPEC[("data/bcm_spec.yaml<br/>SYNTHETIC BCM spec")] -.-> INST
    TPL[["testgen/ 27 templates"]] -.-> INST
    ORACLE[["rules/ engine = ORACLE<br/>expected response bytes<br/>(one NRC-order function)"]] -.-> INST
    ORACLE -.-> VAL

    ANN --> TESTS["Validated, cited TestCases<br/>with confidence"]
    TESTS --> STORE[("store/ SQLite audit trail")]
    TESTS --> RUNNER["runner/ run_suite, run_bug_matrix"]
    TESTS --> EXPORT["export/ pytest + CAPL (CAPL unverified)"]

    SIM[["simulator/ independent ECU<br/>never imports rules/"]] --> RUNNER
    BUGS[("bug catalogs<br/>26 in-sample + 12 / 15 / 15 held-out v1-v3")] -.-> SIM
    RUNNER --> RESULTS["pass/fail + bug-detection matrix"]
    RESULTS --> EVAL["eval/ run_eval -> outputs/eval_report.md/.json"]
    RESULTS --> STORE

    API["api/ FastAPI"] --> AGENT
    API --> RUNNER
    UI["ui/ Streamlit, 5 tabs"] --> AGENT
    UI --> RUNNER

    subgraph TRI["Triangulation (does the oracle deserve trust?)"]
        direction LR
        T1["simulator vs rules engine<br/>5000 random requests"]
        T2["gold tests<br/>60 hand-written, run on simulator"]
        T3["udsoncan library<br/>virtual-CAN sequence"]
    end
    ORACLE --- T1
    SIM --- T1
    SIM --- T2
    SIM --- T3
    EVAL --- TRI
```

How to read it: solid arrows are data flow; dotted arrows are "uses". The key idea is that the oracle and the simulator are two separate programs written from the same prose contract ([behaviour_contract.md](behaviour_contract.md)), and three independent checks compare them against each other, against hand-written expectations, and against a third-party library.

## Retrieval layers, Q&A and confidence (Part E)

Knowledge is kept in four separate collections, as the case study's risk control asks: **standard** (UDS reference notes, written in our own words), **OEM** (a short synthetic OEM-style guideline, `data/oem_diagnostic_guidelines.md`), **ECU** (chunks of the parsed `bcm_spec.yaml`) and **project** (requirements). Each chunk keeps its layer, and citations carry it (`LayeredCitation`).

```mermaid
flowchart LR
    subgraph LAYERS["rag/ four retrieval layers (separate collections)"]
        direction TB
        L1[("standard<br/>UDS notes")]
        L2[("OEM<br/>synthetic guideline")]
        L3[("ECU<br/>spec chunks")]
        L4[("project<br/>requirements")]
    end

    subgraph GEN["Generation pipeline (agent/)"]
        G1["retrieve + ground + cite"]
    end
    L1 -- "core layers only" --> G1
    L3 -- "core layers only" --> G1
    L4 -- "core layers only" --> G1
    L2 -. "NOT used by generation<br/>(DECISIONS E33-NO-OEM-IN-GEN)" .-> G1

    subgraph QA["Q&A path (qa/, POST /ask, Ask tab)"]
        Q0["question"] --> Q1["1 deterministic spec lookup<br/>DID, routine, NRC, service,<br/>security, timing"]
        Q0 --> Q2["2 layered retrieval<br/>search_layers: top-k per layer"]
        Q1 --> Q3["3 verified phrasing<br/>LLM only rephrases;<br/>values and quotes re-checked"]
        Q2 --> Q3
        Q3 --> Q4["cited answer<br/>or not_found"]
    end
    L1 --> Q2
    L2 --> Q2
    L3 --> Q2
    L4 --> Q2
    SPEC[("parsed ECU spec")] --> Q1

    G1 --> CONF
    Q4 --> CONF["confidence (agent/confidence.py)<br/>high / medium / low + reason"]

    subgraph UI["ui/ Streamlit tabs"]
        T1["Ask"]
        T2["Generate & Review"]
        T3["Run on Simulator"]
        T4["Export"]
        T5["Results"]
    end
    CONF --> T1
    CONF --> T2
    T2 --> T3
    T2 --> T4
    EVAL[("outputs/eval_report.json")] --> T5
```

Notes:

- **The generator uses only the core layers (standard, ECU, project).** The OEM text is policy prose; adding it to generation could change the generated tests for no measured gain, so it is reserved for Q&A (`DECISIONS.md` E33-NO-OEM-IN-GEN). The core BM25 index is unchanged, and mock-mode output for the 15 seeds stayed byte-identical (206 tests) when the layers were split.
- **Q&A uses all four layers**, with top-k per layer, because raw BM25 scores from separate indexes are not comparable (E33-MERGE, E31-LAYERED). Deterministic facts come from the parsed spec; the model never states a fact the lookup did not provide, and an unknown entity or unsupported question returns `not_found` (E31-*).
- **Confidence** is one shared rule for generated tests and Q&A answers: start from a base level, lose one level per fired signal (weak retrieval, inferred target, validator rejections or retries, grounding drops, fallback events), floor at low (E32-RULE). It is shown in the API, the Ask tab and the Generate & Review table.
- **UI tabs** call the pipeline, runner, Q&A and exporters directly; the Results tab only reads `outputs/eval_report.json`. The LLM mode (mock or ollama) and retriever (bm25 or chroma) are chosen in the sidebar.
- **Docker** (`Dockerfile`, `docker-compose.yml`) packages the API and UI with an `ollama` service. It is written, not built here.

## Triangulation in plain words

No single check proves the oracle is right, so there are three:

1. **Simulator vs rules engine.** Random sequences of requests are fed to both; every response must match. Result: 5000/5000. Limit: same author, same contract, so a shared misunderstanding would not show.
2. **Gold tests.** 60 hand-written tests with expected bytes derived from the contract, run on the clean simulator: 60/60. Limit: same author again.
3. **udsoncan cross-check.** The well-known `udsoncan` Python client talks to the simulator over a virtual CAN bus (session, seed/key, read, write, read-back): PASS. Limit: it covers one happy path, not edge cases.

Separately, [SWS_DISAGREEMENTS.md](SWS_DISAGREEMENTS.md) lists nine places (D1 to D9) where the oracle's error-priority order differs from AUTOSAR's Dcm specification. They are documented and not fixed.

## "LLM does language, code does correctness"

The rule (stated in [AGENT.md](../AGENT.md)): **the LLM never produces bytes that reach a final test.** What the LLM does: read the requirement, choose which template options apply, write prose explanations. What code does: every byte, every expected response, every check.

How it is enforced:

| Guard | Where | Effect |
|---|---|---|
| LLM output schemas contain only identifiers, template ids, option indices and prose, no byte fields | [llm/base.py](../uds_assistant/llm/base.py) (`ParsedRequirement`, `PlannedTest`, `TestPlan`) | There is nowhere for bytes to go |
| The plan is re-validated from a plain dict, dropping extra fields a misbehaving backend might attach | [agent/nodes.py](../uds_assistant/agent/nodes.py) (`plan`) | Smuggled fields are discarded |
| The LLM chooses only from a fixed menu of registered templates and enumerated parameter options | [agent/options.py](../uds_assistant/agent/options.py), [testgen/templates.py](../uds_assistant/testgen/templates.py) (`TEMPLATES`, `applicable_params`) | Unknown template ids are rejected |
| Bytes come only from template instantiation; expected responses come from the rules engine | [testgen/templates.py](../uds_assistant/testgen/templates.py), [rules/engine.py](../uds_assistant/rules/engine.py) | Deterministic, auditable |
| "Byte provenance" check: a kept test's steps must equal a fresh template instantiation | [agent/nodes.py](../uds_assistant/agent/nodes.py) (`check_test`) | Any hand-edited bytes fail validation |
| Oracle re-check of every step, plus schema and citation checks | [agent/nodes.py](../uds_assistant/agent/nodes.py) (`check_test`, `validate`), [rag/citations.py](../uds_assistant/rag/citations.py) | Failures are dropped and fed back to the planner (max 2 retries) |
| The simulator must not import the oracle | [tests/simulator/test_independence.py](../tests/simulator/test_independence.py) | Keeps the two implementations independent |

What this does and does not buy: it guarantees the bytes are consistent with the oracle. It does not guarantee the LLM picks the right templates; that is what the requirement-understanding and held-out bug numbers in [RESULTS.md](RESULTS.md) measure, and they are modest: on the fresh held-out v3 bugs the full output (requirement-driven tests plus the conformance sweep) finds 10/15 with mock and 9/15 with ollama, almost all of it from the sweep (requirement-driven tests alone 4/15 and 2/15; Main eval 2026-10-04, git `1f0c293`).
