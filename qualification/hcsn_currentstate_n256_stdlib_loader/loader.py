"""Fail-closed standard-library decoder for the authentic N256 new export.

This source is intentionally independent from the frozen candidate and oracle
numeric kernels.  It decodes and binds input originals only; it performs no
operator construction or dynamic propagation.
"""

import ast
import base64
import hashlib
import io
import json
import struct
import zipfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path


IDENTITY = "hcsn-n256-new-export-20261112-c06d-attempt001"
STATE_SHA256 = "360b4bf446e853209c58cdb3faded74d9114d872cfb9c730b220d14cef670f9c"
PHASE_SHA256 = "790fabee8825dbd4361f157f56d78641430fe50b9134cd2cb7b02b51b93fe548"
BASE64_SHA256 = "926191319021c51421dd15d76c66c3b5c6d2efef0f28af3f76c893065a49dbeb"
NPZ_SHA256 = "c98a3339504c908081dbf77d2235a18de96da06b1ebda7b1c0f9192af1570eb8"
EXPECTED_MEMBERS = ("nodes.npy", "active.npy", "content.npy")
EXPECTED_SHAPES = ((257,), (257,), (257, 4))


class N256InputError(ValueError):
    """Raised before accepting any noncanonical or mismatched input byte."""


@dataclass(frozen=True)
class N256InputCertificate:
    identity: str
    npz_sha256: str
    nodes: int
    active_coordinates: int
    signed_content_coordinates: int
    phase_packets: int
    compared_fp64_coordinates: int
    authentic_n256_bundle_loaded: bool = True
    independent_stdlib_decode: bool = True
    candidate_or_oracle_imported: bool = False
    dynamic_calls: int = 0
    matrix_exponential_calls: int = 0
    reference_records_emitted: int = 0
    largegrid_qualification: bool = False


def _read_exact(path, expected_sha256, name):
    value = Path(path).read_bytes()
    observed = hashlib.sha256(value).hexdigest()
    if observed != expected_sha256:
        raise N256InputError(f"{name} SHA-256 mismatch: {observed}")
    return value


def _parse_npy(value, expected_shape, name):
    if not value.startswith(b"\x93NUMPY\x01\x00") or len(value) < 10:
        raise N256InputError(f"{name} is not canonical NPY v1")
    header_length = struct.unpack("<H", value[8:10])[0]
    header_end = 10 + header_length
    if header_end > len(value):
        raise N256InputError(f"{name} header exceeds member bytes")
    try:
        header = ast.literal_eval(value[10:header_end].decode("latin1").strip())
    except (SyntaxError, ValueError) as error:
        raise N256InputError(f"{name} header is invalid") from error
    expected_header = {
        "descr": "<f8",
        "fortran_order": False,
        "shape": expected_shape,
    }
    if header != expected_header:
        raise N256InputError(f"{name} header mismatch")
    payload = value[header_end:]
    coordinates = 1
    for dimension in expected_shape:
        coordinates *= dimension
    if len(payload) != coordinates * 8:
        raise N256InputError(f"{name} payload length mismatch")
    return tuple(
        float.hex(struct.unpack("<d", payload[offset : offset + 8])[0])
        for offset in range(0, len(payload), 8)
    )


def _decode_npz(base64_path):
    encoded = _read_exact(base64_path, BASE64_SHA256, "N256 base64")
    if len(encoded) != 16897 or not encoded.endswith(b"\n") or b"\n" in encoded[:-1]:
        raise N256InputError("N256 base64 is not the canonical one-line-plus-LF form")
    try:
        archive = base64.b64decode(encoded[:-1], validate=True)
    except ValueError as error:
        raise N256InputError("N256 base64 decoding failed") from error
    if len(archive) != 12671 or hashlib.sha256(archive).hexdigest() != NPZ_SHA256:
        raise N256InputError("N256 NPZ bytes mismatch")
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            members = bundle.infolist()
            if tuple(member.filename for member in members) != EXPECTED_MEMBERS:
                raise N256InputError("N256 NPZ member roster mismatch")
            if any(member.is_dir() or member.file_size > 9000 for member in members):
                raise N256InputError("N256 NPZ member bound mismatch")
            values = tuple(
                _parse_npy(bundle.read(member), shape, member.filename)
                for member, shape in zip(members, EXPECTED_SHAPES, strict=True)
            )
    except (OSError, zipfile.BadZipFile) as error:
        raise N256InputError("N256 NPZ ZIP decoding failed") from error
    return values


def _validate_phase(path):
    raw = _read_exact(path, PHASE_SHA256, "N256 phase JSON")
    try:
        phase = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise N256InputError("N256 phase JSON is invalid") from error
    if (
        phase.get("schema") != "hcsn-n256-new-export-phase-v1"
        or phase.get("identity") != IDENTITY
        or phase.get("packet_count") != 8
        or not isinstance(phase.get("packets"), list)
        or len(phase["packets"]) != 8
    ):
        raise N256InputError("N256 phase envelope mismatch")
    prior_end = Fraction(0)
    for index, packet in enumerate(phase["packets"]):
        expected_identity = f"seed37-c0_b1-step24-pos1-n256-new-export-phase-{index}"
        try:
            start = Fraction(packet["start"])
            end = Fraction(packet["end"])
            mass = Fraction(packet["mass"])
            signed = tuple(Fraction(value) for value in packet["signed_content"])
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as error:
            raise N256InputError("N256 phase packet is invalid") from error
        if (
            packet.get("identity") != expected_identity
            or start != prior_end
            or end <= start
            or mass < 0
            or len(signed) != 4
        ):
            raise N256InputError("N256 phase packet semantics mismatch")
        prior_end = end
    if prior_end != Fraction(1, 5):
        raise N256InputError("N256 phase support endpoint mismatch")
    return phase


def load_authentic_n256_input(state_path, phase_path, base64_path):
    """Load and byte-bind all authentic new-export N256 input coordinates."""

    state_raw = _read_exact(state_path, STATE_SHA256, "N256 state JSON")
    try:
        state = json.loads(state_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise N256InputError("N256 state JSON is invalid") from error
    if (
        state.get("schema") != "hcsn-n256-new-export-state-v1"
        or state.get("identity") != IDENTITY
        or state.get("dtype") != "<f8"
        or state.get("nodes_shape") != [257]
        or state.get("active_shape") != [257]
        or state.get("content_shape") != [257, 4]
    ):
        raise N256InputError("N256 state envelope mismatch")
    nodes, active, content = _decode_npz(base64_path)
    expected = (
        tuple(state.get("nodes_fp64_hex", ())),
        tuple(state.get("active_probability_fp64_hex", ())),
        tuple(state.get("signed_content_fp64_hex_row_major", ())),
    )
    observed = (nodes, active, content)
    if observed != expected:
        raise N256InputError("N256 state JSON and NPZ coordinates differ")
    phase = _validate_phase(phase_path)
    return (nodes, active, content, phase), N256InputCertificate(
        identity=IDENTITY,
        npz_sha256=NPZ_SHA256,
        nodes=len(nodes),
        active_coordinates=len(active),
        signed_content_coordinates=len(content),
        phase_packets=len(phase["packets"]),
        compared_fp64_coordinates=len(nodes) + len(active) + len(content),
    )
