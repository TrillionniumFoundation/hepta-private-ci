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
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def wait_for_stable_seal() -> tuple[str, dict[str, Any]]:
    for _ in range(720):
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
        return source, status
    raise RuntimeError("stable r11 seal did not appear")


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
    candidate_commit = commit_if_dirty(
        "docs: publish canonical all-Hepta internal candidate r12"
    )
    git("push", "--force-with-lease", "origin", f"HEAD:refs/heads/{TARGET}")
    print(
        json.dumps(
            {
                "targetBranch": TARGET,
                "candidateCommit": candidate_commit,
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
