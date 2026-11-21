import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    freeze = json.loads((HERE / "SOURCE_FREEZE.json").read_text())
    for name, expected in freeze["files"].items():
        actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"source freeze mismatch: {name}")
    print("PASS_FROZEN_N256_RUNTIME_MATCHED_EXECUTION_SOURCE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

