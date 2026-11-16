"""Create-only B freezes, later C ablations, and honest E5 source availability."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from . import circuit_v2, composition_core
from .circuit_v2 import PathCircuit, evaluate, fit_arm
from .composition_core import ARMS, canonical, digest, require, sha


def write_new(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def source_digest():
    return digest(
        {
            Path(path).name: hashlib.sha256(Path(path).read_bytes()).hexdigest()
            for path in (__file__, circuit_v2.__file__, composition_core.__file__)
        }
    )


def check_isolation(panels):
    owners, observations = {}, {}
    for panel, rows in panels.items():
        for row in rows:
            for field in (
                "task_id",
                "source_id",
                "lineage_id",
                "family_id",
                "observation_digest",
            ):
                if row.get(field) is not None:
                    identity = (field, row[field])
                    require(
                        owners.setdefault(identity, panel) == panel,
                        "cross-panel " + field,
                    )
            identity = row["observation_digest"]
            payload = digest(
                {
                    key: row.get(key)
                    for key in ("features", "target", "source_id", "lineage_id")
                }
            )
            require(
                observations.setdefault(identity, payload) == payload,
                "same observation relabeled",
            )


def freeze_selection(a_rows, b_rows, plan, output_dir):
    """Finish all A training and B selection; this function cannot receive C."""
    require(
        sha(plan.get("feature_binding_digest")), "frozen input-feature binding required"
    )
    check_isolation({"A": a_rows, "B": b_rows})
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=False)
    write_new(destination / "PLAN.json", plan)
    inputs = {"A": a_rows, "B": b_rows}
    write_new(destination / "INPUTS_A_B.json", inputs)
    arms = {}
    source = source_digest()
    for arm in ARMS:
        model, training = fit_arm(a_rows, plan, arm)
        selection = evaluate(model, b_rows)
        directory = destination / arm
        directory.mkdir()
        files = {
            "MODEL.json": model.record(),
            "TRAINING.json": training,
            "B.json": selection,
        }
        for name, value in files.items():
            write_new(directory / name, value)
        arms[arm] = {
            "files": {name: digest(value) for name, value in files.items()},
            "b_accuracy": selection["classification_accuracy"],
            "b_cross_entropy": selection["mean_cross_entropy"],
            "frozen_path": list(model.path),
            "kernel_totals": training["kernel_totals"],
            "active_parameters_per_example": model.cost()[
                "active_parameters_per_example"
            ],
            "resident_parameters": model.cost()["resident_parameters"],
        }
    require(source_digest() == source, "source changed during training")
    kernels = {digest(arm["kernel_totals"]) for arm in arms.values()}
    active = {arm["active_parameters_per_example"] for arm in arms.values()}
    require(
        len(kernels) == len(active) == 1,
        "active parameters or executed model kernels differ",
    )
    selected = min(
        arms,
        key=lambda arm: (-arms[arm]["b_accuracy"], arms[arm]["b_cross_entropy"], arm),
    )
    frozen = {
        "schema": "hepta.path-study.freeze.v2",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_digest": source,
        "plan_digest": digest(plan),
        "inputs_digest": digest(inputs),
        "selected_arm": selected,
        "arms": arms,
        "selection_rule": "B classification accuracy, then B cross entropy, then arm name",
        "matched_active_parameters": True,
        "matched_model_kernel_operations": True,
        "matched_resident_parameters": len(
            {arm["resident_parameters"] for arm in arms.values()}
        )
        == 1,
        "matched_total_computation": False,
        "full_system_cost_known": False,
        "independent_scientific_qualification": "BLOCKED",
        "native_circuit": False,
        "scope": "two-hop input-feature classification diagnostic, not verified coding-agent task capability",
    }
    write_new(destination / "FROZEN_SELECTION.json", frozen)
    return {"frozen_digest": digest(frozen), "frozen": frozen}


def confirm_selection(c_rows, output_dir, expected_freeze_digest):
    """Load immutable B-selected checkpoints, then evaluate C and every ablation."""
    destination = Path(output_dir)
    frozen = json.loads((destination / "FROZEN_SELECTION.json").read_text())
    require(
        sha(expected_freeze_digest) and digest(frozen) == expected_freeze_digest,
        "B freeze differs",
    )
    require(source_digest() == frozen["source_digest"], "frozen source differs")
    plan = json.loads((destination / "PLAN.json").read_text())
    inputs = json.loads((destination / "INPUTS_A_B.json").read_text())
    require(
        digest(plan) == frozen["plan_digest"]
        and digest(inputs) == frozen["inputs_digest"],
        "frozen inputs differ",
    )
    check_isolation({**inputs, "C": c_rows})
    models = {}
    for arm, receipt in frozen["arms"].items():
        loaded = {}
        for name, binding in receipt["files"].items():
            value = json.loads((destination / arm / name).read_text())
            require(
                digest(value) == binding, "frozen artifact differs: " + arm + "/" + name
            )
            loaded[name] = value
        models[arm] = PathCircuit.restore(
            loaded["MODEL.json"], loaded["TRAINING.json"]["model_digest"]
        )
    # Even an interrupted confirmation is retained and cannot be silently retried.
    write_new(
        destination / "C_STARTED.json",
        {
            "frozen_digest": expected_freeze_digest,
            "input_digest": digest(c_rows),
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    write_new(destination / "INPUTS_C.json", c_rows)
    results = {}
    for arm, model in models.items():
        main = evaluate(model, c_rows)
        ablations = {"cells": {}, "edges": {}}
        for cell in range(model.pool):
            ablations["cells"][str(cell)] = evaluate(model, c_rows, drop_cell=cell)
        for edge in range(3):
            ablations["edges"][str(edge)] = evaluate(model, c_rows, drop_edge=edge)
        restored = PathCircuit.restore(model.record(), digest(model.record()))
        restored_predictions = evaluate(restored, c_rows)
        require(
            restored_predictions["rows"] == main["rows"],
            "checkpoint roundtrip changed predictions",
        )
        results[arm] = {
            "main": main,
            "ablations": ablations,
            "parameter_roundtrip_predictions_equal": True,
            "cold_process_recovery_tested": False,
        }
    report = {
        "schema": "hepta.path-study.confirmation.v2",
        "frozen_digest": expected_freeze_digest,
        "selected_arm": frozen["selected_arm"],
        "c_input_digest": digest(c_rows),
        "arms": results,
        "selection_changed_after_c": False,
        "independent_scientific_qualification": "BLOCKED",
        "total_c_panel_accesses": sum(2 + model.pool + 3 for model in models.values()),
        "unique_c_task_count": len({row["task_id"] for row in c_rows}),
        "native_circuit": False,
        "verified_task_success_rate": None,
    }
    require(
        source_digest() == frozen["source_digest"], "source changed during confirmation"
    )
    write_new(destination / "CONFIRMATION.json", report)
    return report


def experience_clusters(rows):
    """Join task, lineage and observation aliases; no statistical independence claim."""
    parents, seen = list(range(len(rows))), {}

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    for index, row in enumerate(rows):
        for field in ("task_id", "lineage_id", "observation_digest"):
            require(
                isinstance(row.get(field), str) and bool(row[field]),
                "missing experience identity",
            )
            previous = seen.setdefault((field, row[field]), index)
            left, right = root(previous), root(index)
            if left != right:
                parents[max(left, right)] = min(left, right)
    return len({root(index) for index in range(len(rows))})


def source_growth_plan(rows, *, unit_field="project_id", updates_per_source=224):
    """Conservative overlap groups, never equating rows/seeds/branches with users."""
    require(
        unit_field in ("project_id", "source_id"),
        "use declared project or provenance source units",
    )
    require(
        type(updates_per_source) is int and 1 <= updates_per_source <= 100000,
        "invalid source budget",
    )
    require(type(rows) is list and bool(rows), "nonempty source rows required")
    units = sorted({row[unit_field] for row in rows})
    require(
        all(isinstance(value, str) and value for value in units), "missing source units"
    )
    parents = {unit: unit for unit in units}

    def root(unit):
        while parents[unit] != unit:
            parents[unit] = parents[parents[unit]]
            unit = parents[unit]
        return unit

    seen = {}
    for row in rows:
        for field in ("task_id", "lineage_id", "observation_digest", "source_id"):
            require(
                isinstance(row.get(field), str) and bool(row[field]),
                "missing task provenance",
            )
            identity = (field, row[field])
            previous = seen.setdefault(identity, row[unit_field])
            a, b = root(previous), root(row[unit_field])
            if a != b:
                parents[max(a, b)] = min(a, b)
    groups = {}
    for unit in units:
        groups.setdefault(root(unit), []).append(unit)
    ordered = sorted(groups.values(), key=digest)
    settings = []
    for regime in ("fixed_total_compute", "fixed_per_source_compute"):
        for count in (1, 4, 16, 64):
            if count > len(ordered):
                settings.append(
                    {
                        "regime": regime,
                        "requested_groups": count,
                        "status": "BLOCKED",
                        "reason": "insufficient nonoverlapping declared source groups",
                        "available_groups": len(ordered),
                    }
                )
                continue
            selected = {unit for group in ordered[:count] for unit in group}
            indices = [
                index for index, row in enumerate(rows) if row[unit_field] in selected
            ]
            chosen = [rows[index] for index in indices]
            settings.append(
                {
                    "regime": regime,
                    "requested_groups": count,
                    "status": "READY_FOR_DIAGNOSTIC",
                    "selected_units": sorted(selected),
                    "row_indices": indices,
                    "updates": updates_per_source
                    * (count if regime == "fixed_per_source_compute" else 1),
                    "records_digest": digest(chosen),
                    "record_count": len(chosen),
                    "unique_tasks": len({row["task_id"] for row in chosen}),
                    "unique_lineages": len({row["lineage_id"] for row in chosen}),
                    "unique_observations": len(
                        {row["observation_digest"] for row in chosen}
                    ),
                    "provenance_disjoint_task_clusters": experience_clusters(chosen),
                    "statistical_effective_sample_size": None,
                }
            )
    return {
        "schema": "hepta.source-growth-plan.v2",
        "unit_field": unit_field,
        "source_groups": ordered,
        "available_groups": len(ordered),
        "settings": settings,
        "provenance_disjoint_task_clusters": experience_clusters(rows),
        "statistical_effective_sample_size": None,
        "verified_users": 0,
        "user_authentication_performed": False,
        "independent_scientific_qualification": "BLOCKED",
        "adoption_rate": None,
        "task_success_rate": None,
        "forgetting": None,
        "full_system_cost": None,
        "scope": "declared provenance overlap groups; no external source authentication or effective-sample-size estimate",
    }
