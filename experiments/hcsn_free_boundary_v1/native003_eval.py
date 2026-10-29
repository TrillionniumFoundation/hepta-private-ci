"""Fresh-holdout worker using actual model steps and the unchanged native owner."""

import argparse
from dataclasses import asdict
import hashlib
from pathlib import Path
import time

import numpy as np
import torch

from .native003_common import (PACKAGE, PROTOCOL_PATH, load_backbone, load_head,
                               read_json, sha, verify_freeze, write_new)
from .native003_heads import FAMILIES, Q, append_price, observed_features
from .native_bridge import MANIFEST, OBJECTIVE, NativeSession, Signals, UPSTREAM, restored_binary


REFERENCES = {"read_all": None, "fixed8": 8, "fixed16": 16, "fixed24": 24}


def learned_profile(family, model_digest):
    kernel = {"width": 5, "top_k": 1, "temporal_decay_q24": 0,
              "activity_decay_q24": 0, "target_activity_q24": 0,
              "threshold_rate_q24": 0, "threshold_min_q24": 0,
              "threshold_max_q24": 0, "eligibility_decay_q24": 0}
    return UPSTREAM.make_profile(
        ["learned_continue_score"],
        [[1, 0, 0, 0], [-1, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]],
        [0, 0, -4, -4, -4], [[1, -1, 0, 0, 0], [0] * 5, [0] * 5], [0, -8, 0],
        source_model_digest=model_digest, objective_digest=UPSTREAM.digest(OBJECTIVE),
        arm_id=f"native003-{family}", kernel=kernel, maximum_ticks=512)


class LearnedNativeSession(NativeSession):
    """Reuse immutable tick/retry/terminal guards; change only the declared profile."""

    def __init__(self, root, *, binary, family, model_digest, case, seed, resume=False):
        self.root, self.case, self.seed = Path(root), case, seed
        self.policy = family
        self.profile = learned_profile(family, model_digest)
        path, self.profile_digest = UPSTREAM.save_profile(self.root / "profiles", self.profile)
        self.bridge = UPSTREAM.NativeBridge(binary, self.root, expected_binary_sha256=MANIFEST["binary_sha256"])
        identity = self.bridge.identity
        if (identity["source_commit"] != MANIFEST["native_base_commit"]
                or identity["source_manifest_digest"] != MANIFEST["source_manifest_sha256"]
                or identity["owner_authority"] != "DENY_ALL"):
            self.bridge.close()
            raise ValueError("Native source or authority changed")
        self.bridge.load_profile(path, self.profile_digest)
        self.open_receipt = self.bridge.open(case, seed, self.profile_digest, resume=resume)
        self.terminal = bool(self.open_receipt["status"]["terminal"])
        self.events = []


def save_state(path, state):
    flat = {"elapsed": state["elapsed"].detach().cpu().numpy()}
    for index, layer in enumerate(state["layers"]):
        flat.update({f"layer{index}.{key}": value.detach().cpu().numpy() for key, value in layer.items()})
    np.savez_compressed(path, **flat)


def load_state(path, depth):
    with np.load(path, allow_pickle=False) as source:
        state = {"elapsed": torch.from_numpy(np.array(source["elapsed"], copy=True)), "layers": []}
        for index in range(depth):
            state["layers"].append({key: torch.from_numpy(np.array(source[f"layer{index}.{key}"], copy=True))
                                     for key in ("content", "voltage", "refractory", "event")})
    return state


def state_identity(state):
    entries = {"elapsed": state["elapsed"]}
    for index, layer in enumerate(state["layers"]):
        entries.update({f"layer{index}.{key}": value for key, value in layer.items()})
    return UPSTREAM.digest({key: {"shape": list(value.shape), "dtype": str(value.dtype),
                                  "sha256": hashlib.sha256(value.detach().cpu().numpy().tobytes()).hexdigest()}
                            for key, value in entries.items()})


