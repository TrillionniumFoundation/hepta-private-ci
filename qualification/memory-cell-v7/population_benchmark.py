"""Measured development competition, never independent structural acceptance.

Fits every candidate, charges failed searches too, and compares against the best
fixed structure under one frozen budget. NumPy timings are explicitly distinct
from native runtime/transport measurements. Unknown costs force keep-fixed.
"""

import argparse
from collections import OrderedDict
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import time
import uuid

import numpy as np

from population_training import sha, train_populations
from test_training import fixture
from training import AssociativeCell, canonical, current_rows
from v6.values import execute_program


FROZEN_BUDGET = {
    "schema": "hepta.memory.population-development-budget.v2",
    "fixed_shards": list(range(1, 9)), "initial_shards": 2,
    "max_native_bytes": 512_000, "max_resident_payload_bytes": 131_072,
    "forecast_queries": 10_000, "retention_error_limit_permyriad": 100,
    "weights": {"error": 1_000_000_000, "byte": 100, "wall_ns": 1},
    "training": {"seed": 71, "steps": 220, "dimension": 32, "total_hidden": 64, "threshold": 0.9},
    "score_units": "frozen weighted development units; not dollars, FLOPs, or native latency",
}


class DiagnosticReader:
    """Reload actual fitted parameters to measure this NumPy diagnostic only."""

    def __init__(self, artifact, resident_budget):
        self.routes = json.loads(artifact["native"])["routes"]
        self.originals = artifact["originals"]
        self.cache = OrderedDict()
        self.budget = resident_budget
        self.wake_wall_ns = self.read_compute_wall_ns = self.wakes = self.evictions = 0
        self.peak_resident_payload_bytes = 0
        self.resident_bytes = 0

    def read(self, key):
        index = self.routes.get(sha(key.encode()))
        if index is None:
            return None
        if index not in self.cache:
            started = time.perf_counter_ns()
            cell = AssociativeCell.from_bytes(self.originals[index].encode())
            self.wake_wall_ns += time.perf_counter_ns() - started
            size = sum(array.nbytes for array in (cell.A, cell.a, cell.B, cell.b))
            size += sum(len(canonical(item)) for item in (cell.catalog, cell.supports, cell.lineage_sources))
            if size > self.budget:
                raise ValueError("diagnostic resident payload exceeds budget")
            while self.resident_bytes + size > self.budget:
                _, (_, previous) = self.cache.popitem(last=False)
                self.resident_bytes -= previous
                self.evictions += 1
            self.cache[index] = (cell, size)
            self.resident_bytes += size
            self.wakes += 1
            self.peak_resident_payload_bytes = max(self.peak_resident_payload_bytes, self.resident_bytes)
        self.cache.move_to_end(index)
        cell = self.cache[index][0]
        started = time.perf_counter_ns()
        prediction = cell.read(key)
        self.read_compute_wall_ns += time.perf_counter_ns() - started
        return prediction["value"] if prediction["abstain"] is None else None

    def sleep(self):
        self.evictions += len(self.cache)
        self.cache.clear()
        self.resident_bytes = 0


def development_export():
    export = fixture(24)
    for row in export["records"]:
        index = int(row["record"]["entity"].rsplit("-", 1)[1])
        domain = "retained-domain" if index < 8 else "new-domain"
        row["record"]["entity"] = f"{domain}:sensor:{index}"
    export["owner_cut_digest"] = sha(canonical(export))
    return export


