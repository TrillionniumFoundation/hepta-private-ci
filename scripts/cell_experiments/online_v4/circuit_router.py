"""A-only measured graph search and a frozen prompt-conditional ridge router."""

import copy
from dataclasses import asdict, dataclass
import hashlib
import math
from pathlib import Path
import re
import time

import numpy as np

from .circuit_contract import (
    Graph,
    contract_record,
    digest,
    is_sha,
    require,
    validate,
    visible_request,
    write_new,
)
from .circuit_runtime import run_graph


@dataclass(frozen=True)
class RouterPlan:
    execution_binding_digest: str
    feature_dimensions: int = 16
    ridge: float = 1.0
    output_token_penalty: float = 0.0
    model_call_penalty: float = 0.0


def prompt_features(record, dimensions):
    """Only original visible prompt text is read; no IDs, targets or outcomes."""
    prompt = visible_request(record)["task"]["input"]
    require(
        type(dimensions) is int and dimensions in (8, 16, 32, 64),
        "invalid feature width",
    )
    tokens = re.findall(r"[a-z_]+|\d+|[^\s]", prompt.lower())
    values = np.zeros(dimensions + 1, dtype=np.float64)
    for token in tokens:
        hashed = hashlib.sha256(token.encode()).digest()
        values[int.from_bytes(hashed[:4], "big") % dimensions] += (
            1 if hashed[4] & 1 else -1
        )
    norm = float(np.linalg.norm(values[:-1]))
    if norm:
        values[:-1] /= norm
    values[-1] = 1.0
    return values, {"prompt_bytes": len(prompt.encode()), "lexical_hashes": len(tokens)}


def _validate_plan(plan):
    require(
        isinstance(plan, RouterPlan) and is_sha(plan.execution_binding_digest),
        "frozen callback/runtime binding required",
    )
    require(
        type(plan.feature_dimensions) is int
        and plan.feature_dimensions in (8, 16, 32, 64),
        "invalid feature dimensions",
    )
    for key in ("ridge", "output_token_penalty", "model_call_penalty"):
        value = getattr(plan, key)
        require(
            type(value) in (int, float) and math.isfinite(value) and value >= 0,
            "invalid router objective parameter",
        )
    require(plan.ridge > 0, "positive regularization required")


class FrozenRouter:
    """Immutable coefficients predict graph utility before any task execution."""

    def __init__(self, record, expected_digest):
        require(
            is_sha(expected_digest) and digest(record) == expected_digest,
            "frozen router identity differs",
        )
        require(
            record.get("schema") == "hepta.prompt-graph-router.v4",
            "unknown router schema",
        )
        require(
            is_sha(record.get("cell_registry_digest"))
            and is_sha(record.get("budget_digest")),
            "frozen Cell and budget identities required",
        )
        self.record, self.expected_digest = copy.deepcopy(record), expected_digest
        plan = RouterPlan(**record["plan"])
        _validate_plan(plan)
        require(
            isinstance(record["graphs"], list) and 1 <= len(record["graphs"]) <= 32,
            "bounded graph inventory required",
        )
        require(
            len({row["graph_id"] for row in record["graphs"]}) == len(record["graphs"]),
            "duplicate frozen graph IDs",
        )
        weights = np.asarray(record["weights"], dtype=np.float64)
        require(
            weights.shape == (len(record["graphs"]), plan.feature_dimensions + 1)
            and np.isfinite(weights).all(),
            "invalid frozen router parameters",
        )

    def route(self, record):
        require(
            digest(self.record) == self.expected_digest, "router changed after freeze"
        )
        tick, cpu = time.perf_counter(), time.process_time()
        features, feature_cost = prompt_features(
            record, self.record["plan"]["feature_dimensions"]
        )
        scores = np.asarray(self.record["weights"]) @ features
        index = min(
            range(len(scores)),
            key=lambda i: (-float(scores[i]), self.record["graphs"][i]["graph_id"]),
        )
        selected = self.record["graphs"][index]
        graph = Graph(
            selected["graph_id"], tuple(selected["path"]), tuple(selected["edges"])
        )
        return graph, {
            "router_digest": self.expected_digest,
            "graph_id": graph.graph_id,
            "scores": scores.tolist(),
            "features_digest": digest(features.tolist()),
            "reads": "original visible task input only; no final outcome or reference",
            "cost": {
                **feature_cost,
                "wall_seconds": time.perf_counter() - tick,
                "cpu_seconds": time.process_time() - cpu,
                "score_dot_mac": len(scores) * len(features),
                "full_operation_count_known": False,
            },
        }


