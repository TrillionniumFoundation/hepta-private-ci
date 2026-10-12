"""Unsigned, SHA-bound first-parent source references for real-project review.

An immediate-parent comparison is not the full pull-request diff, an answer,
a signed human review, an independently verified source family, or a model gain.
"""

import argparse
from collections import Counter
from copy import deepcopy
from pathlib import Path

from project_pr_parent_context import CATEGORIES, reopen_parent
from project_pr_review_packet import CENSUS, compile_packet
from project_pr_source_materialize import (
    atomic_json, canonical, digest, reopen_materialized, strict_json,
)
from project_pr_source_precommit import audit, read_pinned


def join(manifest, packet, parent, ready, verified):
    """Relate all 80 original HEAD files to 16 already committed questions."""
    audit(manifest)
    if (
        packet.get("schema") != "hepta.memorycell.real-project-answer-blind-review-index.v1"
        or packet.get("unsigned_questions") != 16
        or packet.get("original_file_bindings") != 80
        or packet.get("tasks_by_partition") != CENSUS
        or packet.get("source_byte_hashes_verified_by_separate_reopen") is not True
        or packet.get("independent_review_performed") is not False
        or packet.get("production_accepted") is not False
        or packet.get("semantic_citation_precision") is not None
        or parent.get("schema") != "hepta.memorycell.first-parent-byte-context.v1"
        or parent.get("original_file_count") != 80
        or parent.get("original_pr_count") != 8
        or parent.get("head_only_first_parent_not_complete_pr_history") is not True
        or parent.get("complete_pr_change_intent_verified") is not False
        or parent.get("test_target_labels_read") is not False
        or parent.get("pretrained_model_calls") != 0
        or parent.get("production_accepted") is not False
        or ready.get("schema") != "hepta.memorycell.first-parent-context-ready.v1"
        or ready.get("complete_pr_diff_certified") is not False
        or ready.get("independent_semantic_review") is not False
        or ready.get("model_calls") != 0
        or ready.get("production_accepted") is not False
        or verified.get("schema") != "hepta.memorycell.first-parent-offline-reopen.v1"
        or verified.get("offline_source_hash_verification") is not True
        or verified.get("original_file_count") != 80
        or verified.get("human_review_performed") is not False
        or verified.get("model_calls") != 0
        or verified.get("production_accepted") is not False
    ):
        raise ValueError("not a complete byte-verified unsigned source packet")
    if any(
        packet.get(key) != parent.get(mapped)
        for key, mapped in (
            ("source_manifest_sha256", "original_source_manifest_sha256"),
            ("original_inventory_sha256", "original_inventory_sha256"),
            ("original_ready_sha256", "original_ready_sha256"),
        )
    ) or packet.get("source_cut_utc") != parent.get("source_cut_utc"):
        raise ValueError("parent archive detached from original source cut")
    context_sha = digest(canonical(parent) + b"\n")
    if (
        ready.get("context_sha256") != context_sha
        or ready.get("original_source_manifest_sha256")
        != packet["source_manifest_sha256"]
    ):
        raise ValueError("first-parent READY/context digest drift")
    rows = parent.get("files")
    if not isinstance(rows, list) or len(rows) != 80:
        raise ValueError("incomplete first-parent file census")
    registered = [
        (c["repo"], c["partition"], c["pull_number"], c["head_sha"],
         f["path"], f["blob_sha"])
        for c in manifest["cases"] for f in c["files"]
    ]
    observed = [
        (r["project"], r["partition"], r["pull_number"], r["head_sha"],
         r["original_path"], r["original_head_sha1"]) for r in rows
    ]
    if registered != observed or len(set(observed)) != 80:
        raise ValueError("reordered, duplicate or changed original Git refs")
    stats = Counter(r["comparison_status"] for r in rows)
    if not set(stats) <= set(CATEGORIES) or dict(sorted(stats.items())) != parent.get("comparison_counts"):
        raise ValueError("unregistered or changed source classification")
    cases = {
        (c["repo"], c["pull_number"], c["head_sha"]): c
        for c in manifest["cases"]
    }
    if len(cases) != 8:
        raise ValueError("non-independent or duplicate project source cases")
    files_by_case = {
        key: {r["original_path"]: r for r in rows if (
            r["project"], r["pull_number"], r["head_sha"]
        ) == key}
        for key in cases
    }
    if any(len(files_by_case[key]) != len(case["files"])
           for key, case in cases.items()):
        raise ValueError("incomplete per-project source bindings")
    questions = packet.get("questions")
    if not isinstance(questions, list) or len(questions) != 16:
        raise ValueError("incomplete preregistered unsigned question census")
    questions_out, seen_tasks, reused = [], set(), Counter()
    for q in questions:
        key = (q.get("source_project"), q.get("source_pr"),
               q.get("source_head_sha"))
        task = q.get("task_id")
        if (
            key not in cases or not isinstance(task, str)
            or not task.startswith(f"{key[0]}#{key[1]}@{key[2]}/")
            or task in seen_tasks
            or q.get("partition") != cases[key]["partition"]
            or q.get("parent_commit_shas") != cases[key]["parents"]
            or q.get("reviewer_verdict") != "unreviewed"
            or q.get("source_sufficiency") != "unknown"
            or q.get("answer_gold") is not None
            or q.get("answer_or_model_prediction_in_packet") is not False
            or q.get("decoded_parent_diff_available") is not False
            or q.get("historical_review_discussion_authenticated") is not False
        ):
            raise ValueError("altered original question or invented review")
        seen_tasks.add(task)
        heads = q.get("verified_head_files")
        declared = cases[key]["files"]
        if not isinstance(heads, list) or len(heads) != len(declared):
            raise ValueError("missing HEAD evidence for review")
        before = []
        for head, source in zip(heads, declared, strict=True):
            path = head.get("original_path")
            row = files_by_case[key].get(path)
            if row is None or path != source["path"] or any((
                head.get("git_blob_sha1") != row["original_head_sha1"],
                head.get("byte_sha256") != row["original_head_sha256"],
                head.get("head_commit_sha") != row["head_sha"],
                row["full_pr_base_diff_certified"] is not False,
                row["human_semantic_review_performed"] is not False,
                row["independent_source_sufficiency"] is not None,
            )):
                raise ValueError("before/after files not bound to original HEAD bytes")
            parents, status = cases[key]["parents"], row["comparison_status"]
            parent_sha = row["first_parent_commit_sha"]
            if len(parents) == 2:
                if status != "ambiguous-multi-parent-head" or parent_sha is not None:
                    raise ValueError("merge parent must remain ambiguous")
            elif (
                len(parents) != 1 or parent_sha != parents[0]
                or status == "ambiguous-multi-parent-head"
            ):
                raise ValueError("first-parent SHA differs from frozen Git ancestry")
            if status == "byte-different-versus-first-parent":
                previous = row["previous_git_blob_sha1"]
                if (
                    not previous or not row["previous_sha256"]
                    or row["before_blob_path"] != "before-blobs/" + previous + ".blob"
                ):
                    raise ValueError("missing verified previous Git bytes")
            elif row["before_blob_path"] is not None:
                raise ValueError("fabricated old Git blob for unresolved source")
            if (
                status == "unresolved-renamed-previous-path"
                and source["status"] != "renamed"
            ):
                raise ValueError("invented rename status")
            reused[(key, path)] += 1
            before.append(dict(
                original_path=path,
                head_git_blob_sha1=head["git_blob_sha1"],
                first_parent_commit_sha=parent_sha,
                comparison_status=status,
                previous_git_blob_sha1=row["previous_git_blob_sha1"],
                previous_byte_sha256=row["previous_sha256"],
                verified_before_blob_path=row["before_blob_path"],
                complete_pr_diff_certified=False,
                semantic_sufficiency=None,
            ))
        enriched = deepcopy(q)
        enriched["verified_first_parent_files"] = before
        enriched["immediate_parent_is_not_complete_pr_history"] = True
        questions_out.append(enriched)
    if len(seen_tasks) != 16 or len(reused) != 80 or set(reused.values()) != {2}:
        raise ValueError("lost, duplicated or reweighted review questions")
    result = deepcopy(packet)
    result.update(
        schema="hepta.memorycell.real-project-parent-blind-review.v1",
        original_packet_sha256=digest(canonical(packet) + b"\n"),
        first_parent_context_sha256=context_sha,
        source_file_bindings=80,
        unsigned_question_file_references=160,
        comparison_counts=dict(sorted(stats.items())),
        questions=questions_out,
        full_pr_diff_certified=False,
        independent_review_performed=False,
        semantic_citation_precision=None,
        production_accepted=False,
    )
    return result


