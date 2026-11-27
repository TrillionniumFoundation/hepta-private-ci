"""Fit small decoder Cells using only the frozen cohort's training split."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from backend import FlorenceBackend
from cells import FourCells, target_text, token_roles
from cohort import iter_pairs, validate_splits


def prepare(model_path, cohort_dir, output_dir, epochs=15):
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    validate_splits(cohort_dir)
    pairs = list(iter_pairs(cohort_dir, "train"))
    backend = FlorenceBackend(model_path)
    boundaries = sorted(set((backend.tokenizer.bos_token_id, backend.eos_token_id,
                             backend.tokenizer.pad_token_id)))
    vocabulary = set(backend.location_token_ids + boundaries)
    for _, reference in pairs:
        vocabulary.update(backend.tokenizer.encode(target_text(reference), add_special_tokens=True))
    vocabulary = sorted(vocabulary)
    arrays = {key: [] for key in ("hidden", "logits", "full_logsumexp", "target_ids", "roles")}
    receipts, started = [], time.perf_counter()
    for index, (observation, reference) in enumerate(pairs):
        encoded = backend.encode(observation)
        feature = backend.teacher_forced_features(encoded, target_text(reference), vocabulary)
        for key in ("hidden", "logits", "full_logsumexp", "target_ids"):
            arrays[key].append(feature[key].detach().cpu().numpy())
        arrays["roles"].append(np.asarray(token_roles(feature["target_ids"], backend.location_token_ids, boundaries)))
        receipts.append({"task_id": observation["task_id"], "source_id": reference["source_id"],
                         "image_sha256": observation["image_sha256"], "tokens": len(feature["target_ids"]),
                         "costs": feature["costs"]})
        if (index + 1) % 8 == 0:
            print(json.dumps({"phase": "train_features", "completed": index + 1, "total": len(pairs)}), flush=True)
    bank = {key: np.concatenate(values) for key, values in arrays.items()}
    np.savez_compressed(output / "train-features.npz", **bank)
    torch.manual_seed(23)
    cells = FourCells(backend.hidden_size, vocabulary, backend.location_token_ids, boundaries)
    training = cells.fit(bank, epochs=epochs)
    digest = cells.save(output / "cells.pt")
    identity = backend.frozen_receipt()
    receipt = {"schema": "hepta.ndu-cell-training.v1", "split": "train", "sources": len(pairs),
               "cohort_manifest_sha256": hashlib.sha256((Path(cohort_dir) / "manifest.json").read_bytes()).hexdigest(),
               "cells_sha256": digest, "cell_names": ["semantic", "horizontal", "vertical", "completion"],
               "scope": "four sparse logit adapters; not four modality generators", "training": training,
               "seconds": time.perf_counter() - started, "base_identity": identity,
               "feature_receipts": receipts}
    (output / "cell-training.json").write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"phase": "cells_fitted", "sources": len(pairs), "losses": training["losses"], "frozen": identity}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--cohort", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--epochs", type=int, default=15)
    args = parser.parse_args()
    prepare(args.model, args.cohort, args.output, args.epochs)


if __name__ == "__main__":
    main()
