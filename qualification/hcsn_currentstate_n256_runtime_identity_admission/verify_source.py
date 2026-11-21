from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent


def main() -> int:
    freeze = json.loads((HERE / "SOURCE_FREEZE.json").read_text(encoding="utf-8"))
    for name, expected in freeze["files"].items():
        actual = hashlib.sha256((HERE / name).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"source freeze mismatch: {name}")
    print("PASS_FROZEN_N256_RUNTIME_IDENTITY_ADMISSION_SOURCE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

