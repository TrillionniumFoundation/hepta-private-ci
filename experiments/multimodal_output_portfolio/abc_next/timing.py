"""Frozen resident serial timing with actual selected paths and local media.

This module never fits a policy. CLI execution requires the final protocol's
exact timing registration before materializing test sources. Synthetic tests do
not use registered sources or trained checkpoints.
"""

import argparse
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import sys
import time
import traceback
import zipfile

import numpy as np
import torch

from ..abc_recovery.base_recovery import file_sha, write_json
from ..abc_recovery.control import PLANS, load_feedback
from ..abc_recovery.runtime import ACTIONS, initialize, public_features, public_frame, transition
from ..abc_recovery.trees import stable_seed
from ..v6.data import Observation, Target
from ..v6.neural import parameter_hash
from ..v7.data import VIEWS, make_batch
from ..v7.snapshot import Snapshot
from ..v7.sources import load_roles
from .compact_tree import decode_media, encode_media, scores
from .observability import input_evidence, observed_features
from .sensor_run import load_sensor
from .settings import ARMS, CACHE, FIXED_PLAN, MANIFEST, OLD, REPO, SEEDS, SENSOR, model_path, observers, resources, source_pins
from .value import load_controller


POLICIES = ("fixed", "static", "one_shot", "feedback", "legacy")
TIMING_PROFILE = {
    "schema": "hepta.abc-next.resident-timing-profile.v1",
    "source_role": "test", "pair_start": 0, "pair_count": 16,
    "views": list(VIEWS), "scenarios": 2, "training_seeds": list(SEEDS),
    "arms": list(ARMS), "policies": list(POLICIES), "cpu_threads": 2,
    "policy_order": "cyclic rotation by global seed/arm/view/case/scenario group ordinal",
    "owner_stream": "training_seed,case,view,scenario,committed_path; excludes arm and policy",
    "observation_stream": "abc-next-timing-observation,test,0,16; shared across views, arms, seeds and scenarios",
    "main_request_timer": "owner RNG setup, public sensor if used, encoder, actual chosen transitions, policy decisions, lossless terminal NPZ memory serialization and payload SHA256",
    "main_request_excludes": ["model/policy loading", "source/observation construction", "disk archive append and fsync", "offline scoring", "analysis"],
    "additional_costs": "archive append per request; final archive close and fsync; closed-archive readback and scoring per row; setup and total process phases",
    "failure_rule": "retain every attempted row and actual cost; no dropped outliers; unavailable quality blocks that condition/observer's quality inference",
    "raw_media": "local ZIP_STORED container of per-request lossless NPZ bytes; no raw data in Git",
    "bootstrap": {"replicates": 4000, "seed": 2026102507, "confidence": .95,
                  "unit": "paired crossed source and training_seed, retaining all views/scenarios"},
    "quality_scope": "descriptive timing cohort only, not a replacement for main 512-source test",
}


def legacy_path(seed, arm):
    return OLD / f"control-001/seed-{seed}/{arm}/policies/feedback.pt"


def timing_registration(controllers_dir):
    """Metadata-only block for insertion into the final frozen protocol."""
    pins = source_pins()
    for relative in ("abc_next/timing.py", "abc_next/timing_analysis.py", "abc_next/timing_tests.py",
                     "abc_recovery/statistics.py", "abc_recovery/control.py", "abc_recovery/base_recovery.py"):
        path = Path(__file__).parent.parent / relative
        pins[str(path.relative_to(REPO))] = file_sha(path)
    return {"profile": TIMING_PROFILE,
        "controllers_result_sha256": file_sha(Path(controllers_dir) / "result.json"),
        "legacy_policy_sha256": {f"{seed}/{arm}": file_sha(legacy_path(seed, arm)) for seed in SEEDS for arm in ARMS},
        "source_sha256": pins}


def owner_rng(seed, case, view, scenario, path):
    return torch.Generator().manual_seed(stable_seed("abc-next-timing-generation", seed, case, view, scenario, tuple(path)))


def policy_order(group_ordinal):
    offset = group_ordinal % len(POLICIES)
    return POLICIES[offset:] + POLICIES[:offset]


def serialize_terminal(pixels, tokens):
    """Return actual compressed bytes and hashes, without output repair."""
    bits, token_rows, hashes = encode_media(pixels, tokens)
    buffer = io.BytesIO()
    np.savez_compressed(buffer, pixels_bits=bits, tokens=token_rows, output_sha256=hashes)
    raw = buffer.getvalue()
    return raw, hashlib.sha256(raw).hexdigest(), [x.decode() for x in hashes]


