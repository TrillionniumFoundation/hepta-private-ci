"""Independently replay confirmation actions, costs and paired comparisons.

This code does not call episode_run or the fitted predictor's predict method.
Fresh episode private facts are used only by this terminal evidence audit.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.stats import t as student_t

from . import finite
from .frozen import FrozenR7
from .run import checkpoint, digest, source_manifest, write


def interval(values):
    values = np.asarray(values)
    half = student_t.ppf(1 - .05 / 6, len(values) - 1) * values.std(ddof=1) / np.sqrt(len(values))
    return {"mean": float(values.mean()), "interval": [float(values.mean() - half), float(values.mean() + half)]}


def audit(prepared, confirmation, output):
    preparation = json.loads((prepared / "PREPARE.json").read_text())
    frozen = json.loads((prepared / "FREEZE.json").read_text())
    if frozen["source"] != source_manifest():
        raise ValueError("frozen source identity changed")
    model_cache, kernel_cache, totals, counts = {}, {}, {}, {}
    identities = set()
    max_q_error, max_return_error, steps, pairs = 0., 0., 0, 0
    with gzip.open(confirmation / "RAW.jsonl.gz", "rt") as stream:
        for line in stream:
            raw = json.loads(line)
            identity = (raw["mode"], raw["seed"])
            episode_identity = (*identity, raw["regime"], raw["contract"], raw["episode_seed"])
            if episode_identity in identities or set(raw["runs"]) != {"old", "new"}:
                raise AssertionError("duplicate episode or incomplete pair")
            identities.add(episode_identity)
            if identity not in model_cache:
                model_cache[identity] = (FrozenR7(checkpoint(*identity)),
                    json.loads((prepared / f"{identity[0]}_{identity[1]}.json").read_text())["weights"])
            model, h = model_cache[identity]
            p = finite.configurations(raw["regime"])[raw["contract"]]
            episode = finite.task.generate_episode(raw["episode_seed"], p)
            for label, result in raw["runs"].items():
                state, reward, event_count, latent = finite.task.initial_state(episode), 0., 0, model.n // 2
                for call, row in enumerate(result["steps"]):
                    if state.to_dict() != row["state"] or row["latent_before"] != latent:
                        raise AssertionError("public prefix/latent continuity")
                    x = finite.task.features(state)
                    content, drive = model.encode(x)
                    key = (identity, x.tobytes())
                    if key not in kernel_cache:
                        kernel_cache[key] = model.transition(drive[0])[0]
                    probability = np.clip(kernel_cache[key][latent], 0., None)
                    probability /= probability.sum()
                    u = int.from_bytes(hashlib.sha256(f"r8/value/{raw['episode_seed'] + 10000000}/{call}".encode()).digest()[:8], "big") / 2 ** 64
                    next_latent = min(model.states - 1, int(np.searchsorted(probability.cumsum(), u, side="right")))
                    if next_latent != row["latent_after"]:
                        raise AssertionError("sampled event history")
                    event = int(latent < model.n <= next_latent)
                    joined = np.r_[x, content[0], model.basis[next_latent]]
                    if label == "new":
                        a = np.tanh(((joined - h["center"]) / h["scale"]) @ np.asarray(h["w1"]) + h["b1"])
                        q = np.r_[a @ np.asarray(h["w2"]) + h["b2"], 0.]
                        q += abs(2 * state.posterior - 1) - x[16] - finite.COMPUTE
                    else:
                        a = np.tanh(joined @ model.w["readout.0.weight"].T + model.w["readout.0.bias"])
                        q = (a @ model.w["readout.2.weight"].T + model.w["readout.2.bias"])[4:]
                    error = float(abs(q - row["q"]).max())
                    max_q_error = max(max_q_error, error)
                    legal = [a in finite.task.legal_actions(state) for a in finite.ACTIONS]
                    action = finite.ACTIONS[int(np.where(legal, q, -np.inf).argmax())]
                    if action != row["action"] or event != row["event"] or error > 1e-12:
                        raise AssertionError("fitted inference/action/event differs")
                    observed = finite.task.step(state, action, episode)
                    if row["guard_fallback"] or abs(observed.cost - row["cost"]) > 1e-12:
                        raise AssertionError("action cost or guard fallback")
                    if abs(observed.reward - row["reward"]) > 1e-12:
                        raise AssertionError("task reward")
                    state, latent = observed.state, next_latent
                    reward += observed.reward
                    event_count += event
                    steps += 1
                if not state.terminated:
                    raise AssertionError("nonterminal recorded execution")
                utility = reward - finite.COMPUTE * len(result["steps"]) - finite.EVENT * event_count
                error = max(abs(utility - result["utility"]), abs(reward - result["task_return"]))
                max_return_error = max(max_return_error, error)
                if error > 1e-12 or result["correct"] != int(state.answer == episode.truth):
                    raise AssertionError("terminal answer or return")
                if result["decisions"] != len(result["steps"]) or result["events"] != event_count:
                    raise AssertionError("decision or event counter")
                if not np.isfinite(result["cpu_seconds"]) or result["cpu_seconds"] < 0:
                    raise AssertionError("negative recorded CPU")
                group = (raw["mode"], raw["seed"], raw["regime"], label)
                keys = ("utility", "task_return", "correct", "cpu_seconds", "decisions", "events")
                totals.setdefault(group, np.zeros(len(keys)))
                counts[group] = counts.get(group, 0) + 1
                totals[group] += [result[k] for k in keys]
            pairs += 1
    design = preparation["protocol"]["confirmation"]
    expected = set()
    for mode in preparation["protocol"]["modes"]:
        for seed in preparation["protocol"]["core_seeds"]:
            for r, regime in enumerate(design["heldout_parameter_regimes"]):
                for contract in range(len(finite.configurations(regime))):
                    for n in range(design["episodes_per_contract_fit"]):
                        episode_seed = design["seed_start"] + (seed - 11) * 100000 + r * 10000 + contract * 1000 + n
                        expected.add((mode, seed, regime, contract, episode_seed))
    if identities != expected:
        raise AssertionError("registered confirmation coverage differs")
    means = {k: totals[k] / counts[k] for k in totals}
    summary = json.loads((confirmation / "SUMMARY.json").read_text())
    maximum_mean_error = 0.
    for row in summary["fits"]:
        key = row["mode"], row["seed"], row["regime"]
        delta = means[(*key, "new")] - means[(*key, "old")]
        maximum_mean_error = max(maximum_mean_error,
            max(abs(delta[i] - row["differences"][k]) for i, k in enumerate(keys)))
    if maximum_mean_error > 1e-12:
        raise AssertionError("independent aggregate differs")
    family = []
    preparation_cost = {(r["mode"], r["seed"]): r["standalone_new_preparation_cpu_seconds"]
        for r in preparation["fits"]}
    for regime in preparation["protocol"]["confirmation"]["heldout_parameter_regimes"]:
        for baseline in ("clocked", "direct"):
            rows = []
            cost_deltas = []
            for seed in preparation["protocol"]["core_seeds"]:
                rows.append(means["first_passage", seed, regime, "new"] - means[baseline, seed, regime, "new"])
                cost_deltas.append(preparation_cost["first_passage", seed] - preparation_cost[baseline, seed])
            effects = {k: interval([r[i] for r in rows]) for i, k in enumerate(keys)}
            price = design["primary_compute_price_cpu"]
            sessions = design["primary_training_amortization_sessions"]
            effects["net_utility"] = interval([r[0] - price * (r[3] + cost / sessions)
                for r, cost in zip(rows, cost_deltas)])
            sensitivity = [{"cpu_price": price, "deployment_sessions": sessions,
                **interval([r[0] - price * (r[3] + cost / sessions) for r, cost in zip(rows, cost_deltas)])}
                for price in design["cpu_price_sensitivity"] for sessions in design["deployment_sessions_sensitivity"]]
            family.append({"contrast": "new first_passage minus new " + baseline, "regime": regime,
                "effects": effects, "cost_sensitivity": sensitivity,
                "classification": "predeclared secondary; same-capacity/same-training-method heads, different frozen upstream cell and content"})
    records = [{"mode": k[0], "seed": k[1], "regime": k[2], "version": k[3],
        "count": counts[k], "means": dict(zip(keys, map(float, value)))} for k, value in means.items()]
    write(output, {"passed": True, "pairs_replayed": pairs, "decisions_replayed": steps,
        "max_q_error": max_q_error, "max_return_error": max_return_error,
        "max_aggregate_error": maximum_mean_error, "raw_sha256": digest(confirmation / "RAW.jsonl.gz"),
        "absolute_means": records, "calibrated_family_comparisons": family,
        "cpu_scope": "Recorded original execution counters, not this cached audit's timings"})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--confirmation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit(args.prepared, args.confirmation, args.output)


if __name__ == "__main__":
    main()
