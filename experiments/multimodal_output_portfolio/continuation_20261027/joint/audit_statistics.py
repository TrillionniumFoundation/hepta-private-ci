"""Independent bounded-return CE and clustered interval reconstruction."""

import math

import numpy as np

from .protocol import PROTOCOL as P


def direct_ce(array):
    # |utility| <= 1 for the registered metric, so direct exponentiation is safe.
    return float(np.mean([-math.log(float(np.exp(-P["gamma"] * seed).mean())) / P["gamma"]
                          for seed in array]))


def audit_statistics(rows, oracle, result):
    arrays = {}
    for split, count, conditions in (("test", P["test_pairs"], P["conditions"]),
                                      ("retention", P["retention_pairs"], ["clean"])):
        for arm in P["arms"]:
            selected = {(r["seed"], r["pair"], r["condition"]): r["audit"]["utility"]
                        for r in rows if r["split"] == split and r["arm"] == arm}
            arrays[split, arm] = np.array([[[selected[seed, pair, condition] for condition in conditions]
                                           for pair in range(count)] for seed in P["seeds"]])
    maximum = 0.
    for (split, arm), array in arrays.items():
        summary = result["summaries"][f"{split}/{arm}"]
        maximum = max(maximum, abs(summary["audit_ce"] - direct_ce(array)),
                      abs(summary["mean_audit_utility"] - float(array.mean())))
    rng = np.random.default_rng(P["bootstrap_seed"])
    recomputed = {}
    alpha = (1 - P["interval"]) / 2
    for split in ("test", "retention"):
        for candidate, baseline in (("joint_risk", "frozen"), ("joint_risk", "joint_uniform"),
                                    ("joint_uniform", "frozen")):
            a, b = arrays[split, candidate], arrays[split, baseline]
            samples = []
            for _ in range(P["bootstrap_replicates"]):
                take = rng.choice(a.shape[1], size=a.shape[1], replace=True)
                samples.append(direct_ce(a[:, take]) - direct_ce(b[:, take]))
            interval = np.quantile(samples, [alpha, 1 - alpha])
            per_seed = [direct_ce(x[None]) - direct_ce(y[None]) for x, y in zip(a, b)]
            name = candidate + "-" + baseline
            recorded = next(r for r in result["comparisons"] if r["split"] == split and r["comparison"] == name)
            maximum = max(maximum, abs(recorded["ce_difference"] - (direct_ce(a) - direct_ce(b))),
                          float(np.max(np.abs(np.asarray(recorded["paired_97_5_interval"]) - interval))),
                          float(np.max(np.abs(np.asarray(recorded["per_seed_ce_differences"]) - per_seed))))
            recomputed[split, name] = interval, per_seed
    oracle_map = {(r["seed"], r["pair"], r["condition"]): r["utility"] for r in oracle}
    upper = np.array([[[oracle_map[seed, pair, condition] for condition in P["conditions"]]
                       for pair in range(P["test_pairs"])] for seed in P["seeds"]])
    risk = arrays["test", "joint_risk"]
    rng = np.random.default_rng(P["bootstrap_seed"] + 1)
    differences = []
    for _ in range(P["bootstrap_replicates"]):
        take = rng.choice(P["test_pairs"], size=P["test_pairs"], replace=True)
        differences.append(direct_ce(risk[:, take]) - direct_ce(upper[:, take]))
    interval = np.quantile(differences, [alpha, 1 - alpha])
    per_seed = [direct_ce(x[None]) - direct_ce(y[None]) for x, y in zip(risk, upper)]
    recorded = result["generator_attribution"]
    maximum = max(maximum, abs(recorded["oracle_ce"] - direct_ce(upper)),
                  abs(recorded["ce_difference"] - (direct_ce(risk) - direct_ce(upper))),
                  float(np.max(np.abs(np.asarray(recorded["paired_97_5_interval"]) - interval))),
                  float(np.max(np.abs(np.asarray(recorded["per_seed_ce_differences"]) - per_seed))))
    def acceptance(name):
        quality, seeds = recomputed["test", name]
        retained, _ = recomputed["retention", name]
        return bool(quality[0] > 0 and min(seeds) > 0 and retained[0] >= -P["retention_noninferiority_margin"])
    generator, matched = acceptance("joint_risk-frozen"), acceptance("joint_risk-joint_uniform")
    attribution = bool(interval[0] > 0 and min(per_seed) > 0)
    if (result["generator_update_gate_passed"] != generator
            or result["matched_training_gate_passed"] != matched
            or recorded["attribution_gate_passed"] != attribution
            or result["all_joint_acceptance_gates_passed"] != (generator and matched and attribution)):
        raise ValueError("Reported acceptance does not match independent statistics")
    if maximum > 1e-10:
        raise ValueError(f"Independent CE/interval reconstruction differs: {maximum}")
    return {"maximum_independent_statistic_error": maximum,
            "reported_ce_intervals_and_acceptance_reconstructed": True}
