"""Fixed six-coordinate, two-row rational surrogate; no model imports."""
from fractions import Fraction
import math
import struct
import sys

from profile_io import canonical, fields, require, sha

DIMENSION = 6
MAX_BITS = 2048
ROSTER = ["ai395", "pocket4"]
OBJECTIVE = "sum half weighted residual squares; binary64 ridge once globally"


def bounded(value):
    require(isinstance(value, Fraction) and max(value.numerator.bit_length(),
            value.denominator.bit_length()) <= MAX_BITS, "rational bit bound")
    return value


def binary(value):
    require(type(value) is float and math.isfinite(value), "finite binary64 input")
    require(sys.float_info.mant_dig == 53 and sys.float_info.max_exp == 1024
            and sys.float_info.rounds == 1 and struct.calcsize("d") == 8, "IEEE binary64 required")
    return bounded(Fraction.from_float(value))


def pack(value):
    value = bounded(value)
    return [str(value.numerator), str(value.denominator)]


def unpack(value):
    require(type(value) is list and len(value) == 2, "rational pair required")
    for item in value:
        require(type(item) is str and 0 < len(item) <= 618, "bounded integer text")
        require(item.lstrip("-").isdigit() and str(int(item)) == item, "canonical integer text")
    numerator, denominator = map(int, value)
    require(denominator > 0, "positive denominator")
    result = bounded(Fraction(numerator, denominator))
    require(pack(result) == value, "reduced rational required")
    return result


def total(values):
    result = Fraction(0)
    for value in values:
        result = bounded(result + bounded(value))
    return result


def eliminate(matrix, columns):
    """Fixed-size exact Gauss-Jordan; first nonzero pivot is deterministic."""
    matrix = [list(row) for row in matrix]
    require(len(matrix) == DIMENSION and all(len(row) in (DIMENSION, DIMENSION + 1)
            for row in matrix), "fixed elimination dimensions")
    rank = 0
    for column in range(columns):
        pivot = next((i for i in range(rank, DIMENSION) if matrix[i][column]), None)
        if pivot is None:
            continue
        matrix[rank], matrix[pivot] = matrix[pivot], matrix[rank]
        value = matrix[rank][column]
        matrix[rank] = [bounded(item / value) for item in matrix[rank]]
        for i in range(DIMENSION):
            if i != rank:
                factor = matrix[i][column]
                matrix[i] = [bounded(a - bounded(factor * b))
                             for a, b in zip(matrix[i], matrix[rank])]
        rank += 1
    return matrix, rank


def contribution(common, node, row, row_sha256):
    require(node in ROSTER and row_sha256 == common["row_sha256"][node], "own row pin")
    require(row["schema"] == "hepta.smallhcsn.retained-surrogate-row.v1", "retained row schema")
    require(row["source_linearization_sha256"] == common["source_linearization_sha256"], "row source")
    require(row["accepted_result_sha256"] == common["accepted_central_result_sha256"], "row provenance")
    require(row["batch"]["source_row"] == ROSTER.index(node), "assigned retained row")
    require(row["batch"]["original_failed_result_sha256"] == common["original_failed_result_sha256"], "failure retained")
    require(len(row["jacobian"]) == len(row["base_output"]) == 1
            and len(row["jacobian"][0]) == DIMENSION
            and len(row["batch"]["target"]) == len(row["batch"]["weights"]) == 1, "single row only")
    jacobian = [binary(value) for value in row["jacobian"][0]]
    residual = bounded(binary(row["batch"]["target"][0]) - binary(row["base_output"][0]))
    weight = binary(row["batch"]["weights"][0])
    require(weight == 1, "retained unit weight")
    gram = [[pack(bounded(weight * a * b)) for b in jacobian] for a in jacobian]
    moment = [pack(bounded(weight * a * residual)) for a in jacobian]
    return {"schema": "hepta.fixed-peer-rational-contribution.v1", "node": node,
            "common_sha256": sha(canonical(common)), "row_sha256": row_sha256,
            "observation_count": 1, "local_ridge_applied": False,
            "gram": gram, "moment": moment, "residual_square": pack(bounded(weight * residual * residual))}


def admit(common, item, expected_node):
    fields(item, ("schema", "node", "common_sha256", "row_sha256", "observation_count",
                  "local_ridge_applied", "gram", "moment", "residual_square"), "contribution")
    require(item["schema"] == "hepta.fixed-peer-rational-contribution.v1"
            and item["node"] == expected_node and expected_node in ROSTER, "roster assignment")
    require(item["common_sha256"] == sha(canonical(common))
            and item["row_sha256"] == common["row_sha256"][expected_node], "common/row binding")
    require(type(item["observation_count"]) is int and item["observation_count"] == 1
            and item["local_ridge_applied"] is False, "one observation; no local ridge")
    require(type(item["gram"]) is list and len(item["gram"]) == DIMENSION
            and all(type(row) is list and len(row) == DIMENSION for row in item["gram"])
            and type(item["moment"]) is list and len(item["moment"]) == DIMENSION, "statistics shape")
    gram = [[unpack(value) for value in row] for row in item["gram"]]
    moment = [unpack(value) for value in item["moment"]]
    square = unpack(item["residual_square"])
    joint = [gram[i] + [moment[i]] for i in range(DIMENSION)] + [moment + [square]]
    require(all(joint[i][j] == joint[j][i] for i in range(7) for j in range(7)), "joint symmetry")
    pivot = next((i for i in range(7) if joint[i][i] > 0), None)
    require(pivot is not None and all(joint[i][i] >= 0 for i in range(7)), "nonzero PSD row")
    require(all(bounded(joint[i][j] * joint[pivot][pivot]) == bounded(joint[i][pivot] * joint[pivot][j])
                for i in range(7) for j in range(7)), "exact rank-one PSD certificate")
    return gram, moment, square


