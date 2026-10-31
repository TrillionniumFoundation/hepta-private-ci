"""Private evaluation of actual delivered bytes, paired by source, never routing."""

import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from ...v6.data import make_batch, render_tokens
from ...v6.neural import parameter_hash
from ...v6.observer import observe_tensors, read_bundle, write_bundle
from .protocol import PROTOCOL as P
from .train import deploy


def evaluate(snapshot, corpus, observers, seed, arm, output):
    root = Path(output) / "outputs" / f"{seed}-{arm}"
    model, gate = snapshot._base._model, snapshot._gate
    initial = parameter_hash(model), parameter_hash(gate)
    rows = []
    for split, count, offset, conditions in (
        ("test", P["test_pairs"], P["test_offset"], P["test_corruptions"]),
        ("retention", P["retention_pairs"], P["retention_offset"], ["clean"])):
        for condition_index, corruption in enumerate(conditions):
            for start in range(0, count, 16):
                size = min(16, count - start)
                batch = make_batch(corpus, split, size, P["evaluation_seed"] + start + condition_index * 10000,
                                   corruption=corruption, offset=offset + start)
                rng = torch.Generator().manual_seed(seed * 100003 + start + condition_index * 1009)
                noise = torch.randn(size, model.hidden, generator=rng)
                before_wall, before_cpu = time.perf_counter_ns(), time.process_time_ns()
                with torch.inference_mode():
                    generated, choices = deploy(model, gate, batch.observation, noise)
                inference_cpu, inference_wall = time.process_time_ns() - before_cpu, time.perf_counter_ns() - before_wall
                decoded, captions, receipts = [], [], []
                io_started = time.perf_counter_ns()
                for j in range(size):
                    caption = render_tokens(generated.token_ids[j])
                    paths = write_bundle(root / split / corruption / str(start + j), caption,
                                         generated.image_logits[j].sigmoid())
                    pixels, restored_caption, hashes = read_bundle(paths)
                    decoded.append(pixels)
                    captions.append(restored_caption)
                    receipts.append({"paths": {k: str(Path(v).relative_to(output)) for k, v in paths.items()},
                                     "sha256": hashes})
                codec_wall = time.perf_counter_ns() - io_started
                pixels = torch.cat(decoded)
                scored = {name: observe_tensors(observer, pixels, captions, batch.target.pixels,
                                               batch.target.labels) for name, observer in observers.items()}
                for j in range(size):
                    rows.append({"seed": seed, "arm": arm, "split": split, "corruption": corruption,
                                 "pair": start + j, "source_ids": batch.source_ids[j],
                                 "plan": int(choices[j]), "caption": captions[j], "private_labels": batch.target.labels[j].tolist(),
                                 "audit": scored["audit"][j], "reward": scored["reward"][j], "artifacts": receipts[j],
                                 "batch_size": size, "inference_cpu_ns_per_example": inference_cpu / size,
                                 "inference_wall_ns_per_example": inference_wall / size,
                                 "codec_wall_ns_per_example": codec_wall / size,
                                 "logical_budget": {"encoders": 1, "plan_gate": 1, "transitions": 2, "decoders": 1}})
    if initial != (parameter_hash(model), parameter_hash(gate)):
        raise RuntimeError("Evaluation mutated its inference snapshot")
    return rows


def ce(values, gamma=2.):
    # Values indexed by the fixed training seeds, independent source pairs and
    # repeated corruptions. Report the mean of per-seed empirical CEs.
    z = -gamma * np.asarray(values)
    maximum = z.max(axis=(1, 2), keepdims=True)
    return float(np.mean(-(np.log(np.exp(z - maximum).mean(axis=(1, 2)))
                           + maximum[:, 0, 0]) / gamma))


def analyze(rows):
    tables = {}
    for split, count, conditions in (("test", P["test_pairs"], P["test_corruptions"]),
                                      ("retention", P["retention_pairs"], ["clean"])):
        for arm in P["arms"]:
            table = np.full((len(P["seeds"]), count, len(conditions)), np.nan)
            selected = [row for row in rows if row["split"] == split and row["arm"] == arm]
            for row in selected:
                idx = (P["seeds"].index(row["seed"]), row["pair"], conditions.index(row["corruption"]))
                if not np.isnan(table[idx]):
                    raise ValueError("Duplicate evaluation observation")
                table[idx] = row["audit"]["utility"]
            if not np.isfinite(table).all():
                raise ValueError("Incomplete evaluation grid")
            tables[split, arm] = table
    rng = np.random.default_rng(P["bootstrap_seed"])
    reports = []
    for split in ("test", "retention"):
        for baseline in ("frozen", "joint_mean"):
            candidate, control = tables[split, "joint_entropic"], tables[split, baseline]
            count = candidate.shape[1]
            differences = []
            for _ in range(P["bootstrap_samples"]):
                indices = rng.integers(count, size=count)
                differences.append(ce(candidate[:, indices]) - ce(control[:, indices]))
            interval = np.quantile(differences, [.0125, .9875]).tolist()
            reports.append({"split": split, "comparison": "joint_entropic-" + baseline,
                            "ce_difference": ce(candidate) - ce(control), "paired_97_5_interval": interval,
                            "per_seed_ce_differences": [ce(a[None]) - ce(b[None]) for a, b in zip(candidate, control)],
                            "independent_source_pairs": count, "fixed_training_seeds": P["seeds"]})
    primary = [r for r in reports if r["split"] == "test"]
    retention = [r for r in reports if r["split"] == "retention"]
    passed = (all(r["paired_97_5_interval"][0] > 0 and min(r["per_seed_ce_differences"]) > 0 for r in primary)
              and all(r["paired_97_5_interval"][0] >= -P["retention_noninferiority_margin"] for r in retention))
    summaries = {}
    for (split, arm), values in tables.items():
        subset = [r for r in rows if r["split"] == split and r["arm"] == arm]
        summaries[f"{split}/{arm}"] = {"audit_ce": ce(values), "mean_audit_utility": float(values.mean()),
             "mean_reward_utility": float(np.mean([r["reward"]["utility"] for r in subset])),
             "lower_decile_mean_utility": float(np.sort(values.ravel())[:int(values.size * .1)].mean()),
             "mean_inference_cpu_ms_per_example": float(np.mean([r["inference_cpu_ns_per_example"] for r in subset]) / 1e6),
             "mean_inference_wall_ms_per_example": float(np.mean([r["inference_wall_ns_per_example"] for r in subset]) / 1e6),
             "plan_counts": np.bincount([r["plan"] for r in subset], minlength=4).tolist()}
    return {"schema": "hepta.ndu.repair-joint-actual-results.v1", "summaries": summaries,
            "comparisons": reports, "registered_acceptance_passed": passed,
            "raw_deliveries": len(rows), "raw_files": 2 * len(rows),
            "source_manifest_verified": True, "historical_public_source_development": True,
            "fresh_population_confirmation": False, "audit_observer_independent_parameters": True,
            "native_owner_integrated": False, "natural_audio_video_generation": False,
            "timing_scope": "amortized batches of 16; codec and private audit excluded from inference; descriptive host measurement"}


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def checksum(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()
