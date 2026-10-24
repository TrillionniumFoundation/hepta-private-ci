"""Fresh historical source components for the second Cell control experiment.

The full raw story/title graph is closed before selection. Every component
touching the five legacy cohorts or any v1 experiment source is excluded.
This preparation process sees source labels only for grouping and balance;
its final-label payload is written once and never parsed back here.
"""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from prepare_news_cohorts import (
    ARCHIVE_SHA256, ARCHIVE_URL, COUNTS, _read_archive, _read_bounded,
    canonical, normalized_title, publisher_is_ood, select_rows,
)


SCHEMA = "hepta.cell-retention-news.v2"
SALT = "hepta-cell-retention-v2-20261024"
PREVIOUS_RECEIPT_SHA256 = "57742ed6e70c5c33053e4092bc3f58d46f791e84ffedb2efe79fd187e2e707ea"
PREVIOUS_SOURCES_SHA256 = "d3d8c203c2fd88966fa937d0e0b5cf2826399f558a26dc1e256e47ab479a0482"
ROLE_PLAN = (
    ("old_train", "2014-03", 48),
    ("old_probe", "2014-03", 32),
    ("old_test", "2014-03", 48),
    ("current_train", "2014-04", 64),
    ("current_probe", "2014-04", 32),
    ("future_may", "2014-05", 128),
    ("future_june", "2014-06", 128),
)
TRAIN_ROLES = frozenset(("old_train", "old_probe", "current_train", "current_probe"))
FINAL_ROLES = frozenset(("old_test", "future_may", "future_june"))


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def prior_sources(directory):
    """Read the pinned v1 source census, without opening either label file."""
    root = Path(directory)
    receipt_bytes = _read_bounded(root / "data_receipt.json", 1 << 20)
    source_bytes = _read_bounded(root / "sources.json", 2 << 20)
    receipt = json.loads(receipt_bytes)
    source_identity = receipt["files"]["sources.json"]
    if (sha(receipt_bytes) != PREVIOUS_RECEIPT_SHA256
            or sha(source_bytes) != PREVIOUS_SOURCES_SHA256
            or source_identity != {"sha256": sha(source_bytes), "bytes": len(source_bytes)}
            or receipt["source_archive_sha256"] != ARCHIVE_SHA256):
        raise ValueError("v1 source census does not match the pinned experiment")
    sources = json.loads(source_bytes)["rows"]
    if (len(sources) != 512 or [s["index"] for s in sources] != list(range(512))
            or len({s["component_id"] for s in sources}) != 512
            or len({s["raw_source_id"] for s in sources}) != 512
            or any(s["source_id"] != "uci-news:" + s["raw_source_id"] for s in sources)):
        raise ValueError("v1 source census is incomplete or duplicated")
    return sources


def build_cohorts(rows, legacy_cohorts, previous_sources, *, role_plan=ROLE_PLAN):
    """Source-only union components, explicit v1 exclusion and fixed new ranking."""
    if (not rows or len(role_plan) != 7
            or set(r[0] for r in role_plan) != TRAIN_ROLES | FINAL_ROLES
            or any(type(n) is not int or not 4 <= n <= 512 or n % 4 for _, _, n in role_plan)):
        raise ValueError("seven bounded, class-balanced roles required")
    raw_ids = {r["source_id"] for r in rows}
    previous = {s["raw_source_id"]: s for s in previous_sources}
    legacy = {r["source_id"] for cohort in legacy_cohorts.values() for r in cohort}
    if (len(raw_ids) != len(rows) or len(previous) != len(previous_sources)
            or len({s["component_id"] for s in previous_sources}) != len(previous_sources)):
        raise ValueError("duplicate raw source or prior component")
    if not legacy | set(previous) <= raw_ids:
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
    buckets, excluded, exclusion_ids = defaultdict(list), Counter(), defaultdict(list)
    support = Counter()
    wanted_months = {month for _, month, _ in role_plan}
    for members in groups.values():
        ids = sorted(rows[i]["source_id"] for i in members)
        component_id = "news-group:" + sha(ids)
        prior = [previous[source] for source in ids if source in previous]
        for source in prior:
            if (source["component_id"] != component_id
                    or source["component_member_count"] != len(ids)
                    or source["component_members_sha256"] != sha(ids)):
                raise ValueError("v1 component membership differs from the full source graph")
        causes = []
        labels, component_months = {rows[i]["label"] for i in members}, {months[i] for i in members}
        if len(component_months) != 1:
            causes.append("cross_month")
        if len(labels) != 1:
            causes.append("label_conflict")
        if legacy.intersection(ids):
            causes.append("legacy_cohort_component")
        if prior:
            causes.append("v1_experiment_component")
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
    for values in buckets.values():
        values.sort(key=lambda value: value[0])
    selected, offsets = [], Counter()
    for role, month, count in role_plan:
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
                             "label": label, "component_id": component_id, "members": members})
    if len({s["component_id"] for s in selected}) != len(selected):
        raise ValueError("selected roles share a source component")
    return selected, {
        "raw_rows": len(rows), "raw_components": len(groups),
        "legacy_selected_rows": len(legacy), "legacy_source_ids_sha256": sha(sorted(legacy)),
        "v1_selected_rows": len(previous), "v1_source_ids_sha256": sha(sorted(previous)),
        "v1_component_ids_sha256": sha(sorted(s["component_id"] for s in previous_sources)),
        "excluded_components_by_reason": dict(excluded), "exclusion_reason_counts_overlap": True,
        "exclusion_component_ids_sha256": {k: sha(sorted(v)) for k, v in exclusion_ids.items()},
        "eligible_components_by_month_class": dict(support), "selected_components": len(selected),
        "selected_legacy_overlap": 0, "selected_v1_overlap": 0,
        "graph_edges": ["equal raw story_id", "equal NFKC/casefold/whitespace-normalized raw title"],
        "semantic_story_overlap_excluded": False,
    }


