"""Check the complete registered factorial against retained files and weights."""

from collections import Counter
import itertools
import math
from pathlib import Path

import numpy as np
import torch

from .core import ce, groups, read, sha, tensor_digest, trajectory


def checkpoint(audit, path, declaration):
    payload = torch.load(path, map_location="cpu", weights_only=True)
    state = payload["state_dict"]
    parameter_hash = tensor_digest(state)
    audit.check(sha(path) == declaration["sha256"], "checkpoint_file_identity", path)
    audit.check(parameter_hash == declaration["parameters_sha256"], "checkpoint_parameter_identity", path)
    audit.check(payload["config"] == declaration["config"], "checkpoint_configuration", path)
    audit.check(sum(v.numel() for v in state.values()) == declaration["parameters"], "checkpoint_parameter_count", path)
    return parameter_hash, groups(state)


def evaluation(audit, directory, report, model_hash, namespace, count, draws):
    expected = {(source, draw) for source in range(count) for draw in range(draws)}
    actual = [(row["source"], row["draw"]) for row in report["rows"]]
    audit.check(set(actual) == expected and len(actual) == len(expected), "evaluation_source_draw_complete", directory)
    records = []
    for row in report["rows"]:
        path = directory / f"source-{row['source']:03d}-draw-{row['draw']}" / "TRAJECTORY.json"
        item = trajectory(audit, path, "matrix.analysis", model_hash)
        audit.check(row["source_namespace"] == namespace and item["source"] == f"synthetic.{namespace}.{row['source']}",
                    "evaluation_namespace", path)
        for field, key in (("return", "sealed_return"), ("cost", "sealed_cost"), ("utility", "utility")):
            audit.near(row[field], item[key], "evaluation_row_" + field, path)
        audit.check(row["actions"] == item["actions"] and row["failure"] == item["failure"], "evaluation_actions_failure", path)
        audit.check(row["model_sha256"] == model_hash and row["profile_sha256"] == item["profile_sha256"],
                    "evaluation_row_binding", path)
        record = read(path)
        audit.check(row["artifacts"] == record["outcome"]["artifact_sha256"], "evaluation_row_artifacts", path)
        sealed_events = record["events"] + [read(path.with_name("SEAL_COST.json"))]
        by_kind = {kind: math.fsum(e["amount"] for e in sealed_events if e["action"] == kind)
                   for kind in {e["action"] for e in sealed_events}}
        audit.check(set(row["cost_by_kind"]) == set(by_kind), "evaluation_cost_kinds", path)
        for kind, cost in by_kind.items():
            audit.near(row["cost_by_kind"].get(kind, -1), cost, "evaluation_cost_kind_amount", path)
        records.append(item)
    audit.near(report["population_ce_plugin"], ce([r["sealed_return"] for r in records]), "population_ce", directory)
    audit.near(report["mean_cost"], np.mean([r["sealed_cost"] for r in records]), "evaluation_mean_cost", directory)
    audit.near(report["mean_utility"], np.mean([r["utility"] for r in records]), "evaluation_mean_utility", directory)
    audit.check(report["failures"] == sum(r["failure"] is not None for r in records), "evaluation_failure_count", directory)
    retained = list(directory.glob("source-*-draw-*/TRAJECTORY.json"))
    audit.check(len(retained) == len(expected), "evaluation_no_unreported_trajectories", directory)
    return records


def paired(audit, left, right, report, path, *, seed, bootstrap):
    source_ids = [r["source"] for r in left]
    audit.check(source_ids == [r["source"] for r in right], "paired_source_order", path)
    unique = list(dict.fromkeys(source_ids))
    counts = Counter(source_ids)
    weight = np.asarray([1 / counts[source] for source in source_ids])
    a = np.asarray([r["sealed_return"] for r in left]); b = np.asarray([r["sealed_return"] for r in right])
    ca, cb = ce(a, weight), ce(b, weight)
    for field, value in (("ce_left", ca), ("ce_right", cb), ("ce_delta", ca - cb),
                         ("mean_paired_return_delta", np.average(a - b, weights=weight))):
        audit.near(report[field], value, "paired_" + field, path)
    indices = [np.flatnonzero(np.asarray(source_ids) == value) for value in unique]
    rng, estimates = np.random.default_rng(seed), []
    for _ in range(bootstrap):
        blocks = [indices[i] for i in rng.integers(len(indices), size=len(indices))]
        selected = np.concatenate(blocks)
        mass = np.concatenate([np.full(len(block), 1 / len(block)) for block in blocks])
        estimates.append(ce(a[selected], mass) - ce(b[selected], mass))
    ci = np.quantile(estimates, [.025, .975])
    for actual, expected in zip(report["ce_delta_percentile_95"], ci):
        audit.near(actual, expected, "source_bootstrap_interval", path)
    audit.check(report["independent_units"] == len(unique) and report["paired_draws"] == len(a)
                and report["bootstrap_unit"] == "original_source", "source_bootstrap_units", path)


