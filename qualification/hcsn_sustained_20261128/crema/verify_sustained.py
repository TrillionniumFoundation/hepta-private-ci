"""Verify the sealed sustained experiment and compute time to common quality."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

ARMS = ("literal","smooth","lif","sdpa")
SEEDS = (137,311,557)
GATES = (4.1,3.6,3.0)
RUNGS = (20,240,1000,3150)


def read(path):
    return json.loads(path.read_text())


def sha(path):
    with path.open("rb") as src:
        return hashlib.file_digest(src,"sha256").hexdigest()


def scoring(array, y):
    z = array.astype(np.float64, copy=True)
    z -= z.max(1,keepdims=True)
    return np.log(np.exp(z).sum(1))-z[np.arange(len(y)),y],float(np.mean(z.argmax(1)==y))


def verify(root):
    terminal = read(root/"terminal.json")
    seal = read(root/"seal.json")
    if len(terminal["cells"])!=12 or len(seal)!=12 or sha(root/"seal.json")!=terminal["seal_sha256"]:
        raise ValueError("missing terminal seal")
    sessions = [json.loads(line) for line in (root/"sessions.jsonl").read_text().splitlines()]
    events = [json.loads(line) for line in (root/"events.jsonl").read_text().splitlines()]
    sum_active = 0.
    condition, loss_map = {}, {}
    ref_ids = ref_labels = None
    for arm in ARMS:
        for seed in SEEDS:
            key = f"{arm}-{seed}"
            p = root/key
            hist = read(p/"progress.json")
            rr = hist["history"]
            budget = hist["optimization_wall"]
            if budget<3150 or not all(any("time"+str(t) in row["tags"] for row in rr) for t in RUNGS):
                raise ValueError("incomplete "+key)
            if not all(any(e["arm"]==arm and e["seed"]==seed and e["sha256"]==r["sha256"] for e in events) for r in rr):
                raise ValueError("history mismatch "+key)
            sum_active += budget
            best = min(rr,key=lambda row:(row["development_nll"],row["steps"]))
            if best != seal[key]["best"] or sha(p/best["file"])!=best["sha256"]:
                raise ValueError("best checkpoint mismatch "+key)
            with np.load(p/"cold.npz") as a:
                ids,y,z = a["ids"],a["y"],a["scores"]
                if z.shape!=(1311,72) or not np.isfinite(z).all():
                    raise ValueError("wrong cold panel")
                if ref_ids is None:
                    ref_ids,ref_labels = ids,y
                else:
                    np.testing.assert_array_equal(ids,ref_ids)
                    np.testing.assert_array_equal(y,ref_labels)
                loss, acc = scoring(z,y)
                loss_map[key] = loss
                if arm=="literal":
                    loss_map[key+"-nowire"] = scoring(a["no_wire_scores"],y)[0]
            stored = terminal["cells"][key]
            np.testing.assert_allclose([loss.mean(),acc],[stored["chosen"]["nll"],stored["chosen"]["top1"]],atol=1e-6,rtol=3e-7)
            qual = {}
            for gate in GATES:
                name = str(gate)
                row = next((r for r in rr if r["development_nll"]<=gate),None)
                if row != seal[key]["gates"][name]:
                    raise ValueError("gate selection mismatch")
                cold = stored["gates"][name]
                if row is None and cold is not None or row is not None and row!=cold["development"]:
                    raise ValueError("gate reporting mismatch")
                qual[name] = None
                if row is not None:
                    qual[name] = dict(dev_nll=row["development_nll"],cold_nll=cold["cold"]["nll"],
                        qualified=cold["cold"]["nll"]<=gate,step=row["steps"],optimization_s=row["optimization_wall"],
                        optimization_plus_tracked_dev_io_s=row["optimization_wall"]+row["cumulative_validation_and_checkpoint_s"])
            condition[key] = dict(nll=float(loss.mean()),accuracy=acc,steps=hist["steps"],optimization_s=budget,gates=qual)
    if sum_active<37800:
        raise ValueError("under prescribed budget")
    who,actor = np.unique([s.split("_")[0] for s in ref_ids],return_inverse=True)
    if len(who)!=16:
        raise ValueError("wrong actor count")
    counts = np.bincount(actor)
    draw = np.random.default_rng(66541).integers(16,size=(4000,16))
    contrasts = {}
    for control in ("smooth","lif","sdpa","literal-nowire"):
        d = np.stack([loss_map[f"literal-{s}"] - loss_map[f"literal-{s}-nowire" if control=="literal-nowire" else f"{control}-{s}"] for s in SEEDS]).mean(0)
        sums = np.bincount(actor,weights=d)
        ci = np.quantile(sums[draw].sum(1)/counts[draw].sum(1),[.025,.975])
        reported=terminal["contrasts"][control]
        np.testing.assert_allclose([d.mean(),*ci],[reported["literal_minus_control_clip_nll"],*reported["actor_cluster_ci95"]],atol=2e-6,rtol=1e-6)
        contrasts[control] = dict(literal_minus_control=float(d.mean()),actor_ci95=ci.tolist())
    paired = {}
    for gate in GATES:
        k = str(gate)
        paired[k] = {}
        for control in ("smooth","lif","sdpa"):
            ratios=[]
            for s in SEEDS:
                a=condition[f"literal-{s}"]["gates"][k]
                b=condition[f"{control}-{s}"]["gates"][k]
                if a and b and a["qualified"] and b["qualified"]:
                    ratios.append(b["optimization_s"]/a["optimization_s"])
            paired[k][control]=dict(paired_seeds=len(ratios),control_over_literal_optimization_ratios=ratios,
                                    median_at_all_seeds=float(np.median(ratios)) if len(ratios)==3 else None)
    return dict(verified=True,terminal_sha256=sha(root/"terminal.json"),actual_optimization_seconds=sum_active,
                actual_session_wall_s=terminal["terminal_unix"]-sessions[0]["boot_unix"],source_sha256=sessions[0]["source"],
                checked_best_and_no_wire_logits=15*1311*72,cells=condition,actor_contrasts=contrasts,quality=paired,
                time_definition="Observed fixed-checkpoint optimization clocks. Tracked validation/I/O shown separately. Full experiment wall includes cold.")


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("root",type=Path)
    p.add_argument("--output",type=Path)
    a=p.parse_args()
    result=json.dumps(verify(a.root),indent=2,allow_nan=False)+"\n"
    if a.output:
        a.output.write_text(result)
    print(result)
