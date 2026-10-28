"""Persist, confirm and independently replay round-two feedback experiments."""

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy.special import expit, ndtr

from ..audit_feedback import _archive
from ..evidence_audit import _Audit
from ..native_adapter import Native
from . import feedback


SEEDS = (101, 211, 307, 401, 503)


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def save_data(path, data):
    if Path(path).exists():
        raise FileExistsError(path)
    np.savez_compressed(path, **data)


def _law(model, public, arm, saved, audit):
    c = model["calibration"]
    prior, sensor = c["error_variance"], c["noise_scale"] * public["sensor_variance"]
    joint = np.asarray([[prior, prior], [prior, prior + sensor]])
    mean = float(joint[0, 1] * public["residual"] / joint[1, 1])
    variance = float(joint[0, 0] - joint[0, 1] ** 2 / joint[1, 1])
    if arm in ("event", "quantized"):
        codec, config = saved["codec"], c["event_config"]
        steps = [config["mean_step"], config["logvar_step"]]
        config = {**config, "mode": "error_feedback" if arm == "event" else "direct_quantization"}
        levels = [0, 0]
        for i, (packet, target) in enumerate(zip(codec["packets"], ([0.0, math.log(prior)], [mean, math.log(variance)])), 1):
            expected_level = [math.floor(target[j] / steps[j] + 0.5) for j in range(2)]
            audit.require(set(packet) == {"schema", "config_sha256", "sequence", "time", "observation_kind", "counts"}, "codec", "No analog packet bypass")
            audit.require(packet["schema"] == "hepta.signed-event.packet.v1" and packet["config_sha256"] == feedback.digest(config)
                          and packet["sequence"] == i and packet["time"] == float(i - 1)
                          and packet["observation_kind"] == ("propagation" if i == 1 else "observed"), "codec", "Packet identity/time")
            audit.require(packet["counts"] == [expected_level[j] - levels[j] for j in range(2)], "codec", "Independent signed-count reconstruction")
            levels = expected_level
        audit.require(len(codec["packets"]) == 2 and codec["decoder"]["levels"] == levels
                      and codec["decoder"]["sequence"] == 2 and codec["decoder"]["config"] == config, "codec", "Decoder state")
        audit.require(codec["logical_unit_events"] == sum(abs(x) for p in codec["packets"] for x in p["counts"]), "codec", "Event cost")
        mean, variance = levels[0] * steps[0], math.exp(levels[1] * steps[1])
    else:
        audit.require(saved["codec"] is None, "codec", "Only event/quantized arms claim codec")
    amount, cost = mean, public["repair_cost"]
    if amount == 0:
        probability, threshold, event = 0.0, None, "empty_positive_gain_event"
    else:
        threshold = (amount * amount + cost) / (2 * amount)
        probability = float(ndtr((mean - threshold) / math.sqrt(variance))) if amount > 0 else float(ndtr((threshold - mean) / math.sqrt(variance)))
        event = "call: E>threshold" if amount > 0 else "put: E<threshold"
    result = {"mean": mean, "variance": variance, "repair_amount": amount,
              "expected_gain": amount * amount - cost, "improvement_probability": probability}
    for key, value in result.items():
        audit.close(saved[key], value, "posterior", key)
    audit.require(saved["event"] == event and (saved["threshold"] is None) == (threshold is None), "event", "Direction/zero event")
    if threshold is not None:
        audit.close(saved["threshold"], threshold, "event", "Cost-dependent threshold")
    return result


