"""Same-source quality and actual durable-request cost, without offline oracle access."""

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import platform
import struct
import time
import traceback

import torch

from ...abc_next.compact_tree import scores
from ...abc_next.observability import input_evidence, observed_features
from ...abc_next.sensor_run import load_sensor
from ...abc_next.settings import CACHE, FIXED_PLAN, MANIFEST, RUNS, SEEDS, SENSOR, model_path, observers
from ...abc_next.timing import deserialize_terminal, serialize_terminal
from ...abc_next.value import load_controller
from ...abc_recovery.base_recovery import file_sha, write_json
from ...abc_recovery.control import PLANS
from ...abc_recovery.runtime import ACTIONS, initialize, public_frame, transition
from ...abc_recovery.trees import stable_seed
from ...v6.data import Observation, Target
from ...v6.neural import parameter_hash
from ...v7.data import VIEWS, make_batch
from ...v7.snapshot import Snapshot
from ...v7.sources import load_roles
from .features import ExactFeatureCache, compact_frame
from .value import load


POLICIES = ("reference", "old_feedback", "cached_feedback", "compact_feedback")


def owner_rng(seed, case, view, scenario, path):
    return torch.Generator().manual_seed(stable_seed("abc4-control-selected-generation", seed, case, view, scenario, tuple(path)))


def order(group):
    start = group % len(POLICIES)
    return POLICIES[start:] + POLICIES[:start]


def append_durable(stream, payload):
    offset = stream.seek(0, os.SEEK_END)
    stream.write(struct.pack("<Q", len(payload)))
    stream.write(payload)
    stream.flush(); os.fsync(stream.fileno())
    stream.seek(offset)
    length = struct.unpack("<Q", stream.read(8))[0]
    reopened = stream.read(length)
    if len(reopened) != len(payload) or reopened != payload:
        raise ValueError("Durable media readback differs")
    return offset, length, reopened


