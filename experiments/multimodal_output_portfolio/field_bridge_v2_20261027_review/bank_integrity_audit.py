"""Read-only whole-bank identities, chronology, arrays and workload accounting.

This independent checker does not import the bank runner, predictor or analyzer.
It uses protocol JSON and completed persisted evidence. It does not score a task
or fit a model. Hash/timestamp consistency is not external temporal attestation.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


SEEDS = (17, 29, 43)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def object_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def local_hash(parameters):
    result = hashlib.sha256()
    for name, tensor in parameters.items():
        result.update(name.encode())
        result.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    return result.hexdigest()


def optimizer_hash(state):
    import torch
    result = hashlib.sha256(json.dumps(state["param_groups"], sort_keys=True).encode())
    for index, fields in sorted(state["state"].items()):
        result.update(str(index).encode())
        for name, value in sorted(fields.items()):
            result.update(name.encode())
            result.update(value.detach().cpu().contiguous().numpy().tobytes() if torch.is_tensor(value)
                          else repr(value).encode())
    return result.hexdigest()


def expected_resources(count, action, pilot, protocol):
    response = pilot["response_panel"]
    clean = pilot["clean_probe"]
    value_examples = response["pairs"] * len(response["conditions"])
    clean_examples = clean["pairs"] * len(clean["conditions"])
    gradients = count * len(protocol["multipliers"]) * protocol["macro_steps"]
    return {
        "candidate_gradient_forward_calls": gradients,
        "candidate_gradient_examples": gradients * pilot["batch_size"],
        "candidate_backward_calls": gradients,
        "frozen_teacher_forward_calls": gradients,
        "frozen_teacher_examples": gradients * pilot["batch_size"],
        "teacher_forced_field_probe_calls": count * (len(response["conditions"]) + len(clean["conditions"])),
        "teacher_forced_field_probe_examples": count * (value_examples + clean_examples),
        "current_and_branch_hard_value_forward_calls": count * 5 * len(response["conditions"]),
        "current_and_branch_hard_value_examples": count * 5 * value_examples,
        "rich_margin_forward_calls": count * len(response["conditions"]),
        "rich_margin_examples": count * value_examples,
        "hard_value_and_margin_observer_digit_calls": count * 12 * len(response["conditions"]),
        "hard_value_and_margin_observer_digit_examples": count * 12 * value_examples,
        "fixed_refinements_per_forward_example": 1 + (action != 0),
        "zero_branches_compute_gradients_but_hold_weights_and_momentum": True,
        "audit_observer_calls": 0, "test_retention_forward_calls": 0,
    }


def verify_phase(directory, phase, seed, study, pilot_root, predictor_freeze=None):
    import torch
    pilot = json.loads((study / "PILOT_PROTOCOL.json").read_text())
    protocol = json.loads((study / "BANK_PROTOCOL.json").read_text())
    bank_path = directory / "BANK.json"
    bank = json.loads(bank_path.read_text())
    complete = json.loads((directory / "COMPLETE.json").read_text())
    source = json.loads((directory / "SOURCE_FREEZE.json").read_text())
    if (complete["bank_sha256"] != digest(bank_path)
            or complete["source_files"] != source["files"] or bank["source_files"] != source["files"]
            or bank["registered_commit"] != source["registered_commit"]):
        raise ValueError("Completed bank/source identity mismatch")
    for name, expected in source["files"].items():
        if digest(study.parent / name) != expected:
            raise ValueError(f"Frozen executed source changed: {name}")
    recipe = next(item for item in pilot["candidates"] if item["name"] == protocol["selected_recipe"])
    steps = list(range(0, recipe["steps"], protocol["macro_steps"]))
    trajectories = protocol[phase + "_trajectory_ids"]
    expected_grid = {(seed, t, step) for t in trajectories for step in steps}
    records = bank["records"]
    if (len(records) != len(expected_grid) or complete["rows"] != len(records)
            or {(r["seed"], r["trajectory"], r["step"]) for r in records} != expected_grid
            or any(r["partition"] != phase for r in records)
            or bank["phase"] != phase or bank["seed"] != seed or bank["recipe"] != recipe):
        raise ValueError("Completed bank grid or declared phase differs from protocol")
    predictions_path = directory / "PREDICTIONS_BEFORE_OUTCOMES.jsonl"
    predictions = [json.loads(line) for line in predictions_path.read_text().splitlines()]
    if len(predictions) != len(records):
        raise ValueError("Pre-outcome prediction stream has missing/extra rows")
    by_key = {}
    previous_completed = -1
    extra = {"prediction_commit_sha256", "action_values", "branches", "trajectory_action",
             "outcomes_completed_monotonic_ns"}
    source_files = {name: digest(directory / name) for name in
                    ("BANK.json", "COMPLETE.json", "SOURCE_FREEZE.json", predictions_path.name)}
    for row, prediction in zip(records, predictions, strict=True):
        public = {key: value for key, value in prediction.items() if key != "committed_monotonic_ns"}
        if public != {key: value for key, value in row.items() if key not in extra}:
            raise ValueError("Prediction stream differs from the recorded pre-outcome row")
        if object_hash(prediction) != row["prediction_commit_sha256"]:
            raise ValueError("Prediction commitment digest mismatch")
        if not previous_completed < prediction["committed_monotonic_ns"]:
            raise ValueError("Prediction stream is not monotone across completed snapshots")
        last = prediction["committed_monotonic_ns"]
        branches = row["branches"]
        if [branch["action"] for branch in branches] != [0, 1, 2, 3]:
            raise ValueError("Complete action branches missing or reordered")
        for branch in branches:
            if not last < branch["measured_monotonic_ns"]:
                raise ValueError("A branch outcome predates its prediction or preceding branch")
            last = branch["measured_monotonic_ns"]
        if not last < row["outcomes_completed_monotonic_ns"]:
            raise ValueError("Outcome-completion timestamp precedes a branch")
        previous_completed = row["outcomes_completed_monotonic_ns"]
        zero = branches[0]
        if (zero["model_sha256"] != row["state_sha256"]
                or zero["optimizer_sha256"] != row["optimizer_sha256"]
                or zero["output_sha256"] != row["before_output_sha256"]
                or zero["semantic_change_fraction"] != 0
                or row["action_values"][0] != row["current_value"]
                or row["state"][0] != row["current_value"]):
            raise ValueError("No-update branch does not preserve full recorded state/value")
        if not np.isfinite(np.asarray(row["state"], float)).all():
            raise ValueError("Nonfinite recorded field")
        trajectory, step = row["trajectory"], row["step"]
        schedule_id = 0 if trajectory < 4 else trajectory
        schedule = [{"batch_seed": seed * 100003 + 600000 + schedule_id * 1009 + s,
                     "noise_seed": 107 + s, "condition": pilot["conditions"][s % 4]}
                    for s in range(step, step + protocol["macro_steps"])]
        if object_hash(schedule) != row["schedule_sha256"]:
            raise ValueError("Recorded branch schedule differs from protocol")
        if phase == "audit":
            if predictor_freeze is None:
                raise ValueError("Audit bank requires its pre-audit predictor freeze")
            expected_hash = predictor_freeze["controller_sha256"][str(seed)]
            if row["prediction_controller_sha256"] != expected_hash:
                raise ValueError("Audit predictor identities differ from pre-audit freeze")
            for values in row["predictions"].values():
                if len(values) != 4 or not np.isfinite(values).all() or values[0] != row["current_value"]:
                    raise ValueError("Invalid prediction or no-change identity")
        by_key[(trajectory, step)] = row
    max_mean_error, individual_values, terminal_checks = 0., 0, []
    initial_states = set()
    for trajectory in trajectories:
        path = directory / f"trajectory-{trajectory}-values.npz"
        source_files[path.name] = digest(path)
        with np.load(path, allow_pickle=False) as archive:
            if archive.files != ["values"]:
                raise ValueError("Unexpected per-example archive inventory")
            values = archive["values"]
        examples = pilot["response_panel"]["pairs"] * len(pilot["response_panel"]["conditions"])
        if (values.shape != (len(steps), 4, examples) or not np.isfinite(values).all()
                or values.min() < -1.004 or values.max() > .998):
            raise ValueError("Hard-value array shape/range differs from the declared panel")
        individual_values += values.size
        rng = np.random.default_rng(271028 + seed * 1009 + trajectory * 7919)
        previous = None
        previous_vector = None
        for index, step in enumerate(steps):
            row = by_key[(trajectory, step)]
            action = trajectory if trajectory < 4 else int(rng.integers(4))
            if row["trajectory_action"] != action:
                raise ValueError("Chosen exploration path differs from fixed/random schedule")
            error = float(np.max(np.abs(values[index].mean(axis=1) - row["action_values"])))
            max_mean_error = max(max_mean_error, error)
            if error > 1e-12:
                raise ValueError("Per-example values do not reconstruct recorded means")
            if previous is None:
                initial_states.add((row["state_sha256"], row["optimizer_sha256"], row["before_output_sha256"]))
            else:
                if (row["state_sha256"] != previous["model_sha256"]
                        or row["optimizer_sha256"] != previous["optimizer_sha256"]
                        or row["before_output_sha256"] != previous["output_sha256"]
                        or not np.array_equal(values[index, 0], previous_vector)):
                    raise ValueError("Recorded chosen path does not continue its prior branch")
            previous = row["branches"][action]
            previous_vector = values[index, action]
        terminal_path = directory / f"trajectory-{trajectory}-terminal.pt"
        source_files[terminal_path.name] = digest(terminal_path)
        terminal = torch.load(terminal_path, map_location="cpu", weights_only=True)
        parameter_identity = local_hash(terminal["parameters"])
        optimizer_identity = optimizer_hash(terminal["optimizer"])
        if (parameter_identity != previous["model_sha256"] or parameter_identity != terminal["local_sha256"]
                or optimizer_identity != previous["optimizer_sha256"] or optimizer_identity != terminal["optimizer_sha256"]
                or terminal["recipe"] != recipe or terminal["metadata"]["trajectory"] != trajectory
                or terminal["metadata"]["seed"] != seed or terminal["metadata"]["phase"] != phase):
            raise ValueError("Terminal stored parameters/optimizer differ from chosen final branch")
        terminal_checks.append({"trajectory": trajectory, "local_sha256": parameter_identity,
                                "optimizer_sha256": optimizer_identity})
    if len(initial_states) != 1:
        raise ValueError("Exploration trajectories started from different initial states")
    pilot_result = json.loads((pilot_root / "PILOT_RESULT.json").read_text())
    if (digest(pilot_root / "PILOT_RESULT.json") != protocol["actuator_pilot_result_sha256"]
            or bank["fixed_action"] != pilot_result["results"][str(seed)]["action"]):
        raise ValueError("Pilot or fixed deployment action changed")
    if phase == "fit":
        selected = pilot_result["selected"]["index"]
        prior_identity = pilot_result["results"][str(seed)]["candidates"][selected]["history"][-1]["local_sha256"]
        actual_identity = next(item["local_sha256"] for item in terminal_checks if item["trajectory"] == 2)
        if prior_identity != actual_identity:
            raise ValueError("Constant ordinary trajectory does not reproduce selected pilot parameters")
    resources = expected_resources(len(records), bank["fixed_action"], pilot, protocol)
    if any(bank["resources"][name] != value for name, value in resources.items()):
        raise ValueError("Recorded workload counts differ from the complete branch grid")
    if (bank["gradient_steps"] != resources["candidate_backward_calls"]
            or bank["gradient_examples"] != resources["candidate_gradient_examples"]
            or bank["audit_observer_loaded"] or bank["test_retention_scored"]
            or not bank["same_fixed_training_value_panel"]):
        raise ValueError("Bank execution scope or gradient count differs")
    return {"phase": phase, "seed": seed, "records": len(records), "trajectories": len(trajectories),
            "individual_hard_values_checked": int(individual_values), "max_mean_error": max_mean_error,
            "initial_state": list(next(iter(initial_states))), "terminal_checks": terminal_checks,
            "input_files_sha256": source_files, "source_file_count": len(source["files"]),
            "resources": resources, "registered_commit": bank["registered_commit"],
            "chronology_consistent": True, "chosen_paths_and_zero_action_consistent": True,
            "pilot_constant_action_parameters_reproduced": phase == "fit"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank", type=Path, required=True)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--pilot", type=Path, required=True)
    parser.add_argument("--phase", choices=("fit", "audit", "all"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    phases = ("fit", "audit") if args.phase == "all" else (args.phase,)
    freeze_path = args.bank / "PREDICTOR_FREEZE.json"
    freeze = json.loads(freeze_path.read_text()) if "audit" in phases else None
    result = {"schema": "hepta.field-bridge.v2.whole-bank-integrity.v1",
              "script_sha256": digest(Path(__file__)), "phases": phases,
              "banks": [verify_phase(args.bank / f"{phase}-{seed}", phase, seed, args.study,
                                      args.pilot, freeze) for phase in phases for seed in SEEDS],
              "scope": "Whole-record arithmetic, source identity, chronology consistency, saved optimizer/parameter hashes and schedule/workload checks. Not output regeneration, external attestation or new-label evaluation."}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as output:
        json.dump(result, output, indent=2, sort_keys=True, allow_nan=False)
        output.write("\n")
    print(json.dumps({"banks": len(result["banks"]), "complete_records": sum(x["records"] for x in result["banks"]),
                      "per_example_values": sum(x["individual_hard_values_checked"] for x in result["banks"]),
                      "max_mean_error": max(x["max_mean_error"] for x in result["banks"])}))


if __name__ == "__main__":
    main()
