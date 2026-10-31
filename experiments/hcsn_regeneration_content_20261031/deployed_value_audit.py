"""Frozen-policy continuation values, separate from optimal teacher targets."""

import argparse
from dataclasses import replace
import gzip
import hashlib
import json
from pathlib import Path
import re
import time

import numpy as np

try:
    from . import policy, policy_audit, policy_run, run_study
    from .content import Model
    from .content_tasks import multimodal_support
except ImportError:
    import policy
    import policy_audit
    import policy_run
    import run_study
    from content import Model
    from content_tasks import multimodal_support


BASE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def deployed_values(graph, controller):
    """Compute Q^pi for every forced first action, with pi on every successor."""
    values, action_values, choices, estimates = {}, {}, {}, {}
    for history in sorted(graph.nodes, key=len, reverse=True):
        node = graph.nodes[history]
        action, scores = controller.choose(graph.model, node["state"], graph.config)
        q = {"STOP": node["q"]["STOP"]}
        for candidate, edges in node["edges"].items():
            fee = graph.config.read_cost if candidate == "READ" else graph.config.skip_cost
            q[candidate] = -fee + sum(p * values[child] for p, child, _ in edges)
        assert action in q
        action_values[history], values[history] = q, q[action]
        choices[history], estimates[history] = action, scores
    occupancy = {(): 1.}
    terminal_mass, optimal_regret = 0., 0.
    for history in sorted(graph.nodes, key=len):
        mass, node, action = occupancy.get(history, 0.), graph.nodes[history], choices[history]
        optimal_regret += mass * (node["value"] - node["q"][action])
        if action == "STOP":
            terminal_mass += mass
        else:
            for probability, child, _ in node["edges"][action]:
                occupancy[child] = occupancy.get(child, 0.) + mass * probability
    exact = graph.exact_policy(controller)
    parity = abs(values[()] - exact["return"])
    regret_error = abs(graph.nodes[()]["value"] - values[()] - optimal_regret)
    assert abs(terminal_mass - 1.) < 2e-10 and parity < 2e-10 and regret_error < 2e-10
    return {"values": values, "q": action_values, "choices": choices,
            "predictions": estimates, "occupancy": occupancy,
            "terminal_mass": terminal_mass, "policy_value_parity_error": parity,
            "optimal_regret_identity_error": regret_error}


def calibration(graph, result):
    rows = []
    state_improvement, weighted_improvement, decision_mass = [], 0., 0.
    for history, node in graph.nodes.items():
        q_pi, prediction = result["q"][history], result["predictions"][history]
        mass = result["occupancy"].get(history, 0.)
        improvement = max(q_pi.values()) - result["values"][history]
        state_improvement.append(improvement)
        weighted_improvement += mass * improvement
        decision_mass += mass
        for action in ("READ", "SKIP"):
            if action not in q_pi:
                continue
            rows.append({"action": action, "prediction": prediction[action], "occupancy": mass,
                         "optimal": node["q"][action] - node["q"]["STOP"],
                         "deployed": q_pi[action] - q_pi["STOP"]})
    report = {}
    for target in ("optimal", "deployed"):
        report[target] = {}
        for weighting in ("uniform", "pi_occupancy"):
            report[target][weighting] = {}
            for action in ("all", "READ", "SKIP"):
                selected = [row for row in rows if action == "all" or row["action"] == action]
                weights = np.array([1. if weighting == "uniform" else row["occupancy"] for row in selected])
                denominator = float(weights.sum())
                error = np.array([row["prediction"] - row[target] for row in selected])
                sign = np.array([(row["prediction"] > 0) == (row[target] > 0) for row in selected])
                near_zero = np.array([abs(row[target]) < 1e-10 for row in selected])
                report[target][weighting][action] = {
                    "legal_state_action_pairs": len(selected), "weight_sum": denominator,
                    "rmse": None if not denominator else float(np.sqrt(np.dot(weights, error ** 2) / denominator)),
                    "mean_error": None if not denominator else float(np.dot(weights, error) / denominator),
                    "sign_accuracy": None if not denominator else float(np.dot(weights, sign) / denominator),
                    "near_zero_target_weight": float(np.dot(weights, near_zero))}
    return {"advantage_calibration": report,
            "uniform_state_one_step_policy_improvement_regret": float(np.mean(state_improvement)),
            "occupancy_one_step_policy_improvement_regret_sum": weighted_improvement,
            "expected_decision_mass_including_stop": decision_mass,
            "weighting_scope": "Uniform or pi-occupancy weights on legal state-action pairs; each head also separate.",
            "target_scope": "optimal=Q* continuation; deployed=forced first action then same frozen pi."}


