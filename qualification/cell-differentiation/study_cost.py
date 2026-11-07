"""Audit the cost population and named kernels against the frozen execution plan."""

from collections import Counter
import hashlib

from study_data import canonical_bytes
from study_model import PHASES


COST_FIELDS = ("requests", "estimated_float_ops", "route_decisions", "parameter_bytes",
               "serialized_bytes", "hash_input_bytes", "wall_time_ns")


def audit_cost(ledger, required=PHASES):
    if not required.issubset({e["phase"] for e in ledger}):
        raise ValueError("cost ledger is missing a required phase")
    for event in ledger:
        if not isinstance(event.get("complete"), bool) or not event.get("stage"):
            raise ValueError("cost event has no completion status or stage")
        for field in COST_FIELDS:
            value = event.get(field)
            if isinstance(value, int) and value >= 0:
                continue
            if not event["complete"] and value is None and field != "requests":
                continue
            raise ValueError("cost event contains missing or invalid quantities")


def total_cost(ledger):
    def known_sum(field):
        values = [e[field] for e in ledger]
        return sum(values) if all(v is not None for v in values) else None

    def known_max(field):
        values = [e[field] for e in ledger]
        return max(values, default=0) if all(v is not None for v in values) else None

    return {
        "estimated_float_ops": known_sum("estimated_float_ops"),
        "route_decisions": known_sum("route_decisions"),
        "hash_input_bytes": known_sum("hash_input_bytes"),
        "instrumented_wall_time_ns": sum(e["wall_time_ns"] for e in ledger if e["wall_time_ns"] is not None),
        "unmeasured_stage_count": sum(e["wall_time_ns"] is None for e in ledger),
        "retained_parameter_bytes": known_max("parameter_bytes"),
        "largest_serialized_snapshot_bytes": known_max("serialized_bytes"),
        "complete": all(e["complete"] for e in ledger),
    }


def retain_unfinished_stages(ledger, expected, failure):
    observed = {(e["phase"], e["stage"]) for e in ledger}
    for (phase, stage), quantities in expected.items():
        if (phase, stage) not in observed:
            event = {key: None for key in COST_FIELDS}
            event.update({"phase": phase, "stage": stage, "requests": quantities["requests"],
                          "complete": False,
                          "note": f"unknown or unexecuted after failure; no zero-cost credit: {failure}"})
            ledger.append(event)


def expected_events(name, payload, data, plan, propose_child, seed):
    """The cost contract derives from the plan, never reported event totals."""
    events = {}

    def add(phase, stage, **values):
        fields = {key: 0 for key in COST_FIELDS if key != "wall_time_ns"}
        fields.update(values)
        events[(phase, stage)] = fields

    def train(stage, n, dimension, batch, steps=plan.training_steps):
        ops = steps * (4 * n * dimension + n + 5 * dimension)
        if dimension == 10:
            ops += 4 * n
        add("train", stage, requests=n, estimated_float_ops=ops,
            parameter_bytes=8 * dimension, hash_input_bytes=batch.manifest()["data_bytes"])

    def observe(stage, batch, dimension, router, phase="eval", salt=""):
        n = len(batch.ids)
        hashed = sum(len((salt + "/" + i).encode()) for i in batch.ids) if router == "random" else 0
        add("route", stage, requests=n, route_decisions=n, hash_input_bytes=hashed)
        add(phase, stage, requests=n,
            estimated_float_ops=2 * n * dimension + 2 * n + (4 * n if dimension == 10 else 0))

    if name == "shared":
        add("setup", "dataset_and_freeze", requests=sum(len(b.ids) for b in data.values()))
        train("incumbent_pretrain", len(data["pretrain"].ids), 6, data["pretrain"])
        return events

    train_data = data["train"]
    n = len(train_data.ids)
    router = "shared"
    dimension = 10 if name == "expanded_monolith" else 6
    salt = ""
    if name == "demand_specialization":
        observe("demand_monitor", data["monitor"], 6, "shared")
        probe_n = int((train_data.task == 1).sum())
        add("train", "negative_transfer_one_step_probe", requests=probe_n,
            estimated_float_ops=4 * probe_n * 6 + probe_n + 3 * 6,
            parameter_bytes=48, hash_input_bytes=train_data.manifest()["data_bytes"])
        observe("negative_transfer_monitor", data["monitor"], 6, "shared")
    if name == "frozen_incumbent":
        add("train", "frozen_reuse")
    elif name == "demand_specialization" and not propose_child:
        add("train", "no_child_reuse")
    elif name in ("continued_parent", "expanded_monolith"):
        train(f"{name}_fit", n, dimension, train_data)
    else:
        router = "random" if name == "random_grouping" else "task"
        salt = f"precommitted-random/{seed}" if router == "random" else ""
        encoded = [(salt + "/" + i).encode() for i in train_data.ids]
        assignments = ([hashlib.sha256(i).digest()[0] % 2 for i in encoded]
                       if router == "random" else train_data.task.tolist())
        add("route", f"{name}_training_partition", requests=n, route_decisions=n,
            hash_input_bytes=sum(map(len, encoded)) if router == "random" else 0)
        if name == "demand_specialization":
            train("demand_child_fit", assignments.count(1), 6, train_data)
        else:
            for i in (0, 1):
                train(f"{name}_{i}_fit", assignments.count(i), 6, train_data)

    observe("validation", data["validation"], dimension, router, salt=salt)
    wire_size = len(canonical_bytes(payload)) if payload is not None else 0
    params = 8 * dimension * (1 if router == "shared" else 2)
    add("storage", "candidate_snapshot", parameter_bytes=params,
        serialized_bytes=wire_size, hash_input_bytes=wire_size)
    add("migration", "deserialize_snapshot", parameter_bytes=params,
        serialized_bytes=wire_size, hash_input_bytes=2 * wire_size)
    observe("migration_validation", data["validation"], dimension, router, "migration", salt)
    observe("test", data["test"], dimension, router, salt=salt)
    return events


def audit_stages(ledger, expected):
    actual = Counter((event["phase"], event["stage"]) for event in ledger)
    if actual != Counter({stage: 1 for stage in expected}):
        raise ValueError("a planned cost stage is missing, duplicated or substituted")
    for event in ledger:
        contract = expected[(event["phase"], event["stage"])]
        if event["requests"] != contract["requests"]:
            raise ValueError("cost event changed its original request denominator")
        if event["complete"] and any(event[field] != value for field, value in contract.items()):
            raise ValueError("cost quantities differ from the frozen steps/dimensions/kernel plan")
