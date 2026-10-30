"""Finite-horizon Bellman learning with physical replay and original native NDU.

All future decisions use the same registered continuation recursion. The finite
state value projection and learned transition error are explicit approximations;
this is not an exact solution of the continuous-state control problem.
"""

import argparse
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from experiments.first_passage_cell.cell import CellParameters
from experiments.first_passage_cell.kernels import first_passage
from .ndu_value import BellmanNduPort
from experiments.first_passage_cell.task import MaintenanceTask
from experiments.first_passage_cell.value import action_values
from .markov import BIN_COUNT, representative_states, transition_and_reward
from .operators import RegenerativeSpec
from .value_learning import HERE, load_model, verify_freeze

PLAN = "FINITE_HORIZON_REPLAN_SAME_BELLMAN_RECURSION"


def context_rows(spec, distances, pending, horizon=0.5):
    x, eta = np.broadcast_arrays(np.asarray(distances, float), np.asarray(pending, float))
    return np.column_stack([np.full(x.size, spec.mu), np.full(x.size, spec.sigma),
                            np.full(x.size, spec.reset), np.full(x.size, spec.refractory),
                            np.full(x.size, spec.discount), x.ravel(), np.full(x.size, horizon), eta.ravel()])


class BellmanLayer:
    """Nonexpansive finite-step backup on a positive transition-bin basis."""

    def __init__(self, spec, model=None):
        if spec.discount != 0:
            raise ValueError("the retained maintenance objective uses undiscounted physical rewards")
        self.spec, self.model = spec, model
        self.fallbacks = 0
        x, eta = representative_states(spec)
        self.refractory_states = eta > 0
        self.transitions, self.events, self.active = self.predict(x, eta)
        self.repair = self.predict([spec.reset], [spec.refractory])

    def predict(self, distances, pending):
        rows = context_rows(self.spec, distances, pending)
        if self.model is None:
            use_exact = np.ones(len(rows), dtype=bool)
            transition = np.zeros((len(rows), BIN_COUNT))
            events, active = np.zeros(len(rows)), np.zeros(len(rows))
        else:
            with torch.no_grad():
                moments, probabilities = self.model.outputs(torch.from_numpy(rows))
            transition = probabilities.numpy()
            events, active = moments[:, 8].numpy(), moments[:, 9].numpy()
            use_exact = (rows[:, 5] < 0.015) | (rows[:, 5] > 4.0)
            self.fallbacks += int(use_exact.sum())
        for index in np.flatnonzero(use_exact):
            transition[index], events[index], active[index] = transition_and_reward(
                self.spec, rows[index, 5], rows[index, 6], rows[index, 7])
        if (not np.isfinite(transition).all() or transition.min() < 0 or
                np.max(np.abs(transition.sum(axis=1) - 1)) > 5e-10):
            raise ArithmeticError("Bellman transition violates positive unit-mass contract")
        return transition, events, active

    def fit(self, cost):
        """Backwards fitted value iteration on the fixed20-bin state projection."""
        layers = [np.zeros(BIN_COUNT)]
        repair_p, repair_n, repair_a = self.repair
        for _ in range(4):
            wait = 0.6 * self.active - 0.5 * self.events + self.transitions @ layers[-1]
            repair = float(0.6 * repair_a[0] - 0.5 * repair_n[0] - cost + repair_p[0] @ layers[-1])
            value = np.maximum(0.0, wait)
            value[~self.refractory_states] = np.maximum(value[~self.refractory_states], repair)
            layers.append(value)
        return layers

    def forecast(self, observation, layers):
        remaining_steps = 4 - observation["decision_index"]
        continuation = layers[remaining_steps - 1]
        p, n, active = self.predict([max(0.0, observation["level"])], [observation["refractory_remaining"]])
        rows = {"WAIT": (p[0], float(n[0]), float(active[0]), 0.0,
                         observation["level"], observation["refractory_remaining"])}
        if "repair" in observation["legal_actions"]:
            rp, rn, ra = self.repair
            rows["REPAIR"] = (rp[0], float(rn[0]), float(ra[0]), observation["repair_cost"],
                               self.spec.reset, self.spec.refractory)
        paths = {"STOP": {"events": [{"instant": 0.0, "discount": 1.0}], "terminal": 0.0,
                           "resource_cost": 0.0, "risk": 0.0}}
        predicted = {}
        for action, (probability, count, occupied, cost, x, eta) in rows.items():
            instant = 0.6 * occupied - 0.5 * count - cost
            future = float(probability @ continuation)
            risk = float(first_passage(x, self.spec.mu, self.spec.sigma, max(0.0, 0.5 - eta))["F"])
            paths[action] = {"events": [{"instant": instant, "discount": 1.0}],
                             "terminal": future, "resource_cost": cost, "risk": risk}
            predicted[action] = {"immediate": instant, "continuation": future,
                                 "expected_events": count, "expected_active_time": occupied,
                                 "value": instant + future}
        return paths, predicted


