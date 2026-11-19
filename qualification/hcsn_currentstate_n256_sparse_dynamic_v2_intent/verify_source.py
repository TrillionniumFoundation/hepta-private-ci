"""Verify the separately frozen v3 admission bridge and parent originals."""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FREEZE = HERE / "SOURCE_FREEZE.json"
OLD_SOURCE = (
    ROOT
    / "qualification/hcsn_currentstate_n256_sparse_dynamic_intent/sparse_dynamic.py"
)
PHASE = ROOT / "qualification/hcsn_n256_new_export/evidence/attempt001/N256_PHASE.json"
T0_BUILDER = ROOT / "qualification/hcsn_currentstate_n256_t0_capsule_v1/builder.py"
EXECUTION_BRIDGE = (
    ROOT
    / "qualification/hcsn_currentstate_n256_execution_admission_bridge/admission_bridge.py"
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    freeze = json.loads(FREEZE.read_text())
    if freeze["schema"] != "hcsn-n256-sparse-dynamic-source-freeze-v3":
        raise ValueError("freeze schema")
    if freeze["base_commit"] != "1d03be4db492902294bca637b27968ae1de32ca4":
        raise ValueError("base commit")
    for relative, expected in freeze["source_sha256"].items():
        if digest(ROOT / relative) != expected:
            raise ValueError(f"source identity: {relative}")
    bindings = freeze["bindings"]
    if bindings["parent_v2_source_sha256"] != "7ce716d2cbc00740d646b13498cbf6f935ba388e3bb43363a5bc4e79cd7312bf":
        raise ValueError("parent v2 source identity")
    if bindings["parent_v2_request_sha256"] != "1da196b5ddd6ec2b1013cd194fe7da7df3ac895d9285c4b05c529c0041d2f8e1":
        raise ValueError("parent v2 request identity")
    if digest(EXECUTION_BRIDGE) != bindings["execution_admission_bridge_sha256"]:
        raise ValueError("execution admission bridge identity")
    if digest(OLD_SOURCE) != bindings["historical_v1_source_sha256"]:
        raise ValueError("historical v1 source")
    if 'item["content"]' not in OLD_SOURCE.read_text():
        raise ValueError("historical schema failure is not preserved")
    if digest(PHASE) != bindings["authentic_phase_sha256"]:
        raise ValueError("authentic phase")
    phase = json.loads(PHASE.read_text())
    if len(phase["packets"]) != 8 or any(
        "signed_content" not in item or "content" in item for item in phase["packets"]
    ):
        raise ValueError("authentic phase packet schema")
    if digest(T0_BUILDER) != bindings["t0_builder_sha256"]:
        raise ValueError("t0 builder")
    new_source = (HERE / "sparse_dynamic.py").read_text()
    if 'item["signed_content"]' not in new_source or 'item["content"]' in new_source:
        raise ValueError("v2 signed-content mapping")
    admission_source = (HERE / "admission.py").read_text()
    if "admission_bridge.validate_preexecution_bundle" not in admission_source:
        raise ValueError("v2 admission/freeze bridge is not executable")
    if "candidate_source_sha256" not in admission_source:
        raise ValueError("current signed-content source is not byte-bound")
    print("PASS_N256_SPARSE_DYNAMIC_V3_ADMISSION_BRIDGE_SOURCE_HOLD")


if __name__ == "__main__":
    main()
