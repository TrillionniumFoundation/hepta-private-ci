"""Post hoc diagnosis of released V3 fit/development evidence only.

This script never loads a generator, observer, native kernel, corpus pixels,
or any unopened audit/primary/retention task. Logged-state counterfactual
actions are not estimates of a new closed-loop policy's endpoint utility.
"""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import time

import numpy as np

from training_panel_origin import PANEL_INDICES, fit_origin, translate

SEEDS = (17, 29, 43)
MODES = ("field", "generic", "richer", "h7")
METHODS = ("ordinary_0", "ordinary_1", "ordinary_2", "ordinary_3", *MODES)
PROTOCOL_SHA = "a267e91deb23aff25bdb27cf23f8274b5bfa8217c51ee962f3360297f6daa7c7"


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def predict(head, raw):
    values = np.asarray(raw, dtype=np.float64)
    projected = ((values - head["raw_mean"]) / head["raw_scale"]) @ np.asarray(head["projection"])
    normalized = (projected - head["projected_mean"]) / head["projected_scale"]
    design = np.column_stack((np.ones(len(values)), normalized))
    return design @ np.asarray(head["coefficients"])


class Evidence:
    def __init__(self, root):
        self.root = root.resolve()
        self.identities = {}

    def data(self, relative, expected=None):
        parts = Path(relative).parts
        require(parts and ".." not in parts and not Path(relative).is_absolute(), "Unsafe input path")
        require(parts[0] in {"fit", "bank", "development"}
                or relative == "DEVELOPMENT_SELECTION.json", "Only released training evidence may be read")
        path = self.root / relative
        data = path.read_bytes()
        identity = sha(data)
        require(expected is None or identity == expected, "V3 evidence identity differs: " + relative)
        self.identities[relative] = {"sha256": identity, "bytes": len(data)}
        return data

    def json(self, relative, expected=None):
        return json.loads(self.data(relative, expected))

    def unchanged(self):
        return all(sha((self.root / name).read_bytes()) == identity["sha256"]
                   for name, identity in self.identities.items())


def count(actions):
    return np.bincount(np.asarray(actions, dtype=np.int64), minlength=4).tolist()


def fitting_summary(bank, fitted):
    rows = bank["records"]
    x = np.asarray([row["state"] for row in rows], dtype=np.float64)
    y = np.asarray([row["action_values"] for row in rows], dtype=np.float64)
    groups = np.asarray([row["trajectory"] for row in rows])
    require(x.shape == (24, 30) and y.shape == (24, 4), "Incomplete frozen fitting bank")
    origin = fit_origin(bank)
    require(np.array_equal(translate(x, origin, origin), x), "Fit-domain mapping is not exact identity")
    best = int(np.argmax(y.mean(0)))
    oracle = y.max(1)
    result = {
        "states": 24, "independent_exploration_trajectories": 4,
        "target": bank["target_scope"], "reference_action_index": bank["reference_action_index"],
        "best_bank_candidate_action_then_reference": best,
        "bank_candidate_mean_values": y.mean(0).tolist(),
        "statewise_oracle_advantage_over_best_bank_candidate": float((oracle - y[:, best]).mean()),
        "action_value_range_mean": float(np.ptp(y, axis=1).mean()),
        "nontrivial_action_range_rows_at_1e_minus_12": int((np.ptp(y, axis=1) > 1e-12).sum()),
        "fit_panel_origin_equal_across_all_four_paths": True,
        "fit_domain_translation_exact_identity": True,
        "panel_origin": {bank["feature_names"][i]: float(origin[i]) for i in PANEL_INDICES},
        "candidate_diagnostics": {},
        "interpretation": "The statewise oracle and bank-constant comparator both execute one candidate block followed by the frozen reference. They are not full closed-loop policies or independent endpoint estimates."
    }
    for mode in MODES:
        info = fitted["all_candidates"][mode]
        candidates = []
        for candidate in info["candidates"]:
            predictions = np.empty_like(y)
            covered = np.zeros(24, dtype=np.int64)
            for fold in candidate["folds"]:
                mask = groups == fold["held_out_trajectory"]
                predictions[mask] = np.asarray(fold["predictions"])
                covered[mask] += 1
            require(np.all(covered == 1), "OOF predictions do not cover every state exactly once")
            error = predictions - y
            mse = float(np.square(error).mean())
            require(abs(mse - candidate["cv_mse"]) <= 1e-15, "Stored CV arithmetic differs")
            actions = np.argmax(predictions, axis=1)
            selected = y[np.arange(24), actions]
            common_error = error.mean(1, keepdims=True)
            candidates.append({
                "ridge": candidate["ridge"], "absolute_terminal_cv_mse": mse,
                "common_level_mse": float(np.square(common_error).mean()),
                "action_contrast_mse": float(np.square(error - common_error).mean()),
                "mean_oof_candidate_regret": float((oracle - selected).mean()),
                "oof_candidate_advantage_over_best_bank_constant": float((selected - y[:, best]).mean()),
                "oof_action_counts": count(actions),
                "oof_action_is_oracle_up_to_1e_minus_12": int(((oracle - selected) <= 1e-12).sum())
            })
        result["candidate_diagnostics"][mode] = {
            "selected_index_by_original_mse": info["selected_index"],
            "minimum_regret_candidate_index_descriptive_only": int(np.argmin(
                [row["mean_oof_candidate_regret"] for row in candidates])),
            "candidates": candidates
        }
    return result, x, origin


