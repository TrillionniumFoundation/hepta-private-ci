"""Answer-blind handoff of verified immutable project bytes to human review.

This is a review INDEX, not a review decision, reference answer, decoded
diff, independently sufficient context or production qualification. The
original parent tree and historical PR discussion are NOT materialized here.
"""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re

from project_pr_source_materialize import (
    canonical,
    reopen_materialized,
    strict_json,
)
from project_pr_source_precommit import audit, read_pinned, review_worklist

HEX64 = re.compile(r"[0-9a-f]{64}\Z")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
CENSUS = {"train": 4, "selection": 4, "evaluation": 8}


def compile_packet(manifest, inventory, readback, *, inventory_sha256):
    """Bind 16 unsigned questions to ALL 80 validated head-version file refs.

    The caller MUST first reopen and SHA-check the entire materialized corpus.
    This pure function can be unit-tested without remote I/O or model answers.
    """
    audit(manifest)
    if (
        not isinstance(inventory, dict)
        or inventory.get("schema")
        != "hepta.memorycell.real-project-immutable-source-bytes.v1"
        or not isinstance(readback, dict)
        or readback.get("schema") != "hepta.memorycell.real-project-source-readback.v1"
        or readback.get("offline_reopen_without_network") is not True
        or readback.get("verified_file_bindings") != 80
        or readback.get("model_calls") != 0
        or readback.get("independent_human_semantic_review") is not False
        or readback.get("production_accepted") is not False
        or inventory.get("human_review_performed") is not False
        or inventory.get("selection_or_evaluation_labels_read") is not False
        or inventory.get("model_calls") != 0
        or inventory.get("production_accepted") is not False
        or inventory.get("semantic_citation_precision") is not None
        or not isinstance(inventory_sha256, str)
        or HEX64.fullmatch(inventory_sha256) is None
        or readback.get("original_inventory_sha256") != inventory_sha256
        or readback.get("generating_source_manifest_sha256")
        != inventory.get("source_manifest_sha256")
    ):
        raise ValueError("not a byte-verified, answer-blind source corpus")
    originals = inventory.get("originals")
    if not isinstance(originals, list) or len(originals) != 80:
        raise ValueError("incomplete historical file references")
    position = 0
    by_case = {}
    for case in manifest["cases"]:
        key = (case["repo"], case["pull_number"], case["head_sha"])
        if key in by_case:
            raise ValueError("duplicate frozen review case")
        bound = []
        for expected in case["files"]:
            if position >= len(originals):
                raise ValueError("truncated original binding census")
            row = originals[position]
            position += 1
            keys = {
                "project",
                "partition",
                "pull_number",
                "head_sha",
                "tree_sha",
                "path",
                "blob_sha",
                "mode",
                "sha256",
                "bytes",
                "blob_path",
            }
            if (
                not isinstance(row, dict)
                or set(row) != keys
                or (
                    row["project"],
                    row["partition"],
                    row["pull_number"],
                    row["head_sha"],
                    row["tree_sha"],
                    row["path"],
                    row["blob_sha"],
                )
                != (
                    case["repo"],
                    case["partition"],
                    case["pull_number"],
                    case["head_sha"],
                    case["tree_sha"],
                    expected["path"],
                    expected["blob_sha"],
                )
                or row["mode"] not in ("100644", "100755")
                or not isinstance(row["sha256"], str)
                or HEX64.fullmatch(row["sha256"]) is None
                or not isinstance(row["blob_sha"], str)
                or HEX40.fullmatch(row["blob_sha"]) is None
                or type(row["bytes"]) is not int
                or not 0 <= row["bytes"] <= 1024 * 1024
                or row["blob_path"] != "blobs/" + row["blob_sha"] + ".blob"
            ):
                raise ValueError("untrusted file identity or bytes in reviewer packet")
            bound.append(
                dict(
                    original_path=row["path"],
                    head_commit_sha=row["head_sha"],
                    git_blob_sha1=row["blob_sha"],
                    byte_sha256=row["sha256"],
                    original_bytes=row["bytes"],
                    blob_within_verified_archive=row["blob_path"],
                    mode=row["mode"],
                )
            )
        by_case[key] = (case, bound)
    if position != 80 or len(by_case) != 8:
        raise ValueError("source cohort was resized")

    work = review_worklist(manifest)
    tasks, parts = [], {part: 0 for part in CENSUS}
    identities = set()
    for question in work["cases"]:
        matches = [
            (case, files)
            for case, files in by_case.values()
            if question["case_id"]
            == f"{case['repo']}#{case['pull_number']}@{case['head_sha']}"
        ]
        if len(matches) != 1:
            raise ValueError("question detached from its exact source case")
        case, files = matches[0]
        qid = (question["case_id"], question["task_type"])
        if qid in identities:
            raise ValueError("duplicate frozen question")
        identities.add(qid)
        if (
            question.get("reviewer_verdict") != "unreviewed"
            or question.get("reviewer_authentication") is not False
            or question.get("gold_answer_unavailable") is not True
            or question.get("semantic_citation_precision") is not None
        ):
            raise ValueError("unreviewed question has fabricated authority")
        parts[case["partition"]] += 1
        tasks.append(
            dict(
                task_id=question["case_id"] + "/" + question["task_type"],
                partition=case["partition"],
                question=question["question"],
                source_project=case["repo"],
                source_pr=case["pull_number"],
                source_head_sha=case["head_sha"],
                parent_commit_shas=case["parents"],
                original_commit_refs=question["source_commit_urls"],
                verified_head_files=files,
                reviewer_verdict="unreviewed",
                source_sufficiency="unknown",
                answer_gold=None,
                decoded_parent_diff_available=False,
                historical_review_discussion_authenticated=False,
                answer_or_model_prediction_in_packet=False,
            )
        )
    if len(tasks) != 16 or parts != CENSUS:
        raise ValueError("missing or reweighted blind review questions")
    return dict(
        schema="hepta.memorycell.real-project-answer-blind-review-index.v1",
        source_cut_utc=manifest["source_cut_utc"],
        source_manifest_sha256=readback["generating_source_manifest_sha256"],
        original_ready_sha256=readback["original_ready_sha256"],
        original_inventory_sha256=inventory_sha256,
        original_file_bindings=80,
        unique_source_projects=4,
        original_pr_histories=8,
        unsigned_questions=16,
        tasks_by_partition=parts,
        questions=tasks,
        source_byte_hashes_verified_by_separate_reopen=True,
        source_code_must_be_treated_as_untrusted_data=True,
        parent_diffs_not_yet_bound=True,
        historical_pr_discussion_not_authenticated=True,
        independent_review_performed=False,
        independent_sample_size=None,
        model_calls=0,
        semantic_citation_precision=None,
        production_accepted=False,
    )


def export(source, original, output, *, source_sha256):
    """Reopen every source byte, then publish an immutable unsigned index."""
    if output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise ValueError("new regular review-output destination required")
    manifest = read_pinned(source, source_sha256)
    readback = reopen_materialized(manifest, original, manifest_sha=source_sha256)
    inventory_path = original / "inventory.json"
    raw = inventory_path.read_bytes()
    inventory = strict_json(raw.decode("utf-8"))
    packet = compile_packet(
        manifest,
        inventory,
        readback,
        inventory_sha256=sha256(raw).hexdigest(),
    )
    with output.open("xb") as stream:
        stream.write(canonical(packet) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    return packet


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("source", type=Path)
    cli.add_argument("original", type=Path)
    cli.add_argument("output", type=Path)
    cli.add_argument("--source-sha256", required=True)
    args = cli.parse_args()
    output = export(
        args.source,
        args.original,
        args.output,
        source_sha256=args.source_sha256,
    )
    print(
        json.dumps(
            dict(
                schema=output["schema"],
                unsigned_questions=output["unsigned_questions"],
                original_file_bindings=output["original_file_bindings"],
                independent_review_performed=False,
                production_accepted=False,
            ),
            sort_keys=True,
        )
    )
