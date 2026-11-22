"""Fail-closed verifier for the compact checkpoint source freeze."""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FREEZE = json.loads((HERE / "SOURCE_FREEZE.json").read_text())
REQUEST = json.loads((HERE / "REQUEST.json").read_text())


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    for relative, expected in FREEZE["source_sha256"].items():
        path = ROOT / relative
        if not path.is_file() or _sha256(path) != expected:
            raise SystemExit(f"source digest mismatch: {relative}")
    workflow = (ROOT / FREEZE["workflow"]).read_text()
    required = (
        "timeout-minutes: 15",
        "--kill-after=30s 600s",
        "if: always()",
        REQUEST["execution_key"],
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
        "GITHUB_RUN_ATTEMPT",
    )
    run_source = (HERE / "run.py").read_text()
    for token in required:
        if token not in workflow and token not in run_source:
            raise SystemExit(f"execution binding missing: {token}")
    forbidden = ("torch", "optimizer.step", "scipy", "numpy", "_row_action")
    compact_source = (HERE / "compact.py").read_text().lower()
    if any(token in compact_source for token in forbidden):
        raise SystemExit("compact serializer scope expanded")
    if REQUEST["work_upper_bounds"] != {
        "dynamic_steps": 0,
        "exponential_actions": 0,
        "optimizer_steps": 0,
        "provider_outputs": 0,
        "recurrence_row_actions": 0,
        "serializer_decodes": 10,
        "serializer_encodes": 20,
        "tail_checks": 0,
        "torch_calls": 0,
    }:
        raise SystemExit("work upper bound differs")
    print("PASS_N256_AUTHENTIC_COMPACT_CHECKPOINT_SOURCE")


if __name__ == "__main__":
    main()
