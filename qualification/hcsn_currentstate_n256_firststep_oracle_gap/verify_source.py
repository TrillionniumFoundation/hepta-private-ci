"""Fail-closed verifier for the source-only N256 oracle-gap review."""

import hashlib
import json
from pathlib import Path

from qualification.hcsn_currentstate_n256_firststep_oracle_gap.static_review import (
    review,
)


ROOT = Path(__file__).parent
REPOSITORY = ROOT.parents[1]
PATHS = {
    "candidate_sha256": REPOSITORY / "qualification/hcsn_currentstate_n256_sparse_dynamic_v2_intent/sparse_dynamic.py",
    "input_adapter_sha256": REPOSITORY / "qualification/hcsn_currentstate_n256_independent_oracle_v2_intent/adapter.py",
    "legacy_oracle_sha256": REPOSITORY / "qualification/hcsn_currentstate_n256_independent_oracle_intent/independent_oracle.py",
    "serializer_v2_sha256": REPOSITORY / "qualification/hcsn_currentstate_n256_firststep_serializer_v2/serializer.py",
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    request = json.loads((ROOT / "REQUEST.json").read_text())
    freeze = json.loads((ROOT / "SOURCE_FREEZE.json").read_text())
    development_red = json.loads((ROOT / "DEVELOPMENT_RED.json").read_text())
    observed = review(PATHS["candidate_sha256"], PATHS["input_adapter_sha256"], PATHS["legacy_oracle_sha256"])
    if request["source_bindings"] != {name: digest(path) for name, path in PATHS.items()}:
        raise ValueError("reviewed source binding mismatch")
    if freeze["request_sha256"] != digest(ROOT / "REQUEST.json"):
        raise ValueError("request freeze mismatch")
    if freeze["static_review_sha256"] != digest(ROOT / "static_review.py"):
        raise ValueError("static review freeze mismatch")
    if freeze["tests_sha256"] != digest(ROOT / "test_static_review.py"):
        raise ValueError("test freeze mismatch")
    if freeze["development_red_sha256"] != digest(ROOT / "DEVELOPMENT_RED.json"):
        raise ValueError("development RED freeze mismatch")
    if development_red["preserved"] is not True or any(
        development_red[field] != 0
        for field in (
            "n256_serializer_calls",
            "dynamic_steps",
            "matrix_exponential_actions",
            "torch_calls",
            "optimizer_steps",
        )
    ):
        raise ValueError("development RED is not preserved as zero numerical work")
    candidate = observed["candidate"]
    legacy = observed["legacy_oracle"]
    adapter = observed["adapter"]
    if not all(
        candidate[field]
        for field in (
            "packet_has_output",
            "advance_accepts_pending",
            "template_reads_packet_output",
            "run_lane_accepts_pending",
            "capsule_has_packets",
        )
    ):
        raise ValueError("candidate current-state packet surface changed")
    if any(
        legacy[field]
        for field in (
            "packet_has_output",
            "advance_accepts_pending",
            "run_lane_accepts_pending",
            "coordinate_stream_mentions_packet",
            "imports_serializer",
        )
    ):
        raise ValueError("legacy oracle gap observation changed")
    if observed["legacy_oracle_current_state_compatible"] is not False:
        raise ValueError("legacy oracle unexpectedly classified compatible")
    if adapter["numerical_import_roots"] or adapter["has_numeric_propagation_entry"]:
        raise ValueError("input adapter unexpectedly performs numerical propagation")
    gap = request["observed_gap"]
    if gap != {
        "candidate_packet_output": True,
        "candidate_pending_packet_continuation": True,
        "input_adapter_numerical_propagation": False,
        "legacy_oracle_packet_output": False,
        "legacy_oracle_pending_packet_continuation": False,
        "legacy_oracle_packet_coordinate_stream": False,
        "legacy_oracle_current_state_compatible": False,
    }:
        raise ValueError("request does not preserve observed gap")
    if set(request["future_sources"].values()) != {None} or set(request["required_future_admission"].values()) != {None}:
        raise ValueError("future source or admission unexpectedly populated")
    exact_zero = (
        "n256_serializer_calls",
        "dynamic_steps",
        "matrix_exponential_actions",
        "torch_calls",
        "optimizer_steps",
    )
    if any(request[field] != 0 or freeze[field] != 0 for field in exact_zero):
        raise ValueError("source review claims numerical work")
    if request["n256_numerical_execution_allowed"] is not False:
        raise ValueError("source review authorizes N256 execution")
    if any(request[field] is not False for field in ("largegrid_qualification", "production_adoption", "all_closed")):
        raise ValueError("source review grants qualification")
    print(json.dumps({
        "status": request["status"],
        "identity": request["identity"],
        "legacy_oracle_current_state_compatible": False,
        "future_oracle_source_sha256": None,
        "n256_serializer_calls": 0,
        "dynamic_steps": 0,
        "matrix_exponential_actions": 0,
        "torch_calls": 0,
        "optimizer_steps": 0,
        "all_closed": False,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
