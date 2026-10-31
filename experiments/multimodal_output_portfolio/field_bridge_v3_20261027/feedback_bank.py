"""Bounded offline 85-node output trees on registered runtime fit/select roles."""

import hashlib
import json
from pathlib import Path
import time

import numpy as np

from ..v6.data import make_batch
from ..v6.neural import parameter_hash
from .feedback_media import MediaWriter
from .feedback_task import public_event, revise, score, start, verifier_review
from .training_common import Journal, file_hash, object_hash, require, write_json


def depth_of(node):
    if type(node) is not int or node not in range(85):
        raise ValueError("Invalid canonical node")
    return 0 if node == 0 else 1 if node < 5 else 2 if node < 21 else 3


def plan_for(node):
    depth_of(node)
    actions = []
    while node:
        action = (node - 1) % 4 + 1
        actions.append(action)
        node = (node - 1) // 4
    return list(reversed(actions))


def batches(corpus, role, seed, protocol):
    p = protocol["runtime"]
    count = len(corpus.splits[role]) // 2
    width = p["batch_size"]
    for condition in p["conditions"]:
        for offset in range(0, count, width):
            n = min(width, count - offset)
            text = f"v3-batch:{role}:{seed}:{condition}:{offset}"
            batch_seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "little") % (2**63 - 1)
            batch = make_batch(corpus, role, n, batch_seed, corruption=condition, offset=offset)
            case_ids = tuple(f"{role}-{seed}-{condition}-{i:06d}" for i in range(offset, offset + n))
            yield condition, offset, case_ids, batch


def build_tree_batch(model, batch, observer, writer, journal, case_ids, role):
    require(role in ("runtime_fit", "runtime_select"), "Counterfactual trees are fit/select only")
    n = len(case_ids)
    events, values = np.empty((n, 21, 16)), np.empty((n, 85))
    nodes = [start(model, batch.observation, observer, writer, case_ids)]
    for node in range(85):
        delivered = nodes[node]
        require(delivered.depth == depth_of(node), "Tree indexing or depth mismatch")
        measured = score(delivered, batch.target, observer)
        values[:, node] = [row["net_utility"] for row in measured]
        packets = None
        if node < 21:
            if node:
                packets = verifier_review(delivered, batch.target)
            events[:, node] = public_event(delivered, packets)
        journal.append({"kind": "counterfactual_node_output", "role": role,
            "node": node, "plan": plan_for(node), "depth": delivered.depth,
            "case_ids": list(case_ids), "source_ids": batch.source_ids,
            "media": list(delivered.hard.receipts), "reward_scores": measured,
            "public_event": events[:, node].tolist() if node < 21 else None,
            "feedback": packets, "counterfactual_access_scope": "offline_registered_fit_or_selection"})
        if node < 21:
            for action in range(1, 5):
                require(len(nodes) == 4 * node + action, "Noncanonical tree construction order")
                nodes.append(revise(model, delivered, action, observer, writer))
    resources = {
        "encoder_examples": n, "encoder_batches": n,
        "transition_examples": 85 * n, "transition_batches": 85 * n,
        "decoder_examples": 85 * n, "decoder_batches": 85 * n,
        "public_feature_observer_digit_examples": 42 * n,
        "reward_observer_digit_examples": 170 * n,
        "simulated_feedback_packets": 20 * n,
        "media_logical_deliveries_read_back": 85 * n,
        "offline_terminal_targets": 85 * n,
    }
    return events, values, resources


def build_bank(model, corpus, observer, seed, profile, role, protocol, out, metadata):
    require(role in ("runtime_fit", "runtime_select"), "Counterfactual bank role forbidden")
    require(set(corpus.splits) <= {"runtime_fit", "runtime_select"}, "Counterfactual runner loaded forbidden roles")
    expected = protocol["runtime"]["fit_pairs" if role == "runtime_fit" else "selection_pairs"]
    require(len(corpus.splits[role]) == 2 * expected, "Runtime bank size differs from registration")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    before, observer_before = parameter_hash(model), parameter_hash(observer)
    events, values, identities, cases, conditions, resources = [], [], [], [], [], {}
    with MediaWriter(out / "media.h3m") as writer, Journal(out / "evidence.jsonl.gz") as journal:
        for condition, offset, case_ids, batch in batches(corpus, role, seed, protocol):
            x, y, cost = build_tree_batch(model, batch, observer, writer, journal, case_ids, role)
            events.append(x)
            values.append(y)
            identities.extend(batch.source_ids)
            cases.extend(case_ids)
            conditions.extend([condition] * len(case_ids))
            for key, amount in cost.items():
                resources[key] = resources.get(key, 0) + amount
            print(f"runtime bank seed={seed} profile={profile} role={role} condition={condition} offset={offset} complete", flush=True)
    require(parameter_hash(model) == before and parameter_hash(observer) == observer_before,
            "Offline runtime tree generation mutated frozen models")
    resources.update(physical_media_records=writer.physical_records, physical_media_bytes=writer.bytes)
    x, y = np.concatenate(events), np.concatenate(values)
    require(x.shape == (4 * expected, 21, 16) and y.shape == (4 * expected, 85), "Incomplete runtime bank")
    require(np.isfinite(x).all() and np.isfinite(y).all() and abs(x).max() <= 1 + 1e-7,
            "Unbounded/nonfinite runtime bank")
    with (out / "bank.npz").open("xb") as stream:
        np.savez_compressed(stream, events=x, terminal_values=y,
            source_ids=np.asarray(identities, dtype=str), case_ids=np.asarray(cases, dtype=str),
            conditions=np.asarray(conditions, dtype=str))
    record = {"schema": "hepta.field-bridge.v3.feedback-tree-bank.1", "role": role,
        "seed": seed, "profile": profile, "rows": len(x), "pairs": expected,
        "model_parameter_sha256": before, "observer_parameter_sha256": observer_before,
        "metadata": metadata, "source_manifest_sha256": corpus.manifest["manifest_sha256"],
        "resources": resources, "terminal_value": "actual hard utility minus .002*(1+node_depth)",
        "all85_open_loop_plans": [plan_for(i) for i in range(85)],
        "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
        "files": {name: file_hash(out / name) for name in ("bank.npz", "media.h3m", "evidence.jsonl.gz")}}
    write_json(out / "COMPLETE.json", record)
    return record


def load_bank(root, role):
    root = Path(root)
    metadata = json.loads((root / "COMPLETE.json").read_text())
    require(metadata["role"] == role and role in ("runtime_fit", "runtime_select"), "Wrong bank role")
    for name, digest in metadata["files"].items():
        require(file_hash(root / name) == digest, f"Runtime bank evidence changed: {name}")
    with np.load(root / "bank.npz", allow_pickle=False) as arrays:
        result = {name: arrays[name].copy() for name in arrays.files}
    result.update(role=role, metadata=metadata)
    return result
