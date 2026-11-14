"""Hash only the explicit engineering/code inventory. Does not authorize execution."""
import argparse
from datetime import datetime, timezone
from pathlib import Path

from runner import HERE, REQUIRED_FREEZE_FILES, sha256, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = {"schema": "sanitized-pilot-code-freeze-v1",
             "created_utc": datetime.now(timezone.utc).isoformat(),
             "status": "ENGINEERING_FREEZE_NOT_ACQUISITION_OR_EXECUTION_GO",
             "files": {name: sha256(HERE / name) for name in sorted(REQUIRED_FREEZE_FILES)}}
    write_json(args.output, value)
    print(sha256(args.output))


if __name__ == "__main__":
    main()
