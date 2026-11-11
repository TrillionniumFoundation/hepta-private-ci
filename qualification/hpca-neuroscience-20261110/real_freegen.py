#!/usr/bin/env python3
"""Frozen, genuine CPU greedy-generation diagnostic on the already-public OOD plan.

Research-only: no independent evaluator, owner attestation, action/effect,
NoUpdate execution, production permissions, or efficacy claim.
"""
import argparse
import datetime as dt
import gc
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import time

import native_lora_ood_probe as prior

EXPECTED_TWO_CHOICE_SHA = "3002553ec485b19247f510863e9c78d2cce7747434ad7737f68b7dd3f9a74a2a"
SCHEMA = "HPCA-V2-REAL-CPU-GREEDY-GEN-1"
SEEDS = (11, 17, 23, 29)
ARMS = ("interleaved", "bursty")
MAX_NEW_TOKENS = 8

def parse_leading_answer(text):
    # Do not postprocess reasoning or extract a convenient buried label.
    m = re.match(r"^\s*(yes|no)(?=$|[^A-Za-z])", text, flags=re.IGNORECASE)
    return m.group(1).lower() if m else None

def check_previous(path, tasks):
    if prior.sha256(path) != EXPECTED_TWO_CHOICE_SHA:
        raise ValueError("previous actual OOD result changed")
    data = json.loads(Path(path).read_text())
    expected = ["base"] + [f"seed{s} {a}" for s in SEEDS for a in ARMS]
    if data.get("schema") != prior.SCHEMA or data.get("conditions") != expected:
        raise ValueError("previous conditions mismatch")
    if len(data.get("runs", [])) != 9:
        raise ValueError("previous run count")
    expected_ids = {t["id"] for t in tasks}
    output = {}
    for run in data["runs"]:
        rows = run.get("predictions", [])
        ids = [r.get("id") for r in rows]
        if len(rows) != 24 or set(ids) != expected_ids:
            raise ValueError("previous per-run task roster")
        if run["condition"] in output:
            raise ValueError("duplicated previous condition")
        output[run["condition"]] = {r["id"]:r for r in rows}
    if set(output) != set(expected):
        raise ValueError("previous conditions absent")
    return output

def choose_model(base_model_dir, adapter_root, cond, seed, arm):
    from peft import PeftModel
    from transformers import AutoModelForCausalLM
    model = AutoModelForCausalLM.from_pretrained(
        base_model_dir, local_files_only=True, dtype=__import__("torch").float32,
        attn_implementation="eager")
    if seed is not None:
        model = PeftModel.from_pretrained(
            model, adapter_root / f"seed{seed}-{arm}-adapter", is_trainable=False)
    return model.eval()

def evaluate(model, tok, tasks, reference):
    import torch
    rows = []
    with torch.inference_mode():
        for task in tasks:
            prompt = task["question"].strip()+"\nAnswer:"
            x = tok(prompt, return_tensors="pt", add_special_tokens=True)
            t0=time.perf_counter()
            output = model.generate(
                **x, do_sample=False, num_beams=1, max_new_tokens=MAX_NEW_TOKENS,
                pad_token_id=tok.eos_token_id, use_cache=True)
            elapsed = time.perf_counter()-t0
            emitted = output[0][x["input_ids"].shape[1]:]
            decoded = tok.decode(emitted, skip_special_tokens=True)
            parsed = parse_leading_answer(decoded)
            ref = reference[task["id"]]
            if ref["truth"] != task["truth"] or ref["family"] != task["family"]:
                raise ValueError("changed label/family vs frozen two-choice reference")
            if ref["prompt_sha256"] != hashlib.sha256(prompt.encode()).hexdigest():
                raise ValueError("prompt changed vs frozen two-choice reference")
            rows.append({
                "id":task["id"],"family":task["family"],"truth":task["truth"],
                "generated_text":decoded,"parsed":parsed,"valid":parsed is not None,
                "correct":parsed==task["truth"],"tokens":int(emitted.numel()),
                "generate_wall_seconds":elapsed,
                "two_choice_prediction":ref["prediction"],
                "same_as_two_choice":parsed==ref["prediction"],
            })
    return rows

