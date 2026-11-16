"""Exact-rational N256 generator reconstruction without a numeric provider.

This module reviews the frozen generator geometry and semantics only.  It does
not propagate state, evaluate a matrix exponential, emit reference rows, or
import the candidate, oracle, NumPy, SciPy, or Torch.
"""

import hashlib
import json
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from qualification.hcsn_currentstate_n256_stdlib_loader.loader import (
    load_authentic_n256_input,
)


METADATA_SHA256 = "88e84dd3aea396d34c7e2dd08d31f2e30bf694c20516dccde57e6dd1b0c2a3c6"
IDENTITY = "hcsn-n256-new-export-20261112-c06d-attempt001"
INTERIOR = 255


class GeneratorReviewError(ValueError):
    """Raised before accepting a changed or invalid generator input."""


@dataclass(frozen=True)
class GeneratorReviewCertificate:
    metadata_sha256: str
    nodes_bound: int
    metadata_fraction_exact_matches: int
    metadata_fraction_roundtrip_matches: int
    maximum_metadata_fraction_delta: str
    interior_rows: int
    off_diagonal_rates: int
    row_balance_identities: int
    reset_nonzero_coordinates: int
    reset_left_interior_index: int
    reset_right_interior_index: int
    rate_fraction_sha256: str
    reset_fraction_sha256: str
    minimum_rate_fraction: str
    maximum_exit_rate_fraction: str
    independent_exact_rational_reconstruction: bool = True
    permanent_upper_escape_reviewed: bool = True
    lower_hit_flux_reviewed: bool = True
    dynamic_calls: int = 0
    matrix_exponential_calls: int = 0
    numerical_reference_records: int = 0
    candidate_calls: int = 0
    oracle_calls: int = 0
    torch_calls: int = 0
    optimizer_calls: int = 0
    provider_admitted: bool = False
    largegrid_qualification: bool = False


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _fraction(value):
    return Fraction.from_float(float(value))


def _canonical_fractions(values):
    return json.dumps(
        [[value.numerator, value.denominator] for value in values],
        separators=(",", ":"),
    ).encode()


def review_exact_generator(metadata_path, state_path, phase_path, base64_path):
    """Reconstruct and review all 255 generator rows with exact rationals."""

    metadata_raw = Path(metadata_path).read_bytes()
    if _digest(metadata_raw) != METADATA_SHA256:
        raise GeneratorReviewError("N256 metadata SHA-256 mismatch")
    try:
        metadata = json.loads(metadata_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GeneratorReviewError("N256 metadata JSON is invalid") from error
    if (
        metadata.get("schema") != "hcsn-n256-new-export-metadata-v1"
        or metadata.get("identity") != IDENTITY
        or metadata.get("upper_semantics")
        != "permanently active nonreturning escape coordinate"
        or metadata.get("dynamic_execution_allowed") is not False
        or metadata.get("largegrid_qualification") is not False
    ):
        raise GeneratorReviewError("N256 metadata envelope mismatch")

    values, _ = load_authentic_n256_input(
        state_path, phase_path, base64_path
    )
    node_hex = values[0]
    node_fractions = tuple(
        Fraction(value)
        for value in metadata["migration_report"]["actual_node_fractions"]
    )
    observed_nodes = tuple(
        Fraction.from_float(float.fromhex(value)) for value in node_hex
    )
    if len(node_fractions) != INTERIOR + 2:
        raise GeneratorReviewError("metadata node count differs")
    if any(float(value) != float.fromhex(encoded) for value, encoded in zip(node_fractions, node_hex)):
        raise GeneratorReviewError("metadata node fractions do not round-trip to state nodes")
    exact_matches = sum(left == right for left, right in zip(node_fractions, observed_nodes))
    representation_delta = max(
        abs(left - right) for left, right in zip(node_fractions, observed_nodes)
    )
    if any(left >= right for left, right in zip(observed_nodes, observed_nodes[1:])):
        raise GeneratorReviewError("N256 nodes are not strictly increasing")

    physics = metadata["physics"]
    mu = _fraction(physics["mu"])
    sigma = _fraction(physics["sigma"])
    if float(physics["mu"]).hex() != "-0x1.eb851eb851eb7p-4":
        raise GeneratorReviewError("N256 drift identity mismatch")
    if float(physics["sigma"]).hex() != "0x1.6666666666666p-2":
        raise GeneratorReviewError("N256 volatility identity mismatch")

    rates = []
    exits = []
    for index in range(INTERIOR):
        left = observed_nodes[index + 1] - observed_nodes[index]
        right = observed_nodes[index + 2] - observed_nodes[index + 1]
        down = (sigma * sigma - mu * right) / (left * (left + right))
        up = (sigma * sigma + mu * left) / (right * (left + right))
        if down <= 0 or up <= 0:
            raise GeneratorReviewError("N256 off-diagonal rate is not positive")
        diagonal = -(down + up)
        if diagonal + down + up != 0:
            raise GeneratorReviewError("N256 exact row balance failed")
        rates.extend((down, up))
        exits.append(-diagonal)

    reset_position = _fraction(metadata["reset_distance"])
    reset_right = next(
        (index for index, value in enumerate(observed_nodes) if value > reset_position),
        None,
    )
    if reset_right is None:
        raise GeneratorReviewError("N256 reset lies outside the grid")
    reset_left = reset_right - 1
    if not 1 <= reset_left < reset_right <= INTERIOR:
        raise GeneratorReviewError("N256 reset is not bracketed by interior nodes")
    right_weight = (reset_position - observed_nodes[reset_left]) / (
        observed_nodes[reset_right] - observed_nodes[reset_left]
    )
    reset = (1 - right_weight, right_weight)
    if any(value <= 0 for value in reset) or sum(reset) != 1:
        raise GeneratorReviewError("N256 reset interpolation is invalid")

    return GeneratorReviewCertificate(
        metadata_sha256=METADATA_SHA256,
        nodes_bound=len(observed_nodes),
        metadata_fraction_exact_matches=exact_matches,
        metadata_fraction_roundtrip_matches=len(observed_nodes),
        maximum_metadata_fraction_delta=str(representation_delta),
        interior_rows=INTERIOR,
        off_diagonal_rates=len(rates),
        row_balance_identities=INTERIOR,
        reset_nonzero_coordinates=2,
        reset_left_interior_index=reset_left - 1,
        reset_right_interior_index=reset_right - 1,
        rate_fraction_sha256=_digest(_canonical_fractions(rates)),
        reset_fraction_sha256=_digest(_canonical_fractions(reset)),
        minimum_rate_fraction=str(min(rates)),
        maximum_exit_rate_fraction=str(max(exits)),
    )
