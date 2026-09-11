#!/usr/bin/env python3
"""Exact-source and synthetic-merge verifier for Lane B v3."""

from __future__ import annotations

import argparse
import json

from hepta_lane_b_schema import Invalid
from hepta_lane_b_schema import self_test
from hepta_lane_b_schema import verify_repository


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["verify", "self-test"])
    args = parser.parse_args()
    try:
        if args.command == "self-test":
            self_test()
        else:
            verify_repository()
    except Invalid as exc:
        raise SystemExit(f"FAIL_HEPTA_LANE_B_V3: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
