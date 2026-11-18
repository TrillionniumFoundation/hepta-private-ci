#!/usr/bin/env python3
"""Exercise code, parameter and state updates on one frozen native Cell stack.

This is a local native qualifier unless an outer configured-runtime job binds
its request, result and process evidence. The parameter example consumes the
same campaign's originals; it does not invent another training success.
"""

import argparse
import copy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from hepta_cells.bundle import Bundle, OPTIONAL, REQUIRED
from hepta_cells.component_types import ComponentIdentity, StepResult, digest
from hepta_cells.hia_component import HiaCellComponent
from hepta_cells.lifecycle import Budget, CellError, CellOwner, Partition, PendingExecution, Qualification
from hepta_cells.maintenance_execution import freeze_native, load_transport, numeric_identity
from hepta_cells.maintenance_metrics import Measurement, summarize_tasks
from hepta_cells.maintenance_tasks import save, sources
from hepta_cells.temporal import TemporalConfig, TemporalKernel
from hepta_cells.temporal_component import TemporalComponent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def native_from(spec):
    module = load_transport(spec["worker_path"], spec["worker_sha256"])
    return module.NativeCellBridge(Path(spec["hepta_root"]), Path(spec["image_path"]), spec["image_sha256"], expected_source_sha256=spec["source_sha256"])


class SumComponent:
    """Two exact integer implementations; both retain the same state semantics."""

    def __init__(self, version):
        if version not in ("loop", "builtin"):
            raise ValueError("unknown implementation")
        self.version = version
        self.identity = ComponentIdentity("updates.integer-sum." + version, digest([sha(__file__), version]))

    def initial_state(self):
        return {"total": 0, "steps": 0}

    def step(self, payload, state, context):
        values = payload["values"]
        if set(payload) != {"values"} or type(values) is not list or len(values) != 4096 or any(type(x) is not int or abs(x) > 100 for x in values):
            raise CellError("sum input differs from frozen bounded domain")
        if context.identity != self.identity:
            raise CellError("sum implementation identity differs")
        if self.version == "loop":
            value = 0
            for item in values:
                value += item
        else:
            value = sum(values)
        return StepResult({"sum": value}, {"total": state["total"] + value, "steps": state["steps"] + 1}, len(values))

    def migrate_state_from(self, source, state):
        if type(source) is not SumComponent or type(self) is not SumComponent or set(state) != {"total", "steps"} or any(type(x) is not int for x in state.values()):
            raise CellError("sum state relation differs")
        return dict(state)


def wrap(owner, native, inner, plan_hash, native_spec, root, label):
    manifest = {"schema": "hepta.update-instance.v1", "plan_sha256": plan_hash, "inner_identity": asdict(inner.identity), "image_sha256": native_spec["image_sha256"], "transport_sha256": native_spec["worker_sha256"], "label": label}
    candidate_hash = save(root / (label + "-candidate.json"), manifest)
    return HiaCellComponent(owner, inner, native, candidate_sha256=candidate_hash, image_sha256=native_spec["image_sha256"])


