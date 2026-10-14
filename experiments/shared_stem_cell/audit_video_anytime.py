"""Standalone, standard-library audit of sealed video frame budgeting.

Does not import repository runner, classifier, scorer or Torch. Checks archive
consistency and decision arithmetic, NOT hardware execution attestation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

DEPTHS=(2,4,6,8)
THRESHOLDS=(0.0,0.55,0.65,0.75,0.85,0.95,1.01)
ARMS=("adaptive","fixed_2","fixed_4","fixed_6","fixed_8")


def need(cond, why):
    if not cond: raise ValueError(why)


def raw_obj(path, digest=None):
    raw=path.read_bytes()
    if digest is not None: need(hashlib.sha256(raw).hexdigest()==digest, "file SHA drift:"+str(path))
    return json.loads(raw)


def good(p):
    need(isinstance(p,list) and len(p)==2 and all(type(v) in (int,float)
        and math.isfinite(v) and 0 <=v <=1 for v in p)
        and abs(sum(p)-1)<1e-5, "invalid two-class probability")
    return 0 if p[0]>=p[1] else 1


def score(rows, labels):
    need(len(rows)==len(labels) and len(rows)>0,"missing scores")
    return sum(good(p)==y for p,y in zip(rows,labels))


def physical_cost(keys,picks):
    seen=set(); calls=hits=0
    for frames,(depth,_prediction) in zip(keys,picks):
        need(len(frames)==8,"missing eight-frame fingerprint")
        for i in range(0,depth,2):
            segment=frames[i:i+2]
            fresh=set(segment)-seen
            hits+=sum(s in seen for s in segment)
            if fresh: calls+=1;seen.update(fresh)
    return {"unique_frames":len(seen),"physical_video_calls":calls,
            "cache_hits":hits,"requested_frame_rows":sum(d for d,_ in picks)}


def route(exits, threshold):
    n=len(exits[2]); result=[]
    for i in range(n):
        for depth in DEPTHS:
            p=exits[depth][i]
            good(p)
            if depth==8 or max(p)>=threshold:
                result.append((depth,good(p))); break
    return result


def audit(root):
    root=Path(root)
    manifest=raw_obj(root/"manifest.json")
    output=root/"anytime"
    report=raw_obj(output/"report.json")
    selection=raw_obj(output/"selection.json",report["selection_sha256"])
    payload=raw_obj(output/"predictions.json",report["prediction_sha256"])
    need(report["manifest_sha256"]==hashlib.sha256((root/"manifest.json").read_bytes()).hexdigest(),"manifest binding")
    descriptor=manifest["dataset"]
    raw=(root/descriptor["path"]).read_bytes()
    need(hashlib.sha256(raw).hexdigest()==descriptor["sha256"],"dataset hash drift")
    source=[json.loads(line) for line in raw.splitlines()]
    holdout=[r for r in source if r["split"]=="holdout"]
    calibration=[r for r in source if r["split"]=="calibration"]
    need(len(holdout)==len(payload["case_ids"]) and
        payload["case_ids"]==[r["case_id"] for r in holdout],"holdout identities")
    need(selection["calibration_ids"]==[r["case_id"] for r in calibration]
         and selection["calibration_labels"]==[r["label"] for r in calibration],"calibration cohort")
    gold=[r["label"] for r in holdout]
    cal_y=selection["calibration_labels"]
    exits={int(k):v for k,v in selection["calibration_probabilities"].items()}
    need(set(exits)==set(DEPTHS) and all(len(v)==len(cal_y) for v in exits.values()),"calibration exits")
    cal_keys=[[f["sha256"] for f in c["inputs"]["video"]] for c in calibration]
    need(selection["calibration_frame_sha256s"]==cal_keys,"calibration source frames")
    floor=max(score(exits[d],cal_y) for d in DEPTHS)
    need(floor==selection["calibration_correct_floor"],"fixed-depth calibration floor")
    for d in DEPTHS:
        expected=physical_cost(cal_keys,[(d,0)]*len(cal_y))
        need(selection["fixed_depth_controls"][str(d)]["correct"]==score(exits[d],cal_y)
             and all(selection["fixed_depth_controls"][str(d)][k]==v for k,v in expected.items()),"fixed score/cost")
    need(len(selection["grid"])==len(THRESHOLDS),"threshold grid")
    eligible=[]
    for i,(t,row) in enumerate(zip(THRESHOLDS,selection["grid"])):
        picks=route(exits,t)
        correct=sum(pred==gold for (_d,pred),gold in zip(picks,cal_y))
        expected=physical_cost(cal_keys,picks)
        need(row["threshold"]==t and row["correct"]==correct
             and row["cases"]==len(cal_y) and all(row[k]==v for k,v in expected.items()),
             "threshold evidence drift")
        if correct>=floor: eligible.append(i)
    chosen=selection["policy"]
    if eligible:
        best=min(eligible,key=lambda i:(selection["grid"][i]["unique_frames"],
                          selection["grid"][i]["physical_video_calls"],
                          selection["grid"][i]["requested_frame_rows"],
                          -selection["grid"][i]["correct"],i))
        need(chosen["arm"]=="adaptive" and chosen["selected_index"]==best
             and chosen["threshold"]==THRESHOLDS[best],"postcalibration threshold changed")
    else:
        best=min(DEPTHS,key=lambda d:(-score(exits[d],cal_y),
            selection["fixed_depth_controls"][str(d)]["unique_frames"],
            selection["fixed_depth_controls"][str(d)]["physical_video_calls"],d))
        need(chosen["arm"]==f"fixed_{best}" and chosen["depth"]==best,"fallback depth changed")
    need(payload["selection_sha256"]==report["selection_sha256"],"prediction policy mismatch")
    need(set(payload["records"])==set(ARMS) and set(payload["physical_work"])==set(ARMS),"missing arms")
    validated={}
    for arm,rows in payload["records"].items():
        need([r["case_id"] for r in rows]==payload["case_ids"],"missing/reordered row")
        for row in rows:
            profile=(chosen["arm"] if arm=="adaptive" else arm)
            limit=8 if profile=="adaptive" else int(profile.split("_")[1])
            exits_seen=row["exits_seen"]
            need(row["depth"] in DEPTHS and row["depth"]<=limit
                 and [r["depth"] for r in exits_seen]==list(range(2,row["depth"]+1,2)),"invalid physical exit trace")
            need(row["depth"]==len(exits_seen)*2,"frames/transition count")
            for visit in exits_seen: good(visit["probabilities"])
            need(row["probabilities"]==exits_seen[-1]["probabilities"]
                 and row["prediction"]==good(row["probabilities"]),"wrong final inference")
            if profile=="adaptive":
                t=chosen["threshold"]
                need(row["depth"]==8 or max(row["probabilities"])>=t,"missed stop")
                need(all(max(x["probabilities"])<t for x in exits_seen[:-1]),"premature continuation")
            else: need(row["depth"]==limit,"fixed depth violated")
            need(row["model_sha256"]==selection["model_sha256"],"model changed")
        work=payload["physical_work"][arm]
        observed=sum(r["depth"] for r in rows)
        need(work["requested_frame_rows"]==observed and 0<=work["unique_frames"]<=observed
             and 0<=work["cache_hits"]<=observed
             and 0<=work["physical_video_calls"]<=len(rows)*4,"frame work misreported")
        correct=sum(r["prediction"]==y for r,y in zip(rows,gold))
        need(correct==report["scores"][arm]["correct"] and
             report["scores"][arm]["cases"]==len(gold),"holdout score changed")
        validated[arm]={"correct":correct,"rows":len(rows),"frame_rows":observed,
                        "unique_frames":work["unique_frames"],"physical_calls":work["physical_video_calls"]}
    expected_calls=selection["training_calibration_encoding"]["physical_video_calls"]+sum(
        x["physical_video_calls"] for x in payload["physical_work"].values())
    need(report["actual_tower_calls_entire_experiment"]["clip"]==expected_calls,
         "hidden physical CLIP calls")
    need(report["control_work_is_not_foreground_saving"] is True
         and report["production_accepted"] is False,"incorrect resource/product claim")
    return {"selection":chosen,"fixed_accuracy_floor":floor,
            "arms":validated,"total_physical_clip_calls":expected_calls,
            "archive_consistency_only":True,"independent_future_evidence":False}


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    args=p.parse_args()
    print(json.dumps(audit(args.root),sort_keys=True,indent=2))
