"""Confirmation is called only after the unchanged development gate passes."""
import json
import time
import numpy as np
from scipy.stats import t as student_t
from identity import HERE, protocol, save, sha
from owner import Owner
from oracle import Bellman
from network import action

ACTIONS = ("STOP", "SKIP", "READ", "FIRE")


def run_confirmation(manifest, development, adapter, calibrations):
    p, rows = protocol(), []
    models = {}
    for row in development["runs"]:
        arrays = dict(np.load(HERE / row["selected"]["checkpoint"]))
        parameters = {name: arrays[name] for name in ("w1", "b1", "w2", "b2")}
        models[(row["seed"], row["family"])] = (parameters, arrays["feature_mean"], arrays["feature_scale"])
    names = p["families"]+["model_dp"]
    for index, record in enumerate(manifest["records"]):
        confusion = np.asarray(calibrations[str(record["seed"])])
        rotation = (index+record["seed"]) % len(names)
        for name in names[rotation:]+names[:rotation]:
            start, cpu = time.perf_counter(), time.process_time()
            owner = Owner(HERE / record["folder"], adapter, confusion, p["multiplier"])
            dp = Bellman(owner.meta, confusion, p["multiplier"]) if name == "model_dp" else None
            decision_wall = 0.
            while not owner.terminal:
                begin = time.perf_counter()
                if dp is not None:
                    selected = int(np.argmax(dp.q(owner.job, owner.tick, owner.budget, owner.posterior)))
                else:
                    parameters, mean, scale = models[(record["seed"], name)]
                    selected = action(parameters, mean, scale, owner.meta, owner.job, owner.tick,
                        owner.budget, owner.posterior, confusion, p["multiplier"])
                decision_wall += time.perf_counter()-begin
                owner.act(ACTIONS[selected])
            path = HERE / "traces" / f"{record['id']}_{name}.json"
            save(path, owner.snapshot())
            elapsed, elapsed_cpu = time.perf_counter()-start, time.process_time()-cpu
            labels = json.loads((HERE / record["folder"] / "evaluator_labels.json").read_text())["labels"]
            correct = sum(a["prediction"] == labels[a["job"]] for a in owner.answers)
            reward = 2*correct-len(owner.answers)
            rows.append(dict(session=record["id"], seed=record["seed"], family=name,
                utility=reward-owner.charged_cost, reward=reward, charged_cost=owner.charged_cost,
                completed_jobs=len(owner.answers), correct_jobs=correct, counts=owner.counts,
                components=owner.times, metadata_wall_seconds=owner.metadata_wall_seconds,
                decision_wall_seconds=decision_wall, total_wall_seconds=elapsed, total_cpu_seconds=elapsed_cpu,
                trace=str(path.relative_to(HERE)), trace_sha256=sha(path), label_access_after_terminal=True))
    summaries = []
    for name in names:
        group = [r for r in rows if r["family"] == name]
        summaries.append(dict(family=name, mean_utility=float(np.mean([r["utility"] for r in group])),
            mean_completed_jobs=float(np.mean([r["completed_jobs"] for r in group])),
            correct_fraction_of_possible_jobs=sum(r["correct_jobs"] for r in group)/(2*len(group)),
            mean_wall_seconds=float(np.mean([r["total_wall_seconds"] for r in group])),
            mean_reads=float(np.mean([r["counts"]["READ"] for r in group])),
            total_wall_seconds=sum(r["total_wall_seconds"] for r in group),
            total_cpu_seconds=sum(r["total_cpu_seconds"] for r in group)))
    differences = []
    for seed in p["seeds"]:
        means = {name: np.mean([r["utility"] for r in rows if r["seed"] == seed and r["family"] == name]) for name in p["families"][:2]}
        differences.append(float(means["full_value"]-means["ordinary_boundary"]))
    mean = float(np.mean(differences))
    radius = float(student_t.ppf(.975, 4)*np.std(differences, ddof=1)/np.sqrt(5))
    primary = dict(paired_seed_differences=differences, mean=mean, interval95=[mean-radius, mean+radius],
                   benefit_passed=mean-radius > 0. and mean >= .02)
    result = dict(status="completed", rows=rows, summaries=summaries, primary=primary,
        gate_sha256=sha(HERE / "gate.json"), heldout_manifest_sha256=sha(HERE / "heldout_manifest.json"))
    common = development["data"]["generation_wall_seconds"]+development["source_import_wall_seconds"]+development["adapter_setup"]["load_wall_seconds"]
    common += sum(r["calibration_wall_seconds"]+r["oracle_state_and_serialization_wall_seconds"] for r in development["seed_costs"])
    sensitivity = []
    for summary in summaries:
        own_fit = sum(r["total_wall_seconds"] for r in development["runs"] if r["family"] == summary["family"])
        setup = common+own_fit+development["numerical_validation"]["wall_seconds"]
        for sessions in p["setup_amortization_sessions"]:
            for penalty in p["runtime_penalty_per_second"]:
                sensitivity.append(dict(family=summary["family"], sessions=sessions, penalty=penalty,
                    setup_wall_seconds=setup, utility=summary["mean_utility"]-penalty*(summary["mean_wall_seconds"]+setup/sessions)))
    result["runtime_and_setup_sensitivity"] = sensitivity
    save(HERE / "confirmation.json", result)
    return result
