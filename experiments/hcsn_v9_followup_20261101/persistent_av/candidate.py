"""Historical AV development: persistent ordinary states and common-head control.

No analytic AV observation law is introduced. The original four-cell experiment
therefore remains incomplete; these are three ordinary developmental references.
"""

import argparse
import copy
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import sys
import time

import numpy as np
import torch
from torch import nn

from experiments.hcsn_v7_support_20261101.content_interface.content_interface import (
    BackendKind, CacheBudget, ContractError, CoreSnapshot, CorrectnessValue, Modality,
)
from experiments.hcsn_v8_execution_20261101.frontend.replay import (
    episode_arrays, legacy_data, populated_cache,
)
from experiments.hcsn_v8_execution_20261101.scheduler.execution import LogicalClock, run_episode
from experiments.hcsn_v8_execution_20261101.scheduler.historical_probe import (
    FixedServiceModel, fit_development_adapters, fixed_plans,
)
from experiments.hcsn_v8_execution_20261101.scheduler.historical_service import PreparedPrefixService
from experiments.hcsn_causal_execution_v3.av_probe import labels_of


HERE = Path(__file__).resolve().parent
LEVELS = tuple(itertools.product(range(4), repeat=2))
FAMILIES = ("direct", "gru", "ssm")
SEEDS = (91101, 91103)


def source_hashes():
    modules = [sys.modules[name] for name in sys.modules if name.startswith("experiments.")]
    paths = {Path(module.__file__) for module in modules if getattr(module, "__file__", None)}
    paths.add(Path(__file__))
    return {str(p): sha(p) for p in sorted(paths) if p.suffix == ".py"}


def data_identity(data):
    return {"array_sha256": data["metadata"]["array_sha256"],
            "source_ids": data["ids"].astype(str).tolist(),
            "content_sha256": hashlib.sha256(np.ascontiguousarray(data["x"]).tobytes()).hexdigest()}


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cache_features(content, head, increment):
    """Current common-cache content, never future data, object IDs or labels."""
    vectors = [np.zeros(16) if content.observation(m) is None
               else np.asarray(content.observation(m).aligned) for m in Modality]
    p = np.zeros(6)
    current = head.classify(content)
    p[:len(current)] = current
    return np.r_[*vectors, p, content.level(Modality.AUDIO) / 3,
                 content.level(Modality.VIDEO) / 3, increment].astype(np.float64)


class Model(nn.Module):
    def __init__(self, family):
        super().__init__()
        self.family = family
        if family == "gru":
            self.update = nn.GRUCell(41, 32)
        elif family == "ssm":
            self.rate, self.gain, self.drive = (nn.Linear(41, 32) for _ in range(3))
        width = 41 if family == "direct" else 73
        self.reader = nn.Sequential(nn.Linear(width, 64), nn.Tanh(), nn.Linear(64, 16))
        self.double()

    def step(self, x, state):
        if self.family == "direct":
            return state
        if self.family == "gru":
            return self.update(x, state)
        decay = torch.exp(-nn.functional.softplus(self.rate(x)) * x[:, -1:])
        gain = self.gain(x).sigmoid()
        return (1 - gain) * decay * state + gain * self.drive(x).tanh()

    def predict(self, x, state):
        x = torch.cat((x[:, :-1], torch.zeros_like(x[:, -1:])), -1)
        return self.reader(x if self.family == "direct" else torch.cat((x, state), -1))

    def forward(self, x):
        state = x.new_zeros((len(x), 32))
        logits = []
        for index in range(x.shape[1]):
            state = self.step(x[:, index], state)
            logits.append(self.predict(x[:, index], state))
        return torch.stack(logits, 1)


class PersistentCore:
    def __init__(self, model, head, model_id):
        self.model, self.head, self.core_id = model, head, model_id
        self.updates = []

    def initial(self, content):
        return CoreSnapshot(self.core_id, content.fingerprint(), (0.0,) * 32)

    def accept(self, state, updated, observation, global_source_increment):
        if state.core_id != self.core_id or observation.event_id != updated.accepted_event_ids[-1]:
            raise ContractError("Core update identity mismatch")
        x = torch.tensor(cache_features(updated, self.head, global_source_increment))[None]
        previous = torch.tensor(state.values, dtype=torch.float64)[None]
        with torch.no_grad():
            value = self.model.step(x, previous)[0].numpy()
        self.updates.append({"event": observation.event_id, "global_source_increment": global_source_increment,
                             "before": list(state.values), "after": value.tolist(),
                             "content_fingerprint": updated.fingerprint()})
        return CoreSnapshot(self.core_id, updated.fingerprint(), tuple(value))


