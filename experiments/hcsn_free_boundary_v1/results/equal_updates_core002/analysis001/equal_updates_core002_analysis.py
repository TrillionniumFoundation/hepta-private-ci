"""Descriptive analysis of the separately registered fixed-update diagnostic.

Requires its COMPLETE marker, preserves failures, verifies all reused reference
predictions, and never changes the primary or original-secondary evidence.
"""

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics
import time

from .analysis import (PACKAGE, REPOSITORY, _metrics_match, _read_updates,
                       _write_csv, _write_json, digest, inspect_dataset,
                       read_json, selected_parameter_audit, validate_prediction_archive)
from .analysis_report import mean_sd, percent, table
from .analysis_secondary import choose_128_candidate
from .equal_updates_core002 import DEFAULT_OUTPUT, PROTOCOL, update_prefix, verify


PREFIX_PRESERVATION_SHA256 = "99024569247741ffaccbc0bbd4bd117f50d818fddc6cf02cd88fe05e7b22e219"


def _descriptive(values):
    return dict(n=len(values), mean=statistics.mean(values) if values else None,
                sample_sd=statistics.stdev(values) if len(values)>1 else None)


def analyze(output=DEFAULT_OUTPUT, protocol_path=PROTOCOL):
    started_cpu, started = time.process_time(), time.perf_counter()
    output, protocol_path = Path(output), Path(protocol_path)
    if not (output / "COMPLETE.json").is_file():
        raise RuntimeError("Fixed-update diagnostic is not complete; no interim quality analysis")
    for name in ("ANALYSIS.json", "TABLE.csv", "COMPUTE.csv", "REPORT.md"):
        if (output / name).exists():
            raise FileExistsError(f"Preserve first analysis evidence: {name}")
    protocol = verify(protocol_path, output)
    preserved_path = output / "REFERENCE_PREFIX_AUDIT.json"
    if digest(preserved_path) != PREFIX_PRESERVATION_SHA256:
        raise ValueError("Pre-reclamation prefix audit changed")
    preserved = read_json(preserved_path)
    if preserved["protocol_sha256"] != digest(protocol_path):
        raise ValueError("Preserved prefix audit belongs to another registration")
    original_analysis_path = PACKAGE / "results/study001/analysis001/ANALYSIS.json"
    if digest(original_analysis_path) != preserved["original_primary_analysis_sha256"]:
        raise ValueError("Original primary log-hash anchor changed")
    original_analysis = read_json(original_analysis_path)
    original_log_hashes = {(g["task"],g["seed"],c["model"],c["lr"]):c["updates_sha256"]
                          for g in original_analysis["pairing"] for c in g["candidate_logs"]}
    preserved_logs = {(r["task"],r["seed"],r["model"],r["learning_rate"]):r for r in preserved["records"]}
    completion = read_json(output / "COMPLETE.json")
    if completion["completed_jobs"] != 18 or len(completion["results"]) != 18:
        raise ValueError("Diagnostic completion does not include all declared searches")
    datasets = {task: inspect_dataset(PACKAGE / "data/study001", task) for task in protocol["tasks"]}
    new_runs, reference_runs, errors = [], [], []
    audit_counts = Counter()
    execution_lookup = {(r["task"], r["seed"]): r for r in completion["results"]}
    for job in protocol["jobs"]:
        key = (job["task"], job["seed"])
        directory = output / "runs" / key[0] / str(key[1])
        execution = execution_lookup[key]
        entry = dict(task=key[0], model="free_dual", seed=key[1], status="invalid", execution=execution)
        try:
            if execution["status"] != "completed" or execution.get("returncode") != 0:
                entry["status"] = "failed"
                entry["failure"] = read_json(directory / "FAILURE.json") if (directory / "FAILURE.json").exists() else None
                new_runs.append(entry)
                continue
            if read_json(directory / "EXECUTION.json") != execution:
                raise ValueError("Per-run execution differs from final completion receipt")
            result = read_json(directory / "SUMMARY.json")
            request, selection, candidates = result["request"], result["selection"], result["candidates"]
            if result["status"] != "completed" or request["target_updates"] != 128 or request["model"] != "free_dual":
                raise ValueError("Wrong model/fixed-update result")
            for field in ("width", "depth", "batch_size"):
                if request[field] != protocol["optimization"][field]:
                    raise ValueError("Registered dimensions/batching changed")
            if request["learning_rates"] != [.001, .003] or request["cpu_ceiling_per_lr"] != 120:
                raise ValueError("Registered LR/CPU guard changed")
            if request["source_dataset_sha256"] != datasets[key[0]]["sha256"]:
                raise ValueError("Dataset differs from the registered frozen data")
            if len(candidates) != 2 or sorted(c["learning_rate"] for c in candidates) != [.001, .003]:
                raise ValueError("Both prescribed LR candidates are required")
            expected_prefix = update_prefix(REPOSITORY / job["expected_prefix_source"], 128)
            trainability = []
            for candidate in candidates:
                folder = directory / candidate["directory"]
                if read_json(folder / "FIXED_UPDATE_RECEIPT.json") != candidate:
                    raise ValueError("Candidate metadata differs from its durable receipt")
                target = candidate["terminal_checkpoint"]
                if candidate["updates"] != 128 or target["step"] != 128 or not target["fixed_step_128"]:
                    raise ValueError("Candidate is not an exact update128 snapshot")
                if digest(folder / target["weights"]) != target["sha256"]:
                    raise ValueError("Terminal numeric checkpoint hash changed")
                if digest(folder / "initial.npz") != job["original_initial"][str(candidate["learning_rate"])]["sha256"]:
                    raise ValueError("Fresh initialization differs from original bytes")
                actual_prefix = update_prefix(folder / "updates.jsonl", 128)
                if actual_prefix != expected_prefix:
                    raise ValueError("Any of the first128 minibatches/prefixes differs")
                updates, gradients = _read_updates(folder / "updates.jsonl", 128)
                if len(updates) != 128:
                    raise ValueError("Extra or missing optimizer updates")
                changes, named = selected_parameter_audit(folder / "initial.npz", folder / target["weights"], result["counts"])
                for group, actual in changes.items():
                    if not math.isclose(actual["l2"], candidate["parameter_changes_at_target"][group]["l2"], abs_tol=1e-7, rel_tol=2e-5):
                        raise ValueError("Target checkpoint parameter change differs from independent numeric audit")
                passed = all(g["all_finite"] and g["ever_nonzero"] and g["maximum_missing_elements"]==0
                             and changes[name]["max_abs"]>0 for name,g in gradients.items())
                trainability.append(dict(learning_rate=candidate["learning_rate"], gradients=gradients,
                                          actual_parameter_changes=changes, named_changes=named, passed=passed))
                old = job["existing_original128"].get(str(candidate["learning_rate"]))
                if old is not None:
                    if digest(folder / target["weights"]) != old["sha256"] or not candidate["existing_original128_byte_identical"]:
                        raise ValueError("Existing original128 numerical replay mismatch")
                    audit_counts["existing_original128_exact_replays"] += 1
                retained = {p.name for p in folder.glob("*.npz")}
                if retained != set(candidate["retained_numeric"]):
                    raise ValueError("Unexpected numeric checkpoint retention")
                audit_counts["fresh_initials_byte_identical"] += 1
                audit_counts["new_candidate_full128_prefixes_verified"] += 1
            best = min(candidates, key=lambda c:(c["terminal_checkpoint"]["validation"]["cross_entropy"], c["learning_rate"]))
            if (selection["selected_step"] != 128 or selection["selected_learning_rate"] != best["learning_rate"]
                    or selection["selected_checkpoint_sha256"] != best["terminal_checkpoint"]["sha256"]
                    or selection["selected_validation"] != best["terminal_checkpoint"]["validation"]
                    or selection["completed_lr_candidates"] != 2
                    or read_json(directory / "SELECTION.json") != selection
                    or digest(directory / "selected.npz") != selection["selected_checkpoint_sha256"]):
                raise ValueError("New selection is not the val-only winner at exactly128")
            locked = [i for i,r in enumerate(result["access_log"]) if r["event"] == "selection_locked"]
            if len(locked) != 1 or any(i<=locked[0] for i,r in enumerate(result["access_log"]) if r.get("split") in ("test","ood")):
                raise ValueError("Holdout access preceded both-LR fixed-update selection lock")
            metrics = {}
            for split in ("test", "ood"):
                labels = datasets[key[0]]["labels"].get(split)
                if labels is None:
                    if result["metrics"][split] is not None:
                        raise ValueError("Metrics for absent OOD data")
                    metrics[split] = None
                    continue
                archive = directory / f"{split}_predictions.npz"
                computed, _ = validate_prediction_archive(archive, labels, datasets[key[0]]["manifest"]["output_dim"])
                _metrics_match(computed, result["metrics"][split])
                metrics[split] = dict(computed, prediction_sha256=digest(archive))
            entry.update(status="valid", metrics=metrics, selection=selection, trainability=trainability,
                         counts=result["counts"], summary_sha256=digest(directory / "SUMMARY.json"),
                         training_update_cpu_seconds=sum(c["training_cpu_seconds"] for c in candidates),
                         validation_cpu_seconds=sum(c["validation_cpu_seconds"] for c in candidates),
                         updates_per_lr=[c["updates"] for c in candidates],
                         original_search_cost_is_not_recharged_as_new=True)
        except Exception as error:
            entry["error"] = dict(type=type(error).__name__, message=str(error))
            errors.append(dict(task=key[0], seed=key[1], **entry["error"]))
        new_runs.append(entry)
    jobs = {(j["task"],j["seed"]):j for j in protocol["jobs"]}
    for reference in protocol["reused_baseline_references"]:
        key = (reference["task"], reference["model"], reference["seed"])
        folder = REPOSITORY / reference["directory"]
        row = read_json(folder / "summary.json")
        original_folder = REPOSITORY / reference["original_search_directory"]
        original = read_json(original_folder / "summary.json")
        expected = choose_128_candidate(original["candidates"], [.001,.003])
        if row["status"] != "evaluated" or expected["status"] != "eligible" or expected != row["eligibility"]:
            raise ValueError("Reused baseline lacks the original exact128 two-LR selection")
        if read_json(folder / "SELECTION.json") != row["selection"] or row["selection"]["selected_sha256"] != reference["selected_sha256"]:
            raise ValueError("Reused baseline selection identity changed")
        prefix = update_prefix(REPOSITORY / jobs[(key[0],key[2])]["expected_prefix_source"],128)
        for candidate in original["candidates"]:
            source_log = original_folder/candidate["directory"]/"updates.jsonl"
            log_key = (key[0],key[2],key[1],candidate["learning_rate"])
            saved = preserved_logs[log_key]
            expected_canonical = hashlib.sha256(json.dumps(prefix,sort_keys=True,separators=(",",":")).encode()).hexdigest()
            if (saved["canonical_first128_sha256"] != expected_canonical
                    or saved["original_log_sha256"] != original_log_hashes[log_key]
                    or not saved["all128_rows_match_common_reference"]
                    or preserved["common_first128_rows"][f"{key[0]}/{key[2]}"] != prefix):
                raise ValueError("Preserved exact prefix evidence differs from its original audit anchors")
            if source_log.is_file():
                if update_prefix(source_log,128) != prefix:
                    raise ValueError("Reused baseline first128 minibatches differ from paired diagnostic")
                audit_counts["baseline_prefix_logs_reread_live"] += 1
            else:
                audit_counts["baseline_prefix_logs_from_pre_reclamation_audit"] += 1
            audit_counts["reused_baseline_candidate_full128_prefixes_verified"] += 1
        metrics = {}
        for split in ("test","ood"):
            labels = datasets[key[0]]["labels"].get(split)
            if labels is None:
                metrics[split] = None
                continue
            archive = folder / f"{split}_predictions.npz"
            computed,_ = validate_prediction_archive(archive,labels,datasets[key[0]]["manifest"]["output_dim"])
            _metrics_match(computed,row["metrics"][split])
            metrics[split] = dict(computed,prediction_sha256=digest(archive))
        execution = read_json(original_folder / "EXECUTION.json")
        reference_runs.append(dict(task=key[0],model=key[1],seed=key[2],status="valid_reused",metrics=metrics,
                                   selection=row["selection"],counts=original["counts"],new_training=False,new_inference=False,
                                   recorded_training_cpu_to128_all_lrs=row["measured_training_cpu_to_128_all_lrs"],
                                   original_full_search_child_cpu_seconds=execution["child_cpu_seconds"],
                                   original_secondary_per_run_cpu_seconds=row["additional_secondary_cpu_seconds"],
                                   summary_sha256=digest(folder/"summary.json")))
    all_runs = new_runs+reference_runs
    models = ["free_dual"]+protocol["baseline_names"]
    lookup = {(r["task"],r["model"],r["seed"]):r for r in all_runs}
    rows=[]
    for task in protocol["tasks"]:
        for model in models:
            records=[lookup[(task,model,seed)] for seed in protocol["seeds"]]
            valid=[r for r in records if r["status"] in ("valid","valid_reused")]
            row=dict(task=task,model=model,n=len(valid),expected_n=3,complete=len(valid)==3,
                     source="new_fresh128_training" if model=="free_dual" else "explicit_original_secondary_reuse")
            for split in ("test","ood"):
                for metric in ("accuracy","cross_entropy"):
                    values=[r["metrics"][split][metric] for r in valid if r["metrics"][split] is not None]
                    summary=_descriptive(values)
                    row.update({f"{split}_{metric}_{key}":value for key,value in summary.items()})
            rows.append(row)
    differences=[]
    for task in protocol["tasks"]:
        for comparator in protocol["baseline_names"]:
            for split in ("test","ood"):
                if split not in datasets[task]["labels"]:
                    continue
                pairs=[]; missing=[]
                for seed in protocol["seeds"]:
                    left,right=lookup[(task,"free_dual",seed)],lookup[(task,comparator,seed)]
                    if left["status"]!="valid" or right["status"]!="valid_reused":
                        missing.append(seed);continue
                    pairs.append(dict(seed=seed,difference=left["metrics"][split]["accuracy"]-right["metrics"][split]["accuracy"]))
                differences.append(dict(task=task,comparison=comparator,split=split,complete=not missing,
                                         missing_seeds=missing,pairs=pairs,**_descriptive([p["difference"] for p in pairs]),
                                         interpretation="paired three-seed descriptive difference; no new significance/acceptance test"))
    compute=[]
    for model in models:
        records=[r for r in all_runs if r["model"]==model and r["status"] in ("valid","valid_reused")]
        prefix=[r["training_update_cpu_seconds"] if model=="free_dual" else r["recorded_training_cpu_to128_all_lrs"] for r in records]
        historical=[r["execution"]["child_cpu_seconds"] if model=="free_dual" else r["original_full_search_child_cpu_seconds"] for r in records]
        compute.append(dict(model=model,valid_searches=len(records),updates_per_lr=128,
                            two_lr_training_cpu_to128_median=statistics.median(prefix) if prefix else None,
                            two_lr_training_cpu_to128_sum=sum(prefix),
                            measured_full_search_cpu_median=statistics.median(historical) if historical else None,
                            measured_full_search_cpu_sum=sum(historical),
                            full_search_scope="new fixed128 search" if model=="free_dual" else "historical original20CPUperLR search, reused, not reexecuted",
                            new_training=model=="free_dual",new_reference_inference=False))
    verify(protocol_path,output)
    valid_count=sum(r["status"]=="valid" for r in new_runs)
    complete=valid_count==18 and len(reference_runs)==126 and not errors
    costs=dict(new_complete_worker_cpu_seconds=completion["sum_complete_child_cpu_seconds"],
               new_aggregate_rusage_children_cpu_seconds=completion["aggregate_rusage_children_cpu_seconds"],
               new_coordinator_cpu_seconds=completion["coordinator_cpu_seconds"],
               new_wall_seconds=completion["wall_seconds"],
               new_training_update_cpu_seconds=sum(r.get("training_update_cpu_seconds",0) for r in new_runs),
               preserved_failed_worker_cpu_seconds=sum(r["execution"].get("child_cpu_seconds",0) for r in new_runs if r["status"]!="valid"),
               reused_reference_additional_training_cpu_seconds=0,
               reused_reference_additional_inference_cpu_seconds=0,
               historical_reused_reference_full_search_cpu_seconds=sum(r["original_full_search_child_cpu_seconds"] for r in reference_runs),
               historical_reused_reference_secondary_per_run_cpu_seconds=sum(r["original_secondary_per_run_cpu_seconds"] for r in reference_runs),
               historical_scope="previously executed evidence, disclosed separately and not charged again as new computation",
               energy_measured=False)
    report=dict(schema="hcsn-equal-updates-core002-analysis.v1",status="complete" if complete else "incomplete",
                 valid_new_searches=valid_count,expected_new_searches=18,reused_baseline_searches=len(reference_runs),
                 new_runs=new_runs,references=reference_runs,table=rows,paired_descriptive_differences=differences,
                 compute=compute,costs=costs,errors=errors,audit_counts=dict(audit_counts),
                 new_hypothesis_tests_performed=False,original_six_holm_contrasts_changed=False,
                 original_secondary_unchanged="202 evaluated /42 incomplete /0 new training",
                 data_hash_gate_difference="new worker verifies complete frozen manifest before and after fitting/evaluation; unlike original run_search it does not repeat the dataset hash specifically between selection lock and heldout load; all data hashes match in this actual run",
                 protocol_sha256=digest(protocol_path),completion_sha256=digest(output/"COMPLETE.json"),
                 source_sha256={"equal_updates_core002_analysis.py":digest(__file__)},
                 preserved_prefix_audit_sha256=digest(preserved_path),
                 storage_preservation="Unregistered original full logs may be reclaimed only after verified archiving; exact first128 rows were independently checked and bound to original primary log hashes in the preserved audit before reclamation. Registered files are retained.",
                 analysis_cpu_seconds=time.process_time()-started_cpu,analysis_wall_seconds=time.perf_counter()-started)
    _write_json(output/"ANALYSIS.json",report)
    _write_csv(output/"TABLE.csv",rows);_write_csv(output/"COMPUTE.csv",compute)
    by={(r["task"],r["model"]):r for r in rows}
    def performance_row(model,split,tasks):
        result=[model]
        for task in tasks:
            row=by[(task,model)]
            result.append(mean_sd(row[f"{split}_accuracy_mean"],row[f"{split}_accuracy_sample_sd"]) if row["complete"] else f"incomplete {row['n']}/3")
        return result
    pieces=["# Separate equal_updates_core002 diagnostic", "## Status and scope",
        f"**{valid_count}/18 new free_dual searches valid; 126 baseline searches explicitly reused; complete diagnostic: {complete}.** All new candidates are fresh same-seed training runs targeted at exactly128 updates. This is a post-primary diagnostic on already-inspected test data, not a replacement for the 20-CPU-second primary study or an untouched new confirmation.",
        "The original strict128 secondary remains permanently unchanged: **202 evaluated, 42 incomplete, zero added training**. This separate directory pays for new free-cell training to investigate the concrete coverage limitation. It does not fill or rewrite those original records, change the six original Holm comparisons, add learning rates, or tune on these diagnostic outcomes.",
        "## Registration, selection and audit",
        "EQUAL_UPDATES_CORE002_PROTOCOL.json and REGISTRATION.json were written before new training. The six tasks and seeds9101–9103 are fixed. Every new free candidate starts from the original same-seed initialization, uses frozen training.py Adam/task cross entropy/clipping/batch32/model/data, and stops at exactly128 updates. The 120-CPU-second ceiling is a failure guard, not the target allocation. No optimizer state is resumed.",
        "Both learning rates, 0.001 and0.003, complete before choosing minimum validation cross entropy at exactly128; ties use the smaller LR. The helper's earlier CPU-gate best checkpoint is explicitly ignored. Durable selection precedes test/OOD loading. Only this diagnostic's intermediate numeric checkpoints are pruned; their hashes remain in metadata, and initial/128/selected numeric weights are retained. Original files are never pruned.",
        f"Audit counts: {dict(audit_counts)}. The new initial files and all128 minibatch/prefix hashes are verified; every original free128 checkpoint that already existed must replay byte-for-byte. Every reused baseline candidate's first128 minibatches is also independently checked. New and reused prediction archives are independently remapped and their accuracy/CE recomputed. Every failed execution, if any, remains in the complete cost bill.",
        "During execution the shared filesystem filled. Original evidence had already been verified in its complete archive. To recover space, only unregistered redundant old logs/checkpoints could be removed after archive-member hash checks. Before reclamation, all252 baseline LR prefixes were independently parsed and compared, and their full-log SHA matched the original primary audit. The exact first128 evidence is retained in REFERENCE_PREFIX_AUDIT.json, whose byte hash is pinned by this analysis. The eighteen registered prefix logs and every registered training dependency remain live. Counts distinguish live rereads from the preserved pre-reclamation audit; no missing evidence is silently invented.",
        "A check-location difference is disclosed: the new wrapper verifies the complete registered manifest before and after each worker, while the original run_search additionally hashes the dataset immediately between selection lock and heldout load. This wrapper lacks that extra intermediate hash operation. The data were static and all registered hashes match in this actual experiment; the frozen training source itself is unchanged.",
        "## Complete ID table",
        "Accuracy in percent, mean ± sample SD over three paired seeds. free_dual is newly retrained; all seven other rows reuse the original strict128 validation-selected snapshots and already executed predictions. No new significance claim is assigned to these three-seed cells.",
        table(["Model","Copy","MQAR","Irregular","MNIST","FSDD","Multimodal"],[performance_row(m,"test",protocol["tasks"]) for m in models]),
        "## Prespecified OOD table",
        "Copy/MQAR length64 and irregular3× time; no new OOD task was introduced.",
        table(["Model","Copy64","MQAR64","Irregular3×time"],[performance_row(m,"ood",protocol["tasks"][:3]) for m in models]),
        "## Descriptive paired differences",
        "Direction is new free_dual minus the indicated reused baseline, in percentage points. The per-seed pairs and sample SDs are retained in ANALYSIS.json. These are not new corrected hypothesis tests or primary acceptance gates."]
    diff={(r["task"],r["comparison"],r["split"]):r for r in differences}
    pieces.append(table(["Comparator"]+protocol["tasks"],[[m]+[
        f"{100*diff[(task,m,'test')]['mean']:+.2f}" if diff[(task,m,'test')]["complete"] else "incomplete"
        for task in protocol["tasks"]] for m in protocol["baseline_names"]]))
    pieces += ["## Costs and distinct comparison targets",
        table(["Model","Searches","Median two-LR training CPU to128, s","Median measured full-search CPU, s","Full-search scope"],
              [[r["model"],r["valid_searches"],f"{r['two_lr_training_cpu_to128_median']:.3f}" if r["valid_searches"] else "NA",
                f"{r['measured_full_search_cpu_median']:.3f}" if r["valid_searches"] else "NA",r["full_search_scope"]] for r in compute]),
        f"New complete worker CPU: **{costs['new_complete_worker_cpu_seconds']:.6f}s**; coordinator CPU: **{costs['new_coordinator_cpu_seconds']:.6f}s**; wall time: **{costs['new_wall_seconds']:.6f}s**. Actual new training-update CPU is {costs['new_training_update_cpu_seconds']:.6f}s. Failed-worker CPU retained is {costs['preserved_failed_worker_cpu_seconds']:.6f}s. These are nested scopes and must not all be added together.",
        f"The reused baselines add zero training or neural inference in this diagnostic. Their historical complete original searches consumed {costs['historical_reused_reference_full_search_cpu_seconds']:.6f}s; their earlier strict128 per-run evaluation scopes consumed {costs['historical_reused_reference_secondary_per_run_cpu_seconds']:.6f}s, excluding that earlier evaluation worker's shared import/setup overhead. These historical observations are disclosed, not falsely billed as newly executed work.",
        "Equal updates are not equal compute. Prefix CPU-to128 is an observed timing of the training prefix; the original baseline full20CPU/LR searches remain real previously incurred costs. Their original whole-search costs and new free-cell fixed128 whole-search costs have different scopes. Different executions also have different contention/import/checkpoint timing. No hardware-energy or isolated-throughput claim follows.",
        "## Interpretation limits",
        "This complete fixed-update diagnostic, if all18 new searches pass, can describe performance after the same number of optimizer updates with the registered initialization, data and two-LR search. It cannot establish that a fixed-update gain is an equal-CPU advantage, overturn the original0/6 mechanism or0/6 content-screen results, or give a causal decomposition of the original gaps. Both statistical target and computation spent differ from the primary experiment.",
        "The test arrays were already observed in the completed primary/secondary experiments. The diagnostic was motivated by missing strict128 coverage and was separately registered before its new execution. It is therefore a disclosed diagnostic, not an independent fresh-test confirmation. Three seeds support descriptive uncertainty only. The tiny real-data tasks, low absolute speech accuracy, mean-state closure bias and non-foundation-model scope remain applicable. It does not establish universal superiority or inferiority of any architecture family.",
        "Reproduce audit/report only with `python -m experiments.hcsn_free_boundary_v1.equal_updates_core002_analysis`. It performs no training or neural inference and refuses to overwrite prior analysis evidence. All original38 frozen source/data files, primary selections, original secondary records and registered Holm results remain unchanged."]
    (output/"REPORT.md").write_text("\n\n".join(pieces)+"\n")
    return report


if __name__=="__main__":
    result=analyze()
    print(json.dumps(dict(status=result["status"],valid_new_searches=result["valid_new_searches"],
                          reused_baseline_searches=result["reused_baseline_searches"],errors=result["errors"])))
