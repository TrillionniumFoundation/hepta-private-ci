"""Post-freeze independent task, actual decoder, policy and statistical replay.

Only new audit output is written. No candidate training, protocol or source is
changed. Statistical summaries are recomputed from paired RAW episodes, not by
calling the candidate confirmation.analyze or execution.diagnose functions.
"""
import argparse
from functools import lru_cache
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy.stats import t

from ..task_value_factorial_20261030.task import ContentAdapter
from .independent_checks import independent_one_read


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ACTIONS = ("STOP","SKIP","READ","FIRE")
Q = 2**24


def read(path):
    raw = Path(path).read_bytes()
    return json.loads(gzip.decompress(raw) if str(path).endswith(".gz") else raw)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def close(left,right,tolerance=2e-11):
    if not np.allclose(left,right,atol=tolerance,rtol=0):
        raise AssertionError(("numerical mismatch",left,right))


def true_finite_teacher(meta,confusion,multiplier,latency):
    deadline = meta["deadline"]
    @lru_cache(None)
    def values(j,k,b,p):
        return max(qvalues(j,k,b,p))
    @lru_cache(None)
    def qvalues(j,k,b,p):
        q = [0.,-float("inf"),-float("inf"),-float("inf")]
        if j>=2 or k>=deadline:return tuple(q)
        if k+1<deadline:
            q[1] = values(j,k+1,b,p)-latency*meta["duration"][k]
            if b:
                r = meta["reliability"][j][k]
                channel = r*confusion+(1-r)*confusion[::-1]
                probabilities = (1-p)*channel[0]+p*channel[1]
                posteriors = p*channel[1]/probabilities
                q[2] = sum(probabilities[o]*values(j,k+1,b-1,float(posteriors[o])) for o in (0,1))
                q[2] -= multiplier*meta["price"][j][k]+latency*meta["duration"][k]
        q[3] = abs(2*p-1)+values(j+1,k+2,b,.5)-latency*sum(meta["duration"][k:min(k+2,deadline)])
        return tuple(q)
    return qvalues


def structured_features(meta,confusion,multiplier,latency,state,prior):
    j,k,b,p = state
    remaining = meta["deadline"]-k
    reliability,price,duration = np.zeros((2,10)),np.zeros((2,10)),np.zeros(10)
    reliability[:2-j,:remaining] = np.asarray(meta["reliability"])[j:,k:]
    price[:2-j,:remaining] = multiplier*np.asarray(meta["price"])[j:,k:]
    duration[:remaining] = latency*np.asarray(meta["duration"])[k:]
    canonical = confusion if p>=.5 else confusion[::-1,::-1]
    return np.r_[j,remaining/10,b/4,max(p,1-p),abs(2*p-1),canonical.flatten(),multiplier,latency,
                 reliability.flatten(),price.flatten(),duration,np.where(np.isfinite(prior),prior,0.)]


def quantize(x):
    x = np.asarray(x,float)
    return np.sign(x)*np.floor(np.abs(x)*Q+.5)/Q


def interval(values):
    x = np.asarray(values,float)
    se = float(np.std(x,ddof=1)/np.sqrt(x.size))
    mean = float(np.mean(x))
    radius = float(t.isf(.025,x.size-1))*se
    p = float(2*t.sf(abs(mean)/se,x.size-1)) if se else (1. if mean==0 else 0.)
    return dict(mean=mean,lower=mean-radius,upper=mean+radius,se=se,p=p,values=x.tolist())


def verify_files(folder,manifest,key):
    failed = [name for name,expected in manifest[key].items() if digest(folder/name)!=expected]
    if failed:raise AssertionError(("artifact identity mismatch",failed[:5]))
    return len(manifest[key])


