"""Independent numeric replay of an existing *real-model* GitHub Actions artifact.

This reads model-produced rows, not model weights. It is a numeric/case auditor,
NOT source authentication, inference execution, model admission or an end-to-end
P0/P1 qualification. Do not confuse shared batch-wall allocation with per-request
latency or allow the scorer to authorize any downstream behavior.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import zipfile
from pathlib import Path

ARCHIVE_ID = 11886761368
ARCHIVE_SHA256 = "e5d945c655112139fce51b989023abd5111c9e7ab28d9bd4e8a771b86dd95f9d"
SOURCE_RUN = 38541658096
REVISION_GEMMA = "914f7f89142e33e77833254d9c9b90c3cef7303b"
REVISION_LAYA = "55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851"
REQUIRED = (
    "stem-agnews-new-source-panel.json",
    "stem-gemma-fresh-arms.json",
    "stem-laya-fresh-arm.json",
    "stem-new-source-independent-review.json",
    "stem-process-resources.json",
    "stem-gemma-process-time.txt",
    "stem-laya-process-time.txt",
)
ARM_IDS = ("gemma2_frozen_head", "gemma2_trained_head",
           "gemma2_trained_head_scaled_1024", "laya421_frozen")

class AuditError(ValueError):
    pass


def require(test, msg):
    if not test:
        raise AuditError(msg)


def _sha(v):
    return type(v) is str and len(v) == 64 and v != "0"*64 and all(c in "0123456789abcdef" for c in v)


def _json(z, name):
    return json.loads(z.read(name))


def _metrics(prob, truth):
    n=len(prob)
    require(n>0 and n==len(truth), "empty / mismatched prediction array")
    loss=[(p-y)**2 for p,y in zip(prob,truth)]
    right=[(p>=0.5)==bool(y) for p,y in zip(prob,truth)]
    by_bin=[[] for _ in range(8)]
    # Repository reference metric: bin by predicted-class confidence,
    # compare mean confidence to binary correctness (not P(class=1) vs label).
    for p,y in zip(prob,truth):
        confidence=max(p,1-p)
        by_bin[min(7,int(confidence*8))].append((confidence,int((p>=0.5)==bool(y))))
    ece=sum(len(b)/n*abs(sum(p for p,y in b)/len(b)-sum(y for p,y in b)/len(b))
            for b in by_bin if b)
    return {"n":n,"correct":sum(right),"accuracy":sum(right)/n,
            "brier":sum(loss)/n,"ece8_descriptive":ece}


def _process_log(raw):
    match_wall = re.search(r"Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): ([0-9:]+(?:\.[0-9]+)?)",raw)
    match_rss = re.search(r"Maximum resident set size \(kbytes\): (\d+)",raw)
    match_user = re.search(r"User time \(seconds\): ([\d.]+)",raw)
    match_exit = re.search(r"Exit status: (\d+)",raw)
    require(all((match_wall,match_rss,match_user,match_exit)), "incomplete GNU time log")
    parts=list(map(float,match_wall.group(1).split(":")))
    elapsed=sum(v*60**i for i,v in enumerate(reversed(parts)))
    require(match_exit.group(1)=="0" and elapsed>0,"failed or zero-duration worker")
    return {"wall_seconds":elapsed,"max_rss_bytes_from_kib":int(match_rss.group(1))*1024,
            "user_cpu_seconds":float(match_user.group(1)),"exit_status":0}


def replay(zip_path, *, expected_archive_sha256, synthetic_fixture=False):
    path=Path(zip_path)
    require(path.is_file() and path.stat().st_size < 20_000_000, "bounded hosted artifact missing")
    contents=path.read_bytes()
    actual_hash=hashlib.sha256(contents).hexdigest()
    require(type(synthetic_fixture) is bool, "explicit fixture mode required")
    require(_sha(expected_archive_sha256) and actual_hash==expected_archive_sha256,
            "artifact ZIP SHA256 mismatch")
    require(synthetic_fixture or expected_archive_sha256==ARCHIVE_SHA256,
            "not the registered exact real-model archive")
    with zipfile.ZipFile(path) as z:
        names=z.namelist()
        require(len(names)==len(set(names)), "duplicate ZIP member")
        require(set(REQUIRED)<=set(names), "missing real-model/source/cost member")
        require(all(not n.startswith("/") and ".." not in Path(n).parts and
                    z.getinfo(n).file_size<2_000_000 for n in names),"unsafe ZIP member")
        panel=_json(z,REQUIRED[0]); gemma=_json(z,REQUIRED[1]); laya=_json(z,REQUIRED[2]); prior=_json(z,REQUIRED[3]); resource=_json(z,REQUIRED[4])
        original={"gemma":_process_log(z.read("stem-gemma-process-time.txt").decode("utf-8")),
                  "laya":_process_log(z.read("stem-laya-process-time.txt").decode("utf-8"))}
    require(type(panel) is dict and panel.get("case_count")==128 and
            type(panel.get("cases")) is list and len(panel["cases"])==128,
            "unaligned independent source panel")
    require(panel.get("chronological_future_claim") is False and
            panel.get("same_public_source_family") is True and
            panel.get("production_promotion")=="DENY_ALL", "source overclaim")
    cases={}
    for c in panel["cases"]:
        require(type(c) is dict and c.get("split")=="new_holdout" and
                type(c.get("case_id")) is str and c["case_id"] not in cases and
                type(c.get("label")) is int and c["label"] in (0,1) and
                all(_sha(c.get(k)) for k in ("source_digest","joint_input_digest","group_id")) and
                c["source_digest"]==c["group_id"],"invalid/duplicate source row")
        cases[c["case_id"]]=c
    require(len({c["source_digest"] for c in cases.values()})==128, "source overlap")
    require(type(gemma) is list and len(gemma)==3 and type(laya) is dict,"invalid arm roster")
    raw=gemma+[laya]
    require(set(a.get("arm_id") for a in raw)==set(ARM_IDS) and len({a.get("arm_id") for a in raw})==4,
            "duplicate/missing arm")
    byarm={a["arm_id"]:a for a in raw}
    aligned={}
    for name,a in byarm.items():
        require(a.get("production_promotion")=="DENY_ALL" and
                a.get("cross_sectional_new_source_not_temporal_future") is True and
                a.get("foundation_pretraining_overlap_ruled_out") is False and
                a.get("matched_full_lifecycle_cost") is False and
                a.get("raw_source_and_model_origin_independently_attested") is False,
                "unsupported arm authority")
        require(a.get("panel_digest")==prior.get("replication_panel_digest"),"panel revision drift")
        meta=a["metadata"]
        if name=="gemma2_trained_head_scaled_1024":
            require(meta.get("predetermined_logit_multiplier")==1024 and
                    meta.get("head_training_steps")==40, "unbound calibration")
        if name=="gemma2_trained_head":
            require(meta.get("predetermined_logit_multiplier")==1 and
                    meta.get("head_training_steps")==40, "trained Head revision")
        if name=="gemma2_frozen_head":
            require(meta.get("predetermined_logit_multiplier")==1 and
                    meta.get("head_training_steps")==0, "frozen Head changed")
        require(meta.get("revision")== (REVISION_LAYA if name=="laya421_frozen" else REVISION_GEMMA),
                "checkpoint revision drift")
        require(type(a.get("rows")) is list and len(a["rows"])==128,"incomplete real-model row results")
        ids={}
        for pred in a["rows"]:
            case_id=pred.get("case_id")
            require(case_id in cases and case_id not in ids and
                    pred.get("split")=="new_holdout" and
                    pred.get("joint_input_digest")==cases[case_id]["joint_input_digest"] and
                    pred.get("source_digest")==cases[case_id]["source_digest"] and
                    type(pred.get("prob_sports")) in (float,int) and
                    math.isfinite(pred["prob_sports"]) and 0<=pred["prob_sports"]<=1 and
                    type(pred.get("measured_serving_micros")) is int and pred["measured_serving_micros"]>=0,
                    "row or source identity drift")
            ids[case_id]=pred
        require(set(ids)==set(cases),"missing source/arm rows")
        canon=json.dumps(a,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode()
        require(prior.get("source_and_report_digests",{}).get(name)==hashlib.sha256(canon).hexdigest(),
                "arm report digest detached from independent review")
        aligned[name]=ids
    truths=[cases[i]["label"] for i in sorted(cases)]
    result={}
    for name,rows in aligned.items():
        p=[rows[i]["prob_sports"] for i in sorted(cases)]
        m=_metrics(p,truths)
        ref=prior["metrics"][name]
        require(m["n"]==ref["cases"] and all(abs(m[k]-ref[rk])<1e-11 for k,rk in
                    (("accuracy","accuracy"),( "brier","brier"),("ece8_descriptive","descriptive_ece_8bin"))),
                "prior metrics don't match raw physical rows")
        m["allocated_batch_wall_micros_not_request_latency"]=sum(rows[i]["measured_serving_micros"] for i in sorted(cases))
        result[name]=m
    paired={}
    for a,b in (("gemma2_trained_head","gemma2_frozen_head"),
                ("gemma2_trained_head_scaled_1024","laya421_frozen"),
                ("gemma2_trained_head","laya421_frozen")):
        gain=loss=equal=0
        for i in sorted(cases):
            y=cases[i]["label"]
            ac=(aligned[a][i]["prob_sports"]>=0.5)==bool(y)
            bc=(aligned[b][i]["prob_sports"]>=0.5)==bool(y)
            if ac and not bc: gain+=1
            elif bc and not ac: loss+=1
            else: equal+=1
        paired[f"{a}__vs__{b}"]={"recovered":gain,"lost":loss,"same_status":equal,
                                  "delta_accuracy":(gain-loss)/len(cases)}
    # Independently confirm that the "calibrated" arm reused the same frozen
    # trained head logits and applied exactly the previously selected multiplier.
    for i in sorted(cases):
        p=aligned["gemma2_trained_head"][i]["prob_sports"]
        q=aligned["gemma2_trained_head_scaled_1024"][i]["prob_sports"]
        require(0<p<1 and 0<q<1, "invalid calibration logit")
        z=1024*math.log(p/(1-p))
        expected=1/(1+math.exp(-z)) if z >=0 else math.exp(z)/(1+math.exp(z))
        require(abs(q-expected)<1e-10,"different Head bytes disguised as logit scaling")
    summaries={}
    for key in ("gemma","laya"):
        x=resource["measurements"][key]
        o=original[key]
        require(x.get("model_process_exit_status")==0 and
                abs(x["wall_seconds_including_model_load"]-o["wall_seconds"])<1e-6 and
                x["process_peak_rss_bytes"]==o["max_rss_bytes_from_kib"] and
                abs(x["process_user_cpu_seconds"]-o["user_cpu_seconds"])<1e-6,
                "self-reported resource metric differs from raw GNU time log")
        summaries[key]=o
    require(resource.get("model_lifetime_cost_equalization_proven") is False and
            resource.get("production_promotion")=="DENY_ALL", "resource overclaim")
    return {"schema":"hepta.p0.real-pretrained-artifact-independent-numeric-replay.v1",
        "artifact_id":None if synthetic_fixture else ARCHIVE_ID,
        "workflow_run":None if synthetic_fixture else SOURCE_RUN,
        "synthetic_fixture":synthetic_fixture,
        "verified_local_artifact_sha256":actual_hash,
        "model_checkpoint_revision":{"gemma2":REVISION_GEMMA,"laya421":REVISION_LAYA},
        "source_cases":len(cases),"raw_row_coverage":len(cases)*len(ARM_IDS),
        "metrics":result,"paired_correctness":paired,
        "process_observations":summaries,
        "methodological_blocks":["same_public_AG_News_source_family_not_temporal_future",
            "not_four_model_panel_Granite_mmBERT_missing","not_equal_full_lifecycle_cost",
            "pretraining_contamination_not_excluded","model_weights_origin_not_independently_signed",
            "physical_transformer_forwards_not_independently_counted",
            "batch_wall_allocation_not_individual_request_p99",
            "no_64_256_1024_4096_physical_real_encoder_cell_scale"],
        "independent_numeric_and_case_replay":True,
        "independent_model_or_source_authentication":False,
        "p0_accepted":False,"p1_accepted":False,"production_accepted":False,
        "authority":"DENY_ALL"}


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--archive",required=True)
    cli.add_argument("--archive-sha256",required=True)
    cli.add_argument("--output",required=True)
    args=cli.parse_args()
    report=replay(args.archive,expected_archive_sha256=args.archive_sha256)
    with Path(args.output).open("x",encoding="utf-8") as f:
        json.dump(report,f,sort_keys=True,separators=(",",":"),allow_nan=False)
        f.write("\n")
    print(json.dumps({"source_cases":report["source_cases"],"scores":{k:v["accuracy"] for k,v in report["metrics"].items()},"p0_accepted":False,"authority":"DENY_ALL"},sort_keys=True))

if __name__=="__main__":
    main()
