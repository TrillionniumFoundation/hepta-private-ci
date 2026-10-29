"""Bounded warm-cost and persistent-maintenance engineering diagnostics.

Run only after the supplemental source and selected models are sealed. Training
contexts are reused for diagnostics; these are not new confirmation samples.
"""

import argparse
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from experiments.continuous_boundary_flow.common import write_records
from . import cells
from .common import CostMeter, canonical, save_json, sha
from .engineering_replay import ARMS, DIAGNOSTIC_SEED, MaintenanceStream, source_hashes
from .native.bridge import ScoreBridge


def warm_inference(inputs, checkpoint, *, warmup_ticks=128):
    """Fixed causal input values, zero forced reset; only cell math is timed."""
    inputs = np.asarray(inputs, dtype=float)
    if inputs.ndim != 2 or inputs.shape[1] != 18 or not len(inputs):
        raise ValueError("Warm input stream must contain 18 values per tick")
    params, kind = cells.deserialize(checkpoint["model"])
    state, reset = np.zeros((1, 6)), np.zeros(1)
    warmup_clock = CostMeter()
    for i in range(warmup_ticks):
        _, state = cells.step(
            inputs[i % len(inputs)][None, :], reset, state, params, kind
        )
    warmup_cost = warmup_clock.finish()
    started_wall, started_cpu = time.perf_counter(), time.process_time()
    for row in inputs:
        scores, state = cells.step(row[None, :], reset, state, params, kind)
    cpu, wall = time.process_time() - started_cpu, time.perf_counter() - started_wall
    return {
        "arm": checkpoint["arm"],
        "kind": kind,
        "trainable_scalars": cells.parameter_count(params),
        "input_sha256": sha(inputs.tobytes()),
        "warmup_ticks": warmup_ticks,
        "warmup_cost": warmup_cost,
        "timed_model_state_updates": len(inputs),
        "timed_state_scalar_updates": 6 * len(inputs),
        "python_cpu_seconds": cpu,
        "wall_seconds": wall,
        "cpu_seconds_per_tick": cpu / len(inputs),
        "local_numeric_input_bytes": int(inputs.nbytes),
        "persistent_state_bytes": 48,
        "wire_request_bytes": 0,
        "wire_response_bytes": 0,
        "actual_ndu_calls": 0,
        "actual_kernel_calls": 0,
        "forced_reset_fraction": 0.0,
        "final_state_sha256": sha(canonical(state.tolist())),
        "final_scores_sha256": sha(canonical(scores.tolist())),
        "scope": "single Python cell inference stream including input/parameter validation; no feature extraction, environment, serialization, NDU or IPC",
        "byte_scope": "logical local float64 input/state sizes, not measured memory traffic or energy",
        "energy_measurement": None,
    }


