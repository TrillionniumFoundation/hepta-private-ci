"""A descriptive old-TRAIN forecast of task completion at later actor readback.

Only original ensure-entry features are inputs. UNKNOWN targets are censored.
This advisor has no tool host, STOP authority, learned skill selection/composition,
operational benefit or independent-task claim. Existing fixed skills stay adopted.
"""

from collections import Counter, defaultdict
import os
from pathlib import Path
import platform
import re
import time

import numpy as np

import ensure_transition_loader
from ensure_transition_loader import canonical, load_transitions, require, sha


SEEDS = (4101, 4102)
STEPS = 200
RATE = 0.025
REGULARIZATION = 0.001
GROUP = re.compile(
    r"train/train-[ab]/schema-[01]/(keys-[12]/(?:normal|prestaged|already_partial|lost_reply|opaque_after_apply))/[01]"
)


def _parameter_digest(parameters):
    return sha(
        b"".join(
            canonical([key, list(value.shape), "<f8"]) + value.astype("<f8").tobytes()
            for key, value in sorted(parameters.items())
        )
    )


class CompletionAdvisor:
    """A bounded 10→8→1 tanh forecast; probabilities never certify a goal."""

    def __init__(self, seed):
        rng = np.random.default_rng(seed)
        self.parameters = {
            "W": rng.normal(0, 0.08, (10, 8)),
            "b": np.zeros(8),
            "v": rng.normal(0, 0.08, 8),
            "c": np.zeros(1),
        }

    def predict(self, features):
        x = np.asarray(features, dtype=np.float64)
        require(
            x.ndim == 2
            and x.shape[1] == 10
            and np.isfinite(x).all()
            and ((0 <= x) & (x <= 1)).all()
            and (x[:, 1] == 0).all(),
            "only finite original incomplete ensure-entry features are supported",
        )
        p = self.parameters
        logits = np.tanh(x @ p["W"] + p["b"]) @ p["v"] + p["c"][0]
        return np.exp(-np.logaddexp(0, -logits))

    def loss_gradient(self, features, targets):
        probability = self.predict(features)
        y = np.asarray(targets, dtype=np.float64)
        require(
            y.shape == probability.shape
            and len(y) > 0
            and np.isfinite(y).all()
            and ((y == 0) | (y == 1)).all(),
            "loss accepts observed boolean targets only",
        )
        p, x = self.parameters, np.asarray(features, dtype=np.float64)
        hidden = np.tanh(x @ p["W"] + p["b"])
        logits = hidden @ p["v"] + p["c"][0]
        bce = float(np.mean(np.logaddexp(0, logits) - y * logits))
        error = (probability - y) / len(y)
        dh = error[:, None] * p["v"] * (1 - hidden * hidden)
        gradient = {
            "W": x.T @ dh + REGULARIZATION * p["W"],
            "b": dh.sum(axis=0),
            "v": hidden.T @ error + REGULARIZATION * p["v"],
            "c": np.array([error.sum()]),
        }
        penalty = 0.5 * REGULARIZATION * (np.sum(p["W"] ** 2) + np.sum(p["v"] ** 2))
        return bce + float(penalty), bce, gradient

    def fit(self, features, targets, steps=STEPS):
        require(type(steps) is int and 1 <= steps <= STEPS, "optimizer step bound")
        first = {k: np.zeros_like(v) for k, v in self.parameters.items()}
        second = {k: np.zeros_like(v) for k, v in self.parameters.items()}
        records = []
        for step in range(1, steps + 1):
            before = _parameter_digest(self.parameters)
            loss, bce, gradient = self.loss_gradient(features, targets)
            update_norm = 0.0
            for key, g in gradient.items():
                first[key] = 0.9 * first[key] + 0.1 * g
                second[key] = 0.999 * second[key] + 0.001 * g * g
                update = (
                    RATE
                    * (first[key] / (1 - 0.9**step))
                    / (np.sqrt(second[key] / (1 - 0.999**step)) + 1e-8)
                )
                self.parameters[key] -= update
                update_norm += float(np.sum(update * update))
            require(
                all(np.isfinite(v).all() for v in self.parameters.values()),
                "nonfinite optimizer state",
            )
            after = _parameter_digest(self.parameters)
            records.append(
                {
                    "step": step,
                    "objective_before": loss,
                    "bce_before": bce,
                    "gradient_l2": float(
                        np.sqrt(sum(np.sum(g * g) for g in gradient.values()))
                    ),
                    "update_l2": float(np.sqrt(update_norm)),
                    "parameters_before_sha256": before,
                    "parameters_after_sha256": after,
                    "parameter_bytes_changed": before != after,
                }
            )
        return records


