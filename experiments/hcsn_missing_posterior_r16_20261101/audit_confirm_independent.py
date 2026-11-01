"""Recompute opened confirmation evidence without project inference/statistics.

Only the frozen original data generator is reused to reproduce already-opened
raw tapes. The observer below enumerates every possible erased raw WRITE and
checks the generator's public constraints; it does not import posterior.py,
audit.py, confirm.py, or their metrics/inference/summarization functions.
"""

import argparse
import ast
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy.stats import beta

from experiments.hcsn_addressed_flow_20261101 import data


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
MAX_ERROR = 0.
COMPARISONS = 0


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def close(left, right, tolerance=2e-12):
    global MAX_ERROR, COMPARISONS
    a, b = np.asarray(left), np.asarray(right)
    if a.shape != b.shape or not np.isfinite(a).all() or not np.isfinite(b).all():
        raise AssertionError("Shape or finite-data mismatch")
    error = float(np.max(np.abs(a.astype(float)-b.astype(float)))) if a.size else 0.
    MAX_ERROR, COMPARISONS = max(MAX_ERROR, error), COMPARISONS+a.size
    if error > tolerance:
        raise AssertionError(f"Numerical discrepancy {error} exceeds {tolerance}")


def latent(task, prefix, observed):
    """Enumerate 4 x 8 possible raw missing tokens, without using a target."""
    offset = 4 if task == "binding" else 0
    missing = np.flatnonzero(~observed)
    if len(missing) > 1 or np.any(prefix[~observed]):
        raise AssertionError("Invalid single-erasure history")
    worlds, tokens = [], []
    hypotheses = [(key, value) for key in range(4) for value in range(8)] if len(missing) else [(-1, -1)]
    for key, value in hypotheses:
        completed = prefix.copy()
        if len(missing):
            event = np.zeros(24)
            event[key] = event[4+value] = event[12] = event[16] = 1
            completed[missing[0]] = event
        initial = completed[offset:offset+8]
        writes = initial[initial[:, 12] == 1]
        if len(writes) != 4 or sorted(writes[:, :4].argmax(1)) != list(range(4)):
            continue
        updates = completed[offset+8:]
        if len(updates) != (2 if task == "selective" else 0):
            raise AssertionError("Unexpected public schedule")
        if len(updates) and (not np.all(updates[:, 12] == 1) or len(set(updates[:, :4].argmax(1))) != 2):
            continue
        all_writes = np.concatenate((writes, updates))
        if len(set(all_writes[:, 4:12].argmax(1))) != len(all_writes):
            continue
        final = np.full(4, -1)
        for event in all_writes:
            final[event[:4].argmax()] = event[4:12].argmax()
        worlds.append(final)
        tokens.append((key, value))
    if not worlds:
        raise AssertionError("No compatible latent assignment")
    return np.asarray(worlds), np.asarray(tokens)


def posterior(worlds):
    return np.stack([np.bincount(worlds[:, key], minlength=8)/len(worlds) for key in range(4)])


def query_key(task, prefix, query):
    if task != "binding":
        return int(query[:4].argmax())
    alias = int(query[19:23].argmax())
    bridges = prefix[:4]
    match = bridges[bridges[:, 19+alias] == 1]
    if len(match) != 1:
        raise AssertionError("Alias bridge is not unique")
    return int(match[0, :4].argmax())


def metrics(p, y, available):
    correct = p.argmax(1) == y
    prob = p[np.arange(len(y)), y]
    accepted = p.max(1) >= .9
    return dict(accuracy=float(correct.mean()), available_accuracy=float(correct[available].mean()),
        unavailable_accuracy=float(correct[~available].mean()),
        brier=float(((p-np.eye(8)[y])**2).sum(1).mean()),
        log_loss=float(-np.log(prob).mean()) if np.all(prob > 0) else None,
        zero_target_probability=int(np.sum(prob == 0)), confidence_90_coverage=float(accepted.mean()),
        confidence_90_accuracy=float(correct[accepted].mean()) if accepted.any() else None)


