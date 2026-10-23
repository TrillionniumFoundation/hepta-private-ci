"""Independently pinned clean parent and fixed, pre-output arrival recipe."""

import hashlib
import json
from pathlib import Path
import random
import subprocess

import torch

from growth_policy import RULE
from native import digest
from parametric_cohort import TRAIN_TEMPLATES, SELECT_TEMPLATE, TEST_TEMPLATE
from parametric_owner import Frontier
from tensor_contract import bounded_read, strict_json

PARENT_SHA = "c273d4555cc0dbb105fc38a674ac6963a43cf48c58d9fced6a38e373759c2e05"
SOURCE_SHA = "1e2ee44982654500732596e6d41e4f7222702ce3b187f2eb1fced0c24afd70ce"
PROVENANCE_SHA = "ac920436b96e5dd9e2646add53db932d63b8d0f890a9675c9eca1beb587f430d"
SHAPES = ("circle", "square", "triangle", "oval", "star", "cube", "sphere", "cone")
ARRIVAL_SEED = 718203
MODEL_SEED = 2718
SINGLE_STEPS = 480
LR = 0.001


def source_identity():
    here = Path(__file__).resolve().parent
    directories = (
        here,
        here.parent / "memory_cell",
        here.parent / "memory_cell_catalog",
    )
    paths = [path for directory in directories for path in directory.glob("*.py")]
    paths.extend((here / "fixtures").glob("*.json"))
    files = {
        str(path.relative_to(here.parent)): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(paths)
    }
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=here, text=True
    ).strip()
    return {
        "git_head": head,
        "files_sha256": files,
        "source_manifest_sha256": digest(files),
        "torch": torch.__version__,
    }


def protocol():
    return {
        "schema": "hepta.parametric-memory.arrival-protocol.v1",
        "parent_manifest_sha256": PARENT_SHA,
        "parent_source_file_sha256": SOURCE_SHA,
        "parent_provenance_file_sha256": PROVENANCE_SHA,
        "old_count": 15,
        "incoming_count": 15,
        "incoming_relation": "shape",
        "shape_vocabulary": list(SHAPES),
        "shape_seed": ARRIVAL_SEED,
        "shape_assignment": "duplicate vocabulary, shuffle once, then retain first 15",
        "rank": 8,
        "model_seed": MODEL_SEED,
        "learning_rate": LR,
        "single_steps": SINGLE_STEPS,
        "split_steps_per_cell": SINGLE_STEPS // 2,
        "train_templates": list(TRAIN_TEMPLATES),
        "selection_template": SELECT_TEMPLATE,
        "final_template": TEST_TEMPLATE,
        "selection_rule": RULE,
        "single_minimum_selection_gain": 1,
        "split_minimum_gain_over_eligible_cheaper": 2,
        "selected_old_recall_minimum": 0.75,
        "selected_new_recall_minimum": 0.75,
        "old_parent_correct_items_must_be_preserved": True,
        "matched_parameter_budget_claimed": False,
        "typed_namespace_router": {"color": 0, "shape": 1},
        "source_frontier_epoch": 1,
        "live_external_frontier_claimed": False,
        "production_accepted": False,
    }


def _pinned_json(path, expected, limit, *, array=False):
    raw = bounded_read(Path(path), limit)
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("input differs from independently retained pin")
    return json.loads(raw) if array else strict_json(raw)


def parent_inputs(parent_dir, source_facts):
    provenance = _pinned_json(
        Path(__file__).resolve().parent / "fixtures/parent-provenance.json",
        PROVENANCE_SHA,
        128 * 1024,
    )
    old = _pinned_json(source_facts, SOURCE_SHA, 128 * 1024, array=True)
    manifest = _pinned_json(Path(parent_dir) / "lineage.json", PARENT_SHA, 256 * 1024)
    if type(old) is not list or len(old) != 15:
        raise ValueError("registered fifteen-source clean parent required")
    frontier = Frontier(provenance["scope"], provenance["epoch"], provenance["revoked"])
    roots = {row["source_digest"] for row in old}
    training = manifest["training"]
    if (
        provenance["active_manifest_sha256"] != PARENT_SHA
        or provenance["parent_source_file_sha256"] != SOURCE_SHA
        or provenance["parent_source_facts_digest"] != digest(old)
        or set(manifest["roots"]) != roots
        or training["source_facts_sha256"] != digest(old)
        or any(row["scope"] != frontier.scope for row in old)
        or roots & set(frontier.revoked)
        or frontier.epoch != 1
        or training["initialization"] != "frozen_base"
        or training["learned_parent_manifest_sha256"] is not None
        or training["inherited_roots"]
    ):
        raise ValueError("parent must bind the clean active source cohort and frontier")
    actual_cost = {key: training[key] for key in ("steps", "input_tokens", "seconds")}
    if provenance["historical_writes"]["clean_replay"] != actual_cost:
        raise ValueError("inherited parent cost differs from retained replay receipt")
    return old, manifest, provenance, frontier


def shape_arrivals(old):
    if not 1 <= len(old) <= 16:
        raise ValueError("registered shape assignment bound exceeded")
    values = list(SHAPES) * 2
    random.Random(ARRIVAL_SEED).shuffle(values)
    rows = []
    for previous, value in zip(old, values[: len(old)], strict=True):
        source = {
            "scope": previous["scope"],
            "entity": previous["entity"],
            "relation": "shape",
            "value": value,
        }
        rows.append(
            source
            | {"source_digest": digest(["hepta.parametric.shape-arrival.v1", source])}
        )
    return rows
