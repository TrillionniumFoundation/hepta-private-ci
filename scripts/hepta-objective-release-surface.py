#!/usr/bin/env python3
"""Fail closed when objective.compiler qualification can author repository source.

The objective qualification and release surface may create local synthetic commits,
format temporary worktrees, and upload immutable artifacts. It must never obtain a
repository-writing token, retain checkout credentials, or commit/push source.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = Path(".github/workflows")

# These one-shot authoring paths were used to materialize the closeout candidate.
# Keeping the names forbidden prevents them from quietly returning as a second
# implementation or evidence path.
RETIRED_AUTHORING_PATHS = (
    Path(".github/workflows/hepta-objective-production-convergence.yml"),
    Path(".github/workflows/hepta-objective-source-materialize-race.yml"),
    Path("scripts/hepta-objective-materialize-closure.py"),
    Path(".github/workflows/objective-source-snapshot-temporary.yml"),
)

_WRITE_PERMISSION = re.compile(
    r"(?mi)^\s*(?:contents\s*:\s*write|permissions\s*:\s*write-all)\s*(?:#.*)?$"
)
_PERSIST_CREDENTIALS = re.compile(
    r"""(?mix)
    ^\s*persist-credentials\s*:\s*
    (?:
        true
        | ['"]true['"]
    )
    \s*(?:\#.*)?$
    """
)
_REMOTE_AUTHORING_COMMANDS = (
    (
        "git push",
        re.compile(r"(?mi)^\s*(?:run:\s*)?(?:sudo\s+)?git\s+push(?:\s|$)"),
    ),
    (
        "git commit",
        re.compile(r"(?mi)^\s*(?:run:\s*)?(?:sudo\s+)?git\s+commit(?:\s|$)"),
    ),
    (
        "git add",
        re.compile(r"(?mi)^\s*(?:run:\s*)?(?:sudo\s+)?git\s+add(?:\s|$)"),
    ),
    (
        "git rm",
        re.compile(r"(?mi)^\s*(?:run:\s*)?(?:sudo\s+)?git\s+rm(?:\s|$)"),
    ),
)
_EXPLICIT_NO_CREDENTIALS = re.compile(
    r"""(?mix)
    ^\s*persist-credentials\s*:\s*
    (?:
        false
        | ['"]false['"]
    )
    \s*(?:\#.*)?$
    """
)


class ReleaseSurfaceError(ValueError):
    """Raised when the objective release surface can mutate repository source."""


def objective_workflows(root: Path) -> list[Path]:
    workflow_root = root / WORKFLOW_DIR
    if not workflow_root.is_dir():
        raise ReleaseSurfaceError(f"missing workflow directory: {workflow_root}")
    return sorted(
        {
            *workflow_root.glob("*objective*.yml"),
            *workflow_root.glob("*objective*.yaml"),
        }
    )


def _has_explicit_read_only_permissions(text: str) -> bool:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line == "permissions:":
            cursor = index + 1
            while cursor < len(lines):
                candidate = lines[cursor]
                if candidate and not candidate.startswith((" ", "\t")):
                    break
                if re.fullmatch(
                    r"\s+contents\s*:\s*read\s*(?:#.*)?", candidate
                ):
                    return True
                cursor += 1
        if re.fullmatch(
            r"permissions\s*:\s*\{[^}]*\bcontents\s*:\s*read\b[^}]*\}\s*",
            line,
        ):
            return True
    return False


def _checkout_blocks(text: str) -> list[tuple[int, str]]:
    lines = text.splitlines(keepends=True)
    blocks: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        uses = re.match(
            r"^(?P<indent>\s*)(?P<dash>-\s+)?uses:\s*actions/checkout@", line
        )
        if uses is None:
            continue

        uses_indent = len(uses.group("indent"))
        if uses.group("dash") is not None:
            step_start = index
            step_indent = uses_indent
        else:
            step_start = index
            step_indent = -1
            for candidate_index in range(index - 1, -1, -1):
                candidate = re.match(
                    r"^(?P<indent>\s*)-\s+", lines[candidate_index]
                )
                if candidate is None:
                    continue
                candidate_indent = len(candidate.group("indent"))
                if candidate_indent < uses_indent:
                    step_start = candidate_index
                    step_indent = candidate_indent
                    break
            if step_indent < 0:
                blocks.append((index + 1, line))
                continue

        block = lines[step_start : index + 1]
        cursor = index + 1
        while cursor < len(lines):
            candidate = re.match(r"^(?P<indent>\s*)-\s+", lines[cursor])
            if (
                candidate is not None
                and len(candidate.group("indent")) <= step_indent
            ):
                break
            block.append(lines[cursor])
            cursor += 1
        blocks.append((index + 1, "".join(block)))
    return blocks


def verify_release_surface(root: Path = ROOT) -> dict[str, object]:
    root = root.resolve()
    violations: list[str] = []

    for relative in RETIRED_AUTHORING_PATHS:
        if (root / relative).exists():
            violations.append(f"retired objective authoring path exists: {relative}")

    workflows = objective_workflows(root)
    if not workflows:
        violations.append("no objective workflows found")

    for workflow in workflows:
        relative = workflow.relative_to(root)
        try:
            text = workflow.read_text(encoding="utf-8")
        except OSError as error:
            violations.append(f"cannot read {relative}: {error}")
            continue

        if not _has_explicit_read_only_permissions(text):
            violations.append(
                f"{relative}: objective workflow must declare top-level contents: read"
            )
        if _WRITE_PERMISSION.search(text):
            violations.append(f"{relative}: repository write permission is forbidden")
        if _PERSIST_CREDENTIALS.search(text):
            violations.append(f"{relative}: checkout credentials may not be retained")

        for line, block in _checkout_blocks(text):
            if _EXPLICIT_NO_CREDENTIALS.search(block) is None:
                violations.append(
                    f"{relative}:{line}: actions/checkout must set "
                    "persist-credentials: false"
                )

        for label, pattern in _REMOTE_AUTHORING_COMMANDS:
            if pattern.search(text):
                violations.append(
                    f"{relative}: repository-authoring command is forbidden: {label}"
                )

    if violations:
        raise ReleaseSurfaceError("; ".join(violations))

    return {
        "schema": "hepta.objective-release-surface.v1",
        "module": "objective.compiler",
        "workflowsChecked": [str(path.relative_to(root)) for path in workflows],
        "retiredAuthoringPathsAbsent": True,
        "repositoryWritePermissionsAbsent": True,
        "checkoutCredentialsRetained": False,
        "repositoryAuthoringCommandsAbsent": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify",))
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    try:
        result = verify_release_surface(args.root)
    except ReleaseSurfaceError as error:
        raise SystemExit(f"FAIL_HEPTA_OBJECTIVE_RELEASE_SURFACE: {error}") from error

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
