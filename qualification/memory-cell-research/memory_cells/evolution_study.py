"""Executed retention, clean-retraining and costed split/merge diagnostics.

These numerical experiments do not establish production integration, selective
machine unlearning, natural-language transfer or economically optimal growth.
"""

from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import time

from .composition_study import (
    predict_queries,
    revision_id,
    train_artifact,
    typed_keys,
    write_json,
)
from .data import dataset_from_events, make_associative, make_continual
from .encoding import FrozenEncoder, canonical_bytes
from .lifecycle import (
    ArtifactRecord,
    CandidateMetrics,
    LifecycleError,
    MemoryRegistry,
    choose_structure,
    plan_split,
)
from .metrics import measure_bytes, summarize_predictions
from .model import MemoryCell


def unique_queries(queries):
    seen, result = set(), []
    for query in queries:
        identity = (query.domain, query.key)
        if identity not in seen:
            result.append(query)
            seen.add(identity)
    return tuple(result)


def disjoint_readouts(dataset):
    """All keys may be written; selection/test effective read inputs are disjoint."""
    selection_keys, test_keys = set(), set()
    for domain in sorted({event.domain for event in dataset.events}):
        keys = sorted({event.key for event in dataset.events if event.domain == domain})
        selection_keys.update((domain, key) for key in keys[::2])
        test_keys.update((domain, key) for key in keys[1::2])
    if not selection_keys or not test_keys or selection_keys & test_keys:
        raise ValueError("invalid effective-input holdout")
    selection = tuple(
        q
        for q in unique_queries(dataset.selection)
        if (q.domain, q.key) in selection_keys
    )
    test = tuple(
        q for q in unique_queries(dataset.test) if (q.domain, q.key) in test_keys
    )

    def describe(keys):
        return [
            {
                "domain": d,
                "key": k,
                "sha256": sha256(canonical_bytes([d, k])).hexdigest(),
            }
            for d, k in sorted(keys)
        ]

    return (
        selection,
        test,
        {
            "rule": "sorted keys per domain: even selection, odd test",
            "selection_keys": describe(selection_keys),
            "test_keys": describe(test_keys),
            "effective_inputs_disjoint": True,
            "all_keys_legitimately_visible_during_writing": True,
        },
    )


def _training_seconds(receipts):
    return sum(
        sum(
            receipt[field]
            for field in (
                "seconds",
                "encoding_seconds",
                "save_seconds",
                "reload_seconds",
            )
        )
        for receipt in receipts
    )


def _register(registry, name, manifest, dataset, parents=(), generation=1):
    registry.register(
        ArtifactRecord(
            name,
            "research",
            manifest["tensor_sha256"],
            tuple(sorted({revision_id(e) for e in dataset.events})),
            tuple(sorted(parents)),
            generation,
        )
    )


def _blocked(registry, slot):
    try:
        registry.resolve(slot, scope="research")
        return False
    except LifecycleError:
        return True


