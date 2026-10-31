"""Independent full effect/clock/cost replay of the frozen finite-boundary study."""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy.stats import t

from ..task_value_factorial_20261030.task import ContentAdapter
from ..value_boundary_v2_20261031.model import Contract
from .independent_checks import envelope, independent_hit, posterior, valid
from .teacher_confirmation_audit import close, digest, interval, read, verify_files


POLICIES=("fixed_analytic","direct_hard_analytic","direct_soft_analytic","qvi_analytic","qvi_ordinary")
NAMES=("STOP","READ","FIRE")


def replay(result,episode,contract,states,probabilities,templates,decoder_outputs,cdf_cache,policy_key):
    folder=Path(episode["folder"])
    public,clocks=read(folder/"public.json"),read(folder/"private_clocks.json")
    labels=read(folder/"evaluator_labels.json")["labels"]
    if digest(folder/"public.json")!=result["public_sha256"] or digest(folder/"private_clocks.json")!=result["clocks_sha256"]:
        raise AssertionError("Public/clock tape identity changed")
    if result["failure"] is not None:raise AssertionError("Confirmed execution failure")
    lookup={state:i for i,state in enumerate(states)}
    j,b,m,index=0,contract.budget,0,0
    elapsed=query=fire_charge=0.
    terminal=False
    answers=[]
    counts=dict.fromkeys(("READ","FIRE","STOP","deadline","recovery_phases","decoder_calls","payload_bytes",
        "failed_reads","support_check_reads","support_check_bytes","READ_attempts","censored_reads","successful_decoder_calls"),0)
    rng=np.random.default_rng(result["policy_rng_seed"])
    cdf_error=logit_error=0.
    semantic=[]
    def waiting(duration,phase):
        nonlocal elapsed,terminal
        remaining=max(0.,clocks["deadline"]-elapsed)
        actual=min(duration,remaining)
        elapsed+=actual
        hit=duration>=remaining
        if hit:terminal=True;counts["deadline"]+=1
        return dict(phase=phase,duration=actual,censored=hit,elapsed=elapsed)
    for trace,event in zip(result["decision_trace"],result["events"],strict=True):
        if terminal:raise AssertionError("Post-terminal physical event")
        state=(j,b,m)
        if trace["state"]!=list(state) or event["before"]!=list(state):raise AssertionError("Physical state mismatch")
        action=int(rng.choice(3,p=probabilities[lookup[state]])) if result["randomized_policy"] else int(np.argmax(probabilities[lookup[state]]))
        if not valid(contract,state)[action] or NAMES[action]!=trace["action"] or NAMES[action]!=event["action"]:
            raise AssertionError("Frozen boundary action or quality/budget guard mismatch")
        close(event["started_at"],elapsed)
        if result["mode"]=="analytic_boundary":
            key=(policy_key,state)
            if key not in cdf_cache:cdf_cache[key]=independent_hit(contract,states,probabilities,state,1/contract.deadline_rate)
            cdf_error=max(cdf_error,abs(cdf_cache[key]-trace["first_fire"]["probability"]))
            close(trace["first_fire"]["probability"],cdf_cache[key],2e-11)
        normalized=dict(action=NAMES[action],before=state)
        if action==0:terminal=True;counts["STOP"]+=1
        elif action==1:
            counts["READ_attempts"]+=1
            wait=waiting(clocks["read_waits"][j][index],"READ")
            if wait!=event["wait"]:raise AssertionError("READ competing-clock result differs")
            if terminal:counts["censored_reads"]+=1
            else:
                name=public["packets"][j][index]
                path=folder/name
                body=read(path)
                decoded=event["decoded"]
                if name!=event["packet"] or digest(path)!=decoded["payload_sha256"] or path.stat().st_size!=decoded["payload_bytes"]:
                    raise AssertionError("Actual packet identity mismatch")
                template=templates[body["template_id"]]
                if any(body[key]!=template[key] for key in ("schema","symbols","dt")):
                    raise AssertionError("Actual input left exhaustively decoded support")
                reference=decoder_outputs[body["template_id"]]
                if reference["observation"]!=decoded["observation"]:raise AssertionError("Actual finite-support decoder output changed")
                logit_error=max(logit_error,float(np.max(np.abs(np.asarray(reference["logits"])-decoded["logits"]))))
                close(reference["logits"],decoded["logits"],2e-6)
                for count in ("READ","decoder_calls","successful_decoder_calls","support_check_reads"):counts[count]+=1
                for count in ("payload_bytes","support_check_bytes"):counts[count]+=path.stat().st_size
                query+=contract.query_cost[j]
                m+=2*decoded["observation"]-1;b-=1;index+=1
                normalized.update(packet_sha256=decoded["payload_sha256"],observation=decoded["observation"])
        else:
            answer=dict(job=j,prediction=int(m>=0),posterior=posterior(contract,j,m),evidence=m)
            if any(answer[k]!=event["answer"][k] for k in ("job","prediction","evidence")):
                raise AssertionError("Submitted answer differs")
            close(answer["posterior"],event["answer"]["posterior"])
            answers.append(answer);fire_charge+=contract.fire_cost;counts["FIRE"]+=1
            j+=1;m=0;index=0
            recovery=[]
            if j==len(contract.reliability):terminal=True
            else:
                for phase,duration in enumerate(clocks["recovery_waits"][j-1]):
                    recovery.append(waiting(duration,f"RECOVERY_{phase}"))
                    if terminal:break
                    counts["recovery_phases"]+=1
            if recovery!=event["recovery"]:raise AssertionError("Recovery/deadline competition differs")
        if event["after"]!=[j,b,m] or event["terminal"]!=terminal:raise AssertionError("Actual successor differs")
        close(event["elapsed"],elapsed)
        normalized.update(after=(j,b,m),elapsed=elapsed,terminal=terminal)
        semantic.append(normalized)
    if not terminal:raise AssertionError("Score before termination")
    correct=sum(labels[a["job"]]==a["prediction"] for a in answers)
    reward=2*correct-len(answers)
    score=dict(reward=reward,utility=reward-query-fire_charge-contract.time_cost*elapsed,query_charge=query,
               time_charge=contract.time_cost*elapsed,fire_charge=fire_charge,completed_jobs=len(answers),correct_jobs=correct)
    for key,value in score.items():close(value,result["score"][key])
    if counts!=result["counts"]:raise AssertionError(("Count mismatch",counts,result["counts"]))
    close(elapsed,result["task_elapsed"])
    components=result["components"]
    covered=sum(components[k] for k in ("owner_setup_cpu_seconds","cdf_cpu_seconds","decoder_cpu_seconds","support_check_cpu_seconds"))
    if covered>result["cpu_seconds"]+1e-7:raise AssertionError("Nested disjoint CPU exceeds enclosing policy timer")
    return dict(semantic=semantic,score=score,counts=counts,decisions=len(semantic),cdf_error=cdf_error,logit_error=logit_error)


