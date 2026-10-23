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
    Path(".github/workflows/hepta-objective-format-export.yml"),
    Path("scripts/hepta-objective-evidence-materialize.py"),
    Path(".github/workflows/hepta-objective-map-preview.yml"),
    Path(".github/workflows/hepta-objective-source-convergence-author.yml"),
    Path(".github/workflows/hepta-objective-source-convergence-preview.yml"),
    Path(".github/objective-preview/hepta-objective-source-convergence-preview.py.gz"),
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


def _scalar(value: str) -> str:
    """Read the static scalar subset used by permission and checkout inputs."""
    value = value.strip()
    if value.startswith('"'):
        try:
            parsed = json.loads(value)
        except ValueError as error:
            raise ReleaseSurfaceError("unsupported quoted YAML scalar") from error
        if not isinstance(parsed, str):
            raise ReleaseSurfaceError("YAML scalar must be a string")
        return parsed
    if value.startswith("'"):
        if len(value) < 2 or not value.endswith("'"):
            raise ReleaseSurfaceError("unterminated quoted YAML scalar")
        interior = value[1:-1]
        if "'" in interior.replace("''", ""):
            raise ReleaseSurfaceError("invalid single-quoted YAML scalar")
        return interior.replace("''", "'")
    if re.fullmatch(r"[A-Za-z0-9_./@-]+", value) is None:
        raise ReleaseSurfaceError("unsupported dynamic or compound YAML scalar")
    return value


def _parts(text: str, separator: str) -> list[str]:
    """Split flow-map tokens without treating quoted punctuation as structure."""
    pieces: list[str] = []
    start = 0
    quote = None
    cursor = 0
    while cursor < len(text):
        character = text[cursor]
        if quote == '"' and character == "\\":
            cursor += 2
            continue
        if quote == "'" and character == "'" and text[cursor : cursor + 2] == "''":
            cursor += 2
            continue
        if quote is not None:
            if character == quote:
                quote = None
        elif character in ("'", '"'):
            quote = character
        elif character == separator:
            pieces.append(text[start:cursor])
            start = cursor + 1
        cursor += 1
    if quote is not None:
        raise ReleaseSurfaceError("unterminated quoted YAML value")
    pieces.append(text[start:])
    return pieces


def _without_comment(text: str) -> str:
    pieces = _parts(text, "#")
    if len(pieces) == 1:
        return text.rstrip()
    prefix = pieces[0]
    if not prefix or prefix[-1].isspace():
        return prefix.rstrip()
    raise ReleaseSurfaceError("unsupported unquoted YAML '#' value")


def _entry(text: str) -> tuple[str, str]:
    parts = _parts(text, ":")
    if len(parts) < 2:
        raise ReleaseSurfaceError("unsupported workflow YAML mapping entry")
    return _scalar(parts[0]), ":".join(parts[1:]).strip()


def _rows(text: str) -> list[tuple[int, int, int, str, str, bool]]:
    """Read block mappings/steps and skip literal bodies; unsupported forms fail.

    This is deliberately a restricted workflow syntax reader, not a general
    YAML interpreter. Anchors, aliases, merge keys and flow-style jobs/steps
    would hide security-relevant structure, so qualification refuses them.
    """
    rows = []
    body_indent = None
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if body_indent is not None and indent > body_indent:
            continue
        body_indent = None
        if "\t" in line[: indent + 1]:
            raise ReleaseSurfaceError("tabs in workflow YAML structure are unsupported")
        content = _without_comment(line[indent:])
        if not content:
            continue
        step = content.startswith("- ")
        if step:
            content = content[2:].strip()
        if ":" not in content:
            if step:
                if content.startswith(("{", "&", "*")):
                    raise ReleaseSurfaceError(
                        "flow steps and YAML aliases are unsupported"
                    )
                continue
            raise ReleaseSurfaceError("unsupported workflow YAML structure")
        key, value = _entry(content)
        key_indent = indent + (2 if step else 0)
        if key == "<<" or value.startswith(("&", "*", "!")):
            raise ReleaseSurfaceError(
                "YAML anchors, aliases, tags and merge keys are unsupported"
            )
        if step and content.startswith("{"):
            raise ReleaseSurfaceError("flow steps are unsupported")
        if key in {"jobs", "steps"} and value:
            raise ReleaseSurfaceError(
                "jobs and steps must use block workflow structure"
            )
        rows.append((number, indent, key_indent, key, value, step))
        if re.fullmatch(r"[|>][+-]?[1-9]?", value):
            body_indent = key_indent
    return rows


def _mapping(
    rows: list[tuple[int, int, int, str, str, bool]],
    index: int,
    scalar_keys: set[str] | None = None,
) -> dict[str, str]:
    number, _indent, key_indent, _key, value, _step = rows[index]
    values: dict[str, str] = {}
    if value:
        if not (value.startswith("{") and value.endswith("}")):
            raise ReleaseSurfaceError(f"line {number}: static YAML mapping required")
        entries = _parts(value[1:-1], ",") if value[1:-1].strip() else []
        entries = [_entry(entry) for entry in entries]
    else:
        entries = []
        child_indent = None
        for row in rows[index + 1 :]:
            if row[1] <= key_indent:
                break
            if child_indent is None:
                child_indent = row[2]
            if row[2] != child_indent or row[5]:
                raise ReleaseSurfaceError(
                    f"line {number}: nested mapping is unsupported"
                )
            entries.append((row[3], row[4]))
    for key, raw in entries:
        key = key.lower()
        if key in values:
            raise ReleaseSurfaceError(
                f"line {number}: duplicate YAML mapping key {key}"
            )
        values[key] = _scalar(raw) if scalar_keys is None or key in scalar_keys else raw
    return values


