"""Actual E2 workers, exposed-panel use and shared-base Circuit execution."""

from dataclasses import asdict
import hashlib
import os
from pathlib import Path
import time

from .. import data, repo_execution
from ..coding_sft import write_new
from . import onpolicy_loop, onpolicy_train
from .circuit_contract import Budget, CellSpec, Graph
from .circuit_router import RouterPlan, fit_router
from .circuit_study import evaluate_suite
from .onpolicy_contract import SCOPE, require
from .onpolicy_rollout import attempts
from .round03_plan import CELL_MODES, MODES, panels
from .shared_pool_v4 import SharedAdapterPool


def run_e2(context, manifests, backend, freeze, run_directory, mode):
    require(mode in MODES, "unknown E2 mode")
    return onpolicy_loop.run(
        context,
        manifests["final_answer"],
        Path(run_directory) / "e2" / mode,
        freeze["E2"]["freezes"][mode],
        backend,
    )


def _answer_signature(result):
    return [
        {
            "task_id": row["task_id"],
            "record_id": row["record_id"],
            "success": row["success"],
            "first_attempt_success": row["first_attempt_success"],
            "steps": [
                {
                    "request_sha256": step["request_sha256"],
                    "answer_sha256": hashlib.sha256(
                        step["output"]["answer"].encode()
                    ).hexdigest(),
                    "output_tokens": step["output"]["output_tokens"],
                    "input_tokens": step["output"]["input_tokens"],
                    "success": step["verification"]["success"],
                }
                for step in row["steps"]
            ],
        }
        for row in result["rows"]
    ]


def compare_cold(primary, cold):
    require(
        primary["phase"] == "primary"
        and cold["phase"] == "cold"
        and primary["pid"] != cold["pid"],
        "cold use requires a separate observed process",
    )
    for key in (
        "model_digest",
        "comparison_digest",
        "panel_digests",
        "source_inventory",
    ):
        require(primary[key] == cold[key], "cold recovery binding differs: " + key)
    return {
        "same_answer_and_request_observations": _answer_signature(primary)
        == _answer_signature(cold),
        "same_candidate": True,
        "separate_process": True,
        "optimizer_resume": False,
        "scope": "repeated exposed-panel inference reload; not new C or training-state recovery",
        "primary_digest": data.digest(primary),
        "cold_digest": data.digest(cold),
        **SCOPE,
    }


def evaluate_e2(context, root, backend, freeze, run_directory, mode, phase):
    require(mode in MODES and phase in ("primary", "cold"), "unknown evaluation worker")
    run_directory = Path(run_directory)
    study = data._parse((run_directory / "e2" / mode / "RESULT.json").read_bytes())
    require(
        study["status"] == "COMPLETE"
        and study["freeze_digest"] == data.digest(freeze["E2"]["freezes"][mode]),
        "E2 candidate is not from this frozen arm",
    )
    candidate = study["final_manifest"]
    require(
        backend.verify_model(candidate) == study["final_model_digest"],
        "final candidate differs",
    )
    directory = run_directory / "evaluations" / mode / phase
    directory.mkdir(parents=True, exist_ok=False)
    primary = None
    if phase == "cold":
        primary = data._parse(
            (directory.parent / "primary/EVALUATION.json").read_bytes()
        )
        require(primary["pid"] != os.getpid(), "cold use must start in a new process")
    repo_execution.load_catalog("open")
    started, rows = time.perf_counter(), []
    write_new(
        directory / "INTENT.json",
        {
            "pid": os.getpid(),
            "phase": phase,
            "model_digest": study["final_model_digest"],
            "comparison_digest": freeze["comparison_digest"],
            "maximum_attempts": 2,
            "automatic_retry": False,
            **SCOPE,
        },
    )
    predictor = onpolicy_train.load_predictor(candidate, root)
    try:
        for panel, records in panels(context).items():
            for index, record in enumerate(records):
                row = attempts(
                    predictor,
                    record,
                    directory / panel / str(index),
                    maximum=2,
                    execute=True,
                )
                rows.append({**row, "panel": panel})
    finally:
        predictor.close()
    steps = [step for row in rows for step in row["steps"]]
    result = {
        "schema": "hepta.round03-exposed-evaluation.v1",
        "status": "COMPLETE",
        "phase": phase,
        "mode": mode,
        "pid": os.getpid(),
        "rows": rows,
        "model_digest": study["final_model_digest"],
        "comparison_digest": freeze["comparison_digest"],
        "panel_digests": freeze["panel_digests"],
        "source_inventory": backend.sources(),
        "by_panel": {
            key: {
                "tasks": len(records),
                "successes": sum(row["success"] for row in rows if row["panel"] == key),
            }
            for key, records in panels(context).items()
        },
        "model_calls": len(steps),
        "verifier_calls": len(steps),
        "input_tokens": sum(step["output"]["input_tokens"] for step in steps),
        "output_tokens": sum(step["output"]["output_tokens"] for step in steps),
        "wall_seconds": time.perf_counter() - started,
        "full_system_cost_complete": False,
        "repeated_exposed_tasks": True,
        "optimizer_resume": False,
        **SCOPE,
    }
    write_new(directory / "EVALUATION.json", result)
    if primary is not None:
        write_new(directory / "COLD_COMPARISON.json", compare_cold(primary, result))
    return result


