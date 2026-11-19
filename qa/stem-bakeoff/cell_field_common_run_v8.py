"""Frozen, planning-only runner for the unguarded common-terminal J32 diagnostic.

This entry point cannot execute a DRAFT protocol. It reads no selection arrays,
uses all 24 registered historical warmups, and preserves all six output slots.
Hashes bind supplied files; remote publication is checked by the invoking host.
"""

import argparse
from collections import Counter
import hashlib
from itertools import product
import json
import os
from pathlib import Path
import platform
import time

import numpy as np


SOURCE_REQUIRED = {"cell_field_common_run_v8.py", "cell_field_common_objective_v8.py",
    "cell_field_observable_v7.py", "cell_field_response_v7.py", "cell_field_response_v5.py",
    "cell_field_state.py", "cell_learning_models.py", "cell_learning_metrics.py"}
AXES = {"versions": ["v5", "v6"], "tasks": ["agnews", "dbpedia"],
        "head_modes": ["linear", "gated"], "seeds": [7, 17, 29]}
MECHANISM = {"horizon": 32, "dt": .02, "effort_price": .03, "action_bound": 4.,
    "current_mean_weight": 1., "old_mean_weight": .25, "current_dispersion_weight": 0.,
    "continuation": "zero_control", "safety_filter": False}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("ordinary input file required: " + str(path))
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 32 << 20,
            "bounded ordinary JSON input required")
    return json.loads(path.read_bytes())


def write(path, value):
    Path(path).write_bytes(canonical(value) + b"\n")


def verify_sources(code, sources, expected):
    require(isinstance(sources, dict) and SOURCE_REQUIRED <= set(sources)
            and sha(sources) == expected, "complete frozen source map required")
    for name, identity in sources.items():
        require(Path(name).name == name and file_hash(code / name) == identity,
                "changed executed source: " + name)


def frozen_plan(path, expected):
    from cell_field_common_objective_v8 import BRANCHES
    require(file_hash(path) == expected, "protocol byte identity differs")
    plan = read(path)
    require(plan["status"] == "FROZEN" and plan["schema"] == "hepta.common-terminal-diagnostic.v8"
            and all(plan[key] == value for key, value in AXES.items())
            and plan["mechanism"] == MECHANISM and plan["branches"] == list(BRANCHES)
            and plan["registered_fits"] == 24 and plan["registered_outputs"] == 144
            and plan["scientific_acceptance"] is False and plan["production_authority"] is False
            and plan["selection_labels_accessed"] is False and plan["new_sources_accessed"] is False,
            "fixed unguarded planning-only protocol must be remotely frozen before execution")
    return plan


