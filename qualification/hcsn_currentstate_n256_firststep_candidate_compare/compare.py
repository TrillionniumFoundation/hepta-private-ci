"""Execute the frozen sparse warm-1 candidate against an archived dense oracle."""

import hashlib
import json
import math
import struct
import zipfile
from pathlib import Path


CHANNELS = 5
INTERIOR = 255
MAX_CAPSULE_BYTES = 8 * 1024 * 1024
ORACLE_MEMBER = "N256_WARM1.bin"
ORACLE_SHA256 = "b2a6e204e613fead7c0735b12a335a88d2394c8f4da99cab798133443c55dc18"
ORACLE_ZIP_SHA256 = "3ba4ef88608cbfc04d83fd82c1f05d7b439edf4f9338365625e79b0d52f02400"
INPUT_BUNDLE_SHA256 = "17086fb6ba83211e8626c7ac9c22183f6c9c9a7dc615772b5a32d2c14ecb8e95"
METADATA = "qualification/hcsn_n256_new_export/evidence/attempt001/METADATA.json"
PHASE = "qualification/hcsn_n256_new_export/evidence/attempt001/N256_PHASE.json"


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _tensor(np, values):
    from qualification.hcsn_currentstate_n256_firststep_serializer_v2.serializer import Tensor

    array = np.asarray(values, dtype="<f8", order="C")
    return Tensor("<f8", tuple(array.shape), array.tobytes(order="C"))


def _dense_operator(np, operator):
    matrix = np.zeros((operator.dimension, operator.dimension), dtype="float64")
    for row in range(operator.dimension):
        for offset in range(operator.indptr[row], operator.indptr[row + 1]):
            matrix[row, operator.indices[offset]] = operator.data[offset]
    return matrix


def _candidate_envelope(root, oracle):
    import numpy as np

    from qualification.hcsn_currentstate_n256_engineering import candidate as primitive
    from qualification.hcsn_currentstate_n256_independent_oracle_v2_intent.adapter import (
        load_authentic_input,
    )
    from qualification.hcsn_currentstate_n256_sparse_dynamic_v2_intent import (
        sparse_dynamic as candidate,
    )
    from qualification.hcsn_currentstate_n256_firststep_serializer_v2.serializer import (
        Block,
        Envelope,
        Packet,
        coordinate_counts,
    )

    root = Path(root)
    authentic = load_authentic_input(root)
    metadata = json.loads((root / METADATA).read_text())
    phase = json.loads((root / PHASE).read_text())
    arrays = {
        "active.npy": ((257,), np.frombuffer(authentic.active_payload, dtype="<f8")),
        "content.npy": ((257, 4), np.frombuffer(authentic.signed_content_payload, dtype="<f8").reshape(257, 4)),
        "nodes.npy": ((257,), np.frombuffer(authentic.nodes_payload, dtype="<f8")),
    }
    spatial, lower, upper, reset = primitive.spatial_operator(metadata, arrays["nodes.npy"][1])
    state, pending = candidate._initial_state(
        metadata, phase, arrays, primitive, INPUT_BUNDLE_SHA256, np
    )
    counts = candidate.Counts(scipy_imports=1)
    capsules, _, _ = candidate._run_lane(
        "warm", candidate.WARM[:2], state, pending, candidate.F(0), primitive,
        spatial, lower, upper, reset, INPUT_BUNDLE_SHA256,
        candidate._numeric_modules(), counts,
    )
    if len(capsules) != 2 or capsules[1].time != candidate.F(1, 1000):
        raise ValueError("candidate warm-1 capsule schedule")
    capsule = capsules[1]
    values = np.asarray(capsule.state, dtype="float64")
    cuts = (2550, 2565, 2575, 2585, 2600)
    active, upper, mass, discounted, occupation = np.split(values, cuts[:-1])
    blocks = tuple(
        Block(name, _tensor(np, raw))
        for name, raw in sorted((
            ("active", active.reshape(CHANNELS, 2, INTERIOR)),
            ("upper", upper.reshape(CHANNELS, 3)),
            ("mass", mass.reshape(CHANNELS, 2)),
            ("discounted_hit", discounted.reshape(CHANNELS, 2)),
            ("occupation", occupation.reshape(CHANNELS, 3)),
        ))
    )
    packets = tuple(sorted((
        Packet(
            identity=item.source, generation=item.generation,
            origin=item.origin, target=item.target,
            start=str(item.start), end=str(item.end),
            alpha=_tensor(np, np.asarray(item.alpha).reshape(CHANNELS, item.dimension)),
            generator=_tensor(np, _dense_operator(np, item.operator)),
            output=_tensor(np, item.output),
        )
        for item in capsule.packets
    ), key=lambda item: item.identity))
    envelope = Envelope(dict(oracle.metadata), blocks, packets)
    if coordinate_counts(envelope) != {
        "state": 2600, "packet_alpha": 1320, "packet_generator": 65544,
        "packet_output": 264, "packet": 67128, "total": 69728,
    }:
        raise ValueError("candidate coordinate denominator")
    if counts.segments != 1 or counts.expm_actions != 2:
        raise ValueError("candidate numerical action counts")
    return envelope, counts


