"""Registered seed-level paired inference from independently audited trajectories."""

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.stats import t as student_t

from .ledger import measured_stage, sha, write_json_exclusive
from .provenance import verify
from .roster import expected_roster, protocol, verify_roster


METRICS = (
    "utility",
    "reward",
    "observations",
    "avoided_later_observations",
    "covered",
    "correct",
    "actual_resource_work",
    "actual_spikes",
    "actual_snn_cell_updates",
    "price_used",
    "shadow_price_before",
    "shadow_price_after",
    "balance_before",
    "balance_after",
    "budget_forced_abstention",
    "native_fallbacks",
    "applied_readouts",
)


def paired_interval(differences, *, family_alpha, comparisons, practical_effect):
    values = np.asarray(differences, dtype=float)
    if values.ndim != 1 or len(values) < 2 or not np.isfinite(values).all():
        raise ValueError("at least two independent finite seed differences required")
    mean = float(values.mean())
    standard_error = float(values.std(ddof=1) / np.sqrt(len(values)))
    quantile = float(
        student_t.ppf(1 - family_alpha / (2 * comparisons), len(values) - 1)
    )
    lower, upper = mean - quantile * standard_error, mean + quantile * standard_error
    return {
        "independent_seeds": len(values),
        "paired_differences": values.tolist(),
        "mean_difference": mean,
        "standard_error": standard_error,
        "confidence_level": 1 - family_alpha / comparisons,
        "lower": lower,
        "upper": upper,
        "minimum_practical_effect": practical_effect,
        "superiority_established": lower > practical_effect,
    }


def add_work(total, increment):
    for key, value in increment.items():
        total[key] = (
            max(total.get(key, 0), value)
            if key.startswith("peak_")
            else total.get(key, 0) + value
        )


