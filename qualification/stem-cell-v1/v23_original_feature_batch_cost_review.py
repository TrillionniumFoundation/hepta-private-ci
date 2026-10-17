"""Independent NumPy/static readback of V23 packed CPU Head measurement files.

No producer import. Recomputes numeric probe from fixed saved V16 tensors,
checks complete four-size census and recomputes raw sample quantiles. Does NOT
attest timing correctness, host trust, production Worker or future efficacy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from safetensors.numpy import load

import v20_original_material_challenge as original

SCHEMA="hepta.stem.v23.original-feature-packed-head-cost.research"
SIZES=(64,256,1024,4096)
FEATURE_SHA="e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490"
INPUT_SHA="d029f906565946216126db39e4ca3f4f14d7ab5a3c297ec2a62639ccdfbf604a"
PROFILES=("all_loop","all_packed","active32_loop","active32_packed")
EXPECTED_SPLIT=original.SAVED_MODEL_SHA["41-joint"]


def require(ok,why):
    if not ok:raise ValueError(why)


def canon(v):
    return (json.dumps(v,sort_keys=True,separators=(",", ":"),ensure_ascii=False,allow_nan=False)+"\n").encode()


def sha(b):return hashlib.sha256(b).hexdigest()


def uniq(items):
    d={}
    for k,v in items:
        require(k not in d,"duplicate JSON field")
        d[k]=v
    return d


def read(path):
    p=Path(path)
    require(p.is_file() and not p.is_symlink() and 0<p.stat().st_size<1_000_000,
            "bounded ordinary measured receipt required")
    v=json.loads(p.read_bytes(),object_pairs_hook=uniq,
                 parse_constant=lambda _:(_ for _ in ()).throw(ValueError("nonfinite")))
    canon(v)
    return v


def percentile(a,q):
    require(type(a) is list and len(a)>=100 and all(type(x) is int and 0<x<10**12 for x in a),
            "100+ true positive timing samples required")
    a=sorted(a);u=(len(a)-1)*q;k=int(u);w=u-k
    return float(a[k]*(1-w)+a[min(k+1,len(a)-1)]*w)


def probe_digest(w,b,x):
    # Independent NumPy broadcasted sum; no producer functions imported.
    logits=np.empty((len(w),4),dtype=np.float32)
    for k in range(len(w)):
        logits[k]=np.dot(w[k],x)+b[k]
    require(np.isfinite(logits).all(),"original numeric score nonfinite")
    return sha(np.rint(logits*1e4).astype("<i8").tobytes())


def review(inputs,v15,v16,paths):
    require(len(paths)==4,"all four preregistered physical sizes required")
    reports={}
    for p in paths:
        obj=read(p)
        require(type(obj.get("physical_cell_slots")) is int and
                obj["physical_cell_slots"] in SIZES and
                obj["physical_cell_slots"] not in reports,"duplicate/invalid fleet size")
        reports[obj["physical_cell_slots"]]=obj
    require(tuple(sorted(reports))==SIZES,"entire original four-tier benchmark missing")
    original_raw=original.bounded_bytes(Path(inputs)/"features.safetensors",300_000)
    require(sha(original_raw)==FEATURE_SHA and
            sha(original.bounded_bytes(Path(inputs)/"input.json"))==INPUT_SHA,
            "original feature panel source drift")
    dataset=load(original_raw)
    require(set(dataset)=={"features"} and dataset["features"].shape==(128,384) and
            dataset["features"].dtype==np.float32,"wrong actual pretrained feature tensor")
    meta=original.read(Path(inputs)/"input.json")
    indices=meta["partitions"]["train"][:4]
    require(len(indices)==4 and len(set(indices))==4,"no four original TRAIN probes")
    mean,_,split,_,mean_sha=original.physically_reload(v15,v16)
    features=np.array(dataset["features"][indices]-mean,dtype=np.float32,copy=True)
    features/=np.maximum(np.linalg.norm(features,axis=1,keepdims=True),1e-12)
    need_signatures=[]
    result={}
    for n,obj in sorted(reports.items()):
        allowed={"schema","source_kind","producer_source_sha256","feature_sha256","input_source_sha256",
            "v15_normalizer_sha256","original_v16_split_file_sha256",
            "model_origin_signed_by_publisher","encoder_forward_count_this_run",
            "physical_cell_slots","physically_allocated_individual_head_slots",
            "unique_independently_trained_head_values","weight_bank_bytes",
            "selected_cached_head_weight_bytes","total_actual_head_storage_bytes",
            "logical_active_ids","shared_original_feature_count","per_cell_feature_copies_made",
            "probe_numeric_consistency","benchmark_measurement","timed_rounds","warmups",
            "whole_process_rusage_maxrss_kib_before_weights","whole_process_rusage_maxrss_kib_after_weights",
            "whole_process_rusage_maxrss_kib_after_benchmark","profiles","research_result",
            "actual_target_device_host_verified","feature_cache_authority_verified",
            "new_independent_future_sources","prospective_utility_verified","old_task_retention_verified",
            "signed_meter_or_hardware_attested","scientific_promotion_authorized",
            "production_authorized","authority_posture"}
        require(type(obj) is dict and set(obj)==allowed and
                obj["schema"]==SCHEMA and obj["source_kind"]=="original_pretrained_mmbert_cached_features_only" and
                obj["producer_source_sha256"]==sha(Path(__file__).with_name("v23_original_feature_batch_cost.py").read_bytes()) and
                obj["feature_sha256"]==FEATURE_SHA and obj["input_source_sha256"]==INPUT_SHA and
                obj["v15_normalizer_sha256"]==mean_sha and
                obj["original_v16_split_file_sha256"]==EXPECTED_SPLIT and
                obj["encoder_forward_count_this_run"]==0 and
                obj["model_origin_signed_by_publisher"] is False and
                obj["physically_allocated_individual_head_slots"]==n and
                obj["unique_independently_trained_head_values"]==2 and
                obj["weight_bank_bytes"]==n*1540*4 and
                obj["selected_cached_head_weight_bytes"]==32*1540*4 and
                obj["total_actual_head_storage_bytes"]==(n+32)*1540*4 and
                obj["shared_original_feature_count"]==4 and
                obj["per_cell_feature_copies_made"]==0 and
                obj["timed_rounds"]>=100 and obj["timed_rounds"]<=256 and
                0<=obj["warmups"]<=32 and
                obj["benchmark_measurement"]=="local_one_thread_CPU_kernel_wall_and_process_time_not_full_worker" and
                obj["research_result"]=="CPU_KERNEL_MECHANISM_ONLY_NOT_NEW_CELL_SKILL" and
                obj["authority_posture"]=="DENY_ALL" and
                obj["new_independent_future_sources"]==0 and
                obj["actual_target_device_host_verified"] is False and
                obj["feature_cache_authority_verified"] is False and
                obj["prospective_utility_verified"] is False and
                obj["old_task_retention_verified"] is False and
                obj["signed_meter_or_hardware_attested"] is False and
                obj["scientific_promotion_authorized"] is False and
                obj["production_authorized"] is False,
                "physical original-source/report/negative authority claim changed")
        ids=[int(k*n//32) for k in range(32)]
        require(obj["logical_active_ids"]==ids,"active physical Head selection changed")
        w=np.empty((n,4,384),dtype=np.float32)
        b=np.empty((n,4),dtype=np.float32)
        for k in (0,1):
            w[k::2]=split[f"heads.{k}.weight"]
            b[k::2]=split[f"heads.{k}.bias"]
        probes=obj["probe_numeric_consistency"]
        require(type(probes) is list and len(probes)==4,"missing original genuine-feature numerical probes")
        for i,x in enumerate(features):
            require(set(probes[i])=={"full_logit_quantized_sha256","active_logit_quantized_sha256","max_f32_kernel_difference"}
                 and probes[i]["full_logit_quantized_sha256"]==probe_digest(w,b,x) and
                 probes[i]["active_logit_quantized_sha256"]==probe_digest(w[ids],b[ids],x) and
                 type(probes[i]["max_f32_kernel_difference"]) in (int,float) and
                 math.isfinite(probes[i]["max_f32_kernel_difference"]) and
                 0<=probes[i]["max_f32_kernel_difference"]<=1e-5,
                 "pretrained original Head scores changed or fake packed parity")
        need_signatures.append(sha(canon(probes)))
        prof=obj["profiles"]
        require(type(prof) is dict and set(prof)==set(PROFILES),"missing full/selected CPU arms")
        for name,p in prof.items():
            require(type(p) is dict and set(p)=={"latency_ns_samples","p95_ns","p99_ns","process_cpu_ns"}
                    and len(p["latency_ns_samples"])==obj["timed_rounds"] and
                    type(p["process_cpu_ns"]) is int and 0<p["process_cpu_ns"]<10**12,
                    "unbounded or mismatched physically timed CPU samples")
            for q,field in ((.95,"p95_ns"),(.99,"p99_ns")):
                require(type(p[field]) in (int,float) and math.isfinite(p[field]) and
                        abs(float(p[field])-percentile(p["latency_ns_samples"],q))<.001,
                        "source-independent CPU percentile claim not reproduced")
        for fld in ("whole_process_rusage_maxrss_kib_before_weights",
                    "whole_process_rusage_maxrss_kib_after_weights",
                    "whole_process_rusage_maxrss_kib_after_benchmark"):
            require(type(obj[fld]) is int and 1000<=obj[fld]<=50_000_000,
                    "invalid actual Linux process RSS resource meter")
        require(obj["whole_process_rusage_maxrss_kib_before_weights"]<=
                obj["whole_process_rusage_maxrss_kib_after_weights"]<=
                obj["whole_process_rusage_maxrss_kib_after_benchmark"],
                "peak Linux process RSS must be monotone within one child")
        result[str(n)]={"allocated_individual_head_weight_bytes":obj["weight_bank_bytes"],
                        "selected_cached_head_weight_bytes":obj["selected_cached_head_weight_bytes"],
                        "total_head_weight_bytes":obj["total_actual_head_storage_bytes"],
                        "whole_process_rss_peak_kib":obj["whole_process_rusage_maxrss_kib_after_benchmark"],
                        "timed_rounds_per_profile":obj["timed_rounds"],
                        "kernel_p95_ns":{k:v["p95_ns"] for k,v in prof.items()},
                        "kernel_p99_ns":{k:v["p99_ns"] for k,v in prof.items()}}
    return {"schema":"hepta.stem.v23.original-feature-packed-head-cost.independent-review",
            "result":"ACTUAL_ORIGINAL_FEATURE_NUMERIC_PARITY_AND_CPU_PROFILE_NOT_PRODUCTION_QUALIFICATION",
            "model_sha256":EXPECTED_SPLIT,"source_feature_sha256":FEATURE_SHA,
            "input_roster_sha256":INPUT_SHA,
            "four_original_sample_numeric_probe_consistent":True,
            "physical_head_values_are_only_two_repeated_trained_heads":True,
            "independent_forward_replay":True,
            "independently_attested_cpu_or_host":False,"future_task_utility_verified":False,
            "model_or_cell_promotion_authorized":False,"production_authorized":False,
            "authority_posture":"DENY_ALL","per_size":result,
            "receipt_canonical_sha256":{str(k):sha(canon(v)) for k,v in reports.items()}}


def create_only(path,value):
    path=Path(path)
    require(path.parent.is_dir() and not path.exists() and not path.parent.is_symlink(),
            "real create-only audit output required")
    with path.open("xb") as f:
        f.write(canon(value));f.flush()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inputs",required=True)
    p.add_argument("--v15",required=True)
    p.add_argument("--v16",required=True)
    p.add_argument("--receipt",action="append",required=True)
    p.add_argument("--out",required=True)
    a=p.parse_args()
    result=review(a.inputs,a.v15,a.v16,a.receipt)
    create_only(a.out,result)

if __name__=="__main__":main()
