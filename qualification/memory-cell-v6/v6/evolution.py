"""Budgeted, measured candidate competition for isolated associative cells.

Partitions use address features only. Every fit and rejected candidate is charged.
The selection set chooses a candidate; test queries never enter this controller.
The work proxy is arithmetic accounting, not measured hardware FLOPs or energy.
"""

import base64
import hashlib
import json
import math
import time
import zlib

import numpy as np

from .cells import AssociativeCell, canonical, encode, key_digest


def frontier_digest(records):
    return hashlib.sha256(canonical(sorted(records, key=lambda row: row["key"]))).hexdigest()


def partitions(keys, count, seed):
    """Deterministic bounded k-means over target-independent address features."""
    if not 1 <= count <= min(8, len(keys)):
        raise ValueError("invalid partition count")
    if count == 1:
        return np.zeros(len(keys), dtype=int)
    x = encode(keys, 16)
    rng = np.random.default_rng(seed)
    centers = x[rng.choice(len(keys), count, replace=False)].copy()
    labels = np.zeros(len(keys), dtype=int)
    for _ in range(20):
        distances = ((x[:, None] - centers[None]) ** 2).sum(axis=2)
        labels = distances.argmin(axis=1)
        for index in range(count):
            members = x[labels == index]
            if len(members):
                centers[index] = members.mean(axis=0)
            else:
                largest = int(np.argmax(distances.min(axis=1)))
                labels[largest], centers[index] = index, x[largest]
    # Empty clusters may persist on tiny degenerate sets; compact without invention.
    mapping = {value: index for index, value in enumerate(sorted(set(labels)))}
    return np.array([mapping[value] for value in labels])


