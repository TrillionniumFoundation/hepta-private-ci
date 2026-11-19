#!/usr/bin/env python3
"""Qualification-only deterministic arithmetic control for frozen operator B2.

No model, hidden labels, owner input, action receipt, training or deployment rights.
All decisions derive solely from exact prompt syntax. HOLD_NO_GO / DENY_ALL.
"""
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
import re
import resource
import time

MANIFEST_SHA = "0f12ac4aa7fd32989ba62983ed82367b83fe6a3f51868e4c1b8f567a9decf12a"
RESULT_SHA = "937a87f1da2e502f954be0870cd3a64ce06df0245938fc984b8b2a5ed0d95731"
FAMILIES = ("even", "comparison", "divisibility", "set_membership", "prime")
PREFIX = "Answer yes or no. "
PATTERNS = (
    ("even", re.compile(r"Is ([0-9]+) an even integer\?")),
    ("comparison", re.compile(r"Is ([0-9]+) strictly greater than ([0-9]+)\?")),
    ("divisibility", re.compile(r"Is the integer ([0-9]+) divisible by ([0-9]+) with no remainder\?")),
    ("set_membership", re.compile(r"Does the number ([0-9]+) occur in the set \{([0-9]+(?:, [0-9]+)*)\}\?")),
    ("prime", re.compile(r"Is ([0-9]+) a prime integer\?")),
)

def decide(prompt: str) -> tuple[str, str]:
    if not isinstance(prompt, str) or not prompt.startswith(PREFIX):
        raise ValueError("not an admitted arithmetic prompt")
    text = prompt[len(PREFIX):]
    matches = [(family, m) for family, pattern in PATTERNS
               if (m := pattern.fullmatch(text)) is not None]
    if len(matches) != 1:
        raise ValueError("ambiguous or unrecognized arithmetic prompt")
    family, match = matches[0]
    args = match.groups()
    if family == "even":
        yes = int(args[0]) % 2 == 0
    elif family == "comparison":
        yes = int(args[0]) > int(args[1])
    elif family == "divisibility":
        d = int(args[1])
        if not d:
            raise ValueError("zero divisor")
        yes = int(args[0]) % d == 0
    elif family == "set_membership":
        yes = int(args[0]) in [int(x) for x in args[1].split(", ")]
    else:
        n = int(args[0])
        yes = n >= 2 and all(n % k for k in range(2, math.isqrt(n) + 1))
    return family, "yes" if yes else "no"

def read_exact(path: Path, expected: str) -> dict:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("original archive byte identity mismatch")
    return json.loads(raw)

def evaluate(manifest: dict, result: dict, repeats: int = 9) -> dict:
    if type(repeats) is not int or repeats < 1 or repeats > 10000:
        raise ValueError("invalid work repetition")
    tasks = manifest["tasks"]
    if (len(tasks) != 60 or len({t["id"] for t in tasks}) != 60
            or manifest["scope"] != "operator-constructed arithmetic only; not an independent evaluator"
            or result["authority"] != "DENY_ALL" or len(result["runs"]) != 9):
        raise ValueError("wrong scope or roster")
    orig_runs = result["runs"]
    for run in orig_runs:
        rows = run["scores"]["rows"]
        if (len(rows) != 60 or [r["id"] for r in rows] != [t["id"] for t in tasks]
                or any(r["prediction"] != "no" for r in rows)):
            raise ValueError("model output roster changed or nonconstant")
    counts, positive = Counter(), Counter()
    start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
    predictions = []
    for k in range(repeats):
        for task in tasks:
            family, prediction = decide(task["prompt"])  # Never reads truth.
            if (family != task["family"] or task["truth"] not in ("yes", "no")
                    or family not in FAMILIES):
                raise ValueError("family or target metadata invalid")
            counts[family] += 1
            if prediction == task["truth"]:
                positive[family] += 1
            else:
                raise ValueError("operator B2 key disagrees with arithmetical truth")
            if k == 0:
                predictions.append({"id": task["id"], "family": family, "prediction": prediction})
    elapsed_wall = time.perf_counter_ns() - start_wall
    elapsed_cpu = time.process_time_ns() - start_cpu
    if Counter(counts) != Counter({name: 12 * repeats for name in FAMILIES}):
        raise ValueError("wrong family counts")
    return {
        "identity": {"manifest_sha256": MANIFEST_SHA, "model_result_sha256": RESULT_SHA},
        "scope": "same 60 operator arithmetic prompts; syntax-specific direct computation; not independent B",
        "authority": "DENY_ALL", "qualification": "HOLD_NO_GO",
        "repeats": repeats, "unique_tasks": len(tasks),
        "rule_decisions": sum(counts.values()), "rule_correct": sum(positive.values()),
        "rule_family_accuracy": {f: positive[f] / counts[f] for f in FAMILIES},
        "original_model_runs": len(orig_runs),
        "original_model_decisions": sum(len(r["scores"]["rows"]) for r in orig_runs),
        "original_model_correct": sum(sum(int(r["correct"]) for r in run["scores"]["rows"]) for run in orig_runs),
        "original_model_constant_no": True,
        "rule_wall_seconds_warm_loop": elapsed_wall / 1e9,
        "rule_cpu_seconds_warm_loop": elapsed_cpu / 1e9,
        "rule_process_maxrss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "owner_attested": False, "evaluator_independent": False, "training_performed": False,
        "model_forward_performed": False, "cost_comparable": False,
        "predictions_60_unique": predictions,
    }

def run(directory: Path, repeats: int = 9) -> dict:
    return evaluate(
        read_exact(directory / "POSTTRAIN_B2_MANIFEST.json", MANIFEST_SHA),
        read_exact(directory / "POSTTRAIN_B2_RESULT.json", RESULT_SHA),
        repeats=repeats,
    )

if __name__ == "__main__":
    source = Path(__file__).resolve().parent
    print(json.dumps(run(source), sort_keys=True, indent=2))
