#!/usr/bin/env python3
"""Frozen CPU development diagnostic; operator tasks are not independent B."""
import argparse
import datetime
import gc
import json
import os
from pathlib import Path
import platform
import re
import resource
import time
import unicodedata

import freegen_contract as contract
import native_lora_ood_probe as prior

ROOT = Path(__file__).resolve().parent
SPLITS = {"calibration": 16, "old_development": 16,
          "context_worlds": 32, "retention": 32}
WRAPPERS = ("original_chat", "explicit_binary_chat")
CONDITIONS = [("base", None, None)] + [
    (f"seed{seed} {arm}", seed, arm)
    for seed in (11, 17, 23, 29)
    for arm in (("interleaved", "bursty") if seed in (11, 23)
                else ("bursty", "interleaved"))]


def normalized(question):
    text = " ".join(unicodedata.normalize("NFKC", question).casefold().split())
    for prefix in ("answer yes or no. ", "answer with only yes or no. "):
        if text.startswith(prefix):
            text = text[len(prefix):]
    if text.endswith(" answer:"):
        text = text[:-len(" answer:")]
    return text


def validate_data(data, exposed):
    if data.get("schema") != "hpca-prospective-operator-development-data-v1":
        raise ValueError("data schema")
    if data.get("authority") != "DENY_ALL_HOLD_NO_GO" or data.get("independent_evaluator", False) is not False:
        raise ValueError("operator data cannot claim independence")
    rows = data.get("tasks", [])
    if len(rows) != 96 or len({r["id"] for r in rows}) != 96:
        raise ValueError("task roster")
    blocked = {normalized(q) for q in exposed}
    clusters, seen = {}, set()
    for row in rows:
        if row.get("split") not in SPLITS or row.get("truth") not in ("yes", "no"):
            raise ValueError("split or truth")
        if not all(isinstance(row.get(k), str) and row[k].strip()
                   for k in ("id", "source_cluster", "question")):
            raise ValueError("empty identity")
        text = normalized(row["question"])
        if text in seen or text in blocked:
            raise ValueError("duplicate or exposed question")
        seen.add(text)
        cluster = row["source_cluster"]
        if cluster in clusters and clusters[cluster] != row["split"]:
            raise ValueError("source cluster crosses splits")
        clusters[cluster] = row["split"]
    for split, size in SPLITS.items():
        sub = [r for r in rows if r["split"] == split]
        if len(sub) != size or sum(r["truth"] == "yes" for r in sub) != size // 2:
            raise ValueError("split size or balance")
    return rows


def message(task, wrapper):
    if wrapper == "original_chat":
        text = task["question"].strip() + "\nAnswer:"
    elif wrapper == "explicit_binary_chat":
        text = ("Answer the following question with exactly YES or NO. Do not explain.\n"
                "Question: " + task["question"].strip())
    else:
        raise ValueError("unregistered wrapper")
    return [{"role": "user", "content": text}]


def parse_answer(text):
    match = re.match(r"^\s*(yes|no)(?!\w)", text, flags=re.IGNORECASE)
    return match.group(1).lower() if match else None


def select_wrapper(rows):
    if len(rows) != 32:
        raise ValueError("complete base-only calibration required")
    signatures = None
    ranks = []
    for index, wrapper in enumerate(WRAPPERS):
        part = [r for r in rows if r["wrapper"] == wrapper]
        identities = [r["id"] for r in part]
        if (len(part) != 16 or len(set(identities)) != 16 or
                any(r["condition"] != "base" or r["split"] != "calibration" for r in part)):
            raise ValueError("calibration-only selection")
        if signatures is not None and identities != signatures:
            raise ValueError("calibration roster differs by wrapper")
        signatures = identities
        ranks.append((sum(r["valid"] for r in part),
                      sum(r["correct"] for r in part), -index, wrapper))
    return max(ranks)[-1]


