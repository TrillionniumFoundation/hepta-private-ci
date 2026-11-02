"""Preselected first-value episodes: actual frozen neural forward replay.

This deliberately imports the producer's Model architecture to reload its
weights. It is neural replay, separate from the independent standard-library
finite-path numerical and raw-record auditor.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import torch

from experiments.hcsn_v10_followup_20261101.persistent_av import candidate as model_code
from experiments.hcsn_v8_execution_20261101.frontend.legacy_v3 import BinnedCorrectness, LegacyV3Head


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def replay(directory, destination):
    destination.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    specification = {
        "selection": "Every task x seed x family: index=0, policy=value, implementation=expm",
        "expected_cases": 16, "selection_origin": "Parent's explicit predeclared replay request",
        "numerical_requirement": "Exact FP64 neural hidden-state and candidate forward values; exact common-head probabilities",
        "source_sha256": sha(__file__), "candidate_source_sha256": sha(model_code.__file__),
        "traces_sha256": sha(directory / "TRACES.jsonl.gz"), "torch": torch.__version__,
        "python": sys.version, "threads": 1,
        "scope": "Uses producer Model/common-head implementation, not an independent architecture or training implementation",
    }
    with (destination / "PLAN.json").open("x") as stream:
        json.dump(specification, stream, indent=2)
        stream.write("\n")
    with gzip.open(directory / "TRACES.jsonl.gz", "rt") as stream:
        selected = [row for row in map(json.loads, stream) if row["index"] == 0 and row["policy"] == "value" and row["implementation"] == "expm"]
    checks, failures, cases, hidden_steps, candidate_values = 0, [], [], 0, 0

    def check(ok, label):
        nonlocal checks
        checks += 1
        if not ok and len(failures) < 30:
            failures.append(label)

    check(len(selected) == 16, "all preselected episodes present")
    frozen = json.loads((directory / "FROZEN.json").read_text())
    for row in selected:
        task, seed, family = row["task"], row["seed"], row["family"]
        record = next(r for r in frozen["models"] if (r["task"], r["seed"], r["family"]) == (task, seed, family))
        checkpoint = directory / record["path"]
        check(sha(checkpoint) == record["sha256"], "frozen neural checkpoint")
        model = model_code.Model(family)
        model.load_state_dict(torch.load(checkpoint, weights_only=True, map_location="cpu"))
        model.eval()
        h = torch.zeros((1, 64), dtype=torch.float64)
        by_fingerprint, rows = {}, []
        local_hidden, local_values = 0, 0
        for update in row["updates"]:
            value = torch.tensor(update["row"], dtype=torch.float64)[None]
            with torch.no_grad():
                h = model.update_state(value, h)
            check(torch.equal(h, torch.tensor(update["hidden"], dtype=torch.float64)), "exact saved 64-scalar hidden forward")
            rows.append(update["row"])
            padded = np.zeros((6, 58)); padded[:len(rows)] = rows
            history = torch.tensor(np.r_[padded.ravel(), np.arange(6) < len(rows)])[None]
            belief = np.zeros(256)
            if family == "filter":
                belief[:len(update["path_probability"])] = update["path_probability"]
            with torch.no_grad():
                correctness = model.predict(history, h, torch.tensor(belief)[None]).sigmoid()[0].tolist()
            by_fingerprint[update["content_fingerprint"]] = (correctness, update["row"])
            hidden_steps += 1
            local_hidden += 1
        for decision in row["execution"]["decisions"]:
            probabilities, current = by_fingerprint[decision["content_fingerprint"]]
            original_levels = {"audio": round(current[38]*3), "video": round(current[39]*3)}
            plans = []
            for item in decision["plans"]:
                levels = dict(original_levels)
                for step in item["plan"].split("/"):
                    kind, modality, endpoint = step.split(":")
                    check(kind == "READ", "preselected candidate has only public READ steps")
                    levels[modality] = int(endpoint)
                prediction = probabilities[model_code.base.LEVELS.index((levels["audio"], levels["video"]))]
                check(prediction == item["correctness"], "exact actual neural candidate forecast")
                score = prediction - .02*item["expected_requested_reads"] - .005*item["expected_seconds"] - item["deadline_miss_probability"]
                check(score == item["score"], "exact priced replay candidate")
                plans.append((score, item["plan"]))
                candidate_values += 1
                local_values += 1
            best = max(plans, default=None)
            chosen = best[1] if best is not None and best[0] > decision["stop_score"] else None
            check(chosen == decision["selected"], "actual neural replay preserves strict selected action")
        adapter = json.loads((directory / task / f"{task}_ADAPTERS.json").read_text())
        head = LegacyV3Head(task, BinnedCorrectness(**adapter["calibrator"]))
        data = model_code.base.legacy_data(task, "test")
        last = row["updates"][-1]["row"]
        content = model_code.base.populated_cache(data, row["index"], round(last[38]*3), round(last[39]*3))
        check(np.array_equal(head.classify(content), row["execution"]["output"]["probabilities"]), "exact frozen common-head final probabilities")
        cases.append({"task": task, "seed": seed, "family": family, "index": 0,
                      "hidden_steps": local_hidden, "candidate_values": local_values,
                      "checkpoint_sha256": record["sha256"]})
    result = {"schema": "hcsn-v10-preselected-neural-forward-replay.v1", "checks": checks,
              "all_checks_passed": not failures, "failed_examples": failures, "cases": cases,
              "hidden_steps": hidden_steps, "candidate_forecasts": candidate_values,
              "scope": specification["scope"], "source_unchanged": sha(__file__) == specification["source_sha256"]}
    with (destination / "RESULT.json").open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(result))
    return result["all_checks_passed"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if replay(args.directory, args.out) else 1)
