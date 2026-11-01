"""Piecewise-smooth full-coordinate derivative of the declared R15 finite law.

The continuum financial formula only parameterizes the reset boundary.  Its
reset interpolation is rejected at knots.  No clipping or finite difference
participates in this derivative API.  Coordinates need not be trained jointly.
"""

import numpy as np
from scipy.linalg import expm, expm_frechet
from scipy.special import softmax, expit, logit

from ..calibrated_operator_r11_20261031.numerics.kernel import Dual, FullHX, NAMES, exp, log
from ..unified_cell_r12_20261031.cell import BASE_THETA


NAMES = (*NAMES, "log_reset_asset", "log_recovery_mean", "logit_same_content",
         *[f"read_logit_{k}_{j}" for k in range(4) for j in range(4)],
         *[f"refresh_logit_{k}_{j}" for k in range(4) for j in range(4)],
         *[f"initial_logit_{j}" for j in range(4)])
P = len(NAMES)
BASE = np.r_[BASE_THETA, np.log(90.), np.log(.35), logit(.875),
             np.log(np.eye(4) * .6 + .1).ravel(),
             np.log(np.eye(4) * .96 + .01).ravel(), np.zeros(4)]
BASE[5] = .018  # R15 differs from R12's baseline liquidity.


class GradientLaw:
    """All 48 named coordinates, including emissions and initial distribution.

    Nine financial coordinates are natural units. Asset/recovery use logs;
    same-content uses a logit; categorical rows use unconstrained softmax logits.
    R15 itself fixes most coordinates. This is a separately named extension.
    """

    def __init__(self, coordinates=BASE):
        x = np.asarray(coordinates, dtype=float)
        if x.shape != (P,) or not np.isfinite(x).all():
            raise ValueError("Expected 48 finite coordinates")
        self.x = x.copy()
        basis, zero = np.eye(P), np.zeros(P)
        dual = [Dual(value, basis[j]) for j, value in enumerate(x)]
        hx = FullHX(dual[:9])
        centers, spacing = (np.arange(8) + .5) * .1, .1
        reset = log(exp(dual[9]) / hx.b)
        if not centers[0] < reset.v < centers[-1]:
            raise ValueError("Reset is outside represented interior")
        if np.min(abs(centers - reset.v)) <= 1e-9:
            raise ValueError("Reset interpolation knot has no unique derivative")
        lo = int(np.searchsorted(centers, reset.v) - 1)
        fraction = (reset - centers[lo]) / spacing
        weights, dw = np.zeros(8), np.zeros((P, 8))
        weights[lo:lo + 2] = [1 - fraction.v, fraction.v]
        dw[:, lo:lo + 2] = np.stack([-fraction.g, fraction.g], axis=1)
        sigma, r, delta = dual[2], dual[0], dual[1]
        diffusion = sigma * sigma / 2
        drift = r - delta - diffusion
        up = diffusion / spacing ** 2 + drift / (2 * spacing)
        down = diffusion / spacing ** 2 - drift / (2 * spacing)
        absorption = 2 * diffusion / spacing ** 2
        recovery = 2 / exp(dual[10])
        same_value = float(expit(x[11]))
        same = Dual(same_value, basis[11] * same_value * (1 - same_value))
        if min(up.v, down.v, absorption.v, recovery.v) <= 0 or not 0 < same.v < 1:
            raise ValueError("Unrepresentable positive rates or retention")
        q, dq = np.zeros((40, 40)), np.zeros((P, 40, 40))

        def edge(source, target, rate):
            q[source, target] += rate.v
            q[source, source] -= rate.v
            dq[:, source, target] += rate.g
            dq[:, source, source] -= rate.g

        for phase in range(8):
            for content in range(4):
                source = 4 * phase + content
                if phase < 7:
                    edge(source, source + 4, up)
                if phase:
                    edge(source, source - 4, down)
                else:
                    edge(source, 32 + content, absorption)
        for content in range(4):
            edge(32 + content, 36 + content, recovery)
            for phase in range(lo, lo + 2):
                weight = Dual(weights[phase], dw[:, phase])
                for destination in range(4):
                    keep = same if destination == content else (1 - same) / 3
                    edge(36 + content, 4 * phase + destination, recovery * weight * keep)
        self.Q, self.dQ = q, dq
        self.K, self.dK = q.copy(), dq.copy()
        self.rates, self.drates = np.zeros(40), np.zeros((P, 40))
        for content in range(4):
            self.rates[content] = q[content, 32 + content]
            self.drates[:, content] = dq[:, content, 32 + content]
            self.K[content, 32 + content] = 0
            self.dK[:, content, 32 + content] = 0
        self.E, self.dE = {}, {}
        for quality, start, columns in (("read", 12, 5), ("refresh", 28, 4)):
            rows = softmax(x[start:start + 16].reshape(4, 4), axis=1)
            if np.any(rows <= 0):
                raise ValueError("Emission positive support is unrepresentable")
            e, de = np.zeros((40, columns)), np.zeros((P, 40, columns))
            for content in range(4):
                states = np.arange(content, 32 if quality == "read" else 40, 4)
                e[states, :4] = rows[content]
                jac = np.diag(rows[content]) - np.outer(rows[content], rows[content])
                for j in range(4):
                    de[start + content * 4 + j, states, :4] = jac[:, j]
            if quality == "read":
                e[32:, 4] = 1
            self.E[quality], self.dE[quality] = e, de
        content = softmax(x[44:])
        jac = np.diag(content) - np.outer(content, content)
        phase = np.r_[weights, 0., 0.]
        dphase = np.c_[dw, np.zeros((P, 2))]
        self.prior = np.outer(phase, content).ravel()
        self.dprior = np.einsum("kp,c->kpc", dphase, content).reshape(P, 40)
        self.dprior[44:] += np.einsum("p,ck->kpc", phase, jac).reshape(4, 40)
        self.R = np.zeros((40, 40))
        self.R[np.arange(40), 32 + np.arange(40) % 4] = 1
        self.boundary, self.dboundary = float(hx.b.v), hx.b.g.copy()
        self.reset, self.dreset = float(reset.v), reset.g.copy()
        self.segment = lo
        if (not np.isfinite(dq).all() or np.max(abs(q.sum(1))) > 1e-11
                or np.max(abs(dq.sum(2))) > 1e-10):
            raise ValueError("Generator or tangent is not conservative")

    def operator(self, duration, killed=False, gradients=True):
        if not np.isfinite(duration) or duration < 0:
            raise ValueError("Duration must be finite and nonnegative")
        q, dq = (self.K, self.dK) if killed else (self.Q, self.dQ)
        value = expm(duration * q)
        if not gradients:
            return value
        derivative = np.zeros_like(dq)
        for j in np.flatnonzero(np.any(dq != 0, axis=(1, 2))):
            derivative[j] = expm_frechet(duration * q, duration * dq[j], compute_expm=False)
        return value, derivative

    def events(self, duration, first=False, gradients=True):
        q, dq = (self.K, self.dK) if first else (self.Q, self.dQ)
        a, da = np.zeros((41, 41)), np.zeros((P, 41, 41))
        a[:40, :40], a[:40, 40] = q, self.rates
        da[:, :40, :40], da[:, :40, 40] = dq, self.drates
        value = expm(duration * a)[:40, 40]
        if not gradients:
            return value
        derivative = np.zeros((P, 40))
        for j in np.flatnonzero(np.any(da != 0, axis=(1, 2))):
            derivative[j] = expm_frechet(duration * a, duration * da[j], compute_expm=False)[:40, 40]
        return value, derivative

    def evaluate(self, duration, token=0, quality="read", gradients=True):
        """Joint output includes complete reset successor and normalized Bayes.

        Conditional no-hit state is a normalized sublaw; full successor retains
        multiple events/recovery and the time after each event. Reset is an
        explicit action into recovery phase zero, followed by the full law.
        """
        if quality not in self.E or not isinstance(token, int) or not 0 <= token < self.E[quality].shape[1]:
            raise ValueError("Unknown observation")
        if not gradients:
            transition, killed = self.operator(duration, gradients=False), self.operator(duration, True, False)
            full, alive = self.prior @ transition, self.prior @ killed
            evidence = full @ self.E[quality][:, token]
            if evidence <= 0:
                raise ValueError("Observed token has zero likelihood")
            posterior = full * self.E[quality][:, token] / evidence
            return np.r_[full, alive, alive / alive.sum(),
                         self.prior @ self.events(duration, True, False),
                         self.prior @ self.events(duration, False, False),
                         evidence, posterior, self.prior @ self.R @ transition,
                         self.boundary, self.reset]
        transition, dtransition = self.operator(duration)
        killed, dkilled = self.operator(duration, True)
        first, dfirst = self.events(duration, True)
        count, dcount = self.events(duration)
        p, dp = self.prior, self.dprior
        full, alive = p @ transition, p @ killed
        dfull = dp @ transition + np.einsum("i,kij->kj", p, dtransition)
        dalive = dp @ killed + np.einsum("i,kij->kj", p, dkilled)
        survival, dsurvival = alive.sum(), dalive.sum(1)
        conditional = alive / survival
        dconditional = (dalive - dsurvival[:, None] * conditional) / survival
        e, de = self.E[quality][:, token], self.dE[quality][:, :, token]
        evidence, weighted = full @ e, full * e
        dweighted = dfull * e + full * de
        devidence = dweighted.sum(1)
        if evidence <= 0:
            raise ValueError("Observed token has zero likelihood")
        posterior = weighted / evidence
        dposterior = (dweighted - devidence[:, None] * posterior) / evidence
        reset = p @ self.R @ transition
        dreset = dp @ self.R @ transition + np.einsum("i,kij->kj", p @ self.R, dtransition)
        value = np.r_[full, alive, conditional, p @ first, p @ count, evidence, posterior, reset,
                      self.boundary, self.reset]
        derivative = np.c_[dfull, dalive, dconditional, dp @ first + dfirst @ p,
                           dp @ count + dcount @ p, devidence, dposterior, dreset,
                           self.dboundary, self.dreset]
        return value, derivative
