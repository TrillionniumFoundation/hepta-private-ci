"""One-step baselines from complete, chosen-action training observations.

Rows are caller-declared facts, not authenticated receipts. Unknown, cancelled,
and censored rows remain in the input commitment and exclusion accounting; they
are never zero labels. Complete-case fitting can be biased by observation policy.
The MLP's action-conditional empirical log residuals are marginal distributions,
not a joint law or a survival/missingness model. No historical PRED source or
finite simulator support is used here.
"""

from collections import Counter
from hashlib import sha256
import json
import math
import os
from pathlib import Path
from time import perf_counter, process_time

import numpy as np

SCHEMA = "pred1-observed-model-v1"
MAX_ROWS = 65536
MAX_ATOMS = 4096
MAX_CHECKPOINT_BYTES = 64 * 1024 * 1024
ROW_FIELDS = {
    "sample_id", "task_group", "split", "action_id", "features", "outcome_quality",
    "duration_seconds", "action_cost", "outcome_status", "time_status",
    "cost_status", "source",
}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _digest(value):
    return sha256(_canonical(value)).hexdigest()


def _names(values, maximum=256):
    _require(type(values) in (list, tuple) and 1 <= len(values) <= maximum,
             "invalid schema names")
    _require(all(type(x) is str and 0 < len(x) <= 512 for x in values),
             "invalid schema name")
    _require(len(set(values)) == len(values), "duplicate schema name")
    return list(values)


def _number(value):
    _require(type(value) in (int, float) and math.isfinite(value),
             "finite numerical value required")
    return float(value)


def _training_rows(rows, feature_names, action_ids):
    _require(type(rows) is list and 1 <= len(rows) <= MAX_ROWS, "invalid row count")
    ids, groups, selected, exclusions = set(), {}, [], Counter()
    sources, counts = Counter(), Counter()
    for row in rows:
        _require(type(row) is dict and ROW_FIELDS <= set(row), "incomplete row")
        _names([row["sample_id"]])
        _names([row["task_group"]])
        _require(row["sample_id"] not in ids, "duplicate sample identity")
        ids.add(row["sample_id"])
        group, split = row["task_group"], row["split"]
        _require(group not in groups or groups[group] == split, "group crosses splits")
        groups[group] = split
        _require(split == "train", "training accepts train rows only")
        _require(row["source"] in ("fixture", "declared_owner"), "unknown source")
        sources[row["source"]] += 1
        _require(row["action_id"] in action_ids, "action outside schema")
        features = row["features"]
        _require(type(features) is list and len(features) == len(feature_names),
                 "features must be one final observed row")
        for value in features:
            _number(value)
        outcome, timing, cost = row["outcome_status"], row["time_status"], row["cost_status"]
        _require(outcome in ("terminal", "unknown", "cancel_requested", "right_censored"),
                 "unknown outcome status")
        _require(timing in ("exact", "interval", "unobserved"), "unknown time status")
        _require(cost in ("observed", "unknown"), "unknown cost status")
        for key in ("outcome_quality", "duration_seconds", "action_cost"):
            if row[key] is not None:
                value = _number(row[key])
                _require(value in (0.0, 1.0) if key == "outcome_quality" else value >= 0,
                         "invalid observed target")
        reasons = []
        if outcome != "terminal":
            reasons.append("outcome_" + outcome)
        if timing != "exact":
            reasons.append("time_" + timing)
        if cost != "observed":
            reasons.append("cost_" + cost)
        if reasons:
            exclusions.update(reasons)
            continue
        _require(all(row[key] is not None for key in
                     ("outcome_quality", "duration_seconds", "action_cost")),
                 "complete statuses require actual target values")
        selected.append(row)
        counts[row["action_id"]] += 1
    _require(selected, "no complete-case chosen-action training observations")
    _require(max(counts.values()) <= MAX_ATOMS, "per-action empirical support limit")
    report = {
        "input_sha256": _digest(rows), "input_rows": len(rows),
        "complete_case_rows": len(selected), "excluded_rows": len(rows) - len(selected),
        "exclusion_reason_counts": dict(exclusions), "reason_counts_can_overlap": True,
        "task_groups": sorted(groups),
        "used_task_groups": sorted({row["task_group"] for row in selected}),
        "task_groups_sha256": _digest(sorted(groups)),
        "source_counts": dict(sources),
        "used_source_counts": dict(Counter(row["source"] for row in selected)),
        "action_counts": dict(counts),
        "selection": "terminal outcome, exact duration, observed action cost only",
        "provenance_authenticated": False, "missingness_bias_corrected": False,
    }
    return selected, report


