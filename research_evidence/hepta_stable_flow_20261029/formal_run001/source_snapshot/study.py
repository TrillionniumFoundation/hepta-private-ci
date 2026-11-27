"""Sealed new-execution study: freeze, prepare, train, select, then score.

The study intentionally separates training, validation selection and test
access. Development qualification uses independent train-only episodes.
No checkpoint or data from the deleted prior execution is consumed.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import platform
import shutil
import sys
import time

import numpy as np
import torch
from torch.nn import functional as F

from .data import TASKS, TaskConfig, array_digest, contract, episode_digests, generate
from .models import ARMS, ModelConfig, build_model


PACKAGE = Path(__file__).resolve().parent
SEEDS = (81301, 81302, 81303)
LEARNING_RATES = (0.001, 0.003)


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def _sources():
    return {
        str(p.relative_to(PACKAGE)): _digest(p)
        for p in sorted(PACKAGE.rglob("*.py"))
        if "__pycache__" not in p.parts
    }


def _save_weights(path, state):
    with Path(path).open("xb") as stream:
        np.savez_compressed(
            stream,
            **{name: value.detach().cpu().numpy() for name, value in state.items()},
        )
    return _digest(path)


def _load_weights(model, path):
    with np.load(path, allow_pickle=False) as arrays:
        model.load_state_dict(
            {name: torch.from_numpy(arrays[name].copy()) for name in arrays.files}
        )


def _clone_state(model):
    return {name: value.detach().clone() for name, value in model.state_dict().items()}


def _tensor_data(data):
    return {name: torch.from_numpy(value) for name, value in data.items()}


def _read_data(path):
    with np.load(path, allow_pickle=False) as arrays:
        return _tensor_data({name: arrays[name].copy() for name in arrays.files})


def _verified_data(output, task, split):
    path = output / "data" / task / f"{split}.npz"
    manifest = json.loads((output / "data_manifest.json").read_text())
    if _digest(path) != manifest["splits"][f"{task}/{split}"]["file_sha256"]:
        raise RuntimeError(f"{task}/{split} data digest mismatch")
    return _read_data(path)


def _save_data(path, data):
    with Path(path).open("xb") as stream:
        np.savez_compressed(stream, **data)


def _verify_protocol(output):
    protocol_path = output / "protocol.json"
    seal = json.loads((output / "freeze_seal.json").read_text())
    if _digest(protocol_path) != seal["protocol_sha256"]:
        raise RuntimeError("The registered protocol has changed")
    protocol = json.loads(protocol_path.read_text())
    if _sources() != protocol["source_sha256"]:
        raise RuntimeError("Current scientific sources differ from the frozen sources")
    return protocol


def freeze(output, max_step):
    if output.resolve().is_relative_to(PACKAGE):
        raise ValueError(
            "Evidence output must be outside the scientific source package"
        )
    output.mkdir(parents=True, exist_ok=False)
    candidates = [
        {
            "id": f"{task}__{arm}__s{seed}__lr{lr:g}",
            "task": task,
            "arm": arm,
            "seed": seed,
            "learning_rate": lr,
        }
        for task in TASKS
        for arm in ARMS
        for seed in SEEDS
        for lr in LEARNING_RATES
    ]
    protocol = {
        "study_version": "hepta-explicit-associative-stable-flow-20261029-v1",
        "new_execution": True,
        "old_weights_or_raw_data_loaded": False,
        "purpose": "Test analytic boundary constraints conditional on shared explicit associative memory and causal task priors",
        "source_sha256": _sources(),
        "task_contract": contract(),
        "model_config": asdict(ModelConfig(max_step=max_step)),
        "initialization": "All learned tensors are identical at a shared seed across arms. Initial margin x_star is shared, but the operator-derived recovery equilibrium z_star=g_recovery*Put(x_star) differs by operator; raw initial states are not all identical.",
        "conditional_memory_exactness": "The rank-one M update exactly integrates fixed key, value, leak and write rates during each tick, for arbitrary finite key norm including zero. Boundary-dependent rates are held at the post-flow value for that tick. The coupled flow-memory system is not an exact analytic solution.",
        "arms": list(ARMS),
        "seeds": list(SEEDS),
        "learning_rates": list(LEARNING_RATES),
        "candidates": candidates,
        "candidate_count": len(candidates),
        "split_counts": {"train": 1024, "validation": 256, "test": 512},
        "split_seeds": {
            task: {
                split: 174101 + 100 * j + k
                for k, split in enumerate(("train", "validation", "test"))
            }
            for j, task in enumerate(TASKS)
        },
        "batch_size": 32,
        "optimizer": "Adam",
        "gradient_clip_norm": 1.0,
        "dtype": "float32",
        "torch_threads": 1,
        "training_endpoints": {"cpu_seconds": 30, "updates": 384},
        "selection_checkpoints": {
            "cpu30": ["cpu15", "cpu30"],
            "updates384": ["update192", "update384"],
        },
        "cpu_definition": "Sum of process_time for training updates including batching, backward, clipping, optimizer, activity accounting and prior-state snapshot; excludes evaluation and file I/O. CPU checkpoints use the last completed update at or below the stated budget.",
        "selection": "Lowest validation CE among both learning rates and the two eligible checkpoints, separately for each task/arm/seed/budget; ties by checkpoint name then candidate id",
        "test_access": "Only after all 60 candidates finish and validation selection is sealed",
        "quality_floor": {
            "validation_accuracy_every_seed": 0.90,
            "analytic_test_accuracy_every_seed": 0.90,
        },
        "metrics": ["accuracy", "cross_entropy", "sequence_accuracy"],
        "primary_family": {
            "comparator": "matched_c1",
            "comparisons_per_metric": 4,
            "metrics": ["accuracy", "cross_entropy"],
        },
        "secondary_family": {
            "comparators": ["sigmoid", "ordinary"],
            "comparisons_per_metric": 8,
            "metrics": ["accuracy", "cross_entropy"],
        },
        "intervals": "Paired seed mean difference with Bonferroni-adjusted two-sided Student t interval, df=2, per metric/family; normality is untestable at n=3 and intervals are exploratory",
        "multiplicity_scope": "Accuracy and CE are separately declared metric families. No across-metric familywise error control or advantage claim by choosing whichever metric wins.",
        "minimum_mean_effect": {"accuracy": 0.005, "cross_entropy": 0.01},
        "claim_rule": "A metric-specific improvement requires quality floors, adjusted lower CI > 0 and minimum mean effect; no general superiority, multimodal, energy, or scaling claim follows",
        "frozen_flow": "Diagnostic only: analytic controller parameters frozen while v/q/z still evolve; content and rate head train; trainable parameter count differs",
        "ordinary": "Same parameter and state counts, sigmoid state evolution, independent state-feature rate gates; changes the overall controller rather than isolating the Call/Put shape",
        "sigmoid_redundancy": "a+p=1 makes q feedback depend on g_call-g_put; identical tensor count does not imply identical functional degrees of freedom",
        "post_training_solver_sensitivity": "For every selected checkpoint, compare test logits, CE and accuracy at registered h and h/2 on the first 64 test episodes. Report both without checkpoint reselection, retraining or replacing primary scores; this is a numerical diagnostic, not extra inferential evidence.",
        "oracle": "Causal deterministic queue/dictionary contract check only; never a learned model result",
        "environment": {
            "python": sys.version,
            "torch": torch.__version__,
            "numpy": np.__version__,
            "platform": platform.platform(),
        },
    }
    for name in protocol["source_sha256"]:
        target = output / "source_snapshot" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PACKAGE / name, target)
    _write_json(output / "protocol.json", protocol)
    _write_json(
        output / "freeze_seal.json",
        {
            "protocol_sha256": _digest(output / "protocol.json"),
            "created_unix": time.time(),
        },
    )
    return {
        "status": "frozen_before_formal_data",
        "candidates": len(candidates),
        "output": str(output),
    }


def prepare(output):
    protocol = _verify_protocol(output)
    manifest = {"new_execution": True, "splits": {}}
    config = TaskConfig(**protocol["task_contract"]["config"])
    for task in TASKS:
        seen = set()
        for split, count in protocol["split_counts"].items():
            data = generate(task, count, protocol["split_seeds"][task][split], config)
            episodes = episode_digests(data)
            if seen & episodes or len(episodes) != count:
                raise RuntimeError("An exact input episode overlaps a registered split")
            seen |= episodes
            path = output / "data" / task / f"{split}.npz"
            path.parent.mkdir(parents=True, exist_ok=True)
            _save_data(path, data)
            manifest["splits"][f"{task}/{split}"] = {
                "count": count,
                "seed": protocol["split_seeds"][task][split],
                "file_sha256": _digest(path),
                "array_sha256": array_digest(data),
            }
    _write_json(output / "data_manifest.json", manifest)
    return {"status": "prepared_sealed_new_data", "splits": len(manifest["splits"])}


def evaluate(model, data, *, predictions=False):
    model.eval()
    ce, correct, queries, exact, examples = 0.0, 0, 0, 0, 0
    collected = []
    with torch.no_grad():
        for start in range(0, len(data["inputs"]), 64):
            x, y, dt = (
                data[name][start : start + 64] for name in ("inputs", "targets", "dt")
            )
            logits = model(x, dt)
            mask = y != -100
            ce += F.cross_entropy(logits[mask], y[mask], reduction="sum").item()
            hit = logits.argmax(-1) == y
            correct += int(hit[mask].sum())
            queries += int(mask.sum())
            exact += int((hit | ~mask).all(dim=1).sum())
            examples += len(x)
            if predictions:
                collected.append(logits.cpu().numpy())
    model.train()
    metrics = {
        "cross_entropy": ce / queries,
        "accuracy": correct / queries,
        "sequence_accuracy": exact / examples,
        "queries": queries,
        "examples": examples,
    }
    return (metrics, np.concatenate(collected)) if predictions else metrics


def _activity(model, initial, gradient_sums):
    result = {}
    for group, members in model.parameter_groups().items():
        rows = []
        for name, value in members:
            delta = value.detach() - initial[name]
            rows.append(
                {
                    "name": name,
                    "requires_grad": value.requires_grad,
                    "numel": value.numel(),
                    "changed_numel": int((delta != 0).sum()),
                    "update_l2": float(delta.norm()),
                    "gradient_l1_sum": gradient_sums.get(name, 0.0),
                }
            )
        result[group] = {
            "update_l2": math.sqrt(sum(row["update_l2"] ** 2 for row in rows)),
            "gradient_l1_sum": sum(row["gradient_l1_sum"] for row in rows),
            "parameters": rows,
        }
    return result


def _train_update(model, optimizer, data, indices, gradient_sums):
    optimizer.zero_grad(set_to_none=True)
    logits = model(data["inputs"][indices], data["dt"][indices])
    targets = data["targets"][indices]
    mask = targets != -100
    loss = F.cross_entropy(logits[mask], targets[mask])
    if not bool(torch.isfinite(loss)):
        raise FloatingPointError("Nonfinite training loss")
    loss.backward()
    norm = torch.nn.utils.clip_grad_norm_(
        model.parameters(), 1.0, error_if_nonfinite=True
    )
    for name, parameter in model.named_parameters():
        if parameter.grad is not None:
            gradient_sums[name] = gradient_sums.get(name, 0.0) + float(
                parameter.grad.abs().sum()
            )
    optimizer.step()
    return float(loss.detach()), float(norm)


def train(output, candidate_id):
    protocol = _verify_protocol(output)
    specification = next(c for c in protocol["candidates"] if c["id"] == candidate_id)
    folder = output / "candidates" / candidate_id
    folder.mkdir(parents=True, exist_ok=False)
    _write_json(folder / "specification.json", specification)
    start_cpu, start_wall = time.process_time(), time.monotonic()
    model = build_model(
        specification["arm"],
        specification["seed"],
        ModelConfig(**protocol["model_config"]),
    )
    initial = _clone_state(model)
    data = _verified_data(output, specification["task"], "train")
    checkpoints = {}

    def checkpoint(name, state, updates, cpu):
        path = folder / f"{name}.npz"
        checkpoints[name] = {
            "file": path.name,
            "sha256": _save_weights(path, state),
            "updates": updates,
            "training_cpu_seconds": cpu,
        }

    checkpoint("step0", initial, 0, 0.0)
    step0 = evaluate(model, data)
    optimizer = torch.optim.Adam(
        [p for p in model.parameters() if p.requires_grad],
        lr=specification["learning_rate"],
    )
    generator = torch.Generator().manual_seed(specification["seed"] + 500000)
    cursor, order, updates, cpu = len(data["inputs"]), None, 0, 0.0
    gradients = {}
    try:
        with (folder / "training_trace.jsonl").open("x", encoding="utf-8") as trace:
            while updates < 384 or cpu < 30:
                tick = time.process_time()
                previous = _clone_state(model)
                previous_cpu, previous_updates = cpu, updates
                if cursor + protocol["batch_size"] > len(data["inputs"]):
                    order = torch.randperm(len(data["inputs"]), generator=generator)
                    cursor = 0
                indices = order[cursor : cursor + protocol["batch_size"]]
                cursor += protocol["batch_size"]
                loss, norm = _train_update(model, optimizer, data, indices, gradients)
                updates += 1
                cpu += time.process_time() - tick
                for limit in (15, 30):
                    name = f"cpu{limit}"
                    if previous_cpu <= limit < cpu and name not in checkpoints:
                        checkpoint(name, previous, previous_updates, previous_cpu)
                if updates in (192, 384):
                    checkpoint(f"update{updates}", _clone_state(model), updates, cpu)
                trace.write(
                    json.dumps(
                        {
                            "update": updates,
                            "training_cpu_seconds": cpu,
                            "loss": loss,
                            "pre_clip_gradient_norm": norm,
                        }
                    )
                    + "\n"
                )
                trace.flush()
        final_metrics = evaluate(model, data)
        with torch.no_grad():
            _, diagnostic = model(
                data["inputs"][:32], data["dt"][:32], return_diagnostics=True
            )
        diagnostic_path = folder / "final_train_diagnostics.npz"
        _save_data(
            diagnostic_path,
            {
                "flow_rate_trace": diagnostic["flow_rate_trace"].numpy(),
                "final_memory": diagnostic["final_memory"].numpy(),
                "final_flow_state": torch.stack(diagnostic["final_state"]).numpy(),
            },
        )
        features = diagnostic["flow_rate_trace"].reshape(-1, 5)
        feature_names = ("margin", "call", "put", "leak", "write_before_role_mask")
        diagnostic_summary = {
            name: {
                "min": float(values.min()),
                "max": float(values.max()),
                "mean": float(values.mean()),
                "std": float(values.std()),
            }
            for name, values in zip(feature_names, features.unbind(-1))
        }
        result = {
            "status": "complete",
            "specification": specification,
            "accounting": model.accounting(),
            "step0_train": step0,
            "final_train": final_metrics,
            "checkpoints": checkpoints,
            "updates": updates,
            "training_cpu_seconds": cpu,
            "total_process_cpu_seconds": time.process_time() - start_cpu,
            "wall_seconds": time.monotonic() - start_wall,
            "diagnostic_sha256": _digest(diagnostic_path),
            "diagnostic_features": diagnostic_summary,
            "parameter_activity": _activity(model, initial, gradients),
        }
        _write_json(folder / "complete.json", result)
        return {
            "candidate": candidate_id,
            "status": "complete",
            "updates": updates,
            "training_cpu_seconds": cpu,
        }
    except Exception as error:
        _write_json(
            folder / "failure.json",
            {
                "type": type(error).__name__,
                "error": str(error),
                "updates": updates,
                "training_cpu_seconds": cpu,
            },
        )
        raise


def select(output):
    protocol = _verify_protocol(output)
    receipts = {
        c["id"]: output / "candidates" / c["id"] / "complete.json"
        for c in protocol["candidates"]
    }
    if not all(path.exists() for path in receipts.values()):
        raise RuntimeError(
            "All registered candidates must finish before validation selection"
        )
    training_seal = {name: _digest(path) for name, path in receipts.items()}
    _write_json(
        output / "all_training_complete_seal.json",
        {
            "complete_sha256": training_seal,
            "created_unix": time.time(),
            "validation_read_yet": False,
        },
    )
    validation = {task: _verified_data(output, task, "validation") for task in TASKS}
    rows, groups = [], {}
    for spec in protocol["candidates"]:
        model = build_model(
            spec["arm"], spec["seed"], ModelConfig(**protocol["model_config"])
        )
        folder = output / "candidates" / spec["id"]
        receipt = json.loads(receipts[spec["id"]].read_text())
        for regime, eligible in protocol["selection_checkpoints"].items():
            for name in eligible:
                cp = receipt["checkpoints"][name]
                if _digest(folder / cp["file"]) != cp["sha256"]:
                    raise RuntimeError("Checkpoint digest mismatch")
                _load_weights(model, folder / cp["file"])
                row = {
                    **spec,
                    "regime": regime,
                    "checkpoint": name,
                    "checkpoint_sha256": cp["sha256"],
                    "validation": evaluate(model, validation[spec["task"]]),
                }
                rows.append(row)
                groups.setdefault(
                    (spec["task"], spec["arm"], spec["seed"], regime), []
                ).append(row)
    selected = [
        min(
            group,
            key=lambda r: (r["validation"]["cross_entropy"], r["checkpoint"], r["id"]),
        )
        for group in groups.values()
    ]
    result = {
        "selection_uses_test": False,
        "all_training_complete_sha256": training_seal,
        "validation_candidates": rows,
        "selected": selected,
    }
    _write_json(output / "selection.json", result)
    _write_json(
        output / "selection_seal.json",
        {
            "selection_sha256": _digest(output / "selection.json"),
            "created_unix": time.time(),
        },
    )
    return {"status": "validation_selection_sealed", "selected_count": len(selected)}


def _comparisons(rows, protocol):
    indexed = {(r["task"], r["arm"], r["seed"], r["regime"]): r for r in rows}
    comparisons = []
    for comparator in ("matched_c1", "sigmoid", "ordinary"):
        multiplicity = 4 if comparator == "matched_c1" else 8
        p = 1 - 0.05 / (2 * multiplicity)
        z = 2 * p - 1
        t_critical = math.sqrt(2) * z / math.sqrt(1 - z * z)
        for task in TASKS:
            for regime in protocol["selection_checkpoints"]:
                left = [indexed[task, "analytic", seed, regime] for seed in SEEDS]
                right = [indexed[task, comparator, seed, regime] for seed in SEEDS]
                quality = all(
                    r["validation"]["accuracy"] >= 0.9 for r in left + right
                ) and all(r["test"]["accuracy"] >= 0.9 for r in left)
                for metric in ("accuracy", "cross_entropy"):
                    differences = np.array(
                        [
                            a["test"][metric] - b["test"][metric]
                            for a, b in zip(left, right)
                        ]
                    )
                    if metric == "cross_entropy":
                        differences = -differences
                    mean = float(differences.mean())
                    radius = t_critical * float(differences.std(ddof=1)) / math.sqrt(3)
                    comparisons.append(
                        {
                            "task": task,
                            "regime": regime,
                            "comparator": comparator,
                            "metric": metric,
                            "positive_favors_analytic": True,
                            "paired_seed_differences": differences.tolist(),
                            "mean": mean,
                            "adjusted_ci": [mean - radius, mean + radius],
                            "family_size": multiplicity,
                            "quality_floor_passed": quality,
                            "metric_improvement_gate": quality
                            and mean - radius > 0
                            and mean >= protocol["minimum_mean_effect"][metric],
                        }
                    )
    return comparisons


def score(output):
    protocol = _verify_protocol(output)
    seal = json.loads((output / "selection_seal.json").read_text())
    if _digest(output / "selection.json") != seal["selection_sha256"]:
        raise RuntimeError("Selection was modified after sealing")
    selection = json.loads((output / "selection.json").read_text())
    for name, digest in selection["all_training_complete_sha256"].items():
        if _digest(output / "candidates" / name / "complete.json") != digest:
            raise RuntimeError("A training receipt changed after selection")
    tests = {task: _verified_data(output, task, "test") for task in TASKS}
    prediction_dir = output / "predictions"
    prediction_dir.mkdir(exist_ok=False)
    rows, step0, seen = [], [], set()
    for selected in selection["selected"]:
        model = build_model(
            selected["arm"], selected["seed"], ModelConfig(**protocol["model_config"])
        )
        identity = (selected["task"], selected["arm"], selected["seed"])
        if identity not in seen:
            step0.append(
                {
                    "task": identity[0],
                    "arm": identity[1],
                    "seed": identity[2],
                    "test": evaluate(model, tests[identity[0]]),
                }
            )
            seen.add(identity)
        cp = output / "candidates" / selected["id"] / f"{selected['checkpoint']}.npz"
        if _digest(cp) != selected["checkpoint_sha256"]:
            raise RuntimeError("Selected checkpoint digest mismatch")
        _load_weights(model, cp)
        metrics, logits = evaluate(model, tests[selected["task"]], predictions=True)
        subset = {name: value[:64] for name, value in tests[selected["task"]].items()}
        model.flow.max_step = protocol["model_config"]["max_step"] / 2
        refined_metrics, refined_logits = evaluate(model, subset, predictions=True)
        targets = subset["targets"]
        mask = targets != -100
        registered_logits = torch.from_numpy(logits[:64])
        hits = registered_logits.argmax(-1) == targets
        registered_metrics = {
            "cross_entropy": float(
                F.cross_entropy(registered_logits[mask], targets[mask])
            ),
            "accuracy": float(hits[mask].float().mean()),
            "sequence_accuracy": float((hits | ~mask).all(dim=1).float().mean()),
            "queries": int(mask.sum()),
            "examples": len(targets),
        }
        difference = logits[:64] - refined_logits
        sensitivity = {
            "registered_h": protocol["model_config"]["max_step"],
            "refined_h": model.flow.max_step,
            "episodes": 64,
            "registered_metrics": registered_metrics,
            "refined_metrics": refined_metrics,
            "max_abs_logit_difference": float(np.abs(difference).max()),
            "relative_logit_l2_difference": float(
                np.linalg.norm(difference) / max(np.linalg.norm(refined_logits), 1e-12)
            ),
            "used_for_selection": False,
        }
        path = prediction_dir / f"{selected['id']}__{selected['regime']}.npz"
        _save_data(
            path,
            {
                "logits": logits,
                "targets": tests[selected["task"]]["targets"].numpy(),
                "refined_logits_first64": refined_logits,
            },
        )
        rows.append(
            {
                **selected,
                "test": metrics,
                "solver_sensitivity": sensitivity,
                "prediction_file": str(path.relative_to(output)),
                "prediction_sha256": _digest(path),
            }
        )
    result = {
        "new_execution": True,
        "old_results_recovered": False,
        "results": rows,
        "step0": step0,
        "comparisons": _comparisons(rows, protocol),
        "frozen_flow_is_diagnostic": True,
        "scope": "Two synthetic tasks with a common explicit causal address prior and rank-one memory; no multimodal or Transformer superiority inference",
    }
    _write_json(output / "results.json", result)
    return {
        "status": "test_scored_once_after_selection",
        "selected_models": len(rows),
        "step0_models": len(step0),
    }


def qualify(output, updates, learning_rate, max_step):
    """Retained train-only development attempt, outside the formal dataset."""
    output.mkdir(parents=True, exist_ok=False)
    config = ModelConfig(max_step=max_step)
    attempt = {
        "new_execution": True,
        "formal_validation_or_test_read": False,
        "development_only": True,
        "source_sha256": _sources(),
        "updates": updates,
        "learning_rate": learning_rate,
        "model_config": asdict(config),
        "results": [],
    }
    _write_json(
        output / "attempt_specification.json",
        {k: v for k, v in attempt.items() if k != "results"},
    )
    for name in attempt["source_sha256"]:
        target = output / "source_snapshot" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PACKAGE / name, target)
    for j, task in enumerate(TASKS):
        raw = generate(task, 128, 390001 + j)
        _save_data(output / f"{task}_train_only.npz", raw)
        data = _tensor_data(raw)
        model = build_model("ordinary", 391001 + j, config)
        initial = _clone_state(model)
        _save_weights(output / f"{task}_step0.npz", initial)
        before = evaluate(model, data)
        optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
        generator = torch.Generator().manual_seed(392001 + j)
        gradients, cpu = {}, 0.0
        with (output / f"{task}_trace.jsonl").open("x") as trace:
            for update in range(updates):
                start = time.process_time()
                indices = torch.randperm(128, generator=generator)[:32]
                loss, norm = _train_update(model, optimizer, data, indices, gradients)
                cpu += time.process_time() - start
                trace.write(
                    json.dumps(
                        {
                            "update": update + 1,
                            "loss": loss,
                            "gradient_norm": norm,
                            "training_cpu_seconds": cpu,
                        }
                    )
                    + "\n"
                )
                trace.flush()
        after = evaluate(model, data)
        _save_weights(output / f"{task}_final.npz", model.state_dict())
        attempt["results"].append(
            {
                "task": task,
                "arm": "ordinary",
                "step0_train": before,
                "final_train": after,
                "training_cpu_seconds": cpu,
                "accounting": model.accounting(),
                "parameter_activity": _activity(model, initial, gradients),
            }
        )
    _write_json(output / "development_results.json", attempt)
    return {
        "status": "development_only",
        "results": [
            {
                k: row[k]
                for k in ("task", "step0_train", "final_train", "training_cpu_seconds")
            }
            for row in attempt["results"]
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase", choices=("qualify", "freeze", "prepare", "train", "select", "score")
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate")
    parser.add_argument("--max-step", type=float, default=0.0625)
    parser.add_argument("--updates", type=int, default=64)
    parser.add_argument("--learning-rate", type=float, default=0.003)
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    if args.phase == "qualify":
        result = qualify(args.output, args.updates, args.learning_rate, args.max_step)
    elif args.phase == "freeze":
        result = freeze(args.output, args.max_step)
    elif args.phase == "prepare":
        result = prepare(args.output)
    elif args.phase == "train":
        result = train(args.output, args.candidate)
    elif args.phase == "select":
        result = select(args.output)
    else:
        result = score(args.output)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
