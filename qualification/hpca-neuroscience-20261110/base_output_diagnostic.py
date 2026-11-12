#!/usr/bin/env python3
"""Source-frozen base-only output diagnostic; exposed tasks, no training/adoption."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import sys
import time
import urllib.request

import freegen_contract as contract
import native_lora_ood_probe as prior
import real_freegen

ROOT = Path(__file__).parent


def verify_inputs(plan, tasks_file, previous_file):
    if plan.get("schema") != "hpca-base-output-diagnostic-plan-v1":
        raise ValueError("wrong diagnostic plan")
    for path, key in ((tasks_file, "task_plan_sha256"),
                      (previous_file, "previous_two_choice_sha256")):
        if prior.sha256(path) != plan[key]:
            raise ValueError("changed frozen input")
    tasks = prior.check_plan(json.loads(tasks_file.read_text()))
    reference = real_freegen.check_previous(previous_file, tasks)["base"]
    for task in tasks:
        expected = reference[task["id"]]
        prompt = task["question"].strip() + "\nAnswer:"
        if (expected["truth"] != task["truth"] or
                expected["family"] != task["family"] or
                expected["prompt_sha256"] != hashlib.sha256(prompt.encode()).hexdigest()):
            raise ValueError("changed prompt, truth or family")
    return tasks, reference


def validate_generated_tokens(input_ids, output_ids):
    if output_ids[:len(input_ids)] != input_ids:
        raise ValueError("generation changed the prompt prefix")
    emitted = output_ids[len(input_ids):]
    if not 1 <= len(emitted) <= 8:
        raise ValueError("generation did not return one to eight tokens")
    return emitted


def summarize(rows):
    if len(rows) != 24 or len({row["id"] for row in rows}) != 24:
        raise ValueError("not the complete base-only population")
    return {
        "n": 24,
        "two_choice_correct": sum(row["two_choice_prediction"] == row["truth"] for row in rows),
        "greedy_valid": sum(row["parsed"] is not None for row in rows),
        "greedy_correct_including_invalid": sum(row["parsed"] == row["truth"] for row in rows),
        "agreement": sum(row["parsed"] == row["two_choice_prediction"] for row in rows),
        "max_prior_p_yes_absolute_drift": max(row["prior_p_yes_absolute_drift"] for row in rows),
        "min_label_vocabulary_mass": min(row["label_vocabulary_mass"] for row in rows),
        "max_label_vocabulary_mass": max(row["label_vocabulary_mass"] for row in rows),
        "generated_tokens": sum(len(row["emitted_token_ids"]) for row in rows),
        "unique_public_tasks": 24,
        "independently_held_future_tasks": 0,
        "adapters_loaded": 0,
    }


def main():
    started_wall, started_cpu = time.perf_counter(), time.process_time()
    started_utc = dt.datetime.now(dt.timezone.utc).isoformat()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    plan_path = ROOT / "BASE_OUTPUT_PLAN.json"
    plan = json.loads(plan_path.read_text())
    tasks, reference = verify_inputs(plan, ROOT / "HPCA_V2_OOD_PLAN.json",
                                    ROOT / "ACTUAL_OOD_FORWARD_RESULT.json")
    model_root = args.out / "model"
    model_root.mkdir()
    download_start = time.perf_counter()
    download_bytes = 0
    for name in plan["download_files"]:
        url = ("https://huggingface.co/" + plan["model_repository"] + "/resolve/" +
               plan["model_revision"] + "/" + name)
        with urllib.request.urlopen(url, timeout=60) as response, (model_root / name).open("xb") as output:
            while chunk := response.read(1024 * 1024):
                download_bytes += len(chunk)
                if download_bytes > plan["maximum_download_bytes"]:
                    raise ValueError("download exceeded the declared byte budget")
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
    download_wall = time.perf_counter() - download_start
    assets = {p.name: {"bytes": p.stat().st_size, "sha256": prior.sha256(p)}
              for p in sorted(model_root.iterdir())}
    for name, digest in plan["expected_existing_identities"].items():
        if assets[name]["sha256"] != digest:
            raise ValueError("downloaded asset differs from original identity: " + name)
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import_start = time.perf_counter()
    import torch
    import transformers
    import numpy
    import tokenizers
    import safetensors
    from transformers import AutoModelForCausalLM, AutoTokenizer
    runtime = {"python": platform.python_version(), "torch": torch.__version__,
               "transformers": transformers.__version__, "numpy": numpy.__version__,
               "tokenizers": tokenizers.__version__, "safetensors": safetensors.__version__,
               "platform": platform.platform()}
    if any(runtime[key] != plan["runtime"][key] for key in ("python", "torch", "transformers")):
        raise ValueError("runtime differs from source-frozen plan")
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    if torch.cuda.is_available():
        raise ValueError("CPU-only contract violated")
    import_wall = time.perf_counter() - import_start
    load_start = time.perf_counter()
    tok = AutoTokenizer.from_pretrained(model_root, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_root, local_files_only=True, dtype=torch.float32, attn_implementation="eager").eval()
    config = contract.resolve_generation_config(model, tok)
    yes, no = (tok.encode(label, add_special_tokens=False) for label in (" yes", " no"))
    if len(yes) != 1 or len(no) != 1 or yes == no:
        raise ValueError("label candidates are not distinct single tokens")
    class_ids = [yes[0], no[0]]
    load_wall = time.perf_counter() - load_start
    source = {name: prior.sha256(ROOT / name) for name in (
        "base_output_diagnostic.py", "freegen_contract.py", "real_freegen.py",
        "native_lora_ood_probe.py", "BASE_OUTPUT_PLAN.json", "HPCA_V2_OOD_PLAN.json",
        "ACTUAL_OOD_FORWARD_RESULT.json")}
    preexecution = {
        "schema": "hpca-base-output-preexecution-v1", "started_utc": started_utc,
        "recorded_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_head": os.environ.get("SOURCE_HEAD"), "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"), "sources": source,
        "assets": assets, "model_revision": plan["model_revision"], "runtime": runtime,
        "effective_generation_config": config.to_dict(), "class_token_ids": class_ids,
        "eos_token_id": tok.eos_token_id, "bos_token_id": tok.bos_token_id,
        "population": plan["population"], "scope": plan["scope"],
        "authority": plan["authority"],
    }
    contract.write_json_exclusive(args.out / "PREEXECUTION.json", preexecution)
    print("HPCA_BASE_PREEXECUTION_JSON=" + json.dumps(preexecution, sort_keys=True, allow_nan=False), flush=True)
    rows = []
    attempts = contract.RunJournal(args.out / "ATTEMPTS.jsonl")
    with (args.out / "ROWS.jsonl").open("x", encoding="utf-8") as journal, torch.inference_mode():
        for task in tasks:
            prompt = task["question"].strip() + "\nAnswer:"
            inputs = tok(prompt, return_tensors="pt", add_special_tokens=True)
            attempts.append("attempt_started", id=task["id"], condition="base")
            score_start = time.perf_counter()
            logits = model(**inputs, use_cache=False).logits[0, -1].float()
            selected = logits[class_ids]
            p_yes = float(torch.softmax(selected, dim=0)[0])
            log_mass = float(torch.logsumexp(selected, dim=0) - torch.logsumexp(logits, dim=0))
            score_wall = time.perf_counter() - score_start
            generate_start = time.perf_counter()
            output = model.generate(**inputs, generation_config=config, use_model_defaults=False)
            generate_wall = time.perf_counter() - generate_start
            if output.ndim != 2 or output.shape[0] != 1:
                raise ValueError("generation returned multiple sequences")
            emitted = validate_generated_tokens(inputs["input_ids"][0].tolist(), output[0].tolist())
            text = tok.decode(emitted, skip_special_tokens=True)
            top_id = int(logits.argmax())
            row = {
                "sequence": len(rows), "id": task["id"], "truth": task["truth"], "family": task["family"],
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "input_token_ids": inputs["input_ids"][0].tolist(),
                "p_yes": p_yes, "two_choice_prediction": "yes" if p_yes >= 0.5 else "no",
                "label_log_vocabulary_mass": log_mass,
                "label_vocabulary_mass": float(torch.exp(torch.tensor(log_mass, dtype=torch.float64))),
                "class_logits": selected.tolist(),
                "label_token_ranks": [int((logits > logits[i]).sum()) + 1 for i in class_ids],
                "top_next_token_id": top_id, "top_next_token_text": tok.decode([top_id]),
                "generated_text": text, "emitted_token_ids": emitted,
                "parsed": real_freegen.parse_leading_answer(text),
                "prior_p_yes": reference[task["id"]]["p_yes"],
                "prior_p_yes_absolute_drift": abs(p_yes - reference[task["id"]]["p_yes"]),
                "two_choice_wall_seconds": score_wall, "generate_wall_seconds": generate_wall,
            }
            journal.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
            journal.flush()
            os.fsync(journal.fileno())
            rows.append(row)
            attempts.append("attempt_completed", id=task["id"], condition="base", row_index=len(rows)-1)
    attempts.close()
    if any(prior.sha256(model_root / name) != item["sha256"] for name, item in assets.items()):
        raise ValueError("model assets changed during diagnostic")
    if any(prior.sha256(ROOT / name) != digest for name, digest in source.items()):
        raise ValueError("source changed during diagnostic")
    report = {
        "schema": "hpca-base-output-result-v1", "status": "COMPLETE_PUBLIC_BASE_ONLY_DIAGNOSTIC",
        "scope": plan["scope"], "authority": plan["authority"], "summary": summarize(rows), "rows": rows,
        "preexecution_sha256": prior.sha256(args.out / "PREEXECUTION.json"),
        "rows_sha256": prior.sha256(args.out / "ROWS.jsonl"),
        "attempts_sha256": prior.sha256(args.out / "ATTEMPTS.jsonl"),
        "source_head": preexecution["source_head"], "run_id": preexecution["run_id"],
        "started_utc": started_utc, "finished_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "cost": {"download_wall_seconds": download_wall, "download_bytes": download_bytes, "imports_wall_seconds": import_wall,
                 "tokenizer_model_load_and_contract_wall_seconds": load_wall,
                 "main_entry_to_report_wall_seconds": time.perf_counter() - started_wall,
                 "main_entry_to_report_cpu_seconds": time.process_time() - started_cpu,
                 "maxrss_kib_process_lifetime_peak": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                 "excluded": ["interpreter startup before main", "CI queue and setup", "energy", "owner costs"]},
        "not_credited": plan["not_credited"],
    }
    contract.write_json_exclusive(args.out / "RESULT.json", report)
    print("HPCA_BASE_RESULT_JSON=" + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
