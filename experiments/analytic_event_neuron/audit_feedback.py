"""Independent audit of archived original-Hepta two-tick feedback evidence."""

from collections import defaultdict
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import struct
import tarfile
import time

import numpy as np
from scipy.special import expit

from .analytic import event_probs
from .evidence_audit import _Audit, _png_value, _sha

ARMS = ("numeric", "analytic_probability", "zero", "state_reset", "matched_history")
Q24 = 1 << 24


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                     separators=(",", ":")).encode()).hexdigest()


def _archive(metadata, root, audit):
    path = Path(root) / Path(metadata["archive_path"]).name
    audit.require(_sha(path) == metadata["archive_sha256"], "archive", "Compressed archive digest")
    audit.require(path.stat().st_size == metadata["archive_bytes"], "archive", "Compressed archive size")
    members = {}
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            parsed = PurePosixPath(member.name)
            audit.require(not parsed.is_absolute() and ".." not in parsed.parts,
                          "archive", "Safe member name")
            if member.isdir():
                continue
            audit.require(member.isfile() and member.name not in members,
                          "archive", "Unique regular member")
            with archive.extractfile(member) as stream:
                members[member.name] = stream.read()
            audit.require(len(members[member.name]) == member.size, "archive", member.name)
    manifest_name = metadata["manifest_member"]
    manifest_bytes = members[manifest_name]
    audit.require(hashlib.sha256(manifest_bytes).hexdigest() == metadata["manifest_sha256"],
                  "archive", "Manifest digest")
    manifest = json.loads(manifest_bytes)
    prefix = str(PurePosixPath(manifest_name).parent) + "/"
    expected = {prefix + name for name in manifest["files"]} | {manifest_name}
    audit.require(set(members) == expected, "archive", "Complete archive inventory")
    for name, expected in manifest["files"].items():
        content = members[prefix + name]
        audit.require(len(content) == expected["bytes"] and hashlib.sha256(content).hexdigest() == expected["sha256"],
                      "artifact_hash", name)
    audit.require(metadata["all_file_sha256_verified_before_removal"] is True
                  and metadata["verified_archive_files"] == len(members), "archive", "Producer archive verification")
    receipt_bytes = members[metadata["receipt_member"]]
    audit.require(hashlib.sha256(receipt_bytes).hexdigest() == metadata["receipt_sha256"],
                  "archive", "Receipt digest")
    receipts, referenced = {}, {manifest_name, metadata["receipt_member"]}
    observations = deliveries = 0
    for line in receipt_bytes.decode().splitlines():
        row = json.loads(line)
        key = (row["case"], row["arm"], row["kind"], row["stage"])
        audit.require(key not in receipts and row["private_target_supplied"] is False,
                      "receipt", str(key))
        audit.require(0 < row["began_ns"] <= row["written_ns"] <= row["readback_ns"],
                      "chronology", str(key))
        if row["kind"] == "observation":
            observations += 1
            content = members[prefix + row["path"]]
            referenced.add(prefix + row["path"])
            audit.require(hashlib.sha256(content).hexdigest() == row["sha256"], "artifact_hash", str(key))
            payload = json.loads(content)
            audit.require(payload["schema"] == "hepta.analytic-event.public-observation.v1", "receipt", str(key))
            value = float(payload["value"])
        else:
            deliveries += 1
            audit.require(row["kind"] == "delivery", "receipt", str(key))
            text, png = members[prefix + row["text_path"]], members[prefix + row["image_path"]]
            referenced.update((prefix + row["text_path"], prefix + row["image_path"]))
            audit.require(hashlib.sha256(text).hexdigest() == row["text_sha256"]
                          and hashlib.sha256(png).hexdigest() == row["image_sha256"], "artifact_hash", str(key))
            value = _png_value(io.BytesIO(png))
            audit.require(struct.pack(">d", float(text)) == struct.pack(">d", value)
                          == struct.pack(">d", row["prediction"]), "png_bit_replay", str(key))
        receipts[key] = (row, value)
    audit.require(referenced == set(members), "coverage", "Every archived file is referenced")
    audit.require(observations == metadata["observations"] and deliveries == metadata["deliveries"]
                  and observations + 2 * deliveries == metadata["files"], "coverage", "Transport file counters")
    return receipts, len(members)


