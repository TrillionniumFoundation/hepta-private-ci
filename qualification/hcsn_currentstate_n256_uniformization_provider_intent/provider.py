"""Independent sparse-uniformization primitives, frozen without N256 execution.

Only the Python standard library is imported.  The source deliberately has no
N256 runner and no dependency on the engineering candidate, the SciPy oracle,
NumPy, SciPy, Torch, or an inherited propagation implementation.  Small
synthetic fixtures may exercise these primitives; authentic N256 execution
remains fail-closed behind a separately published admission and certificates.
"""

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path


PROVIDER_SCHEMA = "certified_sparse_uniformization_v1"
ADMISSION_SCHEMA = "hcsn-n256-uniformization-provider-admission-v1"
REQUIRED_CERTIFICATIONS = (
    "permanent_nonreturning_upper_escape",
    "deterministic_delay_and_reset",
    "signed_l1_tail",
    "discounted_hit_and_occupation",
    "fp64_rounding",
    "every_emitted_roster_operator",
)


class ProviderError(ValueError):
    """Raised before accepting a malformed operator, certificate, or admission."""


@dataclass(frozen=True)
class SparseSubgenerator:
    """Immutable row-sparse subgenerator with canonical binary64 identity."""

    rows: tuple
    dimension: int
    identity: str

    @classmethod
    def from_rows(cls, rows):
        canonical_rows = []
        dimension = len(rows)
        if dimension <= 0:
            raise ProviderError("operator dimension must be positive")
        for row_index, entries in enumerate(rows):
            seen = set()
            canonical = []
            diagonal = None
            row_sum = 0.0
            for column, raw_value in sorted(entries):
                value = float(raw_value)
                if not isinstance(column, int) or column < 0 or column >= dimension:
                    raise ProviderError("operator column is out of range")
                if column in seen or not math.isfinite(value):
                    raise ProviderError("operator entry is duplicate or non-finite")
                seen.add(column)
                if column == row_index:
                    diagonal = value
                    if value > 0.0:
                        raise ProviderError("subgenerator diagonal is positive")
                elif value < 0.0:
                    raise ProviderError("subgenerator off-diagonal is negative")
                row_sum += value
                canonical.append((column, value))
            if diagonal is None:
                raise ProviderError("subgenerator diagonal is missing")
            tolerance = 32.0 * math.ulp(max(1.0, abs(diagonal)))
            if row_sum > tolerance:
                raise ProviderError("subgenerator row sum is positive")
            canonical_rows.append(tuple(canonical))
        payload = [
            [[column, value.hex()] for column, value in row]
            for row in canonical_rows
        ]
        identity = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return cls(tuple(canonical_rows), dimension, identity)

    def transition_rows(self, rate):
        rate = float(rate)
        if not math.isfinite(rate) or rate <= 0.0:
            raise ProviderError("uniformization rate must be finite and positive")
        transition = []
        for row_index, row in enumerate(self.rows):
            entries = []
            row_sum = 0.0
            for column, value in row:
                probability = value / rate
                if column == row_index:
                    probability += 1.0
                if probability < 0.0 or not math.isfinite(probability):
                    raise ProviderError("uniformization rate is below an exit rate")
                if probability != 0.0:
                    entries.append((column, probability))
                    row_sum += probability
            if row_sum > 1.0 + 64.0 * math.ulp(1.0):
                raise ProviderError("uniformized transition row exceeds one")
            transition.append(tuple(entries))
        return tuple(transition)


@dataclass(frozen=True)
class PoissonWindow:
    intensity: float
    truncation_index: int
    weights: tuple
    tail_upper: float


@dataclass
class ProviderCounts:
    synthetic_provider_calls: int = 0
    sparse_row_actions: int = 0
    poisson_recurrence_terms: int = 0
    n256_provider_calls: int = 0
    candidate_calls: int = 0
    oracle_calls: int = 0
    model_calls: int = 0
    optimizer_calls: int = 0