def choose_native_values(receipt):
    """The task maximizes the unchanged scalar utility; ties prefer STOP then WAIT."""
    order = {"STOP": 0, "WAIT": 1, "REPAIR": 2}
    values = receipt["action_values"]
    return min(values, key=lambda action: (-values[action], order[action])).lower()


def write_parts(records, directory):
    directory.mkdir(parents=True, exist_ok=True)
    files = []
    index = 0
    for start in range(0, len(records), 16):
        stack = [records[start:start+16]]
        while stack:
            part = stack.pop(0)
            raw = b"".join(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
                           + b"\n" for row in part)
            compressed = gzip.compress(raw, mtime=0)
            if len(compressed) > 490000:
                if len(part) == 1:
                    raise ValueError("single episode exceeds the retained blob limit")
                middle = len(part) // 2
                stack[:0] = [part[:middle], part[middle:]]
                continue
            path = directory / f"part-{index:03d}.jsonl.gz"
            path.write_bytes(compressed)
            files.append({"path": str(path.relative_to(HERE)), "sha256": hashlib.sha256(compressed).hexdigest(),
                          "bytes": len(compressed), "records": len(part)})
            index += 1
    return files


def run_confirmation(protocol, output, freeze):
    identity = verify_freeze(freeze)
    if (output / "CONTROL_CONFIRMATION.json").exists():
        raise FileExistsError("retain the original control confirmation")
    output.mkdir(parents=True, exist_ok=True)
    native = BellmanNduPort(HERE.parent / "first_passage_cell/NATIVE_BUILD.json")
    control = protocol["control"]
    result, files = [], []
    count = control["scenarios_per_law_seed"]
    for seed in protocol["model_seeds"]:
        model = load_model(HERE / "value_evidence" / f"model-{seed}.npz")
        for law_index, law in enumerate(control["task_laws"]):
            spec = RegenerativeSpec(law["mu"], law["sigma"], law["reset"], law["refractory"])
            parameters = CellParameters(spec.mu, (0.0, 0.0), spec.sigma, 0.0, spec.reset, spec.refractory)
            planners = {"learned_operator_bellman": BellmanLayer(spec, model),
                        "analytic_operator_bellman": BellmanLayer(spec)}
            rng = np.random.default_rng(np.random.SeedSequence([control["seed"], seed, law_index]))
            scenarios = [{"identity": f"operator-control:{seed}:{law['name']}:{index}", "inputs": [0.0, 0.0],
                          "level": float(rng.uniform(0.08, 1.4)), "repair_cost": float(rng.uniform(0.05, 0.4)),
                          "noise_seed": int(rng.integers(1, 2**63 - 1))} for index in range(count)]
            for arm in control["arms"]:
                started = time.perf_counter()
                records, utilities = [], []
                maximum_q32_error, decisions = 0.0, 0
                for scenario in scenarios:
                    task = MaintenanceTask(scenario, parameters)
                    initial = task.observation()
                    layers = planners[arm].fit(scenario["repair_cost"]) if arm in planners else None
                    forecasts = []
                    while not task.done:
                        observation = task.observation()
                        if arm in planners:
                            paths, prediction = planners[arm].forecast(observation, layers)
                            plan = PLAN
                        else:
                            values = action_values(parameters, observation, mode="renewal")
                            paths, prediction = values["actions"], values
                            plan = "WAIT_AFTER_CURRENT"
                        snapshot = {"schema": "hepta.regenerative.bellman.snapshot.v1", "freeze_sha256": identity,
                                    "seed": seed, "law": law, "arm": arm, "observation": observation,
                                    "continuation_plan": plan, "deployment": PLAN if arm in planners else "MPC_REPLAN_EACH_HALF",
                                    "state_projection": "positive20-bin-continuation" if arm in planners else None,
                                    "same_dynamics_information_for_all_arms": True}
                        receipt = native.evaluate_paths(paths, snapshot, generation=observation["decision_index"] + 1)
                        action = choose_native_values(receipt)
                        forecasts.append({"prediction": prediction, "native": receipt, "executed_action": action,
                                          "native_pareto_advisory": receipt["response"]["advisory_candidate_id"]})
                        task.step(action)
                        decisions += 1
                    actual = native.evaluate_realized(parameters, initial, task.ledger,
                                                        context={"operator_freeze": identity, "policy": arm})
                    error = abs(actual["realized_native_return"] - task.total_reward)
                    if error > actual["roundoff_bound"]:
                        raise ArithmeticError("actual native recursion exceeds its Q32 error bound")
                    maximum_q32_error = max(maximum_q32_error, error)
                    utilities.append(task.total_reward)
                    records.append({"scenario": scenario, "arm": arm, "seed": seed, "law": law,
                                    "forecasts": forecasts, "actual": actual, "utility": task.total_reward,
                                    "actual_failures": sum(x["outcome"]["failure_count"] for x in task.ledger),
                                    "actual_repair_cost": sum(x["action_cost"] for x in task.ledger)})
                directory = output / "episodes" / law["name"] / str(seed) / arm
                files.extend(write_parts(records, directory))
                row = {"seed": seed, "law": law["name"], "arm": arm, "episodes": count,
                       "mean_utility": float(np.mean(utilities)), "utilities": utilities,
                       "mean_failures": float(np.mean([r["actual_failures"] for r in records])),
                       "mean_repair_cost": float(np.mean([r["actual_repair_cost"] for r in records])),
                       "maximum_actual_q32_error": maximum_q32_error, "decisions": decisions,
                       "out_of_domain_exact_fallbacks": planners[arm].fallbacks if arm in planners else 0,
                       "wall_seconds": time.perf_counter() - started}
                result.append(row)
                print(json.dumps({k:v for k,v in row.items() if k != "utilities"}), flush=True)
    comparisons = []
    for law in control["task_laws"]:
        for baseline in ("analytic_operator_bellman", "wait_after_current"):
            differences = []
            seed_means = []
            for seed in protocol["model_seeds"]:
                selected = {r["arm"]: np.array(r["utilities"]) for r in result if r["seed"] == seed and r["law"] == law["name"]}
                difference = selected["learned_operator_bellman"] - selected[baseline]
                seed_means.append(float(difference.mean()))
                differences.extend(difference.tolist())
            comparisons.append({"law": law["name"], "comparison": "learned_operator_bellman - " + baseline,
                                "mean_paired_utility_difference": float(np.mean(differences)), "seed_means": seed_means,
                                "scope": "descriptive paired task returns; no superiority claim or population coverage guarantee"})
    report = {"schema": "hepta.regenerative.bellman.control-confirmation.v1", "freeze_sha256": identity,
              "native_binary_sha256": native.binary_sha256, "native_calls": native.calls,
              "episodes": sum(row["episodes"] for row in result), "rows": result, "comparisons": comparisons,
              "files": files, "actual_utility_contract": "0.6*actual_active_time -0.5*actual_failures -actual_paid_repair_cost",
              "continuation_contract": PLAN, "authority": "DENY_ALL", "safety_certificate": False,
              "decision_contract": "Maximize native scalar-Q32 values; native Pareto advisory retained separately as in original research port."}
    (output / "CONTROL_CONFIRMATION.json").write_text(json.dumps(report, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=HERE / "control_evidence")
    args = parser.parse_args()
    torch.set_num_threads(1)
    protocol = json.loads((HERE / "VALUE_PROTOCOL.json").read_text())
    run_confirmation(protocol, args.output, args.freeze)


if __name__ == "__main__":
    main()
