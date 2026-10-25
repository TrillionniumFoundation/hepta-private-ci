"""Source-cross-fitted positive conditional values for acoustic acquisition."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from experiments.multimodal_output_portfolio.abc_next.temporal.audit import sha256, write_json
from .state import Frame, GAMMA, PRICE, ROUTES, SEEDS, features


FIT = {"steps": 1200, "learning_rate": .008, "l2": .0005,
       "feedback_hidden": 32, "initial_hidden": 64, "folds": 2,
       "positive_floor": .001, "gamma": GAMMA, "price": PRICE,
       "feedback_variants": ["full", "cue_only"]}


def public_features(frame, variant):
    if variant not in FIT["feedback_variants"]:
        raise ValueError("Unknown feedback observation variant")
    if variant == "cue_only":
        state = frame.detached()
        state["previous_audio_fact"] = (None, None, None)
        frame = Frame(**state)
    return features(frame)


def train(x, target, seed, hidden):
    rng = np.random.default_rng(seed)
    center, scale = x.mean(0), np.maximum(x.std(0), .1)
    x = (x - center) / scale
    arrays = [rng.normal(0, .12, (x.shape[1], hidden)), np.zeros(hidden),
              rng.normal(0, .12, (hidden, target.shape[1])), np.zeros(target.shape[1])]
    first, second = [np.zeros_like(a) for a in arrays], [np.zeros_like(a) for a in arrays]
    observed = np.isfinite(target)
    safe_target = np.where(observed, target, 0.)
    for step in range(1, FIT["steps"] + 1):
        h = np.tanh(x @ arrays[0] + arrays[1])
        raw = h @ arrays[2] + arrays[3]
        prediction = np.logaddexp(0, raw) + FIT["positive_floor"]
        delta = 2 * np.where(observed, prediction - safe_target, 0.) / observed.sum() / (1 + np.exp(-np.clip(raw, -40, 40)))
        hdelta = (delta @ arrays[2].T) * (1 - h ** 2)
        gradients = [x.T @ hdelta, hdelta.sum(0), h.T @ delta, delta.sum(0)]
        for i, (a, g) in enumerate(zip(arrays, gradients)):
            if i in (0, 2):
                g = g + FIT["l2"] * a
            first[i] = .9 * first[i] + .1 * g
            second[i] = .999 * second[i] + .001 * g ** 2
            a -= FIT["learning_rate"] * (first[i] / (1 - .9 ** step)) / (np.sqrt(second[i] / (1 - .999 ** step)) + 1e-8)
    model = {"seed": seed, "center": center.tolist(), "scale": scale.tolist(),
             "parameters": [a.tolist() for a in arrays]}
    error = predict(model, x * scale + center) - safe_target
    model["fit_mse"] = float(np.mean(error[observed] ** 2))
    return model


def predict(model, x):
    x = (x - np.asarray(model["center"])) / np.asarray(model["scale"])
    a, b, c, d = [np.asarray(value) for value in model["parameters"]]
    return np.logaddexp(0, np.tanh(x @ a + b) @ c + d) + FIT["positive_floor"]


def crossfit_continuation(x, target, assignment, seed):
    result = np.zeros((len(x), 2))
    for fold in (0, 1):
        held = assignment == fold
        if not held.any() or held.all():
            raise ValueError("Both source folds must be nonempty")
        model = train(x[~held], target[~held], seed, FIT["feedback_hidden"])
        result[held] = predict(model, x[held])
    return result


def read_matrix(directory, expected_role):
    directory = Path(directory)
    complete = json.loads((directory / "complete.json").read_text())
    start = json.loads((directory / "start.json").read_text())
    if complete["role"] != expected_role or start["role"] != expected_role or not complete["complete"]:
        raise ValueError("Wrong or incomplete role")
    if complete["index_sha256"] != sha256(directory / "index.jsonl"):
        raise ValueError("Run index changed")
    groups = {}
    for line in (directory / "index.jsonl").read_text().splitlines():
        item = json.loads(line)
        if sha256(item["case"]) != item["sha256"]:
            raise ValueError("Executed case changed")
        row = json.loads(Path(item["case"]).read_text())
        if row["offline_observation"] is not None:
            raise ValueError("Offline observer cannot enter fitting/selection")
        key = (row["source_id"], row["template"], row["scenario"])
        route = tuple(row["route"])
        if route in groups.setdefault(key, {}):
            raise ValueError("Duplicate route")
        groups[key][route] = row
    if len(groups) != complete["source_groups"] * 4 or any(set(v) != set(ROUTES) for v in groups.values()):
        raise ValueError("Incomplete matrix census")
    return groups


def fixed_component_seconds(row):
    # Matrix collection observes the committed first chunk for feedback states.
    # Fixed/initial deployment omits it. This is only a training/selection cost
    # approximation; all final selected-policy costs are measured directly.
    return (row["generation_cost"]["wall_ns"] - sum(p["wall_ns"] for p in row["prefix_probes"])) / 1e9


def arrays_from_matrix(groups, variant="full"):
    x0, x1, y1, initial, route_y, owners, prefix_costs, actions = [], [], [], [], [], [], [], []
    for key, routes in sorted(groups.items()):
        for route_index, route in enumerate(ROUTES):
            row = routes[route]
            first, second = (Frame(**value) for value in row["frames"])
            # Each recorded history has only its actually executed action label.
            # Vosk confidence varies slightly even for identical PCM, so we do
            # not pretend separate route replays are the same public history.
            x0.append(public_features(first, variant))
            x1.append(public_features(second, variant))
            target = [np.nan, np.nan]
            remaining = row["generation_cost"]["wall_ns"] / 1e9 - second.elapsed_seconds
            target[route[1]] = np.exp(-GAMMA * (row["online_metrics"]["utility"] - PRICE * remaining))
            y1.append(target)
            owners.append(key[0])
            initial.append(features(first, initial_only=True))
            elapsed = second.elapsed_seconds - first.elapsed_seconds
            if variant == "cue_only":
                elapsed -= sum(probe["wall_ns"] for probe in row["prefix_probes"]) / 1e9
            prefix_costs.append(elapsed)
            target = [np.nan] * len(ROUTES)
            target[route_index] = np.exp(-GAMMA * (row["online_metrics"]["utility"] - PRICE * fixed_component_seconds(row)))
            route_y.append(target)
            actions.append(route[0])
    return tuple(np.asarray(v) for v in (x0, x1, y1, initial, route_y, owners, prefix_costs, actions))


class Policy:
    def __init__(self, payload, variant=None):
        if payload["config"] != FIT:
            raise ValueError("Policy configuration identity changed")
        self.payload = payload
        self.variant = variant or payload["selected_feedback_variant"]
        if self.variant not in payload["feedback"]:
            raise ValueError("Unavailable feedback variant")

    @classmethod
    def load(cls, path):
        return cls(json.loads(Path(path).read_text()))

    def initial_route(self, frame):
        x = features(frame, initial_only=True)
        values = np.mean([predict(m, x) for m in self.payload["initial"]], axis=0)
        return ROUTES[int(np.argmin(values))]

    def for_variant(self, variant):
        return Policy(self.payload, variant)

    def needs_prefix_probe(self):
        return self.variant == "full"

    def feedback_action(self, frame):
        name = "q2" if frame.stage == 0 else "q1"
        values = np.mean([predict(m, public_features(frame, self.variant))
                          for m in self.payload["feedback"][self.variant][name]], axis=0)
        return int(np.argmin(values))


def fit(args):
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    groups = read_matrix(args.fit_run, "fit")
    x0, x1, y1, initial, route_y, owners, prefix_costs, actions = arrays_from_matrix(groups)
    source_ids = sorted(set(owners))
    folds = {source: i % 2 for i, source in enumerate(source_ids)}
    assignment = np.asarray([folds[s] for s in owners])
    payload = {"schema": "hepta.abc4.temporal-value.v1", "config": FIT, "seeds": SEEDS,
               "fit_code_sha256": sha256(__file__),
               "fit_sources": len(source_ids), "fit_cases": len(groups), "feedback": {}, "initial": [],
               "selected_feedback_variant": "full",
               "fold_assignments": folds, "fit_index_sha256": sha256(args.fit_run / "index.jsonl"),
               "labels": "online Vosk only; full terminal utility and measured component costs",
               "fixed_cost_labels": "matrix wall minus actual first-output Vosk observation; approximate training/selection only",
               "backup": "source-held-out mean of three Q1 positive-value heads, then minimum over actions; common target for every Q2 seed; same ensemble continuation rule as deployment",
               "value_clock_origins": "Q1: remaining wall time after second decision gate; Q2 multiplier: actual delta from first to second gate; initial-only and final evaluation: complete request wall time",
               "public_feature_dimension": int(x0.shape[1]),
               "external_observer_used": False}
    for variant in FIT["feedback_variants"]:
        x0, x1, y1, _, _, _, prefix_costs, actions = arrays_from_matrix(groups, variant)
        oof_values = [crossfit_continuation(x1, y1, assignment, seed) for seed in SEEDS]
        oof = np.mean(oof_values, axis=0).min(axis=1)
        y2 = np.full((len(x0), 2), np.nan)
        y2[np.arange(len(x0)), actions] = oof * np.exp(GAMMA * PRICE * prefix_costs)
        payload["feedback"][variant] = {"q1": [], "q2": [],
                                        "oof_target_sha256": hashlib.sha256(y2.astype("<f8").tobytes()).hexdigest()}
        for seed in SEEDS:
            payload["feedback"][variant]["q1"].append(train(x1, y1, seed, FIT["feedback_hidden"]))
            payload["feedback"][variant]["q2"].append(train(x0, y2, seed, FIT["feedback_hidden"]))
    for seed in SEEDS:
        payload["initial"].append(train(initial, route_y, seed, FIT["initial_hidden"]))
    fixed_ce = -np.log(np.nanmean(route_y, axis=0)) / GAMMA
    payload["fit_fixed_ce"] = fixed_ce.tolist()
    payload["selected_fixed_route"] = ROUTES[int(np.argmax(fixed_ce))]
    payload["training_wall_ns"] = time.perf_counter_ns() - wall
    payload["training_cpu_ns"] = time.process_time_ns() - cpu
    write_json(args.output, payload)
    print(json.dumps({"policy_sha256": sha256(args.output), "fit_fixed_ce": fixed_ce.tolist(),
                      "training_wall_ns": payload["training_wall_ns"]}), flush=True)


def select(args):
    payload = json.loads(args.policies.read_text())
    policy = Policy(payload)
    complete = json.loads((args.selection_run / "complete.json").read_text())
    if complete["role"] != "selection" or not complete["complete"] or complete["requests"] != 448:
        raise ValueError("Selection requires all 16 groups and seven actually deployed policies")
    values, source_ids = {}, set()
    for line in (args.selection_run / "index.jsonl").read_text().splitlines():
        entry = json.loads(line)
        if sha256(entry["case"]) != entry["sha256"]:
            raise ValueError("Selection observation changed")
        row = json.loads(Path(entry["case"]).read_text())
        if row["offline_observation"] is not None:
            raise ValueError("Whisper cannot enter policy/reference selection")
        source_ids.add(row["source_id"])
        seconds = row["generation_cost"]["wall_ns"] / 1e9
        values.setdefault(entry["policy"], []).append(row["online_metrics"]["utility"] - PRICE * seconds)
    ces = {name: float(-np.log(np.mean(np.exp(-GAMMA * np.asarray(v)))) / GAMMA) for name, v in values.items()}
    best = max(ROUTES, key=lambda r: ces["fixed-" + "".join(map(str, r))])
    selected_variant = max(FIT["feedback_variants"], key=lambda variant: ces["feedback-" + variant])
    payload.update(selected_fixed_route=best, selection_ce=ces,
                   selected_feedback_variant=selected_variant,
                   selection_sources=len(source_ids),
                   selection_index_sha256=sha256(args.selection_run / "index.jsonl"),
                   preselection_policy_sha256=sha256(args.policies))
    write_json(args.output, payload)
    print(json.dumps({"selected_fixed_route": best, "selected_feedback_variant": selected_variant, "selection_ce": ces,
                      "policy_sha256": sha256(args.output)}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("fit", "select"))
    parser.add_argument("--fit-run", type=Path)
    parser.add_argument("--selection-run", type=Path)
    parser.add_argument("--policies", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    (fit if args.mode == "fit" else select)(args)


if __name__ == "__main__":
    main()
