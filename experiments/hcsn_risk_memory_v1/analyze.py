"""Reuse the frozen fixed128 audit and gates with explicit profile disclosure."""

import argparse
import json
from pathlib import Path

from .train_equivalence import PACKAGE, sha, verify, write


def analyze(protocol_path, study, output, equal_cpu_analysis=None):
    from experiments.hcsn_risk_ablation_v1 import equal_updates_analysis as original
    from .model import build_model

    protocol = json.loads(protocol_path.read_bytes())
    verify(protocol)
    if output.exists():
        raise FileExistsError("Preserve previous analyses")
    if protocol["schema"] != "hcsn-risk-memory-profile-fixed128.v1":
        raise ValueError("Fresh memory-profile cohort required")
    original_factory = original.build_model
    original.build_model = build_model
    try:
        result = original.analyze(protocol_path, study, output / "frozen_contract", equal_cpu_analysis)
    finally:
        original.build_model = original_factory
    result.update(schema="hcsn-risk-memory-profile-fixed128-analysis.v1",
        numerical_profile=protocol["model_identity"]["numerical_profile"],
        numerical_revision=protocol["numerical_revision"],
        implementation_disclosure=protocol["joint_inference"]["numerical_implementation_disclosure"],
        frozen_contract_analysis_sha256=sha(output / "frozen_contract/RESULTS.json"),
        original_failed_cohort_pooled=False,
        full_128_update_trajectory_bitwise_equivalence_established=False)
    write(output / "RESULTS.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=PACKAGE / "PROTOCOL.json")
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--equal-cpu-analysis", type=Path)
    args = parser.parse_args()
    result = analyze(args.protocol.resolve(), args.study.resolve(), args.output.resolve(), args.equal_cpu_analysis)
    print(json.dumps({key: result[key] for key in
        ("integrity_passed", "searches", "gates_passed", "numerical_profile")}))
