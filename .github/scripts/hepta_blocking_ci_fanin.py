#!/usr/bin/env python3
"""Fail closed over the exact blocking-ci job set and scope decision.

The scope job MUST emit exact lowercase boolean outputs. Missing, malformed,
or internally inconsistent values cannot be interpreted as an all-static diff.
The required job also pins its complete `needs` set, so losing a CI dependency
cannot accidentally be treated as a passing aggregate.
"""

from __future__ import annotations

import json
import os

from check_ci_results import validate

EXPECTED_JOBS = frozenset(
    {
        "scope",
        "hepta-contract-gate",
        "bazel",
        "blob-size-policy",
        "cargo-deny",
        "codespell",
        "repo-checks",
        "rust-ci",
        "sdk",
        "hepta-scoped",
        "lightweight",
    }
)
FULL_REPO_ONLY = frozenset({"bazel", "cargo-deny", "repo-checks", "rust-ci", "sdk"})


def allowed_skipped(native: str | None, full_repo: str | None) -> set[str]:
    if native not in ("true", "false") or full_repo not in ("true", "false"):
        raise ValueError("native and full_repo must be explicit lowercase booleans")
    has_native = native == "true"
    is_full = full_repo == "true"
    if is_full and not has_native:
        raise ValueError("full_repo=true requires native=true")

    allowed: set[str] = set()
    if not has_native:
        allowed.add("hepta-contract-gate")
    if not is_full:
        allowed.update(FULL_REPO_ONLY)
    if not (has_native and not is_full):
        allowed.add("hepta-scoped")
    if has_native:
        allowed.add("lightweight")
    return allowed


def check(needs: object, native: str | None, full_repo: str | None) -> None:
    validate(needs, allowed_skipped(native, full_repo), set(EXPECTED_JOBS))


def main() -> None:
    try:
        needs = json.loads(os.environ["NEEDS"])
        check(needs, os.environ.get("NATIVE"), os.environ.get("FULL_REPO"))
    except (KeyError, ValueError, TypeError) as error:
        print(f"Blocking CI rejected: {error}")
        raise SystemExit(1) from None
    print("All applicable blocking CI dependencies succeeded.")


if __name__ == "__main__":
    main()
