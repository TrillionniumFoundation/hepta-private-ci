"""Frozen candidate body; this source-only stage never calls :func:`execute`."""

import hashlib
import json
import math
import os
import struct
import zipfile
from dataclasses import dataclass, replace
from fractions import Fraction as F
from pathlib import Path


CHANNELS = 5
INTERIOR = 255
RIGHT = F(1, 1000)
DELAY = F(1, 5)
DISCOUNT = 0.15
MAX_CAPSULE_BYTES = 8 * 1024 * 1024
INPUT_BUNDLE_SHA256 = "17086fb6ba83211e8626c7ac9c22183f6c9c9a7dc615772b5a32d2c14ecb8e95"
BOUNDARY_ZIP_SHA256 = "43d990c1a17e4e075681820caec327e368a0ae3144abdac21ad383d133f3f595"
BOUNDARY_SHA256 = "e580e44a679ecf9e2588c989cd4d026e326e7364331c46d1927b00ccada78fd4"
ORACLE_ZIP_SHA256 = "3ba4ef88608cbfc04d83fd82c1f05d7b439edf4f9338365625e79b0d52f02400"
ORACLE_SHA256 = "b2a6e204e613fead7c0735b12a335a88d2394c8f4da99cab798133443c55dc18"
BOUNDARY_MEMBER = "CANDIDATE_BOUNDARY.bin"
ORACLE_MEMBER = "N256_WARM1.bin"
METADATA = "qualification/hcsn_n256_new_export/evidence/attempt001/METADATA.json"
PHASE = "qualification/hcsn_n256_new_export/evidence/attempt001/N256_PHASE.json"
STATE = "qualification/hcsn_n256_new_export/evidence/attempt001/N256_STATE.json"
NPZ_B64 = "qualification/hcsn_n256_new_export/evidence/attempt001/N256_STATE.npz.b64"


@dataclass(frozen=True)
class StructurePacket:
    source: str
    generation: int
    target: int
    origin: int
    start: F
    end: F
    generator: object
    alpha: object
    output: object

    @property
    def dimension(self):
        return len(self.output)


def _sha_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def _sha_file(path):
    return _sha_bytes(Path(path).read_bytes())


def _publish_bytes(path, raw):
    path = Path(path)
    if path.exists():
        raise ValueError("output already exists")
    temporary = Path(f"{path}.tmp")
    temporary.write_bytes(raw)
    os.replace(temporary, path)


