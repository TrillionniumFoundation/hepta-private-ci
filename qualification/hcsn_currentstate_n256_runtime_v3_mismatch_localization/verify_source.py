"""Verify frozen diagnostic source and immutable input bytes."""

import hashlib
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    freeze = json.loads((HERE / "SOURCE_FREEZE.json").read_text())
    for relative, expected in freeze["source_sha256"].items():
        path = ROOT / relative if relative.startswith(".github/") else HERE / relative
        if digest(path) != expected:
            raise ValueError(f"source identity: {relative}")
    request = json.loads((HERE / "REQUEST.json").read_text())
    if digest(ROOT / request["candidate_archive"]) != request["candidate_archive_sha256"]:
        raise ValueError("candidate archive identity")
    if digest(ROOT / request["oracle_archive"]) != request["oracle_archive_sha256"]:
        raise ValueError("oracle archive identity")
    if any(name in sys.modules for name in ("numpy", "scipy", "torch")):
        raise ValueError("source verifier imported numerical module")
    print("PASS_FROZEN_N256_RUNTIME_V3_MISMATCH_LOCALIZATION_SOURCE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