@dataclass(frozen=True)
class UniformizationResult:
    values: tuple
    operator_identity: str
    intensity_hex: str
    truncation_index: int
    recurrence_terms: int
    input_l1_hex: str
    poisson_tail_upper_hex: str
    signed_l1_tail_upper_hex: str
    fp64_rounding_certified: bool = False
    provider_admitted: bool = False
    largegrid_qualification: bool = False


def _row_action(vector, transition):
    if len(vector) != len(transition):
        raise ProviderError("row-action dimension mismatch")
    output = [0.0] * len(vector)
    for row_index, value in enumerate(vector):
        if not math.isfinite(value):
            raise ProviderError("row-action input is non-finite")
        for column, probability in transition[row_index]:
            output[column] += value * probability
    if not all(math.isfinite(value) for value in output):
        raise ProviderError("row-action output is non-finite")
    return tuple(output)


def stable_poisson_window(intensity, truncation_index):
    """Construct binary64 Poisson weights and a ratio-geometric tail bound.

    The modal weight is evaluated through ``lgamma`` and all other retained
    weights are reached by recurrence.  This avoids ``exp(-intensity)``
    underflow at the frozen N256 stiffness scale.  It does not certify the
    floating-point rounding error of those recurrences.
    """

    intensity = float(intensity)
    if not math.isfinite(intensity) or intensity < 0.0:
        raise ProviderError("Poisson intensity must be finite and nonnegative")
    if not isinstance(truncation_index, int) or truncation_index < 0:
        raise ProviderError("Poisson truncation index is invalid")
    if intensity == 0.0:
        return PoissonWindow(0.0, truncation_index, (1.0,) + (0.0,) * truncation_index, 0.0)
    if truncation_index + 2 <= intensity:
        raise ProviderError("tail is not in the decreasing ratio regime")

    mode = int(math.floor(intensity))
    modal_weight = math.exp(
        -intensity + mode * math.log(intensity) - math.lgamma(mode + 1.0)
    )
    weights = [0.0] * (truncation_index + 1)
    if mode <= truncation_index:
        weights[mode] = modal_weight
    value = modal_weight
    for index in range(mode, 0, -1):
        value *= index / intensity
        if index - 1 <= truncation_index:
            weights[index - 1] = value
    value = modal_weight
    for index in range(mode + 1, truncation_index + 1):
        value *= intensity / index
        weights[index] = value

    last_weight = weights[-1]
    first_omitted = last_weight * intensity / (truncation_index + 1)
    ratio_upper = intensity / (truncation_index + 2)
    tail_upper = first_omitted / (1.0 - ratio_upper)
    if not math.isfinite(tail_upper) or tail_upper < 0.0:
        raise ProviderError("Poisson tail bound is non-finite")
    return PoissonWindow(intensity, truncation_index, tuple(weights), tail_upper)


def synthetic_uniformization_action(operator, initial, duration, rate, truncation_index, counts=None):
    """Exercise the provider on a small synthetic operator only.

    No N256 input path, roster path, or execution admission is accepted here.
    The result exposes a computed Poisson tail bound but explicitly leaves
    FP64-rounding certification and provider admission false.
    """

    if not isinstance(operator, SparseSubgenerator):
        raise ProviderError("operator type mismatch")
    duration = float(duration)
    rate = float(rate)
    if not math.isfinite(duration) or duration < 0.0:
        raise ProviderError("duration must be finite and nonnegative")
    vector = tuple(float(value) for value in initial)
    if len(vector) != operator.dimension:
        raise ProviderError("initial vector dimension mismatch")
    transition = operator.transition_rows(rate)
    window = stable_poisson_window(rate * duration, truncation_index)
    current = vector
    output = [weight * value for value, weight in zip(current, (window.weights[0],) * len(current))]
    local_counts = counts if counts is not None else ProviderCounts()
    for weight in window.weights[1:]:
        current = _row_action(current, transition)
        local_counts.sparse_row_actions += 1
        for index, value in enumerate(current):
            output[index] += weight * value
    local_counts.synthetic_provider_calls += 1
    local_counts.poisson_recurrence_terms += len(window.weights)
    input_l1 = math.fsum(abs(value) for value in vector)
    return UniformizationResult(
        values=tuple(output),
        operator_identity=operator.identity,
        intensity_hex=float(rate * duration).hex(),
        truncation_index=truncation_index,
        recurrence_terms=len(window.weights),
        input_l1_hex=input_l1.hex(),
        poisson_tail_upper_hex=window.tail_upper.hex(),
        signed_l1_tail_upper_hex=(input_l1 * window.tail_upper).hex(),
    )


