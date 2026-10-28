"""Bounded continual structural search; numerical research, not learned biology.

Only written sources and a stable selection-key partition influence decisions.
All attempted training, route migration and checkpoint restoration are charged.
"""

from dataclasses import asdict, replace
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import time

import numpy as np

from memory_cells.data import make_associative
from memory_cells.encoding import FrozenEncoder, canonical_bytes
from memory_cells.lifecycle import ArtifactRecord, LifecycleError, MemoryRegistry
from memory_cells.metrics import measure_bytes
from memory_cells.model import MemoryCell


DEFAULT_PROFILE = {
    "snapshots": [[128, 128], [1024, 256], [1024, 1024]],
    "feature_dim": 128,
    "num_classes": 64,
    "rank_budget": 16,
    "steps": 300,
    "learning_rate": 0.03,
    "trigger_error": 0.05,
    "min_selection_gain": 0.01,
    "max_retention_regression": 0.02,
    "query_budget": 10000,
    "cost_horizons": [1, 100, 10000, 1000000],
    "byte_price": 0.000001,
    "training_second_price": 0.01,
    "read_second_price": 1.0,
    "revocations": 16,
}
DOMAINS = ("pressure-a", "pressure-b")
SCOPE = "memory-cell-v2-growth"


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def _identity(event):
    return sha256(
        canonical_bytes([event.record_id, event.revision, event.source_sha256])
    ).hexdigest()


def _bucket(event, purpose):
    return (
        int(sha256(canonical_bytes([purpose, event.domain, event.key])).hexdigest(), 16)
        % 2
    )


def partition_keys(events):
    """Stable, label-independent effective-input holdout; every key may be written."""
    return tuple(e for e in events if _bucket(e, "selection") == 0), tuple(
        e for e in events if _bucket(e, "selection") == 1
    )


def _route(spec, event):
    return (
        0
        if spec["route"] == "single"
        else (
            DOMAINS.index(event.domain)
            if spec["route"] == "domain"
            else _bucket(event, "routing")
        )
    )


def _register(registry, name, digest, sources, parents):
    parents = tuple(sorted(set(parents)))
    generation = max((registry.records[p].generation for p in parents), default=0) + 1
    registry.register(
        ArtifactRecord(
            name, SCOPE, digest, tuple(sorted(set(sources))), parents, generation
        )
    )


def _predict(bundle, events, encoder, registry=None):
    started = time.perf_counter()
    if registry is not None and not registry.usable(bundle["id"]):
        raise LifecycleError("checkpoint lineage revoked before parameter read")
    predictions = np.empty(len(events), dtype=np.int64)
    for index, cell in enumerate(bundle["models"]):
        positions = [
            i
            for i, event in enumerate(events)
            if _route(bundle["spec"], event) == index
        ]
        if positions:
            inputs = [f"{events[i].domain} {events[i].key}" for i in positions]
            predictions[positions] = cell.predict(encoder.encode(inputs))
    return predictions.tolist(), time.perf_counter() - started


def serve(bundle, events, encoder, registry, revoked_keys):
    """Owner tombstones block deleted keys before any tensor call."""
    if not registry.usable(bundle["id"]):
        raise LifecycleError("selected lineage unavailable")
    positions = [
        i for i, e in enumerate(events) if (e.domain, e.key) not in revoked_keys
    ]
    values = [None] * len(events)
    if positions:
        read, _ = _predict(bundle, [events[i] for i in positions], encoder, registry)
        for index, value in zip(positions, read):
            values[index] = value
    return values


def _observe(bundle, events, encoder, epoch):
    values, seconds = _predict(bundle, events, encoder)
    correct = [value == event.value for value, event in zip(values, events)]
    old = [ok for ok, event in zip(correct, events) if event.step < epoch]
    metrics = {
        "accuracy": sum(correct) / len(correct),
        "correct": sum(correct),
        "queries": len(events),
        "retained_accuracy": sum(old) / len(old) if old else None,
        "seconds": seconds,
        "domain_error": {
            domain: 1
            - sum(ok for ok, e in zip(correct, events) if e.domain == domain)
            / sum(e.domain == domain for e in events)
            for domain in DOMAINS
        },
    }
    return metrics, [
        {"key": e.key, "domain": e.domain, "target": e.value, "prediction": value}
        for e, value in zip(events, values)
    ]


