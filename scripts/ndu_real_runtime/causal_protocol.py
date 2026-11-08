"""Prospective A--E comparisons; a protocol never grants execution or adoption."""

import argparse
from itertools import product
import json
from pathlib import Path

from .metering import atomic_json, canonical_sha

COST_STAGES = (
    "preparation",
    "collection",
    "training",
    "search",
    "controller",
    "messages",
    "reencoding",
    "graph_compile",
    "evaluation",
    "migration",
    "recovery",
    "io",
)
COST_UNITS = ("wall_seconds", "cpu_seconds", "energy_joules", "provider_charges")
COMMON_MATCHES = (
    "model_access",
    "information",
    "external_memory",
    "tools",
    "training_data",
    "tuning_data",
    "evaluation_data",
    "training_opportunity",
    "tuning_opportunity",
    "recovery_mechanism",
    "resource_limits",
    "evaluation_rule",
)


def digest(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


def protocol(source_commit, source_tree, seeds):
    """Freeze questions and complete arms without fabricating implementation."""
    for value in (source_commit, source_tree):
        if (
            not isinstance(value, str)
            or len(value) != 40
            or any(c not in "0123456789abcdef" for c in value)
        ):
            raise ValueError("Exact Git commit and tree are required")
    if (
        not 2 <= len(seeds) <= 16
        or len(set(seeds)) != len(seeds)
        or any(type(s) is not int or not 0 <= s < 2**32 for s in seeds)
    ):
        raise ValueError("Distinct independently initialized training seeds required")
    b_arms = [
        {
            "id": f"{core}/{control}/{mode}",
            "core": core,
            "controller": control,
            "memory_mode": mode,
        }
        for core, control, mode in product(
            ("ordinary", "hepta"),
            ("light", "ndu", "tuned_fixed", "voi", "mpc"),
            ("reset", "persistent"),
        )
    ]
    a_arms = [
        "single_agent",
        "fixed_roles",
        "differentiated_cells",
        "cells_without_state",
        "cells_without_differentiation",
    ]
    result = {
        "schema": "hepta.cell-causal.protocol.v1",
        "source": {"commit": source_commit, "tree": source_tree},
        "training_seeds": list(seeds),
        "sample_unit": "independent complete training or improver replicate",
        "task_unit": "registered source group; episodes nested within group",
        "common_matching_dimensions": list(COMMON_MATCHES),
        "required_cost_stages": list(COST_STAGES),
        "cost_units": list(COST_UNITS),
        "cost_policy": {
            "unknown_is_zero": False,
            "nested_envelopes_are_additive": False,
            "shared_cost": "full standalone charge to each benefitting method; physical event counted once in campaign total",
            "failed_cancelled_unknown_in_denominator": True,
            "research_evaluation_inference_already_included": True,
            "amortization_counts": [100, 1000, 10000],
        },
        "experiments": {
            "A": {
                "arms": a_arms,
                "primary_contrasts": [
                    {"differentiated_cells": 1, "single_agent": -1},
                    {"differentiated_cells": 1, "fixed_roles": -1},
                ],
                "additional_required": "predeclare removed roles before outcomes; match access and training in every ablation",
                "capability_gate": "actual separate local state and trainable differentiation; heads or labels alone do not qualify",
            },
            "B": {
                "arms": b_arms,
                "regimes": ["frozen", "joint"],
                "estimands": ["matched_training", "deployment_state_ablation"],
                "primary_contrasts": b_contrasts(),
                "comparison_policy": "same observations, labels, batch boundaries and opportunities; record actual optimizer steps and full cost",
                "deployment_ablation": "same checkpoint within each pair; preserve training mode; requires an explicit supported deployment profile",
            },
            "C": {
                "arms": [
                    "none",
                    "A_only",
                    "B_only",
                    "A_plus_B",
                    "shared_base_then_combine",
                ],
                "state_transitions": ["reset", "migrate"],
                "interaction": {"A_plus_B": 1, "A_only": -1, "B_only": -1, "none": 1},
                "required": [
                    "complete compatible composition",
                    "original owner selection",
                    "different next task consumes full bundle",
                    "state transition receipt",
                    "model rollback",
                    "separate external effect recovery",
                ],
            },
            "D": {
                "arms": [
                    "fixed_graph_adaptive_scheduler",
                    "dynamic_graph_same_scheduler",
                ],
                "required_operations": ["split", "merge", "rewire"],
                "required": [
                    "actual successor execution graph",
                    "actual message reachability",
                    "state ownership transition",
                    "next task trace",
                    "recovery",
                    "equal maximum capacity and useful routing opportunities",
                ],
            },
            "E": {
                "arms": ["parent_improver", "descendant_improver"],
                "required": [
                    "same starting target bundle",
                    "versioned improver itself",
                    "same full improvement budget",
                    "all attempted candidates",
                    "independent evaluation",
                    "unseen target tasks",
                    "descendant construction cost",
                    "rollback outcomes",
                ],
                "metrics": [
                    "valid/all_attempted",
                    "accepted/all_attempted",
                    "accepted/valid_resolved",
                    "net_quality_change",
                    "total_cost",
                    "rollback_rate",
                    "unseen_task_change",
                ],
            },
        },
        "statistics": {
            "primary_outcome": "source-balanced paired quality and full resource cost",
            "within_fit_episodes_are_independent_fits": False,
            "resampling": "crossed paired fit and source-group bootstrap; descriptive pilot only",
            "alpha": 0.05,
            "confirmatory_use": False,
            "future_confirmation": "freeze independent evaluator, new fits/groups, effect threshold, multiplicity and power before access",
        },
        "execution_started": False,
        "scientific_acceptance": "HOLD",
        "adoption_authorized": False,
    }
    return result


def b_contrasts():
    contrasts = {}
    for mode in ("reset", "persistent"):
        ol, on = f"ordinary/light/{mode}", f"ordinary/ndu/{mode}"
        hl, hn = f"hepta/light/{mode}", f"hepta/ndu/{mode}"
        contrasts.update(
            {
                f"ndu_in_ordinary/{mode}": {on: 1, ol: -1},
                f"ndu_in_hepta/{mode}": {hn: 1, hl: -1},
                f"hepta_under_ndu/{mode}": {hn: 1, on: -1},
                f"hepta_under_light/{mode}": {hl: 1, ol: -1},
                f"kernel_controller_interaction/{mode}": {hn: 1, hl: -1, on: -1, ol: 1},
            }
        )
        for core, baseline in product(
            ("ordinary", "hepta"), ("tuned_fixed", "voi", "mpc")
        ):
            contrasts[f"ndu_vs_{baseline}/{core}/{mode}"] = {
                f"{core}/ndu/{mode}": 1,
                f"{core}/{baseline}/{mode}": -1,
            }
    for core, control in product(
        ("ordinary", "hepta"), ("light", "ndu", "tuned_fixed", "voi", "mpc")
    ):
        contrasts[f"persistent_minus_reset/{core}/{control}"] = {
            f"{core}/{control}/persistent": 1,
            f"{core}/{control}/reset": -1,
        }
    contrasts["three_way_interaction"] = {
        **contrasts["kernel_controller_interaction/persistent"],
        **{k: -v for k, v in contrasts["kernel_controller_interaction/reset"].items()},
    }
    return contrasts


def match_contracts(arms, *, allowed_differences=()):
    """Check declared matched contracts; authenticity is independently required."""
    if len(arms) < 2 or len({a["arm_id"] for a in arms}) != len(arms):
        raise ValueError("At least two uniquely identified arms are required")
    allowed = set(allowed_differences)
    if allowed - set(COMMON_MATCHES):
        raise ValueError("Unknown matching dimension")
    for arm in arms:
        if set(arm["matches"]) != set(COMMON_MATCHES) or not all(
            digest(v) for v in arm["matches"].values()
        ):
            raise ValueError("Each matching dimension needs a frozen artifact digest")
    differences = [
        key
        for key in COMMON_MATCHES
        if key not in allowed and len({a["matches"][key] for a in arms}) != 1
    ]
    return {
        "declared_matching": not differences,
        "mismatches": differences,
        "authenticity_proved": False,
        "adoption_authorized": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=[104729, 130363])
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    value = protocol(args.source_commit, args.source_tree, args.seeds)
    sha = atomic_json(args.output, value)
    print(
        json.dumps(
            {
                "path": str(args.output),
                "sha256": sha,
                "protocol_id": canonical_sha(value),
                "executed": False,
            }
        )
    )


if __name__ == "__main__":
    main()
