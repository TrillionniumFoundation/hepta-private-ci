"""Read-only independent case/metric replay for pinned hosted *pretrained* model output.

The binary source task is AG News world vs sports. This consumes a prior GitHub
Actions archive, not model weights. No causal time-series, model-origin signature,
independent physical forward-count or production authority follows.
"""
import argparse
import hashlib
import json
import math
import zipfile
from pathlib import Path

ARCHIVE_SHA256="e5d945c655112139fce51b989023abd5111c9e7ab28d9bd4e8a771b86dd95f9d"
RUN_ID=38541658096
ARTIFACT_ID=11886761368
ARM_ORDER=("gemma2_frozen_head","gemma2_trained_head",
           "gemma2_trained_head_scaled_1024","laya421_frozen")

def require(ok, reason):
    if not ok:
        raise ValueError(reason)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def metrics(prob,labels):
    n=len(prob)
    require(n>0 and len(labels)==n,"mismatched or empty metric vectors")
    require(all(type(x) in (float,int) and math.isfinite(x) and 0<=x<=1 for x in prob)
            and all(type(y) is int and y in (0,1) for y in labels),"invalid probability/label")
    correct=sum((p>=.5)==bool(y) for p,y in zip(prob,labels))
    brier=sum((p-y)**2 for p,y in zip(prob,labels))/n
    bins=[[] for _ in range(8)]
    for p,y in zip(prob,labels):
        conf=max(p,1-p)
        bins[min(7,int(conf*8))].append((conf,int((p>=.5)==bool(y))))
    ece=sum(len(g)/n*abs(sum(x for x,y in g)/len(g)-sum(y for x,y in g)/len(g))
            for g in bins if g)
    return {"cases":n,"correct":correct,"accuracy":correct/n,"brier":brier,"confidence_ece8":ece}

def audit_archive(filename):
    path=Path(filename)
    require(path.is_file() and path.stat().st_size<20_000_000,"missing/oversize archive")
    raw=path.read_bytes()
    require(sha(raw)==ARCHIVE_SHA256,"not the exact recorded real-model artifact")
    with zipfile.ZipFile(path) as z:
        names=z.namelist()
        required=("stem-agnews-new-source-panel.json","stem-gemma-fresh-arms.json",
                  "stem-laya-fresh-arm.json","stem-new-source-independent-review.json",
                  "stem-process-resources.json")
        require(len(names)==len(set(names)) and set(required)<=set(names),"bad archive inventory")
        require(all(not n.startswith("/") and ".." not in Path(n).parts and z.getinfo(n).file_size<2_000_000
                    for n in names),"unsafe archive member")
        panel,gemma,laya,prior,cost=[json.loads(z.read(n)) for n in required]
    require(panel.get("case_count")==128 and len(panel.get("cases",[]))==128
            and panel.get("chronological_future_claim") is False
            and panel.get("same_public_source_family") is True
            and panel.get("production_promotion")=="DENY_ALL","source not accepted")
    cases={}
    for c in panel["cases"]:
        key=c.get("case_id")
        require(type(key) is str and key not in cases and c.get("split")=="new_holdout"
                and type(c.get("label")) is int and c["label"] in (0,1)
                and c.get("source_digest")==c.get("group_id")
                and type(c.get("joint_input_digest")) is str
                and len(c["joint_input_digest"])==64,"invalid original case")
        cases[key]=c
    require(len(cases)==128 and len({c["group_id"] for c in cases.values()})==128,"missing distinct cases")
    arms=gemma+[laya]
    require(type(gemma) is list and len(arms)==4 and
            set(a.get("arm_id") for a in arms)==set(ARM_ORDER),"wrong model controls")
    aligned={}
    result={}
    ids=sorted(cases)
    labels=[cases[i]["label"] for i in ids]
    for arm in arms:
        name=arm["arm_id"]
        require(arm.get("panel_digest")==prior.get("replication_panel_digest")
                and arm.get("production_promotion")=="DENY_ALL"
                and arm.get("cross_sectional_new_source_not_temporal_future") is True
                and arm.get("matched_full_lifecycle_cost") is False
                and arm.get("raw_source_and_model_origin_independently_attested") is False,
                "unsupported model capability or cohort")
        expected_sha=prior["source_and_report_digests"].get(name)
        canonical=json.dumps(arm,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode()
        require(sha(canonical)==expected_sha,"model source report digest differs")
        rows={}
        for row in arm["rows"]:
            key=row.get("case_id")
            require(key in cases and key not in rows
                    and row.get("source_digest")==cases[key]["source_digest"]
                    and row.get("joint_input_digest")==cases[key]["joint_input_digest"]
                    and row.get("split")=="new_holdout", "unmatched physical prediction")
            rows[key]=row
        require(set(rows)==set(ids),"missing arm case")
        probabilities=[rows[k]["prob_sports"] for k in ids]
        m=metrics(probabilities,labels)
        prev=prior["metrics"][name]
        require(m["cases"]==prev["cases"] and
                abs(m["accuracy"]-prev["accuracy"])<1e-11 and
                abs(m["brier"]-prev["brier"])<1e-11 and
                abs(m["confidence_ece8"]-prev["descriptive_ece_8bin"])<1e-11,
                "independent metric disagreement")
        result[name]=m
        aligned[name]=rows
    for i in ids:
        p=aligned["gemma2_trained_head"][i]["prob_sports"]
        q=aligned["gemma2_trained_head_scaled_1024"][i]["prob_sports"]
        require(0<p<1 and 0<q<1,"invalid scaled logit")
        v=1024*math.log(p/(1-p))
        calc=1/(1+math.exp(-v)) if v>=0 else math.exp(v)/(1+math.exp(v))
        require(abs(calc-q)<1e-10,"posthoc multiplier drift")
    paired={}
    for a,b in (("gemma2_trained_head","gemma2_frozen_head"),
                ("gemma2_trained_head","laya421_frozen")):
        gained=lost=0
        for i in ids:
            true=bool(cases[i]["label"])
            right_a=(aligned[a][i]["prob_sports"]>=.5)==true
            right_b=(aligned[b][i]["prob_sports"]>=.5)==true
            gained+=right_a and not right_b
            lost+=right_b and not right_a
        paired[a+"_vs_"+b]={"recovered":gained,"lost":lost}
    require(cost.get("model_lifetime_cost_equalization_proven") is False and
            cost.get("production_promotion")=="DENY_ALL","incorrect resource authority")
    return {"schema":"hepta.p0.historical-real-artifact-numeric-audit.v1",
            "workflow_run":RUN_ID,"artifact_id":ARTIFACT_ID,
            "archive_sha256":ARCHIVE_SHA256,"case_count":128,
            "metrics":result,"paired":paired,
            "model_process_measurements_claimed":cost.get("measurements"),
            "numerical_and_case_replay":True,
            "physical_model_origin_independently_authenticated":False,
            "future_time_generalization_proven":False,
            "complete_four_stem_p0_qualified":False,
            "p1_four_scale_qualified":False,
            "equal_total_lifecycle_cost_qualified":False,
            "production_accepted":False,"authority":"DENY_ALL"}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--archive",required=True)
    p.add_argument("--output",required=True)
    a=p.parse_args()
    result=audit_archive(a.archive)
    with Path(a.output).open("x",encoding="utf-8") as f:
        json.dump(result,f,sort_keys=True,separators=(",",":"))
        f.write("\n")

if __name__=="__main__":
    main()
