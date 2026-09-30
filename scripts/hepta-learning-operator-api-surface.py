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
    fit_transition_model,
    verify_tabular_operator_plan_v2,
};
fn main() {
    let _ = fit_tabular_operator;
    let _ = fit_transition_model;
    let _ = verify_tabular_operator_plan_v2;
}
"""

DEFAULT_FAIL = {
    "raw-fitter": "use codex_hepta_bellman_operator::fit_tabular_operator; fn main() { let _ = fit_tabular_operator; }\n",
    "compatibility-module": "use codex_hepta_bellman_operator::compatibility::fit_tabular_operator; fn main() { let _ = fit_tabular_operator; }\n",
    "activation-port": "use codex_hepta_bellman_operator::activate_operator; fn main() { let _ = activate_operator; }\n",
    "publish-port": "use codex_hepta_bellman_operator::publish_operator; fn main() { let _ = publish_operator; }\n",
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
        rejected = completed.returncode != 0
        diagnostic = completed.stderr
        relevant = name.split("-")[0] in diagnostic.lower() or any(
            token in diagnostic
            for token in (
                "fit_tabular_operator",
                "compatibility",
                "activate_operator",
                "publish_operator",
            )
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
        "schema": "hepta.learning-operator-api-surface.v1",
        "schemaVersion": 1,
        "defaultCompatibilityFeatureEnabled": False,
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
