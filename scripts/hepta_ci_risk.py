#!/usr/bin/env python3
"""Project exact diff scope into ordinary, stateful, effect or release CI."""
from __future__ import annotations

import argparse
import json

try:
    from scripts.hepta_ci_scope import changed_paths
    from scripts.hepta_ci_scope import include_input_scope
    from scripts.hepta_ci_scope import select
except ModuleNotFoundError as error:
    if error.name != "scripts":
        raise
    from hepta_ci_scope import changed_paths
    from hepta_ci_scope import include_input_scope
    from hepta_ci_scope import select


def classify(scope: dict[str, bool]) -> str:
    if scope["full_repo"]:
        return "release"
    if scope["effects"]:
        return "effect"
    if scope["lifecycle"] or scope["learning"] or scope["objective"]:
        return "stateful"
    return "ordinary"


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
    risk = classify(scope)
    lanes = ["source-head"] if risk == "ordinary" else ["source-head", "base-merge"]
    result = {
        "risk": risk,
        "lanes": lanes,
        "require_exact_source": risk != "ordinary",
        "scope": scope,
    }
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as target:
            target.write(f"risk={risk}\n")
            target.write(
                "require_exact_source="
                + str(risk != "ordinary").lower()
                + "\n"
            )
            target.write("lanes=" + json.dumps(lanes, separators=(",", ":")) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
