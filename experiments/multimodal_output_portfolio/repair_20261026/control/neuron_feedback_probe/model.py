"""Native state interface and a learned readout that cannot read scalar/target."""
import json
import subprocess

import numpy as np

from ...risk_feedback.model import certainty_equivalent, digest


Q = 1 << 24


class Native:
    def __init__(self, binary):
        self.process = subprocess.Popen([str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, bufsize=1)

    def tick_pair(self, case, feedback, readback_digest, reset=False):
        request = {"case": case, "feedback_q24": round(feedback * Q),
                   "readback_digest": readback_digest, "reset_before_readout": reset}
        self.process.stdin.write(json.dumps(request) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("Native probe stopped: " + self.process.stderr.read())
        result = json.loads(line)
        result["request"] = request
        ticks = result["ticks"]
        if len(ticks) != 2 or any(t["authority"] != "DENY_ALL" or not t["requires_calibration"] for t in ticks):
            raise ValueError("Invalid original native receipt")
        if ticks[1]["drive_q24"] != [0] * 10:
            raise ValueError("Second tick accidentally received fresh feedback")
        before = "0" * 64 if reset else ticks[0]["checkpoint_after"]
        if ticks[1]["checkpoint_before"] != before:
            raise ValueError("Native checkpoint chain disagrees with declared intervention")
        return result

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=10)
        if self.process.returncode:
            raise RuntimeError(self.process.stderr.read())


def features(receipt):
    last = receipt["ticks"][-1]
    return np.array([1.0] + [value / Q for key in ("activation_q24", "eligibility_q24")
                             for value in last[key]])


def fit_head(receipts, labels, protocol):
    inputs = np.stack([features(row) for row in receipts])
    labels = np.asarray(labels)
    weights = np.zeros(inputs.shape[1])
    before = digest(weights.tolist())
    initial = float(np.log(2))
    for _ in range(protocol["head_gradient_updates"]):
        logits = inputs @ weights
        predicted = 1 / (1 + np.exp(-logits))
        weights -= protocol["head_learning_rate"] * inputs.T @ (predicted - labels) / len(labels)
    logits = inputs @ weights
    return weights, {"model": "21-coefficient linear logistic readout of original neuron state",
        "gradient_updates": protocol["head_gradient_updates"], "initial_parameter_sha256": before,
        "final_parameter_sha256": digest(weights.tolist()), "initial_logloss": initial,
        "final_logloss": float(np.mean(np.logaddexp(0, logits) - labels * logits)),
        "training_classification_accuracy": float(np.mean((logits >= 0) == labels)),
        "native_kernel_parameters_trained": False, "train_feature_matrix_sha256": digest(inputs.tolist()),
        "labels_sha256": digest(labels.tolist()), "readout_has_scalar_or_private_target_input": False}


def decide(receipt, weights):
    score = float(features(receipt) @ weights)
    return ("repair" if score >= 0 else "stop"), score


def summarize(rows, protocol, gamma):
    grouped = {arm: sorted((row for row in rows if row["arm"] == arm), key=lambda row: row["case"])
               for arm in protocol["arms"]}
    arrays = {arm: np.array([row["net_return"] for row in records]) for arm, records in grouped.items()}
    statistics = {}
    for arm, records in grouped.items():
        values = arrays[arm]
        statistics[arm] = {"rows": len(records), "mean_net_return": float(values.mean()),
            "empirical_ce": float(certainty_equivalent(values, gamma)),
            "repair_count": sum(row["continuation"] == "repair" for row in records),
            "actual_output_bundles": sum(row["actual_output_bundles"] for row in records),
            "native_tick_count": 2 * len(records),
            "native_ns": sum(row["native_ns"] for row in records),
            "wall_ns": sum(row["wall_ns"] for row in records),
            "second_state_digest_differs_from_numeric": sum(a["native"]["ticks"][1]["temporal_digest"]
                != b["native"]["ticks"][1]["temporal_digest"] for a, b in zip(grouped["numeric"], records)),
            "action_disagreements_with_numeric": sum(a["continuation"] != b["continuation"]
                for a, b in zip(grouped["numeric"], records))}
    rng = np.random.default_rng(protocol["bootstrap_seed"])
    indices = rng.integers(len(grouped["numeric"]), size=(protocol["bootstrap_replicates"], len(grouped["numeric"])))
    tail = (1 - protocol["paired_interval"]) / 2
    comparisons = {}
    for arm in protocol["arms"][1:]:
        difference = arrays["numeric"] - arrays[arm]
        interval = np.quantile(difference[indices].mean(1), [tail, 1 - tail]).tolist()
        comparisons[arm] = {"metric": "mean_net_return", "difference": float(difference.mean()),
            "interval": interval, "prespecified_primary": arm in ("zero", "state_reset"),
            "positive_lower_bound": interval[0] > 0}
    return statistics, comparisons
