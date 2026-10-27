"""Restore training identities and reserve unused official-test pixel sources."""

import gzip
import hashlib
import json
from pathlib import Path
import random

import torch

from ...v6.data import (Batch, Observation, SourceCorpus, SourceSplit, Target,
                       _parse_images, _parse_labels, load_corpus, make_batch)
from .protocol import PROTOCOL as P


def historical_corpus(assets):
    assets = Path(assets)
    corpus = load_corpus(assets / "ndu-data", evaluator_sources=10000)
    original = json.loads((assets / "ndu-runs/full-002/protocol.json").read_text())
    if corpus.manifest != original["dataset_manifest"]:
        raise ValueError("Original training/evaluator identities changed")
    return corpus


def fresh_corpus(assets, historical):
    assets = Path(assets)
    source = assets / "ndu-data"
    images, hashes = _parse_images(gzip.decompress((source / "t10k-images-idx3-ubyte.gz").read_bytes()))
    labels = _parse_labels(gzip.decompress((source / "t10k-labels-idx1-ubyte.gz").read_bytes()))
    excluded = {h for split in historical.splits.values() for h in split.pixel_hashes}
    original = json.loads((assets / "ndu-runs/full-002/protocol.json").read_text())
    excluded.update(original.get("prior_heldout_exclusion", {}).get("source_pixel_sha256", []))
    label_sets = {}
    for h, y in zip(hashes, labels.tolist()):
        label_sets.setdefault(h, set()).add(y)
    eligible, seen = [], set()
    for i, h in enumerate(hashes):
        if h not in excluded and h not in seen and len(label_sets[h]) == 1:
            eligible.append(i)
            seen.add(h)
    random.Random(P["fresh_source_seed"]).shuffle(eligible)
    need = 2 * (P["test_pairs"] + P["retention_pairs"])
    if len(eligible) < need:
        raise ValueError("Insufficient new source identities")
    splits, records, start = {}, {}, 0
    for name, count in (("test", P["test_pairs"]), ("retention", P["retention_pairs"])):
        indices = eligible[start:start + 2 * count]
        start += 2 * count
        ids = tuple(f"mnist:test:{i}:{hashes[i]}" for i in indices)
        hs = tuple(hashes[i] for i in indices)
        splits[name] = SourceSplit(images[indices].clone(), labels[indices].clone(), ids, hs)
        records[name] = {"sources": len(ids), "source_ids": ids,
                         "identity_sha256": hashlib.sha256("\n".join(ids).encode()).hexdigest()}
    if set(splits["test"].pixel_hashes) & set(splits["retention"].pixel_hashes):
        raise AssertionError("Qualification/retention source leakage")
    return SourceCorpus(splits, {"schema": "hepta.ndu.fresh-mnist-sources.v1",
        "historical_excluded_pixel_count": len(excluded), "eligible_sources": len(eligible),
        "fresh_source_seed": P["fresh_source_seed"], "splits": records,
        "writer_independence_established": False, "all_historical_global_usage_known": False})


def training_batch(corpus, seed, step):
    half = P["batch_size"] // 2
    batch_seed = seed * 1000003 + step * 17 + 270027
    clean = make_batch(corpus, "train", half, batch_seed, corruption="clean")
    stress = make_batch(corpus, "train", half, batch_seed + 1,
                        corruption=P["stress_cycle"][step % len(P["stress_cycle"])])
    observation = Observation(*(torch.cat((getattr(clean.observation, f), getattr(stress.observation, f)))
                                for f in ("pixels", "mask", "text_tokens")))
    target = Target(*(torch.cat((getattr(clean.target, f), getattr(stress.target, f)))
                      for f in ("pixels", "text_tokens", "labels")))
    return Batch(observation, target, clean.source_ids + stress.source_ids), batch_seed
