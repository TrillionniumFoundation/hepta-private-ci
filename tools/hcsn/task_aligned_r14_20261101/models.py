"""Causal R14 estimators with full sequence derivatives and a common task loss.

The ordinary models receive only raw history. HX and generic HMM carry explicit
finite joint beliefs. The common planner is supplied separately and is frozen.
Initial-state computation is identical in forward(), start(), and execution.
"""

import numpy as np
from scipy.special import expit, softmax, xlogy

from ..unified_cell_r12_20261031.cell import Cell, PHYSICAL_LOWER, PHYSICAL_UPPER
from .task import TaskModel


ORDINARY_KINDS = ("gru", "continuous_ssm", "dual_head", "matched_slope")
PARAMETERS = np.r_[0:2, 3:15]


def task_loss(probabilities, teacher, alpha=None, legal=None, ce_weight=1., q_weight=0.):
    """Posterior CE plus actual frozen-policy Q-pi squared error.

    ``legal`` may be a Boolean mask or nonnegative cost-sensitive action weights.
    Alpha is a stop-gradient state/action return vector produced by the task
    owner, using the frozen deployed continuation policy. Targets and alpha are
    training-only; neither is an actor feature or a planner replacement.
    """
    p, target = probabilities, teacher
    if ce_weight and np.any((target > 0) & (p <= 0)):
        raise FloatingPointError("Target has support outside the estimator")
    count = np.prod(p.shape[:-1])
    loss = -ce_weight * np.sum(xlogy(target, p)) / count if ce_weight else 0.
    score = (-ce_weight * np.divide(target, p, out=np.zeros_like(p), where=p > 0) / count
             if ce_weight else np.zeros_like(p))
    if alpha is not None and q_weight:
        error = np.einsum("...s,...as->...a", p - target, alpha)
        weight = np.asarray(legal, dtype=float)
        denominator = float(weight.sum())
        if denominator <= 0:
            raise ValueError("Q-pi training needs a legal first action")
        loss += q_weight * np.sum(weight * error * error) / denominator
        score += 2 * q_weight * np.einsum("...a,...as->...s", weight * error, alpha) / denominator
    return float(loss), score


class HXEstimator:
    kind = "hx_distribution"

    def __init__(self, seed=0, parameters=None, profile="repairable"):
        rng = np.random.default_rng(seed)
        fraction = (np.array([.27, .016]) - PHYSICAL_LOWER[:2]) / (PHYSICAL_UPPER[:2] - PHYSICAL_LOWER[:2])
        self.params = dict(physical_raw=np.log(fraction / (1 - fraction)) + rng.normal(0, .03, 2),
                           emission_logits=rng.normal(0, .03, (2, 6)))
        if parameters is not None:
            self.params = {k: np.array(v, dtype=float) for k, v in parameters.items()}
        self.profile = profile
        self.cell = None
        self._built_parameters = None
        self.current = None

    def build_cell(self):
        theta = PHYSICAL_LOWER[:2] + (PHYSICAL_UPPER[:2] - PHYSICAL_LOWER[:2]) * expit(self.params["physical_raw"])
        logits = self.params["emission_logits"]
        self.cell = TaskModel(Cell([*theta, 1.3], logits - logits.mean(axis=1, keepdims=True)), self.profile)
        self._built_parameters = tuple(value.tobytes() for value in self.params.values())
        return self.cell

    def forward(self, inputs, gradients=False):
        cell = self.build_cell()
        batch, length = inputs.shape[:2]
        p = np.tile(cell.prior, (batch, 1))
        outputs = np.empty((batch, length, cell.state_count))
        if gradients:
            jac = cell.parameter_jacobians()
            dp = np.tile(jac["prior"][PARAMETERS], (batch, 1, 1))
            de = jac["E"][PARAMETERS]
            derivatives = np.empty((batch, length, len(PARAMETERS), cell.state_count))
        transitions = {float(dt): cell.transition(float(dt), with_grad=gradients)
                       for dt in np.unique(inputs[..., 9])}
        for t in range(length):
            x = inputs[:, t]
            reset = x[:, 10] > .5
            p[reset] = p[reset] @ cell.R
            if gradients:
                dp[reset] = dp[reset] @ cell.R
            previous = p.copy()
            previous_dp = dp.copy() if gradients else None
            for dt, transition in transitions.items():
                selected = x[:, 9] == dt
                if not selected.any():
                    continue
                matrix = transition[0] if gradients else transition
                p[selected] = previous[selected] @ matrix
                if gradients:
                    dp[selected] = previous_dp[selected] @ matrix
                    dp[selected, :2] += np.einsum("bi,kij->bkj", previous[selected], transition[1][:2])
            for token in range(8):
                selected = (x[:, 8] > .5) & (x[:, token] > .5)
                if not selected.any():
                    continue
                unnormalized = p[selected] * cell.E[:, token]
                total = unnormalized.sum(axis=-1, keepdims=True)
                if np.any(total <= 0):
                    raise FloatingPointError("Impossible observed symbol")
                if gradients:
                    du = dp[selected] * cell.E[None, None, :, token] + p[selected, None, :] * de[None, :, :, token]
                    dtotal = du.sum(axis=-1, keepdims=True)
                    dp[selected] = (du - unnormalized[:, None, :] * dtotal / total[:, None, :]) / total[:, None, :]
                p[selected] = unnormalized / total
            outputs[:, t] = p
            if gradients:
                derivatives[:, t] = dp
        return (outputs, derivatives) if gradients else outputs

    def loss_grad(self, inputs, teacher, alpha=None, legal=None, ce_weight=1., q_weight=0.):
        p, dp = self.forward(inputs, gradients=True)
        loss, score = task_loss(p, teacher, alpha, legal, ce_weight, q_weight)
        gradient = np.einsum("bti,btki->k", score, dp)
        fraction = expit(self.params["physical_raw"])
        chain = (PHYSICAL_UPPER[:2] - PHYSICAL_LOWER[:2]) * fraction * (1 - fraction)
        return loss, {"physical_raw": gradient[:2] * chain, "emission_logits": gradient[2:].reshape(2, 6)}

    def start(self):
        if self.cell is None or self._built_parameters != tuple(value.tobytes() for value in self.params.values()):
            self.build_cell()
        self.current = self.cell.prior.copy()
        return self.current.copy()

    def step(self, inputs):
        if self.current is None:
            self.start()
        x = np.asarray(inputs)
        if x[10] > .5:
            self.current = self.current @ self.cell.R
        self.current = self.current @ self.cell.transition(float(x[9]))
        if x[8] > .5:
            self.current *= self.cell.E[:, int(np.argmax(x[:8]))]
            mass = self.current.sum()
            if mass <= 0:
                raise FloatingPointError("Impossible observed symbol")
            self.current /= mass
        return self.current.copy()

    def export(self):
        return dict(kind=self.kind, profile=self.profile,
                    parameters={k: v.tolist() for k, v in self.params.items()},
                    parameter_count=sum(v.size for v in self.params.values()),
                    effective_parameter_count=12, fixed_maturity=1.3)