def code_update(owner, native, plan_hash, native_spec, root):
    components = {name: wrap(owner, native, SumComponent(name), plan_hash, native_spec, root, name) for name in ("loop", "builtin")}
    partitions = {name: Partition("updates", name, "code", "sum") for name in components}
    for name in components:
        owner.create(partitions[name], components[name], budget=Budget(max_work_units=10000, max_elapsed_ms=10000))
    rows = {name: [] for name in components}
    for task in range(24):
        values = [(index * 17 + task * 13) % 201 - 100 for index in range(4096)]
        order = ("loop", "builtin") if task % 2 == 0 else ("builtin", "loop")
        receipts = {}
        for name in order:
            with Measurement("task", f"code-{name}-{task}", parent_scope="updates") as meter:
                receipt = owner.step(partitions[name], components[name], f"task-{task}", {"values": values})
            rows[name].append({"measurement": meter.result, "wall_ns": meter.result["wall_ns"], "receipt": receipt})
            receipts[name] = receipt
        if receipts["loop"]["output"]["cell"] != receipts["builtin"]["output"]["cell"] or receipts["loop"]["state_digest"] != receipts["builtin"]["state_digest"]:
            raise ValueError("optimized output or state differs")
    evaluation = save(root / "CODE_BENCHMARK.json", rows)
    source, target = components["loop"], components["builtin"]
    qualification = Qualification(source.identity.digest, target.identity.digest, evaluation)
    owner.qualify = lambda q: q == qualification
    # The measured migration pilot is charged to optimization, never baseline.
    pilot = Partition("updates", "migration-pilot", "code", "sum")
    owner.create(pilot, source)
    checkpoint = owner.checkpoint(pilot)
    with Measurement("migration", "code-migration-pilot", parent_scope="updates") as transition:
        migrated = owner.migrate(pilot, source, target, qualification, operation_id="pilot", checkpoint_id=checkpoint["digest"])
    elapsed = {name: sum(row["wall_ns"] for row in values) for name, values in rows.items()}
    measured_candidate = elapsed["builtin"] + transition.result["wall_ns"]
    # These measurements omit compiler/build and physical meters. A local speed
    # comparison cannot establish the requested complete-cost adoption gate.
    reason = "complete build/energy/process-tree memory cost is not measured"
    return {"decision": "NoUpdate", "reason": reason, "outputs_and_states_equal": True, "task_pairs": 24, "observed_wall_gain_after_pilot": measured_candidate < elapsed["loop"], "measured_wall_ns": elapsed, "candidate_plus_pilot_wall_ns": measured_candidate, "distributions": {name: summarize_tasks(values, scope="whole native owner call, including admission and settlement") for name, values in rows.items()}, "pilot_migration": migrated, "pilot_cost": transition.result, "selected_identity": source.identity.digest, "benchmark_sha256": evaluation, "full_system_cost_known": False}


def model_pair():
    kernel = TemporalKernel("memory", TemporalConfig(3, 1, 2, hidden_dim=4, seed=7641))
    parts = {name: digest(["updates", name]) for name in REQUIRED}
    parts.update({name: None for name in OPTIONAL})
    parts.update(base=kernel.kernel_sha256, heads=kernel.heads_sha256, composition=kernel.config.sha256)
    source = TemporalComponent(kernel, Bundle("original", 1, parts), "migration")
    updated = copy.deepcopy(kernel)
    updated._model.params["by"][0] += 0.25
    bundle = source.bundle.successor("readout", {**parts, "heads": updated.heads_sha256}, digest("no-training"), digest("readout-delta-0.25"), digest("migration-state-check"))
    return source, TemporalComponent(updated, bundle, "migration")


