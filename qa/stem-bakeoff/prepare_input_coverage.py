"""Freeze new historical SWE-bench train source groups for input coverage.

Official test/dev records are used only for duplicate exclusion. Cohort selection
never depends on labels or tokenization, and evaluation labels are stored apart.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from prepare_repair_cohorts import normalized, patch_targets, task_definitions


TASKS = ("multiple_paths", "multiple_hunks", "at_least_twenty_changed_lines", "net_added_lines")
COUNTS = {"train": 512, "calibration": 128, "evaluation": 256}
REVISION = "e48e2bd1e9fecd5bbd641e9414ac59da9f2e69f6"


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def sha_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare(raw, output, protocol):
    import pyarrow.parquet as pq

    raw, output, protocol = Path(raw), Path(output), Path(protocol)
    if output.exists():
        raise ValueError("new frozen experiment directory required")
    definitions = [d for d in task_definitions() if d["task_id"] in TASKS]
    if set(d["task_id"] for d in definitions) != set(TASKS):
        raise ValueError("fixed task definitions unavailable")
    acquired, records, invalid = {}, [], []
    for split in ("train", "test", "dev"):
        source = raw / f"{split}-00000-of-00001.parquet"
        receipt = json.loads((raw / f"{split}.acquisition.json").read_text())
        if (receipt["revision"] != REVISION or receipt["split"] != split
                or receipt["sha256"] != sha_file(source)):
            raise ValueError("pinned upstream bytes differ from acquisition receipt")
        acquired[split] = receipt
        table = pq.read_table(source, columns=["instance_id", "repo", "base_commit",
                                              "problem_statement", "created_at", "patch"])
        for row in table.to_pylist():
            try:
                source_id, statement = row["instance_id"], row["problem_statement"]
                if not isinstance(source_id, str) or not source_id:
                    raise ValueError("empty source identity")
                if split != "train":
                    keys = [("source", source_id)]
                    if isinstance(statement, str) and statement.strip():
                        keys.append(("issue", sha(normalized(statement))))
                    else:
                        invalid.append({"source_id": source_id, "upstream_split": split,
                                        "reason": "empty old issue; source ID retained for exclusion"})
                    try:
                        _, _, patch_group = patch_targets(row["patch"], definitions)
                        keys.append(("patch", patch_group))
                    except ValueError as exc:
                        invalid.append({"source_id": source_id, "upstream_split": split,
                                        "reason": "patch exclusion unavailable; identity and issue retained: " + str(exc)})
                    records.append({"source_id": source_id, "upstream_split": split, "keys": keys})
                    continue
                if not isinstance(statement, str) or not statement.strip():
                    raise ValueError("empty training issue")
                created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
                if created.tzinfo is None:
                    raise ValueError("source creation time lacks timezone")
                created = created.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
                labels, measurements, patch_group = patch_targets(row["patch"], definitions)
                text = f"Repository: {row['repo']}\n\nIssue:\n{statement}"
                if len(text.encode()) > 1024 * 1024:
                    raise ValueError("source exceeds fixed one-MiB preparation bound")
                record = {"source_id": source_id, "source_version": "sha256:" + sha(canonical({
                    "dataset": "princeton-nlp/SWE-bench", "revision": REVISION,
                    "repo": row["repo"], "base_commit": row["base_commit"]})),
                    "created_at": created, "text": text, "upstream_split": split,
                    "labels": labels, "measurements": measurements,
                    "keys": (("source", source_id), ("issue", sha(normalized(statement))),
                             ("patch", patch_group))}
                records.append(record)
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                invalid.append({"source_id": row.get("instance_id"), "upstream_split": split,
                                "reason": str(exc)})
    parent = list(range(len(records)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    seen = {}
    for index, row in enumerate(records):
        for key in row["keys"]:
            if key in seen:
                parent[find(index)] = find(seen[key])
            seen[key] = index
    groups = {}
    for index, row in enumerate(records):
        groups.setdefault(find(index), []).append(row)
    excluded_old = [rows for rows in groups.values() if any(r["upstream_split"] != "train" for r in rows)]
    candidates = [r for rows in groups.values() if all(r["upstream_split"] == "train" for r in rows) for r in rows]
    candidates.sort(key=lambda r: (r["created_at"], r["source_id"]))
    boundaries = (int(len(candidates) * 0.6), int(len(candidates) * 0.8))
    for index, row in enumerate(candidates):
        row["split"] = "train" if index < boundaries[0] else "calibration" if index < boundaries[1] else "evaluation"
    chosen, boundary_crossing = [], []
    for rows in groups.values():
        if any(r["upstream_split"] != "train" for r in rows):
            continue
        if len(set(r["split"] for r in rows)) != 1:
            boundary_crossing.append([r["source_id"] for r in rows])
            continue
        row = min(rows, key=lambda r: (r["created_at"], r["source_id"]))
        row["group_id"] = sha(canonical(sorted(set(key for r in rows for key in r["keys"]))))
        chosen.append(row)
    selected = []
    for split, cap in COUNTS.items():
        rows = sorted((r for r in chosen if r["split"] == split),
                      key=lambda r: sha("coverage-20261024-v1:" + r["group_id"]))
        if len(rows) < cap:
            raise ValueError(f"insufficient new {split} groups: {len(rows)} < {cap}; no adaptive cap reduction")
        selected.extend(rows[:cap])
    public = [{key: row[key] for key in ("source_id", "source_version", "text", "group_id", "split", "created_at")}
              for row in selected]
    labels = {split: [{"source_id": r["source_id"], "labels": r["labels"]}
                     for r in selected if r["split"] == split] for split in COUNTS}
    availability = {}
    for task in TASKS:
        counts = [sum(r["labels"][task] == label for r in labels["train"]) for label in (0, 1)]
        availability[task] = {"training_class_counts": counts, "available": min(counts) >= 64,
                              "rule": "both classes need 64 training groups for fixed n=128 budget"}
    output.mkdir(parents=True, exist_ok=False)
    (output / "predictors.json").write_bytes(canonical(public) + b"\n")
    for split, rows in labels.items():
        (output / (split + "_labels.json")).write_bytes(canonical(rows) + b"\n")
    manifest = {"schema": "hepta.input-coverage-cohorts.v1", "authority": "DENY_ALL",
        "upstream": acquired, "protocol_sha256": sha_file(protocol),
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "selection": {"caps": COUNTS, "rank_salt": "coverage-20261024-v1:",
                      "label_dependent": False, "tokenization_dependent": False},
        "target_definitions": definitions, "task_availability": availability,
        "accounting": {"valid_records": len(records), "invalid": invalid,
                       "all_groups": len(groups), "old_exclusion_groups": len(excluded_old),
                       "excluded_train_records": sum(r["upstream_split"] == "train" for rows in excluded_old for r in rows),
                       "boundary_crossing_groups": boundary_crossing,
                       "selected_counts": {s: len(labels[s]) for s in labels}},
        "selected_sources": [{key: r[key] for key in ("source_id", "source_version", "group_id", "split", "created_at")}
                             for r in selected],
        "files": {p.name: sha_file(p) for p in sorted(output.iterdir()) if p.is_file()},
        "limitations": ["historical sources, not future qualification", "one structural repair-shape family",
                        "unknown semantic and foundation-pretraining overlap", "conservative generic-patch grouping"]}
    (output / "manifest.json").write_bytes(canonical(manifest) + b"\n")
    return {"manifest_sha256": sha_file(output / "manifest.json"),
            "selected_counts": manifest["accounting"]["selected_counts"],
            "task_availability": availability, "excluded_train_records": manifest["accounting"]["excluded_train_records"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--protocol", required=True)
    print(json.dumps(prepare(**vars(parser.parse_args())), sort_keys=True))
