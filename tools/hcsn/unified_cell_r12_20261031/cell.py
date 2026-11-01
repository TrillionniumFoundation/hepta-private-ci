"""Full-HX-parameterized joint finite distribution and content cell.

The state is a row probability on (physical phase, content bit), with index
``2 * phase + bit``.  Eight cell-centered log-distance bins and two Erlang
recovery phases form a *finite CTMC*.  Its matrix exponential is a semigroup
for that finite generator, not an exact continuum He--Xiong/reset solution.
He--Xiong's financial boundary/value/debt formulas parameterize this declared
synthetic extension; the original financial paper does not imply regeneration.

Unlike the older mean-pressure closure, the entire joint distribution survives
between observations.  Natural absorption preserves the content bit while
entering recovery.  Recovery completion flips it with probability 0.125.
All physical derivatives are forward Dual arithmetic from the unchanged R11
full financial kernel followed by matrix-exponential Frechet derivatives.
There is no finite-difference training path or silent parameter clipping.
"""

import json
from pathlib import Path

import numpy as np
from scipy.linalg import expm, expm_frechet
from scipy.special import softmax

from ..calibrated_operator_r11_20261031.numerics.kernel import Dual, FullHX, log


PROTOCOL = json.loads(Path(__file__).with_name("PROTOCOL.json").read_text())
BASE_THETA = np.array(PROTOCOL["baseline_financial_parameters"], dtype=np.float64)
PHYSICAL_INDICES = np.array([2, 5, 6])
PHYSICAL_LOWER = np.array(PROTOCOL["physical_lower"], dtype=np.float64)
PHYSICAL_UPPER = np.array(PROTOCOL["physical_upper"], dtype=np.float64)
DEFAULT_EMISSIONS = np.array([
    [.32, .08, .24, .06, .22, .08],
    [.08, .32, .06, .24, .08, .22],
], dtype=np.float64)
DEFAULT_THETA = BASE_THETA[PHYSICAL_INDICES].copy()


def _physical_theta(theta):
    theta = np.asarray(theta, dtype=np.float64)
    if theta.shape == (3,):
        full = BASE_THETA.copy()
        full[PHYSICAL_INDICES] = theta
    elif theta.shape == (9,):
        full = theta.copy()
        frozen = np.ones(9, dtype=bool)
        frozen[PHYSICAL_INDICES] = False
        if not np.array_equal(full[frozen], BASE_THETA[frozen]):
            raise ValueError("R12 fixes the six non-learned financial parameters")
        theta = full[PHYSICAL_INDICES]
    else:
        raise ValueError("Expected sigma/liquidity/maturity or nine financial parameters")
    if not np.isfinite(full).all():
        raise ValueError("Financial parameters must be finite")
    if np.any(theta < PHYSICAL_LOWER) or np.any(theta > PHYSICAL_UPPER):
        raise ValueError("Physical parameters are outside the registered R12 box")
    return theta.copy(), full


