"""Fit-level planning and inference; missing fits never become successes only."""
import math

import numpy as np
from scipy.stats import chi2, nct, t

PRIMARY = (
    ("fpt_feedback", {"fpt_base_multi": 1., "fpt_base_single": -1.}),
    ("ordinary_feedback", {"ordinary_multi": 1., "ordinary_single": -1.}),
)
SECONDARY = (
    ("acc_structure_off", {"acc_structured_off": 1., "acc_free_off": -1.}),
    ("acc_structure_multi", {"acc_structured_multi": 1., "acc_free_multi": -1.}),
    ("acc_feedback_free", {"acc_free_multi": 1., "acc_free_off": -1.}),
    ("acc_feedback_structured", {"acc_structured_multi": 1., "acc_structured_off": -1.}),
    ("acc_interaction", {"acc_structured_multi": 1., "acc_structured_off": -1.,
                         "acc_free_multi": -1., "acc_free_off": 1.}),
    ("fpt_drift_at_last_bank", {"fpt_base_multi": 1., "fpt_neutral_drift": -1.}),
    ("fpt_drift_at_neutral_bank", {"fpt_neutral_bank": 1., "fpt_neutral_both": -1.}),
    ("fpt_bank_at_sustained_drift", {"fpt_base_multi": 1., "fpt_neutral_bank": -1.}),
    ("fpt_bank_at_neutral_drift", {"fpt_neutral_drift": 1., "fpt_neutral_both": -1.}),
    ("fpt_drift_bank_interaction", {"fpt_base_multi": 1., "fpt_neutral_drift": -1.,
                                  "fpt_neutral_bank": -1., "fpt_neutral_both": 1.}),
    ("fpt_sign_at_signed_reset", {"fpt_base_multi": 1., "fpt_pooled_sign": -1.}),
    ("fpt_sign_at_common_reset", {"fpt_common_reset": 1., "fpt_pooled_common": -1.}),
    ("fpt_reset_at_signed_readout", {"fpt_base_multi": 1., "fpt_common_reset": -1.}),
    ("fpt_reset_at_pooled_readout", {"fpt_pooled_sign": 1., "fpt_pooled_common": -1.}),
    ("fpt_sign_reset_interaction", {"fpt_base_multi": 1., "fpt_pooled_sign": -1.,
                                  "fpt_common_reset": -1., "fpt_pooled_common": 1.}),
    ("fpt_multi_minus_off", {"fpt_base_multi": 1., "fpt_base_off": -1.}),
    ("analytic_increment", {"fpt_base_multi": 1., "ordinary_multi": -1.}),
)


def _fit_ids(values):
    result = list(values)
    if not result or len(result) != len(set(result)):
        raise ValueError("nonempty unique registered fit IDs required")
    if any(isinstance(fit, bool) or not isinstance(fit, (int, np.integer)) for fit in result):
        raise ValueError("fit IDs must be integers")
    return sorted(int(fit) for fit in result)


def _index(rows, fits, splits):
    index = {}
    for row in rows:
        if row.get("split") not in splits or row.get("controller", "value") != "value":
            continue
        if row["fit"] not in fits:
            raise ValueError("unregistered fit in an analyzed split")
        key = (row["fit"], row["split"], row["candidate"])
        if key in index:
            raise ValueError(f"duplicate fit/split/candidate summary: {key}")
        index[key] = row
    return index


def _differences(index, fits, split, weights):
    differences, failures = [], []
    for fit in fits:
        value, usable = 0., True
        for candidate, weight in weights.items():
            row = index.get((fit, split, candidate))
            reason = None
            if row is None:
                reason = "missing summary"
            elif row.get("valid") is False or row.get("status") in ("failed", "invalid") or row.get("failure"):
                reason = "explicitly invalid summary"
            else:
                metrics = row.get("metrics")
                utility = metrics.get("utility") if isinstance(metrics, dict) else None
                if isinstance(utility, bool) or not isinstance(utility, (int, float)) or not math.isfinite(utility):
                    reason = "nonfinite or missing utility"
            if reason:
                failures.append(dict(fit=fit, split=split, candidate=candidate, reason=reason))
                usable = False
            else:
                value += weight * utility
        if usable:
            differences.append(dict(fit=fit, difference=float(value)))
    if len(fits) < 2:
        failures.append(dict(reason="at least two independent fits required"))
    # Retained valid differences are raw diagnostics only if any fit failed.
    return differences, failures


def _interval(values, alpha, multiplicity):
    count = len(values)
    mean = float(np.mean(values))
    sd = float(np.std(values, ddof=1))
    standard_error = sd / math.sqrt(count)
    critical = float(t.ppf(1 - alpha / (2 * multiplicity), count - 1))
    half_width = critical * standard_error
    return dict(n_independent_fits=count, mean=mean, sample_sd=sd,
                standard_error=standard_error, degrees_of_freedom=count - 1,
                critical_t=critical, confidence_interval=[mean - half_width, mean + half_width],
                alpha=alpha, multiplicity=multiplicity)


def _power(count, sd, true_effect, margin, alpha, multiplicity):
    if sd == 0:
        return float(true_effect > margin)
    critical = float(t.ppf(1 - alpha / (2 * multiplicity), count - 1))
    noncentrality = (true_effect - margin) * math.sqrt(count) / sd
    return float(nct.sf(critical, count - 1, noncentrality))


