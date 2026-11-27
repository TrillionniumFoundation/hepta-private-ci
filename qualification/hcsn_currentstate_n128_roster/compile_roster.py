"""Compile the canonical N128 packet-coordinate roster without dynamics."""

import argparse
import ast
import hashlib
import itertools
import json
import math
import struct
import zipfile
from dataclasses import dataclass, replace
from fractions import Fraction as F
from pathlib import Path

EXPECTED = {
    "law": "7a4b7485bf224b5e343f2c17fccf4ea7ca2dfdd06121810d16c503134f9e92fb",
    "json": "8f4f77b8ba2bc1d1e3012f64ce9614711d178503601878e091b3db8e7eadaf09",
    "npz": "fda047c1a8fce3cc042246b5249859cd0a0ba449647460ba9e0a39592386ff7d",
}
WARM = tuple(
    F(value) for value in ("0", ".001", ".02", ".16", ".2", ".201", ".28", ".36")
)
COARSE = (F(0), F(1, 5), F(9, 25))
COLD = (F(201, 1000), F(7, 25), F(9, 25))
EXPECTED_COORDINATES = 4_623_492
CHANNELS = 5


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def fraction_json(value):
    return [value.numerator, value.denominator]


def support(value):
    return {
        "fraction": fraction_json(value),
        "fp64_le": struct.pack("<d", float(value)).hex(),
    }


def read_npy(raw):
    if raw[:6] != b"\x93NUMPY":
        raise ValueError("NPY magic")
    major = raw[6]
    if major == 1:
        length, offset = struct.unpack("<H", raw[8:10])[0], 10
    elif major in (2, 3):
        length, offset = struct.unpack("<I", raw[8:12])[0], 12
    else:
        raise ValueError("NPY version")
    header = ast.literal_eval(raw[offset : offset + length].decode("latin1"))
    shape = tuple(header["shape"])
    if header["descr"] != "<f8" or header["fortran_order"] is not False:
        raise ValueError("NPY layout")
    data = raw[offset + length :]
    if len(data) != 8 * math.prod(shape):
        raise ValueError("NPY payload length")
    values = tuple(value[0] for value in struct.iter_unpack("<d", data))
    if any(not math.isfinite(value) for value in values):
        raise ValueError("nonfinite NPY input")
    return shape, data, values


@dataclass(frozen=True)
class Packet:
    start: F
    end: F
    dimension: int
    target: int
    origin: int
    source: str


def source_identity(bundle, kind, start, end, target, origin, parents):
    return digest(
        canonical(
            {
                "bundle": bundle,
                "kind": kind,
                "start": fraction_json(start),
                "end": fraction_json(end),
                "target": target,
                "origin": origin,
                "parents": sorted(parents),
            }
        )
    )


def advance(time, pending, new_time, delay, nodes, bundle):
    events = []
    while time < new_time:
        left = time
        boundaries = [new_time, left + delay]
        for packet in pending:
            boundaries.extend((packet.start, packet.end))
        right = min(value for value in boundaries if value > left)
        releasing = tuple(packet for packet in pending if packet.start == left)
        retained = []
        for packet in pending:
            if packet.start == left:
                if packet.end > right:
                    retained.append(replace(packet, start=right))
            else:
                retained.append(packet)
        for origin, target in ((1, 2), (2, 3)):
            if origin == 2 and left < delay:
                continue
            parents = tuple(packet for packet in releasing if packet.target == origin)
            dimension = nodes + sum(packet.dimension for packet in parents)
            identity = source_identity(
                bundle,
                "lower-flux",
                left,
                right,
                target,
                origin,
                [packet.source for packet in parents],
            )
            retained.append(
                Packet(left + delay, right + delay, dimension, target, origin, identity)
            )
        pending = tuple(retained)
        events.append(
            {
                "kind": "transition",
                "left": support(left),
                "right": support(right),
                "releasing": len(releasing),
                "pending_after": len(pending),
            }
        )
        time = right
    return time, pending, events


def coordinate_count(nodes, pending):
    return (
        10 * nodes
        + 50
        + sum(packet.dimension**2 + 6 * packet.dimension for packet in pending)
    )


def packet_record(packet):
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
    value["tuple_identity"] = digest(canonical(value))
    return value


def state_spans(nodes):
    return (
        ("active", (CHANNELS, 2, nodes)),
        ("upper", (CHANNELS, 3)),
        ("M", (CHANNELS, 2)),
        ("H", (CHANNELS, 2)),
        ("A", (CHANNELS, 3)),
    )