def evaluate(result, export, budget):
    rows = current_rows(export)
    typed = {kind: {row["record"]["entity"]: row["record"]["value"] for row in current} for kind, current in rows.items()}
    events = {row["record"]["entity"]: row["record"]["value"] for row in export["records"] if row["record"]["kind"] == "event"}
    readers = {kind: DiagnosticReader(result["artifacts"][kind], budget["max_resident_payload_bytes"] // 2) for kind in rows}
    correct = queries = retention_correct = retention_queries = new_correct = new_queries = 0
    started = time.perf_counter_ns()
    # A second pass follows a real cache drop; no cached answers survive it.
    for _ in range(2):
        for key in sorted(set(typed["semantic"]) & set(typed["procedure"]) & set(events)):
            semantic = readers["semantic"].read(key)
            procedure = readers["procedure"].read(key)
            applied = None if semantic is None or procedure is None else execute_program(procedure, events[key], semantic)
            expected = (typed["semantic"][key], typed["procedure"][key], execute_program(typed["procedure"][key], events[key], typed["semantic"][key]))
            for actual, target in zip((semantic, procedure, applied), expected):
                good = actual == target
                correct += good
                queries += 1
                if key.startswith("retained-domain:"):
                    retention_correct += good
                    retention_queries += 1
                else:
                    new_correct += good
                    new_queries += 1
        for reader in readers.values():
            reader.sleep()
    task_wall_ns = time.perf_counter_ns() - started
    unknown_declined = all(reader.read("never-written-entity") is None for reader in readers.values())
    return {"queries": queries, "correct": correct, "retention_queries": retention_queries, "retention_correct": retention_correct,
        "new_domain_queries": new_queries, "new_domain_correct": new_correct, "unknown_declined": unknown_declined,
        "task_wall_ns": task_wall_ns, "read_compute_wall_ns": sum(reader.read_compute_wall_ns for reader in readers.values()),
        "wake_wall_ns": sum(reader.wake_wall_ns for reader in readers.values()), "wake_count": sum(reader.wakes for reader in readers.values()),
        "eviction_count": sum(reader.evictions for reader in readers.values()),
        "peak_resident_payload_bytes": sum(reader.peak_resident_payload_bytes for reader in readers.values()),
        "independent_future_task_evaluation": False, "routing_specialization_learned": False}


def compete(export, budget, historical_runs=(), progress=None):
    progress = progress or (lambda event: None)
    frozen_digest = sha(canonical(budget))
    count = budget["initial_shards"]
    plans = [("keep-fixed", "keep-fixed", count)] + [(f"fixed-{size}", "fixed", size) for size in budget["fixed_shards"]]
    plans += [("split", "split", count + 1), ("merge", "merge", max(1, count - 1))]
    candidates = []
    # Models are kept until scoring to account for all retained search outputs.
    artifacts = []
    for name, role, shards in plans:
        candidate_start = time.perf_counter_ns()
        config = {**budget["training"], "shard_count": shards}
        progress({"event": "fit_started", "name": name, "role": role, "configuration": config})
        fit_start = time.perf_counter_ns()
        try:
            result = train_populations(export, config)
        except (ValueError, TypeError) as error:
            failed = {"name": name, "role": role, "shards": shards, "fit_failed": type(error).__name__,
                "failed_fit_wall_ns": time.perf_counter_ns() - fit_start, "eligible": False,
                "completed_fit_calls_before_error": None}
            candidates.append(failed)
            progress({"event": "fit_failed", "measurement": failed})
            continue
        fit_wall_ns = time.perf_counter_ns() - fit_start
        progress({"event": "fit_completed", "name": name, "fit_calls": result["receipt"]["fit_calls"],
            "fit_wall_ns": fit_wall_ns, "native_digests": {kind: item["native_digest"] for kind, item in result["receipt"]["types"].items()}})
        eval_start = time.perf_counter_ns()
        measured = evaluate(result, export, budget)
        eval_wall_ns = time.perf_counter_ns() - eval_start
        artifacts.append(result)
        retained = len(canonical(result))
        native = sum(len(item["native"].encode()) for item in result["artifacts"].values())
        types = result["receipt"]["types"]
        footprint = {"native_serialized_bytes": native, "retained_training_result_bytes": retained,
            "raw_native_shard_bytes": sum(item["raw_payload_bytes"] for item in types.values()),
            "original_training_artifact_bytes": sum(len(raw.encode()) for item in result["artifacts"].values() for raw in item["originals"]),
            "parameter_bytes": sum(item["resident_parameters_bytes"] for item in types.values()),
            "catalog_bytes": sum(item["catalog_bytes"] for item in types.values()),
            "route_bytes": sum(item["route_bytes"] for item in types.values()),
            "lineage_bytes": sum(item["lineage_bytes"] for item in types.values()),
            "shard_support_bytes": sum(shard["support_bytes"] for item in types.values() for shard in item["shards"]),
            "source_export_bytes": len(canonical(export)), "source_ledger_bytes": None,
            "actual_rss_bytes": None, "native_read_wall_ns": None, "native_wake_wall_ns": None,
            "communication_bytes": None, "communication_wall_ns": None,
            "breakdowns_overlap_serialized_artifacts": True}
        overhead = time.perf_counter_ns() - candidate_start - fit_wall_ns - eval_wall_ns
        retention_ok = measured["retention_queries"] > 0 and (measured["retention_queries"] - measured["retention_correct"]) * 10_000 <= measured["retention_queries"] * budget["retention_error_limit_permyriad"]
        candidates.append({"name": name, "role": role, "shards": shards, "fit_failed": None, "configuration": config,
            "fit_wall_ns": fit_wall_ns, "training_cpu_ns": result["receipt"]["cpu_ns"], "replay_wall_ns": 0,
            "search_overhead_wall_ns": overhead, "evaluation_wall_ns": eval_wall_ns, "fit_calls": result["receipt"]["fit_calls"],
            "parameters_rebuilt_clean": True, "footprint": footprint, "evaluation": measured,
            "eligible": native <= budget["max_native_bytes"] and measured["peak_resident_payload_bytes"] <= budget["max_resident_payload_bytes"] and retention_ok})
        progress({"event": "candidate_measured", "measurement": candidates[-1]})
    weights = budget["weights"]
    total_search = sum(item.get("fit_wall_ns", item.get("failed_fit_wall_ns", 0)) + item.get("search_overhead_wall_ns", 0) + item.get("evaluation_wall_ns", 0) for item in candidates)
    total_retained = sum(item.get("footprint", {}).get("retained_training_result_bytes", 0) for item in candidates)
    historical_wall = sum(item["all_candidates_search_wall_ns"] for item in historical_runs)
    known_historical_bytes = sum(item["all_candidates_retained_training_bytes"] for item in historical_runs if item["all_candidates_retained_training_bytes"] is not None)
    for item in candidates:
        if item["fit_failed"] is not None:
            continue
        evaluation = item["evaluation"]
        recurring = ((evaluation["queries"] - evaluation["correct"]) * weights["error"] + evaluation["task_wall_ns"] * weights["wall_ns"]) * budget["forecast_queries"] / evaluation["queries"]
        own = item["fit_wall_ns"] + item["search_overhead_wall_ns"] + item["evaluation_wall_ns"]
        item["partial_measured_score"] = recurring + own * weights["wall_ns"] + item["footprint"]["retained_training_result_bytes"] * weights["byte"]
        item["partial_full_search_score"] = recurring + (total_search + historical_wall) * weights["wall_ns"] + (total_retained + known_historical_bytes) * weights["byte"]
    fixed = sorted((item for item in candidates if item["eligible"] and item["role"] in {"fixed", "keep-fixed"}), key=lambda item: (item["partial_measured_score"], item["name"]))
    structural = sorted((item for item in candidates if item["eligible"] and item["role"] in {"split", "merge"}), key=lambda item: (item["partial_full_search_score"], item["name"]))
    return {"schema": "hepta.memory.population-development-competition.v2", "budget": deepcopy(budget), "budget_digest": frozen_digest,
        "source_cut_digest": export["owner_cut_digest"], "source_export_digest": sha(canonical(export)), "candidates": candidates,
        "all_candidates_search_wall_ns": total_search, "all_candidates_retained_training_bytes": total_retained,
        "historical_runs": list(historical_runs), "historical_search_wall_ns_charged": historical_wall,
        "known_historical_materialized_bytes_charged": known_historical_bytes,
        "total_accounted_search_wall_ns": total_search + historical_wall,
        "failed_fits_charged": sum(item["fit_failed"] is not None for item in candidates),
        "strongest_fixed": fixed[0]["name"] if fixed else None, "best_structural_by_partial_score": structural[0]["name"] if structural else None,
        "partial_measured_net_gain": fixed[0]["partial_measured_score"] - structural[0]["partial_full_search_score"] if fixed and structural else None,
        "selected_action": "keep-fixed", "full_cost_gate": "not_passed",
        "unmeasured_required_dimensions": ["independent_future_tasks", "owner_source_ledger_bytes", "native_inference_and_wake", "exclusive_transport_bytes_and_wall_ns", "process_rss"],
        "partial_scores_are_acceptance_evidence": False, "runtime_backend": "NumPy development diagnostic",
        "learned_domain_specialization_established": False, "authority": False}


def write_new_json(path, value):
    with path.open("x") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prior-report", type=Path, action="append", default=[])
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("development evidence is append-only; choose a new output path")
    historical = []
    referenced_history = set()
    for path in args.prior_report:
        raw = path.read_bytes()
        prior = json.loads(raw)
        referenced_history.update(item["report_sha256"] for item in prior.get("historical_runs", []))
        historical.append({"report_sha256": sha(raw), "report_name": path.name,
            "all_candidates_search_wall_ns": prior["all_candidates_search_wall_ns"],
            "all_candidates_retained_training_bytes": prior["all_candidates_retained_training_bytes"],
            "fit_calls": sum(item["fit_calls"] for item in prior["candidates"] if item.get("fit_failed") is None) if "candidates" in prior else None,
            "partial_measured_net_gain": prior["partial_measured_net_gain"],
            "current_run_only": True,
            "incomplete_measurements": prior.get("incomplete_measurements", [])})
    if len({item["report_sha256"] for item in historical}) != len(historical):
        raise ValueError("duplicate historical receipt would double-charge a run")
    if referenced_history - {item["report_sha256"] for item in historical}:
        raise ValueError("supply every referenced historical receipt; totals cannot omit prior runs")
    root = Path(__file__).resolve().parent
    imports = [root / name for name in ("population_benchmark.py", "population_training.py", "training.py", "native_export.py", "test_training.py")]
    imports += [root.parent / "memory-cell-v6/v6" / name for name in ("cells.py", "contracts.py", "values.py", "__init__.py")]
    code = {str(path.relative_to(root.parent)): sha(path.read_bytes()) for path in imports}
    runtime = {"python": sys.version, "numpy": np.__version__}
    export = development_export()
    identity = {"schema": "hepta.memory.population-development-run.v1", "run_id": str(uuid.uuid4()),
        "created_at_unix_ns": time.time_ns(), "budget": FROZEN_BUDGET, "budget_digest": sha(canonical(FROZEN_BUDGET)),
        "source_export_sha256": sha(canonical(export)), "source_cut_digest": export["owner_cut_digest"],
        "code_sha256": code, "runtime": runtime, "historical_runs": historical}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_new_json(args.output.with_suffix(".run.json"), identity)
    started = time.perf_counter_ns()
    with args.output.with_suffix(".progress.jsonl").open("x") as journal:
        def progress(event):
            journal.write(json.dumps({"run_id": identity["run_id"], "elapsed_wall_ns": time.perf_counter_ns() - started, **event}, sort_keys=True) + "\n")
            journal.flush()
            os.fsync(journal.fileno())
        try:
            progress({"event": "run_started", "identity_sha256": sha(canonical(identity))})
            report = compete(export, FROZEN_BUDGET, historical, progress)
            if code != {str(path.relative_to(root.parent)): sha(path.read_bytes()) for path in imports}:
                raise ValueError("training or measurement code changed during this run")
            report.update({"run_id": identity["run_id"], "code_sha256": code, "runtime": runtime,
                "pre_fit_identity_sha256": sha(canonical(identity)), "run_wall_ns": time.perf_counter_ns() - started})
            write_new_json(args.output, report)
            progress({"event": "run_completed", "report_sha256": sha(args.output.read_bytes())})
        except Exception as error:
            failed = {"schema": "hepta.memory.population-development-failed-run.v1", "run_id": identity["run_id"],
                "failure_type": type(error).__name__, "all_candidates_search_wall_ns": time.perf_counter_ns() - started,
                "all_candidates_retained_training_bytes": None, "partial_measured_net_gain": None,
                "incomplete_measurements": ["Run failed; consult the append-only progress journal for completed and failed candidates."]}
            progress({"event": "run_failed", **failed})
            write_new_json(args.output.with_suffix(".failed.json"), failed)
            raise
    print(json.dumps({key: report[key] for key in ("strongest_fixed", "best_structural_by_partial_score", "partial_measured_net_gain", "selected_action", "full_cost_gate", "all_candidates_search_wall_ns")}))


if __name__ == "__main__":
    main()
