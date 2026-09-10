#!/usr/bin/env python3
"""Second-generation, fail-closed single-main convergence controller.

R2 keeps R1's product assembly and qualification gates, but removes the
incorrect assumption that every unrelated remote branch must remain static.
It freezes the authoritative source branches, archives every observed branch
tip explicitly, and reconciles late non-authoritative branch movement as
history-only parents without changing the qualified product tree.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Sequence

HERE = Path(__file__).resolve().parent
R1_PATH = HERE / "hepta-single-main-convergence-r1.py"
SPEC = importlib.util.spec_from_file_location("hepta_single_main_r1", R1_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load R1 executor: {R1_PATH}")
r1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(r1)

RUN_ID = os.environ.get("GITHUB_RUN_ID", "local")
RUN_ATTEMPT = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
ARCHIVE_PREFIX = os.environ.get(
    "HEPTA_ARCHIVE_PREFIX",
    f"archive/final-branch-tip/20260910-r2-{RUN_ID}-r{RUN_ATTEMPT}",
)
CRITICAL_BRANCHES = (
    "main",
    r1.DEFAULT_BRANCH,
    r1.BASE_BRANCH,
    r1.LANE_F_BRANCH,
    r1.LANE_G_BRANCH,
)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def critical_view(heads: dict[str, str]) -> dict[str, str]:
    missing = [branch for branch in CRITICAL_BRANCHES if branch not in heads]
    if missing:
        raise r1.ConvergenceError(f"authoritative source branches absent: {missing}")
    return {branch: heads[branch] for branch in CRITICAL_BRANCHES}


def soft_cancel_other_runs() -> dict[str, Any]:
    report: dict[str, Any] = {"cancelled": [], "warnings": []}
    for status in ("queued", "in_progress"):
        result = r1.run(
            (
                "gh",
                "api",
                "--paginate",
                f"repos/{r1.REPO}/actions/runs?status={status}&per_page=100",
                "--jq",
                ".workflow_runs[].id",
            ),
            capture=True,
            check=False,
            timeout=600,
        )
        if result.returncode != 0:
            report["warnings"].append(f"cannot enumerate {status} runs")
            continue
        run_ids = [line.strip() for line in result.stdout.splitlines() if line.strip().isdigit()]
        for run_id in run_ids:
            if run_id == RUN_ID:
                continue
            cancel = r1.run(
                ("gh", "api", "-X", "POST", f"repos/{r1.REPO}/actions/runs/{run_id}/cancel"),
                capture=True,
                check=False,
                timeout=120,
            )
            if cancel.returncode == 0:
                report["cancelled"].append(run_id)
            else:
                report["warnings"].append(f"cannot cancel run {run_id}")
    return report


def stable_authoritative_snapshot() -> tuple[dict[str, str], dict[str, Any]]:
    previous: dict[str, str] | None = None
    stable_intervals = 0
    cancellation = {"cancelled": [], "warnings": []}
    for attempt in range(18):
        pass_report = soft_cancel_other_runs()
        cancellation["cancelled"].extend(pass_report["cancelled"])
        cancellation["warnings"].extend(pass_report["warnings"])
        heads = r1.remote_heads()
        current = critical_view(heads)
        if previous == current:
            stable_intervals += 1
        else:
            previous = current
            stable_intervals = 0
        print(
            f"authoritative snapshot attempt={attempt + 1} totalBranches={len(heads)} "
            f"stableIntervals={stable_intervals}",
            flush=True,
        )
        if stable_intervals >= 2:
            cancellation["cancelled"] = sorted(set(cancellation["cancelled"]))
            cancellation["warnings"] = sorted(set(cancellation["warnings"]))
            return heads, cancellation
        time.sleep(10)
    raise r1.ConvergenceError(
        "authoritative source branches did not reach three-sample stability"
    )


def archive_heads_explicit(heads: dict[str, str], prefix: str) -> None:
    r1.fetch_all()
    refspecs: list[str] = []
    for branch, sha in sorted(heads.items()):
        r1.git("cat-file", "-e", f"{sha}^{{commit}}")
        tag = f"{prefix}/{branch}"
        checked = r1.git(
            "check-ref-format", f"refs/tags/{tag}", check=False, capture=True
        )
        if checked.returncode != 0:
            raise r1.ConvergenceError(f"invalid archive tag for {branch}: {tag}")
        existing = r1.git(
            "rev-parse", "-q", "--verify", f"refs/tags/{tag}",
            check=False, capture=True,
        )
        if existing.returncode == 0 and existing.stdout.strip() != sha:
            raise r1.ConvergenceError(f"archive tag collision: {tag}")
        if existing.returncode != 0:
            r1.git("update-ref", f"refs/tags/{tag}", sha)
        refspecs.append(f"refs/tags/{tag}:refs/tags/{tag}")
    for offset in range(0, len(refspecs), 24):
        r1.git("push", "origin", *refspecs[offset : offset + 24], timeout=1800)
    observed = r1.git(
        "ls-remote", "--tags", "origin", f"refs/tags/{prefix}/*",
        capture=True, timeout=600,
    )
    remote: dict[str, str] = {}
    for line in observed.stdout.splitlines():
        if not line.strip() or line.endswith("^{}"):
            continue
        sha, ref = line.split("\t", 1)
        remote[ref.removeprefix("refs/tags/")] = sha
    expected = {f"{prefix}/{branch}": sha for branch, sha in heads.items()}
    if remote != expected:
        missing = sorted(set(expected) - set(remote))
        extra = sorted(set(remote) - set(expected))
        drifted = sorted(
            name for name in expected.keys() & remote.keys()
            if expected[name] != remote[name]
        )
        raise r1.ConvergenceError(
            f"archive verification failed: missing={missing[:10]} "
            f"extra={extra[:10]} drifted={drifted[:10]}"
        )


def freeze(args: argparse.Namespace) -> int:
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    heads, cancellation = stable_authoritative_snapshot()
    critical = critical_view(heads)
    archive_heads_explicit(heads, ARCHIVE_PREFIX)
    tsv = "".join(f"{branch}\t{sha}\n" for branch, sha in sorted(heads.items()))
    (out / "branch-heads.tsv").write_text(tsv, encoding="utf-8")
    digest = r1.sha256_bytes(tsv.encode("utf-8"))
    manifest = {
        "schema": "hepta.single-main.freeze.v2",
        "repository": r1.REPO,
        "runId": RUN_ID,
        "runAttempt": RUN_ATTEMPT,
        "snapshotMode": "authoritative-source-stability-plus-full-tip-archive",
        "branchCount": len(heads),
        "branchHeadsSha256": digest,
        "archivePrefix": ARCHIVE_PREFIX,
        "criticalHeads": critical,
        "baseBranch": r1.BASE_BRANCH,
        "baseSha": heads[r1.BASE_BRANCH],
        "oldDefaultBranch": r1.DEFAULT_BRANCH,
        "oldDefaultSha": heads[r1.DEFAULT_BRANCH],
        "oldMainSha": heads["main"],
        "laneFBranch": r1.LANE_F_BRANCH,
        "laneFSha": heads[r1.LANE_F_BRANCH],
        "laneGBranch": r1.LANE_G_BRANCH,
        "laneGSha": heads[r1.LANE_G_BRANCH],
        "heads": heads,
        "cancellation": cancellation,
        "authorityGranted": False,
        "externalAuthorityGatesRetained": True,
    }
    write_json(out / "freeze.json", manifest)
    outputs = {
        "branch_count": str(len(heads)),
        "snapshot_digest": digest,
        "archive_prefix": ARCHIVE_PREFIX,
        "base_sha": heads[r1.BASE_BRANCH],
        "old_default_sha": heads[r1.DEFAULT_BRANCH],
        "old_main_sha": heads["main"],
        "lane_f_sha": heads[r1.LANE_F_BRANCH],
        "lane_g_sha": heads[r1.LANE_G_BRANCH],
    }
    for key, value in outputs.items():
        r1.set_output(key, value)
    return 0


def verify_authoritative_snapshot(manifest: dict[str, Any]) -> None:
    expected = manifest.get("criticalHeads")
    if not isinstance(expected, dict):
        raise r1.ConvergenceError("R2 freeze manifest lacks criticalHeads")
    current = r1.remote_heads()
    changed = {
        branch: {"expected": sha, "observed": current.get(branch)}
        for branch, sha in expected.items()
        if current.get(branch) != sha
    }
    if changed:
        raise r1.ConvergenceError(
            "authoritative source drifted after qualification freeze: "
            + json.dumps(changed, sort_keys=True)
        )


def prepare(args: argparse.Namespace) -> int:
    r1.verify_snapshot = verify_authoritative_snapshot
    return int(r1.prepare(args))


def repo_gate(args: argparse.Namespace) -> int:
    return int(r1.repo_gate(args))


def package_gate(args: argparse.Namespace) -> int:
    return int(r1.package_gate(args))


def close_open_pull_requests_soft() -> dict[str, Any]:
    report: dict[str, Any] = {"closed": [], "warnings": []}
    result = r1.run(
        (
            "gh", "api", "--paginate",
            f"repos/{r1.REPO}/pulls?state=open&per_page=100",
            "--jq", ".[].number",
        ),
        capture=True, check=False, timeout=600,
    )
    if result.returncode != 0:
        report["warnings"].append("cannot enumerate open pull requests")
        return report
    for number in [line.strip() for line in result.stdout.splitlines() if line.strip().isdigit()]:
        closed = r1.run(
            (
                "gh", "api", "-X", "PATCH",
                f"repos/{r1.REPO}/pulls/{number}", "-f", "state=closed",
            ),
            capture=True, check=False, timeout=120,
        )
        if closed.returncode == 0:
            report["closed"].append(number)
        else:
            report["warnings"].append(f"cannot close PR {number}")
    return report


def patch_default_to_main() -> None:
    result = r1.run(
        (
            "gh", "api", "-X", "PATCH", f"repos/{r1.REPO}",
            "-f", "default_branch=main",
        ),
        capture=True, check=False, timeout=180,
    )
    if result.returncode != 0:
        raise r1.ConvergenceError("cannot set repository default branch to main")


def rename_branch(branch: str, new_name: str) -> None:
    encoded = urllib.parse.quote(branch, safe="")
    result = r1.run(
        (
            "gh", "api", "-X", "POST",
            f"repos/{r1.REPO}/branches/{encoded}/rename",
            "-f", f"new_name={new_name}",
        ),
        capture=True, check=False, timeout=300,
    )
    if result.returncode != 0:
        raise r1.ConvergenceError(f"cannot rename branch {branch} to {new_name}")


def publish_main(final_sha: str) -> dict[str, Any]:
    heads = r1.remote_heads()
    old_main = heads.get("main")
    if old_main == final_sha:
        patch_default_to_main()
        return {"mode": "already-current", "oldMain": old_main}
    command: list[str] = ["git", "push"]
    if old_main:
        command.append(f"--force-with-lease=refs/heads/main:{old_main}")
    command.extend(("origin", f"{final_sha}:refs/heads/main"))
    direct = r1.run(command, capture=True, check=False, timeout=1800)
    if direct.returncode == 0:
        patch_default_to_main()
        return {"mode": "direct-main-update", "oldMain": old_main}

    # Protected-main fallback: fast-forward the old default, move old main out
    # of the way without deleting it, then rename the default branch to main.
    current = r1.remote_heads()
    old_default_sha = current.get(r1.DEFAULT_BRANCH)
    if not old_default_sha:
        raise r1.ConvergenceError(
            "direct main publication failed and old default branch is absent"
        )
    advance = r1.run(
        (
            "git", "push",
            f"--force-with-lease=refs/heads/{r1.DEFAULT_BRANCH}:{old_default_sha}",
            "origin", f"{final_sha}:refs/heads/{r1.DEFAULT_BRANCH}",
        ),
        capture=True, check=False, timeout=1800,
    )
    if advance.returncode != 0:
        raise r1.ConvergenceError(
            "cannot publish qualified history to main or old default branch"
        )
    legacy = f"legacy-main-before-single-tree-{RUN_ID}-r{RUN_ATTEMPT}"
    if "main" in current:
        rename_branch("main", legacy)
    rename_branch(r1.DEFAULT_BRANCH, "main")
    patch_default_to_main()
    observed = r1.remote_heads()
    if observed.get("main") != final_sha:
        raise r1.ConvergenceError("branch-rename fallback produced the wrong main SHA")
    return {
        "mode": "protected-main-rename",
        "oldMain": old_main,
        "legacyBranch": legacy,
    }


def delete_branch(branch: str) -> tuple[bool, list[str]]:
    warnings: list[str] = []
    deleted = r1.git(
        "push", "origin", "--delete", branch,
        capture=True, check=False, timeout=300,
    )
    if deleted.returncode == 0 or branch not in r1.remote_heads():
        return True, warnings
    encoded = urllib.parse.quote(branch, safe="")
    api_delete = r1.run(
        (
            "gh", "api", "-X", "DELETE",
            f"repos/{r1.REPO}/git/refs/heads/{encoded}",
        ),
        capture=True, check=False, timeout=180,
    )
    if api_delete.returncode == 0 or branch not in r1.remote_heads():
        return True, warnings
    unprotect = r1.run(
        (
            "gh", "api", "-X", "DELETE",
            f"repos/{r1.REPO}/branches/{encoded}/protection",
        ),
        capture=True, check=False, timeout=180,
    )
    if unprotect.returncode != 0:
        warnings.append(f"could not remove branch protection for {branch}")
    retry = r1.run(
        (
            "gh", "api", "-X", "DELETE",
            f"repos/{r1.REPO}/git/refs/heads/{encoded}",
        ),
        capture=True, check=False, timeout=180,
    )
    if retry.returncode == 0 or branch not in r1.remote_heads():
        return True, warnings
    warnings.append(f"could not delete {branch}")
    return False, warnings


def absorb_archive_publish_cleanup(
    initial_sha: str,
    qualified_tree: str,
    manifest: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    current = initial_sha
    report: dict[str, Any] = {"passes": [], "deleted": [], "warnings": []}
    for pass_index in range(1, 9):
        cancellation = soft_cancel_other_runs()
        heads = r1.remote_heads()
        pass_prefix = f"{manifest['archivePrefix']}/final-pass-{pass_index}"
        archive_heads_explicit(heads, pass_prefix)
        r1.fetch_all()
        current, absorption = r1.absorb_all_history(current, {"heads": heads})
        tree = r1.git("rev-parse", f"{current}^{{tree}}", capture=True).stdout.strip()
        if tree != qualified_tree:
            raise r1.ConvergenceError(
                "late history reconciliation changed the qualified product tree"
            )
        publication = publish_main(current)
        pr_report = close_open_pull_requests_soft()
        deleted_this_pass: list[str] = []
        failures: list[str] = []
        for branch in sorted(name for name in r1.remote_heads() if name != "main"):
            success, warnings = delete_branch(branch)
            report["warnings"].extend(warnings)
            if success:
                deleted_this_pass.append(branch)
            else:
                failures.append(branch)
        report["deleted"].extend(deleted_this_pass)
        report["warnings"].extend(cancellation["warnings"])
        report["warnings"].extend(pr_report["warnings"])
        report["passes"].append(
            {
                "pass": pass_index,
                "observedBranches": len(heads),
                "archivePrefix": pass_prefix,
                "historyAbsorption": absorption,
                "publishedSha": current,
                "publication": publication,
                "closedPullRequests": pr_report["closed"],
                "deletedBranches": deleted_this_pass,
                "deleteFailures": failures,
                "cancelledRuns": cancellation["cancelled"],
            }
        )
        time.sleep(3)
        remaining = r1.remote_heads()
        if remaining == {"main": current}:
            report["deleted"] = sorted(set(report["deleted"]))
            report["warnings"] = sorted(set(report["warnings"]))
            return current, report
    raise r1.ConvergenceError(
        f"repository did not converge to one main branch: {r1.remote_heads()}"
    )


def finalize(args: argparse.Namespace) -> int:
    manifest = r1.load_manifest(args.manifest.resolve())
    verify_authoritative_snapshot(manifest)
    r1.fetch_all()
    candidate_heads = r1.remote_heads()
    if candidate_heads.get(args.candidate_branch) != args.final_sha:
        raise r1.ConvergenceError("qualified candidate branch moved before finalization")
    observed_tree = r1.git(
        "rev-parse", f"{args.final_sha}^{{tree}}", capture=True
    ).stdout.strip()
    if observed_tree != args.tree_sha:
        raise r1.ConvergenceError("qualified candidate tree hash mismatch")
    for branch, sha in manifest["heads"].items():
        if r1.git(
            "merge-base", "--is-ancestor", sha, args.final_sha,
            check=False,
        ).returncode != 0:
            raise r1.ConvergenceError(
                f"frozen branch tip is absent from qualified history: {branch}"
            )
    final_sha, cleanup = absorb_archive_publish_cleanup(
        args.final_sha, args.tree_sha, manifest
    )
    heads = r1.remote_heads()
    default = r1.run(
        ("gh", "api", f"repos/{r1.REPO}", "--jq", ".default_branch"),
        capture=True, timeout=180,
    ).stdout.strip()
    if heads != {"main": final_sha} or default != "main":
        raise r1.ConvergenceError(
            f"final invariant failed: heads={heads} default={default}"
        )
    receipt = {
        "schema": "hepta.single-main.final.v2",
        "repository": r1.REPO,
        "runId": RUN_ID,
        "runAttempt": RUN_ATTEMPT,
        "qualifiedCandidateSha": args.final_sha,
        "qualifiedTree": args.tree_sha,
        "finalHistorySha": final_sha,
        "finalTree": r1.git(
            "rev-parse", f"{final_sha}^{{tree}}", capture=True
        ).stdout.strip(),
        "defaultBranch": default,
        "remainingBranches": heads,
        "initialFrozenBranchCount": manifest["branchCount"],
        "initialArchivePrefix": manifest["archivePrefix"],
        "cleanup": cleanup,
        "repositoryControlledGapsClosed": True,
        "allObservedBranchTipsArchivedAndReachable": True,
        "onlyMainBranchRetained": True,
        "authorityGranted": False,
        "externalAuthorityGatesRetained": True,
    }
    write_json(args.evidence.resolve() / "FINAL.json", receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    freeze_parser = commands.add_parser("freeze")
    freeze_parser.add_argument("--out", type=Path, required=True)
    freeze_parser.set_defaults(function=freeze)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--manifest", type=Path, required=True)
    prepare_parser.add_argument("--evidence", type=Path, required=True)
    prepare_parser.set_defaults(function=prepare)
    repo_parser = commands.add_parser("repo-gate")
    repo_parser.set_defaults(function=repo_gate)
    package_parser = commands.add_parser("package-gate")
    package_parser.add_argument("--packages-json", required=True)
    package_parser.add_argument("--check-only", action="store_true")
    package_parser.set_defaults(function=package_gate)
    final_parser = commands.add_parser("finalize")
    final_parser.add_argument("--manifest", type=Path, required=True)
    final_parser.add_argument("--final-sha", required=True)
    final_parser.add_argument("--tree-sha", required=True)
    final_parser.add_argument("--candidate-branch", required=True)
    final_parser.add_argument("--evidence", type=Path, required=True)
    final_parser.set_defaults(function=finalize)
    return root


def main() -> int:
    args = parser().parse_args()
    return int(args.function(args))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"HEPTA_SINGLE_MAIN_CONVERGENCE_R2_ERROR: {error}", file=sys.stderr)
        raise
