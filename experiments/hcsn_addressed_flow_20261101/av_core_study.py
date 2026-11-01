"""Common frozen real-AV encoders followed by fixed-budget neural cores.

All three modality probabilities become available after the complete accepted
one-second prefix. Their zero-time sequential ingestion is computational order,
not a claim of three earlier online observations. No identity metadata is input.
"""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import multiprocessing
from pathlib import Path
import resource
import time
import traceback

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from experiments.hcsn_four_stage_flow_20261031.models import ContentModel
from . import av_frontend


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
ARMS = ("flow", "diagonal", "gru", "transformer", "mlp")
SEEDS = (17, 29, 43)
CONDITIONS = ("base", "delay8", "delay32", "resample")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def read(path):
    return json.loads(Path(path).read_text())


def sources():
    old = HERE.parent / "hcsn_four_stage_flow_20261031"
    paths = [HERE / "av_core_study.py", HERE / "av_frontend.py", HERE / "av_frontend_protocol.json",
             old / "models.py", old / "marked_flow.py", HERE.parent / "hcsn_distributional_v2/distribution_kernel.py"]
    return {str(path.relative_to(ROOT)): digest(path) for path in paths}


class MLPHead(nn.Module):
    """Ordinary reference: retain supplied modality probabilities without decay."""
    def __init__(self):
        super().__init__()
        self.head = nn.Sequential(nn.Linear(6, 32), nn.GELU(), nn.Linear(32, 2))

    def forward(self, x, dt, observed):
        state = x.new_full((len(x), 3), .5)
        seen = torch.zeros_like(state)
        outputs = []
        for index in range(x.shape[1]):
            outputs.append(self.head(torch.cat((state, seen), -1)))
            mask = x[:, index, 2:5] * observed[:, index, None]
            state = state * (1 - mask) + x[:, index, :1] * mask
            seen = torch.maximum(seen, mask)
        return torch.stack(outputs, 1)

    def resource_shape(self, sequence_length):
        return dict(parameters=sum(p.numel() for p in self.parameters()), persistent_state_scalars=6,
                    sequence_length=sequence_length, content_precision="float32", compiled=False)


def new_model(arm, seed):
    torch.manual_seed(seed)
    return MLPHead() if arm == "mlp" else ContentModel(arm, 6, classes=2)


def tokens(probabilities, condition="base"):
    p = np.asarray(probabilities, dtype=np.float32)
    if p.ndim != 2 or p.shape[1] != 3 or not np.isfinite(p).all() or (p < 0).any() or (p > 1).any():
        raise ValueError("Three finite sentence probabilities in [0,1] required")
    n = len(p)
    x = np.zeros((n, 4, 6), np.float32)
    for modality in range(3):
        x[:, modality, 0], x[:, modality, 1] = p[:, modality], 1 - p[:, modality]
        x[:, modality, 2 + modality] = 1
    x[:, 3, 5] = 1  # Query has no content probability or identity payload.
    dt = np.zeros((n, 4), np.float32); dt[:, 0] = 1.
    observed = np.ones((n, 4), bool)
    if condition in ("delay8", "delay32"):
        dt[:, -1] = int(condition.removeprefix("delay"))
    elif condition == "resample":
        refined = np.zeros((n, 8, 6), np.float32); refined[:, 1::2] = x
        visibility = np.zeros((n, 8), bool); visibility[:, 1::2] = observed
        x, observed, dt = refined, visibility, np.repeat(dt / 2, 2, axis=1)
    elif condition != "base":
        raise ValueError(condition)
    return x, dt, observed


def logits(model, probabilities, condition="base", chunk=24):
    x, dt, observed = tokens(probabilities, condition)
    output = []
    with torch.no_grad():
        for index in range(0, len(x), chunk):
            tensor = [torch.from_numpy(value[index:index + chunk]) for value in (x, dt, observed)]
            output.append(model(*tensor)[:, -1].numpy())
    result = np.concatenate(output)
    if not np.isfinite(result).all():
        raise FloatingPointError("Nonfinite AV core logits")
    return result


