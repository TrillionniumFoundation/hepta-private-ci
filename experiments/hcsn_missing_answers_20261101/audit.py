"""Independent NumPy record/metric audit; imports no campaign code."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def load(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument("--run",type=Path,required=True);a=p.parse_args()
    out=a.run; root=out.parents[3]; summary=load(out/"confirmation/SUMMARY.json")
    protocol=load(out/"PROTOCOL.json");candidates=load(out/"ALL_CHECKPOINTS.json")
    calibrated=load(out/"ALL_CALIBRATIONS.json");checks=0
    assert len(candidates["fits"])==18 and not candidates["failures"]
    assert sha(out/"ALL_CALIBRATIONS.json")==summary["calibration_sha256"]
    assert sha(out/"ALL_CHECKPOINTS.json")==summary["identity"]["candidate_sha256"]
    for path,digest in protocol["source_hashes"].items():
        assert sha(root/path)==digest;checks+=1
    for row in candidates["fits"]:
        assert sha(out/row["checkpoint"])==row["checkpoint_sha256"];checks+=1
    for task in protocol["tasks"]:
        for seed in protocol["fit_seeds"]:
            streams={r["input_stream_sha256"] for r in candidates["fits"] if r["task"]==task and r["seed"]==seed}
            assert len(streams)==1;checks+=1
    calibration={(r["task"],r["core"],r["seed"],r["version"]):r["calibration"] for r in calibrated["records"]}
    grouped={}; identities={}; seen=set()
    for row in summary["records"]:
        key=tuple(row[k] for k in ("task","core","seed","version","condition"))
        assert key not in seen;seen.add(key)
        path=out/"confirmation"/row["raw_file"]
        assert sha(path)==row["raw_sha256"]
        raw=np.load(path,allow_pickle=False);logits=raw["logits"].astype(np.float64)
        labels=raw["labels"];available=raw["available"];cal=calibration[key[:4]]
        v=logits/cal["temperature"];e=np.exp(v-v.max(-1,keepdims=True));prob=e/e.sum(-1,keepdims=True)
        assert np.allclose(prob,raw["probabilities"],rtol=0,atol=1e-14)
        accepted=prob.max(-1)>=cal["threshold"];assert np.array_equal(accepted,raw["accepted"])
        correct=prob.argmax(-1)==labels;nll=-np.log(prob[np.arange(len(labels)),labels].clip(1e-15))
        brier=((prob-np.eye(8)[labels])**2).sum(-1)
        values=dict(accuracy=correct.mean(),all4=correct.reshape(-1,4).all(-1).mean(),
            nll=nll.mean(),brier=brier.mean(),coverage=accepted.mean())
        for name,value in values.items():assert abs(float(value)-row["metrics"][name])<1e-12
        selective=dict(accepted_correctness=float(correct[accepted].mean()) if accepted.any() else None,
            accepted_known_coverage=float(accepted[available].mean()) if available.any() else None,
            accepted_unavailable_rate=float(accepted[~available].mean()) if (~available).any() else None)
        for name,value in selective.items():
            assert value is None and row["metrics"][name] is None or value is not None and abs(value-row["metrics"][name])<1e-12
        for name,mask in (("known",available),("unavailable",~available)):
            metric=row["metrics"][name]
            if mask.any():
                assert metric["count"]==int(mask.sum())
                for k,v in dict(accuracy=correct[mask].mean(),nll=nll[mask].mean(),brier=brier[mask].mean(),
                        mean_confidence=prob.max(-1)[mask].mean()).items():
                    assert abs(float(v)-metric[k])<1e-12
        identity=(row["task"],row["seed"],row["condition"])
        if identity in identities:assert identities[identity]==row["data_sha256"]
        identities[identity]=row["data_sha256"]
        grouped[key]=row["metrics"];checks+=16
    assert len(seen)==144
    effects=[]
    for task in protocol["tasks"]:
        for core in protocol["cores"]:
            for condition in protocol["confirmation"]["conditions"]:
                pairs=[(grouped[task,core,s,"missing_trained",condition],grouped[task,core,s,"historical_base_only",condition]) for s in protocol["fit_seeds"]]
                deltas={name:[new[name]-old[name] for new,old in pairs] for name in ("accuracy","nll","brier","coverage")}
                effects.append(dict(task=task,core=core,condition=condition,
                    candidate_mean={name:float(np.mean([new[name] for new,_ in pairs])) for name in deltas},
                    baseline_mean={name:float(np.mean([old[name] for _,old in pairs])) for name in deltas},
                    candidate_minus_baseline={name:dict(mean=float(np.mean(v)),min=float(min(v)),max=float(max(v))) for name,v in deltas.items()}))
    candidate_rows=[r for r in summary["records"] if r["version"]=="missing_trained"]
    quality=all(r["metrics"]["known"]["accuracy"]>=protocol["gates"]["known_accuracy_min"] for r in candidate_rows)
    selective=all(r["metrics"]["accepted_correctness"] is not None
        and r["metrics"]["accepted_correctness"]>=protocol["gates"]["accepted_correctness_min"]
        and r["metrics"]["accepted_known_coverage"]>=protocol["gates"]["accepted_known_coverage_min"] for r in candidate_rows)
    improvements={}
    for metric in ("brier","nll"):
        improvements[metric]=all(
            grouped[t,co,s,"missing_trained",cond][metric]<grouped[t,co,s,"historical_base_only",cond][metric]
            for t in protocol["tasks"] for co in protocol["cores"] for s in protocol["fit_seeds"]
            for cond in ("missing","missing_tokens_128"))
    verdict=dict(known_accuracy_gate=quality,abstention_accuracy_and_coverage_gate=selective,
        all_missing_brier_improved=improvements["brier"],all_missing_nll_improved=improvements["nll"],
        registered_restricted_criteria_pass=quality and selective and all(improvements.values()),
        analytic_advantage_established=False,all_blockers_closed=False)
    result=dict(passed=True,checks=checks,records=len(seen),effects=effects,verdict=verdict,
        raw_scope="Saved query outputs, probabilities, scoring masks and declared paired input hashes; no independent environment oracle",
        reliability_scope="Dev Wilson bound is a threshold-selection heuristic over correlated queries and scanned thresholds; no population certificate",
        candidate_sha256=sha(out/"ALL_CHECKPOINTS.json"),summary_sha256=sha(out/"confirmation/SUMMARY.json"))
    with (out/"INDEPENDENT_RECORD_AUDIT.json").open("x") as f:json.dump(result,f,indent=2);f.write("\n")
    print(json.dumps(dict(passed=True,checks=checks,records=len(seen)),sort_keys=True))


if __name__=="__main__":main()