def restore_checkpoint(path, registry):
    """Verify route/model bindings and current lineage before restoring tensors."""
    envelope = json.loads(Path(path).read_text())
    if set(envelope) != {"payload", "sha256"}:
        raise LifecycleError("invalid checkpoint envelope")
    payload, digest = envelope["payload"], envelope["sha256"]
    if (
        set(payload) != {"schema", "id", "spec", "encoder", "models", "source_commit"}
        or payload["schema"] != "memory-cell-v2.checkpoint.v1"
    ):
        raise LifecycleError("invalid checkpoint schema")
    if sha256(canonical_bytes(payload)).hexdigest() != digest:
        raise LifecycleError("checkpoint digest mismatch")
    if (
        not registry.usable(payload["id"])
        or registry.records[payload["id"]].parameter_digest != digest
    ):
        raise LifecycleError("checkpoint not admitted by current lineage owner")
    spec = payload["spec"]
    if set(spec) != {"route", "ranks"} or spec["route"] not in {
        "single",
        "domain",
        "hash",
    }:
        raise LifecycleError("invalid route contract")
    if len(spec["ranks"]) != len(payload["models"]) or sum(spec["ranks"]) != 16:
        raise LifecycleError("checkpoint parameter budget mismatch")
    if (
        tuple(sorted(b["id"] for b in payload["models"]))
        != registry.records[payload["id"]].parents
    ):
        raise LifecycleError("checkpoint owner/model lineage mismatch")
    models = []
    encoder = FrozenEncoder.from_manifest(payload["encoder"])
    for index, binding in enumerate(payload["models"]):
        if (
            set(binding) != {"id", "path", "manifest_sha256"}
            or binding["path"] != f"cell-{index}"
        ):
            raise LifecycleError("checkpoint model path mismatch")
        model_dir = Path(path).parent / binding["path"]
        manifest = json.loads((model_dir / "manifest.json").read_text())
        if (
            manifest["manifest_sha256"] != binding["manifest_sha256"]
            or manifest["tensor_sha256"]
            != registry.records[binding["id"]].parameter_digest
        ):
            raise LifecycleError("checkpoint model binding mismatch")
        models.append(
            MemoryCell.load(model_dir, expected_encoder_digest=encoder.digest)
        )
        if models[-1].rank != spec["ranks"][index]:
            raise LifecycleError("checkpoint/model rank mismatch")
    return {
        "id": payload["id"],
        "spec": payload["spec"],
        "models": models,
        "model_ids": [b["id"] for b in payload["models"]],
        "path": Path(path).parent,
    }


