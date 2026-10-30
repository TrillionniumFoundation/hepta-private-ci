"""Frozen authored-task comparison with actual rustc outcomes and shared budgets.

This is a controlled executable task family, not a benchmark of historical
repository incidents. The typed composition is a Python research runtime;
native source ownership is qualified independently by the Rust V11 tests.
"""

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import time

import numpy as np
import torch

from features import Encoder
from models import FeatureMemory, fit, predict, save
from tasks import ACTIONS, Compiler, diagnostic_rule, dump_tasks, execute_policy, make_tasks, observation_text, transform


def write(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def softmax(logits):
    logits = np.asarray(logits)
    values = np.exp(logits - logits.max(axis=-1, keepdims=True))
    return values / values.sum(axis=-1, keepdims=True)


def sigmoid(logits):
    return 1 / (1 + np.exp(-np.clip(logits, -50, 50)))


def source_identity():
    root = Path(__file__).parent
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in ("task_experiment.py", "tasks.py", "features.py", "models.py")}


class BM25:
    def __init__(self, texts, labels):
        self.labels = labels
        self.docs = [Counter(self.tokens(text)) for text in texts]
        self.lengths = np.array([sum(row.values()) for row in self.docs])
        self.average = float(self.lengths.mean())
        counts = Counter(word for row in self.docs for word in row)
        self.idf = {word: np.log(1 + (len(self.docs) - count + .5) / (count + .5))
                    for word, count in counts.items()}

    @staticmethod
    def tokens(text):
        return re.findall(r"[A-Za-z_][A-Za-z_0-9]*|&", text.lower())

    def probabilities(self, text):
        scores = np.zeros(len(self.docs))
        for word in set(self.tokens(text)):
            frequency = np.array([row[word] for row in self.docs])
            scores += self.idf.get(word, 0) * frequency * 2.5 / (
                frequency + 1.5 * (.25 + .75 * self.lengths / max(self.average, 1)))
        top = np.argsort(scores)[-3:]
        weights = softmax(scores[top])
        return np.bincount(self.labels[top], weights=weights, minlength=5)


class Policies:
    def __init__(self, encoder, x, texts, labels, models):
        self.encoder, self.x, self.labels, self.models = encoder, x, labels, models
        self.bm25 = BM25(texts, labels)
        self.inference = {}

    def probabilities(self, arm, text):
        started, cpu = time.perf_counter(), time.process_time()
        if arm == "lexical_bm25":
            result = self.bm25.probabilities(text)
        else:
            x = self.encoder.encode([text])
            if arm == "dense_knn":
                scores = self.x @ x[0]
                top = np.argsort(scores)[-3:]
                result = np.bincount(self.labels[top], weights=softmax(20 * scores[top]), minlength=5)
            elif arm.startswith("typed"):
                semantic = softmax(predict(self.models["semantic"], x))
                predictive = sigmoid(predict(self.models["predictive"], x))
                if arm == "typed_without_semantic":
                    semantic[:] = .2
                if arm == "typed_without_predictive":
                    predictive[:] = .5
                routing_input = np.concatenate([x, semantic, predictive], axis=1)
                route = softmax(predict(self.models["routing"], routing_input))
                support = np.concatenate([predictive, 1 - predictive.max(axis=1, keepdims=True)], axis=1)
                support /= support.sum(axis=1, keepdims=True)
                result = ((semantic + route + support) / 3)[0]
            else:
                result = softmax(predict(self.models[arm], x)[:, :5])[0]
        stats = self.inference.setdefault(arm, dict(calls=0, wall_seconds=0.0, cpu_seconds=0.0))
        stats["calls"] += 1
        stats["wall_seconds"] += time.perf_counter() - started
        stats["cpu_seconds"] += time.process_time() - cpu
        return result


