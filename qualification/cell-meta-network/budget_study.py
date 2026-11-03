"""Bounded shared-runtime continuation of the existing structure study.

The new question is task-value credit under one measured total CPU allowance,
including a lower-capacity pruning comparator. It does not replace prior results.
"""

import time

PROCESS_CPU_START = time.process_time()
PROCESS_WALL_START = time.perf_counter()

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import resource
import sys
import traceback

import numpy as np
import torch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "memory-cell-adapters"))
from corpus import PROGRAMS, bits
from runtime_contract import decode_bits, execute_program
from structure_models import Structure, canonical, digest, fit
from structure_train import phases
from tensor_cell import TensorCell


def task_value(raw_bits, policies, event_probes):
    predicted = [decode_bits(row) for row in raw_bits]
    policy_correct = sum(a == b for a, b in zip(predicted, policies, strict=True))
    correct, count = 0, 0
    for predicted_policy, expected_policy in zip(predicted, policies, strict=True):
        for program in PROGRAMS:
            for event in event_probes:
                actual = execute_program(event, predicted_policy, program)
                expected = execute_program(event, expected_policy, program)
                correct += actual == expected
                count += 1
    return {"policy_correct": policy_correct, "policy_count": len(policies),
            "task_correct": correct, "task_count": count,
            "utility": 0.5 * policy_correct / len(policies) + 0.5 * correct / count}


def outputs(structure, features, entities):
    with torch.no_grad():
        return (structure(features, entities).sigmoid() >= 0.5).numpy()


def prune(structure, features, policies, protocol):
    """Training-prefix task utility chooses removals; all attempts are charged."""
    cell = structure.cells[0]
    parent_digest = cell.parameter_digest()
    kept = list(range(cell.config.rank))
    attempts = []
    entities = torch.arange(8)
    before = task_value(outputs(structure, features, entities), policies, protocol["event_probes"])
    while len(kept) > protocol["pruned_rank"]:
        candidates = []
        for channel in kept:
            with torch.no_grad():
                column = cell.B[:, channel].clone()
                cell.B[:, channel].zero_()
            value = task_value(outputs(structure, features, entities), policies, protocol["event_probes"])
            with torch.no_grad():
                cell.B[:, channel].copy_(column)
            candidates.append((value["utility"], channel, value))
        _, selected, value = max(candidates, key=lambda row: (row[0], -row[1]))
        with torch.no_grad():
            cell.B[:, selected].zero_()
        kept.remove(selected)
        attempts.append({"removed_channel": selected, "candidates": candidates, "selected_task_value": value})
    child = TensorCell(replace(cell.config, rank=len(kept), cell_id="task-value-pruned"),
                       cell.base_encoder_sha, cell.source_ids, head=cell.head)
    with torch.no_grad():
        child.A.copy_(cell.A[kept])
        child.B.copy_(cell.B[:, kept])
    child.parents = [{"cell_id": cell.config.cell_id, "parameter_sha256": parent_digest}]
    structure.cells = torch.nn.ModuleList([child])
    after = task_value(outputs(structure, features, entities), policies, protocol["event_probes"])
    return {"before": before, "after": after, "retained_channels": kept, "attempts": attempts}


def local_credit(structure, prior, prior_routes, features, policies, protocol):
    entities = torch.arange(8)
    measured = task_value(outputs(structure, features, entities), policies, protocol["event_probes"])
    cells = []
    for index, cell in enumerate(structure.cells):
        current = (cell.A.detach().clone(), cell.B.detach().clone())
        with torch.no_grad():
            cell.A.copy_(prior[index][0])
            cell.B.copy_(prior[index][1])
        counterfactual = task_value(outputs(structure, features, entities), policies, protocol["event_probes"])
        with torch.no_grad():
            cell.A.copy_(current[0])
            cell.B.copy_(current[1])
        cells.append({"cell_index": index, "task_value_delta": measured["utility"] - counterfactual["utility"],
                      "counterfactual": counterfactual})
    current_routes = structure.routes.copy()
    structure.routes = prior_routes
    old_route_value = task_value(outputs(structure, features, entities), policies, protocol["event_probes"])
    structure.routes = current_routes
    return {"observed": measured, "cells": cells,
            "routing_task_value_delta": measured["utility"] - old_route_value["utility"]}


