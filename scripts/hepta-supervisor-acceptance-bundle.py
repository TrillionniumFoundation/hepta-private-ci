#!/usr/bin/env python3
"""Freeze exact Supervisor artifacts and host receipts for external review.

This tool prepares a digest-bound review packet. It deliberately cannot mint
operator acceptance, deployment qualification, promotion, merge, or release
authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")
REQUIRED_LANES = {
    "linux-source-head": ("linux", 256, "source"),
    "linux-merge-candidate": ("linux", 8, "merge"),
    "darwin-source-head": ("darwin", 64, "source"),
    "darwin-merge-candidate": ("darwin", 8, "merge"),
}
REQUIRED_ARTIFACTS = {
    "hepta-supervisord",
    "hepta-supervisor-release-controller",
    "hepta-authority-signer",
}
PROTOCOL_PATHS = (
    "codex-rs/hepta-supervisor/src/daemon_protocol.rs",
    "codex-rs/hepta-supervisor/src/signed_authority.rs",
    "codex-rs/hepta-supervisor/src/release_controller.rs",
)


def fail(message: str) -> None:
    raise ValueError(message)


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def git(*arguments: str) -> str:
    return subprocess.check_output(
        ["git", *arguments], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
    ).strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_named_path(values: list[str], label: str) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    for value in values:
        name, separator, raw_path = value.partition("=")
        require(separator == "=" and name and raw_path, f"{label} must use name=path")
        require(name not in parsed, f"duplicate {label} name: {name}")
        parsed[name] = Path(raw_path).resolve()
    return parsed


def read_object(path: Path, label: str) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"{label} must be a regular file")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"{label} must be a JSON object")
    return value


def validate_qualified_artifacts(
    value: dict[str, Any],
    *,
    label: str,
    expected_commit: str,
    expected_tree: str,
    expected_platform: str,
) -> dict[str, dict[str, Any]]:
    require(
        value.get("schema") == "hepta.runtime-supervisor.qualified-artifacts.v1",
        f"{label} qualified artifact schema",
    )
    require(value.get("schema_version") == 1, f"{label} qualified artifact version")
    require(value.get("source_commit") == expected_commit, f"{label} artifact commit mismatch")
    require(value.get("source_tree") == expected_tree, f"{label} artifact tree mismatch")
    require(value.get("host_platform") == expected_platform, f"{label} artifact platform mismatch")
    require(value.get("deployment_qualified") is False, f"{label} artifacts self-qualified deployment")
    require(value.get("independent_acceptance") is False, f"{label} artifacts self-asserted acceptance")
    raw_artifacts = value.get("artifacts")
    require(isinstance(raw_artifacts, list), f"{label} artifact list missing")
    artifacts: dict[str, dict[str, Any]] = {}
    for item in raw_artifacts:
        require(isinstance(item, dict), f"{label} artifact entry must be an object")
        name = item.get("name")
        digest = item.get("sha256")
        size = item.get("size_bytes")
        relative_path = item.get("relative_path")
        require(isinstance(name, str) and name not in artifacts, f"{label} duplicate artifact")
        require(bool(HEX64.fullmatch(digest or "")), f"{label} invalid artifact digest: {name}")
        require(isinstance(size, int) and size > 0, f"{label} empty artifact: {name}")
        require(
            relative_path == f"qualified-artifacts/{name}",
            f"{label} artifact path mismatch: {name}",
        )
        artifacts[name] = item
    require(set(artifacts) == REQUIRED_ARTIFACTS, f"{label} exact three qualified artifacts required")
    return artifacts


def validate_lane(
    label: str,
    root: Path,
    *,
    source_commit: str,
    source_tree: str,
    merge_commit: str,
    merge_tree: str,
    base_commit: str,
) -> dict[str, Any]:
    require(root.is_dir() and not root.is_symlink(), f"{label} lane root is not a directory")
    result_path = root / "result.json"
    policy_path = root / "physical-host-policy.json"
    physical_path = root / "physical-host.json"
    artifacts_path = root / "qualified-artifacts.json"
    result = read_object(result_path, f"{label} result")
    policy = read_object(policy_path, f"{label} policy")
    physical = read_object(physical_path, f"{label} physical host")
    qualified = read_object(artifacts_path, f"{label} qualified artifacts")
    expected_platform, minimum_instances, identity = REQUIRED_LANES[label]
    expected_commit = source_commit if identity == "source" else merge_commit
    expected_tree = source_tree if identity == "source" else merge_tree

    qualified_by_name = validate_qualified_artifacts(
        qualified,
        label=label,
        expected_commit=expected_commit,
        expected_tree=expected_tree,
        expected_platform=expected_platform,
    )

    require(result.get("schema_version") == 1, f"{label} result schema")
    require(result.get("status") == "passed", f"{label} result did not pass")
    require(result.get("source_commit") == expected_commit, f"{label} commit mismatch")
    require(result.get("source_tree") == expected_tree, f"{label} tree mismatch")
    require(result.get("source_still_clean") is True, f"{label} source was not clean")
    require(result.get("host_platform") == expected_platform, f"{label} platform mismatch")
    require(result.get("qualified_artifacts") == qualified, f"{label} result/artifact manifest mismatch")
    instances = result.get("host_instances")
    require(
        isinstance(instances, int) and instances >= minimum_instances,
        f"{label} instance count is below {minimum_instances}",
    )
    require(result.get("deployment_qualified") is False, f"{label} self-qualified deployment")
    require(result.get("independent_acceptance") is False, f"{label} self-asserted acceptance")
    checks = result.get("checks")
    require(isinstance(checks, list) and checks, f"{label} has no command checks")
    for item in checks:
        require(isinstance(item, dict), f"{label} command check must be an object")
        require(item.get("status") == "passed", f"{label} command did not pass: {item.get('name')}")
        require(item.get("exit_code") == 0, f"{label} command exit was not zero")
        require(not item.get("deadline_exceeded", False), f"{label} command exceeded deadline")
    if identity == "merge":
        require(
            result.get("parents") == [base_commit, source_commit],
            f"{label} merge parents are not exact base/source",
        )

    require(policy.get("schema_version") == 1, f"{label} policy schema")
    require(policy.get("status") == "passed", f"{label} policy did not pass")
    require(policy.get("source_commit") == expected_commit, f"{label} policy commit mismatch")
    require(policy.get("platform") == expected_platform, f"{label} policy platform mismatch")
    require(policy.get("instances") == instances, f"{label} policy instance mismatch")
    require(policy.get("deployment_qualified") is False, f"{label} policy self-qualified deployment")
    require(policy.get("independent_acceptance") is False, f"{label} policy self-asserted acceptance")

    require(physical.get("schema_version") == 1, f"{label} physical schema")
    require(physical.get("status") == "passed", f"{label} physical host did not pass")
    require(physical.get("source_commit") == expected_commit, f"{label} physical commit mismatch")
    require(physical.get("instances") == instances, f"{label} physical instance mismatch")
    require(physical.get("deployment_qualified") is False, f"{label} physical self-qualified deployment")
    require(physical.get("independent_acceptance") is False, f"{label} physical self-asserted acceptance")
    binary_digest = physical.get("supervisord_sha256")
    require(
        binary_digest == qualified_by_name["hepta-supervisord"]["sha256"],
        f"{label} physical host did not execute the frozen supervisord",
    )

    return {
        "label": label,
        "platform": expected_platform,
        "identity": identity,
        "instances": instances,
        "source_commit": expected_commit,
        "source_tree": expected_tree,
        "result_sha256": sha256_file(result_path),
        "policy_sha256": sha256_file(policy_path),
        "physical_host_sha256": sha256_file(physical_path),
        "qualified_artifacts_sha256": sha256_file(artifacts_path),
        "qualified_artifacts": qualified_by_name,
        "supervisord_sha256": binary_digest,
        "unmeasured_faults": policy.get("unmeasured_faults"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--merge-commit", required=True)
    parser.add_argument("--merge-tree", required=True)
    parser.add_argument("--lane", action="append", default=[], metavar="NAME=DIR")
    parser.add_argument("--artifact", action="append", default=[], metavar="NAME=FILE")
    parser.add_argument("--release-lane", choices=tuple(REQUIRED_LANES), default="linux-source-head")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    for label, value in (
        ("source commit", args.source_commit),
        ("source tree", args.source_tree),
        ("base commit", args.base_commit),
        ("merge commit", args.merge_commit),
        ("merge tree", args.merge_tree),
    ):
        require(bool(HEX40.fullmatch(value)), f"{label} must be lowercase SHA-1")
    require(git("rev-parse", "HEAD") == args.source_commit, "checkout is not exact source commit")
    require(git("rev-parse", "HEAD^{tree}") == args.source_tree, "checkout tree mismatch")
    require(not git("status", "--porcelain"), "checkout is not clean")

    lanes = parse_named_path(args.lane, "lane")
    require(set(lanes) == set(REQUIRED_LANES), "exact four platform/lane receipts are required")
    artifacts = parse_named_path(args.artifact, "artifact")
    require(set(artifacts) == REQUIRED_ARTIFACTS, "exact three production artifacts are required")

    artifact_manifest: list[dict[str, Any]] = []
    for name in sorted(artifacts):
        path = artifacts[name]
        require(path.is_file() and not path.is_symlink(), f"artifact {name} is not a regular file")
        require(path.stat().st_size > 0, f"artifact {name} is empty")
        artifact_manifest.append(
            {
                "name": name,
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )

    lane_manifest = [
        validate_lane(
            label,
            lanes[label],
            source_commit=args.source_commit,
            source_tree=args.source_tree,
            merge_commit=args.merge_commit,
            merge_tree=args.merge_tree,
            base_commit=args.base_commit,
        )
        for label in sorted(lanes)
    ]
    release_lane = next(item for item in lane_manifest if item["label"] == args.release_lane)
    supplied_by_name = {item["name"]: item for item in artifact_manifest}
    expected_by_name = release_lane["qualified_artifacts"]
    for name in sorted(REQUIRED_ARTIFACTS):
        require(
            supplied_by_name[name]["sha256"] == expected_by_name[name]["sha256"]
            and supplied_by_name[name]["size_bytes"] == expected_by_name[name]["size_bytes"],
            f"frozen {name} does not match the selected qualified lane",
        )

    protocol_manifest = []
    for raw_path in PROTOCOL_PATHS:
        path = ROOT / raw_path
        require(path.is_file(), f"missing protocol source {raw_path}")
        protocol_manifest.append({"path": raw_path, "sha256": sha256_file(path)})

    manifest = {
        "schema": "hepta.runtime-supervisor.acceptance-bundle.v1",
        "schema_version": 1,
        "status": "prepared_for_external_review",
        "candidate": {
            "source_commit": args.source_commit,
            "source_tree": args.source_tree,
            "base_commit": args.base_commit,
            "merge_commit": args.merge_commit,
            "merge_tree": args.merge_tree,
        },
        "release_lane": args.release_lane,
        "artifacts": artifact_manifest,
        "protocol_sources": protocol_manifest,
        "qualification_lanes": lane_manifest,
        "authority": {
            "automatic_transition": False,
            "deployment_qualified": False,
            "independent_acceptance": False,
            "merge_authority": False,
            "promotion_authority": False,
            "release_authority": False,
        },
        "required_external_actions": [
            "independent threat-model review",
            "independent recovery drill on the frozen artifacts",
            "target deployment host qualification including hardware power loss",
            "externally signed operator acceptance",
            "separate release-authority decision",
        ],
    }
    encoded = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    output = args.out.resolve()
    require(not output.exists(), "output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(encoded)
    digest_path = output.with_suffix(output.suffix + ".sha256")
    digest_path.write_text(
        f"{hashlib.sha256(encoded).hexdigest()}  {output.name}\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"manifest": str(output), "sha256": hashlib.sha256(encoded).hexdigest()}
        )
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        print(f"supervisor acceptance bundle failed: {error}", file=sys.stderr)
        sys.exit(1)