def deserialize_terminal(raw, expected_sha):
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError("Terminal NPZ payload checksum differs")
    with np.load(io.BytesIO(raw), allow_pickle=False) as saved:
        pixels, tokens, captions = decode_media(saved["pixels_bits"], saved["tokens"], saved["output_sha256"])
    if len(pixels) != 1:
        raise ValueError("Resident request must have one actual terminal output")
    return pixels, tokens, captions


@torch.inference_mode()
def request(model, observation, policy_name, *, controller, legacy, sensor, static_plan_index,
            seed, case, view, scenario):
    """Public-input-only request; private targets and observers are not arguments."""
    if policy_name not in POLICIES or not isinstance(observation, Observation) or len(observation.pixels) != 1:
        raise ValueError("Expected one registered public request")
    if policy_name == "static" and (type(static_plan_index) is not int or not 0 <= static_plan_index < len(PLANS)):
        raise ValueError("Invalid frozen static plan")
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    run, evidence, payload, ledger = None, None, None, ()
    work, path, decisions, serialization = Counter(), [], [], {}
    status, error, stage = "completed", None, "initialize"
    try:
        run = initialize(model, observation, generator=owner_rng(seed, case, view, scenario, ()))
        planned = None
        if policy_name in {"fixed", "static"}:
            planned = FIXED_PLAN if policy_name == "fixed" else PLANS[static_plan_index]
            work["static_route_lookups"] += 1
        while not run.done:
            stage = "public_policy"
            if policy_name == "legacy":
                action = legacy.action(model, public_frame(run), work)
            elif planned is None:
                frame = public_frame(run)
                if controller.mode == "enriched":
                    if evidence is None:
                        evidence = input_evidence(sensor, observation, work)
                    features = observed_features(model, frame, sensor=sensor, evidence=evidence, work=work)
                else:
                    base = public_features(model, frame, work=work)
                    # Controller.base ignores these columns; no sensor is run.
                    features = torch.cat((base[:, :-1], torch.zeros(1, 90), base[:, -1:]), 1)
                    work["base_ignored_feature_padding_examples"] += 1
                if policy_name == "one_shot":
                    planned = PLANS[int(controller.choose_plan(features)[0])]
                    work["route_head_calls"] += 1
                    work["route_head_examples"] += 1
                    action = planned[0] if planned else "stop"
                else:
                    action = ACTIONS[int(controller.choose(features, run.remaining)[0])]
                    work["critic_calls"] += 1
                    work["critic_examples"] += 1
            else:
                action = planned[len(path)] if len(path) < len(planned) else "stop"
            if action not in ACTIONS:
                raise ValueError("Policy selected an unregistered action")
            decisions.append(action)
            stage = "actual_transition"
            proposal = (*path, action)
            run = transition(model, run, action, generator=owner_rng(seed, case, view, scenario, proposal))
            if action != "stop":
                path.append(action)
            if len(decisions) > 2 or len(path) > 2:
                raise ValueError("The registered H2 request budget was exceeded")
        stage = "lossless_terminal_serialization"
        sw, sc = time.perf_counter_ns(), time.process_time_ns()
        payload, payload_sha, output_sha = serialize_terminal(run.pixels, run.tokens)
        serialization = {"serialization_wall_ns": time.perf_counter_ns() - sw,
                         "serialization_cpu_ns": time.process_time_ns() - sc,
                         "payload_sha256": payload_sha, "output_sha256": output_sha,
                         "serialized_bytes": len(payload)}
        ledger = run.ledger
    except Exception as failure:
        status = "request_failed"
        error = {"type": type(failure).__name__, "message": str(failure), "stage": stage}
        ledger = getattr(failure, "ledger", run.ledger if run is not None else ())
    wall_ns, cpu_ns = time.perf_counter_ns() - wall, time.process_time_ns() - cpu
    for entry in ledger:
        work.update(entry.get("work", {}))
    row = {"status": status, "error": error, "policy": policy_name, "seed": seed, "case": case,
        "view": view, "scenario": scenario, "completed_path": path, "decisions": decisions,
        "request_wall_ns": wall_ns, "request_cpu_ns": cpu_ns, "work": dict(work),
        "stream_identity_without_arm_or_policy": [seed, case, view, scenario],
        "runtime_ledger": list(ledger), **serialization}
    return row, payload


