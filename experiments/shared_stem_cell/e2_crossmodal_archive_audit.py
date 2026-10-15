"""Producer-independent archive-level E2 original-model experiment auditor.

Reads four exact SHA-256-pinned GitHub artifact ZIP byte streams. It never
imports the model loader, ridge fitter, producer, scoring implementation, or
uses private original model weights. It verifies archive contents and recorded
outcomes; independently attested execution and true natural-task efficacy stay
out of scope. Fails closed on the pre-fix target-hash leak.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import io
import json
import math
from pathlib import Path
import stat
import zipfile

PREFIX = "hepta.e2.crossmodal-synthetic-physical.v1"
DINO_REV = "150c8e7bb7cef2d30ec31b13a517af14840ee3f7"
DINO_WEIGHTS = "ae1e99fcefd534ed978cdeb8326f08030c96e28b7a81ffcbc98a857c84d14be1"
GRANITE_REV = "835ad14087e140460703cf0fae09f97d469d65c2"
ARMS = ("fitted", "rotated_target_control", "unaligned_identity")
SOURCE_NAMES = {"train_images.jsonl", "future_images.jsonl", "train_anchors.jsonl", "train_class.jsonl"}
TARGET_NAMES = {"future_caption_targets.jsonl", "future_class_targets.jsonl"}
MAX_ZIP = 8 * 1024 * 1024
MAX_EXPANDED = 16 * 1024 * 1024

class AuditError(ValueError):
    pass

def require(cond, reason):
    if not cond:
        raise AuditError(reason)

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def is_sha(value):
    return type(value) is str and len(value) == 64 and not set(value) - set("0123456789abcdef")

def canonical(obj):
    return (json.dumps(obj, sort_keys=True, ensure_ascii=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode()

def duplicate_keys(pairs):
    out = {}
    for k, v in pairs:
        require(k not in out, "duplicate JSON key")
        out[k] = v
    return out

def obj(raw):
    x = json.loads(raw, object_pairs_hook=duplicate_keys,
                   parse_constant=lambda _: (_ for _ in ()).throw(AuditError("nonfinite JSON")))
    require(canonical(x) == raw, "noncanonical document")
    return x

def jsonl(raw, count=None):
    require(raw and raw.endswith(b"\n"), "invalid JSONL termination")
    lines = raw.splitlines()
    if count is not None:
        require(len(lines) == count, "unexpected row count")
    require(1 <= len(lines) <= 256, "unbounded JSONL")
    return [obj(line+b"\n") for line in lines]

def unzip(data, expected_sha):
    require(is_sha(expected_sha) and sha(data) == expected_sha, "ZIP SHA-256 changed")
    require(0 < len(data) <= MAX_ZIP, "ZIP byte limit")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        infos = z.infolist()
        names = [f.filename for f in infos]
        require(len(names) == len(set(names)) and len(names) <= 48, "duplicate/unbounded ZIP paths")
        total = 0
        out = {}
        for f in infos:
            name = f.filename
            require(not name.startswith("/") and "\\" not in name and
                    not any(part in ("", ".", "..") for part in name.split("/")), "unsafe ZIP path")
            require(not f.is_dir() and not stat.S_ISLNK(f.external_attr >> 16) and
                    not (f.flag_bits & 1), "unsafe ZIP member")
            total += f.file_size
            require(0 < f.file_size <= MAX_EXPANDED and total <= MAX_EXPANDED, "ZIP expansion limit")
            out[name] = z.read(name)
        return out

def vector(v):
    require(type(v) is list and len(v) == 384 and all(
        type(x) in (int, float) and math.isfinite(x) and -8 <= x <= 8 for x in v),
        "invalid 384D real-model feature")
    return v

def cos(a, b):
    vector(a); vector(b)
    ab = math.fsum(x*y for x,y in zip(a,b))
    aa = math.fsum(x*x for x in a)
    bb = math.fsum(y*y for y in b)
    require(aa > 0 and bb > 0, "undefined feature cosine")
    return ab / math.sqrt(aa*bb)

def audit(source_zip, target_zip, producer_zip, evaluator_zip, pins):
    if type(pins) is not dict or set(pins) != {"source", "target", "producer", "evaluator"}:
        raise AuditError("exact complete four-artifact byte pins required")
    a,b,c,d = (unzip(content, pins[name]) for name, content in
                 (("source",source_zip),("target",target_zip),
                  ("producer",producer_zip),("evaluator",evaluator_zip)))
    source_manifest_bytes = a["source-manifest.json"]
    sm = obj(source_manifest_bytes)
    require(sm["schema"] == PREFIX+".source-plan" and
            sm["synthetic_data"] is True and sm["production_accepted"] is False and
            sm["model_selection_permitted"] is False and sm["authority"] == "DENY_ALL" and
            sm["training_cases"] == 16 and sm["future_cases"] == 8 and
            type(sm["file_sha256s"]) is dict and set(sm["file_sha256s"]) == SOURCE_NAMES,
            "SOURCE_MANIFEST_TARGET_HASH_EXPOSED_OR_INVALID")
    tm = obj(b["target-manifest.json"])
    require(tm["schema"] == PREFIX+".withheld-target-plan" and tm["synthetic_data"] is True and
            tm["source_manifest_sha256"] == sha(source_manifest_bytes) and
            tm["production_accepted"] is False and tm["authority"] == "DENY_ALL" and
            type(tm["file_sha256s"]) is dict and set(tm["file_sha256s"]) == TARGET_NAMES,
            "target manifest not exclusively evaluator-bound")
    for name, dig in sm["file_sha256s"].items():
        require(is_sha(dig) and sha(a["source/"+name]) == dig, "source file changed: "+name)
    for name, dig in tm["file_sha256s"].items():
        require(is_sha(dig) and sha(b[name]) == dig, "target file changed: "+name)
    train = jsonl(a["source/train_images.jsonl"],16)
    future = jsonl(a["source/future_images.jsonl"],8)
    targets = jsonl(b["future_class_targets.jsonl"],8)
    expected_source_members = ({"source-manifest.json"} |
                               {"source/" + name for name in SOURCE_NAMES} |
                               {"source/images/" + row["image_path"] for row in train+future})
    require(set(a) == expected_source_members,
            "SOURCE_ARTIFACT_CONTAINS_UNDECLARED_OR_WITHHELD_FILE")
    require(set(b) == TARGET_NAMES | {"target-manifest.json"},
            "evaluator-only target archive contains unapproved material")
    producer_members = {"bridge_fit.json", "future_bridge.jsonl", "granite_train/encoded.jsonl",
        "granite_train/receipt.json", "producer_receipt.json", "sealed_class_predictions.json",
        "sealed_geometry_predictions.json", "train_bridge.jsonl", "vision_future/features.jsonl",
        "vision_future/receipt.json", "vision_train/features.jsonl", "vision_train/receipt.json"}
    require(set(c) == producer_members, "producer archive contains unexpected label/target material")
    require(set(d) == {"class_independent_readout.json", "granite_future_targets/encoded.jsonl",
                       "geometry_independent_readout.json", "granite_future_targets/receipt.json"},
            "evaluator artifact inventory changed")
    for rec in train+future:
        digest = rec["image_sha256"]
        require(is_sha(digest) and sha(a["source/images/"+rec["image_path"]]) == digest,
                "actual image bytes changed")
        case_hash = sha(canonical(["hepta.e2.image-case.v1", rec["case_id"],rec["group_id"],
                                   rec["scope"],rec["observed_at"],rec["condition"],
                                   rec["image_sha256"],rec["question"]]))
        require(rec["source_sha256"] == case_hash, "image/question case identity drift")
    require({r["group_id"] for r in train}.isdisjoint({r["group_id"] for r in future}),
            "train/future source group collision")
    require(max(r["observed_at"] for r in train) < min(r["observed_at"] for r in future),
            "future timestamps not after train")
    require({r["image_sha256"] for r in train}.isdisjoint({r["image_sha256"] for r in future}),
            "image bytes reused")
    receipt = obj(c["producer_receipt.json"])
    require(receipt["schema"] == PREFIX+".producer-receipt" and receipt["synthetic_data"] is True and
            receipt["future_labels_seen"] is False and receipt["stem_selected"] is False and
            receipt["model_publisher_independently_authenticated"] is False and
            receipt["production_accepted"] is False and receipt["authority"] == "DENY_ALL" and
            receipt["dino_model_revision"] == DINO_REV and receipt["dino_model_weights_sha256"] == DINO_WEIGHTS and
            receipt["dino_train_forwards"] == 16 and receipt["dino_future_forwards"] == 8 and
            receipt["granite_model_revision"] == GRANITE_REV and
            type(receipt["granite_train_forwards"]) is int and receipt["granite_train_forwards"] >= 1,
            "producer model-source/count/authority mismatch")
    require(receipt["original_vision_source_sha256"] == sm["file_sha256s"]["train_images.jsonl"] and
            receipt["original_future_vision_source_sha256"] == sm["file_sha256s"]["future_images.jsonl"],
            "declared training/future source not actually used")
    for phase, expected_count, source_name in (("train",16,"train_images.jsonl"),
                                                ("future",8,"future_images.jsonl")):
        prefix = "vision_"+phase+"/"
        r = obj(c[prefix+"receipt.json"])
        raw = c[prefix+"features.jsonl"]
        require(r["encoder_revision"] == DINO_REV and
                r["snapshot_file_sha256s"]["model.safetensors"] == DINO_WEIGHTS and
                r["source_sha256"] == sm["file_sha256s"][source_name] and
                r["output_sha256"] == sha(raw) and
                r["actual_model_forwards"] == expected_count and r["image_count"] == expected_count and
                r["checkpoint_locally_byte_verified"] is True and
                r["labels_seen"] is False and r["production_accepted"] is False and
                r["publisher_authenticated"] is False and r["authority"] == "DENY_ALL",
                "visual physical receipt inconsistent")
        features=jsonl(raw,expected_count)
        expected_ids={r["case_id"] for r in (train if phase=="train" else future)}
        require({r["case_id"] for r in features} == expected_ids, "vision case coverage drift")
        for row in features:
            vector(row["source"]["values"])
            require(row["source"]["modality"] == "image", "not a vision feature")
    gtrain = obj(c["granite_train/receipt.json"])
    require(gtrain["model_revision"] == GRANITE_REV and
            gtrain["encoded_sha256"] == sha(c["granite_train/encoded.jsonl"]) and
            gtrain["model_checkpoint_locally_verified"] is True and
            gtrain["model_publisher_authenticated"] is False and
            gtrain["physical_forwards"] == receipt["granite_train_forwards"] and
            gtrain["production_accepted"] is False and gtrain["output_width"] == 384,
            "training Granite receipt mismatch")
    require(receipt["bridge_fit_sha256"] == sha(c["bridge_fit.json"]),
            "bridge fit artifact digest mismatch")
    bf=obj(c["bridge_fit.json"])
    require(bf["train_examples"] == 16 and bf["source_width"] == 384 and
            bf["target_width"] == 384 and bf["production_accepted"] is False,
            "wrong trained Bridge geometry/authority")
    gpbytes=c["sealed_geometry_predictions.json"]
    cpbytes=c["sealed_class_predictions.json"]
    require(receipt["sealed_geometry_predictions_sha256"] == sha(gpbytes) and
            receipt["sealed_class_predictions_sha256"] == sha(cpbytes),
            "unsealed or changed prediction artifact")
    gp=obj(gpbytes)
    cp=obj(cpbytes)
    require(cp["geometry_pred_sha256"] == sha(gpbytes) and cp["future_labels_seen"] is False and
            cp["production_accepted"] is False and cp["authority"] == "DENY_ALL" and
            cp["arms"] == list(ARMS), "class result not attached to sealed geometry")
    labels={r["case_id"]:r for r in targets}
    sources={r["case_id"]:r for r in future}
    require(len(labels)==len(sources)==8 and {r["case_id"] for r in cp["rows"]} == set(sources),
            "future class result incomplete")
    counted={arm:0 for arm in ARMS}
    paired={arm:{"rescued":0,"harmed":0,"both_correct":0,"both_wrong":0}
            for arm in ARMS if arm!="unaligned_identity"}
    for row in cp["rows"]:
        case=row["case_id"]
        truth=labels[case]
        src=sources[case]
        require(all(row[k]==src[k]==truth[k] for k in
                    ("case_id","group_id","scope","observed_at")) and
                row["source_input_sha256"]==src["image_sha256"]==truth["source_input_sha256"] and
                truth["source_sha256"]==src["source_sha256"] and
                set(row["predicted_labels"])==set(ARMS),"class case/source identity mismatch")
        correct={arm:row["predicted_labels"][arm]==truth["class_label"] for arm in ARMS}
        for arm in ARMS: counted[arm]+=int(correct[arm])
        for arm in paired:
            which=("rescued" if correct[arm] and not correct["unaligned_identity"] else
                   "harmed" if correct["unaligned_identity"] and not correct[arm] else
                   "both_correct" if correct[arm] else "both_wrong")
            paired[arm][which]+=1
    reported=obj(d["class_independent_readout.json"])
    require(reported["production_accepted"] is False and reported["authority"] == "DENY_ALL" and
            reported["cases"] == 8 and reported["three_future_windows_available"] is False and
            reported["complete_e2_five_arm_result"] is False,"unsafe independent readout")
    for row in reported["task_arms"]:
        a=row["arm"]
        require(a in ARMS and row["correct"]==counted[a] and row["total"]==8,
                "independent reported class accuracy disagrees with original data")
    for row in reported["paired_against_unaligned"]:
        require(row["arm"] in paired and all(row[k]==v for k,v in paired[row["arm"]].items()),
                "reported paired rescue/harm changed")
    rg=obj(d["granite_future_targets/receipt.json"])
    require(rg["model_revision"] == GRANITE_REV and
            rg["input_file_sha256"] == tm["file_sha256s"]["future_caption_targets.jsonl"] and
            rg["encoded_sha256"] == sha(d["granite_future_targets/encoded.jsonl"]) and
            rg["model_checkpoint_locally_verified"] is True and rg["production_accepted"] is False,
            "future Granite target authenticity/owner mismatch")
    ref={r["case_id"]:r["target"]["values"] for r in jsonl(d["granite_future_targets/encoded.jsonl"],8)}
    require(set(ref)==set(sources) and
            {r["case_id"] for r in gp["predictions"]}==set(sources),
            "geometry source/target case mismatch")
    ordered=sorted(gp["predictions"],key=lambda r:r["case_id"])
    targets_vec=[ref[r["case_id"]] for r in ordered]
    geom={}
    for arm in ARMS:
        vecs=[r["predictions"][arm] for r in ordered]
        sims=[cos(x,y) for x,y in zip(vecs,targets_vec)]
        errors=[math.fsum((x-y)**2 for x,y in zip(v,t))/384 for v,t in zip(vecs,targets_vec)]
        top1=sum(max(range(8),key=lambda j:(cos(v,targets_vec[j]),-j))==i
                 for i,v in enumerate(vecs))/8
        geom[arm]={"mean_cosine":math.fsum(sims)/8,
                   "mean_squared_error":math.fsum(errors)/8,
                   "within_cohort_retrieval_top1":top1}
    gres=obj(d["geometry_independent_readout.json"])
    require(gres["production_accepted"] is False and
            gres["physical_future_granite_forward_batches"] >= 1 and
            gres["predictions_sha256"] == sha(gpbytes) and
            gres["targets_sha256"] == rg["encoded_sha256"],
            "independent geometry source/readout not bound")
    for arm in ARMS:
        for metric,want in geom[arm].items():
            got=gres["arms"][arm][metric]
            require(type(got) in (int,float) and math.isfinite(got) and abs(got-want)<1e-10,
                    "independently recomputed geometry mismatch")
    return {"schema":PREFIX+".independent-archive-audit.v1",
            "source_sha256":pins["source"],"target_sha256":pins["target"],
            "producer_sha256":pins["producer"],"evaluator_sha256":pins["evaluator"],
            "pre_fix_target_hash_leak_rejected":True,
            "source_target_hash_isolated":True,
            "actual_model_receipts_consistent":True,
            "independently_attested_execution":False,
            "synthetic_classes_correct":counted,
            "paired_against_unaligned":paired,
            "geometry":geom,
            "true_natural_image_ability_proven":False,
            "future_three_windows_proven":False,
            "production_accepted":False,"authority":"DENY_ALL"}

def main():
    p=argparse.ArgumentParser()
    for k in ("source","target","producer","evaluator"):
        p.add_argument("--"+k,required=True,type=Path)
        p.add_argument("--"+k+"-sha256",required=True)
    args=p.parse_args()
    byte_map={k:getattr(args,k).read_bytes() for k in ("source","target","producer","evaluator")}
    print(json.dumps(audit(*(byte_map[k] for k in ("source","target","producer","evaluator")),
                           {k:getattr(args,k+"_sha256") for k in byte_map}),sort_keys=True))

if __name__ == '__main__':
    main()
