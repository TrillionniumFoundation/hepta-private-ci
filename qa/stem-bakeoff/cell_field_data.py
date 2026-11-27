"""Frozen, source-grouped historical news cohorts for Cell field control.

All raw story/title links are closed before selection. Preparation uses source
labels for conflict exclusion and class balance; the controller receives only
training/probe labels. May/June are historical adaptation holdouts, not new
deployment traffic or proof of pretraining independence.
"""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from prepare_news_cohorts import (
    ARCHIVE_SHA256, ARCHIVE_URL, COUNTS, _read_archive, canonical,
    normalized_title, publisher_is_ood, select_rows,
)


SCHEMA = "hepta.cell-field-news.v1"
SALT = "hepta-cell-field-v1-20261024"
ROLE_PLAN = (
    ("old_train", "2014-03", 64),
    ("old_probe", "2014-03", 32),
    ("old_test", "2014-03", 64),
    ("current_train", "2014-04", 64),
    ("current_probe", "2014-04", 32),
    ("future_may", "2014-05", 128),
    ("future_june", "2014-06", 128),
)
TRAIN_ROLES = frozenset(("old_train", "old_probe", "current_train", "current_probe"))
FINAL_ROLES = frozenset(("old_test", "future_may", "future_june"))


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def build_cohorts(rows, old_cohorts, *, role_plan=ROLE_PLAN):
    """Deterministic full-corpus graph closure; models never influence selection."""
    if (not rows or set(r[0] for r in role_plan) != TRAIN_ROLES | FINAL_ROLES
            or len(role_plan) != 7
            or any(type(n) is not int or not 4 <= n <= 512 or n % 4 for _, _, n in role_plan)):
        raise ValueError("seven bounded, class-balanced roles required")
    if len({r["source_id"] for r in rows}) != len(rows):
        raise ValueError("raw source identifiers must be unique")
    parent = list(range(len(rows)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    seen = {}
    months = []
    for i, row in enumerate(rows):
        months.append(datetime.fromtimestamp(row["timestamp_ms"] / 1000, timezone.utc).strftime("%Y-%m"))
        for key in (("story", row["source_group_id"]), ("title", normalized_title(row["text"]))):
            if key in seen:
                left, right = find(i), find(seen[key])
                parent[max(left, right)] = min(left, right)
            else:
                seen[key] = i
    groups = defaultdict(list)
    for i in range(len(rows)):
        groups[find(i)].append(i)
    old_ids = {r["source_id"] for cohort in old_cohorts.values() for r in cohort}
    if not old_ids <= {r["source_id"] for r in rows}:
        raise ValueError("old exposure references a source outside this archive")
    buckets = defaultdict(list)
    excluded = Counter()
    exclusion_component_ids = defaultdict(list)
    selected_months = {month for _, month, _ in role_plan}
    eligible_count = Counter()
    for members in groups.values():
        ids = sorted(rows[i]["source_id"] for i in members)
        component_id = "news-group:" + sha(ids)
        reasons = []
        labels = {rows[i]["label"] for i in members}
        component_months = {months[i] for i in members}
        if len(component_months) != 1:
            reasons.append("cross_month")
        if len(labels) != 1:
            reasons.append("label_conflict")
        if old_ids.intersection(ids):
            reasons.append("previous_cohort_component")
        if reasons:
            for reason in reasons:
                excluded[reason] += 1
                exclusion_component_ids[reason].append(component_id)
            continue
        month, label = next(iter(component_months)), next(iter(labels))
        if month not in selected_months:
            excluded["outside_selected_months"] += 1
            continue
        candidates = [i for i in members if not publisher_is_ood(rows[i]["publisher"])]
        if not candidates:
            excluded["no_non_ood_publisher"] += 1
            continue
        representative = min(candidates, key=lambda i: (rows[i]["timestamp_ms"], rows[i]["source_id"]))
        buckets[(month, label)].append((sha([SALT, component_id]), representative,
                                       component_id, ids))
        eligible_count[f"{month}/{label}"] += 1
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
    audit = {
        "raw_rows": len(rows), "raw_components": len(groups),
        "previous_selected_rows": len(old_ids), "previous_source_ids_sha256": sha(sorted(old_ids)),
        "excluded_components_by_reason": dict(excluded),
        "exclusion_reason_counts_overlap": True,
        "exclusion_component_ids_sha256": {k: sha(sorted(v)) for k, v in exclusion_component_ids.items()},
        "eligible_components_by_month_class": dict(eligible_count),
        "selected_components": len(selected), "selected_previous_overlap": 0,
        "graph_edges": ["equal raw story_id", "equal NFKC/casefold/whitespace-normalized raw title"],
        "semantic_story_overlap_excluded": False,
    }
    return selected, audit


def prepare(archive, output):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    started, cpu_started = time.perf_counter_ns(), time.process_time_ns()
    rows = _read_archive(archive)
    previous = select_rows(rows, COUNTS)
    selected, audit = build_cohorts(rows, previous)
    predictors, sources, role_rows = [], [], defaultdict(lambda: {"indices": [], "labels": [], "source_ids": []})
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
        role_rows[role]["indices"].append(index)
        role_rows[role]["labels"].append(item["label"])
        role_rows[role]["source_ids"].append(source_id)
    objects = {
        "predictors.json": {"schema": SCHEMA, "rows": predictors},
        "sources.json": {"schema": SCHEMA, "rows": sources},
        "train_labels.json": {"schema": SCHEMA, "classes": 4,
                              "roles": {r: role_rows[r] for r, _, _ in ROLE_PLAN if r in TRAIN_ROLES}},
        "final_labels.json": {"schema": SCHEMA, "classes": 4,
                              "roles": {r: role_rows[r] for r, _, _ in ROLE_PLAN if r in FINAL_ROLES}},
    }
    for filename, obj in objects.items():
        (root / filename).write_bytes(canonical(obj) + b"\n")
    receipt = {
        "schema": SCHEMA, "salt": SALT, "source_url": ARCHIVE_URL,
        "source_archive_sha256": ARCHIVE_SHA256,
        "source_archive_bytes": Path(archive).stat().st_size,
        "attribution": "Gasparetti, F. (2017). News Aggregator. UCI. doi:10.24432/C5F61C",
        "license": "CC-BY-4.0", "classes": {"business": 0, "entertainment": 1, "health": 2, "science_technology": 3},
        "roles": {role: {"month": month, "rows": count, "labels_per_class": count // 4}
                  for role, month, count in ROLE_PLAN},
        "pre_execution_feasibility_amendment": {
            "initial_requested_counts": {"old_train": 128, "old_probe": 64, "old_test": 128,
                                         "current_train": 128, "current_probe": 64,
                                         "future_may": 128, "future_june": 128},
            "initial_failure": "March health has 77 eligible components; 80 requested across old roles",
            "change": "halve March and April training/probe/retention counts; keep May/June at 128",
            "selection_constraints_relaxed": False,
            "cohort_model_outputs_observed_before_revision": False,
            "first_attempt_preparation_sha256": "ab1ae85e2ef0c5ca37debda232f4da01af621474c73480f67920ca2e6f24fd63",
        },
        "audit": audit,
        "label_access": {"preparation": "all source labels for conflict exclusion and balanced selection",
                         "training_and_control": sorted(TRAIN_ROLES), "final_scoring_only": sorted(FINAL_ROLES),
                         "future_labels_enter_encoder": False},
        "temporal_semantics": "2014 historical source-group holdouts; old_test is same-month retention",
        "pretraining_exposure": "unknown; public titles may have appeared in foundation pretraining",
        "prior_exposure_exclusion_scope": "the five exact legacy prepare_news_cohorts.py default cohorts only",
        "not_claimed": ["unseen source family", "prospective deployment", "independence from every past experiment"],
        "source_sha256": {name: sha(Path(__file__).with_name(name).read_bytes())
                          for name in ("cell_field_data.py", "prepare_news_cohorts.py")},
        "files": {name: {"sha256": sha((root / name).read_bytes()), "bytes": (root / name).stat().st_size}
                  for name in objects},
        "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu_started,
        "authority": "DENY_ALL", "production_activation_allowed": False,
    }
    (root / "data_receipt.json").write_bytes(canonical(receipt) + b"\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    receipt = prepare(args.archive, args.output)
    print(json.dumps({"roles": receipt["roles"], "audit": receipt["audit"]}, indent=2))


if __name__ == "__main__":
    main()
