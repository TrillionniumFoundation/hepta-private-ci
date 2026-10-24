"""Select an amended, predeclared source-disjoint retention cohort without models.

The amendment uses only measured source availability. Original infeasibility is
retained in a separate pinned report. Public source categories are permitted for
conflict exclusion/class balance. Training/probe and final labels are written
separately; no old label/outcome file is read and no model is invoked here.
"""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from cell_field_retention_sources import PINS, source_feasibility
from prepare_news_cohorts import ARCHIVE_SHA256, _read_archive, canonical, normalized_title, publisher_is_ood


SCHEMA = "hepta.cell-retention-news.v1"
COHORT_PROFILE = "hepta.cell-retention.source-selection.v1"
TRAIN_ROLES = frozenset(("old_train", "old_probe", "current_train", "current_probe"))
FINAL_ROLES = frozenset(("old_test", "future_june", "future_july"))
AMENDED_ROLES = (("old_train", "2014-04", 64), ("old_probe", "2014-04", 32),
                 ("old_test", "2014-04", 64), ("current_train", "2014-05", 64),
                 ("current_probe", "2014-05", 32), ("future_june", "2014-06", 96),
                 ("future_july", "2014-07", 128))


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def pinned_json(path, expected, maximum=4 * 1024**2):
    path = Path(path)
    if (any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file()
            or path.stat().st_size > maximum):
        raise ValueError("bounded regular pinned JSON input required")
    payload = path.read_bytes()
    if sha(payload) != expected:
        raise ValueError(f"immutable input checksum differs: {path.name}")
    return json.loads(payload)