def compare_metrics(actual, saved):
    if set(actual) != set(saved):
        raise AssertionError("Metric fields differ")
    for key, value in actual.items():
        if value is None or saved[key] is None:
            if value is not saved[key]:
                raise AssertionError("Missing-value mismatch")
        else:
            close(value, saved[key])


def run(run_dir, output):
    start = time.process_time()
    summary = json.loads((run_dir/"SUMMARY.json").read_text())
    plan = json.loads((HERE/"CONFIRMATION_PROTOCOL.json").read_text())
    manifest = json.loads((HERE/"SOURCE_MANIFEST.json").read_text())
    freeze = json.loads((run_dir/"FREEZE.json").read_text())
    meter = json.loads((run_dir/"PROCESS_RECEIPT.json").read_text())
    source_before = {name: sha(ROOT/name) for name in manifest["files"]}
    if source_before != manifest["files"] or sha(HERE/"SOURCE_MANIFEST.json") != freeze["source_manifest_sha256"]:
        raise AssertionError("Frozen source identity differs")
    if sha(HERE/"CONFIRMATION_PROTOCOL.json") != freeze["protocol_sha256"]:
        raise AssertionError("Protocol identity differs")
    source_commit = "cf15dfe62476b0081c0d5d329671e345033794c7"
    if any(record["source_commit"] != source_commit for record in (summary, freeze, meter)):
        raise AssertionError("Source commit mismatch")
    if meter["exit_code"] != 0 or meter["source_manifest_sha256"] != freeze["source_manifest_sha256"]:
        raise AssertionError("Fresh process failed or used a different source")
    close(meter["cpu_seconds"], meter["user_cpu_seconds"]+meter["system_cpu_seconds"])
    if meter["cpu_seconds"] < summary["cpu_seconds"] or meter["wall_seconds"] < summary["wall_seconds"]:
        raise AssertionError("Outer process does not enclose inner timing")
    for stream in ("stdout", "stderr"):
        if sha(HERE/meter[stream+"_file"]) != meter[stream+"_sha256"]:
            raise AssertionError("Process log identity mismatch")
    candidates_path = ROOT/"experiments/hcsn_addressed_flow_20261101/results/retention001/ALL_CHECKPOINTS.json"
    if sha(candidates_path) != plan["candidate_manifest_sha256"]:
        raise AssertionError("Candidate set changed")
    candidates = json.loads(candidates_path.read_text())["fits"]
    expected = {(t,c,s) for t in plan["tasks"] for c in plan["cores"] for s in plan["fit_seeds"]}
    if len(candidates) != 18 or {(r["task"],r["core"],r["seed"]) for r in summary["records"]} != expected:
        raise AssertionError("Eighteen-record matrix incomplete")
    weights = {str((Path("frozen_weights")/candidates_path.parent.relative_to(ROOT)/r["checkpoint"])):
               r["checkpoint_sha256"] for r in candidates}
    if weights != summary["checkpoint_hashes"] or any(sha(ROOT/p) != h for p,h in weights.items()):
        raise AssertionError("Checkpoint identities differ")
    rng = np.random.default_rng(plan["bootstrap_seed"])
    rows, bounds, references, read_results, artifacts = [], [], [], [], {}
    for task in plan["tasks"]:
        with np.load(run_dir/f"{task}_inputs.npz", allow_pickle=False) as raw:
            raw = {k: raw[k] for k in raw.files}
        rebuilt = data.batch(task, plan["episodes_per_task"], plan["confirmation_seed"], "confirm", "missing")
        for key, value in rebuilt.items():
            close(raw[key], value, 0.)
        mask = raw["x"][:, :, 13] == 1
        close(mask, raw["query_mask"], 0.)
        labels, available = raw["y"][mask], raw["target_available"][mask]
        first = raw["x"].shape[1]-4
        for index in range(plan["episodes_per_task"]):
            worlds, _ = latent(task, raw["x"][index, :first], raw["observed"][index, :first])
            p = posterior(worlds)
            result = np.array([p[query_key(task, raw["x"][index, :first], query)] for query in raw["x"][index, first:]])
            close(result, raw["reference"][4*index:4*index+4])
            if index < plan["independent_reference_prefixes_per_task"]:
                saved = next(r for r in summary["independent_reference"] if (r["task"],r["episode"]) == (task,index))
                close(len(worlds), saved["latent_worlds"], 0.)
                close(saved["error"], 0., 1e-14)
                references.append(dict(task=task,episode=index,latent_worlds=len(worlds)))
        deltas = {core: [] for core in plan["cores"]}
        exact = raw["reference"]
        uncertain = exact.max(1) < 1
        for core in plan["cores"]:
            for seed in plan["fit_seeds"]:
                file = run_dir/f"{task}_{core}_{seed}.npz"
                with np.load(file, allow_pickle=False) as item:
                    item = {k: item[k] for k in item.files}
                saved = next(r for r in summary["records"] if (r["task"],r["core"],r["seed"]) == (task,core,seed))
                if sha(file) != saved["raw_sha256"]:
                    raise AssertionError("Raw prediction identity mismatch")
                close(item["labels"], labels, 0.); close(item["available"], available, 0.)
                logits = item["logits"].astype(np.float64)
                before = np.exp(logits-logits.max(1, keepdims=True)); before /= before.sum(1, keepdims=True)
                after = item["corrected"]
                close(after[uncertain], exact[uncertain], 0.)
                close(after[~uncertain], before[~uncertain], 0.)
                for name, value in (("before",before),("after",after)):
                    compare_metrics(metrics(value,labels,available),saved[name])
                brier = ((before-np.eye(8)[labels])**2).sum(1)-((after-np.eye(8)[labels])**2).sum(1)
                nll = np.log(after[np.arange(len(labels)),labels]/before[np.arange(len(labels)),labels])
                close(brier,item["brier_reduction"]); close(nll,item["nll_reduction"])
                deltas[core].append(np.stack((brier.reshape(-1,4).mean(1),nll.reshape(-1,4).mean(1)),axis=1))
                accept=(after.max(1)>=plan["abstention_threshold"]).reshape(-1,4)
                errors=((after.argmax(1)!=labels).reshape(-1,4) & accept).any(1)
                included=accept.any(1); successes=int((~errors & included).sum()); failures=int((errors & included).sum())
                lower=float(beta.ppf(.05/18,successes,failures+1)) if successes else 0.
                close(lower,saved["abstention_episode_lower"])
                if (lower>.99) != saved["abstention_pass"]:
                    raise AssertionError("Abstention verdict differs")
                rows.append(dict(task=task,core=core,seed=seed,accepted_episodes=successes+failures,
                                 erroneous_episodes=failures,lower=lower,passed=lower>.99))
                artifacts[str(file.relative_to(HERE))]=sha(file)
        indices=rng.integers(plan["episodes_per_task"],size=(plan["bootstrap_replicates"],plan["episodes_per_task"]))
        for core in plan["cores"]:
            delta=np.mean(deltas[core],axis=0)
            boot=delta[indices].mean(1)
            for col,name in enumerate(("brier","log_loss")):
                lower=float(np.quantile(boot[:,col],plan["family_alpha"]/plan["primary_tests"],method="linear"))
                floor=plan["minimal_brier_reduction" if col==0 else "minimal_log_loss_reduction"]
                saved=next(r for r in summary["proper_scores"] if (r["task"],r["core"],r["metric"])==(task,core,name))
                close(lower,saved["lower"]);close(delta[:,col].mean(),saved["mean_reduction"])
                if (lower>floor)!=saved["passed"]:raise AssertionError("Proper-score verdict differs")
                bounds.append(dict(task=task,core=core,metric=name,lower=lower,floor=floor,passed=lower>floor))
        with np.load(run_dir/f"{task}_read.npz",allow_pickle=False) as raw_read:
            rd={k:raw_read[k] for k in raw_read.files}
        stop,read,prices,removed=data.read_opportunity(task,plan["read_episodes_per_task"],plan["read_seed"],"confirm")
        for key,value in stop.items():close(rd[key],value,0.)
        for key,value in (("read_x",read["x"]),("price",prices),("removed",removed)):close(rd[key],value,0.)
        gains,choices,old_scores,new_scores=[],[],[],[]
        first=stop["x"].shape[1]-4
        for index in range(len(prices)):
            prefix=stop["x"][index,:first]
            worlds,tokens=latent(task,prefix,stop["observed"][index,:first]);p=posterior(worlds)
            expected_after=0.
            for token in np.unique(tokens,axis=0):
                selected=(tokens==token).all(1)
                expected_after+=selected.mean()*posterior(worlds[selected]).max(1).mean()
            gain=expected_after-p.max(1).mean();gains.append(gain);choices.append(gain>prices[index])
            event=rd["read_x"][index,first+1]
            close(event[12],1.,0.)
            selected=(tokens==[event[:4].argmax(),event[4:12].argmax()]).all(1)
            q=posterior(worlds[selected])
            keys=[query_key(task,prefix,event) for event in stop["x"][index,first:]]
            target=stop["y"][index,first:]
            old_scores.append(np.mean(p[keys].argmax(1)==target));new_scores.append(np.mean(q[keys].argmax(1)==target))
        for key,value in (("predicted_gain",gains),("action_read",choices),("stop_quality",old_scores),("read_quality",new_scores)):
            close(value,rd[key])
        if not np.all(np.asarray(new_scores)==1):raise AssertionError("Returned WRITE did not resolve answers")
        saved=next(r for r in summary["read_results"] if r["task"]==task)
        utility=float((np.where(choices,new_scores,old_scores)-np.asarray(choices)*prices).mean())
        close(utility,saved["utility"])
        read_results.append(dict(task=task,episodes=len(prices),actual_read_accuracy=1.,utility=utility))
    if (len(rows),len(bounds),len(references),sum(r["episodes"] for r in read_results))!=(18,12,48,1536):
        raise AssertionError("Incomplete independent review")
    if not all(r["passed"] for r in rows+bounds) or not summary["all_scoped_gates_passed"]:
        raise AssertionError("Scoped acceptance is not supported")
    # Static source ordering corroborates the raw prefix/price-only action replay.
    tree=ast.parse((HERE/"confirm.py").read_text())
    choices_line=min(n.lineno for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
        and isinstance(n.func.value,ast.Name) and n.func.value.id=="choices" and n.func.attr=="append")
    acquire_line=min(n.lineno for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=="acquire")
    if choices_line>=acquire_line:raise AssertionError("Choice follows acquisition in frozen source")
    if any(sha(ROOT/p)!=h for p,h in source_before.items()) or any(sha(ROOT/p)!=h for p,h in weights.items()):
        raise AssertionError("Source or checkpoint drift during independent audit")
    receipt=dict(schema="hcsn.missing.independent.confirmation.audit.v1",passed=True,
        source_commit=source_commit,source_manifest_sha256=sha(HERE/"SOURCE_MANIFEST.json"),
        audit_source_sha256=sha(__file__),protocol_sha256=sha(HERE/"CONFIRMATION_PROTOCOL.json"),
        original_summary_sha256=sha(run_dir/"SUMMARY.json"),outer_receipt_sha256=sha(run_dir/"PROCESS_RECEIPT.json"),
        source_and_all_18_weights_unchanged=True,independently_enumerated_prefixes=3072,
        recorded_reference_prefixes=references,proper_score_bounds=bounds,abstention=rows,actual_reads=read_results,
        numerical_elements_checked=COMPARISONS,maximum_absolute_difference=MAX_ERROR,
        causal_choice_source_lines=dict(choice=choices_line,acquire=acquire_line),artifacts=artifacts,
        original_entire_process_cpu_seconds=meter["cpu_seconds"],independent_audit_cpu_seconds=time.process_time()-start,
        scope="Reanalysis of the one opened confirmation_01. No new holdout, retraining or project inference/statistics helper imports. Fixed-checkpoint known-generator repair only.")
    with output.open("x") as handle:json.dump(receipt,handle,indent=2,sort_keys=True,allow_nan=False)
    print(json.dumps({k:receipt[k] for k in ("passed","independently_enumerated_prefixes","numerical_elements_checked","maximum_absolute_difference","independent_audit_cpu_seconds")}))


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--run",type=Path,default=HERE/"confirmation_01")
    parser.add_argument("--output",type=Path,default=HERE/"INDEPENDENT_CONFIRMATION_AUDIT.json")
    args=parser.parse_args();run(args.run,args.output)
