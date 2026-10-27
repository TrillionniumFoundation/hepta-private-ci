"""Structured task transfer with typed DAGs and feedback-trained allocation.

This is a bounded arithmetic task grammar, not natural-language intent discovery.
All source associations are written before use. The router transfers to new
combinations and newly written domains; it does not invent memory types/opcodes.
"""

import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from .cells import AssociativeCell, canonical, key_digest
from .store import EventStore, StaleSource
from .values import OPCODES, execute_program, validate_typed_value


SIGNATURES = {
    "apply": (("procedure", "int", "semantic"), "int"),
    "difference": (("int", "int"), "int"),
    "sum": (("int", "int"), "int"),
}
FEATURES = (
    "intercept",
    "historical_event",
    "old_program",
    "new_program",
    "cross_entity",
    "event_reads",
    "semantic_reads",
    "procedure_reads",
    "applies",
    "differences",
    "sums",
)
EXPERTS = {
    "general": (48, (1, 2), (1, 2)),
    "current": (16, (2,), (1, 2)),
    "archive": (24, (1, 2), (1,)),
    "revision": (24, (1, 2), (2,)),
}


class TypedTaskCompiler:
    """Infer dependencies and types from expressions; emit a deduplicated DAG."""

    def compile(self, expression, *, maximum_nodes=24):
        nodes, identities = [], {}

        def visit(value, depth):
            if depth > 8 or not isinstance(value, dict):
                raise ValueError("invalid or overdeep task expression")
            identity = canonical(value)
            if identity in identities:
                return identities[identity]
            if value.get("op") == "read":
                if (
                    set(value) != {"op", "kind", "entity", "at"}
                    or value["kind"] not in {"event", "semantic", "procedure"}
                    or type(value["at"]) is not int
                    or value["at"] not in (1, 2)
                ):
                    raise ValueError("invalid typed memory leaf")
                key_digest(value["entity"])
                node = {**value, "inputs": [], "type": "int" if value["kind"] == "event" else value["kind"]}
            else:
                if (
                    set(value) != {"op", "inputs"}
                    or value["op"] not in SIGNATURES
                    or not isinstance(value["inputs"], list)
                ):
                    raise ValueError("unregistered task operator")
                required, result = SIGNATURES[value["op"]]
                if len(value["inputs"]) != len(required):
                    raise ValueError("task arity mismatch")
                indexes = [visit(item, depth + 1) for item in value["inputs"]]
                if tuple(nodes[index]["type"] for index in indexes) != required:
                    raise ValueError("task input type mismatch")
                node = {"op": value["op"], "inputs": indexes, "type": result}
            if len(nodes) >= maximum_nodes:
                raise ValueError("task node budget exceeded")
            index = len(nodes)
            nodes.append(node)
            identities[identity] = index
            return index

        root = visit(expression, 0)
        if nodes[root]["type"] != "int":
            raise ValueError("task result must be an integer")
        leaves = [node for node in nodes if node["op"] == "read"]
        features = [
            1,
            int(any(n["kind"] == "event" and n["at"] == 1 for n in leaves)),
            int(any(n["kind"] == "procedure" and n["at"] == 1 for n in leaves)),
            int(any(n["kind"] == "procedure" and n["at"] == 2 for n in leaves)),
            int(len({n["entity"] for n in leaves}) > 1),
        ]
        features += [sum(n["kind"] == kind for n in leaves) for kind in ("event", "semantic", "procedure")]
        features += [sum(n["op"] == op for n in nodes) for op in ("apply", "difference", "sum")]
        shape = [{key: value for key, value in node.items() if key not in {"entity", "at"}} for node in nodes]
        return {
            "nodes": nodes,
            "root": root,
            "features": features,
            "shape": hashlib.sha256(canonical(shape)).hexdigest(),
            "expression": deepcopy(expression),
        }


def _cell_key(node):
    return node["entity"] if node["kind"] == "semantic" else f"{node['entity']}@{node['at']}"


