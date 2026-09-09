#!/usr/bin/env python3
"""Build a dependency-ordered Hepta convergence candidate.

This executor is intentionally incapable of self-approving independent review,
production activation, selection, promotion or release.  It merges only named
2026-09-10 lane candidates, repairs generated exact-source metadata, runs the
repository's own closed-world verifiers and the affected Rust package gates,
and publishes a dedicated integration candidate plus machine-readable receipts.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

ROOT = Path.cwd()
BASE_REF = os.environ.get(
    "HEPTA_CONVERGENCE_BASE",
    "origin/ops/hepta-final-convergence-review-anchor-20260909",
)
TARGET_BRANCH = os.environ.get(
    "HEPTA_CONVERGENCE_TARGET",
    "integration/hepta-global-gap-closure-20260910",
)
RUN_ID = os.environ.get("GITHUB_RUN_ID", "local")
RUN_ATTEMPT = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
OUT = ROOT / "qualification" / "global-gap-closure"
LOG_DIR = OUT / "logs"

LANE_ORDER = ("A", "B", "C", "D", "E", "F", "G")
LANE_PREFERENCES: dict[str, tuple[str, ...]] = {
    "A": ("codex/lane-a-gap-closure-20260910", "codex/hepta-lane-a-gap-closure-20260910"),
    "B": ("codex/hepta-lane-b-gap-closure-20260910", "codex/lane-b-gap-closure-20260910"),
    "C": ("codex/lane-c-full-gap-closure-20260910", "codex/hepta-lane-c-gap-closure-20260910"),
    "D": ("codex/hepta-lane-d-gap-closure-20260910", "codex/lane-d-gap-closure-20260910"),
    "E": ("codex/hepta-lane-e-gap-closure-20260910", "codex/lane-e-gap-closure-20260910"),
    "F": ("codex/lane-f-gap-closure-20260910", "codex/hepta-lane-f-gap-closure-20260910"),
    "G": ("codex/hepta-lane-g-gap-closure-20260910", "codex/lane-g-gap-closure-20260910"),
}

GENERATED_CONFLICT_PATTERNS = (
    re.compile(r"^codex-rs/Cargo\.lock$"),
    re.compile(r"^docs/(?:STATUS\.md|CURRENT\.json)$"),
    re.compile(r"^docs/.*/STATUS(?:\.md|\.json)$"),
    re.compile(r"^qualification/module-execution-dossiers/(?:NATIVE_BINDINGS|IMPLEMENTATION_COMPLETION)\.json$"),
)

VERIFY_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("python3", "scripts/hepta-readiness.py", "self-test"),
    ("python3", "scripts/hepta-readiness.py", "generate-status", "--check"),
    ("python3", "scripts/hepta-readiness.py", "verify"),
    ("python3", "scripts/hepta-implementation-dossiers.py", "self-test"),
    ("python3", "scripts/hepta-implementation-dossiers.py", "generate-status", "--check"),
    ("python3", "scripts/hepta-implementation-dossiers.py", "verify"),
    ("python3", "scripts/hepta-technical-closure.py", "self-test"),
    ("python3", "scripts/hepta-technical-closure.py", "verify"),
    ("python3", "qualification/module-execution-dossiers/implementation_contracts.py", "self-test"),
    ("python3", "qualification/module-execution-dossiers/implementation_contracts.py", "verify-repository"),
    ("python3", "scripts/hepta-module-docs.py", "self-test"),
    ("python3", "scripts/hepta-module-docs.py", "verify"),
    ("python3", "scripts/hepta-algorithm-docs.py", "self-test"),
    ("python3", "scripts/hepta-algorithm-docs.py", "verify-sources"),
    ("python3", "scripts/hepta-algorithm-docs.py", "generate-status", "--check"),
    ("python3", "scripts/hepta-algorithm-docs.py", "verify"),
    ("python3", "scripts/hepta-cns.py", "self-test"),
    ("python3", "scripts/hepta-cns.py", "generate-status", "--check"),
    ("python3", "scripts/hepta-cns.py", "verify"),
    ("python3", "scripts/hepta-hnmf.py", "self-test"),
    ("python3", "scripts/hepta-hnmf.py", "verify"),
    ("python3", "scripts/hepta-docs.py", "self-test"),
    ("python3", "scripts/hepta-docs.py", "verify"),
)

GENERATOR_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("python3", "scripts/hepta-readiness.py", "generate-status"),
    ("python3", "scripts/hepta-implementation-dossiers.py", "generate-status"),
    ("python3", "scripts/hepta-algorithm-docs.py", "generate-status"),
    ("python3", "scripts/hepta-cns.py", "generate-status"),
    ("python3", "scripts/hepta-docs.py", "generate-status"),
)


@dataclass
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    duration_seconds: float
    output: str

    @property
    def passed(self) -> bool:
        return self.returncode == 0

    def receipt(self) -> dict[str, Any]:
        encoded = self.output.encode("utf-8", errors="replace")
        return {
            "command": list(self.argv),
            "returnCode": self.returncode,
            "durationSeconds": round(self.duration_seconds, 3),
            "outputSha256": hashlib.sha256(encoded).hexdigest(),
            "tail": self.output.splitlines()[-40:],
        }


def run(
    argv: Iterable[str],
    *,
    check: bool = False,
    timeout: int = 3600,
    env: dict[str, str] | None = None,
) -> CommandResult:
    args = tuple(argv)
    print("+", shlex.join(args), flush=True)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            args,
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        result = CommandResult(
            argv=args,
            returncode=completed.returncode,
            duration_seconds=time.monotonic() - started,
            output=completed.stdout,
        )
    except subprocess.TimeoutExpired as error:
        output = (error.stdout or "") + "\nTIMEOUT\n"
        result = CommandResult(
            argv=args,
            returncode=124,
            duration_seconds=time.monotonic() - started,
            output=output,
        )
    print(result.output[-8000:], flush=True)
    if check and not result.passed:
        raise RuntimeError(f"command failed ({result.returncode}): {shlex.join(args)}")
    return result


def git(*args: str, check: bool = True, timeout: int = 600) -> CommandResult:
    return run(("git", *args), check=check, timeout=timeout)


def git_text(*args: str) -> str:
    result = git(*args)
    return result.output.strip()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def available_remote_branches() -> dict[str, int]:
    result = git(
        "for-each-ref",
        "--format=%(refname:short)|%(committerdate:unix)",
        "refs/remotes/origin",
    )
    branches: dict[str, int] = {}
    for line in result.output.splitlines():
        if "|" not in line:
            continue
        ref, timestamp = line.rsplit("|", 1)
        if not ref.startswith("origin/") or ref == "origin/HEAD":
            continue
        try:
            branches[ref.removeprefix("origin/")] = int(timestamp)
        except ValueError:
            continue
    return branches


def select_lane_branches(branches: dict[str, int]) -> dict[str, str | None]:
    selected: dict[str, str | None] = {}
    for lane in LANE_ORDER:
        for preferred in LANE_PREFERENCES[lane]:
            if preferred in branches:
                selected[lane] = preferred
                break
        else:
            marker = f"lane-{lane.lower()}"
            candidates = [
                branch
                for branch in branches
                if marker in branch.lower()
                and "20260910" in branch
                and ("gap" in branch.lower() or "closure" in branch.lower())
                and not branch.startswith("ops/hepta-global-gap-closure")
            ]
            selected[lane] = max(candidates, key=lambda value: branches[value]) if candidates else None
    return selected


def is_generated_conflict(path: str) -> bool:
    return any(pattern.match(path) for pattern in GENERATED_CONFLICT_PATTERNS)


def merge_lane(lane: str, branch: str) -> dict[str, Any]:
    before = git_text("rev-parse", "HEAD")
    result = git(
        "merge",
        "--no-ff",
        "--no-edit",
        "-m",
        f"merge(lane-{lane.lower()}): converge {branch}\n\nSigned-off-by: OpenAI Codex <noreply@openai.com>",
        f"origin/{branch}",
        check=False,
        timeout=1800,
    )
    conflicts: list[str] = []
    auto_resolved = False
    if not result.passed:
        conflicts = [
            line.strip()
            for line in git("diff", "--name-only", "--diff-filter=U", check=False).output.splitlines()
            if line.strip()
        ]
        if conflicts and all(is_generated_conflict(path) for path in conflicts):
            for path in conflicts:
                git("checkout", "--ours", "--", path)
                git("add", "--", path)
            git(
                "commit",
                "--signoff",
                "-m",
                f"merge(lane-{lane.lower()}): resolve generated convergence metadata",
            )
            auto_resolved = True
        else:
            git("merge", "--abort", check=False)
            return {
                "lane": lane,
                "branch": branch,
                "before": before,
                "merged": False,
                "conflicts": conflicts,
                "outputTail": result.output.splitlines()[-80:],
            }
    return {
        "lane": lane,
        "branch": branch,
        "before": before,
        "after": git_text("rev-parse", "HEAD"),
        "merged": True,
        "autoResolvedGeneratedOnly": auto_resolved,
        "conflicts": conflicts,
    }


def regenerate_status_documents() -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    for command in GENERATOR_COMMANDS:
        if not (ROOT / command[1]).exists():
            continue
        result = run(command, check=False, timeout=900)
        receipts.append(result.receipt())
        # Some generators intentionally support only checked output.  A failed
        # generator is retained as evidence and the strict verifier decides.
    return receipts


def repair_native_binding_hashes() -> dict[str, Any]:
    path = ROOT / "qualification/module-execution-dossiers/NATIVE_BINDINGS.json"
    if not path.exists():
        return {"present": False, "updated": 0}
    document = json.loads(path.read_text(encoding="utf-8"))
    observations = document.get("observations", [])
    updated = 0
    missing: list[str] = []
    for observation in observations:
        source = observation.get("path")
        if not isinstance(source, str):
            continue
        source_path = ROOT / source
        if not source_path.is_file():
            missing.append(source)
            continue
        actual = git_text("hash-object", "--", source)
        if observation.get("blobSha") != actual:
            observation["blobSha"] = actual
            updated += 1
    if updated:
        write_json(path, document)
    return {
        "present": True,
        "updated": updated,
        "missingPaths": missing,
        "observationCount": len(observations),
    }


def cargo_metadata(unlocked: bool) -> tuple[dict[str, Any] | None, CommandResult]:
    argv = [
        "cargo",
        "metadata",
        "--manifest-path",
        "codex-rs/Cargo.toml",
        "--format-version",
        "1",
    ]
    if not unlocked:
        argv.append("--locked")
    result = run(argv, check=False, timeout=1800)
    if not result.passed:
        return None, result
    try:
        return json.loads(result.output), result
    except json.JSONDecodeError:
        return None, result


def normalize_lockfile() -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    metadata, locked = cargo_metadata(unlocked=False)
    receipts.append(locked.receipt())
    if metadata is not None:
        return receipts
    metadata, unlocked = cargo_metadata(unlocked=True)
    receipts.append(unlocked.receipt())
    if metadata is None:
        return receipts
    locked_again, result = cargo_metadata(unlocked=False)
    receipts.append(result.receipt())
    return receipts


def affected_packages(base_commit: str) -> tuple[list[str], dict[str, Any]]:
    metadata_result = run(
        (
            "cargo",
            "metadata",
            "--manifest-path",
            "codex-rs/Cargo.toml",
            "--format-version",
            "1",
            "--locked",
        ),
        check=False,
        timeout=1800,
    )
    if not metadata_result.passed:
        return [], {"metadata": metadata_result.receipt()}
    metadata = json.loads(metadata_result.output)
    packages = metadata.get("packages", [])
    workspace_members = set(metadata.get("workspace_members", []))
    by_id = {package["id"]: package for package in packages if package.get("id") in workspace_members}
    changed = {
        line.strip()
        for line in git("diff", "--name-only", f"{base_commit}...HEAD").output.splitlines()
        if line.strip()
    }
    direct: set[str] = set()
    for package_id, package in by_id.items():
        manifest = Path(package["manifest_path"])
        try:
            package_root = manifest.parent.relative_to(ROOT).as_posix()
        except ValueError:
            continue
        if any(path == package_root or path.startswith(package_root + "/") for path in changed):
            direct.add(package_id)

    reverse: dict[str, set[str]] = defaultdict(set)
    for package_id, package in by_id.items():
        for dependency in package.get("dependencies", []):
            dep_name = dependency.get("name")
            for candidate_id, candidate in by_id.items():
                if candidate.get("name") == dep_name:
                    reverse[candidate_id].add(package_id)
    affected = set(direct)
    queue = deque(direct)
    while queue:
        current = queue.popleft()
        for dependent in reverse.get(current, set()):
            if dependent not in affected:
                affected.add(dependent)
                queue.append(dependent)

    names = sorted(
        {
            by_id[package_id]["name"]
            for package_id in affected
            if by_id[package_id]["name"].startswith("codex-hepta-")
        }
    )
    return names, {
        "changedFiles": sorted(changed),
        "directPackageIds": sorted(direct),
        "affectedPackageIds": sorted(affected),
        "selectedPackageNames": names,
    }


def run_repository_verifiers() -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    for command in VERIFY_COMMANDS:
        if not (ROOT / command[1]).exists():
            receipts.append({"command": list(command), "skipped": "missing executable"})
            continue
        receipts.append(run(command, check=False, timeout=1800).receipt())
    receipts.append(
        run(
            (
                "cargo",
                "fmt",
                "--manifest-path",
                "codex-rs/Cargo.toml",
                "--all",
                "--",
                "--check",
            ),
            check=False,
            timeout=1800,
        ).receipt()
    )
    receipts.append(run(("git", "diff", "--check"), check=False, timeout=300).receipt())
    return receipts


def run_package_gates(packages: list[str]) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    for package in packages:
        test = run(
            (
                "cargo",
                "test",
                "--manifest-path",
                "codex-rs/Cargo.toml",
                "--locked",
                "-p",
                package,
                "--all-targets",
            ),
            check=False,
            timeout=5400,
        )
        receipts.append({"package": package, "gate": "test", **test.receipt()})
        lint = run(
            (
                "cargo",
                "clippy",
                "--manifest-path",
                "codex-rs/Cargo.toml",
                "--locked",
                "-p",
                package,
                "--all-targets",
                "--no-deps",
                "--",
                "-D",
                "warnings",
            ),
            check=False,
            timeout=5400,
        )
        receipts.append({"package": package, "gate": "clippy", **lint.receipt()})
    return receipts


def all_receipts_pass(receipts: Iterable[dict[str, Any]]) -> bool:
    for receipt in receipts:
        if "skipped" in receipt:
            continue
        if receipt.get("returnCode") != 0:
            return False
    return True


def external_gate_handoff() -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "authorityGranted": False,
        "selfCertificationAllowed": False,
        "gates": [
            {"id": "independent_semantic_review", "status": "external_open"},
            {"id": "runtime_and_model_identity_attestation", "status": "external_open"},
            {"id": "future_time_validity", "status": "external_open"},
            {"id": "target_host_or_hardware_qualification", "status": "external_open"},
            {"id": "remote_owner_consent", "status": "external_open"},
            {"id": "operator_acceptance", "status": "external_open"},
            {"id": "production_canary", "status": "external_open"},
            {"id": "selection_and_promotion", "status": "external_open"},
            {"id": "release_authorization", "status": "external_open"},
        ],
    }


def commit_if_dirty(message: str) -> str:
    if not git("status", "--porcelain", check=False).output.strip():
        return git_text("rev-parse", "HEAD")
    git("add", "-A")
    git("commit", "--signoff", "-m", message)
    return git_text("rev-parse", "HEAD")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    git("config", "user.name", "Hepta Convergence Controller")
    git("config", "user.email", "noreply@openai.com")
    git("fetch", "--prune", "origin", "+refs/heads/*:refs/remotes/origin/*", timeout=1800)

    branches = available_remote_branches()
    selected = select_lane_branches(branches)
    if not any(selected.values()):
        raise RuntimeError("no 2026-09-10 lane closure branches were discovered")

    base_commit = git_text("rev-parse", BASE_REF)
    git("checkout", "-B", TARGET_BRANCH, BASE_REF)
    merge_receipts: list[dict[str, Any]] = []
    merge_blockers: list[dict[str, Any]] = []
    for lane in LANE_ORDER:
        branch = selected[lane]
        if branch is None:
            merge_receipts.append({"lane": lane, "branch": None, "status": "no_current_candidate"})
            continue
        receipt = merge_lane(lane, branch)
        merge_receipts.append(receipt)
        if not receipt.get("merged"):
            merge_blockers.append(receipt)
            break

    initial = {
        "schemaVersion": 1,
        "runId": RUN_ID,
        "runAttempt": RUN_ATTEMPT,
        "baseRef": BASE_REF,
        "baseCommit": base_commit,
        "targetBranch": TARGET_BRANCH,
        "selectedLaneBranches": selected,
        "mergeReceipts": merge_receipts,
        "mergeBlockers": merge_blockers,
        "authorityGranted": False,
    }
    write_json(OUT / "MERGE_RECEIPT.json", initial)
    if merge_blockers:
        commit_if_dirty("ops: record unresolved global convergence conflict")
        git("push", "--force-with-lease", "origin", f"HEAD:refs/heads/{TARGET_BRANCH}")
        return 2

    generator_receipts = regenerate_status_documents()
    native_repair = repair_native_binding_hashes()
    lock_receipts = normalize_lockfile()
    # Format before exact-source verification, then refresh source anchors.
    format_apply = run(
        ("cargo", "fmt", "--manifest-path", "codex-rs/Cargo.toml", "--all"),
        check=False,
        timeout=1800,
    )
    native_repair_after_format = repair_native_binding_hashes()
    source_commit = commit_if_dirty("chore: materialize dependency-ordered Hepta convergence")

    verifier_receipts = run_repository_verifiers()
    packages, package_selection = affected_packages(base_commit)
    package_receipts = run_package_gates(packages)

    repository_passed = (
        format_apply.passed
        and all_receipts_pass(lock_receipts)
        and all_receipts_pass(verifier_receipts)
        and all_receipts_pass(package_receipts)
    )
    status = {
        "schemaVersion": 1,
        "runId": RUN_ID,
        "runAttempt": RUN_ATTEMPT,
        "baseRef": BASE_REF,
        "baseCommit": base_commit,
        "targetBranch": TARGET_BRANCH,
        "sourceCommit": source_commit,
        "selectedLaneBranches": selected,
        "mergeReceipts": merge_receipts,
        "generatorReceipts": generator_receipts,
        "nativeBindingRepair": native_repair,
        "nativeBindingRepairAfterFormat": native_repair_after_format,
        "lockReceipts": lock_receipts,
        "formatApply": format_apply.receipt(),
        "repositoryVerifierReceipts": verifier_receipts,
        "packageSelection": package_selection,
        "packageGateReceipts": package_receipts,
        "repositoryInternalValidationPassed": repository_passed,
        "repositoryInternalGapsClosed": repository_passed,
        "allGapsClosed": False,
        "externalAuthorityGatesRetained": True,
        "authorityGranted": False,
        "productionActivation": False,
        "selection": False,
        "promotion": False,
        "release": False,
    }
    write_json(OUT / "STATUS.json", status)
    write_json(OUT / "EXTERNAL_GATE_HANDOFF.json", external_gate_handoff())

    failed_commands = [
        receipt
        for receipt in (*lock_receipts, *verifier_receipts, *package_receipts)
        if "skipped" not in receipt and receipt.get("returnCode") != 0
    ]
    report_lines = [
        "# Hepta global gap-closure convergence",
        "",
        f"- base: `{BASE_REF}` @ `{base_commit}`",
        f"- target: `{TARGET_BRANCH}`",
        f"- source commit: `{source_commit}`",
        f"- repository-internal validation: `{'PASS' if repository_passed else 'BLOCKED'}`",
        "- external independent-authority gates: `RETAINED_OPEN`",
        "- self-issued production/release authority: `false`",
        "",
        "## Lane inputs",
        "",
    ]
    for lane in LANE_ORDER:
        report_lines.append(f"- Lane {lane}: `{selected[lane] or 'no current candidate'}`")
    report_lines.extend(["", "## Remaining repository blockers", ""])
    if failed_commands:
        for receipt in failed_commands:
            report_lines.append(
                f"- `{shlex.join(receipt.get('command', []))}` returned `{receipt.get('returnCode')}`; "
                f"output sha256 `{receipt.get('outputSha256')}`."
            )
    else:
        report_lines.append("- none detected by the exact-source, document, format, test and lint gates")
    report_lines.extend(
        [
            "",
            "## Authority ceiling",
            "",
            "This candidate does not satisfy or mint independent review, operator acceptance, "
            "target-host/hardware qualification, production canary, selection, promotion or release.",
            "",
        ]
    )
    (OUT / "REPORT.md").write_text("\n".join(report_lines), encoding="utf-8")
    receipt_commit = commit_if_dirty(
        "docs: bind global convergence validation and external-gate handoff"
    )
    status["receiptCommit"] = receipt_commit
    write_json(OUT / "STATUS.json", status)
    # Amend only the receipt commit so STATUS binds its exact final identity.
    git("add", str((OUT / "STATUS.json").relative_to(ROOT)))
    git("commit", "--amend", "--no-edit")
    final_commit = git_text("rev-parse", "HEAD")
    git("push", "--force-with-lease", "origin", f"HEAD:refs/heads/{TARGET_BRANCH}")
    print(json.dumps({"target": TARGET_BRANCH, "head": final_commit, "passed": repository_passed}))
    return 0 if repository_passed else 3


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # fail closed and leave a visible traceback
        print(f"GLOBAL_CONVERGENCE_ERROR: {error}", file=sys.stderr)
        raise
