"""Independent post-completion analysis of the additional conditional control.

Recomputes saved-logit metrics and actual paired update prefixes. It neither
trains models nor changes selections, original outcomes, or the six-test family.
"""

import argparse
import datetime
import hashlib
import itertools
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy.special import logsumexp
from scipy.stats import t as student_t


PACKAGE = Path(__file__).resolve().parent
ROOT = PACKAGE.parents[1]
TASKS = ("selective_copy", "multimodal_select")
SEEDS = tuple(range(9101, 9109))


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            result.update(chunk)
    return result.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def paired_statistics(differences):
    values = np.asarray(differences, dtype=np.float64)
    if values.shape != (8,) or not np.isfinite(values).all():
        raise ValueError("The registered comparison requires eight finite paired seed differences")
    average = float(values.mean())
    deviation = float(values.std(ddof=1))
    radius = float(student_t.ppf(.975, 7)) * deviation / math.sqrt(8)
    signs = np.asarray(list(itertools.product((-1.0, 1.0), repeat=8)))
    statistics = np.abs(signs @ values / 8)
    tolerance = 32 * np.finfo(float).eps * max(1.0, float(statistics.max()))
    extreme = int(np.count_nonzero(statistics >= abs(average) - tolerance))
    return dict(n=8, mean=average, sample_sd=deviation,
                nominal_paired_t_95=dict(lower=average-radius, upper=average+radius, df=7),
                exact_two_sided_sign_flip=dict(p_value=extreme/256, extreme=extreme,
                                               enumerations=256, adjusted=False),
                direction="free_dual minus conditional_dual; positive favors free_dual",
                inference_scope="Exploratory, training-seed variation on these fixed test sets; nominal nonsimultaneous interval",
                randomization_assumption="Paired differences have sign exchangeability/symmetry under the null",
                included_in_original_six_contrast_holm_family=False)


def validate_predictions(path, expected, classes):
    """Independently validate coordinate coverage and recompute from saved logits."""
    with np.load(path, allow_pickle=False) as archive:
        arrays = {name: np.array(archive[name], copy=True) for name in
                  ("logits", "predictions", "labels", "supervised", "sample_indices", "step_indices")}
    mask = arrays["supervised"]
    if expected.ndim != 2 or mask.dtype != np.bool_ or not np.array_equal(mask, expected != -100):
        raise ValueError("Supervision mask differs from frozen labels")
    samples, steps = arrays["sample_indices"], arrays["step_indices"]
    labels, predicted, logits = arrays["labels"], arrays["predictions"], arrays["logits"]
    count = int(mask.sum())
    if count == 0 or logits.shape != (count, classes) or not np.isfinite(logits).all():
        raise ValueError("Invalid logits shape or values")
    for value in (samples, steps, labels, predicted):
        if value.shape != (count,) or not np.issubdtype(value.dtype, np.integer):
            raise ValueError("Invalid integer prediction metadata")
    if (np.any(samples < 0) or np.any(samples >= expected.shape[0])
            or np.any(steps < 0) or np.any(steps >= expected.shape[1])):
        raise ValueError("Prediction coordinate out of range")
    coordinates = samples * expected.shape[1] + steps
    order = np.argsort(coordinates, kind="stable")
    if not np.array_equal(coordinates[order], np.flatnonzero(mask)):
        raise ValueError("Supervised positions missing or duplicated")
    if (not np.array_equal(labels, expected[samples, steps])
            or not np.array_equal(predicted, logits.argmax(1))
            or np.any(labels < 0) or np.any(labels >= classes)):
        raise ValueError("Labels or argmax predictions disagree")
    correct = predicted == labels
    metrics = dict(accuracy=float(correct.mean()), correct=int(correct.sum()),
                   supervised_positions=count, samples=int(expected.shape[0]),
                   cross_entropy=float((logsumexp(logits.astype(np.float64), axis=1)
                                        - logits[np.arange(count), labels]).mean()))
    return metrics, dict(coordinates=coordinates[order], labels=labels[order],
                          predictions=predicted[order])


