#!/usr/bin/env python3
"""CPU-only genuine frozen-checkpoint OOD forward audit, *not* independent evaluation.

The plan is a publicly committed operator task list. This code reads the original
V2 model/adapter files; it does NOT train, write Owner state, or adopt weights.
"""
from __future__ import annotations
import argparse
import datetime as dt
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import statistics
import sys
import time


SCHEMA = "HPCA-V2-OOD-REAL-CPU-READONLY-V1"
EXPECTED_PLAN = "hpca-v2-operator-ood-plan-1"
EXPECTED_SOURCE_RESULT_SHA = "9512849b90964c35951bb8bb2226b3f2f6d3ec0da1e9a3b98467c8970afbe39c"
PLAN_HEAD = "a54c1d72ee2d82d3bae5c5fdda94d5d3333046b2"
FAMILIES = ("arithmetic", "taxonomy", "negation", "conditional")
SEEDS = (11, 17, 23, 29)
ARMS = ("interleaved", "bursty")


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def io_counts():
    try:
        return dict((k.strip(), int(v.strip())) for line in Path("/proc/self/io").read_text().splitlines()
                    for k, v in [line.split(":", 1)])
    except (OSError, ValueError):
        return {}


def io_difference(before, after):
    return {k: v - before.get(k, 0) for k, v in after.items()}


def check_plan(plan):
    if plan.get("schema") != EXPECTED_PLAN or plan.get("base_head") != (
            "6acce13e2052c9c44c39ec78f29c511a5fc59790"):
        raise ValueError("unrecognized precommitted plan")
    if plan.get("claimed_independent_evaluator") is not False or plan.get("selection") != "DENY_ALL":
        raise ValueError("plan has unsupported independence or authority claim")
    conditions = plan.get("target_conditions")
    expected = ["frozen base"] + [f"seed{s} {arm}" for s in SEEDS for arm in ARMS]
    if conditions != expected:
        raise ValueError("unrecognized frozen conditions")
    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 24:
        raise ValueError("unrecognized OOD task population")
    if len({r["id"] for r in tasks}) != 24 or len({r["question"] for r in tasks}) != 24:
        raise ValueError("duplicate task identity")
    for family in FAMILIES:
        family_rows = [r for r in tasks if r.get("family") == family]
        if len(family_rows) != 6 or sorted(r["truth"] for r in family_rows) != ["no"] * 3 + ["yes"] * 3:
            raise ValueError("unbalanced or missing task family")
    if any(not isinstance(r["question"], str) or not r["question"].strip()
           or r["truth"] not in ("yes", "no") or r["family"] not in FAMILIES
           for r in tasks):
        raise ValueError("invalid task label or question")
    return tasks


def check_archive(archive, archive_file, model_root, adapter_root):
    if sha256(archive_file) != EXPECTED_SOURCE_RESULT_SHA:
        raise ValueError("original model-training report changed")
    if archive.get("schema") != "HPCA-REAL-CPU-LORA-CLOCK-V2-MATCHED":
        raise ValueError("unexpected original V2 schema")
    if sorted(archive.get("seeds", [])) != list(SEEDS):
        raise ValueError("unexpected paired seeds")
    identity = archive["identities"]
    for local_name, key in (("model.safetensors", "model_safetensors_sha256"),
                            ("config.json", "config_sha256"),
                            ("tokenizer.json", "tokenizer_sha256")):
        if sha256(model_root / local_name) != identity[key]:
            raise ValueError("base model/tokenizer identity mismatch")
    old_runs = {(r["seed"], r["arm"]): r for r in archive["runs"]}
    if set(old_runs) != {(seed, arm) for seed in SEEDS for arm in ARMS}:
        raise ValueError("missing original paired runs")
    for (seed, arm), record in old_runs.items():
        checkpoint = adapter_root / f"seed{seed}-{arm}-adapter"
        for name, metadata in record["checkpoint_files"].items():
            artifact = checkpoint / name
            if not artifact.is_file() or artifact.stat().st_size != metadata["bytes"] or (
                    sha256(artifact) != metadata["sha256"]):
                raise ValueError("original retained checkpoint failed SHA/size binding")
    return old_runs


