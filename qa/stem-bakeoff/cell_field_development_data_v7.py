"""Pinned V5/V6 cohorts reused only for V7 development, never confirmation.

Former validation/final labels are reconstructed from their original public
archives. No encrypted label, evaluator key, new cohort, or model outcome is read.
Planning panels are empirical reused data, not independent certificates.
"""

from collections import Counter
import csv
import io
import json
from pathlib import Path
import tarfile
import time

import numpy as np

from cell_field_data_v5 import COUNTS, DATASETS, sha
from cell_field_features import file_hash
from cell_field_io_v4 import load_task


SCHEMA = "hepta.cell-field-development-data.v7"
PANEL_SALT = "cell-field-development-panels-v7-20261026"
PINS = {
    "v5": {
        "protocol": "654994abfb66e8872b0d6632b7d80d5058ad5af06adc2d2dea0de628395ba05e",
        "agnews": ("ed65fd1452fca1ae03cbda8590199f377086f4f5c9778e0ff8ddb62c65d68f15", "ade407ba9cc7c11070c857d831e3017d2928ebb0f786008f7b4992cfaef31d8f"),
        "dbpedia": ("6c7af7dd5700fe331bf8911a25db3c6350e70cfa191398430881e47822ecbf6e", "f9918fb5fd7d83756f8608a59fa80918deaf26d16b20e45b8ee23a1f2a0e67eb"),
    },
    "v6": {
        "protocol": "cdd777f64265acfd6b8e44960a4f3c3bfbd5d856f76bc7c9d9c696bf4e11f41f",
        "agnews": ("72967fffff545339281451a10067057b5fb6eb7c85baa9887ff31d4da8d65758", "6fc6926c2d19e68a88e3ced2f1dbbbcccf93eeca17230a07560a930c80ca1f19"),
        "dbpedia": ("023ea4fa6d034e44f3919e9de653c887bdfecc42ba53acf7f9b0aaf887d6daef", "9688fd4afcc2ea0432cd8337ad8db545e35998cc731c610963acd1a320d2fa54"),
    },
}


def reconstruct_labels(archive, task, sources):
    """Recover only requested historical labels, authenticating exact CSV rows."""
    archive, spec = Path(archive), DATASETS[task]
    if (archive.is_symlink() or archive.stat().st_size != spec["bytes"]
            or file_hash(archive) != spec["sha256"]):
        raise ValueError("original public source archive identity differs")
    wanted = {row["source_id"]: row for row in sources}
    if len(wanted) != len(sources):
        raise ValueError("duplicate requested historical source identity")
    result, observed = {}, Counter()
    with tarfile.open(archive, mode="r:gz") as bundle:
        for member in bundle:
            split = next((s for s in ("train", "test")
                if member.name == spec["prefix"]+"/"+s+".csv"), None)
            if split is None:
                continue
            if not member.isfile() or member.size > 256 << 20 or observed[split]:
                raise ValueError("changed or duplicate source CSV member")
            with bundle.extractfile(member) as stream:
                reader = csv.reader(io.TextIOWrapper(stream, encoding="utf-8", newline=""), strict=True)
                for number, values in enumerate(reader):
                    if len(values) != 3 or not 1 <= int(values[0]) <= spec["class_count"]:
                        raise ValueError("original source CSV schema changed")
                    observed[split] += 1
                    label = int(values[0])-1
                    if label >= 4:
                        continue
                    row_hash = sha(values)
                    source_id = task+":"+sha([split, number, row_hash])
                    if source_id not in wanted:
                        continue
                    row = wanted[source_id]
                    if (source_id in result or row["source_row_sha256"] != row_hash
                            or row["official_split"] != split):
                        raise ValueError("historical source row commitment differs")
                    result[source_id] = label
    if dict(observed) != {s: spec[s+"_rows"] for s in ("train", "test")} or set(result) != set(wanted):
        raise ValueError("historical source census or requested membership differs")
    return result


def planning_indices(sources, labels, *, version, task, domain):
    """Partition probe+former-validation components into four balanced panels."""
    if domain not in ("current", "old"):
        raise ValueError("planning domain must be current or old")
    roles = {domain+"_probe", domain+"_validation"}
    pool = [row for row in sources if row["role"] in roles]
    if (Counter(row["role"] for row in pool) != {domain+"_probe": 128, domain+"_validation": 256}
            or len({row["component_id"] for row in pool}) != 384
            or len({row["source_id"] for row in pool}) != 384
            or len({row["index"] for row in pool}) != 384
            or Counter(labels[row["source_id"]] for row in pool) != {c: 96 for c in range(4)}):
        raise ValueError("planning requires384 unique balanced historical probe/validation components")
    groups = []
    for label in range(4):
        rows = [row for row in pool if labels[row["source_id"]] == label]
        groups.append(sorted(rows, key=lambda r: sha([PANEL_SALT, version, task, domain, r["component_id"]])))
    panels = []
    for panel in range(4):
        rows = [row for group in groups for row in group[24*panel:24*(panel+1)]]
        rows.sort(key=lambda r: sha([PANEL_SALT, version, task, domain, panel, r["component_id"]]))
        panels.append(np.asarray([row["index"] for row in rows], dtype=np.int64))
    return panels