def _train(
    name,
    spec,
    events,
    encoder,
    profile,
    directory,
    source_commit,
    seed,
    registry,
    *,
    parent=None,
    distill=False,
):
    started = time.perf_counter()
    directory.mkdir(parents=True, exist_ok=False)
    teacher_values, teacher_seconds = (
        _predict(parent, events, encoder) if distill else (None, 0.0)
    )
    models, bindings, receipts, sources = [], [], [], [_identity(e) for e in events]
    for index, rank in enumerate(spec["ranks"]):
        positions = [
            i for i, event in enumerate(events) if _route(spec, event) == index
        ]
        inputs = [f"{events[i].domain} {events[i].key}" for i in positions]
        labels = [teacher_values[i] if distill else events[i].value for i in positions]
        inherited = parent is not None and not distill
        parent_index = index if inherited and len(parent["models"]) > 1 else 0
        parents = (
            parent["model_ids"]
            if distill
            else ([parent["model_ids"][parent_index]] if inherited else [])
        )
        if inherited:
            cell, inheritance = parent["models"][parent_index].resize_rank(
                rank, seed + index
            )
        else:
            cell, inheritance = (
                MemoryCell(encoder.dim, rank, profile["num_classes"], seed + index),
                None,
            )
        parent_bindings = [
            {
                "id": p,
                "parameter_digest": registry.records[p].parameter_digest,
                "generation": registry.records[p].generation,
            }
            for p in parents
        ]
        training = {
            "inputs": inputs,
            "targets": labels,
            "source_revisions": [sources[i] for i in positions],
            "parents": parent_bindings,
            "distillation": distill,
            "inheritance": inheritance,
        }
        _json(directory / f"training-{index}.json", training)
        receipt = cell.fit(
            encoder.encode(inputs),
            np.asarray(labels),
            steps=profile["steps"],
            lr=profile["learning_rate"],
        )
        lineage = {
            "dataset": sha256(canonical_bytes(training)).hexdigest(),
            "source_commit": source_commit,
        }
        if parents:
            lineage["parent"] = sha256(canonical_bytes(parent_bindings)).hexdigest()
        manifest = cell.save(
            directory / f"cell-{index}",
            encoder_manifest=encoder.manifest(),
            lineage=lineage,
        )
        models.append(
            MemoryCell.load(
                directory / f"cell-{index}", expected_encoder_digest=encoder.digest
            )
        )
        model_id = f"{name}/cell-{index}"
        _register(
            registry,
            model_id,
            manifest["tensor_sha256"],
            [sources[i] for i in positions],
            parents,
        )
        bindings.append(
            {
                "id": model_id,
                "path": f"cell-{index}",
                "manifest_sha256": manifest["manifest_sha256"],
            }
        )
        receipts.append(receipt)
    payload = {
        "schema": "memory-cell-v2.checkpoint.v1",
        "id": name,
        "spec": spec,
        "encoder": encoder.manifest(),
        "models": bindings,
        "source_commit": source_commit,
    }
    digest = sha256(canonical_bytes(payload)).hexdigest()
    _register(registry, name, digest, (), [b["id"] for b in bindings])
    _json(directory / "checkpoint.json", {"payload": payload, "sha256": digest})
    receipt = {
        "training": receipts,
        "teacher_read_seconds": teacher_seconds,
        "write_seconds": time.perf_counter() - started,
        "training_source_count": len(events),
        "distillation": distill,
        "from_fresh_initialization": parent is None,
        "trainable_parameters": sum(m.trainable_params for m in models),
        "parameter_bytes": sum(m.parameter_bytes for m in models),
    }
    _json(directory / "receipt.json", receipt)
    return {
        "id": name,
        "spec": spec,
        "models": models,
        "model_ids": [b["id"] for b in bindings],
        "path": directory,
        "receipt": receipt,
    }


def _migrate(bundle, old, registry, encoder, selection, slot):
    started = time.perf_counter()
    previous = registry.selections.get(slot)
    expected = previous.revision if previous else 0
    adopted = registry.adopt(slot, bundle["id"], expected_revision=expected)
    registry.save(bundle["path"] / "owner-checkpoint.json")
    restored_owner = MemoryRegistry.load(
        bundle["path"] / "owner-checkpoint.json",
        current_revoked_sources=registry.revoked_sources,
    )
    restored = restore_checkpoint(bundle["path"] / "checkpoint.json", restored_owner)
    probes = selection[: min(16, len(selection))]
    before, _ = _predict(bundle, probes, encoder, registry)
    after, _ = _predict(restored, probes, encoder, restored_owner)
    if (
        before != after
        or restored_owner.resolve(slot, scope=SCOPE).artifact_id != bundle["id"]
    ):
        raise LifecycleError("checkpoint restore changed selected route predictions")
    receipt = {
        "expected_revision": expected,
        "adopted_revision": adopted.revision,
        "old_checkpoint": old["id"] if old else None,
        "new_checkpoint": bundle["id"],
        "structure_changed": old is not None and old["spec"] != bundle["spec"],
        "probe_queries": len(probes),
        "restored_predictions_equal": True,
        "route_generation_changed": old is None or old["id"] != bundle["id"],
        "seconds": time.perf_counter() - started,
    }
    _json(bundle["path"] / "migration.json", receipt)
    restored["receipt"] = bundle["receipt"]
    return restored, receipt


def _split_spec(events, observation):
    weights = [
        sum(e.domain == d for e in events) * (0.05 + observation["domain_error"][d])
        for d in DOMAINS
    ]
    first = min(12, max(4, 4 * round(4 * weights[0] / sum(weights))))
    return {"route": "domain", "ranks": [first, 16 - first]}