def select_amended(rows, excluded_raw_source_ids, *, salt, role_plan=AMENDED_ROLES):
    """Deterministic role assignment after full raw-source connected closure."""
    if (tuple(tuple(v) for v in role_plan) != AMENDED_ROLES
            or salt != "cell-retention-v1-20261024"
            or not rows or len(rows) > 500_000
            or len({r["source_id"] for r in rows}) != len(rows)):
        raise ValueError("exact predeclared amendment, salt and bounded raw rows required")
    excluded = set(excluded_raw_source_ids)
    if not excluded or not excluded <= {r["source_id"] for r in rows}:
        raise ValueError("known exposure closure must identify actual raw source IDs")
    parents, seen, months = list(range(len(rows))), {}, []

    def find(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    for i, row in enumerate(rows):
        months.append(datetime.fromtimestamp(row["timestamp_ms"] / 1000, timezone.utc).strftime("%Y-%m"))
        for edge in (("story", row["source_group_id"]), ("title", normalized_title(row["text"]))):
            if edge in seen:
                a, b = find(i), find(seen[edge])
                parents[max(a, b)] = min(a, b)
            else:
                seen[edge] = i
    components = defaultdict(list)
    for i in range(len(rows)):
        components[find(i)].append(i)
    buckets = defaultdict(list)
    for members in components.values():
        ids = sorted(rows[i]["source_id"] for i in members)
        labels, component_months = {rows[i]["label"] for i in members}, {months[i] for i in members}
        if excluded.intersection(ids) or len(labels) != 1 or len(component_months) != 1:
            continue
        candidates = [i for i in members if not publisher_is_ood(rows[i]["publisher"])]
        if not candidates:
            continue
        representative = min(candidates, key=lambda i: (rows[i]["timestamp_ms"], rows[i]["source_id"]))
        component_id = "news-group:" + sha(ids)
        buckets[(next(iter(component_months)), next(iter(labels)))].append(
            (sha([salt, component_id]), component_id, representative, ids))
    for values in buckets.values():
        values.sort(key=lambda row: (row[0], row[1]))
    offsets, selected = Counter(), []
    for role, month, count in role_plan:
        chosen = []
        for label in range(4):
            key = (month, label)
            start, end = offsets[key], offsets[key] + count // 4
            if end > len(buckets[key]):
                raise ValueError(f"amended source count unavailable: {role} class {label}")
            chosen.extend((entry, label) for entry in buckets[key][start:end])
            offsets[key] = end
        chosen.sort(key=lambda pair: (sha([salt, role, pair[0][1]]), pair[0][1]))
        for (_, component_id, representative, ids), label in chosen:
            selected.append({"row": rows[representative], "role": role, "month": month,
                             "component_id": component_id, "members": ids, "label": label})
    if (len(selected) != 480 or len({r["component_id"] for r in selected}) != 480
            or any(excluded.intersection(r["members"]) for r in selected)):
        raise ValueError("selected roles overlap one another or pinned registered exposures")
    return selected


def prepare(archive, original_feasibility, protocol, output, *, expected_protocol_sha256):
    started, cpu_started = time.perf_counter_ns(), time.process_time_ns()
    plan = pinned_json(protocol, expected_protocol_sha256)
    if (plan.get("schema") != COHORT_PROFILE or plan.get("status") != "FROZEN_SOURCE_SELECTION"
            or plan.get("source_archive_sha256") != ARCHIVE_SHA256
            or plan.get("authority") != "DENY_ALL" or plan.get("model_execution_authorized") is not False
            or tuple(tuple(v) for v in plan.get("roles_in_order", [])) != AMENDED_ROLES):
        raise ValueError("exact reviewed source-only protocol required before selection")
    for name, expected in plan["source_code_sha256"].items():
        if name not in ("cell_field_retention_data.py", "cell_field_retention_sources.py", "prepare_news_cohorts.py"):
            raise ValueError("unexpected preparation source dependency")
        if sha(Path(__file__).with_name(name).read_bytes()) != expected:
            raise ValueError("source preparation implementation differs from freeze")
    if set(plan["source_code_sha256"]) != {
            "cell_field_retention_data.py", "cell_field_retention_sources.py", "prepare_news_cohorts.py"}:
        raise ValueError("all preparation source dependencies must be pinned")
    old = pinned_json(original_feasibility, plan["original_feasibility_sha256"])
    if (old["source_archive_sha256"] != ARCHIVE_SHA256 or old["model_outputs_observed"] is not False
            or old["selected_new_cohort"] is not False or not old["shortages"]
            or old["known_manifest_pins"] != PINS
            or set(old["source_exposure_inputs"]) != set(plan["registered_exposure_sets"])):
        raise ValueError("original failed count audit/exposure identity differs")
    rows = _read_archive(archive)
    audit = source_feasibility(rows, old["source_exposure_inputs"], role_plan=AMENDED_ROLES)
    if (audit["excluded_raw_source_ids_sha256"] != old["excluded_raw_source_ids_sha256"]
            or audit["excluded_raw_source_ids"] != old["excluded_raw_source_ids"]
            or not audit["source_count_feasible_under_supplied_exclusions"]):
        raise ValueError("registered exposure closure changed or amended counts unavailable")
    selected = select_amended(rows, audit["excluded_raw_source_ids"], salt=plan["selection_salt"])
    predictors, sources = [], []
    roles = defaultdict(lambda: {"indices": [], "labels": [], "source_ids": []})
    for index, item in enumerate(selected):
        row, role = item["row"], item["role"]
        source_id = "uci-news:" + row["source_id"]
        predictors.append({"source_id": source_id, "source_version": "sha256:" + row["source_row_sha256"],
                           "text": row["text"]})
        sources.append({"index": index, "source_id": source_id, "raw_source_id": row["source_id"],
            "component_id": item["component_id"], "month": item["month"], "role": role,
            "timestamp_ms": row["timestamp_ms"], "source_row_sha256": row["source_row_sha256"],
            "normalized_title_sha256": sha(normalized_title(row["text"]).encode()),
            "publisher_sha256": sha(normalized_title(row["publisher"]).encode()),
            "component_member_count": len(item["members"]),
            "component_members_sha256": sha(item["members"])})
        roles[role]["indices"].append(index)
        roles[role]["labels"].append(item["label"])
        roles[role]["source_ids"].append(source_id)
    objects = {"predictors.json": {"schema": SCHEMA, "rows": predictors},
               "sources.json": {"schema": SCHEMA, "rows": sources},
               "train_labels.json": {"schema": SCHEMA, "classes": 4,
                   "roles": {role: roles[role] for role, _, _ in AMENDED_ROLES if role in TRAIN_ROLES}},
               "final_labels.json": {"schema": SCHEMA, "classes": 4,
                   "roles": {role: roles[role] for role, _, _ in AMENDED_ROLES if role in FINAL_ROLES}}}
    root = Path(output)
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError("new output path may not contain symlinks")
    root.mkdir(parents=True, exist_ok=False)
    for name, value in objects.items():
        with (root / name).open("xb") as stream:
            stream.write(canonical(value) + b"\n")
    compact_audit = {key: value for key, value in audit.items()
                     if key not in ("excluded_raw_source_ids", "source_exposure_inputs")}
    receipt = {"schema": SCHEMA, "source_archive_sha256": ARCHIVE_SHA256,
        "cohort_protocol_sha256": expected_protocol_sha256,
        "original_feasibility_sha256": plan["original_feasibility_sha256"],
        "roles": {role: {"month": month, "rows": count, "labels_per_class": count // 4}
                  for role, month, count in AMENDED_ROLES},
        "selected_components": len(selected), "selected_registered_exposure_overlap": 0,
        "selected_raw_source_ids_sha256": sha(sorted(r["row"]["source_id"] for r in selected)),
        "selected_component_ids_sha256": sha(sorted(r["component_id"] for r in selected)),
        "registered_exposure_scope": plan["novelty_scope"], "feasibility": compact_audit,
        "source_code_sha256": plan["source_code_sha256"],
        "files": {name: {"sha256": sha((root / name).read_bytes()),
                          "bytes": (root / name).stat().st_size} for name in objects},
        "labels_accessed": "raw categories only for source filtering and balance; split final labels written separately",
        "models_or_predictions_accessed": False, "authority": "DENY_ALL",
        "production_activation_allowed": False, "pretraining_exposure": "unknown",
        "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu_started}
    with (root / "data_receipt.json").open("xb") as stream:
        stream.write(canonical(receipt) + b"\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "original-feasibility", "protocol", "output", "expected-protocol-sha256"):
        parser.add_argument("--" + name, required=True)
    result = prepare(**vars(parser.parse_args()))
    print(json.dumps({key: result[key] for key in
        ("roles", "selected_components", "selected_registered_exposure_overlap", "files", "wall_ns", "cpu_ns")}, indent=2))


if __name__ == "__main__":
    main()
