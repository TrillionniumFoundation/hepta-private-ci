"""NumPy reconstruction of saved historical AV states and decision readouts.

Torch is used only to decode weights_only checkpoints. Candidate implementations
are not imported. Recorded accepted-cache packets are checked across families;
raw media/feature extraction is outside this reconstruction's independent scope.
"""

import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.special import expit, log_ndtr, ndtr


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def close(a,b,tolerance=2e-9):
    assert np.allclose(a,b,atol=tolerance,rtol=tolerance)


def linear(x,w,name):
    return x@w[name+".weight"].T+w[name+".bias"]


def counts(parameters,dt,mode):
    assert np.isfinite(parameters).all() and 0<=dt<=1
    unit=expit(parameters)
    gap=.15+1.2*unit[0];nu=-(.2+.8*unit[1]);sigma=.2+.45*unit[2]
    reset=.4+.6*unit[3];refractory=.16+.12*unit[4]
    n=np.arange(1,11);elapsed=dt-(n-1)*refractory
    safe=np.where(elapsed>0,elapsed,1.)
    distance=gap+(n-1)*reset;scale=sigma*np.sqrt(safe)
    tail=np.where(elapsed>0,ndtr((-distance-nu*safe)/scale)+np.exp(np.minimum(
        -2*nu*distance/sigma**2+log_ndtr((-distance+nu*safe)/scale),0)),0.)
    assert tail[-1]<=1e-10
    probability=np.r_[1.,tail[:-1]]-tail
    assert probability.min()>-1e-10
    probability=np.maximum(probability,0);probability/=probability.sum()
    if mode=="single":
        zero=probability[0];probability[:]=0;probability[:2]=zero,1-zero
    elif mode=="mean":
        mean=float(probability@np.arange(10));lower=int(np.floor(mean))
        assert 0<=lower<=8
        probability[:]=0;probability[lower:lower+2]=1-(mean-lower),mean-lower
    else:assert mode=="renewal"
    return probability


def step(w,family,raw,state,mode=None):
    x=(raw-w["mean"])/w["scale"]
    if family=="direct":return state
    if family=="gru":
        incoming=x@w["update.weight_ih"].T+w["update.bias_ih"]
        recurrent=state@w["update.weight_hh"].T+w["update.bias_hh"]
        r=expit(incoming[:32]+recurrent[:32]);z=expit(incoming[32:64]+recurrent[32:64])
        proposal=np.tanh(incoming[64:]+r*recurrent[64:])
        return (1-z)*proposal+z*state
    if family=="ssm":
        decay=np.exp(-np.logaddexp(0,linear(x,w,"rate"))*raw[-1])
        gain=expit(linear(x,w,"gain"))
        return (1-gain)*decay*state+gain*np.tanh(linear(x,w,"drive"))
    mode=mode or family
    probability=counts(linear(state,w,"physics"),raw[-1],mode)
    angle=np.pi*expit(w["angle"])
    phase=np.arange(10)[:,None]*angle
    cosine,sine=probability@np.cos(phase),probability@np.sin(phase)
    evolved=np.r_[cosine*state[:16]-sine*state[16:],sine*state[:16]+cosine*state[16:]]
    gain=expit(linear(x,w,"gain"))
    return (1-gain)*evolved+gain*np.tanh(linear(x,w,"drive"))


def reader(w,family,raw,state,history):
    if family=="history":
        slots=np.zeros((6,41));slots[:len(history)]=history
        x=np.r_[slots.ravel(),np.arange(6)<len(history)]
    else:
        raw=raw.copy();raw[-1]=0
        x=(raw-w["mean"])/w["scale"]
        if family!="direct":x=np.r_[x,state]
    return linear(np.tanh(linear(x,w,"reader.0")),w,"reader.2")


