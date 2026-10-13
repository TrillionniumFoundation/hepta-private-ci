"""Opt-in PUBLIC pretrained/data execution, never independent future evidence.

Network acquisition is isolated here; execution.py remains local-only. Resolve
immutable Hub revisions and seal them before downloading any weights/data.
This narrow public smoke is not a Laya comparison or a model-selection gate.
"""
import argparse
import hashlib
from pathlib import Path
import shutil

from experiments.shared_stem_cell.execution import canonical, run, sha, write_once

MODEL = "jhu-clsp/mmBERT-small"
DATASET = "fancyzhx/ag_news"


def main(root: Path):
    import torch
    from datasets import load_dataset
    from huggingface_hub import HfApi, snapshot_download

    root.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(2)
    api = HfApi()
    model_info, data_info = api.model_info(MODEL), api.dataset_info(DATASET)
    revisions = {"model_id": MODEL, "model_revision": model_info.sha,
                 "dataset_id": DATASET, "dataset_revision": data_info.sha}
    for key in ("model_revision", "dataset_revision"):
        value = revisions[key]
        if not isinstance(value, str) or len(value) != 40 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("Hub did not return an immutable revision")
    write_once(root / "acquisition.json", {**revisions,
        "origin": "public_release", "temporal_evidence": False,
        "group_definition": "record_identity_not_validated_independent_source_family",
        "eligibility": "nonempty UTF-8 text <= 768 bytes; exact-content dedup before label access",
        "selection": "SHA256 text order; 64 train, 32 calibration, 32 test",
        "independent_evaluation": False, "production_accepted": False})
    snapshot = Path(snapshot_download(MODEL, revision=model_info.sha,
        allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "README.md"],
        cache_dir=root / "download-cache"))
    # Copy to ordinary immutable input files; execution never follows Hub symlinks.
    model_dir = root / "model"
    shutil.copytree(snapshot, model_dir, symlinks=False)
    files = {}
    for path in sorted(model_dir.rglob("*")):
        if path.is_file():
            h = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024**2), b""):
                    h.update(block)
            files[path.relative_to(model_dir).as_posix()] = h.hexdigest()
    # Datasets 4.x rejects executable dataset scripts; this repository is Parquet.
    selected, seen = {}, set()
    for original_split in ("train", "test"):
        source = load_dataset(DATASET, revision=data_info.sha, split=original_split,
                              cache_dir=str(root / "dataset-cache"))
        eligible = []
        for index, text in enumerate(source["text"]):
            if isinstance(text, str) and 0 < len(text.encode()) <= 768:
                eligible.append((sha(text.encode()), index))
        picked = []
        limit = 96 if original_split == "train" else 32
        for fingerprint, index in sorted(eligible):
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            picked.append((index, source[index]))
            if len(picked) == limit:
                break
        if len(picked) != limit:
            raise ValueError("insufficient preregistered eligible public records")
        selected[original_split] = picked
    rows = []
    for source_split, samples in selected.items():
        for position, (index, row) in enumerate(samples):
            split = ("train" if position < 64 else "calibration") if source_split == "train" else "holdout"
            identity = f"ag-news:{source_split}:{index}"
            rows.append({"case_id": identity, "group": identity, "split": split,
                         "observed_at": None, "cell": position % 2,
                         "scope": "public-ag-news-research", "text": row["text"], "label": int(row["label"])})
    raw = b"".join(canonical(row) for row in rows)
    with (root / "dataset.jsonl").open("xb") as stream:
        stream.write(raw)
    config = {"schema": "hepta.shared-stem-execution.v1", "classes": 4, "cells": 2,
        "temporal": False, "steps": 20, "seed": 20261013, "batch_size": 8,
        "maximum_tokens": 512, "run_controls": True, "measure_sharing": True,
        "dataset": {"path": "dataset.jsonl", "sha256": sha(raw)},
        "model": {"path": "model", "kind": "masked_lm", "revision": model_info.sha, "files": files}}
    write_once(root / "manifest.json", config)
    return run(root / "manifest.json", root / "execution")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args().output)
