"""Predeclared equal-call controls supplement the original six-graph Circuit."""

from dataclasses import asdict
from pathlib import Path
import random

from .circuit_contract import Graph, digest, is_sha, require, validate, write_new
from .circuit_runtime import run_graph


def behavior(result):
    """Keep last-step harm visible under verifier-assisted output retention."""
    nodes = [node for node in result["nodes"] if node["status"] == "COMPLETE"]
    first = nodes[0]["business"]["business_success"] if nodes else None
    last = nodes[-1]["business"]["business_success"] if nodes else None
    paired = len(nodes) == 2 and type(first) is bool and type(last) is bool
    return {
        "selected_success": result["success"],
        "first_success": first,
        "last_success": last,
        "two_executed_steps": len(nodes) == 2,
        "recovery_0_to_1": first is False and last is True if paired else None,
        "regression_1_to_0": first is True and last is False if paired else None,
    }


def select_static(search, graphs, training_task_ids, router_digest):
    """Choose by the complete authorized A search; ties use graph ID."""
    require(
        search["status"] == "COMPLETE" and search["router_digest"] == router_digest,
        "completed bound A search required",
    )
    require(
        len(set(training_task_ids)) == len(training_task_ids), "duplicate training task"
    )
    by_id = {graph.graph_id: graph for graph in graphs}
    require(len(by_id) == len(graphs), "duplicate static candidate")
    pairs = [(row["task_id"], row["graph_id"]) for row in search["observations"]]
    require(
        len(set(pairs)) == len(pairs)
        and set(pairs)
        == {(task, graph) for task in training_task_ids for graph in by_id},
        "static selection requires exactly the predeclared A task/graph pairs",
    )
    totals = {
        graph: sum(
            row["utility"] for row in search["observations"] if row["graph_id"] == graph
        )
        for graph in by_id
    }
    selected = min(totals, key=lambda graph: (-totals[graph], graph))
    record = {
        "schema": "hepta.a-only-static-graph-selection.v1",
        "search_digest": digest(search),
        "router_digest": router_digest,
        "training_task_ids": list(training_task_ids),
        "A_utility_sums": totals,
        "selection_rule": "maximum A utility sum, then lexicographically smallest graph ID",
        "selected_graph": asdict(by_id[selected]),
        "selection_uses_B": False,
    }
    return by_id[selected], record


def task_random_graph(graphs, seed, task_id):
    require(type(seed) is int and 0 <= seed < 2**32, "bounded random seed required")
    material = {"seed": seed, "task_id": task_id}
    selected = random.Random(digest(material)).choice(graphs)
    return selected, {
        "seed_material_digest": digest(material),
        "graph_id": selected.graph_id,
    }


