"""Post-confirmation evidence audit, separate from frozen training/evaluation.

Recompute reported metrics from retained arrays, inspect every signed-Q32 path
and physical cost ledger, and replay every recorded action sequence. Replay uses
the unchanged simulator and is a reproducibility check, not an independent proof
of its stochastic law; independent integration/QVI checks are retained separately.
"""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from fractions import Fraction
import gzip
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

from experiments.first_passage_cell.cell import CellParameters
from experiments.first_passage_cell.task import MaintenanceTask

HERE = Path(__file__).resolve().parent
Q = 1 << 32
LIMIT = 1_000_000 * Q
PROFILE = "hepta.ndu.recursive-utility.scalar.q32.v1"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def close(actual, expected, tolerance=2e-12):
    if not math.isclose(float(actual), float(expected), abs_tol=tolerance, rel_tol=tolerance):
        raise AssertionError((actual, expected, tolerance))


def check_file(item, root=HERE):
    data = (root / item["path"]).read_bytes()
    assert digest(data) == item["sha256"], item["path"]
    assert len(data) == item["bytes"], item["path"]
    return data


def check_freeze():
    freeze = json.loads((HERE / "SOURCE_FREEZE.json").read_text())
    for item in freeze["files"]:
        check_file(item)
    for item in freeze["external_files"]:
        check_file(item, HERE.parent)
    return {"frozen_files": len(freeze["files"]),
            "external_dependencies": len(freeze["external_files"]),
            "freeze_sha256": digest((HERE / "SOURCE_FREEZE.json").read_bytes())}


def audit_value():
    report = json.loads((HERE / "value_evidence/CONFIRMATION.json").read_text())
    protocol = json.loads((HERE / "VALUE_PROTOCOL.json").read_text())
    context_parts, target_parts = [], []
    for item in report["reference_files"]:
        check_file(item)
        with np.load(HERE / item["path"], allow_pickle=False) as data:
            context_parts.append(data["contexts"])
            target_parts.append(data["targets"])
    contexts, targets = np.concatenate(context_parts), np.concatenate(target_parts)
    assert len(contexts) == report["rows"] == protocol["confirmation_rows"]
    rows = []
    for saved in report["results"]:
        seed = saved["seed"]
        parts = []
        for path in sorted((HERE / "value_evidence/confirmation").glob(f"prediction-{seed}-*.npz")):
            with np.load(path, allow_pickle=False) as data:
                parts.append({key: data[key] for key in data.files})
        arrays = {key: np.concatenate([part[key] for part in parts]) for key in parts[0]}
        prediction, transition, payoff = (arrays[key] for key in ("predictions", "transitions", "payoff"))
        assert np.isfinite(prediction).all() and np.isfinite(transition).all()
        assert np.min(transition) >= 0
        np.testing.assert_allclose(transition.sum(1), 1, atol=5e-15, rtol=0)
        np.testing.assert_allclose(np.linalg.norm(payoff, axis=1), 1, atol=5e-15, rtol=0)
        error = prediction - targets[:, :10]
        payoff_error = np.einsum("ij,ij->i", error, payoff)
        tv = np.abs(transition - targets[:, 10:]).sum(1) / 2
        mass = prediction[:, 0] + prediction[:, 5] - np.exp(-contexts[:, 4] * contexts[:, 6])
        observed = {
            "moment_rmse": float(np.linalg.norm(error) / math.sqrt(error.size)),
            "maximum_absolute_moment_error": float(np.abs(error).max()),
            "value_rmse_unit_l2_payoff": float(np.linalg.norm(payoff_error) / math.sqrt(len(error))),
            "maximum_absolute_value_error": float(np.abs(payoff_error).max()),
            "max_discounted_mass_defect": float(np.abs(mass).max()),
            "mean_transition_total_variation": float(tv.mean()),
            "maximum_transition_total_variation": float(tv.max()),
        }
        for key, value in observed.items():
            close(value, saved[key])
        gate = protocol["heldout_gate"]
        passed = (observed["moment_rmse"] <= gate["moment_rmse"]
                  and observed["value_rmse_unit_l2_payoff"] <= gate["value_rmse_unit_l2_payoff"]
                  and observed["max_discounted_mass_defect"] <= gate["mass_defect"]
                  and observed["mean_transition_total_variation"] <= gate["mean_transition_total_variation"])
        assert passed == saved["gate_passed"]
        rows.append({"seed": seed, **observed, "gate_passed": passed})
    return {"contexts": len(contexts), "seeds": len(rows), "passed_mean_error_gates": sum(r["gate_passed"] for r in rows),
            "results": rows, "uniform_accuracy_certified": False}


