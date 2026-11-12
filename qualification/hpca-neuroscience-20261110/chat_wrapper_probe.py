#!/usr/bin/env python3
"""One-arm real-model chat-wrapper diagnostic on the 24 exposed HPCA public tasks."""
import argparse
import datetime
import json
import os
from pathlib import Path
import platform
import re
import resource
import subprocess
import time
import urllib.request

from freegen_contract import sha256, write_json_exclusive, RunJournal, resolve_generation_config
from native_lora_ood_probe import check_plan

ROOT = Path(__file__).resolve().parent

def parse_answer(text):
    m = re.match(r"^\s*(yes|no)(?!\w)", text, flags=re.IGNORECASE)
    return m.group(1).lower() if m else None

def messages(task):
    return [{"role": "user", "content": task["question"].strip() + "\nAnswer:"}]

def validate_roster(plan, base, tasks):
    if plan["schema"] != "hpca-chat-wrapper-exposed-v1":
        raise ValueError("wrong diagnostic schema")
    if sha256(ROOT / "BASE_OUTPUT_PLAN.json") != plan["base_plan_sha256"]:
        raise ValueError("frozen base plan changed")
    if sha256(ROOT / "HPCA_V2_OOD_PLAN.json") != plan["task_plan_sha256"]:
        raise ValueError("frozen task plan changed")
    if plan["model_revision"] != base["model_revision"]:
        raise ValueError("model revision drift")
    if plan["arm"] != "user_chat_template_same_text":
        raise ValueError("unregistered prompt arm")
    if base["protocol"]["chat_template"] is not False:
        raise ValueError("original bare-prompt plan drift")
    roster = check_plan(tasks)
    if len(roster) != 24 or len({r["id"] for r in roster}) != 24:
        raise ValueError("incomplete or duplicate public tasks")
    if {r["truth"] for r in roster} != {"yes", "no"}:
        raise ValueError("task label cohort invalid")
    return roster

def encode(tokenizer, task):
    if not tokenizer.chat_template:
        raise ValueError("missing tokenizer chat template")
    msg = messages(task)
    ids = tokenizer.apply_chat_template(msg, tokenize=True, add_generation_prompt=True)
    if not isinstance(ids, list) or not ids or ids[-1] == tokenizer.eos_token_id:
        raise ValueError("invalid open assistant prefix")
    raw = tokenizer(msg[0]["content"], add_special_tokens=True)["input_ids"]
    if ids == raw:
        raise ValueError("chat wrapper not applied")
    return ids