def evaluate_controls(
    records,
    cells,
    budget,
    generate,
    verify,
    output_dir,
    *,
    router,
    static_graph,
    original_routes,
    random_seed,
    comparison_digest,
    protocol_digest,
):
    """Execute all controls; preserve learned routes for same-call replacement."""
    require(set(cells) == {"F", "T", "C"}, "the original F/T/C registry is required")
    require(
        budget.model_calls == 2
        and is_sha(comparison_digest)
        and is_sha(protocol_digest),
        "frozen two-call protocol required",
    )
    require(
        isinstance(records, list) and 1 <= len(records) <= 4096,
        "bounded panel required",
    )
    require(
        len({row["task_id"] for row in records}) == len(records),
        "duplicate panel tasks",
    )
    require(
        len(original_routes) == len(records), "original routes must cover the panel"
    )
    require(router.expected_digest == digest(router.record), "router changed")
    require(
        router.record["plan"]["execution_binding_digest"] == comparison_digest
        and router.record["cell_registry_digest"]
        == digest({key: asdict(value) for key, value in sorted(cells.items())})
        and router.record["budget_digest"] == digest(asdict(budget)),
        "additional controls differ from the frozen router execution binding",
    )
    candidates = [
        Graph(row["graph_id"], tuple(row["path"]), tuple(row["edges"]))
        for row in router.record["graphs"]
    ]
    by_id = {graph.graph_id: graph for graph in candidates}
    require(
        static_graph in candidates, "static graph is outside the shared candidate set"
    )
    selections = []
    for record, route in zip(records, original_routes):
        require(
            route["router_digest"] == router.expected_digest, "original route differs"
        )
        validated_graph, validated_route = router.route(record)
        require(
            route["graph_id"] == validated_graph.graph_id
            and route["features_digest"] == validated_route["features_digest"],
            "original route is not bound to this task's visible input",
        )
        learned = by_id[route["graph_id"]]
        chosen, draw = task_random_graph(candidates, random_seed, record["task_id"])
        graphs = {
            "single_T": Graph("single_T", ("T", "T")),
            "single_C": Graph("single_C", ("C", "C")),
            "task_random": Graph("task_random", chosen.path, chosen.edges),
            "best_static": Graph("best_static", static_graph.path, static_graph.edges),
            "replace_non_F": Graph(
                "replace_non_F", tuple("F" for _ in learned.path), learned.edges
            ),
        }
        for graph in graphs.values():
            validate(cells, graph, budget)
        selections.append(
            {
                "task_id": record["task_id"],
                "random_draw": draw,
                "original_route_digest": digest(route),
                "learned_graph_id": learned.graph_id,
                "route_validation_cost": validated_route["cost"],
                "identity_replacement_noop": all(cell == "F" for cell in learned.path),
                "graphs": {key: asdict(value) for key, value in graphs.items()},
            }
        )
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=False)
    plan = {
        "schema": "hepta.additional-circuit-control-plan.v1",
        "comparison_digest": comparison_digest,
        "protocol_digest": protocol_digest,
        "record_digests": [digest(row) for row in records],
        "cell_registry_digest": digest(
            {key: asdict(value) for key, value in sorted(cells.items())}
        ),
        "budget": asdict(budget),
        "selections": selections,
        "all_single_controls_to_report": ["F", "T", "C"],
        "F_result": "same-run original single F/F arm; no duplicate inference",
        "single_selection": "report every predeclared single; no A or B winner selection",
        "router_search": "unchanged original six graphs; TT/CC are controls only",
        "replacement": "replace each non-F slot by F; preserve edges and two calls; report no-ops",
    }
    write_new(directory / "PLAN.json", plan)
    arms = {key: [] for key in selections[0]["graphs"]}
    for index, (record, selected) in enumerate(zip(records, selections)):
        for arm, value in selected["graphs"].items():
            graph = Graph(
                value["graph_id"], tuple(value["path"]), tuple(value["edges"])
            )
            path = directory / f"task-{index:04d}" / arm
            result = run_graph(record, graph, cells, budget, generate, verify, path)
            arms[arm].append(
                {
                    "record_id": result["record_id"],
                    "task_id": result["task_id"],
                    "result_path": str(path / "RESULT.json"),
                    "result_digest": digest(result),
                    "behavior": behavior(result),
                    "cost": result["cost"],
                    "identity_replacement_noop": selected["identity_replacement_noop"]
                    if arm == "replace_non_F"
                    else None,
                }
            )
    keys = (
        "model_calls",
        "verifier_calls",
        "business_executions",
        "format_rejections",
        "input_tokens",
        "output_tokens",
    )
    result = {
        "schema": "hepta.additional-circuit-control-study.v1",
        "status": "COMPLETE",
        "plan_digest": digest(plan),
        "arms": arms,
        "all_actual_execution_cost": {
            key: sum(row["cost"][key] for rows in arms.values() for row in rows)
            for key in keys
        },
        "actual_cost_matching_claim": False,
        "full_system_cost_known": False,
        "independent_sample_increment": 0,
        "scientific_qualification": False,
    }
    write_new(directory / "STUDY.json", result)
    return result


