"""Build the authentic N256 t=0 capsule without dynamics or numeric libraries."""

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


IDENTITY = "hcsn-n256-authentic-t0-capsule-20261115-c06d-001"
INPUT_BUNDLE_SHA256 = "17086fb6ba83211e8626c7ac9c22183f6c9c9a7dc615772b5a32d2c14ecb8e95"
ROSTER_IDENTITY = "e289c20d6595cb6d92dd3e2585bc7cb40fb0d5a408725c5edc14a9fb7f328fe2"
CAPSULE_IDENTITY = "d9cf0ced835ffcd85323d55c41f87999b52e13f669279cf4093fb629459671b9"
SERIALIZER_SHA256 = "3107fb296043de8f3e3c78e13aa940aea38aa64c16dfe68d342d2adb0c7aa97a"
CANDIDATE_SHA256 = "0f686be417338f7aa102a8386171798b06a63689acdd043a69e95212655bf3f9"
ORACLE_SHA256 = "4213f078e36cd3e296e9301df2d1788c3b9375cf7a911c73c0090fe500f5ab73"
EXPECTED_INPUTS = {
    "metadata": "88e84dd3aea396d34c7e2dd08d31f2e30bf694c20516dccde57e6dd1b0c2a3c6",
    "state": "360b4bf446e853209c58cdb3faded74d9114d872cfb9c730b220d14cef670f9c",
    "phase": "790fabee8825dbd4361f157f56d78641430fe50b9134cd2cb7b02b51b93fe548",
    "npz_b64": "926191319021c51421dd15d76c66c3b5c6d2efef0f28af3f76c893065a49dbeb",
    "npz": "c98a3339504c908081dbf77d2235a18de96da06b1ebda7b1c0f9192af1570eb8",
}
REL = {
    "metadata": "qualification/hcsn_n256_new_export/evidence/attempt001/METADATA.json",
    "state": "qualification/hcsn_n256_new_export/evidence/attempt001/N256_STATE.json",
    "phase": "qualification/hcsn_n256_new_export/evidence/attempt001/N256_PHASE.json",
    "npz_b64": "qualification/hcsn_n256_new_export/evidence/attempt001/N256_STATE.npz.b64",
}
MAX_CAPSULE_BYTES = 8 * 1024 * 1024
T0_COORDINATES = 2_656


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read_npy(raw):
    if raw[:6] != b"\x93NUMPY":
        raise ValueError("NPY magic")
    major = raw[6]
    width = 2 if major == 1 else 4
    if major not in (1, 2, 3):
        raise ValueError("NPY version")
    header_size = int.from_bytes(raw[8 : 8 + width], "little")
    offset = 8 + width
    header = ast.literal_eval(raw[offset : offset + header_size].decode("latin1"))
    payload = raw[offset + header_size :]
    if header["descr"] != "<f8" or header["fortran_order"] is not False:
        raise ValueError("NPY layout")
    shape = tuple(header["shape"])
    if len(payload) != 8 * math.prod(shape):
        raise ValueError("NPY size")
    return shape, payload


def _values(payload):
    return tuple(item[0] for item in struct.iter_unpack("<d", payload))


def source_identity(bundle, kind, start, end):
    return _sha(
        _canonical(
            {
                "bundle": bundle,
                "kind": kind,
                "start": [start.numerator, start.denominator],
                "end": [end.numerator, end.denominator],
                "target": 1,
                "origin": 0,
                "parents": [],
            }
        )
    )


def state_blocks(active_values, content_values):
    if len(active_values) != 257 or len(content_values) != 257 * 4:
        raise ValueError("authentic N256 state shape")
    interior = range(1, 256)
    channels = [active_values] + [content_values[index::4] for index in range(4)]
    active = []
    for channel in channels:
        active.extend(channel[index] for index in interior)
        active.extend(0.0 for _ in interior)
    upper = []
    for channel in channels:
        upper.extend((channel[-1], 0.0, 0.0))
    zeros10 = (0.0,) * 10
    zeros15 = (0.0,) * 15
    return {
        "active": ((5, 2, 255), tuple(active)),
        "discounted_hit": ((5, 2), zeros10),
        "lower_hit": ((5, 2), zeros10),
        "occupation": ((5, 3), zeros15),
        "upper": ((5, 3), tuple(upper)),
    }


