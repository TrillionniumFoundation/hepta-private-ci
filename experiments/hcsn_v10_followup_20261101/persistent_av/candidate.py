"""Fitted finite AV path filter; matrix exponential has a same-law HMM control.

This is a new, explicitly approximate generative research law. It is neither a
financial free-boundary model nor the unavailable V6 scientific confirmation.
"""

import argparse
import copy
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import time

import numpy as np
from scipy.cluster.vq import kmeans2
from scipy.linalg import expm
import torch
from torch import nn

from experiments.hcsn_v9_followup_20261101.persistent_av import candidate as base


FAMILIES = ("history", "gru", "ssm", "filter")
SLOTS, ROW, PATH = 6, 58, 256


def new_window(observation):
    raw = np.asarray(observation.raw[2:]).reshape(-1, 17)
    lower = observation.prefix_end - 1
    select = (raw[:, 0] >= lower if lower == 0 else raw[:, 0] > lower)
    values = raw[select, 1:]
    return (values.mean(0) if len(values) else np.zeros(16)), len(values)


def uniformization(q, dt, tolerance=2e-15):
    rate = float(max(-np.diag(q)))
    if rate == 0 or dt == 0:
        return np.eye(len(q))
    r = np.eye(len(q)) + q / rate
    coefficient, power = np.exp(-rate * dt), np.eye(len(q))
    result, mass = coefficient * power, coefficient
    for order in range(1, 10000):
        power = power @ r
        coefficient *= rate * dt / order
        result += coefficient * power
        mass += coefficient
        if 1 - mass <= tolerance:
            return result
    raise ArithmeticError("Uniformization failed its fixed tail budget")


class PathFilter:
    """Retain the finite latent path, so late V1 conditions z1 after A3."""

    def __init__(self, law, implementation="expm"):
        self.law, self.k, self.time = law, len(law["prior"]), 0
        self.p = np.asarray(law["prior"], float)
        q = np.asarray(law["q"], float)
        self.transition = expm(q) if implementation == "expm" else uniformization(q, 1)
        if np.min(self.transition) < -1e-13 or not np.allclose(self.transition.sum(1), 1, atol=1e-13, rtol=0):
            raise ArithmeticError("Fitted transition is not row stochastic")

    def accept(self, source_time, modality, value, count, global_time):
        if not 1 <= source_time <= global_time <= 3 or global_time < self.time:
            raise ValueError("Invalid causal source-clock update")
        while self.time < global_time:
            self.p = np.einsum("...i,ij->...ij", self.p, self.transition)
            self.time += 1
        if self.p.size > PATH:
            raise ValueError("Finite path storage bound exceeded")
        if not count:
            return 0.0
        mean = np.asarray(self.law["mean"])[modality]
        variance = np.asarray(self.law["variance"])[modality]
        log_likelihood = -.5 * np.sum(np.log(2 * np.pi * variance) + (value - mean)**2 / variance, axis=1)
        shape = [1] * self.p.ndim
        shape[source_time] = self.k
        maximum = float(log_likelihood.max())
        weighted = self.p * np.exp(log_likelihood - maximum).reshape(shape)
        normalizer = float(weighted.sum())
        if normalizer <= 0 or not np.isfinite(normalizer):
            raise ArithmeticError("Observed history has no representable probability")
        self.p = weighted / normalizer
        return maximum + np.log(normalizer)

    def features(self):
        result = np.zeros(PATH)
        result[:self.p.size] = self.p.ravel()
        return result


def windows(data):
    rows = []
    for index in range(len(data["ids"])):
        by_time = []
        for t in range(1, 4):
            cache = base.populated_cache(data, index, t, t)
            by_time.append([new_window(cache.observation(m)) for m in base.Modality])
        rows.append(by_time)
    return rows


