"""Read-only raw-logit analysis; three-seed/actor bootstrap is descriptive.

The analysis never trains, selects a checkpoint, or alters worker artifacts.
Formal test results require --allow-heldout. Output directories are create-only.
"""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import time

import numpy as np


METRICS = ("query_accuracy", "ce", "episode_exact_recall")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def describe(values):
    data = np.asarray(values, np.float64)
    return dict(n=len(data), mean=float(data.mean()), minimum=float(data.min()),
                maximum=float(data.max()), sample_sd=float(data.std(ddof=1)) if len(data) > 1 else None,
                values=data.tolist())


def budget_key(job):
    if "budget_cpu_seconds" in job:
        return "cpu_" + str(job["budget_cpu_seconds"])
    return "updates_" + str(job["updates"])


def score_arrays(raw):
    logits = np.asarray(raw["logits"], np.float64)
    target = np.asarray(raw["labels"], np.int64)
    ids, positions = raw["sample_ids"].astype(str), raw["position"]
    groups = raw["group_ids"].astype(str)
    if logits.ndim != 2 or len(logits) != len(target) or not np.isfinite(logits).all():
        raise ValueError("Invalid raw logits")
    if len(ids) != len(target) or len(groups) != len(target):
        raise ValueError("Raw query rows do not align")
    if len(set(zip(ids.tolist(), positions.tolist(), strict=True))) != len(ids):
        raise ValueError("Duplicate sample/position prediction")
    shifted = logits - logits.max(axis=1, keepdims=True)
    ce = np.log(np.exp(shifted).sum(axis=1)) - shifted[np.arange(len(target)), target]
    correct = logits.argmax(axis=1) == target
    episodes, episode_groups = {}, {}
    for identifier in np.unique(ids):
        selected = ids == identifier
        actor = np.unique(groups[selected])
        if len(actor) != 1:
            raise ValueError("An episode belongs to multiple groups")
        episodes[identifier] = np.array([correct[selected].mean(), ce[selected].mean(),
                                        float(correct[selected].all())])
        episode_groups[identifier] = str(actor[0])
    clusters = {}
    for actor in np.unique(groups):
        members = [episodes[key] for key, value in episode_groups.items() if value == actor]
        clusters[str(actor)] = np.mean(members, axis=0)
    metrics = dict(query_accuracy=float(correct.mean()), ce=float(ce.mean()),
        episode_exact_recall=float(np.mean([value[2] for value in episodes.values()])),
        queries=len(target), episodes=len(episodes), independent_groups=len(clusters),
        actor_macro_accuracy=float(np.mean([value[0] for value in clusters.values()])))
    ordering = np.lexsort((positions, ids))
    identity = [(str(ids[i]), int(positions[i]), int(target[i]), str(groups[i])) for i in ordering]
    return metrics, dict(episodes=episodes, clusters=clusters, identity=identity,
        input_sha=str(raw["input_array_sha256"].item()),
        checkpoint_sha=str(raw["checkpoint_sha256"].item()))


def paired_bootstrap(tables, repeats=2000, seed=2026110191):
    """Jointly resample shared items and training seeds; preserve arm pairing."""
    if not tables:
        raise ValueError("No paired seed tables")
    rng = np.random.default_rng(seed)
    keys = [sorted(table) for table in tables]
    same_items = all(items == keys[0] for items in keys)
    item_draws = rng.integers(0, len(keys[0]), size=(repeats, len(keys[0]))) if same_items else None
    per_seed_draws = []
    for table, items in zip(tables, keys, strict=True):
        values = np.stack([table[item] for item in items])
        draws = item_draws if same_items else rng.integers(0, len(items), size=(repeats, len(items)))
        per_seed_draws.append(values[draws].mean(axis=1))
    draws = np.stack(per_seed_draws, axis=1)
    chosen_seeds = rng.integers(0, len(tables), size=(repeats, len(tables)))
    boot = draws[np.arange(repeats)[:, None], chosen_seeds].mean(axis=1)
    means = np.stack([np.mean(list(table.values()), axis=0) for table in tables])
    return dict(repeats=repeats, seed=seed, paired_seeds=len(tables),
        unit_counts=[len(table) for table in tables], shared_item_ids_across_seeds=same_items,
        method="paired arm differences; bootstrap training seeds plus shared episode/actor IDs; percentile 2.5/97.5",
        metrics={name: dict(**describe(means[:, index]),
            descriptive_percentile_95=np.quantile(boot[:, index], [.025, .975]).tolist())
            for index, name in enumerate(METRICS)},
        significance_supported=False,
        limitation="Only three training seeds; AV has two reused test actors. Intervals describe resampling, not population significance.")


