#!/usr/bin/env python3
"""Project exact diff scope into ordinary, stateful, effect or release CI."""
from __future__ import annotations

import argparse
import json

try:
    from scripts.hepta_ci_scope import changed_paths
    from scripts.hepta_ci_scope import include_input_scope
    from scripts.hepta_ci_scope import select
    from scripts.hepta_repository_surface import load_policy
except ModuleNotFoundError as error:
    if error.name != "scripts":
        raise
    from hepta_ci_scope import changed_paths
    from hepta_ci_scope import include_input_scope
    from hepta_ci_scope import select
    from hepta_repository_surface import load_policy


def classify(scope: dict[str, bool]) -> str:
    if scope["full_repo"]:
        return "release"
    if scope["effects"]:
        return "effect"
    if scope["lifecycle"] or scope["learning"] or scope["objective"]:
        return "stateful"
    return "ordinary"


def project(scope: dict[str, bool]) -> dict[str, object]:
    risk = classify(scope)
    policy = load_policy()
    ordinary = risk == "ordinary"
    return {
        "risk": risk,
        "lanes": ["source-head"] if ordinary else ["source-head", "base-merge"],
        "require_exact_source": not ordinary,
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
    parser.add_argument("--github-output")
    args = parser.parse_args()
    if not args.full and not args.base:
        parser.error("an exact --base is required unless --full is selected")
    paths = [] if args.full else changed_paths(args.base, args.head)
    scope = select(paths, force_full=args.full)
    if not args.full:
        scope = include_input_scope(scope, paths, args.base, args.head)
    result = project(scope)
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as target:
            target.write(f"risk={result['risk']}\n")
            target.write(
                "require_exact_source="
                + str(result["require_exact_source"]).lower()
                + "\n"
            )
            target.write(
                "lanes="
                + json.dumps(result["lanes"], separators=(",", ":"))
                + "\n"
            )
            target.write(
                f"scoped_timeout_minutes={result['scoped_timeout_minutes']}\n"
            )
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
