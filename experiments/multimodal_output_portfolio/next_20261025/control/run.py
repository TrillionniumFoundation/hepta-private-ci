"""Actual paired policy execution with fresh versus delayed draft feedback."""

import argparse
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np
import torch

from ...abc_followup.control.features import ExactFeatureCache
from ...abc_next.compact_tree import scores
from ...abc_next.sensor_run import load_sensor
from ...abc_next.value import features, load_controller
from ...abc_recovery.base_recovery import file_sha, write_json
from ...abc_recovery.control import PLANS
from ...abc_recovery.emission import output_digests
from ...abc_recovery.runtime import ACTIONS, initialize, public_digest, public_frame, transition
from ...abc_recovery.trees import stable_seed
from ...v6.data import Observation, Target
from ...v7.data import VIEWS, make_batch
from ...v7.evaluation import load_reward
from ...v7.sources import load_roles
from ...closure_20261025.control.registry import load_model
from ...closure_20261025.control.rollout import PAYLOAD_SIZE, decode, emit_json
from .compiled import CompiledTeacher


POLICIES = ("cached_teacher", "compiled_teacher", "fresh_feedback", "stale_feedback",
            "strong_nonfeedback", "fixed_allocation")


def payload(pixels, tokens):
    return np.packbits(pixels.to(torch.uint8).numpy().reshape(-1)).tobytes() + tokens.to(torch.uint8).numpy().tobytes()


def persist(media, raw):
    if len(raw) != PAYLOAD_SIZE:
        raise ValueError("Incorrect lossless media size")
    offset = media.seek(0, os.SEEK_END)
    media.write(raw); media.flush(); os.fsync(media.fileno())
    media.seek(offset)
    if media.read(PAYLOAD_SIZE) != raw:
        raise ValueError("Actual media failed durable readback")
    return {"offset": offset, "sha256": hashlib.sha256(raw).hexdigest()}


@torch.inference_mode()
def moments(teacher, full, remaining):
    value = (teacher.one if remaining == 1 else teacher.two)(features(full, teacher.mode))
    if not torch.isfinite(value).all() or not (value > 0).all():
        raise ValueError("Invalid conditional moments")
    if remaining == 1:
        value = value.clone(); value[:, 1] = float("inf")
    return value


