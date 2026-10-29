"""Strict independent evidence audit; run selection-only before opening test data."""

import argparse
from collections import defaultdict
import json
from pathlib import Path

import numpy as np

from .audit_core import (
    ARMS,
    COUNTERS,
    LEARNED,
    SEEDS,
    paired_statistics,
    read,
    require,
    sha,
    strict_json,
    summarize,
)
from .audit_costs import audit_costs, export_counts, native_identity, native_work
from .audit_diagnostics import verify_panel
from .audit_integrity import verify_bindings, verify_contexts
from .audit_records import audit_shard, verify_training


def summaries(evidence):
    arms, seeds = {}, {}
    for arm in ARMS:
        split_rows = {
            split: [r for seed in SEEDS for r in evidence[seed, arm, split]]
            for split in ("test_id", "test_ood")
        }
        arms[arm] = summarize(split_rows["test_id"] + split_rows["test_ood"])
        arms[arm]["splits"] = {
            split: summarize(rows) for split, rows in split_rows.items()
        }
        seeds[arm] = []
        for seed in SEEDS:
            splits = {
                split: summarize(evidence[seed, arm, split])
                for split in ("test_id", "test_ood")
            }
            seeds[arm].append(
                {
                    "seed": seed,
                    "splits": splits,
                    "mean_net_utility": 0.5
                    * sum(v["mean_net_utility"] for v in splits.values()),
                }
            )
        arms[arm]["equal_seed_equal_split_mean_net_utility"] = float(
            np.mean([r["mean_net_utility"] for r in seeds[arm]])
        )
        arms[arm]["action_counts"] = {
            "keep": int(
                sum(
                    r["steps"] - r["repairs"] - r["stops"]
                    for rows in split_rows.values()
                    for r in rows
                )
            ),
            "repair": int(
                sum(r["repairs"] for rows in split_rows.values() for r in rows)
            ),
            "stop": int(sum(r["stops"] for rows in split_rows.values() for r in rows)),
        }
    deltas = [
        a["mean_net_utility"] - b["mean_net_utility"]
        for a, b in zip(seeds["policy_regret"], seeds["iterative_q_mse"])
    ]
    failures = sum(
        arms[a]["stability_failures"] for a in ("policy_regret", "iterative_q_mse")
    )
    return arms, seeds, paired_statistics(deltas, int(failures))


def panel_summary(panels):
    out = {}
    for arm in LEARNED:
        rows = [p["arms"][arm] for p in panels]
        count = sum(r["rows"] for r in rows)
        result = {"rows": count}
        for field in (
            "mean_native_regret",
            "mean_float_regret",
            "mean_signed_quantization_regret",
        ):
            result[field] = sum(r[field] * r["rows"] for r in rows) / count
        for field in (
            "action_disagreements",
            "quantization_harmed_rows",
            "quantization_helped_rows",
        ):
            result[field] = sum(r[field] for r in rows)
        result["maximum_abs_score_error"] = max(
            r["maximum_abs_score_error"] for r in rows
        )
        result["teacher_conditioned_regret"] = {}
        for label in ("keep", "repair", "stop"):
            groups = [r["teacher_conditioned_regret"][label] for r in rows]
            n = sum(g["count"] for g in groups)
            result["teacher_conditioned_regret"][label] = {
                "count": n,
                "mean_native_regret": sum(
                    g["count"] * g["mean_native_regret"] for g in groups if g["count"]
                )
                / n
                if n
                else None,
            }
        out[arm] = result
    return {
        "scope": "descriptive common ID-state panel; neither selection nor confirmation episodes",
        "all_arms_native_activation_identical": True,
        "arms": out,
        "seeds": panels,
    }


