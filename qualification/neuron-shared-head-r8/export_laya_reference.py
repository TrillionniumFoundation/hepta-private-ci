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
    if not isinstance(question.get("instructions"),str) or not question["instructions"].strip():
        raise ValueError("Laya requires explicit pinned question instructions")
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
        # Pinned Laya 'c7527708...' exposes token counts but no truncation flag.
        # Full-input status is independently established BEFORE system_one.
        if not isinstance(usage,dict) or not isinstance(usage.get("input_tokens"),int) or usage["input_tokens"]<=0:
            raise ValueError("Laya usage identity missing")
        if usage.get("truncated") or usage.get("state_tokens_dropped"):
            raise ValueError("Laya input truncated")
        if usage.get("options"):
            raise ValueError("Laya option budget ambiguity")
        answer=result.get("answers",{}).get(qid,{})
        if answer.get("type")!="choice" or answer.get("low_confidence") or answer.get("abstention"):
            raise ValueError("missing eligible typed choice")
        values=answer.get("probabilities")
        if not isinstance(values,dict) or set(values)!=set(keys):
            raise ValueError("missing or extra option probabilities")
        p=[float(values[k]) for k in keys]
        if not all(math.isfinite(v) and v>=0 for v in p) or sum(p)<=0 or abs(sum(p)-1)>0.002:
            raise ValueError("invalid calibrated distribution")
        # The Laya SDK rounds displayed probabilities. Preserve observed values;
        # normalize only the rounding residual, never silently collapse options.
        p=[v/sum(p) for v in p]
        output.append({"id":event["id"],"group":event["group"],"time":event["time"],"probabilities":p})
    return output


PINNED_SDK_COMMIT = "c7527708f9f5220c669d8aa385077cd28d04708a"


def check_pinned_checkpoint(local: Path, manifest_path: Path) -> dict:
    """Every local checkpoint file must be present and hashed in the immutable manifest."""
    if not local.is_dir():
        raise ValueError("Laya checkpoint must be a local pinned directory")
    expected=json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(expected,dict) or "model.safetensors" not in expected or "rl_agent_config.json" not in expected:
        raise ValueError("weights and model config digest pins required")
    actual={str(p.relative_to(local)) for p in local.rglob("*") if p.is_file()}
    if any(p.is_symlink() for p in local.rglob("*")):
        raise ValueError("symlink inside pinned Laya checkpoint")
    if set(expected)!=actual:
        raise ValueError("all checkpoint/tokenizer/encoder files must be pinned, no extras")
    for path,hash_value in expected.items():
        p=Path(path)
        if p.is_absolute() or ".." in p.parts or not isinstance(hash_value,str) or len(hash_value)!=64:
            raise ValueError("invalid artifact pin")
        file=(local/p).resolve()
        if local not in file.parents or not file.is_file() or digest(file)!=hash_value:
            raise ValueError("model artifact missing or digest mismatch")
    return expected


def preflight_full_context(agent, state, question: dict) -> None:
    """Mirror pinned Laya c752... build_sequence clipping checks, fail closed.

    The pinned public system_one() returns 'input_tokens' only, not 'truncated'.
    We reject any case where its actual sequence builder would truncate
    instructions, any single option, or any state tokens.
    """
    from laya.common import render_options, serialize_state
    q=agent._to_internal(question)
    tok=agent.tok
    mask=tok.mask_token
    raw_head=tok("%s question: %s"%(q["t"],str(q["ins"]).replace(mask," ")),
                 add_special_tokens=False)["input_ids"]
    options=render_options(q)
    opt_ids=[]
    for text in options:
        ids=tok(" "+text.replace(mask," "),add_special_tokens=False)["input_ids"]
        if len(ids)>48:
            raise ValueError("Laya option text exceeds pinned head token cap")
        opt_ids.append([tok.mask_token_id]+ids)
    head_max_len=int(agent.cfg.get("head_max_len",192))
    max_len=int(agent.cfg.get("max_len",512))
    budget=head_max_len-sum(map(len,opt_ids))
    if budget<16 or len(raw_head)>max(8,budget):
        raise ValueError("Laya question/choice head would be truncated")
    prefix=1+len(raw_head)+1+sum(map(len,opt_ids))+1
    room=max_len-prefix-1
    tokens=tok(serialize_state(state).replace(mask," "),
               add_special_tokens=False)["input_ids"]
    if room<=0 or len(tokens)>room:
        raise ValueError("Laya state input would be truncated")


def run(args):
    local=Path(args.checkpoint).resolve()
    manifest_path=Path(args.digests)
    expected=check_pinned_checkpoint(local,manifest_path)
    raw=Path(args.input)
    data=json.loads(raw.read_text(encoding="utf-8"))
    rows,questions,keys=validate_input(data)
    os.environ["HF_HUB_OFFLINE"]="1"
    os.environ["TRANSFORMERS_OFFLINE"]="1"
    os.environ["USE_TF"]="0"
    try:
        import importlib
        module=importlib.import_module("laya.agent")
        common=importlib.import_module("laya.common")
    except ImportError as error:
        raise RuntimeError("install the source-pinned Laya SDK on the offline test host") from error
    sdk_expected=json.loads(Path(args.sdk_digests).read_text(encoding="utf-8"))
    if not isinstance(sdk_expected,dict) or sdk_expected.get("source_commit")!=PINNED_SDK_COMMIT:
        raise ValueError("SDK source commit pin missing or different")
    if digest(Path(module.__file__))!=sdk_expected.get("agent_py_sha256") or digest(Path(common.__file__))!=sdk_expected.get("common_py_sha256"):
        raise ValueError("installed Laya SDK does not match source-pinned code")
    # Pinning all weights and configs is required because this older SDK has
    # neither an expected_sha256 constructor argument nor a predict_batch API.
    agent=module.Agent(model_id_or_path=str(local),device=args.device)
    check_pinned_checkpoint(local,manifest_path)  # SDK must not mutate pinned config
    started=time.perf_counter()
    replies=[]
    for row in rows:
        preflight_full_context(agent,row["state"],questions[data["question_id"]])
        replies.append(agent.system_one(row["state"],questions))
    elapsed=time.perf_counter()-started
    check_pinned_checkpoint(local,manifest_path)
    predictions=convert_predictions(rows,replies,data["question_id"],keys)
    value={
        "schema":SCHEMA,"arm":"laya_original","backend":"laya_original_model",
        "model_file_sha256":expected["model.safetensors"],"artifact_manifest_sha256":digest(manifest_path),
        "input_sha256":digest(raw),"encoder_digest":data.get("encoder_digest"),
        "scope_digest":data.get("scope_digest"),"train_groups":data.get("train_groups",[]),
        "valid_groups":data.get("valid_groups",[]),"valid_time_max":data["valid_time_max"],
        "question_id":data["question_id"],"choice_order":keys,"source_commit":PINNED_SDK_COMMIT,
        "sdk_manifest_sha256":digest(Path(args.sdk_digests)),
        "execution_mode":"pinned_system_one_sequential","model_execution_seconds":elapsed,
        "rows":predictions,"production_admitted":False,
        "authenticity":"UNATTESTED_SHADOW_EXPORT",
    }
    output=Path(args.output)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(value,sort_keys=True,indent=2)+"\n",encoding="utf-8")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--checkpoint",required=True)
    p.add_argument("--digests",required=True)
    p.add_argument("--sdk-digests",required=True)
    p.add_argument("--input",required=True)
    p.add_argument("--output",required=True)
    p.add_argument("--device",default="cpu")
    args=p.parse_args()
    run(args)

if __name__=="__main__":
    main()