def prefixes(path):
    output = []
    with Path(path).open() as source:
        for index, line in enumerate(source, 1):
            row = json.loads(line)
            if row["step"] != index:
                raise ValueError("Nonsequential update log")
            output.append((row["batch_sha256"], row["prefix_sha256"]))
    return output


def inspect_run(directory, task, name, seed, expected, classes, data_hash):
    directory = Path(directory)
    summary = read_json(directory / "summary.json")
    execution = read_json(directory / "EXECUTION.json")
    if summary["status"] != "completed" or execution["returncode"] != 0:
        raise ValueError("A declared comparison run did not complete")
    request, selection = summary["request"], summary["selection"]
    if (request["model"] != name or request["seed"] != seed
            or selection["dataset_sha256"] != data_hash
            or [request[key] for key in ("cpu_seconds", "width", "depth", "batch_size", "max_updates")]
               != [20, 32, 1, 32, 8192]
            or request["learning_rates"] != [.001, .003]):
        raise ValueError("Run identity, data, dimensions or search budget mismatch")
    if selection != read_json(directory / "selection.json"):
        raise ValueError("Durable selection differs from summary")
    if digest(directory / "selected.npz") != selection["selected_checkpoint_sha256"]:
        raise ValueError("Selected checkpoint identity mismatch")
    lock = next(i for i, row in enumerate(summary["access_log"]) if row["event"] == "selection_locked")
    if summary["access_log"][lock]["completed_lr_candidates"] != 2:
        raise ValueError("Selection preceded completion of both LR candidates")
    if any(i <= lock for i, row in enumerate(summary["access_log"]) if row.get("split") in ("test", "ood")):
        raise ValueError("Heldout access preceded the locked selection")
    candidates = summary["candidates"]
    if len(candidates) != 2 or sorted(c["learning_rate"] for c in candidates) != [.001, .003]:
        raise ValueError("Wrong LR candidate set")
    update_prefixes = {}
    for candidate in candidates:
        best = min((cp for cp in candidate["checkpoints"] if cp["primary_eligible"]),
                   key=lambda cp: (cp["validation"]["cross_entropy"], cp["training_cpu_seconds"], cp["step"]))
        if (best != candidate["best"] or candidate["training_cpu_seconds"] < 20
                or candidate["stopping_reason"] != "cpu_budget"):
            raise ValueError("Original candidate selection or full CPU budget violated")
        if not best["crossed_cpu_targets"] and best["step"] != candidate["updates"]:
            raise ValueError("128-only snapshot entered primary selection")
        logged = prefixes(directory / candidate["directory"] / "updates.jsonl")
        if len(logged) != candidate["updates"] or logged[-1][1] != candidate["batch_prefix_sha256"]:
            raise ValueError("Candidate prefix receipt mismatch")
        update_prefixes[candidate["learning_rate"]] = logged
    winner = min(candidates, key=lambda c: (c["best"]["validation"]["cross_entropy"], c["learning_rate"]))
    if (winner["learning_rate"] != selection["selected_learning_rate"]
            or winner["best"]["step"] != selection["selected_step"]
            or winner["best"]["sha256"] != selection["selected_checkpoint_sha256"]):
        raise ValueError("Recorded winner differs from frozen validation-only rule")
    initial_path = directory / candidates[0]["directory"] / "initial.npz"
    if any(digest(directory/c["directory"]/"initial.npz") != c["initial_sha256"] for c in candidates):
        raise ValueError("Initial checkpoint identity mismatch")
    if candidates[0]["initial_sha256"] != candidates[1]["initial_sha256"]:
        raise ValueError("LR candidates did not share initialization")
    with np.load(initial_path, allow_pickle=False) as archive:
        initial = {key: np.array(archive[key], copy=True) for key in archive.files}
    trained = {key: value for key, value in initial.items() if not key.endswith(".fixed_boundary")}
    actual_counts = dict(total=sum(value.size for value in trained.values()),
                         backbone=sum(v.size for k,v in trained.items() if k.startswith("layers.")),
                         frontend=sum(v.size for k,v in trained.items() if k.startswith("frontend.")),
                         readout=sum(v.size for k,v in trained.items() if k.startswith("readout.")))
    if any(actual_counts[key] != summary["counts"][key] for key in actual_counts):
        raise ValueError("Independent active parameter count mismatch")
    metrics, aligned, prediction_hashes = {}, {}, {}
    for split, labels in expected.items():
        path = directory / f"{split}_predictions.npz"
        recomputed, coordinates = validate_predictions(path, labels, classes)
        recorded = summary["holdout"][split]
        for key in ("accuracy", "correct", "supervised_positions", "samples"):
            if recomputed[key] != recorded[key]:
                raise ValueError(f"Recomputed {split}/{key} differs from summary")
        if not math.isclose(recomputed["cross_entropy"], recorded["cross_entropy"], rel_tol=1e-6, abs_tol=1e-5):
            raise ValueError("Recomputed cross entropy differs from summary")
        metrics[split], aligned[split], prediction_hashes[split] = recomputed, coordinates, digest(path)
    child_cpu = execution.get("child_cpu_seconds", execution.get("child_total_cpu_seconds"))
    if child_cpu is None or not child_cpu > 0:
        raise ValueError("Complete process-CPU receipt unavailable")
    result = dict(task=task, model=name, seed=seed, directory=str(directory), metrics=metrics,
                  counts=actual_counts, selected_step=selection["selected_step"],
                  selected_learning_rate=selection["selected_learning_rate"],
                  selected_checkpoint_training_cpu_seconds=winner["best"]["training_cpu_seconds"],
                  candidate_updates=[dict(learning_rate=c["learning_rate"], updates=c["updates"],
                                          training_cpu_seconds=c["training_cpu_seconds"]) for c in candidates],
                  training_cpu_seconds=sum(c["training_cpu_seconds"] for c in candidates),
                  complete_search_child_cpu_seconds=child_cpu,
                  selected_checkpoint_sha256=selection["selected_checkpoint_sha256"],
                  summary_sha256=digest(directory / "summary.json"),
                  execution_sha256=digest(directory / "EXECUTION.json"),
                  prediction_sha256=prediction_hashes,
                  original_selection_preserved=True)
    return result, aligned, update_prefixes, initial


