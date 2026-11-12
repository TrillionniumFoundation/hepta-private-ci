"""FP64 history baseline for complete chosen-action continuous observations.

The frozen pilot GRU supplies its recurrence, not its discrete target support.
Unknown/censored rows stay committed and counted, but do not supervise this
complete-case model. Residual marginals are neither survival nor joint/causal
models. Source declarations and hashes do not authenticate owner observations.
"""

from collections import Counter
from hashlib import sha256
import json
import math
import os
from pathlib import Path
from time import perf_counter, process_time

import numpy as np

from .models import Model, sigmoid
from .observed_models import (
    MAX_ATOMS, MAX_CHECKPOINT_BYTES, MAX_ROWS, _canonical, _digest,
    _distribution, _names, _number, _require, _training_rows,
)

SCHEMA = "pred1-observed-gru-v1"
MAX_HISTORY = 256
MAX_HISTORY_STEPS = 65536


def _sources():
    return {name: sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ("observed_gru.py", "observed_models.py", "models.py")}


def _history(history, width):
    _require(type(history) is list and 1 <= len(history) <= MAX_HISTORY,
             "history must contain 1..256 actual observations")
    for row in history:
        _require(type(row) is list and len(row) == width, "history feature width differs")
        for value in row:
            _number(value)
    return np.asarray(history, dtype=np.float64)


def _rows(rows, names, actions):
    selected, report = _training_rows(rows, names, actions)
    steps = 0
    for row in rows:
        history = _history(row.get("history"), len(names))
        _require(row["features"] == row["history"][-1], "features differ from history final row")
        steps += len(history)
        _require(steps <= MAX_HISTORY_STEPS, "total history step limit exceeded")
    lengths = Counter(str(len(row["history"])) for row in selected)
    report.update(input_history_steps=steps,
                  complete_case_history_steps=sum(int(k) * v for k, v in lengths.items()),
                  history_length_counts=dict(lengths))
    return selected, report


def _continuous_loss_grad(kernel, histories, actions, targets):
    """Exact variable-length BPTT, grouped by length without padding observations."""
    gradients = {key: np.zeros_like(value) for key, value in kernel.params.items()}
    loss, count, p = 0.0, len(histories), kernel.params
    for length in sorted({len(history) for history in histories}):
        indices = [i for i, history in enumerate(histories) if len(history) == length]
        x, a, y = np.stack([histories[i] for i in indices]), actions[indices], targets[indices]
        output = kernel.forward(x, a, cache=True)
        error = output[:, 1:] - y[:, 1:]
        loss += float(np.sum(np.logaddexp(0.0, output[:, 0]) - y[:, 0] * output[:, 0]
                             + 0.5 * np.sum(error ** 2, axis=1))) / count
        delta = np.column_stack((sigmoid(output[:, 0]) - y[:, 0], error)) / count
        history, (features, hidden) = kernel._cache
        gradients["Wy"] += hidden.T @ delta
        gradients["by"] += delta.sum(axis=0)
        dh = (delta @ p["Wy"].T) * (1 - hidden ** 2)
        gradients["Wh"] += features.T @ dh
        gradients["bh"] += dh.sum(axis=0)
        df = (dh @ p["Wh"].T)[:, :kernel.h]
        for xt, previous, z, r, n in reversed(history):
            dn = df * z * (1 - n ** 2)
            dz = df * (n - previous) * z * (1 - z)
            dproduct = dn @ p["Un"].T
            dr = dproduct * previous * r * (1 - r)
            for gate, change, recurrent in (("n", dn, r * previous),
                                             ("z", dz, previous), ("r", dr, previous)):
                gradients["W" + gate] += xt.T @ change
                gradients["U" + gate] += recurrent.T @ change
                gradients["b" + gate] += change.sum(axis=0)
            df = df * (1 - z) + dproduct * r + dz @ p["Uz"].T + dr @ p["Ur"].T
    _require(math.isfinite(loss) and all(np.isfinite(x).all() for x in gradients.values()),
             "nonfinite loss or gradient")
    return loss, gradients


