"""Export the frozen empirical planning inputs without any selection labels."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np

from v7_audit_records import canonical, digest, file_hash, pair_hash, require


def export(workspace, grid, output):
    workspace, grid, output = map(Path, (workspace, grid, output))
    sys.path.insert(0, str(workspace/"hepta-repo/qa/stem-bakeoff"))
    from cell_field_development_data_v7 import load_development
    protocol_sha = "75def1fe5a2610f76f5fe02db082bb4f0d01d02f683da0ee500a9af1f7e5e0e6"
    require(file_hash(grid/"protocol.json") == protocol_sha, "frozen V7 input protocol")
    output.mkdir(parents=True, exist_ok=False)
    index = {"schema": "hepta.cell-field-planning-only-export.v7", "protocol_sha256": protocol_sha,
        "exporter_sha256": file_hash(__file__), "selection_labels_included": False, "model_execution": False, "packages": []}
    for version in ("v5", "v6"):
        for task in ("agnews", "dbpedia"):
            values = load_development(version, task, workspace/f"pft-data-{version}/cohorts",
                workspace/f"pft-features-{version}", workspace/"pft-data-v5/inputs")
            prior_path = grid/"inputs"/f"{version}-{task}.json"
            prior, observed = json.loads(prior_path.read_bytes()), json.loads(json.dumps(values["provenance"]))
            for key in ("schema", "version", "task", "panel_salt", "protocol_sha256", "source_archive_sha256",
                        "input_hashes", "feature_report_sha256", "feature_archive_sha256", "feature_tensor_sha256",
                        "component_set_sha256", "roles", "panels"):
                require(prior[key] == observed[key], "planning source identity changed: "+key)
            directory = output/f"{version}-{task}"
            directory.mkdir()
            arrays, contexts = {}, {}
            train = values["split"]["current_train"]
            metadata = values["role_metadata"]["current_train"]
            contexts["current_train"] = {"indices": metadata["indices"], "dataset_sha256": pair_hash(train), "rows": 256}
            arrays.update(current_train_x=train[0], current_train_y=train[1])
            for domain in ("current", "old"):
                for number, pair in enumerate(values[domain+"_panels"]):
                    name = f"{domain}_panel_{number}"
                    arrays[name+"_x"], arrays[name+"_y"] = pair
                    contexts[name] = {"indices": values["panel_metadata"][domain][number]["indices"],
                        "dataset_sha256": pair_hash(pair), "rows": 96}
            indices = {i for context in contexts.values() for i in context["indices"]}
            require(len(indices) == 1024, "exact disjoint fitting/planning source census")
            sources = [{key: row[key] for key in ("index", "source_id", "component_id", "role")}
                for row in values["sources"] if row["index"] in indices]
            require(all(row["role"] in {"current_train", "current_probe", "current_validation", "old_probe", "old_validation"}
                for row in sources), "selection role leaked into planning-only package")
            with (directory/"arrays.npz").open("wb") as stream:
                np.savez_compressed(stream, **arrays)
            (directory/"sources.json").write_bytes(canonical({"rows": sources})+b"\n")
            manifest = {"schema": index["schema"], "version": version, "task": task,
                "protocol_sha256": protocol_sha, "frozen_grid_input_provenance_sha256": file_hash(prior_path),
                "historical_protocol_sha256": prior["protocol_sha256"], "historical_input_hashes": prior["input_hashes"],
                "source_archive_sha256": prior["source_archive_sha256"], "feature_tensor_sha256": prior["feature_tensor_sha256"],
                "contexts": contexts, "files": {name: {"sha256": file_hash(directory/name), "bytes": (directory/name).stat().st_size}
                    for name in ("arrays.npz", "sources.json")},
                "selection_labels_included": False, "source_text_included": False,
                "allowed_role_scope": "original current_train plus probe/former-validation empirical planning panels only",
                "source_component_set_sha256": digest(sorted(row["component_id"] for row in sources)),
                "scientific_acceptance": False, "authority": "DENY_ALL"}
            (directory/"manifest.json").write_bytes(canonical(manifest)+b"\n")
            index["packages"].append({"directory": str(directory), "manifest_sha256": file_hash(directory/"manifest.json"),
                "rows": len(sources), "contexts": len(contexts)})
            print(json.dumps({"version": version, "task": task, "planning_contexts": 9, "unique_components": 1024}), flush=True)
    (output/"index.json").write_bytes(canonical(index)+b"\n")
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("workspace", "grid", "output"):
        parser.add_argument("--"+name, required=True)
    export(**vars(parser.parse_args()))
