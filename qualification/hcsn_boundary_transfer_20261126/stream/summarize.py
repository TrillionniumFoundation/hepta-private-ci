"""Independently verify per-window scores and compare paired fits; standard library."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from statistics import mean,median

ARMS=("qvi_raw","qvi_centered","qvi_signed","qvi_joint","learned_centered","fixed_centered","gru","lif","attention")
SEEDS=(601,1601,2601)
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def check_metrics(case,score):
    y,p=case["y"],case["p"]
    balanced=mean([mean((v>=.5)==(k==1) for t,v in zip(y,p) if t==k) for k in (0,1)])
    brier=mean((t-v)**2 for t,v in zip(y,p))
    accuracy=mean(t==int(v>=.5) for t,v in zip(y,p))
    vals={"balanced_accuracy":balanced,"accuracy":accuracy,"brier":brier}
    if any(abs(score[k]-v)>1e-12 for k,v in vals.items()):
        raise ValueError("independent per-window score mismatch")
    return vals

def main():
    parser=argparse.ArgumentParser()
    for key in ("campaign","wall","output"):parser.add_argument("--"+key,type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(exist_ok=True)
    summaries={};rows=[];common=None
    for regime in ("fixed_updates","filled_wall20","wall20_prefix"):
        data=args.wall if regime=="filled_wall20" else args.campaign
        pred=json.loads((data/"predictions.json").read_text())
        result=json.loads((data/"test.json").read_text())
        seal=json.loads((data/"seal.json").read_text())
        by_arm={}
        for arm in ARMS:
            scored=[]
            for seed in SEEDS:
                key=f"{arm}-{seed}"
                is_wall=regime=="filled_wall20"
                fit_file=data/key/"fit.json"
                fit=json.loads(fit_file.read_text())
                receipt=json.loads((data/f"{key}.receipt.json").read_text())
                a=seal[key]["fit"] if is_wall else seal["roster"][key][0]
                if sha(fit_file)!=a or receipt["exit"]!=0:raise ValueError("fit receipt mismatch")
                score=result[key] if is_wall else result[key][regime]
                if score is None:
                    rows.append(dict(regime=regime,arm=arm,seed=seed,status="no_eligible_checkpoint"))
                    continue
                case=pred[key if is_wall else key+"/"+regime]
                vals=check_metrics(case,score)
                identity=(case["id"],case["date"],case["y"])
                if common is None: common=identity
                if common!=identity:raise ValueError("test windows diverged across methods")
                selected=fit["selected_step" if regime!="wall20_prefix" else "wall20_selected_step"]
                row=dict(regime=regime,arm=arm,seed=seed,status="ok",**vals,selected_step=selected,
                         attempted_updates=fit["attempted_updates" if is_wall else "updates"],
                         full_fit_s=receipt["launch_to_exit_s"],
                         quality_gate=vals["balanced_accuracy"]>=.90 and vals["brier"]<=.10)
                if not is_wall and regime=="fixed_updates":
                    definite=[c["seconds"] for c in fit["history"] if c["dev"]["balanced_accuracy"]>=.90
                              and c["dev"]["brier"]<=.10]
                    row["first_dev_crossing_s"]=min(definite) if definite else None
                rows.append(row);scored.append(row)
            if scored:
                by_arm[arm]={key:mean(r[key] for r in scored) for key in ("balanced_accuracy","accuracy","brier","attempted_updates","selected_step")}
                by_arm[arm].update(median_full_fit_s=median(r["full_fit_s"] for r in scored),
                                   passing=sum(r["quality_gate"] for r in scored),admitted=len(scored))
        paired=[]
        for seed in SEEDS:
            pair={r["arm"]:r for r in rows if r["regime"]==regime and r["seed"]==seed and r["status"]=="ok"}
            if "qvi_raw" in pair and "qvi_centered" in pair:
                paired.append(dict(seed=seed,delta_brier=pair["qvi_centered"]["brier"]-pair["qvi_raw"]["brier"],
                                   delta_balanced_accuracy=pair["qvi_centered"]["balanced_accuracy"]-pair["qvi_raw"]["balanced_accuracy"]))
        summaries[regime]={"arms":by_arm,"paired_centered_minus_raw":paired}
    info={"window_count":len(common[0]),"test_days":sorted(set(common[1])),"positives":sum(common[2]),
          "quality_gate":"balanced accuracy >= .90 AND positive-class Brier <= .10 on the same held-out predictions",
          "source":"actual retained probabilities independently recomputed with Python standard library",
          "regimes":summaries,"slots":rows}
    (args.output/"summary.json").write_text(json.dumps(info,indent=2,sort_keys=True,allow_nan=False)+"\n")
    with (args.output/"slots.csv").open("w",newline="") as f:
        keys=sorted(set().union(*(r.keys() for r in rows)))
        writer=csv.DictWriter(f,fieldnames=keys,lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

if __name__=="__main__":main()
