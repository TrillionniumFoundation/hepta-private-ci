"""Read-only independent prompt-echo inspection of 32 pinned flat Reader outputs.

A structurally valid [E1] is NOT an authored citation when the surrounding
output copies the exact Reader user/system prompt. Never read held-out targets,
rerun the model, credit entailment, or modify old answers here.
"""

import argparse
import ast
from collections import Counter, defaultdict
import json
from pathlib import Path
import re

from native import digest
from stem_audit_archive import PinnedArchive, require
from stem_reader_format_ablation import (
    ARCHIVED_SOURCE, ARCHIVED_TREE, ARCHIVED_ZIP_SHA256,
    fixed_frozen_cases, flat_user_message,
)

FLAT_SOURCE = "9d23a30d1204837767131856cd8f20542f1ddc68"
FLAT_TREE = "5f9329971ce3e46adad70b005ca3efd00dbf6289"
FLAT_SHA256 = "4d28ee07ec9425e3fe3288c9eaf79362fc23d64ec50ad359279d2f9ddca7389b"
PHASES = ("select", "retention", "test", "transfer")
MARKER = re.compile(r"\[E([0-9]+)\]")
MIN_COPY_LENGTH = 24


def _static_system(archived_source):
    """Read the immutable original SYSTEM AST literal without importing Torch."""
    tree = ast.parse(archived_source.decode("utf-8"))
    found = [
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "SYSTEM"
                for t in node.targets)
    ]
    require(len(found) == 1 and isinstance(found[0], str)
            and "[E1]" in found[0], "archived system prompt identity unavailable")
    return found[0]


def longest_prompt_copy(answer, marker, user_message, system_message):
    """Longest original prompt substring surrounding, not merely containing [E1]."""
    require(
        isinstance(answer, str) and len(answer) <= 16384
        and 0 <= marker.start() < marker.end() <= len(answer),
        "bounded original Reader answer/marker required",
    )
    best = (0, None)
    for label, prompt in (("user", user_message), ("system", system_message)):
        for left in range(max(0, marker.start() - 128), marker.start() + 1):
            for right in range(marker.end(),
                               min(len(answer), marker.end() + 128) + 1):
                length = right - left
                if length > best[0] and answer[left:right] in prompt:
                    best = length, label
    return best


