"""Independent stdlib audit of the authentic N128 roster artifacts."""

import argparse
import ast
import hashlib
import json
import math
import struct
import zipfile
from dataclasses import dataclass, replace
from fractions import Fraction as F
from pathlib import Path

HASHES = {
    "law": "7a4b7485bf224b5e343f2c17fccf4ea7ca2dfdd06121810d16c503134f9e92fb",
    "json": "8f4f77b8ba2bc1d1e3012f64ce9614711d178503601878e091b3db8e7eadaf09",
    "npz": "fda047c1a8fce3cc042246b5249859cd0a0ba449647460ba9e0a39592386ff7d",
}
WARM = tuple(
    F(value) for value in ("0", ".001", ".02", ".16", ".2", ".201", ".28", ".36")
)
COARSE = (F(0), F(1, 5), F(9, 25))
COLD = (F(201, 1000), F(7, 25), F(9, 25))


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def pair(value):
    return [value.numerator, value.denominator]


def support(value):
    return {"fraction": pair(value), "fp64_le": struct.pack("<d", float(value)).hex()}


def npy(raw):
    if raw[:6] != b"\x93NUMPY":
        raise ValueError("NPY magic")
    if raw[6] == 1:
        length, offset = struct.unpack("<H", raw[8:10])[0], 10
    elif raw[6] in (2, 3):
        length, offset = struct.unpack("<I", raw[8:12])[0], 12
    else:
        raise ValueError("NPY version")
    header = ast.literal_eval(raw[offset : offset + length].decode("latin1"))
    data = raw[offset + length :]
    if (
        header["descr"] != "<f8"
        or header["fortran_order"]
        or len(data) != 8 * math.prod(header["shape"])
    ):
        raise ValueError("NPY layout")
    return list(header["shape"]), sha(raw), sha(data)


@dataclass(frozen=True)
class Packet:
    start: F
    end: F
    dimension: int
    target: int
    origin: int
    source: str


def lineage(bundle, kind, start, end, target, origin, parents):
    return sha(
        canonical(
            {
                "bundle": bundle,
                "kind": kind,
                "start": pair(start),
                "end": pair(end),
                "target": target,
                "origin": origin,
                "parents": sorted(parents),
            }
        )
    )


def advance(time, pending, query, delay, nodes, bundle):
    segments = 0
    while time < query:
        left = time
        boundaries = [query, left + delay]
        for packet in pending:
            boundaries.extend((packet.start, packet.end))
        right = min(value for value in boundaries if value > left)
        releasing = tuple(packet for packet in pending if packet.start == left)
        retained = [
            replace(packet, start=right)
            if packet.start == left and packet.end > right
            else packet
            for packet in pending
            if packet.start != left or packet.end > right
        ]
        for origin, target in ((1, 2), (2, 3)):
            if origin == 2 and left < delay:
                continue
            parents = tuple(packet for packet in releasing if packet.target == origin)
            source = lineage(
                bundle,
                "lower-flux",
                left,
                right,
                target,
                origin,
                [packet.source for packet in parents],
            )
            retained.append(
                Packet(
                    left + delay,
                    right + delay,
                    nodes + sum(packet.dimension for packet in parents),
                    target,
                    origin,
                    source,
                )
            )
        pending = tuple(retained)
        time = right
        segments += 1
    return time, pending, segments


def tuple_record(packet):
    value = {
        "generation": packet.target,
        "source": packet.source,
        "target": packet.target,
        "origin": packet.origin,
        "start": support(packet.start),
        "end": support(packet.end),
        "dimension": packet.dimension,
        "coordinate_count": packet.dimension**2 + 6 * packet.dimension,
    }
    value["tuple_identity"] = sha(canonical(value))
    return value


