"""Execute frozen-controller fitting and real paired local-owner sessions."""
import time
IMPORT_START = time.perf_counter()
import argparse
import json
import os
from pathlib import Path
import traceback
import numpy as np
from scipy.stats import t as student_t
from common import HERE, ACTIONS, save, sha, freeze, verify, protocol
from adapter import ContentAdapter
from data import prepare
from learn import calibrate, fit_seed, predict
from oracle import Bellman, feasible, myopic_action
from owner import Owner
IMPORT_SECONDS = time.perf_counter()-IMPORT_START


def choose(name, owner, model, dp):
    args = (owner.meta, owner.job, owner.tick, owner.budget, owner.posterior, owner.confusion, owner.multiplier)
    if name in model:
        return predict(model[name], *args)
    if name == "model_dp":
        values = dp.q(owner.job, owner.tick, owner.budget, owner.posterior)
        return ACTIONS[int(np.argmax(values))]
    if name == "myopic":
        return myopic_action(*args)
    if name == "immediate_stop":
        return "STOP"
    if name == "fixed_two_reads":
        valid = feasible(owner.meta, owner.job, owner.tick, owner.budget)
        return "READ" if valid[2] and owner.reads_in_job < 2 else "FIRE" if valid[3] else "STOP"
    raise ValueError(name)


def episode(record, name, multiplier, adapter, confusion, models):
    start, cpu = time.perf_counter(), time.process_time()
    owner = Owner(HERE / record["folder"], adapter, confusion, multiplier)
    dp = Bellman(owner.meta, confusion, multiplier) if name == "model_dp" else None
    policy_wall, policy_cpu = 0., 0.
    while not owner.terminal:
        begin, begin_cpu = time.perf_counter(), time.process_time()
        action = choose(name, owner, models, dp)
        policy_wall += time.perf_counter()-begin
        policy_cpu += time.process_time()-begin_cpu
        owner.act(action)
    trace_path = HERE / "traces" / f"{record['id']}_{name}_price{multiplier}.json"
    serialization_start = time.perf_counter()
    save(trace_path, owner.snapshot())
    serialization_seconds = time.perf_counter()-serialization_start
    elapsed, elapsed_cpu = time.perf_counter()-start, time.process_time()-cpu
    # Labels are opened only after the owner has terminated and persisted its trace.
    labels = json.loads((HERE / record["folder"] / "evaluator_labels.json").read_text())["labels"]
    correct = sum(a["prediction"] == labels[a["job"]] for a in owner.answers)
    reward = 2*correct-len(owner.answers)
    return dict(session=record["id"], seed=record["seed"], policy=name, multiplier=multiplier,
                reward=reward, charged_read_cost=owner.charged_cost, utility=reward-owner.charged_cost,
                completed_jobs=len(owner.answers), correct_jobs=correct, potential_jobs=2,
                counts=owner.counts, components=owner.times, metadata_wall_seconds=owner.metadata_wall_seconds,
                policy_wall_seconds=policy_wall, policy_cpu_seconds=policy_cpu,
                trace_serialization_wall_seconds=serialization_seconds,
                e2e_wall_seconds=elapsed, e2e_cpu_seconds=elapsed_cpu,
                trace=str(trace_path.relative_to(HERE)), trace_sha256=sha(trace_path),
                label_access_after_terminal=True)


