"""Verify the frozen first-step source contract without numerical execution."""

import hashlib
import json
import sys
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY))

from qualification.hcsn_currentstate_n256_firststep_contract import contract
from qualification.hcsn_currentstate_n256_firststep_contract import static_inspector


ROOT = Path(__file__).parent


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    request = json.loads((ROOT / "REQUEST.json").read_text())
    freeze = json.loads((ROOT / "SOURCE_FREEZE.json").read_text())
    contract.validate_request(request)
    for relative, expected in freeze["files"].items():
        if _sha(REPOSITORY / relative) != expected:
            raise SystemExit(f"source freeze mismatch: {relative}")
    report = static_inspector.inspect(ROOT, REPOSITORY)
    if report["status"] != "PASS_SOURCE_ONLY_FIRSTSTEP_CONTRACT_HOLD":
        raise SystemExit("static inspection failed")
    zero_fields = (
        "authentic_firststep_capsules",
        "authentic_firststep_coordinates",
        "dynamic_steps",
        "matrix_exponential_actions",
        "serializer_calls",
        "torch_calls",
        "optimizer_steps",
    )
    if any(freeze[field] != 0 for field in zero_fields):
        raise SystemExit("source freeze claims numerical execution")
    if freeze["historical_resource_red_6295_unchanged"] is not True:
        raise SystemExit("#6295 resource RED was changed")
    if freeze["all_closed"] is not False:
        raise SystemExit("source freeze claims global closure")
    print("PASS_N256_FIRSTSTEP_SOURCE_ONLY_CONTRACT_HOLD")


if __name__ == "__main__":
    main()