class TaskExpert:
    """Actual parameter cells plus a declared event/program admission scope."""

    @classmethod
    def fit(cls, source, scope, name, *, seed, steps=500):
        result = cls()
        result.name, result.scope, result.cut = name, scope, source.cut
        width, result.event_times, result.program_times = EXPERTS[name]
        result.cells = {}
        for kind in ("semantic", "procedure"):
            times = (2,) if kind == "semantic" else result.program_times
            rows = [row for at in times for row in source.rows(scope, kind, at=at, cut=result.cut)]
            keys = [
                row["entity"] if kind == "semantic" else f"{row['entity']}@{at}"
                for at in times
                for row in source.rows(scope, kind, at=at, cut=result.cut)
            ]
            result.cells[kind] = AssociativeCell.fit(
                keys,
                [row["value"] for row in rows],
                seed,
                kind=kind,
                hidden=width,
                steps=steps,
                support_ids=[[row["source_id"]] for row in rows],
            )
        return result

    def planned_work(self, graph):
        work = 0
        for node in graph["nodes"]:
            if node["op"] != "read":
                work += 1
            elif node["kind"] == "event":
                if (
                    node["at"] not in self.event_times
                    or key_digest(node["entity"]) not in self.cells["semantic"].supports
                ):
                    return None
                work += 1
            else:
                cell = self.cells[node["kind"]]
                if key_digest(_cell_key(node)) not in cell.supports:
                    return None
                work += cell.dimension * cell.hidden + cell.hidden * len(cell.catalog)
        return work

    def execute(self, graph, source, *, maximum_work=150_000, maximum_reads=12):
        started = time.perf_counter()
        values, supports, models, work, reads = [], [], [], 0, 0
        reason, result = None, None

        def charge(amount):
            nonlocal work
            if work + amount > maximum_work:
                raise OverflowError("work budget exceeded")
            work += amount

        try:
            if canonical(TypedTaskCompiler().compile(graph["expression"])) != canonical(graph):
                raise ValueError("compiled graph integrity mismatch")
            if source.cut != self.cut:
                raise StaleSource("source cut changed")
            for cell in self.cells.values():
                source.validate_support(cell.lineage_sources, scope=self.scope, cut=self.cut)
            for node in graph["nodes"]:
                if node["op"] == "read":
                    if reads + 1 > maximum_reads:
                        raise OverflowError("read budget exceeded")
                    reads += 1
                    kind = node["kind"]
                    if kind == "event":
                        if node["at"] not in self.event_times:
                            raise StaleSource("event outside specialist scope")
                        charge(1)
                        row = source.resolve(self.scope, node["entity"], kind, at=node["at"], cut=self.cut)
                        value = row["value"]
                        supports.append(row["source_id"])
                    else:
                        cell = self.cells[kind]
                        charge(cell.dimension * cell.hidden + cell.hidden * len(cell.catalog))
                        row = cell.read(_cell_key(node))
                        if row["abstain"]:
                            raise StaleSource("parameter cell abstained")
                        value = row["value"]
                        validate_typed_value(kind, value)
                        supports.extend(row["support_ids"])
                        models.append(cell.parameters_digest())
                else:
                    args = [values[index] for index in node["inputs"]]
                    charge(1)
                    if node["op"] == "apply":
                        value = execute_program(*args)
                    elif node["op"] == "difference":
                        value = args[0] - args[1]
                    elif node["op"] == "sum":
                        value = args[0] + args[1]
                    else:
                        raise ValueError("unregistered task operator")
                    if type(value) is not int or abs(value) > 10**15:
                        raise ValueError("bounded integer result required")
                values.append(value)
            source.validate_support(supports, scope=self.scope, cut=self.cut)
            if source.cut != self.cut:
                raise StaleSource("source cut changed during task")
            result = values[graph["root"]]
        except (StaleSource, OverflowError, ValueError) as error:
            reason = str(error)
        return {
            "value": result,
            "abstain": reason,
            "support_ids": sorted(set(supports)),
            "parameter_digests": sorted(set(models)),
            "source_cut": self.cut,
            "work_proxy": work,
            "reads": reads,
            "seconds": time.perf_counter() - started,
        }

    def to_bytes(self):
        payload = {
            "schema": "hepta.memory.v6.task-expert.v1",
            "name": self.name,
            "scope": self.scope,
            "cut": self.cut,
            "event_times": self.event_times,
            "program_times": self.program_times,
            "cells": {kind: base64.b64encode(cell.to_bytes()).decode() for kind, cell in self.cells.items()},
        }
        return canonical({"payload": payload, "sha256": hashlib.sha256(canonical(payload)).hexdigest()})

    @classmethod
    def from_bytes(cls, raw):
        envelope = json.loads(raw)
        value = envelope["payload"]
        if set(envelope) != {"payload", "sha256"} or hashlib.sha256(canonical(value)).hexdigest() != envelope["sha256"]:
            raise ValueError("task expert integrity mismatch")
        if (
            set(value) != {"schema", "name", "scope", "cut", "event_times", "program_times", "cells"}
            or value["schema"] != "hepta.memory.v6.task-expert.v1"
        ):
            raise ValueError("invalid task expert schema")
        if (
            value["name"] not in EXPERTS
            or set(value["cells"]) != {"semantic", "procedure"}
            or type(value["cut"]) is not int
            or value["cut"] < 1
        ):
            raise ValueError("invalid task expert identity")
        width, event_times, program_times = EXPERTS[value["name"]]
        if tuple(value["event_times"]) != event_times or tuple(value["program_times"]) != program_times:
            raise ValueError("expert capability differs from registered scope")
        result = cls()
        for name in ("name", "scope", "cut", "event_times", "program_times"):
            setattr(result, name, value[name])
        result.cells = {
            kind: AssociativeCell.from_bytes(base64.b64decode(encoded, validate=True))
            for kind, encoded in value["cells"].items()
        }
        if any(cell.kind != kind or cell.hidden != width for kind, cell in result.cells.items()):
            raise ValueError("expert parameter type or capacity mismatch")
        return result