def fit_law(train, validation, seed):
    training, validating = windows(train), windows(validation)
    joint = np.asarray([[np.r_[r[0][0], r[1][0]] for r in clip] for clip in training])
    center, scale = joint.reshape(-1, 32).mean(0), np.maximum(joint.reshape(-1, 32).std(0), 1e-3)
    records, best = [], None
    for k, shrink in itertools.product((2, 4), (.25, 1.0)):
        _, assignment = kmeans2(((joint - center) / scale).reshape(-1, 32), k,
                                iter=50, minit="++", seed=seed)
        assignment = assignment.reshape(len(training), 3)
        rates = np.full((k, k), .1)
        dwell = np.bincount(assignment[:, :2].ravel(), minlength=k) + .1 * k
        for clip in assignment:
            for a, b in zip(clip[:-1], clip[1:]):
                if a != b:
                    rates[a, b] += 1
        np.fill_diagonal(rates, 0)
        q = rates / dwell[:, None]
        np.fill_diagonal(q, -q.sum(1))
        means, variances = [], []
        for modality in range(2):
            all_values = np.asarray([entry[modality][0] for clip in training for entry in clip if entry[modality][1]])
            pooled_mean = all_values.mean(0)
            pooled_variance = np.maximum(all_values.var(0), 1e-4)
            mod_mean, mod_variance = [], []
            for state in range(k):
                values = np.asarray([entry[modality][0] for i, clip in enumerate(training)
                                     for t, entry in enumerate(clip) if assignment[i, t] == state and entry[modality][1]])
                mean = values.mean(0) if len(values) else pooled_mean
                variance = ((np.sum((values - mean)**2, axis=0) if len(values) else np.zeros(16))
                            + shrink * pooled_variance) / (len(values) + shrink) + .01 * pooled_variance
                mod_mean.append(mean.tolist())
                mod_variance.append(variance.tolist())
            means.append(mod_mean)
            variances.append(mod_variance)
        prior = np.bincount(assignment[:, 0], minlength=k) + .1
        law = {"q": q.tolist(), "prior": (prior / prior.sum()).tolist(), "mean": means, "variance": variances,
               "k": k, "shrink": shrink, "fit_seed": seed,
               "fit_method": "train kmeans states, smoothed off-diagonal count/dwell rates, diagonal Gaussian moments"}
        scores = []
        for clip in validating:
            filtering = PathFilter(law)
            score = 0.0
            for t, observations in enumerate(clip, 1):
                for modality, (value, count) in enumerate(observations):
                    score += filtering.accept(t, modality, value, count, t)
            scores.append(score)
        record = {"law": law, "validation_log_likelihood": float(np.sum(scores)), "validation_clip_scores": scores}
        records.append(record)
        if best is None or record["validation_log_likelihood"] > best["validation_log_likelihood"]:
            best = record
    return best["law"], records


def dataset(task, split, head, law):
    data = base.legacy_data(task, split)
    x, y, mask, beliefs = [], [], [], []
    for index, label in enumerate(base.labels_of(data)):
        caches = {level: base.populated_cache(data, index, *level) for level in base.LEVELS}
        targets = np.asarray([head.classify(caches[level]).argmax() == label for level in base.LEVELS], float)
        for schedule in base.schedules():
            a, v, previous = 0, 0, 0
            seq, ms, bs = [], [], []
            filtering = PathFilter(law)
            for modality in schedule:
                a += modality == base.Modality.AUDIO
                v += modality == base.Modality.VIDEO
                current = caches[a, v]
                value, count = new_window(current.observation(modality))
                level = a if modality == base.Modality.AUDIO else v
                filtering.accept(level, int(modality == base.Modality.VIDEO), value, count, max(a, v))
                seq.append(np.r_[base.cache_features(current, head, max(a, v) - previous), value, float(count > 0)])
                bs.append(filtering.features())
                ms.append([ga >= a and gv >= v and (ga, gv) != (a, v) for ga, gv in base.LEVELS])
                previous = max(a, v)
            x.append(seq); beliefs.append(bs); y.append(np.tile(targets, (6, 1))); mask.append(ms)
    return tuple(torch.tensor(np.asarray(value), dtype=torch.float64) for value in (x, y, mask, beliefs)), data


