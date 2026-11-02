"""Retrain the original association ablation on identical dynamics information.

The factorization retains p(state) and the sum of state-conditioned moments.
It removes association only at observed read boundaries, exactly matching the
published execution intervention; it does not remove the full state law.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np
import torch
from torch.nn import functional as F

from experiments.hcsn_addressed_flow_20261101 import data
from experiments.hcsn_four_stage_flow_20261031.models import ContentModel

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ARMS = ("full_flow", "factorized_flow", "transformer")
SEEDS = (67, 83, 101)
DEPENDENCIES = (
    "experiments/hcsn_addressed_flow_20261101/data.py",
    "experiments/hcsn_four_stage_flow_20261031/dynamic_data.py",
    "experiments/hcsn_four_stage_flow_20261031/synthetic_data.py",
    "experiments/hcsn_four_stage_flow_20261031/extended_eval.py",
    "experiments/hcsn_four_stage_flow_20261031/models.py",
    "experiments/hcsn_four_stage_flow_20261031/marked_flow.py",
    "experiments/hcsn_distributional_v2/distribution_kernel.py",
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def sources():
    return {str(p.relative_to(ROOT)): sha(p) for p in [Path(__file__), *(ROOT / p for p in DEPENDENCIES)]}


def model(arm, seed):
    torch.manual_seed(seed)
    result = ContentModel("transformer" if arm == "transformer" else "flow", 24, 4)
    if arm == "factorized_flow":
        result.intervention = "factorized_content"
    return result


def freeze(out):
    out.mkdir(parents=True, exist_ok=False)
    protocol = dict(schema="hcsn-joint-dynamics-retrain.v1", frozen_utc=datetime.now(timezone.utc).isoformat(),
        baseline_commit="a793d55c23a7742378b081b162252da428a9fdb2", source_hashes=sources(),
        arms=list(ARMS), seeds=list(SEEDS), steps=600, batch_size=24, learning_rate=.003,
        weight_decay=.0001, gradient_clip=1., checkpoint="Final update only; no selection", 
        stream="Original addressed train stream, seed*10000+step; identical for all arms",
        confirmation_seed=124731, episodes=512, conditions=["base", "irregular", "missing", "resample"],
        primary="Missing-condition first post-jump query accuracy (original index 9)",
        advancement="Full Flow exceeds both retrained factorized Flow and Transformer in all three seed point estimates, and both conditional episode-bootstrap lower bounds exceed zero",
        secondary=["all-query accuracy", "NLL", "resampling logits", "complete-sequence CPU latency"],
        bootstrap=dict(draws=2000, seed=925117, unit="paired episode, averaging the same three frozen training seeds", scope="Conditional on these checkpoints; not uncertainty over training seeds or generators"),
        timing=dict(batch=24, warmup=3, repeats=9),
        costs="Fixed equal updates/data, not equal CPU. Outer meter contains training/evaluation/imports/writes. Inner timers are nested.",
        exclusions=["No complete-distribution necessity claim", "No task redesign or new generator", "No population-of-training-seeds CI", "No GPU, device joules or production activation"],
        runtime=dict(torch=torch.__version__, numpy=np.__version__, python=platform.python_version(), threads=1))
    write(out / "PROTOCOL.json", protocol)
    return protocol


def tensors(arrays):
    return [torch.from_numpy(np.ascontiguousarray(arrays[k])) for k in ("x", "dt", "observed")]


def train(out, protocol):
    records = []
    for seed in SEEDS:
        for arm in ARMS:
            assert sources() == protocol["source_hashes"]
            directory = out / f"{arm}_seed{seed}"
            directory.mkdir()
            started, cpu = time.perf_counter(), time.process_time()
            candidate = model(arm, seed)
            optimizer = torch.optim.AdamW(candidate.parameters(), lr=.003, weight_decay=.0001)
            inputs = hashlib.sha256()
            with (directory / "loss.jsonl").open("x") as log:
                for step in range(protocol["steps"]):
                    arrays = data.batch("dynamics", 24, seed * 10000 + step, "train")
                    for key in ("x", "dt", "observed", "y"):
                        inputs.update(np.ascontiguousarray(arrays[key]).tobytes())
                    optimizer.zero_grad(set_to_none=True)
                    logits = candidate(*tensors(arrays))
                    loss = F.cross_entropy(logits.flatten(0, 1), torch.from_numpy(arrays["y"]).flatten(), ignore_index=-100)
                    loss.backward()
                    norm = torch.nn.utils.clip_grad_norm_(candidate.parameters(), 1., error_if_nonfinite=True)
                    optimizer.step()
                    log.write(json.dumps(dict(step=step + 1, loss=float(loss.detach()), gradient_norm=float(norm))) + "\n")
            checkpoint = directory / "checkpoint.pt"
            torch.save(candidate.state_dict(), checkpoint)
            record = dict(arm=arm, seed=seed, checkpoint=str(checkpoint.relative_to(out)), sha256=sha(checkpoint),
                input_stream_sha256=inputs.hexdigest(), cpu_seconds=time.process_time() - cpu,
                wall_seconds=time.perf_counter() - started, final_loss=float(loss.detach()), resources=candidate.resource_shape(16))
            write(directory / "FIT.json", record)
            records.append(record)
            print(json.dumps(record), flush=True)
    assert all(len({r["input_stream_sha256"] for r in records if r["seed"] == seed}) == 1 for seed in SEEDS)
    assert sources() == protocol["source_hashes"]
    write(out / "ALL_CHECKPOINTS.json", dict(protocol_sha256=sha(out / "PROTOCOL.json"), fits=records))


def predict(candidate, arrays):
    with torch.no_grad():
        logits = [candidate(*tensors({key: value[s:s+24] for key, value in arrays.items()})).numpy()
                  for s in range(0, len(arrays["x"]), 24)]
    return np.concatenate(logits)


def evaluate(out, protocol):
    lock = json.loads((out / "ALL_CHECKPOINTS.json").read_text())
    assert lock["protocol_sha256"] == sha(out / "PROTOCOL.json")
    assert len(lock["fits"]) == len(ARMS) * len(SEEDS)
    assert sources() == protocol["source_hashes"]
    for record in lock["fits"]:
        assert sha(out / record["checkpoint"]) == record["sha256"]
    confirmation = out / "confirmation"
    confirmation.mkdir()
    write(confirmation / "FREEZE.json", dict(checkpoint_manifest_sha256=sha(out / "ALL_CHECKPOINTS.json"), source_hashes=sources(), opened_utc=datetime.now(timezone.utc).isoformat()))
    rows, primary = [], {}
    for record in lock["fits"]:
        arm, seed = record["arm"], record["seed"]
        candidate = model(arm, seed).eval()
        candidate.load_state_dict(torch.load(out / record["checkpoint"], weights_only=True))
        reference = None
        for condition in protocol["conditions"]:
            arrays = data.batch("dynamics", protocol["episodes"], protocol["confirmation_seed"], "confirm", condition)
            logits = predict(candidate, arrays)
            assert np.isfinite(logits).all()
            mask = arrays["y"] >= 0
            correct = (logits.argmax(-1) == arrays["y"])[mask].reshape(len(logits), -1)
            query_logits = logits[mask].reshape(len(logits), -1, 4)
            y = arrays["y"][mask].reshape(len(logits), -1)
            shifted = query_logits - query_logits.max(-1, keepdims=True)
            log_probs = shifted - np.log(np.exp(shifted).sum(-1, keepdims=True))
            nll = -np.take_along_axis(log_probs, y[..., None], -1).mean()
            np.savez_compressed(confirmation / f"{arm}_{seed}_{condition}.npz", logits=logits, y=arrays["y"], dt=arrays["dt"], observed=arrays["observed"], x_sha256=np.asarray(hashlib.sha256(arrays["x"].tobytes()).hexdigest()))
            if condition == "base":
                reference = logits
            resampling = float(np.max(np.abs(logits[:, 1::2] - reference))) if condition == "resample" else None
            if condition == "missing":
                primary[(arm, seed)] = correct[:, 4].astype(float)
            short = {key: value[:24] for key, value in arrays.items()}
            for _ in range(3):
                predict(candidate, short)
            timings = []
            for _ in range(9):
                started = time.perf_counter()
                predict(candidate, short)
                timings.append(time.perf_counter() - started)
            row = dict(arm=arm, seed=seed, condition=condition, accuracy=float(correct.mean()), nll=float(nll),
                first_post_jump_accuracy=float(correct[:, 4].mean()), resampling_max_abs_logit=resampling,
                latency_seconds=timings, median_latency_seconds=float(np.median(timings)))
            rows.append(row)
    contrasts = []
    for other in ("factorized_flow", "transformer"):
        differences = np.stack([primary[("full_flow", s)] - primary[(other, s)] for s in SEEDS])
        mean_by_episode = differences.mean(0)
        rng = np.random.default_rng(protocol["bootstrap"]["seed"])
        bootstrap = np.asarray([mean_by_episode[rng.integers(len(mean_by_episode), size=len(mean_by_episode))].mean() for _ in range(2000)])
        interval = np.quantile(bootstrap, [.025, .975]).tolist()
        contrasts.append(dict(comparison=f"full_flow-minus-{other}", seed_differences=differences.mean(1).tolist(),
            mean=float(mean_by_episode.mean()), conditional_episode_interval=interval,
            pass_gate=bool((differences.mean(1) > 0).all() and interval[0] > 0)))
    write(out / "SUMMARY.json", dict(rows=rows, primary_contrasts=contrasts,
        source_unchanged=sources() == protocol["source_hashes"], mechanism_gate=all(c["pass_gate"] for c in contrasts),
        all_blockers_closed=False, production_activation=False, energy_joules=None))
    print(json.dumps(dict(contrasts=contrasts, mechanism_gate=all(c["pass_gate"] for c in contrasts))), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("freeze", "train", "confirm"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(1)
    if args.phase == "freeze":
        print(json.dumps(freeze(args.out)), flush=True)
        return
    protocol = json.loads((args.out / "PROTOCOL.json").read_text())
    if args.phase == "train":
        train(args.out, protocol)
    else:
        evaluate(args.out, protocol)


if __name__ == "__main__":
    main()
