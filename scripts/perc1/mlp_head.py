"""Bounded stochastic acquisition training; development calibration is not a test.

Seeds drive real weight initialization and minibatch updates, unlike ridge labels.
Training receipts describe local computation, not independent execution attestation
or source independence. Every exported model remains advisory and HOLD.
"""

import platform
import time
from pathlib import Path

import numpy as np

from .acquisition import features, paired_label
from .schema import canonical, digest, exact, identifier, integer, real, require, sha

COST_SCALE = 1_000_000.0
MODULE_SHA256 = sha(Path(__file__).read_bytes())


def _arrays(parameters, shapes):
    exact(parameters, "w1 b1 w2 b2")
    result = {}
    for name, shape in shapes.items():
        values = parameters[name]
        require(
            type(values) is list and len(values) == shape[0], "invalid parameter shape"
        )
        if len(shape) == 2:
            require(
                all(type(row) is list and len(row) == shape[1] for row in values),
                "invalid parameter shape",
            )
            scalars = [v for row in values for v in row]
        else:
            scalars = values
        for value in scalars:
            real(value, -1e6, 1e6)
        result[name] = np.asarray(values, dtype=np.float64)
    return result


def train_head(
    train_pairs,
    dev_pairs,
    split_groups,
    *,
    feature_extractor_sha256,
    seed,
    steps=200,
    hidden=8,
    batch=32,
    learning_rate=0.02,
    momentum=0.9,
    cost_value=0.0,
    threshold=0.0,
):
    """Fit TRAIN with minibatch SGD/momentum; DEV only calibrates output bias."""
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    require(
        sha(Path(__file__).read_bytes()) == MODULE_SHA256,
        "training source changed; reload frozen module",
    )
    digest(feature_extractor_sha256)
    integer(seed)
    require(
        1 <= integer(steps) <= 2000
        and 1 <= integer(hidden) <= 64
        and 1 <= integer(batch) <= 128,
        "training budget exceeds bounds",
    )
    real(learning_rate, 1e-6, 1.0)
    real(momentum, 0, 0.99)
    real(cost_value, 0, 1e6)
    real(threshold, 0, 1)
    exact(split_groups, "train dev confirmation")
    groups = set()
    for values in split_groups.values():
        require(type(values) is list and values, "empty split registry")
        for group in values:
            require(identifier(group) not in groups, "source group crosses splits")
            groups.add(group)
    rows, labels, identities, solvers, captures, layout = [], [], set(), set(), {}, None
    for split, pairs in (("train", train_pairs), ("dev", dev_pairs)):
        require(type(pairs) is list and 0 < len(pairs) <= 10000, "invalid pair count")
        for pair in pairs:
            label = paired_label(pair)
            require(
                pair["split"] == split and pair["source_group"] in split_groups[split],
                "training/calibration split mismatch",
            )
            require(sha(pair) not in identities, "duplicate pair")
            identities.add(sha(pair))
            solvers.add(pair["without"]["solver_sha256"])
            for item in pair["with"]["evidence"]:
                capture = item["capture_sha256"]
                require(
                    capture not in captures or captures[capture] == split,
                    "captured content crosses splits",
                )
                captures[capture] = split
            current = [
                len(pair["features"][k]) for k in ("task_goal", "acquired_latent")
            ]
            layout = current if layout is None else layout
            require(current == layout, "feature layout changed")
            rows.append(features(pair["features"]))
            labels.append((label[0], label[1] / COST_SCALE))
    require(len(solvers) == 1, "continuation solver changed across training records")
    count = len(train_pairs)
    x, y = np.asarray(rows, dtype=np.float64), np.asarray(labels, dtype=np.float64)
    means, scales = x[:count].mean(axis=0), np.maximum(x[:count].std(axis=0), 1e-6)
    x = (x - means) / scales
    init_seed, order_seed = np.random.SeedSequence(seed).spawn(2)
    init, order = np.random.default_rng(init_seed), np.random.default_rng(order_seed)
    params = dict(
        w1=init.normal(0, (2 / x.shape[1]) ** 0.5, (x.shape[1], hidden)),
        b1=np.zeros(hidden),
        w2=init.normal(0, hidden**-0.5, (hidden, 2)),
        b2=np.zeros(2),
    )
    initial = {k: v.tolist() for k, v in params.items()}
    velocity = {k: np.zeros_like(v) for k, v in params.items()}
    trace = []
    for step in range(1, steps + 1):
        indices = order.choice(count, min(count, batch), replace=False)
        a = np.tanh(x[indices] @ params["w1"] + params["b1"])
        error = a @ params["w2"] + params["b2"] - y[indices]
        delta = error / len(
            indices
        )  # derivative of mean squared error over both outputs
        back = (delta @ params["w2"].T) * (1 - a * a)
        gradients = dict(
            w1=x[indices].T @ back,
            b1=back.sum(axis=0),
            w2=a.T @ delta,
            b2=delta.sum(axis=0),
        )
        norm = np.sqrt(sum(float((g * g).sum()) for g in gradients.values()))
        require(np.isfinite(norm), "nonfinite training gradient")
        for name in params:
            velocity[name] = momentum * velocity[name] + gradients[name] * min(
                1.0, 10 / max(norm, 1e-12)
            )
            params[name] -= learning_rate * velocity[name]
            require(np.isfinite(params[name]).all(), "nonfinite training parameter")
        trace.append(
            dict(
                step=step,
                batch_sha256=sha(indices.tolist()),
                loss=real(float((error * error).mean()), 0),
                parameters_sha256=sha({k: v.tolist() for k, v in params.items()}),
                optimizer_sha256=sha({k: v.tolist() for k, v in velocity.items()}),
            )
        )
    raw_dev = (
        np.tanh(x[count:] @ params["w1"] + params["b1"]) @ params["w2"] + params["b2"]
    )
    residual = y[count:] - raw_dev
    parameters = {k: v.tolist() for k, v in params.items()}
    receipt = dict(
        schema="perc1.acquisition-mlp-training.v1",
        algorithm="tanh_sgd_momentum_v1",
        seed=seed,
        steps=steps,
        hidden=hidden,
        batch=batch,
        learning_rate=learning_rate,
        momentum=momentum,
        independent_training_replicate=True,
        independence_scope="random initialization and minibatch stream; shared TRAIN/DEV sources",
        feature_extractor_sha256=feature_extractor_sha256,
        module_sha256=MODULE_SHA256,
        solver_sha256=next(iter(solvers)),
        train_pairs_sha256=sha(train_pairs),
        dev_pairs_sha256=sha(dev_pairs),
        split_registry_sha256=sha(split_groups),
        train_count=count,
        dev_count=len(dev_pairs),
        initial_parameters=initial,
        initial_parameters_sha256=sha(initial),
        final_parameters_sha256=sha(parameters),
        order_sha256=sha([r["batch_sha256"] for r in trace]),
        trace_sha256=sha(trace),
        trace=trace,
        runtime=dict(python=platform.python_version(), numpy=np.__version__),
        elapsed_ns=time.perf_counter_ns() - started,
        cpu_ns=time.process_time_ns() - cpu,
    )
    head = dict(
        schema="perc1.acquisition-mlp-head.v1",
        status="HOLD",
        scientific_qualified=False,
        layout=layout,
        means=means.tolist(),
        scales=scales.tolist(),
        parameters=parameters,
        calibration=dict(bias=residual.mean(axis=0).tolist()),
        cost_value=cost_value,
        threshold=threshold,
        training_receipt=receipt,
    )
    validate_head(head)
    require(
        sha(Path(__file__).read_bytes()) == MODULE_SHA256,
        "source changed during training",
    )
    return head