def audit_evaluation(result, data, model, native, root):
    began, audit = time.perf_counter_ns(), _Audit()
    audit.require(result["model_sha256"] == feedback.digest(model) and result["dataset_sha256"] == feedback.dataset_digest(data), "identity", "Model/data")
    audit.require(model["native_binary_sha256"] == native.receipt["binary_sha256"] == file_sha(native.binary), "identity", "Native binary")
    receipts, archive_files = _archive(result["archive"], root, audit)
    used, seen, by_arm = set(), set(), {arm: [] for arm in feedback.ARMS}
    position = {str(value): i for i, value in enumerate(data["ids"])}
    native_ticks = 0
    for row in result["rows"]:
        case, arm = row["case"], row["arm"]
        audit.require(case in position and arm in feedback.ARMS and (case, arm) not in seen, "coverage", "Unique episode")
        seen.add((case, arm))
        i = position[case]
        def read(kind, stage):
            key = (case, arm, kind, stage)
            used.add(key)
            return receipts[key]
        initial_receipt, initial = read("delivery", "initial")
        sensor_receipt, sensor = read("observation", "self_evaluation")
        noise_receipt, noise = read("observation", "sensor_variance")
        cost_receipt, cost = read("observation", "repair_cost")
        feedback_receipt, residual = read("delivery", "feedback")
        final_receipt, delivered = read("delivery", "final")
        public = {"initial": initial, "residual": residual, "sensor_variance": noise, "repair_cost": cost}
        expected = {"initial": float(data["initial_output"][i]), "residual": sensor - initial,
                    "sensor_variance": float(data["sensor_variance"][i]), "repair_cost": float(data["repair_cost"][i])}
        audit.close(sensor, float(data["self_evaluation"][i]), "readback", "Sensor", exact=True)
        audit.require(public == expected == row["acquired"]["public"] and row["acquired"]["public_sha256"] == feedback.digest(public), "readback", "Declared public information")
        timeline = [initial_receipt["readback_ns"], sensor_receipt["began_ns"], sensor_receipt["readback_ns"],
                    noise_receipt["began_ns"], noise_receipt["readback_ns"], cost_receipt["began_ns"], cost_receipt["readback_ns"],
                    feedback_receipt["began_ns"], feedback_receipt["readback_ns"], row["acquired"]["acquired_ns"],
                    row["decision_ns"], final_receipt["began_ns"], final_receipt["readback_ns"], row["final_readback_ns"], row["score_started_ns"]]
        audit.require(all(a <= b for a, b in zip(timeline, timeline[1:])), "chronology", "Public acquisition before decision before private score")
        law = _law(model, public, arm, row["posterior"], audit)
        c = model["calibration"]
        raw = np.asarray([residual, math.log(noise), math.log(cost)])
        z = (raw - c["public_center"]) / c["public_scale"]
        vector = None
        if arm == "history":
            powers = [(a, b, c) for a in range(4) for b in range(4) for c in range(4) if a + b + c <= 3]
            vector = np.concatenate(([float(np.prod(z ** p)) for p in powers],
                    np.exp(-0.5 * np.sum((np.asarray(c["history_centers"]) - z) ** 2, axis=1))))
        elif arm in feedback.NATIVE_ARMS:
            logv = (math.log(law["variance"]) - c["logvar_center"]) / c["logvar_scale"]
            drives = np.tanh(z / 3) if arm == "numeric" else np.asarray([2 * law["improvement_probability"] - 1,
                math.tanh(logv / 3), math.tanh(z[2] / 3)])
            if arm == "zero":
                drives = np.zeros(3)
            audit.require(len(row["native"]) == 3, "native", "Three equal-width information channels")
            vector = []
            for channel, saved in enumerate(row["native"]):
                q = int(round(float(drives[channel]) * feedback.Q24))
                actual = native.tick_pair(case + f"/channel{channel}", feedback.digest(public), q, reset_before_readout=arm == "reset")
                audit.require(actual["original_sparse_tick_calls"] == saved["original_sparse_tick_calls"] == 2, "native", "Original two-tick chain")
                audit.require(saved["feedback_q24"] == q and saved["public_sha256"] == feedback.digest(public), "native", "Readback-bound encoded input")
                audit.require(row["acquired"]["acquired_ns"] <= saved["started_ns"] <= saved["completed_ns"] <= row["decision_ns"], "chronology", "Native execution precedes choice")
                for a, b in zip(saved["ticks"], actual["ticks"]):
                    audit.require({k: v for k, v in a.items() if k != "native_ns"} == {k: v for k, v in b.items() if k != "native_ns"}, "native_replay", "Full original tick state")
                    audit.require(a["authority"] == "DENY_ALL" and a["requires_calibration"], "native", "No authority promotion")
                audit.require(actual["ticks"][1]["drive_q24"] == [0] * 10 and actual["checkpoint_reset_intervention"] == (arm == "reset"), "native", "No fresh second-tick drive")
                tick = actual["ticks"][1]
                vector.extend([1.0] + [x / feedback.Q24 for field in ("activation_q24", "eligibility_q24") for x in tick[field]])
                native_ticks += 2
            vector = np.asarray(vector)
        if vector is None:
            audit.require(row["feature"] is None and row["native"] == [], "features", "Direct arm")
            score = law["improvement_probability"]
            repair = law["expected_gain"] > 0 if arm == "gaussian" else score > 0.5
        else:
            audit.require(len(vector) == 63, "features", "Matched head dimension")
            audit.close(row["feature"], vector, "features", "Independent reconstruction")
            head = model["heads"][arm]
            score = float(expit(np.dot(vector, head["weights"])))
            repair = True if head["threshold"] == 0 else False if head["threshold"] == 1 else score >= head["threshold"]
        audit.close(row["score"], score, "choice", "Frozen head score")
        audit.require(bool(row["repair"]) == bool(repair), "choice", "Frozen action")
        audit.close(delivered, initial + (law["repair_amount"] if repair else 0.0), "delivery", "Independent final value")
        audit.close(row["delivered"], delivered, "delivery", "Recorded readback", exact=True)
        paid = cost if repair else 0.0
        error = (delivered - float(data["target"][i])) ** 2
        for key, value in (("cost", paid), ("squared_error", error), ("utility", 1 - error - paid)):
            audit.close(row[key], value, "score", key)
        gain = (initial - float(data["target"][i])) ** 2 - (initial + law["repair_amount"] - float(data["target"][i])) ** 2 - cost
        audit.require(row["improvement_label"] == (gain > 0) and row["model_sha256"] == feedback.digest(model), "score", "Postdecision label/model binding")
        by_arm[arm].append(row)
    audit.require(len(seen) == len(data["ids"]) * len(feedback.ARMS) and used == set(receipts), "coverage", "All episodes and public artifacts")
    audit.require(native_ticks == result["native_ticks"] == len(data["ids"]) * len(feedback.NATIVE_ARMS) * 6, "coverage", "Every original tick replayed")
    recorded_requests = [entry for row in result["rows"] for entry in row["native"]]
    audit.require(result["native_requests"] == len(recorded_requests) == native_ticks // 2,
                  "cost", "Native request count")
    audit.require(result["native_roundtrip_ns"] == sum(entry["subprocess_roundtrip_ns"] for entry in recorded_requests),
                  "cost", "Native adapter roundtrip accounting")
    for arm, values in by_arm.items():
        for key in ("utility", "cost", "squared_error", "wall_ns"):
            audit.close(result["summary"][arm][key], float(np.mean([v[key] for v in values])), "summary", arm + key)
        audit.require(result["summary"][arm]["repairs"] == sum(v["repair"] for v in values), "summary", arm + " repairs")
        audit.require(result["summary"][arm]["episodes"] == len(values), "summary", arm + " episodes")
        probability = np.clip([v["score"] for v in values], 1e-12, 1 - 1e-12)
        label = np.asarray([v["improvement_label"] for v in values], float)
        nll = float(np.mean(-label * np.log(probability) - (1 - label) * np.log1p(-probability)))
        audit.close(result["summary"][arm]["improvement_nll"], nll, "summary", arm + " clipped improvement NLL")
    return {"schema": "hepta.feedback-audit.v2", "passed": True, "checks": audit.counts,
            "episodes": len(seen), "native_ticks_replayed": native_ticks, "archive_files": archive_files,
            "native_requests": len(recorded_requests),
            "recorded_native_roundtrip_ns": sum(entry["subprocess_roundtrip_ns"] for entry in recorded_requests),
            "recorded_native_kernel_tick_ns": sum(tick["native_ns"] for entry in recorded_requests for tick in entry["ticks"]),
            "improvement_nll_definition": "Binary improvement probabilities clipped to [1e-12, 1-1e-12]; not an unclipped tail logscore",
            "wall_ns": time.perf_counter_ns() - began, "source_sha256": file_sha(__file__),
            "scope": "Every confirmation readback, count packet, original native tick, frozen decision and score; not process-memory isolation proof"}