def audit_run(study, repository=None, confirmed=True):
    root = Path(study).resolve()
    repository = (
        Path(repository).resolve()
        if repository
        else Path(__file__).resolve().parents[2]
    )
    protocol, source, environment, selection, manifest, files = verify_bindings(
        root, repository, confirmed
    )
    phases = {"training": 12, "development": 8}
    if confirmed:
        phases.update(test_id=8, test_ood=8, diagnostic=4)
    refs = verify_contexts(root, phases=phases)
    checkpoints, profiles, training, exports, development_counts, expected = (
        verify_training(root, selection, refs)
    )
    training_expected = expected | {
        "PROTOCOL.json",
        "SOURCE_SEAL.json",
        "ENVIRONMENT.json",
        "TRAINING_STARTED.json",
    }
    training_expected |= {
        f"contexts/{seed}/{phase}.json"
        for seed in SEEDS
        for phase in ("training", "development")
    }
    require(
        set(selection["training_files"]) == training_expected,
        "Selection file roster omits expected evidence or includes unrelated/extra artifacts",
    )
    expected = training_expected | {"costs.jsonl", "SELECTION_SEAL.json"}
    evidence, confirmation_counts, diagnostic_counts = defaultdict(list), {}, {}
    panels, seen_shards, result = [], set(), {}
    if confirmed:
        expected |= {"EXTERNAL_SELECTION.json", "MANIFEST.json"}
        expected |= {
            f"contexts/{seed}/{phase}.json"
            for seed in SEEDS
            for phase in ("test_id", "test_ood", "diagnostic")
        }
        roster = {
            (s, a, p) for s in SEEDS for a in ARMS for p in ("test_id", "test_ood")
        }
        for shard in manifest["shards"]:
            seed, arm, split = shard["seed"], shard["arm"], shard["split"]
            key = seed, arm, split
            require(
                key in roster and key not in seen_shards,
                "Duplicate or undeclared confirmation shard",
            )
            seen_shards.add(key)
            require(
                shard["path"] == f"shards/{seed}/{split}/{arm}.jsonl.gz",
                "Confirmation raw path changed",
            )
            ckpt, identity = checkpoints[seed, arm]
            records, counts = audit_shard(
                root, shard, seed, arm, split, ckpt, identity, profiles[seed, arm], refs
            )
            evidence[key] = records
            expected.add(shard["path"])
            aggregate = confirmation_counts.setdefault(
                (seed, arm), dict.fromkeys(COUNTERS, 0)
            )
            for name, value in counts.items():
                aggregate[name] += value
        require(
            seen_shards == roster and sum(map(len, evidence.values())) == 16384,
            "Incomplete scheduled confirmation evidence",
        )
        require(
            [p["seed"] for p in manifest["diagnostic_panels"]] == SEEDS,
            "Diagnostic seed roster changed",
        )
        for item in manifest["diagnostic_panels"]:
            panel, counts, paths = verify_panel(
                root, item, item["seed"], refs, checkpoints, profiles
            )
            panels.append(panel)
            diagnostic_counts.update(counts)
            expected |= paths
        arms, seed_summaries, primary = summaries(evidence)
        result.update(
            arm_summaries=arms,
            seed_summaries=seed_summaries,
            primary_comparison=primary,
            common_state_panel=panel_summary(panels),
            native_confirmation_steps_verified=sum(
                v["source_kernel_calls"] for v in confirmation_counts.values()
            ),
        )
    require(
        set(files) == expected,
        "Final evidence roster contains missing or extra scientific files",
    )
    costs = audit_costs(
        root,
        source,
        selection,
        training,
        exports,
        development_counts,
        confirmation_counts,
        diagnostic_counts,
        confirmed,
    )
    fitted = [c for receipt in training.values() for c in receipt["candidates"]]
    return {
        "schema": "hepta.native-readout-objective.independent-audit.v1",
        "passed": True,
        "phase": "confirmation" if confirmed else "selection_only",
        "protocol_sha256": environment["protocol_sha256"],
        "source_seal_sha256": environment["source_seal_sha256"],
        "selection_seal_sha256": sha((root / "SELECTION_SEAL.json").read_bytes()),
        "manifest_sha256": sha((root / "MANIFEST.json").read_bytes())
        if confirmed
        else None,
        "native_binary_sha256": source["native_binary_sha256"],
        "files_verified": len(files),
        "checkpoints_verified": len(checkpoints),
        "candidate_optimizers_independently_reconstructed": len(fitted),
        "training_native_activation_rows_verified": sum(
            e["rows"] for e in exports.values()
        ),
        "development_episodes_verified": len(fitted) * 64,
        "confirmation_episodes_verified": sum(map(len, evidence.values())),
        "training_selection": [
            {
                "seed": seed,
                "arm": arm,
                "selected_index": receipt["selected_index"],
                "candidates": [
                    {
                        "index": c["candidate_index"],
                        "mean_development_net_utility": c[
                            "development_mean_net_utility"
                        ],
                        "observed_active_columns": c["observed_active_columns"],
                        "gradient_coordinates": c["fit"].get(
                            "coordinates_with_nonzero_gradient"
                        ),
                    }
                    for c in receipt["candidates"]
                ],
            }
            for (seed, arm), receipt in training.items()
        ],
        "costs": costs,
        **result,
        "scope": {
            "independence": "independent Bellman, causal trajectories, physical reward, optimizer and Q24 arithmetic; shared sealed numerical grid constructor; native sparse kernel is executed and receipt-checked, not separately reimplemented",
            "calibration": "common analytic after-action first-passage predictor evaluated on each policy's own exposure; differing visitation prevents an isolated risk-learning comparison",
            "stability": "complete finite task horizons and saved native state/receipt chains only; no unmeasured long-horizon or energy claim",
            "diagnostics": "descriptive only; unique confirmatory family is policy_regret minus iterative_q_mse",
        },
    }


