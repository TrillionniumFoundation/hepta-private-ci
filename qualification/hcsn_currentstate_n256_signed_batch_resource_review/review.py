"""Review shared-parse work on authentic N256 inputs without executing it."""

import ast
import json
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
BATCH_SOURCE = (
    ROOT
    / "qualification"
    / "hcsn_currentstate_n256_signed_batch_candidate"
    / "batch_candidate.py"
)
SCALAR_REVIEW = (
    ROOT / "qualification/hcsn_currentstate_n256_signed_resource_review/REVIEW.json"
)
COMPAT_REVIEW = (
    ROOT / "qualification/hcsn_currentstate_n256_preexpm_provider_compat/REVIEW.json"
)


class BatchResourceReviewError(ValueError):
    """Raised when a frozen input or candidate structure differs."""


def _batch_contract():
    tree = ast.parse(BATCH_SOURCE.read_text())
    assignments = {
        node.targets[0].id: node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    }
    cap = assignments.get("MAX_BATCH_VECTORS")
    if not isinstance(cap, ast.Constant) or cap.value != 16:
        raise BatchResourceReviewError("batch cap changed")
    functions = {
        node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    public = functions.get(
        "non_substochastic_signed_batch_outputs_from_fp64_intervals"
    )
    if public is None:
        raise BatchResourceReviewError("batch public function missing")

    calls = [node for node in ast.walk(public) if isinstance(node, ast.Call)]

    def named_call_count(name):
        return sum(
            isinstance(call.func, ast.Name) and call.func.id == name for call in calls
        )

    if named_call_count("_canonical_operator") != 1:
        raise BatchResourceReviewError("operator parse count changed")
    if named_call_count("_transition_rows") != 1:
        raise BatchResourceReviewError("transition construction count changed")
    if named_call_count("_outputs_from_parsed") != 1:
        raise BatchResourceReviewError("per-vector recurrence call changed")
    recurrence_loops = [
        node
        for node in ast.walk(public)
        if isinstance(node, ast.For)
        and any(
            isinstance(call.func, ast.Name)
            and call.func.id == "_outputs_from_parsed"
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
        )
    ]
    if len(recurrence_loops) != 1:
        raise BatchResourceReviewError("recurrence is not one bounded vector loop")
    if not (
        isinstance(recurrence_loops[0].iter, ast.Name)
        and recurrence_loops[0].iter.id == "parsed_vectors"
    ):
        raise BatchResourceReviewError("recurrence loop input changed")
    return {
        "hard_vector_cap": cap.value,
        "operator_parse_calls_per_lane": 1,
        "transition_build_calls_per_lane": 1,
        "recurrence_calls_per_vector": 1,
        "shared_recurrence_across_vectors": False,
    }


def _compute_review():
    contract = _batch_contract()
    scalar = json.loads(SCALAR_REVIEW.read_text())
    compat = json.loads(COMPAT_REVIEW.read_text())
    if compat["source_identity_status"] != "RED_DUPLICATE_KEY":
        raise BatchResourceReviewError("parent protocol status changed")
    artifact = _artifact(ARTIFACTS[0], ARTIFACT_SHA256[0])

    lanes = {}
    for lane, dimension in (("undiscounted", 258), ("discounted", 259)):
        adapted = adapt_lane(
            artifact[f"oracle-{lane}-augmented.bin"],
            artifact[f"oracle-{lane}-seed.bin"],
            dimension,
        )
        vectors = adapted["vectors_hex"]
        rows = adapted["rows_hex"]
        if len(vectors) != 5 or any(len(vector) != dimension for vector in vectors):
            raise BatchResourceReviewError("authentic vector shape changed")
        sparse_coordinates = sum(len(row) for row in rows)
        if sparse_coordinates != scalar["lanes"][lane][
            "operator_sparse_coordinates_per_call"
        ]:
            raise BatchResourceReviewError("authentic operator shape changed")
        vector_conversions = len(vectors) * dimension
        batch_conversions = sparse_coordinates + vector_conversions + 1
        lanes[lane] = {
            "dimension": dimension,
            "vector_count": len(vectors),
            "batch_calls_if_admitted": 1,
            "operator_parse_count_if_admitted": 1,
            "duration_parse_count_if_admitted": 1,
            "recurrence_channels_if_admitted": len(vectors),
            "operator_input_conversions_if_admitted": sparse_coordinates,
            "vector_input_conversions_if_admitted": vector_conversions,
            "duration_input_conversions_if_admitted": 1,
            "exact_input_conversions_if_admitted": batch_conversions,
        }

    batch_total = sum(
        lane["exact_input_conversions_if_admitted"] for lane in lanes.values()
    )
    scalar_total = scalar["totals"]["exact_input_conversions"]
    reduction = scalar_total - batch_total
    reduction_fraction = Fraction(reduction, scalar_total)
    recurrence_keys = (
        "minimum_row_actions_to_first_tail_check",
        "maximum_row_actions_at_default_limit",
        "minimum_sparse_product_contributions",
        "maximum_sparse_product_contributions",
        "minimum_bound_roundings_at_first_check",
        "maximum_bound_roundings_at_default_limit",
    )
    recurrence_work = {key: scalar["totals"][key] for key in recurrence_keys}
    return {
        "schema": "hcsn-n256-authentic-signed-batch-resource-review-v1",
        "parent_head": "ff429657381de751718b46b27a2187cdd88080f7",
        "historical_statuses": {
            "duplicate_key": "RED_DUPLICATE_KEY",
            "parent_adapter": "RED_NONCANONICAL_INPUT",
            "cause_of_6901_red": "UNKNOWN",
        },
        "batch_contract": contract,
        "lanes": lanes,
        "comparison": {
            "scalar_calls": scalar["totals"]["scalar_provider_calls_required"],
            "batch_calls_if_admitted": 2,
            "recurrence_channels_if_admitted": 10,
            "scalar_operator_parses": 10,
            "batch_operator_parses_if_admitted": 2,
            "scalar_duration_parses": 10,
            "batch_duration_parses_if_admitted": 2,
            "vector_input_conversions_both_designs": scalar["totals"][
                "vector_input_conversions"
            ],
            "scalar_exact_input_conversions": scalar_total,
            "batch_exact_input_conversions_if_admitted": batch_total,
            "exact_input_conversion_reduction": reduction,
            "reduction_fraction": (
                f"{reduction_fraction.numerator}/{reduction_fraction.denominator}"
            ),
            "reduction_percent_exact": (
                f"{(100 * reduction_fraction).numerator}/"
                f"{(100 * reduction_fraction).denominator}"
            ),
        },
        "recurrence_work_if_admitted": recurrence_work,
        "finding": {
            "shared_parse_reduces_exact_input_conversions": True,
            "recurrence_work_unchanged": True,
            "host_peak_rss_bound_available": False,
            "host_wall_time_bound_available": False,
            "valid_host_allocation_available": False,
            "authentic_execution_admitted": False,
            "resource_gate_closed": False,
        },
        "work": {
            "artifact_reads": 1,
            "adapter_lane_calls": 2,
            "batch_source_ast_reads": 1,
            "frozen_review_reads": 2,
            "authentic_batch_provider_calls": 0,
            "authentic_recurrence_calls": 0,
            "dynamic_steps": 0,
            "exponential_actions": 0,
            "torch_calls": 0,
            "optimizer_steps": 0,
        },
        "scope": {
            "authentic_signed_batch_executed": False,
            "authentic_provider_execution_admitted": False,
            "unique_rounding_closed": False,
            "n256_qualified": False,
            "largegrid_qualification": False,
            "c2_full_replay_completed_fits": 0,
            "hpca_status": "NoUpdate",
            "production_adoption": False,
            "all_closed": False,
        },
    }


def review():
    """Verify and return the frozen zero-provider batch resource review."""

    result = _compute_review()
    expected = json.loads((HERE / "REVIEW.json").read_text())
    if result != expected:
        raise BatchResourceReviewError("review record mismatch")
    return result


if __name__ == "__main__":
    print(json.dumps(review(), indent=2, sort_keys=True))