def _maintenance(protocol, seed_dir, source_commit, seed):
    started = time.perf_counter()
    profile, classes = protocol["maintenance_profile"], protocol["num_classes"]
    base = make_associative(
        seed, (profile["initial_records"],), classes, ("semantic-old",)
    )
    stream = make_continual(
        base,
        seed + 431,
        profile["additions"],
        profile["corrections"],
        profile["deletions"],
    )
    current = stream["current"]
    delta = dataset_from_events(stream["additions"] + stream["corrections"])
    encoder = FrozenEncoder(protocol["feature_dim"], seed=0)
    candidates, manifests, receipts = {}, {}, {}
    write_json(
        seed_dir / "corpus.json",
        {"base": base.to_dict(), "history": [asdict(e) for e in stream["history"]]},
    )
    candidates["before"], manifests["before"], receipts["before"] = train_artifact(
        MemoryCell(encoder.dim, profile["rank"], classes, seed),
        base,
        encoder,
        seed_dir / "candidates" / "before",
        protocol,
        source_commit,
    )
    for name, data in (("without_replay", delta), ("with_replay", current)):
        candidates[name], manifests[name], receipts[name] = train_artifact(
            candidates["before"].clone(seed + 71),
            data,
            encoder,
            seed_dir / "candidates" / name,
            protocol,
            source_commit,
            parent=manifests["before"]["manifest_sha256"],
        )
    registry = MemoryRegistry()
    _register(registry, "before", manifests["before"], base)
    _register(
        registry, "without_replay", manifests["without_replay"], delta, ("before",), 2
    )
    _register(
        registry, "with_replay", manifests["with_replay"], current, ("before",), 2
    )
    registry.adopt("current", "with_replay", expected_revision=0)
    registry.save(seed_dir / "registry-before-revocation.json")
    original = {event.record_id: event for event in base.events}
    for event in stream["corrections"]:
        registry.correct_source(
            revision_id(original[event.record_id]), revision_id(event)
        )
    for event in stream["deletions"]:
        registry.revoke_source(revision_id(original[event.record_id]))
    old_lineage_blocked = _blocked(registry, "current")
    restored = MemoryRegistry.load(
        seed_dir / "registry-before-revocation.json",
        current_revoked_sources=registry.revoked_sources,
    )
    stale_restore_blocked = _blocked(restored, "current")
    (
        candidates["clean_retrain"],
        manifests["clean_retrain"],
        receipts["clean_retrain"],
    ) = train_artifact(
        MemoryCell(encoder.dim, profile["rank"], classes, seed + 83),
        current,
        encoder,
        seed_dir / "candidates" / "clean_retrain",
        protocol,
        source_commit,
    )
    _register(registry, "clean_retrain", manifests["clean_retrain"], current)
    registry.adopt("current", "clean_retrain", expected_revision=1)
    registry.save(seed_dir / "registry-after-retrain.json")
    deleted_keys = {(event.domain, event.key) for event in stream["deletions"]}
    write_json(
        seed_dir / "tombstones.json",
        {
            "deleted_keys": sorted(deleted_keys),
            "revoked_source_revisions": sorted(registry.revoked_sources),
        },
    )
    groups = {
        "retained": unique_queries(stream["retained"].test),
        "new": unique_queries(dataset_from_events(stream["additions"]).test),
        "corrected": unique_queries(dataset_from_events(stream["corrections"]).test),
        "current": unique_queries(current.test),
        "deleted": unique_queries(stream["deleted_queries"]),
    }
    metrics, rows, read_seconds = {}, [], {}
    for name, cell in candidates.items():
        metrics[name], read_seconds[name] = {}, {}
        for group, queries in groups.items():
            values, seconds = predict_queries(cell, queries, encoder)
            read_seconds[name][group] = seconds
            if group == "deleted":
                old_values = [original[q.source_record_id].value for q in queries]
                metrics[name][group] = {
                    "raw_weight_old_value_matches": sum(
                        a == b for a, b in zip(old_values, values)
                    ),
                    "queries": len(queries),
                    "raw_weight_old_value_match_rate": sum(
                        a == b for a, b in zip(old_values, values)
                    )
                    / len(queries),
                    "interpretation": "diagnostic only; a different top-1 prediction is not erasure proof",
                }
            else:
                metrics[name][group] = summarize_predictions(
                    [q.target for q in queries], values
                )
            for query, value in zip(queries, values):
                rows.append(
                    {
                        "candidate": name,
                        "group": group,
                        "query_id": query.query_id,
                        "key": query.key,
                        "target": query.target,
                        "raw_prediction": value,
                        "artifact_serving_allowed": registry.usable(name),
                        "current_interface_prediction": None
                        if (query.domain, query.key) in deleted_keys
                        else value
                        if name == "clean_retrain"
                        else None,
                    }
                )
    (seed_dir / "predictions.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    )
    interface_rows, interface_calls = [], 0
    interface_started = time.perf_counter()
    for query in groups["current"] + groups["deleted"]:
        registry.resolve("current", scope="research")
        reason = "deleted_source" if (query.domain, query.key) in deleted_keys else None
        if reason:
            prediction = None
        else:
            prediction = int(
                candidates["clean_retrain"].predict(
                    encoder.encode(typed_keys([query]))
                )[0]
            )
            interface_calls += 1
        interface_rows.append(
            {
                "query_id": query.query_id,
                "target": query.target,
                "prediction": prediction,
                "refusal": reason,
            }
        )
    interface_seconds = time.perf_counter() - interface_started
    (seed_dir / "interface-predictions.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in interface_rows)
    )
    clean = metrics["clean_retrain"]
    regression = (
        metrics["before"]["retained"]["accuracy"] - clean["retained"]["accuracy"]
    )
    clean_sources = {revision_id(event) for event in current.events}
    deleted_source_ids = {
        revision_id(original[event.record_id]) for event in stream["deletions"]
    }
    clean_excludes_revoked = not bool(clean_sources & registry.revoked_sources)
    fresh_without_parent = "parent" not in manifests["clean_retrain"]["lineage"]
    refused = sum(row["refusal"] == "deleted_source" for row in interface_rows)
    result = {
        "seed": seed,
        "profile": profile,
        "metrics": metrics,
        "read_seconds": read_seconds,
        "training_receipts": receipts,
        "old_retention_regression": regression,
        "revoked_lineage_blocked": old_lineage_blocked,
        "stale_restore_blocked": stale_restore_blocked,
        "clean_sources_exclude_deleted_revisions": not bool(
            clean_sources & deleted_source_ids
        ),
        "clean_sources_exclude_all_revoked_revisions": clean_excludes_revoked,
        "clean_retrain_has_no_parameter_parent": fresh_without_parent,
        "maintenance_method": "full retraining from fresh initialization on all current valid sources; not local lossless erasure",
        "clean_retrain_source_records": len(current.events),
        "deletion_interface": {
            "refused": refused,
            "queries": len(groups["deleted"]),
            "model_calls": interface_calls,
            "seconds": interface_seconds,
            "mechanism": "owner tombstone lookup before parameter read",
            "unlearning_proven": False,
        },
        "parameter_bytes_per_candidate": {
            name: cell.parameter_bytes for name, cell in candidates.items()
        },
        "parameter_artifact_bytes": measure_bytes(
            [seed_dir / "candidates" / name / "model" for name in candidates]
        ),
        "source_corpus_bytes": (seed_dir / "corpus.json").stat().st_size,
        "tombstone_bytes": (seed_dir / "tombstones.json").stat().st_size,
        "total_candidate_write_seconds": _training_seconds(receipts.values()),
        "study_wall_seconds": time.perf_counter() - started,
        "criterion_met": clean["new"]["accuracy"] >= 0.95
        and clean["corrected"]["accuracy"] >= 0.95
        and regression <= 0.02
        and old_lineage_blocked
        and stale_restore_blocked
        and clean_excludes_revoked
        and fresh_without_parent
        and refused == len(groups["deleted"]),
        "claim_scope": "one-cell 24-source diagnostic; no primary-96, natural-domain or parameter-erasure qualification",
    }
    write_json(seed_dir / "summary.json", result)
    return result


def _routed(cells, assignments, queries, encoder):
    started = time.perf_counter()
    predictions = [None] * len(queries)
    for model_id in sorted(cells):
        indices = [
            index
            for index, query in enumerate(queries)
            if assignments[query.domain] == model_id
        ]
        if indices:
            values = (
                cells[model_id]
                .predict(encoder.encode(typed_keys([queries[i] for i in indices])))
                .tolist()
            )
            for index, value in zip(indices, values):
                predictions[index] = value
    return predictions, time.perf_counter() - started


def _lifecycle_cost(
    seed_dir,
    trained_ids,
    evaluated_ids,
    deployed_id,
    costs,
    receipts,
    profile,
    *,
    distillation_seconds=0.0,
    lineage_files=(),
):
    """Charge executed search candidates once, including rejected candidates."""
    artifact_dirs = [seed_dir / "candidates" / key for key in trained_ids]
    model_bytes = measure_bytes([path / "model" for path in artifact_dirs])
    routing_bytes = measure_bytes(
        [seed_dir / f"routing-{key}.json" for key in evaluated_ids]
    )
    lineage_bytes = measure_bytes([seed_dir / name for name in lineage_files])
    replay_bytes = measure_bytes(
        [path / "training-data.json" for path in artifact_dirs]
    )
    receipt_bytes = measure_bytes(
        [path / "training-receipt.json" for path in artifact_dirs]
    )
    source_bytes = (seed_dir / "corpus.json").stat().st_size
    retained_bytes = (
        model_bytes
        + routing_bytes
        + lineage_bytes
        + replay_bytes
        + receipt_bytes
        + source_bytes
    )
    writes = {key: _training_seconds([receipts[key]]) for key in trained_ids}
    selection_reads = {
        key: costs[key]["selection_read_seconds"] for key in evaluated_ids
    }
    total_write_seconds = sum(writes.values()) + distillation_seconds
    selection_read_seconds = sum(selection_reads.values())
    hidden_read_seconds = costs[deployed_id]["hidden_read_seconds"]
    total_read_seconds = selection_read_seconds + hidden_read_seconds
    return {
        "trained_artifact_ids": list(trained_ids),
        "selection_evaluated_candidates": list(evaluated_ids),
        "deployed_candidate": deployed_id,
        "write_seconds_by_artifact": writes,
        "distillation_seconds": distillation_seconds,
        "total_write_seconds": total_write_seconds,
        "selection_read_seconds_by_candidate": selection_reads,
        "selection_read_seconds": selection_read_seconds,
        "selected_hidden_read_seconds": hidden_read_seconds,
        "total_read_seconds": total_read_seconds,
        "selected_deployment_bytes": costs[deployed_id]["artifact_bytes"]
        + costs[deployed_id]["routing_metadata_bytes"],
        "retained_model_artifact_bytes": model_bytes,
        "retained_routing_metadata_bytes": routing_bytes,
        "retained_lineage_metadata_bytes": lineage_bytes,
        "source_corpus_bytes": source_bytes,
        "replay_training_data_bytes": replay_bytes,
        "training_receipt_bytes": receipt_bytes,
        "priced_retained_bytes": retained_bytes,
        "priced_resource_cost": profile["byte_price"] * retained_bytes
        + profile["training_second_price"] * total_write_seconds
        + profile["read_second_price"] * total_read_seconds,
        "accounting_scope": "all executed search writes and selection reads; deployed hidden batch once; retained model, routing, lineage, source, replay and receipt files; evaluation logs excluded",
    }


def _growth(protocol, seed_dir, source_commit, seed):
    started = time.perf_counter()
    profile, classes = protocol["growth_profile"], protocol["num_classes"]
    if (
        profile["domains"] != 2
        or len(profile["child_ranks"]) != 2
        or len(profile["fixed_ranks"]) != 2
    ):
        raise ValueError("frozen growth study requires two domains")
    domains = ("semantic-growth-a", "semantic-growth-b")
    data = make_associative(
        seed, (profile["records_per_domain"],) * 2, classes, domains
    )
    selection, test, partition = disjoint_readouts(data)
    write_json(seed_dir / "evaluation-partition.json", partition)
    write_json(seed_dir / "corpus.json", data.to_dict())
    plan = plan_split(
        [q.query_id for q in data.train],
        [q.query_id for q in selection],
        [q.query_id for q in test],
        {q.query_id: q.domain for q in data.train},
    )
    write_json(seed_dir / "split-plan.json", asdict(plan))
    encoder = FrozenEncoder(protocol["feature_dim"], seed=0)
    models, manifests, receipts, inheritance = {}, {}, {}, {}
    models["parent"], manifests["parent"], receipts["parent"] = train_artifact(
        MemoryCell(encoder.dim, profile["parent_rank"], classes, seed),
        data,
        encoder,
        seed_dir / "candidates" / "parent",
        protocol,
        source_commit,
    )
    for index, domain in enumerate(domains):
        subset = dataset_from_events(
            [event for event in data.events if event.domain == domain]
        )
        split_id, fixed_id = f"split-{index}", f"fixed-{index}"
        child, inheritance[split_id] = models["parent"].resize_rank(
            profile["child_ranks"][index], seed + index + 19
        )
        models[split_id], manifests[split_id], receipts[split_id] = train_artifact(
            child,
            subset,
            encoder,
            seed_dir / "candidates" / split_id,
            protocol,
            source_commit,
            parent=manifests["parent"]["manifest_sha256"],
        )
        models[fixed_id], manifests[fixed_id], receipts[fixed_id] = train_artifact(
            MemoryCell(
                encoder.dim, profile["fixed_ranks"][index], classes, seed + index + 31
            ),
            subset,
            encoder,
            seed_dir / "candidates" / fixed_id,
            protocol,
            source_commit,
        )
    split_assignments = {domain: f"split-{i}" for i, domain in enumerate(domains)}
    teachers = {name: models[name] for name in split_assignments.values()}
    distilled, distillation_seconds = _routed(
        teachers, split_assignments, data.train, encoder
    )
    merge_parent = {
        "parents": [manifests[f"split-{i}"]["manifest_sha256"] for i in range(2)]
    }
    write_json(seed_dir / "merge-parents.json", merge_parent)
    models["merge"], manifests["merge"], receipts["merge"] = train_artifact(
        MemoryCell(encoder.dim, profile["merge_rank"], classes, seed + 53),
        data,
        encoder,
        seed_dir / "candidates" / "merge",
        protocol,
        source_commit,
        parent=sha256(canonical_bytes(merge_parent)).hexdigest(),
        targets=distilled,
    )
    write_json(seed_dir / "inheritance.json", inheritance)
    configurations = {
        "parent": ({"parent": models["parent"]}, {d: "parent" for d in domains}),
        "split": (teachers, split_assignments),
        "fixed": (
            {f"fixed-{i}": models[f"fixed-{i}"] for i in range(2)},
            {d: f"fixed-{i}" for i, d in enumerate(domains)},
        ),
        "merge": ({"merge": models["merge"]}, {d: "merge" for d in domains}),
    }
    lineage = {
        "parent": ("parent",),
        "split": ("parent", "split-0", "split-1"),
        "fixed": ("fixed-0", "fixed-1"),
        "merge": ("parent", "split-0", "split-1", "merge"),
    }
    costs, selection_metrics, selection_predictions, records = {}, {}, {}, []
    for name, (cells, assignments) in configurations.items():
        routing = {
            "scope": "given-domain deterministic route",
            "assignments": assignments,
            "artifacts": {key: manifests[key]["manifest_sha256"] for key in cells},
        }
        write_json(seed_dir / f"routing-{name}.json", routing)
        values, seconds = _routed(cells, assignments, selection, encoder)
        selection_predictions[name] = values
        selection_metrics[name] = summarize_predictions(
            [q.target for q in selection], values
        )
        costs[name] = {
            "trainable_params": sum(cell.trainable_params for cell in cells.values()),
            "parameter_bytes": sum(cell.parameter_bytes for cell in cells.values()),
            "artifact_bytes": measure_bytes(
                [seed_dir / "candidates" / key / "model" for key in cells]
            ),
            "routing_metadata_bytes": (seed_dir / f"routing-{name}.json")
            .stat()
            .st_size,
            "cumulative_write_seconds": _training_seconds(
                receipts[key] for key in lineage[name]
            )
            + (distillation_seconds if name == "merge" else 0.0),
            "selection_read_seconds": seconds,
            "read_seconds_per_query": seconds / len(selection),
        }
        records.append(
            CandidateMetrics(
                name,
                {
                    "parent": "no_change",
                    "split": "split",
                    "fixed": "update",
                    "merge": "merge",
                }[name],
                1 - selection_metrics[name]["accuracy"],
                1 - selection_metrics[name]["accuracy"],
                costs[name]["artifact_bytes"] + costs[name]["routing_metadata_bytes"],
                costs[name]["cumulative_write_seconds"],
                costs[name]["read_seconds_per_query"],
            )
        )
    decision = choose_structure(
        [row for row in records if row.candidate_id != "fixed"],
        byte_price=profile["byte_price"],
        training_price=profile["training_second_price"],
        read_price=profile["read_second_price"],
        max_retention_regression=0.02,
        min_gain=0.0,
    )
    sensitivity = {
        str(scale): asdict(
            choose_structure(
                [row for row in records if row.candidate_id != "fixed"],
                byte_price=profile["byte_price"] * scale,
                training_price=profile["training_second_price"] * scale,
                read_price=profile["read_second_price"] * scale,
                max_retention_regression=0.02,
                min_gain=0.0,
            )
        )
        for scale in (0.1, 1.0, 10.0)
    }
    # Persist the complete decision BEFORE accessing hidden-query outcomes.
    write_json(
        seed_dir / "selection-decision.json",
        {
            "decision": asdict(decision),
            "candidate_observations": [asdict(row) for row in records],
            "selection_only_cost_sensitivity": sensitivity,
            "selection_metrics": selection_metrics,
            "selection_keys": partition["selection_keys"],
            "cost_interpretation": "fixed illustrative loss-unit prices; measured host timing, not a physical law",
        },
    )
    test_metrics, test_predictions, rows = {}, {}, []
    for name, (cells, assignments) in configurations.items():
        values, seconds = _routed(cells, assignments, test, encoder)
        test_predictions[name] = values
        test_metrics[name] = summarize_predictions([q.target for q in test], values)
        costs[name]["hidden_read_seconds"] = seconds
        for phase, queries, predictions in (
            ("selection", selection, selection_predictions[name]),
            ("hidden", test, values),
        ):
            rows.extend(
                {
                    "candidate": name,
                    "phase": phase,
                    "query_id": q.query_id,
                    "key": q.key,
                    "domain": q.domain,
                    "target": q.target,
                    "prediction": value,
                }
                for q, value in zip(queries, predictions)
            )
    (seed_dir / "predictions.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    )
    selected = decision.selected_id
    tensor_budgets = {name: cost["parameter_bytes"] for name, cost in costs.items()}
    equal_budget = len(set(tensor_budgets.values())) == 1
    for cost in costs.values():
        cost["priced_resource_cost"] = (
            profile["byte_price"]
            * (cost["artifact_bytes"] + cost["routing_metadata_bytes"])
            + profile["training_second_price"] * cost["cumulative_write_seconds"]
            + profile["read_second_price"] * cost["hidden_read_seconds"] / len(test)
        )
    selected_cost_dominance = (
        costs[selected]["priced_resource_cost"]
        <= costs["fixed"]["priced_resource_cost"]
    )
    policy_cost = _lifecycle_cost(
        seed_dir,
        ("parent", "split-0", "split-1", "merge"),
        ("parent", "split", "merge"),
        selected,
        costs,
        receipts,
        profile,
        distillation_seconds=distillation_seconds,
        lineage_files=("merge-parents.json", "inheritance.json", "split-plan.json"),
    )
    fixed_cost = _lifecycle_cost(
        seed_dir, ("fixed-0", "fixed-1"), ("fixed",), "fixed", costs, receipts, profile
    )
    policy_cost_dominance = (
        policy_cost["priced_resource_cost"] <= fixed_cost["priced_resource_cost"]
    )
    write_json(
        seed_dir / "lifecycle-costs.json",
        {"policy_cost": policy_cost, "fixed_comparator_cost": fixed_cost},
    )
    result = {
        "seed": seed,
        "profile": profile,
        "selection_decision": asdict(decision),
        "selection_metrics": selection_metrics,
        "test_metrics": test_metrics,
        "costs": costs,
        "same_tensor_budget": equal_budget,
        "all_parameter_bytes": tensor_budgets,
        "training_receipts": receipts,
        "distillation_seconds": distillation_seconds,
        "effective_selection_test_inputs_disjoint": partition[
            "effective_inputs_disjoint"
        ],
        "selected_hidden_accuracy": test_metrics[selected]["accuracy"],
        "fixed_hidden_accuracy": test_metrics["fixed"]["accuracy"],
        "selected_minus_fixed_hidden_accuracy": test_metrics[selected]["accuracy"]
        - test_metrics["fixed"]["accuracy"],
        "selected_write_cost_no_greater_than_fixed": costs[selected][
            "cumulative_write_seconds"
        ]
        <= costs["fixed"]["cumulative_write_seconds"],
        "selected_priced_resource_cost_no_greater_than_fixed": selected_cost_dominance,
        "policy_cost": policy_cost,
        "fixed_comparator_cost": fixed_cost,
        "policy_priced_resource_cost_no_greater_than_fixed": policy_cost_dominance,
        "selection_only_cost_sensitivity": sensitivity,
        "total_candidate_search_write_seconds": _training_seconds(receipts.values())
        + distillation_seconds,
        "total_candidate_search_read_seconds": sum(
            c["selection_read_seconds"] + c["hidden_read_seconds"]
            for c in costs.values()
        ),
        "total_persisted_research_bytes": measure_bytes([seed_dir]),
        "persisted_byte_measurement_scope": "all seed files before writing this summary",
        "source_corpus_bytes": (seed_dir / "corpus.json").stat().st_size,
        "study_wall_seconds": time.perf_counter() - started,
        "criterion_met": selected in {"split", "merge"}
        and equal_budget
        and policy_cost_dominance
        and test_metrics[selected]["accuracy"] > test_metrics["fixed"]["accuracy"],
        "claim_scope": "given-domain partition and routing; trained inherited children and hard-label merge; no autonomous topology discovery",
    }
    write_json(seed_dir / "summary.json", result)
    return result


def run_evolution(
    protocol, output_dir: Path, source_commit: str, seeds: list[int]
) -> dict:
    directory = Path(output_dir) / "evolution"
    directory.mkdir(parents=True, exist_ok=False)
    write_json(
        directory / "config.json",
        {"protocol": protocol, "source_commit": source_commit, "seeds": seeds},
    )
    maintenance, growth = [], []
    for seed in seeds:
        maintenance_dir, growth_dir = (
            directory / f"maintenance-{seed}",
            directory / f"growth-{seed}",
        )
        maintenance_dir.mkdir()
        growth_dir.mkdir()
        maintenance.append(_maintenance(protocol, maintenance_dir, source_commit, seed))
        growth.append(_growth(protocol, growth_dir, source_commit, seed))
    result = {
        "maintenance": {"stage": 4, "runs": maintenance},
        "growth": {"stage": 5, "runs": growth},
    }
    write_json(directory / "summary.json", result)
    return result
