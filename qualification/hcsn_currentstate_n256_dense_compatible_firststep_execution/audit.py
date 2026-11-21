"""Independent zero-numerical-call audit of complete raw output."""

import hashlib
import json
from pathlib import Path


EXPECTED = {
    "authentic_distinct_input_file_accesses": 4, "npz_decodes": 1,
    "candidate_boundary_builds": 1, "boundary_container_encodes": 1,
    "boundary_exact_comparisons": 68105, "dynamic_steps": 1,
    "candidate_dense_expm_actions": 2, "candidate_sparse_expm_actions": 0,
    "oracle_reexecutions": 0, "candidate_canonical_encodes": 1,
    "canonical_decodes": 2, "final_exact_comparisons": 69728,
    "torch_calls": 0, "optimizer_steps": 0,
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(output):
    output = Path(output)
    counters = json.loads((output / "COUNTERS.json").read_text())
    result = json.loads((output / "RESULT.json").read_text())
    if counters != EXPECTED:
        raise ValueError("frozen counter budget")
    if sha(output / "REBUILT_BOUNDARY.bin") != "e580e44a679ecf9e2588c989cd4d026e326e7364331c46d1927b00ccada78fd4":
        raise ValueError("rebuilt boundary identity")
    if result["candidate_capsule_sha256"] != sha(output / "CANDIDATE.bin"):
        raise ValueError("candidate publication identity")
    if result["coordinate_comparisons"] != 69728 or result["bitwise_mismatch_coordinates"] != 0:
        raise ValueError("strict final gate")
    if not result["candidate_oracle_bitwise_equal"]:
        raise ValueError("strict equality gate")
    receipt = {
        "schema": "hcsn-n256-dense-compatible-firststep-audit-v1",
        "status": "PASS", "comparisons": 69728, "mismatches": 0,
        "rebuilt_boundary_sha256": sha(output / "REBUILT_BOUNDARY.bin"),
        "candidate_sha256": sha(output / "CANDIDATE.bin"),
        "numerical_calls": 0, "torch_calls": 0, "optimizer_steps": 0,
        "qualification": False, "all_closed": False,
    }
    (output / "AUDIT.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt
