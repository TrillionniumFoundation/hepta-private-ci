"""Real warm-parent writes and value-free typed routing for an arrival trial."""

import math
from pathlib import Path
import re
from dataclasses import asdict

from growth_policy import ARMS, choose_growth
from parametric_cohort import questions
from parametric_model import FACT_FIELDS, adapter_digest
from parametric_owner import Frontier
from pretrained import file_inventory, frozen_digest


def validate_arrival(old, incoming, templates, single_steps):
    if (
        type(old) is not list
        or type(incoming) is not list
        or not 1 <= len(old) <= 64
        or len(old) != len(incoming)
    ):
        raise ValueError("matched bounded old and incoming cohorts required")
    if (
        type(templates) is not list
        or not 1 <= len(templates) <= 8
        or type(single_steps) is not int
        or not 2 * len(old) * len(templates) <= single_steps <= 4096
        or single_steps % 2
    ):
        raise ValueError("bounded even work covering every source/template required")
    all_facts = old + incoming
    for row in all_facts:
        if (
            type(row) is not dict
            or set(row) != FACT_FIELDS
            or any(
                type(v) is not str or not 1 <= len(v.encode()) <= 1024
                for v in row.values()
            )
            or re.fullmatch(r"[0-9a-f]{64}", row["source_digest"]) is None
        ):
            raise ValueError("exact bounded source facts required")
    if (
        len({row["scope"] for row in all_facts}) != 1
        or any(row["relation"] != "color" for row in old)
        or any(row["relation"] != "shape" for row in incoming)
    ):
        raise ValueError("one scope and declared color/shape namespaces required")
    if (
        len({row["source_digest"] for row in all_facts}) != len(all_facts)
        or len({row["entity"] for row in old}) != len(old)
        or [row["entity"] for row in old] != [row["entity"] for row in incoming]
    ):
        raise ValueError("unique roots and matched ordered entities required")


def typed_slot(arm, relation):
    """Only declared namespace metadata routes a key; no answer is inspected."""
    if arm not in ARMS or relation not in ("color", "shape"):
        raise ValueError("unknown arm or relation namespace")
    return int(arm == "split" and relation == "shape")


def _version(directory, manifest, roots):
    return {
        "directory": str(Path(directory).resolve()),
        "manifest_sha256": manifest,
        "roots": sorted(roots),
    }


def _load(cell, version, scope, frontier):
    cell.load(
        Path(version["directory"]),
        expected_manifest_sha256=version["manifest_sha256"],
        scope=scope,
        allowed_roots=set(version["roots"]),
        revoked=set(frontier.revoked),
    )


def _checkpoint_bytes(versions):
    directories = {row["directory"] for row in versions}
    return sum(
        item["bytes"]
        for directory in directories
        for item in file_inventory(Path(directory)).values()
    )