def freeze(out, frontend, data_root):
    out.mkdir(parents=True, exist_ok=False)
    candidate = av_frontend.load_freeze(frontend / "CANDIDATES.json")
    development = read(frontend / "DEVELOPMENT.json")
    for split in ("train", "validation"):
        if digest(data_root / f"{split}.npz") != development[split + "_data_sha256"]:
            raise ValueError("Encoder probability rows and source dataset identity differ")
    inputs = {}
    with np.load(frontend / "development_probabilities.npz", allow_pickle=False) as z:
        for split, key in (("train", "train_actor_crossfit"), ("validation", "validation")):
            inputs[split + "_p"] = z[key].astype(np.float32)
    for split in ("train", "validation"):
        with np.load(data_root / f"{split}.npz", allow_pickle=False) as z:
            for key in ("y", "sample_weight", "actor"):
                inputs[split + "_" + key] = z[key]
            if len(z["y"]) != len(inputs[split + "_p"]):
                raise ValueError("Encoder probabilities and label rows differ")
    np.savez_compressed(out / "INPUTS.npz", **inputs)
    for filename in ("relation_head.npz", "CANDIDATES.json"):
        (out / filename).write_bytes((frontend / filename).read_bytes())
    source_manifest = sources()
    snapshot = out / "sources"; snapshot.mkdir()
    for name in source_manifest:
        path = snapshot / name
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes((ROOT / name).read_bytes())
    protocol = dict(schema="hcsn.av.cores.v1", source_hashes=source_manifest,
        frontend_candidate_sha256=digest(frontend / "CANDIDATES.json"), frontend_directory=str(frontend),
        original_probabilities_sha256=digest(frontend / "development_probabilities.npz"),
        metadata_sha256={split: digest(data_root / f"{split}.npz") for split in ("train", "validation")},
        inputs_sha256=digest(out / "INPUTS.npz"), relation_head_sha256=digest(out / "relation_head.npz"),
        arms=list(ARMS), seeds=list(SEEDS), steps=600, batch=24, optimizer="AdamW", learning_rate=.003,
        weight_decay=.0001, clip_norm=1., selection="Final checkpoint; no head hyperparameter or development selection",
        sampling="Same uniform row indices per seed and step; weighted cross entropy normalized within batch",
        training="Only actor-crossfit training probabilities; no in-sample full-encoder train probabilities",
        input="Two sentence probabilities, three modality flags and one query flag; no actor, clip, filename or duration metadata",
        timing="Entire shared one-second prefix available; dt=[1,0,0,0]; final query has zero value payload",
        conditions=list(CONDITIONS), latency=dict(warmup=3, repeats=9, batches=[1,24]),
        metric="Exact class-balanced sample-weighted accuracy and cross entropy",
        intervals="10000 actor-cluster bootstrap replicates, seed71; three neural training seeds reported individually",
        strong_references=["Frozen train-OOF learned multilinear logistic relation head", "Constructed conditional-independence probability rule"],
        independent_cohort=candidate.get("independent_cohort"), energy_joules=None, gpu=None,
        limits=["Common auxiliary sentence-supervised closed-vocabulary frontend", "One binary consistency answer, not open-domain generation",
                "Head-only clocks exclude encoder/media preparation; those costs remain in frontend ledger",
                "Weak video frontend can remain the binding bottleneck despite successful head training"])
    write(out / "PROTOCOL.json", protocol)
    return dict(protocol_sha256=digest(out / "PROTOCOL.json"), inputs_sha256=protocol["inputs_sha256"], source_hashes=source_manifest)


def _fit(out_string, arm, seed, protocol):
    torch.set_num_threads(1)
    out = Path(out_string); directory = out / "fits" / f"{arm}_{seed}"; directory.mkdir(parents=True)
    wall, cpu = time.perf_counter(), time.process_time()
    try:
        if sources() != protocol["source_hashes"] or digest(out / "INPUTS.npz") != protocol["inputs_sha256"]:
            raise ValueError("Frozen source or input changed")
        with np.load(out / "INPUTS.npz", allow_pickle=False) as z:
            p, y, weight = z["train_p"], z["train_y"], z["train_sample_weight"]
        x, dt, observed = tokens(p)
        model = new_model(arm, seed)
        optimizer = torch.optim.AdamW(model.parameters(), lr=protocol["learning_rate"], weight_decay=protocol["weight_decay"])
        rng = np.random.default_rng(99171 + seed); stream_hash = hashlib.sha256()
        with (directory / "LOSS.jsonl").open("x") as stream:
            for step in range(protocol["steps"]):
                index = rng.integers(len(y), size=protocol["batch"])
                stream_hash.update(index.tobytes())
                features = [torch.from_numpy(v[index]) for v in (x, dt, observed)]
                labels = torch.from_numpy(y[index]).long(); w = torch.from_numpy(weight[index]).float()
                optimizer.zero_grad(set_to_none=True)
                output = model(*features)[:, -1]
                loss = (F.cross_entropy(output, labels, reduction="none") * w).sum() / w.sum()
                loss.backward()
                norm = torch.nn.utils.clip_grad_norm_(model.parameters(), protocol["clip_norm"], error_if_nonfinite=True)
                optimizer.step()
                stream.write(json.dumps(dict(step=step + 1, loss=float(loss.detach()), gradient_norm=float(norm))) + "\n")
        path = directory / "checkpoint.pt"; torch.save(model.state_dict(), path)
        result = dict(arm=arm, seed=seed, status="completed", final_loss=float(loss.detach()),
            checkpoint=str(path.relative_to(out)), checkpoint_sha256=digest(path),
            training_index_sha256=stream_hash.hexdigest(), resources=model.resource_shape(4))
    except Exception as error:
        (directory / "FAILURE.txt").write_text(traceback.format_exc())
        result = dict(arm=arm, seed=seed, status="failed", error=str(error))
    result.update(cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall)
    write(directory / "FIT.json", result)
    return result