class RecurrentEstimator:
    """GRU, continuous gated SSM, factorized dual head, or matched-slope gate."""

    def __init__(self, kind, seed=0, parameters=None, gate_slope=1.):
        if kind not in ORDINARY_KINDS:
            raise ValueError(kind)
        self.kind = kind
        self.width = 24
        self.gate_slope = float(gate_slope)
        rng = np.random.default_rng(seed)
        random = lambda shape, scale: rng.normal(0, scale, shape)
        h = self.width
        outputs = 22 if kind == "dual_head" else 40
        self.params = dict(Wo=random((h, outputs), 1 / np.sqrt(h)), bo=np.zeros(outputs))
        if kind == "gru":
            for name in ("z", "r", "n"):
                self.params["W" + name] = random((11, h), .25)
                self.params["U" + name] = random((h, h), .12)
                self.params["b" + name] = np.zeros(h)
        else:
            self.params.update(Wu=random((11, h), .25), bu=np.zeros(h),
                               Wg=random((11, h), .25), bg=np.zeros(h), rate=random((h,), .2))
        if parameters is not None:
            self.params = {k: np.array(v, dtype=float) for k, v in parameters.items()}
        self.hidden, self.current = None, None

    def _advance(self, x, previous):
        p = self.params
        if self.kind == "gru":
            z = expit(x @ p["Wz"] + previous @ p["Uz"] + p["bz"])
            r = expit(x @ p["Wr"] + previous @ p["Ur"] + p["br"])
            n = np.tanh(x @ p["Wn"] + (r * previous) @ p["Un"] + p["bn"])
            return z * previous + (1 - z) * n, (x, previous, z, r, n)
        decay = np.exp(-x[:, 9:10] * np.logaddexp(0, p["rate"]))
        u = np.tanh(x @ p["Wu"] + p["bu"])
        slope = self.gate_slope if self.kind == "matched_slope" else 1.
        g = expit(slope * (x @ p["Wg"] + p["bg"]))
        return (1 - g) * decay * previous + g * u, (x, previous, decay, u, g, slope)

    def _output(self, hidden):
        logits = hidden @ self.params["Wo"] + self.params["bo"]
        if self.kind == "dual_head":
            phase = softmax(logits[:, :20], axis=-1)
            bit = softmax(logits[:, 20:], axis=-1)
            return (phase[:, :, None] * bit[:, None, :]).reshape(-1, 40)
        return softmax(logits, axis=-1)

    def forward(self, inputs, cache=False):
        batch, length = inputs.shape[:2]
        hidden = np.zeros((batch, self.width))
        probabilities, records = np.empty((batch, length, 40)), []
        for t in range(length):
            hidden, record = self._advance(inputs[:, t], hidden)
            probabilities[:, t] = self._output(hidden)
            if cache:
                records.append((hidden, record))
        return (probabilities, records) if cache else probabilities

    def loss_grad(self, inputs, teacher, alpha=None, legal=None, ce_weight=1., q_weight=0.):
        probabilities, records = self.forward(inputs, cache=True)
        loss, score = task_loss(probabilities, teacher, alpha, legal, ce_weight, q_weight)
        weighted = probabilities * score
        if self.kind == "dual_head":
            joint = probabilities.reshape(*probabilities.shape[:-1], 20, 2)
            weighted = weighted.reshape(*probabilities.shape[:-1], 20, 2)
            total = weighted.sum(axis=(-2, -1), keepdims=False)[..., None]
            output_gradient = np.concatenate((weighted.sum(-1) - joint.sum(-1) * total,
                                              weighted.sum(-2) - joint.sum(-2) * total), axis=-1)
        else:
            output_gradient = weighted - probabilities * weighted.sum(axis=-1, keepdims=True)
        p = self.params
        grads = {k: np.zeros_like(v) for k, v in p.items()}
        future = np.zeros((inputs.shape[0], self.width))
        for t in range(inputs.shape[1] - 1, -1, -1):
            hidden, record = records[t]
            out = output_gradient[:, t]
            grads["Wo"] += hidden.T @ out
            grads["bo"] += out.sum(axis=0)
            dh = future + out @ p["Wo"].T
            if self.kind == "gru":
                x, previous, z, r, n = record
                dz = dh * (previous - n) * z * (1 - z)
                dn = dh * (1 - z) * (1 - n * n)
                drh = dn @ p["Un"].T
                dr = drh * previous * r * (1 - r)
                future = dh * z + drh * r + dz @ p["Uz"].T + dr @ p["Ur"].T
                for name, derivative, recurrent_input in (("z", dz, previous), ("r", dr, previous), ("n", dn, r * previous)):
                    grads["W" + name] += x.T @ derivative
                    grads["U" + name] += recurrent_input.T @ derivative
                    grads["b" + name] += derivative.sum(axis=0)
            else:
                x, previous, decay, u, g, slope = record
                du = dh * g * (1 - u * u)
                dg = dh * (u - decay * previous) * g * (1 - g) * slope
                grads["rate"] += (dh * (1 - g) * previous * (-x[:, 9:10] * decay) * expit(p["rate"])).sum(axis=0)
                future = dh * (1 - g) * decay
                grads["Wu"] += x.T @ du
                grads["bu"] += du.sum(axis=0)
                grads["Wg"] += x.T @ dg
                grads["bg"] += dg.sum(axis=0)
        return loss, grads

    def start(self):
        self.hidden, _ = self._advance(np.zeros((1, 11)), np.zeros((1, self.width)))
        self.current = self._output(self.hidden)[0]
        return self.current.copy()

    def step(self, inputs):
        if self.hidden is None:
            self.start()
        self.hidden, _ = self._advance(np.asarray(inputs)[None, :], self.hidden)
        self.current = self._output(self.hidden)[0]
        return self.current.copy()

    def export(self):
        return dict(kind=self.kind, parameters={k: v.tolist() for k, v in self.params.items()},
                    parameter_count=sum(v.size for v in self.params.values()), gate_slope=self.gate_slope)


class GenericHMM:
    """Ordinary matrix CTMC/HMM with the same fitted model and information."""

    kind = "generic_hmm"

    def __init__(self, task):
        self.cell = task
        self.current = None

    def start(self):
        self.current = self.cell.prior.copy()
        return self.current.copy()

    step = HXEstimator.step

    def export(self):
        return dict(kind=self.kind, model_identity=self.cell.identity, parameter_count=0,
                    note="Shares the charged common calibrated matrix model; no private truth.")


def restore(payload):
    if payload["kind"] == "hx_distribution":
        return HXEstimator(parameters=payload["parameters"], profile=payload.get("profile", "repairable"))
    return RecurrentEstimator(payload["kind"], parameters=payload["parameters"], gate_slope=payload["gate_slope"])
