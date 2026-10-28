"""Read original artifacts, independently decode PNGs, replay native operators."""

import base64
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import struct
import time
import zipfile

import numpy as np
from PIL import Image
from scipy.special import logsumexp

from ..native_adapter import Native
from ..round3 import feedback as previous
from ..runtime import digest
from .runtime_codec import Decoder, levels
from .runtime_evidence import EvidenceZip, write_json
from .runtime_law import action_values, make_law
from .runtime_learning import ARMS, LEARNED
from .runtime_owner import Owner, ZERO, file_sha
from .runtime_study import _native_paths, load_data


def _png(payload):
    with Image.open(io.BytesIO(payload)) as image:
        if image.format != "PNG" or image.mode != "L" or image.size != (256, 32):
            raise ValueError("Unexpected numeric PNG")
        pixels = np.asarray(image)
    bits = []
    for index in range(64):
        top, bottom = pixels[:16, index * 4:(index + 1) * 4], pixels[16:, index * 4:(index + 1) * 4]
        bit = int(top[0, 0])
        if bit not in (0, 255) or not np.all(top == bit) or not np.all(bottom == 255 - bit):
            raise ValueError("Corrupt numeric PNG bit")
        bits.append(bit // 255)
    return struct.unpack(">d", np.packbits(np.asarray(bits, dtype=np.uint8)).tobytes())[0]


def independent_posterior(model, public, arm):
    prior = model["gaussian_prior"] if arm in ("gaussian", "probit") else model["prior"]
    y = np.asarray(public["residuals"])
    noise = np.asarray(public["variances"]) * model["calibration"]["noise_scale"]
    means, variances, logs = [], [], []
    for weight, mean, variance in zip(prior["weights"], prior["means"], prior["variances"]):
        covariance = np.diag(noise) + variance
        regression = np.linalg.solve(covariance, np.full(len(y), variance))
        residual = y - mean
        logdet = np.linalg.slogdet(covariance)[1]
        logs.append(math.log(weight) - .5 * (len(y) * math.log(2 * math.pi) + logdet + residual @ np.linalg.solve(covariance, residual)))
        means.append(float(mean + regression @ residual))
        variances.append(float(variance - variance * regression.sum()))
    return make_law(np.exp(logs - logsumexp(logs)), means, variances)


def audit(run_dir, seed, *, development_only=False):
    from .freeze import verify
    if not development_only:
        verify(run_dir)
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    output = Path(run_dir) / "runtime_confirmation" / f"seed_{seed}"
    prepared = Path(run_dir) / "runtime_prepared" / f"seed_{seed}"
    summary = json.loads((output / "SUMMARY.json").read_text())
    model = json.loads((prepared / "MODELS.json").read_text())
    data = load_data(output / "DATA.npz")
    with gzip.open(output / "ROWS.json.gz", "rt") as stream:
        rows = json.load(stream)
    checks = 0
    def require(condition, message):
        nonlocal checks
        checks += 1
        if not condition:
            raise AssertionError(message)
    require(file_sha(prepared / "MODELS.json") == summary["model_file_sha256"], "Frozen model binding")
    require(file_sha(output / "DATA.npz") == summary["data_sha256"], "Confirmation data binding")
    require(file_sha(output / "ROWS.json.gz") == summary["rows_sha256"], "Scored row binding")
    metadata = summary["worker"]["archive"]
    archive_path = output / metadata["path"]
    require(file_sha(archive_path) == metadata["sha256"], "Execution archive identity")
    entries = json.loads(archive_path.with_suffix(".manifest.json").read_text())["files"]
    replay_archive = EvidenceZip(output / "native_replay.zip")
    indexes = {str(identity): i for i, identity in enumerate(data["ids"])}
    seen, png_count, max_posterior_error = set(), 0, 0.0
    with zipfile.ZipFile(archive_path) as archive, Native(*_native_paths(run_dir)) as native:
        require(set(archive.namelist()) == set(entries) and len(archive.namelist()) == len(entries), "Full archive inventory")
        for name, entry in entries.items():
            require(not name.startswith("/") and ".." not in Path(name).parts, "Safe archive path")
            payload = archive.read(name)
            require({"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()} == entry, "Original artifact bytes")
        for row in rows:
            case, arm = row["case"], row["arm"]
            require(case in indexes and arm in ARMS and (case, arm) not in seen, "Unique registered control execution")
            seen.add((case, arm))
            i = indexes[case]
            prefix = f"case-{i}/{arm}/"
            receipts = [json.loads(line) for line in archive.read(prefix + "readbacks/TRANSPORT_RECEIPTS.jsonl").splitlines()]
            values, transport_receipts = {}, {}
            for item in receipts:
                require(item["case"] == case and item["arm"] == arm and item["private_target_supplied"] is False, "Public transport identity")
                key = (item["kind"], item["stage"])
                require(key not in values, "Unique transport stage")
                if item["kind"] == "observation":
                    value = json.loads(archive.read(prefix + "readbacks/" + item["path"]))["value"]
                else:
                    value = _png(archive.read(prefix + "readbacks/" + item["image_path"]))
                    text_value = float(archive.read(prefix + "readbacks/" + item["text_path"]))
                    require(struct.pack(">d", value) == struct.pack(">d", text_value), "Independent text/PNG decode")
                    png_count += 1
                values[key], transport_receipts[key] = value, item
            initial = values["delivery", "initial"]
            require(initial == float(data["initial_output"][i]), "Actual initial output")
            require(values["observation", "sensor"] == float(data["self_evaluation"][i]), "Acquired sensor")
            public = {"initial": initial, "residuals": [values["delivery", "residual"]],
                      "variances": [values["observation", "sensor_variance"]],
                      **{k: values["observation", k] for k in ("repair_cost", "wait_cost", "wait_variance")}}
            require(public["residuals"][0] == values["observation", "sensor"] - initial, "Residual actual subtraction")
            mode = arm if arm in ("event", "direct", "float") else "float" if arm in ("gaussian", "probit") else "event"
            directory = output / "replay_working"
            owner = Owner(directory, [case, arm], digest(model), native, mode)
            checkpoint, actual_actions, cost, previous_original = ZERO, [], 0.0, ZERO
            for stage_index, stage in enumerate(row["stages"]):
                if stage_index:
                    require(actual_actions[-1] == "wait", "Paid observation only follows wait")
                    public = {**public, "residuals": [*public["residuals"], values["delivery", "wait_residual"]],
                              "variances": [*public["variances"], public["wait_variance"]]}
                    require(values["observation", "wait_sensor"] == float(data["wait_evaluation"][i]), "Actual second sensor")
                    require(public["residuals"][-1] == values["observation", "wait_sensor"] - initial, "Actual second residual")
                saved = stage["runtime"]
                require(stage["public"] == public == saved["public"], "Only acquired public evidence")
                independent = independent_posterior(model, public, arm)
                for key in ("weights", "means", "variances"):
                    error = float(np.max(np.abs(np.asarray(independent[key]) - saved["source_law"][key])))
                    max_posterior_error = max(max_posterior_error, error)
                    require(error < 2e-13, "Independent dense-mixture conditioning")
                packet = archive.read(prefix + f"owners/{saved['subject']}/packet-{stage_index + 1}.bin")
                require(packet == base64.b64decode(saved["packet_base64"]), "Original reopened wire bytes")
                require(saved["checkpoint_before"] == previous_original, "Original adapter ancestry")
                previous_original = saved["checkpoint_after"]
                replay = owner.step(public, saved["source_law"], stage_index + 1, expected_checkpoint=checkpoint)
                checkpoint = replay["checkpoint_after"]
                require(saved["decoder"] == replay["decoder"] and saved["law"] == replay["law"], "Actual native released law replay")
                require(saved["packet_base64"] == replay["packet_base64"], "Exact codec replay")
                for original, fresh in zip(saved["native"], replay["native"]):
                    for key in ("parameters_q24_decoded", "probabilities", "probabilities_q24"):
                        require(original["head"][key] == fresh["head"][key], "Every native CDF/Q24 replay")
                    require(fresh["original_neuron_runtime"] and fresh["abstain"] and fresh["legacy_runtime_confidence_ppm"] == 0, "Original native authority unchanged")
                law = replay["law"]
                expected_values = action_values(law["conditional_law"], public, model["calibration"]["noise_scale"])
                require(expected_values == stage["values"], "Frozen continuation/action values")
                vector, feature_rows = previous.feature(public, law, arm, model["calibration"], native, case + f"/stage{stage_index}/{arm}") if arm in LEARNED else (None, [])
                require((None if vector is None else vector.tolist()) == stage["feature"], "Every learned input replay")
                for a, b in zip(stage["native"], feature_rows):
                    for left, right in zip(a["ticks"], b["ticks"]):
                        require({k: v for k, v in left.items() if k != "native_ns"} == {k: v for k, v in right.items() if k != "native_ns"}, "Every original sparse tick replay")
                repair = expected_values["repair_gain"] if vector is None else float(np.dot(vector, model["heads"][arm]["weights"])) + model["heads"][arm]["offset"]
                scores = {"stop": 0.0, "repair": repair}
                if stage_index == 0:
                    scores["wait"] = expected_values["wait_gain"]
                require(scores == stage["scores"], "Actual choice scores")
                choice = max(scores, key=scores.get)
                require(choice == stage["action"], "Actual downstream choice")
                actual_actions.append(choice)
                cost += public["wait_cost"] if choice == "wait" else public["repair_cost"] if choice == "repair" else 0
            envelope = json.loads(archive.read(prefix + f"owners/{saved['subject']}/state.json"))
            witness = json.loads(archive.read(prefix + f"owners/{saved['subject']}/witness.json"))
            require(envelope["sha256"] == digest(envelope["document"]) == witness["document"]["records"][-1]["state_sha256"], "Actual durable state/witness")
            require(witness["sha256"] == digest(witness["document"]), "Witness envelope")
            require(envelope["document"]["receipts"] == [s["runtime"] for s in row["stages"]], "All policy states preserved")
            delivered = values["delivery", "final"]
            target = float(data["target"][i])
            require(delivered == initial + (expected_values["repair_amount"] if choice == "repair" else 0), "Final actual output")
            require(actual_actions == row["actions"] and cost == row["cost"], "All paid actions/costs")
            require(row["delivered"] == delivered and row["target"] == target and row["squared_error"] == (delivered - target) ** 2 and row["utility"] == 1 - (delivered - target) ** 2 - cost, "Final scorer independent target")
            require(row["stages"][-1]["decision_ns"] <= transport_receipts["delivery", "final"]["began_ns"] <= row["final_readback_ns"] < row["score_started_ns"], "Delivery precedes private scoring")
            replay_archive.append(directory, prefix.rstrip("/"))
        require(len(seen) == len(data["ids"]) * len(ARMS), "All registered executions")
        require(native.original_sparse_ticks == summary["worker"]["native"]["ticks"], "Every native tick replayed exactly once")
        replay_cost = {"requests": native.calls, "ticks": native.original_sparse_ticks, "roundtrip_ns": native.wall_ns}
    report = {"passed": True, "seed": seed, "checks": checks, "independent_png_readbacks": png_count,
              "archive_members_verified": len(entries), "native_replay": replay_cost,
              "independent_dense_posterior_max_absolute_error": max_posterior_error,
              "replay_archive": replay_archive.finish(), "source_archive_sha256": file_sha(archive_path),
              "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
              "development_only": development_only}
    write_json(output / "AUDIT.json", report)
    if not development_only:
        verify(run_dir)
    return report
