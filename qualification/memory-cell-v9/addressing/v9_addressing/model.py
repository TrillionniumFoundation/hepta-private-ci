"""A joint reject class and six separately learned execution-compatibility heads."""

import time
import warnings

import numpy as np
from scipy.special import expit, softmax
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits

from addressing.contracts import OPERATIONS, digest
from addressing.model import IntentModel
from .capabilities import capability_violation
from .identity import policy_digest


LABELS = (*OPERATIONS, "reject")
SCORE_KIND = "joint intent and operation-conditioned compatibility minimum; not calibrated posterior"


class CompatibilityIntentModel(IntentModel):
    """Predict one executable operation only when its own verifier agrees.

    Each compatibility head sees all other valid operations and unsupported
    requests as negatives. Unlike a single supportedness score, this requires
    evidence for the exact proposed operation. No fitted text lookup is used.
    """

    def __init__(self, encoder, kind="hybrid", regularization=8.0):
        super().__init__(encoder, kind, regularization)
        self.policies = {operation: {"threshold": 1.01, "margin": 0.0} for operation in OPERATIONS}
        self.last_diagnostics = []

    def fit(self, rows, *, dense=None):
        if not 32 <= len(rows) <= 16_384:
            raise ValueError("bounded nontrivial training rows required")
        labels = [row["operation"] for row in rows]
        if set(labels) != set(LABELS):
            raise ValueError("all six operations and unsupported requests required")
        features = self.features([row["text"] for row in rows], fit=True, dense=dense)
        receipts, coefficients, intercepts = [], [], []
        targets = [("joint", labels, LABELS)] + [
            (operation, [int(label == operation) for label in labels], (0, 1)) for operation in OPERATIONS]
        for name, values, order in targets:
            started, cpu = time.perf_counter(), time.process_time()
            learner = LogisticRegression(C=self.regularization, class_weight="balanced", max_iter=2000,
                                         solver="lbfgs", random_state=9103, tol=1e-7)
            with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=1):
                warnings.simplefilter("always")
                learner.fit(features, values)
            if name == "joint":
                positions = [list(learner.classes_).index(label) for label in order]
                self.arrays["joint_coef"] = np.asarray(learner.coef_[positions], dtype=np.float64)
                self.arrays["joint_intercept"] = np.asarray(learner.intercept_[positions], dtype=np.float64)
            else:
                if list(learner.classes_) != [0, 1] or learner.coef_.shape[0] != 1:
                    raise ValueError("binary compatibility class convention differs")
                coefficients.append(learner.coef_[0])
                intercepts.append(learner.intercept_[0])
            receipts.append({"head": name, "actual_fit": True, "training_rows": len(values),
                             "positive_rows": sum(value == order[-1] for value in values) if name != "joint" else None,
                             "cpu_seconds": time.process_time() - cpu, "wall_seconds": time.perf_counter() - started,
                             "iterations": learner.n_iter_.tolist(), "warnings": [str(item.message) for item in caught]})
        self.arrays["compat_coef"] = np.asarray(coefficients, dtype=np.float64)
        self.arrays["compat_intercept"] = np.asarray(intercepts, dtype=np.float64)
        self.receipt = {"training_rows": len(rows), "training_sha256": digest(rows), "heads": receipts,
                        "base_updated": False, "blas_threads": 1, "actual_head_fits": len(targets),
                        "seed_interpretation": "deterministic optimization; not independent language replication"}
        return self.receipt

    def hypotheses(self, texts, *, dense=None):
        reasons = [capability_violation(value) for value in texts]
        eligible = [index for index, reason in enumerate(reasons) if reason is None]
        output = [{"raw_operation": "reject", "score": 1.0, "margin": 1.0,
                   "score_kind": "explicit registered-capability boundary", "capability_reason": reason}
                  for reason in reasons]
        self.last_diagnostics = [{"joint_scores": None, "compatibility_scores": None,
                                  "capability_reason": reason} for reason in reasons]
        if not eligible:
            return output
        learned, diagnostics = self._learned([texts[index] for index in eligible],
                                             dense=None if dense is None else np.asarray(dense)[eligible])
        for index, prediction, diagnostic in zip(eligible, learned, diagnostics):
            output[index], self.last_diagnostics[index] = prediction, diagnostic
        return output

    def learned_hypotheses(self, texts, *, dense=None):
        """Offline ablation of learned heads before explicit contract rejection.

        These are diagnostics, not a separate runtime serving entry point.
        Scoring them with the frozen policy cannot grant production admission.
        """
        output, self.last_diagnostics = self._learned(texts, dense=dense)
        return output

    def _learned(self, texts, *, dense=None):
        features = self.features(texts, dense=dense)
        joint = softmax(np.asarray(features @ self.arrays["joint_coef"].T) + self.arrays["joint_intercept"], axis=1)
        compatibility = expit(np.asarray(features @ self.arrays["compat_coef"].T) + self.arrays["compat_intercept"])
        output, diagnostics = [], []
        for probabilities, checks in zip(joint, compatibility):
            order = np.argsort(-probabilities, kind="stable")
            first, second = int(order[0]), int(order[1])
            score, margin = float(probabilities[first]), float(probabilities[first] - probabilities[second])
            if first < len(OPERATIONS):
                score = min(score, float(checks[first]))
                alternatives = np.delete(checks, first)
                margin = max(0.0, min(margin, float(checks[first] - alternatives.max()), 2 * float(checks[first]) - 1))
            output.append({"raw_operation": LABELS[first], "score": score, "margin": margin,
                           "score_kind": SCORE_KIND, "capability_reason": None})
            diagnostics.append({"joint_scores": dict(zip(LABELS, map(float, probabilities))),
                                "compatibility_scores": dict(zip(OPERATIONS, map(float, checks))),
                                "capability_reason": None})
        return output, diagnostics

    def decide(self, hypothesis):
        raw = hypothesis["raw_operation"]
        policy = self.policies.get(raw, {"threshold": 1.01, "margin": 0.0})
        accepted = raw in OPERATIONS and hypothesis["score"] >= policy["threshold"] and hypothesis["margin"] >= policy["margin"]
        # Diagnostics are retained separately; the executable host shape stays exact.
        return {**hypothesis, "operation": raw if accepted else None,
                "threshold": policy["threshold"], "required_margin": policy["margin"]}

    def save(self, directory):
        from .artifact import save
        return save(self, directory)

    @classmethod
    def load(cls, directory, encoder, expected_digest):
        from .artifact import load
        return load(cls, directory, encoder, expected_digest)