def planning(summary_rows, cap=32, minimum_fits=32, expected_fits=None):
    """Plan four intervals from DEV fit means under independent-normal assumptions.

    The SD upper bound is marginal one-sided 90%, not a simultaneous variance
    bound. Validation and validation_ood are mapped to future IID and OOD.
    """
    if not isinstance(cap, int) or not isinstance(minimum_fits, int) or not 8 <= minimum_fits <= cap:
        raise ValueError("integer 8 <= minimum_fits <= cap required")
    fits = _fit_ids(expected_fits if expected_fits is not None else
                    sorted({r["fit"] for r in summary_rows if r.get("split") in ("validation", "validation_ood")}))
    index = _index(summary_rows, fits, ("validation", "validation_ood"))
    alpha, multiplicity, margin, true_effect, target = .05, 4, .02, .08, .8
    entries = []
    for split, development_split in (("iid", "validation"), ("ood", "validation_ood")):
        for name, weights in PRIMARY:
            differences, failures = _differences(index, fits, development_split, weights)
            entry = dict(contrast=name, split=split, development_split=development_split,
                         weights=weights, fit_differences=differences, failures=failures,
                         n_development=len(fits), valid=not failures,
                         sample_sd=None, sd_upper90=None, required_n=None,
                         required_n_exceeds_search_limit=False, power_at_selected=None)
            if not failures:
                values = [row["difference"] for row in differences]
                sd = float(np.std(values, ddof=1))
                upper = math.sqrt((len(fits) - 1) * sd * sd / float(chi2.ppf(.1, len(fits) - 1)))
                entry.update(development_mean=float(np.mean(values)), sample_sd=sd, sd_upper90=upper,
                             zero_empirical_variance=sd == 0)
                if _power(4096, upper, true_effect, margin, alpha, multiplicity) < target:
                    entry["required_n_exceeds_search_limit"] = True
                else:
                    lo, hi = 8, 4096
                    while lo < hi:
                        mid = (lo + hi) // 2
                        if _power(mid, upper, true_effect, margin, alpha, multiplicity) >= target:
                            hi = mid
                        else:
                            lo = mid + 1
                    entry["required_n"] = lo
            entries.append(entry)
    valid = all(row["valid"] for row in entries)
    exceeds = any(row["required_n_exceeds_search_limit"] for row in entries)
    known = [row["required_n"] for row in entries if row["required_n"] is not None]
    requested = max([minimum_fits, *known]) if valid and not exceeds else None
    selected = min(cap, requested) if requested is not None else cap
    for entry in entries:
        if entry["valid"]:
            entry["power_at_selected"] = _power(selected, entry["sd_upper90"], true_effect, margin, alpha, multiplicity)
        entry["resource_cap_binds"] = (entry["required_n_exceeds_search_limit"] or
                                        (entry["required_n"] is not None and entry["required_n"] > cap))
    cap_binds = any(row["resource_cap_binds"] for row in entries)
    return dict(schema="digital-feedback-fit-planning-v1", development_fits=fits,
                expected_fits_inferred=expected_fits is None, contrasts=entries,
                alpha=alpha, simultaneous_intervals=multiplicity, practical_margin=margin,
                planning_true_effect=true_effect, target_power=target, minimum_fits=minimum_fits,
                resource_cap_fits=cap, search_limit=4096, maximum_requested_fits=requested,
                selected_fits=selected, resource_cap_binds=cap_binds, design_ready=valid,
                planned_power_claim=bool(valid and not cap_binds and not exceeds),
                method="noncentral Student t power for a two-sided Bonferroni4 lower bound above .02",
                assumptions="independent normal fit-level paired differences, common prospective variance",
                variance_bound="marginal one-sided 90% chi-square upper SD; not simultaneous over four contrasts",
                limitation="Six development fits give an unstable variance estimate; modeled power is conditional on normality and variance transfer, not a distribution-free guarantee.")


def analyze(summary_rows, protocol):
    """Analyze every registered fit; missing arms null the affected inference."""
    fits = _fit_ids(protocol["fits"])
    index = _index(summary_rows, fits, ("iid", "ood"))
    primary, secondary = [], []
    for split in ("iid", "ood"):
        for name, weights in (*PRIMARY, *SECONDARY):
            is_primary = name in {entry[0] for entry in PRIMARY}
            differences, failures = _differences(index, fits, split, weights)
            inference = None if failures else _interval([r["difference"] for r in differences], .05, 4 if is_primary else 1)
            result = dict(contrast=name, split=split, weights=weights, expected_fits=fits,
                          fit_differences=differences, failures=failures, valid=not failures,
                          inference=inference, practical_margin=.02 if is_primary else None,
                          benefit_gate=(None if inference is None or not is_primary else
                                        inference["confidence_interval"][0] > .02),
                          interpretation="registered primary" if is_primary else
                                         "descriptive 95% interval; no familywise benefit claim")
            (primary if is_primary else secondary).append(result)
    return dict(schema="digital-feedback-confirmation-analysis-v1", fits=fits,
                n_independent_fits=len(fits), primary=primary, secondary=secondary,
                all_primary_valid=all(row["valid"] for row in primary),
                all_four_benefit_gates=all(row["benefit_gate"] is True for row in primary),
                missing_fit_rule="Every registered fit required for each contrast; no success-only inference.",
                method="paired Student t across independent fit means; four primary two-sided Bonferroni intervals",
                assumptions="independent normal fit-level differences; worlds and decisions do not increase n",
                limits="Secondary intervals are descriptive and unadjusted. An unmet benefit gate does not establish harm, zero effect or equivalence.")
