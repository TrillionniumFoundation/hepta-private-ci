#!/usr/bin/env python3
"""Measured CPU shared-compute mechanism probe; no pretrained model or Hepta claim.

A random token/MLP encoder and real gated Heads run in isolated Linux child
processes. Serial and batched arms jointly encode state+question. The sharing arm
encodes state once and conditions its Head on question; equivalence is NOT assumed.
All requests arrive at cohort start. Latency includes local queueing, scoped-key
lookup, encoding and Head work. Fixture materialization, admission digests, model
load, network, production WAL and final-use are outside this serving clock.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import math
import multiprocessing as mp
import os
from pathlib import Path
import platform
import random
import resource
import sys
import time

import torch
from torch import nn
from torch.nn import functional as F

from four_gate_core import (COMPUTE_ARMS, canonical, default_plan, digest, read_jsonl,
                            require, validate_plan, write_once)
from four_gate_review import review_compute


class Encoder(nn.Module):
    def __init__(self):
        super().__init__()
        self.embedding = nn.Embedding(257, 16)
        self.net = nn.Sequential(nn.Linear(16, 32), nn.SiLU(), nn.Linear(32, 16))
        self.calls, self.samples, self.tokens = 0, 0, 0

    def forward(self, tokens):
        self.calls += 1
        self.samples += len(tokens)
        self.tokens += tokens.numel()
        return self.net(self.embedding(tokens).mean(1))


class Heads(nn.Module):
    def __init__(self, count):
        super().__init__()
        self.query = nn.Embedding(8, 8)
        self.gate = nn.Parameter(torch.randn(count, 24, 12) / math.sqrt(24))
        self.drive = nn.Parameter(torch.randn(count, 24, 12) / math.sqrt(24))
        self.out = nn.Parameter(torch.randn(count, 12, 2) / math.sqrt(12))

    def forward(self, states, questions, cell_ids):
        x = torch.cat((states, self.query(questions)), 1).unsqueeze(1)
        values = torch.sigmoid(torch.bmm(x, self.gate[cell_ids])) * F.silu(torch.bmm(x, self.drive[cell_ids]))
        return torch.bmm(values, self.out[cell_ids]).squeeze(1)


def weights_digest(model):
    h = hashlib.sha256()
    for key, tensor in sorted(model.state_dict().items()):
        h.update(canonical([key, list(tensor.shape), str(tensor.dtype)]))
        h.update(tensor.detach().contiguous().numpy().tobytes())
    return h.hexdigest()


def worker(connection, config):
    try:
        torch.set_num_threads(1)
        torch.manual_seed(config["seed"])
        require(torch.are_deterministic_algorithms_enabled(), "deterministic parent setup missing")
        load_start = time.perf_counter()
        active = max(1, math.ceil(config["logical_cells"] * config["active_fraction"]))
        count = max(64, active)
        distinct = max(1, round(count * (1 - config["input_repeat_fraction"])))
        generator = torch.Generator().manual_seed(config["seed"] + 1)
        raw = torch.randint(0, 249, (distinct, 8), generator=generator)
        source_sha = [hashlib.sha256(t.numpy().tobytes()).hexdigest() for t in raw]
        require(len(set(source_sha)) == distinct, "fixture input hash collision")
        sample_ids = (torch.arange(count) % distinct)[torch.randperm(count, generator=generator)]
        cell_ids = torch.arange(count) % active
        questions = cell_ids % {"low": 8, "medium": 4, "high": 1}[config["task_similarity"]]
        encoder, heads = Encoder().eval(), Heads(config["logical_cells"]).eval()
        stem_sha = weights_digest(encoder)
        all_weights = digest([stem_sha, weights_digest(heads)])
        pipeline = ["controlled-group", "one-principal", "research-purpose", 1, 1, stem_sha, "fp32", "token-mean-mlp-v1"]
        pipeline_sha = digest(pipeline)
        workload = digest([source_sha, sample_ids.tolist(), cell_ids.tolist(), questions.tolist(), "cohort_burst"])
        load_seconds = time.perf_counter() - load_start
        cache, hits, coalesced, measured, output_bytes = {}, 0, 0, [], bytearray()
        batch = 1 if config["arm"] == "no_change_serial" else 32
        wall0, cpu0 = time.perf_counter(), time.process_time()
        with torch.inference_mode():
            for lo in range(0, count, batch):
                ids = sample_ids[lo:lo + batch]
                qs, cells = questions[lo:lo + batch], cell_ids[lo:lo + batch]
                if config["arm"] == "shared_features_heads":
                    # Scope/model/source identity stays complete; do not re-SHA the same
                    # already-bound tuple for every logical consumer.
                    keys = [(pipeline_sha, source_sha[int(i)]) for i in ids]
                    pending = {}
                    for key, index in zip(keys, ids):
                        if key in cache:
                            hits += 1
                        elif key in pending:
                            coalesced += 1
                        else:
                            pending[key] = int(index)
                    if pending:
                        encoded = encoder(raw[list(pending.values())])
                        for key, value in zip(pending, encoded):
                            cache[key] = value
                    features = torch.stack([cache[key] for key in keys])
                else:
                    joint = torch.cat((raw[ids], (qs + 249).unsqueeze(1)), 1)
                    features = encoder(joint)
                output = heads(features, qs, cells)
                require(bool(torch.isfinite(output).all()), "nonfinite observed output")
                output_bytes.extend(output.contiguous().numpy().tobytes())
                # All requests were admitted at the SAME cohort start, including
                # those waiting for earlier batches. Never divide batch time by N.
                measured.extend([(time.perf_counter() - wall0) * 1000] * len(ids))
        elapsed, cpu = time.perf_counter() - wall0, time.process_time() - cpu0
        peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024  # Linux KiB.
        result = {"schema": "hepta.four-gate-compute.v1", **config,
                  "implementation_profile": "scoped-key-tuple-v2",
                  "status": "controlled_cpu_tensors_executed", "requests": count,
                  "unique_admitted_inputs": distinct, "ticked_cell_ids": [f"cell-{i}" for i in range(active)],
                  "workload_digest": workload, "encoder_pipeline_digest": pipeline_sha, "weights_digest": all_weights,
                  "encoded_samples": encoder.samples, "encoder_batch_calls": encoder.calls,
                  "encoded_tokens": encoder.tokens, "cache_hits": hits, "inflight_coalesced": coalesced,
                  "request_latencies_ms": measured, "arrival_profile": "cohort_burst",
                  "wall_seconds": elapsed, "cpu_seconds": cpu, "load_wall_seconds_excluded_from_request_latency": load_seconds,
                  "peak_rss_bytes": peak_rss, "gpu_seconds": None, "energy_joules": None,
                  "isolated_process_measurement": True, "output_digest": hashlib.sha256(output_bytes).hexdigest(),
                  "encoder_parameters": sum(p.numel() for p in encoder.parameters()),
                  "head_inventory_parameters": sum(p.numel() for p in heads.parameters()),
                  "actual_distinct_encoder_objects": 1, "random_untrained_encoder": True,
                  "pretrained_model_executed": False, "joint_to_shared_prediction_equivalence_claimed": False,
                  "production_promotion_permitted": False}
        connection.send({"ok": True, "result": result})
    except Exception as exc:
        connection.send({"ok": False, "error": type(exc).__name__ + ": " + str(exc), "config": config})
    finally:
        connection.close()


def measure_one(config, timeout=120):
    require(sys.platform.startswith("linux") and not torch.cuda.is_initialized(), "isolated probe requires CPU/Linux")
    context = mp.get_context("fork")  # Research only; native-thread warnings are not suppressed.
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=worker, args=(child, config))
    process.start()
    child.close()
    try:
        if not parent.poll(timeout):
            process.terminate()
            process.join(10)
            raise RuntimeError("compute child timed out; no invented samples")
        result = parent.recv()
        process.join(10)
        require(process.exitcode == 0 and result.get("ok") is True, "compute child failed: " + str(result))
        return result["result"]
    finally:
        parent.close()
        if process.is_alive():
            process.kill()
            process.join()


def run(output, full=True):
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    plan = default_plan()
    fingerprint = validate_plan(plan)
    write_once(output / "plan.json", plan)
    env = {"python": sys.version, "torch": torch.__version__, "platform": platform.platform(),
           "logical_cpus": os.cpu_count(), "threads": 1, "cuda_available": torch.cuda.is_available(),
           "local_session_nonce": os.urandom(16).hex(), "pretrained_weights_loaded": False}
    write_once(output / "environment.json", env)
    combinations = list(itertools.product(plan["scales"], plan["active_fractions"], plan["input_repeat_fractions"],
                                         plan["task_similarity"], range(plan["compute_repetitions"])))
    if not full:
        combinations = [(64, 1., fraction, "high", 0) for fraction in (0., .9)]
    stream_path = output / "observations.jsonl"
    with stream_path.open("xb") as stream:
        for i, (scale, active, repeat, similarity, repetition) in enumerate(combinations):
            arms = list(COMPUTE_ARMS)
            random.Random(plan["seed"] + i).shuffle(arms)
            for arm in arms:
                config = {"logical_cells": scale, "active_fraction": active, "input_repeat_fraction": repeat,
                          "task_similarity": similarity, "repetition": repetition, "arm": arm,
                          "seed": plan["seed"] + repetition, "plan_digest": fingerprint,
                          "host_session_digest": digest(env), "execution_id": f"cohort-{i}/{arm}"}
                try:
                    result = measure_one(config)
                except Exception as exc:
                    write_once(output / f"FAILED-{i}-{arm}.json", {"error": str(exc), "config": config,
                                                                 "production_promotion_permitted": False})
                    raise
                stream.write(canonical(result) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
            if (i + 1) % 12 == 0:
                print(f"measured {i + 1}/{len(combinations)} paired cohorts", flush=True)
    review = review_compute(read_jsonl(stream_path), plan)
    review["controlled_cpu_only"] = True
    write_once(output / "compute-review.json", review)
    return review


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--smoke", action="store_true", help="six actual executions; does not satisfy matrix coverage")
    args = parser.parse_args()
    result = run(args.output, full=not args.smoke)
    print(canonical({k: result[k] for k in ("observed_cohorts", "required_cohorts", "matrix_complete", "budget_precheck")}).decode())
