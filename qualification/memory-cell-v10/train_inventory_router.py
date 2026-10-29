"""Fit the native operation model using only predefined train/calibration text."""

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np

from cells import Cell, fit
from corpus import TEMPLATES
from export_native import canonical, sha
from inventory_worker import POLICY_FILES
from routing import CLASSES, calibrate, operation_scores


def train(encoder, destination, seed):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    datasets = {}
    for phase in ("train", "calibration"):
        rows = []
        for role, templates in TEMPLATES[phase].items():
            for text in templates:
                # Registry binding rejects unknown/ambiguous addresses separately.
                # Keep all operation-negative templates as negatives for this model.
                text = text.format(entity="ENTITY", workflow="WORKFLOW", second_entity="SECOND_ENTITY", unknown_entity="UNKNOWN_ENTITY")
                operation = {"skill": "procedure", "compose": "apply", "unknown": "reject"}.get(role, role)
                rows.append({"text": text, "operation": operation, "entity": None, "workflow": None})
        datasets[phase] = rows
    x = encoder.encode([row["text"] for row in datasets["train"]])
    y = np.eye(4, dtype=np.float32)[[CLASSES.index(row["operation"]) for row in datasets["train"]]]
    model = Cell(384, 4, 0, seed)
    schedule = np.random.default_rng(seed + 33000).integers(len(x), size=(800, 32), dtype=np.int64)
    receipt = fit(model, x, y, (("multiclass", 4),), schedule, lr=0.01,
                  source_ids=[sha(canonical(row)) for row in datasets["train"]], label="native-operation-router")
    calibration_features = encoder.encode([row["text"] for row in datasets["calibration"]])
    predictions = [{**row, "entity": None, "workflow": None} for row in operation_scores(model.forward(calibration_features))]
    selection = calibrate(predictions, datasets["calibration"])
    checkpoint = model.save(destination / "checkpoint", encoder_sha256=encoder.base_encoder_sha,
                            outputs=(("multiclass", 4),), extra={"not_a_memory_content_model": True})
    qualification = Path(__file__).resolve().parents[1]
    pins = {name: sha((qualification / name).read_bytes()) for name in POLICY_FILES}
    manifest = {"schema": "hepta.memory.v10.inventory-router.v1", "checkpoint": "checkpoint",
                "checkpoint_manifest_sha256": checkpoint["manifest_sha256"], "parameter_sha256": model.identity(),
                "encoder_sha256": encoder.base_encoder_sha, "threshold": selection["threshold"],
                "required_margin": selection["required_margin"], "output_classes": CLASSES,
                "normalization_profile": "unique owner registry matches replaced with ENTITY/WORKFLOW; no gold operation",
                "policy_files": pins, "policy_digest": sha(canonical(pins)),
                "seed": seed, "training_sha256": sha(canonical(datasets["train"])),
                "calibration_sha256": sha(canonical(datasets["calibration"])), "held_read": False}
    payload = canonical(manifest)
    (destination / "manifest.json").write_bytes(payload)
    (destination / "TRAINING.json").write_bytes(canonical({"fit": receipt, "selection": selection,
                                                           "datasets": datasets, "model_digest": sha(payload)}))
    np.save(destination / "schedule.npy", schedule, allow_pickle=False)
    np.savez_compressed(destination / "features.npz", train=x, calibration=calibration_features, targets=y)
    return {"model_dir": str(destination), "model_digest": sha(payload), "selection": selection, "fit": receipt}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encoder-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1741)
    args = parser.parse_args()
    path = Path(__file__).resolve().parents[1] / "memory-cell-adapters" / "encoder.py"
    spec = importlib.util.spec_from_file_location("router_pinned_encoder", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    print(json.dumps(train(module.PinnedMiniLMEncoder(args.encoder_dir), args.output, args.seed)))


if __name__ == "__main__":
    main()