def run_extended_circuit(
    context,
    manifests,
    root,
    comparison,
    output_dir,
    protocol_digest,
    *,
    pool_type=None,
    expected_pool_source_sha256=None,
):
    """Run original search and suite with an explicitly frozen pool implementation."""
    from .. import data, repo_execution
    from .circuit_contract import Budget, CellSpec
    from .circuit_router import RouterPlan, fit_router
    from .circuit_study import evaluate_suite
    from .round03_plan import CELL_MODES, panels
    from .shared_pool_v4 import SharedAdapterPool

    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=False)
    repo_execution.load_catalog("open")
    plan, binding = comparison["E4"], comparison["comparison_digest"]
    if pool_type is None:
        pool_type = SharedAdapterPool
    pool = pool_type({cell: manifests[mode] for cell, mode in CELL_MODES.items()}, root)
    try:
        snapshot = pool.snapshot()
        write_new(directory / "POOL.json", snapshot)
        write_new(
            directory / "POOL_BINDING.json",
            {
                "class_module": type(pool).__module__,
                "class_name": type(pool).__name__,
                "source_sha256": snapshot["inventory"]["source_sha256"],
                "protocol_digest": protocol_digest,
            },
        )
        require(type(pool) is pool_type, "constructed pool type differs")
        if expected_pool_source_sha256 is not None:
            require(
                snapshot["inventory"]["source_sha256"] == expected_pool_source_sha256,
                "frozen pool source differs",
            )
        cells = {}
        for cell, mode in CELL_MODES.items():
            manifest, evidence = manifests[mode], pool.parameter_evidence(cell)
            base = manifest["base_manifest"]
            require(
                data.digest(manifest) == plan["cells"][cell]["manifest_digest"],
                "Run02 Cell identity differs from original comparison",
            )
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
        candidates = [graph(value) for value in plan["graphs"]]
        panel_records = panels(context)
        router, search = fit_router(
            panel_records["old_A"],
            candidates,
            cells,
            budget,
            pool.generate,
            data.verify_answer,
            directory / "search",
            plan=RouterPlan(binding, **plan["router"]),
        )
        static, selection = select_static(
            search,
            candidates,
            [row["task_id"] for row in panel_records["old_A"]],
            router.expected_digest,
        )
        write_new(directory / "STATIC_SELECTION.json", selection)
        summaries = {}
        for panel, records in panel_records.items():
            original = evaluate_suite(
                records,
                cells,
                budget,
                pool.generate,
                data.verify_answer,
                directory / "original" / panel,
                router=router,
                single_cell=plan["single_cell"],
                fixed_graph=graph(plan["fixed_graph"]),
                random_seed=plan["random_seed"],
                execution_binding_digest=binding,
            )
            additional = evaluate_controls(
                records,
                cells,
                budget,
                pool.generate,
                data.verify_answer,
                directory / "additional" / panel,
                router=router,
                static_graph=static,
                original_routes=original["routes"],
                random_seed=plan["random_seed"],
                comparison_digest=binding,
                protocol_digest=protocol_digest,
            )
            summaries[panel] = {
                "original": digest(original),
                "additional": digest(additional),
            }
        result = {
            "schema": "hepta.extended-circuit-control-job.v1",
            "status": "COMPLETE",
            "protocol_digest": protocol_digest,
            "comparison_digest": binding,
            "search_digest": digest(search),
            "static_selection_digest": digest(selection),
            "panel_study_digests": summaries,
            "pool_digest": data.digest(pool.snapshot()),
            "all_inference_uses_one_shared_pool": True,
            "actual_cost_matching_claim": False,
            "full_system_cost_known": False,
            "independent_sample_increment": 0,
            "scientific_qualification": False,
        }
        write_new(directory / "RESULT.json", result)
        return result
    finally:
        pool.close()