class Cell:
    """The common model used by filtering, continuation planning and execution.

    Arrays use numpy float64 and row-vector conventions. ``dQ``, ``dprior``,
    ``dreward`` and ``dread_cost`` have a leading axis in the physical parameter
    order (sigma, liquidity, maturity). ``dE_logits`` has a leading axis for
    the 12 row-major active emission logits.  The seven-valued observation 6
    means recovery; a missing observation is separately represented by None.

    The reset asset remains fixed at 90. Its log-distance changes with the
    full financial boundary, including that boundary's parameter derivatives.
    Linear reset interpolation is only piecewise differentiable. Exact knots
    are rejected rather than silently assigning an arbitrary derivative.
    """

    n_active = int(PROTOCOL["active_cells"])
    n_recovery = int(PROTOCOL["recovery_phases"])
    content_classes = 2
    state_count = (n_active + n_recovery) * content_classes
    physical_parameter_count = 3
    emission_parameter_count = 12
    parameter_count = 15

    def __init__(self, theta=DEFAULT_THETA, emission_logits=None):
        self.theta, self.financial_theta = _physical_theta(theta)
        self.log_upper = float(PROTOCOL["log_upper"])
        self.spacing = self.log_upper / self.n_active
        self.centers = (np.arange(self.n_active) + .5) * self.spacing
        self.phase_centers = self.centers
        self.recovery_mean = float(PROTOCOL["recovery_mean"])
        self.reset_asset = float(PROTOCOL["reset_asset"])
        zero = np.zeros(3, dtype=np.float64)
        basis = np.eye(3, dtype=np.float64)
        parameter_duals = []
        for j, value in enumerate(self.financial_theta):
            locations = np.flatnonzero(PHYSICAL_INDICES == j)
            tangent = basis[int(locations[0])] if locations.size else zero
            parameter_duals.append(Dual(value, tangent))
        self._hx = FullHX(parameter_duals)
        self.boundary = float(self._hx.b.v)
        self.dboundary = self._hx.b.g.copy()
        self.assets = self.boundary * np.exp(self.centers)
        if not np.isfinite(self.boundary) or self.boundary <= 0:
            raise ValueError("Full HX returned an inadmissible financial boundary")
        reset = log(Dual(self.reset_asset, zero) / self._hx.b)
        self.reset_log_distance = float(reset.v)
        self.dreset_log_distance = reset.g.copy()
        if not self.centers[0] < reset.v < self.centers[-1]:
            raise ValueError("Reset log-distance is outside the represented center interval")
        if np.any(np.abs(self.centers - reset.v) <= 32 * np.finfo(float).eps):
            raise ValueError("Reset interpolation knot has no unique ordinary derivative")
        lo = int(np.searchsorted(self.centers, reset.v) - 1)
        fraction = (reset - self.centers[lo]) / self.spacing
        self.reset_weights = np.zeros(self.n_active)
        self.dreset_weights = np.zeros((3, self.n_active))
        self.reset_weights[lo:lo + 2] = [1 - fraction.v, fraction.v]
        self.dreset_weights[:, lo:lo + 2] = np.stack((-fraction.g, fraction.g), axis=1)

        # Centered cell-volume rates are strictly positive throughout the
        # registered physical box. The lower face has zero density: its
        # diffusive escape rate uses the half-cell distance (2 D/h^2), with
        # zero advective face flux. The upper face reflects. Positivity is
        # checked on each construction; no negative-rate clipping is allowed.
        sigma = parameter_duals[2]
        drift = parameter_duals[0] - parameter_duals[1] - sigma * sigma / 2
        diffusion = sigma * sigma / 2
        up = diffusion / self.spacing ** 2 + drift / (2 * self.spacing)
        down = diffusion / self.spacing ** 2 - drift / (2 * self.spacing)
        absorption = 2 * diffusion / self.spacing ** 2
        for name, rate in (("up", up), ("down", down), ("absorption", absorption)):
            if not np.isfinite(rate.v) or rate.v <= 0:
                raise ValueError(f"Nonpositive or nonfinite centered {name} rate")
        self.drift = float(drift.v)
        self.rates = dict(up=float(up.v), down=float(down.v), absorption=float(absorption.v))
        self.Q = np.zeros((self.state_count, self.state_count))
        self.dQ = np.zeros((3, self.state_count, self.state_count))
        self.event_rate = np.zeros(self.state_count)
        self.devent_rate = np.zeros((3, self.state_count))

        def edge(source, destination, rate):
            self.Q[source, destination] += rate.v
            self.Q[source, source] -= rate.v
            self.dQ[:, source, destination] += rate.g
            self.dQ[:, source, source] -= rate.g

        for phase in range(self.n_active):
            for bit in (0, 1):
                source = 2 * phase + bit
                if phase + 1 < self.n_active:
                    edge(source, 2 * (phase + 1) + bit, up)
                if phase:
                    edge(source, 2 * (phase - 1) + bit, down)
                else:
                    edge(source, 2 * self.n_active + bit, absorption)
                    self.event_rate[source] = absorption.v
                    self.devent_rate[:, source] = absorption.g
        recovery_rate = Dual(self.n_recovery / self.recovery_mean, zero)
        same_bit = (1 + float(PROTOCOL["content_retention"])) / 2
        for bit in (0, 1):
            for phase in range(self.n_active, self.n_active + self.n_recovery - 1):
                edge(2 * phase + bit, 2 * (phase + 1) + bit, recovery_rate)
            source = 2 * (self.n_active + self.n_recovery - 1) + bit
            for target in (lo, lo + 1):
                weight = Dual(self.reset_weights[target], self.dreset_weights[:, target])
                edge(source, 2 * target + bit, recovery_rate * weight * same_bit)
                edge(source, 2 * target + 1 - bit, recovery_rate * weight * (1 - same_bit))
        self._check_generator()

        self.R = np.zeros_like(self.Q)
        self.R[np.arange(self.state_count), 2 * self.n_active + np.arange(self.state_count) % 2] = 1
        self.prior = np.zeros(self.state_count)
        self.dprior = np.zeros((3, self.state_count))
        for bit in (0, 1):
            self.prior[bit:2 * self.n_active:2] = self.reset_weights / 2
            self.dprior[:, bit:2 * self.n_active:2] = self.dreset_weights / 2

        logits = np.log(DEFAULT_EMISSIONS) if emission_logits is None else np.asarray(emission_logits, dtype=np.float64)
        if logits.size != 12 or not np.isfinite(logits).all():
            raise ValueError("Expected twelve finite active emission logits")
        self.emission_logits = logits.reshape(2, 6).copy()
        self.active_emissions = softmax(self.emission_logits, axis=1)
        if np.any(self.active_emissions <= 0):
            raise ValueError("Emission logits yield unrepresentable positive likelihoods")
        self.E = np.zeros((self.state_count, 7))
        self.dE = np.zeros((3, self.state_count, 7))
        self.dE_phys = self.dE
        self.dE_logits = np.zeros((12, self.state_count, 7))
        for bit in (0, 1):
            indices = np.arange(bit, 2 * self.n_active, 2)
            self.E[indices, :6] = self.active_emissions[bit]
            jac = np.diag(self.active_emissions[bit]) - np.outer(self.active_emissions[bit], self.active_emissions[bit])
            for parameter in range(6):
                self.dE_logits[6 * bit + parameter, indices, :6] = jac[:, parameter]
        self.E[2 * self.n_active:, 6] = 1

        self.reward = (np.arange(self.state_count)[:, None] % 2 == np.arange(2)[None, :]).astype(float)
        self.dreward = np.zeros((3, self.state_count, 2))
        self.read_cost = np.full(self.state_count, .06)
        self.dread_cost = np.zeros((3, self.state_count))
        self.financial_values = np.zeros((self.n_active, 5))
        self.dfinancial_values = np.zeros((3, self.n_active, 5))
        for phase, center in enumerate(self.centers):
            x = Dual(center, zero)
            equity = self._hx.equity(x)
            hit, discounted_hit = self._hx.first_hit(x, self._hx.m)
            debt = self._hx.c / self._hx.R + self._hx.discount * self._hx.q * (1 - hit)
            debt += (self._hx.alpha * self._hx.b / self._hx.m - self._hx.c / self._hx.R) * discounted_hit
            values = [self._hx.b, equity, hit, discounted_hit, debt]
            self.financial_values[phase] = [v.v for v in values]
            self.dfinancial_values[:, phase] = np.stack([v.g for v in values], axis=1)
            if equity.v < 0 or not np.isfinite([v.v for v in values]).all():
                raise ValueError("Full HX state values are outside the admitted finite domain")
            bonus = .05 * equity / (parameter_duals[8] + equity)
            deficit = self._hx.p - debt
            if deficit.v == 0:
                raise ValueError("READ positive-part cost is at a nondifferentiable kink")
            positive_deficit = deficit if deficit.v > 0 else Dual(0., zero)
            cost = .03 + .03 * positive_deficit / self._hx.p
            for bit in (0, 1):
                state = 2 * phase + bit
                self.reward[state] += bonus.v
                self.dreward[:, state, :] = bonus.g[:, None]
                self.read_cost[state] = cost.v
                self.dread_cost[:, state] = cost.g
        for value in (self.Q, self.dQ, self.E, self.reward, self.dreward,
                      self.read_cost, self.dread_cost, self.dprior):
            if not np.isfinite(value).all():
                raise ValueError("Nonfinite cell value or derivative")
        self._transition_cache = {}
        self._gradient_cache = {}

    def _check_generator(self):
        off_diagonal = self.Q.copy()
        np.fill_diagonal(off_diagonal, 0.)
        if np.any(off_diagonal < 0) or not np.allclose(self.Q.sum(1), 0, rtol=0, atol=2e-13):
            raise ValueError("Invalid conservative row generator")
        if not np.allclose(self.dQ.sum(2), 0, rtol=0, atol=1e-11):
            raise ValueError("Generator derivative violates mass conservation")

    def _belief(self, belief):
        p = np.asarray(belief, dtype=np.float64)
        if p.ndim < 1 or p.shape[-1] != self.state_count or not np.isfinite(p).all():
            raise ValueError("Belief must be finite with final dimension 20")
        if np.any(p < -1e-13) or not np.allclose(p.sum(axis=-1), 1., rtol=0, atol=2e-11):
            raise ValueError("Belief must be a normalized nonnegative distribution")
        return p

    @staticmethod
    def _duration(dt):
        dt = float(dt)
        if not np.isfinite(dt) or dt < 0:
            raise ValueError("Duration must be finite and nonnegative")
        return dt

    def transition(self, dt, with_grad=False):
        """Return exp(dt Q), optionally with its three physical derivatives.

        Fixed parameter values define the state coordinates. Changing a fitted
        model requires rebuilding/replaying its history; this API does not
        silently relabel a retained belief under a new moving boundary.
        """
        dt = self._duration(dt)
        if dt not in self._transition_cache:
            self._transition_cache[dt] = expm(dt * self.Q)
        transition = self._transition_cache[dt]
        if not with_grad:
            return transition
        if dt not in self._gradient_cache:
            self._gradient_cache[dt] = np.stack([
                expm_frechet(dt * self.Q, dt * direction, compute_expm=False)
                for direction in self.dQ
            ])
        return transition, self._gradient_cache[dt]

    def predict(self, belief, dt):
        return self._belief(belief) @ self.transition(dt)

    def observe(self, belief, token, return_likelihood=False):
        """Bayes update on one available token; None is a missing observation."""
        p = self._belief(belief)
        if token is None:
            return (p.copy(), np.ones(p.shape[:-1])) if return_likelihood else p.copy()
        tokens = np.asarray(token)
        if not np.issubdtype(tokens.dtype, np.integer) or np.any(tokens < 0) or np.any(tokens >= 7):
            raise ValueError("Observed token must be an integer from zero to six")
        if tokens.ndim and tokens.shape != p.shape[:-1]:
            raise ValueError("Batched tokens must match the belief batch dimensions")
        likelihood = self.E[:, tokens] if not tokens.ndim else np.moveaxis(self.E[:, tokens], 0, -1)
        weighted = p * likelihood
        evidence = weighted.sum(axis=-1)
        if np.any(evidence <= 0) or not np.isfinite(evidence).all():
            raise ValueError("Observed token has zero probability under this causal belief")
        posterior = weighted / evidence[..., None]
        return (posterior, evidence) if return_likelihood else posterior

    def observe_with_grad(self, belief, belief_gradient, token):
        """Forward Bayes derivative for [3 physics, 12 emission] parameters.

        ``belief_gradient`` has shape (15,20). The result is (posterior,
        posterior_gradient, evidence, evidence_gradient). This scalar-prefix
        helper shares the exact update with inference; callers may batch it.
        """
        p = self._belief(belief)
        dp = np.asarray(belief_gradient, dtype=float)
        if p.ndim != 1 or dp.shape != (self.parameter_count, self.state_count) or not np.isfinite(dp).all():
            raise ValueError("Expected scalar belief and a finite (15,20) gradient")
        if token is None:
            return p.copy(), dp.copy(), 1., np.zeros(self.parameter_count)
        posterior, evidence = self.observe(p, token, return_likelihood=True)
        likelihood = self.E[:, token]
        dlikelihood = np.zeros((self.parameter_count, self.state_count))
        dlikelihood[3:] = self.dE_logits[:, :, token]
        weighted_derivative = dp * likelihood + p * dlikelihood
        evidence_gradient = weighted_derivative.sum(axis=1)
        gradient = (weighted_derivative - evidence_gradient[:, None] * posterior) / evidence
        return posterior, gradient, float(evidence), evidence_gradient

    def reset(self, belief):
        """Explicit action reset: restart recovery phase zero, preserving bit."""
        return self._belief(belief) @ self.R

    def expected_events(self, belief, dt, with_grad=False):
        """Expected *count* of natural absorptions, including repeated events.

        This is not a probability and is not clamped to one. An explicit RESET
        action is not counted as a natural absorption.
        """
        p, dt = self._belief(belief), self._duration(dt)
        size = self.state_count
        augmented = np.zeros((size + 1, size + 1))
        augmented[:size, :size] = self.Q
        augmented[:size, size] = self.event_rate
        result = expm(dt * augmented)[:size, size]
        count = p @ result
        if not with_grad:
            return count
        directions = np.zeros((3, size + 1, size + 1))
        directions[:, :size, :size] = self.dQ
        directions[:, :size, size] = self.devent_rate
        derivatives = np.stack([
            p @ expm_frechet(dt * augmented, dt * d, compute_expm=False)[:size, size]
            for d in directions
        ])
        return count, derivatives

    def survivor_generator(self):
        """Killed row generator for no *future* natural absorption.

        Removing only event destinations while retaining their diagonal loss
        keeps no-hit mass. Existing recovery phases may finish and re-enter
        activity; a later natural hit then kills the path.
        """
        killed = self.Q.copy()
        for bit in (0, 1):
            killed[bit, 2 * self.n_active + bit] = 0.
        return killed

    def surviving_state(self, belief, dt, conditional=False):
        p = self._belief(belief) @ expm(self._duration(dt) * self.survivor_generator())
        mass = p.sum(axis=-1)
        if conditional:
            if np.any(mass <= 0):
                raise ValueError("Conditional survival has no representable positive mass")
            return p / mass[..., None], mass
        return p, mass

    def first_event_probability(self, belief, dt):
        """Positive killed-boundary flux; distinct from repeated event count.

        Accumulating the lost mass avoids subtracting nearly equal numbers in
        ``1 - survival`` when the first-hit probability is very small.
        """
        p, dt = self._belief(belief), self._duration(dt)
        size = self.state_count
        augmented = np.zeros((size + 1, size + 1))
        augmented[:size, :size] = self.survivor_generator()
        augmented[:size, size] = self.event_rate
        return p @ expm(dt * augmented)[:size, size]

    def parameters(self):
        return np.concatenate((self.theta, self.emission_logits.ravel()))

    def parameter_jacobians(self):
        """Full leading-15 Jacobians for generic training implementations."""
        def padded(derivative):
            return np.concatenate((derivative, np.zeros((12, *derivative.shape[1:]))), axis=0)
        return dict(Q=padded(self.dQ), E=np.concatenate((self.dE, self.dE_logits)),
                    reward=padded(self.dreward), read_cost=padded(self.dread_cost),
                    prior=padded(self.dprior), R=np.zeros((15, self.state_count, self.state_count)))
