"""Sealed anchor-consolidation extension of the existing six-control study.

Reuse verified teachers and frozen features, not cached scores or a task oracle.
No data download, production promotion, signature or native owner is introduced.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import math
from pathlib import Path
import time

import torch
from safetensors.torch import load, save

from cell_anchor_consolidation import ANCHOR_TOLERANCE, EXTRA_ARMS, fit_anchors
from cell_consolidation import ARMS, ConsolidationConfig, metrics, select_retained, training_partition
from cell_consolidation_study import affine_logits, review_rows as review_base, source_features
from development_study import prepare_views
from development_study_data import digest, phase, write_once
from development_study_replay import read_bytes, record

ALL_ARMS = ARMS + EXTRA_ARMS


def load_base(rows, features, origin, baseline, *, score_held_out=False):
    """Revalidate the existing study; the producer requests calibration only."""
    report = review_base(rows, features, origin, baseline, score_held_out=score_held_out)
    plan, _ = record(Path(baseline)/"plan.json")
    raw = dict(plan["config"]); raw["old_classes"] = tuple(raw["old_classes"])
    config = ConsolidationConfig(**raw).validate()
    tensors = {n: load(read_bytes(Path(baseline)/f"{n}.safetensors", 1_048_576)) for n in ARMS[:-1]}
    # Check the files read, not merely the earlier review of their paths.
    selection, selection_sha = record(Path(baseline)/"selection.json")
    run, run_sha = record(Path(baseline)/"run.json")
    if run_sha != report["run_sha256"] or selection_sha != run["selection_sha256"]:
        raise ValueError("baseline changed after validation")
    for name, tensor in tensors.items():
        # Serialization metadata/order can differ; reread the pinned bytes instead.
        raw_bytes = read_bytes(Path(baseline)/f"{name}.safetensors", 1_048_576)
        if hashlib.sha256(raw_bytes).hexdigest() != selection["checkpoints"][name]:
            raise ValueError("teacher checkpoint changed after validation")
        reread = load(raw_bytes)
        if set(reread) != set(tensor) or any(not torch.equal(reread[k], tensor[k]) for k in tensor):
            raise ValueError("teacher materialization changed")
    return tensors, config, {"run_sha256": run_sha, "selection_sha256": selection_sha,
        "checkpoints": selection["checkpoints"], "source": origin,
        "prior_learning_costs": selection["costs"]}


def evaluated_logits(teachers, candidates, x, classes):
    """Independent affine equation and probability mean; no training forward."""
    values = {n: affine_logits(t, x, classes) for n, t in teachers.items()}
    values["teacher_mean"] = torch.logsumexp(torch.stack((torch.log_softmax(values["frozen"], -1),
        torch.log_softmax(values["new_only"], -1))), 0) - math.log(2)
    for name, t in candidates.items():
        if (set(t) != {"weight", "bias"} or t["weight"].shape != (classes, x.shape[1])
                or t["bias"].shape != (classes,) or any(v.dtype != torch.float32 or not torch.isfinite(v).all() for v in t.values())):
            raise ValueError("invalid packed affine inventory")
        values[name] = x @ t["weight"].T + t["bias"]
    if any(not torch.isfinite(v).all() for v in values.values()):
        raise ValueError("nonfinite replayed output")
    return values


def execute(rows, features, origin, baseline, output):
    start = time.process_time_ns(), time.perf_counter_ns()
    # Remove unseen labels entirely at the producer's baseline-review boundary.
    hidden = [{k: v for k, v in r.items() if k != "label" or phase(r) != "held_out"} for r in rows]
    teachers, config, source = load_base(hidden, features, origin, baseline)
    inputs, _ = prepare_views(rows)
    truth = {r["sample_id"]: r["label"] for r in rows if phase(r) in ("base", "adapt")}
    old, new, memory = training_partition(inputs, truth, config)
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    plan_sha = write_once(output/"plan.json", {"schema": "hepta.cell.anchor-plan.v1",
        "source": source, "config": asdict(config), "arms": ALL_ARMS,
        "anchor_tolerance": ANCHOR_TOLERANCE, "input_digest": digest(inputs),
        "implementation": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.glob('*.py'))},
        "torch": torch.__version__, "threads": torch.get_num_threads(), "production_authorized": False})
    try:
        candidates, costs = fit_anchors(inputs, truth, features, config, {n: teachers[n] for n in ("frozen", "new_only")})
        inventory = {}
        for name, tensors in candidates.items():
            raw = save(tensors)
            with (output/f"{name}.safetensors").open('xb') as h: h.write(raw)
            inventory[name] = hashlib.sha256(raw).hexdigest()
        mean, scale = features[old].mean(0), features[old].std(0, unbiased=False).clamp_min(1e-6)
        calibration = [i for i, r in enumerate(rows) if phase(r) == 'calibration']
        cal = evaluated_logits(teachers, candidates, (features[calibration]-mean)/scale, config.classes)
        scores = {n: metrics(v, torch.tensor([rows[i]['label'] for i in calibration]),
            [rows[i]['source_group'] for i in calibration], config) for n, v in cal.items()}
        decision = select_retained(scores, config, extra_arms=EXTRA_ARMS)
        selection_sha = write_once(output/'selection.json', {**decision, "calibration_metrics": scores,
            "costs": costs, "checkpoints": inventory, "old": old, "new": new, "memory": memory})
        # No held-out gold is accessed when writing held-out predictions.
        indices = [i for i, r in enumerate(rows) if phase(r) in ('calibration', 'held_out')]
        logits = evaluated_logits(teachers, candidates, (features[indices]-mean)/scale, config.classes)
        predictions = [{"arm": n, "sample_id": inputs[i]['sample_id'], "input_fingerprint": inputs[i]['input_fingerprint'],
            "logits": v} for n in ALL_ARMS for i, v in zip(indices, logits[n].tolist())]
        predictions_sha = write_once(output/'predictions.json', predictions)
        result = {"schema": "hepta.cell.anchor-run.v1", "plan_sha256": plan_sha,
            "selection_sha256": selection_sha, "predictions_sha256": predictions_sha,
            "cpu_ns": time.process_time_ns()-start[0], "wall_ns": time.perf_counter_ns()-start[1],
            "current_encoder_calls": 0, "production_authorized": False}
        write_once(output/'run.json', result)
        return result
    except Exception as error:
        write_once(output/'FAILED.json', {"error_type": type(error).__name__, "message": str(error)})
        raise


def review(rows, features, origin, baseline, output, *, score_held_out=True):
    if type(score_held_out) is not bool:
        raise ValueError("invalid anchor review mode")
    output = Path(output)
    if (output/'FAILED.json').exists(): raise ValueError("failed run cannot be scored")
    teachers, config, source = load_base(rows, features, origin, baseline)
    run, run_sha = record(output/'run.json')
    plan, plan_sha = record(output/'plan.json')
    selection, selection_sha = record(output/'selection.json')
    predictions, preds_sha = record(output/'predictions.json', 16_777_216)
    inputs, _ = prepare_views(rows)
    if (run['schema'] != 'hepta.cell.anchor-run.v1' or run['current_encoder_calls'] != 0
            or run['production_authorized'] is not False or plan['source'] != source
            or plan['input_digest'] != digest(inputs) or plan['arms'] != list(ALL_ARMS)
            or plan['anchor_tolerance'] != ANCHOR_TOLERANCE
            or digest(plan['config']) != digest(asdict(config))
            or (plan_sha, selection_sha, preds_sha) != (run['plan_sha256'], run['selection_sha256'], run['predictions_sha256'])):
        raise ValueError("anchor run source or sealed records changed")
    truth = {r['sample_id']: r['label'] for r in rows if phase(r) in ('base', 'adapt')}
    old, new, memory = training_partition(inputs, truth, config)
    if any(selection[n] != v for n, v in (('old', old), ('new', new), ('memory', memory))):
        raise ValueError("anchor training partition changed")
    if set(selection['checkpoints']) != set(EXTRA_ARMS) or set(selection['costs']) != set(EXTRA_ARMS):
        raise ValueError("missing affine controls")
    candidates = {}
    for n, sha in selection['checkpoints'].items():
        raw = read_bytes(output/f'{n}.safetensors', 1_048_576)
        if hashlib.sha256(raw).hexdigest() != sha: raise ValueError("affine checkpoint changed")
        candidates[n] = load(raw)
    mean, scale = features[old].mean(0), features[old].std(0, unbiased=False).clamp_min(1e-6)
    anchor_reports = {}
    for n in EXTRA_ARMS:
        ids = memory if n == 'anchor_memory' else old if n == 'anchor_all_old' else []
        cost = selection['costs'][n]
        d, count = features.shape[1]+1, (features.shape[1]+1)*config.classes
        if (cost['steps'] != config.steps or cost['sample_presentations'] != config.steps*32
                or cost['anchor_indices'] != ids or cost['anchor_rows'] != len(ids)
                or cost['deployed_parameters'] != count or cost['deployed_weight_bytes'] != count*4
                or cost['current_encoder_calls'] != 0): raise ValueError("false constrained resource census")
        if ids:
            x = (features[ids]-mean)/scale
            predicted = evaluated_logits(teachers, {n: candidates[n]}, x, config.classes)
            drift = float((predicted[n]-predicted['frozen']).abs().max())
            if drift > ANCHOR_TOLERANCE or abs(drift-cost['packed_anchor_max_error']) > 1e-6:
                raise ValueError("old-anchor output was not retained")
            # Recompute rank independently with singular values, not a saved basis.
            a = torch.cat((x.double(), torch.ones(len(x), 1, dtype=torch.float64)), 1)
            s = torch.linalg.svdvals(a); threshold = torch.finfo(torch.float64).eps*max(a.shape)*float(s[0])
            rank = int((s > threshold).sum())
        else:
            drift, rank = None, 0
        if (cost['constraint_rank'] != rank or cost['free_input_dimensions'] != d-rank
                or cost['anchor_tensor_bytes'] != len(ids)*d*8 or cost['basis_tensor_bytes'] != rank*d*8):
            raise ValueError("false anchor rank/storage")
        anchor_reports[n] = {'rows': len(ids), 'rank': rank, 'max_abs_logit_drift': drift}
    indices = [i for i, r in enumerate(rows) if phase(r) in ('calibration', 'held_out')]
    logits = evaluated_logits(teachers, candidates, (features[indices]-mean)/scale, config.classes)
    expected = [{"arm": n, "sample_id": inputs[i]['sample_id'], "input_fingerprint": inputs[i]['input_fingerprint'],
        "logits": v} for n in ALL_ARMS for i, v in zip(indices, logits[n].tolist())]
    if type(predictions) is not list or len(predictions) != len(expected): raise ValueError("prediction census mismatch")
    maximum = 0.
    for p, e in zip(predictions, expected):
        if (type(p) is not dict or set(p) != set(e) or any(p[k] != e[k] for k in e if k != 'logits')
                or type(p['logits']) is not list or any(type(v) not in (int, float) for v in p['logits'])):
            raise ValueError("prediction identity or shape mismatch")
        a, b = torch.tensor(p['logits']), torch.tensor(e['logits'])
        if a.shape != b.shape or not torch.isfinite(a).all(): raise ValueError("invalid logits")
        error = float((a-b).abs().max()); maximum = max(maximum, error)
        if error > 1e-5 or a.argmax() != b.argmax(): raise ValueError("false stored prediction")
    scores = {}
    for part in (('calibration', 'held_out') if score_held_out else ('calibration',)):
        js = [j for j, i in enumerate(indices) if phase(r := rows[i]) == part]
        scores[part] = {n: metrics(v[js], torch.tensor([rows[indices[j]]['label'] for j in js]),
            [rows[indices[j]]['source_group'] for j in js], config) for n, v in logits.items()}
    decision = select_retained(scores['calibration'], config, extra_arms=EXTRA_ARMS)
    if any(selection[k] != v for k, v in decision.items()):
        raise ValueError("calibration selection does not reproduce")
    pending = [(selection['calibration_metrics'], scores['calibration'])]
    while pending:
        saved, computed = pending.pop()
        if isinstance(computed, dict):
            if not isinstance(saved, dict) or set(saved) != set(computed):
                raise ValueError("calibration metric schema changed")
            pending.extend((saved[k], computed[k]) for k in computed)
        elif type(saved) not in (int, float) or not math.isfinite(saved) or abs(saved-computed) > 1e-6:
            raise ValueError("calibration metric values changed")
    return {'schema': 'hepta.cell.anchor-review.v1', 'run_sha256': run_sha, **decision,
        'scores': scores, 'anchors': anchor_reports, 'prediction_rows': len(predictions),
        'unique_held_out_inputs': sum(phase(r) == 'held_out' for r in rows),
        'max_abs_logit_error': maximum, 'argmax_reversals': 0, 'current_encoder_calls': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run', type=Path, required=True)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--consolidation-run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--review-run', type=Path)
    args = parser.parse_args(); torch.set_num_threads(2)
    rows, features, origin = source_features(args.source_run, args.dataset)
    if args.review_run:
        write_once(args.output, review(rows, features, origin, args.consolidation_run, args.review_run))
    else:
        execute(rows, features, origin, args.consolidation_run, args.output)
