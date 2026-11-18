"""One pre-execution comparison for the old exposed A6/B3 development panel."""

import copy
from dataclasses import asdict
from pathlib import Path

from .. import data
from ..coding_sft import file_hash
from .circuit_contract import Budget, Graph
from .onpolicy_contract import SCOPE, require
from .onpolicy_loop import make_freeze

MODES = ("teacher", "shadow", "controlled")
INPUTS_SHA256 = "691945696e7dad9ee0f3023617edf5ca0f787850c16f2623c08d14bc6cfbeaf3"
MANIFEST_SHA256 = {
    "final_answer": "efba23ea6f5f5f7c8e250cea3b4299dfe9b92511deb2a73955dfc6d4cf550ebf",
    "trajectory": "63ea06c2e8813252a19aaa22ca05166e451dc9d888459ed16373f19f24aacab2",
    "controlled_correction": "c0198d6578d6a5fed99cf1c81eb88b0186f92ffacbdb43712e5200564de79c25",
}
CELL_MODES = {"F": "final_answer", "T": "trajectory", "C": "controlled_correction"}
CONTEXT_REVIEW = {
    "scope": "new message relay only; original task and native chat protocol unchanged",
    "relay_max_bytes": 2048,
    "possible_over_1000_tokens": True,
    "reviewed": True,
    "reason": "One bounded JSON tool message carries only the first output and stable feedback; "
    "no target, verifier internals, exceptions or previous hidden assistant copy.",
    "total_prompt_token_gate": 4096,
    "overflow_behavior": "preserve evidence and fail; never truncate or enlarge a running budget",
    "new_model_calls_per_task_max": 2,
}


def read_pinned(path, sha256):
    path = Path(path)
    require(
        path.is_file() and not path.is_symlink() and file_hash(path) == sha256,
        "original frozen file differs: " + str(path),
    )
    return data._parse(path.read_bytes())


def material_inputs(root):
    root = Path(root)
    context = read_pinned(root / "research-sft-02/INPUTS.json", INPUTS_SHA256)
    manifests = {}
    for mode, sha256 in MANIFEST_SHA256.items():
        path = (
            root
            / "research-sft-02/workers"
            / (mode + "-primary/research-model/manifest.json")
        )
        manifests[mode] = read_pinned(path, sha256)
    return context, manifests


def panels(context):
    records = context["records"]
    require(
        len(records) == 9 and len({row["task_id"] for row in records}) == 9,
        "the original nine development tasks are required",
    )
    a, b = records[:6], records[6:]
    require(
        all(row["split"] == "train" for row in a)
        and all(row["split"] == "selection" for row in b),
        "fixed A6/B3 ordering changed",
    )
    require(
        all(
            row["origin_kind"] == "curated_development"
            and row["exposure"] == "development"
            for row in records
        ),
        "this run is limited to the actual exposed development panel",
    )
    return {"old_A": copy.deepcopy(a), "old_B": copy.deepcopy(b)}


def graph_candidates():
    return [
        Graph("ff_both", ("F", "F")),
        Graph("tf_both", ("T", "F")),
        Graph("cf_both", ("C", "F")),
        Graph("tf_answer", ("T", "F"), ("answer",)),
        Graph("tf_feedback", ("T", "F"), ("feedback",)),
        Graph("tf_none", ("T", "F"), ()),
    ]


def compare_freezes(freezes):
    require(set(freezes) == set(MODES), "all three E2 controls must be frozen together")
    for mode, freeze in freezes.items():
        require(
            freeze["collection_mode"] == mode
            and freeze["rounds"] == 2
            and freeze["steps_per_round"] == 64
            and freeze["maximum_attempts"] == 2
            and freeze["optimizer_initialization"] == "fresh_AdamW_each_round"
            and freeze["weight_initialization"] == "previous_candidate_adapter"
            and freeze["retention"] == "latest_round_only",
            "E2 comparison budget differs",
        )
    for key in (
        "initial_model_digest",
        "context_digest",
        "A_records_digest",
        "source_inventory",
    ):
        require(
            len({data.digest(value[key]) for value in freezes.values()}) == 1,
            "E2 controls differ in " + key,
        )


def make_comparison(context, manifests, backend, operation_id, entrypoint_inventory):
    panel = panels(context)
    initial = manifests["final_answer"]
    freezes = {
        mode: make_freeze(
            context,
            initial,
            backend,
            operation_id=operation_id + "/" + mode,
            mode=mode,
            rounds=2,
            maximum=2,
        )
        for mode in MODES
    }
    compare_freezes(freezes)
    cells = {
        key: {
            "source_mode": mode,
            "manifest_digest": backend.verify_model(manifests[mode]),
            "original_manifest_sha256": MANIFEST_SHA256[mode],
        }
        for key, mode in CELL_MODES.items()
    }
    body = {
        "schema": "hepta.online-round03-comparison.v1",
        "operation_id": operation_id,
        "old_inputs_sha256": INPUTS_SHA256,
        "context_digest": data.digest(context),
        "panel_digests": {key: data.digest(value) for key, value in panel.items()},
        "source_inventory": backend.sources(),
        "entrypoint_inventory": entrypoint_inventory,
        "E2": {
            "freezes": freezes,
            "common_initial": data.digest(initial),
            "teacher_meaning": "existing verified authored A reference; zero external teacher calls",
            "collection_and_training_costs_are_not_assumed_equal": True,
        },
        "E4": {
            "cells": cells,
            "graphs": [asdict(graph) for graph in graph_candidates()],
            "budget": asdict(
                Budget(max_output_tokens_per_call=384, max_relay_bytes=2048)
            ),
            "fixed_graph": asdict(Graph("fixed_tf", ("T", "F"))),
            "single_cell": "F",
            "random_seed": 1729,
            "router": {
                "feature_dimensions": 16,
                "ridge": 1.0,
                "output_token_penalty": 0.0,
                "model_call_penalty": 0.0,
            },
            "training_panel": "old_A",
            "context_review": CONTEXT_REVIEW,
            "output_selection": "earliest_business_success_else_last_surviving",
            "actual_cost_matching_claim": False,
            "search_cost_must_be_retained": True,
        },
        "execution": {
            "automatic_retry": False,
            "workers_are_serial": True,
            "cold_process_must_differ": True,
            "optimizer_resume": False,
        },
        **SCOPE,
    }
    return data._parse(data.canonical({**body, "comparison_digest": data.digest(body)}))


def check_comparison(freeze, context, manifests, backend, entrypoint_inventory):
    expected = make_comparison(
        context, manifests, backend, freeze.get("operation_id"), entrypoint_inventory
    )
    require(freeze == expected, "comparison source, data, candidate, or budget changed")
    return panels(context)
