"""Precommitted finite research claims, budgets and source identities."""

import hashlib
from importlib.metadata import version
from pathlib import Path
import platform
import subprocess

from native import digest
from prepare_parametric import REPOSITORY, REVISION

SEEDS = (1907, 2719, 4051)


def protocol():
    return {
        "schema": "hepta.memory-population.protocol.v1",
        "seeds": list(SEEDS),
        "model": REPOSITORY,
        "model_revision": REVISION,
        "model_seed": "cohort seed + 10000",
        "identical_source_and_runtime_identity_across_seeds": True,
        "parent": {"rank": 4, "source_examples": 16, "updates": 512},
        "single": {"rank": 8, "source_examples": 64, "updates": 1024},
        "split": {
            "rank_per_cell": 4,
            "cells": 2,
            "source_examples_per_cell": 32,
            "updates_per_cell": 512,
        },
        "optimizer": {
            "name": "AdamW",
            "learning_rate": 0.001,
            "candidate_visits_per_example": 16,
        },
        "partition": {
            "input": "actual source-only parent LoRA gradients",
            "probe_forwards_backwards": 64,
            "optimizer_updates": 0,
            "sketch_dimensions": 32,
            "maximum_iterations": 16,
            "whole_dependency_groups": True,
            "family_labels_as_features": False,
        },
        "parent_expansion": "verified function-preserving rank 4 to 8, zero new B columns",
        "budget": "equal candidate optimizer updates, source visits, input tokens and adapter tensor bytes",
        "unmatched_costs": [
            "gradient probe",
            "router",
            "lineage",
            "owner database",
            "model loading",
            "wall time",
            "all diagnostic expert reads",
        ],
        "source_selection": {
            "parent_semantic_minimum": 0.75,
            "preserve_each_parent_correct_semantic": True,
            "single_gain_examples": 1,
            "split_gain_examples": 4,
            "router_overhead_fraction_maximum": 0.01,
            "ties_choose_cheaper": True,
        },
        "final_probes": {
            "retention": 64,
            "event_interpolation": 16,
            "procedure_extrapolation": 16,
            "unsupported": 24,
            "additional_parent_semantic_if_not_selected": 16,
        },
        "split_gate": {
            "mean_retention_gain": 0.05,
            "each_seed_gain_minimum": 0.0,
            "preserve_parent_correct_source_selection": True,
            "parent_final_semantic_minimum": 0.75,
            "preserve_every_parent_correct_final_semantic": True,
        },
        "router_gate": {
            "supported_coverage_minimum": 0.75,
            "eligible_oracle_recall_minimum": 0.75,
            "eligible_oracle_regret_maximum": 0.05,
            "gain_over_expected_uniform_random_minimum": 0.05,
            "gain_over_metadata_capability_minimum": 0.05,
            "raw_ood_reject_minimum": 0.90,
        },
        "heterogeneous_gate": {
            "minimum_each_retention_family_each_seed": 0.75,
            "minimum_each_transfer_family_each_seed": 0.75,
        },
        "codec": {
            "fixed_candidate": "single",
            "primary_bits": 8,
            "secondary_bits": 4,
            "packed_complete_ratio_maximum": 0.35,
            "retention_loss_maximum": 0.02,
            "transfer_loss_maximum": 0.02,
            "quantized_execution": False,
            "posthoc_bitwidth_selection": False,
        },
        "net_compression_gate": "complete retained system including shared base, ledger, router, versions and owners must beat the smallest exact full-source representation at equal supported quality",
        "exact_baselines": [
            "complete JSON",
            "zlib9",
            "LZMA6",
            "SQLite",
            "public seed plus retained fixture generator",
        ],
        "capability_guard": "supplied structured operation and source metadata; not learned parsing",
        "frontier": "new isolated cohort, epoch 1; no claim of external live authority",
        "termination": "run all three seeds and both codecs; preserve every negative result",
        "general_memory_proven": False,
        "production_accepted": False,
    }


def source_identity():
    root = Path(__file__).resolve().parents[1]
    directories = (
        "memory_cell",
        "memory_cell_growth",
        "memory_cell_catalog",
        "memory_cell_hardening",
        "memory_cell_router",
        "memory_cell_codec",
        "memory_cell_population",
    )
    paths = sorted(p for name in directories for p in (root / name).glob("*.py"))
    files = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in paths
    }
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    return {
        "git_head": head,
        "files_sha256": files,
        "source_manifest_sha256": digest(files),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "dependencies": {
            name: version(name)
            for name in (
                "torch",
                "transformers",
                "peft",
                "numpy",
                "safetensors",
                "tokenizers",
                "accelerate",
                "huggingface-hub",
            )
        },
    }
