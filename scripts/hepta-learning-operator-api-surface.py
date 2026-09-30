#!/usr/bin/env python3
"""Compile independent consumers against the default and compatibility surfaces."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRATE = ROOT / "codex-rs/hepta-bellman-operator"

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
codex-hepta-types = {{ path = {json.dumps(str(ROOT / "codex-rs/hepta-types"))} }}
"""


def check(source: str, *, compatibility: bool) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="learning-operator-api-") as directory:
        root = Path(directory)
        (root / "src").mkdir()
        (root / "Cargo.toml").write_text(
            manifest(compatibility=compatibility), encoding="utf-8"
        )
        (root / "src/main.rs").write_text(source, encoding="utf-8")
        return subprocess.run(
            [
                "cargo",
                "check",
                "--quiet",
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

    for name, source, compatibility in (
        ("default-authoritative-pass", DEFAULT_PASS, False),
        ("feature-compatibility-pass", COMPATIBILITY_PASS, True),
    ):
        completed = check(source, compatibility=compatibility)
        passed = completed.returncode == 0
        results.append(
            {
                "name": name,
                "expected": "pass",
                "passed": passed,
                "stderr": completed.stderr[-4000:],
            }
        )
        if not passed:
            raise SystemExit(f"{name} failed to compile:\n{completed.stderr}")

    for name, source in DEFAULT_FAIL.items():
        completed = check(source, compatibility=False)
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