def _feature(row, arm, feedback, digest, calibration, native, audit):
    if arm == "matched_history":
        audit.require(row["native"] is None, "native", "History arm does not claim native state")
        z = feedback / calibration["history_scale"]
        radial = np.exp(-2.0 * (z - np.asarray(calibration["history_centers"]))**2)
        return np.concatenate(([1.0, z, z * z, z * z * z], radial))
    if arm == "zero":
        drive = 0.0
    elif arm == "numeric":
        drive = float(np.clip(feedback / calibration["numeric_scale"], -1.0, 1.0))
    else:
        probabilities = event_probs(calibration["kappa"] * feedback, calibration["conditional_variance"], 0.0, 0.0)
        drive = float(probabilities[2] - probabilities[0])
    quantized = int(round(drive * Q24))
    saved = row["native"]
    audit.close(saved["evidence_drive"], drive, "encoding", row["case"])
    audit.require(saved["feedback_q24"] == quantized and saved["readback_digest"] == digest,
                  "encoding", row["case"] + " identity")
    actual = native.tick_pair(row["case"], digest, quantized, reset_before_readout=arm == "state_reset")
    audit.require(saved["original_sparse_tick_calls"] == actual["original_sparse_tick_calls"] == 2
                  and len(saved["ticks"]) == len(actual["ticks"]) == 2, "native", "Two original ticks")
    for recorded, replayed in zip(saved["ticks"], actual["ticks"]):
        a = {key: value for key, value in recorded.items() if key != "native_ns"}
        b = {key: value for key, value in replayed.items() if key != "native_ns"}
        audit.require(a == b, "native_replay", row["case"] + "/" + arm)
        audit.require(recorded["authority"] == "DENY_ALL" and recorded["requires_calibration"] is True,
                      "native", "Non-authorizing original receipt")
    audit.require(saved["checkpoint_reset_intervention"] == (arm == "state_reset")
                  and saved["ticks"][1]["drive_q24"] == [0] * 10, "native", "No fresh readout drive")
    audit.require(row["feedback_readback_ns"] <= saved["started_ns"] <= saved["completed_ns"]
                  <= row["decision_ns"], "chronology", "Native state precedes decision")
    final = actual["ticks"][1]
    return np.array([1.0] + [x / Q24 for field in ("activation_q24", "eligibility_q24") for x in final[field]])