def descriptive(values):
    values = np.asarray(values, dtype=float)
    return dict(n=len(values), mean=float(values.mean()), sample_sd=float(values.std(ddof=1)),
                minimum=float(values.min()), maximum=float(values.max()), total=float(values.sum()))


def analyze(main, additional):
    started = time.process_time()
    main, additional = Path(main), Path(additional)
    main_marker = read_json(main / "COMPLETE.json")
    extra_marker = read_json(additional / "COMPLETE.json")
    if (main_marker["finished_searches"] != 244 or main_marker["scheduled_searches"] != 244
            or main_marker["statuses"] != {"completed":244}
            or any(row["returncode"] != 0 for row in main_marker["results"])
            or extra_marker["status"] != "completed" or extra_marker["completed_jobs"] != 16
            or any(row["returncode"] != 0 for row in extra_marker["receipts"])):
        raise ValueError("Both complete studies are required; no partial or dropped-pair analysis")
    protocol_path = PACKAGE / "CONDITIONAL_PROTOCOL.json"
    protocol = read_json(protocol_path)
    if extra_marker["protocol_sha256"] != digest(protocol_path):
        raise ValueError("Additional protocol identity mismatch")
    for relative, expected in protocol["files_sha256"].items():
        if digest(ROOT / relative) != expected:
            raise ValueError(f"Registered source/data changed: {relative}")
    if tuple(protocol["tasks"]) != TASKS or tuple(protocol["seeds"]) != SEEDS:
        raise ValueError("Comparison task/seed set changed")
    records, pairing, tasks = [], [], {}
    for task in TASKS:
        data = protocol["data"][task]
        data_path = ROOT / data["path"]
        if digest(data_path) != data["sha256"]:
            raise ValueError("Data changed before prediction audit")
        with np.load(data_path, allow_pickle=False) as archive:
            labels = {split: np.array(archive[f"{split}_y"], copy=True) for split in ("test", "ood")
                      if f"{split}_y" in archive.files}
        task_rows = []
        for seed in SEEDS:
            a, pos_a, prefix_a, initial_a = inspect_run(main/"runs"/task/"free_dual"/str(seed),
                                            task, "free_dual", seed, labels, data["output_dim"], data["sha256"])
            b, pos_b, prefix_b, initial_b = inspect_run(additional/"jobs"/f"{task}__conditional_dual__{seed}",
                                            task, "conditional_dual", seed, labels, data["output_dim"], data["sha256"])
            for split in labels:
                for key in ("coordinates", "labels"):
                    if not np.array_equal(pos_a[split][key], pos_b[split][key]):
                        raise ValueError("Task-seed prediction supervision is not paired")
            for key, value in initial_a.items():
                if key not in initial_b or not np.array_equal(value, initial_b[key]):
                    raise ValueError("Common initialized weights differ between actual runs")
            extra_keys = sorted(set(initial_b)-set(initial_a))
            if extra_keys != ["layers.0.raw_boundary_gap", "layers.0.raw_boundary_gap_slope"]:
                raise ValueError("Unexpected conditional parameter additions")
            pair = dict(task=task, seed=seed, supervision_coordinates_and_labels_identical=True,
                        shared_initial_weights_identical=True, extra_parameter_names=extra_keys,
                        extra_active_parameters=b["counts"]["total"]-a["counts"]["total"], prefixes=[])
            for lr in (.001, .003):
                shared = min(len(prefix_a[lr]),len(prefix_b[lr]))
                if prefix_a[lr][:shared] != prefix_b[lr][:shared]:
                    raise ValueError("Actual main/conditional minibatch prefixes differ")
                pair["prefixes"].append(dict(learning_rate=lr, shared_updates=shared,
                                             free_updates=len(prefix_a[lr]), conditional_updates=len(prefix_b[lr]),
                                             all_shared_batch_and_prefix_hashes_equal=True,
                                             last_shared_prefix_sha256=prefix_a[lr][shared-1][1]))
            pairing.append(pair)
            records.extend((a,b))
            task_rows.append(dict(seed=seed, free_accuracy=a["metrics"]["test"]["accuracy"],
                                   conditional_accuracy=b["metrics"]["test"]["accuracy"],
                                   difference=a["metrics"]["test"]["accuracy"]-b["metrics"]["test"]["accuracy"]))
        arms = {}
        for model in ("free_dual", "conditional_dual"):
            subset = [r for r in records if r["task"]==task and r["model"]==model]
            arms[model] = dict(test_accuracy=descriptive([r["metrics"]["test"]["accuracy"] for r in subset]),
                               test_cross_entropy=descriptive([r["metrics"]["test"]["cross_entropy"] for r in subset]),
                               selected_step=descriptive([r["selected_step"] for r in subset]),
                               candidate_updates=descriptive([c["updates"] for r in subset for c in r["candidate_updates"]]),
                               training_cpu_seconds=descriptive([r["training_cpu_seconds"] for r in subset]),
                               complete_search_child_cpu_seconds=descriptive([r["complete_search_child_cpu_seconds"] for r in subset]),
                               counts=subset[0]["counts"])
            if "ood" in labels:
                arms[model]["ood_accuracy"] = descriptive([r["metrics"]["ood"]["accuracy"] for r in subset])
        tasks[task] = dict(arms=arms, seed_pairs=task_rows,
                          mean_accuracy_difference=float(np.mean([r["difference"] for r in task_rows])),
                          supervised_positions_per_seed=int((labels["test"] != -100).sum()))
    seed_pairs = []
    for seed in SEEDS:
        rows = [next(row for row in tasks[task]["seed_pairs"] if row["seed"]==seed) for task in TASKS]
        mean_free = float(np.mean([row["free_accuracy"] for row in rows]))
        mean_conditional = float(np.mean([row["conditional_accuracy"] for row in rows]))
        seed_pairs.append(dict(seed=seed, free_two_task_mean=mean_free,
                               conditional_two_task_mean=mean_conditional,
                               difference=mean_free-mean_conditional))
    costs = {}
    for model in ("free_dual", "conditional_dual"):
        subset = [r for r in records if r["model"]==model]
        costs[model] = dict(searches=16, lr_candidates=32,
                           training_cpu_seconds=sum(r["training_cpu_seconds"] for r in subset),
                           complete_search_child_cpu_seconds=sum(r["complete_search_child_cpu_seconds"] for r in subset),
                           selected_step=descriptive([r["selected_step"] for r in subset]),
                           candidate_updates=descriptive([c["updates"] for r in subset for c in r["candidate_updates"]]))
    report = dict(schema="hcsn-additional-conditional-comparison.v1", status="complete_validated",
                   created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   identity="Additional/exploratory; separate from the original six-contrast Holm family",
                   aggregation="Within each seed average the two task accuracies equally, then pair across eight seeds; do not pool 2048 and 512 supervised positions",
                   paired_test=paired_statistics([r["difference"] for r in seed_pairs]),
                   seed_pairs=seed_pairs, tasks=tasks, costs=costs, records=records, pairing_audit=pairing,
                   validation=dict(valid_task_seed_pairs=16, validated_saved_prediction_archives=sum(len(r["metrics"]) for r in records),
                                   actual_lr_prefix_pairs=32, shared_prefix_updates_range=[min(p["shared_updates"] for r in pairing for p in r["prefixes"]), max(p["shared_updates"] for r in pairing for p in r["prefixes"])],
                                   all_actual_minibatch_prefixes_match=True, all_common_initial_weights_match=True,
                                   original_selections_preserved=True, heldout_metrics_recomputed_from_saved_logits=True,
                                   additional_model_forward_or_training_performed=False),
                   cost_scope="Full subprocess CPU from wait4 includes both full LR searches, imports/setup/validation/checkpoints/heldout; an early selected checkpoint does not reduce charged search cost",
                   original_family_changed=False, new_training_performed=False,
                   analysis_cpu_seconds=time.process_time()-started,
                   source_sha256={"conditional_analysis.py":digest(__file__),
                                  "conditional_analysis_tests.py":digest(PACKAGE/"conditional_analysis_tests.py"),
                                  "conditional_protocol":digest(protocol_path),
                                  "main_protocol":digest(PACKAGE/"PROTOCOL.json"),
                                  "main_complete":digest(main/"COMPLETE.json"),
                                  "conditional_complete":digest(additional/"COMPLETE.json")})
    for relative, expected in protocol["files_sha256"].items():
        if digest(ROOT / relative) != expected:
            raise ValueError("A registered input changed during analysis")
    return report