def replay_row(row,folder,meta,labels,confusion,protocol,model,teacher,adapter,decoded):
    multiplier,latency = protocol["multiplier"],protocol["latency_price"]
    j,k,b,p = 0,0,meta["budget"],.5
    query,time_charge,elapsed = 0.,0.,0.
    actions = dict.fromkeys(ACTIONS,0)
    answers,bytes_read,regrets,reads_in_job = [],0,[],0
    terminal = False
    maximum_q_error,maximum_logit_error = 0.,0.
    for trace in row["traces"]:
        if terminal:raise AssertionError("Post-terminal execution")
        state = (j,k,b,p)
        close(trace["state"],state)
        legal = np.array([True,k+1<meta["deadline"],b>0 and k+1<meta["deadline"],True])
        if not np.array_equal(legal,trace["feasible"]):raise AssertionError("Guard mismatch")
        exact = np.asarray(teacher(*state))
        prior = exact if row["policy"]=="exact_teacher" else independent_one_read(meta,confusion,multiplier,latency,state)
        close(np.where(legal,prior,0.),trace["prior"])
        scores = prior.copy()
        if row["policy"]=="nonzero_residual":
            raw = structured_features(meta,confusion,multiplier,latency,state,prior)
            close(raw,trace["features"])
            x = np.clip((quantize(raw)-model["norm"]["mean"])/model["norm"]["scale"],-8.,8.)
            weights = model["weights"]
            scores = quantize(np.where(legal,prior,0.))+np.maximum(0.,np.tanh(x@weights["w"]+weights["b"])@weights["v"]+weights["c"])
            scores[0] = 0.
        recorded = np.asarray(trace["q"])
        maximum_q_error = max(maximum_q_error,float(np.max(np.abs(recorded[legal]-scores[legal]))))
        close(recorded[legal],scores[legal])
        drive = np.zeros(5,dtype=np.int64)
        drive[:4][legal] = np.floor((scores[legal]+4)*Q+.5).astype(np.int64)
        if not np.array_equal(drive,trace["drive"]):raise AssertionError("Q24 drive differs")
        action = int(np.argmax(drive))
        if action!=trace["action"]:raise AssertionError("Deployed action differs")
        regrets.append(float(max(exact)-exact[action]))
        event = trace["event"]
        if event["action"]!=ACTIONS[action] or event["job"]!=j or event["tick"]!=k:
            raise AssertionError("Action receipt mismatch")
        close(event["posterior_before"],p)
        if event["budget_before"]!=b:raise AssertionError("Budget receipt mismatch")
        duration = 0. if action==0 else sum(meta["duration"][k:min(k+(2 if action==3 else 1),meta["deadline"])])
        elapsed += duration
        time_charge += latency*duration
        actions[ACTIONS[action]] += 1
        if action==0:terminal=True
        elif action==1:k+=1
        elif action==2:
            path = folder/meta["packets"][j][k]
            sha = digest(path)
            if sha!=event["payload_sha256"] or path.stat().st_size!=event["payload_bytes"]:
                raise AssertionError("Actual READ payload identity differs")
            if sha not in decoded:decoded[sha]=adapter.read(path)
            observation = decoded[sha]["observation"]
            if observation!=event["observation"]:raise AssertionError("Actual decoder observation differs")
            maximum_logit_error = max(maximum_logit_error,float(np.max(np.abs(np.asarray(decoded[sha]["logits"])-event["logits"]))))
            close(decoded[sha]["logits"],event["logits"],2e-6)
            bytes_read += path.stat().st_size
            r = meta["reliability"][j][k]
            law = r*confusion+(1-r)*confusion[::-1]
            p = float(p*law[1,observation]/((1-p)*law[0,observation]+p*law[1,observation]))
            query += multiplier*meta["price"][j][k]
            b-=1;k+=1;reads_in_job+=1
        else:
            answer = dict(job=j,prediction=int(p>=.5),posterior=p,tick=k,reads=reads_in_job)
            if answer!=event["answer"]:raise AssertionError("FIRE answer differs")
            answers.append(answer);j+=1;k+=2;p=.5;reads_in_job=0
        terminal = terminal or j>=2 or k>=meta["deadline"]
        if (event["budget_after"]!=b or event["next_job"]!=j or event["next_tick"]!=k or event["terminal"]!=terminal):
            raise AssertionError("Actual legal successor differs")
        close([event["posterior_after"],event["duration"],event["charged_cost"]],[p,duration,query+time_charge])
    if not terminal:raise AssertionError("Scored a nonterminal state")
    correct = sum(a["prediction"]==labels[a["job"]] for a in answers)
    reward = 2*correct-len(answers)
    score = row["score"]
    close([score[k] for k in ("utility","reward","charged_cost","query_cost","latency_cost","completed_jobs","correct_jobs")],
          [reward-query-time_charge,reward,query+time_charge,query,time_charge,len(answers),correct])
    for action,count in actions.items():
        if row["counts"][action]!=count:raise AssertionError("Action counts differ")
    for name in ("content_invocations","packet_file_reads"):
        if row["counts"][name]!=actions["READ"]:raise AssertionError("READ count differs")
    if row["counts"]["payload_bytes"]!=bytes_read or row["counts"]["failed_read_attempts"]:
        raise AssertionError("Failed or unmatched READ accounting")
    close(row["task_elapsed"],elapsed)
    close(row["teacher_regret"],sum(regrets))
    return dict(decisions=len(row["traces"]),reads=actions["READ"],bytes=bytes_read,
                q_error=maximum_q_error,logit_error=maximum_logit_error,regret=sum(regrets))


