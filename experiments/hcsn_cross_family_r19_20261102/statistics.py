"""Per-family primary gates; never let pooled means mask a failed process."""

import gzip
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent


def summarize(archives, spec, selected):
    raw = []
    for entry in archives:
        raw.extend(json.loads(gzip.decompress((ROOT / entry["path"]).read_bytes())))
    delta = .05 / (len(spec["all_families"]) * 4)
    result = dict(schema="hcsn.r19.cross-family.summary.v1", worlds=len(raw),
                  primary_candidate="class_mixture", production_activation=False,
                  one_sided_confirmation_delta=delta, families={})
    for family_index, family in enumerate(spec["all_families"]):
        rows = [row for row in raw if row["family"] == family]
        rng = np.random.default_rng(19021991 + family_index)
        bootstrap = rng.integers(spec["confirm_generators_per_family"],
                                 size=(4096, spec["confirm_generators_per_family"]))
        grouped, models = {}, {}
        for name in spec["models"]:
            attempts = [(row, next(iter(row["predictions"][name].values()))) for row in rows]
            invalid = sum(value["invalid"] for _, value in attempts)
            entry = dict(attempts=len(attempts), invalid=invalid, whole_population_quality=None,
                         calibration=selected[name])
            if not invalid:
                values = np.zeros((spec["confirm_generators_per_family"], 14))
                for row, record in attempts:
                    accepted = record["accepted"]
                    fractional = accepted and record["fractional"]
                    values[row["generator"]] += [record["before_brier"], record["after_brier"], record["payoff"],
                        accepted, accepted and not record["correct"], fractional,
                        fractional and not record["correct"], record["true_probability"] <= 0,
                        record["read_index"] is not None, record["payoff"] - record["no_read_payoff"],
                        record["before_log_loss"], record["after_log_loss"], record["admitted"],
                        record["read_index"] is not None and not accepted]
                grouped[name] = values / spec["confirm_worlds_per_generator"]
                draws = values[bootstrap].sum(1)
                overall = np.divide(draws[:, 4], draws[:, 3], out=np.ones(4096), where=draws[:, 3] > 0)
                fractional = np.divide(draws[:, 6], draws[:, 5], out=np.ones(4096), where=draws[:, 5] > 0)
                total = values.sum(0)
                quality = dict(before_brier=float(grouped[name][:, 0].mean()),
                    after_brier=float(grouped[name][:, 1].mean()), selective_payoff=float(grouped[name][:, 2].mean()),
                    accepted=int(total[3]), accepted_errors=int(total[4]), fractional_accepted=int(total[5]),
                    fractional_errors=int(total[6]), support_failures=int(total[7]), actual_reads=int(total[8]),
                    mean_read_net_effect=float(grouped[name][:, 9].mean()),
                    before_log_loss=float(grouped[name][:, 10].mean()), after_log_loss=float(grouped[name][:, 11].mean()),
                    admitted=int(total[12]), read_then_refused=int(total[13]),
                    overall_error=float(total[4] / total[3]) if total[3] else None,
                    fractional_error=float(total[6] / total[5]) if total[5] else None,
                    simultaneous_upper_overall_error=float(np.quantile(overall, 1 - delta)),
                    simultaneous_upper_fractional_error=float(np.quantile(fractional, 1 - delta)))
                entry["whole_population_quality"] = quality
            models[name] = entry
        gate, comparison = False, None
        if len(grouped) == 2:
            brier = grouped["best_static"][:, 0] - grouped["class_mixture"][:, 0]
            payoff = grouped["class_mixture"][:, 2] - grouped["best_static"][:, 2]
            brier_ci = np.quantile(brier[bootstrap].mean(1), [delta, 1 - delta])
            payoff_ci = np.quantile(payoff[bootstrap].mean(1), [delta, 1 - delta])
            comparison = dict(independent_generator_units=len(brier), before_read_brier_gain=float(brier.mean()),
                simultaneous_brier_gain_interval=brier_ci.tolist(), actual_selective_payoff_gain=float(payoff.mean()),
                simultaneous_payoff_gain_interval=payoff_ci.tolist())
            primary = models["class_mixture"]["whole_population_quality"]
            gate = bool(selected["class_mixture"]["calibration_gate_passed"] and not primary["support_failures"]
                        and primary["fractional_accepted"] >= spec["minimum_fractional_confirmation"]
                        and primary["simultaneous_upper_overall_error"] <= spec["risk_limit"]
                        and primary["simultaneous_upper_fractional_error"] <= spec["risk_limit"]
                        and brier_ci[0] >= 0 and payoff_ci[0] >= 0)
        result["families"][family] = dict(models=models, comparison=comparison,
            all_criteria_passed=gate, seen_in_fit_or_calibration=family in spec["trained_families"])
    result["trained_family_gate_passed"] = all(result["families"][name]["all_criteria_passed"] for name in spec["trained_families"])
    result["all_declared_processes_gate_passed"] = all(value["all_criteria_passed"] for value in result["families"].values())
    result["limits"] = ["Five per-family gates include coherent never-trained processes; no postholdout repairs",
        "Bootstrap multiplicity is prespecified empirical inference, not an exact finite-sample coverage theorem",
        "Ordinary finite model classes and full raw prefix, no analytic-core D-B or learned multimodal representation claim",
        "Task READ fees are measured separately from physical CPU/GPU/energy adoption; complete batch CPU is not per-model timing"]
    return result