def family_summary(rows):
    all_families = sorted(set(row["family"] for row in rows))
    def summarize(sub):
        return {"n": len(sub), "accuracy": sum(r["correct"] for r in sub) / len(sub),
                "mean_binary_log_loss": statistics.fmean(r["log_loss"] for r in sub),
                "mean_brier": statistics.fmean(r["brier"] for r in sub),
                "yes_predictions": sum(r["prediction"] == "yes" for r in sub)}
    return {"overall": summarize(rows), "by_family": {
        f: summarize([r for r in rows if r["family"] == f]) for f in all_families}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--adapter-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.threads <= 8:
        raise ValueError("unsupported CPU thread budget")
    if args.out.exists():
        raise ValueError("output already exists: require immutable fresh result")
    plan = json.loads(args.plan.read_text())
    tasks = check_plan(plan)
    archive = json.loads(args.archive.read_text())
    old_runs = check_archive(archive, args.archive, args.model, args.adapter_root)
    # This public OOD list is operator-written and exposed; it is not a frozen
    # independent future B. Original B/C prompts also remain public.
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import torch
    import torch.nn.functional as F
    from transformers import AutoTokenizer, AutoModelForCausalLM
    from peft import PeftModel
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    if torch.cuda.is_available():
        raise RuntimeError("CPU-only contract violated")
    tok = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    yes_id = tok.encode(" yes", add_special_tokens=False)
    no_id = tok.encode(" no", add_special_tokens=False)
    if len(yes_id) != 1 or len(no_id) != 1 or yes_id[0] == no_id[0]:
        raise ValueError("unexpected two-class tokenizer")
    class_ids = torch.tensor([yes_id[0], no_id[0]], dtype=torch.long)
    def new_base():
        return AutoModelForCausalLM.from_pretrained(args.model, local_files_only=True,
                    dtype=torch.float32, attn_implementation="eager")
    def forward(model):
        outputs = []
        model.eval()
        with torch.inference_mode():
            for r in tasks:
                # Same next-token ' yes'/' no' scoring rule as the original V2
                # run. Do not switch prompt framing after observing labels.
                prompt = r["question"].strip() + "\nAnswer:"
                encoded = tok.encode(prompt, add_special_tokens=True)
                ids = torch.tensor([encoded], dtype=torch.long)
                logits = model(input_ids=ids, use_cache=False).logits[0, -1, class_ids]
                p_yes = float(F.softmax(logits.float(), dim=0)[0])
                p_truth = p_yes if r["truth"] == "yes" else 1 - p_yes
                pred = "yes" if p_yes >= .5 else "no"
                outputs.append({"id": r["id"], "family": r["family"],
                    "truth": r["truth"], "prediction": pred, "correct": pred == r["truth"],
                    "p_yes": round(p_yes, 9), "log_loss": round(-math.log(max(p_truth, 1e-12)), 9),
                    "brier": round((p_yes - (r["truth"] == "yes")) ** 2, 9),
                    "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()})
        return outputs
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    start_wall = time.perf_counter()
    start_cpu = time.process_time()
    start_io = io_counts()
    runs = []
    ordered = [("base", None, None)] + [
        (f"seed{seed} {arm}", seed, arm) for seed in SEEDS for arm in ARMS]
    for condition, seed, arm in ordered:
        b_wall, b_cpu, b_io = time.perf_counter(), time.process_time(), io_counts()
        model = new_base()
        if seed is not None:
            checkpoint = args.adapter_root / f"seed{seed}-{arm}-adapter"
            model = PeftModel.from_pretrained(model, checkpoint, is_trainable=False)
        load_wall = time.perf_counter() - b_wall
        f_wall = time.perf_counter()
        predictions = forward(model)
        inference_wall = time.perf_counter() - f_wall
        runs.append({"condition": condition, "seed": seed, "arm": arm,
            "original_plan_digest": (old_runs[(seed, arm)]["plan_digest"] if seed is not None else None),
            "scores": family_summary(predictions), "predictions": predictions,
            "cost": {"load_wall_seconds": load_wall, "inference_wall_seconds": inference_wall,
                     "load_plus_inference_wall_seconds": time.perf_counter() - b_wall,
                     "process_cpu_seconds": time.process_time() - b_cpu,
                     "io_delta": io_difference(b_io, io_counts()),
                     "ru_maxrss_kib_lifetime_peak": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}})
        del model
        gc.collect()
        print("OOD_CONDITION", condition, "ACC", runs[-1]["scores"]["overall"]["accuracy"],
              "LOGLOSS", round(runs[-1]["scores"]["overall"]["mean_binary_log_loss"], 5),
              "CUM_WALL", round(time.perf_counter() - start_wall, 2), flush=True)
    by_condition = {r["condition"]: r for r in runs}
    paired = []
    for seed in SEEDS:
        inter, burst = by_condition[f"seed{seed} interleaved"], by_condition[f"seed{seed} bursty"]
        paired.append({"seed": seed, "bursty_minus_interleaved_accuracy":
                       burst["scores"]["overall"]["accuracy"] - inter["scores"]["overall"]["accuracy"],
                       "bursty_minus_interleaved_logloss":
                       burst["scores"]["overall"]["mean_binary_log_loss"] - inter["scores"]["overall"]["mean_binary_log_loss"]})
    report = {"schema": SCHEMA, "authority": "DENY_ALL_HOLD_NO_GO",
        "evaluation": "PUBLIC_OPERATOR_OOD_EXPLORATORY_NOT_INDEPENDENT",
        "source_plan_pr": 5960, "precommitted_plan_head": PLAN_HEAD,
        "original_training_pr": 5905, "started_utc": started,
        "ended_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "script_sha256": sha256(__file__), "plan_sha256": sha256(args.plan),
        "original_training_result_sha256": sha256(args.archive),
        "model_identities": archive["identities"],
        "task_count_per_condition": len(tasks), "task_families": list(FAMILIES),
        "conditions": [r["condition"] for r in runs],
        "cpu_only": True, "torch_version": torch.__version__,
        "transformers_version": __import__("transformers").__version__,
        "peft_version": __import__("peft").__version__,
        "threads": args.threads, "runs": runs, "paired": paired,
        "full_run_cost": {"wall_seconds": time.perf_counter() - start_wall,
                         "process_cpu_seconds": time.process_time() - start_cpu,
                         "io_delta": io_difference(start_io, io_counts()),
                         "ru_maxrss_kib_lifetime_peak": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss},
        "baselines": {"constant_no_accuracy": 0.5, "constant_yes_accuracy": 0.5},
        "not_measured": ["independent future evaluation and effect receipts",
            "actual production task correctness", "Owner adoption or NoUpdate execution",
            "seven-lineage model training", "end-to-end energy or dollar charges",
            "Core-NDU 2x2", "real task C and Root/Agentd cold owner recovery"],
        "selection": "NO_UPDATE_RECOMMENDED_RESEARCH_ONLY_NOT_OWNER_DECISION"}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as output:
        json.dump(report, output, sort_keys=True, indent=2, allow_nan=False)
        output.write("\n")
    print("RESULT_PATH", args.out, "SHA256", sha256(args.out), "HOLD_NO_GO", flush=True)


if __name__ == "__main__":
    main()
