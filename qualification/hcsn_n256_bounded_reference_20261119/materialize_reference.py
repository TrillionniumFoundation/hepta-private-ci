"""Serialize the already-proved unique binary64 values; no numerical actions."""

from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import struct

from readback import capsule, check


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def main():
    frozen = json.loads((HERE / "SOURCE_FREEZE.json").read_text())
    for name, expected in frozen["files"].items():
        data = (REPO / name).read_bytes()
        check(len(data) == expected["bytes"] and hashlib.sha256(data).hexdigest() == expected["sha256"], "frozen inputs and source")
    original_name = next(name for name in frozen["files"] if name.endswith("/originals/N256_WARM1.bin"))
    identity, packets, _ = capsule((REPO / original_name).read_bytes())
    data_path = HERE / "evidence" / "attempt001" / "REFERENCE_COORDINATES.json"
    data = json.loads(data_path.read_text())
    check(data["correct_rounding_proven_for_all"] and packets == data["packet_metadata"], "proved complete state")
    encoded, count = {}, 0
    for field in data["fields"]:
        if field["kind"] == "exact_binary64_point":
            raw = bytes.fromhex(field["payload_hex"])
            check(hashlib.sha256(raw).hexdigest() == field["sha256"], "static point payload")
        else:
            check(field["kind"] == "exact_rational_enclosures", "enclosure encoding")
            pieces = []
            for lower, upper in field["intervals"]:
                first, last = struct.pack("<d", float(Fraction(lower))), struct.pack("<d", float(Fraction(upper)))
                check(first == last, "unique endpoint rounding")
                pieces.append(first)
            raw = b"".join(pieces)
        check(len(raw) == 8 * math.prod(field["shape"]), "complete tensor")
        encoded[field["name"]] = (field["shape"], raw)
        count += len(raw) // 8
    check(count == 69728 and len(encoded) == 32, "complete original roster")

    def u32(value):
        return struct.pack(">I", value)

    def record(value):
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        return u32(len(raw)) + raw

    def tensor(name):
        shape, raw = encoded[name]
        return u32(len(shape)) + b"".join(struct.pack(">Q", value) for value in shape) + struct.pack(">Q", len(raw)) + raw

    wire = b"HCSNFSP2" + record(identity) + u32(5)
    for name in sorted(name[6:] for name in encoded if name.startswith("state/")):
        wire += u32(len(name)) + name.encode() + tensor("state/" + name)
    wire += u32(len(packets))
    for packet in packets:
        wire += record(packet)
        for name in ("alpha", "generator", "output"):
            wire += tensor("packet/" + packet["identity"] + "/" + name)
    wire += hashlib.sha256(wire).digest()
    reread_identity, reread_packets, reread_fields = capsule(wire)
    check(reread_identity == identity and reread_packets == packets and reread_fields == encoded, "wire roundtrip")
    output = HERE / "evidence" / "rounded_reference"
    output.mkdir(exist_ok=False)
    target = output / "N256_WARM1_REFERENCE.bin"
    with target.open("xb") as stream:
        stream.write(wire)
    receipt = {"kind": "correctly-rounded-finite-matrix-reference-artifact", "coordinates": count,
               "bytes": len(wire), "sha256": hashlib.sha256(wire).hexdigest(),
               "coordinate_enclosures_sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
               "numerical_actions": 0, "old_candidate_oracle_calls": 0,
               "scope": "Serialization of previously proven endpoint-rounding intervals; does not replace either original solver capsule or original bitwise gate.", "all_closed": False}
    (output / "RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
