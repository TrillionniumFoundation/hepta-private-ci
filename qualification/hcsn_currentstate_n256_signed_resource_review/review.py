"""Compute a zero-provider work ledger for the authentic signed inputs."""

import ast
import json
import math
import struct
from fractions import Fraction
from pathlib import Path

from qualification.hcsn_currentstate_n256_signed_adapter_review.adapter import (
    ARTIFACTS,
    ARTIFACT_SHA256,
    _artifact,
    adapt_lane,
)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROVIDER = (
    ROOT
    / "qualification"
    / "hcsn_currentstate_n256_non_substochastic_signed_interval"
    / "signed_interval.py"
)
COMPAT = (
    ROOT / "qualification/hcsn_currentstate_n256_preexpm_provider_compat/REVIEW.json"
)
MAX_TERMS = 1024


class ResourceReviewError(ValueError):
    """Raised when a frozen input or provider structure differs."""


def _fraction(value_hex):
    if (
        not isinstance(value_hex, str)
        or len(value_hex) != 16
        or any(character not in "0123456789abcdef" for character in value_hex)
    ):
        raise ResourceReviewError("noncanonical binary64 input")
    value = struct.unpack(">d", bytes.fromhex(value_hex))[0]
    if not math.isfinite(value):
        raise ResourceReviewError("non-finite binary64 input")
    return Fraction.from_float(value)


