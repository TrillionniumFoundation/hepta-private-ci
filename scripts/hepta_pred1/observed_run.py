"""Train/dev-only owner pipeline; holdout forecasts are never backdated choices.

Input: a canonical Artifact manifest of already joined, SHA-pinned samples.
Output: fitted baselines, original frozen-policy scores and explicitly offline
held-out forecasts. Confirmation data and production adoption are separate.
"""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter, process_time

from .native_ledger import Artifact, _digest, _require
from .observed_evaluation import (
    UtilityContract, evaluate_observed, paired_adoption_gate, score_forecast,
)
from .observed_models import ObservedModel, fit_observed_model
from .owner_bridge import model_row, observed_from_artifact, target_schema_digest


def _read_inputs(manifest_path):
    manifest_path = Path(manifest_path).resolve(strict=True)
    artifact = Artifact.read(manifest_path)
    p = artifact.payload
    expected = {
        "schema", "train", "dev", "feature_names", "action_ids", "success_definition",
        "utility_contract", "seed", "hidden_size", "epochs", "learning_rate",
    }
    # Refuse unknown fields, including a confirmation entry, before opening data.
    _require(set(p) == expected and p["schema"] == "pred1-observed-study-input-v1", "train/dev manifest fields differ")
    root = manifest_path.parent
    target_digest = target_schema_digest(p["success_definition"], p["utility_contract"]["cost_unit"])
    samples, seen, groups = {"train": [], "dev": []}, set(), {}
    for split in samples:
        entries = p[split]
        _require(type(entries) is list and 1 <= len(entries) <= 256, "need 1..256 samples in each split")
        for entry in entries:
            _require(type(entry) is dict and set(entry) == {"path", "sha256"}, "sample entry fields differ")
            _digest(entry["sha256"])
            _require(type(entry["path"]) is str and not Path(entry["path"]).is_absolute(), "sample path must be relative")
            path = (root / entry["path"]).resolve(strict=True)
            _require(path.is_relative_to(root), "sample path escapes manifest directory")
            sample = Artifact.read(path)
            _require(sample.digest == entry["sha256"], "sample bytes differ")
            row = observed_from_artifact(sample)
            _require(row.split == split, "sample split differs from manifest")
            _require(row.sample_id not in seen, "duplicate sample in study")
            seen.add(row.sample_id)
            _require(row.task_group not in groups or groups[row.task_group] == split, "task group crosses train/dev")
            groups[row.task_group] = split
            _require(sample.payload["feature_names"] == p["feature_names"], "feature schema differs")
            _require(sample.payload["target_schema_sha256"] == target_digest and
                     sample.payload["success_definition"] == p["success_definition"] and
                     sample.payload["cost_unit"] == p["utility_contract"]["cost_unit"], "sample outcome definition or unit differs")
            samples[split].append(sample)
    return artifact, samples


