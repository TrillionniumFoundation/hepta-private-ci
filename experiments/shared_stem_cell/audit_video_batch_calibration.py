"""Torch-free, independent replay of microbatch-native video calibration and costs.

Unlike a duplicate model-run, this checks the archived policy decision arithmetic,
source boundaries, physical cache grouping and heldout route traces using only
JSON and Python. It cannot attest actual external encoder forwards, independence
of the tiny public cohort, target hardware acceleration or production quality.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from experiments.shared_stem_cell import audit_video_batch as b
from experiments.shared_stem_cell import audit_video_value as v

FAMILIES = ("confidence", "value", "cache_value")


def sha(obj):
    return hashlib.sha256((json.dumps(obj, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=False, allow_nan=False) + "\n").encode()).hexdigest()


def replay(exits, ids, policy, coef, batch_size=4):
    n=len(ids)
    v.need(n>0 and len(exits)==4 and all(len(exits[d])==n for d in v.DEPTHS)
           and all(len(row)==8 for row in ids),"complete batch calibration inputs")
    kind=policy["kind"]
    known=set();calls=hits=requested=0
    picks=[None]*n
    for start in range(0,n,batch_size):
        active=list(range(start,min(start+batch_size,n)))
        for d in v.DEPTHS:
            if not active: break
            requested_keys=[k for i in active for k in ids[i][d-2:d]]
            fresh=set(requested_keys)-known
            calls+=int(bool(fresh));hits+=sum(k in known for k in requested_keys)
            requested+=len(requested_keys);known.update(fresh)
            continuing=[]
            for i in active:
                p=exits[d][i]; guess=v.argmax(p)
                marginal=int(any(k not in known for k in ids[i][d:d+2])) if d<8 else None
                est=v.value_est(p,d,coef) if d<8 and kind in ("value","cache_value") else None
                stop=(d==8 or kind=="fixed" and d>=policy["depth"]
                      or kind=="confidence" and max(p)>=policy["threshold"]
                      or kind=="value" and est<=policy["price"]
                      or kind=="cache_value" and est<=v.STEP_PRICE+policy["price"]*marginal)
                if stop:picks[i]=(d,guess)
                else: continuing.append(i)
            active=continuing
    v.need(all(pick is not None for pick in picks),"incomplete batch schedule")
    return {"picks":picks,"physical_video_calls":calls,"unique_frames":len(known),
            "cache_hits":hits,"requested_frame_rows":requested,
            "schedule":"fifo_microbatch_depth_synchronous","batch_size":batch_size}


def calibrate(selection, coef):
    ids=selection["calibration_frame_sha256s"]
    labels=selection["calibration_labels"]
    exits={int(k):val for k,val in selection["calibration_exits"].items()}
    v.need(len(ids)==len(labels)==16 and all(len(row)==8 for row in ids),"closed calibration source records")
    def profile(policy):
        raw=replay(exits,ids,policy,coef);picks=raw.pop("picks")
        return {**raw,"correct":sum(guess==label for (_,guess),label in zip(picks,labels)),
                "cases":len(labels),"mean_depth":sum(d for d,_ in picks)/len(labels)}
    def key(p,i):
        return (p["physical_video_calls"],p["unique_frames"],p["requested_frame_rows"],-p["correct"],i)
    fixed={str(d):profile({"kind":"fixed","depth":d}) for d in v.DEPTHS}
    floor=max(p["correct"] for p in fixed.values())
    best=min(v.DEPTHS,key=lambda d:(-fixed[str(d)]["correct"],*key(fixed[str(d)],d)[:3],d))
    policies,profiles,grids={},{},{}
    for family,settings in (("confidence",v.THRESHOLDS),("value",v.COSTS),("cache_value",v.COSTS)):
        field="threshold" if family=="confidence" else "price"
        grid=[{"setting":float(x),**profile({"kind":family,field:float(x)})} for x in settings]
        good=[i for i,row in enumerate(grid) if row["correct"]>=floor]
        if good:
            i=min(good,key=lambda j:key(grid[j],j))
            policies[family]={"kind":family,field:float(settings[i])}
            profiles[family]=grid[i]
        else:
            policies[family]={"kind":"fixed","depth":best,
                "fallback_reason":"did_not_reach_best_fixed_microbatch_calibration_correct_count"}
            profiles[family]=fixed[str(best)]
        grids[family]=grid
    arms={**{f"fixed_{d}":fixed[str(d)] for d in v.DEPTHS},**profiles}
    names=tuple(f"fixed_{d}" for d in v.DEPTHS)+FAMILIES
    best_arm=min(arms,key=lambda arm:(*key(arms[arm],0)[:-1],
        0 if arm.startswith("fixed_") else 1,names.index(arm)))
    return {"schema":"hepta.video-batch-calibration.v1","batch_size":4,
        "research_best_arm":best_arm,"research_best_policy":(
            {"kind":"fixed","depth":int(best_arm.split("_")[1])}
            if best_arm.startswith("fixed_") else policies[best_arm]),
        "schedule":"fifo_microbatch_depth_synchronous",
        "best_fixed_depth":best,"best_fixed_correct":floor,
        "fixed_profiles":fixed,"grids":grids,"policies":policies,
        "family_profiles":profiles,"selection_uses_holdout_labels":False,
        "critic_retrained":False,"reader_retrained":False,
        "same_calibration_cohort_as_scalar_choice":True,
        "population_nonregression_certified":False,"production_accepted":False}


def audit_native_arm(study,cases,policy,coef,model_id):
    rows,events,groups=study["records"],study["events"],study["groups"]
    v.need(len(rows)==len(cases) and len(groups)==(len(cases)+3)//4
           and study["schedule"]=="fifo_microbatch_depth_synchronous", "native group shape")
    seen=set();calls=hits=requested=0;event_id=0
    for block_i,group in enumerate(groups):
        offset=4*block_i
        group_cases=cases[offset:offset+4]
        v.need(group["case_ids"]==[c["case_id"] for c in group_cases]
               and group["microbatch_size"]==len(group_cases)
               and group["wall"]["wall_ns"]>0,"microbatch group identity/work")
        active=list(range(len(group_cases)))
        for d in v.DEPTHS:
            if not active:break
            v.need(event_id<len(events),"native missing physical event")
            event=events[event_id]
            names=[group_cases[i]["case_id"] for i in active]
            keys=[ref["sha256"] for i in active for ref in group_cases[i]["inputs"]["video"][d-2:d]]
            fresh=set(keys)-seen
            called=int(bool(fresh))
            v.need(event["batch"]==block_i and event["depth"]==d
                   and event["case_ids"]==names and event["requested_frames"]==len(keys)
                   and event["physical_video_calls"]==called
                   and event["charged_once_to_batch"] is True
                   and event["wall"]["wall_ns"]>0,"native physical event/count drift")
            hits+=sum(k in seen for k in keys)
            seen.update(fresh);calls+=called;requested+=len(keys)
            upcoming=[]
            for i in active:
                row=rows[offset+i];case=group_cases[i]
                v.need(row["case_id"]==case["case_id"] and row["scope"]==case["scope"]
                       and row["model_sha256"]==model_id
                       and row["input_digest"]==sha([case["scope"],case["inputs"]]),
                       "native row/source/model identity drift")
                visits=row["exits_seen"]
                v.need(len(visits)>d//2-1 and visits[d//2-1]["depth"]==d
                       and visits[d//2-1]["shared_batch_event_id"]==event_id,
                       "native reader trace order drift")
                info=visits[d//2-1];p=info["probabilities"];guess=v.argmax(p)
                estimate=v.value_est(p,d,coef) if d<8 and policy["kind"] in ("value","cache_value") else None
                marginal=int(any(x not in seen for x in [r["sha256"] for r in case["inputs"]["video"]][d:d+2])) if d<8 and policy["kind"]=="cache_value" else None
                price=v.STEP_PRICE+policy["price"]*marginal if marginal is not None else None
                v.need(info["next_pair_physical_calls_if_continued"]==marginal
                       and info["next_pair_price_accuracy_units"]==price,
                       "native marginal cache price drift")
                if estimate is None:
                    v.need(info["critic_value_estimate"] is None,"native unexpected critic")
                else:
                    v.need(abs(estimate-info["critic_value_estimate"])<1e-5,"native critic estimate drift")
                stop=(d==8 or policy["kind"]=="fixed" and d>=policy["depth"]
                      or policy["kind"]=="confidence" and max(p)>=policy["threshold"]
                      or policy["kind"]=="value" and estimate<=policy["price"]
                      or policy["kind"]=="cache_value" and estimate<=price)
                if stop:
                    v.need(row["depth"]==d and row["prediction"]==guess
                           and row["probabilities"]==p and len(visits)==d//2,
                           "native selected depth/prediction drift")
                else:upcoming.append(i)
            event_id+=1;active=upcoming
    v.need(event_id==len(events),"native unexpected physical event")
    ledger=study["physical_work"]
    v.need(ledger["unique_frames"]==len(seen) and ledger["physical_video_calls"]==calls
           and ledger["cache_hits"]==hits and ledger["requested_frame_rows"]==requested
           and ledger["batch_size_limit"]==4 and ledger["microbatches"]==len(groups)
           and ledger["isolated_cache"] is True and ledger["tower_calls_are_shared_not_per_cell"] is True,
           "native physical ledger drift")
    return {"cases":len(cases),"correct":sum(a["prediction"]==c["label"] for a,c in zip(rows,cases)),
            "physical_video_calls":calls,"unique_frames":len(seen),"requested_frame_rows":requested}


def audit(root):
    root=Path(root)
    base=b.audit(root)  # first verify all old scalar and microbatch controls
    report=v.load(root/"value/report.json")
    selection=v.load(root/"value/selection.json",report["selection_sha256"])
    coef=v.verify_critic(selection)
    derived=calibrate(selection,coef)
    stored=selection.get("microbatch_calibration")
    v.need(stored==derived,"schedule-matched calibration changed")
    plan=v.load(root/"value/batch/plan.json")
    v.need(plan.get("batch_native") is True and plan.get("batch_calibration_sha256")==sha(stored),
           "pre-heldout microbatch policy seal missing")
    saved=v.load(root/"value/batch/predictions.json",report["microbatch_shadow"]["predictions_sha256"])
    native=saved.get("batch_native")
    v.need(isinstance(native,dict) and set(native)==set(FAMILIES),"native microbatch arms incomplete")
    manifest=v.load(root/"manifest.json");dataset=manifest["dataset"]
    raw=(root/dataset["path"]).read_bytes()
    v.need(hashlib.sha256(raw).hexdigest()==dataset["sha256"],"native dataset identity")
    cases=[json.loads(x) for x in raw.splitlines() if x.strip()]
    holdout=[c for c in cases if c["split"]=="holdout"]
    v.need(len(holdout)==16 and saved["case_ids"]==[c["case_id"] for c in holdout],
           "source-disjoint heldout coverage")
    results={};total=0
    for family in FAMILIES:
        v.need(v.load(root/f"value/batch/batch-native-{family}.json")==native[family],
               "individual native arm seal changed")
        stats=audit_native_arm(native[family],holdout,stored["policies"][family],coef,
                               selection["model_sha256"])
        q=report["microbatch_native_scores"][family]
        accuracy=stats["correct"]/len(holdout)
        loss=sum(-math.log(max(1e-8,row["probabilities"][case["label"]]))
                 for row,case in zip(native[family]["records"],holdout))/len(holdout)
        v.need(q["cases"]==16 and q["correct"]==stats["correct"]
               and abs(q["accuracy"]-accuracy)<1e-6 and abs(q["nll"]-loss)<1e-4,
               "native postseal scoring changed")
        total+=stats["physical_video_calls"];results[family]=stats
    v.need(report["microbatch_shadow"]["batch_calibrated_before_holdout"] is True
           and report["microbatch_shadow"]["batch_native_extra_calls"]==total
           and report["microbatch_native_total_extra_calls"]==total
           and report["all_batched_shadow_total_extra_calls"]==total+base["extra_shadow_calls"],
           "native vs total shadow call accounting drift")
    return {"status":"independent_archived_consistency_only","batch_native":results,
            "batch_native_extra_calls":total,"legacy_batch_extra_calls":base["extra_shadow_calls"],
            "actual_external_CLIP_execution_attested":False,
            "population_nonregression_certified":False,"production_accepted":False}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,required=True)
    print(json.dumps(audit(parser.parse_args().root),sort_keys=True))