def run_arm(fixture, output, protocol, seed, arm, shared_cpu, data):
    cpu, wall = time.process_time(), time.perf_counter()
    budget = protocol["cpu_seconds_per_arm_including_shared_setup"] - shared_cpu
    if budget <= protocol["evaluation_reserve_seconds"]:
        raise ValueError("shared setup exhausted the equal allowance")
    parent = TensorCell.load(fixture / "models" / f"seed-{seed}" / "semantic", data["identity"])
    structure = Structure(parent, "monolith" if arm == "pruning" else arm)
    with torch.no_grad():
        expected = parent(data["canonical"])
        actual = structure(data["canonical"], torch.arange(8))
    initial_error = float((expected - actual).abs().max())
    if not torch.allclose(expected, actual, rtol=1e-5, atol=1e-5):
        raise ValueError("initial parent function changed")
    output.mkdir(parents=True, exist_ok=False)
    records = []
    allowance = budget - protocol["evaluation_reserve_seconds"]
    for phase in phases():
        phase_cpu = time.process_time()
        target = torch.tensor([bits(phase["policies"][i]) for i in data["entities"]], dtype=torch.float32)
        before = task_value(outputs(structure, data["canonical"], torch.arange(8)), phase["policies"], protocol["event_probes"])
        pruning = prune(structure, data["canonical"], phase["policies"], protocol) if arm == "pruning" and phase["phase"] == 1 else None
        prior = [(cell.A.detach().clone(), cell.B.detach().clone()) for cell in structure.cells]
        prior_routes = structure.routes.copy()
        route = structure.propose_routes(data["x"], target, data["addresses"])
        deadline = cpu + allowance * phase["phase"] / len(phases()) - protocol["phase_finalize_reserve_seconds"]
        fit_started = time.process_time()
        receipt = fit(structure, data["x"], target, data["addresses"], seed=seed + phase["phase"],
                      steps=protocol["maximum_steps"], batch_size=protocol["batch_size"],
                      learning_rate=protocol["learning_rate"], cpu_budget_seconds=max(0.0, deadline - fit_started),
                      budget_started=fit_started)
        credit = local_credit(structure, prior, prior_routes, data["canonical"], phase["policies"], protocol)
        for cell in structure.cells:
            cell.source_ids.add(digest(canonical(phase)))
        checkpoint = output / f"phase-{phase['phase']}"
        storage = structure.save(checkpoint)
        restored = Structure.load(checkpoint, data["identity"])
        if not np.array_equal(outputs(restored, data["x"], data["addresses"]), outputs(structure, data["x"], data["addresses"])):
            raise ValueError("checkpoint restore changed typed predictions")
        if structure.counts()["trainable"] > protocol["maximum_trainable_parameters"]:
            raise ValueError("parameter upper bound exceeded")
        records.append({"phase": phase["phase"], "before_task_value": before, "credit": credit,
                        "pruning": pruning, "selector": route, "fit": receipt, "storage": storage,
                        "counts": structure.counts(), "phase_cpu_seconds": time.process_time() - phase_cpu})
        structure = restored
    return {"arm": arm, "seed": seed, "phases": records, "shared_setup_cpu_allocation": shared_cpu,
            "initial_parent_max_abs_error": initial_error, "counts": structure.counts(),
            "training_cpu_seconds": time.process_time() - cpu, "training_wall_seconds": time.perf_counter() - wall,
            "common_parent_parameter_sha256": parent.parameter_digest(),
            "stored_bytes": sum(path.stat().st_size for path in output.rglob("*") if path.is_file())}