def summary(rows):
    if not rows:
        raise ValueError("empty summary")
    return {"n": len(rows), "valid": sum(r["valid"] for r in rows),
            "correct": sum(r["correct"] for r in rows),
            "first_eos": sum(r["first_eos"] for r in rows),
            "accuracy_including_invalid": sum(r["correct"] for r in rows) / len(rows)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("model", "adapter-root", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--publication-manifest", type=Path, required=True)
    args = parser.parse_args()
    began_wall, began_cpu = time.perf_counter(), time.process_time()
    began_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    args.out.mkdir(parents=True, exist_ok=False)
    source_names = ("prospective_devel.py", "PROSPECTIVE_DEVEL_DATA.json",
                    "PROSPECTIVE_DEVEL_PLAN.json", "PROSPECTIVE_EXPOSURE_REGISTRY.json",
                    "freegen_contract.py", "native_lora_ood_probe.py",
                    "real_cpu_clock_v2_RESULT.json")
    paths = {name: ROOT / name for name in source_names}
    source_hashes = contract.pin_files(paths)
    publication = json.loads(args.publication_manifest.read_bytes())
    if (not re.fullmatch(r"[0-9a-f]{40}", publication.get("commit", "")) or
            publication.get("sources") != source_hashes):
        raise ValueError("published source-file manifest mismatch")
    plan = json.loads(paths["PROSPECTIVE_DEVEL_PLAN.json"].read_bytes())
    if plan["selection"] != "DENY_ALL" or plan["independent_future_B"] is not False:
        raise ValueError("unsupported authority")
    for name, expected in plan["input_sha256"].items():
        if source_hashes[name] != expected:
            raise ValueError("precommitted input bytes changed: " + name)
    data = json.loads(paths["PROSPECTIVE_DEVEL_DATA.json"].read_bytes())
    exposure = json.loads(paths["PROSPECTIVE_EXPOSURE_REGISTRY.json"].read_bytes())
    tasks = validate_data(data, exposure["questions"])
    archive_path = paths["real_cpu_clock_v2_RESULT.json"]
    archive = json.loads(archive_path.read_bytes())
    prior.check_archive(archive, archive_path, args.model, args.adapter_root)
    assets = contract.asset_manifest(args.model, args.adapter_root)
    if assets["model"] != plan["model_asset_witnesses"]:
        raise ValueError("full original model asset manifest changed")
    os.environ.update(CUDA_VISIBLE_DEVICES="", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel
    runtime = {"python": platform.python_version(), "torch": torch.__version__,
               "transformers": __import__("transformers").__version__,
               "peft": __import__("peft").__version__}
    if runtime != plan["runtime"]:
        raise ValueError("frozen CPU runtime mismatch")
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    if torch.cuda.is_available():
        raise ValueError("CPU-only protocol")
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    encodings = {}
    for wrapper in WRAPPERS:
        for task in tasks:
            ids = tokenizer.apply_chat_template(message(task, wrapper), tokenize=True,
                                                add_generation_prompt=True)
            if not isinstance(ids, list) or not ids or ids[-1] == tokenizer.eos_token_id:
                raise ValueError("invalid open chat encoding")
            encodings[(wrapper, task["id"])] = ids
    pre = {"schema": "hpca-prospective-development-preexecution-v1",
           "authority": "DENY_ALL_HOLD_NO_GO", "source_publication": publication["commit"],
           "sources": source_hashes, "assets": assets, "runtime": runtime,
           "planned_generations": 624, "weight_updates": 0,
           "independent_future_B": False, "encodings": [
               {"wrapper": wrapper, "id": task["id"], "tokens": encodings[(wrapper, task["id"])]}
               for wrapper in WRAPPERS for task in tasks]}
    journal = contract.RunJournal(args.out / "ROWS.jsonl")
    pre["run_id"] = journal.run_id
    pre["publication_manifest_sha256"] = prior.sha256(args.publication_manifest)
    pre["git_tree_materialized"] = False
    pre["source_binding"] = "PUBLICATION_FILE_HASHES_VERIFIED_BY_LAUNCHER"
    all_rows = []

    def evaluate(model, subset, wrapper, condition, generation_config):
        result = []
        with torch.inference_mode():
            for task in subset:
                x = torch.tensor([encodings[(wrapper, task["id"])]], dtype=torch.long)
                journal.append("attempt_started", condition=condition, wrapper=wrapper,
                               task_id=task["id"], split=task["split"])
                start = time.perf_counter()
                output = model.generate(input_ids=x, attention_mask=torch.ones_like(x),
                    generation_config=generation_config, use_model_defaults=False)
                elapsed = time.perf_counter() - start
                if not torch.equal(output[0, :x.shape[1]], x[0]):
                    raise ValueError("prompt prefix changed")
                emitted = output[0, x.shape[1]:].tolist()
                if not 1 <= len(emitted) <= 8:
                    raise ValueError("token budget")
                text = tokenizer.decode(emitted, skip_special_tokens=True)
                parsed = parse_answer(text)
                row = {**task, "condition": condition, "wrapper": wrapper,
                       "text": text, "tokens": emitted, "parsed": parsed,
                       "valid": parsed is not None, "correct": parsed == task["truth"],
                       "first_eos": emitted[0] == tokenizer.eos_token_id,
                       "inference_wall_seconds": elapsed}
                journal.append("row_completed", row=row)
                result.append(row)
                all_rows.append(row)
        return result

    calibration = [t for t in tasks if t["split"] == "calibration"]
    old_dev = [t for t in tasks if t["split"] == "old_development"]
    primary = [t for t in tasks if t["split"] in ("context_worlds", "retention")]
    runs, selected, frozen_config = [], None, None
    for condition, seed, arm in CONDITIONS:
        started_wall, started_cpu = time.perf_counter(), time.process_time()
        model = AutoModelForCausalLM.from_pretrained(args.model, local_files_only=True,
                    dtype=torch.float32, attn_implementation="eager")
        if seed is not None:
            model = PeftModel.from_pretrained(model,
                    args.adapter_root / f"seed{seed}-{arm}-adapter", is_trainable=False)
        model.eval()
        for parameter in model.parameters():
            parameter.requires_grad_(False)
        load_wall = time.perf_counter()-started_wall
        config = contract.resolve_generation_config(model, tokenizer)
        if config.is_assistant is not False:
            raise ValueError("assistant confidence stopping")
        if frozen_config is None:
            frozen_config = config.to_dict()
            contract.write_json_exclusive(args.out / "GENERATION_CONFIG.json", frozen_config)
            pre["generation_config"] = frozen_config
            contract.write_json_exclusive(args.out / "PREEXECUTION.json", pre)
            cal_rows = []
            for wrapper in WRAPPERS:
                cal_rows.extend(evaluate(model, calibration, wrapper, "base", config))
            selected = select_wrapper(cal_rows)
            cal_scores = {w: summary([r for r in cal_rows if r["wrapper"] == w]) for w in WRAPPERS}
            choice = {"selected_wrapper": selected, "rule": "valid then correct then frozen order",
                      "calibration_scores": cal_scores, "selection_task_ids": [t["id"] for t in calibration],
                      "independent_future_B": False}
            contract.write_json_exclusive(args.out / "WRAPPER_SELECTION.json", choice)
            evaluate(model, old_dev, selected, "base", config)
            print("WRAPPER_SELECTION", json.dumps(choice, sort_keys=True), flush=True)
        elif config.to_dict() != frozen_config:
            raise ValueError("configuration differs by adapter")
        primary_wall, primary_cpu = time.perf_counter(), time.process_time()
        rows = evaluate(model, primary, selected, condition, config)
        primary_wall = time.perf_counter()-primary_wall
        primary_cpu = time.process_time()-primary_cpu
        by_split = {split: summary([r for r in rows if r["split"] == split])
                    for split in ("context_worlds", "retention")}
        runs.append({"condition": condition, "seed": seed, "arm": arm,
                     "scores": by_split, "model_load_wall_seconds": load_wall,
                     "primary64_wall_seconds": primary_wall, "primary64_cpu_seconds": primary_cpu,
                     "condition_lifecycle_wall_seconds": time.perf_counter()-started_wall,
                     "condition_lifecycle_cpu_seconds": time.process_time()-started_cpu,
                     "lifecycle_scope": "base includes32 calibration and16 development; adapter only primary64"})
        print("COMPLETE", condition, json.dumps(by_split, sort_keys=True), flush=True)
        del model
        gc.collect()
    if len(all_rows) != 624:
        raise ValueError("incomplete planned execution")
    contract.require_file_pins(paths, source_hashes)
    if prior.sha256(args.publication_manifest) != pre["publication_manifest_sha256"]:
        raise ValueError("publication manifest changed during inference")
    if contract.asset_manifest(args.model, args.adapter_root) != assets:
        raise ValueError("model or adapter bytes changed")
    journal.append("all_rows_complete", n=len(all_rows))
    journal.close()
    base_retention = runs[0]["scores"]["retention"]
    report = {"schema": "hpca-prospective-operator-development-result-v1",
              "authority": "DENY_ALL_HOLD_NO_GO", "source_publication": publication["commit"],
              "run_id": journal.run_id,
              "preexecution_sha256": prior.sha256(args.out/"PREEXECUTION.json"),
              "generation_config_sha256": prior.sha256(args.out/"GENERATION_CONFIG.json"),
              "wrapper_selection_sha256": prior.sha256(args.out/"WRAPPER_SELECTION.json"),
              "journal_sha256": prior.sha256(args.out/"ROWS.jsonl"),
              "selected_wrapper": selected, "calibration_scores": cal_scores,
              "calibration_format_adequate": cal_scores[selected]["valid"] >= 14,
              "old_development": summary([r for r in all_rows if r["split"] == "old_development"]),
              "retention_competency_gate": base_retention["correct"] >= 24 and base_retention["valid"] >= 28,
              "retention_rule": "base correct >=24/32 and valid >=28/32; descriptive development only",
              "runs": runs, "rows": all_rows, "actual_generations": len(all_rows),
              "started_utc": began_utc,
              "finished_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "wall_seconds": time.perf_counter()-began_wall,
              "cpu_seconds": time.process_time()-began_cpu,
              "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              "cost_excludes": ["external setup/control", "queue", "energy", "Owner lifecycle"],
              "independent_future_B": False, "old_capability_confirmation": "NOT_INDEPENDENT",
              "training_updates": 0, "production_qualified": False,
              "decision": "HOLD_NO_GO"}
    contract.write_json_exclusive(args.out/"RESULT.json", report)
    print("RESULT_SHA256", prior.sha256(args.out/"RESULT.json"), "ROWS", len(all_rows), flush=True)


if __name__ == "__main__":
    main()