def validate_head(head):
    exact(
        head,
        "schema status scientific_qualified layout means scales parameters calibration cost_value threshold training_receipt",
    )
    require(
        head["schema"] == "perc1.acquisition-mlp-head.v1"
        and head["status"] == "HOLD"
        and head["scientific_qualified"] is False,
        "invalid head qualification",
    )
    layout = head["layout"]
    require(
        type(layout) is list
        and len(layout) == 2
        and 1 <= integer(layout[0]) <= 16
        and integer(layout[1]) <= 64,
        "invalid feature layout",
    )
    width = sum(layout) + 4
    for name in ("means", "scales"):
        require(
            type(head[name]) is list and len(head[name]) == width,
            "invalid normalization",
        )
        for value in head[name]:
            real(value, 1e-6 if name == "scales" else -1e100, 1e100)
    r = exact(
        head["training_receipt"],
        "schema algorithm seed steps hidden batch learning_rate momentum independent_training_replicate independence_scope feature_extractor_sha256 module_sha256 solver_sha256 train_pairs_sha256 dev_pairs_sha256 split_registry_sha256 train_count dev_count initial_parameters initial_parameters_sha256 final_parameters_sha256 order_sha256 trace_sha256 trace runtime elapsed_ns cpu_ns",
    )
    require(
        r["schema"] == "perc1.acquisition-mlp-training.v1"
        and r["algorithm"] == "tanh_sgd_momentum_v1"
        and r["independent_training_replicate"] is True
        and r["independence_scope"]
        == "random initialization and minibatch stream; shared TRAIN/DEV sources",
        "invalid training receipt",
    )
    integer(r["seed"])
    require(
        1 <= integer(r["steps"]) <= 2000
        and 1 <= integer(r["hidden"]) <= 64
        and 1 <= integer(r["batch"]) <= 128,
        "invalid training budget",
    )
    real(r["learning_rate"], 1e-6, 1)
    real(r["momentum"], 0, 0.99)
    require(
        1 <= integer(r["train_count"]) <= 10000
        and 1 <= integer(r["dev_count"]) <= 10000,
        "invalid training count",
    )
    for k in ("elapsed_ns", "cpu_ns"):
        integer(r[k])
    exact(r["runtime"], "python numpy")
    require(
        all(type(v) is str and 0 < len(v) <= 64 for v in r["runtime"].values()),
        "invalid runtime",
    )
    shapes = dict(
        w1=(width, r["hidden"]), b1=(r["hidden"],), w2=(r["hidden"], 2), b2=(2,)
    )
    for parameters in (head["parameters"], r["initial_parameters"]):
        _arrays(parameters, shapes)
    exact(head["calibration"], "bias")
    require(
        type(head["calibration"]["bias"]) is list
        and len(head["calibration"]["bias"]) == 2,
        "invalid calibration",
    )
    for value in head["calibration"]["bias"]:
        real(value, -1e100, 1e100)
    real(head["cost_value"], 0, 1e6)
    real(head["threshold"], 0, 1)
    for key, value in r.items():
        if key.endswith("sha256"):
            digest(value)
    trace = r["trace"]
    require(
        type(trace) is list and len(trace) == r["steps"], "incomplete optimizer trace"
    )
    for step, row in enumerate(trace, 1):
        exact(row, "step batch_sha256 loss parameters_sha256 optimizer_sha256")
        require(integer(row["step"]) == step, "optimizer step order changed")
        real(row["loss"], 0)
        for key in ("batch_sha256", "parameters_sha256", "optimizer_sha256"):
            digest(row[key])
    require(
        sha(r["initial_parameters"]) == r["initial_parameters_sha256"]
        and sha(head["parameters"])
        == r["final_parameters_sha256"]
        == trace[-1]["parameters_sha256"]
        and sha(trace) == r["trace_sha256"]
        and sha([row["batch_sha256"] for row in trace]) == r["order_sha256"],
        "training digest mismatch",
    )
    require(len(canonical(head)) <= 2 * 1024 * 1024, "head artifact exceeds bound")


def predict(head, public_features):
    validate_head(head)
    vector = features(public_features)
    require(
        [len(public_features[k]) for k in ("task_goal", "acquired_latent")]
        == head["layout"],
        "feature layout mismatch",
    )
    x = (np.asarray(vector) - head["means"]) / head["scales"]
    p = head["parameters"]
    raw = (
        np.tanh(x @ np.asarray(p["w1"]) + p["b1"]) @ np.asarray(p["w2"])
        + p["b2"]
        + head["calibration"]["bias"]
    )
    return dict(
        expected_gain=max(-1.0, min(1.0, real(float(raw[0])))),
        expected_cost=max(0.0, real(float(raw[1] * COST_SCALE))),
    )
