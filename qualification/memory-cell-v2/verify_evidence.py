"""Verify v2 artifacts and exact committed source/data identities."""

import argparse
import json
from pathlib import Path

from v2.evidence import verify_run


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--allow-failed", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            verify_run(args.directory, args.repo, allow_failed=args.allow_failed),
            sort_keys=True,
        )
    )
