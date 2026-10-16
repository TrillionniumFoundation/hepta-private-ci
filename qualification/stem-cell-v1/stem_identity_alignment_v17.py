"""V17 TRAIN-anchor Cell expert-identity alignment and frozen-expert router probe.

Historical real mmBERT features; no held labels, no new Encoder execution, no
production authority. Folds use original V15 TRAIN-only saved teacher models.
All alignment decisions use unlabeled TRAIN-anchor features only. The global
reference does depend on all TRAIN labels through its learned experts for the
logit-alignment diagnostic; geometric alignment uses only frozen centroids.
The former is not an independent out-of-fold teacher. Neither is prospective.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import time
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from safetensors.torch import save as save_torch, load as load_torch

import stem_counterfactual_split_v14 as v14
import stem_stable_router_v15 as v15
import stem_specialization_v16 as v16

SCHEMA="hepta.stem.identity-alignment.v17.research"
V16_SHA="cb42cc34fe6f8c17d8dc5887964ff3f9c7eb10be09ca604677ab498a24c4db20"
SEEDS=(41,47,53)
ARM_NAMES=("extra_continued", "continued", "centroid", "constant0", "constant1", "v15_oof_gate",
           "v16_final_loss_gate", "unaligned_oof", "geo_aligned_oof", "geo_aligned_swapped",
           "geo_aligned_shuffled", "logit_aligned_oof", "logit_aligned_swapped")
ROUTE_NAMES=("v15_oof_gate","v16_final_loss_gate","unaligned_oof", "geo_aligned_oof",
             "geo_aligned_swapped","geo_aligned_shuffled","logit_aligned_oof","logit_aligned_swapped",
             "centroid")
PROTOCOL={"schema":SCHEMA,"seeds":[41,47,53],"router_steps":80,"batch":16,"learning_rate":0.1,
          "fold_count":4,"alignment_anchor":"other 48 original TRAIN rows; no CAL or blind labels",
          "geometry_reference":"frozen V15 full-TRAIN centroids and label-free assignments",
          "logit_reference":"V15 final experts trained with all TRAIN labels; diagnostic only, not unbiased OOF",
          "tie_rule":"do not swap on equal anchor count / equal logit error",
          "training":"identical sigmoid logistic objective, zero initialization, seed xor 0x1717 minibatches",
          "confidence":"calibration-only; 32 previously exposed rows; no significance claim",
          "baseline":"frozen V16 extra_continued; its whole training lifecycle not FLOP-matched",
          "blind_label_access":False,"new_encoder_forwards":0,"production_authorized":False}


def require(condition,reason):
    if not condition:raise ValueError(reason)


def norm(x,mean):
    return v15.normalized(x,mean)


def fold_permutations(train_z,train_x,final_split,v15_dir,seal,seed,folds):
    """No labels accepted. Returns per-fold independent alignment diagnostics."""
    outputs=[]
    for fold_id,held_indexes in enumerate(folds):
        require(len(held_indexes)==16 and len(set(held_indexes))==16,"wrong fold cardinality")
        anchors=[i for i in range(64) if i not in held_indexes]
        name=f"{seed}-fold{fold_id}"
        inner_mean=v16.load_typed(v15_dir,name+"-normalizer",seal["models"])["mean"]
        inner=v16.load_typed(v15_dir,name+"-split",seal["models"])
        inner_centers=inner["centers"]
        anchor_f=norm(train_x[anchors],inner_mean)
        rout_inner=v14.assign(anchor_f,inner_centers)
        rout_final=v14.assign(train_z[anchors],final_split.centers)
        keep=int((rout_inner==rout_final).sum())
        reverse=len(anchors)-keep
        geometric_flip=int(reverse>keep)
        # Secondary label-free *but final-weight-dependent* diagnostic.
        # Its reference experts have been fitted with withheld-fold TRAIN labels.
        with torch.no_grad():
            old_logits=torch.stack([F.linear(anchor_f,inner[f"heads.{i}.weight"],inner[f"heads.{i}.bias"])
                                    for i in (0,1)],dim=1)
            new_logits=v16.fixed_scores(final_split,train_z[anchors])
            keep_err=float(((old_logits-new_logits)**2).sum())
            reverse_err=float(((old_logits-new_logits[:,[1,0]])**2).sum())
            logit_flip=int(reverse_err<keep_err)
        outputs.append({"fold":fold_id,"held_rows":held_indexes,"anchor_rows":len(anchors),
            "geo_keep":keep,"geo_reverse":reverse,"geo_flip":geometric_flip,
            "logit_keep_error":keep_err,"logit_reverse_error":reverse_err,"logit_flip":logit_flip,
            "labels_used_by_alignment":False,"reference_trained_on_excluded_labels_for_logit_arm":True})
    return outputs


def train_gate(features,labels,schedule):
    v14.checked_features(features)
    require(tuple(labels.shape)==(64,) and labels.dtype==torch.long
            and bool(((labels==0)|(labels==1)).all()),"binary aligned TRAIN-only targets")
    gate=nn.Linear(384,1)
    nn.init.zeros_(gate.weight);nn.init.zeros_(gate.bias)
    optimizer=torch.optim.SGD(gate.parameters(),lr=0.1)
    start=time.process_time_ns()
    for indexes in schedule:
        ix=torch.tensor(indexes,dtype=torch.long)
        optimizer.zero_grad(set_to_none=True)
        loss=F.binary_cross_entropy_with_logits(gate(features[ix]).squeeze(1),labels[ix].float())
        require(bool(torch.isfinite(loss)),"nonfinite router loss")
        loss.backward();optimizer.step()
    gate.eval().requires_grad_(False)
    return gate,{"steps":len(schedule),"examples":sum(map(len,schedule)),
                 "cpu_ns":time.process_time_ns()-start,
                 "schedule_sha256":v14.sha(np.asarray(schedule,dtype="<i8").tobytes()),
                 "label_counts":torch.bincount(labels,minlength=2).tolist()}


def score_heads(features,split,continued,extra,v15_gate,v16_gate,gates,seed):
    with torch.no_grad():
        n=len(features)
        routes={"centroid":v14.assign(features,split.centers),
                "v15_oof_gate":v16.gate_routes(v15_gate,features),
                "v16_final_loss_gate":v16.gate_routes(v16_gate,features),
                **{name:v16.gate_routes(gate,features) for name,gate in gates.items()}}
        perm=torch.from_numpy(np.random.default_rng(seed^0x1717).permutation(n))
        routes["geo_aligned_swapped"]=1-routes["geo_aligned_oof"]
        routes["geo_aligned_shuffled"]=routes["geo_aligned_oof"][perm]
        routes["logit_aligned_swapped"]=1-routes["logit_aligned_oof"]
        probability={"extra_continued":extra(features).softmax(1).tolist(),
                     "continued":continued(features).softmax(1).tolist()}
        for cell in (0,1):
            probability[f"constant{cell}"]=split(features,torch.full((n,),cell,dtype=torch.long)).softmax(1).tolist()
        for name,r in routes.items():
            probability[name]=split(features,r).softmax(1).tolist()
        require(set(probability)==set(ARM_NAMES) and set(routes)==set(ROUTE_NAMES),"incomplete profiles")
    return probability,{k:v.tolist() for k,v in routes.items()}


def research_select(scores,old_fit):
    require(set(scores)==set(old_fit)==set(ARM_NAMES),"incomplete candidate set")
    baseline="extra_continued"
    viable=["unaligned_oof","geo_aligned_oof","logit_aligned_oof"]
    eligible=[a for a in viable if scores[baseline]-scores[a]>.01
              and old_fit[a]-old_fit[baseline]<=.01]
    return min(eligible,key=lambda a:(scores[a],viable.index(a))) if eligible else baseline


def load_v16_typed(directory,name,inventory):
    require(name in inventory and set(inventory[name])=={"sha256","state_scalars"}, "invalid V16 census")
    raw=v16.checked_bytes(Path(directory)/(name+".safetensors"),inventory[name]["sha256"])
    state=load_torch(raw)
    require(sum(x.numel() for x in state.values())==inventory[name]["state_scalars"]
            and all(x.dtype==torch.float32 and x.device.type=="cpu" and bool(torch.isfinite(x).all())
                    for x in state.values()),"invalid V16 typed tensor")
    return state


def run(inputs,v15_dir,v16_dir,output):
    output=Path(output);inputs,v15_dir,v16_dir=map(Path,(inputs,v15_dir,v16_dir))
    require(not output.exists() and output.parent.is_dir() and not output.parent.is_symlink(),"new output directory")
    require(v14.sha(Path(v16.__file__).read_bytes())==V16_SHA,"V16 source changed")
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    x,meta,seal=v16.open_v15(inputs,v15_dir)
    v16_seal=v14.read_json(v16_dir/"sealed.json")
    require(v16_seal["schema"]==v16.SCHEMA and v16_seal["protocol"]==v16.PROTOCOL
            and v16_seal["source_sha256"]==V16_SHA
            and v16_seal["v15_seal_sha256"]==v14.sha((v15_dir/"sealed.json").read_bytes())
            and v16_seal["held_labels_read"] is False and v16_seal["held_scores"] is None
            and v16_seal["production_authorized"] is False and len(v16_seal["model_files"])==15,
            "wrong V16 lineage/source/effect claim")
    require({p.name for p in v16_dir.iterdir()}=={name+".safetensors" for name in v16_seal["model_files"]}|{"sealed.json"},"foreign V16 state")
    for name in v16_seal["model_files"]:
        load_v16_typed(v16_dir,name,v16_seal["model_files"])
    pp=meta["partitions"]
    train,cal,blind=(x[pp[k]] for k in ("train","calibration","holdout"))
    y=torch.tensor([meta["labels"][str(i)] for i in pp["train"]],dtype=torch.long)
    cal_y=torch.tensor([meta["labels"][str(i)] for i in pp["calibration"]],dtype=torch.long)
    require(set(meta["labels"])=={str(i) for key in ("train","calibration") for i in pp[key]},"blind labels present")
    mean=v16.load_typed(v15_dir,"normalizer",seal["models"])["mean"]
    z,cz,hz=(norm(a,mean) for a in (train,cal,blind))
    folds=seal["folds"]
    require(len(folds)==4 and sorted(sum(folds,[]))==list(range(64)),"wrong original fold plan")
    output.mkdir(mode=0o700)
    result={"schema":SCHEMA,"protocol":PROTOCOL,"protocol_sha256":v14.sha(v14.canonical(PROTOCOL)),
            "source_sha256":v14.sha(Path(__file__).read_bytes()),"v16_source_sha256":V16_SHA,
            "v15_seal_sha256":v14.sha((v15_dir/"sealed.json").read_bytes()),
            "v16_seal_sha256":v14.sha((v16_dir/"sealed.json").read_bytes()),
            "archive_sha256":v14.ARCHIVE_SHA,"input_sha256":v14.INPUT_SHA,
            "feature_sha256":v14.FEATURE_SHA,"new_encoder_forwards":0,
            "held_labels_read":False,"held_scores":None,"future_utility":None,
            "production_authorized":False,"prospective_efficacy_verified":False,
            "independent_retention":None,"target_host_4096_qualified":False,
            "models":{},"seeds":{}}
    for seed in SEEDS:
        parent=str(seed)
        frozen_state=lambda suffix:v16.load_typed(v15_dir,parent+"-"+suffix,seal["models"])
        split=v16.make_split(frozen_state("centroid"))
        continued=nn.Linear(384,4);continued.load_state_dict(frozen_state("continued"));continued.eval().requires_grad_(False)
        v15_gate=v16.make_gate(frozen_state("gate"));v15_gate.eval().requires_grad_(False)
        extra=nn.Linear(384,4);extra.load_state_dict(load_v16_typed(v16_dir,parent+"-extra_continued",v16_seal["model_files"]));extra.eval().requires_grad_(False)
        v16_gate=v16.make_gate(load_v16_typed(v16_dir,parent+"-loss_gate",v16_seal["model_files"]));v16_gate.eval().requires_grad_(False)
        frozen_hashes=[v14.parameter_sha(m) for m in (split,continued,extra,v15_gate,v16_gate)]
        details=fold_permutations(z,train,split,v15_dir,seal,seed,folds)
        original=torch.tensor(seal["seeds"][parent]["oof_targets"],dtype=torch.long)
        geo=original.clone();logit=original.clone()
        for d in details:
            ix=d["held_rows"]
            if d["geo_flip"]:geo[ix]=1-geo[ix]
            if d["logit_flip"]:logit[ix]=1-logit[ix]
        targets={"unaligned_oof":original,"geo_aligned_oof":geo,"logit_aligned_oof":logit}
        schedule=np.random.default_rng(seed^0x1717).integers(0,64,(80,16)).tolist()
        new_gates,work={},{}
        for label,binary in targets.items():
            gate,stats=train_gate(z,binary,schedule)
            new_gates[label]=gate
            work[label]=stats
            tensors={k:v.detach().contiguous() for k,v in gate.state_dict().items()}
            raw=save_torch(tensors)
            name=f"{parent}-{label}"
            v14.write_new(output/(name+".safetensors"),raw)
            result["models"][name]={"sha256":v14.sha(raw),"state_scalars":sum(v.numel() for v in tensors.values())}
        probability,routes=score_heads(cz,split,continued,extra,v15_gate,v16_gate,new_gates,seed)
        old_probability,_=score_heads(z[:32],split,continued,extra,v15_gate,v16_gate,new_gates,seed)
        blind_probability,blind_routes=score_heads(hz,split,continued,extra,v15_gate,v16_gate,new_gates,seed)
        cal_stats={k:{"correct":int((torch.tensor(v).argmax(-1)==cal_y).sum()),
                     "brier":v14.brier(torch.tensor(v),cal_y)} for k,v in probability.items()}
        oldfit={k:v14.brier(torch.tensor(v),y[:32]) for k,v in old_probability.items()}
        actual=research_select({k:v["brier"] for k,v in cal_stats.items()},oldfit)
        oracle=torch.stack([torch.tensor(probability[f"constant{i}"]) for i in (0,1)],dim=1)
        loss=((oracle-F.one_hot(cal_y,4)[:,None,:].float())**2).sum(2)
        theoretical_min=float(loss.min(1).values.mean())
        disagreement=int((oracle[:,0,:].argmax(1)!=oracle[:,1,:].argmax(1)).sum())
        for before,mod in zip(frozen_hashes,(split,continued,extra,v15_gate,v16_gate)):
            require(v14.parameter_sha(mod)==before,"frozen lineage mutated")
        result["seeds"][parent]={"alignment":details,"target_counts":{k:torch.bincount(v,minlength=2).tolist() for k,v in targets.items()},
                 "targets_sha256":{k:v14.sha(v.numpy().astype("<i8").tobytes()) for k,v in targets.items()},
                 "work":work,"calibration":cal_stats,"calibration_probabilities":probability,"calibration_routes":routes,
                 "blind_probabilities":blind_probability,"blind_routes":blind_routes,
                 "old_train_brier":oldfit,"selected_research_candidate":actual,
                 "post_label_calibration_oracle_brier":theoretical_min,
                 "calibration_expert_class_disagreement":disagreement,
                 "frozen_v15_v16_lineages_unchanged":True}
    require(v14.sha((inputs/"input.json").read_bytes())==v14.INPUT_SHA,"input changed")
    require(v14.sha((v15_dir/"sealed.json").read_bytes())==result["v15_seal_sha256"],"V15 changed")
    require(v14.sha((v16_dir/"sealed.json").read_bytes())==result["v16_seal_sha256"],"V16 changed")
    v14.write_new(output/"sealed.json",v14.canonical(result))
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inputs",required=True)
    p.add_argument("--v15",required=True)
    p.add_argument("--v16",required=True)
    p.add_argument("--output",required=True)
    args=p.parse_args();run(args.inputs,args.v15,args.v16,args.output)
