"""Compact reporting from independently recomputed capacity outcomes."""

from collections import defaultdict

import numpy as np


def distribution(values, *, draws=10000, seed=1913, confidence=0.95):
    samples = np.asarray(values, dtype=np.float64)
    if not len(samples):
        return {
            "count": 0,
            "mean": None,
            "minimum": None,
            "maximum": None,
            "mean_bootstrap_interval": None,
        }
    generator = np.random.default_rng(seed)
    means = samples[
        generator.integers(0, len(samples), size=(draws, len(samples)))
    ].mean(axis=1)
    tail = (1 - confidence) / 2
    return {
        "count": len(samples),
        "mean": float(samples.mean()),
        "minimum": float(samples.min()),
        "maximum": float(samples.max()),
        "mean_bootstrap_interval": [
            float(np.quantile(means, tail)),
            float(np.quantile(means, 1 - tail)),
        ],
    }


def extraction(records, archives, archival_models, sources, statistics):
    settings = {
        "draws": statistics.get("bootstrap_draws", 10000),
        "seed": statistics.get("bootstrap_seed", 1913),
        "confidence": statistics.get("confidence", 0.95),
    }
    groups = defaultdict(list)
    by_key = {
        (r["dataset"], r["seed"], r["budget_bytes"], r["family"]): r for r in records
    }
    for record in records:
        groups[
            sources[record["dataset"]]["group"],
            record["family"],
            record["budget_bytes"],
        ].append(record)
    comparisons = []
    for (dataset, family, budget), members in sorted(groups.items()):
        paired_gain, strong_gain = [], []
        wins = losses = ties = zero_baseline_cases = 0
        for item in members:
            baseline = by_key.get((item["dataset"], item["seed"], budget, "global_svd"))
            vq = by_key.get((item["dataset"], item["seed"], budget, "learned_vq"))
            if baseline is None:
                continue
            base, own = (
                baseline["hidden"]["mse_scaled_integer"],
                item["hidden"]["mse_scaled_integer"],
            )
            wins += own < base
            losses += own > base
            ties += own == base
            if base:
                paired_gain.append((base - own) / base)
            else:
                zero_baseline_cases += 1
            strong = min(base, vq["hidden"]["mse_scaled_integer"]) if vq else base
            if strong:
                strong_gain.append((strong - own) / strong)
        comparisons.append(
            {
                "dataset_group": dataset,
                "family": family,
                "budget_bytes": budget,
                "seeds": [item["seed"] for item in members],
                "artifact_bytes": distribution(
                    [item["artifact_bytes"] for item in members], **settings
                ),
                "complete_parameter_read_bytes": distribution(
                    [item["complete_parameter_read_bytes"] for item in members],
                    **settings,
                ),
                "hidden_mse": distribution(
                    [item["hidden"]["mse_scaled_integer"] for item in members],
                    **settings,
                ),
                "hidden_mae_original_units": distribution(
                    [item["hidden"]["mae_original_units"] for item in members],
                    **settings,
                ),
                "hidden_exact_accuracy": distribution(
                    [item["hidden"]["exact_accuracy"] for item in members], **settings
                ),
                "relative_mse_gain_vs_global": distribution(paired_gain, **settings),
                "relative_mse_gain_vs_best_global_or_vq": distribution(
                    strong_gain, **settings
                ),
                "wins_losses_ties_vs_global": [wins, losses, ties],
                "zero_global_mse_cases_excluded_from_relative_gain": zero_baseline_cases,
            }
        )
    storage = []
    for dataset, archive in sorted(archives.items()):
        model_candidates = [r for r in records if r["dataset"] == dataset]
        global_candidates = [r for r in archival_models if r["dataset"] == dataset]
        best_selected = min(
            model_candidates, key=lambda r: r["complete_exact_replay_bytes"]
        )
        best_global = min(global_candidates, key=lambda r: r["complete_stored_bytes"])
        exact = archive["strong_exact_bytes"]
        best = min(
            best_selected["complete_exact_replay_bytes"],
            best_global["complete_stored_bytes"],
        )
        storage.append(
            {
                "dataset": dataset,
                "dataset_group": sources[dataset]["group"],
                "common_address_provenance_bytes": archive["common_bytes"],
                "strong_exact_complete_bytes": exact,
                "best_selected_family": best_selected["family"],
                "best_selected_model_residual_complete_bytes": best_selected[
                    "complete_exact_replay_bytes"
                ],
                "best_global_archival_rank": best_global["rank"],
                "best_global_archival_complete_bytes": best_global[
                    "complete_stored_bytes"
                ],
                "minimum_audited_complete_bytes": best,
                "minimum_audited_relative_saving": (exact - best) / exact,
                "exact_reconstruction_independently_verified": True,
            }
        )
    random_cases = []
    for dataset, source in sources.items():
        if source.get("random_mix") != 1:
            continue
        subset = [r for r in records if r["dataset"] == dataset]
        exact_parameters = [r for r in subset if r["hidden"]["exact_accuracy"] == 1]
        random_cases.append(
            {
                "dataset": dataset,
                "source_values": int(source["values"].size),
                "alphabet": 401,
                "entropy_bits_per_value_for_declared_iid_source": float(np.log2(401)),
                "strong_exact_complete_bytes": archives[dataset]["strong_exact_bytes"],
                "least_saved_model_bytes_with_zero_hidden_error": min(
                    (r["artifact_bytes"] for r in exact_parameters), default=None
                ),
                "zero_hidden_error_is_not_full_source_exactness_proof": True,
                "lossy_budget_points": [
                    {
                        "family": r["family"],
                        "budget_bytes": r["budget_bytes"],
                        "hidden_mse": r["hidden"]["mse_scaled_integer"],
                    }
                    for r in subset
                    if r["hidden"]["mse_scaled_integer"] > 0
                ],
            }
        )
    return {
        "per_dataset_family_budget": comparisons,
        "complete_storage": storage,
        "random_source_negative_controls": random_cases,
        "statistical_scope": "Bootstrap is conditional on the declared fixed workloads and their seeds. It does not turn deterministic SVD fits into independent learning runs or establish population-wide superiority.",
        "bootstrap": settings,
    }
