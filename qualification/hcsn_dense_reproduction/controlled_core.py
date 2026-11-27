"""Finite spatial CTMC with deterministic delay, reset and shared marked flow.

Upper exits are retained as a permanently active, nonreturning compartment.
This is an explicit truncation, never a returning-tail model. Method-of-steps
uses dense numerical histories of the ACTUAL CTMC hit flux, not uniformized
per-step hit masses. Deterministic delay is exact in the model; ODE history
interpolation and integration still have measured numerical error.
"""

from dataclasses import dataclass
from fractions import Fraction
import math

import numpy as np
from scipy.integrate import solve_ivp
from scipy.sparse import block_diag, csr_matrix

from qualification.hcsn_boundary_audit.spatial_generator import KilledSpatialGenerator
from qualification.hcsn_boundary_audit.refractory_transport import Packet


@dataclass(frozen=True)
class JointModel:
    spatial: KilledSpatialGenerator
    reset: float
    delay: float
    discount: float
    active_reward: float = 0.4
    hit_reward: float = 1.0

    def __post_init__(self):
        if not isinstance(self.spatial, KilledSpatialGenerator):
            raise ValueError("spatial generator required")
        for name in ("reset", "delay", "discount", "active_reward", "hit_reward"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError("finite scalar model parameters required")
        h, endpoint = self.spatial.spacing, self.spatial.endpoint
        if (
            not h <= self.reset <= endpoint - h
            or not 0 < self.delay <= 2
            or not 0.001 <= self.discount <= 4
        ):
            raise ValueError(
                "reset stencil must be interior; positive delay and qualified discount required"
            )
        if self.active_reward < 0 or self.hit_reward < 0:
            raise ValueError("nonnegative rewards required")

    def ingredients(self):
        matrix = self.spatial.matrix()
        transient = matrix[1:-1, 1:-1]
        lower, upper = matrix[1:-1, 0], matrix[1:-1, -1]
        position = self.reset / self.spatial.spacing
        left = int(math.floor(position))
        reset = np.zeros(self.spatial.intervals + 1)
        reset[left] = 1 - (position - left)
        reset[left + 1] = position - left
        return transient, lower, upper, reset[1:-1]

    def perpetual(self):
        """Continuation of THIS same CTMC/delay model, including upper flow."""
        phi = self.spatial.discounted_lower_hit(self.discount)
        reset_phi = float(
            np.interp(self.reset, np.linspace(0, self.spatial.endpoint, len(phi)), phi)
        )
        base = self.active_reward / self.discount
        eta = math.exp(-self.discount * self.delay)
        reset_value = (base * (1 - reset_phi) + self.hit_reward * reset_phi) / (
            1 - eta * reset_phi
        )
        values = base + phi * (self.hit_reward + eta * reset_value - base)
        return values, reset_value

    def solve(
        self,
        query_times,
        active,
        content,
        phase=(),
        *,
        rtol=2e-9,
        atol=2e-11,
        max_step=None,
    ):
        """Return dense-history DDE states for fixed physics and one initial law.

        active includes both boundary coordinates; initial lower-boundary mass
        is refused, rather than silently turning it into an unrecorded hit.
        Content is transported by the identical linear equation. Packet phase
        supports are remaining-time laws at time zero, and may include atoms.
        """
        times = np.asarray(query_times, dtype=np.float64)
        probability = np.asarray(active, dtype=np.float64)
        marked = np.asarray(content, dtype=np.float64)
        if (
            times.ndim != 1
            or not 1 <= len(times) <= 4096
            or not np.all(np.isfinite(times))
            or np.any(times < 0)
            or np.any(np.diff(times) <= 0)
            or times[-1] > 8
        ):
            raise ValueError("strictly increasing finite query times in [0,8] required")
        if (
            probability.shape != (self.spatial.intervals + 1,)
            or marked.ndim != 2
            or marked.shape[0] != len(probability)
            or not 1 <= marked.shape[1] <= 16
            or not np.all(np.isfinite(probability))
            or not np.all(np.isfinite(marked))
            or np.min(probability) < 0
            or probability[0] != 0
            or np.any(marked[0] != 0)
        ):
            raise ValueError(
                "finite initial active/content shapes and zero lower atom required"
            )
        if not 1e-12 <= rtol <= 1e-3 or not 1e-18 <= atol <= 1e-5:
            raise ValueError("explicit ODE error controls required")
        if (
            not isinstance(phase, tuple)
            or len(phase) > 4096
            or times[-1] / self.delay > 4094
            or (len(times) + 2 * len(phase) + 1) * (int(times[-1] / self.delay) + 2)
            > 16384
        ):
            raise ValueError("declared history/source breakpoint budget exceeded")
        max_step = self.delay / 8 if max_step is None else float(max_step)
        if not math.isfinite(max_step) or not 0 < max_step <= self.delay:
            raise ValueError("max_step must be positive and at most the delay")
        transient, lower, upper, reset = self.ingredients()
        n, channels = len(lower), marked.shape[1] + 1
        # Per mark: interior, upper, refractory, M, H_q, A_q, E[e^-q remaining].
        size = n + 6
        state = np.zeros((channels, size))
        state[:, :n] = np.column_stack((probability[1:-1], marked[1:-1])).T
        state[:, n] = np.r_[probability[-1], marked[-1]]
        uniform, atoms = [], {}
        base_knots = [0.0, *times]
        for packet in phase:
            if not isinstance(packet, Packet):
                raise ValueError("validated exact-support phase Packet required")
            vector = np.r_[
                float(packet.mass), np.asarray(packet.content, dtype=np.float64)
            ]
            left, right = float(packet.start), float(packet.end)
            if (
                vector.shape != (channels,)
                or not np.all(np.isfinite(vector))
                or not 0 <= left <= right <= self.delay
            ):
                raise ValueError("phase packet shape/support mismatch")
            state[:, n + 1] += vector
            if left == right:
                phase_discount = math.exp(-self.discount * left)
            else:
                phase_discount = (
                    math.exp(-self.discount * left)
                    * -math.expm1(-self.discount * (right - left))
                    / (self.discount * (right - left))
                )
            state[:, n + 5] += vector * phase_discount
            base_knots.extend((left, right))
            if left == right:
                atoms[left] = atoms.get(left, np.zeros(channels)) + vector
            else:
                uniform.append((left, right, vector / (right - left)))
        # Propagate every source discontinuity by delay; splitting queries is
        # harmless and makes arbitrary observation schedules explicitly visible.
        knots = {Fraction(0), Fraction(str(float(times[-1])))}
        for base_time in base_knots:
            for k in range(int(times[-1] / self.delay) + 2):
                value = Fraction(str(base_time)) + k * Fraction(str(self.delay))
                if 0 <= value <= Fraction(str(float(times[-1]))):
                    knots.add(value)
        knots = list(map(float, sorted(knots)))
        linear = np.zeros((size, size))
        linear[:n, :n] = transient.T
        linear[n, :n] = upper
        linear[n + 1, :n] = lower
        linear[n + 2, :n] = lower
        linear[n + 5, :n] = math.exp(-self.discount * self.delay) * lower
        linear[n + 5, n + 5] = self.discount
        # H and A rows have time-dependent discount, supplied separately.
        jac = block_diag([csr_matrix(linear)] * channels, format="csr")
        history, snapshots, steps = [], {}, 0

        def past_flux(time):
            if time < 0:
                return np.zeros(channels)
            # Delayed forcing is continuous within each recorded source
            # segment. Rightmost segment handles the post-atom convention.
            for left, right, dense in reversed(history):
                if left <= time <= right:
                    return dense(time).reshape(channels, size)[:, :n] @ lower
            return state[:, :n] @ lower if time == 0 else np.zeros(channels)

        for i, left in enumerate(knots):
            if left in atoms:
                vector = atoms[left]
                state[:, :n] += vector[:, None] * reset
                state[:, n + 1] -= vector
                state[:, n + 5] -= vector
            snapshots[left] = state.copy()
            if i == len(knots) - 1:
                break
            right = knots[i + 1]
            mid = (left + right) / 2
            initial_release = sum(
                (value for lo, hi, value in uniform if lo <= mid < hi),
                np.zeros(channels),
            )

            def rhs(time, flat):
                current = flat.reshape(channels, size)
                hit = current[:, :n] @ lower
                # A source jump at the right knot belongs to the next segment.
                forcing_time = min(time, np.nextafter(right, left))
                release = initial_release + past_flux(forcing_time - self.delay)
                result = current @ linear.T
                result[:, :n] += release[:, None] * reset
                result[:, n + 1] -= release
                result[:, n + 5] -= release
                result[:, n + 3] = math.exp(-self.discount * time) * hit
                result[:, n + 4] = math.exp(-self.discount * time) * (
                    current[:, :n].sum(1) + current[:, n]
                )
                return result.ravel()

            # Jacobian excludes discount-weighted integrator rows; supplying
            # its sparsity is safe, while an incomplete exact Jacobian is not.
            sparsity = jac.copy().tolil()
            for channel in range(channels):
                offset = channel * size
                sparsity[offset + n + 3, offset : offset + n] = 1
                sparsity[offset + n + 4, offset : offset + n + 1] = 1
            result = solve_ivp(
                rhs,
                (left, right),
                state.ravel(),
                method="BDF",
                rtol=rtol,
                atol=atol,
                max_step=max_step,
                jac_sparsity=sparsity.tocsr(),
                dense_output=True,
            )
            if not result.success or not np.all(np.isfinite(result.y)):
                raise ArithmeticError("DDE segment integration failed")
            history.append((left, right, result.sol))
            state = result.y[:, -1].reshape(channels, size)
            steps += len(result.t) - 1
        outputs = []
        initial_total = probability.sum() + sum(float(p.mass) for p in phase)
        initial_content = marked.sum(0) + sum(
            (np.asarray(p.content, dtype=float) for p in phase), np.zeros(channels - 1)
        )
        for time in times:
            value = snapshots[float(time)]
            total = value[:, : n + 2].sum(1)
            if np.min(value[0, : n + 2]) < -max(1e-8, 100 * atol):
                raise ArithmeticError(
                    "probability negativity is numerically unresolved"
                )
            outputs.append(
                {
                    "time": float(time),
                    "active": value[:, :n].T,
                    "upper": value[:, n],
                    "refractory": value[:, n + 1],
                    "events": value[:, n + 2],
                    "discounted_events": value[:, n + 3],
                    "discounted_active_time": value[:, n + 4],
                    "discounted_remaining_phase": value[:, n + 5],
                    "mass_residual": total[0] - initial_total,
                    "content_residual": total[1:] - initial_content,
                }
            )
        return {
            "rows": outputs,
            "internal_steps": steps,
            "upper_semantics": "permanently_active_nonreturning_escape",
            "delay_semantics": "deterministic_dense_flux_history",
            "rtol": rtol,
            "atol": atol,
            "max_step": max_step,
        }
