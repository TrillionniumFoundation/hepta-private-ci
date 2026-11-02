"""Full accepted-history MLP reference, with transparent append-only storage.

The V8 scheduler uses its CoreSnapshot plumbing for acceptance callbacks. Here
the snapshot is a 32-byte storage digest, never a learned recurrent state. The
reader receives every accepted 41-value observation record plus six slot masks.
"""

import argparse
import copy
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch
from torch import nn

from . import candidate as base


class HistoryModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.reader = nn.Sequential(nn.Linear(252, 64), nn.Tanh(), nn.Linear(64, 16)).double()

    def forward(self, x):
        triangle = torch.tril(x.new_ones((6, 6)))
        slots = x[:, None] * triangle[None, :, :, None]
        masks = triangle[None].expand(len(x), -1, -1)
        features = torch.cat((slots.flatten(2), masks), -1)
        return self.reader(features)


class AcceptedHistory:
    """A causal bounded log; the learned model has no recurrent hidden state."""

    def __init__(self, head, model_id):
        self.head, self.core_id = head, model_id
        self.events, self.rows, self.current = [], [], None

    def snapshot(self, content):
        encoded = json.dumps([content.fingerprint(), self.rows], separators=(",", ":"), allow_nan=False).encode()
        digest = hashlib.sha256(encoded).digest()
        return base.CoreSnapshot(self.core_id, content.fingerprint(), tuple(float(v) for v in digest))

    def initial(self, content):
        if self.current is not None:
            raise base.ContractError("A history holder belongs to one episode")
        self.current = self.snapshot(content)
        return self.current

    def accept(self, state, updated, observation, global_source_increment):
        if (state != self.current or observation.event_id != updated.accepted_event_ids[-1]
                or len(self.rows) >= 6 or global_source_increment < 0):
            raise base.ContractError("History append has stale identity, capacity or clock")
        row = base.cache_features(updated, self.head, global_source_increment).tolist()
        self.rows.append(row)
        self.current = self.snapshot(updated)
        self.events.append({"event_id": observation.event_id, "content_fingerprint": updated.fingerprint(),
                            "global_source_increment": global_source_increment,
                            "row": row, "digest": list(self.current.values)})
        return self.current

    def features(self, state, content):
        if state != self.current or state.content_fingerprint != content.fingerprint():
            raise base.ContractError("History readout requires the current accepted log")
        slots = np.zeros((6, 41), np.float64)
        slots[:len(self.rows)] = self.rows
        mask = np.arange(6) < len(self.rows)
        return np.r_[slots.ravel(), mask.astype(float)]


class HistoryForecast:
    # CORE here selects the scheduler's accept callback, not a neural core.
    kind = base.BackendKind.CORE

    def __init__(self, model, head, holder, model_id):
        self.model, self.head, self.holder, self.reader_id = model, head, holder, model_id

    def evaluate(self, content, state, plan):
        if not plan.requested_reads:
            return self.head.evaluate(content).calibrated_correctness
        levels = {m: int(content.level(m)) for m in base.Modality}
        for step in plan.steps:
            if hasattr(step, "modality"):
                levels[step.modality] = step.prefix_end
        x = torch.tensor(self.holder.features(state, content))[None]
        with torch.no_grad():
            p = self.model.reader(x).sigmoid()[0, base.LEVELS.index(
                (levels[base.Modality.AUDIO], levels[base.Modality.VIDEO]))].item()
        return base.CorrectnessValue(p, self.head.head_id)


def fit(seed, train, val, output):
    torch.manual_seed(seed)
    model = HistoryModel()
    optimizer = torch.optim.AdamW(model.parameters(), lr=.003, weight_decay=1e-3)
    tx, ty, tm, _ = train
    vx, vy, vm, _ = val
    history, best, selected, weights = [], float("inf"), 0, None
    began = time.process_time()
    for epoch in range(101):
        if epoch:
            optimizer.zero_grad(set_to_none=True)
            errors = nn.functional.binary_cross_entropy_with_logits(model(tx), ty, reduction="none")
            ((errors * tm).sum() / tm.sum()).backward()
            nn.utils.clip_grad_norm_(model.parameters(), 5)
            optimizer.step()
        with torch.no_grad():
            errors = nn.functional.binary_cross_entropy_with_logits(model(vx), vy, reduction="none")
            score = ((errors * vm).sum() / vm.sum()).item()
        history.append({"epoch": epoch, "validation_bce": score})
        if score < best:
            best, selected, weights = score, epoch, copy.deepcopy(model.state_dict())
    torch.save(model.state_dict(), output / f"history-{seed}-final.pt")
    model.load_state_dict(weights)
    path = output / f"history-{seed}-selected.pt"
    torch.save(weights, path)
    with torch.no_grad():
        before = model(tx[:1])
        for t in range(6):
            changed = tx[:1].clone()
            changed[:, t + 1:] = 1234.5
            assert torch.equal(model(changed)[:, t], before[:, t])
    base.write(output / f"history-{seed}-fit.json", {"history": history, "selected_epoch": selected,
        "parameters": sum(p.numel() for p in model.parameters()), "seed": seed,
        "selected_sha256": base.sha(path), "cpu_seconds_nested": time.process_time() - began,
        "future_slot_mutation_causality_checks": 6})
    return model.eval(), base.sha(path)


