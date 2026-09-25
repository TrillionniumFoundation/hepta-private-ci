#!/usr/bin/env python3
"""Prove the default operator API cannot accept qualification-only raw inputs."""
from __future__ import annotations
import argparse
import json
import subprocess
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEATURE = "unchecked-qualification-inputs"
PACKAGE = "codex-hepta-bellman-operator"
RAW = (
    "fit_tabular_operator", "fit_tabular_operator_strict_v2",
    "predict_tabular_operator", "predict_tabular_operator_indexed_v2",
    "verify_tabular_operator_plan_v2", "fit_tabular_operator_verified_v2",
    "verify_world_model_dataset_v2", "fit_transition_model_verified_v2",
    "fit_transition_model", "predict_transition", "TabularWorldModelV1",
)


def manifest_findings(root: Path) -> list[str]:
    failures = []
    op = tomllib.loads((root / "codex-rs/hepta-bellman-operator/Cargo.toml").read_text())
    if op.get("features", {}).get("default") != [] or op.get("features", {}).get(FEATURE) != []:
        failures.append("the raw fixture feature must be explicit and disabled by default")
    for cargo in (root / "codex-rs").rglob("Cargo.toml"):
        name = cargo.relative_to(root).as_posix()
        manifest = tomllib.loads(cargo.read_text())
        for section in [manifest, *manifest.get("target", {}).values()]:
            for table in ("dependencies", "build-dependencies", "dev-dependencies"):
                for alias, dep in section.get(table, {}).items():
                    if not isinstance(dep, dict):
                        continue
                    if FEATURE in dep.get("features", []):
                        approved = (name == "codex-rs/hepta-shadow-qualification/Cargo.toml"
                                    and table == "dev-dependencies"
                                    and dep.get("package", alias) == PACKAGE)
                        if not approved:
                            failures.append(f"{name}:{table}:{alias} enables the raw operator feature")
        for feature, enables in manifest.get("features", {}).items():
            if any(item.split("/")[-1] == FEATURE for item in enables):
                failures.append(f"{name}:{feature} forwards the raw operator feature")
    return failures


def command(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False)


def verify_compilation() -> list[str]:
    cargo = ROOT / "codex-rs"
    build = command(["cargo", "build", "--locked", "-p", PACKAGE, "--lib", "--message-format=json"], cargo)
    if build.returncode:
        raise RuntimeError("default operator build failed:\n" + build.stderr[-12000:])
    library = None
    for line in build.stdout.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("reason") == "compiler-artifact" and row.get("target", {}).get("name") == "codex_hepta_bellman_operator":
            library = next((Path(f) for f in row["filenames"] if f.endswith(".rlib")), library)
    if library is None:
        raise RuntimeError("Cargo did not report the exact default library artifact")
    compiler = command(["rustup", "which", "rustc"], cargo)
    if compiler.returncode:
        raise RuntimeError(compiler.stderr)
    cases = []
    with tempfile.TemporaryDirectory(prefix="operator-api-") as directory:
        path = Path(directory)
        def probe(name: str, source: str, expected: str | None) -> None:
            file = path / f"{name}.rs"
            file.write_text(source)
            run = command([compiler.stdout.strip(), "--crate-type=lib", "--edition=2024", "--emit=metadata",
                           "--out-dir", directory, "-L", f"dependency={library.parent}",
                           "-L", f"dependency={library.parent / 'deps'}",
                           "--extern", f"codex_hepta_bellman_operator={library}", str(file)], cargo)
            if expected is None:
                if run.returncode:
                    raise RuntimeError("positive API control failed:\n" + run.stderr)
            elif run.returncode == 0 or expected not in run.stderr:
                raise RuntimeError(f"{name}: expected {expected} rejection, observed:\n{run.stderr}")
            cases.append(name)
        probe("owner_positive", "pub use codex_hepta_bellman_operator::{freeze_terminal_cell_from_owner_v1, fit_terminal_cell_from_owner_v1, LoadedTabularOperatorV1};", None)
        for symbol in RAW:
            probe("deny_" + symbol.lower(), f"pub use codex_hepta_bellman_operator::{symbol};", "E0432")
        probe("deny_loaded_mutation", "pub fn replace(model: &mut codex_hepta_bellman_operator::LoadedTabularOperatorV1) { model.artifact.cells.clear(); }", "E0616")
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    failures = manifest_findings(ROOT)
    cases = []
    if not failures:
        try:
            cases = verify_compilation()
        except (RuntimeError, OSError) as error:
            failures.append(str(error))
    print(json.dumps({"schema": "hepta.operator-default-api-boundary.v1", "ok": not failures,
                      "compiledCases": cases, "findings": failures}, indent=2))
    return bool(failures)

if __name__ == "__main__":
    raise SystemExit(main())
