"""Independent finite empirical-law evaluator and original-native replay."""

import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess

import numpy as np


def clean(value):
    omitted = {"physical_receipt_processing_micros", "execution_micros", "restore_micros", "model_latency_micros",
               "transient_allocation_bytes", "model_resident_bytes"}
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items() if key not in omitted}
    if isinstance(value, list):
        return [clean(item) for item in value]
    return value


def replay(transcript, binary, development, scratch):
    scratch.mkdir()
    process, count, fingerprint = None, 0, hashlib.sha256()
    try:
        for entry in transcript:
            request = dict(entry["request"])
            if process is None:
                process = subprocess.Popen([str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True, bufsize=1)
            if request["command"] in ("Open", "Resume"):
                request["directory"] = str(scratch / "owner")
                request["model"] = str(development / "MODEL.json")
                request["calibration"] = str(development / "ENCODER_DOMAIN_PROOF.json")
            before_paths = sorted(str(path.relative_to(scratch)) for path in scratch.rglob("*")) if request["command"] == "Open" else None
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
            actual = json.loads(process.stdout.readline())
            if clean(actual) != clean(entry["response"]):
                failure = scratch.parent / "NATIVE_REPLAY_FAILURE.json"
                with failure.open("x") as stream:
                    json.dump({"request": request, "expected": entry["response"], "actual": actual,
                        "paths_before_open": before_paths, "paths_after_error": sorted(str(path.relative_to(scratch)) for path in scratch.rglob("*"))},
                        stream, indent=2, sort_keys=True)
                raise ValueError(f"Original owner replay differs at {request['command']}")
            fingerprint.update(json.dumps(clean(actual), sort_keys=True).encode())
            if request["command"] == "Tick":
                count += int(actual["result"]["native_transition_executed"])
            elif request["command"] == "Forecast":
                count += len(actual["result"]["ticks"])
            if request["command"] == "Close":
                process.stdin.close()
                process.wait(timeout=10)
                if process.returncode:
                    raise ValueError(process.stderr.read())
                process = None
    finally:
        if process is not None:
            process.stdin.close()
            process.wait(timeout=10)
        shutil.rmtree(scratch)
    return count, fingerprint.hexdigest()


def independent_prediction(fit, heads, condition, arm, expires, budget, shrinkage, protocol, given=None):
    def action(symbol):
        if arm == "history":
            return heads["history_moment_difference"][str(symbol)] >= 0
        if arm == "linear_memory":
            vector = np.asarray([1, .5 * symbol, .5 * abs(symbol), .5] + [0.0] * 7)
            return float(vector @ heads["linear_weights"]) >= 0
        return heads["native_by_feedback"][str(symbol)]["proposal"]
    p = protocol
    total = mean = success = cost_sum = moment = 0.0
    frequency = {s: sum(r["feedback"] == s for r in fit) / len(fit) for s in (-1, 0, 1)}
    for row in fit:
        mass = int(row["condition"] == condition) + shrinkage / len(fit)
        if mass == 0:
            continue
        if given is not None:
            if arm in ("native_numeric", "history", "linear_memory") and row["feedback"] != given:
                continue
            symbols = {given: 1.0}
        else:
            symbols = ({0: 1.0} if arm == "native_zero" else frequency if arm == "native_permuted"
                       else {row["feedback"]: 1.0})
        for symbol, probability in symbols.items():
            proposed = action(symbol)
            execute = proposed and expires >= 7 and budget >= 2
            score = row["alternate"] if execute else row["initial"]
            cost = 50 * p["native_kernel_charge"] + (1 + int(execute)) * (p["generator_call_charge"] + p["delivery_charge"])
            cost += int(proposed and not execute) * p["refused_proposal_charge"]
            weight = mass * probability
            utility = score["utility"] - cost
            total += weight
            moment += weight * math.exp(-p["gamma"] * utility)
            mean += weight * utility
            success += weight * score["strict_success"]
            cost_sum += weight * cost
    return {"moment": moment / total, "mean_utility": mean / total, "strict_probability": success / total,
            "mean_cost": cost_sum / total, "ce": -math.log(moment / total) / p["gamma"]}