class Model(nn.Module):
    def __init__(self, family):
        super().__init__()
        self.family = family
        if family == "gru":
            self.update = nn.GRUCell(ROW, 64)
        if family == "ssm":
            self.rate, self.gain, self.drive = (nn.Linear(ROW, 64) for _ in range(3))
        width = {"history": 354, "gru": 418, "ssm": 418, "filter": 610}[family]
        hidden = {"history": 108, "gru": 38, "ssm": 66, "filter": 64}[family]
        self.reader = nn.Sequential(nn.Linear(width, hidden), nn.Tanh(), nn.Linear(hidden, 16))
        self.double()

    def update_state(self, row, h):
        if self.family == "gru":
            return self.update(row, h)
        if self.family == "ssm":
            decay = torch.exp(-nn.functional.softplus(self.rate(row)) * row[:, 40:41])
            gain = self.gain(row).sigmoid()
            return (1 - gain) * decay * h + gain * self.drive(row).tanh()
        return h

    def predict(self, history, h, belief):
        extra = belief if self.family == "filter" else h if self.family in ("gru", "ssm") else None
        return self.reader(history if extra is None else torch.cat((history, extra), -1))

    def forward(self, x, belief):
        h, output = x.new_zeros((len(x), 64)), []
        for t in range(6):
            h = self.update_state(x[:, t], h)
            padded = torch.cat((x[:, :t + 1], torch.zeros_like(x[:, t + 1:])), 1)
            masks = (torch.arange(6, device=x.device) <= t).to(x.dtype).expand(len(x), -1)
            output.append(self.predict(torch.cat((padded.flatten(1), masks), 1), h, belief[:, t]))
        return torch.stack(output, 1)


class Holder:
    def __init__(self, model, head, law, model_id, implementation):
        self.model, self.head, self.core_id = model, head, model_id
        self.filter = PathFilter(law, implementation) if model.family == "filter" else None
        self.rows, self.events, self.current = [], [], None
        self.h = torch.zeros((1, 64), dtype=torch.float64)

    def snapshot(self, content):
        payload = [content.fingerprint(), self.rows, self.h.tolist(),
                   None if self.filter is None else self.filter.p.ravel().tolist()]
        digest = hashlib.sha256(json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()).digest()
        return base.CoreSnapshot(self.core_id, content.fingerprint(), tuple(float(v) for v in digest))

    def initial(self, content):
        if self.current is not None:
            raise base.ContractError("Holder is single-episode")
        self.current = self.snapshot(content)
        return self.current

    def accept(self, state, updated, observation, increment):
        if state != self.current or len(self.rows) >= 6:
            raise base.ContractError("Stale or oversized accepted history")
        value, count = new_window(observation)
        global_time = int(max(updated.level(m) for m in base.Modality))
        if self.filter is not None:
            self.filter.accept(int(observation.prefix_end), int(observation.modality == base.Modality.VIDEO), value, count, global_time)
        row = np.r_[base.cache_features(updated, self.head, increment), value, float(count > 0)]
        with torch.no_grad():
            self.h = self.model.update_state(torch.tensor(row)[None], self.h)
        self.rows.append(row.tolist())
        self.current = self.snapshot(updated)
        self.events.append({"event_id": observation.event_id, "source_time": observation.prefix_end,
            "global_source_increment": increment, "row": row.tolist(),
            "path_shape": [] if self.filter is None else list(self.filter.p.shape),
            "path_probability": [] if self.filter is None else self.filter.p.ravel().tolist(), "hidden": self.h.tolist(),
            "content_fingerprint": updated.fingerprint(), "digest": self.current.values})
        return self.current


class Forecast:
    kind = base.BackendKind.CORE

    def __init__(self, holder):
        self.holder, self.reader_id = holder, holder.core_id

    def evaluate(self, content, state, plan):
        holder = self.holder
        if state != holder.current or state.content_fingerprint != content.fingerprint():
            raise base.ContractError("Readout must bind exact accepted state")
        if not plan.requested_reads:
            return holder.head.evaluate(content).calibrated_correctness
        levels = {m: int(content.level(m)) for m in base.Modality}
        for step in plan.steps:
            if hasattr(step, "modality"):
                levels[step.modality] = step.prefix_end
        padded = np.zeros((6, ROW)); padded[:len(holder.rows)] = holder.rows
        history = torch.tensor(np.r_[padded.ravel(), np.arange(6) < len(holder.rows)])[None]
        with torch.no_grad():
            belief = np.zeros(PATH) if holder.filter is None else holder.filter.features()
            p = holder.model.predict(history, holder.h, torch.tensor(belief)[None]).sigmoid()[
                0, base.LEVELS.index((levels[base.Modality.AUDIO], levels[base.Modality.VIDEO]))].item()
        return base.CorrectnessValue(p, holder.head.head_id)


