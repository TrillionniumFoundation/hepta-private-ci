"""Actual #6823 candidate builder stopped before its first sparse action."""

import hashlib
import json
from fractions import Fraction as F
from pathlib import Path


EXECUTION_ALLOWED = False
CHANNELS = 5
INTERIOR = 255
INPUT_BUNDLE_SHA256 = "17086fb6ba83211e8626c7ac9c22183f6c9c9a7dc615772b5a32d2c14ecb8e95"
CONTAINER_BYTES = 545171
RELATIVE = {
    "metadata": "qualification/hcsn_n256_new_export/evidence/attempt001/METADATA.json",
    "state": "qualification/hcsn_n256_new_export/evidence/attempt001/N256_STATE.json",
    "phase": "qualification/hcsn_n256_new_export/evidence/attempt001/N256_PHASE.json",
    "npz_b64": "qualification/hcsn_n256_new_export/evidence/attempt001/N256_STATE.npz.b64",
}


def _phase_alpha(item):
    if set(item) != {"end", "identity", "mass", "signed_content", "start"}:
        raise ValueError("candidate phase packet fields")
    signed = item["signed_content"]
    if not isinstance(signed, list) or len(signed) != 4:
        raise ValueError("candidate signed-content channels")
    start, end = F(item["start"]), F(item["end"])
    width = end - start
    if width <= 0:
        raise ValueError("candidate phase width")
    return (float(F(item["mass"]) / width),) + tuple(
        float(F(value) / width) for value in signed
    )


def _payload(np, array, shape, name):
    if tuple(array.shape) != shape:
        raise ValueError(f"candidate shape: {name}")
    if array.dtype.str != "<f8" or not array.flags.c_contiguous:
        raise ValueError(f"candidate raw layout: {name}")
    if not np.isfinite(array).all():
        raise ValueError(f"candidate finite values: {name}")
    return array.tobytes(order="C")


def build_boundary(root):
    """Future admitted entry; this source-only stage never calls it."""
    import numpy as np
    from scipy import sparse

    from qualification.hcsn_currentstate_n256_boundary_container_contract.boundary_codec import (
        encode_boundary,
    )
    from qualification.hcsn_currentstate_n256_engineering import candidate as primitive

    root = Path(root)
    paths = {name: root / relative for name, relative in RELATIVE.items()}
    hashes, metadata, phase, arrays = primitive.load_inputs(
        paths["metadata"], paths["state"], paths["phase"], paths["npz_b64"]
    )
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
        if start != 0:
            continue
        source = primitive.source_identity(
            bundle, item["identity"], start, end, 1, 0, ()
        )
        releasing.append(
            (
                primitive.Template(source, 1, start, end, 1, 0, zero, (1.0,), ()),
                _phase_alpha(item),
            )
        )
    if len(releasing) != 1:
        raise ValueError("candidate warm releasing-parent denominator")
    template, phase_alpha = releasing[0]
    operator, _output = primitive.block_operator(
        (template,), spatial, lower, reset
    )
    core = sparse.csr_matrix(
        (operator.data, operator.indices, operator.indptr),
        shape=(operator.dimension, operator.dimension),
        dtype="<f8",
    )
    sink = sparse.csr_matrix(
        [(0.0,) * (operator.dimension - INTERIOR) + tuple(upper)], dtype="<f8"
    ).T
    matrix = sparse.bmat(
        ((core, sink), (None, sparse.csr_matrix((1, 1), dtype="<f8"))),
        format="csr",
    )
    if not matrix.has_canonical_format or not matrix.has_sorted_indices:
        raise ValueError("candidate canonical CSR")
    extended = matrix.toarray(order="C")
    active = np.asarray(arrays["active.npy"][1], dtype="<f8")
    content = np.asarray(arrays["content.npy"][1], dtype="<f8").reshape(257, 4)
    interior = np.column_stack((active[1:-1], content[1:-1])).T
    alpha = np.asarray(phase_alpha, dtype="<f8").reshape(5, 1)
    initial = np.concatenate((alpha, interior, np.zeros((5, 1), dtype="<f8")), axis=1)
    lower_selector = np.zeros((257, 1), dtype="<f8")
    lower_selector[1:256, 0] = lower
    discounted = np.zeros((257, 2), dtype="<f8")
    discounted[1:256, 0] = lower
    discounted[1:, 1] = 1.0
    sections = {
        "extended_generator": _payload(np, extended, (257, 257), "generator"),
        "initial": _payload(np, initial, (5, 257), "initial"),
        "lower_selector": _payload(np, lower_selector, (257, 1), "lower"),
        "discounted_selectors": _payload(np, discounted, (257, 2), "discounted"),
    }
    encoded = encode_boundary(sections)
    if len(encoded) != CONTAINER_BYTES:
        raise ValueError("candidate container length")
    return encoded
