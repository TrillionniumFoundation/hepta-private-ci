"""Source-frozen training, checkpoint freeze and independent confirmation."""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import platform
import re
import resource
import time
import traceback

import numpy as np
import torch
from torch.nn import functional as F

from experiments.hcsn_four_stage_flow_20261031.models import ContentModel
from .addressed_models import AddressedModel
from . import data


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
CONTENT_ARMS = ("addressed_flow", "addressed_diagonal", "legacy_flow", "transformer")
DYNAMIC_ARMS = ("flow", "diagonal", "gru", "snn", "transformer")
SEEDS = (17, 29, 43)
SHARED = ("encode.", "address_a", "address_b", "log_temperature", "roles.", "value.", "read.")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def source_hashes():
    paths = [HERE / name for name in ("study.py", "data.py", "addressed_models.py", "control_study.py",
                                     "STATISTICAL_PLAN.json")]
    old = HERE.parent / "hcsn_four_stage_flow_20261031"
    paths += [old / name for name in ("models.py", "marked_flow.py", "synthetic_data.py",
                                      "dynamic_data.py", "extended_eval.py")]
    paths.append(HERE.parent / "hcsn_distributional_v2/distribution_kernel.py")
    return {str(path.relative_to(ROOT)): digest(path) for path in sorted(paths)}


def freeze(out):
    out.mkdir(parents=True, exist_ok=False)
    fits = [dict(task=task, arm=arm, seed=seed)
            for task in (*data.CONTENT_TASKS, "dynamics")
            for arm in (DYNAMIC_ARMS if task == "dynamics" else CONTENT_ARMS) for seed in SEEDS]
    protocol = dict(schema="hcsn-addressed-study.v1", frozen_utc=datetime.now(timezone.utc).isoformat(),
        source_hashes=source_hashes(), fits=fits, steps=600, batch=24, learning_rate=.003,
        weight_decay=.0001, gradient_clip=1., optimizer="AdamW", checkpoint="Final step only",
        train_seed="seed*10000+step in the independent train stream; same input for every arm",
        shared_initialization=list(SHARED), confirmation_seed=61101, confirmation_episodes=1024,
        content_conditions=list(data.CONDITIONS),
        dynamics_conditions=["base", "irregular", "missing", "resample", "unit_clock", "reverse_clock"],
        latency=dict(batch_sizes=[1, 24], warmup=3, repeats=9, conditions=["base", "long_tokens_128"],
                     scope="Complete CPU sequence including tensor conversion; no media acquisition"),
        gates=dict(content_all4_min=.95, resampling_max_abs_logit=1e-4,
                   dynamic="Paired accuracy and clock interventions; no invented universal quality threshold",
                   adoption="Requires quality and full deployment economics, not training completeness"),
        precision="FP32 neural state; inherited Flow kernels use FP64 then cast to FP32",
        limits=["Typed addressing and two-hop alias prior shared by addressed arms",
                "Occupancy normalization can cancel common event attenuation",
                "Costs include training and confirmation; historical development separate",
                "CPU seconds are not joules; GPU and attributable energy are not measured"],
        runtime=dict(python=platform.python_version(), torch=torch.__version__, numpy=np.__version__,
                     device="cpu", threads_per_worker=1, platform=platform.platform()))
    write_json(out / "PROTOCOL.json", protocol)
    return dict(protocol_sha256=digest(out / "PROTOCOL.json"), fits=len(fits), source_hashes=source_hashes())


def new_model(task, arm, seed):
    torch.manual_seed(seed)
    if arm.startswith("addressed_"):
        template = AddressedModel("diagonal").state_dict()
        torch.manual_seed(seed)
        model = AddressedModel(arm.removeprefix("addressed_"))
        state = model.state_dict()
        for name in state:
            if name.startswith(SHARED):
                state[name] = template[name].clone()
        model.load_state_dict(state)
        return model
    return ContentModel("flow" if arm == "legacy_flow" else arm, 24, classes=4 if task == "dynamics" else 8)


