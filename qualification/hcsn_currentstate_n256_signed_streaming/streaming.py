"""Prevalidate-all, emit-one signed exact streaming candidate.

The public function parses the shared operator and duration once, validates
every vector before returning an iterator, and then parses and evaluates one
frozen vector at a time.  This stage is limited to small synthetic fixtures;
it does not load or execute the authentic N256 bundle.
"""

from qualification.hcsn_currentstate_n256_non_substochastic_signed_interval.signed_interval import (
    NonSubstochasticSignedIntervalError,
    _canonical_operator,
    _exact_fraction,
    _transition_rows,
)
from qualification.hcsn_currentstate_n256_signed_batch_candidate.batch_candidate import (
    MAX_BATCH_VECTORS,
    _outputs_from_parsed,
)


def non_substochastic_signed_stream_from_fp64_intervals(
    rows_hex, vectors_hex, duration_hex, *, max_terms=1024
):
    """Return a one-vector-at-a-time iterator after validating all inputs."""

    if not isinstance(max_terms, int) or isinstance(max_terms, bool) or max_terms < 1:
        raise NonSubstochasticSignedIntervalError(
            "max_terms must be a positive integer"
        )
    if not isinstance(vectors_hex, (tuple, list)) or not vectors_hex:
        raise NonSubstochasticSignedIntervalError(
            "vectors must be a non-empty sequence"
        )
    if len(vectors_hex) > MAX_BATCH_VECTORS:
        raise NonSubstochasticSignedIntervalError(
            f"vectors exceed bounded batch limit {MAX_BATCH_VECTORS}"
        )

    operator_certificates = []
    operator, diagonals, off_diagonal_sums = _canonical_operator(
        rows_hex, operator_certificates
    )
    duration_certificates = []
    duration = _exact_fraction(duration_hex, "duration", duration_certificates)
    if duration < 0:
        raise NonSubstochasticSignedIntervalError("duration must be non-negative")
    transition, rate, transition_l1_norm = _transition_rows(
        operator, diagonals, off_diagonal_sums
    )

    frozen_vectors = []
    for vector_hex in vectors_hex:
        if not isinstance(vector_hex, (tuple, list)) or len(vector_hex) != len(
            operator
        ):
            raise NonSubstochasticSignedIntervalError("vector dimension mismatch")
        frozen_vector = tuple(vector_hex)
        validation_certificates = []
        for value in frozen_vector:
            _exact_fraction(value, "vector value", validation_certificates)
        frozen_vectors.append(frozen_vector)
    frozen_vectors = tuple(frozen_vectors)

    def stream():
        for frozen_vector in frozen_vectors:
            vector_certificates = []
            vector = tuple(
                _exact_fraction(value, "vector value", vector_certificates)
                for value in frozen_vector
            )
            certificates = [
                *operator_certificates,
                *vector_certificates,
                *duration_certificates,
            ]
            yield _outputs_from_parsed(
                vector,
                duration,
                transition,
                rate,
                transition_l1_norm,
                certificates,
                max_terms,
            )

    return stream()
