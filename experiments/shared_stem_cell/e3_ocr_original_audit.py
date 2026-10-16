"""Original-sample-only independent OCR vs Granite text accuracy audit.

No producer, training, Tesseract, model or reviewer code is imported.
Only original real physical predictions are consumed, AFTER both source
prediction digests have been pinned and the evaluator re-staged the exact
historical source and opened original held TEST targets separately.
DENY_ALL / not prospective / no model selection.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from collections import Counter
from math import comb,fsum
from pathlib import Path

ORIGINAL_SHA="e6354f38de4292dda60ebab380cb13d488853b9c08371e54f8f1762827febaf7"
OCR_SHA="96ba4117a37689eeafe2415661e028a9170b7ccdd8c345b6b8d6241b7a928885"
SOURCE_SHA="a561916c7d56b6677c5511c329a49bbeec94879f019d29f159ff59be83359202"
OCR_MODEL=("ibm-granite/granite-embedding-97m-multilingual-r2","835ad14087e140460703cf0fae09f97d469d65c2")
SCHEMA="hepta.e3-ocr-original-independent-heldout-review.v1"

class OriginalOcrError(ValueError):
    pass

def require(ok, why):
    if not ok:raise OriginalOcrError(why)

def sha(raw):return hashlib.sha256(raw).hexdigest()

def sha64(val):return type(val) is str and len(val)==64 and all(ch in "0123456789abcdef" for ch in val)

def no_duplicates(pairs):
    x={}
    for k,v in pairs:
        require(k not in x,"duplicate JSON key")
        x[k]=v
    return x

def parse(raw):
    def no_constant(value):raise OriginalOcrError("nonfinite JSON constant "+value)
    return json.loads(raw,object_pairs_hook=no_duplicates,parse_constant=no_constant)

def pinned(path,expected,maximum=4*1024*1024):
    require(sha64(expected),"unsafe exact source digest")
    path=Path(path)
    require(path.is_file() and not path.is_symlink() and 0<path.stat().st_size<=maximum,
            "unavailable/oversized model source or label")
    buf=path.read_bytes()
    require(sha(buf)==expected,"original source digest mismatch")
    return buf

def prob(x):
    require(type(x) is list and len(x)==4 and
            all(type(v) in (float,int) and math.isfinite(v) and 0<=v<=1 for v in x)
            and abs(fsum(x)-1)<1e-6,"unsafe original probability")
    return x

def exact_p(harmed,rescued):
    n=harmed+rescued
    return min(1.,2*sum(comb(n,i) for i in range(min(harmed,rescued)+1))/2**n) if n else 1.

def outcome(original,ocr,held):
    require(type(original) is dict and type(ocr) is dict and
            original.get("schema")=="hepta.e3-granite-dinov2-scienceqa.v1.sealed-predictions" and
            ocr.get("schema")=="hepta.e3.ocr-granite-physical.v1" and
            original.get("production_accepted") is False and
            original.get("held_labels_visible_to_inference") is False and
            original.get("independent_ground_truth_observer") is False and
            ocr.get("production_accepted") is False and
            ocr.get("stem_selected") is False and
            ocr.get("authority")=="DENY_ALL" and
            ocr.get("signed_model_origin_authenticated") is False,
            "unqualified original Model/OCR inputs")
    require(original.get("source_sha256")==ocr.get("source_sha256")==SOURCE_SHA,
            "not identical original ScienceQA source")
    model=ocr.get("model")
    require(type(model) is dict and
            (model.get("repo"),model.get("revision"))==OCR_MODEL and
            sha64(model.get("pipeline_digest")), "unknown original pretrained Granite")
    require(ocr.get("ocr_engine")=="tesseract" and
            type(ocr.get("physical_ocr_calls")) is int and
            ocr["physical_ocr_calls"]==192 and
            type(ocr.get("ocr_nonempty_cases")) is int and
            0<=ocr["ocr_nonempty_cases"]<=192 and
            type(ocr.get("physical_granite_forward_batches")) is int and
            ocr["physical_granite_forward_batches"]==60 and
            ocr.get("actual_original_pretrained_forward_self_reported") is True,
            "unexecuted/forged complete OCR and original Granite batch coverage")
    require(type(original.get("physical_text_forward_batches")) is int and
            original["physical_text_forward_batches"]>0,"missing real original text forward")
    refs=original.get("predictions")
    others=ocr.get("rows")
    require(type(refs) is list and len(refs)==64 and
            type(others) is list and len(others)==64 and
            type(held) is list and len(held)==64, "incomplete original 64 TEST panel")
    control={}
    for row in refs:
        require(type(row) is dict and set(row)=={
            "id","group","split","source_input_sha256","arms"} and
            row.get("split")=="test" and sha64(row.get("id")) and
            sha64(row.get("group")) and sha64(row.get("source_input_sha256")) and
            row["id"] not in control and type(row["arms"]) is dict and
            "text_only" in row["arms"],"unbound/duplicate original text result")
        control[row["id"]]=row
    images={}
    for row in others:
        require(type(row) is dict and set(row)=={
            "id","group","source_input_sha256","probabilities"} and
            sha64(row.get("id")) and sha64(row.get("group")) and
            sha64(row.get("source_input_sha256")) and row["id"] not in images,
            "unbound/duplicate original real OCR prediction")
        prob(row["probabilities"])
        images[row["id"]]=row
    labels={}
    for row in held:
        require(type(row) is dict and set(row)=={"id","group","split","label"} and
                row.get("split")=="test" and sha64(row.get("id")) and
                sha64(row.get("group")) and
                type(row.get("label")) is int and 0<=row["label"]<4 and
                row["id"] not in labels, "unsafe original held TEST label")
        labels[row["id"]]=row
    require(set(control)==set(images)==set(labels),"OCR/text/labels not same original cohort")
    correct={"text_only":0,"ocr_text":0}
    brier={"text_only":[],"ocr_text":[]}
    rescues=harms=both_correct=both_wrong=0
    for rid,row in control.items():
        x=images[rid]
        lab=labels[rid]
        require(row["group"]==x["group"]==lab["group"] and
                row["source_input_sha256"]==x["source_input_sha256"],
                "original OCR and text source/group mismatch")
        decision=[]
        for arm,values in (("text_only",row["arms"]["text_only"]),
                           ("ocr_text",x["probabilities"])):
            p=prob(values)
            y=lab["label"]
            good=int(max(range(4),key=lambda k:(p[k],-k))==y)
            correct[arm]+=good
            decision.append(good)
            brier[arm].append(fsum((p[k]-int(k==y))**2 for k in range(4))/4)
        both_correct+=int(decision==[1,1]);both_wrong+=int(decision==[0,0])
        rescues+=int(decision==[0,1]);harms+=int(decision==[1,0])
    require(both_correct+both_wrong+rescues+harms==64,"paired original decision partition")
    return {"schema":SCHEMA,"original_text_predictions_sha256":ORIGINAL_SHA,
        "actual_ocr_predictions_sha256":OCR_SHA,"original_held_labels_sha256":None,
        "source_sha256":SOURCE_SHA,"cases":64,"ocr_calls":ocr["physical_ocr_calls"],
        "ocr_nonempty_cases":ocr["ocr_nonempty_cases"],
        "ocr_granite_forward_batches":ocr["physical_granite_forward_batches"],
        "correct":correct,"accuracy":{k:v/64 for k,v in correct.items()},
        "brier":{k:fsum(v)/64 for k,v in brier.items()},
        "rescued_errors":rescues,"new_errors":harms,
        "both_correct":both_correct,"both_wrong":both_wrong,
        "mcnemar_two_sided_exact_unadjusted_p":exact_p(harms,rescues),
        "training_labels_visible_to_scorer":False,
        "historical_public_not_future":True,
        "original_label_owner_independently_authenticated":False,
        "original_model_publisher_signature_authenticated":False,
        "visual_necessity_adjudicated":False,"energy_joules":None,
        "stem_winner":None,"production_accepted":False,"authority":"DENY_ALL"}

def main():
    a=argparse.ArgumentParser(description=__doc__)
    for name in ("original","ocr","held","output"):
        a.add_argument("--"+name,required=True,type=Path)
    a.add_argument("--held-sha256",required=True)
    args=a.parse_args()
    original=parse(pinned(args.original,ORIGINAL_SHA))
    ocr=parse(pinned(args.ocr,OCR_SHA))
    held=[parse(line) for line in pinned(args.held,args.held_sha256).splitlines()]
    result=outcome(original,ocr,held)
    result["original_held_labels_sha256"]=args.held_sha256
    output=args.output
    require(not output.exists() and not output.is_symlink(),"non-overwrite independent score required")
    with output.open("x",encoding="utf-8") as stream:
        stream.write(json.dumps(result,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n")
        stream.flush()
        os.fsync(stream.fileno())
    print("ORIGINAL_REAL_OCR_PAIR_ONLY_DESCRIPTIVE_PASS; DENY_ALL")
    print("OCR correct:",result["correct"]["ocr_text"],
          "text correct:",result["correct"]["text_only"],
          "paired exact p:",result["mcnemar_two_sided_exact_unadjusted_p"])

if __name__=="__main__":
    main()
