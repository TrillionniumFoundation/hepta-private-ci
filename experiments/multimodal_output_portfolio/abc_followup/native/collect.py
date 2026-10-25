"""Commit public-input forecasts before actual stochastic future generation."""

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import time

import numpy as np
import torch

from ...abc_recovery.runtime import initialize, transition, public_frame, public_digest
from ...abc_recovery.training_run import file_sha, write_json
from ...v6.data import render_tokens
from ...v6.observer import observe_tensors, read_bundle, write_bundle
from ...v7.data import make_batch
from ...v7.evaluation import load_reward
from ...v7.snapshot import Snapshot
from ...v7.sources import load_roles
from .forecast import ACTIONS, Q, emitted_state, predict, public_input


def segments(role, spec):
    views = spec["id_views"]
    if role == "development":
        return [("fit", "train", view, i * 600, 600) for i, view in enumerate(views)] + [
            ("fit", "train", "both_missing", 3000, 1000)] + [
            ("selection", "train", view, 4000 + i * 200, 200) for i, view in enumerate(views)] + [
            ("selection", "train", "both_missing", 5000, 1000)]
    allocation = spec["source_ranges"][role]
    start, id_count = allocation["start"], allocation["id_pairs"]
    result, used = [], 0
    for i, view in enumerate(views):
        n = id_count // len(views) + int(i < id_count % len(views))
        result.append((role, "test", view, start + used, n)); used += n
    return result + [(role, "test", "both_missing", start + used, allocation["ood_pairs"])]


def durable_array(path, **values):
    stream = io.BytesIO(); np.savez_compressed(stream, **values)
    raw = stream.getvalue()
    with path.open("xb") as handle:
        handle.write(raw); handle.flush(); os.fsync(handle.fileno())
    return hashlib.sha256(raw).hexdigest()


