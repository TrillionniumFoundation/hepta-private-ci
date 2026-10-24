"""Preregistered persistence calibration; no optimizer or authority is issued.

This tests a hypothesis: latent state change may predict joint output success.
Its score is not inherently semantic confidence. OOD means only the declared
complete-visual-evidence-absence transformation, not arbitrary semantic novelty.
"""

import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import struct
import sys
import time

SPEC_SHA256 = "7472ac00a31a032d164101eb9e691622bdf3b52d5400b9f4ca525a32396c3e49"
OWNER_SOURCE_SHA256 = "9bf09b8f4358f7067548f813ba34100605bc0e0e481d066777befa21093f103a"
COMPLETED_SUMMARY_SHA256 = "baa995a3a6ad66d2376d4bd5e18e3f38c91255ebf41f6a5a88f6a6de131cd28a"
PROJECTION = b"hepta.ndu-v6.four-state-tanh-persistence.q24.v1\0hidden=96;blocks=h,image,text,context;f64-left-sum/4;tanh;round-away;q=16777216;raw-range=-8,8"
Q24, PPM = 1 << 24, 1_000_000
ACTIONS = ("refine_semantic", "refine_image", "refine_text", "couple")


def sha(value):
    return hashlib.sha256(value).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def completed_registration(experiment, expected_summary=COMPLETED_SUMMARY_SHA256):
    """Read only custody metadata from completed reports; never select by quality."""
    status = json.loads((experiment / "status.json").read_bytes())
    summary = json.loads((experiment / "summary.json").read_bytes())
    protocol = json.loads((experiment / "protocol.json").read_bytes())
    if (status.get("state") != "completed" or status.get("rows") != 7560
            or status.get("summary_sha256") != expected_summary or sha(canonical(summary)) != expected_summary
            or sha(canonical(protocol)) != summary["protocol_sha256"]
            or protocol["source"] != summary["source"] or protocol["source"]["dirty"]
            or protocol["source"]["git_commit"] != "b98961ceb71414490e1c6ae397cf635bca3093f4"
            or protocol["seeds"][0] != 17 or protocol["study_id"] != "conditioned-heteroskedastic-002"):
        raise ValueError("Not the preregistered completed full-002 source and protocol")
    model = summary["checkpoint_files"]["seed-17-terminal_entropic_ndu"]["snapshot_file_sha256"]
    reward = summary["observer_binding"]["reward_artifact_sha256"]
    if (sha((experiment / "seed-17-terminal_entropic_ndu.pt").read_bytes()) != model
            or sha((experiment / "reward-observer.pt").read_bytes()) != reward
            or reward != summary["observer"]["weights_sha256"]["reward"]):
        raise ValueError("Selected original model or Reward A bytes changed")
    return {"completed_summary_sha256": expected_summary, "protocol_sha256": summary["protocol_sha256"],
            "model_file_sha256": model, "reward_file_sha256": reward,
            "dataset_manifest_sha256": protocol["dataset_manifest"]["manifest_sha256"],
            "source": protocol["source"]}


def project(values):
    """Full four-block float32 state -> declared 96-dimensional Q24 feature."""
    if not isinstance(values, list) or len(values) != 384:
        raise ValueError("Projection requires all four 96-dimensional state blocks")
    if any(type(v) is not int or not 0 <= v <= 0xffffffff for v in values):
        raise ValueError("Float32 bit patterns must be unsigned integers")
    raw = [struct.unpack("<f", struct.pack("<I", value))[0] for value in values]
    if any(not math.isfinite(v) or not -8 <= v <= 8 for v in raw):
        raise ValueError("Unbounded raw state; projection never clips it")
    result = []
    for i in range(96):
        value = math.tanh(((raw[i] + raw[i + 96]) + raw[i + 192] + raw[i + 288]) / 4) * Q24
        result.append(math.floor(value + .5) if value >= 0 else math.ceil(value - .5))
    return result


