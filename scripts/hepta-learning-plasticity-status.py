#!/usr/bin/env python3
"""Emit a self-reference-safe exact-head learning.plasticity status artifact."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UTC = dt.timezone.utc


def git(*args: str) -> str:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_NO_LAZY_FETCH="1",
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
    )
    return subprocess.run(
        ["git", "--literal-pathspecs", "-c", "core.fsmonitor=false", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def load_receipt(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema") != "hepta.learning-plasticity-command-receipt.v1":
        raise SystemExit("invalid learning.plasticity command receipt schema")
    commands = value.get("commands")
    if not isinstance(commands, list) or not commands:
        raise SystemExit("command receipt must contain commands")
    if any(command.get("conclusion") != "success" for command in commands):
        raise SystemExit("exact-head status cannot be emitted from a failed command receipt")
    return value


def iso(value: dt.datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--json", dest="json_path", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--workflow-name", required=True)
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--workflow-run-attempt", required=True)
    parser.add_argument("--evidence-valid-days", type=int, default=30)
    args = parser.parse_args()
    if not 1 <= args.evidence_valid_days <= 90:
        raise SystemExit("evidence validity must be within 1..=90 days")

    receipt_path = args.receipt.resolve()
    receipt = load_receipt(receipt_path)
    sha = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    if git("status", "--porcelain=v1", "--untracked-files=no"):
        raise SystemExit("exact-head status requires a clean tracked checkout")
    if receipt.get("sourceSha") != sha or receipt.get("sourceTree") != tree:
        raise SystemExit("command receipt does not bind the checked-out source")

    generated = dt.datetime.now(UTC)
    valid_until = generated + dt.timedelta(days=args.evidence_valid_days)
    repository = os.environ.get(
        "GITHUB_REPOSITORY", "TrillionniumFoundation/hepta-private-ci"
    )
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    run_url = f"{server}/{repository}/actions/runs/{args.workflow_run_id}"
    implementation_map = ROOT / "docs/modules/learning.plasticity/IMPLEMENTATION_MAP.json"
    host_profile = ROOT / "docs/modules/learning.plasticity/OPERATIONS.md"

    value = {
        "schema": "hepta.learning-plasticity-exact-head-status.v1",
        "schemaVersion": 1,
        "module": "learning.plasticity",
        "source": {"sha": sha, "tree": tree},
        "implementationMap": {
            "path": str(implementation_map.relative_to(ROOT)),
            "sha256": digest(implementation_map),
        },
        "workflow": {
            "name": args.workflow_name,
            "runId": str(args.workflow_run_id),
            "runAttempt": str(args.workflow_run_attempt),
            "url": run_url,
        },
        "commandReceipt": {
            "path": receipt_path.name,
            "sha256": digest(receipt_path),
            "commands": receipt["commands"],
        },
        "hostProfile": {
            "path": str(host_profile.relative_to(ROOT)),
            "sha256": digest(host_profile),
        },
        "generatedAt": iso(generated),
        "evidenceValidUntil": iso(valid_until),
        "claimBoundary": {
            "sourceQualification": True,
            "targetHostExecution": False,
            "physicalRollbackDomainIndependence": False,
            "independentAcceptance": False,
            "activation": False,
            "release": False,
        },
    }
    args.json_path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    rows = "\n".join(
        f"| `{command['name']}` | `{command['conclusion']}` |"
        for command in receipt["commands"]
    )
    markdown = f"""# learning.plasticity exact-head status

- Source SHA: `{sha}`
- Source tree: `{tree}`
- Implementation map SHA-256: `{value['implementationMap']['sha256']}`
- Workflow: [{args.workflow_name}]({run_url}), run `{args.workflow_run_id}`, attempt `{args.workflow_run_attempt}`
- Command receipt SHA-256: `{value['commandReceipt']['sha256']}`
- Host profile SHA-256: `{value['hostProfile']['sha256']}`
- Generated at: `{value['generatedAt']}`
- Evidence valid until: `{value['evidenceValidUntil']}`

| Qualification command | Conclusion |
| --- | --- |
{rows}

This artifact proves the recorded repository source qualification only. It does not
prove target-host execution, physical rollback-domain independence, independent
acceptance, activation or release.
"""
    args.markdown.write_text(markdown, encoding="utf-8")


if __name__ == "__main__":
    main()
