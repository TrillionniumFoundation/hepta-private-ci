"""Independent stdlib audit of the corrected-lineage N256 t=0 capsule."""

import argparse
import ast
import base64
import hashlib
import io
import json
import math
import struct
import zipfile
from fractions import Fraction
from pathlib import Path


MAGIC = b"HCSNFSP1"
SCHEMA = "hcsn-fullstate-packet-v1"
IDENTITY = "hcsn-n256-corrected-t0-capsule-contract-20261117-c06d-001"
EXECUTION_KEY = "hcsn-n256-corrected-t0-capsule-20261117-c06d-002"
CAPSULE_IDENTITY = "f30003d261658a45e5849339abe3eb683868ac3d513eb40ded1e01992fd1d584"
INPUT_BUNDLE_SHA256 = "17086fb6ba83211e8626c7ac9c22183f6c9c9a7dc615772b5a32d2c14ecb8e95"
ROSTER_IDENTITY = "e289c20d6595cb6d92dd3e2585bc7cb40fb0d5a408725c5edc14a9fb7f328fe2"
EXPECTED_BINDINGS = {
    "candidate_admission_sha256": "d3ec236043f1563a6c05d0843a1b431ec1288da70047a3dc451031c25f67f61b",
    "candidate_request_sha256": "9db32bf0c81051a8ba719a0fd54ece202e312ae84ab5ede43d181e3d86f410fe",
    "candidate_source_sha256": "49616d4fcff9685a6cfcbee00ff45a2fd9ab4eb9c6ce04e62c02f927752d50db",
    "canonical_serializer_sha256": "3107fb296043de8f3e3c78e13aa940aea38aa64c16dfe68d342d2adb0c7aa97a",
    "decoded_npz_sha256": "c98a3339504c908081dbf77d2235a18de96da06b1ebda7b1c0f9192af1570eb8",
    "input_bundle_sha256": INPUT_BUNDLE_SHA256,
    "npz_b64_original_sha256": "926191319021c51421dd15d76c66c3b5c6d2efef0f28af3f76c893065a49dbeb",
    "oracle_adapter_sha256": "311eeeb69ba5002171d3aa765610bc9caea1cb2942309ba6e67543297cb74084",
    "oracle_admission_sha256": "7f3c24118a3504d393d59b31576e8a140c206a154dfaecf4c5ec0aa327feb90c",
    "oracle_request_sha256": "b99b8621b4ea6c4083815d736d07de96ef056251104224044d780c2135f7cdcc",
    "phase_original_sha256": "790fabee8825dbd4361f157f56d78641430fe50b9134cd2cb7b02b51b93fe548",
    "roster_identity": ROSTER_IDENTITY,
    "state_original_sha256": "360b4bf446e853209c58cdb3faded74d9114d872cfb9c730b220d14cef670f9c",
}
EXPECTED_ORIGINALS = {
    "METADATA.json": "88e84dd3aea396d34c7e2dd08d31f2e30bf694c20516dccde57e6dd1b0c2a3c6",
    "N256_STATE.json": "360b4bf446e853209c58cdb3faded74d9114d872cfb9c730b220d14cef670f9c",
    "N256_PHASE.json": "790fabee8825dbd4361f157f56d78641430fe50b9134cd2cb7b02b51b93fe548",
    "N256_STATE.npz.b64": "926191319021c51421dd15d76c66c3b5c6d2efef0f28af3f76c893065a49dbeb",
}
ORIGINALS = Path("qualification/hcsn_n256_new_export/evidence/attempt001")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("ascii")


def _take(view, offset, count):
    end = offset + count
    if count < 0 or end > len(view):
        raise ValueError("truncated capsule")
    return bytes(view[offset:end]), end


def _integer(view, offset, width):
    raw, offset = _take(view, offset, width)
    return int.from_bytes(raw, "big"), offset


