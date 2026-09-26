#!/usr/bin/env python3
"""Emit an immutable cognitive.read qualification receipt for one exact commit."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HEX_SHA = re.compile(r"[0-9a-f]{40}")


def command(*args: str) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_key(value: object, key: str) -> list[object]:
    found: list[object] = []
    if isinstance(value, dict):
        for current_key, current_value in value.items():
            if current_key == key:
                found.append(current_value)
            found.extend(collect_key(current_value, key))
    elif isinstance(value, list):
        for current_value in value:
            found.extend(collect_key(current_value, key))
    return found


def parse_exit_codes(evidence: Path) -> dict[str, int]:
    exit_codes: dict[str, int] = {}
    for path in sorted(evidence.glob("*.exit-code")):
        label = path.name.removesuffix(".exit-code")
        try:
            exit_codes[label] = int(path.read_text(encoding="utf-8").strip())
        except ValueError as error:
            raise SystemExit(f"invalid exit code in {path}") from error
    return exit_codes


def parse_benchmark(evidence: Path) -> tuple[object | None, str | None]:
    path = evidence / "benchmark.json"
    if not path.is_file() or path.stat().st_size == 0:
        return None, "benchmark output missing"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except json.JSONDecodeError as error:
        return None, f"invalid benchmark JSON: {error}"


def evidence_manifest(evidence: Path, output: Path) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for path in sorted(evidence.rglob("*")):
        if path.is_symlink():
            raise SystemExit(f"evidence path must not be a symlink: {path}")
        if not path.is_file() or path == output or path.name == "SHA256SUMS":
            continue
        artifacts.append(
            {
                "path": path.relative_to(evidence).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    return artifacts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--kind",
        choices=("source-head", "merge-candidate"),
        required=True,
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    expected_sha = args.expected_sha.lower()
    if HEX_SHA.fullmatch(expected_sha) is None:
        raise SystemExit("--expected-sha must be a complete lowercase commit SHA")

    root = ROOT.resolve()
    evidence = (ROOT / args.evidence_dir).resolve()
    output = (ROOT / args.output).resolve()
    if not evidence.is_relative_to(root) or not output.is_relative_to(evidence):
        raise SystemExit("evidence and output paths must stay inside the repository evidence dir")
    evidence.mkdir(parents=True, exist_ok=True)

    actual_sha = command("git", "rev-parse", "HEAD")
    if actual_sha != expected_sha:
        raise SystemExit(f"exact-head mismatch: expected {expected_sha}, got {actual_sha}")
    tracked_status = command("git", "status", "--porcelain", "--untracked-files=no")
    if tracked_status:
        raise SystemExit(f"tracked worktree is not clean:\n{tracked_status}")

    map_path = ROOT / "docs/modules/cognitive.read/IMPLEMENTATION_MAP.json"
    try:
        implementation_map = json.loads(map_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SystemExit(f"invalid implementation map: {error}") from error
    activations = collect_key(implementation_map, "activation")
    if not activations or any(value is not False for value in activations):
        raise SystemExit("cognitive.read activation must remain explicitly false")

    exit_codes = parse_exit_codes(evidence)
    benchmark, benchmark_error = parse_benchmark(evidence)
    artifacts = evidence_manifest(evidence, output)
    passed = bool(exit_codes) and all(code == 0 for code in exit_codes.values())

    receipt = {
        "schema": "hepta.cognitive.read.qualification.v1",
        "kind": args.kind,
        "candidate": {
            "commit": actual_sha,
            "tree": command("git", "rev-parse", "HEAD^{tree}"),
            "tracked_worktree_clean": True,
        },
        "implementation_map": {
            "source_base": implementation_map.get("sourceBase"),
            "observed_at_head": implementation_map.get("observedAtHead"),
            "activation": False,
            "product_execution_proved": implementation_map.get(
                "productExecutionProved", False
            ),
        },
        "workflow": {
            "run_id": os.environ.get("GITHUB_RUN_ID"),
            "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "event": os.environ.get("GITHUB_EVENT_NAME"),
            "job": os.environ.get("GITHUB_JOB"),
        },
        "toolchain": {
            "rustc": command("rustc", "--version"),
            "cargo": command("cargo", "--version"),
        },
        "commands": exit_codes,
        "benchmark": benchmark,
        "benchmark_error": benchmark_error,
        "evidence_files": artifacts,
        "passed": passed,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "ok", "passed": passed, "output": str(output)}))


if __name__ == "__main__":
    main()
