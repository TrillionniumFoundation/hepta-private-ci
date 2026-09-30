#!/usr/bin/env python3
"""Materialize and execute the isolated trusted-inprocess learning.eval fixture.

The compatibility feature remains absent from product dependency manifests. The
fixture is copied to a temporary standalone workspace, so Cargo.lock and target
artifacts cannot mutate the candidate tree. Passing this fixture proves only the
bounded compatibility regression; it grants no qualification or release authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "codex-rs/hepta-intelligence-eval"
FIXTURE = EVAL / "fixtures/trusted-inprocess"
SCHEMA = "hepta.learning-eval.trusted-fixture.v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scan_manifests() -> list[str]:
    """Reject product/workspace consumers that enable the compatibility feature."""
    offenders: list[str] = []
    main = EVAL / "Cargo.toml"
    for path in sorted((ROOT / "codex-rs").rglob("Cargo.toml")):
        if path == main:
            continue
        text = path.read_text(encoding="utf-8")
        if "trusted-inprocess-eval" in text:
            offenders.append(path.relative_to(ROOT).as_posix())
    if offenders:
        raise ValueError(
            "trusted-inprocess-eval is enabled outside its owning crate/fixture: "
            + ", ".join(offenders)
        )
    return [path.relative_to(ROOT).as_posix() for path in sorted((ROOT / "codex-rs").rglob("Cargo.toml"))]


def materialize(destination: Path) -> tuple[Path, Path]:
    template = FIXTURE / "Cargo.toml.in"
    source = FIXTURE / "tests/operator_claim.rs"
    if not template.is_file() or not source.is_file():
        raise ValueError("trusted fixture template or test source is missing")
    manifest = template.read_text(encoding="utf-8")
    replacements = {
        "@EVAL_PATH@": EVAL.resolve().as_posix(),
        "@LEDGER_PATH@": (ROOT / "codex-rs/hepta-learning-ledger").resolve().as_posix(),
        "@TYPES_PATH@": (ROOT / "codex-rs/hepta-types").resolve().as_posix(),
    }
    for token, value in replacements.items():
        manifest = manifest.replace(token, value)
    if "@" in manifest:
        raise ValueError("unresolved trusted fixture template token")
    (destination / "tests").mkdir(parents=True)
    manifest_path = destination / "Cargo.toml"
    test_path = destination / "tests/operator_claim.rs"
    manifest_path.write_text(manifest, encoding="utf-8")
    shutil.copyfile(source, test_path)
    return manifest_path, test_path


def write_evidence(path: Path | None, value: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--evidence")
    args = parser.parse_args(argv)
    evidence_path = Path(args.evidence).resolve() if args.evidence else None
    value: dict[str, Any] = {
        "schema": SCHEMA,
        "authority": "DENY_ALL",
        "claims": {
            "fixtureIsolated": False,
            "compatibilityRegressionExecuted": False,
            "targetHostQualified": False,
            "independentAcceptance": False,
            "activationAuthorized": False,
            "releaseAuthorized": False,
        },
    }
    try:
        manifests = scan_manifests()
        with tempfile.TemporaryDirectory(prefix="hepta-learning-eval-fixture-") as directory:
            root = Path(directory)
            manifest, test = materialize(root)
            value["fixture"] = {
                "templateSha256": sha256(FIXTURE / "Cargo.toml.in"),
                "testSha256": sha256(test),
                "scannedProductManifests": len(manifests),
            }
            value["claims"]["fixtureIsolated"] = True
            if args.check_only:
                write_evidence(evidence_path, value)
                print(json.dumps(value, sort_keys=True))
                return 0
            command = [
                "cargo", "test", "--manifest-path", str(manifest),
                "--test", "operator_claim", "--", "--test-threads=1",
            ]
            if args.offline:
                command.insert(2, "--offline")
            env = os.environ.copy()
            env["CARGO_TARGET_DIR"] = str(root / "target")
            completed = subprocess.run(
                command,
                cwd=root,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                check=False,
            )
            output = completed.stdout or ""
            if output:
                print(output, end="" if output.endswith("\n") else "\n")
            value["execution"] = {
                "argv": command,
                "exitCode": completed.returncode,
                "outputBytes": len(output.encode("utf-8", errors="replace")),
                "outputSha256": hashlib.sha256(output.encode("utf-8", errors="replace")).hexdigest(),
            }
            value["claims"]["compatibilityRegressionExecuted"] = completed.returncode == 0
            if completed.returncode != 0:
                value["failure"] = "compatibility_fixture_failed"
            write_evidence(evidence_path, value)
            return completed.returncode
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        value["failure"] = f"{type(error).__name__}: {error}"
        write_evidence(evidence_path, value)
        print(value["failure"], file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
