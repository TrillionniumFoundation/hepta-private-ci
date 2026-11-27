"""Action responses through actual Adam, with analytic Hessian-vector products.

The complete optimizer state supplies coefficients. These are local finite-window
response statistics, not an autonomous compact-state observer. No dense numerical
state Jacobian, held-out labels, or future realized observations are used.
"""

from dataclasses import dataclass
from decimal import Decimal
import time

import numpy as np

from cell_learning_metrics import probabilities
from cell_learning_models import normalize_features
from cell_field_state import dataset_digest


class HeadDerivative:
    """Gradient and symmetric Hessian products for the existing linear/gated head."""

    def __init__(self, head, x, y, l2=0.0):
        if head.mode not in ("linear", "gated"):
            raise ValueError("only the actual linear and gated heads are supported")
        self.head, self.x, self.l2 = head, normalize_features(x), l2
        self.names = tuple(sorted(head.params))
        self.sizes = [head.params[k].size for k in self.names]
        self.p = sum(self.sizes)
        labels = np.asarray(y)
        if (labels.shape != (len(self.x),) or labels.dtype.kind not in "iu"
                or np.any(labels < 0) or np.any(labels >= head.classes)
                or not np.isfinite(l2) or l2 < 0):
            raise ValueError("finite training objective and integer labels required")
        logits, (self.u, self.gate, _) = head._forward(self.x)
        self.prob = probabilities(logits)
        if np.any(self.prob[np.arange(len(labels)), labels] <= 1e-15):
            raise ValueError("reported NLL clipping invalidates its smooth response derivative")
        counts = np.bincount(labels, minlength=head.classes)
        weights = 1.0 / counts[labels]
        self.weights = weights / weights.sum()
        self.delta = self.prob.copy()
        self.delta[np.arange(len(labels)), labels] -= 1
        self.delta *= self.weights[:, None]
        self.loss, gradient = head.loss_gradients(self.x, labels, l2)
        self.gradient = np.concatenate([gradient[k].ravel() for k in self.names])
        if self.gate is not None:
            argument = self.x * head.a + head.g
            if np.any(np.abs(np.abs(argument) - 40) < 1e-10):
                raise ValueError("gate clip boundary is not differentiable")
            self.gate_prime = self.gate * (1 - self.gate) * (np.abs(argument) < 40)

    def hvp(self, vectors):
        """Apply the actual weighted-loss Hessian to one or several columns."""
        v = np.asarray(vectors, dtype=np.float64)
        one = v.ndim == 1
        v = v[:, None] if one else v
        if v.ndim != 2 or v.shape[0] != self.p or not np.isfinite(v).all():
            raise ValueError("finite parameter-shaped direction columns required")
        parts = np.split(v, np.cumsum(self.sizes)[:-1], axis=0)
        d = {k: part.reshape((*self.head.params[k].shape, v.shape[1]))
             for k, part in zip(self.names, parts)}
        x, head = self.x, self.head
        du = np.zeros((*self.u.shape, v.shape[1]))
        if self.gate is not None:
            argument_direction = x[:, :, None] * d["a"][None] + d["g"][None]
            du = x[:, :, None] * self.gate_prime[:, :, None] * argument_direction
        dz = (np.einsum("nwr,wc->ncr", du, head.W)
              + np.einsum("nw,wcr->ncr", self.u, d["W"]) + d["b"][None])
        dp = self.prob[:, :, None] * (dz - np.sum(self.prob[:, :, None] * dz, axis=1, keepdims=True))
        dd = dp * self.weights[:, None, None]
        out = {"W": np.einsum("nwr,nc->wcr", du, self.delta)
                    + np.einsum("nw,ncr->wcr", self.u, dd), "b": dd.sum(axis=0)}
        if self.gate is not None:
            upstream = self.delta @ head.W.T
            dupstream = (np.einsum("ncr,wc->nwr", dd, head.W)
                         + np.einsum("nc,wcr->nwr", self.delta, d["W"]))
            dprime = self.gate_prime[:, :, None] * (1 - 2 * self.gate[:, :, None]) * argument_direction
            term = x[:, :, None] * (dupstream * self.gate_prime[:, :, None]
                                      + upstream[:, :, None] * dprime)
            out.update(a=np.sum(term * x[:, :, None], axis=0), g=term.sum(axis=0))
        for name in self.names:
            if name not in ("b", "g"):
                out[name] += self.l2 * d[name]
        result = np.concatenate([out[k].reshape(self.sizes[i], -1)
                                 for i, k in enumerate(self.names)], axis=0)
        if not np.isfinite(result).all():
            raise ValueError("nonfinite Hessian product")
        return result[:, 0] if one else result


