"""Source-selection-only decoder split experiment; no final-test or runtime grant.

Both training arms own two saved private adapters, inherit the same parent, and
consume the same optimizer steps. Token work is measured, not assumed equal.
The local deterministic router is not a distributed or general memory network.
"""

import hashlib
import json
import math
from pathlib import Path
from string import Formatter

import torch

from experience_inference import frozen_adapter_mode
from native import digest
from parametric_model import FACT_FIELDS
from pretrained import file_inventory, frozen_digest


def _template(value):
    if type(value) is not str or not 1 <= len(value.encode()) <= 1024:
        raise ValueError("bounded source-only template required")
    fields = list(Formatter().parse(value))
    if {name for _, name, _, _ in fields if name is not None} != {
        "entity",
        "relation",
    } or any(spec or conversion for _, _, spec, conversion in fields):
        raise ValueError("template may use only entity and relation")


def _embeddings(cell, questions):
    if type(questions) is not list or not 1 <= len(questions) <= 128:
        raise ValueError("bounded question list required")
    ids = [cell.prompt_ids(question) for question in questions]
    embeddings = []
    with frozen_adapter_mode(cell.reader.model, enabled=False):
        for prompt in ids:
            tokens = torch.tensor([prompt], dtype=torch.long)
            output = cell.reader.model(
                input_ids=tokens,
                attention_mask=torch.ones_like(tokens),
                output_hidden_states=True,
                use_cache=False,
                return_dict=True,
            )
            vector = output.hidden_states[-1].float().mean(dim=1)[0]
            if not torch.isfinite(vector).all() or vector.norm() <= 0:
                raise ValueError("invalid frozen-base embedding")
            embeddings.append(torch.nn.functional.normalize(vector, dim=0).cpu())
    if frozen_digest(cell.reader.model) != cell.reader.base_digest:
        raise ValueError("frozen embedding changed the base")
    return torch.stack(embeddings).double(), {
        "input_tokens": sum(map(len, ids)),
        "model_forwards": len(ids),
        "prompt_sha256": [digest(row) for row in ids],
        "adapter_enabled": False,
    }


def cluster_questions(cell, questions):
    """Deterministic two-means sees question strings, never source values."""
    values, charge = _embeddings(cell, questions)
    if len(values) < 2:
        raise ValueError("two source questions required")
    distances = (values - values[0]).square().sum(dim=1)
    second = int(distances.argmax())
    if float(distances[second]) <= 1e-15:
        raise ValueError("source questions have no separable frozen features")
    centroids = values[[0, second]].clone()
    previous = None
    for iteration in range(32):
        slots = (values[:, None, :] - centroids).square().sum(dim=-1).argmin(dim=1)
        if any(not torch.any(slots == slot) for slot in range(2)):
            raise ValueError("empty source cluster")
        centroids = torch.stack(
            [values[slots == slot].mean(dim=0) for slot in range(2)]
        )
        if previous is not None and torch.equal(slots, previous):
            break
        previous = slots.clone()
    if not torch.equal(
        slots, (values[:, None, :] - centroids).square().sum(dim=-1).argmin(dim=1)
    ):
        raise ValueError("source clustering did not converge within its bound")
    return {
        "schema": "hepta.parametric-question-router.v1",
        "scope": cell.reader.scope,
        "base_identity": cell.reader.identity,
        "centroids": centroids.tolist(),
        "metric": "squared_l2",
        "embedding": "normalized_final_hidden_mean",
        "iterations": iteration + 1,
        "slots": slots.tolist(),
        "embedding_charge": charge,
        "source_values_used": False,
    }


def route_questions(cell, questions, router):
    """Route independent query strings with the frozen source-selected router."""
    if (
        router.get("schema") != "hepta.parametric-question-router.v1"
        or router.get("scope") != cell.reader.scope
        or router.get("base_identity") != cell.reader.identity
        or router.get("metric") != "squared_l2"
        or router.get("embedding") != "normalized_final_hidden_mean"
    ):
        raise ValueError("router identity or profile mismatch")
    expected_width = cell.reader.model.config.hidden_size
    raw = router.get("centroids")
    if (
        type(raw) is not list
        or len(raw) != 2
        or any(type(row) is not list or len(row) != expected_width for row in raw)
        or any(
            type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1.000001
            for row in raw
            for v in row
        )
    ):
        raise ValueError("bounded finite router centroids required")
    vectors, charge = _embeddings(cell, questions)
    centers = torch.tensor(raw, dtype=torch.float64)
    return {
        "slots": (vectors[:, None, :] - centers)
        .square()
        .sum(dim=-1)
        .argmin(dim=1)
        .tolist(),
        "embedding_charge": charge,
    }