def load_path(evidence, seed, method, schedule, complete):
    prefix = f"development/{seed}/{method}/schedule-{schedule}"
    rel = f"{method}/schedule-{schedule}/COMPLETE.json"
    path = evidence.json(prefix + "/COMPLETE.json", complete["files"][rel])
    trace_name = f"{method}/schedule-{schedule}/decisions-and-outcomes.jsonl.gz"
    raw = evidence.data(prefix + "/decisions-and-outcomes.jsonl.gz", complete["files"][trace_name])
    require(sha(raw) == path["trace_sha256"], "Path trace identity differs")
    records = [json.loads(line) for line in gzip.decompress(raw).splitlines()]
    require(len(records) == 12, "Six committed decisions/outcomes required")
    decisions, accepted = [], []
    for position in range(6):
        decision, outcome = records[2 * position:2 * position + 2]
        require(decision["kind"] == "decision_before_update" and outcome["kind"] == "block_outcome",
                "Decision/outcome alternation differs")
        require(decision["step"] == 48 * position and decision["method"] == method
                and decision["seed"] == seed and decision["schedule_id"] == schedule, "Path identity differs")
        require(decision["action_index"] == outcome["receipt"]["action_index"], "Action/outcome differs")
        decisions.append(decision)
        accepted.append(outcome["receipt"]["accepted"])
    require([row["action_index"] for row in decisions] ==
            [row["action_index"] for row in path["decisions"]], "Path summary actions differ")
    return decisions, accepted


