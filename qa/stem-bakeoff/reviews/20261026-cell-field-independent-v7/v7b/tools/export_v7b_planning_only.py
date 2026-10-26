"""Bind the byte-identical V7 empirical planning panels to the V7b protocol.

No labels are reconstructed or selected here. Inputs are the previously audited
planning-only packages, containing no future/old selection labels.
"""

import argparse
import json
from pathlib import Path
import shutil

import numpy as np

from v7_audit_records import canonical, file_hash, pair_hash, read, require


PROTOCOL = "e1827b6a0a4de9a083fca5c9401751b6063e63b447617a90719e64a089b4da7d"
ORIGINAL_INDEX_SHA = "d902e815601c963199ac9f8a3f6ca54864884d42a021b3466f573fdcab0d0b7d"


def load_planning(packages, version, task, grid):
    """Load only fitting and the eight reused empirical planning panels."""
    path, grid = Path(packages)/f"{version}-{task}", Path(grid)
    manifest = read(path/"manifest.json")
    require(manifest["protocol_sha256"] == PROTOCOL and manifest["selection_labels_included"] is False
        and manifest["version"] == version and manifest["task"] == task
        and file_hash(grid/"protocol.json") == PROTOCOL
        and file_hash(grid/"inputs"/f"{version}-{task}.json") == manifest["frozen_grid_input_provenance_sha256"],
        "planning-only inputs bound to the frozen V7b execution")
    for name, pin in manifest["files"].items():
        require((path/name).stat().st_size == pin["bytes"] and file_hash(path/name) == pin["sha256"], "planning package bytes")
    names = ["current_train"]+[f"{role}_panel_{index}" for role in ("current", "old") for index in range(4)]
    with np.load(path/"arrays.npz", allow_pickle=False) as data:
        require(set(data.files) == {name+suffix for name in names for suffix in ("_x", "_y")}, "no selection arrays permitted")
        pairs = {name: (data[name+"_x"], data[name+"_y"]) for name in names}
    indices = []
    for name, pair in pairs.items():
        rows = 256 if name == "current_train" else 96
        pin = manifest["contexts"][name]
        require(pair[0].shape == (rows, 8) and pair[1].shape == (rows,)
            and pair_hash(pair) == pin["dataset_sha256"] and pin["rows"] == rows, "exact registered planning context")
        indices.extend(pin["indices"])
    require(len(indices) == len(set(indices)) == 1024, "all fitting and planning rows disjoint")
    return {"split": {"current_train": pairs["current_train"]},
        "current_panels": [pairs[f"current_panel_{index}"] for index in range(4)],
        "old_panels": [pairs[f"old_panel_{index}"] for index in range(4)]}


def export(original_packages, original_grid, corrected_grid, audit_report, output):
    original_packages, original_grid, corrected_grid, audit_report, output = map(Path,
        (original_packages, original_grid, corrected_grid, audit_report, output))
    require(file_hash(original_packages/"index.json") == ORIGINAL_INDEX_SHA, "exact previously disclosed planning-only index")
    audit = read(audit_report)
    require(audit["status"] == "PASS" and audit["primary_records"] == 864 and audit["protocol_sha256"] == PROTOCOL
        and audit["development_seal_sha256"] == file_hash(corrected_grid/"development_seal.json"), "completed independent V7b audit required")
    old_index = read(original_packages/"index.json")
    output.mkdir(parents=True, exist_ok=False)
    index = {"schema": "hepta.cell-field-planning-only-export.v7b", "protocol_sha256": PROTOCOL,
        "executed_source_sha256": audit["executed_source_sha256"],
        "development_seal_sha256": audit["development_seal_sha256"],
        "independent_audit_sha256": file_hash(audit_report), "original_index_sha256": ORIGINAL_INDEX_SHA,
        "exporter_sha256": file_hash(__file__), "selection_labels_included": False,
        "model_execution": False, "planning_arrays_changed": False, "packages": []}
    for package in old_index["packages"]:
        prior = original_packages/Path(package["directory"]).name
        require(file_hash(prior/"manifest.json") == package["manifest_sha256"], "original source manifest")
        manifest = read(prior/"manifest.json")
        version, task = manifest["version"], manifest["task"]
        old_path = original_grid/"inputs"/f"{version}-{task}.json"
        new_path = corrected_grid/"inputs"/f"{version}-{task}.json"
        require(file_hash(old_path) == manifest["frozen_grid_input_provenance_sha256"], "original frozen input provenance")
        old, new = read(old_path), read(new_path)
        require({k: v for k, v in old.items() if k not in {"cpu_ns", "wall_ns"}}
            == {k: v for k, v in new.items() if k not in {"cpu_ns", "wall_ns"}}, "unchanged actual cohort, source and planning-panel identities")
        target = output/f"{version}-{task}"
        target.mkdir()
        for name, pin in manifest["files"].items():
            require(file_hash(prior/name) == pin["sha256"] and (prior/name).stat().st_size == pin["bytes"], "original exact planning bytes")
            shutil.copyfile(prior/name, target/name)
        manifest.update(schema=index["schema"], protocol_sha256=PROTOCOL,
            frozen_grid_input_provenance_sha256=file_hash(new_path),
            original_planning_manifest_sha256=package["manifest_sha256"],
            original_frozen_grid_input_provenance_sha256=file_hash(old_path),
            derivation="byte-identical original planning-only arrays; all non-timing frozen input provenance fields equal")
        (target/"manifest.json").write_bytes(canonical(manifest)+b"\n")
        load_planning(output, version, task, corrected_grid)
        index["packages"].append({"directory": str(target), "manifest_sha256": file_hash(target/"manifest.json"),
            "rows": package["rows"], "contexts": package["contexts"]})
    (output/"index.json").write_bytes(canonical(index)+b"\n")
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("original-packages", "original-grid", "corrected-grid", "audit-report", "output"):
        parser.add_argument("--"+name, required=True)
    result = export(**vars(parser.parse_args()))
    print(json.dumps({"packages": len(result["packages"]), "protocol_sha256": PROTOCOL,
        "selection_labels_included": False, "planning_arrays_changed": False}))