def run_episode(model, head, family, selection, x, dt, label, episode_id, number,
                price, directory, binary, identity, *, recover=False, reload_objects=None):
    directory = Path(directory)
    case = f"fresh{number:05d}"
    model_digest = UPSTREAM.digest({"backbone": identity["backbone_checkpoint_sha256"],
                                    "head": selection["selected_checkpoint_sha256"],
                                    "family": family, "protocol": identity["protocol_sha256"]})
    native = LearnedNativeSession(directory, binary=binary, family=family,
                                   model_digest=model_digest, case=case, seed=number)
    state, events, native_costs, recovery_records = None, [], [], []
    model_cpu, head_cpu, recovery_cpu = 0.0, 0.0, 0.0
    active_model, active_head = model, head
    for index in range(len(x)):
        clock = time.process_time()
        with torch.no_grad():
            logits, state, aux = active_model.step(x[index:index + 1], dt[index:index + 1], state)
        model_cpu += time.process_time() - clock
        clock = time.process_time()
        with torch.no_grad():
            observed = observed_features(logits[:, None], aux, state["elapsed"][:, None])[:, 0]
            features = append_price(observed, price)
            score = active_head(features)[0]
            if not torch.isfinite(score):
                raise FloatingPointError("Nonfinite live continue score")
            bounded = torch.tanh(score).item()
            prediction = int(logits.argmax(-1).item())
        head_cpu += time.process_time() - clock
        quantized = UPSTREAM.quantize(bounded)
        expected = "keep" if quantized > 0 else "stop"
        float_expected = "keep" if score.item() > 0 else "stop"
        rounding_tie = quantized == 0
        if float_expected != expected and not (rounding_tie and abs(bounded) <= 0.5 / Q + 1e-12):
            raise ValueError("Float/Q24 action disagreement beyond a recorded rounding tie")
        signals = Signals(bounded, 0.0, 0.0, 0.0)
        context = {"fresh_dataset_sha256": identity["fresh_dataset_sha256"],
                   "episode": episode_id, "price": price, "prefix": index + 1,
                   "head_sha256": selection["selected_checkpoint_sha256"],
                   "observed_head_inputs": features[0].tolist()}
        row = native.tick(signals, context=context)
        if row["native"]["effective_action"] != expected:
            raise ValueError("Native NDU action differs from the frozen Q24 score rule")
        events.append({"prefix": index + 1, "prediction": prediction, "features": features[0].tolist(),
                       "score": score.item(), "bounded_score": bounded, "score_q24": quantized,
                       "float_action": float_expected, "q24_action": expected,
                       "rounding_tie": rounding_tie, "native": row["native"]})
        if native.terminal:
            break
        if recover and index == 0:
            if reload_objects is None:
                raise ValueError("Recovery requires an explicit object reconstruction callback")
            clock = time.process_time()
            snapshot = directory / "STATE.npz"
            before = state_identity(state)
            save_state(snapshot, state)
            write_new(directory / "STATE.json", {"cursor": index + 1, "state_identity": before,
                                                 "model_digest": model_digest, "task_identity": identity})
            native_costs.append(native.close())
            active_model, active_head = reload_objects()
            state = load_state(snapshot, active_model.config["depth"])
            if state_identity(state) != before:
                raise ValueError("Numeric recurrent state changed on reload")
            native = LearnedNativeSession(directory, binary=binary, family=family,
                                           model_digest=model_digest, case=case, seed=number, resume=True)
            spent = time.process_time() - clock
            recovery_cpu += spent
            recovery_records.append({"state_sha256": sha(snapshot), "state_identity": before,
                                      "cursor": index + 1, "native_resume": native.open_receipt,
                                      "parent_cpu_seconds": spent, "new_native_process": True,
                                      "new_neural_and_head_objects": True, "new_python_interpreter": False})
    terminal = native.verify_terminal() if native.terminal else None
    native_costs.append(native.close())
    reads = len(events)
    correct = int(prediction == int(label))
    result = {"episode": episode_id, "family": family, "read_price": price,
              "actual_reads": reads, "actual_model_steps": reads, "actual_head_steps": reads,
              "avoided_model_steps": len(x) - reads, "correct": correct,
              "prediction": prediction, "utility": correct - price * reads,
              "stop_reason": "native_stop" if native.terminal else "finite_horizon",
              "model_cpu_seconds": model_cpu, "head_cpu_seconds": head_cpu,
              "recovery_parent_cpu_seconds": recovery_cpu,
              "native_process_costs": native_costs, "recoveries": recovery_records,
              "terminal_probe": terminal, "events": events}
    write_new(directory / "RESULT.json", result)
    return result


