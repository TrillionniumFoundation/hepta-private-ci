"""Read-only, independently implemented audit of one ORIGINAL ScienceQA Actions ZIP.

No producer/trainer/reviewer import. This validates recorded source, paired
math and GitHub run lineage. Held ground-truth labels are NOT in the ZIP:
original human-label correctness is NOT independently re-scored. DENY_ALL.
"""
import argparse
import hashlib
import json
import math
import os
import stat
import zipfile
from math import comb
from pathlib import Path

REPO = "TrillionniumFoundation/hepta-private-ci"
RUN = 38678847948
ARTIFACT = 11947722496
ARCHIVE_SHA = "f421f20cdb5d35becf5e93ed63e58996d48701c2b27b979d608e2b05b6b61f30"
HEAD = "2dc43da7d9bf343acc871219ddce44d0e14d8911"
BASE = "b8b2f10fe38506972301e77e3836729a90200673"
MERGE = "095769f27c6b2861460b385e297540081a26af05"
DATASET = "b9984af01798586705cee1fbdfa80a6dcbef04f1"
ARMS = ("text_only","unaligned_equal_fusion","rotated_equal_fusion","bridge_image_only",
        "bridge_equal_fusion","train_gate","calibrated_fusion","image_masked")
COMPARE = tuple(x for x in ARMS if x not in ("text_only","image_masked"))
MEMBERS = ("independent-descriptive-review.json","SHA256SUMS","offline-tests.txt",
    "optimized-tests.txt","physical-completed-or-absent.json","physical-gate-optimized-tests.txt",
    "physical-gate-contract-tests.txt","predictions-before-labels.sha256",
    "sealed-source-bound-predictions.json","source-blobs-SHA256","source-head.txt",
    "source-seals.json","source-tree.txt","versions.txt")

class AuditError(ValueError):
    pass

def need(cond, why):
    if not cond:
        raise AuditError(why)

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def sha_ok(x, length):
    return type(x) is str and len(x)==length and all(c in "0123456789abcdef" for c in x)

def pairs(items):
    out={}
    for key,value in items:
        need(key not in out,"duplicate JSON key")
        out[key]=value
    return out

def parse(raw):
    def bad(v): raise AuditError("nonfinite JSON constant "+v)
    x=json.loads(raw,object_pairs_hook=pairs,parse_constant=bad)
    def finite(obj):
        if type(obj) is float: need(math.isfinite(obj),"nonfinite JSON float")
        elif type(obj) is list:
            for v in obj: finite(v)
        elif type(obj) is dict:
            for v in obj.values(): finite(v)
    finite(x)
    need(type(x) is dict,"JSON root")
    return x

def exact_p(lost, rescued):
    n=lost+rescued
    return min(1.0,2*sum(comb(n,i) for i in range(min(lost,rescued)+1))/2**n) if n else 1.0

def read_archive(path):
    path=Path(path)
    need(path.is_file() and not path.is_symlink() and 0<path.stat().st_size<1024*1024,
         "archive missing/over-budget")
    need(digest(path.read_bytes())==ARCHIVE_SHA,"original Actions ZIP digest changed")
    with zipfile.ZipFile(path) as f:
        info=f.infolist()
        names=[i.filename for i in info]
        need(len(names)==len(MEMBERS) and set(names)==set(MEMBERS),"archive member inventory")
        need(sum(i.file_size for i in info)<1024*1024,"archive expansion limit")
        for i in info:
            mode=i.external_attr>>16
            need(0<i.file_size<=256*1024 and
                 "/" not in i.filename and ".." not in i.filename and
                 "\\" not in i.filename and not stat.S_ISLNK(mode),"unsafe ZIP member")
        raw={name:f.read(name) for name in names}
    inv={}
    for line in raw["SHA256SUMS"].decode("ascii").splitlines():
        fields=line.split(None,1)
        need(len(fields)==2 and sha_ok(fields[0],64),"SHA256SUMS syntax")
        name=fields[1].removeprefix("*").removeprefix("./")
        need(name not in inv,"duplicated checksum")
        inv[name]=fields[0]
    need(set(inv)==set(MEMBERS)-{"SHA256SUMS"},"missing archive checksums")
    for k,v in inv.items():
        need(v==digest(raw[k]),"member digest drift: "+k)
    return raw

