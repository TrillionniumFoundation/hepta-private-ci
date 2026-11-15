"""Compare fixed empirical/MLP/GRU forecasts on SHA-bound owner histories.

This is an offline train/dev command. Retained decisions are scored separately;
new forecasts never acquire their timestamps or constitute a new policy trial.
"""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter, process_time

from .native_ledger import Artifact, KEY_FIELDS, MAX_BYTES, _digest, _require
from .observed_calibration import summarize_offline_forecasts
from .observed_evaluation import UtilityContract, evaluate_observed, paired_adoption_gate, score_forecast
from .observed_gru import ObservedGRU, fit_observed_gru
from .observed_history import history_model_row, summarize_history, summary_model_row
from .observed_models import ObservedModel, fit_observed_model
from .owner_bridge import observed_from_artifact, target_schema_digest

SOURCE_FILES = (
    "__init__.py", "action_history.py", "contracts.py", "models.py", "native_ledger.py",
    "observed_calibration.py", "observed_evaluation.py", "observed_gru.py",
    "observed_history.py", "observed_history_run.py", "observed_models.py",
    "observed_policy.py", "owner_bridge.py",
)
KINDS = ("empirical", "mlp", "gru")
REPRESENTATIONS = {
    "empirical": "action-conditioned frequency; full history retained but not conditioned on",
    "mlp": "fixed final row, all-row mean and length of the same observed history",
    "gru": "ordered variable-length observed history; candidate action conditions the head",
}


def _read_inputs(manifest_path, manifest=None, retained=None):
    manifest_path = Path(manifest_path).resolve(strict=True)
    manifest = Artifact.read(manifest_path) if manifest is None else manifest
    p = manifest.payload
    fields = {"schema", "train", "dev", "feature_names", "action_ids", "success_definition",
              "utility_contract", "seed", "hidden_size", "epochs", "learning_rate"}
    _require(set(p) == fields and p["schema"] == "pred1-observed-history-study-v1",
             "train/dev history manifest fields differ")
    root, seen, groups, owner_attempts, runs = manifest_path.parent, set(), {}, set(), {}
    samples, rows, sources = {"train": [], "dev": []}, {"train": [], "dev": []}, {}
    contract = UtilityContract(**p["utility_contract"])
    target = target_schema_digest(p["success_definition"], contract.cost_unit)
    replay = manifest.payload
    for split in samples:
        _require(type(p[split]) is list and 1 <= len(p[split]) <= 256,
                 "need 1..256 samples in each split")
        replay[split] = []
        for item in p[split]:
            _require(type(item) is dict and set(item) == {"sample", "decision", "snapshot"},
                     "history input requires sample, decision and original snapshot")
            bundle, replay_entry = {}, {}
            for kind, entry in item.items():
                _require(type(entry) is dict and set(entry) == {"path", "sha256"},
                         "source reference fields differ")
                _digest(entry["sha256"])
                _require(type(entry["path"]) is str and not Path(entry["path"]).is_absolute(),
                         "source path must be relative")
                path = (root / entry["path"]).resolve(strict=True)
                _require(path.is_relative_to(root), "source path escapes input directory")
                artifact = Artifact.read(path)
                if retained is not None and artifact.digest not in sources:
                    artifact.save(retained / (artifact.digest + ".json"))
                _require(artifact.digest == entry["sha256"], "input source bytes differ")
                sources[artifact.digest] = artifact
                bundle[kind] = artifact
                replay_entry[kind] = {"path": "inputs/" + artifact.digest + ".json",
                                      "sha256": artifact.digest}
            row = history_model_row(**bundle)
            sample = bundle["sample"]
            owner_key = tuple(sample.payload["identity"][key] for key in KEY_FIELDS)
            _require(owner_key not in owner_attempts, "native owner attempt reused in study")
            owner_attempts.add(owner_key)
            run = owner_key[:2]
            _require(run not in runs or runs[run] == split, "native owner run crosses train/dev")
            runs[run] = split
            _require(row["split"] == split and row["sample_id"] not in seen,
                     "duplicate sample or split differs")
            seen.add(row["sample_id"])
            group = row["task_group"]
            _require(group not in groups or groups[group] == split, "task group crosses train/dev")
            groups[group] = split
            _require(sample.payload["feature_names"] == p["feature_names"]
                     and sample.payload["target_schema_sha256"] == target,
                     "study feature or target schema differs")
            _require(bundle["decision"].payload["action_order"] == p["action_ids"],
                     "study ordered action panel differs")
            _require(row["action_id"] in p["action_ids"], "action outside study panel")
            _require(observed_from_artifact(sample).budget_contract_digest == contract.digest,
                     "study utility contract differs")
            samples[split].append(sample)
            rows[split].append(row)
            replay[split].append(replay_entry)
    return manifest, samples, rows, sources, Artifact.make(replay)


