"""Execute frozen V10 models from causal AV packets with no Torch dependency.

This inference port retains the original scheduler/head and finite observation
model. It does not retrain, qualify a new cohort or activate production code.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from scipy.linalg import expm
from scipy.special import expit

from experiments.hcsn_v7_support_20261101.content_interface.content_interface import (
    BackendKind, CacheBudget, ContractError, CoreSnapshot, CorrectnessValue, Modality, StopEvaluation,
)
from experiments.hcsn_causal_execution_v3.av_probe import predict_prefix
from experiments.hcsn_v8_execution_20261101.frontend.legacy_v3 import (
    BinnedCorrectness, cache_rows,
)
from experiments.hcsn_v8_execution_20261101.scheduler.execution import LogicalClock, run_episode
from experiments.hcsn_v8_execution_20261101.scheduler.historical_service import PreparedPrefixService
from experiments.hcsn_v8_execution_20261101.scheduler.planning import Plan, Read, ServiceEstimate


ROOT = Path(__file__).resolve().parents[3]
LEVELS = tuple((a, v) for a in range(4) for v in range(4))
FAMILIES = ("history", "gru", "ssm", "filter")
ROW, PATH = 58, 256


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def verify(bundle):
    manifest = json.loads((bundle / "MANIFEST.json").read_text())
    for relative, expected in manifest["source_sha256"].items():
        if sha(ROOT / relative) != expected:
            raise RuntimeError("Frozen runtime source changed: " + relative)
    for relative, expected in manifest["artifact_sha256"].items():
        path = (bundle / relative).resolve()
        if not path.is_relative_to(bundle.resolve()) or sha(path) != expected:
            raise RuntimeError("Frozen runtime artifact changed: " + relative)
    return manifest


class Head:
    def __init__(self, bundle, task):
        with np.load(bundle / task / "head.npz", allow_pickle=False) as arrays:
            self.model = {k: arrays[k].copy() for k in arrays.files}
        record = json.loads((bundle / task / "head.json").read_text())
        self.head_id = record["head_id"]
        self.calibrator = BinnedCorrectness(**record["calibrator"])

    def classify(self, content):
        return predict_prefix(self.model, *cache_rows(content))

    def evaluate(self, content):
        p = tuple(float(v) for v in self.classify(content))
        return StopEvaluation(p, self.calibrator(p, content))


def observation_features(content, head, increment, observation):
    vectors = [np.zeros(16) if content.observation(m) is None
               else np.asarray(content.observation(m).aligned) for m in Modality]
    p = np.zeros(6); current = head.classify(content); p[:len(current)] = current
    raw = np.asarray(observation.raw[2:]).reshape(-1, 17)
    lower = observation.prefix_end - 1
    keep = raw[:, 0] >= lower if lower == 0 else raw[:, 0] > lower
    new = raw[keep, 1:]
    value = new.mean(0) if len(new) else np.zeros(16)
    row = np.r_[*vectors, p, content.level(Modality.AUDIO) / 3,
                content.level(Modality.VIDEO) / 3, increment, value, float(len(new) > 0)]
    return row, value, len(new)


class Model:
    def __init__(self, family, path):
        self.family = family
        with np.load(path, allow_pickle=False) as arrays:
            self.weights = {k: np.asarray(arrays[k], dtype=np.float64).copy() for k in arrays.files}
        if not all(np.isfinite(v).all() for v in self.weights.values()):
            raise ValueError("Nonfinite frozen weight")

    def linear(self, x, name):
        return x @ self.weights[name + ".weight"].T + self.weights[name + ".bias"]

    def update_state(self, row, h):
        if self.family == "gru":
            wi, wh = self.weights["update.weight_ih"], self.weights["update.weight_hh"]
            gi = row @ wi.T + self.weights["update.bias_ih"]
            gh = h @ wh.T + self.weights["update.bias_hh"]
            ir, iz, inn = np.split(gi, 3, axis=1)
            hr, hz, hn = np.split(gh, 3, axis=1)
            reset, update = expit(ir + hr), expit(iz + hz)
            new = np.tanh(inn + reset * hn)
            return (h - new) * update + new
        if self.family == "ssm":
            rate = self.linear(row, "rate")
            softplus = np.where(rate > 20, rate, np.logaddexp(0, rate))
            decay = np.exp(-softplus * row[:, 40:41])
            gain = expit(self.linear(row, "gain"))
            return (1 - gain) * decay * h + gain * np.tanh(self.linear(row, "drive"))
        return h

    def predict(self, history, h, belief):
        extra = belief if self.family == "filter" else h if self.family in ("gru", "ssm") else None
        x = history if extra is None else np.concatenate((history, extra), axis=1)
        return self.linear(np.tanh(self.linear(x, "reader.0")), "reader.2")


def uniformization(q):
    rate = float(max(-np.diag(q)))
    if rate == 0:
        return np.eye(len(q))
    coefficient, power = np.exp(-rate), np.eye(len(q))
    r = power + q / rate
    result, mass = coefficient * power, coefficient
    for order in range(1, 10000):
        power = power @ r; coefficient *= rate / order
        result += coefficient * power; mass += coefficient
        if 1 - mass <= 2e-15:
            return result
    raise ArithmeticError("Uniformization failed its fixed tail budget")


class PathFilter:
    def __init__(self, law, implementation):
        self.law, self.k, self.time = law, len(law["prior"]), 0
        self.p = np.asarray(law["prior"], dtype=np.float64)
        q = np.asarray(law["q"], dtype=np.float64)
        self.transition = expm(q) if implementation == "expm" else uniformization(q)
        if np.min(self.transition) < -1e-13 or not np.allclose(self.transition.sum(1), 1, atol=1e-13, rtol=0):
            raise ArithmeticError("Frozen law is not stochastic")

    def accept(self, source_time, modality, value, count, global_time):
        if not 1 <= source_time <= global_time <= 3 or global_time < self.time:
            raise ValueError("Invalid source clock")
        while self.time < global_time:
            self.p = np.einsum("...i,ij->...ij", self.p, self.transition)
            self.time += 1
        if self.p.size > PATH:
            raise ValueError("Finite path capacity exceeded")
        if count:
            mean = np.asarray(self.law["mean"])[modality]
            variance = np.asarray(self.law["variance"])[modality]
            ll = -.5 * np.sum(np.log(2 * np.pi * variance) + (value - mean)**2 / variance, axis=1)
            shape = [1] * self.p.ndim; shape[source_time] = self.k
            weighted = self.p * np.exp(ll - ll.max()).reshape(shape)
            normalizer = float(weighted.sum())
            if normalizer <= 0 or not np.isfinite(normalizer):
                raise ArithmeticError("No representable conditional mass")
            self.p = weighted / normalizer

    def features(self):
        result = np.zeros(PATH); result[:self.p.size] = self.p.ravel()
        return result


class Holder:
    def __init__(self, model, head, law, model_id, implementation):
        self.model, self.head, self.core_id = model, head, model_id
        self.filter = PathFilter(law, implementation) if model.family == "filter" else None
        self.rows, self.events, self.current = [], [], None
        self.h = np.zeros((1, 64))

    def snapshot(self, content):
        payload = [content.fingerprint(), self.rows, self.h.tolist(),
                   None if self.filter is None else self.filter.p.ravel().tolist()]
        digest = hashlib.sha256(json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()).digest()
        return CoreSnapshot(self.core_id, content.fingerprint(), tuple(float(v) for v in digest))

    def initial(self, content):
        if self.current is not None:
            raise ContractError("Holder is single episode")
        self.current = self.snapshot(content)
        return self.current

    def accept(self, state, updated, observation, increment):
        if state != self.current or len(self.rows) >= 6:
            raise ContractError("Stale or oversized accepted history")
        row, value, count = observation_features(updated, self.head, increment, observation)
        if self.filter is not None:
            self.filter.accept(int(observation.prefix_end), int(observation.modality == Modality.VIDEO), value,
                               count, int(max(updated.level(m) for m in Modality)))
        self.h = self.model.update_state(row[None], self.h)
        self.rows.append(row.tolist()); self.current = self.snapshot(updated)
        self.events.append({"event_id": observation.event_id, "source_time": observation.prefix_end,
            "global_source_increment": increment, "row": row.tolist(), "hidden": self.h.tolist(),
            "path_shape": [] if self.filter is None else list(self.filter.p.shape),
            "path_probability": [] if self.filter is None else self.filter.p.ravel().tolist(),
            "content_fingerprint": updated.fingerprint(), "digest": self.current.values})
        return self.current


class Forecast:
    kind = BackendKind.CORE

    def __init__(self, holder):
        self.holder, self.reader_id = holder, holder.core_id

    def evaluate(self, content, state, plan):
        h = self.holder
        if state != h.current or state.content_fingerprint != content.fingerprint():
            raise ContractError("Readout requires current accepted state")
        if not plan.requested_reads:
            return h.head.evaluate(content).calibrated_correctness
        levels = {m: int(content.level(m)) for m in Modality}
        for step in plan.steps:
            if type(step) is Read:
                levels[step.modality] = step.prefix_end
        padded = np.zeros((6, ROW)); padded[:len(h.rows)] = h.rows
        history = np.r_[padded.ravel(), np.arange(6) < len(h.rows)][None]
        belief = np.zeros(PATH) if h.filter is None else h.filter.features()
        p = expit(h.model.predict(history, h.h, belief[None]))[0, LEVELS.index(
            (levels[Modality.AUDIO], levels[Modality.VIDEO]))]
        return CorrectnessValue(float(p), h.head.head_id)


class ServiceModel:
    def estimate(self, content, plan, now, deadline):
        t, requests = now, 0
        for step in plan.steps:
            if t >= deadline:
                break
            if type(step) is Read:
                requests += 1; t = max(t, step.prefix_end) + .001
            else:
                t += step.seconds
        return ServiceEstimate(min(t, deadline) - now, 0.0, requests)


def episode(bundle, item, data, index, policy, model=None, implementation="expm"):
    head = Head(bundle, item["task"])
    model = Model(item["family"], bundle / item["numpy_path"]) if model is None else model
    law = json.loads((bundle / item["task"] / f"law-{item['seed']}.json").read_text())["selected"]
    holder = Holder(model, head, law, item["source_pt_sha256"][:32], implementation)
    object_id = f"v10-{item['task']}-{index}-{item['seed']}-{item['family']}-{implementation}-{policy}"
    valid = data["valid"][index]
    arrays = data["x"][index, valid], data["observed"][index, valid], data["relative_times"][index, valid]
    steps = (Read(Modality.VIDEO, 1), Read(Modality.AUDIO, 2), Read(Modality.VIDEO, 2),
             Read(Modality.AUDIO, 3), Read(Modality.VIDEO, 3))
    result = run_episode(object_id, CacheBudget(65536), head, Forecast(holder), ServiceModel(),
        PreparedPrefixService(*arrays, object_id), lambda _: None, clock=LogicalClock(), core=holder,
        horizon=6 if policy == "fixed" else 2, fixed_plans=(Plan(steps),) if policy == "fixed" else None)
    if result["requested_observations"] != len(holder.rows) or any(
            e.get("status") in ("failed", "rejected", "timed_out") for e in result["events"]):
        raise AssertionError("Frozen model episode did not complete")
    return result, holder.events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--task", choices=("async_av", "av_binding"), required=True)
    parser.add_argument("--family", choices=FAMILIES, required=True)
    parser.add_argument("--seed", type=int, choices=(91101, 91103), required=True)
    parser.add_argument("--implementation", choices=("expm", "uniformization"), default="expm")
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=False)
    if args.family != "filter" and args.implementation != "expm":
        raise ValueError("Uniformization is a same-law filter implementation only")
    manifest = verify(args.bundle)
    item = next(x for x in manifest["models"] if (x["task"], x["family"], x["seed"]) == (args.task, args.family, args.seed))
    with np.load(args.bundle / args.task / "test-packets.npz", allow_pickle=False) as source:
        data = {k: source[k].copy() for k in source.files}
    model, rows = Model(item["family"], args.bundle / item["numpy_path"]), []
    with gzip.open(args.out / "TRACES.jsonl.gz", "xt") as stream:
        for index in range(len(data["labels"])):
            for policy in ("fixed", "value"):
                result, updates = episode(args.bundle, item, data, index, policy, model, args.implementation)
                correct = result["output"]["predicted_class"] == int(data["labels"][index])
                row = {"index": index, "policy": policy, "correct": correct,
                       "requests": result["requested_observations"], "output": result["output"]}
                rows.append(row)
                stream.write(json.dumps({**row, "execution": result, "updates": updates}, allow_nan=False) + "\n")
    write(args.out / "SUMMARY.json", {"model": item, "rows": rows, "executions": len(rows),
        "implementation": args.implementation,
        "runtime": "NumPy/SciPy real frozen-model inference", "torch_imported": "torch" in sys.modules,
        "numpy": np.__version__, "scientific_admission": False, "energy_joules": None})
    if "torch" in sys.modules:
        raise RuntimeError("Torch must not be imported by this runtime")


if __name__ == "__main__":
    main()