class ForcedFirst:
    """Root intervention, then the exact same frozen public-feature policy."""

    def __init__(self, following, action):
        self.following, self.action = following, action

    def choose(self, model, state, config):
        selected, scores = self.following.choose(model, state, config)
        if state.slot == 0:
            return self.action, {**scores, "forced_root": 1.}
        return selected, scores


def save_states(path, graph, result):
    with gzip.open(path, "xt", encoding="utf-8") as stream:
        for history, node in graph.nodes.items():
            record = {"history": history, "state_sha256": policy.state_digest(node["state"]),
                      "posterior_teacher_only": node["posterior"],
                      "q_optimal": node["q"], "q_deployed": result["q"][history],
                      "v_optimal": node["value"], "v_deployed": result["values"][history],
                      "learned_advantages": result["predictions"][history],
                      "deployed_action": result["choices"][history],
                      "pi_occupancy": result["occupancy"].get(history, 0.)}
            stream.write(json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n")


def cost_ray(graph, controller):
    original = graph.config
    rows = []
    try:
        for cost in np.linspace(0., .5, 21):
            graph.config = replace(original, read_cost=float(cost))
            graph.solve()
            deployed = deployed_values(graph, controller)
            q_star, q_pi = graph.nodes[()]["q"], deployed["q"][()]
            scores, action = deployed["predictions"][()], deployed["choices"][()]
            rows.append({"read_cost": float(cost), "learned_action": action,
                         "predicted_advantages": scores,
                         "predicted_continuation_advantage": max(scores[a] for a in ("READ", "SKIP")),
                         "q_optimal": dict(q_star), "q_deployed": q_pi,
                         "optimal_continuation_advantage": max(q_star[a] for a in ("READ", "SKIP")) - q_star["STOP"],
                         "deployed_continuation_advantage": max(q_pi[a] for a in ("READ", "SKIP")) - q_pi["STOP"],
                         "deployed_selected_action_advantage": q_pi[action] - q_pi["STOP"],
                         "deployed_policy_value": deployed["values"][()],
                         "oracle_policy_value": graph.nodes[()]["value"]})
    finally:
        graph.config = original
        graph.solve()
    monotonic = {key: bool(np.max(np.diff([row[key] for row in rows])) <= 1e-10)
                 for key in ("predicted_continuation_advantage", "optimal_continuation_advantage",
                             "deployed_continuation_advantage")}
    return {"rows": rows, "nonincreasing": monotonic,
            "scope": "Same learned weights, policy receives changed public cost; pi may change action discontinuously.",
            "interpretation": "Task-value surfaces; no smooth-pasting or unique scalar membrane threshold claim."}


def audit_model(family, seed, folder):
    tag = f"{family}_s{seed}"
    model_path = BASE / f"evidence/content/runs/multimodal_evidence/{family}_w16_s{seed}/final.npz"
    controller_path = BASE / f"evidence/policy/fits/{tag}/controller.json"
    payload = json.loads(controller_path.read_text())
    assert payload["source"] == policy_run.identity(model_path)
    model, controller = Model.load(model_path), policy_run.controller_from(payload["value"])
    folder.mkdir(parents=True, exist_ok=False)
    cases = []
    for index, config in enumerate(policy.configurations()["heldout"]):
        graph = policy_run.build_graph(model, config)
        deployed = deployed_values(graph, controller)
        save_states(folder / f"{config.name}_values.jsonl.gz", graph, deployed)
        row = {"config": config.payload(), "histories": len(graph.nodes),
               "calibration": calibration(graph, deployed),
               "q_root_optimal": graph.nodes[()]["q"].copy(),
               "q_root_deployed": deployed["q"][()].copy(),
               "root_policy_value": deployed["values"][()],
               "root_oracle_value": graph.nodes[()]["value"],
               "policy_value_parity_error": deployed["policy_value_parity_error"],
               "optimal_regret_identity_error": deployed["optimal_regret_identity_error"],
               "terminal_mass": deployed["terminal_mass"]}
        if index == 0:
            interventions = {}
            with gzip.open(folder / "forced_first_actual_worlds.jsonl.gz", "xt", encoding="utf-8") as stream:
                for action in policy.ACTIONS:
                    intervention = ForcedFirst(controller, action)
                    def sink(record):
                        stream.write(json.dumps({"forced_first_action": action, **record},
                                                separators=(",", ":"), allow_nan=False) + "\n")
                    actual = policy_audit.independent_expectation(
                        model, config, multimodal_support, intervention, graph, sink)
                    actual["q_deployed_root"] = deployed["q"][()][action]
                    actual["q_deployed_absolute_error"] = abs(
                        actual["actual_expected_return"] - actual["q_deployed_root"])
                    assert actual["q_deployed_absolute_error"] < 2e-10
                    interventions[action] = actual
            row["forced_first_actual_execution"] = interventions
            row["root_cost_ray"] = cost_ray(graph, controller)
        cases.append(row)
    return {"family": family, "seed": seed, "width": 16,
            "model_sha256": sha(model_path), "controller_sha256": sha(controller_path), "cases": cases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-commit", required=True)
    parser.add_argument("--audit-commit", required=True)
    parser.add_argument("--output", default="evidence/deployed_value/formal_01")
    args = parser.parse_args()
    if not all(re.fullmatch("[0-9a-f]{40}", v) for v in (args.candidate_commit, args.audit_commit)):
        parser.error("Previously published candidate and audit commits are required")
    freeze_path = BASE / "DEPLOYED_VALUE_FREEZE.json"
    freeze = json.loads(freeze_path.read_text())
    for name, expected in freeze["source_sha256"].items():
        if sha(BASE / name) != expected:
            raise RuntimeError("Audit source changed after its freeze: " + name)
    primary_source = run_study.verify_freeze()
    run_study.verify_candidate(args.candidate_commit, primary_source)
    folder = BASE / args.output
    folder.mkdir(parents=True, exist_ok=False)
    cpu, wall = time.process_time(), time.perf_counter()
    models = []
    for family in ("ordinary", "analytic"):
        for seed in (11, 23, 37):
            tag = f"{family}_s{seed}"
            result = audit_model(family, seed, folder / tag)
            write_json(folder / tag / "AUDIT.json", result)
            models.append(result)
            print(json.dumps({"completed": tag, "cases": len(result["cases"])}), flush=True)
    for name, expected in freeze["source_sha256"].items():
        assert sha(BASE / name) == expected
    write_json(folder / "SUMMARY.json", {
        "schema": "hcsn.deployed-continuation-audit.v1", "candidate_commit": args.candidate_commit,
        "audit_commit": args.audit_commit, "audit_freeze_sha256": sha(freeze_path),
        "primary_source_freeze_sha256": primary_source, "models": models,
        "cpu_before_final_receipt": time.process_time() - cpu,
        "wall_before_final_receipt": time.perf_counter() - wall,
        "scope": "Read-only audit of already frozen models; no refit, reselection or modified policy.",
        "critical_distinction": "Q* target calibration is separate from actual frozen-policy Qpi continuation calibration."})


if __name__ == "__main__":
    main()
