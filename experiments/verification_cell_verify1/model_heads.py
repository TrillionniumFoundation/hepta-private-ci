"""Actual fitted readout adapters over frozen MLX hidden states, not LoRA."""

import math

from .model_protocol import cases, digest, frozen_plan


def parameter_digest(head):
    """Identify fitted numerical parameters, excluding labels and provenance."""
    return digest({key: head[key] for key in ("mean", "scale", "coefficients", "bias")})


def fit_heads(rows, base_sha256):
    """Fit only the preregistered training trajectories; retain exact provenance."""
    import numpy as np
    expected = {case["goal"]["task_id"]: case["source_group"] for case in cases("train")}
    required = {"case_id", "source_group", "split", "tick", "feature", "feature_operation_id", "label", "label_operation_id", "evidence_sha256"}
    seen, dimensions, labels = set(), set(), {}
    for row in rows:
        if set(row) != required or row["split"] != "train" or expected.get(row["case_id"]) != row["source_group"]:
            raise ValueError("readout fit received an unregistered or non-training source")
        key = (row["case_id"], row["tick"])
        if type(row["tick"]) is not int or row["tick"] not in (0, 2, 3) or key in seen or type(row["label"]) is not bool:
            raise ValueError("invalid or duplicate training observation")
        if row["case_id"] in labels and labels[row["case_id"]] != row["label"]:
            raise ValueError("inconsistent terminal target across a trajectory")
        labels[row["case_id"]] = row["label"]
        seen.add(key)
        vector = row["feature"]
        if type(vector) is not list or not vector or any(type(x) not in (int, float) or not math.isfinite(x) for x in vector):
            raise ValueError("invalid frozen feature")
        dimensions.add(len(vector))
    if seen != {(case, tick) for case in expected for tick in (0, 2, 3)} or len(dimensions) != 1:
        raise ValueError("incomplete training panel or mismatched feature dimensions")
    matrix = np.asarray([row["feature"] for row in rows], dtype=np.float64)
    targets = np.asarray([row["label"] for row in rows], dtype=np.float64)
    mean = matrix.mean(axis=0)
    scale = matrix.std(axis=0)
    scale = np.where(scale > 1e-8, scale, 1.0) * math.sqrt(matrix.shape[1])
    matrix = (matrix - mean) / scale
    config = frozen_plan()["head_training"]
    heads = []
    identifiers = sorted(expected)
    for seed in config["seeds"]:
        generator = np.random.default_rng(seed)
        sampled = generator.choice(identifiers, size=len(identifiers), replace=True).tolist()
        weights = np.asarray([sampled.count(row["case_id"]) for row in rows], dtype=np.float64)
        coefficients = generator.normal(0, 0.001, size=matrix.shape[1])
        bias = 0.0
        # CPU logistic training changes actual readout weights; the LLM stays frozen.
        for _ in range(config["epochs"]):
            logits = np.clip(matrix @ coefficients + bias, -40, 40)
            probabilities = 1 / (1 + np.exp(-logits))
            residual = (probabilities - targets) * weights / weights.sum()
            gradient = matrix.T @ residual + config["l2"] * coefficients
            coefficients -= config["step_size"] * gradient
            bias -= config["step_size"] * residual.sum()
        logits = matrix @ coefficients + bias
        loss = float((weights * (np.logaddexp(0, logits) - targets * logits)).sum() / weights.sum())
        head = {"kind": "trained_frozen_feature_logistic_readout", "base_sha256": base_sha256,
                "seed": seed, "training_data_sha256": digest(rows), "training_source_groups": sorted(set(expected.values())),
                "training_case_ids": identifiers, "bootstrap_unit": "trajectory within training only", "bootstrap_case_ids": sampled,
                "epochs": config["epochs"], "step_size": config["step_size"], "l2": config["l2"],
                "normalization": "train-only standardization divided by sqrt(feature dimension)",
                "mean": mean.tolist(), "scale": scale.tolist(), "coefficients": coefficients.tolist(),
                "bias": float(bias), "training_weighted_log_loss": loss,
                "feature_count": matrix.shape[1], "base_weights_updated": False, "lora": False}
        if not math.isfinite(loss):
            raise ValueError("nonfinite fitted readout")
        head["parameters_sha256"] = parameter_digest(head)
        head["adapter_sha256"] = digest(head)
        heads.append(head)
    if len({parameter_digest(head) for head in heads}) != 3:
        raise ValueError("fitted readouts collapsed to identical numerical parameters")
    return heads


def head_score(head, feature, base_sha256):
    if head.get("kind") != "trained_frozen_feature_logistic_readout" or head["base_sha256"] != base_sha256:
        raise ValueError("readout base identity mismatch")
    if digest({key: value for key, value in head.items() if key != "adapter_sha256"}) != head["adapter_sha256"]:
        raise ValueError("readout digest mismatch")
    if len(feature) != head["feature_count"] or any(type(x) not in (int, float) or not math.isfinite(x) for x in feature):
        raise ValueError("invalid inference feature")
    logit = head["bias"] + sum((x - mean) / scale * coefficient for x, mean, scale, coefficient in zip(feature, head["mean"], head["scale"], head["coefficients"]))
    if not math.isfinite(logit):
        raise ValueError("nonfinite readout logit")
    return 1 / (1 + math.exp(-logit)) if logit >= 0 else math.exp(logit) / (1 + math.exp(logit))