def prepare(tasks, compiler, *, outcomes=False):
    rows = []
    for task in tasks:
        observed = compiler.inspect(task.source)
        row = dict(case_id=task.case_id, source_id=task.source_id,
                   text=observation_text(task.source, observed),
                   label=task.training_actions[0] if task.training_actions else 4,
                   observation=observed)
        if outcomes:
            rewards = []
            line = observed["diagnostics"][0]["line"] if observed["diagnostics"] else None
            for action in ACTIONS:
                outcome = compiler.inspect(transform(task.source, action, line=line))
                rewards.append(int(outcome["compile_returncode"] == 0 and outcome["run_returncode"] == 0
                                   and outcome["stdout"] == task.expected_stdout))
            expected = [int(row["label"] == i) for i in range(4)]
            if rewards != expected:
                raise ValueError("authored supervision disagrees with actual compiler outcome")
            row["action_rewards"] = rewards
        rows.append(row)
    return rows


def decision(probabilities, threshold):
    label = int(np.argmax(probabilities))
    return label if label < 4 and float(probabilities[label]) >= threshold else 4


def calibrate(policies, arm, rows):
    probabilities = np.stack([policies.probabilities(arm, row["text"]) for row in rows])
    labels = np.array([row["label"] for row in rows])
    candidates = []
    for threshold in (0.0, .25, .4, .55, .7, .85, .95, 1.01):
        predictions = np.array([decision(p, threshold) for p in probabilities])
        known, unknown = labels < 4, labels == 4
        score = .5 * float((predictions[known] == labels[known]).mean()) + .5 * float((predictions[unknown] == 4).mean())
        candidates.append(dict(threshold=threshold, balanced_accuracy=score))
    # Deterministic tie breaking, declared before observing calibration outcomes.
    selected = max(candidates, key=lambda item: (item["balanced_accuracy"], -item["threshold"]))
    return dict(selected=selected, candidates=candidates, case_ids=[r["case_id"] for r in rows],
                probabilities=probabilities.tolist(), labels=labels.tolist())


def summarize(results, tasks):
    known = {task.case_id for task in tasks if task.training_actions}
    k = [row for row in results if row["case_id"] in known]
    u = [row for row in results if row["case_id"] not in known]
    return dict(known_tasks=len(k), known_successes=sum(row["success"] for row in k),
                known_success_rate=sum(row["success"] for row in k) / len(k),
                unknown_tasks=len(u), correct_abstentions=sum(row["success"] for row in u),
                unknown_abstention_rate=sum(row["success"] for row in u) / len(u),
                decision_events=sum(len(row["trace"]) for row in results),
                patch_attempts=sum(step["action"] is not None for row in results for step in row["trace"]),
                applied_patches=sum(step["applied"] for row in results for step in row["trace"]),
                tool_calls=sum(row["observation_requests"] for row in results))


def parameter_bytes(model):
    return sum(p.numel() * p.element_size() for p in model.parameters() if p.requires_grad)


