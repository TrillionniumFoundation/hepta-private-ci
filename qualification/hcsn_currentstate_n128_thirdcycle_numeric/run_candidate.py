"""Execute the separately frozen candidate process."""

import argparse
import hashlib
from pathlib import Path

from qualification.hcsn_currentstate_n128_thirdcycle_numeric import candidate_numeric
from qualification.hcsn_currentstate_n128_thirdcycle_numeric.io import write_f64le, write_json
from qualification.hcsn_currentstate_n128_thirdcycle_serializer import format as capsule_format


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--law", required=True)
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--npz", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=False)
    capsule, cost = candidate_numeric.run(
        args.start, args.law, args.metadata, args.npz
    )
    raw = capsule_format.dump(capsule)
    capsule_path = root / "CAPSULE.bin"
    capsule_path.write_bytes(raw)
    count, coordinate_hash = write_f64le(
        root / "COORDINATES.f64le", capsule_format.coordinates(capsule)
    )
    if count != cost["coordinate_denominator"]:
        raise ValueError("candidate coordinate count")
    result = {
        "status": "PASS_CANDIDATE_THIRDCYCLE_NUMERIC_ONLY",
        "capsule_bytes": len(raw),
        "capsule_sha256": hashlib.sha256(raw).hexdigest(),
        "capsule_identity": capsule.capsule_identity,
        "coordinate_count": count,
        "coordinate_sha256": coordinate_hash,
        "dynamic_segments": cost["candidate_dynamic_segments"],
        "matrix_exponentials": cost["candidate_matrix_exponentials"],
        "packets": cost["candidate_packets"],
        "target4_packets": cost["candidate_target4_packets"],
        "torch_operations": 0,
        "optimizer_updates": 0,
    }
    write_json(root / "RESULT.json", result)
    print(result)


if __name__ == "__main__":
    main()
