"""Fresh source components and separated label roles for Cell action experiments.

Preparation sees raw source categories for balanced source-only selection. It
never reads previously evaluated labels or parses its new withheld payloads.
"""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time

from cell_field_retention_data import prior_sources as v1_sources
from prepare_news_cohorts import (
    ARCHIVE_SHA256, ARCHIVE_URL, COUNTS, _read_archive, _read_bounded,
    canonical, normalized_title, publisher_is_ood, select_rows,
)


SCHEMA = "hepta.cell-action-news.v3"
SALT = "hepta-cell-action-v3-20261024"
PRIOR_PINS = {
    "v1": {"sources_sha256": "d3d8c203c2fd88966fa937d0e0b5cf2826399f558a26dc1e256e47ab479a0482",
           "data_receipt_sha256": "57742ed6e70c5c33053e4092bc3f58d46f791e84ffedb2efe79fd187e2e707ea"},
    "v2": {"sources_sha256": "e0e03839ba6cf957288023b04895eaceae5ac89a9b1ae161ff7518c22f9dd482",
           "data_receipt_sha256": "41955087b6ac5cb3fb48ff15d4cb17014eb4a5965c1ba9c6324ce9a0dacc263f"},
}
V2_SOURCE_BYTES, V2_RECEIPT_BYTES = 296017, 4660
TRAIN_ROLES = frozenset(("old_train", "old_probe", "current_train", "current_probe"))
ACCESS_FILES = {"train": "train_labels.json", "validation": "validation_labels.json", "final": "final_labels.json"}


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def validate_roles(role_plan):
    if not isinstance(role_plan, list) or not 7 <= len(role_plan) <= 12:
        raise ValueError("seven to twelve explicit source roles required")
    names, by_access = set(), defaultdict(set)
    for row in role_plan:
        if (not isinstance(row, dict) or set(row) != {"role", "month", "rows", "access"}
                or not isinstance(row["role"], str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", row["role"])
                or row["role"] in names or row["access"] not in ACCESS_FILES
                or type(row["rows"]) is not int or not 4 <= row["rows"] <= 512 or row["rows"] % 4
                or not isinstance(row["month"], str) or not re.fullmatch(r"2014-0[3-8]", row["month"])):
            raise ValueError("invalid, duplicate, unbalanced or unbounded source role")
        names.add(row["role"])
        by_access[row["access"]].add(row["role"])
    if (by_access["train"] != TRAIN_ROLES or "old_validation" not in by_access["validation"]
            or "old_test" not in by_access["final"]
            or not any(role.startswith("future_") for role in by_access["final"])):
        raise ValueError("training, independent retention validation and final roles must remain separate")
    return role_plan


def previous_sources(previous_v1, previous_v2):
    first, first_provenance = v1_sources(previous_v1)
    root = Path(previous_v2)
    if any((root / name).is_symlink() for name in ("sources.json", "data_receipt.json")):
        raise ValueError("v2 source evidence must not be a symlink")
    source_bytes = _read_bounded(root / "sources.json", 2 << 20)
    receipt_bytes = _read_bounded(root / "data_receipt.json", 1 << 20)
    pins = PRIOR_PINS["v2"]
    if (sha(source_bytes) != pins["sources_sha256"] or len(source_bytes) != V2_SOURCE_BYTES
            or sha(receipt_bytes) != pins["data_receipt_sha256"] or len(receipt_bytes) != V2_RECEIPT_BYTES):
        raise ValueError("v2 sources or original receipt differ from the published experiment")
    receipt = json.loads(receipt_bytes)
    source_identity = {"sha256": pins["sources_sha256"], "bytes": V2_SOURCE_BYTES}
    if (receipt["files"]["sources.json"] != source_identity
            or receipt["source_archive_sha256"] != ARCHIVE_SHA256):
        raise ValueError("v2 receipt does not bind source identity and archive")
    second = json.loads(source_bytes)["rows"]
    if (len(second) != 480 or [row["index"] for row in second] != list(range(480))
            or len({row["raw_source_id"] for row in second}) != 480
            or len({row["component_id"] for row in second}) != 480
            or any(row["source_id"] != "uci-news:" + row["raw_source_id"] for row in second)):
        raise ValueError("v2 source census is incomplete or duplicated")
    return {"v1": first, "v2": second}, {"v1": first_provenance,
        "v2": {"mode": "original_receipt", "sources": source_identity,
               "original_receipt": {"sha256": pins["data_receipt_sha256"], "bytes": V2_RECEIPT_BYTES},
               "original_receipt_present": True}}


def build_cohorts(rows, legacy_cohorts, previous, *, role_plan):
    validate_roles(role_plan)
    if set(previous) != {"v1", "v2"} or not rows:
        raise ValueError("both prior experiment source censuses are required")
    raw_ids = {row["source_id"] for row in rows}
    prior = {name: {row["raw_source_id"]: row for row in source} for name, source in previous.items()}
    prior_rows = [row for source in previous.values() for row in source]
    legacy = {row["source_id"] for cohort in legacy_cohorts.values() for row in cohort}
    if (len(raw_ids) != len(rows)
            or len({row["raw_source_id"] for row in prior_rows}) != len(prior_rows)
            or len({row["component_id"] for row in prior_rows}) != len(prior_rows)):
        raise ValueError("duplicate raw source or prior component")
    if not legacy | {row["raw_source_id"] for row in prior_rows} <= raw_ids:
        raise ValueError("previous exposure references a source outside this archive")
    parent, seen, months = list(range(len(rows))), {}, []

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for index, row in enumerate(rows):
        months.append(datetime.fromtimestamp(row["timestamp_ms"] / 1000, timezone.utc).strftime("%Y-%m"))
        for key in (("story", row["source_group_id"]), ("title", normalized_title(row["text"]))):
            if key in seen:
                left, right = find(index), find(seen[key])
                parent[max(left, right)] = min(left, right)
            else:
                seen[key] = index
    groups = defaultdict(list)
    for index in range(len(rows)):
        groups[find(index)].append(index)
    buckets, excluded, exclusion_ids, support = defaultdict(list), Counter(), defaultdict(list), Counter()
    wanted_months = {row["month"] for row in role_plan}
    for members in groups.values():
        ids = sorted(rows[i]["source_id"] for i in members)
        component_id = "news-group:" + sha(ids)
        touched = {name: [mapping[source] for source in ids if source in mapping] for name, mapping in prior.items()}
        for previous_rows in touched.values():
            for source in previous_rows:
                if (source["component_id"] != component_id or source["component_member_count"] != len(ids)
                        or source["component_members_sha256"] != sha(ids)):
                    raise ValueError("prior component membership differs from the full source graph")
        causes = []
        labels, component_months = {rows[i]["label"] for i in members}, {months[i] for i in members}
        if len(component_months) != 1:
            causes.append("cross_month")
        if len(labels) != 1:
            causes.append("label_conflict")
        if legacy.intersection(ids):
            causes.append("legacy_cohort_component")
        causes.extend(name + "_experiment_component" for name, matches in touched.items() if matches)
        if causes:
            for cause in causes:
                excluded[cause] += 1
                exclusion_ids[cause].append(component_id)
            continue
        month, label = next(iter(component_months)), next(iter(labels))
        if month not in wanted_months:
            excluded["outside_selected_months"] += 1
            continue
        candidates = [i for i in members if not publisher_is_ood(rows[i]["publisher"])]
        if not candidates:
            excluded["no_non_ood_publisher"] += 1
            continue
        representative = min(candidates, key=lambda i: (rows[i]["timestamp_ms"], rows[i]["source_id"]))
        buckets[(month, label)].append((sha([SALT, component_id]), representative, component_id, ids))
        support[f"{month}/{label}"] += 1
    for candidates in buckets.values():
        candidates.sort(key=lambda row: row[0])
    selected, offsets = [], Counter()
    for role_row in role_plan:
        role, month, count = (role_row[key] for key in ("role", "month", "rows"))
        chosen = []
        for label in range(4):
            key = (month, label)
            begin, end = offsets[key], offsets[key] + count // 4
            if end > len(buckets[key]):
                raise ValueError(f"insufficient independent components for {role}, class {label}")
            chosen.extend((entry, label) for entry in buckets[key][begin:end])
            offsets[key] = end
        for entry, label in sorted(chosen, key=lambda value: sha([SALT, role, value[0][2]])):
            _, representative, component_id, members = entry
            selected.append({"row": rows[representative], "role": role, "month": month,
                             "access": role_row["access"], "label": label,
                             "component_id": component_id, "members": members})
    if len({row["component_id"] for row in selected}) != len(selected):
        raise ValueError("selected roles share a source component")
    audit = {"raw_rows": len(rows), "raw_components": len(groups),
        "legacy_selected_rows": len(legacy), "legacy_source_ids_sha256": sha(sorted(legacy)),
        "excluded_components_by_reason": dict(excluded), "exclusion_reason_counts_overlap": True,
        "exclusion_component_ids_sha256": {key: sha(sorted(value)) for key, value in exclusion_ids.items()},
        "eligible_components_by_month_class": dict(support), "selected_components": len(selected),
        "selected_legacy_overlap": 0, "selected_v1_overlap": 0, "selected_v2_overlap": 0,
        "graph_edges": ["equal raw story_id", "equal NFKC/casefold/whitespace-normalized raw title"],
        "semantic_story_overlap_excluded": False}
    for name, mapping in prior.items():
        audit[name + "_selected_rows"] = len(mapping)
        audit[name + "_source_ids_sha256"] = sha(sorted(mapping))
        audit[name + "_component_ids_sha256"] = sha(sorted(row["component_id"] for row in mapping.values()))
    return selected, audit


def prepare(archive, previous_v1, previous_v2, output, protocol):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    try:
        protocol_bytes = _read_bounded(protocol, 1 << 20)
        plan = json.loads(protocol_bytes)
        role_plan = validate_roles(plan["source_role_plan"])
        if (plan["source_counts"] != {row["role"]: row["rows"] for row in role_plan}
                or plan["source_split_salt"] != SALT or plan["source_archive_sha256"] != ARCHIVE_SHA256
                or plan["prior_experiments"] != PRIOR_PINS):
            raise ValueError("source plan or prior identity differs from the frozen protocol")
        previous, provenance = previous_sources(previous_v1, previous_v2)
        rows = _read_archive(archive)
        selected, audit = build_cohorts(rows, select_rows(rows, COUNTS), previous, role_plan=role_plan)
        predictors, sources = [], []
        roles = defaultdict(lambda: {"indices": [], "labels": [], "source_ids": []})
        for index, item in enumerate(selected):
            row, role = item["row"], item["role"]
            source_id = "uci-news:" + row["source_id"]
            predictors.append({"source_id": source_id, "source_version": "sha256:" + row["source_row_sha256"], "text": row["text"]})
            sources.append({"index": index, "source_id": source_id, "raw_source_id": row["source_id"],
                "component_id": item["component_id"], "month": item["month"], "role": role,
                "timestamp_ms": row["timestamp_ms"], "source_row_sha256": row["source_row_sha256"],
                "normalized_title_sha256": sha(normalized_title(row["text"]).encode()),
                "publisher_sha256": sha(normalized_title(row["publisher"]).encode()),
                "component_member_count": len(item["members"]), "component_members_sha256": sha(item["members"])})
            for key, value in (("indices", index), ("labels", item["label"]), ("source_ids", source_id)):
                roles[role][key].append(value)
        objects = {"predictors.json": {"schema": SCHEMA, "rows": predictors},
                   "sources.json": {"schema": SCHEMA, "rows": sources}}
        for access, filename in ACCESS_FILES.items():
            objects[filename] = {"schema": SCHEMA, "classes": 4,
                "roles": {row["role"]: roles[row["role"]] for row in role_plan if row["access"] == access}}
        files = {}
        for name, value in objects.items():
            payload = canonical(value) + b"\n"
            (root / name).write_bytes(payload)
            files[name] = {"sha256": sha(payload), "bytes": len(payload)}
        receipt = {"schema": SCHEMA, "salt": SALT, "source_url": ARCHIVE_URL,
            "source_archive_sha256": ARCHIVE_SHA256, "source_archive_bytes": Path(archive).stat().st_size,
            "protocol_sha256": sha(protocol_bytes), "prior_experiments": PRIOR_PINS,
            "previous_source_provenance": provenance,
            "attribution": "Gasparetti, F. (2017). News Aggregator. UCI. doi:10.24432/C5F61C",
            "license": "CC-BY-4.0", "classes": {"business": 0, "entertainment": 1, "health": 2, "science_technology": 3},
            "roles": {row["role"]: {"month": row["month"], "rows": row["rows"],
                "labels_per_class": row["rows"] // 4, "access": row["access"]} for row in role_plan},
            "audit": audit,
            "label_access": {"preparation": "source labels for conflict exclusion and balanced selection",
                "payload_roles": {access: [row["role"] for row in role_plan if row["access"] == access] for access in ACCESS_FILES},
                "validation_and_final_payloads_parsed_after_write": False, "future_labels_enter_encoder": False},
            "temporal_semantics": "2014 historical source-group holdouts; old_test and old_validation are same-month retention",
            "pretraining_exposure": "unknown; public titles may have appeared in foundation pretraining",
            "prior_exposure_exclusion_scope": "five exact legacy cohorts and all 512 v1 plus 480 v2 Cell components",
            "not_claimed": ["unseen source family", "prospective deployment", "independence from every past experiment"],
            "source_sha256": {name: sha(Path(__file__).with_name(name).read_bytes()) for name in
                ("cell_field_action_data.py", "cell_field_retention_data.py", "prepare_news_cohorts.py")},
            "files": files, "wall_ns": time.perf_counter_ns() - began, "cpu_ns": time.process_time_ns() - cpu,
            "authority": "DENY_ALL", "production_activation_allowed": False}
        (root / "data_receipt.json").write_bytes(canonical(receipt) + b"\n")
        return receipt
    except Exception as error:
        failure = {"schema": SCHEMA, "stage": "source_preparation", "error_type": type(error).__name__,
                   "message": str(error), "at_utc": datetime.now(timezone.utc).isoformat(),
                   "source_sha256": sha(Path(__file__).read_bytes()), "model_outputs_observed": False}
        (root / "preparation_failure.json").write_bytes(canonical(failure) + b"\n")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "previous_v1", "previous_v2", "output", "protocol"):
        parser.add_argument("--" + name.replace("_", "-"), required=True)
    result = prepare(**vars(parser.parse_args()))
    print(json.dumps({key: result[key] for key in ("roles", "audit")}, indent=2))
