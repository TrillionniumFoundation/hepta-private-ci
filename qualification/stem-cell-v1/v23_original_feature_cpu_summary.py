"""Source-only deterministic aggregation of TWO independently reviewed V23 CPU runs.

Does NOT import numerical model code. The separate NumPy auditor must already
have authenticated the exact original source/models and every raw timing vector.
No selected Cell, physical target-host claim or future effect can be inferred.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SCHEMA="hepta.stem.v23.actual-original-feature-physical-head-scale.research"
RAW="hepta.stem.v23.original-feature-packed-head-cost.research"
REVIEW="hepta.stem.v23.original-feature-packed-head-cost.independent-review"
SIZES=(64,256,1024,4096)
ARMS=("all_loop","all_packed","active32_loop","active32_packed")


def require(c,msg):
    if not c:raise ValueError(msg)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def canonical(obj):
    return (json.dumps(obj,sort_keys=True,separators=(",", ":"),ensure_ascii=False,allow_nan=False)+"\n").encode()


def unique(items):
    r={}
    for k,v in items:
        require(k not in r,"duplicate JSON metadata field")
        r[k]=v
    return r


def read(p):
    p=Path(p)
    require(p.is_file() and not p.is_symlink() and 0<p.stat().st_size<=1_000_000,
            "bounded ordinary result/receipt required")
    obj=json.loads(p.read_bytes(),object_pairs_hook=unique,
                   parse_constant=lambda c:(_ for _ in ()).throw(ValueError("nonfinite")))
    canonical(obj)
    return obj


def aggregate(evidence):
    root=Path(evidence)
    require(root.is_dir() and not root.is_symlink(),"real distinct evidence directory required")
    reviews={r:read(root/f"v23-{r}-independent-review.json") for r in ("A","B")}
    for x in reviews.values():
        require(x["schema"]==REVIEW and x["independent_forward_replay"] is True and
                x["four_original_sample_numeric_probe_consistent"] is True and
                x["physical_head_values_are_only_two_repeated_trained_heads"] is True and
                x["authority_posture"]=="DENY_ALL" and
                x["independently_attested_cpu_or_host"] is False and
                x["future_task_utility_verified"] is False and
                x["production_authorized"] is False and
                x["model_or_cell_promotion_authorized"] is False,
                "only two negative-only independently reviewed original runs permitted")
    require(reviews["A"]["model_sha256"]==reviews["B"]["model_sha256"] and
            reviews["A"]["source_feature_sha256"]==reviews["B"]["source_feature_sha256"] and
            reviews["A"]["input_roster_sha256"]==reviews["B"]["input_roster_sha256"],
            "replicated original model/source identities changed")
    by_size={}
    for n in SIZES:
        originals={r:read(root/f"v23-{r}-{n}.json") for r in ("A","B")}
        require(all(originals[r]["schema"]==RAW and originals[r]["physical_cell_slots"]==n
                    and reviews[r]["receipt_canonical_sha256"][str(n)]==sha(canonical(originals[r]))
                    for r in ("A","B")),"independent reviewer did not reread exact raw bytes")
        require(originals["A"]["probe_numeric_consistency"]==originals["B"]["probe_numeric_consistency"],
                "original trained Head model forward SHA diverged across physical processes")
        out=[]
        for r,x in originals.items():
            require(set(x["profiles"])==set(ARMS) and x["timed_rounds"]==128 and
                    x["production_authorized"] is False and
                    x["scientific_promotion_authorized"] is False and
                    x["new_independent_future_sources"]==0,
                    "missing original complete CPU only no-go ledger")
            out.append({"replica":r,
                        "source_report_sha256":sha((root/f"v23-{r}-{n}.json").read_bytes()),
                        "whole_process_maxrss_kib":x["whole_process_rusage_maxrss_kib_after_benchmark"],
                        "p95_ns":{k:v["p95_ns"] for k,v in x["profiles"].items()},
                        "p99_ns":{k:v["p99_ns"] for k,v in x["profiles"].items()},
                        "process_cpu_ns":{k:v["process_cpu_ns"] for k,v in x["profiles"].items()},
                        "timed_rounds":x["timed_rounds"]})
        x=originals["A"]
        by_size[str(n)]={"individually_allocated_slots":n,
            "unique_trained_weight_value_sets":2,
            "base_head_storage_bytes":x["weight_bank_bytes"],
            "preselected_cached_head_storage_bytes":x["selected_cached_head_weight_bytes"],
            "total_head_storage_bytes":x["total_actual_head_storage_bytes"],
            "four_original_probe_scores_identical_across_independent_processes":True,
            "replicas":out}
    result={"schema":SCHEMA,"date_utc":"2026-10-16",
     "source_repo":"TrillionniumFoundation/hepta-private-ci",
     "parent_head_sha":"4c878ed845482d759432930f7ddfaff9f5f82a56",
     "source_original_artifact_id":11890616195,
     "source_original_artifact_zip_sha256":"0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7",
     "source_features_sha256":"e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490",
     "source_model_file_sha256":"4dc71c47b4ec297ce65a221adabd8ad7888cdd1c1ce2f67a7aee3986d4a1433e",
     "real_original_train_observation_count":4,"real_trained_distinct_head_value_sets":2,
     "new_original_encoder_forwards":0,"whole_worker_executions":0,"profile_repeat_count":2,
     "timed_samples_per_kernel_profile_per_size_and_replica":128,
     "preselected_active_heads":32,"all_sized_head_fleets_physically_allocated":True,
     "independent_numpy_source_and_logits_replay":True,
     "historical_skill_gain_proven":False,"future_utility_gain_proven":False,
     "frozen_canonical_model_selected":False,"target_device_host_attestation":False,
     "host_counters_or_energy_independently_attested":False,
     "active_router_and_generation_authority_verified":False,
     "new_independent_future_source_families":0,"production_authorized":False,
     "scientific_promotion_authorized":False,"authority_posture":"DENY_ALL",
     "negative_findings":[
      "Only two real trained Head weight value sets are repeated into the N physical slots; fleet does not have N learned skills.",
      "p99 varies substantially even between independently run local CPU processes; no stable device SLA.",
      "A Python/Numpy packed kernel benchmark excludes actual Encoder forward, original Worker scheduling, CAS, WAL, recovery, energy, and authentic source authorization.",
      "Head weights are physically replicated, while four original features are reused as per-request immutable inputs.",
      "The named 4,096 logical slots are not 4,096 independent Cell owners, concurrent requests or production-scoped authorities.",
      "No independent prospective task or old-task retention result is provided."],
     "per_size":by_size}
    return result


def create_only(out,obj):
    out=Path(out)
    require(out.parent.is_dir() and not out.parent.is_symlink() and not out.exists(),
            "create-only science HOLD receipt required")
    with out.open("xb") as f:
        f.write(json.dumps(obj,indent=2,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()+b"\n")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--evidence",required=True)
    p.add_argument("--out",required=True)
    a=p.parse_args();create_only(a.out,aggregate(a.evidence))

if __name__=="__main__":main()
