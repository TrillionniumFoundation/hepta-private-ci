"""Read-only, two-parent *alternatives* for frozen real-project merge HEADs.

No unique baseline is inferred from a merge, no PR-complete diff is asserted,
no model inference or human sufficiency judgment is performed. Parent blobs
come from immutable, SHA-addressed Git objects already identified by the
independent source-byte/concordance archive. Never execute retrieved source.
"""

import argparse
from collections import Counter
from pathlib import Path
import json
import os
import re

from project_first_parent_diff_handoff import (
    ORIGINAL_ZIP_SHA256,
    SOURCE_COMMIT,
    SOURCE_MANIFEST_SHA256,
    checked_archive,
    diff_lines,
    git_blob,
    replay_source,
    sha,
    unique_json,
)
from project_pr_source_materialize import decode_blob, github_json

PROFILE = "hepta.memorycell.real-project.two-parent-alternatives.v1"
MAX_NEW_BLOBS = 64
MAX_BLOB_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024


def bound_rows(files):
    """Require all 31 exact, externally pinned merge rows before remote access."""
    read = lambda name: unique_json(files[name])
    merge = read("merge-concordance/concordance.json")
    ready = read("merge-concordance/READY.json")
    original = read("original/inventory.json")
    context = read("first-parent/context.json")
    questions = read("unsigned-first-parent-review.json")
    if (
        merge.get("schema") != "hepta.memorycell.merge-parent-concordance.v1"
        or merge.get("classification_counts") != {"absent-one": 1, "parents-diverge": 30}
        or merge.get("merge_file_count") != 31
        or merge.get("original_file_count") != 80
        or merge.get("both_parents_required") is not True
        or merge.get("single_parent_selection_prohibited") is not True
        or merge.get("complete_pr_base_diff_certified") is not False
        or merge.get("independent_review") is not None
        or merge.get("model_calls") != 0
        or merge.get("production_accepted") is not False
        or ready.get("common_previous_files") != 0
        or ready.get("common_previous_bytes") != 0
        or ready.get("merge_file_count") != 31
        or ready.get("concordance_sha256") != sha(files["merge-concordance/concordance.json"])
        or ready.get("source_manifest_sha256") != SOURCE_MANIFEST_SHA256
        or ready.get("production_accepted") is not False
        or context.get("original_source_manifest_sha256") != SOURCE_MANIFEST_SHA256
        or context.get("comparison_counts", {}).get("ambiguous-multi-parent-head") != 31
        or original.get("source_manifest_sha256") != SOURCE_MANIFEST_SHA256
        or original.get("original_file_bindings") != 80
        or original.get("model_calls") != 0
        or questions.get("source_manifest_sha256") != SOURCE_MANIFEST_SHA256
        or questions.get("unsigned_questions") != 16
        or questions.get("independent_review_performed") is not False
        or questions.get("production_accepted") is not False
    ):
        raise ValueError("original SHA-bound two-parent source census drift")
    originals = {
        (row["project"], row["pull_number"], row["head_sha"], row["path"]): row
        for row in original["originals"]
    }
    ambiguous = {
        (row["project"], row["pull_number"], row["head_sha"], row["original_path"])
        for row in context["files"]
        if row["comparison_status"] == "ambiguous-multi-parent-head"
    }
    if len(originals) != 80 or len(ambiguous) != 31:
        raise ValueError("incomplete original/merge source binding")
    result = []
    seen = set()
    for row in merge["rows"]:
        key = (row["project"], row["pull_number"], row["head_sha"], row["head_path"])
        entry = originals.get(key)
        if key not in ambiguous or entry is None or key in seen:
            raise ValueError("unknown duplicate or non-merge source")
        seen.add(key)
        if (
            row["partition"] != "evaluation"
            or row["project"] not in ("numpy/numpy", "astral-sh/ruff")
            or row["head_blob_sha1"] != entry["blob_sha"]
            or row["head_sha256"] != entry["sha256"]
            or row["classification"] not in ("parents-diverge", "absent-one")
            or row["common_previous_blob_sha1"] is not None
            or row["common_previous_sha256"] is not None
            or row["complete_pr_base_diff_certified"] is not False
            or row["independent_review"] is not None
            or not isinstance(row["parent_entries"], list)
            or len(row["parent_entries"]) != 2
            or not isinstance(row["parent_commits"], list)
            or len(row["parent_commits"]) != 2
            or len(set(row["parent_commits"])) != 2
            or len(row["parent_trees"]) != 2
        ):
            raise ValueError("original two-parent provenance or authority drift")
        entries = row["parent_entries"]
        if (row["classification"] == "absent-one") != (sum(x is None for x in entries) == 1):
            raise ValueError("parent absence classification drift")
        if row["classification"] == "parents-diverge" and (
            entries[0] is None or entries[1] is None or entries[0] == entries[1]
        ):
            raise ValueError("divergent two-parent claim unsupported")
        for parent in entries:
            if parent is not None and (
                set(parent) != {"blob_sha", "mode"}
                or not re.fullmatch(r"[0-9a-f]{40}", parent["blob_sha"])
                or parent["mode"] not in ("100644", "100755")
            ):
                raise ValueError("invalid original parent Git blob identity")
        result.append((row, entry))
    if len(result) != 31 or seen != ambiguous:
        raise ValueError("missing any preregistered merge file")
    cases = [
        q for q in questions["questions"]
        if (q["source_project"], q["source_pr"]) in {("numpy/numpy", 32523), ("astral-sh/ruff", 28828)}
    ]
    if len(cases) != 4 or len({q["task_id"] for q in cases}) != 4:
        raise ValueError("complete four frozen merge-review question census required")
    if any(
        q["answer_gold"] is not None
        or q["reviewer_verdict"] != "unreviewed"
        or q["source_sufficiency"] != "unknown"
        or q["answer_or_model_prediction_in_packet"] is not False
        for q in cases
    ):
        raise ValueError("gold or synthetic review leaked into source handoff")
    return result, cases


