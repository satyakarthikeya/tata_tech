"""The six headline cards of the Results tab, built from ``outputs/eval_report.json``.

Pure functions (no streamlit): every lookup is defensive, a missing key gives ``n/a`` and a note,
never an exception. Each card carries the run date and git short hash of the run it comes from.
"""

from __future__ import annotations

from dataclasses import dataclass, field

NA = "n/a"


@dataclass
class Card:
    """One headline card: title, value lines, a caption and its run date / git hash."""

    title: str
    lines: list[tuple[str, str]] = field(default_factory=list)
    caption: str = ""
    run_date: str = NA
    git_short: str = NA
    available: bool = True


def _find(items: object, item_id: str) -> dict | None:
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict) and it.get("id") == item_id:
                return it
    return None


def _display(card: dict | None) -> dict[str, str]:
    d = (card or {}).get("display")
    return {str(k): str(v) for k, v in d.items()} if isinstance(d, dict) else {}


def _run(card: dict | None) -> tuple[str, str]:
    if not card:
        return NA, NA
    ref = card.get("run_ref") if isinstance(card.get("run_ref"), dict) else {}
    date = card.get("run_date") or ref.get("date") or NA
    git = card.get("git_short") or ref.get("git_short") or NA
    return str(date), str(git)


def _mode_lines(disp: dict[str, str]) -> list[tuple[str, str]]:
    return [(m, disp[m]) for m in ("mock", "ollama", "all") if m in disp]


def _card(title: str, main: dict | None, extra: list[dict | None], caption: str) -> Card:
    if not main:
        return Card(title, [], f"Not in this report. {caption}", available=False)
    lines = _mode_lines(_display(main))
    for e in extra:
        if e:
            lines += [(f"{e.get('label', '?')} / {m}", v) for m, v in _display(e).items()]
    date, git = _run(main)
    return Card(title, lines, caption, date, git)


def _coverage_card(report: dict) -> Card:
    title = "5. Coverage"
    cov = _find(report.get("success_metrics"), "coverage")
    values = (cov or {}).get("values")
    if not isinstance(values, dict):
        return Card(title, [], "Not in this report.", available=False)
    lines: list[tuple[str, str]] = []
    for m in ("mock", "ollama"):
        v = values.get(m)
        if isinstance(v, dict) and "requirements_with_tests" in v:
            lines.append(
                (m, f"{v['requirements_with_tests']}/{v.get('requirements', '?')} requirements with a test")
            )
    phases = values.get("sweep_phases")
    if isinstance(phases, list) and phases:
        done = sum(int(p.get("covered", 0)) for p in phases if isinstance(p, dict))
        total = sum(int(p.get("items", 0)) for p in phases if isinstance(p, dict))
        lines.append(("conformance sweep", f"{done}/{total} oracle-observable items"))
    date, git = _run(cov)
    return Card(
        title, lines, "Requirements with >= 1 test, plus sweep items covered (not code coverage).", date, git
    )


def _latency_card(report: dict) -> Card:
    card = _card(
        "6. Latency (generation per requirement)",
        _find(report.get("headline_cards"), "timing_mean_s"),
        [],
        "Tool-side wall-clock, mean of 5 requirements; mock is a keyword stand-in, ollama is a local 3B model.",
    )
    return card


def build_cards(report: dict) -> list[Card]:
    """The six headline cards in display order."""
    hc = report.get("headline_cards")
    agree = _find(hc, "simulator_rules_agreement")
    gold = _find(hc, "gold_clean_pass")
    if agree:
        date, git = _run(agree)
        correctness = Card(
            "1. Correctness",
            [("simulator vs rules engine", _display(agree).get("all", NA))],
            "Independent simulator agrees with the rules-engine oracle on random walks; "
            "gold tests pass on the clean simulator.",
            date,
            git,
        )
        if gold:
            correctness.lines.append(("gold tests, clean simulator", _display(gold).get("all", NA)))
    else:
        correctness = Card("1. Correctness", [], "Not in this report.", available=False)
    bugs = _card(
        "2. Bug detection (fresh v3 set, 15 bugs)",
        _find(hc, "v3_bugs_full_output"),
        [],
        "Full output = requirement-driven tests plus conformance sweep. Bugs never seen when tests were written.",
    )
    rd = _find(hc, "v3_bugs_requirement_driven")
    if rd and bugs.available:
        bugs.lines += [(f"requirement-driven only / {m}", v) for m, v in _display(rd).items()]
    und = _card(
        "3. Understanding: mock vs Ollama (natural v3)",
        _find(hc, "natural_v3_target_f1_parsed"),
        [],
        "Parsed-target F1 on 16 fresh natural-language requirements (higher is better).",
    )
    qa = _card(
        "4. Q&A accuracy",
        _find(hc, "qa_answer_accuracy"),
        [_find(hc, "qa_correct_not_found_rate")],
        "Answer accuracy on 25 questions; the second line is the correct not-found rate.",
    )
    return [correctness, bugs, und, qa, _coverage_card(report), _latency_card(report)]
