"""Causal estimators with explicit, independently checkable first derivatives.

The HX estimator is an ordinary finite-state Bayesian filter parameterized by
the full financial kernel. Its structural HMM equality is intentional.
"""

import numpy as np
from scipy.special import expit, xlogy

from .cell import Cell

PHYSICAL_LOWER = np.array([.15, .002, .5])
PHYSICAL_UPPER = np.array([.4, .04, 2.])


def loss_and_logit_gradient(probabilities, teacher, labels):
    """Joint posterior CE + .25 current-label CE; derivative w.r.t. logits."""
    p = probabilities
    bit_mask = (np.arange(20) % 2)[None, None, :] == labels[..., None]
    label_probability = np.sum(p * bit_mask, axis=-1, keepdims=True)
    if np.any(label_probability <= 0):
        raise FloatingPointError("Zero current-label probability")
    loss = posterior_ce(p, teacher)
    loss -= .25 * np.mean(np.log(label_probability))
    gradient = p - teacher + .25 * (p - p * bit_mask / label_probability)
    gradient /= np.prod(p.shape[:2])
    return float(loss), gradient


def posterior_ce(probabilities, teacher):
    if (not np.isfinite(probabilities).all() or not np.isfinite(teacher).all()
            or np.any(probabilities < 0) or np.any(teacher < 0)
            or not np.allclose(probabilities.sum(axis=-1), 1., atol=1e-10)
            or not np.allclose(teacher.sum(axis=-1), 1., atol=1e-10)):
        raise ValueError("Loss requires finite normalized nonnegative distributions")
    if np.any((teacher > 0) & (probabilities <= 0)):
        raise FloatingPointError("Teacher support is impossible under the fitted model")
    return float(-np.mean(np.sum(xlogy(teacher, probabilities), axis=-1)))


class HXFilter:
    kind = "hx_distribution"

    def __init__(self, seed=0, parameters=None):
        rng = np.random.default_rng(seed)
        initial = np.array([.27, .016, 1.15])
        fraction = (initial - PHYSICAL_LOWER) / (PHYSICAL_UPPER - PHYSICAL_LOWER)
        raw = np.log(fraction / (1 - fraction)) + rng.normal(0, .05, 3)
        self.params = {"physical_raw": raw, "emission_logits": rng.normal(0, .05, (2, 6))}
        if parameters is not None:
            self.params = {k: np.array(v, dtype=float) for k, v in parameters.items()}
        self.cell = None
        self.current = None

    def build_cell(self):
        fraction = expit(self.params["physical_raw"])
        theta = PHYSICAL_LOWER + (PHYSICAL_UPPER - PHYSICAL_LOWER) * fraction
        self.cell = Cell(theta, self.params["emission_logits"])
        return self.cell

    def forward(self, inputs, gradients=False):
        cell = self.build_cell()
        batch, length = inputs.shape[:2]
        p = np.tile(cell.prior, (batch, 1))
        outputs = np.empty((batch, length, 20))
        if gradients:
            dp = np.tile(cell.parameter_jacobians()["prior"], (batch, 1, 1))
            derivatives = np.empty((batch, length, 15, 20))
            de = cell.parameter_jacobians()["E"]
        transitions = {float(dt): cell.transition(float(dt), with_grad=gradients)
                       for dt in np.unique(inputs[..., 8])}
        for t in range(length):
            x = inputs[:, t]
            reset = x[:, 9] > .5
            p[reset] = p[reset] @ cell.R
            if gradients:
                dp[reset] = dp[reset] @ cell.R
            previous = p.copy()
            if gradients:
                previous_dp = dp.copy()
            for dt, trans in transitions.items():
                selected = x[:, 8] == dt
                if not selected.any():
                    continue
                matrix = trans[0] if gradients else trans
                p[selected] = previous[selected] @ matrix
                if gradients:
                    dp[selected] = previous_dp[selected] @ matrix
                    dp[selected, :3] += np.einsum("bi,kij->bkj", previous[selected], trans[1])
            for token in range(7):
                selected = (x[:, 7] > .5) & (x[:, token] > .5)
                if not selected.any():
                    continue
                unnormalized = p[selected] * cell.E[:, token]
                total = unnormalized.sum(axis=-1, keepdims=True)
                if np.any(total <= 0):
                    raise FloatingPointError("Impossible observed symbol")
                if gradients:
                    du = (dp[selected] * cell.E[None, None, :, token]
                          + p[selected, None, :] * de[None, :, :, token])
                    dtotal = du.sum(axis=-1, keepdims=True)
                    dp[selected] = (du - unnormalized[:, None, :] * dtotal / total[:, None, :]) / total[:, None, :]
                p[selected] = unnormalized / total
            outputs[:, t] = p
            if gradients:
                derivatives[:, t] = dp
        return (outputs, derivatives) if gradients else outputs

    def loss_grad(self, inputs, teacher, labels):
        probabilities, dp = self.forward(inputs, gradients=True)
        loss, _ = loss_and_logit_gradient(probabilities, teacher, labels)
        mask = (np.arange(20) % 2)[None, None, :] == labels[..., None]
        label_probability = np.sum(probabilities * mask, axis=-1, keepdims=True)
        score = -np.divide(teacher, probabilities, out=np.zeros_like(teacher), where=probabilities > 0)
        score -= .25 * mask / label_probability
        gradient = np.einsum("bti,btki->k", score, dp) / np.prod(labels.shape)
        fraction = expit(self.params["physical_raw"])
        chain = (PHYSICAL_UPPER - PHYSICAL_LOWER) * fraction * (1 - fraction)
        return loss, {"physical_raw": gradient[:3] * chain, "emission_logits": gradient[3:].reshape(2, 6)}

    def start(self, prior=None):
        if self.cell is None:
            self.build_cell()
        self.current = self.cell.prior.copy() if prior is None else np.array(prior, copy=True)
        return self.current.copy()

    def step(self, inputs):
        if self.current is None:
            self.start()
        x = np.asarray(inputs)
        if x[9] > .5:
            self.current = self.current @ self.cell.R
        self.current = self.current @ self.cell.transition(float(x[8]))
        if x[7] > .5:
            self.current = self.cell.observe(self.current, int(np.argmax(x[:7])))
        return self.current.copy()

    def export(self):
        return {"kind": self.kind, "parameters": {k: v.tolist() for k, v in self.params.items()},
                "parameter_count": sum(v.size for v in self.params.values())}


def restore_model(payload):
    if payload["kind"] == "hx_distribution":
        return HXFilter(parameters=payload["parameters"])
    from .recurrent import RecurrentEstimator
    return RecurrentEstimator(payload["kind"], parameters=payload["parameters"])