def audit_network():
    protocol = json.loads((HERE / "NETWORK_PROTOCOL.json").read_text())
    summary = json.loads((HERE / "network_evidence/CONFIRMATION_SUMMARY.json").read_text())
    measurements, rows = {}, []
    maximum_bce_discrepancy = 0.0
    saturated_probabilities = 0
    for task in ("evidence", "order", "delayed_match"):
        with np.load(HERE / "network_evidence" / f"confirmation_arrays_{task}.npz", allow_pickle=False) as arrays:
            for seed in protocol["seeds"]:
                label = arrays[f"{task}_{seed}_labels"]
                for kind in ("first_passage", "lif", "rnn"):
                    prefix = f"{task}_{kind}_{seed}"
                    loss, probability, correct = (arrays[prefix + "_" + key] for key in ("loss", "probability", "correct"))
                    assert loss.shape == probability.shape == correct.shape
                    assert np.isfinite(loss).all() and np.isfinite(probability).all()
                    interior = (probability > 0) & (probability < 1)
                    saturated_probabilities += int((~interior).sum())
                    y = np.broadcast_to(label, probability.shape)
                    p = probability[interior]
                    independent = -y[interior] * np.log(p) - (1 - y[interior]) * np.log1p(-p)
                    discrepancy = float(np.max(np.abs(independent - loss[interior])))
                    maximum_bce_discrepancy = max(maximum_bce_discrepancy, discrepancy)
                    assert discrepancy < 2e-9, (prefix, discrepancy)
                    assert np.array_equal(correct, (probability >= 0.5) == y)
                    measurements[(task, kind, seed)] = loss.mean(0)
                    rows.append({"task": task, "kind": kind, "seed": seed, "bce": float(loss.mean()),
                                 "accuracy": float(correct.mean())})
    rng = np.random.default_rng(protocol["bootstrap_seed"])
    comparisons = []
    for saved in summary["comparisons"]:
        task, baseline = saved["task"], saved["baseline"]
        delta = np.stack([measurements[(task, baseline, seed)] - measurements[(task, "first_passage", seed)]
                          for seed in protocol["seeds"]])
        close(delta.mean(), saved["loss_improvement"])
        np.testing.assert_allclose(delta.mean(1), saved["seed_means"], atol=2e-14, rtol=0)
        boot = []
        for _ in range(protocol["bootstrap_replicates"]):
            selected = rng.integers(delta.shape[0], size=delta.shape[0])
            estimates = [delta[i, rng.integers(delta.shape[1], size=delta.shape[1])].mean() for i in selected]
            boot.append(float(np.mean(estimates)))
        tail = 0.05 / 12
        interval = np.quantile(boot, [tail, 1 - tail])
        np.testing.assert_allclose(interval, saved["simultaneous_empirical_interval"], atol=2e-14, rtol=0)
        passed = bool(interval[0] > protocol["advantage_margin"] and np.all(delta.mean(1) > 0))
        assert passed == saved["passes_advantage_gate"]
        comparisons.append({"task": task, "baseline": baseline, "mean_improvement": float(delta.mean()),
                            "interval": interval.tolist(), "passed": passed})
    return {"fits": len(rows), "comparisons": comparisons, "task_metrics": rows,
            "passed_advantage_gates": sum(r["passed"] for r in comparisons),
            "maximum_bce_reconstruction_discrepancy": maximum_bce_discrepancy,
            "saturated_probability_entries": saturated_probabilities,
            "scope": "reproduced registered empirical intervals; no population coverage theorem"}


