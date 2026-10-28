"""Predeclared bounded full-path study; no qualification-driven retuning."""

from dataclasses import replace
import gzip
import hashlib
import json
from pathlib import Path
import random

from ..v6.data import SourceCorpus, SourceSplit, _parse_images, _parse_labels
from ..v6.observer import METRIC
from ..continuation_20261027.joint.data import historical_corpus, fresh_corpus
from ..closure_v2_20261027.allocate_admission_sources import source_ids
from .generator import EMISSION, RATES, STAGES, file_sha
from .profile import NduProfile, digest


P = {"schema": "hepta.ndu.fullpath-study.v1", "training_seeds": [17, 29, 43],
     "reference_checkpoint_sha256": "508931a0cb780d413bc39de83b8de91aeab68b33cfe1b384f176cb8e8f004ee6",
     "reference_training_seed": 17, "independent_base_initializations": 1,
     "arms": ["fullpath_mean", "fullpath_risk"],
     "conditions": ["clean", "occlusion", "missing", "heavy_noise"],
     "steps_per_stage": 80, "batch_size": 12, "emissions_per_context": 4,
     "learning_rate": .000005, "gradient_clip": 5., "threads": 2,
     "qualification_pairs": 128, "retention_pairs": 64,
     "qualification_emissions": 4, "validation_pairs": 32,
     "validation_retention_pairs": 32, "retention_tolerance": .005,
     "validation_selection": "max population CE among retention-eligible stage checkpoints and exact prior fallback",
     "stages": STAGES, "emission": EMISSION, "tariffs": RATES,
     "primary_profile": "population gamma=2", "mean_control_profile": "population gamma=0",
     "primary_observer": "same frozen reward observer throughout development and qualification",
     "audit_observer": "separately reported sensitivity; never the optimized objective or model selector",
     "train_budget": "both objective arms execute every stage even when selected model falls back",
     "confidence": "paired original-source-pair bootstrap; seed-average paired estimates, not independent seed trials",
     "qualification_access": "after complete frozen development selections only",
     "compute_cost": "registered per-episode work tariffs; actual wall and CPU measured separately, not currency",
     "global_optimizer_claim": False, "native_continuation_training": False}


def write_json(path, value, exclusive=False):
    with Path(path).open("x" if exclusive else "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def profiles(observer_file):
    here = Path(__file__).parent
    observer_spec = {"weights_file_sha256": file_sha(observer_file), "metric": METRIC,
                     "observer_code_sha256": file_sha(here.parent / "v6/observer.py")}
    continuation = {"horizon": 2, "stop": "after actual PNG and UTF8 readback",
                    "plan_selection": "original frozen encoder/gate, current generator has no plan boundary derivative",
                    "reference_checkpoint_sha256": P["reference_checkpoint_sha256"],
                    "policy_class": "fixed prior plan selection plus trainable neural emission or exact deterministic prior fallback",
                    "emission_modes": {"fullpath_stochastic": EMISSION,
                        "prior_deterministic": {"image": "sigmoid_mean_then_uint8",
                            "text": "greedy_fixed_horizon_then_render",
                            "allowed_parameters": P["reference_checkpoint_sha256"]}},
                    "policy_binding": "each evaluation binds model parameter hash, reference snapshot and explicit emission mode",
                    "tariffs": RATES,
                    "generator_source_sha256": file_sha(here / "generator.py"),
                    "native_runtime": False}
    objective = {"metric": METRIC, "task_conditions": P["conditions"],
                 "condition_weights": [.25] * 4, "retention": "external hard checkpoint gate",
                 "cost": "terminal gross utility minus all declared per-trajectory work tariffs"}
    primary = NduProfile(digest(objective), digest(observer_spec), digest(continuation))
    return primary, replace(primary, gamma=0.), {"objective": objective,
           "observer": observer_spec, "continuation": continuation}


def allocate(assets, output):
    historical = historical_corpus(assets)
    old_fresh = fresh_corpus(assets, historical)
    excluded = {h for c in (historical, old_fresh) for s in c.splits.values() for h in s.pixel_hashes}
    original = json.loads((assets / "ndu-runs/full-002/protocol.json").read_text())
    excluded.update(original.get("prior_heldout_exclusion", {}).get("source_pixel_sha256", []))
    prior = Path(__file__).parent.parent / "closure_v2_20261027"
    pins = {}
    for name in ("SOURCE_ALLOCATION.json", "CONTROL_ADMISSION_SOURCE_ALLOCATION.json"):
        path = prior / name
        document = json.loads(path.read_bytes())
        excluded.update(identity.rsplit(":", 1)[1] for identity in source_ids(document))
        pins[name] = file_sha(path)
    source = assets / "ndu-data"
    image_path, label_path = source / "t10k-images-idx3-ubyte.gz", source / "t10k-labels-idx1-ubyte.gz"
    images, hashes = _parse_images(gzip.decompress(image_path.read_bytes()))
    labels = _parse_labels(gzip.decompress(label_path.read_bytes()))
    eligible, seen = [], set()
    for index, sha in enumerate(hashes):
        if sha not in excluded and sha not in seen:
            eligible.append(index)
            seen.add(sha)
    random.Random(281052901).shuffle(eligible)
    need = 2 * (P["qualification_pairs"] + P["retention_pairs"])
    if len(eligible) < need:
        raise ValueError("Fresh source pool exhausted; do not reuse seen qualification sources")
    splits, start = {}, 0
    for name, count in (("test", P["qualification_pairs"]), ("retention", P["retention_pairs"])):
        ids = eligible[start:start + 2 * count]
        start += 2 * count
        splits[name] = {"source_ids": [f"mnist:test:{i}:{hashes[i]}" for i in ids]}
    record = {"schema": "hepta.ndu.fullpath-sources.v1", "splits": splits,
              "official_image_sha256": file_sha(image_path), "official_label_sha256": file_sha(label_path),
              "prior_allocation_pins": pins, "eligible_before": len(eligible),
              "remaining": len(eligible) - need, "new_test_predictions": 0,
              "writer_independence_established": False,
              "historical_global_usage_known": False, "selection_uses_labels": False}
    write_json(output, record, exclusive=True)
    return historical


def qualification_corpus(assets, allocation):
    record = json.loads(Path(allocation).read_text())
    source = Path(assets) / "ndu-data"
    image_path, label_path = source / "t10k-images-idx3-ubyte.gz", source / "t10k-labels-idx1-ubyte.gz"
    if (file_sha(image_path) != record["official_image_sha256"]
            or file_sha(label_path) != record["official_label_sha256"]):
        raise ValueError("Official evaluation image/label identity changed")
    images, hashes = _parse_images(gzip.decompress(image_path.read_bytes()))
    labels = _parse_labels(gzip.decompress(label_path.read_bytes()))
    splits, used = {}, set()
    for name, group in record["splits"].items():
        ids = group["source_ids"]
        indices = [int(i.split(":")[2]) for i in ids]
        hs = tuple(hashes[i] for i in indices)
        if len(set(hs)) != len(hs) or used.intersection(hs):
            raise ValueError("Repeated qualification source")
        if any(identity != f"mnist:test:{index}:{sha}" for identity, index, sha in zip(ids, indices, hs)):
            raise ValueError("Source identity changed")
        used.update(hs)
        splits[name] = SourceSplit(images[indices].clone(), labels[indices].clone(), tuple(ids), hs)
    return SourceCorpus(splits, record)