def _run_observed(manifest_path, output, progress):
    """Fit two preregistered model kinds; report development only, without selection."""
    wall, cpu = perf_counter(), process_time()
    manifest, samples = _read_inputs(manifest_path)
    progress.update(stage="inputs_validated", input_sha256=manifest.digest)
    p = manifest.payload
    contract = UtilityContract(**p["utility_contract"])
    original = [observed_from_artifact(s) for split in ("train", "dev") for s in samples[split]]
    actual = evaluate_observed(original, contract)
    training = [model_row(s) for s in samples["train"]]
    output = Path(output)
    manifest.save(output / "INPUT.json")
    actual_artifact = Artifact.make(actual)
    actual_artifact.save(output / "ORIGINAL_POLICY_SCORES.json")
    models = {}
    for kind in ("empirical", "mlp"):
        progress["stage"] = kind + "_fit"
        model = fit_observed_model(
            training, kind=kind, feature_names=p["feature_names"], action_ids=p["action_ids"],
            success_definition=p["success_definition"], cost_unit=contract.cost_unit,
            seed=p["seed"], hidden_size=p["hidden_size"], epochs=p["epochs"],
            learning_rate=p["learning_rate"],
        )
        checkpoint = output / (kind + ".json")
        checkpoint_sha256 = model.save(checkpoint)
        progress["stage"] = kind + "_checkpoint_readback"
        restored = ObservedModel.load(checkpoint, expected_sha256=checkpoint_sha256)
        rows = []
        for index, sample in enumerate(samples["dev"]):
            progress["stage"] = kind + "_holdout"
            observed = observed_from_artifact(sample)
            executed = observed.executed_action == observed.chosen_action and observed.execution_ref is not None
            supported = observed.chosen_action in model.metadata["training"]["action_counts"]
            prediction = restored.predict(sample.payload["features"], observed.chosen_action) if supported else None
            if supported:
                _require(prediction == model.predict(sample.payload["features"], observed.chosen_action), "checkpoint prediction replay differs")
            score = score_forecast(prediction, observed.evidence) if executed and supported else None
            result = Artifact.make({
                "schema": "pred1-offline-holdout-forecast-v1", "sample_sha256": sample.digest,
                "sample_id": observed.sample_id, "task_group": observed.task_group,
                "chosen_action": observed.chosen_action, "checkpoint_sha256": checkpoint_sha256,
                "prediction": prediction, "scores": score,
                "prediction_status": "available" if supported else "unsupported_action",
                "scope": "offline held-out forecast; not available at original decision time",
                "counterfactual_policy_value": None, "prediction_deployed": False,
            })
            filename = f"{kind}-dev-{index:04d}.json"
            result.save(output / filename)
            rows.append({"path": filename, "sha256": result.digest, "scores": score, "supported": supported})
        summaries = {}
        for metric in ("quality_brier", "duration_crps", "cost_crps"):
            values = [r["scores"][metric] for r in rows if r["scores"] is not None and r["scores"][metric] is not None]
            summaries[metric] = {"observed_count": len(values), "mean": sum(values) / len(values) if values else None}
        models[kind] = {
            "checkpoint": checkpoint.name, "checkpoint_sha256": checkpoint_sha256,
            "optimizer_calls": model.metadata["optimizer_calls"],
            "sample_presentations": model.metadata["sample_presentations"],
            "fit_wall_seconds": model.metadata["fit_wall_seconds"],
            "fit_cpu_seconds": model.metadata["fit_cpu_seconds"],
            "training": model.metadata["training"], "holdout_scores": summaries,
            "unsupported_holdout_actions": sum(not r["supported"] for r in rows),
            "holdout_artifacts": [{"path": r["path"], "sha256": r["sha256"]} for r in rows],
        }
    files = ("observed_run.py", "owner_bridge.py", "observed_evaluation.py", "observed_models.py")
    report = Artifact.make({
        "schema": "pred1-observed-development-run-v1", "input_sha256": manifest.digest,
        "source_sha256": {name: sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in files},
        "train_samples": len(samples["train"]), "dev_samples": len(samples["dev"]),
        "original_policy_scores_sha256": actual_artifact.digest, "models": models,
        "adoption": paired_adoption_gate(original, contract),
        "new_independent_confirmation_units": 0, "confirmation_data_opened": False,
        "native_provenance_authenticated": False, "physical_cost_complete": False,
        "pipeline_wall_seconds": perf_counter() - wall, "pipeline_cpu_seconds": process_time() - cpu,
        "meter_scope": "read/validate/fit/checkpoint/save/reload/holdout; excludes final report serialization and owner/observer work",
        "qualification": "HOLD", "production_activation": False,
    })
    report.save(output / "REPORT.json")
    progress["stage"] = "report_saved"
    return report


def run_observed(manifest_path, output):
    """Retain every admitted run, including failures and their partial artifacts."""
    wall, cpu = perf_counter(), process_time()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    progress = {"stage": "input_validation", "input_sha256": None}
    Artifact.make({"schema": "pred1-observed-run-start-v1", "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest()}).save(output / "STARTED.json")
    failure = None
    try:
        result = _run_observed(manifest_path, output, progress)
    except BaseException as exc:
        failure = {"type": type(exc).__name__, "message": str(exc)[:1024]}
        raise
    finally:
        inventory = []
        for path in sorted(output.iterdir()):
            if path.is_file():
                inventory.append({"path": path.name, "bytes": path.stat().st_size,
                                  "sha256": sha256(path.read_bytes()).hexdigest()})
        receipt = Artifact.make({
            "schema": "pred1-observed-run-terminal-v1", "state": "FAILED" if failure else "COMPLETED",
            **progress, "failure": failure, "artifacts": inventory,
            "wall_seconds": perf_counter() - wall, "process_cpu_seconds": process_time() - cpu,
            "scope": "this admitted run including retained failed work; excludes final receipt serialization",
            "physical_cost_complete": False, "qualification": "HOLD", "production_activation": False,
        })
        receipt.save(output / ("FAILED.json" if failure else "COMPLETED.json"))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = run_observed(args.manifest, args.output)
    print(json.dumps({"report_sha256": report.digest, "qualification": report.payload["qualification"]}))


if __name__ == "__main__":
    main()
