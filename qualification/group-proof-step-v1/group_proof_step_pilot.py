"""Physical stdlib three-seed E0/E3 mechanism campaign, never production selection.

Independent labels come from the task *constructor*; the learner and
runtime receive public prompt bytes only. The task grammar is deliberately
synthetic and must never be represented as natural-language generalization.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import random
import time

from group_proof_step import (FrozenLinePolicy, counterfactual_panel, digest,
                              execute_policy, fit_line_policy, parse_public)

HEADER = "Start at {start} and follow every link. What is the endpoint class? Answer one of A B C D E F G H."


def make_cohort(seed, split, count):
    """Canonical source hash split: 0..2 train; 3 test, never label-based."""
    if split not in {"train", "test"} or not 1 <= count <= 4096:
        raise ValueError("bounded cohort required")
    records, seen, attempt = [], set(), 0
    while len(records) < count:
        rng = random.Random(f"hepta-proof/{seed}/{attempt}")
        attempt += 1
        if attempt > count * 100:
            raise RuntimeError("source group partition unexpectedly sparse")
        depth = rng.randint(2, 6)
        nodes = rng.sample(range(0, 80), depth + 4)
        answer = chr(65 + rng.randrange(8))
        facts = [f"n{left} links to n{right}." for left, right in zip(nodes, nodes[1:depth + 1])]
        facts.append(f"n{nodes[depth]} has class {answer}.")
        facts += [f"n{node} has class {chr(65+rng.randrange(8))}." for node in nodes[depth+1:]]
        rng.shuffle(facts)
        text = "\n".join([HEADER.format(start=f"n{nodes[0]}"), *facts])
        group = parse_public(text).source_group_sha256
        if group in seen or (int(group[:8], 16) % 4 == 3) != (split == "test"):
            continue
        seen.add(group)
        records.append((text, answer, group, depth))
    return records


def _untrained_policy(trained):
    weights = [0.0] * len(trained.weights)
    serialized = json.dumps({"weights": weights, "sources": list(trained.training_source_sha256),
                             "updates": 0}, sort_keys=True, separators=(",", ":"))
    return FrozenLinePolicy(tuple(weights), trained.training_source_sha256, 0, 0, digest(serialized))


def execute_campaign(seed, *, train_count=128, test_count=64):
    train = make_cohort(seed, "train", train_count)
    test = make_cohort(seed, "test", test_count)
    train_ids, test_ids = {row[2] for row in train}, {row[2] for row in test}
    if train_ids & test_ids:
        raise ValueError("training/heldout source group collision")
    trained = fit_line_policy([text for text, _, _, _ in train], epochs=12, seed=seed)
    baseline = _untrained_policy(trained)
    arms = ("full", "question_only", "critical_removed", "distractor_removed", "truth_flipped")
    observed, totals = [], {name: {arm: {"n": 0, "correct": 0, "abstain": 0, "steps": 0,
                                           "candidate_scores": 0, "wall_ns": 0}
                                 for arm in arms} for name in ("untrained", "trained")}
    start = time.process_time_ns()
    for text, expected, group, depth in test:
        controlled = counterfactual_panel(text)
        if set(controlled) != set(arms):
            raise ValueError("incomplete causal controls")
        for label, policy in (("untrained", baseline), ("trained", trained)):
            for arm in arms:
                runtime = execute_policy(controlled[arm], policy)
                oracle_label = (chr(65 + (ord(expected) - 64) % 8)
                                if arm == "truth_flipped" else expected
                                if arm in {"full", "distractor_removed"} else None)
                okay = runtime["answer"] == oracle_label
                if runtime["source_group_sha256"] != parse_public(controlled[arm]).source_group_sha256:
                    raise ValueError("receipt/source identity mismatch")
                score = totals[label][arm]
                score["n"] += 1
                score["correct"] += int(okay)
                score["abstain"] += int(runtime["answer"] is None)
                score["steps"] += runtime["steps"]
                score["candidate_scores"] += runtime["candidate_scores"]
                score["wall_ns"] += runtime["wall_ns"]
                observed.append(dict(group=group, depth=depth, policy=label, arm=arm,
                                     expected=oracle_label, answer=runtime["answer"],
                                     status=runtime["status"], source_sha256=runtime["source_sha256"],
                                     steps=runtime["steps"], candidate_scores=runtime["candidate_scores"],
                                     wall_ns=runtime["wall_ns"]))
    return {"schema": "hepta.group.proof-step-campaign.v1", "seed": seed,
            "train_groups": sorted(train_ids), "test_groups": sorted(test_ids),
            "training": {"completed_updates": trained.completed_updates,
                         "train_source_count": len(train), "fitting_cpu_ns": trained.fitting_cpu_ns,
                         "policy_sha256": trained.policy_sha256, "trained_weights": trained.weights,
                         "input": "public_text_only_grammar_specific"},
            "evaluation_cpu_ns": time.process_time_ns() - start,
            "summary": totals, "observations": observed,
            "source_cases": [dict(source_text=text, constructor_label=label, source_group=group, depth=depth)
                             for text, label, group, depth in test],
            "stem_encoder_forwards": 0, "encoder_work_not_qualified": True,
            "independent_task_labels": "source_constructor_not_model_inference",
            "real_multimodal": False, "actual_native_effects": False,
            "natural_reasoning_emergence_established": False,
            "production_promotion_permitted": False, "authority": "DENY_ALL"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    runs = [execute_campaign(seed) for seed in (41, 47, 53)]
    report = {"schema": "hepta.group.proof-step-three-seed.v1", "runs": runs,
              "note": "Actual Python proof-step policy training and independent synthetic labels; not real Stem System2 gains.",
              "production_promotion_permitted": False}
    data = json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print(json.dumps({"output": str(out), "sha256": sha256(data).hexdigest(),
                      "summary": [{"seed": r["seed"], "baseline": r["summary"]["untrained"],
                                   "trained": r["summary"]["trained"]} for r in runs]}, indent=2))


if __name__ == "__main__":
    main()
