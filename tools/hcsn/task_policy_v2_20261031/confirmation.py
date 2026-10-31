"""Frozen paired confirmation; never invoked by campaign.prepare."""
import json
from pathlib import Path
import re
import time
import traceback

import numpy as np
from scipy.stats import t as student_t

from ..task_value_factorial_20261030.task import ContentAdapter, build_cohort, save
from .campaign import ROOT, packed, sha
from .execution import diagnose, rollout


def verified_freeze(prepared, receipt_path):
    receipt = json.loads(receipt_path.read_text())
    manifest_path = prepared/"PREPARED_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    if (receipt.get("repository") != "TrillionniumFoundation/hepta-private-ci"
            or not re.fullmatch(r"[0-9a-f]{40}", receipt.get("commit", ""))
            or receipt.get("remote_manifest_sha256") != sha(manifest_path)
            or receipt.get("remote_verified") is not True):
        raise ValueError("An externally verified remote freeze receipt matching the prepared manifest is required")
    for relative, expected in manifest["files"].items():
        if sha(prepared/relative) != expected:
            raise ValueError(("Prepared byte changed", relative))
    for relative, expected in manifest["source_sha256"].items():
        if sha(ROOT/relative) != expected:
            raise ValueError(("Executable/source byte changed after preparation", relative))
    return dict(receipt=receipt, receipt_sha256=sha(receipt_path), manifest_sha256=sha(manifest_path),
                scope="Remote publication independently verified by orchestrator; this runner verifies the supplied identity and every local prepared/source byte")


def interval(values):
    values = np.asarray(values,float)
    mean = float(values.mean())
    se = float(values.std(ddof=1)/np.sqrt(len(values)))
    critical = float(student_t.ppf(.975,len(values)-1))
    probability = float(2*student_t.sf(abs(mean/se),len(values)-1)) if se else (0. if mean else 1.)
    return dict(mean=mean, lower=mean-critical*se, upper=mean+critical*se,
                standard_error=se, p_two_sided=probability, seed_values=values.tolist(), df=len(values)-1)


def summary(rows):
    return dict(sessions=len(rows), utility=float(np.mean([r["score"]["utility"] for r in rows])),
        correct_fraction=float(np.mean([r["score"]["correct_jobs"]/2 for r in rows])),
        completed_fraction=float(np.mean([r["score"]["completed_jobs"]/2 for r in rows])),
        wrong_fraction=float(np.mean([(r["score"]["completed_jobs"]-r["score"]["correct_jobs"])/2 for r in rows])),
        conditional_accuracy=(sum(r["score"]["correct_jobs"] for r in rows)/sum(r["score"]["completed_jobs"] for r in rows)
                              if sum(r["score"]["completed_jobs"] for r in rows) else None),
        query_cost=float(np.mean([r["score"]["query_cost"] for r in rows])),
        latency_cost=float(np.mean([r["score"]["latency_cost"] for r in rows])),
        reads=float(np.mean([r["counts"]["READ"] for r in rows])),
        task_elapsed=float(np.mean([r["task_elapsed"] for r in rows])),
        teacher_regret=float(np.mean([r["teacher_regret"] for r in rows])),
        owner_cpu_seconds=float(np.mean([r["cpu_seconds"] for r in rows])),
        full_cpu_seconds=float(np.mean([r["cpu_seconds"]+r["raw_persistence_cpu_seconds"] for r in rows])),
        owner_wall_seconds=float(np.mean([r["wall_seconds"] for r in rows])),
        controller_cpu_seconds=float(np.mean([r["controller_cpu_seconds"] for r in rows])))


def analyze(reports, prepared_summary, protocol):
    preparation = {r["seed"]:r for r in prepared_summary["seeds"]}
    result = {}
    for split in ("test", "ood"):
        differences = {}
        for metric in ("utility","correct_fraction","wrong_fraction","completed_fraction","teacher_regret","full_cpu_seconds"):
            differences[metric] = interval([r["splits"][split]["nonzero_residual"][metric]-
                r["splits"][split]["one_read"][metric] for r in reports])
        sensitivities = {}
        for horizon in protocol["amortization_sessions"]:
            for price in protocol["cpu_prices_utility_per_second"]:
                values = []
                for report in reports:
                    baseline, learned = (report["splits"][split][p] for p in ("one_read","nonzero_residual"))
                    extra_training = preparation[report["seed"]]["residual_incremental_prepare_cpu_seconds"]
                    extra_training += report["model_load_cpu_seconds"]
                    values.append(learned["utility"]-baseline["utility"]-price*(learned["full_cpu_seconds"]-
                        baseline["full_cpu_seconds"]+extra_training/horizon))
                sensitivities[f"H={horizon},CPU={price}"] = interval(values)
        result[split] = dict(paired=differences, cpu_sensitivity=sensitivities,
            quality_noninferior=differences["correct_fraction"]["lower"] > -protocol["quality_noninferiority_margin"],
            one_read_teacher_regret=interval([r["splits"][split]["one_read"]["teacher_regret"] for r in reports]),
            residual_teacher_regret=interval([r["splits"][split]["nonzero_residual"]["teacher_regret"] for r in reports]))
    ordered = sorted(result, key=lambda split:result[split]["paired"]["utility"]["p_two_sided"])
    adjusted = 0.
    for rank, split in enumerate(ordered):
        adjusted = min(1.,max(adjusted,(2-rank)*result[split]["paired"]["utility"]["p_two_sided"]))
        result[split]["utility_holm_p"] = adjusted
    key = f"H={protocol['primary_amortization_sessions']},CPU={protocol['primary_cpu_price']}"
    gates = dict(all_nonzero_models_improve_validation_zero=all(r["nonzero_improves_zero"] for r in preparation.values()),
        positive_utility_both_splits=all(r["paired"]["utility"]["lower"] > 0 and r["utility_holm_p"] < .05 for r in result.values()),
        quality_noninferior_both_splits=all(r["quality_noninferior"] for r in result.values()),
        positive_full_cpu_adjusted_both_splits=all(r["cpu_sensitivity"][key]["lower"] > 0 for r in result.values()))
    return dict(splits=result, gates=gates, task_level_learned_admission=all(gates.values()),
        main_activation=False, scope="Prospective task-policy comparison; no analytic-cell causal or production/energy admission")