class FeedbackRouter:
    """Fit expected expert loss from observed selection outcomes and work only."""

    @classmethod
    def fit(cls, graphs, feedback, *, work_price=1e-6, ridge=0.01):
        start_wall, start_cpu = time.perf_counter(), time.process_time()
        names = list(EXPERTS)
        x = np.array([graph["features"] for graph in graphs], dtype=float)
        y = np.array(
            [
                [int(not row[name]["correct"]) + work_price * row[name]["actual"]["work_proxy"] for name in names]
                for row in feedback
            ]
        )
        if (
            not len(x)
            or x.shape != (len(feedback), len(FEATURES))
            or not np.isfinite(y).all()
            or ridge <= 0
            or work_price < 0
        ):
            raise ValueError("invalid router feedback")
        result = cls()
        result.names, result.work_price = names, work_price
        result.weights = np.linalg.solve(x.T @ x + ridge * np.eye(x.shape[1]), x.T @ y)
        result.constant = names[int(y.mean(axis=0).argmin())]
        result.family_assignment = {}
        for shape in sorted({graph["shape"] for graph in graphs}):
            indices = [i for i, graph in enumerate(graphs) if graph["shape"] == shape]
            result.family_assignment[shape] = names[int(y[indices].mean(axis=0).argmin())]
        result.receipt = {
            "rows": len(graphs),
            "ridge": ridge,
            "mean_squared_loss": float(np.mean((x @ result.weights - y) ** 2)),
            "feedback_digest": hashlib.sha256(canonical(feedback)).hexdigest(),
            "wall_seconds": time.perf_counter() - start_wall,
            "cpu_seconds": time.process_time() - start_cpu,
            "uses_entity_identifiers_or_answer_values_as_features": False,
        }
        return result

    def choose(self, graph):
        losses = np.asarray(graph["features"]) @ self.weights
        return self.names[int(losses.argmin())]

    def to_bytes(self):
        payload = {
            "schema": "hepta.memory.v6.feedback-router.v1",
            "features": FEATURES,
            "names": self.names,
            "weights": self.weights.tolist(),
            "work_price": self.work_price,
            "constant": self.constant,
            "family_assignment": self.family_assignment,
            "receipt": self.receipt,
        }
        return canonical({"payload": payload, "sha256": hashlib.sha256(canonical(payload)).hexdigest()})

    @classmethod
    def from_bytes(cls, raw):
        value = json.loads(raw)
        payload = value["payload"]
        if (
            set(value) != {"payload", "sha256"}
            or set(payload)
            != {"schema", "features", "names", "weights", "work_price", "constant", "family_assignment", "receipt"}
            or hashlib.sha256(canonical(payload)).hexdigest() != value["sha256"]
            or payload["schema"] != "hepta.memory.v6.feedback-router.v1"
        ):
            raise ValueError("router artifact integrity failure")
        if payload["features"] != list(FEATURES) or payload["names"] != list(EXPERTS):
            raise ValueError("router representation mismatch")
        result = cls()
        for name in ("names", "work_price", "constant", "family_assignment", "receipt"):
            setattr(result, name, payload[name])
        result.weights = np.array(payload["weights"], dtype=float)
        if result.weights.shape != (len(FEATURES), len(EXPERTS)) or not np.isfinite(result.weights).all():
            raise ValueError("invalid routing parameters")
        return result