def _data(records):
    features, targets, groups = [], [], []
    for record in records:
        group = GROUP.fullmatch(record["task_id"])
        require(
            group is not None and record["split"] == "train", "non-original TRAIN group"
        )
        label = record["target"]["task_complete_on_readback"]
        require(
            label is None or type(label) is bool,
            "invalid observed task-completion target",
        )
        require(
            (label is None) == (record["target"]["censoring"] is not None),
            "censor/target mismatch",
        )
        feature = record["initiation_features"]
        require(
            isinstance(feature, list)
            and len(feature) == 10
            and all(type(v) in (int, float) for v in feature),
            "invalid original entry features",
        )
        features.append(feature)
        targets.append(np.nan if label is None else float(label))
        groups.append(group[1])
    x, y = np.asarray(features, dtype=np.float64), np.asarray(targets)
    CompletionAdvisor(0).predict(x)  # The same admission rule applies before fitting.
    return x, y, np.asarray(groups)


def _scores(targets, probability):
    observed = np.isfinite(targets)
    y, p = targets[observed], np.asarray(probability)[observed]
    result = {
        "total": len(targets),
        "observed": int(observed.sum()),
        "censored": int((~observed).sum()),
        "brier": None,
        "log_loss": None,
        "confusion": None,
        "accuracy": None,
    }
    if len(y):
        require(
            np.isfinite(p).all() and ((0 <= p) & (p <= 1)).all(), "invalid forecast"
        )
        bounded = np.clip(p, 1e-12, 1 - 1e-12)
        decision = p >= 0.5
        result.update(
            brier=float(np.mean((p - y) ** 2)),
            log_loss=float(
                np.mean(-y * np.log(bounded) - (1 - y) * np.log1p(-bounded))
            ),
            accuracy=float(np.mean(decision == y)),
            confusion={
                "true_positive": int(np.sum(decision & (y == 1))),
                "false_positive": int(np.sum(decision & (y == 0))),
                "true_negative": int(np.sum(~decision & (y == 0))),
                "false_negative": int(np.sum(~decision & (y == 1))),
            },
        )
    return result


def _baselines(train_x, train_y, test_x):
    observed = np.isfinite(train_y)
    x, y = train_x[observed], train_y[observed]
    require(len(y) > 0, "baseline needs observed training labels")
    rate = float((y.sum() + 1) / (len(y) + 2))
    table = defaultdict(list)
    for feature, target in zip(x, y):
        table[tuple(feature)].append(target)
    lookup = []
    for feature in test_x:
        labels = table.get(tuple(feature))
        lookup.append(
            (sum(labels) + 1) / (len(labels) + 2) if labels is not None else rate
        )
    return {
        "smoothed_constant": np.full(len(test_x), rate),
        "laplace_exact_feature_table": np.asarray(lookup),
    }


def _plan(dataset, x, y, groups, sources):
    unique = sorted(set(groups))
    folds, group_features = [], {}
    for group in unique:
        held = groups == group
        train_patterns = {tuple(v) for v in x[~held]}
        group_features[group] = {tuple(v) for v in x[held]}
        folds.append(
            {
                "held_group": group,
                "train_records": [
                    r["record_sha256"]
                    for r, yes in zip(dataset["records"], ~held)
                    if yes
                ],
                "held_records": [
                    r["record_sha256"]
                    for r, yes in zip(dataset["records"], held)
                    if yes
                ],
                "held_total": int(held.sum()),
                "held_observed": int(np.isfinite(y[held]).sum()),
                "held_rows_with_exact_feature_in_training": sum(
                    tuple(v) in train_patterns for v in x[held]
                ),
            }
        )
    components, remaining = [], set(unique)
    while remaining:
        component = {min(remaining)}
        changed = True
        while changed:
            patterns = set().union(*(group_features[g] for g in component))
            expanded = component | {g for g in unique if group_features[g] & patterns}
            changed, component = expanded != component, expanded
        components.append(sorted(component))
        remaining -= component
    ambiguity = []
    for pattern in sorted({tuple(v) for v in x}):
        labels = y[np.all(x == pattern, axis=1)]
        ambiguity.append(
            {
                "features": list(pattern),
                "true": int(np.sum(labels == 1)),
                "false": int(np.sum(labels == 0)),
                "censored": int(np.isnan(labels).sum()),
            }
        )
    return {
        "schema": "hepta.act3.readback-completion-advisory-plan.v1",
        "dataset_sha256": dataset["dataset_sha256"],
        "source_sha256": sources,
        "target": "task_complete_on_first_observed_subsequent_actor_readback",
        "inputs": "only 10 initiation_features; entry complete bit is always false",
        "grouping": "keys-length/fault; destination, schema and replicate copies stay together",
        "seeds": list(SEEDS),
        "optimizer": {
            "kind": "Adam",
            "steps": STEPS,
            "learning_rate": RATE,
            "l2_weights": REGULARIZATION,
            "shape": [10, 8, 1],
        },
        "folds": folds,
        "final_fits": len(SEEDS),
        "planned_fits": (len(folds) + 1) * len(SEEDS),
        "feature_connected_components": components,
        "visible_pattern_targets": ambiguity,
        "distinct_entry_features": len(ambiguity),
        "independent_task_and_feature_holdout_available": len(components) > 1,
        "censoring": "omit missing targets from supervised loss and scores; retain predictions and denominators",
        "missingness_limit": "opaque readback conditions censor outcomes; observed-only scores do not estimate unconditional success",
        "selection": "fixed seeds/hyperparameters; no best-seed or confirmation-driven selection",
        "runtime": {"python": platform.python_version(), "numpy": np.__version__},
        "production_adoption": False,
        "operational_evaluation": False,
    }


