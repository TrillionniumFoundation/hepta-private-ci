"""Original-label-blind Tesseract OCR -> frozen Granite97 ScienceQA arm.

Only genuine ORIGINAL source image bytes, a working Tesseract executable and
publisher-pinned Granite weights qualify. Train/test targets are never loaded.
No fake model, synthetic fallback, unsigned authority or Stem promotion.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import time

from e3_scienceqa_contract import (E3Error, GRANITE, MAX_ROWS, canonical, read_jsonl,
                                   read_pinned, sha, unit_probabilities, validate_source,
                                   write_new)
from e3_granite_dino_real import verified_acquisition, input_prompts

OCR_SCHEMA = "hepta.e3.ocr-granite-physical.v1"

def require(condition, reason):
    if not condition:
        raise E3Error(reason)

def ocr_text(raw: bytes, *, runner=subprocess.run):
    """No artificial OCR features. Empty real OCR output remains a real negative."""
    require(type(raw) is bytes and 0 < len(raw) <= 8*1024*1024,
            "original image bytes required for OCR")
    started = time.perf_counter_ns()
    try:
        outcome = runner(
            ["tesseract", "stdin", "stdout", "-l", "eng", "--psm", "6"],
            input=raw, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise E3Error("physical original OCR failed or timed out") from exc
    require(outcome.returncode == 0 and
            type(outcome.stdout) is bytes and len(outcome.stdout) <= 65536,
            "original Tesseract execution incomplete")
    try:
        text = outcome.stdout.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise E3Error("invalid OCR UTF-8") from exc
    text = " ".join(text.split())
    require(len(text.encode()) <= 2048, "OCR output beyond bounded text input")
    return text, time.perf_counter_ns()-started

def extract_sources(rows, image_root, *, runner=subprocess.run):
    require(1 <= len(rows) <= MAX_ROWS, "unsupported source count")
    names = set()
    revised=[]
    elapsed = 0
    nonempty=0
    ocr_evidence=[]
    for row in rows:
        image_name = row["image"]
        if image_name not in names:
            names.add(image_name)
        image_path = Path(image_root) / image_name
        raw = read_pinned(image_path, image_name, maximum=8*1024*1024)
        text, ns=ocr_text(raw, runner=runner)
        elapsed += ns
        nonempty += bool(text)
        modified = dict(row)
        # In case no OCR text is visible, use the EXACT original text prompt.
        # Do not claim the OCR-only arm uses meaningful image evidence.
        if text:
            modified["hint"] = (row["hint"] + "\n" if row["hint"] else "") + "Image OCR: " + text
        revised.append(modified)
        ocr_evidence.append([row["id"], sha(text.encode()), bool(text)])
    require(len(revised)==len(rows) and len(ocr_evidence)==len(rows),
            "missing Tesseract on original source")
    return revised,{"physical_ocr_calls":len(rows),
                    "ocr_nonempty_cases":nonempty,
                    "ocr_source_text_sha256":sha(canonical(ocr_evidence)),
                    "ocr_wall_ns":elapsed,
                    "ocr_engine":"tesseract"}

def run_original(rows, ocr_rows, *, encoder):
    """Count every real Granite tokenizer/model forward for the changed view."""
    import torch
    import torch.nn.functional as F
    require(len(rows)==len(ocr_rows)==192, "must evaluate original 96/32/64 panel")
    prompts = [text for row in ocr_rows for text in input_prompts(row)]
    packed=[]
    for idx in range(0,len(prompts),16):
        chunk=prompts[idx:idx+16]
        tensor=encoder.encode(chunk,pooling="cls-first-token")
        require(tensor.shape==(len(chunk),384) and
                bool(torch.isfinite(tensor).all()), "original Granite embedding not materialized")
        packed.append(tensor)
    bank=F.normalize(torch.cat(packed).view(len(rows),5,384),dim=-1)
    require(bank.shape==(192,5,384), "original OCR-aware full source feature bank missing")
    result=[]
    for i,row in enumerate(rows):
        if row["split"]!="test":
            continue
        scores=torch.mv(bank[i,1:],bank[i,0])
        result.append({"id":row["id"],"group":row["group"],
                       "source_input_sha256":sha(canonical(row)),
                       "probabilities":unit_probabilities((scores*8).tolist())})
    require(len(result)==64, "missing original OCR TEST result")
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--source-sha256",required=True)
    parser.add_argument("--images",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    source=read_jsonl(args.source,args.source_sha256)
    validate_source(source)
    require(args.images.is_dir() and not args.images.is_symlink(),
            "original media directory required")
    require(not args.out.exists(), "result must be create-only")
    started=time.perf_counter_ns()
    ocr_rows,ocr_receipt=extract_sources(source,args.images)
    import torch
    from execution import LocalEncoder
    args.out.mkdir(parents=True,exist_ok=False)
    (args.out/"weights-not-artifacts").mkdir()
    root=args.out/"weights-not-artifacts"/"granite"
    model_manifest=verified_acquisition(*GRANITE,root)
    with torch.inference_mode():
        encoder=LocalEncoder(root,model_manifest,maximum_tokens=512)
        identity=encoder.identity
        rows=run_original(source,ocr_rows,encoder=encoder)
        forward=encoder.forward_calls
        encoder.close()
    require(type(forward) is int and forward>0 and len(rows)==64,
            "original model never physically executed")
    evidence={"schema":OCR_SCHEMA,
              "source_sha256":args.source_sha256,
              "model":{"repo":GRANITE[0],"revision":GRANITE[1],
                       "pipeline_digest":identity},
              "ocr_engine":"tesseract",
              "physical_ocr_calls":ocr_receipt["physical_ocr_calls"],
              "ocr_nonempty_cases":ocr_receipt["ocr_nonempty_cases"],
              "ocr_source_text_sha256":ocr_receipt["ocr_source_text_sha256"],
              "physical_granite_forward_batches":forward,
              "ocr_wall_ns":ocr_receipt["ocr_wall_ns"],
              "full_model_acquisition_and_ocr_wall_ns":time.perf_counter_ns()-started,
              "process_peak_rss_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              "rows":rows,
              "actual_original_pretrained_forward_self_reported":True,
              "production_accepted":False,"stem_selected":False,
              "signed_model_origin_authenticated":False,"authority":"DENY_ALL"}
    write_new(args.out/"sealed-ocr-predictions.json",evidence)
    print(json.dumps({"cases":len(rows),"nonempty_ocr":ocr_receipt["ocr_nonempty_cases"],
                      "forward_batches":forward,"production_promotion":"DENY_ALL"},
                     sort_keys=True))

if __name__=="__main__":
    main()
