"""Independent stdlib verification of archived CPU Conv2d schedule/cost evidence.

Recounts exact SHA-cache misses and group-depth forwards without importing
repository models, tower code or scoring functions. Timers remain self-reported
samples, NOT independently attested hardware measurements.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics

DEPTHS = (2, 8)
PROFILES = ("forward_only", "paired")
BATCHES = (1, 4)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def get(path):
    raw = Path(path).read_bytes()
    if len(raw) > 10_000_000:
        raise ValueError("oversized evidence file")
    def unique(pairs):
        record={}
        for k, v in pairs:
            if k in record: raise ValueError("duplicate JSON field")
            record[k]=v
        return record
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def insist(condition, reason):
    if not condition:
        raise ValueError(reason)


def nns(x):
    insist(type(x) is int and x > 0, "positive nanosecond timer required")
    return x


def reconstruct(cases, depth, batch_size):
    known=set(); hits=calls=requested=0; events=[]
    for start in range(0,len(cases),batch_size):
        block=cases[start:start+batch_size]
        for current in range(2,depth+1,2):
            frame_ids=[f["sha256"] for c in block for f in c["inputs"]["video"][current-2:current]]
            insist(all(type(k) is str and len(k)==64 for k in frame_ids), "bad frame SHA")
            new=set(frame_ids)-known
            count=int(bool(new)); calls+=count
            hits+=sum(k in known for k in frame_ids)
            known.update(new);requested+=len(frame_ids)
            events.append({"batch":start//batch_size,"depth":current,
                           "case_ids":[c["case_id"] for c in block],
                           "requested_frames":len(frame_ids),"physical_video_calls":count})
    return {"unique_frames":len(known), "physical_video_calls":calls,
            "cache_hits":hits, "requested_frame_rows":requested,
            "events":events, "conv_batch_sizes":None}


def audit(root, output):
    root,output=Path(root),Path(output)
    report=get(output/"report.json");plan=get(output/"plan.json");trace=get(output/"trace.json")
    protocol=get(output/"protocol.json")
    manifest_raw=(root/"manifest.json").read_bytes()
    manifest=get(root/"manifest.json")
    insist(report.get("schema")=="hepta.video-cpu-proxy-benchmark.v1", "wrong report schema")
    insist(plan.get("schema")=="hepta.video-cpu-proxy-plan.v1", "wrong plan schema")
    insist(protocol.get("schema")=="hepta.video-cpu-proxy-protocol.v1" and
           sha((output/"protocol.json").read_bytes())==plan["protocol_sha256"]==report["protocol_sha256"],
           "pretraining source/experiment protocol seal mismatch")
    for f in ("profiles","sizes","depths","batch_sizes","rounds","warmups","torch_threads",
              "frozen_proxy_sha256","manifest_sha256","source_sha256"):
        insist(protocol[f]==plan[f], "presealed CPU experiment grid changed")
    insist(sha(manifest_raw)==report["manifest_sha256"]==plan["manifest_sha256"],"manifest binding mismatch")
    insist(sha((output/"trace.json").read_bytes())==report["trace_sha256"],"trace seal mismatch")
    insist(plan["frozen_proxy_sha256"]==trace["frozen_proxy_sha256"]==report["proxy"]["sha256"],
           "frozen weight identity mismatch")
    insist(plan["trained_reader_sha256"]==trace["trained_reader_sha256"]==report["reader"]["sha256"],
           "Reader weight identity mismatch")
    insist(plan["frozen_random_conv_not_clip"] is True and report["pretrained_vision_model"] is False
           and report["real_clip_acceleration_established"] is False
           and report["net_full_study_savings_established"] is False
           and report["production_accepted"] is False,"surrogate promoted to real CLIP")
    insist(plan["profiles"]==list(PROFILES) and plan["depths"]==list(DEPTHS)
           and plan["batch_sizes"]==list(BATCHES) and plan["torch_threads"]==1,
           "unregistered profile")
    raw=(root/manifest["dataset"]["path"]).read_bytes()
    insist(sha(raw)==manifest["dataset"]["sha256"],"source dataset bytes changed")
    cases=[json.loads(line) for line in raw.splitlines()]
    source_cohort=get(root/manifest["cohort"]["path"])
    insist([c["case_id"] for c in cases]==[r["case_id"] for r in source_cohort], "cohort mismatch")
    pools={"paired":cases,
           "forward_only":[c for c,metadata in zip(cases,source_cohort)
                           if metadata["direction"]=="forward"]}
    insist(len(cases)==80 and len(pools["forward_only"])==40,"unexpected source denominator")
    sizes=plan["sizes"]
    insist(type(sizes) is list and len(sizes)==len(set(sizes)) and all(s in (8,16,32) for s in sizes),
           "bad workload sizes")
    runs=plan["rounds"]
    insist(type(runs) is int and 1<=runs<=9, "bad benchmark repeat count")
    expected={f"{profile}:{size}:{depth}" for profile in PROFILES for size in sizes for depth in DEPTHS}
    insist(set(report["measurements"])==expected, "incomplete workload grid")
    insist(set(trace["records"])=={f"{k}:{b}" for k in expected for b in BATCHES},
           "missing first measured trace")
    res={}; arm_wall_ns=0
    for k in sorted(expected):
        profile, size, depth=k.split(":");size=int(size);depth=int(depth)
        item=report["measurements"][k]
        insist(item["profile"]==profile and item["cases"]==size and item["fixed_depth"]==depth,
               "run metadata drift")
        pool=pools[profile][:size]
        reference_predictions={}
        summaries=[]
        for b in BATCHES:
            observed=trace["records"][f"{k}:{b}"]
            independent=reconstruct(pool,depth,b)
            assert_keys=("unique_frames","physical_video_calls","cache_hits","requested_frame_rows")
            insist(all(observed["physical_work"][f]==independent[f] for f in assert_keys),
                   "physical work does not match independent SHA cache replay")
            events=observed["events"]
            insist(len(events)==len(independent["events"]), "group-depth event coverage mismatch")
            for e1,e2 in zip(events,independent["events"]):
                insist(all(e1[name]==e2[name] for name in e2),"physical batch schedule falsified")
                insist(e1["charged_once_to_batch"] is True and nns(e1["wall"]["wall_ns"]),
                       "missing per-event charge")
            rows=observed["records"]
            insist([r["case_id"] for r in rows]==[c["case_id"] for c in pool],"Cell coverage/order mismatch")
            for row in rows:
                p=row["probabilities"]
                insist(row["depth"]==depth and row["prediction"] in (0,1)
                    and isinstance(p,list) and len(p)==2 and all(type(x) in (int,float)
                    and math.isfinite(x) and 0<=x<=1 for x in p)
                    and abs(sum(p)-1)<1e-5 and row["prediction"]==max(range(2),key=lambda x:p[x])
                    and [x["depth"] for x in row["exits_seen"]]==list(range(2,depth+1,2)),
                    "Reader prediction not coherently serialized")
            reference_predictions[b]=rows
            metric=item[f"batch_{b}"]
            insist(len(metric)==runs,"missing timed repetitions")
            for m in metric:
                arm_wall_ns += m["wall_ns"]
                insist(type(m["stream_wall_ns"]) is int and 0<m["stream_wall_ns"]<=m["wall_ns"]
                    and m["research_wrapper_overhead_ns"]==m["wall_ns"]-m["stream_wall_ns"]
                    and m["physical_calls"]==independent["physical_video_calls"]
                    and m["unique_frames"]==independent["unique_frames"]
                    and m["requested_rows"]==independent["requested_frame_rows"]
                    and len(m["conv_batch_sizes"])==m["physical_calls"]
                    and sum(m["conv_batch_sizes"])==m["unique_frames"]
                    and 0<m["preprocess_ns"]<=m["wall_ns"]
                    and 0<m["conv_forward_ns"]<=m["wall_ns"]
                    and m["preprocess_ns"]+m["conv_forward_ns"]<=m["wall_ns"]
                    and m["read_source_bytes"]>0
                    and nns(m["process_cpu_ns"])>0,
                    "measured physical batching/cost counters inconsistent")
            ordered=sorted(m["wall_ns"] for m in metric)
            entry=item["serial_wall"] if b==1 else item["batched_wall"]
            insist(entry["samples_ns"]==[m["wall_ns"] for m in metric]
                   and entry["median_ns"]==int(statistics.median(ordered))
                   and entry["nearest_rank_p95_ns"]==ordered[(95*runs+99)//100-1]
                   and entry["nearest_rank_p99_ns"]==ordered[(99*runs+99)//100-1],
                   "sampled wall-clock quantile was altered")
            summaries.append(statistics.median(ordered))
        for a,b in zip(reference_predictions[1],reference_predictions[4]):
            insist(a["prediction"]==b["prediction"] and max(abs(x-y) for x,y in
                zip(a["probabilities"],b["probabilities"])) <= 2e-5,
                "fixed Reader output diverged across physical batching")
        insist(math.isclose(item["ratio_median_wall"],summaries[0]/summaries[1],rel_tol=1e-9),
               "reported speed ratio was altered")
        res[k]={"serial_ms":round(summaries[0]/1e6,3),
                "batch4_ms":round(summaries[1]/1e6,3),
                "ratio":round(item["ratio_median_wall"],3),
                "physical_calls_1":trace["records"][f"{k}:1"]["physical_work"]["physical_video_calls"],
                "physical_calls_4":trace["records"][f"{k}:4"]["physical_work"]["physical_video_calls"]}
    insist(report["measured_arm_wall_ns"]==arm_wall_ns
           and report["warmup_executions_charged"]==len(expected)*len(BATCHES)*plan["warmups"]
           and type(report["warmup_wall_ns"]) is int and report["warmup_wall_ns"]>=0
           and nns(report["whole_study_wall_ns_excludes_report_write"])>= (
               arm_wall_ns+report["warmup_wall_ns"]+report["training_breakdown"]["full_training_and_feature_wall"]["wall_ns"]),
           "whole study omitted calibration, training, or shadow work")
    return {"schema":"hepta.independent-video-cpu-proxy-audit.v1", "audited_workloads":res,
            "runs_per_workload_arm":runs, "source_sha256":sha(manifest_raw),
            "hardware_timing_independently_attested":False,
            "real_CLIP_or_model_accuracy_qualified":False,
            "production_accepted":False}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(audit(args.root,args.output),sort_keys=True))