def _write(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def run_probe(archive, output):
    """Reload pinned originals, freeze the descriptive plan, then perform real fits."""
    dataset = load_transitions(archive)
    output = Path(output)
    source_paths = [Path(__file__), Path(ensure_transition_loader.__file__)]
    sources = {p.name: sha(p.read_bytes()) for p in source_paths}
    x, y, groups = _data(dataset["records"])
    require(set(y[np.isfinite(y)]) == {0, 1}, "degenerate observed completion labels")
    plan = _plan(dataset, x, y, groups, sources)
    output.mkdir(parents=True, exist_ok=False)
    _write(output / "FROZEN_PLAN.json", plan)
    _write(output / "DATASET.json", dataset)
    fit_reports, predictions, fold_metrics = [], [], []
    start = time.perf_counter_ns()
    for fold_number, fold in enumerate([*plan["folds"], {"held_group": None}]):
        held = (
            groups == fold["held_group"]
            if fold["held_group"] is not None
            else np.zeros(len(groups), dtype=bool)
        )
        training = ~held & np.isfinite(y)
        for seed in SEEDS:
            name = (
                f"fold-{fold_number:02d}-seed-{seed}"
                if fold["held_group"] is not None
                else f"full-train-seed-{seed}"
            )
            destination = output / name
            destination.mkdir()
            model = CompletionAdvisor(seed)
            np.savez(destination / "initial.npz", **model.parameters)
            initial = _parameter_digest(model.parameters)
            before_wall, before_cpu = time.perf_counter_ns(), time.process_time_ns()
            log = model.fit(x[training], y[training])
            wall, cpu = (
                time.perf_counter_ns() - before_wall,
                time.process_time_ns() - before_cpu,
            )
            with (destination / "optimizer.jsonl").open("x") as stream:
                for record in log:
                    stream.write(canonical(record).decode() + "\n")
            np.savez(destination / "weights.npz", **model.parameters)
            reloaded = CompletionAdvisor(seed)
            with np.load(destination / "weights.npz", allow_pickle=False) as weights:
                require(
                    set(weights.files) == set(reloaded.parameters),
                    "saved model fields differ",
                )
                for key, reference in reloaded.parameters.items():
                    value = weights[key]
                    require(
                        value.shape == reference.shape
                        and value.dtype == np.dtype("float64")
                        and np.isfinite(value).all(),
                        "saved model tensor differs",
                    )
                    reloaded.parameters[key] = value.copy()
            require(
                _parameter_digest(model.parameters)
                == _parameter_digest(reloaded.parameters),
                "model reload drift",
            )
            objective, bce, _ = reloaded.loss_gradient(x[training], y[training])
            multiset = Counter(
                tuple(row) + (float(target),)
                for row, target in zip(x[training], y[training])
            )
            fit_report = {
                "fit": name,
                "seed": seed,
                "held_group": fold["held_group"],
                "observed_training_transitions": int(training.sum()),
                "training_data_sha256": sha(
                    x[training].astype("<f8").tobytes()
                    + y[training].astype("<f8").tobytes()
                ),
                "training_multiset_sha256": sha(
                    canonical(
                        [[list(row), count] for row, count in sorted(multiset.items())]
                    )
                ),
                "optimizer_invocations": len(log),
                "parameter_mutations": sum(r["parameter_bytes_changed"] for r in log),
                "initial_parameters_sha256": initial,
                "final_parameters_sha256": _parameter_digest(reloaded.parameters),
                "initial_bce": log[0]["bce_before"],
                "final_bce": bce,
                "final_objective": objective,
                "fit_wall_ns": wall,
                "fit_cpu_ns": cpu,
                "weights_sha256": sha((destination / "weights.npz").read_bytes()),
            }
            _write(destination / "FIT.json", fit_report)
            fit_reports.append(fit_report)
            if fold["held_group"] is None:
                continue
            forecasts = {
                "neural_advisory": reloaded.predict(x[held]),
                **_baselines(x[~held], y[~held], x[held]),
            }
            fold_metrics.append(
                {
                    "fit": name,
                    "seed": seed,
                    "held_group": fold["held_group"],
                    "metrics": {k: _scores(y[held], p) for k, p in forecasts.items()},
                }
            )
            for position, index in enumerate(np.flatnonzero(held)):
                record = dataset["records"][index]
                predictions.append(
                    {
                        "fit": name,
                        "seed": seed,
                        "held_group": fold["held_group"],
                        "record_sha256": record["record_sha256"],
                        "task_id": record["task_id"],
                        "target": record["target"]["task_complete_on_readback"],
                        "censoring": record["target"]["censoring"],
                        "probability": {
                            k: float(p[position]) for k, p in forecasts.items()
                        },
                        "authority": "forecast only; fresh original readback still required",
                    }
                )
    require(
        load_transitions(archive)["dataset_sha256"] == dataset["dataset_sha256"]
        and all(sha(p.read_bytes()) == sources[p.name] for p in source_paths),
        "source or dataset changed during fitting",
    )
    require(len(fit_reports) == plan["planned_fits"], "fit denominator differs")
    by_seed = {}
    for seed in SEEDS:
        rows = [r for r in predictions if r["seed"] == seed]
        require(
            len(rows) == len(dataset["records"])
            and len({r["record_sha256"] for r in rows}) == len(rows),
            "out-of-fold prediction coverage differs",
        )
        labels = np.array(
            [np.nan if r["target"] is None else float(r["target"]) for r in rows]
        )
        by_seed[str(seed)] = {
            k: _scores(labels, np.array([r["probability"][k] for r in rows]))
            for k in rows[0]["probability"]
        }
    result = {
        "schema": "hepta.act3.readback-completion-advisory-result.v1",
        "status": "OLD_TRAIN_DESCRIPTIVE_PROBE_COMPLETED",
        "dataset_sha256": dataset["dataset_sha256"],
        "fit_count": len(fit_reports),
        "optimizer_invocations": sum(r["optimizer_invocations"] for r in fit_reports),
        "distinct_ordered_supervised_arrays": len(
            {r["training_data_sha256"] for r in fit_reports}
        ),
        "distinct_supervised_multisets": len(
            {r["training_multiset_sha256"] for r in fit_reports}
        ),
        "transitions": len(y),
        "observed": int(np.isfinite(y).sum()),
        "censored": int(np.isnan(y).sum()),
        "folds": len(plan["folds"]),
        "folds_with_observed_targets": sum(
            f["held_observed"] > 0 for f in plan["folds"]
        ),
        "fully_censored_folds": sum(f["held_observed"] == 0 for f in plan["folds"]),
        "by_seed": by_seed,
        "fold_metrics": fold_metrics,
        "fits": fit_reports,
        "campaign_wall_ns": time.perf_counter_ns() - start,
        "source_sha256": sources,
        "promotion": False,
        "fixed_skill_library_retained": True,
        "new_independent_real_tasks": 0,
        "new_confirmation_tasks": 0,
        "operational_evaluation_performed": False,
        "learned_skill_selection_qualified": False,
        "stop_authority": False,
        "scope": "future task completion at separate subsequent readback; not option termination or skill success",
        "limits": [
            "all folds reuse exact feature vectors seen in other configurations",
            "only three entry feature vectors",
            "censoring is condition-dependent",
            "training seeds are not independent tasks",
            "no execution-policy or net-utility comparison",
        ],
    }
    with (output / "PREDICTIONS.jsonl").open("x") as stream:
        for row in predictions:
            stream.write(canonical(row).decode() + "\n")
    _write(output / "RESULT.json", result)
    return result