def main():
    ap=argparse.ArgumentParser()
    for key in ("plan","archive","previous","model","adapter_root","out"):
        ap.add_argument("--"+key.replace("_","-"),type=Path,required=True)
    ap.add_argument("--threads",type=int,default=4)
    args=ap.parse_args()
    if args.out.exists(): raise FileExistsError("output exists")
    if not (1 <= args.threads <= 8): raise ValueError("invalid CPU threads")
    plan=json.loads(args.plan.read_text())
    tasks=prior.check_plan(plan)
    archive=json.loads(args.archive.read_text())
    prior.check_archive(archive,args.archive,args.model,args.adapter_root)
    reference=check_previous(args.previous,tasks)
    os.environ["CUDA_VISIBLE_DEVICES"]=""
    os.environ["HF_HUB_OFFLINE"]="1"
    os.environ["TRANSFORMERS_OFFLINE"]="1"
    import torch
    from transformers import AutoTokenizer
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    if torch.cuda.is_available(): raise RuntimeError("GPU unexpectedly active")
    tok=AutoTokenizer.from_pretrained(args.model,local_files_only=True)
    t0=time.perf_counter(); cpu0=time.process_time(); io0=prior.io_counts()
    stamp=dt.datetime.now(dt.timezone.utc).isoformat()
    conditions=[("base",None,None)]+[(f"seed{s} {arm}",s,arm) for s in SEEDS for arm in ARMS]
    runs=[]
    for condition,seed,arm in conditions:
        start=time.perf_counter(); cpustart=time.process_time()
        model=choose_model(args.model,args.adapter_root,condition,seed,arm)
        load=time.perf_counter()-start
        inf=time.perf_counter()
        rows=evaluate(model,tok,tasks,reference[condition])
        infer=time.perf_counter()-inf
        valid=sum(r["valid"] for r in rows)
        correct=sum(r["correct"] for r in rows)
        agreement=sum(r["same_as_two_choice"] for r in rows)
        runs.append({
            "condition":condition,"seed":seed,"arm":arm,"predictions":rows,
            "scores":{"n":len(rows),"valid":valid,"correct":correct,
                      "valid_rate":valid/len(rows),"accuracy_including_invalid":correct/len(rows),
                      "agreement_with_two_choice":agreement/len(rows),
                      "generated_tokens":sum(x["tokens"] for x in rows)},
            "cost":{"load_wall_seconds":load,"inference_wall_seconds":infer,
                    "cpu_seconds":time.process_time()-cpustart,
                    "maxrss_kib_lifetime_peak":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
        })
        print("GEN",condition,"VALID",valid,"CORRECT",correct,"AGREE",agreement,
              "TOKENS",runs[-1]["scores"]["generated_tokens"],
              "WALL",round(time.perf_counter()-t0,2),flush=True)
        del model; gc.collect()
    report={
        "schema":SCHEMA,"authority":"DENY_ALL_HOLD_NO_GO",
        "status":"PUBLIC_OPERATOR_DIAGNOSTIC_NOT_INDEPENDENT",
        "max_new_tokens":MAX_NEW_TOKENS,"decoding":"greedy_unconstrained",
        "parse_rule":"leading_whitespace_then_yes_or_no_word_only",
        "source_plan_pr":5960,"original_training_pr":5905,"original_ood_pr":5995,
        "plan_sha256":prior.sha256(args.plan),
        "source_training_sha256":prior.sha256(args.archive),
        "source_two_choice_sha256":prior.sha256(args.previous),
        "script_sha256":prior.sha256(__file__),
        "started_utc":stamp,"finished_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
        "cpu_only":True,"threads":args.threads,
        "torch_version":torch.__version__,"transformers_version":__import__("transformers").__version__,
        "model_identities":archive["identities"],
        "runs":runs,
        "full_run_cost":{"wall_seconds":time.perf_counter()-t0,
                         "process_cpu_seconds":time.process_time()-cpu0,
                         "io_delta":prior.io_difference(io0,prior.io_counts()),
                         "maxrss_kib_lifetime_peak":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss},
        "not_measured":["independent evaluator","native Owner signature","A-to-future-B-to-C decision",
                        "ACT/CTRL effect outcomes","NDU 2x2","energy and total owner costs"]
    }
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,sort_keys=True,indent=2,allow_nan=False)+"\n")
    print("RESULT_SHA256",prior.sha256(args.out),"ROWS",sum(len(x["predictions"]) for x in runs),flush=True)

if __name__=="__main__":
    main()
