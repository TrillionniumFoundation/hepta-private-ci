"""Independently audit typed maintenance without training or changing evidence."""

import argparse
import json
from pathlib import Path

import bootstrap  # noqa: F401
from v4.typed_lifecycle_audit import audit_typed_lifecycle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-development", action="store_true")
    parser.add_argument("--allow-unsealed-development", action="store_true")
    args = parser.parse_args()
    report = audit_typed_lifecycle(
        args.run,
        args.output,
        allow_development=args.allow_development,
        allow_unsealed_development=args.allow_unsealed_development,
    )
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "verified",
                    "development_only",
                    "outer_evidence_seal_verified",
                    "formal_qualification_eligible",
                    "all_maintenance_gates_pass",
                    "actual_candidate_count",
                    "svd_calls",
                    "least_squares_solves",
                    "saved_phase_fact_outputs_checked",
                    "actual_process_receipts",
                )
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
