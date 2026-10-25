"""Positive conditional exponential-value critics, trained only on Vosk fit data.

The acoustic model and template text decoder are frozen. This module trains a
small shared-state action-value interface, not an end-to-end speech generator.
The public feature adapter accepts no source identity, target or terminal ASR.
"""

import argparse
import json
from pathlib import Path
import time

import numpy as np

from .facts import GENERATOR_ACTIONS, PublicFrame, action_cost, action_fact, features
from .audit import sha256, write_json


SEEDS = (17, 29, 43, 59, 71)
FIT_CONFIG = {"hidden": 24, "steps": 1200, "learning_rate": .01, "l2": .001,
              "gamma": 2.0, "positive_output_floor": .001,
              "labels": "exp(-2 * online_Vosk_net_utility)", "external_asr_used": False}
MODES = ("initial_only", "feedback", "feedback_no_probe")


def state_features(frame, mode):
    if mode not in MODES:
        raise ValueError("Unknown policy feature mode")
    return features(frame, initial_only=mode == "initial_only", mask_probe=mode == "feedback_no_probe")


def softplus(value):
    return np.logaddexp(0, value)


def train_model(x, target, seed):
    rng = np.random.default_rng(seed)
    center, scale = x.mean(axis=0), np.maximum(x.std(axis=0), .1)
    x = (x - center) / scale
    hidden = FIT_CONFIG["hidden"]
    arrays = [rng.normal(0, .15, (x.shape[1], hidden)), np.zeros(hidden),
              rng.normal(0, .15, (hidden, len(GENERATOR_ACTIONS))), np.zeros(len(GENERATOR_ACTIONS))]
    first, second = [np.zeros_like(a) for a in arrays], [np.zeros_like(a) for a in arrays]
    initial_loss = None
    for step in range(1, FIT_CONFIG["steps"] + 1):
        w0, b0, w1, b1 = arrays
        h = np.tanh(x @ w0 + b0)
        raw = h @ w1 + b1
        prediction = softplus(raw) + FIT_CONFIG["positive_output_floor"]
        error = prediction - target
        mse = float(np.mean(error ** 2))
        initial_loss = mse if initial_loss is None else initial_loss
        grad = 2 * error / error.size / (1 + np.exp(-np.clip(raw, -40, 40)))
        hgrad = (grad @ w1.T) * (1 - h ** 2)
        gradients = [x.T @ hgrad, hgrad.sum(axis=0), h.T @ grad, grad.sum(axis=0)]
        for index, (array, gradient) in enumerate(zip(arrays, gradients)):
            if index in (0, 2):
                gradient = gradient + FIT_CONFIG["l2"] * array
            first[index] = .9 * first[index] + .1 * gradient
            second[index] = .999 * second[index] + .001 * gradient ** 2
            array -= FIT_CONFIG["learning_rate"] * (first[index] / (1 - .9 ** step)) / (np.sqrt(second[index] / (1 - .999 ** step)) + 1e-8)
    final = softplus(np.tanh(x @ arrays[0] + arrays[1]) @ arrays[2] + arrays[3]) + FIT_CONFIG["positive_output_floor"]
    return {"seed": seed, "center": center.tolist(), "scale": scale.tolist(),
            "parameters": [array.tolist() for array in arrays],
            "initial_fit_mse": initial_loss, "final_fit_mse": float(np.mean((final - target) ** 2)),
            "minimum_fit_positive_value": float(final.min())}


def predict(model, frame, mode):
    x = (state_features(frame, mode) - np.asarray(model["center"])) / np.asarray(model["scale"])
    w0, b0, w1, b1 = (np.asarray(array) for array in model["parameters"])
    values = softplus(np.tanh(x @ w0 + b0) @ w1 + b1) + FIT_CONFIG["positive_output_floor"]
    return values


def public_reference(frame):
    """Declared factorized-prior/no-ASR-error reference, not a global optimum."""
    values = []
    for action in GENERATOR_ACTIONS:
        fact = action_fact(frame, action)
        correct = [p[index] for p, index in zip(frame.posterior, fact)]
        positive_value = 0.0
        for mask in range(8):
            indicators = [(mask >> index) & 1 for index in range(3)]
            probability = np.prod([p if correct_bit else 1 - p for p, correct_bit in zip(correct, indicators)])
            utility = .6 * np.mean(indicators) + .2 + .2 * (sum(indicators) == 3) - action_cost(action)
            positive_value += probability * np.exp(-2 * utility)
        values.append(positive_value)
    return GENERATOR_ACTIONS[int(np.argmin(values))]


