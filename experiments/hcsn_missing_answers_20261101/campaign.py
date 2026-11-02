"""Missing-trained content memories; labels and availability never enter forward.

The source and protocol freeze precede training; every final checkpoint freezes
before calibration and new confirmation. This experiment changes supervision
coverage, retaining the explicit typed symbolic prior of PR #4548.
"""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing
from pathlib import Path
import platform
import resource
import time
import traceback

import numpy as np
import torch
from torch.nn import functional as F

from experiments.hcsn_addressed_flow_20261101 import data, study, typed_retention
from experiments.hcsn_four_stage_flow_20261031.extended_eval import stress_data

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TASKS = ("mqar", "selective", "binding")
CORES = ("diagonal", "flow")
SEEDS = (17, 29, 43)
CONDITIONS = ("base", "missing", "long_tokens_128", "missing_tokens_128")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as f:
        json.dump(obj, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")


def load(path):
    return json.loads(Path(path).read_text())


def sources():
    names = [Path(__file__), HERE / "__init__.py"]
    older = ROOT / "experiments"
    for folder, files in {
        "hcsn_addressed_flow_20261101": ["data.py", "study.py", "addressed_models.py", "typed_retention.py"],
        "hcsn_four_stage_flow_20261031": ["models.py", "marked_flow.py", "synthetic_data.py", "dynamic_data.py", "extended_eval.py"],
        "hcsn_distributional_v2": ["distribution_kernel.py"],
    }.items():
        names.extend(older / folder / f for f in files)
    return {str(p.relative_to(ROOT)): sha(p) for p in names}


def model(core, seed):
    return typed_retention.install(study.new_model("mqar", "addressed_" + core, seed))


def batch(task, n, seed, split, condition):
    if condition == "missing_tokens_128":
        base = data.batch(task, n, seed, split, "missing")
        result = stress_data(task, base, "long_tokens_128")
        available = np.zeros_like(result["y"], bool)
        available[:, -4:] = base["target_available"][:, -4:]
        result["target_available"] = available
        return result
    return data.batch(task, n, seed, split, condition)


def freeze(out):
    out.mkdir(parents=True, exist_ok=False)
    protocol = dict(schema="hcsn.missing-training.v1", frozen_utc=datetime.now(timezone.utc).isoformat(),
        baseline_commit="a793d55c23a7742378b081b162252da428a9fdb2", source_hashes=sources(),
        tasks=list(TASKS), cores=list(CORES), fit_seeds=list(SEEDS), steps=600, batch=24,
        learning_rate=.003, weight_decay=.0001, gradient_clip=1.,
        training="Fresh final-step fits; even steps missing condition, odd steps base; seed*10000+step+7000000 in train stream",
        input_contract="Only raw x, dt, observed; y used only by loss; target_available used only by scorer",
        architecture="Unchanged PR4548 typed addressed model; shared initialization and typed prior for both cores",
        calibration=dict(seed=172019, episodes=512, split="dev", conditions=["base", "missing"],
            temperature_grid=[.25,.5,.75,1.,1.5,2.,3.,4.,6.,8.],
            threshold_grid=[.125,.2,.3,.4,.5,.6,.7,.8,.9,.95,.98,.99,.995,.999,1.000001],
            target_correctness=.95, method="Largest dev coverage with Wilson lower bound >= .95; zero-coverage if none"),
        confirmation=dict(seed=173029, episodes=512, split="confirm", conditions=list(CONDITIONS)),
        gates=dict(known_accuracy_min=.95, missing_brier_better_than_baseline=True,
            missing_nll_better_than_baseline=True, unavailable_accuracy="Descriptive, cannot recover erased information",
            accepted_correctness_min=.95, accepted_known_coverage_min=.80),
        comparison="Historical base-only 600-step final checkpoints evaluated on the same fresh draws; runtime version differs from original campaign",
        uncertainty="Per-fit metrics and min/max across three training seeds; no synthetic episode independence claim across fits",
        energy_joules=None, gpu=None,
        runtime=dict(python=platform.python_version(),torch=torch.__version__,numpy=np.__version__,threads=1))
    save(out / "PROTOCOL.json", protocol)
    return dict(protocol_sha256=sha(out / "PROTOCOL.json"), fits=18)


def fit(out, task, core, seed, protocol):
    torch.set_num_threads(1)
    folder = Path(out) / "fits" / f"{task}_{core}_{seed}"
    folder.mkdir(parents=True, exist_ok=False)
    cpu, wall = time.process_time(), time.perf_counter()
    try:
        if sources() != protocol["source_hashes"]:
            raise ValueError("Source drift")
        net = model(core, seed)
        optimizer = torch.optim.AdamW(net.parameters(), lr=protocol["learning_rate"], weight_decay=protocol["weight_decay"])
        stream = hashlib.sha256()
        with (folder / "LOSS.jsonl").open("x") as f:
            for step in range(protocol["steps"]):
                condition = "missing" if step % 2 == 0 else "base"
                arrays = batch(task, protocol["batch"], seed * 10000 + step + 7000000, "train", condition)
                for key in ("x", "dt", "observed", "y"):
                    stream.update(np.ascontiguousarray(arrays[key]).tobytes())
                x, dt, observed, y = [torch.from_numpy(arrays[k]) for k in ("x", "dt", "observed", "y")]
                optimizer.zero_grad(set_to_none=True)
                logits = net(x, dt, observed)
                loss = F.cross_entropy(logits.flatten(0, 1), y.flatten(), ignore_index=-100)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(net.parameters(), protocol["gradient_clip"], error_if_nonfinite=True)
                optimizer.step()
                f.write(json.dumps(dict(step=step+1, condition=condition, loss=float(loss.detach()))) + "\n")
        checkpoint = folder / "checkpoint.pt"
        torch.save(net.state_dict(), checkpoint)
        row = dict(status="completed",task=task,core=core,seed=seed,steps=protocol["steps"],
            checkpoint=str(checkpoint.relative_to(out)),checkpoint_sha256=sha(checkpoint),
            input_stream_sha256=stream.hexdigest(),final_loss=float(loss.detach()))
    except Exception as e:
        (folder / "FAILURE.txt").write_text(traceback.format_exc())
        row = dict(status="failed",task=task,core=core,seed=seed,error=str(e))
    row.update(cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall)
    save(folder / "FIT.json", row)
    return row


def train(out, workers):
    protocol = load(out / "PROTOCOL.json")
    if protocol["source_hashes"] != sources():
        raise ValueError("Source drift")
    cpu, wall = time.process_time(), time.perf_counter()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    rows = []
    with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        jobs = [pool.submit(fit,str(out),task,core,seed,protocol) for task in TASKS for core in CORES for seed in SEEDS]
        for job in as_completed(jobs):
            row = job.result(); rows.append(row); print(json.dumps(row), flush=True)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    manifest = dict(fits=sorted(rows,key=lambda r:(r["task"],r["core"],r["seed"])),
        protocol_sha256=sha(out / "PROTOCOL.json"),source_unchanged=sources()==protocol["source_hashes"],
        failures=sum(r["status"]!="completed" for r in rows),
        parent_cpu_seconds=time.process_time()-cpu,
        children_cpu_seconds=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
        wall_seconds=time.perf_counter()-wall,cost_scope="Parent and waited descendants; inner fit timers nested")
    save(out / "ALL_CHECKPOINTS.json", manifest)
    return dict(failures=manifest["failures"],candidate_sha256=sha(out/"ALL_CHECKPOINTS.json"))


def probabilities(logits, temperature):
    v = np.asarray(logits, np.float64) / temperature
    e = np.exp(v - v.max(-1, keepdims=True))
    return e / e.sum(-1, keepdims=True)


def wilson(correct):
    n = len(correct)
    if not n: return 0.
    p, z = float(np.mean(correct)), 1.959963984540054
    return (p+z*z/(2*n)-z*np.sqrt(p*(1-p)/n+z*z/(4*n*n))) / (1+z*z/n)


def calibrate(logits, y, protocol):
    options = []
    for temperature in protocol["temperature_grid"]:
        p = probabilities(logits,temperature)
        nll = float(-np.log(p[np.arange(len(y)),y].clip(1e-15)).mean())
        options.append((nll,temperature))
    _, temperature = min(options)
    p = probabilities(logits,temperature); confidence=p.max(-1); correct=p.argmax(-1)==y
    eligible = []
    for threshold in protocol["threshold_grid"]:
        mask=confidence>=threshold
        if mask.any() and wilson(correct[mask]) >= protocol["target_correctness"]:
            eligible.append((int(mask.sum()),-threshold,threshold))
    threshold = max(eligible)[2] if eligible else 1.000001
    return dict(temperature=temperature,threshold=threshold,
        dev_coverage=float(np.mean(confidence>=threshold)),
        dev_accepted_wilson_lower=wilson(correct[confidence>=threshold]),
        dev_nll=min(options)[0])


def metrics(logits,y,available,cal):
    p=probabilities(logits,cal["temperature"]); pred=p.argmax(-1); correct=pred==y
    confidence=p.max(-1); accepted=confidence>=cal["threshold"]
    losses=-np.log(p[np.arange(len(y)),y].clip(1e-15))
    brier=((p-np.eye(8)[y])**2).sum(-1)
    row=dict(accuracy=float(correct.mean()),all4=float(correct.reshape(-1,4).all(-1).mean()),
        brier=float(brier.mean()),nll=float(losses.mean()),coverage=float(accepted.mean()),
        accepted_correctness=float(correct[accepted].mean()) if accepted.any() else None,
        accepted_known_coverage=float(accepted[available].mean()) if available.any() else None,
        accepted_unavailable_rate=float(accepted[~available].mean()) if (~available).any() else None)
    for name,mask in (("known",available),("unavailable",~available)):
        row[name] = dict(count=int(mask.sum()),accuracy=float(correct[mask].mean()),
            nll=float(losses[mask].mean()),brier=float(brier[mask].mean()),
            mean_confidence=float(confidence[mask].mean())) if mask.any() else None
    return row,p,accepted


def evaluate(out, baseline):
    protocol=load(out/"PROTOCOL.json"); candidate=load(out/"ALL_CHECKPOINTS.json")
    if candidate["failures"] or not candidate["source_unchanged"] or sources()!=protocol["source_hashes"]:
        raise ValueError("Incomplete candidates or source drift")
    original=load(baseline/"ALL_CHECKPOINTS.json")
    originals={(r["task"],r["core"],r["seed"]):r for r in original["fits"]}
    directory=out/"confirmation"; directory.mkdir(exist_ok=False)
    # Freeze complete candidate identity before any dev or confirmation generation.
    save(out/"EVALUATION_FREEZE.json",dict(candidate_sha256=sha(out/"ALL_CHECKPOINTS.json"),
        historical_candidate_sha256=sha(baseline/"ALL_CHECKPOINTS.json"),protocol_sha256=sha(out/"PROTOCOL.json")))
    cpu,wall=time.process_time(),time.perf_counter();rows=[];calibrations=[]
    for fitrow in candidate["fits"]:
        task,core,seed=[fitrow[k] for k in ("task","core","seed")]
        for version,record,root in (("missing_trained",fitrow,out),("historical_base_only",originals[task,core,seed],baseline)):
            checkpoint=root/record["checkpoint"]
            if sha(checkpoint)!=record["checkpoint_sha256"]:raise ValueError("Checkpoint changed")
            net=model(core,seed).eval();net.load_state_dict(torch.load(checkpoint,weights_only=True,map_location="cpu"))
            c=protocol["calibration"];devlogits=[];devy=[]
            for condition in c["conditions"]:
                arrays=batch(task,c["episodes"],c["seed"],c["split"],condition)
                logits=study.predict(net,arrays);mask=arrays["y"]>=0
                devlogits.append(logits[mask]);devy.append(arrays["y"][mask])
            cal=calibrate(np.concatenate(devlogits),np.concatenate(devy),c)
            calibrations.append(dict(task=task,core=core,seed=seed,version=version,**cal))
            save(directory/f"CAL_{task}_{core}_{seed}_{version}.json",cal)
            for condition in protocol["confirmation"]["conditions"]:
                c=protocol["confirmation"];arrays=batch(task,c["episodes"],c["seed"],c["split"],condition)
                mask=arrays["y"]>=0;logits=study.predict(net,arrays)[mask];y=arrays["y"][mask]
                available=arrays.get("target_available",mask)[mask]
                m,p,accepted=metrics(logits,y,available,cal)
                raw=directory/f"{task}_{core}_{seed}_{version}_{condition}.npz"
                np.savez_compressed(raw,logits=logits,probabilities=p,labels=y,available=available,accepted=accepted)
                row=dict(task=task,core=core,seed=seed,version=version,condition=condition,
                    checkpoint_sha256=record["checkpoint_sha256"],metrics=m,raw_sha256=sha(raw),raw_file=raw.name,
                    data_sha256={k:hashlib.sha256(np.ascontiguousarray(v).tobytes()).hexdigest() for k,v in arrays.items()})
                rows.append(row);save(raw.with_suffix(".json"),row)
        print(json.dumps(dict(task=task,core=core,seed=seed,evaluated=True)),flush=True)
    save(directory/"SUMMARY.json",dict(rows=rows,calibrations=calibrations,
        cpu_seconds=time.process_time()-cpu,wall_seconds=time.perf_counter()-wall,
        candidate_sha256=sha(out/"ALL_CHECKPOINTS.json"),source_unchanged=sources()==protocol["source_hashes"],
        energy_joules=None,all_blockers_closed=False,production_activation=False))
    return dict(records=len(rows),source_unchanged=sources()==protocol["source_hashes"])


def main():
    p=argparse.ArgumentParser();p.add_argument("mode",choices=("freeze","train","evaluate"));p.add_argument("--out",type=Path,required=True)
    p.add_argument("--workers",type=int,default=3);p.add_argument("--baseline",type=Path);a=p.parse_args();torch.set_num_threads(1)
    result=freeze(a.out) if a.mode=="freeze" else train(a.out,a.workers) if a.mode=="train" else evaluate(a.out,a.baseline)
    print(json.dumps(result,sort_keys=True),flush=True)


if __name__=="__main__":main()
