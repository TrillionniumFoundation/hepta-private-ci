"""Verify the exact source-only freeze without numerical N256 work."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).parent
REPO = ROOT.parents[1]


def main():
    request = json.loads((ROOT / "REQUEST.json").read_text(encoding="utf-8"))
    if request["schema"] != "hcsn-n256-independent-uniformization-primitive-source-v1":
        raise SystemExit("request schema mismatch")
    for name in (
        "n256_provider_source_sha256",
        "n256_provider_admission_sha256",
        "numerical_idempotency_key",
    ):
        if request[name] is not None:
            raise SystemExit(f"source stage failed open: {name}")
    if request["n256_numerical_execution_allowed"] is not False:
        raise SystemExit("source stage enabled numerical work")
    if any(request["execution_counts"].values()):
        raise SystemExit("source stage execution count is nonzero")
    if request["largegrid_qualification"] is not False or request["all_closed"] is not False:
        raise SystemExit("source stage overclaims qualification")
    freeze = json.loads((ROOT / "SOURCE_FREEZE.json").read_text(encoding="utf-8"))
    for relative, expected in freeze["source_sha256"].items():
        actual = hashlib.sha256((REPO / relative).read_bytes()).hexdigest()
        if actual != expected:
            raise SystemExit(f"source mismatch: {relative}: {actual} != {expected}")
    print("PASS_N256_INDEPENDENT_UNIFORMIZATION_PRIMITIVE_SOURCE_ONLY")


if __name__ == "__main__":
    main()
