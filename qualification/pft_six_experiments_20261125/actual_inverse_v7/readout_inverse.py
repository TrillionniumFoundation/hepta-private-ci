"""Exact two-coordinate readout proposals from an externally pinned request.

This module never loads a model or executes its dynamics. A trusted caller
must obtain expected_sha256 from the reviewed request, separately from the
request bytes. Hash equality binds data; it does not establish user consent.
"""

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import math
import re


MODEL_SHA256 = "aabc7a29ebfdaed592ebd4a16d7e4db927a6a88cb7247d4b334fd7299eab8576"
SCHEMA = "hepta.frozen-readout.inverse-request.v1"
COORDINATES = [
    {"name": "readout.weight", "flat_index": 0, "shape": [2, 20]},
    {"name": "readout.bias", "flat_index": 0, "shape": [2]},
]
IDENTITY_FIELDS = {
    "model_source_sha256", "source_binding_sha256", "reference_candidate_sha256",
    "reference_state_sha256", "coordinate_layout_sha256", "input_sha256",
    "initial_margin_sha256", "source_linearization_sha256", "common_file_sha256",
}


def _keys(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(f"unexpected fields in {label}")


def _digest(value):
    if not isinstance(value, str) or re.fullmatch("[0-9a-f]{64}", value) is None:
        raise ValueError("invalid SHA256")
    return value


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError(f"nonfinite JSON constant: {value}")


def _binary64(value):
    if not isinstance(value, str):
        raise ValueError("canonical binary64 hex string required")
    try:
        number = float.fromhex(value)
    except (ValueError, OverflowError) as error:
        raise ValueError("invalid binary64 value") from error
    if not math.isfinite(number) or number.hex() != value:
        raise ValueError("finite canonical binary64 value required")
    return Fraction.from_float(number)


@dataclass(frozen=True)
class Row:
    identity: str
    feature: Fraction
    residual: Fraction
    weight: Fraction


@dataclass(frozen=True)
class Statistics:
    binding_sha256: str
    row_id: str
    gram: tuple
    rhs: tuple
    constant: Fraction


def read_request(raw, expected_sha256):
    """Validate the independently pinned request and its fixed coordinate scope."""
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= 32768:
        raise ValueError("bounded request bytes required")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != _digest(expected_sha256):
        raise ValueError("request digest mismatch")
    request = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_nonfinite)
    _keys(request, {"schema", "observation", "freeze_rule", "coordinates", "binding", "rows"}, "request")
    if request["schema"] != SCHEMA:
        raise ValueError("unsupported request schema")
    if request["observation"] != "final_logit_1_minus_logit_0":
        raise ValueError("unsupported observation")
    if request["freeze_rule"] != "all_parameters_buffers_config_inputs_and_initial_state_except_two_listed_coordinates":
        raise ValueError("body and task must be frozen")
    if json.dumps(request["coordinates"], sort_keys=True) != json.dumps(COORDINATES, sort_keys=True):
        raise ValueError("unsupported coordinate layout")
    _keys(request["binding"], IDENTITY_FIELDS, "binding")
    for value in request["binding"].values():
        _digest(value)
    if request["binding"]["model_source_sha256"] != MODEL_SHA256:
        raise ValueError("wrong physical model source")
    if not isinstance(request["rows"], list) or len(request["rows"]) != 2:
        raise ValueError("exactly two frozen observations required")
    rows = []
    for record in request["rows"]:
        _keys(record, {"row_id", "source_row_sha256", "feature0_hex", "base_margin_hex", "target_margin_hex", "weight_hex"}, "row")
        if not isinstance(record["row_id"], str) or re.fullmatch("[a-z0-9_-]{1,64}", record["row_id"]) is None:
            raise ValueError("invalid row identity")
        _digest(record["source_row_sha256"])
        feature = _binary64(record["feature0_hex"])
        residual = _binary64(record["target_margin_hex"]) - _binary64(record["base_margin_hex"])
        weight = _binary64(record["weight_hex"])
        if weight <= 0:
            raise ValueError("strictly positive observation weight required")
        rows.append(Row(record["row_id"], feature, residual, weight))
    if rows[0].identity == rows[1].identity:
        raise ValueError("duplicate observation identity")
    if request["rows"][0]["source_row_sha256"] == request["rows"][1]["source_row_sha256"]:
        raise ValueError("duplicate source observation")
    if rows[0].feature == rows[1].feature:
        raise ValueError("two observations do not identify both readout coordinates")
    return request, tuple(rows), digest