def train(out, protocol, source_commit, workers):
    if len(source_commit or "") != 40 or any(c not in "0123456789abcdef" for c in source_commit) or workers < 1:
        raise ValueError("Remote source commit required")
    wall, cpu = time.perf_counter(), time.process_time()
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    protocol_hash = digest(out / "PROTOCOL.json")
    write(out / "TRAINING_SOURCE.json", dict(source_commit=source_commit, protocol_sha256=protocol_hash))
    records = []
    with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        futures = {pool.submit(_fit, str(out), arm, seed, protocol): (arm, seed) for arm in ARMS for seed in SEEDS}
        for future in as_completed(futures):
            try: result = future.result()
            except Exception as error:
                arm, seed = futures[future]
                result = dict(arm=arm, seed=seed, status="failed", error=str(error), worker_failure=traceback.format_exc())
            records.append(result)
            print(json.dumps(result), flush=True)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    records.sort(key=lambda row: (row["arm"], row["seed"]))
    result = dict(fits=records, source_commit=source_commit, protocol_sha256=protocol_hash,
        frontend_candidate_sha256=protocol["frontend_candidate_sha256"], failed=sum(r["status"] != "completed" for r in records),
        parent_cpu_seconds=time.process_time()-cpu, child_cpu_seconds=after.ru_utime+after.ru_stime-children.ru_utime-children.ru_stime,
        wall_seconds=time.perf_counter()-wall, source_unchanged=sources() == protocol["source_hashes"],
        protocol_unchanged=digest(out / "PROTOCOL.json") == protocol_hash,
        matched_training_indices=all(len({r.get("training_index_sha256") for r in records if r["seed"] == seed}) == 1 for seed in SEEDS),
        cost_scope="Parent+children phase CPU, including worker startup; nested fit timers not added again")
    write(out / "ALL_CHECKPOINTS.json", result)
    return dict(failed=result["failed"], candidate_freeze_sha256=digest(out / "ALL_CHECKPOINTS.json"),
                source_unchanged=result["source_unchanged"], protocol_unchanged=result["protocol_unchanged"])


def metrics(score, labels, weights, actors):
    correct = (score >= .5) == labels
    clip = np.clip(score, 1e-12, 1-1e-12)
    actor_ids = np.unique(actors)
    numerator = np.asarray([np.sum(weights[actors == actor] * correct[actors == actor]) for actor in actor_ids])
    denominator = np.asarray([np.sum(weights[actors == actor]) for actor in actor_ids])
    samples = np.random.default_rng(71).integers(len(actor_ids), size=(10000, len(actor_ids)))
    bootstrap = numerator[samples].sum(1) / denominator[samples].sum(1)
    return dict(weighted_accuracy=float(np.average(correct, weights=weights)),
        cross_entropy=float(np.average(-labels*np.log(clip)-(1-labels)*np.log1p(-clip), weights=weights)),
        actor_bootstrap_95=np.quantile(bootstrap, [.025,.975]).tolist(), actors=len(actor_ids), episodes=len(labels))


