#!/usr/bin/env python3
"""Project exact diff scope into ordinary, stateful, effect or release CI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts.hepta_ci_scope import changed_paths
    from scripts.hepta_ci_scope import include_input_scope
    from scripts.hepta_ci_scope import include_module_scope
    from scripts.hepta_ci_scope import select
    from scripts.hepta_repository_surface import load_policy
except ModuleNotFoundError as error:
    if error.name != "scripts":
        raise
    from hepta_ci_scope import changed_paths
    from hepta_ci_scope import include_input_scope
    from hepta_ci_scope import include_module_scope
    from hepta_ci_scope import select
    from hepta_repository_surface import load_policy


def classify(scope: dict[str, bool]) -> str:
    if scope["full_repo"]:
        # Impact breadth is not release authority. Unknown shared code still
        # gets deep effect/recovery checks, but release is an explicit input.
        return "effect"
    if scope["effects"]:
        return "effect"
    if scope["lifecycle"] or scope["learning"] or scope["objective"]:
        return "stateful"
    return "ordinary"


def project(
    scope: dict[str, bool],
    *,
    change_risk: str | None = None,
    reasons: list[str] | None = None,
    qualification_requested: bool = False,
) -> dict[str, object]:
    risk = change_risk if change_risk is not None else classify(scope)
    if risk not in {"ordinary", "stateful", "effect", "release"}:
        raise ValueError("unknown CI change risk")
    if type(qualification_requested) is not bool:
        raise ValueError("qualification request must be boolean")
    policy = load_policy()
    ordinary = risk == "ordinary" and not qualification_requested
    return {
        "risk": risk,
        "risk_reasons": reasons or [],
        "lanes": ["source-head"] if ordinary else ["source-head", "base-merge"],
        # Change risk selects real source/merge tests, not release evidence.
        # Independent maps and dossiers belong to an explicit qualification run.
        "require_exact_source": qualification_requested,
        "ordinary_feedback_target_minutes": policy["ordinaryFeedbackTargetMinutes"],
        "scoped_timeout_minutes": (
            policy["ordinaryWorkflowTimeoutMinutes"]
            if ordinary
            else policy["statefulWorkflowTimeoutMinutes"]
        ),
        "architecture_timeout_minutes": (
            policy["ordinaryWorkflowTimeoutMinutes"]
            if ordinary
            else policy["architectureDeepTimeoutMinutes"]
        ),
        "scope": scope,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base")
    parser.add_argument("--head", required=True)
    parser.add_argument("--full", action="store_true")
    parser.add_argument(
        "--qualification",
        action="store_true",
        help="include existing exact-source qualification; grants no activation authority",
    )
    parser.add_argument("--github-output")
    args = parser.parse_args()
    if not args.full and not args.base:
        parser.error("an exact --base is required unless --full is selected")
    paths = [] if args.full else changed_paths(args.base, args.head)
    scope = select(paths, force_full=args.full)
    input_scope = scope
    if not args.full:
        input_scope = include_input_scope(scope, paths, args.base, args.head)
        scope = include_module_scope(input_scope, paths, args.base, args.head)
    if args.full:
        result = project(scope, qualification_requested=args.qualification)
    else:
        try:
            from scripts.hepta_ci_modules import assess_changes
        except ModuleNotFoundError as error:
            if error.name != "scripts":
                raise
            from hepta_ci_modules import assess_changes
        risk, reasons = assess_changes(Path.cwd(), paths, args.base, args.head)
        # Embedded/opaque source inputs may look like prose. A source owner
        # discovered by the existing impact planner keeps its deeper boundary.
        raw = select(paths)
        if input_scope != raw:
            from_rank = {"ordinary": 0, "stateful": 1, "effect": 2, "release": 3}
            risk = max((risk, classify(scope)), key=from_rank.get)
        result = project(
            scope,
            change_risk=risk,
            reasons=reasons,
            qualification_requested=args.qualification,
        )
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as target:
            target.write(f"risk={result['risk']}\n")
            target.write(
                "require_exact_source="
                + str(result["require_exact_source"]).lower()
                + "\n"
            )
            target.write(
                "lanes=" + json.dumps(result["lanes"], separators=(",", ":")) + "\n"
            )
            target.write(f"scoped_timeout_minutes={result['scoped_timeout_minutes']}\n")
            target.write(
                "architecture_timeout_minutes="
                f"{result['architecture_timeout_minutes']}\n"
            )
            target.write(
                "ordinary_feedback_target_minutes="
                f"{result['ordinary_feedback_target_minutes']}\n"
            )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
