"""Prospective public-state text guard; not a registered ABC4 final policy.

This pure function considers every *possible* decoded cue-2 category under the
existing public fusion rule. It never receives a source owner, target, future
observation, output score, waveform or filesystem path. A certificate concerns
the two intended text chunks relative to fixed route 10, from the same gate-0
Frame, with gate 1 fixed to commit and no committed-prefix ASR probe.

No actual speech, latency, success-retention or economic result is claimed.
"""

from dataclasses import dataclass

import numpy as np

from .state import Frame, SENSOR_QUALITY, likelihood
from .tasks import WORDS


@dataclass(frozen=True)
class TextGuardDecision:
    """Finite public-model checks, not a physical-output certificate."""

    route: tuple
    skip_query_certified: bool
    original_winners: tuple
    effective_quality: tuple
    enumerated_cases_per_fact: tuple
    changed_winner_cases: int
    nonunique_winner_cases: int


def public_fixed10_guard(frame):
    """Choose 00 only if every cue-2 update preserves all three text winners.

The existing fusion factorizes by fact, so K+1 category/missing cases per fact
suffice. Enumerate the actual floating-point multiply/normalize/argmax sequence
instead of rounding the analytic odds threshold. Tied maxima conservatively
retain route 10 even when NumPy's current tie-break would keep the old winner.

This is intentionally not wired into Policy, run.py, or the frozen final.
"""
    if type(frame) is not Frame:
        raise TypeError("Only a detached public Frame is accepted")
    if (frame.stage != 0 or frame.first_action != -1 or frame.template not in (0, 1)
            or len(frame.observations) != 1 or len(frame.posterior) != len(WORDS)):
        raise ValueError("The guard applies only after the mandatory cue at gate 0")
    winners, qualities, counts = [], [], []
    changed, nonunique = 0, 0
    for prior, nominal, words in zip(frame.posterior, SENSOR_QUALITY[1], WORDS):
        probability = np.asarray(prior, dtype=np.float64)
        if (probability.shape != (len(words),) or not np.isfinite(probability).all()
                or (probability < 0).any()
                or not np.isclose(probability.sum(), 1., rtol=0., atol=32 * np.finfo(np.float64).eps)):
            raise ValueError("Malformed public posterior")
        quality = .85 * nominal + .15 / len(words)
        if not 1 / len(words) <= quality < 1:
            raise ValueError("This derivation requires informative, non-certain fusion")
        winner = int(np.argmax(probability))
        winners.append(winner)
        qualities.append(quality)
        counts.append(len(words) + 1)
        for decoded in (None, *range(len(words))):
            updated = probability.copy()
            if decoded is not None:
                updated *= likelihood(decoded, quality, len(words))
            updated /= updated.sum()
            changed += int(int(np.argmax(updated)) != winner)
            nonunique += int(np.count_nonzero(updated == updated.max()) != 1)
    certified = changed == 0 and nonunique == 0
    return TextGuardDecision((0, 0) if certified else (1, 0), certified,
                             tuple(winners), tuple(qualities), tuple(counts),
                             changed, nonunique)