def sources():
    return {**base.source_hashes(), str(Path(__file__)): base.sha(Path(__file__))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    frozen_sources = sources()
    base.write(args.out / "PROTOCOL.json", {"source_sha256": frozen_sources,
        "scope": "Historical already-exposed AV development, full accepted-history ordinary MLP",
        "seeds": base.SEEDS, "epochs": 100, "selection": "minimum old-validation masked BCE",
        "input": "six chronological accepted 41-value observations plus six masks; future slots zero",
        "capacity": {"observation_scalars": 246, "slot_mask_scalars": 6, "snapshot_digest_bytes": 32},
        "state_semantics": "Transparent raw accepted-history log; no neural recurrence",
        "scheduler_backend_kind": "core only to receive every accepted observation callback",
        "same_recipe": "base candidate dataset, targets, order, AdamW, LR, epochs, selection and common controller",
        "family_tuned_strongest_qualification": False, "capacity_matched": False,
        "scientific_confirmation": False, "D_minus_B_measured": False,
        "torch": torch.__version__, "source_and_service_clock": "logical, not real device latency"})
    traces, rows = [], []
    for task in ("async_av", "av_binding"):
        task_out = args.out / task
        task_out.mkdir()
        head, _, _ = base.fit_development_adapters(task, base.legacy_data(task, "val"), task_out)
        train, val = base.dataset(task, "train", head), base.dataset(task, "val", head)
        base.write(task_out / "INPUTS.json", {"train": base.data_identity(train[3]),
            "validation": base.data_identity(val[3]), "head_checkpoint_sha256": head.checkpoint_sha256,
            "sources": sources()})
        models = [(seed, *fit(seed, train, val, task_out)) for seed in base.SEEDS]
        base.write(task_out / "FROZEN.json", {"unix": time.time(), "models": [
            {"seed": seed, "sha256": model_sha} for seed, _, model_sha in models]})
        data = base.legacy_data(task, "test")
        base.write(task_out / "HISTORICAL_TEST_INPUTS.json", base.data_identity(data))
        for seed, model, model_sha in models:
            for index, label in enumerate(base.labels_of(data)):
                for policy in ("fixed", "value"):
                    object_id = f"history-{task}-{index}-{seed}-{policy}"
                    holder = AcceptedHistory(head, model_sha[:32])
                    forecast = HistoryForecast(model, head, holder, holder.core_id)
                    result = base.run_episode(object_id, base.CacheBudget(65536), head, forecast, base.FixedServiceModel(),
                        base.PreparedPrefixService(*base.episode_arrays(data, index), object_id), lambda _: None,
                        clock=base.LogicalClock(), core=holder, horizon=6 if policy == "fixed" else 2,
                        fixed_plans=base.fixed_plans("common_full") if policy == "fixed" else None)
                    assert result["requested_observations"] == len(holder.rows)
                    assert all(e.get("status") not in ("failed", "rejected", "timed_out") for e in result["events"])
                    levels = {m: 0 for m in base.Modality}
                    for event in result["events"]:
                        if event.get("status") == "accepted":
                            _, modality, level = event["action"].split(":")
                            levels[base.Modality(modality)] = int(level)
                    expected = head.classify(base.populated_cache(data, index, levels[base.Modality.AUDIO], levels[base.Modality.VIDEO]))
                    assert np.array_equal(expected, result["output"]["probabilities"])
                    correct = result["output"]["predicted_class"] == int(label)
                    row = {"task": task, "index": index, "seed": seed, "family": "full_history", "policy": policy,
                        "actor": str(data["group_ids"][index]), "label": int(label), "correct": correct,
                        "requests": result["requested_observations"], "utility": float(correct - result["observation_fee"]
                        - result["latency_fee"] - result["deadline_penalty"]), "head_parity": True}
                    rows.append(row)
                    traces.append({**row, "execution": result, "history": holder.events,
                                   "nominal_history_and_mask_bytes": 252 * 8})
    with gzip.open(args.out / "TRACES.jsonl.gz", "xt") as stream:
        for trace in traces:
            stream.write(json.dumps(trace, allow_nan=False) + "\n")
    groups = []
    for task in ("async_av", "av_binding"):
        for policy in ("fixed", "value"):
            subset = [r for r in rows if r["task"] == task and r["policy"] == policy]
            groups.append({"task": task, "policy": policy, "runs": len(subset),
                "accuracy": float(np.mean([r["correct"] for r in subset])),
                "mean_utility": float(np.mean([r["utility"] for r in subset])),
                "mean_requests": float(np.mean([r["requests"] for r in subset]))})
    base.write(args.out / "SUMMARY.json", {"groups": groups, "rows": rows, "executions": len(rows),
        "source_unchanged": all(base.sha(Path(p)) == h for p, h in frozen_sources.items()),
        "scientific_confirmation": False, "D_minus_B_measured": False,
        "complete_process_family_peak_bytes": None, "energy_joules": None})


if __name__ == "__main__":
    main()
