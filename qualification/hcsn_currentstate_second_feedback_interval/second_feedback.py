"""Exact second-feedback intervals for a deterministic hit-delay-reset fixture.

The first-feedback candidate supplies two completed delay-length segments.  A
third method-of-steps segment carries both the prior active trajectory and its
own delayed driver, so the second reset feedback is evolved by the same finite
CTMC law.  This is not an arbitrary-history or full-domain DDE solver.
"""

from dataclasses import dataclass
from fractions import Fraction

from qualification.hcsn_currentstate_hit_delay_reset_interval.hit_delay_reset import (
    HitDelayResetCertificate,
    hit_delay_reset_outputs_from_fp64_amplitude,
)
from qualification.hcsn_currentstate_n256_non_substochastic_signed_interval.signed_interval import (
    NonSubstochasticSignedIntervalCertificate,
    _exact_fraction,
)
from qualification.hcsn_currentstate_scheduled_reset_interval.scheduled_reset import (
    _intervals,
    _propagate_interval,
)


@dataclass(frozen=True)
class SecondFeedbackCertificate:
    first_feedback: HitDelayResetCertificate
    third_segment: NonSubstochasticSignedIntervalCertificate
    same_ctmc_hit_flux_encoded: bool = True
    two_deterministic_delay_releases_encoded: bool = True
    third_segment_second_feedback_encoded: bool = True
    nonreturning_upper_preserved: bool = True
    fourth_or_later_segment_encoded: bool = False
    arbitrary_history_encoded: bool = False
    authentic_n256_bundle_loaded: bool = False
    current_state_provider_qualified: bool = False


_THIRD_SEGMENT_ROWS = (
    (
        (0, "c008000000000000"),
        (3, "3ff0000000000000"),
        (4, "4000000000000000"),
        (5, "3ff0000000000000"),
        (7, "4000000000000000"),
    ),
    (
        (0, "4000000000000000"),
        (1, "c008000000000000"),
        (6, "4000000000000000"),
    ),
    (
        (1, "4000000000000000"),
        (2, "c008000000000000"),
    ),
    (),
    (),
    (),
    (),
    (),
)


def second_feedback_outputs_from_fp64_amplitude(amplitude_hex, delay_hex):
    """Return outputs after three segments and exactly two reset feedbacks."""

    _, first_feedback = hit_delay_reset_outputs_from_fp64_amplitude(
        amplitude_hex, delay_hex
    )
    first_lower, first_upper = _intervals(
        first_feedback.first_segment.interval_certificate
    )
    second_lower, second_upper = _intervals(first_feedback.second_segment)
    certificates = []
    amplitude = _exact_fraction(amplitude_hex, "amplitude", certificates)
    lower = (
        second_lower[0],
        first_lower[0],
        amplitude,
        second_lower[2],
        second_lower[3],
        second_lower[4],
        second_lower[5],
        Fraction(0),
    )
    upper = (
        second_upper[0],
        first_upper[0],
        amplitude,
        second_upper[2],
        second_upper[3],
        second_upper[4],
        second_upper[5],
        Fraction(0),
    )
    outputs, third = _propagate_interval(
        _THIRD_SEGMENT_ROWS, lower, upper, delay_hex
    )
    return outputs, SecondFeedbackCertificate(
        first_feedback=first_feedback,
        third_segment=third,
    )
