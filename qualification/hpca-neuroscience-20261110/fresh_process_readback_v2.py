#!/usr/bin/env python3
"""Fresh-OS-process readback of HPCA V2 exposed LoRA adapters. Research only.

Unlike the training script's same-process reload, this is invoked in a new
heptaruntime durable job and loads the original files from disk. Does not
authenticate an owner or certify an independently selected future task.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import time

ORIGINAL_RESULT_SHA256 = "9512849b90964c35951bb8bb2226b3f2f6d3ec0da1e9a3b98467c8970afbe39c"
ORIGINAL_TRAINING_SCRIPT_SHA256 = "4dded105ac0477c9747b13d98ee1b57d46dcc322d034121a55a9c63a12250e5e"
ARMS = {"interleaved", "bursty"}
SEEDS = {11, 17, 23, 29}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def io_counts():
    try:
        return {k.strip(): int(v) for line in Path("/proc/self/io").read_text().splitlines()
                for k, v in [line.split(":", 1)]}
    except (OSError, ValueError):
        return {}


def check_rows(actual, recorded, *, tolerance=1e-5):
    """Compare every task, label, prompt hash, decision and scored probability."""
    if len(actual) != len(recorded):
        raise ValueError("changed evaluation row count")
    maximum = 0.0
    for got, expect in zip(actual, recorded):
        for field in ("id", "truth", "prediction", "prompt_sha256", "correct"):
            if got[field] != expect[field]:
                raise ValueError("evaluation identity or outcome mismatch: " + field)
        difference = abs(got["p_yes"] - expect["p_yes"])
        if not 0 <= difference <= tolerance:
            raise ValueError("cold model probability drift")
        maximum = max(maximum, difference)
    return maximum


def main():
    parser = argparse.ArgumentParser()
    for key in ("model", "fixture", "original_result", "adapter_root", "out"):
        parser.add_argument("--" + key.replace("_", "-"), required=True)
    parser.add_argument("--threads", type=int, default=4)
    a = parser.parse_args()
    if not 1 <= a.threads <= 16:
        raise ValueError("invalid threads")
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    started = time.perf_counter()
    cpu_started = time.process_time()
    io_before = io_counts()

    parent_path = Path(a.original_result)
    if sha256(parent_path) != ORIGINAL_RESULT_SHA256:
        raise ValueError("different original training archive")
    parent = json.loads(parent_path.read_text())
    from native_lora_clock_v2 import C_TASKS, load_fixture, prompt, digest
    source_script = Path(__file__).with_name("native_lora_clock_v2.py")
    if sha256(source_script) != ORIGINAL_TRAINING_SCRIPT_SHA256:
        raise ValueError("different original training executable")
    model_dir = Path(a.model)
    identity_files = {"model_safetensors_sha256": "model.safetensors",
                      "config_sha256": "config.json",
                      "tokenizer_sha256": "tokenizer.json"}
    for field, name in identity_files.items():
        if sha256(model_dir / name) != parent["identities"][field]:
            raise ValueError("changed pinned model identity: " + name)
    if sha256(a.fixture) != parent["identities"]["exposed_fixture_sha256"]:
        raise ValueError("changed fixture")
    split = load_fixture(a.fixture)
    B = sorted(split["evaluation"], key=lambda row: row["id"])
    C = [{"id": "OOD-C" + str(i), "prompt": "Answer yes or no. " + q,
          "expected_output": label} for i, (q, label) in enumerate(C_TASKS)]
    if len(B) != 4 or len(C) != 8:
        raise ValueError("evaluation panel changed")
    runs = parent["runs"]
    if (len(runs) != 8 or
        {(int(r["seed"]), r["arm"]) for r in runs} != {(s, arm) for s in SEEDS for arm in ARMS}):
        raise ValueError("original arm roster changed")
    import torch
    import torch.nn.functional as F
    from transformers import AutoTokenizer, AutoModelForCausalLM
    from peft import PeftModel
    torch.set_num_threads(a.threads)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    if torch.cuda.is_available():
        raise ValueError("GPU violates frozen CPU comparison")
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    yes_ids = tokenizer.encode(" yes", add_special_tokens=False)
    no_ids = tokenizer.encode(" no", add_special_tokens=False)
    if len(yes_ids) != 1 or len(no_ids) != 1 or yes_ids == no_ids:
        raise ValueError("tokenizer target contract changed")
    class_ids = torch.tensor([yes_ids[0], no_ids[0]], dtype=torch.long)

    def infer(model, panel):
        observed = []
        model.eval()
        with torch.inference_mode():
            for row in panel:
                ids = torch.tensor([tokenizer.encode(prompt(row["prompt"]),
                                    add_special_tokens=True)], dtype=torch.long)
                logits = model(input_ids=ids, use_cache=False).logits[0, -1, class_ids]
                prob_yes = F.softmax(logits.float(), dim=0)[0].item()
                predicted = "yes" if prob_yes >= 0.5 else "no"
                observed.append({"id": row["id"], "truth": row["expected_output"],
                    "prediction": predicted, "correct": predicted == row["expected_output"],
                    "p_yes": round(prob_yes, 9),
                    "prompt_sha256": hashlib.sha256(row["prompt"].encode()).hexdigest()})
        return observed

    observed = []
    adapter_root = Path(a.adapter_root)
    for row in runs:
        seed, arm = int(row["seed"]), row["arm"]
        adapter = adapter_root / f"seed{seed}-{arm}-adapter"
        declared = row["checkpoint_files"]
        actual_names = {p.name for p in adapter.iterdir() if p.is_file()}
        if actual_names != set(declared):
            raise ValueError("checkpoint file manifest changed")
        for name, record in declared.items():
            p = adapter / name
            if sha256(p) != record["sha256"] or p.stat().st_size != record["bytes"]:
                raise ValueError("adapter bytes differ from original archived declaration")
        started_arm = time.perf_counter()
        base = AutoModelForCausalLM.from_pretrained(model_dir,
            local_files_only=True, dtype=torch.float32, attn_implementation="eager")
        model = PeftModel.from_pretrained(base, adapter, is_trainable=False)
        diffs = {}
        scores = {}
        for key, panel in (("B_exposed_eval", B), ("C_operator_constructed", C)):
            predictions = infer(model, panel)
            diffs[key] = check_rows(predictions, row["scores"][key]["rows"])
            scores[key] = sum(q["correct"] for q in predictions) / len(predictions)
            if scores[key] != row["scores"][key]["accuracy"]:
                raise ValueError("cold readback score differs")
        observed.append({"seed": seed, "arm": arm,
            "checkpoint_file_sha256": {n: declared[n]["sha256"] for n in sorted(declared)},
            "B_accuracy": scores["B_exposed_eval"], "C_accuracy": scores["C_operator_constructed"],
            "max_B_p_yes_difference": diffs["B_exposed_eval"],
            "max_C_p_yes_difference": diffs["C_operator_constructed"],
            "fresh_load_infer_wall_seconds": time.perf_counter() - started_arm})
        print("FRESH_READBACK", seed, arm, scores, flush=True)
        del model, base

    evidence = {"schema": "hpca.v2.fresh_process_readback.v1",
        "qualification": "HOLD_NO_GO", "authority": "DENY_ALL",
        "interpretation": "actual fresh OS process, same host; exposed task probes only; NOT native owner recovery",
        "original_result_sha256": sha256(parent_path),
        "original_training_script_sha256": sha256(source_script),
        "consumer_script_sha256": sha256(__file__),
        "declared_original_model_identity": parent["identities"],
        "original_training_arms": len(runs), "fresh_process_evaluated_arms": len(observed),
        "fresh_process_task_forwards": len(observed) * (len(B) + len(C)),
        "torch": torch.__version__, "threads": a.threads, "cpu_only": True,
        "full_consumer_wall_seconds": time.perf_counter() - started,
        "full_consumer_cpu_seconds": time.process_time() - cpu_started,
        "process_ru_maxrss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "io_delta": {k: v - io_before.get(k, 0) for k, v in io_counts().items()},
        "arms": observed,
        "not_proved": ["original owner signature", "independent B", "future task C",
                      "production FinalUse", "cold original owner / Root recovery",
                      "energy and entire ecosystem cost", "scientific utility improvement"]}
    with open(a.out, "x", encoding="utf-8") as handle:
        json.dump(evidence, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    print("PASS_FRESH_PROCESS_READBACK", a.out, sha256(a.out), flush=True)


if __name__ == "__main__":
    main()

