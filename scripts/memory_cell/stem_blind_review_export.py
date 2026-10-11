"""Export an unreviewed, source-pinned 32-question semantic worklist.

No target annotations, privileged Oracle, label-dependent scores or models
are opened. Reviewer packet and owner-only provenance are separate files.
Requires a separately authenticated, genuinely independent review to finish.
"""

import argparse
import json
from pathlib import Path

from native import digest
from stem_audit_archive import PinnedArchive, require
from stem_blind_review_packet import make_blind_review_packet

SOURCE = "cb9e98365b5f46e00fb2693f548a7215b1ed1145"
TREE = "022c9aa8abc095c91ef744644329aaed12564859"
ZIP_SHA = "be3393f448993451c7860e8867e28a79f5fb7f95d5773f79ed55b30d12a84776"


def _write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(
            value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
        )
        stream.write("\n")


def _jsonl(path, records):
    with path.open("x", encoding="utf-8") as stream:
        for row in records:
            stream.write(
                json.dumps(row, sort_keys=True, ensure_ascii=False, allow_nan=False)
                + "\n"
            )


def export_worklist(archive_path: Path, dest: Path):
    archive = PinnedArchive(archive_path, ZIP_SHA)
    try:
        require(
            archive.read("tested-commit.txt").decode().strip() == SOURCE,
            "actual pinned frozen Reader execution source moved",
        )
        require(
            archive.read("tested-tree.txt").decode().strip() == TREE,
            "actual pinned frozen Reader execution tree moved",
        )
        # NO scored-policy-attempts, answer targets, oracle diagnostics or
        # native ground-truth file is read by this exporter.
        plan = archive.json("comparison/preregistered.json")
        predictions = archive.jsonl("comparison/policy-predictions.jsonl")
        empty = archive.jsonl("comparison/reader-no-evidence.jsonl")
        require(plan["source_commit"] == SOURCE, "registered source identity changed")
        public, private = make_blind_review_packet(plan, predictions, empty)
        require(
            public["original_cases"] == len(public["reviewer_packets"]) == 32
            and public["reader_conditions"] == 64
            and public["no_gold_answers_read"] is True
            and public["semantic_citation_precision"] is None
            and public["production_accepted"] is False
            and private["independent_reviewer_identity_verified"] is False,
            "incomplete or falsely independently certified review packet",
        )
        dest.mkdir(parents=True, exist_ok=False)
        worklist = public["reviewer_packets"]
        template = [
            dict(
                case_id=case["case_id"],
                condition_slot=condition["slot"],
                evidence_sufficient_for_question=None,
                answer_claims_supported_by_evidence=None,
                cited_spans_entailed=None,
                missing_provenance_or_unreviewable=None,
                reviewer_identity=None,
                reviewer_attestation=None,
                independently_authenticated=False,
            )
            for case in worklist
            for condition in case["conditions"]
        ]
        _jsonl(dest / "blind-question-answer-worklist.jsonl", worklist)
        _jsonl(dest / "unsigned-reviewer-return-template.jsonl", template)
        _write(dest / "private-owner-case-mapping.json", private)
        summary = dict(
            schema="hepta.stem-blind-review-handoff.v1",
            source_commit=SOURCE,
            source_tree=TREE,
            source_artifact_zip_sha256=archive.sha256,
            verified_artifact_manifest_entries=archive.manifest_entries,
            original_frozen_question_count=32,
            original_reader_condition_count=64,
            reviewer_worklist_digest=digest(worklist),
            unsigned_review_slots=len(template),
            actual_reviewer_verdicts=0,
            gold_answers_opened=False,
            pretrained_models_executed=False,
            source_selection_policy_changed=False,
            reviewer_credential_verified=False,
            independently_adjudicated_entailment=False,
            semantic_citation_precision=None,
            production_accepted=False,
        )
        _write(dest / "unreviewed-handoff-summary.json", summary)
        return summary
    finally:
        archive.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = export_worklist(args.archive, args.output)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
