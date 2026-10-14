"""Frozen-model search experiment: exact-terminal scheduling and successor budgets.

Reuse authenticated parent tensors, not new training. Deferred remains a control.
Old tasks diagnose reproducibility; next fixed hash slice tests different number
multisets. Neither set is a natural-language or independent-domain confirmation.
"""

import argparse
from fractions import Fraction
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import time

import torch
from torch import nn
from safetensors.torch import load

from system2_ablation import model_digest
from system2_native_receipt import verified_archive, strict_json, index_rows
from system2_verified_search import ARMS, ExactLabels, digest, search, verify

PARENT = "15a9c7cd50d471cd255779401c3555b70588ce28"
ARCHIVE = "3838a940e601117070438a6e6f88ffc7c46645c50df5ef0f1ea304ebe91ae0bd"
POLICIES = ("deferred", "eager")
LIMITS = (256, 1024)


def read_parent(archive):
    files = verified_archive(archive, ARCHIVE)
    if (
        files["tested-commit.txt"].decode().strip() != PARENT
        or files["tested-tree.txt"].decode().strip()
        != "41679c9d46e801a0e6305ebc48ad8c6cf689da1e"
    ):
        raise ValueError("unexpected historical generating source")
    data = files["source/system2_verified_search.py"]
    if (
        hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        != "35e15c61b0830c78ed91693f8653842e12984d6e"
    ):
        raise ValueError("historical search source drift")
    plan = strict_json(files["search/plan.json"])
    receipts = strict_json(files["search/training.json"])
    raw = files["search/predictions.jsonl"]
    if (
        hashlib.sha256(raw).hexdigest()
        != strict_json(files["search/prediction-seal.json"])["sha256"]
    ):
        raise ValueError("historical prediction seal mismatch")
    records = [strict_json(line) for line in raw.splitlines() if line.strip()]
    expected = {
        (digest(n), a, b) for n in plan["evaluation"] for a in ARMS for b in (64, 256)
    }
    index_rows(records, ("query_id", "arm", "budget"), expected)
    if len(records) != 336:
        raise ValueError("incomplete historical search census")
    models = {}
    for name in ("value", "shuffled"):
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(719)
            model = nn.Sequential(nn.Linear(12, 16), nn.Tanh(), nn.Linear(16, 1))
        model.load_state_dict(
            load(files["search/" + name + ".safetensors"]), strict=True
        )
        model.eval().requires_grad_(False)
        if model_digest(model) != receipts[name]["after"]:
            raise ValueError("historical trained parameters differ")
        models[name] = model
    return (
        plan,
        models,
        records,
        dict(
            archive_sha256=ARCHIVE,
            verified_files=len(files) - 1,
            generating_source=PARENT,
            historical_search=strict_json(files["search/summary.json"]),
            historical_lq=strict_json(files["lq/summary.json"]),
        ),
    )


