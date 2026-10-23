"""Registered conditional-CE estimates and paired, fixed-checkpoint bootstrap."""

import numpy as np


MODALITIES = ("text", "audio", "image", "video")


def conditional_ce(values, gamma, axis):
    values = np.asarray(values, dtype=np.float64)
    if not np.isfinite(values).all() or gamma < 0 or not np.isfinite(gamma):
        raise ValueError("finite returns and nonnegative finite gamma required")
    if gamma == 0:
        return values.mean(axis=axis)
    scaled = -gamma * values
    peak = scaled.max(axis=axis, keepdims=True)
    return -(np.squeeze(peak, axis=axis)
             + np.log(np.exp(scaled - peak).mean(axis=axis))) / gamma


def _array(record, name, shape, integer=False):
    value = np.asarray(record[name])
    if value.shape != shape or value.dtype.kind not in "iuf" or not np.isfinite(value).all():
        raise ValueError("invalid registered score array: " + name)
    if integer and not np.equal(value, np.floor(value)).all():
        raise ValueError("integer evidence required: " + name)
    return value.astype(np.int64 if integer else np.float64)


def allocation_report(seed_results, protocol, development=False):
    """No checkpoint resampling; one paired draw per seed/root/world stratum.

    Draw order is bootstrap replicate, registered checkpoint order, q/mode root,
    then within-root replicate. All four arms share the same sampled indices.
    Mechanism/causality acceptance is deliberately left to execution audits.
    """
    seeds = ([protocol["development"]["study_seed"]] if development else protocol["seeds"])
    if set(seed_results) != set(seeds):
        raise ValueError("all and only registered study seeds must be complete")
    settings = protocol["development" if development else "confirmation"]
    replicates = settings["worlds_per_condition_initial_mode"]
    count = 32 * replicates
    arms = protocol["policies"]["arms"]
    if arms != ["dynamic", "initial_feedback_committed_open_loop", "myopic",
                "clean_no_disturbance_reference"]:
        raise ValueError("registered ordered four-arm experiment required")
    resource = protocol["resource_contract"]
    price, gamma = (protocol["objective"][key] for key in ("mac_price_lambda", "gamma"))
    decoder = np.array([resource["decoder_macs"][m] for m in MODALITIES], np.int64)
    refine = np.array([resource["refine_macs"][m] for m in MODALITIES], np.int64)
    losses = np.empty((len(seeds), 32, replicates, len(arms)), np.float64)
    returns, exact = np.empty_like(losses), np.empty((len(seeds), len(arms)), np.float64)
    arm_rows, costs = {arm: [] for arm in arms}, []
    for index, seed in enumerate(seeds):
        result = seed_results[seed]
        if set(result["arms"]) != set(arms):
            raise ValueError("all registered arms must be complete")
        planning = result["planning"]
        planning_macs = int(planning["tree_and_clean_forward_linear_macs"])
        if planning_macs != planning["tree_and_clean_forward_linear_macs"] or planning_macs <= 0:
            raise ValueError("actual nonzero planning work required")
        seed_cost = {"seed": seed, "shared_planning_linear_macs": planning_macs,
                     "planning_wall_seconds": float(planning["wall_seconds"]),
                     "planning_process_cpu_seconds": float(planning["process_cpu_seconds"]),
                     "online_linear_macs_by_arm": {}, "amortization_by_arm": {}}
        for column, arm in enumerate(arms):
            record = result["arms"][arm]
            ids = _array(record, "world_id", (count,), integer=True)
            if not np.array_equal(ids, np.arange(count)):
                raise ValueError("paired registered world order required")
            loss = _array(record, "loss", (count,))
            error = _array(record, "per_modality_error", (count, 4))
            contradiction = _array(record, "contradiction", (count,))
            macs = _array(record, "macs", (count,), integer=True)
            counts = _array(record, "refinement_counts", (count, 4), integer=True)
            if (np.any(error < 0) or np.any(error > 2) or np.any(contradiction < 0)
                    or np.any(contradiction > 1) or np.any(counts < 0)
                    or np.any(counts.sum(1) > 2)):
                raise ValueError("loss or resource evidence outside registered bounds")
            expected = resource["native_init_charge_macs"] + decoder.sum() + counts @ refine
            if (not np.array_equal(macs, expected) or np.any(macs > resource["budget_macs_all_arms"])
                    or np.max(np.abs(loss - error.mean(1) - .25 * contradiction)) > 1e-10):
                raise ValueError("resource or global-loss evidence does not reconcile")
            if arm == "clean_no_disturbance_reference" and np.any(counts):
                raise ValueError("clean reference cannot refine")
            losses[index, :, :, column] = loss.reshape(32, replicates)
            returns[index, :, :, column] = (-loss - price * macs).reshape(32, replicates)
            exact[index, column] = float(planning["root_J"][arm])
            row = {"seed": seed, "worlds": count, "mean_external_loss": float(loss.mean()),
                   "mean_per_modality_error": dict(zip(MODALITIES, error.mean(0).tolist())),
                   "mean_contradiction": float(contradiction.mean()),
                   "mean_refinement_counts": dict(zip(MODALITIES, counts.mean(0).tolist())),
                   "mean_allocated_linear_macs": dict(zip(MODALITIES,
                       (counts * refine + decoder).mean(0).tolist())),
                   "shared_init_macs_per_world": resource["native_init_charge_macs"],
                   "mean_online_linear_macs": float(macs.mean()),
                   "total_online_linear_macs": int(macs.sum()),
                   "refinement_depth_counts": np.bincount(counts.sum(1), minlength=3).tolist()}
            arm_rows[arm].append(row)
            seed_cost["online_linear_macs_by_arm"][arm] = int(macs.sum())
            seed_cost["amortization_by_arm"][arm] = {
                "N_1": planning_macs + float(macs.mean()),
                "N_1024": planning_macs / 1024 + float(macs.mean())}
        seed_cost["planning_and_online_linear_macs_subtotal"] = (
            planning_macs + sum(seed_cost["online_linear_macs_by_arm"].values()))
        costs.append(seed_cost)
    if not np.isfinite(exact).all():
        raise ValueError("finite exact compiled policy values required")
    root_ce = conditional_ce(returns, gamma, axis=2)
    per_seed_j, observed_j = root_ce.mean(1), root_ce.mean((0, 1))
    bootstrap = protocol["performance_analysis"]["bootstrap_replicates"]
    generator = np.random.default_rng(np.random.SeedSequence([5300000, 0]))
    boot_j, boot_loss = np.empty((bootstrap, len(arms))), np.empty((bootstrap, len(arms)))
    for index in range(bootstrap):
        draw = generator.integers(replicates, size=(len(seeds), 32, replicates))
        selected = np.take_along_axis(returns, draw[..., None], axis=2)
        boot_j[index] = conditional_ce(selected, gamma, axis=2).mean((0, 1))
        boot_loss[index] = np.take_along_axis(losses, draw[..., None], axis=2).mean((0, 1, 2))
    quantiles = protocol["performance_analysis"]["bootstrap_percentiles"]
    comparisons = {}
    for baseline in (1, 2):
        delta = boot_j[:, 0] - boot_j[:, baseline]
        interval = np.quantile(delta, quantiles, method="linear").tolist()
        loss_delta = boot_loss[:, 0] - boot_loss[:, baseline]
        comparisons[arms[baseline]] = {
            "sampled_J_difference": float(observed_j[0] - observed_j[baseline]),
            "sampled_J_paired_stratified_bootstrap_95_interval": interval,
            "exact_finite_model_J_difference": float((exact[:, 0] - exact[:, baseline]).mean()),
            "per_seed_sampled_J_difference": dict(zip(map(str, seeds),
                (per_seed_j[:, 0] - per_seed_j[:, baseline]).tolist())),
            "per_seed_exact_J_difference": dict(zip(map(str, seeds),
                (exact[:, 0] - exact[:, baseline]).tolist())),
            "mean_external_loss_difference": float((losses[..., 0] - losses[..., baseline]).mean()),
            "mean_external_loss_paired_bootstrap_95_interval": np.quantile(
                loss_delta, quantiles, method="linear").tolist(),
            "interval_lower_strictly_positive": bool(interval[0] > 0),
            "inference_role": "registered primary" if baseline == 1 else "descriptive unadjusted secondary"}
    arm_summary = {}
    for column, arm in enumerate(arms):
        rows = arm_rows[arm]
        arm_summary[arm] = {"worlds": len(seeds) * count,
            "sampled_J": float(observed_j[column]), "exact_finite_model_J": float(exact[:, column].mean()),
            "mean_external_loss": float(losses[..., column].mean()),
            "mean_online_linear_macs": float(np.mean([row["mean_online_linear_macs"] for row in rows])),
            "total_online_linear_macs": sum(row["total_online_linear_macs"] for row in rows),
            "mean_per_modality_error": {m: float(np.mean([row["mean_per_modality_error"][m]
                                                          for row in rows])) for m in MODALITIES},
            "mean_contradiction": float(np.mean([row["mean_contradiction"] for row in rows])),
            "mean_refinement_counts": {m: float(np.mean([row["mean_refinement_counts"][m]
                                                         for row in rows])) for m in MODALITIES},
            "mean_allocated_linear_macs": {m: float(np.mean([row["mean_allocated_linear_macs"][m]
                                                             for row in rows])) for m in MODALITIES},
            "refinement_depth_counts": np.sum([row["refinement_depth_counts"] for row in rows], axis=0).tolist(),
            "per_seed": [{**row, "sampled_J": float(per_seed_j[index, column]),
                          "exact_finite_model_J": float(exact[index, column]),
                          "conditional_root_CE": root_ce[index, :, column].tolist()}
                         for index, row in enumerate(rows)]}
    primary = comparisons[arms[1]]
    return {"schema": "hepta.modality-allocation.report.v4", "development": bool(development),
            "confirmatory": not development, "seeds": seeds, "arms": arm_summary,
            "comparisons_dynamic_minus": comparisons,
            "primary_superiority_passed": bool(not development and primary["interval_lower_strictly_positive"]),
            "mechanism_gate": "requires independent actual-trajectory/native/sibling audit",
            "bootstrap": {"replicates": bootstrap, "rng_seed_sequence": [5300000, 0],
                "paired_across_arms": True, "checkpoint_resampling": False,
                "draw_order": "bootstrap, registered checkpoint, q/mode root, within-root draw",
                "strata": len(seeds) * 32, "observations_per_stratum": replicates,
                "quantile_method": "linear", "gamma": gamma,
                "scope": "Approximate execution-sampling uncertainty conditional on fixed checkpoints and finite support; empirical CE is a finite-sample plug-in estimate."},
            "costs": {"per_seed": costs,
                "planning_and_online_linear_macs_subtotal": sum(row[
                    "planning_and_online_linear_macs_subtotal"] for row in costs),
                "accounting": "One full-tree/clean planning cache per checkpoint, shared by all arms. N=1/1024 shows that complete planner amortized over N worlds for one arm. Subtotal excludes separately metered encoder-contract checks, development and independent audits; it is not total FLOPs, energy or wall time."}}
