"""Replay owner, invalidation and reproducible parameter-memory experiments.

The source/training ledger is deliberately separate from serving artifacts. This
is a research owner; production adoption remains with Hepta's existing owners.
"""

from copy import deepcopy
import hashlib
from pathlib import Path
import time
import zlib

import numpy as np

from .cells import AssociativeCell, canonical, execute_program
from .evolution import CellEnsemble, EvolutionController, partitions


class LearningSession:
    """Keep immutable examples and cleanly rebuild a source-scoped memory cell."""

    def __init__(self, kind="semantic", *, seed=0, steps=400):
        if kind not in {"semantic", "procedure"}:
            raise ValueError("unsupported learning session type")
        self.kind, self.seed, self.steps = kind, seed, steps
        self.events, self.latest, self.revoked, self.tombstones = {}, {}, set(), set()
        self.model, self.blocked, self.generation = None, False, 0
        self.versions, self.ledger = [], []

    def write(self, event_id, key, value):
        if not isinstance(event_id, str) or not 0 < len(event_id) <= 256:
            raise ValueError("invalid event identity")
        row = {"event_id": event_id, "key": key, "value": deepcopy(value), "kind": self.kind}
        canonical(row)
        if event_id in self.events:
            if self.events[event_id] != row:
                raise ValueError("event identity reused with changed payload")
            return
        if event_id in self.revoked or key in self.tombstones:
            raise ValueError("revoked event/key requires a new scoped identity")
        self.events[event_id] = row
        self.latest[key] = event_id
        self.blocked = self.model is not None
        self.ledger.append({"operation": "write", "event_id": event_id})

    def revoke(self, event_id):
        if event_id not in self.events:
            raise ValueError("unknown source event")
        self.revoked.add(event_id)
        key = self.events[event_id]["key"]
        if self.latest.get(key) == event_id:
            self.tombstones.add(key)
        if self.model is not None and event_id in self.model.lineage_sources:
            self.blocked = True
        self.ledger.append({"operation": "revoke", "event_id": event_id})

    def valid_records(self):
        return [
            deepcopy(self.events[event_id])
            for key, event_id in sorted(self.latest.items())
            if key not in self.tombstones and event_id not in self.revoked
        ]

    def rebuild(self, *, inherit=False):
        records = self.valid_records()
        if not records:
            raise ValueError("no valid memory rows")
        if inherit and self.model is not None and set(self.model.lineage_sources) & self.revoked:
            raise ValueError("revoked parameter ancestry requires a clean fit")
        parent = self.model if inherit else None
        model = AssociativeCell.fit(
            [row["key"] for row in records],
            [row["value"] for row in records],
            self.seed,
            support_ids=[[row["event_id"]] for row in records],
            kind=self.kind,
            steps=self.steps,
            parent=parent,
        )
        if set(model.lineage_sources) & self.revoked:
            raise ValueError("new artifact still depends on a revoked source")
        self.generation += 1
        self.model, self.blocked = model, False
        self.versions.append(model.to_bytes())
        receipt = {
            "operation": "incremental-replay" if inherit else "clean-replay-rebuild",
            "generation": self.generation,
            "parameter_digest": model.parameters_digest(),
            "valid_rows": len(records),
            "replay_source_bytes": len(canonical(records)),
            "excluded_sources": sorted(self.revoked),
            "lineage_sources": model.lineage_sources,
            "training": deepcopy(model.training_receipt),
            "cost": model.cost(),
            "statistical_unlearning_proved": False,
        }
        self.ledger.append(receipt)
        return receipt

    def read(self, key):
        if self.blocked:
            return {"value": None, "abstain": "rebuild-required", "support_ids": []}
        if self.model is None:
            return {"value": None, "abstain": "untrained", "support_ids": []}
        return {**self.model.read(key), "generation": self.generation}

    def cost(self):
        return {
            "current_model_bytes": 0 if self.model is None else len(self.model.to_bytes()),
            "all_retained_version_bytes": sum(len(value) for value in self.versions),
            "immutable_source_ledger_bytes": len(canonical(self.events)),
            "maintenance_ledger_bytes": len(canonical(self.ledger)),
            "revocation_bytes": len(canonical(sorted(self.revoked))),
            "training_cpu_seconds": sum(row.get("training", {}).get("cpu_seconds", 0) for row in self.ledger),
        }


def _accuracy(reader, records):
    started = time.perf_counter()
    reads = [reader.read(row["key"]) for row in records]
    correct = sum(read.get("abstain") is None and read["value"] == row["value"] for read, row in zip(reads, records))
    result = {
        "correct": correct,
        "rows": len(records),
        "accuracy": correct / len(records),
        "read_seconds": time.perf_counter() - started,
        "reads": reads,
    }
    if isinstance(reader, CellEnsemble):
        work = sum(
            cell.dimension * cell.hidden + cell.hidden * len(cell.catalog)
            for read in reads
            if "cell_index" in read
            for cell in [reader._load(read["cell_index"])]
        )
        result.update(read_work_proxy=work, mean_read_work_proxy=work / len(records))
    return result