def meter_index(root):
    by_output, by_id, paths = {}, {}, []
    for path in sorted((root / "meter").rglob("whole_process.json")):
        receipt = json.loads(path.read_text())
        paths.append(path)
        by_id[receipt["job_id"]] = receipt
        argv = receipt.get("argv", [])
        if "--output" in argv:
            directory = Path(argv[argv.index("--output") + 1])
            if not directory.is_absolute():
                directory = Path(receipt["cwd"]) / directory
            by_output[str(directory.resolve())] = receipt
    return by_output, by_id, paths


def make_job_record(directory, summary, meter):
    job = summary["job"]
    record = dict(job_id=directory.name, directory=str(directory), task=job["task"],
        family=job["family"], mode=job.get("content_mode", "joint"), seed=job["seed"],
        budget=budget_key(job), data_seed=job.get("data_seed"), selected_step=summary["selected_step"],
        final_step=summary["final_step"], stop_reason=summary["stop_reason"],
        parameters=summary["total_parameters"], trainable_parameters=summary["trainable_parameters"],
        shared_parameters=summary["shared_parameters"],
        shared_donor_selected_step=summary.get("shared_donor_selected_step"),
        shared_donor_trained=summary.get("shared_donor_trained"),
        shared_initial_sha256=summary["shared_initial_sha256"],
        shared_selected_sha256=summary["shared_selected_sha256"],
        selected_checkpoint_sha256=summary["selected_checkpoint_sha256"],
        pretrained_checkpoint_sha256=summary.get("pretrained_checkpoint_sha256"),
        initial_selected=(summary["selected_step"] == 0),
        costs=dict(summary["costs"]), meter=meter,
        final_group_changed_tensors={key:value["changed_tensors"] for key,value in summary["final_group_changes"].items()},
        selected_group_changed_tensors={key:value["changed_tensors"] for key,value in summary["selected_group_changes"].items()},
        gradient_nonzero_steps=summary["gradient_nonzero_steps"])
    profile = directory / "inference_profile_validation.json"
    if profile.exists():
        values = json.loads(profile.read_text())
        if values["selected_checkpoint_sha256"] != summary["selected_checkpoint_sha256"]:
            raise ValueError("Inference profile uses a different checkpoint")
        record["inference_profile"] = values
    return record


