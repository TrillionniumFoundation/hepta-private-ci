"""Fresh-process canonical restore for the candidate output capsule."""

import argparse
import hashlib
from pathlib import Path

from qualification.hcsn_currentstate_n128_thirdcycle_numeric.io import write_f64le, write_json
from qualification.hcsn_currentstate_n128_thirdcycle_serializer import independent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--capsule", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=False)
    raw = Path(args.capsule).read_bytes()
    decoded = independent.decode(raw)
    count, coordinate_hash = write_f64le(
        root / "COORDINATES.f64le", independent.coordinates(decoded)
    )
    if (
        decoded["time"].numerator,
        decoded["time"].denominator,
        len(decoded["state"]),
        len(decoded["packets"]),
        count,
    ) != (401, 1000, 1975, 25, 1151028):
        raise ValueError("fresh restore denominator")
    result = {
        "status": "PASS_FRESH_RESTORE_THIRDCYCLE_NUMERIC_ONLY",
        "capsule_sha256": hashlib.sha256(raw).hexdigest(),
        "capsule_identity": decoded["capsule_identity"],
        "coordinate_count": count,
        "coordinate_sha256": coordinate_hash,
        "dynamic_segments": 0,
        "matrix_exponentials": 0,
        "torch_operations": 0,
        "optimizer_updates": 0,
    }
    write_json(root / "RESULT.json", result)
    print(result)


if __name__ == "__main__":
    main()