def audit(prepared,confirmed,process,out):
    wall,cpu = time.perf_counter(),time.process_time()
    protocol,prep_summary = read(prepared/"PROTOCOL.json"),read(prepared/"PREPARE_SUMMARY.json")
    result,manifest = read(confirmed/"CONFIRMATION.json"),read(confirmed/"CONFIRMATION_MANIFEST.json")
    artifact_count = verify_files(confirmed,manifest,"files")
    prepared_manifest = read(prepared/"PREPARED_MANIFEST.json")
    preparation_count = verify_files(prepared,prepared_manifest,"files")
    verify_files(ROOT,prepared_manifest,"source_sha256")
    adapter = ContentAdapter()
    decoded,keys,checks,seed_metrics = {},set(),[],{}
    cpu_rows,raw_persistence,diagnostic_cpu = 0.,0.,0.
    for seed in protocol["seeds"]:
        model = read(prepared/f"seed{seed}/model_nonzero.json")
        model["weights"] = {k:np.asarray(v) for k,v in model["weights"].items()}
        confusion = np.asarray(read(prepared/f"seed{seed}/PREPARE_SEED.json")["confusion"])
        for split in ("test","ood"):
            bundle = read(confirmed/f"seed{seed}/{split}_RUNS_AND_DIAGNOSIS.json.gz")
            cohort = read(confirmed/f"seed{seed}/{split}_COHORT.json.gz")
            folders = {x["id"]:Path(x["folder"]) for x in cohort["records"]}
            qteachers = {}
            sums = {}
            for row in bundle["rows"]:
                key = (seed,split,row["session_id"],row["policy"])
                if key in keys:raise AssertionError("Duplicate paired policy episode")
                keys.add(key)
                folder = folders[row["session_id"]]
                meta,labels = read(folder/"public.json"),read(folder/"evaluator_labels.json")["labels"]
                if digest(folder/"public.json")!=row["public_sha256"]:raise AssertionError("Public metadata identity changed")
                if row["session_id"] not in qteachers:
                    qteachers[row["session_id"]]=true_finite_teacher(meta,confusion,protocol["multiplier"],protocol["latency_price"])
                checks.append(replay_row(row,folder,meta,labels,confusion,protocol,model,qteachers[row["session_id"]],adapter,decoded))
                record = dict(utility=row["score"]["utility"],correct_fraction=row["score"]["correct_jobs"]/2,
                    wrong_fraction=(row["score"]["completed_jobs"]-row["score"]["correct_jobs"])/2,
                    completed_fraction=row["score"]["completed_jobs"]/2,teacher_regret=row["teacher_regret"],
                    full_cpu_seconds=row["cpu_seconds"]+row["raw_persistence_cpu_seconds"])
                sums.setdefault(row["policy"],[]).append(record)
                cpu_rows+=row["cpu_seconds"];raw_persistence+=row["raw_persistence_cpu_seconds"]
            if any(len(x)!=128 for x in sums.values()) or set(sums)!=set(protocol["policies"]):
                raise AssertionError("Incomplete confirmation stratum")
            seed_metrics[seed,split]={p:{m:float(np.mean([r[m] for r in rows])) for m in rows[0]} for p,rows in sums.items()}
            diagnostic_cpu+=bundle["diagnosis"]["cpu_seconds"]
    summaries = {}
    preps = {x["seed"]:x for x in prep_summary["seeds"]}
    reports = {x["seed"]:x for x in result["reports"]}
    for split in ("test","ood"):
        intervals = {}
        for metric in ("utility","correct_fraction","wrong_fraction","completed_fraction","teacher_regret","full_cpu_seconds"):
            values=[seed_metrics[seed,split]["nonzero_residual"][metric]-seed_metrics[seed,split]["one_read"][metric] for seed in protocol["seeds"]]
            intervals[metric]=interval(values)
            expected=result["splits"][split]["paired"][metric]
            close([intervals[metric][k] for k in ("mean","lower","upper")],[expected[k] for k in ("mean","lower","upper")])
        cpu_scenarios={}
        for horizon in protocol["amortization_sessions"]:
            for price in protocol["cpu_prices_utility_per_second"]:
                values=[]
                for seed in protocol["seeds"]:
                    a,b=(seed_metrics[seed,split][p] for p in ("nonzero_residual","one_read"))
                    training=preps[seed]["total_prepare_cpu_seconds"]-preps[seed]["common_prepare_cpu_seconds"]+reports[seed]["model_load_cpu_seconds"]
                    values.append(a["utility"]-b["utility"]-price*(a["full_cpu_seconds"]-b["full_cpu_seconds"]+training/horizon))
                key=f"H={horizon},CPU={price}"
                cpu_scenarios[key]=interval(values)
                expected=result["splits"][split]["cpu_sensitivity"][key]
                close([cpu_scenarios[key][k] for k in ("mean","lower","upper")],[expected[k] for k in ("mean","lower","upper")])
        summaries[split]=dict(intervals=intervals,cpu_scenarios=cpu_scenarios)
    ordered=sorted(summaries,key=lambda s:summaries[s]["intervals"]["utility"]["p"])
    previous=0.
    for i,split in enumerate(ordered):
        adjusted=min(1.,max(previous,(2-i)*summaries[split]["intervals"]["utility"]["p"]))
        summaries[split]["utility_holm_p"]=adjusted;previous=adjusted
        close(adjusted,result["splits"][split]["utility_holm_p"])
    primary=f"H={protocol['primary_amortization_sessions']},CPU={protocol['primary_cpu_price']}"
    gates=dict(all_nonzero_models_improve_validation_zero=all(x["nonzero_improves_zero"] for x in preps.values()),
        positive_utility_both_splits=all(x["intervals"]["utility"]["lower"]>0 and x["utility_holm_p"]<.05 for x in summaries.values()),
        quality_noninferior_both_splits=all(x["intervals"]["correct_fraction"]["lower"]>-.02 for x in summaries.values()),
        positive_full_cpu_adjusted_both_splits=all(x["cpu_scenarios"][primary]["lower"]>0 for x in summaries.values()))
    if gates!=result["gates"] or all(gates.values())!=result["task_level_learned_admission"]:
        raise AssertionError("Independent admission differs")
    outer=read(process)
    if outer["returncode"] or outer["total_cpu_seconds"]+1e-9<result["total_cpu_seconds"]:
        raise AssertionError("Invalid enclosing process accounting")
    report=dict(schema="hcsn.progression.teacher-confirmation-audit.v1",passed=True,
        source_sha256=digest(Path(__file__)),confirmation_artifacts=artifact_count,preparation_artifacts=preparation_count,
        episodes=len(keys),paired_sessions=len(keys)//3,decisions=sum(x["decisions"] for x in checks),
        reads=sum(x["reads"] for x in checks),payload_bytes=sum(x["bytes"] for x in checks),
        unique_actual_decoder_reexecutions=len(decoded),maximum_q_replay_error=max(x["q_error"] for x in checks),
        maximum_actual_decoder_logit_error=max(x["logit_error"] for x in checks),
        summaries=summaries,gates=gates,task_level_learned_admission=all(gates.values()),main_activation=False,
        accounting=dict(policy_cpu=cpu_rows,raw_persistence_cpu=raw_persistence,teacher_diagnostic_cpu=diagnostic_cpu,
            internal_confirmation_cpu=result["total_cpu_seconds"],process_lifetime_cpu=outer["total_cpu_seconds"],
            accounting_rule="Nested policy, persistence and diagnostics are not added to the enclosing process total; candidate preparation is amortized once, common setup cancels in paired net comparisons"),
        freeze=result["freeze"],audit_cpu_seconds=time.process_time()-cpu,audit_wall_seconds=time.perf_counter()-wall)
    with out.open("x") as stream:json.dump(report,stream,indent=2,allow_nan=False)
    print(json.dumps({k:v for k,v in report.items() if k not in ("summaries","freeze")}))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("prepared","confirmed","process","out"):parser.add_argument("--"+name,type=Path,required=True)
    audit(**vars(parser.parse_args()))
