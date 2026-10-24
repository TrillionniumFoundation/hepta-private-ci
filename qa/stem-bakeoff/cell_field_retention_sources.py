"""Source-only feasibility audit for a NEW retention cohort; no model or scoring.

Never opens historical final-label, prediction, score or checkpoint files. The
pinned public raw archive supplies source categories only for component conflict
exclusion and class-count feasibility. Output contains counts and source IDs,
not new selected test labels, model outputs or an executable training approval.
"""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import time

from prepare_news_cohorts import (ARCHIVE_SHA256, COUNTS, _read_archive, canonical,
                                  normalized_title, publisher_is_ood, select_rows)


ROLE_PLAN = (("old_train", "2014-04", 64), ("old_probe", "2014-04", 32),
             ("old_test", "2014-04", 64), ("current_train", "2014-05", 64),
             ("current_probe", "2014-05", 32), ("future_july", "2014-07", 128),
             ("future_august", "2014-08", 128))
PINS = {"sources.json": "d3d8c203c2fd88966fa937d0e0b5cf2826399f558a26dc1e256e47ab479a0482",
        "cohort_manifest.json.gz": "30cbc5492d4ed572c1caf58bcf4788ba20358884d863dce77f82fcefe780a523",
        "prepare_news_cohorts.py": "33fa46322d4e9ee341b1f5ea80f37b79713a7f9420f14df9204766f38b6b45b1"}
EVOLUTION_UNCOMPRESSED = "478e7afac704e934234024888f5f6d5025493a93a747182c39aac35e32d84b01"


def _sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def _load_pinned(directory, name):
    path = Path(directory) / name
    if (any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file()
            or path.stat().st_size > 1024**2):
        raise ValueError("bounded, regular source-only manifest required")
    payload = path.read_bytes()
    if _sha(payload) != PINS[name]:
        raise ValueError(f"exact source-only manifest pin differs: {name}")
    if name.endswith(".gz"):
        payload = gzip.decompress(payload)
        if _sha(payload) != EVOLUTION_UNCOMPRESSED:
            raise ValueError("evolution source manifest decompressed pin differs")
    return json.loads(payload)


def known_exposure(rows, pft_sources, evolution_manifest):
    """Minimal KNOWN exposure union, not an unsupported all-history assertion."""
    legacy = select_rows(rows, COUNTS)
    return {
        "legacy_default_768": {"source_ids": sorted(r["source_id"] for values in legacy.values() for r in values),
                               "story_ids": []},
        "evolution_v3_all_1104": {"source_ids": [], "story_ids": sorted(
            group for split in evolution_manifest["splits"].values() for group in split["source_groups"])},
        "pft_all_512": {"source_ids": sorted(r["raw_source_id"] for r in pft_sources["rows"]),
                        "story_ids": []},
    }


