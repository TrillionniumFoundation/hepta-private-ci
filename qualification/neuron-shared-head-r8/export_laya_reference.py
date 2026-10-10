#!/usr/bin/env python3
"""Optional real Laya choice-probability exporter for R8 experiment 02.

No network or implicit Hub download is permitted. Requires locally provisioned,
hash-pinned Laya weights and an explicitly qualified, disjoint future dataset.
Does not extract arbitrary shared embeddings or attest execution cryptographically.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import time

SCHEMA = "hepta.neuron.head-experiments.v1"
INPUT_SCHEMA = "hepta.neuron.laya-choice-input.v1"


def digest(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda:stream.read(1048576),b""):
            h.update(part)
    return h.hexdigest()


def validate_input(data: dict) -> tuple[list, dict, list[str]]:
    if data.get("schema")!=INPUT_SCHEMA or not isinstance(data.get("rows"),list) or not data["rows"]:
        raise ValueError("missing real future dataset")
    qid=data.get("question_id")
    question=data.get("question")
    if not isinstance(qid,str) or not qid or not isinstance(question,dict) or question.get("type")!="choice":
        raise ValueError("fixed typed choice question required")
    criteria=question.get("criteria")
    if not isinstance(criteria,dict) or len(criteria)<2 or len(criteria)>128:
        raise ValueError("invalid bounded complete choice set")
    keys=list(criteria)
    if not all(isinstance(k,str) and k and isinstance(criteria[k],str) for k in keys):
        raise ValueError("invalid typed choice criteria")
    seen=set()
    for row in data["rows"]:
        if not all(k in row for k in ("id","group","time","state")):
            raise ValueError("missing future event identity or state")
        if not isinstance(row["id"],str) or not isinstance(row["group"],str) or not row["id"] or not row["group"]:
            raise ValueError("invalid event identity")
        if row["id"] in seen:
            raise ValueError("duplicate event")
        seen.add(row["id"])
        if not isinstance(row["time"],int) or row["time"]<=0:
            raise ValueError("invalid time index")
        if isinstance(row["state"],str) and not row["state"]:
            raise ValueError("empty state")
    old=set(map(str,data.get("train_groups",[]))) | set(map(str,data.get("valid_groups",[])))
    if old & {x["group"] for x in data["rows"]}:
        raise ValueError("future source-group overlap")
    if not isinstance(data.get("valid_time_max"),int) or min(row["time"] for row in data["rows"])<=data["valid_time_max"]:
        raise ValueError("future window must follow validation")
    return data["rows"],{qid:question},keys


def convert_predictions(rows: list, replies: list, qid: str, keys: list[str]) -> list[dict]:
    if len(replies)!=len(rows):
        raise ValueError("missing batch reply")
    output=[]
    for event,result in zip(rows,replies):
        usage=result.get("usage")
        if not isinstance(usage,dict) or "truncated" not in usage or usage["truncated"] or usage.get("state_tokens_dropped"):
            raise ValueError("Laya input truncated or evidence missing")
        if usage.get("options"):
            raise ValueError("Laya option budget ambiguity")
        answer=result.get("answers",{}).get(qid,{})
        if answer.get("type")!="choice" or answer.get("low_confidence") or answer.get("abstention"):
            raise ValueError("missing eligible typed choice")
        values=answer.get("probabilities")
        if not isinstance(values,dict) or set(values)!=set(keys):
            raise ValueError("missing or extra option probabilities")
        p=[float(values[k]) for k in keys]
        if not all(math.isfinite(v) and v>=0 for v in p) or abs(sum(p)-1)>0.002:
            raise ValueError("invalid calibrated distribution")
        # The Laya SDK rounds displayed probabilities. Preserve observed values;
        # normalize only the rounding residual, never silently collapse options.
        p=[v/sum(p) for v in p]
        output.append({"id":event["id"],"group":event["group"],"time":event["time"],"probabilities":p})
    return output


def run(args):
    local=Path(args.checkpoint).resolve()
    if not local.is_dir():
        raise ValueError("Laya checkpoint must be a local pinned directory")
    weights=local/"model.safetensors"
    if not weights.is_file():
        raise ValueError("missing local model.safetensors")
    expected=json.loads(Path(args.digests).read_text(encoding="utf-8"))
    if not isinstance(expected,dict) or not expected.get("model.safetensors"):
        raise ValueError("weights digest pin required")
    for path,hash_value in expected.items():
        if Path(path).is_absolute() or ".." in Path(path).parts or len(hash_value)!=64:
            raise ValueError("invalid artifact pin")
        file=(local/path).resolve()
        if local not in file.parents or not file.is_file() or digest(file)!=hash_value:
            raise ValueError("model artifact missing or digest mismatch")
    raw=Path(args.input)
    data=json.loads(raw.read_text(encoding="utf-8"))
    rows,questions,keys=validate_input(data)
    os.environ["HF_HUB_OFFLINE"]="1"
    os.environ["TRANSFORMERS_OFFLINE"]="1"
    os.environ["USE_TF"]="0"
    try:
        import laya
    except ImportError as error:
        raise RuntimeError("install version-pinned laya package in offline test host") from error
    agent=laya.Agent(model_id_or_path=str(local),device=args.device,backend="eager",expected_sha256=expected)
    started=time.perf_counter()
    reply=agent.predict_batch([r["state"] for r in rows],questions,batch_size=args.batch_size)
    elapsed=time.perf_counter()-started
    predictions=convert_predictions(rows,reply,data["question_id"],keys)
    value={
        "schema":SCHEMA,"arm":"laya_original","backend":"laya_original_model",
        "model_file_sha256":expected["model.safetensors"],"artifact_manifest_sha256":digest(Path(args.digests)),
        "input_sha256":digest(raw),"encoder_digest":data.get("encoder_digest"),
        "scope_digest":data.get("scope_digest"),"train_groups":data.get("train_groups",[]),
        "valid_groups":data.get("valid_groups",[]),"valid_time_max":data["valid_time_max"],
        "question_id":data["question_id"],"choice_order":keys,"batch_size":args.batch_size,
        "model_execution_seconds":elapsed,"rows":predictions,"production_admitted":False,
        "authenticity":"UNATTESTED_SHADOW_EXPORT",
    }
    Path(args.output).write_text(json.dumps(value,sort_keys=True,indent=2)+"\n",encoding="utf-8")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--checkpoint",required=True)
    p.add_argument("--digests",required=True)
    p.add_argument("--input",required=True)
    p.add_argument("--output",required=True)
    p.add_argument("--device",default="cpu")
    p.add_argument("--batch-size",type=int,default=8)
    args=p.parse_args()
    if args.batch_size<1 or args.batch_size>128:
        raise ValueError("bounded 1..128 batch size required")
    run(args)

if __name__=="__main__":
    main()
