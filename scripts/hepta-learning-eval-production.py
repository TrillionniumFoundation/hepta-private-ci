#!/usr/bin/env python3
"""Fail-closed production boundary verifier and provenance emitter for learning.eval."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import subprocess
import sys
from typing import Iterable

ROOT = pathlib.Path(__file__).resolve().parents[1]
EVAL = ROOT / "codex-rs" / "hepta-intelligence-eval"
RUNTIME = ROOT / "codex-rs" / "hepta-intelligence" / "src" / "evaluated_shadow.rs"
CONTRACT = EVAL / "PRODUCTION_CONTRACT.md"
MATRIX = ROOT / "docs" / "lane-e" / "LANE_E_IMPLEMENTATION_MATRIX.json"
VERIFY_RECORD = (
    ROOT / "qualification" / "module-verification" / "detail" / "learning.eval-verification.md"
)

SOURCE_FILES = [
    CONTRACT,
    EVAL / "src" / "lib.rs",
    EVAL / "src" / "closure.rs",
    EVAL / "src" / "metric_roles.rs",
    EVAL / "src" / "signed_evaluation.rs",
    EVAL / "src" / "holdout_journal.rs",
    EVAL / "src" / "durable_holdout.rs",
    EVAL / "src" / "fenced_holdout.rs",
    EVAL / "tests" / "production_qualification_e2e.rs",
    RUNTIME,
    ROOT / "codex-rs" / "hepta-intelligence" / "src" / "evaluated_shadow_tests.rs",
    MATRIX,
    VERIFY_RECORD,
]


def die(message: str) -> None:
    print(f"learning.eval production verification: {message}", file=sys.stderr)
    raise SystemExit(1)


def read(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        die(f"cannot read {path.relative_to(ROOT)}: {exc}")


def require(condition: bool, message: str) -> None:
    if not condition:
        die(message)


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        die(f"git {' '.join(args)} failed: {exc}")


def command_identity(command: str, *args: str) -> str:
    try:
        return subprocess.check_output(
            [command, *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        return f"unavailable:{type(exc).__name__}"


def iter_evidence_files(paths: Iterable[pathlib.Path]) -> Iterable[pathlib.Path]:
    for path in paths:
        if path.is_file():
            yield path
        elif path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file():
                    yield child


def verify() -> None:
    for path in SOURCE_FILES:
        require(path.is_file(), f"required source/evidence file missing: {path.relative_to(ROOT)}")

    lib = read(EVAL / "src" / "lib.rs")
    require("pub fn evaluate(" not in lib, "legacy evaluate() remains public")
    require(
        "pub(crate) fn evaluate_legacy_inprocess" in lib,
        "legacy scalar comparator is not capability-isolated",
    )
    require("mod fenced_holdout;" in lib, "fenced holdout module not compiled")
    require(
        "pub use fenced_holdout::FencedFinalHoldoutStoreV1" in lib,
        "multi-host fenced store contract is not exported",
    )

    signed = read(EVAL / "src" / "signed_evaluation.rs")
    require(
        "decide_with_signed_evidence_v2" in signed
        and "verify_signed_role_separation" in signed,
        "signed V2 role-separated admission missing",
    )

    runtime = read(RUNTIME)
    require(
        "decide_with_signed_evidence_v2" in runtime,
        "production evaluated-shadow ingress does not consume signed V2 evidence",
    )
    require(
        "evaluation_signing_payload_v2" in runtime,
        "runtime does not bind candidate admission to V2 evaluation payload",
    )

    fenced = read(EVAL / "src" / "fenced_holdout.rs")
    for token in (
        "trait FencedFinalHoldoutStoreV1",
        "fn claim_fence(",
        "fn compare_and_swap(",
        "struct FencedFinalHoldoutOwnerV1",
        "StaleFence",
    ):
        require(token in fenced, f"multi-host holdout contract missing {token}")

    durable = read(EVAL / "src" / "durable_holdout.rs")
    require(
        "cooperating" in durable and "hostile" in durable,
        "single-host filesystem trust boundary is not explicit",
    )

    contract = read(CONTRACT)
    for token in (
        "Production-required",
        "decide_with_signed_evidence_v2",
        "decide_with_signed_longitudinal_evidence_v3",
        "FencedFinalHoldoutStoreV1",
        "source_implemented_ci_pending",
        "branch protection / rulesets",
    ):
        require(token in contract, f"production contract missing {token}")

    matrix = json.loads(read(MATRIX))
    rows = [row for row in matrix.get("modules", []) if row.get("module") == "learning.eval"]
    require(len(rows) == 1, "Lane E matrix must contain exactly one learning.eval row")
    require(
        rows[0].get("implementationState") in {"source_implemented_ci_pending", "closed"},
        "unexpected learning.eval implementation state",
    )

    print("learning.eval production boundary verification: ok")


def emit_provenance(output: pathlib.Path, expected_source: str | None, evidence: list[pathlib.Path]) -> None:
    verify()
    head = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    if expected_source:
        require(head == expected_source, f"source SHA mismatch: expected {expected_source}, got {head}")

    digests: dict[str, str] = {}
    for path in [*SOURCE_FILES, *iter_evidence_files(evidence)]:
        try:
            key = str(path.resolve().relative_to(ROOT.resolve()))
        except ValueError:
            key = str(path.resolve())
        digests[key] = sha256(path)

    manifest = {
        "schema": "hepta.learning-eval.provenance.v1",
        "source_commit": head,
        "source_tree": tree,
        "workflow": os.getenv("GITHUB_WORKFLOW", "local"),
        "workflow_run_id": os.getenv("GITHUB_RUN_ID", "local"),
        "workflow_run_attempt": os.getenv("GITHUB_RUN_ATTEMPT", "local"),
        "ref": os.getenv("GITHUB_REF", "local"),
        "actor": os.getenv("GITHUB_ACTOR", "local"),
        "rustc": command_identity("rustc", "--version"),
        "cargo": command_identity("cargo", "--version"),
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "sha256": dict(sorted(digests.items())),
        "security_note": (
            "CI provenance binds the retained qualification evidence to source; "
            "it is not a substitute for signed evaluator identity."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify")
    provenance = sub.add_parser("provenance")
    provenance.add_argument("--output", required=True, type=pathlib.Path)
    provenance.add_argument("--source-sha")
    provenance.add_argument("--evidence", action="append", default=[], type=pathlib.Path)
    args = parser.parse_args()
    if args.command == "verify":
        verify()
    else:
        emit_provenance(args.output, args.source_sha, args.evidence)


if __name__ == "__main__":
    main()
