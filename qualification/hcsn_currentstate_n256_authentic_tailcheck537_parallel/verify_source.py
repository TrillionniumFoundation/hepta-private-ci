"""Fail-closed verifier for the parallel index537 first-tail source."""

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
    for token in (
        "timeout-minutes: 120",
        "fail-fast: false",
        "max-parallel: 10",
        "--kill-after=30s 6900s",
        "if: always()",
        REQUEST["execution_key"],
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
        "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
    ):
        if token not in workflow:
            raise SystemExit(f"workflow binding missing: {token}")
    expected_work = {
        "dynamic_steps": 0,
        "exponential_actions": 0,
        "index256_compact_decodes": 10,
        "index537_compact_decodes": 10,
        "index537_compact_encodes": 20,
        "optimizer_steps": 0,
        "provider_outputs": 0,
        "recurrence_row_actions": 2810,
        "rounding_calls": 5180,
        "tail_checks": 10,
        "torch_calls": 0,
    }
    if REQUEST["work_upper_bounds"] != expected_work:
        raise SystemExit("work upper bound differs")
    if REQUEST["result_policy"] != "publish unique or nonunique first-tail observation without rerun":
        raise SystemExit("result publication policy differs")
    lane = (HERE / "lane.py").read_text()
    if "GITHUB_RUN_ATTEMPT" not in lane or "!= \"1\"" not in lane:
        raise SystemExit("lane rerun guard is missing")
    print("PASS_N256_AUTHENTIC_TAILCHECK537_PARALLEL_SOURCE")


if __name__ == "__main__":
    main()
