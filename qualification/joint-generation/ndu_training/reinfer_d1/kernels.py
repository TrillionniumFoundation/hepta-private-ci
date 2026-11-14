"""Bounded, charged read-only CE reference and request diagnostics."""

import numpy as np

from data import prepare_decoded_observer
from independent.accounting import WorkLedger
from independent.learning import CONTENT_PARAMETERS, setup_work
from model import softmax

DIMS = (202, 12, 192, 32)
ELEMENTS = 7288


def forward_work(n, h=32):
    return dict(
        macs=n * (202 * h + 2 * h * 12),
        scalar_ops=n * h + 70 * n,
        compare_ops=22 * n,
        exp_ops=24 * n,
        div_ops=24 * n,
        tanh_ops=n * h,
    )


def backward_work(n, h=32):
    return dict(
        macs=n * (202 * h + 4 * h * 12), scalar_ops=4 * n * h + (n - 1) * (h + 24)
    )


def pullback_work(n, h=32, weighted=True):
    return dict(
        macs=n * (202 * h + 2 * h * 12),
        scalar_ops=n * (h + 24) + (n - 1) * (h + 24),
        div_ops=n if weighted else 1,
    )


def price(work):
    return WorkLedger("quote").estimate_kernel(**work)


def flat(values):
    return np.concatenate([values[key].ravel() for key in CONTENT_PARAMETERS])


class Reference:
    def __init__(self, model, x, labels, ledger):
        self.x, self.y, self.model = x, labels, model
        n, h = len(x), model.dimensions[3]
        ledger.charge_kernel("reference", "cache_forward", **forward_work(n, h))
        self.h = np.tanh(x @ model.params["encoder"] + model.params["bias"])
        self.p = softmax(self.h @ model.params["text"] + model.params["text_bias"])
        self.q = softmax(self.h @ model.params["image"] + model.params["image_bias"])
        ledger.charge_kernel(
            "reference", "cache_ce_derivative", scalar_ops=2 * n + 24 * n
        )
        self.dt, self.di = self.p.copy(), self.q.copy()
        self.dt[np.arange(n), labels] -= 1
        self.di[np.arange(n), labels] -= 1
        self.dt *= 0.5
        self.di *= 0.5
        ledger.charge_kernel(
            "reference", "cache_hidden_pullback", macs=24 * n * h, scalar_ops=4 * n * h
        )
        self.dh = (
            self.dt @ model.params["text"].T + self.di @ model.params["image"].T
        ) * (1 - self.h * self.h)
        self.mean = self.pull(np.arange(n), None, ledger, "reference")
        # Independent public dense route, with independently formed CE logits.
        ledger.charge_kernel("reference", "independent_forward", **forward_work(n, h))
        p, q = model.forward(x)
        ledger.charge_kernel(
            "reference", "independent_ce", scalar_ops=2 * n, div_ops=24 * n + 1
        )
        p[np.arange(n), labels] -= 1
        q[np.arange(n), labels] -= 1
        ledger.charge_kernel(
            "reference", "independent_gradient_forward", **forward_work(n, h)
        )
        ledger.charge_kernel("reference", "independent_backward", **backward_work(n, h))
        expected = model.gradients(x, p / (2 * n), q / (2 * n))
        self.mean_max_error = max(
            float(abs(self.mean[key] - expected[key]).max())
            for key in CONTENT_PARAMETERS
        )
        for key in CONTENT_PARAMETERS:
            np.testing.assert_allclose(
                self.mean[key], expected[key], rtol=1e-10, atol=1e-12
            )
        ledger.charge_kernel(
            "reference",
            "mean_validation",
            compare_ops=4 * sum(v.size for v in self.mean.values()),
        )
        ledger.charge_kernel(
            "reference", "decoded_reward", **setup_work(model.dimensions, "A")
        )
        observer = prepare_decoded_observer(model)
        self.reward, self.observations = observer.reward, observer.observations
        ledger.charge_kernel(
            "reference", "reward_exponential", scalar_ops=1728, exp_ops=1728
        )
        self.exponential_reward = np.exp(-1.5 * self.reward)
        for value in (self.h, self.p, self.q, self.dt, self.di, self.dh):
            value.flags.writeable = False

    def pull(self, indices, weights, ledger, stage):
        n = len(indices)
        ledger.charge_kernel(
            stage,
            "reference_cached_pullback",
            **pullback_work(n, self.h.shape[1], weights is not None),
        )
        factors = np.full(n, 1 / n) if weights is None else weights / n
        dh = self.dh[indices] * factors[:, None]
        dt, di = (
            self.dt[indices] * factors[:, None],
            self.di[indices] * factors[:, None],
        )
        h, x = self.h[indices], self.x[indices]
        return {
            "encoder": x.T @ dh,
            "bias": dh.sum(0),
            "text": h.T @ dt,
            "text_bias": dt.sum(0),
            "image": h.T @ di,
            "image_bias": di.sum(0),
        }

    def arrays(self):
        return {
            "hidden": self.h,
            "ce_dhidden": self.dh,
            "ce_dtext": self.dt,
            "ce_dimage": self.di,
            "p": self.p,
            "q": self.q,
            **{"mean_" + key: value for key, value in self.mean.items()},
        }