def _ledger(arm, directory, state, profile, shared_setup_seconds):
    bundles, migrations, deployed = (
        state["bundles"],
        state["migrations"],
        state["active"],
    )
    selection_seconds, hidden_seconds, queries = (
        state["selection_seconds"],
        state["hidden_seconds"],
        state["queries"],
    )
    write_seconds = sum(b["receipt"]["write_seconds"] for b in bundles)
    migration_seconds = sum(m["seconds"] for m in migrations)
    maintenance_seconds = max(
        0.0, state["wall_seconds"] - write_seconds - selection_seconds - hidden_seconds
    )
    source_bytes = (directory.parent / "source-stream.json").stat().st_size
    withdrawal_bytes = (directory.parent / "withdrawal.json").stat().st_size
    retained_bytes = measure_bytes([directory]) + source_bytes + withdrawal_bytes
    fixed_cost = profile["byte_price"] * retained_bytes + profile[
        "training_second_price"
    ] * (write_seconds + maintenance_seconds + shared_setup_seconds)
    fixed_cost += profile["read_second_price"] * selection_seconds
    read_per_query = sum(
        o["seconds"] / o["queries"] for o in state["hidden_batches"]
    ) / len(state["hidden_batches"])
    expected_queries = profile["query_budget"] * len(state["hidden_batches"])
    expected_cost = (
        fixed_cost + profile["read_second_price"] * read_per_query * expected_queries
    )
    return {
        "arm": arm,
        "attempted_checkpoints": [b["id"] for b in bundles],
        "write_seconds": write_seconds,
        "migration_restore_seconds": migration_seconds,
        "other_maintenance_seconds_including_migrations": maintenance_seconds,
        "shared_setup_seconds_charged_once": shared_setup_seconds,
        "selection_read_seconds": selection_seconds,
        "observed_hidden_read_seconds": hidden_seconds,
        "hidden_queries": queries,
        "observed_read_seconds_per_query": hidden_seconds / queries,
        "read_seconds_per_query": read_per_query,
        "shared_source_stream_bytes_charged_once": source_bytes,
        "shared_withdrawal_frontier_bytes_charged_once": withdrawal_bytes,
        "retained_artifact_source_and_replay_bytes": retained_bytes,
        "deployed_parameter_bytes": sum(m.parameter_bytes for m in deployed["models"]),
        "deployed_checkpoint_bytes": measure_bytes(
            [deployed["path"] / "checkpoint.json"]
            + [deployed["path"] / f"cell-{i}" for i in range(len(deployed["models"]))]
        ),
        "fixed_lifecycle_priced_cost": fixed_cost,
        "expected_read_queries_at_protocol_h": expected_queries,
        "expected_resource_cost_at_protocol_h": expected_cost,
        "amortized_resource_cost_per_query": expected_cost / expected_queries,
        "accounting_scope": "standalone arm: every attempted checkpoint, replay, owner backup and audit file; shared source/frontier charged once; all arm wall time except hidden probes becomes upfront write/maintenance or selection-read cost; hidden latency extrapolated to H equally per update; aggregate summaries excluded",
        "latency_scope": "one observed hidden batch per update; no timing confidence interval",
        "training_receipts": [b["receipt"] for b in bundles],
    }


