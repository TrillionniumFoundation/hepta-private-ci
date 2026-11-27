"""Prepare chronological, duplicate-grouped historical repair-shape tasks.

Targets are mechanical lexical properties of human patch changed lines. They are
not root-cause annotations, operation outcomes, or evidence of autonomous repair.
Only repository and issue statement construct predictor text. All task rules and
the first-32 eligible capacity policy are fixed before reading corpus outcomes.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import unicodedata


SCHEMA = "hepta.repair-shape-cohorts.v1"
PATTERNS = (
    ("conditional", r"\b(?:if|elif|else)\b"),
    ("return", r"\breturn\b"),
    ("call", r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\s*\("),
    ("assignment", r"(?<![=!<>:])=(?!=)"),
    ("comparison", r"==|!=|<=|>=|(?<![<])<(?![<=])|(?<![>])>(?![>=])|\b(?:is|in)\b"),
    ("loop", r"\b(?:for|while)\b"),
    ("import", r"\bimport\b"),
    ("raise", r"\braise\b"),
    ("string_literal", r"['\"]"),
    ("numeric_literal", r"(?<![\w])(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?(?!\w)"),
    ("collection_delimiter", r"[\[\]{}]"),
    ("boolean_operator", r"\b(?:and|or|not)\b"),
    ("attribute_access", r"\b[A-Za-z_]\w*\s*\.\s*[A-Za-z_]\w*"),
    ("function_definition", r"\b(?:async\s+)?def\s+[A-Za-z_]\w*\s*\("),
    ("subscript", r"(?:\w|[\])])\s*\["),
    ("context_manager", r"\bwith\b"),
    ("exception_handling", r"\b(?:try|except|finally)\b"),
    ("comment_marker", r"#"),
)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def task_definitions():
    definitions = []
    for category, pattern in PATTERNS:
        for direction in ("added", "removed", "either"):
            definitions.append({"task_id": f"{direction}_{category}", "family": "historical_repair_shape",
                "rule": "regex_search_in_any_selected_changed_line", "direction": direction,
                "regex": pattern, "flags": [], "positive_label": 1, "negative_label": 0})
    for name, measurement, comparison, threshold in (
        ("multiple_paths", "paths", "ge", 2), ("multiple_hunks", "hunks", "ge", 2),
        ("at_least_ten_changed_lines", "changed_lines", "ge", 10),
        ("at_least_twenty_changed_lines", "changed_lines", "ge", 20),
        ("at_least_five_removed_lines", "removed_lines", "ge", 5),
        ("net_added_lines", "added_minus_removed", "gt", 0),
    ):
        definitions.append({"task_id": name, "family": "historical_repair_shape",
            "rule": "patch_measurement", "measurement": measurement,
            "comparison": comparison, "threshold": threshold, "positive_label": 1, "negative_label": 0})
    return definitions


def patch_targets(patch, definitions):
    added, removed, paths, hunks = [], [], [], 0
    in_hunk = False
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            paths.append(line)
            in_hunk = False
        elif line.startswith("@@ "):
            hunks += 1
            in_hunk = True
        elif in_hunk and line.startswith("+"):
            added.append(line[1:])
        elif in_hunk and line.startswith("-"):
            removed.append(line[1:])
    if not paths or not hunks or not (added or removed):
        raise ValueError("patch lacks an ordinary changed-line diff")
    measurement = {"paths": len(set(paths)), "hunks": hunks, "changed_lines": len(added) + len(removed),
                   "removed_lines": len(removed), "added_minus_removed": len(added) - len(removed)}
    labels = {}
    for definition in definitions:
        if definition["rule"] == "regex_search_in_any_selected_changed_line":
            selected = {"added": added, "removed": removed, "either": added + removed}[definition["direction"]]
            labels[definition["task_id"]] = int(any(re.search(definition["regex"], line) for line in selected))
        else:
            value, threshold = measurement[definition["measurement"]], definition["threshold"]
            labels[definition["task_id"]] = int(value >= threshold if definition["comparison"] == "ge"
                                                else value > threshold)
    normalized_patch = canonical([[direction, normalized(line)]
                                 for direction, lines in (("+", added), ("-", removed)) for line in lines])
    return labels, measurement, sha(normalized_patch)


def predictor_text(repo, statement, max_bytes=16384):
    if (type(repo) is not str or not repo.strip() or type(statement) is not str or not statement.strip()
            or type(max_bytes) is not int or not 256 <= max_bytes <= 32768):
        raise ValueError("bounded issue statement and repository required")
    raw = f"Repository: {repo}\n\nIssue:\n{statement}".encode()
    text = raw[:max_bytes].decode("utf-8", errors="ignore")
    return text, {"input_fields": ["repo", "problem_statement"], "raw_input_sha256": sha(raw),
                  "encoded_text_sha256": sha(text), "original_utf8_bytes": len(raw),
                  "retained_utf8_bytes": len(text.encode()), "truncated": len(text.encode()) < len(raw),
                  "truncation": "UTF-8 byte prefix, incomplete final codepoint removed"}


def prepare(records, acquisition, *, min_per_class=64, max_tasks=32, max_text_bytes=16384):
    if (type(min_per_class) is not int or not 1 <= min_per_class <= 10000
            or type(max_tasks) is not int or not 1 <= max_tasks <= 64):
        raise ValueError("invalid predeclared eligibility or capacity")
    definitions = task_definitions()
    protocol = {"schema": SCHEMA, "family": "historical_repair_shape", "task_family_count": 1,
        "target_interpretation": "lexical indicators on human patch changed lines; comments and strings count",
        "not_measured": ["human-validated root cause", "autonomous repair success", "independent task families"],
        "predictor_fields": ["repo", "problem_statement"], "forbidden_predictor_fields":
            ["patch", "test_patch", "hints_text", "FAIL_TO_PASS", "PASS_TO_PASS"],
        "chronology": "sort UTC issue-created_at, instance_id; raw-row 60/20/20 boundaries before duplicate removal",
        "grouping": ["instance_id", "normalized_issue", "normalized_changed_patch_lines", "normalized_predictor_text"],
        "duplicate_policy": "union before split; exclude every boundary-crossing group; earliest row per remaining group",
        "eligibility": {"training_distinct_groups_per_class_min": min_per_class,
                        "calibration_or_holdout_labels_used_for_selection": False},
        "capacity": {"max_tasks": max_tasks, "order": [d["task_id"] for d in definitions],
                     "selection": "first eligible tasks in this fixed order"},
        "max_predictor_utf8_bytes": max_text_bytes,
        "pretrained_corpus_contamination_controlled": False,
        "definition_sha256": sha(canonical(definitions))}
    prepared, invalid = [], []
    for record in records:
        try:
            source = record["instance_id"]
            if type(source) is not str or not source or len(source.encode()) > 512:
                raise ValueError("invalid source ID")
            created = datetime.fromisoformat(record["created_at"].replace("Z", "+00:00"))
            if created.tzinfo is None:
                raise ValueError("issue date lacks timezone")
            created = created.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            text, receipt = predictor_text(record["repo"], record["problem_statement"], max_text_bytes)
            labels, measurement, normalized_patch_hash = patch_targets(record["patch"], definitions)
            prepared.append({"source_id": source, "text": text, "created_at": created, "labels": labels,
                "source_version": {"dataset_repository": acquisition["repository"],
                    "dataset_revision": acquisition["revision"], "repo": record["repo"],
                    "base_commit": record["base_commit"], "version": record["version"]},
                "target": {"patch_sha256": sha(record["patch"]), "normalized_patch_sha256": normalized_patch_hash,
                           "measurements": measurement}, "receipt": receipt,
                "keys": [source, sha(normalized(record["problem_statement"])),
                         normalized_patch_hash, sha(normalized(text))]})
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            invalid.append({"source_id": record.get("instance_id"), "reason": str(exc)})
    prepared.sort(key=lambda r: (datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")),
                                 r["source_id"], r["target"]["patch_sha256"]))
    if len(prepared) < 5:
        raise ValueError("insufficient valid source events for chronological cohorts")
    parent = list(range(len(prepared)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    seen = {}
    for index, row in enumerate(prepared):
        for kind, value in enumerate(row["keys"]):
            key = (kind, value)
            if key in seen:
                parent[find(index)] = find(seen[key])
            seen[key] = index
    groups = {}
    boundaries = (int(len(prepared) * 0.6), int(len(prepared) * 0.8))
    for index, row in enumerate(prepared):
        row["split"] = "train" if index < boundaries[0] else "calibration" if index < boundaries[1] else "holdout"
        groups.setdefault(find(index), []).append(row)
    rows, targets, receipts, excluded, duplicates = [], [], [], [], []
    for members in groups.values():
        group_id = "repair-group:" + sha(canonical(sorted([m["source_id"], m["target"]["patch_sha256"]] for m in members)))
        if len({m["split"] for m in members}) > 1:
            excluded.append({"group_id": group_id, "source_ids": [m["source_id"] for m in members],
                             "reason": "duplicate group crosses chronological boundaries"})
            continue
        row = members[0]
        public = {key: row[key] for key in ("source_id", "text", "created_at", "source_version", "split", "labels")}
        public["group_id"] = group_id
        rows.append(public)
        targets.append({"source_id": row["source_id"], "group_id": group_id, **row["target"]})
        receipts.append({"source_id": row["source_id"], **row["receipt"]})
        if len(members) > 1:
            duplicates.append({"group_id": group_id, "retained": row["source_id"],
                "omitted": [m["source_id"] for m in members[1:]],
                "mixed_targets": any(m["labels"] != row["labels"] for m in members[1:])})
    task_status, selected = [], []
    for definition in definitions:
        task = definition["task_id"]
        counts = {split: [sum(r["labels"][task] == label for r in rows if r["split"] == split)
                          for label in (0, 1)] for split in ("train", "calibration", "holdout")}
        eligible = min(counts["train"]) >= min_per_class
        status = "unavailable_training_support"
        if eligible:
            status = "selected" if len(selected) < max_tasks else "not_selected_by_fixed_capacity"
            if status == "selected":
                selected.append(task)
        task_status.append({"task_id": task, "status": status, "eligible": eligible,
            "support_negative_positive": counts,
            "evaluation_missing_class_splits": [split for split in ("calibration", "holdout") if min(counts[split]) == 0]})
    protocol["cohort_boundaries"] = {"raw_valid_rows": len(prepared), "row_indices": list(boundaries),
        "first_calibration_created_at": prepared[boundaries[0]]["created_at"],
        "first_holdout_created_at": prepared[boundaries[1]]["created_at"]}
    dataset = {"schema": SCHEMA, "protocol": protocol, "task_definitions": definitions,
        "task_status": task_status, "selected_tasks": selected, "rows": rows}
    audit = {"input_rows": len(records), "retained_distinct_groups": len(rows),
        "retained_split_counts": {s: sum(r["split"] == s for r in rows) for s in ("train", "calibration", "holdout")},
        "invalid_rows": invalid, "crossing_groups_excluded": excluded, "duplicate_representatives": duplicates,
        "text_receipts": receipts, "selected_task_count": len(selected),
        "eligible_task_count": sum(t["eligible"] for t in task_status)}
    return dataset, targets, audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("input", "acquisition", "output"):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args()
    input_path, acquisition_path, output = Path(args.input), Path(args.acquisition), Path(args.output)
    acquisition = json.loads(acquisition_path.read_bytes())
    if (sha(input_path.read_bytes()) != acquisition["sha256"]
            or input_path.stat().st_size != acquisition["bytes"]
            or re.fullmatch(r"[0-9a-f]{40}", acquisition["revision"]) is None):
        raise ValueError("pinned source acquisition hash, size or revision mismatch")
    import pyarrow.parquet as pq
    records = pq.read_table(input_path, columns=["repo", "instance_id", "base_commit", "patch",
                            "problem_statement", "created_at", "version"]).to_pylist()
    dataset, targets, audit = prepare(records, acquisition)
    output.mkdir(parents=True, exist_ok=False)
    for name, value in (("dataset.json", dataset), ("targets.json", targets), ("audit.json", audit),
                        ("protocol.json", dataset["protocol"]), ("acquisition.json", acquisition)):
        (output / name).write_bytes(canonical(value) + b"\n")
    manifest = {"schema": SCHEMA, "acquisition": acquisition, "preparation_source_sha256": sha(Path(__file__).read_bytes()),
        "files": {p.name: {"sha256": sha(p.read_bytes()), "bytes": p.stat().st_size} for p in sorted(output.iterdir())},
        "selected_tasks": dataset["selected_tasks"], "audit_summary": {k: audit[k] for k in
            ("input_rows", "retained_distinct_groups", "retained_split_counts", "selected_task_count", "eligible_task_count")}}
    (output / "manifest.json").write_bytes(canonical(manifest) + b"\n")
    print(json.dumps(manifest["audit_summary"], indent=2))


if __name__ == "__main__":
    main()