def local_statistics(row, binding_sha256):
    """One node's exact unregularized quadratic for [-feature, -1]."""
    if row.weight <= 0:
        raise ValueError("positive weight required")
    _digest(binding_sha256)
    feature, residual, weight = row.feature, row.residual, row.weight
    return Statistics(binding_sha256, row.identity,
                      (weight * feature * feature, weight * feature, weight),
                      (-weight * feature * residual, -weight * residual),
                      weight * residual * residual)


def merge_statistics(parts, binding_sha256, expected_rows):
    """Combine exactly the registered two contributions without a coordinator solve.

    Caller-authenticated contributions are required. This is equation agreement,
    not a signature, privacy, liveness or Byzantine validation protocol.
    """
    if len(parts) != 2 or len(expected_rows) != 2 or len(set(expected_rows)) != 2:
        raise ValueError("exactly two registered rows required")
    _digest(binding_sha256)
    if {part.row_id for part in parts} != set(expected_rows):
        raise ValueError("missing, duplicate or unregistered contribution")
    if any(part.binding_sha256 != binding_sha256 for part in parts):
        raise ValueError("incompatible frozen problem")
    if any(len(part.gram) != 3 or len(part.rhs) != 2 for part in parts):
        raise ValueError("invalid sufficient-statistic shape")
    if any(type(value) is not Fraction for part in parts
           for value in (*part.gram, *part.rhs, part.constant)):
        raise ValueError("exact Fraction statistics required")
    gram = tuple(sum((part.gram[k] for part in parts), Fraction()) for k in range(3))
    rhs = tuple(sum((part.rhs[k] for part in parts), Fraction()) for k in range(2))
    return gram, rhs, sum((part.constant for part in parts), Fraction())


def _ratio(value):
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def propose_readout_edit(raw, expected_sha256):
    """Return an inspectable edit; never install/export/adopt a model candidate."""
    request, rows, digest = read_request(raw, expected_sha256)
    parts = tuple(local_statistics(row, digest) for row in rows)
    gram, rhs, constant = merge_statistics(parts, digest, tuple(row.identity for row in rows))
    g00, g01, g11 = gram
    h0, h1 = rhs
    determinant = g00 * g11 - g01 * g01
    if g00 <= 0 or determinant <= 0:
        raise ValueError("readout normal matrix is not positive definite")
    delta = ((g11 * h0 - g01 * h1) / determinant,
             (g00 * h1 - g01 * h0) / determinant)
    exact_residual = tuple(-row.feature * delta[0] - delta[1] - row.residual for row in rows)
    if any(exact_residual):
        raise ArithmeticError("exact readout equations were not solved")
    try:
        rounded = tuple(float(value) for value in delta)
    except OverflowError as error:
        raise ValueError("proposal is outside finite binary64 range") from error
    if not all(map(math.isfinite, rounded)):
        raise ValueError("proposal is outside finite binary64 range")
    rounded_exact = tuple(Fraction.from_float(value) for value in rounded)
    projected_residual = tuple(-row.feature * rounded_exact[0] - rounded_exact[1] - row.residual for row in rows)
    gap = abs(rows[0].feature - rows[1].feature)
    inverse_norm = max(Fraction(2), abs(rows[0].feature) + abs(rows[1].feature)) / gap
    return {
        "schema": "hepta.frozen-readout.inverse-proposal.v1",
        "status": "EXACT_AFFINE_PROPOSAL_ONLY",
        "request_sha256": digest,
        "binding": request["binding"],
        "coordinates": request["coordinates"],
        "freeze_rule": request["freeze_rule"],
        "delta_exact": [_ratio(value) for value in delta],
        "delta_binary64_hex": [value.hex() for value in rounded],
        "normal_matrix": [_ratio(value) for value in gram],
        "normal_rhs": [_ratio(value) for value in rhs],
        "normal_constant": _ratio(constant),
        "normal_determinant": _ratio(determinant),
        "inverse_linf_norm": _ratio(inverse_norm),
        "exact_max_abs_residual": _ratio(max(map(abs, exact_residual))),
        "binary64_delta_projection_max_abs_residual": _ratio(max(map(abs, projected_residual))),
        "projection_scope": "rounding_delta_only_with_frozen_exact_binary64_features; excludes parameter-addition and physical-forward roundoff",
        "regularization": "none",
        "candidate_exported": False,
        "model_executed": False,
        "production_adoption": False,
    }
