"""P0.6 matched same-model Head intervention on pinned historical AG News features.

UNCONDITIONALLY RESEARCH_ONLY / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL.
Original AG News source includes labels for held/calibration (historically exposed).
The producer sees a source-filtered bundle with *only training labels*; the
independent scoring process opens the original archive only AFTER a sealed,
create-only prelabel prediction exists. This is a stronger producer-isolation
experiment, not future-window, independently custodied or truly unseen gold.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import io
import json
import math
import os
from pathlib import Path
import random
import stat
import struct
from typing import Any

import numpy as np
from safetensors.numpy import load as load_safetensors

from agnews_crossfamily import ARCHIVE_SHA256, MEMBERS, read_original
from fabric import Denied
from science_gate import exact_mcnemar

SCHEMA="hepta.cell-fabric.p06.agnews-equalbudget.v1"
SOURCE_DOMAIN=b"hepta.cell-fabric.p06.source.v1\x00"
SEAL_DOMAIN=b"hepta.cell-fabric.p06.prelabel.v1\x00"
SEEDS=(101,211,307)
SGD_STEPS=512
LEARNING_RATE=0.05
TRAIN_SCALE=4.0
WEIGHT_DECAY=0.0001
DIM=384
CLASSES=4
PARAMS_PER_HEAD=(DIM+1)*CLASSES
TRAINED=("split","random_route","shared_twin","shared_one")
ALL_ARMS=("split","random_route","shared_twin","shared_one","split_zero","split_swap","frozen","type_prior","global_prior","centroid","centroid_train_loo")


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise Denied(reason)


def _reject_constant(value):
    raise Denied(f"nonfinite constant: {value}")


def _strict_pairs(items):
    out={}
    for k,v in items:
        if k in out:
            raise Denied("duplicate json key")
        out[k]=v
    return out


def canonical(obj: Any) -> bytes:
    return json.dumps(obj,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode("utf-8")


def digest(raw: bytes, domain: bytes=SOURCE_DOMAIN) -> str:
    return hashlib.sha256(domain+raw).hexdigest()


def json_read(path: Path, max_bytes: int=1_500_000) -> dict:
    fd=os.open(path,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0))
    with os.fdopen(fd,"rb") as f:
        require(stat.S_ISREG(os.fstat(f.fileno()).st_mode),"not a regular file")
        b=f.read(max_bytes+1)
    require(len(b)<=max_bytes,"oversized input")
    obj=json.loads(b,object_pairs_hook=_strict_pairs,parse_constant=_reject_constant)
    require(type(obj) is dict,"expected object")
    return obj


def write_private(path: Path, payload: Any) -> str:
    """Create-only, no-symlink final name and journal data before use."""
    data=canonical(payload)+b"\n"
    require(len(data)<=1_500_000,"oversized outgoing evidence")
    require(not path.is_symlink() and not path.parent.is_symlink(),"refuse symlink")
    parent_fd=os.open(path.parent,os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0))
    try:
        mode=os.fstat(parent_fd).st_mode
        require(stat.S_ISDIR(mode) and mode & 0o077 == 0,"output directory must be private")
    finally:
        os.close(parent_fd)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),0o600)
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        d=os.open(path.parent,os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0))
        try:os.fsync(d)
        finally:os.close(d)
    except Exception:
        try:path.unlink()
        except OSError:pass
        raise
    return hashlib.sha256(data).hexdigest()


def _normalize(row: np.ndarray) -> np.ndarray:
    require(row.shape==(DIM,) and np.isfinite(row).all(),"invalid physical feature row")
    norm=float(np.linalg.norm(row.astype(np.float64)))
    require(1e-6<norm<1e6,"unusable model feature magnitude")
    return (row.astype(np.float64)*(TRAIN_SCALE/norm))


def staged_bundle(archive_path: Path) -> dict:
    """Source-custody stage MAY see labels; producer gets this redacted view."""
    packet=read_original(archive_path)   # exact 1.4MB pinned archive + SHA members
    rows=[json.loads(s,object_pairs_hook=_strict_pairs,parse_constant=_reject_constant)
          for s in packet["dataset.jsonl"].splitlines()]
    meta=json.loads(packet["execution/frozen-features/manifest.json"],object_pairs_hook=_strict_pairs)
    tensors=load_safetensors(packet["execution/frozen-features/features.safetensors"])
    require(set(tensors)=={"features"},"unknown feature tensor")
    mat=tensors["features"]
    require(mat.shape==(128,DIM) and mat.dtype==np.float32,"wrong actual pretrained feature layout")
    require(meta["simulated_encoder"] is False and meta["file_sha256"]==MEMBERS["hepta-public-study/execution/frozen-features/features.safetensors"],"not original pretrained feature material")
    require(len(rows)==len(meta["rows"])==128,"incomplete original archive population")
    producer={"schema":SCHEMA,"archive_sha256":ARCHIVE_SHA256,
              "feature_sha256":MEMBERS["hepta-public-study/execution/frozen-features/features.safetensors"],
              "scale_norm":TRAIN_SCALE,"dimension":DIM,"classes":CLASSES,
              "train":[],"calibration":[],"holdout":[],"claims":{"historical_gold_co_resident":True,"future_source":False,"real_original_pretrained_features":True,"new_pretrained_forwards":0,"authority":"DENY_ALL"}}
    used=set()
    for src,bind,v in zip(rows,meta["rows"],mat,strict=True):
        case_id=src.get("case_id");split=src.get("split");cell=src.get("cell")
        require(type(case_id) is str and case_id not in used and
                src.get("group")==case_id and bind.get("case_id")==case_id and
                bind.get("split")==split and bind.get("cell")==cell and
                type(cell) is int and cell in (0,1) and split in ("train","calibration","holdout") and
                type(src.get("label")) is int and 0<=src["label"]<CLASSES,
                "original source/feature/route population drift")
        used.add(case_id)
        item={"id":case_id,"cell":cell,"features":_normalize(v).tolist()}
        if split=="train":item["target"]=src["label"]
        producer[split].append(item)
    require(tuple(len(producer[k]) for k in ("train","calibration","holdout"))==(64,32,32),"wrong train/cal/held census")
    for k in ("calibration","holdout"):
        require(all("target" not in item and "label" not in item for item in producer[k]),"held gold exposed")
    return producer


def verify_bundle(bundle: dict) -> None:
    require(type(bundle) is dict and set(bundle)=={"schema","archive_sha256","feature_sha256","scale_norm","dimension","classes","train","calibration","holdout","claims"},"unknown bundle fields")
    require(bundle["schema"]==SCHEMA and bundle["archive_sha256"]==ARCHIVE_SHA256 and
            bundle["feature_sha256"]==MEMBERS["hepta-public-study/execution/frozen-features/features.safetensors"] and
            type(bundle["scale_norm"]) in (float,int) and bundle["scale_norm"]==TRAIN_SCALE and
            type(bundle["dimension"]) is int and bundle["dimension"]==DIM and
            type(bundle["classes"]) is int and bundle["classes"]==CLASSES and
            bundle["claims"]=={"historical_gold_co_resident":True,"future_source":False,"real_original_pretrained_features":True,"new_pretrained_forwards":0,"authority":"DENY_ALL"},"unqualified source, model or scope")
    observed=set()
    for split,size in (("train",64),("calibration",32),("holdout",32)):
        seq=bundle[split];require(type(seq) is list and len(seq)==size,"missing cases")
        for row in seq:
            fields={"id","cell","features","target"} if split=="train" else {"id","cell","features"}
            require(type(row) is dict and set(row)==fields,"held label leak or wrong fields")
            key=row["id"]
            require(type(key) is str and 0<len(key)<=128 and key not in observed and type(row["cell"]) is int and row["cell"] in (0,1),"case identity or Cell route")
            observed.add(key)
            a=row["features"]
            require(type(a) is list and len(a)==DIM and all(type(x) in (int,float) and math.isfinite(x) for x in a),"invalid normalized features")
            norm=math.sqrt(math.fsum(float(x)**2 for x in a))
            require(3.999999<=norm<=4.000001,"feature normalization mismatch")
            if split=="train":require(type(row["target"]) is int and 0<=row["target"]<CLASSES,"invalid training target")


def _softmax(logits: np.ndarray) -> np.ndarray:
    l=logits-np.max(logits)
    p=np.exp(l);p/=p.sum()
    return p


def _extra_route(id_: str) -> int:
    return hashlib.sha256(b"hepta.p06.independent-fixed-route.v1\x00"+id_.encode("utf-8")).digest()[0]&1


def _features(row: dict) -> np.ndarray:
    return np.array([*row["features"],1.0],dtype=np.float64)


def _prob(model: np.ndarray, x: np.ndarray, cell: int, arm: str, ident: str) -> np.ndarray:
    if arm=="shared_one":z=model[0]@x
    elif arm=="shared_twin":z=(model[0]@x+model[1]@x)*.5
    elif arm=="random_route":z=model[_extra_route(ident)]@x
    elif arm=="split_swap":z=model[1-cell]@x
    elif arm=="split_zero":
        temp=x.copy();temp[:-1]=0;z=model[cell]@temp
    else:z=model[cell]@x
    return _softmax(z)


def train_only_centroid_temperature(xtrain: np.ndarray, ytrain: np.ndarray) -> dict:
    """Class-centroid LOO calibration; never reads CAL/HELD features or gold.

    Paid search is 64 leave-one-out centroid predictions per candidate scale;
    this is NO SGD, not zero mathematical training work.
    """
    candidates=(0.125,0.25,0.5,1.,2.,4.,8.,16.)
    values=[]
    for temperature in candidates:
        loss=0.
        for i in range(len(ytrain)):
            means=[]
            for label in range(CLASSES):
                inds=np.flatnonzero(ytrain==label)
                inds=inds[inds!=i]
                require(len(inds)>0,"class support insufficient for train-only LOO")
                means.append(xtrain[inds,:-1].mean(axis=0))
            p=_softmax(np.stack(means) @ xtrain[i,:-1] * temperature)
            loss-=math.log(max(1e-300,float(p[ytrain[i]])))
        values.append(loss/len(ytrain))
    selected=min(range(len(values)),key=lambda i:(values[i],candidates[i]))
    return {"candidate_temperatures":list(candidates),
            "train_loo_nll":values,"selected_temperature":candidates[selected],
            "training_only_calibration_predictions":len(candidates)*len(ytrain)}


def fit_predict(bundle: dict) -> dict:
    """Physically train matched 2-slot 4-class heads; no validation/held targets in input."""
    verify_bundle(bundle)
    training=bundle["train"]
    xtrain=np.stack([_features(r) for r in training])
    ytrain=np.array([r["target"] for r in training],dtype=np.int64)
    counts=Counter(ytrain.tolist());routes={0:Counter(),1:Counter()}
    for r in training:routes[r["cell"]][r["target"]]+=1
    prior_global=np.array([(counts[i]+1)/(len(training)+4) for i in range(CLASSES)])
    prior_route={c:np.array([(routes[c][i]+1)/(sum(routes[c].values())+4) for i in range(CLASSES)]) for c in (0,1)}
    centroids=np.stack([xtrain[ytrain==c,:-1].mean(axis=0) for c in range(CLASSES)])
    require(np.isfinite(centroids).all(),"centroid class missing")
    centroid_calibration=train_only_centroid_temperature(xtrain,ytrain)
    trials=[]
    for seed in SEEDS:
        rng=random.Random(seed)
        init=np.array([[(rng.random()-.5)*.02 for _ in range(DIM+1)] for c in range(2*CLASSES)],dtype=np.float64).reshape(2,CLASSES,DIM+1)
        models={}
        total_updates={}
        for arm in TRAINED:
            w=init.copy()
            order=[];rng_order=random.Random(seed+77)
            while len(order)<SGD_STEPS:
                permutation=list(range(len(training)));rng_order.shuffle(permutation);order.extend(permutation)
            for tick,idx in enumerate(order[:SGD_STEPS]):
                row=training[idx];cell=row["cell"];x=xtrain[idx];y=ytrain[idx]
                if arm=="shared_one":slot=0
                elif arm=="random_route":slot=_extra_route(row["id"])
                elif arm=="shared_twin":slot=tick%2
                else:slot=cell
                p=_prob(w,x,cell,arm,row["id"])
                delta=p.copy();delta[y]-=1.0
                # One active parameter slot and exactly one update per case.
                # Shared-twin prediction needs two forward paths; its gradient
                # to a selected head is half the average-logit gradient.
                factor=.5 if arm=="shared_twin" else 1.
                grad=delta[:,None]*x[None,:]*factor+WEIGHT_DECAY*w[slot]
                w[slot]-=LEARNING_RATE*grad
            models[arm]=w
            total_updates[arm]={"steps":SGD_STEPS,"active_head_parameters_touched":SGD_STEPS*PARAMS_PER_HEAD,
                                "resident_parameter_slots":1 if arm=="shared_one" else 2,
                                "resident_parameter_scalars":PARAMS_PER_HEAD if arm=="shared_one" else 2*PARAMS_PER_HEAD,
                                "forward_heads_per_query":2 if arm=="shared_twin" else 1,
                                "weights_sha256":hashlib.sha256(b"hepta.p06.head-weights.v1\x00"+w.tobytes()).hexdigest()}
        predictions=[]
        for row in bundle["holdout"]:
            cell=row["cell"];x=_features(row);name=row["id"]
            for arm in ALL_ARMS:
                if arm in TRAINED:p=_prob(models[arm],x,cell,arm,name)
                elif arm=="split_zero":p=_prob(models["split"],x,cell,arm,name)
                elif arm=="split_swap":p=_prob(models["split"],x,cell,arm,name)
                elif arm=="frozen":p=_prob(init,x,cell,"split",name)
                elif arm=="type_prior":p=prior_route[cell]
                elif arm=="global_prior":p=prior_global
                elif arm=="centroid":p=_softmax(centroids@x[:-1]*0.25)
                else:p=_softmax(centroids@x[:-1]*centroid_calibration["selected_temperature"])
                predictions.append({"id":name,"cell":cell,"seed":seed,"arm":arm,"probabilities":[float(v) for v in p]})
        trials.append({"seed":seed,"training":total_updates,"predictions":predictions})
    return {"schema":SCHEMA,"bundle_sha256":digest(canonical(bundle)),"model_source_sha256":ARCHIVE_SHA256,
            "training_policy":{"seeds":list(SEEDS),"sgd_steps":SGD_STEPS,"lr":LEARNING_RATE,"weight_decay":WEIGHT_DECAY,"features_l2_norm":TRAIN_SCALE},
            "heads_real_cpu_sgd":True,"same_pretrained_encoder_and_frozen_features":True,
            "original_encoder_new_forward_calls":0,"producer_observed_heldout_labels":False,
            "original_publisher_gold_previously_exposed":True,
            "centroid_calibration":centroid_calibration,"trials":trials,"authority":"DENY_ALL","disposition":"HOLD_NO_GO"}


def prelabel_commit(bundle_path:Path, output_path:Path, seal_path:Path)->dict:
    bundle=json_read(bundle_path)
    result=fit_predict(bundle)
    sha=write_private(output_path,result)
    seal={"schema":SCHEMA,"bundle_sha256":result["bundle_sha256"],"prelabel_file_sha256":sha,
          "original_head_checkpoint_sha256":[{a:v["weights_sha256"] for a,v in row["training"].items()} for row in result["trials"]],
          "authority":"DENY_ALL","gold_opened_in_producer":False}
    write_private(seal_path,seal)
    return {"prelabel_sha256":sha,"cases":len(bundle["holdout"]),"seeds":len(SEEDS),"authority":"DENY_ALL"}


def _check_prelabel(output_path:Path,seal_path:Path)->dict:
    seal=json_read(seal_path,20000)
    require(seal.get("schema")==SCHEMA and seal.get("authority")=="DENY_ALL" and seal.get("gold_opened_in_producer") is False,"untrusted proposal seal")
    fd=os.open(output_path,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0))
    with os.fdopen(fd,"rb") as f:
        require(stat.S_ISREG(os.fstat(f.fileno()).st_mode),"prelabel must be a regular file")
        raw=f.read(1_500_001)
    require(len(raw)<=1_500_000 and hashlib.sha256(raw).hexdigest()==seal.get("prelabel_file_sha256"),"tampered prelabel predictions")
    result=json.loads(raw,object_pairs_hook=_strict_pairs,parse_constant=_reject_constant)
    require(result.get("schema")==SCHEMA and result.get("bundle_sha256")==seal.get("bundle_sha256") and
            result.get("producer_observed_heldout_labels") is False and
            result.get("original_publisher_gold_previously_exposed") is True and
            result.get("authority")=="DENY_ALL" and result.get("disposition")=="HOLD_NO_GO",
            "unqualified original experiment result")
    require(type(result.get("trials")) is list and len(result["trials"])==len(SEEDS),"incomplete trained seeds")
    require(tuple(row.get("seed") for row in result["trials"])==SEEDS,"seed order or duplication")
    for row,weights in zip(result["trials"],seal["original_head_checkpoint_sha256"],strict=True):
        require(type(row) is dict and row.get("seed") in SEEDS and
                {k:v.get("weights_sha256") for k,v in row["training"].items()}==weights,"modified model checkpoint digest")
    return result


def independent_review(archive_path:Path,bundle_path:Path,output_path:Path,seal_path:Path)->dict:
    # This call intentionally authenticates prelabel bytes BEFORE opening gold.
    results=_check_prelabel(output_path,seal_path)
    redacted=json_read(bundle_path)
    verify_bundle(redacted)
    require(results["bundle_sha256"]==digest(canonical(redacted)),"source view has changed")
    expected_rows={r["id"]:r for r in redacted["holdout"]}
    require(len(expected_rows)==32,"incomplete heldout")
    # Independent source byte/view reconstitution after the prelabel seal:
    # a producer cannot replace genuine mmBERT numerical features with a
    # synthetic feature map and still obtain a matching source review.
    authentic=staged_bundle(archive_path)
    require(canonical(authentic)==canonical(redacted),"redacted source not genuine original features")
    # Re-execute the whole train-only optimizer in the reviewer process and
    # require byte-identical original predictions and paid SGD counters.
    original_replay=fit_predict(redacted)
    require(canonical(results)==canonical(original_replay),"prelabel model trial not deterministically replayable")
    # Independent numerical implementation, not importing this producer's
    # gradient, softmax or head matrix forward function.
    from matched_router_oracle_p06 import audit_math
    oracle=audit_math(redacted,results)
    original=read_original(archive_path)
    source=[json.loads(line,object_pairs_hook=_strict_pairs,parse_constant=_reject_constant) for line in original["dataset.jsonl"].splitlines()]
    gold={r["case_id"]:r["label"] for r in source if r["split"]=="holdout"}
    require(set(gold)==set(expected_rows),"original publisher test IDs mismatch")
    # Historical pretrained model's separately trained Gated Head is a useful
    # NON-equal-budget reference, and is only read by the postseal reviewer.
    gated_rows=json.loads(original["execution/predictions.json"],object_pairs_hook=_strict_pairs,parse_constant=_reject_constant)["predictions"]
    gated={r["case_id"]:r["probabilities"] for r in gated_rows if r.get("arm")=="gated"}
    require(set(gated)==set(gold),"original historical Gated comparator population drift")
    for p in gated.values():
        require(type(p) is list and len(p)==CLASSES and all(type(x) in (float,int) and math.isfinite(x) and 0<=x<=1 for x in p) and abs(math.fsum(p)-1)<1e-6,"untrusted archival Gated probabilities")
    gated_decisions={id_:max(range(CLASSES),key=lambda j:gated[id_][j]) for id_ in gold}
    gated_brier=math.fsum(math.fsum((x-int(j==gold[id_]))**2 for j,x in enumerate(gated[id_])) for id_ in gold)/len(gold)
    gated_scores={"correct":sum(gated_decisions[id_]==gold[id_] for id_ in gold),
                  "multiclass_brier":gated_brier,"same_training_budget_as_p06":False}
    out={}
    for tr in results["trials"]:
        seed=tr["seed"]
        preds=tr["predictions"]
        require(type(preds) is list and len(preds)==32*len(ALL_ARMS),"missing original cohort predictions")
        seen=set(); arms={n:{} for n in ALL_ARMS}
        for row in preds:
            require(type(row) is dict and set(row)=={"id","cell","seed","arm","probabilities"},"changed row contract")
            id_,arm=row["id"],row["arm"]
            require(id_ in gold and row["cell"]==expected_rows[id_]["cell"] and row["seed"]==seed and arm in arms and (arm,id_) not in seen,"changed original route/prediction identity")
            seen.add((arm,id_));p=row["probabilities"]
            require(type(p) is list and len(p)==CLASSES and all(type(v) in (int,float) and math.isfinite(v) and 0<=v<=1 for v in p) and abs(math.fsum(p)-1)<1e-10,"nonfinite or malformed probabilities")
            arms[arm][id_]=p
        require(len(seen)==32*len(ALL_ARMS),"incomplete original predictions")
        scores={}; decisions={}
        for arm,pred in arms.items():
            decisions[arm]={id_:max(range(CLASSES),key=lambda i:pred[id_][i]) for id_ in sorted(gold)}
            scores[arm]={"correct":sum(decisions[arm][x]==gold[x] for x in gold),
                         "multiclass_brier":math.fsum(math.fsum((val-int(i==gold[x]))**2 for i,val in enumerate(pred[x])) for x in gold)/len(gold),
                         "steps_paid": tr["training"][arm]["steps"] if arm in TRAINED else 0}
        paired={}
        for ref in ("random_route","shared_twin","shared_one","type_prior","centroid","split_zero"):
            wins=sum(decisions["split"][x]==gold[x] and decisions[ref][x]!=gold[x] for x in gold)
            loses=sum(decisions["split"][x]!=gold[x] and decisions[ref][x]==gold[x] for x in gold)
            paired[ref]={"split_only_correct":wins,"reference_only_correct":loses,"nominal_exact_p":exact_mcnemar(wins,loses)}
        for ref in ("centroid","centroid_train_loo"):
            wins=sum(decisions[ref][x]==gold[x] and gated_decisions[x]!=gold[x] for x in gold)
            loses=sum(decisions[ref][x]!=gold[x] and gated_decisions[x]==gold[x] for x in gold)
            paired[ref+"_vs_historical_gated"]={"centroid_only_correct":wins,"historical_gated_only_correct":loses,"nominal_posthoc_exact_p":exact_mcnemar(wins,loses)}
        out[str(seed)]={"score":scores,"paired":paired}
    return {"schema":SCHEMA,"original_publisher_archive_sha256":ARCHIVE_SHA256,
            "prelabel_file_sha256":json_read(seal_path,20000)["prelabel_file_sha256"],
            "train_rows":64,"calibration_rows_unused":32,"held_rows":32,
            "physical_cpu_training_steps_per_trained_arm":SGD_STEPS,
            "physical_training_cost_matching":"same SGD steps, 1540 active parameter touches per step; two-head shared_twin pays extra inference forwards",
            "trials":out,"historical_gated_head_comparator":gated_scores,
            "centroid_loo_calibration":results["centroid_calibration"],
            "loo_temperature_grid_boundary_reached":results["centroid_calibration"]["selected_temperature"]==max(results["centroid_calibration"]["candidate_temperatures"]),
            "independent_reviewer_recomputed_train_only_sgd":True,
            "independent_fp64_oracle":oracle,
            "independent_reviewer_reconstructed_source_features":True,
            "original_model_features_real":True,"original_model_new_forwards":0,
            "known_historical_gold_co_resident":True,"truly_new_prospective_panel":False,
            "independent_gold_custody":False,"validated_future_source_family":False,
            "head_specialization_promotable":False,"ndu_task_gain_proved":False,
            "production_authorized":False,"authority":"DENY_ALL","disposition":"HOLD_NO_GO"}


def main():
    import argparse
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest="command",required=True)
    source=sub.add_parser("source");source.add_argument("--archive",type=Path,required=True);source.add_argument("--output",type=Path,required=True)
    prod=sub.add_parser("producer");prod.add_argument("--source",type=Path,required=True);prod.add_argument("--prelabel",type=Path,required=True);prod.add_argument("--seal",type=Path,required=True)
    review=sub.add_parser("review");review.add_argument("--archive",type=Path,required=True);review.add_argument("--source",type=Path,required=True);review.add_argument("--prelabel",type=Path,required=True);review.add_argument("--seal",type=Path,required=True);review.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    if args.command=="source":
        result=staged_bundle(args.archive);write_private(args.output,result)
        print(json.dumps({"cohort":128,"redacted_heldout":True,"authority":"DENY_ALL"}))
    elif args.command=="producer":print(json.dumps(prelabel_commit(args.source,args.prelabel,args.seal)))
    else:
        report=independent_review(args.archive,args.source,args.prelabel,args.seal)
        sealed=write_private(args.out,report)
        print(json.dumps({"report_sha256":sealed,"authority":"DENY_ALL","prospective_gain_claim":False}))

if __name__=="__main__": main()