def run_seed(seed, output, encoder, rustc, steps):
    output.mkdir()
    compiler = Compiler(rustc, output / "compiler-observations")
    train = make_tasks(seed, "train", per_family=12, unknown=4)
    calibration = make_tasks(seed + 10000, "calibration", per_family=4, unknown=4)
    single = make_tasks(seed + 20000, "held-single", per_family=4, unknown=4)
    paired = make_tasks(seed + 30000, "held-paired", per_family=8, paired=True, unknown=4)
    partitions = {"train": train, "calibration": calibration, "held-single": single, "held-paired": paired}
    ids = [task.source_id for rows in partitions.values() for task in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("source leakage between partitions")
    for name, rows in partitions.items():
        dump_tasks(rows, output / (name + ".json"))
    train_rows = prepare(train, compiler, outcomes=True)
    calibration_rows = prepare(calibration, compiler)
    write(output / "training-observations.json", train_rows)
    write(output / "calibration-observations.json", calibration_rows)
    texts = [row["text"] for row in train_rows]
    x = encoder.encode(texts)
    labels = np.array([row["label"] for row in train_rows])
    targets = np.concatenate([np.eye(5, dtype=np.float32)[labels],
                              np.array([row["action_rewards"] for row in train_rows], np.float32)], axis=1)
    np.savez(output / "training-matrices.npz", x=x, labels=labels, targets=targets)
    schedule = np.random.default_rng(seed + 40000).integers(0, len(x), size=(steps, 16))
    np.save(output / "schedule.npy", schedule)
    source_ids = [row["source_id"] for row in train_rows]
    models, receipts = {}, {}
    for arm, hidden in (("single_model", 96), ("capacity_control", 128)):
        models[arm] = FeatureMemory("mlp", x.shape[1], 9, seed=seed, hidden=hidden)
        receipts[arm] = fit(models[arm], x, targets, [("multiclass", 5), ("binary", 4)], schedule,
                            source_ids=source_ids, label=arm, deadline=time.perf_counter() + 120)
    for name, hidden, target, outputs, offset in (
        ("semantic", 64, targets[:, :5], [("multiclass", 5)], 0),
        ("predictive", 32, targets[:, 5:], [("binary", 4)], steps // 3)):
        models[name] = FeatureMemory("mlp", x.shape[1], target.shape[1], seed=seed, hidden=hidden)
        receipts[name] = fit(models[name], x, target, outputs, schedule[offset:offset + steps // 3],
                             source_ids=source_ids, label=name, deadline=time.perf_counter() + 40)
    routed = np.concatenate([x, softmax(predict(models["semantic"], x)),
                             sigmoid(predict(models["predictive"], x))], axis=1)
    models["routing"] = FeatureMemory("mlp", routed.shape[1], 5, seed=seed, hidden=32)
    receipts["routing"] = fit(models["routing"], routed, targets[:, :5], [("multiclass", 5)], schedule[2 * (steps // 3):],
                              source_ids=source_ids, label="routing", deadline=time.perf_counter() + 40)
    for name, model in models.items():
        save(model, output / "models" / name, metadata={"training_source_ids": source_ids})
    write(output / "training-receipts.json", receipts)
    policies = Policies(encoder, x, texts, labels, models)
    arms = ("compiler_rule", "lexical_bm25", "dense_knn", "single_model", "capacity_control", "typed",
            "typed_without_semantic", "typed_without_predictive")
    calibrated = {arm: calibrate(policies, arm, calibration_rows) for arm in arms if arm != "compiler_rule"}
    # Ablations preserve the deployed network's threshold, avoiding post-intervention retuning.
    for arm in ("typed_without_semantic", "typed_without_predictive"):
        calibrated[arm]["selected"] = dict(calibrated["typed"]["selected"])
        calibrated[arm]["threshold_source"] = "typed unchanged threshold"
    write(output / "calibration.json", calibrated)
    ledger = sqlite3.connect(output / "events.sqlite")
    ledger.execute("CREATE TABLE events(arm TEXT, case_id TEXT, step INTEGER, source_id TEXT, action TEXT, details TEXT)")
    scores = {}
    for phase, tasks in (("held-single", single), ("held-paired", paired)):
        scores[phase] = {}
        for arm in arms:
            start_calls, start_seconds = compiler.calls, compiler.seconds
            results = []
            started = time.perf_counter()
            for task in tasks:
                seen = set()

                def choose(text, observed):
                    current = observed["source_sha256"]
                    if current in seen:
                        action, detail = None, {"repeat_source": True}
                    elif arm == "compiler_rule":
                        action, detail = diagnostic_rule(observed), {"policy": "compiler_rule"}
                    else:
                        probabilities = policies.probabilities(arm, text)
                        threshold = calibrated[arm]["selected"]["threshold"]
                        label = decision(probabilities, threshold)
                        action = ACTIONS[label] if label < 4 else None
                        detail = {"probabilities": probabilities.tolist(), "threshold": threshold}
                    ledger.execute("INSERT INTO events VALUES (?,?,?,?,?,?)",
                                   (arm, task.case_id, len(seen), current, action, json.dumps(detail)))
                    ledger.commit()
                    seen.add(current)
                    return action, detail

                results.append(execute_policy(task, compiler, choose, steps=2, use_cache=False))
            write(output / (phase + "-" + arm + ".json"), results)
            scores[phase][arm] = dict(summarize(results, tasks), actual_compiler_calls=compiler.calls - start_calls,
                                      compiler_wall_seconds=compiler.seconds - start_seconds,
                                      end_to_end_wall_seconds=time.perf_counter() - started)
            print(json.dumps(dict(seed=seed, phase=phase, arm=arm, **scores[phase][arm])), flush=True)
    ledger.close()
    write(output / "SCORES.json", scores)
    write(output / "COSTS.json", dict(inference=policies.inference, encoder=encoder.receipt(),
                                      trainable_payload_bytes={k: parameter_bytes(m) for k, m in models.items()},
                                      typed_payload_bytes=sum(parameter_bytes(models[k]) for k in ("semantic", "predictive", "routing")),
                                      compiler_calls=compiler.calls, compiler_cache_hits=compiler.cache_hits,
                                      compiler_wall_seconds=compiler.seconds,
                                      disk_bytes={str(p.relative_to(output)): p.stat().st_size for p in output.rglob("*") if p.is_file()},
                                      training_sample_presentations={k: r["sample_presentations"] for k, r in receipts.items()},
                                      note="Shared frozen encoding cache is instrumented; compiler calls are uncached in every policy arm. Python object/allocator overhead is not inferred from tensor bytes."))
    return scores


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--encoder", required=True, type=Path)
    parser.add_argument("--rustc", required=True)
    parser.add_argument("--seeds", default="81231,91243,101267")
    parser.add_argument("--steps", type=int, default=600)
    args = parser.parse_args()
    if args.steps < 3:
        parser.error("at least three steps required for typed partition")
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(2)
    seeds = [int(value) for value in args.seeds.split(",")]
    identity = source_identity()
    protocol = dict(schema="hepta.memory.v11.task-protocol.v1", argv=sys.argv, seeds=seeds,
                    source_sha256=identity, steps=args.steps, batch=16, max_patches=2, max_compiler_calls=3,
                    train_per_family=12, calibration_per_family=4, held_single_per_family=4, held_paired_per_family=8,
                    unknown_per_phase=4, supervision="actual compiler and exact program stdout on training examples",
                    budgets=dict(learned_total_sample_presentations=args.steps * 16, training_seconds_ceiling=120,
                                 trainable_bytes_ceiling=250000, compiler_timeout_seconds=20),
                    controls=["dense_knn", "lexical_bm25", "compiler_rule", "single_model", "capacity_control"],
                    primary_metric="held paired known-task executable-and-exact-output success; unknown abstention separate",
                    calibration="eight fixed thresholds, balanced known/unknown accuracy, lower-threshold tie break",
                    data_scope="authored compiler-backed fixtures, opaque variable names, unseen sources and two-defect compositions",
                    deployment_scope="research Python typed network; separate Rust ownership vertical slice",
                    prices="none; quality, parameter bytes, training, inference and compiler costs reported separately")
    write(args.output / "PROTOCOL.json", protocol)
    encoder = Encoder(args.encoder)
    all_scores = {str(seed): run_seed(seed, args.output / str(seed), encoder, args.rustc, args.steps) for seed in seeds}
    if source_identity() != identity:
        raise RuntimeError("source changed during experiment; attempt is not frozen")
    write(args.output / "RESULTS.json", dict(protocol=protocol, scores=all_scores, encoder=encoder.receipt(),
                                             complete=True, acceptance_claim=False))


if __name__ == "__main__":
    main()