def _run_seed(profile, output, source_commit, seed):
    setup_started = time.perf_counter()
    encoder = FrozenEncoder(profile["feature_dim"], seed=0)
    max_sizes = tuple(profile["snapshots"][-1])
    all_events = make_associative(
        seed, max_sizes, profile["num_classes"], DOMAINS
    ).events
    grouped = {d: [e for e in all_events if e.domain == d] for d in DOMAINS}
    arrivals = {
        (e.domain, e.key): next(
            t for t, sizes in enumerate(profile["snapshots"]) if i < sizes[d]
        )
        for d, domain in enumerate(DOMAINS)
        for i, e in enumerate(grouped[domain])
    }
    all_events = tuple(replace(e, step=arrivals[(e.domain, e.key)]) for e in all_events)
    _json(
        output / "source-stream.json",
        {"events": [asdict(e) for e in all_events], "snapshots": profile["snapshots"]},
    )
    specs = {
        "policy": {"route": "single", "ranks": [16]},
        "fixed-single": {"route": "single", "ranks": [16]},
        "fixed-domain": {"route": "domain", "ranks": [8, 8]},
        "fixed-hash": {"route": "hash", "ranks": [8, 8]},
    }
    states = {
        arm: {
            "registry": MemoryRegistry(),
            "active": None,
            "bundles": [],
            "migrations": [],
            "selection_seconds": 0.0,
            "hidden_seconds": 0.0,
            "correct": 0,
            "queries": 0,
            "wall_seconds": 0.0,
            "hidden_batches": [],
        }
        for arm in specs
    }
    shared_setup_seconds = time.perf_counter() - setup_started
    phases = []
    for epoch in range(len(profile["snapshots"])):
        events = tuple(e for e in all_events if e.step <= epoch)
        selection, hidden = partition_keys(events)
        phase = {
            "epoch": epoch,
            "written_sources": len(events),
            "selection_keys": len(selection),
            "hidden_keys": len(hidden),
            "effective_keys_disjoint": not bool(
                {e.key for e in selection} & {e.key for e in hidden}
            ),
            "selection": {},
            "hidden": {},
            "search_triggered": False,
        }
        for arm, state in states.items():
            arm_started = time.perf_counter()
            parent, registry = state["active"], state["registry"]
            spec = parent["spec"] if parent else specs[arm]
            base = _train(
                f"{arm}-e{epoch}-no_change",
                spec,
                events,
                encoder,
                profile,
                output / arm / f"epoch-{epoch}" / "no_change",
                source_commit,
                seed + epoch * 100,
                registry,
                parent=parent,
            )
            candidates = [base]
            observations, raw = {}, {}
            observations[base["id"]], raw[base["id"]] = _observe(
                base, selection, encoder, epoch
            )
            if (
                arm == "policy"
                and 1 - observations[base["id"]]["accuracy"] > profile["trigger_error"]
            ):
                phase["search_triggered"] = True
                split = _train(
                    f"{arm}-e{epoch}-split",
                    _split_spec(events, observations[base["id"]]),
                    events,
                    encoder,
                    profile,
                    output / arm / f"epoch-{epoch}" / "split",
                    source_commit,
                    seed + epoch * 100 + 31,
                    registry,
                    parent=base,
                )
                merge = _train(
                    f"{arm}-e{epoch}-merge",
                    specs["fixed-single"],
                    events,
                    encoder,
                    profile,
                    output / arm / f"epoch-{epoch}" / "merge",
                    source_commit,
                    seed + epoch * 100 + 53,
                    registry,
                    parent=split,
                    distill=True,
                )
                candidates.extend((split, merge))
            for candidate in candidates[1:]:
                observations[candidate["id"]], raw[candidate["id"]] = _observe(
                    candidate, selection, encoder, epoch
                )

            def objective(candidate):
                observed = observations[candidate["id"]]
                resource = profile["byte_price"] * sum(
                    m.parameter_bytes for m in candidate["models"]
                )
                resource += (
                    profile["training_second_price"]
                    * candidate["receipt"]["write_seconds"]
                )
                return (
                    1
                    - observed["accuracy"]
                    + resource / profile["query_budget"]
                    + profile["read_second_price"]
                    * observed["seconds"]
                    / len(selection)
                )

            baseline_retained = observations[base["id"]]["retained_accuracy"]
            eligible = [
                c
                for c in candidates
                if baseline_retained is None
                or observations[c["id"]]["retained_accuracy"]
                >= baseline_retained - profile["max_retention_regression"]
            ]
            best = min(eligible, key=lambda c: (objective(c), c["id"]))
            chosen = (
                best
                if objective(base) - objective(best) > profile["min_selection_gain"]
                else base
            )
            decision = {
                "selected": chosen["id"],
                "operation": chosen["id"].rsplit("-", 1)[-1],
                "observations": observations,
                "objectives": {c["id"]: objective(c) for c in candidates},
                "selection_only": True,
                "spec": chosen["spec"],
            }
            _json(output / arm / f"epoch-{epoch}" / "decision.json", decision)
            _json(output / arm / f"epoch-{epoch}" / "selection-predictions.json", raw)
            state["active"], migration = _migrate(
                chosen, parent, registry, encoder, selection, arm
            )
            state["bundles"].extend(candidates)
            state["migrations"].append(migration)
            state["selection_seconds"] += sum(
                o["seconds"] for o in observations.values()
            )
            observed, raw_hidden = _observe(state["active"], hidden, encoder, epoch)
            state["hidden_seconds"] += observed["seconds"]
            state["queries"] += observed["queries"]
            state["correct"] += observed["correct"]
            state["hidden_batches"].append(observed)
            _json(
                output / arm / f"epoch-{epoch}" / "hidden-predictions.json", raw_hidden
            )
            phase["selection"][arm], phase["hidden"][arm] = decision, observed
            state["wall_seconds"] += time.perf_counter() - arm_started
        phases.append(phase)
    withdrawal_started = time.perf_counter()
    deleted = tuple(
        sorted(
            all_events,
            key=lambda e: sha256(canonical_bytes(["revoke", e.key])).hexdigest(),
        )[: profile["revocations"]]
    )
    revoked = {_identity(e) for e in deleted}
    revoked_keys = {(e.domain, e.key) for e in deleted}
    _json(
        output / "withdrawal.json",
        {"source_revisions": sorted(revoked), "keys": sorted(revoked_keys)},
    )
    current = tuple(e for e in all_events if _identity(e) not in revoked)
    selection, hidden = partition_keys(current)
    shared_setup_seconds += time.perf_counter() - withdrawal_started
    maintenance = {}
    for arm, state in states.items():
        arm_started = time.perf_counter()
        registry, before = state["registry"], state["active"]
        tainted = [
            b
            for b in state["bundles"]
            if any(set(registry.records[p].sources) & revoked for p in b["model_ids"])
        ]
        for source_id in revoked:
            registry.revoke_source(source_id)
        blocked = False
        try:
            _predict(before, deleted, encoder, registry)
        except LifecycleError:
            blocked = True
        restored = MemoryRegistry.load(
            before["path"] / "owner-checkpoint.json", current_revoked_sources=revoked
        )
        stale_blocked = False
        try:
            restore_checkpoint(before["path"] / "checkpoint.json", restored)
        except LifecycleError:
            stale_blocked = True
        clean = _train(
            f"{arm}-consolidation",
            before["spec"],
            current,
            encoder,
            profile,
            output / arm / "consolidation",
            source_commit,
            seed + 701,
            registry,
        )
        state["active"], migration = _migrate(
            clean, before, registry, encoder, selection, arm
        )
        state["bundles"].append(clean)
        state["migrations"].append(migration)
        observed, raw = _observe(clean, hidden, encoder, len(phases))
        state["hidden_seconds"] += observed["seconds"]
        state["correct"] += observed["correct"]
        state["queries"] += observed["queries"]
        state["hidden_batches"].append(observed)
        residual, _ = _predict(clean, deleted, encoder)
        refused = serve(clean, deleted, encoder, registry, revoked_keys)
        _json(output / arm / "consolidation" / "hidden-predictions.json", raw)
        maintenance[arm] = {
            "revoked_parent_blocked": blocked,
            "stale_restore_blocked": stale_blocked,
            "all_tainted_checkpoints_blocked": all(
                not registry.usable(b["id"]) for b in tainted
            ),
            "tainted_checkpoint_count": len(tainted),
            "deleted_interface_refused": sum(v is None for v in refused),
            "fresh_sources_exclude_revoked": not bool(
                {_identity(e) for e in current} & revoked
            ),
            "clean_hidden": observed,
            "deleted_raw_old_value_matches": sum(
                v == e.value for v, e in zip(residual, deleted)
            ),
            "deletion_count": len(deleted),
            "method": "full fresh retraining; not selective parameter erasure",
        }
        state["wall_seconds"] += time.perf_counter() - arm_started
    ledgers = {
        arm: _ledger(arm, output / arm, s, profile, shared_setup_seconds)
        for arm, s in states.items()
    }
    accuracy = {arm: s["correct"] / s["queries"] for arm, s in states.items()}
    macro_accuracy = {
        arm: sum(o["accuracy"] for o in s["hidden_batches"]) / len(s["hidden_batches"])
        for arm, s in states.items()
    }
    curves, comparisons = {}, {}
    for arm in specs:
        if arm == "policy":
            continue
        policy, fixed = ledgers["policy"], ledgers[arm]
        fixed_delta = (
            policy["fixed_lifecycle_priced_cost"] - fixed["fixed_lifecycle_priced_cost"]
        )
        per_query_gain = (
            macro_accuracy["policy"]
            - macro_accuracy[arm]
            - profile["read_second_price"]
            * (policy["read_seconds_per_query"] - fixed["read_seconds_per_query"])
        )
        curves[arm] = [
            {
                "queries_per_update": h,
                "net_gain_per_query": per_query_gain
                - fixed_delta / (h * (len(phases) + 1)),
            }
            for h in profile["cost_horizons"]
        ]
        comparisons[arm] = {
            "accuracy_gain": macro_accuracy["policy"] - macro_accuracy[arm],
            "net_gain_per_query_at_protocol_h": per_query_gain
            - fixed_delta / (profile["query_budget"] * (len(phases) + 1)),
            "break_even_queries_per_update": max(
                0.0, fixed_delta / per_query_gain / (len(phases) + 1)
            )
            if per_query_gain > 0
            else None,
        }
    accepted_operations = [
        p["selection"]["policy"]["operation"]
        for p in phases
        if p["selection"]["policy"]["operation"] != "no_change"
    ]
    guards_passed = all(
        m["revoked_parent_blocked"]
        and m["stale_restore_blocked"]
        and m["all_tainted_checkpoints_blocked"]
        and m["fresh_sources_exclude_revoked"]
        and m["deleted_interface_refused"] == m["deletion_count"]
        for m in maintenance.values()
    )
    result = {
        "seed": seed,
        "phases": phases,
        "maintenance": maintenance,
        "costs": ledgers,
        "stream_accuracy": accuracy,
        "mean_update_accuracy": macro_accuracy,
        "comparisons": comparisons,
        "break_even_curves": curves,
        "accepted_evolution_operations": accepted_operations,
        "maintenance_guards_passed": guards_passed,
        "research_wall_seconds_before_summary": time.perf_counter() - setup_started,
        "research_physical_bytes_before_summary": measure_bytes([output]),
        "criterion_met": bool(accepted_operations)
        and guards_passed
        and all(
            v["accuracy_gain"] > 0.02 and v["net_gain_per_query_at_protocol_h"] > 0
            for v in comparisons.values()
        ),
        "scope": "numerical written-key stream; given domains; selection-residual rank allocation; all search costs retained",
    }
    _json(output / "summary.json", result)
    return result


