"""Replay train-internal threshold selection and frozen artifact bindings."""
import hashlib
import json
import math
from pathlib import Path

from token_review import _official, _sha, require, score


def review_selection(seed_folder, *, source_dir):
    folder = Path(seed_folder)
    root = folder.parent
    design = json.loads((root / "design.json").read_text())
    frozen = json.loads((root / "all-models-frozen.json").read_text())
    manifest_bytes = (folder / "models.json").read_bytes()
    models = json.loads(manifest_bytes)
    tuning = json.loads((folder / "tuning.json").read_text())
    official, _ = _official(Path(source_dir), design["dataset_files_sha256"])
    arms = design["expected_arms"]
    require(set(tuning) == set(arms) == set(models["arm_thresholds"]) == set(models["arm_model_names"]),
            "complete train-internal arm selection required")
    seed = str(int(folder.name.removeprefix("seed-")))
    require(hashlib.sha256(manifest_bytes).hexdigest() == frozen["model_manifests_sha256"][seed],
            "selected model manifest changed after global freeze")
    require(models["final_evaluation_started"] is False and frozen["final_evaluation_started"] is False,
            "selection must precede final evaluation")
    require(type(models["frozen_before_final_ns"]) is int and
            type(frozen["frozen_ns"]) is int and frozen["frozen_ns"] >= models["frozen_before_final_ns"] > 0,
            "declared freeze boundaries are inconsistent")
    tune_sources = set(design["partitions"]["tune"])
    expected_ids = {key for key, value in official.items() if value["source_hash"] in tune_sources}
    require(expected_ids and all(official[key]["split"] == "train" for key in expected_ids),
            "threshold selection must use official-train paragraphs")
    grid = [i / 20 for i in range(1, 20)]
    require(design["threshold_grid"] == grid, "registered threshold grid changed")
    selected, arm_models = {}, {}
    for name, artifact in models["models"].items():
        _sha(artifact["file_sha256"])
        path = Path(artifact["file"])
        require(not path.is_absolute() and ".." not in path.parts, "relative model artifact path required")
        require(hashlib.sha256((folder / path).read_bytes()).hexdigest() == artifact["file_sha256"],
                "selected model artifact bytes changed")
        _sha(artifact["model_sha256"])
    for arm in arms:
        selection = tuning[arm]
        ids, probabilities = selection["case_ids"], selection["probabilities"]
        require(isinstance(ids, list) and len(ids) == len(set(ids)) and set(ids) == expected_ids,
                "tuning omits/duplicates source paragraph candidates")
        require(isinstance(probabilities, list) and len(probabilities) == len(ids) and all(
            type(p) in (int, float) and math.isfinite(p) and 0 <= p <= 1 for p in probabilities),
            "complete finite tuning probabilities required")
        require(selection["final_outcomes_used"] is False and
                selection["criterion"] == "F1a_then_EM_then_nearest_0.5_then_lower", "threshold selection rule changed")
        candidates = []
        require(len(selection["candidates"]) == len(grid), "full tuning grid results required")
        for threshold, declared in zip(grid, selection["candidates"]):
            require(declared["threshold"] == threshold, "tuning grid order changed")
            metrics = score([dict(case_id=key, prediction=int(p >= threshold)) for key, p in zip(ids, probabilities)], official)
            for field in ("questions", "f1_a", "exact_match", "accuracy"):
                require(type(declared["metrics"][field]) in (int, float) and math.isclose(
                    declared["metrics"][field], metrics[field], rel_tol=0., abs_tol=1e-12),
                    "tuning metric disagrees with official labels")
            require(declared["metrics"].get("n", declared["metrics"].get("candidates")) == len(ids), "tuning candidate count changed")
            candidates.append((threshold, metrics))
        best = max(candidates, key=lambda row: (row[1]["f1_a"], row[1]["exact_match"], -abs(row[0] - .5), -row[0]))[0]
        require(selection["threshold"] == models["arm_thresholds"][arm] == best,
                "selected threshold differs from independent grid/tie-break replay")
        model_name = models["arm_model_names"][arm]
        require(model_name in models["models"], "arm references missing selected model")
        arm_models[arm] = models["models"][model_name]["model_sha256"]
        selected[arm] = best
    return dict(schema="hepta.token-selection.independent-review.v1", passed=True,
        tuning_candidates=len(expected_ids), tuning_sources=len(tune_sources), arms=len(arms),
        arm_thresholds=selected, arm_model_sha256=arm_models,
        official_train_only=True, full_paragraph_candidates=True,
        grid_and_tie_break_independently_replayed=True, frozen_artifact_bytes_checked=True,
        preregistration_time_independently_verified=False)