class CellEnsemble:
    """Immutable parameter generation with a mutable, disposable resident cache."""

    @classmethod
    def fit(
        cls,
        records,
        labels,
        *,
        seed=0,
        total_hidden=64,
        steps=300,
        parent=None,
        generation=1,
        parameter_budget_bytes=None,
    ):
        if not records or len(labels) != len(records) or len({row["key"] for row in records}) != len(records):
            raise ValueError("unique aligned training records required")
        kind = records[0]["kind"]
        if any(row["kind"] != kind for row in records):
            raise ValueError("one ensemble must have one memory type")
        groups = sorted(set(int(value) for value in labels))
        if not 1 <= len(groups) <= 8 or total_hidden < len(groups):
            raise ValueError("partition budget exceeded")
        grouped = [[row for row, label in zip(records, labels) if int(label) == group] for group in groups]
        widths = [total_hidden // len(groups)] * len(groups)
        if parameter_budget_bytes is not None:
            classes = [len({canonical(row["value"]) for row in rows}) for rows in grouped]
            increments = [4 * (64 + count + 1) for count in classes]
            widths = [1] * len(groups)
            remaining = parameter_budget_bytes - sum(increments) - 4 * sum(classes)
            if remaining < 0:
                raise ValueError("parameter budget cannot contain the minimum candidate")
            while available := [
                i for i, increment in enumerate(increments) if increment <= remaining and widths[i] < 256
            ]:
                index = min(available, key=lambda i: (widths[i], i))
                widths[index] += 1
                remaining -= increments[index]
        ensemble = cls()
        ensemble.generation, ensemble.kind = generation, kind
        ensemble.frontier = frontier_digest(records)
        ensemble.routes, ensemble.raw, ensemble.cache = {}, [], []
        ensemble.reload_count, ensemble.reload_seconds = 0, 0.0
        for index, rows in enumerate(grouped):
            inherited = None
            if parent is not None:
                overlap = [
                    sum(parent.routes.get(key_digest(row["key"])) == old for row in rows)
                    for old in range(len(parent.raw))
                ]
                if max(overlap, default=0):
                    inherited = parent._load(int(np.argmax(overlap)))
            cell = AssociativeCell.fit(
                [row["key"] for row in rows],
                [row["value"] for row in rows],
                seed + index,
                support_ids=[[row["event_id"]] for row in rows],
                kind=kind,
                hidden=widths[index],
                steps=steps,
                parent=inherited,
            )
            ensemble.raw.append(cell.to_bytes())
            ensemble.cache.append(cell)
            ensemble.routes.update({key_digest(row["key"]): index for row in rows})
        return ensemble

    def _load(self, index):
        if self.cache[index] is None:
            started = time.perf_counter()
            self.cache[index] = AssociativeCell.from_bytes(self.raw[index])
            self.reload_count += 1
            self.reload_seconds += time.perf_counter() - started
        return self.cache[index]

    def read(self, key):
        index = self.routes.get(key_digest(key))
        if index is None:
            return {"value": None, "abstain": "outside-written-support", "support_ids": []}
        return {**self._load(index).read(key), "cell_index": index, "generation": self.generation}

    def sleep(self, indexes=None):
        indexes = range(len(self.raw)) if indexes is None else indexes
        for index in indexes:
            if type(index) is not int or not 0 <= index < len(self.raw):
                raise ValueError("invalid dormant cell index")
            self.cache[index] = None

    def to_bytes(self):
        value = {
            "schema": "hepta.memory.v6.ensemble.v1",
            "generation": self.generation,
            "kind": self.kind,
            "frontier": self.frontier,
            "routes": self.routes,
            "cells": [base64.b64encode(raw).decode() for raw in self.raw],
        }
        return canonical({"payload": value, "sha256": hashlib.sha256(canonical(value)).hexdigest()})

    @classmethod
    def from_bytes(cls, raw):
        if not isinstance(raw, bytes) or len(raw) > 64_000_000:
            raise ValueError("invalid ensemble artifact")
        envelope = json.loads(raw)
        value = envelope["payload"]
        if set(envelope) != {"payload", "sha256"} or hashlib.sha256(canonical(value)).hexdigest() != envelope["sha256"]:
            raise ValueError("ensemble digest mismatch")
        if (
            set(value) != {"schema", "generation", "kind", "frontier", "routes", "cells"}
            or value["schema"] != "hepta.memory.v6.ensemble.v1"
        ):
            raise ValueError("invalid ensemble schema")
        if type(value["generation"]) is not int or value["generation"] < 1 or not 1 <= len(value["cells"]) <= 8:
            raise ValueError("invalid ensemble generation or cell count")
        result = cls()
        result.generation, result.kind, result.frontier, result.routes = (
            value[name] for name in ("generation", "kind", "frontier", "routes")
        )
        result.raw = [base64.b64decode(item, validate=True) for item in value["cells"]]
        result.cache = [AssociativeCell.from_bytes(item) for item in result.raw]
        reconstructed = {}
        for index, cell in enumerate(result.cache):
            if cell.kind != result.kind or set(reconstructed) & set(cell.supports):
                raise ValueError("incompatible or duplicate cell support")
            reconstructed.update({address: index for address in cell.supports})
        if reconstructed != result.routes:
            raise ValueError("route inventory differs from parameter support")
        result.reload_count, result.reload_seconds = 0, 0.0
        return result

    def cost(self):
        metadata = [AssociativeCell.from_bytes(raw).cost() for raw in self.raw]
        return {
            "cells": len(self.raw),
            "serialized_bytes": len(self.to_bytes()),
            "parameter_bytes": sum(item["parameter_bytes"] for item in metadata),
            "catalog_bytes": sum(item["catalog_bytes"] for item in metadata),
            "source_support_bytes": sum(item["support_bytes"] for item in metadata),
            "training_cpu_seconds": sum(item["training_cpu_seconds"] for item in metadata),
            "training_steps": sum(item["training_steps"] for item in metadata),
            "route_bytes": len(canonical(self.routes)),
            "loaded_parameter_bytes": sum(cell.cost()["parameter_bytes"] for cell in self.cache if cell is not None),
            "serialized_cache_bytes": sum(len(raw) for raw in self.raw),
            "reload_count": self.reload_count,
            "reload_seconds": self.reload_seconds,
            "full_process_rss_measured": False,
        }


def _measure(ensemble, keys, values):
    start = time.perf_counter()
    reads = [ensemble.read(key) for key in keys]
    correct = sum(row["abstain"] is None and row["value"] == target for row, target in zip(reads, values))
    work = sum(
        cell.dimension * cell.hidden + cell.hidden * len(cell.catalog)
        for key in keys
        if (index := ensemble.routes.get(key_digest(key))) is not None
        for cell in [ensemble._load(index)]
    )
    return {
        "rows": len(keys),
        "correct": correct,
        "accuracy": correct / len(keys) if keys else None,
        "read_seconds": time.perf_counter() - start,
        "read_work_proxy": work,
        "mean_read_work_proxy": work / len(keys) if keys else 0,
    }


class EvolutionController:
    """Select complete successor candidates without publishing a live topology."""

    def __init__(
        self,
        *,
        maximum_bytes=512_000,
        total_hidden=64,
        steps=300,
        storage_price=1e-7,
        work_price=1e-11,
        inference_work_price=1e-9,
        expected_future_queries=10_000,
        retention_floor=0.98,
        maximum_search_bytes=4_000_000,
        maximum_search_work=10_000_000_000,
        parameter_budget_bytes=None,
    ):
        if (
            maximum_bytes <= 0
            or total_hidden < 4
            or steps < 1
            or storage_price < 0
            or work_price < 0
            or inference_work_price < 0
            or not 0 <= retention_floor <= 1
            or type(expected_future_queries) is not int
            or expected_future_queries < 1
            or maximum_search_bytes < 1
            or maximum_search_work < 1
            or parameter_budget_bytes is not None
            and (type(parameter_budget_bytes) is not int or parameter_budget_bytes < 1)
        ):
            raise ValueError("invalid frozen structure budget")
        self.maximum_bytes, self.total_hidden, self.steps = maximum_bytes, total_hidden, steps
        self.storage_price, self.work_price, self.retention_floor = storage_price, work_price, retention_floor
        self.inference_work_price, self.expected_future_queries = inference_work_price, expected_future_queries
        self.maximum_search_bytes, self.maximum_search_work = maximum_search_bytes, maximum_search_work
        self.parameter_budget_bytes = parameter_budget_bytes

    def propose(
        self,
        records,
        selection_keys,
        selection_values,
        *,
        parent=None,
        seed=0,
        retention_keys=None,
        retention_values=None,
    ):
        if not selection_keys or len(selection_keys) != len(selection_values):
            raise ValueError("selection queries are required")
        retention_keys = [] if retention_keys is None else list(retention_keys)
        retention_values = [] if retention_values is None else list(retention_values)
        if len(retention_keys) != len(retention_values) or set(retention_keys) & set(selection_keys):
            raise ValueError("retention must be aligned and independent of structure selection")
        if parent is not None and (
            not retention_keys or any(key_digest(key) not in parent.routes for key in retention_keys)
        ):
            raise ValueError("parent evolution requires an independent old-address retention set")
        keys = [row["key"] for row in records]
        if not set(selection_keys) <= set(keys):
            raise ValueError("structure selection queries must address written memory")
        if not set(retention_keys) <= set(keys):
            raise ValueError("retention queries must address surviving written memory")
        candidates, ledger = [], []
        generation = 1 if parent is None else parent.generation + 1
        specifications = [("refit", partitions(keys, 1, seed), None)]
        specifications += [(f"fixed_{k}", partitions(keys, k, seed), None) for k in (2, 4) if k <= len(keys)]
        if parent is not None:
            old_labels = np.array([parent.routes.get(key_digest(key), 0) for key in keys])
            groups = len(set(old_labels))
            if groups < min(8, len(keys)):
                counts = np.bincount(old_labels)
                chosen = int(counts.argmax())
                member_indexes = np.flatnonzero(old_labels == chosen)
                if len(member_indexes) > 1:
                    split = old_labels.copy()
                    local = partitions([keys[i] for i in member_indexes], 2, seed + 101)
                    split[member_indexes[local == 1]] = int(old_labels.max()) + 1
                    specifications.append(("split", split, parent))
            if groups > 1:
                merged = old_labels.copy()
                a, b = sorted(set(old_labels))[-2:]
                merged[merged == b] = a
                specifications.append(("merge", merged, parent))
            if parent.frontier == frontier_digest(records):
                kept = CellEnsemble.from_bytes(parent.to_bytes())
                kept.generation = generation
                candidates.append(("keep", kept, 0, 0.0))
        for name, labels, inherited in specifications:
            start = time.process_time()
            model = CellEnsemble.fit(
                records,
                labels,
                seed=seed,
                total_hidden=self.total_hidden,
                steps=self.steps,
                parent=inherited,
                generation=generation,
                parameter_budget_bytes=self.parameter_budget_bytes,
            )
            cpu = time.process_time() - start
            work = sum(
                cell.training_receipt["examples_seen"]
                * (cell.dimension * cell.hidden + cell.hidden * len(cell.catalog))
                for cell in model.cache
            )
            candidates.append((name, model, work, cpu))
        for name, model, work, cpu in candidates:
            measured = _measure(model, selection_keys, selection_values)
            retention = _measure(model, retention_keys, retention_values)
            cost = model.cost()
            reasons = []
            if cost["serialized_bytes"] > self.maximum_bytes:
                reasons.append("serving-byte-budget")
            if self.parameter_budget_bytes is not None and cost["parameter_bytes"] > self.parameter_budget_bytes:
                reasons.append("parameter-byte-budget")
            if retention_keys and retention["accuracy"] < self.retention_floor:
                reasons.append("old-memory-retention")
            per_query = 1 - measured["accuracy"] + self.inference_work_price * measured["mean_read_work_proxy"]
            evaluation_work = measured["read_work_proxy"] + retention["read_work_proxy"]
            fixed_upfront = self.storage_price * cost["serialized_bytes"] + self.work_price * (work + evaluation_work)
            ledger.append(
                {
                    "name": name,
                    "selection": measured,
                    "retention": retention,
                    "cost": cost,
                    "parameter_budget_slack_bytes": None
                    if self.parameter_budget_bytes is None
                    else self.parameter_budget_bytes - cost["parameter_bytes"],
                    "training_work_proxy": work,
                    "evaluation_work_proxy": evaluation_work,
                    "candidate_cpu_seconds": cpu,
                    "per_query_objective": per_query,
                    "own_upfront_objective": fixed_upfront,
                    "own_projected_total": fixed_upfront + self.expected_future_queries * per_query,
                    "eligible": not reasons,
                    "rejection_reasons": reasons,
                }
            )
        self.candidate_artifacts = {name: model.to_bytes() for name, model, _, _ in candidates}
        all_training = sum(row["training_work_proxy"] for row in ledger)
        all_evaluation = sum(row["evaluation_work_proxy"] for row in ledger)
        all_bytes = sum(row["cost"]["serialized_bytes"] for row in ledger)
        adaptive_upfront = self.storage_price * all_bytes + self.work_price * (all_training + all_evaluation)
        search_exceeded = (
            all_bytes > self.maximum_search_bytes or all_training + all_evaluation > self.maximum_search_work
        )
        for row in ledger:
            row["score"] = adaptive_upfront + self.expected_future_queries * row["per_query_objective"]
            if search_exceeded:
                row["eligible"] = False
                row["rejection_reasons"].append("whole-search-budget")
        eligible = [index for index, row in enumerate(ledger) if row["eligible"]]
        winner = min(eligible, key=lambda index: (ledger[index]["score"], ledger[index]["name"])) if eligible else None
        fixed = [index for index in eligible if ledger[index]["name"] in {"refit", "fixed_2", "fixed_4"}]
        baseline = (
            min(fixed, key=lambda index: (ledger[index]["own_projected_total"], ledger[index]["name"]))
            if fixed
            else None
        )
        comparison = None
        approved = False
        if winner is not None and baseline is not None:
            chosen, control = ledger[winner], ledger[baseline]
            advantage = control["per_query_objective"] - chosen["per_query_objective"]
            excess = adaptive_upfront - control["own_upfront_objective"]
            break_even = (
                max(0, math.ceil(excess / advantage))
                if advantage > 0
                else (0 if advantage == 0 and excess <= 0 else None)
            )
            net = control["own_projected_total"] - chosen["score"]
            approved = net > 0
            comparison = {
                "baseline": control["name"],
                "candidate": chosen["name"],
                "baseline_optimistic_single_fit_upfront": control["own_upfront_objective"],
                "adaptive_all_search_upfront": adaptive_upfront,
                "upfront_excess": excess,
                "per_query_advantage": advantage,
                "break_even_queries": break_even,
                "forecast_queries": self.expected_future_queries,
                "projected_net_benefit": net,
                "projected_benefit_positive": approved,
                "fixed_model_selection_cost_waived_for_optimistic_baseline": True,
                "evidence_population": "selection; final test has not been observed",
                "measured_full_cost_net_benefit_proved": False,
            }
        # Retain the strongest fixed structure when the complete adaptive search
        # cannot repay its upfront costs under the predeclared query forecast.
        selected = winner if approved or baseline is None else baseline
        selected_model = None if selected is None else candidates[selected][1]
        selected_name = None if selected is None else ledger[selected]["name"]
        if selected_model is not None:
            before = selected_model.cost()["loaded_parameter_bytes"]
            selected_model.sleep()
            dormant = selected_model.cost()
            dormant["released_parameter_array_bytes"] = before - dormant["loaded_parameter_bytes"]
            # Parameters remain durably available; the first subsequent read reloads.
        else:
            dormant = None
        exact = zlib.compress(canonical(records), level=9)
        report = {
            "schema": "hepta.memory.v6.structure-proposal.v1",
            "generation": generation,
            "parent_generation": None if parent is None else parent.generation,
            "selected": selected_name,
            "candidates": ledger,
            "candidate_objective_winner": None if winner is None else ledger[winner]["name"],
            "structural_adoption_approved": approved and selected_name in {"split", "merge"},
            "all_candidate_work_proxy": all_training,
            "all_candidate_evaluation_work_proxy": all_evaluation,
            "all_candidate_cpu_seconds": sum(row["candidate_cpu_seconds"] for row in ledger),
            "all_candidate_retained_bytes": all_bytes,
            "forecast_cost_comparison": comparison,
            "frozen_cost_configuration": {
                "storage_price": self.storage_price,
                "training_work_price": self.work_price,
                "inference_work_price": self.inference_work_price,
                "expected_future_queries": self.expected_future_queries,
                "maximum_search_bytes": self.maximum_search_bytes,
                "maximum_search_work": self.maximum_search_work,
                "objective_units": "one wrong future read costs 1; bytes/work use the disclosed scenario coefficients",
                "search_budget_gate": "measured whole-search admission; does not stop an already running candidate fit",
            },
            "evaluation_split": {
                "selection_keys": list(selection_keys),
                "retention_keys": retention_keys,
                "disjoint": True,
                "retention_from_parent_support": parent is not None,
                "retention_assessed": bool(retention_keys),
            },
            "fixed_total_hidden_width_budget": self.total_hidden,
            "equal_parameter_byte_ceiling": self.parameter_budget_bytes,
            "comparison_basis": "natural fixed hidden width"
            if self.parameter_budget_bytes is None
            else "same parameter-byte ceiling; integer-width slack disclosed",
            "equal_parameter_counts_claimed": False,
            "equal_serialized_byte_ceiling": self.maximum_bytes,
            "strong_exact_key_value_codec_bytes": len(exact),
            "exact_codec_includes_source_lineage": True,
            "dormant_selected": dormant,
            "test_used_for_selection": False,
            "live_topology_mutated": False,
            "work_proxy_is_hardware_flops": False,
            "work_proxy_excludes": "hashing, Python, optimizer constants, serialization and hardware effects; wall/CPU reported separately",
        }
        return selected_model, report