def run(audit, v3, *, partial=False):
    root = v3 / "evidence/matrix_frozen_20261030"
    protocol = read(v3 / "protocol.json")
    frozen = read(root / "FROZEN_SOURCE.json")
    audit.sources(frozen, v3)
    results = sorted(root.glob("seed-*-width-*/RESULT.json"))
    expected = set(itertools.product(protocol["seeds"], protocol["widths"]))
    identities, cells, controls_total, training_total, analysis_total = set(), [], 0, 0, 0
    for path in results:
        cell = read(path); directory = path.parent
        identities.add((cell["seed"], cell["width"]))
        audit.check(not cell["smoke"] and read(directory / "EXECUTED_PROTOCOL.json") == protocol,
                    "registered_non_smoke_protocol", path)
        audit.check(cell["protocol_sha256"] == sha(v3 / "protocol.json"), "registered_protocol_hash", path)
        audit.sources(cell["source_sha256"], v3); audit.sources(cell["parent_source_sha256"], v3.parent)
        bases = {}
        for mode in protocol["modes"]:
            base = cell["pretraining"][mode]
            base_hash, base_groups = checkpoint(audit, directory / mode / "PRETRAINED.pt", base["checkpoint"])
            audit.check(base_groups == base["training"]["final_group_hashes"], "pretrained_group_identity", path)
            bases[mode] = (base_hash, base_groups)
        expected_arms = {".".join(x) for x in itertools.product(protocol["modes"], protocol["content_training"], protocol["policies"])}
        audit.check(set(cell["arms"]) == expected_arms and set(cell["executed_arm_order"]) == expected_arms,
                    "factorial_arm_completeness", path)
        evaluated, training_costs = {}, {}
        for name, arm in cell["arms"].items():
            mode, content, policy = name.split(".")
            model_hash, actual_groups = checkpoint(audit, directory / name / "MODEL.pt", arm["checkpoint"])
            training = arm["training"]
            audit.check(training["initial_group_hashes"] == bases[mode][1], "identical_pretrained_start", directory / name)
            audit.check(training["final_group_hashes"] == actual_groups, "trained_parameter_group_identity", directory / name)
            if content == "frozen":
                audit.check(actual_groups["generator"] == bases[mode][1]["generator"], "frozen_generator_unchanged", directory / name)
            if policy == "fixed":
                audit.check(actual_groups["actor"] == bases[mode][1]["actor"], "fixed_actor_unchanged", directory / name)
            training_rows = []
            for update in range(protocol["joint_updates"]):
                batch_hashes = set()
                for draw in range(protocol["joint_batch"]):
                    trace = directory / name / "training" / f"update-{update:04d}" / f"draw-{draw}" / "TRAJECTORY.json"
                    item = trajectory(audit, trace, "matrix.train", bases[mode][0] if update == 0 else None)
                    audit.check(item["source"].startswith("synthetic." + protocol["train_namespace"] + "."), "training_namespace", trace)
                    batch_hashes.add(item["parameter_sha256"]); training_rows.append(item)
                audit.check(len(batch_hashes) == 1, "immutable_training_batch_parameters", directory / name)
            training_total += len(training_rows)
            audit.check(len(list((directory/name/"training").glob("update-*/draw-*/TRAJECTORY.json"))) == len(training_rows),
                        "training_no_missing_or_unreported_trajectories", directory/name)
            audit.check(training["actual_episodes"] == len(training_rows), "training_episode_count", directory/name)
            audit.check(training["failures"] == sum(r["failure"] is not None for r in training_rows), "training_failure_count", directory/name)
            audit.check(training["initial_stop_samples"] == sum(bool(r["actions"]) and r["actions"][0] == "stop" for r in training_rows),
                        "initial_stop_sample_count", directory/name)
            audit.near(training["total_episode_cost"], math.fsum(r["sealed_cost"] for r in training_rows), "training_total_cost", directory/name)
            service = math.fsum(r["service_fee"] for r in training_rows)
            training_costs[name] = (cell["phase_costs"]["training."+name]["physical_cost"] + service +
                                    cell["phase_costs"]["pretraining."+mode]["physical_cost"])
            evaluated[name] = evaluation(audit, directory/name/"analysis", arm["evaluation"], model_hash,
                                         protocol["development_namespace"], protocol["development_sources"], protocol["evaluation_draws_per_source"])
            analysis_total += len(evaluated[name])
            if content == "joint" and policy == "dynamic":
                audit.check(set(cell["inference_controls"][mode]) == set(protocol["inference_controls"]), "inference_controls_complete", path)
                for control, report in cell["inference_controls"][mode].items():
                    records = evaluation(audit, directory/name/"controls"/control, report, model_hash,
                                         protocol["development_namespace"], protocol["development_sources"], protocol["evaluation_draws_per_source"])
                    controls_total += len(records)
        for comparison, report in cell["comparisons"].items():
            left, right = comparison.split("__minus__")
            paired(audit, evaluated[left], evaluated[right], report, path,
                   seed=cell["seed"], bootstrap=protocol["bootstrap_replicates"])
            for name in (left, right):
                audit.near(report["training_cost"][name], training_costs[name], "amortization_training_cost", path)
            for requests, actual in report["amortized_training_deltas"].items():
                expected_delta = report["ce_delta"] - (training_costs[left] - training_costs[right]) / int(requests)
                audit.near(actual, expected_delta, "amortized_training_delta", path)
        audit.check(cell["confirmation_sources_consumed"] == 0 and not cell["research_effect_qualified"] and not cell["natural_semantics_qualified"],
                    "development_claim_boundary", path)
        cells.append({"seed": cell["seed"], "width": cell["width"], "result_sha256": sha(path), "arms": len(cell["arms"])})
    audit.check(identities <= expected and len(identities) == len(results), "registered_cell_identity", root)
    if not partial:
        audit.check(identities == expected, "all_six_registered_cells_complete", root)
    summary_path = root / "SUMMARY.json"
    if summary_path.exists():
        summary = read(summary_path)
        for name, value in (("cells", len(cells)), ("training_trajectories", training_total),
                            ("analysis_trajectories", analysis_total), ("inference_control_trajectories", controls_total)):
            audit.check(summary[name] == value, "matrix_summary_count_"+name, summary_path)
    return {"completed_cells": cells, "expected_cells": sorted(expected), "training_trajectories": training_total,
            "analysis_trajectories": analysis_total, "control_trajectories": controls_total,
            "frozen_source_sha256": sha(root/"FROZEN_SOURCE.json"), "full_matrix_present": identities == expected}
