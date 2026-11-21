"""Verify source freeze, parent bindings, and zero authentic execution."""

import hashlib
import json
import os
from pathlib import Path

from qualification.hcsn_currentstate_n256_authentic_boundary_builders import (
    static_inspector,
)


HERE = Path(__file__).resolve().parent
SOURCE_ROOT = HERE.parents[1]
PARENT_ROOT = Path.cwd()
BOUNDARY_ROOT = Path(os.environ.get("HCSN_BOUNDARY_PARENT_ROOT", PARENT_ROOT))
PARENT_BINDINGS = {
    "qualification/hcsn_currentstate_n256_boundary_container_contract/boundary_codec.py":
        "70ac907077417ca4164ad749b736f395b2deebdd1fd8af08c316eee042db6232",
    "qualification/hcsn_currentstate_n256_boundary_container_contract/compare_boundary.py":
        "f1b31f953d1ac17c4ac99be3cf71157dda5fa133415680f36566edf318596a00",
    "qualification/hcsn_currentstate_n256_dense_compatible_action_boundary_intent/action_boundary.py":
        "941d0e7d2d17853208504aea9c649fdac4a59ee55a17cce64834f92288e2b08f",
    "qualification/hcsn_currentstate_n256_firststep_dense_oracle_source/dense_oracle.py":
        "a3aa6a95cd55d254d9fa911d10768d1ec827e2374265a5b0474e0d6243929bfa",
    "qualification/hcsn_currentstate_n256_sparse_dynamic_v2_intent/sparse_dynamic.py":
        "6d3fea2b230bc7abc28df3d4d3c8f28ceaa163d9961ef2db8a7e369eee1f4816",
    "qualification/hcsn_currentstate_n256_engineering/candidate.py":
        "91c55d87fd993c9d01d1b1e98ba855bf171dfd74f2bdc12bd94fc23d9dc7a9d3",
    "qualification/hcsn_currentstate_n256_independent_oracle_v2_intent/adapter.py":
        "311eeeb69ba5002171d3aa765610bc9caea1cb2942309ba6e67543297cb74084",
    "qualification/hcsn_n256_new_export/evidence/attempt001/METADATA.json":
        "88e84dd3aea396d34c7e2dd08d31f2e30bf694c20516dccde57e6dd1b0c2a3c6",
    "qualification/hcsn_n256_new_export/evidence/attempt001/N256_STATE.json":
        "360b4bf446e853209c58cdb3faded74d9114d872cfb9c730b220d14cef670f9c",
    "qualification/hcsn_n256_new_export/evidence/attempt001/N256_PHASE.json":
        "790fabee8825dbd4361f157f56d78641430fe50b9134cd2cb7b02b51b93fe548",
    "qualification/hcsn_n256_new_export/evidence/attempt001/N256_STATE.npz.b64":
        "926191319021c51421dd15d76c66c3b5c6d2efef0f28af3f76c893065a49dbeb",
}


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify():
    request = json.loads((HERE / "REQUEST.json").read_text())
    freeze = json.loads((HERE / "SOURCE_FREEZE.json").read_text())
    if request["parent_commit"] != "793a4824779415804be9fb336005d43d7e1ee325":
        raise ValueError("parent commit")
    if request["parent_tree"] != "81d6ae90bdfb2829b6eaa39c5299022beb201ba4":
        raise ValueError("parent tree")
    if request["execution_allowed"] or request["numerical_execution_allowed"]:
        raise ValueError("execution must remain disabled")
    if request["unique_execution_key"] is not None:
        raise ValueError("source-only key")
    if any(request["source_only_counts"].values()):
        raise ValueError("source-only counters")
    boundary = request["boundary"]
    if (
        boundary["coordinates"] != 68105
        or boundary["payload_total_bytes"] != 544840
        or boundary["canonical_container_bytes_each"] != 545171
        or boundary["mismatch_allowance"] != 0
    ):
        raise ValueError("boundary envelope")
    if request["boundary_built"] or request["boundary_compared"]:
        raise ValueError("authentic boundary claim")
    if request["qualification"] or request["all_closed"]:
        raise ValueError("qualification claim")
    for relative, expected in PARENT_BINDINGS.items():
        root = BOUNDARY_ROOT if "boundary_container_contract" in relative else PARENT_ROOT
        if _digest(root / relative) != expected:
            raise ValueError(f"parent binding: {relative}")
    expected_sources = {
        path.relative_to(SOURCE_ROOT).as_posix()
        for path in HERE.iterdir()
        if path.is_file() and path.name != "SOURCE_FREEZE.json"
    }
    if set(freeze["source_sha256"]) != expected_sources:
        raise ValueError("complete source freeze")
    for relative, expected in freeze["source_sha256"].items():
        if _digest(SOURCE_ROOT / relative) != expected:
            raise ValueError(f"source digest: {relative}")
    static = static_inspector.verify()
    if static["authentic_builder_calls"] or static["propagation_calls"]:
        raise ValueError("static execution count")
    return {
        "status": "PASS_AUTHENTIC_BUILDER_SOURCE_HOLD",
        "boundary_coordinates": 68105,
        "canonical_container_bytes": 545171,
        "qualification": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True))