def markdown(report):
    statistics = report["paired_test"]
    interval = statistics["nominal_paired_t_95"]
    p_value = statistics["exact_two_sided_sign_flip"]["p_value"]
    direction = "conditional_dual" if statistics["mean"] < 0 else "free_dual"
    conclusion = ("The nominal interval includes zero and the sign-flip test does not reject at 0.05. "
                  "This does not establish superiority for either arm or equivalence."
                  if interval["lower"] <= 0 <= interval["upper"] and p_value >= .05 else
                  "This remains an exploratory contrast; no equivalence margin or original-family confirmatory status is asserted.")
    lines = ["# Additional conditional-threshold comparison", "",
             "This report is the separately registered **additional/exploratory** comparison. "
             "It does not change the original six-contrast Holm family, original selections or predictions. "
             "Both studies completed before this analysis; no training or new model inference was performed.", "",
             "## Paired result", "",
             f"The effect is **free_dual minus conditional_dual**. Averaging the two tasks equally within each "
             f"of eight seeds gives **{100*statistics['mean']:+.4f} percentage points**, with nominal paired-t "
             f"95% interval **[{100*interval['lower']:+.4f}, {100*interval['upper']:+.4f}] pp** (7 df). "
             f"The two-sided exact sign-flip test enumerates all 256 assignments: **p={p_value:.8f}**, unadjusted and exploratory.", "",
             f"The observed mean favors **{direction}** under the declared CPU search budget. "
             f"{conclusion} "
             "The interval describes training-seed variation on these fixed test sets, not uncertainty over "
             "new datasets or deployment populations. Sign-flip inference assumes sign exchangeability/symmetry "
             "of paired differences under the null; the t interval is nominal and not simultaneous.", "",
             "| Task | Free accuracy | Conditional accuracy | Free minus conditional | Supervised positions per seed |",
             "|---|---:|---:|---:|---:|"]
    for task in TASKS:
        row=report["tasks"][task]
        lines.append(f"| {task} | {100*row['arms']['free_dual']['test_accuracy']['mean']:.4f}% | "
                     f"{100*row['arms']['conditional_dual']['test_accuracy']['mean']:.4f}% | "
                     f"{100*row['mean_accuracy_difference']:+.4f} pp | {row['supervised_positions_per_seed']} |")
    lines += ["", "The two tasks receive equal weight. The selective-copy task's four supervised tokens "
              "per episode are not pooled with the other task's single query token.", "",
              "| Seed | Free two-task mean | Conditional two-task mean | Paired difference |",
              "|---:|---:|---:|---:|"]
    for row in report["seed_pairs"]:
        lines.append(f"| {row['seed']} | {100*row['free_two_task_mean']:.4f}% | "
                     f"{100*row['conditional_two_task_mean']:.4f}% | {100*row['difference']:+.4f} pp |")
    lines += ["", "## Selection, work and active parameters", "",
              "Both arms use width32/depth1, batch32, LR .001/.003, and 20 training process-CPU seconds "
              "per candidate. Validation-only selection uses the common 5/10/20 CPU checkpoints; "
              "128-only snapshots do not enter the primary selection. Both LR candidates finish before "
              "heldout evaluation. All common initialized weights are byte-for-byte numerically equal.", "",
              "| Task / arm | Backbone / total parameters | Mean selected step (range) | Mean complete search CPU | Mean training CPU |",
              "|---|---:|---:|---:|---:|"]
    for task in TASKS:
        for name in ("free_dual","conditional_dual"):
            row=report["tasks"][task]["arms"][name]
            step=row["selected_step"]
            lines.append(f"| {task} / {name} | {row['counts']['backbone']} / {row['counts']['total']} | "
                         f"{step['mean']:.2f} ({step['minimum']:.0f}–{step['maximum']:.0f}) | "
                         f"{row['complete_search_child_cpu_seconds']['mean']:.4f} s | {row['training_cpu_seconds']['mean']:.4f} s |")
    lines += ["", "The conditional arm adds 64 active parameters (0.7273% of the 8800-parameter free backbone): "
              "a per-neuron gap and slope. Its frontend/readout are unchanged; no parameter padding is used.", "",
              "| Across 16 searches | Actual training CPU | Complete child process CPU | Candidate update range |",
              "|---|---:|---:|---:|"]
    for name in ("free_dual","conditional_dual"):
        row=report["costs"][name]
        lines.append(f"| {name} | {row['training_cpu_seconds']:.5f} s | {row['complete_search_child_cpu_seconds']:.5f} s | "
                     f"{row['candidate_updates']['minimum']:.0f}–{row['candidate_updates']['maximum']:.0f} |")
    lines += ["", "Complete CPU includes interpreter/imports, setup, both full LR searches, validation, "
              "checkpoint IO and heldout evaluation. Selecting an earlier checkpoint does not remove "
              "the rest of its search cost. These are reference single-thread CPU measurements, not energy "
              "measurements or optimized GPU/neuromorphic performance.", "",
              "The comparison uses equal process-CPU budgets, not equal update counts. Consequently, an "
              "accuracy difference can reflect both threshold parametrization and training throughput. "
              "This report does not claim a matched-step advantage; missing 128-update snapshots remain "
              "missing, with no extra training or extrapolation. Runs used different scheduling windows, "
              "so CPU timing is descriptive for this shared host.", "",
              "## Prediction and pairing audit", "",
              f"All **{report['validation']['valid_task_seed_pairs']} task-seed pairs** passed independent "
              "checks against the frozen data labels. Saved logits were checked for finite values; "
              "argmax predictions, labels, supervision masks and row coordinates cover every supervised "
              "position exactly once. Accuracy and cross entropy were recomputed and matched the original summaries. "
              "Prediction archive hashes, selected checkpoint hashes and run receipts are retained in COMPARISON.json.", "",
              f"All **32 actual LR minibatch-prefix pairs** match through their common update prefix "
              f"({report['validation']['shared_prefix_updates_range'][0]}–{report['validation']['shared_prefix_updates_range'][1]} updates). "
              "This compares the original main update logs with the additional logs, rather than relying "
              "only on nominal seed equality. Common initialized state-dict arrays also match exactly.", ""]
    row=report["tasks"]["selective_copy"]["arms"]
    lines += ["## Separate OOD description", "",
              f"For selective-copy OOD length64, mean accuracy is "
              f"{100*row['free_dual']['ood_accuracy']['mean']:.4f}% for free and "
              f"{100*row['conditional_dual']['ood_accuracy']['mean']:.4f}% for conditional. "
              "This is descriptive, is not mixed into the primary two-task pairing, and has no new significance claim.", "",
              "## What this addresses", "",
              "The original direct_dual has a learned but input-static per-neuron threshold, whereas "
              "free_dual's boundary changes with input-dependent mu. A free-versus-static-direct result "
              "therefore mixes the boundary formula with the ability to adapt the threshold to the input. "
              "It cannot by itself establish a special benefit of the endogenous free-boundary mechanism.", "",
              "The added control uses b_t=K+softplus(raw_gap+slope*mu_t), with slope initialized to zero. "
              "It reuses the exact same mu mapping, content network, own-policy J/G and mean-state "
              "reset/refractory update. It addresses that conditionality gap while remaining a restricted "
              "softplus-affine function, not a universal learned threshold network. The two arms also "
              "couple their learned dynamics parameters to the threshold differently.", "",
              "Both arms retain the known frozen-local mean-closure limitation; this comparison does not "
              "certify exact stochastic propagation or global optimality. It is evidence about two small "
              "tasks and a declared search budget, not a foundation-model, Transformer or SNN superiority "
              "claim. No primary Holm conclusion is rewritten by this additional result.", "",
              "## Reproduction and identities", "",
              "Run `python -m experiments.hcsn_free_boundary_v1.conditional_analysis` from the repository "
              "with the supplied scientific Python dependencies. The command refuses to replace existing "
              "COMPARISON.json or REPORT.md; use a separate output directory for a repeat analysis. "
              "It reads existing evidence and performs no training or model forward pass.", "",
              "```json", json.dumps(report["source_sha256"], indent=2, sort_keys=True), "```", ""]
    return "\n".join(lines)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main", type=Path, default=PACKAGE/"results/study001")
    parser.add_argument("--additional", type=Path, default=PACKAGE/"results/conditional001")
    parser.add_argument("--output", type=Path)
    args=parser.parse_args()
    output=args.output or args.additional
    output.mkdir(parents=True,exist_ok=True)
    if (output/"COMPARISON.json").exists() or (output/"REPORT.md").exists():
        raise FileExistsError("Preserve previous comparison evidence; use a new output directory")
    report=analyze(args.main,args.additional)
    (output/"COMPARISON.json").write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+"\n")
    (output/"REPORT.md").write_text(markdown(report))
    print(json.dumps(dict(status=report["status"], paired_test=report["paired_test"],
                         costs=report["costs"], validation=report["validation"]),indent=2))


if __name__=="__main__":
    main()