def _npy_payload(raw):
    if raw[:6] != b"\x93NUMPY" or raw[6] not in (1, 2, 3):
        raise ValueError("NPY header")
    width = 2 if raw[6] == 1 else 4
    size = int.from_bytes(raw[8 : 8 + width], "little")
    start = 8 + width
    header = ast.literal_eval(raw[start : start + size].decode("latin1"))
    payload = raw[start + size :]
    if header["descr"] != "<f8" or header["fortran_order"] is not False:
        raise ValueError("NPY layout")
    if len(payload) != 8 * math.prod(header["shape"]):
        raise ValueError("NPY size")
    return tuple(header["shape"]), payload


def _packet_id(kind, start, end):
    return _sha(
        _canonical(
            {
                "bundle": INPUT_BUNDLE_SHA256,
                "kind": kind,
                "start": [start.numerator, start.denominator],
                "end": [end.numerator, end.denominator],
                "target": 1,
                "origin": 0,
                "parents": [],
            }
        )
    )


def _expected(root):
    folder = root / ORIGINALS
    observed = {name: _sha((folder / name).read_bytes()) for name in EXPECTED_ORIGINALS}
    if observed != EXPECTED_ORIGINALS:
        raise ValueError("original input hash")
    decoded = base64.b64decode(
        (folder / "N256_STATE.npz.b64").read_text().strip(), validate=True
    )
    if _sha(decoded) != EXPECTED_BINDINGS["decoded_npz_sha256"]:
        raise ValueError("decoded NPZ hash")
    with zipfile.ZipFile(io.BytesIO(decoded)) as archive:
        if set(archive.namelist()) != {"active.npy", "content.npy", "nodes.npy"}:
            raise ValueError("NPZ members")
        arrays = {name: _npy_payload(archive.read(name)) for name in archive.namelist()}
    active = struct.unpack("<257d", arrays["active.npy"][1])
    content = struct.unpack("<1028d", arrays["content.npy"][1])
    channels = [active] + [content[index::4] for index in range(4)]
    state = {
        "active": (
            (5, 2, 255),
            tuple(value for row in channels for value in tuple(row[1:256]) + (0.0,) * 255),
        ),
        "discounted_hit": ((5, 2), (0.0,) * 10),
        "lower_hit": ((5, 2), (0.0,) * 10),
        "occupation": ((5, 3), (0.0,) * 15),
        "upper": (
            (5, 3),
            tuple(value for row in channels for value in (row[-1], 0.0, 0.0)),
        ),
    }
    phase = json.loads((folder / "N256_PHASE.json").read_text())
    packets = {}
    for item in phase["packets"]:
        if set(item) != {"end", "identity", "mass", "signed_content", "start"}:
            raise ValueError("authentic signed-content packet schema")
        start, end = Fraction(item["start"]), Fraction(item["end"])
        width = end - start
        identity = _packet_id(item["identity"], start, end)
        packets[identity] = (
            {
                "identity": identity,
                "generation": 1,
                "origin": 0,
                "target": 1,
                "start": str(start),
                "end": str(end),
            },
            struct.pack(
                "<5d",
                float(Fraction(item["mass"]) / width),
                *(float(Fraction(value) / width) for value in item["signed_content"]),
            ),
            struct.pack("<2d", 0.0, 1.0),
        )
    return state, packets