def load_planning(root, grid, index, version, task, protocol_sha):
    from cell_field_state import dataset_digest
    directory = root / f"{version}-{task}"
    pins = [pin for pin in index["packages"] if Path(pin["directory"]).name == directory.name]
    require(len(pins) == 1 and file_hash(directory / "manifest.json") == pins[0]["manifest_sha256"],
            "unique pinned planning package required")
    manifest = read(directory / "manifest.json")
    provenance_path = grid / "inputs" / (directory.name + ".json")
    provenance = read(provenance_path)
    require(manifest["protocol_sha256"] == protocol_sha and manifest["version"] == version
            and manifest["task"] == task and manifest["selection_labels_included"] is False
            and manifest["source_text_included"] is False
            and manifest["frozen_grid_input_provenance_sha256"] == file_hash(provenance_path)
            and set(manifest["files"]) == {"arrays.npz", "sources.json"}, "planning provenance mismatch")
    for name, pin in manifest["files"].items():
        require(file_hash(directory / name) == pin["sha256"]
                and (directory / name).stat().st_size == pin["bytes"], "planning payload changed")
    rows = read(directory / "sources.json")["rows"]
    by_index = {row["index"]: row for row in rows}
    allowed = {"current_train", "current_probe", "current_validation", "old_probe", "old_validation"}
    require(len(rows) == len(by_index) == len({r["component_id"] for r in rows}) == 1024
            and all(r["role"] in allowed for r in rows), "disjoint planning-only source census required")
    names = ["current_train"] + [f"{role}_panel_{k}" for role in ("current", "old") for k in range(4)]
    require(set(manifest["contexts"]) == set(names), "exactly nine planning contexts required")
    pairs, used = {}, []
    with np.load(directory / "arrays.npz", allow_pickle=False) as arrays:
        require(set(arrays.files) == {name + "_" + suffix for name in names for suffix in ("x", "y")},
                "unexpected or selection arrays are forbidden")
        for name in names:
            x, y = arrays[name + "_x"], arrays[name + "_y"]
            context = manifest["contexts"][name]
            marks, count = context["indices"], 256 if name == "current_train" else 96
            require(x.shape == (count, 8) and y.shape == (count,) and len(marks) == count
                    and context["rows"] == count and np.isfinite(x).all()
                    and dataset_digest(x, y) == context["dataset_sha256"]
                    and Counter(y.tolist()) == {c: count // 4 for c in range(4)}, "planning context identity")
            identity = {"indices": marks, "labels": y.tolist(),
                "source_ids": [by_index[i]["source_id"] for i in marks],
                "component_ids": [by_index[i]["component_id"] for i in marks]}
            expected = (provenance["roles"][name] if name == "current_train" else
                        provenance["panels"][name.split("_")[0]][int(name[-1])])
            require(sha(identity) == expected["identity_sha256"], "planning row order/labels differ")
            pairs[name] = x.copy(), y.copy()
            used.extend(marks)
    require(len(set(used)) == len(used) == 1024, "planning contexts overlap")
    return pairs["current_train"], [pairs[name] for name in names[1:]], manifest


def load_warmup(workspace, base_plan, fit, version, train):
    from cell_field_state import CellTrainingState, dataset_digest
    pin = base_plan["historical_warmups"][fit]
    directory = workspace / f"pft-run-{version}" / pin["relative_directory"]
    require(set(pin["files"]) == {"manifest.json", "state.npz"}, "complete warmup checkpoint pin required")
    for name, identity in pin["files"].items():
        require(file_hash(directory / name) == identity["sha256"]
                and (directory / name).stat().st_size == identity["bytes"], "historical warmup changed")
    metadata = read(directory / "manifest.json")
    state = CellTrainingState.load(directory, metadata["bindings"], metadata["protocol"],
                                   metadata["contexts"], pin["state_sha256"])
    require(state.contexts.get(state.active_context) == dataset_digest(*train), "original warmup context mismatch")
    return state, pin


def execute_fit(directory, state, train, panels):
    """One complete six-branch diagnostic; no outcome chooses a replacement action."""
    from cell_field_common_objective_v8 import BRANCHES, WEIGHTS, build_long_reference, prepare_proposals, rollout32
    directory.mkdir(parents=True, exist_ok=False)
    state.save(directory / "initial")
    reference = build_long_reference(state, train, panels)
    prepared = prepare_proposals(reference)
    field = prepared["field"]
    np.savez_compressed(directory / "reference.npz", states=reference.states, observations=reference.observations,
        gradients=reference.gradients, nominal_actions=reference.nominal_actions,
        full_maps=prepared["maps"]["full"], field_maps=prepared["maps"]["field"], loss2_maps=prepared["maps"]["loss2"],
        field_initial=field.observations[0], field_inputs=np.vstack(field.inputs),
        field_input_offsets=np.r_[0, np.cumsum([len(x) for x in field.inputs])])
    write(directory / "preparation.json", prepared["record"])
    rows = []
    for branch in BRANCHES:
        target = directory / branch
        target.mkdir()
        proposal = prepared["plans"][branch]
        write(target / "proposal.json", proposal["record"])
        np.save(target / "proposed_actions.npy", proposal["actions"], allow_pickle=False)
        began, wall = time.process_time_ns(), time.perf_counter_ns()
        try:
            result = rollout32(state, train, panels, proposal["actions"], reference.observations[0, 4:])
            forecasts = {name: reference.observations[-1] + np.einsum("kqp,kp->q", matrix, result["actions"])
                         for name, matrix in prepared["maps"].items()}
            result["record"]["forecasts_on_actual_actions"] = {name: {
                "terminal_panels": predicted.tolist(),
                "terminal_panel_errors_actual_minus_tangent": (result["losses"][-1] - predicted).tolist(),
                "tangent_common_objective": float(WEIGHTS @ predicted + result["record"]["parameter_penalty"]),
                "objective_error_actual_minus_tangent": float(WEIGHTS @ (result["losses"][-1] - predicted))}
                for name, predicted in forecasts.items()}
            np.savez_compressed(target / "trajectory.npz", states=np.asarray([s.vector() for s in result["states"]]),
                                actions=result["actions"], losses=result["losses"])
            result["states"][-1].save(target / "terminal")
            row = result["record"]
        except Exception as error:
            row = {"status": "actual_error", "error": f"{type(error).__name__}: {error}",
                   "cpu_ns": time.process_time_ns() - began, "wall_ns": time.perf_counter_ns() - wall}
        row.update(branch=branch, scientific_acceptance=False, production_authority=False)
        write(target / "result.json", row)
        rows.append(row)
    return rows


def run(protocol, protocol_sha256, source_manifest, source_sha256, source_commit, workspace, grid, planning, output):
    import scipy
    from threadpoolctl import threadpool_info
    code = Path(__file__).resolve().parent
    protocol, source_manifest, workspace, grid, planning, output = map(lambda x: Path(x).resolve(),
        (protocol, source_manifest, workspace, grid, planning, output))
    plan, sources = frozen_plan(protocol, protocol_sha256), read(source_manifest)
    verify_sources(code, sources, source_sha256)
    require(len(source_commit) == 40 and all(c in "0123456789abcdef" for c in source_commit), "host-pinned source commit required")
    require(not output.exists() and all(p != output and p not in output.parents for p in
        (grid, planning, code, workspace / "pft-run-v5", workspace / "pft-run-v6")), "fresh separate diagnostic output required")
    runtime = {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__,
               "threadpools": threadpool_info(), "platform": platform.platform(),
               "threads": {name: os.environ.get(name) for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")}}
    require(runtime["threads"] == {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"}, "frozen single-thread runtime required")
    pins = plan["base_inputs"]
    for path, key in ((grid / "protocol.json", "protocol_sha256"), (grid / "development_seal.json", "seal_sha256"),
                      (planning / "index.json", "planning_index_sha256")):
        require(file_hash(path) == pins[key], "base input identity changed")
    seal, base, index = read(grid / "development_seal.json"), read(grid / "protocol.json"), read(planning / "index.json")
    require(seal["protocol_sha256"] == index["protocol_sha256"] == pins["protocol_sha256"]
            and index["development_seal_sha256"] == pins["seal_sha256"]
            and sha(read(grid / "executed_source.json")) == seal["executed_source_sha256"]
            == index["executed_source_sha256"] == pins["executed_source_sha256"]
            and len(index["packages"]) == 4, "base seal/planning/source identity mismatch")
    fits = [(version, task, head, seed, f"{version}-{task}-seed{seed}-{head}")
            for version, task, head, seed in product(*(AXES[k] for k in ("versions", "tasks", "head_modes", "seeds")))]
    require(set(base["historical_warmups"]) == {fit[-1] for fit in fits}, "complete historical warmup census required")
    inputs = {(v, t): load_planning(planning, grid, index, v, t, pins["protocol_sha256"])
              for v, t in product(AXES["versions"], AXES["tasks"])}
    warmups = {fit: load_warmup(workspace, base, fit, v, inputs[v, t][0]) for v, t, h, s, fit in fits}
    output.mkdir(parents=True, exist_ok=False)
    (output / "protocol.json").write_bytes(protocol.read_bytes())
    write(output / "executed_source.json", sources)
    started, wall, rows = time.process_time_ns(), time.perf_counter_ns(), []
    from cell_field_common_objective_v8 import BRANCHES
    for v, t, h, s, fit in fits:
        state, pin = warmups[fit]
        train, panels, manifest = inputs[v, t]
        began, began_wall = time.process_time_ns(), time.perf_counter_ns()
        try:
            results = execute_fit(output / fit, state, train, panels)
        except Exception as error:
            results = []
            for branch in BRANCHES:
                retained = output / fit / branch / "result.json"
                results.append(read(retained) if retained.is_file() else {"branch": branch, "status": "fit_error",
                    "error": f"{type(error).__name__}: {error}", "scientific_acceptance": False})
        metadata = {"fit": fit, "warmup": pin, "planning_manifest_canonical_sha256": sha(manifest),
            "cpu_ns": time.process_time_ns() - began, "wall_ns": time.perf_counter_ns() - began_wall, "branches": results}
        write(output / (fit + ".json"), metadata)
        rows.extend({"fit": fit, **result} for result in results)
    verify_sources(code, sources, source_sha256)
    require(file_hash(protocol) == protocol_sha256 and file_hash(grid / "protocol.json") == pins["protocol_sha256"]
            and file_hash(grid / "development_seal.json") == pins["seal_sha256"]
            and file_hash(planning / "index.json") == pins["planning_index_sha256"], "execution inputs changed during diagnostic")
    for v, t in product(AXES["versions"], AXES["tasks"]):
        load_planning(planning, grid, index, v, t, pins["protocol_sha256"])
    for v, t, h, s, fit in fits:
        load_warmup(workspace, base, fit, v, inputs[v, t][0])
    report = {"schema": "hepta.common-terminal-diagnostic-results.v8", "protocol_sha256": protocol_sha256,
        "source_sha256": source_sha256, "source_commit": source_commit, "runtime": runtime, "base_inputs": pins,
        "fits": len(fits), "output_slots": len(rows), "status_counts": dict(Counter(r["status"] for r in rows)),
        "cpu_ns": time.process_time_ns() - started, "wall_ns": time.perf_counter_ns() - wall,
        "rows": rows, "selection_labels_accessed": False, "new_sources_accessed": False,
        "scientific_acceptance": False, "production_authority": False,
        "scope": "all six fixed proposals; unguarded actual J32, forecasts and old-panel violations; no heldout or cost-gate conclusion"}
    write(output / "report.json", report)
    inventory = {p.relative_to(output).as_posix(): {"sha256": file_hash(p), "bytes": p.stat().st_size}
                 for p in sorted(output.rglob("*")) if p.is_file()}
    write(output / "diagnostic_seal.json", {"protocol_sha256": protocol_sha256, "source_sha256": source_sha256,
        "files": inventory, "scope": "local integrity commitment, not independent authentication or scientific approval"})
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("protocol", "protocol-sha256", "source-manifest", "source-sha256", "source-commit",
                     "workspace", "grid", "planning", "output"):
        parser.add_argument("--" + argument, required=True)
    result = run(**vars(parser.parse_args()))
    print(json.dumps({key: result[key] for key in ("fits", "output_slots", "status_counts")}, sort_keys=True))
