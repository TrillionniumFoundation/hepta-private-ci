"""Independent stdlib replay of source-disjoint CPU batch selection and charges.

No repository models/fit/selector/scorers are imported. Wall timers are
self-reported measurements, not independent hardware attestation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics

BATCHES=(1,2,4)
MARGIN=.05
PROFILES=("forward_only","paired")
DEPTHS=(2,8)
WORKLOADS=(("forward_only",8,2),("forward_only",8,8),("paired",8,2),
           ("paired",8,8),("paired",16,2),("paired",16,8))


def insist(condition,message):
    if not condition: raise ValueError(message)


def sha(data):return hashlib.sha256(data).hexdigest()


def get(path):
    raw=Path(path).read_bytes()
    insist(len(raw)<=15_000_000,"bounded audit source required")
    def unique(pairs):
        out={}
        for k,v in pairs:
            insist(k not in out,"duplicate JSON key")
            out[k]=v
        return out
    return json.loads(raw,object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def rank(seq,p):
    s=sorted(seq)
    return s[(p*len(s)+99)//100-1]


def reconstruct(cases,depth,size):
    cache=set();calls=hits=rows=0;events=[];groups=[]
    for start in range(0,len(cases),size):
        block=cases[start:start+size]
        for d in range(2,depth+1,2):
            fs=[frame["sha256"] for c in block for frame in c["inputs"]["video"][d-2:d]]
            miss=set(fs)-cache
            count=int(bool(miss))
            calls+=count
            hits+=sum(f in cache for f in fs)
            cache.update(miss);rows+=len(fs)
            events.append((start//size,d,[c["case_id"] for c in block],len(fs),count))
        groups.append([c["case_id"] for c in block])
    return {"unique":len(cache),"calls":calls,"hits":hits,"rows":rows,
            "events":events,"groups":groups}


def audit(root,output):
    root,output=Path(root),Path(output)
    raw=(root/"manifest.json").read_bytes();manifest=json.loads(raw)
    report=get(output/"report.json");protocol=get(output/"protocol.json")
    training=get(output/"training.json");cal=get(output/"calibration.json")
    selection=get(output/"selection.json");evaluation=get(output/"evaluation.json")
    prediction=get(output/"holdout-predictions.json")
    warmup=get(output/"warmup-records.json")
    insist(report["schema"]=="hepta.video-source-disjoint-cpu-autotune.v1", "report schema")
    insist(protocol["schema"]=="hepta.video-source-disjoint-cpu-autotune-protocol.v1", "protocol schema")
    insist(protocol["batch_sizes"]==list(BATCHES) and protocol["margin"]==MARGIN
           and protocol["workloads"] and all(tuple(w) in WORKLOADS for w in protocol["workloads"])
           and len(set(tuple(w) for w in protocol["workloads"]))==len(protocol["workloads"]),
           "registered workload grid")
    insist(protocol["manifest_sha256"]==report["manifest_sha256"]==sha(raw), "source SHA")
    paths={"protocol_sha256":"protocol.json","calibration_sha256":"calibration.json",
           "selection_sha256":"selection.json","holdout_prediction_sha256":"holdout-predictions.json",
           "evaluation_sha256":"evaluation.json", "warmup_sha256":"warmup-records.json"}
    for key,name in paths.items():
        insist(report[key]==sha((output/name).read_bytes()),"sealed object mismatch: "+name)
    insist(selection["protocol_sha256"]==report["protocol_sha256"]
           and selection["calibration_sha256"]==report["calibration_sha256"]
           and prediction["selection_sha256"]==report["selection_sha256"]
           and evaluation["prediction_sha256"]==report["holdout_prediction_sha256"]
           and evaluation["selection_sha256"]==report["selection_sha256"],
           "selection or source not sealed before holdout")
    insist(training["reader"]["sha256"]==report["reader_sha256"]==selection["trained_reader_sha256"]
           and training["frozen_proxy"]["sha256"]==report["frozen_proxy_sha256"]==protocol["frozen_proxy_sha256"],
           "frozen network/Reader identity mismatch")
    insist(report["pretrained_clip_executed"] is False and report["real_clip_latency_savings_established"] is False
           and report["production_accepted"] is False and report["energy_joules"] is None
           and report["independent_future_population_quality"] is False
           and selection["holdout_labels_used"] is False,
           "unqualified research promoted to production/scientific success")
    dataset_raw=(root/manifest["dataset"]["path"]).read_bytes()
    insist(sha(dataset_raw)==manifest["dataset"]["sha256"],"dataset bytes drift")
    cases=[json.loads(row) for row in dataset_raw.splitlines()]
    cohort=get(root/manifest["cohort"]["path"])
    insist(len(cases)==len(cohort)==80 and [c["case_id"] for c in cases]==[x["case_id"] for x in cohort],
           "original video pairing drift")
    sources={p:set() for p in ("train","calibration","holdout")}
    parts={p:{pr:[] for pr in PROFILES} for p in sources}
    labels={}
    for c,meta in zip(cases,cohort):
        part=c["split"]
        insist(part in sources and meta["split"]==part and meta["source_id"]==c["group"],"source crosses fold")
        sources[part].add(meta["source_id"])
        parts[part]["paired"].append(c)
        if meta["direction"]=="forward":parts[part]["forward_only"].append(c)
        else:insist(meta["direction"]=="reverse","unknown direction")
        labels[c["case_id"]]=c["label"]
    insist([len(sources[x]) for x in sources]==[6,2,2] and len(set.union(*sources.values()))==10
           and training["source_groups"]==selection["source_groups"]==report["source_groups"]
           and all(sorted(sources[k])==report["source_groups"][k] for k in sources),"not source-disjoint")
    insist(cal["source_groups"]==sorted(sources["calibration"])
           and evaluation["source_groups"]==sorted(sources["holdout"]),"fold isolation drift")
    all_keys={f"{p}:{n}:{d}" for p,n,d in protocol["workloads"]}
    insist(set(cal["measurements"])==set(evaluation["measurements"])==
           set(selection["by_workload"])==set(prediction["records"])==
           set(report["summary"])==set(report["holdout_scores"])==all_keys,"incomplete workload grid")
    rounds={"calibration":protocol["calibration_rounds"],"holdout":protocol["evaluation_rounds"]}
    charged=0; audits={}
    charged_calls=charged_frames=charged_conv=charged_prep=charged_bytes=0
    orders=(BATCHES,(4,2,1),(2,4,1))
    def verify_entry(entry, observed, *, workload, fold, iteration, b, position):
        insist(entry["fold"]==fold and entry["workload"]==workload
               and entry["iteration"]==iteration and entry["batch_size"]==b
               and entry["order_position"]==position and orders[iteration % len(orders)][position]==b,
               "interleaved counterbalanced schedule falsified")
        insist(entry["case_count"]==int(workload.split(":")[1])
               and entry["unique_frames"]==observed["unique"]
               and entry["physical_forward_calls"]==observed["calls"]
               and entry["requested_frame_rows"]==observed["rows"]
               and sum(entry["conv_batch_sizes"])==observed["unique"]
               and len(entry["conv_batch_sizes"])==observed["calls"]
               and type(entry["wall_ns"]) is int and entry["wall_ns"]>0
               and 0<entry["stream_wall_ns"]<=entry["wall_ns"]
               and 0<entry["preprocess_ns"]+entry["conv_forward_ns"]<=entry["wall_ns"]
               and entry["source_bytes"]>0 and entry["process_cpu_ns"]>0,
               "physical cost or elapsed clock counters forged")
        values=entry["all_arrive_at_zero_group_completion_ns"]
        insist(len(values)==entry["case_count"] and all(type(v) is int and
               0<v<=entry["stream_wall_ns"] for v in values)
               and entry["first_group_completion_ns"]==min(values)
               and entry["group_completion_p50_ns"]==int(statistics.median(values))
               and entry["group_completion_p95_ns"]==rank(values,95)
               and entry["group_completion_p99_ns"]==rank(values,99),
               "group-to-Cell completion percentile forged")
        return values
    for profile,n,depth in map(tuple,protocol["workloads"]):
        key=f"{profile}:{n}:{depth}"
        readings={};selected=selection["by_workload"][key]
        for fold,archive in (("calibration",cal),("holdout",evaluation)):
            group=parts[fold][profile][:n]
            entries=archive["measurements"][key]
            insist(set(entries)==set(map(str,BATCHES)),"batch schedule coverage")
            reference=None
            for b in BATCHES:
                observed=reconstruct(group,depth,b)
                trace=entries[str(b)]
                insist(len(trace)==rounds[fold],"missing timed rounds")
                for i,entry in enumerate(trace):
                    charged+=entry["wall_ns"]
                    raw_trace=entry.get("trace")
                    insist((i==0)==(raw_trace is not None),"first-run trace identity")
                    values=verify_entry(entry,observed,workload=key,fold=fold,
                        iteration=i,b=b,position=orders[i%len(orders)].index(b))
                    charged_calls+=entry["physical_forward_calls"]
                    charged_frames+=entry["unique_frames"]
                    charged_conv+=entry["conv_forward_ns"]
                    charged_prep+=entry["preprocess_ns"]
                    charged_bytes+=entry["source_bytes"]
                    if raw_trace is not None:
                        insist(raw_trace["physical_work"]["unique_frames"]==observed["unique"]
                               and raw_trace["physical_work"]["physical_video_calls"]==observed["calls"]
                               and raw_trace["physical_work"]["requested_frame_rows"]==observed["rows"],
                               "trace physical resource totals")
                        ev=raw_trace["events"]
                        insist(len(ev)==len(observed["events"]),"missing depth/batch event")
                        for a,t in zip(ev,observed["events"]):
                            insist((a["batch"],a["depth"],a["case_ids"],a["requested_frames"],a["physical_video_calls"])==t,
                                   "event forward/count/cases forged")
                        actual_groups=raw_trace["groups"]
                        insist([g["case_ids"] for g in actual_groups]==observed["groups"],"groups altered")
                        elapsed=0;completion={}
                        for g in actual_groups:
                            elapsed+=g["wall"]["wall_ns"]
                            for identity in g["case_ids"]:completion[identity]=elapsed
                        insist([completion[r["case_id"]] for r in raw_trace["records"]]==values,
                               "group completion clock chain forged")
                        insist([r["case_id"] for r in raw_trace["records"]]==[c["case_id"] for c in group]
                               and all(r["depth"]==depth for r in raw_trace["records"]),
                               "source/Case depth coverage changed")
                        if reference is None:reference=raw_trace["records"]
                        else:
                            for a,c in zip(reference,raw_trace["records"]):
                                insist(a["prediction"]==c["prediction"] and
                                       max(abs(x-y) for x,y in zip(a["probabilities"],c["probabilities"]))<=2e-5,
                                       "batch schedule changed frozen Reader answer")
                if fold=="calibration":readings[b]=[x["wall_ns"] for x in trace]
        med={b:int(statistics.median(readings[b])) for b in BATCHES}
        best=min(med.values())
        chosen=min(b for b in BATCHES if med[b] <= (1+MARGIN)*best)
        insist(selected["batch_size"]==chosen and
               selected["median_wall_ns"]=={str(k):v for k,v in med.items()} and
               selected["best_observed_median_ns"]==best and
               selected["near_optimal_tolerance"]==MARGIN,
               "posthoc batch-size selection or incorrect tie break")
        pred=prediction["records"][key]
        group=parts["holdout"][profile][:n]
        # The scoring file must be the SAME pre-scoring model prediction as the
        # archived executed shadow trace, not a newly forged valid probability.
        first_trace=evaluation["measurements"][key]["1"][0]["trace"]["records"]
        insist(len(first_trace)==n, "missing original unscored predictions")
        for raw_row,predicted in zip(first_trace,pred["predictions"]):
            insist(type(predicted) is list and len(predicted)==2 and
                   max(abs(x-y) for x,y in zip(raw_row["probabilities"],predicted))<=2e-5,
                   "scored predictions diverge from sealed physical execution")
        insist(pred["case_ids"]==[c["case_id"] for c in group]
               and pred["selected_batch_size"]==chosen and len(pred["predictions"])==n,
               "predictions/selected schedule binding drift")
        correct=0; nll=0.
        for c,probs in zip(group,pred["predictions"]):
            insist(type(probs) is list and len(probs)==2 and all(type(x) in (int,float) and
                   math.isfinite(x) and 0<=x<=1 for x in probs) and abs(sum(probs)-1)<1e-5,
                   "invalid holdout probabilities")
            correct+=int(max(range(2),key=lambda x:probs[x])==labels[c["case_id"]])
            nll-=math.log(max(probs[labels[c["case_id"]]],1e-12))
        insist(report["holdout_scores"][key]["correct"]==correct
               and report["holdout_scores"][key]["total"]==n
               and math.isclose(report["holdout_scores"][key]["nll"],nll/n,rel_tol=1e-9,abs_tol=1e-9),
               "postseal scoring/NLL drift")
        summary=report["summary"][key]
        median_ns={b:int(statistics.median([x["wall_ns"] for x in evaluation["measurements"][key][str(b)]])) for b in BATCHES}
        insist(summary["selected_batch_size"]==chosen and summary["selected_wall_median_ns"]==median_ns[chosen]
               and summary["scalar_wall_median_ns"]==median_ns[1] and
               math.isclose(summary["selected_vs_scalar_speed_ratio"],median_ns[1]/median_ns[chosen],rel_tol=1e-10)
               and summary["selected_is_faster_on_holdout"]==(median_ns[chosen]<median_ns[1]),
               "holdout speed ratio/selected batch falsified")
        for b in BATCHES:
            entry=summary["holdout"][str(b)]
            rows=evaluation["measurements"][key][str(b)]
            walls=[row["wall_ns"] for row in rows]
            insist(entry["wall_median_ns"]==median_ns[b]
                   and entry["wall_p95_across_runs_ns"]==rank(walls,95)
                   and entry["wall_p99_across_runs_ns"]==rank(walls,99)
                   and entry["first_group_completion_median_ns"]==int(statistics.median([row["first_group_completion_ns"] for row in rows]))
                   and entry["group_p95_completion_median_ns"]==int(statistics.median([row["group_completion_p95_ns"] for row in rows]))
                   and entry["physical_call_samples"]==[row["physical_forward_calls"] for row in rows]
                   and entry["unique_frame_samples"]==[row["unique_frames"] for row in rows],
                   "holdout tail/timing or physical-call statistic forged")
        audits[key]={"source_disjoint":True,"chosen_batch":chosen,"heldout_correct":correct,
                     "heldout_denominator":n,
                     "selected_wall_ms":round(median_ns[chosen]/1e6,3),
                     "scalar_wall_ms":round(median_ns[1]/1e6,3)}
    warmup_entries=warmup["records"]
    expected_warmups=len(protocol["workloads"])*len(BATCHES)*2*protocol["warmups"]
    insist(len(warmup_entries)==expected_warmups and warmup["all_arms_included"] is True,
           "warmup shadow workload omitted")
    warmup_calls=warmup_frames=warmup_conv=warmup_prep=warmup_bytes=warmup_ns=0
    expected_warmup_ids=set()
    for profile,n,depth in map(tuple,protocol["workloads"]):
        key=f"{profile}:{n}:{depth}"
        for fold in ("calibration","holdout"):
            for i in range(-protocol["warmups"],0):
                for pos,b in enumerate(orders[i%len(orders)]):
                    expected_warmup_ids.add((key,fold,i,b,pos))
    observed_ids=set()
    for entry in warmup_entries:
        key,fold,i,b,pos=(entry["workload"],entry["fold"],entry["iteration"],
                           entry["batch_size"],entry["order_position"])
        id_tuple=(key,fold,i,b,pos)
        insist(id_tuple in expected_warmup_ids and id_tuple not in observed_ids,
               "warmup arm chronology/coverage drift")
        observed_ids.add(id_tuple)
        profile,n,depth=key.split(":");n=int(n);depth=int(depth)
        independent=reconstruct(parts[fold][profile][:n],depth,b)
        insist("trace" not in entry,"warmup prediction reintroduced")
        verify_entry(entry,independent,workload=key,fold=fold,iteration=i,b=b,position=pos)
        warmup_ns+=entry["wall_ns"]
        warmup_calls+=entry["physical_forward_calls"]
        warmup_frames+=entry["unique_frames"]
        warmup_conv+=entry["conv_forward_ns"]
        warmup_prep+=entry["preprocess_ns"]
        warmup_bytes+=entry["source_bytes"]
    insist(observed_ids==expected_warmup_ids,"missing presealed warmup comparisons")
    expected_runs=len(protocol["workloads"])*len(BATCHES)*(sum(rounds.values())+2*protocol["warmups"])
    insist(report["arm_execution_count_including_warmups"]==expected_runs
           and report["all_arms_execution_wall_ns"]==charged
           and report["warmup_wall_ns"]==warmup_ns
           and report["all_arms_including_warmups_physical_calls"]==charged_calls+warmup_calls
           and report["all_arms_including_warmups_encoded_frames"]==charged_frames+warmup_frames
           and report["all_arms_including_warmups_conv_ns"]==charged_conv+warmup_conv
           and report["all_arms_including_warmups_preprocess_ns"]==charged_prep+warmup_prep
           and report["all_arms_including_warmups_file_bytes"]==charged_bytes+warmup_bytes
           and report["all_workload_physical_calls_plus_training"]==charged_calls+warmup_calls+
                 training["work"]["training_physical_tower_calls"]
           and report["all_workload_encoded_frames_plus_training"]==charged_frames+warmup_frames+
                 training["work"]["training_unique_frames"]
           and report["whole_study_wall_ns_excludes_report_write"]>=charged+warmup_ns+
                 training["fitting_wall"]["wall_ns"],
           "study-wide resource ledger omits training, calibration or shadow arms")
    return {"schema":"hepta.independent-video-cpu-autotune-audit.v1",
            "source_disjoint_holdout":True,"audited_workloads":audits,
            "all_workload_physical_calls_plus_training":report["all_workload_physical_calls_plus_training"],
            "self_reported_timing_not_independently_attested":True,
            "not_real_clip":True,"production_accepted":False}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(audit(args.root,args.output),sort_keys=True))