def run(
    study_dir,
    score_binary,
    output_dir,
    *,
    ticks=8192,
    checkpoint_interval=1024,
    replay_ticks=16,
    warm_ticks=4096,
):
    if (
        not 1 <= ticks <= 8192
        or not 1 <= checkpoint_interval <= ticks
        or not 1 <= replay_ticks <= min(checkpoint_interval, 64)
        or not 1 <= warm_ticks <= ticks
    ):
        raise ValueError("Invalid bounded engineering schedule")
    study, output = Path(study_dir).resolve(), Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    overall_clock = CostMeter()
    selection_raw = (study / "SELECTION_SEAL.json").read_bytes()
    selection = json.loads(selection_raw)
    contexts_raw = (study / "contexts" / "2203" / "training.json").read_bytes()
    contexts_payload = json.loads(contexts_raw)
    binary = Path(score_binary).resolve()
    binary_sha = sha(binary.read_bytes())
    source = source_hashes()
    schedule = {
        "schema": "hepta.boundary-policy.engineering-request.v1",
        "seed": 2203,
        "arms": list(ARMS),
        "primary_ticks_per_model": ticks,
        "checkpoint_interval": checkpoint_interval,
        "cold_replay_ticks": replay_ticks,
        "warm_ticks_per_model": warm_ticks,
        "diagnostic_rng_seed": DIAGNOSTIC_SEED,
        "selection_sha256": sha(selection_raw),
        "training_contexts_sha256": sha(contexts_raw),
        "score_binary_sha256": binary_sha,
        "sources": source,
        "scope_mode": "full_engineering"
        if ticks == 8192
        and checkpoint_interval == 1024
        and replay_ticks == 16
        and warm_ticks == 4096
        else "engineering_preflight",
        "new_confirmation_samples": 0,
    }
    save_json(output / "REQUEST.json", schedule)
    results, warm_source, checkpoints = [], None, {}
    for arm in ARMS:
        entries = [
            row
            for row in selection["checkpoints"]
            if row["seed"] == 2203 and row["arm"] == arm
        ]
        if len(entries) != 1:
            raise ValueError("Missing or duplicate selected engineering checkpoint")
        entry = entries[0]
        selected_path = (study / entry["path"]).resolve()
        if not selected_path.is_relative_to(study):
            raise ValueError("Selected checkpoint escapes the study")
        raw = selected_path.read_bytes()
        if sha(raw) != entry["sha256"]:
            raise ValueError("Selected checkpoint hash mismatch")
        checkpoint = json.loads(raw)
        checkpoints[arm] = checkpoint
        bindings = {
            "selection_sha256": sha(selection_raw),
            "selection_entry": entry,
            "checkpoint_sha256": sha(raw),
            "training_contexts_sha256": sha(contexts_raw),
            "score_binary_sha256": binary_sha,
            "sources": source,
        }
        target = output / arm
        target.mkdir()
        setup_clock = CostMeter()
        stream = MaintenanceStream(checkpoint, contexts_payload, bindings)
        setup_cost = setup_clock.finish()
        primary_clock = CostMeter()
        bridge = ScoreBridge(
            binary, target / "native", expected_binary_sha256=binary_sha
        )
        records, saved = [], []
        try:
            for tick in range(1, ticks + 1):
                records.append(stream.advance(bridge))
                if tick % checkpoint_interval == 0 or tick == ticks:
                    path = target / "checkpoints" / f"t{tick}.json"
                    digest = save_json(path, stream.snapshot())
                    saved.append(
                        {
                            "tick": tick,
                            "path": str(path.relative_to(output)),
                            "sha256": digest,
                            "resume_verified": tick < ticks
                            and tick + replay_ticks <= ticks,
                        }
                    )
        finally:
            native_cost = bridge.close()
        primary_cost = primary_clock.finish()
        serialization_clock = CostMeter()
        evidence = write_records(target / "records.jsonl.gz", records)
        evidence["path"] = str((target / "records.jsonl.gz").relative_to(output))
        serialization_cost = serialization_clock.finish()
        if arm == "dual_flow":
            warm_source = [
                {"source_tick": row["tick"], "features": row["features"]}
                for row in records[:warm_ticks]
            ]
        replay_results = []
        for saved_checkpoint in saved:
            if not saved_checkpoint["resume_verified"]:
                continue
            position = saved_checkpoint["tick"]
            replay_output = target / "cold_replay" / f"t{position}"
            clock = CostMeter()
            env = dict(
                os.environ, PYTHONDONTWRITEBYTECODE="1", OPENBLAS_NUM_THREADS="1"
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "experiments.continuous_boundary_policy.engineering_replay",
                    "--checkpoint",
                    str(output / saved_checkpoint["path"]),
                    "--score-binary",
                    str(binary),
                    "--output",
                    str(replay_output),
                    "--ticks",
                    str(replay_ticks),
                ],
                cwd=Path(__file__).resolve().parents[2],
                env=env,
                capture_output=True,
                check=False,
            )
            launched_cost = clock.finish()
            if completed.returncode != 0:
                (target / f"replay-t{position}.stderr.log").write_bytes(
                    completed.stderr
                )
                raise RuntimeError("Cold replay subprocess failed; evidence preserved")
            receipt = json.loads((replay_output / "SUMMARY.json").read_bytes())
            expected = [
                sha(canonical(row))
                for row in records[position : position + replay_ticks]
            ]
            if (
                receipt["record_sha256"] != expected
                or receipt["source_checkpoint_sha256"] != saved_checkpoint["sha256"]
                or receipt["ending_tick"] != position + replay_ticks
            ):
                raise ValueError(
                    "Cold process diverged from uninterrupted task continuation"
                )
            replay_results.append(
                {
                    "starting_tick": position,
                    "ticks": replay_ticks,
                    "exact_match": True,
                    "checkpoint_sha256": saved_checkpoint["sha256"],
                    "receipt_path": str(
                        (replay_output / "SUMMARY.json").relative_to(output)
                    ),
                    "receipt_sha256": sha(
                        (replay_output / "SUMMARY.json").read_bytes()
                    ),
                    "launched_process_cost": launched_cost,
                    "cost_scope": "launch window includes fresh Python startup and reaped descendants; worker/native internal clocks are subsets",
                }
            )
        blocks = []
        for start in range(0, len(records), checkpoint_interval):
            block = records[start : start + checkpoint_interval]
            hidden = np.asarray([row["maintenance_after"]["hidden"] for row in block])
            blocks.append(
                {
                    "start_tick": start,
                    "ticks": len(block),
                    "hidden_mean": hidden.mean(axis=0).tolist(),
                    "hidden_std": hidden.std(axis=0).tolist(),
                    "max_abs_hidden": float(np.abs(hidden).max()),
                }
            )
        results.append(
            {
                "arm": arm,
                "checkpoint_sha256": bindings["checkpoint_sha256"],
                "primary_model_state_updates": ticks,
                "primary_actual_ndu_calls": native_cost["actual_ndu_calls"],
                "primary_actual_kernel_calls": native_cost["actual_kernel_calls"],
                "semantic_decision_input_bytes": ticks * 24,
                "state_reset_at_job_boundary_count": 0,
                "maintenance_final": stream.state,
                "state_blocks": blocks,
                "records": evidence,
                "setup_cost": setup_cost,
                "primary_cost": primary_cost,
                "native_cost_subset": native_cost,
                "record_serialization_cost": serialization_cost,
                "saved_checkpoints": saved,
                "cold_replays": replay_results,
                "terminal_checkpoint_scope": "saved at the final tick; no continuation claim for this terminal snapshot",
            }
        )
    warm_save_clock = CostMeter()
    warm_manifest = write_records(output / "warm_inputs.jsonl.gz", warm_source)
    warm_manifest["path"] = "warm_inputs.jsonl.gz"
    with gzip.open(output / "warm_inputs.jsonl.gz", "rt") as handle:
        common_inputs = np.asarray([json.loads(line)["features"] for line in handle])
    warm_save_cost = warm_save_clock.finish()
    warm = [warm_inference(common_inputs, checkpoints[arm]) for arm in ARMS]
    if len({row["input_sha256"] for row in warm}) != 1:
        raise ValueError("Warm inference inputs differ across architectures")
    overall_cost = overall_clock.finish()
    summary = {
        "schema": "hepta.boundary-policy.engineering-summary.v1",
        "passed": True,
        "request": schedule,
        "models": results,
        "warm_inference": warm,
        "warm_inputs": warm_manifest,
        "warm_input_save_load_cost": warm_save_cost,
        "overall_window_cost": overall_cost,
        "overall_cost_scope": "inclusive engineering window; component windows and native process clocks must not be added to it",
        "primary_model_state_updates": len(ARMS) * ticks,
        "cold_python_processes": sum(len(row["cold_replays"]) for row in results),
        "cold_replay_model_state_updates": sum(
            sum(r["ticks"] for r in row["cold_replays"]) for row in results
        ),
        "new_confirmation_samples": 0,
        "energy_measurement": None,
        "scope": "persistent Python recurrent policy plus actual original NDU; no sparse kernel, production authority, or durable native owner",
        "interpretation": "bounded finite engineering workload, not infinite-horizon convergence or a new comparative utility experiment",
    }
    save_json(output / "SUMMARY.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", required=True)
    parser.add_argument("--score-binary", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--ticks", type=int, default=8192)
    parser.add_argument("--checkpoint-interval", type=int, default=1024)
    parser.add_argument("--replay-ticks", type=int, default=16)
    parser.add_argument("--warm-ticks", type=int, default=4096)
    args = parser.parse_args()
    result = run(
        args.study,
        args.score_binary,
        args.output,
        ticks=args.ticks,
        checkpoint_interval=args.checkpoint_interval,
        replay_ticks=args.replay_ticks,
        warm_ticks=args.warm_ticks,
    )
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "primary_ticks": result["primary_model_state_updates"],
                "cold_processes": result["cold_python_processes"],
            }
        )
    )


if __name__ == "__main__":
    main()
