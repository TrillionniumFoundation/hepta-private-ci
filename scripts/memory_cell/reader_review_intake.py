"""PRIVATE reconciliation of returned Reader review forms, never an approval gate.

No model calls, human judgments, signature creation or source-owner authority.
All inputs must be independently authenticated by an operator outside this code.
Disagreements, partial answers and missing review records can NEVER be voted
into a positive Reader gate. Real forms/packets must not be uploaded to CI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from reader_originals_attestation import (
    load_strict_json_file,
    canonical_sha,
    has_answer_beyond_evidence_labels,
    read_no_symlink_file,
    NONCANONICAL_CITE,
    _datetime,
)
from reader_review_handoff import (
    _private_output_directory,
    _write_private,
    _write_private_lines,
)
from reader_review_ledger import CONDITIONS

RECEIPT_SCHEMA = "hepta.reader.blinded-review-handoff.v1"
INTAKE_SCHEMA = "hepta.reader.private-review-intake.v1"
QUESTION_KEYS = frozenset(
    (
        "ticket",
        "question",
        "question_observed_at",
        "raw_reader_answer",
        "evidence",
        "cited_labels",
        "candidate_is_approved",
        "review_judgments_provided",
    )
)
MAP_KEYS = frozenset(("ticket", "item_id", "condition", "exact_provenance"))
FORM_KEYS = frozenset(
    (
        "ticket",
        "grounded_and_cited",
        "exact_refusal",
        "cited_semantically_supported",
        "reviewer_notes",
    )
)
VERDICT_KEYS = ("grounded_and_cited", "exact_refusal", "cited_semantically_supported")
FILES = (
    "review-questions.jsonl",
    "reviewer-blank-form.jsonl",
    "operator-private-map.jsonl",
)
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
TICKET_RE = re.compile(r"[0-9a-f]{32}\Z")
LABEL_RE = re.compile(r"\[E([0-9]+)\]", re.I)
MAX_FILE_BYTES = 96 * 1024 * 1024
MAX_RECORDS = 40000
ABSTAIN = "I do not have enough evidence."


def _sha(value):
    return type(value) is str and SHA_RE.fullmatch(value) is not None


def _file(path, pin):
    """Read bounded, private, regular UTF-8 input with independent SHA pin."""
    if not _sha(pin):
        raise ValueError("an out-of-band raw-file SHA256 pin is required")
    path = Path(path)
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError("review packet path has symlink")
    raw = read_no_symlink_file(path, MAX_FILE_BYTES, private=True)
    if not raw or len(raw) > MAX_FILE_BYTES or hashlib.sha256(raw).hexdigest() != pin:
        raise ValueError("review input raw-file pin or byte budget mismatch")
    return raw


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate key in private review record")
        result[key] = value
    return result


def _nonfinite(_):
    raise ValueError("nonfinite review value")


def _json_lines(path, pin):
    raw = _file(path, pin)
    if not raw.endswith(b"\n"):
        raise ValueError("review JSONL must end with newline")
    lines = raw.splitlines()
    if not 1 <= len(lines) <= MAX_RECORDS:
        raise ValueError("review positions exceed bound")
    try:
        rows = [
            json.loads(
                line.decode("utf-8", "strict"),
                object_pairs_hook=_pairs,
                parse_constant=_nonfinite,
            )
            for line in lines
        ]
    except (UnicodeError, ValueError) as error:
        raise ValueError("invalid or ambiguous private review JSONL") from error
    if any(type(row) is not dict for row in rows):
        raise ValueError("review JSONL rows must be objects")
    return rows


def _index(rows, keys, *, name):
    indexed = {}
    for row in rows:
        if (
            set(row) != keys
            or type(row.get("ticket")) is not str
            or not TICKET_RE.fullmatch(row["ticket"])
        ):
            raise ValueError("invalid " + name + " ticket/schema")
        ticket = row["ticket"]
        if ticket in indexed:
            raise ValueError("duplicate " + name + " ticket")
        indexed[ticket] = row
    return indexed


def verified_handoff(directory, *, receipt_pin):
    """Replay a private handoff; it still does NOT authenticate the producer."""
    directory = Path(directory)
    if (
        directory.is_symlink()
        or any(p.is_symlink() for p in directory.parents)
        or not directory.is_dir()
        or directory.stat().st_mode & 0o077
    ):
        raise ValueError("operator handoff directory must be private and non-symlink")
    _file(directory / "handoff-receipt.json", receipt_pin)
    receipt = load_strict_json_file(
        directory / "handoff-receipt.json",
        expected_file_sha256=receipt_pin,
        require_pin=True,
    )
    if (
        receipt.get("schema") != RECEIPT_SCHEMA
        or receipt.get("reviewer_verdicts_filled") != 0
        or receipt.get("reviewer_signatures") != 0
        or receipt.get("independent_human_adjudication_obtained") is not False
        or receipt.get("production_accepted") is not False
        or receipt.get("source_producer_identity_authenticated_by_code") is not False
        or not _sha(receipt.get("original_file_sha256"))
        or not _sha(receipt.get("canonical_originals_sha256"))
        or type(receipt.get("written_file_sha256")) is not dict
        or set(receipt["written_file_sha256"]) != set(FILES)
    ):
        raise ValueError("unregistered or fabricated handoff approval receipt")
    if set(p.name for p in directory.iterdir()) != set(FILES) | {
        "handoff-receipt.json"
    }:
        raise ValueError("unexpected or missing private handoff file")
    files = {
        name: _json_lines(directory / name, receipt["written_file_sha256"][name])
        for name in FILES
    }
    work = _index(files[FILES[0]], QUESTION_KEYS, name="question")
    blanks = _index(files[FILES[1]], FORM_KEYS, name="blank-form")
    maps = _index(files[FILES[2]], MAP_KEYS, name="operator-map")
    tickets = set(work)
    if (
        tickets != set(blanks)
        or tickets != set(maps)
        or receipt.get("review_positions") != len(tickets)
        or receipt.get("cohort_size") * len(CONDITIONS) != len(tickets)
    ):
        raise ValueError("handoff ticket census is incomplete")
    by_question = {}
    visible_questions = {}
    visible_sources = {}
    visible_source_sets = {}
    for ticket in tickets:
        view, blank, link = work[ticket], blanks[ticket], maps[ticket]
        # Recheck reviewer-visible question fields across all four blinded
        # conditions. A file/receipt pin proves bytes, not that the reviewer
        # was shown the same question as the separately pinned source ledger.
        if (
            type(view["question"]) is not str
            or not view["question"].strip()
            or len(view["question"].encode("utf-8")) > 16384
            or type(view["question_observed_at"]) is not str
            or not view["question_observed_at"].strip()
            or len(view["question_observed_at"].encode("utf-8")) > 128
        ):
            raise ValueError("invalid reviewer-visible question or observation time")
        try:
            question_time = _datetime(view["question_observed_at"])
        except (ValueError, TypeError, OverflowError) as error:
            raise ValueError("invalid reviewer-visible question time") from error
        if (
            any(blank[key] is not None for key in VERDICT_KEYS)
            or blank["reviewer_notes"] is not None
            or view["candidate_is_approved"] is not False
            or view["review_judgments_provided"] is not False
            or type(view["raw_reader_answer"]) is not str
            or not view["raw_reader_answer"].strip()
            or type(view["evidence"]) is not list
            or type(view["cited_labels"]) is not list
        ):
            raise ValueError("handoff contained a purported existing review")
        if (
            type(link["item_id"]) is not str
            or not link["item_id"]
            or link["condition"] not in CONDITIONS
            or type(link["exact_provenance"]) is not dict
        ):
            raise ValueError("unregistered operator ticket/provenance")
        expected_proof_keys = {
            "item_id",
            "condition",
            "question_sha256",
            "prompt_input_ids_sha256",
            "raw_answer_sha256",
            "delivered_source_sha256",
            "cited_source_sha256",
        }
        proof = link["exact_provenance"]
        if (
            set(proof) != expected_proof_keys
            or proof["item_id"] != link["item_id"]
            or proof["condition"] != link["condition"]
            or any(
                not _sha(proof[key])
                for key in (
                    "question_sha256",
                    "prompt_input_ids_sha256",
                    "raw_answer_sha256",
                )
            )
            or proof["raw_answer_sha256"] != canonical_sha(view["raw_reader_answer"])
        ):
            raise ValueError("handoff provenance does not match original answer")
        evidence = view["evidence"]
        if (
            len(evidence) > 64
            or any(
                type(e) is not dict
                or set(e) != {"label", "excerpt", "observed_at", "source_fingerprint"}
                for e in evidence
            )
            or any(
                e["label"] != "E" + str(i + 1) or not _sha(e["source_fingerprint"])
                for i, e in enumerate(evidence)
            )
            or proof["delivered_source_sha256"]
            != [e["source_fingerprint"] for e in evidence]
        ):
            raise ValueError("handoff source labels/fingerprints are unbound")
        fingerprints = [e["source_fingerprint"] for e in evidence]
        if len(set(fingerprints)) != len(fingerprints):
            raise ValueError("duplicate reviewer-visible source fingerprint")
        visible_source_sets.setdefault(link["item_id"], {})[link["condition"]] = set(
            fingerprints
        )
        question = (
            view["question"],
            view["question_observed_at"],
            proof["question_sha256"],
        )
        qid = link["item_id"]
        if qid in visible_questions and visible_questions[qid] != question:
            raise ValueError(
                "reviewer-visible question changed across blinded conditions"
            )
        visible_questions[qid] = question
        for entry in evidence:
            if (
                type(entry["excerpt"]) is not str
                or not entry["excerpt"].strip()
                or len(entry["excerpt"].encode("utf-8")) > 2 * 1024 * 1024
                or type(entry["observed_at"]) is not str
                or not entry["observed_at"].strip()
                or len(entry["observed_at"].encode("utf-8")) > 128
            ):
                raise ValueError("invalid reviewer-visible source excerpt or time")
            try:
                source_time = _datetime(entry["observed_at"])
            except (ValueError, TypeError, OverflowError) as error:
                raise ValueError("invalid reviewer-visible source time") from error
            if source_time > question_time:
                raise ValueError("future reviewer-visible source time")
            visible = (entry["excerpt"], entry["observed_at"])
            fp = entry["source_fingerprint"]
            if fp in visible_sources and visible_sources[fp] != visible:
                raise ValueError(
                    "same source fingerprint displays inconsistent evidence"
                )
            visible_sources[fp] = visible
        if NONCANONICAL_CITE.search(view["raw_reader_answer"]):
            raise ValueError("noncanonical reviewer-visible source citation label")
        citation_labels = ["E" + x for x in LABEL_RE.findall(view["raw_reader_answer"])]
        if citation_labels != view["cited_labels"]:
            raise ValueError("handoff cited labels differ from original answer")
        cited_hashes = []
        for label in citation_labels:
            idx = int(label[1:]) - 1
            if not 0 <= idx < len(evidence):
                raise ValueError("handoff citation not delivered")
            hash_value = evidence[idx]["source_fingerprint"]
            if hash_value not in cited_hashes:
                cited_hashes.append(hash_value)
        if proof["cited_source_sha256"] != cited_hashes:
            raise ValueError("handoff cited provenance mismatch")
        by_question.setdefault(link["item_id"], set()).add(link["condition"])
    if len(by_question) != receipt["cohort_size"] or any(
        items != set(CONDITIONS) for items in by_question.values()
    ):
        raise ValueError("handoff original question/condition census changed")
    # Re-pin-safe structural validation: a reviewer must never be shown
    # replacement evidence in a purported premise-removal intervention.
    # This does not authenticate the original producer or authorize verdicts.
    for arms in visible_source_sets.values():
        if (
            arms["no_evidence"]
            or not arms["human_sufficient"]
            or not arms["critical_premise_removed"] < arms["human_sufficient"]
        ):
            raise ValueError(
                "reviewer-visible evidence intervention not strictly nested"
            )
    return dict(views=work, maps=maps, receipt=receipt)


def _reviewed_forms(path, pin, tickets, views):
    forms = _index(_json_lines(path, pin), FORM_KEYS, name="returned-form")
    if set(forms) != tickets:
        raise ValueError("reviewer submission has missing/extra tickets")
    for ticket, answer in forms.items():
        values = [answer[k] for k in VERDICT_KEYS]
        if any(type(v) is not bool and v is not None for v in values):
            raise ValueError("reviewer verdict must be true/false or unknown")
        note = answer["reviewer_notes"]
        if note is not None and (
            type(note) is not str or len(note.encode("utf-8")) > 4096
        ):
            raise ValueError("reviewer note exceeds private text budget")
        if answer["grounded_and_cited"] is True:
            if not views[ticket]["cited_labels"]:
                raise ValueError("claimed grounded answer lacks cited support")
            # A positive grounded answer is not complete when source support
            # or the non-refusal verdict has not actually been judged. The
            # signed gate remains separate and cannot be made by this intake.
            if answer["cited_semantically_supported"] is not True:
                raise ValueError(
                    "grounded answer requires affirmative cited-source support"
                )
            if answer["exact_refusal"] is not False:
                raise ValueError("grounded answer requires explicit non-refusal review")
        if (
            answer["cited_semantically_supported"] is True
            and not views[ticket]["cited_labels"]
        ):
            raise ValueError("cited support claimed without citations")
        if (
            answer["grounded_and_cited"] is True
            or answer["cited_semantically_supported"] is True
        ) and not has_answer_beyond_evidence_labels(views[ticket]["raw_reader_answer"]):
            raise ValueError(
                "positive reviewed answer contains only source labels or refusal"
            )
        if answer["grounded_and_cited"] is True and answer["exact_refusal"] is True:
            raise ValueError("grounded answer and refusal cannot both be true")
        if type(answer["exact_refusal"]) is bool and answer["exact_refusal"] != (
            views[ticket]["raw_reader_answer"] == ABSTAIN
        ):
            raise ValueError("reviewer exact-refusal verdict disagrees with raw answer")
    return forms


def reconcile_handoff(
    handoff,
    reviewer_one,
    reviewer_two,
    output,
    *,
    receipt_pin,
    first_pin,
    second_pin,
    first_id,
    second_id,
):
    """Reconcile two UNSIGNED submissions; leave the actual Reader gate blocked."""
    if (
        any(
            type(name) is not str
            or re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", name) is None
            for name in (first_id, second_id)
        )
        or first_id == second_id
    ):
        raise ValueError("distinct operator-verified reviewer names required")
    if Path(reviewer_one) == Path(reviewer_two):
        raise ValueError("two separate reviewer form files required")
    packet = verified_handoff(handoff, receipt_pin=receipt_pin)
    tickets = set(packet["views"])
    first = _reviewed_forms(reviewer_one, first_pin, tickets, packet["views"])
    second = _reviewed_forms(reviewer_two, second_pin, tickets, packet["views"])
    # Two distinct paths can alias the SAME inode through hard links. Reject
    # the alias even when its separately supplied SHA and claimed IDs differ.
    # Two independently materialized but byte-identical files remain permitted,
    # and neither case authenticates the human reviewers.
    if Path(reviewer_one).samefile(reviewer_two):
        raise ValueError("two reviewer submissions reference one filesystem inode")
    comparisons = []
    counts = dict(agreed=0, disputed=0, incomplete=0)
    for ticket in sorted(tickets):
        left = [first[ticket][key] for key in VERDICT_KEYS]
        right = [second[ticket][key] for key in VERDICT_KEYS]
        if any(type(v) is not bool for v in (*left, *right)):
            status = "incomplete"
        elif left != right:
            status = "disputed"
        else:
            status = "agreed"
        counts[status] += 1
        link = packet["maps"][ticket]
        comparisons.append(
            dict(
                ticket=ticket,
                item_id=link["item_id"],
                condition=link["condition"],
                first_verdict=dict(zip(VERDICT_KEYS, left, strict=True)),
                second_verdict=dict(zip(VERDICT_KEYS, right, strict=True)),
                status=status,
                externally_authenticated=False,
            )
        )
    output = Path(output)
    if output.is_symlink() or any(p.is_symlink() for p in output.parents):
        raise ValueError("review reconciliation output path has symlink")
    with _private_output_directory(output) as directory_fd:
        digest = _write_private_lines(
            "operator-private-comparison.jsonl", comparisons, directory_fd=directory_fd
        )
        receipt = dict(
            schema=INTAKE_SCHEMA,
            handoff_receipt_sha256=receipt_pin,
            original_file_sha256=packet["receipt"]["original_file_sha256"],
            original_question_count=packet["receipt"]["cohort_size"],
            planned_positions=len(tickets),
            reviewer_ids_claimed=[first_id, second_id],
            reviewer_form_sha256=[first_pin, second_pin],
            identical_unverified_review_bytes=(first_pin == second_pin),
            **counts,
            comparison_file_sha256=digest,
            both_reviewers_externally_authenticated=False,
            independent_human_judgment_established=False,
            cryptographic_review_signatures=0,
            review_approval_produced=False,
            production_accepted=False,
            neural_calls=0,
            next_step="operator-verify-reviewers-resolve-disagreements-and-sign-original-case-ledger",
        )
        _write_private(
            "reconciliation-receipt.json", receipt, directory_fd=directory_fd
        )
    return dict(
        positions=len(tickets),
        **counts,
        review_approval_produced=False,
        production_accepted=False,
        neural_calls=0,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("handoff_dir", type=Path)
    parser.add_argument("first_completed_form", type=Path)
    parser.add_argument("second_completed_form", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--handoff-receipt-sha256", required=True)
    parser.add_argument("--first-form-sha256", required=True)
    parser.add_argument("--second-form-sha256", required=True)
    parser.add_argument("--first-reviewer", required=True)
    parser.add_argument("--second-reviewer", required=True)
    args = parser.parse_args()
    result = reconcile_handoff(
        args.handoff_dir,
        args.first_completed_form,
        args.second_completed_form,
        args.output_dir,
        receipt_pin=args.handoff_receipt_sha256,
        first_pin=args.first_form_sha256,
        second_pin=args.second_form_sha256,
        first_id=args.first_reviewer,
        second_id=args.second_reviewer,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
