"""Prepare a fresh bounded final cohort and reserve all other source groups.

Only this source-preparation stage sees raw categories for balanced sampling.
It writes a withheld final payload without parsing that payload afterwards.
"""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from prepare_news_cohorts import (ARCHIVE_SHA256, COUNTS, _read_archive, canonical,
                                 normalized_title, publisher_is_ood, select_rows)

PINS = {"v1": "d3d8c203c2fd88966fa937d0e0b5cf2826399f558a26dc1e256e47ab479a0482",
        "v2": "e0e03839ba6cf957288023b04895eaceae5ac89a9b1ae161ff7518c22f9dd482",
        "v3": "56b0a717cd4afbd82e73a46064e2fe310a2a9c642433b6d9ff8108aa14fc1baa"}


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def write(path, value):
    payload = canonical(value) + b"\n"
    with Path(path).open("xb") as stream:
        stream.write(payload)
    return {"sha256": sha(payload), "bytes": len(payload)}


def run_new_stage(callback, arguments):
    root = Path(arguments["output"])
    existed = root.exists()
    try:
        return callback(**arguments)
    except Exception as error:
        if not existed and root.is_dir():
            write(root / "failure.json", {"stage": callback.__name__, "error_type": type(error).__name__,
                  "message": str(error), "at_utc": datetime.now(timezone.utc).isoformat(),
                  "final_payload_parsed": False, "partial_outputs_preserved": True, "authority": "DENY_ALL"})
        raise


def prepare(archive, previous_v1, previous_v2, previous_v3, protocol, output):
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    plan_bytes = Path(protocol).read_bytes()
    plan = json.loads(plan_bytes)
    prior = {}
    for name, source in zip(("v1", "v2", "v3"), (previous_v1, previous_v2, previous_v3)):
        payload = Path(source).read_bytes()
        if sha(payload) != PINS[name]:
            raise ValueError("old source census hash differs: " + name)
        for row in json.loads(payload)["rows"]:
            if row["raw_source_id"] in prior:
                raise ValueError("old experiments overlap")
            prior[row["raw_source_id"]] = row
    rows = _read_archive(archive)
    legacy = {row["source_id"] for group in select_rows(rows, COUNTS).values() for row in group}
    parent, seen, months = list(range(len(rows))), {}, []

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

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
    buckets, excluded, eligible = defaultdict(list), Counter(), []
    observed_prior = set()
    for members in groups.values():
        ids = sorted(rows[i]["source_id"] for i in members)
        component = "news-group:" + sha(ids)
        touched = set(ids).intersection(prior)
        observed_prior.update(touched)
        for identity in touched:
            old = prior[identity]
            if (old["component_id"] != component or old["component_member_count"] != len(ids)
                    or old["component_members_sha256"] != sha(ids)):
                raise ValueError("prior component differs from full source graph")
        labels, dates = {rows[i]["label"] for i in members}, {months[i] for i in members}
        reason = ("prior" if touched else "legacy" if legacy.intersection(ids)
                  else "cross_month" if len(dates) != 1 else "conflict" if len(labels) != 1 else None)
        if reason:
            excluded[reason] += 1
            continue
        candidates = [i for i in members if not publisher_is_ood(rows[i]["publisher"])]
        if not candidates:
            excluded["ood_publisher"] += 1
            continue
        representative = min(candidates, key=lambda i: (rows[i]["timestamp_ms"], rows[i]["source_id"]))
        month, label = next(iter(dates)), next(iter(labels))
        entry = (sha([plan["source_salt"], component]), component, representative, ids)
        buckets[(month, label)].append(entry)
        eligible.append(component)
    if observed_prior != set(prior):
        raise ValueError("old source census contains absent source rows")
    for entries in buckets.values():
        entries.sort()
    selected, offsets = [], Counter()
    for role in plan["new_source_plan"]:
        if role["rows"] % 4:
            raise ValueError("balanced four-class source plan required")
        chosen = []
        for label in range(4):
            key = (role["month"], label)
            start, stop = offsets[key], offsets[key] + role["rows"] // 4
            if stop > len(buckets[key]):
                raise ValueError("frozen source plan infeasible; no fallback sampling")
            chosen.extend((entry, label) for entry in buckets[key][start:stop])
            offsets[key] = stop
        for entry, label in sorted(chosen, key=lambda x: sha([plan["source_salt"], role["role"], x[0][1]])):
            selected.append((entry, label, role))
    predictors, sources, final = [], [], defaultdict(lambda: {"indices": [], "labels": [], "source_ids": []})
    for index, (entry, label, role) in enumerate(selected):
        _, component, representative, ids = entry
        row = rows[representative]
        identity = "uci-news:" + row["source_id"]
        predictors.append({"source_id": identity, "source_version": "sha256:" + row["source_row_sha256"], "text": row["text"]})
        sources.append({"index": index, "source_id": identity, "raw_source_id": row["source_id"],
                        "component_id": component, "role": role["role"], "month": role["month"],
                        "component_member_count": len(ids), "component_members_sha256": sha(ids),
                        "source_row_sha256": row["source_row_sha256"]})
        for key, value in (("indices", index), ("labels", label), ("source_ids", identity)):
            final[role["role"]][key].append(value)
    chosen_ids = {x["component_id"] for x in sources}
    if len(chosen_ids) != len(sources) or chosen_ids.intersection(x["component_id"] for x in prior.values()):
        raise ValueError("new holdout component overlap")
    reserved = sorted(set(eligible) - chosen_ids)
    payloads = {"predictors.json": {"rows": predictors}, "sources.json": {"rows": sources},
                "final_labels.json": {"classes": 4, "roles": dict(final)},
                "reserved_components.json": {"component_ids": reserved, "labels_or_titles_emitted": False}}
    files = {name: write(root / name, {"schema": "hepta.cell-closure-news.v4", **payload})
             for name, payload in payloads.items()}
    receipt = {"schema": "hepta.cell-closure-news.v4", "protocol_sha256": sha(plan_bytes),
               "source_archive_sha256": ARCHIVE_SHA256, "prior_source_hashes": PINS,
               "selected_components": len(selected), "reserved_components": len(reserved),
               "eligible_counts": {f"{month}/{label}": len(v) for (month, label), v in buckets.items()},
               "excluded_counts": dict(excluded), "source_roles": plan["new_source_plan"],
               "files": files, "prior_or_legacy_overlap": 0,
               "withheld_payload_parsed_after_write": False,
               "scope": "new historical source components, not pretraining-unseen or new independent fitted tasks",
               "wall_ns": time.perf_counter_ns() - began, "cpu_ns": time.process_time_ns() - cpu,
               "authority": "DENY_ALL", "production_authority": False}
    write(root / "data_receipt.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "previous-v1", "previous-v2", "previous-v3", "protocol", "output"):
        parser.add_argument("--" + name, required=True)
    print(json.dumps(run_new_stage(prepare, vars(parser.parse_args())), sort_keys=True))