def load_originals(root):
    paths = {name: root / path for name, path in REL.items()}
    observed = {name: _sha(path.read_bytes()) for name, path in paths.items()}
    decoded = base64.b64decode(paths["npz_b64"].read_text().strip(), validate=True)
    observed["npz"] = _sha(decoded)
    if observed != EXPECTED_INPUTS or _sha(_canonical(observed)) != INPUT_BUNDLE_SHA256:
        raise ValueError("authentic N256 input identity")
    with zipfile.ZipFile(io.BytesIO(decoded)) as archive:
        if set(archive.namelist()) != {"active.npy", "content.npy", "nodes.npy"}:
            raise ValueError("NPZ member set")
        arrays = {name: _read_npy(archive.read(name)) for name in archive.namelist()}
    if {name: shape for name, (shape, _) in arrays.items()} != {
        "active.npy": (257,),
        "content.npy": (257, 4),
        "nodes.npy": (257,),
    }:
        raise ValueError("NPZ shapes")
    state = json.loads(paths["state"].read_text())
    checks = (
        (arrays["nodes.npy"][1], state["nodes_fp64_hex"]),
        (arrays["active.npy"][1], state["active_probability_fp64_hex"]),
        (arrays["content.npy"][1], state["signed_content_fp64_hex_row_major"]),
    )
    for payload, expected in checks:
        if [float(value[0]).hex() for value in struct.iter_unpack("<d", payload)] != expected:
            raise ValueError("NPZ/JSON byte mismatch")
    return arrays, json.loads(paths["phase"].read_text())


def build(root, output):
    from qualification.hcsn_currentstate_n256_canonical_serializer_intent import canonical_serializer as serializer

    if _sha(Path(serializer.__file__).read_bytes()) != SERIALIZER_SHA256:
        raise ValueError("canonical serializer source mismatch")
    arrays, phase = load_originals(root)
    blocks = []
    for name, (shape, values) in state_blocks(
        _values(arrays["active.npy"][1]), _values(arrays["content.npy"][1])
    ).items():
        blocks.append(serializer.Block(name, "<f8", shape, struct.pack(f"<{len(values)}d", *values)))
    packets = []
    for item in phase["packets"]:
        start, end = Fraction(item["start"]), Fraction(item["end"])
        width = end - start
        alpha = (float(Fraction(item["mass"]) / width),) + tuple(
            float(Fraction(value) / width) for value in item["signed_content"]
        )
        packets.append(
            serializer.Packet(
                identity=source_identity(INPUT_BUNDLE_SHA256, item["identity"], start, end),
                generation=1,
                origin=0,
                target=1,
                start=str(start),
                end=str(end),
                alpha=struct.pack("<5d", *alpha),
                operator=struct.pack("<2d", 0.0, 1.0),
            )
        )
    envelope = serializer.Envelope(
        metadata={
            "identity": IDENTITY,
            "capsule_identity": CAPSULE_IDENTITY,
            "lane": "warm",
            "lane_order": 0,
            "time": "0",
            "coordinate_count": T0_COORDINATES,
            "historical_negative_and_unknown_preserved": True,
            "largegrid_qualification": False,
            "production_adoption": False,
            "bindings": {
                "candidate_source_sha256": CANDIDATE_SHA256,
                "oracle_source_sha256": ORACLE_SHA256,
                "input_bundle_sha256": INPUT_BUNDLE_SHA256,
                "roster_identity": ROSTER_IDENTITY,
            },
        },
        blocks=tuple(blocks),
        packets=tuple(sorted(packets, key=lambda packet: packet.identity)),
    )
    capsule_sha256 = serializer.publish_atomic(output, envelope)
    size = output.stat().st_size
    if size > MAX_CAPSULE_BYTES:
        raise ValueError("t=0 capsule exceeds bounded allocation")
    return {
        "identity": IDENTITY,
        "status": "PASS_AUTHENTIC_N256_T0_CAPSULE_HOLD",
        "capsule_sha256": capsule_sha256,
        "capsule_bytes": size,
        "coordinate_count": T0_COORDINATES,
        "state_coordinates": 2600,
        "packet_coordinates": 56,
        "packets": 8,
        "serializer_calls": 1,
        "dynamic_calls": 0,
        "matrix_exponential_calls": 0,
        "provider_calls": 0,
        "torch_calls": 0,
        "optimizer_calls": 0,
        "largegrid_qualification": False,
        "all_closed": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.root, args.output)
    args.receipt.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
