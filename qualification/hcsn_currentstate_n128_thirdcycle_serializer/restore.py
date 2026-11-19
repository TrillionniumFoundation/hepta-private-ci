"""Fresh-process independent restore of the actual projected capsule."""

import argparse
import hashlib
import json
import struct
from fractions import Fraction as F
from pathlib import Path

from qualification.hcsn_currentstate_n128_thirdcycle_serializer import independent


CAPSULE_IDENTITY = "0a2aa32bf4972781bb3dd218a12e8d4a1d3d93f2ea25bbc19d7fcf86f24cae8b"
COORDINATES = 870_739


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--capsule", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    raw = Path(args.capsule).read_bytes()
    decoded = independent.decode(raw)
    if decoded["capsule_identity"] != CAPSULE_IDENTITY or decoded["time"] != F(9, 25):
        raise ValueError("independent projected identity")
    if decoded["nodes"] != 127 or len(decoded["state"]) != 1975 or len(decoded["packets"]) != 22 or decoded["readouts"] != 9:
        raise ValueError("independent projected shape")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    digest = hashlib.sha256()
    count = 0
    with (output / "COORDINATES.f64le").open("wb") as handle:
        for value in independent.coordinates(decoded):
            packed = struct.pack("<d", value)
            handle.write(packed)
            digest.update(packed)
            count += 1
    if count != COORDINATES:
        raise ValueError("independent coordinate denominator")
    result = {"all_closed": False, "capsule_sha256": hashlib.sha256(raw).hexdigest(), "coordinate_comparisons": count, "coordinate_sha256": digest.hexdigest(), "dynamic_segments": 0, "identity": "hcsn-n128-thirdcycle-serializer-20261113-c06d", "matrix_exponentials": 0, "optimizer_updates": 0, "qualification": False, "review_calls": 0, "status": "PASS_INDEPENDENT_COLD_RESTORE_ACTUAL_PARENT_ONLY", "torch_operations": 0}
    (output / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
