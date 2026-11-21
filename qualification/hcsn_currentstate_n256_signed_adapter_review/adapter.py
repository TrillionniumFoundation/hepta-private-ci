"""Adapt immutable dense N256 bytes to the signed interval input schema.

This module performs parsing, validation, and byte-exact round trips only.  It
does not call a propagation provider or evaluate a matrix exponential.
"""

import hashlib
import json
import math
import struct
import zipfile
from pathlib import Path

from qualification.hcsn_currentstate_n256_fp64_input_conversion.fp64_exact import (
    Fp64InputError,
    fp64_hex_to_exact_decimal,
)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EVIDENCE = ROOT / "qualification/hcsn_currentstate_n256_preexpm_snapshot_evidence"
ARTIFACTS = (
    EVIDENCE / "run44916753930-artifact14711463209.zip",
    EVIDENCE / "run44916786884-artifact14711278907.zip",
)
ARTIFACT_SHA256 = (
    "918e9c0f0a1e27ebe0ad4159ce8314771b7d08e78f6e484473ff18506b906c22",
    "56da770158265e85a81beeb32c9c53a188ffd3b35130cf6ff30e880996a567de",
)
PREFIX = "hcsn-n256-preexpm-snapshot-output/"


class SignedAdapterError(ValueError):
    """Raised when an immutable input cannot enter the signed schema."""


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _artifact(path, expected_sha):
    raw = path.read_bytes()
    if _sha256(raw) != expected_sha:
        raise SignedAdapterError("artifact identity")
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise SignedAdapterError("artifact CRC")
        return {
            name[len(PREFIX) :]: archive.read(name)
            for name in archive.namelist()
            if name.startswith(PREFIX) and not name.endswith("/")
        }


def _unpack(raw, coordinates, label):
    if len(raw) != 8 * coordinates:
        raise SignedAdapterError(f"{label} dimensions")
    values = struct.unpack(f"<{coordinates}d", raw)
    if not all(math.isfinite(value) for value in values):
        raise SignedAdapterError(f"{label} non-finite value")
    return values


def _canonical_hex(value):
    return struct.pack(">d", value).hex()


def _from_canonical_hex(value_hex):
    try:
        fp64_hex_to_exact_decimal(value_hex)
    except Fp64InputError as error:
        raise SignedAdapterError("target parser compatibility") from error
    return struct.unpack(">d", bytes.fromhex(value_hex))[0]