def validate_external_certificate(record, result, provider_source_sha256, admission_sha256):
    """Validate identities and required claims without creating a certificate."""

    required = {
        "schema",
        "provider_source_sha256",
        "provider_admission_sha256",
        "operator_identity",
        "poisson_intensity_fp64_hex",
        "truncation_index",
        "input_l1_fp64_hex",
        "poisson_tail_upper_fp64_hex",
        "rounding_upper_fp64_hex",
        "signed_l1_output_upper_fp64_hex",
        "recurrence_terms",
        "certifications",
        "certificate_sha256",
    }
    if set(record) != required:
        raise ProviderError("external certificate field set mismatch")
    expected = (
        PROVIDER_SCHEMA,
        provider_source_sha256,
        admission_sha256,
        result.operator_identity,
        result.intensity_hex,
        result.truncation_index,
        result.input_l1_hex,
        result.recurrence_terms,
    )
    actual = (
        record["schema"],
        record["provider_source_sha256"],
        record["provider_admission_sha256"],
        record["operator_identity"],
        record["poisson_intensity_fp64_hex"],
        record["truncation_index"],
        record["input_l1_fp64_hex"],
        record["recurrence_terms"],
    )
    if actual != expected:
        raise ProviderError("external certificate identity mismatch")
    certifications = record["certifications"]
    if set(certifications) != set(REQUIRED_CERTIFICATIONS) or not all(
        value is True for value in certifications.values()
    ):
        raise ProviderError("external certificate claims are incomplete")
    for name in (
        "poisson_tail_upper_fp64_hex",
        "rounding_upper_fp64_hex",
        "signed_l1_output_upper_fp64_hex",
    ):
        try:
            value = float.fromhex(record[name])
        except (TypeError, ValueError) as error:
            raise ProviderError("external certificate bound is invalid") from error
        if not math.isfinite(value) or value < 0.0:
            raise ProviderError("external certificate bound is invalid")
    if float.fromhex(record["poisson_tail_upper_fp64_hex"]) < float.fromhex(
        result.poisson_tail_upper_hex
    ):
        raise ProviderError("external certificate understates Poisson tail")
    payload = dict(record)
    digest = payload.pop("certificate_sha256")
    expected_digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if digest != expected_digest:
        raise ProviderError("external certificate digest mismatch")
    return True


def require_execution_admission(request_path, admission_path, provider_source_sha256):
    """Fail closed unless a later request and immutable admission are complete."""

    request = json.loads(Path(request_path).read_text())
    admission = json.loads(Path(admission_path).read_text())
    if request.get("numerical_execution_allowed") is not True:
        raise ProviderError("numerical execution is not allowed by request")
    required = {
        "runtime_profile_sha256",
        "host_snapshot_sha256",
        "ancestor_cgroup_snapshot_sha256",
        "allocation_sha256",
        "calendar_sha256",
        "provider_independence_review_sha256",
        "precision_policy_sha256",
    }
    resources = request.get("required_external_freeze")
    if not isinstance(resources, dict) or set(resources) != required or any(
        not isinstance(value, str) or len(value) != 64 for value in resources.values()
    ):
        raise ProviderError("external execution freeze is incomplete")
    if (
        admission.get("schema") != ADMISSION_SCHEMA
        or admission.get("provider_source_sha256") != provider_source_sha256
        or admission.get("request_sha256")
        != hashlib.sha256(Path(request_path).read_bytes()).hexdigest()
        or admission.get("admitted") is not True
    ):
        raise ProviderError("provider admission identity mismatch")
    return admission