def analyze(root, output, *, allow_heldout=False, repeats=2000):
    if not allow_heldout:
        raise PermissionError("Formal analysis needs explicit --allow-heldout after protocol freeze")
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    started = time.process_time()
    by_output, by_id, meter_paths = meter_index(root)
    inputs = {str(path): digest(path) for path in meter_paths}
    jobs, metrics, raw_tables, issues = [], [], {}, []
    for path in sorted((root / "jobs").rglob("summary.json")):
        summary = json.loads(path.read_text())
        if summary.get("schema") != "hcsn-content-v2.summary":
            continue
        directory = path.parent
        meter = by_output.get(str(directory), by_id.get(directory.name))
        record = make_job_record(directory, summary, meter)
        jobs.append(record)
        inputs[str(path)] = digest(path)
        if meter is None or meter.get("exit_code") != 0:
            issues.append(dict(job_id=directory.name, problem="missing or failed whole-process meter"))
        for artifact in ("selection.json", "job.json", "source_identity.json", "inference_profile_validation.json"):
            if (directory / artifact).exists():
                inputs[str(directory / artifact)] = digest(directory / artifact)
        for predictions in sorted(directory.glob("predictions_*.npz")):
            condition = predictions.stem.removeprefix("predictions_")
            with np.load(predictions, allow_pickle=False) as archive:
                raw = {name: archive[name] for name in archive.files}
            scores, details = score_arrays(raw)
            if details["checkpoint_sha"] != summary["selected_checkpoint_sha256"]:
                raise ValueError("Raw predictions use a different selected checkpoint")
            stored = summary["results"][condition]
            if abs(scores["query_accuracy"] - stored["accuracy"]) > 1e-12 or abs(scores["ce"] - stored["ce"]) > 2e-5:
                raise ValueError("Raw logits do not reproduce worker quality metrics")
            if details["input_sha"] != stored["array_sha256"]:
                raise ValueError("Raw predictions use a different input array")
            metrics.append(dict(job_id=directory.name, task=record["task"], family=record["family"],
                mode=record["mode"], seed=record["seed"], budget=record["budget"], condition=condition,
                **scores, inference_cost=stored.get("inference_cost"), prediction_path=str(predictions)))
            raw_tables[(directory.name, condition)] = details
            inputs[str(predictions)] = digest(predictions)
    if not jobs:
        raise ValueError("No completed content workers found")
    expected = root / "meter" / "plan.json"
    if expected.exists():
        plan = json.loads(expected.read_text())
        inputs[str(expected)] = digest(expected)
        planned = [row["id"] for row in plan["jobs"]]
        completed = {row["job_id"] for row in jobs}
        missing = [identifier for identifier in planned if identifier not in completed]
        if missing:
            issues.append(dict(problem="planned jobs without completed summary", jobs=missing))
    by_checkpoint = {row["selected_checkpoint_sha256"]: row for row in jobs}
    for job in jobs:
        donor = by_checkpoint.get(job["pretrained_checkpoint_sha256"])
        job["shared_pretraining_job_id"] = donor["job_id"] if donor else None
        meter, donor_meter = job["meter"], donor["meter"] if donor else None
        job["standalone_pipeline_worker_cpu_seconds"] = ((meter["cpu_total_sec"] + donor_meter["cpu_total_sec"])
            if donor_meter and meter else (meter["cpu_total_sec"] if meter else None))
        if job["mode"] == "frozen_shared" and job["shared_initial_sha256"] != job["shared_selected_sha256"]:
            raise ValueError("Frozen shared checkpoint changed")
    job_lookup = {row["job_id"]: row for row in jobs}
    pair_candidates = defaultdict(dict)
    for row in metrics:
        if row["family"] in ("analytic", "two_gate"):
            key = tuple(row[name] for name in ("task", "mode", "budget", "seed", "condition"))
            if row["family"] in pair_candidates[key]:
                raise ValueError("Duplicate paired candidate")
            pair_candidates[key][row["family"]] = row
    paired, contrast_tables, contrast_rows = [], defaultdict(list), defaultdict(list)
    for key, candidates in sorted(pair_candidates.items()):
        if len(candidates) != 2:
            issues.append(dict(problem="unpaired analytic/ordinary result", key=list(key)))
            continue
        analytic, ordinary = candidates["analytic"], candidates["two_gate"]
        left = raw_tables[(analytic["job_id"], analytic["condition"])]
        right = raw_tables[(ordinary["job_id"], ordinary["condition"])]
        if left["identity"] != right["identity"] or left["input_sha"] != right["input_sha"]:
            raise ValueError("Paired candidates differ in example/target/input identity")
        a_job, o_job = job_lookup[analytic["job_id"]], job_lookup[ordinary["job_id"]]
        if a_job["shared_initial_sha256"] != o_job["shared_initial_sha256"]:
            raise ValueError("Paired candidates do not share content initialization")
        unit = "clusters" if analytic["task"] in ("async_av", "av_binding") else "episodes"
        if left[unit].keys() != right[unit].keys():
            raise ValueError("Paired resampling units differ")
        differences = {item: left[unit][item] - right[unit][item] for item in left[unit]}
        row = dict(task=key[0], mode=key[1], budget=key[2], seed=key[3], condition=key[4],
            analytic_job=analytic["job_id"], ordinary_job=ordinary["job_id"],
            difference_direction="analytic minus two_gate; positive accuracy/exact and negative CE favor analytic",
            differences={name: analytic[name] - ordinary[name] for name in METRICS},
            resampling_unit="actor" if unit == "clusters" else "episode",
            units=len(differences), parameter_difference=a_job["parameters"] - o_job["parameters"],
            shared_checkpoint_identical=True)
        for name in ("body_cpu_seconds", "training_budget_cpu_seconds"):
            row[name + "_difference"] = a_job["costs"][name] - o_job["costs"][name]
        if a_job["meter"] and o_job["meter"]:
            for name in ("cpu_total_sec", "wall_sec", "peak_rss_kib"):
                row["worker_" + name + "_difference"] = a_job["meter"][name] - o_job["meter"][name]
        a_inf, o_inf = analytic["inference_cost"], ordinary["inference_cost"]
        if a_inf and o_inf:
            row["inference_batch_loop_wall_ratio"] = a_inf["prepared_input_batch_loop_wall_seconds"] / o_inf["prepared_input_batch_loop_wall_seconds"]
        if a_job.get("inference_profile") and o_job.get("inference_profile"):
            for name in ("p50_wall_seconds", "p95_wall_seconds"):
                row["single_request_" + name + "_ratio"] = a_job["inference_profile"][name] / o_job["inference_profile"][name]
        paired.append(row)
        contrast = (key[0], key[1], key[2], key[4])
        contrast_tables[contrast].append(differences)
        contrast_rows[contrast].append(row)
    comparisons = []
    for key, tables in sorted(contrast_tables.items()):
        cost_names = sorted({name for row in contrast_rows[key] for name in row
                             if name.endswith("_difference") or name.endswith("_ratio")})
        comparisons.append(dict(task=key[0], mode=key[1], budget=key[2], condition=key[3],
            seeds=[row["seed"] for row in contrast_rows[key]],
            resampling_unit=contrast_rows[key][0]["resampling_unit"],
            paired_costs_and_parameters={name: describe([row[name] for row in contrast_rows[key] if name in row])
                                        for name in cost_names},
            **paired_bootstrap(tables, repeats=repeats)))
    aggregate = defaultdict(list)
    for row in metrics:
        aggregate[tuple(row[name] for name in ("task", "family", "mode", "budget", "condition"))].append(row)
    aggregates = [dict(task=key[0], family=key[1], mode=key[2], budget=key[3], condition=key[4],
        seeds=[row["seed"] for row in rows],
        **{name: describe([row[name] for row in rows]) for name in METRICS})
        for key, rows in sorted(aggregate.items())]
    diagnostics = []
    metric_lookup = {(row["job_id"], row["condition"]): row for row in metrics}
    for row in metrics:
        if "_normal" in row["condition"] and not row["condition"].endswith("_adapter_disabled"):
            continue
        prefix = "_".join(row["condition"].split("_")[:2])
        normal = metric_lookup.get((row["job_id"], prefix + "_normal"))
        if normal:
            diagnostics.append(dict(job_id=row["job_id"], condition=row["condition"],
                differences_from_normal={name: row[name] - normal[name] for name in METRICS},
                interpretation="destructive or counterfactual sensitivity; not a new independently trained arm"))
    completed_cpu = sum(row["meter"].get("cpu_total_sec", 0) for row in jobs if row["meter"])
    total_cpu = sum(receipt.get("cpu_total_sec", 0) for receipt in by_id.values())
    costs = defaultdict(list)
    for job in jobs:
        values = {name: value for name, value in job["costs"].items()
                  if isinstance(value, (float, int)) and not isinstance(value, bool)}
        if job["meter"]:
            values.update({"worker_" + name: job["meter"][name]
                           for name in ("cpu_total_sec", "wall_sec", "peak_rss_kib")})
        if job.get("inference_profile"):
            profile = job["inference_profile"]
            values.update({"single_request_" + name: profile[name] for name in
                ("p50_wall_seconds", "p95_wall_seconds", "samples_per_second", "queries_per_second")})
            values["single_request_mean_wall_seconds"] = float(np.mean(profile["per_batch_wall_seconds"]))
        if job["standalone_pipeline_worker_cpu_seconds"] is not None:
            values["standalone_pipeline_worker_cpu_seconds"] = job["standalone_pipeline_worker_cpu_seconds"]
        values.update({name: job[name] for name in ("parameters", "trainable_parameters", "shared_parameters")})
        costs[tuple(job[name] for name in ("task", "family", "mode", "budget"))].append((job["seed"], values))
    cost_aggregates = []
    for key, records in sorted(costs.items()):
        names = sorted({name for _, values in records for name in values})
        cost_aggregates.append(dict(task=key[0], family=key[1], mode=key[2], budget=key[3],
            seeds=[seed for seed, _ in records],
            statistics={name: describe([values[name] for _, values in records if name in values]) for name in names}))
    output.mkdir(parents=True, exist_ok=False)
    write_new(output / "jobs.json", jobs)
    write_new(output / "metrics.json", metrics)
    write_new(output / "aggregates.json", aggregates)
    write_new(output / "paired_seeds.json", paired)
    write_new(output / "paired_bootstrap.json", comparisons)
    write_new(output / "diagnostics.json", diagnostics)
    write_new(output / "cost_aggregates.json", cost_aggregates)
    manifest = dict(schema="hcsn-content-v2.analysis", complete=not issues, issues=issues,
        jobs=len(jobs), prediction_tables=len(metrics), paired_seed_comparisons=len(paired),
        bootstrap_comparisons=len(comparisons), inputs=inputs,
        analyzer_sha256=digest(__file__), analysis_cpu_seconds=time.process_time() - started,
        study_actual_worker_cpu_seconds_deduplicated=total_cpu,
        completed_quality_worker_cpu_seconds=completed_cpu,
        measured_worker_receipts=len(by_id),
        measured_failed_or_skipped_worker_ids=[key for key, receipt in by_id.items() if receipt.get("exit_code") != 0],
        standalone_cost_policy="One entire shared pretrain worker plus adaptation worker per hypothetical independent pipeline; not additive across arms sharing the donor",
        inclusive_cost_policy="body includes training/preparation/inference/serialization; training includes updates and scheduled validation; process includes body/import/startup. Never sum nested measures.",
        limitations=["Three seeds are descriptive; no multiplicity-corrected superiority claim.",
            "AV uses two previously observed heldout actors; pair repetition does not create new independent actors.",
            "Prepared-feature whole-sequence inference excludes raw decoding/sensor/network and incremental KV-cache operation.",
            "Source binding can exploit temporal metadata; inspect metadata_only, missing-modality and adapter-disabled diagnostics.",
            "Copy prefix counting/ordinal addresses and causal SDPA are common to all families; they do not establish analytic superiority.",
            "Selected step0 is retained honestly; selected_group_changes can be zero despite nonzero training gradients."])
    write_new(output / "manifest.json", manifest)
    return manifest