def summarize_native(records, parent_cpu):
    costs = [cost for row in records for cost in row["native_process_costs"]]
    native_cpu = sum(cost["child_cpu_seconds"] for cost in costs)
    counters = {key: sum(cost["counters"][key] for cost in costs) for key in (
        "owner_ticks", "total_native_kernel_calls", "total_native_ndu_calls",
        "original_journal_replay_steps", "event_validation_kernel_steps",
        "event_validation_ndu_calls", "native_errors", "rpc_calls")}
    if counters["owner_ticks"] != sum(row["actual_reads"] for row in records):
        raise ValueError("Native owner ticks do not equal actual paid reads")
    n = len(records)
    return {"episodes": n, "accuracy": sum(row["correct"] for row in records) / n,
            "mean_reads": sum(row["actual_reads"] for row in records) / n,
            "mean_utility": sum(row["utility"] for row in records) / n,
            "native_stop_episodes": sum(row["stop_reason"] == "native_stop" for row in records),
            "parent_cpu_seconds": parent_cpu, "native_child_cpu_seconds": native_cpu,
            "model_cpu_seconds": sum(row["model_cpu_seconds"] for row in records),
            "head_cpu_seconds": sum(row["head_cpu_seconds"] for row in records),
            "execution_cpu_per_episode": (parent_cpu + native_cpu) / n,
            "native_counters": counters,
            "q24_zero_ties": sum(event["rounding_tie"] for row in records for event in row["events"]),
            "float_q24_action_disagreements": sum(event["float_action"] != event["q24_action"] for row in records for event in row["events"]),
            "recovery_count": sum(len(row["recoveries"]) for row in records),
            "ledger": [{key: row[key] for key in ("episode", "actual_reads", "correct", "prediction", "utility", "stop_reason")}
                       for row in records]}


def run_references(model, x, dt, labels, ids, price, output):
    summaries = {}
    for name, count in REFERENCES.items():
        started = time.process_time()
        count = x.shape[1] if count is None else count
        if count > x.shape[1]:
            raise ValueError("Fixed reference exceeds horizon")
        records = []
        for number in range(len(x)):
            state, model_cpu, steps = None, 0.0, []
            for index in range(count):
                clock = time.process_time()
                with torch.no_grad():
                    logits, state, _ = model.step(x[number:number + 1, index], dt[number:number + 1, index], state)
                model_cpu += time.process_time() - clock
                prediction = int(logits.argmax(-1).item())
                steps.append({"prefix": index + 1, "prediction": prediction,
                              "logits_sha256": hashlib.sha256(logits.numpy().tobytes()).hexdigest()})
            correct = int(prediction == int(labels[number]))
            row = {"episode": ids[number], "actual_reads": count, "actual_model_steps": count,
                   "correct": correct, "prediction": prediction, "utility": correct - price * count,
                   "model_cpu_seconds": model_cpu, "stop_reason": name, "steps": steps}
            write_new(Path(output) / name / f"fresh{number:05d}.json", row)
            records.append(row)
        parent_cpu = time.process_time() - started
        summaries[name] = {"episodes": len(records), "accuracy": sum(row["correct"] for row in records) / len(records),
                           "mean_reads": count, "mean_utility": sum(row["utility"] for row in records) / len(records),
                           "parent_cpu_seconds": parent_cpu, "native_child_cpu_seconds": 0.0,
                           "execution_cpu_per_episode": parent_cpu / len(records),
                           "model_cpu_seconds": sum(row["model_cpu_seconds"] for row in records),
                           "ledger": [{key: row[key] for key in ("episode", "actual_reads", "correct", "prediction", "utility", "stop_reason")}
                                      for row in records]}
    return summaries