def expected_capsules(metadata, bundle, nodes):
    delay = F(1, 5)
    initial = tuple(
        Packet(
            F(item["start"]),
            F(item["end"]),
            1,
            1,
            0,
            lineage(
                bundle, item["identity"], F(item["start"]), F(item["end"]), 1, 0, ()
            ),
        )
        for item in metadata["phase"]
    )
    result = []
    time, pending = F(0), initial
    saved = None
    segments = 0
    for order, query in enumerate(WARM):
        time, pending, count = advance(time, pending, query, delay, nodes, bundle)
        segments += count
        result.append(("warm", order, time, pending))
        if query == COLD[0]:
            saved = time, pending
    time, pending = F(0), initial
    for order, query in enumerate(COARSE):
        time, pending, count = advance(time, pending, query, delay, nodes, bundle)
        segments += count
        result.append(("coarse", order, time, pending))
    time, pending = saved
    for order, query in enumerate(COLD):
        time, pending, count = advance(time, pending, query, delay, nodes, bundle)
        segments += count
        result.append(("cold", order, time, pending))
    return result, segments


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def audit(law_path, json_path, npz_path, evidence, output):
    paths = {"law": Path(law_path), "json": Path(json_path), "npz": Path(npz_path)}
    hashes = {name: sha(path.read_bytes()) for name, path in paths.items()}
    if hashes != HASHES:
        raise ValueError("input hash mismatch")
    law = json.loads(paths["law"].read_text())
    metadata = json.loads(paths["json"].read_text())
    if (
        law["grid"]["phase_cells"] != 8
        or law["grid"]["refractory"] != 0.2
        or metadata["intervals"] != 128
    ):
        raise ValueError("authentic input geometry")
    with zipfile.ZipFile(paths["npz"]) as archive:
        if set(archive.namelist()) != {"active.npy", "content.npy", "nodes.npy"}:
            raise ValueError("authentic NPZ members")
        member_audit = {
            name: npy(archive.read(name)) for name in sorted(archive.namelist())
        }
    if {name: value[0] for name, value in member_audit.items()} != {
        "active.npy": [129],
        "content.npy": [129, 4],
        "nodes.npy": [129],
    }:
        raise ValueError("authentic NPZ shapes")
    nodes = 127
    bundle = sha(canonical(hashes))
    expected, segment_count = expected_capsules(metadata, bundle, nodes)
    evidence = Path(evidence)
    capsules = json.loads((evidence / "CAPSULES.json").read_text())
    packets = lines(evidence / "PACKET_ROSTER.jsonl")
    spans = lines(evidence / "COORDINATE_SPANS.jsonl")
    events = lines(evidence / "EVENTS.jsonl")
    summary = json.loads((evidence / "SUMMARY.json").read_text())
    if summary["status"] != "PASS" or summary["input_sha256"] != hashes:
        raise ValueError("compiler summary admission/input mismatch")
    manifest = json.loads((evidence / "RAW_MANIFEST.json").read_text())
    for name, record in manifest["files"].items():
        raw = (evidence / name).read_bytes()
        if len(raw) != record["bytes"] or sha(raw) != record["sha256"]:
            raise ValueError("raw manifest mismatch")
    cursor = 0
    for capsule_order, (lane, lane_order, time, pending) in enumerate(expected):
        actual = capsules[capsule_order]
        expected_count = (
            10 * nodes
            + 50
            + sum(packet.dimension**2 + 6 * packet.dimension for packet in pending)
        )
        capsule_base = {
            "lane": lane,
            "lane_order": lane_order,
            "time": support(time),
            "channels": 5,
            "packets": len(pending),
            "coordinate_count": expected_count,
        }
        capsule_base["capsule_identity"] = sha(canonical(capsule_base))
        if actual != capsule_base:
            raise ValueError("capsule mismatch")
        for order, packet in enumerate(pending):
            actual_packet = packets[cursor]
            expected_packet = tuple_record(packet) | {
                "capsule_order": capsule_order,
                "packet_order": order,
            }
            if actual_packet != expected_packet:
                raise ValueError("packet tuple mismatch")
            cursor += 1
    if cursor != len(packets):
        raise ValueError("packet denominator mismatch")
    coordinate_hash = hashlib.sha256()
    coordinate_count = 0
    for record in spans:
        base = dict(record)
        identity = base.pop("span_identity")
        if sha(canonical(base)) != identity or base["span_order"] < 0:
            raise ValueError("span identity/order")
        if math.prod(base["shape"]) != base["count"]:
            raise ValueError("span shape/count")
        for index in range(base["count"]):
            coordinate_hash.update(f"{identity}:{index}\n".encode())
        coordinate_count += base["count"]
    transitions = sum(event["kind"] == "transition" for event in events)
    if (
        len(events) != 46
        or sum(event["kind"] == "cold_restore" for event in events) != 1
        or {event["lane"] for event in events} != {"warm", "coarse", "cold"}
    ):
        raise ValueError("event roster mismatch")
    result = {
        "schema": "hcsn-authentic-n128-roster-independent-audit-v1",
        "status": "PASS",
        "input_sha256": hashes,
        "npz_members": member_audit,
        "capsules": len(capsules),
        "packet_tuples": len(packets),
        "coordinate_spans": len(spans),
        "fp64_coordinate_denominator": coordinate_count,
        "coordinate_identity_sha256": coordinate_hash.hexdigest(),
        "transition_segments": transitions,
        "independently_reconstructed_segments": segment_count,
        "cold_restore_events": sum(event["kind"] == "cold_restore" for event in events),
        "dynamic_runs": 0,
        "matrix_exponentials": 0,
        "oracle_calls": 0,
        "torch_calls": 0,
        "optimizer_steps": 0,
        "execution_key": None,
        "admission": "HOLD_NO_NUMERICAL_EXECUTION",
        "all_closed": False,
    }
    expected_summary = (14, 185, 625, 4_623_492, 45, 22, 870_084)
    observed = (
        result["capsules"],
        result["packet_tuples"],
        result["coordinate_spans"],
        coordinate_count,
        transitions,
        summary["largest_pending_packets"],
        summary["largest_capsule_coordinates"],
    )
    if (
        observed != expected_summary
        or coordinate_hash.hexdigest() != summary["coordinate_identity_sha256"]
        or segment_count != 45
    ):
        result["status"] = "RED"
        Path(output).write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
        raise RuntimeError("RED: independent denominator audit mismatch")
    Path(output).write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--law", required=True)
    parser.add_argument("--json", required=True)
    parser.add_argument("--npz", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            audit(args.law, args.json, args.npz, args.evidence, args.output),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
