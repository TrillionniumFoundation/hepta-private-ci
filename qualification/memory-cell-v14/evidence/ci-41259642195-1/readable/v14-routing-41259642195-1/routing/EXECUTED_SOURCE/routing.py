"""Calibrated sparse experts; fit data and serving inputs have separate APIs.

The experts choose existing operations. They do not learn the executors' algorithms.
Calibration changes group probabilities and conditional expert scores jointly;
serving still invokes only the selected experts. Gold routing is diagnostic only.
"""

import time

import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp


def matrix(value):
    value = np.asarray(value, dtype=np.float64)
    if value.ndim != 2 or not np.isfinite(value).all():
        raise ValueError("finite score matrix required")
    return value


def logits(expert, X):
    return matrix(expert.features(X) @ expert.params["W"] + expert.params["b"])


def partition_labels(partition):
    labels = sum([list(part) for part in partition], [])
    if not partition or any(not part for part in partition) or sorted(labels) != list(range(len(labels))):
        raise ValueError("partition must cover every class exactly once")
    return len(labels)


class RoutingCalibration:
    """Bounded temperatures and group biases, with an identity-centered penalty."""

    def __init__(self, partition):
        self.partition = [list(part) for part in partition]
        self.classes = partition_labels(self.partition)
        self.theta = np.zeros(1 + 2 * len(partition))
        self.receipt = {"status": "identity"}

    def route(self, scores):
        scores = matrix(scores)
        groups = len(self.partition)
        if scores.shape[1] != groups:
            raise ValueError("router width mismatch")
        bias = self.theta[1 + groups:]
        values = scores / np.exp(self.theta[0]) + bias - bias.mean()
        return values - logsumexp(values, axis=1, keepdims=True)

    def local(self, group, scores):
        scores = matrix(scores) / np.exp(self.theta[1 + group])
        return scores - logsumexp(scores, axis=1, keepdims=True)

    def fit(self, route_scores, expert_scores, labels, *, penalty=0.02):
        started = time.perf_counter()
        route_scores = matrix(route_scores)
        scores = [matrix(value) for value in expert_scores]
        labels = np.asarray(labels)
        groups = len(self.partition)
        if labels.ndim != 1 or not len(labels) or not np.issubdtype(labels.dtype, np.integer):
            raise ValueError("nonempty integer calibration labels required")
        if len(scores) != groups or route_scores.shape != (len(labels), groups):
            raise ValueError("calibration rows/groups mismatch")
        if any(value.shape != (len(labels), len(part)) for value, part in zip(scores, self.partition)):
            raise ValueError("expert rows/classes mismatch")
        if labels.min() < 0 or labels.max() >= self.classes or penalty <= 0:
            raise ValueError("invalid calibration labels or penalty")
        ownership = {label: (g, j) for g, part in enumerate(self.partition) for j, label in enumerate(part)}
        owner = np.array([ownership[int(label)][0] for label in labels])
        local = np.array([ownership[int(label)][1] for label in labels])

        def objective(theta):
            self.theta = theta
            likelihood = self.route(route_scores)[np.arange(len(labels)), owner].copy()
            for group, values in enumerate(scores):
                rows = np.flatnonzero(owner == group)
                likelihood[rows] += self.local(group, values)[rows, local[rows]]
            return float(-likelihood.mean() + penalty * np.dot(theta, theta))

        initial = objective(np.zeros_like(self.theta))
        result = minimize(objective, np.zeros_like(self.theta), method="L-BFGS-B",
                          bounds=[(-2.0, 2.0)] * len(self.theta), options={"maxiter": 120})
        # A failed optimizer cannot silently select its last trial parameters.
        accepted = bool(result.success and np.isfinite(result.fun) and result.fun <= initial)
        self.theta = result.x.copy() if accepted else np.zeros_like(self.theta)
        self.receipt = {"status": "fitted" if accepted else "identity_after_fit_failure",
                        "optimizer_success": bool(result.success), "message": str(result.message),
                        "initial_regularized_nll": initial, "final_regularized_nll": objective(self.theta),
                        "function_evaluations": int(result.nfev), "parameters": self.theta.tolist(),
                        "penalty": penalty, "seconds": time.perf_counter() - started,
                        "calibration_rows": len(labels), "expert_example_invocations": groups * len(labels)}
        return self.receipt


