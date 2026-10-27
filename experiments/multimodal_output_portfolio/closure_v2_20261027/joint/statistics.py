"""Source-pair inference, conditional on the three fixed training/noise seeds."""

import numpy as np

from .protocol import PROTOCOL as P


def ce(table):
    values = -P["gamma"] * np.asarray(table, dtype=np.float64)
    maximum = values.max(axis=(1, 2), keepdims=True)
    return float(np.mean(-(np.log(np.exp(values - maximum).mean(axis=(1, 2)))
                           + maximum[:, 0, 0]) / P["gamma"]))


def analyze(rows):
    tables, summary = {}, {}
    for split, count, conditions in (("test", P["test_pairs"], P["conditions"]),
                                      ("retention", P["retention_pairs"], ["clean"])):
        for arm in P["arms"]:
            table = np.full((len(P["seeds"]), count, len(conditions)), np.nan)
            selected = [r for r in rows if r["split"] == split and r["arm"] == arm]
            for row in selected:
                index = P["seeds"].index(row["seed"]), row["pair"], conditions.index(row["condition"])
                if np.isfinite(table[index]):
                    raise ValueError("Repeated delivered outcome")
                table[index] = row["audit"]["utility"]
            if not np.isfinite(table).all():
                raise ValueError("Incomplete evaluation grid")
            tables[split, arm] = table
            summary[f"{split}/{arm}"] = {"audit_ce": ce(table), "mean_utility": float(table.mean()),
                "model_cpu_ms": float(np.mean([r["model_cpu_ns_per_example"] for r in selected])) / 1e6,
                "delivered_cpu_ms": float(np.mean([r["delivered_cpu_ns_per_example"] for r in selected])) / 1e6,
                "delivered_wall_ms": float(np.mean([r["delivered_wall_ns_per_example"] for r in selected])) / 1e6}
    rng, comparisons = np.random.default_rng(P["bootstrap_seed"]), []
    pairs = [("direct_risk", "original"), ("direct_risk", "noise_control"),
             ("direct_risk", "direct_mean"), ("direct_mean", "original")]
    for split in ("test", "retention"):
        for candidate, baseline in pairs:
            x, y = tables[split, candidate], tables[split, baseline]
            samples = []
            for _ in range(P["bootstrap_replicates"]):
                indices = rng.integers(x.shape[1], size=x.shape[1])
                samples.append(ce(x[:, indices]) - ce(y[:, indices]))
            alpha = (1 - P["interval"]) / 2
            comparisons.append({"split": split, "comparison": candidate + "-" + baseline,
                "ce_difference": ce(x) - ce(y), "paired_97_5_interval": np.quantile(samples, [alpha, 1 - alpha]).tolist(),
                "per_seed_ce_differences": [ce(a[None]) - ce(b[None]) for a, b in zip(x, y)],
                "source_pairs": x.shape[1], "fixed_seeds": P["seeds"]})
    def gate(name):
        q = next(r for r in comparisons if r["split"] == "test" and r["comparison"] == name)
        retention = next(r for r in comparisons if r["split"] == "retention" and r["comparison"] == name)
        return (q["paired_97_5_interval"][0] > 0 and min(q["per_seed_ce_differences"]) > 0
                and retention["paired_97_5_interval"][0] >= -P["retention_noninferiority_margin"])
    return {"schema": "hepta.ndu.direct-delivery-gradient-result.v1", "summaries": summary,
        "comparisons": comparisons, "actual_delivered_bundles": len(rows),
        "generator_gain_and_retention_passed": gate("direct_risk-original"),
        "same_family_training_gain_passed": gate("direct_risk-noise_control"),
        "matched_risk_specific_gate_passed": gate("direct_risk-direct_mean"),
        "mean_generator_gain_and_retention_passed": gate("direct_mean-original"),
        "new_test_used_to_select": False, "global_optimality_established": False,
        "independent_unit": "source pair shared across fixed seeds and conditions",
        "seed_or_writer_population_inference": False,
        "trained_parameters": "Gaussian latent mean MLP, not the frozen base decoder weights"}