def _leaf(kind, entity, at=2):
    return {"op": "read", "kind": kind, "entity": entity, "at": at}


def _join(op, *inputs):
    return {"op": op, "inputs": list(inputs)}


def _tasks(entities, *, combinations):
    """A fixed typed grammar generates many identities/context combinations."""
    result = []
    for i, a in enumerate(entities):
        b = entities[(i + 1) % len(entities)]
        for at in (1, 2):
            for version in (1, 2):
                event, program, semantic = _leaf("event", a, at), _leaf("procedure", a, version), _leaf("semantic", a)
                if combinations:
                    event = _join("difference", event, _leaf("event", b, 3 - at))
                    if i % 2:
                        event = _join("sum", event, _leaf("event", a, 3 - at))
                    expression = _join("apply", _leaf("procedure", b, version), event, semantic)
                else:
                    expression = _join("apply", program, event, semantic)
                    if i % 2:
                        expression = _join("difference", expression, _leaf("event", b, at))
                result.append(expression)
    return result


def _gold(expression, source, scope):
    """Source-side grader; deliberately never calls the serving interpreter."""
    if expression["op"] == "read":
        row = source.resolve(scope, expression["entity"], expression["kind"], at=expression["at"], cut=source.cut)
        return row["value"], {row["source_id"]}
    values = [_gold(item, source, scope) for item in expression["inputs"]]
    args, ids = [item[0] for item in values], set().union(*(item[1] for item in values))
    if expression["op"] == "difference":
        return args[0] - args[1], ids
    if expression["op"] == "sum":
        return args[0] + args[1], ids
    program, event, semantic = args
    opcode, bias, factor = program["opcode"], program["bias"], semantic["factor"]
    arithmetic = {
        "identity": event,
        "add_bias": event + bias,
        "multiply": event * factor,
        "affine": event * factor + bias,
    }
    value = (
        max(-program["limit"], min(program["limit"], event * factor + bias))
        if opcode == "clamp"
        else arithmetic[opcode]
    )
    return value, ids