def _canonical(value):
    return json.dumps(
        value, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode()


def _source_identity(kind, start, end, target, origin, parents):
    return hashlib.sha256(
        _canonical({
            "bundle": INPUT_BUNDLE_SHA256,
            "kind": kind,
            "start": [start.numerator, start.denominator],
            "end": [end.numerator, end.denominator],
            "target": target,
            "origin": origin,
            "parents": sorted(parents),
        })
    ).hexdigest()


def _zip_member(path, archive_sha, member, member_sha):
    if _sha_file(path) != archive_sha:
        raise ValueError("archived ZIP identity")
    with zipfile.ZipFile(path) as archive:
        if archive.namelist().count(member) != 1:
            raise ValueError("archived member identity")
        raw = archive.read(member)
    if _sha_bytes(raw) != member_sha:
        raise ValueError("archived member digest")
    return raw


def _require_exact_bytes(reference, rebuilt):
    if _sha_bytes(reference) != BOUNDARY_SHA256:
        raise ValueError("reference boundary identity")
    if rebuilt != reference:
        raise ValueError("rebuilt boundary is not bitwise exact")


def require_exact_boundary(reference, rebuilt):
    """Compare all 68,105 FP64 coordinates before numerical imports."""

    from qualification.hcsn_currentstate_n256_boundary_container_contract.boundary_codec import (
        decode_boundary,
    )

    _require_exact_bytes(reference, rebuilt)
    left, right = decode_boundary(reference), decode_boundary(rebuilt)
    if tuple(left) != tuple(right):
        raise ValueError("boundary section identity")
    comparisons = 0
    for name in left:
        if len(left[name]) != len(right[name]) or len(left[name]) % 8:
            raise ValueError("boundary section length")
        for offset in range(0, len(left[name]), 8):
            comparisons += 1
            if left[name][offset : offset + 8] != right[name][offset : offset + 8]:
                raise ValueError("boundary coordinate mismatch")
    if comparisons != 68105:
        raise ValueError("boundary coordinate denominator")
    return comparisons


def _numeric_modules():
    import numpy as np
    from scipy import sparse
    from scipy.linalg import expm

    return np, sparse, expm


def _stream_action(generator, initial, selectors, duration, discount, np, expm):
    outputs = selectors.shape[1]
    dimension = generator.shape[0]
    augmented = np.zeros((dimension + outputs, dimension + outputs), dtype="float64")
    augmented[:dimension, :dimension] = generator - discount * np.eye(dimension)
    augmented[:dimension, dimension:] = selectors
    seed = np.concatenate(
        (initial, np.zeros((initial.shape[0], outputs), dtype="float64")), axis=1
    )
    evolved = (expm(augmented.T * float(duration)) @ seed.T).T
    return evolved[:, :dimension], evolved[:, dimension:]


def _arrays(raw, np):
    from qualification.hcsn_currentstate_n256_boundary_container_contract.boundary_codec import (
        decode_boundary,
    )

    sections = decode_boundary(raw)
    exact = {
        "extended_generator": (257, 257),
        "initial": (5, 257),
        "lower_selector": (257, 1),
        "discounted_selectors": (257, 2),
    }
    arrays = {}
    for name, shape in exact.items():
        array = np.frombuffer(sections[name], dtype="<f8").reshape(shape)
        if array.flags.writeable:
            raise ValueError("boundary view must be immutable")
        arrays[name] = array
    return arrays


def _tensor(np, values):
    from qualification.hcsn_currentstate_n256_firststep_serializer_v2.serializer import Tensor

    array = np.asarray(values, dtype="<f8", order="C")
    return Tensor("<f8", tuple(array.shape), array.tobytes(order="C"))


def _phase_alpha(item):
    if set(item) != {"end", "identity", "mass", "signed_content", "start"}:
        raise ValueError("authentic phase packet field set")
    start, end = F(item["start"]), F(item["end"])
    width = end - start
    signed = item["signed_content"]
    if width <= 0 or not isinstance(signed, list) or len(signed) != CHANNELS - 1:
        raise ValueError("authentic phase packet content")
    return (float(F(item["mass"]) / width),) + tuple(
        float(F(value) / width) for value in signed
    )


def _initial_structure(arrays, phase, np):
    original_active = np.asarray(arrays["active.npy"][1], dtype="<f8")
    original_content = np.asarray(arrays["content.npy"][1], dtype="<f8").reshape(257, 4)
    active = np.zeros((CHANNELS, 2, INTERIOR), dtype="float64")
    active[:, 0] = np.column_stack((original_active[1:-1], original_content[1:-1])).T
    upper = np.zeros((CHANNELS, 3), dtype="float64")
    upper[:, 0] = np.r_[original_active[-1], original_content[-1]]
    state = {
        "active": active,
        "upper": upper,
        "mass": np.zeros((CHANNELS, 2), dtype="float64"),
        "discounted_hit": np.zeros((CHANNELS, 2), dtype="float64"),
        "occupation": np.zeros((CHANNELS, 3), dtype="float64"),
    }
    packets = []
    for item in phase["packets"]:
        start, end = F(item["start"]), F(item["end"])
        packets.append(StructurePacket(
            _source_identity(item["identity"], start, end, 1, 0, ()),
            1, 1, 0, start, end,
            np.zeros((1, 1), dtype="float64"),
            np.asarray(_phase_alpha(item), dtype="float64").reshape(CHANNELS, 1),
            np.ones(1, dtype="float64"),
        ))
    return state, tuple(packets)


def _payload(np, array, shape, name):
    if tuple(array.shape) != shape:
        raise ValueError(f"candidate shape: {name}")
    if array.dtype.str != "<f8" or not array.flags.c_contiguous:
        raise ValueError(f"candidate raw layout: {name}")
    if not np.isfinite(array).all():
        raise ValueError(f"candidate finite values: {name}")
    return array.tobytes(order="C")


def _build_boundary_and_structure(root, np, sparse):
    """Read the four authentic files once and return boundary plus structure."""

    from qualification.hcsn_currentstate_n256_boundary_container_contract.boundary_codec import (
        encode_boundary,
    )
    from qualification.hcsn_currentstate_n256_engineering import candidate as primitive

    root = Path(root)
    paths = [root / item for item in (METADATA, STATE, PHASE, NPZ_B64)]
    hashes, metadata, phase, arrays = primitive.load_inputs(*paths)
    bundle = hashlib.sha256(
        json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if bundle != INPUT_BUNDLE_SHA256:
        raise ValueError("candidate input bundle")
    spatial, lower, upper, reset = primitive.spatial_operator(
        metadata, arrays["nodes.npy"][1]
    )
    zero = primitive.CSR.from_rows(({},))
    releasing = []
    for item in phase["packets"]:
        start, end = F(item["start"]), F(item["end"])
        if start == 0:
            source = primitive.source_identity(
                bundle, item["identity"], start, end, 1, 0, ()
            )
            template = primitive.Template(
                source, 1, start, end, 1, 0, zero, (1.0,), ()
            )
            releasing.append((template, _phase_alpha(item)))
    if len(releasing) != 1:
        raise ValueError("candidate warm releasing-parent denominator")
    template, phase_alpha = releasing[0]
    operator, _ = primitive.block_operator((template,), spatial, lower, reset)
    core = sparse.csr_matrix(
        (operator.data, operator.indices, operator.indptr),
        shape=(operator.dimension, operator.dimension), dtype="<f8",
    )
    sink = sparse.csr_matrix(
        [(0.0,) * (operator.dimension - INTERIOR) + tuple(upper)], dtype="<f8"
    ).T
    matrix = sparse.bmat(
        ((core, sink), (None, sparse.csr_matrix((1, 1), dtype="<f8"))), format="csr"
    )
    if not matrix.has_canonical_format or not matrix.has_sorted_indices:
        raise ValueError("candidate canonical CSR")
    extended = matrix.toarray(order="C")
    active = np.asarray(arrays["active.npy"][1], dtype="<f8")
    content = np.asarray(arrays["content.npy"][1], dtype="<f8").reshape(257, 4)
    interior = np.column_stack((active[1:-1], content[1:-1])).T
    alpha = np.asarray(phase_alpha, dtype="<f8").reshape(CHANNELS, 1)
    initial = np.ascontiguousarray(
        np.concatenate((alpha, interior, np.zeros((CHANNELS, 1), dtype="<f8")), axis=1),
        dtype="<f8",
    )
    lower_selector = np.zeros((257, 1), dtype="<f8")
    lower_selector[1:256, 0] = lower
    discounted = np.zeros((257, 2), dtype="<f8")
    discounted[1:256, 0] = lower
    discounted[1:, 1] = 1.0
    encoded = encode_boundary({
        "extended_generator": _payload(np, extended, (257, 257), "generator"),
        "initial": _payload(np, initial, (5, 257), "initial"),
        "lower_selector": _payload(np, lower_selector, (257, 1), "lower"),
        "discounted_selectors": _payload(np, discounted, (257, 2), "discounted"),
    })
    if len(encoded) != 545171:
        raise ValueError("candidate container length")
    state, pending = _initial_structure(arrays, phase, np)
    return encoded, state, pending


def _candidate_envelope(oracle, rebuilt, state, pending, np, expm):
    from qualification.hcsn_currentstate_n256_firststep_serializer_v2.serializer import (
        Block,
        Envelope,
        Packet,
        coordinate_counts,
    )

    parents = tuple(item for item in pending if item.start == 0 and item.target == 1)
    if len(parents) != 1:
        raise ValueError("warm first-step releasing packet denominator")
    parent = parents[0]

    first = _arrays(rebuilt, np)
    if _sha_bytes(rebuilt) != BOUNDARY_SHA256:
        raise ValueError("boundary changed before undiscounted action")
    final, hit = _stream_action(
        first["extended_generator"], first["initial"], first["lower_selector"],
        RIGHT, 0.0, np, expm,
    )
    second = _arrays(rebuilt, np)
    if _sha_bytes(rebuilt) != BOUNDARY_SHA256:
        raise ValueError("boundary changed before discounted action")
    _, discounted = _stream_action(
        second["extended_generator"], second["initial"],
        second["discounted_selectors"], RIGHT, DISCOUNT, np, expm,
    )

    fragment = replace(parent, start=RIGHT, alpha=tuple(final[:, : parent.dimension].ravel()))
    state["active"][:, 0] = final[:, -INTERIOR - 1 : -1]
    state["upper"][:, 1] = final[:, -1]
    state["mass"][:, 0] += hit[:, 0]
    state["discounted_hit"][:, 0] += discounted[:, 0]
    state["occupation"][:, 1] += discounted[:, 1]
    state["occupation"][:, 0] += state["upper"][:, 0] * (
        -math.expm1(-DISCOUNT * float(RIGHT)) / DISCOUNT
    )
    emitted_source = _source_identity("lower-flux", F(0), RIGHT, 2, 1, (parent.source,))

    blocks = tuple(
        Block(name, _tensor(np, value))
        for name, value in sorted((
            ("active", state["active"]),
            ("upper", state["upper"]),
            ("mass", state["mass"]),
            ("discounted_hit", state["discounted_hit"]),
            ("occupation", state["occupation"]),
        ))
    )
    retained = tuple(item for item in pending if item is not parent) + (fragment,)
    packets = [
        Packet(
            identity=item.source, generation=item.generation, origin=item.origin,
            target=item.target, start=str(item.start), end=str(item.end),
            alpha=_tensor(np, np.asarray(item.alpha).reshape(CHANNELS, item.dimension)),
            generator=_tensor(np, item.generator),
            output=_tensor(np, item.output),
        )
        for item in retained
    ]
    packets.append(
        Packet(
            identity=emitted_source, generation=2, origin=1, target=2,
            start=str(DELAY), end=str(RIGHT + DELAY),
            alpha=_tensor(np, first["initial"][:, :-1]),
            generator=_tensor(np, first["extended_generator"][:-1, :-1]),
            output=_tensor(np, first["lower_selector"][:-1, 0]),
        )
    )
    envelope = Envelope(dict(oracle.metadata), blocks, tuple(sorted(packets, key=lambda p: p.identity)))
    if coordinate_counts(envelope) != {
        "state": 2600, "packet_alpha": 1320, "packet_generator": 65544,
        "packet_output": 264, "packet": 67128, "total": 69728,
    }:
        raise ValueError("candidate coordinate denominator")
    return envelope


def _ordered_int(raw):
    bits = int.from_bytes(raw, "little")
    return (0xFFFFFFFFFFFFFFFF - bits) if bits >> 63 else bits + 0x8000000000000000


def execute(root, boundary_zip, oracle_zip, rebuilt_boundary_path, output_path):
    """Future admitted child entry; source freeze executes this zero times."""

    from qualification.hcsn_currentstate_n256_firststep_serializer_v2.serializer import (
        coordinate_rows,
        decode,
        publish_atomic,
    )

    reference = _zip_member(
        boundary_zip, BOUNDARY_ZIP_SHA256, BOUNDARY_MEMBER, BOUNDARY_SHA256
    )
    np, sparse, expm = _numeric_modules()
    rebuilt, state, pending = _build_boundary_and_structure(root, np, sparse)
    require_exact_boundary(reference, rebuilt)
    _publish_bytes(rebuilt_boundary_path, rebuilt)
    oracle_raw = _zip_member(oracle_zip, ORACLE_ZIP_SHA256, ORACLE_MEMBER, ORACLE_SHA256)
    oracle = decode(oracle_raw, MAX_CAPSULE_BYTES)
    candidate = _candidate_envelope(oracle, rebuilt, state, pending, np, expm)
    candidate_sha = publish_atomic(output_path, candidate)
    candidate_raw = Path(output_path).read_bytes()
    candidate = decode(candidate_raw, MAX_CAPSULE_BYTES)
    oracle_rows = coordinate_rows(oracle)
    candidate_rows = coordinate_rows(candidate)
    if [(a, b) for a, b, _ in oracle_rows] != [(a, b) for a, b, _ in candidate_rows]:
        raise ValueError("candidate/oracle coordinate identity")
    mismatch = 0
    maximum = 0.0
    maximum_ulp = 0
    for (_, _, left), (_, _, right) in zip(oracle_rows, candidate_rows):
        if left != right:
            mismatch += 1
        a, b = struct.unpack("<d", left)[0], struct.unpack("<d", right)[0]
        if not math.isfinite(a) or not math.isfinite(b):
            raise ValueError("non-finite comparison coordinate")
        maximum = max(maximum, abs(a - b))
        maximum_ulp = max(maximum_ulp, abs(_ordered_int(left) - _ordered_int(right)))
    return {
        "schema": "hcsn-n256-dense-compatible-firststep-result-v1",
        "candidate_capsule_sha256": candidate_sha,
        "coordinate_comparisons": len(oracle_rows),
        "bitwise_mismatch_coordinates": mismatch,
        "max_abs_error_hex": maximum.hex(),
        "max_ulp_distance": maximum_ulp,
        "candidate_oracle_bitwise_equal": mismatch == 0,
        "candidate_boundary_builds": 1,
        "boundary_exact_comparisons": 68105,
        "candidate_dynamic_steps": 1,
        "candidate_dense_expm_actions": 2,
        "candidate_sparse_expm_actions": 0,
        "oracle_reexecutions": 0,
        "torch_calls": 0,
        "optimizer_steps": 0,
        "qualification": False,
        "all_closed": False,
    }
