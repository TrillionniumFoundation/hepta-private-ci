"""Independent method of steps for piecewise event-time delayed laws.

Only NumPy/SciPy ODE integration is used. Every emission epoch retains its
own delay and reset distribution. Overlapping return windows contribute
additively; changing a delay never retimes an already emitted event.
"""

from dataclasses import dataclass
from fractions import Fraction
import math

import numpy as np
from scipy.integrate import solve_ivp


@dataclass(frozen=True)
class Law:
    end: Fraction
    delay: Fraction
    generator: np.ndarray
    lower: np.ndarray
    upper: np.ndarray
    reset: np.ndarray
    reward: np.ndarray
    escape_reward: float
    spike_reward: float
    discount: float


def solve(laws, active, *, rtol=2e-11, atol=2e-13):
    """Return active/escape/hits/occupation/discounted-hits/value and waiting.

No instantaneous interventions are implicit. The generator grid is fixed,
and the supplied finite signed initial channels have no pending prehistory.
The discount clock is the integral of the piecewise discount rate.
"""
    if not laws or active.ndim != 2 or not np.isfinite(active).all():
        raise ValueError("finite channel-by-space initial state and laws required")
    starts = [Fraction(0), *[law.end for law in laws[:-1]]]
    if any(not isinstance(law.end, Fraction) or not isinstance(law.delay, Fraction)
           or law.end <= start or law.delay <= 0 for law, start in zip(laws, starts)):
        raise ValueError("strict rational epochs and positive delays required")
    channels, nodes = active.shape
    if any(law.generator.shape != (nodes, nodes) or law.discount < 0 for law in laws):
        raise ValueError("fixed spatial grid and nonnegative discount required")
    horizon = laws[-1].end
    smallest = min(law.delay for law in laws)
    # Closing discontinuities under the applicable emission-time delay also
    # covers subsequent generations. Regular knots bound every ODE interval
    # by the shortest delay, so all forcing comes from solved earlier history.
    knots = {Fraction(0), horizon, *[law.end for law in laws]}
    count = math.ceil(horizon / smallest)
    if count > 128:
        raise ValueError("bounded reference horizon exceeded")
    knots.update(i * smallest for i in range(1, count))
    queue = list(knots)
    while queue:
        edge = queue.pop()
        for start, law in zip(starts, laws):
            shifted = edge + law.delay
            if start <= edge <= law.end and shifted < horizon and shifted not in knots:
                knots.add(shifted)
                queue.append(shifted)
        if len(knots) > 4096:
            raise ValueError("reference knot budget exceeded")
    prior_discount = [0.]
    for start, law in zip(starts, laws):
        prior_discount.append(prior_discount[-1] + law.discount * float(law.end - start))
    y = np.zeros((channels, nodes + 5))
    y[:, :nodes] = active
    histories = []
    evaluations = 0

    def past_state(time):
        for left, right, dense in reversed(histories):
            if left - 2e-15 <= time <= right + 2e-15:
                return dense(min(right, max(left, time))).reshape(channels, nodes + 5)
        if abs(time) <= 2e-15:
            initial = np.zeros_like(y)
            initial[:, :nodes] = active
            return initial
        raise ValueError("delayed forcing requested unsolved history")

    ordered = sorted(knots)
    for left_q, right_q in zip(ordered, ordered[1:]):
        middle = (left_q + right_q) / 2
        index = next(i for i, law in enumerate(laws) if middle < law.end)
        law = laws[index]
        sources = [(old, float(old.delay)) for start, old in zip(starts, laws)
                   if start <= middle - old.delay < old.end]
        left, right = float(left_q), float(right_q)

        def rhs(time, flat):
            z = flat.reshape(channels, nodes + 5)
            incoming = np.zeros((channels, nodes))
            for old, delay in sources:
                previous = past_state(time - delay)[:, :nodes]
                incoming += (previous @ old.lower)[:, None] * old.reset
            derivative = np.zeros_like(z)
            derivative[:, :nodes] = z[:, :nodes] @ law.generator + incoming
            derivative[:, nodes] = z[:, :nodes] @ law.upper
            flux = z[:, :nodes] @ law.lower
            discount = math.exp(-prior_discount[index]
                                - law.discount * (time - float(starts[index])))
            derivative[:, nodes + 1] = flux
            derivative[:, nodes + 2] = z[:, :nodes].sum(1) + z[:, nodes]
            derivative[:, nodes + 3] = discount * flux
            derivative[:, nodes + 4] = discount * (
                z[:, :nodes] @ law.reward + law.escape_reward * z[:, nodes]
                + law.spike_reward * flux)
            return derivative.ravel()

        result = solve_ivp(rhs, (left, right), y.ravel(), method="DOP853",
                           rtol=rtol, atol=atol, dense_output=True,
                           max_step=float(smallest) / 6)
        if not result.success or not np.isfinite(result.y).all():
            raise FloatingPointError("unresolved independent delayed ODE")
        evaluations += result.nfev
        y = result.y[:, -1].reshape(channels, nodes + 5)
        histories.append((left, right, result.sol))
    waiting = np.zeros(channels)
    for start, law in zip(starts, laws):
        left = max(start, horizon - law.delay)
        right = min(horizon, law.end)
        if left < right:
            # Hits are continuous and have no intervention atoms in this API.
            waiting += (past_state(float(right))[:, nodes + 1]
                        - past_state(float(left))[:, nodes + 1])
    return {"state": y, "waiting": waiting,
            "discount_factor": math.exp(-prior_discount[-1]),
            "segments": len(histories), "rhs_evaluations": evaluations}
