"""Registered paired context bootstrap, conditional on three frozen fitted seeds.

Each record is one complete context cluster: its arm means already contain all
within-context rollout repeats. Resampling never separates arms or expands
those repeats into independent contexts. The family contains two pooled and
six stratum-specific contrasts, with equal stratum and fitted-seed weights.
"""

import math

import numpy as np


ARMS = ("fixed_threshold","ordinary_context_threshold","value_threshold")
CONTRASTS = ("value_threshold minus fixed_threshold",
             "value_threshold minus ordinary_context_threshold")


def summarize(records, protocol):
    """Summarize executed mean utility records without inspecting other splits.

    protocol may be the full adaptive protocol or its threshold_study section.
    Percentile bounds are empirical conditional-on-fit diagnostics, not a
    population coverage theorem. The additional per-fit positivity condition
    is applied to each of the two equally stratum-weighted fitted-seed means.
    """
    config = protocol.get("threshold_study",protocol)
    fits,strata = list(config["fit_seeds"]),list(config["strata"])
    if (len(fits) != 3 or len(strata) != 3 or len(set(fits)) != 3 or len(set(strata)) != 3
            or not all(isinstance(fit,int) and not isinstance(fit,bool) for fit in fits)
            or not all(isinstance(stratum,str) for stratum in strata)):
        raise ValueError("Expected three distinct registered fitted seeds and strata")
    replicates = config["bootstrap_replicates"]
    comparisons = config["family_comparisons"]
    alpha,margin = float(config["family_alpha"]),float(config["minimum_effect"])
    tail = alpha/(2*comparisons) if comparisons else float("nan")
    if (replicates != 4000 or comparisons != 2*(1+len(strata))
            or not 0 < alpha < 1 or not math.isfinite(margin) or margin < 0
            or not math.isclose(float(config["individual_interval_tail_probability"]),tail,rel_tol=0,abs_tol=1e-15)
            or tuple(config["arms"]) != ARMS or tuple(config["primary_contrasts"]) != CONTRASTS):
        raise ValueError("Inference settings disagree with the registered eight-comparison family")
    records = list(records)
    if not records:
        raise ValueError("No executed context clusters supplied")
    cells = {(fit,stratum):[] for fit in fits for stratum in strata}
    for record in records:
        key = (record["fit_seed"],record["stratum"])
        if key not in cells:
            raise ValueError("Unknown fitted seed or stratum in executed records")
        utility = []
        for arm in ARMS:
            value = record["arms"][arm]["mean_utility"]
            if isinstance(value,bool) or not isinstance(value,(int,float,np.number)) or not np.isfinite(value):
                raise ValueError("Every arm must have a finite numeric executed mean utility")
            utility.append(float(value))
        cells[key].append(utility)
    if any(not rows for rows in cells.values()):
        raise ValueError("An entire registered fitted-seed/stratum cell is absent")

    rng = np.random.default_rng(config["bootstrap_seed"])
    arm_means = np.empty((len(fits),len(strata),len(ARMS)))
    effects = np.empty((len(fits),len(strata),2))
    counts = np.empty((len(fits),len(strata)),dtype=int)
    # Replicate is the first axis. Each cell jointly resamples both contrasts.
    draws = np.empty((replicates,len(fits),len(strata),2))
    for fit_index,fit in enumerate(fits):
        for stratum_index,stratum in enumerate(strata):
            utility = np.asarray(cells[(fit,stratum)],dtype=float)
            paired_effect = utility[:,2,None]-utility[:,:2]
            counts[fit_index,stratum_index] = len(utility)
            arm_means[fit_index,stratum_index] = utility.mean(axis=0)
            effects[fit_index,stratum_index] = paired_effect.mean(axis=0)
            indices = rng.integers(len(utility),size=(replicates,len(utility)))
            draws[:,fit_index,stratum_index] = paired_effect[indices].mean(axis=1)

    per_fit = effects.mean(axis=1)
    pooled = per_fit.mean(axis=0)
    stratum_effects = effects.mean(axis=0)
    pooled_bounds = np.quantile(draws.mean(axis=(1,2)),[tail,1-tail],axis=0,method="linear").T
    stratum_bounds = np.quantile(draws.mean(axis=1),[tail,1-tail],axis=0,method="linear").transpose(1,2,0)
    pooled_pass = pooled_bounds[:,0] > margin
    fit_pass = per_fit > 0
    stratum_pass = stratum_bounds[:,:,0] > margin
    primary = bool(pooled_pass.all() and fit_pass.all())
    cross = bool(primary and stratum_pass.all())
    return {
        "schema":"hepta.first-passage.adaptive.paired-context-statistics.v1",
        "fit_seeds":fits,"strata":strata,"contrast_names":list(CONTRASTS),
        "complete_context_count":len(records),"counts_by_fit_stratum":counts.tolist(),
        "arm_order":list(ARMS),"arm_means_by_fit_stratum":arm_means.tolist(),
        "pooled_arm_means":dict(zip(ARMS,arm_means.mean(axis=(0,1)).tolist())),
        "effects_by_fit_stratum":effects.tolist(),"per_fit_pooled_means":per_fit.tolist(),
        "pooled_effects":pooled.tolist(),"pooled_intervals":pooled_bounds.tolist(),
        "stratum_effects":stratum_effects.tolist(),"stratum_intervals":stratum_bounds.tolist(),
        "primary_gate":primary,"cross_stratum_gate":cross,
        "gate_checks":{"pooled_lower_bounds_exceed_margin":pooled_pass.tolist(),
                       "per_fit_pooled_means_positive":fit_pass.tolist(),
                       "stratum_lower_bounds_exceed_margin":stratum_pass.tolist()},
        "minimum_effect":margin,"family_alpha":alpha,"family_comparisons":comparisons,
        "interval_tail_probability":tail,"bootstrap_replicates":replicates,
        "bootstrap_seed":config["bootstrap_seed"],"quantile_method":"linear",
        "weighting":"Equal strata within fit, then equal fitted seeds; identical weights in bootstrap",
        "resampling_unit":"One complete paired context cluster within each fit/stratum cell",
        "limits":"Empirical percentile intervals conditional on the three frozen fits; no fitted-network population or general coverage claim.",
    }