def audit_native(receipt, expected_binary):
    request, response, snapshot = (receipt[key] for key in ("request", "response", "snapshot"))
    assert digest(canonical(request)) == response["request_digest"]
    assert digest(canonical(snapshot)) == request["snapshot_digest"] == response["snapshot_digest"]
    assert digest(canonical(snapshot["objective"])) == request["objective_digest"] == response["objective_digest"]
    assert request["recursive_profile"] == response["identity"]["recursive_profile"] == PROFILE
    assert receipt["binary_sha256"] == expected_binary
    assert response["authority"] == response["identity"]["authority"] == "DENY_ALL"
    assert response["safety_certificate"] is False and response["identity"]["safety_certificate"] is False
    assert response["rejected"] == []
    candidates = {row["id"]: row for row in request["candidates"]}
    assert len(candidates) == len(request["candidates"]) == len(response["paths"])
    for path in response["paths"]:
        candidate = candidates[path["id"]]
        # Independent rational arithmetic, with nearest/ties-even rounding.
        values = [int(candidate["terminal_q32"])]
        projections = 0
        for event in reversed(candidate["events"]):
            assert event["preference_digest"] == request["objective_digest"]
            raw = int(event["instant_q32"]) + round(Fraction(int(event["discount_q32"]) * values[0], Q))
            value = min(LIMIT, max(-LIMIT, raw))
            projections += value != raw
            values.insert(0, value)
        assert values == path["values_q32"] and projections == path["projection_count"]
        for key in ("support_digest", "verification_digest", "resource_cost_q32", "risk_q32"):
            assert path[key] == candidate[key]
        action = receipt["native_candidate_to_action"][path["id"]]
        assert receipt["action_values"][action] == values[0] / Q
    return len(candidates)