def audit(root, capsule, build_receipt):
    payload = capsule.read_bytes()
    if len(payload) > 8 * 1024 * 1024 or payload[:8] != MAGIC:
        raise ValueError("capsule bound or magic")
    body, trailer = payload[:-32], payload[-32:]
    if hashlib.sha256(body).digest() != trailer:
        raise ValueError("capsule checksum")
    view, offset = memoryview(body), 8
    metadata_size, offset = _integer(view, offset, 4)
    metadata_raw, offset = _take(view, offset, metadata_size)
    metadata = json.loads(metadata_raw)
    if _canonical(metadata) != metadata_raw or metadata.get("schema") != SCHEMA:
        raise ValueError("metadata canonicality")
    expected_metadata = {
        "schema": SCHEMA,
        "identity": IDENTITY,
        "execution_key": EXECUTION_KEY,
        "capsule_identity": CAPSULE_IDENTITY,
        "lane": "warm",
        "lane_order": 0,
        "time": "0",
        "coordinate_count": 2656,
        "historical_negative_and_unknown_preserved": True,
        "largegrid_qualification": False,
        "production_adoption": False,
        "all_closed": False,
        "bindings": EXPECTED_BINDINGS,
    }
    if metadata != expected_metadata:
        raise ValueError("corrected-lineage metadata binding")
    expected_blocks, expected_packets = _expected(root)
    block_count, offset = _integer(view, offset, 4)
    blocks = {}
    for _ in range(block_count):
        name_size, offset = _integer(view, offset, 4)
        name, offset = _take(view, offset, name_size)
        dtype_size, offset = _integer(view, offset, 4)
        dtype, offset = _take(view, offset, dtype_size)
        dimensions, offset = _integer(view, offset, 4)
        shape = []
        for _ in range(dimensions):
            size, offset = _integer(view, offset, 8)
            shape.append(size)
        data_size, offset = _integer(view, offset, 8)
        data, offset = _take(view, offset, data_size)
        blocks[name.decode("ascii")] = (dtype.decode("ascii"), tuple(shape), data)
    for name, (shape, values) in expected_blocks.items():
        target = ("<f8", shape, struct.pack(f"<{len(values)}d", *values))
        if blocks.get(name) != target:
            raise ValueError("state block byte mismatch")
    packet_count, offset = _integer(view, offset, 4)
    packets = {}
    for _ in range(packet_count):
        size, offset = _integer(view, offset, 4)
        raw, offset = _take(view, offset, size)
        packet = json.loads(raw)
        if _canonical(packet) != raw:
            raise ValueError("packet metadata canonicality")
        alpha_size, offset = _integer(view, offset, 8)
        alpha, offset = _take(view, offset, alpha_size)
        operator_size, offset = _integer(view, offset, 8)
        operator, offset = _take(view, offset, operator_size)
        packets[packet["identity"]] = (packet, alpha, operator)
    if offset != len(view) or blocks.keys() != expected_blocks.keys():
        raise ValueError("capsule independent block comparison")
    if packets != expected_packets:
        raise ValueError("capsule independent packet comparison")
    coordinates = sum(len(item[2]) // 8 for item in blocks.values()) + sum(
        (len(alpha) + len(operator)) // 8 for _, alpha, operator in packets.values()
    )
    if coordinates != 2656:
        raise ValueError("coordinate denominator")

    build = json.loads(build_receipt.read_text())
    if build["capsule_sha256"] != _sha(payload) or build["capsule_bytes"] != len(payload):
        raise ValueError("build/cold capsule identity")
    counts = dict(build["counts"])
    counts["independent_parser_calls"] = 1
    record = {
        "schema": "hcsn-n256-corrected-t0-capsule-receipt-v1",
        "identity": IDENTITY,
        "bindings": EXPECTED_BINDINGS,
        "time": "0",
        "lane": "warm",
        "lane_order": 0,
        "semantics": {
            "channels": 5,
            "interior_nodes": 255,
            "phase_packets": 8,
            "phase_schema": ["end", "identity", "mass", "signed_content", "start"],
            "reset": "0.3131468965881033",
            "upper": "permanently_active_nonreturning",
        },
        "blocks": {
            "active": [5, 2, 255],
            "discounted_hit": [5, 2],
            "lower_hit": [5, 2],
            "occupation": [5, 3],
            "upper": [5, 3],
        },
        "coordinate_counts": {
            "compared": 2656,
            "equal": 2656,
            "mismatches": 0,
            "packet": 56,
            "state": 2600,
            "total": 2656,
        },
        "packet_ids": sorted(packets),
        "counts": counts,
        "canonical_decode_roundtrip_exact": True,
        "independent_comparison_exact": True,
        "capsule_bytes": len(payload),
        "capsule_sha256": _sha(payload),
        "historical_negative_and_unknown_preserved": True,
        "cold_load_qualified": False,
        "largegrid_qualification": False,
        "production_adoption": False,
        "all_closed": False,
    }
    from qualification.hcsn_currentstate_n256_corrected_t0_contract import contract

    contract.validate_future_capsule_record(record)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--capsule", type=Path, required=True)
    parser.add_argument("--build-receipt", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    arguments = parser.parse_args()
    result = audit(arguments.root, arguments.capsule, arguments.build_receipt)
    arguments.receipt.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