def _distribution(values):
    atoms, counts = np.unique(np.asarray(values, dtype=np.float64), return_counts=True)
    _require(0 < len(atoms) <= MAX_ATOMS and np.isfinite(atoms).all()
             and (atoms >= 0).all(), "invalid predicted marginal")
    return atoms.tolist(), (counts / counts.sum()).tolist()


def _loss_grad(parameters, inputs, targets):
    hidden = np.tanh(inputs @ parameters["w1"] + parameters["b1"])
    output = hidden @ parameters["w2"] + parameters["b2"]
    probability = np.exp(-np.logaddexp(0.0, -output[:, 0]))
    error = output[:, 1:] - targets[:, 1:]
    loss = np.mean(np.logaddexp(0.0, output[:, 0]) - targets[:, 0] * output[:, 0]
                   + 0.5 * np.sum(error ** 2, axis=1))
    derivative = np.column_stack((probability - targets[:, 0], error)) / len(inputs)
    back = (derivative @ parameters["w2"].T) * (1.0 - hidden ** 2)
    gradients = {"w1": inputs.T @ back, "b1": back.sum(axis=0),
                 "w2": hidden.T @ derivative, "b2": derivative.sum(axis=0)}
    _require(np.isfinite(loss) and all(np.isfinite(x).all() for x in gradients.values()),
             "nonfinite loss or gradient")
    return float(loss), gradients