def make_capsule(lane, lane_order, time, pending, nodes):
    packets = [packet_record(packet) for packet in pending]
    capsule = {
        "lane": lane,
        "lane_order": lane_order,
        "time": support(time),
        "channels": CHANNELS,
        "packets": len(packets),
        "coordinate_count": coordinate_count(nodes, pending),
    }
    capsule["capsule_identity"] = digest(canonical(capsule))
    return capsule, packets


def append_spans(capsule_order, capsule, packets, nodes, spans):
    order = 0
    for kind, shape in state_spans(nodes):
        record = {
            "capsule_order": capsule_order,
            "capsule_identity": capsule["capsule_identity"],
            "span_order": order,
            "kind": kind,
            "shape": list(shape),
            "count": math.prod(shape),
        }
        record["span_identity"] = digest(canonical(record))
        spans.append(record)
        order += 1
    for packet_order, packet in enumerate(packets):
        dimension = packet["dimension"]
        for kind, shape in (
            ("alpha", (CHANNELS, dimension)),
            ("generator", (dimension, dimension)),
            ("output", (dimension,)),
        ):
            record = {
                "capsule_order": capsule_order,
                "capsule_identity": capsule["capsule_identity"],
                "span_order": order,
                "kind": kind,
                "packet_order": packet_order,
                "packet_identity": packet["tuple_identity"],
                "shape": list(shape),
                "count": math.prod(shape),
            }
            record["span_identity"] = digest(canonical(record))
            spans.append(record)
            order += 1


