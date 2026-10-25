"""Independent post-evaluation arithmetic audit of the frozen V5/V6 reports.

Consumes disclosed source statistics and strata, never ciphertext or keys. It
does not fit models, select policies, change cohorts, or authenticate labels.
No evaluation metric, bootstrap, or decision helper is imported from the scorer.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
from pathlib import Path
import sys
import time

import numpy as np


PROTOCOLS = {5:"654994abfb66e8872b0d6632b7d80d5058ad5af06adc2d2dea0de628395ba05e",
             6:"cdd777f64265acfd6b8e44960a4f3c3bfbd5d856f76bc7c9d9c696bf4e11f41f"}
MANIFESTS = {5:"4ae63c6bd5a16cd2057b8d8748047d8d3f092db8f02675e8e65ab4150ef7f526",
             6:"9d7948427f08d1ec619b5f3737231bd7922c01ad081c9ee08e56f3868acf9ea1"}
TASKS, HEADS, SEEDS, SPLITS = ("agnews","dbpedia"),("linear","gated"),(7,17,29),("current","future","old")
ROLES = {"current":"current_validation","future":"future_test","old":"old_test"}


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition,message):
    if not condition:
        raise ValueError(message)


def close(actual,expected,message):
    require(np.shape(actual)==np.shape(expected),"shape: "+message)
    error=float(np.max(np.abs(np.asarray(actual)-np.asarray(expected)),initial=0.))
    require(np.isfinite(error) and error<=1e-12,"arithmetic: "+message)
    return error


def index_rows(rows,fields,expected):
    result={tuple(row[k] for k in fields):row for row in rows}
    require(len(result)==len(rows) and set(result)==set(expected),"exact census: "+str(fields))
    return result


def component_draws(names,strata,rng,replicates=10000):
    """Explicit sorted component grouping plus integer-indexed stratum draws."""
    names,strata=np.asarray(names),np.asarray(strata)
    require(names.ndim==1 and names.dtype.kind in "US" and strata.shape==names.shape
        and strata.dtype.kind in "iu" and set(strata.tolist())=={0,1,2,3},"four aligned strata required")
    ordered=sorted(set(names.tolist()))
    lookup={name:i for i,name in enumerate(ordered)}
    inverse=np.asarray([lookup[name] for name in names])
    classes=[]
    for i in range(len(ordered)):
        labels=set(strata[inverse==i].tolist())
        require(len(labels)==1,"component crosses strata")
        classes.append(labels.pop())
    blocks=[]
    for label in range(4):
        members=np.asarray([i for i,c in enumerate(classes) if c==label])
        blocks.append(members[rng.integers(0,len(members),size=(replicates,len(members)))])
    return inverse,np.concatenate(blocks,axis=1)


def paired_interval(paired,inverse,samples):
    paired=np.asarray(paired,dtype=np.float64)
    require(paired.shape==(3,len(inverse)) and np.isfinite(paired).all(),"three complete paired seed rows required")
    delta=paired.mean(axis=0)
    groups=[np.flatnonzero(inverse==i) for i in range(int(inverse.max())+1)]
    totals=np.asarray([delta[group].sum() for group in groups])
    counts=np.asarray([len(group) for group in groups])
    statistics=totals[samples].sum(axis=1)/counts[samples].sum(axis=1)
    quantile=1-.05/12
    upper=float(np.sort(statistics)[math.ceil((len(statistics)-1)*quantile)])
    return {"difference":float(delta.mean()),"upper_bound":upper,
        "one_sided_quantile":quantile,"source_rows":len(delta),"source_components":len(groups),
        "replicates":len(samples),"paired_seed_mean_differences":paired.mean(axis=1).tolist()}


def numerical_gate(split,upper):
    return upper<-.001 if split=="future" else upper<=0.


def audit(evaluation_directory,run_directory,protocol_path,output):
    directory,run,protocol_path,output=map(Path,(evaluation_directory,run_directory,protocol_path,output))
    require(not output.exists() and not output.resolve().is_relative_to(run.resolve()),"new output outside sealed run required")
    began,cpu=time.perf_counter_ns(),time.process_time_ns()
    report={"schema":"hepta.independent-statistical-recomputation.v6","status":"failed","failures":[],
        "auditor_sha256":sha(__file__),"ciphertext_or_keys_opened":False,"production_authority":False,
        "scope":"frozen report arithmetic, source pairing, conditional bootstrap, completion/cost gates; disclosed strata/statistics, no model selection"}
    try:
        plan=read(protocol_path);version=int(plan["schema"].rsplit("v",1)[1]);p=plan["evaluation"]
        require(sha(protocol_path)==PROTOCOLS[version],"frozen original protocol")
        manifest=read(directory/"audit_inputs.json");evaluation=read(directory/"evaluation.json")
        require(sha(directory/"audit_inputs.json")==MANIFESTS[version]
            and manifest["protocol_sha256"]==PROTOCOLS[version]
            and manifest["evaluation_sha256"]==sha(directory/"evaluation.json")
            and manifest["pre_evaluation_seal_sha256"]==sha(run/"pre_evaluation_seal.json")
            and manifest["pre_label_audit_sha256"]==sha(directory/"pre_label_audit.json"),"audit input commitments")
        require(manifest["arrays_sha256"]==sha(directory/"audit_inputs.npz")
            and manifest["arrays_bytes"]==(directory/"audit_inputs.npz").stat().st_size,"source-statistic bytes")
        require(read(directory/"pre_label_audit.json")["all_replays_valid"] is True
            and evaluation["candidate"]==p["candidate"] and evaluation["registered_fits"]==12
            and evaluation["registered_policy_outputs"]==72 and manifest["metric_count"]==228
            and manifest["contrast_count"]==12 and manifest["cost_record_count"]==72,"declared complete audit census")
        with np.load(directory/"audit_inputs.npz",allow_pickle=False) as a:
            arrays={k:a[k] for k in a.files}
        require(p["tasks"]==list(TASKS) and p["heads"]==list(HEADS) and p["seeds"]==list(SEEDS)
            and p["splits"]==list(SPLITS) and p["bootstrap_seed"]==20261025
            and p["bootstrap_replicates"]==10000 and p["family_size"]==12
            and p["family_alpha"]==.05 and p["improvement_margin"]==.001
            and p["retention_margin"]==0 and p["max_cpu_ratio"]==3.,"registered statistics unchanged")
        for key,value in p.items():
            require(evaluation["bootstrap"][key]==value,"reported frozen rule: "+key)
        expected_roles=list(itertools.product(TASKS,SPLITS))
        roles=index_rows(manifest["source_roles"],("task","split"),expected_roles)
        expected_metrics=[(t,h,s,policy,split) for t,h,s in itertools.product(TASKS,HEADS,SEEDS)
            for policy in (*p["policies"],"warmup_old") for split in (("old",) if policy=="warmup_old" else SPLITS)]
        descriptions=index_rows(manifest["metric_rows"],("task","head","seed","policy","split"),expected_metrics)
        metrics=index_rows(evaluation["records"],("task","head","seed","policy","split"),expected_metrics)
        role_values,used,indices={},set(),{}
        for task,split in expected_roles:
            row=roles[task,split]
            names,classes=arrays[row["components_key"]],arrays[row["strata_key"]]
            source=[x for x in read(run/task/"inputs.json")["sources"] if x["role"]==ROLES[split]]
            require(names.tolist()==[x["component_id"] for x in source] and len(names)==row["rows"]
                ==plan["source_counts"][task][ROLES[split]],"source component order/count")
            require(not used.intersection(names.tolist()),"component appears across evaluation roles/tasks")
            used.update(names.tolist());role_values[task,split]=(names,classes)
            indices[task,split]=np.asarray([x["index"] for x in source])
        maximum_metric_error,losses=0.,{}
        prediction_cache={}
        for key in expected_metrics:
            task,head,seed,policy,split=key
            description,row=descriptions[key],metrics[key]
            cache_key=key[:4]
            fit=run/task/f"seed{seed}-{head}"
            if cache_key not in prediction_cache:
                path=fit/"warmup/warmup.npz" if policy=="warmup_old" else fit/"mpc"/policy/"trajectory.npz"
                with np.load(path,allow_pickle=False) as a:
                    prediction_cache[cache_key]=a["probabilities" if policy=="warmup_old" else "terminal_probabilities"]
            probabilities=prediction_cache[cache_key][indices[task,split]]
            classes=role_values[task,split][1]
            values={"nll":-np.log(np.maximum(probabilities[np.arange(len(classes)),classes],np.finfo(float).tiny)),
                "correct":(probabilities.argmax(axis=1)==classes).astype(float),
                "brier":np.square(probabilities-np.eye(4)[classes]).sum(axis=1)}
            for metric,value in values.items():
                maximum_metric_error=max(maximum_metric_error,close(value,arrays[description[metric+"_key"]],"export "+str(key)+metric))
            require(row["status"]=="completed" and row["rows"]==len(classes),"descriptive output availability")
            calculated={"nll":float(values["nll"].mean()),"accuracy":float(values["correct"].mean()),
                "balanced_accuracy":float(np.mean([values["correct"][classes==c].mean() for c in range(4)])),
                "brier":float(values["brier"].mean())}
            for name,value in calculated.items():
                maximum_metric_error=max(maximum_metric_error,close(value,row[name],"reported metric "+name))
            losses[key]=values["nll"]
        expected_costs=list(itertools.product(TASKS,HEADS,SEEDS,p["policies"]))
        costs=index_rows(manifest["cost_records"],("task","head","seed","policy"),expected_costs)
        recorded_costs=index_rows(evaluation["cost_records"],("task","head","seed","policy"),expected_costs)
        valid_costs=[]
        for key,record in costs.items():
            task,head,seed,policy=key;path=run/task/f"seed{seed}-{head}"/"mpc"/policy/"result.json"
            actual=read(path)
            require(sha(path)==record["result_sha256"],"timing source identity")
            for field in ("status","cpu_ns","wall_ns","registered_steps","completed_steps"):
                require(actual[field]==record[field]==recorded_costs[key][field],"actual cost/status field")
            require(record["valid_record"] is True and recorded_costs[key]["valid_record"] is True,"valid actual timing record")
            valid_costs.append(type(record["cpu_ns"]) is int and record["cpu_ns"]>0)
        required=list(itertools.product(TASKS,HEADS,SEEDS,p["required_completed_policies"]))
        completion=index_rows(evaluation["completion_gates"],("task","head","seed","policy"),required)
        eligibility={}
        for task,head in itertools.product(TASKS,HEADS):
            checks=[]
            for seed,policy in itertools.product(SEEDS,p["required_completed_policies"]):
                key=task,head,seed,policy;c=costs[key]
                complete=c["status"]=="completed" and c["registered_steps"]==c["completed_steps"]==32 and c["cpu_ns"]>0
                require(completion[key]["criterion_met"]==complete and completion[key]["required_steps"]==32
                    and completion[key]["completed_steps"]==c["completed_steps"] and completion[key]["status"]==c["status"],"complete-policy gate")
                checks.append(complete)
            eligibility[task,head]=all(checks)
        expected_contrasts=[(t,h,split,base) for t,h in itertools.product(TASKS,HEADS)
            for split,base in [("future",b) for b in p["primary_future_baselines"]]+[("old","warmup_old")]]
        primary=index_rows(evaluation["primary_contrasts"],("task","head","split","baseline"),expected_contrasts)
        exported=index_rows(manifest["contrasts"],("task","head","split","baseline"),expected_contrasts)
        rng=np.random.Generator(np.random.PCG64(20261025));checks={};maximum_interval_error=0.
        for task,split in expected_roles:
            inverse,samples=component_draws(*role_values[task,split],rng)
            for key in [k for k in expected_contrasts if k[0]==task and k[2]==split]:
                _,head,_,baseline=key;row=primary[key]
                paired=np.stack([losses[task,head,s,p["candidate"],split]-losses[task,head,s,baseline,split] for s in SEEDS])
                close(paired,arrays[exported[key]["paired_delta_key"]],"exported paired source losses")
                interval=paired_interval(paired,inverse,samples)
                for field,value in interval.items():
                    maximum_interval_error=max(maximum_interval_error,close(value,row[field],"bootstrap "+field))
                numeric=numerical_gate(split,interval["upper_bound"]);passed=numeric and eligibility[task,head]
                require(row["candidate"]==p["candidate"] and row["threshold"]==(-.001 if split=="future" else 0.)
                    and row["completion_eligible"]==eligibility[task,head] and row["numerical_threshold_met"]==numeric
                    and row["criterion_met"]==passed and row["status"]==("completed" if eligibility[task,head] else "scored_but_incomplete_execution"),"primary strict/inclusive gate")
                checks[key]={"task":task,"head":head,"split":split,"baseline":baseline,**interval,"criterion_met":passed}
        cost_groups=index_rows(evaluation["cost_contrasts"],("task","head"),itertools.product(TASKS,HEADS))
        cost_pass=[]
        for (task,head),row in cost_groups.items():
            candidate=[costs[task,head,s,p["candidate"]]["cpu_ns"] for s in SEEDS]
            baseline=[costs[task,head,s,p["primary_future_baselines"][0]]["cpu_ns"] for s in SEEDS]
            ratio=sum(candidate)/sum(baseline);passed=ratio<=3 and eligibility[task,head]
            close(ratio,row["cpu_ratio"],"ratio of summed CPU")
            close(np.asarray(candidate)/baseline,row["paired_seed_cpu_ratios"],"paired CPU ratios")
            require(row["threshold"]==3. and row["criterion_met"]==passed
                and row["completion_eligible"]==eligibility[task,head] and row["candidate"]==p["candidate"]
                and row["baseline"]==p["primary_future_baselines"][0]
                and row["status"]==("completed" if eligibility[task,head] else "scored_but_incomplete_execution"),"cost gate")
            cost_pass.append(passed)
        science=all(eligibility.values()) and all(r["criterion_met"] for r in checks.values())
        resources=all(valid_costs) and all(eligibility.values()) and all(cost_pass)
        flags={"census_complete":True,"cost_census_complete":all(valid_costs),
            "required_completion_met":all(eligibility.values()),"all_scientific_criteria_met":science,
            "all_cost_criteria_met":resources,"all_registered_gates_met":science and resources,
            "primary_criteria_met":sum(r["criterion_met"] for r in checks.values()),
            "candidate_completed_fits":sum(r["criterion_met"] for r in completion.values() if r["policy"]==p["candidate"])}
        for key,value in flags.items():
            require(evaluation[key]==value,"closed verdict: "+key)
        report.update(status="passed",experiment_version=version,protocol_sha256=PROTOCOLS[version],
            report_sha256=sha(directory/"evaluation.json"),source_statistics_sha256=sha(directory/"audit_inputs.npz"),
            statistics_manifest_sha256=sha(directory/"audit_inputs.json"),seal_sha256=sha(run/"pre_evaluation_seal.json"),
            metric_records_verified=len(metrics),source_roles_verified=len(roles),cost_records_verified=len(costs),
            completion_records_verified=len(completion),completion_criteria_met=sum(r["criterion_met"] for r in completion.values()),
            primary_contrasts_verified=len(checks),cost_contrasts_verified=len(cost_groups),cost_criteria_met=sum(cost_pass),
            metric_max_abs_error=maximum_metric_error,interval_max_abs_error=maximum_interval_error,
            primary_contrasts=[checks[k] for k in expected_contrasts],verified_verdict=flags,
            science_disposition="eligible_for_trusted_native_review" if flags["all_registered_gates_met"] else "REJECT")
    except Exception as error:
        report["failures"].append({"type":type(error).__name__,"message":str(error)})
    report.update(completed_at=datetime.now(timezone.utc).isoformat(),cpu_ns=time.process_time_ns()-cpu,wall_ns=time.perf_counter_ns()-began)
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open("x") as stream:
        json.dump(report,stream,indent=2,sort_keys=True,allow_nan=False);stream.write("\n")
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("evaluation-directory","run-directory","protocol-path","output"):
        parser.add_argument("--"+name,required=True)
    result=audit(**vars(parser.parse_args()))
    print(json.dumps({k:result[k] for k in ("status","failures")}))
    sys.exit(0 if result["status"]=="passed" else 1)
