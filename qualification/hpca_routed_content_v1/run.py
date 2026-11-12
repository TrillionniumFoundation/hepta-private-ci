#!/usr/bin/env python3
"""Real frozen-LM content-head development experiment; no production adoption."""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import resource
import time

import numpy as np
import credit

ROOT = Path(__file__).resolve().parent
SOURCE_NAMES = (
    "run.py",
    "credit.py",
    "PLAN.json",
    "TASKS.json",
    "TRAIN_FEEDBACK.json",
    "EVAL_LABELS.json",
    "build_data.py",
)


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            h.update(block)
    return h.hexdigest()


def write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def sources():
    return {name: sha(ROOT / name) for name in SOURCE_NAMES}


def validate_inputs(plan, tasks, labels):
    if len(tasks) != 160 or len({t["id"] for t in tasks}) != 160:
        raise ValueError("task identity denominator")
    if len({t["question"] for t in tasks}) != 160:
        raise ValueError("duplicate question")
    if any(
        "truth" in t or type(t["group"]) is not int or t["group"] not in (0, 1)
        for t in tasks
    ):
        raise ValueError("truth leaked into prompts or invalid routing metadata")
    train = [t for t in tasks if t["split"] == "train"]
    if len(train) != 64 or set(labels) != {t["id"] for t in train}:
        raise ValueError("training feedback roster")
    if any(x not in ("yes", "no") for x in labels.values()):
        raise ValueError("training feedback values")
    if {
        s: sum(t["split"] == s for t in tasks)
        for s in ("train", "content", "retention")
    } != {"train": 64, "content": 64, "retention": 32}:
        raise ValueError("split denominators")
    if any(
        sum(t["pair"] == p and t["group"] == g for t in train) != 1
        for p in range(32)
        for g in range(2)
    ):
        raise ValueError("incomplete training pair")
    clusters = {}
    for t in tasks:
        prior = clusters.setdefault(t["source_cluster"], t["split"])
        if prior != t["split"]:
            raise ValueError("source cluster crosses training/evaluation")
    for name, expected in plan["data_sha256"].items():
        if sha(ROOT / name) != expected:
            raise ValueError("frozen data bytes changed: " + name)
    if plan["independent_future_B"] is not False or plan["decision"] != "HOLD_NO_GO":
        raise ValueError("unqualified authority")
    return train


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("model", "out", "publication"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--replay-source", type=Path)
    parser.add_argument("--expected-result-sha256")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    started, cpu_started = time.perf_counter(), time.process_time()
    source_pins = sources()
    publication = json.loads(args.publication.read_bytes())
    if (
        not re.fullmatch(r"[0-9a-f]{40}", publication.get("commit", ""))
        or publication.get("sources") != source_pins
    ):
        raise ValueError("publication source binding")
    publication_hash = sha(args.publication)
    plan = json.loads((ROOT / "PLAN.json").read_bytes())
    tasks = json.loads((ROOT / "TASKS.json").read_bytes())["tasks"]
    labels = json.loads((ROOT / "TRAIN_FEEDBACK.json").read_bytes())
    training = validate_inputs(plan, tasks, labels)
    assets = {name: sha(args.model / name) for name in plan["model_sha256"]}
    if assets != plan["model_sha256"]:
        raise ValueError("frozen model asset identity")
    os.environ.update(
        CUDA_VISIBLE_DEVICES="", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1"
    )
    import torch
    import transformers

    torch.set_num_threads(plan["threads"])
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    runtime = {
        "torch": torch.__version__,
        "transformers": transformers.__version__,
        "python": platform.python_version(),
        "numpy": np.__version__,
    }
    if any(runtime[k] != v for k, v in plan["required_runtime"].items()):
        raise ValueError("runtime differs from preregistration")
    if torch.cuda.is_available():
        raise ValueError("CPU protocol")
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        args.model, local_files_only=True, use_fast=True
    )
    if not tokenizer.is_fast:
        raise ValueError("pinned self-contained fast tokenizer required")
    target_ids = [
        tokenizer.encode(word, add_special_tokens=False) for word in ("Yes", "No")
    ]
    if any(len(ids) != 1 for ids in target_ids) or target_ids[0] == target_ids[1]:
        raise ValueError("preregistered single-token answer markers unavailable")
    yes, no = (ids[0] for ids in target_ids)
    encodings = {}
    for task in tasks:
        text = (
            "Answer the following question with exactly YES or NO. Do not explain.\nQuestion: "
            + task["question"]
        )
        ids = tokenizer.apply_chat_template(
            [{"role": "user", "content": text}],
            tokenize=True,
            add_generation_prompt=True,
        )
        if (
            not 1 <= len(ids) <= plan["max_prompt_tokens"]
            or ids[-1] == tokenizer.eos_token_id
        ):
            raise ValueError("prompt exceeds frozen budget or ends with EOS")
        encodings[task["id"]] = ids
    load_begin = time.perf_counter()
    model = transformers.AutoModelForCausalLM.from_pretrained(
        args.model,
        local_files_only=True,
        dtype=torch.float32,
        attn_implementation="eager",
    )
    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    model_load_seconds = time.perf_counter() - load_begin
    pre = {
        "schema": "hpca-routed-content-preexecution-v1",
        "source_publication": publication,
        "source_sha256": source_pins,
        "assets": assets,
        "runtime": runtime,
        "target_token_ids": {"Yes": yes, "No": no},
        "prompt_token_ids": encodings,
        "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "decision": "HOLD_NO_GO",
        "independent_future_B": False,
        "body_trainable_parameters": 0,
        "evaluation_labels_parsed_before_training": False,
        "evaluation_label_bytes_hashed_before_training": True,
        "generation": "unrestricted full-vocabulary greedy, first-token private-head edit only",
    }
    write(args.out / "PREEXECUTION.json", pre)

    def prefill(task):
        x = torch.tensor([encodings[task["id"]]], dtype=torch.long)
        output = model(
            input_ids=x,
            attention_mask=torch.ones_like(x),
            use_cache=True,
            output_hidden_states=True,
        )
        hidden = output.hidden_states[-1][0, -1].detach().cpu().numpy()
        return output, credit.feature(hidden), x.shape[1]

    def generate(task, weights):
        begin = time.perf_counter()
        with torch.inference_mode():
            output, f, prefix_length = prefill(task)
            emitted, first_delta = [], float(weights[task["group"]] @ f)
            for step in range(plan["max_new_tokens"]):
                logits = output.logits[0, -1].detach().cpu().numpy().astype(np.float64)
                if step == 0:
                    logits[yes] += first_delta
                    logits[no] -= first_delta
                token = int(np.argmax(logits))
                emitted.append(token)
                if (
                    token == tokenizer.eos_token_id
                    or step + 1 == plan["max_new_tokens"]
                ):
                    break
                output = model(
                    input_ids=torch.tensor([[token]], dtype=torch.long),
                    attention_mask=torch.ones(
                        (1, prefix_length + len(emitted)), dtype=torch.long
                    ),
                    past_key_values=output.past_key_values,
                    use_cache=True,
                )
        return {
            "id": task["id"],
            "split": task["split"],
            "group": task["group"],
            "source_cluster": task["source_cluster"],
            "status": "completed",
            "tokens": emitted,
            "text": tokenizer.decode(emitted, skip_special_tokens=True),
            "first_token_head_delta": first_delta,
            "feature_sha256": credit.digest_array(f),
            "body_forward_calls": len(emitted),
            "wall_seconds": time.perf_counter() - begin,
        }

    def record_attempt(task, weights, condition, journal, earlier=None):
        journal.write(
            json.dumps(
                {"event": "attempt_started", "condition": condition, "id": task["id"]}
            )
            + "\n"
        )
        journal.flush()
        try:
            row = generate(task, weights)
        except Exception as error:
            row = {
                "id": task["id"],
                "split": task["split"],
                "group": task["group"],
                "source_cluster": task["source_cluster"],
                "status": "failed",
                "error_type": type(error).__name__,
                "error": str(error)[:1000],
                "text": "",
                "tokens": [],
            }
        row["condition"] = condition
        if earlier is not None:
            row["exact_replay"] = (
                row["status"] == earlier["status"] == "completed"
                and row["tokens"] == earlier["tokens"]
                and row["feature_sha256"] == earlier["feature_sha256"]
                and row["first_token_head_delta"] == earlier["first_token_head_delta"]
            )
        journal.write(
            json.dumps({"event": "row_completed", "row": row}, allow_nan=False) + "\n"
        )
        journal.flush()
        os.fsync(journal.fileno())
        return row

    if args.replay_source is not None:
        result_path = args.replay_source / "RESULT.json"
        if sha(result_path) != args.expected_result_sha256:
            raise ValueError("original result identity")
        original = json.loads(result_path.read_bytes())
        if original["source_publication"] != publication["commit"]:
            raise ValueError("replay source mismatch")
        expected = {(r["condition"], r["id"]): r for r in original["rows"]}
        subset = [t for t in tasks if t["id"] in plan["cold_task_ids"]]
        if len(subset) != 12 or len(original["conditions"]) != 17:
            raise ValueError("cold replay denominator")
        rows = []
        with (args.out / "ROWS.jsonl").open("x") as journal:
            for condition in original["conditions"]:
                path = args.replay_source / condition["weights_file"]
                if sha(path) != condition["weights_sha256"]:
                    raise ValueError("cold checkpoint changed")
                weights = np.asarray(json.loads(path.read_bytes())["weights"])
                for task in subset:
                    earlier = expected[(condition["condition"], task["id"])]
                    rows.append(
                        record_attempt(
                            task, weights, condition["condition"], journal, earlier
                        )
                    )
        if len(rows) != 204:
            raise ValueError("incomplete cold replay attempt denominator")
        report = {
            "schema": "hpca-routed-content-cold-replay-v1",
            "rows": rows,
            "planned_generation_attempts": 204,
            "rows_sha256": sha(args.out / "ROWS.jsonl"),
            "all_exact": all(r["exact_replay"] for r in rows),
            "original_result_sha256": args.expected_result_sha256,
            "source_publication": publication["commit"],
            "independent_future_B": False,
            "decision": "HOLD_NO_GO",
        }
    else:
        cache_begin = time.perf_counter()
        cached = {}
        with torch.inference_mode():
            for task in training:
                output, f, _ = prefill(task)
                logits = output.logits[0, -1].detach().cpu().numpy().astype(np.float64)
                other = logits.copy()
                other[[yes, no]] = -np.inf
                cached[task["id"]] = {
                    "feature": f.tolist(),
                    "normalizer": [
                        float(logits[yes]),
                        float(logits[no]),
                        float(np.logaddexp.reduce(other)),
                    ],
                }
        write(args.out / "TRAIN_FEATURES.json", cached)
        cache_seconds = time.perf_counter() - cache_begin
        by_key = {(t["pair"], t["group"]): t for t in training}
        features = np.array(
            [
                [cached[by_key[(p, g)]["id"]]["feature"] for g in range(2)]
                for p in range(32)
            ]
        )
        normalizer = np.array(
            [
                [cached[by_key[(p, g)]["id"]]["normalizer"] for g in range(2)]
                for p in range(32)
            ]
        )
        teacher = np.array(
            [
                [1 if labels[by_key[(p, g)]["id"]] == "yes" else -1 for g in range(2)]
                for p in range(32)
            ]
        )
        candidates, metadata, feedback_pins = {}, [], {}
        training_begin = time.perf_counter()
        candidates["base"] = np.zeros(features.shape[1:])
        write(args.out / "weights-base.json", {"weights": candidates["base"].tolist()})
        metadata.append(
            {
                "condition": "base",
                "weights_file": "weights-base.json",
                "manual_sgd_calls": 0,
            }
        )
        for seed in plan["seeds"]:
            for arm in plan["arms"]:
                name = f"seed{seed}-{arm}"
                weights, receipts, feedback_pin = credit.train(
                    features, normalizer, teacher, seed, arm, plan
                )
                if seed in feedback_pins and feedback_pins[seed] != feedback_pin:
                    raise ValueError("external feedback vector differs between arms")
                feedback_pins[seed] = feedback_pin
                candidates[name] = weights
                filename = "weights-" + name + ".json"
                write(
                    args.out / filename,
                    {
                        "weights": weights.tolist(),
                        "state_sha256": credit.digest_array(weights),
                    },
                )
                write(
                    args.out / ("train-" + name + ".json"),
                    {"receipts": receipts, "feedback_sha256": feedback_pin},
                )
                metadata.append(
                    {
                        "condition": name,
                        "seed": seed,
                        "arm": arm,
                        "weights_file": filename,
                        "manual_sgd_calls": len(receipts),
                        "nonzero_updates": sum(r["delta_norm"] > 0 for r in receipts),
                        "feedback_sha256": feedback_pin,
                    }
                )
                print(
                    "TRAINED",
                    name,
                    len(receipts),
                    credit.digest_array(weights),
                    flush=True,
                )
        for condition in metadata:
            condition["weights_sha256"] = sha(args.out / condition["weights_file"])
        write(args.out / "FROZEN_CANDIDATES.json", metadata)
        training_seconds = time.perf_counter() - training_begin
        # First evaluation-label read occurs only after every candidate is frozen.
        eval_labels = json.loads((ROOT / "EVAL_LABELS.json").read_bytes())
        evaluation = [t for t in tasks if t["split"] != "train"]
        if set(eval_labels) != {t["id"] for t in evaluation}:
            raise ValueError("evaluation label denominator")
        rows, all_scores = [], {}
        with (args.out / "ROWS.jsonl").open("x") as journal:
            for condition in metadata:
                name = condition["condition"]
                condition_begin = time.perf_counter()
                for task in evaluation:
                    rows.append(record_attempt(task, candidates[name], name, journal))
                part = [r for r in rows if r["condition"] == name]
                scores = {
                    s: credit.score([r for r in part if r["split"] == s], eval_labels)
                    for s in ("content", "retention")
                }
                all_scores[name] = scores
                condition["evaluation_wall_seconds"] = (
                    time.perf_counter() - condition_begin
                )
                print("EVALUATED", name, json.dumps(scores, sort_keys=True), flush=True)
        if len(rows) != 1632:
            raise ValueError("incomplete planned generation denominator")
        for condition in metadata:
            if sha(args.out / condition["weights_file"]) != condition["weights_sha256"]:
                raise ValueError("candidate mutated during evaluation")
        report = {
            "schema": "hpca-routed-content-development-v1",
            "source_publication": publication["commit"],
            "conditions": metadata,
            "scores": all_scores,
            "rows": rows,
            "planned_generation_attempts": 1632,
            "training_prefill_calls": 64,
            "manual_sgd_calls": sum(c["manual_sgd_calls"] for c in metadata),
            "torch_optimizer_calls": 0,
            "model_load_seconds": model_load_seconds,
            "training_prefill_seconds": cache_seconds,
            "head_training_seconds": training_seconds,
            "feedback_same_across_arms": True,
            "feedback_sha256_by_seed": feedback_pins,
            "retention_competency_gate": all_scores["base"]["retention"]["correct"]
            >= 24
            and all_scores["base"]["retention"]["valid"] >= 28,
            "frozen_candidates_sha256": sha(args.out / "FROZEN_CANDIDATES.json"),
            "rows_sha256": sha(args.out / "ROWS.jsonl"),
            "body_weight_updates": 0,
            "independent_future_B": False,
            "decision": "HOLD_NO_GO",
        }
    if source_pins != sources() or publication_hash != sha(args.publication):
        raise ValueError("source changed during execution")
    if {name: sha(args.model / name) for name in assets} != assets:
        raise ValueError("model bytes changed during execution")
    report.update(
        {
            "wall_seconds": time.perf_counter() - started,
            "cpu_seconds": time.process_time() - cpu_started,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "preexecution_sha256": sha(args.out / "PREEXECUTION.json"),
            "finished_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "cost_excludes": [
                "source preparation",
                "queue",
                "prior model training",
                "energy",
                "Owner lifecycle",
            ],
        }
    )
    report.update(credit.generation_counts(rows))
    write(args.out / "RESULT.json", report)
    print(
        "RESULT",
        sha(args.out / "RESULT.json"),
        report["actual_generations"],
        flush=True,
    )


if __name__ == "__main__":
    main()