def _test_cost(proposal, candidate, baseline):
    comparison = proposal["forecast_cost_comparison"]
    config = proposal["frozen_cost_configuration"]
    if comparison is None:
        return None
    candidate_rate = 1 - candidate["accuracy"] + config["inference_work_price"] * candidate["mean_read_work_proxy"]
    baseline_rate = 1 - baseline["accuracy"] + config["inference_work_price"] * baseline["mean_read_work_proxy"]
    return {
        "candidate": comparison["candidate"],
        "baseline": comparison["baseline"],
        "test_rows": candidate["rows"],
        "forecast_queries": config["expected_future_queries"],
        "projected_net_benefit": config["expected_future_queries"] * (baseline_rate - candidate_rate)
        - comparison["upfront_excess"],
        "all_search_upfront_included": True,
        "selection_changed_after_test": False,
        "measured_full_cost_net_benefit_proved": False,
        "scope": "independent test errors/work with frozen scenario prices; not measured dollars or energy",
    }


def run_learning_study(seed, output_dir, *, expected_future_queries=10_000):
    """Execute one disclosed synthetic write/maintenance/structure experiment.

    Random values are created for new opaque entities. These experiments measure
    memory mechanisms and costs; they are not independent natural-language or
    universal-memory evidence. Source values are visible during writes by design.
    """
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    started_wall, started_cpu = time.perf_counter(), time.process_time()
    rng = np.random.default_rng(seed)
    factors = rng.integers(1, 9, size=40)
    keys = [f"project-{seed}/entity-{hashlib.sha256(f'{seed}:{i}'.encode()).hexdigest()[:12]}" for i in range(40)]
    records = [
        {
            "event_id": f"semantic-{seed}-{i}",
            "key": key,
            "kind": "semantic",
            "value": {"factor": int(factors[i]), "label": f"group-{int(factors[i])}"},
        }
        for i, key in enumerate(keys)
    ]
    session = LearningSession(seed=seed)
    for row in records[:24]:
        session.write(row["event_id"], row["key"], row["value"])
    initial_receipt = session.rebuild()
    initial = _accuracy(session, records[:24])
    for row in records[24:32]:
        session.write(row["event_id"], row["key"], row["value"])
    append_guard = session.read(keys[0])
    append_receipt = session.rebuild(inherit=True)
    replay = _accuracy(session, records[:32])
    # Same initialization, output catalog, steps and optimizer; only the rows
    # replayed differ. Raw predictions bypass the narrower serving-support gate.
    parent = AssociativeCell.from_bytes(session.versions[0])
    recent = AssociativeCell.fit(
        keys[24:32],
        [row["value"] for row in records[24:32]],
        seed,
        support_ids=[[row["event_id"]] for row in records[24:32]],
        parent=parent,
        catalog_values=session.model.catalog,
    )
    raw_old = recent.probabilities(keys[:24]).argmax(axis=1)
    raw_replay = session.model.probabilities(keys[:24]).argmax(axis=1)
    old_predictions = [
        {"key": row["key"], "expected": row["value"], "actual": recent.catalog[int(index)]}
        for index, row in zip(raw_old, records[:24])
    ]
    no_replay = {
        "raw_old_correct": sum(row["actual"] == row["expected"] for row in old_predictions),
        "old_rows": 24,
        "raw_old_predictions": old_predictions,
        "replay_raw_old_correct": sum(
            session.model.catalog[int(index)] == row["value"] for index, row in zip(raw_replay, records[:24])
        ),
        "initial_raw_old_correct": initial["correct"],
        "matched_catalog": recent.catalog == session.model.catalog,
        "matched_initial_parameters": recent.training_receipt["initial_parameters"]
        == session.model.training_receipt["initial_parameters"],
        "catalog_digest": recent.training_receipt["catalog_digest"],
        "initial_catalog_classes": len(parent.catalog),
        "update_catalog_classes": len(recent.catalog),
        "serving_old_accepted": sum(recent.read(key)["abstain"] is None for key in keys[:24]),
        "cost": recent.cost(),
        "training": recent.training_receipt,
        "scope": "same-catalog parameter interference; support rejection is not counted as forgetting",
        "equal_optimizer_steps": True,
        "equal_examples_seen": False,
    }
    recent_path = output / "no-replay.cell.json"
    recent_path.write_bytes(recent.to_bytes())
    before_change = session.read(keys[3])["value"]
    corrected = {"factor": int(factors[3]) + 11, "label": "corrected-group"}
    session.write(f"semantic-{seed}-correction", keys[3], corrected)
    correction_receipt = session.rebuild()
    changed = session.read(keys[3])
    session.revoke(records[5]["event_id"])
    deletion_guard = session.read(keys[6])
    deletion_receipt = session.rebuild()
    deleted = session.read(keys[5])
    surviving = _accuracy(session, session.valid_records())
    clean_reference = AssociativeCell.fit(
        [row["key"] for row in session.valid_records()],
        [row["value"] for row in session.valid_records()],
        seed,
        support_ids=[[row["event_id"]] for row in session.valid_records()],
        steps=session.steps,
    )
    clean_match = clean_reference.parameters_digest() == session.model.parameters_digest()
    session.model.calibrate(keys[:3], [records[i]["value"] for i in range(3)])
    counterfactual = {
        "before": before_change,
        "after": changed,
        "target": corrected,
        "changed_correctly": before_change != corrected and changed["value"] == corrected,
    }
    procedure = LearningSession("procedure", seed=seed)
    opcodes = ("identity", "add_bias", "multiply", "affine", "clamp")
    for i, key in enumerate(keys[:32]):
        program = {"opcode": opcodes[i % len(opcodes)], "bias": i % 7, "limit": 20 + i}
        procedure.write(f"procedure-{seed}-{i}", key, program)
    procedure_receipt = procedure.rebuild()
    procedure_reads = _accuracy(procedure, procedure.valid_records())
    composition_rows = []
    for i, key in enumerate(keys[:32]):
        semantic, program = session.read(key), procedure.read(key)
        if semantic["abstain"] is not None:
            continue
        value = int(rng.integers(-15, 16))
        actual = execute_program(program["value"], value, semantic["value"])
        gold_semantic = next(row["value"] for row in session.valid_records() if row["key"] == key)
        gold_program = procedure.events[procedure.latest[key]]["value"]
        expected = execute_program(gold_program, value, gold_semantic)
        composition_rows.append(
            {
                "key": key,
                "event_value": value,
                "actual": actual,
                "expected": expected,
                "semantic_support": semantic["support_ids"],
                "procedure_support": program["support_ids"],
            }
        )
    # New domain entities are written before their first read; no base-model
    # knowledge can supply their randomized associations.
    transfer = LearningSession(seed=seed + 7)
    for i, row in enumerate(records[32:]):
        transfer.write(f"transfer-{seed}-{i}", "new-domain/" + row["key"], row["value"])
    transfer.rebuild()
    transfer_reads = _accuracy(transfer, transfer.valid_records())
    structure_records = session.valid_records()
    old_records = [row for row in structure_records if row["key"] in keys[:24]]
    new_records = [row for row in structure_records if row["key"] in keys[24:32]]
    retention, selection = old_records[:8], new_records[:4]
    test = old_records[8:] + new_records[4:]
    evaluation = {
        "selection_keys": [row["key"] for row in selection],
        "selection_values": [row["value"] for row in selection],
        "retention_keys": [row["key"] for row in retention],
        "retention_values": [row["value"] for row in retention],
    }
    controller = EvolutionController(steps=300, expected_future_queries=expected_future_queries)
    selected, initial_structure = controller.propose(structure_records, **evaluation, seed=seed)
    for name, raw in controller.candidate_artifacts.items():
        (output / f"structure-initial-{name}.ensemble.json").write_bytes(raw)
    # The ancestor only knows old addresses. All fixed and adaptive successors
    # train on the same current frontier, including the new selection addresses.
    parent_4 = CellEnsemble.fit(
        old_records, partitions([row["key"] for row in old_records], 4, seed), seed=seed, steps=300
    )
    successor, evolved_structure = controller.propose(structure_records, **evaluation, parent=parent_4, seed=seed)
    for name, raw in controller.candidate_artifacts.items():
        (output / f"structure-evolved-{name}.ensemble.json").write_bytes(raw)
    fixed_4 = CellEnsemble.from_bytes(controller.candidate_artifacts["fixed_4"])
    fixed_name = (
        evolved_structure["forecast_cost_comparison"]["baseline"]
        if evolved_structure["forecast_cost_comparison"]
        else "fixed_4"
    )
    strong_fixed = CellEnsemble.from_bytes(controller.candidate_artifacts[fixed_name])
    winner_name = evolved_structure["candidate_objective_winner"]
    winner_test = (
        None
        if winner_name is None
        else _accuracy(CellEnsemble.from_bytes(controller.candidate_artifacts[winner_name]), test)
    )
    structure_tests = {
        "initial": None if selected is None else _accuracy(selected, test),
        "successor": None if successor is None else _accuracy(successor, test),
        "fixed_4": _accuracy(fixed_4, test),
        "strong_fixed": _accuracy(strong_fixed, test),
        "strong_fixed_name": fixed_name,
        "selection_keys": evaluation["selection_keys"],
        "retention_keys": evaluation["retention_keys"],
        "test_keys": [row["key"] for row in test],
    }
    structure_tests["candidate_objective_winner"] = winner_test
    structure_tests["frozen_cost_comparison"] = (
        None if winner_test is None else _test_cost(evolved_structure, winner_test, structure_tests["strong_fixed"])
    )
    parameter_ceiling = next(
        row["cost"]["parameter_bytes"] for row in evolved_structure["candidates"] if row["name"] == "refit"
    )
    equal_controller = EvolutionController(
        steps=300, expected_future_queries=expected_future_queries, parameter_budget_bytes=parameter_ceiling
    )
    equal_successor, equal_structure = equal_controller.propose(
        structure_records, **evaluation, parent=parent_4, seed=seed
    )
    for name, raw in equal_controller.candidate_artifacts.items():
        (output / f"structure-equal-parameter-{name}.ensemble.json").write_bytes(raw)
    structure_tests["equal_parameter_successor"] = None if equal_successor is None else _accuracy(equal_successor, test)
    if equal_structure["forecast_cost_comparison"] is not None:
        comparison = equal_structure["forecast_cost_comparison"]
        candidate_test = _accuracy(
            CellEnsemble.from_bytes(equal_controller.candidate_artifacts[comparison["candidate"]]), test
        )
        baseline_test = _accuracy(
            CellEnsemble.from_bytes(equal_controller.candidate_artifacts[comparison["baseline"]]), test
        )
        structure_tests["equal_parameter_cost_comparison"] = _test_cost(equal_structure, candidate_test, baseline_test)
    for index, raw in enumerate(session.versions):
        (output / f"semantic-generation-{index + 1}.cell.json").write_bytes(raw)
    (output / "semantic-selected.cell.json").write_bytes(session.model.to_bytes())
    (output / "diagnostic-clean-reference.cell.json").write_bytes(clean_reference.to_bytes())
    (output / "procedure.cell.json").write_bytes(procedure.model.to_bytes())
    (output / "transfer.cell.json").write_bytes(transfer.model.to_bytes())
    (output / "ancestor-fixed-4.ensemble.json").write_bytes(parent_4.to_bytes())
    (output / "fixed-4.ensemble.json").write_bytes(fixed_4.to_bytes())
    if successor is not None:
        (output / "selected.ensemble.json").write_bytes(successor.to_bytes())
    source_ledger = {"semantic": session.events, "procedure": procedure.events, "transfer": transfer.events}
    (output / "source-ledger.json").write_bytes(canonical(source_ledger))
    report = {
        "schema": "hepta.memory.v6.learning-study.v1",
        "seed": seed,
        "source_kind": "new synthetic opaque entities and randomized assignments",
        "initial": initial,
        "initial_receipt": initial_receipt,
        "append_guard": append_guard,
        "append_receipt": append_receipt,
        "replay": replay,
        "no_replay": no_replay,
        "counterfactual": counterfactual,
        "correction_receipt": correction_receipt,
        "deletion_guard": deletion_guard,
        "deletion_receipt": deletion_receipt,
        "deleted_read": deleted,
        "surviving": surviving,
        "independent_clean_refit_same_parameters": clean_match,
        "diagnostic_clean_refit_training": clean_reference.training_receipt,
        "procedure": procedure_reads,
        "procedure_receipt": procedure_receipt,
        "composition": {
            "rows": composition_rows,
            "correct": sum(row["actual"] == row["expected"] for row in composition_rows),
        },
        "transfer": transfer_reads,
        "transfer_claim": "written new-domain associations, unchanged code; no new type invention",
        "initial_structure": initial_structure,
        "evolved_structure": evolved_structure,
        "equal_parameter_structure": equal_structure,
        "structure_tests": structure_tests,
        "cost": {
            "semantic": session.cost(),
            "procedure": procedure.cost(),
            "transfer": transfer.cost(),
            "no_replay": recent.cost(),
            "diagnostic_clean_reference": clean_reference.cost(),
            "structure_ancestor": parent_4.cost(),
            "all_model_source_artifact_files_bytes": sum(
                path.stat().st_size for path in output.iterdir() if path.is_file()
            ),
            "exact_source_codec_bytes": len(zlib.compress(canonical(source_ledger), level=9)),
            "full_process_rss_measured": False,
        },
        "ledger": session.ledger,
        "wall_seconds": time.perf_counter() - started_wall,
        "cpu_seconds": time.process_time() - started_cpu,
        "model_outputs_are_source_authority": False,
        "general_memory_claim": False,
    }
    (output / "REPORT.json").write_bytes(canonical(report))
    files = {
        str(path.relative_to(output)): {
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in output.iterdir()
        if path.is_file()
    }
    (output / "MANIFEST.json").write_bytes(canonical({"files": files}))
    return report
