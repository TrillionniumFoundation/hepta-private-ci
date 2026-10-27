"""Actual selected-path deployment; no unchosen output tree is evaluated."""

import json
from pathlib import Path
import time

import numpy as np

from ..v6.data import Target
from ..v6.neural import parameter_hash
from .feedback_bank import batches, plan_for
from .feedback_media import MediaWriter
from .feedback_task import (merge_delivered, public_event, revise, score, start,
                            subset_delivered, verifier_review)
from .runtime_controller import select
from .training_common import Journal, file_hash, object_hash, require, write_json


def target_subset(target, indices):
    return Target(*(getattr(target, name)[indices] for name in ("pixels", "text_tokens", "labels")))


def rollout_batch(model, batch, observers, controller, bridge, writer, journal,
                  case_ids, role, arm):
    """The selector receives only a causal public history and its own state."""
    n = len(case_ids)
    native = controller.get("representation") in ("native", "reset_native")
    fixed = controller.get("kind") == "fixed"
    if fixed:
        require(controller["actions"] == plan_for(controller["node"]), "Fixed plan does not match its canonical node")
    require(fixed or "representation" in controller, "Missing frozen policy")
    controller_sha = object_hash(controller)
    sessions = [bridge.open(case) for case in case_ids] if native else []
    costs = {"encoder_examples": n, "encoder_batches": n,
        "transition_examples": n, "transition_batches": n,
        "decoder_examples": n, "decoder_batches": n,
        "public_feature_observer_digit_examples": 2 * n,
        "media_logical_deliveries_read_back": n, "simulated_feedback_packets": 0,
        "native_tick_calls": 0, "selection_rows": 0, "selection_batches": 0,
        "select_wall_ns": 0, "select_python_cpu_ns": 0, "native_ns": 0,
        "unchosen_continuations_executed": 0}
    paths, media, decisions, feedbacks = [[] for _ in range(n)], [[] for _ in range(n)], [[] for _ in range(n)], [[] for _ in range(n)]
    finished, final_nodes = {}, np.zeros(n, dtype=np.int64)
    active = np.arange(n)
    delivered = start(model, batch.observation, observers["reward"], writer, case_ids)
    history = public_event(delivered)[:, None]
    for i, receipt in enumerate(delivered.hard.receipts):
        media[i].append(receipt)
    journal.append({"kind": "initial_delivery", "role": role, "arm": arm,
        "case_ids": list(case_ids), "media": list(delivered.hard.receipts), "public_events": history[:, 0].tolist()})

    def finish(current, indices):
        local = subset_delivered(delivered, indices)
        private = target_subset(batch.target, current)
        observed = {name: score(local, private, observer) for name, observer in observers.items()}
        for name in observers:
            key = name + "_outcome_observer_digit_examples"
            costs[key] = costs.get(key, 0) + 2 * len(current)
        for j, global_index in enumerate(current):
            finished[int(global_index)] = {"case_id": case_ids[global_index], "source_ids": list(batch.source_ids[global_index]),
                "role": role, "arm": arm, "actions": paths[global_index], "terminal_node": int(final_nodes[global_index]),
                "depth": local.depth, "media": media[global_index], "decisions": decisions[global_index],
                "feedback": feedbacks[global_index], "scores": {name: rows[j] for name, rows in observed.items()},
                "controller_sha256": controller_sha, "unchosen_continuations_executed": 0}
            if native:
                sessions[global_index].close()

    try:
        for round_index in range(3):
            require(delivered.depth == round_index and len(history) == len(active), "Active episode clock mismatch")
            if fixed:
                started, cpu = time.perf_counter_ns(), time.process_time_ns()
                action = controller["actions"][round_index] if round_index < len(controller["actions"]) else 0
                actions = np.full(len(active), action, dtype=np.int64)
                selection = {"action_indices": actions.tolist(), "round": round_index,
                    "representation": "fixed", "target_accesses": 0, "future_events_accessed": 0,
                    "native_tick_calls": 0, "native_ns": 0, "controller_sha256": controller_sha,
                    "select_wall_ns": time.perf_counter_ns() - started,
                    "select_python_cpu_ns": time.process_time_ns() - cpu}
            else:
                actions, selection = select(controller, history, bridge=bridge,
                    sessions=[sessions[i] for i in active] if native else None)
            costs["selection_rows"] += len(active)
            costs["selection_batches"] += 1
            for name in ("native_tick_calls", "native_ns", "select_wall_ns", "select_python_cpu_ns"):
                costs[name] += selection[name]
            committed_time = time.monotonic_ns()
            commitment = journal.append({"kind": "selected_actions_before_execution", "role": role, "arm": arm,
                "case_ids": [case_ids[i] for i in active], "round": round_index,
                "public_history": history.tolist(), "selection": selection,
                "delivered_record_sha256": [r["record_sha256"] for r in delivered.hard.receipts],
                "controller_sha256": controller_sha})
            for i, global_index in enumerate(active):
                paths[global_index].append(int(actions[i]))
                decisions[global_index].append(commitment)
            stopped = np.flatnonzero(actions == 0)
            if len(stopped):
                finish(active[stopped], stopped)
            continuing = np.flatnonzero(actions != 0)
            if not len(continuing):
                break
            next_active = active[continuing]
            groups, positions, packets_by_position = [], [], {}
            for action in (1, 2, 3, 4):
                positions_in_live = np.flatnonzero(actions[continuing] == action)
                if not len(positions_in_live):
                    continue
                indices = continuing[positions_in_live]
                parent = subset_delivered(delivered, indices)
                child = revise(model, parent, action, observers["reward"], writer)
                require(all(r["readback_monotonic_ns"] >= committed_time for r in child.hard.receipts),
                        "A selected revision was delivered before its action commitment")
                for i, global_index in enumerate(active[indices]):
                    final_nodes[global_index] = 4 * final_nodes[global_index] + action
                    media[global_index].append(child.hard.receipts[i])
                costs["transition_examples"] += len(indices)
                costs["transition_batches"] += len(indices)
                costs["decoder_examples"] += len(indices)
                costs["decoder_batches"] += len(indices)
                costs["media_logical_deliveries_read_back"] += len(indices)
                packets = None
                if child.depth < 3:
                    packets = verifier_review(child, target_subset(batch.target, active[indices]))
                    costs["simulated_feedback_packets"] += len(indices)
                    costs["public_feature_observer_digit_examples"] += 2 * len(indices)
                    for position, packet in zip(positions_in_live, packets, strict=True):
                        packets_by_position[int(position)] = packet
                journal.append({"kind": "selected_revision_delivery", "role": role, "arm": arm,
                    "decision_sha256": commitment, "depth": child.depth, "action": action,
                    "case_ids": list(child.case_ids), "media": list(child.hard.receipts), "feedback": packets,
                    "future_or_unchosen_branches_executed": 0})
                groups.append(child)
                positions.append(positions_in_live)
            delivered = merge_delivered(groups, positions)
            active = next_active
            require(delivered.case_ids == tuple(case_ids[i] for i in active), "Live source identity reorder")
            if delivered.depth == 3:
                finish(active, np.arange(len(active)))
                break
            packets = [packets_by_position[i] for i in range(len(active))]
            for i, global_index in enumerate(active):
                feedbacks[global_index].append(packets[i])
            history = np.concatenate((history[continuing], public_event(delivered, packets)[:, None]), axis=1)
        require(set(finished) == set(range(n)), "Incomplete selected-path episodes")
        rows = [finished[i] for i in range(n)]
        require(costs["decoder_examples"] <= 4 * n and costs["native_tick_calls"] <= 6 * n,
                "Deterministic registered episode work ceiling exceeded")
        return rows, costs
    finally:
        for session in sessions:
            if not session.closed:
                session.close()


