"""Registered seed-paired analysis; invalid or missing runs never disappear."""

import hashlib
import itertools
import json
from pathlib import Path
import time

import numpy as np
from scipy.stats import t as student_t

from . import data
from .study import metrics, read, verify, write


def paired(values):
    values = np.asarray(values, np.float64)
    count = len(values)
    mean = float(values.mean())
    sd = float(values.std(ddof=1)) if count > 1 else 0.0
    interval = float(student_t.ppf(.975, count - 1)) * sd / count ** .5 if count > 1 else None
    permutations = np.array(list(itertools.product((-1.0, 1.0), repeat=count))) @ values / count
    return dict(n=count, differences=values.tolist(), mean=mean, sample_sd=sd,
        ci95=None if interval is None else [mean - interval, mean + interval],
        one_sided_sign_flip_p=float(np.mean(permutations >= mean - 1e-14)),
        two_sided_sign_flip_p=float(np.mean(np.abs(permutations) >= abs(mean) - 1e-14)),
        uncertainty_unit="paired model seed, conditional on fixed dataset split")


def holm(rows):
    order = sorted(range(len(rows)), key=lambda index: rows[index]["one_sided_sign_flip_p"])
    maximum = 0.0
    for rank, index in enumerate(order):
        maximum = max(maximum, min(1.0, (len(rows) - rank) * rows[index]["one_sided_sign_flip_p"]))
        rows[index]["holm_one_sided_p"] = maximum


def numpy_state_hash(path):
    digest = hashlib.sha256()
    with np.load(path, allow_pickle=False) as archive:
        for key in sorted(archive.files):
            array = archive[key]
            if not np.isfinite(array).all():
                raise FloatingPointError("Nonfinite checkpoint array")
            digest.update(json.dumps([key, str(array.dtype), list(array.shape)]).encode())
            digest.update(array.tobytes())
    return digest.hexdigest()


