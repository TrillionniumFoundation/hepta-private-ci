#!/usr/bin/env python3
"""Bind review slices to exact Git ranges and one candidate command set."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

import channel_matrix_evidence as evidence

ROOT = SCRIPT_DIRECTORY.parent
REGISTRY_PATH = ROOT / "docs/modules/channel.matrix/REVIEW_SLICES.json"
RESULT_SCHEMA = "hepta.channel-matrix-review-slice-receipt.v1"
REGISTRY_SCHEMA = "hepta.channel-matrix-review-slices.v1"
EXPECTED_SLICE_IDS = (
    "01-sdk-final-use",
    "02-durable-store-migrations",
    "03-runtime-recovery",
    "04-transport-adapter-tcb",
    "05-observability-clock",
    "06-qualification-evidence",
    "07-documentation-generated-status",
)
SHA1 = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
MAX_JSON_BYTES = 64 * 1024 * 1024


def git(root: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
    )


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def object_digest(value: object, domain: bytes) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(domain + b"\0" + encoded).hexdigest()


def read_object(path: Path) -> dict[str, Any]:
    def unique(pairs):
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key in {path.name}: {key}")
            result[key] = value
        return result

    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError(f"invalid review evidence object: {path}")
    row = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if not isinstance(row, dict):
        raise ValueError(f"review evidence must be an object: {path}")
    return row


def split_z(value: bytes) -> list[str]:
    return [item.decode("utf-8") for item in value.split(b"\0") if item]


def exact_commit(root: Path, value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA1.fullmatch(value):
        raise ValueError(f"{label} is not exact lowercase 40-hex")
    resolved = git(root, "rev-parse", f"{value}^{{commit}}").stdout.decode().strip()
    if resolved != value:
        raise ValueError(f"{label} changed during Git resolution")
    return value


def command_policy() -> dict[str, list[str]]:
    if "api-compile-fail" not in evidence.COMMANDS:
        # Importing the policy overlay mutates the canonical command map for
        # this process. It does not execute commands or introduce a second
        # receipt format.
        import channel_matrix_evidence_v2  # noqa: F401

    return evidence.COMMANDS


def load_registry(path: Path = REGISTRY_PATH) -> tuple[list[dict[str, Any]], str]:
    row = read_object(path)
    if (
        row.get("schema") != REGISTRY_SCHEMA
        or row.get("schemaVersion") != 1
        or row.get("module") != "channel.matrix"
        or row.get("historyPolicy") != "append_only_review_slices_no_history_rewrite"
        or row.get("rangePolicy") != "derive_first_last_touch_from_exact_base_and_head"
        or set(row)
        != {
            "schema",
            "schemaVersion",
            "module",
            "historyPolicy",
            "rangePolicy",
            "slices",
        }
    ):
        raise ValueError("unsupported review-slice registry")
    slices = row.get("slices")
    if (
        not isinstance(slices, list)
        or tuple(item.get("id") for item in slices if isinstance(item, dict))
        != EXPECTED_SLICE_IDS
        or len(slices) != len(EXPECTED_SLICE_IDS)
    ):
        raise ValueError("review-slice inventory is incomplete or reordered")
    seen_paths: set[str] = set()
    for item in slices:
        if (
            not isinstance(item, dict)
            or set(item)
            != {"id", "owner", "deputy", "paths", "invariants", "commands"}
        ):
            raise ValueError("invalid review slice")
        for field in ("owner", "deputy"):
            if not isinstance(item[field], str) or not item[field]:
                raise ValueError(f"review slice lacks {field}")
        for field in ("paths", "invariants"):
            values = item[field]
            if (
                not isinstance(values, list)
                or not values
                or values != sorted(values)
                or len(values) != len(set(values))
                or any(not isinstance(value, str) or not value for value in values)
            ):
                raise ValueError(f"review slice has invalid {field}")
        commands = item["commands"]
        if (
            not isinstance(commands, list)
            or not commands
            or len(commands) != len(set(commands))
            or any(not isinstance(command, str) or not command for command in commands)
        ):
            raise ValueError("review slice has invalid commands")
        overlap = seen_paths & set(item["paths"])
        if overlap:
            raise ValueError(f"review-slice paths overlap: {sorted(overlap)}")
        seen_paths.update(item["paths"])
    return slices, digest(path)


def validate_command_receipts(
    directory: Path,
    source: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    source_digest = digest(directory / "source.json")
    receipts: dict[str, Any] = {}
    for label, arguments in command_policy().items():
        command_path = directory / f"{label}.command.json"
        log_path = directory / f"{label}.log"
        row = read_object(command_path)
        if (
            row.get("schema") != "hepta.channel-matrix-command.v1"
            or row.get("label") != label
            or row.get("arguments") != arguments
            or row.get("workingDirectory") != "codex-rs"
            or row.get("testedSha") != source.get("testedSha")
            or row.get("sourceSnapshotSha256") != source_digest
            or type(row.get("exitCode")) is not int
            or row.get("exitCode") != 0
            or row.get("completed") is not True
            or row.get("launchError") is not None
            or row.get("sourceUnchanged") is not True
            or not log_path.is_file()
            or row.get("log")
            != {
                "path": log_path.name,
                "bytes": log_path.stat().st_size,
                "sha256": digest(log_path),
                "withinBudget": True,
            }
        ):
            raise ValueError(f"review slice cannot bind failed command: {label}")
        junit = row.get("junit")
        junit_digest = None
        if label == "focused-tests":
            junit_path = directory / "focused-tests.junit.xml"
            expected_junit = {
                "path": junit_path.name,
                "bytes": junit_path.stat().st_size,
                "sha256": digest(junit_path),
            }
            if junit != expected_junit:
                raise ValueError("focused review evidence lacks exact JUnit")
            junit_digest = expected_junit["sha256"]
        elif junit is not None:
            raise ValueError(f"unexpected JUnit on review command: {label}")
        receipts[label] = {
            "arguments": arguments,
            "commandReceiptSha256": digest(command_path),
            "logSha256": digest(log_path),
            "junitSha256": junit_digest,
        }
    return receipts, object_digest(
        receipts,
        b"hepta.channel-matrix-review-command-set.v1",
    )


def build(
    root_value: Path,
    directory_value: Path,
    registry_value: Path = REGISTRY_PATH,
) -> dict[str, Any]:
    root = root_value.resolve(strict=True)
    directory = directory_value.resolve(strict=True)
    if directory.is_relative_to(root):
        raise ValueError("review receipts must remain outside the checkout")
    source = read_object(directory / "source.json")
    lane = source.get("lane")
    if lane not in ("source-head", "base-merge"):
        raise ValueError("unsupported review-receipt lane")
    source_sha = exact_commit(root, source.get("sourceSha"), "source SHA")
    base_sha = exact_commit(root, source.get("baseSha"), "base SHA")
    tested_sha = exact_commit(root, source.get("testedSha"), "tested SHA")
    tested_tree = source.get("testedTree")
    if not isinstance(tested_tree, str) or not SHA1.fullmatch(tested_tree):
        raise ValueError("tested tree is not exact lowercase 40-hex")
    if git(root, "rev-parse", "HEAD").stdout.decode().strip() != tested_sha:
        raise ValueError("review checkout differs from tested SHA")
    if git(root, "rev-parse", "HEAD^{tree}").stdout.decode().strip() != tested_tree:
        raise ValueError("review checkout tree differs from source receipt")
    if lane == "source-head" and tested_sha != source_sha:
        raise ValueError("source-head review receipt tests another commit")
    if lane == "base-merge":
        parents = git(root, "rev-list", "--parents", "-n", "1", tested_sha).stdout.decode().split()[1:]
        if parents != [base_sha, source_sha]:
            raise ValueError("base-merge review receipt has wrong parents")

    provenance = read_object(directory / "source-provenance.json")
    execution = provenance.get("execution")
    if (
        provenance.get("schema") != "hepta.channel-matrix-source-provenance.v1"
        or provenance.get("valid") is not True
        or provenance.get("checkoutSha") != tested_sha
        or provenance.get("checkoutTree") != tested_tree
        or not isinstance(execution, dict)
        or not isinstance(execution.get("workflowRunId"), str)
        or not execution["workflowRunId"]
        or not isinstance(execution.get("attemptId"), str)
        or not execution["attemptId"]
    ):
        raise ValueError("review receipt lacks exact execution provenance")

    commands, command_set_sha256 = validate_command_receipts(directory, source)
    slices, registry_sha256 = load_registry(registry_value.resolve(strict=True))
    output_slices = []
    for item in slices:
        pathspecs = item["paths"]
        commits = [
            value
            for value in git(
                root,
                "log",
                "--reverse",
                "--format=%H",
                f"{base_sha}..{source_sha}",
                "--",
                *pathspecs,
            )
            .stdout.decode()
            .splitlines()
            if value
        ]
        changed_paths = split_z(
            git(
                root,
                "diff",
                "--name-only",
                "-z",
                base_sha,
                source_sha,
                "--",
                *pathspecs,
            ).stdout
        )
        if (
            not commits
            or not changed_paths
            or any(not SHA1.fullmatch(commit) for commit in commits)
            or changed_paths != sorted(set(changed_paths))
        ):
            raise ValueError(f"review slice has no exact source delta: {item['id']}")
        policy = {
            "id": item["id"],
            "owner": item["owner"],
            "deputy": item["deputy"],
            "paths": pathspecs,
            "invariants": item["invariants"],
            "commands": item["commands"],
        }
        output_slices.append(
            {
                **policy,
                "firstCommit": commits[0],
                "lastCommit": commits[-1],
                "commitCount": len(commits),
                "commits": commits,
                "changedPathCount": len(changed_paths),
                "changedPaths": changed_paths,
                "sourceRangeSha256": object_digest(
                    {"base": base_sha, "source": source_sha, "commits": commits, "paths": changed_paths},
                    b"hepta.channel-matrix-review-range.v1",
                ),
                "invariantPolicySha256": object_digest(
                    policy,
                    b"hepta.channel-matrix-review-invariants.v1",
                ),
                "commandEvidenceSha256": command_set_sha256,
                "sourceBound": True,
                "invariantPolicyBound": True,
                "commandEvidenceBound": True,
            }
        )
    return {
        "schema": RESULT_SCHEMA,
        "module": "channel.matrix",
        "lane": lane,
        "sourceSha": source_sha,
        "baseSha": base_sha,
        "testedSha": tested_sha,
        "testedTree": tested_tree,
        "workflowRunId": execution["workflowRunId"],
        "attemptId": execution["attemptId"],
        "registrySha256": registry_sha256,
        "commandSetSha256": command_set_sha256,
        "commandEvidence": commands,
        "slices": output_slices,
        "allSlicesSourceBound": True,
        "allSlicesInvariantPolicyBound": True,
        "allSlicesCommandEvidenceBound": True,
        "authorityGranted": False,
        "activation": False,
        "promotion": False,
        "release": False,
    }


def write_exclusive(path_value: Path, row: dict[str, Any]) -> None:
    path = path_value.absolute()
    parent = path.parent.resolve(strict=True)
    if path_value.is_symlink() or parent.is_relative_to(ROOT.resolve()) or path.exists():
        raise ValueError("review receipt must be a new file outside the checkout")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(row, stream, indent=2, sort_keys=True)
        stream.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    args = parser.parse_args()
    try:
        write_exclusive(
            args.output,
            build(args.root, args.directory, args.registry),
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"FAIL_CHANNEL_MATRIX_REVIEW_SLICES: {exc}\n")
    print("PASS_CHANNEL_MATRIX_REVIEW_SLICES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
