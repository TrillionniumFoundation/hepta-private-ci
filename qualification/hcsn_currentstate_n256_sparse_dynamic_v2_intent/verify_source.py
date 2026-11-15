"""Verify the separately frozen v2 source and unchanged authentic originals."""

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


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    freeze = json.loads(FREEZE.read_text())
    if freeze["schema"] != "hcsn-n256-sparse-dynamic-source-freeze-v2":
        raise ValueError("freeze schema")
    if freeze["base_commit"] != "c749869a68a5f5d26600fdfb49ffd0352d214b39":
        raise ValueError("base commit")
    for relative, expected in freeze["source_sha256"].items():
        if digest(ROOT / relative) != expected:
            raise ValueError(f"source identity: {relative}")
    bindings = freeze["bindings"]
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
    print("PASS_N256_SPARSE_DYNAMIC_V2_SIGNED_CONTENT_SOURCE_HOLD")


if __name__ == "__main__":
    main()