def predict(model, arrays, chunk=24):
    steps = arrays["x"].shape[1]
    chunk = min(chunk, 4096 // steps)
    if chunk < 1:
        raise ValueError("Sequence exceeds inherited finite operator batch cap")
    logits = []
    with torch.no_grad():
        for start in range(0, len(arrays["x"]), chunk):
            tensors = [torch.from_numpy(np.ascontiguousarray(arrays[key][start:start + chunk]))
                       for key in ("x", "dt", "observed")]
            result = model(*tensors).detach().numpy()
            if not np.isfinite(result).all():
                raise FloatingPointError("Nonfinite model output")
            logits.append(result)
    return np.concatenate(logits)


def fit_records(out):
    return json.loads((Path(out) / "ALL_CHECKPOINTS.json").read_text())["fits"]


def _fit(out_string, spec, protocol):
    torch.set_num_threads(1)
    out = Path(out_string)
    task, arm, seed = (spec[key] for key in ("task", "arm", "seed"))
    fit_id = f"{task}/{arm}/seed{seed}"
    directory = out / "fits" / fit_id
    directory.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter(), time.process_time()
    try:
        if source_hashes() != protocol["source_hashes"]:
            raise RuntimeError("Scientific source changed after freeze")
        model = new_model(task, arm, seed)
        optimizer = torch.optim.AdamW(model.parameters(), lr=protocol["learning_rate"],
                                     weight_decay=protocol["weight_decay"])
        inputs_hash = hashlib.sha256()
        with (directory / "LOSS.jsonl").open("x") as stream:
            for step in range(protocol["steps"]):
                arrays = data.batch(task, protocol["batch"], seed * 10000 + step, "train")
                for key in ("x", "dt", "observed", "y"):
                    inputs_hash.update(np.ascontiguousarray(arrays[key]).tobytes())
                x, dt, observed, y = [torch.from_numpy(arrays[key]) for key in ("x", "dt", "observed", "y")]
                optimizer.zero_grad(set_to_none=True)
                logits = model(x, dt, observed)
                loss = F.cross_entropy(logits.flatten(0, 1), y.flatten(), ignore_index=-100)
                loss.backward()
                norm = torch.nn.utils.clip_grad_norm_(model.parameters(), protocol["gradient_clip"], error_if_nonfinite=True)
                optimizer.step()
                stream.write(json.dumps(dict(step=step + 1, loss=float(loss.detach()), gradient_norm=float(norm))) + "\n")
        checkpoint = directory / "checkpoint.pt"
        torch.save(model.state_dict(), checkpoint)
        if source_hashes() != protocol["source_hashes"]:
            raise RuntimeError("Scientific source changed during fit")
        result = dict(**spec, fit_id=fit_id, status="completed", steps=protocol["steps"],
            checkpoint=str(checkpoint.relative_to(out)), checkpoint_sha256=digest(checkpoint),
            input_stream_sha256=inputs_hash.hexdigest(), final_loss=float(loss.detach()),
            resources=model.resource_shape(arrays["x"].shape[1]),
            wall_seconds=time.perf_counter() - wall, cpu_seconds=time.process_time() - cpu,
            diagnostics=getattr(model, "last_diagnostics", None))
    except Exception as error:
        (directory / "FAILURE.txt").write_text(traceback.format_exc())
        result = dict(**spec, fit_id=fit_id, status="failed", error=str(error),
                      wall_seconds=time.perf_counter() - wall, cpu_seconds=time.process_time() - cpu)
    write_json(directory / "FIT.json", result)
    return result


def train(out, protocol, source_commit, workers):
    if not re.fullmatch("[0-9a-f]{40}", source_commit or "") or workers < 1:
        raise ValueError("Full source commit and positive worker count required")
    protocol_hash = digest(out / "PROTOCOL.json")
    write_json(out / "TRAINING_SOURCE.json", dict(source_commit=source_commit,
        protocol_sha256=protocol_hash, source_hashes=source_hashes(), workers=workers))
    wall, cpu = time.perf_counter(), time.process_time()
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    rows = []
    with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        futures = {pool.submit(_fit, str(out), spec, protocol): spec for spec in protocol["fits"]}
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception as error:
                spec = futures[future]
                fit_id = f"{spec['task']}/{spec['arm']}/seed{spec['seed']}"
                result = dict(**spec, fit_id=fit_id, status="failed", error=str(error),
                              cpu_seconds=None, worker_failure=traceback.format_exc())
            rows.append(result)
            print(json.dumps({key: result.get(key) for key in ("fit_id", "status", "final_loss", "cpu_seconds")}), flush=True)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    rows.sort(key=lambda row: row["fit_id"])
    receipt = dict(source_commit=source_commit, fits=len(rows), failed=sum(row["status"] != "completed" for row in rows),
        wall_seconds=time.perf_counter() - wall, parent_cpu_seconds=time.process_time() - cpu,
        children_cpu_seconds=after.ru_utime + after.ru_stime - children.ru_utime - children.ru_stime,
        fit_cpu_seconds=sum(row["cpu_seconds"] for row in rows if row["cpu_seconds"] is not None),
        fits_missing_cpu=sum(row["cpu_seconds"] is None for row in rows),
        matched_input_streams=all(len({row.get("input_stream_sha256") for row in rows
            if row["task"] == task and row["seed"] == seed}) == 1
            for task in (*data.CONTENT_TASKS, "dynamics") for seed in SEEDS),
        cost_note="Parent plus child CPU is outer total; fit CPU is nested and must not be added again",
        clock_scope="Phase after parent imports; worker imports included; external meter covers entire process",
        protocol_unchanged=digest(out / "PROTOCOL.json") == protocol_hash,
        source_unchanged=source_hashes() == protocol["source_hashes"])
    write_json(out / "TRAIN_RECEIPT.json", receipt)
    write_json(out / "ALL_CHECKPOINTS.json", dict(schema="hcsn-all-checkpoints.v1", source_commit=source_commit,
        protocol_sha256=protocol_hash, fits=rows))
    return dict(**receipt, candidate_freeze_sha256=digest(out / "ALL_CHECKPOINTS.json"))


def _latency(model, arrays, protocol):
    timings = {}
    for size in protocol["latency"]["batch_sizes"]:
        small = {key: value[:size] for key, value in arrays.items()}
        for _ in range(protocol["latency"]["warmup"]):
            predict(model, small, chunk=size)
        measurements = []
        for _ in range(protocol["latency"]["repeats"]):
            started = time.perf_counter()
            predict(model, small, chunk=size)
            measurements.append(time.perf_counter() - started)
        timings[str(size)] = dict(seconds=measurements, median_seconds=float(np.median(measurements)),
            episodes_per_second=float(size / np.median(measurements)))
    return timings


def evaluate(out, protocol, candidate_hash):
    if not re.fullmatch("[0-9a-f]{64}", candidate_hash or "") or digest(out / "ALL_CHECKPOINTS.json") != candidate_hash:
        raise ValueError("Exact all-checkpoint manifest SHA256 required after remote candidate freeze")
    manifest = json.loads((out / "ALL_CHECKPOINTS.json").read_text())
    training_source = json.loads((out / "TRAINING_SOURCE.json").read_text())
    if (digest(out / "PROTOCOL.json") != manifest["protocol_sha256"]
            or training_source["protocol_sha256"] != manifest["protocol_sha256"]
            or training_source["source_commit"] != manifest["source_commit"]):
        raise RuntimeError("Protocol or source identity changed since training")
    records = manifest["fits"]
    registered = {(row["task"], row["arm"], row["seed"]) for row in protocol["fits"]}
    present = {(row["task"], row["arm"], row["seed"]) for row in records}
    if (len(records) != len(protocol["fits"]) or present != registered
            or any(row["status"] != "completed" for row in records)):
        raise RuntimeError("Every registered fit must complete before opening confirmation")
    for row in records:
        if digest(out / row["checkpoint"]) != row["checkpoint_sha256"]:
            raise RuntimeError("Checkpoint changed after freeze")
    destination = out / "confirmation"
    destination.mkdir(exist_ok=False)
    wall, cpu = time.perf_counter(), time.process_time()
    write_json(destination / "CANDIDATE_FREEZE.json", dict(candidate_freeze_sha256=candidate_hash,
        training_source=training_source, source_hashes=source_hashes()))
    rows = []
    for record in records:
        task, arm, seed = (record[key] for key in ("task", "arm", "seed"))
        model = new_model(task, arm, seed).eval()
        model.load_state_dict(torch.load(out / record["checkpoint"], map_location="cpu", weights_only=True))
        fit_dir = destination / record["fit_id"]
        fit_dir.mkdir(parents=True)
        conditions = protocol["dynamics_conditions"] if task == "dynamics" else protocol["content_conditions"]
        base_logits = None
        for condition in conditions:
            started, started_cpu = time.perf_counter(), time.process_time()
            try:
                kind = "base" if condition in ("unit_clock", "reverse_clock") else condition
                arrays = data.batch(task, protocol["confirmation_episodes"], protocol["confirmation_seed"], "confirm", kind)
                if kind != condition:
                    arrays = data.informative_time_intervention(arrays, condition)
                logits = predict(model, arrays)
                if condition == "base":
                    base_logits = logits.copy()
                mask = arrays["y"] >= 0
                episode, position = np.where(mask)
                target, selected = arrays["y"][mask], logits[mask]
                prediction = selected.argmax(-1)
                correct = prediction == target
                per_episode = correct.reshape(len(logits), -1)
                payload = dict(episode_id=episode, query_position=position, target=target,
                    prediction=prediction, logits=selected, correct=correct,
                    sample_weight=arrays["sample_weight"][mask],
                    target_available=arrays.get("target_available", mask)[mask])
                filename = fit_dir / f"{condition}.npz"
                np.savez_compressed(filename, **payload)
                row = dict(task=task, arm=arm, seed=seed, condition=condition, status="completed",
                    fit_id=record["fit_id"], checkpoint_sha256=record["checkpoint_sha256"],
                    artifact=str(filename.relative_to(out)), artifact_sha256=digest(filename),
                    episodes=len(logits), queries=int(mask.sum()), accuracy=float(correct.mean()),
                    all_queries_correct=float(per_episode.all(-1).mean()),
                    cross_entropy=float(F.cross_entropy(torch.from_numpy(selected), torch.from_numpy(target))),
                    data_sha256={key: hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest()
                                 for key, value in arrays.items()},
                    inference_and_data_wall_seconds=time.perf_counter() - started,
                    inference_and_data_cpu_seconds=time.process_time() - started_cpu)
                if condition == "resample":
                    row["resampling_max_abs_logit"] = float(np.max(np.abs(logits[:, 1::2] - base_logits)))
                if task == "dynamics":
                    row["jump_first_query_accuracy"] = float(per_episode[:, 4].mean())
                    row["jump_later_query_accuracy"] = float(per_episode[:, 5:].mean())
                if condition in protocol["latency"]["conditions"]:
                    row["latency"] = _latency(model, arrays, protocol)
            except Exception as error:
                (fit_dir / f"{condition}.FAILURE.txt").write_text(traceback.format_exc())
                row = dict(task=task, arm=arm, seed=seed, condition=condition,
                    status="failed", error=str(error), wall_seconds=time.perf_counter() - started,
                    cpu_seconds=time.process_time() - started_cpu)
            rows.append(row)
            write_json(fit_dir / f"{condition}.json", row)
        print(json.dumps(dict(fit_id=record["fit_id"], conditions=len(conditions),
                             completed=sum(row["status"] == "completed" for row in rows))), flush=True)
    receipt = dict(records=len(rows), failed=sum(row["status"] != "completed" for row in rows),
        wall_seconds=time.perf_counter() - wall, cpu_seconds=time.process_time() - cpu,
        source_unchanged=source_hashes() == protocol["source_hashes"], candidate_freeze_sha256=candidate_hash,
        energy_joules=None, gpu=None, cost_scope="Entire confirmation loop including data, inference, archives and latency repeats")
    write_json(destination / "RESULTS.json", rows)
    write_json(destination / "RECEIPT.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--phase", choices=("train", "evaluate"))
    parser.add_argument("--source-commit")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--candidate-freeze-sha256")
    args = parser.parse_args()
    torch.set_num_threads(1)
    out = Path(args.out).resolve()
    if args.freeze:
        result = freeze(out)
    else:
        protocol = json.loads((out / "PROTOCOL.json").read_text())
        if source_hashes() != protocol["source_hashes"]:
            raise RuntimeError("Scientific source changed after protocol freeze")
        if args.phase == "train":
            result = train(out, protocol, args.source_commit, args.workers)
        elif args.phase == "evaluate":
            result = evaluate(out, protocol, args.candidate_freeze_sha256)
        else:
            parser.error("Choose --freeze or --phase")
    print(json.dumps(result, sort_keys=True), flush=True)
    return 1 if (result.get("failed", 0) or result.get("source_unchanged") is False
                 or result.get("protocol_unchanged") is False) else 0


if __name__ == "__main__":
    raise SystemExit(main())
