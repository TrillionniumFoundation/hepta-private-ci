#!/usr/bin/env python3
"""Generate and verify the exact-source learning.operator implementation map.

The checked-in implementation map is a navigation/provenance document. This
qualification projection is generated *after* the source candidate commit, so
it can bind that exact commit/tree and every mapped source object without a
cryptographic self-reference.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_MAP = ROOT / "docs/modules/learning.operator/IMPLEMENTATION_MAP.json"
DEFAULT_OUTPUT = (
    ROOT / "qualification/lane-e/learning-operator-current-implementation-map.json"
)


def git(*args: str) -> str:
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
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


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def reject_legacy_source_commit(value: object, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "sourceCommit":
                raise ValueError(f"{path}.{key} is forbidden; use exact source identity")
            reject_legacy_source_commit(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_legacy_source_commit(child, f"{path}[{index}]")


def source_path_from_test(value: object) -> str | None:
    if isinstance(value, str):
        return value.split(".rs::", 1)[0] + ".rs" if ".rs::" in value else value
    if isinstance(value, dict):
        candidate = value.get("path", value.get("sourcePath"))
        return source_path_from_test(candidate)
    return None


def mapped_paths(row: dict[str, object]) -> list[str]:
    paths: set[str] = {
        "codex-rs/Cargo.toml",
        "codex-rs/Cargo.lock",
        "scripts/hepta-learning-operator-contract.py",
        "scripts/hepta-learning-operator-evidence.py",
        "scripts/hepta-learning-operator-map.py",
        "scripts/hepta-learning-operator-receipt.py",
    }
    for key in ("technicalGuide",):
        value = row.get(key)
        if isinstance(value, str) and value:
            paths.add(value)
    for key in ("declaredRoots", "resolvedRoots", "sourceRoot"):
        values = row.get(key, [])
        if isinstance(values, str):
            values = [values]
        if isinstance(values, list):
            paths.update(value for value in values if isinstance(value, str) and value)
    for operation in row.get("operations", []):
        if not isinstance(operation, dict):
            continue
        source = operation.get("sourcePath")
        if isinstance(source, str) and source:
            paths.add(source)
        for key in ("tests", "delegatedCallees"):
            for entry in operation.get(key, []):
                source = source_path_from_test(entry)
                if source:
                    paths.add(source)
    for caller in row.get("productCallers", []):
        if not isinstance(caller, dict):
            continue
        for key in ("sourcePath", "path"):
            source = caller.get(key)
            if isinstance(source, str) and source:
                paths.add(source)
    return sorted(paths)


def require_sha(value: str, label: str) -> None:
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError(f"{label} must be a literal SHA-1 identity")


def source_object(source_sha: str, path: str) -> dict[str, str]:
    object_sha = git("rev-parse", f"{source_sha}:{path}")
    kind = git("cat-file", "-t", object_sha)
    if kind not in {"blob", "tree"}:
        raise ValueError(f"{path}: unsupported Git object type {kind}")
    return {"path": path, "object": object_sha, "kind": kind}


def generate(source_sha: str, source_tree: str, output: Path) -> None:
    require_sha(source_sha, "source SHA")
    require_sha(source_tree, "source tree")
    if git("rev-parse", f"{source_sha}^{{tree}}") != source_tree:
        raise ValueError("source SHA/tree mismatch")
    row = json.loads(CANONICAL_MAP.read_text(encoding="utf-8"))
    reject_legacy_source_commit(row)
    if row.get("module") != "learning.operator":
        raise ValueError("canonical implementation map identity mismatch")

    paths = mapped_paths(row)
    objects = [source_object(source_sha, path) for path in paths]
    payload: dict[str, object] = {
        "schema": "hepta.learning-operator-current-implementation-map.v1",
        "schemaVersion": 1,
        "module": "learning.operator",
        "generatedFrom": str(CANONICAL_MAP.relative_to(ROOT)),
        "source": {"sha": source_sha, "tree": source_tree},
        "canonicalMapSha256": sha256_bytes(CANONICAL_MAP.read_bytes()),
        "claimBoundary": row.get("claimBoundary"),
        "productCallerState": row.get("productCallerState"),
        "productionWriterState": row.get("productionWriterState"),
        "operations": row.get("operations", []),
        "productCallers": row.get("productCallers", []),
        "sourceObjects": objects,
    }
    payload["projectionSha256"] = sha256_bytes(canonical_bytes(payload))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    verify(output, expected_sha=source_sha, expected_tree=source_tree)


def verify(
    path: Path,
    *,
    expected_sha: str | None = None,
    expected_tree: str | None = None,
) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    reject_legacy_source_commit(value)
    if value.get("schemaVersion") != 1 or value.get("module") != "learning.operator":
        raise ValueError("implementation projection schema or module mismatch")
    source = value.get("source")
    if not isinstance(source, dict):
        raise ValueError("implementation projection source identity absent")
    source_sha = source.get("sha")
    source_tree = source.get("tree")
    if not isinstance(source_sha, str) or not isinstance(source_tree, str):
        raise ValueError("implementation projection source identity malformed")
    require_sha(source_sha, "source SHA")
    require_sha(source_tree, "source tree")
    if expected_sha is not None and source_sha != expected_sha:
        raise ValueError("implementation projection source SHA differs from expected candidate")
    if expected_tree is not None and source_tree != expected_tree:
        raise ValueError("implementation projection source tree differs from expected candidate")
    if git("rev-parse", f"{source_sha}^{{tree}}") != source_tree:
        raise ValueError("implementation projection source SHA/tree mismatch")

    canonical_map_digest = sha256_bytes(CANONICAL_MAP.read_bytes())
    if value.get("canonicalMapSha256") != canonical_map_digest:
        raise ValueError("canonical implementation map digest drift")
    canonical = json.loads(CANONICAL_MAP.read_text(encoding="utf-8"))
    if value.get("operations") != canonical.get("operations"):
        raise ValueError("implementation operation inventory drift")
    if value.get("claimBoundary") != canonical.get("claimBoundary"):
        raise ValueError("implementation claim boundary drift")

    expected_paths = mapped_paths(canonical)
    entries = value.get("sourceObjects")
    if not isinstance(entries, list):
        raise ValueError("source object manifest absent")
    by_path: dict[str, dict[str, str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("source object entry malformed")
        object_path = entry.get("path")
        object_sha = entry.get("object")
        kind = entry.get("kind")
        if (
            not isinstance(object_path, str)
            or not isinstance(object_sha, str)
            or kind not in {"blob", "tree"}
        ):
            raise ValueError("source object entry malformed")
        if object_path in by_path:
            raise ValueError(f"duplicate source object path: {object_path}")
        actual = source_object(source_sha, object_path)
        if actual != entry:
            raise ValueError(f"source object drift: {object_path}")
        by_path[object_path] = entry
    if sorted(by_path) != expected_paths:
        raise ValueError("source object manifest is not the exact closed world")

    projection_digest = value.pop("projectionSha256", None)
    if projection_digest != sha256_bytes(canonical_bytes(value)):
        raise ValueError("implementation projection aggregate digest mismatch")
    value["projectionSha256"] = projection_digest


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    emit = subparsers.add_parser("emit")
    emit.add_argument("--source-sha", required=True)
    emit.add_argument("--source-tree", required=True)
    emit.add_argument("--output", default=str(DEFAULT_OUTPUT.relative_to(ROOT)))
    check = subparsers.add_parser("verify")
    check.add_argument("--path", default=str(DEFAULT_OUTPUT.relative_to(ROOT)))
    check.add_argument("--expected-sha")
    check.add_argument("--expected-tree")
    args = parser.parse_args()

    if args.command == "emit":
        generate(args.source_sha, args.source_tree, ROOT / args.output)
    else:
        verify(
            ROOT / args.path,
            expected_sha=args.expected_sha,
            expected_tree=args.expected_tree,
        )


if __name__ == "__main__":
    main()