class CalibratedExperts:
    """A frozen sparse network plus calibration; inference does not receive labels."""

    def __init__(self, network, calibration=None):
        self.network = network
        self.calibration = calibration or RoutingCalibration(network.partition)
        if self.calibration.partition != network.partition:
            raise ValueError("calibration belongs to another partition")
        self.stats = {"requests": 0, "expert_example_invocations": 0}

    def fit(self, X, labels):
        route = np.column_stack([X, np.ones(len(X))]) @ self.network.router
        return self.calibration.fit(route, [logits(expert, X) for expert in self.network.experts], labels)

    def predict_proba(self, X):
        X = matrix(X)
        network = self.network
        route = self.calibration.route(np.column_stack([X, np.ones(len(X))]) @ network.router)
        chosen = np.argsort(-route, axis=1, kind="stable")[:, :network.top_k]
        result = np.full((len(X), network.num_classes), -np.inf)
        for group, (part, expert) in enumerate(zip(network.partition, network.experts)):
            rows = np.flatnonzero(np.any(chosen == group, axis=1))
            if len(rows):
                result[np.ix_(rows, part)] = self.calibration.local(group, logits(expert, X[rows])) + route[rows, group, None]
                self.stats["expert_example_invocations"] += len(rows)
        self.stats["requests"] += len(X)
        return np.exp(result - logsumexp(result, axis=1, keepdims=True))

    def predict(self, X):
        return self.predict_proba(X).argmax(axis=1)


def class_folds(labels, folds=4):
    labels = np.asarray(labels)
    result = np.empty(len(labels), dtype=np.int64)
    for label in np.unique(labels):
        rows = np.flatnonzero(labels == label)
        if len(rows) < folds:
            raise ValueError("each class needs every calibration fold")
        result[rows] = np.arange(len(rows)) % folds
    return result


def crossfit(network, X, labels):
    assignments = class_folds(labels)
    prediction = np.empty(len(labels), dtype=np.int64)
    receipts = []
    for fold in range(4):
        training, scoring = assignments != fold, assignments == fold
        model = CalibratedExperts(network)
        receipt = model.fit(X[training], labels[training])
        prediction[scoring] = model.predict(X[scoring])
        receipts.append({"fold": fold, **receipt})
    final = CalibratedExperts(network)
    receipts.append({"fold": "final_refit_all_calibration", **final.fit(X, labels)})
    return final, prediction, receipts


def choose_candidate(scores, numerical_bytes):
    """All controls participate; ties use declared storage, then stable name."""
    if not scores or scores.keys() != numerical_bytes.keys():
        raise ValueError("candidate score/cost inventory mismatch")
    return min(scores, key=lambda name: (-scores[name], numerical_bytes[name], name))


def route_diagnostics(model, X, labels, actual):
    """Gold labels are used after selection solely to localize errors."""
    network = model.network
    route = model.calibration.route(np.column_stack([X, np.ones(len(X))]) @ network.router)
    chosen = np.argsort(-route, axis=1, kind="stable")[:, :network.top_k]
    ownership = {label: (g, j) for g, part in enumerate(network.partition) for j, label in enumerate(part)}
    all_predictions = [expert.predict(X) for expert in network.experts]
    rows = []
    for i, label in enumerate(labels):
        group, local = ownership[int(label)]
        oracle = int(all_predictions[group][i]) == local
        rows.append({"true_group_in_top_k": bool(group in chosen[i]), "oracle_label_correct": bool(oracle),
                     "actual_label_correct": bool(actual[i] == label), "true_group": group,
                     "chosen_groups": chosen[i].tolist()})
    return {"gold_used_only_for_postselection_diagnostic": True, "rows": rows,
            "true_group_coverage": sum(r["true_group_in_top_k"] for r in rows),
            "oracle_label_correct": sum(r["oracle_label_correct"] for r in rows),
            "oracle_correct_missed_route": sum(r["oracle_label_correct"] and not r["actual_label_correct"] and not r["true_group_in_top_k"] for r in rows),
            "oracle_correct_present_but_misranked": sum(r["oracle_label_correct"] and not r["actual_label_correct"] and r["true_group_in_top_k"] for r in rows),
            "diagnostic_expert_example_invocations": len(X) * len(network.experts)}