class Forecast:
    def __init__(self, model, head, model_id):
        self.model, self.head = model, head
        self.kind = BackendKind.DIRECT_HISTORY if model.family == "direct" else BackendKind.CORE
        self.reader_id = model_id

    def evaluate(self, content, state, plan):
        if not plan.requested_reads:
            return self.head.evaluate(content).calibrated_correctness
        if self.kind == BackendKind.CORE and (state.core_id != self.reader_id
                or state.content_fingerprint != content.fingerprint()):
            raise ContractError("Forecast state is stale or belongs to another model")
        levels = {m: int(content.level(m)) for m in Modality}
        for step in plan.steps:
            if hasattr(step, "modality"):
                levels[step.modality] = step.prefix_end
        # dt is used in observation assimilation only. Current cache readout is
        # time-independent, like the common head, and future features are unseen.
        x = torch.tensor(cache_features(content, self.head, 0.0))[None]
        h = torch.zeros((1, 32), dtype=torch.float64) if state is None else torch.tensor(
            state.values, dtype=torch.float64)[None]
        with torch.no_grad():
            p = self.model.predict(x, h).sigmoid()[0, LEVELS.index(
                (levels[Modality.AUDIO], levels[Modality.VIDEO]))].item()
        return CorrectnessValue(p, self.head.head_id)


def schedules():
    result = []
    for audio_positions in itertools.combinations(range(5), 2):
        result.append((Modality.AUDIO,) + tuple(Modality.AUDIO if i in audio_positions
                                              else Modality.VIDEO for i in range(5)))
    return result


def dataset(task, split, head):
    """Every legal full schedule after mandatory A1; rows cluster by recording."""
    data = legacy_data(task, split)
    labels = labels_of(data)
    xs, ys, masks = [], [], []
    for index, label in enumerate(labels):
        caches = {level: populated_cache(data, index, *level) for level in LEVELS}
        correct = np.array([head.classify(caches[level]).argmax() == label for level in LEVELS], float)
        for schedule in schedules():
            a, v, previous = 0, 0, 0
            seq, mask = [], []
            for modality in schedule:
                a += modality == Modality.AUDIO
                v += modality == Modality.VIDEO
                level = max(a, v)
                seq.append(cache_features(caches[a, v], head, float(level - previous)))
                mask.append([ga >= a and gv >= v and (ga, gv) != (a, v) for ga, gv in LEVELS])
                previous = level
            xs.append(seq)
            ys.append(np.tile(correct, (6, 1)))
            masks.append(mask)
    return (torch.tensor(np.asarray(xs)), torch.tensor(np.asarray(ys)),
            torch.tensor(np.asarray(masks), dtype=torch.float64), data)


