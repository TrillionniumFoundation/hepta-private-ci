"""Saved exact-law TRAIN results only. No model execution or new selection."""

import json
from pathlib import Path
import sys
import time

import numpy as np


def analyze(run):
    start=time.process_time();run=Path(run)
    b=json.loads((run/"build.json").read_text())
    if b["execution_exit_code"]!=0:raise ValueError("probe execution failed; inspect its retained failure")
    reference=next(r for r in b["service"]["H"] if r["profile"]=="identity" and r["model_seed"]==11)["CPU_ns"]/64
    families={};ready=True
    for family in ("H","A"):
        summaries=b["quality"][family]
        values={tau:{name:float(np.mean([summaries[str(s)][tau]["means"][name] for s in (11,23,47)]))
                     for name in summaries["11"][tau]["means"]} for tau in ("zero","log2","infinity")}
        primary={name:values["log2"][name]-values["infinity"][name] for name in values["log2"]}
        greedy_drop=max(summaries[str(s)]["infinity"]["greedy_joint_success"]-summaries[str(s)]["log2"]["greedy_joint_success"] for s in (11,23,47))
        passed=primary["ce"]>0 and primary["joint_success"]>0 and greedy_drop<=.02
        ready=ready and passed
        runtime={}
        for profile in ("Q_zero","T_zero","Q_log2","T_log2","Q_infinity","identity"):
            reports=[r for r in b["service"][family] if r["profile"]==profile]
            tau=reports[0]["tau"]
            cpu=float(np.mean([r["CPU_ns"]/r["rows"] for r in reports]))
            work=float(np.mean([r["work_units"]/r["rows"] for r in reports]))
            runtime[profile]={"CPU_ns_per_request":cpu,"units_per_request":work,
                "complete_CPU_net_CE":values[tau]["ce"]-.02*(cpu+b["costs"][family]["complete_CPU"]*1e9/3/100000)/reference,
                "exact_law_CE":values[tau]["ce"],"observed_requests":sum(r["rows"] for r in reports)}
        families[family]={"means":values,"primary_log2_minus_KEEP":primary,"greedy_drop":greedy_drop,
            "TRAIN_decoding_readiness":bool(passed),"runtime":runtime,"costs":b["costs"][family],
            "complete_units":b["ledgers"][family]["consumed_units"],
            "added_units":b["ledgers"][family]["consumed_units"]-b["ledgers"][family]["stages"]["inherited_nine_candidate_build"]["consumed_units"]}
    report={"families":families,"primary_TRAIN_decoding_readiness":bool(ready),"reference_CPU_ns":reference,
        "scope":"fixed already-trained models; joint decoding only; no training or dynamic-over-best-static system claim",
        "formal_confirmation":False,"descriptive_analysis_CPU":time.process_time()-start}
    (run/"analysis.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps(report,indent=2))
    return 0 if ready else 2


if __name__=="__main__":raise SystemExit(analyze(sys.argv[1]))
