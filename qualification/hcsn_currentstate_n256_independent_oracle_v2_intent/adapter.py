"""Stdlib-only authentic input adapter for a future independent N256 oracle.

This module deliberately performs no numerical propagation.  It validates the
exact persisted originals and maps their byte-level active/signed-content
surfaces without accepting the legacy ``content`` phase alias.
"""

import ast
import base64
import hashlib
import io
import json
import math
import struct
import zipfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path


INPUT_BUNDLE_SHA256 = "17086fb6ba83211e8626c7ac9c22183f6c9c9a7dc615772b5a32d2c14ecb8e95"
EXPECTED = {
    "metadata": "88e84dd3aea396d34c7e2dd08d31f2e30bf694c20516dccde57e6dd1b0c2a3c6",
    "state": "360b4bf446e853209c58cdb3faded74d9114d872cfb9c730b220d14cef670f9c",
    "phase": "790fabee8825dbd4361f157f56d78641430fe50b9134cd2cb7b02b51b93fe548",
    "npz_b64": "926191319021c51421dd15d76c66c3b5c6d2efef0f28af3f76c893065a49dbeb",
    "npz": "c98a3339504c908081dbf77d2235a18de96da06b1ebda7b1c0f9192af1570eb8",
}
RELATIVE = {
    "metadata": "qualification/hcsn_n256_new_export/evidence/attempt001/METADATA.json",
    "state": "qualification/hcsn_n256_new_export/evidence/attempt001/N256_STATE.json",
    "phase": "qualification/hcsn_n256_new_export/evidence/attempt001/N256_PHASE.json",
    "npz_b64": "qualification/hcsn_n256_new_export/evidence/attempt001/N256_STATE.npz.b64",
}


@dataclass(frozen=True)
class AuthenticOracleInput:
    nodes_payload: bytes
    active_payload: bytes
    signed_content_payload: bytes
    phase_packets: tuple


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _npy(raw):
    if raw[:6] != b"\x93NUMPY" or raw[6] not in (1, 2, 3):
        raise ValueError("NPY header")
    width = 2 if raw[6] == 1 else 4
    header_size = int.from_bytes(raw[8 : 8 + width], "little")
    offset = 8 + width
    header = ast.literal_eval(raw[offset : offset + header_size].decode("latin1"))
    payload = raw[offset + header_size :]
    if header["descr"] != "<f8" or header["fortran_order"] is not False:
        raise ValueError("NPY FP64 layout")
    shape = tuple(header["shape"])
    if len(payload) != 8 * math.prod(shape):
        raise ValueError("NPY payload size")
    return shape, payload


def _validate_phase(phase):
    if not isinstance(phase, dict) or not isinstance(phase.get("packets"), list):
        raise ValueError("authentic phase packet collection")
    packets = []
    for item in phase["packets"]:
        if set(item) != {"end", "identity", "mass", "signed_content", "start"}:
            raise ValueError("authentic phase packet field set")
        signed = item["signed_content"]
        if not isinstance(signed, list) or len(signed) != 4:
            raise ValueError("authentic signed-content channel count")
        start, end = Fraction(item["start"]), Fraction(item["end"])
        if end <= start:
            raise ValueError("authentic phase interval")
        alpha = (Fraction(item["mass"]) / (end - start),) + tuple(
            Fraction(value) / (end - start) for value in signed
        )
        packets.append((item["identity"], start, end, alpha))
    if len(packets) != 8:
        raise ValueError("authentic phase packet denominator")
    return tuple(packets)


def load_authentic_input(root):
    """Read the immutable originals without importing NumPy or SciPy."""

    root = Path(root)
    paths = {name: root / relative for name, relative in RELATIVE.items()}
    observed = {name: _sha(path.read_bytes()) for name, path in paths.items()}
    decoded = base64.b64decode(paths["npz_b64"].read_text().strip(), validate=True)
    observed["npz"] = _sha(decoded)
    if observed != EXPECTED or _sha(_canonical(observed)) != INPUT_BUNDLE_SHA256:
        raise ValueError("authentic N256 input identity")
    with zipfile.ZipFile(io.BytesIO(decoded)) as archive:
        if set(archive.namelist()) != {"active.npy", "content.npy", "nodes.npy"}:
            raise ValueError("authentic NPZ member set")
        arrays = {name: _npy(archive.read(name)) for name in archive.namelist()}
    if {name: shape for name, (shape, _) in arrays.items()} != {
        "active.npy": (257,),
        "content.npy": (257, 4),
        "nodes.npy": (257,),
    }:
        raise ValueError("authentic N256 array shapes")
    state = json.loads(paths["state"].read_text())
    checks = (
        (arrays["nodes.npy"][1], state["nodes_fp64_hex"]),
        (arrays["active.npy"][1], state["active_probability_fp64_hex"]),
        (arrays["content.npy"][1], state["signed_content_fp64_hex_row_major"]),
    )
    for payload, expected in checks:
        if [value[0].hex() for value in struct.iter_unpack("<d", payload)] != expected:
            raise ValueError("NPZ/JSON byte mismatch")
    phase = _validate_phase(json.loads(paths["phase"].read_text()))
    return AuthenticOracleInput(
        nodes_payload=arrays["nodes.npy"][1],
        active_payload=arrays["active.npy"][1],
        signed_content_payload=arrays["content.npy"][1],
        phase_packets=phase,
    )
