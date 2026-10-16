"""Train genuine-human-label 1700-scalar gated Cells on ARCHIVED pretrained scores.

Distinct from actual pretrained 97D Reader latent: score_text uses a declared
handcrafted lexical sidecar. No 97M Granite model, original TokenBank, or new
encoder forward is available; candidate-only, DENY_ALL, no model promotion.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import random
import time

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from bridge_v79_archived_scores import (SCHEMA,SEEDS,V6_SHA,V7_SHA,file_bytes,make_features,load_sources,original_logits,
    score,sha,canonical,require)
from bridge_split_cell_v77 import GatedNewHead

ARMS = ("score_only_row", "score_only_source", "score_text_row", "score_text_source")
UPDATES = 420
BATCH = 16
LEARNING_RATE = 0.005


def parameter_sha(model):
    result=sha256()
    for name,tensor in sorted(model.state_dict().items()):
        value=tensor.detach().cpu().contiguous().numpy()
        require(value.dtype==np.float32 and bool(np.isfinite(value).all()),
                "finite CPU FP32 Head parameters required")
        result.update(name.encode()+str(tuple(value.shape)).encode()+value.tobytes())
    return result.hexdigest()


def head_identity(model):
    expected={"input.weight":(16,97),"input.bias":(16,),"gate.weight":(1,97),"gate.bias":(1,),
              "output.weight":(2,16),"output.bias":(2,)}
    require({n:tuple(t.shape) for n,t in model.state_dict().items()}==expected,
            "unaltered 1700-scalar gated Head architecture required")
    require(sum(p.numel() for p in model.parameters())==1700,
            "exact registered 1700-scalar Head required")
    return expected


def sampling(rows, *, seed, kind):
    require(kind in ("row","source") and len(rows)==3909,"registered complete natural TRAIN source")
    rng=random.Random(f"hepta-v79-real-multirc/{seed}/{kind}/fixed-420x16")
    groups=defaultdict(list)
    for ix,row in enumerate(rows):groups[row["source_hash"]].append(ix)
    keys=sorted(groups)
    require(len(keys)==64,"exact train source count required")
    chosen=[]
    for _ in range(UPDATES):
        if kind=="row":
            indices=rng.sample(range(len(rows)),BATCH)
        else:
            sources=rng.sample(keys,BATCH)
            indices=[rng.choice(groups[source]) for source in sources]
        require(len(set(indices))==BATCH,"no duplicate example per batch")
        chosen.append(indices)
    return chosen


def dump_json(path,value):
    path=Path(path)
    with path.open("x",encoding="utf-8") as stream:
        json.dump(value,stream,sort_keys=True,indent=2,allow_nan=False)
        stream.write("\n")
        stream.flush();os.fsync(stream.fileno())


def raw_sha(path):
    with Path(path).open("rb") as stream:
        digest=sha256()
        for part in iter(lambda:stream.read(1<<20),b""):
            digest.update(part)
    return digest.hexdigest()


def _loss_control(score_train,labels,score_tune,*,sampler):
    """Two-scalar baseline; same 420x16 row schedule and original training labels."""
    old=torch.from_numpy(original_logits(score_train)[:,1]).contiguous()
    y=torch.tensor(labels,dtype=torch.float32)
    scale=nn.Parameter(torch.tensor(0.,dtype=torch.float32))
    bias=nn.Parameter(torch.tensor(0.,dtype=torch.float32))
    optimizer=torch.optim.Adam((scale,bias),lr=LEARNING_RATE,foreach=False)
    started=time.process_time_ns()
    for inds in sampler:
        optimizer.zero_grad(set_to_none=True)
        q=torch.tensor(inds,dtype=torch.long)
        logits=torch.exp(scale)*old[q]+bias
        loss=F.binary_cross_entropy_with_logits(logits,y[q])
        require(bool(torch.isfinite(loss)),"nonfinite two-scalar control objective")
        loss.backward()
        optimizer.step()
    with torch.no_grad():
        anchor=torch.from_numpy(original_logits(score_tune)[:,1])
        pred=(torch.exp(scale)*anchor+bias>0).long().tolist()
    return dict(trainable_parameters=2,update_count=UPDATES,batch_size=BATCH,
                score_on_tune=pred,log_scale=float(scale.detach()),bias=float(bias.detach()),
                cpu_ns=time.process_time_ns()-started)


def fit_head(seed,arm,train_rows,tune_rows,p_train,p_tune,*,out_dir):
    """No tune labels or source IDs enter optimizer. No historical weights loaded."""
    require(seed in SEEDS and arm in ARMS,"known source-bound cohort required")
    mode="score_text" if arm.startswith("score_text") else "score_only"
    sampler="source" if arm.endswith("source") else "row"
    xtrain=torch.from_numpy(make_features(train_rows,p_train,mode=mode).copy())
    xtune=torch.from_numpy(make_features(tune_rows,p_tune,mode=mode).copy())
    baseline=torch.from_numpy(original_logits(p_train).copy())
    baseline_tune=torch.from_numpy(original_logits(p_tune).copy())
    targets=torch.tensor([r["label"] for r in train_rows],dtype=torch.long)
    require(not xtrain.requires_grad and not xtune.requires_grad and not baseline.requires_grad,
            "pretrained score and lexical input must be frozen")
    head=GatedNewHead(seed+19079)
    head_identity(head)
    initial=parameter_sha(head)
    with torch.no_grad():
        require(torch.equal(head(xtune[:16],baseline_tune[:16]),baseline_tune[:16]),
                "zero-init split Head must reproduce original frozen score")
    params=list(head.parameters())
    opt=torch.optim.Adam(params,lr=LEARNING_RATE,foreach=False)
    planned=sampling(train_rows,seed=seed,kind=sampler)
    begin=time.process_time_ns(),time.perf_counter_ns()
    losses=[]
    for step,ids in enumerate(planned,1):
        idx=torch.tensor(ids,dtype=torch.long)
        opt.zero_grad(set_to_none=True)
        out=head(xtrain[idx],baseline[idx])
        loss=F.cross_entropy(out,targets[idx])
        require(bool(torch.isfinite(loss)),"nonfinite real human-label natural loss")
        loss.backward()
        require(all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in params),
                "missing or nonfinite Cell Head gradient")
        opt.step()
        if step in (1,UPDATES//2,UPDATES):losses.append(dict(step=step,real_label_ce=float(loss.detach())))
    elapsed_cpu=time.process_time_ns()-begin[0]
    elapsed_wall=time.perf_counter_ns()-begin[1]
    head.eval().requires_grad_(False)
    with torch.no_grad():
        train_logits=head(xtrain,baseline).detach().cpu()
        tune_logits=head(xtune,baseline_tune).detach().cpu()
        require(bool(torch.isfinite(train_logits).all()) and bool(torch.isfinite(tune_logits).all()),
                "all candidate logits finite")
    train_dec=train_logits.argmax(-1).tolist()
    tune_dec=tune_logits.argmax(-1).tolist()
    before_dec=(baseline_tune[:,1]>baseline_tune[:,0]).long().tolist()
    require(len(tune_dec)==827 and len(train_dec)==3909,"complete original source outputs required")
    folder=Path(out_dir)
    folder.mkdir(parents=True,exist_ok=False)
    tensors={key.replace(".","__"):val.detach().contiguous().numpy().copy()
             for key,val in head.state_dict().items()}
    np.savez(folder/"head-weights.npz",**tensors)
    np.save(folder/"tune-logits.npy",tune_logits.numpy())
    # Audit label access: only original 3909 train targets touched by optimizer.
    report=dict(schema=SCHEMA,seed=seed,arm=arm,mode=mode,sampler=sampler,
        original_human_labels_train_used=True,train_cases=len(train_rows),tune_cases=len(tune_rows),
        optimizer="Adam_foreach_false",learning_rate=LEARNING_RATE,
        updates=UPDATES,batch_size=BATCH,total_optimizer_exposures=UPDATES*BATCH,
        trainable_parameters=1700,trainable_weight_bytes=6800,
        initial_head_sha256=initial,final_head_sha256=parameter_sha(head),
        sampling_schedule_sha256=sha(canonical(planned)),
        weights_file_sha256=raw_sha(folder/"head-weights.npz"),
        tune_logits_file_sha256=raw_sha(folder/"tune-logits.npy"),
        frozen_old_model_weight_updated=False,frozen_archived_pretrained_scores_modified=False,
        original_granite_hidden_states_used=False,original_granite_encoder_calls_this_run=0,
        exact_original_Reader_logits_reused=True,
        tune_source_labels_used_in_training=False,train_and_tune_source_sets_disjoint=True,
        train_metrics=score(train_rows,train_dec),
        tune_metrics=score(tune_rows,tune_dec),
        frozen_tune_metrics=score(tune_rows,before_dec),
        tune_class_flip_count=sum(a!=b for a,b in zip(tune_dec,before_dec)),
        train_intermediate_losses=losses,
        candidate_tune_prediction_sha256=sha(canonical(tune_dec)),
        cpu_ns=elapsed_cpu,wall_ns=elapsed_wall,
        cpu_scope="train_420_steps_minibatch_forward_backward_Adam_only_excludes_encoding_and_scoring",
        source_disjoint_future_task_verified=False,model_selected=False,
        production_authorized=False,cell_split_authorized=False,native_ndu_admitted=False)
    dump_json(folder/"candidate.json",report)
    return report


def run(original_v6,original_v7,output):
    """Write-once full 3-seed x 4-arm, after exact original archive preflight."""
    started=time.process_time_ns(),time.perf_counter_ns()
    require(not Path(output).exists() and not Path(output).is_symlink(),
            "new output path required; no restore/reuse or silent overwrite")
    data=load_sources(original_v6,original_v7)
    torch.set_num_threads(1)
    Path(output).mkdir(parents=True,exist_ok=False)
    manifest=dict(schema=SCHEMA,status="started",v6_sha256=V6_SHA,v7_sha256=V7_SHA,
        source_identity_sha256=data["source_sha256"],training_cases=3909,
        internal_tune_cases=827,training_sources=64,internal_tune_sources=16,
        old_model_weight_update_count=0,encoder_weight_downloaded=False,
        original_97d_hidden_unavailable=True,feature_mode="archived_score_plus_public_lexical_sidecar",
        training_labels_external_to_original_old_model_only=True,
        historical_human_task_internal_panel_already_exposed=True,
        future_independent_evidence=False,production_authorized=False)
    dump_json(Path(output)/"start.json",manifest)
    result={}
    for seed in SEEDS:
        record=data["reports"][seed]
        result[str(seed)]={"parent_execution_parameter_sha256":record["model_sha256"],
                           "original_train_panel_sha256":record["train_panel_sha256"],
                           "original_tune_panel_sha256":record["tune_panel_sha256"],
                           "frozen_baseline":score(data["tune"],[int(p>.5) for p in record["tune_p"]]),
                           "always_positive":score(data["tune"],[1]*827),"arms":{}}
        for arm in ARMS:
            try:
                result[str(seed)]["arms"][arm]=fit_head(seed,arm,data["train"],data["tune"],
                    record["train_p"],record["tune_p"],out_dir=Path(output)/f"seed-{seed}"/arm)
            except Exception as err:
                fail=dict(schema=SCHEMA,status="failed",seed=seed,arm=arm,
                    error_type=type(err).__name__,error=str(err)[:400],
                    unqualified_partial_work_possible=True,production_authorized=False)
                dump_json(Path(output)/"failed.json",fail)
                raise
        scores=_loss_control(record["train_p"],[r["label"] for r in data["train"]],
                             record["tune_p"],sampler=sampling(data["train"],seed=seed,kind="row"))
        result[str(seed)]["two_scalar_control"]={k:v for k,v in scores.items() if k!="score_on_tune"}
        result[str(seed)]["two_scalar_control"]["tune_metrics"]=score(data["tune"],scores["score_on_tune"])
        result[str(seed)]["two_scalar_control"]["tune_prediction_sha256"]=sha(canonical(scores["score_on_tune"]))
    # Recheck original archives before publishing the completion (immutable source).
    file_bytes(original_v6,"v6")
    file_bytes(original_v7,"v7")
    summary=dict(schema=SCHEMA,status="COMPLETE_EXPOSED_INTERNAL_RESEARCH_ONLY",
        archive_sha256=data["archive_sha256"],source_identity_sha256=data["source_sha256"],
        seeds=list(SEEDS),arms=list(ARMS),train_cases=3909,tune_cases=827,
        independent_training_sources=64,previously_exposed_internal_tune_sources=16,
        training_steps_per_head=UPDATES,trainable_parameters_per_head=1700,
        total_new_head_updates=UPDATES*len(SEEDS)*len(ARMS),
        physical_new_encoder_forward_calls=0,
        inference_on_pretrained_original_scores=True,
        original_tokenbank_hidden_used=False,no_granite_weights_loaded=True,
        original_reader_weight_byte_changes=0,
        costs_include_archived_encoder_generation=False,
        original_source_disjoint_internal_tune=True,
        future_independent_task_accuracy_established=False,
        promoted_model_count=0,production_authorized=False,cell_split_authorized=False,native_ndu_admitted=False,
        process_cpu_ns=time.process_time_ns()-started[0],
        process_wall_ns=time.perf_counter_ns()-started[1],results=result)
    dump_json(Path(output)/"completed.json",summary)
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("v6","v7","output"):
        p.add_argument("--"+name,type=Path,required=True)
    a=p.parse_args()
    run(a.v6,a.v7,a.output)
    print(json.dumps(dict(status="COMPLETE_EXPOSED_INTERNAL_RESEARCH_ONLY",output=str(a.output),
        head_runs=len(ARMS)*len(SEEDS),full_original_encoder_reloaded=False),sort_keys=True))


if __name__=="__main__":main()