def load_development(version, task, data_root, feature_root, source_inputs):
    """Return frozen projected arrays,8 planning panels and DEV selection splits.

    ``split`` retains the original four train/probe roles, including current
    training256. ``current_panels`` and ``old_panels`` contain four ``(x,y)``
    pairs each. ``selection`` contains former future/old test ``(x,y)`` pairs.
    No returned split is eligible as new V7 confirmatory evidence.
    """
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    if version not in PINS or task not in DATASETS:
        raise ValueError("only the exact disclosed V5/V6 tasks may enter development")
    data, features = Path(data_root)/task, Path(feature_root)/task
    protocol = Path(__file__).with_name("cell_field_protocol_"+version+".json")
    expected = PINS[version]
    if (file_hash(protocol) != expected["protocol"]
            or file_hash(data/"data_receipt.json") != expected[task][0]
            or file_hash(features/"report.json") != expected[task][1]):
        raise ValueError("historical protocol/data/feature commitment differs")
    inputs = load_task(data, features, protocol, task)
    sources, projected = inputs["sources"], inputs["projected"]
    labels = reconstruct_labels(Path(source_inputs)/DATASETS[task]["file"], task, sources)
    roles, metadata = {}, {}
    for role in COUNTS:
        indices = np.asarray([r["index"] for r in sources if r["role"] == role], dtype=np.int64)
        y = np.asarray([labels[sources[i]["source_id"]] for i in indices], dtype=np.int64)
        if Counter(y.tolist()) != {c: COUNTS[role]//4 for c in range(4)}:
            raise ValueError("reconstructed historical role class balance differs")
        if role in inputs["split"] and not np.array_equal(y, inputs["split"][role][1]):
            raise ValueError("original training labels differ from source reconstruction")
        roles[role] = (projected[indices], y)
        metadata[role] = {"indices": indices.tolist(), "labels": y.tolist(),
            "source_ids": [sources[i]["source_id"] for i in indices],
            "component_ids": [sources[i]["component_id"] for i in indices]}
    panels, panel_metadata, pools = {}, {}, {}
    for domain in ("current", "old"):
        groups = planning_indices(sources, labels, version=version, task=task, domain=domain)
        panels[domain], panel_metadata[domain] = [], []
        for indices in groups:
            y = np.asarray([labels[sources[i]["source_id"]] for i in indices], dtype=np.int64)
            panels[domain].append((projected[indices], y))
            panel_metadata[domain].append({"indices": indices.tolist(), "labels": y.tolist(),
                "source_ids": [sources[i]["source_id"] for i in indices],
                "component_ids": [sources[i]["component_id"] for i in indices]})
        indices = np.sort(np.concatenate(groups))
        pools[domain] = (projected[indices], np.asarray([labels[sources[i]["source_id"]] for i in indices], dtype=np.int64))
    provenance = {"schema": SCHEMA, "version": version, "task": task,
        "use": "development_only_all_prior_validation_and_final_labels_disclosed",
        "confirmatory_eligible": False, "independent_online_certificate": False,
        "panel_salt": PANEL_SALT, "protocol_sha256": expected["protocol"],
        "source_archive_sha256": DATASETS[task]["sha256"], "input_hashes": inputs["input_hashes"],
        "feature_report_sha256": expected[task][1], "feature_archive_sha256": inputs["feature_report"]["feature_sha256"],
        "feature_tensor_sha256": inputs["feature_report"]["tensor_sha256"],
        "component_set_sha256": sha(sorted(row["component_id"] for row in sources)),
        "roles": {role: {"rows": len(item["indices"]), "identity_sha256": sha(item)} for role, item in metadata.items()},
        "panels": {domain: [{"rows": len(item["indices"]), "class_counts": dict(Counter(item["labels"])),
            "identity_sha256": sha(item), "indices": item["indices"]} for item in groups]
            for domain, groups in panel_metadata.items()},
        "label_source": "exact original pinned public CSV rows; no ciphertext/key read",
        "new_cohort_selected": False, "encoder_calls": 0,
        "cpu_ns": time.process_time_ns()-cpu, "wall_ns": time.perf_counter_ns()-began}
    return {**inputs, "version": version, "current_panels": panels["current"], "old_panels": panels["old"],
        "planning_pools": pools, "selection": {"future": roles["future_test"], "old": roles["old_test"]},
        "role_metadata": metadata, "panel_metadata": panel_metadata, "provenance": provenance}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("version", "task", "data-root", "feature-root", "source-inputs", "receipt"):
        parser.add_argument("--"+name, required=True)
    args = vars(parser.parse_args())
    receipt = Path(args.pop("receipt"))
    result = load_development(**args)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    with receipt.open("x") as stream:
        json.dump(result["provenance"], stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps({"schema": SCHEMA, "version": result["version"], "task": result["provenance"]["task"],
        "panel_sizes": [len(y) for _, y in result["current_panels"]+result["old_panels"]],
        "base_current_train": len(result["split"]["current_train"][1]), "confirmatory_eligible": False}))
