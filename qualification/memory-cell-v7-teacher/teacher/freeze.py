"""Run once before evaluation; replacing a freeze creates a new candidate."""

import hashlib
import json
from pathlib import Path

from teacher_router import FROZEN_FILES, HERE


def main():
    files = {}
    for name in sorted(FROZEN_FILES):
        data = (HERE / name).read_bytes()
        files[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    raw = (json.dumps({"schema": "memory-cell-v7.teacher-freeze.v1", "files": files},
                      sort_keys=True, indent=2) + "\n").encode()
    with (HERE / "FREEZE.json").open("xb") as stream:
        stream.write(raw)
    print(json.dumps({"freeze_sha256": hashlib.sha256(raw).hexdigest(), "files": files}, indent=2))


if __name__ == "__main__":
    main()