def audit_control():
    report = json.loads((HERE / "control_evidence/CONTROL_CONFIRMATION.json").read_text())
    groups = defaultdict(list)
    scenarios = {}
    identities = set()
    episodes = native_calls = native_paths = replayed_transitions = 0
    pareto_difference = 0
    out_of_domain = 0
    max_q32_error = 0.0
    priority = {"STOP": 0, "WAIT": 1, "REPAIR": 2}
    for item in report["files"]:
        compressed = check_file(item)
        records = [json.loads(line) for line in gzip.decompress(compressed).splitlines()]
        assert len(records) == item["records"]
        for record in records:
            scenario, arm, law, seed = (record[key] for key in ("scenario", "arm", "law", "seed"))
            identity = (scenario["identity"], arm)
            assert identity not in identities
            identities.add(identity)
            scenario_digest = digest(canonical(scenario))
            assert scenarios.setdefault(scenario["identity"], scenario_digest) == scenario_digest
            actual = record["actual"]
            ledger = actual["snapshot"]["transitions"]
            assert len(ledger) == len(record["forecasts"])
            parameters = CellParameters(law["mu"], (0.0, 0.0), law["sigma"], 0.0, law["reset"], law["refractory"])
            replay = MaintenanceTask(scenario, parameters)
            rewards, costs, failures = [], [], []
            for step, forecast in zip(ledger, record["forecasts"], strict=True):
                receipt = forecast["native"]
                native_paths += audit_native(receipt, report["native_binary_sha256"])
                native_calls += 1
                observation = receipt["snapshot"]["observation"]
                assert observation == step["observation"] == replay.observation()
                assert set(receipt["action_values"]) == {a.upper() for a in observation["legal_actions"]}
                choice = min(receipt["action_values"], key=lambda a: (-receipt["action_values"][a], priority[a])).lower()
                assert choice == forecast["executed_action"] == step["action"]
                advisory = forecast["native_pareto_advisory"]
                advisory_action = receipt["native_candidate_to_action"].get(advisory)
                pareto_difference += advisory_action != choice.upper()
                expected_plan = "WAIT_AFTER_CURRENT" if arm == "wait_after_current" else "FINITE_HORIZON_REPLAN_SAME_BELLMAN_RECURSION"
                assert receipt["snapshot"]["continuation_plan"] == expected_plan
                if arm == "learned_operator_bellman":
                    out_of_domain += not 0.015 <= observation["level"] <= 4.0
                cost = observation["repair_cost"] if choice == "repair" else 0.0
                active, count = step["outcome"]["active_duration"], step["outcome"]["failure_count"]
                reward = 0.6 * active - 0.5 * count - cost
                close(reward, step["reward"])
                close(cost, step["action_cost"])
                assert count == len(step["outcome"]["events"])
                assert choice in observation["legal_actions"]
                replay.step(choice)
                assert canonical(replay.ledger[-1]) == canonical(step), (identity, observation["decision_index"])
                replayed_transitions += 1
                rewards.append(reward)
                costs.append(cost)
                failures.append(count)
            assert replay.done and ledger[-1]["done"]
            utility = math.fsum(rewards)
            close(utility, record["utility"])
            close(sum(costs), record["actual_repair_cost"])
            assert sum(failures) == record["actual_failures"]
            native_paths += audit_native(actual, report["native_binary_sha256"])
            native_calls += 1
            realized = next(x for x in actual["request"]["candidates"] if x["id"] == "realized")
            assert realized["terminal_q32"] == 0
            assert [e["instant_q32"] for e in realized["events"]] == [round(Fraction.from_float(x) * Q) for x in rewards]
            error = abs(actual["realized_native_return"] - utility)
            assert error <= actual["roundoff_bound"]
            max_q32_error = max(max_q32_error, error)
            groups[(seed, law["name"], arm)].append(record["utility"])
            episodes += 1
        if episodes % 384 == 0:
            print(json.dumps({"audited_episodes": episodes, "native_calls": native_calls}), flush=True)
    assert episodes == report["episodes"] == 3456
    assert native_calls == report["native_calls"] == 17280
    for row in report["rows"]:
        utilities = groups[(row["seed"], row["law"], row["arm"])]
        np.testing.assert_array_equal(utilities, row["utilities"])
        close(np.mean(utilities), row["mean_utility"])
    assert len(scenarios) * 3 == episodes
    assert out_of_domain == sum(x["out_of_domain_exact_fallbacks"] for x in report["rows"])
    for comparison in report["comparisons"]:
        baseline = comparison["comparison"].split(" - ")[1]
        deltas = [np.asarray(groups[(seed, comparison["law"], "learned_operator_bellman")])
                  - np.asarray(groups[(seed, comparison["law"], baseline)]) for seed in (3109, 3119, 3121)]
        close(np.mean(deltas), comparison["mean_paired_utility_difference"])
    return {"episodes": episodes, "paired_scenarios": len(scenarios), "retained_parts": len(report["files"]),
            "native_calls": native_calls, "native_candidate_paths": native_paths,
            "replayed_transitions": replayed_transitions, "maximum_actual_q32_error": max_q32_error,
            "exact_out_of_domain_fallbacks": out_of_domain,
            "scalar_choices_different_from_native_pareto_advisory": pareto_difference,
            "replay_scope": "all recorded actions replayed with unchanged simulator; independent law validation is separate",
            "authority": "DENY_ALL", "safety_certificate": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write a new receipt; an existing path is never overwritten")
    args = parser.parse_args()
    if args.output is not None and args.output.exists():
        raise FileExistsError("Preserve the existing completed audit")
    started = time.perf_counter()
    freeze = check_freeze()
    value = audit_value()
    network = audit_network()
    control = audit_control()
    assert check_freeze() == freeze
    report = {"schema": "hepta.regenerative.post-confirmation-audit.v1",
              "recorded_utc": datetime.now(timezone.utc).isoformat(),
              "auditor_sha256": digest(Path(__file__).read_bytes()),
              "auditor_written_after_confirmation": True, "source_freeze": freeze,
              "value": value, "network": network, "control": control,
              "status": "passed", "wall_seconds": time.perf_counter() - started,
              "limits": ["A reproducibility audit does not change scientific acceptance gates.",
                         "Zero of six cross-task advantage gates passed.",
                         "Finite-domain average value accuracy is not a uniform approximation certificate.",
                         "Native receipts remain advisory and do not establish production safety."]}
    if args.output is not None:
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": report["status"], "freeze": freeze, "control": control,
                      "value_passed": value["passed_mean_error_gates"],
                      "network_passed": network["passed_advantage_gates"]}, indent=2))


if __name__ == "__main__":
    main()