def run_circuit(context, manifests, root, freeze, run_directory):
    directory = Path(run_directory) / "circuit"
    directory.mkdir(parents=True, exist_ok=False)
    plan, binding = freeze["E4"], freeze["comparison_digest"]
    repo_execution.load_catalog("open")
    pool = SharedAdapterPool(
        {cell: manifests[mode] for cell, mode in CELL_MODES.items()}, root
    )
    try:
        write_new(directory / "POOL.json", pool.snapshot())
        cells = {}
        for cell, mode in CELL_MODES.items():
            manifest, evidence = manifests[mode], pool.parameter_evidence(cell)
            base = manifest["base_manifest"]
            cells[cell] = CellSpec(
                cell,
                data.digest(manifest),
                data.digest(base),
                data.digest(base["files"]),
                data.digest(base["runtime"]),
                evidence["active_parameters"],
                evidence["parameter_evidence_digest"],
            )
        require(
            len({cell.active_parameters for cell in cells.values()}) == 1,
            "actual selected-adapter parameter counts differ",
        )
        write_new(
            directory / "CELLS.json",
            {cell: asdict(spec) for cell, spec in cells.items()},
        )
        graph = lambda value: Graph(
            value["graph_id"], tuple(value["path"]), tuple(value["edges"])
        )
        budget = Budget(**plan["budget"])
        router, search = fit_router(
            panels(context)["old_A"],
            [graph(v) for v in plan["graphs"]],
            cells,
            budget,
            pool.generate,
            data.verify_answer,
            directory / "search",
            plan=RouterPlan(binding, **plan["router"]),
        )
        summaries = {}
        for panel, records in panels(context).items():
            summaries[panel] = evaluate_suite(
                records,
                cells,
                budget,
                pool.generate,
                data.verify_answer,
                directory / panel,
                router=router,
                single_cell=plan["single_cell"],
                fixed_graph=graph(plan["fixed_graph"]),
                random_seed=plan["random_seed"],
                execution_binding_digest=binding,
            )
        result = {
            "schema": "hepta.round03-circuit-job.v1",
            "status": "COMPLETE",
            "comparison_digest": binding,
            "search_digest": data.digest(search),
            "panel_study_digests": {
                key: data.digest(value) for key, value in summaries.items()
            },
            "source_inventory": freeze["source_inventory"],
            "pool_digest": data.digest(pool.snapshot()),
            "cost_locations": [
                "POOL.json",
                "search/SEARCH.json",
                "old_A/STUDY.json",
                "old_B/STUDY.json",
            ],
            "actual_cost_matching_claim": False,
            **SCOPE,
        }
        write_new(directory / "RESULT.json", result)
        return result
    finally:
        pool.close()
