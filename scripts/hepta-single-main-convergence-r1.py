#!/usr/bin/env python3
"""Fail-closed all-Hepta convergence and single-main publication controller."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path.cwd()
REPO = os.environ.get("GITHUB_REPOSITORY", "TrillionniumFoundation/hepta-private-ci")
RUN_ID = os.environ.get("GITHUB_RUN_ID", "local")
RUN_ATTEMPT = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
BASE_BRANCH = os.environ.get(
    "HEPTA_BASE_BRANCH", "integration/hepta-all-gap-closure-20260910-r12"
)
DEFAULT_BRANCH = os.environ.get(
    "HEPTA_OLD_DEFAULT_BRANCH", "integration/vnext-main-20260811"
)
LANE_F_BRANCH = os.environ.get(
    "HEPTA_LANE_F_BRANCH", "codex/lane-f-gap-closure-20260910"
)
LANE_G_BRANCH = os.environ.get(
    "HEPTA_LANE_G_BRANCH", "codex/lane-g-real-full-closure-v2-20260910"
)
OUT_ROOT = Path(
    os.environ.get(
        "HEPTA_SINGLE_MAIN_OUT", "qualification/single-main-closure-r1"
    )
)
ARCHIVE_PREFIX = os.environ.get(
    "HEPTA_ARCHIVE_PREFIX", f"archive/final-branch-tip/20260910-r1-{RUN_ID}"
)
SHARDS = int(os.environ.get("HEPTA_PACKAGE_SHARDS", "8"))


class ConvergenceError(RuntimeError):
    pass


def command_text(command: Sequence[str]) -> str:
    return " ".join(subprocess.list2cmdline([part]) for part in command)


def run(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    capture: bool = False,
    timeout: int | None = None,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    print(f"+ {command_text(command)}", flush=True)
    completed = subprocess.run(
        list(command),
        cwd=str(cwd or ROOT),
        check=False,
        text=True,
        input=input_text,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        timeout=timeout,
        env=env,
    )
    if capture:
        if completed.stdout:
            print(completed.stdout, end="", flush=True)
        if completed.stderr:
            print(completed.stderr, end="", file=sys.stderr, flush=True)
    if check and completed.returncode != 0:
        raise ConvergenceError(
            f"command failed ({completed.returncode}): {command_text(command)}"
        )
    return completed


def git(*args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return run(("git", *args), **kwargs)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def set_output(name: str, value: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")
    print(f"OUTPUT {name}={value}", flush=True)


def remote_heads() -> dict[str, str]:
    result = git("ls-remote", "--heads", "origin", capture=True, timeout=600)
    heads: dict[str, str] = {}
    prefix = "refs/heads/"
    for raw in result.stdout.splitlines():
        if not raw.strip():
            continue
        sha, ref = raw.split("\t", 1)
        if not ref.startswith(prefix):
            raise ConvergenceError(f"unexpected remote head ref: {ref}")
        branch = ref[len(prefix) :]
        if branch in heads:
            raise ConvergenceError(f"duplicate remote branch: {branch}")
        heads[branch] = sha
    if not heads:
        raise ConvergenceError("remote branch snapshot is empty")
    return dict(sorted(heads.items()))


def gh_ids_for_status(status: str) -> list[str]:
    result = run(
        (
            "gh",
            "api",
            "--paginate",
            f"repos/{REPO}/actions/runs?status={status}&per_page=100",
            "--jq",
            ".workflow_runs[].id",
        ),
        capture=True,
        check=False,
        timeout=600,
    )
    if result.returncode != 0:
        raise ConvergenceError(f"cannot enumerate {status} workflow runs")
    return [line.strip() for line in result.stdout.splitlines() if line.strip().isdigit()]


def cancel_other_runs() -> int:
    cancelled = 0
    for status in ("queued", "in_progress"):
        for run_id in gh_ids_for_status(status):
            if run_id == RUN_ID:
                continue
            result = run(
                ("gh", "api", "-X", "POST", f"repos/{REPO}/actions/runs/{run_id}/cancel"),
                check=False,
                capture=True,
                timeout=120,
            )
            if result.returncode == 0:
                cancelled += 1
    return cancelled


def stable_snapshot() -> tuple[dict[str, str], int]:
    prior: dict[str, str] | None = None
    stable_intervals = 0
    cancelled_total = 0
    for attempt in range(18):
        cancelled_total += cancel_other_runs()
        current = remote_heads()
        if prior == current:
            stable_intervals += 1
        else:
            prior = current
            stable_intervals = 0
        print(
            f"snapshot attempt={attempt + 1} branches={len(current)} "
            f"stableIntervals={stable_intervals}",
            flush=True,
        )
        if stable_intervals >= 2:
            return current, cancelled_total
        time.sleep(10)
    raise ConvergenceError("remote branch heads did not reach three-sample stability")


def fetch_all() -> None:
    git(
        "fetch",
        "--prune",
        "origin",
        "+refs/heads/*:refs/remotes/origin/*",
        "+refs/tags/*:refs/tags/*",
        timeout=1800,
    )


def archive_heads(heads: dict[str, str], prefix: str) -> None:
    fetch_all()
    for branch, sha in heads.items():
        git("cat-file", "-e", f"{sha}^{{commit}}")
        tag = f"{prefix}/{branch}"
        result = git("check-ref-format", f"refs/tags/{tag}", check=False, capture=True)
        if result.returncode != 0:
            raise ConvergenceError(f"invalid archive tag for branch {branch}: {tag}")
        existing = git("rev-parse", "-q", "--verify", f"refs/tags/{tag}", check=False, capture=True)
        if existing.returncode == 0:
            if existing.stdout.strip() != sha:
                raise ConvergenceError(f"archive tag collision: {tag}")
            continue
        git("update-ref", f"refs/tags/{tag}", sha)
    git(
        "push",
        "origin",
        f"refs/tags/{prefix}/*:refs/tags/{prefix}/*",
        timeout=1800,
    )
    observed = git("ls-remote", "--tags", "origin", f"refs/tags/{prefix}/*", capture=True)
    remote = {
        line.split("\t", 1)[1].removeprefix("refs/tags/"): line.split("\t", 1)[0]
        for line in observed.stdout.splitlines()
        if line.strip() and not line.endswith("^{}")
    }
    expected = {f"{prefix}/{branch}": sha for branch, sha in heads.items()}
    if remote != expected:
        missing = sorted(set(expected) - set(remote))
        drifted = sorted(name for name in expected.keys() & remote.keys() if expected[name] != remote[name])
        raise ConvergenceError(
            f"archive tag verification failed: missing={missing[:10]} drifted={drifted[:10]}"
        )


def freeze(args: argparse.Namespace) -> int:
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    heads, cancelled = stable_snapshot()
    for required in ("main", DEFAULT_BRANCH, BASE_BRANCH, LANE_F_BRANCH, LANE_G_BRANCH):
        if required not in heads:
            raise ConvergenceError(f"required branch absent from stable snapshot: {required}")
    archive_heads(heads, ARCHIVE_PREFIX)
    lines = [f"{branch}\t{sha}" for branch, sha in heads.items()]
    tsv = "\n".join(lines) + "\n"
    (out / "branch-heads.tsv").write_text(tsv, encoding="utf-8")
    digest = sha256_bytes(tsv.encode("utf-8"))
    manifest = {
        "schema": "hepta.single-main.freeze.v1",
        "repository": REPO,
        "runId": RUN_ID,
        "runAttempt": RUN_ATTEMPT,
        "branchCount": len(heads),
        "branchHeadsSha256": digest,
        "archivePrefix": ARCHIVE_PREFIX,
        "cancelledRuns": cancelled,
        "baseBranch": BASE_BRANCH,
        "baseSha": heads[BASE_BRANCH],
        "oldDefaultBranch": DEFAULT_BRANCH,
        "oldDefaultSha": heads[DEFAULT_BRANCH],
        "oldMainSha": heads["main"],
        "laneFBranch": LANE_F_BRANCH,
        "laneFSha": heads[LANE_F_BRANCH],
        "laneGBranch": LANE_G_BRANCH,
        "laneGSha": heads[LANE_G_BRANCH],
        "heads": heads,
        "authorityGranted": False,
        "externalAuthorityGatesRetained": True,
    }
    write_json(out / "freeze.json", manifest)
    executor_source = Path(__file__).resolve()
    shutil.copy2(executor_source, out / "executor.py")
    mapping = {
        "branch_count": str(len(heads)),
        "snapshot_digest": digest,
        "archive_prefix": ARCHIVE_PREFIX,
        "base_sha": heads[BASE_BRANCH],
        "old_default_sha": heads[DEFAULT_BRANCH],
        "old_main_sha": heads["main"],
        "lane_f_sha": heads[LANE_F_BRANCH],
        "lane_g_sha": heads[LANE_G_BRANCH],
    }
    for key, value in mapping.items():
        set_output(key, value)
    return 0


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConvergenceError(f"cannot read freeze manifest {path}: {error}") from error
    if not isinstance(value, dict) or not isinstance(value.get("heads"), dict):
        raise ConvergenceError("invalid freeze manifest")
    return value


def verify_snapshot(manifest: dict[str, Any]) -> None:
    expected = manifest["heads"]
    current = remote_heads()
    changed = {
        branch: {"expected": sha, "observed": current.get(branch)}
        for branch, sha in expected.items()
        if current.get(branch) != sha
    }
    if changed:
        preview = dict(list(sorted(changed.items()))[:20])
        raise ConvergenceError(f"frozen branch snapshot drifted: {json.dumps(preview, sort_keys=True)}")


def commit_if_dirty(message: str) -> str:
    status = git("status", "--porcelain", capture=True)
    if status.stdout.strip():
        git("add", "-A")
        git("commit", "--signoff", "-m", message)
    return git("rev-parse", "HEAD", capture=True).stdout.strip()


def merge_lane_g(lane_g_sha: str) -> dict[str, Any]:
    if git("merge-base", "--is-ancestor", lane_g_sha, "HEAD", check=False).returncode == 0:
        return {"sourceSha": lane_g_sha, "alreadyAncestor": True, "changed": False}
    merge = git("merge", "--no-ff", "--no-commit", lane_g_sha, check=False, capture=True, timeout=1800)
    if merge.returncode != 0:
        conflicts = git("diff", "--name-only", "--diff-filter=U", capture=True, check=False).stdout.splitlines()
        git("merge", "--abort", check=False)
        raise ConvergenceError(
            "Lane G cannot be merged without semantic conflict resolution: "
            + ", ".join(conflicts[:50])
        )
    git("commit", "--signoff", "-m", "merge(lane-g): absorb latest engineering-control closure")
    return {"sourceSha": lane_g_sha, "alreadyAncestor": False, "changed": True}


def lane_f_recover_and_overlay(lane_f_sha: str) -> dict[str, Any]:
    worktree = Path(tempfile.mkdtemp(prefix="hepta-lane-f-"))
    recovery_receipt = Path(tempfile.mkstemp(prefix="lane-f-recovery-", suffix=".json")[1])
    repair_receipt = Path(tempfile.mkstemp(prefix="lane-f-repair-", suffix=".json")[1])
    try:
        git("worktree", "add", "--detach", str(worktree), lane_f_sha, timeout=1800)
        recovery_script = worktree / ".lane-f-recovery/recover_source.py"
        repair_script = worktree / ".lane-f-recovery/repair_source.py"
        if not recovery_script.is_file() or not repair_script.is_file():
            raise ConvergenceError("latest Lane F lacks pinned recovery/repair executors")
        run(
            (sys.executable, str(recovery_script), "--root", str(worktree), "--receipt", str(recovery_receipt)),
            cwd=worktree,
            timeout=600,
        )
        run((sys.executable, str(recovery_script), "--root", str(worktree), "--check"), cwd=worktree, timeout=600)
        run(
            (sys.executable, str(repair_script), "--root", str(worktree), "--receipt", str(repair_receipt)),
            cwd=worktree,
            timeout=600,
        )
        run((sys.executable, str(repair_script), "--root", str(worktree), "--check"), cwd=worktree, timeout=600)
        standalone = worktree / "qualification/lane-f-shadow/Cargo.toml"
        if not standalone.is_file():
            raise ConvergenceError("Lane F standalone qualification manifest is missing")
        run(
            ("cargo", "fmt", "--manifest-path", str(standalone), "--all"),
            cwd=worktree,
            timeout=2400,
        )
        run(
            ("cargo", "test", "--manifest-path", str(standalone)),
            cwd=worktree,
            timeout=7200,
            env={**os.environ, "CARGO_TARGET_DIR": str(worktree / ".target-lane-f")},
        )
        run(
            (
                "cargo",
                "clippy",
                "--manifest-path",
                str(standalone),
                "--all-targets",
                "--",
                "-D",
                "warnings",
            ),
            cwd=worktree,
            timeout=7200,
            env={**os.environ, "CARGO_TARGET_DIR": str(worktree / ".target-lane-f")},
        )
        run(
            ("cargo", "fmt", "--manifest-path", str(standalone), "--all", "--", "--check"),
            cwd=worktree,
            timeout=2400,
        )
        recovery = json.loads(recovery_receipt.read_text(encoding="utf-8"))
        repair = json.loads(repair_receipt.read_text(encoding="utf-8"))
        paths = [row["path"] for row in recovery["files"]]
        paths.append("qualification/lane-f-shadow/Cargo.toml")
        copied: list[dict[str, Any]] = []
        for relative in sorted(set(paths)):
            source = worktree / relative
            target = ROOT / relative
            if not source.is_file():
                raise ConvergenceError(f"Lane F overlay member is missing: {relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(
                {
                    "path": relative,
                    "sha256": sha256_bytes(target.read_bytes()),
                    "bytes": target.stat().st_size,
                }
            )
        return {
            "sourceSha": lane_f_sha,
            "recovery": recovery,
            "repair": repair,
            "copied": copied,
        }
    finally:
        git("worktree", "remove", "--force", str(worktree), check=False)
        shutil.rmtree(worktree, ignore_errors=True)
        recovery_receipt.unlink(missing_ok=True)
        repair_receipt.unlink(missing_ok=True)


TRANSIENT_DIRS = (
    ".lane-f-bootstrap",
    ".lane-f-min",
    ".lane-f-final",
    ".lane-f-recovery",
)
TRANSIENT_WORKFLOW_TOKENS = (
    "trigger-",
    "patch-",
    "materializer",
    "source-export",
    "diagnostic",
    "global-finalizer",
    "gap-closure-controller",
    "candidate-publisher",
    "fixed-point-controller",
    "repair-replay",
    "one-shot",
)


def remove_transient_carriers() -> list[str]:
    removed: list[str] = []
    for value in TRANSIENT_DIRS:
        path = ROOT / value
        if path.exists():
            shutil.rmtree(path)
            removed.append(value)
    probe = ROOT / "__tool_probe_do_not_create__"
    if probe.exists():
        probe.unlink()
        removed.append(probe.name)
    workflows = ROOT / ".github/workflows"
    if workflows.is_dir():
        for path in sorted(workflows.iterdir()):
            if not path.is_file():
                continue
            lowered = path.name.lower()
            if lowered.startswith("tmp-") or any(token in lowered for token in TRANSIENT_WORKFLOW_TOKENS):
                path.unlink()
                removed.append(path.relative_to(ROOT).as_posix())
    return removed


def generator_commands() -> list[tuple[str, ...]]:
    candidates = (
        ("scripts/hepta-readiness.py", "generate-status"),
        ("scripts/hepta-implementation-dossiers.py", "generate-status"),
        ("scripts/hepta-algorithm-docs.py", "generate-status"),
        ("scripts/hepta-cns.py", "generate-status"),
        ("scripts/hepta-docs.py", "generate-status"),
    )
    return [(sys.executable, path, subcommand) for path, subcommand in candidates if (ROOT / path).is_file()]


def normalize_fixed_point() -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    metadata = run(
        ("cargo", "metadata", "--manifest-path", "codex-rs/Cargo.toml", "--format-version", "1", "--locked", "--no-deps"),
        check=False,
        capture=True,
        timeout=1800,
    )
    if metadata.returncode != 0:
        lock = run(("cargo", "generate-lockfile", "--manifest-path", "codex-rs/Cargo.toml"), timeout=3600)
        receipts.append({"command": "cargo generate-lockfile", "returnCode": lock.returncode})
    prior: str | None = None
    for round_index in range(1, 5):
        for command in generator_commands():
            result = run(command, timeout=1200)
            receipts.append({"round": round_index, "command": list(command), "returnCode": result.returncode})
        fmt = run(("cargo", "fmt", "--manifest-path", "codex-rs/Cargo.toml", "--all"), timeout=2400)
        receipts.append({"round": round_index, "command": ["cargo", "fmt"], "returnCode": fmt.returncode})
        diff = git("diff", "--binary", capture=True).stdout
        digest = sha256_bytes(diff.encode("utf-8"))
        print(f"fixed-point round={round_index} diffSha256={digest}")
        if digest == prior:
            return receipts
        prior = digest
    raise ConvergenceError("generators and formatters did not reach a deterministic fixed point")


def canonical_packages() -> list[str]:
    result = run(
        ("cargo", "metadata", "--manifest-path", "codex-rs/Cargo.toml", "--format-version", "1", "--locked", "--no-deps"),
        capture=True,
        timeout=1800,
    )
    metadata = json.loads(result.stdout)
    packages = sorted(
        {
            package["name"]
            for package in metadata.get("packages", [])
            if isinstance(package, dict)
            and isinstance(package.get("name"), str)
            and package["name"].startswith("codex-hepta-")
        }
    )
    if len(packages) < 40:
        raise ConvergenceError(f"canonical Hepta package set is unexpectedly small: {len(packages)}")
    return packages


def shard_matrix(packages: list[str], shards: int) -> dict[str, Any]:
    if shards < 1:
        raise ConvergenceError("package shard count must be positive")
    rows = [[] for _ in range(shards)]
    for index, package in enumerate(packages):
        rows[index % shards].append(package)
    return {
        "include": [
            {
                "shard": index,
                "packages_json": json.dumps(row, separators=(",", ":")),
                "package_count": len(row),
            }
            for index, row in enumerate(rows)
            if row
        ]
    }


def commit_tree(tree: str, current: str, parents: list[str], message: str) -> str:
    command: list[str] = ["git", "commit-tree", tree, "-p", current]
    for parent in parents:
        command.extend(("-p", parent))
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Hepta single-main convergence controller",
        "GIT_AUTHOR_EMAIL": "hepta-single-main@users.noreply.github.com",
        "GIT_COMMITTER_NAME": "Hepta single-main convergence controller",
        "GIT_COMMITTER_EMAIL": "hepta-single-main@users.noreply.github.com",
        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
        "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
    }
    result = run(command, capture=True, env=env, input_text=message + "\n")
    sha = result.stdout.strip().splitlines()[-1]
    git("cat-file", "-e", f"{sha}^{{commit}}")
    return sha


def absorb_all_history(product_sha: str, manifest: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    tree = git("rev-parse", f"{product_sha}^{{tree}}", capture=True).stdout.strip()
    current = product_sha
    remaining: list[tuple[str, str]] = []
    seen: set[str] = set()
    for branch, sha in sorted(manifest["heads"].items()):
        if sha in seen:
            continue
        seen.add(sha)
        if git("merge-base", "--is-ancestor", sha, current, check=False).returncode == 0:
            continue
        remaining.append((branch, sha))
    receipts: list[dict[str, Any]] = []
    batch_size = 24
    for offset in range(0, len(remaining), batch_size):
        batch = remaining[offset : offset + batch_size]
        parents = [sha for _, sha in batch]
        lines = [
            "merge(history): absorb archived branch tips into single-main lineage",
            "",
            "This commit preserves the exact qualified product tree while making the",
            "following archived branch tips reachable from the final main history:",
            "",
            *[f"- {branch}: {sha}" for branch, sha in batch],
            "",
            "No production, release, external-owner, model/provider, operator or",
            "independent-review authority is granted by this history-only merge.",
        ]
        current = commit_tree(tree, current, parents, "\n".join(lines))
        receipts.append({"commit": current, "parents": [{"branch": b, "sha": s} for b, s in batch]})
    final_tree = git("rev-parse", f"{current}^{{tree}}", capture=True).stdout.strip()
    if final_tree != tree:
        raise ConvergenceError("history absorption changed the qualified product tree")
    missing: list[str] = []
    for branch, sha in manifest["heads"].items():
        if git("merge-base", "--is-ancestor", sha, current, check=False).returncode != 0:
            missing.append(branch)
    if missing:
        raise ConvergenceError(f"branch tips not reachable from final candidate: {missing[:20]}")
    return current, receipts


def prepare(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.manifest.resolve())
    verify_snapshot(manifest)
    fetch_all()
    git("config", "user.name", "Hepta single-main convergence controller")
    git("config", "user.email", "hepta-single-main@users.noreply.github.com")
    base_sha = str(manifest["baseSha"])
    lane_f_sha = str(manifest["laneFSha"])
    lane_g_sha = str(manifest["laneGSha"])
    git("checkout", "--detach", base_sha)
    git("reset", "--hard", base_sha)
    git("clean", "-fdx")
    git("switch", "-c", f"hepta-single-main-work-{RUN_ID}")
    lane_g = merge_lane_g(lane_g_sha)
    lane_f = lane_f_recover_and_overlay(lane_f_sha)
    removed = remove_transient_carriers()
    fixed_point = normalize_fixed_point()
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    prepare_receipt = {
        "schema": "hepta.single-main.prepare.v1",
        "runId": RUN_ID,
        "runAttempt": RUN_ATTEMPT,
        "frozenBranchCount": manifest["branchCount"],
        "frozenBranchHeadsSha256": manifest["branchHeadsSha256"],
        "archivePrefix": manifest["archivePrefix"],
        "baseBranch": manifest["baseBranch"],
        "baseSha": base_sha,
        "laneG": lane_g,
        "laneF": lane_f,
        "removedTransientCarriers": removed,
        "fixedPointReceipts": fixed_point,
        "repositoryQualificationPending": True,
        "packageQualificationPending": True,
        "authorityGranted": False,
        "externalAuthorityGatesRetained": True,
    }
    write_json(OUT_ROOT / "PREPARE.json", prepare_receipt)
    git("diff", "--check")
    product_sha = commit_if_dirty("feat(convergence): assemble single qualified Hepta product tree")
    clean = git("status", "--porcelain", capture=True)
    if clean.stdout.strip():
        raise ConvergenceError("product tree is dirty after prepare commit")
    packages = canonical_packages()
    final_sha, history_receipts = absorb_all_history(product_sha, manifest)
    final_tree = git("rev-parse", f"{final_sha}^{{tree}}", capture=True).stdout.strip()
    product_tree = git("rev-parse", f"{product_sha}^{{tree}}", capture=True).stdout.strip()
    if final_tree != product_tree:
        raise ConvergenceError("final history head does not preserve product tree")
    candidate_branch = f"integration/hepta-single-main-candidate-{RUN_ID}-r{RUN_ATTEMPT}"
    git("push", "origin", f"{final_sha}:refs/heads/{candidate_branch}", timeout=1800)
    qualification = {
        "schema": "hepta.single-main.candidate.v1",
        "candidateBranch": candidate_branch,
        "productSha": product_sha,
        "finalSha": final_sha,
        "treeSha": final_tree,
        "canonicalPackageCount": len(packages),
        "historyAbsorptionCommits": history_receipts,
        "allFrozenBranchTipsReachable": True,
        "authorityGranted": False,
        "externalAuthorityGatesRetained": True,
    }
    evidence_dir = args.evidence.resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    write_json(evidence_dir / "candidate.json", qualification)
    matrix = shard_matrix(packages, SHARDS)
    set_output("candidate_branch", candidate_branch)
    set_output("product_sha", product_sha)
    set_output("final_sha", final_sha)
    set_output("tree_sha", final_tree)
    set_output("package_count", str(len(packages)))
    set_output("packages_json", json.dumps(packages, separators=(",", ":")))
    set_output("matrix", json.dumps(matrix, separators=(",", ":")))
    return 0


def run_existing(command: Sequence[str], *, timeout: int = 1800) -> None:
    if len(command) >= 2 and command[0] == sys.executable:
        script = ROOT / command[1]
        if not script.is_file():
            print(f"SKIP absent script: {script}")
            return
    run(command, timeout=timeout)


def canonical_repository_commands() -> Iterable[tuple[str, ...]]:
    python = sys.executable
    commands = (
        (python, "scripts/hepta-readiness.py", "self-test"),
        (python, "scripts/hepta-readiness.py", "generate-status", "--check"),
        (python, "scripts/hepta-readiness.py", "verify"),
        (python, "scripts/hepta-implementation-dossiers.py", "self-test"),
        (python, "scripts/hepta-implementation-dossiers.py", "generate-status", "--check"),
        (python, "scripts/hepta-implementation-dossiers.py", "verify"),
        (python, "scripts/hepta-technical-closure.py", "self-test"),
        (python, "scripts/hepta-technical-closure.py", "verify"),
        (python, "qualification/module-execution-dossiers/implementation_contracts.py", "self-test"),
        (python, "qualification/module-execution-dossiers/implementation_contracts.py", "verify-repository"),
        (python, "scripts/hepta-module-docs.py", "self-test"),
        (python, "scripts/hepta-module-docs.py", "verify"),
        (python, "scripts/hepta-algorithm-docs.py", "self-test"),
        (python, "scripts/hepta-algorithm-docs.py", "verify-sources"),
        (python, "scripts/hepta-algorithm-docs.py", "generate-status", "--check"),
        (python, "scripts/hepta-algorithm-docs.py", "verify"),
        (python, "scripts/hepta-cns.py", "self-test"),
        (python, "scripts/hepta-cns.py", "generate-status", "--check"),
        (python, "scripts/hepta-cns.py", "verify"),
        (python, "scripts/hepta-hnmf.py", "self-test"),
        (python, "scripts/hepta-hnmf.py", "verify"),
        (python, "scripts/hepta-docs.py", "self-test"),
        (python, "scripts/hepta-docs.py", "verify"),
    )
    return commands


def lane_specific_repository_gates() -> None:
    for script in (
        "scripts/verify_lane_a_foundation.py",
        "scripts/hepta-lane-b-truth.py",
        "scripts/hepta-lane-c-closure.py",
        "scripts/hepta-lane-d-semantic-conformance.py",
        "scripts/hepta-lane-e-closure.py",
    ):
        if (ROOT / script).is_file():
            run((sys.executable, script), timeout=3600)
    tool_root = ROOT / "tools/hepta-engineering-control"
    if tool_root.is_dir():
        run(
            (sys.executable, "-m", "unittest", "discover", "-s", str(tool_root), "-p", "test_*.py"),
            timeout=3600,
        )
        for script in ("lane_g_validate.py", "lane_g_hardening_validate.py"):
            path = tool_root / script
            if path.is_file():
                run((sys.executable, str(path)), timeout=3600)
    for app in ("hepta-browser", "hepta-control-ui", "hepta-native"):
        tests = sorted((ROOT / "apps" / app / "test").glob("*.test.js"))
        if tests:
            run(("node", "--test", *[str(path) for path in tests]), timeout=3600)


def standalone_lane_f_gate() -> None:
    manifest = ROOT / "qualification/lane-f-shadow/Cargo.toml"
    if not manifest.is_file():
        raise ConvergenceError("Lane F standalone qualification manifest absent from candidate")
    lock = manifest.parent / "Cargo.lock"
    tracked_lock = git("ls-files", "--error-unmatch", str(lock.relative_to(ROOT)), check=False).returncode == 0
    target = Path(tempfile.mkdtemp(prefix="lane-f-gate-target-"))
    try:
        run(("cargo", "fmt", "--manifest-path", str(manifest), "--all", "--", "--check"), timeout=2400)
        env = {**os.environ, "CARGO_TARGET_DIR": str(target)}
        run(("cargo", "test", "--manifest-path", str(manifest)), timeout=7200, env=env)
        run(
            ("cargo", "clippy", "--manifest-path", str(manifest), "--all-targets", "--", "-D", "warnings"),
            timeout=7200,
            env=env,
        )
    finally:
        shutil.rmtree(target, ignore_errors=True)
        if lock.exists() and not tracked_lock:
            lock.unlink()


def repo_gate(_: argparse.Namespace) -> int:
    expected = os.environ.get("HEPTA_FINAL_SHA", "").strip()
    if expected:
        actual = git("rev-parse", "HEAD", capture=True).stdout.strip()
        if actual != expected:
            raise ConvergenceError(f"repository gate checked wrong head: {actual} != {expected}")
    if git("status", "--porcelain", capture=True).stdout.strip():
        raise ConvergenceError("repository gate starts from dirty tree")
    git("diff", "--check")
    run(("cargo", "fmt", "--manifest-path", "codex-rs/Cargo.toml", "--all", "--", "--check"), timeout=2400)
    for command in canonical_repository_commands():
        run_existing(command, timeout=7200)
    lane_specific_repository_gates()
    standalone_lane_f_gate()
    git("diff", "--check")
    status = git("status", "--porcelain", capture=True)
    if status.stdout.strip():
        raise ConvergenceError(f"repository gates mutated the qualified tree:\n{status.stdout}")
    return 0


def package_selectors(packages: list[str]) -> list[str]:
    values: list[str] = []
    for package in packages:
        values.extend(("-p", package))
    return values


def package_gate(args: argparse.Namespace) -> int:
    packages = json.loads(args.packages_json)
    if not isinstance(packages, list) or not packages or not all(isinstance(value, str) for value in packages):
        raise ConvergenceError("package gate requires a non-empty string package list")
    expected = os.environ.get("HEPTA_FINAL_SHA", "").strip()
    if expected:
        actual = git("rev-parse", "HEAD", capture=True).stdout.strip()
        if actual != expected:
            raise ConvergenceError(f"package gate checked wrong head: {actual} != {expected}")
    common = ("--manifest-path", "codex-rs/Cargo.toml", "--locked", *package_selectors(packages), "--all-targets")
    if args.check_only:
        run(("cargo", "check", *common), timeout=14400)
    else:
        run(("cargo", "test", *common), timeout=18000)
        run(("cargo", "clippy", *common, "--no-deps", "--", "-D", "warnings"), timeout=18000)
    if git("status", "--porcelain", capture=True).stdout.strip():
        raise ConvergenceError("package gate mutated the qualified tree")
    return 0


def close_open_pull_requests() -> int:
    result = run(
        ("gh", "api", "--paginate", f"repos/{REPO}/pulls?state=open&per_page=100", "--jq", ".[].number"),
        capture=True,
        timeout=600,
    )
    numbers = [line.strip() for line in result.stdout.splitlines() if line.strip().isdigit()]
    for number in numbers:
        run(("gh", "api", "-X", "PATCH", f"repos/{REPO}/pulls/{number}", "-f", "state=closed"), timeout=120)
    return len(numbers)


def rename_default_to_main(final_sha: str) -> None:
    git("push", "origin", f"{final_sha}:refs/heads/{DEFAULT_BRANCH}", timeout=1800)
    observed = remote_heads()
    if observed.get(DEFAULT_BRANCH) != final_sha:
        raise ConvergenceError("old default branch did not advance to qualified final SHA")
    if "main" in observed:
        git("push", "origin", ":refs/heads/main", timeout=600)
    encoded = urllib.parse.quote(DEFAULT_BRANCH, safe="")
    run(
        (
            "gh",
            "api",
            "-X",
            "POST",
            f"repos/{REPO}/branches/{encoded}/rename",
            "-f",
            "new_name=main",
        ),
        timeout=600,
    )
    for _ in range(30):
        current = remote_heads()
        if current.get("main") == final_sha and DEFAULT_BRANCH not in current:
            return
        time.sleep(2)
    raise ConvergenceError("default branch rename did not converge to main")


def delete_non_main_branches() -> list[str]:
    deleted: list[str] = []
    for _ in range(6):
        heads = remote_heads()
        branches = [branch for branch in heads if branch != "main"]
        if not branches:
            return deleted
        for offset in range(0, len(branches), 30):
            batch = branches[offset : offset + 30]
            result = git("push", "origin", "--delete", *batch, check=False, capture=True, timeout=1800)
            if result.returncode != 0:
                for branch in batch:
                    one = git("push", "origin", "--delete", branch, check=False, capture=True, timeout=300)
                    if one.returncode != 0 and branch in remote_heads():
                        raise ConvergenceError(f"cannot delete non-main branch: {branch}")
                    deleted.append(branch)
            else:
                deleted.extend(batch)
        time.sleep(2)
    remaining = [branch for branch in remote_heads() if branch != "main"]
    if remaining:
        raise ConvergenceError(f"non-main branches remain after cleanup: {remaining[:20]}")
    return deleted


def finalize(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.manifest.resolve())
    verify_snapshot(manifest)
    final_sha = args.final_sha
    candidate_branch = args.candidate_branch
    fetch_all()
    remote = remote_heads()
    if remote.get(candidate_branch) != final_sha:
        raise ConvergenceError("qualified candidate branch moved before publication")
    git("cat-file", "-e", f"{final_sha}^{{commit}}")
    for branch, sha in manifest["heads"].items():
        if git("merge-base", "--is-ancestor", sha, final_sha, check=False).returncode != 0:
            raise ConvergenceError(f"frozen branch tip is not in qualified final history: {branch}")
    cancelled_before = cancel_other_runs()
    closed_prs = close_open_pull_requests()
    rename_default_to_main(final_sha)
    cancelled_after = cancel_other_runs()
    deleted = delete_non_main_branches()
    final_heads = remote_heads()
    if final_heads != {"main": final_sha}:
        raise ConvergenceError(f"repository did not reach one-main state: {final_heads}")
    repo_info = run(("gh", "api", f"repos/{REPO}", "--jq", ".default_branch"), capture=True, timeout=120)
    if repo_info.stdout.strip() != "main":
        raise ConvergenceError(f"repository default branch is not main: {repo_info.stdout.strip()}")
    receipt = {
        "schema": "hepta.single-main.final.v1",
        "repository": REPO,
        "runId": RUN_ID,
        "runAttempt": RUN_ATTEMPT,
        "finalSha": final_sha,
        "finalTree": git("rev-parse", f"{final_sha}^{{tree}}", capture=True).stdout.strip(),
        "defaultBranch": "main",
        "remainingBranches": final_heads,
        "frozenBranchCount": manifest["branchCount"],
        "archivePrefix": manifest["archivePrefix"],
        "closedPullRequests": closed_prs,
        "deletedBranches": len(set(deleted)),
        "cancelledRuns": cancelled_before + cancelled_after,
        "repositoryControlledGapsClosed": True,
        "allFrozenBranchTipsReachable": True,
        "onlyMainBranchRetained": True,
        "authorityGranted": False,
        "externalAuthorityGatesRetained": True,
    }
    write_json(args.evidence.resolve() / "FINAL.json", receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    freeze_parser = subparsers.add_parser("freeze")
    freeze_parser.add_argument("--out", type=Path, required=True)
    freeze_parser.set_defaults(function=freeze)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--manifest", type=Path, required=True)
    prepare_parser.add_argument("--evidence", type=Path, required=True)
    prepare_parser.set_defaults(function=prepare)
    repo_parser = subparsers.add_parser("repo-gate")
    repo_parser.set_defaults(function=repo_gate)
    package_parser = subparsers.add_parser("package-gate")
    package_parser.add_argument("--packages-json", required=True)
    package_parser.add_argument("--check-only", action="store_true")
    package_parser.set_defaults(function=package_gate)
    finalize_parser = subparsers.add_parser("finalize")
    finalize_parser.add_argument("--manifest", type=Path, required=True)
    finalize_parser.add_argument("--final-sha", required=True)
    finalize_parser.add_argument("--candidate-branch", required=True)
    finalize_parser.add_argument("--evidence", type=Path, required=True)
    finalize_parser.set_defaults(function=finalize)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.function(args))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"HEPTA_SINGLE_MAIN_CONVERGENCE_ERROR: {error}", file=sys.stderr)
        raise