def task_groups(parent_plan):
    catalogue = sorted(
        itertools.combinations_with_replacement(range(1, 10), 4),
        key=lambda n: digest(("verified-search-v1", n)),
    )
    if (
        list(map(tuple, parent_plan["training"])) != catalogue[:12]
        or list(map(tuple, parent_plan["evaluation"])) != catalogue[12:36]
    ):
        raise ValueError("historical task identity changed")
    return dict(reused=catalogue[12:36], next_hash_slice=catalogue[36:60])


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def run(archive, output, *, source_commit):
    if not re.fullmatch("[0-9a-f]{40}", source_commit or ""):
        raise ValueError("exact tested source required")
    output.mkdir(exist_ok=False, parents=True)
    parent, models, old, audit = read_parent(archive)
    groups = task_groups(parent)
    plan = dict(
        schema="hepta.system2.eager-verifier.v1",
        source_commit=source_commit,
        parent_archive=ARCHIVE,
        groups=groups,
        policies=POLICIES,
        successor_limits=LIMITS,
        arms=ARMS,
        popped_ceiling=8192,
        frozen_models={k: model_digest(m) for k, m in models.items()},
        primary_comparison="next_hash_slice,1024,eager:value_search versus heuristic_search and shuffled_value",
        reusing_225_parameter_critics=True,
        training_updates=0,
        new_encoder_reader_calls=0,
        generated_successors_include_duplicates=True,
        exact_compute_matched=False,
        intermediate_states_may_overlap=True,
        production_accepted=False,
        independent_natural_task_evidence=False,
        ndu_utility_calibrated=False,
    )
    write(output / "plan.json", plan)
    write(output / "parent-audit.json", audit)
    # Default behavior is an exact deterministic replay, excluding wall time.
    replays = []
    for previous in old:
        arm = previous["arm"]
        model = models["shuffled" if arm == "shuffled_value" else "value"]
        row = dict(query_id=previous["query_id"], arm=arm, budget=previous["budget"])
        try:
            actual = search(previous["numbers"], 24, arm, previous["budget"], model)
            for key in ("found", "budget_exhausted", "costs"):
                if actual[key] != previous[key]:
                    raise ValueError("default replay drift: " + key)
            if actual["proof"] is not None and not verify(
                previous["numbers"], 24, actual["proof"]
            ):
                raise ValueError("invalid replay proof")
            if (None if actual["proof"] is None else list(actual["proof"])) != previous[
                "proof"
            ]:
                raise ValueError("default proof drift")
            row.update(status="matched", seconds=actual["seconds"])
        except Exception as exc:
            row.update(status="failed", error=str(exc)[:512])
        replays.append(row)
    write(output / "legacy-replay.json", replays)
    if any(r["status"] != "matched" for r in replays):
        raise RuntimeError("legacy replay mismatch; retained all 336 attempts")
    records = []
    configurations = list(itertools.product(LIMITS, POLICIES, ARMS))
    for group, tasks in groups.items():
        for numbers in tasks:
            offset = int(digest(numbers)[:8], 16) % len(configurations)
            for limit, policy, arm in configurations[offset:] + configurations[:offset]:
                row = dict(
                    group=group,
                    numbers=numbers,
                    query_id=digest(numbers),
                    successor_limit=limit,
                    terminal_policy=policy,
                    arm=arm,
                )
                started = time.perf_counter()
                try:
                    result = search(
                        numbers,
                        24,
                        arm,
                        8192,
                        models["shuffled" if arm == "shuffled_value" else "value"],
                        terminal_policy=policy,
                        successor_limit=limit,
                    )
                    if result["costs"]["generated_successors"] > limit:
                        raise ValueError("successor budget overshoot")
                    row.update(result, status="completed")
                except Exception as exc:
                    row.update(
                        status="failed",
                        error_type=type(exc).__name__,
                        error=str(exc)[:512],
                        seconds=time.perf_counter() - started,
                        costs_may_be_incomplete=True,
                    )
                records.append(row)
                with (output / "predictions.jsonl").open("a") as stream:
                    stream.write(json.dumps(row, allow_nan=False) + "\n")
                    stream.flush()
    expected = {
        (digest(n), a, p, b)
        for tasks in groups.values()
        for n in tasks
        for b, p, a in configurations
    }
    index_rows(
        records, ("query_id", "arm", "terminal_policy", "successor_limit"), expected
    )
    raw = (output / "predictions.jsonl").read_bytes()
    answer_seal = hashlib.sha256(raw).hexdigest()
    write(
        output / "prediction-seal.json",
        dict(sha256=answer_seal, rows=len(records), scoring_started=False),
    )
    if {k: model_digest(m) for k, m in models.items()} != plan["frozen_models"]:
        raise ValueError("search mutated shared frozen models")
    # No post-seal oracle result affects either policy or the frozen model.
    labeler = ExactLabels()
    possible = {
        digest(n): labeler.solve(tuple(map(Fraction, n)), 24)
        for tasks in groups.values()
        for n in tasks
    }
    for row in records:
        valid = bool(row.get("found")) and verify(row["numbers"], 24, row["proof"])
        if row.get("found") and not valid:
            raise ValueError("search claimed an invalid proof")
        row.update(verified_solution=bool(valid), solvable=possible[row["query_id"]])
    summaries = []
    for group in groups:
        for limit, policy, arm in configurations:
            rows = [
                r
                for r in records
                if (r["group"], r["successor_limit"], r["terminal_policy"], r["arm"])
                == (group, limit, policy, arm)
            ]
            summaries.append(
                dict(
                    group=group,
                    successor_limit=limit,
                    terminal_policy=policy,
                    arm=arm,
                    planned=len(rows),
                    failed=sum(r["status"] == "failed" for r in rows),
                    valid_solutions=sum(r["verified_solution"] for r in rows),
                    solvable_tasks=sum(r["solvable"] for r in rows),
                    seconds=sum(r["seconds"] for r in rows),
                    costs={
                        key: sum(r.get("costs", {}).get(key, 0) for r in rows)
                        for key in (
                            "popped_states",
                            "generated_successors",
                            "critic_examples",
                            "verifier_calls",
                        )
                    },
                    failed_costs_may_be_incomplete=any(
                        r["status"] == "failed" for r in rows
                    ),
                )
            )
    summary = plan | dict(
        planned=len(expected),
        recorded=len(records),
        legacy_replays=len(replays),
        failed=sum(r["status"] == "failed" for r in records),
        results=summaries,
        prediction_sha256=answer_seal,
        evaluation_oracle_states=labeler.calls,
        reasoning_emergence_established=False,
    )
    write(output / "scored.json", records)
    write(output / "summary.json", summary)
    if (
        hashlib.sha256((output / "predictions.jsonl").read_bytes()).hexdigest()
        != answer_seal
    ):
        raise ValueError("scoring changed original predictions")
    if summary["failed"]:
        raise RuntimeError("failed searches retained in full census")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.archive,
                args.output,
                source_commit=os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", ""),
            ),
            allow_nan=False,
        )
    )