class AdamDerivative:
    """JVP/VJP of the exact existing post-gradient Adam transition."""

    def __init__(self, state, vector, step, train):
        self.p = state.parameter_count
        self.loss = HeadDerivative(state.head_from_vector(vector), *train, state.protocol["l2"])
        self.next = state.transition_vector(vector, step, *train)
        p, protocol = self.p, state.protocol
        self.b1, self.b2 = protocol["beta1"], protocol["beta2"]
        self.c1, self.c2 = (float(Decimal(1) - Decimal(str(b))) for b in (self.b1, self.b2))
        gradient = self.loss.gradient
        norm, limit = np.linalg.norm(gradient), protocol["gradient_clip"]
        if abs(norm - limit) <= 1e-10 * max(1., limit):
            raise ValueError("gradient clip boundary is not differentiable")
        self.clip = min(1., limit / max(norm, 1e-12))
        self.unit = gradient / norm if self.clip < 1 else None
        self.gradient = gradient * self.clip
        root = np.sqrt(self.next[2*p:] / (1 - self.b2**(step + 1)))
        mhat = self.next[p:2*p] / (1 - self.b1**(step + 1))
        self.dm = -protocol["learning_rate"] / (1 - self.b1**(step + 1)) / (root + protocol["epsilon"])
        self.dv = np.zeros(p)
        positive = root > 0
        if np.any((~positive) & (mhat != 0)):
            raise ValueError("nondifferentiable zero-variance Adam coordinate")
        self.dv[positive] = (protocol["learning_rate"] * mhat[positive]
            / (2 * (1 - self.b2**(step + 1)) * root[positive]
               * np.square(root[positive] + protocol["epsilon"])))

    def _columns(self, value):
        a = np.asarray(value, dtype=np.float64)
        one = a.ndim == 1
        a = a[:, None] if one else a
        if a.ndim != 2 or a.shape[0] != 3*self.p or not np.isfinite(a).all():
            raise ValueError("finite complete-state columns required")
        return a, one

    def _clip_product(self, value):
        if self.unit is None:
            return value
        return self.clip * (value - self.unit[:, None] * (self.unit @ value)[None])

    def jvp(self, vectors):
        a, one = self._columns(vectors)
        theta, m, v = np.split(a, 3)
        gradient = self._clip_product(self.loss.hvp(theta))
        nm = self.b1*m + self.c1*gradient
        nv = self.b2*v + 2*self.c2*self.gradient[:, None]*gradient
        result = np.vstack((theta + self.dm[:, None]*nm + self.dv[:, None]*nv, nm, nv))
        return result[:, 0] if one else result

    def vjp(self, vectors):
        a, one = self._columns(vectors)
        theta, m, v = np.split(a, 3)
        em, ev = m + self.dm[:, None]*theta, v + self.dv[:, None]*theta
        back = self.c1*em + 2*self.c2*self.gradient[:, None]*ev
        result = np.vstack((theta + self.loss.hvp(self._clip_product(back)), self.b1*em, self.b2*ev))
        return result[:, 0] if one else result


@dataclass
class Response:
    states: np.ndarray
    observations: np.ndarray
    gradients: np.ndarray
    transitions: list
    dt: float
    cpu_ns: int
    wall_ns: int

    def impulse_maps(self):
        """All H probe responses to one first-step impulse; no repeated projection."""
        h, p = len(self.transitions), self.gradients.shape[-1]
        sensitivity = np.vstack((self.dt*np.eye(p), np.zeros((2*p, p))))
        maps = np.zeros((h + 1, 2, p))
        for k in range(1, h + 1):
            maps[k] = self.gradients[k] @ sensitivity[:p]
            if k < h:
                sensitivity = self.transitions[k].jvp(sensitivity)
        return maps

    def terminal_sequence_maps(self):
        """Two terminal losses vs all H post-Adam interventions by one adjoint."""
        h, p = len(self.transitions), self.gradients.shape[-1]
        adjoint = np.vstack((self.gradients[-1].T, np.zeros((2*p, 2))))
        maps = np.zeros((h, 2, p))
        for k in range(h-1, -1, -1):
            maps[k] = self.dt * adjoint[:p].T
            adjoint = self.transitions[k].vjp(adjoint)
        return maps


def build_response(state, train, probes, *, horizon=8, dt=0.02):
    if (state.protocol["sampler"] != "full_batch" or state.step_count < 1
            or type(horizon) is not int or not 1 <= horizon <= 256
            or not 0 < dt <= 1 or len(probes) != 2):
        raise ValueError("warmed deterministic state and bounded declared horizon required")
    cpu, wall = time.process_time_ns(), time.perf_counter_ns()
    if state.contexts.get(state.active_context) != dataset_digest(*train):
        raise ValueError("response training bytes differ from the selected complete-state context")
    initial = state.digest()
    vectors, observations, gradients, transitions = [state.vector()], [], [], []
    for k in range(horizon + 1):
        head = state.head_from_vector(vectors[-1])
        rows = [HeadDerivative(head, *probe) for probe in probes]
        observations.append([row.loss for row in rows])
        gradients.append(np.vstack([row.gradient for row in rows]))
        if k < horizon:
            derivative = AdamDerivative(state, vectors[-1], state.step_count + k, train)
            transitions.append(derivative)
            vectors.append(derivative.next)
    if state.digest() != initial:
        raise RuntimeError("response construction mutated its origin")
    return Response(np.asarray(vectors), np.asarray(observations), np.asarray(gradients),
                    transitions, dt, time.process_time_ns()-cpu, time.perf_counter_ns()-wall)


def compress_response(maps, relative_tolerance=1e-8):
    """SVD input statistic sufficient to tolerance for these local response rows.

    All directions still exist. The retained coordinates describe the input action
    in this fixed local finite-window map; they do not reconstruct hidden state.
    """
    value = np.asarray(maps, dtype=np.float64)
    if value.ndim != 3 or not np.isfinite(value).all() or not 0 < relative_tolerance < 1:
        raise ValueError("finite response tensor and explicit relative tolerance required")
    matrix = value.reshape(-1, value.shape[-1])
    left, singular, right = np.linalg.svd(matrix, full_matrices=False)
    cutoff = relative_tolerance * singular[0] if len(singular) and singular[0] else 0.
    rank = int(np.count_nonzero(singular > cutoff))
    basis = right[:rank].T
    compressed = matrix @ basis
    residual = matrix - compressed @ basis.T
    return {"basis": basis, "coefficients": compressed.reshape(*value.shape[:-1], rank),
            "rank": rank, "singular_values": singular, "spectral_residual": float(np.linalg.norm(residual, 2)),
            "relative_tolerance": relative_tolerance,
            "scope": "fixed local action-response row space; complete state supplies coefficients"}