def confirm(prepared, out, freeze_receipt):
    # This validation occurs before mkdir, RNG use or cohort generation.
    freeze = verified_freeze(prepared, freeze_receipt)
    out.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter(), time.process_time()
    save(out/"VERIFIED_FREEZE.json", freeze)
    protocol = json.loads((prepared/"PROTOCOL.json").read_text())
    preparation = json.loads((prepared/"PREPARE_SUMMARY.json").read_text())
    reports, payload_hashes, current = [], set(), {}
    try:
        for seed in protocol["seeds"]:
            folder = out/f"seed{seed}"
            folder.mkdir()
            train = json.loads((prepared/f"seed{seed}"/"PREPARE_SEED.json").read_text())
            adapter = ContentAdapter()
            confusion = np.asarray(train["confusion"],float)
            start, start_cpu = time.perf_counter(), time.process_time()
            checkpoint = json.loads((prepared/train["models"]["nonzero"]["path"]).read_text())
            model_load_wall, model_load_cpu = time.perf_counter()-start, time.process_time()-start_cpu
            report = dict(seed=seed, splits={}, model_load_cpu_seconds=model_load_cpu,
                          model_load_wall_seconds=model_load_wall, adapter_setup=adapter.setup)
            for split in ("test","ood"):
                spec = protocol if split == "test" else dict(protocol,**protocol["ood"])
                cohort = build_cohort(folder/split, split, seed, protocol[f"{split}_sessions"], spec)
                if payload_hashes.intersection(cohort["payload_hashes"]):
                    raise ValueError("Duplicate confirmation packet bytes across splits/seeds")
                payload_hashes.update(cohort["payload_hashes"])
                packed(folder/f"{split}_COHORT.json.gz", cohort)
                rows, order = [], np.random.default_rng(seed*10000+(201 if split == "test" else 301))
                for session in cohort["records"]:
                    for policy in order.permutation(protocol["policies"]):
                        current = dict(seed=seed, split=split, session=session, policy=str(policy))
                        row = rollout(session, adapter, confusion, protocol["multiplier"], protocol["latency_price"],
                            "residual" if policy == "nonzero_residual" else policy, checkpoint,
                            numeric_contract=protocol["numeric_contract"])
                        row["policy"] = str(policy)
                        begin, begin_cpu = time.perf_counter(), time.process_time()
                        packed(folder/f"{split}_raw_{len(rows):04d}.json.gz", row)
                        row["raw_persistence_cpu_seconds"] = time.process_time()-begin_cpu
                        row["raw_persistence_wall_seconds"] = time.perf_counter()-begin
                        rows.append(row)
                meta = {s["id"]:json.loads((Path(s["folder"])/"public.json").read_text()) for s in cohort["records"]}
                diagnosis = diagnose(rows, meta, confusion, protocol["multiplier"], protocol["latency_price"])
                for row, regret in zip(rows,diagnosis["rows"]):
                    row["teacher_regret"] = regret["cumulative_regret"]
                packed(folder/f"{split}_RUNS_AND_DIAGNOSIS.json.gz", dict(rows=rows, diagnosis=diagnosis))
                report["splits"][split] = {policy:summary([r for r in rows if r["policy"] == policy])
                                             for policy in protocol["policies"]}
                print(json.dumps(dict(seed=seed, split=split, metrics=report["splits"][split])), flush=True)
            save(folder/"CONFIRM_SEED.json", report)
            reports.append(report)
        result = analyze(reports, preparation, protocol)
        result.update(freeze=freeze, reports=reports, total_cpu_seconds=time.process_time()-cpu,
                      total_wall_seconds=time.perf_counter()-wall, packet_count=len(payload_hashes),
                      scope_timing="Whole confirmation includes generation, policy runs, persistence and teacher diagnosis; deployment CPU excludes generation/teacher diagnosis, separately retained")
        save(out/"CONFIRMATION.json", result)
        save(out/"CONFIRMATION_MANIFEST.json", dict(files={str(p.relative_to(out)):sha(p) for p in sorted(out.rglob("*")) if p.is_file()}))
        print(json.dumps(dict(out=str(out), gates=result["gates"], main_activation=False)), flush=True)
        return result
    except Exception as exc:
        save(out/"FAILED_CONFIRMATION.json", dict(current=current, error=repr(exc), traceback=traceback.format_exc(),
            total_cpu_seconds=time.process_time()-cpu, total_wall_seconds=time.perf_counter()-wall,
            task_level_learned_admission=False, main_activation=False, replacement_or_retuning_allowed=False))
        raise
