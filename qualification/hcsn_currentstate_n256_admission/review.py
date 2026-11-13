"""Independent, zero-numerical review of the N256 lineage admission originals."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

IDENTITY = "hcsn-n256-input-lineage-admission-20261113-c06d-001"
EXPECTED_INPUT = {
    "metadata": "88e84dd3aea396d34c7e2dd08d31f2e30bf694c20516dccde57e6dd1b0c2a3c6",
    "state": "360b4bf446e853209c58cdb3faded74d9114d872cfb9c730b220d14cef670f9c",
    "phase": "790fabee8825dbd4361f157f56d78641430fe50b9134cd2cb7b02b51b93fe548",
    "npz_b64": "926191319021c51421dd15d76c66c3b5c6d2efef0f28af3f76c893065a49dbeb",
    "npz": "c98a3339504c908081dbf77d2235a18de96da06b1ebda7b1c0f9192af1570eb8",
}
EXPECTED_BUNDLE = "17086fb6ba83211e8626c7ac9c22183f6c9c9a7dc615772b5a32d2c14ecb8e95"
EXPECTED_ROSTER = "e289c20d6595cb6d92dd3e2585bc7cb40fb0d5a408725c5edc14a9fb7f328fe2"
ZERO_FIELDS = (
    "dynamic_runs",
    "matrix_exponentials",
    "oracle_numeric_calls",
    "serializer_numeric_calls",
    "torch_calls",
    "backward_calls",
    "optimizer_steps",
    "training_runs",
)


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    report = load(args.evidence / "REPORT.json")
    costs = load(args.evidence / "COSTS.json")
    receipt = load(args.evidence / "RECEIPT.json")

    require(report["identity"] == costs["identity"] == receipt["identity"] == IDENTITY, "identity")
    require(receipt["report_sha256"] == digest(args.evidence / "REPORT.json"), "report hash")
    require(receipt["costs_sha256"] == digest(args.evidence / "COSTS.json"), "cost hash")
    require(report["status"] == "PASS_AUTHENTIC_NEW_EXPORT_LINEAGE_HOLD_DYNAMIC", "status")
    require(report["closed_gate"] == "authentic_new_export_input_lineage", "closed gate")
    require(report["input_sha256"] == EXPECTED_INPUT, "input hashes")
    require(report["input_bundle_sha256"] == EXPECTED_BUNDLE, "bundle")
    require(report["roster_identity"] == EXPECTED_ROSTER, "roster")
    require(report["decoded_coordinates_checked"] == 1542, "decoded denominator")
    require(report["fp64_coordinate_denominator"] == 18_225_028, "roster denominator")
    require(report["preserved_results"]["engineering"] == "RED_RESOURCE_CAP_HOLD", "RED preserved")
    require(report["historical_N256_export_recovered"] is False, "history")
    require(report["historical_N256_missing_statement_preserved"] is True, "history preservation")
    require(report["new_export_only"] is True, "new-export-only")
    require(all(report["execution_counts"][field] == 0 for field in ZERO_FIELDS), "report zero execution")
    require(all(costs[field] == 0 for field in ZERO_FIELDS), "cost zero execution")
    require(report["largegrid_qualification"] is False and report["global_HOLD"] is True, "HOLD")
    require(report["all_closed"] is False and len(report["remaining_gates"]) == 7, "remaining gates")

    for name, relative in report["original_sha256"].items():
        require(digest(args.root / relative) == report["original_sha256"][name], f"original changed: {name}")

    review = {
        "schema": "hcsn-n256-input-lineage-admission-independent-review-v1",
        "identity": IDENTITY,
        "status": "PASS_ZERO_NUMERICAL_REVIEW_HOLD_DYNAMIC",
        "files_checked": len(report["original_sha256"]) + 3,
        "decoded_coordinates_checked": 1542,
        "fp64_coordinate_denominator": 18_225_028,
        "verified_zero_fields": list(ZERO_FIELDS),
        "historical_N256_export_recovered": False,
        "new_export_only": True,
        "largegrid_qualification": False,
        "global_HOLD": True,
        "all_closed": False,
    }
    target = args.evidence / "REVIEW.json"
    target.write_text(json.dumps(review, indent=2, sort_keys=True) + "\n")
    print(json.dumps(review, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