def request_readout(p, q, y, reference, ledger):
    n = len(y)
    ledger.charge_kernel(
        "readout",
        "request_reward_and_margins",
        macs=4 * n * 144,
        scalar_ops=400 * n,
        compare_ops=100 * n,
        div_ops=2 * n,
        log_ops=n,
    )
    rows = np.arange(n)
    text, image, _, distances = reference.observations
    np.testing.assert_array_equal(text, np.arange(12))
    np.testing.assert_array_equal(image, np.arange(12))
    pt, qi = p[rows, y], q[rows, y]
    joint, consistency = pt * qi, np.sum(p * q, axis=1)
    mse = np.sum(q * distances.T[y], axis=1)
    quality = np.sum(q * np.maximum(0, 1 - 4 * distances.T[y]), axis=1)
    components = np.column_stack(
        (0.3 * pt, 0.3 * qi, 0.3 * joint, 0.1 * quality, -0.35 * (1 - consistency))
    )
    reward = reference.reward[y]
    direct = np.einsum("ni,nij,nj->n", p, reward, q)
    np.testing.assert_allclose(direct, components.sum(1), rtol=1e-10, atol=1e-12)
    z = np.einsum("ni,nij,nj->n", p, reference.exponential_reward[y], q)
    negative_mass = np.einsum("ni,nij,nj->n", p, (reward < 0).astype(float), q)
    negative_reward = np.einsum("ni,nij,nj->n", p, np.where(reward < 0, reward, 0), q)
    gp, gq = p.argmax(1), q.argmax(1)
    pp, qq = p.copy(), q.copy()
    pp[rows, y], qq[rows, y] = -np.inf, -np.inf
    top_p, top_q = (
        np.partition(p, -2, axis=1)[:, -2:],
        np.partition(q, -2, axis=1)[:, -2:],
    )
    attrs = np.column_stack(
        (np.arange(12) // 4, (np.arange(12) // 2) % 2, np.arange(12) % 2)
    )
    return {
        "p": p,
        "q": q,
        "text_true_probability": pt,
        "image_true_probability": qi,
        "joint_success": joint,
        "consistency": consistency,
        "pixel_mse": mse,
        "task_utility": direct,
        "reward_components": components,
        "Z": z,
        "CE_rho": -np.log(z) / 1.5,
        "negative_reward_mass": negative_mass,
        "negative_reward_expectation": negative_reward,
        "text_true_margin": pt - pp.max(1),
        "image_true_margin": qi - qq.max(1),
        "text_top2_margin": top_p[:, 1] - top_p[:, 0],
        "image_top2_margin": top_q[:, 1] - top_q[:, 0],
        "greedy_text": gp.astype(np.uint8),
        "greedy_image": gq.astype(np.uint8),
        "greedy_joint_success": ((gp == y) & (gq == y)),
        "greedy_reward": reward[rows, gp, gq],
        "text_attribute_errors": attrs[gp] != attrs[y],
        "image_attribute_errors": attrs[gq] != attrs[y],
    }


def planned_units():
    n, b, draws = 6144, 64, 32
    reference = 3 * (
        3 * price(forward_work(n))
        + price(backward_work(n))
        + price(dict(macs=24 * n * 32, scalar_ops=4 * n * 32))
        + price(pullback_work(n))
        + price(dict(scalar_ops=26 * n + 2 * n, div_ops=24 * n + 1))
        + price(setup_work(DIMS, "N"))
        + 4 * ELEMENTS
    )
    # Unused head/optimizer kernels are absent. Detailed actual ledgers decide.
    from independent.learning import objective_work
    from ndu_training.estimators import weighted_work

    gradient = {
        arm: 6
        * draws
        * (
            price(forward_work(b))
            + price(backward_work(b))
            + price(objective_work(arm, b))
            + price(weighted_work(b))
            + price(pullback_work(b))
            + price(
                dict(
                    scalar_ops=25 * ELEMENTS,
                    div_ops=3 * ELEMENTS,
                    compare_ops=3 * ELEMENTS,
                )
            )
        )
        for arm in ("A", "N")
    }
    service = 6 * 4 * 3072 * 19236
    readout = 6 * price(
        dict(
            macs=5 * 3072 * 144,
            scalar_ops=400 * 3072,
            compare_ops=100 * 3072,
            div_ops=2 * 3072,
            log_ops=3072,
        )
    )
    return {
        "shared_reference_units_bound": reference,
        "gradient_units_bound": gradient,
        "service_units_each_arm": service,
        "readout_units_each_arm": readout,
        "total_each_arm": {
            arm: reference + gradient[arm] + service + readout for arm in ("A", "N")
        },
    }
