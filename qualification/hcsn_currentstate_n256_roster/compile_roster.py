"""Compile a source-bound N256 packet-coordinate roster without dynamics."""

import argparse
import base64
import hashlib
import io
import json
import math
import struct
import zipfile
from fractions import Fraction as F
from pathlib import Path

from qualification.hcsn_currentstate_n128_roster.compile_roster import (
    CHANNELS,
    COARSE,
    COLD,
    WARM,
    Packet,
    advance,
    append_spans,
    canonical,
    coordinate_count,
    digest,
    make_capsule,
    read_npy,
    source_identity,
)

EXPECTED = {
    "metadata": "88e84dd3aea396d34c7e2dd08d31f2e30bf694c20516dccde57e6dd1b0c2a3c6",
    "state": "360b4bf446e853209c58cdb3faded74d9114d872cfb9c730b220d14cef670f9c",
    "phase": "790fabee8825dbd4361f157f56d78641430fe50b9134cd2cb7b02b51b93fe548",
    "npz_b64": "926191319021c51421dd15d76c66c3b5c6d2efef0f28af3f76c893065a49dbeb",
    "npz": "c98a3339504c908081dbf77d2235a18de96da06b1ebda7b1c0f9192af1570eb8",
}
IDENTITY = "hcsn-n256-new-export-20261112-c06d-attempt001"
EXPECTED_COORDINATES = 18_225_028
EXPECTED_LARGEST = 3_444_164


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
        raise ValueError("hash-bound N256 export differs")
    metadata = json.loads(paths["metadata"].read_text())
    state = json.loads(paths["state"].read_text())
    phase = json.loads(paths["phase"].read_text())
    if (
        metadata["schema"] != "hcsn-n256-new-export-metadata-v1"
        or metadata["identity"] != IDENTITY
        or metadata["historical_N256_export_present"] is not False
        or metadata["new_export"] is not True
        or metadata["dynamic_execution_allowed"] is not False
        or metadata["npz"]["sha256"] != hashes["npz"]
        or metadata["state_json_sha256"] != hashes["state"]
        or metadata["phase_json_sha256"] != hashes["phase"]
        or metadata["reset_distance"] != 0.3131468965881033
    ):
        raise ValueError("N256 metadata contract differs")
    if (
        state["schema"] != "hcsn-n256-new-export-state-v1"
        or state["identity"] != IDENTITY
        or state["intervals"] != 256
        or state["nodes_shape"] != [257]
        or state["active_shape"] != [257]
        or state["content_shape"] != [257, 4]
        or state["dtype"] != "<f8"
        or phase["schema"] != "hcsn-n256-new-export-phase-v1"
        or phase["identity"] != IDENTITY
        or phase["packet_count"] != 8
        or len(phase["packets"]) != 8
    ):
        raise ValueError("N256 state/phase contract differs")
    arrays = {}
    with zipfile.ZipFile(io.BytesIO(decoded)) as archive:
        if set(archive.namelist()) != {"active.npy", "content.npy", "nodes.npy"}:
            raise ValueError("N256 NPZ members")
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
    if (
        arrays["active.npy"]["shape"] != [257]
        or arrays["content.npy"]["shape"] != [257, 4]
        or arrays["nodes.npy"]["shape"] != [257]
    ):
        raise ValueError("N256 decoded shapes")
    if [float(value).hex() for value in arrays["nodes.npy"]["values"]] != state["nodes_fp64_hex"]:
        raise ValueError("N256 node readback")
    if [float(value).hex() for value in arrays["active.npy"]["values"]] != state["active_probability_fp64_hex"]:
        raise ValueError("N256 active readback")
    if [float(value).hex() for value in arrays["content.npy"]["values"]] != state["signed_content_fp64_hex_row_major"]:
        raise ValueError("N256 content readback")
    for value in arrays.values():
        value.pop("values")
    packets = phase["packets"]
    if (
        packets[0]["start"] != "0"
        or packets[-1]["end"] != "1/5"
        or any(F(left["end"]) != F(right["start"]) for left, right in zip(packets, packets[1:]))
    ):
        raise ValueError("N256 phase support is not contiguous")
    return hashes, metadata, phase, arrays


def compile_roster(metadata_path, state_path, phase_path, npz_b64_path, output):
    hashes, metadata, phase, arrays = load_inputs(
        metadata_path, state_path, phase_path, npz_b64_path
    )
    nodes = arrays["nodes.npy"]["shape"][0] - 2
    if nodes != 255:
        raise ValueError("N256 interior-node count")
    delay = F(1, 5)
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
            "time": {"fraction": [time.numerator, time.denominator], "fp64_le": struct.pack("<d", float(time)).hex()},
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
    largest = max(capsule["coordinate_count"] for capsule in capsules)
    status = (
        "PASS"
        if coordinates == EXPECTED_COORDINATES
        and largest == EXPECTED_LARGEST
        and len(capsules) == 14
        and len(packet_lines) == 185
        and len(spans) == 625
        and transitions == 45
        else "RED"
    )
    summary = {
        "schema": "hcsn-authentic-n256-roster-v1",
        "status": status,
        "admission": "HOLD_NO_NUMERICAL_EXECUTION",
        "all_closed": False,
        "historical_N256_export_present": False,
        "new_export_only": True,
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
        "largest_capsule_coordinates": largest,
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
        json.dumps({"sha256": hashes, "arrays": arrays}, indent=2, allow_nan=False) + "\n"
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
        raise RuntimeError("RED: N256 symbolic roster differs from frozen denominator")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--npz-b64", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            compile_roster(
                args.metadata, args.state, args.phase, args.npz_b64, args.output
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