def run_evaluation(output):
    output = Path(output)
    verify_freeze(output)
    protocol = read_json(PROTOCOL_PATH)
    lock = read_json(output / "TRAINING_LOCK.json")
    for name, expected in lock["files"].items():
        if sha(output / name) != expected:
            raise ValueError("Head selection changed before fresh-test access")
    if not read_json(output / "TRAINING_SUMMARY.json")["head_selections_locked"]:
        raise ValueError("All head selections must be locked before fresh-test access")
    torch.set_num_threads(1)
    model, backbone = load_backbone(protocol)
    heads = {family: load_head(output, family) for family in FAMILIES}
    data = PACKAGE / "data/native003/fresh_mnist.npz"
    metadata = read_json(data.with_suffix(".json"))
    with np.load(data, allow_pickle=False) as archive:
        x = torch.from_numpy(np.array(archive["test_x"], copy=True))
        dt = torch.from_numpy(np.array(archive["test_dt"], copy=True))
        labels = torch.from_numpy(np.array(archive["test_y"][:, -1], copy=True))
    ids = metadata["splits"]["test"]["episode_ids"]
    if len(x) != protocol["data"]["fresh_test_episodes"] or len(ids) != len(x):
        raise ValueError("Fresh test cohort size changed")
    identity = {"fresh_dataset_sha256": sha(data), "fresh_manifest_sha256": sha(data.with_suffix(".json")),
                "backbone_checkpoint_sha256": backbone["checkpoint_sha256"],
                "protocol_sha256": sha(PROTOCOL_PATH), "training_lock_sha256": sha(output / "TRAINING_LOCK.json")}
    write_new(output / "FRESH_INPUT_IDENTITY.json", {**identity, "episode_ids": ids,
                                                    "head_selections": {name: selection for name, (_, selection) in heads.items()}})
    binary = restored_binary()
    cohorts = []
    for price in protocol["execution"]["read_prices"]:
        directory = output / "evaluation" / ("price_" + format(price, ".3f").replace(".", "p"))
        summaries = {}
        for family, (head, selection) in heads.items():
            started = time.process_time()
            records = [run_episode(model, head, family, selection, x[i], dt[i], labels[i], ids[i], i,
                                    price, directory / family / f"fresh{i:05d}", binary, identity)
                       for i in range(len(x))]
            summaries[family] = summarize_native(records, time.process_time() - started)
        summaries.update(run_references(model, x, dt, labels, ids, price, directory / "references"))
        cohort = {"read_price": price, "results": summaries}
        write_new(directory / "SUMMARY.json", cohort)
        cohorts.append(cohort)
    recovery = {}
    for family, (head, selection) in heads.items():
        started = time.process_time()

        def reload_objects():
            new_model, _ = load_backbone(protocol)
            new_head, _ = load_head(output, family)
            return new_model, new_head

        record = run_episode(model, head, family, selection, x[0], dt[0], labels[0], ids[0], 0,
                              0.005, output / "recovery" / family, binary, identity,
                              recover=True, reload_objects=reload_objects)
        uninterrupted = read_json(output / "evaluation/price_0p005" / family / "fresh00000/RESULT.json")
        keys = ("prefix", "prediction", "features", "score", "score_q24", "q24_action")
        native_keys = ("checkpoint_before", "checkpoint_after", "activation_q24", "readout", "effective_action")

        def numerical(row):
            return [{**{key: event[key] for key in keys}, "native": {key: event["native"][key] for key in native_keys}}
                    for event in row["events"]]

        if numerical(record) != numerical(uninterrupted):
            raise ValueError(f"Restored learned controller trajectory differs: {family}")
        recovery[family] = {**summarize_native([record], time.process_time() - started),
                            "matches_uninterrupted_including_context_digests": True,
                            "new_python_interpreter": False}
    verify_freeze(output)
    result = {"status": "completed", "fresh_episodes": len(x), "cohorts": cohorts,
              "recovery": recovery, "identity": identity, "native_authority": "DENY_ALL",
              "hardware_energy_measured": False, "head_fitting_on_fresh_test": False}
    write_new(output / "EVALUATION_SUMMARY.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    run_evaluation(args.output)
