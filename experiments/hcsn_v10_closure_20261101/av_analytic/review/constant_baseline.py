"""Post-freeze validation-motivated constant forecast; original B is retained."""

import argparse
import gzip
import json
from pathlib import Path

import numpy as np
import torch

from .. import interfaces as base
from ..campaign import configure_assets, plan_at, sha, write


class ConstantForecast:
    kind = base.BackendKind.DIRECT_HISTORY
    reader_id = "historical-validation-constant-half-v1"

    def __init__(self, head):
        self.head = head

    def evaluate(self, content, state, plan):
        if state is not None:
            raise ValueError("Constant forecast has no latent state")
        if not plan.requested_reads:
            return self.head.evaluate(content).calibrated_correctness
        return base.CorrectnessValue(.5, self.head.head_id)


def prepare(output, candidate):
    output.mkdir(parents=True, exist_ok=False)
    plan_at(candidate)
    write(output / "PROTOCOL.json", {"schema": "hcsn-v10-posthoc-constant-reference.v1",
        "source_sha256": sha(__file__), "candidate_plan_sha256": sha(candidate / "PLAN.json"),
        "probability": .5, "fit_parameters": 0, "tasks": ["async_av", "av_binding"],
        "motivation": "Training/validation-only diagnostic: validation BCE of flat .5 beats many selected emotion models; expose a cheap ordinary reference",
        "posthoc_to_original_experiment": True, "original_B_selection_replaced": False,
        "historical_recordings_are_new_confirmation": False,
        "source_evaluation_may_already_have_run": True,
        "candidate_test_results_used_to_select_constant": False,
        "scope": "Additional descriptive historical reference, not a new pre-registered confirmation"})


def execute(output, candidate):
    protocol = json.loads((output / "PROTOCOL.json").read_text())
    assert sha(__file__) == protocol["source_sha256"]
    assert sha(candidate / "PLAN.json") == protocol["candidate_plan_sha256"]
    configure_assets(candidate)
    rows = []
    with gzip.open(output / "TRACES.jsonl.gz", "xt") as stream:
        for task in protocol["tasks"]:
            directory = output / task
            directory.mkdir()
            head, _, _ = base.fit_development_adapters(task, base.legacy_data(task, "val"), directory)
            data = base.legacy_data(task, "test")
            for i, label in enumerate(base.labels_of(data)):
                for policy in ("fixed", "value"):
                    object_id = f"constant-half-{task}-{i}-{policy}"
                    receipt = base.run_episode(object_id, base.CacheBudget(65536), head,
                        ConstantForecast(head), base.FixedServiceModel(),
                        base.PreparedPrefixService(*base.episode_arrays(data, i), object_id),
                        lambda _: None, clock=base.LogicalClock(), horizon=6 if policy == "fixed" else 2,
                        fixed_plans=base.fixed_plans("common_full") if policy == "fixed" else None)
                    correct = int(receipt["output"]["predicted_class"] == int(label))
                    row = {"task": task, "index": i, "policy": policy, "label": int(label),
                        "correct": correct, "requests": receipt["requested_observations"],
                        "utility": correct - receipt["observation_fee"] - receipt["latency_fee"] - receipt["deadline_penalty"]}
                    rows.append(row)
                    stream.write(json.dumps({**row, "execution": receipt}) + "\n")
    source = json.loads((candidate / "SCORES.json").read_text())
    contrasts = {}
    for task in protocol["tasks"]:
        constant = {r["index"]: r for r in rows if r["task"] == task and r["policy"] == "value"}
        values = [r["utility"] - constant[r["index"]]["utility"] for r in source["rows"]
                  if r["task"] == task and r["family"] == "renewal" and r["policy"] == "value"]
        contrasts[task] = {"D_minus_constant_half_descriptive_mean": float(np.mean(values)),
            "constant_value_accuracy": float(np.mean([r["correct"] for r in constant.values()])),
            "constant_value_requests": float(np.mean([r["requests"] for r in constant.values()]))}
    write(output / "SUMMARY.json", {"runs": len(rows), "rows": rows, "contrasts": contrasts,
        "protocol_sha256": sha(output / "PROTOCOL.json"), "raw_sha256": sha(output / "TRACES.jsonl.gz"),
        "posthoc": True, "original_B_unchanged": True, "fresh_confirmation": False})
    print(json.dumps(contrasts))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "execute"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(1)
    if args.command == "prepare":
        prepare(args.output, args.candidate)
    else:
        execute(args.output, args.candidate)