def evaluate(fixture, output, protocol, records, identity):
    # The published held set is opened only after all candidate optimization.
    opened = time.monotonic_ns()
    held = json.loads((fixture / "held-evaluator-rows.json").read_bytes())
    selected = [i for i, row in enumerate(held) if row["role"] == "semantic"]
    entities = np.asarray([held[i]["entity"] for i in selected], dtype=np.int64)
    with np.load(fixture / "held-encoded.npz", allow_pickle=False) as archive:
        features = torch.from_numpy(archive["features"][selected].copy())
    for record in records:
        if record.get("error"):
            continue
        cpu = time.process_time()
        scored, previous = [], set()
        for phase in phases():
            model = Structure.load(output / f"{record['seed']}-{record['arm']}" / f"phase-{phase['phase']}", identity)
            raw = outputs(model, features, torch.from_numpy(entities))
            expected = np.asarray([bits(phase["policies"][entity]) for entity in entities], dtype=bool)
            correct = (raw == expected).all(1)
            untouched = ~np.isin(entities, sorted(previous | set(phase["changed_entities"])))
            groups = {}
            for i, source_index in enumerate(selected):
                group = groups.setdefault(held[source_index]["wording_group"], {"correct": 0, "count": 0})
                group["correct"] += int(correct[i]); group["count"] += 1
            scored.append({"phase": phase["phase"], "correct": int(correct.sum()), "count": len(correct),
                           "untouched_correct": int(correct[untouched].sum()), "untouched_count": int(untouched.sum()),
                           "wording_groups": groups, "predicted_bits": raw.astype(int).tolist()})
            previous |= set(phase["changed_entities"])
        record["held"] = scored
        record["evaluation_cpu_seconds"] = time.process_time() - cpu
        record["charged_cpu_seconds"] = record["shared_setup_cpu_allocation"] + record["training_cpu_seconds"] + record["evaluation_cpu_seconds"]
        record["budget_valid"] = record["charged_cpu_seconds"] <= protocol["cpu_seconds_per_arm_including_shared_setup"]
    return opened


