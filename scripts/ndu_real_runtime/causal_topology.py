"""Validate concrete D execution evidence; a graph manifest cannot prove a run."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

from .causal_analysis import cost_inventory
from .causal_protocol import digest, match_contracts
from .metering import atomic_json, canonical_sha

ARTIFACTS = (
    "before_graph",
    "after_graph",
    "before_state",
    "after_state",
    "migration",
    "trace",
    "recovery",
    "costs",
    "owner",
)
COUNTERS = {
    "messages": ("messages", "message_bytes"),
    "reencoding": ("encoder_calls", "duplicate_encoder_calls"),
    "search": ("candidates_evaluated",),
    "graph_compile": ("graphs_compiled",),
    "training": ("optimizer_steps",),
    "migration": ("state_items", "bytes_migrated"),
    "evaluation": ("evaluation_calls",),
    "recovery": ("recovery_attempts",),
}
ARMS = ("fixed_graph_adaptive_scheduler", "dynamic_graph_same_scheduler")


def _artifact(root, reference, *, json_lines=False):
    name = reference["path"]
    relative = PurePosixPath(name)
    if relative.is_absolute() or any(p in {"", ".", ".."} for p in name.split("/")):
        raise ValueError("unsafe evidence path")
    path = root / relative
    if (
        path.is_symlink()
        or not path.is_file()
        or not path.resolve().is_relative_to(root)
        or type(reference["bytes"]) is not int
        or not 0 < reference["bytes"] <= 8 * 1024**2
        or path.stat().st_size != reference["bytes"]
        or not digest(reference["sha256"])
    ):
        raise ValueError("missing, changed or oversized evidence: " + name)
    data = path.read_bytes()
    if (
        len(data) != reference["bytes"]
        or hashlib.sha256(data).hexdigest() != reference["sha256"]
    ):
        raise ValueError("missing, changed or oversized evidence: " + name)
    if json_lines:
        rows = [json.loads(line) for line in data.splitlines() if line.strip()]
        if not 1 <= len(rows) <= 20000:
            raise ValueError("bounded nonempty next-task trace required")
        return rows
    return json.loads(data)


def _graph(graph, capacity):
    nodes, edges = graph["nodes"], graph["edges"]
    ids = [n["id"] for n in nodes]
    if (
        type(graph["generation"]) is not int
        or graph["generation"] < 1
        or not 1 <= len(nodes) <= capacity
        or ids != sorted(set(ids))
        or len(edges) > 1024
        or edges != sorted([list(e) for e in {tuple(e) for e in edges}])
    ):
        raise ValueError("invalid canonical graph shape")
    for node in nodes:
        if (
            not isinstance(node["id"], str)
            or not node["id"]
            or not node.get("state_owner")
            or not digest(node.get("bundle_sha256"))
        ):
            raise ValueError("node identity, actual state owner and bundle required")
    if any(len(e) != 2 or e[0] not in ids or e[1] not in ids for e in edges):
        raise ValueError("message edge refers to absent node")
    return {n["id"]: n for n in nodes}, {tuple(e) for e in edges}


def _validate(receipt, root, trusted_observer_sha256):
    if (
        receipt["schema"] != "hepta.cell-causal.topology.v1"
        or receipt["arm_id"] not in ARMS
    ):
        raise ValueError("unsupported D receipt")
    if (
        not receipt["run_id"]
        or not receipt["paired_fit_id"]
        or not receipt["adaptation_task_id"]
        or not receipt["next_task_id"]
        or receipt["next_task_id"] == receipt["adaptation_task_id"]
        or not digest(receipt["adaptive_scheduler_sha256"])
        or type(receipt["max_nodes"]) is not int
        or not 1 <= receipt["max_nodes"] <= 256
    ):
        raise ValueError(
            "distinct next task, paired fit and bounded scheduler contract required"
        )
    refs = receipt["artifacts"]
    if (
        set(refs) != set(ARTIFACTS)
        or sum(r["bytes"] for r in refs.values()) > 32 * 1024**2
    ):
        raise ValueError("complete bounded artifact inventory required")
    evidence = {
        key: _artifact(root, refs[key], json_lines=key == "trace") for key in ARTIFACTS
    }
    before, after = evidence["before_graph"], evidence["after_graph"]
    old, old_edges = _graph(before, receipt["max_nodes"])
    new, new_edges = _graph(after, receipt["max_nodes"])
    transition = receipt["transition"]
    kind = transition["kind"]
    removed, added = set(old) - set(new), set(new) - set(old)
    if transition["consumed"] != sorted(removed) or transition["produced"] != sorted(
        added
    ):
        raise ValueError("declared split/merge membership differs from actual graphs")
    if any(old[n] != new[n] for n in set(old) & set(new)):
        raise ValueError(
            "topology contrast also changed retained node bundles or ownership"
        )
    if receipt["arm_id"] == ARMS[0]:
        if kind != "no_change" or before != after:
            raise ValueError("fixed adaptive-scheduler arm changed its graph")
    elif (
        kind == "split"
        and not (len(removed) == 1 and len(added) >= 2)
        or kind == "merge"
        and not (len(removed) >= 2 and len(added) == 1)
        or kind == "rewire"
        and not (not removed and not added and old_edges != new_edges)
        or kind not in {"split", "merge", "rewire"}
        or after["generation"] != before["generation"] + 1
    ):
        raise ValueError("dynamic arm lacks the actual declared generation transition")
    before_state, after_state = evidence["before_state"], evidence["after_state"]
    for state, graph, nodes in ((before_state, before, old), (after_state, after, new)):
        if state["generation"] != graph["generation"] or set(state["states"]) != set(
            nodes
        ):
            raise ValueError("state snapshot does not cover the installed membership")
    if any(
        before_state["states"][n] != after_state["states"][n]
        for n in set(old) & set(new)
    ):
        raise ValueError(
            "unrelated retained state changed during topology installation"
        )
    migration = evidence["migration"]
    sources, targets = (removed, added) if removed or added else (set(old), set(new))
    if (
        migration["before_state_sha256"] != refs["before_state"]["sha256"]
        or migration["after_state_sha256"] != refs["after_state"]["sha256"]
        or migration["source_values"]
        != {n: canonical_sha(before_state["states"][n]) for n in sources}
        or migration["target_values"]
        != {n: canonical_sha(after_state["states"][n]) for n in targets}
        or not digest(migration.get("policy_sha256"))
        or migration["mode"] not in {"migrate", "reset", "preserve"}
    ):
        raise ValueError("state migration/reset is not bound to actual state bytes")
    if kind in {"split", "merge"} and migration["mode"] == "preserve":
        raise ValueError("split/merge requires explicit migrate or reset semantics")
    if migration["mode"] == "reset" and not digest(migration.get("initializer_sha256")):
        raise ValueError("reset initializer must be pinned separately from migration")
    costs = evidence["costs"]
    budget = cost_inventory(costs, [receipt["arm_id"]])
    if not budget["whole_budget_complete"]:
        raise ValueError("full cost contains unknown measurements or missing stages")
    by_cost = {row["event_id"]: row for row in costs}
    counters = {stage: {key: 0 for key in keys} for stage, keys in COUNTERS.items()}
    for event in costs:
        for key in COUNTERS.get(event["stage"], ()):
            value = event.get("counters", {}).get(key)
            if type(value) is not int or value < 0:
                raise ValueError("missing nonnegative organization counter: " + key)
            counters[event["stage"]][key] += value
    if (
        counters["recovery"]["recovery_attempts"] < 1
        or counters["evaluation"]["evaluation_calls"] < 1
    ):
        raise ValueError("recovery and evaluation were not metered")
    if receipt["arm_id"] == ARMS[1] and (
        counters["graph_compile"]["graphs_compiled"] < 1
        or counters["search"]["candidates_evaluated"] < 1
    ):
        raise ValueError(
            "dynamic graph search and installation compilation are unmetered"
        )
    trace, dispatched, messages, message_bytes, encodings = (
        evidence["trace"],
        set(),
        [],
        0,
        [],
    )
    for index, event in enumerate(trace):
        if (
            event["sequence"] != index
            or event["run_id"] != receipt["run_id"]
            or event["task_id"] != receipt["next_task_id"]
            or event["generation"] != after["generation"]
            or event["graph_sha256"] != canonical_sha(after)
        ):
            raise ValueError("next task did not consume the exact installed graph")
        if event["type"] == "dispatch":
            if (
                event["node_id"] not in new
                or event["state_owner"] != new[event["node_id"]]["state_owner"]
            ):
                raise ValueError(
                    "next-task dispatch used an absent node or wrong owner"
                )
            dispatched.add(event["node_id"])
        elif event["type"] == "message":
            edge = (event["from"], event["to"])
            if (
                edge not in new_edges
                or type(event["bytes"]) is not int
                or event["bytes"] < 0
            ):
                raise ValueError("next-task message violates actual graph reachability")
            messages.append(edge)
            message_bytes += event["bytes"]
            if by_cost[event["cost_event_id"]]["stage"] != "messages":
                raise ValueError("message lacks its original cost event")
        elif event["type"] == "encode":
            if (
                not digest(event["input_sha256"])
                or by_cost[event["cost_event_id"]]["stage"] != "reencoding"
            ):
                raise ValueError("encoding lacks input identity or cost")
            encodings.append(event["input_sha256"])
        else:
            raise ValueError("unknown next-task trace event")
    if not dispatched or not added <= dispatched:
        raise ValueError("successor nodes were not actually executed on the next task")
    if kind == "rewire" and not (new_edges - old_edges) & set(messages):
        raise ValueError("new edge was not consumed by next-task messaging")
    if (
        counters["messages"]["messages"] < len(messages)
        or counters["messages"]["message_bytes"] < message_bytes
        or counters["reencoding"]["encoder_calls"] < len(encodings)
        or counters["reencoding"]["duplicate_encoder_calls"]
        < len(encodings) - len(set(encodings))
    ):
        raise ValueError("observed communication/reencoding exceeds charged counters")
    recovery = evidence["recovery"]
    if (
        not recovery.get("original_job_id")
        or recovery.get("injected_failure")
        not in {"compile", "start", "migration", "dispatch"}
        or recovery["restored_graph"] != before
        or recovery["restored_state"] != before_state
        or recovery.get("events")
        != ["failure_observed", "rollback_completed", "restored_state_readback"]
    ):
        raise ValueError(
            "actual failed-transition recovery and state readback are absent"
        )
    owner = evidence["owner"]
    comparison = {
        key: receipt[key]
        for key in (
            "matches",
            "adaptive_scheduler_sha256",
            "max_nodes",
            "paired_fit_id",
        )
    }
    if (
        owner.get("schema") != "hepta.cell-causal.topology-owner.v1"
        or not owner.get("host")
        or not owner.get("original_job_id")
        or owner.get("terminal") != "completed"
        or owner.get("run_id") != receipt["run_id"]
        or owner.get("arm_id") != receipt["arm_id"]
        or owner.get("comparison_sha256") != canonical_sha(comparison)
        or owner.get("transition_sha256") != canonical_sha(transition)
        or owner.get("artifact_sha256s")
        != {k: v["sha256"] for k, v in refs.items() if k != "owner"}
        or owner.get("installed_graph_sha256") != canonical_sha(after)
    ):
        raise ValueError("original execution owner did not bind all evidence")
    if refs["owner"]["sha256"] not in trusted_observer_sha256:
        raise ValueError(
            "independently pinned original-host observer receipt is missing"
        )
    return {
        "operation": kind,
        "before_graph_sha256": canonical_sha(before),
        "before_state_sha256": canonical_sha(before_state),
        "after_graph_sha256": canonical_sha(after),
        "state_mode": migration["mode"],
        "cost_inventory": budget,
        "organization_counters": counters,
        "next_task_dispatches": len(dispatched),
        "next_task_messages": len(messages),
    }


def validate_topology_receipt(receipt, evidence_root, *, trusted_observer_sha256=()):
    """Read original artifacts and an externally trusted observer pin, never just declarations."""
    report = {
        "schema": "hepta.cell-causal.topology-validation.v1",
        "status": "BLOCKED",
        "blockers": [],
        "scientific_acceptance": "HOLD",
        "benefit_proven": False,
        "adoption_authorized": False,
    }
    missing = sorted(set(ARTIFACTS) - set(receipt.get("artifacts", {})))
    if missing:
        return {
            **report,
            "blockers": ["missing evidence artifact: " + name for name in missing],
        }
    try:
        checked = _validate(
            receipt,
            Path(evidence_root).resolve(strict=True),
            set(trusted_observer_sha256),
        )
    except (KeyError, TypeError, ValueError, OSError, IndexError) as error:
        return {**report, "blockers": [str(error)]}
    return {
        **report,
        **checked,
        "status": "EVIDENCE_CONSISTENT",
        "independent_observer_pin_matched": True,
    }


def validate_topology_pair(
    fixed, dynamic, evidence_root, *, trusted_observer_sha256=()
):
    reports = [
        validate_topology_receipt(
            r, evidence_root, trusted_observer_sha256=trusted_observer_sha256
        )
        for r in (fixed, dynamic)
    ]
    blockers = [b for report in reports for b in report["blockers"]]
    try:
        matches = match_contracts([fixed, dynamic])
        if [fixed["arm_id"], dynamic["arm_id"]] != list(ARMS) or not matches[
            "declared_matching"
        ]:
            blockers.append(
                "fixed/dynamic arms do not share complete matched contracts"
            )
        for key in (
            "adaptive_scheduler_sha256",
            "max_nodes",
            "paired_fit_id",
            "adaptation_task_id",
            "next_task_id",
        ):
            if fixed[key] != dynamic[key]:
                blockers.append("unequal paired contract: " + key)
        if (
            not blockers
            and reports[0]["before_graph_sha256"] != reports[1]["before_graph_sha256"]
        ):
            blockers.append("paired arms did not start with the same actual graph")
        if (
            not blockers
            and reports[0]["before_state_sha256"] != reports[1]["before_state_sha256"]
        ):
            blockers.append("paired arms did not start with the same actual state")
    except (KeyError, TypeError, ValueError) as error:
        blockers.append(str(error))
    return {
        "schema": "hepta.cell-causal.topology-pair.v1",
        "status": "BLOCKED" if blockers else "EVIDENCE_CONSISTENT",
        "blockers": blockers,
        "arms": reports,
        "scientific_acceptance": "HOLD",
        "benefit_proven": False,
        "remaining": "all split/merge/rewire operations, independent paired training repetitions and blinded quality/cost comparison",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--trusted-observer-sha256", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = validate_topology_receipt(
        json.loads(args.receipt.read_text()),
        args.evidence_root,
        trusted_observer_sha256=args.trusted_observer_sha256,
    )
    atomic_json(args.output, result)
    print(
        json.dumps(
            {
                "status": result["status"],
                "blockers": result["blockers"],
                "benefit_proven": False,
            }
        )
    )
    return 0 if result["status"] == "EVIDENCE_CONSISTENT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
