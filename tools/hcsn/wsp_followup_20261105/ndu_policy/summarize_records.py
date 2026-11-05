"""Descriptive arithmetic on frozen records; never calls a model or environment."""
import argparse
import gzip
import json
from pathlib import Path
import statistics
import numpy as np


def read(path):
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.name.endswith(".gz") else data)


def describe(values):
    return dict(count=len(values), total=sum(values), minimum=min(values),
                maximum=max(values), mean=statistics.mean(values))


def summarize(root):
    fits = [11, 23, 37, 53, 71]
    costs, targets, sizes, cold = [], [], [], []
    for fit in fits:
        record = read(root / f"fit_{fit}_CANDIDATES.json.gz")
        setup = sum(x["shared_setup_cpu_seconds"] for x in record["solvers"].values())
        shared = record["shared_data_bellman_feature_preparation_cpu_seconds"] + setup
        entry = dict(fit=fit, rows=record["rows"], preparation_cpu_seconds=shared,
                     candidate_all_arms_cpu_seconds=record["candidate_cpu_seconds"])
        for method, name in (("direct", "D"), ("gradient", "G")):
            solve = sum(x[method]["cpu_seconds"] for x in record["solvers"].values())
            serialization = record["models"][name]["serialize_save_load_cpu_seconds"]
            entry[name] = dict(solver_cpu_seconds=solve, serialization_cpu_seconds=serialization,
                               inclusive_construction_cpu_seconds=shared+solve+serialization)
        costs.append(entry)
        for group, selection in (("continuation", slice(0, 3)), ("belief", slice(3, 4))):
            problem, solvers = record["problems"][group], record["solvers"][group]
            original = np.array(record["heads"]["C"])[selection]
            delta = np.array(record["heads"]["D"])[selection] - original
            a, g = np.array(problem["matrices"]), np.array(problem["rhs"])
            change = sum(float(d @ matrix @ d-2*rhs @ d) for matrix, d, rhs in zip(a, delta, g))
            targets.append(dict(fit=fit, group=group,
                C_weighted_target_loss_from_stored_quadratic=solvers["direct"]["objective"]-change,
                D_weighted_target_loss=solvers["direct"]["weighted_target_loss"],
                G_weighted_target_loss=solvers["gradient"]["weighted_target_loss"],
                D_regularized_objective=solvers["direct"]["objective"],
                G_regularized_objective=solvers["gradient"]["objective"],
                gradient_steps=solvers["gradient"]["steps"],
                direct_numerical_fw_gap=solvers["direct"]["numerical_fw_gap"],
                gradient_numerical_fw_gap=solvers["gradient"]["numerical_fw_gap"]))
        for world in record["training_worlds"]:
            identity = world["own_bellman"]
            sizes.append(dict(split="train", fit=fit, world_id=world["world_id"],
                              full_states=world["full_states"], markov_states=identity["compilation"]["states"],
                              table_bytes=identity["table_bytes"]))
            cold.append(dict(split="train", identity=identity))
    metrics = {}
    for split in ("validation", "test"):
        metrics[split] = {}
        for domain in ("iid", "ood"):
            rows = []
            for fit in fits:
                records = read(root / f"{split}_{fit}_{domain}_RESULTS.json.gz")["records"]
                rows.extend(records)
                for world in records:
                    identity = world["own_bellman"]
                    sizes.append(dict(split=split, fit=fit, world_id=world["world_id"],
                                      markov_states=identity["compilation"]["states"], table_bytes=identity["table_bytes"]))
                    cold.append(dict(split=split, identity=identity))
            metrics[split][domain] = {}
            for name in rows[0]["arms"]:
                arms = [r["arms"][name] for r in rows]
                metrics[split][domain][name] = {
                    metric: statistics.mean(arm[metric] for arm in arms) for metric in (
                        "utility", "fees", "reads_requested", "reads_completed", "repairs", "elapsed", "correct", "submitted",
                        "selected_q_rmse", "posterior_probability_mse", "teacher_regret_mean", "ranking_error_mean", "margin_absolute_error_mean")}
                metrics[split][domain][name]["measured_policy_cpu_total"] = sum(a["policy_cpu_seconds"] for a in arms)
                metrics[split][domain][name]["measured_arm_initialization_cpu_total"] = sum(a["arm_initialization_cpu_seconds"] for a in arms)
    inclusive = {name: sum(c[name]["inclusive_construction_cpu_seconds"] for c in costs) for name in ("D", "G")}
    solve = {name: sum(c[name]["solver_cpu_seconds"] for c in costs) for name in ("D", "G")}
    phases = {}
    for split in ("train", "validation", "test"):
        matching = [x for x in sizes if x["split"] == split]
        identities = [x["identity"] for x in cold if x["split"] == split]
        phases[split] = dict(worlds=len(matching), markov_states=describe([x["markov_states"] for x in matching]),
            table_bytes=describe([x["table_bytes"] for x in matching]),
            full_cold_preparation_cpu_seconds=describe([x["full_cold_preparation_cpu_seconds"] for x in identities]),
            compilation_cpu_seconds=sum(x["compilation"]["cpu_seconds"] for x in identities),
            verification_cpu_seconds=sum(x["verification_cpu_seconds"] for x in identities),
            serialization_cpu_seconds=sum(x["serialization"]["cpu_seconds"] for x in identities),
            load_cpu_seconds=sum(x["load"]["cpu_seconds"] for x in identities),
            maximum_bellman_residual=max(x["bellman_residual_max"] for x in identities),
            maximum_probability_sum_error=max(x["probability_sum_error_max"] for x in identities))
        if split == "train":
            phases[split]["full_states"] = describe([x["full_states"] for x in matching])
    return dict(schema="hepta-own-bellman-derived-descriptive-analysis-v1", costs_by_fit=costs,
        costs_aggregate=dict(solver_cpu_seconds=solve, inclusive_construction_cpu_seconds=inclusive,
                            solver_stage_G_over_D=solve["G"]/solve["D"], inclusive_G_over_D=inclusive["G"]/inclusive["D"],
                            scope="same shared TRAIN targets/features/Gram/eigen setup charged to each method, plus its solve and model save/load; excludes validation and process startup"),
        training_target_losses=targets, graph_and_cold_preparation_by_phase=phases, full_world_sizes=sizes,
        descriptive_metrics=metrics,
        caveats=["All task error metrics are on each arm's own visitation distribution, not paired same-state errors.",
                 "Policy CPU aggregates are instrumented expected-trajectory execution with an initially empty per-arm feature cache; no packet I/O or native performance claim.",
                 "Cold J preparation is additional to warm policy lookup and excludes any economic pricing of CPU.",
                 "Target losses reconstructed from stored quadratics do not reexecute features or prove their provenance.",
                 "This is descriptive analysis of the frozen experiment and creates no new scientific candidate or gate."])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("run", type=Path); parser.add_argument("output", type=Path)
    args = parser.parse_args(); result = summarize(args.run)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False); stream.write("\n")
    print(json.dumps({key: result[key] for key in ("costs_aggregate", "graph_and_cold_preparation_by_phase")}, sort_keys=True))
