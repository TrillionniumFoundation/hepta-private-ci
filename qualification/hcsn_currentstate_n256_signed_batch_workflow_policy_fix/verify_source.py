"""Verify the frozen metadata-only branch-policy repair."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "qualification/hcsn_currentstate_n256_signed_batch_workflow_policy_fix"
ORIGINAL_FREEZE_SHA256 = "5f60c371cff340cc3834fd2c236d9be23c0c4a62bb272df74c66ee99b7451ebb"
BATCH_SOURCE_SHA256 = "12285fd01ff8df80d154d65677fe779147e1e95fddaedec6303d53b8755d107f"


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    freeze = json.loads((PACKAGE / "SOURCE_FREEZE.json").read_text())
    for relative, expected in freeze["files"].items():
        if _digest(ROOT / relative) != expected:
            raise SystemExit(f"exact source mismatch: {relative}")

    original = PACKAGE / "ORIGINAL_6918_SOURCE_FREEZE.json"
    if _digest(original) != ORIGINAL_FREEZE_SHA256:
        raise SystemExit("original #6918 source freeze bytes changed")
    batch_source = ROOT / (
        "qualification/hcsn_currentstate_n256_signed_batch_candidate/"
        "batch_candidate.py"
    )
    if _digest(batch_source) != BATCH_SOURCE_SHA256:
        raise SystemExit("#6918 Python batch source changed")

    request = json.loads((PACKAGE / "REQUEST.json").read_text())
    if (
        request["numerical_execution_allowed"] is not False
        or request["authentic_provider_execution_allowed"] is not False
        or request["execution_key"] is not None
        or request["provider_calls"] != 0
        or request["optimizer_calls"] != 0
        or request["resource_gate_closed"] is not False
        or request["n256_qualified"] is not False
        or request["all_closed"] is not False
        or request["cause_of_6901_red"] != "UNKNOWN"
        or request["c2_full_replay_completed_fits"] != 0
        or request["hpca_status"] != "NoUpdate"
    ):
        raise SystemExit("request is not fail closed")

    review = json.loads((PACKAGE / "REVIEW.json").read_text())
    scope = review["scope"]
    if (
        scope["authentic_provider_calls"] != 0
        or scope["dynamic_kernel_calls"] != 0
        or scope["exponential_actions"] != 0
        or scope["torch_calls"] != 0
        or scope["optimizer_calls"] != 0
        or scope["resource_gate_closed"] is not False
        or scope["n256_qualified"] is not False
        or scope["all_closed"] is not False
        or review["preservation"]["scientific_evidence_transferred"] is not False
        or review["historical_statuses"]["6901_numerical_cause"] != "UNKNOWN"
    ):
        raise SystemExit("review is not fail closed")

    print("PASS_N256_SIGNED_BATCH_WORKFLOW_POLICY_FIX")


if __name__ == "__main__":
    main()
