#!/usr/bin/env python3
"""Retired one-shot platform.types mutation entrypoint.

Qualification and repair are now ordinary reviewed source changes followed by
read-only exact-candidate workflows. This compatibility file deliberately
refuses to edit the repository so an old operator command cannot rewrite the
Rama graph, refresh evidence, or push a self-modified candidate.
"""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "platform.types closure repair is retired; apply reviewed source changes "
        "and run the read-only qualification workflows",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
