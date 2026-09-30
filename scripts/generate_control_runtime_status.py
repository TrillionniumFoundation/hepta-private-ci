#!/usr/bin/env python3
"""Generate exact-head control.runtime status and qualification matrix evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
MODULE_DOCS = ROOT / "docs/modules/control.runtime"
STATUS_TEMPLATE = MODULE_DOCS / "STATUS.json"
QUALIFICATION_WORKFLOW = ROOT / ".github/workflows/control-runtime-qualification.yml"

REQUIRED_WORKFLOW_TOKENS = (
    "cargo fmt --all -- --check",
    "cargo check --locked --all-targets",
    "cargo test --locked -p codex-hepta-control-plane",
    "cargo clippy --locked --all-targets",
    "matrix:",
    "lane: [source-head, synthetic-merge]",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-sha", default=os.environ.get("GITHUB_SHA"))
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "target/control-runtime-status/STATUS.json",
    )
    parser.add_argument(
        "--matrix-output",
        type=Path,
        default=ROOT / "target/control-runtime-status/TEST_MATRIX.json",
    )
    parser.add_argument("--check-template", action="store_true")
    return parser.parse_args()


def git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def source_files() -> Iterable[Path]:
    fixed = (
        ROOT / "codex-rs/hepta-control-plane/Cargo.toml",
        QUALIFICATION_WORKFLOW,
        ROOT / ".github/workflows/control-runtime-acceptance.yml",
        Path(__file__).resolve(),
    )
    for path in fixed:
        if path.exists():
            yield path
    for base in (
        ROOT / "codex-rs/hepta-control-plane/src",
        ROOT / "codex-rs/hepta-control-plane/tests",
        MODULE_DOCS,
    ):
        if not base.exists():
            continue
        for path in sorted(item for item in base.rglob("*") if item.is_file()):
            if path == STATUS_TEMPLATE:
                continue
            yield path


def source_digest() -> str:
    digest = hashlib.sha256()
    digest.update(b"hepta.control-runtime.source-set.v1\0")
    for path in sorted(set(source_files())):
        relative = path.relative_to(ROOT).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def validate_template(template: dict[str, object]) -> None:
    if template.get("schema") != "hepta.control-runtime.status.v1":
        raise SystemExit("unexpected control.runtime STATUS schema")
    if template.get("sourceSha") != "${GITHUB_SHA}":
        raise SystemExit("STATUS.json must retain the ${GITHUB_SHA} template value")
    if template.get("sourceDigest") != "${CONTROL_RUNTIME_SOURCE_DIGEST}":
        raise SystemExit("STATUS.json must retain the source digest template value")
    workflow = QUALIFICATION_WORKFLOW.read_text(encoding="utf-8")
    missing = [token for token in REQUIRED_WORKFLOW_TOKENS if token not in workflow]
    if missing:
        raise SystemExit(f"qualification workflow is missing required tokens: {missing}")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    template = json.loads(STATUS_TEMPLATE.read_text(encoding="utf-8"))
    validate_template(template)
    if args.check_template:
        return

    source_sha = args.source_sha or git_head()
    if len(source_sha) != 40 or any(character not in "0123456789abcdef" for character in source_sha):
        raise SystemExit("source SHA must be a lowercase 40-character Git object id")
    digest = source_digest()

    status = dict(template)
    status["sourceSha"] = source_sha
    status["sourceDigest"] = digest
    status["generatedBy"] = "scripts/generate_control_runtime_status.py"
    write_json(args.output, status)

    matrix = {
        "schema": "hepta.control-runtime.test-matrix.v1",
        "sourceSha": source_sha,
        "sourceDigest": digest,
        "workflow": ".github/workflows/control-runtime-qualification.yml",
        "lanes": ["source-head", "synthetic-merge"],
        "requiredChecks": [
            "repository invariants",
            "formatting",
            "locked all-target compilation",
            "control runtime package tests",
            "NDU regression suite",
            "strict Clippy",
            "named-host NDU qualification",
            "clean source preservation",
        ],
        "externalEvidenceGates": [
            "HIL qualification",
            "physical device qualification",
            "independent security acceptance",
            "activation approval",
            "release approval",
        ],
    }
    write_json(args.matrix_output, matrix)


if __name__ == "__main__":
    main()