class ObservedModel:
    """Frozen-schema empirical or FP64 MLP marginal predictor; no action authority."""

    def _inputs(self, features, action_ids):
        values = np.asarray(features, dtype=np.float64)
        _require(values.shape == (len(action_ids), len(self.metadata["feature_names"]))
                 and np.isfinite(values).all(), "invalid feature matrix")
        columns = self.metadata["action_ids"]
        _require(all(action in self.metadata["training"]["action_counts"]
                     for action in action_ids), "action unavailable in complete-case training")
        one_hot = np.eye(len(columns), dtype=np.float64)[[columns.index(a) for a in action_ids]]
        with np.errstate(over="ignore", invalid="ignore"):
            encoded = np.concatenate(((values - self.center) / self.scale, one_hot), axis=1)
        _require(np.isfinite(encoded).all(), "nonfinite normalized features")
        return encoded

    def _output(self, inputs):
        p = self.parameters
        result = np.tanh(inputs @ p["w1"] + p["b1"]) @ p["w2"] + p["b2"]
        _require(np.isfinite(result).all(), "nonfinite model output")
        return result

    def predict(self, features, action_id):
        """Predict one supplied action; unseen actions fail instead of using pooled data."""
        _require(type(features) is list, "features must be one final observed row")
        _names([action_id])
        for value in features:
            _number(value)
        inputs = self._inputs([features], [action_id])
        if self.metadata["kind"] == "empirical":
            return json.loads(_canonical(self.empirical[action_id]))
        output = self._output(inputs)[0]
        with np.errstate(over="raise", invalid="raise"):
            try:
                samples = np.expm1(np.maximum(0.0, output[1:] + self.residuals[action_id]))
            except FloatingPointError as error:
                raise ValueError("nonfinite predicted marginal") from error
        duration, duration_p = _distribution(samples[:, 0])
        cost, cost_p = _distribution(samples[:, 1])
        return {"success_probability": float(np.exp(-np.logaddexp(0.0, -output[0]))),
                "duration_values": duration, "duration_probabilities": duration_p,
                "cost_values": cost, "cost_probabilities": cost_p}

    def _optimize(self, selected, epochs):
        _require(type(epochs) is int and 1 <= epochs <= 10000, "invalid epoch count")
        inputs = self._inputs([r["features"] for r in selected],
                              [r["action_id"] for r in selected])
        targets = np.array([[r["outcome_quality"], math.log1p(r["duration_seconds"]),
                             math.log1p(r["action_cost"])] for r in selected], dtype=np.float64)
        if self.loss_history:
            self.loss_history.pop()
        for _ in range(epochs):
            loss, gradients = _loss_grad(self.parameters, inputs, targets)
            self.loss_history.append(loss)
            self.step += 1
            for name, gradient in gradients.items():
                self.m[name] = 0.9 * self.m[name] + 0.1 * gradient
                self.v[name] = 0.999 * self.v[name] + 0.001 * gradient ** 2
                first = self.m[name] / (1 - 0.9 ** self.step)
                second = self.v[name] / (1 - 0.999 ** self.step)
                self.parameters[name] -= self.metadata["learning_rate"] * first / (np.sqrt(second) + 1e-8)
            _require(all(np.isfinite(v).all() for state in (self.parameters, self.m, self.v)
                         for v in state.values()), "nonfinite optimizer state")
        self.loss_history.append(_loss_grad(self.parameters, inputs, targets)[0])
        residual = targets[:, 1:] - self._output(inputs)[:, 1:]
        self.residuals = {action: residual[[r["action_id"] == action for r in selected]].copy()
                          for action in self.metadata["training"]["action_counts"]}
        self.metadata["optimizer_calls"] = self.step
        self.metadata["sample_presentations"] = self.step * len(selected)

    def continue_fit(self, rows, *, epochs):
        """Resume Adam only on the identical committed training records."""
        _require(self.metadata["kind"] == "mlp", "empirical model has no optimizer")
        started, cpu = perf_counter(), process_time()
        selected, report = _training_rows(rows, self.metadata["feature_names"],
                                           self.metadata["action_ids"])
        _require(report == self.metadata["training"], "resume training data identity differs")
        self._optimize(selected, epochs)
        self.metadata["fit_wall_seconds"] += perf_counter() - started
        self.metadata["fit_cpu_seconds"] += process_time() - cpu
        return self

    def save(self, path):
        """Create a bounded JSON checkpoint, including Adam and training identities."""
        payload = {"schema": SCHEMA, "metadata": self.metadata,
                   "center": self.center.tolist(), "scale": self.scale.tolist(),
                   "parameters": {k: v.tolist() for k, v in self.parameters.items()},
                   "optimizer": {"step": self.step, "m": {k: v.tolist() for k, v in self.m.items()},
                                 "v": {k: v.tolist() for k, v in self.v.items()}},
                   "residuals": {k: v.tolist() for k, v in self.residuals.items()},
                   "empirical": self.empirical, "loss_history": self.loss_history}
        encoded = _canonical({"payload": payload, "payload_sha256": _digest(payload)})
        _require(len(encoded) <= MAX_CHECKPOINT_BYTES, "checkpoint byte limit exceeded")
        with Path(path).open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        return sha256(encoded).hexdigest()

    @classmethod
    def load(cls, path, *, expected_sha256):
        """Load exact pinned bytes under the same source and NumPy version."""
        with Path(path).open("rb") as stream:
            encoded = stream.read(MAX_CHECKPOINT_BYTES + 1)
        _require(len(encoded) <= MAX_CHECKPOINT_BYTES and sha256(encoded).hexdigest() == expected_sha256,
                 "checkpoint size or SHA256 differs")
        envelope = json.loads(encoded)
        _require(type(envelope) is dict and set(envelope) == {"payload", "payload_sha256"},
                 "invalid checkpoint envelope")
        p = envelope["payload"]
        _require(_digest(p) == envelope["payload_sha256"] and p["schema"] == SCHEMA,
                 "checkpoint payload differs")
        model = cls()
        model.metadata = p["metadata"]
        meta = model.metadata
        _require(meta["source_sha256"] == sha256(Path(__file__).read_bytes()).hexdigest()
                 and meta["numpy_version"] == np.__version__, "source or NumPy identity differs")
        _require(meta["kind"] in ("empirical", "mlp"), "unknown model kind")
        _require(0 < _number(meta["learning_rate"]) <= 1.0, "invalid learning rate")
        d, a = len(_names(meta["feature_names"])), len(_names(meta["action_ids"]))
        hidden = meta["hidden_size"]
        _require(type(hidden) is int and 1 <= hidden <= 256, "invalid hidden size")
        shapes = {"w1": (d + a, hidden), "b1": (hidden,), "w2": (hidden, 3), "b2": (3,)}
        if meta["kind"] == "empirical":
            shapes = {}
        model.parameters, model.m, model.v = {}, {}, {}
        for target, values in ((model.parameters, p["parameters"]),
                               (model.m, p["optimizer"]["m"]), (model.v, p["optimizer"]["v"])):
            _require(set(values) == set(shapes), "checkpoint parameters differ")
            for name, shape in shapes.items():
                value = np.asarray(values[name], dtype=np.float64)
                _require(value.shape == shape and np.isfinite(value).all(), "invalid parameter shape/value")
                target[name] = value
        _require(all((v >= 0).all() for v in model.v.values()), "negative Adam second moment")
        model.center, model.scale = np.array(p["center"], dtype=np.float64), np.array(p["scale"], dtype=np.float64)
        _require(model.center.shape == model.scale.shape == (d,) and np.isfinite(model.center).all()
                 and np.isfinite(model.scale).all() and (model.scale > 0).all(), "invalid feature normalization")
        model.step = p["optimizer"]["step"]
        _require(type(model.step) is int and model.step >= 0, "invalid Adam step")
        model.loss_history, model.empirical = p["loss_history"], p["empirical"]
        model.residuals = {k: np.array(v, dtype=np.float64) for k, v in p["residuals"].items()}
        counts = meta["training"]["action_counts"]
        _require(counts and set(counts) <= set(meta["action_ids"]), "invalid training actions")
        _require(all(type(n) is int and 1 <= n <= MAX_ATOMS for n in counts.values()), "invalid action count")
        training = meta["training"]
        complete = training["complete_case_rows"]
        total, excluded = training["input_rows"], training["excluded_rows"]
        _require(type(complete) is int and 1 <= complete <= MAX_ROWS
                 and type(total) is int and complete <= total <= MAX_ROWS
                 and type(excluded) is int and excluded == total - complete
                 and sum(counts.values()) == complete, "inconsistent training row ledger")
        _require(type(meta["optimizer_calls"]) is int and meta["optimizer_calls"] == model.step
                 and type(meta["sample_presentations"]) is int
                 and meta["sample_presentations"] == model.step * complete,
                 "inconsistent optimizer work ledger")
        if meta["kind"] == "mlp":
            _require(set(model.residuals) == set(counts) and not model.empirical,
                     "missing action residuals")
            _require(all(v.shape == (counts[k], 2) and np.isfinite(v).all()
                         for k, v in model.residuals.items()), "invalid residuals")
            _require(len(model.loss_history) == model.step + 1 and
                     all(math.isfinite(x) for x in model.loss_history), "invalid loss history")
        else:
            _require(set(model.empirical) == set(counts) and not model.residuals and
                     model.step == 0 and not model.loss_history, "invalid empirical checkpoint")
        # Exercise each supported prediction before returning a restored checkpoint.
        for action in counts:
            prediction = model.predict(model.center.tolist(), action)
            _require(0 <= _number(prediction["success_probability"]) <= 1, "invalid success probability")
            for prefix in ("duration", "cost"):
                values, probabilities = prediction[prefix + "_values"], prediction[prefix + "_probabilities"]
                _require(0 < len(values) <= MAX_ATOMS and len(values) == len(probabilities)
                         and all(_number(x) >= 0 for x in values)
                         and all(0 < _number(x) <= 1 for x in probabilities)
                         and math.isclose(sum(probabilities), 1.0, abs_tol=1e-12), "invalid empirical marginal")
        return model


