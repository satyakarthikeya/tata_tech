"""Coverage of the hand-written gold tests versus the conformance sweep (spec items touched).

Used for the "coverage improvement" success metric of Case Study 5: the gold set is the
hand-authored baseline, the sweep is generated. Run from the repo root: ``python scripts/coverage_baseline.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from uds_assistant.eval.coverage import coverage_report
from uds_assistant.spec.schema import load_spec
from uds_assistant.testgen.conformance import build_conformance_suite
from uds_assistant.testgen.model import load_tests


def main() -> None:
    spec = load_spec(ROOT / "data" / "bcm_spec.yaml")
    gold = load_tests(ROOT / "data" / "gold" / "gold_tests.yaml", spec)
    sweep = build_conformance_suite(spec).tests
    for name, tests in (("gold (hand-written baseline)", gold), ("conformance sweep (generated)", sweep)):
        rep = coverage_report(tests, spec)
        total = sum(len(v) for v in rep["items"].values())
        missing = sum(len(v) for v in rep["uncovered"].values())
        kinds = {k: f"{sum(1 for r in v if r['tests'])}/{len(v)}" for k, v in rep["items"].items()}
        print(f"{name}: {len(tests)} tests, spec items touched {total - missing}/{total}")
        print(f"  by category: {rep['by_category']}")
        print(f"  by kind: {kinds}")
        for kind, items in rep["uncovered"].items():
            if items:
                print(f"  zero tests ({kind}): {', '.join(items)}")


if __name__ == "__main__":
    main()
