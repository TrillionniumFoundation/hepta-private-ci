"""Reopen every feedback artifact and replay all original native calls."""

import gzip
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import tarfile
import time

import numpy as np
from scipy.special import ndtr

from ..analytic import event_probs
from ..audit_feedback import _archive
from ..evidence_audit import _Audit
from ..native_adapter import Native
from .feedback import ARMS, LEARNED, POWERS, Q24, STEP, digest
from .feedback_study import archive_directory, load_data, write_json
from .runtime_feedback import file_sha


def owner_members(path, metadata, audit):
    audit.require(file_sha(path) == metadata["sha256"] and Path(path).stat().st_size == metadata["bytes"], "owners", "Archive binding")
    members = {}
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            parsed = PurePosixPath(member.name)
            audit.require(not parsed.is_absolute() and ".." not in parsed.parts, "owners", "Safe path")
            if member.isdir():
                continue
            audit.require(member.isfile() and member.name not in members, "owners", "Unique regular file")
            members[member.name] = archive.extractfile(member).read()
    manifest_name = next(x for x in members if x.count("/") == 1 and x.endswith("/MANIFEST.json"))
    root = manifest_name.split("/")[0] + "/"
    manifest = json.loads(members[manifest_name])["files"]
    audit.require(set(members) == {root + name for name in manifest} | {manifest_name}, "owners", "Full inventory")
    for name, expected in manifest.items():
        content = members[root + name]
        audit.require(len(content) == expected["bytes"] and hashlib.sha256(content).hexdigest() == expected["sha256"], "owners", "Member hash")
    return members, root


def _conditional(calibration, public):
    alpha = calibration["error_variance"]
    noise = np.asarray(public["variances"]) * calibration["noise_scale"]
    covariance = np.full((len(noise), len(noise)), alpha) + np.diag(noise)
    regression = np.linalg.solve(covariance, np.full(len(noise), alpha))
    return float(regression @ public["residuals"]), float(alpha - alpha * regression.sum())


def _wait(mean, variance, cost, noise, wait_cost):
    spread = math.sqrt(variance * variance / (variance + noise))
    cutoff = math.sqrt(cost)
    zplus, zminus = (mean - cutoff) / spread, (-mean - cutoff) / spread
    density = lambda z: math.exp(-z * z / 2) / math.sqrt(2 * math.pi)
    base = mean * mean + spread * spread - cost
    expectation = (base * (ndtr(zplus) + ndtr(zminus))
        + spread * (mean + cutoff) * density(zplus)
        + spread * (cutoff - mean) * density(zminus))
    return max(0.0, float(expectation)) - wait_cost


