#!/usr/bin/env python3
"""Enforce the two-gate automatic Hepta CI entrypoint policy.

Only blocking-ci.yml and hepta-architecture-convergence.yml may subscribe to
pull_request or push for Hepta source qualification. Module- or lane-specific
workflows are retained as workflow_call/workflow_dispatch utilities, so they do
not create parallel required surfaces or duplicate every source change.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
AUTOMATIC_EVENTS = frozenset({"pull_request", "push", "merge_group"})
AGGREGATES = {
    "blocking-ci.yml": {"pull_request", "push"},
    "hepta-architecture-convergence.yml": {"pull_request", "push"},
}
SPECIAL_NAMES = (
    re.compile(r"^hepta-(?!architecture-convergence\.yml$).+\.ya?ml$"),
    re.compile(r"^automation-taskflow-focused\.ya?ml$"),
    re.compile(r"^hnmf-qualification\.ya?ml$"),
    re.compile(r"^intelligence-provider-qualification\.ya?ml$"),
    re.compile(r"^lane-a-foundation\.ya?ml$"),
    re.compile(r"^memory-federation-v2-final-verify\.ya?ml$"),
    re.compile(r"^openbao-compatibility\.ya?ml$"),
    re.compile(r"^runtime-supervisor-.+\.ya?ml$"),
    re.compile(r"^single-main-.+\.ya?ml$"),
    re.compile(r"^trillionnium-os-attestation-handoff-check\.ya?ml$"),
    re.compile(r"^v8-canary\.ya?ml$"),
)


def on_block(text: str) -> tuple[str, list[str]]:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("on:"):
            first = line[3:].strip()
            block: list[str] = []
            cursor = index + 1
            while cursor < len(lines):
                candidate = lines[cursor]
                if candidate and not candidate[0].isspace() and not candidate.lstrip().startswith("#"):
                    break
                block.append(candidate)
                cursor += 1
            return first, block
    raise ValueError("missing top-level on block")


def events(text: str) -> set[str]:
    first, block = on_block(text)
    result: set[str] = set()
    if first:
        if first.startswith("[") and first.endswith("]"):
            result.update(value.strip().strip("'\"") for value in first[1:-1].split(",") if value.strip())
        elif first not in {"{}", "null", "~"}:
            result.add(first.strip("'\""))
    for line in block:
        match = re.match(r"^  ([A-Za-z_][A-Za-z0-9_-]*):", line)
        if match:
            result.add(match.group(1))
    return result


def is_special(name: str) -> bool:
    return any(pattern.match(name) for pattern in SPECIAL_NAMES)


def verify(root: Path = ROOT) -> dict[str, object]:
    workflows = root / ".github/workflows"
    failures: list[str] = []
    observed: dict[str, list[str]] = {}
    for path in sorted(workflows.glob("*.y*ml")):
        try:
            current = events(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            failures.append(f"{path.name}: {error}")
            continue
        observed[path.name] = sorted(current)
        required = AGGREGATES.get(path.name)
        if required is not None:
            missing = sorted(required - current)
            if missing:
                failures.append(f"{path.name}: missing automatic events {missing}")
        elif is_special(path.name):
            forbidden = sorted(current & AUTOMATIC_EVENTS)
            if forbidden:
                failures.append(f"{path.name}: parallel automatic events {forbidden}")
    for aggregate in AGGREGATES:
        if aggregate not in observed:
            failures.append(f"missing aggregate workflow {aggregate}")
    if failures:
        raise ValueError("; ".join(failures))
    return {
        "schema": "hepta.ci-entrypoint-policy.v1",
        "automaticAggregates": sorted(AGGREGATES),
        "specialtyAutomaticViolations": [],
        "specialtyWorkflowCount": sum(is_special(name) for name in observed),
        "status": "aligned",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        report = verify(args.root.resolve())
    except (OSError, ValueError) as error:
        print(f"FAIL_HEPTA_CI_ENTRYPOINTS: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
