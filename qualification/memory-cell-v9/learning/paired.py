"""Matched metadata, zero-step and frozen-parent interventions.

The source owner export supplies all current facts. Future task requests never
enter this module. Catalog models retain explicit values; byte models do not.
Neither candidate construction nor training grants publication authority.
"""

from copy import deepcopy
import json
import time

import numpy as np

from training import AssociativeCell, KINDS, canonical, current_rows, sha
from native_export import export_cell


CONFIG = {"seed": 91317, "steps": 600, "dimension": 48, "hidden": 32,
          "threshold": 0.5}


def initialize(rows, kind, config, parent=None):
    """Rebase metadata, preserving every compatible inherited parameter bit."""
    cell = AssociativeCell()
    cell.kind, cell.dimension, cell.hidden = kind, config["dimension"], config["hidden"]
    cell.catalog = [json.loads(value) for value in sorted({canonical(row["record"]["value"]) for row in rows})]
    cell.supports = {sha(row["record"]["entity"].encode()): [row["source_id"]] for row in rows}
    cell.lineage_sources = sorted(row["source_id"] for row in rows)
    cell.threshold, cell.acceptance_enabled, cell.calibration = config["threshold"], True, None
    rng = np.random.default_rng(config["seed"])
    cell.A = rng.normal(0, 1, (cell.dimension, cell.hidden))
    cell.a = np.zeros(cell.hidden)
    cell.B = rng.normal(0, 0.03, (cell.hidden, len(cell.catalog)))
    cell.b = np.zeros(len(cell.catalog))
    mapping = []
    if parent is not None:
        if (parent.kind != kind or parent.dimension != cell.dimension or parent.hidden != cell.hidden
                or not set(parent.lineage_sources) <= set(cell.lineage_sources)):
            raise ValueError("parent dimensions or source ancestry require clean rebuild")
        cell.A[:] = parent.A
        cell.a[:] = parent.a
        for previous, value in enumerate(parent.catalog):
            if value not in cell.catalog:
                raise ValueError("removed or corrected value requires clean rebuild")
            current = cell.catalog.index(value)
            cell.B[:, current] = parent.B[:, previous]
            cell.b[current] = parent.b[previous]
            mapping.append([previous, current])
    cell.A, cell.a, cell.B, cell.b = [array.astype(np.float32) for array in (cell.A, cell.a, cell.B, cell.b)]
    cell.training_receipt = {
        "kind": "zero-gradient-matched-metadata-v9", "steps": 0, "seed": config["seed"],
        "parent_parameters": None if parent is None else parent.parameters_digest(),
        "catalog_index_mapping": mapping, "new_output_columns": len(cell.catalog) - len(mapping),
        "new_columns_policy": "same seeded initialization, no target-dependent parameter writes",
        "source_bound": True, "catalog_contains_explicit_values": True,
        "initial_parameters": cell.parameters_digest(), "wall_seconds": 0.0, "cpu_seconds": 0.0,
    }
    return cell


def artifact(cell):
    raw = cell.to_bytes()
    native = export_cell(raw)
    return {"original": raw.decode(), "native": native.decode()}, {
        "parameter_digest": cell.parameters_digest(), "native_digest": sha(native),
        "original_digest": sha(raw), "training": deepcopy(cell.training_receipt),
        "parameter_bytes": sum(array.nbytes for array in (cell.A, cell.a, cell.B, cell.b)),
        "catalog_bytes": len(canonical(cell.catalog)), "support_bytes": len(canonical(cell.supports)),
        "lineage_bytes": len(canonical(cell.lineage_sources)), "native_bytes": len(native),
    }


def prepare_parent(payload, kind):
    if payload is None:
        return None
    if not isinstance(payload, dict) or set(payload) != {"original", "native"}:
        raise ValueError("bounded exact original/native parent required")
    raw = payload["original"].encode()
    if export_cell(raw) != payload["native"].encode():
        raise ValueError("parent native and original disagree")
    parent = AssociativeCell.from_bytes(raw)
    if parent.kind != kind:
        raise ValueError("parent type mismatch")
    return parent


def paired_catalog(export, parents):
    rows = current_rows(export)
    if not isinstance(parents, dict) or set(parents) not in (set(), set(KINDS)):
        raise ValueError("both parent types or a clean fit required")
    started = time.perf_counter_ns()
    variants = {name: {} for name in ("zero", "frozen", "trained", "clean")}
    reports = {name: {} for name in variants}
    rebuilds = {}
    for kind in KINDS:
        selected = rows[kind]
        if not selected:
            raise ValueError("each memory type requires current facts")
        parent = prepare_parent(parents.get(kind), kind)
        zero = initialize(selected, kind, CONFIG)
        frozen = initialize(selected, kind, CONFIG, parent)
        fit_args = dict(kind=kind, support_ids=[[row["source_id"]] for row in selected],
                        hidden=CONFIG["hidden"], dimension=CONFIG["dimension"], steps=CONFIG["steps"])
        keys = [row["record"]["entity"] for row in selected]
        values = [row["record"]["value"] for row in selected]
        trained = AssociativeCell.fit(keys, values, CONFIG["seed"], parent=parent, **fit_args)
        clean = AssociativeCell.fit(keys, values, CONFIG["seed"], **fit_args)
        rebuilt = AssociativeCell.fit(keys, values, CONFIG["seed"], **fit_args)
        trained.threshold = clean.threshold = rebuilt.threshold = CONFIG["threshold"]
        if trained.training_receipt["initial_parameters"] != frozen.parameters_digest():
            raise ValueError("gradient candidate did not start from frozen intervention")
        if clean.parameters_digest() != rebuilt.parameters_digest():
            raise ValueError("clean rebuild parameter bits differ")
        reference = (zero.catalog, zero.supports, zero.lineage_sources, zero.threshold)
        for name, cell in (("zero", zero), ("frozen", frozen), ("trained", trained), ("clean", clean)):
            if (cell.catalog, cell.supports, cell.lineage_sources, cell.threshold) != reference:
                raise ValueError("interventions changed nonparameter read metadata")
            variants[name][kind], reports[name][kind] = artifact(cell)
        reports["clean"][kind]["rebuild_parameters_identical"] = True
        reports["clean"][kind]["rebuild_parameter_digest"] = rebuilt.parameters_digest()
        rebuilds[kind], _ = artifact(rebuilt)
    return {"schema": "hepta.memory.v9.paired-result.v1", "representation": "catalog",
        "scope": export["scope"], "owner_cut_digest": export["owner_cut_digest"],
        "configuration": CONFIG, "artifacts": variants, "rebuilds": rebuilds,
        "receipt": {"variants": reports, "actual_fit_calls": 6,
            "wall_ns": time.perf_counter_ns() - started,
            "catalog_contains_explicit_values": True, "future_requests_seen": False,
            "same_support_catalog_threshold": True, "parent_rebased_without_gradients": bool(parents),
            "compression_established": False, "authority": False}}
