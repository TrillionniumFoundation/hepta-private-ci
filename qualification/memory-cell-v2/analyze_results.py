"""Derive preregistered comparisons and a static figure from a verified full run."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np


PACKAGE = Path(__file__).resolve().parent
sys.path.insert(0, str(PACKAGE.parent / "memory-cell-research"))
from memory_cells.metrics import paired_cluster_interval  # noqa: E402
from v2.evidence import fingerprint, verify_run, write_json  # noqa: E402


PRIMARY_TASKS = ("module_attribute", "latest_sampled_change", "schema_execution")
CHAIN_TASKS = ("schema_chain", "commit_owner_chain")
FIXED_ARMS = ("fixed-single", "fixed-domain", "fixed-hash")


def mean(values):
    return float(np.mean(list(values)))


def interval(candidate, baseline, seeds, protocol):
    settings = protocol["statistics"]
    return paired_cluster_interval(
        candidate,
        baseline,
        seeds,
        bootstrap_seed=settings["bootstrap_seed"],
        n_boot=settings["bootstrap_draws"],
        confidence=settings["confidence"],
    )


def ordered_runs(stage, seeds):
    runs = stage["runs"]
    by_seed = {run["seed"]: run for run in runs}
    if len(by_seed) != len(runs) or set(by_seed) != set(seeds):
        raise ValueError(
            "analysis requires exactly one component run per protocol seed"
        )
    return [by_seed[seed] for seed in seeds]


def analyze(results, protocol):
    seeds = protocol["seeds"]
    runs = ordered_runs(results["real"], seeds)
    real = {"task_means": results["real"]["task_summary"], "runs": [], "cost_means": {}}
    for run in runs:
        scores = {
            arm: mean(data["tasks"][task]["final_accuracy"] for task in PRIMARY_TASKS)
            for arm, data in run["results"].items()
            if all(t in data["tasks"] for t in PRIMARY_TASKS)
        }
        real["runs"].append(
            {
                "seed": run["seed"],
                "primary_macro_accuracy": scores,
                "multi_parameters": run["multi_trainable_params_including_router"],
                "single_parameters": run["single_trainable_params"],
                "oracle_route_gap": mean(
                    run["oracle_route_gaps"][task] for task in PRIMARY_TASKS
                ),
            }
        )
    real["primary_macro_means"] = {
        arm: mean(r["primary_macro_accuracy"][arm] for r in real["runs"])
        for arm in real["runs"][0]["primary_macro_accuracy"]
    }
    real["learned_multi_minus_single_interval"] = interval(
        [r["primary_macro_accuracy"]["multi_learned"] for r in real["runs"]],
        [r["primary_macro_accuracy"]["single_schema"] for r in real["runs"]],
        seeds,
        protocol,
    )
    difference = real["learned_multi_minus_single_interval"]
    real["matched_parameter_budget"] = all(
        r["single_parameters"] >= r["multi_parameters"] for r in real["runs"]
    )
    real["fixed_multi_gate_passed"] = bool(
        real["matched_parameter_budget"]
        and difference["paired_difference"]
        > protocol["gates"]["fixed_multi_advantage"]["mean_accuracy_gain_min"]
        and difference["lower"] is not None
        and difference["lower"] > 0
    )
    real["fresh_process_reads"] = sum(len(r["fresh_process_validation"]) for r in runs)
    real["fresh_process_queries"] = sum(
        v["query_count"] for r in runs for v in r["fresh_process_validation"].values()
    )
    real["all_fresh_reads_match"] = all(
        v["predictions_match_in_process"]
        for r in runs
        for v in r["fresh_process_validation"].values()
    )
    real["single_record_identity_gate_passed"] = all(
        r["results"]["single_schema"]["tasks"][t]["event_value_identity_accuracy"]
        >= protocol["gates"]["single_parameter_memory"]["record_value_accuracy_min"]
        for r in runs
        for t in PRIMARY_TASKS
    )
    for arm in ("multi", "single", "exact"):
        real["cost_means"][arm] = {
            key: mean(r["cost"]["standalone_arms"][arm][key] for r in runs)
            for key in (
                "retained_bytes",
                "parameter_bytes",
                "model_write_seconds",
                "validation_cold_seconds",
                "validation_in_process_seconds",
            )
        }
    real["base_bytes"] = results["real"]["shared_base_bytes_once"]
    real["shared_base_load_seconds_once"] = results["real"][
        "shared_base_load_seconds_once"
    ]
    real["common_preparation_mean_seconds"] = mean(
        r["cost"]["source_and_index_setup_seconds"] for r in runs
    )
    real["shared_training_encoding_mean_seconds"] = mean(
        r["cost"]["shared_training_encoding_seconds"] for r in runs
    )
    real["write_cost_scope"] = (
        "model_write_seconds excludes the separately reported common preparation, base load and feature encoding; cold validation is also separate"
    )
    real["composition"] = {}
    for task in CHAIN_TASKS:
        values = {
            arm: mean(r["results"][arm]["tasks"][task]["final_accuracy"] for r in runs)
            for arm in (
                "multi_learned",
                "multi_no_edges",
                "multi_shuffled_edges",
                "exact",
                "exact_no_edges",
                "exact_shuffled_edges",
            )
        }
        values["parameter_edge_removal_drop"] = (
            values["multi_learned"] - values["multi_no_edges"]
        )
        values["parameter_edge_permutation_drop"] = (
            values["multi_learned"] - values["multi_shuffled_edges"]
        )
        values["supplied_edge_gate_passed"] = (
            values["parameter_edge_removal_drop"] >= 0.1
            and values["parameter_edge_permutation_drop"] >= 0.1
        )
        values["per_seed_queries"] = [
            r["results"]["multi_learned"]["tasks"][task]["queries"] for r in runs
        ]
        real["composition"][task] = values

    gruns = ordered_runs(results["growth"], seeds)
    growth = {
        "runs": [
            {
                "seed": r["seed"],
                "accuracy": r["mean_update_accuracy"],
                "adopted": r["accepted_evolution_operations"],
                "criterion_met": r["criterion_met"],
                "maintenance_guards_passed": r["maintenance_guards_passed"],
            }
            for r in gruns
        ],
        "accuracy_means": {
            arm: mean(r["mean_update_accuracy"][arm] for r in gruns)
            for arm in ("policy", *FIXED_ARMS)
        },
        "comparisons": {},
        "cost_means": {},
        "strict_all_seed_gate_passed": all(r["criterion_met"] for r in gruns),
        "passing_seeds": sum(r["criterion_met"] for r in gruns),
        "maintenance_guards_all_passed": all(
            r["maintenance_guards_passed"] for r in gruns
        ),
    }
    for arm in FIXED_ARMS:
        growth["comparisons"][arm] = {
            "accuracy_interval": interval(
                [r["mean_update_accuracy"]["policy"] for r in gruns],
                [r["mean_update_accuracy"][arm] for r in gruns],
                seeds,
                protocol,
            ),
            "mean_net_gain_per_query": mean(
                r["comparisons"][arm]["net_gain_per_query_at_protocol_h"] for r in gruns
            ),
            "per_seed_break_even_queries_per_update": [
                r["comparisons"][arm]["break_even_queries_per_update"] for r in gruns
            ],
        }
    for arm in ("policy", *FIXED_ARMS):
        growth["cost_means"][arm] = {
            key: mean(r["costs"][arm][key] for r in gruns)
            for key in (
                "write_seconds",
                "migration_restore_seconds",
                "other_maintenance_seconds_including_migrations",
                "selection_read_seconds",
                "read_seconds_per_query",
                "retained_artifact_source_and_replay_bytes",
                "deployed_parameter_bytes",
                "amortized_resource_cost_per_query",
                "expected_resource_cost_at_protocol_h",
            )
        }

    external = {
        "datasets": results["external"]["datasets"],
        "cost_means": {},
        "independent_domains": 3,
        "split_seeds_are_not_independent_domains": True,
    }
    if set(external["datasets"]) != {"iris", "wine", "digits"}:
        raise ValueError("external domain inventory differs from the frozen protocol")
    for name in external["datasets"]:
        cases = [r for r in results["external"]["runs"] if r["dataset"] == name]
        if len(cases) != len(seeds) or {r["seed"] for r in cases} != set(seeds):
            raise ValueError("external dataset lacks the declared repeated splits")
        external["cost_means"][name] = {
            key: mean(r["costs"]["deployment_bytes"][key] for r in cases)
            for key in ("model_without_replay", "model_with_replay", "exact", "knn")
        }
    rruns = ordered_runs(results["routing"], seeds)
    routing = {"means": {}, "learned_group_means": {}}
    for mode in ("typed", "literal", "learned"):
        routing["means"][mode] = {
            key: mean(r["metrics"][mode]["all"][key] for r in rruns)
            for key in (
                "decision_accuracy",
                "coverage",
                "wrong_accepted_rate",
                "oracle_gap",
            )
        }
    for group in rruns[0]["metrics"]["learned"]["groups"]:
        routing["learned_group_means"][group] = {
            key: mean(r["metrics"]["learned"]["groups"][group][key] for r in rruns)
            for key in ("decision_accuracy", "coverage", "oracle_gap")
        }
    return {
        "schema": "memory-cell-v2.analysis.v1",
        "seeds": seeds,
        "real": real,
        "growth": growth,
        "routing": routing,
        "external": external,
        "general_memory_system_established": False,
        "limitations": [
            "bootstrap intervals are conditional on fixed workload designs",
            "five trials cannot certify population-wide superiority",
            "graph schemas and ports are supplied",
            "classification transfer is not general episodic memory",
            "full priced lifecycle cost does not isolate same-optimizer-work causality",
        ],
    }


def plot(analysis, output):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    fig, axes = plt.subplots(2, 2, figsize=(13, 9), layout="constrained")
    blue, teal, orange, gray = "#365DA7", "#138A82", "#D97B29", "#77838D"
    ax = axes[0, 0]
    x = np.arange(3)
    for offset, (arm, label, color) in enumerate(
        (
            ("single_schema", "Single cell", blue),
            ("multi_learned", "Multi + actual route", teal),
            ("exact", "Exact store", gray),
        )
    ):
        values = [
            analysis["real"]["task_means"][arm][t]["seed_mean_final_accuracy"] * 100
            for t in PRIMARY_TASKS
        ]
        ax.bar(x + (offset - 1) * 0.24, values, 0.23, color=color, label=label)
    ax.set(
        xticks=x,
        xticklabels=["Semantic", "Episodic", "Procedure result"],
        ylim=(0, 105),
        ylabel="Hidden query accuracy (%)",
        title="A  Fixed real repository tasks",
    )
    ax.legend(fontsize=8, loc="lower left")

    ax = axes[0, 1]
    arms = ("policy", *FIXED_ARMS)
    values = [analysis["growth"]["accuracy_means"][a] * 100 for a in arms]
    ax.bar(np.arange(4), values, color=[teal, blue, orange, gray], width=0.65)
    for index, arm in enumerate(arms):
        ys = [r["accuracy"][arm] * 100 for r in analysis["growth"]["runs"]]
        ax.scatter(
            np.full(len(ys), index) + np.linspace(-0.16, 0.16, len(ys)),
            ys,
            s=19,
            color="#18212B",
            zorder=3,
        )
    ax.set(
        xticks=np.arange(4),
        xticklabels=["Adaptive", "Single", "Domain split", "Hash split"],
        ylim=(0, 100),
        ylabel="Mean over four updates (%)",
        title="B  Capacity-pressure lifecycle (dots = seeds)",
    )

    ax = axes[1, 0]
    names = ["iris", "wine", "digits"]
    for offset, (arm, label, color) in enumerate(
        (
            ("model", "Parameter model", teal),
            ("selected_knn", "Selection-chosen kNN", blue),
        )
    ):
        ys = [
            analysis["external"]["datasets"][n]["unseen_test"][arm]["mean"] * 100
            for n in names
        ]
        ax.bar(np.arange(3) + (offset - 0.5) * 0.3, ys, 0.29, color=color, label=label)
    ax.set(
        xticks=np.arange(3),
        xticklabels=[n.title() for n in names],
        ylim=(0, 105),
        ylabel="Unseen-input accuracy (%)",
        title="C  Three independent classification datasets",
    )
    ax.legend(fontsize=8, loc="lower left")

    ax = axes[1, 1]
    groups = ["public_type_alias", "known_cue_new_keys", "unseen_synonyms"]
    ys = [
        analysis["routing"]["learned_group_means"][g]["decision_accuracy"] * 100
        for g in groups
    ]
    ax.barh(np.arange(3), ys, color=[teal, teal, orange], height=0.55)
    for y, value in enumerate(ys):
        ax.text(
            min(value + 2, 96),
            y,
            f"{value:.1f}%",
            va="center",
            ha="left" if value < 90 else "right",
        )
    ax.set(
        yticks=np.arange(3),
        yticklabels=["Public type alias", "Known cue / new key", "Unseen synonym"],
        xlim=(0, 110),
        xlabel="Learned route decision accuracy (%)",
        title="D  Routing scope is measured separately",
    )
    ax.invert_yaxis()
    for ax in axes.flat:
        ax.set_axisbelow(True)
        ax.grid(
            axis="y" if ax is not axes[1, 1] else "x", color="#E9EDF1", linewidth=0.7
        )
    fig.suptitle(
        "MemoryCell v2 | Frozen five-seed CPU evaluation", fontsize=17, weight="bold"
    )
    fig.supxlabel(
        "Single-cell parameters are rounded up to cover multi + router. Full cost, given graph ports and repeated data limit the conclusions.",
        fontsize=9,
    )
    fig.savefig(output / "results.png", dpi=180, facecolor="white")
    fig.savefig(output / "results.svg", facecolor="white")
    plt.close(fig)
    return matplotlib.__version__


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verified = verify_run(args.run, PACKAGE.parents[1])
    if verified["mode"] != "frozen_protocol_research" or set(
        verified["completed_stages"]
    ) != {"routing", "real", "growth", "external"}:
        parser.error("analysis requires a verified full formal run")
    args.output.mkdir(parents=True, exist_ok=False)
    protocol = json.loads((args.run / "protocol.json").read_bytes())
    results = json.loads((args.run / "results.json").read_bytes())
    analysis = analyze(results, protocol)
    write_json(args.output / "analysis.json", analysis)
    plotting_version = plot(analysis, args.output)
    write_json(
        args.output / "MANIFEST.json",
        {
            "source_run_verification": verified,
            "analysis_script_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
            "matplotlib": plotting_version,
            "files": {
                p.name: fingerprint(p.read_bytes())
                for p in sorted(args.output.iterdir())
                if p.is_file()
            },
        },
    )
    print(
        json.dumps(
            {
                "analysis_saved": str(args.output),
                "source_manifest": verified["manifest_sha256"],
            }
        )
    )


if __name__ == "__main__":
    main()
