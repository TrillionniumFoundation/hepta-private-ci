"""Four fresh-execution graph arms and frozen-policy edge/Cell interventions."""

from dataclasses import asdict
from pathlib import Path
import random

from .circuit_contract import (
    OUTPUT_SELECTION,
    Graph,
    digest,
    require,
    validate,
    write_new,
)
from .circuit_runtime import run_graph


def _retained(result, directory):
    return {
        "record_id": result["record_id"],
        "task_id": result["task_id"],
        "graph_id": result["graph_id"],
        "success": result["success"],
        "output_selection": result["output_selection"],
        "final_slot": result["final_slot"],
        "last_executed_slot": result["last_executed_slot"],
        "first_success": result["first_success"],
        "cost": result["cost"],
        "intervention": result["intervention"],
        "result_digest": digest(result),
        "result_path": str(directory / "RESULT.json"),
    }


def _paired(main, removed):
    return {
        "task_id": main["task_id"],
        "main_result_digest": main["result_digest"],
        "intervention_result_digest": removed["result_digest"],
        "success_delta_main_minus_removed": int(main["success"])
        - int(removed["success"])
        if type(main["success"]) is bool and type(removed["success"]) is bool
        else None,
        "saved_model_calls": main["cost"]["model_calls"]
        - removed["cost"]["model_calls"],
        "input_token_difference_main_minus_removed": main["cost"]["input_tokens"]
        - removed["cost"]["input_tokens"],
        "output_token_difference_main_minus_removed": main["cost"]["output_tokens"]
        - removed["cost"]["output_tokens"],
        "intervention_effective": removed["intervention"]["effective_on_graph"],
    }


def evaluate_suite(
    records,
    cells,
    budget,
    generate,
    verify,
    output_dir,
    *,
    router,
    single_cell,
    fixed_graph,
    random_seed,
    execution_binding_digest,
):
    """Execute controls and all learned-graph interventions; never select on B/C.

    The frozen router selects once per task. Interventions retain that route;
    they neither retrain the router nor choose a replacement from the outcome.
    Each fresh call/verification is paid, including no-op interventions on an
    edge or Cell absent from a task's selected graph.
    """
    require(
        isinstance(records, list) and 1 <= len(records) <= 4096,
        "bounded panel required",
    )
    require(
        len({row["task_id"] for row in records}) == len(records),
        "duplicate panel tasks",
    )
    require(single_cell in cells, "single-model control missing")
    require(
        type(random_seed) is int and 0 <= random_seed < 2**32, "bounded seed required"
    )
    require(
        router.record["plan"]["execution_binding_digest"] == execution_binding_digest,
        "execution binding differs from router search",
    )
    require(router.expected_digest == digest(router.record), "frozen router changed")
    require(
        router.record["cell_registry_digest"]
        == digest({key: asdict(cell) for key, cell in sorted(cells.items())})
        and router.record["budget_digest"] == digest(asdict(budget)),
        "Cell registry or budget differs from frozen router",
    )
    single = Graph("single", (single_cell, single_cell))
    candidate = random.Random(random_seed).choice(router.record["graphs"])
    random_graph = Graph(
        "random_sparse", tuple(candidate["path"]), tuple(candidate["edges"])
    )
    for graph in (single, fixed_graph, random_graph):
        validate(cells, graph, budget)
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=False)
    plan = {
        "schema": "hepta.graph-evaluation-plan.v4",
        "router_digest": router.expected_digest,
        "record_digests": [digest(row) for row in records],
        "controls": {
            "single": asdict(single),
            "fixed": asdict(fixed_graph),
            "random_sparse": asdict(random_graph),
        },
        "random_seed": random_seed,
        "budget": asdict(budget),
        "execution_binding_digest": execution_binding_digest,
        "cell_interventions": sorted(cells),
        "edge_interventions": ["answer", "feedback"],
        "route_under_intervention": "same pre-action frozen route; no retraining or substitution",
        "matching": "same call/token caps; all actual costs retained, not asserted equal",
        "output_selection": OUTPUT_SELECTION,
        "selection_on_this_panel": False,
    }
    write_new(directory / "PLAN.json", plan)
    arms = {key: [] for key in ("single", "fixed", "random_sparse", "learned_sparse")}
    interventions = {"edge-" + edge: [] for edge in ("answer", "feedback")}
    interventions.update({"cell-" + cell: [] for cell in sorted(cells)})
    paired, routes, all_rows = {key: [] for key in interventions}, [], []
    for index, record in enumerate(records):
        learned, routing = router.route(record)
        validate(cells, learned, budget)
        task_dir = directory / f"task-{index:04d}"
        task_dir.mkdir(exist_ok=False)
        write_new(task_dir / "ROUTE.json", routing)
        routes.append(routing)
        selected = {
            "single": single,
            "fixed": fixed_graph,
            "random_sparse": random_graph,
            "learned_sparse": learned,
        }
        for arm, graph in selected.items():
            path = task_dir / arm
            result = run_graph(record, graph, cells, budget, generate, verify, path)
            observed = _retained(result, path)
            arms[arm].append(observed)
            all_rows.append(observed)
        for name in interventions:
            kind, value = name.split("-", 1)
            path = task_dir / name
            kwargs = {"drop_edge" if kind == "edge" else "drop_cell": value}
            result = run_graph(
                record, learned, cells, budget, generate, verify, path, **kwargs
            )
            observed = _retained(result, path)
            interventions[name].append(observed)
            paired[name].append(_paired(arms["learned_sparse"][-1], observed))
            all_rows.append(observed)
    counts = {cell.active_parameters for cell in cells.values()}
    report = {
        "schema": "hepta.online-circuit-study.v4",
        "status": "COMPLETE",
        "plan_digest": digest(plan),
        "router_digest": router.expected_digest,
        "arms": arms,
        "interventions": interventions,
        "paired": paired,
        "routes": routes,
        "summary": {
            key: {
                "tasks": len(rows),
                "successes": sum(row["success"] is True for row in rows),
                "unknown": sum(row["success"] is None for row in rows),
                "model_calls": sum(row["cost"]["model_calls"] for row in rows),
                "input_tokens": sum(row["cost"]["input_tokens"] for row in rows),
                "output_tokens": sum(row["cost"]["output_tokens"] for row in rows),
            }
            for key, rows in arms.items()
        },
        "all_actual_execution_cost": {
            key: sum(row["cost"][key] for row in all_rows)
            for key in (
                "model_calls",
                "verifier_calls",
                "business_executions",
                "format_rejections",
                "input_tokens",
                "output_tokens",
            )
        },
        "declared_active_parameter_counts_equal": None
        if None in counts
        else len(counts) == 1,
        "matched_actual_cost_claim": False,
        "full_system_cost_known": False,
        "search_cost_included_in_above_totals": False,
        "search_cost_location": "separate bound SEARCH.json; do not discard or relabel free",
        "independent_sample_increment": 0,
        "scientific_qualification": False,
        "native_cell_or_HIA_execution": False,
        "new_C_or_adoption_claim": False,
    }
    write_new(directory / "STUDY.json", report)
    return report
