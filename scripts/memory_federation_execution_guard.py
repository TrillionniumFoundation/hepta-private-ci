#!/usr/bin/env python3
"""Pin one memory.federation qualification execution to immutable inputs.

The guard is intentionally independent from the final attestation.  It captures
HEAD/tree, the complete qualified source manifest, and the declared command
contract before compilation begins, then recomputes all four after the matrix.
A source edit, command edit, checkout movement, or hidden tracked mutation makes
the run ineligible for a success receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import tempfile
from typing import Any

import memory_federation_full_attestation as full

SCHEMA = "hepta.memory-federation.execution-guard.v1"
ROOT = pathlib.Path(__file__).resolve().parents[1]


class GuardError(RuntimeError):
    pass


def _run(*argv: str) -> str:
    completed = subprocess.run(
        argv,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise GuardError(
            f"{' '.join(argv)} failed with {completed.returncode}: "
            f"{completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def _git(*argv: str) -> str:
    return _run("git", *argv)


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _candidate() -> dict[str, str]:
    return {
        "sha": _git("rev-parse", "HEAD"),
        "tree": _git("rev-parse", "HEAD^{tree}"),
    }


def _require_clean_tracked_checkout() -> None:
    dirty = _git("status", "--porcelain=v1", "--untracked-files=no")
    if dirty:
        raise GuardError("tracked checkout changed during qualification")


def _snapshot(expected_sha: str, expected_tree: str) -> dict[str, Any]:
    candidate = _candidate()
    if candidate != {"sha": expected_sha, "tree": expected_tree}:
        raise GuardError(
            "qualification candidate identity changed: "
            f"expected {expected_sha}/{expected_tree}, "
            f"observed {candidate['sha']}/{candidate['tree']}"
        )
    _require_clean_tracked_checkout()
    manifest = full.base._source_manifest()
    commands = list(full.base.COMMANDS)
    qualified_paths = list(full.base.QUALIFIED_PATHS)
    return {
        "schema": SCHEMA,
        "module": "memory.federation",
        "candidate": candidate,
        "sourceManifestSha256": _sha256(_canonical_bytes(manifest)),
        "qualifiedFileCount": len(manifest),
        "qualifiedPathsSha256": _sha256(_canonical_bytes(qualified_paths)),
        "commandManifestSha256": _sha256(_canonical_bytes(commands)),
        "commandCount": len(commands),
    }


def _sidecar(path: pathlib.Path) -> pathlib.Path:
    return path.with_suffix(path.suffix + ".sha256")


def _write(path: pathlib.Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical_bytes(value)
    path.write_bytes(payload)
    _sidecar(path).write_text(f"{_sha256(payload)}  {path.name}\n", encoding="utf-8")


def _read(path: pathlib.Path) -> dict[str, Any]:
    try:
        payload = path.read_bytes()
        sidecar = _sidecar(path).read_text(encoding="utf-8").strip()
        expected = f"{_sha256(payload)}  {path.name}"
        if sidecar != expected:
            raise GuardError("execution guard sidecar digest mismatch")
        value = json.loads(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GuardError(f"cannot read execution guard: {error}") from error
    if not isinstance(value, dict):
        raise GuardError("execution guard must be a JSON object")
    return value


def capture(path: pathlib.Path, expected_sha: str, expected_tree: str) -> int:
    _write(path, _snapshot(expected_sha, expected_tree))
    return 0


def verify(path: pathlib.Path, expected_sha: str, expected_tree: str) -> int:
    recorded = _read(path)
    current = _snapshot(expected_sha, expected_tree)
    if recorded != current:
        changed = sorted(
            key
            for key in set(recorded) | set(current)
            if recorded.get(key) != current.get(key)
        )
        raise GuardError(
            "qualification inputs changed during execution: " + ", ".join(changed)
        )
    return 0


def self_test() -> int:
    candidate = _candidate()
    with tempfile.TemporaryDirectory(prefix="memory-federation-guard-") as directory:
        path = pathlib.Path(directory) / "guard.json"
        capture(path, candidate["sha"], candidate["tree"])
        verify(path, candidate["sha"], candidate["tree"])

        tampered = _read(path)
        tampered["commandManifestSha256"] = "0" * 64
        _write(path, tampered)
        try:
            verify(path, candidate["sha"], candidate["tree"])
        except GuardError:
            pass
        else:
            raise GuardError("self-test accepted a changed command contract")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("capture", "verify"):
        command = subparsers.add_parser(name)
        command.add_argument("--state", required=True, type=pathlib.Path)
        command.add_argument("--expected-sha", required=True)
        command.add_argument("--expected-tree", required=True)
    subparsers.add_parser("self-test")

    args = parser.parse_args()
    if args.command == "capture":
        return capture(args.state, args.expected_sha, args.expected_tree)
    if args.command == "verify":
        return verify(args.state, args.expected_sha, args.expected_tree)
    return self_test()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GuardError as error:
        raise SystemExit(f"FAIL_MEMORY_FEDERATION_EXECUTION_GUARD: {error}") from error