def review_copied_markers(cases, records, system_message):
    """All 32 original questions and all new answers required before reviewing."""
    case_by_id = {case["question_id"]: case for case in cases}
    require(len(cases) == len(case_by_id) == 32
            and all(sum(c["phase"] == p for c in cases) == 8 for p in PHASES),
            "noncanonical original Reader case denominator")
    raw = {}
    for row in records:
        qid = row["question_id"]
        require(qid in case_by_id and qid not in raw
                and row["phase"] == case_by_id[qid]["phase"]
                and row["status"] == "succeeded"
                and row["schema"] == "hepta.stem-flat-format-answer.v1",
                "missing, failed, duplicated or substituted flat Reader answer")
        raw[qid] = row
    require(set(raw) == set(case_by_id), "missing original Reader flat-format request")
    phase_counts = defaultdict(Counter)
    question_rows = []
    for case in cases:
        qid = case["question_id"]
        row = raw[qid]
        receipt = row["receipt"]
        original_user = flat_user_message(
            case["question"], case["delivered_evidence"],
        )
        require(
            row["case_original_digest"] == digest(case)
            and row["original_reader_identity"] == case["original_reader_identity"]
            and row["original_reader_profile"] == case["original_reader_profile"]
            and row["previous_answer_sha256"] == case["original_answer_sha256"]
            and receipt["generator_identity"] == case["original_reader_identity"]
            and receipt["original_reader_profile"] == case["original_reader_profile"]
            and receipt["delivered_evidence"] == case["delivered_evidence"]
            and receipt["question_digest"] == digest(case["question"])
            and receipt["new_flat_user_message_digest"] == digest(original_user)
            and receipt["decoded_max_new_tokens"] == 96
            and receipt["generator_parameter_updates"] == 0
            and receipt["new_flat_user_payload_only"] is True
            and receipt["same_generator_weights"] is True
            and receipt["same_system_instruction"] is True
            and receipt["production_accepted"] is False,
            "flat output not tied to the same immutable Reader and source",
        )
        label = case["delivered_evidence"][0]["label"]
        markers = []
        for marker in MARKER.finditer(row["answer"]):
            overlap, prompt = longest_prompt_copy(
                row["answer"], marker, original_user, system_message,
            )
            markers.append(dict(
                delivered_label=marker.group()[1:-1] == label,
                exact_prompt_overlap_chars=overlap,
                copied_from_prompt=overlap >= MIN_COPY_LENGTH,
                copied_from=prompt if overlap >= MIN_COPY_LENGTH else None,
                independently_semantically_adjudicated=False,
            ))
        phase = case["phase"]
        phase_counts[phase]["questions"] += 1
        phase_counts[phase]["structural_markers"] += len(markers)
        phase_counts[phase]["bound_to_delivered_label"] += sum(
            x["delivered_label"] for x in markers
        )
        phase_counts[phase]["long_prompt_copies"] += sum(
            x["copied_from_prompt"] for x in markers
        )
        phase_counts[phase]["user_copies"] += sum(
            x["copied_from"] == "user" for x in markers
        )
        phase_counts[phase]["system_copies"] += sum(
            x["copied_from"] == "system" for x in markers
        )
        question_rows.append(dict(
            question_identity_sha256=digest(qid),
            phase=phase,
            citation_markers=len(markers),
            citation_markers_with_long_prompt_copy=sum(
                x["copied_from_prompt"] for x in markers
            ),
            marker_classifications=markers,
            answer_text_and_evidence_not_reexported=True,
        ))
    phases = {}
    for p in PHASES:
        require(phase_counts[p]["questions"] == 8, "retained phase census drift")
        phases[p] = {
            k: phase_counts[p][k] for k in (
                "questions", "structural_markers", "bound_to_delivered_label",
                "long_prompt_copies", "user_copies", "system_copies",
            )
        }
    total = lambda key: sum(phases[p][key] for p in PHASES)
    return dict(
        schema="hepta.stem-flat-reader-prompt-echo-audit.v1",
        original_strict_source=ARCHIVED_SOURCE,
        original_flat_reader_source=FLAT_SOURCE,
        registered_original_policy_attempts=576,
        registered_distinct_questions=32,
        phases=phases,
        structural_citation_markers=total("structural_markers"),
        bound_to_delivered_evidence_label=total("bound_to_delivered_label"),
        verbatim_prompt_citation_markers=total("long_prompt_copies"),
        flat_user_prompt_copies=total("user_copies"),
        original_system_prompt_copies=total("system_copies"),
        minimum_contiguous_prompt_copy_chars=MIN_COPY_LENGTH,
        markers_not_proven_prompt_copies=(
            total("structural_markers") - total("long_prompt_copies")
        ),
        independently_authored_citation_count_not_established=True,
        independent_semantic_entailment_precision=None,
        source_or_model_input_bytes_unchanged=True,
        model_calls_this_audit=0,
        target_annotations_opened=False,
        production_accepted=False,
        rows=question_rows,
    )


def audit(strict_zip, flat_zip):
    original = PinnedArchive(strict_zip, ARCHIVED_ZIP_SHA256)
    try:
        changed = PinnedArchive(flat_zip, FLAT_SHA256)
        try:
            require(
                original.read("tested-commit.txt").decode().strip() == ARCHIVED_SOURCE
                and original.read("tested-tree.txt").decode().strip() == ARCHIVED_TREE
                and changed.read("auditor-commit.txt").decode().strip() == FLAT_SOURCE
                and changed.read("auditor-tree.txt").decode().strip() == FLAT_TREE,
                "original generation source/tree or flat experiment source drift",
            )
            cases = fixed_frozen_cases(
                original.json("comparison/preregistered.json"),
                original.jsonl("comparison/policy-predictions.jsonl"),
            )
            sys = _static_system(changed.read("source/selector_answering.py"))
            result = review_copied_markers(
                cases, changed.jsonl("experiment/flat-answers.jsonl"), sys,
            )
            previous = changed.json("experiment/flat-vs-json-evaluation.json")
            require(previous["planned_questions"] == 32
                    and previous["only_user_payload_format_changed"] is True
                    and previous["frozen_reader_model_and_system_prompt_unchanged"] is True
                    and previous["semantic_citation_precision"] is None
                    and previous["production_accepted"] is False,
                    "original scored flat-format report incompatible")
            require(all(
                previous["phases"][phase]["flat_structural_citation_markers"]
                == result["phases"][phase]["structural_markers"]
                for phase in PHASES
            ), "published flat-format citation census was rewritten")
            result["archive_reconciliation"] = dict(
                strict_zip_sha256=original.sha256,
                strict_sha256sum_members=original.manifest_entries,
                flat_zip_sha256=changed.sha256,
                flat_sha256sum_members=changed.manifest_entries,
            )
            return result
        finally:
            changed.close()
    finally:
        original.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", type=Path, required=True)
    parser.add_argument("--flat", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.strict, args.flat)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False, sort_keys=True,
                  allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"},
                     ensure_ascii=False, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
