"""Actual-output joint-trajectory NDU updates with complete physical costs.

This uses the joint score of both sequential episodes, so a second episode's
measured cost may depend on the first sampled output. Residual direct parameter
influence on physical timing is still a declared conditional-exogeneity
assumption. Optimizer and receipt serialization are reported outside episodes.
"""
import hashlib
import json
import math
from pathlib import Path
import time

import torch

from ..unified_20261028.profile import digest, moment_cost
from .control_actor import fit_actor
from .natural_episode import initial_actor, save
from .natural_model import LAW, parameter_hash
from .natural_protocol import STUDY
from .natural_train import load_checkpoint
from .profile_contract import cpu_seconds


def tree_hash(value):
    h = hashlib.sha256()
    def add(item):
        if isinstance(item, torch.Tensor):
            tensor = item.detach().cpu().contiguous()
            h.update(str((str(tensor.dtype),tuple(tensor.shape))).encode())
            h.update(tensor.numpy().tobytes())
        elif isinstance(item, dict):
            for key in sorted(item, key=repr):
                h.update(repr(key).encode());add(item[key])
        elif isinstance(item, (tuple,list)):
            h.update(str(len(item)).encode())
            for part in item:add(part)
        else:
            h.update(json.dumps(item,sort_keys=True,allow_nan=False).encode())
    add(value)
    return h.hexdigest()


def write_checkpoint(path, model, initial_state, profile, protocol_sha, step):
    state = {"schema":"hepta.closure.natural-checkpoint.v1", "model":model.state_dict(),
             "ontology":model.ontology, "emission_law":LAW, "parameter_sha256":parameter_hash(model),
             "warmstart_protocol_sha256":initial_state["warmstart_protocol_sha256"], "step":step,
             "actual_training_profile_sha256":profile.digest, "actual_training_protocol_sha256":protocol_sha}
    temporary = Path(path).with_suffix(".pending")
    torch.save(state,temporary);temporary.replace(path)
    return {"path":str(path),"parameter_sha256":state["parameter_sha256"],
            "sha256":hashlib.sha256(Path(path).read_bytes()).hexdigest(),"step":step}


def release_training_media(directory, receipt, retain):
    directory = Path(directory).resolve()
    unusual_emission=any(item.get("failure") or item.get("terminal_kind")=="failed" for item in receipt["emissions"])
    if (retain or receipt["terminal_kind"] != "delivered" or receipt["host_refusals"]
            or receipt["cpu_admission_threshold_exceeded"] or unusual_emission):
        return {"retained":True,"reason":"registered boundary sample or any unusual branch, including a failed first emission before successful retry"}
    files = {}
    for branch in ("initial","final"):
        native = receipt["native_execution"][branch]
        for kind,path in native["artifact_refs"].items():
            files[Path(path).resolve()] = native["artifact_sha256"][kind]
    removal = []
    for path,pin in files.items():
        if directory not in path.parents or path.suffix not in (".txt",".wav",".png",".mkv"):
            raise ValueError("Training retention may only release its own metered media")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != pin:
            raise ValueError("Training media changed before its registered release")
        removal.append({"path":str(path),"sha256":pin,"bytes":path.stat().st_size})
    # The completed episode and update/actor-fit record are already closed on
    # disk before this function is called. Keep a separate immutable release
    # record, never alter an original physical-observation receipt.
    save(directory/"MEDIA_RELEASE.json",{"schema":"hepta.closure.training-media-release.v1",
         "episode_receipt_sha256":hashlib.sha256((directory/"EPISODE.json").read_bytes()).hexdigest(),
         "removed":removal,"scope":"only consumed intermediate training media; replay from recorded schedule, not later independent reread"})
    for path in files:path.unlink()
    return {"retained":False,"released_bytes":sum(row["bytes"] for row in removal)}


