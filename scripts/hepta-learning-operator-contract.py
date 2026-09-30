#!/usr/bin/env python3
"""Verify the authoritative learning.operator source/document contract."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = "docs/modules/learning.operator/IMPLEMENTATION_MAP.json"


def read(path: str) -> str:
    target = ROOT / path
    if not target.is_file():
        raise SystemExit(f"learning.operator contract verification failed: absent {path}")
    return target.read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"learning.operator contract verification failed: {message}")


def require_tokens(path: str, tokens: list[str]) -> None:
    text = read(path)
    for token in tokens:
        require(token in text, f"{path} missing {token!r}")


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "--no-replace-objects", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def exact_sha(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None


def source_candidate_sha() -> str:
    requested = os.environ.get("SOURCE_SHA", "")
    if exact_sha(requested):
        return requested
    parents = git("show", "-s", "--format=%P", "HEAD").split()
    if len(parents) >= 2 and exact_sha(parents[1]):
        return parents[1]
    return git("rev-parse", "HEAD")


def verify_observation_freshness(implementation: dict[str, object]) -> None:
    observed = implementation.get("observedAtHead")
    require(isinstance(observed, dict), "observedAtHead identity absent")
    observed_sha = observed.get("commit") if isinstance(observed, dict) else None
    observed_tree = observed.get("tree") if isinstance(observed, dict) else None
    require(exact_sha(observed_sha), "observedAtHead.commit must be an exact SHA")
    require(exact_sha(observed_tree), "observedAtHead.tree must be an exact tree identity")
    assert isinstance(observed_sha, str)
    assert isinstance(observed_tree, str)
    require(
        git("rev-parse", f"{observed_sha}^{{tree}}") == observed_tree,
        "observedAtHead commit/tree mismatch",
    )
    candidate = source_candidate_sha()
    ancestry = subprocess.run(
        ["git", "--no-replace-objects", "merge-base", "--is-ancestor", observed_sha, candidate],
        cwd=ROOT,
        check=False,
    )
    require(ancestry.returncode == 0, "observedAtHead is not an ancestor of the source candidate")
    changed = set(
        line
        for line in git(
            "diff",
            "--name-only",
            "--no-renames",
            observed_sha,
            candidate,
            "--",
        ).splitlines()
        if line
    )
    require(
        changed.issubset({MAP_PATH}),
        "implementation map observation is stale for source/workflow/test changes: "
        + ", ".join(sorted(changed - {MAP_PATH})),
    )


def require_opaque_non_clone(source: str, capability: str) -> None:
    match = re.search(rf"pub struct {capability}\b", source)
    require(match is not None, f"opaque capability absent: {capability}")
    prefix = source[max(0, match.start() - 160) : match.start()]
    require("derive(Clone" not in prefix, f"{capability} must not be clonable")


def verify_source() -> None:
    manifest = read("codex-rs/hepta-bellman-operator/Cargo.toml")
    require('path = "src/authoritative_lib.rs"' in manifest, "authoritative crate root")
    require(
        re.search(r"(?m)^default\s*=\s*\[\]$", manifest) is not None,
        "default feature set must remain empty",
    )
    require('qualification-unverified-input = []' in manifest, "compatibility feature missing")

    require_tokens(
        "codex-rs/hepta-bellman-operator/src/authoritative_lib.rs",
        [
            "mod budget;",
            "mod profiles;",
            "mod sensor_core_v2;",
            "mod tabular_v2;",
            "mod world_model_v2;",
            "mod final_use;",
            "mod final_use_hardening;",
            "FinalUseTabularCapabilityV1",
            "OpaquePinnedTabularArtifactV1",
            "OpaquePinnedWorldModelV1",
        ],
    )
    require_tokens(
        "codex-rs/hepta-bellman-operator/src/profiles.rs",
        [
            "pub struct TrainingProfileV1",
            "pub struct WorldModelProfileV1",
            "sensor_core_digest",
            "runtime_profile_digest",
            "profile_digest",
            "maximum_absolute_error",
            "maximum_ood_false_acceptance",
            "world_model_profile_digest_binds_sensor_core_identity",
        ],
    )
    require_tokens(
        "codex-rs/hepta-bellman-operator/src/budget.rs",
        [
            "pub struct WorkControlV1",
            "OperatorWorkErrorV1::Cancelled",
            "with_work_control_v1",
            "max_elapsed_micros",
        ],
    )

    final_use = read("codex-rs/hepta-bellman-operator/src/final_use.rs")
    for token in (
        "issue_tabular_final_use_capability_v1",
        "issue_world_model_final_use_capability_v1",
        "fit_tabular_final_use_v1",
        "fit_world_model_final_use_v1",
        "owner.revalidate_dataset_snapshot",
        "durable owner currentness changed at final use",
        "selection is stale or bound to another candidate/currentness epoch",
    ):
        require(token in final_use, f"final-use source missing {token!r}")
    for capability in (
        "OpaquePinnedTabularArtifactV1",
        "OpaquePinnedWorldModelV1",
    ):
        require_opaque_non_clone(final_use, capability)

    final_use_hardening = read(
        "codex-rs/hepta-bellman-operator/src/final_use_hardening.rs"
    )
    for token in (
        "issued_at_unix_micros",
        "absolute_deadline_unix_micros",
        "use_observed_at_unix_micros < issued_at_unix_micros",
        "publish_observed_at_unix_micros < use_observed_at_unix_micros",
        "issued_at_unix_micros >= absolute_deadline_unix_micros",
        "use_observed_at_unix_micros >= absolute_deadline_unix_micros",
        "publish_observed_at_unix_micros >= absolute_deadline_unix_micros",
        "capability_issue_at_deadline_fails_closed",
        "use_at_deadline_fails_closed",
        "use_before_capability_issue_is_clock_regression",
        "publish_before_use_is_clock_regression",
    ):
        require(token in final_use_hardening, f"final-use hardening missing {token!r}")
    for capability in (
        "FinalUseTabularCapabilityV1",
        "FinalUseWorldModelCapabilityV1",
    ):
        require_opaque_non_clone(final_use_hardening, capability)

    require_tokens(
        "codex-rs/hepta-bellman-operator/src/sensor_core_v2.rs",
        [
            "exact_candidate_limit",
            "maximum_working_candidates",
            "farthest_point_exact",
            "farthest_point_streaming",
            "OperatorWorkMeter",
        ],
    )
    require_tokens(
        "codex-rs/hepta-bellman-operator/src/authoritative_tests.rs",
        [
            "mutation_profile_digest_covers_runtime_and_error_budget",
            "mutation_cancelled_work_is_rejected_before_fit",
            "authoritative_performance_matrix_v1",
            "process_resident_bytes",
            "p99ResidentDeltaBytes",
            "p99EstimatedBytes",
            "1_000_usize, 4_000, 8_000, 16_000",
            "100_000_usize, 500_000, 1_000_000",
        ],
    )

    coordinator = read("codex-rs/hepta-agentd/src/learning_operator_coordinator.rs")
    for token in (
        "coordinate_learning_operator_shadow_v1",
        "fresh_process_load",
        "freeze_evaluation",
        "IndependentFutureWindowSuperiority",
        "CandidateRevoked",
        "ShadowCompleted",
        "LoadAfterDeadline",
        "CurrentnessClockRegression",
        "valid_window",
        "rollback",
    ):
        require(token in coordinator, f"shadow coordinator missing {token!r}")
    for forbidden in ("fn publish(", "fn canary(", "fn activate("):
        require(forbidden not in coordinator, f"default shadow coordinator exposes {forbidden}")
    require_tokens(
        "codex-rs/hepta-agentd/src/lib.rs",
        ["pub mod learning_operator_coordinator;"],
    )

    ranker_admission = read("codex-rs/hepta-agentd/src/cognitive_ranker_admission.rs")
    for token in (
        "pub struct RankerAdmissionSnapshotV2",
        "pub(crate) learning_verifier",
        "pub(crate) artifact_trust_digest",
        "pub(crate) runtime_profile_digest",
        "pub(crate) now_unix_micros",
        "impl RankerAdmissionSnapshotV2",
        "pub fn new(",
        "ranker admission requires current nonzero trust",
    ):
        require(token in ranker_admission, f"opaque ranker admission missing {token!r}")
    for public_field in (
        "pub learning_verifier:",
        "pub artifact_trust_digest:",
        "pub runtime_profile_digest:",
        "pub now_unix_micros:",
    ):
        require(public_field not in ranker_admission, f"ranker admission leaks {public_field!r}")

    compatibility = json.loads(read("docs/modules/learning.operator/SCHEMA_COMPATIBILITY.json"))
    require(
        compatibility.get("schema") == "hepta.learning-operator-schema-compatibility.v2"
        and compatibility.get("schemaVersion") == 2,
        "compatibility schema",
    )
    path = compatibility.get("defaultQualificationPath", {})
    require(
        path.get("trainingProfile") == "TrainingProfileV1"
        and path.get("worldModelProfile") == "WorldModelProfileV1"
        and path.get("tabularCapability") == "FinalUseTabularCapabilityV1"
        and path.get("worldModelCapability") == "FinalUseWorldModelCapabilityV1"
        and path.get("hostLoop") == "coordinate_learning_operator_shadow_v1",
        "default final-use qualification path",
    )
    require(path.get("activationAllowed") is False, "default path must not activate")

    implementation = json.loads(read(MAP_PATH))
    require(implementation.get("module") == "learning.operator", "implementation map identity")
    verify_observation_freshness(implementation)
    operations = {
        row.get("operation")
        for row in implementation.get("operations", [])
        if isinstance(row, dict)
    }
    required_operations = {
        "build_sensor_core_v2",
        "issue_tabular_final_use_capability_v1",
        "fit_tabular_final_use_v1",
        "issue_world_model_final_use_capability_v1",
        "fit_world_model_final_use_v1",
        "load_pinned_tabular_operator_v2",
        "coordinate_learning_operator_shadow_v1",
        "generate_current_implementation_map",
        "emit_qualification_manifest_v3",
    }
    require(required_operations.issubset(operations), "implementation map operation inventory")
    boundary = implementation.get("claimBoundary", {})
    require(boundary.get("singleUseFinalUseCapabilities") is True, "final-use claim boundary")
    require(boundary.get("exclusiveFinalUseDeadline") is True, "exclusive deadline claim boundary")
    require(
        boundary.get("worldModelSensorIdentityBound") is True,
        "world-model sensor identity claim boundary",
    )
    require(boundary.get("defaultShadowOnlyCoordinator") is True, "shadow-only claim boundary")
    require(boundary.get("activation") is False, "repository qualification cannot activate")
    require(boundary.get("release") is False, "repository qualification cannot release")

    for path in (
        "scripts/hepta-learning-operator-authoritative.sh",
        "scripts/hepta-learning-operator-evidence.py",
        "scripts/hepta-learning-operator-map.py",
        "scripts/hepta-learning-operator-mutation.py",
        "scripts/hepta-learning-operator-receipt.py",
        ".github/workflows/learning-operator-authoritative.yml",
    ):
        require((ROOT / path).is_file(), f"qualification component absent: {path}")
    workflow = read(".github/workflows/learning-operator-authoritative.yml")
    require("workflow_call:" in workflow, "authoritative workflow must be reusable")
    require("contents: read" in workflow, "authoritative workflow must be read-only")
    require(
        "paths:" not in workflow and "paths-ignore:" not in workflow,
        "authoritative workflow cannot path-skip",
    )
    require("qualification-result" in workflow, "stable final qualification check name")

    authoritative = read("scripts/hepta-learning-operator-authoritative.sh")
    for token in (
        "distinct_process_load_changes_prediction_and_rolls_back_without_retraining",
        "evaluated_load_uses_real_owner_training_selection_revocation_and_rollback",
        "fresh-process-load",
        "product-shadow-e2e",
        "time and memory qualification matrix",
    ):
        require(token in authoritative, f"authoritative qualification missing {token!r}")

    mutation = read("scripts/hepta-learning-operator-mutation.py")
    for token in (
        "omit-world-model-sensor-from-profile-digest",
        "relax-exclusive-final-use-deadline",
        "disable-final-use-issuance-clock-fence",
    ):
        require(token in mutation, f"mutation qualification missing {token!r}")

    blocking = read(".github/workflows/blocking-ci.yml")
    for token in (
        "learning-operator-authoritative:",
        "uses: ./.github/workflows/learning-operator-authoritative.yml",
        "needs.scope.outputs.learning",
        "- learning-operator-authoritative",
        "allowed.append(\"learning-operator-authoritative\")",
    ):
        require(token in blocking, f"protected CI fan-in missing {token!r}")

    for path in (
        "docs/modules/learning.operator/ADMISSION_CONTRACT.md",
        "docs/modules/learning.operator/COMPATIBILITY_RESOURCE_AND_SHADOW_POLICY.md",
        "docs/modules/learning.operator/OPERATIONS_RUNBOOK.md",
    ):
        require_tokens(
            path,
            [
                "FinalUseTabularCapabilityV1",
                "TrainingProfileV1",
                "coordinate_learning_operator_shadow_v1",
                "activation remains false",
            ],
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["verify"])
    parser.add_argument("--receipt")
    args = parser.parse_args()
    verify_source()
    if args.receipt:
        subprocess.run(
            [
                "python3",
                "scripts/hepta-learning-operator-receipt.py",
                "verify",
                "--path",
                args.receipt,
            ],
            cwd=ROOT,
            check=True,
        )
    print("learning.operator authoritative source/document contract verified")


if __name__ == "__main__":
    main()