def fit_router(
    records,
    graphs,
    cells,
    budget,
    generate,
    verify,
    output_dir,
    *,
    plan,
    execution_profile="verified_v4",
):
    """Execute every predeclared A candidate; search cost is retained in full."""
    _validate_plan(plan)
    if execution_profile == "verified_v4":
        runner = run_graph
    elif execution_profile == "local_last_answer_v1":
        from .circuit_bundle import training_graph

        runner = training_graph
    else:
        raise ValueError("unsupported router training execution profile")
    require(
        isinstance(records, list) and 1 <= len(records) <= 4096,
        "bounded A records required",
    )
    require(
        all(
            row.get("split") == "train"
            and row.get("authorization", {}).get("training_allowed") is True
            for row in records
        ),
        "router fitting accepts authorized A only",
    )
    require(
        len({row["task_id"] for row in records}) == len(records), "duplicate A tasks"
    )
    require(
        isinstance(graphs, list) and 1 <= len(graphs) <= 32,
        "bounded declared graph search required",
    )
    require(
        len({graph.graph_id for graph in graphs}) == len(graphs)
        and len({(graph.path, graph.edges) for graph in graphs}) == len(graphs),
        "duplicate graph identity or topology",
    )
    for graph in graphs:
        validate(cells, graph, budget)
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=False)
    frozen = {
        "schema": "hepta.graph-search-plan.v4",
        "plan": asdict(plan),
        "record_digests": [digest(row) for row in records],
        "contracts": [contract_record(cells, graph, budget) for graph in graphs],
        "planned_model_call_opportunities": len(records)
        * len(graphs)
        * budget.model_calls,
        "feature_spec": "signed SHA256 lexical hashes of original prompt; L2 normalize; bias=1",
        "utility": "final business success - output_token_penalty*(tokens/declared token cap) - model_call_penalty*(calls/call cap)",
    }
    if execution_profile == "local_last_answer_v1":
        for contract in frozen["contracts"]:
            contract.update(
                output_selection="last_slot",
                selection_evidence="blind final-slot generation",
                edge_definition={"answer": "first generated answer as one tool turn"},
            )
        frozen["execution_profile"] = execution_profile
    write_new(directory / "PLAN.json", frozen)
    started = time.perf_counter()
    x, feature_costs, observations = [], [], []
    y = np.zeros((len(records), len(graphs)), dtype=np.float64)
    for row_index, record in enumerate(records):
        vector, cost = prompt_features(record, plan.feature_dimensions)
        x.append(vector)
        feature_costs.append(cost)
        for graph_index, graph in enumerate(graphs):
            location = directory / (f"task-{row_index:04d}") / graph.graph_id
            result = runner(record, graph, cells, budget, generate, verify, location)
            require(
                type(result["success"]) is bool,
                "unknown business result cannot label router",
            )
            c = result["cost"]
            y[row_index, graph_index] = (
                int(result["success"])
                - plan.output_token_penalty
                * c["output_tokens"]
                / (budget.model_calls * budget.max_output_tokens_per_call)
                - plan.model_call_penalty * c["model_calls"] / budget.model_calls
            )
            result_path = location / "RESULT.json"
            if execution_profile == "local_last_answer_v1":
                result_path = result_path.relative_to(directory)
            observations.append(
                {
                    "task_id": record["task_id"],
                    "graph_id": graph.graph_id,
                    "result_digest": digest(result),
                    "result_path": str(result_path),
                    "success": result["success"],
                    "utility": float(y[row_index, graph_index]),
                    "cost": c,
                }
            )
    tick, cpu = time.perf_counter(), time.process_time()
    x = np.asarray(x)
    weights = np.linalg.solve(x.T @ x + plan.ridge * np.eye(x.shape[1]), x.T @ y).T
    require(np.isfinite(weights).all(), "nonfinite fitted router")
    record = {
        "schema": "hepta.prompt-graph-router.v4",
        "plan": asdict(plan),
        "graphs": [asdict(graph) for graph in graphs],
        "weights": weights.tolist(),
        "cell_registry_digest": digest(
            {key: asdict(cell) for key, cell in sorted(cells.items())}
        ),
        "budget_digest": digest(asdict(budget)),
        "training_plan_digest": digest(frozen),
        "training_record_digests": frozen["record_digests"],
        "training_task_ids": [row["task_id"] for row in records],
        "feature_spec": frozen["feature_spec"],
        "training_only": "A",
        "frozen": True,
    }
    write_new(directory / "ROUTER.json", record)
    report = {
        "schema": "hepta.graph-search-result.v4",
        "status": "COMPLETE",
        "plan_digest": digest(frozen),
        "router_digest": digest(record),
        "observations": observations,
        "feature_costs": feature_costs,
        "router_parameters": int(weights.size),
        "router_parameter_l2": float(np.linalg.norm(weights)),
        "router_fit_wall_seconds": time.perf_counter() - tick,
        "router_fit_cpu_seconds": time.process_time() - cpu,
        "search_model_calls": sum(row["cost"]["model_calls"] for row in observations),
        "search_verifier_calls": sum(
            row["cost"]["verifier_calls"] for row in observations
        ),
        "search_input_tokens": sum(row["cost"]["input_tokens"] for row in observations),
        "search_output_tokens": sum(
            row["cost"]["output_tokens"] for row in observations
        ),
        "total_wall_seconds": time.perf_counter() - started,
        "full_system_cost_known": False,
        "independent_sample_increment": 0,
        "scientific_qualification": False,
        "scope": "finite graph search plus prompt-conditional ridge; no differentiable Cell-weight or HIA graph training",
    }
    write_new(directory / "SEARCH.json", report)
    return FrozenRouter(record, digest(record)), report