def run_profile(model, corpus, observers, policies, bridge, seed, profile, role, protocol, out, metadata):
    require(role in ("runtime_audit", "primary", "retention"), "Selected execution role forbidden")
    require(set(corpus.splits) == {role}, "Selected execution loaded other source roles")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    fingerprint = parameter_hash(model)
    observer_fingerprints = {k: parameter_hash(v) for k, v in observers.items()}
    started, cpu, resources = time.perf_counter_ns(), time.process_time_ns(), {}
    phase_protocol = protocol
    if role == "retention":
        phase_protocol = {**protocol, "runtime": {**protocol["runtime"], "conditions": ["clean"]}}
    count = 0
    with MediaWriter(out / "media.h3m") as writer, Journal(out / "events.jsonl.gz") as journal, Journal(out / "rows.jsonl.gz") as rows_stream:
        for condition, offset, case_ids, batch in batches(corpus, role, seed, phase_protocol):
            for arm, controller in policies.items():
                rows, costs = rollout_batch(model, batch, observers, controller, bridge, writer, journal, case_ids, role, arm)
                for i, row in enumerate(rows):
                    rows_stream.append({**row, "seed": seed, "profile": profile, "condition": condition, "pair_index": offset + i})
                    count += 1
                for key, value in costs.items():
                    resources[key] = resources.get(key, 0) + value
            print(f"selected seed={seed} profile={profile} role={role} condition={condition} offset={offset} complete", flush=True)
    require(parameter_hash(model) == fingerprint and all(parameter_hash(v) == observer_fingerprints[k] for k, v in observers.items()),
            "Selected execution mutated frozen parameters")
    resources.update(physical_media_records=writer.physical_records, physical_media_bytes=writer.bytes)
    expected = (len(corpus.splits[role]) // 2) * len(phase_protocol["runtime"]["conditions"]) * len(policies)
    require(count == expected, "Incomplete selected episode count")
    record = {"schema": "hepta.field-bridge.v3.selected-feedback-complete.1", "role": role,
        "seed": seed, "profile": profile, "arms": list(policies), "episodes": count,
        "resources": resources, "metadata": metadata, "model_parameter_sha256": fingerprint,
        "observer_parameter_sha256": observer_fingerprints, "source_manifest_sha256": corpus.manifest["manifest_sha256"],
        "controller_sha256": {k: object_hash(v) for k, v in policies.items()},
        "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
        "files": {name: file_hash(out / name) for name in ("media.h3m", "events.jsonl.gz", "rows.jsonl.gz")},
        "unchosen_continuations_executed": 0, "authority": "DENY_ALL", "native_owner_integration": False}
    write_json(out / "COMPLETE.json", record)
    return record
