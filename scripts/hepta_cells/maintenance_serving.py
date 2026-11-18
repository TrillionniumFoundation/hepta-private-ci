"""Durable maintenance inference and same-candidate cold recovery."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import time

import numpy as np

from .bundle import Bundle
from .lifecycle import Budget, CellOwner, Partition
from .temporal import TemporalConfig, TemporalKernel
from .maintenance_tasks import Compiler, observations, repair, save, sources
from .maintenance_execution import DiagnosticComponent, RuntimeBinding, cell_output
from .maintenance_metrics import Measurement


@contextmanager
def measure_window(windows, stage, scope, **metadata):
    """Retain successful and failed inclusive windows without adding them."""
    meter = Measurement(stage, scope, parent_scope="campaign")
    row = dict(stage=stage, scope=scope, **metadata)
    windows.append(row)
    try:
        with meter:
            yield row
    finally:
        row["measurement"] = meter.result
        row["wall_ns"] = meter.result["wall_ns"] if meter.result else None


def serve(owner, kernel, bound, task, episode, arm, *, runtime, active=False):
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    run = "active" if active else task["id"] + "-" + arm
    partition = Partition(
        "controlled-fixture", "active" if active else arm, kernel.cell_id, run
    )
    component, candidate_hash = runtime.component(owner, kernel, bound, run)
    if active:
        owner.reset(partition, component, component.identity.digest)
    else:
        owner.create(
            partition,
            component,
            budget=Budget(max_work_units=100000, max_elapsed_ms=10000),
            total_work_units=100000000,
        )
    receipts = []
    for index, event in enumerate(episode):
        if arm == "no_memory" and index:
            owner.reset(partition, component, component.identity.digest)
        receipts.append(
            owner.step(
                partition,
                component,
                task["id"] + f"-event-{index}",
                {
                    "operation": "observe",
                    "cursor": 0 if arm == "no_memory" else index,
                    "observation": event.tolist(),
                },
            )
        )
    actions = np.eye(4) if kernel.cell_id == "predictor" else np.zeros((1, 1))
    predictions = [
        owner.step(
            partition,
            component,
            task["id"] + f"-predict-{i}",
            {"operation": "predict", "action": action.tolist()},
        )
        for i, action in enumerate(actions)
    ]
    logits = np.asarray([cell_output(row)["logits"] for row in predictions])
    if kernel.cell_id == "predictor":
        probabilities = np.exp(logits - logits.max(axis=1, keepdims=True))
        chosen = int(np.argmax(probabilities[:, 1] / probabilities.sum(axis=1)))
    else:
        chosen = int(np.argmax(logits[0]))
    receipt = predictions[chosen if kernel.cell_id == "predictor" else 0]
    return dict(
        action=chosen,
        receipts=receipts + predictions,
        chosen_logits=cell_output(receipt)["logits"],
        predict_action=actions[chosen if kernel.cell_id == "predictor" else 0].tolist(),
        wall_ns=time.perf_counter_ns() - wall,
        cpu_ns=time.process_time_ns() - cpu,
        parameter_work=sum(row["work_units"] for row in receipts + predictions),
        candidate_manifest_sha256=candidate_hash,
        wrapper_identity_digest=component.identity.digest,
    )


def serve_diagnostic(owner, cell, task, diagnostic, runtime):
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    partition = Partition("controlled-fixture", "deterministic", cell, task["id"])
    component, candidate_hash = runtime.wrap(
        owner, DiagnosticComponent(cell, runtime.plan_hash)
    )
    owner.create(partition, component)
    receipt = owner.step(
        partition, component, task["id"] + "-diagnostic", {"diagnostic": diagnostic}
    )
    return dict(
        action=cell_output(receipt)["action"],
        receipts=[receipt],
        parameter_work=receipt["work_units"],
        wall_ns=time.perf_counter_ns() - wall,
        cpu_ns=time.process_time_ns() - cpu,
        candidate_manifest_sha256=candidate_hash,
        wrapper_identity_digest=component.identity.digest,
    )


def recover(spec_path):
    spec = json.loads(Path(spec_path).read_text())
    root = Path(spec["root"])
    windows = []
    try:
        with measure_window(
            windows,
            "recovery",
            "cold model/owner restore, exact inference and optional D task",
            cell=spec["cell"],
        ):
            result = _recover(spec_path, windows)
        result["cost_windows"] = windows
        save(root / "COLD_RESULT.json", result)
    except BaseException as error:
        save(
            root / "COLD_FAILURE.json",
            dict(
                error=f"{type(error).__name__}: {error}",
                cost_windows=windows,
            ),
        )
        raise


def _recover(spec_path, windows):
    spec = json.loads(Path(spec_path).read_text())
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    if sources() != spec["sources"]:
        raise ValueError("cold source identity changed")
    root = Path(spec["root"])
    kernel, state = TemporalKernel.restore_checkpoint(
        root / "live.npz",
        expected_sha256=spec["model_hash"],
        cell_id=spec["cell"],
        config=TemporalConfig(**spec["config"]),
    )
    owner = CellOwner(root / "owner.sqlite")
    runtime = RuntimeBinding(**spec["runtime"])
    component, _ = runtime.component(
        owner,
        kernel,
        Bundle(**spec["bundle"]),
        "active",
        expected_manifest=spec["candidate_manifest_sha256"],
    )
    if component.identity.digest != spec["wrapper_identity_digest"]:
        raise ValueError("cold wrapper identity differs from active version")
    partition = Partition("controlled-fixture", "active", spec["cell"], "active")
    try:
        checkpoint = owner.checkpoint(partition)
        if checkpoint != spec["checkpoint"] or checkpoint["state"] != state:
            raise ValueError("cold durable state changed")
        receipt = owner.step(
            partition,
            component,
            "cold-new-prediction",
            {"operation": "predict", "action": spec["predict_action"]},
        )
        if cell_output(receipt)["logits"] != spec["expected_logits"]:
            raise ValueError("cold actual inference differs")
        result = dict(
            pid=os.getpid(),
            receipt=receipt,
            matches_pre_restart=True,
            wall_ns=time.perf_counter_ns() - wall,
            cpu_ns=time.process_time_ns() - cpu,
            candidate_manifest_sha256=spec["candidate_manifest_sha256"],
            wrapper_identity_digest=component.identity.digest,
        )
        if spec.get("semantic") is True:
            task = spec["new_task"]
            with measure_window(
                windows,
                "task",
                "fresh original diagnostic, Cell inference, repair and semantic check",
                phase="D-cold",
                cell=spec["cell"],
                arm="selected",
                task_id=task["id"],
                diagnostic_scope="fresh diagnostic included; no shared diagnostic allocation",
            ) as task_cost:
                compiler = Compiler(
                    root,
                    time.perf_counter(),
                    semantic=True,
                    filename="cold-compile.jsonl",
                )
                original = compiler.check(task, task["source"], "D-cold", "observation")
                use = serve(
                    owner,
                    kernel,
                    Bundle(**spec["bundle"]),
                    task,
                    observations(task, original),
                    "active",
                    runtime=runtime,
                    active=True,
                )
                use["outcome"] = compiler.check(
                    task,
                    repair(task["source"], use["action"]),
                    "D-cold",
                    spec["cell"] + "-selected",
                )
            use["task_cost"] = task_cost
            result.update(
                new_task=use,
                cold_compile_calls=compiler.calls,
                semantic_subprocesses=compiler.semantic_calls,
                wall_ns=time.perf_counter_ns() - wall,
                cpu_ns=time.process_time_ns() - cpu,
            )
        return result
    finally:
        owner.close()
        runtime.close()
