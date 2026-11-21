"""Verify the immutable source-only intent without importing numerical modules."""

import hashlib
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    freeze = json.loads((HERE / "SOURCE_FREEZE.json").read_text())
    request = json.loads((HERE / "REQUEST.json").read_text())
    if freeze["request_sha256"] != _sha(HERE / "REQUEST.json"):
        raise ValueError("request identity")
    for relative, expected in freeze["source_sha256"].items():
        path = ROOT / relative if relative.startswith(".github/") else HERE / relative
        if _sha(path) != expected:
            raise ValueError(f"source identity: {relative}")
    if request["future_attempt"]["execution_allowed"] is not False:
        raise ValueError("source intent unexpectedly admits execution")
    if request["future_attempt"]["unique_execution_key"] is not None:
        raise ValueError("source intent unexpectedly allocates a key")
    if set(request["source_stage_counts"].values()) != {0}:
        raise ValueError("source-stage numerical count")
    if any(name in sys.modules for name in ("numpy", "scipy", "torch")):
        raise ValueError("numerical module imported by source verifier")
    print("PASS_SOURCE_ONLY_N256_DENSE_COMPATIBLE_FIRSTSTEP_INTENT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