def review(raw, run, merge, art):
    need(run.get("id")==RUN and run.get("head_sha")==HEAD and run.get("event")=="pull_request"
         and run.get("status")=="completed" and run.get("conclusion")=="success",
         "unconfirmed original run")
    need(run.get("name")=="Hepta E3 original Granite97 DINOv2 physical-and-score (DENY_ALL)",
         "wrong original workflow")
    prs=run.get("pull_requests")
    need(type(prs) is list and len(prs)==1 and prs[0].get("number")==2173 and
         prs[0].get("base",{}).get("sha")==BASE and prs[0].get("head",{}).get("sha")==HEAD,
         "original PR identity changed")
    need(merge.get("sha")==MERGE and
         [p.get("sha") for p in merge.get("parents",[])]==[BASE,HEAD] and
         raw["source-head.txt"].decode().strip()==MERGE and
         raw["source-tree.txt"].decode().strip()==merge.get("commit",{}).get("tree",{}).get("sha"),
         "tested synthetic merge lineage drift")
    need(art.get("id")==ARTIFACT and art.get("digest")=="sha256:"+ARCHIVE_SHA and
         art.get("name")=="hepta-e3-granite-dino-actual-or-failure-no-weights-no-media" and
         art.get("workflow_run",{}).get("id")==RUN and
         art.get("workflow_run",{}).get("head_sha")==HEAD,"wrong artifact/run")
    source=parse(raw["source-seals.json"])
    pred=parse(raw["sealed-source-bound-predictions.json"])
    score=parse(raw["independent-descriptive-review.json"])
    witness=parse(raw["physical-completed-or-absent.json"])
    need(source.get("dataset_revision")==DATASET and source.get("raw_image_count")==192
         and source.get("externally_independent_labels") is False and
         source.get("production_accepted") is False,"unmatched original dataset/authority")
    for k in ("source_sha256","fit_labels_sha256","private_test_labels_sha256"):
        need(sha_ok(source.get(k),64),"source SHA missing: "+k)
    pid=digest(raw["sealed-source-bound-predictions.json"])
    need(pid==raw["predictions-before-labels.sha256"].decode().split()[0] and
         pid==witness.get("sealed_predictions_sha256")==score.get("sealed_predictions_sha256"),
         "prediction seal/order of operations")
    need(pred.get("source_sha256")==source["source_sha256"]==score.get("source_sha256")==
         witness.get("source_sha256") and
         pred.get("fit_labels_sha256")==source["fit_labels_sha256"] and
         score.get("holdout_targets_sha256")==source["private_test_labels_sha256"],
         "source/held-label identity mismatch")
    need(witness.get("exact_source_sha")==MERGE and witness.get("authority")=="DENY_ALL"
         and witness.get("stem_winner") is None and
         witness.get("signed_model_origin_authenticated") is False and
         witness.get("natural_visual_necessity_adjudicated") is False and
         witness.get("completed_original_pretrained_stage_and_scoring") is True,
         "unsupported physical witness authority")
    for name,repo_name,rev in (
        ("stem_model","ibm-granite/granite-embedding-97m-multilingual-r2",
         "835ad14087e140460703cf0fae09f97d469d65c2"),
        ("vision_model","facebook/dinov2-small","ed25f3a31f01632728cabb09d1542f84ab7b0056")):
        model=pred.get(name,{})
        need(model.get("repo")==repo_name and model.get("revision")==rev and
             sha_ok(model.get("sha256"),64),"unpinned pretrained model")
    for name in ("physical_text_forward_batches","physical_vision_forward_batches"):
        need(type(pred.get(name)) is int and pred[name]>0 and pred[name]==witness.get(name),
             "wrong physical batch counters")
    fit=pred.get("fit",{})
    for key,count in (("organ_bridge_parameter_count",147840),
                      ("private_cell_head_parameters",769),("cell_optimizer_updates",80),
                      ("train_cases",96),("calibration_cases",32),("holdout_cases",64)):
        need(type(fit.get(key)) is int and fit[key]==count,"Head fitting ledger: "+key)
    need(pred.get("production_accepted") is False and
         pred.get("held_labels_visible_to_inference") is False and
         pred.get("independent_ground_truth_observer") is False and
         pred.get("same_source_public_release_not_future") is True and
         pred.get("true_pretrained_execution_unattested") is True and
         score.get("production_accepted") is False and
         score.get("authority")=="DENY_ALL" and score.get("stem_winner") is None and
         score.get("statistical_selection_authorized") is False and
         score.get("external_ground_truth_independent_owner") is False and
         score.get("visual_necessity_ground_truth_adjudicated") is False and
         score.get("historical_scienceqa_release_not_future") is True,
         "producer/score authority claim false")
    metrics=score.get("arms")
    need(type(metrics) is dict and set(metrics)==set(ARMS) and
         score.get("original_heldout_cases")==witness.get("heldout_cases")==64,
         "incomplete heldout review")
    for name,m in metrics.items():
        need(type(m) is dict and type(m.get("correct")) is int and 0<=m["correct"]<=64
             and type(m.get("cases")) is int and m["cases"]==64
             and type(m.get("accuracy")) in (int,float)
             and abs(m["accuracy"]-m["correct"]/64)<1e-12,"invalid accuracy: "+name)
        for k in ("nll","brier_4class_mean"):
            need(type(m.get(k)) in (int,float) and math.isfinite(m[k]) and m[k]>=0,
                 "invalid score: "+name)
    need(metrics["text_only"]==metrics["image_masked"],"invalid image mask")
    rows=pred.get("predictions")
    need(type(rows) is list and len(rows)==64 and
         len({x.get("id") for x in rows if type(x) is dict})==64,"heldout prediction inventory")
    for row in rows:
        arm=row.get("arms",{})
        need(type(arm) is dict and set(arm)==set(ARMS) and
             arm["text_only"]==arm["image_masked"],"missing/masked arm")
        if fit.get("calibration_selected_weight")==0:
            need(arm["calibrated_fusion"]==arm["text_only"],"calibration-to-text mismatch")
        for values in arm.values():
            need(type(values) is list and len(values)==4 and
                 all(type(x) in (int,float) and 0<=x<=1 and math.isfinite(x) for x in values) and
                 abs(sum(values)-1)<1e-4,"invalid four-class probability")
    if fit.get("calibration_selected_weight")==0:
        need(metrics["calibrated_fusion"]==metrics["text_only"],"calibrated summary mismatch")
    paired=score.get("paired_vs_text_only",{})
    need(type(paired) is dict and set(paired)==set(COMPARE),"incomplete paired review")
    calculated={}
    for name in COMPARE:
        p=paired[name]
        lost,rescued=p.get("new_errors_vs_text"),p.get("rescued_errors_vs_text")
        need(type(lost) is int and type(rescued) is int and
             min(lost,rescued)>=0 and lost+rescued<=64 and
             p.get("discordant_cases")==lost+rescued and
             rescued-lost==metrics[name]["correct"]-metrics["text_only"]["correct"],
             "false paired benefit: "+name)
        exact=exact_p(lost,rescued)
        need(type(p.get("mcnemar_unadjusted_exact_p")) in (float,int) and
             abs(p["mcnemar_unadjusted_exact_p"]-exact)<1e-12,
             "false McNemar p: "+name)
        calculated[name]={"rescued":rescued,"harmed":lost,"net_correct":rescued-lost,
                          "exact_mcnemar_p":exact,"six_arm_bonferroni_p":min(1.0,6*exact)}
    meter=pred.get("meter",{})
    total=pred.get("full_acquisition_plus_training_wall_ns")
    need(type(total) is int and type(meter.get("wall_ns")) is int and
         0<meter["wall_ns"]<=total and meter.get("peak_rss_bytes") is None and
         meter.get("energy_joules") is None and pred.get("energy_joules") is None,
         "unattested target host cost")
    g=calculated["train_gate"]
    return {"schema":"hepta.e3-independently-audited-archived-outcomes.v1",
            "source_pr_head":HEAD,"source_pr_merge":MERGE,"source_base":BASE,
            "original_run_id":RUN,"artifact_id":ARTIFACT,"archive_sha256":ARCHIVE_SHA,
            "original_prediction_sha256":pid,"heldout_cases":64,
            "accuracy_reported_by_original_review":{k:metrics[k]["accuracy"] for k in ARMS},
            "correct_reported_by_original_review":{k:metrics[k]["correct"] for k in ARMS},
            "independent_paired_count_and_exact_test_recalculation":calculated,
            "gate_gain_percentage_points":100*g["net_correct"]/64,
            "gate_unadjusted_p":g["exact_mcnemar_p"],
            "gate_six_arm_bonferroni_p":g["six_arm_bonferroni_p"],
            "original_calibrated_visual_weight":fit["calibration_selected_weight"],
            "original_model_forward_batches":{"text":pred["physical_text_forward_batches"],
                                                "vision":pred["physical_vision_forward_batches"]},
            "original_shared_bridge_parameters":147840,"original_cell_head_parameters":769,
            "reported_total_model_acquisition_and_fit_wall_s":total/1e9,
            "reported_measured_compute_phase_wall_s":meter["wall_ns"]/1e9,
            "human_labels_independently_replayed":False,
            "visual_necessity_adjudicated":False,"true_future_three_windows":False,
            "independent_publisher_signature":False,"target_host_peak_rss":None,
            "energy_joules":None,"stem_selected":False,"authority":"DENY_ALL"}

def main():
    p=argparse.ArgumentParser()
    for x in ("zip","run","merge","artifact","out"): p.add_argument("--"+x,required=True,type=Path)
    a=p.parse_args()
    for path in (a.run,a.merge,a.artifact):
        need(path.is_file() and not path.is_symlink() and 0<path.stat().st_size<256*1024,
             "untrusted/missing GitHub API metadata")
    result=review(read_archive(a.zip),parse(a.run.read_bytes()),parse(a.merge.read_bytes()),
                  parse(a.artifact.read_bytes()))
    need(not a.out.exists() and not a.out.is_symlink(),"result must be create-only")
    with a.out.open("x",encoding="utf-8") as f:
        f.write(json.dumps(result,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n")
        f.flush()
        os.fsync(f.fileno())
    print("E3_INDEPENDENT_ARCHIVE_PASS: original results descriptive, DENY_ALL")
    print("gate net pp",result["gate_gain_percentage_points"],
          "six-comparison corrected p",result["gate_six_arm_bonferroni_p"])

if __name__=="__main__":
    main()
