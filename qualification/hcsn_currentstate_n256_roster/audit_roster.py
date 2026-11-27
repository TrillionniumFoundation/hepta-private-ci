"""Independent stdlib audit for the symbolic N256 roster; imports no compiler."""

import argparse
import base64
import hashlib
import io
import json
import math
import struct
import zipfile
from dataclasses import dataclass, replace
from fractions import Fraction as F
from pathlib import Path

EXPECTED = {
    "metadata": "88e84dd3aea396d34c7e2dd08d31f2e30bf694c20516dccde57e6dd1b0c2a3c6",
    "state": "360b4bf446e853209c58cdb3faded74d9114d872cfb9c730b220d14cef670f9c",
    "phase": "790fabee8825dbd4361f157f56d78641430fe50b9134cd2cb7b02b51b93fe548",
    "npz_b64": "926191319021c51421dd15d76c66c3b5c6d2efef0f28af3f76c893065a49dbeb",
    "npz": "c98a3339504c908081dbf77d2235a18de96da06b1ebda7b1c0f9192af1570eb8",
}
WARM = tuple(F(value) for value in ("0", ".001", ".02", ".16", ".2", ".201", ".28", ".36"))
COARSE = (F(0), F(1, 5), F(9, 25))
COLD = (F(201, 1000), F(7, 25), F(9, 25))
CHANNELS = 5
NODES = 255


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def support(value):
    return {
        "fraction": [value.numerator, value.denominator],
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
    import ast
    header = ast.literal_eval(raw[offset : offset + length].decode("latin1"))
    shape = tuple(header["shape"])
    if header["descr"] != "<f8" or header["fortran_order"] is not False:
        raise ValueError("NPY layout")
    data = raw[offset + length :]
    if len(data) != 8 * math.prod(shape):
        raise ValueError("NPY payload length")
    values = tuple(item[0] for item in struct.iter_unpack("<d", data))
    if any(not math.isfinite(value) for value in values):
        raise ValueError("nonfinite NPY input")
    return shape, data, values


def source_identity(bundle, kind, start, end, target, origin, parents):
    return digest(
        canonical(
            {
                "bundle": bundle,
                "kind": kind,
                "start": [start.numerator, start.denominator],
                "end": [end.numerator, end.denominator],
                "target": target,
                "origin": origin,
                "parents": sorted(parents),
            }
        )
    )


@dataclass(frozen=True)
class Packet:
    start: F
    end: F
    dimension: int
    target: int
    origin: int
    source: str


def advance(time, pending, new_time, bundle):
    rows = []
    while time < new_time:
        left = time
        boundaries = [new_time, left + F(1, 5)]
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
            if origin == 2 and left < F(1, 5):
                continue
            parents = tuple(packet for packet in releasing if packet.target == origin)
            dimension = NODES + sum(packet.dimension for packet in parents)
            retained.append(
                Packet(
                    left + F(1, 5),
                    right + F(1, 5),
                    dimension,
                    target,
                    origin,
                    source_identity(
                        bundle,
                        "lower-flux",
                        left,
                        right,
                        target,
                        origin,
                        [packet.source for packet in parents],
                    ),
                )
            )
        pending = tuple(retained)
        rows.append(
            {
                "kind": "transition",
                "left": support(left),
                "right": support(right),
                "releasing": len(releasing),
                "pending_after": len(pending),
            }
        )
        time = right
    return time, pending, rows


def packet_record(packet):
    row = {
        "generation": packet.target,
        "source": packet.source,
        "target": packet.target,
        "origin": packet.origin,
        "start": support(packet.start),
        "end": support(packet.end),
        "dimension": packet.dimension,
        "coordinate_count": packet.dimension**2 + 6 * packet.dimension,
    }
    row["tuple_identity"] = digest(canonical(row))
    return row


def make_capsule(lane, lane_order, time, pending):
    packets = [packet_record(packet) for packet in pending]
    count = 10 * NODES + 50 + sum(packet["coordinate_count"] for packet in packets)
    capsule = {
        "lane": lane,
        "lane_order": lane_order,
        "time": support(time),
        "channels": CHANNELS,
        "packets": len(packets),
        "coordinate_count": count,
    }
    capsule["capsule_identity"] = digest(canonical(capsule))
    return capsule, packets


def append_spans(capsule_order, capsule, packets, spans):
    order = 0
    for kind, shape in (
        ("active", (CHANNELS, 2, NODES)),
        ("upper", (CHANNELS, 3)),
        ("M", (CHANNELS, 2)),
        ("H", (CHANNELS, 2)),
        ("A", (CHANNELS, 3)),
    ):
        row = {
            "capsule_order": capsule_order,
            "capsule_identity": capsule["capsule_identity"],
            "span_order": order,
            "kind": kind,
            "shape": list(shape),
            "count": math.prod(shape),
        }
        row["span_identity"] = digest(canonical(row))
        spans.append(row)
        order += 1
    for packet_order, packet in enumerate(packets):
        dimension = packet["dimension"]
        for kind, shape in (
            ("alpha", (CHANNELS, dimension)),
            ("generator", (dimension, dimension)),
            ("output", (dimension,)),
        ):
            row = {
                "capsule_order": capsule_order,
                "capsule_identity": capsule["capsule_identity"],
                "span_order": order,
                "kind": kind,
                "packet_order": packet_order,
                "packet_identity": packet["tuple_identity"],
                "shape": list(shape),
                "count": math.prod(shape),
            }
            row["span_identity"] = digest(canonical(row))
            spans.append(row)
            order += 1


def load_inputs(metadata_path, state_path, phase_path, npz_b64_path):
    paths = {
        "metadata": Path(metadata_path),
        "state": Path(state_path),
        "phase": Path(phase_path),
        "npz_b64": Path(npz_b64_path),
    }
    hashes = {name: digest(path.read_bytes()) for name, path in paths.items()}
    decoded = base64.b64decode(paths["npz_b64"].read_text().strip(), validate=True)
    hashes["npz"] = digest(decoded)
    if hashes != EXPECTED:
        raise ValueError("independent input hash mismatch")
    metadata = json.loads(paths["metadata"].read_text())
    state = json.loads(paths["state"].read_text())
    phase = json.loads(paths["phase"].read_text())
    if (
        metadata["identity"] != phase["identity"]
        or state["identity"] != phase["identity"]
        or metadata["historical_N256_export_present"] is not False
        or metadata["dynamic_execution_allowed"] is not False
        or state["intervals"] != 256
        or phase["packet_count"] != 8
    ):
        raise ValueError("independent N256 metadata mismatch")
    arrays = {}
    with zipfile.ZipFile(io.BytesIO(decoded)) as archive:
        if set(archive.namelist()) != {"active.npy", "content.npy", "nodes.npy"}:
            raise ValueError("independent NPZ members")
        for name in sorted(archive.namelist()):
            raw = archive.read(name)
            shape, data, values = read_npy(raw)
            arrays[name] = {
                "shape": list(shape),
                "npy_sha256": digest(raw),
                "payload_sha256": digest(data),
                "first_fp64_le": struct.pack("<d", values[0]).hex(),
                "last_fp64_le": struct.pack("<d", values[-1]).hex(),
                "values": values,
            }
    if [float(v).hex() for v in arrays["nodes.npy"]["values"]] != state["nodes_fp64_hex"]:
        raise ValueError("independent node readback")
    if [float(v).hex() for v in arrays["active.npy"]["values"]] != state["active_probability_fp64_hex"]:
        raise ValueError("independent active readback")
    if [float(v).hex() for v in arrays["content.npy"]["values"]] != state["signed_content_fp64_hex_row_major"]:
        raise ValueError("independent content readback")
    for value in arrays.values():
        value.pop("values")
    return hashes, phase, arrays


def reconstruct(hashes, phase):
    bundle = digest(canonical(hashes))
    initial = []
    for item in phase["packets"]:
        start, end = F(item["start"]), F(item["end"])
        initial.append(
            Packet(
                start,
                end,
                1,
                1,
                0,
                source_identity(bundle, item["identity"], start, end, 1, 0, ()),
            )
        )
    capsules, packets, spans, events = [], [], [], []
    time, pending = F(0), tuple(initial)
    saved = None
    for lane_order, query in enumerate(WARM):
        time, pending, emitted = advance(time, pending, query, bundle)
        events.extend(dict(row, lane="warm") for row in emitted)
        capsule, rows = make_capsule("warm", lane_order, time, pending)
        capsules.append(capsule)
        packets.extend(
            dict(row, capsule_order=len(capsules) - 1, packet_order=index)
            for index, row in enumerate(rows)
        )
        append_spans(len(capsules) - 1, capsule, rows, spans)
        if query == COLD[0]:
            saved = (time, pending)
    time, pending = F(0), tuple(initial)
    for lane_order, query in enumerate(COARSE):
        time, pending, emitted = advance(time, pending, query, bundle)
        events.extend(dict(row, lane="coarse") for row in emitted)
        capsule, rows = make_capsule("coarse", lane_order, time, pending)
        capsules.append(capsule)
        packets.extend(
            dict(row, capsule_order=len(capsules) - 1, packet_order=index)
            for index, row in enumerate(rows)
        )
        append_spans(len(capsules) - 1, capsule, rows, spans)
    if saved is None:
        raise ValueError("independent cold source")
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
        time, pending, emitted = advance(time, pending, query, bundle)
        events.extend(dict(row, lane="cold") for row in emitted)
        capsule, rows = make_capsule("cold", lane_order, time, pending)
        capsules.append(capsule)
        packets.extend(
            dict(row, capsule_order=len(capsules) - 1, packet_order=index)
            for index, row in enumerate(rows)
        )
        append_spans(len(capsules) - 1, capsule, rows, spans)
    return bundle, capsules, packets, spans, events


def audit(metadata, state, phase, npz_b64, roster, output):
    hashes, phase_data, arrays = load_inputs(metadata, state, phase, npz_b64)
    bundle, capsules, packets, spans, events = reconstruct(hashes, phase_data)
    roster = Path(roster)
    actual_capsules = json.loads((roster / "CAPSULES.json").read_text())
    actual_packets = [json.loads(line) for line in (roster / "PACKET_ROSTER.jsonl").read_text().splitlines()]
    actual_spans = [json.loads(line) for line in (roster / "COORDINATE_SPANS.jsonl").read_text().splitlines()]
    actual_events = [json.loads(line) for line in (roster / "EVENTS.jsonl").read_text().splitlines()]
    summary = json.loads((roster / "SUMMARY.json").read_text())
    readback = json.loads((roster / "INPUT_READBACK.json").read_text())
    if (actual_capsules, actual_packets, actual_spans, actual_events) != (
        capsules,
        packets,
        spans,
        events,
    ):
        raise ValueError("independent roster reconstruction mismatch")
    coordinate_hash = hashlib.sha256()
    coordinates = 0
    for span in spans:
        for index in range(span["count"]):
            coordinate_hash.update(f"{span['span_identity']}:{index}\n".encode())
        coordinates += span["count"]
    if (
        readback != {"sha256": hashes, "arrays": arrays}
        or summary["input_bundle_sha256"] != bundle
        or summary["coordinate_identity_sha256"] != coordinate_hash.hexdigest()
        or summary["fp64_coordinate_denominator"] != coordinates
        or coordinates != 18_225_028
        or summary["largest_capsule_coordinates"] != 3_444_164
        or summary["historical_N256_export_present"] is not False
        or summary["new_export_only"] is not True
        or any(summary[name] != 0 for name in ("dynamic_runs", "matrix_exponentials", "oracle_calls", "torch_calls", "optimizer_steps"))
        or summary["execution_key"] is not None
        or summary["largegrid_qualification"] is not False
    ):
        raise ValueError("independent summary mismatch")
    manifest = json.loads((roster / "RAW_MANIFEST.json").read_text())["files"]
    for name, record in manifest.items():
        raw = (roster / name).read_bytes()
        if record != {"bytes": len(raw), "sha256": digest(raw)}:
            raise ValueError("raw manifest mismatch")
    result = {
        "schema": "hcsn-authentic-n256-roster-independent-audit-v1",
        "status": "PASS",
        "input_sha256": hashes,
        "input_bundle_sha256": bundle,
        "capsules": len(capsules),
        "packet_tuples": len(packets),
        "coordinate_spans": len(spans),
        "fp64_coordinate_denominator": coordinates,
        "coordinate_identity_sha256": coordinate_hash.hexdigest(),
        "transition_segments": sum(row["kind"] == "transition" for row in events),
        "candidate_numeric_calls": 0,
        "oracle_numeric_calls": 0,
        "matrix_exponentials": 0,
        "torch_calls": 0,
        "optimizer_steps": 0,
        "largegrid_qualification": False,
        "admission": "HOLD_NO_NUMERICAL_EXECUTION",
        "all_closed": False,
    }
    Path(output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--npz-b64", required=True)
    parser.add_argument("--roster", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.metadata, args.state, args.phase, args.npz_b64, args.roster, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
