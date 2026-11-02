"""Independent downloaded-artifact audit; no vendor weights or encoder replay."""

import argparse
import hashlib
import io
import json
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np


VENDOR_SHA = "efa5ac1a13b2d2f42182738e44794b1eb4c0cdd221a8b4ae11304c3a5f5fae95"
REVISION = "6eba34a2485ea31cb03600241787c3a5edab8626"
MODEL = "audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim"
CLASSES = ("ANG", "DIS", "FEA", "HAP", "NEU", "SAD")


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(array):
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def arrays(path):
    with np.load(path, allow_pickle=False) as archive:
        return {key: archive[key].copy() for key in archive.files}


def main(base, out, head):
    out.mkdir(parents=True, exist_ok=False)
    protocol = {"schema": "hcsn-v13-independent-emotion-ci-audit.v1", "expected_head": head,
        "auditor_sha256": sha(Path(__file__)), "encoder_reference_atol": 1e-6,
        "encoder_reference_rtol": 1e-5, "ridge_atol": 1e-9, "ridge_rtol": 1e-8,
        "solver": "Independent symmetric eigendecomposition of centered dual ridge; producer used a linear solve",
        "scope": "All retained identities/features/folds/heads/predictions and first-prefix preprocessing/pooling. No vendor checkpoint download or second encoder implementation."}
    (out / "PLAN.json").write_text(json.dumps(protocol, indent=2) + "\n")
    checks, failures, errors = 0, [], {}

    def check(ok, label):
        nonlocal checks
        checks += 1
        if not bool(ok) and len(failures) < 50:
            failures.append(label)

    def close(actual, expected, label, atol=1e-9, rtol=1e-8):
        a, b = np.asarray(actual), np.asarray(expected)
        check(a.shape == b.shape and np.isfinite(a).all() and np.isfinite(b).all(), label + " finite shape")
        if a.shape == b.shape:
            errors[label] = float(np.max(np.abs(a-b))) if a.size else 0.
            check(np.allclose(a, b, atol=atol, rtol=rtol), label + " fixed numeric gate")

    identity = read(base / "identity/IDENTITY.json")
    check(identity["checkout_sha"] == identity["expected_head"] == head, "exact actual source-head identity")
    sources = {}
    for row in identity["files"]:
        path = base / "identity" / row["snapshot"]
        content = path.read_bytes()
        check(len(content) == row["bytes"] and sha(path) == row["sha256"], "exact source/input snapshot SHA")
        check(hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest() == row["git_blob"], "snapshot self Git-blob identity")
        sources[row["path"]] = path

    def source(suffix):
        selected = [value for name, value in sources.items() if name.endswith(suffix)]
        if len(selected) != 1:
            raise ValueError("Ambiguous or absent captured input: " + suffix)
        return selected[0]

    check(any(name == ".github/workflows/hcsn-v13-emotion-encoder.yml" for name in sources), "hidden actual workflow snapshot retained")
    pcm = read(source("/emotion_encoder/inputs/PCM_IDENTITY.json"))
    cohort = sorted(read(source("/emotion_encoder/inputs/COHORT.json"))["records"], key=lambda r: r["clip"])
    transport = read(source("/emotion_encoder/inputs/TRANSPORT.json"))
    blocks = []
    for row in transport["parts"]:
        path = source("/emotion_encoder/inputs/" + row["name"])
        check(path.stat().st_size == row["bytes"] and sha(path) == row["sha256"], "actual waveform transport part")
        blocks.append(path.read_bytes())
    whole = b"".join(blocks)
    check(len(whole) == transport["whole_bytes"] and hashlib.sha256(whole).hexdigest() == transport["whole_sha256"] == pcm["waveforms_npz_sha256"], "whole physical waveform transport")
    with np.load(io.BytesIO(whole), allow_pickle=False) as data:
        waves, clips, actors = (data[key].copy() for key in ("waveforms", "clip", "actor"))
        check(int(data["sample_rate"]) == 16000, "actual transported sample rate")
    check(waves.shape == (288, 16000) and waves.dtype == np.float32 and np.isfinite(waves).all(), "all real accepted physical waveforms")
    check(digest(waves) == pcm["array_sha256"] and len(cohort) == 288 and len(set(clips)) == 288 and len(set(actors)) == 24, "fixed TRAIN population and array identity")
    y = np.asarray([CLASSES.index(row["emotion"]) for row in cohort])
    for index, row in enumerate(cohort):
        original = pcm["details"][index]
        fields = row["clip"].split("_")
        check(row["split"] == "train" and fields[0] == str(row["actor"]) and fields[2] == row["emotion"], "TRAIN label/actor agrees with recording identity")
        check(str(clips[index]) == row["clip"] and str(actors[index]) == str(row["actor"]) == original["actor"], "actual model row binds metadata")
        check(digest(waves[index]) == original["waveform_sha256"] == original["source_clock"]["waveform_sha256"], "actual accepted waveform hash")
        check(original["source_clock"]["padded_samples"] == 0 and original["source_clock"]["future_pcm_used"] is False, "actual no-padding/no-future prefix preparation")

    acquisition = read(base / "acquisition/ACQUISITION.json")
    seal = read(base / "acquisition/ASSET_SEAL.json")
    check(acquisition["status"] == "PASS" and acquisition["retry_count"] == 0 and acquisition["authentication_used"] is False, "one unauthenticated official acquisition campaign")
    check(seal["model"] == MODEL and seal["revision"] == REVISION and seal["sealed_before_inference_or_readout"] is True, "immutable official asset seal")
    check(seal["files"]["model.safetensors"]["sha256"] == VENDOR_SHA and seal["files"]["model.safetensors"]["bytes"] == 661375508, "actual CI download receipt binds published weight identity")
    for name in ("README.md", "config.json", "preprocessor_config.json"):
        path, record = base / "acquisition" / name, seal["files"][name]
        check(sha(path) == record["sha256"] and path.stat().st_size == record["bytes"], "retained official metadata bytes")
    for attempt in acquisition["attempts"]:
        check(attempt["status"] == "PASS" and attempt["attempts"] == 1 and attempt["sha256"] == seal["files"][attempt["file"]]["sha256"], "completed bounded official-file acquisition")
        urls = [attempt["official_url"], attempt["final_url"]]
        urls += [item[key] for item in attempt["redirects"] for key in ("from", "to")]
        check(all(not urlsplit(url).query and not urlsplit(url).fragment and urlsplit(url).username is None for url in urls), "logged URLs exclude queries/fragments/credentials")

    model = base / "model"
    result, loaded, runtime = read(model / "RESULT.json"), read(model / "MODEL_LOADED.json"), read(model / "RUNTIME.json")
    check(result["status"] == "PASS_EXECUTION_ONLY" and result["actual_recordings"] == 288 and result["actual_encoder_forwards"] == 290 and result["head_fits"] == 25, "complete real encoder/readout campaign roster")
    check(loaded["strict_missing_keys"] == loaded["strict_unexpected_keys"] == [] and loaded["loaded_tensor_count"] == 234 and loaded["no_random_weight_fallback"] is True and loaded["remote_code_execution"] is False, "actual complete strict pretrained load")
    check(loaded["asset_seal_sha256"] == sha(base / "acquisition/ASSET_SEAL.json") and loaded["attention_implementation"] == "eager", "actual loaded state binds seal and declared attention")
    mappings = {(row["from"].split(".")[-1], row["to"].split(".")[-1]) for row in loaded["key_mapping"]}
    check(mappings == {("weight_g", "original0"), ("weight_v", "original1")} and len(loaded["key_mapping"]) == 2, "only two positional weight-normalization aliases")
    expected_versions = {"torch": "2.6.0+cpu", "transformers": "4.49.0", "safetensors": "0.5.3", "numpy": "2.3.5"}
    check({key: value["version"] for key, value in runtime["packages"].items()} == expected_versions, "actual pinned scientific versions")
    check(result["source_identity_sha256"] == runtime["source_identity_sha256"] == sha(base / "identity/IDENTITY.json"), "model and runtime bind captured source")
    controls = {row["name"]: row for row in result["actual_controls"]}
    check(set(controls) == {"future_NaN", "future_finite", "inside_NaN", "short"}, "complete actual prefix controls")
    check(all(controls[name]["actual_forward"] and controls[name]["bitwise_equal"] for name in ("future_NaN", "future_finite")), "real future suffix forward controls passed")
    check(all(controls[name]["rejected_before_forward"] for name in ("inside_NaN", "short")), "invalid accepted-prefix controls rejected")

    features, oof = arrays(model / "FEATURES.npz"), arrays(model / "OOF_PREDICTIONS.npz")
    x = features["pooled"]
    check(x.shape == (288, 1024) and x.dtype == np.float64 and np.isfinite(x).all(), "only official pooled descriptor dimensions")
    check(np.array_equal(features["clip"], clips) and np.array_equal(features["actor"], actors), "all pooled rows bind original records")
    check(sha(model / "FEATURES.npz") == result["features_sha256"] and sha(model / "OOF_PREDICTIONS.npz") == result["oof_predictions_sha256"], "complete feature/prediction file identities")
    progress = [json.loads(line) for line in (model / "PROGRESS.jsonl").read_text().splitlines()]
    check(len(progress) == 288 and [row["index"] for row in progress] == list(range(288)), "all actual-prefix progress records exactly once")
    for index, row in enumerate(progress):
        path = model / "prefixes" / (str(clips[index]) + ".npz")
        local = arrays(path)
        check(row["clip"] == str(clips[index]) and row["accepted_waveform_sha256"] == digest(waves[index]), "prefix progress binds actual accepted input")
        check(sha(path) == row["prefix_output_sha256"] and digest(local["pooled"]) == row["pooled_sha256"] and digest(local["regression"]) == row["regression_sha256"], "retained actual prefix outputs match progress hashes")
        check(np.array_equal(local["pooled"].astype(np.float64), x[index]) and np.array_equal(local["regression"], features["regression"][index]), "whole features contain each actual prefix output")
    first = arrays(model / "FORWARD_REFERENCE.npz")
    check(np.array_equal(first["waveform"], waves[0]) and digest(first["hidden"]) == progress[0]["hidden_sha256"], "retained first forward input and hidden identity")
    check(first["hidden"].shape == (49, 1024) and np.isfinite(first["hidden"]).all(), "actual first transformer hidden dimensions")
    normalized = (waves[0]-waves[0].mean())/np.sqrt(waves[0].var()+1e-7)
    close(first["normalized"], normalized, "independent prefix-local normalization", 1e-6, 1e-5)
    close(first["hidden"].astype(np.float64).mean(0), first["pooled"], "independent hidden mean pooling", 1e-6, 1e-5)
    check(np.array_equal(first["pooled"].astype(np.float64), x[0]), "retained first output feeds actual descriptor")
    head_check = read(model / "HEAD_NUMERICAL_CHECK.json")
    check(head_check["independent_numpy_fp64_reference_passed"] is True and head_check["pretrained_parameter_bytes_exported"] is False and head_check["rtol"] == 1e-5 and head_check["atol"] == 1e-6, "CI internal independent head equation check and parameter-export boundary")
    check(set(head_check["parameter_identities"]) == {"dense.weight", "dense.bias", "out_proj.weight", "out_proj.bias"}, "official head recorded as identities only")
    check(not list(base.rglob("HEAD_REFERENCE_WEIGHTS.npz")), "no official pretrained head tensor archive exported")
    for path in model.rglob("*.npz"):
        check(not ({"dense.weight", "out_proj.weight"} & set(arrays(path))), "model artifact NPZ does not contain upstream parameter tensors")

    def eigen_fit(indices):
        values, labels = x[indices], y[indices]
        mean, scale = values.mean(0), values.std(0)
        scale[scale < 1e-12] = 1.
        z = (values-mean)/scale
        targets = np.eye(6)[labels]
        bias = targets.mean(0)
        eigenvalues, vectors = np.linalg.eigh(z @ z.T)
        alpha = vectors @ ((vectors.T @ (targets-bias))/(eigenvalues[:, None]+10.))
        return {"mean": mean, "scale": scale, "weight": z.T @ alpha, "bias": bias}

    def metrics(probability, labels):
        return {"correct": int((probability.argmax(1) == labels).sum()), "examples": len(labels),
            "accuracy": float((probability.argmax(1) == labels).mean()),
            "uncalibrated_nll": float(-np.log(probability[np.arange(len(labels)), labels]).mean()),
            "uncalibrated_brier": float(np.square(probability-np.eye(6)[labels]).sum(1).mean())}

    independent_oof, independent_scores, fold_rows = np.zeros((288, 6)), np.zeros((288, 6)), []
    check(len(result["held_actor_folds"]) == 24 and len(list((model / "heads").glob("*.npz"))) == 25 and result["fixed_lambda"] == 10., "all fixed-lambda readout fits retained")
    for fold in result["held_actor_folds"]:
        actor = fold["held_actor"]
        held, train = np.flatnonzero(actors == actor), np.flatnonzero(actors != actor)
        check(held.tolist() == fold["held_indices"] and train.tolist() == fold["train_indices"] and len(held) == 12 and len(train) == 276, "held actor wholly excluded from coefficient and normalizer fitting")
        check(np.array_equal(np.bincount(y[held], minlength=6), np.full(6, 2)), "actual held actor class support")
        expected, path = eigen_fit(train), model / "heads" / ("held_actor_" + actor + ".npz")
        stored = arrays(path)
        check(sha(path) == fold["weights_sha256"] and float(stored["ridge"]) == 10., "actual fold head identity and lambda")
        for key in expected:
            close(stored[key], expected[key], actor + " independent-eigh " + key)
        scores = ((x[held]-expected["mean"])/expected["scale"]) @ expected["weight"] + expected["bias"]
        exponent = np.exp(scores-scores.max(1, keepdims=True))
        probability = exponent/exponent.sum(1, keepdims=True)
        independent_scores[held], independent_oof[held] = scores, probability
        local_metrics = metrics(probability, y[held])
        for key, value in local_metrics.items():
            check(abs(value-fold[key]) < 1e-9, "independent held-actor metric: " + key)
        fold_rows.append({"actor": actor, **local_metrics})
    full = arrays(model / "heads/full_train.npz")
    for key, value in eigen_fit(np.arange(288)).items():
        close(full[key], value, "independent full TRAIN head " + key)
    close(oof["scores"], independent_scores, "all independently recomputed held scores")
    close(oof["probability"], independent_oof, "all independently recomputed OOF probabilities")
    check(np.array_equal(oof["emotion_target"], y) and np.array_equal(oof["actor"], actors) and np.array_equal(oof["clip"], clips), "raw prediction targets/identities")
    final_metrics = metrics(independent_oof, y)
    for key, value in final_metrics.items():
        check(abs(value-result["oof"][key]) < 1e-9, "independent aggregate OOF metric: " + key)
    for key in ("validation_or_test_loaded", "independent_confirmation", "readout_calibrated", "original_v6_task_equivalence_verified", "semantic_binding_completed", "strong_audio_reference_qualified"):
        check(result[key] is False, "strict qualification remains false: " + key)
    check(result["device_energy_joules"] is None and result["complete_process_family_rss_bytes"] is None, "unavailable energy/full-family memory not imputed")
    costs = []
    for directory in ("acquire_cost001", "model_cost001"):
        receipt = read(base / directory / "RECEIPT.json")
        check(receipt["complete_task_cpu_coverage"] and receipt["task_success"] and receipt["source_unchanged_through_collection"], "successful complete outer worker cost receipt")
        costs.append(receipt["complete_supervisor_wait4"]["cpu_seconds"])
    report = {"schema": protocol["schema"], "checks": checks, "passed": not failures, "failures": failures,
        "expected_head": head, "snapshot_count": len(sources), "independent_oof": final_metrics,
        "independent_actor_metrics": fold_rows, "largest_absolute_error": max(errors.values()),
        "numeric_errors": errors, "actual_encoder_forwards_reported_and_source_bound": 290,
        "strict_loaded_tensor_count": loaded["loaded_tensor_count"], "outer_cpu_seconds_nested_not_additive": costs,
        "scope": protocol["scope"], "second_encoder_implementation_executed": False,
        "full_vendor_checkpoint_locally_rehashed": False, "original_strong_reference_or_new_cohort_qualified": False,
        "source_snapshot_git_tree_membership": "Root independently checks expected local0f04 tree; this auditor verifies snapshot self identities."}
    (out / "RESULT.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("checks", "passed", "failures", "independent_oof", "snapshot_count")}))
    return report["passed"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expected-head", required=True)
    args = parser.parse_args()
    raise SystemExit(0 if main(args.artifact, args.out, args.expected_head) else 1)
