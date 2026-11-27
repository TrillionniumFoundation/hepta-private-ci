"""Independent fresh-process audit of the authentic N256 t=0 capsule."""

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
IDENTITY = "hcsn-n256-authentic-t0-capsule-20261115-c06d-001"
INPUT_BUNDLE_SHA256 = "17086fb6ba83211e8626c7ac9c22183f6c9c9a7dc615772b5a32d2c14ecb8e95"
CAPSULE_IDENTITY = "d9cf0ced835ffcd85323d55c41f87999b52e13f669279cf4093fb629459671b9"
ROSTER_IDENTITY = "e289c20d6595cb6d92dd3e2585bc7cb40fb0d5a408725c5edc14a9fb7f328fe2"
EXPECTED = {
    "METADATA.json": "88e84dd3aea396d34c7e2dd08d31f2e30bf694c20516dccde57e6dd1b0c2a3c6",
    "N256_STATE.json": "360b4bf446e853209c58cdb3faded74d9114d872cfb9c730b220d14cef670f9c",
    "N256_PHASE.json": "790fabee8825dbd4361f157f56d78641430fe50b9134cd2cb7b02b51b93fe548",
    "N256_STATE.npz.b64": "926191319021c51421dd15d76c66c3b5c6d2efef0f28af3f76c893065a49dbeb",
}
ORIGINALS = Path("qualification/hcsn_n256_new_export/evidence/attempt001")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("ascii")


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
    return _sha(_canonical({
        "bundle": INPUT_BUNDLE_SHA256,
        "kind": kind,
        "start": [start.numerator, start.denominator],
        "end": [end.numerator, end.denominator],
        "target": 1,
        "origin": 0,
        "parents": [],
    }))


def _expected(root):
    folder = root / ORIGINALS
    for name, digest in EXPECTED.items():
        if _sha((folder / name).read_bytes()) != digest:
            raise ValueError("original input hash")
    decoded = base64.b64decode((folder / "N256_STATE.npz.b64").read_text().strip(), validate=True)
    if _sha(decoded) != "c98a3339504c908081dbf77d2235a18de96da06b1ebda7b1c0f9192af1570eb8":
        raise ValueError("decoded NPZ hash")
    with zipfile.ZipFile(io.BytesIO(decoded)) as archive:
        arrays = {name: _npy_payload(archive.read(name)) for name in archive.namelist()}
    active = struct.unpack("<257d", arrays["active.npy"][1])
    content = struct.unpack("<1028d", arrays["content.npy"][1])
    channels = [active] + [content[index::4] for index in range(4)]
    state = {}
    state["active"] = ((5, 2, 255), tuple(value for row in channels for value in tuple(row[1:256]) + (0.0,) * 255))
    state["discounted_hit"] = ((5, 2), (0.0,) * 10)
    state["lower_hit"] = ((5, 2), (0.0,) * 10)
    state["occupation"] = ((5, 3), (0.0,) * 15)
    state["upper"] = ((5, 3), tuple(value for row in channels for value in (row[-1], 0.0, 0.0)))
    phase = json.loads((folder / "N256_PHASE.json").read_text())
    packets = {}
    for item in phase["packets"]:
        start, end = Fraction(item["start"]), Fraction(item["end"])
        width = end - start
        identity = _packet_id(item["identity"], start, end)
        packets[identity] = (
            {"identity": identity, "generation": 1, "origin": 0, "target": 1, "start": str(start), "end": str(end)},
            struct.pack("<5d", float(Fraction(item["mass"]) / width), *(float(Fraction(value) / width) for value in item["signed_content"])),
            struct.pack("<2d", 0.0, 1.0),
        )
    return state, packets


def audit(root, capsule):
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
    expected_metadata = (IDENTITY, CAPSULE_IDENTITY, ROSTER_IDENTITY, 2656, False)
    observed_metadata = (metadata.get("identity"), metadata.get("capsule_identity"), metadata.get("bindings", {}).get("roster_identity"), metadata.get("coordinate_count"), metadata.get("largegrid_qualification"))
    if observed_metadata != expected_metadata:
        raise ValueError("metadata binding")
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
        if blocks.get(name) != ("<f8", shape, struct.pack(f"<{len(values)}d", *values)):
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
    if offset != len(view) or blocks.keys() != expected_blocks.keys() or packets != expected_packets:
        raise ValueError("capsule independent byte comparison")
    coordinates = sum(len(item[2]) // 8 for item in blocks.values()) + sum((len(alpha) + len(operator)) // 8 for _, alpha, operator in packets.values())
    if coordinates != 2656:
        raise ValueError("coordinate denominator")
    return {"identity": IDENTITY, "status": "PASS_INDEPENDENT_COLD_BYTES_HOLD", "capsule_sha256": _sha(payload), "capsule_bytes": len(payload), "coordinates_compared": coordinates, "coordinates_equal": coordinates, "mismatches": 0, "dynamic_calls": 0, "matrix_exponential_calls": 0, "torch_calls": 0, "optimizer_calls": 0, "largegrid_qualification": False, "all_closed": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--capsule", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.root, args.capsule)
    args.receipt.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
