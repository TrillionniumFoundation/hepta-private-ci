"""Execute the separately implemented dense-oracle process."""

import argparse
from pathlib import Path

from qualification.hcsn_currentstate_n128_thirdcycle_numeric import oracle_numeric
from qualification.hcsn_currentstate_n128_thirdcycle_numeric.io import write_f64le, write_json


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
    result, cost = oracle_numeric.run(args.start, args.law, args.metadata, args.npz)
    count, coordinate_hash = write_f64le(
        root / "COORDINATES.f64le", oracle_numeric.coordinates(result)
    )
    if count != cost["coordinate_denominator"]:
        raise ValueError("oracle coordinate count")
    summary = {
        "status": "PASS_INDEPENDENT_DENSE_ORACLE_THIRDCYCLE_ONLY",
        "coordinate_count": count,
        "coordinate_sha256": coordinate_hash,
        "dynamic_segments": cost["oracle_dynamic_segments"],
        "matrix_exponentials": cost["oracle_matrix_exponentials"],
        "packets": cost["oracle_packets"],
        "target4_packets": cost["oracle_target4_packets"],
        "torch_operations": 0,
        "optimizer_updates": 0,
    }
    write_json(root / "RESULT.json", summary)
    print(summary)


if __name__ == "__main__":
    main()