@torch.inference_mode()
def request(model, observation, teacher, compiled, sensor, *, policy, reference,
            seed, case, view, draw, evaluation, media, commitments):
    if type(observation) is not Observation or policy not in POLICIES:
        raise ValueError("Public observation and registered policy required")
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    row = dict(seed=seed, case=case, view=view, draw=draw, policy=policy, status="failed")
    work, path, decisions = Counter(), [], []
    run, initial_features, calibration = None, None, None
    try:
        run = initialize(model, observation, generator=torch.Generator().manual_seed(
            stable_seed(evaluation["initial_namespace"], seed, case, view)))
        cache = (compiled.cache(model, sensor, observation, work) if policy == "compiled_teacher"
                 else ExactFeatureCache(model, sensor, observation, work))
        plan = None
        if policy == "fixed_allocation" or (policy == "strong_nonfeedback" and reference["selected_nonfeedback"] == "fixed"):
            plan = ("refine_image", "refine_text")
        elif policy == "strong_nonfeedback" and reference["selected_nonfeedback"] == "static":
            plan = PLANS[reference["static_plan_index"]]
        while not run.done:
            frame = public_frame(run)
            full = cache.read(frame)
            if initial_features is None:
                initial_features = full.clone()
            detail = {"remaining": frame.remaining, "public_sha256": public_digest(frame)}
            value = None
            if policy == "compiled_teacher":
                chosen = int(compiled.choose(full, frame.remaining, work)[0])
            elif policy in ("fresh_feedback", "stale_feedback"):
                # Both branches really receive and compute on the actual fresh
                # draft. The delayed branch chooses using its initial draft
                # while retaining current latent state and remaining horizon.
                stale = torch.cat((full[:, :384], initial_features[:, 384:762], full[:, -1:]), 1)
                fresh_value = moments(teacher, full, frame.remaining)
                stale_value = moments(teacher, stale, frame.remaining)
                value = fresh_value if policy == "fresh_feedback" else stale_value
                chosen = int(value.argmin(-1)[0])
                work["teacher_calls"] += 2
                detail.update({"fresh_action": int(fresh_value.argmin(-1)[0]),
                               "stale_action": int(stale_value.argmin(-1)[0]),
                               "observed_draft_changed": not torch.equal(full[:, 384:762], initial_features[:, 384:762]),
                               "new_draft_delivered": True, "both_heads_actually_executed": True,
                               "selection_uses_new_draft": policy == "fresh_feedback"})
            elif policy in ("strong_nonfeedback", "fixed_allocation"):
                if plan is None:
                    plan = PLANS[int(teacher.choose_plan(full)[0])]
                    work["route_head_calls"] += 1
                chosen = ACTIONS.index(plan[len(path)]) if len(path) < len(plan) else 0
                detail["initial_plan"] = list(plan)
            else:
                value = moments(teacher, full, frame.remaining)
                chosen = int(value.argmin(-1)[0]); work["teacher_calls"] += 1
            action = ACTIONS[chosen]
            if frame.remaining == 1 and policy in ("cached_teacher", "fresh_feedback", "stale_feedback"):
                calibration = payload(frame.pixels, frame.tokens)
                detail["predicted_action_minus_stop_moment"] = float(value[0, chosen] - value[0, 0])
            detail.update({"action": action, "decision_index": len(decisions)})
            emit_json(commitments, {**row, **detail})
            decisions.append(detail)
            # No future decoder innovation exists before the durable choice.
            future = torch.Generator().manual_seed(stable_seed(evaluation["future_namespace"], seed, case, view, draw, tuple((*path, action))))
            run = transition(model, run, action, generator=future)
            if action != "stop": path.append(action)
            if len(decisions) > 2: raise ValueError("Finite H2 budget exceeded")
        raw = payload(run.pixels, run.tokens)
        saved = persist(media, raw)
        p, t, _ = decode(raw)
        if not torch.equal(run.pixels, p) or not torch.equal(run.tokens, t):
            raise ValueError("Generated media does not roundtrip")
        row.update({"status": "completed", "terminal": saved,
                    "output_sha256": output_digests(run.pixels, run.tokens)[0]})
    except Exception as error:
        row["error"] = {"type": type(error).__name__, "message": str(error)}
    if run is not None:
        for entry in run.ledger: work.update(entry.get("work", {}))
    row.update({"wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
                "path": path, "decisions": decisions, "work": dict(work)})
    # Diagnostic preservation is outside request cost but inside whole process.
    if calibration is not None: row["calibration_stop"] = persist(media, calibration)
    return row


def load_corpus(asset, spec, protocol):
    if spec["source"]["kind"] == "historical_development":
        return load_roles(asset / "abc2-assets/mnist", asset / "abc2-runs/source-recovery-001/source-manifest.json", roles=("forecast_calibration",))
    from ..sources import load_registered
    return load_registered(Path(spec["source"]["cache"]), Path(spec["source"]["allocation"]), protocol, "control")


