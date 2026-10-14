"""Pure stdlib audit of value-of-information video source/route/cost evidence.

Recomputes a fixed ridge solution and policy from sealed predictions; cannot
attest physical GPU/CPU work or independence of real media populations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

DEPTHS = (2, 4, 6, 8)
COSTS = (0., .005, .02, .05, .1, .2)
THRESHOLDS = (0., .55, .65, .75, .85, .95, 1.01)
ARMS = ("value", "cache_value", "confidence", "fixed_2", "fixed_4", "fixed_6", "fixed_8")
STEP_PRICE = .005
RIDGE = .5


def need(ok, why):
    if not ok: raise ValueError(why)


def load(path, digest=None):
    raw = path.read_bytes()
    if digest is not None: need(hashlib.sha256(raw).hexdigest() == digest, "SHA mismatch: " + str(path))
    return json.loads(raw)


def argmax(p):
    need(isinstance(p, list) and len(p) == 2 and all(type(x) in (float, int)
         and math.isfinite(x) and 0 <= x <= 1 for x in p)
         and abs(sum(p)-1) <= 1e-5, "invalid binary probabilities")
    return 0 if p[0] >= p[1] else 1


def vector(p, depth):
    argmax(p)
    entropy = -sum(x*math.log(max(x,1e-12)) for x in p)/math.log(2.)
    return [1., max(p), abs(p[0]-p[1]), entropy, depth/8.]


def solve(matrix, rhs):
    augmented = [list(row)+[y] for row,y in zip(matrix,rhs)]
    n=len(rhs)
    for j in range(n):
        pivot=max(range(j,n),key=lambda i:abs(augmented[i][j]))
        augmented[j],augmented[pivot]=augmented[pivot],augmented[j]
        div=augmented[j][j]
        need(abs(div)>1e-10,"singular critic ridge")
        augmented[j]=[x/div for x in augmented[j]]
        for i in range(n):
            if i==j: continue
            k=augmented[i][j]
            augmented[i]=[a-k*b for a,b in zip(augmented[i],augmented[j])]
    return [augmented[i][-1] for i in range(n)]


def verify_critic(selection):
    c=selection["critic"]
    need(c["schema"]=="hepta.video-value-critic.v1" and c["ridge"]==RIDGE,"critic contract")
    labels=selection["critic_labels"]
    exits={int(k):v for k,v in selection["critic_exits"].items()}
    need(set(exits)==set(DEPTHS) and all(len(exits[d])==len(labels) for d in DEPTHS),"critic source coverage")
    result={}
    for d in DEPTHS[:-1]:
        x=[vector(p,d) for p in exits[d]]
        y=[int(argmax(f)==l)-int(argmax(p)==l)
           for f,p,l in zip(exits[d+2],exits[d],labels)]
        gram=[[sum(row[i]*row[j] for row in x) + (RIDGE if i==j else 0.)
               for j in range(5)] for i in range(5)]
        rhs=[sum(row[i]*v for row,v in zip(x,y)) for i in range(5)]
        calc=solve(gram,rhs)
        saved=c["coefficients"][str(d)]
        need(len(saved)==5 and max(abs(a-b) for a,b in zip(calc,saved))<1e-5,
             "critic coefficients changed")
        details=c["diagnostics"][str(d)]
        need(details["rows"]==len(y) and details["target_positive"]==y.count(1)
             and details["target_negative"]==y.count(-1)
             and abs(details["target_mean_next_pair_correctness_change"]-sum(y)/len(y))<1e-8,
             "critic train target record drift")
        result[d]=saved
    return result


def value_est(p,d,coef):
    return max(-1.,min(1.,sum(a*b for a,b in zip(vector(p,d),coef[d]))))


def picks(exits,kind,setting,coef, frame_ids=None):
    n=len(exits[2]); out=[]; cache=set()
    if kind=="cache_value":
        need(isinstance(frame_ids,list) and len(frame_ids)==n,"cache-value frame ids")
    for i in range(n):
        for d in DEPTHS:
            p=exits[d][i]
            if kind=="cache_value":
                row=frame_ids[i]
                need(len(row)==8 and all(isinstance(k,str) and len(k)==64
                    and all(ch in "0123456789abcdef" for ch in k) for k in row),
                    "cache-value bounded frame IDs")
                cache.update(row[d-2:d])
                marginal=int(any(k not in cache for k in row[d:d+2])) if d<8 else None
            decision=(d==8 or kind=="fixed" and d==setting
                      or kind=="confidence" and max(p)>=setting
                      or kind=="value" and value_est(p,d,coef)<=setting
                      or kind=="cache_value" and
                         value_est(p,d,coef)<=STEP_PRICE+setting*marginal)
            if decision:
                out.append((d,argmax(p)));break
    return out


def work(ids,selected):
    known=set();calls=hits=0
    for row,(d,_) in zip(ids,selected):
        for j in range(0,d,2):
            pair=row[j:j+2]
            fresh=set(pair)-known
            hits+=sum(key in known for key in pair)
            if fresh:
                calls+=1;known.update(fresh)
    return {"unique_frames":len(known),"physical_video_calls":calls,
            "cache_hits":hits,"requested_frame_rows":sum(d for d,_ in selected)}


def quality(frameids,selected,labels):
    return {"correct":sum(pred==y for (_,pred),y in zip(selected,labels)),
            "cases":len(labels),"mean_depth":sum(d for d,_ in selected)/len(selected),
            **work(frameids,selected)}


def key(profile,i):
    return (profile["unique_frames"],profile["physical_video_calls"],
            profile["requested_frame_rows"],-profile["correct"],i)


def audit(root):
    root=Path(root); folder=root/"value"
    report=load(folder/"report.json"); manifest=load(root/"manifest.json")
    need(report["manifest_sha256"]==hashlib.sha256((root/"manifest.json").read_bytes()).hexdigest(),"manifest binding")
    selection=load(folder/"selection.json",report["selection_sha256"])
    saved=load(folder/"predictions.json",report["prediction_sha256"])
    dataset=manifest["dataset"]
    raw=(root/dataset["path"]).read_bytes()
    need(hashlib.sha256(raw).hexdigest()==dataset["sha256"],"dataset bytes")
    cases=[json.loads(row) for row in raw.splitlines()]
    cohort=manifest["cohort"]
    roster=load(root/cohort["path"],cohort["sha256"])
    need(len(cases)==len(roster) and [r["case_id"] for r in cases]==[r["case_id"] for r in roster],"cohort coverage")
    trainids=list(dict.fromkeys(r["source_id"] for r in roster if r["split"]=="train"))
    need(len(trainids)==6,"six train source groups")
    group={"reader":[],"critic":[],"calibration":[],"holdout":[]}
    for c,r in zip(cases,roster):
        name=("reader" if r["source_id"] in trainids[:4] else
              "critic" if r["source_id"] in trainids[4:] else c["split"])
        group[name].append(c)
    need([len(group[g]) for g in group]==[32,16,16,16],"split counts")
    for name in ("reader","critic","calibration"):
        need(selection[name+"_ids"]==[c["case_id"] for c in group[name]],"split identity drift "+name)
    need(selection["critic_labels"]==[c["label"] for c in group["critic"]],"critic label coverage")
    need(selection["calibration_labels"]==[c["label"] for c in group["calibration"]],"calibration label coverage")
    coef=verify_critic(selection)
    exits={int(k):v for k,v in selection["calibration_exits"].items()}
    labels=selection["calibration_labels"]
    ids=[[f["sha256"] for f in c["inputs"]["video"]] for c in group["calibration"]]
    need(ids==selection["calibration_frame_sha256s"],"calibration frame identity")
    need(set(exits)==set(DEPTHS) and all(len(exits[d])==len(labels) for d in DEPTHS),"calibration exits")
    fixed={d:quality(ids,picks(exits,"fixed",d,coef),labels) for d in DEPTHS}
    floor=max(v["correct"] for v in fixed.values())
    need(floor==selection["calibration_correct_floor"],"fixed accuracy floor")
    best=min(DEPTHS,key=lambda d:(-fixed[d]["correct"],fixed[d]["unique_frames"],fixed[d]["physical_video_calls"],d))
    need(best==selection["best_fixed_depth"],"best fixed choice")
    policies={f"fixed_{d}":{"kind":"fixed","depth":d} for d in DEPTHS}
    profiles={f"fixed_{d}":fixed[d] for d in DEPTHS}
    for family, settings in (("confidence",THRESHOLDS),("value",COSTS),
                             ("cache_value",COSTS)):
        cal=[{"setting":s,**quality(ids,picks(exits,family,s,coef,ids),labels)} for s in settings]
        need(selection["grids"][family]==cal,"calibration grid drift "+family)
        eligible=[i for i,p in enumerate(cal) if p["correct"]>=floor]
        if eligible:
            i=min(eligible,key=lambda j:key(cal[j],j))
            policies[family]={"kind":family,"threshold" if family=="confidence" else "price":settings[i]}
            profiles[family]=cal[i]
        else:
            policies[family]={"kind":"fixed","depth":best,
                "fallback_reason":"did_not_reach_best_fixed_calibration_correct_count"}
            profiles[family]=fixed[best]
    need(selection["policies"]==policies,"presealed policy drift")
    need(selection["calibration_profiles"]==profiles,"calibration profiles drift")
    winner=min(ARMS,key=lambda arm:(key(profiles[arm],0)[:-1],
                 0 if policies[arm]["kind"]=="fixed" else 1,ARMS.index(arm)))
    need(selection["best_calibration_arm"]==winner,"calibration selected arm changed")
    need(saved["selection_sha256"]==report["selection_sha256"],"prediction seal policy mismatch")
    need(set(saved["records"])==set(ARMS) and set(saved["physical_work"])==set(ARMS),"missing shadow arms")
    holdout=group["holdout"]
    need(saved["case_ids"]==[c["case_id"] for c in holdout],"heldout case ids")
    observed={}
    for arm in ARMS:
        rows=saved["records"][arm]; policy=policies[arm]
        need([r["case_id"] for r in rows]==saved["case_ids"],"row order")
        seen=[]; consumed=set()
        for r,case in zip(rows,holdout):
            visits=r["exits_seen"]
            need(r["depth"] in DEPTHS and len(visits)*2==r["depth"]
                and [v["depth"] for v in visits]==list(range(2,r["depth"]+1,2)),"invalid reader depth trace")
            for v in visits:
                argmax(v["probabilities"])
            need(r["probabilities"]==visits[-1]["probabilities"]
                 and r["prediction"]==argmax(r["probabilities"]),"invalid final reader prediction")
            row_ids=[f["sha256"] for f in case["inputs"]["video"]]
            def allowed_continue(v):
                d=v["depth"];p=v["probabilities"]
                if d==8: return False
                if policy["kind"]=="fixed": return d<policy["depth"]
                if policy["kind"]=="confidence": return max(p)<policy["threshold"]
                if policy["kind"]=="value": return value_est(p,d,coef)>policy["price"]
                if policy["kind"]=="cache_value":
                    fresh=int(any(k not in consumed for k in row_ids[d:d+2]))
                    return value_est(p,d,coef)>STEP_PRICE+policy["price"]*fresh
                need(False,"unknown policy family")
            for index,v in enumerate(visits):
                d=v["depth"]
                chunk=row_ids[d-2:d]
                additional=int(any(k not in consumed for k in chunk))
                need(v["physical_pair_call_delta"]==additional,"per-pair CLIP call delta drift")
                consumed.update(chunk)
                if policy["kind"]=="cache_value":
                    expected_calls=int(any(k not in consumed for k in row_ids[d:d+2])) if d<8 else None
                    expected_price=STEP_PRICE+policy["price"]*expected_calls if d<8 else None
                    need(v["next_pair_physical_calls_if_continued"]==expected_calls,
                         "cache marginal call drift")
                    need(v["next_pair_price_accuracy_units"]==expected_price,
                         "cache marginal price drift")
                else:
                    need(v.get("next_pair_physical_calls_if_continued") is None
                         and v.get("next_pair_price_accuracy_units") is None,
                         "unexpected cache-aware trace")
                if policy["kind"] in ("value","cache_value"):
                    expected=value_est(v["probabilities"],d,coef) if d<8 else None
                    saved_est=v["critic_value_estimate"]
                    need(expected is None and saved_est is None or
                         expected is not None and abs(expected-saved_est)<1e-6,
                         "critic estimate trace drift")
                else:
                    need(v["critic_value_estimate"] is None,"non-critic trace drift")
                if index<len(visits)-1:
                    need(allowed_continue(v),"stopped policy should have continued")
                else:
                    need(d==8 or not allowed_continue(v),"bad stop decision")
            seen.append((d,r["prediction"]))
        keys=[[f["sha256"] for f in c["inputs"]["video"]] for c in holdout]
        calc=work(keys,seen)
        need(all(saved["physical_work"][arm][k]==v for k,v in calc.items()),"physical frame cache cost drift")
        samples=sorted(r["wall"]["wall_ns"] for r in rows)
        latency={f"p{p}":samples[(len(samples)*p+99)//100-1] for p in (50,95,99)}
        need(report["scores"][arm]["latency_ns"]==latency,"per-row wall latency drift")
        by_source={}
        for r,case in zip(rows,holdout):
            source=next(s["source_id"] for s in roster if s["case_id"]==case["case_id"])
            entry=by_source.setdefault(source,{"attempted":0,"correct":0})
            entry["attempted"]+=1
            entry["correct"]+=int(r["prediction"]==case["label"])
        need(report["per_source_video_scores"][arm]==by_source,"per-source video score drift")
        correct=sum(pred==c["label"] for (_d,pred),c in zip(seen,holdout))
        need(report["scores"][arm]["cases"]==len(holdout)
             and report["scores"][arm]["correct"]==correct
             and report["physical_work"][arm]==saved["physical_work"][arm],"holdout scoring/cost drift")
        observed[arm]={"correct":correct,"cases":len(holdout),**calc}
    return {"status":"audited_archived_consistency_only","holdout":observed,
            "trained_critic_on_heldout":False,"physical_tower_execution_attested":False,
            "new_independent_semantic_video_tasks":False}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(audit(args.root),sort_keys=True))