class PolicyBundle:
    def __init__(self, payload):
        if payload["config"] != FIT_CONFIG or tuple(payload["seeds"]) != SEEDS:
            raise ValueError("Policy configuration changed after fitting")
        self.payload = payload

    @classmethod
    def load(cls, path):
        return cls(json.loads(Path(path).read_text()))

    def initial_decisions(self, frame):
        return {f"initial_only/{model['seed']}": GENERATOR_ACTIONS[int(np.argmin(predict(model, frame, "initial_only")))]
                for model in self.payload["models"]["initial_only"]}

    def feedback_decisions(self, frame, initial):
        result = dict(initial)
        for mode in ("feedback", "feedback_no_probe"):
            for model in self.payload["models"][mode]:
                result[f"{mode}/{model['seed']}"] = GENERATOR_ACTIONS[int(np.argmin(predict(model, frame, mode)))]
        result.update({"fixed/" + action: action for action in GENERATOR_ACTIONS})
        result["fixed/best_fit"] = self.payload["best_fixed_action"]
        result["public/assumed_prior_reference"] = public_reference(frame)
        result["mechanism/clamped_fuse"] = "fuse_clamp_normal"
        return result


def fit(args):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    run = json.loads((args.fit_run / "run_start.json").read_text())
    complete = json.loads((args.fit_run / "run_complete.json").read_text())
    if run["role"] != "fit" or complete["source_groups"] != 32 or complete["cases"] != 128:
        raise ValueError("Fitting requires all and only the frozen 32 fit groups")
    rows = []
    for line in (args.fit_run / "cases.jsonl").read_text().splitlines():
        entry = json.loads(line)
        if sha256(entry["case_path"]) != entry["case_sha256"]:
            raise ValueError("Executed fit path changed")
        rows.append(json.loads(Path(entry["case_path"]).read_text()))
    keys = {(row["source_id"], row["scenario"]) for row in rows}
    if len(keys) != 128 or len({key[0] for key in keys}) != 32 or any(key[1] not in range(4) for key in keys):
        raise ValueError("Incomplete or duplicated fit source/scenario census")
    if any(outcome["external_terminal_observation"] is not None for row in rows for outcome in row["outcomes"].values()):
        raise ValueError("External ASR outcomes cannot enter the fit data interface")
    frames = [PublicFrame(**row["public_frame"]) for row in rows]
    utility = np.asarray([[row["outcomes"][action]["online_metrics"]["net_utility"]
                           for action in GENERATOR_ACTIONS] for row in rows])
    target = np.exp(-FIT_CONFIG["gamma"] * utility)
    models = {}
    for mode in MODES:
        x = np.asarray([state_features(frame, mode) for frame in frames])
        models[mode] = [train_model(x, target, seed) for seed in SEEDS]
    fixed_ce = -np.log(target.mean(axis=0)) / FIT_CONFIG["gamma"]
    payload = {"schema": "hepta.abc3.positive-temporal-conditional-value.v1", "config": FIT_CONFIG,
               "seeds": SEEDS, "models": models, "best_fixed_action": GENERATOR_ACTIONS[int(np.argmax(fixed_ce))],
               "fit_fixed_ce": dict(zip(GENERATOR_ACTIONS, fixed_ce.tolist())),
               "fit_source_groups": 32, "fit_cases": len(rows),
               "fit_run_index_sha256": sha256(args.fit_run / "cases.jsonl"),
               "policy_code_sha256": sha256(__file__), "qualification_sha256": run["qualification_sha256"],
               "wall_ns_before_report": time.perf_counter_ns() - started,
               "cpu_ns_before_report": time.process_time_ns() - cpu}
    write_json(args.output, payload)
    print(json.dumps({"policy_sha256": sha256(args.output), "best_fixed_action": payload["best_fixed_action"],
                      "fit_fixed_ce": payload["fit_fixed_ce"], "fit_wall_ns": payload["wall_ns_before_report"]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fit-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    fit(parser.parse_args())


if __name__ == "__main__":
    main()
