"""Independent supplemental raw-evidence auditor and registered statistics.

No policy training, inference, rollout, or reporting function is imported.
The source-bound numerical grid constructor is shared; its Bellman recursion,
cell recurrence, actions, ledgers, selection arithmetic and statistics are not.
"""

import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path

import numpy as np

from .audit_cell import (
    inference,
    validate_cell,
    verify_score_receipt,
    verify_sparse_step,
)
from .audit_integrity import (
    ARMS,
    LEARNED,
    PAIRS,
    SEEDS,
    canonical,
    checked_file,
    sha,
    strict_json,
    verify_contexts,
    verify_selection,
    verify_study_bindings,
)
from .audit_math import close, expected_features, require, streams, verify_physics
from .audit_stats import (
    COUNTERS,
    audit_costs,
    paired_statistics,
    summarize,
    verify_context_counters,
)
from .dp_reference import verify_production_solver


def audit_episode(
    record,
    checkpoint,
    ref,
    score_binary_sha,
    profile=None,
    expected_initial=None,
    expected_slots=None,
    cell=None,
):
    """Validate one raw episode; diagnostic fixtures need no full study manifest."""
    require(
        record.get("schema") == "hepta.continuous-boundary-policy.episode.v1",
        "Episode schema mismatch",
    )
    arm, steps, spec = record["arm"], record["steps"], record["spec"]
    require(
        arm in ARMS and spec == vars(ref["model"].spec), "Episode task/arm mismatch"
    )
    horizon = spec["horizon"]
    require(
        isinstance(steps, list)
        and 0 < len(steps) <= horizon
        and type(record["stability_failure"]) is bool,
        "Invalid complete episode",
    )
    continuous = arm in LEARNED and arm != "native_sparse"
    if continuous and cell is None:
        cell = validate_cell(checkpoint["model"])
    totals = dict.fromkeys(
        (
            "gross_utility",
            "production",
            "failure_cost",
            "maintenance_cost",
            "discounted_action_regret",
            "action_regret",
        ),
        0.0,
    )
    counters = dict.fromkeys(COUNTERS, 0)
    probabilities, labels = [], []
    previous_failed = previous_risk = previous_repair = 0.0
    state, hidden, native_state = expected_initial, np.zeros(6), "0" * 64
    failures = repairs = stops = 0
    for elapsed, step in enumerate(steps):
        require(
            step["elapsed"] == elapsed and type(step["elapsed"]) is int,
            "Missing/duplicate/out-of-order decision window",
        )
        require(
            state is None or step["state_idx"] == state, "Physical state chain mismatch"
        )
        if expected_slots is not None:
            require(
                step["uniforms"] == expected_slots[elapsed].tolist(),
                "Nonpaired or changed environmental innovations",
            )
        remaining, current = horizon - elapsed, step["state_idx"]
        require(
            type(current) is int and 0 <= current < 64, "Invalid finite state index"
        )
        q = ref["q"][remaining - 1, current]
        close(step["teacher_q"], q, "confirmation teacher Q", atol=2e-12)
        action = ("wait", "repair", "stop").index(step["action"])
        regret = float(np.max(q) - q[action])
        close(step["action_regret"], regret, "DP action regret", atol=2e-12)
        discount = float(np.exp(-spec["discount"] * spec["dt"] * elapsed))
        totals["action_regret"] += regret
        totals["discounted_action_regret"] += discount * regret
        if arm in LEARNED:
            values, reset = expected_features(
                ref,
                checkpoint,
                current,
                remaining,
                previous_failed,
                previous_risk,
                previous_repair,
            )
            close(
                step["features"], values, "causal public/channel features", atol=2e-12
            )
            close(step["reset_fraction"], reset, "causal reset", atol=2e-12)
            if continuous:
                close(
                    step["hidden_before"], hidden, "continuous hidden chain", atol=2e-12
                )
                scores, following = inference(
                    step["features"], step["reset_fraction"], hidden, *cell
                )
                close(
                    step["hidden_after"],
                    following,
                    "independent recurrent state",
                    atol=2e-12,
                )
                close(
                    step["scores_float"],
                    scores,
                    "independent recurrent scores",
                    atol=2e-12,
                )
                require(
                    np.max(np.abs(step["hidden_after"])) <= 1
                    and np.max(np.abs(step["scores_float"])) <= 8,
                    "Recurrent stability bound violated",
                )
                verify_score_receipt(step, record, elapsed, score_binary_sha)
                hidden = np.asarray(step["hidden_after"], dtype=float)
            else:
                require(profile is not None, "Sparse profile missing")
                native_state = verify_sparse_step(
                    step, record, elapsed, profile, native_state
                )
        elif arm == "dp":
            require(
                action == max(range(3), key=lambda index: (q[index], index)),
                "DP reference action mismatch",
            )
        else:
            require(
                action == {"always_keep": 0, "always_repair": 1, "always_stop": 2}[arm],
                "Fixed policy action mismatch",
            )
        expected_counts = {
            "source_kernel_calls": int(arm == "native_sparse"),
            "native_ndu_calls": int(arm in LEARNED),
            "semantic_message_bytes": 24
            if continuous
            else 160
            if arm == "native_sparse"
            else 0,
        }
        for name in COUNTERS:
            value = step[name]
            require(type(value) is int and value >= 0, "Invalid step resource counter")
            require(
                name not in expected_counts or value == expected_counts[name],
                "Hidden sparse work or incorrect semantic communication charge",
            )
            if arm not in LEARNED:
                require(value == 0, "Algorithmic control falsely charged native work")
            counters[name] += value
        ledger = verify_physics(step, ref)
        for name, value in ledger.items():
            totals[name] += value
        state = step["next_state_idx"]
        if step["action"] == "stop":
            require(elapsed == len(steps) - 1, "Actions occurred after absorbing stop")
            stops += 1
        else:
            probabilities.append(float(step["predicted_risk"]))
            labels.append(int(step["failed"]))
        failures += int(step["failed"])
        repairs += int(step["action"] == "repair")
        previous_failed = float(step["failed"])
        previous_risk = (
            0.0 if step["predicted_risk"] is None else float(step["predicted_risk"])
        )
        previous_repair = float(step["action"] == "repair")
    require(stops == 1 or len(steps) == horizon, "Incomplete nonterminal episode")
    totals["net_utility"] = (
        totals["gross_utility"] - 1e-6 * counters["semantic_message_bytes"]
    )
    close(
        record["reported_utility"],
        totals["gross_utility"],
        "episode physical utility",
        atol=2e-10,
    )
    close(
        record["reported_net_utility"],
        totals["net_utility"],
        "episode net utility",
        atol=2e-10,
    )
    return {
        **totals,
        **counters,
        "steps": len(steps),
        "failures": failures,
        "repairs": repairs,
        "stops": stops,
        "probabilities": probabilities,
        "labels": labels,
        "brier": float(np.mean((np.asarray(probabilities) - labels) ** 2))
        if probabilities
        else None,
        "stability_failure": int(record["stability_failure"]),
    }


