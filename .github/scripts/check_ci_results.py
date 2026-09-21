#!/usr/bin/env python3

"""Fail a terminal CI job unless every applicable dependency succeeded.

NEEDS is GitHub's toJSON(needs). EXPECTED_NEEDS optionally binds the complete
job set. ALLOWED_SKIPPED is only for jobs a successful scope decision proved
inapplicable; failed or cancelled work never passes. Empty input never passes.
"""

import json
import os


def names(value: object, label: str) -> set[str]:
    if not isinstance(value, list) or any(
        not isinstance(name, str) or not name for name in value
    ):
        raise ValueError(f"{label} must be a JSON list of nonempty job names")
    if len(value) != len(set(value)):
        raise ValueError(f"{label} contains duplicate job names")
    return set(value)


def validate(needs: object, allowed: set[str], expected: set[str] | None) -> None:
    if not isinstance(needs, dict) or not needs:
        raise ValueError("NEEDS must be a nonempty object")
    if any(not isinstance(name, str) or not name for name in needs):
        raise ValueError("invalid CI dependency name")
    if expected is not None and (not expected or set(needs) != expected):
        raise ValueError("CI dependency set does not match EXPECTED_NEEDS")
    if allowed.difference(needs):
        raise ValueError("unknown allowed-skipped CI dependencies")
    failures = []
    for name, dependency in needs.items():
        if not isinstance(dependency, dict):
            raise ValueError(f"invalid CI dependency: {name}")
        result = dependency.get("result")
        if result not in ("success", "failure", "cancelled", "skipped"):
            raise ValueError(f"invalid or absent CI result: {name}")
        if result != "success" and not (result == "skipped" and name in allowed):
            failures.append((name, result))
    if failures:
        raise ValueError("CI dependencies did not succeed: " + ", ".join(
            f"{name}: {result}" for name, result in sorted(failures)
        ))


def main() -> None:
    try:
        needs = json.loads(os.environ["NEEDS"])
        allowed = names(json.loads(os.environ.get("ALLOWED_SKIPPED", "[]")), "ALLOWED_SKIPPED")
        raw_expected = os.environ.get("EXPECTED_NEEDS")
        expected = None if raw_expected is None else names(json.loads(raw_expected), "EXPECTED_NEEDS")
        validate(needs, allowed, expected)
    except (KeyError, ValueError, TypeError) as error:
        print(f"CI gate rejected: {error}")
        raise SystemExit(1) from None
    print("All CI dependencies succeeded.")


if __name__ == "__main__":
    main()
