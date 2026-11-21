"""Verify every frozen source and parent byte without numerical imports."""

import hashlib
import json
import os
from pathlib import Path

from qualification.hcsn_currentstate_n256_authentic_boundary_attempt002 import static_inspector


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REPOSITORY = Path.cwd()
BUILDER_ROOT = Path(os.environ.get("HCSN_BUILDER_PARENT_ROOT", REPOSITORY))
BOUNDARY_ROOT = Path(os.environ.get("HCSN_BOUNDARY_PARENT_ROOT", REPOSITORY))
PARENT_HASHES = {
    "qualification/hcsn_currentstate_n256_authentic_boundary_builders_v2/REQUEST.json": "0b7204c70d0e8b866f1f2f7023ed22428999f39980a4a6707f51466a85b258df",
    "qualification/hcsn_currentstate_n256_authentic_boundary_builders_v2/SOURCE_FREEZE.json": "3b17d7bd829a5a94b6b85001bd49d46915d8324f190b67123eac01d80869c638",
    "qualification/hcsn_currentstate_n256_authentic_boundary_builders_v2/candidate_boundary_builder.py": "3310210cd9cd28e1199041fc6fe47702ac7f1fcf4fb7d661855a05cce77f4ece",
    "qualification/hcsn_currentstate_n256_authentic_boundary_builders_v2/compare_runner.py": "7347cd8666473ac1e698bef8e8c4f65e4ff79e570d895f351e82f0ea03126dd7",
    "qualification/hcsn_currentstate_n256_authentic_boundary_builders_v2/oracle_boundary_builder.py": "31b0decd9e7d4c892f2936ff8960ac8fc493f347bf671db51e9f8578bace5acd",
}
BOUNDARY_HASHES = {
    "qualification/hcsn_currentstate_n256_boundary_container_contract/boundary_codec.py": "70ac907077417ca4164ad749b736f395b2deebdd1fd8af08c316eee042db6232",
    "qualification/hcsn_currentstate_n256_boundary_container_contract/compare_boundary.py": "f1b31f953d1ac17c4ac99be3cf71157dda5fa133415680f36566edf318596a00",
}
REPOSITORY_HASHES = {
    "qualification/hcsn_currentstate_n256_firststep_dense_oracle_hosted/requirements.txt": "1668a3152e33680d94637b13421c15e68bd97cd8701f7f555c691f5bc5c0b9f3",
    "qualification/hcsn_n256_new_export/evidence/attempt001/METADATA.json": "88e84dd3aea396d34c7e2dd08d31f2e30bf694c20516dccde57e6dd1b0c2a3c6",
    "qualification/hcsn_n256_new_export/evidence/attempt001/N256_STATE.json": "360b4bf446e853209c58cdb3faded74d9114d872cfb9c730b220d14cef670f9c",
    "qualification/hcsn_n256_new_export/evidence/attempt001/N256_PHASE.json": "790fabee8825dbd4361f157f56d78641430fe50b9134cd2cb7b02b51b93fe548",
    "qualification/hcsn_n256_new_export/evidence/attempt001/N256_STATE.npz.b64": "926191319021c51421dd15d76c66c3b5c6d2efef0f28af3f76c893065a49dbeb",
}


def _verify(root, expected):
    for relative, digest in expected.items():
        if hashlib.sha256((root / relative).read_bytes()).hexdigest() != digest:
            raise ValueError(f"frozen byte identity: {relative}")


def verify():
    request = json.loads((HERE / "REQUEST.json").read_text())
    freeze = json.loads((HERE / "SOURCE_FREEZE.json").read_text())
    if request["parent_commit"] != "c32fb369b43701b74a40ad45b9f5f1e8a142602b":
        raise ValueError("parent commit")
    if request["unique_execution_key"] != "hcsn-n256-authentic-boundary-hosted-20261121-c06d-002":
        raise ValueError("execution key")
    if request["historical_sparse_red_preserved"]["result"] != "RED":
        raise ValueError("historical RED")
    attempt001 = request["attempt001_red_preserved"]
    if (
        attempt001["result"] != "RED"
        or attempt001["audit_status"] != "INCOMPLETE"
        or attempt001["output_containers"] != 0
    ):
        raise ValueError("attempt001 provenance")
    repair = request["source_repair_parent"]
    if repair["commit"] != request["parent_commit"] or not repair["applied_symmetrically"]:
        raise ValueError("repair parent")
    if request["c2_full_replay_completed_fits"] or request["hpca_update"] != "NoUpdate":
        raise ValueError("scope boundary")
    _verify(BUILDER_ROOT, PARENT_HASHES)
    _verify(BOUNDARY_ROOT, BOUNDARY_HASHES)
    _verify(REPOSITORY, REPOSITORY_HASHES)
    _verify(ROOT, freeze["files"])
    static_inspector.verify()
    return "PASS_ATTEMPT002_PRECOMMIT"


if __name__ == "__main__":
    print(verify())
