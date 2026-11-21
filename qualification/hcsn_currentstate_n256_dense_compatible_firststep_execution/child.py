"""The only numerical child for the single frozen attempt."""

import json
import math
import struct
import sys
import traceback
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = Path(sys.argv[1])
BOUNDARY_ZIP = ROOT / "qualification/hcsn_currentstate_n256_authentic_boundary_attempt002/evidence/originals/artifact.zip"
ORACLE_ZIP = ROOT / "qualification/hcsn_currentstate_n256_firststep_dense_oracle_dispatch_bridge/evidence/run44848445922/ARTIFACT.zip"


def write(name, value):
    (OUTPUT / name).write_text(json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n")


def main():
    counters = {
        "authentic_distinct_input_file_accesses": 0, "npz_decodes": 0,
        "candidate_boundary_builds": 0, "boundary_container_encodes": 0,
        "boundary_exact_comparisons": 0, "dynamic_steps": 0,
        "candidate_dense_expm_actions": 0, "candidate_sparse_expm_actions": 0,
        "oracle_reexecutions": 0, "candidate_canonical_encodes": 0,
        "canonical_decodes": 0, "final_exact_comparisons": 0,
        "torch_calls": 0, "optimizer_steps": 0,
    }
    try:
        from qualification.hcsn_currentstate_n256_dense_compatible_firststep_intent import candidate
        from qualification.hcsn_currentstate_n256_firststep_serializer_v2.serializer import (
            coordinate_rows, decode, publish_atomic,
        )

        reference = candidate._zip_member(BOUNDARY_ZIP, candidate.BOUNDARY_ZIP_SHA256, candidate.BOUNDARY_MEMBER, candidate.BOUNDARY_SHA256)
        oracle_raw = candidate._zip_member(ORACLE_ZIP, candidate.ORACLE_ZIP_SHA256, candidate.ORACLE_MEMBER, candidate.ORACLE_SHA256)
        np, sparse, scipy_expm = candidate._numeric_modules()

        def counted_expm(matrix):
            counters["candidate_dense_expm_actions"] += 1
            return scipy_expm(matrix)

        rebuilt, state, pending = candidate._build_boundary_and_structure(ROOT, np, sparse)
        counters.update(authentic_distinct_input_file_accesses=4, npz_decodes=1, candidate_boundary_builds=1, boundary_container_encodes=1)
        candidate._publish_bytes(OUTPUT / "REBUILT_BOUNDARY.bin", rebuilt)
        counters["boundary_exact_comparisons"] = candidate.require_exact_boundary(reference, rebuilt)
        oracle = decode(oracle_raw, candidate.MAX_CAPSULE_BYTES)
        counters["canonical_decodes"] += 1
        envelope = candidate._candidate_envelope(oracle, rebuilt, state, pending, np, counted_expm)
        counters["dynamic_steps"] = 1
        candidate_sha = publish_atomic(OUTPUT / "CANDIDATE.bin", envelope)
        counters["candidate_canonical_encodes"] = 1
        actual = decode((OUTPUT / "CANDIDATE.bin").read_bytes(), candidate.MAX_CAPSULE_BYTES)
        counters["canonical_decodes"] += 1
        left, right = coordinate_rows(oracle), coordinate_rows(actual)
        if [(a, b) for a, b, _ in left] != [(a, b) for a, b, _ in right]:
            raise ValueError("candidate/oracle coordinate identity")
        mismatch, maximum, maximum_ulp = 0, 0.0, 0
        for (_, _, expected), (_, _, observed) in zip(left, right):
            counters["final_exact_comparisons"] += 1
            mismatch += expected != observed
            a, b = struct.unpack("<d", expected)[0], struct.unpack("<d", observed)[0]
            if not math.isfinite(a) or not math.isfinite(b):
                raise ValueError("non-finite comparison coordinate")
            maximum = max(maximum, abs(a - b))
            maximum_ulp = max(maximum_ulp, abs(candidate._ordered_int(expected) - candidate._ordered_int(observed)))
        result = {
            "schema": "hcsn-n256-dense-compatible-firststep-result-v1",
            "candidate_capsule_sha256": candidate_sha,
            "coordinate_comparisons": len(left),
            "bitwise_mismatch_coordinates": mismatch,
            "max_abs_error_hex": maximum.hex(),
            "max_ulp_distance": maximum_ulp,
            "candidate_oracle_bitwise_equal": mismatch == 0,
            "qualification": False,
            "all_closed": False,
        }
        write("RESULT.json", result)
        if mismatch:
            raise ValueError("strict bitwise gate")
        return 0
    except BaseException as error:
        write("CHILD_ERROR.json", {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()})
        raise
    finally:
        write("COUNTERS.json", counters)


if __name__ == "__main__":
    raise SystemExit(main())