def _run(manifest_path, output, progress, source_hashes, manifest_bytes):
    output = Path(output)
    manifest, samples, rows, _, replay = _read_inputs(
        manifest_path, Artifact(manifest_bytes), output / "inputs")
    progress.update(stage="inputs_validated", input_sha256=manifest.digest)
    p = manifest.payload
    manifest.save(output / "INPUT.json")
    replay.save(output / "REPLAY_INPUT.json")
    contract = UtilityContract(**p["utility_contract"])
    original = [observed_from_artifact(s) for split in ("train", "dev") for s in samples[split]]
    Artifact.make(evaluate_observed(original, contract)).save(output / "ORIGINAL_POLICY_SCORES.json")
    observations = [observed_from_artifact(s) for s in samples["dev"]]
    parameters = {key: p[key] for key in ("feature_names", "action_ids", "success_definition",
                                         "seed", "hidden_size", "epochs", "learning_rate")}
    parameters["cost_unit"] = contract.cost_unit
    models = {}
    for kind in KINDS:
        progress["stage"] = kind + "_fit"
        if kind == "gru":
            model = fit_observed_gru(rows["train"], **parameters)
        elif kind == "mlp":
            _, names = summarize_history(rows["train"][0]["history"], p["feature_names"])
            training = [summary_model_row(row, p["feature_names"]) for row in rows["train"]]
            model = fit_observed_model(training, kind=kind, **{**parameters, "feature_names": names},
                                       feature_encoding="history_last_mean_length_v1")
        else:
            model = fit_observed_model(rows["train"], kind=kind, **parameters)
        expected_source = ({name: source_hashes[name] for name in
                            ("observed_gru.py", "observed_models.py", "models.py")}
                           if kind == "gru" else source_hashes["observed_models.py"])
        _require(model.metadata["source_sha256"] == expected_source, "model source differs from retained source")
        checkpoint = output / (kind + ".json")
        digest = model.save(checkpoint)
        progress["stage"] = kind + "_checkpoint_readback"
        loader = ObservedGRU if kind == "gru" else ObservedModel
        restored = loader.load(checkpoint, expected_sha256=digest)
        predictions, artifacts = [], []
        for index, (observed, row, sample) in enumerate(zip(observations, rows["dev"], samples["dev"])):
            progress["stage"] = kind + "_holdout"
            features = row["history"] if kind == "gru" else row["features"]
            if kind == "mlp":
                features, _ = summarize_history(row["history"], p["feature_names"])
            supported = observed.chosen_action in model.metadata["training"]["action_counts"]
            prediction = restored.predict(features, observed.chosen_action) if supported else None
            if supported:
                _require(prediction == model.predict(features, observed.chosen_action),
                         "checkpoint forecast replay differs")
            predictions.append(prediction)
            executed = observed.executed_action == observed.chosen_action and observed.execution_ref is not None
            forecast = Artifact.make({
                "schema": "pred1-offline-history-forecast-v1", "sample_sha256": sample.digest,
                "sample_id": observed.sample_id, "history_binding": row["history_binding"],
                "task_group": observed.task_group, "chosen_action": observed.chosen_action,
                "checkpoint_sha256": digest, "prediction": prediction,
                "scores": score_forecast(prediction, observed.evidence) if supported and executed else None,
                "prediction_status": "available" if supported else "unsupported_action",
                "prediction_deployed": False, "counterfactual_policy_value": None,
                "scope": "offline chosen-action forecast; not available at original decision time",
            })
            filename = f"{kind}-dev-{index:04d}.json"
            forecast.save(output / filename)
            artifacts.append({"path": filename, "sha256": forecast.digest})
        calibration = Artifact.make(summarize_offline_forecasts(observations, predictions))
        calibration.save(output / (kind + "-calibration.json"))
        models[kind] = {"checkpoint": checkpoint.name, "checkpoint_sha256": digest,
                        "calibration_sha256": calibration.digest, "metadata": model.metadata,
                        "representation": REPRESENTATIONS[kind], "holdout_artifacts": artifacts}
    _require(all(sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() == digest
                 for name, digest in source_hashes.items()), "runtime source changed during study")
    report = Artifact.make({
        "schema": "pred1-observed-history-run-v1", "input_sha256": manifest.digest,
        "replay_input_sha256": replay.digest, "source_sha256": source_hashes,
        "train_samples": len(rows["train"]), "dev_samples": len(rows["dev"]), "models": models,
        "original_policy_eligibility": paired_adoption_gate(original, contract),
        "new_policy_adoption": "NoUpdate", "new_policy_real_task_comparisons": 0,
        "new_independent_confirmation_units": 0, "confirmation_data_opened": False,
        "prediction_deployed": False, "native_provenance_authenticated": False,
        "physical_cost_complete": False, "causal_policy_value_identified": False,
        "recursive_latent_rollout": False, "survival_model_fitted": False,
        "qualification": "HOLD", "production_activation": False,
        "scope": "complete-case observational marginals; architecture and history-summary comparison; no winner selection",
    })
    report.save(output / "REPORT.json")
    progress["stage"] = "report_saved"
    return report


