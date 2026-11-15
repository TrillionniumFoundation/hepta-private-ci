"""Project the exact #6285 capsule into the frozen three-generation schema."""

import argparse
import hashlib
import json
import struct
from fractions import Fraction as F
from pathlib import Path

from qualification.hcsn_currentstate_n128_engineering import candidate
from qualification.hcsn_currentstate_n128_thirdcycle_serializer import format


START_SHA256 = "228c4ddc4b45627fe54874cd087f2bbf8c21a4e3752a6d3e6202243967c3194a"
CAPSULE_IDENTITY = "0a2aa32bf4972781bb3dd218a12e8d4a1d3d93f2ea25bbc19d7fcf86f24cae8b"
COORDINATES = 870_739


def expand_state(values):
    values = tuple(values)
    offset = 0
    active = values[offset : offset + 5 * 2 * 127]
    offset += 5 * 2 * 127
    upper = values[offset : offset + 5 * 3]
    offset += 5 * 3
    mass = values[offset : offset + 5 * 2]
    offset += 5 * 2
    hit = values[offset : offset + 5 * 2]
    offset += 5 * 2
    occupation = values[offset : offset + 5 * 3]
    offset += 5 * 3
    if offset != len(values):
        raise ValueError("parent state layout")
    active3 = tuple(active[channel * 254 : (channel + 1) * 254] + (0.0,) * 127 for channel in range(5))
    upper4 = tuple(upper[channel * 3 : (channel + 1) * 3] + (0.0,) for channel in range(5))
    mass3 = tuple(mass[channel * 2 : (channel + 1) * 2] + (0.0,) for channel in range(5))
    hit3 = tuple(hit[channel * 2 : (channel + 1) * 2] + (0.0,) for channel in range(5))
    occupation4 = tuple(occupation[channel * 3 : (channel + 1) * 3] + (0.0,) for channel in range(5))
    return tuple(value for group in (*active3, *upper4, *mass3, *hit3, *occupation4) for value in group)


def write_coordinates(path, values):
    digest = hashlib.sha256()
    count = 0
    with Path(path).open("wb") as handle:
        for value in values:
            raw = struct.pack("<d", value)
            handle.write(raw)
            digest.update(raw)
            count += 1
    return count, digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    raw = Path(args.start).read_bytes()
    if hashlib.sha256(raw).hexdigest() != START_SHA256:
        raise ValueError("#6285 capsule hash")
    parent = candidate.load(raw)
    if parent.time != F(9, 25) or len(parent.state) != 1320 or len(parent.packets) != 22:
        raise ValueError("#6285 capsule coordinates")
    readouts = parent.readouts + (candidate.Readout(0, 8, parent.time, CAPSULE_IDENTITY),)
    capsule = format.ThirdCycleCapsule(parent.roster_identity, parent.input_hashes, CAPSULE_IDENTITY, parent.lane, parent.time, parent.interior_nodes, readouts, expand_state(parent.state), parent.packets)
    container = format.dump(capsule)
    if format.load(container) != capsule:
        raise ValueError("primary cold roundtrip")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "CAPSULE.bin").write_bytes(container)
    count, coordinate_sha = write_coordinates(output / "COORDINATES.f64le", format.coordinates(capsule))
    if count != COORDINATES:
        raise ValueError("coordinate denominator")
    result = {"all_closed": False, "capsule_bytes": len(container), "capsule_sha256": hashlib.sha256(container).hexdigest(), "coordinate_comparisons": count, "coordinate_sha256": coordinate_sha, "dynamic_segments": 0, "identity": "hcsn-n128-thirdcycle-serializer-20261113-c06d", "matrix_exponentials": 0, "optimizer_updates": 0, "packets": len(capsule.packets), "qualification": False, "state_scalars": len(capsule.state), "status": "PASS_THIRDCYCLE_SERIALIZER_ACTUAL_PARENT_ONLY", "torch_operations": 0}
    (output / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
