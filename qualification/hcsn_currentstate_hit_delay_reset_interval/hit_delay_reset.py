"""Exact first-feedback intervals for a deterministic hit-delay-reset fixture.

The first segment uses the same finite CTMC active state and its actual lower
hit flux.  On the second method-of-steps segment, a frozen driver copy carries
the first segment's active trajectory.  Twice that delayed driver is added to
the current active coordinate and to an explicit returned accumulator.  This
is the exact one-delay, first-feedback law for the small frozen fixture.

It does not cover a third segment, arbitrary histories, authentic N256, or the
full current-state provider.
"""

from dataclasses import dataclass
from fractions import Fraction

from qualification.hcsn_currentstate_augmented_selector_interval.augmented_selector import (
    AugmentedSelectorCertificate,
    augmented_selector_outputs_from_fp64_amplitude,
)
from qualification.hcsn_currentstate_n256_non_substochastic_signed_interval.signed_interval import (
    NonSubstochasticSignedIntervalCertificate,
    RoundedSignedOutputInterval,
    _exact_fraction,
)
from qualification.hcsn_currentstate_scheduled_reset_interval.scheduled_reset import (
    _intervals,
    _propagate_interval,
)


class HitDelayResetIntervalError(ValueError):
    """Raised when the first-feedback request leaves the frozen proof domain."""


@dataclass(frozen=True)
class HitDelayResetCertificate:
    first_segment: AugmentedSelectorCertificate
    second_segment: NonSubstochasticSignedIntervalCertificate
    pending_interval: RoundedSignedOutputInterval
    same_ctmc_hit_flux_encoded: bool = True
    one_deterministic_delay_release_encoded: bool = True
    first_feedback_segment_encoded: bool = True
    nonreturning_upper_preserved: bool = True
    third_or_later_cycle_encoded: bool = False
    arbitrary_history_encoded: bool = False
    authentic_n256_bundle_loaded: bool = False
    current_state_provider_qualified: bool = False


_SECOND_SEGMENT_ROWS = (
    (
        (0, "c008000000000000"),
        (2, "3ff0000000000000"),
        (3, "4000000000000000"),
        (4, "3ff0000000000000"),
        (6, "4000000000000000"),
    ),
    (
        (0, "4000000000000000"),
        (1, "c008000000000000"),
        (5, "4000000000000000"),
    ),
    (),
    (),
    (),
    (),
    (),
)


def hit_delay_reset_outputs_from_fp64_amplitude(amplitude_hex, delay_hex):
    """Return first-feedback outputs after exactly two delay-length segments."""

    _, first = augmented_selector_outputs_from_fp64_amplitude(
        amplitude_hex, delay_hex
    )
    first_lower, first_upper = _intervals(first.interval_certificate)
    conversion_certificates = []
    amplitude = _exact_fraction(
        amplitude_hex, "amplitude", conversion_certificates
    )
    lower = (
        first_lower[0],
        amplitude,
        first_lower[1],
        first_lower[2],
        first_lower[3],
        Fraction(0),
        Fraction(0),
    )
    upper = (
        first_upper[0],
        amplitude,
        first_upper[1],
        first_upper[2],
        first_upper[3],
        Fraction(0),
        Fraction(0),
    )
    outputs, second = _propagate_interval(
        _SECOND_SEGMENT_ROWS, lower, upper, delay_hex
    )
    pending = second.outputs[6]
    return outputs, HitDelayResetCertificate(
        first_segment=first,
        second_segment=second,
        pending_interval=pending,
    )
