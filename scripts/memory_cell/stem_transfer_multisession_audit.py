"""Read-only structural ceiling for fixed one-window LongMemEval transfers.

Uses archived post-policy frozen answers and pinned native SOURCE/ANNOTATION
records. The word 'support' denotes published document/session labels, NOT
human-verified necessity or window-level entailment. Zero model executions.
"""

import hashlib


def _hash(x):
    return hashlib.sha256(x.encode("utf-8")).hexdigest()


def audit_transfer_support(plan, policy_rows, native_rows):
    transfer = plan["questions"]["transfer"]
    if len(transfer) != 8 or len(set(transfer)) != 8:
        raise ValueError("original eight transfer question identities required")
    seen, native = set(), {}
    for row in native_rows:
        qid = "longmemeval:" + row["question_id"]
        if qid not in transfer:
            continue
        if qid in seen:
            raise ValueError("duplicate pinned transfer native question")
        seen.add(qid)
        sessions = row["haystack_session_ids"]
        required = row["answer_session_ids"]
        if (
            not isinstance(sessions, list)
            or not isinstance(required, list)
            or len(set(sessions)) != len(sessions)
            or any(not isinstance(x, str) or not x for x in sessions + required)
            or len(set(required)) != len(required)
            or not set(required).issubset(sessions)
            or not isinstance(row["answer"], str)
        ):
            raise ValueError("malformed native source support identity")
        native[qid] = row
    if seen != set(transfer):
        raise ValueError("missing exact pinned transfer native question")
    frozen = {}
    for row in policy_rows:
        if (
            row["stage"] != 48
            or row["arm"] != "frozen_rerank"
            or row["phase"] != "transfer"
        ):
            continue
        qid = row["question_id"]
        if qid not in transfer or qid in frozen:
            raise ValueError("unregistered or duplicate final frozen transfer attempt")
        if row["status"] not in ("succeeded", "failed"):
            raise ValueError("unknown original policy result")
        frozen[qid] = row
    if set(frozen) != set(transfer):
        raise ValueError("incomplete final frozen transfer census")
    out = []
    for qid in transfer:
        case, attempt = native[qid], frozen[qid]
        native_abs = qid.endswith("_abs")
        required = set(case["answer_session_ids"])
        receipt = attempt.get("receipt")
        if attempt["status"] == "succeeded" and not isinstance(receipt, dict):
            raise ValueError("missing completed frozen Reader evidence receipt")
        delivered = (
            receipt.get("delivered_evidence", []) if isinstance(receipt, dict) else []
        )
        if attempt["status"] == "succeeded":
            if not isinstance(delivered, list) or len(delivered) > 1:
                raise ValueError("frozen Reader exceeded registered one-window budget")
        elif delivered:
            raise ValueError("failed Reader cannot claim completed evidence delivery")
        source_ids = []
        for item in delivered:
            sid = item["original_id"].split("/")[-1]
            if (
                item["original_id"] != f"{qid}/{sid}"
                or sid not in case["haystack_session_ids"]
                or not isinstance(item.get("excerpt"), str)
                or len(item["excerpt"].encode("utf-8")) > 512
            ):
                raise ValueError("unbound or over-budget selected source excerpt")
            source_ids.append(sid)
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("duplicate delivered source identity")
        source_match = len(set(source_ids) & required)
        correct = attempt.get("source_choice_correct")
        if type(correct) is not int or correct not in (0, 1):
            raise ValueError("unscorable original native source choice")
        if attempt["status"] == "succeeded":
            expected_choice_correct = int(
                (not native_abs and source_match > 0)
                or (native_abs and attempt.get("selected") is None)
            )
            if correct != expected_choice_correct:
                raise ValueError(
                    "native source-choice scorer and delivered source disagree"
                )
        literal = (
            case["answer"].strip().casefold() in delivered[0]["excerpt"].casefold()
            if delivered and not native_abs and case["answer"].strip()
            else None
        )
        out.append(
            dict(
                question_id=qid,
                native_unanswerable=native_abs,
                annotated_distinct_support_sessions=len(required),
                multiple_annotated_support_sessions=len(required) > 1,
                reader_actual_success=attempt["status"] == "succeeded",
                delivered_window_count=len(delivered),
                required_sessions_delivered=source_match,
                cannot_deliver_all_annotated_sessions=(
                    len(required) > 1 and source_match < len(required)
                    if not native_abs and attempt["status"] == "succeeded"
                    else None
                ),
                native_document_support_selected=bool(source_match)
                if not native_abs
                else None,
                exact_answer_literal_in_excerpt=literal,
                answer_string_sha256=_hash(case["answer"]),
                gold_text_exported=False,
            )
        )
    answerable = [x for x in out if not x["native_unanswerable"]]
    chosen = [x for x in answerable if x["native_document_support_selected"]]
    return dict(
        schema="hepta.stem-native-transfer-one-window-ceiling.v1",
        unique_registered_transfer_questions=8,
        answerable_questions=len(answerable),
        unanswerable_questions=8 - len(answerable),
        answerable_with_multiple_annotated_sessions=sum(
            x["multiple_annotated_support_sessions"] for x in answerable
        ),
        answerable_with_native_support_selected=len(chosen),
        supporting_document_selected_but_multiple_sessions_required=sum(
            x["multiple_annotated_support_sessions"] for x in chosen
        ),
        supporting_document_selected_with_full_answer_literal_in_excerpt=sum(
            x["exact_answer_literal_in_excerpt"] is True for x in chosen
        ),
        original_reader_successes=sum(x["reader_actual_success"] for x in out),
        source_labels_not_independent_entailment=True,
        literal_nonmatch_does_not_establish_insufficient_semantic_evidence=True,
        all_required_sessions_not_guaranteed_necessary_for_answer=True,
        reader_weights_unchanged_and_not_executed=True,
        production_accepted=False,
        rows=out,
    )


