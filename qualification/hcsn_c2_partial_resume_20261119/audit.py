"""Read complete archived continuation evidence; execute no model or optimizer."""

import argparse
from collections import Counter
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import random
import resource
import tarfile
import time
from zipfile import ZipFile

for variable in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[variable] = "1"

import numpy as np
import torch

from audit_adam import verify_first_adam


HERE = Path(__file__).resolve().parent
METRIC_ARITHMETIC_ABSOLUTE_BOUND = 1e-12
OBJECTIVE_KEYS = {"loss", "events", "micro_forward_calls", "forward_seconds", "backward_seconds",
                  "last_microbatch_diagnostics", "target_weight_sum", "weighted_loss_numerator"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def exact(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, torch.Tensor):
        return (left.dtype == right.dtype and left.shape == right.shape
                and left.contiguous().numpy().tobytes() == right.contiguous().numpy().tobytes())
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(exact(value, right[key]) for key, value in left.items())
    if isinstance(left, (list, tuple)):
        return len(left) == len(right) and all(exact(a, b) for a, b in zip(left, right))
    return left == right


def read_json(data):
    return json.loads(data)


def load_state(data):
    return torch.load(io.BytesIO(data), weights_only=True, map_location="cpu")


def archive_members(path, receipt):
    payload = path.read_bytes()
    require(len(payload) == receipt["bytes"] and digest(payload) == receipt["sha256"], "exact complete archive identity")
    members, size = {}, 0
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r|xz") as source:
        for item in source:
            name = Path(item.name)
            require(item.isfile() and not name.is_absolute() and ".." not in name.parts
                    and item.name not in members and item.size < 32 * 1024**2, "safe unique bounded member")
            size += item.size
            require(size < 1024**3, "bounded complete archive payload")
            members[item.name] = source.extractfile(item).read()
    manifest = read_json(members["MANIFEST.json"])
    require(set(members) == set(manifest["members"]) | {"MANIFEST.json"}, "exhaustive archive membership")
    for name, expected in manifest["members"].items():
        require(len(members[name]) == expected["bytes"] and digest(members[name]) == expected["sha256"],
                "exact archived file " + name)
    require(len(members) == receipt["members"] and len(members["MANIFEST.json"]) == receipt["manifest_bytes"]
            and digest(members["MANIFEST.json"]) == receipt["manifest_sha256"], "archive manifest receipt")
    require(sorted(name[4:] for name in members if name.startswith("run/")) == manifest["all_run_output_files"],
            "all archived run output retained")
    by_path = {row["source_path"]: name for name, row in manifest["members"].items()}
    require(len(by_path) == len(manifest["members"]), "unique original source paths")
    return members, manifest, by_path


def plateau(history, policy):
    best, best_epoch, anchor, stale, first = -1.0, None, -1.0, 0, None
    for number, row in enumerate(history, 1):
        require(row["epoch"] == number and row["complete"] is True, "complete contiguous history")
        score = row["development"]["macro_f1_11_classes"]
        require(math.isfinite(score) and 0 <= score <= 1, "valid development score")
        if score > best:
            best, best_epoch = score, number
        if score > anchor + policy["plateau_delta"]:
            anchor, stale = score, 0
        else:
            stale += 1
        if first is None and number >= policy["minimum_cumulative_epochs"] and stale >= policy["patience"]:
            first = number
    return {"best": best, "best_epoch": best_epoch, "plateau_anchor": anchor, "stale_epochs": stale}, first


def confusion_metrics(matrix):
    matrix = np.asarray(matrix, dtype=np.int64)
    require(matrix.shape == (11, 11) and np.all(matrix >= 0) and int(matrix.sum()) == 31952,
            "complete original development confusion matrix")
    support, predicted, correct = matrix.sum(1), matrix.sum(0), matrix.diagonal()
    f1 = 2 * correct / np.maximum(support + predicted, 1)
    present = support > 0
    return {"events": int(matrix.sum()), "accuracy": float(correct.sum() / matrix.sum()),
            "macro_f1_11_classes": float(f1.mean()), "macro_f1_present_classes": float(f1[present].mean()),
            "balanced_accuracy_present_classes": float((correct[present] / support[present]).mean())}


def compare_metrics(observed, reported):
    differences = {}
    for key, value in observed.items():
        if key == "confusion_matrix":
            require(value == reported[key], "independently recomputed confusion matrix")
        else:
            differences[key] = abs(value - reported[key])
            require(math.isfinite(differences[key]) and differences[key] <= METRIC_ARITHMETIC_ABSOLUTE_BOUND,
                    "independently recomputed metric " + key)
    return differences


def logits_metrics(saved):
    logits, labels = saved["logits"].numpy(), saved["labels"].numpy()
    require(logits.shape == (31952, 11) and labels.shape == (31952,) and logits.dtype == np.float64
            and labels.dtype == np.int64 and np.isfinite(logits).all() and np.all((0 <= labels) & (labels < 11)),
            "complete finite saved FP64 development logits and labels")
    shifted = logits - logits.max(axis=1, keepdims=True)
    exponentials = np.exp(shifted)
    probabilities = exponentials / exponentials.sum(axis=1, keepdims=True)
    predictions = probabilities.argmax(axis=1)
    matrix = np.bincount(11 * labels + predictions, minlength=121).reshape(11, 11)
    result = confusion_metrics(matrix)
    result["confusion_matrix"] = matrix.tolist()
    result["nll"] = float(np.mean(np.log(exponentials.sum(axis=1)) - shifted[np.arange(len(labels)), labels]))
    onehot = np.eye(11)[labels]
    result["brier_half_sum"] = float(.5 * np.mean(np.sum((probabilities - onehot)**2, axis=1)))
    result["brier_mean_classes"] = result["brier_half_sum"] * (2 / 11)
    confidence = probabilities.max(axis=1)
    terms = []
    for index in range(15):
        chosen = (confidence >= index / 15) & ((confidence < (index + 1) / 15) if index < 14 else confidence <= 1)
        if np.any(chosen):
            terms.append(float(np.mean(chosen) * abs(np.mean(confidence[chosen]) - np.mean(predictions[chosen] == labels[chosen]))))
    result["ece_15_equal_width_bins"] = sum(terms)
    return result


def check_state(state, original, initial, trainable, updates, epochs, manifest_sha):
    require(state.keys() in (original.keys(), original.keys() - {"continuation_cursor"}), "checkpoint full schema")
    require(state["model_configuration"] == original["model_configuration"] == initial["model_configuration"]
            and state["main_updates"] == updates and state["epochs_completed"] == epochs
            and state["data_manifest_sha256"] == manifest_sha, "checkpoint configuration and logical counters")
    require(state["model"].keys() == original["model"].keys() == initial["model"].keys(), "complete model state names")
    changed = []
    for name, tensor in state["model"].items():
        require(tensor.dtype == original["model"][name].dtype and tensor.shape == original["model"][name].shape
                and bool(torch.isfinite(tensor).all()), "finite model tensor with original shape/dtype")
        if name not in trainable:
            require(exact(tensor, initial["model"][name]), "unchanged original frozen parameter/buffer " + name)
        elif not exact(tensor, original["model"][name]):
            changed.append(name)
    require(exact(state["optimizer"]["param_groups"], original["optimizer"]["param_groups"])
            and state["optimizer"]["state"].keys() == original["optimizer"]["state"].keys(), "retained complete AdamW groups")
    require(len(state["optimizer"]["state"]) == len(trainable), "one AdamW state per trainable tensor")
    for key, value in state["optimizer"]["state"].items():
        require(value.keys() == original["optimizer"]["state"][key].keys() and float(value["step"]) == updates,
                "actual saved AdamW update age")
        for field, tensor in value.items():
            old = original["optimizer"]["state"][key][field]
            require(isinstance(tensor, torch.Tensor) and tensor.shape == old.shape and tensor.dtype == old.dtype
                    and bool(torch.isfinite(tensor).all()), "complete finite saved AdamW tensors")
    rng = state["torch_rng"]
    require(rng.dtype == original["torch_rng"].dtype and rng.shape == original["torch_rng"].shape, "saved Torch RNG representation")
    random.Random().setstate(state["order_rng"])
    return changed


def fit_review(fit, bound, request, members, by_path, cold):
    prefix = "run/" + fit["name"] + "/"
    read = lambda name: read_json(members[prefix + name])
    original_bytes, initial_bytes = [members[by_path[bound[key]]] for key in ("last_checkpoint", "initial_checkpoint")]
    require(digest(original_bytes) == fit["checkpoint_sha256"], "bound original checkpoint identity")
    original, initial, restored = map(load_state, (original_bytes, initial_bytes, members[prefix + "RESUME_START.pt"]))
    require(exact(original, restored), "all restored model/optimizer/RNG/schema tensor bytes")
    cold_result = read_json(cold.read("run/" + fit["name"] + "-replica1/RESULT.json"))
    trainable = set(cold_result["trainable_parameter_max_abs_changes"])
    require(len(trainable) == 11 and trainable <= original["model"].keys(), "bound cold-recovery trainable names")
    plan_path = request["original_root"] + "/campaign-v2/" + fit["name"] + "/plan.json"
    plan = read_json(members[by_path[plan_path]])
    dataset = read_json(members[by_path[plan["prepared"] + "/data-manifest.json"]])
    require(digest(members[by_path[plan["prepared"] + "/data-manifest.json"]]) == request["manifest_sha256"]
            and dataset["confirmation_access"] is False, "exact development-only data manifest")
    input_identities = dict(read_json(members["source/BINDINGS.json"])["input_files"])
    source_expectations = read_json(members[by_path[request["cold_probe_root"] + "/SOURCE_EXPECTATIONS.json"]])
    for relative, expected in source_expectations["source_files"].items():
        input_identities[request["original_root"] + "/" + request["source_relative"] + "/" + relative] = {"sha256": expected}
    input_identities[plan["prepared"] + "/data-manifest.json"] = {"sha256": request["manifest_sha256"]}
    for item in dataset["episodes"]:
        input_identities[plan["prepared"] + "/" + item["path"]] = {"sha256": item["sha256"]}
    require(read("INPUT_IDENTITIES.json") == input_identities, "complete original/source/dataset identity ledger")
    train = [row for row in dataset["episodes"] if row["partition"] == "train"]
    dev = [row for row in dataset["episodes"] if row["partition"] == "dev"]
    ids, event_counts = [row["id"] for row in train], {row["id"]: row["events"] for row in train}
    steps, batch_size, micro = bound["steps_per_epoch"], plan["batch_size"], plan["micro_batch_size"]
    require(sum(event_counts.values()) == 89216 and sum(row["events"] for row in dev) == 31952
            and steps == math.ceil(len(ids) / batch_size), "full original population and batch count")
    require(original["epochs_completed"] == fit["epoch"] and original["main_updates"] == fit["main_updates"],
            "original partial checkpoint counters")
    result = read("RESULT.json")
    require(digest(members[prefix + "INHERITED_BEST.pt"]) == fit["best_checkpoint_sha256"], "unchanged inherited strict-best bytes")
    inherited_validation = read("INHERITED_BEST_VALIDATION.json")
    require(inherited_validation["original_development"] == bound["best_development"], "original inherited-best metrics")
    fresh_inherited, prior_inherited = inherited_validation["fresh_development"], bound["best_development"]
    require(all(fresh_inherited[key] == prior_inherited[key] for key in ("confusion_matrix", "macro_f1_11_classes")),
            "original inherited-best CM/F1 restore conditions")
    inherited_differences = {key: abs(value - prior_inherited[key]) for key, value in fresh_inherited.items() if isinstance(value, (int, float))}
    require(inherited_differences == inherited_validation["scalar_absolute_differences"], "retained cross-runtime scalar differences without new tolerance")
    events = [read_json(line) for line in members[prefix + "events.jsonl"].splitlines()]
    require(digest(members[prefix + "events.jsonl"]) == result["events_sha256"], "complete new journal bytes")
    counts = Counter(row["kind"] for row in events)
    require(counts["failed"] == 0 and counts["finished"] == 1 and counts["restore_verified"] == 1, "complete successful journal envelope")
    require([row["new_phase_wall_seconds"] for row in events] == sorted(row["new_phase_wall_seconds"] for row in events),
            "monotone journal time")
    history, previous_commit = list(bound["inherited_history"]), bound["last_commit"]
    old_directory = request["original_root"] + "/c2-native-execution-20261110-c385-v1/fits/" + fit["name"]
    admission = read_json(members[by_path[old_directory + "/ADMISSION.json"]])
    initial_identity = admission["inputs"][bound["missing_original_initial_path"]]
    require(len(initial_bytes) == initial_identity["bytes"] and digest(initial_bytes) == initial_identity["sha256"],
            "alternate original initial file exactly matches target original admission bytes")
    inherited_history = list(admission["boundary"]["logical_epochs"])
    inherited_previous = None
    for number in range(bound["parent_retained_epochs"] + 1, fit["original_fit"]["epoch"] + 1):
        path = old_directory + f"/commits/epoch-{number:04d}.json"
        data = members[by_path[path]]; commit = read_json(data)
        require(commit["previous_commit"] == inherited_previous, "all original inherited commit links")
        inherited_history.append(commit["epoch"])
        require(plateau(inherited_history, request["stopping"])[0] == commit["stopping"], "every original inherited stopping state")
        inherited_previous = {"path": path, "bytes": len(data), "sha256": digest(data)}
    prior_directory = request["previous_continuation_root"] + "/RUN_OUTPUT/" + fit["name"]
    for number in range(fit["original_fit"]["epoch"] + 1, fit["epoch"] + 1):
        path = prior_directory + f"/commits/epoch-{number:04d}.json"
        data = members[by_path[path]]; commit = read_json(data)
        require(commit["previous_commit"] == inherited_previous, "prior independent continuation commit links")
        inherited_history.append(commit["epoch"])
        require(plateau(inherited_history, request["stopping"])[0] == commit["stopping"], "prior continuation stopping state")
        inherited_previous = {"path": path, "bytes": len(data), "sha256": digest(data)}
    require(inherited_history == history and inherited_previous == previous_commit, "inherited history independently rebuilt from original records")
    require(plateau(history, request["stopping"]) == (bound["stopping"], None), "inherited stopping state")
    rng = random.Random(); rng.setstate(original["order_rng"])
    updates, completed, epoch, batch_index, pending, stepping = original["main_updates"], [], None, 0, None, False
    order, objectives, last_update, last_epoch = None, [], restored, restored
    observed_checkpoints, changed_names, rng_hashes = set(), set(), set()
    latest_checkpoint_path = prefix + "RESUME_START.pt"
    final_epoch_path = by_path[bound["last_complete_epoch_checkpoint"]["path"]]
    last_committed = None
    for event in events:
        kind = event["kind"]
        if kind == "partial_epoch_resumed":
            cursor = original["continuation_cursor"]
            require(epoch is None and pending is None and not completed and counts[kind] == 1,
                    "one partial resume before new updates")
            epoch, batch_index = cursor["current_epoch"], cursor["completed_effective_batches"]
            order, objectives = list(cursor["episode_indices"]), list(cursor["completed_batch_objectives"])
            require(cursor == bound["partial_cursor"] and sorted(order) == list(range(len(ids)))
                    and event["epoch"] == len(history) + 1 == epoch
                    and event["episode_order"] == cursor["episode_ids"] == [ids[index] for index in order]
                    and event["already_completed_batches"] == batch_index == 5
                    and event["next_episode_offset"] == cursor["next_episode_offset"] == batch_index * batch_size,
                    "partial epoch order/objectives/next offset preserved without reshuffle or replay")
        elif kind == "epoch_started":
            require(epoch is None and pending is None, "new epoch follows completed prior epoch")
            epoch, batch_index, objectives = event["epoch"], 0, []
            require(epoch == len(history) + 1, "contiguous new epoch")
            order = list(range(len(ids))); rng.shuffle(order)
            require(event["episode_order"] == [ids[index] for index in order], "saved Python RNG shuffles exact original episode order")
        elif kind == "update_started":
            require(epoch == event["epoch"] and pending is None and event["batch_index"] == batch_index,
                    "effective batch inside correct epoch")
            pending = [ids[index] for index in order[batch_index * batch_size:(batch_index + 1) * batch_size]]
            require(event["episode_ids"] == pending and event["logical_next_update"] == updates + 1, "declared batch and logical update")
            micro_events = []
        elif kind == "micro_forward_started":
            require(pending is not None and not stepping and event["epoch"] == epoch and event["batch_index"] == batch_index,
                    "micro forward attached to pending effective batch")
            micro_events.append((event["start"], event["end"]))
        elif kind == "optimizer_started":
            require(pending is not None and not stepping and event["logical_next_update"] == updates + 1,
                    "one started AdamW call per batch")
            stepping = True
        elif kind == "optimizer_completed":
            require(stepping and pending is not None and event["epoch"] == epoch and event["batch_index"] == batch_index,
                    "completion follows actual optimizer start")
            updates += 1
            require(event["number"] == updates and event["new_number"] == updates - original["main_updates"], "contiguous actual update count")
            require(micro_events == [(i, min(i + micro, len(pending))) for i in range(0, len(pending), micro)]
                    and event["micro_forward_calls"] == len(micro_events)
                    and event["events"] == sum(event_counts[name] for name in pending), "complete microbatches and labelled events")
            require(math.isfinite(event["loss"]) and math.isfinite(event["gradient_norm"]) and event["gradient_norm"] >= 0
                    and event["target_weight_sum"] > 0 and event["weighted_loss_numerator"] == event["loss"] * event["target_weight_sum"],
                    "finite original weighted objective and gradient norm")
            require(event["within_scientific_budget"] == (event["optimizer_return_elapsed_seconds"] <= request["budget"]["scientific_wall_seconds_per_fit"]),
                    "late optimizer completion remains charged but ineligible")
            completed.append(event); objectives.append({key: event[key] for key in OBJECTIVE_KEYS})
            stepping, pending = False, None
        elif kind == "optimizer_checkpoint_committed":
            require(event["number"] == updates and completed and completed[-1]["number"] == updates
                    and last_committed != updates, "one durable checkpoint per completed update")
            record = event["checkpoint"]; name = by_path[record["path"]]
            require(digest(members[name]) == record["sha256"] and len(members[name]) == record["bytes"], "exact update checkpoint receipt")
            state = load_state(members[name])
            changed_names.update(check_state(state, original, initial, trainable, updates, len(history), request["manifest_sha256"]))
            cursor = {"schema": "hcsn-c2-mid-epoch-continuation-v2", "current_epoch": epoch, "episode_indices": order,
                      "episode_ids": [ids[index] for index in order], "next_episode_offset": min((batch_index + 1) * batch_size, len(ids)),
                      "completed_effective_batches": batch_index + 1, "completed_batch_objectives": objectives,
                      "batch_size": batch_size, "micro_batch_size": micro, "complete_epoch": False}
            require(state["continuation_cursor"] == cursor and exact(state["order_rng"], rng.getstate()), "complete durable mid-epoch cursor and order RNG")
            require(record["within_scientific_budget"] == completed[-1]["within_scientific_budget"], "checkpoint eligibility flag")
            rng_hashes.add(digest(state["torch_rng"].numpy().tobytes()))
            observed_checkpoints.add(name); last_update, latest_checkpoint_path, last_committed = state, name, updates
            batch_index += 1
        elif kind == "epoch_completed":
            require(epoch == event["epoch"] and pending is None and not stepping and batch_index == steps,
                    "complete epoch requires all committed optimizer batches")
            commit_record = event["commit"]; commit_name = by_path[commit_record["path"]]
            require(digest(members[commit_name]) == commit_record["sha256"], "exact complete epoch commit")
            commit = read_json(members[commit_name]); row = commit["epoch"]
            require(commit["previous_commit"] == previous_commit and commit["logical_main_updates"] == updates,
                    "unbroken inherited/new epoch commit chain")
            require(all(event[key] == value for key, value in row.items()) and row["events"] == 89216,
                    "epoch journal equals complete committed record")
            numerator, denominator = sum(x["weighted_loss_numerator"] for x in objectives), sum(x["target_weight_sum"] for x in objectives)
            require(row["training_weighted_loss_numerator"] == numerator and row["training_target_weight_sum"] == denominator
                    and row["training_weighted_loss"] == numerator / denominator, "full-epoch original weighted aggregation")
            compare_metrics(confusion_metrics(row["development"]["confusion_matrix"]), row["development"])
            history.append(row); stopping, first = plateau(history, request["stopping"])
            require(commit["stopping"] == stopping and (first is None or first == epoch), "strict best and distinct plateau anchor")
            record = commit["checkpoint"]; name = by_path[record["path"]]
            require(digest(members[name]) == record["sha256"] and len(members[name]) == record["bytes"], "exact epoch checkpoint")
            state = load_state(members[name])
            check_state(state, original, initial, trainable, updates, epoch, request["manifest_sha256"])
            expected = {key: value for key, value in last_update.items() if key != "continuation_cursor"}
            expected["epochs_completed"] = epoch
            require(exact(state, expected), "epoch commit changes only epoch cursor, retaining exact model/optimizer/RNG")
            require(digest(members[by_path[commit["best_checkpoint"]["path"]]]) == commit["best_checkpoint"]["sha256"], "best checkpoint identity")
            best_state = load_state(members[by_path[commit["best_checkpoint"]["path"]]])
            require(best_state["epochs_completed"] == stopping["best_epoch"], "strict-best checkpoint epoch")
            observed_checkpoints.add(name); last_epoch = last_update = state
            latest_checkpoint_path = final_epoch_path = name
            previous_commit, epoch = commit_record, None
    require(observed_checkpoints == {name for name in members if name.startswith(prefix + "updates/") or name.startswith(prefix + "checkpoints/")},
            "every saved new update/epoch checkpoint independently checked")
    require(result["epochs"] == history[len(bound["inherited_history"]):] and result["last_complete_epoch"] == len(history)
            and result["logical_main_updates"] == updates and result["last_commit"] == previous_commit, "complete result history and counters")
    require(not completed or bool(changed_names), "completed training includes saved nonzero trainable parameter change")
    require(by_path[result["last_complete_optimizer_checkpoint"]["path"]] == latest_checkpoint_path
            and by_path[result["last_complete_epoch_checkpoint"]["path"]] == final_epoch_path, "honest final durable checkpoint pointers")
    stopping, first = plateau(history, request["stopping"])
    require(result["stopping"] == stopping and counts["optimizer_started"] == result["new_optimizer_started"]
            and counts["optimizer_completed"] == result["new_optimizer_completed"] == len(completed)
            and counts["micro_forward_started"] == result["new_micro_forwards_started"], "journal-derived final work counters")
    require(result["open_optimizer_completion_interval"] == ([0, 1] if stepping else [0, 0])
            and result["uncommitted_optimizer_call"] == stepping, "unobserved in-flight optimizer is not invented")
    if epoch is None:
        require(result["live_partial_epoch_cursor"] is None, "no fabricated partial epoch after complete epoch")
    else:
        live_cursor = result["live_partial_epoch_cursor"]
        require(live_cursor["current_epoch"] == epoch and live_cursor["episode_indices"] == order
                and live_cursor["episode_ids"] == [ids[index] for index in order]
                and live_cursor["completed_effective_batches"] == batch_index
                and live_cursor["next_episode_offset"] == min(batch_index * batch_size, len(ids))
                and live_cursor["completed_batch_objectives"] == objectives and live_cursor["complete_epoch"] is False,
                "honest live partial epoch cursor")
    late = sum(not row["within_scientific_budget"] for row in completed)
    require(result["optimizer_completions_after_scientific_deadline"] == late
            and result["scientifically_in_budget_optimizer_completions"] == len(completed) - late, "complete late work accounting")
    require((result["status"] == "COMPLETED_PLATEAU") == (first == len(history)), "actual first plateau terminal")
    require(result["status"] in ("COMPLETED_PLATEAU", "BUDGET_STOP", "EPOCH_CAP"), "reviewable actual terminal category")
    if result["status"] == "EPOCH_CAP":
        require(len(history) == request["maximum_cumulative_epochs"], "actual epoch cap")
    selected_differences = selected_epoch_differences = None
    selected = result.get("selected_best_checkpoint")
    if selected is not None:
        selected_bytes = members[by_path[selected["path"]]]
        require(digest(selected_bytes) == selected["sha256"] and selected["epoch"] == stopping["best_epoch"]
                and load_state(selected_bytes)["epochs_completed"] == stopping["best_epoch"], "final strict-best checkpoint identity")
    if result["selected_development_complete"]:
        saved = load_state(members[prefix + "DEVELOPMENT_LOGITS.pt"])
        require(digest(members[prefix + "DEVELOPMENT_LOGITS.pt"]) == result["selected_development_logits"]["sha256"], "saved final logits receipt")
        require(saved["episode_ids"] == [row["id"] for row in dev], "full original development episode roster")
        selected_differences = compare_metrics(logits_metrics(saved), result["selected_development"])
        require(result["selected_development"]["confusion_matrix"] == history[stopping["best_epoch"] - 1]["development"]["confusion_matrix"],
                "selected-best final evaluation agrees with selected epoch")
        selected_reference = history[stopping["best_epoch"] - 1]["development"]
        require(result["selected_development"]["macro_f1_11_classes"] == selected_reference["macro_f1_11_classes"], "selected-best final macro F1")
        selected_epoch_differences = {key: abs(value - selected_reference[key]) for key, value in result["selected_development"].items() if isinstance(value, (int, float))}
    require(result["training_adequacy_established"] == bool(result["status"] == "COMPLETED_PLATEAU"
            and result["selected_development_complete"] and bound["inherited_memorization"]["passed"]), "limited declared adequacy rule")
    complete_development_forwards = math.ceil(len(dev) / batch_size) * (1 + len(result["epochs"]) + int(result["selected_development_complete"]))
    require(result["development_forwards_started"] >= complete_development_forwards, "complete development passes remain charged")
    if result["status"] == "COMPLETED_PLATEAU" and result["selected_development_complete"]:
        require(result["development_forwards_started"] == complete_development_forwards, "plateau terminal full-development forward count")
    for key, expected in {"scientific_admission": "HOLD", "original_controller_terminal": "UNKNOWN",
                          "independent_complete_training_replays": 0, "full_six_fit_replay": False,
                          "original_runtime_exact_replay": False, "confirmation_access": False}.items():
        require(result[key] == expected, "retained qualification limitation " + key)
    cost = read("COST.json")
    require(cost == read_json(members["run/" + fit["name"] + ".COST.json"])
            and cost["result_sha256"] == digest(members[prefix + "RESULT.json"]), "exact wait4 cost/result identity")
    require(cost["cpu_total_seconds"] == cost["cpu_user_seconds"] + cost["cpu_system_seconds"]
            and cost["full_fresh_process_wall_seconds"] == cost["wait4_return_monotonic"] - cost["dispatch_monotonic"], "whole-process wait4 arithmetic")
    limits = request["budget"]; scientific = limits["scientific_wall_seconds_per_fit"]
    wall = cost["full_fresh_process_wall_seconds"]
    require(all(result["runtime"][key] == request["runtime"][key] for key in ("python", "torch", "numpy"))
            and result["runtime"]["torch_threads"] == result["runtime"]["torch_interop_threads"] == limits["threads_per_fit"]
            and result["runtime"]["affinity"] == [cost["assigned_cpu"]], "actual one-thread CPU continuation runtime")
    require(cost["exit_code"] == 0 and cost["hard_killed"] is False and cost["result_status"] == result["status"]
            and cost["wall_within_scientific_budget_seconds"] == min(wall, scientific)
            and cost["cleanup_budget_overrun_wall_seconds"] == max(0.0, wall - scientific)
            and cost["scientific_wall_budget_seconds"] == result["scientific_wall_budget_seconds"] == scientific,
            "actual exit and complete scientific/cleanup cost partition")
    require(result["finalization_reserve_seconds"] == limits["finalization_reserve_seconds"]
            and result["new_phase_wall_seconds_before_exit"] <= wall
            and result["training_end_new_phase_wall_seconds"] <= result["new_phase_wall_seconds_before_exit"]
            and cost["peak_rss_kib"] * 1024 <= limits["peak_rss_stop_bytes_per_fit"]
            and cost["rss_limit_exceeded"] is False, "finalization is inside original budget and RSS scope")
    require(wall <= scientific + limits["cleanup_grace_seconds"], "declared scientific plus cleanup envelope")
    require(all(row["new_phase_wall_seconds"] < scientific for row in events if row["kind"] == "optimizer_started"),
            "no fresh optimizer call after scientific deadline")
    if cost["external_stop"] is not None:
        require(cost["post_external_stop_wall_seconds"] == cost["wait4_return_monotonic"] - cost["external_stop"]["monotonic"], "exact stop-to-reap cost")
    old_path = next(path for path in by_path if path.endswith("/fits/" + fit["name"] + "/events.jsonl"))
    old_events, malformed = [], []
    for number, line in enumerate(members[by_path[old_path]].splitlines(), 1):
        try:
            old_events.append(read_json(line))
        except json.JSONDecodeError:
            malformed.append({"line": number, "bytes": len(line), "sha256": digest(line)})
    require(malformed == bound["original_malformed_journal_lines"], "retained original malformed tail identity")
    old_updates = {row["number"]: row for row in old_events if row["kind"] == "optimizer_completed"
                   and row.get("phase") == "main" and row["number"] > fit["original_fit"]["epoch"] * steps}
    require(len(old_updates) == bound["original_surviving_completed_after_checkpoint"], "original partial completed work count")
    comparisons = [{"logical_update": row["number"], "absolute_differences": {
        key: abs(row[key] - old_updates[row["number"]][key]) for key in ("loss", "gradient_norm", "events", "micro_forward_calls")}}
        for row in completed if row["number"] in old_updates]
    first_adam = verify_first_adam(original,
        load_state(members[prefix + f"updates/update-{fit['main_updates'] + 1:08d}.pt"]),
        load_state(members[prefix + "FIRST_GRADIENTS.pt"])) if completed else None
    return {"first_restored_adam_update": first_adam, "fit": fit["name"], "status": result["status"], "start_epoch": fit["epoch"], "last_complete_epoch": len(history),
            "stopping": stopping, "new_optimizer_completed": len(completed), "new_micro_forwards_started": counts["micro_forward_started"],
            "complete_epochs": len(history) - fit["epoch"], "checked_new_checkpoints": len(observed_checkpoints),
            "development_forwards_reported": result["development_forwards_started"], "complete_development_forwards_minimum": complete_development_forwards,
            "changed_trainable_names": sorted(changed_names), "frozen_tensor_count": len(original["model"]) - len(trainable),
            "saved_torch_rng_hashes": sorted(rng_hashes), "complete_restore_tensor_bytes_equal": True,
            "old_partial_scalar_comparisons": comparisons, "old_partial_work_refunded": False,
            "old_partial_known_updates": len(old_updates), "old_partial_compared_updates": len(comparisons),
            "old_partial_unmatched_logical_updates": sorted(set(old_updates) - {row["logical_update"] for row in comparisons}),
            "inherited_best_cross_runtime_scalar_differences": inherited_differences, "selected_best_to_recorded_epoch_scalar_differences": selected_epoch_differences,
            "final_logit_metric_absolute_differences": selected_differences, "selected_development": result.get("selected_development"),
            "training_adequacy_established": result["training_adequacy_established"], "cost": cost,
            "optimizer_completions_after_training_reserve_boundary": sum(row["optimizer_return_elapsed_seconds"] > scientific - limits["finalization_reserve_seconds"] for row in completed),
            "open_optimizer_completion_interval": result["open_optimizer_completion_interval"],
            "live_partial_epoch_cursor": result["live_partial_epoch_cursor"], "late_optimizer_completions": late}


def main(archive, receipt_path):
    started, cpu = time.monotonic(), time.process_time()
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    receipt = read_json(receipt_path.read_bytes())
    members, manifest, by_path = archive_members(archive, receipt)
    request, freeze, bindings = [read_json(members["source/" + name]) for name in ("REQUEST.json", "FREEZE.json", "BINDINGS.json")]
    require(request["identity"] == freeze["identity"] == bindings["identity"] == manifest["identity"], "one archived continuation identity")
    for name, expected in freeze["files"].items():
        require(digest(members["source/" + name]) == expected, "unchanged frozen execution file " + name)
    for path, expected in bindings["input_files"].items():
        data = members[by_path[path]]
        require(len(data) == expected["bytes"] and digest(data) == expected["sha256"], "unchanged bound original input")
    expectations = read_json(members[by_path[request["cold_probe_root"] + "/SOURCE_EXPECTATIONS.json"]])
    for relative, expected in expectations["source_files"].items():
        original_path = request["original_root"] + "/" + request["source_relative"] + "/" + relative
        require(digest(members[by_path[original_path]]) == expected, "actual original numerical source " + relative)
    native, terminal = [read_json(members[name]) for name in ("native/NATIVE_TERMINAL.json", "run/TERMINAL.json")]
    launch = read_json(members["native/RUN_LAUNCH.json"])
    require(native["job_id"] == launch["job"]["id"]
            and launch["job"]["idempotency_key"] == request["identity"]
            and native["terminal_publication_confirmed"] is True
            and native["output_complete"] is True and native["state"] in ("succeeded", "failed", "cancelled", "timed_out")
            and terminal["status"] not in ("RUNNING", "FINISHING"), "actual authoritative terminal")
    require(terminal["source_freeze"] == terminal["source_freeze_after"]
            and terminal["source_freeze"]["freeze_sha256"] == digest(members["source/FREEZE.json"]), "controller before/after source freeze")
    cold_path = request["cold_probe_root"] + "/c2-cold-resume-exact-artifact.zip"
    cold_bytes = members[by_path[cold_path]]
    require(digest(cold_bytes) == request["cold_probe_archive_sha256"], "original bound cold-recovery archive")
    with ZipFile(io.BytesIO(cold_bytes)) as cold:
        cold_manifest = read_json(cold.read("MANIFEST.json"))
        for name, expected in cold_manifest["members"].items():
            data = cold.read(name)
            require(len(data) == expected["bytes"] and digest(data) == expected["sha256"], "bound cold-recovery member")
        reviews = [fit_review(fit, bindings["fits"][fit["name"]], request, members, by_path, cold) for fit in request["fits"]]
    for review in reviews:
        require(review["cost"] == terminal["fits"][review["fit"]], "controller terminal equals exact child wait4 receipt")
    return {"schema": "hcsn-c2-independent-archive-review-v1", "status": "VERIFIED_ARCHIVED_CONTINUATIONS",
            "reader_source_sha256": digest(Path(__file__).read_bytes()),
            "archive_sha256": receipt["sha256"], "archive_members_verified": len(members), "reviews": reviews,
            "independent_review_forward_calls": 0, "independent_review_optimizer_calls": 0,
            "metric_reader_arithmetic_absolute_bound": METRIC_ARITHMETIC_ABSOLUTE_BOUND,
            "metric_scope": "NumPy recomputation from saved logits/labels; no evaluation forward or independent model-inference/training replay. This arithmetic comparison does not change a scientific gate.",
            "gradient_scope": "First saved clipped gradients independently reproduce the first restored AdamW moment/parameter update with NumPy; gradient vectors are not independently regenerated by backward. All other checkpoints/ages/cursors are checked.",
            "rng_scope": "Full restored bytes and saved RNG representation checked; Python episode shuffles independently reproduced without model calls.",
            "dataset_scope": "Recorded episode SHA strings and roster identities are cross-checked. Episode payloads remain external and are not rehashed here; the frozen producer records their before/after verification.",
            "reader_runtime": {"python": platform.python_version(), "torch": torch.__version__, "numpy": np.__version__},
            "cost_scope": "Reader main after numerical imports; outer fresh-process import/startup cost must be retained separately. No scientific training budget is added.",
            "original_controller_terminal": "UNKNOWN", "independent_complete_training_replays": 0,
            "full_six_fit_replay": False, "original_runtime_exact_replay": False, "scientific_admission": "HOLD",
            "wall_seconds": time.monotonic() - started, "cpu_seconds": time.process_time() - cpu,
            "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, default=HERE / "evidence/c2-continuation-exact-artifact.tar.xz")
    parser.add_argument("--receipt", type=Path, default=HERE / "evidence/ARTIFACT.json")
    args = parser.parse_args()
    print(json.dumps(main(args.archive, args.receipt), sort_keys=True, indent=2, allow_nan=False))
