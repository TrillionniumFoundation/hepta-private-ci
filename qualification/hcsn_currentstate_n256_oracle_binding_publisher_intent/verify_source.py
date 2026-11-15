"""Verify exact parent identities for the source-only binding publisher."""

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from qualification.hcsn_currentstate_n256_oracle_binding_publisher_intent import (
    static_inspector,
)


ROOT = Path(__file__).parent
EXPECTED = {
    "qualification/hcsn_currentstate_n256_independent_oracle_v2_intent/adapter.py": "311eeeb69ba5002171d3aa765610bc9caea1cb2942309ba6e67543297cb74084",
    "qualification/hcsn_currentstate_n256_independent_oracle_v2_intent/admission.py": "7f3c24118a3504d393d59b31576e8a140c206a154dfaecf4c5ec0aa327feb90c",
    "qualification/hcsn_currentstate_n256_independent_oracle_v2_intent/REQUEST.json": "b99b8621b4ea6c4083815d736d07de96ef056251104224044d780c2135f7cdcc",
    "qualification/hcsn_currentstate_n256_sparse_dynamic_v2_intent/sparse_dynamic.py": "49616d4fcff9685a6cfcbee00ff45a2fd9ab4eb9c6ce04e62c02f927752d50db",
    "qualification/hcsn_currentstate_n256_sparse_dynamic_v2_intent/admission.py": "d3ec236043f1563a6c05d0843a1b431ec1288da70047a3dc451031c25f67f61b",
    "qualification/hcsn_currentstate_n256_sparse_dynamic_v2_intent/REQUEST.json": "9db32bf0c81051a8ba719a0fd54ece202e312ae84ab5ede43d181e3d86f410fe",
    "qualification/hcsn_currentstate_n256_independent_oracle_intent/independent_oracle.py": "4213f078e36cd3e296e9301df2d1788c3b9375cf7a911c73c0090fe500f5ab73",
    "qualification/hcsn_currentstate_n256_t0_capsule_v1/builder.py": "e96f8165cffc3e9f616f07bf42e18a0960a6213582f1e525f93ac5a8623f0b6c",
}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    request = json.loads((ROOT / "REQUEST.json").read_text())
    freeze = json.loads((ROOT / "SOURCE_FREEZE.json").read_text())
    for relative, expected in EXPECTED.items():
        if _sha(REPO / relative) != expected:
            raise SystemExit(f"parent identity mismatch: {relative}")
    for relative, expected in freeze["files"].items():
        if _sha(REPO / relative) != expected:
            raise SystemExit(f"frozen source mismatch: {relative}")
    report = static_inspector.inspect(ROOT / "publisher.py", ROOT / "REQUEST.json")
    if report["status"] != "PASS_ORACLE_BINDING_PUBLISHER_SOURCE_HOLD":
        raise SystemExit("static source inspection failed")
    if request["base_commit"] != "73deea3ce50d4da23f9df1915c4ffd8219d726b2":
        raise SystemExit("base commit mismatch")
    if freeze["status"] != "PASS_SOURCE_ONLY_HOLD_EXTERNAL_ORIGINALS":
        raise SystemExit("source freeze status mismatch")
    if freeze["all_closed"] is not False or freeze["largegrid_qualification"] is not False:
        raise SystemExit("source freeze grants closure or qualification")
    print("PASS_N256_ORACLE_BINDING_PUBLISHER_SOURCE_HOLD")


if __name__ == "__main__":
    main()