def scores(previous, current):
    prediction, drive = project(previous), project(current)
    error = max(abs(a - b) for a, b in zip(drive, prediction))
    return {"prediction_q24": prediction, "drive_q24": drive, "error_q24": error,
            "confidence_ppm": PPM - min(PPM, error * PPM // (2 * Q24)),
            "ood_ppm": min(PPM, error * PPM // Q24)}


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def _wilson(successes, count):
    if not count:
        return None
    p, z = successes / count, 1.959963984540054
    denominator = 1 + z * z / count
    centre = (p + z * z / (2 * count)) / denominator
    radius = z * math.sqrt(p * (1 - p) / count + z * z / (4 * count * count)) / denominator
    return [max(0., centre - radius), min(1., centre + radius)]


def metrics(rows):
    if not rows:
        raise ValueError("Empty calibration cohort")
    bins = [[0, 0, 0] for _ in range(10)]
    accepted = bad = accepted_bad = ood = false_ood = successes = 0
    for row in rows:
        confidence, score, success = row["confidence_ppm"], row["ood_ppm"], row["joint_success"]
        if type(confidence) is not int or not 0 <= confidence <= PPM or type(score) is not int or not 0 <= score <= PPM:
            raise ValueError("Invalid integer confidence/OOD score")
        if type(success) is not bool or type(row["predeclared_ood"]) is not bool:
            raise ValueError("Calibration labels must be explicit booleans")
        bucket = bins[min(9, confidence * 10 // (PPM + 1))]
        bucket[0] += 1
        bucket[1] += confidence
        bucket[2] += int(success)
        admit = confidence >= 750_000 and score <= 500_000
        accepted += admit
        bad += not success
        accepted_bad += admit and not success
        successes += success
        ood += row["predeclared_ood"]
        false_ood += row["predeclared_ood"] and score <= 500_000
    if not ood:
        raise ValueError("Native OOD FAR requires a nonempty predeclared OOD cohort")
    ece_numerator = sum(abs(confidence_sum - PPM * label_sum) for _, confidence_sum, label_sum in bins)
    return {"pairs": len(rows), "ood_pairs": ood, "ood_false_accepts": false_ood,
            "ece_ppm": (ece_numerator + len(rows) - 1) // len(rows),
            "ood_false_acceptance_ppm": (false_ood * PPM + ood - 1) // ood,
            "ood_far_wilson_95_descriptive": _wilson(false_ood, ood),
            "joint_success_rate": successes / len(rows), "coverage": accepted / len(rows),
            "semantic_false_acceptance_among_incorrect": _ratio(accepted_bad, bad),
            "semantic_error_among_accepted": _ratio(accepted_bad, accepted),
            "ece_bins_count_confidence_sum_successes": bins}


def summarize(rows):
    """Validate one independent pair per prespecified slot, then report failures."""
    if len(rows) != 128 or {r["pair_index"] for r in rows} != set(range(640, 768)):
        raise ValueError("Missing or duplicate independent pair")
    identities, pixels = set(), set()
    for row in rows:
        index = row["pair_index"]
        ordinal = (index - 640) % 64
        cohort = "calibration" if index < 704 else "verification"
        if row["cohort"] != cohort or row["action"] != ACTIONS[ordinal % 4] or row["predeclared_ood"] != (ordinal >= 32):
            raise ValueError("Preregistered cohort/action/OOD assignment changed")
        if row["row_sha256"] != sha(canonical({k: v for k, v in row.items() if k != "row_sha256"})):
            raise ValueError("Calibration row custody mismatch")
        for field, seen in (("source_ids", identities), ("pixel_hashes", pixels)):
            values = row[field]
            if len(values) != 2 or len(set(values)) != 2 or any(v in seen for v in values):
                raise ValueError("Source pair or pixel identity reused")
            seen.update(values)
        if any(row[key] != value for key, value in scores(row["previous_state"]["values_f32"], row["current_state"]["values_f32"]).items()):
            raise ValueError("Reported scores do not follow actual recorded state")
        measured = row["metrics"]
        success = measured["caption_valid"] and all(measured[key] == 0 for key in ("text_fact", "relation", "image_fact", "crossmodal_disagreement"))
        if type(row["joint_success"]) is not bool or row["joint_success"] != success:
            raise ValueError("Joint-success label differs from frozen Reward A metric")
    cohorts = {name: metrics([r for r in rows if r["cohort"] == name]) for name in ("calibration", "verification")}
    ece = max(value["ece_ppm"] for value in cohorts.values())
    far = max(value["ood_false_acceptance_ppm"] for value in cohorts.values())
    return {"schema": "hepta.ndu-v6.neuron-calibration-report.v1", "specification_sha256": SPEC_SHA256,
            "projection_sha256": sha(PROJECTION), "cohorts": cohorts,
            "native_measured_ece_ppm": ece, "native_measured_false_acceptance_ppm": far,
            "maximum_ece_ppm": 30_000, "maximum_false_acceptance_ppm": 4_999,
            "point_gates_passed": ece <= 30_000 and far <= 4_999,
            "stratum_counts": {f"{cohort}/{action}/{domain}": sum(
                r["cohort"] == cohort and r["action"] == action and r["predeclared_ood"] == (domain == "ood") for r in rows)
                for cohort in cohorts for action in ACTIONS for domain in ("id", "ood")},
            "row_set_sha256": sha(canonical([r["row_sha256"] for r in sorted(rows, key=lambda r: r["pair_index"])])),
            "claim": "bounded synthetic OOD/Reward-A pilot; no confidence guarantee, independent evaluator authentication, production qualification or daemon activation",
            "authority": "deny_all"}


def run(experiment, cache, specification, output):
    """One frozen model/observer, no fitting, no Audit B or formal rollout input."""
    if sha(specification.read_bytes()) != SPEC_SHA256:
        raise ValueError("Preregistration byte identity changed")
    output.mkdir(parents=True, exist_ok=False)

    def write(name, value):
        with (output / name).open("x") as file:
            json.dump(value, file, sort_keys=True, indent=2, allow_nan=False)
            file.write("\n")

    write("specification.json", json.loads(specification.read_bytes()))
    try:
        import numpy as np
        import torch
        from experiments.multimodal_output_portfolio.v6 import neural, owner_worker
        from experiments.multimodal_output_portfolio.v6.data import Observation, load_corpus, make_batch, render_tokens
        from experiments.multimodal_output_portfolio.v6.observer import Recognizer, observe_tensors, read_bundle, write_bundle
        from experiments.multimodal_output_portfolio.v6.plan_training import ControlledSnapshot

        original_registration = completed_registration(experiment)
        checkpoint, reward = experiment / "seed-17-terminal_entropic_ndu.pt", experiment / "reward-observer.pt"
        paths = {"checkpoint": checkpoint, "reward_a": reward, "calibrator_source": Path(__file__)}
        pins = {name: sha(path.read_bytes()) for name, path in paths.items()}
        if owner_worker.source_digest() != OWNER_SOURCE_SHA256:
            raise ValueError("Original generation implementation changed before calibration")
        write("registration.json", {**pins, "owner_source_sha256": OWNER_SOURCE_SHA256,
                                    "specification_sha256": SPEC_SHA256, "selection": "seed17/terminal_entropic_ndu",
                                    "original": original_registration})
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        record = neural.read_checkpoint(checkpoint, pins["checkpoint"])
        if record["schema"] != "hepta.ndu-v6.controlled-snapshot.v2":
            raise ValueError("Selected full-002 checkpoint must be registered controlled-v2")
        config_sha = sha(canonical(record["base_record"]["config"]))
        owner_worker.validate_checkpoint_config(record, {"hidden": 96, "config_sha256": config_sha})
        del record
        snapshot = ControlledSnapshot.load(checkpoint, expected_file_sha256=pins["checkpoint"])
        observer = Recognizer()
        reward_bytes = reward.read_bytes()
        if sha(reward_bytes) != pins["reward_a"]:
            raise ValueError("Reward A changed before deserialization")
        observer.load_state_dict(torch.load(io.BytesIO(reward_bytes), weights_only=True))
        observer.eval().requires_grad_(False)
        corpus = load_corpus(cache, evaluator_sources=10000)
        if corpus.manifest["manifest_sha256"] != original_registration["dataset_manifest_sha256"]:
            raise ValueError("Calibration corpus differs from the frozen original source manifest")
        source = corpus.splits["validation"]
        if len(source) < 1536:
            raise ValueError("Validation source capacity below preregistered 768 pairs")
        excluded = list(range(0, 512)) + list(range(1024, 1152))
        excluded_ids, excluded_pixels = ({source.ids[i] for i in excluded}, {source.pixel_hashes[i] for i in excluded})
        chosen = range(1280, 1536)
        if excluded_ids.intersection(source.ids[i] for i in chosen) or excluded_pixels.intersection(source.pixel_hashes[i] for i in chosen):
            raise ValueError("Calibration sources overlap forecasting or competence sources")
        write("source-manifest.json", {"validation": corpus.manifest["splits"]["validation"],
                                      "excluded_source_ids": sorted(excluded_ids), "excluded_pixel_hashes": sorted(excluded_pixels)})
        model_pins = {"checkpoint_sha256": pins["checkpoint"], "snapshot_sha256": snapshot.fingerprint,
                      "parameters_sha256": owner_worker.parameters_digest(snapshot), "config_sha256": config_sha,
                      "source_sha256": OWNER_SOURCE_SHA256, "python_sha256": sha(Path(sys.executable).read_bytes()),
                      "device_sha256": owner_worker.device_digest(), "runtime_versions": owner_worker.runtime_versions(), "hidden": 96}

        def state_record(state):
            values = snapshot.state_features(state).detach().cpu().numpy().astype("<f4").reshape(-1)
            backend, plan = snapshot.state_key(state), state.plan_indices[0]
            payload = b"hepta.inference.generation-state.v1\0" + snapshot.fingerprint.encode() + backend.encode()
            payload += struct.pack("<i", plan) + values.tobytes()
            return {"values_f32": values.view("<u4").tolist(), "backend_state_sha256": backend,
                    "plan_index": plan, "state_sha256": sha(payload)}

        rows = []
        with (output / "rows.jsonl").open("x") as journal, torch.inference_mode():
            for index in range(640, 768):
                ordinal, ood = (index - 640) % 64, (index - 640) % 64 >= 32
                corruption = ("clean", "occlusion", "missing", "train")[(ordinal // 4) % 4] if not ood else "clean"
                batch = make_batch(corpus, "validation", 1, 97531000 + index, corruption=corruption, offset=index)
                observation = batch.observation
                if ood:
                    tokens = observation.text_tokens.clone()
                    tokens[:, 3], tokens[:, 5] = 11, 11
                    observation = Observation(torch.zeros_like(observation.pixels), torch.zeros_like(observation.mask), tokens)
                action = ACTIONS[ordinal % 4]
                started = time.perf_counter_ns()
                previous = snapshot.encode(observation, noise_seed=18675000 + index, content_control=True)
                current = snapshot.step(previous, action)
                decoded = snapshot.decode(current)
                generation_ns = time.perf_counter_ns() - started
                previous_record, current_record = state_record(previous), state_record(current)
                started = time.perf_counter_ns()
                projection = scores(previous_record["values_f32"], current_record["values_f32"])
                projection_ns = time.perf_counter_ns() - started
                files = write_bundle(output / f"outputs/pair-{index}", render_tokens(decoded.token_ids[0]), decoded.image_logits.sigmoid()[0])
                pixels, caption, hashes = read_bundle(files)
                measured = observe_tensors(observer, pixels, [caption], batch.target.pixels, batch.target.labels)[0]
                success = measured["caption_valid"] and all(measured[key] == 0 for key in ("text_fact", "relation", "image_fact", "crossmodal_disagreement"))
                request = {"schema": owner_worker.SCHEMA, "request_id": f"neuron-generation:{index}",
                           "objective_sha256": SPEC_SHA256, "input_source_sha256": sha(canonical(batch.source_ids)),
                           "model": model_pins, "required_modalities": 3,
                           "pixels_f32": observation.pixels.numpy().astype("<f4").reshape(-1).view("<u4").tolist(),
                           "mask_f32": observation.mask.numpy().astype("<f4").reshape(-1).view("<u4").tolist(),
                           "text_tokens": observation.text_tokens[0].tolist(), "noise_seed": 18675000 + index,
                           "content_control": True, "actions": [action]}
                row = {"cohort": "calibration" if index < 704 else "verification", "pair_index": index,
                       "source_ids": list(batch.source_ids[0]), "pixel_hashes": list(source.pixel_hashes[2 * index:2 * index + 2]),
                       "predeclared_ood": ood, "corruption": "complete_visual_absence_no_hint" if ood else corruption,
                       "action": action, "joint_success": success, "metrics": measured, "generation_request": request,
                       "previous_state": previous_record, "current_state": current_record, **projection,
                       "generation_wall_ns": generation_ns, "projection_wall_ns": projection_ns,
                       "output_paths": {name: str(Path(path).relative_to(output)) for name, path in files.items()},
                       "output_hashes": hashes, "token_ids": decoded.token_ids[0].tolist()}
                row["row_sha256"] = sha(canonical(row))
                journal.write(canonical(row).decode() + "\n")
                journal.flush()
                rows.append(row)
        snapshot.verify_integrity()
        if (pins != {name: sha(path.read_bytes()) for name, path in paths.items()}
                or owner_worker.source_digest() != OWNER_SOURCE_SHA256
                or completed_registration(experiment) != original_registration):
            raise ValueError("Artifact/source changed during calibration")
        summary = summarize(rows)
        summary["registration"] = pins
        write("summary.json", summary)
        write("completion.json", {"state": "completed", "rows": len(rows), "summary_sha256": sha((output / "summary.json").read_bytes()),
                                  "point_gates_passed": summary["point_gates_passed"], "native_runtime_admission": "not_yet_executed"})
        return summary
    except BaseException as error:
        write("failure.json", {"state": "failed", "type": type(error).__name__, "error": str(error)})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("experiment", "cache", "specification", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(run(**vars(args)), sort_keys=True, allow_nan=False))