def adapt_lane(matrix_raw, seed_raw, dimension):
    """Return byte-reversible signed-provider rows and five seed vectors."""

    matrix = _unpack(matrix_raw, dimension * dimension, "matrix")
    seed = _unpack(seed_raw, 5 * dimension, "seed")
    rows = []
    diagonal_positive = 0
    off_diagonal_negative = 0
    for row_index in range(dimension):
        sparse = []
        for column in range(dimension):
            value = matrix[row_index * dimension + column]
            if column == row_index:
                diagonal_positive += value > 0.0
            else:
                off_diagonal_negative += value < 0.0
            if value != 0.0 or math.copysign(1.0, value) < 0.0:
                sparse.append((column, _canonical_hex(value)))
        rows.append(tuple(sparse))
    if diagonal_positive or off_diagonal_negative:
        raise SignedAdapterError("matrix is not Metzler")

    vectors = tuple(
        tuple(
            _canonical_hex(value)
            for value in seed[index * dimension : (index + 1) * dimension]
        )
        for index in range(5)
    )
    rebuilt_matrix = [0.0] * (dimension * dimension)
    for row_index, row in enumerate(rows):
        prior = -1
        for column, value_hex in row:
            if column <= prior:
                raise SignedAdapterError("sparse columns are not ordered")
            prior = column
            rebuilt_matrix[row_index * dimension + column] = _from_canonical_hex(
                value_hex
            )
    rebuilt_matrix_raw = struct.pack(
        f"<{dimension * dimension}d", *rebuilt_matrix
    )
    rebuilt_seed_raw = struct.pack(
        f"<{5 * dimension}d",
        *(
            _from_canonical_hex(value_hex)
            for vector in vectors
            for value_hex in vector
        ),
    )
    if rebuilt_matrix_raw != matrix_raw:
        raise SignedAdapterError("matrix round trip")
    if rebuilt_seed_raw != seed_raw:
        raise SignedAdapterError("seed round trip")

    canonical = json.dumps(
        {"rows_hex": rows, "vectors_hex": vectors},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return {
        "rows_hex": tuple(rows),
        "vectors_hex": vectors,
        "review": {
            "dimension": dimension,
            "matrix_coordinates": dimension * dimension,
            "matrix_sparse_coordinates": sum(len(row) for row in rows),
            "seed_channels": 5,
            "seed_coordinates": 5 * dimension,
            "signed_provider_input_coordinates": sum(len(row) for row in rows)
            + 5 * dimension,
            "diagonal_positive_coordinates": diagonal_positive,
            "off_diagonal_negative_coordinates": off_diagonal_negative,
            "matrix_round_trip_byte_equal": True,
            "seed_round_trip_byte_equal": True,
            "target_fp64_parser_compatible": True,
            "canonical_bit_hex_coordinates": sum(len(row) for row in rows)
            + 5 * dimension,
            "canonical_adapter_bytes": len(canonical),
            "canonical_adapter_sha256": _sha256(canonical),
        },
    }


def _compute_review():
    parent = json.loads(
        (
            ROOT
            / "qualification/hcsn_currentstate_n256_preexpm_provider_compat/REVIEW.json"
        ).read_text()
    )
    if parent["source_identity_status"] != "RED_DUPLICATE_KEY":
        raise SignedAdapterError("parent protocol status")
    left, right = (
        _artifact(path, digest)
        for path, digest in zip(ARTIFACTS, ARTIFACT_SHA256, strict=True)
    )
    lanes = {}
    for lane, dimension in (("undiscounted", 258), ("discounted", 259)):
        matrix_name = f"oracle-{lane}-augmented.bin"
        seed_name = f"oracle-{lane}-seed.bin"
        if (
            left[matrix_name] != right[matrix_name]
            or left[seed_name] != right[seed_name]
        ):
            raise SignedAdapterError("duplicate artifacts differ")
        adapted = adapt_lane(left[matrix_name], left[seed_name], dimension)
        lanes[lane] = adapted["review"]
    return {
        "schema": "hcsn-n256-authentic-signed-adapter-review-v2",
        "parent_head": "1f4143719aca1d7aeec99bda863301dfdd7dd2f3",
        "parent_status": "RED_DUPLICATE_KEY",
        "historical_parent_adapter": {
            "encoding": "python_float_hex",
            "target_fp64_parser_compatible": False,
            "status": "RED_NONCANONICAL_INPUT",
        },
        "lanes": lanes,
        "finding": {
            "authentic_dense_bytes_adapter_compatible": True,
            "sparse_rows_strictly_ordered": True,
            "five_seed_channels_complete": True,
            "matrix_and_seed_round_trip_byte_exact": True,
            "target_fp64_parser_compatible": True,
            "signed_interval_provider_directly_called": False,
        },
        "work": {
            "artifact_reads": 2,
            "authentic_adapter_lane_calls": 2,
            "matrix_coordinate_reads": 258 * 258 + 259 * 259,
            "seed_coordinate_reads": 5 * 258 + 5 * 259,
            "target_parser_input_checks": 767 + 5 * 258 + 1025 + 5 * 259,
            "provider_calls": 0,
            "dynamic_steps": 0,
            "exponential_actions": 0,
            "torch_calls": 0,
            "optimizer_steps": 0,
        },
        "scope": {
            "adapter_admitted": False,
            "authentic_signed_interval_executed": False,
            "tail_bound_closed": False,
            "unique_rounding_closed": False,
            "resource_gate_closed": False,
            "n256_qualified": False,
            "cause_of_6901_red": "UNKNOWN",
            "c2_full_replay_completed_fits": 0,
            "hpca_status": "NoUpdate",
            "production_adoption": False,
            "all_closed": False,
        },
    }


def review():
    """Verify and return the frozen authentic adapter review."""

    result = _compute_review()
    expected = json.loads((HERE / "REVIEW.json").read_text())
    if result != expected:
        raise SignedAdapterError("review record mismatch")
    return result


if __name__ == "__main__":
    print(json.dumps(review(), indent=2, sort_keys=True))
