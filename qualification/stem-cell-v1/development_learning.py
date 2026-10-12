"""Existing shared Encoder -> independent learned Heads, with sealed test labels.

This is an offline research consumer, not a new loader/trainer/authority. Public
rows and TRAIN labels are separate. The CLI uses the existing safetensors-only
local loader; it cannot download weights or fall back to a simulated model.
"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import torch
from torch import nn

from development_ablation import FoldIdentity, PhaseClock, fit_candidate, validate_folds
from development_tensors import parameter_digest
from shared_encoder_batch import FeatureRequest, SharedStemEngine, digest_ok


@dataclass(frozen=True)
class LearningRow:
    request: FeatureRequest
    source_group: str
    observed_at: int
    split: str


def validate_rows(rows, training_labels, *, classes):
    """Reject the entire trial before any Encoder call or cache mutation."""
    if (type(rows) is not tuple or not 2 <= len(rows) <= 4096
            or type(classes) is not int or not 2 <= classes <= 128
            or type(training_labels) is not dict):
        raise ValueError("invalid learning census")
    ids, scopes, cells = set(), set(), set()
    grouped = {key: [] for key in ("train", "heldout")}
    for row in rows:
        if (type(row) is not LearningRow or type(row.request) is not FeatureRequest
                or type(row.split) is not str or row.split not in grouped
                or type(row.source_group) is not str or not 0 < len(row.source_group) <= 128
                or type(row.observed_at) is not int or not 0 <= row.observed_at < 2**63):
            raise ValueError("invalid row identity")
        row.request.validate()
        r = row.request
        if r.request_id in ids:
            raise ValueError("duplicate request")
        ids.add(r.request_id)
        scopes.add(r.cache_key()[:6] + (r.representation,))
        cells.add(r.cell_id)
        grouped[row.split].append(row)
    if len(scopes) != 1 or len(cells) > 64 or not all(grouped.values()):
        raise ValueError("mixed scope/version or incomplete folds")
    folds = [FoldIdentity(rows[0].request.scope_digest, tuple(r.source_group for r in group),
                          tuple(r.observed_at for r in group)) for group in grouped.values()]
    validate_folds(*folds, *(len(group) for group in grouped.values()))
    if {r.request.input_digest for r in grouped['train']} & {r.request.input_digest for r in grouped['heldout']}:
        raise ValueError("same input bytes cross training and heldout folds")
    train_ids = {r.request.request_id for r in grouped['train']}
    if (set(training_labels) != train_ids
            or any(type(v) is not int or not 0 <= v < classes for v in training_labels.values())):
        raise ValueError("exact training-only label map required")
    for cell in cells:
        if any(not any(r.request.cell_id == cell for r in group) for group in grouped.values()):
            raise ValueError("every Cell needs both training and heldout rows")
    return tuple(sorted(cells))


def run_shared_learning(engine, rows, training_labels, *, classes, steps=80, seed=19,
                        parameter_budget=16384):
    """Actual shared forwards and per-Cell SGD; no heldout gold enters this API."""
    cells = validate_rows(rows, training_labels, classes=classes)
    if (not isinstance(engine, SharedStemEngine) or type(steps) is not int or not 1 <= steps <= 1000
            or type(seed) is not int or not 0 <= seed < 2**31
            or type(parameter_budget) is not int or not 1 <= parameter_budget <= 262144):
        raise ValueError("invalid trial envelope")
    # Preflight against the selected backend before any work, including later batches.
    for row in rows:
        r = row.request
        if (r.encoder_digest, r.preprocessor_digest, r.runtime_digest) != (
                engine.backend.encoder_digest, engine.backend.preprocessor_digest, engine.backend.runtime_digest):
            raise ValueError("unselected backend")
    clock, encode_clock = PhaseClock(), PhaseClock()
    features, observations = [], []
    count = 0
    for offset in range(0, len(rows), 32):
        obs, batch = engine.run(tuple(r.request for r in rows[offset:offset+32]), return_features=True)
        count += sum(len(f.values) for f in batch)
        if count > 4_194_304:
            raise ValueError("feature retention budget exceeded")
        observations.append(obs)
        features.extend(batch)
    widths = {len(f.values) for f in features}
    if len(widths) != 1 or (next(iter(widths)) + 1) * classes > parameter_budget:
        raise ValueError("feature width or physical Head budget mismatch")
    # Ordinary, non-inference tensors permit autograd for Heads, never the Stem.
    x = torch.tensor([f.values for f in features], dtype=torch.float32)
    encoding = encode_clock.finish()
    predictions, receipts = [], {}
    for index, cell in enumerate(cells):
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed + index)
            initial = nn.Linear(x.shape[1], classes)
        train = [i for i, r in enumerate(rows) if r.request.cell_id == cell and r.split == 'train']
        heldout = [i for i, r in enumerate(rows) if r.request.cell_id == cell and r.split == 'heldout']
        labels = torch.tensor([training_labels[rows[i].request.request_id] for i in train], dtype=torch.long)
        original = parameter_digest(initial)
        candidate, receipt = fit_candidate(initial, x[train], labels, steps=steps, seed=seed+index)
        infer_clock = PhaseClock()
        with torch.no_grad():
            old, new = initial.eval()(x[heldout]), candidate(x[heldout])
        if not torch.isfinite(old).all() or not torch.isfinite(new).all():
            raise ValueError("nonfinite prediction")
        if original != parameter_digest(initial):
            raise RuntimeError("frozen baseline mutated")
        receipts[cell] = {"training": receipt, "paired_inference": infer_clock.finish(),
                          "initial_sha256": original, "candidate_sha256": parameter_digest(candidate)}
        for i, frozen, trained in zip(heldout, old.tolist(), new.tolist()):
            r = rows[i]
            predictions.append({"request_id": r.request.request_id, "cell_id": cell,
                                "source_group": r.source_group, "input_digest": r.request.input_digest,
                                "feature_digest": features[i].feature_digest,
                                "frozen_logits": frozen, "trained_logits": trained})
    return {"predictions": predictions, "cells": receipts, "encoding": encoding, "total": clock.finish(),
            "encoder_calls": sum(o.backend_calls for o in observations),
            "encoder_batch_widths": [w for o in observations for w in o.backend_batch_widths],
            "simulated_encoder": any(o.simulated for o in observations),
            "scored_heldout_labels": False, "independent_provenance_verified": False,
            "production_authorized": False}


def read_pinned_json(path, expected):
    """Bounded strict JSON; duplicate keys/NaN/overflow cannot be hidden in evidence."""
    path = Path(path)
    if not digest_ok(expected) or path.is_symlink() or not path.is_file():
        raise ValueError("invalid input file/digest")
    with path.open('rb') as stream:
        raw = stream.read(4_194_305)
    if not 0 < len(raw) <= 4_194_304 or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("changed or oversized input bytes")
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError("duplicate JSON key")
            out[key] = value
        return out
    def reject(value):
        raise ValueError("noninteger/nonstandard JSON number")
    return json.loads(raw, object_pairs_hook=pairs, parse_float=reject, parse_constant=reject)


def run_local(args):
    """Operator-invoked real-weight run; all admission happens before model loading."""
    public = read_pinned_json(args.rows, args.rows_sha256)
    labels = read_pinned_json(args.labels, args.labels_sha256)
    if type(public) is not list:
        raise ValueError("row array required")
    rows = []
    for row in public:
        if type(row) is not dict or set(row) != {'request', 'source_group', 'observed_at', 'split'}:
            raise ValueError("unknown fields or heldout labels in public rows")
        rows.append(LearningRow(FeatureRequest(**row['request']), row['source_group'], row['observed_at'], row['split']))
    rows = tuple(rows)
    validate_rows(rows, labels, classes=args.classes)
    if (type(args.steps) is not int or not 1 <= args.steps <= 1000
            or type(args.parameter_budget) is not int or not 1 <= args.parameter_budget <= 262144
            or type(args.max_tokens) is not int or not 1 <= args.max_tokens <= 8192):
        raise ValueError("invalid pre-load resource envelope")
    r = rows[0].request
    if r.encoder_digest != args.snapshot_sha256:
        raise ValueError("rows do not bind selected snapshot")
    output = Path(args.output)
    if output.exists():
        raise FileExistsError("output must be new")
    from model_runner import snapshot_digest
    from shared_encoder_batch import FrozenLocalHfBackend
    load_clock = PhaseClock()
    backend = FrozenLocalHfBackend(Path(args.snapshot), expected_snapshot_digest=args.snapshot_sha256,
                                  preprocessor_digest=r.preprocessor_digest, runtime_digest=r.runtime_digest,
                                  max_tokens=args.max_tokens, device='cpu')
    load = load_clock.finish()
    report = run_shared_learning(SharedStemEngine(backend), rows, labels, classes=args.classes,
                                 steps=args.steps, parameter_budget=args.parameter_budget)
    # Persistent source changes must be detected before publishing predictions.
    read_pinned_json(args.rows, args.rows_sha256)
    read_pinned_json(args.labels, args.labels_sha256)
    if snapshot_digest(Path(args.snapshot)) != args.snapshot_sha256:
        raise ValueError("snapshot changed during learning")
    report.update({"load": load, "snapshot_sha256": args.snapshot_sha256,
                   "rows_sha256": args.rows_sha256, "training_labels_sha256": args.labels_sha256,
                   "verified_loading": backend.verified_loading,
                   "verified_materialization": backend.verified_materialization,
                   "torch_version": torch.__version__, "device": "cpu",
                   "consumer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as stream:
        json.dump(report, stream, sort_keys=True, allow_nan=False)
        stream.write('\n')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('snapshot', 'snapshot-sha256', 'rows', 'rows-sha256', 'labels', 'labels-sha256', 'output'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--classes', type=int, required=True)
    parser.add_argument('--steps', type=int, default=80)
    parser.add_argument('--parameter-budget', type=int, default=16384)
    parser.add_argument('--max-tokens', type=int, default=512)
    run_local(parser.parse_args())
