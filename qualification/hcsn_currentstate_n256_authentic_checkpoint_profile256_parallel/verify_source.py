"""Fail-closed verifier for the parallel resource-amended source."""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FREEZE = json.loads((HERE / "SOURCE_FREEZE.json").read_text())


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    for relative, expected in FREEZE["source_sha256"].items():
        path = ROOT / relative
        if not path.is_file() or _sha256(path) != expected:
            raise SystemExit(f"source digest mismatch: {relative}")
    workflow = (ROOT / FREEZE["workflow"]).read_text()
    required = (
        "timeout-minutes: 120",
        "fail-fast: false",
        "max-parallel: 10",
        "--kill-after=30s 6900s",
        "if: always()",
        "hcsn-n256-authentic-checkpoint-profile256-parallel-20261122-c6bc-001",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
        "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
    )
    for token in required:
        if token not in workflow:
            raise SystemExit(f"workflow binding missing: {token}")
    lane = (HERE / "lane.py").read_text()
    if "set_int_max_str_digits" in lane or "optimizer" not in lane:
        raise SystemExit("lane scope guard mismatch")
    print("PASS_N256_INDEX256_PARALLEL_RESOURCE_AMENDMENT_SOURCE")


if __name__ == "__main__":
    main()