def development_summary(evidence, seed, fitted, bank, x, origin, selection):
    complete = evidence.json(f"development/{seed}/COMPLETE.json")
    raw = evidence.data(f"development/{seed}/ENDPOINTS.npz", complete["endpoint_values_sha256"])
    with np.load(io.BytesIO(raw), allow_pickle=False) as loaded:
        arrays = {key: loaded[key].copy() for key in loaded.files}
    require(arrays["methods"].tolist() == list(METHODS), "Development method order differs")
    require(arrays["schedule_ids"].tolist() == [6000, 6001, 6002, 6003], "Development schedules differ")
    require(arrays["observer_names"].tolist() == ["reward", "audit"], "Observer order differs")
    task_gain = (arrays["task_values"] - arrays["original_task"][None, None]).mean(axis=(1, 3))
    clean_gain = (arrays["clean_values"] - arrays["original_clean"][None, None]).mean(axis=(1, 3))
    best = selection["ordinary_action_indices"][str(seed)]
    result = {
        "paired_endpoint_shapes": {name: list(arrays[name].shape) for name in ("task_values", "clean_values")},
        "ordinary_comparator_selected_in_original_development": best,
        "field_minus_selected_ordinary": (task_gain[4] - task_gain[best]).tolist(),
        "methods": {}
    }
    for number, method in enumerate(METHODS):
        paths, states, old_actions, mapped_actions, accepted_all = [], [], [], [], []
        errors = []
        contributions = []
        old_initial, mapped_initial = [], []
        for schedule in arrays["schedule_ids"].tolist():
            decisions, accepted = load_path(evidence, seed, method, schedule, complete)
            state = np.asarray([row["state"] for row in decisions], dtype=np.float64)
            observed = state[0].copy()
            mapped = translate(state, observed, origin)
            actions = [row["action_index"] for row in decisions]
            original_values = None
            newer_actions = None
            if method in MODES:
                head = fitted["controllers"][method]
                original_values = predict(head, state)
                stored = np.asarray([row["predictions"] for row in decisions])
                errors.append(float(np.max(np.abs(original_values - stored))))
                require(np.array_equal(np.argmax(original_values, axis=1), actions), "Frozen head actions differ")
                require(errors[-1] <= 1e-12, "Frozen head predictions differ")
                newer_actions = np.argmax(predict(head, mapped), axis=1).tolist()
                mapped_actions.extend(newer_actions)
                old_initial.append(actions[0])
                mapped_initial.append(newer_actions[0])
                if method == "field":
                    normalized = (((state - head["raw_mean"]) / head["raw_scale"]) @ head["projection"]
                                  - head["projected_mean"]) / head["projected_scale"]
                    design = np.column_stack((np.ones(6), normalized))
                    coefficients = np.asarray(head["coefficients"])
                    contribution = design * (coefficients[:, actions].T - coefficients[:, best])
                    contributions.extend(contribution[np.asarray(actions) != best].tolist())
            paths.append({"schedule": schedule, "actions": actions, "guard_accepted": accepted,
                          "translated_actions_on_same_logged_states": newer_actions})
            states.extend(state.tolist())
            old_actions.extend(actions)
            accepted_all.extend(accepted)
        values = np.asarray(states)
        fit_scale = np.maximum(x.std(0), 1e-6)
        z = (values - x.mean(0)) / fit_scale
        fields = []
        for i in range(12):
            fields.append({"name": bank["feature_names"][i], "fit_mean": float(x[:, i].mean()),
                "fit_standard_deviation_with_floor": float(fit_scale[i]),
                "development_min": float(values[:, i].min()), "development_max": float(values[:, i].max()),
                "max_abs_fit_scaled_coordinate": float(np.max(np.abs(z[:, i]))),
                "initial_mean_fit_scaled_coordinate": float(z.reshape(4, 6, 30)[:, 0, i].mean())})
        item = {"endpoint_task_gain_reward_audit": task_gain[number].tolist(),
            "endpoint_clean_gain_reward_audit": clean_gain[number].tolist(),
            "original_action_counts": count(old_actions), "guard_accepted_blocks": int(sum(accepted_all)),
            "guard_rejected_blocks": int(len(accepted_all) - sum(accepted_all)),
            "paths": paths, "h12_coordinate_shift": fields if method == "field" else None}
        if method in MODES:
            mapped_all = np.concatenate([translate(values[n:n + 6], values[n], origin)
                                         for n in range(0, 24, 6)])
            new_z = (mapped_all - x.mean(0)) / fit_scale
            item.update(frozen_head_max_abs_reconstruction_error=max(errors),
                translated_logged_state_action_counts=count(mapped_actions),
                changed_actions_on_logged_states=int((np.asarray(old_actions) != mapped_actions).sum()),
                original_initial_actions=old_initial, translated_initial_actions=mapped_initial,
                maximum_abs_h12_coordinate_before=float(np.max(np.abs(z[:, :12]))),
                maximum_abs_h12_coordinate_after=float(np.max(np.abs(new_z[:, :12]))),
                translated_policy_new_endpoint_utility=None,
                logged_state_action_replay_is_off_policy=True)
            if method == "field" and contributions:
                mean = np.mean(contributions, axis=0)
                item["original_predicted_advantage_over_selected_ordinary_when_actions_differ"] = {
                    "decisions": len(contributions), "mean": float(mean.sum()),
                    "mean_coordinate_contributions": dict(zip(["intercept", *bank["feature_names"][:12]],
                                                              mean.tolist(), strict=True))}
        result["methods"][method] = item
        for domain, calculated in (("task_gain", task_gain[number]), ("clean_gain", clean_gain[number])):
            expected = selection["per_seed"][str(seed)][method][domain]
            require(np.array_equal(calculated, expected), "Original selected development arithmetic differs")
    return result


