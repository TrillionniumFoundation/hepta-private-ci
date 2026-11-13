"""Execute a bounded Python ORG-1 reference, never native learning or adoption.

Both arms use the same dictionary-indexed router. State keys move exactly once;
a deliberately interrupted move is restored from saved bytes before retrying.
Energy, provider charges and resident-byte integrals are unmeasured, so this
reference must remain HOLD. Self-observation is never an independent owner pin.
"""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import statistics
import time
import uuid

from .causal_topology import ARMS
from .metering import canonical_sha
from .organization_policy import STAGES, review_organization
from .organization_reference_artifacts import (
    ArmArtifacts,
    encoded as _bytes,
    graph as _graph,
    prepare,
    replace as _replace,
    source_identity,
    write as _write,
)


def _index(state):
    result = {}
    for node, content in state["states"].items():
        for key in content.get("records", {}):
            if key in result:
                raise ValueError("duplicate state-key owner")
            result[key] = node
    return result


def _route(index, key):
    return index[key]


def _values(state):
    return {
        key: state["states"][node]["records"][key]
        for key, node in _index(state).items()
    }


def _transition(graph, state, operation, persist, *, inject=False):
    """Partition/recombine actual values; transient checkpoints retain one owner."""
    original = copy.deepcopy(_values(state))
    if operation == "no_change":
        return graph, state
    graph["generation"] += 1
    state["generation"] += 1
    if operation == "rewire":
        graph["edges"] = sorted(graph["edges"] + [["recovery", "general"]])
        persist(graph, state)
        if inject:
            raise InterruptedError("injected after persisted edge update")
    else:
        sources, targets = (
            (("general",), ("left", "right"))
            if operation == "split"
            else (("left", "right"), ("general",))
        )
        bundle = graph["nodes"][0]["bundle_sha256"]
        for node in targets:
            state["states"][node] = {"records": {}}
        for source in sources:
            for key in list(state["states"][source]["records"]):
                target = targets[int(key[1:]) % len(targets)]
                state["states"][target]["records"][key] = state["states"][source][
                    "records"
                ].pop(key)
                if _values(state) != original:
                    raise ValueError("state lost or duplicated during migration")
                pending = _graph(state["states"], graph["generation"], bundle)
                persist(pending, state)
                if inject:
                    raise InterruptedError(
                        "injected after first persisted key transfer"
                    )
            del state["states"][source]
        graph = _graph(state["states"], graph["generation"], bundle)
    if _values(state) != original:
        raise ValueError("migration changed key values")
    persist(graph, state)
    return graph, state


def _dispatch_failure(graph, state, persist):
    """Fail after one routed state write, before an acknowledgement is returned."""
    index = _index(state)
    key = sorted(index)[0]
    owner = _route(index, key)
    state["states"][owner]["records"][key] += 1
    persist(graph, state)
    raise InterruptedError(f"injected dispatch failure after persisted write to {key}")


class _Observer:
    def __init__(self):
        self.start_wall, self.start_cpu = time.perf_counter(), time.process_time()
        self.spans, self.transferred = [], {stage: 0 for stage in STAGES}
        self.active_stage = None

    def run(self, stage, function):
        if self.active_stage is not None:
            raise RuntimeError("organization cost phases must not overlap")
        self.active_stage = stage
        wall, cpu = time.perf_counter(), time.process_time()
        status = "completed"
        try:
            return function()
        except Exception:
            status = "failed"
            raise
        finally:
            end = time.perf_counter()
            self.spans.append(
                {
                    "stage": stage,
                    "start": wall,
                    "end": end,
                    "wall_seconds": end - wall,
                    "cpu_seconds": time.process_time() - cpu,
                    "status": status,
                }
            )
            self.active_stage = None

    def close(self):
        elapsed, cpu = (
            time.perf_counter() - self.start_wall,
            time.process_time() - self.start_cpu,
        )
        self.spans.append(
            {
                "stage": "maintenance",
                "wall_seconds": max(
                    0, elapsed - sum(s["wall_seconds"] for s in self.spans)
                ),
                "cpu_seconds": max(0, cpu - sum(s["cpu_seconds"] for s in self.spans)),
                "status": "unclassified_envelope_gaps",
            }
        )

    def totals(self, stage):
        spans = [s for s in self.spans if s["stage"] == stage]
        return {
            "cpu_seconds": sum(s["cpu_seconds"] for s in spans),
            "accelerator_seconds": 0.0,
            "transferred_bytes": self.transferred[stage],
            "resident_byte_seconds": None,
        }


