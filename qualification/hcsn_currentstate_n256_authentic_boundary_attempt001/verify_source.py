"""Verify every frozen source and parent byte without numerical imports."""

import hashlib
import json
import os
from pathlib import Path

from qualification.hcsn_currentstate_n256_authentic_boundary_attempt001 import static_inspector


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REPOSITORY = Path.cwd()
BUILDER_ROOT = Path(os.environ.get("HCSN_BUILDER_PARENT_ROOT", REPOSITORY))
BOUNDARY_ROOT = Path(os.environ.get("HCSN_BOUNDARY_PARENT_ROOT", REPOSITORY))
PARENT_HASHES = {
    "qualification/hcsn_currentstate_n256_authentic_boundary_builders/REQUEST.json": "b55ce65e1991618d592aaee824fd030e2311af75f2bbcb247caf8a765a1743ea",
    "qualification/hcsn_currentstate_n256_authentic_boundary_builders/SOURCE_FREEZE.json": "ff0aa23339ac3afe2c494127d11f7b36d292f87409d7fb34d2968e869717e82d",
    "qualification/hcsn_currentstate_n256_authentic_boundary_builders/candidate_boundary_builder.py": "5e0f2dc706f201d2378aeb6be500e6e6b8a33227800a20391a493b02348d3f63",
    "qualification/hcsn_currentstate_n256_authentic_boundary_builders/compare_runner.py": "8bc839e5678f8cb60b98d1ee07c58867a5197bb49dcdb22435d358719f68140c",
    "qualification/hcsn_currentstate_n256_authentic_boundary_builders/oracle_boundary_builder.py": "23e1c7b7ed339d917202e9d3c71bb4e22339c6bb6dbacd9c697cd20cec301dff",
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
    if request["parent_commit"] != "24bfb1df76ddb05b7e5d742a9bd0ab9b35feccf5":
        raise ValueError("parent commit")
    if request["unique_execution_key"] != "hcsn-n256-authentic-boundary-hosted-20261121-c06d-001":
        raise ValueError("execution key")
    if request["historical_sparse_red_preserved"]["result"] != "RED":
        raise ValueError("historical RED")
    if request["c2_full_replay_completed_fits"] or request["hpca_update"] != "NoUpdate":
        raise ValueError("scope boundary")
    _verify(BUILDER_ROOT, PARENT_HASHES)
    _verify(BOUNDARY_ROOT, BOUNDARY_HASHES)
    _verify(REPOSITORY, REPOSITORY_HASHES)
    _verify(ROOT, freeze["files"])
    static_inspector.verify()
    return "PASS_ATTEMPT001_PRECOMMIT"


if __name__ == "__main__":
    print(verify())
