"""Reproduce opened missing-content failures and audit a shared posterior repair."""

import argparse
import hashlib
import itertools
import json
from pathlib import Path
import resource
import time

import numpy as np
from scipy.special import softmax

from experiments.hcsn_addressed_flow_20261101 import data
from .posterior import calibrate, infer


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OLD = ROOT / "experiments/hcsn_addressed_flow_20261101/results/retention001"
BASE_COMMIT = "a793d55c23a7742378b081b162252da428a9fdb2"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def independent(task, prefix, observed):
    """Enumerate the generator's latent assignments, independently of infer()."""
    count = 6 if task == "selective" else 4
    assignments = np.asarray(list(itertools.permutations(range(8), count)), np.int8)
    keys = np.asarray(list(itertools.permutations(range(4), 2)), np.int8)
    if task == "selective":
        assignments = np.repeat(assignments, len(keys), axis=0)
        keys = np.tile(keys, (len(assignments) // len(keys), 1))
    keep = np.ones(len(assignments), bool)
    offset = 4 if task == "binding" else 0
    for position in range(offset, len(prefix)):
        event = prefix[position]
        if not observed[position] or event[12] != 1:
            continue
        key, value = event[:4].argmax(), event[4:12].argmax()
        if position < offset + 8:
            keep &= assignments[:, key] == value
        else:
            update = position - 8
            keep &= (keys[:, update] == key) & (assignments[:, 4 + update] == value)
    assignments = assignments[keep]
    final = assignments[:, :4].copy()
    if task == "selective":
        keys = keys[keep]
        for update in range(2):
            final[np.arange(len(final)), keys[:, update]] = assignments[:, 4 + update]
    if not len(final):
        raise AssertionError("No independent latent world matches the raw history")
    return np.eye(8)[final].mean(0), len(final)


def numerical_audit():
    rows, maximum = [], 0.
    for task in data.CONTENT_TASKS:
        arrays = data.batch(task, 32, 981731, "dev", "missing")
        first = arrays["x"].shape[1] - 4
        for row in range(16):
            x, mask = arrays["x"][row, :first], arrays["observed"][row, :first]
            posterior = infer(task, x, mask)
            expected, count = independent(task, x, mask)
            error = float(np.abs(posterior.by_address() - expected).max())
            maximum = max(maximum, error)
            if error > 1e-14:
                raise AssertionError("Closed-form posterior differs from latent enumeration")
            # Every possible acquired raw token has its actual Bayesian successor.
            for key, value in np.unique(posterior.missing_events, axis=0):
                raw = np.zeros(24); raw[key] = raw[4 + value] = raw[12] = 1
                after = posterior.acquire(raw)
                if np.any(after.by_address().max(1) != 1):
                    raise AssertionError("Real missing-event acquisition did not resolve content")
            rows.append(dict(task=task,episode=row,missing_slot=int(np.flatnonzero(~mask)[0]),
                latent_worlds=count,max_error=error,probabilities=expected.tolist(),
                read_gain=posterior.value_of_read()))
    # The masked token must not retain an answer, and extra erasures are invalid.
    x, mask = x.copy(), mask.copy()
    x[np.flatnonzero(~mask)[0], 4] = 1
    try:
        infer(task, x, mask)
    except ValueError:
        rejected = True
    else:
        raise AssertionError("Hidden missing-token payload was accepted")
    return dict(independent_prefixes=len(rows),maximum_error=maximum,
        raw_hidden_payload_rejected=rejected,rows=rows,
        scope="Finite generator posterior identity; not a learned model efficacy test")


def metrics(probabilities, labels, available):
    correct = probabilities.argmax(-1) == labels
    selected = probabilities[np.arange(len(labels)), labels]
    certain = probabilities.max(1) >= .9
    return dict(accuracy=float(correct.mean()),
        available_accuracy=float(correct[available].mean()),
        unavailable_accuracy=float(correct[~available].mean()),
        brier=float(np.square(probabilities - np.eye(8)[labels]).sum(1).mean()),
        log_loss=float(-np.log(selected).mean()) if np.all(selected > 0) else None,
        zero_target_probability=int(np.sum(selected == 0)),
        confidence_90_coverage=float(certain.mean()),
        confidence_90_accuracy=float(correct[certain].mean()) if certain.any() else None)


def run(out):
    import torch
    from experiments.hcsn_addressed_flow_20261101.addressed_models import AddressedModel
    from experiments.hcsn_addressed_flow_20261101.typed_retention import install
    from experiments.hcsn_addressed_flow_20261101.study import predict

    out.mkdir(parents=True, exist_ok=False)
    start, cpu = time.perf_counter(), time.process_time()
    torch.set_num_threads(1)
    sources = {str(path.relative_to(ROOT)):digest(path) for path in
               sorted(ROOT.glob("experiments/**/*.py"))}
    protocol = dict(schema="hcsn.missing.posterior.regression.v1",base_commit=BASE_COMMIT,
        source_hashes=sources,tasks=list(data.CONTENT_TASKS),fit_seeds=[17,29,43],
        opened_confirmation_seed=73117,episodes=1024,
        status="Development regression on previously opened confirmation; no fresh efficacy confirmation",
        repair="Replace uncertain rows only with exact causal posterior, identically for both cores",
        observation_boundary="Public task identity and raw x/observed prefixes only",
        prior="Known typed finite generator including sampling without replacement",
        costs="Current full process measured separately; old training not repeated or free",
        energy_joules=None,gpu=None)
    (out/"PROTOCOL.json").write_text(json.dumps(protocol,indent=2,sort_keys=True)+"\n")
    reference = numerical_audit()
    (out/"INDEPENDENT_POSTERIOR.json").write_text(json.dumps(reference,indent=2,sort_keys=True)+"\n")
    manifest = json.loads((OLD/"ALL_CHECKPOINTS.json").read_text())
    previous = json.loads((OLD/"confirmation/SUMMARY.json").read_text())
    records, prepare, roundtrips = [], [], []
    for task in data.CONTENT_TASKS:
        begin = time.process_time()
        arrays = data.batch(task,1024,73117,"confirm","missing")
        query = arrays["y"] >= 0
        labels = arrays["y"][query]
        available = arrays["target_available"][query]
        exact = np.zeros((*query.shape,8))
        prelude = arrays["x"].shape[1] - 4
        vof, styles = [], []
        for row in range(len(arrays["x"])):
            posterior = infer(task,arrays["x"][row,:prelude],arrays["observed"][row,:prelude])
            for position in np.flatnonzero(query[row]):
                exact[row,position] = posterior.query(arrays["x"][row,position])
            vof.append(posterior.value_of_read())
            styles.append(int(np.flatnonzero(~arrays["observed"][row])[0]))
        np.savez_compressed(out/f"{task}_inputs.npz",**arrays,reference=exact[query],
                            exact_read_value=np.asarray(vof))
        prepare.append(dict(task=task,cpu_seconds=time.process_time()-begin,
            reference=metrics(exact[query],labels,available),read_value_mean=float(np.mean(vof)),
            missing_initial_count=int(np.sum(np.asarray(styles)<8))))
        for fit in (r for r in manifest["fits"] if r["task"] == task):
            core, seed = fit["core"],fit["seed"]
            checkpoint=ROOT/"frozen_weights"/OLD.relative_to(ROOT)/fit["checkpoint"]
            if digest(checkpoint)!=fit["checkpoint_sha256"]:
                raise AssertionError("Frozen checkpoint identity mismatch")
            model=install(AddressedModel(core)).eval()
            model.load_state_dict(torch.load(checkpoint,weights_only=True,map_location="cpu"))
            begin=time.process_time();logits=predict(model,arrays)
            inference_cpu=time.process_time()-begin
            before=softmax(logits.astype(float),axis=-1)
            begin=time.process_time();after=calibrate(task,arrays["x"],arrays["observed"],before)
            repair_cpu=time.process_time()-begin
            original=next(r for r in previous["records"] if
                (r["task"],r["core"],r["seed"],r["condition"])==(task,core,seed,"missing"))
            before_stats=metrics(before[query],labels,available)
            reproduced=all(before_stats[key]==original[key] for key in
                           ("accuracy","available_accuracy","unavailable_accuracy"))
            if not reproduced:
                raise AssertionError("Old observed accuracy did not reproduce")
            path=out/f"{task}_{core}_{seed}.npz"
            np.savez_compressed(path,logits=logits[query],corrected=after[query],labels=labels,
                available=available,episode=np.where(query)[0],position=np.where(query)[1])
            records.append(dict(task=task,core=core,seed=seed,before=before_stats,
                after=metrics(after[query],labels,available),old_accuracy_reproduced=reproduced,
                checkpoint_sha256=fit["checkpoint_sha256"],raw_sha256=digest(path),
                inference_cpu_seconds=inference_cpu,repair_cpu_seconds=repair_cpu))
            # A no-erasure batch passes through bit for bit for both real models.
            base=data.batch(task,32,872991,"dev","base")
            probability=softmax(predict(model,base).astype(float),axis=-1)
            same=np.array_equal(probability,calibrate(task,base["x"],base["observed"],probability))
            if not same: raise AssertionError("Observed-content probabilities changed")
            roundtrips.append(dict(task=task,core=core,seed=seed,unchanged=same))
            print(json.dumps(records[-1]),flush=True)
    # Compare Bayesian action values with actual acquisition on fresh DEV worlds.
    actions=[]
    for task in data.CONTENT_TASKS:
        full=data.batch(task,128,190012,"dev","base")
        stop,read,prices,removed=data.read_opportunity(task,128,190012,"dev")
        prelude=stop["x"].shape[1]-4
        gain,stop_quality,read_quality=[],[],[]
        for row in range(128):
            p=infer(task,stop["x"][row,:prelude],stop["observed"][row,:prelude])
            # This is the actual environment-supplied delayed raw WRITE.
            raw=read["x"][row,prelude+1]
            q=p.acquire(raw)
            queries=stop["x"][row,prelude:]
            target=stop["y"][row,prelude:]
            stop_quality.append(np.mean([p.query(x).argmax() for x in queries]==target))
            read_quality.append(np.mean([q.query(x).argmax() for x in queries]==target))
            gain.append(p.value_of_read())
        gain,stop_quality,read_quality=map(np.asarray,(gain,stop_quality,read_quality))
        choice=gain>prices
        if not np.all(read_quality==1):raise AssertionError("Actual READ failed to recover all four values")
        np.savez_compressed(out/f"{task}_read.npz",**stop,read_x=read["x"],price=prices,
            removed=removed,predicted_gain=gain,choice=choice,stop_quality=stop_quality,read_quality=read_quality)
        actions.append(dict(task=task,episodes=128,mean_gain=float(gain.mean()),
            stop_quality=float(stop_quality.mean()),read_quality=float(read_quality.mean()),
            read_rate=float(choice.mean()),utility=float((np.where(choice,read_quality,stop_quality)-choice*prices).mean()),
            scope="Actual paired DEV successors; labels are used only after action selection"))
    summary=dict(schema="hcsn.missing.posterior.result.v1",base_commit=BASE_COMMIT,
        records=records,reference=prepare,read_actions=actions,nonmissing_checks=roundtrips,
        exact_latent_checks=reference["independent_prefixes"],max_reference_error=reference["maximum_error"],
        source_unchanged=all(digest(ROOT/p)==v for p,v in sources.items()),
        cpu_seconds=time.process_time()-cpu,wall_seconds=time.perf_counter()-start,
        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        torch=torch.__version__,energy_joules=None,
        claim="Shared inference/calibration repair in a known symbolic profile; no analytical gain, new training or full-modal qualification")
    (out/"SUMMARY.json").write_text(json.dumps(summary,indent=2,sort_keys=True,allow_nan=False)+"\n")
    return summary


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args();result=run(args.out)
    print(json.dumps(dict(records=len(result["records"]),source_unchanged=result["source_unchanged"])))
