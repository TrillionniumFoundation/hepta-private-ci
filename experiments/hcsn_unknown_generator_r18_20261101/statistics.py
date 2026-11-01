"""Generator-cluster summaries, with all dependent worlds retained per draw."""

import gzip
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent


def summarize(archives, spec, selected):
    rows = []
    for entry in archives:
        rows.extend(json.loads(gzip.decompress((ROOT / entry["path"]).read_bytes())))
    output = dict(worlds=len(rows), production_activation=False, models={}, panels={}, limits=[
        "New generators are unseen continuous parameter draws from the same declared training population",
        "Generator bootstrap intervals are approximate empirical evidence, not exact coverage guarantees",
        "All addresses and complete symbolic alias bridges are supplied; no learned semantic or real AV binding",
        "Both models are ordinary finite references; no analytic-core D-B or network adoption result"])
    rng = np.random.default_rng(1888113)
    bootstrap = rng.integers(spec["confirm_generators"], size=(4096, spec["confirm_generators"]))
    grouped = {}
    for name in spec["models"]:
        main = [(r, next(iter(r["predictions"][name].values()))) for r in rows if r["split"] == "confirm"]
        invalid = sum(v["invalid"] for _, v in main)
        value = dict(attempts=len(main), invalid=invalid, quality=None, calibration=selected[name])
        if not invalid:
            stats = np.zeros((spec["confirm_generators"], 12))
            for row, record in main:
                accepted, fractional = record["accepted"], record["accepted"] and record["fractional"]
                stats[row["generator"]] += [record["before_brier"], record["brier"], record["payoff"],
                    accepted, accepted and not record["correct"], fractional,
                    fractional and not record["correct"], record["true_probability"] <= 0,
                    record["read_index"] is not None, record["payoff"] - record["no_read_payoff"],
                    record["before_log_loss"], record["log_loss"]]
            grouped[name] = stats / spec["confirm_worlds_per_generator"]
            draws = stats[bootstrap].sum(1)
            fraction_risk = np.divide(draws[:, 6], draws[:, 5], out=np.ones(4096), where=draws[:, 5] > 0)
            overall_risk = np.divide(draws[:, 4], draws[:, 3], out=np.ones(4096), where=draws[:, 3] > 0)
            accepted_count, fractional_count = int(stats[:, 3].sum()), int(stats[:, 5].sum())
            error_count, fractional_errors = int(stats[:, 4].sum()), int(stats[:, 6].sum())
            reliability = []
            for low, high in ((0., .5), (.5, .65), (.65, .75), (.75, .85), (.85, .95), (.95, 1.0000001)):
                subset = [record for _, record in main if low <= record["confidence"] < high]
                reliability.append(dict(low=low, high=high, count=len(subset),
                    mean_confidence=float(np.mean([record["confidence"] for record in subset])) if subset else None,
                    observed_accuracy=float(np.mean([record["correct"] for record in subset])) if subset else None))
            quality = dict(before_read_brier=float(grouped[name][:, 0].mean()),
                           after_read_brier=float(grouped[name][:, 1].mean()),
                           before_read_log_loss=float(grouped[name][:, 10].mean()),
                           after_read_log_loss=float(grouped[name][:, 11].mean()),
                           selective_payoff=float(grouped[name][:, 2].mean()),
                           accepted=accepted_count, errors=error_count, fractional_accepted=fractional_count,
                           fractional_errors=fractional_errors, coverage=accepted_count / len(main),
                           accepted_error=error_count / accepted_count if accepted_count else None,
                           fractional_error=fractional_errors / fractional_count if fractional_count else None,
                           upper95_fractional_error=float(np.quantile(fraction_risk, .95)),
                           upper95_accepted_error=float(np.quantile(overall_risk, .95)),
                           positive_support_failures=int(stats[:, 7].sum()), actual_reads=int(stats[:, 8].sum()),
                           mean_actual_read_net_effect=float(grouped[name][:, 9].mean()),
                           reliability_bins=reliability)
            quality["bounded_uncertainty_gate_passed"] = bool(selected[name]["calibration_gate_passed"]
                and not quality["positive_support_failures"]
                and fractional_count >= spec["minimum_fractional_confirmation_answers"]
                and quality["upper95_fractional_error"] <= spec["risk_limit"])
            value["quality"] = quality
        output["models"][name] = value
        for split in ("rotor", "vocabulary"):
            panel = [next(iter(r["predictions"][name].values())) for r in rows if r["split"] == split]
            valid = [r for r in panel if not r["invalid"]]
            output["panels"][name + ":" + split] = dict(attempts=len(panel), invalid=len(panel) - len(valid),
                refused=sum(not r["accepted"] for r in panel), answered=sum(r["accepted"] for r in panel),
                accepted_errors=sum(r["accepted"] and not r["correct"] for r in valid),
                whole_population_quality=None if len(valid) != len(panel) else float(np.mean([r["payoff"] for r in panel])),
                interpretation="Misspecified family; not included in calibration/primary gate")
    if len(grouped) == 2:
        difference = grouped["pooled_iid"][:, 0] - grouped["markov_mixture"][:, 0]
        payoff = grouped["markov_mixture"][:, 2] - grouped["pooled_iid"][:, 2]
        brier_ci = np.quantile(difference[bootstrap].mean(1), [.025, .975])
        payoff_ci = np.quantile(payoff[bootstrap].mean(1), [.025, .975])
        output["paired_ordinary_model_comparison"] = dict(independent_units=len(difference),
            before_read_brier_improvement=float(difference.mean()), before_read_brier_ci95=brier_ci.tolist(),
            selective_payoff_improvement=float(payoff.mean()), selective_payoff_ci95=payoff_ci.tolist(),
            gate_passed=bool(difference.mean() >= .01 and brier_ci[0] > 0 and payoff_ci[0] >= 0),
            scope="Ordinary shared-information generator models; no analytic HCSN core or production adoption")
    return output
