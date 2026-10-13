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
from experiments.shared_stem_cell.checkpoint_conversion import convert, digest_file

MODEL = "jhu-clsp/mmBERT-small"
DATASET = "fancyzhx/ag_news"



def publisher_file(path, sibling):
    """Check published LFS or Git-blob identity, not just a self-computed checksum."""
    raw_digest = digest_file(path)
    if path.stat().st_size != sibling.size:
        raise ValueError("publisher file size drift")
    lfs = getattr(sibling, "lfs", None)
    expected = lfs.get("sha256") if isinstance(lfs, dict) else getattr(lfs, "sha256", None)
    if lfs is not None:
        if not isinstance(expected, str) or raw_digest != expected:
            raise ValueError("publisher LFS content drift")
    else:
        expected = getattr(sibling, "blob_id", None)
        h = hashlib.sha1(b"blob " + str(path.stat().st_size).encode() + b"\0")
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024**2), b""):
                h.update(block)
        if not isinstance(expected, str) or h.hexdigest() != expected:
            raise ValueError("publisher Git content drift")
    return {"sha256": raw_digest, "publisher_digest": expected,
            "publisher_digest_kind": "lfs_sha256" if lfs is not None else "git_blob_sha1"}



def stage_model(root, model_id, revision, *, kind, allow_conversion=False):
    """Acquire exact public artifacts, then optionally convert an explicitly accepted bin."""
    from huggingface_hub import HfApi, snapshot_download
    info = HfApi().model_info(model_id, revision=revision, files_metadata=True)
    if info.sha != revision:
        raise ValueError("immutable model lookup drift")
    siblings = {item.rfilename: item for item in info.siblings}
    if len(siblings) != len(info.siblings):
        raise ValueError("duplicate publisher file name")
    safe = sorted(name for name in siblings if name.endswith(".safetensors"))
    names = [name for name in siblings if name.endswith((".json", ".txt", ".model")) or name == "README.md"]
    conversion = None
    if safe:
        names += safe
    else:
        if allow_conversion is not True or "pytorch_model.bin" not in siblings:
            raise ValueError("no safetensors; explicit separate weights-only conversion required")
        names.append("pytorch_model.bin")
    for name in names:
        path = Path(name)
        if path.is_absolute() or not path.parts or ".." in path.parts:
            raise ValueError("invalid public artifact path")
    # Do not start a multi-gigabyte or unbounded acquisition from a metadata guess.
    sizes = [siblings[name].size for name in names]
    if any(type(size) is not int or size < 0 for size in sizes) or sum(sizes) > 2 * 1024**3:
        raise ValueError("unknown or excessive public snapshot size")
    lfs = getattr(siblings.get("pytorch_model.bin"), "lfs", None)
    expected = (lfs.get("sha256") if isinstance(lfs, dict) else getattr(lfs, "sha256", None))
    if not safe and (not isinstance(expected, str) or len(expected) != 64):
        raise ValueError("publisher LFS SHA256 required before bin acquisition")
    write_once(root / "model-source.json", {"model_id": model_id, "revision": revision,
        "files": names, "declared_bytes": sum(sizes), "source_bin_sha256": expected if not safe else None,
        "conversion_explicitly_accepted": allow_conversion, "production_accepted": False})
    snapshot = Path(snapshot_download(model_id, revision=revision, allow_patterns=names,
                                     cache_dir=root / "download-cache"))
    model_dir = root / "model"
    model_dir.mkdir(exist_ok=False)
    verified = {}
    for name in names:
        if name == "pytorch_model.bin":
            continue
        source = snapshot / name
        target = model_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target, follow_symlinks=True)
        verified[name] = publisher_file(target, siblings[name])
    if not safe:
        # Preserve source separately; inference cannot discover or unpickle it.
        original = root / "source-weights.bin"
        shutil.copyfile(snapshot / "pytorch_model.bin", original, follow_symlinks=True)
        verified["pytorch_model.bin"] = publisher_file(original, siblings["pytorch_model.bin"])
        conversion = convert(original, expected, root / "conversion", accepted=allow_conversion)
        shutil.copyfile(root / "conversion/model.safetensors", model_dir / "model.safetensors")
    files = {p.relative_to(model_dir).as_posix(): digest_file(p)
             for p in sorted(model_dir.rglob("*")) if p.is_file()}
    write_once(root / "verified-publisher-files.json", verified)
    return {"path": "model", "kind": kind, "revision": revision, "files": files,
            "model_id": model_id, "conversion": conversion}


def main(root: Path, *, allow_conversion=False):
    import torch
    from datasets import load_dataset
    from huggingface_hub import HfApi

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
    model = stage_model(root, MODEL, model_info.sha, kind="masked_lm",
                        allow_conversion=allow_conversion)
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
        "export_frozen_features": True, "maximum_tokens": 512, "run_controls": True, "split_routing": "train_two_means", "measure_sharing": True, "measure_head_batch": True,
        "dataset": {"path": "dataset.jsonl", "sha256": sha(raw)},
        "model": model}
    write_once(root / "manifest.json", config)
    return run(root / "manifest.json", root / "execution")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-weights-only-conversion", action="store_true")
    args = parser.parse_args()
    main(args.output, allow_conversion=args.allow_weights_only_conversion)
