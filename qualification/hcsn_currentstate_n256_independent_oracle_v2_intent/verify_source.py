"""Verify exact parent sources and authentic originals for oracle v2."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).parents[2]
PACKAGE = Path(__file__).parent
EXPECTED = {
    "qualification/hcsn_currentstate_n256_sparse_dynamic_v2_intent/sparse_dynamic.py": "49616d4fcff9685a6cfcbee00ff45a2fd9ab4eb9c6ce04e62c02f927752d50db",
    "qualification/hcsn_currentstate_n256_sparse_dynamic_v2_intent/admission.py": "d3ec236043f1563a6c05d0843a1b431ec1288da70047a3dc451031c25f67f61b",
    "qualification/hcsn_currentstate_n256_independent_oracle_intent/independent_oracle.py": "4213f078e36cd3e296e9301df2d1788c3b9375cf7a911c73c0090fe500f5ab73",
    "qualification/hcsn_currentstate_n256_t0_capsule_v1/builder.py": "e96f8165cffc3e9f616f07bf42e18a0960a6213582f1e525f93ac5a8623f0b6c",
    "qualification/hcsn_n256_new_export/evidence/attempt001/N256_STATE.json": "360b4bf446e853209c58cdb3faded74d9114d872cfb9c730b220d14cef670f9c",
    "qualification/hcsn_n256_new_export/evidence/attempt001/N256_PHASE.json": "790fabee8825dbd4361f157f56d78641430fe50b9134cd2cb7b02b51b93fe548",
    "qualification/hcsn_n256_new_export/evidence/attempt001/N256_STATE.npz.b64": "926191319021c51421dd15d76c66c3b5c6d2efef0f28af3f76c893065a49dbeb",
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    observed = {path: sha(ROOT / path) for path in EXPECTED}
    if observed != EXPECTED:
        raise SystemExit("frozen parent source or authentic original mismatch")
    request = json.loads((PACKAGE / "REQUEST.json").read_text())
    if request["candidate_source_sha256"] != EXPECTED[next(iter(EXPECTED))]:
        raise SystemExit("candidate source request binding mismatch")
    if request["candidate_admission_sha256"] != EXPECTED[
        "qualification/hcsn_currentstate_n256_sparse_dynamic_v2_intent/admission.py"
    ]:
        raise SystemExit("candidate admission request binding mismatch")
    if request["legacy_oracle_source_sha256"] != EXPECTED[
        "qualification/hcsn_currentstate_n256_independent_oracle_intent/independent_oracle.py"
    ]:
        raise SystemExit("legacy oracle request binding mismatch")
    freeze = json.loads((PACKAGE / "SOURCE_FREEZE.json").read_text())
    for path, digest in freeze["source_sha256"].items():
        if sha(ROOT / path) != digest:
            raise SystemExit(f"source freeze mismatch: {path}")
    print("PASS_N256_INDEPENDENT_ORACLE_V2_SIGNED_CONTENT_SOURCE_HOLD")


if __name__ == "__main__":
    main()