def analyze(output):
    output = Path(output).resolve()
    tick, cpu = time.perf_counter(), time.process_time()
    protocol = verify(output)
    design = protocol["design"]
    lock = read(output / "SELECTION_LOCK.json")
    rows, errors, checks, ledgers, whole_cpu = {}, [], [], {}, {}
    expected_labels = {}

    def check(name, passed, detail=None):
        record = dict(name=name, passed=bool(passed), detail=detail)
        checks.append(record)
        if not passed:
            errors.append(record)

    for stage in ("development", "fixed", "equal_cpu"):
        jobs = read(output / ("jobs_" + stage + ".json"))
        ledger_path = output / ("RUN_" + stage + ".json")
        ledger = read(ledger_path) if ledger_path.exists() else {}
        ledgers[stage] = {key: value for key, value in ledger.items() if key != "jobs"}
        for row in ledger.get("jobs", []):
            whole_cpu[stage, row["id"]] = row["child_cpu_seconds"]
        check(stage + ": complete queue", ledger.get("complete") is True and ledger.get("failed") == 0)
        check(stage + ": exact job coverage", sorted(row["id"] for row in ledger.get("jobs", [])) == sorted(job["id"] for job in jobs))
        for job in jobs:
            directory = output / stage / job["id"]
            name = stage + "/" + job["id"]
            if not (directory / "RESULT.json").exists():
                check(name + ": result exists", False,
                      read(directory / "FAILURE.json") if (directory / "FAILURE.json").exists() else "missing")
                continue
            result = read(directory / "RESULT.json")
            rows[stage, job["task"], job["arm"], job["seed"], job["learning_rate"]] = result
            check(name + ": job matches", result["job"] == job and result["status"] == "complete")
            check(name + ": protocol matches", result["protocol_sha256"] == data.sha256(output / "PROTOCOL.json"))
            selected = read(directory / "selection.json")
            state_path = directory / "selected_state.npz"
            check(name + ": selected tensor bytes", data.sha256(state_path) == selected["state_sha256"]
                  and numpy_state_hash(state_path) == selected["tensor_hash"])
            best = min(result["validations"], key=lambda item: (item["cross_entropy"], item["step"]))
            check(name + ": validation selection", selected["step"] == best["step"]
                  and selected["cross_entropy"] == best["cross_entropy"])
            expected_splits = ["dev_val" if stage == "development" else "val"]
            evaluations = [(expected_splits[0], row) for row in result["validations"]]
            evaluations += list(result["evaluation"].items())
            for split, item in evaluations:
                label_key = job["task"], split
                if label_key not in expected_labels:
                    with np.load(output / "data" / protocol["data"][job["task"]][split]["file"], allow_pickle=False) as raw:
                        y = raw["y"]
                        expected_labels[label_key] = y[y >= 0]
                prediction_path = directory / item["file"]
                check(name + ": " + item["file"] + " bytes", data.sha256(prediction_path) == item["sha256"])
                with np.load(prediction_path, allow_pickle=False) as predictions:
                    check(name + ": " + item["file"] + " exact labels",
                          np.array_equal(predictions["labels"], expected_labels[label_key]))
                    recomputed = metrics(predictions["logits"], predictions["labels"])
                    check(name + ": " + item["file"] + " recomputed metrics",
                          all(abs(recomputed[key] - item[key]) <= 2e-12 for key in recomputed))
            trajectory = read(directory / "trajectory.json")
            check(name + ": every update retained", len(trajectory) == result["updates"]
                  and [row["step"] for row in trajectory] == list(range(1, result["updates"] + 1)))
            check(name + ": training clock matches", trajectory[-1]["training_cpu_seconds"] == result["training_cpu_seconds"])
            if stage != "equal_cpu":
                check(name + ": update budget", result["updates"] == job["updates"])
            else:
                check(name + ": CPU budget", result["training_cpu_seconds"] >= design["equal_cpu_seconds"]
                      and (len(trajectory) == 1 or trajectory[-2]["training_cpu_seconds"] < design["equal_cpu_seconds"]))
            if stage != "development":
                chosen = lock["choices"][job["task"]][job["arm"]]
                check(name + ": locked development LR", job["learning_rate"] == chosen["learning_rate"])
                access = [json.loads(line) for line in (directory / "access.jsonl").read_text().splitlines()]
                check(name + ": heldout access after selection", all(
                    row["utc"] >= selected["locked_utc"] for row in access if row["split"] in ("test", "ood")))
            if job["arm"].startswith("freeze_"):
                group = job["arm"].removeprefix("freeze_")
                check(name + ": frozen parameters never update", result["final_update_groups"][group]["nonzero"] == 0
                    and all(row["gradient_groups"][group]["nonzero"] == 0 for row in trajectory))
                with np.load(directory / "frozen_initial.npz", allow_pickle=False) as initial, np.load(state_path, allow_pickle=False) as final:
                    check(name + ": frozen selected bytes equal initial", all(np.array_equal(initial[key], final[key]) for key in initial.files))
    check("selection lock protocol identity", lock["protocol_sha256"] == data.sha256(output / "PROTOCOL.json"))
    for task in design["tasks"]:
        recomputed_choices = {}
        for arm in design["arms"]:
            candidates = [value for key, value in rows.items() if key[:3] == ("development", task, arm)]
            check(f"{task}/{arm}: all registered LR candidates", len(candidates) == len(design["learning_rates"]))
            if not candidates:
                continue
            best = min(candidates, key=lambda value: (value["selected"]["cross_entropy"],
                       value["selected"]["step"], value["job"]["learning_rate"]))
            choice = lock["choices"][task][arm]
            path = output / "development" / best["job"]["id"] / "RESULT.json"
            check(f"{task}/{arm}: independent LR argmin and provenance", choice == dict(
                learning_rate=best["job"]["learning_rate"],
                development_cross_entropy=best["selected"]["cross_entropy"],
                result_file=str(path.relative_to(output)), result_sha256=data.sha256(path)))
            recomputed_choices[arm] = best["selected"]["cross_entropy"]
        physical = [arm for arm in recomputed_choices if arm.startswith(("value_", "fixed_", "learned_"))]
        if physical:
            best_arm = min(physical, key=lambda arm: (recomputed_choices[arm], arm))
            check(task + ": independently selected equal-CPU physical arm", lock["equal_cpu_arms"][task] ==
                  [best_arm, "two_gates", "transformer", "lif_snn"])
    for stage in ("development", "fixed", "equal_cpu"):
        expected = []
        for task in design["tasks"]:
            arms = lock["equal_cpu_arms"][task] if stage == "equal_cpu" else design["arms"]
            for arm in arms:
                seeds = [design["development_seed"]] if stage == "development" else design["formal_seeds"]
                lrs = design["learning_rates"] if stage == "development" else [lock["choices"][task][arm]["learning_rate"]]
                expected += [(task, arm, seed, lr) for seed in seeds for lr in lrs]
        actual = [(job["task"], job["arm"], job["seed"], job["learning_rate"])
                  for job in read(output / ("jobs_" + stage + ".json"))]
        check(stage + ": full design matrix independently reconstructed", sorted(expected) == sorted(actual))
    fixed = [result for key, result in rows.items() if key[0] == "fixed"]
    for task in design["tasks"]:
        for seed in design["formal_seeds"]:
            selected = [row for row in fixed if row["job"]["task"] == task and row["job"]["seed"] == seed]
            check(f"paired {task} {seed}: same initial frontend/readout", len({row["common_initial_hash"] for row in selected}) == 1)
            check(f"paired {task} {seed}: same minibatch stream", len({row["batch_stream_sha256"] for row in selected}) == 1)
    backbone_counts = [row["counts"]["backbone"] for row in fixed if not row["job"]["arm"].startswith("freeze_")]
    if backbone_counts:
        gap = (max(backbone_counts) - min(backbone_counts)) / max(backbone_counts)
        check("active resident backbone parameter spread", gap <= .03, dict(relative_gap=gap, minimum=min(backbone_counts), maximum=max(backbone_counts)))

    def result(stage, task, arm, seed):
        lr = lock["choices"][task][arm]["learning_rate"]
        return rows[stage, task, arm, seed, lr]

    def difference(arm, metric="accuracy", split="test"):
        return [float(np.mean([result("fixed", task, "value_jg", seed)["evaluation"][split][metric]
                              - result("fixed", task, arm, seed)["evaluation"][split][metric]
                              for task in design["tasks"]])) for seed in design["formal_seeds"]]

    families = {"freeze": ["freeze_content", "freeze_dynamics", "freeze_boundary", "freeze_reset", "freeze_refractory"],
                "boundary": ["fixed_jg", "learned_jg"],
                "channel": ["value_margin", "value_j", "value_g", "value_fh", "value_ordinary"]}
    mechanism, external, summaries = {}, [], []
    complete = not errors and len(fixed) == len(read(output / "jobs_fixed.json"))
    if complete:
        for family, controls in families.items():
            contrasts = []
            for control in controls:
                contrast = dict(control=control, **paired(difference(control)),
                    mean_brier_difference=float(np.mean(difference(control, "brier"))),
                    mean_ece_difference=float(np.mean(difference(control, "ece"))))
                contrasts.append(contrast)
            holm(contrasts)
            for row in contrasts:
                row["positive_gate"] = bool(row["mean"] >= .005 and row["ci95"][0] > 0
                    and row["holm_one_sided_p"] < .05 and row["mean_brier_difference"] <= .01
                    and row["mean_ece_difference"] <= .02)
            mechanism[family] = contrasts
        interactions = []
        for boundary in ("fixed", "learned"):
            differences = []
            for seed in design["formal_seeds"]:
                differences.append(float(np.mean([
                    result("fixed", task, "value_jg", seed)["evaluation"]["test"]["accuracy"]
                    - result("fixed", task, "value_ordinary", seed)["evaluation"]["test"]["accuracy"]
                    - result("fixed", task, boundary + "_jg", seed)["evaluation"]["test"]["accuracy"]
                    + result("fixed", task, boundary + "_ordinary", seed)["evaluation"]["test"]["accuracy"]
                    for task in design["tasks"]])))
            interactions.append(dict(boundary_control=boundary, **paired(differences)))
        holm(interactions)
        for row in interactions:
            row["positive_gate"] = bool(row["mean"] >= .005 and row["ci95"][0] > 0 and row["holm_one_sided_p"] < .05)
        mechanism["boundary_channel_interaction"] = interactions
        for task in design["tasks"]:
            primary = lock["equal_cpu_arms"][task][0]
            for split in ("test", "ood"):
                for control in lock["equal_cpu_arms"][task][1:]:
                    a = [result("equal_cpu", task, primary, seed) for seed in design["formal_seeds"]]
                    b = [result("equal_cpu", task, control, seed) for seed in design["formal_seeds"]]
                    row = dict(task=task, split=split, selected_hcsn=primary, control=control,
                        **paired([x["evaluation"][split]["accuracy"] - y["evaluation"][split]["accuracy"] for x, y in zip(a, b, strict=True)]))
                    for metric in ("brier", "ece"):
                        row["mean_" + metric + "_difference"] = float(np.mean([
                            x["evaluation"][split][metric] - y["evaluation"][split][metric] for x, y in zip(a, b, strict=True)]))
                    row["whole_process_cpu_ratio_hcsn_over_control"] = float(np.exp(np.mean([
                        np.log(whole_cpu["equal_cpu", x["job"]["id"]] / whole_cpu["equal_cpu", y["job"]["id"]])
                        for x, y in zip(a, b, strict=True)])))
                    row["inference_wall_ratio_hcsn_over_control"] = float(np.exp(np.mean([
                        np.log(x["inference"]["median_wall_seconds"] / y["inference"]["median_wall_seconds"]) for x, y in zip(a, b, strict=True)])))
                    external.append(row)
        holm(external)
        for row in external:
            row["positive_gate"] = bool(row["mean"] >= .02 and row["ci95"][0] > 0
                and row["holm_one_sided_p"] < .05 and row["mean_brier_difference"] <= .01 and row["mean_ece_difference"] <= .02)
        for stage in ("fixed", "equal_cpu"):
            for task in design["tasks"]:
                arms = design["arms"] if stage == "fixed" else lock["equal_cpu_arms"][task]
                for arm in arms:
                    values = [result(stage, task, arm, seed) for seed in design["formal_seeds"]]
                    summaries.append(dict(stage=stage, task=task, arm=arm,
                        learning_rate=lock["choices"][task][arm]["learning_rate"],
                        mean_updates=float(np.mean([row["updates"] for row in values])),
                        mean_training_cpu_seconds=float(np.mean([row["training_cpu_seconds"] for row in values])),
                        mean_whole_process_cpu_seconds=float(np.mean([whole_cpu[stage, row["job"]["id"]] for row in values])),
                        evaluation={split: {metric: dict(mean=float(np.mean([row["evaluation"][split][metric] for row in values])),
                            sample_sd=float(np.std([row["evaluation"][split][metric] for row in values], ddof=1)))
                            for metric in ("accuracy", "cross_entropy", "brier", "ece")} for split in ("test", "ood")}))
    analysis = dict(schema="hcsn-blocker-content-analysis.v1", complete=complete, valid_results=len(rows),
        protocol_sha256=data.sha256(output / "PROTOCOL.json"), selection_lock_sha256=data.sha256(output / "SELECTION_LOCK.json"),
        checks=checks, errors=errors, selected_equal_cpu_arms=lock["equal_cpu_arms"], summaries=summaries,
        mechanism_families=mechanism, equal_cpu_external=external,
        mechanism_positive_count=sum(row["positive_gate"] for values in mechanism.values() for row in values),
        external_positive_count=sum(row["positive_gate"] for row in external),
        external_contrasts=len(external), costs=ledgers,
        costs_nonoverlap=dict(child_cpu_seconds=sum(row.get("child_cpu_seconds", 0) for row in ledgers.values()),
            coordinator_cpu_seconds=sum(row.get("coordinator_cpu_seconds", 0) for row in ledgers.values()),
            worker_training_cpu_seconds=sum(row["training_cpu_seconds"] for row in rows.values()),
            warning="training clocks are nested inside child CPU; do not add them"),
        analysis_cpu_seconds=time.process_time() - cpu, analysis_wall_seconds=time.perf_counter() - tick,
        limitations=design["limitations"] + ["No result here closes task-optimal control or GPU/energy/foundation-model evidence"])
    write(output / "ANALYSIS.json", analysis)
    return dict(complete=complete, valid_results=len(rows), errors=len(errors),
        mechanism_positive_count=analysis["mechanism_positive_count"],
        external_positive_count=analysis["external_positive_count"], external_contrasts=len(external))
