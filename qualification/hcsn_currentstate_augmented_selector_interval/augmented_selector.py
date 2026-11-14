"""Exact small-fixture intervals for augmented current-state selectors.

The fixed finite operator contains an active state, a nonreturning upper state,
lower-hit and occupation accumulators, and an independently discounted active
copy with discounted hit and occupation accumulators.  It deliberately proves
only the selector arithmetic on this fixture.  It is not the authentic N256
provider and it does not implement deterministic delay or reset.
"""

from dataclasses import dataclass

from qualification.hcsn_currentstate_n256_non_substochastic_signed_interval.signed_interval import (
    NonSubstochasticSignedIntervalCertificate,
    non_substochastic_signed_outputs_from_fp64_intervals,
)


@dataclass(frozen=True)
class AugmentedSelectorCertificate:
    interval_certificate: NonSubstochasticSignedIntervalCertificate
    state_order: tuple[str, ...]
    nonreturning_upper_encoded: bool = True
    lower_hit_accumulator_encoded: bool = True
    occupation_accumulator_encoded: bool = True
    discounted_hit_accumulator_encoded: bool = True
    discounted_occupation_accumulator_encoded: bool = True
    deterministic_delay_encoded: bool = False
    reset_encoded: bool = False
    authentic_n256_bundle_loaded: bool = False
    current_state_provider_qualified: bool = False


_ROWS = (
    (
        (0, "c008000000000000"),
        (1, "3ff0000000000000"),
        (2, "4000000000000000"),
        (3, "3ff0000000000000"),
    ),
    (),
    (),
    (),
    (
        (4, "c00c000000000000"),
        (5, "4000000000000000"),
        (6, "3ff0000000000000"),
    ),
    (),
    (),
)

_STATE_ORDER = (
    "active",
    "nonreturning_upper",
    "lower_hit",
    "occupation",
    "discounted_active",
    "discounted_lower_hit",
    "discounted_occupation",
)


def augmented_selector_outputs_from_fp64_amplitude(amplitude_hex, duration_hex):
    """Return exact interval-rounded outputs for the fixed augmented fixture."""

    outputs, interval_certificate = (
        non_substochastic_signed_outputs_from_fp64_intervals(
            _ROWS,
            (
                amplitude_hex,
                "0000000000000000",
                "0000000000000000",
                "0000000000000000",
                amplitude_hex,
                "0000000000000000",
                "0000000000000000",
            ),
            duration_hex,
        )
    )
    return outputs, AugmentedSelectorCertificate(
        interval_certificate=interval_certificate,
        state_order=_STATE_ORDER,
    )
