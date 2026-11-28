"""Independently validate native checkpoints, all score arrays, paired metrics and specimen identities."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_text())


def compare(observed, expected):
    np.testing.assert_allclose(observed, expected, atol=2e-10, rtol=1e-11)


def measure(z, y):
    if z.shape != (len(y), 72) or not np.isfinite(z).all():
        raise ValueError("invalid finite score array")
    z = z.astype(np.float64)
    loss = np.logaddexp.reduce(z, axis=1) - z[np.arange(len(y)), y]
    return loss, (np.argmax(z, axis=1) == y)


def verify(source, root):
    term = read(root / "terminal.json")
    seal = read(root / "seal.json")
    identity = read(root / "session.json")
    if len(seal) != 6 or term["seal_sha256"] != sha(root / "seal.json"):
        raise ValueError("end-state seal")
    for n, expected in identity["inputs"].items():
        if sha(source / n) != expected:
            raise ValueError("source identity " + n)
    with np.load(source / "data/data.npz") as data:
        ids, labels, split = (data[k].copy() for k in ("ids", "labels", "split"))
    tr, dv, te = [np.flatnonzero(split == n) for n in range(3)]
    if tuple(map(len,(tr,dv,te))) != (4984,1147,1311) or len(set(ids)) != len(ids):
        raise ValueError("clip roster")
    loss_map = {}
    reopened = steps = dev_count = cold_count = restarted = 0
    mean_summary = {arm: [] for arm in ("literal", "sdpa")}
    scores = {}
    for a, n in (("literal",1016475200),("sdpa",1011757056)):
        for seed in (137,311,557):
            key = f"{a}-{seed}"
            loc = root / key
            fit, cold = read(loc/"fit.json"), read(loc/"cold.json")
            if fit != term["cells"][key]["fit"] or cold != term["cells"][key]["cold"]:
                raise ValueError("terminal linkage")
            w = loc/"epoch_state.pt"
            if (sha(w) != seal[key]["end_checkpoint_sha256"] or sha(loc/"fit.json") != seal[key]["fit_sha256"]
                    or w.stat().st_size != fit["end_checkpoint_bytes"] or sha(loc/"cold.npz") != cold["score_sha256"]):
                raise ValueError("checkpoint or scores " + key)
            reopened += w.stat().st_size
            order = np.random.default_rng(seed + 7369).permutation(tr)
            order_sha = hashlib.sha256(order.astype("<i8").tobytes()).hexdigest()
            if fit["order_sha256"] != order_sha or fit["parameters"] != n or fit["unique_examples"] != len(set(order)):
                raise ValueError("training coverage " + key)
            rows = [json.loads(line) for line in (loc/"steps.jsonl").read_text().splitlines()]
            latest = {r["step"]: r for r in rows}
            if set(latest) != set(range(1,313)) or latest[1]["gradient_scalar_count"] != n:
                raise ValueError("step or gradient coverage " + key)
            for i, r in latest.items():
                if r["seen"] != min(16*i,4984) or not np.isfinite([r["grad_norm"],r["training_loss"]]).all():
                    raise ValueError("per-step data or objective " + key)
            steps += len(latest)
            restarted += len(rows)-len(latest)
            for r in fit["history"]:
                step = r["step"]
                fn = loc / f"dev-{step}.npz"
                if step not in (16,128,312) or sha(fn) != r["score_sha256"]:
                    raise ValueError("development linkage")
                with np.load(fn) as dat:
                    np.testing.assert_array_equal(dat["ids"],ids[dv])
                    np.testing.assert_array_equal(dat["labels"],labels[dv])
                    loss,acc = measure(dat["aligned"],labels[dv])
                    compare([loss.mean(),acc.mean()],[r["metrics"]["nll"],r["metrics"]["top1"]])
                    dev_count += dat["aligned"].size
            if [r["step"] for r in fit["history"]] != [16,128,312]:
                raise ValueError("development stages")
            with np.load(loc/"cold.npz") as dat:
                np.testing.assert_array_equal(dat["ids"],ids[te])
                np.testing.assert_array_equal(dat["labels"],labels[te])
                variants = ("aligned","audio_swapped","video_swapped","both_swapped")
                for k in variants:
                    arr = dat[k]
                    loss,acc = measure(arr,labels[te])
                    scores[key,k] = loss
                    compare([loss.mean(),acc.mean()],[cold["variants"][k]["nll"],cold["variants"][k]["top1"]])
                    cold_count += arr.size
                    if k == "aligned":
                        loss_map[key] = loss
                        mean_summary[a].append([loss.mean(),acc.mean(),fit["training_wall_s"]])
    actors = np.array([s.split("_")[0] for s in ids[te]])
    unique, ix = np.unique(actors,return_inverse=True)
    if len(unique) != 16:
        raise ValueError("held actor count")
    rng = np.random.default_rng(66541)
    draws = rng.integers(0,len(unique),(4000,len(unique)))
    counts = np.bincount(ix)
    def interval(delta):
        sums = np.bincount(ix,weights=delta)
        return [float(delta.mean()),*np.quantile(sums[draws].sum(1)/counts[draws].sum(1),[.025,.975]).tolist()]
    seeds = (137,311,557)
    paired = interval(np.mean([loss_map[f"literal-{s}"]-loss_map[f"sdpa-{s}"] for s in seeds],0))
    compare(paired,[term["literal_minus_sdpa_nll"],*term["actor_ci95"]])
    sensitivity={}
    for arm in mean_summary:
        sensitivity[arm] = {k:interval(np.mean([scores[f"{arm}-{s}",k]-loss_map[f"{arm}-{s}"] for s in seeds],0))
                            for k in ("audio_swapped","video_swapped","both_swapped")}
    if (steps,dev_count,cold_count)!=(1872,1486512,2265408):
        raise ValueError(f"unexpected counts {steps}, {dev_count}, {cold_count}")
    return dict(verified=True, completed_unix=time.time(), terminal_sha256=sha(root/"terminal.json"),
                reopened_checkpoint_bytes=reopened, final_fits=6, distinct_steps=steps,
                duplicate_after_restart_log_rows=restarted, dev_logits=dev_count,cold_logits=cold_count,
                means_nll_top1_training_s={k:np.mean(v,0).tolist() for k,v in mean_summary.items()},
                literal_minus_sdpa_ci95=paired, within_actor_sensitivity_delta_ci95=sensitivity)


if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument("source",type=Path)
    p.add_argument("root",type=Path)
    args=p.parse_args()
    result=verify(args.source,args.root)
    tmp=args.root/"verification.tmp"
    tmp.write_text(json.dumps(result,indent=2)+"\n")
    tmp.replace(args.root/"verification.json")
    print(json.dumps(result),flush=True)
