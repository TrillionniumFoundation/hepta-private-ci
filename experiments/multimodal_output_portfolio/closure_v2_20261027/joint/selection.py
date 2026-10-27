"""Actual-output validation, never audit-observer or new-test selection."""

from copy import deepcopy

import numpy as np
import torch

from ...v6.data import make_batch
from ...repair_20261026.joint.train import deploy
from ...continuation_20261027.joint.training import actual_utilities
from .actor import LatentActor, LatentSnapshot
from .protocol import PROTOCOL as P, checksum, write_json


def ce(values):
    z = -P["gamma"] * np.asarray(values, dtype=np.float64)
    maximum = z.max()
    return float(-(np.log(np.exp(z - maximum).mean()) + maximum) / P["gamma"])


@torch.inference_mode()
def validation(base, actor, corpus, reward, seed):
    result = {}
    for name, count, offset, conditions in (
            ("quality", P["validation_pairs"], 0, P["conditions"]),
            ("retention", P["validation_retention_pairs"], P["validation_retention_offset"], ["clean"])):
        values, hashes = [], []
        for ci, condition in enumerate(conditions):
            for start in range(0, count, 32):
                n = min(32, count - start)
                batch = make_batch(corpus, "validation", n, P["evaluation_seed"] + ci * 10000 + start,
                                   corruption=condition, offset=offset + start)
                rng = torch.Generator().manual_seed(seed * 100003 + start + ci * 1009)
                noise = torch.randn(n, base._base._model.hidden, generator=rng)
                residual_noise = torch.randn(n, P["dimensions"], generator=rng)
                if actor is None:
                    output, _ = deploy(base._base._model, base._gate, batch.observation, noise)
                else:
                    output, _, _ = actor.generate(batch.observation, noise, residual_noise)
                actual, image_hashes, captions = actual_utilities(output, batch.target, reward)
                values.extend(actual.tolist())
                hashes.extend({"image": h, "caption": c} for h, c in zip(image_hashes, captions))
        result[name] = {"ce": ce(values), "utilities": values, "outputs": hashes}
    return result


def select(base, basis, corpus, reward, seed, arm, training, directory):
    torch.manual_seed(seed * 73 + 19)
    zero = LatentSnapshot(base, LatentActor(4 * base._base._model.hidden, P["dimensions"], P["hidden"]),
                          basis, P["sigma"], {"step": 0, "arm": "noise_control"})
    original = validation(base, None, corpus, reward, seed)
    zero_scores = validation(base, zero, corpus, reward, seed)
    def eligible(scores):
        return scores["retention"]["ce"] >= original["retention"]["ce"] - P["validation_retention_tolerance"]
    candidates = [{"step": 0, "checkpoint": None, "eligible": eligible(zero_scores), "metrics": zero_scores}]
    chosen, model = candidates[0], zero
    for checkpoint in training["checkpoints"]:
        candidate_model = LatentSnapshot.load(directory / checkpoint["path"], base)
        metrics = validation(base, candidate_model, corpus, reward, seed)
        row = {"step": checkpoint["step"], "checkpoint": checkpoint["path"],
               "eligible": eligible(metrics), "metrics": metrics}
        candidates.append(row)
        if row["eligible"] and (not chosen["eligible"] or metrics["quality"]["ce"] > chosen["metrics"]["quality"]["ce"] + 1e-12):
            chosen, model = row, candidate_model
    path = directory / f"seed-{seed}-{arm}-selected.pt"
    model.save(path)
    record = {"seed": seed, "arm": arm, "selected_step": chosen["step"],
        "selected_eligible": chosen["eligible"], "selected_path": path.name,
        "selected_sha256": checksum(path), "selected_ce": {k: v["ce"] for k, v in chosen["metrics"].items()},
        "original_ce": {k: v["ce"] for k, v in original.items()},
        "noise_control_ce": {k: v["ce"] for k, v in zero_scores.items()},
        "candidates": candidates, "audit_or_new_test_used": False}
    write_json(directory / f"SELECTION-{seed}-{arm}.json", record)
    print(f"select direct seed={seed} arm={arm} step={chosen['step']} eligible={chosen['eligible']} CE={record['selected_ce']}", flush=True)
    return record