def export(manifest_path, originals, parents, output, *, manifest_sha):
    """Reread both original byte stores before emitting an exclusive new index."""
    if output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise ValueError("output must be new")
    manifest = read_pinned(manifest_path, manifest_sha)
    original_receipt = reopen_materialized(
        manifest, originals, manifest_sha=manifest_sha
    )
    inventory_path = originals / "inventory.json"
    if inventory_path.is_symlink() or not inventory_path.is_file():
        raise ValueError("missing source inventory")
    raw = inventory_path.read_bytes()
    packet = compile_packet(
        manifest, strict_json(raw.decode()), original_receipt,
        inventory_sha256=digest(raw),
    )
    checked = reopen_parent(
        manifest, originals, parents, manifest_sha=manifest_sha
    )
    def canonical_file(path):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
            raise ValueError("missing or unsafe parent metadata")
        raw_bytes = path.read_bytes()
        value = strict_json(raw_bytes.decode("utf-8"))
        if raw_bytes != canonical(value) + b"\n":
            raise ValueError("noncanonical parent receipt")
        return value
    result = join(
        manifest, packet, canonical_file(parents / "context.json"),
        canonical_file(parents / "READY.json"), checked,
    )
    atomic_json(output, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("original", type=Path)
    parser.add_argument("parents", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-sha256", required=True)
    a = parser.parse_args()
    result = export(a.manifest, a.original, a.parents, a.output,
                    manifest_sha=a.source_sha256)
    print(dict(unsigned_questions=result["unsigned_questions"],
               source_file_bindings=result["source_file_bindings"],
               independent_review_performed=False, production_accepted=False))
