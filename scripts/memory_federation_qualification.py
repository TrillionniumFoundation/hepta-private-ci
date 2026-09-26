#!/usr/bin/env python3
"""Build self-digesting memory.federation qualification attestations."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
from pathlib import Path


def run(*argv: str) -> str:
    return subprocess.run(
        argv,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def command_records(directory: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in sorted(directory.glob("*.json")):
        raw = path.read_bytes()
        records.append(
            {
                "path": path.name,
                "sha256": sha256(raw),
                "record": json.loads(raw),
            }
        )
    if not records:
        raise SystemExit("no qualification command records were found")
    return records


def finalize(args: argparse.Namespace) -> None:
    evidence = Path(args.evidence_dir)
    tested_sha = run("git", "rev-parse", "HEAD")
    tested_tree = run("git", "rev-parse", "HEAD^{tree}")
    if tested_sha != args.tested_sha:
        raise SystemExit(
            f"tested SHA mismatch: expected {args.tested_sha}, observed {tested_sha}"
        )
    value: dict[str, object] = {
        "schema": "hepta.memory-federation.qualification-attestation.v1",
        "schemaVersion": 1,
        "module": "memory.federation",
        "lane": args.lane,
        "sourceSha": args.source_sha,
        "baseSha": args.base_sha or None,
        "mergeSha": args.merge_sha or None,
        "testedSha": tested_sha,
        "testedTree": tested_tree,
        "toolchain": {
            "rustc": run("rustc", "--version", "--verbose"),
            "cargo": run("cargo", "--version", "--verbose"),
            "python": run("python3", "--version"),
        },
        "commands": command_records(evidence),
        "conclusion": "passed",
        "workflow": {
            "repository": os.environ.get("GITHUB_REPOSITORY"),
            "workflow": os.environ.get("GITHUB_WORKFLOW"),
            "runId": os.environ.get("GITHUB_RUN_ID"),
            "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "job": os.environ.get("GITHUB_JOB"),
        },
        "generatedAtUtc": dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
    }
    value["attestationDigestSha256"] = sha256(canonical(value))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def envelope(args: argparse.Namespace) -> None:
    attestation = Path(args.attestation)
    raw = attestation.read_bytes()
    value = {
        "schema": "hepta.memory-federation.qualification-artifact-envelope.v1",
        "schemaVersion": 1,
        "module": "memory.federation",
        "lane": args.lane,
        "attestationSha256": sha256(raw),
        "evidenceArtifactDigest": args.artifact_digest,
        "runId": os.environ.get("GITHUB_RUN_ID"),
        "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
    }
    value["envelopeDigestSha256"] = sha256(canonical(value))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)

    final = commands.add_parser("finalize")
    final.add_argument("--lane", required=True)
    final.add_argument("--source-sha", required=True)
    final.add_argument("--base-sha", default="")
    final.add_argument("--merge-sha", default="")
    final.add_argument("--tested-sha", required=True)
    final.add_argument("--evidence-dir", required=True)
    final.add_argument("--output", required=True)
    final.set_defaults(function=finalize)

    env = commands.add_parser("envelope")
    env.add_argument("--lane", required=True)
    env.add_argument("--attestation", required=True)
    env.add_argument("--artifact-digest", required=True)
    env.add_argument("--output", required=True)
    env.set_defaults(function=envelope)
    return root


def main() -> None:
    args = parser().parse_args()
    args.function(args)


if __name__ == "__main__":
    main()