def _execute_arm(root, protocol, arm, before, initial, common_refs):
    run_id, pin = uuid.uuid4().hex, canonical_sha(protocol)
    prefix = "fixed" if arm == ARMS[0] else "dynamic"
    observer, trace, observations, trials = _Observer(), [], [], []
    artifacts = ArmArtifacts(root, protocol, arm, run_id, before, initial, common_refs)
    graph_path, state_path = (
        root / (prefix + "-working-graph.json"),
        root / (prefix + "-working-state.json"),
    )
    original_graph, original_state = _bytes(before), _bytes(initial)

    def persist(graph, state):
        graph_raw, state_raw = _bytes(graph), _bytes(state)
        _replace(graph_path, graph_raw)
        _replace(state_path, state_raw)
        observer.transferred[observer.active_stage] += len(graph_raw) + len(state_raw)

    observer.run("loading", lambda: persist(before, initial))
    recovery_events = []
    fault = protocol["recovery_policy"]["faults"][arm]
    try:
        if fault == "dispatch":
            observer.run(
                "recovery",
                lambda: _dispatch_failure(
                    copy.deepcopy(before), copy.deepcopy(initial), persist
                ),
            )
        else:
            observer.run(
                "recovery",
                lambda: _transition(
                    copy.deepcopy(before),
                    copy.deepcopy(initial),
                    protocol["operation"],
                    persist,
                    inject=True,
                ),
            )
    except InterruptedError as error:
        recovery_events.append("failure_observed")
        partial = {
            "graph": json.loads(graph_path.read_bytes()),
            "state": json.loads(state_path.read_bytes()),
            "error": str(error),
        }
        partial_ref = _write(root, prefix + "/failed-transition.json", partial)
        observer.run(
            "recovery",
            lambda: (
                _replace(graph_path, original_graph),
                _replace(state_path, original_state),
            ),
        )
        observer.transferred["recovery"] += len(original_graph) + len(original_state)
        recovery_events.append("rollback_completed")
    else:
        raise RuntimeError("failure injection was not reached")
    restored = (
        graph_path.read_bytes() == original_graph
        and state_path.read_bytes() == original_state
    )
    if not restored:
        raise RuntimeError("rollback did not restore original bytes")
    recovery_events.append("restored_state_readback")
    operation = "no_change" if arm == ARMS[0] else protocol["operation"]
    after, installed = observer.run(
        "migration",
        lambda: _transition(
            copy.deepcopy(before), copy.deepcopy(initial), operation, persist
        ),
    )
    index = observer.run("loading", lambda: _index(installed))
    if _values(installed) != _values(initial):
        raise RuntimeError("installed state differs from original key values")
    artifacts.installed(after, installed, operation, _transition)

    def event(kind, **fields):
        trace.append(
            {
                "sequence": len(trace),
                "type": kind,
                "run_id": run_id,
                "task_id": "successor-panel",
                "generation": after["generation"],
                "graph_sha256": canonical_sha(after),
                **fields,
            }
        )

    def send(source, target, payload):
        if [source, target] not in after["edges"]:
            raise ValueError("message outside installed graph")
        raw = _bytes(payload)
        observer.transferred["communication"] += len(raw)
        event(
            "message",
            **{
                "from": source,
                "to": target,
                "bytes": len(raw),
                "cost_event_id": "messages",
            },
        )
        return json.loads(raw)

    def apply_request(owner, request):
        event("dispatch", node_id=owner, state_owner="python-reference:" + owner)
        event("dispatch", node_id="recovery", state_owner="python-reference:recovery")
        ledger = installed["states"]["recovery"]["completed"]
        request_id, key = request["request_id"], request["key"]
        if request_id not in ledger:
            installed["states"][owner]["records"][key] += request["delta"]
            ledger[request_id] = installed["states"][owner]["records"][key]
        return ledger[request_id]

    for planned in protocol["roster"]:
        key, delta = planned["key"], planned["delta"]
        owner = observer.run("inference", lambda: _route(index, key))
        prior = installed["states"][owner]["records"][key]
        request = {"request_id": planned["task_id"], "key": key, "delta": delta}
        raw = observer.run("communication", lambda: _bytes(request))
        event(
            "encode",
            input_sha256=hashlib.sha256(raw).hexdigest(),
            cost_event_id="reencoding",
        )
        delivered = observer.run(
            "communication", lambda: send(owner, "recovery", json.loads(raw))
        )
        actual = observer.run("inference", lambda: apply_request(owner, delivered))
        retried = None
        if planned["panel"] == "rare_fault":
            delivered = observer.run(
                "communication", lambda: send(owner, "recovery", request)
            )
            retried = observer.run("recovery", lambda: apply_request(owner, delivered))
        if ["recovery", owner] in after["edges"]:
            acknowledged = observer.run(
                "communication", lambda: send("recovery", owner, {"result": actual})
            )
            if acknowledged["result"] != actual:
                raise RuntimeError("acknowledgement changed result")
        final = installed["states"][owner]["records"][key]
        score = observer.run(
            "evaluation",
            lambda: float(
                actual == prior + delta
                and final == prior + delta
                and (retried is None or retried == actual)
            ),
        )
        observer.run("maintenance", lambda: _index(installed))
        observed = {
            "task_id": planned["task_id"],
            "owner": owner,
            "key": key,
            "prior": prior,
            "delta": delta,
            "actual": actual,
            "retried": retried,
            "final": final,
            "score": score,
        }
        observations.append(observed)
        trials.append(
            {k: planned[k] for k in ("pair_id", "task_id", "seed")}
            | {
                "arm_id": arm,
                "run_id": run_id,
                "protocol_sha256": pin,
                "status": "completed",
                "score": score,
                "evidence_sha256": canonical_sha(observed),
            }
        )
    observer.close()
    recovery = {
        "original_job_id": run_id + ":" + fault + "-failure",
        "injected_failure": fault,
        "restored_graph": before,
        "restored_state": initial,
        "events": recovery_events,
        "restored_exact_bytes": restored,
        "failed_transition": partial_ref,
    }
    arm_data, receipt = artifacts.seal(
        observer, trace, trials, observations, recovery, installed
    )
    return (
        arm_data,
        receipt,
        {
            "key_values_preserved_at_install": True,
            "unique_key_owners": len(_index(installed)) == len(_values(initial)),
            "rollback_exact_bytes": restored,
            "injected_failure": fault,
            "completed_pairs": len(trials),
            "score_sum": sum(r["score"] for r in trials),
            "successor_dispatches": len([e for e in trace if e["type"] == "dispatch"]),
            "training_steps": 0,
        },
    )