def summarize(root, audit_root, destination, source_seal):
    root, audit_root, destination = Path(root), Path(audit_root), Path(destination)
    with measured_stage(
        destination,
        identity={"stage": "registered_statistics"},
        scope="Verification of complete native audit roster, seed-level reduction, paired intervals and all cost/trajectory summaries.",
    ) as cost:
        config, source = protocol(), verify(source_seal)
        expected = expected_roster(config)
        index = json.loads((root / "INDEX.json").read_text())
        audit_index = json.loads((audit_root / "INDEX.json").read_text())
        verify_roster(index["organs"], expected)
        verify_roster(audit_index["organs"], expected)
        if (
            not audit_index["passed"]
            or audit_index["source"] != source
            or audit_index["deployment_index_sha256"] != sha(root / "INDEX.json")
        ):
            raise ValueError("complete identity-bound native audit required")
        seed_rows, traces, execution_work, replay_work = [], {}, {}, {}
        total_episodes, runtime_cpu, replay_cpu = 0, 0.0, 0.0
        for record in audit_index["organs"]:
            audit_path = audit_root / "organs" / f"{record['organ']}.json"
            organ_root = root / "organs" / record["organ"]
            if (
                sha(audit_path) != record["audit_sha256"]
                or sha(organ_root / "INDEX.json") != record["index_sha256"]
            ):
                raise ValueError("native evidence changed after independent audit")
            audit = json.loads(audit_path.read_text())
            native = json.loads((organ_root / "INDEX.json").read_text())
            if (
                not audit["passed"]
                or not audit["raw_bytes_unchanged"]
                or audit["development_only"]
            ):
                raise ValueError(
                    "failed or development-only evidence cannot enter inference"
                )
            episodes = audit["episode_metrics"]
            if len(episodes) != config["deployment"]["episodes_per_organ"]:
                raise ValueError("partial episode group cannot enter a seed mean")
            total_episodes += len(episodes)
            seed_row = {
                key: record[key] for key in ("seed", "split", "variant", "training_arm")
            }
            seed_row["means"] = {
                key: float(np.mean([row["metrics"][key] for row in episodes]))
                for key in METRICS
            }
            covered = sum(row["metrics"]["covered"] for row in episodes)
            seed_row["conditional_accuracy"] = (
                None
                if not covered
                else sum(row["metrics"]["correct"] for row in episodes) / covered
            )
            seed_rows.append(seed_row)
            traces[record["seed"], record["split"], record["variant"]] = episodes
            for episode in native["episodes"]:
                add_work(execution_work, episode["work"])
            add_work(replay_work, audit["work"])
            runtime_cpu += native["parent_cpu_ns"] / 1e9 + native["child_cpu_seconds"]
            replay_cpu += audit["parent_cpu_ns"] / 1e9 + audit["child_cpu_seconds"]
        if total_episodes != config["deployment"]["expected_episodes"]:
            raise ValueError("episode roster incomplete")
        means = {
            (row["seed"], row["split"], row["variant"]): row["means"]
            for row in seed_rows
        }
        settings = config["statistics"]
        primary = []
        for first, second in settings["primary_contrasts"]:
            difference = [
                means[seed, settings["primary_split"], first]["utility"]
                - means[seed, settings["primary_split"], second]["utility"]
                for seed in config["confirmation_seeds"]
            ]
            primary.append(
                {
                    "first": first,
                    "second": second,
                    "split": settings["primary_split"],
                    **paired_interval(
                        difference,
                        family_alpha=settings["family_alpha"],
                        comparisons=len(settings["primary_contrasts"]),
                        practical_effect=settings["minimum_practical_effect"],
                    ),
                }
            )
        summaries = []
        for split in config["deployment"]["splits"]:
            for variant in config["deployment"]["variants"]:
                rows = [
                    means[seed, split, variant["id"]]
                    for seed in config["confirmation_seeds"]
                ]
                summaries.append(
                    {
                        "split": split,
                        "variant": variant["id"],
                        "seed_count": len(rows),
                        "episodes": len(rows)
                        * config["deployment"]["episodes_per_organ"],
                        "means": {
                            key: float(np.mean([row[key] for row in rows]))
                            for key in METRICS
                        },
                    }
                )
        trajectory = []
        for first, second in (
            ("meta_live", "meta_frozen"),
            ("meta_live", "meta_off"),
            ("meta_live", "fixed_live"),
            ("fixed_live", "fixed_frozen"),
        ):
            pairs = changed_time = changed_action = 0
            for seed in config["confirmation_seeds"]:
                for split in config["deployment"]["splits"]:
                    for a, b in zip(
                        traces[seed, split, first],
                        traces[seed, split, second],
                        strict=True,
                    ):
                        if a["case"] != b["case"]:
                            raise ValueError("paired trajectory case identity mismatch")
                        pairs += 1
                        changed_time += (
                            a["metrics"]["observations"] != b["metrics"]["observations"]
                        )
                        changed_action += (
                            a["metrics"]["decision"] != b["metrics"]["decision"]
                        )
            trajectory.append(
                {
                    "first": first,
                    "second": second,
                    "paired_episodes": pairs,
                    "different_stopping_times": changed_time,
                    "different_terminal_actions": changed_action,
                }
            )
        result = {
            "schema": "hepta.adaptive-neuron.registered-statistics.v2",
            "source": source,
            "deployment_index_sha256": sha(root / "INDEX.json"),
            "audit_index_sha256": sha(audit_root / "INDEX.json"),
            "complete": True,
            "organs": len(seed_rows),
            "episodes": total_episodes,
            "independent_seeds": len(config["confirmation_seeds"]),
            "primary_contrasts": primary,
            "descriptive_summaries": summaries,
            "seed_means": seed_rows,
            "trajectory_changes": trajectory,
            "execution_work": execution_work,
            "independent_replay_work": replay_work,
            "nested_native_execution_cpu_seconds": runtime_cpu,
            "nested_independent_replay_cpu_seconds": replay_cpu,
            "cost_qualification": "Native CPU entries are nested components of enclosing stage receipts. Sum disjoint top-level stages only. Budget work is a declared resource proxy; no Joule or production throughput claim.",
            "inference_qualification": "Only the two frozen OOD contrasts are confirmatory. Episodes within a seed are not independent replicates. All baselines and negative results remain reported.",
        }
        if verify(source_seal) != source:
            raise ValueError("source identity changed during registered statistics")
        write_json_exclusive(destination / "STATISTICS.json", result)
        cost.update(
            organs=len(seed_rows),
            episodes=total_episodes,
            statistics_sha256=sha(destination / "STATISTICS.json"),
        )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "audit-root", "destination", "source-seal"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.root, args.audit_root, args.destination, args.source_seal)
    print(
        json.dumps(
            {
                "complete": result["complete"],
                "primary_contrasts": result["primary_contrasts"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
