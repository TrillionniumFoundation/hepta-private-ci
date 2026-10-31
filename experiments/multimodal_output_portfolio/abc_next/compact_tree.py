"""Actual H2 candidate paths, with lossless binary-pixel and token evidence.

The closed local NPZ archive is reopened before offline outcome assignment.
Only current-public root/child features reach the separate control fitter.
This collector is for registered fit/selection/qualification sources, not test.
"""

from collections import Counter
import hashlib
from pathlib import Path
import time

import numpy as np
import torch

from ..abc_recovery.base_recovery import file_sha, write_json
from ..abc_recovery.emission import output_digests
from ..abc_recovery.runtime import initialize, public_frame, transition
from ..abc_recovery.trees import METRICS, PLANS, _source_identity, stable_seed
from ..v6.data import Observation, Target, render_tokens
from ..v6.neural import parameter_hash
from ..v6.observer import observe_tensors
from ..v7.data import VIEWS, make_batch
from .observability import input_evidence, observed_features


ALLOWED = {"forecast_fit": (480, 256), "forecast_calibration": (448, 128),
           "development": (896, 104)}


def paired_batch(corpus, role, start, count, scenarios, view):
    batch = make_batch(corpus, role, count, stable_seed("abc-next-observation", role, start),
                       view=view, offset=start)
    observation = Observation(*(x.repeat_interleave(scenarios, 0) for x in
                                (batch.observation.pixels, batch.observation.mask, batch.observation.text_tokens)))
    target = Target(*(x.repeat_interleave(scenarios, 0) for x in
                      (batch.target.pixels, batch.target.text_tokens, batch.target.labels)))
    return batch, observation, target


def owner_rng(role, start, training_seed, view, path):
    # Deliberately omit training arm and controller: paired owner-side streams.
    return torch.Generator().manual_seed(stable_seed("abc-next-generation", role, start, training_seed, view, path))


def encode_media(pixels, tokens):
    hashes = output_digests(pixels, tokens)
    binary = pixels.to(torch.uint8).numpy().reshape(len(pixels), -1)
    return np.packbits(binary, axis=1), tokens.numpy().astype(np.uint8), np.array(hashes, dtype="S64")


def decode_media(bits, tokens, hashes):
    pixels = torch.from_numpy(np.unpackbits(bits, axis=1, count=1568).copy()).reshape(-1, 1, 28, 56).float()
    tokens = torch.from_numpy(tokens.astype(np.int64))
    if tuple(x.decode() for x in hashes) != output_digests(pixels, tokens):
        raise ValueError("Persisted actual pixel/token identity differs")
    captions = [render_tokens(row) for row in tokens.tolist()]
    return pixels, tokens, captions


def scores(observers, pixels, captions, target):
    result = {}
    for name, observer in observers.items():
        rows = observe_tensors(observer, pixels, captions, target.pixels, target.labels)
        for caption, row in zip(captions, rows):
            row["joint_fact_correct"] = bool(row["caption_valid"] and all(row[key] == 0 for key in
                                           ("text_fact", "relation", "image_fact", "crossmodal_disagreement")))
            row["required_output_complete"] = bool(caption.strip())
        result[name] = {metric: torch.tensor([r[metric] for r in rows], dtype=torch.float32) for metric in METRICS}
    return result