def fit(family, seed, train, val, output):
    torch.manual_seed(seed)
    model = Model(family)
    optimizer = torch.optim.AdamW(model.parameters(), lr=.003, weight_decay=1e-3)
    tx, ty, tm, _ = train
    vx, vy, vm, _ = val
    history, best, selected, weights = [], float("inf"), 0, None
    started = time.process_time()
    for epoch in range(101):
        if epoch:
            optimizer.zero_grad(set_to_none=True)
            errors = nn.functional.binary_cross_entropy_with_logits(model(tx), ty, reduction="none")
            loss = (errors * tm).sum() / tm.sum()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 5)
            optimizer.step()
        with torch.no_grad():
            errors = nn.functional.binary_cross_entropy_with_logits(model(vx), vy, reduction="none")
            score = ((errors * vm).sum() / vm.sum()).item()
        history.append({"epoch": epoch, "validation_bce": score})
        if score < best:
            best, selected, weights = score, epoch, copy.deepcopy(model.state_dict())
    torch.save(model.state_dict(), output / f"{family}-{seed}-final.pt")
    model.load_state_dict(weights)
    path = output / f"{family}-{seed}-selected.pt"
    torch.save(weights, path)
    write(output / f"{family}-{seed}-fit.json", {"history": history, "selected_epoch": selected,
          "parameters": sum(p.numel() for p in model.parameters()), "seed": seed,
          "cpu_seconds_nested": time.process_time() - started, "selected_sha256": sha(path),
          "scope": "Fixed recipe development fit, no per-family tuning or strongest-reference qualification"})
    return model.eval(), sha(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    source = source_hashes()
    write(args.out / "PROTOCOL.json", {"scope": "Historical exposed recordings, developmental persistent ordinary controls",
          "source_sha256": source, "seeds": SEEDS, "families": FAMILIES, "epochs": 100,
          "selection": "lowest historical-validation BCE; retain final and selected weights",
          "tasks": ["async_av", "av_binding"], "test_role": "previously exposed historical replay",
          "training_sequences_per_object": 10, "state_scalars": 32,
          "policy_pair": ["fixed common-full", "same task-value controller"],
          "analytic_av_law_defined": False, "four_cell_complete": False,
          "strong_reference_qualified": False, "scientific_confirmation": False,
          "torch": torch.__version__, "python": sys.executable,
          "timing": "Logical source/service clock, actual CPU is enclosing worker receipt",
          "raw_media_feature_preparation_included": False})
    rows, traces = [], []
    for task in ("async_av", "av_binding"):
        task_out = args.out / task
        task_out.mkdir(exist_ok=False)
        head, _, _ = fit_development_adapters(task, legacy_data(task, "val"), task_out)
        train, val = dataset(task, "train", head), dataset(task, "val", head)
        write(task_out / "INPUTS.json", {"train": data_identity(train[3]), "validation": data_identity(val[3]),
              "head_checkpoint_sha256": head.checkpoint_sha256, "sources": source_hashes()})
        np.savez_compressed(task_out / "training.npz", x=train[0].numpy(), y=train[1].numpy(), mask=train[2].numpy())
        np.savez_compressed(task_out / "validation.npz", x=val[0].numpy(), y=val[1].numpy(), mask=val[2].numpy())
        fitted = []
        for seed in SEEDS:
            for family in FAMILIES:
                model, model_sha = fit(family, seed, train, val, task_out)
                fitted.append((seed, family, model, model_sha))
        # Freeze every selected model before opening the historical test labels.
        write(args.out / f"{task}-FROZEN.json", {"models": [
              {"seed": s, "family": f, "sha256": h} for s, f, _, h in fitted], "unix": time.time()})
        data = legacy_data(task, "test")
        write(task_out / "HISTORICAL_TEST_INPUTS.json", data_identity(data))
        labels = labels_of(data)
        for seed, family, model, model_sha in fitted:
            forecast = Forecast(model, head, model_sha[:32])
            for index, label in enumerate(labels):
                for policy in ("fixed", "value"):
                    core = None if family == "direct" else PersistentCore(model, head, forecast.reader_id)
                    object_id = f"v9-{task}-{index}-{seed}-{family}-{policy}"
                    result = run_episode(object_id, CacheBudget(65536), head, forecast, FixedServiceModel(),
                        PreparedPrefixService(*episode_arrays(data, index), object_id), lambda _: None,
                        clock=LogicalClock(), core=core, horizon=6 if policy == "fixed" else 2,
                        fixed_plans=fixed_plans("common_full") if policy == "fixed" else None)
                    levels = {m: 0 for m in Modality}
                    for event in result["events"]:
                        if event.get("status") == "accepted":
                            _, modality, level = event["action"].split(":")
                            levels[Modality(modality)] = int(level)
                    expected = head.classify(populated_cache(data, index, levels[Modality.AUDIO], levels[Modality.VIDEO]))
                    parity = np.array_equal(expected, result["output"]["probabilities"])
                    if not parity or any(e.get("status") in ("failed", "rejected", "timed_out") for e in result["events"]):
                        raise AssertionError("Historical execution parity or acceptance failure")
                    correct = result["output"]["predicted_class"] == int(label)
                    row = {"task": task, "index": index, "seed": seed, "family": family, "policy": policy,
                        "actor": str(data["group_ids"][index]), "label": int(label), "correct": correct,
                        "requests": result["requested_observations"], "utility": float(correct - result["observation_fee"]
                        - result["latency_fee"] - result["deadline_penalty"]), "head_parity": bool(parity)}
                    rows.append(row)
                    traces.append({**row, "execution": result, "core_updates": [] if core is None else core.updates})
    with gzip.open(args.out / "TRACES.jsonl.gz", "xt") as stream:
        for trace in traces:
            stream.write(json.dumps(trace, allow_nan=False) + "\n")
    groups = []
    for task, family, policy in itertools.product(("async_av", "av_binding"), FAMILIES, ("fixed", "value")):
        subset = [r for r in rows if (r["task"], r["family"], r["policy"]) == (task, family, policy)]
        groups.append({"task": task, "family": family, "policy": policy, "runs": len(subset),
            "accuracy": float(np.mean([r["correct"] for r in subset])),
            "mean_utility": float(np.mean([r["utility"] for r in subset])),
            "mean_requests": float(np.mean([r["requests"] for r in subset]))})
    write(args.out / "SUMMARY.json", {"groups": groups, "rows": rows, "executions": len(rows),
        "all_common_head_parity": all(r["head_parity"] for r in rows),
        "source_unchanged": all(sha(Path(p)) == h for p, h in source.items()),
        "D_minus_B_measured": False, "analytic_AV_fitted": False, "four_cell_complete": False,
        "scientific_confirmation": False, "process_family_peak_bytes": None, "device_energy_joules": None})


if __name__ == "__main__":
    main()