def audit_seed(output, prepared, native_binary, native_receipt):
    began, output = time.perf_counter_ns(), Path(output)
    model = json.loads((Path(prepared) / "MODELS.json").read_text())
    data, summary = load_data(output / "DATA.npz"), json.loads((output / "SUMMARY.json").read_text())
    with gzip.open(output / "ROWS.json.gz", "rt") as stream:
        rows = json.load(stream)
    audit = _Audit()
    audit.require(summary["model_file_sha256"] == file_sha(Path(prepared) / "MODELS.json")
                  and summary["model_sha256"] == digest(model), "identity", "Frozen model")
    audit.require(summary["rows_sha256"] == file_sha(output / "ROWS.json.gz")
                  and summary["data_sha256"] == file_sha(output / "DATA.npz"), "identity", "Rows/data")
    receipts, archive_files = _archive(summary["readbacks"], output, audit)
    members, prefix = owner_members(output / summary["owners"]["path"], summary["owners"], audit)
    locations = {str(identity): i for i, identity in enumerate(data["ids"])}
    seen, used, typed, sparse = set(), set(), 0, 0
    with Native(native_binary, native_receipt) as native:
        audit.require(native.receipt["binary_sha256"] == model["native_binary_sha256"], "identity", "Native executable")
        for row in rows:
            case, arm = row["case"], row["arm"]
            audit.require(case in locations and arm in ARMS and (case, arm) not in seen, "coverage", "Unique registered episode")
            seen.add((case, arm))
            i = locations[case]
            def read(kind, stage):
                key = (case, arm, kind, stage)
                used.add(key)
                return receipts[key]
            _, initial = read("delivery", "initial")
            _, sensor = read("observation", "sensor")
            terms = {key: read("observation", key)[1] for key in ("sensor_variance", "repair_cost", "wait_variance", "wait_cost")}
            residual_receipt, residual = read("delivery", "residual")
            audit.close(initial, float(data["initial_output"][i]), "readback", "Initial", exact=True)
            audit.close(sensor, float(data["self_evaluation"][i]), "readback", "Sensor", exact=True)
            audit.close(residual, sensor - initial, "readback", "Residual", exact=True)
            for name, value in terms.items():
                audit.close(value, float(data[name][i]), "readback", name, exact=True)
            public = {"initial": initial, "residuals": [residual], "variances": [terms.pop("sensor_variance")], **terms}
            levels, predecessor, owner_states = [0, 0], "0" * 64, []
            cost, expected_actions = 0.0, []
            for index, stage in enumerate(row["stages"]):
                if index:
                    _, sensor2 = read("observation", "wait_sensor")
                    residual_receipt, residual2 = read("delivery", "wait_residual")
                    audit.close(sensor2, float(data["wait_evaluation"][i]), "readback", "Paid sensor", exact=True)
                    audit.close(residual2, sensor2 - initial, "readback", "Paid residual", exact=True)
                    public = {**public, "residuals": [residual, residual2], "variances": [public["variances"][0], public["wait_variance"]]}
                audit.require(stage["public"] == public, "readback", "Only acquired public history")
                audit.require(residual_receipt["readback_ns"] <= stage["decision_ns"], "chronology", "Readback before choice")
                mean, variance = _conditional(model["calibration"], public)
                runtime, law = stage["runtime"], stage["law"]
                if arm in ("gaussian", "probit"):
                    audit.require(runtime is None, "runtime", "Direct baseline")
                    threshold = math.sqrt(public["repair_cost"])
                    expected_law = {"mean": mean, "variance": variance,
                        "probabilities": event_probs(mean, variance, -threshold, threshold).tolist()}
                else:
                    audit.close(runtime["source_forecast"], [mean, variance], "posterior", "Independent joint conditioning")
                    packet = runtime["packet"]
                    new_levels = [math.floor(mean / STEP + .5), math.floor(math.log(variance) / STEP + .5)]
                    audit.require(set(packet) == {"schema", "config_sha256", "sequence", "time", "observation_kind", "counts"}, "codec", "Integer packet schema")
                    audit.require(packet["counts"] == [new_levels[j] - levels[j] for j in range(2)]
                        and packet["sequence"] == index + 1 and packet["time"] == index + 1
                        and packet["observation_kind"] == "observed", "codec", "Independent count reconstruction")
                    levels = new_levels
                    decoded = [levels[0] * STEP, math.exp(levels[1] * STEP)]
                    threshold = math.sqrt(public["repair_cost"])
                    replay = native.typed(runtime["subject"], output / "audit_native" / runtime["subject"],
                        *decoded, -threshold, threshold,
                        expected_checkpoint=None if index == 0 else replay["checkpoint_after"])
                    typed += 1
                    for key in ("parameters_q24_decoded", "probabilities", "probabilities_q24"):
                        audit.close(runtime["native"]["head"][key], replay["head"][key], "typed_replay", key, exact=True)
                    audit.require(runtime["checkpoint_before"] == predecessor, "runtime", "Adapter predecessor")
                    predecessor = runtime["checkpoint_after"]
                    q = replay["head"]["parameters_q24_decoded"]
                    expected_law = {"mean": q[0], "variance": q[1],
                        "probabilities": [v / Q24 for v in replay["head"]["probabilities_q24"]]}
                    audit.require(runtime["law"] == law and runtime["decoder"]["levels"] == levels, "runtime", "Decoded law is policy law")
                    owner_states.append(runtime)
                for name in ("mean", "variance", "probabilities"):
                    audit.close(law[name], expected_law[name], "law", name)
                vector = None
                if arm in LEARNED:
                    precision = sum(1 / v for v in public["variances"])
                    residual_mean = sum(x / v for x, v in zip(public["residuals"], public["variances"])) / precision
                    raw = np.asarray([residual_mean, math.log(1 / precision), math.log(public["repair_cost"])])
                    z = (raw - model["calibration"]["public_center"]) / model["calibration"]["public_scale"]
                    if arm == "history":
                        vector = [float(np.prod(z ** p)) for p in POWERS]
                        vector.extend(np.exp(-.5 * np.sum((np.asarray(model["calibration"]["history_centers"]) - z) ** 2, axis=1)))
                    else:
                        p = law["probabilities"]
                        drives = np.tanh(z / 3) if arm == "numeric" else np.asarray([p[2] - p[0], 2 * p[1] - 1, math.tanh(z[2] / 3)])
                        if arm == "zero":
                            drives *= 0
                        vector = []
                        audit.require(len(stage["native"]) == 3, "sparse_replay", "Three matched-width channels")
                        for channel, drive in enumerate(drives):
                            count = int(round(float(drive) * Q24))
                            saved = stage["native"][channel]
                            actual = native.tick_pair(case + f"/stage{index}/channel{channel}", digest(public), count, reset_before_readout=arm == "reset")
                            audit.require(saved["drive_q24"] == count, "sparse_replay", "Actual encoded drive")
                            for a, b in zip(saved["ticks"], actual["ticks"]):
                                audit.require({k: v for k, v in a.items() if k != "native_ns"} == {k: v for k, v in b.items() if k != "native_ns"}, "sparse_replay", "Complete original tick")
                            tick = actual["ticks"][1]
                            vector.extend([1.0] + [v / Q24 for key in ("activation_q24", "eligibility_q24") for v in tick[key]])
                            sparse += 2
                    audit.close(stage["feature"], vector, "feature", "Independent native/history vector")
                else:
                    audit.require(stage["feature"] is None and not stage["native"], "feature", "Direct reference")
                amount = round(law["mean"] * Q24) / Q24
                repair_gain = 2 * amount * law["mean"] - amount * amount - public["repair_cost"]
                score = repair_gain if vector is None else float(np.dot(vector, model["heads"][arm]["weights"])) + model["heads"][arm]["offset"]
                scores = {"stop": 0.0, "repair": score}
                if index == 0:
                    scores["wait"] = _wait(law["mean"], law["variance"], public["repair_cost"],
                        model["calibration"]["noise_scale"] * public["wait_variance"], public["wait_cost"])
                for name, value in scores.items():
                    audit.close(stage["scores"][name], value, "value", name)
                expected_action = max(scores, key=scores.get)
                audit.require(stage["action"] == expected_action, "choice", "Frozen expected utility choice")
                expected_actions.append(expected_action)
                cost += public["wait_cost"] if expected_action == "wait" else public["repair_cost"] if expected_action == "repair" else 0
            audit.require(len(row["stages"]) == (2 if row["actions"][0] == "wait" else 1), "choice", "One paid wait opportunity")
            audit.require(row["actions"] == expected_actions, "choice", "Action sequence")
            if owner_states:
                stem = prefix + owner_states[0]["subject"] + "/"
                state_envelope = json.loads(members[stem + "state.json"])
                state = state_envelope["document"]
                witness_envelope = json.loads(members[stem + "delivery.witness.json"])
                witness = witness_envelope["document"]
                audit.require(digest(state) == state_envelope["sha256"] == witness["records"][-1]["state_sha256"]
                    and digest(witness) == witness_envelope["sha256"] and state["receipts"] == owner_states, "runtime", "Durable state and witness bind policy law")
            final_receipt, delivered = read("delivery", "final")
            audit.close(delivered, initial + (amount if expected_actions[-1] == "repair" else 0), "delivery", "Actual output", exact=True)
            target = float(data["target"][i])
            for name, value in (("target", target), ("delivered", delivered), ("cost", cost),
                                ("squared_error", (delivered - target) ** 2), ("utility", 1 - (delivered - target) ** 2 - cost)):
                audit.close(row[name], value, "scoring", name, exact=True)
            audit.require(row["stages"][-1]["decision_ns"] <= final_receipt["began_ns"] <= final_receipt["readback_ns"]
                          <= row["final_readback_ns"] < row["score_started_ns"], "chronology", "Delivery before scoring")
        audit.require(used == set(receipts) and len(seen) == len(data["ids"]) * len(ARMS), "coverage", "All artifacts and trajectories")
        audit.require(typed + sparse == summary["native_ticks"] == native.original_sparse_ticks, "coverage", "Every original native tick replayed")
        replay_cost = {"native_requests": native.calls, "native_ticks": native.original_sparse_ticks, "native_roundtrip_ns": native.wall_ns}
    for arm in ARMS:
        subset = [r for r in rows if r["arm"] == arm]
        for key in ("utility", "squared_error", "cost", "wall_ns"):
            audit.close(summary["summary"][arm][key], float(np.mean([r[key] for r in subset])), "summary", arm + key)
    report = {"passed": True, "checks": audit.counts, "episodes": len(rows), "unique_trajectories": len(data["ids"]),
        "dataset_split": data["split"],
        "typed_ticks_replayed": typed, "sparse_ticks_replayed": sparse, "readback_archive_files": archive_files,
        "runtime_owner_files": len(members), "replay_cost": replay_cost,
        "native_replay_archive": archive_directory(output / "audit_native"),
        "wall_ns": time.perf_counter_ns() - began, "source_sha256": file_sha(__file__),
        "private_target_process_access_control_claimed": False,
        "scope": "All readbacks, count packets, typed heads and original sparse ticks, durable witnesses, actions and scores"}
    write_json(output / "AUDIT.json", report)
    return report
