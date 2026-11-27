"""Print prospective arithmetic allocations; never starts a method build."""

import argparse
import json
from pathlib import Path

from content_budget.boundary import Plan, tail_unit_admission_quote


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    evidence = json.loads(args.evidence.read_text())["future_budget_candidates"]
    result = dict(scope="prospective boundary/allocation calculation only; no training permission or execution",
        old_failed_result_unchanged=True, model_work=0,
        measured_worst_core_tail_CPU=evidence["observed_worst_core_tail_CPU"],
        old_all_inclusive_tail_CPU=evidence["observed_old_whole_tail_CPU"],
        plans={str(cap): Plan(cap, 12_000_000_000, evidence["shared_CPU_reference"],
            evidence["shared_units_reference"]).snapshot() for cap in (10., 11.)},
        tail_unit_quote=tail_unit_admission_quote(),
        caveat="2.5-second tail and0.5-second global guard are prospective empirical safeguards, not universal CPU bounds; any observed violation fails and is retained")
    assert result["tail_unit_quote"]["total"] <= 500_000_000
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
