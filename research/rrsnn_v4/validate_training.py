"""End-to-end trainer checks on FOUR development episodes in a temporary root.

This does not read, create or modify the production data/results directories.
The temporary protocol and data are bound before fitting and destroyed on exit.
"""

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

import numpy as np
import torch

from . import train
from .task import make_dataset


def validate():
    torch.set_num_threads(1)
    original_root, original_protocol = train.ROOT, train.PROTOCOL
    filenames = ["train.py", "train_matrix.py", "models.py", "operators.py", "baselines.py", "task.py"]
    original_hashes = {name: train.sha256(original_root / name) for name in filenames}
    checks, results = [], {}
    with tempfile.TemporaryDirectory(prefix="rr-v4-development-train-") as directory:
        root = Path(directory)
        for name in filenames:
            shutil.copyfile(original_root / name, root / name)
        (root / "data").mkdir()
        before_data = {"scope": "DEVELOPMENT_ONLY", "total_unique_episodes": 4,
                       "seed": 840201, "created_at_utc": datetime.now(timezone.utc).isoformat(),
                       "source_sha256": original_hashes}
        train.atomic_json(root / "pre_data_freeze.json", before_data)
        _, arrays = make_dataset(4, 840201, "train")
        np.savez(root / "data" / "train.npz", **{k: v[:3] for k, v in arrays.items()})
        np.savez(root / "data" / "validation.npz", **{k: v[3:] for k, v in arrays.items()})
        train.atomic_json(root / "data" / "manifest.json", {"scope": "DEVELOPMENT_ONLY", "train": 3, "validation": 1})
        frozen = {name: train.sha256(root / name) for name in filenames+
                  ["pre_data_freeze.json", "data/train.npz", "data/validation.npz", "data/manifest.json"]}
        variants = ["rr_full", "lif", "alif", "resource_lif", "ctrnn", "ctrnn_state", "ctrnn_upper_state", "alif_analog", "ctrnn_analog"]
        protocol = {"scope": "DEVELOPMENT_ONLY", "seeds": [899101], "variants": variants,
                    "cpu_matched_variants": {"ctrnn_state_cpu": "ctrnn_state"},
                    "training": {"epochs": 2, "batch_size": 3, "learning_rate": .003,
                                 "clip_norm": 1., "validation_every": 1,
                                 "validation_draws": 4, "validation_seed": 840301,
                                 "train_episodes": 3, "validation_episodes": 1,
                                 "cpu_epoch_cap": 10000}, "frozen_files": frozen}
        train.atomic_json(root / "experiment_protocol.json", protocol)
        train.ROOT, train.PROTOCOL = root, root / "experiment_protocol.json"
        try:
            for variant in variants+["ctrnn_state_cpu"]:
                result = train.train_one(variant, 899101)
                assert result["status"] == "completed" and result["holdout_opened_by_training"] is False
                assert result["gradients_all_finite"]
                assert result["best_validation_nll"] <= result["initial_validation_nll"]
                results[variant] = {key: result[key] for key in (
                    "updates", "epochs", "initial_validation_nll", "best_validation_nll", "best_epoch",
                    "actual_training_internal_spikes", "per_parameter_gradient_norm_max_before_clip",
                    "nonzero_gradient_elements_seen", "cpu_budget_target_seconds",
                    "cpu_budget_overshoot_seconds", "train_cpu_seconds", "checkpoint_sha256")}
            checks.append({"name": "real_trainer_on_four_development_episodes", "passed": True, "runs": len(results)})
            target = results["rr_full"]["train_cpu_seconds"]
            control = results["ctrnn_state_cpu"]
            assert control["cpu_budget_target_seconds"] == target
            assert control["train_cpu_seconds"] >= target
            checks.append({"name": "paired_cpu_target_and_complete_epoch_stop", "passed": True,
                           "overshoot_seconds": control["cpu_budget_overshoot_seconds"]})
            path = root / "results" / "alif" / "seed_899101"
            before = torch.load(path / "model.pt", map_location="cpu", weights_only=False)["state_dict"]
            (path / "training.json").unlink()
            (path / "model.pt").unlink()
            resumed = train.train_one("alif", 899101)
            after = torch.load(path / "model.pt", map_location="cpu", weights_only=False)["state_dict"]
            assert resumed["resumed"] and resumed["updates"] == 2
            assert all(torch.equal(before[key], after[key]) for key in before)
            checks.append({"name": "resume_completed_epochs_without_retraining", "passed": True})
            receipt_path = root / "results" / "lif" / "seed_899101" / "training.json"
            original = json.loads(receipt_path.read_text())
            changed = copy.deepcopy(original)
            changed["seed"] = 899102
            train.atomic_json(receipt_path, changed)
            try:
                train.completed_receipt("lif", 899101, train.sha256(train.PROTOCOL))
            except RuntimeError:
                checks.append({"name": "wrong_seed_receipt_rejected", "passed": True})
            else:
                raise AssertionError("wrong-seed receipt accepted")
            train.atomic_json(receipt_path, original)
            frozen_path = root / "data" / "train.npz"
            bytes_before = frozen_path.read_bytes()
            frozen_path.write_bytes(bytes_before+b"changed")
            try:
                train.verify_protocol()
            except RuntimeError:
                checks.append({"name": "data_identity_drift_rejected_before_fit", "passed": True})
            else:
                raise AssertionError("changed data accepted")
            frozen_path.write_bytes(bytes_before)
            train.verify_protocol()
            retained_protocol = {"configuration": protocol, "sha256": train.sha256(train.PROTOCOL)}
        finally:
            train.ROOT, train.PROTOCOL = original_root, original_protocol
    assert original_hashes == {name: train.sha256(original_root / name) for name in filenames}
    return {"schema": "rr-v4-training-smoke-1", "allPassed": True, "checks": checks,
            "scope": {"developmentOnly": True, "uniqueEpisodes": 4, "trainEpisodes": 3,
                      "validationEpisodes": 1, "productionDataOpened": False, "holdoutOpened": False,
                      "taskSuperiorityClaim": False, "temporaryArtifactsRemoved": True},
            "protocol": retained_protocol, "results": results,
            "gradientInterpretation": "Elementwise training support is recorded; a zero derivative in one finite sample is not a dummy architecture parameter. Spiking surrogates are explicitly biased."}


if __name__ == "__main__":
    report = validate()
    destination = Path(__file__).with_name("training_smoke_results.json")
    train.atomic_json(destination, report)
    print(json.dumps({"allPassed": report["allPassed"], "checks": report["checks"],
                      "scope": report["scope"], "runs": list(report["results"])}))