def audit(base):
    import torch
    base=Path(base);here=base.parents[1]
    plan=json.loads((base/"PLAN.json").read_text())
    fit=json.loads((base/"FIT.json").read_text())
    frozen=json.loads((base/"FROZEN_MODELS.json").read_text())
    summary=json.loads((base/"SUMMARY.json").read_text())
    scorebook=json.loads((base/"SCORES.json").read_text())
    for path,digest in plan["source_sha256"].items():assert sha(here/path)==digest
    for path,digest in plan["input_sha256"].items():assert sha(base/path)==digest
    assert sha(base/"PLAN.json")==frozen["plan_sha256"]
    assert sha(base/"FIT.json")==frozen["fit_sha256"]
    assert sha(base/"TRACES.jsonl.gz")==scorebook["raw_sha256"]
    models={};validation_scores={}
    for task in plan["tasks"]:
        validation=np.load(base/task/"validation.npz")
        for seed in plan["fit_seeds"]:
            validation_scores[task,seed]={}
            for family in plan["families"]:
                path=base/task/"fits"/f"{family}-{seed}-selected.pt"
                assert sha(path)==fit[task][str(seed)][family]["checkpoint_sha256"]
                w={k:v.detach().cpu().numpy() for k,v in torch.load(path,map_location="cpu",weights_only=True).items()}
                models[task,seed,family]=w
                predictions=[]
                for sequence in validation["x"]:
                    state=np.zeros(32);history=[];outputs=[]
                    for raw in sequence:
                        if family=="history":history.append(raw)
                        else:state=step(w,family,raw,state)
                        outputs.append(reader(w,family,raw,state,history))
                    predictions.append(outputs)
                logits=np.asarray(predictions);labels=validation["y"];mask=validation["mask"]
                bce=float(((np.logaddexp(0,logits)-labels*logits)*mask).sum()/mask.sum())
                close(bce,fit[task][str(seed)][family]["validation_bce"])
                validation_scores[task,seed][family]=bce
            selected=min(plan["ordinary_pool"],key=lambda f:(validation_scores[task,seed][f],f))
            assert selected==frozen["selection"][task][str(seed)]
    with gzip.open(base/"TRACES.jsonl.gz","rt") as stream:runs=[json.loads(line) for line in stream]
    canonical,aligned,posteriors={}, {}, {}
    for run in runs:
        a,v=0,0
        accepted=[e for e in run["execution"]["events"] if e.get("status")=="accepted"]
        updates=run["updates"]
        for j,event in enumerate(accepted):
            _,modality,level=event["action"].split(":")
            if modality=="audio":a=int(level)
            else:v=int(level)
            if run["family"]=="direct":continue
            packet=np.asarray(updates[j]["row"] if run["family"]=="history" else updates[j]["packet"])
            key=run["task"],run["index"],a,v
            if key in canonical:close(canonical[key],packet[:-1])
            canonical[key]=packet[:-1]
            aligned[run["task"],run["index"],"audio",a]=packet[:16]
            aligned[run["task"],run["index"],"video",v]=packet[16:32]
            posteriors[key]=packet[32:38]
        p=np.r_[run["execution"]["output"]["probabilities"],np.zeros(6-len(run["execution"]["output"]["probabilities"]))]
        key=run["task"],run["index"],a,v
        if key in posteriors:close(p,posteriors[key])
        posteriors[key]=p
    max_error,update_count,decision_count,uncovered=0.,0,0,0
    indexed={}
    for run in runs:
        task,seed,family,i=run["task"],run["seed"],run["family"],run["index"]
        fitted="renewal" if family.startswith("same_weight_") else family
        mode=family.removeprefix("same_weight_") if family.startswith("same_weight_") else family
        w=models[task,seed,fitted];state=np.zeros(32);history=[];a,v,prior=0,0,0
        receipts={}
        accepted=[e for e in run["execution"]["events"] if e.get("status")=="accepted"]
        assert len(accepted)==run["requests"]
        for j,event in enumerate(accepted):
            _,modality,level=event["action"].split(":")
            if modality=="audio":assert int(level)==a+1;a=int(level)
            else:assert int(level)==v+1;v=int(level)
            delta=max(a,v)-prior;prior=max(a,v)
            key=task,i,a,v
            packet=None
            if family!="direct":
                update=run["updates"][j]
                packet=np.asarray(update["row"] if family=="history" else update["packet"])
                close(packet[38:40],[a/3,v/3]);close(packet[-1],delta)
                if family=="history":history.append(packet)
                else:
                    close(state,update["before"])
                    state=step(w,fitted,packet,state,mode)
                    error=float(np.max(abs(state-update["after"])))
                    max_error=max(max_error,error);assert error<2e-9
                update_count+=1
            elif key in posteriors:
                packet=np.r_[aligned[task,i,"audio",a],aligned.get((task,i,"video",v),np.zeros(16)),posteriors[key],a/3,v/3,delta]
            if packet is not None:
                receipts[event["after"]]=(packet,state.copy(),list(history),a,v)
        for decision in run["execution"]["decisions"]:
            if decision.get("mode")=="fixed":continue
            key=decision["content_fingerprint"]
            if key not in receipts:uncovered+=1;continue
            packet,h,old_history,a0,v0=receipts[key]
            output=expit(reader(w,fitted,packet,h,old_history))
            observation_cost=run["execution"]["observation_fee"]/run["execution"]["requested_observations"]
            elapsed_cost=run["execution"]["latency_fee"]/run["execution"]["output_elapsed_seconds"]
            for candidate in decision["plans"]:
                ga,gv=a0,v0
                for action in candidate["plan"].split("/"):
                    parts=action.split(":")
                    if parts[0]=="READ":
                        if parts[1]=="audio":ga=int(parts[2])
                        else:gv=int(parts[2])
                close(output[ga*4+gv],candidate["correctness"])
                close(candidate["deadline_miss_probability"],0.)
                expected=(output[ga*4+gv]-observation_cost*candidate["expected_requested_reads"]
                          -elapsed_cost*candidate["expected_seconds"])
                close(expected,candidate["score"])
            best=max(decision["plans"],key=lambda c:(c["score"],c["plan"]),default=None)
            selected=best["plan"] if best is not None and best["score"]>decision["stop_score"] else None
            assert selected==decision["selected"]
            decision_count+=1
        receipt=run["execution"]
        correct=int(np.argmax(receipt["output"]["probabilities"])==run["label"])
        assert correct==run["correct"]
        close(correct-receipt["observation_fee"]-receipt["latency_fee"]-receipt["deadline_penalty"],run["utility"])
        key=task,seed,family,run["policy"],run["index"]
        assert key not in indexed;indexed[key]=run
    effects={}
    for task in plan["tasks"]:
        differences=[]
        for seed in plan["fit_seeds"]:
            ordinary=frozen["selection"][task][str(seed)]
            d=[r["utility"] for r in runs if r["task"]==task and r["seed"]==seed and r["family"]=="renewal" and r["policy"]=="value"]
            b=[r["utility"] for r in runs if r["task"]==task and r["seed"]==seed and r["family"]==ordinary and r["policy"]=="value"]
            differences.append(float(np.mean(d)-np.mean(b)))
        close(np.mean(differences),summary["tasks"][task]["D_minus_B_descriptive_mean"])
        effects[task]={"descriptive_D_minus_B":float(np.mean(differences))}
    selection_status={task:{family:{"selected_epoch_zero_count":sum(
        fit[task][str(seed)][family]["selected_epoch"]==0 for seed in plan["fit_seeds"]),
        "total_seeds":len(plan["fit_seeds"]),
        "reported_selected_physics_parameter_max_changes":[max(
            [value for key,value in fit[task][str(seed)][family]["maximum_parameter_change"].items() if key.startswith("physics")],default=0.)
            for seed in plan["fit_seeds"]]} for family in plan["families"]} for task in plan["tasks"]}
    return {"runs_recomputed":len(runs),"accepted_updates_reconstructed":update_count,
        "decision_readouts_reconstructed":decision_count,"uncovered_direct_decisions":uncovered,
        "maximum_hidden_state_error":max_error,"effects":effects,
        "validation_selection_status":selection_status,
        "scope":"Independent NumPy state/count/reader and accepted-packet cross-family replay; raw media and upstream feature/head extraction not independently recreated here",
        "checkpoint_loader":"Genuine Torch weights_only loader only; candidate models/interfaces not imported",
        "fresh_recording_or_identified_media_law_asserted":False}
