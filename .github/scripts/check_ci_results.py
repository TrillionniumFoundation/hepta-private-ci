#!/usr/bin/env python3

"""Fail a terminal CI job unless every applicable dependency succeeded.

Parent workflows pass GitHub's `toJSON(needs)` object through the NEEDS
environment variable. Skipped dependencies fail by default. A parent may name
an explicit JSON list in ALLOWED_SKIPPED when a preceding, successful scope job
proved those jobs inapplicable. Cancelled and failed dependencies never pass.
"""

import json
import os


def main() -> None:
    # Keep result policy in one script so blocking-ci and postmerge-ci cannot
    # drift in how they interpret dependency conclusions.
    needs = json.loads(os.environ["NEEDS"])
    allowed_skipped = set(json.loads(os.environ.get("ALLOWED_SKIPPED", "[]")))
    unknown = sorted(allowed_skipped.difference(needs))
    if unknown:
        print("Unknown allowed-skipped CI dependencies:")
        for name in unknown:
            print(name)
        raise SystemExit(1)
    failures = sorted(
        (name, dependency["result"])
        for name, dependency in needs.items()
        if dependency["result"] != "success"
        and not (dependency["result"] == "skipped" and name in allowed_skipped)
    )

    if failures:
        print("CI dependencies did not succeed:")
        for name, result in failures:
            print(f"{name}: {result}")
        raise SystemExit(1)

    print("All CI dependencies succeeded.")


if __name__ == "__main__":
    main()