def fit_actual_policy(*, runner, model, checkpoint, source_rows, output, seed, reference_actor=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    sources=sorted(source_rows,key=lambda item:hashlib.sha256(("natural-actor-fit:"+item[1]["source_id"]).encode()).hexdigest())[:16]
    model.eval()
    reference=reference_actor or initial_actor(runner.profile)
    if reference.profile_sha256!=runner.profile.digest:raise ValueError("Reference actor profile changed")
    protocol={"schema":"hepta.closure.natural-actor-fit.v1","profile_sha256":runner.profile.digest,
              "current_parameter_sha256":parameter_hash(model),"reference_actor":reference.to_dict(),
              "sources":[row["source_id"] for _,row in sources],"seed":seed,
              "design":"paired complete actions; actual reference prediction overhead included; source-uniform direct moment fit"}
    save(output/"PROTOCOL.json",protocol)
    namespace=hashlib.sha256(str(output.resolve()).encode()).hexdigest()[:16]
    rows=[]
    for index,(directory,_) in enumerate(sources):
        for action in (("keep","swap") if index%2==0 else ("swap","keep")):
            case=f"{namespace}-actorfit-{index:02d}-{action}"
            logp,_,receipt=runner.complete(model=model,checkpoint=checkpoint,event_directory=directory,
                seed=seed+index,route="stochastic",actor=reference,output=output,case=case,intervention=action)
            del logp
            receipt.update(phase="actor_training",source_ordinal=index,current_parameter_sha256=parameter_hash(model))
            save(output/case/"EPISODE.json",receipt);rows.append(receipt)
    actor,report=fit_actor(rows,runner.profile,steps=400,learning_rate=.03)
    save(output/"ACTOR.json",actor.to_dict());save(output/"ACTOR_FIT.json",report)
    save(output/"REPLAY_SCHEDULE.json",{"protocol_sha256":digest(protocol),"rows_sha256":digest(rows),
         "steps":[{"case":r["event_id"],"seed":r["actual_seed"],"source_id":r["source_id"],"action":r["selected_action"]} for r in rows]})
    for row in rows:
        release_training_media(output/row["event_id"],row,row["source_ordinal"] in (0,15))
    return actor,report,rows


def train_arm(*, runner, warmstart, actor, source_rows, output, seed, resume=False):
    started,cpu_start=time.monotonic(),cpu_seconds()
    output=Path(output)
    if not resume:output.mkdir(parents=True,exist_ok=False)
    model,initial_state=load_checkpoint(warmstart)
    model.eval().requires_grad_(True)
    spec=STUDY["actual_training"]
    protocol={"schema":"hepta.closure.actual-natural-gradient.v1","profile_sha256":runner.profile.digest,
              "source_protocol_sha256":runner.judge.bindings["source_protocol_sha256"],"seed":seed,
              "warmstart_file_sha256":hashlib.sha256(Path(warmstart).read_bytes()).hexdigest(),
              "warmstart_parameter_sha256":initial_state["parameter_sha256"],"actor_sha256":actor.digest,
              "specification":spec,"implementation_sha256":{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in runner.paths},
              "source_ids":[event["source_id"] for _,event in source_rows],
              "episode_positions":"two sequential complete episodes for one uniformly sampled source; same positional law used in calibration/qualification",
              "retention":STUDY["training_artifact_retention"]}
    if resume:
        if json.loads((output/"PROTOCOL.json").read_text())!=protocol:raise ValueError("Training resume identity changed")
    else:save(output/"PROTOCOL.json",protocol);save(output/"ACTOR.json",actor.to_dict())
    protocol_sha=digest(protocol)
    optimizer=torch.optim.AdamW(model.parameters(),lr=spec["optimizer_lr"],weight_decay=0.)
    sampler=torch.Generator().manual_seed(seed+401)
    initial_hashes={name:parameter_hash(module) for name,module in model.components().items()}
    log,baseline,start_step=[],0.,0
    if resume:
        state=torch.load(output/"RECOVERY.pt",map_location="cpu",weights_only=True)
        if state["protocol_sha256"]!=protocol_sha:raise ValueError("Actual recovery protocol changed")
        model.load_state_dict(state["model"],strict=True);optimizer.load_state_dict(state["optimizer"])
        sampler.set_state(state["sampler_rng"]);torch.set_rng_state(state["global_rng"])
        log,baseline,start_step=state["log"],state["baseline"],state["step"]
        if parameter_hash(model)!=state["parameter_sha256"]:raise ValueError("Recovered actual parameter identity changed")
    invocation=len(list(output.glob("INVOCATION-*.json")))
    save(output/f"INVOCATION-{invocation:03d}.json",{"resume_from_step":start_step,"protocol_sha256":protocol_sha,
         "history_baseline":baseline,"note":"any incomplete earlier invocation remains preserved as resource evidence"})
    namespace=hashlib.sha256((str(output.resolve())+runner.profile.digest).encode()).hexdigest()[:16]
    active=output/"ACTIVE.pt"
    active_identity=write_checkpoint(active,model,initial_state,runner.profile,protocol_sha,start_step)
    parameters=list(model.parameters())
    for step in range(start_step+1,spec["updates_per_arm"]+1):
        sampler_before=tree_hash(sampler.get_state());source_index=int(torch.randint(len(source_rows),(1,),generator=sampler))
        directory,event=source_rows[source_index]
        parameter_before=parameter_hash(model);optimizer_before=tree_hash(optimizer.state_dict())
        joint_score_gradient=[torch.zeros_like(p) for p in parameters]
        moments,receipts,score_jobs=[],[],[]
        for draw in range(2):
            actual_seed=seed*1000000+step*4+draw
            case=f"{namespace}-inv{invocation}-{step:03d}-{draw}"
            pending,value,receipt=runner.complete(model=model,checkpoint=active,event_directory=directory,
                seed=actual_seed,route="stochastic",actor=actor,output=output,case=case,training_score=True)
            score_jobs.append(pending)
            moments.append(moment_cost(value,runner.profile.gamma))
            receipt.update(phase="actual_generator_training",training_seed=seed,update_step=step,draw_index=draw,
                           current_parameter_sha256=parameter_before,current_checkpoint_sha256=active_identity["sha256"],
                           optimizer_before_sha256=optimizer_before,
                           actor_parameter_path="frozen context maps and registered physical samples only; no unsampled current logits",
                           timing_gradient_status="conditional-exogenous residual timing assumption; complete actual net return weights the score")
            save(output/case/"PHYSICAL_EPISODE.json",receipt);receipts.append(receipt)
        # Do not insert optimizer replay/backward between the two real episodes:
        # their actual sequential deployment workload must match qualification.
        for pending,receipt in zip(score_jobs,receipts):
            logp=pending.evaluate();backward_started=cpu_seconds()
            if isinstance(logp,torch.Tensor) and logp.requires_grad:
                gradient=torch.autograd.grad(logp,parameters,allow_unused=True)
                for total,part in zip(joint_score_gradient,gradient):
                    if part is not None:total.add_(part.detach())
                del gradient
            elif receipt["samples"]:
                raise ValueError("Executed stochastic draws lost their differentiable normalized score")
            receipt["training_score_backward_cpu_seconds"]=cpu_seconds()-backward_started
            save(output/receipt["event_id"]/"EPISODE.json",receipt)
            del logp
        target=sum(moments)/2;coefficient=target-baseline
        optimizer.zero_grad(set_to_none=True)
        for parameter,gradient in zip(parameters,joint_score_gradient):parameter.grad=gradient*coefficient
        component_norms={name:math.sqrt(sum(float(p.grad.double().square().sum()) for p in module.parameters() if p.grad is not None))
                         for name,module in model.components().items()}
        norm=torch.nn.utils.clip_grad_norm_(parameters,spec["gradient_clip"])
        if not torch.isfinite(norm):raise ValueError("Nonfinite actual-output gradient invalidates the run")
        optimizer.step()
        baseline_before=baseline;baseline=.9*baseline+.1*target
        item={"step":step,"source_id":event["source_id"],"source_index":source_index,
              "sampler_before_sha256":sampler_before,"sampler_after_sha256":tree_hash(sampler.get_state()),
              "cases":[r["event_id"] for r in receipts],"complete_net_returns":[r["net_return"] for r in receipts],
              "actual_moment_costs":moments,"joint_batch_target":target,"predictable_baseline_before_batch":baseline_before,
              "baseline_after_consumption":baseline,"joint_score_multiplier":coefficient,
              "raw_joint_gradient_norm":float(norm),"component_raw_gradient_norms":component_norms,
              "parameter_before_sha256":parameter_before,"parameter_after_sha256":parameter_hash(model),
              "optimizer_before_sha256":optimizer_before,"optimizer_after_sha256":tree_hash(optimizer.state_dict()),
              "actual_episode_cpu_seconds":sum(r["cpu_seconds"] for r in receipts),
              "optimizer_replay_cpu_seconds":sum(r["training_score_replay"]["cpu_seconds_outside_episode"] for r in receipts),
              "score_backward_cpu_seconds":sum(r["training_score_backward_cpu_seconds"] for r in receipts)}
        save(output/f"UPDATE-{step:03d}-inv{invocation}.json",item);log.append(item)
        active_identity=write_checkpoint(active,model,initial_state,runner.profile,protocol_sha,step)
        recovery={"schema":"hepta.closure.actual-natural-recovery.v1","protocol_sha256":protocol_sha,
                  "model":model.state_dict(),"optimizer":optimizer.state_dict(),"sampler_rng":sampler.get_state(),
                  "global_rng":torch.get_rng_state(),"baseline":baseline,"step":step,"log":log,
                  "parameter_sha256":parameter_hash(model)}
        temporary=output/"RECOVERY.pending";torch.save(recovery,temporary);temporary.replace(output/"RECOVERY.pt")
        for receipt in receipts:release_training_media(output/receipt["event_id"],receipt,step in (1,spec["updates_per_arm"]))
        del joint_score_gradient,receipts,score_jobs,pending
        if step%8==0:print(json.dumps({"phase":"actual_training","seed":seed,"gamma":runner.profile.gamma,
            "step":step,"batch_moment_cost":target,"raw_gradient_norm":float(norm)}),flush=True)
    final=write_checkpoint(output/"FINAL.pt",model,initial_state,runner.profile,protocol_sha,spec["updates_per_arm"])
    result={"schema":"hepta.closure.actual-natural-training-result.v1","profile_sha256":runner.profile.digest,
            "protocol_sha256":protocol_sha,"training_seed":seed,"updates":spec["updates_per_arm"],
            "complete_episodes_consumed_by_committed_updates":2*spec["updates_per_arm"],
            "actual_source_count_used_in_updates":len({row["source_id"] for row in log}),
            "all_completed_physical_episode_records":len(list(output.glob("*/PHYSICAL_EPISODE.json"))),"final_checkpoint":final,
            "components_changed":{name:parameter_hash(module)!=initial_hashes[name] for name,module in model.components().items()},
            "components_with_nonzero_actual_gradient":{name:any(row["component_raw_gradient_norms"][name]>0 for row in log) for name in initial_hashes},
            "actual_episode_CPU_seconds":sum(row["actual_episode_cpu_seconds"] for row in log),
            "optimizer_replay_CPU_seconds":sum(row["optimizer_replay_cpu_seconds"] for row in log),
            "score_backward_CPU_seconds":sum(row["score_backward_cpu_seconds"] for row in log),
            "cpu_seconds_this_invocation":cpu_seconds()-cpu_start,"wall_seconds_this_invocation":time.monotonic()-started,
            "updates_resumed_from":start_step,"training_seeds_are_separate_experiments":True,
            "strict_future_moment_certificate":False,"all_original_training_media_later_reread_claimed":False}
    save(output/"TRAINING_RESULT.json",result)
    return final,result