def fit_model(family, seed, train, val, output):
    torch.manual_seed(seed)
    model, history = Model(family), []
    optimizer = torch.optim.AdamW(model.parameters(), lr=.003, weight_decay=1e-3)
    tx, ty, tm, tb = train; vx, vy, vm, vb = val
    best, selected, weights = float("inf"), 0, None
    for epoch in range(101):
        if epoch:
            optimizer.zero_grad(set_to_none=True)
            errors = nn.functional.binary_cross_entropy_with_logits(model(tx, tb), ty, reduction="none")
            ((errors * tm).sum() / tm.sum()).backward()
            nn.utils.clip_grad_norm_(model.parameters(), 5); optimizer.step()
        with torch.no_grad():
            errors = nn.functional.binary_cross_entropy_with_logits(model(vx, vb), vy, reduction="none")
            score = ((errors * vm).sum() / vm.sum()).item()
        history.append({"epoch": epoch, "validation_bce": score})
        if score < best:
            best, selected, weights = score, epoch, copy.deepcopy(model.state_dict())
    torch.save(model.state_dict(), output / f"{family}-{seed}-final.pt")
    model.load_state_dict(weights)
    torch.save(weights, output / f"{family}-{seed}-selected.pt")
    base.write(output / f"{family}-{seed}-FIT.json", {"history": history, "selected_epoch": selected,
        "parameters": sum(p.numel() for p in model.parameters()), "validation_bce": best})
    return model


def sources():
    return {**base.source_hashes(), str(Path(__file__)): base.sha(Path(__file__))}


def prepare(output):
    output.mkdir(parents=True, exist_ok=False)
    base.write(output / "PROTOCOL.json", {"sources": sources(), "seeds": base.SEEDS, "families": FAMILIES,
        "bounded_budget": "K in {2,4}, variance shrinkage in {.25,1}; train-fitted moments, val likelihood selection; 100 updates per reader",
        "semantics": "Finite CTMC latent-path distribution; approximate diagonal Gaussian fresh-window emissions; empty windows uninformative",
        "initial_prior": "Smoothed training first-window state occupancy used as initial-time mixture",
        "information": "Every family receives full six-slot accepted 58-value history; filter appends same fresh-window observations",
        "conditioning": "A3 then V1 conditions retained z1, never current z3; cumulative prefix rows assimilated only in their new source window",
        "same_law_reference": "Independent Poisson uniformization ordinary HMM; shared Q/emissions/readout weights; no exclusive analytic gain expected",
        "financial_HX": False, "real_independent_confirmation": False, "original_scientific_admission": False,
        "torch": torch.__version__, "source_clock": "logical; CPU charged by enclosing workers"})
    freezes = []
    for task in ("async_av", "av_binding"):
        destination = output / task; destination.mkdir()
        training, validation = base.legacy_data(task, "train"), base.legacy_data(task, "val")
        head, _, _ = base.fit_development_adapters(task, validation, destination)
        base.write(destination / "INPUTS.json", {"train": base.data_identity(training), "val": base.data_identity(validation),
            "head_checkpoint_sha256": head.checkpoint_sha256, "sources": sources()})
        for seed in base.SEEDS:
            law, attempted = fit_law(training, validation, seed)
            base.write(destination / f"LAW-{seed}.json", {"selected": law, "all_candidates": attempted})
            train, _ = dataset(task, "train", head, law); val, _ = dataset(task, "val", head, law)
            np.savez_compressed(destination / f"data-{seed}.npz", **{
                f"{split}_{name}": tensor.numpy() for split, arrays in (("train", train), ("val", val))
                for name, tensor in zip(("x", "y", "mask", "belief"), arrays, strict=True)})
            for family in FAMILIES:
                fit_model(family, seed, train, val, destination)
                path = destination / f"{family}-{seed}-selected.pt"
                freezes.append({"task": task, "seed": seed, "family": family,
                                "sha256": base.sha(path), "path": str(path.relative_to(output))})
    base.write(output / "FROZEN.json", {"unix": time.time(), "models": freezes, "sources": sources()})