class ObservedGRU:
    """Frozen-schema history predictor with a candidate-conditioned marginal head."""

    def _inputs(self, history, action):
        _require(action in self.metadata["training"]["action_counts"],
                 "action unavailable in complete-case training")
        values = _history(history, len(self.metadata["feature_names"]))
        with np.errstate(over="ignore", invalid="ignore"):
            values = (values - self.center) / self.scale
        _require(np.isfinite(values).all(), "nonfinite normalized history")
        one_hot = np.zeros(len(self.metadata["action_ids"]), dtype=np.float64)
        one_hot[self.metadata["action_ids"].index(action)] = 1.0
        return values, one_hot

    def predict(self, history, action_id):
        """Read actual history; candidate action enters only the final head."""
        _names([action_id])
        x, action = self._inputs(history, action_id)
        output = self.kernel.forward(x[None], action[None])[0]
        _require(np.isfinite(output).all(), "nonfinite model output")
        with np.errstate(over="raise", invalid="raise"):
            try:
                samples = np.expm1(np.maximum(0.0, output[1:] + self.residuals[action_id]))
            except FloatingPointError as error:
                raise ValueError("nonfinite predicted marginal") from error
        duration, duration_p = _distribution(samples[:, 0])
        cost, cost_p = _distribution(samples[:, 1])
        return {"success_probability": float(sigmoid(output[0])),
                "duration_values": duration, "duration_probabilities": duration_p,
                "cost_values": cost, "cost_probabilities": cost_p}

    def _optimize(self, selected, epochs):
        _require(type(epochs) is int and 1 <= epochs <= 10000, "invalid epoch count")
        encoded = [self._inputs(row["history"], row["action_id"]) for row in selected]
        histories, actions = [pair[0] for pair in encoded], np.stack([pair[1] for pair in encoded])
        targets = np.array([[r["outcome_quality"], math.log1p(r["duration_seconds"]),
                             math.log1p(r["action_cost"])] for r in selected], dtype=np.float64)
        if self.loss_history:
            self.loss_history.pop()
        kernel = self.kernel
        for _ in range(epochs):
            loss, gradients = _continuous_loss_grad(kernel, histories, actions, targets)
            self.loss_history.append(loss)
            norm = math.sqrt(sum(float(np.sum(value ** 2)) for value in gradients.values()))
            _require(math.isfinite(norm), "nonfinite gradient norm")
            clip = min(1.0, 5.0 / max(norm, 1e-12))
            kernel.steps += 1
            for name, gradient in gradients.items():
                gradient = gradient * clip
                kernel.m[name] = 0.9 * kernel.m[name] + 0.1 * gradient
                kernel.v[name] = 0.999 * kernel.v[name] + 0.001 * gradient ** 2
                first = kernel.m[name] / (1 - 0.9 ** kernel.steps)
                second = kernel.v[name] / (1 - 0.999 ** kernel.steps)
                kernel.params[name] -= self.metadata["learning_rate"] * first / (np.sqrt(second) + 1e-8)
            _require(all(np.isfinite(v).all() for state in (kernel.params, kernel.m, kernel.v)
                         for v in state.values()), "nonfinite optimizer state")
        self.loss_history.append(_continuous_loss_grad(kernel, histories, actions, targets)[0])
        output = np.vstack([kernel.forward(x[None], a[None])[0] for x, a in encoded])
        residuals = targets[:, 1:] - output[:, 1:]
        self.residuals = {action: residuals[[r["action_id"] == action for r in selected]].copy()
                          for action in self.metadata["training"]["action_counts"]}
        self.metadata.update(optimizer_calls=kernel.steps, sample_presentations=kernel.steps * len(selected),
                             history_step_presentations=kernel.steps * sum(map(len, histories)))

    def continue_fit(self, rows, *, epochs):
        """Resume exact Adam state only on identical committed training rows."""
        wall, cpu = perf_counter(), process_time()
        selected, report = _rows(rows, self.metadata["feature_names"], self.metadata["action_ids"])
        _require(report == self.metadata["training"], "resume training data identity differs")
        self._optimize(selected, epochs)
        self.metadata["fit_wall_seconds"] += perf_counter() - wall
        self.metadata["fit_cpu_seconds"] += process_time() - cpu
        return self

    def save(self, path):
        """Create immutable JSON checkpoint including recurrence, Adam and residuals."""
        payload = {"schema": SCHEMA, "metadata": self.metadata,
                   "center": self.center.tolist(), "scale": self.scale.tolist(),
                   "parameters": {k: v.tolist() for k, v in self.kernel.params.items()},
                   "optimizer": {"step": self.kernel.steps,
                                 "m": {k: v.tolist() for k, v in self.kernel.m.items()},
                                 "v": {k: v.tolist() for k, v in self.kernel.v.items()}},
                   "residuals": {k: v.tolist() for k, v in self.residuals.items()},
                   "loss_history": self.loss_history}
        encoded = _canonical({"payload": payload, "payload_sha256": _digest(payload)})
        _require(len(encoded) <= MAX_CHECKPOINT_BYTES, "checkpoint byte limit exceeded")
        with Path(path).open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        return sha256(encoded).hexdigest()

    @classmethod
    def load(cls, path, *, expected_sha256):
        """Verify exact bytes, dependency identities, numeric state and work ledger."""
        with Path(path).open("rb") as stream:
            encoded = stream.read(MAX_CHECKPOINT_BYTES + 1)
        _require(len(encoded) <= MAX_CHECKPOINT_BYTES and sha256(encoded).hexdigest() == expected_sha256,
                 "checkpoint size or SHA256 differs")
        try:
            envelope = json.loads(encoded)
            _require(set(envelope) == {"payload", "payload_sha256"}, "invalid checkpoint envelope")
            p = envelope["payload"]
            _require(_digest(p) == envelope["payload_sha256"] and p["schema"] == SCHEMA,
                     "checkpoint payload differs")
            model, meta = cls(), p["metadata"]
            _require(meta["source_sha256"] == _sources() and meta["numpy_version"] == np.__version__,
                     "source or NumPy identity differs")
            _require(meta["kind"] == "gru" and meta["feature_encoding"] == "observed_history_v1"
                     and meta["duration_unit"] == "seconds", "model schema differs")
            names, actions = _names(meta["feature_names"]), _names(meta["action_ids"])
            for value in (meta["success_definition"], meta["cost_unit"]):
                _names([value])
            _require(type(meta["seed"]) is int and 0 <= meta["seed"] < 2 ** 64, "invalid seed")
            hidden = meta["hidden_size"]
            _require(type(hidden) is int and 1 <= hidden <= 256, "invalid hidden size")
            _require(0 < _number(meta["learning_rate"]) <= 1, "invalid learning rate")
            model.metadata = meta
            model.kernel = Model("gru", len(names), len(actions), 3, hidden, meta["seed"])
            _require(type(meta["parameter_count"]) is int and meta["parameter_count"] == model.kernel.parameter_count,
                     "parameter count differs")
            _require(meta["physical_cost_complete"] is False and meta["provenance_authenticated"] is False,
                     "unqualified model cannot claim physical cost or provenance authentication")
            model.center, model.scale = np.array(p["center"], dtype=np.float64), np.array(p["scale"], dtype=np.float64)
            _require(model.center.shape == model.scale.shape == (len(names),)
                     and np.isfinite(model.center).all() and np.isfinite(model.scale).all()
                     and (model.scale > 0).all(), "invalid feature normalization")
            for target, values in ((model.kernel.params, p["parameters"]),
                                   (model.kernel.m, p["optimizer"]["m"]), (model.kernel.v, p["optimizer"]["v"])):
                _require(set(target) == set(values), "checkpoint parameter names differ")
                for name, template in target.items():
                    value = np.asarray(values[name], dtype=np.float64)
                    _require(value.shape == template.shape and np.isfinite(value).all(), "invalid parameter shape/value")
                    target[name] = value
            _require(all((v >= 0).all() for v in model.kernel.v.values()), "negative Adam second moment")
            step, training = p["optimizer"]["step"], meta["training"]
            _require(type(step) is int and step >= 1, "invalid Adam step")
            complete, total, excluded = (training[k] for k in ("complete_case_rows", "input_rows", "excluded_rows"))
            counts, lengths = training["action_counts"], training["history_length_counts"]
            _require(type(complete) is int and 1 <= complete <= MAX_ROWS
                     and type(total) is int and complete <= total <= MAX_ROWS
                     and type(excluded) is int and excluded == total - complete, "inconsistent training row ledger")
            _require(counts and set(counts) <= set(actions)
                     and all(type(n) is int and 1 <= n <= MAX_ATOMS for n in counts.values())
                     and sum(counts.values()) == complete, "inconsistent action ledger")
            _require(lengths and all(str(int(k)) == k and 1 <= int(k) <= MAX_HISTORY
                                     and type(n) is int and n > 0 for k, n in lengths.items())
                     and sum(lengths.values()) == complete, "inconsistent history length ledger")
            used_steps, input_steps = training["complete_case_history_steps"], training["input_history_steps"]
            _require(type(used_steps) is int and used_steps == sum(int(k) * n for k, n in lengths.items())
                     and type(input_steps) is int and used_steps + excluded <= input_steps <= MAX_HISTORY_STEPS
                     and input_steps <= used_steps + excluded * MAX_HISTORY, "inconsistent history step ledger")
            for key, expected in (("optimizer_calls", step), ("sample_presentations", step * complete),
                                  ("history_step_presentations", step * used_steps)):
                _require(type(meta[key]) is int and meta[key] == expected, "inconsistent optimizer work ledger")
            groups, used_groups = training["task_groups"], training["used_task_groups"]
            _names(groups, MAX_ROWS)
            _names(used_groups, MAX_ROWS)
            _require(set(used_groups) <= set(groups) and len(used_groups) <= complete and len(groups) <= total
                     and groups == sorted(groups) and used_groups == sorted(used_groups)
                     and training["task_groups_sha256"] == _digest(groups), "inconsistent training group ledger")
            digest = training["input_sha256"]
            _require(type(digest) is str and len(digest) == 64 and all(x in "0123456789abcdef" for x in digest),
                     "invalid training input commitment")
            reasons = training["exclusion_reason_counts"]
            allowed_reasons = {"outcome_unknown", "outcome_cancel_requested", "outcome_right_censored",
                               "time_interval", "time_unobserved", "cost_unknown"}
            _require(set(reasons) <= allowed_reasons
                     and all(type(n) is int and 1 <= n <= excluded for n in reasons.values())
                     and excluded <= sum(reasons.values()) <= 3 * excluded,
                     "inconsistent exclusion ledger")
            _require(training["provenance_authenticated"] is False and training["missingness_bias_corrected"] is False,
                     "complete-case model cannot claim authentication or missingness correction")
            for key, expected in (("source_counts", total), ("used_source_counts", complete)):
                sources = training[key]
                _require(set(sources) <= {"fixture", "declared_owner"}
                         and all(type(n) is int and n > 0 for n in sources.values())
                         and sum(sources.values()) == expected, "inconsistent source ledger")
            _require(all(n <= training["source_counts"].get(k, 0) for k, n in training["used_source_counts"].items()),
                     "used sources exceed input source ledger")
            model.kernel.steps, model.loss_history = step, p["loss_history"]
            _require(len(model.loss_history) == step + 1 and all(_number(x) >= 0 for x in model.loss_history),
                     "invalid loss history")
            model.residuals = {k: np.asarray(v, dtype=np.float64) for k, v in p["residuals"].items()}
            _require(set(model.residuals) == set(counts)
                     and all(v.shape == (counts[k], 2) and np.isfinite(v).all() for k, v in model.residuals.items()),
                     "invalid residuals")
            for key in ("fit_wall_seconds", "fit_cpu_seconds"):
                _require(_number(meta[key]) >= 0, "invalid fit meter")
            for action in counts:
                model.predict([model.center.tolist()], action)
            return model
        except (KeyError, TypeError, IndexError, OverflowError) as error:
            raise ValueError("malformed GRU checkpoint") from error