def summarize(rows, setup):
    p = protocol()
    summaries, contrasts = [], []
    for multiplier in p["cost_multipliers"]:
        for name in p["policies"]:
            group = [r for r in rows if r["policy"] == name and r["multiplier"] == multiplier]
            seed_means = {str(seed): float(np.mean([r["utility"] for r in group if r["seed"] == seed])) for seed in p["seeds"]}
            total_correct = sum(r["correct_jobs"] for r in group)
            total_answers = sum(r["completed_jobs"] for r in group)
            summaries.append(dict(policy=name, multiplier=multiplier, sessions=len(group),
                mean_utility=float(np.mean([r["utility"] for r in group])), seed_mean_utilities=seed_means,
                mean_reward=float(np.mean([r["reward"] for r in group])),
                correct_fraction_of_available_jobs=total_correct/(2*len(group)),
                answered_accuracy=total_correct/total_answers if total_answers else None,
                completed_jobs_per_session=total_answers/len(group),
                mean_READ=float(np.mean([r["counts"]["READ"] for r in group])),
                mean_SKIP=float(np.mean([r["counts"]["SKIP"] for r in group])),
                mean_FIRE=float(np.mean([r["counts"]["FIRE"] for r in group])),
                mean_STOP=float(np.mean([r["counts"]["STOP"] for r in group])),
                mean_wall_seconds=float(np.mean([r["e2e_wall_seconds"] for r in group])),
                median_wall_seconds=float(np.median([r["e2e_wall_seconds"] for r in group])),
                total_cpu_seconds=sum(r["e2e_cpu_seconds"] for r in group),
                total_wall_seconds=sum(r["e2e_wall_seconds"] for r in group),
                actual_packet_reads=sum(r["counts"]["packet_file_reads"] for r in group),
                actual_content_invocations=sum(r["counts"]["content_invocations"] for r in group)))
        paired = []
        for seed in p["seeds"]:
            means = {name: np.mean([r["utility"] for r in rows if r["seed"] == seed and r["multiplier"] == multiplier and r["policy"] == name])
                     for name in ("learned_value", "ordinary_boundary")}
            paired.append(float(means["learned_value"]-means["ordinary_boundary"]))
        mean, se = float(np.mean(paired)), float(np.std(paired, ddof=1)/np.sqrt(len(paired)))
        radius = float(student_t.ppf(1-.05/(2*len(p["cost_multipliers"])), len(paired)-1)*se)
        contrasts.append(dict(multiplier=multiplier, paired_seed_differences=paired, mean=mean,
                              family95=[mean-radius, mean+radius], corrected_positive=mean-radius > 0.))
    primary = next(c for c in contrasts if c["multiplier"] == 1.5)
    common_setup = setup["data_generation_wall_seconds"]+setup["source_import_wall_seconds"]+setup["adapter_load_wall_seconds"]+sum(s["calibration_wall_seconds"] for s in setup["seeds"])
    sensitivity = []
    for item in summaries:
        name = item["policy"]
        training = sum(s["oracle_label_wall_seconds"]+s["fit_by_policy"][name]["wall_seconds"] for s in setup["seeds"]) if name in ("learned_value", "ordinary_boundary", "first_event_value") else 0.
        setup_cost = 0. if name == "immediate_stop" else common_setup+training
        for sessions in p["setup_amortization_sessions"]:
            for penalty in p["runtime_penalty_per_second"]:
                sensitivity.append(dict(policy=name, multiplier=item["multiplier"], amortization_sessions=sessions,
                    runtime_penalty_per_second=penalty, setup_wall_seconds=setup_cost,
                    utility_after_runtime_and_setup=item["mean_utility"]-penalty*(item["mean_wall_seconds"]+setup_cost/sessions)))
    return dict(summaries=summaries, primary_contrasts=contrasts, primary_gate_passed=primary["corrected_positive"],
                runtime_setup_sensitivity=sensitivity,
                interval_scope="Five paired independently generated cohort/controller-fit means; small-sample t assumption, not a universal architecture conclusion",
                setup_allocation="Each deployment-policy estimate includes incurred common data/import/decoder/calibration setup and that readout's fitting plus complete shared oracle-label preparation. No setup charge for the no-work immediate-STOP reference. These counterfactual allocations are not summed to measure actual study total.")


def run():
    verify()
    destination = HERE / "results.json"
    if destination.exists():
        raise RuntimeError("Completed/partial study exists; preserve it and use audit, never rerun exposed results")
    started, cpu = time.perf_counter(), time.process_time()
    manifest = prepare()
    adapter = ContentAdapter()
    setup = dict(data_generation_wall_seconds=manifest["generation_wall_seconds"],
                  data_generation_cpu_seconds=manifest["generation_cpu_seconds"],
                  source_import_wall_seconds=IMPORT_SECONDS,
                  adapter_load_wall_seconds=adapter.setup["load_wall_seconds"], content=adapter.setup, seeds=[])
    p, rows = protocol(), []
    result = dict(complete=False, scientific_freeze_sha256=sha(HERE / "freeze.json"),
                  data_manifest_sha256=sha(HERE / "data_manifest.json"), setup=setup, rows=rows,
                  environment=dict(python=os.sys.version, numpy=np.__version__, affinity=sorted(os.sched_getaffinity(0)),
                                   blas_threads=os.environ.get("OPENBLAS_NUM_THREADS")))
    save(destination, result)
    for seed in p["seeds"]:
        confusion, calibration = calibrate(seed, adapter)
        models, fit = fit_seed(seed, manifest["records"], confusion)
        setup["seeds"].append(dict(seed=seed, calibration_wall_seconds=calibration["wall_seconds"],
            calibration_cpu_seconds=calibration["cpu_seconds"], oracle_label_wall_seconds=fit["oracle_label_wall_seconds"],
            oracle_label_cpu_seconds=fit["oracle_label_cpu_seconds"], fit_wall_seconds=fit["fit_wall_seconds"],
            fit_cpu_seconds=fit["fit_cpu_seconds"], fit_by_policy=fit["fit_by_policy"]))
        for index, record in enumerate(r for r in manifest["records"] if r["seed"] == seed and r["split"] == "test"):
            for multiplier in p["cost_multipliers"]:
                rotation = (seed+index) % len(p["policies"])
                order = p["policies"][rotation:]+p["policies"][:rotation]
                for name in order:
                    rows.append(episode(record, name, multiplier, adapter, confusion, models))
            if (index+1) % 10 == 0:
                save(destination, result)
                print(json.dumps(dict(seed=seed, completed_test_sessions=index+1, policy_sessions=len(rows))), flush=True)
        save(destination, result)
    result.update(complete=True, analysis=summarize(rows, setup),
                  run_wall_seconds=time.perf_counter()-started, run_cpu_seconds=time.process_time()-cpu,
                  total_actual_content_invocations=sum(r["counts"]["content_invocations"] for r in rows)+p["calibration_packets_per_seed"]*len(p["seeds"]))
    verify()
    save(destination, result)
    save(HERE / "analysis.json", result["analysis"])
    print(json.dumps(dict(complete=True, policy_sessions=len(rows), primary_gate=result["analysis"]["primary_gate_passed"],
                          seconds=result["run_wall_seconds"])), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("freeze", "run"))
    action = parser.parse_args().action
    if action == "freeze":
        print(json.dumps(freeze(), indent=2))
    else:
        try:
            run()
        except Exception:
            save(HERE / "failure.json", dict(traceback=traceback.format_exc()))
            raise
