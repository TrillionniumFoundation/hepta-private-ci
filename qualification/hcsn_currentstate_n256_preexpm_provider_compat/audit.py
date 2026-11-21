"""Inspect immutable N256 pre-exponential bytes without propagating them."""

import hashlib
import json
import math
import struct
import zipfile
from fractions import Fraction
from pathlib import Path


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
DURATION = Fraction.from_float(float(Fraction(1, 1000)))


class CompatibilityError(ValueError):
    """Raised when an immutable input or structural invariant differs."""


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _fraction(value):
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def _artifact(path, expected_sha):
    raw = path.read_bytes()
    if _sha256(raw) != expected_sha:
        raise CompatibilityError("artifact identity")
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise CompatibilityError("artifact CRC")
        return {
            name[len(PREFIX) :]: archive.read(name)
            for name in archive.namelist()
            if name.startswith(PREFIX) and not name.endswith("/")
        }


def _matrix_metrics(raw, dimension):
    if len(raw) != 8 * dimension * dimension:
        raise CompatibilityError("matrix dimensions")
    values = struct.unpack(f"<{dimension * dimension}d", raw)
    row_sums = []
    off_diagonal_sums = []
    diagonals = []
    nonzero = 0
    off_diagonal_negative = 0
    for row_index in range(dimension):
        row = values[row_index * dimension : (row_index + 1) * dimension]
        row_sum = Fraction(0)
        off_diagonal_sum = Fraction(0)
        for column, value in enumerate(row):
            if not math.isfinite(value):
                raise CompatibilityError("non-finite matrix value")
            exact = Fraction.from_float(value)
            row_sum += exact
            nonzero += value != 0.0
            if column == row_index:
                diagonals.append(exact)
            else:
                off_diagonal_sum += exact
                off_diagonal_negative += value < 0.0
        row_sums.append(row_sum)
        off_diagonal_sums.append(off_diagonal_sum)
    if any(value > 0 for value in diagonals):
        raise CompatibilityError("positive diagonal")
    rate = max(tuple(-value for value in diagonals) + tuple(off_diagonal_sums))
    transition_l1_norm = max(Fraction(1) + value / rate for value in row_sums)
    intensity = rate * DURATION
    tail_argument = intensity * transition_l1_norm
    first_tail_check_index = max(
        0, tail_argument.numerator // tail_argument.denominator - 1
    )
    return {
        "dimension": dimension,
        "coordinates": dimension * dimension,
        "nonzero_coordinates": nonzero,
        "off_diagonal_negative_coordinates": off_diagonal_negative,
        "positive_row_sums": sum(value > 0 for value in row_sums),
        "zero_row_sums": sum(value == 0 for value in row_sums),
        "negative_row_sums": sum(value < 0 for value in row_sums),
        "minimum_row_sum": _fraction(min(row_sums)),
        "maximum_row_sum": _fraction(max(row_sums)),
        "uniformization_rate": _fraction(rate),
        "transition_l1_norm": _fraction(transition_l1_norm),
        "binary64_duration": _fraction(DURATION),
        "binary64_duration_hex": float(DURATION).hex(),
        "poisson_intensity": _fraction(intensity),
        "growth_tail_argument": _fraction(tail_argument),
        "first_possible_growth_tail_check_index": first_tail_check_index,
    }


def _seed_metrics(raw, dimension):
    if len(raw) != 8 * 5 * dimension:
        raise CompatibilityError("seed dimensions")
    values = struct.unpack(f"<{5 * dimension}d", raw)
    rows = []
    for index in range(5):
        row = values[index * dimension : (index + 1) * dimension]
        if not all(math.isfinite(value) for value in row):
            raise CompatibilityError("non-finite seed value")
        rows.append(
            {
                "positive": sum(value > 0.0 for value in row),
                "negative": sum(value < 0.0 for value in row),
                "zero": sum(value == 0.0 for value in row),
            }
        )
    return {
        "dimension": dimension,
        "channels": 5,
        "coordinates": 5 * dimension,
        "rows": rows,
        "positive_coordinates": sum(row["positive"] for row in rows),
        "negative_coordinates": sum(row["negative"] for row in rows),
        "zero_coordinates": sum(row["zero"] for row in rows),
    }


def _compute_review():
    """Compute the exact structural routing result from the published bytes."""

    review = json.loads((EVIDENCE / "REVIEW.json").read_text())
    if review["protocol"]["status"] != "RED_DUPLICATE_KEY":
        raise CompatibilityError("duplicate-key history")
    if not review["raw_review"]["raw_binary_byte_equal_across_runs"]:
        raise CompatibilityError("cross-run byte equality")
    left, right = (
        _artifact(path, digest)
        for path, digest in zip(ARTIFACTS, ARTIFACT_SHA256, strict=True)
    )
    members = {}
    for lane, dimension in (("undiscounted", 258), ("discounted", 259)):
        matrix_name = f"oracle-{lane}-augmented.bin"
        seed_name = f"oracle-{lane}-seed.bin"
        if (
            left[matrix_name] != right[matrix_name]
            or left[seed_name] != right[seed_name]
        ):
            raise CompatibilityError("cross-run lane bytes")
        members[lane] = {
            "matrix_sha256": _sha256(left[matrix_name]),
            "seed_sha256": _sha256(left[seed_name]),
            "matrix": _matrix_metrics(left[matrix_name], dimension),
            "seed": _seed_metrics(left[seed_name], dimension),
        }
    result = {
        "schema": "hcsn-n256-preexpm-provider-compat-review-v1",
        "parent_evidence_head": "dcca46569da92ea9d4b44aa32d9a525c29aa0e47",
        "source_identity_status": "RED_DUPLICATE_KEY",
        "lanes": members,
        "finding": {
            "finite_metzler_augmented_matrices": True,
            "positive_row_sums_present": True,
            "uniformized_transition_l1_norm_above_one": True,
            "signed_seed_channels_present": True,
            "substochastic_sparse_subgenerator_direct_path_compatible": False,
            "signed_non_substochastic_interval_path_required": True,
        },
        "work": {
            "artifact_reads": 2,
            "matrix_coordinate_reads": 258 * 258 + 259 * 259,
            "seed_coordinate_reads": 5 * 258 + 5 * 259,
            "dynamic_steps": 0,
            "exponential_actions": 0,
            "provider_calls": 0,
            "torch_calls": 0,
            "optimizer_steps": 0,
        },
        "scope": {
            "authentic_signed_interval_executed": False,
            "authentic_unique_rounding_proved": False,
            "provider_admitted": False,
            "n256_qualified": False,
            "cause_of_6901_red": "UNKNOWN",
            "c2_full_replay_completed_fits": 0,
            "hpca_status": "NoUpdate",
            "production_adoption": False,
            "all_closed": False,
        },
    }
    return result


def audit():
    """Verify and return the frozen structural routing review."""

    result = _compute_review()
    expected = json.loads((HERE / "REVIEW.json").read_text())
    if result != expected:
        raise CompatibilityError("review record mismatch")
    return result


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2, sort_keys=True))