def source_feasibility(rows, exposures, *, role_plan=ROLE_PLAN):
    """Close ALL story/title edges before exclusion, regardless of selected role.

    An exposure by story ID excludes all title-linked components, including
    copies through unselected/otherwise invalid-month rows. Additional manifests
    can contribute raw source IDs, raw story IDs and/or normalized-title hashes.
    """
    if (not rows or len(rows) > 500_000 or not exposures or len(exposures) > 128
            or len({r["source_id"] for r in rows}) != len(rows)
            or any(type(count) is not int or not 4 <= count <= 512 or count % 4
                   for _, _, count in role_plan)
            or len({name for name, _, _ in role_plan}) != len(role_plan)):
        raise ValueError("bounded unique source rows, exposure sets and balanced roles required")
    all_ids = {row["source_id"] for row in rows}
    all_stories = {row["source_group_id"] for row in rows}
    parsed = {}
    for name, item in exposures.items():
        if set(item) - {"source_ids", "story_ids", "title_sha256"}:
            raise ValueError("exposure manifest has fields outside source-only schema")
        source_ids, story_ids = set(item.get("source_ids", [])), set(item.get("story_ids", []))
        title_hashes = set(item.get("title_sha256", []))
        if (not source_ids <= all_ids or not story_ids <= all_stories
                or not (source_ids or story_ids or title_hashes)
                or any(not isinstance(v, str) or len(v) != 64
                       or set(v) - set("0123456789abcdef") for v in title_hashes)):
            raise ValueError("exposure sources absent from the pinned raw universe")
        parsed[name] = (source_ids, story_ids, title_hashes)
    parent, seen, months = list(range(len(rows))), {}, []

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for i, row in enumerate(rows):
        months.append(datetime.fromtimestamp(row["timestamp_ms"] / 1000, timezone.utc).strftime("%Y-%m"))
        for edge in (("story", row["source_group_id"]), ("title", normalized_title(row["text"]))):
            if edge in seen:
                a, b = find(i), find(seen[edge])
                parent[max(a, b)] = min(a, b)
            else:
                seen[edge] = i
    grouped = defaultdict(list)
    for i in range(len(rows)):
        grouped[find(i)].append(i)
    by_origin, rejected, eligible = defaultdict(set), Counter(), Counter()
    closed_ids, title_hashes_seen = set(), set()
    for members in grouped.values():
        ids = {rows[i]["source_id"] for i in members}
        stories = {rows[i]["source_group_id"] for i in members}
        titles = {_sha(normalized_title(rows[i]["text"]).encode()) for i in members}
        title_hashes_seen.update(titles)
        component_id = "news-group:" + _sha(sorted(ids))
        origins = [name for name, (source_ids, story_ids, title_hashes) in parsed.items()
                   if ids & source_ids or stories & story_ids or titles & title_hashes]
        for name in origins:
            by_origin[name].add(component_id)
        reasons = []
        if origins:
            reasons.append("known_exposed_component")
            closed_ids.update(ids)
        labels, component_months = {rows[i]["label"] for i in members}, {months[i] for i in members}
        if len(labels) != 1:
            reasons.append("label_conflict")
        if len(component_months) != 1:
            reasons.append("cross_month")
        if not any(not publisher_is_ood(rows[i]["publisher"]) for i in members):
            reasons.append("no_non_ood_publisher")
        rejected.update(reasons)
        if not reasons:
            month, label = next(iter(component_months)), next(iter(labels))
            eligible[f"{month}/{label}"] += 1
    if any(not titles <= title_hashes_seen for _, _, titles in parsed.values()):
        raise ValueError("exposed normalized title hash absent from raw archive")
    needed = Counter()
    for _, month, count in role_plan:
        for label in range(4):
            needed[f"{month}/{label}"] += count // 4
    shortages = {key: {"required": count, "available": eligible[key], "shortfall": count - eligible[key]}
                 for key, count in needed.items() if count > eligible[key]}
    overlaps = {f"{a}|{b}": len(by_origin[a] & by_origin[b])
                for j, a in enumerate(parsed) for b in list(parsed)[j + 1:]}
    return {"schema": "hepta.cell-retention.source-feasibility.v1",
            "source_archive_sha256": ARCHIVE_SHA256, "raw_rows": len(rows),
            "raw_components": len(grouped), "role_plan": [list(v) for v in role_plan],
            "source_exposure_inputs": exposures,
            "exposure_components_by_origin": {name: len(by_origin[name]) for name in parsed},
            "exposure_component_pair_overlaps": overlaps,
            "excluded_raw_source_ids": sorted(closed_ids),
            "excluded_raw_source_ids_sha256": _sha(sorted(closed_ids)),
            "rejection_counts_nonexclusive": dict(rejected),
            "eligible_by_month_class_after_known_exposures": dict(sorted(eligible.items())),
            "required_by_month_class": dict(sorted(needed.items())), "shortages": shortages,
            "source_count_feasible_under_supplied_exclusions": not shortages,
            "source_inventory_completeness_verified": False,
            "unopened_final_labels": True, "model_outputs_observed": False,
            "labels_accessed": "public raw category only for conflict exclusion and class-count feasibility",
            "selected_new_cohort": False, "executable_preregistration": False,
            "unknown_pretraining_and_semantic_overlap_remain": True,
            "authority": "DENY_ALL"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--source-metadata", required=True)
    parser.add_argument("--additional-exposures", help="optional source-only JSON mapping; never labels/outcomes")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    started, cpu_started = time.perf_counter_ns(), time.process_time_ns()
    dependency = Path(__file__).with_name("prepare_news_cohorts.py")
    if _sha(dependency.read_bytes()) != PINS["prepare_news_cohorts.py"]:
        raise ValueError("pinned source reader implementation differs")
    pft = _load_pinned(args.source_metadata, "sources.json")
    evolution = _load_pinned(args.source_metadata, "cohort_manifest.json.gz")
    if (pft.get("schema") != "hepta.cell-field-news.v1" or len(pft["rows"]) != 512
            or evolution.get("source_archive_sha256") != ARCHIVE_SHA256
            or sum(v["rows"] for v in evolution["splits"].values()) != 1104):
        raise ValueError("known exposure manifests differ from reviewed scope")
    rows = _read_archive(args.archive)
    exposure = known_exposure(rows, pft, evolution)
    if args.additional_exposures:
        path = Path(args.additional_exposures)
        if (path.is_symlink() or not path.is_file() or path.stat().st_size > 1024**2):
            raise ValueError("bounded additional source-only manifest required")
        additional = json.loads(path.read_bytes())
        if set(additional) & set(exposure):
            raise ValueError("additional exposure cannot overwrite known exclusions")
        exposure.update(additional)
    report = source_feasibility(rows, exposure)
    report.update(code_sha256=_sha(Path(__file__).read_bytes()), known_manifest_pins=PINS,
                  wall_ns=time.perf_counter_ns() - started, cpu_ns=time.process_time_ns() - cpu_started)
    with Path(args.output).open("xb") as stream:
        stream.write(canonical(report) + b"\n")
    print(json.dumps({key: report[key] for key in
        ("raw_components", "exposure_components_by_origin", "exposure_component_pair_overlaps",
         "shortages", "source_count_feasible_under_supplied_exclusions", "wall_ns", "cpu_ns")}, indent=2))


if __name__ == "__main__":
    main()
