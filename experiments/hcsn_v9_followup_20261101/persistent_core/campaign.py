"""Frozen synthetic continuous-time AV filtering and control development assay."""

import argparse
import copy
import gzip
import hashlib
import json
from pathlib import Path
import resource
import time

import numpy as np

from .models import AnalyticFilter, LearnedFilter, features


HERE = Path(__file__).parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def source_hashes():
    return {name: digest(HERE / name) for name in ("models.py", "campaign.py", "test_models.py")}


def prepare(output):
    output.mkdir(parents=True, exist_ok=False)
    plan = {
        "schema": "hcsn-v9-persistent-synthetic-development.v1",
        "source_sha256": source_hashes(), "created_unix": time.time(),
        "fit_seeds": [91101, 91103, 91107, 91109, 91113],
        "families": ["gru", "ssm"], "width": 16, "epochs": 100,
        "train_size": 384, "validation_size": 128, "test_worlds": 256,
        "ticks": 16, "learning_rate": .008, "batch_size": 128,
        "rate": .35, "sensor_accuracy": {"A": .78, "V": .9},
        "read_cost": {"A": .035, "V": .06}, "interval_seconds": [.04, .7],
        "training_event_probabilities": {"skip": .3, "A": .35, "V": .35},
        "ordinary_selection": "Lowest separate validation latent-label NLL, all epochs including zero; both families retained",
        "test_seed_namespace": [20261101, 91997],
        "information": "All methods receive only dt and accepted noisy sensor events; fixed rate/accuracy are public task constants",
        "analytic_prior": "Known two-state continuous-time Markov law; ordinary networks learn from sampled latent training labels",
        "controls": {"light": "Read every third tick, alternating A and V", "value": "Common one-step expected posterior correctness minus actual issued-read fee; SKIP wins ties"},
        "training_target": "Current latent binary class after each advance/event substep; label never enters recurrent input",
        "persistent_state": "Retained across all 16 ticks, reset only at episode boundary; tentative actions clone state",
        "no_core_reference": "Exact filtering recomputed from full raw visible history for each candidate, identical public physics",
        "claim_scope": "Synthetic finite CTMC task with noisy A/V sensors, not real audio/video and not renewal/first-passage propagation",
        "real_AV_confirmation": False, "strong_ordinary_qualification": False,
        "production_acceptance": False,
        "limitations": ["single public fixed law", "synthetic binary targets", "one-step control", "no raw AV content", "no architectural adoption claim", "ordinary fit budget not a convergence certificate"],
    }
    write(output / "PLAN.json", plan)
    print(json.dumps({"plan_sha256": digest(output / "PLAN.json")}), flush=True)


def world(seed, ticks, plan):
    rng = np.random.default_rng(seed)
    dt = rng.uniform(*plan["interval_seconds"], ticks)
    latent = np.zeros(ticks, dtype=int)
    current = int(rng.integers(2))
    audio, video = [], []
    for t, delta in enumerate(dt):
        if rng.random() < (1 - np.exp(-2 * plan["rate"] * delta)) / 2:
            current = 1 - current
        latent[t] = current
        for name, dest in (("A", audio), ("V", video)):
            observed = current if rng.random() < plan["sensor_accuracy"][name] else 1 - current
            dest.append(2 * observed - 1)
    return {"dt": dt.tolist(), "latent": latent.tolist(), "A": audio, "V": video}


def dataset(seed, size, plan):
    inputs, labels, masks = [], [], []
    mask_rng = np.random.default_rng(np.random.SeedSequence([seed, 737]))
    for i in range(size):
        w = world(np.random.SeedSequence([seed, i, 199]), plan["ticks"], plan)
        xs, ys, ms = [], [], []
        for t, dt in enumerate(w["dt"]):
            modality = mask_rng.choice(["skip", "A", "V"], p=[.3, .35, .35])
            xs.append(features(dt)); ys.append(w["latent"][t]); ms.append(0)
            xs.append(features(0, None if modality == "skip" else modality,
                               0 if modality == "skip" else w[modality][t]))
            ys.append(w["latent"][t]); ms.append({"skip": 0, "A": 1, "V": 2}[modality])
        inputs.append(xs); labels.append(ys); masks.append(ms)
    return np.array(inputs), np.array(labels), np.array(masks)