def _verify_structure(text: str, target_host: bool = False) -> list[str]:
    violations: list[str] = []
    rows = _rows(text)
    top_permissions = []
    job_sections = [
        index for index, row in enumerate(rows) if row[2] == 0 and row[3] == "jobs"
    ]
    if len(job_sections) != 1:
        raise ReleaseSurfaceError("one block jobs mapping is required")
    for row in rows[job_sections[0] + 1 :]:
        if row[1] == 0:
            break
        if row[2] == 2 and (row[4] or row[5]):
            raise ReleaseSurfaceError("each job must use block workflow structure")
    for index, row in enumerate(rows):
        number, _indent, key_indent, key, value, _step = row
        if key == "permissions":
            if value == "write-all" or value in ('"write-all"', "'write-all'"):
                violations.append("repository write permission is forbidden")
                continue
            permissions = _mapping(rows, index)
            if permissions.get("contents") == "write":
                violations.append("repository write permission is forbidden")
            if any(
                level not in {"read", "write", "none"} for level in permissions.values()
            ):
                raise ReleaseSurfaceError(
                    f"line {number}: unsupported permission level"
                )
            if key_indent == 0:
                top_permissions.append(permissions)
                if any(level == "write" for level in permissions.values()):
                    violations.append("workflow-wide write permissions are forbidden")
            elif any(level == "write" for level in permissions.values()):
                parent_job = next(
                    (parent[3] for parent in reversed(rows[:index]) if parent[2] == 2),
                    None,
                )
                if not (
                    target_host and key_indent == 4 and parent_job == "attest-candidate"
                ):
                    violations.append(
                        "candidate execution job write permissions are forbidden"
                    )
                elif permissions != {
                    "contents": "read",
                    "id-token": "write",
                    "attestations": "write",
                }:
                    violations.append(
                        "attestation job permissions must be restricted to provenance"
                    )
        if key != "uses":
            continue
        action = _scalar(value)
        if not action.lower().startswith("actions/checkout@"):
            continue
        start = index
        while start >= 0 and not rows[start][5]:
            start -= 1
        if start < 0 or rows[start][2] != key_indent:
            raise ReleaseSurfaceError(
                f"line {number}: checkout must belong to one block step"
            )
        end = index + 1
        while end < len(rows) and rows[end][1] > rows[start][1]:
            end += 1
        with_rows = [
            cursor
            for cursor in range(start, end)
            if rows[cursor][3] == "with" and rows[cursor][2] == key_indent
        ]
        if len(with_rows) != 1:
            violations.append(
                f"line {number}: actions/checkout must set persist-credentials: false"
            )
            continue
        inputs = _mapping(rows, with_rows[0], {"persist-credentials"})
        credentials = inputs.get("persist-credentials")
        if credentials == "true":
            violations.append("checkout credentials may not be retained")
        if credentials != "false":
            violations.append(
                f"line {number}: actions/checkout must set persist-credentials: false"
            )
    if len(top_permissions) != 1 or top_permissions[0].get("contents") != "read":
        violations.append("objective workflow must declare top-level contents: read")
    if target_host:
        # Candidate build scripts and tests may execute arbitrary code. Their
        # jobs cannot receive attestation/OIDC permission through inheritance.
        for name in ("package-candidate", "target-host"):
            indices = [
                index
                for index, row in enumerate(rows)
                if row[2] == 2 and row[3] == name
            ]
            if len(indices) != 1:
                violations.append(f"candidate job {name} must be explicitly declared")
                continue
            start = indices[0]
            end = start + 1
            while end < len(rows) and rows[end][1] > 2:
                end += 1
            declarations = [
                index
                for index in range(start + 1, end)
                if rows[index][2] == 4 and rows[index][3] == "permissions"
            ]
            if len(declarations) != 1:
                violations.append(
                    f"candidate job {name} must declare explicit read-only permissions"
                )
                continue
            permissions = _mapping(rows, declarations[0])
            if permissions.get("contents") != "read" or any(
                level not in {"read", "none"} for level in permissions.values()
            ):
                violations.append(
                    f"candidate job {name} may not obtain any write permission"
                )
        attestation = [
            index
            for index, row in enumerate(rows)
            if row[2] == 2 and row[3] == "attest-candidate"
        ]
        if len(attestation) != 1:
            violations.append("one isolated attest-candidate job is required")
        else:
            start = attestation[0]
            end = start + 1
            while end < len(rows) and rows[end][1] > 2:
                end += 1
            actions = []
            for row in rows[start + 1 : end]:
                if row[3] == "run":
                    violations.append(
                        "attest-candidate cannot execute shell or candidate code"
                    )
                if row[3] == "uses":
                    action, separator, revision = _scalar(row[4]).partition("@")
                    if not separator or re.fullmatch(r"[0-9a-f]{40}", revision) is None:
                        violations.append(
                            "attest-candidate actions must be pinned immutable identities"
                        )
                    actions.append(action.lower())
            if actions != [
                "actions/download-artifact",
                "actions/attest-build-provenance",
            ]:
                violations.append(
                    "attest-candidate may only download inert data and attest provenance"
                )
    return violations


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

        try:
            violations.extend(
                f"{relative}: {message}"
                for message in _verify_structure(
                    text, workflow.stem == "hepta-objective-target-host"
                )
            )
        except ReleaseSurfaceError as error:
            violations.append(f"{relative}: {error}")

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