def solve(common, contributions):
    require(common["roster"] == ROSTER and common["objective"] == OBJECTIVE, "fixed objective/roster")
    require(set(contributions) == set(ROSTER), "exact complete roster")
    parts = [admit(common, contributions[node], node) for node in ROSTER]
    gram = [[total(part[0][i][j] for part in parts) for j in range(DIMENSION)] for i in range(DIMENSION)]
    moment = [total(part[1][i] for part in parts) for i in range(DIMENSION)]
    square = total(part[2] for part in parts)
    ridge = binary(common["ridge_binary64"])
    require(ridge == Fraction.from_float(0.001), "fixed original binary64 ridge")
    _, rank = eliminate(gram, DIMENSION)
    require(rank == 2, "retained data rank must remain two")
    operator = [[bounded(gram[i][j] + (ridge if i == j else 0)) for j in range(DIMENSION)]
                for i in range(DIMENSION)]
    reduced, solved_rank = eliminate([operator[i] + [moment[i]] for i in range(DIMENSION)], DIMENSION)
    require(solved_rank == DIMENSION, "positive ridge system singular")
    delta = [row[-1] for row in reduced]
    require(all(total(bounded(a * b) for a, b in zip(row, delta)) == target
                for row, target in zip(operator, moment)), "exact normal equation residual")
    floats = [float(value) for value in delta]
    rounded = [binary(value) for value in floats]
    errors = [abs(bounded(value - quantized)) for value, quantized in zip(delta, rounded)]
    require(all(error <= Fraction.from_float(math.ulp(value)) / 2 for error, value in zip(errors, floats)),
            "at most half-ulp binary64 quantization")
    norm_squared = total(bounded(value * value) for value in rounded)
    require(norm_squared <= 1, "prespecified unit step bound; no clipping")
    rounded_residual = [bounded(total(bounded(a * b) for a, b in zip(row, rounded)) - target)
                        for row, target in zip(operator, moment)]
    require(max(map(abs, rounded_residual)) <= Fraction.from_float(1e-12), "rounded stationarity bound")
    hashes = {node: sha(canonical(contributions[node])) for node in ROSTER}
    linear_data = bounded((total(bounded(rounded[i] * gram[i][j] * rounded[j])
                           for i in range(DIMENSION) for j in range(DIMENSION))
                           - 2 * total(bounded(a * b) for a, b in zip(moment, rounded)) + square) / 2)
    regularized = bounded(linear_data + bounded(ridge * norm_squared / 2))
    predicted = bounded(square / 2 - regularized)
    require(predicted > 0, "positive surrogate prediction required")
    aggregate = {"gram": [[pack(value) for value in row] for row in gram],
                 "moment": [pack(value) for value in moment], "residual_square": pack(square)}
    return {"schema": "hepta.fixed-peer-rational-step.v1", "common_sha256": sha(canonical(common)),
            "round": common["round"], "contribution_sha256": hashes,
            "aggregate_sha256": sha(canonical(aggregate)),
            "parent_state_sha256": common["linearization"]["parent_state_sha256"],
            "coordinate_sha256": common["linearization"]["coordinate_sha256"],
            "delta_rational": [pack(value) for value in delta], "delta": floats,
            "delta_hex": [value.hex() for value in floats],
            "delta_sha256": sha(str(("<f8", (DIMENSION,))).encode() + struct.pack("<6d", *floats)),
            "quantization_absolute_error": [pack(value) for value in errors],
            "rounded_stationarity": [pack(value) for value in rounded_residual],
            "objective_at_zero_rational": pack(bounded(square / 2)),
            "predicted_reduction_at_rounded_step_rational": pack(predicted),
            "objective_at_zero": float(square / 2), "predicted_reduction": float(predicted),
            "data_rank": rank, "data_nullity": DIMENSION - rank, "solver_rank": solved_rank,
            "observation_count": 2, "global_ridge_applications": 1,
            "ridge_rational": pack(ridge), "ridge_is_data_identification": False,
            "original_smooth_check_status": "FAILED", "genuine_independent_users": False,
            "actual_nonlinear_improvement_measured": False, "candidate_materialized": False,
            "adopted": False}
