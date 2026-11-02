"""Exact-head source capture, actual fixed emotion encoder and fixed actor OOF."""

import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import subprocess
import sys
import time

from .contracts import VERSIONS, safe_error, sha, write

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CLASSES = ("ANG", "DIS", "FEA", "HAP", "NEU", "SAD")


def identity(out, expected_head):
    if subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() != expected_head:
        raise ValueError("Actual checkout differs from exact event head")
    out.mkdir(parents=True, exist_ok=False)
    scope = str(HERE.relative_to(ROOT))
    extras = [".github/workflows/hcsn-v13-emotion-encoder.yml",
        "experiments/hcsn_v13_followup_20261102/frontend/emotion_readout.py",
        "experiments/hcsn_v13_followup_20261102/frontend/strong_audio.py",
        "experiments/hcsn_v13_followup_20261102/frontend/reused_train001/encoder.py",
        "experiments/hcsn_v13_followup_20261102/frontend/reused_train001/inputs/train001/IDENTITY.json",
        "experiments/hcsn_v8_execution_20261101/economics/worker_cost.py",
        "experiments/hcsn_v8_execution_20261101/economics/worker_entry.py",
        "experiments/hcsn_v7_support_20261101/memory_observer/process_memory.py"]
    extras += [str((HERE / name).relative_to(ROOT)) for name in
               ("contracts.py", "model.py", "campaign.py", "acquire.py", "transport.py", "PROTOCOL.json",
                "inputs/TRANSPORT.json", "inputs/PCM_IDENTITY.json", "inputs/COHORT.json")]
    paths = subprocess.check_output(["git", "ls-files", "-z", "--", scope, *extras]).decode().split("\0")
    snapshots, records = out / "snapshots", []
    snapshots.mkdir()
    for name in sorted(filter(None, paths)):
        path = ROOT / name
        content = path.read_bytes()
        blob = subprocess.check_output(["git", "rev-parse", "HEAD:" + name], text=True).strip()
        actual = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
        if actual != blob:
            raise ValueError("Uncommitted source/input bytes: " + name)
        target = snapshots / name.replace("/", "__")
        target.write_bytes(content)
        records.append({"path": name, "git_blob": blob, "sha256": sha(path), "bytes": len(content),
                        "snapshot": str(target.relative_to(out))})
    if not all(name in {r["path"] for r in records} for name in extras):
        raise ValueError("Sparse checkout omitted required source snapshots")
    write(out / "IDENTITY.json", {"schema": "hcsn-v13-emotion-source-identity.v1", "expected_head": expected_head,
          "checkout_sha": expected_head, "files": records, "python": sys.version})


def arrays_sha(array):
    return hashlib.sha256(array.tobytes()).hexdigest()