def state_update(owner, native, plan_hash, native_spec, root):
    old, new = model_pair()
    source = wrap(owner, native, old, plan_hash, native_spec, root, "gru-original")
    target = wrap(owner, native, new, plan_hash, native_spec, root, "gru-readout")
    partition = Partition("updates", "migration", "memory", "migration")
    owner.create(partition, source)
    for index, observation in enumerate(([0.5, -1.0, 0.25], [-0.5, 0.2, 0.75])):
        owner.step(partition, source, f"observe-{index}", {"operation": "observe", "cursor": index, "observation": observation})
    before = owner.checkpoint(partition)
    qualification = Qualification(source.identity.digest, target.identity.digest, digest(["readout-state-relation", before["digest"]]))
    owner.qualify = lambda q: q == qualification
    with Measurement("migration", "gru-readout-migration", parent_scope="updates") as migration:
        receipt = owner.migrate(partition, source, target, qualification, operation_id="upgrade-readout", checkpoint_id=before["digest"])
    if receipt["target_checkpoint"]["state"] != {**before["state"], "weights_sha256": new.kernel.weights_sha256}:
        raise ValueError("migration changed hidden state")
    replay = owner.migrate(partition, source, target, qualification, operation_id="upgrade-readout", checkpoint_id=before["digest"])
    if replay != receipt:
        raise ValueError("migration replay differs")
    predicted = owner.step(partition, target, "warm-predict", {"operation": "predict", "action": [0.0]})
    state = owner.checkpoint(partition)["state"]
    checkpoint_hash = new.kernel.checkpoint(root / "MIGRATED_MODEL.npz", state)
    spec = {"root": str(root), "model_sha256": checkpoint_hash, "config": asdict(new.kernel.config), "bundle": asdict(new.bundle), "state": state, "partition": asdict(partition), "native": native_spec, "wrapper_identity": asdict(target.identity), "candidate_sha256": target.candidate_sha256, "expected_logits": predicted["output"]["cell"]["logits"], "source_sha256": sha(__file__)}
    save(root / "COLD_REQUEST.json", spec)
    with Measurement("recovery", "fresh-child-restore-and-inference", parent_scope="updates") as cold:
        process = subprocess.run([sys.executable, "-B", __file__, "--cold", str(root / "COLD_REQUEST.json")], capture_output=True, text=True, timeout=30)
    save(root / "COLD_PROCESS.json", {"returncode": process.returncode, "stdout": process.stdout, "stderr": process.stderr, "cost": cold.result})
    if process.returncode:
        raise RuntimeError("cold migration inference failed: " + process.stderr)
    result = read(root / "COLD_RESULT.json")
    if result["pid"] == os.getpid() or result["receipt"]["output"]["cell"]["logits"] != spec["expected_logits"]:
        raise ValueError("cold process did not preserve selected prediction")
    # An actual native INVOKE_CELL followed by an injected inner failure stays
    # pending. Neither cancellation nor attempted upgrade erases the original.
    uncertain = Partition("updates", "pending-control", "memory", "migration")
    owner.create(uncertain, source)
    pending_checkpoint = owner.checkpoint(uncertain)
    original_step = old.step
    def fail_after_native_begin(*_):
        raise RuntimeError("injected failure after native dispatch")
    old.step = fail_after_native_begin
    try:
        try:
            owner.step(uncertain, source, "unfinished", {"operation": "predict", "action": [0.0]})
        except PendingExecution:
            pass
        else:
            raise ValueError("fault did not remain pending")
    finally:
        old.step = original_step
    owner.request_cancel(uncertain, source, "unfinished")
    source.observe_cancellation(uncertain, "unfinished")
    pending = owner.status(uncertain)
    try:
        owner.migrate(uncertain, source, target, qualification, operation_id="blocked-upgrade", checkpoint_id=pending_checkpoint["digest"])
    except PendingExecution:
        pass
    else:
        raise ValueError("unsettled native invocation was migrated")
    if owner.status(uncertain) != pending:
        raise ValueError("refused migration changed pending owner")
    return {"status": "IDLE_READOUT_MIGRATION_AND_COLD_INFERENCE_PASS", "migration": receipt, "migration_cost": migration.result, "cold_cost": cold.result, "cold": result, "pending_control": pending, "pending_continuation": source.continuation_status(uncertain, "unfinished"), "pending_preserved": True, "same_owner_and_partition": True, "cross_owner_or_effectful_migration": False, "external_business_effect_counts": None}


def cold_restore(path):
    spec = read(path)
    if sha(__file__) != spec["source_sha256"]:
        raise ValueError("cold source changed")
    root = Path(spec["root"])
    kernel, state = TemporalKernel.restore_checkpoint(root / "MIGRATED_MODEL.npz", expected_sha256=spec["model_sha256"], cell_id="memory", config=TemporalConfig(**spec["config"]))
    if state != spec["state"]:
        raise ValueError("model state differs from migration checkpoint")
    owner, native = CellOwner(root / "owner.sqlite"), native_from(spec["native"])
    try:
        inner = TemporalComponent(kernel, Bundle(**spec["bundle"]), "migration")
        component = HiaCellComponent(owner, inner, native, candidate_sha256=spec["candidate_sha256"], image_sha256=spec["native"]["image_sha256"])
        partition = Partition(**spec["partition"])
        if asdict(component.identity) != spec["wrapper_identity"] or owner.checkpoint(partition)["state"] != state:
            raise ValueError("cold owner/candidate differs")
        receipt = owner.step(partition, component, "cold-new-predict", {"operation": "predict", "action": [0.0]})
        save(root / "COLD_RESULT.json", {"pid": os.getpid(), "receipt": receipt})
    finally:
        owner.close()
        native.close()


