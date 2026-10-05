"""Merge-commit enforcement for exact-blob control.engineering changes.

A squash or rebase discards the reviewed feature-branch ancestry used by the
module's explicit source observation.  Pull-request qualification can announce the
required method, but only the exact post-merge main commit can prove it.  This gate
therefore rejects relevant one-parent main commits and emits a retained receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from .control_plane import EngineeringError
from .git_security import run_git

_SCHEMA = "hepta.control-engineering-merge-policy.v1"
_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_RELEVANT_PREFIXES = (
    "tools/hepta-engineering-control/",
    "docs/modules/control.engineering/",
    "qualification/module-execution-dossiers/detail/control.engineering.md",
)
_RELEVANT_FILES = frozenset(
    {
        ".github/workflows/blocking-ci.yml",
        ".github/workflows/hepta-consolidated-source.yml",
        ".github/workflows/control-engineering-required.yml",
        ".github/workflows/control-engineering-production-acceptance.yml",
        ".github/workflows/control-engineering-projection.yml",
        "scripts/hepta-implementation-maps.py",
        "scripts/hepta-lane-b-truth.py",
    }
)


def _sha(value: str, label: str) -> str:
    if not isinstance(value, str) or _SHA1.fullmatch(value) is None:
        raise ValueError(label)
    return value


def _git(root: Path, *args: str) -> str:
    return run_git(root, *args)


def _changed_paths(root: Path, base: str, head: str) -> tuple[str, ...]:
    output = _git(
        root,
        "diff",
        "--name-only",
        "--no-renames",
        base,
        head,
        "--",
    )
    return tuple(sorted(path for path in output.splitlines() if path))


def is_control_engineering_path(path: str) -> bool:
    return path in _RELEVANT_FILES or any(path.startswith(prefix) for prefix in _RELEVANT_PREFIXES)


def control_engineering_scope(root: str | Path, *, base_sha: str, head_sha: str) -> bool:
    root_path = Path(root).resolve()
    base = _sha(base_sha, "invalid_base_sha")
    head = _sha(head_sha, "invalid_head_sha")
    return any(is_control_engineering_path(path) for path in _changed_paths(root_path, base, head))


def _map_policy(root: Path) -> dict[str, object]:
    path = root / "docs/modules/control.engineering/IMPLEMENTATION_MAP.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ValueError("control_engineering_map_unavailable") from None
    if (
        not isinstance(value, dict)
        or value.get("module") != "control.engineering"
        or value.get("mappingSourceIdentityMode") != "exact_blob"
    ):
        raise ValueError("control_engineering_exact_blob_policy_missing")
    return value


def build_merge_policy_receipt(
    repository: str | Path,
    *,
    base_sha: str,
    head_sha: str,
    mode: str,
) -> dict[str, object]:
    root = Path(repository).resolve()
    base = _sha(base_sha, "invalid_base_sha")
    head = _sha(head_sha, "invalid_head_sha")
    if mode not in {"pull-request", "post-merge-main"}:
        raise ValueError("invalid_merge_policy_mode")
    if _git(root, "rev-parse", "HEAD") != head:
        raise ValueError("merge_policy_checkout_mismatch")
    try:
        _git(root, "merge-base", "--is-ancestor", base, head)
    except EngineeringError:
        raise ValueError("merge_policy_base_not_ancestor") from None
    changed = _changed_paths(root, base, head)
    relevant = tuple(path for path in changed if is_control_engineering_path(path))
    policy = _map_policy(root)
    parents = tuple(_git(root, "show", "-s", "--format=%P", head).split())
    if relevant and mode == "post-merge-main":
        if len(parents) < 2:
            raise ValueError("control_engineering_squash_or_rebase_rejected")
        if parents[0] != base:
            raise ValueError("control_engineering_main_first_parent_mismatch")

    observation = policy.get("observedAtHead")
    if not isinstance(observation, dict):
        raise ValueError("control_engineering_observation_missing")
    observation_commit = _sha(str(observation.get("commit", "")), "invalid_observation_commit")
    observation_tree = _sha(str(observation.get("tree", "")), "invalid_observation_tree")
    if _git(root, "rev-parse", f"{observation_commit}^{{tree}}") != observation_tree:
        raise ValueError("control_engineering_observation_tree")
    try:
        _git(root, "merge-base", "--is-ancestor", observation_commit, head)
    except EngineeringError:
        raise ValueError("control_engineering_observation_not_ancestral") from None
    value: dict[str, object] = {
        "schema": _SCHEMA,
        "mode": mode,
        "baseSha": base,
        "headSha": head,
        "headTree": _git(root, "rev-parse", f"{head}^{{tree}}"),
        "parents": list(parents),
        "relevant": bool(relevant),
        "relevantPaths": list(relevant),
        "requiredMergeMethod": "merge" if relevant else "not_applicable",
        "exactBlobObservationCommit": observation_commit,
        "exactBlobObservationTree": observation_tree,
        "postMergeMethodVerified": bool(relevant and mode == "post-merge-main"),
        "runtimeAuthority": False,
        "mergeAuthority": False,
        "releaseAuthority": False,
    }
    value["receiptDigest"] = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("scope", "verify-pr", "verify-main"))
    parser.add_argument("--repository", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "scope":
            required = control_engineering_scope(
                args.repository,
                base_sha=args.base_sha,
                head_sha=args.head_sha,
            )
            value: dict[str, object] = {
                "schema": _SCHEMA,
                "mode": "scope",
                "baseSha": args.base_sha,
                "headSha": args.head_sha,
                "required": required,
            }
            if args.github_output is not None:
                with args.github_output.open("a", encoding="utf-8") as handle:
                    handle.write(f"required={'true' if required else 'false'}\n")
        else:
            value = build_merge_policy_receipt(
                args.repository,
                base_sha=args.base_sha,
                head_sha=args.head_sha,
                mode=("pull-request" if args.command == "verify-pr" else "post-merge-main"),
            )
    except (OSError, ValueError, EngineeringError, subprocess.CalledProcessError) as error:
        print(json.dumps({"schema": _SCHEMA, "status": "rejected", "error": str(error)}))
        return 1
    rendered = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
