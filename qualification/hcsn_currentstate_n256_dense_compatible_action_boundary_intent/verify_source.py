"""Verify the source-only N256 dense-compatible boundary intent."""

import hashlib
import json
from pathlib import Path

from qualification.hcsn_currentstate_n256_dense_compatible_action_boundary_intent import (
    static_inspector,
)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FREEZE = HERE / "SOURCE_FREEZE.json"

PARENT_BINDINGS = {
    "qualification/hcsn_currentstate_n256_firststep_dense_oracle_source/dense_oracle.py":
        "a3aa6a95cd55d254d9fa911d10768d1ec827e2374265a5b0474e0d6243929bfa",
    "qualification/hcsn_currentstate_n256_sparse_dynamic_v2_intent/sparse_dynamic.py":
        "6d3fea2b230bc7abc28df3d4d3c8f28ceaa163d9961ef2db8a7e369eee1f4816",
    "qualification/hcsn_currentstate_n256_firststep_serializer_v2/serializer.py":
        "dfa63cbfe7688e9c07cfff627cffd3d1e0352191e09f2be20ad53d1e310c1ab9",
    "qualification/hcsn_currentstate_n256_firststep_candidate_compare/compare.py":
        "473f7e05269a6768885b539e2f8af83ed892a7b835b68772fe42e4f0912d7f2b",
    "qualification/hcsn_currentstate_n256_firststep_candidate_listrow_bitwise_red_run44851931235/MANIFEST.json":
        "20356ad99cfcd76851a76df9bde275db3d57ed4a5f264bc97b282e75f3e647ca",
    "qualification/hcsn_currentstate_n256_firststep_candidate_listrow_bitwise_red_run44851931235/REVIEW.json":
        "7f40636ab99842eb7524d811340d25476e24cf69e98664761d8f5483dbf070c5",
    "qualification/hcsn_currentstate_n256_firststep_candidate_listrow_bitwise_red_run44851931235/originals/hcsn-n256-firststep-candidate-listrow-repair-001.zip":
        "6323e8494359b42e11639afd3033d90c7fa86bbb057b824aefae49799ecb4ef5",
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify():
    freeze = json.loads(FREEZE.read_text())
    request = json.loads((HERE / "REQUEST.json").read_text())
    if freeze["schema"] != "hcsn-n256-dense-compatible-action-boundary-source-freeze-v1":
        raise ValueError("source freeze schema")
    if freeze["base_evidence_commit"] != "6b1bc27cc1c0b31830df2a489cb9e12e2f675d1b":
        raise ValueError("base evidence commit")
    for relative, expected in freeze["source_sha256"].items():
        if digest(ROOT / relative) != expected:
            raise ValueError(f"source identity: {relative}")
    for relative, expected in PARENT_BINDINGS.items():
        if digest(ROOT / relative) != expected:
            raise ValueError(f"parent identity: {relative}")
    if request["execution_allowed"] is not False:
        raise ValueError("execution allowed")
    if request["numerical_execution_allowed"] is not False:
        raise ValueError("numerical execution allowed")
    if request["unique_execution_key"] is not None:
        raise ValueError("source-only intent has a key")
    if any(request["source_only_counts"].values()):
        raise ValueError("source-only count is nonzero")
    if request["boundary_compared"] is not False:
        raise ValueError("unexecuted boundary marked compared")
    if request["historical_sparse_red"]["result"] != "RED":
        raise ValueError("historical RED changed")
    if any(
        item["dynamic_steps"] is not None or item["sparse_exponential_actions"] is not None
        for item in request["prior_constructor_reds"]
    ):
        raise ValueError("historical UNKNOWN counters changed")
    static_result = static_inspector.verify()
    if static_result["boundary_coordinates"] != request["boundary"]["coordinate_denominator"]:
        raise ValueError("boundary denominator")
    return {
        "status": "PASS_SOURCE_ONLY_BOUNDARY_HOLD",
        "parent_bindings": len(PARENT_BINDINGS),
        "boundary_coordinates": 68105,
        "numerical_calls": 0,
    }


def main():
    print(json.dumps(verify(), sort_keys=True))


if __name__ == "__main__":
    main()