def audit_feedback_evaluation(result_dict, data, models, native, artifact_root):
    """Reopen all archives and rerun the actual two-tick kernel for every row."""
    began, audit = time.perf_counter_ns(), _Audit()
    result = {"schema": "hepta.analytic-event.feedback-audit.v1", "audit_source_sha256": _sha(__file__),
              "offline_replay": True, "chronology_scope": "Retained artifact chronology; not process-memory isolation proof"}
    try:
        model_digest = _digest(models)
        dataset_digest = _digest({key: value.tolist() if isinstance(value, np.ndarray) else value
                                  for key, value in data.items()})
        audit.require(result_dict["dataset_sha256"] == dataset_digest, "dataset_hash", "Evaluation dataset")
        audit.require(result_dict["model_sha256"] == model_digest, "model_hash", "Model identity")
        audit.require(models["native_binary_sha256"] == native.receipt["binary_sha256"] == _sha(native.binary),
                      "model_hash", "Executed native binary")
        audit.require(set(models["heads"]) == set(ARMS) and models["calibration"]["source"] == "training_only",
                      "model_hash", "Registered heads and calibration source")
        receipts, files = _archive(result_dict["archive"], artifact_root, audit)
        positions = {str(identity): i for i, identity in enumerate(data["ids"])}
        audit.require(len(positions) == len(data["ids"]), "dataset_hash", "Unique environment identities")
        calibration, seen, used, groups = models["calibration"], set(), set(), defaultdict(dict)
        for row in result_dict["rows"]:
            case, arm = row["case"], row["arm"]
            index, identity = positions[case], (case, arm)
            audit.require(arm in ARMS and identity not in seen, "coverage", str(identity))
            seen.add(identity)

            def receipt(kind, stage):
                key = (case, arm, kind, stage)
                used.add(key)
                return receipts[key]

            initial_receipt, initial = receipt("delivery", "initial")
            observed_receipt, observation = receipt("observation", "self_evaluation")
            feedback_receipt, feedback = receipt("delivery", "feedback")
            final_receipt, delivered = receipt("delivery", "final")
            audit.close(initial, data["initial_output"][index], "readback", str(identity) + " draft", exact=True)
            audit.close(observation, data["self_evaluation"][index], "readback", str(identity) + " sensor", exact=True)
            audit.close(feedback, observation - initial, "readback", str(identity) + " residual", exact=True)
            for field, expected in (("initial_readback", initial), ("self_evaluation_readback", observation),
                                    ("feedback_readback", feedback), ("delivered_prediction", delivered)):
                audit.close(row[field], expected, "readback", str(identity) + "/" + field, exact=True)
            for field in ("text_path", "image_path", "text_sha256", "image_sha256"):
                audit.require(row["feedback_" + field] == feedback_receipt[field], "readback", str(identity) + field)
            readback_digest = _digest({key: feedback_receipt[key] for key in ("text_sha256", "image_sha256")})
            audit.require(row["readback_digest"] == readback_digest and row["model_sha256"] == model_digest,
                          "model_hash", str(identity))
            timeline = [initial_receipt["readback_ns"], row["initial_readback_ns"], observed_receipt["began_ns"],
                        observed_receipt["readback_ns"], row["self_evaluation_readback_ns"], feedback_receipt["began_ns"],
                        feedback_receipt["readback_ns"], row["feedback_readback_ns"], row["decision_ns"],
                        final_receipt["began_ns"], final_receipt["readback_ns"], row["final_readback_ns"], row["score_started_ns"]]
            audit.require(all(a <= b for a, b in zip(timeline, timeline[1:])), "chronology", str(identity))
            feature = _feature(row, arm, feedback, readback_digest, calibration, native, audit)
            audit.close(row["head_features"], feature, "feature_replay", str(identity))
            audit.require(feature.shape == (21,), "feature_replay", "Twenty-one head coefficients")
            head = models["heads"][arm]
            score = float(feature @ np.asarray(head["weights"]))
            probability = float(expit(score))
            threshold = head["threshold"]
            repair = True if threshold == 0 else False if threshold == 1 else probability >= threshold
            action = "repair" if repair else "stop"
            for field, expected in (("head_score", score), ("head_probability", probability), ("head_threshold", threshold)):
                audit.close(row[field], expected, "head_replay", str(identity) + "/" + field)
            audit.require(row["action"] == final_receipt["action"] == action, "action", str(identity))
            audit.require(initial_receipt["action"] == "preview" and feedback_receipt["action"] == "self_evaluation_residual",
                          "action", str(identity) + " transport actions")
            proposal = initial + (calibration["kappa"] * feedback if repair else 0.0)
            audit.close(row["proposed_final_prediction"], proposal, "delivery", str(identity))
            audit.close(delivered, proposal, "delivery", str(identity) + " artifact", exact=True)
            target, cost = data["target"][index], 0.12 if repair else 0.0
            square = (delivered - target)**2
            gain = (initial - target)**2 - (initial + calibration["kappa"] * feedback - target)**2 - 0.12
            for field, expected in (("terminal_target", target), ("paid_cost", cost), ("squared_error", square),
                                    ("utility", 1 - square - cost), ("repair_improvement_if_taken", gain)):
                audit.close(row[field], expected, "score", str(identity) + "/" + field)
            audit.require(row["profitable_choice"] == bool(repair == (gain > 0)) and row["actual_transport"] is True,
                          "score", str(identity) + " flags")
            groups[arm][case] = row
        audit.require(len(seen) == len(ARMS) * len(positions) and used == set(receipts),
                      "coverage", "All trajectories, arms, and receipts")
        for arm, cases in groups.items():
            rows = list(cases.values())
            expected = {"trajectories": len(rows), "mean_utility": np.mean([r["utility"] for r in rows]),
                        "mean_squared_error": np.mean([r["squared_error"] for r in rows]),
                        "mean_action_cost": np.mean([r["paid_cost"] for r in rows]),
                        "repair_count": sum(r["action"] == "repair" for r in rows),
                        "severe_loss_fraction": np.mean([r["utility"] < -2 for r in rows]),
                        "profitable_choice_fraction": np.mean([r["profitable_choice"] for r in rows]),
                        "native_ticks": 0 if arm == "matched_history" else 2 * len(rows),
                        "wall_ns": sum(r["elapsed_ns"] for r in rows), "cpu_ns": sum(r["cpu_ns"] for r in rows),
                        "action_disagreements_with_numeric": sum(r["action"] != groups["numeric"][case]["action"] for case, r in cases.items())}
            if arm != "matched_history":
                expected["state_value_disagreements_with_numeric"] = sum(
                    r["head_features"] != groups["numeric"][case]["head_features"] for case, r in cases.items())
            else:
                audit.require(result_dict["summary"][arm]["state_value_disagreements_with_numeric"] is None,
                              "summary", "History has no native state comparison")
            for field, value in expected.items():
                audit.close(result_dict["summary"][arm][field], value, "summary", arm + "/" + field)
        result.update(passed=True, trajectories=len(positions), control_rows=len(seen),
                      archived_files=files, transport_receipts=len(receipts),
                      original_native_ticks_replayed=2 * 4 * len(positions), model_sha256=model_digest,
                      dataset_sha256=dataset_digest)
    except (AssertionError, ValueError, KeyError, OSError, TypeError, IndexError, tarfile.TarError) as error:
        result.update(passed=False, error=f"{type(error).__name__}: {error}")
    result.update(checks=dict(audit.counts), maximum_absolute_numeric_error=audit.maximum_absolute_error,
                  audit_elapsed_ns=time.perf_counter_ns() - began)
    return result