def run_transfer_study(seed, output_dir):
    """Freeze allocation before new-domain writes, then evaluate novel DAGs."""
    started_wall, started_cpu = time.perf_counter(), time.process_time()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    source, scope = EventStore(output / "source.sqlite"), f"transfer-{seed}"
    rng, compiler = np.random.default_rng(seed), TypedTaskCompiler()
    entities = [
        f"{'old' if i < 12 else 'new'}/" + hashlib.sha256(f"{seed}:{i}".encode()).hexdigest()[:16] for i in range(20)
    ]
    all_sources, generation_costs, feedback, selection_expected = [], [], [], []

    def write(indexes):
        for i in indexes:
            entity = entities[i]
            rows = [
                ("semantic", 2, {"factor": int(rng.integers(1, 6)), "label": f"category-{int(rng.integers(0, 4))}"})
            ]
            for at in (1, 2):
                rows.extend(
                    [
                        ("event", at, int(rng.integers(-20, 21))),
                        (
                            "procedure",
                            at,
                            {
                                "opcode": OPCODES[int(rng.integers(0, len(OPCODES)))],
                                "bias": int(rng.integers(-7, 8)),
                                "limit": int(rng.integers(4, 25)),
                            },
                        ),
                    ]
                )
            for kind, at, value in rows:
                identity = source.append(
                    scope=scope,
                    entity=entity,
                    kind=kind,
                    effective_at=at,
                    value=value,
                    origin_id=f"synthetic-{i}-{kind}-{at}",
                )
                all_sources.append(source.record(identity))

    def train(generation):
        experts = {name: TaskExpert.fit(source, scope, name, seed=seed) for name in EXPERTS}
        costs = {}
        for name, expert in experts.items():
            raw = expert.to_bytes()
            (output / f"generation-{generation}-{name}.json").write_bytes(raw)
            costs[name] = {
                "serialized_bytes": len(raw),
                "cells": {kind: cell.cost() for kind, cell in expert.cells.items()},
                "training_work_proxy": sum(
                    cell.training_receipt["examples_seen"]
                    * (cell.dimension * cell.hidden + cell.hidden * len(cell.catalog))
                    for cell in expert.cells.values()
                ),
            }
            experts[name] = TaskExpert.from_bytes(raw)
        generation_costs.append(costs)
        return experts

    try:
        write(range(12))
        experts = train(1)
        selection_graphs = [compiler.compile(expr) for expr in _tasks(entities[:8], combinations=False)]
        for graph in selection_graphs:
            expected, ids = _gold(graph["expression"], source, scope)
            selection_expected.append({"value": expected, "support_ids": sorted(ids)})
            row = {}
            for name, expert in experts.items():
                actual = expert.execute(graph, source)
                row[name] = {
                    "actual": actual,
                    "correct": actual["abstain"] is None
                    and actual["value"] == expected
                    and set(actual["support_ids"]) == ids,
                }
            feedback.append(row)
        router = FeedbackRouter.fit(selection_graphs, feedback)
        router_raw = router.to_bytes()
        router = FeedbackRouter.from_bytes(router_raw)
        (output / "router.json").write_bytes(router_raw)
        (output / "selection-feedback.json").write_bytes(
            canonical({"graphs": selection_graphs, "expected": selection_expected, "feedback": feedback})
        )
        # No test feedback or newly written entity identifiers update the router.
        write(range(12, 20))
        experts = train(2)
        populations = {
            "old_domain_new_combinations": _tasks(entities[8:12], combinations=True),
            "new_domain_known_combinations": _tasks(entities[12:], combinations=False),
            "new_domain_new_combinations": _tasks(entities[12:], combinations=True),
        }
        summaries, raw_results = {}, []
        for population, expressions in populations.items():
            stats = {
                name: {
                    "rows": 0,
                    "correct": 0,
                    "abstained": 0,
                    "work_proxy": 0,
                    "routing_seconds": 0.0,
                    "read_seconds": 0.0,
                    "assignments": {},
                }
                for name in ("learned", "general", "constant", "fixed_family", "fixed_capability")
            }
            for index, expression in enumerate(expressions):
                graph = compiler.compile(expression)
                expected, ids = _gold(expression, source, scope)
                actuals = {}
                for strategy in stats:
                    start = time.perf_counter()
                    if strategy == "learned":
                        chosen = router.choose(graph)
                    elif strategy == "fixed_capability":
                        eligible = [
                            (work, name)
                            for name, expert in experts.items()
                            if (work := expert.planned_work(graph)) is not None
                        ]
                        chosen = min(eligible)[1] if eligible else "general"
                    elif strategy == "fixed_family":
                        chosen = router.family_assignment.get(graph["shape"], router.constant)
                    else:
                        chosen = "general" if strategy == "general" else router.constant
                    routing_seconds = time.perf_counter() - start
                    actual = experts[chosen].execute(graph, source)
                    correct = (
                        actual["abstain"] is None and actual["value"] == expected and set(actual["support_ids"]) == ids
                    )
                    row = stats[strategy]
                    row["rows"] += 1
                    row["correct"] += correct
                    row["abstained"] += actual["abstain"] is not None
                    row["work_proxy"] += actual["work_proxy"]
                    row["routing_seconds"] += routing_seconds
                    row["read_seconds"] += actual["seconds"]
                    row["assignments"][chosen] = row["assignments"].get(chosen, 0) + 1
                    actuals[strategy] = {"expert": chosen, "actual": actual, "correct": correct}
                raw_results.append(
                    {
                        "id": f"{population}-{index}",
                        "population": population,
                        "graph": graph,
                        "expected": expected,
                        "expected_support_ids": sorted(ids),
                        "strategies": actuals,
                    }
                )
            summaries[population] = stats
        budget_probe = experts["general"].execute(
            compiler.compile(populations["new_domain_new_combinations"][0]), source, maximum_work=1
        )
        (output / "source-ledger.json").write_bytes(canonical(all_sources))
        (output / "raw-results.json").write_bytes(canonical(raw_results))
        report = {
            "schema": "hepta.memory.v6.structured-transfer.v1",
            "seed": seed,
            "populations": summaries,
            "router_training": router.receipt,
            "router_unchanged_after_new_domain": router.to_bytes() == router_raw,
            "router_parameter_bytes": router.weights.nbytes,
            "router_serialized_bytes": len(router_raw),
            "routing_work_proxy_per_query": int(router.weights.size),
            "routing_features": FEATURES,
            "selection_task_count": len(selection_graphs),
            "selection_shapes": sorted({g["shape"] for g in selection_graphs}),
            "test_shapes": {
                name: sorted({compiler.compile(expr)["shape"] for expr in expressions})
                for name, expressions in populations.items()
            },
            "generation_costs": generation_costs,
            "all_selection_expert_work_proxy": sum(
                value["actual"]["work_proxy"] for row in feedback for value in row.values()
            ),
            "fixed_capability_uses_gold_answers": False,
            "budget_probe": budget_probe,
            "registered_task_operators": list(SIGNATURES),
            "registered_procedure_opcodes": OPCODES,
            "specialist_registry": {
                name: {"hidden_width": spec[0], "event_times": spec[1], "procedure_versions": spec[2]}
                for name, spec in EXPERTS.items()
            },
            "expert_capability_scopes_predeclared": True,
            "new_specialist_scopes_invented": False,
            "test_feedback_used_for_routing": False,
            "new_natural_language_intents_supported": False,
            "new_types_or_primitives_invented": False,
            "full_cost_net_gain_claimed": False,
            "work_proxy_is_hardware_flops": False,
            "full_process_rss_measured": False,
            "scope": "structured typed grammar; learned allocation transfers, association values require writes and model rebuilds",
            "wall_seconds": time.perf_counter() - started_wall,
            "cpu_seconds": time.process_time() - started_cpu,
        }
    finally:
        source.close()
    report["all_source_model_feedback_result_file_bytes"] = sum(
        path.stat().st_size for path in output.iterdir() if path.is_file()
    )
    (output / "REPORT.json").write_bytes(canonical(report))
    files = {
        path.name: {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in output.iterdir()
        if path.is_file()
    }
    (output / "MANIFEST.json").write_bytes(canonical({"files": files}))
    return report