def audit_pinned_native(native_path, original_zip, earlier_zip):
    """Recheck original source bytes and both complete archived model runs."""
    import json
    from stem_audit_archive import PinnedArchive, require
    from stem_archive_contrast import ORIGINAL, EARLIER_SUCCESS

    expected_native = "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442"
    if (
        native_path.is_symlink()
        or not native_path.is_file()
        or not 0 < native_path.stat().st_size <= 512 * 1024**2
    ):
        raise ValueError("bounded original LongMemEval source file required")
    with native_path.open("rb") as f:
        sha = hashlib.file_digest(f, "sha256").hexdigest()
    require(sha == expected_native, "native source bytes differ from pin")
    raw = json.loads(native_path.read_bytes())
    receipts = {}
    for key, path, origin in (
        ("original", original_zip, ORIGINAL),
        ("historically_complete", earlier_zip, EARLIER_SUCCESS),
    ):
        archive = PinnedArchive(path, origin[2])
        try:
            require(
                archive.read("tested-commit.txt").decode().strip() == origin[0],
                "original experiment source identity changed",
            )
            require(
                archive.read("tested-tree.txt").decode().strip() == origin[1],
                "original experiment tree identity changed",
            )
            plan = archive.json("comparison/preregistered.json")
            require(plan["source_commit"] == origin[0], "unregistered model execution")
            require(
                plan["dataset_sha256"]["longmemeval"] == sha,
                "LongMemEval source schema/bytes not same as model experiment",
            )
            results = audit_transfer_support(
                plan, archive.json("comparison/scored-policy-attempts.json"), raw
            )
            results.update(
                experiment_commit=origin[0],
                original_zip_sha256=origin[2],
                verified_zip_member_count=archive.manifest_entries,
                native_longmemeval_sha256=sha,
            )
            receipts[key] = results
        finally:
            archive.close()
    return receipts


def main():
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-longmemeval", required=True, type=Path)
    parser.add_argument("--original", required=True, type=Path)
    parser.add_argument("--historically-complete", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = audit_pinned_native(
        args.native_longmemeval, args.original, args.historically_complete
    )
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(
            report,
            handle,
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        handle.write(chr(10))
    print(
        json.dumps(
            {
                name: {key: value for key, value in receipt.items() if key != "rows"}
                for name, receipt in report.items()
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
