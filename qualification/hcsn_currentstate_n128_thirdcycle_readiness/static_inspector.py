"""Pure-stdlib inspection of the frozen #6285 terminal capsule and source."""

import argparse
import hashlib
import json
import struct
from fractions import Fraction as F
from pathlib import Path


IDENTITY = "hcsn-n128-thirdcycle-readiness-20261113-c06d"
KEY = IDENTITY + "-001"
PARENT = "7883eac90ee882b6a0d453452582860dfb47b517"
CAPSULE_SHA256 = "228c4ddc4b45627fe54874cd087f2bbf8c21a4e3752a6d3e6202243967c3194a"
MAGIC = b"HCSNN128"
SECTION_IDS = (1, 2, 3, 4, 5)


class Cursor:
    def __init__(self, raw):
        self.raw = raw
        self.offset = 0

    def take(self, size):
        if self.offset + size > len(self.raw):
            raise ValueError("truncated capsule")
        value = self.raw[self.offset : self.offset + size]
        self.offset += size
        return value

    def unpack(self, fmt):
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))

    def fraction(self):
        return F(*self.unpack("<qQ"))

    def finish(self):
        if self.offset != len(self.raw):
            raise ValueError("trailing capsule bytes")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sections(raw):
    if hashlib.sha256(raw).hexdigest() != CAPSULE_SHA256:
        raise ValueError("#6285 capsule hash differs")
    if raw[:8] != MAGIC or hashlib.sha256(raw[:-32]).digest() != raw[-32:]:
        raise ValueError("capsule outer identity")
    if struct.unpack("<HHHH", raw[8:16]) != (1, 0x4C45, 5, 236):
        raise ValueError("capsule header")
    cursor = Cursor(raw[16:-32])
    directory = []
    for expected in SECTION_IDS:
        kind, flags, size = cursor.unpack("<HHQ")
        expected_hash = cursor.take(32)
        if (kind, flags) != (expected, 0):
            raise ValueError("capsule section directory")
        directory.append((size, expected_hash))
    result = []
    for size, expected_hash in directory:
        section = cursor.take(size)
        if hashlib.sha256(section).digest() != expected_hash:
            raise ValueError("capsule section hash")
        result.append(section)
    cursor.finish()
    return result