def nll(q, y):
    return float(-np.mean(y * np.log(q + 1e-12) + (1 - y) * np.log(1 - q + 1e-12)))


def fit(output, plan):
    dest = output / "fits"
    dest.mkdir()
    reports, models = {}, {}
    for seed in plan["fit_seeds"]:
        began_cpu, began_wall = time.process_time(), time.monotonic()
        x, y, masks = dataset(seed, plan["train_size"], plan)
        vx, vy, vmasks = dataset(seed + 80003, plan["validation_size"], plan)
        data_path = dest / f"data_{seed}.npz"
        np.savez_compressed(data_path, train_x=x, train_y=y, train_masks=masks,
                            validation_x=vx, validation_y=vy, validation_masks=vmasks)
        generation = {"cpu_seconds": time.process_time() - began_cpu,
                      "wall_seconds": time.monotonic() - began_wall}
        reports[str(seed)] = {"data_generation": generation, "data_sha256": digest(data_path), "families": {}}
        models[seed] = {}
        orders = [np.random.default_rng(np.random.SeedSequence([seed, e, 123])).permutation(len(x))
                  for e in range(plan["epochs"])]
        for family in plan["families"]:
            start_cpu, start_wall = time.process_time(), time.monotonic()
            model = LearnedFilter(family, seed, plan["width"])
            first, second = ({k: np.zeros_like(v) for k, v in model.p.items()} for _ in range(2))
            best, selected, best_weights, step = float("inf"), 0, None, 0
            history = []
            for epoch in range(plan["epochs"] + 1):
                if epoch:
                    for indices in np.array_split(orders[epoch - 1], len(x) // plan["batch_size"]):
                        _, grad, _ = model.loss_grad(x[indices], y[indices])
                        norm = np.sqrt(sum(np.sum(v ** 2) for v in grad.values()))
                        step += 1
                        for key in model.p:
                            g = grad[key] * min(1, 5 / max(norm, 1e-12))
                            first[key] = .9 * first[key] + .1 * g
                            second[key] = .999 * second[key] + .001 * g ** 2
                            model.p[key] -= plan["learning_rate"] * (first[key] / (1 - .9 ** step)) / (np.sqrt(second[key] / (1 - .999 ** step)) + 1e-8)
                score = nll(model.sequence(vx), vy)
                history.append(score)
                if score < best:
                    best, selected, best_weights = score, epoch, copy.deepcopy(model.p)
            model.p = best_weights
            path = dest / f"{family}_{seed}.npz"
            np.savez_compressed(path, **model.p)
            report = {"validation_nll": best, "selected_epoch": selected,
                      "validation_nll_history": history, "parameter_count": sum(v.size for v in model.p.values()),
                      "fit_cpu_seconds": time.process_time() - start_cpu,
                      "fit_wall_seconds": time.monotonic() - start_wall,
                      "checkpoint_sha256": digest(path), "persistent_observation_state": True,
                      "strong_ordinary_qualification": False}
            reports[str(seed)]["families"][family] = report
            models[seed][family] = model
            print(json.dumps({"fit_seed": seed, "family": family, **{k: report[k] for k in ("validation_nll", "selected_epoch", "fit_cpu_seconds")}}), flush=True)
        reports[str(seed)]["selected_family"] = min(plan["families"], key=lambda f: (reports[str(seed)]["families"][f]["validation_nll"], f))
    write(output / "FIT.json", reports)
    write(output / "FROZEN_MODELS.json", {"plan_sha256": digest(output / "PLAN.json"),
          "fit_sha256": digest(output / "FIT.json"), "before_test_world_generation": True,
          "selection": {k: v["selected_family"] for k, v in reports.items()},
          "checkpoints": {str(p.relative_to(output)): digest(p) for p in dest.glob("*_[0-9]*.npz") if not p.name.startswith("data_")}})
    return reports, models


def rollout(w, family, control, plan, model=None):
    analytical = AnalyticFilter(plan["rate"], plan["sensor_accuracy"])
    state = model.zero() if model is not None else .5
    history, trace = [], []
    start_cpu, start_wall = time.process_time(), time.monotonic()

    def advance(previous, dt, modality=None, value=0, visible=None):
        if model is not None:
            h, q, _ = model.step(features(dt, modality, value)[None], previous)
            return h, float(q[0])
        if family == "direct_history":
            p = analytical.history(visible + [(dt, modality, value)])
        else:
            p = analytical.step(dt, previous, modality, value)
        return p, p

    for t, dt in enumerate(w["dt"]):
        state, prior = advance(state, dt, visible=history)
        history.append((dt, None, 0))
        scores = {"SKIP": max(prior, 1 - prior)}
        for modality in ("A", "V"):
            accuracy = plan["sensor_accuracy"][modality]
            p_yes = prior * accuracy + (1 - prior) * (1 - accuracy)
            expected = 0
            for value, weight in ((1, p_yes), (-1, 1 - p_yes)):
                _, after = advance(state, 0, modality, value, history)
                expected += weight * max(after, 1 - after)
            scores[modality] = expected - plan["read_cost"][modality]
        if control == "light":
            action = ("A" if (t // 3) % 2 == 0 else "V") if t % 3 == 0 else "SKIP"
        else:
            action = max(("SKIP", "A", "V"), key=lambda a: (scores[a], a == "SKIP"))
        probability, fee, accepted = prior, 0., None
        if action != "SKIP":
            accepted = w[action][t]
            state, probability = advance(state, 0, action, accepted, history)
            history.append((0, action, accepted))
            fee = plan["read_cost"][action]
        prediction = int(probability > .5)
        correct = int(prediction == w["latent"][t])
        trace.append({"tick": t, "dt": dt, "prior_probability": prior,
                      "probability": probability, "scores": scores, "action": action,
                      "accepted_event": accepted, "fee": fee,
                      "correct": correct, "net_reward": correct - fee,
                      "brier": (probability - w["latent"][t]) ** 2,
                      "state": np.asarray(state).reshape(-1).tolist()})
    return {"family": family, "control": control, "trace": trace,
            "summary": {k: float(np.mean([r[k] for r in trace])) for k in ("correct", "fee", "net_reward", "brier")},
            "execution_cpu_seconds": time.process_time() - start_cpu,
            "execution_wall_seconds": time.monotonic() - start_wall}


def evaluate(output, plan, reports, models):
    dest = output / "evaluation"
    dest.mkdir()
    rows, maximum_parity = [], 0.
    worlds = []
    with gzip.open(dest / "runs.jsonl.gz", "xt") as stream:
        for index in range(plan["test_worlds"]):
            w = world(np.random.SeedSequence(plan["test_seed_namespace"] + [index]), plan["ticks"], plan)
            worlds.append({"index": index, **w})
            analytic_runs = {}
            for family in ("analytic", "direct_history"):
                for control in ("light", "value"):
                    run = {"world": index, "fit_seed": None, **rollout(w, family, control, plan)}
                    rows.append(run); stream.write(json.dumps(run, allow_nan=False) + "\n")
                    analytic_runs[(family, control)] = run
            for control in ("light", "value"):
                a, b = (analytic_runs[(f, control)] for f in ("analytic", "direct_history"))
                maximum_parity = max(maximum_parity, max(abs(x["probability"] - y["probability"]) for x, y in zip(a["trace"], b["trace"])))
                if [r["action"] for r in a["trace"]] != [r["action"] for r in b["trace"]]:
                    raise AssertionError("Direct-history action parity failed")
            for seed in plan["fit_seeds"]:
                for family in plan["families"]:
                    for control in ("light", "value"):
                        run = {"world": index, "fit_seed": seed, **rollout(w, family, control, plan, models[seed][family])}
                        rows.append(run); stream.write(json.dumps(run, allow_nan=False) + "\n")
    with gzip.open(dest / "worlds.jsonl.gz", "xt") as stream:
        for w in worlds:
            stream.write(json.dumps(w) + "\n")
    indexed = {(r["world"], r["fit_seed"], r["family"], r["control"]): r for r in rows}
    means, paired = {}, []
    for seed in plan["fit_seeds"]:
        selected = reports[str(seed)]["selected_family"]
        measures = {}
        for label, family, control in (("A", selected, "light"), ("B", selected, "value"), ("C", "analytic", "light"), ("D", "analytic", "value"), ("H", "direct_history", "value")):
            measures[label] = np.array([indexed[(i, seed if label in ("A", "B") else None, family, control)]["summary"]["net_reward"] for i in range(plan["test_worlds"])])
        contrasts = {"B-A": measures["B"] - measures["A"], "D-C": measures["D"] - measures["C"],
                     "C-A": measures["C"] - measures["A"], "D-B": measures["D"] - measures["B"],
                     "interaction": measures["D"] - measures["C"] - measures["B"] + measures["A"],
                     "D-H": measures["D"] - measures["H"]}
        means[str(seed)] = {"selected_family": selected, "means": {k: float(v.mean()) for k, v in measures.items()},
                            "contrasts": {k: float(v.mean()) for k, v in contrasts.items()}}
        paired.append(contrasts["D-B"])
    paired = np.array(paired)
    rng = np.random.default_rng(91379)
    boot = []
    for _ in range(2000):
        selected_seeds = rng.integers(0, len(paired), len(paired))
        selected_worlds = rng.integers(0, paired.shape[1], paired.shape[1])
        boot.append(float(paired[np.ix_(selected_seeds, selected_worlds)].mean()))
    np.savez_compressed(dest / "paired_D_minus_B.npz", paired=paired)
    summary = {"claim_scope": plan["claim_scope"], "real_AV_confirmation": False,
               "production_acceptance": False, "strong_ordinary_qualification": False,
               "test_worlds": len(worlds), "runs": len(rows), "outputs": sum(len(r["trace"]) for r in rows),
               "fits": means, "D_minus_B_mean": float(paired.mean()),
               "D_minus_B_two_way_bootstrap_95": np.quantile(boot, [.025, .975]).tolist(),
               "interval_unit": "Resample independent fit seeds and independent worlds, not 98304 correlated outputs",
               "direct_history_max_probability_error": maximum_parity,
               "direct_history_actions_identical": True,
               "analytic_better_than_exact_history": False,
               "execution_cpu_seconds_sum": sum(r["execution_cpu_seconds"] for r in rows),
               "execution_wall_seconds_sum": sum(r["execution_wall_seconds"] for r in rows),
               "raw_sha256": {str(p.relative_to(output)): digest(p) for p in dest.iterdir()},
               "interpretation": "Persistent filters now evaluated over actual observation sequences. Known-law analytic Bayes may outperform finite-budget learned models; exact raw-history recomputation has identical quality, so this is not a core necessity or real-AV result."}
    write(output / "SUMMARY.json", summary)
    print(json.dumps({k: summary[k] for k in ("test_worlds", "runs", "D_minus_B_mean", "D_minus_B_two_way_bootstrap_95", "direct_history_max_probability_error")}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.output)
        return
    plan = json.loads((args.output / "PLAN.json").read_text())
    if plan["source_sha256"] != source_hashes():
        raise RuntimeError("Source changed after registration")
    cpu, wall = time.process_time(), time.monotonic()
    before = resource.getrusage(resource.RUSAGE_SELF)
    reports, models = fit(args.output, plan)
    evaluate(args.output, plan, reports, models)
    after = resource.getrusage(resource.RUSAGE_SELF)
    write(args.output / "RUNTIME.json", {"inclusive_cpu_seconds": time.process_time() - cpu,
          "inclusive_wall_seconds": time.monotonic() - wall, "ru_maxrss_kib": after.ru_maxrss,
          "rusage_user_delta": after.ru_utime - before.ru_utime,
          "rusage_system_delta": after.ru_stime - before.ru_stime,
          "cost_scope": "Single Python process, generation/training/checkpoints/test/raw writing included; nested execution timers not added", "energy_joules": None})


if __name__ == "__main__":
    main()