def compile_roster(law_path, json_path, npz_path, output):
    paths = {"law": Path(law_path), "json": Path(json_path), "npz": Path(npz_path)}
    hashes = {name: digest(path.read_bytes()) for name, path in paths.items()}
    if hashes != EXPECTED:
        raise ValueError("hash-bound input mismatch")
    law = json.loads(paths["law"].read_text())
    metadata = json.loads(paths["json"].read_text())
    if metadata["npz_sha256"] != hashes["npz"] or metadata["intervals"] != 128:
        raise ValueError("N128 metadata mismatch")
    if law["grid"]["phase_cells"] != 8 or law["grid"]["refractory"] != 0.2:
        raise ValueError("selected-law geometry mismatch")
    delay = F(str(law["grid"]["refractory"]))
    if delay != F(1, 5) or metadata["reset_distance"] != 0.3131468965881033:
        raise ValueError("delay/reset mismatch")
    with zipfile.ZipFile(paths["npz"]) as archive:
        if set(archive.namelist()) != {"active.npy", "content.npy", "nodes.npy"}:
            raise ValueError("NPZ members")
        arrays = {}
        for name in sorted(archive.namelist()):
            raw = archive.read(name)
            shape, data, values = read_npy(raw)
            arrays[name] = {
                "shape": list(shape),
                "npy_sha256": digest(raw),
                "payload_sha256": digest(data),
                "first_fp64_le": struct.pack("<d", values[0]).hex(),
                "last_fp64_le": struct.pack("<d", values[-1]).hex(),
            }
    if (
        arrays["active.npy"]["shape"] != [129]
        or arrays["content.npy"]["shape"] != [129, 4]
        or arrays["nodes.npy"]["shape"] != [129]
    ):
        raise ValueError("N128 array shape")
    nodes = arrays["nodes.npy"]["shape"][0] - 2
    if nodes != 127:
        raise ValueError("N128 interior-node count")
    phase = metadata["phase"]
    if len(phase) != 8:
        raise ValueError("phase count")
    bundle = digest(canonical(hashes))
    initial = []
    for item in phase:
        start, end = F(item["start"]), F(item["end"])
        expected_source = source_identity(
            bundle, item["identity"], start, end, 1, 0, ()
        )
        initial.append(Packet(start, end, 1, 1, 0, expected_source))
    if (
        initial[0].start != 0
        or initial[-1].end != delay
        or any(left.end != right.start for left, right in itertools.pairwise(initial))
    ):
        raise ValueError("noncontiguous authentic phase supports")
    capsules = []
    packet_lines = []
    spans = []
    events = []
    time, pending = F(0), tuple(initial)
    saved = None
    for lane_order, query in enumerate(WARM):
        time, pending, emitted = advance(time, pending, query, delay, nodes, bundle)
        events.extend(dict(event, lane="warm") for event in emitted)
        capsule, packets = make_capsule("warm", lane_order, time, pending, nodes)
        capsules.append(capsule)
        packet_lines.extend(
            dict(record, capsule_order=len(capsules) - 1, packet_order=order)
            for order, record in enumerate(packets)
        )
        append_spans(len(capsules) - 1, capsule, packets, nodes, spans)
        if query == COLD[0]:
            saved = (time, pending)
    time, pending = F(0), tuple(initial)
    for lane_order, query in enumerate(COARSE):
        time, pending, emitted = advance(time, pending, query, delay, nodes, bundle)
        events.extend(dict(event, lane="coarse") for event in emitted)
        capsule, packets = make_capsule("coarse", lane_order, time, pending, nodes)
        capsules.append(capsule)
        packet_lines.extend(
            dict(record, capsule_order=len(capsules) - 1, packet_order=order)
            for order, record in enumerate(packets)
        )
        append_spans(len(capsules) - 1, capsule, packets, nodes, spans)
    if saved is None:
        raise ValueError("warm resume capsule missing")
    time, pending = saved
    events.append(
        {
            "kind": "cold_restore",
            "lane": "cold",
            "time": support(time),
            "pending_after": len(pending),
        }
    )
    for lane_order, query in enumerate(COLD):
        time, pending, emitted = advance(time, pending, query, delay, nodes, bundle)
        events.extend(dict(event, lane="cold") for event in emitted)
        capsule, packets = make_capsule("cold", lane_order, time, pending, nodes)
        capsules.append(capsule)
        packet_lines.extend(
            dict(record, capsule_order=len(capsules) - 1, packet_order=order)
            for order, record in enumerate(packets)
        )
        append_spans(len(capsules) - 1, capsule, packets, nodes, spans)
    coordinate_hash = hashlib.sha256()
    coordinates = 0
    for span in spans:
        for index in range(span["count"]):
            coordinate_hash.update(f"{span['span_identity']}:{index}\n".encode())
        coordinates += span["count"]
    transitions = sum(event["kind"] == "transition" for event in events)
    status = (
        "PASS"
        if coordinates == EXPECTED_COORDINATES
        and len(capsules) == 14
        and transitions == 45
        else "RED"
    )
    summary = {
        "schema": "hcsn-authentic-n128-roster-v1",
        "status": status,
        "admission": "HOLD_NO_NUMERICAL_EXECUTION",
        "all_closed": False,
        "input_sha256": hashes,
        "input_bundle_sha256": bundle,
        "arrays": arrays,
        "interior_nodes": nodes,
        "channels": CHANNELS,
        "capsules": len(capsules),
        "packet_tuples": len(packet_lines),
        "coordinate_spans": len(spans),
        "fp64_coordinate_denominator": coordinates,
        "coordinate_identity_sha256": coordinate_hash.hexdigest(),
        "events_including_cold_restore": len(events),
        "transition_segments": transitions,
        "largest_capsule_coordinates": max(
            capsule["coordinate_count"] for capsule in capsules
        ),
        "largest_pending_packets": max(capsule["packets"] for capsule in capsules),
        "dynamic_runs": 0,
        "matrix_exponentials": 0,
        "oracle_calls": 0,
        "torch_calls": 0,
        "optimizer_steps": 0,
        "execution_key": None,
        "largegrid_qualification": False,
    }
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "INPUT_READBACK.json").write_text(
        json.dumps({"sha256": hashes, "arrays": arrays}, indent=2, allow_nan=False)
        + "\n"
    )
    (output / "CAPSULES.json").write_text(
        json.dumps(capsules, indent=2, allow_nan=False) + "\n"
    )
    (output / "PACKET_ROSTER.jsonl").write_bytes(
        b"".join(canonical(value) + b"\n" for value in packet_lines)
    )
    (output / "COORDINATE_SPANS.jsonl").write_bytes(
        b"".join(canonical(value) + b"\n" for value in spans)
    )
    (output / "EVENTS.jsonl").write_bytes(
        b"".join(canonical(value) + b"\n" for value in events)
    )
    (output / "SUMMARY.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n"
    )
    files = {
        path.name: {"bytes": path.stat().st_size, "sha256": digest(path.read_bytes())}
        for path in sorted(output.iterdir())
    }
    (output / "RAW_MANIFEST.json").write_text(
        json.dumps({"files": files}, indent=2, allow_nan=False) + "\n"
    )
    if status != "PASS":
        raise RuntimeError("RED: authentic roster differs from frozen denominator")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--law", required=True)
    parser.add_argument("--json", required=True)
    parser.add_argument("--npz", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            compile_roster(args.law, args.json, args.npz, args.output), sort_keys=True
        )
    )


if __name__ == "__main__":
    main()
