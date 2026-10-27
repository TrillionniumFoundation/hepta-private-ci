"""Promotion requires the extra semantic-tail gate as well as legacy metrics."""

import argparse
import json
from pathlib import Path

from ...continuation_20261027.control.client import Native
from ...continuation_20261027.control.training import prefix
from .check_binding import tree_identity
from .protocol import preserve_sources, sha, write


def evaluate(qualification, audit):
    result = json.loads((qualification / "RESULT.json").read_text())
    independent = json.loads((audit / "RESULT.json").read_text())
    seal = json.loads((qualification / "QUALIFICATION_SEAL.json").read_text())
    bound = (sha(qualification / "ROWS.json") == result["rows_sha256"] == independent["run_rows_sha256"]
        and sha(qualification / "QUALIFICATION_SEAL.json") == result["seal_sha256"] == independent["run_seal_sha256"]
        and sha(qualification / "CALIBRATOR.json") == seal["calibrator_sha256"])
    gates = {"sealed_same_generator_and_policy_evidence": bound,
        "independent_native_media_and_metric_audit": independent["passed"],
        "legacy_full_cohort_ECE_and_declared_OOD": all(result["legacy_shaped_gates"].values()),
        "selective_nonvacuity": result["additional_selective_gates"]["id_coverage"],
        "additional_semantic_tail": result["additional_selective_gates"]["incorrect_commit_rate"]}
    return {"candidate_promotion_allowed": all(gates.values()), "gates": gates,
        "failed_gates": [key for key, value in gates.items() if not value],
        "rows_sha256": result["rows_sha256"], "qualification_seal_sha256": result["seal_sha256"],
        "independent_audit_sha256": sha(audit / "RESULT.json"),
        "semantic_error_count": result["incorrect_semantic_commits_id"],
        "semantic_error_per_ID_case": result["incorrect_semantic_commit_per_id_case"],
        "semantic_error_limit_unchanged": .004999,
        "native_authority": "DENY_ALL", "production_authorization": False,
        "original_native_profile_modified": False}


def require_qualified_candidate(qualification, audit):
    decision = evaluate(qualification, audit)
    if not decision["candidate_promotion_allowed"]:
        raise ValueError("Candidate promotion refused: " + ", ".join(decision["failed_gates"]))
    return decision


def run(qualification, audit, development, binary, output):
    output.mkdir(parents=True, exist_ok=False)
    preserve_sources(output / "executed-source")
    decision = evaluate(qualification, audit)
    if decision["candidate_promotion_allowed"] or decision["failed_gates"] != ["additional_semantic_tail"]:
        raise ValueError("The retained tail failure was not enforced as the promotion blocker")
    native = Native(binary)
    native.open(output / "owner", "semantic-tail-promotion-denial", 7,
        development / "MODEL.json", development / "ENCODER_DOMAIN_PROOF.json")
    prefix(native, 0)
    before, before_files = native.call({"command": "Status"}), tree_identity(output / "owner")
    try:
        require_qualified_candidate(qualification, audit)
    except ValueError as error:
        rejection = str(error)
    else:
        raise ValueError("Failed semantic-tail candidate was allowed to promote")
    if native.call({"command": "Status"}) != before or tree_identity(output / "owner") != before_files:
        raise ValueError("Promotion denial changed original-owner durable state")
    native.close()
    write(output / "TRANSCRIPT.json", native.transcript)
    native.finish()
    write(output / "PROMOTION_DECISION.json", decision)
    write(output / "RESULT.json", {"passed": True, "promotion_allowed": False,
        "rejection": rejection, "live_owner_and_durable_bytes_unchanged": True,
        "decision_sha256": sha(output / "PROMOTION_DECISION.json"), "actual_native_kernel_ticks": 4,
        "new_generator_outputs_computed": False})
    print(json.dumps(decision), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("qualification", "audit", "development", "binary", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.qualification, args.audit, args.development, args.binary, args.output)