def run_history_study(manifest_path, output):
    """Retain original inputs, sources and partial work for every admitted run."""
    wall, cpu = perf_counter(), process_time()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    progress = {"stage": "source_retention", "input_sha256": None}
    Artifact.make({"schema": "pred1-history-start-v1", "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest()}).save(output / "STARTED.json")
    failure = None
    try:
        (output / "inputs").mkdir()
        (output / "source" / "hepta_pred1").mkdir(parents=True)
        source_hashes = {}
        for name in SOURCE_FILES:
            data = Path(__file__).with_name(name).read_bytes()
            source_hashes[name] = sha256(data).hexdigest()
            with (output / "source" / "hepta_pred1" / name).open("xb") as stream:
                stream.write(data)
        Artifact.make({"source_sha256": source_hashes}).save(output / "SOURCE.json")
        progress["stage"] = "input_validation"
        with Path(manifest_path).open("rb") as stream:
            encoded = stream.read(MAX_BYTES + 1)
        with (output / "INPUT.raw").open("xb") as stream:
            stream.write(encoded)
        progress["input_sha256"] = sha256(encoded).hexdigest()
        Artifact.make({"sha256": progress["input_sha256"], "bytes": len(encoded),
                       "complete": len(encoded) <= MAX_BYTES}).save(output / "INPUT_CAPTURE.json")
        _require(len(encoded) <= MAX_BYTES, "manifest byte limit exceeded; prefix retained")
        return _run(manifest_path, output, progress, source_hashes, encoded)
    except BaseException as exc:
        failure = {"type": type(exc).__name__, "message": str(exc)[:1024]}
        raise
    finally:
        inventory = [{"path": path.relative_to(output).as_posix(), "bytes": path.stat().st_size,
                      "sha256": sha256(path.read_bytes()).hexdigest()}
                     for path in sorted(output.rglob("*")) if path.is_file()]
        Artifact.make({"schema": "pred1-history-terminal-v1", "state": "FAILED" if failure else "COMPLETED",
                       **progress, "failure": failure, "artifacts": inventory,
                       "wall_seconds": perf_counter() - wall, "process_cpu_seconds": process_time() - cpu,
                       "meter_scope": "all admitted run work through inventory; excludes final receipt serialization",
                       "physical_cost_complete": False, "qualification": "HOLD",
                       "production_activation": False}).save(output / ("FAILED.json" if failure else "COMPLETED.json"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = run_history_study(args.manifest, args.output)
    print(json.dumps({"report_sha256": report.digest, "qualification": report.payload["qualification"]}))


if __name__ == "__main__":
    main()