def collect(protocol, role, output, model_dir=None):
    spec = json.loads(protocol.read_text())
    weights = None
    if role != "development":
        if model_dir is None:
            raise ValueError("Reserved-source access needs a frozen predictor")
        barrier = model_dir / ("predictor-freeze.json" if role == "calibration" else "calibrator-freeze.json")
        frozen = json.loads(barrier.read_text())
        if frozen["protocol_sha256"] != file_sha(protocol):
            raise ValueError("Protocol differs from prospective freeze")
        for name, digest in frozen["files"].items():
            if file_sha(model_dir / name) != digest:
                raise ValueError("Predictor/calibrator identity changed")
        for name, digest in spec["source_pins"].items():
            if file_sha(Path(__file__).parent / name) != digest:
                raise ValueError("Frozen implementation changed")
        weights = json.loads((model_dir / "weights.json").read_text())
    else:
        barrier = None
    output.mkdir(parents=True, exist_ok=False)
    (output / "commits").mkdir()
    parts = segments(role, spec)
    write_json(output / "access-registration.json", {
        "schema": "hepta.abc4.future-access.v1", "role": role,
        "protocol_sha256": file_sha(protocol), "opened_unix_ns": time.time_ns(),
        "segments": parts, "prior_freeze_sha256": file_sha(barrier) if barrier else None,
        "allocation_sha256": spec["allocation_sha256"],
    })
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    torch.set_num_threads(1)
    paths = {k: Path(v) for k, v in spec["paths"].items()}
    for name, digest in spec["input_sha256"].items():
        if file_sha(paths[name]) != digest:
            raise ValueError("Frozen input changed")
    corpus = load_roles(paths["cache"], paths["manifest"], roles=("train",) if role == "development" else ("test",))
    generator = Snapshot.load(paths["model"], expected_file_sha256=spec["input_sha256"]["model"])._model
    observer, _ = load_reward(paths["observer"], spec["input_sha256"]["observer"])
    arrays = {key: [] for key in ("x_q24", "past_q24", "future_q24", "future_tokens", "y", "pair", "action", "group", "ood")}
    rows = []
    for group, source_role, view, offset, count in parts:
        for begin in range(offset, offset + count, 32):
            size = min(32, offset + count - begin)
            seed = spec["seed"] + begin + (0 if role == "development" else 100000 if role == "calibration" else 200000)
            batch = make_batch(corpus, source_role, size, seed, view=view, offset=begin)
            rng = torch.Generator().manual_seed(seed + 1000000)
            with torch.inference_mode():
                prefix = initialize(generator, batch.observation, generator=rng)
                prefix = transition(generator, prefix, "refine_image", generator=rng)
                frame = public_frame(prefix)
                past = emitted_state(generator, frame)
                parent_digest = public_digest(frame)
                pending = []
                for action_index, action in enumerate(ACTIONS):
                    x = public_input(generator, frame, batch.observation, action)
                    values = {"x_q24": x, "past_q24": past}
                    if weights is not None:
                        forecast, probability = predict(weights, x.astype(np.float64) / Q)
                        values.update(forecast=forecast, raw_probability=probability)
                    committed_at = time.time_ns()
                    commit_name = f"{begin:04d}-{action}.npz"
                    commit_sha = durable_array(output / "commits" / commit_name, **values)
                    pending.append((action_index, action, x, committed_at, commit_name, commit_sha))
                # Both forecasts are durable before either future branch draws.
                for action_index, action, x, committed_at, commit_name, commit_sha in pending:
                    branch_rng = torch.Generator().manual_seed(seed + 2000000 + action_index * 3000000)
                    before_transition = time.time_ns()
                    future = transition(generator, prefix, action, generator=branch_rng)
                    z = emitted_state(generator, public_frame(future))
                    generated_at = time.time_ns()
                    pixels, captions, hashes = [], [], []
                    for i in range(size):
                        media = write_bundle(output / "media" / f"{begin+i:04d}-{action}",
                                             render_tokens(future.tokens[i]), future.pixels[i])
                        reopened, text, identity = read_bundle(media)
                        if (not torch.equal(reopened[0],future.pixels[i])
                                or text!=render_tokens(future.tokens[i])):
                            raise ValueError("Persisted media differs from actual emitted future")
                        pixels.append(reopened[0]); captions.append(text); hashes.append(identity)
                    scored = observe_tensors(observer, torch.stack(pixels), captions,
                                             batch.target.pixels, batch.target.labels)
                    ys = [int(s["caption_valid"] and all(s[k] == 0 for k in
                              ("text_fact", "relation", "image_fact", "crossmodal_disagreement"))) for s in scored]
                    arrays["x_q24"].append(x); arrays["past_q24"].append(past); arrays["future_q24"].append(z)
                    arrays["future_tokens"].append(future.tokens.numpy())
                    for key, value in (("y", ys), ("pair", range(begin, begin + size)),
                                       ("action", [action_index] * size), ("group", [group] * size),
                                       ("ood", [view == "both_missing"] * size)):
                        arrays[key].append(np.asarray(value))
                    for i, score in enumerate(scored):
                        rows.append({"pair": begin+i, "source_ids": batch.source_ids[i], "action": action,
                            "view": view, "group": group, "joint_correct": ys[i], "scores": score,
                            "media": hashes[i], "commit_file": commit_name, "commit_sha256": commit_sha,
                            "commit_unix_ns": committed_at, "transition_started_unix_ns": before_transition,
                            "generation_finished_unix_ns": generated_at, "prefix_public_digest": parent_digest,
                            "forecast_used_current_outcome": False})
            print(json.dumps({"role":role,"pairs_completed":len(rows)//2,"view":view}), flush=True)
    np.savez_compressed(output / "data.npz", **{k:np.concatenate(v) for k,v in arrays.items()})
    with gzip.open(output / "rows.jsonl.gz", "wt") as handle:
        for row in rows: handle.write(json.dumps(row, sort_keys=True) + "\n")
    write_json(output / "cost.json", {"role": role, "source_pairs":len(rows)//2,"future_rows":len(rows),
        "wall_ns":time.perf_counter_ns()-began,"cpu_ns":time.process_time_ns()-cpu,
        "data_sha256":file_sha(output / "data.npz"),"rows_sha256":file_sha(output / "rows.jsonl.gz"),
        "scope":"load, actual common prefix, two causal forecast commitments, actual future emissions, media write/reopen, independent scoring, persistence"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--role", choices=("development", "calibration", "verification"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", type=Path)
    args = parser.parse_args(); collect(args.protocol, args.role, args.output, args.model)
