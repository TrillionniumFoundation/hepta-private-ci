"""Time-normalized AV profile; copied scheduling from the unexecuted v1 seal.

The only model-input change is dt=1 for every observation of every clip.
All architecture, objective and metric implementations are imported unchanged.
"""

import argparse
import hashlib
import json
from pathlib import Path
import resource
import time

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from ..data import digest, write_json
from ..study import (PairEncoder, load_split as load_source_split, save_weights,
                    load_weights, objective, evaluate, retrieval)


HERE = Path(__file__).resolve().parent
BASE = HERE.parent


def load_split(path, expected):
    data = load_source_split(path, expected)
    data["dt"] = torch.ones_like(data["dt"])
    return data


def verify_freeze():
    freeze = json.loads((HERE / "FREEZE.json").read_text())
    root = HERE.parents[2]
    for row in freeze["files"]:
        if digest(root / row["path"]) != row["sha256"]:
            raise ValueError(f"Frozen input changed: {row['path']}")
    return freeze


def verify_identity(identity):
    verify_freeze()
    for filename, expected in identity.items():
        if digest(HERE / filename) != expected:
            raise ValueError(f"Study identity changed during the run: {filename}")


def run(name, seed, output):
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    protocol_bytes = (HERE / "PROTOCOL.json").read_bytes()
    protocol = json.loads(protocol_bytes)
    identity = {"PROTOCOL.json": hashlib.sha256(protocol_bytes).hexdigest(),
                "FREEZE.json": digest(HERE / "FREEZE.json")}
    verify_identity(identity)
    if name not in protocol["models"] or seed not in protocol["seeds"]:
        raise ValueError("Job not present in the sealed protocol")
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "START.json", dict(model=name, seed=seed,
        protocol_sha256=identity["PROTOCOL.json"], freeze_sha256=identity["FREEZE.json"]))
    data_manifest = json.loads((BASE / "data/DATASET.json").read_text())
    def split(which):
        row = data_manifest["splits"][which]
        return load_split(BASE / "data" / row["path"], row["sha256"])
    train, validation = split("train"), split("validation")
    model = PairEncoder(name, seed)
    initial = {key: value.detach().clone() for key, value in model.named_parameters()}
    initial_hash = save_weights(output / "initial.npz", model)
    optimizer = torch.optim.Adam(model.parameters(), lr=protocol["learning_rate"])
    generator = torch.Generator().manual_seed(seed + 370003)
    permutation, position = torch.randperm(len(train["y"]), generator=generator), 0
    checkpoints, training_cpu, validation_cpu = [], 0.0, 0.0
    with (output / "updates.jsonl").open("x") as log:
        for step in range(1, protocol["updates"] + 1):
            update_start = time.process_time()
            if position + protocol["batch_size"] > len(permutation):
                permutation, position = torch.randperm(len(train["y"]), generator=generator), 0
            indices = permutation[position:position + protocol["batch_size"]]
            position += protocol["batch_size"]
            model.train()
            optimizer.zero_grad(set_to_none=True)
            outputs = model(train["audio"][indices], train["video"][indices], train["dt"][indices])
            loss = objective(outputs, train["y"][indices], protocol["temperature"])
            if not bool(torch.isfinite(loss)):
                raise FloatingPointError("Nonfinite audiovisual objective")
            loss.backward()
            gradients = {}
            for group, entries in model.groups().items():
                values = [p.grad for _, p in entries if p.grad is not None]
                gradients[group] = dict(l2=float(torch.sqrt(sum((g.square().sum() for g in values), torch.tensor(0.)))),
                                        finite=all(bool(torch.isfinite(g).all()) for g in values),
                                        missing=[n for n, p in entries if p.grad is None])
            if any(item["missing"] for item in gradients.values()):
                raise FloatingPointError("A registered parameter is disconnected from the task objective")
            if not all(item["finite"] for item in gradients.values()):
                raise FloatingPointError("Nonfinite gradient")
            norm = float(nn.utils.clip_grad_norm_(model.parameters(), 2.0))
            optimizer.step()
            training_cpu += time.process_time() - update_start
            log.write(json.dumps(dict(step=step, indices=indices.tolist(), loss=float(loss.detach()),
                training_cpu_seconds=training_cpu, gradients=gradients, preclip_l2=norm), allow_nan=False) + "\n")
            log.flush()
            if step in protocol["selection_updates"]:
                validation_start = time.process_time()
                metrics, _ = evaluate(model, validation)
                filename = f"step_{step:04d}.npz"
                digest_value = save_weights(output / filename, model)
                validation_cpu += time.process_time() - validation_start
                checkpoints.append(dict(step=step, weights=filename, sha256=digest_value,
                    training_cpu_seconds=training_cpu, validation=metrics))
                write_json(output / f"checkpoint_{step:04d}.json", checkpoints[-1])
            if training_cpu > protocol["resource_cap_training_cpu_seconds"]:
                raise RuntimeError("Engineering CPU cap exceeded; failed job retained")
    selected = min(checkpoints, key=lambda row: (row["validation"]["fused"]["cross_entropy"], row["step"]))
    # No test tensor is loaded before this durable, validation-only selection lock.
    write_json(output / "SELECTION.json", dict(selected=selected, candidates=checkpoints,
        rule="minimum validation fused CE; earlier update breaks ties", initial_sha256=initial_hash))
    if digest(output / selected["weights"]) != selected["sha256"]:
        raise ValueError("Selected checkpoint identity changed")
    load_weights(output / selected["weights"], model)
    changes = {name: float((p.detach() - initial[name]).norm()) for name, p in model.named_parameters()}
    verify_identity(identity)
    test = split("test")
    metrics, predictions = evaluate(model, test)
    retrieval_metrics, similarities = retrieval(predictions, test["actor"])
    # A fixed within-actor derangement preserves actor identity while breaking paired recordings.
    rng = np.random.default_rng(92497)
    shuffled = np.arange(len(test["actor"]))
    for actor in np.unique(test["actor"]):
        group = rng.permutation(np.flatnonzero(test["actor"] == actor))
        shuffled[group] = np.roll(group, 1)
    with torch.no_grad():
        shuffled_logits = model.head((torch.from_numpy(predictions["audio_embedding"]) +
                                      torch.from_numpy(predictions["video_embedding"])[shuffled]) / 2)
    shuffled_metrics = dict(accuracy=float((shuffled_logits.argmax(-1) == test["y"]).float().mean()),
                           cross_entropy=float(F.cross_entropy(shuffled_logits, test["y"])))
    np.savez_compressed(output / "predictions.npz", **predictions, y=test["y"].numpy(),
        actor=test["actor"], clip=test["clip"], similarities=similarities,
        shuffled_video_indices=shuffled, shuffled_fused_logits=shuffled_logits.numpy())
    verify_identity(identity)
    result = dict(model=name, seed=seed, completed=True, updates=protocol["updates"],
        selected=selected, recognition=metrics, retrieval=retrieval_metrics,
        same_actor_shuffled_fusion=shuffled_metrics, selected_parameter_changes=changes,
        probability_checks=model.probability_checks,
        counts=dict(audio=model.audio.counts(), video=model.video.counts(),
                    total=sum(p.numel() for p in model.parameters())),
        costs=dict(training_cpu_seconds=training_cpu, validation_cpu_seconds=validation_cpu,
            process_cpu_seconds=time.process_time()-start_cpu, wall_seconds=time.perf_counter()-start_wall,
            peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            gpu_memory_bytes=None, measured_energy_joules=None),
        predictions_sha256=digest(output / "predictions.npz"),
        protocol_sha256=identity["PROTOCOL.json"], freeze_sha256=identity["FREEZE.json"],
        scope="720 short acted-emotion clips; actor-disjoint time-normalized offline AV encoder; descriptive 3-seed study")
    write_json(output / "RESULT.json", result)
    print(json.dumps(dict(model=name, seed=seed, recognition=metrics,
                         cpu_seconds=result["costs"]["process_cpu_seconds"])), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    try:
        run(args.model, args.seed, args.output)
    except Exception as error:
        if args.output.is_dir() and not (args.output / "RESULT.json").exists():
            write_json(args.output / "FAILED.json", dict(type=type(error).__name__, error=str(error)))
        raise


if __name__ == "__main__":
    main()