@torch.inference_mode()
def request(model, observation, policy, *, old, compact, sensor, reference, static_index,
            seed, case, view, scenario, media):
    """Only public observation and frozen policies enter an online request."""
    if policy not in POLICIES or not isinstance(observation, Observation) or len(observation.pixels) != 1:
        raise ValueError("One registered public request required")
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    work, path, decisions = Counter(), [], []
    row = {"policy": policy, "seed": seed, "case": case, "view": view, "scenario": scenario,
           "status": "request_failed", "error": None}
    run, cache, evidence, planned = None, None, None, None
    try:
        run = initialize(model, observation, generator=owner_rng(seed, case, view, scenario, ()))
        if policy == "reference" and reference in {"fixed", "static"}:
            planned = FIXED_PLAN if reference == "fixed" else PLANS[static_index]
        while not run.done:
            frame = public_frame(run)
            if planned is not None:
                action = planned[len(path)] if len(path) < len(planned) else "stop"
            elif policy == "compact_feedback":
                action = ACTIONS[int(compact.choose(compact_frame(frame), run.remaining)[0])]
                work["compact_head_calls"] += 1
            else:
                if policy == "old_feedback":
                    if evidence is None:
                        evidence = input_evidence(sensor, observation, work)
                    feature = observed_features(model, frame, sensor=sensor, evidence=evidence, work=work)
                else:
                    if cache is None:
                        cache = ExactFeatureCache(model, sensor, observation, work)
                    feature = cache.read(frame)
                if policy == "reference":
                    if reference != "one_shot":
                        raise ValueError("Unknown frozen reference")
                    planned = PLANS[int(old.choose_plan(feature)[0])]
                    action = planned[0] if planned else "stop"
                    work["route_head_calls"] += 1
                else:
                    action = ACTIONS[int(old.choose(feature, run.remaining)[0])]
                    work["old_value_head_calls"] += 1
            decisions.append(action)
            run = transition(model, run, action, generator=owner_rng(seed, case, view, scenario, (*path, action)))
            if action != "stop":
                path.append(action)
            if len(decisions) > 2:
                raise ValueError("Finite-horizon request exceeded H2")
        payload, payload_hash, output_hash = serialize_terminal(run.pixels, run.tokens)
        offset, length, persisted = append_durable(media, payload)
        deserialize_terminal(persisted, payload_hash)
        row.update({"status": "completed", "payload_sha256": payload_hash, "output_sha256": output_hash,
                    "media_offset": offset, "media_length": length, "serialized_bytes": len(payload)})
    except Exception as error:
        row["error"] = {"type": type(error).__name__, "message": str(error)}
    row.update({"request_wall_ns": time.perf_counter_ns() - wall, "request_cpu_ns": time.process_time_ns() - cpu,
                "completed_path": path, "decisions": decisions})
    ledger = run.ledger if run is not None else ()
    for entry in ledger:
        work.update(entry.get("work", {}))
    row["work"] = dict(work)
    row["runtime_ledger_sha256"] = hashlib.sha256(json.dumps(ledger, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return row


def phase_timer(phases, name, wall, cpu):
    phases[name] = {"wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu}


def run(protocol_path, output):
    from .protocol import validate
    spec = validate(protocol_path)
    output.mkdir(parents=True, exist_ok=False)
    total_wall, total_cpu = time.perf_counter_ns(), time.process_time_ns()
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    phases, rows, model_loads = {}, [], []
    write_json(output / "registration.json", {"schema": "hepta.abc4.control-final-launch.v1",
        "started_unix_ns": time.time_ns(), "protocol_sha256": file_sha(protocol_path),
        "output": str(output), "profile": spec["profile"],
        "environment": {"python": platform.python_version(), "torch": torch.__version__, "platform": platform.platform(),
                        "cpu_count": os.cpu_count(), "threads": 1, "loadavg": list(os.getloadavg())}})
    media_path = output / "actual-terminal-media.bin"
    try:
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        corpus = load_roles(CACHE, MANIFEST, roles=("test",))
        public, targets, source_ids = {}, {}, {}
        start, count = spec["profile"]["pair_start"], spec["profile"]["pair_count"]
        for view in VIEWS:
            batch = make_batch(corpus, "test", count, stable_seed("abc4-control-observation", "test", start, count), view=view, offset=start)
            for index in range(count):
                case = start + index
                public[view, case] = Observation(*(x[index:index + 1].clone() for x in
                    (batch.observation.pixels, batch.observation.mask, batch.observation.text_tokens)))
                targets[view, case] = Target(*(x[index:index + 1].clone() for x in
                    (batch.target.pixels, batch.target.text_tokens, batch.target.labels)))
                source_ids[case] = batch.source_ids[index]
        sensor, judges = load_sensor(SENSOR), observers()
        hashes = {name: parameter_hash(value) for name, value in {"sensor": sensor, **judges}.items()}
        phase_timer(phases, "source_and_reader_setup", wall, cpu)
        group = 0
        with media_path.open("x+b") as media, (output / "clock-rows.jsonl").open("x") as log:
            for entry in spec["controllers"]:
                seed = entry["seed"]
                wall, cpu = time.perf_counter_ns(), time.process_time_ns()
                snapshot = Snapshot.load(model_path(seed, "output_ndu"), expected_file_sha256=entry["model_sha256"])
                old = load_controller(Path(entry["old_controller_file"]))
                compact = load(Path(entry["compact_file"]))
                model_loads.append({"seed": seed, "wall_ns": time.perf_counter_ns() - wall,
                                    "cpu_ns": time.process_time_ns() - cpu, "loadavg": list(os.getloadavg())})
                for view in VIEWS:
                    for case in range(start, start + count):
                        for scenario in range(spec["profile"]["scenarios"]):
                            for position, policy in enumerate(order(group)):
                                row = request(snapshot._model, public[view, case], policy, old=old, compact=compact, sensor=sensor,
                                    reference=entry["selected_nonfeedback"], static_index=entry["static_plan_index"],
                                    seed=seed, case=case, view=view, scenario=scenario, media=media)
                                row.update({"source_ids": source_ids[case], "group": group, "order_position": position,
                                    "selected_candidate": entry["selected_candidate"], "selected_nonfeedback": entry["selected_nonfeedback"]})
                                rows.append(row)
                                log.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
                            group += 1
                    log.flush(); os.fsync(log.fileno())
                    print(json.dumps({"phase": "requests", "seed": seed, "view": view, "requests": len(rows),
                                      "failures": sum(r["status"] != "completed" for r in rows)}), flush=True)
                snapshot.verify_integrity()
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        with media_path.open("rb") as media, (output / "scored-rows.jsonl").open("x") as log:
            for row in rows:
                sw, sc = time.perf_counter_ns(), time.process_time_ns()
                row["observer_scores"], row["required_output_complete"] = {}, False
                if row["status"] == "completed":
                    try:
                        media.seek(row["media_offset"])
                        length = struct.unpack("<Q", media.read(8))[0]
                        if length != row["media_length"]:
                            raise ValueError("Closed media index differs")
                        pixels, _, captions = deserialize_terminal(media.read(length), row["payload_sha256"])
                        row["required_output_complete"] = bool(captions[0].strip())
                        values = scores(judges, pixels, captions, targets[row["view"], row["case"]])
                        row["observer_scores"] = {name: {key: float(value[0]) for key, value in metrics.items()}
                                                  for name, metrics in values.items()}
                    except Exception as error:
                        row["status"] = "offline_scoring_failed"
                        row["error"] = {"type": type(error).__name__, "message": str(error)}
                row["scoring_wall_ns"], row["scoring_cpu_ns"] = time.perf_counter_ns() - sw, time.process_time_ns() - sc
                log.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
            log.flush(); os.fsync(log.fileno())
        phase_timer(phases, "closed_media_readback_and_scoring", wall, cpu)
        if hashes != {name: parameter_hash(value) for name, value in {"sensor": sensor, **judges}.items()}:
            raise ValueError("Frozen sensor or outcome observers changed")
        validate(protocol_path)
        from .analysis import aggregate
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        summary = aggregate(rows, spec)
        phase_timer(phases, "analysis", wall, cpu)
        summary.update({"protocol_sha256": file_sha(protocol_path), "launch_sha256": file_sha(output / "registration.json"),
            "actual_media_sha256": file_sha(media_path), "clock_rows_sha256": file_sha(output / "clock-rows.jsonl"),
            "scored_rows_sha256": file_sha(output / "scored-rows.jsonl"), "phases": phases, "resident_loads": model_loads,
            "runner_wall_ns": time.perf_counter_ns() - total_wall, "runner_cpu_ns": time.process_time_ns() - total_cpu})
        write_json(output / "summary.json", summary)
        print(json.dumps({"phase": "completed", "requests": len(rows), "status": summary["status"]}), flush=True)
    except BaseException as error:
        write_json(output / "failure.json", {"type": type(error).__name__, "message": str(error),
            "traceback": traceback.format_exc(), "attempts": len(rows), "phases": phases})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(); run(args.protocol, args.output)