def train_seed(seed, output, native_binary, native_receipt):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    training = feedback.build_dataset(10_000_000 + seed * 100 + 1, 384, "train")
    development = feedback.build_dataset(10_000_000 + seed * 100 + 2, 128, "development")
    with Native(native_binary, native_receipt) as native:
        model, receipt = feedback.fit(training, development, native, output)
    save_data(output / "TRAIN.npz", training)
    save_data(output / "DEVELOPMENT.npz", development)
    write_json(output / "MODELS.json", model)
    with gzip.open(output / "TRAINING_RECEIPT.json.gz", "xt") as stream:
        json.dump(receipt, stream, sort_keys=True, allow_nan=False, separators=(",", ":"))
    summary = {k: v for k, v in receipt.items() if k != "scopes"}
    summary.update(seed=seed, models_file_sha256=file_sha(output / "MODELS.json"),
                   training_receipt_sha256=file_sha(output / "TRAINING_RECEIPT.json.gz"))
    write_json(output / "TRAINING_SUMMARY.json", summary)
    return summary


def confirm_seed(seed, model_directory, output, native_binary, native_receipt, expected_model_sha256):
    model_file = Path(model_directory) / "MODELS.json"
    if file_sha(model_file) != expected_model_sha256:
        raise ValueError("Frozen trained model file changed")
    model = json.loads(model_file.read_text())
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    data = feedback.build_dataset(10_000_000 + seed * 100 + 3, 256, "confirmation")
    save_data(output / "DATA.npz", data)
    with Native(native_binary, native_receipt) as native:
        result = feedback.evaluate(model, data, native, output)
    with gzip.open(output / "ROWS.json.gz", "xt") as stream:
        json.dump(result["rows"], stream, sort_keys=True, allow_nan=False, separators=(",", ":"))
    summary = {k: v for k, v in result.items() if k != "rows"}
    summary.update(seed=seed, rows_sha256=file_sha(output / "ROWS.json.gz"), data_file_sha256=file_sha(output / "DATA.npz"),
                   models_file_sha256=expected_model_sha256)
    write_json(output / "SUMMARY.json", summary)
    with Native(native_binary, native_receipt) as native:
        audit = audit_evaluation(result, data, model, native, output)
    write_json(output / "AUDIT.json", audit)
    return summary, audit


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("train", "confirm"))
    parser.add_argument("--seed", required=True, type=int)
    for name in ("output", "native-binary", "native-receipt"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--model-directory")
    parser.add_argument("--expected-model-sha256")
    args = vars(parser.parse_args())
    operation = args.pop("operation")
    if operation == "train":
        args.pop("model_directory")
        args.pop("expected_model_sha256")
        result = train_seed(**args)
        print(json.dumps({"models_file_sha256": result["models_file_sha256"], "wall_ns": result["wall_ns"]}))
    else:
        result, audit = confirm_seed(**args)
        print(json.dumps({"summary": result["summary"], "audit": audit}))