def _ordered_int(raw):
    bits = int.from_bytes(raw, "little")
    return (0xFFFFFFFFFFFFFFFF - bits) if bits >> 63 else (bits + 0x8000000000000000)


def execute(root, oracle_zip, candidate_path):
    from qualification.hcsn_currentstate_n256_firststep_serializer_v2.serializer import (
        coordinate_rows,
        decode,
        publish_atomic,
    )

    if _sha(oracle_zip) != ORACLE_ZIP_SHA256:
        raise ValueError("archived oracle ZIP identity")
    with zipfile.ZipFile(oracle_zip) as archive:
        if ORACLE_MEMBER not in archive.namelist():
            raise ValueError("archived oracle member")
        oracle_raw = archive.read(ORACLE_MEMBER)
    if hashlib.sha256(oracle_raw).hexdigest() != ORACLE_SHA256:
        raise ValueError("archived oracle capsule identity")
    oracle = decode(oracle_raw, MAX_CAPSULE_BYTES)
    candidate, counts = _candidate_envelope(root, oracle)
    candidate_sha = publish_atomic(candidate_path, candidate)
    candidate_raw = Path(candidate_path).read_bytes()
    candidate = decode(candidate_raw, MAX_CAPSULE_BYTES)
    oracle_rows, candidate_rows = coordinate_rows(oracle), coordinate_rows(candidate)
    if [(a, b) for a, b, _ in oracle_rows] != [(a, b) for a, b, _ in candidate_rows]:
        raise ValueError("candidate/oracle coordinate identity")
    mismatch = 0
    maximum = total = 0.0
    maximum_ulp = 0
    for (_, _, left), (_, _, right) in zip(oracle_rows, candidate_rows):
        if left != right:
            mismatch += 1
        a, b = struct.unpack("<d", left)[0], struct.unpack("<d", right)[0]
        if not math.isfinite(a) or not math.isfinite(b):
            raise ValueError("non-finite comparison coordinate")
        error = abs(a - b)
        maximum = max(maximum, error)
        total += error
        maximum_ulp = max(maximum_ulp, abs(_ordered_int(left) - _ordered_int(right)))
    return {
        "schema": "hcsn-n256-warm1-candidate-oracle-comparison-v1",
        "oracle_zip_sha256": ORACLE_ZIP_SHA256,
        "oracle_capsule_sha256": ORACLE_SHA256,
        "candidate_capsule_sha256": candidate_sha,
        "capsule_bytes": len(candidate_raw),
        "coordinate_comparisons": len(oracle_rows),
        "coordinate_identity_equal": True,
        "bitwise_mismatch_coordinates": mismatch,
        "max_abs_error_hex": maximum.hex(),
        "sum_abs_error_hex": total.hex(),
        "max_ulp_distance": maximum_ulp,
        "candidate_oracle_bitwise_equal": mismatch == 0,
        "candidate_dynamic_steps": counts.segments,
        "candidate_sparse_exponential_actions": counts.expm_actions,
        "oracle_reexecutions": 0,
        "oracle_dense_exponentials": 0,
        "canonical_decode_calls": 2,
        "canonical_encode_calls": 1,
        "torch_calls": 0,
        "optimizer_steps": 0,
        "qualification": False,
    }
