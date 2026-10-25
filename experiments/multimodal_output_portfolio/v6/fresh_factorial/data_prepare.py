"""Prepare label-separated source pairs only after audited protocol publication."""

import argparse
from dataclasses import replace
import json
from pathlib import Path

import numpy as np

from .io import (arrays, clock, cost, cpu_environment, digest, identity,
                               published_source, read_arrays, read_json, require_identity,
                               require_owner, run_stage, validate_data, write)


def planned_cases(plan, split_ids):
    """Identity-only selection; no outcome or target enters the range decision."""
    excluded = set(plan["exposed_source_pixels"])
    if len(excluded) < 360:
        raise ValueError("the audited prior exclusion census is incomplete")
    cases, used = [], set()
    for split in ("future", "retention"):
        selected = plan["case_ranges"][split]
        forbidden = plan["development_only_pair_ranges"][split]
        for ordinal in range(selected["count"]):
            index = selected["offset"] + ordinal
            if forbidden[0] <= index <= forbidden[1] or 2 * index + 1 >= len(split_ids[split]):
                raise ValueError("registered range touches development smoke or exceeds its source split")
            sources = list(split_ids[split][2 * index:2 * index + 2])
            pixels = {x.rsplit(":", 1)[-1] for x in sources}
            if len(pixels) != 2 or pixels & (excluded | used):
                raise ValueError("registered new range overlaps an old or repeated source; no fallback sampling")
            used.update(pixels)
            cases.append({"case_id": f"{split}-{index:04}", "split": split, "index": index,
                          "source_ids": sources, "corruption": plan["corruptions"][ordinal % 6]
                          if split == "future" else "clean"})
    reserved = {split: [identity for position, identity in enumerate(ids)
                       if identity.rsplit(":", 1)[-1] not in used | excluded
                       and not plan["development_only_pair_ranges"][split][0] <= position // 2
                       <= plan["development_only_pair_ranges"][split][1]]
                for split, ids in split_ids.items()}
    return cases, reserved


def case_batch(corpus, case):
    from ..data import Observation, make_batch
    corruption = case["corruption"]
    actual = "missing" if corruption in ("wrong_hint", "missing_no_hint") else corruption
    split = "test" if case["split"] == "future" else "retention"
    batch = make_batch(corpus, split, 1, 424242 + case["index"], actual, offset=case["index"],
                       drop_hint=corruption == "missing_no_hint")
    if corruption == "wrong_hint":
        tokens = batch.observation.text_tokens.clone()
        for position in (3, 5):
            if int(tokens[0, position]) >= 14:
                tokens[0, position] = 14 + (int(tokens[0, position]) - 14 + 1) % 10
        batch = replace(batch, observation=Observation(batch.observation.pixels, batch.observation.mask, tokens))
    if list(batch.source_ids[0]) != case["source_ids"]:
        raise ValueError("observation recipe source differs from preselected identity")
    return batch


