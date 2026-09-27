#!/usr/bin/env python3
"""Compatibility entrypoint for exact Agentd qualification.

GitHub runner image labels are deployment choices, while the receipt schema has
stable logical platform identifiers. Normalize fixed image aliases before
calling the retained verifier implementation so old and protected workflows
produce one closed receipt matrix.
"""
from __future__ import annotations

import sys

from agentd_exact_head_base import *  # noqa: F401,F403

_RUNNER_OS_ALIASES = {
    "ubuntu-24.04": "ubuntu-latest",
    "macos-15": "macos-latest",
}


def _normalize_runner_os(argv: list[str]) -> list[str]:
    normalized = list(argv)
    for index, value in enumerate(normalized[:-1]):
        if value == "--os":
            normalized[index + 1] = _RUNNER_OS_ALIASES.get(
                normalized[index + 1], normalized[index + 1]
            )
    return normalized


if __name__ == "__main__":
    sys.argv[:] = _normalize_runner_os(sys.argv)
    raise SystemExit(main())
