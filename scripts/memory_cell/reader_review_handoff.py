"""Prepare PRIVATE blinded Reader review requests from an externally pinned original.

NO human verdicts, simulated approvals, signing keys, model calls or automatic
Cell admission. The operator, NOT this software, authenticates the source
producer, distributes packets and approves independent human reviewers.
Never upload real generated packets to public CI artifacts or GitHub.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from reader_originals_attestation import (
    CASE_KEYS,
    CITE,
    EXACT_REFUSAL,
    SCHEMA,
    audit_originals,
    canonical_sha,
    load_strict_json_file,
    source_fingerprint,
)
from reader_review_ledger import CONDITIONS

FIELDS = frozenset(("schema", "cohort", "model_binding", "items"))
MAX_QUESTIONS = 10000


def prepare_cases(originals):
    """Validate a COMPLETE original-source census without manufacturing verdicts."""
    if (
        type(originals) is not dict
        or set(originals) != FIELDS
        or originals["schema"] != SCHEMA
    ):
        raise ValueError("unregistered original Reader review source")
    cohort = originals["cohort"]
    if (
        type(cohort) is not list
        or not 1 <= len(cohort) <= MAX_QUESTIONS
        or any(type(q) is not str or not q for q in cohort)
        or len(set(cohort)) != len(cohort)
    ):
        raise ValueError("incomplete or duplicate original review cohort")
    if type(originals["model_binding"]) is not dict:
        raise ValueError("missing frozen Reader identity")
    rows = originals["items"]
    expected = {(qid, arm) for qid in cohort for arm in CONDITIONS}
    if type(rows) is not list or len(rows) != len(expected):
        raise ValueError("missing original question-condition positions")
    by_key, ledger = {}, []
    for row in rows:
        if type(row) is not dict or set(row) != CASE_KEYS:
            raise ValueError("unregistered original case shape")
        key = (row["item_id"], row["condition"])
        if (
            type(key[0]) is not str
            or type(key[1]) is not str
            or key not in expected
            or key in by_key
        ):
            raise ValueError("duplicate or unexpected original case")
        sources = row["delivered_sources"]
        if type(sources) is not list or len(sources) > 64:
            raise ValueError("invalid delivered original evidence")
        answer = row["raw_answer"]
        if type(answer) is not str:
            raise ValueError("missing original raw answer")
        fingerprints = [source_fingerprint(s) for s in sources]
        cited = []
        for match in CITE.finditer(answer):
            position = int(match[1])
            if not 1 <= position <= len(sources):
                raise ValueError("unknown Reader citation label")
            fingerprint = fingerprints[position - 1]
            if fingerprint not in cited:
                cited.append(fingerprint)
        ledger.append(
            dict(
                item_id=key[0],
                condition=key[1],
                question_sha256=canonical_sha(row["question_record"]),
                prompt_input_ids_sha256=canonical_sha(row["input_ids"]),
                raw_answer_sha256=canonical_sha(answer),
                delivered_source_sha256=fingerprints,
                cited_source_sha256=cited,
            )
        )
        by_key[key] = row
    if set(by_key) != expected:
        raise ValueError("original review case census mismatch")
    # Only the literal-refusal predicate is mechanically computable from the
    # original Reader bytes. Use it for the *internal* provenance check, never
    # populate the human review ledger or blank reviewer verdict forms.
    # Actual gate admission still requires separately signed review verdicts.
    mechanical_rows = [
        dict(
            item,
            exact_refusal=(
                by_key[item["item_id"], item["condition"]]["raw_answer"]
                == EXACT_REFUSAL
            ),
        )
        for item in ledger
    ]
    reason = audit_originals(
        cohort, originals["model_binding"], mechanical_rows, originals
    )
    if reason is not None:
        raise ValueError("original source provenance invalid: " + reason)
    ledger_by_key = {(r["item_id"], r["condition"]): r for r in ledger}
    for qid in cohort:
        hashes = {ledger_by_key[qid, arm]["question_sha256"] for arm in CONDITIONS}
        if len(hashes) != 1:
            raise ValueError("question changed between review conditions")
        full = set(ledger_by_key[qid, "human_sufficient"]["delivered_source_sha256"])
        removed = set(
            ledger_by_key[qid, "critical_premise_removed"]["delivered_source_sha256"]
        )
        # The removal arm must be a STRICT SUBSET of the sufficient arm.
        # Merely dropping one fact while introducing a different fact would
        # confound a source-withholding experiment despite a full census.
        if not full or not removed < full:
            raise ValueError("sufficient/removed provenance not differentiated")
        if by_key[qid, "no_evidence"]["delivered_sources"]:
            raise ValueError("no-evidence condition not empty")
    return by_key, ledger_by_key


@contextmanager
def _private_output_directory(path):
    """Create one private directory, then keep its no-follow FD for EVERY write.

    Path-based writes after mkdir() would reopen an ancestor an adversary
    could swap to a symlink. Directory-FD-relative O_EXCL writes stay inside
    the directory inode first opened, even if its pathname changes.
    A locally writable/swap-capable parent still requires operator control.
    """
    dest = Path(path)
    if (
        ".." in dest.parts
        or not dest.name
        or not hasattr(os, "O_NOFOLLOW")
        or not hasattr(os, "O_DIRECTORY")
    ):
        raise ValueError("private output requires bounded POSIX no-follow path")
    if dest.is_symlink() or any(p.is_symlink() for p in dest.parents):
        raise ValueError("symlink in private output path")
    absolute_parent = Path(os.path.abspath(os.fspath(dest.parent)))
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    parent_fd, output_fd = None, None
    try:
        parent_fd = os.open(os.sep, flags)
        for component in absolute_parent.parts[1:]:
            next_fd = os.open(component, flags, dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = next_fd
        # Keep the exact parent inode open through creation and all writes.
        # Existing destinations remain a FileExistsError; never overwrite.
        os.mkdir(dest.name, mode=0o700, dir_fd=parent_fd)
        output_fd = os.open(dest.name, flags, dir_fd=parent_fd)
        info = os.fstat(output_fd)
        if (
            not stat.S_ISDIR(info.st_mode)
            or stat.S_IMODE(info.st_mode) & 0o077
            or info.st_uid != os.geteuid()
        ):
            raise ValueError("private output must be an owner-only directory")
        yield output_fd
        os.fsync(output_fd)
    except FileExistsError:
        raise
    except OSError as error:
        raise ValueError("symlink or inaccessible private output directory") from error
    finally:
        if output_fd is not None:
            os.close(output_fd)
        if parent_fd is not None:
            os.close(parent_fd)


def _write_private_bytes(name, raw, *, directory_fd):
    """Write exclusively beneath the already opened private directory."""
    if (
        type(name) is not str
        or not name
        or name in (".", "..")
        or Path(name).name != name
        or "/" in name
        or "\\" in name
    ):
        raise ValueError("private output filename must be a single component")
    fd = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory_fd,
    )
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()


def _write_private(name, data, *, directory_fd):
    raw = (
        json.dumps(
            data,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    return _write_private_bytes(name, raw, directory_fd=directory_fd)


def _write_private_lines(name, rows, *, directory_fd):
    raw = "".join(
        json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
        for row in rows
    ).encode("utf-8")
    return _write_private_bytes(name, raw, directory_fd=directory_fd)


def prepare_handoff(originals, *, source_file_sha256, output, salt=None):
    """Emit review QUESTIONS, NOT review judgments or an approval artifact.

    The operator-private identity map remains separate from a condition-blinded
    reviewer view. A randomized ID/order reduces arm visibility but DOES NOT
    guarantee blinding to semantic differences in the evidence itself.
    """
    if (
        type(source_file_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", source_file_sha256) is None
    ):
        raise ValueError("externally pinned original FILE SHA256 required")
    cases, ledger = prepare_cases(originals)
    if salt is None:
        salt = os.urandom(32)
    if type(salt) is not bytes or len(salt) != 32:
        raise ValueError("private 256-bit blinding salt required")
    reviewer_views, operator_map, verdict_forms = [], [], []
    for key, row in cases.items():
        ticket = canonical_sha(
            ["hepta.review-ticket.v1", salt.hex(), source_file_sha256, key[0], key[1]]
        )[:32]
        evidence = []
        for i, source in enumerate(row["delivered_sources"], 1):
            raw = source["content"].encode("utf-8", "strict")
            evidence.append(
                dict(
                    label="E" + str(i),
                    excerpt=raw[source["start"] : source["end"]].decode(
                        "utf-8", "strict"
                    ),
                    observed_at=source["observed_at"],
                    source_fingerprint=ledger[key]["delivered_source_sha256"][i - 1],
                )
            )
        cited = ["E" + str(int(m[1])) for m in CITE.finditer(row["raw_answer"])]
        reviewer_views.append(
            dict(
                ticket=ticket,
                question=row["question_record"]["content"],
                question_observed_at=row["question_record"]["observed_at"],
                raw_reader_answer=row["raw_answer"],
                evidence=evidence,
                cited_labels=cited,
                candidate_is_approved=False,
                review_judgments_provided=False,
            )
        )
        operator_map.append(
            dict(
                ticket=ticket,
                item_id=key[0],
                condition=key[1],
                exact_provenance=ledger[key],
            )
        )
        verdict_forms.append(
            dict(
                ticket=ticket,
                grounded_and_cited=None,
                exact_refusal=None,
                cited_semantically_supported=None,
                reviewer_notes=None,
            )
        )
    if len({v["ticket"] for v in reviewer_views}) != len(cases):
        raise ValueError("blinding ticket collision")
    reviewer_views.sort(key=lambda r: r["ticket"])
    operator_map.sort(key=lambda r: r["ticket"])
    verdict_forms.sort(key=lambda r: r["ticket"])
    dest = Path(output)
    if dest.is_symlink() or any(parent.is_symlink() for parent in dest.parents):
        raise ValueError("symlink in private handoff output path")
    with _private_output_directory(dest) as directory_fd:
        file_hashes = {
            "review-questions.jsonl": _write_private_lines(
                "review-questions.jsonl", reviewer_views, directory_fd=directory_fd
            ),
            "reviewer-blank-form.jsonl": _write_private_lines(
                "reviewer-blank-form.jsonl", verdict_forms, directory_fd=directory_fd
            ),
            "operator-private-map.jsonl": _write_private_lines(
                "operator-private-map.jsonl", operator_map, directory_fd=directory_fd
            ),
        }
        _write_private(
            "handoff-receipt.json",
            dict(
                schema="hepta.reader.blinded-review-handoff.v1",
                original_file_sha256=source_file_sha256,
                canonical_originals_sha256=canonical_sha(originals),
                cohort_size=len(originals["cohort"]),
                review_positions=len(reviewer_views),
                written_file_sha256=file_hashes,
                reviewer_verdicts_filled=0,
                reviewer_signatures=0,
                source_producer_identity_authenticated_by_code=False,
                independent_human_adjudication_obtained=False,
                production_accepted=False,
                neural_calls=0,
                private_source_bytes_require_operator_authorization=True,
            ),
            directory_fd=directory_fd,
        )
    return dict(
        positions=len(reviewer_views),
        independent_reviews=0,
        neural_calls=0,
        production_accepted=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("originals", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--original-file-sha256", required=True)
    args = parser.parse_args()
    originals = load_strict_json_file(
        args.originals,
        expected_file_sha256=args.original_file_sha256,
        require_pin=True,
    )
    result = prepare_handoff(
        originals, source_file_sha256=args.original_file_sha256, output=args.output
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