def prepare(cache, protocol, source_commit, output):
    began = clock()
    plan = read_json(protocol)
    source = published_source(plan, source_commit, protocol)
    if (plan["status"] != "frozen_after_exposure_review_requires_publication_before_data"
            or not plan.get("exposure_review_canonical_sha256") or not plan.get("exposure_census_canonical_sha256")):
        raise ValueError("audited exposure review and resolved protocol are required")
    torch, environment = cpu_environment(plan)
    from ..data import load_corpus
    root, cache = require_owner(plan, output, "data"), Path(cache)
    root.mkdir(parents=True, exist_ok=False)
    for item in plan["source_files"]:
        require_identity(cache / item["name"], item)
    corpus = load_corpus(cache, evaluator_sources=10000)
    if corpus.manifest["manifest_sha256"] != plan["dataset_manifest_sha256"]:
        raise ValueError("original source split changed")
    cases, reserved = planned_cases(plan, {"future": corpus.splits["test"].ids,
                                         "retention": corpus.splits["retention"].ids})
    if len(cases) != 90:
        raise ValueError("registered final source census must contain 90 pairs")
    pixels, masks, tokens, targets, labels = [], [], [], [], []
    for case in cases:
        batch = case_batch(corpus, case)
        for container, value in ((pixels, batch.observation.pixels), (masks, batch.observation.mask),
                                 (tokens, batch.observation.text_tokens), (targets, batch.target.pixels),
                                 (labels, batch.target.labels)):
            container.append(value.numpy())
    train, observer = corpus.splits["train"], corpus.splits["evaluator"]
    final_pixels = {s.rsplit(":", 1)[-1] for c in cases for s in c["source_ids"]}
    if final_pixels & (set(train.pixel_hashes) | set(observer.pixel_hashes) | set(corpus.splits["validation"].pixel_hashes)):
        raise ValueError("new final sources overlap model training, observer training or historical validation")
    files = {
        "training.npz": arrays(root / "training.npz", images=train.images.numpy(), labels=train.labels.numpy()),
        "training-source.json": write(root / "training-source.json", {"source_ids": train.ids,
            "pixel_hashes": train.pixel_hashes, "dataset_manifest": corpus.manifest}),
        "observer-training.npz": arrays(root / "observer-training.npz", images=observer.images.numpy(), labels=observer.labels.numpy()),
        "observer-source.json": write(root / "observer-source.json", {"source_ids": observer.ids,
            "pixel_hashes": observer.pixel_hashes, "dataset_manifest_sha256": corpus.manifest["manifest_sha256"]}),
        "observations.npz": arrays(root / "observations.npz", pixels=np.concatenate(pixels),
            masks=np.concatenate(masks), tokens=np.concatenate(tokens)),
        "cases.json": write(root / "cases.json", {"cases": cases, "target_labels_emitted": False}),
        "reserved-sources.json": write(root / "reserved-sources.json", {"source_ids": reserved,
            "pixels_or_labels_emitted": False}),
        "final-targets.npz": arrays(root / "final-targets.npz", pixels=np.concatenate(targets), labels=np.concatenate(labels)),
    }
    receipt = {"schema": "hepta.ndu-fresh-factorial.prepared-data.v1", "protocol_canonical_sha256": digest(plan),
               "source": source, "source_count": len(cases), "source_pixels": 180,
               "exposed_source_pixel_count": len(plan["exposed_source_pixels"]),
               "reserved_source_pixels": {key: len(value) for key, value in reserved.items()},
               "files": files, "dataset_manifest_sha256": corpus.manifest["manifest_sha256"],
               "withheld_targets_parsed_after_write": False, "environment": environment,
               "cost": cost(began), "authority": "DENY_ALL", "production_authority": False}
    write(root / "data-receipt.json", receipt)
    return {key: receipt[key] for key in ("source_count", "source_pixels", "reserved_source_pixels", "cost")}


def training_corpus(data, plan, torch, include_observer=False):
    from ..data import SourceCorpus, SourceSplit
    validate_data(data, plan)
    root = Path(data)
    tensors = read_arrays(root / "training.npz", {"images", "labels"})
    source = read_json(root / "training-source.json")
    if (tensors["images"].shape != (10000, 1, 28, 28) or tensors["images"].dtype != np.uint8
            or tensors["labels"].shape != (10000,) or tensors["labels"].dtype.kind not in "iu"
            or len(source["source_ids"]) != 10000 or len(source["pixel_hashes"]) != 10000
            or source["dataset_manifest"]["manifest_sha256"] != plan["dataset_manifest_sha256"]):
        raise ValueError("prepared training-only source artifact differs")
    split = SourceSplit(torch.from_numpy(tensors["images"]), torch.from_numpy(tensors["labels"]),
                        tuple(source["source_ids"]), tuple(source["pixel_hashes"]))
    splits = {"train": split}
    if include_observer:
        values = read_arrays(root / "observer-training.npz", {"images", "labels"})
        provenance = read_json(root / "observer-source.json")
        if (values["images"].shape != (10000, 1, 28, 28) or values["images"].dtype != np.uint8
                or values["labels"].shape != (10000,) or values["labels"].dtype.kind not in "iu"
                or len(provenance["source_ids"]) != 10000 or len(provenance["pixel_hashes"]) != 10000
                or provenance["dataset_manifest_sha256"] != plan["dataset_manifest_sha256"]
                or set(provenance["pixel_hashes"]) & set(source["pixel_hashes"])):
            raise ValueError("fresh observer source pool differs or overlaps the base training pool")
        splits["evaluator"] = SourceSplit(torch.from_numpy(values["images"]), torch.from_numpy(values["labels"]),
            tuple(provenance["source_ids"]), tuple(provenance["pixel_hashes"]))
    return SourceCorpus(splits, source["dataset_manifest"])


def public_observations(data, plan):
    receipt, cases = validate_data(data, plan)
    values = read_arrays(Path(data) / "observations.npz", {"pixels", "masks", "tokens"})
    if (values["pixels"].shape != (90, 1, 28, 56) or values["pixels"].dtype != np.float32
            or values["masks"].shape != values["pixels"].shape or values["masks"].dtype != np.float32
            or values["tokens"].shape != (90, 8) or values["tokens"].dtype.kind not in "iu"
            or np.any(values["pixels"] < 0) or np.any(values["pixels"] > 1)
            or not set(np.unique(values["masks"]).tolist()).issubset({0.0, 1.0})):
        raise ValueError("prepared public observation dimensions or values differ")
    return receipt, cases, values


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("cache", "protocol", "source-commit", "output"):
        parser.add_argument("--" + name, required=True)
    print(json.dumps(run_stage(prepare, vars(parser.parse_args())), sort_keys=True))
