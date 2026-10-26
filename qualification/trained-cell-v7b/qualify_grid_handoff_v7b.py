"""Additive V7b profile for the unchanged native V7 handoff codec.

The original V7 entry point, protocol and evidence remain immutable. This entry
point pins the separate V7b manifest/protocol/source/seal and reuses the existing
serving conversion helpers. Scope is fixed config00 diagnostic only.
"""

import argparse
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np

PREVIOUS = Path(__file__).resolve().parents[1]/"trained-cell-v7"
sys.path.insert(0, str(PREVIOUS))
sys.path.insert(0, str(PREVIOUS/"actual-grid"))
from handoff_v7 import canonical, checkpoint, encode, require, restore_native_dump, sha, verified_modules
from qualify_grid_handoff_v7 import source_features, serving, floats, TASKS, MODES, SEEDS, STEPS

PROTOCOL = "e1827b6a0a4de9a083fca5c9401751b6063e63b447617a90719e64a089b4da7d"
INPUT_SHA = "11aeb65c298cebc58f8786e7362fb3fea69b8f79e7fce9edf66c5af47eb82495"
SOURCE_COMMIT = "147a67868afb68511a5152f7f944fb26df34843b"
SOURCE_SHA = "1a112e348eeaa06645896f1121c2ceab3f73e36caa967d1abda72bc462c7f110"
SEAL_SHA = "e3ad867157e293e0c80eee6a2985583688e851fee9ff98c68323f6fa83af6131"


def run(manifest, manifest_sha256, grid, code, workspace, native, output):
    manifest, grid, code, workspace, native, output = map(Path, (manifest, grid, code, workspace, native, output))
    original_manifest = manifest.read_bytes()
    require(manifest_sha256 == INPUT_SHA and sha(original_manifest) == INPUT_SHA,
            "independently pinned V7b materialization manifest changed")
    plan = json.loads(original_manifest)
    require(plan["schema"] == "hepta.cell-field-native-development-inputs.v7b"
        and plan["protocol_sha256"] == PROTOCOL and plan["fallback"] is True
        and plan["executed_source_commit"] == SOURCE_COMMIT
        and plan["executed_source_sha256"] == SOURCE_SHA and plan["grid_seal_sha256"] == SEAL_SHA
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
            payload, binding = serving(rows, f"v7b-dev-config00-{version}-step{step}", 1 if step == 0 else 2,
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
    result = {"schema": "hepta.actual-native-handoff-diagnostic.v7b", "scope": "fixed config00 engineering fallback; no scientific selection",
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
