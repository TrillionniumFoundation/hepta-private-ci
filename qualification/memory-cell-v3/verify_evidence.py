"""Verify all run files, original source snapshot, and exact committed sources."""

import argparse
import json
from pathlib import Path
import sys

PACKAGE = Path(__file__).resolve().parent
sys.path.insert(0, str(PACKAGE.parent / "memory-cell-v2"))

from v3.evidence import verify_run  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--repo", type=Path, default=PACKAGE.parents[1])
    parser.add_argument("--allow-failed", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            verify_run(args.run, args.repo, allow_failed=args.allow_failed),
            sort_keys=True,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
