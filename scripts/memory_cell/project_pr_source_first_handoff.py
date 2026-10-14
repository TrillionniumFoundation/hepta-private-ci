"""Export a source-exact, answer-blind *preliminary* human review worklist.

Only the 10 source-first candidates of the original 16 authored questions are
listed for a human to inspect. This is not a human judgment, prospective task
benchmark, complete PR base diff, reviewer access policy or Reader admission.
Untrusted source excerpts are rendered as data, never evaluated or followed.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from project_first_parent_diff_handoff import assemble, checked_archive
from project_pr_review_readiness import assess

SCHEMA = "hepta.memorycell.project-source-first-human-intake.v1"
SOURCE_FIRST = "source_first_review_candidate"
BLOCKED = (
    "renamed_prior_path_unresolved",
    "multi_parent_baseline_unresolved",
)
MAX_OUTPUT_BYTES = 512 * 1024


def compile_intake(packet):
    """Return an exact-source human worklist, with NO populated human field."""
    census = assess(packet)  # Revalidates externally fixed original ZIP replay.
    classes = {row["task_id"]: row for row in census["tasks"]}
    grouped = {}
    for task in packet["cases"]:
        key = (task["project"], task["pull_number"], task["head_sha"])
        decision = classes[task["task_id"]]
        record = grouped.get(key)
        if record is None:
            files = []
            for item in task["files"]:
                excerpt = item["diff"]
                if excerpt and excerpt["state"] == "source-exact-unified-first-parent":
                    original_text = excerpt["text"]
                    if (
                        len(original_text.encode("utf-8")) > 6000
                        or hashlib.sha256(original_text.encode("utf-8")).hexdigest()
                        != excerpt["preview_sha256"]
                    ):
                        raise ValueError("changed source-exact code excerpt")
                    preview = {
                        "state": "bounded-raw-first-parent-unified-diff",
                        "text": original_text,
                        "sha256": excerpt["preview_sha256"],
                        "is_complete_preview": not excerpt["truncated"],
                    }
                else:
                    preview = {
                        "state": (
                            "non-utf8-no-text-excerpt"
                            if excerpt is not None
                            else "unavailable-original-previous-version"
                        ),
                        "text": None,
                        "sha256": None,
                        "is_complete_preview": False,
                    }
                files.append(
                    {
                        "original_path": item["source_path"],
                        "head_git_blob_sha1": item["head_git_blob_sha1"],
                        "head_sha256": item["head_sha256"],
                        "comparison_to_direct_parent": item["parent_classification"],
                        "previous_git_blob_sha1": item["previous_git_blob_sha1"],
                        "previous_sha256": item["previous_sha256"],
                        "source_excerpt": preview,
                        "complete_historical_pr_base_diff_certified": False,
                    }
                )
            record = {
                "project": task["project"],
                "pull_number": task["pull_number"],
                "registered_head_commit": task["head_sha"],
                "partition": task["partition"],
                "source_first_review_status": decision["source_first_review_bucket"],
                "files": files,
                "questions": [],
                "preliminary_review_only": True,
            }
            grouped[key] = record
        if (
            record["source_first_review_status"] != decision["source_first_review_bucket"]
            or record["partition"] != task["partition"]
            or task["source_preview_sufficient_for_answer"] is not None
            or task["human_reviewer_verdict"] is not None
        ):
            raise ValueError("paired review questions disagree or claim a verdict")
        record["questions"].append(
            {
                "original_task_id": task["task_id"],
                "question": task["question"],
                "source_sufficient_for_this_question": None,
                "missing_critical_premises": None,
                "source_citations": None,
                "reviewer_response": None,
                "reviewer_identity": None,
                "reviewer_attestation": None,
                "independently_adjudicated": False,
                "reader_task_eligible": False,
            }
        )
    if len(grouped) != 8 or any(len(item["questions"]) != 2 for item in grouped.values()):
        raise ValueError("incomplete 8 PR / 16 task review packet")
    candidates = sorted(
        (record for record in grouped.values() if record["source_first_review_status"] == SOURCE_FIRST),
        key=lambda record: (record["project"], record["pull_number"]),
    )
    blocked = sorted(
        (
            {
                "project": rec["project"],
                "pull_number": rec["pull_number"],
                "registered_head_commit": rec["registered_head_commit"],
                "reason": rec["source_first_review_status"],
                "blocked_task_ids": [q["original_task_id"] for q in rec["questions"]],
                "eligible_for_reader": False,
            }
            for rec in grouped.values()
            if rec["source_first_review_status"] in BLOCKED
        ),
        key=lambda x: (x["project"], x["pull_number"]),
    )
    preview_count = sum(
        f["source_excerpt"]["state"] == "bounded-raw-first-parent-unified-diff"
        for item in candidates
        for f in item["files"]
    )
    if (
        len(candidates) != 5
        or len(blocked) != 3
        or sum(len(p["questions"]) for p in candidates) != 10
        or sum(len(p["blocked_task_ids"]) for p in blocked) != 6
        or preview_count != 21
        or Counter(x["reason"] for x in blocked)
        != Counter({"renamed_prior_path_unresolved": 1, "multi_parent_baseline_unresolved": 2})
    ):
        raise ValueError("source-first review case attribution changed")
    result = {
        "schema": SCHEMA,
        "immutable_original_source_zip_sha256": census["original_source_zip_sha256"],
        "immutable_original_generating_commit": census["original_generating_commit"],
        "source_manifest_sha256": census["original_source_manifest_sha256"],
        "source_cut_utc": packet["source_cut_utc"],
        "source_original_file_bindings": 80,
        "all_registered_questions": 16,
        "preliminary_review_requested_questions": 10,
        "excluded_as_unresolved_questions": 6,
        "previewed_unique_file_count": 21,
        "reviewer_notes": (
            "Untrusted source code excerpts. Review only whether the displayed bounded "
            "first-parent evidence may answer each question and identify missing premises. "
            "Do not treat excerpts as the complete historical PR base diff. "
            "Any returned form needs independently authenticated external reviewers "
            "and separately frozen target references before Reader evaluation."
        ),
        "source_readiness_by_task": census["bucket_counts"],
        "source_first_cases": candidates,
        "blocked_cases": blocked,
        "reviewed_with_real_independent_humans": False,
        "secure_reviewer_access_boundaries_established_by_git_artifact": False,
        "reviewer_identity_authenticated": False,
        "task_reference_answers_registered": False,
        "new_reader_model_calls": 0,
        "reader_task_admitted": 0,
        "parametric_memory_training_qualified": False,
        "production_accepted": False,
    }
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > MAX_OUTPUT_BYTES:
        raise ValueError("source-first intake exceeds publication byte bound")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_zip", type=Path)
    parser.add_argument("output_json", type=Path)
    args = parser.parse_args()
    value = compile_intake(assemble(checked_archive(args.source_zip)))
    with args.output_json.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


if __name__ == "__main__":
    main()