def pin_assets(base, model_dir, fetch):
    if fetch:
        model_dir.mkdir(parents=True, exist_ok=False)
        total = 0
        for file in base["download_files"]:
            if "/" in file or file.startswith("."):
                raise ValueError("unsafe model path")
            url = ("https://huggingface.co/" + base["model_repository"] +
                   "/resolve/" + base["model_revision"] + "/" + file)
            with urllib.request.urlopen(url, timeout=90) as source, (model_dir / file).open("xb") as out:
                for data in iter(lambda: source.read(1024 * 1024), b""):
                    total += len(data)
                    if total > base["maximum_download_bytes"]:
                        raise ValueError("original download cap exceeded")
                    out.write(data)
                out.flush()
                os.fsync(out.fileno())
    record = {}
    for name in base["download_files"]:
        file = model_dir / name
        if file.is_symlink() or not file.is_file():
            raise ValueError("unavailable original model asset: " + name)
        record[name] = {"bytes": file.stat().st_size, "sha256": sha256(file)}
    for name, digest in base["expected_existing_identities"].items():
        if record[name]["sha256"] != digest:
            raise ValueError("original weight/config/tokenizer mismatch: " + name)
    return record

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--model-dir", type=Path, default=None)
    args = parser.parse_args()
    began_wall = time.perf_counter()
    began_cpu = time.process_time()
    began_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    args.out.mkdir(parents=True, exist_ok=False)
    paths = [Path(__file__), ROOT / "CHAT_WRAPPER_PLAN.json",
             ROOT / "BASE_OUTPUT_PLAN.json", ROOT / "HPCA_V2_OOD_PLAN.json",
             ROOT / "freegen_contract.py", ROOT / "native_lora_ood_probe.py"]
    source_pins = {path.name: sha256(path) for path in paths}
    plan = json.loads((ROOT / "CHAT_WRAPPER_PLAN.json").read_text())
    base = json.loads((ROOT / "BASE_OUTPUT_PLAN.json").read_text())
    tasks = validate_roster(plan, base, json.loads((ROOT / "HPCA_V2_OOD_PLAN.json").read_text()))
    model_dir = args.model_dir if args.model_dir is not None else args.out / "model"
    fetch_start = time.perf_counter()
    assets = pin_assets(base, model_dir, args.model_dir is None)
    fetch_wall = time.perf_counter() - fetch_start
    os.environ.update(CUDA_VISIBLE_DEVICES="", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, __version__ as tf_version
    if (platform.python_version(), torch.__version__, tf_version) != (
        "3.14.4", "2.9.1+cpu", "4.57.3"
    ):
        raise ValueError("frozen CPU runtime mismatch")
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    if torch.cuda.is_available():
        raise ValueError("GPU not permitted")
    tok = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_dir, local_files_only=True, dtype=torch.float32,
        attn_implementation="eager").eval()
    config = resolve_generation_config(model, tok)
    if config.is_assistant:
        raise ValueError("assistant confidence stopping prohibited")
    encodings = {task["id"]: encode(tok, task) for task in tasks}
    head = subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    tree = subprocess.check_output(["git","rev-parse","HEAD^{tree}"],cwd=ROOT,text=True).strip()
    write_json_exclusive(args.out / "PREEXECUTION.json", {
        "schema":"HPCA-CHAT-WRAPPER-PREEXECUTION-1","head":head,"tree":tree,
        "sources":source_pins,"model":assets,"config":config.to_dict(),
        "runtime":{"python":platform.python_version(),"torch":torch.__version__,
                   "transformers":tf_version,"cpu_threads":4},
        "prompts":[{"id":t["id"],"input_ids":encodings[t["id"]]} for t in tasks],
        "authority":"DENY_ALL_HOLD_NO_GO","independent_future":0,"weight_updates":0})
    journal = RunJournal(args.out / "ROWS.jsonl")
    rows = []
    with torch.inference_mode():
        for task in tasks:
            x = torch.tensor([encodings[task["id"]]],dtype=torch.long)
            journal.append("attempt_started",task_id=task["id"])
            t0 = time.perf_counter()
            y = model.generate(input_ids=x,attention_mask=torch.ones_like(x),
                               generation_config=config,use_model_defaults=False)
            dt = time.perf_counter()-t0
            if not torch.equal(y[0,:x.shape[1]], x[0]):
                raise ValueError("output prompt prefix drift")
            emitted = y[0,x.shape[1]:].tolist()
            if not 1 <= len(emitted) <= 8:
                raise ValueError("invalid token count")
            decoded = tok.decode(emitted, skip_special_tokens=True)
            parsed = parse_answer(decoded)
            row = {"id":task["id"],"family":task["family"],"truth":task["truth"],
                   "tokens":emitted,"text":decoded,"parsed":parsed,
                   "valid":parsed is not None,"correct":parsed==task["truth"],
                   "first_eos":emitted[0]==tok.eos_token_id,
                   "inference_wall_seconds":dt}
            journal.append("row_completed",row=row)
            rows.append(row)
    journal.append("all_rows_complete",n=len(rows))
    journal.close()
    if len(rows) != 24:
        raise ValueError("incomplete public cohort")
    if {path.name:sha256(path) for path in paths} != source_pins:
        raise ValueError("source bytes drifted during execution")
    if pin_assets(base, model_dir, False) != assets:
        raise ValueError("model bytes drifted during execution")
    report = {
        "schema":"HPCA-CHAT-WRAPPER-PUBLIC-RESULT-1",
        "authority":"DENY_ALL_HOLD_NO_GO",
        "head":head,"tree":tree,
        "preexecution_sha256":sha256(args.out/"PREEXECUTION.json"),
        "journal_sha256":sha256(args.out/"ROWS.jsonl"),
        "summary":{"n":24,"valid":sum(r["valid"] for r in rows),
                   "correct":sum(r["correct"] for r in rows),
                   "first_eos":sum(r["first_eos"] for r in rows),
                   "independent_future":0},
        "rows":rows,
        "cost":{"wall_seconds":time.perf_counter()-began_wall,
                "cpu_seconds":time.process_time()-began_cpu,
                "model_download_wall_seconds":fetch_wall,
                "peak_rss_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss},
        "cost_excluded":["CI setup and queue","power","Owner lifecycle"],
        "started_utc":began_utc,
        "finished_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope":"ONE public-task output-format diagnostic, NOT HPCA gain, future B, or production"})
    write_json_exclusive(args.out / "RESULT.json",report)
    print("HPCA_PUBLIC_CHAT_RESULT",json.dumps(report["summary"],sort_keys=True),flush=True)
    print("RESULT_SHA256",sha256(args.out/"RESULT.json"),flush=True)

if __name__=="__main__":
    main()
