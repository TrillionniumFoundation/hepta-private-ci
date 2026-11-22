"""Fail-closed source verifier for the #6948 evidence readback."""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FREEZE = json.loads((HERE / "SOURCE_FREEZE.json").read_text())


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    for relative, expected in FREEZE["source_sha256"].items():
        path = ROOT / relative
        if not path.is_file() or _sha256(path) != expected:
            raise SystemExit(f"source digest mismatch: {relative}")
    artifact = json.loads((HERE / "ARTIFACT.json").read_text())
    expected = {
        "artifact_id": 14746536349,
        "artifact_name": "hcsn-n256-authentic-compact-checkpoint-001",
        "artifact_sha256": "fe98992972a1779e6ffe1baf2142a2010bd71eb92e633dc69e459578caa9e8f6",
        "artifact_size_bytes": 17089235,
        "job_id": 137145342292,
        "run_id": 45001992354,
        "source_commit": "9e4d8bf6e38f5372a55bc9e772c5f9cd095f297c",
        "source_pull_request": 6948,
        "status": "success",
    }
    if artifact != expected:
        raise SystemExit("artifact identity differs")
    sizes = [
        (HERE / f"ORIGINAL.zip.part{index:03d}").stat().st_size
        for index in range(35)
    ]
    if sizes != [500_000] * 34 + [89_235]:
        raise SystemExit("artifact part geometry differs")
    workflow = (ROOT / FREEZE["workflow"]).read_text()
    for token in (
        "timeout-minutes: 10",
        "verify_readback.py",
        "python3 -O",
        "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd",
    ):
        if token not in workflow:
            raise SystemExit(f"workflow binding missing: {token}")
    print("PASS_N256_AUTHENTIC_COMPACT_CHECKPOINT_READBACK_SOURCE")


if __name__ == "__main__":
    main()