def evaluate(out, protocol, confirmation, candidate_sha):
    if digest(out / "ALL_CHECKPOINTS.json") != candidate_sha:
        raise ValueError("Exact remotely frozen all-head-checkpoint digest required")
    candidate = read(out / "ALL_CHECKPOINTS.json")
    training = read(out / "TRAINING_SOURCE.json")
    if (candidate["failed"] or candidate["protocol_sha256"] != digest(out / "PROTOCOL.json")
            or training["protocol_sha256"] != candidate["protocol_sha256"]
            or training["source_commit"] != candidate["source_commit"]
            or not candidate["source_unchanged"] or not candidate["protocol_unchanged"]):
        raise ValueError("Incomplete candidate or changed protocol")
    if ({(r["arm"],r["seed"]) for r in candidate["fits"]} != {(a,s) for a in ARMS for s in SEEDS}
            or len(candidate["fits"]) != len(ARMS)*len(SEEDS)):
        raise ValueError("Registered neural head candidates missing or duplicated")
    for fit in candidate["fits"]:
        if digest(out / fit["checkpoint"]) != fit["checkpoint_sha256"]:
            raise ValueError("Head weights changed after freeze")
    if (digest(out / "relation_head.npz") != protocol["relation_head_sha256"]
            or digest(out / "CANDIDATES.json") != protocol["frontend_candidate_sha256"]
            or digest(out / "INPUTS.npz") != protocol["inputs_sha256"]):
        raise ValueError("Frozen shared inputs or frontend reference changed")
    frontend_result = read(confirmation / "CONFIRMATION.json")
    if frontend_result["split"] != "independent_test" or frontend_result["candidate_freeze_sha256"] != protocol["frontend_candidate_sha256"]:
        raise ValueError("Fresh actor confirmation from the common frozen encoder required")
    wall, cpu = time.perf_counter(), time.process_time()
    with np.load(confirmation / "predictions.npz", allow_pickle=False) as z:
        p, y, w, actors = z["probabilities"].astype(np.float32), z["y"], z["sample_weight"], z["actor"]
    if set(actors) != set(protocol["independent_cohort"]["actors"]):
        raise ValueError("Actors differ from frozen prospective cohort")
    destination = out / "confirmation"; destination.mkdir()
    results = []
    for fit in candidate["fits"]:
        if digest(out / fit["checkpoint"]) != fit["checkpoint_sha256"]:
            raise ValueError("Head weights changed after freeze")
        model = new_model(fit["arm"], fit["seed"]).eval()
        model.load_state_dict(torch.load(out / fit["checkpoint"], weights_only=True, map_location="cpu"))
        for condition in CONDITIONS:
            output = logits(model, p, condition)
            score = torch.softmax(torch.from_numpy(output), -1).numpy()[:, 1].astype(float)
            row = dict(arm=fit["arm"], seed=fit["seed"], condition=condition, **metrics(score,y,w,actors))
            if condition == "base": base = output
            if condition == "resample": row["resampling_error"] = float(np.max(np.abs(output-base)))
            path = destination / f"{fit['arm']}_{fit['seed']}_{condition}.npz"
            np.savez_compressed(path, logits=output, score=score, y=y, sample_weight=w, actor=actors)
            row.update(raw_file=path.name, raw_sha256=digest(path), checkpoint_sha256=fit["checkpoint_sha256"])
            if condition == "base":
                row["head_only_latency"] = {}
                for size in (1,24):
                    times = []
                    for repeat in range(12):
                        tick = time.perf_counter(); logits(model,p[:size],chunk=size)
                        if repeat >= 3: times.append(time.perf_counter()-tick)
                    row["head_only_latency"][str(size)] = dict(seconds=times, median_seconds=float(np.median(times)), episodes_per_second=float(size/np.median(times)))
            results.append(row)
    with np.load(out / "relation_head.npz", allow_pickle=False) as z:
        logit = av_frontend.relation_features(p) @ z["coef"] + z["intercept"]
        learned = 1 / (1 + np.exp(-logit))
    references = {"learned_relation": metrics(learned,y,w,actors), "constructed": metrics(av_frontend.constructed_posterior(p),y,w,actors)}
    np.savez_compressed(destination / "reference_predictions.npz", learned_relation=learned,
        constructed=av_frontend.constructed_posterior(p), y=y, sample_weight=w, actor=actors)
    summary = dict(results=results, references=references, frontend_confirmation_sha256=digest(confirmation / "CONFIRMATION.json"),
        encoder_probabilities_sha256=digest(confirmation / "predictions.npz"), candidate_freeze_sha256=candidate_sha,
        reference_predictions_sha256=digest(destination / "reference_predictions.npz"),
        cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall,
        source_unchanged=sources() == protocol["source_hashes"], energy_joules=None, gpu=None,
        scope="Real-AV common-encoder closed-vocabulary consistency; head costs separate from frontend acquisition and encoding")
    write(destination / "SUMMARY.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("freeze", "train", "evaluate"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--frontend", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--source-commit")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--confirmation", type=Path)
    parser.add_argument("--candidate-freeze-sha256")
    args = parser.parse_args(); torch.set_num_threads(1)
    if args.mode == "freeze": result = freeze(args.out, args.frontend, args.data_root)
    else:
        protocol = read(args.out / "PROTOCOL.json")
        if sources() != protocol["source_hashes"]: raise ValueError("Scientific source changed after freeze")
        result = train(args.out,protocol,args.source_commit,args.workers) if args.mode == "train" else evaluate(args.out,protocol,args.confirmation,args.candidate_freeze_sha256)
    print(json.dumps(result, sort_keys=True), flush=True)
    return 1 if result.get("failed",0) or result.get("source_unchanged") is False or result.get("protocol_unchanged") is False else 0


if __name__ == "__main__":
    raise SystemExit(main())