def audit_smoke(study):
    """Actual native integration fixture; explicitly not preregistered efficacy."""
    root = Path(study).resolve()
    summary = read(root, "SUMMARY.json")
    require(
        summary["schema"] == "hepta.native-readout-objective.native-smoke.v1"
        and summary["seed"] == 991
        and summary["registered_confirmation_accessed"] is False,
        "Diagnostic fixture is not the declared nonstudy seed",
    )
    refs = verify_contexts(
        root, [991], {"training": 2, "development": 1, "diagnostic": 1}
    )
    selection = {
        "checkpoints": [
            dict(a["checkpoint"], seed=991, arm=a["arm"]) for a in summary["arms"]
        ]
    }
    checkpoints, profiles, training, exports, development_counts, _ = verify_training(
        root,
        selection,
        refs,
        seeds=[991],
        training_contexts=2,
        training_paths=2,
        development_contexts=1,
        development_paths=2,
        epochs=4,
        candidates=(1,),
    )
    source = {
        "native_binary_sha256": summary["native_binary_sha256"],
        "native_source_manifest_sha256": exports[991]["native_process_cost"][
            "identity"
        ]["source_manifest_digest"],
    }
    native_work(
        exports[991]["native_process_cost"],
        exports[991]["cost"],
        source,
        export_counts(root, exports[991]),
    )
    results = {}
    for item in summary["arms"]:
        arm = item["arm"]
        ckpt, identity = checkpoints[991, arm]
        shard = dict(
            item["shard"],
            seed=991,
            arm=arm,
            split="diagnostic",
            counts=[item["counts"]],
        )
        rows, counts = audit_shard(
            root,
            shard,
            991,
            arm,
            "diagnostic",
            ckpt,
            identity,
            profiles[991, arm],
            refs,
            1,
            4,
        )
        if arm in LEARNED:
            native_identity(item["native_process_cost"], source)
            native_work(
                training[991, arm]["native_process_cost"],
                training[991, arm]["cost"],
                source,
                development_counts[991, arm],
            )
            native = item["native_process_cost"]["counters"]
            require(
                native["actual_kernel_calls"] == counts["source_kernel_calls"]
                and native["actual_ndu_calls"] == counts["native_ndu_calls"],
                "Smoke native work differs from raw records",
            )
        results[arm] = summarize(rows)
    panel, panel_counts, _ = verify_panel(
        root, summary["diagnostic_panel"], 991, refs, checkpoints, profiles, 1, 2
    )
    for row in (
        read_cost
        for read_cost in map(
            strict_json, (root / "costs.jsonl").read_bytes().splitlines()
        )
        if read_cost["phase"] == "diagnostic_panel"
    ):
        native_work(
            row["native_process_cost"],
            row["cost"],
            source,
            panel_counts[991, row["arm"]],
        )
    return {
        "schema": "hepta.native-readout-objective.smoke-audit.v1",
        "passed": True,
        "registered_confirmation_accessed": False,
        "episodes_verified": 16,
        "native_binary_sha256": source["native_binary_sha256"],
        "training_export_rows_verified": exports[991]["rows"],
        "candidate_optimizers_verified": 3,
        "development_episodes_verified": 6,
        "arm_summaries": results,
        "diagnostic_panel": panel,
        "scope": "diagnostic-only actual native integration; no formal source/selection publication, full study cost or efficacy claim",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", type=Path)
    parser.add_argument("--repository", type=Path)
    parser.add_argument("--selection-only", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(
        not args.output.resolve().is_relative_to(args.study.resolve()),
        "Audit output must not mutate sealed evidence",
    )
    result = (
        audit_smoke(args.study)
        if args.smoke
        else audit_run(args.study, args.repository, not args.selection_only)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                "passed": True,
                "output": str(args.output),
                "formal_confirmation": not args.smoke and not args.selection_only,
            }
        )
    )


if __name__ == "__main__":
    main()