@torch.inference_mode()
def collect(snapshot, sensor, corpus, observers, outdir, *, role, start, count, scenarios, training_seed):
    if ALLOWED.get(role) != (start, count) or scenarios != 2:
        raise ValueError("Only the newly registered development cohorts are permitted")
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    snapshot.verify_integrity()
    identity = _source_identity(corpus, role, start, count)
    observer_hash = {name: parameter_hash(value) for name, value in observers.items()}
    sensor_hash = parameter_hash(sensor)
    model = snapshot._model
    registration = {"schema": "hepta.abc-next.compact-tree-registration.v1", "unix_ns": time.time_ns(),
                    "role": role, "start": start, "count": count, "scenarios": scenarios,
                    "training_seed": training_seed, "model_sha256": snapshot.fingerprint,
                    "source_identity": identity, "observers_sha256": observer_hash, "sensor_sha256": sensor_hash,
                    "entrypoint_sha256": file_sha(Path(__file__)), "plans": PLANS,
                    "raw_format": "NPZ packbits lossless actual Bernoulli pixels, actual AR uint8 tokens and per-output SHA256",
                    "private_targets_are_offline_only": True, "features_expose_grandchildren": False}
    write_json(outdir / "registration.json", registration)
    data = {"role": role, "pair_start": start, "pair_count": count, "scenarios_per_source": scenarios,
            "training_seed": training_seed, "plans": list(PLANS), "features": [], "cases": [],
            "views": [], "scenarios": [], "source_ids": [],
            "source_identity": identity,
            "metrics": {name: {metric: [] for metric in METRICS} for name in observers}}
    work, feature_work, archive_hash = Counter(), Counter(), {}
    node_count = 0
    for view in VIEWS:
        batch, observation, target = paired_batch(corpus, role, start, count, scenarios, view)
        evidence = input_evidence(sensor, observation, feature_work)
        states, public, bit_rows, token_rows, hash_rows, ledgers = {}, [], [], [], [], []
        for index, plan in enumerate(PLANS):
            rng = owner_rng(role, start, training_seed, view, plan)
            if not plan:
                run = initialize(model, observation, generator=rng)
                edge_start = 0
            else:
                parent = states[plan[:-1]]
                edge_start = len(parent.ledger)
                run = transition(model, parent, plan[-1], generator=rng)
            new_ledger = run.ledger[edge_start:]
            for entry in new_ledger:
                work.update(entry.get("work", {}))
            ledgers.append({"plan_index": index, "incremental_ledger": new_ledger})
            if len(plan) < 2:
                states[plan] = run
                public.append(observed_features(model, public_frame(run), sensor=sensor,
                                                evidence=evidence, work=feature_work))
            bits, tokens, hashes = encode_media(run.pixels, run.tokens)
            bit_rows.append(bits)
            token_rows.append(tokens)
            hash_rows.append(hashes)
            node_count += len(run.pixels)
        archive_path = outdir / f"{view}.npz"
        with archive_path.open("xb") as stream:
            np.savez_compressed(stream, pixels_bits=np.stack(bit_rows), tokens=np.stack(token_rows),
                                output_sha256=np.stack(hash_rows))
        archive_hash[archive_path.name] = file_sha(archive_path)
        write_json(outdir / f"{view}.ledger.json", {"nodes": ledgers, "ancestor_work_counted_once": True})
        view_metrics = {name: {metric: [] for metric in METRICS} for name in observers}
        with np.load(archive_path, allow_pickle=False) as saved:
            saved_bits, saved_tokens, saved_hashes = saved["pixels_bits"], saved["tokens"], saved["output_sha256"]
            for index in range(len(PLANS)):
                pixels, _, captions = decode_media(saved_bits[index], saved_tokens[index], saved_hashes[index])
                values = scores(observers, pixels, captions, target)
                for name in observers:
                    for metric in METRICS:
                        view_metrics[name][metric].append(values[name][metric])
        for name in observers:
            for metric in METRICS:
                data["metrics"][name][metric].append(torch.stack(view_metrics[name][metric], 1))
        data["features"].append(torch.stack(public, 1))
        for case in range(count):
            for scenario in range(scenarios):
                data["cases"].append(start + case)
                data["views"].append(view)
                data["scenarios"].append(scenario)
                data["source_ids"].append(batch.source_ids[case])
    data["features"] = torch.cat(data["features"])
    for name in observers:
        for metric in METRICS:
            data["metrics"][name][metric] = torch.cat(data["metrics"][name][metric])
    if data["features"].shape != (8 * count * scenarios, 5, 763):
        raise ValueError("Public feature census differs")
    if not torch.equal(data["features"][:, :, -1], torch.tensor([1., .5, .5, .5, .5]).expand(len(data["cases"]), 5)):
        raise ValueError("Public horizon feature differs")
    snapshot.verify_integrity()
    if sensor_hash != parameter_hash(sensor) or observer_hash != {k: parameter_hash(v) for k, v in observers.items()}:
        raise ValueError("Frozen readers or outcome observers changed")
    with (outdir / "data.pt").open("xb") as stream:
        torch.save(data, stream)
    write_json(outdir / "summary.json", {
        "schema": "hepta.abc-next.compact-tree-result.v1", "status": "completed",
        "registration_sha256": file_sha(outdir / "registration.json"), "data_sha256": file_sha(outdir / "data.pt"),
        "node_rows": node_count, "independent_source_pairs": count, "views": list(VIEWS),
        "scenarios_per_source": scenarios, "archives_sha256": archive_hash,
        "all_saved_media_reopened_and_hash_verified": True, "outcomes_scored_after_reopen": True,
        "generation_work": dict(work), "feature_work": dict(feature_work),
        "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
        "timer_scope": "collector entry through generation, persistence, reopening, scoring, data save and integrity checks"})
    return data