def run(args):
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    if hasattr(os, "sched_setaffinity"):
        os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    fixture, output = args.fixture.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    protocol = json.loads((ROOT / "BUDGET_PROTOCOL.json").read_bytes())
    source_paths = [ROOT / name for name in ("budget_study.py", "BUDGET_PROTOCOL.json", "structure_models.py", "structure_train.py")]
    source_paths += [ROOT.parent / "memory-cell-adapters" / name for name in ("tensor_cell.py", "corpus.py", "runtime_contract.py")]
    sources = {str(path.relative_to(ROOT.parent)): digest(path.read_bytes()) for path in source_paths}
    inputs = {name: digest((fixture / name).read_bytes()) for name in ("development.json", "development_features.npz", "development-encoder.json", "held-evaluator-rows.json", "held-encoded.npz")}
    (output / "FREEZE.json").write_bytes(canonical({"source": sources, "inputs": inputs, "protocol": protocol,
                                                   "held_access_before_training": "hash bytes only; published exploratory set"}))
    development = json.loads((fixture / "development.json").read_bytes())
    selected = [i for i, row in enumerate(development["train"]) if row["role"] == "semantic"]
    identity = json.loads((fixture / "development-encoder.json").read_bytes())["base_encoder_sha"]
    with np.load(fixture / "development_features.npz", allow_pickle=False) as archive:
        features = np.concatenate([archive["semantic"], archive["train"][selected]])
        canonical_features = archive["semantic"].copy()
    entities = np.asarray(list(range(8)) + [development["train"][i]["entity"] for i in selected], dtype=np.int64)
    data = {"identity": identity, "x": torch.from_numpy(features), "entities": entities,
            "addresses": torch.from_numpy(entities), "canonical": torch.from_numpy(canonical_features)}
    # Materialize the optimizer's shared lazy imports once, with a real parent.
    setup_parent = TensorCell.load(fixture / "models" / f"seed-{protocol['seeds'][0]}" / "semantic", identity)
    torch.optim.Adam(setup_parent.parameters(), lr=protocol["learning_rate"])
    del setup_parent
    shared_cpu = time.process_time() - PROCESS_CPU_START
    count = len(protocol["seeds"]) * len(protocol["arms"])
    records = []
    for index, seed in enumerate(protocol["seeds"]):
        arms = protocol["arms"][index:] + protocol["arms"][:index]
        for arm in arms:
            started, wall = time.process_time(), time.perf_counter()
            try:
                record = run_arm(fixture, output / f"{seed}-{arm}", protocol, seed, arm, shared_cpu / count, data)
            except Exception:
                record = {"arm": arm, "seed": seed, "error": traceback.format_exc(), "budget_valid": False,
                          "failed_cpu_seconds": time.process_time() - started, "failed_wall_seconds": time.perf_counter() - wall}
            records.append(record)
            (output / f"{seed}-{arm}.receipt.json").write_bytes(canonical(record))
            print(json.dumps({"arm": arm, "seed": seed, "failed": bool(record.get("error"))}), flush=True)
    finished = time.monotonic_ns()
    opened = evaluate(fixture, output, protocol, records, identity)
    if sources != {str(path.relative_to(ROOT.parent)): digest(path.read_bytes()) for path in source_paths}:
        raise ValueError("source changed during study")
    observed_cpu = time.process_time() - PROCESS_CPU_START
    direct_cpu = sum(row.get("training_cpu_seconds", row.get("failed_cpu_seconds", 0)) + row.get("evaluation_cpu_seconds", 0) for row in records)
    shared_overhead = max(0.0, observed_cpu - shared_cpu - direct_cpu)
    for record in records:
        record["shared_runtime_overhead_allocation"] = shared_overhead / count
        record["charged_cpu_seconds"] = (shared_cpu + shared_overhead) / count + record.get("training_cpu_seconds", record.get("failed_cpu_seconds", 0)) + record.get("evaluation_cpu_seconds", 0)
        record["budget_valid"] = not record.get("error") and record["charged_cpu_seconds"] <= protocol["cpu_seconds_per_arm_including_shared_setup"]
    summary = {}
    for arm in protocol["arms"]:
        rows = [row for row in records if row["arm"] == arm]
        scored = [phase for row in rows for phase in row.get("held", [])]
        summary[arm] = {"held_correct": sum(row["correct"] for row in scored), "held_count": sum(row["count"] for row in scored),
                        "untouched_correct": sum(row["untouched_correct"] for row in scored), "untouched_count": sum(row["untouched_count"] for row in scored),
                        "all_budget_valid": all(row.get("budget_valid", False) for row in rows),
                        "failures": sum(bool(row.get("error")) for row in rows),
                        "charged_cpu_seconds": sum(row.get("charged_cpu_seconds", row.get("failed_cpu_seconds", 0)) for row in rows)}
    result = {"schema": "hepta.structure-total-budget-result.v1", "summary": summary, "records": records,
              "protocol": protocol, "shared_setup_cpu_seconds": shared_cpu, "shared_runtime_overhead_cpu_seconds": shared_overhead, "shared_process_pid": os.getpid(),
              "causal_order_verified": finished < opened, "training_finished_ns": finished, "held_opened_ns": opened,
              "observed_process_cpu_seconds_before_report": observed_cpu,
              "observed_process_wall_seconds_before_report": time.perf_counter() - PROCESS_WALL_START,
              "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              "full_cost_exact": False, "unmeasured_cost": ["interpreter startup before module clock", "report serialization and outer transport", "historical parent training and encoder creation"],
              "scope": "shared Python runtime; existing precomputed features; finite task; no native production activation"}
    (output / "RESULT.json").write_bytes(canonical(result))
    print(json.dumps(summary, sort_keys=True), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
