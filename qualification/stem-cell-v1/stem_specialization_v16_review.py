"""Independent NumPy source-bound audit of V16 saved model outputs.

No torch, no V14/V15/V16 producer import, no heldout labels, no optimizer replay.
This is numerical replay plus a no-promotion filter, not publisher attestation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from safetensors.numpy import load

SCHEMA = "hepta.stem.specialization.v16.research"
ARCHIVE = "0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7"
FEATURE = "e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490"
INPUT = "d029f906565946216126db39e4ca3f4f14d7ab5a3c297ec2a62639ccdfbf604a"
V15_SHA = "7a998eebeab237b20c004f4cb4ef19adc48ad3e03ddb778658373049745decdd"
V14_SHA = "7e325bf6a08216b1bb497ee3910682b4155705b56fd77534251a42f590112e86"
SEEDS = (41, 47, 53)
NAMES = ("frozen", "continued", "wide", "centroid", "task", "constant0", "constant1",
         "loss_gate", "loss_gate_swapped", "loss_gate_shuffled", "expected_gate",
         "expected_gate_swapped", "expected_gate_soft", "joint_hard", "joint_swapped",
         "joint_soft", "extra_continued")
PROTOCOL = {
    "schema": SCHEMA, "seeds": [41, 47, 53], "steps_per_extra_fit": 80,
    "minibatch": 16, "learning_rate": 0.1,
    "gate_source": "final frozen V15 experts TRAIN-only", "trained_arm_exposure": "1280 TRAIN example positions",
    "expected_gate_balance_coefficient": 0.02,
    "joint_rule": "soft expected per-expert cross entropy plus balance penalty",
    "joint_training_executes_both_experts": True, "selected_head_hard_inference": True,
    "soft_profiles_execute_both_experts": True,
    "source_only": "original 64 TRAIN + original 32 CALIBRATION, no blind labels",
    "calibration_is_prospective": False, "new_pretrained_encoder_forwards": 0,
    "production_authorized": False,
}


def demand(ok, why):
    if not ok:
        raise ValueError(why)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def pairs(items):
    value = {}
    for key, datum in items:
        demand(key not in value, "duplicate JSON property")
        value[key] = datum
    return value


def readfile(path, limit=2_000_000):
    path = Path(path)
    demand(path.is_file() and not path.is_symlink() and path.stat().st_size <= limit,
           "missing/linked/oversized evidence")
    return path.read_bytes()


def read(path):
    value = json.loads(readfile(path), object_pairs_hook=pairs)
    canonical(value)
    return value


def matrices(root, name, roster):
    demand(name in roster, "missing candidate")
    metadata = roster[name]
    demand(set(metadata) == {"sha256", "state_scalars"}, "incorrect tensor metadata")
    blob = readfile(Path(root)/(name+".safetensors"))
    demand(sha(blob) == metadata["sha256"], "tensor-file bytes changed")
    tensors = load(blob)
    demand(sum(v.size for v in tensors.values()) == metadata["state_scalars"]
           and all(v.dtype==np.float32 and np.isfinite(v).all() for v in tensors.values()),
           "tensor count/type changed")
    return tensors


def saved_v15(root, name, roster):
    demand(name in roster, "V15 model missing")
    metadata = roster[name]
    demand(set(metadata) == {"sha256", "scalars"}, "V15 tensor metadata changed")
    blob = readfile(Path(root)/(name+".safetensors"))
    demand(sha(blob) == metadata["sha256"], "V15 tensor changed")
    tensors = load(blob)
    demand(sum(v.size for v in tensors.values()) == metadata["scalars"] and
           all(v.dtype==np.float32 and np.isfinite(v).all() for v in tensors.values()),"V15 tensor invalid")
    return tensors


def normalize(x, mean):
    z = x - mean
    return z / np.maximum(np.linalg.norm(z,axis=1,keepdims=True),1e-12)


def dense(x, state, prefix=""):
    return x @ state[prefix+"weight"].T + state[prefix+"bias"]


def two_heads(x, state, route=None):
    if route is None:
        centers=state["centers"]
        distance = (x*x).sum(1,keepdims=True)-2*x@centers.T+(centers*centers).sum(1)
        route = distance.argmin(1)
    demand(tuple(route.shape)==(len(x),) and np.all((route == 0)|(route == 1)),"invalid route")
    v=np.empty((len(x),4),dtype=np.float32)
    for k in (0,1):
        ix=np.flatnonzero(route==k)
        v[ix]=dense(x[ix],state,f"heads.{k}.")
    return v,route


def scores_by_profile(x, old, newer, seed):
    split=old["centroid"]
    centroid=two_heads(x,split)[1]
    routes={"centroid":centroid, "task":(dense(x,old["gate"])[:,0]>0).astype(np.int64),
            "loss_gate":(dense(x,newer["loss_gate"])[:,0]>0).astype(np.int64),
            "expected_gate":(dense(x,newer["expected_gate"])[:,0]>0).astype(np.int64),
            "joint_hard":(dense(x,newer["joint_gate"])[:,0]>0).astype(np.int64)}
    perm=np.random.default_rng(seed ^ 0x1616).permutation(len(x))
    routes["loss_gate_shuffled"]=routes["loss_gate"][perm]
    logit={"frozen":dense(x,old["frozen"]),"continued":dense(x,old["continued"]),
           "extra_continued":dense(x,newer["extra_continued"])}
    wide=old["wide"]
    logit["wide"]=dense(x,wide,"parent.")+dense(np.tanh(dense(x,wide,"residual.0.")),wide,"residual.2.")
    logit["centroid"]=two_heads(x,split,routes["centroid"])[0]
    logit["task"]=two_heads(x,split,routes["task"])[0]
    logit["constant0"]=two_heads(x,split,np.zeros(len(x),dtype=np.int64))[0]
    logit["constant1"]=two_heads(x,split,np.ones(len(x),dtype=np.int64))[0]
    for a in ("loss_gate","expected_gate"):
        logit[a]=two_heads(x,split,routes[a])[0]
        logit[a+"_swapped"]=two_heads(x,split,1-routes[a])[0]
    logit["loss_gate_shuffled"]=two_heads(x,split,routes["loss_gate_shuffled"])[0]
    def soft(model, gate):
        weight=1/(1+np.exp(-np.clip(dense(x,gate)[:,0],-30,30)))
        return (1-weight[:,None])*dense(x,model,"heads.0.")+weight[:,None]*dense(x,model,"heads.1.")
    logit["expected_gate_soft"]=soft(split,newer["expected_gate"])
    joint=newer["joint"]
    logit["joint_hard"]=two_heads(x,joint,routes["joint_hard"])[0]
    logit["joint_swapped"]=two_heads(x,joint,1-routes["joint_hard"])[0]
    logit["joint_soft"]=soft(joint,newer["joint_gate"])
    result={}
    for k,value in logit.items():
        v=value.astype(np.float64)
        expo=np.exp(v-v.max(1,keepdims=True))
        result[k]=expo/expo.sum(1,keepdims=True)
    demand(set(result)==set(NAMES),"not all profiles numerically reproduced")
    return result,{k:v.tolist() for k,v in routes.items()}


def brier(p,y):
    return float(((p-np.eye(4)[y])**2).sum(1).mean())


def candidate_select(scores,old_fit):
    choices=("frozen","continued","wide","centroid","task","loss_gate","expected_gate","joint_hard","extra_continued")
    allowed=["frozen"]+[a for a in choices[1:] if scores["frozen"]-scores[a]>.01
                        and old_fit[a]-old_fit["frozen"]<=.01]
    win=min(allowed,key=lambda a:(scores[a],choices.index(a)))
    if win not in ("frozen","continued","extra_continued") and scores["continued"]-scores[win]<=.01:
        win=min((a for a in allowed if a in ("frozen","continued","extra_continued")),key=lambda a:(scores[a],choices.index(a)))
    return win


def review(inputs, v15_dir, candidate):
    inputs, v15_dir, candidate = map(Path,(inputs,v15_dir,candidate))
    meta=read(inputs/"input.json")
    demand(sha(readfile(inputs/"input.json"))==INPUT,"input identity mismatch")
    demand(set(meta["labels"])=={str(i) for a in ("train","calibration") for i in meta["partitions"][a]},
           "held labels leaked")
    data=readfile(inputs/"features.safetensors")
    demand(sha(data)==FEATURE,"source feature tensor mismatch")
    matrix=load(data)["features"]
    demand(matrix.shape==(128,384) and matrix.dtype==np.float32,"feature shape mismatch")
    v15=read(v15_dir/"sealed.json")
    require_record=read(candidate/"sealed.json")
    demand(require_record["schema"]==SCHEMA and require_record["protocol"]==PROTOCOL
           and require_record["protocol_sha256"]==sha(canonical(PROTOCOL))
           and require_record["v15_seal_sha256"]==sha(readfile(v15_dir/"sealed.json"))
           and require_record["v15_sha256"]==V15_SHA and require_record["archive_sha256"]==ARCHIVE
           and require_record["input_sha256"]==INPUT and require_record["feature_sha256"]==FEATURE
           and require_record["source_sha256"]==sha(readfile(Path(__file__).with_name("stem_specialization_v16.py")))
           and sha(readfile(Path(__file__).with_name("stem_stable_router_v15.py")))==V15_SHA,
           "source / protocol identity mismatch")
    demand(require_record["production_authorized"] is False
           and require_record["prospective_efficacy_verified"] is False
           and require_record["held_labels_read"] is False and require_record["held_scores"] is None
           and require_record["target_host_4096_qualified"] is False
           and require_record["new_encoder_forwards"]==0
           and require_record["independent_future_utility"] is None
           and require_record["independent_negative_transfer"] is None,
           "false effect/utility/host claim")
    demand(set(require_record["seeds"])=={"41","47","53"},"missing original training seed")
    census=require_record["model_files"]
    expected={f"{seed}-{name}" for seed in SEEDS for name in ("loss_gate","expected_gate","joint","joint_gate","extra_continued")}
    demand(set(census)==expected and
           {p.name for p in candidate.iterdir()}=={f"{name}.safetensors" for name in expected}|{"sealed.json"},
           "extra/missing/unregistered candidate models")
    # Validate entire V15 lineage, not merely the five forward-used tensors.
    demand(len(v15["models"])==58 and set(v15["seeds"])=={"41","47","53"}
           and v15["producer_sha256"]==V15_SHA and v15["held_scores"] is None,"V15 invalid")
    for name in v15["models"]:
        saved_v15(v15_dir,name,v15["models"])
    original=matrix
    p=meta["partitions"]
    tx,cx,hx=(original[p[key]] for key in ("train","calibration","holdout"))
    y=np.array([meta["labels"][str(i)] for i in p["train"]])
    cy=np.array([meta["labels"][str(i)] for i in p["calibration"]])
    mean=saved_v15(v15_dir,"normalizer",v15["models"])["mean"]
    z,cz,hz=(normalize(x,mean) for x in (tx,cx,hx))
    maximum=0.0; summaries={}
    for seed in SEEDS:
        sid=str(seed)
        old={name:saved_v15(v15_dir,f"{seed}-{name}",v15["models"])
             for name in ("frozen","continued","wide","centroid","gate")}
        new={name:matrices(candidate,f"{seed}-{name}",census)
             for name in ("loss_gate","expected_gate","joint","joint_gate","extra_continued")}
        def shape_require(state,shape):
            demand(set(state)==set(shape) and all(state[k].shape==value for k,value in shape.items()),
                   "tensor shape or name mismatch")
        gate_shape={"weight":(1,384),"bias":(1,)}
        for key in ("loss_gate","expected_gate","joint_gate"):
            shape_require(new[key],gate_shape)
        shape_require(new["extra_continued"],{"weight":(4,384),"bias":(4,)})
        shape_require(new["joint"],{"centers":(2,384),**{f"heads.{k}.{f}":shape for k in (0,1)
                   for f,shape in (("weight",(4,384)),("bias",(4,)))}})
        demand(np.array_equal(new["joint"]["centers"],old["centroid"]["centers"]),"joint original centers drift")
        schedule=np.random.default_rng(seed ^ 0x1616).integers(0,64,(80,16)).astype("<i8").tobytes()
        work=require_record["seeds"][sid]["work"]
        demand(set(work)=={"loss_gate","expected_gate","joint","extra_continued"},"wrong charged training arms")
        for a,details in work.items():
            demand(details["optimizer_steps"]==80 and details["examples"]==1280
                   and details["scheduled_sha256"]==sha(schedule)
                   and details["source_train_rows"]==64
                   and type(details["cpu_ns"]) is int and details["cpu_ns"]>=0
                   and type(details["wall_ns"]) is int and details["wall_ns"]>=0,
                   "unmatched optimizer work or source policy")
        demand(work["joint"]["train_symmetric_expert_forwards"]==2560 and
               work["loss_gate"]["experts_trained"] is False and
               work["expected_gate"]["experts_trained"] is False and
               work["joint"]["experts_trained"] is True,"fake active train operator counts")
        record=require_record["seeds"][sid]
        cal,routes=scores_by_profile(cz,old,new,seed)
        train,_=scores_by_profile(z[:32],old,new,seed)
        blind,b_routes=scores_by_profile(hz,old,new,seed)
        demand(set(record["calibration"])==set(NAMES)
               and set(record["calibration_probabilities"])==set(NAMES)
               and set(record["blind_probabilities"])==set(NAMES),"wrong profile census")
        for saved_values,calculated in ((record["calibration_probabilities"],cal),(record["blind_probabilities"],blind)):
            for name,pred in calculated.items():
                stored=np.array(saved_values[name],dtype=np.float64)
                demand(stored.shape==(32,4) and np.isfinite(stored).all()
                       and np.allclose(stored.sum(1),1,atol=1e-6,rtol=0),"invalid output")
                delta=float(np.max(np.abs(pred-stored)))
                maximum=max(maximum,delta)
                demand(delta<5e-5 and np.array_equal(stored.argmax(-1),pred.argmax(-1)),
                       "independent forward/probability mismatch")
        demand(record["calibration_routes"]==routes and record["blind_routes"]==b_routes,
               "routing did not replay")
        cal_briers={key:brier(value,cy) for key,value in cal.items()}
        old_briers={key:brier(value,y[:32]) for key,value in train.items()}
        for key,value in cal_briers.items():
            demand(record["calibration"][key]["correct"]==int((cal[key].argmax(1)==cy).sum())
                   and abs(record["calibration"][key]["brier"]-value)<5e-5,
                   "false cal correct/Brier")
        for key,value in old_briers.items():
            demand(abs(record["old_train_brier"][key]-value)<5e-5,"false old TRAIN retention")
        selection=candidate_select(cal_briers,old_briers)
        demand(record["selected_research_candidate"]==selection,"selector did not replay")
        # Verify OOF teacher alignment diagnostic independently from already frozen models.
        teacher=old["centroid"]
        logits=np.stack((dense(z,teacher,"heads.0."),dense(z,teacher,"heads.1.")),1)
        v=logits.astype(np.float64)
        logp=v-np.log(np.exp(v-v.max(-1,keepdims=True)).sum(-1,keepdims=True))-v.max(-1,keepdims=True)
        loss=-np.take_along_axis(logp,np.broadcast_to(y[:,None,None],(64,2,1)),axis=2).squeeze(-1)
        best=loss.argmin(-1)
        oof=np.array(v15["seeds"][sid]["oof_targets"])
        diag=record["diagnostics"]
        demand(diag["v15_oof_vs_final_expert_direct_agreement"]==int((oof==best).sum())
               and diag["v15_oof_vs_final_expert_flipped_agreement"]==int((oof!=best).sum())
               and diag["train_optimal_head_counts"]==np.bincount(best,minlength=2).tolist()
               and diag["train_loss_gate_vs_final_optimal_agreement"]==int(((dense(z,new["loss_gate"])[:,0]>0)==best).sum())
               and record["frozen_parent_and_v15_heads_unchanged"] is True,"expert-identity diagnosis drift")
        summaries[sid]={"selected_research_candidate":selection,"calibration":record["calibration"],
                        "OOF_direct_matches":int((oof==best).sum()),
                        "OOF_flipped_matches":int((oof!=best).sum()),
                        "candidate_sha256s":{name:census[f"{seed}-{name}"]["sha256"] for name in new},
                        "charged_optimizer_updates":320,
                        "joint_train_2head_rows":2560,
                        "blind_labels_used":False}
    return {"schema":SCHEMA+".numpy-review", "status":"CALIBRATION_ONLY_SPECIALIZATION_UNPROVEN",
        "model_files_verified":15,"v15_original_files_verified":58,
        "independent_calibration_probability_rows":len(SEEDS)*32*len(NAMES),
        "independent_unscored_blind_rows":len(SEEDS)*32*len(NAMES),
        "max_probability_error":maximum,"seeds":summaries,
        "source_sha256":require_record["source_sha256"],
        "sealed_sha256":sha(readfile(candidate/"sealed.json")),
        "independent_gradient_reexecution":False,"held_scores":None,
        "prospective_utility":None,"target_host_4096":False,"production_authorized":False}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs",required=True)
    parser.add_argument("--v15",required=True)
    parser.add_argument("--candidate",required=True)
    parser.add_argument("--output",required=True)
    a=parser.parse_args()
    result=review(a.inputs,a.v15,a.candidate)
    with Path(a.output).open("xb") as f:
        f.write(canonical(result)+b"\n")
