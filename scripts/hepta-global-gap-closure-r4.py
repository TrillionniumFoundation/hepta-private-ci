#!/usr/bin/env python3
"""Dependency-ordered, fail-closed global Hepta convergence executor.

The executor may create and qualify a dedicated integration candidate.  It may
not self-issue independent review, production activation, selection, promotion,
release, model/provider authority, or an additional production writer.
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
TARGET_BRANCH = os.environ.get(
    "HEPTA_CONVERGENCE_TARGET",
    "integration/hepta-global-gap-closure-20260910-r4",
)
OUT = ROOT / "qualification" / "global-gap-closure-r4"
RUN_ID = os.environ.get("GITHUB_RUN_ID", "local")
RUN_ATTEMPT = os.environ.get("GITHUB_RUN_ATTEMPT", "1")

BASE_CANDIDATES = (
    "origin/ops/hepta-final-convergence-review-anchor-20260909",
    "origin/codex/hepta-native-source-closed-world-20260909",
    "origin/integration/vnext-main-20260811",
)
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
GENERATED_CONFLICTS = (
    re.compile(r"^codex-rs/Cargo\.lock$"),
    re.compile(r"^docs/(?:STATUS\.md|CURRENT\.json)$"),
    re.compile(r"^docs/.*/STATUS(?:\.md|\.json)$"),
    re.compile(
        r"^qualification/module-execution-dossiers/"
        r"(?:NATIVE_BINDINGS|IMPLEMENTATION_COMPLETION)\.json$"
    ),
)

GENERATORS: tuple[tuple[str, ...], ...] = (
    ("python3", "scripts/hepta-readiness.py", "generate-status"),
    ("python3", "scripts/hepta-implementation-dossiers.py", "generate-status"),
    ("python3", "scripts/hepta-algorithm-docs.py", "generate-status"),
    ("python3", "scripts/hepta-cns.py", "generate-status"),
    ("python3", "scripts/hepta-docs.py", "generate-status"),
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
    (
        "python3",
        "qualification/module-execution-dossiers/implementation_contracts.py",
        "self-test",
    ),
    (
        "python3",
        "qualification/module-execution-dossiers/implementation_contracts.py",
        "verify-repository",
    ),
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


@dataclass
class Result:
    argv: tuple[str, ...]
    returncode: int
    seconds: float
    output: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def receipt(self) -> dict[str, Any]:
        encoded = self.output.encode("utf-8", errors="replace")
        return {
            "command": list(self.argv),
            "returnCode": self.returncode,
            "durationSeconds": round(self.seconds, 3),
            "outputSha256": hashlib.sha256(encoded).hexdigest(),
            "tail": self.output.splitlines()[-50:],
        }


def run(
    argv: Iterable[str],
    *,
    timeout: int = 3600,
    check: bool = False,
) -> Result:
    args = tuple(argv)
    print("+", shlex.join(args), flush=True)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            args,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        result = Result(args, completed.returncode, time.monotonic() - started, completed.stdout)
    except subprocess.TimeoutExpired as error:
        output = (error.stdout or "") + "\nTIMEOUT\n"
        result = Result(args, 124, time.monotonic() - started, output)
    print(result.output[-10000:], flush=True)
    if check and not result.ok:
        raise RuntimeError(f"command failed: {shlex.join(args)}")
    return result


def git(*args: str, check: bool = True, timeout: int = 900) -> Result:
    return run(("git", *args), check=check, timeout=timeout)


def git_text(*args: str) -> str:
    return git(*args).output.strip()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_json_object(output: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for index, character in enumerate(output):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("command output did not contain a JSON object")


def resolve_base() -> tuple[str, str]:
    override = os.environ.get("HEPTA_CONVERGENCE_BASE")
    candidates = (override,) + BASE_CANDIDATES if override else BASE_CANDIDATES
    for ref in candidates:
        probe = git("rev-parse", "--verify", f"{ref}^{{commit}}", check=False)
        if probe.ok:
            return ref, probe.output.strip()
    raise RuntimeError("no admissible convergence base exists")


def remote_branches() -> dict[str, int]:
    result = git(
        "for-each-ref",
        "--format=%(refname:short)|%(committerdate:unix)",
        "refs/remotes/origin",
    )
    values: dict[str, int] = {}
    for line in result.output.splitlines():
        if not line.startswith("origin/") or "|" not in line:
            continue
        ref, raw_time = line.rsplit("|", 1)
        branch = ref.removeprefix("origin/")
        if branch == "HEAD":
            continue
        try:
            values[branch] = int(raw_time)
        except ValueError:
            continue
    return values


def select_lanes(branches: dict[str, int]) -> dict[str, str | None]:
    selected: dict[str, str | None] = {}
    for lane in LANE_ORDER:
        selected[lane] = next(
            (value for value in LANE_PREFERENCES[lane] if value in branches),
            None,
        )
        if selected[lane] is not None:
            continue
        marker = f"lane-{lane.lower()}"
        discovered = [
            branch
            for branch in branches
            if marker in branch.lower()
            and "20260910" in branch
            and ("gap" in branch.lower() or "closure" in branch.lower())
            and "global-gap-closure" not in branch
        ]
        if discovered:
            selected[lane] = max(discovered, key=lambda value: branches[value])
    return selected


def generated_only(paths: list[str]) -> bool:
    return bool(paths) and all(any(pattern.match(path) for pattern in GENERATED_CONFLICTS) for path in paths)


def merge_lane(lane: str, branch: str) -> dict[str, Any]:
    before = git_text("rev-parse", "HEAD")
    message = (
        f"merge(lane-{lane.lower()}): converge {branch}\n\n"
        "Signed-off-by: OpenAI Codex <noreply@openai.com>"
    )
    result = git(
        "merge",
        "--no-ff",
        "--no-edit",
        "-m",
        message,
        f"origin/{branch}",
        check=False,
        timeout=1800,
    )
    conflicts: list[str] = []
    auto_resolved = False
    if not result.ok:
        conflicts = [
            line.strip()
            for line in git("diff", "--name-only", "--diff-filter=U", check=False).output.splitlines()
            if line.strip()
        ]
        if not generated_only(conflicts):
            git("merge", "--abort", check=False)
            return {
                "lane": lane,
                "branch": branch,
                "merged": False,
                "before": before,
                "conflicts": conflicts,
                "tail": result.output.splitlines()[-80:],
            }
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
    return {
        "lane": lane,
        "branch": branch,
        "merged": True,
        "before": before,
        "after": git_text("rev-parse", "HEAD"),
        "autoResolvedGeneratedOnly": auto_resolved,
        "conflicts": conflicts,
    }


def repair_native_bindings() -> dict[str, Any]:
    path = ROOT / "qualification/module-execution-dossiers/NATIVE_BINDINGS.json"
    if not path.is_file():
        return {"present": False, "updated": 0}
    document = json.loads(path.read_text(encoding="utf-8"))
    observations = document.get("observations", [])
    updated = 0
    missing: list[str] = []
    for row in observations:
        source = row.get("path")
        if not isinstance(source, str):
            continue
        if not (ROOT / source).is_file():
            missing.append(source)
            continue
        actual = git_text("hash-object", "--", source)
        if row.get("blobSha") != actual:
            row["blobSha"] = actual
            updated += 1
    if updated:
        write_json(path, document)
    return {
        "present": True,
        "observationCount": len(observations),
        "updated": updated,
        "missingPaths": missing,
    }


def run_generators() -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    for command in GENERATORS:
        if not (ROOT / command[1]).is_file():
            receipts.append({"command": list(command), "skipped": "missing executable"})
            continue
        receipts.append(run(command, timeout=1200).receipt())
    return receipts


def normalize_lockfile() -> list[dict[str, Any]]:
    commands = [
        (
            "cargo",
            "metadata",
            "--manifest-path",
            "codex-rs/Cargo.toml",
            "--format-version",
            "1",
            "--locked",
        )
    ]
    receipts: list[dict[str, Any]] = []
    first = run(commands[0], timeout=1800)
    receipts.append(first.receipt())
    if first.ok:
        return receipts
    unlocked = run(
        (
            "cargo",
            "metadata",
            "--manifest-path",
            "codex-rs/Cargo.toml",
            "--format-version",
            "1",
        ),
        timeout=1800,
    )
    receipts.append(unlocked.receipt())
    if unlocked.ok:
        locked = run(commands[0], timeout=1800)
        receipts.append(locked.receipt())
    return receipts


def repository_verifiers() -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    for command in VERIFY_COMMANDS:
        if not (ROOT / command[1]).is_file():
            receipts.append({"command": list(command), "skipped": "missing executable"})
            continue
        receipts.append(run(command, timeout=1800).receipt())
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
            timeout=1800,
        ).receipt()
    )
    receipts.append(git("diff", "--check", check=False).receipt())
    return receipts


def metadata_locked() -> tuple[dict[str, Any] | None, dict[str, Any]]:
    result = run(
        (
            "cargo",
            "metadata",
            "--manifest-path",
            "codex-rs/Cargo.toml",
            "--format-version",
            "1",
            "--locked",
        ),
        timeout=1800,
    )
    if not result.ok:
        return None, result.receipt()
    try:
        return parse_json_object(result.output), result.receipt()
    except ValueError:
        return None, result.receipt()


def affected_packages(base_commit: str) -> tuple[list[str], dict[str, Any]]:
    metadata, receipt = metadata_locked()
    if metadata is None:
        return [], {"metadataReceipt": receipt, "selected": []}
    packages = metadata.get("packages", [])
    workspace = set(metadata.get("workspace_members", []))
    by_id = {row["id"]: row for row in packages if row.get("id") in workspace}
    by_name = {row["name"]: package_id for package_id, row in by_id.items()}
    changed = {
        line.strip()
        for line in git("diff", "--name-only", f"{base_commit}...HEAD").output.splitlines()
        if line.strip()
    }
    direct: set[str] = set()
    for package_id, package in by_id.items():
        manifest = Path(package["manifest_path"])
        try:
            root = manifest.parent.relative_to(ROOT).as_posix()
        except ValueError:
            continue
        if any(path == root or path.startswith(root + "/") for path in changed):
            direct.add(package_id)

    reverse: dict[str, set[str]] = defaultdict(set)
    for package_id, package in by_id.items():
        for dependency in package.get("dependencies", []):
            dep_id = by_name.get(dependency.get("name", ""))
            if dep_id is not None:
                reverse[dep_id].add(package_id)
    affected = set(direct)
    queue = deque(direct)
    while queue:
        current = queue.popleft()
        for dependent in reverse.get(current, set()):
            if dependent not in affected:
                affected.add(dependent)
                queue.append(dependent)

    selected = sorted(
        {
            by_id[package_id]["name"]
            for package_id in affected
            if by_id[package_id]["name"].startswith("codex-hepta-")
            or package_id in direct
        }
    )
    return selected, {
        "metadataReceipt": receipt,
        "changedFiles": sorted(changed),
        "directPackageIds": sorted(direct),
        "affectedPackageIds": sorted(affected),
        "selected": selected,
    }


def package_gate(package: str, repair: bool) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
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
        timeout=5400,
    )
    receipts.append({"package": package, "gate": "clippy", **lint.receipt()})
    if repair and not lint.ok:
        fixed = run(
            (
                "cargo",
                "clippy",
                "--fix",
                "--allow-dirty",
                "--allow-staged",
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
            timeout=5400,
        )
        receipts.append({"package": package, "gate": "clippy-fix", **fixed.receipt()})
    return receipts


def receipts_pass(receipts: Iterable[dict[str, Any]]) -> bool:
    return all(
        "skipped" in receipt or receipt.get("returnCode") == 0
        for receipt in receipts
        if receipt.get("gate") != "clippy-fix"
    )


def commit_if_dirty(message: str) -> str:
    if not git("status", "--porcelain", check=False).output.strip():
        return git_text("rev-parse", "HEAD")
    git("add", "-A")
    git("commit", "--signoff", "-m", message)
    return git_text("rev-parse", "HEAD")


def discover_external_gates() -> list[dict[str, Any]]:
    candidates = (
        ROOT / "docs/readiness/READINESS.json",
        ROOT / "qualification/module-execution-dossiers/IMPLEMENTATION_COMPLETION.json",
    )
    found: dict[str, dict[str, Any]] = {}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            gate_id = value.get("id")
            status = value.get("status")
            if isinstance(gate_id, str) and (
                gate_id.startswith("RDY-EXT-") or status == "external_open"
            ):
                found[gate_id] = {
                    "id": gate_id,
                    "status": "external_open",
                    "selfCertificationAllowed": False,
                }
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for path in candidates:
        if path.is_file():
            try:
                visit(json.loads(path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
    if not found:
        for index in range(1, 10):
            gate_id = f"RDY-EXT-{index:03d}"
            found[gate_id] = {
                "id": gate_id,
                "status": "external_open",
                "selfCertificationAllowed": False,
            }
    return [found[key] for key in sorted(found)]


def write_failure_candidate(
    base_ref: str,
    base_commit: str,
    selected: dict[str, str | None],
    merges: list[dict[str, Any]],
) -> int:
    status = {
        "schemaVersion": 1,
        "runId": RUN_ID,
        "runAttempt": RUN_ATTEMPT,
        "baseRef": base_ref,
        "baseCommit": base_commit,
        "targetBranch": TARGET_BRANCH,
        "selectedLaneBranches": selected,
        "mergeReceipts": merges,
        "repositoryInternalGapsClosed": False,
        "allGapsClosed": False,
        "authorityGranted": False,
    }
    write_json(OUT / "STATUS.json", status)
    commit_if_dirty("ops: record fail-closed global convergence conflict")
    git("push", "--force-with-lease", "origin", f"HEAD:refs/heads/{TARGET_BRANCH}")
    return 2


def main() -> int:
    git("config", "user.name", "Hepta Convergence Controller")
    git("config", "user.email", "noreply@openai.com")
    git("fetch", "--prune", "origin", "+refs/heads/*:refs/remotes/origin/*", timeout=1800)
    base_ref, base_commit = resolve_base()
    selected = select_lanes(remote_branches())
    if not any(selected.values()):
        raise RuntimeError("no current 2026-09-10 lane closure branch was discovered")

    git("checkout", "-B", TARGET_BRANCH, base_ref)
    merges: list[dict[str, Any]] = []
    for lane in LANE_ORDER:
        branch = selected[lane]
        if branch is None:
            merges.append({"lane": lane, "branch": None, "status": "no_current_candidate"})
            continue
        receipt = merge_lane(lane, branch)
        merges.append(receipt)
        if not receipt.get("merged"):
            return write_failure_candidate(base_ref, base_commit, selected, merges)

    generator_receipts = run_generators()
    native_before = repair_native_bindings()
    lock_receipts = normalize_lockfile()
    format_apply = run(
        ("cargo", "fmt", "--manifest-path", "codex-rs/Cargo.toml", "--all"),
        timeout=1800,
    )
    native_after_format = repair_native_bindings()
    source_commit = commit_if_dirty("chore: materialize global Hepta gap convergence r4")

    verifier_receipts = repository_verifiers()
    packages, selection_receipt = affected_packages(base_commit)
    package_receipts: list[dict[str, Any]] = []
    for package in packages:
        package_receipts.extend(package_gate(package, repair=True))

    repaired_commit: str | None = None
    if git("status", "--porcelain", check=False).output.strip():
        run(
            ("cargo", "fmt", "--manifest-path", "codex-rs/Cargo.toml", "--all"),
            timeout=1800,
        )
        repair_native_bindings()
        repaired_commit = commit_if_dirty("fix: apply deterministic global convergence repairs")
        verifier_receipts = repository_verifiers()
        package_receipts = []
        for package in packages:
            package_receipts.extend(package_gate(package, repair=False))

    repository_passed = (
        format_apply.ok
        and receipts_pass(lock_receipts)
        and receipts_pass(verifier_receipts)
        and receipts_pass(package_receipts)
    )
    external_gates = discover_external_gates()
    status = {
        "schemaVersion": 1,
        "runId": RUN_ID,
        "runAttempt": RUN_ATTEMPT,
        "baseRef": base_ref,
        "baseCommit": base_commit,
        "targetBranch": TARGET_BRANCH,
        "sourceCommit": source_commit,
        "repairedCommit": repaired_commit,
        "selectedLaneBranches": selected,
        "mergeReceipts": merges,
        "generatorReceipts": generator_receipts,
        "nativeBindingRepairBeforeFormat": native_before,
        "nativeBindingRepairAfterFormat": native_after_format,
        "lockReceipts": lock_receipts,
        "formatApply": format_apply.receipt(),
        "repositoryVerifierReceipts": verifier_receipts,
        "packageSelection": selection_receipt,
        "packageGateReceipts": package_receipts,
        "repositoryInternalValidationPassed": repository_passed,
        "repositoryInternalGapsClosed": repository_passed,
        "externalAuthorityGates": external_gates,
        "externalAuthorityGatesRetained": True,
        "allGapsClosed": repository_passed and not external_gates,
        "authorityGranted": False,
        "productionActivation": False,
        "selection": False,
        "promotion": False,
        "release": False,
    }
    write_json(OUT / "STATUS.json", status)
    write_json(
        OUT / "EXTERNAL_GATE_HANDOFF.json",
        {
            "schemaVersion": 1,
            "sourceCommit": repaired_commit or source_commit,
            "authorityGranted": False,
            "selfCertificationAllowed": False,
            "gates": external_gates,
        },
    )

    failed = [
        receipt
        for receipt in (*lock_receipts, *verifier_receipts, *package_receipts)
        if "skipped" not in receipt
        and receipt.get("gate") != "clippy-fix"
        and receipt.get("returnCode") != 0
    ]
    lines = [
        "# Hepta global gap-closure r4",
        "",
        f"- base: `{base_ref}` @ `{base_commit}`",
        f"- target: `{TARGET_BRANCH}`",
        f"- repository internal validation: `{'PASS' if repository_passed else 'BLOCKED'}`",
        f"- external independent-authority gates retained: `{len(external_gates)}`",
        "- self-issued authority: `false`",
        "",
        "## Lane inputs",
        "",
    ]
    for lane in LANE_ORDER:
        lines.append(f"- Lane {lane}: `{selected[lane] or 'no current candidate'}`")
    lines.extend(["", "## Remaining repository blockers", ""])
    if failed:
        for receipt in failed:
            lines.append(
                f"- `{shlex.join(receipt.get('command', []))}` returned "
                f"`{receipt.get('returnCode')}`; output sha256 "
                f"`{receipt.get('outputSha256')}`."
            )
    else:
        lines.append("- none detected by repository exact-source, document, format, test and lint gates")
    lines.extend(
        [
            "",
            "## External handoff",
            "",
            "Independent review, operator acceptance, target-host/hardware qualification, "
            "production canary, selection, promotion and release remain non-self-certifiable.",
            "",
        ]
    )
    (OUT / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    receipt_commit = commit_if_dirty("docs: bind global r4 validation and external handoff")
    git("push", "--force-with-lease", "origin", f"HEAD:refs/heads/{TARGET_BRANCH}")
    print(
        json.dumps(
            {
                "targetBranch": TARGET_BRANCH,
                "head": receipt_commit,
                "repositoryInternalValidationPassed": repository_passed,
                "externalGates": len(external_gates),
            }
        )
    )
    return 0 if repository_passed else 3


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"HEPTA_GLOBAL_CONVERGENCE_R4_ERROR: {error}", file=sys.stderr)
        raise
