"""Frozen actors, shared policy fitting, genuine causal reads and native STOP."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time
import traceback

import torch
from torch.nn import functional as F

from experiments.continuous_spiking_network import records
from experiments.continuous_spiking_network.boundary_study import (
    make_episodes,
    prefix_log_odds,
)
from experiments.continuous_spiking_network.models import SequenceClassifier

from .budget_io import write_arrays
from .budget_training import current_seals
from .online_policy import OnlinePolicies
from .online_task import execute_episode, metrics, verify_resume
from .streaming import model_digest


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


def write_traces(path, values):
    payload = b"".join(
        (json.dumps(row, sort_keys=True, allow_nan=False) + "\n").encode()
        for row in values
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with (
        path.open("wb") as raw,
        gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as output,
    ):
        output.write(payload)
    return {
        "path": str(path.name),
        "sha256": records.digest_bytes(path.read_bytes()),
        "uncompressed_sha256": records.digest_bytes(payload),
        "records": len(values),
    }


def calibration_metrics(odds, labels, temperature):
    target = labels[:, None].expand_as(odds).float()
    values = {}
    for name, score in (("raw", odds), ("shared_temperature", odds / temperature)):
        probability = score.sigmoid()
        values[name] = {
            "prefix_ce": float(F.binary_cross_entropy_with_logits(score, target)),
            "prefix_brier": float((probability - target).square().mean()),
        }
    return values


def execute(
    seed,
    output,
    base_results,
    native_binary,
    native_work,
    enforce_seal=True,
    development_protocol=None,
):
    package = Path(__file__).parent
    if development_protocol is not None:
        if enforce_seal:
            raise ValueError("formal studies cannot override the frozen protocol")
        protocol = development_protocol
    else:
        protocol = json.loads((package / "PROTOCOL.json").read_text())["boundary"]
    if seed not in protocol["actor_seeds"]:
        raise ValueError("actor seed is not in the frozen boundary inventory")
    output = Path(output)
    if any(
        (output / name).exists()
        for name in ("START.json", "FAILED.json", "RESULT.json")
    ):
        raise FileExistsError(
            "preserve prior boundary attempt and use a fresh directory"
        )
    seals = current_seals(enforce_seal)
    started = time.process_time(), time.perf_counter()
    torch.set_num_threads(1)
    actor_root = Path(base_results) / "boundary" / f"seed{seed}"
    original = json.loads((actor_root / "RESULT.json").read_text())
    manifest_path = actor_root / "actor_checkpoint" / "manifest.json"
    manifest_sha = records.digest_bytes(manifest_path.read_bytes())
    if manifest_sha != original["actor"]["checkpoint_manifest_sha256"]:
        raise ValueError("historical selected actor identity changed")
    config = json.loads(manifest_path.read_text())["config"]
    model = SequenceClassifier(**config)
    records.checkpoint_load(model, actor_root / "actor_checkpoint")
    model.eval()
    identity = model_digest(model)
    records.write_json(
        output / "START.json",
        {
            "seed": seed,
            "protocol": protocol,
            "source_seals": seals,
            "actor_manifest_sha256": manifest_sha,
            "actor_model_sha256": identity,
            "historical_actor_training_cpu_seconds": original["actor"][
                "training_cpu_seconds"
            ],
            "historical_actor_result_sha256": records.digest_bytes(
                (actor_root / "RESULT.json").read_bytes()
            ),
            "started_unix": time.time(),
            "environment": records.environment(),
        },
    )
    batches = {}
    for name, count, offset, prefix in (
        ("train", protocol["train_size"], 101, "train"),
        ("validation", protocol["validation_size"], 202, "train"),
        ("id", protocol["test_id_size"], 303, "train"),
        ("ood", protocol["test_ood_size"], 404, "ood"),
    ):
        batches[name] = make_episodes(
            count,
            protocol[prefix + "_horizon"],
            protocol[prefix + "_snr"],
            protocol[prefix + "_cost"],
            seed + protocol["new_episode_seed_offset"] + offset,
            "study002." + name,
        )
    cpu = time.process_time()
    train_odds = prefix_log_odds(model, batches["train"])
    val_odds = prefix_log_odds(model, batches["validation"])
    fitting_prefix_cpu = time.process_time() - cpu
    policies, fit = OnlinePolicies.fit(
        train_odds, val_odds, batches["train"], batches["validation"]
    )
    records.write_json(output / "POLICY.json", fit)
    policy_sha = records.digest_bytes((output / "POLICY.json").read_bytes())
    objective_sha = digest(
        {
            "correct_reward": 1.0,
            "cost": "all purchased observations",
            "force_first_observation": True,
            "protocol": protocol,
        }
    )
    outcomes, traces, replays, data_arrays, native_outcomes = {}, {}, {}, {}, {}
    for split in ("id", "ood"):
        batch = batches[split]
        horizon = batch["x"].shape[1]
        policies.precompute(batch["snr"].tolist(), batch["cost"].tolist(), horizon)
        for key, value in batch.items():
            data_arrays[split + "_" + key] = (
                value.numpy() if isinstance(value, torch.Tensor) else value
            )
        mode_records = {mode: [] for mode in ("fixed", "direct", "value", "full")}
        for row in range(len(batch["label"])):
            modes = ["fixed", "direct", "value", "full"]
            shift = (seed + row) % len(modes)
            modes = modes[shift:] + modes[:shift]
            args = dict(
                model=model,
                policies=policies,
                x=batch["x"][row],
                dt=batch["dt"][row],
                episode_id=batch["episode_id"][row],
                snr=float(batch["snr"][row]),
                cost=float(batch["cost"][row]),
            )
            for mode in modes:
                record, _ = execute_episode(mode=mode, **args)
                mode_records[mode].append(record)
        outcomes[split] = {
            mode: metrics(values, batch["label"])
            for mode, values in mode_records.items()
        }
        traces[split] = {
            mode: write_traces(output / f"{split}_{mode}.jsonl.gz", values)
            for mode, values in mode_records.items()
        }
        # Verification is separate from primary online timing and does not fit policies.
        replays[split] = {}
        for mode in ("fixed", "direct", "value"):
            args = dict(
                model=model,
                policies=policies,
                mode=mode,
                x=batch["x"][0],
                dt=batch["dt"][0],
                episode_id=batch["episode_id"][0],
                snr=float(batch["snr"][0]),
                cost=float(batch["cost"][0]),
            )
            replay_record, snapshot = execute_episode(**args, capture_resume=True)
            if [item["logits"] for item in replay_record["trace"]] != [
                item["logits"] for item in mode_records[mode][0]["trace"]
            ]:
                raise ValueError("repeating frozen online execution changed logits")
            replays[split][mode] = verify_resume(
                model,
                policies,
                mode,
                args["x"],
                args["dt"],
                args["snr"],
                args["cost"],
                replay_record,
                snapshot,
                output / "replay" / split / mode,
            )
        cpu = time.process_time()
        full_odds = prefix_log_odds(model, batch)
        outcomes[split]["calibration"] = calibration_metrics(
            full_odds, batch["label"], policies.temperature
        )
        outcomes[split]["verification_full_prefix_cpu_seconds"] = (
            time.process_time() - cpu
        )
        if seed == protocol["native"]["actor_seed"]:
            from .native_consumer import NativeEpisodeConsumer

            if native_binary is None or native_work is None:
                raise ValueError(
                    "the prespecified native subset requires the verified host and work directory"
                )
            native_outcomes[split] = {}
            for mode in ("fixed", "direct", "value"):
                rows, recovered = [], False
                for row in range(protocol["native"]["episodes_per_split_policy"]):
                    x, dt = batch["x"][row], batch["dt"][row]
                    episode_id = f"study002.{seed}.{split}.{mode}.{row:03d}"
                    task_binding = {
                        "input_sha256": records.digest_bytes(
                            x.numpy().tobytes() + dt.numpy().tobytes()
                        ),
                        "policy_sha256": policy_sha,
                        "snr": float(batch["snr"][row]),
                        "cost": float(batch["cost"][row]),
                        "horizon": horizon,
                    }
                    consumer = NativeEpisodeConsumer(
                        native_binary,
                        Path(native_work) / episode_id,
                        model_sha256=identity,
                        objective_sha256=objective_sha,
                        policy_id=mode,
                        episode_id=episode_id,
                        seed=seed + row,
                        maximum_steps=horizon,
                        task_binding=task_binding,
                    )
                    native_record, _ = execute_episode(
                        model,
                        policies,
                        mode,
                        x,
                        dt,
                        episode_id,
                        task_binding["snr"],
                        task_binding["cost"],
                        native=consumer,
                        capture_resume=not recovered,
                    )
                    recovered = (
                        recovered or native_record["native_recovery"] is not None
                    )
                    native_record["native_cost"] = consumer.finish()
                    native_record["reference_python_observations"] = mode_records[mode][
                        row
                    ]["observations"]
                    native_record["same_stop_as_python"] = (
                        native_record["observations"]
                        == mode_records[mode][row]["observations"]
                    )
                    archive = Path(native_record["native_cost"]["archive"]["path"])
                    destination = output / "native_archives" / archive.name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(archive.read_bytes())
                    native_record["native_cost"]["archive"]["path"] = str(
                        destination.relative_to(output)
                    )
                    rows.append(native_record)
                native_outcomes[split][mode] = {
                    "metrics": metrics(rows, batch["label"][: len(rows)]),
                    "records": write_traces(
                        output / f"native_{split}_{mode}.jsonl.gz", rows
                    ),
                    "same_stop_count": sum(row["same_stop_as_python"] for row in rows),
                    "cold_resume_count": sum(
                        row["native_recovery"] is not None for row in rows
                    ),
                }
    data_sha = write_arrays(output / "episodes", data_arrays)
    if current_seals(enforce_seal) != seals:
        raise ValueError("source changed while online boundary study was running")
    result = {
        "seed": seed,
        "source_seals": seals,
        "actor_model_sha256": identity,
        "actor_manifest_sha256": manifest_sha,
        "policy_sha256": policy_sha,
        "objective_sha256": objective_sha,
        "fitting_prefix_cpu_seconds": fitting_prefix_cpu,
        "policy_fit": fit,
        "bellman_table_build_cpu_seconds": policies.table_build_cpu_seconds,
        "metrics": outcomes,
        "trace_files": traces,
        "replays": replays,
        "native": native_outcomes,
        "episode_manifest_sha256": data_sha,
        "total_cpu_seconds": time.process_time() - started[0],
        "total_wall_seconds": time.perf_counter() - started[1],
        "timing_scope": "Python process after initial source check includes model loading, data, fitting, policy tables, online task runs, verification, evidence serialization and final source check; interpreter/import, initial source check and final RESULT write excluded; child native CPU separately recorded",
        "limits": "temperature fitting is not a Bayesian transition proof; source arrays are prepared in RAM; avoided reads are actual task iterator/model steps, not network download or hardware energy",
    }
    records.write_json(output / "RESULT.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--output", required=True)
    parser.add_argument("--base-results", required=True)
    parser.add_argument("--native-binary")
    parser.add_argument("--native-work")
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    try:
        result = execute(
            args.seed,
            args.output,
            args.base_results,
            args.native_binary,
            args.native_work,
            not args.development,
        )
        print(
            json.dumps(
                {
                    "seed": args.seed,
                    "metrics": result["metrics"],
                    "native": result["native"],
                }
            )
        )
    except Exception:
        failure = Path(args.output) / "FAILED.json"
        if not failure.exists() and not (Path(args.output) / "RESULT.json").exists():
            records.write_json(failure, {"traceback": traceback.format_exc()})
        raise
