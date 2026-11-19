"""Human report and independent secondary-prediction/cost reconciliation.

Adds evidence after completion; does not modify primary or secondary analyses,
select checkpoints, train models, or run additional neural inference.
"""

from collections import Counter
import csv
import json
from pathlib import Path
import statistics
import time

from .analysis import (PACKAGE, REPOSITORY, _metrics_match, _write_csv,
                       _write_json, digest, expected_jobs, inspect_dataset,
                       read_json, require_complete, validate_prediction_archive)
from .analysis_secondary import choose_128_candidate


def table(headers, rows):
    return "\n".join(["| " + " | ".join(map(str, headers)) + " |",
                       "| " + " | ".join("---" for _ in headers) + " |"]
                      + ["| " + " | ".join(map(str, row)) + " |" for row in rows])


def percent(value):
    return f"{100 * float(value):.2f}"


def mean_sd(mean, sd):
    return f"{percent(mean)} ± {percent(sd)}"


def run(study=PACKAGE / "results/study001"):
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    study = Path(study)
    completion = require_complete(study)
    output = study / "analysis001"
    for name in ("REPORT.md", "SUPPLEMENTARY_AUDIT.json", "MODEL_COMPUTE.csv", "SECONDARY_COVERAGE.csv"):
        if (output / name).exists():
            raise FileExistsError(f"Preserve existing evidence: {name}")
    primary = read_json(output / "ANALYSIS.json")
    trainability = read_json(output / "TRAINABILITY.json")
    strata = read_json(output / "DATA_STRATA.json")
    protocol = read_json(PACKAGE / "PROTOCOL.json")
    identity = read_json(study / "IDENTITY.json")
    secondary = read_json(study / "secondary128/SECONDARY128.json")
    execution_primary = read_json(study / "analysis001_EXECUTION.json")
    execution_secondary = read_json(study / "secondary128_EXECUTION.json")
    if not primary["global_integrity_gate"] or primary["valid_searches"] != len(expected_jobs(protocol)):
        raise ValueError("Primary integrity gate/complete matrix is not satisfied")
    protected = {path: digest(REPOSITORY / path) for path in identity["files"]}
    if protected != identity["files"]:
        raise ValueError("Frozen source/data changed before human reporting")
    runs = {(r["task"], r["model"], r["seed"]): r for r in primary["runs"]}
    primary_receipt_mismatches = []
    for row in completion["results"]:
        key = (row["task"], row["model"], row["seed"])
        if row != runs[key]["execution_receipt"]:
            primary_receipt_mismatches.append(key)
    if primary_receipt_mismatches:
        raise ValueError("COMPLETE result rows differ from persisted execution receipts")
    for key, row in runs.items():
        folder = study / "runs" / key[0] / key[1] / str(key[2])
        if digest(folder / "selected.npz") != row["selection"]["selected_checkpoint_sha256"]:
            raise ValueError("Primary selected checkpoint changed after secondary inference")
    datasets = {task: inspect_dataset(PACKAGE / "data/study001", task) for task in protocol["core"]["tasks"]}
    secondary_checks, missing = [], []
    secondary_lookup = {}
    for row in secondary["records"]:
        key = (row["task"], row["model"], row["seed"])
        if key in secondary_lookup:
            raise ValueError("Duplicated secondary run")
        secondary_lookup[key] = row
        primary_folder = study / "runs" / key[0] / key[1] / str(key[2])
        original = read_json(primary_folder / "summary.json")
        expected = choose_128_candidate(original["candidates"], protocol["optimization"]["learning_rates"])
        if row.get("eligibility") != expected:
            raise ValueError("Secondary eligibility/validation-only LR choice changed")
        if row["status"] == "incomplete":
            if expected["status"] != "incomplete":
                raise ValueError("Eligible secondary run was omitted")
            missing.append(dict(task=key[0], model=key[1], seed=key[2],
                                missing_learning_rates=[r["learning_rate"] for r in expected["missing"]],
                                actual_primary_updates_per_lr=runs[key]["costs"]["updates_per_lr"]))
            continue
        if row["status"] != "evaluated" or expected["status"] != "eligible":
            raise ValueError("Unexpected secondary invalid/eligibility status")
        folder = study / "secondary128/runs" / key[0] / key[1] / str(key[2])
        if read_json(folder / "SELECTION.json") != row["selection"]:
            raise ValueError("Secondary durable selection differs from summary")
        selected = expected["selected"]
        checkpoint = primary_folder / selected["directory"] / selected["checkpoint"]["weights"]
        if digest(checkpoint) != row["selection"]["selected_sha256"]:
            raise ValueError("Secondary selected 128 checkpoint hash changed")
        checks = {}
        for split, labels in datasets[key[0]]["labels"].items():
            if split not in ("test", "ood"):
                continue
            archive = folder / f"{split}_predictions.npz"
            metrics, _ = validate_prediction_archive(archive, labels, datasets[key[0]]["manifest"]["output_dim"])
            _metrics_match(metrics, row["metrics"][split])
            checks[split] = dict(metrics, prediction_sha256=digest(archive))
        secondary_checks.append(dict(task=key[0], model=key[1], seed=key[2], metrics=checks))
    if set(secondary_lookup) != set(runs):
        raise ValueError("Secondary matrix differs from declared primary searches")
    if len(secondary_checks) != secondary["available_runs"]:
        raise ValueError("Secondary availability count mismatch")
    models = protocol["core"]["models"] + [m for m in protocol["mechanism"]["models"] if m not in protocol["core"]["models"]]
    coverage = []
    for model in models:
        for task in protocol["core"]["tasks"]:
            subset = [r for key, r in secondary_lookup.items() if key[0] == task and key[1] == model]
            if subset:
                available = sum(r["status"] == "evaluated" for r in subset)
                coverage.append(dict(task=task, model=model, expected=len(subset), available=available,
                                      missing=len(subset) - available,
                                      missing_seeds=[r["seed"] for r in subset if r["status"] != "evaluated"]))
    complete_panels = []
    for task in protocol["core"]["tasks"]:
        for seed in protocol["core"]["seeds"]:
            if all(secondary_lookup[(task, model, seed)]["status"] == "evaluated" for model in protocol["core"]["models"]):
                complete_panels.append(dict(task=task, seed=seed))
    if len(complete_panels) != sum(r["all_core_arms_available"] for r in secondary["core_paired_coverage"]):
        raise ValueError("Secondary complete-panel count mismatch")
    complete_tasks = [task for task in protocol["core"]["tasks"] if all(
        dict(task=task, seed=seed) in complete_panels for seed in protocol["core"]["seeds"])]
    compute = []
    for cohort in ("core", "mechanism"):
        section = protocol[cohort]
        for model in section["models"]:
            records = [runs[(task, model, seed)] for task in section["tasks"] for seed in section["seeds"]]
            updates = [number for r in records for number in r["costs"]["updates_per_lr"].values()]
            cpus = [r["costs"]["complete_child_cpu_seconds"] for r in records]
            compute.append(dict(cohort=cohort, model=model, searches=len(records), lr_candidates=len(updates),
                                updates_per_lr_median=statistics.median(updates),
                                updates_per_lr_min=min(updates), updates_per_lr_max=max(updates),
                                selected_step_median=statistics.median(r["selection"]["selected_step"] for r in records),
                                complete_search_cpu_seconds_median=statistics.median(cpus),
                                complete_search_cpu_seconds_sum=sum(cpus),
                                training_update_cpu_seconds_sum=sum(r["costs"]["training_cpu_seconds"] for r in records),
                                whole_child_peak_rss_mib_median=statistics.median(r["costs"]["whole_process_peak_rss_bytes"] / 2**20 for r in records)))
    aggregate_cpu = completion["all_child_process_cpu_seconds"]
    receipt_cpu = sum(r["execution_receipt"]["child_cpu_seconds"] for r in runs.values())
    reconciliation = dict(aggregate_rusage_children_cpu_seconds=aggregate_cpu,
                           sum_individual_wait4_cpu_seconds=receipt_cpu,
                           difference_seconds=aggregate_cpu - receipt_cpu,
                           complete_rows_exactly_match_per_run_execution=True,
                           interpretation="two preserved measurement routes; tiny difference is consistent with independently accumulated microsecond reporting, not corrected or redistributed")
    with (output / "CORE_TABLE.csv").open() as stream:
        core_rows = list(csv.DictReader(stream))
    core = {(r["task"], r["model"]): r for r in core_rows}
    _write_csv(output / "MODEL_COMPUTE.csv", compute)
    _write_csv(output / "SECONDARY_COVERAGE.csv", coverage)
    audit = dict(schema="hcsn-post-analysis-audit.v1", status="passed",
                 all_frozen_files_rechecked=len(protected), primary_selected_hashes_rechecked=len(runs),
                 secondary_evaluated_predictions_verified=len(secondary_checks), secondary_missing=len(missing),
                 secondary_invalid=0, secondary_prediction_checks=secondary_checks,
                 secondary_missing_detail=missing, secondary_coverage=coverage,
                 secondary_complete_task_seed_panels=complete_panels,
                 secondary_complete_three_seed_tasks=complete_tasks,
                 cost_reconciliation=reconciliation, compute=compute,
                 source_sha256={"analysis_report.py": digest(__file__)},
                 input_sha256={str(path.relative_to(study)): digest(path) for path in (
                     output / "ANALYSIS.json", output / "TRAINABILITY.json", output / "DATA_STRATA.json",
                     output / "CORE_TABLE.csv", output / "MECHANISM_TABLE.csv", study / "COMPLETE.json",
                     study / "secondary128/SECONDARY128.json", study / "analysis001_EXECUTION.json",
                     study / "secondary128_EXECUTION.json")},
                 audit_cpu_seconds_before_report=time.process_time() - start_cpu,
                 audit_wall_seconds_before_report=time.perf_counter() - start_wall,
                 additional_inference=False, additional_training=False)
    _write_json(output / "SUPPLEMENTARY_AUDIT.json", audit)
    sections = []
    sections.append("""# Frozen study001: completed analysis and exactly-128 secondary

## Finding

The implementation runs and jointly trains its content, dynamics, boundary,
reset and refractory parameter groups, but the registered accuracy claims fail
in this small CPU-budget study. **All 244 searches are valid; zero of six
positive mechanism contrasts are accepted; zero of six 2-percentage-point
content screens pass.** These are genuine measured negative results, not
missing-run substitutions.

The only Holm-significant two-sided mechanism difference points against the
new free-boundary cell: `free_dual - two_gates` is −35.01 percentage points,
with nominal paired-t 95% interval [−39.32, −30.70] points and Holm-adjusted
exact sign-flip p=0.046875. This is evidence of worse performance for `free_dual`
under the registered paired experiment and its sign-exchangeability assumption,
not acceptance of a free-cell advantage.

The primary comparison gives each LR candidate 20 training CPU seconds.
Different models complete very different numbers of updates. A separately
registered exactly-128-update evaluation was executed without new training,
but its coverage is insufficient for a complete equal-update comparison of the
free cell. Both results and their distinct limitations are preserved below.

## Audit, selection and statistical units

The analysis began only after `COMPLETE.json`. All 244 searches, both LR
candidates per search, numeric checkpoints, supervised prediction coordinates,
labels, argmax decisions, cross entropies, accuracy counts and frozen data/source
identities passed the audit. No primary or secondary checkpoint was changed.

The six-task core uses seeds 9101–9103. The mechanism family uses seeds
9101–9108 on two fixed tasks, selective copy and multimodal selection. Shared
jobs are reused, giving 244 searches and 488 completed LR candidates. Within an
LR, primary selection is minimum validation cross entropy, then earlier CPU
time and step. Across LRs, it is minimum validation cross entropy, then smaller
LR, the operational reading documented before outcomes. There were no exact
cross-LR validation ties. Both candidates finish and selection is durably
recorded before test/OOD evaluation.

The mechanism unit is **one seed's mean accuracy difference across the two
fixed tasks**, giving n=8, not 16 independent task-seed observations. The exact
two-sided sign-flip test enumerates 256 sign assignments and assumes sign
exchangeability/symmetry under its null. Holm correction retains all six
predeclared comparisons. Acceptance also requires a mean gain of at least 1
point and a nominal paired-t 95% lower endpoint above zero. These t intervals
are not simultaneous intervals. Core three-seed means and sample SDs are
descriptive only. No episode-level binomial confidence intervals are invented.

All 28 task/seed pairing groups have identical minibatch streams through their
common update count, which ranges from 112 to 131. Shared frontend/readout
initialization also matches. Comparing the common prefix does not assert that
the faster models stop at the same update; their additional updates are part
of the registered equal-CPU experiment.
""")
    rows = [[model] + [mean_sd(core[(task, model)]["test_accuracy_mean"], core[(task, model)]["test_accuracy_sample_sd"])
                      for task in protocol["core"]["tasks"]] for model in protocol["core"]["models"]]
    sections.append("## Six-task core results\n\nAccuracy in percent, mean ± sample SD over the three registered seeds. These are the tested small-budget implementations, not claims about the best possible member of a model family.\n\n"
                    + table(["Model", "Selective copy", "MQAR", "Irregular", "MNIST", "FSDD", "Multimodal select"], rows))
    sections.append("""The strongest observed candidate varies by task. Mamba1 is the core mean
leader on selective copy and MNIST, Transformer on MQAR, FSDD and multimodal
selection, and two_gates on irregular observations. These are maxima among
this registered candidate set. FSDD performance is low for **all** candidates:
even its best mean is only 28.45%; this is neither state of the art nor strong
absolute speech-recognition capability. The MNIST and multimodal results are
also small-data, short-budget pilot results.

On these same six tasks the legacy Hepta HCSN candidate has a higher mean than
the new `free_dual` in every core cell. That is a three-seed descriptive finding,
not a separately corrected six-task significance claim.
""")
    rows = [[s["task"], percent(core[(s["task"], "free_dual")]["test_accuracy_mean"]), s["best_baseline"],
             percent(core[(s["task"], s["best_baseline"])]["test_accuracy_mean"]),
             f"{100*s['free_minus_best_baseline']:+.2f}", "pass" if s["passed"] else "fail"] for s in primary["core_content_screens"]]
    sections.append("### Registered content screens\n\nThe rule is `free_dual` within 2 points of the best mean among all seven baselines, including legacy_hcsn. This is a point-estimate screen, not an equivalence or noninferiority test.\n\n"
                    + table(["Task", "Free %", "Best tested baseline", "Baseline %", "Free − best, pp", "Screen"], rows)
                    + "\n\nIrregular observations miss the screen by 0.34 points beyond its 2-point allowance. The screen failure alone does not establish a statistically significant three-seed deficit on that task.")
    rows = [[model] + [mean_sd(core[(task, model)]["ood_accuracy_mean"], core[(task, model)]["ood_accuracy_sample_sd"])
                      for task in protocol["core"]["tasks"][:3]] for model in protocol["core"]["models"]]
    sections.append("### Prespecified OOD probes\n\nSelective copy and MQAR increase sequence length from 32 to 64; irregular observations multiply elapsed intervals by three. No real-data OOD split was silently substituted. Values are accuracy %, mean ± sample SD, n=3.\n\n"
                    + table(["Model", "Copy length 64", "MQAR length 64", "Irregular 3× time"], rows)
                    + "\n\nThe free cell does not show a general OOD robustness advantage. Its irregular-task mean falls from 93.95% to 53.58%; the continuous_rnn candidate reaches 81.58% in that OOD probe. The result does not isolate the cause of the drop.")
    rows = []
    for row in primary["mechanism"]:
        interval = row["paired_interval"]
        rows.append([row["comparison"], f"{100*interval['mean']:+.3f}",
                     f"[{100*interval['lower']:+.3f}, {100*interval['upper']:+.3f}]",
                     f"{row['test']['p_value']:.7f}", f"{row['holm_adjusted_p']:.7f}",
                     "accepted" if row["accepted"] else "not accepted"])
    sections.append("## Full six-contrast mechanism family\n\nDirection is always `free_dual minus comparator`. Effect and interval are percentage points. All comparisons contain all eight required seed pairs.\n\n"
                    + table(["Comparator", "Mean difference, pp", "Nominal paired-t 95% CI", "Two-sided sign-flip p", "Holm p", "Positive gate"], rows)
                    + "\n\nThe fixed_dual raw p is below 0.05 but its Holm p is not; it must not be reported as a corrected significant result. free_continuation has a point gain above 1 point, but its interval includes zero and its Holm p fails. The free_ordinary difference is close to zero. The two_gates result is a significant negative difference, not a positive-gate success.")
    rows = []
    for model in protocol["mechanism"]["models"]:
        row = [model]
        for task in protocol["mechanism"]["tasks"]:
            values = [runs[(task, model, seed)]["metrics"]["test"]["accuracy"] for seed in protocol["mechanism"]["seeds"]]
            row.append(mean_sd(statistics.mean(values), statistics.stdev(values)))
        rows.append(row)
    sections.append("### Mechanism-task descriptive cells\n\nThese eight-seed task means explain the paired family but do not add task-specific significance claims.\n\n"
                    + table(["Model", "Selective copy %", "Multimodal select %"], rows)
                    + "\n\nThe original fixed/direct threshold controls are per-neuron static while free_dual's boundary responds to input-dependent drift. That limits a pure interpretation as analytic-root versus equally conditional ordinary gating. A separately registered conditional_dual extension addresses this issue; it is additional/exploratory and is not retroactively inserted into the original six-comparison Holm family. Its results are outside this report.")
    rows = []
    for model in protocol["core"]["models"]:
        record = runs[("mnist", model, 9101)]
        count = record["counts"]["backbone"]
        rows.append([model, count, f"{100*abs(count-8800)/8800:.3f}", record["counts"]["total"]])
    sections.append("## Parameters, actual updates and complete CPU\n\nBackbone matching uses actual trainable parameters with no dummy padding. Every baseline is within 5% of the 8,800-parameter free backbone. The frontend has 2,208 parameters for every model. Readout size is shared within a task; the total column below uses the 10-class MNIST configuration.\n\n"
                    + table(["Model", "Backbone parameters", "Absolute backbone gap %", "Total, 10-class task"], rows))
    def compute_table(cohort):
        return table(["Model", "Searches", "Updates/LR median [min,max]", "Selected step median", "Full search CPU median, s", "Full search CPU sum, s"],
                     [[r["model"], r["searches"], f"{r['updates_per_lr_median']:g} [{r['updates_per_lr_min']},{r['updates_per_lr_max']}]",
                       f"{r['selected_step_median']:g}", f"{r['complete_search_cpu_seconds_median']:.3f}",
                       f"{r['complete_search_cpu_seconds_sum']:.3f}"] for r in compute if r["cohort"] == cohort])
    sections.append("### Balanced six-task, three-seed core compute\n\nEach row covers 18 searches and 36 LR candidates. The full process includes both complete candidates regardless of which earlier checkpoint was selected.\n\n" + compute_table("core"))
    sections.append("### Two-task, eight-seed mechanism compute\n\nEach row covers 16 searches. These rows overlap the core where task/model/seed match and must not be added to the core bill. They give actual update/CPU information for every additional mechanism arm.\n\n" + compute_table("mechanism"))
    cost = primary["costs"]
    rows = [["Nominal training-update allocation", "9760.000000", "488 LR candidates × 20 CPU s"],
            ["Actual measured training-update CPU", f"{cost['known_training_cpu_seconds_from_valid_summaries']:.6f}", "Includes finishing the update that crosses the budget"],
            ["All complete search children: aggregate RUSAGE_CHILDREN", f"{aggregate_cpu:.6f}", "Includes imports/setup/two LRs/validation/checkpoint/holdout costs"],
            ["All complete search children: sum of individual wait4 receipts", f"{receipt_cpu:.6f}", "Preserved second measurement route"],
            ["Scheduler self CPU", f"{completion['scheduler_cpu_seconds']:.6f}", "Separate from search children"],
            ["Primary analysis complete child", f"{execution_primary['child_cpu_seconds']:.6f}", "Imports, integrity audit, metrics, statistics and output writes"],
            ["Exactly-128 secondary complete child", f"{execution_secondary['child_cpu_seconds']:.6f}", "Eligibility/hash checks and new heldout inference; no new training"]]
    sections.append("### Cost reconciliation\n\n" + table(["Measured scope", "CPU seconds", "Meaning"], rows)
                    + f"\n\nThe main matrix wall time is {completion['wall_seconds']:.6f} seconds. The two child-CPU routes differ by {aggregate_cpu-receipt_cpu:.9f} seconds (247 microseconds). Every one of the 244 COMPLETE result rows exactly matches its per-run EXECUTION receipt. The tiny aggregate-versus-sum difference is consistent with separately accumulated microsecond reporting; neither value is adjusted or redistributed. These nested cost scopes must not be added as independent costs.\n\n"
                    + "The analysis also preserves setup, validation, holdout and outside-search-function costs per run. The latter combines interpreter/import/startup/shutdown overhead; it is not a separately isolated import benchmark. Whole-process peak RSS is not model-only allocation, and per-process peaks are not summed into a simultaneous-memory estimate. No hardware energy was measured. Shared data/native/scaling/solver work has separate receipts and is not hidden inside the main training total.")
    rows = []
    for group in ("content", "dynamics", "boundary", "reset", "refractory"):
        records = [r["groups"][group] for r in trainability["records"] if r["model"] == "free_dual"]
        rows.append([group, len(records), f"{min(r['selected_change']['l2'] for r in records):.6g}",
                     f"{min(r['gradient']['max_abs'] for r in records):.6g}", "pass"])
    sections.append("## Joint trainability and selected-checkpoint evidence\n\nAll 108 required HCSN-family runs pass all five parameter-group checks: finite gradients through the selected update, at least one nonzero gradient, and independently recomputed nonzero change from initialization to the actual selected checkpoint. No recorded gradient element is missing. All separately named drift/noise/discount/cost/reset/refractory tensors changed.\n\nFor the 28 free_dual searches specifically:\n\n"
                    + table(["Parameter group", "Runs", "Minimum selected-change L2", "Minimum across runs of observed max |gradient|", "Check"], rows)
                    + "\n\nA group passing this audit proves that the implemented loss reaches and updates it. It does not prove every scalar has a large gradient, that the learned mechanism is causally necessary, or that optimization found a good solution. The accuracy results above remain negative despite valid gradients and actual updates.")
    categories = [("fsdd", "speaker", "lucas"), ("fsdd", "speaker", "yweweler"),
                  ("multimodal_select", "query_modality", "image"), ("multimodal_select", "query_modality", "spoken"),
                  ("multimodal_select", "distractor_digit_agreement", "agree"), ("multimodal_select", "distractor_digit_agreement", "disagree")]
    indexed = {(r["task"], r["model"], r["stratum"], r["value"]): r for r in strata["aggregates"]["core"] if r["split"] == "test"}
    rows = []
    for model in protocol["core"]["models"]:
        row = [model]
        for task, category, value in categories:
            s = indexed[(task, model, category, value)]["accuracy"]
            row.append(mean_sd(s["mean"], s["sample_sd"]))
        rows.append(row)
    sections.append("## Data strata and scope of multimodality\n\nEvery task has 1,024 training, 256 validation and 512 test episodes. Copy/MQAR supervise four query positions per episode; the other tasks supervise one. Source-image IDs, audio recording IDs and speakers are disjoint across train/validation/test where applicable. The FSDD subset has only 600 unique recordings: 300 train, 100 validation and 200 test; test episodes repeat those 200 recordings. Test speakers are lucas and yweweler, with 100 recordings each. These are not official FSDD benchmark splits.\n\nAudio features use complete utterances. The multimodal task combines image/audio inputs with four fixed query tokens; it does not test raw live microphone causality or open-ended natural language. The test has 272 image queries, 240 spoken queries, 46 image/audio digit agreements and 466 disagreements. Repeated recordings and the training-seed repetitions do not create new independent recordings.\n\nThe table is accuracy %, mean ± sample SD over three seeds. FSDD speaker columns each have 256 episodes. Multimodal agreement and disagreement strata have different sizes and must not be averaged equally to reconstruct overall accuracy.\n\n"
                    + table(["Model", "FSDD lucas", "FSDD yweweler", "MM image query", "MM spoken query", "MM digits agree", "MM digits disagree"], rows)
                    + "\n\nThe free cell's modality-specific means are low on both image and spoken queries; this does not support a claim that it solves all modalities. The complete query-by-agreement and speaker strata, including source counts, remain in DATA_STRATA.json. No episode-independence significance claim is made from these descriptive strata.")
    lookup = {(r["task"], r["model"]): r for r in coverage}
    rows = [[model] + [(f"{lookup[(task,model)]['available']}/{lookup[(task,model)]['expected']} (−{lookup[(task,model)]['missing']})"
                         if (task,model) in lookup else "not scheduled") for task in protocol["core"]["tasks"]] for model in models]
    sections.append("## Exactly-128-update secondary: completed evaluation, incomplete coverage\n\nThe secondary requires **both** prescribed LR candidates to contain a saved checkpoint at exactly update 128. LR selection uses only each candidate's validation loss at that update, with a smaller-LR tie break. Missing 128 checkpoints are not replaced with nearby updates, a single available LR, extrapolation, or new training. Primary choices and costs are unchanged.\n\n"
                    + f"{len(secondary_checks)} of {len(runs)} run-level searches are eligible and evaluated; {len(missing)} are explicitly incomplete; zero are invalid. All newly saved supervised predictions, coordinate mappings and metrics were independently verified after evaluation. The two-LR availability counts below are `evaluated/scheduled (−missing)`.\n\n"
                    + table(["Model", "Copy", "MQAR", "Irregular", "MNIST", "FSDD", "Multimodal"], rows)
                    + f"\n\nOnly {len(complete_panels)} of 18 core task-seed panels contain all eight models, and {len(complete_tasks)} of six tasks has all eight models across all three core seeds. The two complete task-seed panels are FSDD/9103 and irregular/9103. free_dual has only 3/28 eligible searches in the entire matrix: selective_copy/9108, irregular/9103 and fsdd/9103. Its multimodal_select coverage is 0/8, so no eight-seed two-task free-cell mechanism comparison at exactly128 is available.\n\n"
                    + "This secondary therefore does not establish an equal-update advantage or deficit for the free cell across the registered matrix. The seven baseline models' complete coverage cannot repair missing free-cell observations. No failed completeness gate is silently reduced to a convenient subset. The saved eligible predictions remain available for explicitly limited descriptive inspection, but the main equal-CPU result is not replaced by such a subset.\n\n"
                    + "Equal update counts would also not imply equal CPU cost. The recorded training-prefix CPU describes already existing snapshots; all original full LR searches remain charged. The additional secondary inference consumes new CPU and is recorded separately. There is no basis here to infer that the large equal-CPU gaps are exclusively update-count effects or exclusively differences in representation quality.")
    sections.append("""## Interpretation and reproducibility

This study supports a narrower feasibility statement: the stationary scalar
oracle, its first derivative, and a content-carrying neural cell can be
implemented and trained jointly; selections and predictions can be audited.
It does not support the proposed accuracy or compute superiority of this cell
over the tested ordinary recurrent/gated/attention alternatives under the
registered small CPU budget. It also gives no foundation-model, full-modality,
hardware-energy or optimized deployment result.

The underlying neuron is a frozen-local mean-state closure, not exact
continuous stochastic regeneration. Its independently measured closure bias
remains a separate limitation; these task results do not identify that bias as
the sole cause of poor accuracy. Likewise, an optional faster scalar root was
tested in a separate extension and was not retroactively used in these runs.
An exact scalar optimal-control proof does not by itself certify a neural
content advantage.

The baseline implementations, dataset transformations, two-rate search,
20-CPU-second allocation and three/eight seed counts define the evidence's
scope. Other configurations may behave differently; none were substituted
after seeing these outcomes. Original static-direct fairness limitations and
the separately registered conditional control are reported openly.

Primary artifacts are `ANALYSIS.json`, `CORE_TABLE.csv`, `MECHANISM_TABLE.csv`,
`TRAINABILITY.json` and `DATA_STRATA.json`. This report adds
`SUPPLEMENTARY_AUDIT.json`, `MODEL_COMPUTE.csv` and `SECONDARY_COVERAGE.csv`.
The latter audit binds all report inputs, rechecks every original selected
checkpoint, verifies every eligible secondary prediction archive, and records
all 42 missing secondary searches with their actual primary update counts.
Both complete analysis-process receipts are preserved next to analysis001.

The reproducible reporting command is:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m experiments.hcsn_free_boundary_v1.analysis_report
```

It performs no new neural inference or training and refuses to overwrite
existing reporting evidence. The original analysis/secondary commands likewise
preserve their first outputs. No frozen training source, data, protocol,
checkpoint or primary outcome was edited for this report.
""")
    report = "\n\n".join(section.strip() for section in sections) + "\n"
    (output / "REPORT.md").write_text(report)
    return dict(status="passed", report=str(output / "REPORT.md"),
                secondary_verified=len(secondary_checks), secondary_missing=len(missing),
                complete_secondary_core_panels=len(complete_panels),
                cpu_seconds=time.process_time() - start_cpu)


if __name__ == "__main__":
    print(json.dumps(run()))
