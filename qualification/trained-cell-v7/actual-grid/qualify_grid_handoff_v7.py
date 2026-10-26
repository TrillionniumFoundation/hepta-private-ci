"""Unadmitted config00 diagnostic over the exact sealed V7 development census.

All96 registered cut points remain visible. A stopped controller is rejected;
missing states stay missing. Available actual states use the native codec and
serving implementation, then the existing pinned research checkpoint loader.
Only cached unlabelled Encoder vectors are read; no optimizer is advanced.
"""

import argparse
import itertools
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from handoff_v7 import canonical, checkpoint, encode, require, restore_native_dump, sha, verified_modules


PROTOCOL = "75def1fe5a2610f76f5fe02db082bb4f0d01d02f683da0ee500a9af1f7e5e0e6"
TASKS, MODES, SEEDS, STEPS = ("agnews", "dbpedia"), ("linear", "gated"), (7, 17, 29), (0, 16, 17, 32)
NORMALIZATION = b"hepta.neuron.float64-l2-times-sqrt-width8.floor1e-12.v5"


def floats(value):
    return np.asarray(value, dtype=">f8").tobytes()


def identifier(value):
    data = value.encode("ascii")
    require(0 < len(data) <= 128, "bounded cell identity required")
    return struct.pack(">H", len(data))+data


def source_features(workspace, version, contracts):
    from cell_field_features import load_features

    run = workspace/f"pft-run-{version}"
    seal_bytes = (run/"pre_evaluation_seal.json").read_bytes()
    seal = json.loads(seal_bytes)
    vectors, reports, projection, origins = {}, {}, None, []
    for task in TASKS:
        contract = contracts[f"{version}-{task}-seed7-linear"]
        protocol = contract["optimizer_origin_protocol_sha256"]
        path = workspace/f"pft-features-{version}"/task
        vectors[task], reports[task] = load_features(path, protocol)
        require(reports[task]["plan"]["labels_enter_encoder"] is False
                and reports[task]["encoder_updates"] == 0, "unlabelled frozen features required")
        projected = run/task/"projected.npz"
        require(sha(projected.read_bytes()) == seal["files"][f"{task}/projected.npz"]["sha256"]
                and seal["protocol_sha256"] == protocol, "original sealed projection changed")
        with np.load(projected, allow_pickle=False) as archive:
            matrix = archive["projection"]
        require(matrix.shape == (384, 8) and matrix.dtype == np.float64
                and np.isfinite(matrix).all() and np.max(np.abs(matrix)) <= 1, "projection differs")
        if projection is None:
            projection = matrix
        else:
            require(np.array_equal(projection, matrix), "cross-task projection differs")
        origins.append({"task": task, "origin_protocol_sha256": protocol,
            "feature_report_sha256": sha((path/"report.json").read_bytes()),
            "feature_archive_sha256": reports[task]["feature_sha256"],
            "projection_archive_sha256": sha(projected.read_bytes()), "origin_seal_sha256": sha(seal_bytes)})
    require(reports[TASKS[0]]["encoder_identity"] == reports[TASKS[1]]["encoder_identity"],
            "shared frozen encoder identity differs")
    return vectors, reports, projection, origins


def serving(rows, artifact, generation, reports, projection):
    encoder = sha(canonical(reports[TASKS[0]]["encoder_identity"]))
    wire = bytearray(b"HPTACV05"+identifier(artifact)+struct.pack(">Q", generation)
        +bytes.fromhex(encoder)+floats(projection)+struct.pack(">H", len(rows)))
    for _, state, item in rows:
        feature = state.bindings["feature_identity"]
        require(feature == reports[state.bindings["task"]]["feature_identity"], "state/feature pipeline differs")
        wire += identifier(item["cell_id"])+bytes.fromhex(state.digest())+bytes.fromhex(feature)
        wire += bytes([int(state.head.mode == "gated")])
        for name in (("W", "b") if state.head.mode == "linear" else ("W", "b", "a", "g")):
            wire += floats(state.head.params[name])
    return bytes(wire), {"generation": generation, "encoder_sha256": encoder,
        "projection_sha256": sha(b"hepta.neuron.float64-projection.v5"+floats(projection)),
        "normalization_sha256": sha(NORMALIZATION)}


