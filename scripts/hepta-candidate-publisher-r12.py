#!/usr/bin/env python3
"""Publish one canonical internal candidate from a stable r11 seal."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable

ROOT = Path.cwd()
SOURCE_REF = os.environ.get(
    "HEPTA_SEALED_SOURCE",
    "origin/integration/hepta-all-gap-closure-20260910-sealed-r11",
)
TARGET = os.environ.get(
    "HEPTA_CANONICAL_CANDIDATE",
    "candidate/hepta-all-gap-closure-final-20260910",
)
SEAL_STATUS = "qualification/global-gap-closure-seal-r11/STATUS.json"
OUT = ROOT / "qualification" / "global-gap-closure-final-candidate"
PUBLICATION_BASE_REF = os.environ.get(
    "HEPTA_PUBLICATION_BASE",
    "origin/ops/hepta-final-convergence-review-anchor-20260909",
)
EXPECTED_R8_REF = "origin/integration/hepta-all-gap-closure-20260910-r8"
EXPECTED_R9_REF = "origin/integration/hepta-all-gap-closure-20260910-r9"
EXPECTED_R8_STATUS = "qualification/global-gap-closure-final-r8/STATUS.json"
EXPECTED_R9_STATUS = "qualification/global-gap-closure-final-r9/STATUS.json"
TEMPORARY_MUTATION_PATHS = (
    ".github/workflows/hepta-candidate-publisher-r12.yml",
    ".github/workflows/hepta-fixed-point-sealer-r10.yml",
    ".github/workflows/hepta-fixed-point-sealer-r11.yml",
    ".github/workflows/hepta-global-finalizer-r6.yml",
    ".github/workflows/hepta-global-finalizer-r7.yml",
    ".github/workflows/hepta-global-finalizer-r8.yml",
    ".github/workflows/hepta-global-finalizer-r9.yml",
    ".github/workflows/hepta-global-gap-closure-controller-r2.yml",
    ".github/workflows/hepta-global-gap-closure-controller-r3.yml",
    ".github/workflows/hepta-global-gap-closure-controller-r4.yml",
    ".github/workflows/hepta-global-gap-closure-controller.yml",
    ".github/workflows/tmp-hepta-controller-remediation.yml",
    ".github/workflows/tmp-hepta-r13-chain-patcher.yml",
    ".github/workflows/tmp-hepta-r13-patcher-fixer.yml",
    "scripts/apply-hepta-remaining-blocker-remediation.sh",
    "scripts/hepta-candidate-publisher-r12.py",
    "scripts/hepta-fixed-point-sealer-r10.py",
    "scripts/hepta-fixed-point-sealer-r11.py",
    "scripts/hepta-global-finalizer-r6.py",
    "scripts/hepta-global-finalizer-r7.py",
    "scripts/hepta-global-finalizer-r8-fixed.py",
    "scripts/hepta-global-finalizer-r8.py",
    "scripts/hepta-global-gap-closure-r4.py",
    "scripts/hepta-global-gap-closure.py",
)


def run(argv: Iterable[str], *, check: bool = True, timeout: int = 1800) -> str:
    args = tuple(argv)
    print("+", shlex.join(args), flush=True)
    completed = subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    print(completed.stdout[-12000:], flush=True)
    if check and completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {shlex.join(args)}"
        )
    return completed.stdout.strip()


def git(*args: str, check: bool = True, timeout: int = 1800) -> str:
    return run(("git", *args), check=check, timeout=timeout)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def wait_for_stable_seal() -> tuple[str, dict[str, Any]]:
    for _ in range(2160):
        git(
            "fetch",
            "--prune",
            "origin",
            "+refs/heads/*:refs/remotes/origin/*",
            check=False,
        )
        source = git("rev-parse", "--verify", f"{SOURCE_REF}^{{commit}}", check=False)
        if not source:
            time.sleep(10)
            continue
        raw = git("show", f"{SOURCE_REF}:{SEAL_STATUS}", check=False)
        try:
            status = json.loads(raw)
        except json.JSONDecodeError:
            time.sleep(10)
            continue
        if not isinstance(status, dict):
            time.sleep(10)
            continue
        if (
            status.get("r8Ref") != EXPECTED_R8_REF
            or status.get("r9Ref") != EXPECTED_R9_REF
            or status.get("r8StatusPath") != EXPECTED_R8_STATUS
            or status.get("r9StatusPath") != EXPECTED_R9_STATUS
        ):
            time.sleep(10)
            continue
        try:
            validate(status)
        except RuntimeError:
            time.sleep(10)
            continue
        return source, status
    raise RuntimeError("publishable stable r11 seal did not appear")


def validate(status: dict[str, Any]) -> None:
    required_true = (
        "fixedPointStable",
        "repositoryInternalValidationPassed",
        "repositoryInternalGapsClosed",
        "r8InternalPassed",
        "r9InternalPassed",
    )
    required_false = (
        "authorityGranted",
        "productionActivation",
        "modelInvocationAuthority",
        "providerDispatchAuthority",
        "productionWriterAuthorityAdded",
        "selection",
        "promotion",
        "release",
    )
    missing_true = [key for key in required_true if status.get(key) is not True]
    missing_false = [key for key in required_false if status.get(key) is not False]
    if missing_true or missing_false or status.get("driftPaths") not in ([], None):
        raise RuntimeError(
            f"seal is not publishable: missing_true={missing_true} "
            f"missing_false={missing_false} drift={status.get('driftPaths')}"
        )


def commit_if_dirty(message: str) -> str:
    if not git("status", "--porcelain", check=False):
        return git("rev-parse", "HEAD")
    git("add", "-A")
    git("commit", "--signoff", "-m", message)
    return git("rev-parse", "HEAD")


def remove_temporary_mutation_carriers() -> None:
    git("rm", "-f", "--ignore-unmatch", "--", *TEMPORARY_MUTATION_PATHS)
    survivors = [path for path in TEMPORARY_MUTATION_PATHS if (ROOT / path).exists()]
    if survivors:
        raise RuntimeError(f"temporary mutation carriers survived cleanup: {survivors}")


def assert_no_candidate_mutation_workflows(publication_base: str) -> None:
    changed = git(
        "diff",
        "--name-only",
        publication_base,
        "--",
        ".github/workflows",
        check=False,
    ).splitlines()
    violations: list[str] = []
    for path in sorted(set(changed)):
        candidate = ROOT / path
        if not candidate.is_file() or candidate.suffix not in {".yml", ".yaml"}:
            continue
        source = candidate.read_text(encoding="utf-8", errors="replace").lower()
        if (
            "contents: write" in source
            or "pull-requests: write" in source
            or "persist-credentials: true" in source
        ):
            violations.append(path)
    if violations:
        raise RuntimeError(
            f"candidate-controlled mutation workflows remain: {violations}"
        )


def publish_as_direct_child(staged_commit: str) -> tuple[str, str]:
    publication_base = git(
        "rev-parse",
        "--verify",
        f"{PUBLICATION_BASE_REF}^{{commit}}",
    )
    candidate_tree = git("rev-parse", f"{staged_commit}^{{tree}}")
    candidate_commit = git(
        "commit-tree",
        candidate_tree,
        "-p",
        publication_base,
        "-m",
        "fix(hepta): publish exact single-parent all-lanes blocker closure",
        "-m",
        "Signed-off-by: Hepta Canonical Candidate Publisher <noreply@openai.com>",
    )
    git("reset", "--hard", candidate_commit)
    parents = git("show", "-s", "--format=%P", candidate_commit).split()
    if parents != [publication_base]:
        raise RuntimeError(
            f"candidate parent mismatch: expected {[publication_base]}, got {parents}"
        )
    return candidate_commit, publication_base


def main() -> int:
    git("config", "user.name", "Hepta Canonical Candidate Publisher")
    git("config", "user.email", "noreply@openai.com")
    seal_commit, seal_status = wait_for_stable_seal()
    validate(seal_status)
    git("checkout", "-B", TARGET, SOURCE_REF)
    publication = {
        "schemaVersion": 1,
        "sourceRef": SOURCE_REF,
        "sourceSealCommit": seal_commit,
        "sourceQualifiedCommit": seal_status.get("r9QualifiedSource"),
        "filteredSurfaceSha256": seal_status.get("r9FilteredSurfaceSha256"),
        "targetBranch": TARGET,
        "repositoryInternalValidationPassed": True,
        "repositoryInternalGapsClosed": True,
        "fixedPointStable": True,
        "candidatePublished": True,
        "externalAuthorityGatesRetained": True,
        "allGapsClosed": False,
        "authorityGranted": False,
        "productionActivation": False,
        "modelInvocationAuthority": False,
        "providerDispatchAuthority": False,
        "productionWriterAuthorityAdded": False,
        "selection": False,
        "promotion": False,
        "release": False,
    }
    write_json(OUT / "STATUS.json", publication)
    write_json(
        OUT / "EXTERNAL_GATE_HANDOFF.json",
        {
            "schemaVersion": 1,
            "candidateCommit": seal_commit,
            "selfCertificationAllowed": False,
            "authorityGranted": False,
            "gates": [
                {
                    "id": f"RDY-EXT-{index:03d}",
                    "status": "external_open",
                    "selfCertificationAllowed": False,
                }
                for index in range(1, 10)
            ],
        },
    )
    (OUT / "REPORT.md").write_text(
        "\n".join(
            [
                "# Hepta canonical internal candidate",
                "",
                f"- sealed source ref: `{SOURCE_REF}`",
                f"- sealed source commit: `{seal_commit}`",
                f"- qualified source commit: `{seal_status.get('r9QualifiedSource')}`",
                f"- filtered surface sha256: `{seal_status.get('r9FilteredSurfaceSha256')}`",
                "- repository-internal fixed point: `PASS`",
                "- production activation: `false`",
                "- external independent-authority gates: `retained open`",
                "",
                "This ref is the single canonical integration candidate. It is not a production "
                "release and grants no model/provider, writer, selection, promotion, or release authority.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    publication_base = git(
        "rev-parse",
        "--verify",
        f"{PUBLICATION_BASE_REF}^{{commit}}",
    )
    remove_temporary_mutation_carriers()
    assert_no_candidate_mutation_workflows(publication_base)
    staged_commit = commit_if_dirty(
        "docs: publish canonical all-Hepta internal candidate r12"
    )
    candidate_commit, publication_base = publish_as_direct_child(staged_commit)
    git("push", "--force-with-lease", "origin", f"HEAD:refs/heads/{TARGET}")
    print(
        json.dumps(
            {
                "targetBranch": TARGET,
                "candidateCommit": candidate_commit,
                "publicationBase": publication_base,
                "directParentVerified": True,
                "temporaryMutationCarriersPresent": False,
                "fixedPointStable": True,
                "repositoryInternalGapsClosed": True,
            }
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"HEPTA_CANDIDATE_PUBLISHER_R12_ERROR: {error}", file=sys.stderr)
        raise