def main_run(out, model_dir, waveform_file, source_identity):
    import numpy as np
    from .model import EmotionEncoder
    from ..frontend.emotion_readout import fit, metrics, probabilities, save_parameters
    source = json.loads(source_identity.read_text())
    if subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() != source["expected_head"]:
        raise ValueError("Model worker checkout differs from captured source")
    for row in source["files"]:
        if sha(ROOT / row["path"]) != row["sha256"]:
            raise ValueError("Captured committed source/input changed")
    out.mkdir(parents=True, exist_ok=False)
    began, phases = time.process_time(), {"stage": "inputs", "completed_prefixes": 0}
    try:
        pcm = json.loads((HERE / "inputs/PCM_IDENTITY.json").read_text())
        records = sorted(json.loads((HERE / "inputs/COHORT.json").read_text())["records"], key=lambda r: r["clip"])
        if sha(waveform_file) != pcm["waveforms_npz_sha256"] or len(records) != 288:
            raise ValueError("Actual restored waveform input differs")
        with np.load(waveform_file, allow_pickle=False) as values:
            waves, clips, actors = values["waveforms"].copy(), values["clip"].copy(), values["actor"].copy()
            if int(values["sample_rate"]) != 16000 or waves.shape != (288, 16000) or waves.dtype != np.float32:
                raise ValueError("Prepared waveform shape/dtype/rate differs")
        if not np.isfinite(waves).all() or len(set(actors)) != 24 or arrays_sha(waves) != pcm["array_sha256"]:
            raise ValueError("Fixed TRAIN wave/actor contract differs")
        for index, row in enumerate(records):
            detail = pcm["details"][index]
            if (row["split"] != "train" or str(clips[index]) != row["clip"] or str(actors[index]) != str(row["actor"])
                    or detail["clip"] != row["clip"] or detail["raw_sha256"] != row["sha256"]
                    or detail["waveform_sha256"] != arrays_sha(waves[index])):
                raise ValueError("Actual TRAIN prefix identity differs")
        packages = {name: {"version": metadata.version(name)} for name in VERSIONS}
        write(out / "RUNTIME.json", {"python": sys.version, "python_binary_sha256": sha(Path(sys.executable).resolve()),
              "packages": packages, "source_identity_sha256": sha(source_identity),
              "protocol_sha256": sha(HERE / "PROTOCOL.json"), "numeric_reference_rtol": 1e-5, "numeric_reference_atol": 1e-6})
        phases["stage"] = "strict_model_load"
        encoder = EmotionEncoder(model_dir)
        write(out / "MODEL_LOADED.json", {"strict_missing_keys": [], "strict_unexpected_keys": [],
            "loaded_tensor_count": encoder.tensor_count, "key_mapping": encoder.key_mapping,
            "runtime_source_sha256": encoder.runtime_source_sha256,
            "asset_seal_sha256": sha(model_dir / "ASSET_SEAL.json"), "no_random_weight_fallback": True,
            "remote_code_execution": False, "attention_implementation": "eager"})
        prefixes, features, regressions, controls = out / "prefixes", [], [], []
        prefixes.mkdir()
        phases["stage"] = "actual_encoder_forwards"
        with (out / "PROGRESS.jsonl").open("x") as progress:
            for index, row in enumerate(records):
                tick = time.process_time()
                actual = encoder.infer(waves[index])
                if index == 0:
                    for label, suffix in (("future_NaN", np.full(127, np.nan, dtype=np.float32)),
                                          ("future_finite", np.linspace(-100, 100, 127, dtype=np.float32))):
                        changed = encoder.infer(np.r_[waves[index], suffix])
                        passed = all(np.array_equal(actual[key], changed[key]) for key in actual)
                        controls.append({"name": label, "actual_forward": True, "bitwise_equal": passed})
                        if not passed:
                            raise ValueError("Unaccepted future affected actual pretrained encoder")
                    for label, bad in (("inside_NaN", np.r_[np.nan, waves[index, 1:]]), ("short", waves[index, :-1])):
                        try:
                            encoder.infer(bad)
                        except ValueError:
                            controls.append({"name": label, "rejected_before_forward": True})
                        else:
                            raise ValueError("Invalid accepted prefix admitted")
                    normalized = (waves[index] - waves[index].mean()) / np.sqrt(waves[index].var() + 1e-7)
                    if not np.allclose(actual["normalized"], normalized, rtol=1e-5, atol=1e-6):
                        raise ValueError("Actual processor differs from prefix-local normalization")
                    head = {key: value.detach().numpy().copy() for key, value in encoder.model.classifier.state_dict().items()}
                    pooled_reference = actual["hidden"].astype(np.float64).mean(0)
                    dense_reference = pooled_reference @ head["dense.weight"].astype(np.float64).T + head["dense.bias"]
                    regression_reference = np.tanh(dense_reference) @ head["out_proj.weight"].astype(np.float64).T + head["out_proj.bias"]
                    if (not np.allclose(pooled_reference, actual["pooled"], rtol=1e-5, atol=1e-6)
                            or not np.allclose(regression_reference, actual["regression"], rtol=1e-5, atol=1e-6)):
                        raise ValueError("Independent FP64 mean/regression-head reference differs")
                    write(out / "HEAD_NUMERICAL_CHECK.json", {"independent_numpy_fp64_reference_passed": True,
                        "pooled_max_absolute_difference": float(np.max(abs(pooled_reference - actual["pooled"]))),
                        "regression_max_absolute_difference": float(np.max(abs(regression_reference - actual["regression"]))),
                        "parameter_identities": {key: {"shape": list(value.shape), "sha256": arrays_sha(value)} for key, value in head.items()},
                        "pretrained_parameter_bytes_exported": False, "rtol": 1e-5, "atol": 1e-6})
                    np.savez_compressed(out / "FORWARD_REFERENCE.npz", waveform=waves[index], **actual)
                path = prefixes / (row["clip"] + ".npz")
                np.savez_compressed(path, pooled=actual["pooled"], regression=actual["regression"])
                features.append(actual["pooled"]); regressions.append(actual["regression"])
                record = {"index": index, "clip": row["clip"], "accepted_waveform_sha256": arrays_sha(waves[index]),
                    "hidden_sha256": arrays_sha(actual["hidden"]), "pooled_sha256": arrays_sha(actual["pooled"]),
                    "regression_sha256": arrays_sha(actual["regression"]), "prefix_output_sha256": sha(path),
                    "body_cpu_seconds": time.process_time() - tick}
                progress.write(json.dumps(record) + "\n"); progress.flush()
                phases["completed_prefixes"] = index + 1
                if (index + 1) % 24 == 0:
                    print(json.dumps({"actual_prefixes_completed": index + 1}), flush=True)
        x, y = np.asarray(features, dtype=np.float64), np.asarray([CLASSES.index(row["emotion"]) for row in records])
        np.savez_compressed(out / "FEATURES.npz", pooled=x, regression=np.asarray(regressions), clip=clips, actor=actors)
        phases["stage"] = "fixed_actor_OOF"
        heads, oof, scores, folds = out / "heads", np.zeros((288, 6)), np.zeros((288, 6)), []
        heads.mkdir()
        for actor in sorted(set(actors)):
            held, train = np.flatnonzero(actors == actor), np.flatnonzero(actors != actor)
            if len(held) != 12 or not np.array_equal(np.bincount(y[held], minlength=6), np.full(6, 2)):
                raise ValueError("Fixed actor-fold support differs")
            parameters = fit(x[train], y[train])
            scores[held], oof[held] = probabilities(x[held], parameters)
            path = heads / ("held_actor_" + str(actor) + ".npz")
            save_parameters(path, parameters)
            folds.append({"held_actor": str(actor), "train_indices": train.tolist(), "held_indices": held.tolist(),
                          "weights_sha256": sha(path), **metrics(oof[held], y[held])})
        save_parameters(heads / "full_train.npz", fit(x, y))
        np.savez_compressed(out / "OOF_PREDICTIONS.npz", probability=oof, scores=scores, emotion_target=y, actor=actors, clip=clips)
        write(out / "RESULT.json", {"schema": "hcsn-v13-actual-emotion-encoder-development.v1", "status": "PASS_EXECUTION_ONLY",
            "actual_recordings": 288, "actual_encoder_forwards": 290, "feature_width": 1024, "head_fits": 25,
            "classes": list(CLASSES), "fixed_lambda": 10., "held_actor_folds": folds, "oof": metrics(oof, y),
            "actual_controls": controls, "features_sha256": sha(out / "FEATURES.npz"),
            "oof_predictions_sha256": sha(out / "OOF_PREDICTIONS.npz"), "process_body_cpu_seconds": time.process_time() - began,
            "reference_rtol": 1e-5, "reference_atol": 1e-6, "source_identity_sha256": sha(source_identity),
            "validation_or_test_loaded": False, "independent_confirmation": False, "readout_calibrated": False,
            "original_v6_task_equivalence_verified": False, "semantic_binding_completed": False,
            "strong_audio_reference_qualified": False, "device_energy_joules": None, "complete_process_family_rss_bytes": None})
    except Exception as error:
        write(out / "FAILURE.json", {**phases, "error_type": type(error).__name__, "error": safe_error(error),
              "process_body_cpu_seconds_so_far": time.process_time() - began, "complete_campaign_cpu_seconds": None})
        raise RuntimeError(safe_error(error)) from None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("identity", "run"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expected-head")
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--waveforms", type=Path)
    parser.add_argument("--source-identity", type=Path)
    args = parser.parse_args()
    identity(args.out, args.expected_head) if args.mode == "identity" else main_run(args.out, args.model_dir, args.waveforms, args.source_identity)
