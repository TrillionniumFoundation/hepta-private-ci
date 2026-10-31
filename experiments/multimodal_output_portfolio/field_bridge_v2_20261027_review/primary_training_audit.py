"""Independent arithmetic and identity audit of the frozen primary training run.

No model inference, fitting, or reserved data access occurs in this module.
Predictor mathematics and serialized optimizer hashes are reconstructed here.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch


REGISTERED_COMMIT = "c5233ce581e8fc6b45ab52b6d4653e01be8aa93f"
PRIMARY_NAMES = ("PRIMARY_PROTOCOL.json", "primary_common.py", "primary_training.py",
                 "primary_runtime.py", "primary_media.py", "primary_evaluate.py",
                 "primary_analyze.py", "native_fast.py", "native_ffi.rs")


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def content_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def close(actual, expected, message, tolerance=1e-12):
    actual, expected = np.asarray(actual, dtype=float), np.asarray(expected, dtype=float)
    require(actual.shape == expected.shape and np.isfinite(actual).all()
            and np.isfinite(expected).all() and np.max(np.abs(actual - expected), initial=0.) <= tolerance, message)


def local_identity(parameters):
    digest = hashlib.sha256()
    for name, value in parameters.items():
        require(torch.is_tensor(value) and torch.isfinite(value).all().item(), "Invalid adapter tensor")
        digest.update(name.encode())
        digest.update(value.contiguous().numpy().tobytes())
    return digest.hexdigest()


def optimizer_identity(state):
    digest = hashlib.sha256(json.dumps(state["param_groups"], sort_keys=True).encode())
    for index, fields in sorted(state["state"].items()):
        digest.update(str(index).encode())
        for name, value in sorted(fields.items()):
            digest.update(name.encode())
            if torch.is_tensor(value):
                require(torch.isfinite(value).all().item(), "Nonfinite saved optimizer tensor")
                digest.update(value.detach().contiguous().numpy().tobytes())
            else:
                digest.update(repr(value).encode())
    return digest.hexdigest()


def checkpoint(path, recipe):
    record = torch.load(path, map_location="cpu", weights_only=True)
    require(record["schema"] == "hepta.field-bridge.v2.adapter" and record["recipe"] == recipe,
            "Checkpoint treatment differs")
    require(local_identity(record["parameters"]) == record["local_sha256"], "Checkpoint adapter hash differs")
    require(optimizer_identity(record["optimizer"]) == record["optimizer_sha256"], "Complete SGD hash differs")
    groups = record["optimizer"]["param_groups"]
    require(len(groups) == 1 and groups[0]["momentum"] == .9 and groups[0]["weight_decay"] == 0
            and groups[0]["dampening"] == 0 and not groups[0]["nesterov"] and not groups[0]["maximize"],
            "Saved optimizer is not registered plain momentum SGD")
    parameters = list(record["parameters"].values())
    require(groups[0]["params"] == list(range(len(parameters))) and len(parameters) == 16
            and sum(p.numel() for p in parameters) == 18144, "Local optimizer tensor inventory differs")
    for index, fields in record["optimizer"]["state"].items():
        require(set(fields) == {"momentum_buffer"}
                and fields["momentum_buffer"].shape == parameters[index].shape
                and fields["momentum_buffer"].dtype == parameters[index].dtype,
                "Incomplete or malformed SGD momentum state")
    return record


def prediction(controller, raw, current):
    """Independent direct-distance implementation; never calls owner predict()."""
    raw = np.asarray(raw, dtype=float)
    normalizer = controller["normalizer"]
    z = np.clip((raw - normalizer["mean"]) / normalizer["scale"], -10., 10.)
    x = np.clip(z @ np.asarray(controller["projection"]), -10., 10.)
    selected, fitted = controller["selected_candidate"], controller["fitted"]
    if selected["family"] == "ridge":
        basis = x if selected["basis"] == "linear" else np.r_[x, [x[i] * x[j]
                    for i in range(len(x)) for j in range(i, len(x))]]
        centered = basis - fitted["basis_mean"]
    else:
        require(selected["family"] == "rbf", "Unknown predictor family")
        centers = np.asarray(fitted["centers"])
        kernel = np.exp(-np.sum((centers - x) ** 2, axis=1)
                        / (2 * selected["width"] ** 2 * len(x)))
        centered = kernel - kernel.mean() - fitted["kernel_column_mean"] + fitted["kernel_grand_mean"]
    delta = np.clip(centered @ np.asarray(fitted["coefficient"]) + fitted["target_mean"], -2., 2.)
    return np.r_[current, np.clip(current + delta, -1.004, .998)]


def schedule_hash(p, seed, step):
    return content_hash([{"batch_seed": seed * 100003 + 600000 + s,
                          "noise_seed": 107 + s, "condition": p["training_conditions"][s % 4]}
                         for s in range(step, step + 8)])


def expected_resources(p, action, advanced, predictor=False):
    blocks, gradients = p["steps"] // p["macro_steps"], p["steps"]
    nr, nc = len(p["response_panel"]["conditions"]), len(p["clean_probe"]["conditions"])
    n, c = nr * p["response_panel"]["pairs"], nc * p["clean_probe"]["pairs"]
    result = {"gradient_forward_calls": gradients, "backward_calls": gradients,
        "gradient_examples": gradients * p["batch_size"], "optimizer_steps": advanced,
        "frozen_teacher_forward_calls": gradients, "frozen_teacher_examples": gradients * p["batch_size"],
        "teacher_forced_field_probe_calls": blocks * (nr + nc),
        "teacher_forced_field_probe_examples": blocks * (n + c),
        "current_hard_value_forward_calls": blocks * nr, "current_hard_value_examples": blocks * n,
        "rich_margin_forward_calls": blocks * nr, "rich_margin_examples": blocks * n,
        "hard_value_and_margin_observer_digit_calls": blocks * 4 * nr,
        "hard_value_and_margin_observer_digit_examples": blocks * 4 * n,
        "fixed_refinements_per_forward_example": 1 + (action != 0),
        "audit_observer_calls": 0, "test_retention_forward_calls": 0}
    if predictor:
        result["predictor_calls"] = blocks
    return result


def source_identity(source_root, parent):
    files = dict(read(parent / "PREDICTOR_FREEZE.json")["source_files"])
    for name in PRIMARY_NAMES:
        path = source_root / "field_bridge_v2_20261027" / name
        files[str(path.relative_to(source_root))] = file_hash(path)
    for name, identity in files.items():
        require(file_hash(source_root / name) == identity, "A frozen scientific source changed")
    return files


def audit_ordinary(root, directory, parent, pilot, p, seed, complete):
    selection, trace = read(directory / "FIT_SELECTION.json"), read(directory / "ordinary.json")
    with np.load(directory / "ordinary-selection-values.npz", allow_pickle=False) as archive:
        values = archive["values"]
    spec = p["ordinary_selection_panel"]
    require(values.shape == (5, spec["pairs"] * len(spec["conditions"]))
            and np.isfinite(values).all(), "Ordinary score grid differs")
    require(file_hash(directory / "ordinary-selection-values.npz") == selection["values_file_sha256"]
            and selection["panel"] == spec and selection["seed"] == seed
            and selection["fixed_action"] == complete["fixed_action"], "Ordinary selection identity differs")
    grouped = values.reshape(5, len(spec["conditions"]), spec["pairs"])
    baseline = read(pilot / str(seed) / "BASELINE.json")["actions"][complete["fixed_action"]]
    close(values[0], baseline["values"], "Ordinary baseline no longer reproduces original pilot values")
    close(values[1], values[0], "Zero ordinary endpoint changed original hard outputs")
    close(selection["baseline"]["value"], values[0].mean(), "Ordinary baseline mean differs")
    require(selection["baseline"]["output_sha256"] == content_hash(baseline["output_sha256"]), "Baseline output identity differs")
    bank_path = parent / f"fit-{seed}/BANK.json"
    bank = read(bank_path)
    require(selection["parent_bank_sha256"] == file_hash(bank_path), "Ordinary parent bank changed")
    candidates, parent_rows = selection["candidates"], []
    require([c["action_index"] for c in candidates] == [0, 1, 2, 3], "Ordinary candidate inventory differs")
    for index, candidate in enumerate(candidates):
        close(candidate["value"], values[index + 1].mean(), "Ordinary candidate mean differs")
        for j, condition in enumerate(spec["conditions"]):
            close(candidate["by_condition"][condition], grouped[index + 1, j].mean(), "Ordinary condition mean differs")
            close(selection["baseline"]["by_condition"][condition], grouped[0, j].mean(), "Baseline condition mean differs")
        clean_index = spec["conditions"].index("clean")
        change = grouped[index + 1, clean_index].mean() - grouped[0, clean_index].mean()
        close(candidate["clean_change"], change, "Ordinary clean change differs")
        close(candidate["gain_vs_original"], values[index + 1].mean() - values[0].mean(), "Ordinary gain differs")
        require(candidate["eligible"] == (change >= -.01) and candidate["multiplier"] == p["multipliers"][index],
                "Ordinary eligibility or multiplier differs")
        rows = [row for row in bank["records"] if row["trajectory"] == index]
        require([row["step"] for row in rows] == list(range(0, 288, 8))
                and content_hash(rows) == candidate["parent_path_sha256"], "Incomplete ordinary parent path")
        previous = None
        for row in rows:
            require(row["trajectory_action"] == index and row["seed"] == seed and row["partition"] == "fit"
                    and row["schedule_sha256"] == schedule_hash(p, seed, row["step"]), "Ordinary schedule/action differs")
            if previous is not None:
                require(row["state_sha256"] == previous["model_sha256"]
                        and row["optimizer_sha256"] == previous["optimizer_sha256"]
                        and row["before_output_sha256"] == previous["output_sha256"], "Ordinary parent state continuity differs")
            previous = row["branches"][index]
        terminal_path = parent / candidate["source_checkpoint"]
        terminal = checkpoint(terminal_path, p["recipe"])
        require(file_hash(terminal_path) == candidate["source_checkpoint_sha256"]
                and terminal["local_sha256"] == previous["model_sha256"] == candidate["local_sha256"]
                and terminal["optimizer_sha256"] == previous["optimizer_sha256"] == candidate["optimizer_sha256"],
                "Ordinary candidate terminal identity differs")
        require(terminal["metadata"] == {"seed": seed, "trajectory": index, "phase": "fit",
                "source_identity": complete["original_identity"], "fixed_action": complete["fixed_action"]},
                "Ordinary parent seed/source metadata differs")
        parent_rows.append(rows)
    eligible = [c for c in candidates if c["eligible"]]
    selected = max(eligible, key=lambda c: (c["value"], -c["action_index"]))
    require(selection["selected"] == selected and trace["records"] == parent_rows[selected["action_index"]],
            "Ordinary candidate was not the strongest eligible registered endpoint")
    require(trace["reuse"] is True and trace["new_gradient_or_probe_calls"] == 0
            and trace["logical_path_resources_already_in_shared_bank"] == expected_resources(
                p, complete["fixed_action"], 288 if selected["action_index"] else 0), "Reused ordinary path cost differs")
    chosen = checkpoint(root / complete["profiles"]["ordinary"]["checkpoint"], p["recipe"])
    require(chosen["local_sha256"] == selected["local_sha256"]
            and chosen["optimizer_sha256"] == selected["optimizer_sha256"], "Saved ordinary treatment differs from winner")
    expected_selection_cost = {"hard_value_forward_calls": 20, "hard_value_examples": 5120,
        "reward_observer_digit_calls": 40, "reward_observer_digit_examples": 10240,
        "audit_observer_calls": 0, "test_retention_forward_calls": 0}
    require(selection["new_resources"] == expected_selection_cost
            and complete["ordinary_selection_new_resources"] == expected_selection_cost, "Ordinary selection cost differs")
    return {"selected_action": selected["action_index"], "selected_multiplier": selected["multiplier"],
            "values": values[1:].mean(axis=1).tolist(), "eligible": [c["eligible"] for c in candidates],
            "clean_changes": [c["clean_change"] for c in candidates], "candidate_rows_verified": int(values.size)}


def audit_profile(root, directory, parent, p, seed, profile, complete, freeze):
    trace_path = directory / f"{profile}.json"
    trace = read(trace_path)
    stream_path = directory / f"{profile}-decisions-before-updates.jsonl"
    decisions = [json.loads(line) for line in stream_path.read_text().splitlines()]
    rows = trace["records"]
    controller_path = parent / f"controllers/{seed}-{profile}.json"
    controller = read(controller_path)
    controller_hash = content_hash(controller)
    require(controller_hash == freeze["controller_sha256"][str(seed)][profile]
            and file_hash(controller_path) == freeze["controller_files_sha256"][str(controller_path.relative_to(parent))],
            "Controller differs from pre-audit freeze")
    require(len(rows) == len(decisions) == 36 and [row["step"] for row in rows] == list(range(0, 288, 8)),
            "Final training is missing registered blocks")
    initial = next(row for row in read(parent / f"fit-{seed}/BANK.json")["records"]
                   if row["trajectory"] == row["step"] == 0)
    state_hash, optimizer_hash = initial["state_sha256"], initial["optimizer_sha256"]
    last_time, advanced, max_error = -1, 0, 0.
    for row, committed in zip(rows, decisions, strict=True):
        reconstructed = {key: value for key, value in row.items()
                         if key not in {"after", "completed_monotonic_ns", "decision_sha256"}}
        require(reconstructed == committed and content_hash(committed) == row["decision_sha256"], "Decision stream differs from trace")
        require(row["seed"] == seed and row["profile"] == profile and row["controller_sha256"] == controller_hash
                and row["local_sha256"] == state_hash and row["optimizer_sha256"] == optimizer_hash
                and row["schedule_sha256"] == schedule_hash(p, seed, row["step"]), "Training metadata/state/schedule differs")
        require(last_time < row["committed_monotonic_ns"] < row["completed_monotonic_ns"], "Decision was not before completed update")
        close(row["state"][0], row["current_value"], "Current hard value differs from field coordinate")
        close(row["state"][6], row["step"] / 288, "Field time coordinate differs")
        require(len(row["state"]) == 25, "Final training used a different representation population")
        predicted = prediction(controller, row["state"], row["current_value"])
        close(row["predicted_values"], predicted, "Frozen predictor value differs", tolerance=1e-10)
        max_error = max(max_error, float(np.max(np.abs(predicted - row["predicted_values"]))))
        require(row["choice"] == int(np.argmax(predicted)) == int(np.argmax(row["predicted_values"]))
                and row["multiplier"] == p["multipliers"][row["choice"]], "Greedy action or deterministic tie rule differs")
        if row["choice"] == 0:
            require(row["after"] == {"local_sha256": state_hash, "optimizer_sha256": optimizer_hash}, "Zero action changed complete state")
        else:
            advanced += 8
        state_hash, optimizer_hash = row["after"]["local_sha256"], row["after"]["optimizer_sha256"]
        last_time = row["completed_monotonic_ns"]
    require(trace["resources"] == expected_resources(p, complete["fixed_action"], advanced, predictor=True)
            and not trace["audit_observer_loaded"] and not trace["test_retention_scored"]
            and trace["schedule_id"] == 0 and trace["decisions_file_sha256"] == file_hash(stream_path),
            "Training resource scope or decision stream identity differs")
    receipt = complete["profiles"][profile]
    require(receipt["resources"] == trace["resources"] and receipt["wall_ns"] == trace["wall_ns"]
            and receipt["decisions_sha256"] == file_hash(stream_path)
            and receipt["local_sha256"] == state_hash and receipt["optimizer_sha256"] == optimizer_hash,
            "Completed profile does not bind its actual training trace")
    return {"blocks": len(rows), "choices": np.bincount([r["choice"] for r in rows], minlength=4).tolist(),
            "actual_gradient_calls": 288, "optimizer_steps": advanced,
            "maximum_independent_prediction_error": max_error}


def audit(args):
    root, parent, pilot, source_root = map(Path, (args.root, args.parent_bank, args.pilot, args.source_root))
    p = read(source_root / "field_bridge_v2_20261027/PRIMARY_PROTOCOL.json")
    sources, freeze = source_identity(source_root, parent), read(parent / "PREDICTOR_FREEZE.json")
    require(p["schedule_id"] == 0 and p["steps"] == 288 and p["macro_steps"] == 8, "Unexpected primary training registration")
    report, inputs = {}, {}
    for seed in p["seeds"]:
        directory = root / "training" / str(seed)
        complete, source = read(directory / "COMPLETE.json"), read(directory / "SOURCE_FREEZE.json")
        require(complete["source_files"] == source["source_files"] == sources
                and complete["registered_commit"] == source["registered_commit"] == REGISTERED_COMMIT
                and complete["seed"] == seed and complete["recipe"] == p["recipe"]
                and complete["all_profiles_complete"] and not complete["audit_observer_loaded"]
                and not complete["test_retention_scored"], "Training completion/provenance differs")
        require(complete["fixed_action"] == read(pilot / "PILOT_RESULT.json")["results"][str(seed)]["action"], "Fixed deployment action changed")
        require(set(complete["profiles"]) == {"ordinary", "field", "generic", "richer"}, "Training profile inventory differs")
        report[str(seed)] = {"ordinary": audit_ordinary(root, directory, parent, pilot, p, seed, complete)}
        for profile, receipt in complete["profiles"].items():
            path = root / receipt["checkpoint"]
            record = checkpoint(path, p["recipe"])
            require(file_hash(path) == receipt["checkpoint_sha256"] and record["local_sha256"] == receipt["local_sha256"]
                    and record["optimizer_sha256"] == receipt["optimizer_sha256"]
                    and file_hash(root / receipt["trace"]) == receipt["trace_sha256"], "Checkpoint/trace receipt differs")
            metadata = record["metadata"]
            expected = {"seed": seed, "profile": profile, "source_identity": complete["original_identity"],
                        "fixed_action": complete["fixed_action"], "schedule_id": 0, "steps": 288, "source_files": sources}
            require(all(metadata.get(k) == v for k, v in expected.items()), "Saved checkpoint metadata differs")
            if profile == "ordinary":
                selected = read(directory / "FIT_SELECTION.json")["selected"]
                require(metadata["reused_checkpoint_sha256"] == selected["source_checkpoint_sha256"]
                        and metadata["selection_sha256"] == file_hash(directory / "FIT_SELECTION.json")
                        and receipt["actual_new_gradient_calls"] == receipt["actual_new_boundary_probe_calls"] == 0,
                        "Ordinary checkpoint reuse metadata differs")
            else:
                require(metadata["controller_sha256"] == freeze["controller_sha256"][str(seed)][profile]
                        and metadata["trace_sha256"] == receipt["trace_sha256"], "Controller checkpoint metadata differs")
                report[str(seed)][profile] = audit_profile(root, directory, parent, p, seed, profile, complete, freeze)
        require(len({r["base_sha256"] for r in complete["profiles"].values()}) == 1, "Adapted profiles cite different frozen bases")
        for phase, key in (("fit", "shared_fit"), ("audit", "qualification_audit")):
            bank = read(parent / f"{phase}-{seed}/BANK.json")
            require(complete[key + "_resources_count_once"] == bank["resources"]
                    and complete[key + "_wall_ns"] == bank["wall_ns"], "Shared cost was omitted or reassigned")
        require(complete["ordinary_selection_sha256"] == file_hash(directory / "FIT_SELECTION.json")
                and complete["shared_predictor_fit_freeze_sha256"] == file_hash(parent / "PREDICTOR_FREEZE.json"),
                "Selection or shared fit identity differs")
        for path in sorted(directory.iterdir()):
            if path.is_file():
                inputs[str(path.relative_to(root))] = file_hash(path)
    if (root / "TRAINING_COMPLETE.json").exists():
        aggregate = read(root / "TRAINING_COMPLETE.json")
        require(aggregate["source_files"] == sources and set(aggregate["seeds"]) == set(report), "Training aggregate differs")
        for seed in report:
            require(aggregate["seeds"][seed] == read(root / f"training/{seed}/COMPLETE.json"), "Training aggregate changed seed evidence")
        inputs["TRAINING_COMPLETE.json"] = file_hash(root / "TRAINING_COMPLETE.json")
    result = {"schema": "hepta.field-bridge.v2.primary-training-audit.1", "status": "pass", "by_seed": report,
        "source_files": sources, "input_files_sha256": inputs, "script_sha256": file_hash(__file__),
        "independently_reconstructed_prediction_rows": 324, "ordinary_hard_value_rows_checked": 15360,
        "complete_checkpoints_verified": 12, "parent_constant_endpoints_verified": 12,
        "new_final_gradient_calls": 2592, "new_ordinary_selection_hard_forward_calls": 60,
        "shared_fit_and_audit_costs_preserved_once_per_seed": True,
        "model_inference_calls": 0, "test_retention_scored": False,
        "scope": "Independent serialized evidence arithmetic/provenance. Actual first-two-block replay is a separately bound receipt; this audit does not infer primary benefit or prove all physical executions from hashes alone."}
    path = Path(args.report)
    require(not path.exists(), "Refusing to overwrite an existing audit receipt")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--parent-bank", required=True)
    parser.add_argument("--pilot", required=True)
    parser.add_argument("--source-root", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--report", required=True)
    outcome = audit(parser.parse_args())
    print(json.dumps({key: value for key, value in outcome.items() if key not in {"source_files", "input_files_sha256"}}, sort_keys=True))
