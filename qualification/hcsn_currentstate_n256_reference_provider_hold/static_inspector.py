"""Zero-numerical audit of the N256 reference-provider scientific HOLD."""

import hashlib
import json
from pathlib import Path

from .method_hold import (
    AdmissionRequired,
    assess_frozen_numeric_kernels,
    require_provider_admission,
    validate_source_request,
)


ROOT = Path(__file__).parent
REPO = ROOT.parents[1]
CANDIDATE = (
    REPO
    / "qualification/hcsn_currentstate_n256_sparse_dynamic_intent/sparse_dynamic.py"
)
ORACLE = (
    REPO
    / "qualification/hcsn_currentstate_n256_independent_oracle_intent/independent_oracle.py"
)


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    request = json.loads((ROOT / "REQUEST.json").read_text())
    validate_source_request(request)
    if _digest(CANDIDATE) != request["candidate_source_sha256"]:
        raise SystemExit("candidate source binding mismatch")
    if _digest(ORACLE) != request["oracle_source_sha256"]:
        raise SystemExit("oracle source binding mismatch")
    assessment = assess_frozen_numeric_kernels(
        CANDIDATE.read_text(), ORACLE.read_text()
    )
    if not assessment.shared_numeric_kernel:
        raise SystemExit("frozen shared-kernel blocker changed")
    freeze = json.loads((ROOT / "SOURCE_FREEZE.json").read_text())
    for relative, expected in freeze["source_sha256"].items():
        actual = _digest(REPO / relative)
        if actual != expected:
            raise SystemExit(f"source mismatch: {relative}: {actual} != {expected}")
    try:
        require_provider_admission(ROOT / "REQUEST.json", None)
    except AdmissionRequired:
        pass
    else:
        raise SystemExit("reference-provider HOLD failed open")
    print("PASS_N256_REFERENCE_PROVIDER_TRUTHFUL_HOLD_SOURCE_ONLY")


if __name__ == "__main__":
    main()