def parameter_originals(path, native_spec):
    root, result = Path(path).parent.resolve(), read(path)
    plan = read(root / "PLAN.json")
    if result["plan_sha256"] != sha(root / "PLAN.json") or set(result["cells"]) != {"memory", "predictor"}:
        raise ValueError("parameter campaign plan or Cell coverage differs")
    if plan["native"]["image_sha256"] != native_spec["image_sha256"]:
        raise ValueError("parameter campaign used another native image")
    # The campaign imports semantic/serving modules which this read-only review
    # need not execute. Compare their actual bytes, not sys.modules membership.
    for name, expected in plan["source_sha256"].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".py":
            raise ValueError("parameter campaign has an invalid source path")
        if sha(Path(__file__).parent / relative) != expected:
            raise ValueError("parameter campaign used another Cell source: " + name)
    cells = {}
    for cell, summary in result["cells"].items():
        directory = root / cell
        decision, cold = read(directory / "DECISION.json"), read(directory / "COLD_RESULT.json")
        served, cold_request = read(directory / "C_SERVED.json"), read(directory / "COLD_REQUEST.json")
        if summary["decision"] != decision or summary["cold"] != cold or decision["decision"] not in ("Adopt", "NoUpdate") or cold["candidate_manifest_sha256"] != decision["selected_candidate_manifest_sha256"]:
            raise ValueError("parameter decision/selected version differs")
        if not served or sum(row["outcome"]["success"] for row in served) != summary["C_successes"] or any(row["candidate_manifest_sha256"] != decision["selected_candidate_manifest_sha256"] for row in served):
            raise ValueError("parameter new-task result or selected version differs")
        if cold["wrapper_identity_digest"] != decision["selected_identity"] or cold["receipt"]["output"]["cell"]["logits"] != cold_request["expected_logits"] or sha(directory / "live.npz") != cold_request["model_hash"]:
            raise ValueError("parameter cold inference/model differs")
        db = sqlite3.connect((directory / "owner.sqlite").as_uri() + "?mode=ro", uri=True)
        try:
            partition = Partition("controlled-fixture", "active", cell, "active")
            row = db.execute("SELECT identity FROM cells WHERE partition=?", (partition.digest,)).fetchone()
            if row is None or digest(json.loads(row[0])) != decision["selected_identity"]:
                raise ValueError("parameter owner active identity differs")
            pending = db.execute("SELECT count(*) FROM intents WHERE status='pending'").fetchone()[0]
        finally:
            db.close()
        cells[cell] = {"decision": decision, "C_successes": summary["C_successes"], "cold_exact": cold["matches_pre_restart"], "pending": pending, "decision_sha256": sha(directory / "DECISION.json"), "cold_sha256": sha(directory / "COLD_RESULT.json")}
    return {"source_result_sha256": sha(path), "source_plan_sha256": sha(root / "PLAN.json"), "cells": cells, "new_training_performed_by_this_qualifier": False}


def run(output, native_build_record, learning_result):
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    native_spec = freeze_native(root, native_build_record)
    plan = {"schema": "hepta.three-update-examples.v1", "source_sha256": {**sources(), Path(__file__).name: sha(__file__), "hepta_cells/maintenance_metrics.py": sha(Path(__file__).parent / "hepta_cells/maintenance_metrics.py")}, "native": native_spec, "numeric": numeric_identity(), "code_tasks": {"pairs": 24, "integers_per_task": 4096, "values": "(index*17+task*13)%201-100", "order": "alternating", "gate": "equal outputs/state and complete-cost saving; missing full costs means NoUpdate"}, "migration": "pure idle GRU readout change, same owner/partition/native; pending transition refuses", "learning_result_sha256": sha(learning_result), "scope": "local native; configured-runtime authority requires external job binding"}
    plan_hash = save(root / "PLAN.json", plan)
    owner, native = CellOwner(root / "owner.sqlite"), native_from(native_spec)
    whole = Measurement("updates", "updates")
    try:
        with whole:
            code = code_update(owner, native, plan_hash, native_spec, root)
            state = state_update(owner, native, plan_hash, native_spec, root)
            parameters = parameter_originals(learning_result, native_spec)
        result = {"status": "THREE_UPDATE_EXAMPLES_OBSERVED", "plan_sha256": plan_hash, "code": code, "parameters": parameters, "state": state, "cost": whole.result, "configured_runtime_verified_by_this_qualifier": False, "full_system_cost_known": False, "ordinary_daemon_adoption": False}
        save(root / "RESULT.json", result)
        return result
    except BaseException as error:
        save(root / "FAILURE.json", {"error": type(error).__name__ + ": " + str(error), "cost": whole.result})
        raise
    finally:
        owner.close()
        native.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--native-build-record", type=Path)
    parser.add_argument("--learning-result", type=Path)
    parser.add_argument("--cold", type=Path)
    args = parser.parse_args()
    if args.cold:
        cold_restore(args.cold)
    elif args.output and args.native_build_record and args.learning_result:
        print(json.dumps(run(args.output, args.native_build_record, args.learning_result), sort_keys=True, allow_nan=False))
    else:
        parser.error("supply --output --native-build-record --learning-result, or --cold")