def fit_observed_model(rows, *, kind, feature_names, action_ids, success_definition,
                       cost_unit, feature_encoding="last_observed_row", seed=0,
                       hidden_size=16, epochs=200, learning_rate=0.01):
    """Fit train-only chosen actions; caller owns factual/readback authentication."""
    started, cpu = perf_counter(), process_time()
    _require(kind in ("empirical", "mlp"), "unknown model kind")
    feature_names, action_ids = _names(feature_names), _names(action_ids)
    for text in (success_definition, cost_unit, feature_encoding):
        _names([text])
    _require(type(seed) is int and 0 <= seed < 2 ** 64, "invalid seed")
    _require(type(hidden_size) is int and 1 <= hidden_size <= 256, "invalid hidden size")
    _require(0 < _number(learning_rate) <= 1.0, "invalid learning rate")
    selected, report = _training_rows(rows, feature_names, action_ids)
    model = ObservedModel()
    model.metadata = {
        "kind": kind, "feature_names": feature_names, "feature_encoding": feature_encoding,
        "action_ids": action_ids, "success_definition": success_definition,
        "duration_unit": "seconds", "cost_unit": cost_unit,
        "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "numpy_version": np.__version__, "training": report, "seed": seed,
        "hidden_size": hidden_size, "learning_rate": float(learning_rate),
        "optimizer_calls": 0, "sample_presentations": 0,
        "physical_cost_complete": False,
        "fit_meter_scope": "validation, fitting and residuals; excludes checkpoint IO, collection and downstream work",
        "distribution_scope": "chosen-action complete-case marginals; not a joint or causal counterfactual law",
    }
    features = np.array([r["features"] for r in selected], dtype=np.float64)
    model.center, scale = features.mean(axis=0), features.std(axis=0)
    model.scale = np.where(scale > 1e-12, scale, 1.0)
    _require(np.isfinite(model.center).all() and np.isfinite(model.scale).all(),
             "nonfinite feature normalization")
    model.parameters, model.m, model.v, model.residuals, model.empirical = {}, {}, {}, {}, {}
    model.step, model.loss_history = 0, []
    if kind == "empirical":
        for action in report["action_counts"]:
            matched = [r for r in selected if r["action_id"] == action]
            duration, duration_p = _distribution([r["duration_seconds"] for r in matched])
            cost, cost_p = _distribution([r["action_cost"] for r in matched])
            model.empirical[action] = {
                "success_probability": float(np.mean([r["outcome_quality"] for r in matched])),
                "duration_values": duration, "duration_probabilities": duration_p,
                "cost_values": cost, "cost_probabilities": cost_p,
            }
    else:
        rng = np.random.default_rng(seed)
        width = len(feature_names) + len(action_ids)
        model.parameters = {"w1": rng.normal(0, 1 / math.sqrt(width), (width, hidden_size)),
                            "b1": np.zeros(hidden_size),
                            "w2": rng.normal(0, 0.1 / math.sqrt(hidden_size), (hidden_size, 3)),
                            "b2": np.zeros(3)}
        model.m = {k: np.zeros_like(v) for k, v in model.parameters.items()}
        model.v = {k: np.zeros_like(v) for k, v in model.parameters.items()}
        model._optimize(selected, epochs)
    model.metadata["fit_wall_seconds"] = perf_counter() - started
    model.metadata["fit_cpu_seconds"] = process_time() - cpu
    return model
