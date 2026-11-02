"""Summarize frozen confirmation at the registered fit level, without refitting.

Primary intervals come only from the frozen statistics.analyze implementation.
Other distributions are descriptive; missing fits/pairs remain explicit nulls.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import resource
import statistics
import time

ARMS = ("fpt_base_multi", "fpt_neutral_drift", "fpt_neutral_bank", "fpt_neutral_both",
        "fpt_pooled_sign", "fpt_common_reset", "fpt_pooled_common", "fpt_base_single",
        "fpt_base_off", "ordinary_multi", "ordinary_single", "acc_free_off",
        "acc_free_multi", "acc_structured_off", "acc_structured_multi", "bayes")
PRIMARY = ("fpt_base_multi", "fpt_base_single", "ordinary_multi", "ordinary_single")
GATES = dict(belief_teacher_rmse="belief_teacher_rmse_max", selected_q_rmse="selected_q_rmse_max",
    pairwise_ranking_error="pairwise_ranking_error_max", margin_absolute_error_mean="margin_absolute_error_mean_max",
    teacher_regret_mean="teacher_regret_mean_max", coarse_seen_fraction="coarse_seen_fraction_min",
    actual_label_brier="actual_label_brier_max", actual_label_ece="actual_label_ece_max")
INPUTS = ("before_cell", "after_cell", "before_full", "after_full")
GROUPS = ("event", "recovery", "combined")


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def close(a, b):
    return finite(a) and finite(b) and math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-12)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Inputs:
    def __init__(self):
        self.hashes, self.issues = {}, []

    def read(self, path):
        path = Path(path)
        if not path.is_file():
            self.hashes[str(path)] = None
            self.issues.append(dict(path=str(path), reason="missing input"))
            return None
        raw = path.read_bytes()
        self.hashes[str(path)] = hashlib.sha256(raw).hexdigest()
        try:
            return json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)
        except (ValueError, OSError) as error:
            self.issues.append(dict(path=str(path), reason=str(error)))
            return None


def distribution(values):
    """One value per registered fit; never weight by decisions or pair counts."""
    available = [float(value) for value in values if finite(value)]
    detail = None if not available else dict(mean=statistics.fmean(available), minimum=min(available),
        maximum=max(available), median=statistics.median(available),
        sample_sd=statistics.stdev(available) if len(available) > 1 else None)
    complete = bool(values) and len(available) == len(values)
    return dict(expected_fits=len(values), available_fits=len(available), missing_or_undefined_fits=len(values)-len(available),
                all_registered_fits_complete=complete, all_registered_fit_summary=detail if complete else None,
                observed_available_fit_summary=detail,
                weighting="one equal-weight value per fit; partial summaries descriptive only; no additional inference")


def gate_counts(rows):
    return {name:dict(passed=sum((r.get("gates") or {}).get(name) is True for r in rows),
                      failed=sum((r.get("gates") or {}).get(name) is False for r in rows),
                      null=sum((r.get("gates") or {}).get(name) is None for r in rows)) for name in GATES}


def process_records(tracker, root, fits):
    abort_path = root / "ABORT_REGISTRATION.json"
    abort_registration = tracker.read(abort_path) if abort_path.exists() else None
    controller_path = root / "CONTROLLER_RECEIPT.json"
    controller = tracker.read(controller_path) if controller_path.exists() else None
    records = []
    for fit in fits:
        receipt = tracker.read(root / "process_receipts" / f"fit_{fit}.json")
        finished = tracker.read(root / f"fit_{fit}" / "FINISHED.json")
        started = tracker.read(root / f"fit_{fit}" / "STARTED.json")
        failure = root / f"fit_{fit}" / "FAILED.json"
        failed_record = tracker.read(failure) if failure.exists() else None
        guard = root / f"fit_{fit}" / "CANCELLED_BEFORE_START.json"
        if not guard.exists():
            guard = root / f"fit_{fit}" / "ABORTED_BEFORE_START.json"
        cancellation = tracker.read(guard) if guard.exists() else None
        scientific_started = isinstance(started,dict) and started.get("fit") == fit
        controlled_cancel = guard.exists() and not scientific_started
        attempted_worker = (isinstance(receipt,dict) and receipt.get("spawned") is not False
                            or any(value is not None for value in (finished,started,failed_record)))
        attempts = {path.name:tracker.read(path) for path in sorted((root/f"fit_{fit}"/"attempts").glob("*.json"))}
        reason = []
        if not isinstance(receipt, dict) or receipt.get("fit") != fit:
            reason.append("missing/mismatched process receipt")
            receipt = receipt if isinstance(receipt, dict) else {}
        if controlled_cancel:
            reason.append("controlled cancellation before scientific stage; worker failure receipt is not a scientific fit failure")
        elif attempted_worker and receipt.get("returncode") != 0:
            reason.append("worker did not exit successfully")
        if not isinstance(finished, dict) or finished.get("fit") != fit:
            reason.append("missing/mismatched FINISHED")
        if not isinstance(started, dict) or started.get("fit") != fit:
            reason.append("missing/mismatched STARTED")
        if failure.exists() and not controlled_cancel:
            reason.append("FAILED record exists")
        cpu = receipt.get("cpu_seconds")
        records.append(dict(fit=fit, complete=not reason, reasons=reason, receipt=receipt or None,
            status="cancelled_before_scientific_start" if controlled_cancel else "complete" if not reason else
                   "worker_failed_or_incomplete" if attempted_worker else "not_started_or_not_generated",
            scientific_stage_started=scientific_started,worker_attempt_observed=attempted_worker,
            cancellation=cancellation,failed_record=failed_record,candidate_attempts=attempts,
            observed_candidate_attempt_files=len(attempts),cpu_seconds=cpu if finite(cpu) and cpu >= 0 else None))
    values = [row["cpu_seconds"] for row in records]
    controller_cpu = controller.get("controller_self_cpu_seconds") if isinstance(controller,dict) else None
    if not finite(controller_cpu) or controller_cpu < 0:
        controller_cpu = None
    worker_total = sum(values) if all(v is not None for v in values) else None
    return dict(root=str(root), fits=records, all_workers_successful=all(row["complete"] for row in records),
                abort_registration=abort_registration,status_counts=dict(Counter(row["status"] for row in records)),
                scientific_stages_started=sum(row["scientific_stage_started"] for row in records),
                observed_candidate_attempt_files=sum(row["observed_candidate_attempt_files"] for row in records),
                observed_workers_cpu_seconds=sum(v for v in values if v is not None),
                all_registered_workers_cpu_seconds=worker_total,
                controller_receipt=controller,controller_self_cpu_seconds=controller_cpu,
                disjoint_workers_plus_controller_cpu_seconds=(worker_total+controller_cpu
                    if worker_total is not None and controller_cpu is not None else None),
                recorded_cost_receipts=sum(v is not None for v in values),
                measured_spawned_worker_receipts=sum(row["cpu_seconds"] is not None and row["worker_attempt_observed"] for row in records),
                cancelled_without_spawn=sum(row["status"]=="cancelled_before_scientific_start" and not row["worker_attempt_observed"] for row in records),
                expected_receipts=len(fits),
                scope="external wait4 user+system CPU, including unsuccessful workers; nested timings are not added")


def quality_record(quality, candidate, thresholds):
    if not isinstance(quality, dict) or quality.get("schema") != "digital-feedback-control-quality-v2":
        return dict(status="missing_or_invalid", metrics=None, gates=None, overall=None,
                    reasons=["missing or invalid v2 quality artifact"])
    record = quality.get("candidates", {}).get(candidate)
    if not isinstance(record, dict):
        return dict(status="missing_or_invalid", metrics=None, gates=None, overall=None,
                    reasons=["candidate quality record absent"])
    result = dict(record)
    reasons = list(result.get("reasons", []))
    if quality.get("thresholds") != thresholds or quality.get("required_candidates") != list(PRIMARY):
        reasons.append("quality contract differs from frozen protocol")
    if set(quality.get("candidates", {})) - set(ARMS):
        reasons.append("unregistered candidate in quality artifact")
    if record.get("status") not in ("complete", "incomplete"):
        reasons.append("unknown quality status")
    if record.get("status") == "complete":
        metric, gates = record.get("metrics"), record.get("gates")
        if not isinstance(metric, dict) or not isinstance(gates, dict) or set(gates) != set(GATES):
            reasons.append("missing quality metric/gate inventory")
        else:
            for name, limit in GATES.items():
                value = metric.get(name)
                expected = (None if not finite(value) else value >= thresholds[limit]
                            if name == "coarse_seen_fraction" else value <= thresholds[limit])
                if gates[name] is not expected:
                    reasons.append("quality gate inconsistent with recorded metric: " + name)
            overall = None if any(v is None for v in gates.values()) else all(gates.values())
            if record.get("overall") is not overall:
                reasons.append("quality overall flag inconsistent")
    if reasons:
        result.update(status="incomplete", metrics=None, gates=None, overall=None, reasons=reasons,
                      original_record=record)
    return result


def decoder_group(record, group, fitted):
    result = dict(status="missing", train_count=None, test_count=None, mse=None,
                  paired_mse_difference_after_minus_before=None, pair_ids=None, reasons=[])
    if not isinstance(record, dict) or not isinstance(fitted, dict):
        result["reasons"].append("missing decoder group or frozen group model")
        return result
    try:
        train, test = record["train_count"], record["test_count"]
        if any(not isinstance(n, int) or isinstance(n, bool) or n < 0 for n in (train, test)):
            raise ValueError("invalid decoder population counts")
        if train != fitted["train_count"]:
            raise ValueError("decoder TRAIN support differs from frozen model")
        status = ("no_eligible_training_pairs" if fitted["models"] is None else
                  "complete" if test else "no_eligible_pairs")
        if record["status"] != status:
            raise ValueError("decoder empty/support status inconsistent")
        result.update(status=status, train_count=train, test_count=test)
        if status != "complete":
            if any(record.get(name) is not None for name in
                   ("mse", "paired_mse_difference_after_minus_before", "predictions")):
                raise ValueError("unsupported decoder group must retain null errors")
            return result
        predictions = record["predictions"]
        if train <= 0 or not isinstance(predictions, list) or len(predictions) != test:
            raise ValueError("decoder prediction count differs from common paired population")
        ids, errors = set(), {name: [] for name in INPUTS}
        for row in predictions:
            if row["id"] in ids or row["group"] not in ("event", "recovery") or (group != "combined" and row["group"] != group):
                raise ValueError("duplicate pair or wrong event/recovery population")
            ids.add(row["id"])
            if not finite(row["target"]) or not 0 <= row["target"] <= 1 or set(row["predicted"]) != set(INPUTS):
                raise ValueError("invalid decoder target or four-input prediction inventory")
            for name in INPUTS:
                if not finite(row["predicted"][name]):
                    raise ValueError("nonfinite decoder prediction")
                errors[name].append((row["predicted"][name] - row["target"]) ** 2)
            for scope in ("cell", "full"):
                difference = errors["after_"+scope][-1] - errors["before_"+scope][-1]
                if not close(row["paired_mse_difference"][scope], difference):
                    raise ValueError("within-pair decoder error difference inconsistent")
        mse = {name: statistics.fmean(values) for name, values in errors.items()}
        paired = {scope: statistics.fmean(a-b for a,b in zip(errors["after_"+scope], errors["before_"+scope]))
                  for scope in ("cell", "full")}
        if any(not close(record["mse"].get(name), value) for name,value in mse.items()):
            raise ValueError("decoder MSE differs from paired predictions")
        if any(not close(record["paired_mse_difference_after_minus_before"].get(name), value) for name,value in paired.items()):
            raise ValueError("decoder paired mean differs from paired predictions")
        result.update(mse=mse, paired_mse_difference_after_minus_before=paired, pair_ids=sorted(ids))
    except (KeyError, TypeError, ValueError) as error:
        result.update(status="invalid", mse=None, paired_mse_difference_after_minus_before=None,
                      reasons=[str(error)], original_record=record)
    return result


def summarize(confirmation, training, protocol_path):
    start = time.process_time()
    tracker = Inputs()
    here = Path(__file__).resolve().parents[1]
    repository = here.parents[2]
    freeze = tracker.read(here / "SOURCE_FREEZE.json")
    protocol = tracker.read(protocol_path)
    if not isinstance(freeze, dict) or not isinstance(protocol, dict):
        raise ValueError("frozen source/protocol required")
    identity = {name: sha(repository/name) for name in freeze["source_sha256"]}
    if identity != freeze["source_sha256"] or sha(protocol_path) != freeze["protocol_sha256"]:
        raise ValueError("scientific source/protocol differs from published freeze")
    from ..statistics import analyze
    fits = protocol["fits"]
    if not fits or len(set(fits)) != len(fits) or fits != freeze["fits"]:
        raise ValueError("exact frozen fit list required")
    if confirmation.resolve() == training.resolve():
        raise ValueError("training/confirmation workers must be disjoint cost populations")
    costs = {name: process_records(tracker, root, fits) for name,root in
             (("training",training),("confirmation",confirmation))}
    operational = {fit: all(next(r for r in costs[stage]["fits"] if r["fit"] == fit)["complete"]
                           for stage in costs) for fit in fits}
    summaries, quality_rows, utility_rows, decoder_rows = [], [], [], []
    for fit in fits:
        folder = confirmation / f"fit_{fit}"
        raw_summary = tracker.read(folder / "summary.json")
        indexed = {}
        for row in raw_summary if isinstance(raw_summary,list) else []:
            key = (row.get("split"),row.get("candidate"))
            if row.get("fit") != fit or key in indexed or key[0] not in ("iid","ood") or key[1] not in ARMS:
                raise ValueError("duplicate or unregistered summary identity")
            indexed[key] = row
        artifact = tracker.read(training/f"fit_{fit}"/"models/independent_decoders.json")
        artifact_digest = (hashlib.sha256(json.dumps(artifact,sort_keys=True,allow_nan=False).encode()).hexdigest()
                           if isinstance(artifact,dict) else None)
        for split in ("iid","ood"):
            quality = tracker.read(folder / f"{split}_quality.json")
            decoder = tracker.read(folder / f"{split}_decoder.json")
            for candidate in ARMS:
                row = indexed.get((split,candidate))
                metrics = row.get("metrics") if isinstance(row,dict) else None
                valid = bool(row and row.get("valid") is True and operational[fit]
                             and row.get("controller") == "value" and row.get("worlds") == protocol[split+"_worlds"])
                if row is not None:
                    summaries.append(dict(row,valid=valid))
                utility_rows.append(dict(fit=fit,split=split,candidate=candidate,valid=valid,
                    utility=metrics.get("utility") if isinstance(metrics,dict) and finite(metrics.get("utility")) else None,
                    terminal_structure_error=metrics.get("terminal_structure_error") if isinstance(metrics,dict) else None,
                    structure_scope="within-fit mean of per-episode maximum terminal-identity residual",
                    original_summary=row))
                quality_item = quality_record(quality,candidate,protocol["quality_thresholds"])
                if quality_item.get("status") == "complete":
                    reported = quality_item["metrics"]
                    if (reported.get("episodes") != protocol[split+"_worlds"] or not isinstance(metrics,dict)
                            or not close(reported.get("actual_utility_mean"),metrics.get("utility"))):
                        quality_item = dict(status="incomplete",metrics=None,gates=None,overall=None,
                            reasons=["quality episode population or actual utility differs from summary"],original_record=quality_item)
                quality_rows.append(dict(fit=fit,split=split,candidate=candidate,execution_and_training_valid=valid,
                                         **quality_item))
            decoder_valid = (isinstance(decoder,dict) and isinstance(artifact,dict)
                and decoder.get("schema") == "digital-feedback-independent-ridge-decoder-v1"
                and decoder.get("fitted_during_evaluation") is False
                and artifact.get("training_used_confirmation") is False
                and decoder.get("artifact_sha256") == artifact_digest
                and decoder.get("fit") in (fit,None) and artifact.get("fit") in (fit,None)
                and decoder.get("ridge") == artifact.get("ridge") == protocol["decoder_ridge"])
            for group in GROUPS:
                item = decoder_group(decoder.get("groups",{}).get(group) if decoder_valid else None,
                                     group,artifact.get("groups",{}).get(group) if decoder_valid else None)
                baseline = indexed.get((split,"fpt_base_multi"))
                baseline_valid = bool(operational[fit] and baseline and baseline.get("valid") is True)
                decoder_rows.append(dict(fit=fit,split=split,group=group,
                    execution_and_training_valid=baseline_valid,artifact_binding_verified=decoder_valid,**item))
    analysis = analyze(summaries,protocol)
    quality_groups,utility_groups,decoder_groups = [],[],[]
    for split in ("iid","ood"):
        for candidate in ARMS:
            rows = [r for r in quality_rows if r["split"]==split and r["candidate"]==candidate]
            quality_groups.append(dict(split=split,candidate=candidate,expected_fits=len(fits),
                status_counts=dict(Counter(r["status"] for r in rows)),
                gate_counts=gate_counts(rows),
                metrics={name:distribution([(r.get("metrics") or {}).get(name) for r in rows])
                         for name in (*GATES,"exact_seen_fraction")},
                all_registered_pass=all(r.get("overall") is True and r["execution_and_training_valid"] for r in rows)))
            values = [r for r in utility_rows if r["split"]==split and r["candidate"]==candidate]
            utility_groups.append(dict(split=split,candidate=candidate,
                valid_fits=sum(r["valid"] for r in values),
                utility=distribution([r["utility"] for r in values]),
                terminal_structure_error=distribution([r["terminal_structure_error"] for r in values])))
        for group in GROUPS:
            rows = [r for r in decoder_rows if r["split"]==split and r["group"]==group]
            decoder_groups.append(dict(split=split,group=group,status_counts=dict(Counter(r["status"] for r in rows)),
                all_registered_valid=all(r["status"]=="complete" and r["execution_and_training_valid"] for r in rows),
                invalid_training_or_execution_fits=[r["fit"] for r in rows if not r["execution_and_training_valid"]],
                train_pair_counts=distribution([r["train_count"] for r in rows]),
                test_pair_counts=distribution([r["test_count"] for r in rows]),
                mse={name:distribution([(r["mse"] or {}).get(name) for r in rows]) for name in INPUTS},
                paired_mse_difference_after_minus_before={scope:distribution([
                    (r["paired_mse_difference_after_minus_before"] or {}).get(scope) for r in rows]) for scope in ("cell","full")}))
    primary = [r for r in quality_rows if r["candidate"] in PRIMARY]
    total_cost = [costs[name]["all_registered_workers_cpu_seconds"] for name in costs]
    tree_cost = [costs[name]["disjoint_workers_plus_controller_cpu_seconds"] for name in costs]
    costs["combined"] = dict(all_registered_workers_cpu_seconds=sum(total_cost) if all(v is not None for v in total_cost) else None,
        observed_workers_cpu_seconds=sum(costs[name]["observed_workers_cpu_seconds"] for name in ("training","confirmation")),
        all_registered_workers_plus_controllers_cpu_seconds=sum(tree_cost) if all(v is not None for v in tree_cost) else None,
        controller_self_cpu_seconds_by_stage={name:costs[name]["controller_self_cpu_seconds"] for name in ("training","confirmation")},
        scope="disjoint formal training/confirmation workers and separately recorded controller self CPU; controller launch CPU is a subset and is not added; no candidate/diagnostic/shared timers added; development, packaging and this summary process are additional costs")
    if identity != {name:sha(repository/name) for name in identity}:
        raise ValueError("scientific source changed during summary")
    usage=resource.getrusage(resource.RUSAGE_SELF)
    report=dict(schema="digital-feedback-confirmation-summary-v1",utc=datetime.now(timezone.utc).isoformat(),fits=fits,
        expected_quality_rows=len(fits)*2*len(ARMS),expected_primary_quality_rows=len(fits)*2*len(PRIMARY),
        quality=dict(primary_all_pass=all(r.get("overall") is True and r["execution_and_training_valid"] for r in primary),
            primary_joint_passed=sum(r.get("overall") is True and r["execution_and_training_valid"] for r in primary),
            primary_quality_overall_counts=dict(passed=sum(r.get("overall") is True for r in primary),
                failed=sum(r.get("overall") is False for r in primary),null=sum(r.get("overall") is None for r in primary)),
            primary_execution_or_training_invalid=sum(not r["execution_and_training_valid"] for r in primary),
            primary_gate_counts=gate_counts(primary),all_candidate_gate_counts=gate_counts(quality_rows),
            all_candidate_status_counts=dict(Counter(r["status"] for r in quality_rows)),
            by_candidate_domain=quality_groups,per_fit=quality_rows,
            coverage_scope="coarse empirical support and exact numeric overlap are distinct; neither certifies universal support"),
        utility=dict(by_candidate_domain=utility_groups,per_fit=utility_rows,
            scope="all recorded fit means retained, including invalid fits; only frozen primary analysis determines inferential validity"),
        decoders=dict(by_group_domain=decoder_groups,per_fit=decoder_rows,
            scope="final FPT baseline, fixed controller, same eligible before/after pairs; equal-weight fit summaries; empty support null; no information-theoretic or counterfactual causal claim"),
        whole_worker_costs=costs,input_sha256=tracker.hashes,input_issues=tracker.issues,
        source_sha256=identity,summary_script_sha256=sha(__file__),
        analysis_cpu_seconds=time.process_time()-start,summary_process_cpu_to_report_seconds=usage.ru_utime+usage.ru_stime,
        limitations="Primary inference imports the frozen producer statistic; this helper is aggregation, not independent audit. Decoder errors are checked against retained paired predictions, without refitting or rerunning neural inputs. Partial descriptive means are labeled and never replace complete-fit primary inference.")
    return analysis,report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--confirmation",type=Path,required=True)
    parser.add_argument("--training",type=Path,required=True)
    parser.add_argument("--protocol",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True,help="New evidence directory or existing directory without these outputs")
    args=parser.parse_args()
    targets=[args.output/name for name in ("ANALYSIS.json","CONFIRMATION_SUMMARY.json.gz")]
    if any(path.exists() for path in targets):
        raise FileExistsError("summary outputs already exist; retain them and choose a new output directory")
    analysis,report=summarize(args.confirmation,args.training,args.protocol)
    args.output.mkdir(parents=True,exist_ok=True)
    for path,value in zip(targets,(analysis,report)):
        raw=(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+"\n").encode()
        with path.open("xb") as stream:
            stream.write(gzip.compress(raw,compresslevel=6,mtime=0) if path.suffix==".gz" else raw)
    print(json.dumps(dict(outputs=[str(path) for path in targets],all_primary_valid=analysis["all_primary_valid"],
                         all_four_benefit_gates=analysis["all_four_benefit_gates"],quality_primary_all_pass=report["quality"]["primary_all_pass"],
                         input_issues=len(report["input_issues"])),sort_keys=True))


if __name__ == "__main__":
    main()
