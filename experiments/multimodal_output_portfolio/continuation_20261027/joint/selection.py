"""Validation-only model selection using actual post-codec observations."""

from copy import deepcopy

import numpy as np
import torch

from ...v6.data import make_batch
from ...v6.neural import snapshot_from_model
from ...v6.plan_training import ControlledSnapshot
from ...repair_20261026.joint.train import deploy
from .protocol import PROTOCOL as P, checksum, write_json
from .training import actual_utilities


def ce(values):
    z = -P["gamma"] * np.asarray(values, dtype=np.float64)
    shift = z.max()
    return float(-(np.log(np.exp(z - shift).mean()) + shift) / P["gamma"])


def interpolate(original, updated, alpha):
    model, gate = deepcopy(original._base._model), deepcopy(original._gate)
    for target, teacher, trained in ((model, original._base._model, updated._base._model),
                                      (gate, original._gate, updated._gate)):
        state = {name: torch.lerp(value, trained.state_dict()[name], alpha)
                 for name, value in teacher.state_dict().items()}
        target.load_state_dict(state)
    return ControlledSnapshot(snapshot_from_model(model, {"parameter_interpolation": alpha}), gate)


@torch.inference_mode()
def validation(snapshot, corpus, observer, seed):
    model, gate = snapshot._base._model, snapshot._gate
    reports = {}
    for scope, count, offset, conditions in (
        ("quality", P["validation_pairs"], 0, P["conditions"]),
        ("retention", P["validation_retention_pairs"], P["validation_retention_offset"], ["clean"])):
        values, hashes = [], []
        for k, condition in enumerate(conditions):
            for start in range(0, count, 32):
                n = min(32, count - start)
                b = make_batch(corpus, "validation", n, P["evaluation_seed"] + start + k * 10000,
                               corruption=condition, offset=offset + start)
                rng = torch.Generator().manual_seed(seed * 100003 + start + k * 1009)
                output, _ = deploy(model, gate, b.observation, torch.randn(n, model.hidden, generator=rng))
                actual, image_hashes, captions = actual_utilities(output, b.target, observer)
                values.extend(actual.tolist())
                hashes.extend({"image": h, "caption": c} for h, c in zip(image_hashes, captions))
        reports[scope] = {"ce": ce(values), "actual_utilities": values, "outputs": hashes}
    return reports


def select(original, corpus, observer, seed, arm, training, output):
    base = validation(original, corpus, observer, seed)
    candidates = [{"step": 0, "alpha": 0., "checkpoint": None, "metrics": base, "eligible": True}]
    best, selected = candidates[0], original
    for checkpoint in training["checkpoints"]:
        updated = ControlledSnapshot.load(output / checkpoint["path"], expected_file_sha256=checkpoint["sha256"])
        for alpha in P["parameter_interpolations"]:
            model = interpolate(original, updated, alpha)
            scores = validation(model, corpus, observer, seed)
            eligible = scores["retention"]["ce"] >= base["retention"]["ce"] - P["validation_retention_tolerance"]
            candidate = {"step": checkpoint["step"], "alpha": alpha, "checkpoint": checkpoint["path"],
                         "metrics": scores, "eligible": eligible}
            candidates.append(candidate)
            difference = scores["quality"]["ce"] - best["metrics"]["quality"]["ce"]
            preferred_tie = (abs(difference) <= 1e-12
                             and (alpha, checkpoint["step"]) < (best["alpha"], best["step"]))
            if eligible and (difference > 1e-12 or preferred_tie):
                best, selected = candidate, model
    path = output / f"seed-{seed}-{arm}-selected.pt"
    selected.save(path)
    record = {"seed": seed, "arm": arm, "selected": {k: v for k, v in best.items() if k != "metrics"},
              "selected_validation_ce": {k: v["ce"] for k, v in best["metrics"].items()},
              "frozen_validation_ce": {k: v["ce"] for k, v in base.items()},
              "selected_path": path.name, "selected_checkpoint_sha256": checksum(path),
              "selected_snapshot_sha256": selected.fingerprint, "candidates": candidates,
              "audit_observer_used": False, "new_test_or_retention_sources_used": False}
    write_json(output / f"SELECTION-{seed}-{arm}.json", record)
    print(f"selected seed={seed} arm={arm} step={best['step']} alpha={best['alpha']} CE={record['selected_validation_ce']}", flush=True)
    return record
