"""All four guarded actions followed by the actual deployed ordinary baseline."""

import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

from ..multimodal_output_portfolio.field_bridge_v3_20261027 import learning
from ..multimodal_output_portfolio.field_bridge_v3_20261027.training_features import measure_state
from .branching import BASELINES, StudyAdapter, codec, dynamics_identity, full_current_feature, state_difference, timed
from .heads import fit_head, head_metadata, history_feature


def write_json(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def initialize(context, binding, schedule_id, kind):
    model = learning.make_model(context.original, context.seed, context.protocol)
    optimizer = learning.new_optimizer(model, context.protocol)
    learning.hard_panel(model, context.probe[:1], {"reward": context.observers["reward"]}, context.action,
                        context.protocol, context.costs, "cold_cache_initialization")
    adapter = StudyAdapter(context, model, optimizer, binding)
    adapter.schedule_id, adapter.path_kind = schedule_id, kind
    return adapter


def measure(adapter):
    before, digest = adapter.seal()
    state = codec.loads(before, digest, len(before))
    context = adapter.context
    field, unused, receipt = timed(context.costs, "feature_measurement", lambda: measure_state(
        context, adapter.model, adapter.optimizer, adapter.clock, adapter.schedule_id))
    after, unused_digest = adapter.seal()
    if before != after:
        raise ValueError("Features changed full state or incoming gradient/RNG")
    features = {"field12": np.asarray(field[:12]), "full_current_state": full_current_feature(state, field[:12]),
                "history6": history_feature(adapter.history, field[:12])}
    return before, digest, state, features, receipt


def append_history(adapter, feature, action, receipt):
    adapter.history.append({"field": np.asarray(feature).tolist(), "action": int(action),
                            "accepted": bool(receipt["accepted"]), "scheduled_microsteps": 48})


def build_bank(context, binding, out, check_budget):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    baseline, records = BASELINES[context.seed], []
    features = {name: [] for name in ("field12", "full_current_state", "history6")}
    with gzip.open(out / "trace.jsonl.gz", "xt") as trace:
        for schedule_index, schedule_id in enumerate(range(6000, 6004)):
            for kind in ("baseline", "balanced"):
                adapter = initialize(context, binding, schedule_id, kind)
                for decision in range(6):
                    check_budget()
                    step = adapter.clock
                    raw, digest, parent, measured, feature_receipt = measure(adapter)
                    stem = f"schedule-{schedule_id}-{kind}-step-{step}"
                    (out / (stem + ".state")).write_bytes(raw)
                    chosen = baseline if kind == "baseline" else (schedule_index + decision) % 4
                    values, branches, first_states = [], [], {}
                    for action in range(4):
                        adapter.restore(raw, digest)
                        before_cost = context.costs.snapshot()
                        first_receipt = adapter.transition(action)
                        first_states[action] = adapter.capture()
                        tail_receipts = [first_receipt]
                        while adapter.clock < 288:
                            check_budget()
                            tail_receipts.append(adapter.transition(baseline))
                        terminal = adapter.capture()
                        score = timed(context.costs, "bank_label_scoring", lambda: learning.hard_panel(
                            adapter.model, context.probe, {"reward": context.observers["reward"]}, context.action,
                            context.protocol, context.costs, "aligned_terminal_label", retain=True))
                        value = score["means"]["reward"]
                        values.append(value)
                        learning.save_hard(out / f"{stem}-action-{action}.npz", score)
                        branch = {"action": action, "value": value, "first": dynamics_identity(first_states[action]),
                                  "terminal": dynamics_identity(terminal), "accepted": first_receipt["accepted"],
                                  "costs": context.costs.since(before_cost)}
                        branches.append(branch)
                        trace.write(json.dumps({"parent": digest, "schedule_id": schedule_id, "prefix": kind,
                                                "step": step, "action": action, "transactions": tail_receipts,
                                                "branch": branch}, allow_nan=False) + "\n")
                        trace.flush()
                    differences = {str(a): state_difference(first_states[a], first_states[baseline]) for a in range(4)}
                    adapter.restore(raw, digest)
                    actual = adapter.transition(chosen)
                    if dynamics_identity(adapter.capture()) != dynamics_identity(first_states[chosen]):
                        raise ValueError("Selected prefix failed exact independent replay")
                    append_history(adapter, measured["field12"], chosen, actual)
                    for mode, vector in measured.items():
                        features[mode].append(vector)
                    records.append({"seed": context.seed, "schedule_id": schedule_id, "prefix": kind,
                                    "step": step, "parent_sha256": digest, "parent_bytes": len(raw),
                                    "action_values": values, "advantages": (np.asarray(values) - values[baseline]).tolist(),
                                    "baseline": baseline, "selected_prefix_action": chosen, "branches": branches,
                                    "first_legal_successor_differences": differences, "feature_receipt": feature_receipt,
                                    "prefix_replay_equal": True})
                    print(json.dumps({"stage": "A_bank", "seed": context.seed, "schedule": schedule_id,
                                      "prefix": kind, "step": step, "rows": len(records)}), flush=True)
    if len(records) != 48:
        raise ValueError("Incomplete aligned bank")
    advantages = np.asarray([r["advantages"] for r in records])
    fit_mask = np.asarray([r["schedule_id"] != 6003 for r in records])
    heads = {}
    for mode, vectors in features.items():
        array = np.asarray(vectors)
        with (out / (mode + "-bank.npz")).open("xb") as stream:
            np.savez_compressed(stream, features=array, advantages=advantages, fit_mask=fit_mask)
        heads[mode] = timed(context.costs, "head_fit", lambda: fit_head(array, advantages, fit_mask, ~fit_mask, baseline))
        head = heads[mode]
        metadata = head_metadata(head)
        np.savez_compressed(out / (mode + "-head.npz"), **{k: v for k, v in head.items() if isinstance(v, np.ndarray)},
                            metadata_json=np.asarray(json.dumps(metadata)))
    result = {"complete": True, "seed": context.seed, "records": records,
              "heads": {mode: head_metadata(head) for mode, head in heads.items()}, "costs": context.costs.snapshot(),
              "label_reference": "first action then baseline; same guard, clock, budget and paired tape",
              "certificate": False}
    write_json(out / "BANK.json", result)
    return heads, result


def load_heads(bank_directory):
    heads = {}
    for mode in ("field12", "full_current_state", "history6"):
        with np.load(Path(bank_directory) / (mode + "-head.npz"), allow_pickle=False) as saved:
            heads[mode] = {**json.loads(saved["metadata_json"].item()),
                           **{k: saved[k].copy() for k in saved.files if k != "metadata_json"}}
    return heads