def execute(root, protocol_path):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    protocol_raw = protocol_path.read_bytes()
    require(sha(protocol_raw) == PROTOCOL_SHA, "Unexpected frozen V3 protocol")
    protocol = json.loads(protocol_raw)
    require(protocol["training"]["multipliers"] == [0., .25, 1., 2.], "Action values differ")
    evidence = Evidence(root)
    selection = evidence.json("DEVELOPMENT_SELECTION.json")
    require(selection["passed"] is False, "This diagnosis must preserve the failed V3 gate")
    seeds = {}
    for seed in SEEDS:
        bank_complete = evidence.json(f"bank/{seed}/COMPLETE.json")
        bank = evidence.json(f"bank/{seed}/BANK.json", bank_complete["files"]["BANK.json"])
        fit_complete = evidence.json(f"fit/{seed}/COMPLETE.json")
        fitted = evidence.json(f"fit/{seed}/CONTROLLERS.json", fit_complete["files"]["CONTROLLERS.json"])
        require(fitted["bank_sha256"] == evidence.identities[f"bank/{seed}/BANK.json"]["sha256"],
                "Controller is not fitted to this bank")
        fitting, x, origin = fitting_summary(bank, fitted)
        development = development_summary(evidence, seed, fitted, bank, x, origin, selection)
        seeds[str(seed)] = {"fit": fitting, "development": development}
    require(evidence.unchanged(), "An original evidence input changed during diagnosis")
    return {"schema": "hepta.field-bridge.v4.training-origin-diagnosis.1", "status": "pass",
        "exploratory_post_v3_outcomes": True, "confirmatory_or_new_policy_outcome_evidence": False,
        "original_v3_development_gate_passed": False, "original_v3_primary_opened": False,
        "data_access": {"allowed": ["V3 fit bank", "frozen fitted controllers", "released V3 development"],
                        "unopened_audit_primary_retention_tasks_accessed": False, "corpus_pixels_loaded": False},
        "new_generator_observer_native_network_calls": 0, "new_optimizer_steps": 0,
        "original_inputs_unchanged_after_analysis": True,
        "policy_intervention_under_consideration": {
            "name": "panel-origin translation with frozen V3 heads",
            "indices": list(PANEL_INDICES),
            "rule": "mapped[I] = raw[I] - (observed_initial[I] - fit_initial[I]); all other coordinates unchanged",
            "fit_domain": "Exact identity; initial selected coordinates equal on all four fit trajectories",
            "weights_normalization_ridge_and_family_selection_changed": False,
            "initial_measurement": "Reuse the first authorized probe/guard state; freeze once per full path",
            "outcome_caveat": "Changed actions on fixed logged states imply no identified new trajectory or endpoint reward."
        },
        "seeds": seeds, "input_identities": evidence.identities, "protocol_sha256": PROTOCOL_SHA,
        "script_sha256": sha(Path(__file__).read_bytes()),
        "helper_sha256": sha(Path(__file__).with_name("training_panel_origin.py").read_bytes()),
        "analysis_wall_ns": time.perf_counter_ns() - started, "analysis_cpu_ns": time.process_time_ns() - cpu}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "Refusing to overwrite an existing diagnostic result")
    result = execute(args.run_root, args.protocol)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status": result["status"], "seeds": list(result["seeds"]),
                      "input_files": len(result["input_identities"]),
                      "original_v3_development_gate_passed": False, "new_model_calls": 0}))