def prepare(archive, previous, output, protocol):
    """Write once; preserve a failed preparation rather than overwriting its trace."""
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    try:
        protocol_bytes = _read_bounded(protocol, 1 << 20)
        plan = json.loads(protocol_bytes)
        if (plan["source_counts"] != {role: count for role, _, count in ROLE_PLAN}
                or plan["source_split_salt"] != SALT
                or plan["source_archive_sha256"] != ARCHIVE_SHA256):
            raise ValueError("source counts, salt or archive differ from the frozen protocol")
        previous_rows = prior_sources(previous)
        rows = _read_archive(archive)
        selected, audit = build_cohorts(rows, select_rows(rows, COUNTS), previous_rows,
                                       role_plan=ROLE_PLAN)
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
                "component_member_count": len(item["members"]), "component_members_sha256": sha(item["members"])})
            roles[role]["indices"].append(index)
            roles[role]["labels"].append(item["label"])
            roles[role]["source_ids"].append(source_id)
        objects = {
            "predictors.json": {"schema": SCHEMA, "rows": predictors},
            "sources.json": {"schema": SCHEMA, "rows": sources},
            "train_labels.json": {"schema": SCHEMA, "classes": 4,
                "roles": {r: roles[r] for r, _, _ in ROLE_PLAN if r in TRAIN_ROLES}},
            "final_labels.json": {"schema": SCHEMA, "classes": 4,
                "roles": {r: roles[r] for r, _, _ in ROLE_PLAN if r in FINAL_ROLES}},
        }
        files = {}
        for name, obj in objects.items():
            payload = canonical(obj) + b"\n"
            (root / name).write_bytes(payload)
            files[name] = {"sha256": sha(payload), "bytes": len(payload)}
        receipt = {
            "schema": SCHEMA, "salt": SALT, "source_url": ARCHIVE_URL,
            "source_archive_sha256": ARCHIVE_SHA256, "source_archive_bytes": Path(archive).stat().st_size,
            "protocol_sha256": sha(protocol_bytes), "previous_data_receipt_sha256": PREVIOUS_RECEIPT_SHA256,
            "previous_sources_sha256": PREVIOUS_SOURCES_SHA256,
            "attribution": "Gasparetti, F. (2017). News Aggregator. UCI. doi:10.24432/C5F61C",
            "license": "CC-BY-4.0", "classes": {"business": 0, "entertainment": 1, "health": 2, "science_technology": 3},
            "roles": {role: {"month": month, "rows": count, "labels_per_class": count // 4}
                      for role, month, count in ROLE_PLAN},
            "audit": audit,
            "label_access": {"preparation": "source labels for conflict exclusion and balanced selection",
                "training_and_control": sorted(TRAIN_ROLES), "final_scoring_only": sorted(FINAL_ROLES),
                "future_labels_enter_encoder": False, "final_payload_parsed_after_write": False},
            "temporal_semantics": "2014 historical source-group holdouts; old_test is same-month retention",
            "pretraining_exposure": "unknown; public titles may have appeared in foundation pretraining",
            "prior_exposure_exclusion_scope": "five exact legacy cohorts and all 512 v1 Cell field components",
            "source_only_design": "480-row plan and new salt fixed after source feasibility, before model outcomes",
            "not_claimed": ["unseen source family", "prospective deployment", "independence from every past experiment"],
            "source_sha256": {name: sha(Path(__file__).with_name(name).read_bytes())
                              for name in ("cell_field_retention_data.py", "prepare_news_cohorts.py")},
            "files": files, "wall_ns": time.perf_counter_ns() - began, "cpu_ns": time.process_time_ns() - cpu,
            "authority": "DENY_ALL", "production_activation_allowed": False,
        }
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
    for name in ("archive", "previous", "output", "protocol"):
        parser.add_argument("--" + name, required=True)
    result = prepare(**vars(parser.parse_args()))
    print(json.dumps({"roles": result["roles"], "audit": result["audit"]}, indent=2))