def run(manifest, manifest_sha256, grid, code, workspace, native, output):
    manifest, grid, code, workspace, native, output = map(Path, (manifest, grid, code, workspace, native, output))
    original_manifest = manifest.read_bytes()
    require(sha(original_manifest) == manifest_sha256, "independent materialization manifest changed")
    plan = json.loads(original_manifest)
    require(plan["schema"] == "hepta.cell-field-native-development-inputs.v7"
        and plan["protocol_sha256"] == PROTOCOL and plan["fallback"] is True
        and plan["configuration_index"] == 0 and plan["selected_index"] is None
        and plan["scientific_acceptance"] is False and plan["primary_selection_changed"] is False
        and plan["optimization_calls"] == 0, "fixed unadmitted fallback scope differs")
    seal, selection = grid/"development_seal.json", grid/"selection.json"
    require(sha(seal.read_bytes()) == plan["grid_seal_sha256"]
        and sha(selection.read_bytes()) == plan["unchanged_selection_sha256"]
        and sha((grid/"protocol.json").read_bytes()) == PROTOCOL, "sealed grid identity changed")
    source = (grid/"executed_source.json").read_bytes()
    states, _, _ = verified_modules(code, {}, source, plan["executed_source_sha256"])
    expected = set(itertools.product(("v5", "v6"), TASKS, MODES, SEEDS, STEPS))
    actual = [(r["version"], r["task"], r["head"], r["seed"], r["step"]) for r in plan["rows"]]
    require(len(actual) == 96 and len(set(actual)) == 96 and set(actual) == expected,
            "full fixed96 checkpoint census required")
    output.mkdir(parents=True, exist_ok=False)
    grouped, census = {}, []
    for row in plan["rows"]:
        result = {k: row.get(k) for k in ("version", "fit_id", "task", "head", "seed", "step", "available", "run_status")}
        if not row["available"]:
            result.update(status="missing", reason=row["reason"])
            census.append(result)
            continue
        directory = Path(row["directory"])
        require(directory.resolve().is_relative_to(manifest.parent.resolve()), "checkpoint escaped materialization root")
        metadata = json.loads((directory/"state/manifest.json").read_bytes())
        contract = plan["contracts"][row["fit_id"]]
        require(sha(canonical(contract)) == row["contract_sha256"], "external controller contract changed")
        state = states.CellTrainingState.load(directory/"state", metadata["bindings"],
            metadata["protocol"], metadata["contexts"], row["state_sha256"])
        source_controller = (directory/"controller.json").read_bytes()
        require(sha(source_controller) == row["controller_sha256"]
            and (state.bindings["task"], state.head.mode, state.bindings["seed"])
                == (row["task"], row["head"], row["seed"])
            and json.loads(source_controller)["run_status"] == row["run_status"], "materialized checkpoint identity differs")
        try:
            item = checkpoint(state, source_controller, contract, code, source)
        except ValueError as error:
            require(row["run_status"] == "stopped" and "stopped controller" in str(error),
                    "unexpected checkpoint restoration failure")
            result.update(status="stopped_rejected", reason=str(error), state_sha256=state.digest())
            census.append(result)
            continue
        require(row["run_status"] in ("active", "completed"), "unregistered resume status")
        grouped.setdefault((row["version"], row["step"]), []).append((row, state, item))
        result.update(status="ready", state_sha256=state.digest())
        census.append(result)
    bundles, origins = [], []
    census_by_checkpoint = {(row["fit_id"], row["step"]): row for row in census}
    for version in ("v5", "v6"):
        vectors, reports, projection, identity = source_features(workspace, version, plan["contracts"])
        origins.extend({"version": version, **item} for item in identity)
        origin = output/version
        origin.mkdir()
        raw, tasks = bytearray(), []
        for task in TASKS:
            tasks.append({"task": task, "rows": len(vectors[task]), "offset_bytes": len(raw)})
            raw += floats(vectors[task])
        (origin/"vectors.bin").write_bytes(raw)
        predecessor = None
        for step in STEPS:
            rows = sorted(grouped[(version, step)], key=lambda r: r[2]["cell_id"])
            group = origin/f"step{step}"
            group.mkdir()
            payload, binding = serving(rows, f"v7-dev-config00-{version}-step{step}", 1 if step == 0 else 2,
                reports, projection)
            wire = encode(payload, PROTOCOL, predecessor, [r[2] for r in rows])
            if step == 0:
                predecessor = sha(wire)
            (group/"handoff.bin").write_bytes(wire)
            references, cases = bytearray(), []
            for row, state, item in rows:
                projected = vectors[row["task"]].astype(np.float64) @ projection
                values = np.column_stack((state.head.predict_logits(projected), state.head.predict_proba(projected)))
                cases.append({"cell_id": item["cell_id"], "task": row["task"], "rows": len(values),
                    "offset_bytes": len(references)})
                references += floats(values)
            os.link(origin/"vectors.bin", group/"vectors.bin")
            (group/"expected.bin").write_bytes(references)
            parity = {"schema": "hepta.handoff-serving-diagnostic.v7", "authority": "DENY_ALL",
                "scientific_acceptance": False, "production_authority": False, "protocol_sha256": PROTOCOL,
                "handoff_sha256": sha(wire), "absolute_tolerance": 1e-12, "tasks": tasks,
                "vectors_sha256": sha(raw), "expected_sha256": sha(references),
                "versions": [{**binding, "name": f"{version}-step{step}", "payload_sha256": sha(payload), "cases": cases}]}
            (group/"manifest.json").write_bytes(canonical(parity)+b"\n")
            executed = subprocess.run([str(native), str(group/"handoff.bin"), sha(wire), PROTOCOL,
                str(group), str(group/"native.json")], capture_output=True, text=True)
            require(executed.returncode == 0, f"native diagnostic failed: {executed.stderr}")
            decoded = json.loads((group/"native.json").read_bytes())
            by_cell = {item["cell_id"]: item for item in decoded["checkpoints"]}
            for row, state, item in rows:
                record = by_cell[item["cell_id"]]
                restored, controller = restore_native_dump(record, code, source,
                    plan["contracts"][row["fit_id"]], group/"restored"/item["cell_id"])
                require(restored.digest() == row["state_sha256"]
                    and sha(canonical(controller)) == row["controller_sha256"]
                    and record["pending_actions"] == row["pending_actions"], "actual native restoration changed state/plan")
                census_by_checkpoint[row["fit_id"], row["step"]]["status"] = "restored"
            bundles.append({"version": version, "step": step, "heads": len(rows), "handoff_sha256": sha(wire),
                "native_receipt_sha256": sha((group/"native.json").read_bytes()),
                "serving_parity": decoded["serving_parity"], "states_restored_exactly": len(rows)})
    require(manifest.read_bytes() == original_manifest and sha(seal.read_bytes()) == plan["grid_seal_sha256"]
        and sha(selection.read_bytes()) == plan["unchanged_selection_sha256"], "immutable input changed during diagnostic")
    result = {"schema": "hepta.actual-native-handoff-diagnostic.v7", "scope": "fixed config00 engineering fallback; no scientific selection",
        "protocol_sha256": PROTOCOL, "input_manifest_sha256": manifest_sha256,
        "grid_seal_sha256": plan["grid_seal_sha256"], "controller_source_sha256": plan["executed_source_sha256"],
        "native_binary_sha256": sha(native.read_bytes()), "exporter_sha256": sha(Path(__file__).read_bytes()),
        "registered_checkpoints": 96, "census": census, "bundles": bundles, "feature_origins": origins,
        "restored_checkpoints": sum(b["heads"] for b in bundles),
        "stopped_rejections": sum(r["status"] == "stopped_rejected" for r in census),
        "missing_checkpoints": sum(r["status"] == "missing" for r in census),
        "optimization_calls": 0, "candidate_published": False, "scientific_acceptance": False,
        "production_authority": False, "source_grid_unchanged": True, "primary_selection_unchanged": True}
    (output/"qualification.json").write_bytes(canonical(result)+b"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "manifest-sha256", "grid", "code", "workspace", "native", "output"):
        parser.add_argument("--"+name, required=True)
    result = run(**vars(parser.parse_args()))
    print(json.dumps({k: result[k] for k in ("restored_checkpoints", "stopped_rejections", "missing_checkpoints",
        "optimization_calls", "candidate_published", "scientific_acceptance")}))