def _losses(receipt, facts, template_count):
    result = {}
    for relation in ("color", "shape"):
        values = [
            loss
            for index, loss in zip(
                receipt["schedule_indices"], receipt["losses"], strict=True
            )
            if facts[index // template_count]["relation"] == relation
        ]
        result[relation] = {
            "updates": len(values),
            "mean_completion_ce": sum(values) / len(values) if values else None,
            "first_completion_ce": values[0] if values else None,
            "last_completion_ce": values[-1] if values else None,
        }
    return result


def train_candidates(
    cell,
    *,
    old,
    incoming,
    parent,
    frontier,
    output,
    single_steps,
    learning_rate,
    templates,
    selection_template,
    final_template,
    write_json,
):
    """Train source-defined candidates; persist selection before final reads."""
    validate_arrival(old, incoming, templates, single_steps)
    if (
        type(learning_rate) not in (int, float)
        or not math.isfinite(learning_rate)
        or not 0 < learning_rate <= 0.1
    ):
        raise ValueError("bounded learning rate required")
    facts, scope = old + incoming, old[0]["scope"]
    if type(frontier) is not Frontier or frontier.scope != scope:
        raise ValueError("independently supplied scope frontier required")
    if {row["source_digest"] for row in facts} & set(frontier.revoked):
        raise ValueError("withdrawn source cannot enter parent or arrival training")
    if set(parent["roots"]) != {row["source_digest"] for row in old}:
        raise ValueError("parent may contain only actually observed old roots")
    parent_before = file_inventory(Path(parent["directory"]))
    _load(cell, parent, scope, frontier)
    for row in facts:
        wordings = [
            template.format(entity=row["entity"], relation=row["relation"])
            for template in [*templates, selection_template, final_template]
        ]
        prompts = [tuple(cell.prompt_ids(wording)) for wording in wordings]
        if len(set(prompts)) != len(prompts):
            raise ValueError("train/selection/final wording must be token-distinct")
    output = Path(output)
    output.mkdir(exist_ok=False)
    parameter_bytes = sum(
        p.numel() * p.element_size()
        for name, p in cell.reader.model.named_parameters()
        if "lora_" in name
    )
    versions = {"nochange": [parent]}
    receipts = {"nochange": []}
    losses = {"nochange": []}
    for arm in ("single", "split"):
        versions[arm], receipts[arm], losses[arm] = [], [], []
        subsets = [facts] if arm == "single" else [old, incoming]
        steps = single_steps if arm == "single" else single_steps // 2
        for slot, subset in enumerate(subsets):
            _load(cell, parent, scope, frontier)
            receipt = cell.fit_sources(subset, steps, learning_rate, templates)
            expected_roots = set(parent["roots"]) | {
                row["source_digest"] for row in subset
            }
            if expected_roots & set(frontier.revoked):
                raise ValueError("withdrawn ancestor cannot enter a trained candidate")
            if (
                receipt["learned_parent_manifest_sha256"] != parent["manifest_sha256"]
                or set(receipt["inherited_roots"]) != set(parent["roots"])
                or set(receipt["roots"]) != expected_roots
                or any(v == 0 for v in receipt["fact_visits"])
            ):
                raise ValueError("actual exposure or warm parent ancestry mismatch")
            directory = output / f"{arm}-{slot}"
            manifest = cell.save(directory)
            write_json(output / f"{arm}-{slot}.write.json", receipt)
            versions[arm].append(_version(directory, manifest, expected_roots))
            receipts[arm].append(receipt)
            losses[arm].append(_losses(receipt, subset, len(templates)))
    costs = {
        arm: {
            "private_parameter_bytes": parameter_bytes * len(versions[arm]),
            "retained_checkpoint_bytes": _checkpoint_bytes(versions[arm]),
            "optimizer_steps": sum(row["steps"] for row in receipts[arm]),
        }
        for arm in ARMS
    }
    raw, assessments = {}, {}
    selection_queries = questions(facts, selection_template)
    for arm in ARMS:
        rows = [None] * len(facts)
        for slot, version in enumerate(versions[arm]):
            _load(cell, version, scope, frontier)
            indices = [
                i
                for i, fact in enumerate(facts)
                if typed_slot(arm, fact["relation"]) == slot
            ]
            before = adapter_digest(cell.reader.model)
            generated = cell.generate([selection_queries[i] for i in indices])
            if adapter_digest(cell.reader.model) != before:
                raise ValueError("selection inference wrote adapter parameters")
            for index, row in zip(indices, generated, strict=True):
                rows[index] = row
        raw[arm] = rows
        correctness = [
            row["text"] == fact["value"] for row, fact in zip(rows, facts, strict=True)
        ]
        assessments[arm] = {
            "old": correctness[: len(old)],
            "new": correctness[len(old) :],
        }
    write_json(output / "source-selection-generations.json", raw)
    selection = choose_growth(assessments, costs)
    report = {
        "schema": "hepta.parametric-memory.arrival-candidates.v1",
        "versions": versions,
        "source_frontier": asdict(frontier),
        "revoked_ancestry_disjoint": all(
            not set(version["roots"]) & set(frontier.revoked)
            for versions_in_arm in versions.values()
            for version in versions_in_arm
        ),
        "costs": costs,
        "source_assessments": assessments,
        "selection": selection,
        "training_loss_by_relation": losses,
        "work": {
            arm: {
                "input_tokens": sum(r["input_tokens"] for r in receipts[arm]),
                "supervised_tokens": sum(r["supervised_tokens"] for r in receipts[arm]),
                "model_forwards": sum(
                    r["actual_model_forwards"] for r in receipts[arm]
                ),
                "training_seconds": sum(r["seconds"] for r in receipts[arm]),
            }
            for arm in ARMS
        },
        "source_selection_input_tokens": sum(
            row["input_tokens"] for rows in raw.values() for row in rows
        ),
        "source_selection_generated_tokens": sum(
            row["generated_tokens"] for rows in raw.values() for row in rows
        ),
        "source_selection_seconds": sum(
            row["seconds"] for rows in raw.values() for row in rows
        ),
        "matched_optimizer_steps": costs["single"]["optimizer_steps"]
        == costs["split"]["optimizer_steps"],
        "matched_parameter_bytes": False,
        "typed_router": {"color": 0, "shape": 1},
        "learned_routing_claimed": False,
        "parent_unchanged": file_inventory(Path(parent["directory"])) == parent_before,
        "production_accepted": False,
    }
    if (
        not report["parent_unchanged"]
        or frozen_digest(cell.reader.model) != cell.reader.base_digest
    ):
        raise ValueError("parent or shared base changed")
    write_json(output / "precommitted-selection.json", report)
    return report
