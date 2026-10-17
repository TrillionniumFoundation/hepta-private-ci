"""Independent NumPy V17 forward/route/source audit; no Torch or producer import.

Never reads original held labels. Verifies physical archived features, saved
V15/V16/V17 model inventories, fold-specific reference permutation, 13 route
profiles, calibration Brier, and a post-label oracle bound on calibration only.
No gradient reexecution or owner/host signature is implied.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from safetensors.numpy import load

SCHEMA="hepta.stem.identity-alignment.v17.research"
ARCHIVE="0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7"
FEATURE="e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490"
INPUT="d029f906565946216126db39e4ca3f4f14d7ab5a3c297ec2a62639ccdfbf604a"
V14_SOURCE="7e325bf6a08216b1bb497ee3910682b4155705b56fd77534251a42f590112e86"
V15_SOURCE="7a998eebeab237b20c004f4cb4ef19adc48ad3e03ddb778658373049745decdd"
V16_SOURCE="cb42cc34fe6f8c17d8dc5887964ff3f9c7eb10be09ca604677ab498a24c4db20"
ARMS=("extra_continued", "continued", "centroid", "constant0", "constant1", "v15_oof_gate",
      "v16_final_loss_gate", "unaligned_oof", "geo_aligned_oof", "geo_aligned_swapped",
      "geo_aligned_shuffled", "logit_aligned_oof", "logit_aligned_swapped")
ROUTES=("v15_oof_gate","v16_final_loss_gate","unaligned_oof","geo_aligned_oof",
        "geo_aligned_swapped","geo_aligned_shuffled","logit_aligned_oof","logit_aligned_swapped","centroid")
PROTOCOL={"schema":SCHEMA,"seeds":[41,47,53],"router_steps":80,"batch":16,"learning_rate":0.1,
          "fold_count":4,"alignment_anchor":"other 48 original TRAIN rows; no CAL or blind labels",
          "geometry_reference":"frozen V15 full-TRAIN centroids and label-free assignments",
          "logit_reference":"V15 final experts trained with all TRAIN labels; diagnostic only, not unbiased OOF",
          "tie_rule":"do not swap on equal anchor count / equal logit error",
          "training":"identical sigmoid logistic objective, zero initialization, seed xor 0x1717 minibatches",
          "confidence":"calibration-only; 32 previously exposed rows; no significance claim",
          "baseline":"frozen V16 extra_continued; its whole training lifecycle not FLOP-matched",
          "blind_label_access":False,"new_encoder_forwards":0,"production_authorized":False}


def demand(condition,why):
    if not condition:raise ValueError(why)


def digest(data):return hashlib.sha256(data).hexdigest()

def canonical(obj):return json.dumps(obj,sort_keys=True,separators=(",", ":"),allow_nan=False).encode()

def no_duplicates(items):
    result={}
    for name,item in items:
        demand(name not in result,"duplicate JSON property")
        result[name]=item
    return result


def checked(path,expected=None,max_bytes=3_000_000):
    path=Path(path)
    demand(path.is_file() and not path.is_symlink() and 0<path.stat().st_size<=max_bytes,"missing/symlink/oversized proof")
    b=path.read_bytes()
    if expected is not None:demand(digest(b)==expected,"source/blob identity changed")
    return b


def jread(path):
    result=json.loads(checked(path),object_pairs_hook=no_duplicates)
    canonical(result)
    return result


def state(folder,name,roster,kind):
    meta=roster[name]
    expect={"sha256","scalars"} if kind=="v15" else ({"sha256","state_scalars"})
    demand(set(meta)==expect,"tensor manifest malformed")
    tensors=load(checked(Path(folder)/(name+".safetensors"),meta["sha256"]))
    field="scalars" if kind=="v15" else "state_scalars"
    demand(sum(v.size for v in tensors.values())==meta[field] and all(v.dtype==np.float32
           and np.isfinite(v).all() for v in tensors.values()),"tensor geometry/values changed")
    return tensors


def normalize(x,m):
    z=x-m
    return z/np.maximum(np.linalg.norm(z,axis=1,keepdims=True),1e-12)


def assign(x,c):
    distances=(x*x).sum(1,keepdims=True)-2*x@c.T+(c*c).sum(1)
    return np.argmin(distances,axis=1)


def linear(x,m,prefix=""):
    return x@m[prefix+"weight"].T+m[prefix+"bias"]


def twohead(x,m,chosen):
    demand(tuple(chosen.shape)==(len(x),) and np.all((chosen==0)|(chosen==1)),"invalid selected expert")
    output=np.empty((len(x),4),dtype=np.float32)
    for cell in (0,1):
        indices=np.flatnonzero(chosen==cell)
        output[indices]=linear(x[indices],m,f"heads.{cell}.")
    return output


def softmax(z):
    z=z.astype(np.float64)
    e=np.exp(z-z.max(1,keepdims=True))
    return e/e.sum(1,keepdims=True)


def brier(p,y):return float(((p-np.eye(4)[y])**2).sum(1).mean())


def decide(cal,old):
    demand(set(cal)==set(old)==set(ARMS),"incomplete results")
    eligible=[x for x in ("unaligned_oof","geo_aligned_oof","logit_aligned_oof")
              if cal["extra_continued"]-cal[x]>.01 and old[x]-old["extra_continued"]<=.01]
    return min(eligible,key=lambda x:(cal[x],("unaligned_oof","geo_aligned_oof","logit_aligned_oof").index(x))) if eligible else "extra_continued"


def validate_fold(x,z,folds,ref,v15folder,roster,seed,record):
    original=np.array(record["oof_targets"],dtype=np.int64)
    demand(original.shape==(64,) and np.all((original==0)|(original==1)),"invalid V15 OOF target")
    geo=original.copy();logit=original.copy();details=[]
    for k,held in enumerate(folds):
        name=f"{seed}-fold{k}"
        other=[i for i in range(64) if i not in held]
        fold_mean=state(v15folder,name+"-normalizer",roster,"v15")["mean"]
        folded=state(v15folder,name+"-split",roster,"v15")
        folded_x=normalize(x[other],fold_mean)
        routes_fold=assign(folded_x,folded["centers"])
        routes_ref=assign(z[other],ref["centers"])
        keep=int((routes_fold==routes_ref).sum());rev=len(other)-keep
        flip=int(rev>keep)
        f0=np.stack([linear(folded_x,folded,f"heads.{i}.") for i in (0,1)],axis=1)
        f1=np.stack([linear(z[other],ref,f"heads.{i}.") for i in (0,1)],axis=1)
        costkeep=float(((f0-f1)**2).sum());costflip=float(((f0-f1[:,[1,0]])**2).sum())
        flip2=int(costflip<costkeep)
        if flip:geo[held]=1-geo[held]
        if flip2:logit[held]=1-logit[held]
        details.append({"fold":k,"held_rows":held,"anchor_rows":48,"geo_keep":keep,
                        "geo_reverse":rev,"geo_flip":flip,"logit_keep_error":costkeep,
                        "logit_reverse_error":costflip,"logit_flip":flip2,
                        "labels_used_by_alignment":False,
                        "reference_trained_on_excluded_labels_for_logit_arm":True})
    return details,{"unaligned_oof":original,"geo_aligned_oof":geo,"logit_aligned_oof":logit}


def profiles(x,seed,ref,continued,extra,v15gate,v16gate,newgates):
    routes={"centroid":assign(x,ref["centers"]),
            "v15_oof_gate":(linear(x,v15gate)[:,0]>0).astype(np.int64),
            "v16_final_loss_gate":(linear(x,v16gate)[:,0]>0).astype(np.int64),
            **{k:(linear(x,v)[:,0]>0).astype(np.int64) for k,v in newgates.items()}}
    perm=np.random.default_rng(seed^0x1717).permutation(len(x))
    routes["geo_aligned_swapped"]=1-routes["geo_aligned_oof"]
    routes["geo_aligned_shuffled"]=routes["geo_aligned_oof"][perm]
    routes["logit_aligned_swapped"]=1-routes["logit_aligned_oof"]
    result={"extra_continued":softmax(linear(x,extra)),"continued":softmax(linear(x,continued))}
    result["constant0"]=softmax(linear(x,ref,"heads.0."))
    result["constant1"]=softmax(linear(x,ref,"heads.1."))
    for key,r in routes.items():result[key]=softmax(twohead(x,ref,r))
    demand(set(result)==set(ARMS) and set(routes)==set(ROUTES),"missing route candidate")
    return result,{k:v.tolist() for k,v in routes.items()}


def compare(reference,candidate,tolerance=5e-5):
    actual=np.asarray(reference,dtype=np.float64)
    expected=np.asarray(candidate,dtype=np.float64)
    demand(actual.shape==expected.shape and np.isfinite(actual).all() and np.isfinite(expected).all(),"prediction invalid")
    discrepancy=float(np.abs(actual-expected).max())
    demand(discrepancy<tolerance and np.array_equal(actual.argmax(1),expected.argmax(1)),"independent forward/choice mismatch")
    return discrepancy


def review(inputs,v15folder,v16folder,v17folder):
    inputs,v15folder,v16folder,v17folder=map(Path,(inputs,v15folder,v16folder,v17folder))
    meta=jread(inputs/"input.json")
    demand(digest(checked(inputs/"input.json"))==INPUT,"not exact original input")
    data=load(checked(inputs/"features.safetensors",FEATURE))["features"]
    demand(data.shape==(128,384) and data.dtype==np.float32 and np.isfinite(data).all(),"original real feature bytes invalid")
    for name,sha in (("stem_counterfactual_split_v14.py",V14_SOURCE),
                     ("stem_stable_router_v15.py",V15_SOURCE),
                     ("stem_specialization_v16.py",V16_SOURCE)):
        demand(digest(checked(Path(__file__).with_name(name)))==sha,"inherited source changed")
    p=meta["partitions"]
    demand({k:len(p[k]) for k in ("train","calibration","holdout")}=={"train":64,"calibration":32,"holdout":32}
           and set(meta["labels"])=={str(i) for k in ("train","calibration") for i in p[k]},"held labels accessed")
    train,cal,blind=(data[p[k]] for k in ("train","calibration","holdout"))
    y=np.asarray([meta["labels"][str(i)] for i in p["train"]],dtype=np.int64)
    cy=np.asarray([meta["labels"][str(i)] for i in p["calibration"]],dtype=np.int64)
    v15=jread(v15folder/"sealed.json");v16=jread(v16folder/"sealed.json");rec=jread(v17folder/"sealed.json")
    demand(len(v15["models"])==58 and v15["producer_sha256"]==V15_SOURCE
           and len(v16["model_files"])==15 and v16["source_sha256"]==V16_SOURCE,
           "incomplete frozen predecessor source")
    demand(rec["schema"]==SCHEMA and rec["protocol"]==PROTOCOL
           and rec["protocol_sha256"]==digest(canonical(PROTOCOL))
           and rec["source_sha256"]==digest(checked(Path(__file__).with_name("stem_identity_alignment_v17.py")))
           and rec["archive_sha256"]==ARCHIVE and rec["input_sha256"]==INPUT
           and rec["feature_sha256"]==FEATURE and rec["v16_source_sha256"]==V16_SOURCE
           and rec["v15_seal_sha256"]==digest(checked(v15folder/"sealed.json"))
           and rec["v16_seal_sha256"]==digest(checked(v16folder/"sealed.json")),
           "source/identity/ABI changed")
    demand(rec["new_encoder_forwards"]==0 and rec["held_labels_read"] is False
           and rec["held_scores"] is None and rec["production_authorized"] is False
           and rec["prospective_efficacy_verified"] is False and rec["future_utility"] is None
           and rec["independent_retention"] is None and rec["target_host_4096_qualified"] is False,
           "false production/future/host claim")
    expected={f"{seed}-{name}" for seed in (41,47,53) for name in ("unaligned_oof","geo_aligned_oof","logit_aligned_oof")}
    demand(set(rec["models"])==expected and
           {p.name for p in v17folder.iterdir()}=={n+".safetensors" for n in expected}|{"sealed.json"}
           and set(rec["seeds"])=={"41","47","53"},"missing/extra candidate state")
    # Physical SHA and tensor census for ALL 73 predecessor files, not only used ones.
    prev15={name:state(v15folder,name,v15["models"],"v15") for name in v15["models"]}
    prev16={name:state(v16folder,name,v16["model_files"],"v16") for name in v16["model_files"]}
    new={name:state(v17folder,name,rec["models"],"v16") for name in rec["models"]}
    demand(all(set(s)=={"weight","bias"} and s["weight"].shape==(1,384)
           and s["bias"].shape==(1,) for s in new.values()),"invalid new gate geometry")
    mean=prev15["normalizer"]["mean"]
    z,cz,hz=(normalize(x,mean) for x in (train,cal,blind))
    folds=v15["folds"]
    demand(len(folds)==4 and all(len(a)==16 for a in folds) and sorted(sum(folds,[]))==list(range(64)),"folds changed")
    deviations=[];summary={}
    for seed in (41,47,53):
        row=rec["seeds"][str(seed)]
        final=prev15[f"{seed}-centroid"]
        d,target=validate_fold(train,z,folds,final,v15folder,v15["models"],seed,v15["seeds"][str(seed)])
        demand(len(row["alignment"])==4 and all(rec_item["fold"]==d_item["fold"]
               and rec_item["held_rows"]==d_item["held_rows"] and rec_item["anchor_rows"]==48
               and all(rec_item[k]==d_item[k] for k in ("geo_keep","geo_reverse","geo_flip","logit_flip","labels_used_by_alignment","reference_trained_on_excluded_labels_for_logit_arm"))
               and abs(rec_item["logit_keep_error"]-d_item["logit_keep_error"])<5e-4
               and abs(rec_item["logit_reverse_error"]-d_item["logit_reverse_error"])<5e-4
               for rec_item,d_item in zip(row["alignment"],d)),"fold alignment drift")
        for name,desired in target.items():
            demand(row["targets_sha256"][name]==digest(desired.astype("<i8").tobytes())
                   and row["target_counts"][name]==np.bincount(desired,minlength=2).tolist(),"training targets changed")
        work=row["work"]
        demand(set(work)==set(target),"incomplete trained gate census")
        schedule=np.random.default_rng(seed^0x1717).integers(0,64,(80,16))
        sch_sha=digest(schedule.astype("<i8").tobytes())
        for name,info in work.items():
            demand(info["steps"]==80 and info["examples"]==1280
                   and info["label_counts"]==np.bincount(target[name],minlength=2).tolist()
                   and info["schedule_sha256"]==sch_sha
                   and type(info["cpu_ns"]) is int and info["cpu_ns"]>=0,"training receipt changed")
        models={name:new[f"{seed}-{name}"] for name in target}
        continued=prev15[f"{seed}-continued"]
        extra=prev16[f"{seed}-extra_continued"]
        gate15=prev15[f"{seed}-gate"]
        gate16=prev16[f"{seed}-loss_gate"]
        cal_pred,cal_route=profiles(cz,seed,final,continued,extra,gate15,gate16,models)
        old_pred,_=profiles(z[:32],seed,final,continued,extra,gate15,gate16,models)
        blind_pred,blind_route=profiles(hz,seed,final,continued,extra,gate15,gate16,models)
        demand(cal_route==row["calibration_routes"] and blind_route==row["blind_routes"],"prediction routes changed")
        demand(set(row["calibration_probabilities"])==set(ARMS) and set(row["blind_probabilities"])==set(ARMS),"prediction arms changed")
        for name in ARMS:
            deviations.append(compare(cal_pred[name],row["calibration_probabilities"][name]))
            deviations.append(compare(blind_pred[name],row["blind_probabilities"][name]))
        cal_score={name:brier(value,cy) for name,value in cal_pred.items()}
        old_score={name:brier(value,y[:32]) for name,value in old_pred.items()}
        demand(set(row["calibration"])==set(ARMS) and set(row["old_train_brier"])==set(ARMS),"incomplete metrics")
        for name in ARMS:
            demand(row["calibration"][name]["correct"]==int((cal_pred[name].argmax(1)==cy).sum())
                   and abs(row["calibration"][name]["brier"]-cal_score[name])<5e-5
                   and abs(row["old_train_brier"][name]-old_score[name])<5e-5,"false observed score")
        demand(row["selected_research_candidate"]==decide(cal_score,old_score),"selection overwritten")
        oracle=np.minimum(((cal_pred["constant0"]-np.eye(4)[cy])**2).sum(1),
                          ((cal_pred["constant1"]-np.eye(4)[cy])**2).sum(1)).mean()
        disagree=int((cal_pred["constant0"].argmax(1)!=cal_pred["constant1"].argmax(1)).sum())
        demand(abs(oracle-row["post_label_calibration_oracle_brier"])<5e-5
               and disagree==row["calibration_expert_class_disagreement"],"oracle/expert disagreement changed")
        demand(row["frozen_v15_v16_lineages_unchanged"] is True,"false frozen lineage claim")
        summary[str(seed)]={"calibration_brier":cal_score,"calibration_correct":{k:int((v.argmax(1)==cy).sum()) for k,v in cal_pred.items()},
            "selected_research_candidate":row["selected_research_candidate"],
            "fold_geometry_flips":[a["geo_flip"] for a in d],
            "fold_logit_flips":[a["logit_flip"] for a in d],
            "oracle_postlabel_calibration_brier":float(oracle),
            "expert_class_disagreement_32":disagree,
            "new_gate_train_cpu_ns_reported":sum(x["cpu_ns"] for x in work.values())}
    return {"schema":SCHEMA+".numpy-audit","status":"RETROSPECTIVE_CALIBRATION_NO_FUTURE_CLAIM",
            "source_sha256":rec["source_sha256"],"sealed_sha256":digest(checked(v17folder/"sealed.json")),
            "archive_sha256":ARCHIVE,"v15_model_files_verified":len(prev15),
            "v16_model_files_verified":len(prev16),"v17_gate_files_verified":len(new),
            "model_files_total_verified":len(prev15)+len(prev16)+len(new),
            "real_calibration_cases":32,"independent_future_cases":0,
            "max_probability_deviation":max(deviations),"independent_gradient_reexecution":False,
            "held_labels_read":False,"held_scores":None,"selected_production_model":None,
            "new_encoder_forwards":0,"prospective_efficacy_verified":False,
            "production_authorized":False,"seeds":summary}


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for k in ("inputs","v15","v16","v17","out"):
        p.add_argument("--"+k,required=True)
    a=p.parse_args();report=review(a.inputs,a.v15,a.v16,a.v17)
    with Path(a.out).open("xb") as f:f.write(canonical(report)+b"\n")
