"""Read-only reproduction from raw confirmation data; no scientific-module imports."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys
import time

from scipy.special import stdtrit


FAMILIES = ["ordinary_base", "ordinary_bank", "clocked_bank", "first_passage_bank", "raw_history"]
CPU = ["ordinary_bank__structured_on__cpu", "first_passage_bank__structured_on__cpu",
       "first_passage_bank__impulse_on__cpu", "evidence_accumulator__structured_on__cpu"]
CANDIDATES = [f"{f}__{v}" for f in FAMILIES for v in ("free_off", "structured_off", "structured_on")]
CANDIDATES += [f"{f}__impulse_on" for f in ("ordinary_bank", "clocked_bank", "first_passage_bank")]
CANDIDATES += ["evidence_accumulator__free_off", "evidence_accumulator__structured_on"] + CPU
COMPARISONS = {
    "terminal_structure": [(f"{f}__structured_off", f"{f}__free_off") for f in FAMILIES],
    "occupancy_supervision": [("first_passage_bank__structured_on", "first_passage_bank__structured_off")],
    "impulse_mechanism": [("first_passage_bank__impulse_on", "first_passage_bank__structured_on")],
    "analytic_increment": [("first_passage_bank__structured_on", "ordinary_bank__structured_on")],
}


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1048576):
            value.update(block)
    return value.hexdigest()


def read(path):
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def array_records(path):
    """Incremental array decoding also consumes gzip EOF and rejects trailing data."""
    decoder = json.JSONDecoder()
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        buffer, ended = "", False

        def fill():
            nonlocal buffer, ended
            data = stream.read(65536)
            buffer += data
            ended = not data

        def token():
            nonlocal buffer
            buffer = buffer.lstrip()
            while not buffer and not ended:
                fill()
                buffer = buffer.lstrip()
            if not buffer:
                raise ValueError("incomplete JSON array")

        token()
        if buffer[0] != "[":
            raise ValueError("raw episodes must form an array")
        buffer = buffer[1:]
        first = True
        while True:
            token()
            if buffer[0] == "]" and first:
                buffer = buffer[1:]
                break
            while True:
                try:
                    value, consumed = decoder.raw_decode(buffer)
                    break
                except json.JSONDecodeError:
                    if ended:
                        raise
                    fill()
            buffer = buffer[consumed:]
            yield value
            first = False
            token()
            if buffer[0] == "]":
                buffer = buffer[1:]
                break
            if buffer[0] != ",":
                raise ValueError("raw episode separator missing")
            buffer = buffer[1:]
        while not ended:
            if buffer.strip():
                raise ValueError("extra content after raw array")
            buffer = ""
            fill()
        if buffer.strip():
            raise ValueError("extra content after raw array")


def utc(value):
    if value.endswith(" UTC"):
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def average(values):
    return math.fsum(values) / len(values)


def interval(fits, values, multiplicity=1, primary=False):
    n = len(values)
    mean = average(values)
    sd = math.sqrt(math.fsum((v-mean)**2 for v in values) / (n-1))
    se = sd / math.sqrt(n)
    critical = float(stdtrit(n-1, 1-.05/(2*multiplicity)))
    result = dict(fits=fits, fit_differences=values, n_independent_fits=n, degrees_of_freedom=n-1,
                  mean=mean, sample_sd=sd, standard_error=se, t_critical=critical,
                  confidence_interval=[mean-critical*se, mean+critical*se],
                  multiplicity=multiplicity, alpha_per_interval=.05/multiplicity)
    if primary:
        signed_sums = [0.]
        for value in values:
            signed_sums = [s-value for s in signed_sums] + [s+value for s in signed_sums]
        result.update(practical_margin=.02, benefit_gate=result["confidence_interval"][0]>.02,
                      signflip_two_sided_p_unadjusted=sum(abs(s/n)>=abs(mean)-1e-14 for s in signed_sums)/len(signed_sums))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    study, runs, repo = args.study.resolve(), args.runs.resolve(), args.study.resolve().parents[2]
    wall, cpu = time.perf_counter(), time.process_time()
    report = dict(schema="digital-confirmation-independent-review-v1", audit_started_utc=datetime.now(timezone.utc).isoformat(),
                  auditor_source_sha256=digest(__file__), fatal_issues=[], discrepancies=[], numeric_checks=0,
                  max_absolute_numeric_difference=0., absolute_tolerance=1e-12, relative_tolerance=1e-10,
                  arithmetic="Independent streaming JSON decoding, math.fsum fit/world means and sample variance; scipy.special.stdtrit. No analyze.py or task/model module import.")
    hashes, counts = {}, defaultdict(int)

    def require(condition, message):
        if not condition:
            raise ValueError(message)

    def track(path):
        path = Path(path).resolve()
        current = digest(path)
        if str(path) in hashes:
            require(hashes[str(path)] == current, "input changed during audit: " + str(path))
        hashes[str(path)] = current
        return current

    def compare(actual, expected, label):
        if isinstance(expected, dict):
            for key, value in expected.items():
                require(key in actual, "missing recorded key: " + label + "/" + key)
                compare(actual[key], value, label + "/" + key)
        elif isinstance(expected, list):
            require(isinstance(actual, list) and len(actual)==len(expected), "recorded list membership mismatch: " + label)
            for i, (x, y) in enumerate(zip(actual, expected)):
                compare(x, y, label + "/" + str(i))
        elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
            require(isinstance(actual, (int, float)) and math.isfinite(actual) and math.isfinite(expected), "invalid number: " + label)
            delta = abs(actual-expected)
            report["numeric_checks"] += 1
            report["max_absolute_numeric_difference"] = max(report["max_absolute_numeric_difference"], delta)
            if not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-12):
                report["discrepancies"].append(dict(path=label, recorded=actual, recomputed=expected, absolute_difference=delta))
        elif actual != expected:
            report["discrepancies"].append(dict(path=label, recorded=actual, recomputed=expected))

    try:
        protocol = read(study/"protocol.json")
        source_freeze = read(study/"SOURCE_FREEZE.json")
        seal = read(study/"SEALED_MODEL_FREEZE.json")
        analysis_path = study/"evidence/CONFIRMATION_ANALYSIS.json"
        analysis = read(analysis_path)
        launch = read(study/"evidence/CONFIRMATION_LAUNCH.json")
        for path in (study/"protocol.json", study/"SOURCE_FREEZE.json", study/"SEALED_MODEL_FREEZE.json",
                     study/"analyze.py", study/"evidence/CONFIRMATION_LAUNCH.json", analysis_path):
            track(path)
        fits = protocol["fits"]
        require(len(fits)==16 and len(set(fits))==16, "all16 registered independent fits required")
        require(protocol==source_freeze["protocol"]==seal["protocol"], "frozen protocol identity mismatch")
        for name, sha in source_freeze["source_sha256"].items():
            require(track(repo/name)==sha, "frozen scientific source changed: " + name)
        require(protocol["statistics"]["primary_intervals"]==8 and protocol["statistics"]["practical_utility_margin"]==.02, "registered threshold/allocation changed")
        root = runs/"confirmation"
        require({p.name for p in root.glob("fit_*") if p.is_dir()}=={f"fit_{f}" for f in fits}, "confirmation fit directories differ")
        processes, start_rows = [], []
        for fit in fits:
            receipt_path = root/f"process_receipts/fit_{fit}.json"
            track(receipt_path)
            process = read(receipt_path)
            require(process["fit"]==fit and process["stage"]=="confirm" and process["returncode"]==0, "failed or missing confirmation process: " + str(fit))
            track(root/f"fit_{fit}/FINISHED.json")
            require(read(root/f"fit_{fit}/FINISHED.json")["fit"]==fit, "confirmation FINISHED identity mismatch")
            path = root/f"fit_{fit}/STARTED.json"
            track(path)
            started = read(path)
            require(started["fit"]==fit and started["model_freeze_sha256"]==digest(study/"SEALED_MODEL_FREEZE.json")
                    and started["published_model_commit"]==seal["verified_remote_commit"]
                    and started["confirmation_preexisting"] is False and utc(started["utc"])>=utc(launch["utc"]), "fresh STARTED provenance mismatch")
            start_rows.append(dict(started))
        means, worlds, runtime_index = {}, set(), {}
        structure_max = defaultdict(float)
        for fit in fits:
            folder = root/f"fit_{fit}"
            track(folder/"summary.json")
            summaries = read(folder/"summary.json")
            summary_index = {}
            for row in summaries:
                key = (row["split"], row["candidate"], row["controller"])
                require(row["fit"]==fit and key not in summary_index, "duplicate or wrong summary fit")
                summary_index[key] = row
            expected_keys = {(s, c, k) for s in ("iid", "ood") for c in CANDIDATES+["bayes"] for k in ("fixed", "value")}
            require(set(summary_index)==expected_keys, "summary arm coverage incomplete")
            track(folder/"runtime.json")
            for block in read(folder/"runtime.json"):
                for row in block["models"]:
                    key = (fit, block["split"], row["candidate"], row["controller"])
                    require(key not in runtime_index, "duplicate runtime record")
                    runtime_index[key] = row
            for split in ("iid", "ood"):
                cohort_path = folder/f"{split}_cohort.json"
                track(cohort_path)
                cohort = read(cohort_path)
                records = cohort["records"]
                require(len(records)==protocol[f"{split}_worlds"]==96, "cohort size differs")
                order = {r["id"]: i for i, r in enumerate(records)}
                require(len(order)==96, "duplicate cohort world")
                labels = {}
                for record in records:
                    require(record["fit"]==fit and record["split"]==split, "cohort identity mismatch")
                    labels[record["id"]] = read(Path(record["folder"])/"evaluator.json")["label"]
                for name, sha in cohort["files"].items():
                    require(digest(folder/"worlds"/name)==sha, "cohort content hash mismatch")
                    counts["cohort_file_hashes"] += 1
                raw_path = folder/f"{split}_episodes.json.gz"
                track(raw_path)
                group_values, group_worlds = {}, {}
                for candidate in CANDIDATES+["bayes"]:
                    for controller in ("fixed", "value"):
                        key = (split, candidate, controller)
                        group_values[key] = defaultdict(list)
                        group_worlds[key] = set()
                for row in array_records(raw_path):
                    key = (row["split"], row["candidate"], row["controller"])
                    require(row["fit"]==fit and key in group_values and row["label_access_after_terminal"] is True, "raw identity/scoring flag mismatch")
                    world = row["world"]
                    require(world in order and world not in group_worlds[key], "missing, extra or duplicate paired world")
                    group_worlds[key].add(world)
                    worlds.add((fit, split, world))
                    require(row["seed"]==protocol["execution_seed_base"]+fit*100000+({"iid":10000,"ood":20000}[split])+order[world], "execution seed pairing differs")
                    metrics, state, decisions = row["metrics"], row["final_state"], row["decisions"]
                    require(state["terminal"] and decisions and decisions[-1]["after"]==state, "raw terminal state mismatch")
                    submitted = state["submitted"]
                    reward = 0 if submitted is None else (1 if submitted==labels[world] else -1)
                    reconstructed = dict(reward=reward, utility=reward-state["charges"], charges=state["charges"],
                                         correct=float(submitted==labels[world]), submitted=submitted is not None,
                                         reads_requested=3-state["budget"], reads_completed=len(state["history"]),
                                         elapsed=state["elapsed"], decisions=len(decisions),
                                         events=sum(bool(d["event"]["event"]) for d in decisions),
                                         recoveries=sum(bool(d["event"]["recovery"]) for d in decisions))
                    compare(metrics, reconstructed, f"episode/{fit}/{split}/{world}/{key[1]}/{key[2]}")
                    require(set(metrics)==set(summary_index[key]["metrics"]), "raw/summary metric columns differ")
                    for metric, value in metrics.items():
                        require(isinstance(value,(float,int)) and math.isfinite(value), "nonfinite episode metric")
                        group_values[key][metric].append(float(value))
                    structure_max[(key[1],key[2])] = max(structure_max[(key[1],key[2])], metrics["terminal_structure_error"])
                    counts["episodes"] += 1
                    counts["decisions"] += len(decisions)
                for key, values in group_values.items():
                    require(group_worlds[key]==set(order), "common within-fit world pairing differs")
                    require(summary_index[key]["worlds"]==96, "recorded summary world count differs")
                    computed = {name:average(v) for name,v in values.items()}
                    compare(summary_index[key]["metrics"], computed, f"summary/{fit}/{key}")
                    counts["summary_metric_means"] += len(computed)
                    means[(fit,*key)] = computed
                track(raw_path)
            print(json.dumps(dict(stage="independent_raw_audit",fit=fit,cumulative_episodes=counts["episodes"])),flush=True)
        require(counts["episodes"]==153600 and len(worlds)==3072 and len(means)==1600, "complete registered experiment cardinality differs")
        require(set(runtime_index)==set(means), "runtime record coverage differs")
        compare(analysis["independently_recomputed_raw_means"],counts["summary_metric_means"],"recorded_raw_mean_count")
        compare(analysis["fits"],fits,"analysis_fit_order")

        def value(fit,split,candidate,controller="value",metric="utility"):
            return means[(fit,split,candidate,controller)][metric]

        def contrast(fit,split,name,metric="utility"):
            return average([value(fit,split,a,metric=metric)-value(fit,split,b,metric=metric) for a,b in COMPARISONS[name]])

        recorded_primary = {(r["split"],r["contrast"]):r for r in analysis["primary_results"]}
        require(len(recorded_primary)==len(analysis["primary_results"])==8,"primary result inventory differs")
        primary = []
        for split in ("iid","ood"):
            for name in COMPARISONS:
                recomputed = interval(fits,[contrast(f,split,name) for f in fits],8,True)
                compare(recorded_primary[split,name],recomputed,f"primary/{split}/{name}")
                diagnostics = recorded_primary[split,name]["descriptive_diagnostic_differences"]
                computed_diagnostics = {m:average([contrast(f,split,name,m) for f in fits]) for m in diagnostics}
                compare(diagnostics,computed_diagnostics,f"primary_diagnostics/{split}/{name}")
                primary.append(dict(split=split,contrast=name,**recomputed,descriptive_diagnostic_differences=computed_diagnostics))
        compare(analysis["all_eight_benefit_gates"],all(p["benefit_gate"] for p in primary),"all_eight_gates")
        controller_rows = []
        recorded_controller = {(r["split"],r["candidate"]):r for r in analysis["controller_value_minus_fixed"]}
        require(len(recorded_controller)==50,"controller effect inventory differs")
        for split in ("iid","ood"):
            for candidate in CANDIDATES+["bayes"]:
                result = interval(fits,[value(f,split,candidate)-value(f,split,candidate,"fixed") for f in fits])
                compare(recorded_controller[split,candidate],result,f"controller/{split}/{candidate}")
                controller_rows.append(dict(split=split,candidate=candidate,descriptive=True,**result))
        for row in analysis["family_terminal_constraints"]:
            result=interval(fits,[value(f,row["split"],row["family"]+"__structured_off")-value(f,row["split"],row["family"]+"__free_off") for f in fits])
            compare(row,result,f"family_terminal/{row['split']}/{row['family']}")
        for row in analysis["two_by_two"]:
            arm={a:[] for a in "ABCD"}
            delta={a:[] for a in ("B-A","D-C","C-A","D-B","interaction")}
            for fit in fits:
                a,b,c,d=[value(fit,row["split"],family+"__"+row["method"],controller) for family,controller in (("ordinary_bank","fixed"),("ordinary_bank","value"),("first_passage_bank","fixed"),("first_passage_bank","value"))]
                for k,v in zip("ABCD",(a,b,c,d)):arm[k].append(v)
                for k,v in zip(delta,(b-a,d-c,c-a,d-b,(d-c)-(b-a))):delta[k].append(v)
            compare(row["arm_fit_means"],arm,"factorial_arm_means")
            compare(row["contrasts"],{k:interval(fits,v) for k,v in delta.items()},"factorial_contrasts")
        recorded_means={(r["split"],r["candidate"],r["controller"]):r for r in analysis["means"]}
        require(len(recorded_means)==100,"pooled descriptive mean inventory differs")
        task_panel=[]
        for key,row in recorded_means.items():
            split,candidate,controller=key
            metrics={m:average([means[(f,*key)][m] for f in fits]) for m in row["metrics"]}
            compare(row,dict(metrics=metrics,fit_utility=[means[(f,*key)]["utility"] for f in fits]),"mean_panel/"+str(key))
            setup=[runtime_index[(f,*key)]["model_setup_cpu_seconds"] for f in fits]
            task_panel.append(dict(split=split,candidate=candidate,controller=controller,metrics=metrics,
                                   model_setup_cpu_seconds_per_fit=average(setup),
                                   complete_model_execution_cpu_seconds_per_world=metrics["execution_cpu_seconds"]+average(setup)/96,
                                   diagnostic_cpu_seconds_per_world=metrics["diagnostic_cpu_seconds"]))
        training_cost=[]
        stored_cost={r["candidate"]:r for r in analysis["training_cost_panel"]}
        require(set(stored_cost)==set(CANDIDATES),"training cost arm inventory differs")
        for candidate in CANDIDATES:
            receipts=[]
            for fit in fits:
                path=runs/f"formal_training/fit_{fit}/training/{candidate}.json.gz"
                require(track(path)==seal["training_receipts_sha256"][f"{fit}/{candidate}"],"sealed training receipt changed")
                receipt=read(path);receipts.append(receipt)
                require(receipt["fit"]==fit and receipt["spec"]["id"]==candidate and receipt["batch_size"]==128,"training receipt identity mismatch")
                require(receipt["spec"]["budget"]==("cpu" if candidate in CPU else "updates"),"training budget kind differs")
                if candidate in CPU:
                    require(receipt["training_cpu_budget"]==16. and receipt["learning_cpu_seconds"]>=16.,"CPU arm short budget")
                    compare(receipt["cpu_budget_overshoot"],receipt["learning_cpu_seconds"]-16.,"cpu_budget_overshoot")
                else:require(receipt["optimizer_updates"]==240,"equal-update arm update count differs")
            reconstructed=dict(fits=fits,budget="cpu" if candidate in CPU else "updates",
                               learning_cpu_seconds=[r["learning_cpu_seconds"] for r in receipts],setup_cpu_seconds=[r["setup_cpu_seconds"] for r in receipts],
                               optimizer_updates=[r["optimizer_updates"] for r in receipts],overshoot_seconds=[r["cpu_budget_overshoot"] for r in receipts],
                               nominal_cpu_budget=16. if candidate in CPU else None,capacity_by_fit=[r["capacity"] for r in receipts])
            compare(stored_cost[candidate],reconstructed,"training_cost/"+candidate)
            training_cost.append(dict(candidate=candidate,budget=reconstructed["budget"],
                                      learning_cpu_seconds_mean=average(reconstructed["learning_cpu_seconds"]),
                                      setup_cpu_seconds_mean=average(reconstructed["setup_cpu_seconds"]),
                                      learning_cpu_seconds_range=[min(reconstructed["learning_cpu_seconds"]),max(reconstructed["learning_cpu_seconds"])],
                                      optimizer_updates_range=[min(reconstructed["optimizer_updates"]),max(reconstructed["optimizer_updates"])],
                                      optimizer_updates_mean=average(reconstructed["optimizer_updates"]),
                                      overshoot_seconds_mean=average(reconstructed["overshoot_seconds"]),overshoot_seconds_max=max(reconstructed["overshoot_seconds"]),
                                      capacity_by_fit=reconstructed["capacity_by_fit"]))
        for fit in fits:
            for folder,stage in ((runs/"formal_training","train"),(root,"confirm")):
                path=folder/f"process_receipts/fit_{fit}.json";track(path);row=read(path)
                require(row["fit"]==fit and row["stage"]==stage and row["returncode"]==0,"registered worker failed")
                processes.append(row)
        for fit in protocol["development_fits"]:
            path=runs/f"development_v2/process_receipts/fit_{fit}.json";track(path);row=read(path)
            require(row["stage"]=="development" and row["returncode"]==0,"successful development receipt missing")
            processes.append(row)
        failed_attempts=[]
        for path in sorted((runs/"development/process_receipts").glob("fit_*.json")):
            track(path);row=read(path);failed_attempts.append(row);processes.append(row)
        compare(analysis["external_process_receipts"],processes,"external_process_receipts")
        totals={stage:math.fsum(row["whole_process_cpu_seconds"] for row in processes if row["stage"]==stage) for stage in {r["stage"] for r in processes}}
        for process in processes:compare(process["whole_process_cpu_seconds"],process["user_cpu_seconds"]+process["system_cpu_seconds"],"wait4_components")
        compare(analysis["external_process_cpu_by_stage"],totals,"stage_CPU_totals")
        compare(analysis["external_process_cpu_total"],math.fsum(totals.values()),"full_registered_worker_CPU")
        require(analysis["cost_superiority_established"] is False and analysis["cost_superiority_gate"] is False,"unregistered cost-superiority claim")
        for path,sha in list(hashes.items()):require(digest(path)==sha,"input changed before audit completion: "+path)
        require(not any(name.endswith(".analyze") or name.startswith("tools.hcsn") or name=="torch" for name in sys.modules),"scientific implementation was imported")
        report.update(registered_fits=fits,independent_fit_unit=True,counts=dict(counts,distinct_fit_worlds=len(worlds),fit_arm_split_controller_means=len(means)),
                      confirmation_started=start_rows,common_published_model_commit=seal["verified_remote_commit"],seal_sha256=digest(study/"SEALED_MODEL_FREEZE.json"),
                      raw_and_input_sha256=hashes,source_sha256=source_freeze["source_sha256"],primary_results=primary,
                      all_eight_benefit_gates=all(p["benefit_gate"] for p in primary),controller_value_minus_fixed=controller_rows,
                      descriptive_task_quality_and_execution_cost=task_panel,training_cost=training_cost,
                      structured_terminal_max_error=[dict(candidate=k[0],controller=k[1],maximum=v) for k,v in sorted(structure_max.items())],
                      external_process_cpu_by_stage=totals,external_process_cpu_total=math.fsum(totals.values()),
                      complete_registered_workers=len(processes),retained_failed_development_attempts=len(failed_attempts),
                      analysis_output_sha256=digest(analysis_path),analysis_outer_receipt=read(runs/"analysis_outer/frozen_analysis.json"),
                      no_new_significance_claims=True,cost_superiority_established=False,
                      cost_scope="Worker CPU includes complete OS processes; setup/learning/execution are nested decompositions. Model execution panel adds model setup once to episode execution and separately reports diagnostics. Bayes/fixed contains unused Q computation and is an unoptimized reference. No deployment amortization or hardware-energy superiority is established.",
                      causal_scope="Terminal primary averages only five inherited families. Accumulator free_off versus structured_on combines terminal structure and occupancy; no isolated six-family terminal effect is claimed.")
        report["discrepancy_count"]=len(report["discrepancies"])
        report["reproduced_within_declared_tolerances"]=not report["discrepancies"]
        report["bitwise_numeric_equality"]=report["max_absolute_numeric_difference"]==0.
        require(not report["discrepancies"],"nonzero independently detected discrepancies")
    except Exception as error:
        report["fatal_issues"].append(dict(type=type(error).__name__,message=str(error)))
        report["reproduced_within_declared_tolerances"]=False
    finally:
        report.update(audit_finished_utc=datetime.now(timezone.utc).isoformat(),audit_process_cpu_seconds=time.process_time()-cpu,audit_wall_seconds=time.perf_counter()-wall)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open("x") as stream:
            json.dump(report,stream,sort_keys=True,indent=2,allow_nan=False);stream.write("\n")
        print(json.dumps(dict(output=str(args.output),sha256=digest(args.output),fatal_issues=report["fatal_issues"],discrepancy_count=len(report["discrepancies"]),max_absolute_numeric_difference=report["max_absolute_numeric_difference"],counts=report.get("counts")),sort_keys=True),flush=True)
        if report["fatal_issues"] or report["discrepancies"]:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