def audit_run(study, repository=None):
    root = Path(study).resolve()
    repository = (
        Path(repository).resolve()
        if repository is not None
        else Path(__file__).resolve().parents[2]
    )
    protocol, manifest, selection, environment = verify_study_bindings(root, repository)
    references = verify_contexts(root)
    checkpoints, cells, profiles, training = verify_selection(
        root, selection, references
    )
    evidence, seen_shards, raw_counts = defaultdict(list), set(), {}
    expected_shards = {
        (seed, arm, split)
        for seed in SEEDS
        for arm in ARMS
        for split in ("test_id", "test_ood")
    }
    for shard in manifest["shards"]:
        seed, arm, split = shard["seed"], shard["arm"], shard["split"]
        key = seed, arm, split
        require(
            key in expected_shards and key not in seen_shards,
            "Duplicate/undeclared confirmation shard",
        )
        seen_shards.add(key)
        require(
            shard["path"] == f"shards/{seed}/{split}/{arm}.jsonl.gz"
            and shard["count"] == 128,
            "Confirmation shard path/count mismatch",
        )
        raw = gzip.decompress(
            checked_file(root, shard["path"], shard["sha256"]).read_bytes()
        )
        require(
            sha(raw) == shard["uncompressed_sha256"]
            and len(raw) == shard["uncompressed_bytes"],
            "Raw trajectory digest/size mismatch",
        )
        records = [strict_json(line) for line in raw.splitlines()]
        require(
            len(records) == 128 and len(shard["counts"]) == 8,
            "Incomplete confirmation cases",
        )
        checkpoint, identity = checkpoints[seed, arm]
        for index in range(8):
            ref = references[seed, split, index]
            initial, slots, stream_id = streams(seed, split, index, 16, ref)
            group = records[index * 16 : (index + 1) * 16]
            for path_index, record in enumerate(group):
                require(
                    record["train_seed"] == seed
                    and record["arm"] == arm
                    and record["split"] == split
                    and record["episode_id"] == f"{seed}.{split}.c{index}.p{path_index}"
                    and record["eval_seed"] == stream_id
                    and record["checkpoint_sha256"] == identity,
                    "Episode/phase/stream/checkpoint binding mismatch",
                )
                result = audit_episode(
                    record,
                    checkpoint,
                    ref,
                    environment["binary_sha256"]["score"],
                    profile=profiles.get((seed, arm)),
                    expected_initial=int(initial[path_index]),
                    expected_slots=slots[:, path_index],
                    cell=cells[seed, arm],
                )
                evidence[seed, arm, split].append(result)
                raw_counts.setdefault((seed, arm), dict.fromkeys(COUNTERS, 0))
                for name in COUNTERS:
                    raw_counts[seed, arm][name] += result[name]
            verify_context_counters(group, shard["counts"][index])
    require(
        seen_shards == expected_shards
        and sum(len(rows) for rows in evidence.values()) == 26624,
        "Missing scheduled confirmation data",
    )
    arm_summaries, seed_summaries = {}, {}
    for arm in ARMS:
        split_rows = {
            split: [row for seed in SEEDS for row in evidence[seed, arm, split]]
            for split in ("test_id", "test_ood")
        }
        arm_summaries[arm] = summarize(split_rows["test_id"] + split_rows["test_ood"])
        arm_summaries[arm]["splits"] = {
            split: summarize(rows) for split, rows in split_rows.items()
        }
        seed_summaries[arm] = []
        for seed in SEEDS:
            split_summaries = {
                split: summarize(evidence[seed, arm, split])
                for split in ("test_id", "test_ood")
            }
            seed_summaries[arm].append(
                {
                    "seed": seed,
                    "splits": split_summaries,
                    "mean_net_utility": 0.5
                    * sum(row["mean_net_utility"] for row in split_summaries.values()),
                }
            )
    comparisons = []
    for pair in PAIRS:
        treatment, control = pair["treatment"], pair["control"]
        delta = [
            a["mean_net_utility"] - b["mean_net_utility"]
            for a, b in zip(seed_summaries[treatment], seed_summaries[control])
        ]
        failures = (
            arm_summaries[treatment]["stability_failures"]
            + arm_summaries[control]["stability_failures"]
        )
        comparisons.append({**pair, **paired_statistics(delta, failures)})
    costs = audit_costs(root, training, raw_counts)
    return {
        "schema": "hepta.continuous-boundary-policy.independent-audit.v1",
        "passed": True,
        "protocol_sha256": manifest["protocol_sha256"],
        "source_seal_sha256": manifest["source_seal_sha256"],
        "selection_seal_sha256": manifest["selection_seal_sha256"],
        "manifest_sha256": sha((root / "MANIFEST.json").read_bytes()),
        "episodes_verified": 26624,
        "shards_verified": len(seen_shards),
        "checkpoints_verified": len(checkpoints),
        "continuous_forward_steps_verified": sum(
            row["steps"]
            for key, rows in evidence.items()
            if key[1] in LEARNED and key[1] != "native_sparse"
            for row in rows
        ),
        "sparse_head_steps_verified": sum(
            row["steps"]
            for key, rows in evidence.items()
            if key[1] == "native_sparse"
            for row in rows
        ),
        "scope": {
            "finite_grid_constructor": "shared source-bound quadrature constructor; independent Bellman loop and scalar F/H checks",
            "continuous_inference": "independent recurrence and bounded parameters for every confirmation tick",
            "native_sparse": "immutable profile, original host receipts/checkpoint chain and independent Q24 head; no separate sparse-core emulator",
            "native_digest": "native evaluation digest is opaque; source-bound host input/support/receipt hashes and selected frontier checked",
            "development": "all candidates, 64 returns each, optimizer budget, common teacher/input hashes and selection arithmetic; no full development native replay",
            "risk": "common analytic after-action predictor; calibration describes policy visitation",
        },
        "exact_finite_dp": verify_production_solver(),
        "arm_summaries": arm_summaries,
        "seed_summaries": seed_summaries,
        "paired_comparisons": comparisons,
        "benefit_gates_passed": sum(row["benefit_gate_passed"] for row in comparisons),
        "costs": costs,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", type=Path)
    args = parser.parse_args()
    report = audit_run(args.study, args.repository)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as stream:
        stream.write(canonical(report) + b"\n")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "episodes": report["episodes_verified"],
                "benefit_gates_passed": report["benefit_gates_passed"],
                "output": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    main()