def decode_capsule(raw):
    meta_raw, state_raw, packet_raw, operator_raw, readout_raw = sections(raw)
    meta = Cursor(meta_raw)
    meta.take(64)
    lane, nodes = meta.unpack("<BI")
    logical_time = meta.fraction()
    (input_count,) = meta.unpack("<I")
    for _ in range(input_count):
        (size,) = meta.unpack("<H")
        meta.take(size + 32)
    meta.finish()

    state = Cursor(state_raw)
    (state_count,) = state.unpack("<Q")
    state.take(state_count * 8)
    state.finish()

    operators = Cursor(operator_raw)
    (operator_count,) = operators.unpack("<I")
    dimensions = {}
    for _ in range(operator_count):
        identity = operators.take(32).hex()
        dimension, nnz = operators.unpack("<IQ")
        operators.take((dimension + 1) * 8 + nnz * 4 + nnz * 8)
        dimensions[identity] = dimension
    operators.finish()

    packets = Cursor(packet_raw)
    (packet_count,) = packets.unpack("<I")
    roster = []
    for _ in range(packet_count):
        source = packets.take(32).hex()
        generation, target, origin = packets.unpack("<III")
        start, end = packets.fraction(), packets.fraction()
        operator_id = packets.take(32).hex()
        dimension = dimensions[operator_id]
        packets.take((5 * dimension + dimension) * 8)
        roster.append(
            {
                "source": source,
                "generation": generation,
                "target": target,
                "origin": origin,
                "start": [start.numerator, start.denominator],
                "end": [end.numerator, end.denominator],
                "dimension": dimension,
            }
        )
    packets.finish()

    readouts = Cursor(readout_raw)
    (readout_count,) = readouts.unpack("<I")
    for _ in range(readout_count):
        readouts.take(5)
        readouts.fraction()
        readouts.take(32)
    readouts.finish()
    return lane, nodes, logical_time, state_count, roster


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--capsule")
    args = parser.parse_args()
    root = Path(args.root)
    package = root / "qualification/hcsn_currentstate_n128_thirdcycle_readiness"
    request = json.loads((package / "REQUEST.json").read_text())
    design = json.loads((package / "DESIGN.json").read_text())
    source = json.loads((package / "SOURCE.json").read_text())
    if request["identity"] != IDENTITY or request["unique_execution_key"] != KEY:
        raise ValueError("request identity differs")
    if request["base_source_commit"] != PARENT:
        raise ValueError("parent source differs")
    if source["identity"] != IDENTITY or source["unique_execution_key"] != KEY:
        raise ValueError("source identity differs")
    if source["parent_head"] != PARENT:
        raise ValueError("source parent differs")
    actual = {name: digest(root / name) for name in source["source_sha256"]}
    if actual != source["source_sha256"]:
        raise ValueError("source inventory differs")

    capsule_path = (
        Path(args.capsule)
        if args.capsule
        else root
        / "qualification/hcsn_currentstate_n128_secondcycle_cold/reference/CAPSULE-7.bin"
    )
    lane, nodes, logical_time, state_count, roster = decode_capsule(capsule_path.read_bytes())
    if (lane, nodes, logical_time, state_count, len(roster)) != (0, 127, F(9, 25), 1320, 22):
        raise ValueError("#6285 terminal roster differs")
    release = [
        {
            key: row[key]
            for key in ("source", "generation", "target", "origin", "dimension")
        }
        for row in roster
        if row["start"] == [2, 5]
    ]
    if release != design["simultaneous_release_at_point4"]:
        raise ValueError("simultaneous .4 release differs")

    candidate_text = (root / "qualification/hcsn_currentstate_n128_secondcycle_warm/candidate_warm.py").read_text()
    engineering_text = (root / "qualification/hcsn_currentstate_n128_engineering/candidate.py").read_text()
    core_text = (root / "qualification/hcsn_currentstate/packets.py").read_text()
    if "if len(releasing) != 1 or releasing[0].target not in (1, 2):" not in candidate_text:
        raise ValueError("#6285 single-release guard differs")
    if "for origin in (1, 2):" not in candidate_text:
        raise ValueError("#6285 two-generation loop differs")
    if "if len(state) != 10 * self.interior_nodes + 50:" not in engineering_text:
        raise ValueError("#6285 state serializer guard differs")
    if 'raise ValueError("third excursion outside stage")' not in core_text:
        raise ValueError("finite candidate third-excursion refusal differs")

    required = design["required_state_layout"]
    if required != {
        "active": 5 * 3 * 127,
        "upper": 5 * 4,
        "mass_M": 5 * 3,
        "hit_H": 5 * 3,
        "occupation_A": 5 * 4,
        "total": 1975,
    }:
        raise ValueError("third-cycle state denominator")
    remaining = [row["dimension"] for row in roster if F(*row["start"]) >= F(401, 1000)]
    new_dimensions = design["prospective_block_dimensions"]
    conceptual = required["total"] + sum(
        dimension * dimension + 6 * dimension
        for dimension in remaining + new_dimensions
    )
    if conceptual != design["prospective_comparison_coordinates"]:
        raise ValueError("prospective coordinate denominator")
    augmented = [dimension + 1 for dimension in new_dimensions]
    if augmented != design["prospective_augmented_dimensions"]:
        raise ValueError("augmented dimension roster")
    largest = max(dimension * dimension * 8 for dimension in augmented)
    two_integrated = 2 * sum(dimension * dimension * 8 for dimension in augmented)
    if largest != design["largest_single_dense_matrix_payload_bytes"] or two_integrated != design["two_integrated_dense_matrix_payload_bytes"]:
        raise ValueError("static dense payload arithmetic")

    result = {
        "identity": IDENTITY,
        "unique_execution_key": KEY,
        "source_parent": PARENT,
        "status": "PASS_STATIC_THIRDCYCLE_READINESS_HOLD_ONLY",
        "parent_capsule_time": [logical_time.numerator, logical_time.denominator],
        "parent_packets": len(roster),
        "simultaneous_releases_at_point4": len(release),
        "existing_state_scalars": state_count,
        "required_state_scalars": required["total"],
        "prospective_comparison_coordinates": conceptual,
        "largest_single_dense_matrix_payload_bytes": largest,
        "dynamic_segments": 0,
        "matrix_exponentials": 0,
        "torch_operations": 0,
        "optimizer_updates": 0,
        "qualification": False,
        "all_closed": False,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