def run_growth(
    protocol,
    output_dir: Path,
    source_commit: str,
    seeds: list[int],
    *,
    development=False,
) -> dict:
    profile = dict(protocol["growth_v2_profile"])
    if development and not set(seeds) <= {8001, 8003}:
        raise ValueError("development is limited to preregistered seeds 8001 and 8003")
    if (
        profile["rank_budget"] != 16
        or profile["revocations"] < 1
        or profile["query_budget"] <= 0
    ):
        raise ValueError("invalid frozen-rank growth profile")
    snapshots = profile["snapshots"]
    if (
        not snapshots
        or any(len(s) != 2 or min(s) < 4 for s in snapshots)
        or any(
            a > b
            for previous, current in zip(snapshots, snapshots[1:])
            for a, b in zip(previous, current)
        )
    ):
        raise ValueError(
            "stream snapshots must contain two positive monotone source counts"
        )
    directory = Path(output_dir) / "growth"
    directory.mkdir(parents=True, exist_ok=False)
    dependencies = {
        "model": MemoryCell.fit,
        "encoding": FrozenEncoder.encode,
        "lineage": MemoryRegistry.register,
        "data": make_associative,
        "metrics": measure_bytes,
    }
    _json(
        directory / "config.json",
        {
            "profile": profile,
            "source_commit": source_commit,
            "source_module_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
            "v1_dependency_sha256": {
                name: sha256(Path(fn.__code__.co_filename).read_bytes()).hexdigest()
                for name, fn in dependencies.items()
            },
            "runtime": {
                "python": platform.python_version(),
                "numpy": np.__version__,
                "platform": platform.system(),
                "parameter_dtype": "float64",
                "thread_settings": {
                    name: os.environ.get(name)
                    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")
                },
            },
            "seeds": seeds,
            "development_only": development,
            "hidden_keys": "independent SHA256 namespace from routing",
        },
    )
    runs = [
        _run_seed(profile, directory / f"seed-{seed}", source_commit, seed)
        for seed in seeds
    ]
    result = {
        "stage": "growth_v2",
        "development_only": development,
        "profile": profile,
        "runs": runs,
    }
    _json(directory / "summary.json", result)
    return result