def _provider_contract():
    tree = ast.parse(PROVIDER.read_text())
    functions = {
        node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    public = functions["non_substochastic_signed_outputs_from_fp64_intervals"]
    if len(public.args.kw_defaults) != 1:
        raise ResourceReviewError("provider max_terms default")
    default = public.args.kw_defaults[0]
    if not isinstance(default, ast.Constant) or default.value != MAX_TERMS:
        raise ResourceReviewError("provider max_terms value")
    loops = [
        node
        for node in ast.walk(public)
        if isinstance(node, ast.For)
        and isinstance(node.iter, ast.Call)
        and isinstance(node.iter.func, ast.Name)
        and node.iter.func.id == "range"
    ]
    if len(loops) != 1:
        raise ResourceReviewError("provider loop structure")
    calls = [
        node
        for node in ast.walk(loops[0])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_row_action"
    ]
    if len(calls) != 1:
        raise ResourceReviewError("provider row-action structure")
    return {
        "api_shape": "one_operator_one_vector_one_duration",
        "default_max_terms": MAX_TERMS,
        "row_actions_per_loop_iteration": 1,
    }


def _lane_metrics(rows_hex, duration_hex, dimension, channels):
    operator = []
    diagonals = []
    off_diagonal_sums = []
    for row_index, row in enumerate(rows_hex):
        values = {}
        diagonal = Fraction(0)
        off_diagonal_sum = Fraction(0)
        for column, value_hex in row:
            value = _fraction(value_hex)
            if column == row_index:
                diagonal = value
            else:
                off_diagonal_sum += value
            if value:
                values[column] = value
        operator.append(values)
        diagonals.append(diagonal)
        off_diagonal_sums.append(off_diagonal_sum)
    rate = max(tuple(-value for value in diagonals) + tuple(off_diagonal_sums))
    transition_nonzero = 0
    row_sums = []
    for row_index, row in enumerate(operator):
        values = {column: value / rate for column, value in row.items()}
        values[row_index] = values.get(row_index, Fraction(0)) + 1
        if any(value < 0 for value in values.values()):
            raise ResourceReviewError("negative transition entry")
        transition_nonzero += sum(value != 0 for value in values.values())
        row_sums.append(sum(values.values(), Fraction(0)))
    transition_norm = max(row_sums)
    tail_argument = rate * _fraction(duration_hex) * transition_norm
    first_check = max(0, tail_argument.numerator // tail_argument.denominator - 1)
    if first_check != 537:
        raise ResourceReviewError("unexpected first tail check")

    scalar_calls = channels
    minimum_actions = scalar_calls * first_check
    maximum_actions = scalar_calls * MAX_TERMS
    possible_tail_checks = MAX_TERMS - first_check
    sparse_coordinates = sum(len(row) for row in rows_hex)
    return {
        "dimension": dimension,
        "seed_channels": channels,
        "scalar_provider_calls_required": scalar_calls,
        "operator_sparse_coordinates_per_call": sparse_coordinates,
        "operator_input_conversions": scalar_calls * sparse_coordinates,
        "vector_input_conversions": scalar_calls * dimension,
        "duration_input_conversions": scalar_calls,
        "transition_nonzero_coordinates": transition_nonzero,
        "first_possible_growth_tail_check_index": first_check,
        "minimum_row_actions_to_first_tail_check": minimum_actions,
        "maximum_row_actions_at_default_limit": maximum_actions,
        "minimum_sparse_product_contributions": minimum_actions
        * transition_nonzero,
        "maximum_sparse_product_contributions": maximum_actions
        * transition_nonzero,
        "maximum_tail_checks_at_default_limit": possible_tail_checks,
        "minimum_bound_roundings_at_first_check": scalar_calls * 2 * dimension,
        "maximum_bound_roundings_at_default_limit": scalar_calls
        * 2
        * dimension
        * possible_tail_checks,
    }


def _compute_review():
    contract = _provider_contract()
    compat = json.loads(COMPAT.read_text())
    if compat["source_identity_status"] != "RED_DUPLICATE_KEY":
        raise ResourceReviewError("parent protocol status")
    artifact = _artifact(ARTIFACTS[0], ARTIFACT_SHA256[0])
    lanes = {}
    for lane, dimension in (("undiscounted", 258), ("discounted", 259)):
        adapted = adapt_lane(
            artifact[f"oracle-{lane}-augmented.bin"],
            artifact[f"oracle-{lane}-seed.bin"],
            dimension,
        )
        duration = compat["lanes"][lane]["matrix"]["binary64_duration_hex"]
        duration_hex = struct.pack(">d", float.fromhex(duration)).hex()
        lanes[lane] = _lane_metrics(
            adapted["rows_hex"],
            duration_hex,
            dimension,
            len(adapted["vectors_hex"]),
        )
    total_keys = (
        "scalar_provider_calls_required",
        "operator_input_conversions",
        "vector_input_conversions",
        "duration_input_conversions",
        "minimum_row_actions_to_first_tail_check",
        "maximum_row_actions_at_default_limit",
        "minimum_sparse_product_contributions",
        "maximum_sparse_product_contributions",
        "minimum_bound_roundings_at_first_check",
        "maximum_bound_roundings_at_default_limit",
    )
    totals = {
        key: sum(lane[key] for lane in lanes.values()) for key in total_keys
    }
    totals["exact_input_conversions"] = (
        totals["operator_input_conversions"]
        + totals["vector_input_conversions"]
        + totals["duration_input_conversions"]
    )
    return {
        "schema": "hcsn-n256-authentic-signed-resource-review-v1",
        "parent_head": "ceea7e25893548820879a2e68c32be2244c2848d",
        "historical_statuses": {
            "duplicate_key": "RED_DUPLICATE_KEY",
            "parent_adapter": "RED_NONCANONICAL_INPUT",
            "cause_of_6901_red": "UNKNOWN",
        },
        "provider_contract": contract,
        "lanes": lanes,
        "totals": totals,
        "finding": {
            "scalar_api_reparses_operator_per_channel": True,
            "ten_provider_calls_required_without_batch_api": True,
            "host_peak_rss_bound_available": False,
            "host_wall_time_bound_available": False,
            "valid_host_allocation_available": False,
            "resource_gate_closed": False,
        },
        "work": {
            "artifact_reads": 1,
            "adapter_lane_calls": 2,
            "provider_source_ast_reads": 1,
            "provider_calls": 0,
            "dynamic_steps": 0,
            "exponential_actions": 0,
            "torch_calls": 0,
            "optimizer_steps": 0,
        },
        "scope": {
            "provider_execution_admitted": False,
            "authentic_signed_interval_executed": False,
            "unique_rounding_closed": False,
            "n256_qualified": False,
            "c2_full_replay_completed_fits": 0,
            "hpca_status": "NoUpdate",
            "production_adoption": False,
            "all_closed": False,
        },
    }


def review():
    """Verify and return the frozen zero-provider resource review."""

    result = _compute_review()
    expected = json.loads((HERE / "REVIEW.json").read_text())
    if result != expected:
        raise ResourceReviewError("review record mismatch")
    return result


if __name__ == "__main__":
    print(json.dumps(review(), indent=2, sort_keys=True))