def _assess(cell, versions, questions, routes, facts, allowed):
    records = [None] * len(questions)
    for slot, version in enumerate(versions):
        cell.load(
            version["directory"],
            expected_manifest_sha256=version["manifest_sha256"],
            scope=facts[0]["scope"],
            allowed_roots=allowed,
            revoked=set(),
        )
        indices = [i for i, route in enumerate(routes) if route == slot]
        if indices:
            generated = cell.generate([questions[i] for i in indices])
            for index, record in zip(indices, generated, strict=True):
                records[index] = record
    correct = [
        record["text"] == fact["value"]
        for record, fact in zip(records, facts, strict=True)
    ]
    return {
        "correct": sum(correct),
        "count": len(correct),
        "correct_by_source": correct,
    }, records


def run_evolution(
    cell,
    *,
    parent_dir,
    parent_sha,
    facts,
    output,
    steps,
    learning_rate,
    templates,
    selection_template,
):
    """Create both measured arms; choose only with source-derived held-out wording."""
    if (
        type(facts) is not list
        or not 2 <= len(facts) <= 128
        or type(templates) is not list
        or not 1 <= len(templates) <= 8
        or type(steps) is not int
        or not len(facts) * len(templates) <= steps <= 4096
        or type(learning_rate) not in (int, float)
        or not math.isfinite(learning_rate)
        or not 0 < learning_rate <= 0.1
    ):
        raise ValueError("bounded evolution source and optimizer budget required")
    for template in [*templates, selection_template]:
        _template(template)
    if selection_template in templates or len(set(templates)) != len(templates):
        raise ValueError("distinct source-heldout selection wording required")
    if any(
        type(f) is not dict
        or set(f) != FACT_FIELDS
        or any(type(v) is not str or not v for v in f.values())
        for f in facts
    ):
        raise ValueError(
            "exact source fact fields required; no task or final-test labels"
        )
    ordered = sorted(facts, key=lambda f: (f["entity"], f["relation"]))
    scope = ordered[0]["scope"]
    allowed = {f["source_digest"] for f in ordered}
    if (
        len(allowed) != len(ordered)
        or len({(f["entity"], f["relation"]) for f in ordered}) != len(ordered)
        or any(f["scope"] != scope for f in ordered)
    ):
        raise ValueError("unique source identities in one scope required")
    parent_dir, output = Path(parent_dir), Path(output)
    if output.exists():
        raise ValueError("fresh evolution output directory required")
    parent_before = file_inventory(parent_dir)
    cell.load(
        parent_dir,
        expected_manifest_sha256=parent_sha,
        scope=scope,
        allowed_roots=allowed,
        revoked=set(),
    )
    if set(cell.reader.roots) != allowed:
        raise ValueError("parent must have actually observed every source fact")
    source_questions = [
        templates[0].format(entity=f["entity"], relation=f["relation"]) for f in ordered
    ]
    questions = [
        selection_template.format(entity=f["entity"], relation=f["relation"])
        for f in ordered
    ]
    for fact, question in zip(ordered, questions, strict=True):
        selected = cell.prompt_ids(question)
        if any(
            selected
            == cell.prompt_ids(
                t.format(entity=fact["entity"], relation=fact["relation"])
            )
            for t in templates
        ):
            raise ValueError("selection wording must differ at the token level")
    router = cluster_questions(cell, source_questions)
    routing = route_questions(cell, questions, router)
    partitions = [
        [f for f, s in zip(ordered, router["slots"], strict=True) if s == slot]
        for slot in range(2)
    ]
    parent = {
        "directory": str(parent_dir.absolute()),
        "manifest_sha256": parent_sha,
        "roots": sorted(allowed),
    }
    output.mkdir(parents=True)
    arms, raw = {}, {}
    assessment, raw["nochange"] = _assess(
        cell, [parent, parent], questions, routing["slots"], ordered, allowed
    )
    arms["nochange"] = {
        "selection": assessment,
        "cells": [parent, parent],
        "optimizer_steps": 0,
    }
    for arm in ("continue", "split"):
        versions, receipts = [], []
        for slot in range(2):
            cell.load(
                parent_dir,
                expected_manifest_sha256=parent_sha,
                scope=scope,
                allowed_roots=allowed,
                revoked=set(),
            )
            trained = ordered if arm == "continue" else partitions[slot]
            receipt = cell.fit_sources(trained, steps, learning_rate, templates)
            directory = output / f"{arm}-{slot}"
            manifest = cell.save(directory)
            if (
                receipt["learned_parent_manifest_sha256"] != parent_sha
                or set(receipt["roots"]) != allowed
                or any(v == 0 for v in receipt["fact_visits"])
            ):
                raise ValueError("child inheritance or actual exposure mismatch")
            versions.append(
                {
                    "slot": slot,
                    "directory": str(directory.absolute()),
                    "manifest_sha256": manifest,
                    "roots": receipt["roots"],
                }
            )
            receipts.append(receipt)
        assessment, raw[arm] = _assess(
            cell, versions, questions, routing["slots"], ordered, allowed
        )
        arms[arm] = {
            "selection": assessment,
            "cells": versions,
            "optimizer_steps": sum(r["steps"] for r in receipts),
            "parameter_bytes": sum(r["parameter_bytes"] for r in receipts),
            "input_tokens": sum(r["input_tokens"] for r in receipts),
            "supervised_tokens": sum(r["supervised_tokens"] for r in receipts),
            "model_forwards": sum(r["actual_model_forwards"] for r in receipts),
            "training_seconds": sum(r["seconds"] for r in receipts),
            "saved_adapter_bytes": sum(
                (Path(v["directory"]) / "adapter_model.safetensors").stat().st_size
                for v in versions
            ),
            "slot_fact_counts": [
                len(ordered) if arm == "continue" else len(p) for p in partitions
            ],
        }
    continued, split = arms["continue"]["selection"], arms["split"]["selection"]
    original = arms["nochange"]["selection"]["correct_by_source"]
    preserved = all(
        not (a or b) or c
        for a, b, c in zip(
            original,
            continued["correct_by_source"],
            split["correct_by_source"],
            strict=True,
        )
    )
    continuation_preserves_parent = all(
        not old or new
        for old, new in zip(original, continued["correct_by_source"], strict=True)
    )
    if split["correct"] >= continued["correct"] + 2 and preserved:
        chosen = "split"
    elif continuation_preserves_parent and continued["correct"] >= sum(original):
        chosen = "continue"
    else:
        chosen = "nochange"
    for key in ("optimizer_steps", "parameter_bytes", "saved_adapter_bytes"):
        if arms["continue"][key] != arms["split"][key]:
            raise ValueError(f"evolution arms changed matched budget: {key}")
    if file_inventory(parent_dir) != parent_before:
        raise ValueError("evolution mutated the persisted parent")
    journal = json.dumps(raw, sort_keys=True, indent=2, allow_nan=False).encode()
    (output / "selection-generations.json").write_bytes(journal)
    report = {
        "schema": "hepta.parametric-evolution.source-selection.v1",
        "scope": scope,
        "parent_manifest_sha256": parent_sha,
        "parent_inventory_sha256": digest(parent_before),
        "parent_unchanged": True,
        "router": router,
        "partition": {
            "source_digests": [f["source_digest"] for f in ordered],
            "slots": router["slots"],
        },
        "selection_template_sha256": digest(selection_template),
        "selection_routing": routing,
        "arms": arms,
        "chosen_arm": chosen,
        "chosen_cells": arms[chosen]["cells"],
        "selection_rule": "split gains at least two correct and preserves parent and continuation correct; otherwise continue only if parent correct items and score are preserved, else nochange",
        "matched_parameter_bytes_and_optimizer_steps": True,
        "flops_assumed_equal": False,
        "matched_input_tokens": arms["continue"]["input_tokens"]
        == arms["split"]["input_tokens"],
        "candidate_search_cost": {
            "optimizer_steps": sum(
                arms[a]["optimizer_steps"] for a in ("continue", "split")
            ),
            "input_tokens": sum(arms[a]["input_tokens"] for a in ("continue", "split")),
            "embedding_input_tokens": router["embedding_charge"]["input_tokens"]
            + routing["embedding_charge"]["input_tokens"],
            "selection_input_tokens": sum(
                r["input_tokens"] for records in raw.values() for r in records
            ),
            "selection_generated_tokens": sum(
                r["generated_tokens"] for records in raw.values() for r in records
            ),
        },
        "source_selection_is_not_final_test": True,
        "source_values_used_for_routing": False,
        "raw_generation_sha256": hashlib.sha256(journal).hexdigest(),
        "production_accepted": False,
    }
    (output / "evolution.json").write_text(
        json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n"
    )
    return report
