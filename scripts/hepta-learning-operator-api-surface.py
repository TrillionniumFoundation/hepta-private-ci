#!/usr/bin/env python3
"""Compile independent consumers against the default and compatibility surfaces."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRATE = ROOT / "codex-rs/hepta-bellman-operator"
WORKSPACE_LOCK = ROOT / "codex-rs/Cargo.lock"

DEFAULT_PASS = """
use codex_hepta_bellman_operator::{
    FinalUseFenceV1,
    FitContextV1,
    LoadedTabularOperatorV2,
    QualifiedSensorCoreBuildReceiptV1,
    SensorCoreSelectionModeV1,
};
fn main() {
    let _ = core::mem::size_of::<FinalUseFenceV1>();
    let _ = core::mem::size_of::<FitContextV1>();
    let _ = core::mem::size_of::<LoadedTabularOperatorV2>();
    let _ = core::mem::size_of::<QualifiedSensorCoreBuildReceiptV1>();
    let _ = SensorCoreSelectionModeV1::Exact.as_str();
}
"""

COMPATIBILITY_PASS = """
use codex_hepta_bellman_operator::compatibility::{
    fit_tabular_operator,
    fit_tabular_operator_verified_v3,
    fit_transition_model,
    verify_tabular_operator_plan_v2,
    verify_tabular_operator_plan_v3,
    verify_world_model_dataset_v3,
};
fn main() {
    let _ = fit_tabular_operator;
    let _ = fit_tabular_operator_verified_v3;
    let _ = fit_transition_model;
    let _ = verify_tabular_operator_plan_v2;
    let _ = verify_tabular_operator_plan_v3;
    let _ = verify_world_model_dataset_v3;
}
"""

EVALUATION_AUTHENTICATION_PASS = """
use codex_hepta_intelligence_eval::{
    authenticate_evaluation_evidence_v2,
    ProductQualificationReceiptV1,
    SignedEvaluationError,
    VerifiedEvaluationAuthenticationV2,
};
fn require_authentication_only<F, A, B, C, D>(_: F)
where
    F: Fn(A, B, C, D, u64)
        -> Result<VerifiedEvaluationAuthenticationV2, SignedEvaluationError>,
{}
fn inspect(authentication: VerifiedEvaluationAuthenticationV2,
           qualification: &ProductQualificationReceiptV1) {
    let _ = authentication.generator();
    let _ = authentication.evaluator();
    let _ = authentication.trust_digest();
    let _ = authentication.authentication_digest();
    let _ = qualification.validate_integrity();
}
fn main() {
    require_authentication_only(authenticate_evaluation_evidence_v2);
}
"""

DEFAULT_FAIL = {
    "selected-load-clock": "use codex_hepta_bellman_operator::OpaquePinnedTabularArtifactV1; fn check(pin: OpaquePinnedTabularArtifactV1) { let _ = pin.load(); } fn main() {}\n",
    "selected-prediction-clock": "use codex_hepta_bellman_operator::SelectedTabularOperatorV1; use codex_hepta_types::StableId; fn check(model: SelectedTabularOperatorV1, id: StableId) { let _ = model.predict(&id, &id); } fn main() {}\n",
    "selected-loader-escape": "use codex_hepta_bellman_operator::SelectedTabularOperatorV1; fn check(model: SelectedTabularOperatorV1) { let _ = model.loaded; } fn main() {}\n",
    "raw-fitter": "use codex_hepta_bellman_operator::fit_tabular_operator; fn main() { let _ = fit_tabular_operator; }\n",
    "bounded-raw-fitter": "use codex_hepta_bellman_operator::fit_tabular_operator_bounded_v2; fn main() { let _ = fit_tabular_operator_bounded_v2; }\n",
    "direct-v3-tabular-verifier": "use codex_hepta_bellman_operator::verify_tabular_operator_plan_v3; fn main() { let _ = verify_tabular_operator_plan_v3; }\n",
    "direct-v3-tabular-fitter": "use codex_hepta_bellman_operator::fit_tabular_operator_verified_v3; fn main() { let _ = fit_tabular_operator_verified_v3; }\n",
    "direct-v3-world-verifier": "use codex_hepta_bellman_operator::verify_world_model_dataset_v3; fn main() { let _ = verify_world_model_dataset_v3; }\n",
    "direct-v3-world-fitter": "use codex_hepta_bellman_operator::fit_transition_model_verified_v3; fn main() { let _ = fit_transition_model_verified_v3; }\n",
    "compatibility-module": "use codex_hepta_bellman_operator::compatibility::fit_tabular_operator; fn main() { let _ = fit_tabular_operator; }\n",
    "activation-port": "use codex_hepta_bellman_operator::activate_operator; fn main() { let _ = activate_operator; }\n",
    "publish-port": "use codex_hepta_bellman_operator::publish_operator; fn main() { let _ = publish_operator; }\n",
    "raw-signed-evaluation-v2": "use codex_hepta_intelligence_eval::decide_with_signed_evidence_v2; fn main() { let _ = decide_with_signed_evidence_v2; }\n",
    "raw-signed-longitudinal-evaluation-v3": "use codex_hepta_intelligence_eval::decide_with_signed_longitudinal_evidence_v3; fn main() { let _ = decide_with_signed_longitudinal_evidence_v3; }\n",
    "qualification-seal-rewrite": "use codex_hepta_intelligence_eval::ProductQualificationReceiptV1; fn rewrite(mut receipt: ProductQualificationReceiptV1) { receipt.receipt_seal = receipt.evidence_digest; } fn main() {}\n",
    "qualification-external-construction": "use codex_hepta_intelligence_eval::ProductQualificationReceiptV1; fn forge(receipt: ProductQualificationReceiptV1) -> ProductQualificationReceiptV1 { ProductQualificationReceiptV1 { evidence_digest: receipt.publication_digest, ..receipt } } fn main() {}\n",
}

EXPECTED_DIAGNOSTIC_TOKENS = {
    "selected-load-clock": ("error[E0061]", "argument #1 of type `u64` is missing"),
    "selected-prediction-clock": (
        "error[E0061]",
        "argument #3 of type `u64` is missing",
    ),
    "selected-loader-escape": ("error[E0616]", "field `loaded`"),
    "raw-fitter": (
        "error[E0432]",
        "fit_tabular_operator",
    ),
    "bounded-raw-fitter": (
        "error[E0432]",
        "fit_tabular_operator_bounded_v2",
    ),
    "direct-v3-tabular-verifier": (
        "error[E0603]",
        "verify_tabular_operator_plan_v3",
    ),
    "direct-v3-tabular-fitter": (
        "error[E0432]",
        "fit_tabular_operator_verified_v3",
    ),
    "direct-v3-world-verifier": (
        "error[E0603]",
        "verify_world_model_dataset_v3",
    ),
    "direct-v3-world-fitter": (
        "error[E0432]",
        "fit_transition_model_verified_v3",
    ),
    "compatibility-module": (
        "error[E0432]",
        "compatibility",
    ),
    "activation-port": (
        "error[E0432]",
        "activate_operator",
    ),
    "publish-port": (
        "error[E0432]",
        "publish_operator",
    ),
    "raw-signed-evaluation-v2": (
        "error[E0603]",
        "decide_with_signed_evidence_v2",
    ),
    "raw-signed-longitudinal-evaluation-v3": (
        "error[E0603]",
        "decide_with_signed_longitudinal_evidence_v3",
    ),
    "qualification-seal-rewrite": ("error[E0616]", "field `receipt_seal`"),
    "qualification-external-construction": ("error[E0451]", "field `receipt_seal`"),
}


def manifest(*, compatibility: bool) -> str:
    feature = ', features = ["qualification-unverified-input"]' if compatibility else ""
    return f"""[package]
