#!/usr/bin/env python3
"""Fail closed when a memory.retrieval workflow can mutate source or execute a ref chosen by repository code."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

WORKFLOW_GLOB = "hepta-memory-retrieval-*.yml"
DENIED = {
    "pull_request_target event": re.compile(r"(?m)^\s*pull_request_target\s*:"),
    "repository write permission": re.compile(
        r"(?m)^\s*contents\s*:\s*write\s*(?:#.*)?$"
    ),
    "credential persistence": re.compile(
        r"(?m)^\s*persist-credentials\s*:\s*true\s*(?:#.*)?$"
    ),
    "git push": re.compile(r"(?m)\bgit\s+push\b"),
    "GitHub API mutation": re.compile(
        r"(?m)\bgh\s+api\b[^\n]*(?:-X|--method)\s*(?:POST|PUT|PATCH|DELETE)\b"
    ),
    "job output controls checkout ref": re.compile(
        r"(?m)^\s*ref\s*:\s*\$\{\{\s*needs\."
    ),
    "step output controls checkout ref": re.compile(
        r"(?m)^\s*ref\s*:\s*\$\{\{\s*steps\."
    ),
    "job output controls executable Git identity": re.compile(
        r"(?m)^\s*(?:SOURCE_SHA|BASE_SHA|MAIN_SHA|TESTED_SHA)\s*:\s*"
        r"\$\{\{\s*needs\."
    ),
    "candidate helper controls tested checkout": re.compile(
        r'(?s)\bTESTED_SHA="\$\(\s*python3\s+'
        r"scripts/hepta_memory_retrieval_candidate\.py\s+merge\b"
    ),
    "candidate helper publishes executable ref": re.compile(
        r"(?s)hepta_memory_retrieval_candidate\.py\s+refs\b"
        r".{0,600}\$GITHUB_OUTPUT"
    ),
}


class WorkflowPolicyError(ValueError):
    pass


def audit(root: Path) -> list[str]:
    directory = root / ".github/workflows"
    if not directory.is_dir():
        raise WorkflowPolicyError("workflow directory is missing")
    files = sorted(directory.glob(WORKFLOW_GLOB))
    if not files:
        raise WorkflowPolicyError("no memory.retrieval workflows found")
    violations: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for label, pattern in DENIED.items():
            if pattern.search(text):
                violations.append(f"{path.relative_to(root).as_posix()}: {label}")
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        violations = audit(args.root)
        if violations:
            raise WorkflowPolicyError("\n".join(violations))
        print("memory.retrieval workflows are read-only and use trusted checkout identities")
    except (WorkflowPolicyError, OSError, UnicodeError) as error:
        print(f"memory.retrieval workflow policy refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