def self_test():
    raw = dict(logits=np.array([[4., 0.], [0., 4.], [4., 0.], [4., 0.]]),
        labels=np.array([0, 1, 0, 1]), sample_ids=np.array(["a", "a", "b", "b"]),
        position=np.array([2, 3, 2, 3]), group_ids=np.array(["u", "u", "v", "v"]),
        input_array_sha256=np.asarray("input"), checkpoint_sha256=np.asarray("checkpoint"))
    result, _ = score_arrays(raw)
    assert result["query_accuracy"] == .75 and result["episode_exact_recall"] == .5
    tables = [{"a": np.array([.2, -.1, .3]), "b": np.array([.2, -.1, .3])}] * 3
    result = paired_bootstrap(tables, repeats=200)
    for name, value in zip(METRICS, (.2, -.1, .3), strict=True):
        np.testing.assert_allclose(result["metrics"][name]["descriptive_percentile_95"], [value, value])
    print(json.dumps(dict(self_test="pass", raw_query_accuracy=.75, episode_exact_recall=.5)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-heldout", action="store_true")
    parser.add_argument("--repeats", type=int, default=2000)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        if args.root is None or args.output is None:
            parser.error("--root and --output are required")
        result = analyze(args.root, args.output, allow_heldout=args.allow_heldout, repeats=args.repeats)
        print(json.dumps({key: result[key] for key in ("complete", "jobs", "prediction_tables", "paired_seed_comparisons")}))