def compare_interval(values,expected):
    own=interval(values)
    if expected["n"]!=len(values):raise AssertionError("Statistical unit count differs")
    close([own["mean"],own["se"],own["lower"],own["upper"]],
          [expected["mean"],expected["standard_error"],*expected["confidence_interval"]])
    return own


def aggregate(strata,expected):
    k=len(strata)
    mean=sum(x["mean"] for x in strata)/k
    variances=[x["se"]**2/k**2 for x in strata]
    variance=sum(variances)
    denominator=sum(v*v/(len(x["values"])-1) for v,x in zip(variances,strata))
    degrees=variance*variance/denominator if denominator else None
    radius=float(t.isf(.025,degrees)*math.sqrt(variance)) if degrees else 0.
    close([mean,math.sqrt(variance),mean-radius,mean+radius],
          [expected["mean"],expected["standard_error"],*expected["confidence_interval"]])
    return dict(mean=mean,standard_error=math.sqrt(variance),degrees_of_freedom=degrees,
                confidence_interval=[mean-radius,mean+radius],contract_count=k)


def audit(prepared,confirmed,process,out):
    wall,cpu=time.perf_counter(),time.process_time()
    bundle=read(prepared/"PREPARED.json.gz")
    protocol=bundle["protocol"]
    summary=read(confirmed/"SUMMARY.json")
    manifest=read(confirmed/"EVIDENCE_MANIFEST.json")
    files=verify_files(confirmed,manifest,"artifacts")
    prep_manifest=read(prepared/"FREEZE_MANIFEST.json")
    prep_files=verify_files(prepared,prep_manifest,"artifacts")
    adapter=ContentAdapter()
    templates,decoder_outputs={},{}
    for index in range(8):
        path=confirmed/f"finite_support/support_{index}.json"
        templates[index]=read(path);decoder_outputs[index]=adapter.read(path)
    seen=set();check_count=decisions=reads=payload_bytes=cdf_checks=0
    max_cdf=max_logits=0.
    total_policy_cpu=0.
    pair_count=0
    per_contract=[]
    for c,record in enumerate(bundle["contracts"]):
        contract=Contract(**record["contract"])
        states=envelope(contract)
        cdf_cache={}
        differences=defaultdict(list);cluster=defaultdict(list);net=defaultdict(list);net_cluster=defaultdict(list)
        metrics=defaultdict(list)
        for f,fit in enumerate(record["fits"]):
            raw=read(confirmed/f"contract{c}_fit{f}_RAW.json.gz")
            def io_cost(descriptor):
                return descriptor["serialization_cpu_seconds"]+descriptor["prepare_load_validation"]["cpu_seconds"]
            timing=record["timing"]
            common=timing["model"]["cpu_seconds"]
            fixed_cost=common+timing["fixed"]["cpu_seconds"]+io_cost(record["deployment_artifacts"]["fixed"])
            qvi_cost=common+timing["qvi"]["cpu_seconds"]+timing["qvi_certificate"]["cpu_seconds"]+io_cost(record["deployment_artifacts"]["qvi"])
            direct_cost=fit["cpu_seconds"]+fit["additional_certificate_timing"]["cpu_seconds"]+sum(io_cost(x) for x in fit["deployment_artifacts"].values())
            independent_preparation=dict(fixed_analytic=fixed_cost,qvi_analytic=qvi_cost,qvi_ordinary=qvi_cost,
                direct_hard_analytic=direct_cost,direct_soft_analytic=direct_cost)
            for name,base_cost in independent_preparation.items():
                close(base_cost+raw["expected"]["deployment_load_receipts"][name]["cpu_seconds"],
                      raw["expected"]["preparation_cpu"][name])
            probabilities={p:np.eye(3)[record["fixed_actions"] if p=="fixed_analytic" else
                fit["hard_actions"] if p=="direct_hard_analytic" else record["qvi_actions"]]
                for p in POLICIES if p!="direct_soft_analytic"}
            probabilities["direct_soft_analytic"]=np.asarray(fit["probabilities"])
            local=defaultdict(list);local_net=defaultdict(list)
            if len(raw["episodes"])!=128:raise AssertionError("Incomplete frozen fit block")
            for row in raw["episodes"]:
                episode=row["episode"]
                if episode["id"] in seen:raise AssertionError("Repeated episode across fit/contract strata")
                seen.add(episode["id"])
                seed=protocol["episode_seed_base"]+c*protocol["contract_seed_stride"]+f*protocol["fit_seed_stride"]+len(local.get("seed_check",[]))
                local["seed_check"].append(episode["seed"])
                if episode["seed"]!=seed:raise AssertionError("Episode RNG namespace changed")
                replays={}
                for name,result in row["results"].items():
                    if name not in POLICIES:raise AssertionError("Undeclared policy")
                    checked=replay(result,episode,contract,states,probabilities[name],templates,decoder_outputs,cdf_cache,(c,f,name))
                    replays[name]=checked
                    check_count+=1;decisions+=checked["decisions"];reads+=checked["counts"]["READ"];payload_bytes+=checked["counts"]["payload_bytes"]
                    cdf_checks+=len(result["decision_trace"]) if result["mode"]=="analytic_boundary" else 0
                    max_cdf=max(max_cdf,checked["cdf_error"]);max_logits=max(max_logits,checked["logit_error"])
                    total_policy_cpu+=result["cpu_seconds"]
                    metrics[name].append(dict(utility=result["score"]["utility"],correct_fraction=result["score"]["correct_jobs"]/2,
                        error_fraction=(result["score"]["completed_jobs"]-result["score"]["correct_jobs"])/2,
                        completion_fraction=result["score"]["completed_jobs"]/2,cpu_seconds=result["cpu_seconds"]))
                if replays["qvi_analytic"]["semantic"]!=replays["qvi_ordinary"]["semantic"] or replays["qvi_analytic"]["score"]!=replays["qvi_ordinary"]["score"]:
                    raise AssertionError("Same-policy analytic/ordinary physical null failed")
                pair_count+=1
                for contrast in protocol["primary_comparisons"]+protocol["secondary_comparisons"]:
                    left,right=contrast.split("-minus-")
                    effects=row["results"]
                    delta=effects[left]["score"]["utility"]-effects[right]["score"]["utility"]
                    differences[contrast].append(delta);local[contrast].append(delta)
                    if contrast in protocol["primary_comparisons"]:
                        setup=raw["expected"]["preparation_cpu"][left]-raw["expected"]["preparation_cpu"][right]
                        cost=effects[left]["cpu_seconds"]-effects[right]["cpu_seconds"]
                        for kappa in protocol["cpu_accounting"]["kappa_sensitivity"]:
                            for horizon in protocol["cpu_accounting"]["deployment_sessions_sensitivity"]:
                                key=(contrast,f"kappa={kappa:g};H={horizon}")
                                value=delta-kappa*(cost+setup/horizon)
                                net[key].append(value);local_net[key].append(value)
            for contrast,values in local.items():
                if contrast!="seed_check":cluster[contrast].append(float(np.mean(values)))
            for key,values in local_net.items():net_cluster[key].append(float(np.mean(values)))
        expected=summary["reports"][c]
        audited=dict(name=record["name"],comparison={},net={},metrics={})
        for contrast,values in differences.items():
            audited["comparison"][contrast]=dict(conditional_episode=compare_interval(values,expected["comparisons"][contrast]["conditional_episode"]),
                fit_cluster=compare_interval(cluster[contrast],expected["comparisons"][contrast]["fit_cluster"]))
        for key,values in net.items():
            contrast,scenario=key
            audited["net"].setdefault(contrast,{})[scenario]=dict(conditional_episode=compare_interval(values,expected["net_comparisons"][contrast][scenario]["conditional_episode"]),
                fit_cluster=compare_interval(net_cluster[key],expected["net_comparisons"][contrast][scenario]["fit_cluster"]))
        for policy,rows in metrics.items():
            audited["metrics"][policy]={m:float(np.mean([r[m] for r in rows])) for m in rows[0]}
            for metric,value in audited["metrics"][policy].items():close(value,expected["sampled_means"][policy][metric])
        per_contract.append(audited)
    aggregates={};net_aggregates={}
    for contrast in protocol["primary_comparisons"]:
        aggregates[contrast]={kind:aggregate([x["comparison"][contrast][kind] for x in per_contract],summary["primary_equal_weight_aggregate"][contrast][kind])
                              for kind in ("conditional_episode","fit_cluster")}
        net_aggregates[contrast]={}
        for scenario in per_contract[0]["net"][contrast]:
            net_aggregates[contrast][scenario]={kind:aggregate([x["net"][contrast][scenario][kind] for x in per_contract],summary["net_equal_weight_aggregate"][contrast][scenario][kind])
                for kind in ("conditional_episode","fit_cluster")}
    if len(seen)!=5120 or check_count!=25600 or not summary["qualified"] or summary["main_enrollment"]:
        raise AssertionError("Coverage or declared qualification mismatch")
    outer=read(process);stage=read(confirmed/"CONFIRM_STAGE_RECEIPT.json")
    if outer["returncode"] or outer["total_cpu_seconds"]<stage["cpu_seconds"] or stage["cpu_seconds"]<total_policy_cpu:
        raise AssertionError("Invalid enclosing cost accounting")
    report=dict(schema="hcsn.progression.value-confirmation-audit.v1",passed=True,source_sha256=digest(Path(__file__)),
        confirmation_artifacts=files,preparation_artifacts=prep_files,episodes=len(seen),rollouts=check_count,
        decisions=decisions,actual_reads=reads,payload_bytes=payload_bytes,exhaustive_decoder_support_reexecutions=8,
        first_fire_cdf_checks=cdf_checks,maximum_first_fire_error=max_cdf,maximum_decoder_logit_error=max_logits,
        same_policy_ordinary_analytic_pairs=pair_count,all_physical_nulls_equal=True,
        per_contract=per_contract,aggregates=aggregates,net_aggregates=net_aggregates,
        complete_cost=dict(enclosing_policy_cpu=total_policy_cpu,confirmation_stage_cpu=stage["cpu_seconds"],process_lifetime_cpu=outer["total_cpu_seconds"],
            rule="Nested components are not added to enclosing CPU; per-policy preparation plus actual deployment load amortized once"),
        main_activation=False,independent_analytic_gain=False,audit_cpu_seconds=time.process_time()-cpu,audit_wall_seconds=time.perf_counter()-wall)
    with out.open("x") as stream:json.dump(report,stream,indent=2,allow_nan=False)
    print(json.dumps({k:v for k,v in report.items() if k not in ("per_contract","aggregates","net_aggregates")}))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("prepared","confirmed","process","out"):parser.add_argument("--"+name,type=Path,required=True)
    audit(**vars(parser.parse_args()))
