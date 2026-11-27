"""Execute a synthetic parameter-layout control, never authorize differentiation.

A task-conditioned shared bank and separate private heads represent the same
linear functions. Both use the real SemanticComponent producer and SQLite owner.
The selected-head arithmetic is identical; total physical cost is not certified.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import time

import numpy as np

from .lifecycle import Budget, CellOwner, Partition
from .semantic import (
    CallableFeatureBackend,
    LocalHead,
    LocalObjective,
    SemanticBinding,
    SemanticCell,
    SharedSemanticPool,
    _digest,
)
from .semantic_component import SemanticComponent, semantic_bundle


TASKS, WIDTH, TRAIN_ROWS, EVAL_ROWS = 2, 4, 24, 16
ARMS = ("frozen", "shared_bank", "routed_heads")
COUNTERS = (
    "provider_calls",
    "provider_rows",
    "feature_copy_scalars",
    "input_bytes",
    "route_decisions",
    "head_calls",
    "forward_mac",
    "gradient_mac",
    "optimizer_steps",
    "parameter_update_scalars",
    "owner_work_units",
    "forward_bias_adds",
    "gradient_bias_adds",
    "training_mse_values",
)


def _write(root, name, value):
    with (root / name).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _event(root, **value):
    with (root / "EVENTS.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _sources():
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(Path(__file__).parent.glob("*.py"))
    }


class _Bank:
    def __init__(self, arm, seed, heads):
        self.arm, self.counters = arm, dict.fromkeys(COUNTERS, 0)
        self.layout_copy_scalars, self.layout_write_scalars = 0, 0
        if arm == "routed_heads":
            self.storage = tuple(heads)
        else:
            self.storage = LocalHead(
                np.concatenate([h.first for h in heads], axis=1),
                np.concatenate([h.bias for h in heads]),
            )
        pin = _digest("synthetic-task-labelled-identity-features-v1")
        self.binding = SemanticBinding(*(pin for _ in range(5)))
        self.pool = SharedSemanticPool()

        def encode(inputs):
            rows = np.asarray(inputs, dtype=np.float64)
            if rows.shape != (len(inputs), WIDTH + 1) or not np.isfinite(rows).all():
                raise ValueError("bounded task-labelled numeric rows required")
            if not np.isin(rows[:, 0], (0, 1)).all():
                raise ValueError("unknown task identity")
            self.counters["provider_calls"] += 1
            self.counters["provider_rows"] += len(rows)
            self.counters["feature_copy_scalars"] += len(rows) * WIDTH
            self.counters["input_bytes"] += rows.nbytes
            return rows[:, 1:].copy()

        self.pool.register_backend(
            CallableFeatureBackend(self.binding, WIDTH, encode, lambda: pin)
        )
        self.bundles = [
            semantic_bundle(self.cell(task), f"ref:{seed}:{arm}:{task}")
            for task in range(TASKS)
        ]

    def head(self, task):
        if type(task) is not int or not 0 <= task < TASKS:
            raise ValueError("known integer task identity required")
        if self.arm == "routed_heads":
            return self.storage[task]
        return LocalHead(
            self.storage.first[:, task : task + 1],
            self.storage.bias[task : task + 1],
        )

    def cell(self, task):
        return SemanticCell(
            f"task{task}",
            self.binding,
            self.head(task),
            LocalObjective("mse", 1, "synthetic-linear-target"),
        )

    def component(self, task):
        return SemanticComponent(self.pool, self.cell(task), self.bundles[task])

    def replace(self, task, component, candidate):
        if self.arm == "frozen":
            raise ValueError("frozen control cannot train")
        if self.arm == "routed_heads":
            updated = list(self.storage)
            updated[task] = candidate.head
            self.storage = tuple(updated)
        else:
            first, bias = self.storage.first.copy(), self.storage.bias.copy()
            self.layout_copy_scalars += first.size + bias.size
            first[:, task : task + 1], bias[task : task + 1] = (
                candidate.head.first,
                candidate.head.bias,
            )
            self.layout_write_scalars += (
                candidate.head.first.size + candidate.head.bias.size
            )
            self.storage = LocalHead(first, bias)
        self.bundles[task] = component.bundle


def _evaluate(bank, owner, phase, task, inputs, *, dense=False):
    before = bank.counters.copy()
    bank.counters["route_decisions"] += len(inputs)
    selected, receipts, last = None, [], None
    for invoked in range(TASKS) if dense else (task,):
        component = bank.component(invoked)
        partition = Partition(
            "synthetic",
            bank.arm,
            f"task{invoked}",
            f"phase{phase}:task{task}:dense{int(dense)}",
        )
        owner.create(partition, component, budget=Budget(max_elapsed_ms=60000))
        payload = {"inputs": inputs.tolist()}
        receipt = owner.step(partition, component, "evaluate", payload)
        if receipt["status"] != "committed":
            raise RuntimeError("reference inference did not commit")
        bank.counters["head_calls"] += 1
        bank.counters["forward_mac"] += len(inputs) * WIDTH
        bank.counters["forward_bias_adds"] += len(inputs)
        bank.counters["owner_work_units"] += receipt["work_units"]
        if invoked == task:
            selected = np.asarray(receipt["output"]["logits"])
        receipts.append(receipt)
        last = partition, component, payload, receipt
    return (
        selected,
        receipts,
        {key: bank.counters[key] - before[key] for key in COUNTERS},
        last,
    )


def _arm(root, arm, seed, steps, data, initial):
    wall, cpu = time.perf_counter(), time.process_time()
    bank = _Bank(arm, seed, initial)
    database = root / f"{seed}-{arm}.sqlite"
    owner = CellOwner(database)
    result, arrays, dense_cost = (
        {"training": [], "panels": []},
        {},
        dict.fromkeys(COUNTERS, 0),
    )
    try:
        for phase in range(TASKS):
            if arm != "frozen":
                inputs, targets = data[phase]["train"]
                bank.counters["route_decisions"] += len(inputs)
                _event(
                    root,
                    status="started",
                    stage="training",
                    arm=arm,
                    seed=seed,
                    phase=phase,
                )
                component, candidate = bank.component(phase).propose(
                    list(inputs),
                    targets,
                    artifact_id=f"fit:{seed}:{arm}:{phase}",
                    evaluation_profile=_digest("public-synthetic-layout-reference-v1"),
                    steps=steps,
                    learning_rate=0.1,
                )
                receipt = candidate.training_receipt
                completed, rows = receipt["completed_steps"], receipt["items"]
                if (
                    receipt["status"] != "completed"
                    or completed != steps
                    or rows != len(inputs)
                ):
                    raise RuntimeError(
                        "training receipt does not cover the frozen work roster"
                    )
                _event(
                    root,
                    status="completed",
                    stage="training",
                    arm=arm,
                    seed=seed,
                    phase=phase,
                    receipt=receipt,
                    bundle=component.bundle.record(),
                )
                bank.counters["optimizer_steps"] += completed
                bank.counters["head_calls"] += completed + 2
                bank.counters["forward_mac"] += rows * WIDTH * (completed + 2)
                bank.counters["gradient_mac"] += rows * WIDTH * completed
                bank.counters["forward_bias_adds"] += rows * (completed + 2)
                bank.counters["gradient_bias_adds"] += (rows - 1) * completed
                bank.counters["training_mse_values"] += rows * (completed + 2)
                bank.counters["parameter_update_scalars"] += (WIDTH + 1) * completed
                bank.replace(phase, component, candidate)
                checkpoint = f"{seed}-{arm}-fit{phase}.npz"
                with (root / checkpoint).open("xb") as stream:
                    np.savez(
                        stream, weights=candidate.head.first, bias=candidate.head.bias
                    )
                result["training"].append(receipt)
                _event(
                    root,
                    status="completed",
                    stage="checkpoint",
                    arm=arm,
                    seed=seed,
                    phase=phase,
                    checkpoint=checkpoint,
                )
            for task in range(TASKS):
                head = bank.head(task)
                arrays[f"phase{phase}_task{task}_weights"] = head.first
                arrays[f"phase{phase}_task{task}_bias"] = head.bias
                inputs, targets = data[task]["evaluation"]
                predicted, receipts, cost, last = _evaluate(
                    bank, owner, phase, task, inputs
                )
                arrays[f"phase{phase}_task{task}_predictions"] = predicted
                panel = {
                    "phase": phase,
                    "task": task,
                    "predictions": predicted.tolist(),
                    "targets": targets.tolist(),
                    "mse": float(np.mean((predicted - targets) ** 2)),
                    "receipts": receipts,
                    "selected_cost": cost,
                }
                if arm == "routed_heads":
                    dense, dense_receipts, extra, _ = _evaluate(
                        bank, owner, phase, task, inputs, dense=True
                    )
                    if not np.array_equal(predicted, dense):
                        raise RuntimeError(
                            "dense selection differs from selected-only inference"
                        )
                    panel.update(dense_receipts=dense_receipts, dense_cost=extra)
                    for key in COUNTERS:
                        dense_cost[key] += extra[key]
                result["panels"].append(panel)
            _event(
                root,
                status="completed",
                stage="evaluation",
                arm=arm,
                seed=seed,
                phase=phase,
            )
        owner.close()
        owner = CellOwner(database)
        before = bank.counters.copy()
        partition, component, payload, original = last
        replay = owner.step(partition, component, "evaluate", payload)
        if replay != original or before != bank.counters:
            raise RuntimeError(
                "journal reopen changed the receipt or repeated model work"
            )
    finally:
        owner.close()
    with (root / f"{seed}-{arm}.npz").open("xb") as stream:
        np.savez(stream, **arrays)
    result.update(
        parameters=sum(
            bank.head(t).first.size + bank.head(t).bias.size for t in range(TASKS)
        ),
        counters={key: bank.counters[key] - dense_cost[key] for key in COUNTERS},
        dense_additional_counters=dense_cost,
        explicit_layout_copy_scalars=bank.layout_copy_scalars,
        explicit_layout_indexed_writes=bank.layout_write_scalars,
        old_task_predictions_retained=np.array_equal(
            arrays["phase0_task0_predictions"], arrays["phase1_task0_predictions"]
        ),
        owner_reopened_same_process=True,
        replay_without_model_execution=True,
        wall_seconds_including_dense=time.perf_counter() - wall,
        cpu_seconds_including_dense=time.process_time() - cpu,
        resident_byte_seconds=None,
        energy_joules=None,
        full_cost_known=False,
    )
    return result, arrays


def run_reference(output, *, seeds=(17, 29, 43), steps=24):
    """Create immutable original arrays, journals and receipts for bounded real fits."""
    if (
        type(seeds) is not tuple
        or not 1 <= len(seeds) <= 8
        or any(type(seed) is not int or not 0 <= seed < 2**32 for seed in seeds)
        or len(set(seeds)) != len(seeds)
    ):
        raise ValueError("one to eight distinct integer seeds required")
    if type(steps) is not int or not 1 <= steps <= 128:
        raise ValueError("one to 128 optimizer steps required")
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    sources = _sources()
    protocol = {
        "schema": "hepta.cell.differentiation-layout-reference.v1",
        "seeds": seeds,
        "steps": steps,
        "arms": ARMS,
        "source_sha256": sources,
        "tasks": TASKS,
        "features": WIDTH,
        "train_rows": TRAIN_ROWS,
        "evaluation_rows": EVAL_ROWS,
        "task_order": [0, 1],
        "learning_rate": 0.1,
        "scope": "synthetic disjoint linear readouts; shared bank and separate heads have identical hypotheses",
        "task_information": "all arms receive the same task ID and numeric input",
        "dense_control": "same routed parameters, all heads executed; no additional training",
        "cost_scope": "receipt-derived active linear MAC and update-scalar counts; not hardware instructions",
        "training_mse_values": "training loss elements only; evaluator scoring is outside this arithmetic counter",
        "exclusions": [
            "Python/NumPy allocation and validation operation counts",
            "complete dependency cost",
            "resident-byte integrals",
            "energy",
            "final report serialization",
        ],
        "python": platform.python_version(),
        "numpy": np.__version__,
        "decision": "NoUpdate",
        "scientific_acceptance": "HOLD",
        "adoption_authorized": False,
    }
    _write(root, "PROTOCOL.json", protocol)
    reports = []
    try:
        for seed in seeds:
            rng = np.random.default_rng(seed)
            initial = tuple(
                LocalHead(rng.normal(0, 0.05, (WIDTH, 1)), np.zeros(1))
                for _ in range(TASKS)
            )
            data, inputs_archive = [], {}
            for task in range(TASKS):
                teacher = rng.normal(size=(WIDTH, 1))
                samples = {}
                for split, rows in (("train", TRAIN_ROWS), ("evaluation", EVAL_ROWS)):
                    features = rng.normal(size=(rows, WIDTH))
                    inputs = np.column_stack((np.full(rows, task), features))
                    targets = features @ teacher
                    samples[split] = inputs, targets
                    inputs_archive[f"task{task}_{split}_inputs"] = inputs
                    inputs_archive[f"task{task}_{split}_targets"] = targets
                inputs_archive[f"task{task}_initial_weights"] = initial[task].first
                inputs_archive[f"task{task}_initial_bias"] = initial[task].bias
                inputs_archive[f"task{task}_teacher"] = teacher
                data.append(samples)
            with (root / f"{seed}-inputs.npz").open("xb") as stream:
                np.savez(stream, **inputs_archive)
            arms, snapshots = {}, {}
            for arm in ARMS:
                arms[arm], snapshots[arm] = _arm(root, arm, seed, steps, data, initial)
            shared, routed = arms["shared_bank"], arms["routed_heads"]
            equal = all(
                np.array_equal(value, snapshots["routed_heads"][key])
                for key, value in snapshots["shared_bank"].items()
            )
            matched = (
                shared["counters"] == routed["counters"]
                and shared["parameters"] == routed["parameters"]
            )
            data_equal = [r["dataset_digest"] for r in shared["training"]] == [
                r["dataset_digest"] for r in routed["training"]
            ]
            if not equal or not matched or not data_equal:
                raise RuntimeError("task-conditioned layout controls diverged")
            reports.append(
                {
                    "seed": seed,
                    "arms": arms,
                    "parameters_and_predictions_equal": equal,
                    "active_arithmetic_and_exposure_matched": matched and data_equal,
                    "total_physical_compute_matched": False,
                }
            )
        if _sources() != sources:
            raise RuntimeError("source changed during the reference execution")
        artifacts = {
            path.name: {
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in sorted(root.iterdir())
            if path.is_file()
        }
        result = {
            "schema": "hepta.cell.differentiation-layout-result.v1",
            "status": "REFERENCE_EQUIVALENT",
            "runs": reports,
            "artifacts": artifacts,
            "fits": len(seeds) * TASKS * 2,
            "optimizer_steps": len(seeds) * TASKS * 2 * steps,
            "independent_real_tasks": 0,
            "negative_transfer_tested": False,
            "learned_routing_tested": False,
            "native_population_adoption_tested": False,
            "full_physical_cost_known": False,
            "total_physical_compute_matched": False,
            "scientific_acceptance": "HOLD",
            "decision": "NoUpdate",
            "adoption_authorized": False,
            "interpretation": "equivalent task-conditioned layout control, no evidence that splitting improves quality",
        }
        _write(root, "RESULT.json", result)
        return result
    except Exception as error:
        failure_receipt = getattr(error, "receipt", None)
        _event(
            root,
            status="failed",
            error_type=type(error).__name__,
            error=str(error),
            training_receipt=failure_receipt,
        )
        _write(
            root,
            "FAILURE.json",
            {
                "status": "FAILED",
                "error_type": type(error).__name__,
                "error": str(error),
                "training_receipt": failure_receipt,
                "decision": "NoUpdate",
                "adoption_authorized": False,
            },
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = run_reference(args.output)
    print(
        json.dumps(
            {
                key: result[key]
                for key in ("status", "fits", "optimizer_steps", "decision")
            }
        )
    )


if __name__ == "__main__":
    main()