name = "learning-operator-api-consumer"
version = "0.0.0"
edition = "2024"
publish = false

[workspace]

[dependencies]
codex-hepta-bellman-operator = {{ path = {json.dumps(str(CRATE))}{feature} }}
codex-hepta-intelligence-eval = {{ path = {json.dumps(str(ROOT / "codex-rs/hepta-intelligence-eval"))} }}
codex-hepta-types = {{ path = {json.dumps(str(ROOT / "codex-rs/hepta-types"))} }}
"""


def package_identity(package: dict[str, object]) -> tuple[object, ...]:
    return tuple(package.get(key) for key in ("name", "version", "source", "checksum"))


def check(
    source: str, *, compatibility: bool, workspace_lock: bytes
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="learning-operator-api-") as directory:
        root = Path(directory)
        (root / "src").mkdir()
        (root / "Cargo.toml").write_text(
            manifest(compatibility=compatibility), encoding="utf-8"
        )
        (root / "src/main.rs").write_text(source, encoding="utf-8")
        (root / "Cargo.lock").write_bytes(workspace_lock)
        # Cargo must add this independent root and prune unused workspace members.
        # Permit that projection offline, then reject any dependency pin drift
        # before compiling the consumer under --locked.
        projection = subprocess.run(
            [
                "cargo",
                "metadata",
                "--offline",
                "--format-version",
                "1",
                "--manifest-path",
                str(root / "Cargo.toml"),
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if projection.returncode != 0:
            return projection
        locked_packages = {
            package_identity(package)
            for package in tomllib.loads(workspace_lock.decode("utf-8"))["package"]
        }
        consumer_lock = tomllib.loads((root / "Cargo.lock").read_text(encoding="utf-8"))
        for package in consumer_lock["package"]:
            if package["name"] == "learning-operator-api-consumer":
                continue
            if package_identity(package) not in locked_packages:
                return subprocess.CompletedProcess(
                    projection.args,
                    1,
                    stdout="",
                    stderr=f"consumer dependency differs from workspace Cargo.lock: {package_identity(package)!r}\n",
                )
        return subprocess.run(
            [
                "cargo",
                "check",
                "--quiet",
                "--offline",
                "--locked",
                "--manifest-path",
                str(root / "Cargo.toml"),
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    args = parser.parse_args()
    results: list[dict[str, object]] = []
    workspace_lock = WORKSPACE_LOCK.read_bytes()

    for name, source, compatibility in (
        ("default-authoritative-pass", DEFAULT_PASS, False),
        ("feature-compatibility-pass", COMPATIBILITY_PASS, True),
        ("evaluation-authentication-only-pass", EVALUATION_AUTHENTICATION_PASS, False),
    ):
        completed = check(
            source, compatibility=compatibility, workspace_lock=workspace_lock
        )
        passed = completed.returncode == 0
        results.append(
            {
                "name": name,
                "expected": "pass",
                "passed": passed,
                "exitCode": completed.returncode,
                "stderr": completed.stderr[-4000:],
            }
        )
        if not passed:
            raise SystemExit(f"{name} failed to compile:\n{completed.stderr}")

    for name, source in DEFAULT_FAIL.items():
        completed = check(source, compatibility=False, workspace_lock=workspace_lock)
        diagnostic = completed.stderr
        rejected = completed.returncode != 0
        relevant = all(
            token.lower() in diagnostic.lower()
            for token in EXPECTED_DIAGNOSTIC_TOKENS[name]
        )
        passed = rejected and relevant
        results.append(
            {
                "name": name,
                "expected": "compile-fail",
                "passed": passed,
                "exitCode": completed.returncode,
                "expectedDiagnosticTokens": EXPECTED_DIAGNOSTIC_TOKENS[name],
                "stderr": diagnostic[-4000:],
            }
        )
        if not passed:
            raise SystemExit(
                f"{name} did not fail for the expected public-surface reason:\n{diagnostic}"
            )

    payload = {
        "schema": "hepta.learning-operator-api-surface.v2",
        "schemaVersion": 2,
        "defaultCompatibilityFeatureEnabled": False,
        "defaultDirectV3FitAllowed": False,
        "workspaceLockSha256": hashlib.sha256(workspace_lock).hexdigest(),
        "workspaceDependencyPinsEnforced": True,
        "results": results,
        "passed": all(bool(row["passed"]) for row in results),
    }
    if args.output:
        output = ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