def fit_observed_gru(rows, *, feature_names, action_ids, success_definition, cost_unit,
                     seed=0, hidden_size=16, epochs=200, learning_rate=0.01):
    """Fit real supplied histories only; never synthesize histories from final rows."""
    wall, cpu = perf_counter(), process_time()
    names, actions = _names(feature_names), _names(action_ids)
    for value in (success_definition, cost_unit):
        _names([value])
    _require(type(seed) is int and 0 <= seed < 2 ** 64, "invalid seed")
    _require(type(hidden_size) is int and 1 <= hidden_size <= 256, "invalid hidden size")
    _require(0 < _number(learning_rate) <= 1, "invalid learning rate")
    selected, report = _rows(rows, names, actions)
    model = ObservedGRU()
    model.kernel = Model("gru", len(names), len(actions), 3, hidden_size, seed)
    values = np.concatenate([np.asarray(r["history"], dtype=np.float64) for r in selected])
    model.center, scale = values.mean(axis=0), values.std(axis=0)
    model.scale = np.where(scale > 1e-12, scale, 1.0)
    _require(np.isfinite(model.center).all() and np.isfinite(model.scale).all(), "nonfinite feature normalization")
    model.metadata = {
        "kind": "gru", "feature_names": names, "feature_encoding": "observed_history_v1",
        "action_ids": actions, "success_definition": success_definition,
        "duration_unit": "seconds", "cost_unit": cost_unit, "source_sha256": _sources(),
        "numpy_version": np.__version__, "training": report, "seed": seed,
        "hidden_size": hidden_size, "learning_rate": float(learning_rate),
        "parameter_count": model.kernel.parameter_count,
        "physical_cost_complete": False, "provenance_authenticated": False,
        "normalization_scope": "each actual complete-case training history step once; no padding",
        "distribution_scope": "chosen-action complete-case residual marginals; not survival, joint or causal counterfactual law",
        "fit_meter_scope": "validation, fitting and residuals; excludes checkpoint IO, owner and downstream work",
    }
    model.loss_history, model.residuals = [], {}
    model._optimize(selected, epochs)
    model.metadata.update(fit_wall_seconds=perf_counter() - wall, fit_cpu_seconds=process_time() - cpu)
    return model
