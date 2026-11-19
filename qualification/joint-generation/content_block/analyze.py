"""Saved TRAIN-only endpoints and complete group costs; no model execution."""

import json
from pathlib import Path
import sys
import time

import numpy as np

from content_block.run import PRIOR, SEEDS
from independent.evaluation import paired_interval
from independent.run import write_json


def analyze(run):
    started=time.process_time()
    run=Path(run)
    build=json.loads((run/"build.json").read_text())
    result=json.loads((run/"train-result.json").read_text())
    old=json.loads((PRIOR/"train-result.json").read_text())
    arrays=result["per_row"]
    arrays.update(old_A=old["per_row"]["A"],old_H=old["per_row"]["H"])
    comparisons={}
    for left,right in (("A_alt","H_alt"),("A_alt","A_joint"),("H_alt","H_joint"),
                       ("A_joint","H_joint"),("A_alt","old_A"),("H_alt","old_H")):
        comparisons[left+"-"+right]={metric:paired_interval([r[metric] for r in arrays[left]],[r[metric] for r in arrays[right]],
            build["inner_rows_source_ids"],seeds=list(SEEDS),replicates=2000,bootstrap_seed=77431)
            for metric in ("task_utility","joint_success","greedy_joint_success")}
    ref=build["calibration"]["cpu_ns"]/64
    groups={}
    for group,reports in result["reports"].items():
        cpu=build["costs"][group]["complete_cpu"]
        means={k:float(np.mean([r["means"][k] for r in reports])) for k in reports[0]["means"]}
        means["cpu_net_utility"]=float(np.mean([r["means"]["task_utility"]-.02*(
            r["service"]["cpu_ns"]/r["service"]["rows"]+r["service"]["prepare_cpu_ns"]/100000+
            cpu*1e9/3/100000)/ref for r in reports]))
        chosen=[c for c in build["candidates"][group] if c["lr"]==result["selected"][group]["lr"]]
        groups[group]={"means":means,"complete_cpu":cpu,"units":build["ledgers"][group]["consumed_units"],
            "selected":result["selected"][group],"selected_updates":[c["updates"] for c in chosen],
            "selected_encoder_updates":[c["update_types"]["joint"] for c in chosen],
            "all_candidate_updates":sum(c["updates"] for c in build["candidates"][group]),
            "per_seed_means":[r["means"] for r in reports]}
    metric_ok=all(comparisons[contrast][metric]["mean"]>0 for contrast in ("A_alt-H_alt","A_alt-A_joint","A_alt-old_A")
                  for metric in ("task_utility","joint_success"))
    greedy_drop=max(float(np.max(np.mean(np.array([r["greedy_joint_success"] for r in arrays[right]])-
                      np.array([r["greedy_joint_success"] for r in arrays[left]]),axis=1)))
                    for left,right in (("A_alt","H_alt"),("A_alt","A_joint"),("A_alt","old_A")))
    report={"scope":"selected TRAIN inner-validation; descriptive intervals, no formal confirmation", "groups":groups,
        "comparisons":comparisons,"train_readiness":bool(metric_ok and greedy_drop<=.02),
        "maximum_greedy_drop":greedy_drop,"reference_cpu_ns":ref,
        "current_wave_cpu_net_A_alt_minus_A_joint":groups["A_alt"]["means"]["cpu_net_utility"]-groups["A_joint"]["means"]["cpu_net_utility"],
        "old_CPU_comparability":"different timing wave; no CPU superiority comparison against old saved costs",
        "analysis_cpu_before_receipt":time.process_time()-started}
    write_json(run/"analysis.json",report)
    print(json.dumps(report,indent=2))
    return 0 if report["train_readiness"] else 2


if __name__=="__main__": raise SystemExit(analyze(sys.argv[1]))
