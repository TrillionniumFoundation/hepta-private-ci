#!/usr/bin/env python3
"""Inventory and safely retire merged refs; never merge unreviewed source."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
REMOTE_URL = f"https://github.com/{REPOSITORY}.git"
SCHEMA = "hepta.branch-retirement.v3"
PROTECTION_SCHEMA = "hepta.branch-protection.v2"
DEFAULT_PROTECTION = Path(__file__).with_name("protected-branches.json")


class RefSafetyError(RuntimeError):
    """The requested ref operation cannot be proved safe."""


def git(
    root: Path,
    *args: str,
    check: bool = True,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "--no-replace-objects", "-C", str(root), *args],
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="surrogateescape",
        timeout=300,
    )
    if check and result.returncode:
        raise RefSafetyError(f"git {args[0]} failed: {result.stderr[-4000:]}")
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ancestor(root: Path, older: str, newer: str) -> bool:
    result = git(root, "merge-base", "--is-ancestor", older, newer, check=False)
    if result.returncode not in (0, 1):
        raise RefSafetyError("Cannot determine commit ancestry")
    return result.returncode == 0


def remote_heads(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in git(root, "ls-remote", "--heads", "origin").stdout.splitlines():
        sha, ref = line.split("\t", 1)
        if not ref.startswith("refs/heads/") or not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise RefSafetyError("Unexpected remote ref encoding")
        name = ref.removeprefix("refs/heads/")
        if name in result:
            raise RefSafetyError("Duplicate remote branch in inventory")
        result[name] = sha
    if "main" not in result:
        raise RefSafetyError("Missing main")
    return result


def remote_default(root: Path) -> str:
    for line in git(
        root, "ls-remote", "--symref", "origin", "HEAD"
    ).stdout.splitlines():
        if line.startswith("ref: refs/heads/") and line.endswith("\tHEAD"):
            return line.removeprefix("ref: refs/heads/").removesuffix("\tHEAD")
    raise RefSafetyError("Cannot identify the live remote default branch")


def fetch_heads(root: Path) -> None:
    git(root, "fetch", "--no-tags", "origin", "+refs/heads/*:refs/remotes/origin/*")


def protected_branches(
    root: Path,
    heads: dict[str, str],
    manifest: dict[str, Any],
) -> dict[str, list[str]]:
    """Protect historical names, exact pins and every descendant of those pins."""
    if (
        manifest.get("schema") != PROTECTION_SCHEMA
        or manifest.get("repository") != REPOSITORY
    ):
        raise RefSafetyError("Wrong protection manifest schema or repository")
    seeds = set()
    for key in ("hiaRootCommits", "historicalProtectedCommits"):
        records = manifest.get(key)
        if not isinstance(records, list) or any(
            not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha)
            for sha in records
        ):
            raise RefSafetyError("Invalid protected ancestry pins")
        seeds.update(records)
    for key in ("protectedHeads", "protectedBaseHeads"):
        records = manifest.get(key)
        if not isinstance(records, dict):
            raise RefSafetyError("Missing protected branch manifest")
        for name, sha in records.items():
            if (
                not isinstance(name, str)
                or git(
                    root,
                    "check-ref-format",
                    f"refs/heads/{name}",
                    check=False,
                ).returncode
                or not isinstance(sha, str)
                or not re.fullmatch(r"[0-9a-f]{40}", sha)
            ):
                raise RefSafetyError("Invalid protected branch identity")
        seeds.update(records.values())

    named = {}
    for name, sha in heads.items():
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise RefSafetyError("Invalid live protected ancestry input")
        reasons = []
        if "hia" in name.lower():
            reasons.append("hia_branch_name")
        if name in manifest["protectedHeads"]:
            reasons.append("explicit_protected_branch")
        if name in manifest["protectedBaseHeads"]:
            reasons.append("protected_pr_base")
        if reasons:
            named[name] = reasons
            seeds.add(sha)

    if git(root, "rev-parse", "--is-shallow-repository").stdout.strip() != "false":
        raise RefSafetyError("Protected ancestry requires complete, non-shallow history")
    grafts = Path(git(root, "rev-parse", "--git-path", "info/grafts").stdout.strip())
    if not grafts.is_absolute():
        grafts = root / grafts
    if grafts.exists() and grafts.read_text().strip():
        raise RefSafetyError("Protected ancestry refuses grafted history")

    # One complete graph avoids a subprocess for each branch/pin pair.
    ordered_seeds = sorted(seeds)
    seed_bits = {sha: 1 << index for index, sha in enumerate(ordered_seeds)}
    revisions = seeds | set(heads.values())
    graph = git(
        root,
        "rev-list",
        "--parents",
        "--topo-order",
        "--reverse",
        "--stdin",
        input_text="\n".join(sorted(revisions)) + "\n",
    )
    masks = {}
    for row in graph.stdout.splitlines():
        parts = row.split()
        if not parts or any(not re.fullmatch(r"[0-9a-f]{40}", sha) for sha in parts):
            raise RefSafetyError("Invalid commit parent graph")
        sha, *parents = parts
        if sha in masks:
            raise RefSafetyError("Duplicate commit in parent graph")
        mask = seed_bits.get(sha, 0)
        for parent in parents:
            if parent not in masks:
                raise RefSafetyError("Missing or unordered commit parent")
            mask |= masks[parent]
        masks[sha] = mask
    if revisions - masks.keys():
        raise RefSafetyError("Protected pin or live head is missing from history")

    protected = {}
    for name, sha in heads.items():
        reasons = named.get(name, [])
        if not reasons:
            reasons = [
                f"hia_ancestor:{seed}"
                for index, seed in enumerate(ordered_seeds)
                if masks[sha] & (1 << index)
            ]
        if reasons:
            protected[name] = reasons
    return protected


def freeze_protection(
    heads: dict[str, str],
    protection: dict[str, Any],
    protected: dict[str, list[str]],
) -> dict[str, Any]:
    """Retain previous pins before advancing observed protected names."""
    frozen_protection = {
        **protection,
        "protectedHeads": dict(protection["protectedHeads"]),
        "protectedBaseHeads": dict(protection["protectedBaseHeads"]),
        "historicalProtectedCommits": sorted(
            set(protection["historicalProtectedCommits"])
            | set(protection["hiaRootCommits"])
            | set(protection["protectedHeads"].values())
            | set(protection["protectedBaseHeads"].values())
            | {heads[name] for name in protected if name != "main"}
        ),
    }
    for name in protected:
        if name == "main":
            continue
        key = (
            "protectedBaseHeads"
            if name in frozen_protection["protectedBaseHeads"]
            else "protectedHeads"
        )
        frozen_protection[key][name] = heads[name]
    return frozen_protection


def plan_retirement(
    root: Path, output: Path, protection: dict[str, Any]
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    fetch_heads(root)
    heads = remote_heads(root)
    default = remote_default(root)
    protected = protected_branches(root, heads, protection)
    frozen_protection = freeze_protection(heads, protection, protected)
    rows = []
    for name, sha in sorted(heads.items()):
        local_ref = f"refs/remotes/origin/{name}"
        if git(root, "rev-parse", local_ref).stdout.strip() != sha:
            raise RefSafetyError("Remote changed during inventory; create a new plan")
        git(root, "cat-file", "-e", f"{sha}^{{commit}}")
        included = ancestor(root, sha, heads["main"])
        row: dict[str, Any] = {
            "branch": name,
            "sha": sha,
            "tree": git(root, "rev-parse", f"{sha}^{{tree}}").stdout.strip(),
            "ancestorOfMain": included,
            "protectionReasons": protected.get(name, []),
            "disposition": "keep_main"
            if name == "main"
            else (
                "keep_default"
                if name == default
                else (
                    "keep_protected"
                    if name in protected
                    else ("eligible_merged" if included else "keep_unmerged")
                )
            ),
        }
        if not included:
            bases = git(root, "merge-base", "--all", heads["main"], sha, check=False)
            if bases.returncode not in (0, 1):
                raise RefSafetyError("Cannot compute merge bases")
            row["mergeBases"] = bases.stdout.splitlines()
            if len(row["mergeBases"]) == 1:
                row["changedPaths"] = (
                    git(
                        root,
                        "diff",
                        "--name-only",
                        "-z",
                        row["mergeBases"][0],
                        sha,
                    )
                    .stdout.rstrip("\0")
                    .split("\0")
                )
                preview = git(
                    root, "merge-tree", "--write-tree", heads["main"], sha, check=False
                )
                if preview.returncode not in (0, 1):
                    raise RefSafetyError("Cannot compute merge preview")
                row["mergePreviewClean"] = preview.returncode == 0
                row["mergePreview"] = preview.stdout
        rows.append(row)
    if remote_heads(root) != heads or remote_default(root) != default:
        raise RefSafetyError("Remote changed before backup; no cleanup authorized")
    bundle = output / "all-branches.bundle"
    git(root, "bundle", "create", str(bundle.resolve()), "--all")
    git(root, "bundle", "verify", str(bundle.resolve()))
    bundled = {}
    for line in git(
        root, "bundle", "list-heads", str(bundle.resolve())
    ).stdout.splitlines():
        sha, ref = line.split(" ", 1)
        bundled[ref] = sha
    for name, sha in heads.items():
        if bundled.get(f"refs/remotes/origin/{name}") != sha:
            raise RefSafetyError("Backup does not contain every frozen branch")
    plan = {
        "schema": SCHEMA,
        "repository": REPOSITORY,
        "remoteUrl": git(root, "remote", "get-url", "origin").stdout.strip(),
        "main": heads["main"],
        "defaultBranch": default,
        "branches": rows,
        "protectionManifest": frozen_protection,
        "bundleSha256": sha256(bundle),
        "backupVerified": True,
        "allHeadsRetainedByMain": all(row["ancestorOfMain"] for row in rows),
        "allUnprotectedHeadsRetainedByMain": all(
            row["ancestorOfMain"] for row in rows if not row["protectionReasons"]
        ),
        "sourceChangesMade": False,
        "branchesDeleted": [],
    }
    (output / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    (output / "SHA256SUMS").write_text(
        f"{sha256(bundle)}  all-branches.bundle\n{sha256(output / 'plan.json')}  plan.json\n"
    )
    return plan


def apply_retirement(
    root: Path, output: Path, expected_plan_sha256: str
) -> dict[str, Any]:
    path = output / "plan.json"
    if sha256(path) != expected_plan_sha256:
        raise RefSafetyError("Plan digest mismatch")
    attempt_path = output / "attempt.json"
    if attempt_path.exists():
        raise RefSafetyError(
            "Plan already attempted; reconcile its journal and create a fresh plan"
        )
    plan = json.loads(path.read_text())
    bundle = output / "all-branches.bundle"
    if plan.get("schema") != SCHEMA or plan.get("repository") != REPOSITORY:
        raise RefSafetyError("Wrong plan schema or repository")
    if not plan.get("backupVerified") or sha256(bundle) != plan["bundleSha256"]:
        raise RefSafetyError("Backup missing or changed")
    if git(root, "remote", "get-url", "origin").stdout.strip() != plan["remoteUrl"]:
        raise RefSafetyError("Remote changed after planning")
    git(root, "bundle", "verify", str(bundle.resolve()))
    fetch_heads(root)
    current = remote_heads(root)
    default = remote_default(root)
    protection = plan.get("protectionManifest")
    if not isinstance(protection, dict):
        raise RefSafetyError("Frozen protection manifest missing")
    protected = protected_branches(root, current, protection)
    observed_protection = freeze_protection(current, protection, protected)
    if not ancestor(root, plan["main"], current["main"]):
        raise RefSafetyError("Main history was replaced; abort all deletions")
    deletions = []
    skipped = []
    for row in plan["branches"]:
        name, sha = row["branch"], row["sha"]
        if name in ("main", default):
            skipped.append({"branch": name, "reason": "main_or_live_default"})
        elif name in protected:
            skipped.append({"branch": name, "reason": "protected_branch"})
        elif row["disposition"] != "eligible_merged":
            skipped.append({"branch": name, "reason": "not_approved_in_frozen_plan"})
        elif current.get(name) != sha:
            skipped.append({"branch": name, "reason": "ref_changed_or_absent"})
        elif not ancestor(root, sha, current["main"]):
            raise RefSafetyError("Candidate no longer retained by main")
        else:
            deletions.append((name, sha))
    receipt: dict[str, Any] = {
        "schema": "hepta.branch-retirement-receipt.v3",
        "planSha256": expected_plan_sha256,
        "main": current["main"],
        "defaultBranch": default,
        "requestedDeletions": [name for name, _ in deletions],
        "skipped": skipped,
        "branchesDeleted": [],
        "sourceChangesMade": False,
        "singleMainRefVerified": False,
        "protectedBranches": protected,
        "protectionManifest": observed_protection,
        "attemptJournal": attempt_path.name,
    }
    attempt = {
        "schema": "hepta.branch-retirement-attempt.v1",
        "planSha256": expected_plan_sha256,
        "main": current["main"],
        "defaultBranch": default,
        "protectionManifest": observed_protection,
        "requestedDeletions": [
            {"branch": name, "sha": sha} for name, sha in deletions
        ],
    }
    try:
        with attempt_path.open("x", encoding="utf-8") as stream:
            json.dump(attempt, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == "posix":
            directory_fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except FileExistsError as error:
        raise RefSafetyError("Another application attempt already owns this plan") from error
    if deletions:
        args = ["push", "--atomic", "--porcelain"]
        args += [
            f"--force-with-lease=refs/heads/{name}:{sha}" for name, sha in deletions
        ]
        args += ["origin"] + [f":refs/heads/{name}" for name, _ in deletions]
        result = git(root, *args, check=False)
        receipt["pushExitCode"] = result.returncode
        receipt["pushOutput"] = result.stdout + result.stderr
        after = remote_heads(root)
        receipt["branchesDeleted"] = [
            name for name, _ in deletions if name not in after
        ]
        if result.returncode:
            receipt["error"] = (
                "Atomic deletion rejected; no permissions or protection bypass attempted"
            )
    else:
        after = current
    receipt["remainingHeads"] = after
    receipt["singleMainRefVerified"] = (
        list(after) == ["main"] and remote_default(root) == "main"
    )
    # Unknown/newly moved refs remain unclassified, so they cannot prove completion.
    protected_names = set(protection["protectedHeads"]) | set(
        protection["protectedBaseHeads"]
    )
    protected_names.update(
        name for name in protected if after.get(name) == current.get(name)
    )
    receipt["remainingUnprotectedHeads"] = {
        name: sha
        for name, sha in after.items()
        if name == "main" or name not in protected_names
    }
    receipt["singleRustMainRefVerified"] = (
        list(receipt["remainingUnprotectedHeads"]) == ["main"]
        and remote_default(root) == "main"
    )
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    if receipt.get("error"):
        raise RefSafetyError(receipt["error"])
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["plan", "apply"])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument(
        "--protected-manifest",
        type=Path,
        default=DEFAULT_PROTECTION,
        help="Planning policy; apply always uses the digest-bound frozen policy",
    )
    args = parser.parse_args()
    if git(args.root, "remote", "get-url", "origin").stdout.strip() not in (
        REMOTE_URL,
        REMOTE_URL.removesuffix(".git"),
    ):
        raise RefSafetyError("CLI is restricted to the user-selected repository")
    if args.action == "plan":
        result = plan_retirement(
            args.root, args.output, json.loads(args.protected_manifest.read_text())
        )
        print(json.dumps({"branches": len(result["branches"]), "main": result["main"]}))
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
                stream.write(f"plan_sha256={sha256(args.output / 'plan.json')}\n")
    else:
        if not args.expected_plan_sha256:
            raise RefSafetyError("An independently retained plan digest is required")
        result = apply_retirement(args.root, args.output, args.expected_plan_sha256)
        print(json.dumps(result))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RefSafetyError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"Consolidation stopped: {error}", file=sys.stderr)
        raise SystemExit(1)