def _sum_phase(phases, name, wall, cpu):
    record = phases.setdefault(name, {"calls": 0, "wall_ns": 0, "cpu_ns": 0})
    record["calls"] += 1
    record["wall_ns"] += time.perf_counter_ns() - wall
    record["cpu_ns"] += time.process_time_ns() - cpu


def run(controllers_dir, freeze_path, output):
    output.mkdir(parents=True, exist_ok=False)
    total_wall, total_cpu = time.perf_counter_ns(), time.process_time_ns()
    phases, rows, archive = {}, [], None
    try:
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        freeze = json.loads(freeze_path.read_text())
        expected_timing, expected_resources = timing_registration(controllers_dir), resources()
        if freeze.get("timing") != expected_timing or freeze.get("resources") != expected_resources:
            raise ValueError("Timing code, resources or controller collection differ from final freeze")
        collection = json.loads((controllers_dir / "result.json").read_text())
        if collection.get("status") != "completed" or collection.get("schema") != "hepta.abc-next.controller-freeze.v1":
            raise ValueError("A completed frozen controller collection is required")
        entries = {(item["seed"], item["arm"]): item for item in collection["controllers"]}
        if len(entries) != len(collection["controllers"]) or set(entries) != {(s, a) for s in SEEDS for a in ARMS}:
            raise ValueError("Frozen controller collection has missing or duplicate models")
        for item in entries.values():
            if file_sha(Path(item["controller_file"])) != item["controller_sha256"]:
                raise ValueError("Frozen controller file changed")
            chosen = item["selection"]
            if type(chosen["static_plan_index"]) is not int or not 0 <= chosen["static_plan_index"] < len(PLANS) or chosen["selected_nonfeedback"] not in {"fixed", "static", "one_shot"}:
                raise ValueError("Unregistered nonfeedback selection")
        torch.set_num_threads(TIMING_PROFILE["cpu_threads"])
        write_json(output / "registration.json", {"schema": "hepta.abc-next.resident-timing-registration.v1",
            "frozen_protocol_sha256": file_sha(freeze_path), "timing": expected_timing,
            "resources": expected_resources, "registered_unix_ns": time.time_ns(),
            "test_outcomes_materialized_before_registration": False,
            "environment": {"python": sys.version, "torch": torch.__version__, "numpy": np.__version__,
                            "platform": platform.platform(), "cpu_count": os.cpu_count(),
                            "torch_threads": torch.get_num_threads(), "interop_threads": torch.get_num_interop_threads()}})
        corpus = load_roles(CACHE, MANIFEST, roles=("test",))
        public_inputs, targets, sources = {}, {}, {}
        for view in VIEWS:
            batch = make_batch(corpus, "test", 16, stable_seed("abc-next-timing-observation", "test", 0, 16), view=view, offset=0)
            for case in range(16):
                public_inputs[view, case] = Observation(*(x[case:case + 1].clone() for x in
                    (batch.observation.pixels, batch.observation.mask, batch.observation.text_tokens)))
                targets[view, case] = Target(*(x[case:case + 1].clone() for x in
                    (batch.target.pixels, batch.target.text_tokens, batch.target.labels)))
                sources[view, case] = batch.source_ids[case]
        sensor, judges = load_sensor(SENSOR), observers()
        sensor_hash = parameter_hash(sensor)
        judge_hashes = {name: parameter_hash(judge) for name, judge in judges.items()}
        _sum_phase(phases, "verification_and_source_setup", wall, cpu)
        archive_path = output / "terminal-media.zip"
        archive = zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_STORED)
        group = 0
        with (output / "clock-rows.jsonl").open("x") as clock_rows:
            for seed in SEEDS:
                for arm in ARMS:
                    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
                    snapshot = Snapshot.load(model_path(seed, arm), expected_file_sha256=expected_resources["model_sha256"][f"{seed}/{arm}"])
                    entry = entries[seed, arm]
                    controller, legacy = load_controller(Path(entry["controller_file"])), load_feedback(legacy_path(seed, arm))
                    if (controller.mode, controller.hidden) != (collection["architecture"]["mode"], collection["architecture"]["hidden"]):
                        raise ValueError("Controller architecture differs from frozen selection")
                    _sum_phase(phases, "resident_model_and_policy_load", wall, cpu)
                    for view in VIEWS:
                        for case in range(16):
                            for scenario in range(2):
                                for position, policy_name in enumerate(policy_order(group)):
                                    row, raw = request(snapshot._model, public_inputs[view, case], policy_name,
                                        controller=controller, legacy=legacy, sensor=sensor,
                                        static_plan_index=entry["selection"]["static_plan_index"],
                                        seed=seed, case=case, view=view, scenario=scenario)
                                    row.update({"arm": arm, "source_ids": sources[view, case],
                                        "group_ordinal": group, "order_position": position,
                                        "selected_nonfeedback": entry["selection"]["selected_nonfeedback"]})
                                    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
                                    if raw is not None:
                                        member = f"terminal/{len(rows):06d}.npz"
                                        archive.writestr(member, raw)
                                        row["media_member"] = member
                                    row.update({"archive_append_wall_ns": time.perf_counter_ns() - wall,
                                                "archive_append_cpu_ns": time.process_time_ns() - cpu})
                                    rows.append(row)
                                    clock_rows.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
                                group += 1
                    clock_rows.flush()
                    os.fsync(clock_rows.fileno())
                    snapshot.verify_integrity()
                    print(json.dumps({"phase": "resident_requests_completed", "seed": seed, "arm": arm,
                        "cumulative_requests": len(rows), "failures": sum(r["status"] != "completed" for r in rows)}), flush=True)
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        archive.close()
        with archive_path.open("rb") as stream:
            os.fsync(stream.fileno())
        archive = None
        _sum_phase(phases, "terminal_archive_close_and_fsync", wall, cpu)
        with zipfile.ZipFile(archive_path, "r") as saved, (output / "scored-rows.jsonl").open("x") as scored:
            for row in rows:
                wall, cpu = time.perf_counter_ns(), time.process_time_ns()
                row["observer_scores"], row["required_output_complete"] = {}, False
                if row["status"] == "completed":
                    try:
                        pixels, _, captions = deserialize_terminal(saved.read(row["media_member"]), row["payload_sha256"])
                        row["required_output_complete"] = bool(captions[0].strip())
                        values = scores(judges, pixels, captions, targets[row["view"], row["case"]])
                        for name, metrics in values.items():
                            row["observer_scores"][name] = {key: float(value[0]) for key, value in metrics.items()}
                    except Exception as failure:
                        row["status"] = "offline_scoring_failed"
                        row["error"] = {"type": type(failure).__name__, "message": str(failure), "stage": "closed_archive_readback_and_scoring"}
                row["scoring_wall_ns"], row["scoring_cpu_ns"] = time.perf_counter_ns() - wall, time.process_time_ns() - cpu
                scored.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
            scored.flush()
            os.fsync(scored.fileno())
        if sensor_hash != parameter_hash(sensor) or judge_hashes != {name: parameter_hash(judge) for name, judge in judges.items()}:
            raise ValueError("Frozen sensor or offline observers changed")
        if expected_timing != timing_registration(controllers_dir) or expected_resources != resources():
            raise ValueError("Frozen implementation or inputs changed during timing")
        from .timing_analysis import aggregate, write_report
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        source_pairs = [sources[VIEWS[0], case] for case in range(16)]
        summary = aggregate(rows, entries, source_pairs)
        _sum_phase(phases, "aggregation", wall, cpu)
        summary.update({"frozen_protocol_sha256": file_sha(freeze_path), "registration_sha256": file_sha(output / "registration.json"),
            "actual_media_archive_sha256": file_sha(archive_path), "clock_rows_sha256": file_sha(output / "clock-rows.jsonl"),
            "scored_rows_sha256": file_sha(output / "scored-rows.jsonl"), "setup_and_finalization_phases": phases,
            "total_wall_ns": time.perf_counter_ns() - total_wall, "total_cpu_ns": time.process_time_ns() - total_cpu,
            "controller_training_process_wall_ns": collection["wall_ns"], "controller_training_process_cpu_ns": collection["cpu_ns"],
            "training_scope": "Controller collection process cost retained separately; original generator training and sensor training remain separate registered receipts, not included in request latency",
            "profile": TIMING_PROFILE, "raw_data_in_git": False})
        write_json(output / "summary.json", summary)
        write_report(summary, output / "REPORT.md")
        print(json.dumps({"phase": "complete", "summary": str(output / "summary.json"),
            "status": summary["status"], "requests": len(rows)}), flush=True)
    except BaseException as failure:
        if archive is not None:
            archive.close()
        write_json(output / "failure.json", {"type": type(failure).__name__, "error": str(failure),
            "traceback": traceback.format_exc(), "completed_attempt_rows": len(rows), "phases": phases})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controllers", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.controllers, args.freeze, args.output)


if __name__ == "__main__":
    main()