def produce(files, fetch):
    """Fetch each missing immutable parent blob once, preserve both alternatives."""
    rows, cases = bound_rows(files)
    originals = {}
    for row, entry in rows:
        key = (row["project"], row["pull_number"], row["head_sha"], row["head_path"])
        raw = replay_source(
            files, "original/" + entry["blob_path"],
            git_sha=entry["blob_sha"], digest=entry["sha256"],
        )
        if len(raw) != entry["bytes"]:
            raise ValueError("changed original HEAD source length")
        originals[key] = raw
    cached = {}
    total = 0
    grouped = {}
    fetched_refs = set()
    for row, entry in rows:
        key = (row["project"], row["pull_number"], row["head_sha"], row["head_path"])
        head = originals[key]
        parents = []
        for parent_commit, parent_tree, version in zip(
            row["parent_commits"], row["parent_trees"], row["parent_entries"], strict=True
        ):
            previous = None
            if version is not None:
                blob = version["blob_sha"]
                if blob == row["head_blob_sha1"]:
                    previous = head
                else:
                    cache_key = row["project"], blob
                    if cache_key not in cached:
                        if len(cached) >= MAX_NEW_BLOBS:
                            raise ValueError("too many remote parent blobs")
                        payload = fetch(*cache_key)
                        if not isinstance(payload, bytes) or len(payload) > MAX_BLOB_BYTES:
                            raise ValueError("parent blob unavailable under byte limit")
                        if git_blob(payload) != blob:
                            raise ValueError("parent bytes do not match exact Git SHA-1")
                        if total + len(payload) > MAX_TOTAL_BYTES:
                            raise ValueError("parent source byte bound exceeded")
                        cached[cache_key] = payload
                        total += len(payload)
                    previous = cached[cache_key]
                    fetched_refs.add(cache_key)
            preview = (
                None if previous is None
                else diff_lines(previous, head, row["head_path"])
            )
            parents.append({
                "parent_commit": parent_commit,
                "parent_tree": parent_tree,
                "previous_exists_at_same_path": version is not None,
                "previous_blob_sha1": version["blob_sha"] if version else None,
                "previous_mode": version["mode"] if version else None,
                "previous_sha256": sha(previous) if previous is not None else None,
                "same_bytes_as_head": previous == head if previous is not None else None,
                "diff": preview,
            })
        grouped.setdefault((row["project"], row["pull_number"], row["head_sha"]), []).append({
            "path": row["head_path"],
            "head_git_blob_sha1": row["head_blob_sha1"],
            "head_sha256": row["head_sha256"],
            "classification": row["classification"],
            "both_parent_alternatives": parents,
            "no_uniquely_certified_previous_version": True,
            "complete_pr_base_diff_certified": False,
            "semantic_source_sufficiency_verified": False,
        })
    tasks = []
    for question in cases:
        key = (question["source_project"], question["source_pr"], question["source_head_sha"])
        bindings = grouped[key]
        expected = [
            x["original_path"] for x in question["verified_first_parent_files"]
        ]
        if expected != [x["path"] for x in bindings]:
            raise ValueError("frozen question-to-merged-code association changed")
        tasks.append({
            "task_id": question["task_id"],
            "project": key[0],
            "pull_number": key[1],
            "partition": question["partition"],
            "question": question["question"],
            "files": bindings,
            "original_gold_answer": None,
            "reviewer_verdict": "unreviewed",
            "reviewer_identity_authenticated": False,
            "evidence_sufficiency": None,
        })
    if sum(len(x["files"]) for x in tasks) != 62:
        raise ValueError("partial double-review source association")
    return {
        "schema": PROFILE,
        "original_source_zip_sha256": ORIGINAL_ZIP_SHA256,
        "original_generating_commit": SOURCE_COMMIT,
        "source_manifest_sha256": SOURCE_MANIFEST_SHA256,
        "merge_file_count": 31,
        "merge_classifications": dict(Counter(row["classification"] for row, _ in rows)),
        "review_tasks": tasks,
        "review_task_count": len(tasks),
        "parent_alternatives_per_file": 2,
        "independently_git_sha1_verified_new_parent_blobs": len(cached),
        "original_new_parent_bytes_verified": total,
        "independently_certified_unique_previous_versions": 0,
        "complete_pr_base_diff_certified": False,
        "historical_pr_discussion_authenticated": False,
        "independent_semantic_review": False,
        "human_sufficient_evidence_verdicts": 0,
        "actual_reader_model_calls": 0,
        "parametric_memory_training_qualified": False,
        "production_accepted": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_zip", type=Path)
    parser.add_argument("output_json", type=Path)
    args = parser.parse_args()
    content = checked_archive(args.source_zip)

    def fetch_blob(repo, oid):
        obj = github_json(repo, "blobs", oid, token=os.environ.get("GH_TOKEN"))
        return decode_blob(obj, oid)

    record = produce(content, fetch_blob)
    with args.output_json.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()