"""Four independently learned Cells and bounded shared-basis serving experiments.

Reuse the pinned historical feature loader and existing training operators. No
new Encoder execution, runtime, store, production route or structural selection.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import importlib
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import platform
import time

import torch
from safetensors.torch import save

from development_study_data import canonical, write_once
from development_study_fit import RoutedBank, fit_record
from development_tensors import (BasisCellHeads, checked_tensor, fit_cell_candidate,
                                 parameter_digest, split_candidate)
from historical_feature_study import load_reference, derive_study
from model_runner import train_head
from shared_cell_execution import forward_shared

MAX_ERROR = 1e-4
METHODS = ("expanded_batch", "shared_features", "folded_dense")


def train_population(base_x, base_y, experiences, *, classes, rank=8, steps=200, seed=7347):
    """No evaluation labels accepted. Every Cell gets its own disjoint experience."""
    if (type(experiences) is not tuple or not 2 <= len(experiences) <= 64
            or type(steps) is not int or not 1 <= steps <= 1000):
        raise ValueError("invalid population or step budget")
    for x, y in ((base_x, base_y), *experiences):
        checked_tensor(x, 2, "training features")
        if (x.shape[1] != base_x.shape[1] or x.dtype != torch.float32
                or not isinstance(y, torch.Tensor) or y.device.type != "cpu"
                or y.dtype != torch.long or y.shape != (len(x),)
                or bool(((y < 0) | (y >= classes)).any())):
            raise ValueError("invalid population training rows")
    parent = RoutedBank(BasisCellHeads(base_x.shape[1], classes, rank, ("cell-0",), seed=seed))
    parent.bank.base.requires_grad_(True); parent.bank.basis.requires_grad_(True)
    base_cost = fit_record(parent, base_x, base_y, steps, seed)
    bank = deepcopy(parent.bank)
    for i in range(1, len(experiences)):
        bank = split_candidate(bank, "cell-0", f"cell-{i}",
                               maximum_local_parameters=len(experiences)*(2*rank+1))
    inherited = deepcopy(bank).requires_grad_(False)
    costs = []
    start = time.process_time_ns()
    for i, (x, y) in enumerate(experiences):
        before = bank
        bank, cost = fit_cell_candidate(bank, f"cell-{i}", x, y,
                                       fit=train_head, steps=steps, seed=seed+i+1)
        peers = [j for j in range(len(experiences)) if j != i]
        if (not torch.equal(before.coefficients[peers], bank.coefficients[peers])
                or not torch.equal(before.gates[peers], bank.gates[peers])):
            raise ValueError("local training changed another Cell")
        cost.update(cell_id=f"cell-{i}", training_rows=len(x),
                    sample_presentations=steps*min(32, len(x)))
        costs.append(cost)
    for name in ("basis", "gate_axes", "base.weight", "base.bias"):
        if not torch.equal(bank.state_dict()[name], inherited.state_dict()[name]):
            raise ValueError("private training changed shared parameters")
    return inherited, bank.requires_grad_(False), {
        "base_training": base_cost, "cell_training": costs,
        "private_training_including_candidate_copies_cpu_ns": time.process_time_ns()-start,
        "total_optimizer_steps": steps*(len(experiences)+1),
        "parameter_counts": bank.parameter_counts(), "encoder_calls_this_run": 0}


def folded_parameters(bank):
    """Strong frozen affine control; charge compilation AND replicated matrices."""
    stored = len(bank.cell_ids) * (bank.width*bank.classes + bank.width + 1)
    if stored * bank.base.weight.element_size() > 64*1024*1024:
        raise ValueError("folded control exceeds its 64 MiB matrix budget")
    return (torch.einsum("cr,rdk->cdk", bank.coefficients, bank.basis),
            bank.gates[:, :-1] @ bank.gate_axes, bank.gates[:, -1].clone())


def folded_forward(bank, folded, features, fids, cids):
    x = features[fids]
    weights, gates, bias = folded
    activation = torch.sigmoid((x*gates[cids]).sum(1) + bias[cids])
    return bank.base(x) + activation[:, None]*(x[:, :, None]*weights[cids]).sum(1)


def probe(bank, features, fids, cids, *, repeats=3):
    """Same input/output census; balanced rotated order, no hidden warm-up cost.

    Each 32-request call shares only its referenced rows. This measures CPU Head
    math including validation; the already-computed Encoder work is not rerun.
    The folded control is genuinely compiled once and keeps its extra matrices.
    """
    if type(repeats) is not int or not 3 <= repeats <= 30 or repeats % 3:
        raise ValueError("probe requires complete three-position rotations")
    all_cpu, all_wall = time.process_time_ns(), time.perf_counter_ns()
    with torch.no_grad():
        # Validate the complete population before preparing any benchmark plan.
        forward_shared(bank, features, fids, cids)
        before = parameter_digest(bank)
        prep_cpu, prep_wall = time.process_time_ns(), time.perf_counter_ns()
        batches = []
        for a in range(0, len(cids), 32):
            unique, inverse = torch.unique(fids[a:a+32], sorted=True, return_inverse=True)
            batches.append((features[unique].clone(), inverse, cids[a:a+32].clone()))
        preparation = {"cpu_ns": time.process_time_ns()-prep_cpu,
                       "wall_ns": time.perf_counter_ns()-prep_wall}
        start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
        folded = folded_parameters(bank)
        compilation = {"cpu_ns": time.process_time_ns()-start_cpu,
                       "wall_ns": time.perf_counter_ns()-start_wall,
                       "additional_tensor_bytes": sum(t.numel()*t.element_size() for t in folded)}
        operations = {
            "expanded_batch": lambda x, f, c: bank(x[f], c),
            "shared_features": lambda x, f, c: forward_shared(bank, x, f, c),
            "folded_dense": lambda x, f, c: folded_forward(bank, folded, x, f, c),
        }
        # All initial warm-up work is measured, retained, and not called cold load.
        start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
        for op in operations.values():
            op(*batches[0])
        warmup = {"cpu_ns": time.process_time_ns()-start_cpu,
                  "wall_ns": time.perf_counter_ns()-start_wall}
        reference = torch.cat([operations["expanded_batch"](*b) for b in batches])
        trials = []
        for repeat in range(repeats):
            order = METHODS[repeat % 3:] + METHODS[:repeat % 3]
            for position, name in enumerate(order):
                cpu, wall = time.process_time_ns(), time.perf_counter_ns()
                outputs = torch.cat([operations[name](*b) for b in batches])
                duration = {"cpu_ns": time.process_time_ns()-cpu, "wall_ns": time.perf_counter_ns()-wall}
                error = float((outputs-reference).abs().max())
                if (not torch.isfinite(outputs).all() or error > MAX_ERROR
                        or not torch.equal(outputs.argmax(1), reference.argmax(1))):
                    raise ValueError("shared/folded result differs from trained batch")
                trials.append({"repeat": repeat, "position": position, "method": name,
                               **duration, "max_abs_logit_error": error, "argmax_reversals": 0})
        if parameter_digest(bank) != before:
            raise ValueError("benchmark mutated learned parameters")
        medians = {m: statistics.median(t["wall_ns"] for t in trials if t["method"] == m) for m in METHODS}
        return {"request_rows": len(cids), "active_distinct_cells": len(torch.unique(cids)),
                "distinct_feature_rows": len(features), "batch_calls_per_trial": len(batches),
                "shared_projection_rows_per_trial": sum(len(b[0]) for b in batches),
                "expanded_input_rows_per_trial": len(cids), "trials": trials,
                "median_wall_ns": medians, "preparation": preparation,
                "folded_compilation": compilation, "warmup": warmup,
                "parameter_counts": bank.parameter_counts(),
                "stored_bank_tensor_bytes": sum(v.numel()*v.element_size() for v in bank.state_dict().values()),
                "preflight_shared_rows": len(cids), "reference_rows": len(cids),
                "warmup_rows": 3*len(batches[0][1]),
                "complete_probe_cpu_ns": time.process_time_ns()-all_cpu,
                "complete_probe_wall_ns": time.perf_counter_ns()-all_wall,
                "encoder_calls_this_run": 0, "rss_measured": False, "production_authorized": False}


def execute(archive, output, *, synthetic_scaling=False):
    """Fixed four-Cell protocol; saved parameters/predictions precede scoring."""
    total_cpu, total_wall = time.process_time_ns(), time.perf_counter_ns()
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    source_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob("*.py")}
    imports = {}
    for name in ("model_runner", "study"):
        p = Path(importlib.import_module(name).__file__).resolve()
        imports[name] = {"file_sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                         "within_qualification_source": p.parent == Path(__file__).resolve().parent}
    git = subprocess.run(["git", "-C", str(Path(__file__).resolve().parents[2]), "rev-parse", "HEAD"],
                         capture_output=True, text=True, check=False)
    write_once(output/"plan.json", {"schema": "hepta.stem.multicell-learning.v1",
        "git_source_sha": git.stdout.strip() if git.returncode == 0 else None,
        "imported_source_files": imports, "python": platform.python_version(),
        "torch": torch.__version__, "torch_threads": torch.get_num_threads(), "cells": 4, "classes": 4, "rank": 8, "seed": 7347,
        "base_steps": 200, "steps_each_cell": 200, "synthetic_scaling": synthetic_scaling,
        "source_file_sha256": source_hashes, "fresh_encoder_execution": False})
    try:
        inventory, ids, raw, reference, _ = load_reference(archive)
        rows, raw, config = derive_study(inventory, ids, raw)
        base = [i for i,r in enumerate(rows) if r["training_phase"] == "base"]
        local = [i for i,r in enumerate(rows) if r["training_phase"] in ("adapt", "extra")]
        mean, scale = raw[base].mean(0), raw[base].std(0, unbiased=False).clamp_min(1e-6)
        features = (raw-mean)/scale
        assigned = [[] for _ in range(4)]
        for label in range(4):
            by_label = sorted((i for i in local if rows[i]["label"] == label),
                              key=lambda i: rows[i]["source_group"])
            for j, i in enumerate(by_label):
                assigned[j % 4].append(i)
        if len({i for group in assigned for i in group}) != len(local):
            raise ValueError("private training rows are not disjoint")
        def labels(indices):
            return torch.tensor([rows[i]["label"] for i in indices], dtype=torch.long)
        inherited, learned, costs = train_population(features[base], labels(base),
            tuple((features[g], labels(g)) for g in assigned), classes=config.classes)
        with (output/"learned.safetensors").open("xb") as f:
            f.write(save({k:v.detach().contiguous() for k,v in learned.state_dict().items()}))
        with (output/"inherited.safetensors").open("xb") as f:
            f.write(save({k:v.detach().contiguous() for k,v in inherited.state_dict().items()}))
        with (output/"normalizer.safetensors").open("xb") as f:
            f.write(save({"mean": mean, "scale": scale}))
        training = {"cell_ids": list(learned.cell_ids), "generation": learned.generation, "costs": costs,
            "private_training_sample_ids": [[rows[i]["sample_id"] for i in g] for g in assigned],
            "shared_pretrained_feature_origin": reference,
            "private_parameter_sha256": [hashlib.sha256(torch.cat((c,g)).numpy().tobytes()).hexdigest()
                for c,g in zip(learned.coefficients.detach(),learned.gates.detach())],
            "learned_parameter_digest": parameter_digest(learned),
            "inherited_parameter_digest": parameter_digest(inherited)}
        write_once(output/"training.json", training)
        evaluated = [i for i,r in enumerate(rows) if r["split"] == "held_out"]
        x = features[evaluated]
        fids = torch.arange(len(x)).repeat_interleave(4)
        cids = torch.arange(4).repeat(len(x))
        with torch.no_grad():
            trained = forward_shared(learned, x, fids, cids)
            frozen = inherited(x[fids], cids)
            oracle = folded_forward(learned, folded_parameters(learned), x, fids, cids)
        if float((trained-oracle).abs().max()) > MAX_ERROR or not torch.equal(trained.argmax(1),oracle.argmax(1)):
            raise ValueError("learned predictions fail independent affine reconstruction")
        predictions = [{"sample_id": rows[evaluated[f]]["sample_id"], "cell_id": learned.cell_ids[c],
                        "logits": new.tolist(), "frozen_logits": old.tolist()}
                       for f,c,new,old in zip(fids.tolist(),cids.tolist(),trained,frozen)]
        write_once(output/"predictions.json", predictions)
        measured = probe(learned, x, fids, cids)
        write_once(output/"trained-serving.json", measured)
        if synthetic_scaling:
            for size in (64, 256, 1024, 4096):
                bank = BasisCellHeads(learned.width, 4, 8, tuple(f"fixture-{i}" for i in range(size)), seed=7347)
                with torch.no_grad():
                    bank.base.load_state_dict(learned.base.state_dict())
                    bank.basis.copy_(learned.basis); bank.gate_axes.copy_(learned.gate_axes)
                    g = torch.Generator().manual_seed(size)
                    bank.coefficients.copy_(torch.randn(size,8,generator=g)*.03)
                    bank.gates.copy_(torch.randn(size,9,generator=g)*.03)
                for unique in (1,8,32):
                    result = probe(bank, x[:unique], torch.arange(size)%unique, torch.arange(size))
                    result["private_coefficients_synthetic_not_trained"] = True
                    write_once(output/f"synthetic-{size}-{unique}.json", result)
        files = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file()}
        report = {"schema": "hepta.stem.multicell-run.v1",
            "calibration_selection_performed": False,
            "independent_future_outcomes": False, "physical_encoder_calls_this_run": 0,
            "total_cpu_ns": time.process_time_ns()-total_cpu,
            "total_wall_ns": time.perf_counter_ns()-total_wall,
            "cost_scope": "all current preparation/fit/prediction/probes/hashes before terminal record; separate review excluded",
            "all_files_sha256": files,
            "production_authorized": False}
        write_once(output/"result.json", report)
        return report
    except Exception as error:
        write_once(output/"FAILED.json", {"error_type": type(error).__name__, "message": str(error)})
        raise


def review(archive, folder, output):
    """Separate original-label score and affine replay; never pick a winner."""
    from safetensors.torch import load
    from development_study_replay import record, read_bytes
    folder = Path(folder)
    if (folder/"FAILED.json").exists():
        raise ValueError("failed study cannot be scored")
    run, _ = record(folder/"result.json", 1_000_000)
    if run.get("schema") != "hepta.stem.multicell-run.v1" or run.get("physical_encoder_calls_this_run") != 0:
        raise ValueError("wrong historical population profile")
    required = {"plan.json", "training.json", "learned.safetensors", "inherited.safetensors",
                "normalizer.safetensors", "predictions.json", "trained-serving.json"}
    if not isinstance(run.get("all_files_sha256"), dict) or not required <= set(run["all_files_sha256"]):
        raise ValueError("required population files are not bound")
    for name, sha in run["all_files_sha256"].items():
        if Path(name).name != name or hashlib.sha256(read_bytes(folder/name, 8_388_608)).hexdigest() != sha:
            raise ValueError("sealed population files changed")
    inventory, ids, raw, _, _ = load_reference(archive)
    rows, raw, _ = derive_study(inventory, ids, raw)
    normalizer = load(read_bytes(folder/"normalizer.safetensors", 8192))
    base = raw[[i for i,r in enumerate(rows) if r["training_phase"] == "base"]]
    mean, scale = base.mean(0), base.std(0,unbiased=False).clamp_min(1e-6)
    if set(normalizer) != {"mean","scale"} or not torch.equal(normalizer["mean"],mean) or not torch.equal(normalizer["scale"],scale):
        raise ValueError("normalizer not fitted to base data only")
    cells = tuple(f"cell-{i}" for i in range(4))
    predictions, _ = record(folder/"predictions.json", 2_097_152)
    evaluated = [r for r in rows if r["split"] == "held_out"]
    x = ((raw-mean)/scale)[[i for i,r in enumerate(rows) if r["split"] == "held_out"]]
    if len(predictions) != len(evaluated)*4:
        raise ValueError("incomplete multi-Cell prediction census")
    metrics, max_error = {}, 0.0
    for name, field in (("learned","logits"),("inherited","frozen_logits")):
        bank = BasisCellHeads(raw.shape[1],4,8,cells,seed=7347).requires_grad_(False)
        tensors = load(read_bytes(folder/(name+".safetensors"),8_388_608))
        if any(v.dtype != torch.float32 or not torch.isfinite(v).all() for v in tensors.values()):
            raise ValueError("invalid saved Cell parameter dtype or value")
        bank.load_state_dict(tensors,strict=True)
        folded = folded_parameters(bank)
        target = torch.tensor([r["label"] for r in evaluated])
        for c, cell in enumerate(cells):
            original = predictions[c::4]
            if any(p.get("sample_id") != r["sample_id"] or p.get("cell_id") != cell for p,r in zip(original,evaluated)):
                raise ValueError("prediction identity/order mismatch")
            logits = torch.tensor([p[field] for p in original])
            if logits.shape != (len(evaluated),4):
                raise ValueError("invalid saved Cell logit shape")
            actual = folded_forward(bank,folded,x,torch.arange(len(x)),torch.full((len(x),),c))
            error = float((actual-logits).abs().max())
            if not torch.isfinite(logits).all() or not torch.isfinite(actual).all() or error > MAX_ERROR or not torch.equal(actual.argmax(1),logits.argmax(1)):
                raise ValueError("sealed logits fail affine reconstruction")
            max_error = max(max_error,error)
            metrics.setdefault(cell,{})[name] = {"correct": int((logits.argmax(1)==target).sum()),
                "count":len(target),"brier":float((torch.softmax(logits,1)-torch.nn.functional.one_hot(target,4)).square().sum(1).mean())}
    result = {"per_cell":metrics,"max_abs_affine_replay_error":max_error,"argmax_reversals":0,
        "unique_test_inputs":len(evaluated),"prediction_rows":len(predictions),
        "parameter_updates_selected":False,"independent_future_outcomes":False,"production_authorized":False}
    write_once(output,result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--synthetic-scaling", action="store_true")
    parser.add_argument("--review-run", type=Path)
    args = parser.parse_args()
    torch.set_num_threads(2)
    torch.use_deterministic_algorithms(True)
    if args.review_run:
        review(args.archive, args.review_run, args.output)
    else:
        execute(args.archive, args.output, synthetic_scaling=args.synthetic_scaling)
