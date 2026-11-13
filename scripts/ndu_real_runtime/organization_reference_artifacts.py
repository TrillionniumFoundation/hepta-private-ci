"""Create-only artifacts for the Python ORG-1 reference; no trusted receipts."""

import hashlib
import inspect
import json
import os
from pathlib import Path
import platform

from .causal_protocol import COMMON_MATCHES, COST_STAGES
from .causal_topology import ARMS, COUNTERS
from .metering import canonical_sha
from .organization_policy import AXES, STAGES


def encoded(value):
    return (
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()


def write(root, name, value, *, lines=False):
    raw = (
        b"".join(encoded(row).replace(b"\n", b" ") + b"\n" for row in value)
        if lines
        else encoded(value)
    )
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def replace(path, raw):
    temporary = path.with_suffix(path.suffix + ".pending")
    with temporary.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def graph(names, generation, bundle):
    return {
        "generation": generation,
        "nodes": [
            {
                "id": name,
                "state_owner": "python-reference:" + name,
                "bundle_sha256": bundle,
            }
            for name in sorted(names)
        ],
        "edges": [[name, "recovery"] for name in sorted(names) if name != "recovery"],
    }


def source_identity(runner):
    """Bind both implementation files; this is not a complete dependency closure."""
    files = {}
    for path in (Path(runner), Path(__file__)):
        raw = path.read_bytes()
        files[path.name] = {
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    return {"files": files, "sha256": canonical_sha(files)}


def prepare(root, operation, source, router):
    names = (
        ["left", "right", "recovery"]
        if operation == "merge"
        else ["general", "recovery"]
    )
    before = graph(names, 1, source["sha256"])
    initial = {
        "generation": 1,
        "states": {n: {"records": {}} for n in names if n != "recovery"}
        | {"recovery": {"completed": {}}},
    }
    for index in range(12):
        node = ("left", "right")[index % 2] if operation == "merge" else "general"
        initial["states"][node]["records"][f"k{index:02}"] = index * 10
    common = {
        "before_graph": write(root, "before-graph.json", before),
        "before_state": write(root, "before-state.json", initial),
    }
    inventory = write(
        root,
        "protected-capabilities.json",
        {"schema": "hepta.org1.capabilities.v1", "protected": ["recovery:lost_ack"]},
    )
    roster = []
    for seed in (17, 29, 41):
        for panel, indices, delta in (
            ("ordinary", range(8), 1),
            ("retention", (10, 11), 0),
            ("rare_fault", (8,), 3),
        ):
            for index in indices:
                pair = f"seed-{seed}:{panel}:{index}"
                roster.append(
                    {
                        "pair_id": pair,
                        "task_id": "task-" + pair,
                        "seed": seed,
                        "panel": panel,
                        "capability_id": "recovery:lost_ack"
                        if panel == "rare_fault"
                        else None,
                        "key": f"k{index:02}",
                        "delta": delta,
                    }
                )
    recovery = {
        "schema": "hepta.org1.reference-recovery-policy.v1",
        "faults": {ARMS[0]: "dispatch", ARMS[1]: "migration"},
        "restore": "saved original graph and state bytes",
        "scope": "different failure modes; mechanism demonstrations, not a common physical fault distribution",
    }
    contracts = {
        "initial_artifacts_sha256": canonical_sha(
            {"source": source, "artifacts": common, "recovery_policy": recovery}
        ),
        "objective_sha256": canonical_sha(
            {"goal": "exact key increments and idempotent lost-ACK replay"}
        ),
        "scheduler_sha256": hashlib.sha256(
            inspect.getsource(router).encode()
        ).hexdigest(),
        "scheduler_tuning_sha256": canonical_sha(
            {"method": "dictionary lookup", "tuning_trials": 0}
        ),
        "evaluation_sha256": canonical_sha(roster),
        "before_graph_sha256": canonical_sha(before),
        "before_state_sha256": common["before_state"]["sha256"],
        "capability_inventory_sha256": inventory["sha256"],
    }
    protocol = {
        "schema": "hepta.org1.protocol.v1",
        "scope": "synthetic_reference",
        "operation": operation,
        "candidate_id": "reference-" + operation,
        "contracts": contracts,
        "recovery_policy": recovery,
        "trigger_rule": {
            "kind": "capacity_bottleneck",
            "metric": "measured_capacity_pressure",
            "minimum_windows": 3,
            "minimum_samples_per_window": 4,
            "minimum_value": 0.9,
        },
        "roster": roster,
        "protected_capabilities": [
            {
                "capability_id": "recovery:lost_ack",
                "minimum_score": 1.0,
                "maximum_drop": 0.0,
            }
        ],
        "required_cost_axes": list(AXES),
        "utility_rates": {a: 1e-6 for a in AXES},
        "budget": {a: 1e9 for a in AXES},
        "minimum_mean_net_gain": 0.01,
        "maximum_retention_drop": 0.0,
        "comparison_method": "finite_paired_panel",
    }
    write(root, "PROTOCOL.json", protocol)
    write(root, "SOURCE.json", source)
    return protocol, before, initial, common, inventory


class ArmArtifacts:
    def __init__(self, root, protocol, arm, run_id, before, initial, common):
        self.root, self.protocol, self.arm, self.run_id = root, protocol, arm, run_id
        self.prefix = "fixed" if arm == ARMS[0] else "dynamic"
        self.identity = {
            "arm_id": arm,
            "run_id": run_id,
            "protocol_sha256": canonical_sha(protocol),
        }
        self.before, self.initial, self.refs = before, initial, dict(common)
        self.receipt = None

    def write(self, name, value, *, lines=False):
        return write(self.root, self.prefix + "/" + name, value, lines=lines)

    def installed(self, after, state, operation, migration_policy):
        self.after = after
        self.refs["after_graph"] = self.write("after-graph.json", after)
        self.refs["after_state"] = self.write("after-state.json", state)
        old, new = (
            {n["id"] for n in self.before["nodes"]},
            {n["id"] for n in after["nodes"]},
        )
        removed, added = old - new, new - old
        sources, targets = (removed, added) if removed or added else (old, new)
        self.migrated_items = sum(
            len(self.initial["states"][n].get("records", {})) for n in removed
        )
        self.refs["migration"] = self.write(
            "migration.json",
            {
                "mode": "migrate" if removed else "preserve",
                "policy_sha256": hashlib.sha256(
                    inspect.getsource(migration_policy).encode()
                ).hexdigest(),
                "before_state_sha256": self.refs["before_state"]["sha256"],
                "after_state_sha256": self.refs["after_state"]["sha256"],
                "source_values": {
                    n: canonical_sha(self.initial["states"][n]) for n in sources
                },
                "target_values": {
                    n: canonical_sha(state["states"][n]) for n in targets
                },
            },
        )
        matches = {
            k: canonical_sha({"dimension": k, "contracts": self.protocol["contracts"]})
            for k in COMMON_MATCHES
        }
        matches["recovery_mechanism"] = canonical_sha(self.protocol["recovery_policy"])
        self.receipt = {
            "schema": "hepta.cell-causal.topology.v1",
            "arm_id": self.arm,
            "run_id": self.run_id,
            "paired_fit_id": self.protocol["candidate_id"],
            "adaptation_task_id": "partition-state",
            "next_task_id": "successor-panel",
            "adaptive_scheduler_sha256": self.protocol["contracts"]["scheduler_sha256"],
            "max_nodes": 4,
            "transition": {
                "kind": operation,
                "consumed": sorted(removed),
                "produced": sorted(added),
            },
            "matches": matches,
            "artifacts": self.refs,
        }

    def seal(self, observer, trace, trials, observations, recovery, post_state):
        raw = self.write(
            "execution-observations.json",
            {
                "scope": "self_observed_python_reference",
                "trials": observations,
                "spans": observer.spans,
            },
        )
        trial_refs = [
            self.write(f"trial-{i:03}.json", row | self.identity)
            for i, row in enumerate(trials)
        ]
        cost_refs = [
            self.write(
                f"cost-{stage}.json",
                self.identity
                | {
                    "event_id": self.prefix + ":" + stage,
                    "stage": stage,
                    "values": observer.totals(stage),
                    "evidence_sha256": raw["sha256"],
                },
            )
            for stage in STAGES
        ]
        self.refs["trace"] = self.write("successor-trace.jsonl", trace, lines=True)
        self.refs["recovery"] = self.write("recovery.json", recovery)
        stage_map = {
            "controller": "inference",
            "messages": "communication",
            "graph_compile": "loading",
            "evaluation": "evaluation",
            "migration": "migration",
            "recovery": "recovery",
            "io": "maintenance",
            "training": "training",
            "search": "search",
        }
        d_costs = []
        for stage in COST_STAGES:
            spans = [s for s in observer.spans if s["stage"] == stage_map.get(stage)]
            counters = {k: 0 for k in COUNTERS.get(stage, ())}
            counters.update(
                {
                    "messages": sum(e["type"] == "message" for e in trace),
                    "message_bytes": observer.transferred["communication"],
                }
                if stage == "messages"
                else {}
            )
            if stage == "reencoding":
                counters["encoder_calls"] = len(trials)
            if stage == "graph_compile":
                counters["graphs_compiled"] = 1
            if stage == "migration":
                counters.update(
                    state_items=self.migrated_items,
                    bytes_migrated=observer.transferred["migration"],
                )
            if stage == "evaluation":
                counters["evaluation_calls"] = len(trials)
            if stage == "recovery":
                counters["recovery_attempts"] = 1 + sum(
                    r["panel"] == "rare_fault" for r in self.protocol["roster"]
                )
            d_costs.append(
                {
                    "event_id": stage,
                    "stage": stage,
                    "methods": [self.arm],
                    "parent_event_id": None,
                    "measurements": {
                        "wall_seconds": sum(s["wall_seconds"] for s in spans),
                        "cpu_seconds": sum(s["cpu_seconds"] for s in spans),
                        "energy_joules": None,
                        "provider_charges": None,
                    },
                    "provider_charges_unit": "USD",
                    "counters": counters,
                }
            )
        self.refs["costs"] = self.write("d-costs.json", d_costs)
        receipt = self.receipt
        owner = {
            "schema": "hepta.cell-causal.topology-owner.v1",
            "host": "python-reference:" + platform.node(),
            "original_job_id": self.run_id,
            "terminal": "completed",
            "run_id": self.run_id,
            "arm_id": self.arm,
            "self_observed_only": True,
            "comparison_sha256": canonical_sha(
                {
                    k: receipt[k]
                    for k in (
                        "matches",
                        "adaptive_scheduler_sha256",
                        "max_nodes",
                        "paired_fit_id",
                    )
                }
            ),
            "transition_sha256": canonical_sha(receipt["transition"]),
            "installed_graph_sha256": canonical_sha(self.after),
            "artifact_sha256s": {k: ref["sha256"] for k, ref in self.refs.items()},
        }
        self.refs["owner"] = self.write("self-observed-owner.json", owner)
        self.write("topology-receipt.json", receipt)
        self.write("post-task-state.json", post_state)
        return {
            "contracts": self.protocol["contracts"],
            "trials": trial_refs,
            "costs": cost_refs,
        }, receipt