def evaluate(output):
    frozen = json.loads((output / "FROZEN.json").read_text())
    if any(base.sha(Path(p)) != h for p, h in frozen["sources"].items()):
        raise RuntimeError("Frozen sources changed")
    if not (output / "INDEPENDENT_PRECHECK.json").is_file():
        raise RuntimeError("Independent pre-evaluation numerical check is required")
    precheck = json.loads((output / "INDEPENDENT_PRECHECK.json").read_text())
    if precheck.get("status") != "passed":
        raise RuntimeError("Independent precheck did not pass")
    rows, traces = [], []
    for task in ("async_av", "av_binding"):
        destination = output / task
        adapter = json.loads((destination / f"{task}_ADAPTERS.json").read_text())
        from experiments.hcsn_v8_execution_20261101.frontend.legacy_v3 import BinnedCorrectness, LegacyV3Head
        head = LegacyV3Head(task, BinnedCorrectness(**adapter["calibrator"]))
        data = base.legacy_data(task, "test")
        base.write(destination / "HISTORICAL_TEST_INPUTS.json", base.data_identity(data))
        for item in [r for r in frozen["models"] if r["task"] == task]:
            path = output / item["path"]
            if base.sha(path) != item["sha256"]:
                raise RuntimeError("Selected model changed")
            family, seed = item["family"], item["seed"]
            model = Model(family); model.load_state_dict(torch.load(path, weights_only=True)); model.eval()
            law = json.loads((destination / f"LAW-{seed}.json").read_text())["selected"]
            for implementation in (("expm", "uniformization") if family == "filter" else ("expm",)):
                for index, label in enumerate(base.labels_of(data)):
                    for policy in ("fixed", "value"):
                        object_id = f"v10-{task}-{index}-{seed}-{family}-{implementation}-{policy}"
                        holder = Holder(model, head, law, item["sha256"][:32], implementation)
                        result = base.run_episode(object_id, base.CacheBudget(65536), head, Forecast(holder), base.FixedServiceModel(),
                            base.PreparedPrefixService(*base.episode_arrays(data, index), object_id), lambda _: None,
                            clock=base.LogicalClock(), core=holder, horizon=6 if policy == "fixed" else 2,
                            fixed_plans=base.fixed_plans("common_full") if policy == "fixed" else None)
                        assert result["requested_observations"] == len(holder.rows)
                        assert not any(e.get("status") in ("failed", "rejected", "timed_out") for e in result["events"])
                        correct = result["output"]["predicted_class"] == int(label)
                        row = {"task": task, "index": index, "seed": seed, "family": family,
                            "implementation": implementation, "policy": policy, "label": int(label), "correct": correct,
                            "requests": result["requested_observations"], "utility": float(correct - result["observation_fee"]
                                - result["latency_fee"] - result["deadline_penalty"])}
                        rows.append(row); traces.append({**row, "execution": result, "updates": holder.events})
    with gzip.open(output / "TRACES.jsonl.gz", "xt") as stream:
        for trace in traces:
            stream.write(json.dumps(trace, allow_nan=False) + "\n")
    groups = []
    for task, family, policy in itertools.product(("async_av", "av_binding"), FAMILIES, ("fixed", "value")):
        selected = [r for r in rows if (r["task"], r["family"], r["policy"], r["implementation"]) == (task, family, policy, "expm")]
        groups.append({"task": task, "family": family, "policy": policy, "runs": len(selected),
            "accuracy": float(np.mean([r["correct"] for r in selected])),
            "mean_utility": float(np.mean([r["utility"] for r in selected])),
            "mean_requests": float(np.mean([r["requests"] for r in selected]))})
    base.write(output / "SUMMARY.json", {"groups": groups, "rows": rows, "executions": len(rows),
        "original_scientific_admission": False, "financial_HX": False, "energy_joules": None})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "evaluate"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(); torch.set_num_threads(1)
    prepare(args.output) if args.stage == "prepare" else evaluate(args.output)
