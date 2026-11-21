"""Standard-library preexecution binding for the one permitted comparison."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).parents[2]
HERE = Path(__file__).parent
EXPECTED_PATHS = {
    ".github/workflows/hepta-contract-gate.yml",
    "qualification/hcsn_currentstate_n256_firststep_candidate_compare/README.md",
    "qualification/hcsn_currentstate_n256_firststep_candidate_compare/REQUEST.json",
    "qualification/hcsn_currentstate_n256_firststep_candidate_compare/__init__.py",
    "qualification/hcsn_currentstate_n256_firststep_candidate_compare/compare.py",
    "qualification/hcsn_currentstate_n256_firststep_candidate_compare/run.py",
    "qualification/hcsn_currentstate_n256_firststep_candidate_compare/test_source.py",
    "qualification/hcsn_currentstate_n256_firststep_candidate_compare/verify_source.py",
    "qualification/hcsn_currentstate_n256_sparse_dynamic_v2_intent/sparse_dynamic.py",
    "qualification/hcsn_currentstate_n256_engineering/candidate.py",
    "qualification/hcsn_currentstate_n256_firststep_serializer_v2/serializer.py",
    "qualification/hcsn_currentstate_n256_independent_oracle_v2_intent/adapter.py",
    "qualification/hcsn_currentstate_n256_firststep_dense_oracle_dispatch_bridge/evidence/run44848445922/ARTIFACT.zip",
}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    freeze = json.loads((HERE / "SOURCE_FREEZE.json").read_text())
    request = json.loads((HERE / "REQUEST.json").read_text())
    if freeze.get("schema") != "hcsn-n256-warm1-candidate-oracle-compare-scipy17-repair-freeze-v1":
        raise ValueError("source freeze schema")
    if freeze.get("parent_commit") != "42aa0ba6153b46c197775634a18db15589ddb199":
        raise ValueError("evidence parent identity")
    files = freeze.get("files")
    if not isinstance(files, dict) or set(files) != EXPECTED_PATHS:
        raise ValueError("source freeze path set")
    observed = {name: _sha(ROOT / name) for name in files}
    if observed != files:
        raise ValueError("source freeze byte mismatch")
    exact = {
        "schema": "hcsn-n256-warm1-candidate-oracle-compare-scipy17-repair-request-v1",
        "identity": "hcsn-n256-warm1-candidate-oracle-compare-scipy17-repair-20261120-c06d-001",
        "unique_execution_key": "hcsn-n256-firststep-candidate-scipy17-repair-hosted-20261120-c06d-001",
        "exact_head_branch": "research/hcsn-n256-firststep-candidate-scipy17-repair-20261120-c06d",
        "maximum_attempts": 1,
        "prior_numerical_attempts": 1,
        "oracle_artifact_zip_sha256": "3ba4ef88608cbfc04d83fd82c1f05d7b439edf4f9338365625e79b0d52f02400",
        "oracle_capsule_sha256": "b2a6e204e613fead7c0735b12a335a88d2394c8f4da99cab798133443c55dc18",
        "input_bundle_sha256": "17086fb6ba83211e8626c7ac9c22183f6c9c9a7dc615772b5a32d2c14ecb8e95",
    }
    for name, value in exact.items():
        if request.get(name) != value:
            raise ValueError(f"request mismatch: {name}")
    prior = request.get("prior_red")
    if prior != {
        "source_commit": "a3373921a0193336837d217c24d0d35dccd9a5ad",
        "run_id": 44849987440,
        "job_id": 136678793301,
        "artifact_id": 14684118589,
        "artifact_zip_sha256": "a922989c369eddf6685f273334fcad5d02b464a1cec21607f98d9f1f400ccf0a",
        "evidence_commit": "e081b8bc9faf64b3ee22a292cd1787f3a48345dc",
        "executed_dynamic_steps": None,
        "executed_sparse_exponential_actions": None,
    }:
        raise ValueError("prior RED or UNKNOWN counters changed")
    if request.get("gate") != {
        "coordinate_identity_equal": True,
        "candidate_oracle_bitwise_equal": True,
        "signed_error_cancellation_allowed": False,
        "threshold_relaxation_allowed": False,
    }:
        raise ValueError("exact comparison gate")
    if freeze.get("prior_red") != request.get("prior_red"):
        raise ValueError("prior RED binding")
    if any(request["precommit_counts"].values()):
        raise ValueError("precommit numerical work claimed")
    if request.get("historical_negative_and_unknown_preserved") is not True:
        raise ValueError("historical negative or UNKNOWN erased")
    if request.get("largegrid_qualification") is not False or request.get("all_closed") is not False:
        raise ValueError("source self-grants qualification")
    print(json.dumps({
        "status": "PASS_SOURCE_FREEZE", "files": len(files),
        "oracle_reexecutions": 0, "candidate_dynamic_steps": 0,
        "candidate_sparse_exponential_actions": 0,
        "torch_calls": 0, "optimizer_steps": 0,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