def run(asset, protocol, output):
    spec = json.loads(protocol.read_text())
    for path, digest in spec["frozen_sha256"].items():
        if file_sha(Path(path)) != digest: raise ValueError("Frozen file differs: " + path)
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    write_json(output / "registration.json", {"protocol_sha256": file_sha(protocol), "started_unix_ns": time.time_ns(), "spec": spec})
    corpus = load_corpus(asset, spec, protocol)
    source = spec["source"]; count, start = source["pairs"], source["offset"]
    public, targets, identities = {}, {}, {}
    for view in VIEWS:
        batch = make_batch(corpus, source["role"], count, stable_seed(spec["evaluation"]["observation_namespace"], start, count), view=view, offset=start)
        for i in range(count):
            public[view, i] = Observation(*(getattr(batch.observation, k)[i:i + 1].clone() for k in ("pixels", "mask", "text_tokens")))
            targets[view, i] = Target(*(getattr(batch.target, k)[i:i + 1].clone() for k in ("pixels", "text_tokens", "labels")))
            identities[i] = batch.source_ids[i]
    sensor = load_sensor(asset / "abc3-runs/public-sensor-001/sensor.pt")
    judges = {name: load_reward(asset / path, expected_file_sha256=sha)[0] for name, path, sha in (
        ("primary", "abc2-runs/base-recovery-001/reward-observer.pt", "8cfca1b0cd0a69bcfcc6a9d34d0a672c07c28f3342823ef8a3f6763e9430a003"),
        ("secondary", "abc2-runs/qualification-001/secondary-observer.pt", "b0851ce56189d159b53449cfc914cf84b9b63e82a6f0050228096666752595fe"))}
    references = {r["seed"]: r for r in json.loads((Path(__file__).resolve().parents[2] / "abc_followup/control/PROTOCOL-v2.json").read_text())["controllers"]}
    rows, loads, group = [], [], 0
    rng = np.random.default_rng(spec["evaluation"]["order_seed"])
    with (output / "media.bin").open("x+b") as media, gzip.open(output / "commitments.jsonl.gz", "xt", compresslevel=3) as commitments, gzip.open(output / "requests.jsonl.gz", "xt", compresslevel=3) as log:
        for seed in spec["seeds"]:
            started = time.perf_counter_ns()
            snapshot = load_model(asset, seed)
            teacher = load_controller(asset / f"abc3-runs/controllers-001/seed-{seed}/output_ndu/controller.pt")
            compile_started = time.perf_counter_ns()
            compiled = CompiledTeacher(snapshot._model, sensor, teacher)
            graph_folder = output / f"compiled-seed-{seed}"; graph_folder.mkdir()
            for name in ("heads", "readers", "summary"):
                torch.jit.save(getattr(compiled, name), graph_folder / (name + ".pt"))
            loads.append({"seed": seed, "wall_ns": time.perf_counter_ns() - started, "compile_and_save_wall_ns": time.perf_counter_ns() - compile_started,
                          "graph_sha256": {p.name: file_sha(p) for p in graph_folder.iterdir()}})
            for view in VIEWS:
                for case in range(count):
                    for draw in range(spec["draws"]):
                        order = rng.permutation(spec["policies"]).tolist()
                        for order_index, policy in enumerate(order):
                            row = request(snapshot._model, public[view, case], teacher, compiled, sensor,
                                policy=policy, reference=references[seed], seed=seed, case=case, view=view, draw=draw,
                                evaluation=spec["evaluation"], media=media, commitments=commitments)
                            row.update({"source_ids": identities[case], "group": group, "order_index": order_index})
                            rows.append(row); emit_json(log, row)
                        group += 1
                print(json.dumps({"seed": seed, "view": view, "requests": len(rows), "failures": sum(r["status"] != "completed" for r in rows)}), flush=True)
            snapshot.verify_integrity()
    scoring = time.perf_counter_ns()
    with (output / "media.bin").open("rb") as media, gzip.open(output / "scored.jsonl.gz", "xt", compresslevel=3) as log:
        for row in rows:
            row["scores"] = {}
            for label, key in (("scores", "terminal"), ("stop_scores", "calibration_stop")):
                if key not in row: continue
                saved = row[key]; media.seek(saved["offset"]); raw = media.read(PAYLOAD_SIZE)
                if hashlib.sha256(raw).hexdigest() != saved["sha256"]: raise ValueError("Closed media changed")
                pixels, _, captions = decode(raw)
                values = scores(judges, pixels, captions, targets[row["view"], row["case"]])
                row[label] = {name: {k: float(value[0]) for k, value in metrics.items()} for name, metrics in values.items()}
            log.write(json.dumps({k: row[k] for k in ("seed", "case", "view", "draw", "policy", "status", "scores", "stop_scores") if k in row}, sort_keys=True, allow_nan=False) + "\n")
        log.flush(); os.fsync(log.fileno())
    expected = count * len(VIEWS) * spec["draws"] * len(spec["seeds"]) * len(spec["policies"])
    if len(rows) != expected or any(file_sha(Path(p)) != h for p, h in spec["frozen_sha256"].items()):
        raise ValueError("Source, model, implementation or census changed")
    write_json(output / "completion.json", {"status": "completed", "requests": len(rows), "failures": sum(r["status"] != "completed" for r in rows),
        "source_pairs": count, "new_source_pairs": count if source["kind"] != "historical_development" else 0,
        "model_loads": loads, "scoring_wall_ns": time.perf_counter_ns() - scoring,
        "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
        "files_sha256": {p.name: file_sha(p) for p in output.iterdir() if p.is_file()}, "completed_unix_ns": time.time_ns()})


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--asset-root", type=Path, required=True)
    p.add_argument("--protocol", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args(); run(a.asset_root, a.protocol, a.output)