def run_reference(output, operation):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    source = source_identity(__file__)
    protocol, graph, initial, common, inventory = prepare(
        root, operation, source, _route
    )
    pin, windows = canonical_sha(protocol), []
    for window in range(3):
        start, used, capacity = time.perf_counter(), [], []
        for sample in range(4):
            # Count actual loaded logical records; this is not a measured RAM limit.
            loaded = json.loads((root / common["before_state"]["path"]).read_bytes())
            used.append(len(_index(loaded)))
            capacity.append(12)
        windows.append(
            _write(
                root,
                f"window-{window}.json",
                {
                    "window_id": f"window-{window}",
                    "protocol_sha256": pin,
                    "start": start,
                    "end": time.perf_counter(),
                    "sample_ids": [f"window-{window}:load-{i}" for i in range(4)],
                    "samples": 4,
                    "value": statistics.mean(u / c for u, c in zip(used, capacity)),
                    "used": used,
                    "capacity": capacity,
                    "unit": "logical_records",
                    "capacity_policy": "synthetic predeclared 12-record logical capacity; not hardware saturation",
                },
            )
        )
    arms, receipts, engineering = {}, {}, {}
    for arm in ARMS:
        arms[arm], receipts[arm], engineering[arm] = _execute_arm(
            root, protocol, arm, graph, initial, common
        )
    evidence = {
        "schema": "hepta.org1.evidence.v1",
        "protocol_sha256": pin,
        "capability_inventory": inventory,
        "trigger_windows": windows,
        "arms": arms,
        "fixed_topology": receipts[ARMS[0]],
        "dynamic_topology": receipts[ARMS[1]],
    }
    _write(root, "EVIDENCE.json", evidence)
    report = review_organization(protocol, evidence, root, trusted_protocol_sha256=pin)
    _write(root, "REVIEW.json", report)
    _write(
        root,
        "ENGINEERING.json",
        {
            "schema": "hepta.org1.reference-execution.v1",
            "operation": operation,
            "arms": engineering,
            "source_sha256": source["sha256"],
            "source_files": source["files"],
            "scope": "actual Python state operations on synthetic tasks; not native Cell execution or learning",
            "limitations": [
                "No independently trusted observer",
                "No training or organization search",
                "Fixed dispatch fault and dynamic migration fault are separate demonstrations, not a shared physical fault distribution",
                "Two implementation files are bound; this is not a full dependency closure",
                "No measured resident-byte integral, energy or provider charges",
                "Receipt serialization after arm metering is not charged",
                "Logical capacity probe is not a hardware bottleneck",
                "Seeds label repeated deterministic panels, not independent training fits",
            ],
            "scientific_acceptance": "HOLD",
            "benefit_proven": False,
            "adoption_authorized": False,
        },
    )
    return {
        "operation": operation,
        "status": report["status"],
        "observed_pairs": report["observed_pairs"],
        "protocol_sha256": pin,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, required=True, help="New, absent directory"
    )
    parser.add_argument(
        "--operation", choices=("split", "merge", "rewire"), required=True
    )
    args = parser.parse_args()
    print(json.dumps(run_reference(args.output, args.operation)))
    return 0  # Successful reference execution is distinct from qualification.


if __name__ == "__main__":
    raise SystemExit(main())
