"""Fresh deliveries followed by original-neuron feedback interventions."""
import argparse
import json
from pathlib import Path
import resource
import shutil
import time

import numpy as np

from ...risk_feedback.media import emit, file_sha, readback
from ...risk_feedback.model import PublicTask, choose_initial, digest
from ...risk_feedback.run import private_score
from .model import Native, decide, features, fit_head, summarize


def save(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def train(native, protocol, task, output):
    rng = np.random.default_rng(protocol["training_seed"])
    receipts, labels, rows = [], [], []
    for case in range(protocol["training_rows"]):
        directory = output / "training" / f"case-{case:04d}"
        action = int(rng.integers(4))
        fault = int(rng.choice(3, p=task["fault_probabilities"]))
        first = readback(emit(directory / "first", action, fault))
        save(directory / "FIRST_DELIVERY.json", first)
        scalar = task["numeric_feedback_by_fault"][first["fault_class"]]
        receipt = native.tick_pair(f"training-{case}", scalar, digest(first))
        save(directory / "NATIVE_STATE.json", receipt)
        repaired = readback(emit(directory / "repair", action))
        gain = (task["terminal_mismatch_penalty"][first["fault_class"]]
                - task["terminal_mismatch_penalty"][repaired["fault_class"]] - task["repair_cost"])
        rows.append({"case": case, "first": first, "repair": repaired, "scalar": scalar,
            "actual_paired_repair_gain": gain, "label": int(gain > 0),
            "native_receipt_sha256": file_sha(directory / "NATIVE_STATE.json"),
            "private_target_supplied": False})
        receipts.append(receipt)
        labels.append(int(gain > 0))
    weights, report = fit_head(receipts, labels, protocol)
    save(output / "TRAINING_ROWS.json", rows)
    save(output / "HEAD_PARAMETERS.json", weights.tolist())
    report.update(rows=len(rows), actual_bundles=2 * len(rows), native_ticks=2 * len(rows),
                  training_rows_sha256=file_sha(output / "TRAINING_ROWS.json"))
    return np.asarray(json.loads((output / "HEAD_PARAMETERS.json").read_text())), report


def first_delivery(case, arm, public, fault, posterior, task, output):
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    action, law, values = choose_initial(public, posterior, "risk", task)
    directory = output / "evaluation" / f"case-{case:04d}" / arm
    observation = readback(emit(directory / "first", action, fault))
    reopened = time.perf_counter_ns()
    scalar = task["numeric_feedback_by_fault"][observation["fault_class"]]
    record = {"case": case, "arm": arm, "public_cue": public.cue,
        "initial_action": action, "posterior": law, "initial_values": values,
        "first_observation": observation, "observed_feedback": scalar,
        "began_ns": began, "first_readback_ns": reopened,
        "hidden_target_supplied": False, "first_delivery_immutable": True}
    save(directory / "FIRST_DELIVERY.json", record)
    record["first_commit_ns"] = time.perf_counter_ns()
    record["first_wall_ns"] = record["first_commit_ns"] - began
    record["first_cpu_ns"] = time.process_time_ns() - cpu
    return record


def continue_delivery(record, shuffled, native, weights, task, output):
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    case, arm = record["case"], record["arm"]
    directory = output / "evaluation" / f"case-{case:04d}" / arm
    scalar = 0.0 if arm == "zero" else shuffled if arm == "shuffled" else record["observed_feedback"]
    receipt = native.tick_pair(f"evaluation-{case}", scalar, digest(record["first_observation"]),
                               reset=arm == "state_reset")
    save(directory / "NATIVE_STATE.json", receipt)
    native_committed = time.perf_counter_ns()
    action, logit = decide(receipt, weights)
    if arm == "history":
        penalty = task["terminal_mismatch_penalty"][record["first_observation"]["fault_class"]]
        action = "repair" if penalty > task["repair_cost"] else "stop"
    save(directory / "DECISION.json", {"continuation": action, "native_feature_logit": logit,
        "native_features_sha256": digest(features(receipt).tolist()),
        "native_receipt_sha256": file_sha(directory / "NATIVE_STATE.json"),
        "head_parameters_sha256": digest(weights.tolist()), "private_target_supplied": False,
        "history_bypass_declared": arm == "history"})
    decision_committed = time.perf_counter_ns()
    final = (readback(emit(directory / "repair", record["initial_action"]))
             if action == "repair" else record["first_observation"])
    completed = time.perf_counter_ns()
    row = {**record, "continuation": action, "native": receipt, "native_feature_logit": logit,
        "effective_scalar": scalar, "final_observation": final,
        "native_started_ns": began, "native_committed_ns": native_committed,
        "decision_committed_ns": decision_committed, "completed_ns": completed,
        "wall_ns": record["first_wall_ns"] + completed - began,
        "pipeline_elapsed_including_barrier_ns": completed - record["began_ns"],
        "cpu_ns": record["first_cpu_ns"] + time.process_time_ns() - cpu,
        "native_ns": sum(tick["native_ns"] for tick in receipt["ticks"]),
        "actual_output_bundles": 1 + int(action == "repair"), "target_supplied_to_online": False}
    save(directory / "EPISODE.json", row)
    return row


def run(output, build_receipt):
    source = Path(__file__).parent
    repair = source.parents[1]
    repository = source.parents[4]
    task_root = repair / "risk_feedback"
    protocol = json.loads((source / "PROTOCOL.json").read_text())
    task = json.loads((task_root / "PROTOCOL.json").read_text())
    posterior = np.asarray(json.loads((task_root / "evidence/PARAMETERS.json").read_text())["posterior"])
    build = json.loads(build_receipt.read_text())
    binary = Path(build["binary"])
    if file_sha(binary) != build["binary_sha256"] or file_sha(source / "native.rs") != build["native_probe_sha256"]:
        raise ValueError("Build is not the registered exact native probe")
    for path, expected in build["source_sha256"].items():
        if file_sha(repository / "codex-rs" / path) != expected:
            raise ValueError("Original native source changed after isolated build")
    output.mkdir(parents=True, exist_ok=False)
    paths = list(source.glob("*.py")) + [source / "native.rs", source / "PROTOCOL.json"]
    paths += [task_root / path for path in ("model.py", "media.py", "run.py", "PROTOCOL.json", "evidence/PARAMETERS.json")]
    paths += [repair.parent / "advance_20261026/control/bellman.py"]
    pins = {str(path.relative_to(repository)): file_sha(path) for path in paths}
    save(output / "FROZEN_REGISTRATION.json", {"registered_utc_ns": time.time_ns(),
        "protocol": protocol, "inherited_task": task, "source_sha256": pins,
        "native_build_receipt_sha256": file_sha(build_receipt), "evaluation_not_started": True,
        "run_count": 1, "native_owner_integration": False})
    shutil.copyfile(build_receipt, output / "BUILD_RECEIPT.json")
    shutil.copyfile(build_receipt.parent / "Cargo.lock", output / "Cargo.lock")
    shutil.copy2(binary, output / "feedback_probe")
    snapshot = {**pins, **{"codex-rs/" + path: expected for path, expected in build["source_sha256"].items()}}
    for path, expected in snapshot.items():
        target = output / "executed-sources" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repository / path, target)
        if file_sha(target) != expected:
            raise ValueError("Executed source snapshot changed while copying")
    native = Native(binary)
    began = time.perf_counter_ns()
    try:
        weights, training = train(native, protocol, task, output)
        if digest(weights.tolist()) != training["final_parameter_sha256"]:
            raise ValueError("Head reload mismatch")
        rng = np.random.default_rng(protocol["evaluation_seed"])
        cues = rng.choice(4, protocol["evaluation_rows"], p=task["cue_probabilities"])
        targets = [int(rng.choice(3, p=task["target_law_by_cue"][cue])) for cue in cues]
        faults = rng.choice(3, len(cues), p=task["fault_probabilities"])
        first = [first_delivery(case, arm, PublicTask(int(cue)), int(faults[case]), posterior, task, output)
                 for case, cue in enumerate(cues) for arm in protocol["arms"]]
        actual_scalars = np.array([row["observed_feedback"] for row in first if row["arm"] == "numeric"])
        permutation = np.random.default_rng(protocol["shuffle_seed"]).permutation(len(cues))
        shuffled = actual_scalars[permutation]
        save(output / "SHUFFLE_COMMITTED.json", {"actual_readback_scalars": actual_scalars.tolist(),
            "permutation": permutation.tolist(), "shuffled_scalars": shuffled.tolist(),
            "all_first_deliveries_already_committed": True})
        rows = []
        for record in first:
            row = continue_delivery(record, float(shuffled[record["case"]]), native, weights, task, output)
            directory = output / "evaluation" / f"case-{row['case']:04d}" / row["arm"]
            score = private_score(row, targets[row["case"]], task)
            score["episode_sha256"] = file_sha(directory / "EPISODE.json")
            save(directory / "PRIVATE_SCORE.json", score)
            rows.append({**row, **score})
            if len(rows) % 320 == 0:
                print(json.dumps({"completed_episodes": len(rows)}), flush=True)
    finally:
        native.close()
    save(output / "ROWS.json", rows)
    statistics, comparisons = summarize(rows, protocol, task["gamma"])
    chronology = all(row["first_readback_ns"] < row["first_commit_ns"] < row["native_started_ns"]
        < row["native_committed_ns"] < row["decision_committed_ns"] < row["completed_ns"]
        < row["private_score_started_ns"] for row in rows)
    same_information = all(len({digest(row["first_observation"]) for row in rows if row["case"] == case}) == 1
                           for case in range(len(cues)))
    unchanged = all(file_sha(repository / path) == expected for path, expected in pins.items())
    unchanged &= all(file_sha(repository / "codex-rs" / path) == expected for path, expected in build["source_sha256"].items())
    result = {"schema": "hepta.repair.original-neuron-feedback.result.v1", "status": "completed",
        "registration_sha256": file_sha(output / "FROZEN_REGISTRATION.json"),
        "rows_sha256": file_sha(output / "ROWS.json"), "training": training,
        "actual_evaluation_episodes": len(rows), "actual_native_sparse_ticks": 2 * len(rows) + training["native_ticks"],
        "actual_media_files": 4 * (sum(row["actual_output_bundles"] for row in rows) + training["actual_bundles"]),
        "statistics": statistics, "comparisons": comparisons, "source_unchanged": unchanged,
        "post_delivery_feedback_before_decision_chronology": chronology,
        "same_public_information_across_arms": same_information,
        "shuffle_from_actual_committed_receipts_and_preserves_marginal": sorted(actual_scalars) == sorted(shuffled),
        "original_sparse_neuron_state_causally_mediates_actions": statistics["state_reset"]["action_disagreements_with_numeric"] > 0,
        "numeric_unique_advantage_over_same_information_history": comparisons["history"]["positive_lower_bound"],
        "original_neuron_parameters_trained": False, "readout_parameters_trained": True,
        "native_owner_integration": False, "authority": "DENY_ALL", "requires_calibration": True,
        "learned_natural_multimodal_generation": False, "full_NDU_training": False,
        "host_private_state_isolation_proven": False, "old_native_closure_recovered": False,
        "scope": "Constructed two-tick feedback pathway in a new synthetic codec task; conditional on one trained head",
        "wall_ns": time.perf_counter_ns() - began,
        "python_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024}
    save(output / "RESULT.json", result)
    if not chronology or not same_information or not unchanged:
        raise ValueError("Integrity failure: retained results cannot be promoted")
    print(json.dumps({"status": result["status"], "episodes": len(rows), "comparisons": comparisons}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--build-receipt", type=Path, required=True)
    arguments = parser.parse_args()
    output_existed_before_invocation = arguments.output.exists()
    try:
        run(arguments.output, arguments.build_receipt)
    except Exception as error:
        if not output_existed_before_invocation and arguments.output.exists() and not (arguments.output / "FAILED.json").exists():
            save(arguments.output / "FAILED.json", {"error": f"{type(error).__name__}: {error}", "raw_evidence_retained": True})
        raise
