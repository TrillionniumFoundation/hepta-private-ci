#!/usr/bin/env python3
"""Validate Lane B companions against the single v3 truth bundle."""

from __future__ import annotations

import argparse
import json

from hepta_lane_b_schema import Invalid, load_bundle, verify_companions, verify_structure


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["check", "verify"], default="check")
    parser.parse_args()
    try:
        bundle = load_bundle()
        mapped, delegated = verify_structure(bundle, inspect_source=False)
        companions = verify_companions(bundle)
        print(json.dumps({
            "status": "PASS_HEPTA_LANE_B_DOCUMENTS_V3",
            "modules": 11,
            "operations": mapped,
            "delegatedOperations": delegated,
            "companions": companions,
        }, sort_keys=True))
    except Invalid as exc:
        raise SystemExit(f"FAIL_HEPTA_LANE_B_DOCUMENTS_V3: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
