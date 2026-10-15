#!/usr/bin/env python3
"""Independent stdlib replay of genuinely frozen post-stage1 No-Change.

Never imports torch, numpy, the frozen producer or trainer; does not prove
source/model signatures, live time windows, physical hardware or admission.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
from typing import Any

from qualification.cell_meta_execution_af import physical_router_audit as soft_audit
from qualification.cell_meta_execution_af import physical_router_hard_review as hard_audit
from qualification.cell_meta_execution_af import physical_router_top1_review as top1_audit

SCHEMA="hepta.cell-meta-true-frozen-stage1.v1"
PARTS=("old_retention","future_1","future_2","ood")
FIELDS={"schema","source_panel_sha256","hard_predecessor_sha256",
        "control_identity","historical_no_change_semantics",
        "stage1_parent_fp32","stage1_parent_domain_sha256","prediction_sha256",
        "predictions","retrospective_evaluation","brier_minus_historical_unsplit_continued",
        "meters","new_independent_stage1_execution_attested",
        "original_stage1_model_origin_authenticated","true_ood_verified",
        "future_window_prospective","total_compute_matched",
        "independent_ndu_selection_authorized","production_admission","authority_posture"}
FLAGS={"new_independent_stage1_execution_attested":False,
       "original_stage1_model_origin_authenticated":False,
       "true_ood_verified":False,"future_window_prospective":False,
       "total_compute_matched":False,"independent_ndu_selection_authorized":False,
       "production_admission":"BLOCKED","authority_posture":"DENY_ALL"}

class FrozenReviewDenied(ValueError):
    """Incorrect or ungrounded frozen-stage1 counterfactual."""

def ensure(cond:bool,message:str)->None:
    if not cond:raise FrozenReviewDenied(message)

def sigmoid(x:float)->float:
    if x<0:
        a=math.exp(x)
        return a/(1+a)
    return 1/(1+math.exp(-x))

def read_metrics(rows:list[dict],preds:list[dict])->dict[str,float|int]:
    ensure(type(preds) is list and len(preds)==len(rows),"missing frozen predictions")
    ps=[];ys=[]
    for row,pred in zip(rows,preds,strict=True):
        ensure(type(pred) is dict and set(pred)=={"id","probability"} and
               pred["id"]==row["id"],"source-ordered frozen ID required")
        p=pred["probability"]
        ensure(type(p) is float and math.isfinite(p) and 1e-6<=p<=1-1e-6,
               "invalid frozen probability")
        ps.append(p);ys.append(row["label"])
    n=len(ps)
    return {"count":n,
            "accuracy":round(sum(int((p>=.5)==bool(y)) for p,y in zip(ps,ys,strict=True))/n,7),
            "brier":round(sum((p-y)**2 for p,y in zip(ps,ys,strict=True))/n,7),
            "nll":round(-sum(y*math.log(p)+(1-y)*math.log1p(-p)
                             for p,y in zip(ps,ys,strict=True))/n,7)}

def replay(panel:dict[str,Any],soft:dict[str,Any],posthoc:dict[str,Any],
           hard:dict[str,Any],frozen:dict[str,Any])->dict[str,Any]:
    # Originals are independently replayed BEFORE any derived candidate can pass.
    hard_audit.replay(panel,soft,posthoc,hard)
    ensure(type(frozen) is dict and set(frozen)==FIELDS,"frozen report inventory drift")
    for name,value in FLAGS.items():
        ensure(type(frozen[name]) is type(value) and frozen[name]==value,
               "false authority, OOD, compute matching or prospective claim: "+name)
    ensure(frozen["schema"]==SCHEMA and
           frozen["source_panel_sha256"]==soft_audit.digest(panel) and
           frozen["hard_predecessor_sha256"]==soft_audit.digest(hard),
           "frozen source and hard predecessor must be exact")
    ensure(frozen["control_identity"]=="frozen_stage1_no_second_phase_learning" and
           frozen["historical_no_change_semantics"]=="unsplit_continued_stage2_update",
           "historical unsplit-continuation is not a frozen no-change policy")
    width=panel["source"]["dim"]
    old=hard["results"][0]["stage1_parent_fp32"]
    ensure(all(x["stage1_parent_fp32"]==old for x in hard["results"]),
           "split arms disagree on common stage1 parent")
    ensure(frozen["stage1_parent_fp32"]==old,"frozen Head did not use stage1 weights")
    shape=old["shape"]
    hex_values=old["data_le_hex"]
    ensure(shape==[width+1] and type(hex_values) is str and
           len(hex_values)==8*(width+1) and
           all(ch in "0123456789abcdef" for ch in hex_values),
           "not an exact FP32 parent tensor")
    raw=bytes.fromhex(hex_values)
    sha=hashlib.sha256(b"hepta.true-frozen.stage1.v1\0"+raw).hexdigest()
    ensure(frozen["stage1_parent_domain_sha256"]==sha,"frozen tensor hash mismatch")
    weights=list(struct.unpack("<"+str(width+1)+"f",raw))
    ensure(all(math.isfinite(x) for x in weights),"nonfinite frozen model weights")
    preds=frozen["predictions"]
    ensure(type(preds) is dict and set(preds)==set(PARTS) and
           frozen["prediction_sha256"]==soft_audit.digest(preds),
           "frozen pre-label prediction seal invalid")
    metrics=frozen["retrospective_evaluation"]
    diffs=frozen["brier_minus_historical_unsplit_continued"]
    ensure(type(metrics) is dict and set(metrics)==set(PARTS) and
           type(diffs) is dict and set(diffs)==set(PARTS),
           "missing frozen comparison cohorts")
    n_eval=0;delta={}
    for part in PARTS:
        rows=panel["partitions"][part]
        evaluations=preds[part]
        reference=read_metrics(rows,evaluations)
        score=metrics[part]
        ensure(type(score) is dict and set(score)==set(reference) and
               type(score["count"]) is int and score["count"]==reference["count"] and
               all(type(score[k]) in (float,int) and math.isfinite(score[k]) and
                   abs(score[k]-reference[k])<=1e-7
                   for k in ("accuracy","brier","nll")),
               "historical frozen score does not match actual source labels")
        for row,pred in zip(rows,evaluations,strict=True):
            x=row["features"]+[1.0]
            p=sigmoid(sum(a*b for a,b in zip(x,weights,strict=True)))
            p=min(1-1e-6,max(1e-6,p))
            ensure(abs(pred["probability"]-p)<3e-6,
                   "frozen stage1 FP32 inference does not replay")
        computed=round(reference["brier"]-hard["results"][0]["retrospective_evaluation"][part]["brier"],7)
        ensure(type(diffs[part]) is float and math.isfinite(diffs[part]) and
               abs(diffs[part]-computed)<=1e-7,
               "frozen versus unsplit-continued Brier contrast was altered")
        delta[part]=computed
        n_eval+=len(rows)
    meter=frozen["meters"]
    expected={"reused_stage1_train_rows_reported":len(panel["partitions"]["old_train"])*hard["steps_each_stage"],
              "additional_stage2_train_head_rows":0,
              "additional_stage2_optimizer_updates":0,
              "additional_eval_head_rows":n_eval,
              "additional_eval_router_rows":0,
              "frozen_head_payload_bytes_fp32":len(raw)}
    ensure(type(meter) is dict and set(meter)==set(expected)|{"actual_inference_cpu_seconds"},
           "incomplete or unexpected frozen resource receipt")
    for name,expected_value in expected.items():
        ensure(type(meter[name]) is int and meter[name]==expected_value,
               name+": wrong physical frozen budget")
    t=meter["actual_inference_cpu_seconds"]
    ensure(type(t) in (float,int) and math.isfinite(t) and t>=0,
           "invalid untrusted CPU timing")
    return {"outcome":"FROZEN_NO_CHANGE_NUMERIC_REPLAY_NO_AUTHORITY",
            "historical_no_change_is_unsplit_continued_update":True,
            "source_case_predictions_and_fp32_replayed":True,
            "additional_stage2_optimizer_updates":0,
            "additional_frozen_eval_head_rows":n_eval,
            "brier_delta_frozen_minus_continued":delta,
            "actual_host_provenance_attested":False,
            "prospective_ndu_qualified":False,
            "total_compute_matched":False,
            "production_selection_permitted":False,
            "authority_posture":"DENY_ALL"}

def main(argv:list[str]|None=None)->int:
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ("panel","soft_report","posthoc_report","hard_report","frozen_report"):
        parser.add_argument("--"+key.replace("_","-"),type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        p=soft_audit.load(args.panel)
        s=soft_audit.load(args.soft_report)
        t=soft_audit.load(args.posthoc_report)
        h=soft_audit.load(args.hard_report)
        f=soft_audit.load(args.frozen_report)
        print(json.dumps(replay(p,s,t,h,f),sort_keys=True))
        return 0
    except (FrozenReviewDenied,hard_audit.HardReplayDenied,
            soft_audit.AuditError,top1_audit.Top1AuditError,KeyError,
            TypeError,ValueError,OSError,OverflowError,RecursionError) as exc:
        print(f"FROZEN BASELINE NUMERIC REPLAY BLOCKED: {exc}",file=sys.stderr)
        return 2

if __name__=="__main__":
    raise SystemExit(main())
